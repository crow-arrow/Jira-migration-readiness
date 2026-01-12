from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Set

from jmrt.report.schema import CheckResult, Severity


def normalize_name(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[\[\]\(\)\{\}]", " ", s)
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def schema_key(field: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    sch = field.get("schema") or {}
    return sch.get("type"), sch.get("custom")


def score_pair(a: Dict[str, Any], b: Dict[str, Any]) -> int:
    # base: name match (we usually group by normalized name anyway)
    score = 60

    a_type, a_custom = schema_key(a)
    b_type, b_custom = schema_key(b)

    if a_type and b_type and a_type == b_type and a_custom == b_custom:
        score += 25
    elif a_type and b_type and a_type == b_type:
        score += 10

    a_cfg: Set[str] = set(a.get("configured_projects") or [])
    b_cfg: Set[str] = set(b.get("configured_projects") or [])
    if a_cfg or b_cfg:
        inter = len(a_cfg & b_cfg)
        union = len(a_cfg | b_cfg) or 1
        overlap_ratio = inter / union
        score += round(10 * overlap_ratio)

    a_hits = int(a.get("usage_hits") or 0)
    b_hits = int(b.get("usage_hits") or 0)
    lo, hi = min(a_hits, b_hits), max(a_hits, b_hits)
    if lo == 0 and hi <= 2:
        score += 5
    else:
        # mild similarity bonus
        if hi > 0:
            ratio = lo / hi
            score += round(5 * ratio)

    return min(score, 100)


def pick_canonical(fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Choose the "best" representative:
    # prefer more usage, then more configured projects, then lowest id number (stable)
    def key(f: Dict[str, Any]) -> Tuple[int, int, int]:
        hits = int(f.get("usage_hits") or 0)
        cfg = len(f.get("configured_projects") or [])
        # extract numeric part from customfield_12345
        fid = f.get("id") or ""
        m = re.search(r"(\d+)$", fid)
        num = int(m.group(1)) if m else 10**9
        # higher hits, higher cfg, then smaller num preferred
        return (hits, cfg, -num)

    return sorted(fields, key=key, reverse=True)[0]


def build_duplicate_candidates(
    fields_index: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    fields_index: field_id -> {
        id, name, schema, configured_projects: [...], usage_hits: int, used_projects: [...]
    }
    """
    # Group by normalized name
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for f in fields_index.values():
        name = f.get("name") or ""
        if not name:
            continue
        n = normalize_name(name)
        groups.setdefault(n, []).append(f)

    duplicate_groups = []
    for norm_name, items in groups.items():
        if len(items) < 2:
            continue

        canonical = pick_canonical(items)
        canonical_id = canonical.get("id")

        # pair scores vs canonical
        comparisons = []
        for f in items:
            if f.get("id") == canonical_id:
                continue
            s = score_pair(canonical, f)

            # classify pair
            a_type, a_custom = schema_key(canonical)
            b_type, b_custom = schema_key(f)

            same_type = (a_type and b_type and a_type == b_type)
            if s >= 85 and same_type:
                pair_category = "MERGE_CANDIDATE"
            else:
                pair_category = "MANUAL_REVIEW"

            # remove candidate if unused
            remove_candidate = (int(f.get("usage_hits") or 0) == 0)

            comparisons.append({
                "field_id": f.get("id"),
                "field_name": f.get("name"),
                "schema": f.get("schema") or {},
                "score_vs_canonical": s,
                "pair_category": pair_category,
                "remove_candidate": remove_candidate,
                "configured_projects_count": len(f.get("configured_projects") or []),
                "usage_hits": int(f.get("usage_hits") or 0),
            })

        duplicate_groups.append({
            "normalized_name": norm_name,
            "canonical": {
                "field_id": canonical.get("id"),
                "field_name": canonical.get("name"),
                "schema": canonical.get("schema") or {},
                "configured_projects_count": len(canonical.get("configured_projects") or []),
                "usage_hits": int(canonical.get("usage_hits") or 0),
            },
            "candidates": sorted(comparisons, key=lambda x: (-x["score_vs_canonical"], x["field_name"] or "")),
        })

    # sort groups by "impact": size desc, then total configured footprint
    def grp_key(g: Dict[str, Any]) -> Tuple[int, int]:
        size = 1 + len(g["candidates"])
        footprint = g["canonical"]["configured_projects_count"] + \
            sum(c["configured_projects_count"] for c in g["candidates"])
        return (size, footprint)

    duplicate_groups.sort(key=grp_key, reverse=True)

    return {
        "groups": duplicate_groups,
        "groups_count": len(duplicate_groups),
        "fields_in_groups": sum(1 + len(g["candidates"]) for g in duplicate_groups),
    }


def run_cf_duplicates_check(
    fields: List[Dict[str, Any]],
    cf_configured: Dict[str, Any],
    cf_usage: Dict[str, Any],
) -> CheckResult:
    """
    Expected inputs (adapt to your real structures):
      - fields: list from /field
      - cf_configured: mapping by project or field; we need field->projects list
      - cf_usage: field usage hits per project; we need field->hits total
    """
    # Build helper maps from your existing collectors.
    # Adjust these adapters to your actual output shapes.
    field_to_projects: Dict[str, List[str]] = cf_configured.get(
        "field_to_projects", {})  # field_id -> [PROJKEY]
    field_to_hits: Dict[str, int] = cf_usage.get(
        "field_hits_total", {})                  # field_id -> int

    fields_index: Dict[str, Dict[str, Any]] = {}
    for f in fields:
        fid = f.get("id")
        if not fid or not str(fid).startswith("customfield_"):
            continue
        fields_index[fid] = {
            "id": fid,
            "name": f.get("name"),
            "schema": f.get("schema") or {},
            "configured_projects": field_to_projects.get(fid, []),
            "usage_hits": int(field_to_hits.get(fid, 0)),
        }

    dup = build_duplicate_candidates(fields_index)

    return CheckResult(
        id="CF_DUPLICATES",
        title="Duplicate custom fields candidates",
        severity=Severity.WARN if dup["groups_count"] > 0 else Severity.PASS,
        message=(
            f"Found {dup['groups_count']} duplicate-name groups "
            f"({dup['fields_in_groups']} fields). Review MERGE/REMOVE candidates."
            if dup["groups_count"] > 0
            else "No obvious duplicate-name groups detected."
        ),
        details=dup,
        remediation=(
            "Review groups; keep canonical field, consider merging same-type fields, "
            "and mark unused duplicates for removal after verifying dashboards/filters/automation."
        ),
    )
