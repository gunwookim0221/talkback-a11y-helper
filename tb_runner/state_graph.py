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
    scroll_evidence: dict[str, Any]


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


def _phase6e_capture_is_current(raw: Any, expected_marker: Any = None) -> bool:
    if not isinstance(raw, Mapping) or raw.get("production_observation_current") is not True:
        return False
    try:
        if not _production_observation_envelope_valid(raw):
            return False
        from tb_runner.state_fingerprint import validated_capture_root_tree
        from talkback_lib.hierarchy_snapshot import flatten_service_hierarchy
        root = validated_capture_root_tree(raw)
        if root is None or not isinstance(raw.get("nodes"), list):
            return False
        projected = flatten_service_hierarchy({"success": True, "windows": [
            {"active": True, "focused": True, "root": deepcopy(dict(root))}]})
        # The original service window index is transport-local; all other
        # consumed hierarchy fields must come from the sealed root itself.
        def without_service_index(nodes):
            return [{key: value for key, value in node.items() if key != "serviceWindowIndex"}
                    for node in nodes]
        if canonical_json(without_service_index(raw["nodes"])) != canonical_json(without_service_index(projected)):
            return False
    except (TypeError, ValueError, KeyError):
        return False
    envelope = raw.get("production_observation_envelope")
    observed_marker = raw.get("_exploration_observation")
    marker = expected_marker if isinstance(expected_marker, Mapping) else observed_marker
    return bool(
        isinstance(envelope, Mapping)
        and isinstance(observed_marker, Mapping)
        and isinstance(marker, Mapping)
        and dict(marker) == dict(observed_marker)
        and dict(marker) == dict(envelope.get("observation") or {})
        and envelope.get("capture_complete") is True
        and marker.get("capture_complete") is True
    )


def _phase6e_scroll_owner(raw: Mapping[str, Any], transition: Mapping[str, Any], *, pre_dispatch: bool = False) -> dict[str, Any]:
    """Resolve a scroll target from this capture's hierarchy, never from focus or RID alone."""
    from tb_runner.scroll_reliability import scroll_axis
    from tb_runner.traversal_reliability import normalized_bounds

    capability = raw.get("capability") if isinstance(raw.get("capability"), Mapping) else {}
    if (capability.get("vertical_can_scroll_forward", capability.get("can_scroll_forward")) is not True
            or capability.get("contradictory") is True):
        return {"status": "VERTICAL_OPPORTUNITY_UNAVAILABLE", "identity": None}

    package = str(raw.get("package_name") or "")
    candidates = []
    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        if (node.get("scrollable", node.get("isScrollable")) is not True
                or node.get("visibleToUser", node.get("isVisibleToUser", True)) is False
                or node.get("enabled", node.get("isEnabled", True)) is False):
            continue
        axis, _axis_source = scroll_axis(node)
        if axis not in {"VERTICAL", "BIDIRECTIONAL"}:
            continue
        path = str(node.get("stable_node_path") or node.get("path") or "").strip()
        bounds = normalized_bounds(node.get("boundsInScreen", node.get("bounds")))
        # A scrollable class or resource-id by itself cannot bind an owner.
        if not path or not bounds:
            continue
        action_ids = sorted({
            str(item.get("id") if isinstance(item, Mapping) else item)
            for item in (node.get("actions") or [])
            if (item.get("id") if isinstance(item, Mapping) else item) is not None
            and str(item.get("id") if isinstance(item, Mapping) else item) in {
                "16908344", "16908345", "16908346", "16908347", "4096", "8192",
            }
        })
        projection = {
            "package_name": package,
            "path": path,
            "bounds": bounds,
            "resource_id": str(node.get("viewIdResourceName") or node.get("resource-id") or ""),
            "class_name": str(node.get("className") or node.get("class") or ""),
            "ancestors": [
                {key: item.get(key) for key in ("path", "resource_id", "class_name", "role")}
                for item in (node.get("ancestors") or []) if isinstance(item, Mapping)
            ],
            "axis": axis,
            "scrollable": True,
            "visible": True,
            "enabled": True,
            "actions": action_ids,
            "scroll_forward_supported": node.get("scroll_forward_supported", node.get("canScrollForward")),
            "scroll_down_supported": node.get("scroll_down_supported"),
        }
        identity_projection = {key: projection[key] for key in (
            "package_name", "path", "bounds", "resource_id", "class_name", "ancestors", "axis")}
        candidates.append((projection, "scroll_owner_" + canonical_sha256(identity_projection)))

    target = transition.get("action_target") if isinstance(transition.get("action_target"), Mapping) else {}
    action_result = transition.get("action_result") if isinstance(transition.get("action_result"), Mapping) else {}
    mode = str(target.get("mode") or "").strip().upper()
    requested_path = str(target.get("container_path") or "").strip()
    requested_bounds = normalized_bounds(target.get("container_bounds"))
    result_path = str(action_result.get("scrollContainerPath") or "").strip()

    if mode == "EXPLICIT_CONTAINER":
        if (not requested_path or not requested_bounds
                or (not pre_dispatch and (action_result.get("explicitTarget") is not True
                                          or result_path != requested_path))):
            return {"status": "OWNER_TARGET_MISMATCH", "identity": None}
        matches = [item for item in candidates
                   if item[0]["path"] == requested_path and item[0]["bounds"] == requested_bounds]
        if not matches and any(item[0]["path"] == requested_path for item in candidates):
            return {"status": "OWNER_TARGET_MISMATCH", "identity": None}
    elif mode == "ACCESSIBILITY_FALLBACK":
        if result_path or action_result.get("explicitTarget") is True:
            return {"status": "OWNER_TARGET_MISMATCH", "identity": None}
        matches = candidates
    else:
        return {"status": "OWNER_TARGET_MISMATCH", "identity": None}

    if len(matches) == 0:
        return {"status": "OWNER_NOT_IN_CURRENT_HIERARCHY", "identity": None}
    if len(matches) != 1:
        return {"status": "OWNER_AMBIGUOUS", "identity": None}
    projection, identity = matches[0]
    return {
        "status": "RESOLVED",
        "identity": identity,
        "path": projection["path"],
        "bounds": projection["bounds"],
        "resource_id": projection["resource_id"],
        "class_name": projection["class_name"],
        "axis": projection["axis"],
        "state": {key: projection[key] for key in (
            "scrollable", "visible", "enabled", "actions",
            "scroll_forward_supported", "scroll_down_supported")},
    }


def phase6e_current_scroll_owner(raw: Any, marker: Any) -> dict[str, Any]:
    """Resolve the exact target verified_scroll would choose from a sealed capture."""
    if not _phase6e_capture_is_current(raw, marker):
        return {"status": "SOURCE_CAPTURE_UNVERIFIED", "identity": None}
    if not build_graph_state_identity(raw).state_id:
        return {"status": "SOURCE_STATE_UNRESOLVED", "identity": None}
    capability = raw.get("capability") if isinstance(raw.get("capability"), Mapping) else {}
    target = capability.get("container")
    target = target if isinstance(target, Mapping) else {}
    action_target = {"mode": "ACCESSIBILITY_FALLBACK"}
    if target.get("path"):
        action_target = {"mode": "EXPLICIT_CONTAINER", "container_path": str(target["path"]),
                         "container_bounds": target.get("boundsInScreen")}
    return _phase6e_scroll_owner(raw, {"action_target": action_target}, pre_dispatch=True)


def _phase6e_accessibility_focus(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Read only the unique strict accessibility-focus bit from this capture."""
    from tb_runner.traversal_reliability import instance_id

    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    focused = [node for node in nodes if isinstance(node, Mapping)
               and node.get("accessibilityFocused") is True
               and node.get("visibleToUser", node.get("isVisibleToUser", True)) is not False]
    if len(focused) != 1:
        return {"status": "AMBIGUOUS" if focused else "UNAVAILABLE", "instance_id": None,
                "authority": "CURRENT_HIERARCHY_ACCESSIBILITY_FOCUS"}
    node = focused[0]
    focus_id = instance_id({
        "scenario_id": raw.get("scenario_id"),
        "view_id": node.get("viewIdResourceName") or node.get("resource-id") or "",
        "bounds": node.get("boundsInScreen") or node.get("bounds") or "",
    })
    return {"status": "CONFIRMED", "instance_id": focus_id,
            "authority": "CURRENT_HIERARCHY_ACCESSIBILITY_FOCUS"}


def build_phase6e_scroll_evidence(source: Mapping[str, Any] | None,
                                  result: Mapping[str, Any] | None,
                                  transition: Mapping[str, Any] | None,
                                  *, source_marker: Mapping[str, Any] | None = None,
                                  result_marker: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build non-authoritative, capture-bound diagnostics for one verified scroll."""
    source = source if isinstance(source, Mapping) else {}
    result = result if isinstance(result, Mapping) else {}
    transition = transition if isinstance(transition, Mapping) else {}
    action_result = transition.get("action_result") if isinstance(transition.get("action_result"), Mapping) else {}
    source_current = _phase6e_capture_is_current(source, source_marker)
    result_current = _phase6e_capture_is_current(result, result_marker)
    before_marker = source_marker if isinstance(source_marker, Mapping) else source.get("_exploration_observation")
    after_marker = result_marker if isinstance(result_marker, Mapping) else result.get("_exploration_observation")
    before_marker = before_marker if isinstance(before_marker, Mapping) else {}
    after_marker = after_marker if isinstance(after_marker, Mapping) else {}
    source_capture_id = str(source.get("capture_id") or "")
    result_capture_id = str(result.get("capture_id") or "")
    capture_linked = bool(
        source_current and result_current and source_capture_id and result_capture_id
        and source_capture_id != result_capture_id
        and source.get("scenario_id") == result.get("scenario_id")
        and source.get("scenario_run_id") == result.get("scenario_run_id")
        and before_marker.get("scope_id")
        and before_marker.get("scope_id") == after_marker.get("scope_id")
        and before_marker.get("context_revision") == after_marker.get("context_revision")
        and type(before_marker.get("action_epoch")) is int
        and type(after_marker.get("action_epoch")) is int
        and after_marker.get("action_epoch") == before_marker.get("action_epoch") + 1
        and type(before_marker.get("observation_sequence")) is int
        and type(after_marker.get("observation_sequence")) is int
        and after_marker.get("observation_sequence") > before_marker.get("observation_sequence")
    )

    action_type = str(transition.get("action_type") or "").strip().upper()
    action_request_id = str(transition.get("action_request_id") or "").strip()
    result_request_id = str(transition.get("action_result_request_id")
                            or action_result.get("reqId") or action_result.get("requestId")
                            or action_result.get("request_id") or "").strip()
    action_success = transition.get("action_success") is True
    result_success = action_result.get("success") is True
    receipt = after_marker.get("action_ownership") if isinstance(after_marker.get("action_ownership"), Mapping) else {}
    receipt_correlated = bool(
        type(receipt.get("action_epoch")) is int
        and receipt.get("action_epoch") == after_marker.get("action_epoch")
        and str(receipt.get("action_type") or "").strip().upper() == "SCROLL"
        and str(receipt.get("request_id") or "").strip() == action_request_id
        and receipt.get("ownership_status") == "KNOWN"
    )
    action_linked = bool(
        action_type in {EdgeType.SCROLL_FORWARD.value, EdgeType.SCROLL_BACKWARD.value}
        and action_request_id and result_request_id == action_request_id
        and transition.get("action_result_correlated") is True
        and receipt_correlated
        and action_result.get("reqId", action_result.get("requestId", action_result.get("request_id")))
        == action_request_id
        and action_result.get("action") == action_type
        and action_result.get("actionAttempted") is True
        and ((action_type == EdgeType.SCROLL_FORWARD.value and transition.get("direction") == "down")
             or (action_type == EdgeType.SCROLL_BACKWARD.value and transition.get("direction") == "up"))
        and action_success == result_success
    )

    owner = (_phase6e_scroll_owner(source, transition) if source_current
             else {"status": "SOURCE_CAPTURE_STALE", "identity": None})
    source_identity = build_graph_state_identity(source) if source_current else GraphIdentityResult(
        None, "UNRESOLVED", ("SOURCE_CAPTURE_STALE",))
    result_identity = build_graph_state_identity(result) if result_current else GraphIdentityResult(
        None, "UNRESOLVED", ("RESULT_CAPTURE_STALE",))
    state_changed = bool(source_identity.state_id and result_identity.state_id
                         and source_identity.state_id != result_identity.state_id)
    # Derive movement from the two bound captures, not a separately acquired
    # transition dump that may belong to a different observation epoch.
    from tb_runner.scroll_reliability import viewport
    container = {"boundsInScreen": owner.get("bounds")} if owner.get("status") == "RESOLVED" else None
    before_viewport = viewport(source.get("nodes", []), source.get("scenario_id"), container)
    after_viewport = viewport(result.get("nodes", []), result.get("scenario_id"), container)
    viewport_valid = before_viewport["valid"] and after_viewport["valid"]
    viewport_changed = bool(viewport_valid and before_viewport["stable_signature"] != after_viewport["stable_signature"])
    new_content = bool(viewport_valid and set(before_viewport["instances"]) != set(after_viewport["instances"]))
    meaningful_reasons = []
    if state_changed:
        meaningful_reasons.append("GRAPH_STATE_CHANGED")
    if viewport_changed:
        meaningful_reasons.append("VIEWPORT_CHANGED")
    if new_content:
        meaningful_reasons.append("CONTENT_INSTANCES_CHANGED")
    meaningful_change = bool(meaningful_reasons)
    after_capability = transition.get("capability_after") if isinstance(transition.get("capability_after"), Mapping) else {}
    captured_capability = result.get("capability") if isinstance(result.get("capability"), Mapping) else {}
    boundary = bool(transition.get("viewport_end") is True
                    and after_capability.get("can_scroll_forward") is False
                    and after_capability.get("contradictory") is not True
                    and captured_capability.get("vertical_can_scroll_forward",
                                                captured_capability.get("can_scroll_forward")) is False
                    and captured_capability.get("contradictory") is not True)
    focus_after = _phase6e_accessibility_focus(result) if result_current else {
        "status": "UNAVAILABLE", "instance_id": None,
        "authority": "CURRENT_HIERARCHY_ACCESSIBILITY_FOCUS"}

    if not source_current or not result_current or not capture_linked:
        classification = "STALE_CAPTURE"
    elif not action_linked:
        classification = "STALE_INVOCATION_RESULT"
    elif owner.get("status") != "RESOLVED":
        classification = str(owner.get("status") or "OWNER_UNAVAILABLE")
    elif not source_identity.state_id or not result_identity.state_id:
        classification = "STATE_UNRESOLVED"
    elif not action_success:
        classification = "NO_OP"
    elif meaningful_change:
        classification = "SCROLL_MOVED"
    elif boundary:
        classification = "BOUNDARY"
    else:
        classification = "NO_PROGRESS"

    return {
        "schema_version": "phase6e-scroll-evidence.v1",
        "classification": classification,
        "valid_for_edge": classification == "SCROLL_MOVED",
        "owner_status": owner.get("status"),
        "owner_identity": owner.get("identity"),
        "owner": {key: owner.get(key) for key in (
            "path", "bounds", "resource_id", "class_name", "axis", "state")},
        "action_type": action_type or None,
        "direction": transition.get("direction"),
        "action_request_id": action_request_id or None,
        "result_request_id": result_request_id or None,
        "action_result_correlated": action_linked,
        "dispatch_receipt_correlated": receipt_correlated,
        "action_attempted": bool(action_request_id and action_result.get("actionAttempted") is not False),
        "action_dispatched": action_result.get("actionAttempted") is True,
        "action_success": action_success if action_linked else None,
        "source_capture_current": source_current,
        "result_capture_current": result_current,
        "capture_linked_to_invocation": capture_linked,
        "source_capture_id": source_capture_id or None,
        "result_capture_id": result_capture_id or None,
        "source_state_id": source_identity.state_id,
        "result_state_id": result_identity.state_id,
        "meaningful_change": meaningful_change,
        "meaningful_change_reasons": meaningful_reasons,
        "boundary": boundary,
        "focus_after_scroll": focus_after,
    }


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
                    "status", "classification", "axis", "direction", "owner_identity",
                    "owner_status", "movement_status", "end_evidence", "valid_for_edge",
                    "action_request_id", "result_request_id", "source_capture_id", "result_capture_id")
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
                # An earlier observation can coexist with a later attempt in
                # the row without becoming that attempt's observation.
                if evidence.get("action_effect_current") is not False:
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
                             if key in {"resource_id", "class_name", "bounds", "candidate_instance_id",
                                        "direction", "owner_identity", "container_path", "axis"}}
        opportunity = {"source_state_id": source_state_id, "edge_type": action_type,
                       "target": target_descriptor}
        opportunity_id = "opportunity_" + canonical_sha256(opportunity)
        lifecycle: list[str] = []
        for field_name, lifecycle_name in (("planned", EdgeLifecycle.PLANNED),
                                           ("attempted", EdgeLifecycle.ATTEMPTED),
                                           ("dispatched", EdgeLifecycle.DISPATCHED)):
            if evidence.get(field_name) is True:
                lifecycle.append(lifecycle_name.value)
        scroll_evidence = evidence.get("scroll_evidence")
        scroll_evidence = scroll_evidence if isinstance(scroll_evidence, Mapping) else {}
        is_scroll = action_type in {EdgeType.SCROLL_FORWARD.value, EdgeType.SCROLL_BACKWARD.value}
        unbound_focus = not is_scroll and evidence.get("action_effect_current") is False
        if unbound_focus:
            focus = {"observation": FocusObservation.FOCUS_UNKNOWN.value}
            visit_outcome, visit_id = VisitObservation.VISIT_UNKNOWN.value, None
            destination_state_id = None
        if is_scroll:
            # A scroll is successful only when the Phase6E evidence binds a
            # current owner, current invocation/result, current captures, and
            # an observable state/viewport/content/window change. A request or
            # focus-only movement cannot promote it to progress.
            effect_observed = scroll_evidence.get("valid_for_edge") is True
            state_changed = bool(effect_observed and source_state_id and destination_state_id
                                 and source_state_id != destination_state_id)
            focus_moved = False
        elif unbound_focus:
            effect_observed = state_changed = focus_moved = False
        else:
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
            "effect_attribution": str((None if unbound_focus else evidence.get("effect_attribution")) or (
                "OBSERVED_SCROLL_CHANGE" if is_scroll and effect_observed else
                "UNKNOWN" if is_scroll else
                "FOCUS_RECONCILIATION" if focus_moved else "OBSERVED_STATE" if state_changed else "UNKNOWN")),
            "scroll_evidence": ({key: deepcopy(scroll_evidence.get(key)) for key in (
                "classification", "owner_status", "owner_identity", "action_request_id",
                "result_request_id", "action_result_correlated", "source_capture_id",
                "result_capture_id", "meaningful_change", "meaningful_change_reasons",
                "boundary", "valid_for_edge") if key in scroll_evidence} if is_scroll else {}),
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


def _raw_observation_from_phase6e_slot(row: Mapping[str, Any], slot: str,
                                       marker_slot: str) -> dict[str, Any] | None:
    supplied = row.get(slot)
    if not isinstance(supplied, Mapping):
        return None
    raw = deepcopy(dict(supplied))
    wrapper = dict(row)
    wrapper.update(
        state_graph_observation=raw,
        capture_id=raw.get("capture_id"),
        scenario_id=raw.get("scenario_id"),
        scenario_run_id=raw.get("scenario_run_id"),
        _exploration_observation=deepcopy(row.get(marker_slot) or raw.get("_exploration_observation")),
    )
    return _raw_observation_from_row(wrapper)


def _phase6e_scroll_action_evidence(scroll: Mapping[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {"scroll_evidence": deepcopy(dict(scroll))}
    # Graph edges represent observed traversal success. Keep unsuccessful,
    # boundary, stale, and no-progress scrolls on the current state's bounded
    # diagnostic record without manufacturing a traversed edge.
    if (scroll.get("valid_for_edge") is not True
            or scroll.get("action_result_correlated") is not True
            or scroll.get("capture_linked_to_invocation") is not True):
        return evidence
    owner = scroll.get("owner") if isinstance(scroll.get("owner"), Mapping) else {}
    target = {
        key: deepcopy(value) for key, value in (
            ("owner_identity", scroll.get("owner_identity")),
            ("container_path", owner.get("path")),
            ("bounds", owner.get("bounds")),
            ("resource_id", owner.get("resource_id")),
            ("class_name", owner.get("class_name")),
            ("axis", owner.get("axis")),
            ("direction", scroll.get("direction")),
        ) if value is not None
    }
    evidence.update(
        action={"type": scroll.get("action_type"), "target": target,
                "request_id": scroll.get("action_request_id")},
        planned=True,
        attempted=scroll.get("action_attempted") is True,
        dispatched=scroll.get("action_dispatched") is True,
        command_ack=("SUCCESS" if scroll.get("action_success") is True else "FAILED"),
    )
    return evidence


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
    if action_family == "TARGETED_FOCUS":
        from tb_runner.focus_realign_logic import targeted_focus_observation_current
        evidence["action_effect_current"] = targeted_focus_observation_current(row)
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
        step = max(0, step)
        primary_raw = _raw_observation_from_row(row)
        recorder.record(step=step, raw_observation=primary_raw, evidence=_evidence_from_row(row))

        if not (isinstance(row.get("scroll_transition"), Mapping)
                or isinstance(row.get("phase6e_scroll_source_observation"), Mapping)
                or isinstance(row.get("phase6e_scroll_result_observation"), Mapping)):
            continue
        source_raw = _raw_observation_from_phase6e_slot(
            row, "phase6e_scroll_source_observation", "phase6e_scroll_source_marker")
        result_raw = _raw_observation_from_phase6e_slot(
            row, "phase6e_scroll_result_observation", "phase6e_scroll_result_marker")
        scroll = build_phase6e_scroll_evidence(
            source_raw, result_raw,
            row.get("scroll_transition") if isinstance(row.get("scroll_transition"), Mapping) else {},
            source_marker=row.get("phase6e_scroll_source_marker"),
            result_marker=row.get("phase6e_scroll_result_marker"),
        )
        if source_raw is not None:
            source_identity = build_graph_state_identity(source_raw)
            if source_identity.state_id != recorder._previous_state_id:
                recorder.record(step=step, raw_observation=source_raw, evidence={})
        if result_raw is not None:
            recorder.record(step=step, raw_observation=result_raw,
                            evidence=_phase6e_scroll_action_evidence(scroll))
        else:
            recorder.record(step=step, raw_observation=source_raw or primary_raw,
                            evidence={"scroll_evidence": scroll})
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
    "StateGraphRecorder", "VisitObservation", "build_graph_state_identity",
    "build_phase6e_scroll_evidence", "graph_mode_from_environment",
    "maybe_write_shadow_graph_from_rows", "read_state_graph", "recorder_from_existing_rows",
    "replay_state_graph", "state_graph_artifact_path", "write_replay_manifest", "write_state_graph",
]
