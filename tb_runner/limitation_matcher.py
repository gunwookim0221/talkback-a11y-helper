"""Exact, scope-aware known-limitation binding without raw-failure suppression."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from tb_runner.observation_normalizer import parse_bounds
from tb_runner.observation_schema import CanonicalObservation


def _is_failure(item: CanonicalObservation) -> bool:
    return item.raw_result.upper() == "FAIL" or item.mismatch_type.upper() in {
        "EMPTY_VISIBLE",
        "EMPTY_SPEECH",
        "LABEL_MISMATCH",
    }


def _scope(
    limitation: Mapping[str, Any],
    observation: CanonicalObservation,
    app_version_name: str | None = None,
) -> bool:
    scenarios = limitation.get("scenario_scope") or [limitation.get("scenario_id")]
    environment = limitation.get("environment_scope") or {}
    locale = str(environment.get("locale") or "")
    release = str(environment.get("app_release_train") or "")
    return (
        observation.scenario_id in scenarios
        and (not locale or locale == observation.locale)
        and (not release or not app_version_name or release == app_version_name)
    )


def _signature(
    limitation: Mapping[str, Any],
    observation: CanonicalObservation,
) -> tuple[bool, list[str]]:
    signature = limitation.get("match_signature") or limitation
    drift: list[str] = []
    checks = (
        ("resource_id", observation.resource_id),
        ("class", observation.class_name),
        ("mismatch_type", observation.mismatch_type),
        ("stop_reason", observation.stop_reason),
    )
    for field, actual in checks:
        expected = str(signature.get(field) or limitation.get(field) or "")
        if expected and expected != str(actual or ""):
            drift.append(field.upper() + "_DRIFT")
    expected_bounds = parse_bounds(signature.get("bounds") or limitation.get("bounds"))
    if expected_bounds and expected_bounds != observation.bounds:
        drift.append("BOUNDS_DRIFT")
    return not drift, drift


def bind_limitations(
    limitations: Iterable[Mapping[str, Any]],
    baseline: Iterable[CanonicalObservation],
    candidate: Iterable[CanonicalObservation],
    *,
    generated_at: str | None = None,
    baseline_app_version_name: str | None = None,
    candidate_app_version_name: str | None = None,
) -> list[dict[str, Any]]:
    base = list(baseline)
    cand = list(candidate)
    now = datetime.fromisoformat((generated_at or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
    results: list[dict[str, Any]] = []
    bound_candidate_ids: set[str] = set()
    handled_candidate_ids: set[str] = set()
    for limitation in limitations:
        drift: list[str] = []
        scoped_base = [
            item for item in base
            if _scope(limitation, item, baseline_app_version_name)
            and _signature(limitation, item)[0]
        ]
        scoped_candidate = [
            item for item in cand
            if _scope(limitation, item, candidate_app_version_name)
        ]
        scope_agnostic_candidate = [
            item
            for item in cand
            if _scope(limitation, item)
            and _signature(limitation, item)[0]
        ]
        exact = [item for item in scoped_candidate if _signature(limitation, item)[0]]
        referenced_transactions = {
            str(reference).split("#transaction=", 1)[1]
            for reference in limitation.get("evidence_references") or ()
            if "#transaction=" in str(reference)
        }
        transaction_exact = [
            item for item in exact if item.transaction_id in referenced_transactions
        ]
        if transaction_exact:
            exact = transaction_exact
        expired = False
        if limitation.get("expires_at"):
            expired = datetime.fromisoformat(str(limitation["expires_at"]).replace("Z", "+00:00")) < now
        if expired and exact:
            status = "LIMITATION_EXPIRED"
        elif len(exact) > 1 and limitation.get("derivation") != "DUPLICATE_DERIVED_FAILURE":
            status = "LIMITATION_BINDING_AMBIGUOUS"
        elif exact:
            item = exact[0]
            bound_candidate_ids.add(item.observation_id)
            status = (
                "DERIVATIVE_DUPLICATE"
                if limitation.get("derivation") == "DUPLICATE_DERIVED_FAILURE"
                or limitation.get("issue_type") == "DUPLICATE_DERIVED_FAILURE"
                else "KNOWN_LIMITATION_UNCHANGED"
            )
        elif scoped_candidate:
            drift = sorted({reason for item in scoped_candidate for reason in _signature(limitation, item)[1]})
            status = "KNOWN_LIMITATION_CHANGED" if drift else "LIMITATION_BINDING_AMBIGUOUS"
        elif scope_agnostic_candidate:
            status = "LIMITATION_SCOPE_EXPANDED"
            drift = ["APP_VERSION_SCOPE_DRIFT"]
            handled_candidate_ids.update(
                item.observation_id for item in scope_agnostic_candidate
            )
        elif scoped_base:
            drift = []
            status = "KNOWN_LIMITATION_RESOLVED"
        else:
            drift = []
            status = "KNOWN_LIMITATION_RESOLVED"
        results.append(
            {
                "issue_id": limitation.get("issue_id"),
                "status": status,
                "raw_fail_retained": True,
                "baseline_observation_ids": [item.observation_id for item in scoped_base],
                "candidate_observation_ids": [item.observation_id for item in exact],
                "review_status": limitation.get("review_status"),
                "expiration": limitation.get("expires_at"),
                "evidence_references": list(limitation.get("evidence_references") or ()),
                "review_reasons": drift,
            }
        )
    issue_scopes = {
        (item.get("issue_id"), scenario)
        for item in limitations
        for scenario in (item.get("scenario_scope") or [item.get("scenario_id")])
    }
    for item in cand:
        if (
            _is_failure(item)
            and item.observation_id not in bound_candidate_ids
            and item.observation_id not in handled_candidate_ids
        ):
            unchanged_unreviewed = any(
                _is_failure(previous)
                and previous.scenario_id == item.scenario_id
                and previous.resource_id == item.resource_id
                and previous.class_name == item.class_name
                and previous.bounds == item.bounds
                and previous.mismatch_type == item.mismatch_type
                for previous in base
            )
            if unchanged_unreviewed:
                continue
            same_issue_other_scope = any(
                limitation.get("issue_id")
                and _signature(limitation, item)[0]
                and (limitation.get("issue_id"), item.scenario_id) not in issue_scopes
                for limitation in limitations
            )
            results.append(
                {
                    "issue_id": None,
                    "status": "LIMITATION_SCOPE_EXPANDED" if same_issue_other_scope else "NEW_UNREVIEWED_FAILURE",
                    "raw_fail_retained": True,
                    "baseline_observation_ids": [],
                    "candidate_observation_ids": [item.observation_id],
                    "review_status": "UNREVIEWED",
                    "expiration": None,
                    "evidence_references": [],
                    "review_reasons": ["NO_EXACT_LIMITATION_BINDING"],
                }
            )
    return results


__all__ = ["bind_limitations"]
