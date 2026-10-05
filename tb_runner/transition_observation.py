"""Opt-in Phase 3B sidecar for externally controlled actions.

No device client, executor, action chooser, visit ledger or runtime integration.
Registry/equality, candidate inventory and strict focus reconciliation remain
the authorities. An occurrence key identifies a caller-recorded action, not a
permission to execute it. Registry IDs are local to its persisted namespace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.diagnostics import classify_command_ack
from tb_runner.discovery_candidates import ACTION_INVENTORY, DiscoverySnapshot, _node, build_discovery_snapshot
from tb_runner.focus_reconciliation import reconcile_focus
from tb_runner.state_equality import VerifiedScrollEvidence, evaluate_state_equality
from tb_runner.state_observation import StateObservation, build_state_observation
from tb_runner.state_registry import StateRegistry
from tb_runner.traversal_reliability import focus_instance, instance_id

TRANSITION_SCHEMA = "transition-observation-v1"
OUTCOMES = frozenset({"STATE_CHANGED", "SAME_STATE", "VIEWPORT_CHANGED", "FOCUS_ONLY",
                      "ACTION_FAILED", "AMBIGUOUS_RESULT", "ERROR"})


def _target(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    if any(k in value for k in ("resource_id", "viewIdResourceName", "view_id", "bounds", "boundsInScreen")):
        node = _node(value)
        result.update(resource_id=node["viewIdResourceName"], bounds=node["boundsInScreen"])
        if node["className"]:
            result["class_name"] = node["className"]
    for name in ("destination", "operation"):
        if name in value:
            result[name] = value[name]
    return result


@dataclass(frozen=True)
class ControlledAction:
    occurrence_id: str
    action_kind: str
    _document_json: str = field(repr=False)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ControlledAction":
        if not isinstance(value, Mapping):
            raise TypeError("controlled action must be a mapping")
        for key in ("occurrence_id", "producer"):
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ValueError("controlled action requires " + key)
        kind = value.get("action_kind")
        if kind not in ACTION_INVENTORY:
            raise ValueError("unknown controlled action kind")
        target = value.get("target_identity") or {}
        if not isinstance(target, Mapping):
            raise ValueError("invalid controlled target")
        doc = dict(occurrence_id=value["occurrence_id"], action_kind=kind, producer=value["producer"],
                   target_identity=_target(target), requested_candidate_id=value.get("requested_candidate_id"))
        if doc["requested_candidate_id"] is not None and not isinstance(doc["requested_candidate_id"], str):
            raise ValueError("invalid requested candidate ID")
        return cls(doc["occurrence_id"], kind, canonical_json(doc))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._document_json)


@dataclass(frozen=True)
class PreparedTransition:
    source_observation: StateObservation
    source_snapshot: DiscoverySnapshot
    action: ControlledAction
    _raw_json: str = field(repr=False)
    _binding_json: str = field(repr=False)
    action_started_at: str | None = None


@dataclass(frozen=True)
class TransitionObservation:
    transition_id: str
    semantic_hash: str
    outcome: str
    _document_json: str = field(repr=False)
    resulting_snapshot: DiscoverySnapshot | None = field(repr=False, compare=False, default=None)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._document_json)

    def to_json(self) -> str:
        return self._document_json


def _bind(snapshot: DiscoverySnapshot, action: ControlledAction) -> dict[str, Any]:
    declared = action.to_dict()
    reason = "NO_OBSERVED_CANDIDATE"
    matches = []
    for item in snapshot.candidates:
        candidate = item.to_dict()
        if item.action_kind != action.action_kind:
            continue
        if declared["requested_candidate_id"] and item.candidate_id != declared["requested_candidate_id"]:
            continue
        target = declared["target_identity"]
        if action.action_kind == "FOCUS_NEXT" and target not in ({}, {"operation": "HELPER_SMART_NEXT_UNTARGETED"}):
            continue
        if action.action_kind != "FOCUS_NEXT" and not target and not declared["requested_candidate_id"]:
            continue  # A kind alone never silently selects a target.
        if not all(candidate["target_identity"].get(k) == v for k, v in target.items()):
            continue
        if candidate["eligibility"]["availability"] != "AVAILABLE":
            reason = "CANDIDATE_NOT_AVAILABLE"
            continue
        matches.append(candidate)
    if snapshot.state_id is None:
        reason = "UNRESOLVED_SOURCE"
    elif len(matches) == 1:
        return dict(status="MAPPED", candidate_id=matches[0]["candidate_id"],
                    candidate_target=matches[0]["target_identity"], reason="EXACT_CURRENT_SOURCE_MATCH")
    elif len(matches) > 1:
        reason = "AMBIGUOUS_ACTION_TARGET"
    return dict(status="UNMAPPED_CONTROLLED_ACTION", candidate_id=None, candidate_target=None, reason=reason)


def _focus_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    n = _node(raw.get("focus_node") or {})
    row = dict(scenario_id="transition-focus", focus_node=n, focus_view_id=n["viewIdResourceName"],
               focus_bounds=n["boundsInScreen"], visible_label=n.get("text") or n.get("contentDescription") or "")
    for name in ("actual_focus_accessibility_focused", "actual_focus_input_focused", "actual_focus_resource_id",
                 "actual_focus_visible", "actual_focus_speech", "focus_transition_status",
                 "focus_reconciliation_confidence", "physical_visited"):
        if name in raw:
            row[name] = raw[name]
    if "actual_focus_node" in raw:
        row["actual_focus_node"] = _node(raw["actual_focus_node"] or {})
    if "actual_focus_bounds" in raw:
        row["actual_focus_bounds"] = _node({"bounds": raw["actual_focus_bounds"]})["boundsInScreen"]
    return row


def _focus(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    left, right = _focus_row(before), _focus_row(after)
    result = reconcile_focus(row=right, previous_row=left, scenario_id="transition-focus", inventory=[],
                             expected_candidates=[], physical_visit_confirmed=False, planning_consumed=False)
    li, ri = focus_instance(left), focus_instance(right)
    status = result["focus_transition_status"]
    if not li or not ri:
        status = "AMBIGUOUS" if status == "AMBIGUOUS" else "UNAVAILABLE"
    moved = True if status == "CONFIRMED_MOVED" else False if status == "CONFIRMED_UNCHANGED" else None
    # Project focus facts only. Reconciliation's advisory visit/progress fields
    # never enter this sidecar or any traversal ledger.
    actual = result["actual_item"]
    target = {k: actual.get(k) for k in ("view_id", "bounds", "class_name", "label", "role")} if actual else None
    return dict(status=status, actual_focus_moved=moved,
                before_instance_id=instance_id(li) if li else None,
                after_instance_id=instance_id(ri) if ri else None,
                actual_observed_target=target,
                reconciliation_producer="focus_reconciliation.reconcile_focus+strict_focus_instance")


def _reference(snapshot: DiscoverySnapshot, observation: StateObservation) -> dict[str, Any]:
    return dict(state_id=snapshot.state_id, observation_id=observation.observation_id,
                fingerprint_hash=observation.fingerprint.fingerprint_hash,
                viewport_signature=observation.fingerprint.viewport_signature,
                candidate_set_hash=snapshot.candidate_set_hash,
                state_resolution=snapshot.to_dict()["state_resolution"])


class TransitionObserver:
    """Diagnostic prepare/complete brackets; the caller executes in between."""

    def __init__(self, registry: StateRegistry):
        if not isinstance(registry, StateRegistry):
            raise TypeError("transition observer requires diagnostic StateRegistry")
        self.registry = registry
        self._prepared: list[PreparedTransition] = []
        self._occurrences: dict[str, tuple[str, str]] = {}
        self._identities: dict[str, str] = {}
        self._records: dict[str, dict[str, Any]] = {}
        self._collisions = self._churn = self._mismatches = 0

    def prepare(self, raw: Mapping[str, Any], action: Mapping[str, Any] | ControlledAction, *,
                action_started_at: str | None = None) -> PreparedTransition:
        action = ControlledAction.from_dict(action.to_dict() if isinstance(action, ControlledAction) else action)
        observation = build_state_observation(raw)
        snapshot = build_discovery_snapshot(raw, self.registry)
        prepared = PreparedTransition(observation, snapshot, action, canonical_json(raw),
                                      canonical_json(_bind(snapshot, action)), action_started_at)
        self._prepared.append(prepared)
        return prepared

    def complete(self, prepared: PreparedTransition, after_raw: Mapping[str, Any] | None, *,
                 command_ack: Any = None, action_evidence: Mapping[str, Any] | None = None,
                 action_finished_at: str | None = None, evidence_refs: Mapping[str, Any] | None = None) -> TransitionObservation:
        if not any(p is prepared for p in self._prepared):
            raise ValueError("foreign or forged prepared source")
        evidence = json.loads(canonical_json(action_evidence or {}))
        action = prepared.action.to_dict()
        binding = json.loads(prepared._binding_json)
        before = json.loads(prepared._raw_json)
        ack = classify_command_ack({"move_result": command_ack})
        normalized_ack = {k: ack[k] for k in ("status", "result", "normalized_result")}
        proof = None
        proof_error = None
        result = snapshot = equality = None
        focus = dict(status="UNAVAILABLE", actual_focus_moved=None, before_instance_id=None,
                     after_instance_id=None, actual_observed_target=None)
        source_id = prepared.source_snapshot.state_id
        result_id = None
        mismatch = False
        if after_raw is not None:
            result = build_state_observation(after_raw)
            if "scroll_transition" in evidence:
                try:
                    proof = VerifiedScrollEvidence.from_transition(prepared.source_observation, result, evidence["scroll_transition"])
                except (ValueError, TypeError, AttributeError) as exc:
                    proof_error = str(exc)
            snapshot = build_discovery_snapshot(after_raw, self.registry, continuity=proof)
            result_id = snapshot.state_id
            equality = evaluate_state_equality(prepared.source_observation, result, proof).to_dict()
            focus = _focus(before, after_raw)
            relation = equality["verdict"]
            mismatch = bool(source_id and result_id and relation != "AMBIGUOUS" and
                            ((source_id == result_id) != (relation == "SAME")))
            if mismatch:
                result_id = None  # Quarantine an inconsistent binding, never merge it.
            if not source_id or not result_id or relation == "AMBIGUOUS" or mismatch:
                outcome = "AMBIGUOUS_RESULT"
            elif relation == "DIFFERENT":
                outcome = "STATE_CHANGED"
            elif equality["viewport_equal"] is False:
                outcome = "VIEWPORT_CHANGED"
            elif focus["actual_focus_moved"] is True:
                outcome = "FOCUS_ONLY"
            elif ack["status"] == "FAIL":
                outcome = "ACTION_FAILED"
            else:
                outcome = "SAME_STATE"
        else:
            outcome = "ERROR"
        executed_target = evidence.get("executed_target_identity")
        if executed_target is not None and binding["candidate_target"] is not None:
            supplied = _target(executed_target)
            if not supplied or not all(binding["candidate_target"].get(k) == v for k, v in supplied.items()):
                binding = dict(status="UNMAPPED_CONTROLLED_ACTION", candidate_id=None, candidate_target=None,
                               reason="EXECUTED_TARGET_CONTRADICTS_REQUESTED_CANDIDATE")
        actual = focus["actual_observed_target"] or {}
        requested = binding["candidate_target"] or action["target_identity"]
        target_matches = None
        if prepared.action.action_kind == "FOCUS_TARGET" and focus["after_instance_id"] and requested.get("bounds"):
            target_matches = requested.get("resource_id") == actual.get("view_id") and requested["bounds"] == actual.get("bounds")
        semantic = dict(schema_version=TRANSITION_SCHEMA, source_state_id=source_id,
                        action_candidate_id=binding["candidate_id"], action_kind=prepared.action.action_kind,
                        target_identity=requested, resulting_state_id=result_id, outcome=outcome,
                        command_ack=normalized_ack, focus_status=focus["status"],
                        actual_focus_moved=focus["actual_focus_moved"],
                        focus_before=focus["before_instance_id"], focus_after=focus["after_instance_id"],
                        viewport_changed=None if equality is None or equality["viewport_equal"] is None else not equality["viewport_equal"],
                        equality_relation=equality["verdict"] if equality else None)
        # Unresolved observations need a discriminator, but not timestamps or
        # transient observation IDs. No ID is fabricated for their logical state.
        for side, sid, obs in (("source", source_id, prepared.source_observation), ("result", result_id, result)):
            if sid is None and obs is not None:
                fp = obs.fingerprint.to_dict()
                semantic[side + "_unresolved_fingerprint"] = {k: fp[k] for k in ("core", "viewport", "overlay")}
        semantic_json = canonical_json(semantic)
        semantic_hash = canonical_sha256(semantic)
        transition_id = "transition:" + canonical_sha256(dict(occurrence_id=prepared.action.occurrence_id, semantic=semantic))
        prior = self._identities.get(transition_id)
        if prior is not None and prior != canonical_json(dict(occurrence_id=prepared.action.occurrence_id, semantic=semantic)):
            self._collisions += 1
            raise ValueError("transition ID collision")
        existing = self._occurrences.get(prepared.action.occurrence_id)
        if existing and existing != (transition_id, semantic_json):
            self._churn += 1
            raise ValueError("conflicting action occurrence; unexpected transition churn")
        transition_type = {k: v for k, v in semantic.items() if k not in {"focus_before", "focus_after"}}
        doc = dict(schema_version=TRANSITION_SCHEMA, transition_id=transition_id, semantic_hash=semantic_hash,
                   transition_type_hash=canonical_sha256(transition_type), semantic_identity=semantic,
                   occurrence_id=prepared.action.occurrence_id, source_state_id=source_id,
                   source=_reference(prepared.source_snapshot, prepared.source_observation),
                   action_candidate_id=binding["candidate_id"], action_kind=prepared.action.action_kind,
                   target_identity=requested, controlled_action=action, action_binding=binding,
                   action_started_at=prepared.action_started_at, action_finished_at=action_finished_at,
                   command_ack=dict(raw=command_ack, normalized=normalized_ack), actual_focus_moved=focus["actual_focus_moved"],
                   focus=focus, requested_target_matches_actual_focus=target_matches,
                   viewport_changed=semantic["viewport_changed"], resulting_state_id=result_id,
                   resulting_fingerprint=_reference(snapshot, result) if snapshot and result else None,
                   equality_relation=equality, outcome=outcome,
                   definitive_state_binding=bool(source_id and result_id and outcome != "AMBIGUOUS_RESULT"),
                   state_binding_mismatch=mismatch, evidence=dict(producer=evidence,
                       scroll_continuity=proof.to_dict() if proof else None, scroll_continuity_rejected=proof_error,
                       refs=dict(evidence_refs or {})),
                   provenance=dict(source="EXTERNALLY_CONTROLLED_ACTION", action_producer=action["producer"],
                       equality="state_equality.evaluate_state_equality", registry_namespace=self.registry.namespace,
                       scenario_id=before.get("scenario_id"), step=before.get("step")),
                   auto_activation=False, action_executed_by_observer=False, visit_credit=0)
        if existing is None:
            self._mismatches += mismatch
            self._records[transition_id] = doc
        self._occurrences[prepared.action.occurrence_id] = (transition_id, semantic_json)
        self._identities[transition_id] = canonical_json(dict(occurrence_id=prepared.action.occurrence_id, semantic=semantic))
        return TransitionObservation(transition_id, semantic_hash, outcome, canonical_json(doc), snapshot)

    def metrics(self) -> dict[str, int]:
        records = list(self._records.values())
        mapped = sum(r["action_binding"]["status"] == "MAPPED" for r in records)
        return dict(TOTAL_TRANSITIONS_OBSERVED=len(records), MAPPED_ACTION_TRANSITIONS=mapped,
                    UNMAPPED_CONTROLLED_ACTIONS=len(records)-mapped,
                    AMBIGUOUS_SOURCE_COUNT=sum(r["source_state_id"] is None for r in records),
                    AMBIGUOUS_RESULT_COUNT=sum(r["outcome"] == "AMBIGUOUS_RESULT" for r in records),
                    STATE_BINDING_MISMATCH_COUNT=self._mismatches, TRANSITION_ID_COLLISION_COUNT=self._collisions,
                    UNSAFE_TRANSITION_BIND_COUNT=sum(r["definitive_state_binding"] and
                        (r["state_binding_mismatch"] or r["outcome"] in {"AMBIGUOUS_RESULT", "ERROR"}) for r in records),
                    UNEXPECTED_TRANSITION_CHURN_COUNT=self._churn)


def write_transition(path: str | Path, observation: TransitionObservation) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(observation.to_json() + "\n")
