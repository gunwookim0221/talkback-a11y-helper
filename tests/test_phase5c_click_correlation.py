"""Regression tests for transaction-scoped Phase 5C click evidence."""
from __future__ import annotations

from tb_runner import entry_safety


PACKAGE = "com.samsung.android.oneconnect"
TRANSACTION = "tx-home-monitor"


def node(rid, label, bounds, *, klass="android.view.ViewGroup", clickable=False, children=None):
    return dict(viewIdResourceName=rid, className=klass, text="", contentDescription=label,
                boundsInScreen=bounds, clickable=clickable, focusable=clickable,
                enabled=True, children=children or [])


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


def helper_event(req_id, event_id, event_time, *, transaction=TRANSACTION, rid="app:id/monitorHeaderGroup",
                 klass="android.view.ViewGroup", text="", description="Home Monitor", package=PACKAGE):
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
                             captured_elapsed_realtime_ms=int(event_time) + 1,
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
    def __init__(self, *, appear_at_poll=None, event_time=10100, events=None, stale_owner=False):
        self.clock = None
        self.appear_at_poll = appear_at_poll
        self.event_time = event_time
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

    def _read_log_result(self, dev, prefix, req_id, **_kwargs):
        operation = self.rpc_responses[req_id]
        rows = list(self.events)
        if operation == "snapshot":
            self.snapshot_count += 1
            if isinstance(self.appear_at_poll, int) and self.snapshot_count >= self.appear_at_poll and not rows:
                req_id_owner = "stale-owner" if self.stale_owner else self.active_capture_id
                rows.append(helper_event(req_id_owner, "event-1", self.event_time,
                                         transaction=self.transaction_id))
                self.events = list(rows)
        if operation == "end" and not rows and self.appear_at_poll == "end":
            rows.append(helper_event(self.active_capture_id, "late-event", self.event_time,
                                     transaction=self.transaction_id))
            self.events = list(rows)
        return dict(ok=True, operation=operation, transactionId=self.transaction_id,
                    reqId=self.active_capture_id, cursorEventSequence=0,
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
            return dict(ok=True, transactionId=TRANSACTION, operation=call["operation"],
                        reqId=call["reqId"], captureReqId=call["captureReqId"], evidenceEvents=[])

    client = Client()
    begin = entry_safety._entry_capture_request(client, "SERIAL", req_id="owner",
        transaction_id=TRANSACTION, operation="begin")
    snapshot = entry_safety._entry_capture_request(client, "SERIAL", req_id="owner",
        transaction_id=TRANSACTION, operation="snapshot")
    assert begin["ok"] and snapshot["ok"]
    assert begin["responseReqId"] != snapshot["responseReqId"]
    assert client.calls[0]["captureReqId"] == client.calls[1]["captureReqId"] == "owner"
    assert begin["reqId"] == begin["responseReqId"]


def test_stale_helper_operation_response_is_rejected():
    class Client:
        def _broadcast(self, *_args):
            pass
        def _read_log_result(self, _dev, _prefix, req_id, **_kwargs):
            return dict(ok=True, reqId=req_id, transactionId=TRANSACTION, operation="begin", evidenceEvents=[])

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
    assert hit["matched"] is True
    assert hit["evidence_strength"] == "STRONG_UNIQUE"


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


def test_boundsless_source_resource_id_maps_to_unique_authorized_owner():
    roots, owner, _child = owned_tree()
    permit = permit_for(roots, owner)
    event = dict(package=PACKAGE, class_name="android.view.ViewGroup", text="[Home Monitor]",
                 content_description="Home Monitor", bounds=None, source_status="FIELD_PRESENT",
                 source=dict(resource_id="app:id/monitorHeaderGroup",
                             class_name="android.view.ViewGroup", text=None,
                             content_description="Home Monitor", bounds=None))
    mapping = entry_safety.map_click_source_to_target(event, permit, roots)
    assert mapping["status"] == "STRONG_UNIQUE"
    hit = entry_safety.verify_actual_hit(permit, {}, [dict(event, event_time="10100")], roots=roots,
        dispatch_uptime_ms=10000, collection={"deadline_uptime_ms": 11000})
    assert hit["matched"] is True and hit["evidence_strength"] == "STRONG_UNIQUE"


def test_exact_bounds_and_source_match_are_classified_exact():
    roots, owner, _child = owned_tree()
    permit = permit_for(roots, owner)
    event = dict(event_time="10100", package=PACKAGE, class_name=owner["className"],
                 text="[Home Monitor]", content_description="Home Monitor",
                 bounds=(30, 1421, 1050, 1469), source_status="FIELD_PRESENT",
                 source=dict(resource_id=owner["viewIdResourceName"],
                             class_name=owner["className"],
                             content_description="Home Monitor",
                             bounds=(30, 1421, 1050, 1469)))
    result = entry_safety.verify_actual_hit(permit, {}, [event], roots=roots,
        dispatch_uptime_ms=10000, collection={"deadline_uptime_ms": 11000})
    assert result["matched"] is True
    assert result["evidence_strength"] == "EXACT"
    assert result["source_mapping"]["status"] == "EXACT"


def test_boundsless_duplicate_resource_identity_is_rejected_as_ambiguous():
    roots, owner, child = owned_tree()
    permit = permit_for(roots, owner)
    child["viewIdResourceName"] = owner["viewIdResourceName"]
    child["className"] = owner["className"]
    child["contentDescription"] = "Home Monitor"
    event = dict(event_time="10100", package=PACKAGE, class_name="android.view.ViewGroup",
                 text="[Home Monitor]", content_description="Home Monitor", bounds=None,
                 source_status="FIELD_PRESENT",
                 source=dict(resource_id=owner["viewIdResourceName"], class_name=owner["className"],
                             content_description="Home Monitor", bounds=None))
    result = entry_safety.verify_actual_hit(permit, {}, [event], roots=roots,
        dispatch_uptime_ms=10000, collection={"deadline_uptime_ms": 11000,
                                              "activity_transition": True})
    assert result["matched"] is False
    assert result["evidence_strength"] == "AMBIGUOUS"


def test_boundsless_semantics_alone_reject_when_owner_and_child_are_indistinguishable():
    roots, owner, child = owned_tree()
    owner["viewIdResourceName"] = ""
    permit = permit_for(roots, owner)
    child["className"] = owner["className"]
    child["contentDescription"] = "Home Monitor"
    event = dict(event_time="10100", package=PACKAGE, class_name="android.view.ViewGroup",
                 text="[Home Monitor]", content_description="Home Monitor", bounds=None,
                 source_status="FIELD_ABSENT")
    result = entry_safety.verify_actual_hit(permit, {}, [event], roots=roots,
        dispatch_uptime_ms=10000, collection={"deadline_uptime_ms": 11000,
                                              "activity_transition": True})
    assert result["matched"] is False
    assert result["evidence_strength"] == "AMBIGUOUS"


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
    permit = permit_for(roots, owner)
    event = dict(event_time="10100", package=PACKAGE, class_name=child["className"],
                 text="[Armed Stay]", content_description="Armed Stay", bounds=None,
                 source_status="FIELD_PRESENT",
                 source=dict(resource_id=child["viewIdResourceName"], class_name=child["className"],
                             content_description="Armed Stay", bounds=None))
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
        dict(event_time="10100", package=PACKAGE, bounds=(30, 1421, 1050, 1469),
             text="[Home Monitor]"),
        dict(event_time="10120", package="com.android.systemui", bounds=None,
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
