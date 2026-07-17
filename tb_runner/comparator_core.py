"""Deterministic, aggregate-only, read-only Comparator Core."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from tb_runner.aggregate_comparator import compare_aggregates
from tb_runner.baseline_selector import select_baseline
from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.comparison_compatibility import (
    assess_compatibility,
    build_compatibility_key,
)
from tb_runner.comparison_input import adapt_candidate
from tb_runner.comparator_schema import (
    COMPARATOR_VERSION,
    COMPARISON_RESULT_SCHEMA_VERSION,
    CompatibilityAssessment,
    CompatibilityGrade,
    ComparatorContractError,
    ComparatorInput,
    SelectionResult,
    reason,
)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _source_reference(source: ComparatorInput | None) -> dict[str, Any] | None:
    if source is None:
        return None
    return {
        "source_kind": source.source_kind.value,
        "source_id": source.source_id,
        "source_digest": source.source_digest,
        "schema_versions": source.schema_versions,
    }


def _data_availability(
    baseline: ComparatorInput | None,
    candidate: ComparatorInput,
) -> dict[str, Any]:
    candidate_availability = candidate.artifacts.get("data_availability") or {}
    baseline_availability = (
        baseline.artifacts.get("data_availability") if baseline else {}
    ) or {}
    return {
        "aggregate": {
            "baseline": baseline_availability.get("aggregate"),
            "candidate": candidate_availability.get("aggregate"),
            "status": "AVAILABLE" if baseline is not None else "DATA_UNAVAILABLE",
        },
        "node_text_speech": {
            "baseline": baseline_availability.get("node_text_speech"),
            "candidate": candidate_availability.get("node_text_speech"),
            "status": "DATA_UNAVAILABLE",
            "reason": "PHASE_10_3C_NOT_IMPLEMENTED",
        },
        "optional_observations": {
            "baseline": (
                baseline.artifacts.get("optional_observations") if baseline else {}
            ),
            "candidate": candidate.artifacts.get("optional_observations") or {},
        },
    }


def _comparison_identity(
    baseline: ComparatorInput | None,
    candidate: ComparatorInput,
    compatibility_key: Mapping[str, Any],
    selection: SelectionResult,
) -> dict[str, Any]:
    return {
        "comparison_schema": COMPARISON_RESULT_SCHEMA_VERSION,
        "comparator_version": COMPARATOR_VERSION,
        "baseline_source_id": baseline.source_id if baseline else None,
        "baseline_semantic_digest": (
            canonical_sha256(baseline.semantic_source()) if baseline else None
        ),
        "candidate_source_id": candidate.source_id,
        "candidate_semantic_digest": canonical_sha256(candidate.semantic_source()),
        "compatibility_key_source": compatibility_key.get("key_source"),
        "compatibility_grade": selection.assessment.grade.value,
        "version_relation": selection.assessment.version_relation.value,
        "tie": selection.tie,
    }


def compare_selected_inputs(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
    *,
    assessment: CompatibilityAssessment | None = None,
    generated_at: str | None = None,
    selection_rationale: tuple[dict[str, Any], ...] = (),
    rejected_baselines: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    resolved_assessment = assessment or assess_compatibility(baseline, candidate)
    selection = SelectionResult(
        baseline,
        {
            "baseline_id": baseline.source_id,
            "revision": baseline.provenance.get("revision"),
            "repository_state": baseline.provenance.get(
                "repository_state", "APPROVED"
            ),
        },
        resolved_assessment,
        selection_rationale,
        rejected_baselines,
    )
    return _build_result(candidate, selection, generated_at=generated_at)


def _empty_deltas(reason_code: str) -> dict[str, Any]:
    names = (
        "environment_delta",
        "app_version_delta",
        "scenario_delta",
        "coverage_aggregate_delta",
        "identity_aggregate_delta",
        "traversal_aggregate_delta",
        "recovery_aggregate_delta",
        "reconciliation_delta",
        "profiler_aggregate_delta",
        "limitation_summary_delta",
    )
    return {
        name: {"status": "DATA_UNAVAILABLE", "reason": reason_code}
        for name in names
    }


def _build_result(
    candidate: ComparatorInput,
    selection: SelectionResult,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    baseline = selection.selected
    compatibility_key = build_compatibility_key(candidate).to_dict()
    identity = _comparison_identity(
        baseline, candidate, compatibility_key, selection
    )
    comparison_id = "comparison_" + canonical_sha256(identity)[:24]
    deltas = (
        compare_aggregates(baseline, candidate)
        if baseline is not None
        else _empty_deltas("NO_SELECTED_BASELINE")
    )
    review_items = list(selection.assessment.review_items)
    if selection.tie:
        review_items.append(reason("MULTIPLE_BASELINE_TIE"))
    if baseline is None:
        review_items.append(reason("BASELINE_SELECTION_UNRESOLVED"))
    warnings = [
        reason("NODE_LEVEL_COMPARISON_DEFERRED_TO_PHASE_10_3C"),
        reason("FINAL_VERDICT_NOT_IMPLEMENTED_IN_PHASE_10_3B"),
    ]
    warnings.extend(candidate.diagnostics)
    if baseline is not None:
        warnings.extend(baseline.diagnostics)
    return {
        "comparison_schema": COMPARISON_RESULT_SCHEMA_VERSION,
        "comparison_id": comparison_id,
        "generated_at": generated_at or _utc_now(),
        "comparator_version": COMPARATOR_VERSION,
        "comparison_identity": identity,
        "baseline_reference": _source_reference(baseline),
        "candidate_reference": _source_reference(candidate),
        "compatibility_key": compatibility_key,
        "selected_baseline_rationale": list(selection.rationale),
        "rejected_baselines": list(selection.rejected),
        "selection_tie": selection.tie,
        "compatibility_grade": selection.assessment.grade.value,
        "compatibility_reasons": list(selection.assessment.reasons),
        **deltas,
        "data_availability": _data_availability(baseline, candidate),
        "review_items": review_items,
        "implementation_warnings": warnings,
        "errors": list(selection.errors),
    }


def _error_result(
    error: ComparatorContractError,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    identity = {
        "comparison_schema": COMPARISON_RESULT_SCHEMA_VERSION,
        "comparator_version": COMPARATOR_VERSION,
        "error": error.to_dict(),
    }
    empty = _empty_deltas(error.code)
    return {
        "comparison_schema": COMPARISON_RESULT_SCHEMA_VERSION,
        "comparison_id": "comparison_" + canonical_sha256(identity)[:24],
        "generated_at": generated_at or _utc_now(),
        "comparator_version": COMPARATOR_VERSION,
        "comparison_identity": identity,
        "baseline_reference": None,
        "candidate_reference": None,
        "compatibility_key": {
            "status": "UNUSABLE",
            "digest": None,
            "key_source": {},
            "missing_fields": [],
            "incompatible_fields": [error.code],
        },
        "selected_baseline_rationale": [],
        "rejected_baselines": [],
        "selection_tie": False,
        "compatibility_grade": CompatibilityGrade.INCOMPARABLE.value,
        "compatibility_reasons": [error.to_dict()],
        **empty,
        "data_availability": {
            "aggregate": {"status": "DATA_UNAVAILABLE", "reason": error.code},
            "node_text_speech": {
                "status": "DATA_UNAVAILABLE",
                "reason": error.code,
            },
            "optional_observations": {},
        },
        "review_items": [],
        "implementation_warnings": [
            reason("COMPARATOR_INPUT_REJECTED"),
            reason("FINAL_VERDICT_NOT_IMPLEMENTED_IN_PHASE_10_3B"),
        ],
        "errors": [error.to_dict()],
    }


def run_comparator_core(
    candidate_source: str | Path | Mapping[str, Any] | ComparatorInput,
    repository_root: str | Path,
    *,
    environment_profile: str | Path | Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Run selection and aggregate comparison without changing any input."""
    try:
        candidate = (
            candidate_source
            if isinstance(candidate_source, ComparatorInput)
            else adapt_candidate(
                candidate_source, environment_profile=environment_profile
            )
        )
        selection = select_baseline(candidate, repository_root)
        return _build_result(candidate, selection, generated_at=generated_at)
    except ComparatorContractError as exc:
        return _error_result(exc, generated_at=generated_at)


def comparison_result_json(result: Mapping[str, Any]) -> str:
    return canonical_json(result)


__all__ = [
    "compare_selected_inputs",
    "comparison_result_json",
    "run_comparator_core",
]
