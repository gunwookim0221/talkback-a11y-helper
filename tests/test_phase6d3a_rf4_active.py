"""Offline ACTIVE production-evidence to Phase4/5/native/reconciliation tests."""
from copy import deepcopy
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest
from talkback_lib import A11yAdbClient
from tb_runner import collection_flow as flow
from tb_runner.phase4b_authority import ExecutionBudget
from tb_runner.phase4a_planner import plan_shadow
from tb_runner.phase4b_execution import focus_row
from test_phase6d3a_rf2_shadow import _production_shaped_shadow_fixture


def active_fixture(monkeypatch, case="success"):
    monkeypatch.setenv("TB_STATE_GRAPH_MODE", "SHADOW")
    f = _production_shaped_shadow_fixture()
    client = A11yAdbClient(start_monitor=False)
    device = client._adb_device
    client.__dict__.update(vars(f.client))
    client._adb_device = device
    device.shadow_evidence_clock = f.clock
    device._resolve_serial = lambda _dev: "offline"
    f.client = client
    f.controller.mode = "ACTIVE"
    client._phase6d3a_controlled_budget = ExecutionBudget()
    client._evidence_set_step = lambda *a, **kw: None
    client._evidence_begin_target_action = lambda *a, **kw: None
    client._evidence_correlation_extras = lambda: []
    client._evidence_action_sent = lambda *, action, req_id: setattr(client, "_evidence_active_request_id", req_id)
    client._evidence_helper_ack = lambda *a, **kw: None
    client._safe_trace_print = lambda *a, **kw: None
    client.check_helper_status = lambda **kw: True
    # Real wrapper/recorder/firewall/shared ADB path; subprocess only is fake.
    from test_window_lifecycle import _snapshot
    f.lifecycle_reads = []
    f.lifecycle_output = lambda: _snapshot("12345")
    f.lifecycle.client = client
    client.target_focus_commit = A11yAdbClient.target_focus_commit.__get__(client, A11yAdbClient)
    client._run = lambda args, dev=None, **kw: device._run_adb_command(args, dev=dev, **kw)
    f.native, f.collected = [], []
    target = plan_shadow(f.planner_input).to_dict()["recommended_target"]
    f.target = next(n for n in f.raw["nodes"] if n.get("viewIdResourceName") == target["resource_id"]
                    and n.get("boundsInScreen") == target["bounds"])
    f.focus = deepcopy(f.raw["focus_node"])
    def native(command, **kw):
        from talkback_lib.window_lifecycle import is_lifecycle_readonly_command
        if is_lifecycle_readonly_command(command[3:] if command[:2] == ["adb", "-s"] else command[1:]):
            f.lifecycle_reads.append(command)
            return CompletedProcess(command, 0, stdout=f.lifecycle_output(), stderr="")
        f.native.append(command)
        if case != "no_effect":
            f.focus = {**f.target, "accessibilityFocused": True}
        return CompletedProcess(command, 0, stdout="ok", stderr="")
    monkeypatch.setattr("talkback_lib.adb_device.subprocess.run", native)
    monkeypatch.setattr("time.sleep", lambda *a: None)
    f.lifecycle.capture("fixture", "PING")
    client.get_focus = lambda **kw: deepcopy(f.focus)
    def read(*args, **kwargs):
        request = kwargs.get("req_id", args[2] if len(args)>2 else None)
        return dict(success=True, status="SUCCESS", reqId=request)
    client._read_log_result = read
    def collect(**kw):
        f.collected.append(kw)
        assert kw.get("move") is False
        return {**focus_row(f.focus, f.scenario_id), "focus_node": deepcopy(f.focus),
                "dump_tree_nodes": deepcopy(f.raw["nodes"]), "scenario_type": "content"}
    f.collect = collect
    return f


def run(f):
    return flow._phase6d3a_intercept_focus_step(original_collect=f.collect,
        collect_kwargs=dict(move=True, direction="next", step_index=8),
        client=f.client, dev="offline", state=f.state, phase_ctx=f.phase_ctx, step_idx=8,
        tab_cfg={**f.tab_cfg, "max_steps": 20})


def test_active_positive_existing_production_authorities(monkeypatch):
    f = active_fixture(monkeypatch)
    row = run(f)
    audit = row["phase6d3a_redirect"]
    assert audit.get("common_readiness", {}).get("readiness_status") == "READY", audit
    assert audit["dispatch_count"] == 1, audit
    assert len(f.native) == 1
    assert audit["dispatch_evidence"]["dispatch_status"] == "DISPATCHED"
    assert f.controller.budget.redirects_used == f.client._phase6d3a_controlled_budget.actions == 1
    assert f.controller.budget.consecutive_failures == 0
    assert len(f.collected) == 1
    assert any(e["record"].get("event") == "NATIVE_DISPATCH_AUTHORIZED"
               for e in audit["phase5_authorization_events"]), audit["phase5_authorization_events"]
    # The adapter has not awarded visits. Use the real production reconciliation.
    assert row.get("visit_record_status") != "RECORDED"
    flow._apply_focus_reconciliation(client=f.client, dev="offline", row=row,
        previous_row=focus_row(f.raw["focus_node"], f.scenario_id),
        state=SimpleNamespace(reliability_metrics=None, consumed_cluster_signatures=set()),
        progress_decision=None, visit_decision=None)
    assert row["focus_transition_status"] == "CONFIRMED_MOVED", row
    assert row["visit_record_status"] == "RECORDED"
    from tb_runner.traversal_reliability import TraversalMetrics
    metrics = TraversalMetrics()
    metrics.observe_reconciliation(row)
    assert metrics.reconciled_new_visits == 1
    # Feed actual production result to the existing pure progress evaluator.
    from test_exploration_progress import _inputs
    from tb_runner.exploration_progress import evaluate_exploration_progress
    values = _inputs(8, state_id=audit["state_id"], production={
        "focus_transition_status": row["focus_transition_status"],
        "visit_record_status": row["visit_record_status"],
        "reconciled_visit_instance_id": row["reconciled_visit_instance_id"],
        "focus_authority": "ACCESSIBILITY", "visit_authority": "PRODUCTION",
        "actual_focus_accessibility_focused": True,
        "visit_outcome": "NEW_VISIT" if row["visit_record_status"] == "RECORDED" else "REVISIT"})
    progress = evaluate_exploration_progress(**values)
    assert "MEANINGFUL_NEW_VISIT" in progress.reason_codes
    flow._phase6d3a_record_production_reconciliation(client=f.client, row=row)
    assert row["phase6d3a_redirect"]["production_target_reached"]
    assert f.controller.metrics.counters["REDIRECT_TARGET_REACHED_COUNT"] == 1
    # Reconciliation replay cannot update failure/metrics again.
    replay = deepcopy(row)
    replay["phase6d3a_redirect"].pop("production_reconciliation_recorded", None)
    flow._phase6d3a_record_production_reconciliation(client=f.client, row=replay)
    assert f.controller.metrics.counters["REDIRECT_TARGET_REACHED_COUNT"] == 1


@pytest.mark.parametrize("case", ["readiness_blocked", "readiness_unknown", "epoch", "watermark",
    "target", "binding", "presence", "helper", "lifecycle", "planner", "safety", "budget", "disabled", "substate", "controlled_budget"])
def test_active_negative_zero_native(monkeypatch, case):
    from contextlib import contextmanager
    from tb_runner.phase5b_navigation import SafeNavigationSession
    f = active_fixture(monkeypatch)
    if case == "readiness_blocked":
        f.row["overlay"]["observed"] = True
    elif case == "readiness_unknown":
        f.row.pop("command_ack_result", None)
        f.row.pop("command_ack_normalized_result", None)
    elif case == "budget":
        f.controller.budget.redirects_used = 5
    elif case == "controlled_budget":
        f.client._phase6d3a_controlled_budget.actions = 5
    elif case == "disabled":
        f.controller.budget.active_disabled = True
    else:
        original = SafeNavigationSession.authorize_focus_target
        @contextmanager
        def authorization(session, **kw):
            with original(session, **kw) as permit:
                if case == "epoch":
                    f.clock.dispatch(["shell", "input", "keyevent", "4"])
                elif case == "substate":
                    f.record["selected_frontier"]["substate_ref"] = "stale"
                elif case == "watermark":
                    f.record["decision_watermark"] += 1
                elif case in {"target", "binding", "presence"}:
                    nodes = f.row["dump_tree_nodes"]
                    if case == "target":
                        nodes[0]["boundsInScreen"] = "0,0,1,1"
                    elif case == "binding":
                        nodes.append(deepcopy(nodes[0]))
                    else:
                        nodes.clear()
                elif case == "helper":
                    f.row["phase5c_primary_action_request_id"] = "foreign"
                elif case == "lifecycle":
                    from test_window_lifecycle import _snapshot
                    f.lifecycle_output = lambda: _snapshot("")
                elif case == "planner":
                    f.state.stop_triggered = True
                elif case == "safety":
                    # Mutate the actual authorization, not the final allow result.
                    permit["action_type"] = "CLICK"
                yield permit
        monkeypatch.setattr(SafeNavigationSession, "authorize_focus_target", authorization)
    row = run(f)
    a = row["phase6d3a_redirect"]
    assert len(f.native) == 0, a
    assert f.controller.budget.redirects_used == (5 if case == "budget" else 0)
    assert f.client._phase6d3a_controlled_budget.actions == (5 if case == "controlled_budget" else 0)
    assert f.controller.budget.consecutive_failures == 0
    assert len(f.collected) == 1
    assert a["fallback_count"] == 1


@pytest.mark.parametrize("failure", ["read", "parse", "missing_receipt", "precheck", "fallback", "no_effect", "ack_error", "observation_exception"])
def test_active_exception_accounting_no_duplicate(monkeypatch, failure):
    f = active_fixture(monkeypatch, failure)
    if failure in {"read", "parse", "missing_receipt"}:
        if failure == "missing_receipt":
            monkeypatch.setattr(f.client._adb_device, "_observe_native_dispatch", lambda *a: None)
        def reader(*a, **kw):
            if failure == "parse":
                import json
                return json.loads("{invalid")
            raise OSError("post-native read")
        f.client._read_log_result = reader
    elif failure == "ack_error":
        f.client._read_log_result = lambda *a, **kw: dict(success=False, status="ERROR", reqId=a[2])
    elif failure == "observation_exception":
        def failed_focus(**kw):
            raise RuntimeError("post-native focus observation")
        f.client.get_focus = failed_focus
        with pytest.raises(RuntimeError):
            run(f)
        assert len(f.native) == 1
        assert f.controller.budget.redirects_used == f.client._phase6d3a_controlled_budget.actions == 1
        assert not f.collected
        assert f.controller.budget.consecutive_failures == 0
        return
    elif failure == "precheck":
        f.client.last_target_action_result = dict(status="ERROR", reason="helper_unavailable", reqId="old")
        f.client._evidence_active_request_id = "old"
        f.client.check_helper_status = lambda **kw: False
    elif failure == "fallback":
        f.controller.budget.active_disabled = True
        def failed_collect(**kw):
            f.collected.append(kw)
            raise OSError("passive read failed")
        f.collect = failed_collect
    elif failure == "no_effect":
        f.client.get_focus = lambda **kw: deepcopy(f.raw["focus_node"])
    row = run(f)
    a = row["phase6d3a_redirect"]
    expected = int(failure in {"read", "parse", "no_effect", "ack_error"})
    assert f.client._phase6d3a_controlled_budget.actions == expected
    assert f.controller.budget.redirects_used == expected
    assert len(f.native) == int(failure not in {"precheck", "fallback"})
    assert f.controller.budget.consecutive_failures == 0  # only production outcome may change it
    if failure == "missing_receipt":
        assert a["status"] == "UNKNOWN"
        assert f.controller.budget.active_disabled
        assert a["fallback_count"] == 0
    elif failure in {"read", "parse"}:
        assert a["dispatch_evidence"]["dispatch_status"] == "DISPATCHED"
        assert a["fallback_count"] == 0
    elif failure == "no_effect":
        assert a["fallback_count"] == 1
        flow._apply_focus_reconciliation(client=f.client, dev="offline", row=row,
            previous_row=focus_row(f.raw["focus_node"], f.scenario_id),
            state=SimpleNamespace(reliability_metrics=None, consumed_cluster_signatures=set()),
            progress_decision=None, visit_decision=None)
        flow._phase6d3a_record_production_reconciliation(client=f.client, row=row)
        assert f.controller.budget.consecutive_failures == 1
    assert a["fallback_count"] <= 1


def test_controller_reset_and_typed_event_dedup(monkeypatch):
    f = active_fixture(monkeypatch)
    row = run(f)
    from talkback_lib.native_dispatch_evidence import NativeDispatchCheckpoint, native_dispatch_evidence
    proof = row["phase6d3a_redirect"]["dispatch_evidence"]
    store = f.client._adb_device.native_dispatch_receipts
    cp = NativeDispatchCheckpoint(proof["operation_id"], proof["store_generation"], 0, "VALID")
    evidence = native_dispatch_evidence(cp, store, request_id=proof["current_request_id"], native_boundary_entered=True)
    assert not f.controller.account_dispatch(evidence, hint=row["phase6d3a_redirect"])
    assert f.controller.budget.redirects_used == 1
    sequence, generation = store.receipt_watermark(), store.generation_id
    flow._phase6d3a_reset_run_state(client=f.client, run_id="new-run")
    assert not f.controller.dispatch_operations
    assert not f.controller.reconciled_operations
    assert f.controller.budget.redirects_used == 0
    assert store.receipt_watermark() == sequence and store.generation_id == generation
