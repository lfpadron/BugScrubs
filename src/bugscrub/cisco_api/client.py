from __future__ import annotations

import requests


class CiscoApiClient:
    """Thin placeholder around Cisco API access."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = requests.Session()

    def fetch_bugs(self) -> list[dict]:
        return []
