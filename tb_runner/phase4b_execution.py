"""Controlled adapter using production actions, collection and reconciliation.

Imported only by the explicit Phase 4B harness. No normal runner hook enables it.
"""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy

from talkback_lib.window_lifecycle import get_talkback_restart_event
from talkback_lib.utils import normalize_bounds
from tb_runner import collection_flow, focus_reconciliation, scroll_reliability
from tb_runner.phase4b_authority import correlated_result
from tb_runner.phase4b_target_binding import actual_target_matches, resolve_focus_target
from tb_runner.traversal_reliability import focus_instance


def focus_row(node, scenario):
    return dict(scenario_id=scenario, actual_focus_node=deepcopy(node),
                actual_focus_accessibility_focused=node.get("accessibilityFocused"),
                actual_focus_resource_id=node.get("viewIdResourceName") or node.get("resourceId") or "",
                actual_focus_bounds=normalize_bounds(node),
                actual_focus_class_name=node.get("className", ""),
                actual_focus_visible=node.get("text") or node.get("contentDescription")
                    or node.get("talkbackLabel") or node.get("mergedLabel") or "",
                actual_focus_payload_source="phase4b_fresh_strict_before")


def coherent_focus(raw):
    """Require one tree accessibility focus agreeing with the strict focus read."""
    focus = raw.get("focus_node") or {}
    if focus.get("accessibilityFocused") is not True or focus_instance(focus_row(focus, "coherence_check")) is None:
        return False
    focused = [n for n in scroll_reliability.flat_nodes(raw.get("nodes", []))
               if n.get("accessibilityFocused") is True]
    if len(focused) != 1:
        return False
    def key(n):
        return (n.get("viewIdResourceName") or n.get("resourceId") or "",
                scroll_reliability.normalized_bounds(n.get("boundsInScreen") or n.get("bounds") or ""))
    return bool(key(focus)[1] and key(focus) == key(focused[0]))


def safe_scroll_container(raw, recommendation):
    cap = raw.get("capability") or {}
    container = cap.get("container") or {}
    target = recommendation.to_dict().get("recommended_target") or {}
    return bool(cap.get("axis_contract") == "axis-v1" and cap.get("contradictory") is False
                and cap.get("can_scroll_forward") is True and container.get("path")
                and container.get("axis") in {"VERTICAL", "BIDIRECTIONAL"}
                and scroll_reliability.normalized_bounds(container.get("boundsInScreen")) == target.get("bounds"))


def geometry_in_viewport(raw, recommendation):
    from tb_runner.utils import parse_bounds_str
    bounds = parse_bounds_str((recommendation.to_dict().get("recommended_target") or {}).get("bounds", ""))
    display = raw.get("display_bounds")
    return bool(bounds and isinstance(display, (list, tuple)) and len(display) == 4
                and display[0] <= bounds[0] < bounds[2] <= display[2]
                and display[1] <= bounds[1] < bounds[3] <= display[3])


def scroll_request_audit(client, scroll, audit, **kwargs):
    """Observe SCROLL's native exact-request read without changing transport.

    SCROLL has no active focus transaction, so _evidence_active_request_id is
    not its request oracle. Capture the explicit SCROLL_RESULT read argument.
    """
    reader = getattr(client, "_read_log_result", None)
    had_override = "_read_log_result" in vars(client)
    if not callable(reader):
        return scroll(**kwargs)
    def observed_reader(*args, **read_kwargs):
        prefix = read_kwargs.get("prefix", args[1] if len(args) > 1 else None)
        request = read_kwargs.get("req_id", args[2] if len(args) > 2 else None)
        result = reader(*args, **read_kwargs)
        if prefix == "SCROLL_RESULT":
            audit.update(helper_request_id=str(request or ""), helper_ack_result=deepcopy(result),
                helper_result_correlated=bool(request and str(request) == str(result.get("reqId") or "")),
                helper_request_source="SCROLL_RESULT_EXPLICIT_TRANSPORT_ARGUMENT")
        return result
    client._read_log_result = observed_reader
    try:
        return scroll(**kwargs)
    finally:
        if had_override:
            client._read_log_result = reader
        else:
            del client._read_log_result


def controlled_collect(*, client, dev, scenario, step, raw, recommendation, decision,
                       budget, collect, collect_kwargs, refresh, output_dir, audit, audit_sink=None,
                       focus_authorization=None):
    """At most one controlled action and one production fallback in a step.

    The returned row still travels through the complete production main loop.
    The pure reconciliation preview decides fallback only; its credit is never
    applied. Production reconciliation and metrics are the sole visit owners.
    """
    def emit(event):
        if audit_sink is not None:
            audit_sink(dict(event=event, **deepcopy(audit)))

    def fallback(reason):
        budget.fallback_count += 1
        audit.update(fallback_used=True, fallback_reason=reason,
                     production_fallback_action="FOCUS_NEXT")
        emit("BEFORE_PRODUCTION_FALLBACK")
        row = collect(**collect_kwargs)
        ack = deepcopy(getattr(client, "last_smart_nav_result", {}) or {})
        audit.update(fallback_helper_request_id=ack.get("reqId"), fallback_helper_ack_result=ack,
                     fallback_result_correlated=correlated_result(client, ack))
        if not audit.get("planner_executed"):
            audit.update(helper_request_id=ack.get("reqId"), helper_ack_result=ack)
        emit("AFTER_PRODUCTION_FALLBACK")
        return row

    if not decision.allowed:
        audit["classification"] = ("PRODUCTION_ONLY" if decision.mode == "SHADOW_ONLY" else
                                    "PLANNER_NO_SAFE_ACTION" if decision.reason == "NO_SAFE_PLANNER_ACTION" else
                                    "PLANNER_BLOCKED_BY_GATE")
        audit["actual_execution_mode"] = decision.mode
        return fallback(decision.reason)
    chosen = recommendation.to_dict()
    budget.reserve(decision.mode, chosen["recommended_instance_id"],
                   raw["snapshot_hash"], (chosen["planner_state_id"], chosen["semantic_substates"]))
    audit.update(actual_execution_mode=decision.mode, planner_executed=False,
                 classification="PLANNER_EXECUTED", fallback_used=False, fallback_reason="")
    before = focus_row(raw.get("focus_node") or {}, scenario)
    audit["actual_focus_before"] = before
    if decision.mode == "CONTROLLED_SCROLL":
        observed = scroll_reliability.capture(client, dev, scenario, step_index=step,
                                              evidence="phase4b_verified_scroll_before")
        # Revalidate the actual production container; the earlier capability
        # copy must not authorize a different path/container at execution time.
        if not safe_scroll_container(dict(capability=observed["capability"]), recommendation):
            budget.outcome("SCROLL_INDETERMINATE", False)
            audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED")
            return fallback("SCROLL_CONTAINER_CHANGED")
        audit["planner_executed"] = True
        emit("BEFORE_CONTROLLED_SCROLL")
        original_scroll = getattr(client, "scroll", None)
        had_scroll_override = "scroll" in vars(client)
        def correlated_scroll(**kwargs):
            return scroll_request_audit(client, original_scroll, audit, **kwargs)
        client.scroll = correlated_scroll
        try:
            result, after = scroll_reliability.verified_scroll(client, dev, scenario, step,
                                                             before=observed, output_base_dir=output_dir)
        finally:
            if had_scroll_override:
                client.scroll = original_scroll
            else:
                del client.scroll
        status = ("SCROLL_MOVED" if result["status"] == "SCROLL_MOVED" else
                  "SCROLL_NO_MOVEMENT" if result["before"]["valid"] and result["after"]["valid"]
                  and result["action_success"] and not result["viewport_changed"] else "SCROLL_INDETERMINATE")
        audit.update(scroll_result=status, scroll_transition=result)
        emit("AFTER_CONTROLLED_SCROLL")
        budget.outcome(status, status == "SCROLL_MOVED")
        # Always refresh, even for uncertain/no movement. No old rank is reused.
        refreshed = refresh()
        audit["post_scroll_refresh"] = refreshed
        if status != "SCROLL_MOVED":
            audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED")
            return fallback(status)
        row = collect(**{**collect_kwargs, "move": False})
        row.update(move_result="scrolled", scroll_transition=result, phase4b_before_row=before)
        return row

    target = chosen["recommended_target"]
    # Select exactly the freshly gated node, never a label/scenario guess.
    node, binding = resolve_focus_target(raw, chosen, scenario)
    audit["target_binding"] = binding
    if node is None:
        budget.outcome("TARGET_DISAPPEARED_OR_AMBIGUOUS", False)
        audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED")
        return fallback("TARGET_DISAPPEARED_OR_AMBIGUOUS")
    target_meta = dict(focus_node=raw.get("focus_node"), actual_focus_node=raw.get("focus_node"))
    client._evidence_set_step(step, phase="main_loop")
    emit("BEFORE_CONTROLLED_TARGET_FOCUS")
    original_target_commit = client.target_focus_commit
    had_target_override = "target_focus_commit" in vars(client)
    def focusable_commit(**kwargs):
        return original_target_commit(**{**kwargs, "target": {**kwargs["target"], "require_focusable": True}})
    client.target_focus_commit = focusable_commit
    try:
        authorization = (focus_authorization(target, node) if focus_authorization is not None
                        else nullcontext())
        with authorization:
            _, status, observed_focus = collection_flow._maybe_realign_focus_to_representative(
                row=target_meta, client=client, dev=dev, selected_node=node,
                selected_rid=target["resource_id"], selected_label="", selected_bounds=target["bounds"],
                scenario_id=scenario, step_idx=step, force_reason="phase4b_gated_structural_target")
    finally:
        if had_target_override:
            client.target_focus_commit = original_target_commit
        else:
            del client.target_focus_commit
    ack = deepcopy(getattr(client, "last_target_action_result", {}) or {})
    correlated = correlated_result(client, ack)
    audit["planner_executed"] = target_meta.get("target_focus_attempted") is True
    audit.update(helper_request_id=str(getattr(client, "_evidence_active_request_id", "") or ""),
                 helper_ack_result=ack, helper_result_correlated=correlated,
                 target_attempt_id=target_meta.get("target_focus_attempt_id"), attempt_credit=1,
                 immediate_actual_focus=observed_focus, target_focus_status=status)
    emit("AFTER_CONTROLLED_TARGET_FOCUS")
    # Prevent a previous SMART_NEXT result leaking into a target-only row.
    client.last_smart_nav_result, client.last_smart_nav_terminal = {}, False
    row = collect(**{**collect_kwargs, "move": False})
    row.update(scenario_id=scenario, scenario_type="content")
    row.update({k: v for k, v in target_meta.items() if k.startswith("target_focus_")})
    row["phase4b_before_row"] = before
    row["move_result"] = client._normalize_action_result(success=bool(ack.get("success")),
                                                         status="MOVED" if ack.get("success") else "FAILED", raw=ack)
    preview = focus_reconciliation.reconcile_focus(row=row, previous_row=before, scenario_id=scenario,
        inventory=raw.get("nodes", []), expected_candidates=raw.get("nodes", []),
        physical_visit_confirmed=False, planning_consumed=False)
    moved = preview["focus_transition_status"] == "CONFIRMED_MOVED"
    matched = (moved and preview["actual_focus_instance_id"] == chosen["recommended_instance_id"]
               and actual_target_matches(row.get("actual_focus_node"), target))
    audit["focus_preview"] = {k: v for k, v in preview.items() if k not in {"actual_item", "mapped_candidate"}}
    emit("CONTROLLED_FOCUS_PREVIEW")
    budget.outcome(preview["focus_transition_status"], matched and correlated)
    if get_talkback_restart_event(client):
        # The outer monitor/main loop owns immediate hard-stop; no fallback I/O.
        audit.update(planner_failed=True, fallback_reason="LIFECYCLE_HARD_STOP")
        return row
    if not correlated or not moved:
        audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED",
                     controlled_action_status="PLANNER_ACTION_FAILED")
        return fallback("STALE_REQUEST_RESULT" if not correlated else
                        "INDETERMINATE_FOCUS" if preview["focus_transition_status"] in {"UNAVAILABLE", "AMBIGUOUS"}
                        else "FOCUS_EXECUTION_FAILED")
    if not matched:
        audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED",
                     controlled_action_status="PLANNER_ACTION_FAILED")
        return fallback("FOCUS_TARGET_MISMATCH")
    return row
