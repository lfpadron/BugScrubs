from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ParseResult:
    source: Path
    records: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Parser:
    """Base parser contract for raw Cisco inputs."""

    def parse(self, source: Path) -> ParseResult:
        raise NotImplementedError("Parser implementations will be added in the next phase.")
