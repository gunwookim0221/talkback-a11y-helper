from types import SimpleNamespace

import pytest

from talkback_lib import A11yAdbClient
from tb_runner.phase5c_hard_stop import (
    Phase5CHardStopError,
    Phase5CHardStopState,
    commit_audit_hard_stop,
)
from tb_runner.phase5b_navigation import SafeNavigationSession
from tb_runner import collection_flow


def test_hard_stop_is_monotonic_and_preserves_first_failure():
    state = Phase5CHardStopState(scenario="devices_main", run_id="run-1")
    first = state.latch(step=10, reasons=["AUDIT_CHAIN_INCOMPLETE"], action_id="step-10")
    second = state.latch(step=11, reasons=["OTHER"], action_id="step-11")

    assert first == second
    assert state.snapshot()["step"] == 10
    assert state.snapshot()["audit_reasons"] == ["AUDIT_CHAIN_INCOMPLETE"]
    assert state.snapshot()["later_work_permitted"] is False
    with pytest.raises(Phase5CHardStopError, match="10:preflight"):
        state.guard("preflight")


def test_committed_hard_stop_marks_terminal_without_changing_credits():
    state = Phase5CHardStopState(scenario="devices_main", run_id="run-2")
    client = SimpleNamespace()
    loop_state = SimpleNamespace(stop_triggered=False, stop_reason="", stop_step=0)
    row = {"attempt_credit": 0, "visit_credit": 1, "visit_record_status": "RECORDED"}

    record = commit_audit_hard_stop(
        controller=state,
        client=client,
        state=loop_state,
        row=row,
        step=10,
        reasons=["FALLBACK_OBSERVATION_OWNERSHIP_UNPROVEN"],
        action_id="step-10-action",
    )

    assert client._phase5c_hard_stop_state is state
    assert loop_state.stop_triggered is True
    assert loop_state.stop_reason == "audit_chain_incomplete"
    assert loop_state.stop_step == 10
    assert row["scenario_terminal_status"] == "INCOMPLETE_ERROR"
    assert row["scenario_terminal_reason"] == "audit_chain_incomplete"
    assert row["phase5c_hard_stop"] == record
    assert (row["attempt_credit"], row["visit_credit"], row["visit_record_status"]) == (
        0, 1, "RECORDED"
    )


@pytest.mark.parametrize("action", [
    "com.iotpart.sqe.talkbackhelper.GET_FOCUS",
    "com.iotpart.sqe.talkbackhelper.SCROLL",
    "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT",
    "com.iotpart.sqe.talkbackhelper.PING",
    "com.iotpart.sqe.talkbackhelper.DUMP_TREE",
    "com.iotpart.sqe.talkbackhelper.DUMP_HIERARCHY",
    "com.iotpart.sqe.talkbackhelper.EVIDENCE_EVENTS",
])
def test_helper_transport_refuses_every_new_command_after_hard_stop(action):
    calls = []
    client = object.__new__(A11yAdbClient)
    client.package_name = "com.iotpart.sqe.talkbackhelper"
    client._run = lambda command, **kwargs: calls.append((command, kwargs)) or "sent"
    client._evidence_correlation_extras = lambda: []
    client._phase5c_hard_stop_state = Phase5CHardStopState(
        scenario="devices_main", run_id="run-3"
    )
    client._phase5c_hard_stop_state.latch(
        step=10, reasons=["AUDIT_CHAIN_INCOMPLETE"], action_id="step-10"
    )

    with pytest.raises(Phase5CHardStopError):
        client._broadcast("SERIAL", action)

    assert calls == []


def test_helper_transport_remains_available_before_hard_stop():
    calls = []
    client = object.__new__(A11yAdbClient)
    client.package_name = "com.iotpart.sqe.talkbackhelper"
    client._run = lambda command, **kwargs: calls.append((command, kwargs)) or "sent"
    client._evidence_correlation_extras = lambda: []

    assert client._broadcast("SERIAL", "com.iotpart.sqe.talkbackhelper.GET_FOCUS") == "sent"
    assert len(calls) == 1


def test_phase5b_preflight_fallback_recovery_and_authorization_are_guarded():
    state = Phase5CHardStopState(scenario="devices_main", run_id="run-4")
    state.latch(step=10, reasons=["AUDIT_CHAIN_INCOMPLETE"], action_id="step-10")
    session = SafeNavigationSession("devices_main", lambda *_args, **_kwargs: None)
    session._active_client = SimpleNamespace(_phase5c_hard_stop_state=state)

    calls = [
        lambda: session.preflight_activation_dispatch(target={}, request_id="activate"),
        lambda: session.preflight_focus_dispatch(target={}, request_id="focus"),
        lambda: session.preflight_bounds_focus_dispatch(bounds="0,0,1,1", request_id="bounds"),
        lambda: session.collect(lambda **_kwargs: {}, {"move": False}, {}, session._active_client),
        lambda: session.fallback(lambda **_kwargs: {}, {}, {}, session._active_client),
        lambda: session.authorize("SCROLL").__enter__(),
        lambda: session.authorize_focus_target(
            raw={}, value=None, target={}, phase4_gate={}, step=11
        ).__enter__(),
    ]

    for operation in calls:
        with pytest.raises(Phase5CHardStopError):
            operation()


def test_scenario_terminal_records_hard_stop_and_surfaces_write_failure():
    state = Phase5CHardStopState(scenario="devices_main", run_id="run-5")
    state.latch(step=10, reasons=["AUDIT_CHAIN_INCOMPLETE"], action_id="step-10")
    emitted = []

    class Runtime:
        def emit(self, *args, **kwargs):
            emitted.append((args, kwargs))

    collection_flow._emit_scenario_terminal_event(
        Runtime(), {"traversal_started": True, "main_steps_completed": 10}, state
    )
    name, kwargs = emitted[0]
    assert name == ("SCENARIO_TERMINAL",)
    assert kwargs["payload"]["reason"] == "AUDIT_HARD_STOP"
    assert kwargs["payload"]["termination_status"] == "INCOMPLETE_ERROR"
    assert kwargs["payload"]["termination_reason"] == "audit_chain_incomplete"
    assert kwargs["payload"]["audit_hard_stop"]["step"] == 10

    class FailingRuntime:
        def emit(self, *_args, **_kwargs):
            raise OSError("terminal evidence unavailable")

    with pytest.raises(OSError, match="terminal evidence unavailable"):
        collection_flow._emit_scenario_terminal_event(
            FailingRuntime(), {"traversal_started": True}, state
        )


def test_phase5b_transport_firewall_observes_authoritative_hard_stop():
    state = Phase5CHardStopState(scenario="devices_main", run_id="run-6")
    state.latch(step=10, reasons=["AUDIT_CHAIN_INCOMPLETE"], action_id="step-10")
    calls = []
    client = SimpleNamespace(
        _phase5c_hard_stop_state=state,
        _run=lambda command, **kwargs: calls.append((command, kwargs)),
        _adb_device=None,
    )
    session = SafeNavigationSession("devices_main", lambda *_args, **_kwargs: None)

    with session.firewall(client, "SERIAL"):
        with pytest.raises(Phase5CHardStopError):
            client._run(["shell", "input", "swipe", "1", "2", "3", "4"])

    assert calls == []
