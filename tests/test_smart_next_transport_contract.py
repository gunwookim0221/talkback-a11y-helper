from types import SimpleNamespace
import json
import subprocess

import pytest

from talkback_lib import ACTION_SMART_NEXT, A11yAdbClient
from talkback_lib.helper_bridge import HelperBridge


@pytest.fixture
def client(monkeypatch):
    value = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(HelperBridge, "SMART_NAV_RESULT_WAIT_SECONDS", 1.0)
    return value


@pytest.fixture
def clock(monkeypatch):
    import talkback_lib
    state = [0.0]
    monkeypatch.setattr(talkback_lib.time, "monotonic", lambda: state[0])
    monkeypatch.setattr(talkback_lib.time, "sleep", lambda seconds: state.__setitem__(0, state[0] + seconds))
    return state


def payload(req_id):
    return "A11Y_HELPER: SMART_NAV_RESULT " + json.dumps({"reqId": req_id, "success": True, "status": "moved"})


def test_command_success_and_correlated_result(client, monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="Broadcast completed: result=0", stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: payload("ok"))
    result = client._helper_bridge._request_smart_next(None, "ok")
    assert result["success"] is True
    assert result["reqId"] == "ok"
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 30.0
    assert calls[0][1]["capture_output"] is True
    assert "shell" not in calls[0][1]
    assert result["resultWaitSeconds"] == 1.0


def test_adb_timeout_is_delivery_failure_and_never_retried_or_credited(client, monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"Broadcasting: Intent", stderr=b"pending")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(client, "_read_log_result", lambda *a, **k: pytest.fail("Must not accept a result after uncertain delivery"))
    result = client._helper_bridge._request_smart_next(None, "timed-out")
    assert result["success"] is False
    assert result["status"] == "transport_error"
    assert result["reason"] == "adb_command_timeout"
    assert result["commandTimeoutSeconds"] == 30.0
    assert result["commandStdout"] == "Broadcasting: Intent"
    assert result["commandStderr"] == "pending"
    assert result["resultWaitStarted"] is False
    assert len(calls) == 1


def test_command_nonzero_is_not_result_wait_timeout(client, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="device offline"))
    result = client._helper_bridge._request_smart_next(None, "offline")
    assert result["reason"] == "adb_command_failed"
    assert result["success"] is False
    assert result["commandStderr"] == "device offline"


def test_result_can_arrive_after_command_ack(client, monkeypatch, clock):
    monkeypatch.setattr(client, "_broadcast", lambda *a, **k: "ACK")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: payload("delayed") if clock[0] >= .4 else "")
    result = client._helper_bridge._request_smart_next(None, "delayed")
    assert result["success"] is True
    assert .4 <= clock[0] < 1.0
    assert result["deliveryElapsedSeconds"] == 0


def test_missing_correlated_result_times_out_without_false_success(client, monkeypatch, clock):
    monkeypatch.setattr(client, "_broadcast", lambda *a, **k: "ACK")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: payload("other-request"))
    result = client._helper_bridge._request_smart_next(None, "missing")
    assert result["success"] is False
    assert result["reqId"] == "missing"
    assert result["reason"] == "smart_nav_result_wait_timeout"


def test_result_returned_after_wait_deadline_is_explicitly_late(client, monkeypatch, clock):
    monkeypatch.setattr(client, "_broadcast", lambda *a, **k: "ACK")
    def logs(dev=None):
        clock[0] = 1.1
        return payload("late")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", logs)
    result = client._helper_bridge._request_smart_next(None, "late")
    assert result["success"] is False
    assert result["reason"] == "late_smart_nav_result"
    assert result["lateResult"] is True


def test_duplicate_request_id_cannot_execute_or_accept_previous_result_again(client, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "_broadcast", lambda *a, **k: calls.append(a) or "ACK")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: payload("once"))
    assert client._helper_bridge._request_smart_next(None, "once")["success"] is True
    result = client._helper_bridge._request_smart_next(None, "once")
    assert result["success"] is False
    assert result["reason"] == "duplicate_smart_next_request_id"
    assert len(calls) == 1


def test_retired_late_result_is_observed_once_and_cannot_satisfy_next_request(client, monkeypatch, clock, capsys):
    monkeypatch.setattr(client, "_broadcast", lambda *a, **k: "ACK")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: "")
    assert client._helper_bridge._request_smart_next(None, "old")["success"] is False
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: payload("old") + "\n" + payload("new"))
    result = client._helper_bridge._request_smart_next(None, "new")
    assert result["reqId"] == "new"
    assert result["success"] is True
    client._helper_bridge.observe_late_smart_results(payload("old"))
    assert capsys.readouterr().out.count("late_result req_id=old ignored=true") == 1


def test_move_focus_smart_does_not_retry_transport_failure(client, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "_has_recent_helper_ok", lambda **k: True)
    monkeypatch.setattr(client, "_broadcast", lambda *a, **k: calls.append(a) or "ACK")
    monkeypatch.setattr(client, "_read_log_result", lambda dev, prefix, req_id, **k: {"reqId": req_id, "success": False, "status": "transport_error", "reason": "smart_nav_result_wait_timeout"})
    result = client.move_focus_smart()
    assert result["success"] is False
    assert result["status"] == "failed"
    assert len(calls) == 1
    assert calls[0][1] == ACTION_SMART_NEXT
    assert len(client.last_smart_nav_result["reqId"]) == 32


def test_generic_adb_timeout_contract_remains_unchanged(client, monkeypatch):
    def run(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k["timeout"])
    monkeypatch.setattr(subprocess, "run", run)
    assert client._broadcast(None, "com.example.PING") == ""
