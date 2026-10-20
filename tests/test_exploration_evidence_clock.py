"""Offline native-boundary regression tests. All subprocess IO is replaced."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from talkback_lib.adb_device import AdbDevice
from talkback_lib.exploration_evidence_clock import EvidenceClock, classify_dispatch, dispatch_owner


def device(monkeypatch, *, returncode=0):
    monkeypatch.setenv("TB_STATE_GRAPH_MODE", "SHADOW")
    native = Mock(return_value=SimpleNamespace(returncode=returncode, stdout="", stderr="failure"))
    monkeypatch.setattr("talkback_lib.adb_device.subprocess.run", native)
    adb = AdbDevice("offline-adb", lambda dev: "offline")
    return adb, native


def observation(clock):
    return clock.finish_observation(clock.begin_observation())


@pytest.mark.parametrize("suffix", ["SMART_NEXT", "NEXT", "PREV", "FOCUS_TARGET", "FOCUS_IN_BOUNDS", "TARGET_FOCUS_COMMIT", "CLICK_TARGET", "CLICK_FOCUSED", "SCROLL", "SET_TEXT", "ACTION_COMMAND"])
def test_native_helper_dispatch_invalidates_even_when_failed(monkeypatch, suffix):
    adb, native = device(monkeypatch, returncode=1)
    clock = adb.shadow_evidence_clock
    old = observation(clock)
    assert clock.current(old)
    adb._run_adb_command(["shell", "am", "broadcast", "-a", "com.iotpart.sqe.talkbackhelper." + suffix, "--es", "request_id", "req-1"])
    assert native.call_count == 1
    assert clock.action_epoch == 1 and not clock.current(old)
    assert clock.receipts[-1]["request_id"] == "req-1"


@pytest.mark.parametrize("args", [
    ["shell", "am", "get-current-user"],
    ["shell", "-T", "content", "read", "--uri", "content://test/request"],
    ["shell", "content", "query", "--uri", "content://test/request"],
    ["shell", "settings", "get", "secure", "accessibility_enabled"],
    ["shell", "pm", "path", "app"], ["shell", "wm", "size"],
    ["shell", "screencap", "-p", "/sdcard/temp.png"],
    ["shell", "echo MARKER; dumpsys accessibility | grep -F 'Enabled services:'; pidof helper"],
    *[["shell", "am", "broadcast", "-a", "com.iotpart.sqe.talkbackhelper." + suffix]
      for suffix in ["GET_FOCUS", "DUMP_TREE", "RESOLVE_EXACT_NODE", "HIERARCHY_TRANSFER_START", "HIERARCHY_TRANSFER_STATUS", "HIERARCHY_TRANSFER_ACK", "HIERARCHY_TRANSFER_CANCEL"]],
])
def test_pure_reads_do_not_advance_epoch(monkeypatch, args):
    adb, _ = device(monkeypatch)
    clock = adb.shadow_evidence_clock
    old = observation(clock)
    adb._run_adb_command(args)
    assert clock.action_epoch == 0 and clock.current(old)


def test_pre_dispatch_guards_do_not_advance_epoch(monkeypatch):
    adb, native = device(monkeypatch)
    adb.command_guard = Mock(side_effect=RuntimeError("planner/safety/binding denied"))
    for invoke in (lambda: adb._tap(None, 1, 2), lambda: adb._run_adb_command(["shell", "input", "keyevent", "4"])):
        with pytest.raises(RuntimeError):
            invoke()
    assert adb.shadow_evidence_clock.action_epoch == 0
    native.assert_not_called()


def test_multiple_dispatches_and_fresh_capture(monkeypatch):
    adb, _ = device(monkeypatch)
    clock = adb.shadow_evidence_clock
    old = observation(clock)
    with dispatch_owner("RECOVERY"):
        adb._tap(None, 1, 2)
        adb._run_adb_command(["shell", "input", "keyevent", "4"])
    assert clock.action_epoch == 2 and not clock.current(old)
    current = observation(clock)
    assert clock.current(current)
    assert current["action_ownership"]["owner"] == "RECOVERY"
    assert current["observation_epoch"] == 2
    assert len(clock.receipts) == 2
    assert not clock.current(old)


def test_dispatch_during_capture_and_new_observation_invalidate_old_evidence():
    clock = EvidenceClock()
    token = clock.begin_observation()
    clock.dispatch(["shell", "input", "tap", "1", "2"])
    assert not clock.current(clock.finish_observation(token))
    old = observation(clock)
    fresh = observation(clock)
    assert not clock.current(old) and clock.current(fresh)
    assert clock.action_epoch == 1


def test_io_exception_advances_but_off_mode_remains_off(monkeypatch):
    adb, native = device(monkeypatch)
    native.side_effect = OSError("offline failure")
    assert adb._tap(None, 1, 2) is False
    assert adb.shadow_evidence_clock.action_epoch == 1
    monkeypatch.delenv("TB_STATE_GRAPH_MODE")
    off = AdbDevice("offline-adb", lambda dev: "offline")
    assert off.shadow_evidence_clock is None


def test_native_binary_read_does_not_advance(monkeypatch):
    adb, _ = device(monkeypatch)
    monkeypatch.setattr("talkback_lib.adb_device.subprocess.Popen", Mock(side_effect=OSError("offline")))
    with pytest.raises(Exception):
        adb._run_adb_binary_command(["shell", "-T", "content", "read", "--uri", "content://test/request"], max_stdout_bytes=100)
    assert adb.shadow_evidence_clock.action_epoch == 0


@pytest.mark.parametrize("owner", ["PRIMARY", "SEQUENTIAL", "TARGETED", "FALLBACK", "RECOVERY", "OPTIONAL_EXPANSION", "POPUP", "TAB", "OTHER"])
def test_owner_scope_is_observational_only(monkeypatch, owner):
    adb, native = device(monkeypatch)
    with dispatch_owner(owner):
        assert adb.shadow_evidence_clock.action_epoch == 0
        adb._tap(None, 1, 2)
    native.assert_called_once()
    assert adb.shadow_evidence_clock.receipts[-1]["owner"] == owner


def test_existing_phase5_firewall_blocks_before_clock_and_forwards_once(monkeypatch):
    from test_phase5b_navigation import session, focus_case, focus_scope, focus_command
    from tb_runner.phase5b_navigation import SafetyBlocked
    adb, native = device(monkeypatch)
    client = SimpleNamespace(_adb_device=adb, _run=lambda command, **kwargs: adb._run_adb_command(command, **kwargs))
    safety, _ = session()
    raw, value, candidate = focus_case()
    clock = adb.shadow_evidence_clock
    captured = observation(clock)
    with safety.firewall(client, "serial"):
        with pytest.raises(SafetyBlocked):
            client._run(focus_command(candidate["target_identity"]), dev="serial")
        with pytest.raises(SafetyBlocked):
            adb._tap("serial", 1, 2)
        assert clock.current(captured) and clock.action_epoch == 0
        native.assert_not_called()
        with focus_scope(safety, raw, value, candidate):
            client._run(focus_command(candidate["target_identity"]), dev="serial")
            assert clock.action_epoch == 1
            with pytest.raises(SafetyBlocked):
                client._run(focus_command(candidate["target_identity"], request="request:second"), dev="serial")
        assert clock.action_epoch == 1
    native.assert_called_once()
    assert not clock.current(captured)


def test_observer_failure_does_not_change_native_dispatch(monkeypatch):
    adb, native = device(monkeypatch)
    monkeypatch.setattr("talkback_lib.exploration_evidence_clock.classify_dispatch", Mock(side_effect=ValueError("bad evidence")))
    assert adb._tap(None, 1, 2) is True
    native.assert_called_once()
    assert not adb.shadow_evidence_clock.healthy


def test_history_reset_is_not_a_ui_action_but_expires_planner_context(monkeypatch):
    adb, native = device(monkeypatch)
    clock = adb.shadow_evidence_clock
    captured = observation(clock)
    command = ["shell", "am", "broadcast", "-a", "com.iotpart.sqe.talkbackhelper.ACTION_COMMAND", "--es", "command", "reset"]
    assert classify_dispatch(command) is None
    adb._run_adb_command(command)
    native.assert_called_once()
    assert clock.action_epoch == 0 and clock.context_revision == 1
    assert not clock.current(captured)
    assert clock.current(observation(clock))
    token = clock.begin_observation()
    adb._run_adb_command(command)
    assert not clock.current(clock.finish_observation(token))
