from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from tqdm import tqdm

from jmrt.jira.client import JiraClient


@dataclass
class ProjectWaveSignals:
    key: str
    name: str
    project_type: str
    issue_count: int
    issue_types_count: int
    unique_statuses_count: int
    create_fields_count: int
    create_custom_fields_count: int


class WaveCollector:
    def __init__(self, client: JiraClient):
        self.client = client

    def get_projects(self) -> List[Dict[str, Any]]:
        return self.client.get_projects()

    def get_issue_count(self, project_key: str) -> int:
        data = self.client._request(
            "GET",
            "/search",
            params={"jql": f'project="{project_key}"', "maxResults": 0},
        )
        return int(data.get("total", 0))

    def get_statuses_proxy(self, project_key: str) -> tuple[int, int]:
        data = self.client._request("GET", f"/project/{project_key}/statuses")

        issue_types_count = 0
        statuses = set()

        if isinstance(data, list):
            issue_types_count = len(data)
            for it in data:
                for st in it.get("statuses", []) or []:
                    statuses.add(st.get("id") or st.get("name"))

        return issue_types_count, len(statuses)

    def get_createmeta_fields(self, project_key: str) -> tuple[int, int]:
        data = self.client._request(
            "GET",
            "/issue/createmeta",
            params={"projectKeys": project_key, "expand": "projects.issuetypes.fields"},
        )

        total_fields = 0
        custom_fields = 0

        if isinstance(data, dict):
            projects = data.get("projects", []) or []
            for p in projects:
                for it in p.get("issuetypes", []) or []:
                    fields: Dict[str, Any] = it.get("fields", {}) or {}
                    total_fields += len(fields)
                    for fid in fields.keys():
                        if str(fid).startswith("customfield_"):
                            custom_fields += 1

        return total_fields, custom_fields

    def collect(self, limit_projects: Optional[int] = None) -> List[ProjectWaveSignals]:
        projects = self.get_projects()
        if limit_projects:
            projects = projects[:limit_projects]

        results: List[ProjectWaveSignals] = []

        bar = tqdm(projects, desc="Wave planning: projects", unit="proj")
        for p in bar:
            key = p.get("key")
            bar.set_postfix_str(str(key))
            if not key:
                continue

            name = p.get("name") or key
            ptype = p.get("projectTypeKey") or "unknown"

            # Defaults if endpoints are blocked
            issue_count = 0
            issue_types_count = 0
            unique_statuses_count = 0
            create_fields_count = 0
            create_custom_fields_count = 0

            try:
                issue_count = self.get_issue_count(key)
            except Exception:
                pass

            try:
                issue_types_count, unique_statuses_count = self.get_statuses_proxy(key)
            except Exception:
                pass

            try:
                create_fields_count, create_custom_fields_count = self.get_createmeta_fields(key)
            except Exception:
                pass

            results.append(
                ProjectWaveSignals(
                    key=key,
                    name=name,
                    project_type=ptype,
                    issue_count=issue_count,
                    issue_types_count=issue_types_count,
                    unique_statuses_count=unique_statuses_count,
                    create_fields_count=create_fields_count,
                    create_custom_fields_count=create_custom_fields_count,
                )
            )

        return results

    @staticmethod
    def to_dict_list(items: List[ProjectWaveSignals]) -> List[Dict[str, Any]]:
        return [asdict(x) for x in items]
