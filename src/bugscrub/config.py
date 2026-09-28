from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from os import getenv
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    duckdb_path: Path
    runtime_root: Path
    api_enabled: bool
    policy_path: Path
    log_level: str
    cisco_client_id: str
    cisco_client_secret: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        duckdb_path=Path(getenv("BUGSCRUB_DUCKDB_PATH", "storage/bugscrub.duckdb")),
        runtime_root=Path(getenv("BUGSCRUB_RUNTIME_ROOT", "storage/runtime")),
        api_enabled=getenv("BUGSCRUB_API_ENABLED", "false").lower() == "true",
        policy_path=Path(getenv("BUGSCRUB_POLICY_PATH", "secrets/policy.yaml")),
        log_level=getenv("BUGSCRUB_LOG_LEVEL", "INFO"),
        cisco_client_id=getenv("BUGSCRUB_CISCO_CLIENT_ID", ""),
        cisco_client_secret=getenv("BUGSCRUB_CISCO_CLIENT_SECRET", ""),
    )
