"""Phase 10.3D deterministic final verdict reduction."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_sha256


VERDICT_POLICY_VERSION = "phase10.3d-verdict-policy-v1"
FINAL_COMPARATOR_VERSION = "phase10.3d-comparator-v1"
FINAL_COMPARISON_SCHEMA_VERSION = "talkback-final-comparison-result-v1"
VERDICTS = (
    "PASS",
    "PASS_WITH_LIMITATIONS",
    "REVIEW_REQUIRED",
    "FAIL",
    "INCOMPARABLE",
)

_ACCESSIBILITY_AGGREGATES = (
    "coverage_aggregate_delta",
    "identity_aggregate_delta",
    "traversal_aggregate_delta",
    "recovery_aggregate_delta",
    "reconciliation_delta",
)
_STRUCTURAL_DIMENSIONS = (
    "environment_delta",
    "scenario_delta",
    "coverage_aggregate_delta",
    "identity_aggregate_delta",
    "traversal_aggregate_delta",
    "recovery_aggregate_delta",
    "reconciliation_delta",
)
_LIMITATION_REVIEW = {
    "KNOWN_LIMITATION_CHANGED",
    "NEW_UNREVIEWED_FAILURE",
    "LIMITATION_SCOPE_EXPANDED",
    "LIMITATION_EXPIRED",
    "LIMITATION_BINDING_AMBIGUOUS",
}


def _status(result: Mapping[str, Any], name: str) -> str:
    value = result.get(name)
    return str(value.get("status") or "") if isinstance(value, Mapping) else ""


def _reason(code: str, dimension: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "dimension": dimension, **details}


def reduce_verdict(result: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[dict[str, Any]] = []
    compatibility = str(result.get("compatibility_grade") or "")
    errors = list(result.get("errors") or ())
    observation = result.get("observation_availability") or {}
    observation_status = str(observation.get("status") or "DATA_UNAVAILABLE")
    failure_counts = Counter(
        {
            str(key): int(value or 0)
            for key, value in (
                (result.get("accessibility_failure_summary") or {}).get(
                    "classification_counts", {}
                )
            ).items()
        }
    )
    bindings = list(
        (result.get("limitation_binding_deltas") or {}).get("bindings") or ()
    )
    binding_counts = Counter(
        str(item.get("status") or "") for item in bindings
    )
    known_count = (
        binding_counts["KNOWN_LIMITATION_UNCHANGED"]
        + binding_counts["DERIVATIVE_DUPLICATE"]
    )
    resolved_count = binding_counts["KNOWN_LIMITATION_RESOLVED"]
    review_count = len(result.get("review_items") or ())

    incomparable = bool(
        compatibility == "INCOMPARABLE"
        or errors
        or result.get("baseline_reference") is None
    )
    if compatibility == "INCOMPARABLE":
        reasons.append(
            _reason(
                "COMPATIBILITY_INCOMPARABLE",
                "compatibility",
                grade=compatibility,
            )
        )
    if errors:
        reasons.append(
            _reason("COMPARATOR_INPUT_ERROR", "input", count=len(errors))
        )
    if result.get("baseline_reference") is None:
        reasons.append(_reason("NO_SELECTED_BASELINE", "selection"))

    fail_reasons: list[dict[str, Any]] = []
    new_failures = failure_counts["NEW_ACCESSIBILITY_FAILURE"]
    if new_failures:
        fail_reasons.append(
            _reason(
                "NEW_ACCESSIBILITY_FAILURE",
                "node_text_speech",
                count=new_failures,
            )
        )
    for dimension in _ACCESSIBILITY_AGGREGATES:
        if _status(result, dimension) == "REGRESSED":
            fail_reasons.append(
                _reason("ACCESSIBILITY_AGGREGATE_REGRESSION", dimension)
            )

    review_reasons: list[dict[str, Any]] = []
    if compatibility in {"REVIEW_REQUIRED", "COMPATIBLE_FAMILY"}:
        review_reasons.append(
            _reason(
                "COMPATIBILITY_REVIEW_REQUIRED",
                "compatibility",
                grade=compatibility,
            )
        )
    if result.get("selection_tie"):
        review_reasons.append(
            _reason("MULTIPLE_BASELINE_TIE", "selection")
        )
    if observation_status != "COMPLETE":
        review_reasons.append(
            _reason(
                "OBSERVATION_DATA_UNAVAILABLE",
                "node_text_speech",
                status=observation_status,
                availability_reason=observation.get("reason"),
            )
        )
    if review_count:
        review_reasons.append(
            _reason("UNRESOLVED_REVIEW_ITEMS", "review", count=review_count)
        )
    ambiguous = failure_counts["AMBIGUOUS_FAILURE"]
    if ambiguous:
        review_reasons.append(
            _reason(
                "AMBIGUOUS_ACCESSIBILITY_FAILURE",
                "node_text_speech",
                count=ambiguous,
            )
        )
    structural_failures = failure_counts["STRUCTURAL_CHANGE"]
    if structural_failures:
        review_reasons.append(
            _reason(
                "STRUCTURAL_NODE_CHANGE",
                "node_matching",
                count=structural_failures,
            )
        )
    for dimension in _STRUCTURAL_DIMENSIONS:
        status = _status(result, dimension)
        if status in {"STRUCTURAL_CHANGE", "REVIEW_REQUIRED", "DATA_UNAVAILABLE"}:
            review_reasons.append(
                _reason(
                    "DIMENSION_REVIEW_REQUIRED",
                    dimension,
                    status=status,
                )
            )
    for status in sorted(_LIMITATION_REVIEW):
        if binding_counts[status]:
            review_reasons.append(
                _reason(
                    "LIMITATION_REVIEW_REQUIRED",
                    "known_limitation",
                    status=status,
                    count=binding_counts[status],
                )
            )

    if incomparable:
        overall = "INCOMPARABLE"
    elif fail_reasons:
        overall = "FAIL"
    elif review_reasons:
        overall = "REVIEW_REQUIRED"
    elif known_count:
        overall = "PASS_WITH_LIMITATIONS"
    else:
        overall = "PASS"
    reasons.extend(fail_reasons if overall == "FAIL" else ())
    reasons.extend(review_reasons if overall == "REVIEW_REQUIRED" else ())
    if overall == "PASS_WITH_LIMITATIONS":
        reasons.append(
            _reason(
                "REVIEWED_LIMITATIONS_RETAINED",
                "known_limitation",
                count=known_count,
            )
        )
    if overall == "PASS":
        reasons.append(_reason("NO_REGRESSION_OR_ACTIVE_LIMITATION", "overall"))

    profiler_status = _status(result, "profiler_aggregate_delta") or "DATA_UNAVAILABLE"
    recommendation = {
        "PASS": "Eligible for explicit human approval.",
        "PASS_WITH_LIMITATIONS": (
            "Eligible for explicit human approval with all reviewed raw failures retained."
        ),
        "REVIEW_REQUIRED": "Resolve every review item before approval.",
        "FAIL": "Do not approve; investigate and fix the new regression.",
        "INCOMPARABLE": "Do not approve from this comparison; establish a comparable baseline.",
    }[overall]
    return {
        "policy_version": VERDICT_POLICY_VERSION,
        "overall": overall,
        "automatic_approval": False,
        "raw_failure_count": sum(
            value
            for key, value in failure_counts.items()
            if key
            in {
                "REVIEWED_KNOWN_FAILURE",
                "NEW_ACCESSIBILITY_FAILURE",
                "AMBIGUOUS_FAILURE",
            }
        ),
        "new_failure_count": new_failures,
        "known_limitation_count": known_count,
        "resolved_failure_count": (
            failure_counts["RESOLVED_FAILURE"] + resolved_count
        ),
        "review_item_count": review_count,
        "performance_status": profiler_status,
        "performance_affects_accessibility_verdict": False,
        "reasons": reasons,
        "recommendation": recommendation,
    }


def finalize_comparison_result(result: Mapping[str, Any]) -> dict[str, Any]:
    verdict = reduce_verdict(result)
    previous_id = str(result.get("comparison_id") or "")
    identity = {
        "observation_comparison_id": previous_id,
        "final_comparator_version": FINAL_COMPARATOR_VERSION,
        "final_comparison_schema": FINAL_COMPARISON_SCHEMA_VERSION,
        "verdict_policy_version": VERDICT_POLICY_VERSION,
        "verdict_semantic_digest": canonical_sha256(verdict),
    }
    finalized = dict(result)
    finalized["comparison_schema"] = FINAL_COMPARISON_SCHEMA_VERSION
    finalized["observation_comparison_id"] = previous_id
    finalized["comparison_id"] = (
        "comparison_" + canonical_sha256(identity)[:24]
    )
    finalized["comparison_identity"] = {
        **dict(result.get("comparison_identity") or {}),
        "finalization": identity,
    }
    finalized["comparator_version"] = FINAL_COMPARATOR_VERSION
    finalized["verdict"] = verdict
    finalized["implementation_warnings"] = [
        item
        for item in result.get("implementation_warnings") or ()
        if item.get("code")
        not in {
            "FINAL_VERDICT_NOT_IMPLEMENTED_IN_PHASE_10_3B",
            "FINAL_VERDICT_DEFERRED_TO_PHASE_10_3D",
        }
    ]
    return finalized


__all__ = [
    "FINAL_COMPARATOR_VERSION",
    "FINAL_COMPARISON_SCHEMA_VERSION",
    "VERDICT_POLICY_VERSION",
    "VERDICTS",
    "finalize_comparison_result",
    "reduce_verdict",
]
