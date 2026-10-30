"""Offline ACTIVE production-evidence to Phase4/5/native/reconciliation tests."""
from copy import deepcopy
from subprocess import CompletedProcess
from types import SimpleNamespace

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


def test_active_component_unknown_blocks_before_dispatch(monkeypatch):
    f = active_fixture(monkeypatch)
    row = run(f)
    audit = row["phase6d3a_redirect"]
    readiness = audit["common_readiness"]

    assert readiness["readiness_status"] == "UNKNOWN"
    assert "PLUGIN_CONTEXT_UNKNOWN" in readiness["reason_codes"]
    assert audit["ready"] is False
    assert audit["dispatch_count"] == 0
    assert audit["visit_credit"] == 0
    assert readiness.get("phase5_permit_issued") is False
    assert f.native == []
    assert f.client._phase6d3a_controlled_budget.actions == 0
    assert f.controller.budget.redirects_used == 0
    assert f.controller.budget.consecutive_failures == 0
    assert row.get("visit_record_status") != "RECORDED"


def test_controller_reset_keeps_component_unknown_dispatch_budget_empty(monkeypatch):
    f = active_fixture(monkeypatch)
    row = run(f)
    audit = row["phase6d3a_redirect"]
    store = f.client._adb_device.native_dispatch_receipts
    assert audit["common_readiness"]["readiness_status"] == "UNKNOWN"
    assert "PLUGIN_CONTEXT_UNKNOWN" in audit["common_readiness"]["reason_codes"]
    assert audit["dispatch_count"] == 0
    assert f.native == []
    assert f.controller.budget.redirects_used == 0
    sequence, generation = store.receipt_watermark(), store.generation_id
    flow._phase6d3a_reset_run_state(client=f.client, run_id="new-run")
    assert not f.controller.dispatch_operations
    assert not f.controller.reconciled_operations
    assert f.controller.budget.redirects_used == 0
    assert store.receipt_watermark() == sequence and store.generation_id == generation
