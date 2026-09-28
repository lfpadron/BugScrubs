from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any


LOGGER_NAME = "bugscrub"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FILE_NAME = "bugscrub.jsonl"


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", {})
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


def build_log_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / "logs" / DEFAULT_LOG_FILE_NAME


def configure_structured_logging(runtime_root: Path, *, level: str = DEFAULT_LOG_LEVEL) -> Path:
    log_path = build_log_path(runtime_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, str(level or DEFAULT_LOG_LEVEL).upper(), logging.INFO))
    logger.propagate = False

    target_path = str(log_path.resolve())
    for handler in logger.handlers:
        if getattr(handler, "_bugscrub_log_path", "") == target_path:
            return log_path

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonLineFormatter())
    handler._bugscrub_log_path = target_path  # type: ignore[attr-defined]
    logger.addHandler(handler)
    return log_path


def get_logger(name: str | None = None) -> logging.Logger:
    if not name:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def log_event(logger: logging.Logger, level: int, event: str, message: str, **fields: object) -> None:
    logger.log(level, message, extra={"event": event, "fields": fields})


def log_exception(
    logger: logging.Logger,
    event: str,
    message: str,
    *,
    error: BaseException,
    **fields: object,
) -> None:
    logger.exception(
        message,
        exc_info=error,
        extra={
            "event": event,
            "fields": {
                **fields,
                "error_type": error.__class__.__name__,
                "error_message": str(error),
            },
        },
    )
