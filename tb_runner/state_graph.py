"""Phase 6B observational state graph.

This module consumes already collected observations. It never performs UI or
hierarchy I/O, selects actions, grants visits, or makes traversal decisions.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any, Mapping, TypedDict

from tb_runner.canonical_json import canonical_json, canonical_json_bytes, canonical_sha256
from tb_runner.phase3_context import resolve_phase3_context
from tb_runner.state_observation import build_state_observation, observation_problems

GRAPH_SCHEMA_VERSION = "phase6-state-graph.v1"
IDENTITY_SCHEMA_VERSION = "phase6-state-identity.v1"
REPLAY_SCHEMA_VERSION = "phase6-state-graph-replay.v1"
GRAPH_MODE_ENV = "TB_STATE_GRAPH_MODE"


class GraphMode(str, Enum):
    OFF = "OFF"
    SHADOW = "SHADOW"


class EdgeType(str, Enum):
    FOCUS_NEXT = "FOCUS_NEXT"
    FOCUS_PREVIOUS = "FOCUS_PREVIOUS"
    TARGETED_FOCUS = "TARGETED_FOCUS"
    SCROLL_FORWARD = "SCROLL_FORWARD"
    SCROLL_BACKWARD = "SCROLL_BACKWARD"
    SAFE_ACTIVATION = "SAFE_ACTIVATION"
    TAB_CHANGE = "TAB_CHANGE"
    BACK = "BACK"
    RECOVERY = "RECOVERY"
    SCENARIO_SEED_ENTRY = "SCENARIO_SEED_ENTRY"
    OTHER = "OTHER"


class EdgeLifecycle(str, Enum):
    PLANNED = "PLANNED"
    ATTEMPTED = "ATTEMPTED"
    DISPATCHED = "DISPATCHED"
    EFFECT_OBSERVED = "EFFECT_OBSERVED"
    STATE_CHANGED = "STATE_CHANGED"
    VISIT_CREDIT = "VISIT_CREDIT"


class FocusObservation(str, Enum):
    FOCUS_MOVED = "FOCUS_MOVED"
    FOCUS_UNCHANGED = "FOCUS_UNCHANGED"
    FOCUS_UNKNOWN = "FOCUS_UNKNOWN"


class VisitObservation(str, Enum):
    VISIT_GRANTED = "VISIT_GRANTED"
    NO_VISIT = "NO_VISIT"
    VISIT_UNKNOWN = "VISIT_UNKNOWN"


class GraphState(TypedDict):
    state_id: str
    identity: dict[str, Any]
    first_seen_step: int
    last_seen_step: int
    observation_count: int
    focus_instance_ids: list[str]
    visit_instance_ids: list[str]
    candidate_count: int | None
    package_name: str | None
    activity_name: str | None
    context: dict[str, Any]
    scroll_observations: list[dict[str, Any]]


class GraphObservation(TypedDict):
    schema_version: str
    step: int
    state_id: str | None
    state_resolution: str
    state_resolution_reasons: list[str]
    focus: dict[str, Any]
    visit_outcome: str
    candidate_count: int | None
    visible_node_count: int | None
    context_evidence: dict[str, Any]
    scroll_evidence: dict[str, Any]
    terminal_evidence: dict[str, Any]
    edge_id: str | None
    observation_id: str


class GraphEdge(TypedDict):
    schema_version: str
    edge_id: str
    occurrence_index: int
    step: int
    opportunity_id: str
    edge_type: str
    request_id: str | None
    source_state_id: str | None
    destination_state_id: str | None
    target: dict[str, Any]
    lifecycle: list[str]
    command_ack: Any
    focus_observation: str
    visit_outcome: str
    visit_instance_id: str | None
    effect_attribution: str


class GraphRun(TypedDict):
    schema_version: str
    identity_schema_version: str
    graph_version: int
    mode: str
    authority: str
    decision_authority: str
    run: dict[str, str]
    limits: dict[str, int]
    truncated: bool
    truncation_reasons: list[str]
    states: list[GraphState]
    edges: list[GraphEdge]
    observations: list[GraphObservation]
    terminal_evidence: dict[str, Any]
    summary: dict[str, int]


@dataclass(frozen=True)
class GraphLimits:
    max_states: int = 512
    max_edges: int = 2048
    max_observations: int = 10000
    max_artifact_bytes: int = 10_000_000

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or value <= 0 for value in (
                self.max_states, self.max_edges, self.max_observations, self.max_artifact_bytes)):
            raise ValueError("graph limits must be positive integers")

    def to_dict(self) -> dict[str, int]:
        return {"max_states": self.max_states, "max_edges": self.max_edges,
                "max_observations": self.max_observations,
                "max_artifact_bytes": self.max_artifact_bytes}


@dataclass(frozen=True)
class GraphIdentityResult:
    state_id: str | None
    status: str
    reasons: tuple[str, ...]
    identity: Mapping[str, Any] | None = None
    context: Mapping[str, Any] | None = None


def graph_mode_from_environment(environ: Mapping[str, str] | None = None) -> GraphMode:
    """Read the opt-in gate. Default and invalid values fail to OFF."""
    values = os.environ if environ is None else environ
    value = str(values.get(GRAPH_MODE_ENV, "OFF") or "OFF").strip().upper()
    try:
        return GraphMode(value)
    except ValueError:
        return GraphMode.OFF


def _structural_node(node: Mapping[str, Any]) -> dict[str, Any]:
    """Project stable structure and typed states; omit raw labels and focus."""
    semantic = node.get("semantic") if isinstance(node.get("semantic"), Mapping) else {}
    result = {
        "resource_id": semantic.get("resource_id"),
        "class_name": semantic.get("class_name"),
        "role": semantic.get("role"),
        "semantic_state": semantic.get("semantic_state"),
        "flags": {key: (semantic.get("flags") or {}).get(key)
                  for key in ("enabled", "checked", "selected", "clickable", "focusable", "scrollable")},
        "layout_bucket": semantic.get("layout_bucket"),
    }
    return result


def _identity_from_observation(raw: Mapping[str, Any]) -> GraphIdentityResult:
    try:
        if raw.get("production_observation_current") is False or not _production_observation_envelope_valid(raw):
            return GraphIdentityResult(None, "UNRESOLVED", ("PRODUCTION_OBSERVATION_NOT_CURRENT_OR_ALIGNED",))
        context = resolve_phase3_context(raw)
        context_evidence = {"status": context.get("status"), "verified": context.get("verified") is True,
                            "context_type": context.get("context_type"), "context_id": context.get("context_id"),
                            "reasons": sorted(context.get("reasons") or [])}
        from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
        authority = validate_capture_authority(raw.get("capture_authority"))
        capture_local_hierarchy = bool(
            authority is not None
            and raw.get("capture_id") == authority.capture_key
            and raw.get("hierarchy_capture_id") == authority.capture_key
            and context.get("status") == "UNRESOLVED_CONTEXT"
            and context.get("reasons") == ["CAPTURE_COMPONENT_UNKNOWN"]
        )
        if (context.get("verified") is not True or not context.get("context_id")) and not capture_local_hierarchy:
            return GraphIdentityResult(None, "UNRESOLVED", tuple(sorted(
                str(reason) for reason in (context.get("reasons") or ["UNVERIFIED_LOGICAL_CONTEXT"]))),
                context=context_evidence)
        observation = build_state_observation(raw)
        problems = set(observation_problems(observation))
        # Phase 3 context stays UNKNOWN for root-only captures. Structural graph
        # identity below is capture-local and does not claim component context.
        if problems:
            return GraphIdentityResult(None, "UNRESOLVED", tuple(sorted(problems)), context=context_evidence)

        viewport = observation.fingerprint.to_dict()["viewport"]
        if viewport.get("observation_status") == "UNOBSERVED" or viewport.get("bounds_strategy") != "relative-grid32":
            return GraphIdentityResult(None, "UNRESOLVED", ("UNOBSERVED_OR_UNNORMALIZED_VIEWPORT",),
                                       context=context_evidence)

        payload = observation.fingerprint.to_dict()
        core = payload["core"]
        secondary = observation.secondary
        viewport_nodes = [_structural_node(node) for node in secondary.get("nodes", [])]
        markers = [_structural_node(node) for node in secondary.get("markers", [])]
        substates = [
            {"category": item["category"], "key": item["key"], "value": item["value"]}
            for item in observation.semantic_substates
            if item.get("confidence") in {"OBSERVED_EXACT", "BOUNDED_OBSERVED"}
            and item.get("value") != "UNKNOWN"
        ]
        overlay = payload["overlay"]
        identity = {
            "schema_version": IDENTITY_SCHEMA_VERSION,
            "environment_partition": secondary.get("environment_partition"),
            "root": {
                "package_name": core.get("package_name"),
                "window_id": authority.hierarchy_window_id if authority is not None else None,
                "context_type": context.get("context_type"),
                "context_id": context.get("context_id"),
                "selected_tab": core.get("selected_tab"),
                "persistent_markers": sorted(markers, key=canonical_json),
            },
            "substates": sorted(substates, key=lambda item: (item["category"], item["key"])),
            # Overlay/WMS diagnostics remain safety evidence and cannot alter state identity.
            "viewport": {
                "model": "relative-grid32-structural-multiset-v1",
                "nodes": sorted(viewport_nodes, key=canonical_json),
            },
        }
        return GraphIdentityResult("state_" + canonical_sha256(identity), "RESOLVED", (), identity, context_evidence)
    except (TypeError, ValueError, KeyError) as exc:
        return GraphIdentityResult(None, "UNRESOLVED", ("INVALID_OBSERVATION_" + type(exc).__name__,))


def build_graph_state_identity(raw: Mapping[str, Any]) -> GraphIdentityResult:
    """Build identity from a valid capture-local root and stable tree structure.

    Phase3 context can remain UNKNOWN: this identity is scoped by captured
    package/window/root bytes and never asserts Activity or screen continuity.
    Focus, visit/attempt history, timestamps, request IDs, labels and pixel
    offsets are excluded. Without an observed normalized viewport, identity is unresolved.
    """
    if not isinstance(raw, Mapping):
        raise TypeError("graph observation must be a mapping")
    return _identity_from_observation(raw)


def _production_observation_envelope_valid(raw: Mapping[str, Any]) -> bool:
    """Validate a production snapshot and its immutable Helper capture authority."""
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority

    authority = validate_capture_authority(raw.get("capture_authority"))
    if authority is None:
        return False
    envelope = raw.get("production_observation_envelope")
    if not isinstance(envelope, Mapping):
        return False
    if envelope.get("schema_version") != "phase6-production-observation-v1":
        return False
    capture_id = str(envelope.get("capture_id") or "")
    scenario_id = str(envelope.get("scenario_id") or "")
    run_id = str(envelope.get("scenario_run_id") or "")
    if (not capture_id or capture_id != authority.capture_key or not scenario_id or not run_id
            or raw.get("package_name") != authority.hierarchy_package_name
            or raw.get("traversal_root_ref") != authority.root_ref
            or raw.get("traversal_root_window_id") != authority.hierarchy_window_id
            or raw.get("hierarchy_request_id") != authority.request_id
            or raw.get("hierarchy_capture_sequence") != authority.capture_sequence
            or envelope.get("capture_authority") != authority.to_dict()
            or raw.get("capture_id") != capture_id
            or raw.get("scenario_id") != scenario_id
            or raw.get("scenario_run_id") != run_id):
        return False
    if envelope.get("hierarchy_capture_id") != capture_id:
        return False
    for key in ("focus_capture_id", "geometry_capture_id"):
        value = envelope.get(key)
        if value is not None and value != capture_id:
            return False
        if raw.get(key) != value:
            return False
    observation = envelope.get("observation")
    if not isinstance(observation, Mapping):
        return False
    scope_id = observation.get("scope_id")
    sequence = observation.get("observation_sequence")
    epoch = observation.get("action_epoch")
    context_revision = observation.get("context_revision")
    if (not isinstance(scope_id, str) or not scope_id
            or type(sequence) is not int or sequence < 0
            or type(epoch) is not int or epoch < 0
            or type(context_revision) is not int or context_revision < 0
            or observation.get("observation_epoch") != epoch
            or observation.get("capture_end_action_epoch") != epoch
            or observation.get("observation_id") != f"observation:{scope_id}:{sequence}"
            or observation.get("capture_complete") is not True
            or envelope.get("capture_complete") is not True):
        return False
    if raw.get("_exploration_observation") != dict(observation):
        return False
    if (envelope.get("coverage") != raw.get("observation_coverage")
            or envelope.get("coverage_source") != raw.get("coverage_source")
            or envelope.get("navigation_epoch") != raw.get("navigation_epoch")
            or envelope.get("snapshot_coherent") is not True
            or raw.get("snapshot_coherent") is not True):
        return False
    if raw.get("observation_coverage") == "OBSERVED_FULL":
        if (envelope.get("hierarchy_complete") is not True
                or raw.get("hierarchy_complete") is not True
                or envelope.get("coverage_source") not in {
                    "reliable_service_hierarchy", "service_hierarchy_xml",
                }):
            return False
    elif raw.get("hierarchy_complete") is True or envelope.get("hierarchy_complete") is True:
        return False
    return True


def _focus_projection(evidence: Mapping[str, Any]) -> dict[str, Any]:
    status = str(evidence.get("focus_transition_status", "") or "").strip().upper()
    if status == "CONFIRMED_MOVED":
        observation = FocusObservation.FOCUS_MOVED
    elif status == "CONFIRMED_UNCHANGED":
        observation = FocusObservation.FOCUS_UNCHANGED
    else:
        observation = FocusObservation.FOCUS_UNKNOWN
    # Identity is copied only from production reconciliation, never rebuilt here.
    focus_id = evidence.get("actual_focus_instance_id") if observation != FocusObservation.FOCUS_UNKNOWN else None
    return {"observation": observation.value,
            "instance_id": focus_id if isinstance(focus_id, str) and focus_id else None,
            "authority": "production_focus_reconciliation" if focus_id else "none"}


def _visit_projection(evidence: Mapping[str, Any]) -> tuple[str, str | None]:
    status = str(evidence.get("visit_record_status", "") or "").strip().upper()
    if status == "RECORDED":
        visit_id = evidence.get("reconciled_visit_instance_id")
        if isinstance(visit_id, str) and visit_id:
            return VisitObservation.VISIT_GRANTED.value, visit_id
        return VisitObservation.VISIT_UNKNOWN.value, None
    if status in {"ALREADY_VISITED", "NOT_RECORDED", "NO_VISIT", "UNVISITED_NOT_CREDITED"}:
        return VisitObservation.NO_VISIT.value, None
    return VisitObservation.VISIT_UNKNOWN.value, None


def _edge_type(value: Any) -> str:
    candidate = str(value or EdgeType.OTHER.value).strip().upper()
    return candidate if candidate in {item.value for item in EdgeType} else EdgeType.OTHER.value


@dataclass
class StateGraphRecorder:
    run_id: str
    scenario_id: str = ""
    mode: GraphMode = GraphMode.SHADOW
    limits: GraphLimits = field(default_factory=GraphLimits)
    states: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    truncation_reasons: set[str] = field(default_factory=set)
    _previous_state_id: str | None = field(default=None, repr=False)
    _edge_sequence: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("graph run_id is required")
        if not isinstance(self.mode, GraphMode):
            self.mode = GraphMode(str(self.mode).upper())
        if self.mode != GraphMode.SHADOW:
            raise ValueError("recorder only records in SHADOW mode")

    def record(self, *, step: int, raw_observation: Mapping[str, Any],
               evidence: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        if not isinstance(step, int) or step < 0:
            raise ValueError("step must be a non-negative integer")
        if len(self.observations) >= self.limits.max_observations:
            self.truncation_reasons.add("MAX_OBSERVATIONS")
            self._previous_state_id = None
            return None
        evidence = evidence if isinstance(evidence, Mapping) else {}
        identity_result = build_graph_state_identity(raw_observation)
        state_id = identity_result.state_id
        if state_id and state_id not in self.states and len(self.states) >= self.limits.max_states:
            self.truncation_reasons.add("MAX_STATES")
            state_id = None
        state_meta = self.states.get(state_id) if state_id else None
        if state_id and state_meta is None:
            identity = dict(identity_result.identity or {})
            root = identity.get("root", {})
            state_meta = dict(state_id=state_id, identity=identity,
                first_seen_step=step, last_seen_step=step, observation_count=0,
                focus_instance_ids=[], visit_instance_ids=[], candidate_count=None,
                package_name=root.get("package_name"), activity_name=root.get("activity_name"),
                context=dict(context_type=root.get("context_type"), context_id=root.get("context_id")),
                scroll_observations=[])
            self.states[state_id] = state_meta
        if state_meta is not None:
            state_meta["last_seen_step"] = step
            state_meta["observation_count"] += 1
            candidate_count = evidence.get("candidate_count")
            if isinstance(candidate_count, int) and candidate_count >= 0:
                state_meta["candidate_count"] = candidate_count

        focus = _focus_projection(evidence)
        visit_outcome, visit_id = _visit_projection(evidence)
        if state_meta is not None:
            focus_id = focus.get("instance_id")
            if focus_id and focus_id not in state_meta["focus_instance_ids"]:
                state_meta["focus_instance_ids"].append(focus_id)
                state_meta["focus_instance_ids"].sort()
            if visit_id and visit_id not in state_meta["visit_instance_ids"]:
                state_meta["visit_instance_ids"].append(visit_id)
                state_meta["visit_instance_ids"].sort()
            scroll = evidence.get("scroll_evidence")
            if isinstance(scroll, Mapping) and scroll:
                compact_scroll = {key: scroll.get(key) for key in (
                    "status", "axis", "direction", "owner_identity", "movement_status", "end_evidence")
                    if key in scroll}
                if compact_scroll and compact_scroll not in state_meta["scroll_observations"]:
                    state_meta["scroll_observations"].append(compact_scroll)

        source_state_id = self._previous_state_id
        action = evidence.get("action")
        edge_id = None
        if isinstance(action, Mapping):
            if len(self.edges) >= self.limits.max_edges:
                self.truncation_reasons.add("MAX_EDGES")
            else:
                edge = self._record_edge(step, source_state_id, state_id, action, evidence,
                                         focus, visit_outcome, visit_id)
                edge_id = edge["edge_id"]

        context = identity_result.context or {}
        candidate_nodes = raw_observation.get("nodes")
        candidate_count = evidence.get("candidate_count")
        observation_doc = {
            "schema_version": "phase6-graph-observation.v1",
            "step": step,
            "state_id": state_id,
            "state_resolution": identity_result.status if state_id else (
                "TRUNCATED" if identity_result.status == "RESOLVED" else "UNRESOLVED"),
            "state_resolution_reasons": list(identity_result.reasons),
            "focus": focus,
            "visit_outcome": visit_outcome,
            "candidate_count": candidate_count if isinstance(candidate_count, int) and candidate_count >= 0 else None,
            "visible_node_count": len(candidate_nodes) if isinstance(candidate_nodes, list) else None,
            "context_evidence": dict(context),
            "scroll_evidence": dict(evidence.get("scroll_evidence") or {})
                if isinstance(evidence.get("scroll_evidence"), Mapping) else {},
            "terminal_evidence": {key: evidence.get(key) for key in ("terminal_status", "terminal_reason")
                                  if evidence.get(key) is not None},
            "edge_id": edge_id,
        }
        observation_doc["observation_id"] = "graph_observation_" + canonical_sha256(observation_doc)
        self.observations.append(observation_doc)
        self._previous_state_id = state_id
        return observation_doc

    def _record_edge(self, step: int, source_state_id: str | None, destination_state_id: str | None,
                     action: Mapping[str, Any], evidence: Mapping[str, Any], focus: Mapping[str, Any],
                     visit_outcome: str, visit_id: str | None) -> dict[str, Any]:
        action_type = _edge_type(action.get("type"))
        target = action.get("target") if isinstance(action.get("target"), Mapping) else {}
        target_descriptor = {key: target[key] for key in sorted(target)
                             if key in {"resource_id", "class_name", "bounds", "candidate_instance_id", "direction"}}
        opportunity = {"source_state_id": source_state_id, "edge_type": action_type,
                       "target": target_descriptor}
        opportunity_id = "opportunity_" + canonical_sha256(opportunity)
        lifecycle: list[str] = []
        for field_name, lifecycle_name in (("planned", EdgeLifecycle.PLANNED),
                                           ("attempted", EdgeLifecycle.ATTEMPTED),
                                           ("dispatched", EdgeLifecycle.DISPATCHED)):
            if evidence.get(field_name) is True:
                lifecycle.append(lifecycle_name.value)
        state_changed = bool(source_state_id and destination_state_id and source_state_id != destination_state_id)
        focus_moved = focus.get("observation") == FocusObservation.FOCUS_MOVED.value
        effect_observed = state_changed or focus_moved or evidence.get("effect_observed") is True
        if effect_observed:
            lifecycle.append(EdgeLifecycle.EFFECT_OBSERVED.value)
        if state_changed:
            lifecycle.append(EdgeLifecycle.STATE_CHANGED.value)
        if visit_outcome == VisitObservation.VISIT_GRANTED.value and visit_id:
            lifecycle.append(EdgeLifecycle.VISIT_CREDIT.value)
        self._edge_sequence += 1
        edge_id = "edge_" + canonical_sha256({"run_id": self.run_id,
            "occurrence_index": self._edge_sequence, "opportunity_id": opportunity_id})
        row = {
            "schema_version": "phase6-graph-edge.v1",
            "edge_id": edge_id,
            "occurrence_index": self._edge_sequence,
            "step": step,
            "opportunity_id": opportunity_id,
            "edge_type": action_type,
            "request_id": (action.get("request_id")
                           if isinstance(action.get("request_id"), str) and action.get("request_id")
                           else None),
            "source_state_id": source_state_id,
            "destination_state_id": destination_state_id,
            "target": target_descriptor,
            "lifecycle": lifecycle,
            "command_ack": evidence.get("command_ack"),
            "focus_observation": focus.get("observation"),
            "visit_outcome": visit_outcome,
            "visit_instance_id": visit_id if visit_outcome == VisitObservation.VISIT_GRANTED.value else None,
            "effect_attribution": str(evidence.get("effect_attribution") or (
                "FOCUS_RECONCILIATION" if focus_moved else "OBSERVED_STATE" if state_changed else "UNKNOWN")),
        }
        self.edges.append(row)
        return row

    def to_dict(self, *, terminal: Mapping[str, Any] | None = None) -> GraphRun:
        states = [self.states[key] for key in sorted(self.states)]
        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "graph_version": 1,
            "mode": self.mode.value,
            "authority": "OBSERVATIONAL_SHADOW_ONLY",
            "decision_authority": "NONE",
            "run": {"run_id": self.run_id, "scenario_id": self.scenario_id},
            "limits": self.limits.to_dict(),
            "truncated": bool(self.truncation_reasons),
            "truncation_reasons": sorted(self.truncation_reasons),
            "states": states,
            "edges": list(self.edges),
            "observations": list(self.observations),
            "terminal_evidence": dict(terminal or {}),
            "summary": {
                "state_count": len(states),
                "edge_count": len(self.edges),
                "observation_count": len(self.observations),
                "unresolved_observation_count": sum(item["state_id"] is None for item in self.observations),
                "focus_move_count": sum(item["focus"]["observation"] == FocusObservation.FOCUS_MOVED.value
                                         for item in self.observations),
                "visit_grant_observation_count": sum(item["visit_outcome"] == VisitObservation.VISIT_GRANTED.value
                                                      for item in self.observations),
            },
        }

    def to_json(self, *, terminal: Mapping[str, Any] | None = None) -> str:
        return canonical_json(self.to_dict(terminal=terminal))


def replay_state_graph(manifest: Mapping[str, Any], *, limits: GraphLimits | None = None) -> StateGraphRecorder:
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != REPLAY_SCHEMA_VERSION:
        raise ValueError("incompatible state graph replay manifest")
    run_id = manifest.get("run_id")
    scenario_id = manifest.get("scenario_id", "")
    steps = manifest.get("steps")
    if not isinstance(run_id, str) or not run_id.strip() or not isinstance(scenario_id, str) or not isinstance(steps, list):
        raise ValueError("replay manifest requires run_id, scenario_id, and steps")
    recorder = StateGraphRecorder(run_id=run_id, scenario_id=scenario_id, limits=limits or GraphLimits())
    for item in steps:
        if not isinstance(item, Mapping) or not isinstance(item.get("observation"), Mapping):
            raise ValueError("each replay step requires an observation mapping")
        recorder.record(step=item.get("step"), raw_observation=item["observation"],
                        evidence=item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {})
    return recorder


def _raw_observation_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    supplied = row.get("state_graph_observation")
    if isinstance(supplied, Mapping):
        raw = deepcopy(dict(supplied))
        if isinstance(raw.get("production_observation_envelope"), Mapping):
            marker = row.get("_exploration_observation")
            aligned = bool(
                _production_observation_envelope_valid(raw)
                and isinstance(marker, Mapping)
                and dict(marker) == raw.get("_exploration_observation")
                and row.get("capture_id") == raw.get("capture_id")
                and row.get("scenario_id") == raw.get("scenario_id")
                and row.get("scenario_run_id") == raw.get("scenario_run_id")
            )
            raw["production_observation_current"] = bool(
                raw.get("production_observation_current") is True and aligned)
        return raw
    focus = row.get("actual_focus_node") or row.get("focus_node") or {}
    focus = focus if isinstance(focus, Mapping) else {}
    raw = {
        "scenario_id": row.get("scenario_id"),
        "scenario_run_id": row.get("scenario_run_id"),
        "timestamp": row.get("timestamp"),
        "capture_id": row.get("capture_id"),
        "phase3_entry_evidence": row.get("phase3_entry_evidence"),
        "phase3_plugin_context_evidence": row.get("phase3_plugin_context_evidence"),
        "navigation_epoch": row.get("navigation_epoch"),
        "package_name": row.get("package_name") or focus.get("packageName") or focus.get("package_name"),
        "activity_name": row.get("activity_name"),
        "context_source": row.get("context_source"),
        "navigation_context": row.get("navigation_context"),
        "selected_tab": row.get("selected_tab"),
        "nodes": row.get("dump_tree_nodes") if isinstance(row.get("dump_tree_nodes"), list) else [],
        "focus_node": focus,
        "display_bounds": row.get("display_bounds"),
        "capability": row.get("capability") if isinstance(row.get("capability"), Mapping) else {},
        "overlay": row.get("overlay") if isinstance(row.get("overlay"), Mapping) else {},
        "environment_partition": row.get("environment_partition"),
        "observation_coverage": row.get("observation_coverage", "OBSERVED_PARTIAL"),
    }
    return raw


def _evidence_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    focus_status = str(row.get("focus_transition_status", "") or "").strip().upper()
    evidence: dict[str, Any] = {
        "focus_transition_status": focus_status,
        "actual_focus_instance_id": row.get("actual_focus_instance_id"),
        "visit_record_status": row.get("visit_record_status"),
        "reconciled_visit_instance_id": row.get("reconciled_visit_instance_id"),
        "candidate_count": row.get("candidate_count"),
        "command_ack": row.get("command_ack_status"),
        "terminal_status": row.get("status") if row.get("status") == "END" else None,
        "terminal_reason": row.get("stop_reason") or None,
    }
    # Reuse the production action discriminator and action-scoped request
    # selector. Import lazily because frontier_shadow consumes this module's
    # graph types during its own initialization.
    from tb_runner.frontier_shadow import canonical_action_request_id, current_action_type

    action_family = current_action_type(row)
    action_request_id = canonical_action_request_id(row, action_family)
    graph_action = {
        "SMART_NEXT": EdgeType.FOCUS_NEXT.value,
        "SMART_PREVIOUS": EdgeType.FOCUS_PREVIOUS.value,
        "TARGETED_FOCUS": EdgeType.TARGETED_FOCUS.value,
        # Controlled focus is a target-directed focus edge in the v1 graph
        # vocabulary; retain its request and target as separate provenance.
        "CONTROLLED_FOCUS": EdgeType.TARGETED_FOCUS.value,
        "RECOVERY": EdgeType.RECOVERY.value,
        "SCROLL_FORWARD": EdgeType.SCROLL_FORWARD.value,
        "SCROLL_BACKWARD": EdgeType.SCROLL_BACKWARD.value,
        "TAB_CHANGE": EdgeType.TAB_CHANGE.value,
        "BACK": EdgeType.BACK.value,
        "SAFE_ACTIVATION": EdgeType.SAFE_ACTIVATION.value,
    }.get(action_family)

    marker = str(row.get("phase6_current_action_type")
                or row.get("current_action_type")
                or row.get("smart_nav_action_type") or "").strip()
    action_attempted = bool(
        marker or action_request_id or row.get("move_result") is not None
        or row.get("target_focus_attempted") is True
        or row.get("recovery_action_attempted") is True
        or row.get("controlled_focus_intent") is not None
        or row.get("controlled_focus_dispatch_status") is not None
    )

    target: dict[str, Any] = {}
    descriptor = None
    if action_family == "CONTROLLED_FOCUS":
        intent = row.get("controlled_focus_intent")
        if isinstance(intent, Mapping):
            descriptor = intent.get("target_descriptor")
        if not isinstance(descriptor, Mapping):
            descriptor = row.get("target_focus_descriptor")
    elif action_family == "TARGETED_FOCUS":
        descriptor = row.get("target_focus_descriptor")
    if isinstance(descriptor, Mapping):
        for key in ("resource_id", "class_name", "bounds", "candidate_instance_id", "direction"):
            if descriptor.get(key) is not None and descriptor.get(key) != "":
                target[key] = deepcopy(descriptor[key])
    elif action_family == "SMART_NEXT":
        for target_key, source_key in (("resource_id", "smart_nav_requested_view_id"),
                                       ("class_name", "smart_nav_requested_class_name"),
                                       ("bounds", "smart_nav_requested_bounds")):
            if row.get(source_key):
                target[target_key] = row[source_key]

    has_action_observation = graph_action is not None and action_attempted
    evidence["action"] = ({"type": graph_action, "target": target,
                           "request_id": action_request_id or None}
                          if has_action_observation else None)
    evidence["attempted"] = bool(has_action_observation)

    dispatch_status = "UNKNOWN"
    dispatch_status_key = {
        "SMART_NEXT": "smart_nav_dispatch_status",
        "SMART_PREVIOUS": "smart_previous_dispatch_status",
        "TARGETED_FOCUS": "target_focus_dispatch_status",
        "CONTROLLED_FOCUS": "controlled_focus_dispatch_status",
        "RECOVERY": "recovery_action_dispatch_status",
        "SCROLL_FORWARD": "scroll_dispatch_status",
        "SCROLL_BACKWARD": "scroll_dispatch_status",
        "TAB_CHANGE": "tab_change_dispatch_status",
        "BACK": "back_dispatch_status",
        "SAFE_ACTIVATION": "activation_dispatch_status",
    }.get(action_family)
    if dispatch_status_key and action_request_id:
        status_request_key = {
            "SMART_NEXT": "smart_nav_dispatch_request_id",
            "SMART_PREVIOUS": "smart_previous_dispatch_request_id",
            "TARGETED_FOCUS": "target_focus_dispatch_request_id",
            "CONTROLLED_FOCUS": "controlled_focus_request_id",
            "RECOVERY": "recovery_action_dispatch_request_id",
            "SCROLL_FORWARD": "scroll_dispatch_request_id",
            "SCROLL_BACKWARD": "scroll_dispatch_request_id",
            "TAB_CHANGE": "tab_change_dispatch_request_id",
            "BACK": "back_dispatch_request_id",
            "SAFE_ACTIVATION": "activation_dispatch_request_id",
        }.get(action_family)
        status_request = str(row.get(status_request_key) or "").strip() if status_request_key else ""
        # CONTROLLED_FOCUS's status is written beside its action-scoped request
        # by controlled_collect and is itself produced from NativeDispatchEvidence.
        if status_request == action_request_id:
            dispatch_status = str(row.get(dispatch_status_key) or "UNKNOWN").strip().upper()
        elif action_family == "CONTROLLED_FOCUS":
            dispatch_status = str(row.get("controlled_focus_dispatch_status") or "UNKNOWN").strip().upper()
    if dispatch_status not in {"DISPATCHED", "NOT_DISPATCHED", "UNKNOWN"}:
        dispatch_status = "UNKNOWN"
    evidence["dispatch_status"] = dispatch_status
    evidence["dispatched"] = dispatch_status == "DISPATCHED"

    command_ack = None
    if action_family == "SMART_NEXT" and action_request_id:
        result = row.get("last_smart_nav_result")
        result_request = ""
        if isinstance(result, Mapping):
            result_request = str(result.get("reqId") or result.get("requestId")
                                 or result.get("request_id") or "").strip()
        generation = row.get("smart_nav_invocation_generation")
        result_generation = row.get("smart_nav_result_generation")
        if result_request == action_request_id or (
                isinstance(result, str) and type(generation) is int
                and result_generation == generation):
            command_ack = result
    if command_ack is None and action_request_id and row.get("command_ack_request_id") == action_request_id:
        command_ack = row.get("command_ack_status") or row.get("command_ack_result")
    evidence["command_ack"] = command_ack
    return evidence


def recorder_from_existing_rows(rows: list[Mapping[str, Any]], *, run_id: str, scenario_id: str,
                                limits: GraphLimits | None = None) -> StateGraphRecorder:
    """Project existing persisted runner rows; never asks the client for data."""
    if not isinstance(rows, list):
        raise TypeError("existing rows must be a list")
    recorder = StateGraphRecorder(run_id=run_id, scenario_id=scenario_id, limits=limits or GraphLimits())
    for ordinal, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        try:
            step = int(row.get("step_index", ordinal) or ordinal)
        except (TypeError, ValueError):
            step = ordinal
        recorder.record(step=max(0, step), raw_observation=_raw_observation_from_row(row),
                        evidence=_evidence_from_row(row))
    return recorder


def write_state_graph(path: str | Path, recorder: StateGraphRecorder, *,
                      terminal: Mapping[str, Any] | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(recorder.to_dict(terminal=terminal))
    if len(payload) > recorder.limits.max_artifact_bytes:
        recorder.truncation_reasons.add("MAX_ARTIFACT_BYTES")
        document = recorder.to_dict(terminal=terminal)
        before_counts = {name: len(document[name]) for name in ("states", "edges", "observations")}
        document["artifact_truncated_from_counts"] = before_counts
        while len(payload) > recorder.limits.max_artifact_bytes and document["observations"]:
            document["observations"].pop()
            document["summary"]["observation_count"] = len(document["observations"])
            document["summary"]["unresolved_observation_count"] = sum(
                item["state_id"] is None for item in document["observations"])
            document["summary"]["focus_move_count"] = sum(
                item["focus"]["observation"] == FocusObservation.FOCUS_MOVED.value
                for item in document["observations"])
            document["summary"]["visit_grant_observation_count"] = sum(
                item["visit_outcome"] == VisitObservation.VISIT_GRANTED.value
                for item in document["observations"])
            payload = canonical_json_bytes(document)
        while len(payload) > recorder.limits.max_artifact_bytes and document["edges"]:
            document["edges"].pop()
            document["summary"]["edge_count"] = len(document["edges"])
            payload = canonical_json_bytes(document)
        while len(payload) > recorder.limits.max_artifact_bytes and document["states"]:
            document["states"].pop()
            document["summary"]["state_count"] = len(document["states"])
            payload = canonical_json_bytes(document)
        if len(payload) > recorder.limits.max_artifact_bytes:
            raise ValueError("state graph artifact exceeds configured byte bound")
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(target)
    return target


def state_graph_artifact_path(output_path: str | Path) -> Path:
    output = Path(output_path)
    return output.with_name(output.stem + ".state_graph.json")


def maybe_write_shadow_graph_from_rows(*, rows: list[Mapping[str, Any]], output_path: str | Path,
                                       run_id: str, scenario_id: str,
                                       terminal: Mapping[str, Any] | None = None,
                                       environ: Mapping[str, str] | None = None) -> Path | None:
    """OFF is a no-op; SHADOW adds one artifact from already collected row data."""
    if graph_mode_from_environment(environ) != GraphMode.SHADOW:
        return None
    recorder = recorder_from_existing_rows(rows, run_id=run_id, scenario_id=scenario_id)
    return write_state_graph(state_graph_artifact_path(output_path), recorder, terminal=terminal)


def read_state_graph(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise ValueError("incompatible state graph artifact")
    if value.get("mode") != GraphMode.SHADOW.value or value.get("decision_authority") != "NONE":
        raise ValueError("state graph artifact has an invalid authority contract")
    return value


def write_replay_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != REPLAY_SCHEMA_VERSION:
        raise ValueError("incompatible state graph replay manifest")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_json_bytes(manifest))
    return target


__all__ = [
    "EdgeLifecycle", "EdgeType", "FocusObservation", "GraphEdge", "GraphIdentityResult", "GraphLimits",
    "GraphMode", "GraphObservation", "GraphRun", "GraphState",
    "GRAPH_MODE_ENV", "GRAPH_SCHEMA_VERSION", "IDENTITY_SCHEMA_VERSION", "REPLAY_SCHEMA_VERSION",
    "StateGraphRecorder", "VisitObservation", "build_graph_state_identity", "graph_mode_from_environment",
    "maybe_write_shadow_graph_from_rows", "read_state_graph", "recorder_from_existing_rows",
    "replay_state_graph", "state_graph_artifact_path", "write_replay_manifest", "write_state_graph",
]
