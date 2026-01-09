from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .schema import Report


def write_json(report: Report, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def write_html(report: Report, template_dir: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.get_template("report.html.j2")

    summary_json = json.dumps(report.summary.model_dump())

    html = tpl.render(report=report, summary_json=summary_json)
    path = out_dir / "report.html"
    path.write_text(html, encoding="utf-8")
    return path
