from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


@dataclass
class JiraAuth:
    """
    Supports:
      - basic auth: username + token/password
      - bearer: PAT/OAuth token (if your setup supports it)
    """
    username: Optional[str] = None
    token: Optional[str] = None
    bearer_token: Optional[str] = None

    def headers(self) -> Dict[str, str]:
        if self.bearer_token:
            return {"Authorization": f"Bearer {self.bearer_token}"}
        if self.username and self.token:
            raw = f"{self.username}:{self.token}".encode("utf-8")
            b64 = base64.b64encode(raw).decode("ascii")
            return {"Authorization": f"Basic {b64}"}
        return {}


class JiraClient:
    def __init__(
        self,
        base_url: str,
        api_path: str = "/rest/api/2",
        auth: Optional[JiraAuth] = None,
        timeout_s: float = 30.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_path = api_path.rstrip("/")
        self.auth = auth or JiraAuth()
        self.timeout_s = timeout_s
        self.max_retries = max_retries

        self._client = httpx.Client(
            base_url=f"{self.base_url}{self.api_path}",
            timeout=self.timeout_s,
            headers={
                "Accept": "application/json",
                "User-Agent": "jmrt/0.1.0",
                **self.auth.headers(),
            },
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.request(method, url, params=params)

                # retry transient errors / rate limits
                if resp.status_code in (429, 502, 503, 504):
                    wait = min(2 ** (attempt - 1), 8)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                return resp.json()

            except Exception as e:
                last_exc = e
                wait = min(2 ** (attempt - 1), 8)
                time.sleep(wait)

        raise RuntimeError(f"Jira request failed after retries: {method} {url}") from last_exc

    def get_workflows(self) -> Any:
        return self._request("GET", "/workflow")

    def get_projects(self) -> Any:
        return self._request("GET", "/project")

    def get_fields(self) -> Any:
        return self._request("GET", "/field")
