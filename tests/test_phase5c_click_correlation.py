"""Regression tests for transaction-scoped Phase 5C click evidence."""
from __future__ import annotations

from copy import deepcopy
import base64
import json
import re
import pytest

from tb_runner import entry_safety
from talkback_lib import A11yAdbClient
from talkback_lib.adb_device import AdbCommandFailure


PACKAGE = "com.samsung.android.oneconnect"
TRANSACTION = "tx-home-monitor"
_BASE_ENTRY_SAFETY_CONFIG = entry_safety.default_config


@pytest.fixture(autouse=True)
def explicit_read_only_effect_for_positive_harness_cases(monkeypatch):
    def test_config():
        config = deepcopy(_BASE_ENTRY_SAFETY_CONFIG())
        config.setdefault("metadata_rules", []).append({
            "match": {"resource_id": ".*", "context_kind": "plugin_entry"},
            "effect": "read_only_navigation",
        })
        return config
    monkeypatch.setattr(entry_safety, "default_config", test_config)


def node(rid, label, bounds, *, klass="android.view.ViewGroup", clickable=False, children=None):
    return dict(viewIdResourceName=rid, className=klass, text="", contentDescription=label,
                boundsInScreen=bounds, clickable=clickable, focusable=clickable,
                enabled=True, sourceNodeId=f"stable:{rid}" if rid else None,
                windowId=4, children=children or [])


def owned_tree():
    owner = node("app:id/monitorHeaderGroup", "Home Monitor", "[30,1421][1050,1469]", clickable=True)
    owner.update(role="button", actions=[16])
    child = node("app:id/awayButton", "Armed Stay", "[50,1500][300,1600]", clickable=True,
                 klass="android.widget.Button")
    card = node("app:id/monitorCard", "Home Monitor", "[20,1400][1060,1700]", clickable=True,
                children=[owner, child])
    card.update(role="button", actions=[16])
    return [card], owner, child


def permit_for(roots, owner):
    # Entry discovery starts from the card candidate and resolves its semantic
    # descendant as the actual navigation owner.
    resolution = entry_safety.resolve_navigation_owner(roots, roots[0], "Home Monitor")
    assert resolution.get("owner") is owner
    permit = entry_safety.authorize_entry(resolution, roots, scenario="life_home_monitor_plugin",
                                          matched_phrase="Home Monitor")
    assert permit["authorized"]
    return permit


def exact_authority_case(*, source_node_id="target-node", anchor_label="Air Care"):
    roots, owner, _child = owned_tree()
    owner.update(sourceNodeId="target-node", windowId=4)
    permit = permit_for(roots, owner)
    transaction_id = permit["transaction_id"]
    click = dict(
        event_id="click-event-1", event_time="10100", event_ingestion_elapsed_realtime_ms=10100,
        dispatch_uptime_ms=10000, package=PACKAGE, source_status="FIELD_PRESENT",
        source_node_id=source_node_id, transaction_id=transaction_id, request_id="req-1",
        capture_id="capture-1", connection_id="connection-1",
        source=dict(source_node_id=source_node_id, window_id=4),
    )
    focus_node = dict(sourceNodeId="focus-anchor", windowId=9, accessibilityFocused=True,
                      text=anchor_label, contentDescription="", viewIdResourceName="app:id/airCareTitle",
                      children=[])
    post = dict(
        event_id="post-event-1", request_id="req-1", transaction_id=transaction_id,
        capture_id="capture-1", connection_id="connection-1", source_click_event_id="click-event-1",
        dispatch_uptime_ms=10000, source_click_captured_elapsed_realtime_ms=10100,
        captured_elapsed_realtime_ms=10300, current_capture_id="post-capture-1",
        root_window_id=9, focus_node_id="focus-anchor", focus_window_id=9,
        accessibility_focused=True, current_hierarchy=focus_node,
    )
    collection = dict(
        req_id="req-1", transaction_id=transaction_id, capture_id="capture-1",
        connection_id="connection-1", deadline_uptime_ms=11000, post_action_observations=[post],
    )
    patterns = dict(anchor_text="Air Care", anchor_resource="", context_text="")
    return roots, owner, permit, click, collection, patterns


def helper_event(req_id, event_id, event_time, *, transaction=TRANSACTION, rid="app:id/monitorHeaderGroup",
                 klass="android.view.ViewGroup", text="", description="Home Monitor", package=PACKAGE,
                 captured_elapsed_realtime_ms=None):
    return dict(eventId=event_id, eventType="ENTRY_CLICK_OBSERVED", reqId=req_id,
                correlation={"transaction_id": transaction},
                timestamp=int(event_time) + 100,
                payload=dict(event_time_uptime_ms=event_time, event_type="TYPE_VIEW_CLICKED",
                             package=package, class_name=klass, text=text or None,
                             content_description=description,
                             source_status="FIELD_PRESENT" if rid else "FIELD_ABSENT",
                             source_node_id=None, source_process_id=None,
                             parser_source="helper_accessibility_event",
                             raw_reference=f"{req_id}:{event_time}",
                             captured_elapsed_realtime_ms=(
                                 int(event_time) + 1 if captured_elapsed_realtime_ms is None
                                 else int(captured_elapsed_realtime_ms)
                             ),
                             cursor_event_sequence=0,
                             source=(dict(resource_id=rid, class_name=klass, text=text or None,
                                          content_description=description, bounds=None,
                                          window_id=None, enabled=True, clickable=True, focusable=True)
                                     if rid or klass or description else None),
                             field_status={"resource_id": "FIELD_PRESENT" if rid else "FIELD_ABSENT"}))


class FakeClock:
    def __init__(self, start=100.0):
        self.value = start

    def monotonic(self):
        return self.value

    def monotonic_ns(self):
        return int(self.value * 1_000_000_000)

    def sleep(self, seconds):
        self.value += max(0.0, float(seconds))


class CaptureClient:
    def __init__(self, *, appear_at_poll=None, event_time=10100, events=None, stale_owner=False,
                 captured_elapsed_realtime_ms=None):
        self.clock = None
        self.appear_at_poll = appear_at_poll
        self.event_time = event_time
        self.captured_elapsed_realtime_ms = captured_elapsed_realtime_ms
        self.events = list(events or [])
        self.stale_owner = stale_owner
        self.operations = []
        self.snapshot_count = 0
        self.active_capture_id = ""
        self.transaction_id = TRANSACTION
        self.rpc_responses = {}

    def _broadcast(self, dev, action, extras):
        values = {}
        for index in range(0, len(extras), 3):
            values[extras[index + 1]] = extras[index + 2]
        operation = values.get("operation")
        response_id = values.get("reqId")
        capture_id = values.get("captureReqId", response_id)
        self.operations.append((operation, response_id, capture_id))
        self.active_capture_id = capture_id
        self.transaction_id = values.get("transactionId", TRANSACTION)
        self.rpc_responses[response_id] = operation
        return f"Broadcasting: Intent {{ act={action} }}\nBroadcast completed: result=0"

    def _read_log_result(self, dev, prefix, req_id, **_kwargs):
        operation = self.rpc_responses[req_id]
        rows = list(self.events)
        if operation == "snapshot":
            self.snapshot_count += 1
            if isinstance(self.appear_at_poll, int) and self.snapshot_count >= self.appear_at_poll and not rows:
                req_id_owner = "stale-owner" if self.stale_owner else self.active_capture_id
                rows.append(helper_event(req_id_owner, "event-1", self.event_time,
                                         transaction=self.transaction_id,
                                         captured_elapsed_realtime_ms=self.captured_elapsed_realtime_ms))
                self.events = list(rows)
        if operation == "end" and not rows and self.appear_at_poll == "end":
            rows.append(helper_event(self.active_capture_id, "late-event", self.event_time,
                                     transaction=self.transaction_id))
            self.events = list(rows)
        return dict(ok=True, operation=operation, transactionId=("" if operation == "end" else self.transaction_id),
                    requestedTransactionId=self.transaction_id, active=(operation != "end"),
                    reqId=req_id, captureReqId=self.active_capture_id, cursorEventSequence=0,
                    evidenceEvents=rows)

    def _run(self, args, *, dev=None, timeout=2.0):
        return ""


def run_collection(monkeypatch, client, *, window_ms=300, dispatch_uptime_ms=10000):
    clock = FakeClock()
    client.clock = clock
    monkeypatch.setattr(entry_safety.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(entry_safety.time, "monotonic_ns", clock.monotonic_ns)
    monkeypatch.setattr(entry_safety.time, "sleep", clock.sleep)
    capture = dict(req_id="capture-owner", transaction_id=TRANSACTION,
                   armed={"ok": True, "reason": "ARMED"}, cursor_started_monotonic_ns=clock.monotonic_ns())
    roots, owner, _child = owned_tree()
    permit = permit_for(roots, owner)
    permit["transaction_id"] = TRANSACTION
    permit["dispatch_uptime_ms"] = dispatch_uptime_ms
    result = entry_safety.collect_transaction_click_events(
        client, "SERIAL", transaction_id=TRANSACTION, hierarchy_roots=roots,
        permit=permit, capture_session=capture, window_ms=window_ms,
        poll_interval_ms=100, dispatch_started_monotonic_ns=clock.monotonic_ns(),
    )
    return roots, permit, result, clock


def test_helper_capture_uses_fresh_rpc_request_id_per_operation():
    class Client:
        calls = []
        def _broadcast(self, _dev, _action, extras):
            values = {}
            for index in range(0, len(extras), 3):
                values[extras[index + 1]] = extras[index + 2]
            self.calls.append(values)
        def _read_log_result(self, _dev, _prefix, req_id, **_kwargs):
            call = next(row for row in reversed(self.calls) if row.get("reqId") == req_id)
            return dict(ok=True, transactionId=("" if call["operation"] == "end" else TRANSACTION),
                        requestedTransactionId=TRANSACTION, active=(call["operation"] != "end"),
                        operation=call["operation"], reqId=call["reqId"],
                        captureReqId=call["captureReqId"], evidenceEvents=[])

    client = Client()
    begin = entry_safety._entry_capture_request(client, "SERIAL", req_id="owner",
        transaction_id=TRANSACTION, operation="begin")
    snapshot = entry_safety._entry_capture_request(client, "SERIAL", req_id="owner",
        transaction_id=TRANSACTION, operation="snapshot")
    assert begin["ok"] and snapshot["ok"]
    assert begin["responseReqId"] != snapshot["responseReqId"]
    assert client.calls[0]["captureReqId"] == client.calls[1]["captureReqId"] == "owner"
    assert begin["reqId"] == begin["responseReqId"]
    assert client.calls[0]["operation"] == "begin"
    assert client.calls[0]["reqId"] == begin["responseReqId"]
    assert client.calls[0]["transactionId"] == TRANSACTION


def test_entry_capture_broadcast_failure_is_reported_without_reading_or_authority():
    class Client:
        read_calls = 0
        def _broadcast(self, *_args):
            error = RuntimeError("adb_command_failed")
            error.reason = "adb_command_failed"
            raise error
        def _read_log_result(self, *_args, **_kwargs):
            self.read_calls += 1
            pytest.fail("response reader must not run after failed broadcast")

    client = Client()
    result = entry_safety._entry_capture_request(client, "SERIAL", req_id="owner",
        transaction_id=TRANSACTION, operation="begin")
    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_BROADCAST_FAILED"
    assert result["stage"] == "broadcast"
    assert result["responseReqId"].startswith("owner_begin_")
    assert "ownerLeaseId" not in result and "captureId" not in result
    assert client.read_calls == 0


def test_entry_capture_adb_broadcast_uses_raise_on_delivery_failure(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    observed = {}
    def run_adb(_cmd, *, dev=None, timeout=None, raise_on_failure=False):
        observed["raise_on_failure"] = raise_on_failure
        raise AdbCommandFailure("adb_command_failed", ["adb", "shell", "am", "broadcast"], 3.0,
                                stderr="receiver delivery failed")
    monkeypatch.setattr(client._adb_device, "_run_adb_command", run_adb)

    result = entry_safety._entry_capture_request(client, "SERIAL", req_id="owner",
        transaction_id=TRANSACTION, operation="begin")

    assert observed["raise_on_failure"] is True
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_BROADCAST_FAILED"
    assert result["stage"] == "broadcast"
    assert result["broadcastError"] == "adb_command_failed"
    assert result["responseReqId"].startswith("owner_begin_")


def test_canonical_invocation_uri_reaches_adb_broadcast_argument_vector(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    observed = {}

    def run_adb(args, *, dev=None, timeout=None, raise_on_failure=False):
        observed["args"] = list(args)
        observed["raise_on_failure"] = raise_on_failure
        return "Broadcasting: Intent { dat=invocation_id:scenario-current }\nBroadcast completed: result=0"

    monkeypatch.setattr(client._adb_device, "_run_adb_command", run_adb)
    uri = "invocation_id:scenario-current"
    output = client._broadcast("SERIAL", entry_safety.ENTRY_CLICK_CAPTURE_ACTION,
                               ["-d", uri, "--es", "evidenceTransactionId", TRANSACTION])
    assert output.endswith("result=0")
    assert observed["args"][observed["args"].index("-d") + 1] == uri
    assert observed["raise_on_failure"] is True


def test_correlated_helper_begin_rejection_preserves_reason_without_lease_fields():
    class Client:
        def _broadcast(self, *_args):
            return "Broadcast completed: result=0"
        def _read_log_result(self, _dev, _prefix, req_id, **_kwargs):
            return {"reqId": req_id, "ok": False, "reason": "OBSERVATION_TARGET_STALE",
                    "operation": "begin", "requestedTransactionId": TRANSACTION,
                    "captureReqId": "owner"}

    result = entry_safety._entry_capture_request(Client(), "SERIAL", req_id="owner",
        transaction_id=TRANSACTION, operation="begin")
    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_HELPER_REJECTED:OBSERVATION_TARGET_STALE"
    assert result["helperReason"] == "OBSERVATION_TARGET_STALE"
    assert "ownerLeaseId" not in result and "captureId" not in result
    assert result["responseReqId"].startswith("owner_begin_")


def test_owner_lease_rejection_retains_only_redacted_live_node_diagnostics(capsys):
    diagnostic = {
        "stage": "live_node_actionability", "code": "OBSERVATION_TARGET_NOT_ACTIONABLE",
        "request_id": "owner-request", "transaction_id": TRANSACTION,
        "expected_path": [0, 1, 4], "expected_window_id": 26,
        "expected_package": PACKAGE, "expected_descriptor_digest": "a" * 64,
        "expected_source_node_id_status": "FIELD_ABSENT",
        "source_capture_request_id": "capture-request", "source_process_epoch": "process-epoch",
        "source_generation": 12, "source_service_instance_id": "service-id",
        "source_capture_sequence": 3, "source_connection_epoch": "connection-epoch",
        "source_boot_epoch": "boot-epoch", "source_root_digest": "b" * 64,
        "source_candidate_digest": "c" * 64, "source_capture_key": "d" * 64,
        "current_service_instance_id": "service-id", "current_process_epoch": "process-epoch",
        "current_generation": 12, "current_capture_sequence": 3,
        "current_connection_epoch": "connection-epoch", "current_boot_epoch": "boot-epoch",
        "currentness": {"source_capture_current": True, "generation_matches": True,
                        "capture_sequence_matches": True, "unexpected": "PRIVATE"},
        "actual_live_node": {"package_name": PACKAGE, "class_name": "android.widget.RelativeLayout",
                             "resource_id": "com.samsung:id/containerNameLayout", "window_id": 26,
                             "visible": True, "enabled": True, "clickable": False,
                             "action_click": False, "text": "PRIVATE LABEL",
                             "content_description": "PRIVATE DESCRIPTION"},
        "unexpected": "PRIVATE",
    }

    class Client:
        def __init__(self):
            self.capture_req_id = None

        def _broadcast(self, _dev, _action, extras):
            self.capture_req_id = extras[extras.index("captureReqId") + 1]
            return "Broadcast completed: result=0"

        def _read_log_result(self, _dev, _prefix, req_id, **_kwargs):
            return {"reqId": req_id, "ok": False,
                    "reason": "OBSERVATION_TARGET_NOT_ACTIONABLE", "operation": "begin",
                    "requestedTransactionId": TRANSACTION,
                    "captureReqId": self.capture_req_id, "diagnostics": diagnostic,
                    "ownerLeaseId": "must-not-be-returned"}

    client = Client()
    capture = entry_safety.begin_transaction_click_capture(
        client, "SERIAL", transaction_id=TRANSACTION,
        target_node={"_helperNodePath": [0, 1, 4], "_helperNodeDescriptorDigest": "a" * 64,
                     "_helperSourceSnapshotId": "snapshot", "windowId": 26,
                     "packageName": PACKAGE},
        scenario_id="life_air_care_plugin", include_talkback_baseline=False)

    armed = capture["armed"]
    assert armed["ok"] is False
    assert armed["reason"] == "ENTRY_CLICK_CAPTURE_HELPER_REJECTED:OBSERVATION_TARGET_NOT_ACTIONABLE"
    assert armed["captureReqId"] == capture["req_id"]
    assert armed["requestedTransactionId"] == TRANSACTION
    assert armed["helperDiagnostics"]["request_id"] == "owner-request"
    assert armed["helperDiagnostics"]["transaction_id"] == TRANSACTION
    assert armed["helperDiagnostics"]["expected_path"] == [0, 1, 4]
    assert armed["helperDiagnostics"]["actual_live_node"]["class_name"] == "android.widget.RelativeLayout"
    assert armed["helperDiagnostics"]["actual_live_node"]["clickable"] is False
    assert armed["helperDiagnostics"]["currentness"]["generation_matches"] is True
    assert "ownerLeaseId" not in armed and "captureId" not in armed
    assert "text" not in armed["helperDiagnostics"]["actual_live_node"]
    assert "content_description" not in armed["helperDiagnostics"]["actual_live_node"]
    assert "unexpected" not in armed["helperDiagnostics"]
    assert "PRIVATE LABEL" not in capsys.readouterr().out


def test_entry_capture_nonzero_am_broadcast_result_is_rejected_before_result_read():
    class Client:
        def _broadcast(self, _dev, action, _extras):
            return f"Broadcasting: Intent {{ act={action} }}\nBroadcast completed: result=-1"
        def _read_log_result(self, *_args, **_kwargs):
            pytest.fail("Helper response cannot grant authority after rejected broadcast")

    result = entry_safety._entry_capture_request(Client(), "SERIAL", req_id="owner",
        transaction_id=TRANSACTION, operation="begin")
    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_BROADCAST_REJECTED"
    assert result["stage"] == "broadcast"
    assert result["broadcastDiagnostics"] == {
        "status": "REJECTED", "resultCode": -1,
        "output": "Broadcasting: Intent { act=com.iotpart.sqe.talkbackhelper.ENTRY_CLICK_CAPTURE } Broadcast completed: result=-1",
    }
    assert "ownerLeaseId" not in result


def test_entry_capture_missing_begin_persists_bounded_broadcast_stdout(capsys):
    class Client:
        def _broadcast(self, _dev, _action, _extras):
            return "Broadcasting: Intent { act=ENTRY_CLICK_CAPTURE }\nBroadcast completed: result=0"
        def _read_log_result(self, _dev, _prefix, req_id, **_kwargs):
            return {"success": False, "reason": "result_missing", "reqId": req_id}

    result = entry_safety._entry_capture_request(
        Client(), "SERIAL", req_id="owner", transaction_id=TRANSACTION,
        operation="begin", wait_seconds=0.25)
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_RESULT_UNAVAILABLE"
    output = capsys.readouterr().out
    assert "operation=begin stage=broadcast status=COMPLETED resultCode=0" in output
    assert 'stdout="Broadcasting: Intent { act=ENTRY_CLICK_CAPTURE } Broadcast completed: result=0"' in output


def test_canonical_begin_binds_nonempty_invocation_uri_to_owner_lease():
    invocation_id = "scenario-transaction-current"
    owner_lease_request = {
        "run_id": "run-current", "invocation_id": invocation_id,
        "scenario_id": "life_air_care_plugin", "request_id": "owner",
        "transaction_id": TRANSACTION,
        "source_snapshot_id": "snapshot-current", "window_id": 45534,
        "package": PACKAGE, "node_path": [0, 1, 2],
        "descriptor_digest": "a" * 64,
    }

    class Client:
        def __init__(self):
            self.extras = None

        def _broadcast(self, _dev, _action, extras):
            self.extras = list(extras)
            return ("Broadcasting: Intent { act=ENTRY_CLICK_CAPTURE dat=invocation_id: flg=0x400000 }\n"
                    "Broadcast completed: result=0")

        def _read_log_result(self, _dev, _prefix, req_id, **_kwargs):
            return {"reqId": req_id, "captureReqId": "owner", "requestedTransactionId": TRANSACTION,
                    "transactionId": TRANSACTION, "operation": "begin", "ok": True, "active": True,
                    "invocationUriBound": True, "invocationId": invocation_id}

    client = Client()
    result = entry_safety._entry_capture_request(
        client, "SERIAL", req_id="owner", transaction_id=TRANSACTION, operation="begin",
        owner_lease_request=owner_lease_request, invocation_id=invocation_id)
    assert result["ok"] is True
    assert client.extras[client.extras.index("-d") + 1] == f"invocation_id:{invocation_id}"
    assert client.extras[client.extras.index("canonicalInvocation") + 1] == "true"
    assert "ownerLeaseRequest" not in client.extras
    encoded_owner = client.extras[client.extras.index("ownerLeaseRequestBase64") + 1]
    assert re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", encoded_owner)
    decoded_owner = json.loads(base64.urlsafe_b64decode(encoded_owner).decode("utf-8"))
    assert decoded_owner == owner_lease_request


def test_canonical_begin_rejects_missing_owner_lease_request_before_broadcast():
    class Client:
        def _broadcast(self, *_args):
            pytest.fail("canonical begin must not dispatch without its current owner request")

        def _read_log_result(self, *_args, **_kwargs):
            pytest.fail("no Helper response should be read without a dispatched owner request")

    result = entry_safety._entry_capture_request(
        Client(), "SERIAL", req_id="owner", transaction_id=TRANSACTION, operation="begin",
        owner_lease_request=None, invocation_id="scenario-current")
    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_OWNER_LEASE_REQUEST_MISSING"
    assert result["stage"] == "request"


@pytest.mark.parametrize("owner_invocation,selected_invocation", [
    ("", "scenario-current"),
    ("scenario-stale", "scenario-current"),
])
def test_canonical_begin_rejects_empty_or_mismatched_invocation_before_result_read(
        owner_invocation, selected_invocation):
    class Client:
        read_calls = 0

        def _broadcast(self, *_args):
            pytest.fail("invalid owner invocation must be rejected before broadcast")

        def _read_log_result(self, *_args, **_kwargs):
            self.read_calls += 1
            pytest.fail("mismatched invocation URI must fail before reading a Helper response")

    client = Client()
    result = entry_safety._entry_capture_request(
        client, "SERIAL", req_id="owner", transaction_id=TRANSACTION, operation="begin",
        owner_lease_request={"invocation_id": owner_invocation}, invocation_id=selected_invocation)
    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_INVOCATION_IDENTITY_INVALID"
    assert client.read_calls == 0


def test_canonical_begin_requires_helper_receipt_to_bind_invocation():
    class Client:
        read_calls = 0

        def _broadcast(self, *_args):
            # Android's Intent.toString redacts the opaque URI payload.
            return "Broadcasting: Intent { dat=invocation_id: }\nBroadcast completed: result=0"

        def _read_log_result(self, _dev, _prefix, req_id, **_kwargs):
            self.read_calls += 1
            return {"reqId": req_id, "captureReqId": "owner", "requestedTransactionId": TRANSACTION,
                    "transactionId": TRANSACTION, "operation": "begin", "ok": True, "active": True,
                    "invocationUriBound": False, "invocationId": ""}

    client = Client()
    result = entry_safety._entry_capture_request(
        client, "SERIAL", req_id="owner", transaction_id=TRANSACTION, operation="begin",
        owner_lease_request={"invocation_id": "scenario-current"}, invocation_id="scenario-current")
    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_INVOCATION_BINDING_UNPROVEN"
    assert client.read_calls == 1


def test_stale_helper_operation_response_is_rejected():
    class Client:
        def _broadcast(self, *_args):
            pass
        def _read_log_result(self, _dev, _prefix, req_id, **_kwargs):
            return dict(ok=True, reqId=req_id, transactionId=TRANSACTION, requestedTransactionId=TRANSACTION,
                        captureReqId="owner", active=True, operation="begin", evidenceEvents=[])

    result = entry_safety._entry_capture_request(Client(), "SERIAL", req_id="owner",
        transaction_id=TRANSACTION, operation="snapshot")
    assert result["ok"] is False
    assert result["reason"] == "ENTRY_CLICK_CAPTURE_OPERATION_RESPONSE_MISMATCH"


def test_delayed_helper_click_inside_bounded_window_is_captured(monkeypatch):
    client = CaptureClient(appear_at_poll=2, event_time=10150)
    roots, permit, collection, clock = run_collection(monkeypatch, client)
    assert collection["ok"] is True
    assert len(collection["candidate_events"]) == 1
    assert collection["candidate_events"][0]["correlation_status"] == "IN_TRANSACTION_WINDOW"
    assert clock.value <= 100.31
    hit = entry_safety.verify_actual_hit(permit, {}, collection["candidate_events"], roots=roots,
        dispatch_uptime_ms=10000, collection=collection)
    assert hit["matched"] is False
    assert hit["reason"] == "ACTIVATED_SOURCE_IDENTITY_UNPROVEN"


def test_event_after_deadline_is_collected_as_stale_but_rejected(monkeypatch):
    client = CaptureClient(appear_at_poll="end", event_time=10400)
    roots, permit, collection, _clock = run_collection(monkeypatch, client, window_ms=300)
    assert collection["ok"] is True
    assert collection["candidate_events"] == []
    assert len(collection["stale_events"]) == 1
    assert collection["stale_events"][0]["correlation_status"] == "OUTSIDE_TRANSACTION_WINDOW"
    assert not entry_safety.verify_actual_hit(permit, {}, collection["candidate_events"], roots=roots,
        dispatch_uptime_ms=10000, collection=collection)["matched"]


def test_no_event_before_deadline_fails_closed_and_polling_is_bounded(monkeypatch):
    client = CaptureClient()
    roots, permit, collection, clock = run_collection(monkeypatch, client, window_ms=300)
    assert collection["candidate_events"] == []
    assert len(collection["polls"]) <= 4
    assert clock.value <= 100.31
    result = entry_safety.verify_actual_hit(permit, {}, [], roots=roots,
        dispatch_uptime_ms=10000, collection=collection)
    assert result["matched"] is False and result["evidence_strength"] == "INSUFFICIENT"


def test_competing_click_events_in_window_are_ambiguous(monkeypatch):
    client = CaptureClient(appear_at_poll=1, event_time=10100)
    roots, permit, _collection, _clock = run_collection(monkeypatch, client)
    client.events.append(helper_event("capture-owner", "event-2", 10120,
                                     transaction=TRANSACTION, rid="app:id/monitorHeaderGroup"))
    # Exercise the verifier with the transaction's complete set of candidate events.
    events = [entry_safety._helper_click_events({"evidenceEvents": client.events},
              req_id="capture-owner", transaction_id=TRANSACTION)[index]
              for index in range(2)]
    result = entry_safety.verify_actual_hit(permit, {}, events, roots=roots,
        dispatch_uptime_ms=10000, collection={"deadline_uptime_ms": 11000})
    assert result["matched"] is False
    assert result["candidate_count"] == 2 and result["competing_event_count"] == 1


def test_pre_dispatch_event_is_not_reused_as_current_hit(monkeypatch):
    client = CaptureClient(appear_at_poll=1, event_time=9999)
    roots, permit, collection, _clock = run_collection(monkeypatch, client)
    assert collection["candidate_events"] == []
    assert collection["stale_events"][0]["correlation_status"] == "PRE_DISPATCH_EVENT"
    assert not entry_safety.verify_actual_hit(permit, {}, collection["candidate_events"], roots=roots,
        dispatch_uptime_ms=10000, collection=collection)["matched"]


def test_wrong_capture_owner_or_transaction_event_is_not_attributed(monkeypatch):
    client = CaptureClient(appear_at_poll=1, event_time=10100, stale_owner=True)
    _roots, _permit, collection, _clock = run_collection(monkeypatch, client)
    assert collection["candidate_events"] == []
    assert collection["helper_event_count"] == 0


def test_authoritative_hard_stop_ends_collection_without_more_device_io(monkeypatch):
    class HardStop:
        def guard(self, operation):
            raise RuntimeError(f"STOP:{operation}")

    client = CaptureClient()
    client._phase5c_hard_stop_state = HardStop()
    roots, permit, collection, _clock = run_collection(monkeypatch, client)
    assert collection["ok"] is False
    assert collection["reason"].startswith("AUTHORITATIVE_HARD_STOP")
    assert client.operations == []
    assert collection["helper_capture_closed"] is False


def test_valid_exact_owner_and_current_focus_anchor_pass():
    roots, _owner, permit, click, collection, patterns = exact_authority_case()
    mapping = entry_safety.map_click_source_to_target(click, permit, roots)
    assert mapping["status"] == "EXACT"
    result = entry_safety.verify_actual_hit(
        permit, {}, [click], roots=roots, dispatch_uptime_ms=10000,
        collection=collection, required_anchor_patterns=patterns,
    )
    assert result["matched"] is True
    assert result["reason"] == "EXACT_OWNER_AND_CURRENT_FOCUS_ANCHOR"


def test_multiple_current_accessibility_focus_nodes_remain_unauthorized():
    roots, _owner, permit, click, collection, patterns = exact_authority_case()
    collection["post_action_observations"][0]["current_hierarchy"] = [
        dict(sourceNodeId="focus-anchor", windowId=9, accessibilityFocused=True,
             text="Air Care", children=[]),
        dict(sourceNodeId="other-focus", windowId=9, accessibilityFocused=True,
             text="Other", children=[]),
    ]
    result = entry_safety.verify_actual_hit(
        permit, {}, [click], roots=roots, dispatch_uptime_ms=10000,
        collection=collection, required_anchor_patterns=patterns,
    )
    assert result["matched"] is False
    assert result["reason"] == "CURRENT_ACCESSIBILITY_FOCUS_AMBIGUOUS"


def test_helper_post_action_parser_preserves_transaction_capture_and_hierarchy():
    snapshot = {"evidenceEvents": [dict(
        eventId="post-event", eventType="ENTRY_CLICK_POST_ACTION_OBSERVED", reqId="req-1",
        correlation={"transaction_id": "tx-1"}, payload=dict(
            capture_id="capture-1", connection_id="connection-1", source_click_event_id="click-1",
            dispatch_uptime_ms=1000, source_click_captured_elapsed_realtime_ms=1100,
            captured_elapsed_realtime_ms=1400, current_capture_id="current-1", root_window_id=9,
            focus_node_id="focus-1", focus_window_id=9, accessibility_focused=True,
            current_hierarchy={"sourceNodeId": "focus-1", "windowId": 9,
                              "accessibilityFocused": True, "text": "Air Care", "children": []},
            current_hierarchy_status="FIELD_PRESENT",
        ),
    )]}
    parsed = entry_safety._helper_post_action_events(snapshot, req_id="req-1", transaction_id="tx-1")
    assert len(parsed) == 1
    assert parsed[0]["capture_id"] == "capture-1"
    assert parsed[0]["source_click_event_id"] == "click-1"
    assert parsed[0]["current_hierarchy"]["sourceNodeId"] == "focus-1"


def test_bounds_and_class_cannot_override_mismatched_source_node_id():
    roots, _owner, permit, click, collection, patterns = exact_authority_case(source_node_id="other-node")
    click["bounds"] = (30, 1421, 1050, 1469)
    click["source"].update(class_name="android.widget.RelativeLayout", bounds=click["bounds"])
    result = entry_safety.verify_actual_hit(
        permit, {}, [click], roots=roots, dispatch_uptime_ms=10000,
        collection=collection, required_anchor_patterns=patterns,
    )
    assert result["matched"] is False
    assert result["reason"] == "ACTIVATED_SOURCE_AMBIGUOUS"


def test_duplicate_stable_source_identity_is_ambiguous():
    roots, _owner, permit, click, collection, patterns = exact_authority_case()
    duplicate = node("other:id", "Different", "[0,0][10,10]")
    duplicate.update(sourceNodeId="target-node", windowId=4)
    roots[0]["children"].append(duplicate)
    result = entry_safety.verify_actual_hit(
        permit, {}, [click], roots=roots, dispatch_uptime_ms=10000,
        collection=collection, required_anchor_patterns=patterns,
    )
    assert result["matched"] is False
    assert result["source_mapping"]["status"] == "AMBIGUOUS"


def test_stale_post_action_focus_observation_is_rejected():
    roots, _owner, permit, click, collection, patterns = exact_authority_case()
    collection["post_action_observations"][0]["captured_elapsed_realtime_ms"] = 10099
    result = entry_safety.verify_actual_hit(
        permit, {}, [click], roots=roots, dispatch_uptime_ms=10000,
        collection=collection, required_anchor_patterns=patterns,
    )
    assert result["matched"] is False
    assert result["reason"] == "POST_ACTION_OBSERVATION_STALE_OR_OUTSIDE_WINDOW"


def test_focus_must_be_current_and_match_required_anchor():
    roots, _owner, permit, click, collection, patterns = exact_authority_case(anchor_label="Unrelated")
    result = entry_safety.verify_actual_hit(
        permit, {}, [click], roots=roots, dispatch_uptime_ms=10000,
        collection=collection, required_anchor_patterns=patterns,
    )
    assert result["matched"] is False
    assert result["reason"] == "CURRENT_REQUIRED_ANCHOR_MISSING_OR_AMBIGUOUS"


def test_current_focus_path_proves_unique_anchor_when_unique_id_is_absent():
    roots, _owner, permit, click, collection, patterns = exact_authority_case()
    observation = collection["post_action_observations"][0]
    observation["focus_node_id"] = None
    observation["focus_node_path"] = []
    result = entry_safety.verify_actual_hit(
        permit, {}, [click], roots=roots, dispatch_uptime_ms=10000,
        collection=collection, required_anchor_patterns=patterns,
    )
    assert result["matched"] is True


def test_duplicate_current_anchor_is_ambiguous_even_when_focus_path_is_exact():
    roots, _owner, permit, click, collection, patterns = exact_authority_case()
    observation = collection["post_action_observations"][0]
    observation["focus_node_id"] = None
    observation["focus_node_path"] = []
    duplicate_anchor = dict(observation["current_hierarchy"])
    duplicate_anchor["accessibilityFocused"] = False
    observation["current_hierarchy"]["children"] = [
        duplicate_anchor,
    ]
    result = entry_safety.verify_actual_hit(
        permit, {}, [click], roots=roots, dispatch_uptime_ms=10000,
        collection=collection, required_anchor_patterns=patterns,
    )
    assert result["matched"] is False
    assert result["reason"] == "CURRENT_REQUIRED_ANCHOR_MISSING_OR_AMBIGUOUS"


def test_capture_connection_mismatch_is_rejected():
    roots, _owner, permit, click, collection, patterns = exact_authority_case()
    collection["post_action_observations"][0]["connection_id"] = "reconnected"
    result = entry_safety.verify_actual_hit(
        permit, {}, [click], roots=roots, dispatch_uptime_ms=10000,
        collection=collection, required_anchor_patterns=patterns,
    )
    assert result["matched"] is False
    assert result["reason"] == "POST_ACTION_CAPTURE_IDENTITY_MISMATCH"


def test_resource_and_semantics_without_stable_owner_id_fail_closed():
    roots, owner, child = owned_tree()
    owner["viewIdResourceName"] = ""
    owner["sourceNodeId"] = None
    resolution = entry_safety.resolve_navigation_owner(roots, roots[0], "Home Monitor")
    denied = entry_safety.authorize_entry(resolution, roots, scenario="life_home_monitor_plugin",
                                          matched_phrase="Home Monitor")
    assert denied["authorized"] is False
    assert denied["reason"] == "ENTRY_TARGET_STABLE_IDENTITY_UNAVAILABLE"
    owner["sourceNodeId"] = "stable:owner"
    permit = permit_for(roots, owner)
    child["className"] = owner["className"]
    child["contentDescription"] = "Home Monitor"
    event = dict(event_time="10100", event_ingestion_elapsed_realtime_ms=10101,
                 package=PACKAGE, class_name="android.view.ViewGroup",
                 text="[Home Monitor]", content_description="Home Monitor", bounds=None,
                 source_status="FIELD_ABSENT", transaction_id=permit["transaction_id"])
    result = entry_safety.verify_actual_hit(permit, {}, [event], roots=roots,
        dispatch_uptime_ms=10000, collection={"deadline_uptime_ms": 11000,
                                              "activity_transition": True})
    assert result["matched"] is False
    assert result["reason"] == "ACTIVATED_SOURCE_IDENTITY_UNPROVEN"


def test_activity_transition_without_click_event_is_insufficient():
    roots, owner, _child = owned_tree()
    permit = permit_for(roots, owner)
    result = entry_safety.verify_actual_hit(permit, {}, [], roots=roots,
        dispatch_uptime_ms=10000, collection={"deadline_uptime_ms": 11000,
                                              "activity_transition": True})
    assert result["matched"] is False
    assert result["evidence_strength"] == "INSUFFICIENT"


def test_mixed_action_child_cannot_be_mapped_as_parent_navigation_target():
    roots, owner, child = owned_tree()
    owner.update(sourceNodeId="owner-source", windowId=4)
    child.update(sourceNodeId="child-source", windowId=4)
    permit = permit_for(roots, owner)
    event = dict(event_time="10100", event_ingestion_elapsed_realtime_ms=10101,
                 package=PACKAGE, class_name=child["className"],
                 text="[Armed Stay]", content_description="Armed Stay", bounds=None,
                 source_status="FIELD_PRESENT", transaction_id=permit["transaction_id"],
                 source=dict(resource_id=child["viewIdResourceName"], class_name=child["className"],
                             content_description="Armed Stay", bounds=None,
                             source_node_id="child-source", window_id=4))
    result = entry_safety.verify_actual_hit(permit, {}, [event], roots=roots,
        dispatch_uptime_ms=10000, collection={"deadline_uptime_ms": 11000})
    assert result["matched"] is False
    assert result["source_mapping"]["reason"] == "SOURCE_MAP_IS_NOT_AUTHORIZED_OWNER"


def test_talkback_click_parser_preserves_fields_and_absence_status():
    raw = ("talkback eventId=type:EVENT_TYPE_ACCESSIBILITY subtype:TYPE_VIEW_CLICKED "
           "time:77 event=null interpretation=UiChange{sourceBoundsInScreen=Rect(20, 120 - 1000, 180)}\n"
           "talkback event=EventType: TYPE_VIEW_CLICKED; EventTime: 77; "
           f"PackageName: {PACKAGE}; Action: 0; [ ClassName: android.view.ViewGroup; "
           "Text: [Home Monitor]; ContentDescription: Home Monitor; ItemCount: -1; Enabled: true; "
           "Password: false; eventSourceNode=source-12 boundsInScreen: Rect(20, 120 - 1000, 180); "
           "packageName: com.samsung.android.oneconnect; className: android.view.ViewGroup; "
           "viewIdResName: app:id/monitorHeaderGroup; windowId: 4; clickable: true; focusable: true ]\n")
    event = entry_safety.click_events(raw)["77"]
    assert event["event_type"] == "TYPE_VIEW_CLICKED"
    assert event["event_time"] == "77" and event["package"] == PACKAGE
    assert event["class_name"] == "android.view.ViewGroup"
    assert event["text"] == "[Home Monitor]" and event["content_description"] == "Home Monitor"
    assert event["bounds"] == (20, 120, 1000, 180)
    assert event["source_node_id"] == "source-12"
    assert event["resource_id"] == "app:id/monitorHeaderGroup"
    assert event["window_id"] == 4 and event["enabled"] is True
    assert event["clickable"] is True and event["focusable"] is True
    assert event["field_status"]["resource_id"] == "FIELD_PRESENT"
    assert event["raw_line"] and event["parser_source"] == "talkback_logcat"

    historical = (f"EventType: TYPE_VIEW_CLICKED; EventTime: 878142546; PackageName: {PACKAGE}; "
                  "Action: 0; [ ClassName: android.view.ViewGroup; Text: [Home Monitor]; "
                  "ContentDescription: Home Monitor; ItemCount: -1; Enabled: true; Password: false ]")
    old_event = entry_safety.click_events(historical)["878142546"]
    assert old_event["content_description"] == "Home Monitor"
    assert old_event["resource_id"] is None
    assert old_event["field_status"]["resource_id"] == "FIELD_ABSENT"


def test_malformed_source_metadata_is_not_fabricated():
    malformed = (f"EventType: TYPE_VIEW_CLICKED; EventTime: 90; PackageName: {PACKAGE}; "
                 "[ ClassName: android.view.ViewGroup; Text: [Home Monitor]; Enabled: true; "
                 "eventSourceNode=; viewIdResName:; windowId: not-a-number ]")
    event = entry_safety.click_events(malformed)["90"]
    assert event["source_node_id"] is None and event["resource_id"] is None
    assert event["field_status"]["source_node_id"] == "FIELD_PARSE_FAILED"
    assert event["field_status"]["resource_id"] == "FIELD_PARSE_FAILED"
    assert event["field_status"]["window_id"] == "FIELD_PARSE_FAILED"
    roots, owner, _child = owned_tree()
    permit = permit_for(roots, owner)
    assert not entry_safety.verify_actual_hit(permit, {}, [dict(event, event_time="90")], roots=roots,
        dispatch_uptime_ms=80, collection={"deadline_uptime_ms": 200})["matched"]


def test_unexpected_package_click_is_not_dropped_from_competitor_set():
    roots, owner, _child = owned_tree()
    permit = permit_for(roots, owner)
    events = [
        dict(event_time="10100", event_ingestion_elapsed_realtime_ms=10101, package=PACKAGE,
             bounds=(30, 1421, 1050, 1469), text="[Home Monitor]"),
        dict(event_time="10120", event_ingestion_elapsed_realtime_ms=10121,
             package="com.android.systemui", bounds=None,
             class_name="android.view.View", text="Overlay"),
    ]
    result = entry_safety.verify_actual_hit(permit, {}, events, roots=roots,
        dispatch_uptime_ms=10000, collection={"deadline_uptime_ms": 11000})
    assert result["matched"] is False
    assert result["candidate_count"] == 2
    assert result["competing_event_count"] == 1


def test_duplicate_same_time_clicks_are_not_collapsed_by_channel_merge():
    first = dict(event_id="helper-a", event_time="10100", package=PACKAGE,
                 class_name="android.view.ViewGroup", text="Home Monitor",
                 content_description="Home Monitor", parser_source="helper_accessibility_event")
    second = dict(first, event_id="helper-b")
    talkback = {"10100": dict(first, event_id="10100", parser_source="talkback_logcat", raw_line="duplicate")}
    merged = entry_safety._merge_click_channels([first, second], talkback)
    assert len(merged) == 3


def test_helper_click_collection_uses_elapsed_capture_clock_after_deep_sleep(monkeypatch):
    client = CaptureClient(appear_at_poll=1, event_time=3065574678,
                           captured_elapsed_realtime_ms=3163450989)
    roots, permit, collection, _clock = run_collection(
        monkeypatch, client, dispatch_uptime_ms=3163450760,
    )

    assert collection["ok"] is True
    assert len(collection["candidate_events"]) == 1
    assert collection["stale_events"] == []
    assert collection["candidate_events"][0]["event_time"] == "3065574678"
    assert collection["candidate_events"][0]["event_ingestion_elapsed_realtime_ms"] == 3163450989
    assert collection["candidate_events"][0]["correlation_status"] == "IN_TRANSACTION_WINDOW"
    hit = entry_safety.verify_actual_hit(
        permit, {}, collection["candidate_events"], roots=roots,
        dispatch_uptime_ms=3163450760, collection=collection,
    )
    assert hit["matched"] is False
    assert hit["reason"] == "ACTIVATED_SOURCE_IDENTITY_UNPROVEN"
