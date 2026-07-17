"""Canonical JSON and deterministic Markdown comparison reports."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json, canonical_json_bytes


COMPARISON_REPORT_SCHEMA_VERSION = "talkback-comparison-report-v1"


def canonical_report_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude only non-semantic wall-clock metadata from replay bytes."""
    comparison = {
        key: value
        for key, value in result.items()
        if key != "generated_at"
    }
    return {
        "report_schema": COMPARISON_REPORT_SCHEMA_VERSION,
        "comparison": comparison,
    }


def canonical_report_json(result: Mapping[str, Any]) -> str:
    return canonical_json(canonical_report_payload(result))


def _status(result: Mapping[str, Any], key: str) -> str:
    value = result.get(key)
    return str(value.get("status") or "DATA_UNAVAILABLE") if isinstance(value, Mapping) else "DATA_UNAVAILABLE"


def _count_map(value: Any) -> str:
    if not isinstance(value, Mapping) or not value:
        return "none"
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def _reason_lines(items: Any) -> list[str]:
    rows = []
    for item in items or ():
        if isinstance(item, Mapping):
            code = str(item.get("code") or "UNKNOWN")
            dimension = str(item.get("dimension") or item.get("field") or "")
            rows.append(f"- `{code}`" + (f" — {dimension}" if dimension else ""))
        else:
            rows.append(f"- `{item}`")
    return rows or ["- none"]


def render_markdown_report(result: Mapping[str, Any]) -> str:
    verdict = result.get("verdict") or {}
    app_version = result.get("app_version_delta") or {}
    availability = result.get("observation_availability") or {}
    failures = (result.get("accessibility_failure_summary") or {}).get(
        "classification_counts", {}
    )
    limitations = (result.get("limitation_binding_deltas") or {}).get(
        "status_counts", {}
    )
    node_counts = (result.get("node_match_summary") or {}).get(
        "node_delta_counts", {}
    )
    lines = [
        "# TalkBack Accessibility Comparison Report",
        "",
        f"- Comparison ID: `{result.get('comparison_id')}`",
        f"- Verdict: **{verdict.get('overall', 'INCOMPARABLE')}**",
        f"- Comparator: `{result.get('comparator_version')}`",
        f"- Verdict policy: `{verdict.get('policy_version')}`",
        "- Automatic approval: disabled",
        "",
        "## Environment",
        "",
        f"- Status: `{_status(result, 'environment_delta')}`",
        f"- Changes: `{_count_map((result.get('environment_delta') or {}).get('changes'))}`",
        "",
        "## Version",
        "",
        f"- Relation: `{app_version.get('relation', app_version.get('version_relation', 'UNKNOWN'))}`",
        f"- Baseline: `{app_version.get('baseline', {}).get('raw_version_name', '')}`",
        f"- Candidate: `{app_version.get('candidate', {}).get('raw_version_name', '')}`",
        "",
        "## Compatibility",
        "",
        f"- Grade: `{result.get('compatibility_grade')}`",
        f"- Selection tie: `{str(bool(result.get('selection_tie'))).lower()}`",
        "",
        "## Coverage",
        "",
        f"- Aggregate: `{_status(result, 'coverage_aggregate_delta')}`",
        f"- Common-cohort data: `{(result.get('coverage_cohort_transitions') or {}).get('status', 'DATA_UNAVAILABLE')}`",
        "",
        "## Identity",
        "",
        f"- Status: `{_status(result, 'identity_aggregate_delta')}`",
        f"- Node deltas: `{_count_map(node_counts)}`",
        "",
        "## Traversal",
        "",
        f"- Status: `{_status(result, 'traversal_aggregate_delta')}`",
        "",
        "## Recovery",
        "",
        f"- Status: `{_status(result, 'recovery_aggregate_delta')}`",
        "",
        "## Profiler",
        "",
        f"- Status: `{_status(result, 'profiler_aggregate_delta')}`",
        "- Accessibility verdict effect: `NONE`",
        "",
        "## Known Limitation",
        "",
        f"- Bindings: `{_count_map(limitations)}`",
        "- Raw failures remain unchanged.",
        "",
        "## New Failure",
        "",
        f"- Count: `{verdict.get('new_failure_count', 0)}`",
        f"- Classifications: `{_count_map(failures)}`",
        "",
        "## Resolved Failure",
        "",
        f"- Count: `{verdict.get('resolved_failure_count', 0)}`",
        "",
        "## Observation Availability",
        "",
        f"- Status: `{availability.get('status', 'DATA_UNAVAILABLE')}`",
        f"- Baseline observations: `{(availability.get('baseline') or {}).get('observation_count', 0)}`",
        f"- Candidate observations: `{(availability.get('candidate') or {}).get('observation_count', 0)}`",
        "",
        "## Review Items",
        "",
        *_reason_lines(result.get("review_items")),
        "",
        "## Verdict Reasons",
        "",
        *_reason_lines(verdict.get("reasons")),
        "",
        "## Recommendation",
        "",
        str(verdict.get("recommendation") or ""),
        "",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class ReportWriteResult:
    directory: Path
    comparison_json: Path
    markdown_report: Path


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_comparison_report(
    result: Mapping[str, Any],
    output_root: str | Path,
) -> ReportWriteResult:
    package = str(
        (
            (result.get("compatibility_key") or {}).get("key_source") or {}
        ).get("identity", {}).get("app_package")
        or "unknown-package"
    )
    safe_package = re.sub(r"[^A-Za-z0-9._-]+", "-", package)
    comparison_id = str(result.get("comparison_id") or "")
    if not re.fullmatch(r"comparison_[0-9a-f]{24}", comparison_id):
        raise ValueError("invalid comparison ID")
    directory = Path(output_root) / safe_package / comparison_id
    json_path = directory / "comparison.json"
    markdown_path = directory / "report.md"
    json_bytes = canonical_json_bytes(canonical_report_payload(result))
    markdown_bytes = render_markdown_report(result).encode("utf-8")
    if directory.exists():
        if (
            json_path.is_file()
            and markdown_path.is_file()
            and json_path.read_bytes() == json_bytes
            and markdown_path.read_bytes() == markdown_bytes
        ):
            return ReportWriteResult(directory, json_path, markdown_path)
        raise ValueError("immutable comparison report already exists with different bytes")
    directory.mkdir(parents=True)
    _atomic_write(json_path, json_bytes)
    _atomic_write(markdown_path, markdown_bytes)
    return ReportWriteResult(directory, json_path, markdown_path)


__all__ = [
    "COMPARISON_REPORT_SCHEMA_VERSION",
    "ReportWriteResult",
    "canonical_report_json",
    "canonical_report_payload",
    "render_markdown_report",
    "write_comparison_report",
]
