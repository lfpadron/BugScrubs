from __future__ import annotations

from pathlib import Path
import subprocess
import threading
import webbrowser

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Log, Static

from bugscrub.deploy_control import (
    CancelledError,
    DeployAppConfig,
    DeployContext,
    DeployControlError,
    DOCKER_LOGIN_URL,
    GCLOUD_LOGIN_URL,
    GCloudConfig,
    DockerHubConfig,
    StepSelection,
    build_selected_steps,
    create_default_context,
    load_control_config,
    run_selected_steps,
    save_control_config,
    shutdown_cloud_run_service,
)


class DeployControlApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        layout: horizontal;
        height: 1fr;
    }

    #sidebar {
        width: 42;
        padding: 1;
        border: solid $primary;
    }

    #main {
        padding: 1;
    }

    .section-title {
        text-style: bold;
        margin-top: 1;
    }

    .full-width {
        width: 1fr;
    }

    #action-row Button {
        margin-right: 1;
    }

    #status-box {
        border: round $accent;
        padding: 0 1;
        margin-bottom: 1;
    }

    #log {
        height: 1fr;
        border: round $secondary;
    }
    """

    BINDINGS = [
        ("ctrl+c", "cancel_or_exit", "Cancel/Exit"),
        ("ctrl+r", "run_selected", "Run"),
        ("ctrl+s", "shutdown_service", "Shutdown"),
    ]

    def __init__(self, repo_root: Path) -> None:
        super().__init__()
        self.repo_root = repo_root
        self.control_paths, self.context = create_default_context(repo_root)
        self.current_url = ""
        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._active_process: subprocess.Popen[str] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Label("Config", classes="section-title")
                yield Input(value=self.context.config.docker.username, id="docker-username", placeholder="Docker Hub user")
                yield Input(value=self.context.config.docker.image_name, id="image-name", placeholder="Image name")
                yield Input(value=self.context.tag, id="tag", placeholder="Tag")
                yield Input(value=self.context.config.gcloud.project_id, id="project-id", placeholder="GCP project")
                yield Input(value=self.context.config.gcloud.region, id="region", placeholder="Region")
                yield Input(value=self.context.config.gcloud.service_name, id="service-name", placeholder="Cloud Run service")
                yield Label(f"Config: {self.control_paths.config_path}", classes="section-title")
                yield Label(f"Secrets: {self.control_paths.secrets_path}")
                yield Button("Save config", id="save-config", variant="primary")
                yield Button("Open config folder", id="open-config-folder")
                yield Label("Auth helpers", classes="section-title")
                yield Button("Docker login", id="docker-login")
                yield Button("GCloud auth login", id="gcloud-login")
            with Vertical(id="main"):
                yield Static(self._status_text(), id="status-box")
                yield Label("Steps", classes="section-title")
                yield Checkbox("Git push current branch", value=False, id="step-git-push")
                yield Checkbox("Build Docker image", value=True, id="step-docker-build")
                yield Checkbox("Push image to Docker Hub", value=True, id="step-docker-push")
                yield Checkbox("Make Docker Hub repo public", value=True, id="step-docker-public")
                yield Checkbox("Deploy to Cloud Run", value=True, id="step-cloudrun-deploy")
                yield Checkbox("Make Cloud Run public", value=True, id="step-cloudrun-public")
                with Horizontal(id="action-row"):
                    yield Button("Run selected", id="run-selected", variant="success")
                    yield Button("Shutdown / Private", id="shutdown-service", variant="warning")
                    yield Button("Cancel / Exit", id="cancel-exit", variant="error")
                yield Label("Execution log", classes="section-title")
                yield Log(id="log", classes="full-width", auto_scroll=True)
        yield Footer()

    def on_mount(self) -> None:
        self._log("Deploy control center ready.")
        self._log(f"Repo root: {self.repo_root}")
        self._log(f"Docker image: {self.context.image_ref}")

    def action_cancel_or_exit(self) -> None:
        self._handle_cancel_or_exit()

    def action_run_selected(self) -> None:
        self._run_selected_steps()

    def action_shutdown_service(self) -> None:
        self._shutdown_service()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "save-config":
            self._save_config()
        elif button_id == "open-config-folder":
            self._open_config_folder()
        elif button_id == "docker-login":
            self._launch_external_auth(["docker", "login"], DOCKER_LOGIN_URL)
        elif button_id == "gcloud-login":
            self._launch_external_auth(["gcloud", "auth", "login"], GCLOUD_LOGIN_URL)
        elif button_id == "run-selected":
            self._run_selected_steps()
        elif button_id == "shutdown-service":
            self._shutdown_service()
        elif button_id == "cancel-exit":
            self._handle_cancel_or_exit()

    def _status_text(self) -> str:
        running = "Yes" if self._worker and self._worker.is_alive() else "No"
        url = self.current_url or "Not deployed yet"
        return (
            "BugScrub Deploy Control Center\n"
            f"Running job: {running}\n"
            f"Image: {self.context.image_ref}\n"
            f"Cloud Run URL: {url}"
        )

    def _refresh_status(self) -> None:
        self.query_one("#status-box", Static).update(self._status_text())

    def _selection_from_ui(self) -> StepSelection:
        return StepSelection(
            git_push=self.query_one("#step-git-push", Checkbox).value,
            docker_build=self.query_one("#step-docker-build", Checkbox).value,
            docker_push=self.query_one("#step-docker-push", Checkbox).value,
            docker_repo_public=self.query_one("#step-docker-public", Checkbox).value,
            cloud_run_deploy=self.query_one("#step-cloudrun-deploy", Checkbox).value,
            cloud_run_public=self.query_one("#step-cloudrun-public", Checkbox).value,
        )

    def _save_config(self) -> None:
        config = DeployAppConfig(
            docker=DockerHubConfig(
                username=self.query_one("#docker-username", Input).value.strip(),
                image_name=self.query_one("#image-name", Input).value.strip(),
                default_tag=self.query_one("#tag", Input).value.strip(),
                repo_name=self.query_one("#image-name", Input).value.strip(),
            ),
            gcloud=GCloudConfig(
                project_id=self.query_one("#project-id", Input).value.strip(),
                region=self.query_one("#region", Input).value.strip(),
                service_name=self.query_one("#service-name", Input).value.strip(),
            ),
            deploy=self.context.config.deploy,
        )
        save_control_config(self.control_paths, config)
        _, secrets = load_control_config(self.control_paths)
        self.context = DeployContext(
            repo_root=self.repo_root,
            config=config,
            secrets=secrets,
            tag=config.docker.default_tag,
        )
        self._log("Configuration saved.")
        self._refresh_status()

    def _open_config_folder(self) -> None:
        subprocess.Popen(
            ["explorer", str(self.control_paths.base_dir)],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        self._log(f"Opened config folder: {self.control_paths.base_dir}")

    def _launch_external_auth(self, command: list[str], fallback_url: str) -> None:
        try:
            subprocess.Popen(
                command,
                cwd=self.repo_root,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            self._log(f"Started external auth flow: {' '.join(command)}")
        except Exception as error:
            self._log(f"Could not launch auth command, opening browser instead: {error}")
            webbrowser.open(fallback_url)

    def _run_selected_steps(self) -> None:
        if self._worker and self._worker.is_alive():
            self._log("A job is already running.")
            return

        self._save_config()
        selection = self._selection_from_ui()
        selected_steps = build_selected_steps(selection)
        if not selected_steps:
            self._log("Select at least one step before running.")
            return

        self._cancel_event.clear()
        self._worker = threading.Thread(
            target=self._run_selected_steps_worker,
            args=(selection,),
            daemon=True,
        )
        self._worker.start()
        self._refresh_status()

    def _run_selected_steps_worker(self, selection: StepSelection) -> None:
        try:
            url = run_selected_steps(
                self.context,
                selection,
                logger=self._thread_log,
                command_runner=self._run_command,
                cancel_check=lambda: self._cancel_event.is_set(),
            )
            if url:
                self.current_url = url
            self._thread_log("Selected steps completed successfully.")
        except CancelledError as error:
            self._thread_log(str(error))
        except Exception as error:
            self._thread_log(f"Execution failed: {error}")
        finally:
            self.call_from_thread(self._refresh_status)

    def _shutdown_service(self) -> None:
        if self._worker and self._worker.is_alive():
            self._log("Wait for the current job to finish, or cancel it first.")
            return

        self._save_config()
        self._cancel_event.clear()
        self._worker = threading.Thread(target=self._shutdown_worker, daemon=True)
        self._worker.start()
        self._refresh_status()

    def _shutdown_worker(self) -> None:
        try:
            shutdown_cloud_run_service(
                self.context,
                logger=self._thread_log,
                command_runner=self._run_command,
            )
            self._thread_log("Shutdown completed.")
        except Exception as error:
            self._thread_log(f"Shutdown failed: {error}")
        finally:
            self.call_from_thread(self._refresh_status)

    def _handle_cancel_or_exit(self) -> None:
        if self._worker and self._worker.is_alive():
            self._cancel_event.set()
            if self._active_process is not None and self._active_process.poll() is None:
                try:
                    self._active_process.terminate()
                except Exception:
                    pass
            self._log("Cancellation requested.")
            return
        self.exit()

    def _thread_log(self, message: str) -> None:
        self.call_from_thread(self._log, message)

    def _log(self, message: str) -> None:
        self.query_one("#log", Log).write_line(message)

    def _run_command(self, command: list[str], cwd: Path | None) -> None:
        self.call_from_thread(self._log, f"$ {subprocess.list2cmdline(command)}")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self._active_process = process
        assert process.stdout is not None
        for line in process.stdout:
            if self._cancel_event.is_set():
                process.terminate()
                raise CancelledError("Deployment cancelled by the user.")
            self.call_from_thread(self._log, line.rstrip())

        return_code = process.wait()
        self._active_process = None
        if return_code != 0:
            raise DeployControlError(
                f"Command failed with exit code {return_code}: {subprocess.list2cmdline(command)}"
            )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    app = DeployControlApp(repo_root=repo_root)
    app.run()
    return 0
