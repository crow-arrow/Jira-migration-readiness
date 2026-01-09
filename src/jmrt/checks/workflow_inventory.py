from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from jmrt.report.schema import CheckResult, Severity


def _get_name(wf: Dict[str, Any]) -> str:
    # common keys across versions
    return wf.get("name") or wf.get("workflowName") or wf.get("id") or "unknown"


def workflow_inventory_check(data: Dict[str, Any]) -> List[CheckResult]:
    workflows = data.get("workflows", [])

    if not isinstance(workflows, list):
        return [
            CheckResult(
                id="WF_INVENTORY",
                title="Workflow inventory",
                severity=Severity.INFO,
                message="Unexpected workflow payload shape (skipped detailed analysis).",
                details={"payload_type": str(type(workflows)), "raw_keys": list(data.get("raw", {}).keys()) if isinstance(data.get("raw"), dict) else None},
                remediation="Inspect Jira /workflow response shape for your version and adjust parser.",
            )
        ]

    total = len(workflows)
    names = [_get_name(w) for w in workflows]
    name_counts = Counter(names)

    unique = len(name_counts)
    duplicates = sum(1 for _, c in name_counts.items() if c > 1)

    # Simple, migration-oriented heuristic:
    # More unique workflows -> more remediation effort.
    if unique >= 500:
        sev = Severity.FAIL
        msg = "Extremely high number of unique workflows. Standardization required before Cloud migration."
    elif unique >= 200:
        sev = Severity.WARN
        msg = "High number of unique workflows may increase migration effort."
    else:
        sev = Severity.PASS
        msg = "Workflow inventory looks manageable."

    top10 = [name for name, _ in name_counts.most_common(10)]

    return [
        CheckResult(
            id="WF_INVENTORY",
            title="Workflow inventory (all workflows)",
            severity=sev,
            message=msg,
            details={
                "total_workflows_returned": total,
                "unique_workflow_names": unique,
                "duplicate_name_entries": duplicates,
                "top_10_workflow_names": top10,
            },
            remediation=(
                "Identify workflow standardization candidates. "
                "Reduce one-off workflows and consolidate similar processes before migration."
            ),
        )
    ]
