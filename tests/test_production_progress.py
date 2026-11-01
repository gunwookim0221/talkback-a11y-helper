from copy import deepcopy
from types import SimpleNamespace

import pytest

from tb_runner.production_progress import (
    _strict_focus_id, capture_checkpoint, classify_focus_progress, classify_scroll_progress,
    meaningful_semantic_transition,
)
from talkback_lib.exploration_evidence_clock import EvidenceClock
from talkback_lib.native_dispatch_evidence import NativeDispatchReceiptStore, dispatch_owner
from phase6d_capture_support import attach_capture_authority, bind_observation_marker
from test_phase6d3a_rf5r_handoff import _production_raw, SCENARIO, RUN_ID
from tb_runner import collection_flow
from tb_runner.traversal_reliability import TraversalMetrics


def observation(**changes):
    node = {"viewIdResourceName": "id/control", "className": "Button",
            "visibleToUser": True, "checked": False, "enabled": True,
            "text": "before", "boundsInScreen": "[0,0][50,50]"}
    node.update(changes)
    return {"nodes": [node], "state_id": "state-a", "timestamp": "before"}


@pytest.mark.parametrize("field", ["checked", "selected", "enabled"])
def test_comparable_boolean_change_is_semantic(field):
    before = observation(**{field: False})
    after = deepcopy(before)
    after["nodes"][0][field] = True
    assert meaningful_semantic_transition(before, after)


def test_id_text_focus_geometry_and_timestamp_alone_are_not_semantic():
    before = observation()
    after = deepcopy(before)
    after.update(state_id="other", timestamp="after")
    after["nodes"][0].update(text="after", boundsInScreen="[0,10][50,60]",
                              accessibilityFocused=True, focused=True)
    assert not meaningful_semantic_transition(before, after)


def test_ambiguous_duplicate_identity_is_not_compared():
    before = observation()
    before["nodes"].append({"viewIdResourceName": "id/control", "className": "Button"})
    after = observation(checked=True)
    assert not meaningful_semantic_transition(before, after)


def test_unshared_or_unknown_boolean_cannot_create_transition():
    before = observation(checked=None)
    after = observation(checked=True)
    assert not meaningful_semantic_transition(before, after)


def test_new_actionable_resource_is_meaningful_but_anonymous_change_is_not():
    before = observation()
    after = deepcopy(before)
    after["nodes"].append({"viewIdResourceName": "id/new", "className": "Button", "clickable": True})
    assert meaningful_semantic_transition(before, after)
    after["nodes"][-1]["viewIdResourceName"] = ""
    assert not meaningful_semantic_transition(before, after)


def bound_operation(action="SMART_NEXT", focused="sensor"):
    clock = EvidenceClock()
    store = NativeDispatchReceiptStore()
    before = _production_raw(focused="more", request_id="before-capture")
    before["production_observation_envelope"]["step_index"] = 5
    marker = clock.finish_observation(clock.begin_observation())
    bind_observation_marker(before, marker)
    checkpoint = capture_checkpoint(before, marker, clock=clock, receipt_store=store,
                                    scenario_id=SCENARIO, run_id=RUN_ID, step=5)
    assert checkpoint is not None
    args = ["shell", "am", "broadcast", "-a",
            "com.iotpart.sqe.talkbackhelper." + action, "--es", "reqId", "request-1"]
    if action == "FOCUS_IN_BOUNDS":
        with dispatch_owner("RECOVERY"):
            store.observe(args, operation_id="operation-1")
            clock.dispatch(args)
    else:
        store.observe(args, operation_id="operation-1")
        clock.dispatch(args)
    after = _production_raw(focused=focused, request_id="after-capture")
    after["production_observation_envelope"]["step_index"] = 5
    marker = clock.finish_observation(clock.begin_observation())
    bind_observation_marker(after, marker)
    before_id, after_id = _strict_focus_id(before, SCENARIO), _strict_focus_id(after, SCENARIO)
    row = dict(scenario_id=SCENARIO, scenario_run_id=RUN_ID, step_index=5,
               phase6_current_action_type="SMART_NEXT", smart_nav_req_id="request-1",
               smart_nav_invocation_generation=1, smart_nav_result_generation=1,
               actual_focus_before_id=before_id, actual_focus_instance_id=after_id,
               reconciled_visit_instance_id=after_id, focus_transition_status="CONFIRMED_MOVED",
               visit_record_status="ALREADY_VISITED", progress_status="NO_PROGRESS_DUPLICATE_INSTANCE")
    if action == "TARGET_FOCUS_COMMIT":
        row.update(phase6_current_action_type="TARGETED_FOCUS", target_focus_attempted=True,
                   target_focus_attempt_id="attempt-1", target_focus_request_id="request-1")
    elif action == "FOCUS_IN_BOUNDS":
        row.update(phase6_current_action_type="RECOVERY", recovery_operation_id="operation-1",
                   recovery_action_request_id="request-1")
    if focused == "more":
        row.update(focus_transition_status="CONFIRMED_UNCHANGED",
                   progress_status="NO_PROGRESS_UNCHANGED", reconciled_visit_instance_id="")
    return checkpoint, after, marker, clock, store, row


def classify(parts, request="request-1"):
    checkpoint, after, marker, clock, store, row = parts
    return classify_focus_progress(checkpoint, after, marker, clock=clock, receipt_store=store,
                                   row=row, action_request_id=request,
                                   invocation_result={"reqId": "request-1"})


def evaluate_production(parts, *, same_count=3, capture_status="CURRENT"):
    checkpoint, after, marker, clock, store, row = parts
    row.update(state_graph_observation=after, _exploration_observation=marker,
               production_observation_capture_status=capture_status, move_result="moved",
               capture_id=after["capture_id"],
               production_observation_envelope=deepcopy(after["production_observation_envelope"]),
               recent_semantic_unique_count=5)
    client = SimpleNamespace(
        _adb_device=SimpleNamespace(shadow_evidence_clock=clock, native_dispatch_receipts=store),
        _production_progress_pending=checkpoint, _smart_nav_invocation_generation=1,
        _smart_nav_result_generation=1, _last_smart_nav_invocation_result={"reqId": "request-1"},
    )
    state = SimpleNamespace(production_progress_enabled=True, production_progress_scope=None,
                            production_progress_receipt=0, prev_fingerprint=("", "", ""),
                            fail_count=0, same_count=same_count)
    status = collection_flow._production_progress_for_row(client, state, row)
    client._production_progress_bound = (row, status, deepcopy(marker))
    outcome = collection_flow._apply_stop_evaluation_phase_impl(
        client=client, state=state, row=row, previous_row={"step_index": 4},
        tab_cfg={"scenario_type": "content", "stop_policy": {}},
        should_stop_fn=collection_flow.should_stop, build_inputs_fn=lambda **_: {},
    )
    return client, state, row, outcome


def test_production_revisit_reaches_stop_even_when_semantic_window_is_wide():
    _client, state, row, (stop, reason, details, _) = evaluate_production(bound_operation())
    assert row["production_progress_status"] == "NO_PROGRESS"
    assert (stop, reason, state.same_count, details["no_progress"]) == (True, "repeat_no_progress", 4, True)


def test_production_new_visit_resets_count_and_prevents_repeat_stop():
    parts = bound_operation()
    parts[-1].update(visit_record_status="RECORDED", progress_status="PROGRESS")
    _client, state, row, (stop, _, _, _) = evaluate_production(parts, same_count=8)
    assert row["production_progress_status"] == "NEW_VISIT"
    assert not stop and state.same_count == 0


def test_ambiguous_post_scroll_visit_identity_cannot_be_production_progress():
    parts = bound_operation()
    parts[-1].update(visit_record_status="NOT_RECORDED_AMBIGUOUS",
                     progress_status="NO_PROGRESS_AMBIGUOUS",
                     reconciled_visit_instance_id="")
    assert classify(parts) == "UNKNOWN"


def test_current_reached_end_without_change_neither_resets_nor_completes():
    parts = bound_operation(focused="more")
    parts[-1].update(last_smart_nav_terminal=True, last_smart_nav_result="reached_end")
    _client, state, row, (stop, _, _, _) = evaluate_production(parts, same_count=1)
    assert row["production_progress_status"] == "NO_PROGRESS"
    assert not stop and state.same_count == 2


@pytest.mark.parametrize("mutation", ["unaligned", "stale", "ambiguous"])
def test_unproven_reconciliation_neither_resets_nor_increments_production_count(mutation):
    parts = bound_operation()
    parts[-1].update(visit_record_status="RECORDED", progress_status="PROGRESS")
    if mutation == "stale":
        parts[3].begin_observation()
    elif mutation == "ambiguous":
        parts[-1]["focus_transition_status"] = "AMBIGUOUS"
    _client, state, row, (stop, _, _, _) = evaluate_production(
        parts, same_count=3, capture_status="UNALIGNED" if mutation == "unaligned" else "CURRENT")
    assert row["production_progress_status"] == "UNKNOWN"
    assert not stop and state.same_count == 3


def test_production_receipt_cannot_be_consumed_twice():
    client, state, row, _ = evaluate_production(bound_operation())
    outcome = collection_flow._apply_stop_evaluation_phase_impl(
        client=client, state=state, row=row, previous_row={"step_index": 4},
        tab_cfg={"scenario_type": "content", "stop_policy": {}},
        should_stop_fn=collection_flow.should_stop, build_inputs_fn=lambda **_: {},
    )
    assert row["production_progress_status"] == "UNKNOWN"
    assert state.same_count == 4 and outcome[0] is False


def test_unaligned_reconciliation_is_withheld_from_actual_visit_ledger():
    checkpoint, raw, marker, clock, store, row = bound_operation()
    node = deepcopy(raw["focus_node"])
    row.update(state_graph_observation=raw, _exploration_observation=marker,
               production_observation_capture_status="UNALIGNED", capture_id=raw["capture_id"],
               production_observation_envelope=deepcopy(raw["production_observation_envelope"]),
               actual_focus_node=node, actual_focus_accessibility_focused=True,
               actual_focus_resource_id=node["viewIdResourceName"],
               actual_focus_bounds=node["boundsInScreen"], actual_focus_visible=node["text"],
               move_result="moved")
    client = SimpleNamespace(_adb_device=SimpleNamespace(shadow_evidence_clock=clock,
                                                         native_dispatch_receipts=store),
                             _production_progress_pending=checkpoint,
                             _smart_nav_invocation_generation=1, _smart_nav_result_generation=1,
                             _last_smart_nav_invocation_result={"reqId": "request-1"})
    state = collection_flow._build_main_loop_state_from_anchor(
        {}, anchor_fingerprint="", anchor_repeat_count=0, step_index=0)
    state.reliability_metrics = TraversalMetrics()
    result = {"actual_focus_before_id": row["actual_focus_before_id"],
              "actual_focus_instance_id": row["actual_focus_instance_id"],
              "reconciled_visit_instance_id": row["actual_focus_instance_id"],
              "focus_transition_status": "CONFIRMED_MOVED", "visit_record_status": "RECORDED",
              "progress_status": "PROGRESS", "physical_visit_confirmed": True,
              "actual_item": {"view_id": node["viewIdResourceName"], "bounds": node["boundsInScreen"],
                              "label": node["text"], "node": node}}
    result = collection_flow._bind_production_reconciliation(client, state, row, result)
    collection_flow.focus_reconciliation.apply_reconciliation_to_row(row, result)
    collection_flow._record_recent_representative_signature(state, row)
    assert row["production_progress_status"] == "UNKNOWN"
    assert row["visit_record_status"] == "UNAVAILABLE" and row["physical_visited"] is False
    assert state.reliability_metrics.visited == set()


def test_action_checkpoint_reconciliation_and_stop_consumer_bound_revisits(monkeypatch):
    clock, store = EvidenceClock(), NativeDispatchReceiptStore()
    client = SimpleNamespace(_adb_device=SimpleNamespace(shadow_evidence_clock=clock,
                                                         native_dispatch_receipts=store),
                             _focusable_inventory=[])
    metrics = TraversalMetrics()
    state = SimpleNamespace(production_progress_enabled=True, production_progress_scope=None,
                            production_progress_receipt=0, prev_fingerprint=("", "", ""),
                            fail_count=0, same_count=0, reliability_metrics=metrics,
                            consumed_cluster_signatures=set(), consumed_cluster_logical_signatures=set())

    def make_raw(focused, step):
        raw = _production_raw(focused=focused, request_id=f"capture-{step}")
        raw["production_observation_envelope"]["step_index"] = step
        bind_observation_marker(raw, clock.finish_observation(clock.begin_observation()))
        return raw

    def actual_row(raw, step):
        node = deepcopy(raw["focus_node"])
        return {"scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": step,
                "scenario_type": "content", "row_source": "actual_focus", "move_result": "moved",
                "actual_focus_node": node, "actual_focus_accessibility_focused": True,
                "actual_focus_resource_id": node["viewIdResourceName"],
                "actual_focus_bounds": node["boundsInScreen"], "actual_focus_visible": node["text"],
                "focus_node": deepcopy(node), "focus_view_id": node["viewIdResourceName"],
                "focus_bounds": node["boundsInScreen"], "visible_label": node["text"],
                "capture_id": raw["capture_id"], "state_graph_observation": raw,
                "_exploration_observation": raw["_exploration_observation"],
                "production_observation_envelope": raw["production_observation_envelope"],
                "production_observation_capture_status": "CURRENT", "recent_semantic_unique_count": 5}

    previous_raw = make_raw("more", 0)
    previous = actual_row(previous_raw, 0)
    metrics.visited.add(_strict_focus_id(previous_raw, SCENARIO))
    sensor = _production_raw(focused="sensor", request_id="seed-sensor")
    metrics.visited.add(_strict_focus_id(sensor, SCENARIO))
    after_box = {}

    def capture_current(*, row, **_kwargs):
        raw = after_box["raw"]
        row.update(capture_id=raw["capture_id"], state_graph_observation=raw,
                   _exploration_observation=raw["_exploration_observation"],
                   production_observation_envelope=raw["production_observation_envelope"],
                   production_observation_capture_status="CURRENT", dump_tree_nodes=raw["nodes"])
        return raw

    monkeypatch.setattr(collection_flow, "_capture_phase6d3a_production_observation", capture_current)
    for step in range(1, 6):
        checkpoint = collection_flow._production_progress_checkpoint_from_row(client, previous, step=step)
        assert checkpoint is not None
        client._production_progress_pending = checkpoint
        request = f"request-{step}"
        args = ["shell", "am", "broadcast", "-a", "com.iotpart.sqe.talkbackhelper.SMART_NEXT",
                "--es", "reqId", request]
        store.observe(args, operation_id=f"op-{step}")
        clock.dispatch(args)
        client._smart_nav_invocation_generation = client._smart_nav_result_generation = step
        client._last_smart_nav_invocation_result = {"reqId": request}
        raw = make_raw("target" if step == 5 else "sensor" if step % 2 else "more", step)
        after_box["raw"] = raw
        row = actual_row(raw, step)
        row.update(phase6_current_action_type="SMART_NEXT", smart_nav_req_id=request,
                   smart_nav_invocation_generation=step, smart_nav_result_generation=step)
        collection_flow._apply_focus_reconciliation(client=client, row=row, previous_row=previous,
                                                    state=state, progress_decision=None, visit_decision=None)
        stop, reason, _details, _ = collection_flow._apply_stop_evaluation_phase_impl(
            client=client, state=state, row=row, previous_row=previous,
            tab_cfg={"scenario_type": "content", "stop_policy": {}},
            should_stop_fn=collection_flow.should_stop, build_inputs_fn=lambda **_: {})
        assert row["production_progress_status"] == ("NEW_VISIT" if step == 5 else "NO_PROGRESS")
        assert state.same_count == (0 if step == 5 else step)
        assert stop is (step == 4)
        assert reason == ("repeat_no_progress" if step == 4 else "")
        previous = row


def test_current_actual_revisit_is_no_progress():
    assert classify(bound_operation()) == "NO_PROGRESS"


def test_current_new_actual_visit_is_progress():
    parts = bound_operation()
    parts[-1].update(visit_record_status="RECORDED", progress_status="PROGRESS")
    assert classify(parts) == "NEW_VISIT"


def test_current_semantic_transition_is_progress_even_on_revisit():
    parts = bound_operation()
    parts[1]["nodes"][1]["selected"] = False
    attach_capture_authority(parts[1], production=True, sequence=31, request_id="semantic-change", window_id=17)
    parts[1]["production_observation_envelope"]["step_index"] = 5
    bind_observation_marker(parts[1], parts[2])
    assert classify(parts) == "STATE_TRANSITION"


def test_detached_node_mutation_does_not_create_semantic_progress():
    parts = bound_operation()
    parts[1]["nodes"][1]["selected"] = False
    assert classify(parts) == "NO_PROGRESS"


def test_changed_scroll_capability_cannot_be_no_progress_or_frontier_progress():
    parts = bound_operation()
    parts[0].capture["capability"] = {"vertical_can_scroll_forward": False}
    parts[1]["capability"] = {"vertical_can_scroll_forward": True}
    assert classify(parts) == "UNKNOWN"


def test_missing_semantic_flag_is_not_inferred_from_projection_defaults():
    parts = bound_operation()
    parts[1]["nodes"][1].pop("selected")
    attach_capture_authority(parts[1], production=True, sequence=35, request_id="missing-flag", window_id=17)
    parts[1]["production_observation_envelope"]["step_index"] = 5
    bind_observation_marker(parts[1], parts[2])
    assert classify(parts) == "NO_PROGRESS"


@pytest.mark.parametrize("detail", ["reached_end", "success", "failed", "unchanged"])
def test_smart_next_result_alone_does_not_reset_progress(detail):
    parts = bound_operation(focused="more")
    parts[-1].update(last_smart_nav_result=detail, command_ack_status="SUCCESS")
    assert classify(parts) == "NO_PROGRESS"


def test_failed_target_without_focus_change_is_not_progress():
    parts = bound_operation(action="TARGET_FOCUS_COMMIT", focused="more")
    parts[-1]["target_focus_status"] = "TARGET_NOT_FOUND"
    assert classify(parts) == "NO_PROGRESS"


def test_recovery_actual_new_visit_can_prove_progress():
    parts = bound_operation(action="FOCUS_IN_BOUNDS")
    parts[-1].update(visit_record_status="RECORDED", progress_status="PROGRESS")
    _client, state, row, (stop, _, _, _) = evaluate_production(parts, same_count=4)
    assert row["production_progress_status"] == "NEW_VISIT"
    assert not stop and state.same_count == 0


@pytest.mark.parametrize("status", ["UNKNOWN", "NO_PROGRESS", None])
def test_unchanged_or_unverified_recovery_cannot_suppress_repeat_stop(status):
    assert collection_flow._resolve_recovery_stop(
        guarded=True, prior_reason="repeat_no_progress", stop=False, reason="",
        recovered=True, block_stop=True, progress_status=status) == (True, "repeat_no_progress")


def test_current_recovery_progress_can_continue():
    assert collection_flow._resolve_recovery_stop(
        guarded=True, prior_reason="repeat_no_progress", stop=False, reason="",
        recovered=True, block_stop=True, progress_status="NEW_VISIT") == (False, "")


def test_recovery_dispatch_with_unknown_outcome_does_not_reuse_stale_stop_proof():
    assert collection_flow._resolve_recovery_stop(
        guarded=True, prior_reason="repeat_no_progress", stop=False, reason="",
        recovered=True, block_stop=True, progress_status="UNKNOWN", dispatched=True) == (
            True, "production_progress_unverified")
    assert collection_flow._resolve_recovery_stop(
        guarded=True, prior_reason="repeat_no_progress", stop=False, reason="",
        recovered=True, block_stop=True, progress_status="NO_PROGRESS", dispatched=True) == (
            True, "repeat_no_progress")


def test_unverified_secondary_action_cannot_suppress_or_complete_repeat_stop():
    clock = EvidenceClock()
    marker = clock.finish_observation(clock.begin_observation())
    assert collection_flow._guard_secondary_progress_stop(
        guarded=True, marker=marker, clock=clock, stop=False, reason="") == (True, "repeat_no_progress")
    clock.dispatch(["shell", "input", "tap", "1", "1"])
    assert collection_flow._guard_secondary_progress_stop(
        guarded=True, marker=marker, clock=clock, stop=False, reason="") == (True, "production_progress_unverified")
    assert collection_flow._guard_secondary_progress_stop(
        guarded=True, marker=marker, clock=clock, stop=True, reason="scroll_exhausted") == (True, "production_progress_unverified")
    assert collection_flow._guard_secondary_progress_stop(
        guarded=False, marker=marker, clock=clock, stop=False, reason="") == (False, "")


def bound_scroll(owner_count=1):
    clock, store = EvidenceClock(), NativeDispatchReceiptStore()
    before = _production_raw(focused="more", request_id="scroll-before")
    before["production_observation_envelope"]["step_index"] = 5
    containers = [{"path": f"0.0.{4 + index}", "stable_node_path": f"0.0.{4 + index}",
                   "scrollable": True, "className": "android.widget.ScrollView",
                   "visibleToUser": True, "boundsInScreen": "[0,0][1080,2400]"}
                  for index in range(owner_count)]
    before["nodes"].extend(deepcopy(containers))
    attach_capture_authority(before, production=True, sequence=32, request_id="scroll-before-sealed", window_id=17)
    before["production_observation_envelope"]["step_index"] = 5
    before["capability"] = {
        "status": "SCROLL_CAPABLE", "source": "helper_metadata",
        "can_scroll_forward": True, "vertical_can_scroll_forward": True,
        "axis": ("VERTICAL" if owner_count == 1 else "UNKNOWN"),
        "container": containers[0] if owner_count == 1 else None,
        "containers": containers if owner_count else [],
        "contradictory": False,
    }
    marker = clock.finish_observation(clock.begin_observation())
    bind_observation_marker(before, marker)
    checkpoint = capture_checkpoint(before, marker, clock=clock, receipt_store=store,
                                    scenario_id=SCENARIO, run_id=RUN_ID, step=5)
    assert checkpoint is not None
    args = ["shell", "am", "broadcast", "-a",
            "com.iotpart.sqe.talkbackhelper.SCROLL", "--es", "reqId", "scroll-1"]
    store.observe(args, operation_id="scroll-operation")
    clock.dispatch(args)
    after = _production_raw(focused="more", request_id="scroll-after")
    after["nodes"][0]["boundsInScreen"] = "[100,464][900,664]"
    after["nodes"].extend(deepcopy(containers))
    attach_capture_authority(after, production=True, sequence=33, request_id="scroll-after-sealed", window_id=17)
    after["production_observation_envelope"]["step_index"] = 5
    marker = clock.finish_observation(clock.begin_observation())
    bind_observation_marker(after, marker)
    target = {"mode": "EXPLICIT_CONTAINER", "container_path": "0.0.4",
              "container_bounds": "[0,0][1080,2400]"}
    transition = dict(scenario_id=SCENARIO, step_index=5, action_type="SCROLL_FORWARD",
                      direction="down", action_target=target, action_request_id="scroll-1",
                      action_result_request_id="scroll-1", action_result_correlated=True,
                      action_success=True, action_result={"reqId": "scroll-1", "success": True,
                                                         "action": "SCROLL_FORWARD", "actionAttempted": True,
                                                         "explicitTarget": True, "scrollContainerPath": "0.0.4"})
    if owner_count == 1:
        owner = {"status": "RESOLVED", "identity": "owner-0.0.4",
                 "path": "0.0.4", "bounds": "[0,0][1080,2400]"}
    else:
        owner = {"status": "OWNER_NOT_IN_CURRENT_HIERARCHY" if owner_count == 0 else "OWNER_AMBIGUOUS",
                 "identity": None, "path": None, "bounds": None}
    return checkpoint, after, marker, clock, store, transition, owner


def scroll_classification(parts):
    checkpoint, after, marker, clock, store, transition, owner = parts
    return classify_scroll_progress(checkpoint, after, marker, clock=clock, receipt_store=store,
                                    transition=transition, owner=owner)


def test_current_owner_bound_scroll_change_is_progress():
    assert scroll_classification(bound_scroll()) == "SCROLL_CHANGE"


def test_unique_current_fallback_scroll_can_prove_change():
    parts = bound_scroll()
    parts[0].capture["capability"]["container"] = None
    parts[-2]["action_target"] = {"mode": "ACCESSIBILITY_FALLBACK"}
    parts[-2]["action_result"].update(explicitTarget=False, scrollContainerPath=None,
                                       scrollableNodeFound=True,
                                       fallbackToTreeSearchScrollable=True,
                                       scrollContainerClass="android.widget.ScrollView")
    assert scroll_classification(parts) == "SCROLL_CHANGE"


@pytest.mark.parametrize("owner_status", ["UNRESOLVED", "OWNER_AMBIGUOUS", "SOURCE_CAPTURE_STALE"])
def test_moved_fallback_without_current_resolved_owner_is_unknown(owner_status):
    parts = bound_scroll(owner_count={"UNRESOLVED": 0, "OWNER_AMBIGUOUS": 2,
                                     "SOURCE_CAPTURE_STALE": 1}[owner_status])
    if owner_status == "SOURCE_CAPTURE_STALE":
        parts[3].begin_observation()
    parts[-2]["action_target"] = {"mode": "ACCESSIBILITY_FALLBACK",
                                  "container_path": None, "container_bounds": None}
    parts[-2]["action_result"].update(
        explicitTarget=False, scrollContainerPath=None, scrollableNodeFound=True,
        fallbackToTreeSearchScrollable=True, scrollContainerClass="android.widget.ScrollView")
    if owner_status == "UNRESOLVED":
        assert parts[0].capture["capability"]["container"] is None
        assert parts[0].capture["capability"]["axis"] == "UNKNOWN"
        assert parts[0].capture["capability"]["containers"] == []
        assert parts[-1]["status"] == "OWNER_NOT_IN_CURRENT_HIERARCHY"
    elif owner_status == "OWNER_AMBIGUOUS":
        assert parts[-1]["status"] == "OWNER_AMBIGUOUS"
    else:
        assert parts[-1]["status"] == "RESOLVED"
        assert not parts[3].current(dict(parts[2]))

    assert parts[-2]["action_success"] is True
    assert parts[-2]["action_result"]["success"] is True
    assert scroll_classification(parts) == "UNKNOWN"


def test_fallback_movement_without_helper_authority_is_unknown():
    parts = bound_scroll()
    parts[0].capture["capability"]["container"] = None
    parts[-2]["action_target"] = {"mode": "ACCESSIBILITY_FALLBACK"}
    parts[-2]["action_result"].update(explicitTarget=False, scrollContainerPath=None,
                                       scrollableNodeFound=True,
                                       scrollContainerClass="android.widget.ScrollView")

    assert scroll_classification(parts) == "UNKNOWN"


def test_post_scroll_source_uses_current_snapshot_focus_for_next_action(monkeypatch):
    checkpoint, raw, marker, clock, store, transition, owner = bound_scroll()
    capture_row = {"scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": 5,
                   "capture_id": raw["capture_id"], "state_graph_observation": raw,
                   "_exploration_observation": marker,
                   "production_observation_envelope": raw["production_observation_envelope"],
                   "production_observation_capture_status": "CURRENT",
                   "actual_focus_resource_id": "stale-pre-scroll"}
    source = collection_flow._production_post_scroll_source(capture_row, raw)
    assert source["actual_focus_resource_id"] == raw["focus_node"]["viewIdResourceName"]
    assert source["actual_focus_resource_id"] != "stale-pre-scroll"
    client = SimpleNamespace(_adb_device=SimpleNamespace(shadow_evidence_clock=clock,
                                                         native_dispatch_receipts=store))
    next_checkpoint = collection_flow._production_progress_checkpoint_from_row(client, source, step=6)
    assert next_checkpoint is not None and next_checkpoint.capture["capture_id"] == raw["capture_id"]
    request = "after-scroll-next"
    command = ["shell", "am", "broadcast", "-a", "com.iotpart.sqe.talkbackhelper.SMART_NEXT",
               "--es", "reqId", request]
    store.observe(command, operation_id="after-scroll-operation")
    clock.dispatch(command)
    client._production_progress_pending = next_checkpoint
    client._smart_nav_invocation_generation = client._smart_nav_result_generation = 1
    client._last_smart_nav_invocation_result = {"reqId": request}
    client._focusable_inventory = []
    after_next = _production_raw(focused="sensor", request_id="after-scroll-next-capture")
    after_next["production_observation_envelope"]["step_index"] = 6
    bind_observation_marker(after_next, clock.finish_observation(clock.begin_observation()))
    node = deepcopy(after_next["focus_node"])
    row = {"scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": 6,
           "scenario_type": "content", "move_result": "moved", "row_source": "actual_focus",
           "phase6_current_action_type": "SMART_NEXT", "smart_nav_req_id": request,
           "smart_nav_invocation_generation": 1, "smart_nav_result_generation": 1,
           "actual_focus_node": node, "actual_focus_accessibility_focused": True,
           "actual_focus_resource_id": node["viewIdResourceName"],
           "actual_focus_bounds": node["boundsInScreen"], "actual_focus_visible": node["text"],
           "focus_node": deepcopy(node), "focus_view_id": node["viewIdResourceName"],
           "focus_bounds": node["boundsInScreen"], "visible_label": node["text"]}

    def capture_current(*, row, **_kwargs):
        row.update(capture_id=after_next["capture_id"], state_graph_observation=after_next,
                   _exploration_observation=after_next["_exploration_observation"],
                   production_observation_envelope=after_next["production_observation_envelope"],
                   production_observation_capture_status="CURRENT", dump_tree_nodes=after_next["nodes"])
        return after_next

    monkeypatch.setattr(collection_flow, "_capture_phase6d3a_production_observation", capture_current)
    state = collection_flow._build_main_loop_state_from_anchor(
        {}, anchor_fingerprint="", anchor_repeat_count=0, step_index=0)
    state.reliability_metrics = TraversalMetrics()
    state.reliability_metrics.visited.add(_strict_focus_id(raw, SCENARIO))
    collection_flow._apply_focus_reconciliation(client=client, row=row, previous_row=source,
                                                state=state, progress_decision=None, visit_decision=None)
    collection_flow._record_recent_representative_signature(state, row)
    assert row["production_progress_status"] == "NEW_VISIT"
    assert row["actual_focus_before_id"] == _strict_focus_id(raw, SCENARIO)
    assert row["visit_record_status"] == "RECORDED" and row["physical_visited"] is True
    assert row["actual_focus_instance_id"] in state.reliability_metrics.visited
    assert collection_flow._production_progress_checkpoint_from_row(client, source, step=6) is None


def test_post_scroll_without_strict_focus_cannot_reuse_older_focus():
    parts = bound_scroll()
    parts[1]["focus_node"] = {}
    assert collection_flow._production_post_scroll_source({"scenario_id": SCENARIO}, parts[1]) is None


@pytest.mark.parametrize("outcome", ["no_op", "boundary", "failed"])
def test_scroll_no_change_never_is_progress(outcome):
    parts = bound_scroll()
    parts[1]["nodes"][0]["boundsInScreen"] = "[100,400][900,600]"
    attach_capture_authority(parts[1], production=True, sequence=34, request_id="scroll-noop", window_id=17)
    parts[1]["production_observation_envelope"]["step_index"] = 5
    bind_observation_marker(parts[1], parts[2])
    if outcome == "failed":
        parts[-2]["action_success"] = False
        parts[-2]["action_result"]["success"] = False
    if outcome == "boundary":
        parts[-2]["viewport_end"] = True
    assert scroll_classification(parts) == "NO_PROGRESS"


@pytest.mark.parametrize("mutation", ["owner", "request", "capture", "receipt", "inconsistent_result"])
def test_unbound_scroll_is_unknown(mutation):
    parts = bound_scroll()
    if mutation == "owner":
        parts[-1]["path"] = "other"
    elif mutation == "request":
        parts[-2]["action_result_request_id"] = "other"
    elif mutation == "capture":
        parts[1]["geometry_capture_id"] = "other"
    elif mutation == "receipt":
        parts[4].receipts.clear()
    elif mutation == "inconsistent_result":
        parts[-2]["action_result"]["success"] = False
    assert scroll_classification(parts) == "UNKNOWN"


@pytest.mark.parametrize("mutation", [
    "stale_clock", "wrong_request", "wrong_run", "wrong_step", "wrong_focus",
    "ambiguous_focus", "missing_receipt", "borrowed_capture", "extra_action",
    "mismatched_visit", "missing_operation", "different_store_generation",
    "wrong_invocation", "wrong_action", "multiple_focus_nodes", "wrong_root",
    "borrowed_geometry", "wrong_clock_receipt", "incomplete_capture", "wrong_focus_class", "partial_tree",
    "mutated_sealed_root",
])
def test_unproven_operation_cannot_produce_progress(mutation):
    parts = bound_operation()
    checkpoint, after, marker, clock, store, row = parts
    row.update(visit_record_status="RECORDED", progress_status="PROGRESS")
    request = "request-1"
    if mutation == "stale_clock":
        clock.begin_observation()
    elif mutation == "wrong_request":
        request = "borrowed-request"
    elif mutation == "wrong_run":
        row["scenario_run_id"] = "other"
    elif mutation == "wrong_step":
        row["step_index"] = 6
    elif mutation == "wrong_focus":
        row["actual_focus_instance_id"] = "other"
    elif mutation == "ambiguous_focus":
        row["focus_transition_status"] = "AMBIGUOUS"
    elif mutation == "missing_receipt":
        store.receipts.clear()
    elif mutation == "borrowed_capture":
        after["focus_capture_id"] = "other"
    elif mutation == "extra_action":
        store.observe(["shell", "input", "keyevent", "4"], operation_id="other")
    elif mutation == "mismatched_visit":
        row["reconciled_visit_instance_id"] = "other"
    elif mutation == "missing_operation":
        store.receipts[0]["operation_id"] = None
    elif mutation == "different_store_generation":
        store.reset()
    elif mutation == "wrong_invocation":
        row["smart_nav_result_generation"] = 2
    elif mutation == "wrong_action":
        row["phase6_current_action_type"] = "TARGETED_FOCUS"
    elif mutation == "multiple_focus_nodes":
        after["nodes"][-1]["accessibilityFocused"] = True
    elif mutation == "wrong_root":
        after["traversal_root_ref"] = "other-root"
    elif mutation == "borrowed_geometry":
        after["geometry_capture_id"] = "other"
    elif mutation == "wrong_clock_receipt":
        marker["action_ownership"]["request_id"] = "other"
    elif mutation == "incomplete_capture":
        after["production_observation_envelope"]["capture_complete"] = False
    elif mutation == "wrong_focus_class":
        after["focus_node"]["className"] = "Other"
    elif mutation == "partial_tree":
        after["hierarchy_complete"] = False
    elif mutation == "mutated_sealed_root":
        after["_capture_root_tree"]["children"][0]["selected"] = True
    assert classify(parts, request) == "UNKNOWN"
