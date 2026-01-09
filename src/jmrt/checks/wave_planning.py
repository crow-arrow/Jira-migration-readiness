from __future__ import annotations

from typing import Any, Dict, List, Tuple

from jmrt.report.schema import CheckResult, Severity
from jmrt.jira.waves import ProjectWaveSignals


def _bucket(value: int, thresholds: List[int]) -> int:
    """
    Returns 0..len(thresholds) bucket index.
    Example thresholds [5000, 20000, 100000]
    """
    for i, t in enumerate(thresholds):
        if value <= t:
            return i
    return len(thresholds)


def score_project(p: ProjectWaveSignals) -> Tuple[int, Dict[str, Any]]:
    # size (issues)
    size_bucket = _bucket(p.issue_count, [5_000, 20_000, 100_000])

    # workflow proxy (unique statuses)
    wf_bucket = _bucket(p.unique_statuses_count, [15, 30, 60])

    # custom field usage proxy (custom fields on create screens)
    cf_bucket = _bucket(p.create_custom_fields_count, [30, 80, 150])

    total = size_bucket + wf_bucket + cf_bucket

    details = {
        "size_bucket": size_bucket,
        "workflow_bucket": wf_bucket,
        "custom_fields_bucket": cf_bucket,
        "issue_count": p.issue_count,
        "unique_statuses_count": p.unique_statuses_count,
        "create_custom_fields_count": p.create_custom_fields_count,
        "project_type": p.project_type,
    }
    return total, details


def classify_wave(score: int) -> str:
    # Conservative defaults (tune later)
    if score <= 2:
        return "WAVE_1"
    if score <= 5:
        return "WAVE_2"
    return "WAVE_3"


def wave_planning_check(projects: List[ProjectWaveSignals]) -> List[CheckResult]:
    scored = []
    for p in projects:
        s, d = score_project(p)
        scored.append((p, s, d))

    scored.sort(key=lambda x: x[1])  # easiest first

    wave1 = [p.key for (p, s, _) in scored if classify_wave(s) == "WAVE_1"]
    wave2 = [p.key for (p, s, _) in scored if classify_wave(s) == "WAVE_2"]
    wave3 = [p.key for (p, s, _) in scored if classify_wave(s) == "WAVE_3"]

    # Build a compact table for the report (top 30 only, to keep HTML readable)
    top = []
    for p, s, d in scored[:30]:
        top.append(
            {
                "key": p.key,
                "type": p.project_type,
                "score": s,
                "issues": p.issue_count,
                "unique_statuses": p.unique_statuses_count,
                "create_custom_fields": p.create_custom_fields_count,
                "wave": classify_wave(s),
            }
        )

    msg = (
        "Wave planning candidates computed from issue volume, workflow complexity proxy, "
        "and per-project create-screen custom field footprint."
    )

    return [
        CheckResult(
            id="WAVE_PLANNING",
            title="Wave planning (project candidates)",
            severity=Severity.INFO,
            message=msg,
            details={
                "wave1_count": len(wave1),
                "wave2_count": len(wave2),
                "wave3_count": len(wave3),
                "wave1_projects": wave1[:50],
                "top_30_ranked_projects": top,
                "scoring_rules": {
                    "issue_count": "0<=5k, 1<=20k, 2<=100k, 3>100k",
                    "unique_statuses": "0<=15, 1<=30, 2<=60, 3>60",
                    "create_custom_fields": "0<=30, 1<=80, 2<=150, 3>150",
                    "wave": "W1<=2, W2<=5, W3>=6",
                },
            },
            affected=wave1[:30],
            remediation=(
                "Start Wave 1 with the easiest projects (low score). "
                "Use this output to propose a migration sequence and validate with app parity and JSM-specific checks."
            ),
        )
    ]
