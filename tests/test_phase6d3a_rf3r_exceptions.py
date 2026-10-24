"""Production client/bridge/native-boundary exception regressions; no device IO."""
from copy import deepcopy
from subprocess import CompletedProcess

import pytest
import test_phase4b_authority as fixture
from talkback_lib import A11yAdbClient
from talkback_lib.native_dispatch_evidence import native_dispatch_evidence
from tb_runner import scroll_reliability
from tb_runner.phase4a_planner import plan_shadow
from tb_runner.phase4b_authority import ExecutionBudget
from tb_runner.phase4b_execution import controlled_collect, focus_row


@pytest.mark.parametrize("graph", ["OFF", "SHADOW"])
@pytest.mark.parametrize("kind", ["focus", "scroll"])
@pytest.mark.parametrize("failure", ["read", "parse", "post_native_safety", "pre_native", "missing_receipt"])
@pytest.mark.parametrize("prior", ["precheck", "unknown", "foreign_operation"])
def test_real_operation_exception_accounting(monkeypatch, graph, kind, failure, prior):
    monkeypatch.setenv("TB_STATE_GRAPH_MODE", graph)
    native_calls, read_requests, rows = [], [], []
    def native(command, **kwargs):
        native_calls.append(command)
        return CompletedProcess(command, 0, stdout="ok", stderr="")
    monkeypatch.setattr("talkback_lib.adb_device.subprocess.run", native)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    client = A11yAdbClient(start_monitor=False)
    device = client._adb_device
    device._resolve_serial = lambda _dev: "offline-only"
    client.check_helper_status = lambda **kw: True
    client._safe_trace_print = lambda *a, **kw: None
    client._evidence_set_step = lambda *a, **kw: None
    client._evidence_begin_target_action = lambda *a, **kw: None
    client._evidence_correlation_extras = lambda: []
    client._evidence_action_sent = lambda *, action, req_id: setattr(client, "_evidence_active_request_id", req_id)
    client._normalize_action_result = lambda **kw: kw
    client.clear_logcat = lambda **kw: None
    stale = {"success": False, "status": "ERROR", "reason": "helper_unavailable"}
    if prior == "unknown":
        stale = {"status": "UNKNOWN", "reqId": "previous"}
    if prior == "foreign_operation":
        stale.update(operation_id="foreign", store_generation="foreign", reqId="previous")
    client.last_target_action_result = deepcopy(stale)
    client.last_scroll_result = deepcopy(stale)
    def broadcast(dev, action, extras):
        if failure == "pre_native":
            raise RuntimeError("before native boundary")
        return device._run_adb_command(["shell", "am", "broadcast", "-a", action, *extras], dev=dev)
    client._broadcast = broadcast
    if failure == "missing_receipt":
        monkeypatch.setattr(device, "_observe_native_dispatch", lambda *a: None)
    def reader(*args, **kw):
        request = kw.get("req_id", args[2] if len(args) > 2 else None)
        read_requests.append(request)
        if kind == "scroll":
            assert audit["scroll_operation_capture"]["request_id"] == request
            assert audit["scroll_operation_capture"]["operation_id"]
            assert audit["scroll_operation_capture"]["store_generation"]
        if failure == "post_native_safety":
            from tb_runner.phase5b_navigation import SafetyBlocked
            raise SafetyBlocked("post-native observation guard")
        if failure == "parse":
            # Exercise the actual response parser boundary after native receipt.
            import json
            return json.loads("{invalid")
        raise OSError("post-native response read")
    client._read_log_result = reader
    budget, audit = ExecutionBudget(), {}
    if kind == "focus":
        value, raw = fixture.value()
        selected = fixture.node("id.a", "A", accessibilityFocused=True)
        client.get_focus = lambda **kw: selected
        client.target_focus_commit = client._target_focus_commit_impl
        collect = lambda **kw: rows.append(kw) or {**focus_row(selected, "synthetic"), "focus_node": selected}
        decision = fixture.gate(value)
    else:
        value, raw = fixture.value(only_current=True, scroll=True)
        capability = dict(axis_contract="axis-v1", contradictory=False, can_scroll_forward=True,
            source="offline_fixture", container=dict(path="0.1", boundsInScreen="0,0,1000,900", axis="VERTICAL"))
        capture = dict(nodes=[], capability=capability, viewport=scroll_reliability.viewport([], "synthetic"))
        monkeypatch.setattr(scroll_reliability, "capture", lambda *a, **kw: deepcopy(capture))
        client.scroll = client._scroll_impl
        collect = lambda **kw: rows.append(kw) or {}
        decision = fixture.gate(value, evidence=fixture.trusted(scroll_container_proven=True))
    controlled_collect(client=client, dev="offline", scenario="synthetic", step=1, raw=raw,
        recommendation=plan_shadow(value), decision=decision, budget=budget, collect=collect,
        collect_kwargs=dict(move=True, direction="next", step_index=1), refresh=lambda: {}, output_dir="", audit=audit)
    dispatched = failure in {"read", "parse", "post_native_safety"}
    assert audit["dispatch_status"] == ("DISPATCHED" if dispatched else "UNKNOWN")
    assert budget.actions == int(dispatched)
    assert budget.fallback_count == 0
    assert len(rows) == 1 and rows[0]["move"] is False
    assert len(native_calls) == (0 if failure == "pre_native" else 1)
    assert client._broadcast is broadcast
    assert client.last_target_action_result == stale  # compatibility cache retained, never authoritative
    if dispatched:
        assert read_requests == [audit["current_request_id"]]
        # The same typed current receipt cannot charge the budget again.
        proof = audit["dispatch_evidence"]
        from talkback_lib.native_dispatch_evidence import NativeDispatchCheckpoint
        cp = NativeDispatchCheckpoint(proof["operation_id"], proof["store_generation"], 0, "VALID", "")
        evidence = native_dispatch_evidence(cp, device.native_dispatch_receipts,
            request_id=audit["current_request_id"], native_boundary_entered=True, operation_error=True)
        assert evidence.dispatch_status == "DISPATCHED"
        assert not budget.reserve_dispatched_once(evidence=evidence, mode=decision.mode,
            target="ignored", inventory="ignored", state=("ignored", ()))
        assert budget.actions == 1
    else:
        assert budget.degraded


@pytest.mark.parametrize("graph", ["OFF", "SHADOW"])
def test_real_focus_current_helper_precheck_not_dispatched(monkeypatch, graph):
    monkeypatch.setenv("TB_STATE_GRAPH_MODE", graph)
    client = A11yAdbClient(start_monitor=False)
    client.check_helper_status = lambda **kw: False
    client._safe_trace_print = lambda *a, **kw: None
    client._evidence_set_step = lambda *a, **kw: None
    client._normalize_action_result = lambda **kw: kw
    value, raw = fixture.value()
    node = raw["focus_node"]
    client.get_focus = lambda **kw: node
    client.target_focus_commit = client._target_focus_commit_impl
    audit, budget = {}, ExecutionBudget()
    controlled_collect(client=client, dev="offline", scenario="synthetic", step=1, raw=raw,
        recommendation=plan_shadow(value), decision=fixture.gate(value), budget=budget,
        collect=lambda **kw: focus_row(node, "synthetic"), collect_kwargs=dict(move=True),
        refresh=lambda: {}, output_dir="", audit=audit)
    assert audit["dispatch_status"] == "NOT_DISPATCHED"
    assert budget.actions == 0
