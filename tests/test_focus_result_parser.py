from __future__ import annotations

from talkback_lib import A11yAdbClient
from talkback_lib.action_result_parser import ActionResultParser
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


def test_truncated_focus_result_salvages_text_field(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    calls = {"count": 0}
    logs = '01-01 I/A11Y_HELPER: FOCUS_RESULT {"reqId":"focus-3","success":true,"node":{"text":"SmartThings Home Care","className":"android.webkit.WebView"'

    def dump_filtered(dev=None):
        calls["count"] += 1
        return logs

    monkeypatch.setattr(client._logcat_reader, "dump_filtered", dump_filtered)

    result = client._read_log_result(None, "FOCUS_RESULT", "focus-3", wait_seconds=5.0)

    assert calls["count"] == 1
    assert result["success"] is False
    assert result["status"] == "partial_parse_success"
    assert result["partial_parse_success"] is True
    assert result["reason"] == "json_parse_failed"
    assert result["reqId"] == "focus-3"
    assert result["node"]["text"] == "SmartThings Home Care"
    assert result["node"]["className"] == "android.webkit.WebView"


def test_truncated_focus_result_salvages_content_description(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    logs = (
        '01-01 I/A11Y_HELPER: FOCUS_RESULT '
        '{"reqId":"focus-4","success":true,'
        '"packageName":"com.samsung.android.oneconnect",'
        '"className":"android.widget.FrameLayout",'
        '"contentDescription":"Home Care'
    )

    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: logs)

    result = client._read_log_result(None, "FOCUS_RESULT", "focus-4", wait_seconds=5.0)

    assert result["status"] == "partial_parse_success"
    assert result["partial_parse_success"] is True
    assert result["node"]["contentDescription"] == "Home Care"
    assert result["node"]["packageName"] == "com.samsung.android.oneconnect"
    assert result["node"]["className"] == "android.widget.FrameLayout"

def test_truncated_focus_result_without_salvageable_fields_remains_parse_error(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    logs = '01-01 I/A11Y_HELPER: FOCUS_RESULT {"reqId":"focus-5","success":true,"node":{"boundsInScreen"'

    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: logs)

    result = client._read_log_result(None, "FOCUS_RESULT", "focus-5", wait_seconds=5.0)

    assert result["status"] == "parse_error"
    assert "partial_parse_success" not in result
    assert "node" not in result


def test_truncated_focus_result_does_not_mix_child_fields_into_partial_node():
    raw_payload = (
        '{"reqId":"focus-mixed","success":false,"node":{'
        '"text":null,"contentDescription":null,"viewIdResourceName":null,'
        '"className":"android.widget.FrameLayout","children":['
        '{"text":"패밀리 케어"},'
        '{"contentDescription":"상위 메뉴로 이동"},'
        '{"viewIdResourceName":"menu_main_invite_member"}'
    )

    result = ActionResultParser.focus_parse_error_result("focus-mixed", raw_payload, "truncated")

    assert result["partial_parse_success"] is True
    assert result["partial_fields_from_root_only"] is True
    assert result["partial_children_truncated"] is True
    assert result["partial_payload_trusted"] is False
    assert result["node"] == {"className": "android.widget.FrameLayout"}


def test_truncated_focus_result_trusts_complete_root_fields_before_children():
    raw_payload = (
        '{"timestamp":1,"packageName":"com.samsung.android.oneconnect",'
        '"className":"android.webkit.WebView","viewIdResourceName":null,'
        '"text":"SmartThings Home Care","contentDescription":null,'
        '"boundsInScreen":{"l":0,"t":100,"r":1080,"b":2200},'
        '"accessibilityFocused":true,"focused":false,"visibleToUser":true,'
        '"children":[{"text":"truncated child'
    )

    result = ActionResultParser.focus_parse_error_result("focus-webview", raw_payload, "truncated")

    assert result["partial_children_truncated"] is True
    assert result["partial_root_complete"] is True
    assert result["partial_payload_trusted"] is True
    assert result["node"] == {
        "text": "SmartThings Home Care",
        "className": "android.webkit.WebView",
        "packageName": "com.samsung.android.oneconnect",
        "boundsInScreen": {"l": 0, "t": 100, "r": 1080, "b": 2200},
        "accessibilityFocused": True,
        "focused": False,
        "visibleToUser": True,
    }


def test_truncated_focus_result_rejects_incomplete_root_field_before_children():
    raw_payload = (
        '{"text":"SmartThings Home Care","boundsInScreen":'
        '{"l":0,"t":100,"r":1080,"children":[{"text":"child"}'
    )

    result = ActionResultParser.focus_parse_error_result("focus-incomplete", raw_payload, "truncated")

    assert result["partial_root_complete"] is False
    assert result["partial_payload_trusted"] is False


def test_get_focus_rejects_untrusted_partial_payload_and_uses_dump_focus(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(client, "_has_recent_helper_ok", lambda dev=None: True)
    monkeypatch.setattr(client, "check_helper_status", lambda dev=None: True)
    monkeypatch.setattr(
        client._helper_bridge,
        "_request_get_focus",
        lambda dev, req_id, wait_seconds, poll_interval_sec=0.2: {
            "success": False,
            "status": "partial_parse_success",
            "partial_parse_success": True,
            "partial_payload_trusted": False,
            "partial_fields_from_root_only": True,
            "partial_children_truncated": True,
            "node": {
                "text": "패밀리 케어",
                "contentDescription": "상위 메뉴로 이동",
                "viewIdResourceName": "menu_main_invite_member",
            },
        },
    )
    monkeypatch.setattr(
        client,
        "dump_tree",
        lambda dev=None: [
            {
                "contentDescription": "상위 메뉴로 이동",
                "viewIdResourceName": "menu_main_up",
                "accessibilityFocused": True,
                "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 100},
            },
            {"text": "패밀리 케어"},
            {"text": "가족 구성원 추가", "viewIdResourceName": "menu_main_invite_member"},
        ],
    )

    result = client.get_focus(wait_seconds=1.0, allow_fallback_dump=True)

    assert result["contentDescription"] == "상위 메뉴로 이동"
    assert result["viewIdResourceName"] == "menu_main_up"
    assert "text" not in result
    assert client.last_get_focus_trace["untrusted_partial_payload_rejected"] is True
    assert client.last_get_focus_trace["final_payload_source"] == "fallback_dump"
    assert client.last_get_focus_trace["partial_root_evidence"]["text"] == "패밀리 케어"


def test_get_focus_untrusted_partial_without_dump_focus_returns_empty(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(client, "_has_recent_helper_ok", lambda dev=None: True)
    monkeypatch.setattr(client, "check_helper_status", lambda dev=None: True)
    monkeypatch.setattr(
        client._helper_bridge,
        "_request_get_focus",
        lambda dev, req_id, wait_seconds, poll_interval_sec=0.2: {
            "success": False,
            "status": "partial_parse_success",
            "partial_parse_success": True,
            "partial_payload_trusted": False,
            "node": {"text": "패밀리 케어"},
        },
    )
    monkeypatch.setattr(client, "dump_tree", lambda dev=None: [])

    assert client.get_focus(wait_seconds=1.0, allow_fallback_dump=True) == {}
    assert client.last_get_focus_trace["empty_reason"] == "untrusted_partial_payload"
    assert client.last_get_focus_trace["final_focus_reason"] == "fallback_dump_not_found"


def test_complete_bounded_partial_focus_payload_remains_usable():
    raw_payload = (
        '{"reqId":"focus-trusted","success":false,"node":{'
        '"text":"Energy","boundsInScreen":{"l":1,"t":2,"r":30,"b":40}}'
    )

    result = ActionResultParser.focus_parse_error_result("focus-trusted", raw_payload, "truncated")

    assert result["partial_parse_success"] is True
    assert result["partial_root_complete"] is True
    assert result["partial_payload_trusted"] is True
    assert result["node"]["text"] == "Energy"
    assert result["node"]["boundsInScreen"] == {"l": 1, "t": 2, "r": 30, "b": 40}


def test_get_focus_accepts_trusted_complete_partial_payload_without_dump(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(client, "_has_recent_helper_ok", lambda dev=None: True)
    monkeypatch.setattr(client, "check_helper_status", lambda dev=None: True)
    monkeypatch.setattr(
        client._helper_bridge,
        "_request_get_focus",
        lambda dev, req_id, wait_seconds, poll_interval_sec=0.2: {
            "success": False,
            "status": "partial_parse_success",
            "partial_parse_success": True,
            "partial_payload_trusted": True,
            "node": {
                "text": "Energy",
                "boundsInScreen": {"l": 1, "t": 2, "r": 30, "b": 40},
            },
        },
    )
    dump_called = {"value": False}
    monkeypatch.setattr(client, "dump_tree", lambda dev=None: dump_called.update(value=True) or [])

    result = client.get_focus(wait_seconds=1.0, allow_fallback_dump=True)

    assert result["text"] == "Energy"
    assert dump_called["value"] is False
    assert client.last_get_focus_trace["final_focus_reason"] == "accepted_meaningful_payload"


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
