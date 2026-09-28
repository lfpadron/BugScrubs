from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import tomllib
from typing import Callable

import requests


DOCKER_LOGIN_URL = "https://login.docker.com/activate"
GCLOUD_LOGIN_URL = "https://console.cloud.google.com/"


class DeployControlError(RuntimeError):
    """Base error for deploy control operations."""


class CancelledError(DeployControlError):
    """Raised when a running operation is cancelled."""


@dataclass(slots=True)
class DockerHubConfig:
    username: str
    image_name: str
    default_tag: str
    repo_name: str


@dataclass(slots=True)
class GCloudConfig:
    project_id: str
    region: str
    service_name: str


@dataclass(slots=True)
class DeployConfig:
    memory: str
    cpu: int
    concurrency: int
    max_instances: int
    min_instances: int
    timeout_seconds: int
    runtime_root: str
    duckdb_path: str


@dataclass(slots=True)
class SecretsConfig:
    docker_token: str


@dataclass(slots=True)
class DeployAppConfig:
    docker: DockerHubConfig
    gcloud: GCloudConfig
    deploy: DeployConfig


@dataclass(slots=True)
class ControlPaths:
    base_dir: Path
    config_path: Path
    secrets_path: Path


@dataclass(slots=True)
class StepSelection:
    git_push: bool = False
    docker_build: bool = True
    docker_push: bool = True
    docker_repo_public: bool = True
    cloud_run_deploy: bool = True
    cloud_run_public: bool = True


@dataclass(slots=True)
class DeployContext:
    repo_root: Path
    config: DeployAppConfig
    secrets: SecretsConfig
    tag: str

    @property
    def image_ref(self) -> str:
        return f"docker.io/{self.config.docker.username}/{self.config.docker.image_name}:{self.tag}"


def default_control_paths() -> ControlPaths:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data) / "bugscrub-deploy"
    else:
        base_dir = Path.home() / ".bugscrub-deploy"
    return ControlPaths(
        base_dir=base_dir,
        config_path=base_dir / "config.toml",
        secrets_path=base_dir / "secrets.toml",
    )


def ensure_control_files(paths: ControlPaths) -> None:
    paths.base_dir.mkdir(parents=True, exist_ok=True)

    if not paths.config_path.exists():
        paths.config_path.write_text(default_config_toml(), encoding="utf-8")
    if not paths.secrets_path.exists():
        paths.secrets_path.write_text(default_secrets_toml(), encoding="utf-8")


def default_config_toml() -> str:
    return """[docker]
username = "lfpadron"
image_name = "bugscrub-local-first"
default_tag = "cloudrun-v1"
repo_name = "bugscrub-local-first"

[gcloud]
project_id = "bugscrubs-t"
region = "us-central1"
service_name = "bugscrub-web"

[deploy]
memory = "2Gi"
cpu = 1
concurrency = 20
max_instances = 3
min_instances = 1
timeout_seconds = 900
runtime_root = "/tmp/bugscrub-runtime"
duckdb_path = "/tmp/bugscrub.duckdb"
"""


def default_secrets_toml() -> str:
    return """[docker]
token = "REPLACE_WITH_DOCKER_HUB_PAT"
"""


def load_control_config(paths: ControlPaths) -> tuple[DeployAppConfig, SecretsConfig]:
    ensure_control_files(paths)

    config_data = tomllib.loads(paths.config_path.read_text(encoding="utf-8"))
    secrets_data = tomllib.loads(paths.secrets_path.read_text(encoding="utf-8"))

    docker_data = dict(config_data.get("docker", {}))
    gcloud_data = dict(config_data.get("gcloud", {}))
    deploy_data = dict(config_data.get("deploy", {}))
    docker_secret_data = dict(secrets_data.get("docker", {}))

    config = DeployAppConfig(
        docker=DockerHubConfig(
            username=str(docker_data.get("username", "lfpadron")),
            image_name=str(docker_data.get("image_name", "bugscrub-local-first")),
            default_tag=str(docker_data.get("default_tag", "cloudrun-v1")),
            repo_name=str(docker_data.get("repo_name", docker_data.get("image_name", "bugscrub-local-first"))),
        ),
        gcloud=GCloudConfig(
            project_id=str(gcloud_data.get("project_id", "bugscrubs-t")),
            region=str(gcloud_data.get("region", "us-central1")),
            service_name=str(gcloud_data.get("service_name", "bugscrub-web")),
        ),
        deploy=DeployConfig(
            memory=str(deploy_data.get("memory", "2Gi")),
            cpu=int(deploy_data.get("cpu", 1)),
            concurrency=int(deploy_data.get("concurrency", 20)),
            max_instances=int(deploy_data.get("max_instances", 3)),
            min_instances=int(deploy_data.get("min_instances", 1)),
            timeout_seconds=int(deploy_data.get("timeout_seconds", 900)),
            runtime_root=str(deploy_data.get("runtime_root", "/tmp/bugscrub-runtime")),
            duckdb_path=str(deploy_data.get("duckdb_path", "/tmp/bugscrub.duckdb")),
        ),
    )
    secrets = SecretsConfig(
        docker_token=str(docker_secret_data.get("token", "")).strip(),
    )
    return config, secrets


def save_control_config(paths: ControlPaths, config: DeployAppConfig) -> None:
    ensure_control_files(paths)
    content = (
        "[docker]\n"
        f'username = "{_toml_escape(config.docker.username)}"\n'
        f'image_name = "{_toml_escape(config.docker.image_name)}"\n'
        f'default_tag = "{_toml_escape(config.docker.default_tag)}"\n'
        f'repo_name = "{_toml_escape(config.docker.repo_name)}"\n\n'
        "[gcloud]\n"
        f'project_id = "{_toml_escape(config.gcloud.project_id)}"\n'
        f'region = "{_toml_escape(config.gcloud.region)}"\n'
        f'service_name = "{_toml_escape(config.gcloud.service_name)}"\n\n'
        "[deploy]\n"
        f'memory = "{_toml_escape(config.deploy.memory)}"\n'
        f"cpu = {config.deploy.cpu}\n"
        f"concurrency = {config.deploy.concurrency}\n"
        f"max_instances = {config.deploy.max_instances}\n"
        f"min_instances = {config.deploy.min_instances}\n"
        f"timeout_seconds = {config.deploy.timeout_seconds}\n"
        f'runtime_root = "{_toml_escape(config.deploy.runtime_root)}"\n'
        f'duckdb_path = "{_toml_escape(config.deploy.duckdb_path)}"\n'
    )
    paths.config_path.write_text(content, encoding="utf-8")


def build_selected_steps(selection: StepSelection) -> list[str]:
    ordered: list[tuple[str, bool]] = [
        ("git_push", selection.git_push),
        ("docker_build", selection.docker_build),
        ("docker_push", selection.docker_push),
        ("docker_repo_public", selection.docker_repo_public),
        ("cloud_run_deploy", selection.cloud_run_deploy),
        ("cloud_run_public", selection.cloud_run_public),
    ]
    return [name for name, enabled in ordered if enabled]


def current_git_branch(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def create_default_context(repo_root: Path, *, tag: str | None = None) -> tuple[ControlPaths, DeployContext]:
    paths = default_control_paths()
    config, secrets = load_control_config(paths)
    resolved_tag = tag or config.docker.default_tag
    return paths, DeployContext(repo_root=repo_root, config=config, secrets=secrets, tag=resolved_tag)


def run_selected_steps(
    context: DeployContext,
    selection: StepSelection,
    *,
    logger: Callable[[str], None],
    command_runner: Callable[[list[str], Path | None], None],
    cancel_check: Callable[[], bool],
) -> str | None:
    last_url: str | None = None
    for step_name in build_selected_steps(selection):
        if cancel_check():
            raise CancelledError("Deployment cancelled by the user.")
        logger(f"[step] {step_name}")

        if step_name == "git_push":
            branch = current_git_branch(context.repo_root)
            command_runner(["git", "push", "--set-upstream", "origin", branch], context.repo_root)
        elif step_name == "docker_build":
            command_runner(["docker", "build", "-t", context.image_ref, "."], context.repo_root)
        elif step_name == "docker_push":
            command_runner(["docker", "push", context.image_ref], context.repo_root)
        elif step_name == "docker_repo_public":
            set_docker_hub_repository_visibility(context, is_private=False, logger=logger)
        elif step_name == "cloud_run_deploy":
            deploy_to_cloud_run(context, logger=logger, command_runner=command_runner)
            last_url = describe_cloud_run_url(context, logger=logger, command_runner=command_runner)
        elif step_name == "cloud_run_public":
            set_cloud_run_public(context, logger=logger, command_runner=command_runner)
            last_url = describe_cloud_run_url(context, logger=logger, command_runner=command_runner)
        else:
            raise DeployControlError(f"Unknown step: {step_name}")

    return last_url


def shutdown_cloud_run_service(
    context: DeployContext,
    *,
    logger: Callable[[str], None],
    command_runner: Callable[[list[str], Path | None], None],
) -> None:
    command_runner(
        [
            "gcloud",
            "run",
            "services",
            "remove-iam-policy-binding",
            context.config.gcloud.service_name,
            "--region",
            context.config.gcloud.region,
            "--member",
            "allUsers",
            "--role",
            "roles/run.invoker",
        ],
        context.repo_root,
    )
    logger("Cloud Run service was made private.")


def deploy_to_cloud_run(
    context: DeployContext,
    *,
    logger: Callable[[str], None],
    command_runner: Callable[[list[str], Path | None], None],
) -> None:
    command_runner(["gcloud", "config", "set", "project", context.config.gcloud.project_id], context.repo_root)
    command_runner(
        [
            "gcloud",
            "run",
            "deploy",
            context.config.gcloud.service_name,
            "--image",
            context.image_ref,
            "--region",
            context.config.gcloud.region,
            "--platform",
            "managed",
            "--no-allow-unauthenticated",
            "--port",
            "8080",
            "--memory",
            context.config.deploy.memory,
            "--cpu",
            str(context.config.deploy.cpu),
            "--concurrency",
            str(context.config.deploy.concurrency),
            "--max-instances",
            str(context.config.deploy.max_instances),
            "--min-instances",
            str(context.config.deploy.min_instances),
            "--timeout",
            str(context.config.deploy.timeout_seconds),
            "--set-env-vars",
            (
                f"BUGSCRUB_RUNTIME_ROOT={context.config.deploy.runtime_root},"
                f"BUGSCRUB_DUCKDB_PATH={context.config.deploy.duckdb_path}"
            ),
        ],
        context.repo_root,
    )
    logger("Cloud Run deployment completed.")


def set_cloud_run_public(
    context: DeployContext,
    *,
    logger: Callable[[str], None],
    command_runner: Callable[[list[str], Path | None], None],
) -> None:
    command_runner(
        [
            "gcloud",
            "run",
            "services",
            "add-iam-policy-binding",
            context.config.gcloud.service_name,
            "--region",
            context.config.gcloud.region,
            "--member",
            "allUsers",
            "--role",
            "roles/run.invoker",
        ],
        context.repo_root,
    )
    logger("Cloud Run service was made public.")


def describe_cloud_run_url(
    context: DeployContext,
    *,
    logger: Callable[[str], None],
    command_runner: Callable[[list[str], Path | None], None],
) -> str:
    capture: list[str] = []

    def capture_runner(command: list[str], cwd: Path | None) -> None:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        capture.append(result.stdout.strip())

    capture_runner(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            context.config.gcloud.service_name,
            "--region",
            context.config.gcloud.region,
            "--format",
            "value(status.url)",
        ],
        context.repo_root,
    )
    url = capture[-1].strip()
    logger(f"Cloud Run URL: {url}")
    return url


def set_docker_hub_repository_visibility(
    context: DeployContext,
    *,
    is_private: bool,
    logger: Callable[[str], None],
) -> None:
    token = context.secrets.docker_token.strip()
    if not token or token == "REPLACE_WITH_DOCKER_HUB_PAT":
        raise DeployControlError("Docker Hub token is missing in secrets.toml.")

    bearer_token = authenticate_docker_hub(
        username=context.config.docker.username,
        token=token,
    )

    repo_payload = get_or_create_docker_repository(
        username=context.config.docker.username,
        repo_name=context.config.docker.repo_name,
        bearer_token=bearer_token,
        is_private=is_private,
    )
    patch_payload = {
        "name": context.config.docker.repo_name,
        "namespace": context.config.docker.username,
        "description": repo_payload.get("description") or "",
        "full_description": repo_payload.get("full_description") or "",
        "is_private": is_private,
    }
    _docker_hub_request(
        method="PATCH",
        username=context.config.docker.username,
        repo_name=context.config.docker.repo_name,
        bearer_token=bearer_token,
        json=patch_payload,
    )
    visibility = "private" if is_private else "public"
    logger(f"Docker Hub repository visibility set to {visibility}.")


def authenticate_docker_hub(*, username: str, token: str) -> str:
    response = requests.post(
        "https://hub.docker.com/v2/users/login",
        json={"username": username, "password": token},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    bearer_token = str(payload.get("token", "")).strip()
    if not bearer_token:
        raise DeployControlError("Docker Hub login succeeded but no bearer token was returned.")
    return bearer_token


def get_or_create_docker_repository(
    *,
    username: str,
    repo_name: str,
    bearer_token: str,
    is_private: bool,
) -> dict[str, object]:
    response = _docker_hub_request(
        method="GET",
        username=username,
        repo_name=repo_name,
        bearer_token=bearer_token,
        allow_not_found=True,
    )
    if response.status_code != 404:
        return response.json()

    create_payload = {
        "namespace": username,
        "name": repo_name,
        "is_private": is_private,
        "description": "",
        "full_description": "",
    }
    create_response = _docker_hub_collection_request(
        method="POST",
        username=username,
        bearer_token=bearer_token,
        json=create_payload,
    )
    return create_response.json()


def _docker_hub_request(
    *,
    method: str,
    username: str,
    repo_name: str,
    bearer_token: str,
    json: dict[str, object] | None = None,
    allow_not_found: bool = False,
) -> requests.Response:
    endpoints = [
        f"https://hub.docker.com/v2/namespaces/{username}/repositories/{repo_name}",
        f"https://hub.docker.com/v2/repositories/{username}/{repo_name}/",
    ]
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }
    last_response: requests.Response | None = None
    for endpoint in endpoints:
        response = requests.request(method, endpoint, headers=headers, json=json, timeout=30)
        last_response = response
        if response.status_code == 404 and allow_not_found:
            return response
        if response.ok:
            return response
        if response.status_code in {301, 302, 307, 308, 405, 404}:
            continue
        response.raise_for_status()
    if last_response is None:
        raise DeployControlError("Docker Hub repository request did not produce any response.")
    if allow_not_found and last_response.status_code == 404:
        return last_response
    last_response.raise_for_status()
    return last_response


def _docker_hub_collection_request(
    *,
    method: str,
    username: str,
    bearer_token: str,
    json: dict[str, object],
) -> requests.Response:
    endpoints = [
        f"https://hub.docker.com/v2/namespaces/{username}/repositories/",
        "https://hub.docker.com/v2/repositories/",
    ]
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }
    last_response: requests.Response | None = None
    for endpoint in endpoints:
        payload = dict(json)
        if endpoint.endswith("/v2/repositories/"):
            payload.setdefault("namespace", username)
        response = requests.request(method, endpoint, headers=headers, json=payload, timeout=30)
        last_response = response
        if response.ok:
            return response
        if response.status_code in {301, 302, 307, 308, 405, 404}:
            continue
        response.raise_for_status()
    if last_response is None:
        raise DeployControlError("Docker Hub collection request did not produce any response.")
    last_response.raise_for_status()
    return last_response


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
