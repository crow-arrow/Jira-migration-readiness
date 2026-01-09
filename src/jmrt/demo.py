from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path
from typing import Any, List
from tqdm import tqdm

from jmrt.jira.client import JiraClient, JiraAuth
from jmrt.report.schema import Report, Summary, CheckResult, Severity
from jmrt.report.renderer import write_json, write_html

from jmrt.jira.workflows import WorkflowCollector
from jmrt.checks.workflow_inventory import workflow_inventory_check

from jmrt.jira.waves import WaveCollector
from jmrt.checks.wave_planning import wave_planning_check

from jmrt.jira.cf_configured import CFConfiguredCollector
from jmrt.checks.cf_configured import cf_configured_check

from jmrt.jira.cf_used import CFUsedCollector
from jmrt.checks.cf_configured_vs_used_gap import cf_configured_vs_used_check



def is_custom_field(field: Any) -> bool:
    return bool(field.get("custom", False))


def main() -> None:
    """
    Run:
        python -m jmrt.demo

    Env vars:
        JIRA_BASE_URL=https://atlassian-int.mercedes-benz.polygran.de/[your-instance]
        JIRA_API_PATH=/rest/api/2   (DC usually /2, Cloud usually /3)
        JIRA_BEARER=[your-PAT-token]
    """
    base_url = os.environ.get("JIRA_BASE_URL")
    if not base_url:
        raise SystemExit("Set JIRA_BASE_URL, e.g. https://atlassian-int.mercedes-benz.polygran.de/pilot-aftersales")

    api_path = os.environ.get("JIRA_API_PATH", "/rest/api/2")

    bearer = os.environ.get("JIRA_BEARER")
    if not bearer:
        raise SystemExit("Set JIRA_BEARER with a valid token for authentication")

    auth = JiraAuth(bearer_token=bearer)
    client = JiraClient(base_url=base_url, api_path=api_path, auth=auth)

    try:
        with tqdm(total=7, desc="JMRT demo progress", unit="step") as pbar:

            # Step 1) Auth sanity check
            me = client._request("GET", "/myself")
            print(f'Authenticated as: {me.get("displayName")} ({me.get("emailAddress")})')
            pbar.update(1)

            # Step 2) Custom fields + projects
            fields: List[Any] = client.get_fields()
            field_id_to_name = {str(f.get("id")): (f.get("name") or str(f.get("id"))) for f in fields if f.get("id")}
            custom_fields = [f for f in fields if is_custom_field(f)]
            cf_count = len(custom_fields)

            projects: List[Any] = client.get_projects()
            project_keys = [p.get("key") for p in projects if p.get("key")]

            if cf_count >= 400:
                sev = Severity.FAIL
                msg = "Very high number of custom fields. Expect complex remediation and longer migration timelines."
            elif cf_count >= 200:
                sev = Severity.WARN
                msg = "High number of custom fields may increase migration complexity."
            else:
                sev = Severity.PASS
                msg = "Custom fields count looks manageable."

            cf_check = CheckResult(
                id="CF_COUNT",
                title="Custom fields count",
                severity=sev,
                message=msg,
                details={"count": cf_count},
                affected=project_keys[:20],
                remediation="Identify unused fields, consolidate duplicates, verify Cloud app parity for field behavior.",
            )
            pbar.update(1)

            # Step 3) Workflow inventory (ONE call, no loop)
            try:
                wf_collector = WorkflowCollector(client)
                wf_data = wf_collector.collect()
                wf_checks = workflow_inventory_check(wf_data)
            except Exception as e:
                wf_checks = [
                    CheckResult(
                        id="WF_INVENTORY",
                        title="Workflow inventory (all workflows)",
                        severity=Severity.INFO,
                        message="Workflow inventory endpoint is not accessible on this instance (skipped).",
                        details={"error": str(e)},
                        remediation="Ensure the token/user has Jira admin permission required for GET /rest/api/2/workflow.",
                    )
                ]
            pbar.update(1)

            # Step 4) Wave planning (ONE call; per-project progress should be inside WaveCollector.collect())
            try:
                wave_collector = WaveCollector(client)
                wave_projects = wave_collector.collect(limit_projects=20)  # увеличишь позже
                wave_checks = wave_planning_check(wave_projects)
            except Exception as e:
                wave_checks = [
                    CheckResult(
                        id="WAVE_PLANNING",
                        title="Wave planning (project candidates)",
                        severity=Severity.INFO,
                        message="Wave planning collection failed (skipped).",
                        details={"error": str(e)},
                        remediation=(
                            "Reduce scope (limit_projects), verify permissions for /search, "
                            "/project/{key}/statuses and /issue/createmeta, then retry."
                        ),
                    )
                ]
            pbar.update(1)

            cf_conf_projects = []
            cf_conf_checks = []
            gap_checks = []

            # Step 5) CF configured footprint per project (/customFields?projectIds=<id>)
            try:
                cf_conf_collector = CFConfiguredCollector(client)
                # важно: использовать те же limit_projects, что и в wave planning (пока 20)
                cf_conf_projects = cf_conf_collector.collect(limit_projects=20)
                cf_conf_checks = cf_configured_check(cf_conf_projects)
            except Exception as e:
                cf_conf_checks = [
                    CheckResult(
                        id="CF_CONFIGURED_FOOTPRINT",
                        title="Custom fields configured footprint (per project)",
                        severity=Severity.INFO,
                        message="Configured custom fields per project collection failed (skipped).",
                        details={"error": str(e)},
                        remediation=(
                            "Verify permissions for GET /rest/api/2/customFields?projectIds=<id>. "
                            "If the endpoint is heavy, reduce limit_projects and increase timeouts in JiraClient."
                        ),
                    )
                ]
            pbar.update(1)

            # Step 6) CF configured vs used gap per project
            try:
                cf_used_collector = CFUsedCollector(client)
                cf_used_projects = cf_used_collector.collect(limit_projects=20, sample_size=200)
                cf_used_checks = []  # можно отдельно чекнуть или только использовать для сравнения
                gap_checks = cf_configured_vs_used_check(
                    cf_conf_projects,
                    cf_used_projects,
                    field_id_to_name=field_id_to_name,
                    top_fields_per_project=15,
                )


            except Exception as e:
                gap_checks = [
                    CheckResult(
                        id="CF_CONFIGURED_VS_USED",
                        title="Custom fields: configured vs real usage (sampled)",
                        severity=Severity.INFO,
                        message="Configured vs used custom fields per project comparison failed (skipped).",
                        details={"error": str(e)},
                        remediation=(
                            "Ensure both configured (/customFields) and used (/search sampling) data collections "
                            "are successful before running this comparison."
                        ),
                    )
                ]
            pbar.update(1)

            # Step 7) Render report
            checks = [
                *wf_checks,
                *wave_checks,
                *cf_conf_checks,
                *gap_checks,
                cf_check,
            ]

            summary = Summary(
                pass_count=sum(1 for c in checks if c.severity == Severity.PASS),
                info_count=sum(1 for c in checks if c.severity == Severity.INFO),
                warn_count=sum(1 for c in checks if c.severity == Severity.WARN),
                fail_count=sum(1 for c in checks if c.severity == Severity.FAIL),
                blocker_count=sum(1 for c in checks if c.severity == Severity.BLOCKER),
            )

            report = Report(
                target=f"{base_url}{api_path}",
                summary=summary,
                checks=checks,
            )

            out_dir = Path("reports/real")
            json_path = write_json(report, out_dir)
            html_path = write_html(report, Path("templates"), out_dir)

            print(f"Wrote: {json_path}")
            print(f"Wrote: {html_path}")
            print("Open: reports/real/report.html")

            pbar.update(1)


    finally:
        client.close()


if __name__ == "__main__":
    main()
