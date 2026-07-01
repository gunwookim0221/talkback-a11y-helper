from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tb_runner.v10_preparation import V10_ARTIFACT_ROOT, V10VersionSchema

SHADOW_COMPARISON_SCHEMA_VERSION = "v10-shadow-comparison-v1"
SHADOW_REPORT_SCHEMA_VERSION = "v10-shadow-report-v1"
SHADOW_ARTIFACT_VERSION = "v10-shadow-artifact-v1"
ALLOWED_COMPARISON_RESULTS = {
    "MATCH",
    "MISMATCH",
    "UNKNOWN",
    "AMBIGUOUS",
    "FAILED",
}

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator > 0 else 0.0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _markdown_escape(value: Any) -> str:
    text = _text(value)
    return text.replace("|", "\\|") if text else "-"


def _percent(value: Any) -> str:
    return f"{_float(value) * 100:.2f}%"


def compare_shadow_candidate(
    legacy_result: Mapping[str, Any],
    shadow_candidate: Mapping[str, Any],
    *,
    versions: V10VersionSchema | Mapping[str, Any] | None = None,
    clock: Clock = _utc_now,
) -> dict[str, Any]:
    resolved_versions = (
        versions
        if isinstance(versions, V10VersionSchema)
        else V10VersionSchema.from_mapping(versions)
    )
    legacy_inventory_id = _text(legacy_result.get("inventory_id"))
    legacy_runtime_card_id = _text(legacy_result.get("runtime_card_id"))
    shadow_inventory_id = _text(shadow_candidate.get("inventory_id"))
    shadow_runtime_card_id = _text(shadow_candidate.get("runtime_card_id"))
    legacy_scenario = _text(
        legacy_result.get("legacy_scenario") or legacy_result.get("scenario")
    )
    candidate_scenario = _text(shadow_candidate.get("scenario_candidate"))
    legacy_decision = _text(legacy_result.get("decision")).lower()
    eligibility = _text(shadow_candidate.get("eligibility")).lower()
    display_label = _text(
        shadow_candidate.get("display_label") or legacy_result.get("display_label")
    )
    stable_label = _text(
        shadow_candidate.get("stable_label") or legacy_result.get("stable_label")
    )
    run_id = _text(shadow_candidate.get("run_id") or legacy_result.get("run_id"))
    device_name = _text(
        shadow_candidate.get("device_name") or legacy_result.get("device_name")
    )

    result = "UNKNOWN"
    reason = "scenario_unresolved"
    if (
        not legacy_inventory_id
        or not legacy_runtime_card_id
        or legacy_inventory_id != shadow_inventory_id
        or legacy_runtime_card_id != shadow_runtime_card_id
    ):
        result = "FAILED"
        reason = "comparison_identity_mismatch"
    elif legacy_decision == "failed" or eligibility == "failed":
        result = "FAILED"
        reason = (
            "legacy_routing_failed"
            if legacy_decision == "failed"
            else "shadow_candidate_failed"
        )
    elif legacy_decision == "ambiguous" or eligibility == "ambiguous":
        result = "AMBIGUOUS"
        reason = (
            "legacy_routing_ambiguous"
            if legacy_decision == "ambiguous"
            else "shadow_candidate_ambiguous"
        )
    elif eligibility in {"unknown", "unsupported", ""}:
        result = "UNKNOWN"
        reason = (
            "shadow_candidate_unsupported"
            if eligibility == "unsupported"
            else "shadow_candidate_unknown"
        )
    elif not legacy_scenario:
        result = "UNKNOWN"
        reason = "legacy_scenario_unresolved"
    elif not candidate_scenario:
        result = "UNKNOWN"
        reason = "shadow_scenario_unresolved"
    elif legacy_scenario == candidate_scenario:
        result = "MATCH"
        reason = "scenario_exact_match"
    else:
        result = "MISMATCH"
        reason = "scenario_conflict"

    promotion_eligible = result == "MATCH" and eligibility == "eligible"
    return {
        "schema_version": SHADOW_COMPARISON_SCHEMA_VERSION,
        "artifact_version": SHADOW_ARTIFACT_VERSION,
        "comparison_id": f"comparison-{uuid.uuid4().hex[:12]}",
        "inventory_id": legacy_inventory_id or shadow_inventory_id,
        "runtime_card_id": legacy_runtime_card_id or shadow_runtime_card_id,
        "display_label": display_label,
        "stable_label": stable_label,
        "run_id": run_id,
        "device_name": device_name,
        "legacy_scenario": legacy_scenario,
        "shadow_candidate": candidate_scenario,
        "comparison_result": result,
        "comparison_reason": reason,
        "confidence": int(shadow_candidate.get("confidence", 0) or 0),
        "mapping_revision": shadow_candidate.get(
            "mapping_revision", resolved_versions.mapping_revision
        ),
        "policy_version": _text(shadow_candidate.get("policy_version"))
        or resolved_versions.policy_version,
        "registry_version": _text(shadow_candidate.get("registry_version"))
        or resolved_versions.registry_version,
        "shadow_validation_version": resolved_versions.shadow_validation_version,
        "timestamp": _timestamp(clock()),
        "legacy_authoritative": True,
        "legacy_fallback_used": legacy_result.get("fallback_used") is True,
        "shadow_eligibility": eligibility or "unknown",
        "promotion_eligible": promotion_eligible,
        "v10_traversal_allowed": False,
        "v10_routing_performed": False,
    }


def calculate_shadow_metrics(
    comparisons: Sequence[Mapping[str, Any]],
    *,
    eligible_inventory_count: int | None = None,
) -> dict[str, int | float]:
    counts = {
        result: sum(
            1 for item in comparisons if item.get("comparison_result") == result
        )
        for result in ALLOWED_COMPARISON_RESULTS
    }
    attempts = len(comparisons)
    comparable = counts["MATCH"] + counts["MISMATCH"]
    valid_records = attempts - counts["FAILED"]
    coverage_denominator = (
        eligible_inventory_count
        if isinstance(eligible_inventory_count, int) and eligible_inventory_count > 0
        else attempts
    )
    fallback_count = sum(
        1 for item in comparisons if item.get("legacy_fallback_used") is True
    )
    promotion_eligible_count = sum(
        1 for item in comparisons if item.get("promotion_eligible") is True
    )
    return {
        "attempt_count": attempts,
        "match_count": counts["MATCH"],
        "mismatch_count": counts["MISMATCH"],
        "unknown_count": counts["UNKNOWN"],
        "ambiguous_count": counts["AMBIGUOUS"],
        "failed_count": counts["FAILED"],
        "match_rate": _ratio(counts["MATCH"], comparable),
        "shadow_coverage": _ratio(valid_records, coverage_denominator),
        "fallback_count": fallback_count,
        "fallback_rate": _ratio(fallback_count, attempts),
        "promotion_eligible_count": promotion_eligible_count,
    }


def build_shadow_report(
    comparisons: Sequence[Mapping[str, Any]],
    *,
    versions: V10VersionSchema | Mapping[str, Any] | None = None,
    eligible_inventory_count: int | None = None,
    clock: Clock = _utc_now,
) -> dict[str, Any]:
    resolved_versions = (
        versions
        if isinstance(versions, V10VersionSchema)
        else V10VersionSchema.from_mapping(versions)
    )
    records = [dict(item) for item in comparisons]
    return {
        "schema_version": SHADOW_REPORT_SCHEMA_VERSION,
        "artifact_version": SHADOW_ARTIFACT_VERSION,
        "shadow_run_id": f"shadow-{uuid.uuid4().hex[:12]}",
        "mode": "comparison_only",
        "legacy_authoritative": True,
        "v10_routing_performed": False,
        "v10_traversal_allowed": False,
        "shadow_validation_version": resolved_versions.shadow_validation_version,
        "created_at": _timestamp(clock()),
        "metrics": calculate_shadow_metrics(
            records,
            eligible_inventory_count=eligible_inventory_count,
        ),
        "comparisons": records,
    }


def render_shadow_report_markdown(report: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    comparisons = report.get("comparisons") if isinstance(report.get("comparisons"), Sequence) else []
    inventory_id = _text(report.get("inventory_id"))
    if not inventory_id:
        seen_inventory_ids = [
            _text(item.get("inventory_id"))
            for item in comparisons
            if isinstance(item, Mapping) and _text(item.get("inventory_id"))
        ]
        inventory_id = seen_inventory_ids[0] if seen_inventory_ids else "-"

    run_ids = []
    device_names = []
    promotion_rows = []
    blocking_rows = []
    comparison_rows = []
    version_info = {
        "policy_version": "-",
        "registry_version": "-",
        "mapping_revision": "-",
        "shadow_validation_version": _text(report.get("shadow_validation_version")) or "-",
    }

    for item in comparisons:
        if not isinstance(item, Mapping):
            continue
        run_id = _text(item.get("run_id"))
        device_name = _text(item.get("device_name"))
        if run_id and run_id not in run_ids:
            run_ids.append(run_id)
        if device_name and device_name not in device_names:
            device_names.append(device_name)
        if version_info["policy_version"] == "-":
            version_info["policy_version"] = _text(item.get("policy_version")) or "-"
        if version_info["registry_version"] == "-":
            version_info["registry_version"] = _text(item.get("registry_version")) or "-"
        if version_info["mapping_revision"] == "-":
            version_info["mapping_revision"] = _text(item.get("mapping_revision")) or "-"

        label = _text(item.get("display_label")) or _text(item.get("stable_label")) or "-"
        result = _text(item.get("comparison_result")) or "-"
        row = (
            f"| {_markdown_escape(item.get('runtime_card_id'))} | {_markdown_escape(label)} "
            f"| {_markdown_escape(item.get('legacy_scenario'))} | {_markdown_escape(item.get('shadow_candidate'))} "
            f"| {_markdown_escape(result)} | {_markdown_escape(item.get('confidence'))} "
            f"| {_markdown_escape(item.get('comparison_reason'))} |"
        )
        comparison_rows.append(row)

        if item.get("promotion_eligible") is True:
            promotion_rows.append(
                f"| {_markdown_escape(label)} | {_markdown_escape(item.get('legacy_scenario'))} "
                f"| {_markdown_escape(item.get('shadow_candidate'))} | {_markdown_escape(item.get('confidence'))} |"
            )

        if result in {"MISMATCH", "UNKNOWN", "AMBIGUOUS", "FAILED"}:
            blocking_rows.append(
                f"| {_markdown_escape(label)} | {_markdown_escape(result)} | {_markdown_escape(item.get('legacy_scenario'))} "
                f"| {_markdown_escape(item.get('shadow_candidate'))} | {_markdown_escape(item.get('comparison_reason'))} |"
            )

    lines = [
        "# V10 Shadow Validation Report",
        "",
        "## Summary",
        f"- inventory_id: `{inventory_id}`",
        f"- run_id: `{', '.join(run_ids) if run_ids else '-'}`",
        f"- device: `{', '.join(device_names) if device_names else '-'}`",
        f"- total comparisons: `{metrics.get('attempt_count', 0)}`",
        f"- MATCH count: `{metrics.get('match_count', 0)}`",
        f"- MISMATCH count: `{metrics.get('mismatch_count', 0)}`",
        f"- UNKNOWN count: `{metrics.get('unknown_count', 0)}`",
        f"- AMBIGUOUS count: `{metrics.get('ambiguous_count', 0)}`",
        f"- FAILED count: `{metrics.get('failed_count', 0)}`",
        f"- match rate: `{_percent(metrics.get('match_rate', 0.0))}`",
        f"- shadow coverage: `{_percent(metrics.get('shadow_coverage', 0.0))}`",
        f"- fallback rate: `{_percent(metrics.get('fallback_rate', 0.0))}`",
        f"- promotion eligible count: `{metrics.get('promotion_eligible_count', 0)}`",
        "",
        "## Promotion Eligible",
        "| Label | Legacy Scenario | Shadow Candidate | Confidence |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(promotion_rows or ["| - | - | - | - |"])
    lines.extend(
        [
            "",
            "## Blocking / Needs Review",
            "| Label | Result | Legacy Scenario | Shadow Candidate | Reason |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(blocking_rows or ["| - | - | - | - | - |"])
    lines.extend(
        [
            "",
            "## Comparison Table",
            "| Runtime Card ID | Label | Legacy Scenario | Shadow Candidate | Result | Confidence | Reason |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(comparison_rows or ["| - | - | - | - | - | - | - |"])
    lines.extend(
        [
            "",
            "## Version Info",
            f"- policy_version: `{version_info['policy_version']}`",
            f"- registry_version: `{version_info['registry_version']}`",
            f"- mapping_revision: `{version_info['mapping_revision']}`",
            f"- shadow_validation_version: `{version_info['shadow_validation_version']}`",
            "",
        ]
    )
    return "\n".join(lines)


def write_shadow_report_artifact(
    report: Mapping[str, Any],
    *,
    artifact_dir: str | Path = V10_ARTIFACT_ROOT / "shadow",
) -> Path:
    output_dir = Path(artifact_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{report.get('shadow_run_id', 'shadow-unknown')}.json"
    output_path.write_text(
        json.dumps(dict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def write_shadow_markdown_artifact(
    report: Mapping[str, Any],
    *,
    artifact_dir: str | Path = V10_ARTIFACT_ROOT / "shadow",
) -> Path:
    output_dir = Path(artifact_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{report.get('shadow_run_id', 'shadow-unknown')}.md"
    output_path.write_text(render_shadow_report_markdown(report), encoding="utf-8")
    return output_path


def run_shadow_compare_if_enabled(
    v10_config: Mapping[str, Any] | None,
    comparison_inputs: Sequence[Mapping[str, Any]],
    *,
    eligible_inventory_count: int | None = None,
    artifact_dir: str | Path = V10_ARTIFACT_ROOT / "shadow",
    clock: Clock = _utc_now,
) -> dict[str, Any]:
    raw = v10_config if isinstance(v10_config, Mapping) else {}
    flags = raw.get("feature_flags") if isinstance(raw.get("feature_flags"), Mapping) else {}
    if flags.get("shadow_validation_enabled") is not True:
        return {"status": "disabled", "result": None, "artifact_path": ""}

    versions = V10VersionSchema.from_mapping(raw.get("versions"))
    comparisons = [
        compare_shadow_candidate(
            item.get("legacy", {}) if isinstance(item.get("legacy"), Mapping) else {},
            item.get("shadow_candidate", {})
            if isinstance(item.get("shadow_candidate"), Mapping)
            else {},
            versions=versions,
            clock=clock,
        )
        for item in comparison_inputs
    ]
    report = build_shadow_report(
        comparisons,
        versions=versions,
        eligible_inventory_count=eligible_inventory_count,
        clock=clock,
    )
    path = write_shadow_report_artifact(report, artifact_dir=artifact_dir)
    markdown_path = write_shadow_markdown_artifact(report, artifact_dir=artifact_dir)
    return {
        "status": "completed",
        "result": report,
        "artifact_path": str(path),
        "markdown_artifact_path": str(markdown_path),
    }
