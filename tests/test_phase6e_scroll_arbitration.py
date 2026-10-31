"""Current SMART_NEXT end and scroll-owner arbitration through the real consumer."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from phase6d_capture_support import bind_observation_marker
from test_content_terminal import node, observation, scroll
from test_state_graph import _phase6e_capture, _phase6e_transition
from talkback_lib.exploration_evidence_clock import EvidenceClock
from talkback_lib.native_dispatch_evidence import NativeDispatchReceiptStore
from tb_runner.content_terminal import ContentTerminal
from tb_runner.traversal_reliability import TraversalMetrics


def _case(monkeypatch, tmp_path, *, omit_owner=False, stale_capture=False):
    from tb_runner import collection_flow as flow

    clock = EvidenceClock(scope_id="arbitration")
    store = NativeDispatchReceiptStore()
    dispatch = ["shell", "am", "broadcast", "-a",
                "com.iotpart.sqe.talkbackhelper.SMART_NEXT", "--es", "reqId", "current-end"]
    clock.dispatch(dispatch)
    store.observe(dispatch)
    result = {"reqId": "current-end", "status": "failed", "detail": "reached_end", "success": False}
    client = SimpleNamespace(
        _adb_device=SimpleNamespace(shadow_evidence_clock=clock, native_dispatch_receipts=store),
        _smart_nav_invocation_generation=1, _smart_nav_result_generation=1,
        _last_smart_nav_invocation_result=result, _scroll_transitions=[], _focusable_inventory=[])
    obs = observation(forward=True)
    tracker = ContentTerminal("home_main")
    tracker.observe(obs, 0)
    tracker.observe(obs, 1)
    state = SimpleNamespace(content_terminal=tracker, reliability_metrics=TraversalMetrics())
    ctx = SimpleNamespace(output_path=str(tmp_path / "run.xlsx"), all_rows=[], output_base_dir=str(tmp_path))
    row = {"scenario_id": "home_main", "scenario_run_id": "fixture_run", "step_index": 2,
           "phase6_current_action_type": "SMART_NEXT", "smart_nav_req_id": "current-end",
           "smart_nav_invocation_generation": 1, "smart_nav_result_generation": 1,
           "last_smart_nav_detail": "reached_end", "last_smart_nav_terminal": True,
           "smart_nav_success": False, "progress_status": "NO_PROGRESS_UNCHANGED"}
    source = _phase6e_capture(sequence=10, omit_owner=omit_owner)
    result_capture = _phase6e_capture(sequence=11, changed=True, focus=True)
    captures = iter((source, result_capture))
    def capture_current(*, client, dev, row, **_kwargs):
        raw = next(captures)
        marker = clock.finish_observation(clock.begin_observation())
        bind_observation_marker(raw, marker)
        row["_exploration_observation"] = deepcopy(marker)
        if stale_capture:
            clock.dispatch(["shell", "input", "keyevent", "4"])
        return raw
    monkeypatch.setattr(flow, "_capture_phase6d3a_production_observation", capture_current)
    monkeypatch.setattr(flow.scroll_reliability, "capture", lambda *a, **k: obs)
    monkeypatch.setattr(flow, "_ensure_focusable_inventory", lambda *_: [])
    monkeypatch.setattr(flow, "_build_focusable_coverage_payload", lambda *a, **k: {"records": []})
    calls = []
    def perform(*args, **kwargs):
        calls.append(kwargs["before"])
        nav = ["shell", "am", "broadcast", "-a", "com.iotpart.sqe.talkbackhelper.SCROLL",
               "--es", "reqId", "scroll-1"]
        clock.dispatch(nav)
        store.observe(nav)
        transition = _phase6e_transition(source, request_id="scroll-1")
        transition.update(scroll(observation([node(bounds="10,160,110,260")], forward=False), changed=True, new=1))
        return transition, observation([node(bounds="10,160,110,260")], forward=False)
    monkeypatch.setattr(flow.scroll_reliability, "verified_scroll", perform)
    return flow, client, state, row, ctx, calls


def test_current_end_with_current_owner_scrolls_before_repeating(monkeypatch, tmp_path):
    flow, client, state, row, ctx, calls = _case(monkeypatch, tmp_path)
    stopped, reason = flow._apply_content_terminal_phase(client, "device", state, row, ctx, 2, False, "")
    assert len(calls) == 1
    assert (stopped, reason) == (False, "")
    assert row["phase6e_scroll_evidence"]["classification"] == "SCROLL_MOVED"
    assert row["phase6e_scroll_evidence"]["valid_for_edge"] is True


@pytest.mark.parametrize("condition", ["missing_owner", "stale_capture"])
def test_current_end_without_current_owner_fails_closed(monkeypatch, tmp_path, condition):
    flow, client, state, row, ctx, calls = _case(
        monkeypatch, tmp_path, omit_owner=condition == "missing_owner",
        stale_capture=condition == "stale_capture")
    stopped, reason = flow._apply_content_terminal_phase(client, "device", state, row, ctx, 2, False, "")
    assert calls == []
    assert (stopped, reason) == (True, "content_scroll_unverified")


@pytest.mark.parametrize("condition", ["current", "missing_owner", "stale_capture"])
def test_plateau_requires_current_owner(monkeypatch, tmp_path, condition):
    flow, client, state, row, ctx, calls = _case(
        monkeypatch, tmp_path, omit_owner=condition == "missing_owner",
        stale_capture=condition == "stale_capture")
    row["phase6_current_action_type"] = ""
    state.content_terminal.observe(observation(forward=True), 2)
    state.content_terminal.observe(observation(forward=True), 3)
    stopped, reason = flow._apply_content_terminal_phase(client, "device", state, row, ctx, 4, False, "")
    assert len(calls) == (1 if condition == "current" else 0)
    assert (stopped, reason) == ((False, "") if condition == "current" else (True, "content_scroll_unverified"))


@pytest.mark.parametrize("condition", ["generation", "request", "later_action", "focus_progress", "unknown_progress"])
def test_stale_or_progressing_end_cannot_trigger_scroll(monkeypatch, tmp_path, condition):
    flow, client, state, row, ctx, calls = _case(monkeypatch, tmp_path)
    if condition == "generation":
        row["smart_nav_result_generation"] = 2
    elif condition == "request":
        row["smart_nav_req_id"] = "other-request"
    elif condition == "later_action":
        client._adb_device.native_dispatch_receipts.observe(["shell", "input", "keyevent", "4"])
    elif condition == "focus_progress":
        row["progress_status"] = "PROGRESS"
    else:
        row["progress_status"] = "UNAVAILABLE"
    assert flow._apply_content_terminal_phase(client, "device", state, row, ctx, 2, False, "") == (False, "")
    assert calls == []


def test_repeated_end_is_not_focus_or_content_progress():
    tracker = ContentTerminal("home_main")
    obs = observation(forward=True)
    tracker.observe(obs, 0)
    for step in range(1, 4):
        latest = tracker.observe(obs, step, focus_sequence_progress=False)
        assert latest["new_instances"] == 0
        assert latest["focus_sequence_progress"] is False
        assert latest["no_progress_steps"] == step


@pytest.mark.parametrize("capture_failure", [False, True])
def test_temporary_gate_clock_is_removed_on_every_exit(monkeypatch, tmp_path, capture_failure):
    from talkback_lib.adb_device import AdbDevice

    flow, client, state, row, ctx, calls = _case(monkeypatch, tmp_path)
    device = object.__new__(AdbDevice)
    device.native_dispatch_receipts = client._adb_device.native_dispatch_receipts
    device.shadow_evidence_clock = None
    client._adb_device = device
    def capture_current(*, client, dev, row, **_kwargs):
        if capture_failure:
            raise ValueError("capture failed")
        raw = _phase6e_capture(sequence=10, omit_owner=True)
        clock = client._adb_device.shadow_evidence_clock
        marker = clock.finish_observation(clock.begin_observation())
        bind_observation_marker(raw, marker)
        row["_exploration_observation"] = deepcopy(marker)
        return raw
    monkeypatch.setattr(flow, "_capture_phase6d3a_production_observation", capture_current)
    stopped, reason = flow._apply_content_terminal_phase(client, "device", state, row, ctx, 2, False, "")
    assert stopped
    assert reason == ("content_error" if capture_failure else "content_scroll_unverified")
    assert device.shadow_evidence_clock is None
    assert calls == []


@pytest.mark.parametrize("second_container,expected", [(False, "RESOLVED"), (True, "OWNER_AMBIGUOUS")])
def test_fallback_owner_must_be_unique_in_current_hierarchy(second_container, expected):
    from tb_runner.state_graph import phase6e_current_scroll_owner

    source = _phase6e_capture(sequence=10, second_container=second_container)
    source["capability"]["container"] = None
    owner = phase6e_current_scroll_owner(source, source["_exploration_observation"])
    assert owner["status"] == expected
    assert bool(owner["identity"]) is (not second_container)
