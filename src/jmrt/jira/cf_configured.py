# jmrt/jira/cf_configured.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from tqdm import tqdm

from jmrt.jira.client import JiraClient


@dataclass
class ProjectCFConfiguredSignals:
    key: str
    name: str
    project_type: str
    configured_custom_fields_count: int
    configured_custom_field_ids: List[str]


class CFConfiguredCollector:
    """
    Configured custom fields footprint per project via:
      GET /rest/api/2/customFields?projectIds=<id>
    """

    def __init__(self, client: JiraClient):
        self.client = client

    def get_projects(self) -> List[Dict[str, Any]]:
        return self.client.get_projects()

    @staticmethod
    def _extract_fields_list(data: Any) -> List[Dict[str, Any]]:
        """
        DC versions may return either:
          - {"values": [ ... ]}
          - [ ... ]
        """
        if isinstance(data, dict) and isinstance(data.get("values"), list):
            return data.get("values") or []
        if isinstance(data, list):
            return data
        return []

    def get_configured_custom_fields_count(self, project_id: str) -> int:
        data = self.client._request(
            "GET",
            "/customFields",
            params={"projectIds": project_id},
        )
        fields = self._extract_fields_list(data)
        return len(fields)

    def get_configured_custom_field_ids(self, project_id: str) -> List[str]:
        data = self.client._request(
            "GET",
            "/customFields",
            params={"projectIds": project_id},
        )
        fields = self._extract_fields_list(data)

        ids: List[str] = []
        for f in fields:
            fid = f.get("id") or f.get("fieldId")
            if fid:
                ids.append(str(fid))

        # keep only real custom fields
        ids = [x for x in ids if x.startswith("customfield_")]
        return ids

    def collect(self, limit_projects: Optional[int] = None) -> List[ProjectCFConfiguredSignals]:
        projects = self.get_projects()
        if limit_projects:
            projects = projects[:limit_projects]

        results: List[ProjectCFConfiguredSignals] = []

        bar = tqdm(projects, desc="CF configured: projects", unit="proj")
        for p in bar:
            key = p.get("key")
            pid = p.get("id")
            bar.set_postfix_str(str(key or pid))
            if not key or not pid:
                continue

            name = p.get("name") or key
            ptype = p.get("projectTypeKey") or "unknown"

            # Default if endpoint is blocked/unstable
            configured_custom_fields_count = 0
            configured_ids: List[str] = []

            try:
                configured_custom_fields_count = self.get_configured_custom_fields_count(
                    str(pid))
            except Exception:
                pass

            results.append(
                ProjectCFConfiguredSignals(
                    key=key,
                    name=name,
                    project_type=ptype,
                    configured_custom_fields_count=configured_custom_fields_count,
                    configured_custom_field_ids=configured_ids,
                )
            )

        return results

    @staticmethod
    def to_dict_list(items: List[ProjectCFConfiguredSignals]) -> List[Dict[str, Any]]:
        return [asdict(x) for x in items]
