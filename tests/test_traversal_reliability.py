"""Phase 0A: instance identity, observed visits and incomplete termination."""
from types import SimpleNamespace
from collections import deque
import json

import pytest

from tb_runner import collection_flow as flow
from tb_runner.traversal_reliability import (
    TraversalMetrics, focus_instance, instance_id, termination_status,
)


def item(bounds="0,0,100,100", label="Card", rid="card"):
    return dict(scenario_id="screen", view_id=rid, bounds=bounds, label=label)


def focus(bounds="0,0,100,100", **extra):
    row = dict(scenario_id="screen", focus_view_id="card", focus_bounds=bounds,
               visible_label="Card", move_result="moved")
    if "focus_node" not in extra:
        row["actual_focus_accessibility_focused"] = True
    row.update(extra)
    return row


def test_same_resource_different_bounds():
    assert instance_id(item()) != instance_id(item("0,100,100,200"))


def test_same_resource_different_label_and_bounds():
    assert instance_id(item()) != instance_id(item("0,100,100,200", "Other"))


def test_repeated_dump_and_mutable_label_are_stable():
    assert instance_id(item()) == instance_id(item(label="On"))
    assert instance_id(item()) == instance_id(item(bounds="{'l': 0, 't': 0, 'r': 100, 'b': 100}"))


def test_no_resource_id_stable_and_distinct():
    assert instance_id(item(rid="")) == instance_id(item(rid=""))
    assert instance_id(item(rid="")) != instance_id(item("0,100,100,200", rid=""))


def test_same_text_cards_do_not_merge():
    assert len(flow._canonicalize_focusable_inventory([item(), item("0,100,100,200")])) == 2
    assert flow._candidate_logical_signature(dict(rid="card", label="Card", bounds="0,0,100,100")) != flow._candidate_logical_signature(dict(rid="card", label="Card", bounds="0,100,100,200"))


def test_one_card_does_not_visit_sibling():
    payload = flow._build_focusable_coverage_payload([item(), item("0,100,100,200")], [focus()], "test.xlsx")
    assert [r["visit_status"] for r in payload["records"]] == ["VISITED", "UNVISITED"]
    assert payload["records"][1]["coverage_status"] != "COVERED"


def test_planned_representative_without_actual_focus_is_not_visited():
    row = focus(row_source="representative")
    assert focus_instance(row) is None
    payload = flow._build_focusable_coverage_payload([item()], [row], "test.xlsx")
    assert payload["records"][0]["visit_status"] != "VISITED"


def test_actual_focus_wins_over_candidate():
    row = focus(row_source="representative", actual_focus_resource_id="card",
                actual_focus_bounds="0,100,100,200", actual_focus_visible="Card")
    assert instance_id(focus_instance(row)) == instance_id(item("0,100,100,200"))


def test_safety_limit_is_incomplete():
    assert termination_status("safety_limit") == "INCOMPLETE_SAFETY_LIMIT"


@pytest.mark.parametrize("reason", ["smart_nav_terminal", "move_terminal", "confirmed_local_tab_exhaustion"])
def test_explicit_terminal_is_complete(reason):
    assert termination_status(reason) == "COMPLETED"


@pytest.mark.parametrize("reason", ["repeat_no_progress", "bounded_two_card_loop", "global_nav_end", "exhausted_not_scrollable_no_unvisited_local_tab", "exhausted_strip_only_terminal_state", "local_tab_revisit_no_new_semantic_content"])
def test_no_progress_is_incomplete(reason):
    assert termination_status(reason) == "INCOMPLETE_NO_PROGRESS"


def test_safety_never_means_coverage_complete():
    metrics = TraversalMetrics()
    metrics.begin_step(10)
    summary = metrics.summary([focus()], "safety_limit")
    assert summary["coverage_complete"] is False
    assert summary["terminal_step"] == 10


def test_attempted_and_rows_are_independent():
    metrics = TraversalMetrics()
    for step in range(1, 4):
        metrics.begin_step(step)
        metrics.observe_move(focus() if step < 3 else dict(focus(), move_result="failed"))
    summary = metrics.summary([focus()], "safety_limit")
    assert summary["attempted_steps"] == 3
    assert summary["recorded_result_rows"] == 1
    assert summary["successful_moves"] == 2
    assert summary["failed_moves"] == 1


def test_duplicate_focus_does_not_inflate_visits():
    metrics = TraversalMetrics()
    for _ in range(3):
        metrics.observe_focus(focus())
    assert metrics.summary([], "safety_limit")["unique_visited_instances"] == 1


def test_ack_failures_and_reconciled_visits_have_separate_counters():
    metrics = TraversalMetrics()
    metrics.begin_step(1)
    metrics.observe_move({"move_result": {"success": False, "status": "failed"}})
    metrics.observe_reconciliation({
        "focus_transition_status": "CONFIRMED_MOVED",
        "command_ack_status": "FAIL",
        "visit_record_status": "RECORDED",
    })
    summary = metrics.summary([], "safety_limit")
    assert summary["failed_moves"] == 1
    assert summary["focus_moved_steps"] == 1
    assert summary["ack_failed_focus_moved_steps"] == 1
    assert summary["reconciled_new_visits"] == 1


def test_semantic_card_consumption_preserves_sibling_bounds():
    first = dict(semantic_card_id="card||rid||Card", semantic_card_title="Card", semantic_card_bounds="0,0,100,100")
    second = dict(first, semantic_card_bounds="0,100,100,200")
    state = SimpleNamespace()
    assert flow._semantic_card_consumed_signature(first, state) != flow._semantic_card_consumed_signature(second, state)


@pytest.mark.parametrize("reason", ["possible_crash", "runtime_error", "unknown_stop"])
def test_error_or_unverified_stop_is_incomplete(reason):
    assert termination_status(reason) == "INCOMPLETE_ERROR"


def test_section_heading_does_not_consume_children():
    state = SimpleNamespace(recent_representative_signatures=deque(), consumed_representative_signatures=set())
    row = focus(semantic_card_role="title", focus_cluster_signature="section",
                focus_cluster_logical_signature="section-logical")
    flow._record_recent_representative_signature(state, row)
    assert not getattr(state, "consumed_cluster_signatures", set())
    assert not getattr(state, "consumed_cluster_logical_signatures", set())


def test_safety_persistence_uses_last_attempt_not_last_row():
    metrics = TraversalMetrics()
    for step in range(1, 11):
        metrics.begin_step(step)
    rows = [dict(focus(), step_index=9)]
    state = SimpleNamespace(stop_triggered=False, stop_reason="", stop_step=-1, reliability_metrics=metrics)
    ctx = SimpleNamespace(rows=rows, tab_cfg=dict(scenario_id="screen"), state=state, scenario_perf=None)
    flow._persist_phase(ctx)
    assert rows[0]["termination_status"] == "INCOMPLETE_SAFETY_LIMIT"
    assert rows[0]["stop_step"] == rows[0]["terminal_step"] == 10
    assert rows[0]["attempted_steps"] == 10
    assert rows[0]["recorded_result_rows"] == 1
    assert rows[0]["coverage_complete"] is False


def test_runtime_exception_persists_incomplete_summary(monkeypatch, tmp_path):
    def fail(client, *args, **kwargs):
        client._active_traversal_metrics.begin_step(1)
        raise RuntimeError("helper failed")
    monkeypatch.setattr(flow, "_collect_tab_rows_inner", fail)
    client = SimpleNamespace()
    output = tmp_path / "run.xlsx"
    with pytest.raises(RuntimeError, match="helper failed"):
        flow._collect_tab_rows_impl(client, "serial", dict(scenario_id="screen"), [], str(output), str(tmp_path))
    summary = json.loads(output.with_suffix(".traversal_summary.json").read_text(encoding="utf-8"))["scenarios"][0]
    assert summary["termination_status"] == "INCOMPLETE_ERROR"
    assert summary["attempted_steps"] == 1
    assert summary["terminal_step"] == 1
    assert summary["unresolved_moves"] == 1


def test_representative_fallback_is_not_an_observation():
    assert focus_instance(focus(row_source="representative_fallback")) is None


def test_collision_summary_is_stable_for_duplicate_dumps():
    from tb_runner.traversal_reliability import identity_collisions
    candidates = [item(), item(), item("0,100,100,200", "Other")]
    assert identity_collisions(candidates) == [dict(scenario_id="screen", view_id="card", instances=2, distinct_labels=2, distinct_bounds=2)]


def test_unfocused_root_fallback_does_not_count_as_a_visit():
    row = focus(focus_payload_source="top_level", focus_node=dict(focused=False, accessibilityFocused=False))
    assert focus_instance(row) is None
    metrics = TraversalMetrics()
    metrics.observe_focus(row)
    assert metrics.summary([], "safety_limit")["unique_visited_instances"] == 0


def test_actual_focus_wins_without_v2_gate():
    state = SimpleNamespace(recent_representative_signatures=deque(), consumed_representative_signatures=set())
    row = focus(row_source="representative", actual_focus_resource_id="card",
                actual_focus_bounds="0,100,100,200", actual_focus_visible="Card")
    flow._record_recent_representative_signature(state, row)
    actual_key = flow._row_logical_signature(dict(focus(), focus_bounds="0,100,100,200"))
    assert actual_key in state.visited_logical_signatures
    assert flow._row_logical_signature(focus()) not in state.visited_logical_signatures


def test_unfocused_anchor_does_not_seed_visited_candidates():
    row = focus(focus_node=dict(focused=False, accessibilityFocused=False))
    state = flow._build_main_loop_state_from_anchor(row, anchor_fingerprint="root", anchor_repeat_count=0, step_index=0)
    assert state.visited_logical_signatures == set()


def test_representative_preserves_actual_unfocused_flags():
    row = focus(actual_focus_resource_id="card", actual_focus_bounds="0,0,100,100",
                actual_focus_visible="Card", focus_node=dict(focused=False, accessibilityFocused=False))
    flow._apply_cta_node_to_row(row=row, selected_node=dict(focused=True, accessibilityFocused=True),
        selected_rid="other", selected_label="Other", selected_bounds="0,100,100,200", selected_class="View", normalized_label="other")
    assert row["actual_focus_accessibility_focused"] is False
    assert row["actual_focus_input_focused"] is False
    assert focus_instance(row) is None
