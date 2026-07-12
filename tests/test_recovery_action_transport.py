from __future__ import annotations

import json
from types import SimpleNamespace

from talkback_lib import A11yAdbClient


def _event(*, request_id: str, transaction_id: str, success: bool, status: str, detail: str) -> str:
    return "EVIDENCE_HELPER_EVENT " + json.dumps(
        {
            "requestId": request_id,
            "transactionId": transaction_id,
            "eventType": "ACTION_API_RESULT",
            "correlation": {"transaction_id": transaction_id},
            "payload": {
                "success": success,
                "status": status,
                "detail": detail,
                "reason": detail,
                "action": "FOCUS_IN_BOUNDS",
            },
        }
    )


def _client(monkeypatch, log_text: str) -> tuple[A11yAdbClient, list[str]]:
    monkeypatch.setenv("TB_TRAVERSAL_IDENTITY_V2_ENABLED", "1")
    client = A11yAdbClient(start_monitor=False)
    client._evidence_active_transaction = {"transaction_id": "tx-current", "phase": "recovery"}
    client._logcat_reader = SimpleNamespace(dump_filtered=lambda **_kwargs: log_text)
    client._evidence_collect_helper_logcat_events = lambda *_args, **_kwargs: {}
    traces: list[str] = []
    client._safe_trace_print = traces.append
    return client, traces


def test_recovery_ack_parses_bounded_focus_in_bounds_success(monkeypatch):
    client, traces = _client(
        monkeypatch,
        "I/A11Y_HELPER: " + _event(
            request_id="req-1", transaction_id="tx-current", success=True, status="moved", detail="content_like_focused_row"
        ),
    )

    result = client._read_recovery_action_ack("serial", "req-1")

    assert result == {
        "reqId": "req-1",
        "success": True,
        "status": "moved",
        "detail": "content_like_focused_row",
        "reason": "content_like_focused_row",
        "action": "FOCUS_IN_BOUNDS",
        "transportSource": "recovery_evidence_event",
    }
    assert any("matched=true" in trace for trace in traces)


def test_recovery_ack_preserves_helper_failure(monkeypatch):
    client, _ = _client(
        monkeypatch,
        _event(
            request_id="req-1", transaction_id="tx-current", success=False, status="failed", detail="focus_action_failed"
        ),
    )

    result = client._read_recovery_action_ack("serial", "req-1")

    assert result is not None
    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["detail"] == "focus_action_failed"


def test_recovery_ack_rejects_stale_request_and_transaction(monkeypatch):
    client, traces = _client(
        monkeypatch,
        "\n".join(
            [
                _event(request_id="req-1", transaction_id="tx-current", success=True, status="moved", detail="current"),
                _event(request_id="req-old", transaction_id="tx-current", success=True, status="moved", detail="old"),
                _event(request_id="req-1", transaction_id="tx-old", success=True, status="moved", detail="old-tx"),
            ]
        ),
    )

    result = client._read_recovery_action_ack("serial", "req-1")

    assert result is not None
    assert result["detail"] == "current"
    assert any("staleResultRejected=2" in trace for trace in traces)


def test_recovery_ack_does_not_read_transport_when_flag_off(monkeypatch):
    monkeypatch.delenv("TB_TRAVERSAL_IDENTITY_V2_ENABLED", raising=False)
    client = A11yAdbClient(start_monitor=False)
    client._evidence_active_transaction = {"transaction_id": "tx-current", "phase": "recovery"}
    client._logcat_reader = SimpleNamespace(dump_filtered=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected read")))

    assert client._read_recovery_action_ack("serial", "req-1") is None
