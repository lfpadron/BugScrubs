from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiPolicy:
    enabled: bool = False
    allow_bug_sync: bool = False

    def can_call_cisco_api(self) -> bool:
        return self.enabled and self.allow_bug_sync
