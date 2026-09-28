from __future__ import annotations

from bugscrub.cisco_api.client import CiscoApiClient
from bugscrub.security.policy import ApiPolicy


class CiscoApiGateway:
    """Policy-aware wrapper for optional Cisco API usage."""

    def __init__(self, policy: ApiPolicy, client: CiscoApiClient) -> None:
        self.policy = policy
        self.client = client

    def fetch_bugs_if_allowed(self) -> list[dict]:
        if not self.policy.can_call_cisco_api():
            return []
        return self.client.fetch_bugs()
