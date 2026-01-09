from __future__ import annotations

from typing import Any, Dict, List, Optional

from jmrt.report.schema import CheckResult, Severity
from jmrt.jira.cf_configured import ProjectCFConfiguredSignals
from jmrt.jira.cf_used import ProjectCFUsedSignals


def _sev_for_gap(configured: int, used: int) -> Severity:
    # heuristic: big configured but low usage => toxic config
    if configured >= 200 and used <= 30:
        return Severity.FAIL
    if configured >= 120 and used <= 30:
        return Severity.WARN
    return Severity.INFO


def cf_configured_vs_used_check(
    configured_projects: List[ProjectCFConfiguredSignals],
    used_projects: List[ProjectCFUsedSignals],
    field_id_to_name: Optional[Dict[str, str]] = None,
    top_fields_per_project: int = 15,
) -> List[CheckResult]:
    conf_by_key = {p.key: p for p in configured_projects}
    used_by_key = {p.key: p for p in used_projects}
    field_id_to_name = field_id_to_name or {}

    rows: List[Dict[str, Any]] = []
    for key, c in conf_by_key.items():
        u = used_by_key.get(key)

        used_cnt = u.used_custom_fields_count if u else 0
        configured_cnt = c.configured_custom_fields_count

        gap = configured_cnt - used_cnt
        ratio = round((used_cnt / configured_cnt), 3) if configured_cnt > 0 else 0.0

        # Add named used fields (bounded)
        used_ids = (u.used_custom_field_ids if u else []) or []
        used_named = []
        for fid in used_ids[:top_fields_per_project]:
            used_named.append({"id": fid, "name": field_id_to_name.get(fid, fid)})

        rows.append(
            {
                "key": key,
                "type": c.project_type,
                "configured": configured_cnt,
                "used_sampled": used_cnt,
                "gap": gap,
                "used_ratio": ratio,
                "sample_size": (u.sample_size if u else 0),
                "issues_total": (u.issues_total if u else 0),
                "top_used_fields_named": used_named,  # <-- NEW
                "severity": _sev_for_gap(configured_cnt, used_cnt).value,
            }
        )

    # Most toxic first: large gap, then low ratio
    rows.sort(key=lambda r: (r["gap"], -r["used_ratio"]), reverse=True)

    top = rows[:30]

    overall = Severity.INFO
    if top:
        worst = top[0]
        overall = _sev_for_gap(int(worst["configured"]), int(worst["used_sampled"]))

    affected = [r["key"] for r in rows if r["severity"] in (Severity.WARN.value, Severity.FAIL.value)][:50]

    msg = (
        "Configured vs sampled-used custom fields per project. "
        "Large gaps indicate configuration sprawl and potential 'toxic' field inventory."
    )

    return [
        CheckResult(
            id="CF_CONFIGURED_VS_USED",
            title="Custom fields: configured vs real usage (sampled)",
            severity=overall,
            message=msg,
            details={
                "projects_analyzed": len(rows),
                "top_30_toxic_gap_projects": top,
                "heuristics": {
                    "fail": "configured>=200 AND used_sampled<=30",
                    "warn": "configured>=120 AND used_sampled<=30",
                    "sort": "gap desc, then used_ratio asc",
                    "used_definition": "unique customfield_* with non-empty values found in /search sample",
                    "top_used_fields_named": f"first {top_fields_per_project} used fields per project (from sample), id->name resolved via GET /field",
                },
            },
            affected=affected,
            remediation=(
                "For top-gap projects: identify unused fields, shrink field contexts/screen schemes, "
                "and validate which fields are truly required. "
                "Use named used fields list to drive cleanup workshops with project admins."
            ),
        )
    ]
