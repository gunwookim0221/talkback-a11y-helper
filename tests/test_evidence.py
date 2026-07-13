from __future__ import annotations

import json
from pathlib import Path

from talkback_lib import A11yAdbClient
from talkback_lib.helper_bridge import HelperBridge
from tb_runner.evidence import (
    AppendOnlyEvidenceLedger,
    EvidenceEvent,
    EvidenceRuntime,
    build_node_observation,
    build_reconciliation_report,
    deterministic_json,
    evidence_enabled,
    reduce_shadow_events,
)


def _event(event_id: str = "evt_test", event_type: str = "TEST") -> EvidenceEvent:
    return EvidenceEvent(
        schema_version="evidence-event-v1",
        event_id=event_id,
        event_type=event_type,
        run_id="run_test",
        scenario_tx_id="stx_test",
        transaction_id="tx_test",
        logical_action_id="act_test",
        attempt_id="att_test",
        parent_transaction_id=None,
        causation_event_id=None,
        producer="runner",
        producer_instance_id="python_runner",
        producer_sequence=1,
        wall_time_utc="2026-01-01T00:00:00.000Z",
        monotonic_time_ns=1,
        runner_received_wall_time_utc=None,
        scenario_id="scenario",
        plugin_family="plugin",
        step_index=1,
        phase="main_loop",
        surface_id="surface",
        surface_revision=0,
        payload={"b": 2, "a": 1},
        provenance={},
    )


def test_event_envelope_serialization_is_deterministic() -> None:
    left = deterministic_json(_event().to_dict())
    right = deterministic_json(_event().to_dict())
    assert left == right
    assert json.loads(left)["payload"] == {"a": 1, "b": 2}


def test_append_only_ledger_deduplicates_event_ids(tmp_path: Path) -> None:
    ledger = AppendOnlyEvidenceLedger(tmp_path / "run.evidence.jsonl")
    assert ledger.append(_event()) is True
    assert ledger.append(_event()) is False
    lines = (tmp_path / "run.evidence.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_ledger_write_failure_is_isolated(tmp_path: Path) -> None:
    warnings: list[str] = []
    ledger = AppendOnlyEvidenceLedger(tmp_path / "blocked" / "ledger.jsonl", warning_fn=warnings.append)
    # A file where a directory is expected makes creation fail, but append must not raise.
    (tmp_path / "blocked").write_text("not a directory", encoding="utf-8")
    assert ledger.append(_event()) is False
    assert warnings


def test_runtime_parent_child_and_correlation_metadata(tmp_path: Path) -> None:
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx", run_id="run_fixed")
    runtime.start_scenario("home_safe_plugin", "home")
    parent = runtime.begin_transaction("SMART_NEXT", phase="main_loop")
    child = runtime.begin_transaction("REALIGN_FOCUS", phase="realign", parent_transaction_id=parent["transaction_id"])
    assert child["parent_transaction_id"] == parent["transaction_id"]
    extras = runtime.correlation_extras(parent)
    assert "evidenceRunId" in extras
    assert "run_fixed" in extras


def test_runtime_exposes_read_only_transaction_event_snapshot(tmp_path: Path) -> None:
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("home_safe_plugin", "home")
    transaction = runtime.begin_transaction("SMART_NEXT", phase="main_loop")
    runtime.emit(
        "ACTION_API_RESULT",
        producer="helper",
        phase="helper",
        transaction=transaction,
        payload={"success": True},
    )
    events = runtime.events_for_transaction(transaction["transaction_id"])
    assert isinstance(events, tuple)
    assert [event.event_type for event in events] == ["TRANSACTION_OPENED", "ACTION_API_RESULT"]
    assert runtime.events_for_transaction("missing") == ()


def test_disabled_runtime_does_not_create_production_or_evidence_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "talkback_compare.xlsx"
    runtime = EvidenceRuntime(output_path=output, enabled=False)
    runtime.start_scenario("home_safe_plugin")
    runtime.begin_transaction("SMART_NEXT", phase="main_loop")
    assert runtime.finalize() == {}
    assert not list(tmp_path.glob("*.evidence.*"))


def test_traversal_flag_implies_evidence_but_default_remains_off() -> None:
    assert evidence_enabled({}) is False
    assert evidence_enabled({"TB_TRAVERSAL_IDENTITY_V2_ENABLED": "1"}) is True


def test_evidence_transaction_links_do_not_add_fields_to_production_row(tmp_path: Path) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("home_safe_plugin", "home")
    client.set_evidence_runtime(runtime)
    client._evidence_set_step(1)
    client._evidence_begin_step_action("SMART_NEXT")
    row = {"step_index": 1, "merged_announcement": "hello", "focus_payload_source": "top_level"}
    client._evidence_complete_step_action(
        row,
        {"text": "title", "className": "android.widget.TextView", "boundsInScreen": {"l": 0, "t": 0, "r": 1, "b": 1}},
    )
    assert not any(key.startswith("_evidence_") for key in row)
    assert client._evidence_transaction_for_step(1)
    assert client._evidence_actual_observation_for_step(1)


def test_smart_next_helper_facts_are_copied_to_runner_ledger(tmp_path: Path) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("home_safe_plugin", "home")
    client.set_evidence_runtime(runtime)
    client._evidence_begin_step_action("SMART_NEXT")
    client._evidence_helper_ack(
        {
            "status": "moved",
            "evidenceEvents": [
                {
                    "eventType": "ACTION_API_RESULT",
                    "timestamp": "2026-01-01T00:00:00.000Z",
                    "payload": {"success": True},
                    "correlation": {"evidenceTransactionId": "ignored_by_runner"},
                }
            ],
        },
        req_id="req_1",
    )
    event_types = [json.loads(line)["event_type"] for line in runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    assert "ACTION_API_RESULT" in event_types
    assert "HELPER_ACK_RECEIVED" in event_types


def test_helper_evidence_accepts_json_string_and_snake_case_event_type(tmp_path: Path) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("home_safe_plugin", "home")
    client.set_evidence_runtime(runtime)
    client._evidence_begin_step_action("SMART_NEXT")
    client._evidence_helper_ack(
        {"evidenceEvents": json.dumps([{"eventId": "helper_1", "event_type": "POST_ACTION_OBSERVATION", "payload": {}}])},
        req_id="req_1",
    )
    event_types = [json.loads(line)["event_type"] for line in runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    assert "POST_ACTION_OBSERVATION" in event_types


def test_helper_evidence_snapshot_deduplicates_inline_event_ids(tmp_path: Path) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("home_safe_plugin", "home")
    client.set_evidence_runtime(runtime)
    client._evidence_begin_step_action("SMART_NEXT")
    event = {"eventId": "helper_1", "eventType": "ACTION_API_RESULT", "payload": {"success": True}}
    client._evidence_helper_ack({"evidenceEvents": [event]}, req_id="req_1")
    client._evidence_helper_ack({"evidenceEvents": [event]}, req_id="req_1")
    event_types = [json.loads(line)["event_type"] for line in runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    assert event_types.count("ACTION_API_RESULT") == 1


def test_individual_helper_logcat_events_merge_with_inline_and_snapshot(tmp_path: Path, monkeypatch) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("home_safe_plugin", "home")
    client.set_evidence_runtime(runtime)
    transaction = client._evidence_begin_step_action("SMART_NEXT")
    assert transaction is not None
    tx_id = transaction["transaction_id"]
    client._evidence_helper_ack({"evidenceEvents": [{"eventId": "inline", "eventType": "TARGET_RESOLVED", "payload": {}}]}, req_id="req_1")
    client._evidence_helper_ack({"evidenceEvents": [{"eventId": "snapshot", "eventType": "ACTION_API_RESULT", "payload": {}}]}, req_id="req_1", source="snapshot")
    line = json.dumps({
        "requestId": "req_1",
        "transactionId": tx_id,
        "eventId": "logcat",
        "event_type": "POST_ACTION_OBSERVATION",
        "correlation": {"transaction_id": tx_id},
        "payload": {},
    })
    monkeypatch.setattr(
        client._logcat_reader,
        "dump_filtered",
        lambda dev=None: f"I/A11Y_HELPER: SMART_NAV_RESULT {{\"reqId\":\"req_1\",\"evidenceEvents\":[\nI/A11Y_HELPER: EVIDENCE_HELPER_EVENT {line}\n",
    )
    stats = client._evidence_collect_helper_logcat_events(dev=None, req_id="req_1")
    event_types = [json.loads(item)["event_type"] for item in runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    assert stats["merged"] == 1
    assert {"TARGET_RESOLVED", "ACTION_API_RESULT", "POST_ACTION_OBSERVATION"}.issubset(event_types)


def test_individual_helper_logcat_event_ignores_unrelated_request_and_malformed_payload(tmp_path: Path, monkeypatch) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("home_safe_plugin", "home")
    client.set_evidence_runtime(runtime)
    transaction = client._evidence_begin_step_action("SMART_NEXT")
    assert transaction is not None
    tx_id = transaction["transaction_id"]
    unrelated = json.dumps({"requestId": "other", "transactionId": tx_id, "eventId": "other", "eventType": "ACTION_API_RESULT", "payload": {}})
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: f"EVIDENCE_HELPER_EVENT {unrelated}\nEVIDENCE_HELPER_EVENT {{bad\n")
    stats = client._evidence_collect_helper_logcat_events(dev=None, req_id="req_1")
    assert stats["merged"] == 0
    assert stats["incomplete"] == 1


def _helper_log_line(*, request_id: str, transaction_id: str, event_id: str, event_type: str = "ACTION_API_RESULT") -> str:
    payload = json.dumps({
        "requestId": request_id,
        "transactionId": transaction_id,
        "eventId": event_id,
        "eventType": event_type,
        "timestamp": 1,
        "correlation": {"transaction_id": transaction_id},
        "payload": {"success": True},
    })
    return f"07-11 21:04:59.520 26557 28786 I A11Y_HELPER: EVIDENCE_HELPER_EVENT {payload}"


def test_threadtime_helper_event_appends_to_closed_transaction(tmp_path: Path, monkeypatch) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("motion")
    client.set_evidence_runtime(runtime)
    transaction = client._evidence_begin_step_action("SMART_NEXT")
    assert transaction is not None
    runtime.close_transaction(transaction, status="completed", phase="main_loop")
    line = _helper_log_line(request_id="req_closed", transaction_id=transaction["transaction_id"], event_id="closed_event")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: line)
    stats = client._evidence_collect_helper_logcat_events(None, req_id="req_closed")
    assert stats["prefix"] == stats["json"] == stats["transaction"] == stats["merged"] == 1
    assert runtime.transaction(transaction["transaction_id"])["state"] == "closed"


def test_missing_transaction_is_queued_then_retried(tmp_path: Path, monkeypatch) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("motion")
    client.set_evidence_runtime(runtime)
    client._evidence_active_transaction = None
    line = _helper_log_line(request_id="req_future", transaction_id="tx_future", event_id="future_event")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: line)
    first = client._evidence_collect_helper_logcat_events(None, req_id="req_future")
    assert first["merged"] == 0
    assert len(client._evidence_pending_helper_events) == 1
    future = runtime.begin_transaction("SMART_NEXT", phase="main_loop")
    runtime._transactions["tx_future"] = {**future, "transaction_id": "tx_future", "state": "closed"}
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: "")
    retried = client._evidence_retry_pending()
    assert retried["merged"] == 1
    assert not client._evidence_pending_helper_events


def test_finalize_records_unresolved_helper_event_as_orphan(tmp_path: Path, monkeypatch) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("motion")
    client.set_evidence_runtime(runtime)
    client._evidence_active_transaction = None
    line = _helper_log_line(request_id="req_orphan", transaction_id="tx_missing", event_id="orphan_event")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: line)
    client._evidence_collect_helper_logcat_events(None, req_id="req_orphan")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: "")
    report = runtime.finalize()
    assert report["orphan_evidence"] == {"count": 1, "reasons": {"transaction_not_found": 1}}


def test_clear_logcat_drains_evidence_before_device_buffer_clear(tmp_path: Path, monkeypatch) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("motion")
    client.set_evidence_runtime(runtime)
    transaction = client._evidence_begin_step_action("SMART_NEXT")
    client._evidence_active_request_id = "req_1"
    line = _helper_log_line(request_id="req_1", transaction_id=transaction["transaction_id"], event_id="before_clear")
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: line)
    cleared: list[bool] = []
    monkeypatch.setattr(client._adb_device, "_clear_logcat_best_effort", lambda dev=None, timeout=1.5: cleared.append(True) or "")
    client.clear_logcat()
    assert cleared == [True]
    event_types = [json.loads(item)["event_type"] for item in runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    assert "ACTION_API_RESULT" in event_types


def test_collector_exception_is_reported_not_silently_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    client = A11yAdbClient(start_monitor=False)
    runtime = EvidenceRuntime(output_path=tmp_path / "talkback_compare.xlsx")
    runtime.start_scenario("motion")
    client.set_evidence_runtime(runtime)
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: (_ for _ in ()).throw(OSError("boom")))
    client._evidence_collect_helper_logcat_events(None, req_id="req_1")
    assert "[EVIDENCE][collector_error]" in capsys.readouterr().out


def test_evidence_off_clear_logcat_does_not_call_collector(monkeypatch) -> None:
    client = A11yAdbClient(start_monitor=False)
    called: list[bool] = []
    monkeypatch.setattr(client, "_evidence_collect_helper_logcat_events", lambda *args, **kwargs: called.append(True))
    monkeypatch.setattr(client._adb_device, "_clear_logcat_best_effort", lambda dev=None, timeout=1.5: "")
    client.clear_logcat()
    assert called == []


def test_helper_bridge_keeps_correlation_metadata_backward_compatible() -> None:
    class Client:
        adb_path = "adb"
        package_name = "pkg"

        def __init__(self) -> None:
            self.extras: list[str] = []

        def _resolve_serial(self, _dev):
            return None

        def _evidence_correlation_extras(self):
            return ["--es", "evidenceTransactionId", "tx_123"]

        def _safe_trace_print(self, _message: str) -> None:
            return None

        def _broadcast(self, _dev, _action, extras):
            self.extras = list(extras)
            return "ok"

        def _read_log_result(self, *_args, **_kwargs):
            return {"success": True, "status": "moved"}

    client = Client()
    result = HelperBridge(client)._request_smart_next(dev=None, req_id="req_1")
    assert result["status"] == "moved"
    assert client.extras[:4] == ["--es", "reqId", "req_1", "--es"]
    assert "evidenceTransactionId" in client.extras


def test_observation_id_does_not_hash_raw_text_as_the_identity_key() -> None:
    common = {
        "packageName": "pkg",
        "windowId": 7,
        "className": "android.widget.TextView",
        "viewIdResourceName": "title",
        "boundsInScreen": {"l": 1, "t": 2, "r": 3, "b": 4},
    }
    first = build_node_observation({**common, "text": "private A"}, run_id="run", surface_id="s", surface_revision=1, source="test", snapshot_id="snap")
    second = build_node_observation({**common, "text": "private B"}, run_id="run", surface_id="s", surface_revision=1, source="test", snapshot_id="snap")
    assert first.observation_id == second.observation_id
    assert first.normalized_text != second.normalized_text


def test_shadow_reducer_is_indeterminate_without_atomic_pre_post_evidence() -> None:
    result = reduce_shadow_events([_event(event_type="HELPER_ACK_RECEIVED")])
    assert result["verdict"] == "INDETERMINATE"
    assert result["evidence_completeness"] == "PARTIAL"


def _node(resource_id: str, left: int, *, children: list[dict] | None = None) -> dict:
    return {
        "packageName": "pkg",
        "windowId": 1,
        "className": "android.widget.TextView",
        "viewIdResourceName": resource_id,
        "boundsInScreen": {"l": left, "t": 0, "r": left + 10, "b": 10},
        "children": children or [],
    }


def test_shadow_reducer_confirms_target_landing_from_helper_physical_observation() -> None:
    before = _node("before", 0)
    target = _node("target", 20)
    events = [
        EvidenceEvent(**{**_event("pre", "PRE_FOCUS_OBSERVED").to_dict(), "payload": {"observation": before}}),
        EvidenceEvent(**{**_event("api", "ACTION_API_RESULT").to_dict(), "payload": {"success": True}}),
        EvidenceEvent(**{**_event("resolved", "TARGET_RESOLVED").to_dict(), "payload": {"resolvedTarget": target}}),
        EvidenceEvent(**{**_event("post", "POST_ACTION_OBSERVATION").to_dict(), "payload": {"observation": target}}),
        _event("ack", "HELPER_ACK_RECEIVED"),
    ]
    assert reduce_shadow_events(events)["verdict"] == "MOVE_CONFIRMED"


def test_shadow_reducer_detects_static_focus_from_atomic_observations() -> None:
    before = _node("before", 0)
    events = [
        EvidenceEvent(**{**_event("pre_static", "PRE_FOCUS_OBSERVED").to_dict(), "payload": {"observation": before}}),
        EvidenceEvent(**{**_event("api_static", "ACTION_API_RESULT").to_dict(), "payload": {"success": True}}),
        EvidenceEvent(**{**_event("post_static", "POST_ACTION_OBSERVATION").to_dict(), "payload": {"observation": before}}),
        _event("ack_static", "HELPER_ACK_RECEIVED"),
    ]
    assert reduce_shadow_events(events)["verdict"] == "STATIC_FOCUS"


def test_shadow_reducer_detects_snap_back_from_delayed_observation() -> None:
    before = _node("before", 0)
    target = _node("target", 20)
    events = [
        EvidenceEvent(**{**_event("pre2", "PRE_FOCUS_OBSERVED").to_dict(), "payload": {"observation": before}}),
        EvidenceEvent(**{**_event("api2", "ACTION_API_RESULT").to_dict(), "payload": {"success": True}}),
        EvidenceEvent(**{**_event("resolved2", "TARGET_RESOLVED").to_dict(), "payload": {"resolvedTarget": target}}),
        EvidenceEvent(**{**_event("post2", "POST_ACTION_OBSERVATION").to_dict(), "payload": {"observation": target}}),
        EvidenceEvent(**{**_event("late", "DELAYED_OBSERVATION").to_dict(), "payload": {"observation": before, "offsetMs": 300}}),
        _event("ack2", "HELPER_ACK_RECEIVED"),
    ]
    assert reduce_shadow_events(events)["verdict"] == "SNAP_BACK"


def test_shadow_reducer_records_container_to_child_target_relation() -> None:
    before = _node("before", 0)
    child = _node("child", 25)
    container = _node("container", 20, children=[child])
    events = [
        EvidenceEvent(**{**_event("pre3", "PRE_FOCUS_OBSERVED").to_dict(), "payload": {"observation": before}}),
        EvidenceEvent(**{**_event("api3", "ACTION_API_RESULT").to_dict(), "payload": {"success": True}}),
        EvidenceEvent(**{**_event("resolved3", "TARGET_RESOLVED").to_dict(), "payload": {"resolvedTarget": container}}),
        EvidenceEvent(**{**_event("post3", "POST_ACTION_OBSERVATION").to_dict(), "payload": {"observation": child}}),
        _event("ack3", "HELPER_ACK_RECEIVED"),
    ]
    result = reduce_shadow_events(events)
    assert result["target_relation"] == "CONTAINER_CHILD"
    assert result["verdict"] == "MOVE_CONFIRMED"


def test_reconciliation_preserves_anchor_abort_and_zero_meaning() -> None:
    events = [
        _event("evt_anchor", "ANCHOR_ABORT"),
        _event("evt_terminal", "SCENARIO_TERMINAL"),
    ]
    events[1] = EvidenceEvent(**{**events[1].to_dict(), "payload": {"reason": "ANCHOR_ABORT"}})
    report = build_reconciliation_report(events)
    assert report["status"] == "PASS"
    assert report["checks"]["anchor_abort_preserved"] is True


def test_reconciliation_keeps_anchor_abort_when_later_scenario_has_different_terminal() -> None:
    anchor_abort = _event("anchor_abort", "ANCHOR_ABORT")
    anchor_terminal = EvidenceEvent(
        **{
            **_event("anchor_terminal", "SCENARIO_TERMINAL").to_dict(),
            "payload": {"reason": "ANCHOR_ABORT"},
        }
    )
    later_terminal = EvidenceEvent(
        **{
            **_event("later_terminal", "SCENARIO_TERMINAL").to_dict(),
            "scenario_tx_id": "stx_later",
            "scenario_id": "later_scenario",
            "payload": {"reason": "NO_TARGET_CANDIDATE"},
        }
    )

    report = build_reconciliation_report([anchor_abort, anchor_terminal, later_terminal])

    assert report["checks"]["anchor_abort_preserved"] is True
    assert report["anchor_abort_scenarios"] == 1
    assert report["anchor_abort_conflicting_terminal"] == []


def test_reconciliation_does_not_create_anchor_abort_or_hide_same_scenario_conflict() -> None:
    no_abort = EvidenceEvent(
        **{
            **_event("no_abort_terminal", "SCENARIO_TERMINAL").to_dict(),
            "payload": {"reason": "NO_TARGET_CANDIDATE"},
        }
    )
    no_abort_report = build_reconciliation_report([no_abort])
    assert no_abort_report["checks"]["anchor_abort_preserved"] is True
    assert no_abort_report["anchor_abort_scenarios"] == 0

    conflicting_terminal = EvidenceEvent(
        **{
            **_event("anchor_conflict", "SCENARIO_TERMINAL").to_dict(),
            "payload": {"reason": "NO_TARGET_CANDIDATE"},
        }
    )
    conflict_report = build_reconciliation_report([_event("anchor", "ANCHOR_ABORT"), conflicting_terminal])
    assert conflict_report["checks"]["anchor_abort_preserved"] is False
