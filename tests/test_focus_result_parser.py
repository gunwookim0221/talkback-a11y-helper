from __future__ import annotations

from talkback_lib import A11yAdbClient
from talkback_lib.logcat_reader import LogcatReader


def test_extract_all_payloads_strips_focus_result_trailing_garbage():
    logs = (
        '01-01 I/A11Y_HELPER: FOCUS_RESULT '
        '{"reqId":"req-1","success":true,"node":{"text":"Energy"}} trailing noise'
    )

    payloads = LogcatReader.extract_all_payloads(logs, "FOCUS_RESULT")

    assert payloads == ['{"reqId":"req-1","success":true,"node":{"text":"Energy"}}']


def test_extract_req_payloads_preserves_dump_tree_chunks():
    logs = "\n".join(
        [
            '01-01 I/A11Y_HELPER: DUMP_TREE_PART dump-1 {"nodes":[{"text":"A"}',
            '01-01 I/A11Y_HELPER: DUMP_TREE_PART dump-1 ,{"text":"B"}]} trailing kept',
        ]
    )

    payloads = LogcatReader.extract_req_payloads(logs, "DUMP_TREE_PART", "dump-1")

    assert payloads == ['{"nodes":[{"text":"A"}', ',{"text":"B"}]} trailing kept']


def test_read_focus_result_strips_trailing_garbage(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    logs = (
        '01-01 I/A11Y_HELPER: FOCUS_RESULT '
        '{"reqId":"focus-1","success":true,"node":{"text":"Energy"}} trailing noise'
    )

    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: logs)

    result = client._read_log_result(None, "FOCUS_RESULT", "focus-1", wait_seconds=1.0)

    assert result["success"] is True
    assert result["reqId"] == "focus-1"
    assert result["node"]["text"] == "Energy"


def test_malformed_focus_result_returns_parse_error_without_retry(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    calls = {"count": 0}
    logs = '01-01 I/A11Y_HELPER: FOCUS_RESULT {"reqId":"focus-2", success:false}'

    def dump_filtered(dev=None):
        calls["count"] += 1
        return logs

    monkeypatch.setattr(client._logcat_reader, "dump_filtered", dump_filtered)

    result = client._read_log_result(None, "FOCUS_RESULT", "focus-2", wait_seconds=5.0)

    assert calls["count"] == 1
    assert result["success"] is False
    assert result["status"] == "parse_error"
    assert result["reason"] == "json_parse_failed"
    assert result["prefix"] == "FOCUS_RESULT"
    assert result["reqId"] == "focus-2"
    assert "rawSnippet" in result


def test_truncated_focus_result_returns_parse_error_without_retry(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    calls = {"count": 0}
    logs = '01-01 I/A11Y_HELPER: FOCUS_RESULT {"reqId":"focus-3","success":true,"node":{"text":"Energy"'

    def dump_filtered(dev=None):
        calls["count"] += 1
        return logs

    monkeypatch.setattr(client._logcat_reader, "dump_filtered", dump_filtered)

    result = client._read_log_result(None, "FOCUS_RESULT", "focus-3", wait_seconds=5.0)

    assert calls["count"] == 1
    assert result["success"] is False
    assert result["status"] == "parse_error"
    assert result["reason"] == "json_parse_failed"
    assert result["reqId"] == "focus-3"


def test_truncated_focus_result_preserves_package_context(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    logs = (
        '01-01 I/A11Y_HELPER: FOCUS_RESULT '
        '{"reqId":"focus-4","success":true,'
        '"packageName":"com.samsung.android.oneconnect",'
        '"className":"android.widget.FrameLayout",'
        '"mergedLabel":"Energy'
    )

    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: logs)

    result = client._read_log_result(None, "FOCUS_RESULT", "focus-4", wait_seconds=5.0)

    assert result["status"] == "parse_error"
    assert result["packageName"] == "com.samsung.android.oneconnect"
    assert result["className"] == "android.widget.FrameLayout"


def test_get_focus_parse_error_uses_bounded_fallback_reason(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(client, "_has_recent_helper_ok", lambda dev=None: True)
    monkeypatch.setattr(client, "check_helper_status", lambda dev=None: True)
    monkeypatch.setattr(
        client._helper_bridge,
        "_request_get_focus",
        lambda dev, req_id, wait_seconds, poll_interval_sec=0.2: {
            "success": False,
            "status": "parse_error",
            "reason": "json_parse_failed",
            "reqId": req_id,
        },
    )
    monkeypatch.setattr(client, "_run_get_focus_fallback_dump", lambda dev, serial, req_id, started: {})

    result = client.get_focus(wait_seconds=5.0, allow_fallback_dump=True)

    assert result == {}
    assert client.last_get_focus_trace["empty_reason"] == "parse_error"
    assert client.last_get_focus_trace["fallback_reason"] == "parse_error"
    assert client.last_get_focus_trace["final_focus_reason"] == "fallback_dump_not_found"
