from tb_runner.entry_safety import (
    _entry_capture_request,
    _event_in_uptime_window,
    dispatch_authorized_entry_tap,
)


class RecordingClient:
    def __init__(self, stdout):
        self.stdout = stdout
        self.calls = []

    def _run(self, args, dev=None, timeout=None):
        self.calls.append((list(args), dev, timeout))
        return self.stdout


def test_dispatch_uses_single_remote_shell_argument_and_keeps_uptime_cursor():
    client = RecordingClient("123.45 678.90\n")

    receipt = dispatch_authorized_entry_tap(client, "SERIAL", (25, 38))

    assert client.calls == [(["shell", "cat /proc/uptime; input tap 25 38"], "SERIAL", 10.0)]
    assert receipt["executed"] is True
    assert receipt["dispatch_uptime_ms"] == 123450
    assert receipt["dispatch_cursor_available"] is True
    assert receipt["reason"] == "DISPATCHED_WITH_DEVICE_UPTIME_CURSOR"


def test_end_capture_accepts_the_requested_transaction_after_disarm():
    class CaptureClient:
        def _broadcast(self, dev, action, extras):
            self.broadcast_args = (dev, action, list(extras))

        def _read_log_result(self, dev, prefix, response_req_id, **_kwargs):
            return {
                "reqId": response_req_id,
                "transactionId": "",
                "requestedTransactionId": "tx-1",
                "captureReqId": "capture-1",
                "operation": "end",
                "active": False,
                "ok": True,
                "reason": "DISARMED",
                "evidenceEvents": [],
            }

    result = _entry_capture_request(
        CaptureClient(), "SERIAL", req_id="capture-1", transaction_id="tx-1", operation="end"
    )

    assert result["ok"] is True
    assert result["transactionId"] == ""
    assert result["requestedTransactionId"] == "tx-1"
    assert result["responseReqId"].startswith("capture-1_end_")


def test_end_capture_accepts_matching_nonempty_transaction_id_after_disarm():
    class CaptureClient:
        def _broadcast(self, dev, action, extras):
            pass

        def _read_log_result(self, dev, prefix, response_req_id, **_kwargs):
            return {
                "reqId": response_req_id,
                "transactionId": "tx-1",
                "requestedTransactionId": "tx-1",
                "captureReqId": "capture-1",
                "operation": "end",
                "active": False,
                "ok": True,
                "reason": "DISARMED",
            }

    result = _entry_capture_request(
        CaptureClient(), "SERIAL", req_id="capture-1", transaction_id="tx-1", operation="end"
    )

    assert result["ok"] is True
    assert result["transactionId"] == "tx-1"


def test_end_capture_rejects_mismatched_returned_transaction_id():
    class CaptureClient:
        def _broadcast(self, dev, action, extras):
            pass

        def _read_log_result(self, dev, prefix, response_req_id, **_kwargs):
            return {
                "reqId": response_req_id,
                "transactionId": "stale-tx",
                "requestedTransactionId": "tx-1",
                "captureReqId": "capture-1",
                "operation": "end",
                "active": False,
                "ok": True,
            }

    result = _entry_capture_request(
        CaptureClient(), "SERIAL", req_id="capture-1", transaction_id="tx-1", operation="end"
    )

    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_TRANSACTION_MISMATCH"


def test_end_capture_rejects_stale_response_request_id():
    class CaptureClient:
        def _broadcast(self, dev, action, extras):
            pass

        def _read_log_result(self, dev, prefix, response_req_id, **_kwargs):
            return {
                "reqId": "old-response-id",
                "transactionId": "tx-1",
                "requestedTransactionId": "tx-1",
                "captureReqId": "capture-1",
                "operation": "end",
                "active": False,
                "ok": True,
            }

    result = _entry_capture_request(
        CaptureClient(), "SERIAL", req_id="capture-1", transaction_id="tx-1", operation="end"
    )

    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_RESPONSE_REQUEST_MISMATCH"


def test_end_capture_rejects_still_active_response():
    class CaptureClient:
        def _broadcast(self, dev, action, extras):
            pass

        def _read_log_result(self, dev, prefix, response_req_id, **_kwargs):
            return {
                "reqId": response_req_id,
                "transactionId": "tx-1",
                "requestedTransactionId": "tx-1",
                "captureReqId": "capture-1",
                "operation": "end",
                "active": True,
                "ok": True,
            }

    result = _entry_capture_request(
        CaptureClient(), "SERIAL", req_id="capture-1", transaction_id="tx-1", operation="end"
    )

    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_TRANSACTION_MISMATCH"

def test_end_capture_still_rejects_a_mismatched_requested_transaction():
    class CaptureClient:
        def _broadcast(self, dev, action, extras):
            pass

        def _read_log_result(self, dev, prefix, response_req_id, **_kwargs):
            return {
                "reqId": response_req_id,
                "transactionId": "",
                "requestedTransactionId": "wrong-tx",
                "captureReqId": "capture-1",
                "operation": "end",
                "active": False,
                "ok": True,
                "reason": "DISARMED",
            }

    result = _entry_capture_request(
        CaptureClient(), "SERIAL", req_id="capture-1", transaction_id="tx-1", operation="end"
    )

    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_TRANSACTION_MISMATCH"


def test_dispatch_window_uses_helper_elapsed_capture_clock_not_event_uptime():
    event = {
        "event_time": "3063818777",
        "event_ingestion_elapsed_realtime_ms": 3161695066,
    }

    assert _event_in_uptime_window(event, 3161694860, 3161695860) is True
    assert _event_in_uptime_window(
        {**event, "event_ingestion_elapsed_realtime_ms": 3161694800},
        3161694860,
        3161695860,
    ) is False
    assert _event_in_uptime_window({"event_time": "3161695066"}, 3161694860, 3161695860) is False
