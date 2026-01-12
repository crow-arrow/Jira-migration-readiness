from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, DefaultDict

from collections import defaultdict

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


@dataclass
class EndpointStats:
    calls: int = 0
    retries: int = 0
    failures: int = 0
    total_time_s: float = 0.0
    status_counts: DefaultDict[int, int] = field(
        default_factory=lambda: defaultdict(int))


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
        self.stats: Dict[str, EndpointStats] = {}

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
        endpoint_key = f"{method.upper()} {url}"

        if endpoint_key not in self.stats:
            self.stats[endpoint_key] = EndpointStats()

        for attempt in range(1, self.max_retries + 1):
            start = time.perf_counter()
            try:
                self.stats[endpoint_key].calls += 1

                resp = self._client.request(method, url, params=params)
                elapsed = time.perf_counter() - start
                self.stats[endpoint_key].total_time_s += elapsed
                self.stats[endpoint_key].status_counts[resp.status_code] += 1

                # retry transient errors / rate limits
                if resp.status_code in (429, 502, 503, 504):
                    self.stats[endpoint_key].retries += 1

                    # if Jira provides Retry-After, use it (seconds)
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait = min(int(retry_after), 30)
                    else:
                        wait = min(2 ** (attempt - 1), 8)

                    time.sleep(wait)
                    continue

                resp.raise_for_status()

                # Some Jira endpoints can return empty body; guard json decode
                if not resp.content:
                    return None

                return resp.json()

            except httpx.RequestError as e:
                # network/transient transport errors
                last_exc = e
                if attempt == self.max_retries:
                    self.stats[endpoint_key].failures += 1
                wait = min(2 ** (attempt - 1), 8)
                time.sleep(wait)

            except httpx.HTTPStatusError as e:
                # only retry on specific status codes
                last_exc = e
                status = e.response.status_code
                if status in (429, 502, 503, 504) and attempt < self.max_retries:
                    self.stats[endpoint_key].retries += 1

                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait = min(int(retry_after), 30)
                    else:
                        wait = min(2 ** (attempt - 1), 8)

                    time.sleep(wait)
                    continue

                # non-retryable status or no attempts left
                self.stats[endpoint_key].failures += 1
                raise

        raise RuntimeError(
            f"Jira request failed after retries: {method} {url}") from last_exc

    def get_paginated(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        items_key: str,
        start_at_param: str = "startAt",
        max_results_param: str = "maxResults",
        page_size: int = 100,
        total_key: str = "total",
        limit: Optional[int] = None,
    ) -> List[Any]:
        """
        Generic Jira pagination for endpoints that use startAt/maxResults/total.

        Examples:
          - /search -> items_key="issues"
          - some list endpoints -> items_key="values" (if they follow same model)

        limit: hard cap on total items returned (useful for sampling)
        """
        params = dict(params or {})
        start_at = int(params.get(start_at_param, 0))
        params[max_results_param] = int(
            params.get(max_results_param, page_size))

        all_items: List[Any] = []

        while True:
            params[start_at_param] = start_at
            page = self._request("GET", url, params=params) or {}

            if not isinstance(page, dict):
                raise RuntimeError(
                    f"Expected paginated response dict, got {type(page)} for {url}")

            items = page.get(items_key) or []
            all_items.extend(items)

            if limit is not None and len(all_items) >= limit:
                return all_items[:limit]

            # Determine if we're done
            total = page.get(total_key)
            page_size_effective = len(items)

            if page_size_effective == 0:
                return all_items

            # If total is present, we can stop when we reach it
            if isinstance(total, int):
                start_at += page_size_effective
                if start_at >= total:
                    return all_items
            else:
                # Fallback: stop when returned fewer than requested
                requested = int(params[max_results_param])
                start_at += page_size_effective
                if page_size_effective < requested:
                    return all_items

    def stats_summary(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for key, st in self.stats.items():
            avg = (st.total_time_s / st.calls) if st.calls else 0.0
            out[key] = {
                "calls": st.calls,
                "retries": st.retries,
                "failures": st.failures,
                "avg_time_s": round(avg, 4),
                "status_counts": dict(st.status_counts),
            }
        return out

    def get_workflows(self) -> Any:
        return self._request("GET", "/workflow")

    def get_projects(self) -> Any:
        return self._request("GET", "/project")

    def get_fields(self) -> Any:
        return self._request("GET", "/field")
