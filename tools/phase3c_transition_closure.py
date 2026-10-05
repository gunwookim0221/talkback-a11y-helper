"""Offline Phase 3 cross-layer audit; no client, action selector or executor."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.state_equality import evaluate_state_equality
from tb_runner.state_observation import StateObservation

CONTRADICTIONS = (
    "SOURCE_STATE_SNAPSHOT_MISMATCH_COUNT",
    "ACTION_NOT_IN_SOURCE_SNAPSHOT_COUNT",
    "RESULT_STATE_FINGERPRINT_MISMATCH_COUNT",
    "OUTCOME_STATE_EQUALITY_MISMATCH_COUNT",
    "VIEWPORT_OUTCOME_MISMATCH_COUNT",
    "FOCUS_OUTCOME_MISMATCH_COUNT",
    "ACK_RECONCILIATION_MISMATCH_COUNT",
    "TRANSITION_HASH_REPLAY_MISMATCH_COUNT",
)
COUNTERS = (
    "SOURCE_STATE_SNAPSHOT_MISMATCH_COUNT", "ACTION_NOT_IN_SOURCE_SNAPSHOT_COUNT",
    "RESULT_STATE_FINGERPRINT_MISMATCH_COUNT", "OUTCOME_STATE_EQUALITY_MISMATCH_COUNT",
    "VIEWPORT_OUTCOME_MISMATCH_COUNT", "FOCUS_OUTCOME_MISMATCH_COUNT",
    "ACK_RECONCILIATION_MISMATCH_COUNT", "TRANSITION_HASH_REPLAY_MISMATCH_COUNT",
    "INCOMPATIBLE_SCHEMA_COUNT", "STATE_COLLISION_COUNT", "CANDIDATE_ID_COLLISION_COUNT",
    "TRANSITION_ID_COLLISION_COUNT", "UNSAFE_STATE_BIND_COUNT", "UNSAFE_TRANSITION_BIND_COUNT",
    "UNEXPECTED_CANDIDATE_CHURN_COUNT", "UNEXPECTED_TRANSITION_CHURN_COUNT",
    "UNEXPECTED_TRANSITION_SPLIT_COUNT", "CROSS_LAYER_CONTRADICTION_COUNT",
    "ERROR_TRANSITION_COUNT",
)


def _ack_status(transition: Mapping[str, Any]) -> str:
    ack = transition.get("command_ack") or {}
    return str((ack.get("normalized") or {}).get("status") or "UNKNOWN")


def _expected_outcome(transition: Mapping[str, Any]) -> str:
    if transition.get("outcome") == "ERROR":
        return "ERROR"
    eq = transition.get("equality_relation") or {}
    if (not transition.get("source_state_id") or not transition.get("resulting_state_id")
            or eq.get("verdict") == "AMBIGUOUS" or transition.get("state_binding_mismatch")):
        return "AMBIGUOUS_RESULT"
    if eq.get("verdict") == "DIFFERENT":
        return "STATE_CHANGED"
    if eq.get("verdict") != "SAME":
        return "AMBIGUOUS_RESULT"
    if eq.get("viewport_equal") is False:
        return "VIEWPORT_CHANGED"
    if transition.get("actual_focus_moved") is True:
        return "FOCUS_ONLY"
    if _ack_status(transition) == "FAIL":
        return "ACTION_FAILED"
    return "SAME_STATE"


def _occurrence(case: Mapping[str, Any]) -> str:
    transition = case.get("transition") or {}
    return str(transition.get("occurrence_id") or "<missing>")


def _candidate_identity(candidate: Mapping[str, Any]) -> str:
    return canonical_json({k: candidate.get(k) for k in ("state_id", "action_kind", "target_identity")})


def audit_transitions(cases: list[Mapping[str, Any]], *,
                      historical_candidate_churn: int = 0,
                      historical_transition_churn: int = 0) -> dict[str, Any]:
    """Validate saved snapshots, observations and transition documents.

    Each case has `transition`, `source_snapshot`, `result_snapshot` (nullable),
    `source_observation`, `result_observation` (nullable) and optional `before_raw`.
    Unsupported versions are reported and skipped rather than reinterpreted.
    """
    counts = {key: 0 for key in COUNTERS}
    counts["UNEXPECTED_CANDIDATE_CHURN_COUNT"] = int(historical_candidate_churn)
    counts["UNEXPECTED_TRANSITION_CHURN_COUNT"] = int(historical_transition_churn)
    details: list[dict[str, Any]] = []
    state_core: dict[str, str] = {}
    candidate_ids: dict[str, str] = {}
    transition_ids: dict[str, str] = {}
    occurrence_ids: dict[str, set[str]] = defaultdict(set)
    case_faults: dict[str, bool] = {}
    classifications: dict[str, str] = {}
    groups: dict[str, list[tuple[str, str, Mapping[str, Any]]]] = defaultdict(list)

    for case in cases:
        t = case.get("transition") or {}
        occurrence = _occurrence(case)
        issues: list[str] = []
        if t.get("schema_version") != "transition-observation-v1":
            counts["INCOMPATIBLE_SCHEMA_COUNT"] += 1
            details.append(dict(occurrence_id=occurrence, status="INCOMPATIBLE_SCHEMA",
                                observed=t.get("schema_version")))
            continue
        source = case.get("source_snapshot") or {}
        result = case.get("result_snapshot")
        source_obs = case.get("source_observation")
        result_obs = case.get("result_observation")

        def issue(counter: str) -> None:
            name = counter.removesuffix("_COUNT")
            if name not in issues:
                counts[counter] += 1
                issues.append(name)

        source_doc = (source_obs.to_dict() if isinstance(source_obs, StateObservation) else source_obs)
        if source_doc is not None:
            source_fp = source_doc.get("fingerprint") or {}
            if (source_doc.get("observation_id") != source.get("observation_id")
                    or source_fp.get("fingerprint_hash") != source.get("fingerprint_hash")):
                issue("SOURCE_STATE_SNAPSHOT_MISMATCH_COUNT")

        if t.get("source_state_id") != source.get("state_id"):
            issue("SOURCE_STATE_SNAPSHOT_MISMATCH_COUNT")
        binding = t.get("action_binding") or {}
        cid = t.get("action_candidate_id")
        if binding.get("status") == "MAPPED":
            found = [c for c in source.get("candidates", []) if c.get("candidate_id") == cid]
            if (not cid or len(found) != 1
                    or found[0].get("state_id") != source.get("state_id")
                    or found[0].get("action_kind") != t.get("action_kind")):
                issue("ACTION_NOT_IN_SOURCE_SNAPSHOT_COUNT")
        elif cid is not None or binding.get("candidate_id") is not None:
            issue("ACTION_NOT_IN_SOURCE_SNAPSHOT_COUNT")

        result_ref = t.get("resulting_fingerprint")
        if result_obs is None:
            if result_ref is not None:
                issue("RESULT_STATE_FINGERPRINT_MISMATCH_COUNT")
        else:
            result_doc = result_obs.to_dict() if isinstance(result_obs, StateObservation) else result_obs
            result_fp_hash = result_doc.get("fingerprint", {}).get("fingerprint_hash")
            result_snapshot_id = result.get("state_id") if result is not None else None
            result_snapshot_obsid = result.get("observation_id") if result is not None else None
            result_mismatch = (not result_ref or result_ref.get("fingerprint_hash") != result_fp_hash
                or result_ref.get("state_id") != result_snapshot_id
                or result_ref.get("observation_id") != result_doc.get("observation_id")
                or result_snapshot_obsid != result_doc.get("observation_id"))
            if result is not None:
                result_mismatch = result_mismatch or result.get("fingerprint_hash") != result_fp_hash
            if result_mismatch:
                issue("RESULT_STATE_FINGERPRINT_MISMATCH_COUNT")
            result_sid = result_snapshot_id
            if t.get("resulting_state_id") != result_sid and not (
                    t.get("state_binding_mismatch") is True and t.get("resulting_state_id") is None):
                issue("RESULT_STATE_FINGERPRINT_MISMATCH_COUNT")

        if t.get("outcome") != _expected_outcome(t):
            issue("OUTCOME_STATE_EQUALITY_MISMATCH_COUNT")
        eq = t.get("equality_relation") or {}
        expected_viewport = None if eq.get("viewport_equal") is None else not eq["viewport_equal"]
        if t.get("viewport_changed") != expected_viewport:
            issue("VIEWPORT_OUTCOME_MISMATCH_COUNT")
        focus = t.get("focus") or {}
        if (focus.get("actual_focus_moved") != t.get("actual_focus_moved")
                or t.get("outcome") == "FOCUS_ONLY" and t.get("actual_focus_moved") is not True
                or t.get("actual_focus_moved") is True and focus.get("status") != "CONFIRMED_MOVED"):
            issue("FOCUS_OUTCOME_MISMATCH_COUNT")
        ack = _ack_status(t)
        no_observed_change = (eq.get("verdict") == "SAME" and eq.get("viewport_equal") is True
                              and t.get("actual_focus_moved") is not True)
        definitive = bool(t.get("source_state_id") and t.get("resulting_state_id")
                          and t.get("definitive_state_binding"))
        if ((t.get("outcome") == "ACTION_FAILED" and ack != "FAIL")
                or (ack == "FAIL" and no_observed_change and definitive and t.get("outcome") != "ACTION_FAILED")):
            issue("ACK_RECONCILIATION_MISMATCH_COUNT")

        semantic = t.get("semantic_identity")
        if (not isinstance(semantic, Mapping)
                or t.get("semantic_hash") != canonical_sha256(semantic)
                or t.get("transition_id") != "transition:" + canonical_sha256(
                    dict(occurrence_id=occurrence, semantic=semantic))):
            issue("TRANSITION_HASH_REPLAY_MISMATCH_COUNT")
        occurrence_ids[occurrence].add(str(t.get("transition_id")))

        snapshots = [source] + ([result] if result is not None else [])
        for snapshot in snapshots:
            snapshot_state = snapshot.get("state_id")
            for candidate in snapshot.get("candidates", []):
                candidate_id = candidate.get("candidate_id")
                if not candidate_id:
                    continue
                identity = _candidate_identity(candidate)
                old = candidate_ids.get(candidate_id)
                if old is not None and old != identity:
                    issue("CANDIDATE_ID_COLLISION_COUNT")
                candidate_ids[candidate_id] = identity
            observation = source_obs if snapshot is source else result_obs
            if snapshot_state and observation is not None:
                obs_doc = observation.to_dict() if isinstance(observation, StateObservation) else observation
                core = canonical_json(obs_doc.get("fingerprint", {}).get("core"))
                old_core = state_core.get(snapshot_state)
                if old_core is not None and old_core != core:
                    issue("STATE_COLLISION_COUNT")
                state_core[snapshot_state] = core

        if t.get("definitive_state_binding") and (not t.get("source_state_id") or not t.get("resulting_state_id")):
            issue("UNSAFE_STATE_BIND_COUNT")
        if t.get("definitive_state_binding") and (
                t.get("state_binding_mismatch") or t.get("outcome") in {"AMBIGUOUS_RESULT", "ERROR"}):
            issue("UNSAFE_TRANSITION_BIND_COUNT")
        if t.get("outcome") == "ERROR":
            counts["ERROR_TRANSITION_COUNT"] += 1
        case_faults[occurrence] = case_faults.get(occurrence, False) or bool(issues)
        target = (t.get("controlled_action") or {}).get("target_identity") or {}
        raw = case.get("before_raw") or {}
        root = ((raw.get("selected_tab") or {}).get("name")
                if isinstance(raw.get("selected_tab"), Mapping) else None)
        group = canonical_json(dict(action_kind=t.get("action_kind"), root=root, target=target,
                                   producer=(t.get("controlled_action") or {}).get("producer")))
        groups[group].append((occurrence, str(t.get("transition_type_hash")), t))
        status = ("AMBIGUOUS_BUT_SAFE" if not t.get("definitive_state_binding") or
                  t.get("outcome") == "AMBIGUOUS_RESULT" else "STABLE")
        classifications[occurrence] = status
        if issues:
            details.append(dict(occurrence_id=occurrence, status="CONTRADICTION", issues=sorted(set(issues))))
        elif status == "AMBIGUOUS_BUT_SAFE":
            details.append(dict(occurrence_id=occurrence, status=status, outcome=t.get("outcome"),
                                action_binding=binding.get("status")))

    transition_semantics: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        t = case.get("transition") or {}
        tid = str(t.get("transition_id") or "<missing>")
        semantic = canonical_json(dict(occurrence_id=t.get("occurrence_id"),
                                       semantic=t.get("semantic_identity")))
        transition_semantics[tid].add(semantic)
    counts["TRANSITION_ID_COLLISION_COUNT"] = sum(len(semantics) > 1 for semantics in transition_semantics.values())
    counts["UNEXPECTED_TRANSITION_SPLIT_COUNT"] = sum(len(ids) > 1 for ids in occurrence_ids.values())

    for _, values in groups.items():
        hashes = {value[1] for value in values}
        occurrences = {value[0] for value in values}
        if len(occurrences) > 1 and len(hashes) > 1:
            def stable_focus_projection(value: Mapping[str, Any]) -> str:
                identity = deepcopy(value[2].get("semantic_identity") or {})
                for key in ("focus_before", "focus_after", "focus_status", "actual_focus_moved", "outcome"):
                    identity.pop(key, None)
                return canonical_json(identity)
            focus_varies = len({canonical_json(((value[2].get("focus") or {}).get("status"),
                                                (value[2].get("focus") or {}).get("actual_focus_moved")))
                                for value in values}) > 1
            focus_variation = focus_varies and len({stable_focus_projection(value) for value in values}) == 1
            if focus_variation:
                for occurrence, _, t in values:
                    if classifications.get(occurrence) == "STABLE":
                        classifications[occurrence] = "EXPECTED_VARIABILITY"
            elif not any(classifications.get(occurrence) == "AMBIGUOUS_BUT_SAFE" for occurrence in occurrences):
                # A different semantic result for the same kind/root/target is
                # only variability when its persisted evidence is classified.
                counts["UNEXPECTED_TRANSITION_CHURN_COUNT"] += 1
                for occurrence in occurrences:
                    case_faults[occurrence] = True

    counts["UNEXPECTED_NONDETERMINISM_COUNT"] = sum(counts[key] for key in (
        *CONTRADICTIONS, "STATE_COLLISION_COUNT", "CANDIDATE_ID_COLLISION_COUNT",
        "TRANSITION_ID_COLLISION_COUNT", "UNSAFE_STATE_BIND_COUNT", "UNSAFE_TRANSITION_BIND_COUNT",
        "UNEXPECTED_CANDIDATE_CHURN_COUNT", "UNEXPECTED_TRANSITION_CHURN_COUNT",
        "UNEXPECTED_TRANSITION_SPLIT_COUNT", "ERROR_TRANSITION_COUNT"))
    counts["CROSS_LAYER_CONTRADICTION_COUNT"] = sum(bool(v) for v in case_faults.values())
    counts["TOTAL_REPLAY_CASES"] = len(cases)
    counts["TOTAL_DEVICE_TRANSITIONS"] = sum(c.get("origin") != "SYNTHETIC" for c in cases)
    counts["STABLE_TRANSITIONS"] = sum(value == "STABLE" for value in classifications.values())
    counts["EXPECTED_VARIABILITY_COUNT"] = sum(value == "EXPECTED_VARIABILITY" for value in classifications.values())
    counts["AMBIGUOUS_BUT_SAFE_COUNT"] = sum(value == "AMBIGUOUS_BUT_SAFE" for value in classifications.values())
    counts["UNCLASSIFIED_TRANSITIONS"] = counts["TOTAL_DEVICE_TRANSITIONS"] - sum(
        counts[k] for k in ("STABLE_TRANSITIONS", "EXPECTED_VARIABILITY_COUNT", "AMBIGUOUS_BUT_SAFE_COUNT"))
    counts["UNEXPECTED_NONDETERMINISM_COUNT"] += counts["UNCLASSIFIED_TRANSITIONS"]
    counts["VALIDATION_FAILURE_COUNT"] = (counts["UNEXPECTED_NONDETERMINISM_COUNT"]
                                           + counts["INCOMPATIBLE_SCHEMA_COUNT"])
    return dict(status="PASS" if counts["VALIDATION_FAILURE_COUNT"] == 0 else "FAIL",
                metrics=counts, classifications=classifications, details=details)


def make_case(transition: Mapping[str, Any], source_snapshot: Mapping[str, Any],
              result_snapshot: Mapping[str, Any] | None, source_observation: StateObservation | Mapping[str, Any],
              result_observation: StateObservation | Mapping[str, Any] | None, *,
              before_raw: Mapping[str, Any] | None = None, origin: str = "DEVICE") -> dict[str, Any]:
    return dict(transition=deepcopy(dict(transition)), source_snapshot=deepcopy(dict(source_snapshot)),
                result_snapshot=deepcopy(dict(result_snapshot)) if result_snapshot is not None else None,
                source_observation=source_observation.to_dict() if isinstance(source_observation, StateObservation) else deepcopy(source_observation),
                result_observation=(result_observation.to_dict() if isinstance(result_observation, StateObservation)
                                    else deepcopy(result_observation)),
                before_raw=deepcopy(dict(before_raw)) if before_raw is not None else {}, origin=origin)


def write_report(path: str | Path, result: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
