from __future__ import annotations

import logging
from pathlib import Path
import shutil

from bugscrub.config import Settings
from bugscrub.db.duckdb_store import DuckDBStore
from bugscrub.observability import LOGGER_NAME, configure_structured_logging


RUNTIME_DATA_DIRECTORIES = ("uploads", "bug-datasets", "exports", "logs")


def reset_application_data(settings: Settings, store: DuckDBStore) -> None:
    """Reset persisted analysis data, keeping application code and deployment settings."""
    runtime_root = Path(settings.runtime_root).resolve()
    if runtime_root == Path(runtime_root.anchor):
        raise ValueError("The runtime directory cannot be a filesystem root.")

    targets = [runtime_root / name for name in RUNTIME_DATA_DIRECTORIES]
    protected_paths = (
        store.database_path.resolve(), Path(settings.policy_path).resolve(), Path(__file__).resolve(),
    )
    # Validate every absolute target before changing either the database or files.
    # Do not follow a symlink/junction replacing an application's data directory.
    for target in targets:
        resolved = target.resolve()
        if resolved != target or resolved.parent != runtime_root:
            raise ValueError(f"Refusing to reset a redirected runtime directory: {target}")
        if any(path.is_relative_to(resolved) for path in protected_paths):
            raise ValueError(f"A protected application file is inside the reset directory: {target}")
        if target.exists() and not target.is_dir():
            raise ValueError(f"Expected a runtime directory: {target}")

    store.reset_data()
    log_root = runtime_root / "logs"
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        log_path = getattr(handler, "_bugscrub_log_path", None)
        if log_path and Path(log_path).resolve().is_relative_to(log_root):
            logger.removeHandler(handler)
            handler.close()

    try:
        for target in targets:
            if target.exists():
                shutil.rmtree(target)
    finally:
        # Reopen a fresh log after removing the old files, including on Windows.
        configure_structured_logging(settings.runtime_root, level=settings.log_level)
