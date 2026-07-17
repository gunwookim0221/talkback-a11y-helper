"""Additive Phase 10.3C node-level comparator orchestration."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from tb_runner.canonical_json import canonical_sha256
from tb_runner.comparator_schema import ComparatorInput, reason
from tb_runner.coverage_transition_comparator import compare_coverage_transitions
from tb_runner.limitation_matcher import bind_limitations
from tb_runner.node_matcher import match_observations
from tb_runner.observation_adapter import load_observation_set
from tb_runner.observation_bundle import (
    ObservationBundleError,
    find_portable_bundle,
)
from tb_runner.observation_schema import (
    OBSERVATION_COMPARATOR_VERSION,
    ObservationAvailability,
    ObservationSet,
)
from tb_runner.text_speech_comparator import classify_text_speech


_SET_CACHE: dict[tuple[str, str, str], ObservationSet] = {}


def _workspace_root(path: Path) -> Path:
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / "qa_frontend_runs").is_dir() or (candidate / ".baseline-artifacts").is_dir():
            return candidate
    return resolved


def _load(source: ComparatorInput, root: Path) -> ObservationSet:
    root = _workspace_root(root)
    artifact_key = canonical_sha256(source.artifacts)
    environment_key = canonical_sha256(source.environment)
    key = (
        source.source_id,
        source.source_digest + artifact_key + environment_key,
        str(root),
    )
    if key not in _SET_CACHE:
        try:
            declared = source.artifacts.get("optional_observations") or {}
            portable_allowed = (
                source.source_kind.value == "BASELINE"
                or any(
                    isinstance(item, dict)
                    and item.get("status") == "AVAILABLE"
                    for item in declared.values()
                )
            )
            portable = (
                find_portable_bundle(source, root)
                if portable_allowed
                else None
            )
        except ObservationBundleError as exc:
            portable = ObservationSet(
                observation_set_schema="talkback-comparison-observation-set-v1",
                source_kind=source.source_kind.value,
                source_id=source.source_id,
                locale=str(source.environment.get("locale") or ""),
                app_package=str(source.environment.get("app_package") or ""),
                app_version_name=source.environment.get("app_version_name"),
                app_version_code=source.environment.get("app_version_code"),
                availability=ObservationAvailability.CORRUPT,
                source_quality="PORTABLE_BUNDLE_CORRUPT",
                observations=(),
                artifacts=(),
                observation_identity_digest=None,
                diagnostics=({"code": "PORTABLE_BUNDLE_CORRUPT", "detail": str(exc)},),
            )
        _SET_CACHE[key] = portable or load_observation_set(
                source,
                qa_runs_root=root / "qa_frontend_runs",
                artifact_root=root / ".baseline-artifacts",
            )
    return _SET_CACHE[key]


def _data_unavailable(
    baseline: ObservationSet,
    candidate: ObservationSet,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "observation_availability": {
            "status": "DATA_UNAVAILABLE",
            "reason": reason_code,
            "baseline": baseline.public_summary(),
            "candidate": candidate.public_summary(),
        },
        "node_match_summary": {"status": "DATA_UNAVAILABLE", "reason": reason_code},
        "node_deltas": [{"node_delta": "DATA_UNAVAILABLE", "confidence": "INDETERMINATE"}],
        "text_speech_deltas": [{"classification": "DATA_UNAVAILABLE", "equivalent": False}],
        "coverage_cohort_transitions": {"status": "DATA_UNAVAILABLE", "reason": reason_code},
        "limitation_binding_deltas": {"status": "DATA_UNAVAILABLE", "reason": reason_code},
        "accessibility_failure_summary": {
            "status": "DATA_UNAVAILABLE",
            "classification_counts": {"DATA_UNAVAILABLE": 1},
        },
        "observation_artifact_references": {
            "baseline": baseline.artifacts,
            "candidate": candidate.artifacts,
        },
        "observation_review_items": [reason(reason_code)],
    }


def compare_observation_sets(
    baseline: ObservationSet,
    candidate: ObservationSet,
    limitations: tuple[dict[str, Any], ...] = (),
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if baseline.locale != candidate.locale:
        return _data_unavailable(baseline, candidate, "OBSERVATION_LOCALE_MISMATCH")
    if baseline.availability != candidate.availability:
        return _data_unavailable(baseline, candidate, "ASYMMETRIC_OBSERVATION_AVAILABILITY")
    if baseline.availability != ObservationAvailability.COMPLETE:
        return _data_unavailable(
            baseline,
            candidate,
            f"OBSERVATION_{baseline.availability.value}",
        )
    matches = match_observations(baseline.observations, candidate.observations)
    left = {item.observation_id: item for item in baseline.observations}
    right = {item.observation_id: item for item in candidate.observations}
    limitation_rows = bind_limitations(
        limitations,
        baseline.observations,
        candidate.observations,
        generated_at=generated_at,
        baseline_app_version_name=baseline.app_version_name,
        candidate_app_version_name=candidate.app_version_name,
    )
    known_candidate_ids = {
        observation_id
        for row in limitation_rows
        if row["status"] in {"KNOWN_LIMITATION_UNCHANGED", "DERIVATIVE_DUPLICATE"}
        for observation_id in row["candidate_observation_ids"]
    }
    text_rows: list[dict[str, Any]] = []
    failure_counts: Counter[str] = Counter()
    for match in matches:
        base = left.get((match.get("baseline") or {}).get("observation_id"))
        cand = right.get((match.get("candidate") or {}).get("observation_id"))
        text = classify_text_speech(
            base,
            cand,
            known_empty_visible=bool(cand and cand.observation_id in known_candidate_ids),
            ambiguous=bool(match.get("ambiguity")),
        )
        text_rows.append(text)
        if (
            match["node_delta"] == "ADDED_NODE"
            and cand
            and cand.focusable
            and not cand.visible_text
            and not cand.content_description
        ):
            failure = "NEW_ACCESSIBILITY_FAILURE"
        elif match["node_delta"] in {"ADDED_NODE", "REMOVED_NODE", "SPLIT_NODE", "MERGED_NODE"}:
            failure = "STRUCTURAL_CHANGE"
        elif match["node_delta"] == "AMBIGUOUS_MATCH":
            failure = "AMBIGUOUS_FAILURE"
        elif text["classification"] in {"RESOLVED_EMPTY_VISIBLE"}:
            failure = "RESOLVED_FAILURE"
        elif cand and cand.observation_id in known_candidate_ids:
            failure = "REVIEWED_KNOWN_FAILURE"
        elif (
            text["classification"] in {
                "NEW_EMPTY_VISIBLE",
                "BOTH_CHANGED_DIFFERENT",
            }
            or (
                text["classification"] == "SPEECH_MISSING"
                and base
                and bool(base.talkback_speech)
            )
        ) or match["node_delta"] == "SAME_NODE_CHANGED_ROLE" or (
            base
            and cand
            and base.coverage_status.upper() == "COVERED"
            and cand.coverage_status.upper() == "MISSED"
        ) or (
            cand
            and cand.raw_result.upper() == "FAIL"
            and (not base or base.raw_result.upper() != "FAIL")
        ):
            failure = "NEW_ACCESSIBILITY_FAILURE"
        elif (
            cand
            and cand.raw_result.upper() == "FAIL"
            and bool(cand.mismatch_type)
        ):
            failure = "AMBIGUOUS_FAILURE"
        else:
            failure = "NO_ACCESSIBILITY_FAILURE"
        failure_counts[failure] += 1
    node_counts = Counter(item["node_delta"] for item in matches)
    coverage = compare_coverage_transitions(
        matches, baseline.observations, candidate.observations
    )
    review_items = [
        reason(
            "OBSERVATION_MATCH_REVIEW_REQUIRED",
            baseline=item.get("baseline"),
            candidate=item.get("candidate"),
        )
        for item in matches
        if item["node_delta"] == "AMBIGUOUS_MATCH" or item["confidence"] == "LOW"
    ]
    review_items.extend(
        reason("LIMITATION_BINDING_REVIEW_REQUIRED", issue_id=item.get("issue_id"), status=item["status"])
        for item in limitation_rows
        if item["status"] in {
            "KNOWN_LIMITATION_CHANGED",
            "NEW_UNREVIEWED_FAILURE",
            "LIMITATION_SCOPE_EXPANDED",
            "LIMITATION_EXPIRED",
            "LIMITATION_BINDING_AMBIGUOUS",
        }
    )
    return {
        "observation_availability": {
            "status": "COMPLETE",
            "baseline": baseline.public_summary(),
            "candidate": candidate.public_summary(),
        },
        "node_match_summary": {
            "status": "AVAILABLE",
            "total": len(matches),
            "match_type_counts": dict(sorted(Counter(item["match_type"] for item in matches).items())),
            "node_delta_counts": dict(sorted(node_counts.items())),
        },
        "node_deltas": matches,
        "text_speech_deltas": text_rows,
        "coverage_cohort_transitions": {"status": "AVAILABLE", **coverage},
        "limitation_binding_deltas": {
            "status": "AVAILABLE",
            "bindings": limitation_rows,
            "status_counts": dict(sorted(Counter(item["status"] for item in limitation_rows).items())),
        },
        "accessibility_failure_summary": {
            "status": "AVAILABLE",
            "classification_counts": dict(sorted(failure_counts.items())),
        },
        "observation_artifact_references": {
            "baseline": baseline.artifacts,
            "candidate": candidate.artifacts,
        },
        "observation_review_items": review_items,
    }


def enrich_comparison_result(
    result: dict[str, Any],
    baseline: ComparatorInput | None,
    candidate: ComparatorInput,
    repository_root: str | Path,
) -> dict[str, Any]:
    if baseline is None:
        unavailable = ObservationSet(
            observation_set_schema="talkback-comparison-observation-set-v1",
            source_kind="BASELINE",
            source_id="unselected",
            locale=str(candidate.environment.get("locale") or ""),
            app_package=str(candidate.environment.get("app_package") or ""),
            app_version_name=None,
            app_version_code=None,
            availability=ObservationAvailability.UNAVAILABLE,
            source_quality="NO_SELECTED_BASELINE",
            observations=(),
            artifacts=(),
            observation_identity_digest=None,
        )
        candidate_set = _load(candidate, Path(repository_root))
        additive = _data_unavailable(unavailable, candidate_set, "NO_SELECTED_BASELINE")
    else:
        baseline_set = _load(baseline, Path(repository_root))
        candidate_set = _load(candidate, Path(repository_root))
        additive = compare_observation_sets(
            baseline_set,
            candidate_set,
            baseline.reviewed_limitations,
            generated_at=result.get("generated_at"),
        )
    enriched = dict(result)
    aggregate_id = result["comparison_id"]
    observation_identity = {
        "aggregate_comparison_id": aggregate_id,
        "observation_comparator_version": OBSERVATION_COMPARATOR_VERSION,
        "baseline_observation_digest": additive["observation_availability"]["baseline"].get("observation_identity_digest"),
        "candidate_observation_digest": additive["observation_availability"]["candidate"].get("observation_identity_digest"),
    }
    enriched["aggregate_comparison_id"] = aggregate_id
    enriched["comparison_id"] = "comparison_" + canonical_sha256(observation_identity)[:24]
    enriched["comparison_identity"] = {
        **result["comparison_identity"],
        "observation": observation_identity,
    }
    enriched.update(additive)
    enriched["review_items"] = [
        *result.get("review_items", ()),
        *additive["observation_review_items"],
    ]
    enriched["implementation_warnings"] = [
        item for item in result.get("implementation_warnings", ())
        if item.get("code") != "NODE_LEVEL_COMPARISON_DEFERRED_TO_PHASE_10_3C"
    ]
    enriched["implementation_warnings"].append(reason("FINAL_VERDICT_DEFERRED_TO_PHASE_10_3D"))
    enriched["data_availability"] = {
        **result.get("data_availability", {}),
        "node_text_speech": additive["observation_availability"],
    }
    return enriched


__all__ = ["compare_observation_sets", "enrich_comparison_result"]
