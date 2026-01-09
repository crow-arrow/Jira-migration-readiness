from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Set
from tqdm import tqdm

from jmrt.jira.client import JiraClient


@dataclass
class ProjectCFUsedSignals:
    key: str
    name: str
    project_type: str

    issues_total: int
    sample_size: int

    used_custom_fields_count: int
    used_custom_field_ids: List[str]  # keep it bounded in report


class CFUsedCollector:
    """
    Real usage of custom fields per project via /search sampling.
    """

    def __init__(self, client: JiraClient):
        self.client = client

    def get_projects(self) -> List[Dict[str, Any]]:
        return self.client.get_projects()

    def _search_sample(
        self,
        project_key: str,
        sample_size: int,
        start_at: int = 0,
    ) -> Dict[str, Any]:
        # Ask Jira to return fields for issues; safest is "*all" (heavy but ok for small sample)
        # Alternative: "fields": ["*all"] vs fields="*all" depends on API; with _request we use params.
        return self.client._request(
            "GET",
            "/search",
            params={
                "jql": f'project="{project_key}" order by created DESC',
                "startAt": start_at,
                "maxResults": sample_size,
                "fields": "*all",
            },
        )

    @staticmethod
    def _is_non_empty_value(v: Any) -> bool:
        if v is None:
            return False
        if v == "":
            return False
        if isinstance(v, list) and len(v) == 0:
            return False
        if isinstance(v, dict) and len(v) == 0:
            return False
        return True

    def collect_project_usage(self, project_key: str, sample_size: int) -> tuple[int, int, Set[str]]:
        """
        Returns: (issues_total, sample_size_effective, used_custom_field_ids_set)
        """
        data = self._search_sample(project_key, sample_size=sample_size)
        total = int(data.get("total", 0))
        issues = data.get("issues", []) or []

        used: Set[str] = set()
        for issue in issues:
            fields: Dict[str, Any] = issue.get("fields", {}) or {}
            for fid, val in fields.items():
                if not str(fid).startswith("customfield_"):
                    continue
                if self._is_non_empty_value(val):
                    used.add(str(fid))

        return total, len(issues), used

    def collect(
        self,
        limit_projects: Optional[int] = None,
        sample_size: int = 200,
        max_field_ids_in_report: int = 200,
    ) -> List[ProjectCFUsedSignals]:
        projects = self.get_projects()
        if limit_projects:
            projects = projects[:limit_projects]

        results: List[ProjectCFUsedSignals] = []

        bar = tqdm(projects, desc="CF used (sample): projects", unit="proj")
        for p in bar:
            key = p.get("key")
            if not key:
                continue
            bar.set_postfix_str(str(key))

            name = p.get("name") or key
            ptype = p.get("projectTypeKey") or "unknown"

            issues_total = 0
            sample_effective = 0
            used_ids: Set[str] = set()

            try:
                issues_total, sample_effective, used_ids = self.collect_project_usage(key, sample_size=sample_size)
            except Exception:
                # degrade gracefully
                pass

            used_list = sorted(list(used_ids))[:max_field_ids_in_report]

            results.append(
                ProjectCFUsedSignals(
                    key=key,
                    name=name,
                    project_type=ptype,
                    issues_total=issues_total,
                    sample_size=sample_effective,
                    used_custom_fields_count=len(used_ids),
                    used_custom_field_ids=used_list,
                )
            )

        return results

    @staticmethod
    def to_dict_list(items: List[ProjectCFUsedSignals]) -> List[Dict[str, Any]]:
        return [asdict(x) for x in items]
