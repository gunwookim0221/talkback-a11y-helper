"""CLV fail-closed unknown component and durable entry evidence."""
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tb_runner import collection_flow as flow
from tb_runner.evidence import EvidenceRuntime
from tb_runner.phase5b_navigation import SafeNavigationSession, SafetyBlocked
from tools import phase4b_controlled_smoke as smoke
from test_phase4c_unknown_component_availability import hierarchy_capture
from test_phase5b_navigation import focus_case, focus_scope


def test_observation_only_is_sticky_and_never_issues_action_permits():
    records = []
    session = SafeNavigationSession("scenario", lambda name, value: records.append((name, value)))
    raw, value, candidate = focus_case()
    smoke._install_observation_only_guard(session, lambda: True)
    assert session.permit is None
    for kind in ("SCROLL", "CLICK", "BACK"):
        with pytest.raises(SafetyBlocked, match="Observation-only"):
            with session.authorize(kind):
                pytest.fail("permit was issued")
    with pytest.raises(SafetyBlocked, match="Observation-only"):
        with focus_scope(session, raw, value, candidate):
            pytest.fail("focus permit was issued")
    calls = []
    client = SimpleNamespace(_run=lambda command, **kw: calls.append(command))
    with session.firewall(client, "offline"):
        with pytest.raises(SafetyBlocked):
            client._run(["shell", "input", "tap", "1", "1"], dev="offline")
        client._run(["shell", "am", "broadcast", "-a",
                     "com.iotpart.sqe.talkbackhelper.GET_FOCUS",
                     "-p", "com.iotpart.sqe.talkbackhelper"], dev="offline")
    assert len(calls) == 1 and "GET_FOCUS" in calls[0][4]
    assert session.permit is None
    assert not any(row.get("event") == "PERMIT_ISSUED" for _, row in records)


def test_observation_only_blocks_otherwise_proven_scroll():
    session = SafeNavigationSession("scenario", lambda *a: None)
    smoke._install_observation_only_guard(session, lambda: True)
    session.raw = {"capability": {"axis_contract": "axis-v1", "contradictory": False,
                                 "can_scroll_forward": True,
                                 "container": {"path": "0.1", "boundsInScreen": "0,0,100,100",
                                               "className": "ScrollView"}}}
    native = []
    client = SimpleNamespace(scroll=lambda *a, **kw: native.append((a, kw)))
    with session.firewall(client, "offline"):
        with pytest.raises(SafetyBlocked, match="Observation-only"):
            client.scroll(direction="forward", container_path="0.1", container_bounds="0,0,100,100")
    assert native == [] and session.permit is None


def test_successful_start_writes_complete_entry_diagnostics_to_real_ledger(tmp_path, monkeypatch):
    runtime = EvidenceRuntime(output_path=tmp_path / "capture.xlsx", enabled=True)
    client = SimpleNamespace(evidence_runtime=runtime)
    data = {"schema_version": "phase6d3a-entry-diagnostics-v1",
            "diagnostic_only": True,
            "events": [{"event": "transition_impl_baseline", "payload": {"nodes": "x" * 40000}},
                       {"event": "transition_impl_poll", "payload": {"capture_id": "post", "currentness": "UNKNOWN"}}]}
    monkeypatch.setattr(flow, "_ensure_focusable_inventory", lambda *a, **kw: None)
    monkeypatch.setattr(flow, "_run_start_pipeline", lambda *a, **kw: SimpleNamespace(
        needs_open_failed_row=False, should_enter_main_loop=False, entry_contract_reason=""))
    monkeypatch.setattr(flow, "_phase6d3a_attach_entry_diagnostics", lambda *a, **kw: deepcopy(data))
    flow._collect_tab_rows_inner(client, "offline", {"scenario_id": "fixture"}, [], str(tmp_path / "capture.xlsx"), str(tmp_path))
    records = [json.loads(line) for line in runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    event = next(x for x in records if x["event_type"] == "PHASE6D3A_ENTRY_DIAGNOSTICS")
    assert event["payload"]["diagnostics"] == data
    assert len(json.dumps(event)) > 32767
    assert event["payload"]["terminal_reason"] == "START_PIPELINE_COMPLETE"


def test_resulting_root_diagnostic_update_preserves_unknown_in_real_ledger(tmp_path, monkeypatch):
    from talkback_lib.exploration_evidence_clock import EvidenceClock
    raw = hierarchy_capture()
    raw.update(snapshot_coherent=True, focus_capture_id=None, geometry_capture_id=None)
    runtime = EvidenceRuntime(output_path=tmp_path / "root.xlsx", enabled=True)
    runtime.start_scenario(raw["scenario_id"], plugin_family="content")
    tracker = SimpleNamespace(bind_current_root=lambda *a, **kw: {
        "status": "INCOMPLETE_OR_STALE", "currentness": "UNKNOWN"})
    client = SimpleNamespace(_adb_device=SimpleNamespace(shadow_evidence_clock=EvidenceClock()),
                             _phase6d_exploration_shadow_runtime=object(),
                             _phase6d3a_entity_root_tracker=tracker, evidence_runtime=runtime,
                             last_hierarchy_metadata={})
    monkeypatch.setattr("tools.state_fingerprint_diagnostic.capture_observation", lambda *a, **kw: deepcopy(raw))
    def attach(_client, row):
        row["phase6d3a_entry_diagnostics"] = {"resulting_root": {"status": "UNKNOWN"}}
    monkeypatch.setattr(flow, "_phase6d3a_attach_entry_diagnostics", attach)
    row = {"scenario_id": raw["scenario_id"], "scenario_run_id": raw["scenario_run_id"], "step_index": 1}
    flow._capture_phase6d3a_production_observation(client=client, dev="offline", row=row)
    events = [json.loads(line) for line in runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    event = next(x for x in events if x["event_type"] == "PHASE6D3A_ENTRY_DIAGNOSTICS")
    assert event["payload"]["terminal_reason"] == "RESULTING_ROOT_DIAGNOSTIC_UPDATED"
    assert event["payload"]["diagnostics"]["resulting_root"]["status"] == "UNKNOWN"


def _install_rf5(monkeypatch, tmp_path, *, setup_error=False, proof_present=True):
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"scenarios": {"device_air_purifier_plugin": {"max_steps": 7}}}))
    event_path = tmp_path / "rf5.jsonl"
    for key, val in {"TB_PHASE4C_CONTROLLED": "1", "TB_PHASE4C_SMOKE_SCENARIO": "device_air_purifier_plugin",
                     "TB_PHASE4C_SMOKE_OUT": str(tmp_path), "TB_RUNTIME_CONFIG_PATH": str(config),
                     "TB_PHASE6D3A_RF5_MAIN_STEP_BUDGET": "7", "TB_PHASE6D3A_RF5_EVIDENCE_PATH": str(event_path),
                     "TB_PHASE5A_ACTION_SAFETY_MODE": "enforce", "TB_PHASE5B_CONTROLLED": "1"}.items():
        monkeypatch.setenv(key, val)
    raw = hierarchy_capture()
    raw["nodes"] = []
    raw["scenario_id"] = "device_air_purifier_plugin"
    def capture(*a, **kw):
        if setup_error:
            raise RuntimeError("capture setup failed")
        value = deepcopy(raw)
        value["scenario_run_id"] = kw["scenario_run_id"]
        return value
    monkeypatch.setattr(smoke, "A11yAdbClient", lambda **kw: SimpleNamespace())
    monkeypatch.setattr(smoke, "capture_observation", capture)
    monkeypatch.setattr(smoke, "phase3_entry_evidence_from_main_loop", lambda ctx, run, stamp: {
        "scenario_id": "device_air_purifier_plugin", "scenario_run_id": run,
        "entry_anchor_accessibility_focused": True, "entry_anchor_source": "verified_pre_loop_anchor",
        "entry_contract_digest": "fixture-digest"})
    if not proof_present:
        monkeypatch.setattr(smoke, "plugin_context_evidence", lambda *a, **kw: {})
    client = SimpleNamespace(
        _run=lambda *a, **kw: pytest.fail("native input dispatched"),
        last_start_open_summary={"open_completed": True, "entry_contract_reason": "success_verified",
                                 "entry_contract_detail": "plugin_open_verified"})
    ctx = SimpleNamespace(output_path=str(tmp_path / "result.xlsx"))
    return client, ctx, event_path


@pytest.mark.parametrize("proof_present", [True, False])
def test_rf5_unknown_entry_continues_read_only_and_persists_denial(monkeypatch, tmp_path, proof_present):
    client, ctx, events = _install_rf5(monkeypatch, tmp_path, proof_present=proof_present)
    seen = []
    def production_loop(c, dev, phase):
        with pytest.raises(SafetyBlocked):
            c._run(["shell", "input", "tap", "1", "1"], dev=dev)
        def collect(**kwargs):
            seen.append(kwargs)
            return {"move_result": "OBSERVED"}
        result = flow._phase6d3a_intercept_focus_step(
            original_collect=collect, collect_kwargs={"move": True, "direction": "next"},
            client=c, dev=dev, state=SimpleNamespace(), phase_ctx=phase,
            step_idx=1, tab_cfg={"scenario_id": "device_air_purifier_plugin"})
        assert result["move_result"] == "OBSERVED"
        return ["observed"]
    monkeypatch.setattr(flow, "_main_loop_phase", production_loop)
    def runner():
        assert flow._main_loop_phase(client, "offline", ctx) == ["observed"]
        return 0
    monkeypatch.setitem(sys.modules, "script_test", SimpleNamespace(main=runner))
    assert smoke.main(generalized=True, safe_navigation=True, rf5_harness=True) == 0
    assert seen == [{"move": False, "direction": "next"}]
    assert client.last_start_open_summary["trusted_entry_verified"] is False
    entry = json.loads((tmp_path / "phase4c_observation_only_entry.jsonl").read_text())
    assert entry["ownership"] is False and entry["action_authority"] == "NONE" and entry["visit_credit"] == 0
    observed = json.loads((tmp_path / "phase4c_observations.jsonl").read_text())
    assert observed["context"]["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]
    summary = json.loads((tmp_path / "phase5b_session_summary.jsonl").read_text())
    assert summary["observation_only"] is True and summary["visit_credit"] == 0
    records = [json.loads(line) for line in events.read_text().splitlines()]
    assert any(r["event"] == "REDIRECT_SUPPRESSED_OBSERVATION_ONLY" and r["dispatch_attempted"] is False for r in records)
    assert any(r["event"] == "RUNTIME_EVIDENCE_SAVED" for r in records)


def test_rf5_setup_failure_finalizes_without_inventing_runtime_counts(monkeypatch, tmp_path):
    client, ctx, events = _install_rf5(monkeypatch, tmp_path, setup_error=True)
    client.evidence_runtime = EvidenceRuntime(output_path=tmp_path / "failure.xlsx", enabled=True)
    client.evidence_runtime.start_scenario("device_air_purifier_plugin", plugin_family="content")
    monkeypatch.setitem(sys.modules, "script_test", SimpleNamespace(main=lambda: flow._main_loop_phase(client, "offline", ctx)))
    with pytest.raises(RuntimeError, match="capture setup failed"):
        smoke.main(generalized=True, safe_navigation=True, rf5_harness=True)
    records = [json.loads(line) for line in events.read_text().splitlines()]
    end = next(r for r in records if r["event"] == "RUNTIME_EVIDENCE_SAVED")
    assert end["reason"] == "MAIN_LOOP_SETUP_FAILED"
    assert end["native_dispatches"] is None and end["evaluated_attempts"] is None
    assert end["finalized_decisions"] is None and end["controlled_budget"] is None
    ledger = [json.loads(line) for line in client.evidence_runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    failure = next(r for r in ledger if r["event_type"] == "PHASE6D3A_HARNESS_SETUP_FAILED")
    assert failure["payload"]["error_type"] == "RuntimeError"
    assert failure["payload"]["action_authority"] == failure["payload"]["visit_credit"] == "UNKNOWN"


def test_unexpected_ownership_error_still_stops_and_finalizes(monkeypatch, tmp_path):
    from tb_runner import dynamic_context
    client, ctx, events = _install_rf5(monkeypatch, tmp_path)
    def unexpected(*a, **kw):
        raise ValueError("unexpected constructor failure")
    monkeypatch.setattr(dynamic_context, "DestinationOwnership", unexpected)
    monkeypatch.setitem(sys.modules, "script_test", SimpleNamespace(main=lambda: flow._main_loop_phase(client, "offline", ctx)))
    with pytest.raises(ValueError, match="unexpected constructor failure"):
        smoke.main(generalized=True, safe_navigation=True, rf5_harness=True)
    assert not (tmp_path / "phase4c_observation_only_entry.jsonl").exists()
    records = [json.loads(line) for line in events.read_text().splitlines()]
    assert any(r["event"] == "RUNTIME_EVIDENCE_SAVED" and r["reason"] == "MAIN_LOOP_SETUP_FAILED" for r in records)


def test_start_transport_exception_persists_existing_lineage_and_reraises_once(tmp_path, monkeypatch):
    from talkback_lib.hierarchy_file_transport import HierarchyTransportError

    runtime = EvidenceRuntime(output_path=tmp_path / "failed-start.xlsx", enabled=True)
    client = SimpleNamespace(evidence_runtime=runtime)
    lineage = {"schema_version": "phase6d3a-entry-diagnostics-v1", "diagnostic_only": True,
               "entry_operation": {"operation_id": "existing-tap", "receipt": "MATCHED"},
               "events": [{"event": "transition_impl_baseline", "payload": {"nodes": "x" * 40000}},
                          {"event": "transition_impl_poll", "payload": {"capture_id": "post", "currentness": "UNKNOWN"}}]}
    calls = []
    failure = HierarchyTransportError("WRITE_FAILED", "request-id")
    def fail_once(*args, **kwargs):
        calls.append(1)
        raise failure
    monkeypatch.setattr(flow, "_ensure_focusable_inventory", lambda *a, **kw: None)
    monkeypatch.setattr(flow, "_run_start_pipeline", fail_once)
    monkeypatch.setattr(flow, "_phase6d3a_attach_entry_diagnostics", lambda *a, **kw: deepcopy(lineage))
    with pytest.raises(HierarchyTransportError) as caught:
        flow._collect_tab_rows_inner(client, "offline", {"scenario_id": "fixture"}, [],
                                     str(tmp_path / "failed-start.xlsx"), str(tmp_path))
    assert caught.value is failure and len(calls) == 1
    records = [json.loads(line) for line in runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    diag = next(r for r in records if r["event_type"] == "PHASE6D3A_ENTRY_DIAGNOSTICS")
    assert diag["payload"]["diagnostics"] == lineage and len(json.dumps(diag)) > 32767
    error = next(r for r in records if r["event_type"] == "PHASE6D3A_START_PIPELINE_EXCEPTION")
    assert error["payload"]["error_type"] == "HierarchyTransportError"
    assert "WRITE_FAILED" in error["payload"]["error_detail"] and "request-id" in error["payload"]["error_detail"]
    assert error["payload"]["traversal_started"] is False
    assert error["payload"]["action_authority"] == error["payload"]["visit_credit"] == "UNKNOWN"
