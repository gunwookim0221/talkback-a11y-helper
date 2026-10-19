"""Phase 6B observational state graph.

This module consumes already collected observations. It never performs UI or
hierarchy I/O, selects actions, grants visits, or makes traversal decisions.
"""
from __future__ import annotations

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
        context = resolve_phase3_context(raw)
        context_evidence = {"status": context.get("status"), "verified": context.get("verified") is True,
                            "context_type": context.get("context_type"), "context_id": context.get("context_id"),
                            "reasons": sorted(context.get("reasons") or [])}
        if context.get("verified") is not True or not context.get("context_id"):
            return GraphIdentityResult(None, "UNRESOLVED", tuple(sorted(
                str(reason) for reason in (context.get("reasons") or ["UNVERIFIED_LOGICAL_CONTEXT"]))),
                context=context_evidence)
        observation = build_state_observation(raw)
        problems = set(observation_problems(observation))
        # The Phase 3 resolver above is the authoritative context proof. Its
        # verified plugin/root forms need not also have a selected bottom tab.
        problems.difference_update({"UNVERIFIED_SELECTED_CONTEXT", "UNVERIFIED_PLUGIN_CONTEXT"})
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
        overlay_nodes = [_structural_node(node) for node in secondary.get("overlay_nodes", [])]
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
                "activity_name": core.get("activity_name"),
                "context_type": context.get("context_type"),
                "context_id": context.get("context_id"),
                "selected_tab": core.get("selected_tab"),
                "persistent_markers": sorted(markers, key=canonical_json),
            },
            "substates": sorted(substates, key=lambda item: (item["category"], item["key"])),
            "overlay": ({"kind": overlay.get("kind"),
                         "nodes": sorted(overlay_nodes, key=canonical_json)}
                        if overlay.get("observed") is True else None),
            "viewport": {
                "model": "relative-grid32-structural-multiset-v1",
                "nodes": sorted(viewport_nodes, key=canonical_json),
            },
        }
        return GraphIdentityResult("state_" + canonical_sha256(identity), "RESOLVED", (), identity, context_evidence)
    except (TypeError, ValueError, KeyError) as exc:
        return GraphIdentityResult(None, "UNRESOLVED", ("INVALID_OBSERVATION_" + type(exc).__name__,))


def build_graph_state_identity(raw: Mapping[str, Any]) -> GraphIdentityResult:
    """Build deterministic state identity from verified context and stable structure.

    Focus, visit/attempt history, timestamps, request IDs, raw labels, and pixel
    offsets are excluded. Viewport geometry uses the existing relative-grid32
    projection; without a sufficiently observed viewport, identity is unresolved.
    """
    if not isinstance(raw, Mapping):
        raise TypeError("graph observation must be a mapping")
    return _identity_from_observation(raw)


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
        return dict(supplied)
    focus = row.get("actual_focus_node") or row.get("focus_node") or {}
    focus = focus if isinstance(focus, Mapping) else {}
    raw = {
        "scenario_id": row.get("scenario_id"),
        "scenario_run_id": row.get("scenario_run_id"),
        "timestamp": row.get("timestamp"),
        "phase3_entry_evidence": row.get("phase3_entry_evidence"),
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
    try:
        step_index = int(row.get("step_index", 0) or 0)
    except (TypeError, ValueError):
        step_index = 0
    action_request_id = row.get("smart_nav_req_id") or row.get("get_focus_req_id")
    has_action_observation = bool(action_request_id or row.get("move_result") is not None or step_index > 0)
    if row.get("forced_local_tab_navigation") is True:
        action_type = EdgeType.TARGETED_FOCUS.value
    else:
        action_type = EdgeType.FOCUS_NEXT.value
    target = {}
    for target_key, source_key in (("resource_id", "smart_nav_requested_view_id"),
                                   ("class_name", "smart_nav_requested_class_name"),
                                   ("bounds", "smart_nav_requested_bounds")):
        if row.get(source_key):
            target[target_key] = row[source_key]
    evidence["action"] = {"type": action_type, "target": target} if has_action_observation else None
    evidence["attempted"] = bool(action_request_id or row.get("move_result") is not None or step_index > 0)
    evidence["dispatched"] = bool(row.get("smart_nav_req_id"))
    evidence["command_ack"] = row.get("command_ack_status") or row.get("last_smart_nav_result")
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
