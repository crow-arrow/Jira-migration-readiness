# jmrt/checks/cf_configured.py
from __future__ import annotations

from typing import Any, Dict, List

from jmrt.report.schema import CheckResult, Severity
from jmrt.jira.cf_configured import ProjectCFConfiguredSignals


def _severity_for_count(count: int) -> Severity:
    # Tune later, but conservative defaults
    if count >= 300:
        return Severity.FAIL
    if count >= 150:
        return Severity.WARN
    return Severity.INFO


def cf_configured_check(projects: List[ProjectCFConfiguredSignals]) -> List[CheckResult]:
    """
    Top projects by configured custom fields footprint (per-project configuration),
    using /customFields?projectIds=<id>.
    """

    # Sort desc by configured footprint
    ranked = sorted(projects, key=lambda p: p.configured_custom_fields_count, reverse=True)

    # Compact table for HTML (top 30)
    top = []
    for p in ranked[:30]:
        top.append(
            {
                "key": p.key,
                "name": p.name,
                "type": p.project_type,
                "configured_custom_fields": p.configured_custom_fields_count,
                "severity": _severity_for_count(p.configured_custom_fields_count).value,
            }
        )

    max_count = ranked[0].configured_custom_fields_count if ranked else 0
    max_sev = _severity_for_count(max_count) if ranked else Severity.INFO

    # Affected = projects above WARN threshold (>=150), capped for report readability
    affected = [p.key for p in ranked if p.configured_custom_fields_count >= 150][:50]

    msg = (
        "Configured custom field footprint per project computed via /customFields?projectIds=<id>. "
        "This reflects configuration scope (screens/contexts) and is expected to be higher than real usage."
    )

    return [
        CheckResult(
            id="CF_CONFIGURED_FOOTPRINT",
            title="Custom fields configured footprint (per project)",
            severity=max_sev,
            message=msg,
            details={
                "projects_analyzed": len(projects),
                "top_30_projects": top,
                "thresholds": {
                    "warn": ">=150 configured custom fields per project",
                    "fail": ">=300 configured custom fields per project",
                },
                "notes": [
                    "High configured footprint increases migration complexity (field mapping, context explosion, screen schemes).",
                    "Compare with sampled real usage (/search) to find toxic gaps (configured >> used).",
                ],
            },
            affected=affected,
            remediation=(
                "For projects with high configured footprint, validate field contexts and screens, "
                "identify unused/legacy fields, and reduce configuration scope before migration. "
                "Next: compare configured vs used per project to flag 'toxic' fields and refine wave scoring."
            ),
        )
    ]
