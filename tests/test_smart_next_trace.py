from __future__ import annotations

from unittest.mock import patch

import pytest

from talkback_lib import ACTION_SMART_NEXT, A11yAdbClient


class _TraceSafeClient(A11yAdbClient):
    def __init__(self) -> None:
        super().__init__(adb_path="adb", package_name="com.example.custom", start_monitor=False)
        self.broadcast_calls: list[tuple[object, list[str]]] = []
        self.move_focus_calls: list[tuple[object, str]] = []
        self.read_log_result_payload = {"success": True, "status": "moved", "detail": ""}
        self.helper_ready = True

    def _has_recent_helper_ok(self, dev=None):  # pylint: disable=unused-argument
        return self.helper_ready

    def check_helper_status(self, dev=None):  # pylint: disable=unused-argument
        return self.helper_ready

    def _broadcast(self, dev, action: str, extras=None):
        extras_list = list(extras or [])
        self.broadcast_calls.append((dev, [action, *extras_list]))
        return "broadcast ok"

    def _read_log_result(self, dev, prefix, req_id, wait_seconds=3.0, poll_interval_sec=0.2):  # noqa: ARG002
        return dict(self.read_log_result_payload)

    def move_focus(self, dev=None, direction: str = "next"):
        self.move_focus_calls.append((dev, direction))
        return True


def test_move_focus_smart_does_not_abort_when_trace_print_raises_oserror():
    client = _TraceSafeClient()

    with patch("builtins.print", side_effect=OSError(22, "Invalid argument")):
        result = client.move_focus_smart("SER", direction="next")

    assert result["success"] is True
    assert result["status"] == "moved"
    assert client.last_smart_nav_result["status"] == "moved"
    assert any(call[1][0] == ACTION_SMART_NEXT for call in client.broadcast_calls)


def test_request_smart_next_does_not_abort_when_trace_print_raises_oserror():
    client = _TraceSafeClient()

    with patch("builtins.print", side_effect=OSError(22, "Invalid argument")):
        result = client._helper_bridge._request_smart_next("SER", req_id="REQ12345")

    assert result["success"] is True
    assert any(call[1][0] == ACTION_SMART_NEXT for call in client.broadcast_calls)


def test_move_focus_smart_non_print_exceptions_still_propagate():
    client = _TraceSafeClient()

    with patch.object(client._helper_bridge, "_request_smart_next", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            client.move_focus_smart("SER", direction="next")


def test_request_smart_next_non_print_exceptions_still_propagate():
    client = _TraceSafeClient()

    with patch.object(client, "_broadcast", side_effect=RuntimeError("broadcast failed")):
        with pytest.raises(RuntimeError, match="broadcast failed"):
            client._helper_bridge._request_smart_next("SER", req_id="REQ12345")
