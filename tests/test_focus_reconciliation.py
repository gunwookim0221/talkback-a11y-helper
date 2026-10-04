from tb_runner.focus_reconciliation import apply_reconciliation_to_row, has_strict_post_move_focus, reconcile_focus
from tb_runner.traversal_reliability import instance_id
from tb_runner import collection_flow as flow
from tb_runner.traversal_reliability import TraversalMetrics
from collections import deque
from types import SimpleNamespace


def candidate(rid, label, bounds, **extra):
    return {
        "scenario_id": "devices_main",
        "rid": rid,
        "label": label,
        "bounds": bounds,
        "class_name": extra.get("class_name", "android.widget.Button"),
        "node": {
            "viewIdResourceName": rid,
            "text": label,
            "boundsInScreen": bounds,
            "className": extra.get("class_name", "android.widget.Button"),
            **extra.get("node", {}),
        },
        **{k: v for k, v in extra.items() if k not in {"class_name", "node"}},
    }


def row(rid, label, bounds, *, selected=None, **extra):
    selected = selected or candidate(rid, label, bounds)
    return {
        "scenario_id": "devices_main",
        "scenario_type": "content",
        "step_index": 2,
        "row_source": "representative",
        "focus_view_id": selected["rid"],
        "focus_bounds": selected["bounds"],
        "visible_label": selected["label"],
        "merged_announcement": selected["label"],
        "focus_class_name": selected.get("class_name", ""),
        "focus_node": selected["node"],
        "actual_focus_resource_id": rid,
        "actual_focus_visible": label,
        "actual_focus_speech": label,
        "actual_focus_bounds": bounds,
        "actual_focus_accessibility_focused": True,
        "actual_focus_input_focused": False,
        "actual_focus_class_name": "android.widget.Button",
        "actual_focus_node": {
            "viewIdResourceName": rid,
            "text": label,
            "boundsInScreen": bounds,
            "className": "android.widget.Button",
            "accessibilityFocused": True,
        },
        "move_result": "moved",
        **extra,
    }


def reconcile(current, previous=None, inventory=(), expected=None, *, confirmed=True, consumed=()):
    return reconcile_focus(
        row=current,
        previous_row=previous,
        scenario_id="devices_main",
        inventory=inventory,
        expected_candidates=expected if expected is not None else inventory,
        physical_visit_confirmed=confirmed,
        planning_consumed=True,
        visited_instance_ids_before=(),
        consumed_cluster_signatures=consumed,
    )


def test_selected_a_actual_a_maps_exact_and_is_consumed():
    a = candidate("id.a", "A", "0,0,100,100")
    current = row("id.a", "A", "0,0,100,100", selected=a)
    result = reconcile(current, inventory=[a])
    assert result["mapping_confidence"] == "EXACT"
    assert result["selected_candidate_consumed"] is True
    assert result["classification"] == "ALIGNED"


def test_selected_a_actual_b_strong_match_maps_b():
    b = candidate("id.b", "B", "0,100,100,200")
    current = row("", "B", "0,100,100,200", selected=candidate("id.a", "A", "0,0,100,100"))
    result = reconcile(current, inventory=[b])
    assert result["mapping_confidence"] == "STRONG"
    assert result["mapped_candidate_instance_id"] == instance_id({
        "scenario_id": "devices_main", "view_id": "id.b", "bounds": "0,100,100,200", "label": "B"
    })
    assert result["selected_candidate_consumed"] is False
    assert result["classification"] == "RECONCILED"


def test_ambiguous_combined_mapping_does_not_choose_a_candidate():
    first = candidate("id.one", "Same", "0,0,100,100")
    second = candidate("id.two", "Same", "0,0,100,100")
    current = row("", "Same", "0,0,100,100", selected=candidate("id.a", "A", "0,200,100,300"))
    result = reconcile(current, inventory=[first, second])
    assert result["mapping_confidence"] == "AMBIGUOUS"
    assert result["physical_visit_confirmed"] is False
    assert result["visit_record_status"] == "NOT_RECORDED_AMBIGUOUS"
    assert result["mapped_candidate_instance_id"] == ""
    assert result["candidate_in_expected_population"] is False
    assert result["selected_candidate_consumed"] is False


def test_focus_outside_inventory_is_unexpected_and_keeps_actual_identity():
    current = row("id.unseen", "New", "0,300,100,400", selected=candidate("id.a", "A", "0,0,100,100"))
    result = reconcile(current, inventory=[])
    assert result["mapping_confidence"] == "UNMATCHED"
    assert result["classification"] == "UNEXPECTED_ACTUAL_FOCUS"
    assert result["reconciled_visit_instance_id"] == result["actual_focus_instance_id"]
    assert result["candidate_in_expected_population"] is False


def test_known_inventory_focus_outside_body_population_maps_but_stays_unexpected():
    a = candidate("id.a", "A", "0,0,100,100")
    chrome = {
        "scenario_id": "devices_main",
        "view_id": "id.chrome",
        "label": "Search",
        "bounds": "0,300,100,400",
        "class_name": "android.widget.ImageView",
    }
    current = row("id.chrome", "Search", "0,300,100,400", selected=a)
    result = reconcile(current, inventory=[a, chrome], expected=[a])
    assert result["mapping_confidence"] == "EXACT"
    assert result["candidate_in_expected_population"] is False
    assert result["classification"] == "UNEXPECTED_ACTUAL_FOCUS"


def test_same_resource_sibling_maps_by_instance_bounds():
    first = candidate("id.shared", "First", "0,0,100,100")
    second = candidate("id.shared", "Second", "0,100,100,200")
    current = row("id.shared", "Second", "0,100,100,200", selected=first)
    result = reconcile(current, inventory=[first, second])
    assert result["mapping_confidence"] == "EXACT"
    assert result["mapped_candidate_instance_id"] == instance_id({
        "scenario_id": "devices_main", "view_id": "id.shared", "bounds": "0,100,100,200", "label": "Second"
    })


def test_repeated_selection_with_actual_focus_move_counts_as_sequence_progress():
    a = candidate("id.a", "A", "0,0,100,100")
    b = candidate("id.b", "B", "0,100,100,200")
    current = row("id.b", "B", "0,100,100,200", selected=a)
    previous = row("id.a", "A", "0,0,100,100", selected=a)
    result = reconcile(current, previous, inventory=[a, b])
    assert result["selection_candidate_instance_id"] == result["actual_focus_before_id"]
    assert result["focus_sequence_changed"] is True
    assert result["reconciliation_progress"] is True
    assert result["focus_transition_status"] == "CONFIRMED_MOVED"
    assert result["cases"] == ["CASE_D_SELECTION_ORDER_MISMATCH"]


def test_selection_change_while_actual_focus_stays_same_is_not_sequence_progress():
    a = candidate("id.a", "A", "0,0,100,100")
    b = candidate("id.b", "B", "0,100,100,200")
    current = row("id.a", "A", "0,0,100,100", selected=b)
    previous = row("id.a", "A", "0,0,100,100", selected=a)
    result = reconcile(current, previous, inventory=[a, b])
    assert result["focus_sequence_changed"] is False
    assert result["focus_transition_status"] == "CONFIRMED_UNCHANGED"
    assert "CASE_A_SMART_NEXT_SAME_FOCUS" in result["cases"]
    assert "CASE_D_SELECTION_ORDER_MISMATCH" in result["cases"]


def test_actual_b_to_c_is_not_duplicate_and_repeated_actual_focus_is():
    b = candidate("id.b", "B", "0,100,100,200")
    c = candidate("id.c", "C", "0,200,100,300")
    prior_b = row("id.b", "B", "0,100,100,200", selected=b)
    actual_c = row("id.c", "C", "0,200,100,300", selected=b)
    moved = reconcile(actual_c, prior_b, inventory=[b, c])
    repeated = reconcile(row("id.b", "B", "0,100,100,200", selected=c), prior_b, inventory=[b, c])
    assert moved["focus_sequence_changed"] is True
    assert repeated["focus_sequence_changed"] is False


def test_case_b_detects_raw_identity_change_collapsed_to_same_phase0a_id():
    prior = row("id.same", "A", "0,0,100,100")
    prior["actual_focus_container_id"] = "container.one"
    current = row("id.same", "A", "0,0,100,100")
    current["actual_focus_container_id"] = "container.two"
    result = reconcile(current, prior, inventory=[])
    assert result["actual_focus_instance_id"] == result["actual_focus_before_id"]
    assert "CASE_B_IDENTITY_COLLAPSE" in result["cases"]


def test_case_c_reports_new_instance_in_already_consumed_semantic_cluster():
    b = candidate("id.b", "B", "0,100,100,200", cluster_signature="cluster.1")
    c = candidate("id.c", "C", "0,200,100,300", cluster_signature="cluster.1")
    result = reconcile(
        row("id.c", "C", "0,200,100,300", selected=b),
        row("id.b", "B", "0,100,100,200", selected=b),
        inventory=[b, c], consumed={"cluster.1"},
    )
    assert "CASE_C_SEMANTIC_CLUSTER_ALREADY_CONSUMED" in result["cases"]


def test_confirmation_false_does_not_grant_visit_or_rewrite_selected_context():
    a = candidate("id.a", "A", "0,0,100,100")
    current = row("id.b", "B", "0,100,100,200", selected=a)
    result = reconcile(current, inventory=[a], confirmed=False)
    apply_reconciliation_to_row(current, result)
    assert result["reconciled_visit_instance_id"] == ""
    assert current["focus_view_id"] == "id.a"
    assert current["focus_reconciliation_applied"] is False


def test_confirmed_mismatch_visits_b_not_a_and_updates_next_context():
    a = candidate("id.a", "A", "0,0,100,100", semantic_card_id="semantic.a")
    b = candidate("id.b", "B", "0,100,100,200", semantic_card_id="semantic.b")
    current = row("id.b", "B", "0,100,100,200", selected=a, semantic_card_id="semantic.a")
    result = reconcile(current, inventory=[a, b])
    apply_reconciliation_to_row(current, result)
    assert current["focus_view_id"] == "id.b"
    assert current["reconciled_visit_instance_id"] == instance_id({
        "scenario_id": "devices_main", "view_id": "id.b", "bounds": "0,100,100,200", "label": "B"
    })
    assert current["selected_candidate_consumed"] is False
    assert current["selected_candidate_state"] == "selected_but_not_focused"
    assert current["selection_candidate_semantic_card_id"] == "semantic.a"
    assert current["semantic_card_id"] == "semantic.b"
    next_result = reconcile(row("id.c", "C", "0,200,100,300"), current, inventory=[])
    assert next_result["actual_focus_before_id"] == current["actual_focus_instance_id"]


def test_actual_focus_without_accessibility_focused_flag_is_not_promoted():
    a = candidate("id.a", "A", "0,0,100,100")
    current = row("id.a", "A", "0,0,100,100", selected=a)
    current["actual_focus_accessibility_focused"] = False
    result = reconcile(current, inventory=[a])
    assert result["classification"] == "NO_STRICT_ACTUAL_FOCUS"
    assert result["reconciled_visit_instance_id"] == ""


def test_coherent_actual_node_supplies_missing_top_level_a11y_focus_flag():
    a = candidate("id.a", "A", "0,0,100,100")
    current = row("id.a", "A", "0,0,100,100", selected=a)
    current["actual_focus_accessibility_focused"] = None
    result = reconcile(current, inventory=[a])
    assert result["physical_visit_confirmed"] is True
    assert result["reconciled_visit_instance_id"] == result["actual_focus_instance_id"]


def test_strict_post_move_focus_blocks_expected_candidate_realign():
    assert has_strict_post_move_focus({"actual_focus_accessibility_focused": True}, "moved") is True
    assert has_strict_post_move_focus({"focus_node": {"accessibilityFocused": True}}, "moved") is True
    assert has_strict_post_move_focus({"actual_focus_accessibility_focused": True}, "failed") is False
    assert has_strict_post_move_focus({"actual_focus_accessibility_focused": False}, "moved") is False


def test_collection_flow_applies_confirmed_actual_context_and_emits_structured_log(monkeypatch):
    a = candidate("id.a", "A", "0,0,100,100")
    b = candidate("id.b", "B", "0,100,100,200")
    current = row("id.b", "B", "0,100,100,200", selected=a)
    previous = row("id.prev", "Previous", "0,200,100,300")
    current["dump_tree_nodes"] = [a["node"], b["node"]]
    state = SimpleNamespace(
        reliability_metrics=TraversalMetrics(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
    )
    monkeypatch.setattr(flow, "_collect_step_candidate_priority_groups", lambda *_a, **_k: ([a, b], [], {}))
    logs = []
    monkeypatch.setattr(flow, "log", logs.append)
    result = flow._apply_focus_reconciliation(
        client=SimpleNamespace(),
        row=current,
        previous_row=previous,
        state=state,
        progress_decision=None,
        visit_decision=None,
    )
    assert result["classification"] == "RECONCILED"
    assert current["focus_view_id"] == "id.b"
    assert current["actual_focus_before_id"] == instance_id({
        "scenario_id": "devices_main", "view_id": "id.prev", "bounds": "0,200,100,300", "label": "Previous"
    })
    assert any("[FOCUS_RECONCILIATION]" in entry and "selected_consumed=false" in entry for entry in logs)


def test_failed_ack_with_confirmed_actual_move_records_new_actual_visit(monkeypatch):
    a = candidate("id.a", "A", "0,0,100,100")
    b = candidate("id.b", "B", "0,100,100,200")
    previous = row("id.a", "A", "0,0,100,100", selected=a)
    current = row("id.b", "B", "0,100,100,200", selected=a,
                  move_result={"success": False, "status": "failed_single_target"},
                  last_smart_nav_result="failed_single_target", smart_nav_success=False)
    current["dump_tree_nodes"] = [a["node"], b["node"]]
    metrics = TraversalMetrics()
    metrics.observe_focus(previous)
    state = SimpleNamespace(reliability_metrics=metrics, consumed_cluster_signatures=set(),
                            consumed_cluster_logical_signatures=set(),
                            recent_representative_signatures=deque(), consumed_representative_signatures=set(),
                            visited_logical_signatures=set(), consumed_semantic_card_signatures=set())
    monkeypatch.setattr(flow, "_collect_step_candidate_priority_groups", lambda *_a, **_k: ([a, b], [], {}))

    result = flow._apply_focus_reconciliation(
        client=SimpleNamespace(), row=current, previous_row=previous, state=state,
        progress_decision=None, visit_decision=None,
    )
    flow._record_recent_representative_signature(state, current)

    assert result["focus_transition_status"] == "CONFIRMED_MOVED"
    assert current["command_ack_status"] == "FAIL"
    assert current["command_ack_result"] == "failed_single_target"
    assert current["visit_record_status"] == "RECORDED"
    assert current["progress_status"] == "PROGRESS"
    assert current["reconciled_visit_instance_id"] == current["actual_focus_instance_id"]
    assert current["focus_view_id"] == "id.b"
    assert current["physical_visited"] is True
    assert instance_id({"scenario_id": "devices_main", "view_id": "id.b", "bounds": "0,100,100,200"}) in metrics.visited
    assert metrics.ack_failed_focus_moved_steps == 1
    assert metrics.reconciled_new_visits == 1
    assert '"progress":true' in current["move_outcome_evidence"]


def test_ack_success_with_unchanged_actual_focus_cannot_force_visit_or_progress(monkeypatch):
    a = candidate("id.a", "A", "0,0,100,100")
    b = candidate("id.b", "B", "0,100,100,200")
    previous = row("id.a", "A", "0,0,100,100", selected=a)
    current = row("id.a", "A", "0,0,100,100", selected=b,
                  move_result={"success": True, "status": "moved"},
                  last_smart_nav_result="moved", smart_nav_success=True)
    current["dump_tree_nodes"] = [a["node"], b["node"]]
    metrics = TraversalMetrics()
    metrics.observe_focus(previous)
    state = SimpleNamespace(reliability_metrics=metrics, consumed_cluster_signatures=set(),
                            consumed_cluster_logical_signatures=set(),
                            recent_representative_signatures=deque(), consumed_representative_signatures=set(),
                            visited_logical_signatures=set(), consumed_semantic_card_signatures=set())
    monkeypatch.setattr(flow, "_collect_step_candidate_priority_groups", lambda *_a, **_k: ([a, b], [], {}))
    progress_gate = SimpleNamespace(gate_applied=True, physical_progress=True)
    visit_gate = SimpleNamespace(visited=True, consumed=True)

    result = flow._apply_focus_reconciliation(
        client=SimpleNamespace(), row=current, previous_row=previous, state=state,
        progress_decision=progress_gate, visit_decision=visit_gate,
    )
    flow._record_recent_representative_signature(
        state, current, progress_decision=progress_gate, visit_decision=visit_gate,
    )

    assert result["focus_transition_status"] == "CONFIRMED_UNCHANGED"
    assert current["command_ack_status"] == "SUCCESS"
    assert current["visit_record_status"] == "ALREADY_VISITED"
    assert current["progress_status"] == "NO_PROGRESS_UNCHANGED"
    assert current["reconciled_visit_instance_id"] == ""
    assert current["physical_visited"] is False
    assert metrics.summary([], "safety_limit")["unique_visited_instances"] == 1


def test_conflicting_actual_focus_flags_are_ambiguous_and_not_visited():
    a = candidate("id.a", "A", "0,0,100,100")
    previous = row("id.a", "A", "0,0,100,100", selected=a)
    current = row("id.b", "B", "0,100,100,200", selected=a)
    current["actual_focus_node"]["accessibilityFocused"] = False
    result = reconcile(current, previous, inventory=[a], confirmed=True)
    assert result["focus_transition_status"] == "AMBIGUOUS"
    assert result["physical_visit_confirmed"] is False
    assert result["visit_record_status"] == "NOT_RECORDED_AMBIGUOUS"
    assert result["progress_status"] == "NO_PROGRESS_AMBIGUOUS"


def test_unavailable_focus_still_serializes_the_command_ack():
    current = row("id.b", "B", "0,100,100,200",
                  move_result={"success": False, "status": "failed_single_target"},
                  last_smart_nav_result="failed_single_target", smart_nav_success=False)
    current["row_source"] = "actual_focus"
    current["actual_focus_accessibility_focused"] = False
    current["actual_focus_input_focused"] = False
    current["actual_focus_node"]["accessibilityFocused"] = False
    current["focus_node"]["accessibilityFocused"] = False
    state = SimpleNamespace(reliability_metrics=TraversalMetrics(), consumed_cluster_signatures=set())
    result = flow._apply_focus_reconciliation(
        client=SimpleNamespace(), row=current, previous_row=None, state=state,
        progress_decision=None, visit_decision=None,
    )
    assert result["focus_transition_status"] == "UNAVAILABLE"
    assert current["command_ack_status"] == "FAIL"
    assert current["visit_record_status"] == "UNAVAILABLE"
    assert '"command_ack_status":"FAIL"' in current["move_outcome_evidence"]


def test_unmatched_actual_instance_still_records_visit_separately_from_expected_coverage():
    expected = candidate("id.expected", "Expected", "0,0,100,100")
    previous = row("id.before", "Before", "0,200,100,300")
    current = row("id.unexpected", "Unexpected", "0,300,100,400", selected=expected)
    result = reconcile(current, previous, inventory=[expected], expected=[expected], confirmed=False)
    assert result["focus_transition_status"] == "CONFIRMED_MOVED"
    assert result["candidate_in_expected_population"] is False
    assert result["classification"] == "UNEXPECTED_ACTUAL_FOCUS"
    assert result["visit_record_status"] == "RECORDED"
    assert result["progress_status"] == "PROGRESS"


def test_stop_evaluation_uses_new_actual_focus_sequence_even_when_ack_fails():
    state = SimpleNamespace(prev_fingerprint=("A", "id.a", "0,0,100,100"), fail_count=0, same_count=4)
    tab_cfg = {"scenario_type": "content", "stop_policy": {}}
    outcomes = []
    for step, rid, bounds, label in (
        (1, "id.b", "0,100,100,200", "B"),
        (2, "id.c", "0,200,100,300", "C"),
    ):
        row_data = {
            "step_index": step,
            "move_result": {"success": False, "status": "failed_single_target"},
            "last_smart_nav_result": "failed_single_target",
            "command_ack_status": "FAIL",
            "focus_transition_status": "CONFIRMED_MOVED",
            "progress_status": "PROGRESS",
            "visible_label": label,
            "merged_announcement": label,
            "normalized_visible_label": label,
            "normalized_announcement": label,
            "focus_view_id": rid,
            "focus_bounds": bounds,
        }
        stop, reason, details, _inputs = flow._apply_stop_evaluation_phase_impl(
            row=row_data, state=state, previous_row=None, tab_cfg=tab_cfg,
            progress_decision=None, should_stop_fn=flow.should_stop,
            build_inputs_fn=lambda **kwargs: {},
        )
        outcomes.append((stop, reason, state.fail_count, state.same_count, details))
    assert all(stop is False for stop, *_ in outcomes)
    assert all(reason == "" for _, reason, *_ in outcomes)
    assert all(fail_count == 0 and same_count == 0 for _, _, fail_count, same_count, _ in outcomes)


def test_collection_flow_uses_fresh_viewport_dump_when_step_dump_is_absent(monkeypatch):
    a = candidate("id.a", "A", "0,0,100,100")
    b = candidate("id.b", "B", "0,100,100,200")
    current = row("id.b", "B", "0,100,100,200", selected=a)
    current["dump_tree_nodes"] = []
    observed_nodes = []
    client = SimpleNamespace(
        dump_tree=lambda **kwargs: observed_nodes.extend([a["node"], b["node"]]) or [a["node"], b["node"]],
        _focusable_inventory=[],
    )
    state = SimpleNamespace(
        reliability_metrics=TraversalMetrics(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
    )
    monkeypatch.setattr(flow, "_collect_step_candidate_priority_groups", lambda nodes, **_k: ([a, b], [], {}))
    result = flow._apply_focus_reconciliation(
        client=client,
        dev="serial",
        row=current,
        previous_row=None,
        state=state,
        progress_decision=None,
        visit_decision=None,
    )
    assert observed_nodes == [a["node"], b["node"]]
    assert current["focus_reconciliation_evidence"]
    assert result["mapped_candidate_instance_id"] == result["actual_focus_instance_id"]


def test_collection_flow_keeps_menu_ack_failed_actual_focus_as_visit(monkeypatch):
    a = candidate("id.a", "A", "0,0,100,100")
    b = candidate("id.b", "B", "0,100,100,200")
    current = row("id.b", "B", "0,100,100,200", selected=a,
                  move_result={"success": False, "status": "failed_single_target"},
                  last_smart_nav_result="failed_single_target", smart_nav_success=False)
    current["scenario_id"] = "menu_main"
    current["scenario_type"] = "content"
    current["dump_tree_nodes"] = [a["node"], b["node"]]
    previous = row("id.a", "A", "0,0,100,100", selected=a)
    state = SimpleNamespace(
        reliability_metrics=TraversalMetrics(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
    )
    monkeypatch.setattr(flow, "_collect_step_candidate_priority_groups", lambda *_a, **_k: ([a, b], [], {}))
    result = flow._apply_focus_reconciliation(
        client=SimpleNamespace(),
        row=current,
        previous_row=previous,
        state=state,
        progress_decision=SimpleNamespace(gate_applied=True, physical_progress=False),
        visit_decision=SimpleNamespace(visited=False, consumed=True),
    )
    assert result["focus_sequence_changed"] is True
    assert result["focus_transition_status"] == "CONFIRMED_MOVED"
    assert result["reconciled_visit_instance_id"] == result["actual_focus_instance_id"]
    assert current["command_ack_status"] == "FAIL"
    assert current["focus_view_id"] == "id.b"
    assert current["focus_reconciliation_applied"] is True
    assert current["focus_reconciliation_planning_consumed"] is True
