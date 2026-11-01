"""Narrow, production progress evidence primitives.

These helpers do not dispatch, grant visits, or decide termination.  A caller
must bind both observations to the same operation before using a result.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from talkback_lib.reliable_hierarchy_schema import capture_canonical_sha256, validate_capture_authority
from tb_runner.traversal_reliability import focus_instance, instance_id


@dataclass(frozen=True)
class ProgressCheckpoint:
    scenario_id: str
    run_id: str
    step: int
    capture: dict[str, Any]
    marker: dict[str, Any]
    receipt_store: Any
    receipt_generation: str
    receipt_watermark: int


def _sealed_raw_nodes(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    authority = validate_capture_authority(raw.get("capture_authority"))
    root = raw.get("_capture_root_tree")
    if (authority is None or not isinstance(root, Mapping)
            or capture_canonical_sha256(root) != authority.root_digest):
        return []
    nodes: list[dict[str, Any]] = []

    def visit(node):
        if not isinstance(node, Mapping):
            raise ValueError("invalid sealed node")
        nodes.append(dict(node))
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("invalid sealed children")
        for child in children:
            visit(child)

    visit(root)
    return nodes


def _sealed_nodes(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project nodes from the exact hierarchy root sealed by capture authority."""
    from talkback_lib.hierarchy_snapshot import flatten_service_hierarchy

    if not _sealed_raw_nodes(raw):
        return []
    root = raw["_capture_root_tree"]
    return flatten_service_hierarchy({"success": True, "windows": [
        {"active": True, "focused": True, "root": deepcopy(dict(root))}]})


def _capture_bound(raw: Any, marker: Any, scenario_id: str, run_id: str, step: int) -> bool:
    if not isinstance(raw, Mapping) or not isinstance(marker, Mapping):
        return False
    envelope = raw.get("production_observation_envelope")
    if not isinstance(envelope, Mapping):
        return False
    authority = validate_capture_authority(raw.get("capture_authority"))
    capture = raw.get("capture_id")
    return bool(
        scenario_id and run_id and authority is not None and capture and _sealed_nodes(raw)
        and raw.get("scenario_id") == envelope.get("scenario_id") == scenario_id
        and raw.get("scenario_run_id") == envelope.get("scenario_run_id") == run_id
        and envelope.get("step_index") == step
        and raw.get("production_observation_current") is True
        and raw.get("snapshot_coherent") is True and envelope.get("snapshot_coherent") is True
        and raw.get("hierarchy_complete") is True and envelope.get("hierarchy_complete") is True
        and raw.get("observation_coverage") == envelope.get("coverage") == "OBSERVED_FULL"
        and envelope.get("capture_complete") is True
        and capture == authority.capture_key == envelope.get("capture_id")
        and raw.get("hierarchy_capture_id") == envelope.get("hierarchy_capture_id") == capture
        and raw.get("focus_capture_id") == envelope.get("focus_capture_id") == capture
        and raw.get("geometry_capture_id") == envelope.get("geometry_capture_id")
        and raw.get("geometry_capture_id") in (None, capture)
        and raw.get("package_name") == authority.hierarchy_package_name
        and raw.get("traversal_root_ref") == authority.root_ref
        and raw.get("traversal_root_window_id") == authority.hierarchy_window_id
        and envelope.get("capture_authority") == authority.to_dict()
        and raw.get("_exploration_observation") == dict(marker) == envelope.get("observation")
    )


def _strict_focus_id(raw: Mapping[str, Any], scenario_id: str) -> str:
    node = raw.get("focus_node")
    if not isinstance(node, Mapping) or node.get("accessibilityFocused") is not True:
        return ""
    nodes = _sealed_nodes(raw)
    detached = raw.get("nodes")
    if not nodes or not isinstance(detached, list):
        return ""
    focused = [item for item in nodes if isinstance(item, Mapping)
               and item.get("accessibilityFocused") is True
               and item.get("isVisibleToUser", item.get("visibleToUser", True)) is not False]
    if len(focused) != 1:
        return ""
    detached_focused = [item for item in detached if isinstance(item, Mapping)
                        and item.get("accessibilityFocused") is True
                        and item.get("isVisibleToUser", item.get("visibleToUser", True)) is not False]
    if len(detached_focused) != 1:
        return ""
    row = {"scenario_id": scenario_id, "actual_focus_node": dict(node),
           "actual_focus_resource_id": node.get("viewIdResourceName") or node.get("resourceId") or "",
           "actual_focus_bounds": node.get("boundsInScreen") or node.get("bounds") or "",
           "actual_focus_visible": node.get("talkbackLabel") or node.get("contentDescription") or node.get("text") or "",
           "actual_focus_accessibility_focused": True}
    actual = focus_instance(row)
    if not actual:
        return ""
    observed = focused[0]
    if str(node.get("className") or node.get("class") or "") != str(
            observed.get("className") or observed.get("class") or ""):
        return ""
    matching = {"scenario_id": scenario_id,
                "view_id": observed.get("viewIdResourceName") or observed.get("resourceId") or "",
                "bounds": observed.get("boundsInScreen") or observed.get("bounds") or ""}
    focus_id = instance_id(actual)
    detached_node = detached_focused[0]
    detached_identity = {"scenario_id": scenario_id,
                         "view_id": detached_node.get("viewIdResourceName") or detached_node.get("resourceId") or "",
                         "bounds": detached_node.get("boundsInScreen") or detached_node.get("bounds") or ""}
    return focus_id if focus_id == instance_id(matching) == instance_id(detached_identity) else ""


def capture_checkpoint(raw: Any, marker: Any, *, clock: Any, receipt_store: Any,
                       scenario_id: str, run_id: str, step: int,
                       source_step: int | None = None,
                       require_focus: bool = True) -> ProgressCheckpoint | None:
    """Seal a current pre-action capture and receipt watermark; fail closed."""
    try:
        generation = str(receipt_store.generation_id or "")
        watermark = receipt_store.receipt_watermark()
        if (not generation or type(watermark) is not int or watermark < 0
                or not _capture_bound(raw, marker, scenario_id, run_id,
                                      step if source_step is None else source_step)
                or not clock.current(dict(marker))
                or (require_focus and not _strict_focus_id(raw, scenario_id))):
            return None
        return ProgressCheckpoint(scenario_id, run_id, step, deepcopy(dict(raw)),
                                  deepcopy(dict(marker)), receipt_store, generation, watermark)
    except Exception:
        return None


def classify_focus_progress(checkpoint: ProgressCheckpoint | None, raw: Any, marker: Any,
                            *, clock: Any, receipt_store: Any, row: Mapping[str, Any],
                            action_request_id: str, invocation_result: Any = None) -> str:
    """Return NEW_VISIT, NO_PROGRESS, STATE_TRANSITION, or UNKNOWN.

    The single current action must have a unique native receipt after the
    checkpoint. The current row must reconcile the two captured focus nodes.
    Request success, candidate identity and graph/shadow state never grant it.
    """
    try:
        if checkpoint is None or receipt_store is not checkpoint.receipt_store:
            return "UNKNOWN"
        scenario, run, step = checkpoint.scenario_id, checkpoint.run_id, checkpoint.step
        if (receipt_store.generation_id != checkpoint.receipt_generation
                or not _capture_bound(raw, marker, scenario, run, step)
                or not clock.current(dict(marker))
                or row.get("scenario_id") != scenario or row.get("scenario_run_id") != run
                or row.get("step_index") != step
                or raw.get("package_name") != checkpoint.capture.get("package_name")
                or raw.get("traversal_root_ref") != checkpoint.capture.get("traversal_root_ref")
                or raw.get("traversal_root_window_id") != checkpoint.capture.get("traversal_root_window_id")):
            return "UNKNOWN"
        before = checkpoint.marker
        if (not action_request_id or raw.get("capture_id") == checkpoint.capture.get("capture_id")
                or marker.get("scope_id") != before.get("scope_id")
                or marker.get("context_revision") != before.get("context_revision")
                or type(before.get("action_epoch")) is not int
                or marker.get("action_epoch") != before["action_epoch"] + 1
                or type(marker.get("observation_sequence")) is not int
                or type(before.get("observation_sequence")) is not int
                or marker["observation_sequence"] <= before["observation_sequence"]):
            return "UNKNOWN"
        receipts = receipt_store.receipts_after(checkpoint.receipt_watermark)
        if len(receipts) != 1:
            return "UNKNOWN"
        receipt = receipts[0]
        if (receipt.get("store_generation") != checkpoint.receipt_generation
                or receipt.get("request_id") != action_request_id
                or not receipt.get("operation_id")
                or receipt.get("ownership_status") != "KNOWN"
                or receipt.get("native_boundary_status") != "ENTERED"
                or receipt.get("dispatch_status") != "NATIVE_DISPATCH_ATTEMPTED"):
            return "UNKNOWN"
        action = row.get("phase6_current_action_type")
        if action == "SMART_NEXT":
            generation = row.get("smart_nav_invocation_generation")
            if (row.get("smart_nav_req_id") != action_request_id
                    or type(generation) is not int or generation <= 0
                    or row.get("smart_nav_result_generation") != generation
                    or not isinstance(invocation_result, Mapping)
                    or str(invocation_result.get("req_id") or invocation_result.get("reqId")
                           or invocation_result.get("requestId") or "") != action_request_id
                    or receipt.get("action_type") != "SMART_NEXT"
                    or receipt.get("owner") != "SEQUENTIAL"):
                return "UNKNOWN"
        elif action == "TARGETED_FOCUS":
            if (row.get("target_focus_attempted") is not True
                    or not row.get("target_focus_attempt_id")
                    or row.get("target_focus_request_id") != action_request_id
                    or receipt.get("action_type") != "TARGET_FOCUS_COMMIT"
                    or receipt.get("owner") != "TARGETED"):
                return "UNKNOWN"
        elif action == "CONTROLLED_FOCUS":
            if (row.get("controlled_focus_request_id") != action_request_id
                    or row.get("controlled_focus_operation_id") != receipt.get("operation_id")
                    or receipt.get("action_type") != "TARGET_FOCUS_COMMIT"
                    or receipt.get("owner") != "TARGETED"):
                return "UNKNOWN"
        elif action == "RECOVERY":
            if (row.get("recovery_action_request_id") != action_request_id
                    or row.get("recovery_operation_id") != receipt.get("operation_id")
                    or receipt.get("action_type") != "FOCUS_IN_BOUNDS"
                    or receipt.get("owner") != "RECOVERY"):
                return "UNKNOWN"
        else:
            return "UNKNOWN"
        clock_receipt = marker.get("action_ownership")
        if (not isinstance(clock_receipt, Mapping)
                or clock_receipt.get("request_id") != action_request_id
                or clock_receipt.get("owner") != receipt.get("owner")
                or clock_receipt.get("action_type") != receipt.get("action_type")
                or clock_receipt.get("action_epoch") != marker.get("action_epoch")
                or clock_receipt.get("ownership_status") != "KNOWN"):
            return "UNKNOWN"
        before_id = _strict_focus_id(checkpoint.capture, scenario)
        after_id = _strict_focus_id(raw, scenario)
        if not before_id or not after_id or row.get("actual_focus_instance_id") != after_id:
            return "UNKNOWN"
        transition = row.get("focus_transition_status")
        visit = row.get("visit_record_status")
        progress = row.get("progress_status")
        reconciled_before = str(row.get("actual_focus_before_id") or "")
        if (transition == "CONFIRMED_MOVED" and reconciled_before and reconciled_before != after_id
                and visit == "RECORDED"
                and progress == "PROGRESS" and row.get("reconciled_visit_instance_id") == after_id):
            return "NEW_VISIT"
        if transition not in {"CONFIRMED_MOVED", "CONFIRMED_UNCHANGED"}:
            return "UNKNOWN"
        if transition == "CONFIRMED_MOVED" and (not reconciled_before or reconciled_before == after_id):
            return "UNKNOWN"
        if transition == "CONFIRMED_UNCHANGED" and reconciled_before != after_id:
            return "UNKNOWN"
        no_progress = (
            (transition == "CONFIRMED_MOVED" and visit == "ALREADY_VISITED"
             and progress == "NO_PROGRESS_DUPLICATE_INSTANCE"
             and row.get("reconciled_visit_instance_id") == after_id)
            or (transition == "CONFIRMED_UNCHANGED"
                and visit == "ALREADY_VISITED" and progress == "NO_PROGRESS_UNCHANGED")
        )
        if not no_progress:
            return "UNKNOWN"
        if meaningful_semantic_transition(
                {"nodes": _sealed_raw_nodes(checkpoint.capture)}, {"nodes": _sealed_raw_nodes(raw)}):
            return "STATE_TRANSITION"
        # Capability/frontier observations are not production progress
        # authority. A change also means the relevant state is not proven
        # stable, so it cannot count as a no-progress observation.
        def capability(value):
            item = value.get("capability")
            if not isinstance(item, Mapping):
                return None
            return tuple(item.get(key) for key in (
                "vertical_can_scroll_forward", "can_scroll_forward", "contradictory"))
        if capability(checkpoint.capture) != capability(raw):
            return "UNKNOWN"
        return "NO_PROGRESS"
    except Exception:
        return "UNKNOWN"


def classify_scroll_progress(checkpoint: ProgressCheckpoint | None, raw: Any, marker: Any,
                             *, clock: Any, receipt_store: Any, transition: Any,
                             owner: Any) -> str:
    """Verify one owned scroll and compare the two current viewport captures.

    The caller must take the checkpoint immediately before this scroll and
    enter a native operation around the dispatch. A no-op never grants progress.
    This function does not itself publish a graph edge or reset a counter.
    """
    try:
        from tb_runner.scroll_reliability import normalized_bounds, scroll_axis, viewport

        if checkpoint is None or receipt_store is not checkpoint.receipt_store:
            return "UNKNOWN"
        scenario, run, step = checkpoint.scenario_id, checkpoint.run_id, checkpoint.step
        if (not isinstance(transition, Mapping) or not isinstance(owner, Mapping)
                or receipt_store.generation_id != checkpoint.receipt_generation
                or not _capture_bound(raw, marker, scenario, run, step)
                or not clock.current(dict(marker))
                or raw.get("capture_id") == checkpoint.capture.get("capture_id")
                or raw.get("package_name") != checkpoint.capture.get("package_name")
                or raw.get("traversal_root_ref") != checkpoint.capture.get("traversal_root_ref")
                or raw.get("traversal_root_window_id") != checkpoint.capture.get("traversal_root_window_id")):
            return "UNKNOWN"
        before = checkpoint.marker
        if (marker.get("scope_id") != before.get("scope_id")
                or marker.get("context_revision") != before.get("context_revision")
                or type(before.get("action_epoch")) is not int
                or marker.get("action_epoch") != before["action_epoch"] + 1
                or type(before.get("observation_sequence")) is not int
                or type(marker.get("observation_sequence")) is not int
                or marker["observation_sequence"] <= before["observation_sequence"]):
            return "UNKNOWN"
        capability = checkpoint.capture.get("capability")
        if not isinstance(capability, Mapping):
            return "UNKNOWN"
        container = capability.get("container")
        target = transition.get("action_target")
        result = transition.get("action_result")
        if not all(isinstance(value, Mapping) for value in (target, result)):
            return "UNKNOWN"
        path = str(owner.get("path") or "")
        bounds = normalized_bounds(owner.get("bounds"))
        owner_identity = str(owner.get("identity") or "").strip()
        request = str(transition.get("action_request_id") or "")
        if (owner.get("status") != "RESOLVED" or not owner_identity or not path or not bounds
                or capability.get("vertical_can_scroll_forward", capability.get("can_scroll_forward")) is not True
                or capability.get("contradictory") is True
                or transition.get("scenario_id") != scenario or transition.get("step_index") != step
                or transition.get("action_type") != "SCROLL_FORWARD" or transition.get("direction") != "down"
                or not request or transition.get("action_result_request_id") != request
                or transition.get("action_result_correlated") is not True
                or str(result.get("reqId") or result.get("requestId") or result.get("request_id") or "") != request
                or result.get("action") != "SCROLL_FORWARD" or result.get("actionAttempted") is not True):
            return "UNKNOWN"
        eligible_owners = [node for node in _sealed_nodes(checkpoint.capture)
                           if node.get("scrollable") is True
                           and node.get("visibleToUser", True) is not False
                           and node.get("enabled", True) is not False
                           and scroll_axis(node)[0] in {"VERTICAL", "BIDIRECTIONAL"}]
        matching_owners = [node for node in eligible_owners
                           if str(node.get("stable_node_path") or node.get("stableNodePath")
                                  or node.get("nodePath") or node.get("path") or "") == path
                           and normalized_bounds(node.get("boundsInScreen") or node.get("bounds")) == bounds]
        if len(matching_owners) != 1:
            return "UNKNOWN"
        mode = target.get("mode")
        if mode == "EXPLICIT_CONTAINER":
            if (not isinstance(container, Mapping) or container.get("path") != path
                    or target.get("container_path") != path
                    or normalized_bounds(target.get("container_bounds")) != bounds
                    or result.get("explicitTarget") is not True
                    or result.get("scrollContainerPath") != path):
                return "UNKNOWN"
        elif mode == "ACCESSIBILITY_FALLBACK":
            generic_fallback_authorized = (
                result.get("fallbackToTreeSearchScrollable") is True
                or result.get("fallbackToLargestScrollable") is True
            )
            if (len(eligible_owners) != 1 or not generic_fallback_authorized
                    or result.get("explicitTarget") is not False
                    or result.get("scrollContainerPath")
                    or result.get("scrollableNodeFound") is not True
                    or not result.get("scrollContainerClass")
                    or result.get("scrollContainerClass") != matching_owners[0].get("className")):
                return "UNKNOWN"
        else:
            return "UNKNOWN"
        if (type(transition.get("action_success")) is not bool
                or type(result.get("success")) is not bool
                or transition.get("action_success") != result.get("success")):
            return "UNKNOWN"
        receipts = receipt_store.receipts_after(checkpoint.receipt_watermark)
        if len(receipts) != 1:
            return "UNKNOWN"
        receipt = receipts[0]
        clock_receipt = marker.get("action_ownership")
        if (receipt.get("store_generation") != checkpoint.receipt_generation
                or not receipt.get("operation_id") or receipt.get("request_id") != request
                or receipt.get("action_type") != "SCROLL" or receipt.get("owner") != "PRIMARY"
                or receipt.get("ownership_status") != "KNOWN"
                or receipt.get("native_boundary_status") != "ENTERED"
                or receipt.get("dispatch_status") != "NATIVE_DISPATCH_ATTEMPTED"
                or not isinstance(clock_receipt, Mapping)
                or clock_receipt.get("request_id") != request
                or clock_receipt.get("action_type") != "SCROLL"
                or clock_receipt.get("owner") != "PRIMARY"
                or clock_receipt.get("action_epoch") != marker.get("action_epoch")
                or clock_receipt.get("ownership_status") != "KNOWN"):
            return "UNKNOWN"
        if transition.get("action_success") is not True or result.get("success") is not True:
            return "NO_PROGRESS"
        before_view = viewport(_sealed_nodes(checkpoint.capture), scenario,
                               {"boundsInScreen": bounds})
        after_view = viewport(_sealed_nodes(raw), scenario, {"boundsInScreen": bounds})
        if not before_view["valid"] or not after_view["valid"]:
            return "UNKNOWN"
        if before_view["stable_signature"] == after_view["stable_signature"]:
            return "NO_PROGRESS"
        return "SCROLL_CHANGE"
    except Exception:
        return "UNKNOWN"


def _stable_semantic_nodes(raw: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, bool]]:
    """Select comparable boolean state for uniquely identified visible nodes.

    Text, labels, geometry, focus, timestamps and generated state IDs are not
    semantic transition evidence. Duplicate resource/class pairs are excluded
    because a before/after comparison cannot reliably match their instances.
    """
    nodes = raw.get("nodes")
    if not isinstance(nodes, list):
        return {}
    candidates: list[tuple[tuple[str, str], dict[str, bool]]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        if node.get("isVisibleToUser", node.get("visibleToUser", True)) is False:
            continue
        rid = str(node.get("viewIdResourceName") or node.get("resourceId") or "").strip()
        cls = str(node.get("className") or node.get("class") or "").strip()
        if not rid or not cls:
            continue
        flags = {name: node[name] for name in ("checked", "selected", "enabled")
                 if type(node.get(name)) is bool}
        candidates.append(((rid, cls), flags))
    counts = Counter(key for key, _ in candidates)
    return {key: flags for key, flags in candidates if counts[key] == 1}


def meaningful_semantic_transition(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    """Identify a comparable state-flag change, never a novel state ID alone.

    This is only a semantic comparison. It supplies no capture, operation,
    invocation, or visit authority, and must not be used alone as progress.
    """
    old = _stable_semantic_nodes(before)
    new = _stable_semantic_nodes(after)
    for identity in old.keys() & new.keys():
        for field in old[identity].keys() & new[identity].keys():
            if old[identity][field] != new[identity][field]:
                return True
    # A stable, actionable resource entering or leaving the current hierarchy
    # is structural state, not a text, position, or graph-ID change. Anonymous
    # nodes are excluded because they cannot be compared reliably across views.
    def actionable(raw):
        nodes = raw.get("nodes")
        if not isinstance(nodes, list):
            return Counter()
        return Counter(
            (str(node.get("viewIdResourceName") or node.get("resourceId") or "").strip(),
             str(node.get("className") or node.get("class") or "").strip())
            for node in nodes if isinstance(node, Mapping)
            and node.get("isVisibleToUser", node.get("visibleToUser", True)) is not False
            and str(node.get("viewIdResourceName") or node.get("resourceId") or "").strip()
            and str(node.get("className") or node.get("class") or "").strip()
            and any(node.get(key) is True for key in ("clickable", "focusable", "scrollable", "checkable"))
        )
    if actionable(before) != actionable(after):
        return True
    return False
