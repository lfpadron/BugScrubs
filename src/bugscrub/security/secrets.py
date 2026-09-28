from __future__ import annotations

from pathlib import Path


def preferred_secret_path(path: Path) -> Path:
    """Expose the mounted-file-first convention used by the MVP."""

    return path
