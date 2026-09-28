from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

from bugscrub.deploy_control import (
    ControlPaths,
    StepSelection,
    build_selected_steps,
    default_config_toml,
    default_secrets_toml,
    ensure_control_files,
    load_control_config,
)


def test_ensure_control_files_creates_templates() -> None:
    workspace_dir = build_workspace_dir()
    paths = ControlPaths(
        base_dir=workspace_dir / "control",
        config_path=workspace_dir / "control" / "config.toml",
        secrets_path=workspace_dir / "control" / "secrets.toml",
    )

    try:
        ensure_control_files(paths)

        assert paths.config_path.exists()
        assert paths.secrets_path.exists()
        assert paths.config_path.read_text(encoding="utf-8") == default_config_toml()
        assert paths.secrets_path.read_text(encoding="utf-8") == default_secrets_toml()
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def test_load_control_config_reads_expected_defaults() -> None:
    workspace_dir = build_workspace_dir()
    paths = ControlPaths(
        base_dir=workspace_dir / "control",
        config_path=workspace_dir / "control" / "config.toml",
        secrets_path=workspace_dir / "control" / "secrets.toml",
    )

    try:
        ensure_control_files(paths)
        config, secrets = load_control_config(paths)

        assert config.docker.username == "lfpadron"
        assert config.docker.image_name == "bugscrub-local-first"
        assert config.gcloud.project_id == "bugscrubs-t"
        assert config.deploy.timeout_seconds == 900
        assert secrets.docker_token == "REPLACE_WITH_DOCKER_HUB_PAT"
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def test_build_selected_steps_respects_checkbox_order() -> None:
    selection = StepSelection(
        git_push=True,
        docker_build=False,
        docker_push=True,
        docker_repo_public=False,
        cloud_run_deploy=True,
        cloud_run_public=True,
    )

    assert build_selected_steps(selection) == [
        "git_push",
        "docker_push",
        "cloud_run_deploy",
        "cloud_run_public",
    ]


def build_workspace_dir() -> Path:
    workspace_dir = Path("storage") / "test-artifacts" / f"deploy-control-{uuid4().hex[:8]}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir
