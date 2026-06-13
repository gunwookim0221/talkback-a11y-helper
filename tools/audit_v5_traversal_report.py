"""Report rendering for the Audit V5 offline traversal parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# Audit V5 Traversal Engine MVP Summary",
        "",
        f"- Schema: `{report['schema_version']}`",
        f"- Run: `{report['run_metadata']['run_id']}`",
        f"- Source: `{report['run_metadata']['source_output_dir']}`",
        f"- Runner behavior changed: `{report['run_metadata']['runner_behavior_changed']}`",
        "",
        "## Metrics",
        "",
        f"- Discovered: {metrics['discovered_count']}",
        f"- Selected: {metrics['selected_count']}",
        f"- Activation attempts: {metrics['activation_attempt_count']}",
        f"- Activation successes: {metrics['activation_success_count']}",
        f"- Visited: {metrics['visited_count']}",
        f"- Missed: {metrics['missed_count']}",
        f"- Unknown misses: {metrics['unknown_miss_count']}",
        f"- Activation success rate: {metrics['activation_success_rate']}",
        f"- Visit rate: {metrics['visit_rate']}",
        f"- Miss attribution rate: {metrics['miss_attribution_rate']}",
        "",
        "## Root Cause Breakdown",
        "",
    ]
    for cause, count in report["root_cause_summary"].items():
        if count:
            lines.append(f"- `{cause}`: {count}")
    if not any(report["root_cause_summary"].values()):
        lines.append("- No missed candidates")

    lines.extend(["", "## Scenario Summaries", ""])
    for scenario in report["scenario_summaries"]:
        lines.append(
            f"- `{scenario['scenario_id']}`: discovered={scenario['discovered_count']} "
            f"visited={scenario['visited_count']} missed={scenario['missed_count']} "
            f"unknown={scenario['unknown_miss_count']}"
        )

    missed_ledgers = [ledger for ledger in report["candidate_ledgers"] if ledger.get("missed")]
    missed_ledgers = sorted(
        missed_ledgers,
        key=lambda item: (item.get("root_cause") or "", item.get("stable_label") or ""),
    )[:20]
    lines.extend(["", "## Top Missed Candidates", ""])
    if not missed_ledgers:
        lines.append("- No missed candidates")
    for ledger in missed_ledgers:
        lines.append(
            f"- `{ledger['stable_label']}`: root_cause={ledger.get('root_cause')} "
            f"selected={ledger.get('selected')} activation_attempted={ledger.get('activation_attempted')}"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "traversal_audit.json"
    markdown_path = output_dir / "traversal_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path
