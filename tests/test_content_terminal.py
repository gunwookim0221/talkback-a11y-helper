from types import SimpleNamespace

import pytest

from tb_runner.content_terminal import ContentTerminal, enabled, failed_scroll_reason
from tb_runner.scroll_reliability import capability, viewport
from tb_runner.traversal_reliability import TraversalMetrics, instance_id, termination_status


def node(label="Card", bounds="10,30,110,130", rid="app:id/card", **extra):
    return dict(text=label, boundsInScreen=bounds, viewIdResourceName=rid,
                className="android.widget.TextView", focusable=True, clickable=False,
                isVisibleToUser=True, **extra)


def observation(nodes=None, forward=False, contradictory=False):
    nodes = [node()] if nodes is None else nodes
    cap = capability(nodes, {"canScrollDown": forward} if forward is not None else {})
    cap["contradictory"] = contradictory
    return dict(nodes=nodes, capability=cap, viewport=viewport(nodes, "test"))


def proof(n=None, a11y=True, focused=False):
    n = n or node()
    return dict(scenario_id="test", actual_focus_resource_id=n["viewIdResourceName"],
                actual_focus_bounds=n["boundsInScreen"], actual_focus_visible=n["text"],
                actual_focus_accessibility_focused=a11y, actual_focus_input_focused=focused,
                physical_visited=True)


def stable(t, obs=None, proofs=(), semantic_ids=(), steps=2):
    for step in range(steps):
        t.observe(obs or observation(), step, focus_observations=proofs, semantic_ids=semantic_ids)
    return t


def scroll(obs, *, changed=False, success=True, new=0):
    return dict(action_success=success, viewport_changed=changed, new_count=new,
                before=obs["viewport"], after=obs["viewport"], status="SCROLL_MOVED" if changed else "SCROLL_NO_CHANGE")


def test_unseen_zero_no_scroll_stable_completes():
    t = stable(ContentTerminal("test"), proofs=[proof()])
    assert t.decision() == "content_completed"
    assert t.latest["remaining_unseen_count"] == 0


def test_first_observation_cannot_prove_stability():
    t = stable(ContentTerminal("test"), proofs=[proof()], steps=1)
    assert t.decision() == ""


def test_unseen_remains_no_progress_is_incomplete():
    t = stable(ContentTerminal("test"), steps=5)
    assert t.latest["remaining_unseen_count"] == 1
    assert t.decision() == "content_no_progress"
    assert termination_status(t.decision()) == "INCOMPLETE_NO_PROGRESS"


def test_new_unmatched_actual_focus_resets_traversal_no_progress_without_covering_population():
    t = ContentTerminal("test")
    obs = observation()
    for step in range(4):
        t.observe(obs, step)
    outside = node("Navigation", bounds="10,200,110,300", rid="app:id/outside_expected")
    t.observe(obs, 4, focus_observations=[proof(outside)], focus_sequence_progress=True)
    assert t.latest["focus_sequence_progress"] is True
    assert t.latest["remaining_unseen_count"] == 1
    assert t.latest["visited_candidates"] == 0
    assert t.latest["no_progress_steps"] == 0
    assert t.latest["no_focus_progress_steps"] == 0
    assert t.decision() == ""


def test_unlabeled_actionable_object_is_not_discarded():
    t = stable(ContentTerminal("test"), observation([node(label="")]))
    assert t.latest["remaining_unseen_count"] == 1 and t.latest["excluded_candidates"] == 0
    assert t.decision() == ""


def test_scroll_potential_prevents_completion():
    t = stable(ContentTerminal("test"), observation(forward=True), [proof()])
    assert not t.latest["scroll_exhausted"] and t.decision() == ""


def test_scroll_movement_adds_candidate_and_resets_stability():
    t = stable(ContentTerminal("test"), observation(forward=True), [proof()])
    obs = observation([node(bounds="10,160,110,260")], forward=False)
    t.observe(obs, 2, [proof()], scroll=scroll(obs, changed=True, new=1))
    assert t.latest["new_instances"] == 1 and t.latest["remaining_unseen_count"] == 1
    assert not t.latest["viewport_stable"] and t.decision() == ""


def test_successful_unchanged_scroll_with_forward_true_is_unverified():
    obs = observation(forward=True)
    t = stable(ContentTerminal("test"), obs, [proof()])
    t.observe(obs, 2, [proof()], scroll=scroll(obs))
    assert t.decision() == "content_scroll_unverified" and t.latest["stable_scroll_attempts"] == 1
    t.observe(obs, 3, [proof()], scroll=scroll(obs))
    assert t.decision() == "content_scroll_unverified" and not t.latest["scroll_exhausted"]


@pytest.mark.parametrize("forward,contradictory", [(None, False), (True, True), (False, True)])
def test_unknown_or_contradictory_scroll_never_completes(forward, contradictory):
    obs = observation(forward=forward, contradictory=contradictory)
    t = stable(ContentTerminal("test"), obs, [proof()])
    t.observe(obs, 2, [proof()], scroll=scroll(obs))
    t.observe(obs, 3, [proof()], scroll=scroll(obs))
    assert t.decision() == "content_scroll_unverified" and not t.latest["scroll_exhausted"]


def test_failed_action_is_not_a_stable_scroll_confirmation():
    obs = observation(forward=True)
    t = stable(ContentTerminal("test"), obs, [proof()])
    t.observe(obs, 2, [proof()], scroll=scroll(obs, success=False))
    assert t.latest["stable_scroll_attempts"] == 0 and not t.latest["scroll_exhausted"]


@pytest.mark.parametrize("result,reason", [
    ({"actionSupported": False, "actionAttempted": False}, "content_scroll_unverified"),
    ({"error": "ADBDisconnected"}, "content_error"),
    ({"after_dump_error": "TransportError"}, "content_error"),
    ({"actionSupported": True, "actionAttempted": True}, "content_error"),
])
def test_unsupported_scroll_is_unverified_while_runtime_failure_is_error(result, reason):
    assert failed_scroll_reason({"action_result": result}) == reason


def test_cap_before_closure_remains_safety_limit():
    t = stable(ContentTerminal("test"), steps=2)
    s = t.summary("safety_limit", 2)
    assert s["termination_status"] == "INCOMPLETE_SAFETY_LIMIT"
    assert s["remaining_unseen_count"] == 1 and s["termination_step"] == 2


def test_pending_transition_prevents_completion():
    t = stable(ContentTerminal("test"), proofs=[proof()])
    t.observe(observation(), 2, [proof()], pending=True)
    assert t.decision() == ""


@pytest.mark.parametrize("a11y,focused", [(False, False), (False, True), (None, None)])
def test_false_focus_input_focus_and_unknown_flags_are_not_actual_visits(a11y, focused):
    t = stable(ContentTerminal("test"), proofs=[proof(a11y=a11y, focused=focused)])
    assert t.latest["visited_candidates"] == 0 and t.latest["unseen_candidates"] == 1


def test_semantic_readable_coverage_stays_separate_from_actual_visits():
    n = node(); n["focusable"] = False
    key = instance_id(dict(scenario_id="test", view_id=n["viewIdResourceName"], bounds=n["boundsInScreen"]))
    t = stable(ContentTerminal("test"), observation([n]), semantic_ids=[key])
    assert t.latest["visited_candidates"] == 0 and t.latest["semantically_covered_candidates"] == 1
    assert t.decision() == "content_completed"


def test_semantic_actionable_coverage_cannot_hide_unseen_focus_target():
    key = instance_id(dict(scenario_id="test", view_id="app:id/card", bounds="10,30,110,130"))
    t = stable(ContentTerminal("test"), semantic_ids=[key])
    assert t.latest["semantically_covered_candidates"] == 1 and t.latest["unseen_candidates"] == 1
    assert t.decision() == ""


def test_state_refresh_and_volatile_text_do_not_create_instances_or_block_terminal():
    t = ContentTerminal("test")
    for step in range(5):
        t.observe(observation([node(label=f"Updated {step}")]), step, [proof()])
    assert len(t.records) == 1 and t.latest["new_instances"] == 0
    assert len(t.latest["volatile_candidate_ids"]) == 1 and t.decision() == "content_completed"
    assert len({e["strict_viewport_signature"] for e in t.history}) == 5
    assert len({e["semantic_viewport_signature"] for e in t.history}) == 1


def test_same_resource_id_distinct_bounds_preserve_collision():
    nodes = [node(), node(bounds="120,30,220,130")]
    t = stable(ContentTerminal("test"), observation(nodes), [proof(nodes[0])])
    assert len(t.records) == 2 and t.latest["visited_candidates"] == 1 and t.latest["unseen_candidates"] == 1


def test_horizontal_navigation_container_excluded_but_readable_child_retained():
    n = node(); n["className"] = "androidx.viewpager.widget.ViewPager"
    n["children"] = [node(bounds="20,40,90,90", rid="app:id/child")]
    t = stable(ContentTerminal("test"), observation([n]))
    assert t.latest["excluded_candidate_records"][0]["exclusion_reason"] == "OUT_OF_SCOPE_FOR_CONTENT_TERMINAL"
    assert t.latest["unseen_candidates"] == 1


def test_global_nav_bounds_are_scope_evidence_not_body_visits():
    t = ContentTerminal("test", nav_regions=["0,20,200,140"])
    stable(t, proofs=[proof()])
    assert t.latest["visible_candidates"] == 0 and t.latest["visited_candidates"] == 0
    assert t.latest["excluded_candidates"] == 1


def test_empty_or_missing_snapshot_is_error_not_empty_completion():
    t = stable(ContentTerminal("test"), observation([]))
    assert t.decision() == "content_error"
    assert t.latest["remaining_unseen_count"] is None


def test_unverified_scope_cannot_complete():
    t = stable(ContentTerminal("test", scope_verified=False), proofs=[proof()], steps=6)
    assert t.decision() == "content_scope_unverified"


def test_continuous_structural_churn_is_retained_and_bounded():
    t = ContentTerminal("test")
    for step in range(8):
        t.observe(observation([node(rid=f"app:id/object{step}")]), step)
    assert len(t.records) == 8 and t.decision() == "content_dynamic_unsettled"


def test_root_scope_dispatch_keeps_global_nav_and_plugin_contracts():
    assert enabled(dict(scenario_type="content", screen_context_mode="bottom_tab"))
    assert not enabled(dict(scenario_type="global_nav", screen_context_mode="bottom_tab"))
    assert not enabled(dict(scenario_type="content", screen_context_mode="plugin_screen"))


def test_common_phase_uses_real_focus_and_rejects_legacy_false_completion(monkeypatch, tmp_path):
    from tb_runner import collection_flow as flow
    n = node()
    client = SimpleNamespace(dump_tree=lambda **kwargs: [n], last_dump_metadata={"canScrollDown": False},
                             last_scroll_capabilities=[], _focusable_inventory=[], _scroll_transitions=[])
    state = SimpleNamespace(content_terminal=ContentTerminal("test"), reliability_metrics=TraversalMetrics())
    ctx = SimpleNamespace(output_path=str(tmp_path / "run.xlsx"), all_rows=[], output_base_dir=str(tmp_path))
    monkeypatch.setattr(flow, "_ensure_focusable_inventory", lambda *_: [])
    monkeypatch.setattr(flow, "_build_focusable_coverage_payload", lambda *a, **k: {"records": []})
    for step in range(1, 6):
        stop, reason = flow._apply_content_terminal_phase(client, "device", state, {}, ctx, step,
                                                         True, "move_terminal")
    assert stop and reason == "content_no_progress"
    assert state.content_terminal.latest["remaining_unseen_count"] == 1


def test_finalizer_writes_same_terminal_to_json_coverage_excel_and_evidence(monkeypatch, tmp_path):
    from tb_runner import collection_flow as flow
    from tb_runner.excel_report import save_excel
    import json
    import pandas as pd
    t = stable(ContentTerminal("test"), proofs=[proof()])
    events = []
    runtime = SimpleNamespace(is_enabled=True, emit=lambda event, **kw: events.append((event, kw["payload"])))
    client = SimpleNamespace(_content_terminal_trackers={"test": t}, _focusable_inventory=[], evidence_runtime=runtime,
                             last_main_traversal_summary={"stop_reason": "content_completed"})
    inventory = dict(scenario_id="test", view_id="app:id/card", bounds="10,30,110,130",
                     label="Card", class_name="android.widget.TextView", focusable=True, source="helper_snapshot")
    rows = [dict(proof(), scenario_id="test", visible_label="Card", merged_announcement="Card", status="PASS", step_index=1)]
    def inner(*args, **kwargs):
        args[0]._content_terminal_trackers = {"test": t}
        args[0].last_main_traversal_summary = {"stop_reason": "content_completed"}
        args[0]._active_traversal_metrics.begin_step(1)
        args[3].extend(rows)
        return rows
    monkeypatch.setattr(flow, "_collect_tab_rows_inner", inner)
    monkeypatch.setattr(flow, "_ensure_focusable_inventory", lambda *a: [inventory])
    monkeypatch.setattr(flow, "save_excel_with_perf", lambda fn, rows, path, **kw: save_excel(rows, path, with_images=False))
    path = tmp_path / "run.xlsx"
    flow._collect_tab_rows_impl(client, "device", {"scenario_id": "test"}, [], str(path), str(tmp_path))
    s = json.loads(path.with_suffix('.traversal_summary.json').read_text())["scenarios"][0]
    cov = json.loads(path.with_suffix('.focusable_coverage.json').read_text())
    x = pd.read_excel(path, sheet_name="traversal").iloc[0]
    terminal = next(payload for event, payload in events if event == "CONTENT_TERMINAL")
    summary_sheet = pd.read_excel(path, sheet_name="summary")
    for k in ["termination_status", "termination_reason", "termination_step", "remaining_unseen_count", "scroll_exhausted", "viewport_stable"]:
        assert s[k] == x[k] == terminal[k] == cov["summary"][0][k]
        value = summary_sheet.loc[(summary_sheet["section"] == "content_terminal:test") & (summary_sheet["metric"] == k), "value"].iloc[0]
        assert value == s[k]
    assert s["termination_status"] == "COMPLETED"
    assert path.with_suffix('.traversal_summary.content_terminal.json').exists()


def test_new_attempt_cannot_reuse_previous_completion_or_terminal_tracker(monkeypatch, tmp_path):
    from tb_runner import collection_flow as flow
    client = SimpleNamespace(last_main_traversal_summary={"stop_reason": "content_completed"},
                             _content_terminal_trackers={"test": stable(ContentTerminal("test"), proofs=[proof()])},
                             _initial_scroll_observations={"test": observation()}, _focusable_inventory=[],
                             _focusable_inventory_snapshot_keys={str(tmp_path / "run.xlsx") + "|test|Tab"})
    def failed(*args, **kwargs):
        rows = [{"scenario_id": "test", "stop_reason": "tab_or_anchor_failed", "status": "TAB_OPEN_FAILED"}]
        args[3].extend(rows)
        return rows
    monkeypatch.setattr(flow, "_collect_tab_rows_inner", failed)
    monkeypatch.setattr(flow, "save_excel_with_perf", lambda *a, **k: None)
    flow._collect_tab_rows_impl(client, "device", {"scenario_id": "test", "screen_context_mode": "bottom_tab"}, [], str(tmp_path / "run.xlsx"), str(tmp_path))
    assert client.last_main_traversal_summary["termination_status"] == "INCOMPLETE_ERROR"
    assert client.last_main_traversal_summary["termination_reason"] == "tab_or_anchor_failed"
    assert client.last_main_traversal_summary["remaining_unseen_count"] is None
    assert client.last_main_traversal_summary["observation_valid"] is False
    assert "test" not in client._content_terminal_trackers and "test" not in client._initial_scroll_observations


def test_home_plateau_requires_scroll_before_no_progress():
    t = stable(ContentTerminal("test"), observation(forward=True), steps=5)
    assert t.latest["active_unseen"] == 1
    assert t.scroll_opportunity()
    assert t.decision() == ""


def test_same_viewport_no_change_scroll_is_not_retried_or_completed():
    obs = observation(forward=True)
    t = stable(ContentTerminal("test"), obs, steps=5)
    t.observe(obs, 5, scroll=scroll(obs))
    assert not t.scroll_opportunity()
    assert t.decision() == "content_scroll_unverified"
    assert not t.latest["scroll_exhausted"]


def test_scroll_moved_new_focus_is_visited_and_progress():
    obs = observation(forward=True)
    t = stable(ContentTerminal("test"), obs, steps=5)
    fresh = node(bounds="10,160,110,260")
    after = observation([fresh], forward=False)
    t.observe(after, 5, [proof(fresh)], scroll=scroll(after, changed=True, new=1))
    assert t.latest["visited_candidates"] == 1
    assert t.latest["no_progress_steps"] == 0
    assert t.decision() == ""


def test_home_common_phase_scrolls_with_active_unseen(monkeypatch, tmp_path):
    from tb_runner import collection_flow as flow
    obs = observation(forward=True)
    t = stable(ContentTerminal("test"), obs, steps=4)
    client = SimpleNamespace(_scroll_transitions=[], _focusable_inventory=[])
    state = SimpleNamespace(content_terminal=t, reliability_metrics=TraversalMetrics())
    ctx = SimpleNamespace(output_path=str(tmp_path / "run.xlsx"), all_rows=[], output_base_dir=str(tmp_path))
    monkeypatch.setattr(flow.scroll_reliability, "capture", lambda *a, **k: obs)
    monkeypatch.setattr(flow, "_ensure_focusable_inventory", lambda *_: [])
    monkeypatch.setattr(flow, "_build_focusable_coverage_payload", lambda *a, **k: {"records": []})
    calls = []
    fresh = observation([node(bounds="10,160,110,260")], forward=False)
    def perform(*a, **k):
        calls.append(k["before"])
        return scroll(fresh, changed=True, new=1), fresh
    monkeypatch.setattr(flow.scroll_reliability, "verified_scroll", perform)
    row = {}
    stop, reason = flow._apply_content_terminal_phase(client, "device", state, row, ctx, 4, True, "repeat_no_progress")
    assert len(calls) == 1
    assert (stop, reason) == (False, "")
    assert row["scroll_status"] == "SCROLL_MOVED"
    assert t.latest["no_progress_steps"] == 0


@pytest.mark.parametrize("forward", [False, None])
def test_plateau_without_verified_vertical_opportunity_does_not_scroll(forward):
    t = stable(ContentTerminal("test"), observation(forward=forward), steps=5)
    assert not t.scroll_opportunity()
    assert t.decision() in {"content_no_progress", "content_scroll_unverified"}


def test_horizontal_only_plateau_never_requests_vertical_scroll():
    from tb_runner.scroll_reliability import capability, viewport
    n = node()
    container = dict(className="android.widget.HorizontalScrollView", isScrollable=True,
                     scroll_forward_supported=True, boundsInScreen="0,0,200,200")
    obs = dict(nodes=[n], capability=capability([n], {"canScrollDown": True}, [container]),
               viewport=viewport([n], "test"))
    t = stable(ContentTerminal("test"), obs, steps=5)
    assert t.latest["horizontal_can_scroll_forward"]
    assert t.latest["vertical_can_scroll_forward"] is False
    assert not t.scroll_opportunity()
    assert t.decision() == "content_no_progress"


def test_failed_scroll_consumes_viewport_without_retry():
    obs = observation(forward=True)
    t = stable(ContentTerminal("test"), obs, steps=5)
    t.observe(obs, 5, scroll=scroll(obs, success=False))
    for step in range(6, 10):
        t.observe(obs, step)
        assert not t.scroll_opportunity()
        assert t.decision() == "content_scroll_unverified"
    assert len(t.scroll_attempted_viewports) == 1
    assert not t.visited


def test_new_viewport_opportunity_after_movement_is_not_deduped():
    obs = observation(forward=True)
    t = stable(ContentTerminal("test"), obs, steps=5)
    after = observation([node(bounds="10,160,110,260")], forward=True)
    transition = scroll(obs, changed=True, new=1)
    transition["after"] = after["viewport"]
    t.observe(after, 5, scroll=transition)
    assert t.no_progress_steps == 0
    assert not t.scroll_opportunity()
    for step in range(6, 10):
        t.observe(after, step)
    assert t.scroll_opportunity()
    assert t.decision() == ""


def test_error_stop_does_not_consume_scroll_opportunity(monkeypatch, tmp_path):
    from tb_runner import collection_flow as flow
    obs = observation(forward=True)
    t = stable(ContentTerminal("test"), obs, steps=5)
    client = SimpleNamespace(_scroll_transitions=[], _focusable_inventory=[])
    state = SimpleNamespace(content_terminal=t, reliability_metrics=TraversalMetrics())
    ctx = SimpleNamespace(output_path=str(tmp_path / "run.xlsx"), all_rows=[], output_base_dir=str(tmp_path))
    monkeypatch.setattr(flow.scroll_reliability, "capture", lambda *a, **k: obs)
    monkeypatch.setattr(flow, "_ensure_focusable_inventory", lambda *_: [])
    monkeypatch.setattr(flow, "_build_focusable_coverage_payload", lambda *a, **k: {"records": []})
    def unexpected(*a, **k):
        pytest.fail("runtime error must not trigger scroll")
    monkeypatch.setattr(flow.scroll_reliability, "verified_scroll", unexpected)
    assert flow._apply_content_terminal_phase(client, "device", state, {}, ctx, 6, True, "content_error") == (True, "content_error")
