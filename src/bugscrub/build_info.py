from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def current_build_timestamp(project_root: Path) -> str:
    """Return the latest application source modification time, in UTC."""
    source_files = [project_root / "streamlit_app.py"]
    source_files.extend((project_root / "src" / "bugscrub").rglob("*.py"))
    latest_modified = max(path.stat().st_mtime for path in source_files if path.is_file())
    return datetime.fromtimestamp(latest_modified, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
