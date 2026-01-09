from __future__ import annotations

from typing import Any, Dict, List

from jmrt.jira.client import JiraClient


class WorkflowCollector:
    def __init__(self, client: JiraClient):
        self.client = client

    def get_workflows(self) -> Dict[str, Any] | List[Dict[str, Any]]:
        """
        Jira DC: GET /rest/api/2/workflow
        Returns all workflows (admin permission required).
        """
        return self.client.get_workflows()

    def collect(self) -> Dict[str, Any]:
        data = self.get_workflows()

        # Different Jira versions may return:
        # - a dict with "workflows": [...]
        # - a list directly
        if isinstance(data, dict) and "workflows" in data:
            workflows = data["workflows"]
        elif isinstance(data, list):
            workflows = data
        else:
            workflows = data  # keep raw for debugging

        return {
            "raw": data,
            "workflows": workflows,
        }
