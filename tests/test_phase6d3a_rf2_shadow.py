from copy import deepcopy
from types import SimpleNamespace

import pytest

from tb_runner.exploration_redirect import ExplorationRedirectController


def _production_shaped_shadow_fixture(*, overlay=False):
    """Offline fixture using the production row, context, discovery and frontier adapters."""
    # Production policy must already exist at the decision cut. This fixture
    # loads it before constructing the decision, never inside pre-capture.
    from tb_runner.action_safety import default_config
    default_config()

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_phase4b_authority import value as authority_value
    from tb_runner.discovery_candidates import build_discovery_snapshot
    from tb_runner.frontier_shadow import FrontierShadowRuntime, capture_reconciled_inventory
    from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop
    from tb_runner.phase4a_inputs import runtime_input
    from tb_runner.phase4a_planner import plan_shadow
    from tb_runner.scenario_config import TAB_CONFIGS
    from tb_runner.state_graph import build_graph_state_identity
    from tb_runner.state_registry import StateRegistry
    from talkback_lib.window_lifecycle import WindowLifecycleRecorder
    from talkback_lib.exploration_evidence_clock import EvidenceClock
    from tb_runner import collection_flow

    scenario_id, run_id = "device_tv_plugin", "rf2-offline-run"
    tab_cfg = next(config for config in TAB_CONFIGS if config["scenario_id"] == scenario_id)
    planner_template, raw = authority_value(context="VERIFIED_PLUGIN_CONTEXT")
    raw.update(
        scenario_id=scenario_id, scenario_run_id=run_id, step=7,
        timestamp="2026-10-22T01:02:03+09:00", capture_id="rf2-capture-7",
        package_name="com.samsung.android.oneconnect", activity_name="pkg.WebPluginActivity",
        context_source="window_current_focus", navigation_context=None, selected_tab=None,
        observation_coverage="OBSERVED_FULL", overlay={"observed": bool(overlay)},
        display_bounds=[0, 0, 1000, 1000],
        nodes=[*raw["nodes"], dict(viewIdResourceName="plugin:body", text="TV",
            className="android.widget.TextView", boundsInScreen="0,0,900,80",
            visibleToUser=True, enabled=True, clickable=False, focusable=False)],
    )
    raw.pop("phase3_entry_evidence", None)
    raw.pop("phase3_plugin_context_evidence", None)
    # The generic plugin context contract is derived from the real main-loop
    # entry evidence and the already-recorded start summary during evaluation.
    anchor = {
        "timestamp": "2026-10-22T01:02:00+09:00",
        "actual_focus_accessibility_focused": True,
        "actual_focus_payload_source": "verified_pre_loop_anchor",
    }
    phase_ctx = SimpleNamespace(tab_cfg=tab_cfg, rows=[anchor], all_rows=[])
    client = SimpleNamespace(last_start_open_summary={
        "open_completed": True, "entry_contract_reason": "success_verified",
        "entry_contract_detail": "plugin_open_verified",
    })
    client._preflight_talkback_pid = "12345"
    context = collection_flow._phase6d3a_initialize_redirect_context(
        client=client, dev="offline", phase_ctx=phase_ctx, run_id=run_id)
    raw["phase3_entry_evidence"] = context["phase3_entry_evidence"]
    raw["navigation_epoch"] = context["navigation_epoch"]
    from tb_runner.plugin_context_contract import plugin_context_evidence
    raw["phase3_plugin_context_evidence"] = plugin_context_evidence(
        raw["phase3_entry_evidence"], raw, client.last_start_open_summary,
        raw["navigation_epoch"])
    assert raw["phase3_plugin_context_evidence"]

    registry = StateRegistry("rf2-test-discovery")
    snapshot = build_discovery_snapshot(raw, registry)
    planner_input = runtime_input(
        snapshot, "VERIFIED_PLUGIN_CONTEXT", scenario_id=scenario_id,
        client=client, state=SimpleNamespace(), rows=(), capability=raw.get("capability"))
    planner_input = __import__("dataclasses").replace(
        planner_input, history=__import__("dataclasses").replace(
            planner_input.history, scenario_id=scenario_id))
    plan = plan_shadow(planner_input).to_dict()
    assert plan["recommended_action"] == "FOCUS_CANDIDATE", plan
    target = plan["recommended_target"]
    target_node = next(node for node in raw["nodes"]
                       if (node.get("viewIdResourceName") or node.get("resourceId")) == target["resource_id"]
                       and node.get("boundsInScreen") == target["bounds"])

    graph_identity = build_graph_state_identity(raw)
    assert graph_identity.state_id
    from tb_runner.frontier_shadow import production_candidate
    production = production_candidate(state_id=graph_identity.state_id,
                                      scenario_id=scenario_id, candidate=target_node)
    assert production is not None

    # Use the existing production-shaped closed-decision test fixture for the
    # scheduler output, then bind it to this actual target and observation.
    from test_exploration_redirect import _scheduler_record
    record, clock = _scheduler_record(
        target_instance=production["target_identity"]["instance_id"],
        target_identity=production["target_identity"], state_id=graph_identity.state_id)
    record["decision_id"] = scenario_id + ":closed:7"
    record["decision_watermark"] = 7
    record["step"] = 7
    record["state"] = {**record["state"], "state_id": graph_identity.state_id}
    record["selected_frontier_execution_ready"] = False
    record["selected_frontier_execution_evidence"] = {"status": "BLOCKED"}
    raw["_exploration_observation"] = deepcopy(record["observation_alignment"])

    row = {
        **{key: deepcopy(raw.get(key)) for key in (
            "scenario_id", "scenario_run_id", "timestamp", "package_name", "activity_name",
            "context_source", "navigation_context", "selected_tab", "observation_coverage",
            "display_bounds", "overlay", "capability")},
        "step_index": 7, "focus_node": deepcopy(raw["focus_node"]),
        "actual_focus_node": deepcopy(raw["focus_node"]),
        "actual_focus_accessibility_focused": True,
        "dump_tree_nodes": deepcopy(raw["nodes"]),
        "_exploration_observation": deepcopy(raw["_exploration_observation"]),
        "phase6_current_action_type": "SMART_NEXT",
        "smart_nav_req_id": "rf2-prior-request", "phase5c_primary_action_request_id": "rf2-prior-request",
        "command_ack_status": "SUCCESS", "command_ack_result": "MOVED",
        "command_ack_normalized_result": "moved", "focus_transition_status": "CONFIRMED_UNCHANGED",
        "reconciliation_status": "RESOLVED", "phase3_entry_evidence": deepcopy(context["phase3_entry_evidence"]),
        "phase3_plugin_context_evidence": deepcopy(raw["phase3_plugin_context_evidence"]),
        "capture_id": raw["capture_id"],
        "navigation_epoch": context["navigation_epoch"],
    }
    state = SimpleNamespace(
        previous_step_row=row, content_terminal=None,
        reliability_metrics=SimpleNamespace(visited=set()),
        post_realign_pending_steps=0, food_scan_recovery_pending=False,
        stop_triggered=False,
    )
    phase_ctx.all_rows = [row]
    phase_ctx.state = state
    lifecycle = WindowLifecycleRecorder(client, "offline", scenario_id, None)
    lifecycle.step = 7
    lifecycle.event_count = 1
    client._window_lifecycle_recorder = lifecycle
    client._adb_device = SimpleNamespace(shadow_evidence_clock=clock)
    client._phase6d3a_main_loop_state = state
    client._phase6d3a_phase_context = phase_ctx
    client._phase6d3a_controlled_budget = SimpleNamespace(actions=0, max_actions=5)
    controller = ExplorationRedirectController(mode="SHADOW", graph_mode="SHADOW")
    client._phase6d3a_redirect_controller = controller
    client._phase6d_exploration_shadow_runtime = SimpleNamespace(decisions=[record])
    frontier_runtime = FrontierShadowRuntime(run_id=run_id, scenario_id=scenario_id,
                                              evidence_clock=clock)
    capture_reconciled_inventory(
        frontier_runtime, row=row, candidates=raw["nodes"], scenario_id=scenario_id,
        raw_nodes=raw["nodes"], projection_complete=True)
    client._phase6c2_frontier_shadow_runtime = frontier_runtime
    client._phase6d3a_redirect_context["registry"] = registry
    client.get_focus = lambda **_kwargs: pytest.fail("SHADOW added a focus query")
    client.dump_tree = lambda **_kwargs: pytest.fail("SHADOW added a hierarchy query")
    client._run = lambda *_args, **_kwargs: pytest.fail("SHADOW added an ADB/OS query")
    return SimpleNamespace(
        client=client, state=state, phase_ctx=phase_ctx, row=row, raw=raw,
        record=record, clock=clock, controller=controller, lifecycle=lifecycle,
        frontier_runtime=frontier_runtime, tab_cfg=tab_cfg, scenario_id=scenario_id,
        planner_input=planner_input, production=production,
    )


def _production_collector_result():
    return {
        "move_result": "moved",
        "focus_transition_status": "CONFIRMED_MOVED",
        "focus_reconciliation_confidence": "STRICT",
        "actual_focus_accessibility_focused": True,
        "visit_record_status": "RECORDED",
        "reconciled_visit_instance_id": "existing-production-instance",
        "status": "CONTINUE",
        "stop_reason": "",
        "summary": "existing production summary",
    }


def _run_shadow(fixture, *, collector_delay_seconds=0.0, collector_hook=None, tab_cfg_override=None):
    from tb_runner import collection_flow
    import time

    calls = []
    expected = _production_collector_result()
    def collect(**kwargs):
        calls.append(kwargs)
        if collector_delay_seconds:
            time.sleep(collector_delay_seconds)
        if collector_hook is not None:
            collector_hook()
        return dict(expected)
    result = collection_flow._phase6d3a_intercept_focus_step(
        original_collect=collect, collect_kwargs={"move": True, "direction": "next"},
        client=fixture.client, dev="offline", state=fixture.state,
        phase_ctx=fixture.phase_ctx, step_idx=8,
        tab_cfg=tab_cfg_override if tab_cfg_override is not None else {
                 "scenario_id": fixture.scenario_id, "scenario_type": "content",
                 "screen_context_mode": "new_screen"})
    return result, expected, calls, getattr(fixture.client, "_phase6d3a_last_step_audit", None)


def test_production_shaped_shadow_uses_actual_provider_common_bundle_and_evaluator_once():
    fixture = _production_shaped_shadow_fixture()
    budget_before = (fixture.client._phase6d3a_controlled_budget.actions,
                     fixture.controller.budget.redirects_used,
                     fixture.controller.budget.consecutive_failures)
    receipts_before = len(fixture.clock.receipts)
    result, expected, calls, audit = _run_shadow(fixture)

    assert result == expected
    assert len(calls) == 1
    assert audit["readiness_status"] == "READY", (audit.get("reason_codes"), audit.get("conditions"),
        audit.get("proof"), audit.get("readiness_trace"))
    assert audit["ready"] is True
    assert audit["proof"]["build_status"] == "COMPLETE"
    assert audit["proof"]["source_refs"]["planner"] == "phase4a_planner.plan_shadow"
    assert audit["proof"]["source_refs"]["binding"].startswith(
        "phase4b_target_binding.resolve_focus_target:")
    assert audit["identity_bridge"]["status"] == "EXACT_ONE"
    assert audit["execution_authority"] == "NONE"
    assert audit["phase5_permit_issued"] is False
    assert audit["dispatch_count"] == 0
    assert audit["visit_credit"] == 0
    assert len(fixture.clock.receipts) == receipts_before
    assert budget_before == (fixture.client._phase6d3a_controlled_budget.actions,
                             fixture.controller.budget.redirects_used,
                             fixture.controller.budget.consecutive_failures)
    assert fixture.controller.metrics.counters["SHADOW_READY_COUNT"] == 1
    assert fixture.controller.metrics.counters["SHADOW_RECOMMENDATION_COUNT"] == 1
    assert fixture.controller.metrics.counters["SHADOW_PROOF_MATCH_COUNT"] == 1
    assert fixture.controller.metrics.counters["SHADOW_IDENTITY_EXACT_ONE_COUNT"] == 1
    assert fixture.controller.metrics.counters["SHADOW_PLANNER_ALLOWED_COUNT"] == 1
    assert fixture.controller.metrics.counters["SHADOW_SAFETY_ALLOWED_COUNT"] == 1
    assert fixture.controller.metrics.counters["SHADOW_FALSE_READY_COUNT"] == 0
    latency = fixture.controller.metrics.latency_summary()
    assert latency["count"] == 1 and latency["p50_ms"] is not None and latency["p95_ms"] is not None
    assert fixture.controller.events[-1]["readiness_trace"]["event_id"] == audit["readiness_trace"]["event_id"]
    assert audit["readiness_trace"]["proof"]["proof_complete"] is True
    trace = audit["readiness_trace"]
    assert trace["event_id"] == "rf2-readiness:" + ":".join((
        audit["run_id"], audit["decision_id"], audit["observation_id"]))
    assert trace["decision_watermark"] == audit["decision_watermark"]
    assert trace["frontier"]["priority_class"] == "P0"
    assert trace["proof"]["source_refs"]["safety_assessment"].startswith(
        "phase5a_safety.SafetySession.assess:")
    assert trace["conditions"]["lifecycle_status"] == "CLEAR"
    assert trace["conditions"]["lifecycle_evidence"]["process_evidence"] == "STABLE"
    assert trace["frame"]["lifecycle_evidence"]["previous_pid_present"] is True
    assert trace["dispatch_count"] == 0 and trace["visit_credit"] == 0


@pytest.mark.parametrize("blocker,expected_status", [
    ("talkback_restart", "BLOCKED"), ("helper_unavailable", "BLOCKED"),
    ("talkback_pid_gap", "BLOCKED"),
    ("overlay", "BLOCKED"), ("recovery", "BLOCKED"), ("transition", "BLOCKED"),
    ("lifecycle_missing", "UNKNOWN"), ("helper_missing", "UNKNOWN"),
    ("observation_stale", "UNKNOWN"), ("inventory_incomplete", "UNKNOWN"),
])
def test_known_blockers_and_missing_evidence_never_ready(blocker, expected_status):
    fixture = _production_shaped_shadow_fixture(overlay=blocker == "overlay")
    if blocker == "talkback_restart":
        fixture.lifecycle.restart_event = {"talkback_process_event": "pid_changed"}
    elif blocker == "talkback_pid_gap":
        fixture.lifecycle._track_talkback_process({
            "talkback_pid": None, "talkback_enabled": True,
            "timestamp": "2026-10-22T01:03:00+09:00", "step": 8,
            "phase": "test", "action_type": "SMART_NEXT",
        })
    elif blocker == "helper_unavailable":
        fixture.row["command_ack_result"] = "ACK_TIMEOUT"
    elif blocker == "recovery":
        fixture.state.food_scan_recovery_pending = True
    elif blocker == "transition":
        fixture.state.post_realign_pending_steps = 1
    elif blocker == "lifecycle_missing":
        fixture.client._window_lifecycle_recorder = None
    elif blocker == "helper_missing":
        fixture.row.pop("smart_nav_req_id", None)
        fixture.row.pop("phase5c_primary_action_request_id", None)
        fixture.row["command_ack_status"] = "UNKNOWN"
    elif blocker == "observation_stale":
        fixture.record["observation_alignment"]["scope_id"] = "foreign-scope"
    elif blocker == "inventory_incomplete":
        fixture.frontier_runtime._latest_inventory["inventory_complete"] = False

    result, expected, calls, audit = _run_shadow(fixture)
    assert result == expected
    assert len(calls) == 1
    if blocker == "observation_stale":
        assert audit["readiness_status"] in {"BLOCKED", "UNKNOWN"}
    else:
        assert audit["readiness_status"] == expected_status
    assert audit["ready"] is False
    assert audit["dispatch_count"] == 0
    assert audit["visit_credit"] == 0
    assert fixture.controller.metrics.counters["SHADOW_FALSE_READY_COUNT"] == 0
    if blocker == "talkback_pid_gap":
        assert fixture.lifecycle.saw_enabled_process_gap is True
        assert audit["conditions"]["lifecycle_status"] == "BLOCKED"
        assert audit["conditions"]["lifecycle_evidence"]["process_evidence"] == "ENABLED_BUT_PID_MISSING"
        assert audit["conditions"]["lifecycle_evidence"]["reason"] == "TALKBACK_ENABLED_PROCESS_GAP"
    assert fixture.controller.metrics.counters[
        "SHADOW_" + audit["readiness_status"] + "_COUNT"] == 1
    assert len(fixture.clock.receipts) == 1  # only the pre-existing fixture-owned action


def test_old_phase6_ready_flag_is_not_a_second_shadow_authority():
    fixture = _production_shaped_shadow_fixture()
    assert fixture.record["selected_frontier_execution_ready"] is False
    _result, _expected, calls, audit = _run_shadow(fixture)
    assert len(calls) == 1
    assert audit["readiness_status"] == "READY"


@pytest.mark.parametrize("failure", ["provider", "evaluator", "trace"])
def test_diagnostic_failure_preserves_result_and_collector_once(monkeypatch, failure):
    from tb_runner import collection_flow, redirect_evidence

    fixture = _production_shaped_shadow_fixture()
    calls = []
    marker = object()
    def collect(**kwargs):
        calls.append(kwargs)
        return marker
    if failure == "provider":
        monkeypatch.setattr(redirect_evidence.ProductionRedirectProofProvider,
                            "build_target_proof_set",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider")))
    elif failure == "evaluator":
        monkeypatch.setattr(redirect_evidence, "evaluate_redirect_readiness",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("evaluator")))
    else:
        monkeypatch.setattr(fixture.controller, "record",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("trace")))
    result = collection_flow._phase6d3a_intercept_focus_step(
        original_collect=collect, collect_kwargs={"move": True, "direction": "next"},
        client=fixture.client, dev="offline", state=fixture.state,
        phase_ctx=fixture.phase_ctx, step_idx=8,
        tab_cfg={"scenario_id": fixture.scenario_id, "scenario_type": "content",
                 "screen_context_mode": "new_screen"})
    assert result is marker
    assert len(calls) == 1
    assert fixture.client._phase6d3a_last_step_audit["status"] == "DIAGNOSTIC_ERROR"
    assert fixture.client._phase6d3a_last_step_audit["dispatch_count"] == 0
    assert len(fixture.clock.receipts) == 1


@pytest.mark.parametrize("failure", ["none", "preparation", "currentness", "provider", "evaluator", "trace"])
def test_shadow_diagnostic_failure_preserves_meaningful_production_parity(monkeypatch, failure):
    from tb_runner import collection_flow, redirect_evidence

    off = _production_shaped_shadow_fixture()
    off.client._phase6d3a_redirect_controller = ExplorationRedirectController(
        mode="OFF", graph_mode="SHADOW")
    off_result, _off_expected, off_calls, _off_audit = _run_shadow(off)
    assert len(off_calls) == 1

    shadow = _production_shaped_shadow_fixture()
    shadow_calls = []
    if failure == "preparation":
        monkeypatch.setattr(collection_flow, "deepcopy",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("snapshot")))
    elif failure == "currentness":
        monkeypatch.setattr(collection_flow, "_phase6d3a_capture_shadow_currentness_token",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("currentness")))
    elif failure == "provider":
        monkeypatch.setattr(redirect_evidence.ProductionRedirectProofProvider,
                            "build_target_proof_set",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider")))
    elif failure == "evaluator":
        monkeypatch.setattr(redirect_evidence, "evaluate_redirect_readiness",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("evaluator")))
    elif failure == "trace":
        monkeypatch.setattr(shadow.controller, "record",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("trace")))

    expected = _production_collector_result()
    def collect(**kwargs):
        shadow_calls.append(kwargs)
        return dict(expected)
    shadow_result = collection_flow._phase6d3a_intercept_focus_step(
        original_collect=collect, collect_kwargs={"move": True, "direction": "next"},
        client=shadow.client, dev="offline", state=shadow.state,
        phase_ctx=shadow.phase_ctx, step_idx=8,
        tab_cfg={"scenario_id": shadow.scenario_id, "scenario_type": "content",
                 "screen_context_mode": "new_screen"})
    audit = shadow.client._phase6d3a_last_step_audit
    assert shadow_result == off_result == expected
    assert len(shadow_calls) == 1
    if failure == "none":
        assert audit["status"] == "READY"
        assert audit["readiness_status"] == "READY"
        assert audit["ready"] is True
    else:
        assert audit["status"] == "DIAGNOSTIC_ERROR"
        assert audit["readiness_status"] == "UNKNOWN"
        assert audit["ready"] is False
    assert audit["dispatch_count"] == 0
    assert audit["visit_credit"] == 0
    assert audit["evaluation_duration_ms"] >= 0


def test_shadow_latency_includes_provider_and_evaluator_and_updates_percentiles(monkeypatch):
    import time
    from tb_runner import redirect_evidence

    fixture = _production_shaped_shadow_fixture()
    provider_original = redirect_evidence.ProductionRedirectProofProvider.build_target_proof_set
    evaluator_original = redirect_evidence.evaluate_redirect_readiness

    def delayed_provider(self, *args, **kwargs):
        time.sleep(0.09)
        return provider_original(self, *args, **kwargs)

    def delayed_evaluator(*args, **kwargs):
        time.sleep(0.035)
        return evaluator_original(*args, **kwargs)

    monkeypatch.setattr(redirect_evidence.ProductionRedirectProofProvider,
                        "build_target_proof_set", delayed_provider)
    monkeypatch.setattr(redirect_evidence, "evaluate_redirect_readiness", delayed_evaluator)
    _result, _expected, calls, audit = _run_shadow(fixture)
    assert len(calls) == 1 and audit["readiness_status"] == "READY"
    assert audit["evaluation_duration_ms"] >= 110
    assert audit["readiness_trace"]["evaluation_duration_ms"] == audit["evaluation_duration_ms"]
    latency = fixture.controller.metrics.latency_summary()
    assert latency["count"] == 1
    assert latency["p50_ms"] == audit["evaluation_duration_ms"]
    assert latency["p95_ms"] == audit["evaluation_duration_ms"]


def test_shadow_latency_excludes_production_collector_delay():
    fixture = _production_shaped_shadow_fixture()
    started = __import__("time").perf_counter()
    _result, _expected, calls, audit = _run_shadow(fixture, collector_delay_seconds=0.16)
    wall_ms = (__import__("time").perf_counter() - started) * 1000.0
    assert len(calls) == 1
    assert wall_ms >= 150
    assert audit["evaluation_duration_ms"] < wall_ms - 100


def test_off_mode_is_transparent_and_no_shadow_bundle_is_built(monkeypatch):
    from tb_runner import collection_flow

    fixture = _production_shaped_shadow_fixture()
    fixture.client._phase6d3a_redirect_controller = ExplorationRedirectController(
        mode="OFF", graph_mode="SHADOW")
    monkeypatch.setattr(collection_flow, "_phase6d3a_shadow_readiness",
                        lambda **_kwargs: pytest.fail("OFF mode built readiness"))
    calls = []
    result = collection_flow._phase6d3a_intercept_focus_step(
        original_collect=lambda **kwargs: calls.append(kwargs) or {"same": True},
        collect_kwargs={"move": True, "direction": "next"},
        client=fixture.client, dev="offline", state=fixture.state,
        phase_ctx=fixture.phase_ctx, step_idx=8,
        tab_cfg={"scenario_id": fixture.scenario_id, "scenario_type": "content"})
    assert result == {"same": True}
    assert len(calls) == 1


def _assert_production_parity_and_no_redirect(fixture, result):
    from tb_runner import collection_flow
    row, expected, calls, audit = result
    off_calls = []
    off = SimpleNamespace(_phase6d3a_redirect_controller=ExplorationRedirectController(mode="OFF"))
    off_result = collection_flow._phase6d3a_intercept_focus_step(
        original_collect=lambda **kwargs: off_calls.append(kwargs) or _production_collector_result(),
        collect_kwargs={"move": True, "direction": "next"}, client=off, dev="offline",
        state=None, phase_ctx=None, step_idx=8, tab_cfg={})
    assert len(off_calls) == 1
    assert row == expected == off_result
    assert len(calls) == 1
    assert audit["dispatch_count"] == 0 and audit["visit_credit"] == 0
    assert fixture.client._phase6d3a_controlled_budget.actions == 0
    assert fixture.controller.budget.redirects_used == 0
    assert fixture.controller.budget.consecutive_failures == 0
    assert fixture.controller.budget.active_disabled is False
    assert fixture.controller.metrics.counters["SHADOW_FALSE_READY_COUNT"] == 0
    return audit


@pytest.mark.parametrize("failure", ["runtime", "clock", "clock_busy", "lifecycle", "inventory", "state", "config", "mode"])
def test_actual_precollector_read_failures_are_isolated_and_preserve_production(failure):
    fixture = _production_shaped_shadow_fixture()
    from tb_runner import collection_flow

    class ReadFailure:
        def __init__(self, target, field):
            self.target, self.field = target, field
        def __getattr__(self, name):
            if name == self.field:
                raise RuntimeError("precollector read: " + name)
            return getattr(self.target, name)

    config = None
    if failure == "runtime":
        fixture.client._phase6d_exploration_shadow_runtime = ReadFailure(
            fixture.client._phase6d_exploration_shadow_runtime, "decisions")
    elif failure in {"clock", "clock_busy"}:
        class BrokenLock:
            def acquire(self, *, blocking):
                assert blocking is False
                if failure == "clock_busy":
                    return False
                raise RuntimeError("clock token lock read")
            def release(self):
                pytest.fail("failed lock acquisition must not release")
        fixture.clock._lock = BrokenLock()
    elif failure == "lifecycle":
        fixture.client._window_lifecycle_recorder = ReadFailure(fixture.lifecycle, "saw_enabled_process_gap")
    elif failure == "inventory":
        fixture.client._phase6c2_frontier_shadow_runtime = ReadFailure(
            fixture.frontier_runtime, "_latest_inventory")
    elif failure == "state":
        fixture.state = ReadFailure(fixture.state, "previous_step_row")
    elif failure == "config":
        class BrokenConfig(dict):
            def get(self, *args, **kwargs):
                raise RuntimeError("diagnostic config read")
        config = BrokenConfig()
    else:
        fixture.client._phase6d3a_redirect_controller = ReadFailure(fixture.controller, "effective_mode")
    audit = _assert_production_parity_and_no_redirect(
        fixture, _run_shadow(fixture, tab_cfg_override=config))
    assert audit["readiness_status"] == "UNKNOWN" and audit["ready"] is False


def test_decision_token_is_deeply_immutable_and_does_not_keep_runtime_references():
    from dataclasses import FrozenInstanceError
    from tb_runner import collection_flow

    f = _production_shaped_shadow_fixture()
    token = collection_flow._phase6d3a_capture_shadow_decision_token(
        client=f.client, state=f.state, phase_ctx=f.phase_ctx, tab_cfg=f.tab_cfg)
    assert token.status == "CAPTURED"
    with pytest.raises(FrozenInstanceError):
        token.status = "READY"
    with pytest.raises(TypeError):
        collection_flow.DecisionEvidenceToken(signature=(("mutable", {}),))
    original = token.signature
    f.record["observation_alignment"]["scope_id"] = "mutated"
    f.lifecycle.saw_enabled_process_gap = True
    assert token.signature == original
    assert token.lifecycle_token[5] is False


@pytest.mark.parametrize("mutation,reason", [
    ("scope", "DECISION_SCOPE_MISMATCH"),
    ("observation", "DECISION_OBSERVATION_MISMATCH"),
    ("epoch", "DECISION_OBSERVATION_MISMATCH"),
    ("decision", "DECISION_DECISION_ID_MISMATCH"),
    ("watermark", "DECISION_DECISION_WATERMARK_MISMATCH"),
    ("state", "DECISION_STATE_MISMATCH"),
    ("frontier", "DECISION_FRONTIER_MISMATCH"),
    ("plugin", "DECISION_ROW_CONTEXT_MISMATCH"),
    ("inventory", "DECISION_INVENTORY_REFERENCE_MISMATCH"),
])
def test_mutable_evidence_rebinding_cannot_ready_and_preserves_production(mutation, reason):
    f = _production_shaped_shadow_fixture()
    def mutate():
        captures = [f.record["observation_alignment"], f.row["_exploration_observation"],
                    f.frontier_runtime._latest_inventory["observation_ref"]["capture"]]
        if mutation in {"scope", "observation", "epoch"}:
            for obs in captures:
                if mutation == "scope":
                    obs["scope_id"] = "foreign-after-collector"
                elif mutation == "observation":
                    obs["observation_sequence"] += 1
                else:
                    obs["action_epoch"] += 1
                    obs["observation_epoch"] += 1
                    obs["capture_end_action_epoch"] += 1
                obs["observation_id"] = f"observation:{obs['scope_id']}:{obs['observation_sequence']}"
        elif mutation == "decision":
            f.record["decision_id"] += ":foreign"
        elif mutation == "watermark":
            f.record["decision_watermark"] += 1
        elif mutation == "state":
            f.record["state"]["state_id"] = "foreign-state"
        elif mutation == "frontier":
            f.record["selected_frontier"]["frontier_id"] += ":foreign"
        elif mutation == "plugin":
            f.row["phase3_plugin_context_evidence"]["navigation_epoch"] += ":foreign"
        else:
            f.frontier_runtime._latest_inventory = deepcopy(f.frontier_runtime._latest_inventory)
    audit = _assert_production_parity_and_no_redirect(f, _run_shadow(f, collector_hook=mutate))
    assert audit["ready"] is False
    assert audit["decision_alignment"]["status"] == "UNKNOWN"
    assert reason in audit["reason_codes"]
    trace = audit["readiness_trace"]["decision_alignment"]
    assert trace["decision_token_id"] and trace["pre_scope"] == "scope-1"
    if mutation == "scope":
        assert trace["post_scope"] == "foreign-after-collector"


@pytest.mark.parametrize("transition,expected", [
    ("gap_cleared", "BLOCKED"), ("worsened", "BLOCKED"),
    ("unknown_resolved", "UNKNOWN"), ("stable", "CLEAR"),
])
def test_actual_recorder_temporal_lifecycle_merge_preserves_decision_evidence(transition, expected):
    f = _production_shaped_shadow_fixture()
    def gap():
        f.lifecycle._track_talkback_process({"talkback_pid": None, "talkback_enabled": True})
    if transition == "gap_cleared":
        gap()
    elif transition == "unknown_resolved":
        f.client._window_lifecycle_recorder = None
    def collect_transition():
        if transition == "gap_cleared":
            f.lifecycle._track_talkback_process({"talkback_pid": "12345", "talkback_enabled": True})
            assert f.lifecycle.saw_enabled_process_gap is False
        elif transition == "worsened":
            gap()
        elif transition == "unknown_resolved":
            f.client._window_lifecycle_recorder = f.lifecycle
    audit = _assert_production_parity_and_no_redirect(f, _run_shadow(f, collector_hook=collect_transition))
    temporal = audit["conditions"]["lifecycle_evidence"]
    assert audit["conditions"]["lifecycle_status"] == expected
    assert temporal["lifecycle_effective_for_readiness"] == expected
    if transition == "gap_cleared":
        assert temporal["lifecycle_pre_decision"]["enabled_process_gap"] is True
        assert temporal["lifecycle_pre_decision"]["status"] == "BLOCKED"
        assert temporal["lifecycle_post_collector"]["enabled_process_gap"] is False
        assert temporal["lifecycle_post_collector"]["status"] == "CLEAR"
    assert audit["ready"] is (transition == "stable")


def test_production_clock_advance_does_not_rebind_the_original_decision_observation():
    f = _production_shaped_shadow_fixture()
    observation_id = f.record["observation_alignment"]["observation_id"]
    def production_advance():
        f.clock.dispatch(["shell", "am", "broadcast", "-a",
                          "com.iotpart.sqe.talkbackhelper.SMART_NEXT", "--es", "reqId", "production-next"])
        f.clock.finish_observation(f.clock.begin_observation())
    audit = _assert_production_parity_and_no_redirect(f, _run_shadow(f, collector_hook=production_advance))
    assert audit["readiness_status"] == "READY"
    assert audit["observation_id"] == observation_id
    assert audit["decision_alignment"]["status"] == "MATCH"


@pytest.mark.parametrize("failure", ["bundle", "adapter_import"])
def test_postcollector_bundle_and_adapter_failure_preserve_production(monkeypatch, failure):
    from tb_runner import redirect_evidence
    f = _production_shaped_shadow_fixture()
    if failure == "bundle":
        monkeypatch.setattr(redirect_evidence, "RedirectEvidenceBundle",
                            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("bundle")))
    else:
        import builtins
        original = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name == "tb_runner.phase4b_execution":
                raise ImportError("diagnostic adapter")
            return original(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", guarded_import)
    audit = _assert_production_parity_and_no_redirect(f, _run_shadow(f))
    assert audit["readiness_status"] == "UNKNOWN"


def test_provider_exception_trace_retains_predecision_gap_after_collector_recovery(monkeypatch):
    from tb_runner import redirect_evidence
    f = _production_shaped_shadow_fixture()
    f.lifecycle._track_talkback_process({"talkback_pid": None, "talkback_enabled": True})
    monkeypatch.setattr(redirect_evidence.ProductionRedirectProofProvider, "build_target_proof_set",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider")))
    def recover():
        f.lifecycle._track_talkback_process({"talkback_pid": "12345", "talkback_enabled": True})
    audit = _assert_production_parity_and_no_redirect(f, _run_shadow(f, collector_hook=recover))
    assert audit["readiness_status"] == "UNKNOWN"
    evidence = audit["readiness_trace"]["lifecycle_evidence"]
    assert evidence["lifecycle_pre_decision"]["enabled_process_gap"] is True
    assert evidence["lifecycle_post_collector"]["enabled_process_gap"] is False
    assert evidence["lifecycle_effective_for_readiness"] == "BLOCKED"


@pytest.mark.parametrize("case,pre_status,post_status,effective", [
    ("request_repaired", "MISMATCH", "READY", "MISMATCH"),
    ("ack_repaired", "UNAVAILABLE", "READY", "UNAVAILABLE"),
    ("request_worsened", "READY", "MISMATCH", "MISMATCH"),
    ("ack_worsened", "READY", "UNAVAILABLE", "UNAVAILABLE"),
    ("missing_repaired", "UNKNOWN", "READY", "UNKNOWN"),
    ("valid_rebound", "READY", "READY", "UNKNOWN"),
])
def test_rf2r3_helper_raw_temporal_provenance(case, pre_status, post_status, effective):
    f = _production_shaped_shadow_fixture()
    if case == "request_repaired":
        f.row.update(phase5c_primary_action_request_id="primary-A", smart_nav_req_id="navigation-B")
    elif case == "ack_repaired":
        f.row["command_ack_result"] = "ACK_TIMEOUT"
    elif case == "missing_repaired":
        for key in ("phase5c_primary_action_request_id", "smart_nav_req_id", "command_ack_status"):
            f.row.pop(key)

    def change():
        if case in {"request_repaired", "missing_repaired", "valid_rebound"}:
            f.row.update(phase5c_primary_action_request_id="foreign-C", smart_nav_req_id="foreign-C",
                         command_ack_status="SUCCESS")
        elif case == "request_worsened":
            f.row["smart_nav_req_id"] = "foreign-C"
        else:
            f.row["command_ack_result"] = "MOVED" if case == "ack_repaired" else "ACK_TIMEOUT"

    outcome = _run_shadow(f, collector_hook=change)
    result, expected, calls, audit = outcome
    assert result == expected and len(calls) == 1
    assert audit["readiness_status"] != "READY"
    evidence = audit["conditions"]["helper_evidence"]
    assert (evidence["pre_status"], evidence["post_status"], evidence["effective_status"]) == (
        pre_status, post_status, effective)
    assert evidence["alignment"] == "MISMATCH"
    assert "DECISION_HELPER_SOURCE_MISMATCH" in audit["reason_codes"]
    assert evidence["pre_decision"] != evidence["post_collector"]
    _assert_production_parity_and_no_redirect(f, outcome)


def test_rf2r3_helper_stable_positive_trace():
    f = _production_shaped_shadow_fixture()
    result, expected, calls, audit = _run_shadow(f)
    assert result == expected and len(calls) == 1
    assert audit["readiness_status"] == "READY"
    evidence = audit["conditions"]["helper_evidence"]
    assert evidence["pre_decision"] == evidence["post_collector"]
    assert evidence["pre_status"] == evidence["post_status"] == evidence["effective_status"] == "READY"
    assert evidence["reason"] == "SAME_DECISION_STABLE"


def test_rf2r3_actual_helper_raw_capture_failure_preserves_collector():
    f = _production_shaped_shadow_fixture()
    class BrokenHelperRow(dict):
        def get(self, key, *args):
            if key == "command_ack_status":
                raise RuntimeError("actual raw ACK read failed")
            return super().get(key, *args)
    f.state.previous_step_row = BrokenHelperRow(f.row)
    outcome = _run_shadow(f)
    result, expected, calls, audit = outcome
    assert result == expected and len(calls) == 1
    assert audit["readiness_status"] == "UNKNOWN"
    assert audit["pre_diagnostic_capture_status"] == "UNKNOWN"
    _assert_production_parity_and_no_redirect(f, outcome)


@pytest.mark.parametrize("source", [
    "tree_semantics", "tree_competitor", "focus", "overlay", "context", "capability",
    "planner_visits", "planner_attempts", "planner_history_row", "planner_tracker",
    "registry_policy", "registry_state", "summary", "provider_budget", "frontier_eligibility",
    "recovery_clear", "transition_clear", "overlay_clear",
])
def test_rf2r3_readiness_source_seals_reject_in_place_changes(source):
    f = _production_shaped_shadow_fixture(overlay=source == "overlay_clear")
    if source == "recovery_clear":
        f.state.food_scan_recovery_pending = True
    if source == "transition_clear":
        f.state.post_realign_pending_steps = 1
    if source == "planner_attempts":
        f.client._target_attempt_ledger = SimpleNamespace(entries={})
    if source == "planner_tracker":
        f.state.content_terminal = SimpleNamespace(no_progress_steps=0)

    def change():
        if source == "tree_semantics":
            f.row["dump_tree_nodes"][0]["text"] = "changed semantic source"
        elif source == "tree_competitor":
            f.row["dump_tree_nodes"].append(deepcopy(f.row["dump_tree_nodes"][0]))
        elif source == "focus":
            f.row["actual_focus_node"]["accessibilityFocused"] = False
        elif source in {"overlay", "overlay_clear"}:
            f.row["overlay"]["observed"] = source == "overlay"
        elif source == "context":
            f.row["context_source"] = "foreign_context"
        elif source == "capability":
            f.row["capability"] = {"contradictory": True}
        elif source == "planner_visits":
            f.state.reliability_metrics.visited.add("new-production-visit")
        elif source == "planner_attempts":
            f.client._target_attempt_ledger.entries["new"] = {"scenario_id": f.scenario_id,
                "target": {"resource_id": "changed", "bounds": "0,0,10,10"}, "step": 8}
        elif source == "planner_history_row":
            f.phase_ctx.all_rows[0]["visit_record_status"] = "RECORDED"
        elif source == "planner_tracker":
            f.state.content_terminal.no_progress_steps = 5
        elif source.startswith("registry_"):
            registry = f.client._phase6d3a_redirect_context["registry"]
            if source == "registry_policy":
                registry.matching_policy = "changed-policy"
            else:
                next(iter(registry._states.values()))["representative_observation_ids"] = []
        elif source == "summary":
            f.client.last_start_open_summary["open_completed"] = False
        elif source == "provider_budget":
            f.client._phase6d3a_controlled_budget.max_actions = 0
        elif source == "frontier_eligibility":
            f.record["production"]["final_terminal"] = True
        elif source == "recovery_clear":
            f.state.food_scan_recovery_pending = False
        elif source == "transition_clear":
            f.state.post_realign_pending_steps = 0

    result, expected, calls, audit = _run_shadow(f, collector_hook=change)
    assert result == expected and len(calls) == 1
    assert audit["readiness_status"] != "READY"
    assert audit["decision_alignment"]["status"] == "UNKNOWN"
    assert any(r.startswith("DECISION_") and r.endswith("MISMATCH") for r in audit["reason_codes"])
    assert audit["dispatch_count"] == 0 and audit["visit_credit"] == 0


def test_rf2r3_explicit_authority_coverage_and_immutable_seals():
    from tb_runner import collection_flow as flow
    expected = {"helper_request", "helper_ack", "planner", "phase4_gate", "phase5_safety",
                "binding", "presence", "frontier", "inventory", "state_context", "observation",
                "clock", "lifecycle", "overlay", "recovery", "transition"}
    assert set(flow._PHASE6D3A_PROVENANCE_AUTHORITIES) == expected
    f = _production_shaped_shadow_fixture()
    token = flow._phase6d3a_capture_shadow_decision_token(
        client=f.client, state=f.state, phase_ctx=f.phase_ctx, tab_cfg=f.tab_cfg)
    assert token.status == "CAPTURED"
    groups = dict(token.signature)
    assert {"helper_source", "raw_provider_sources", "planner_history", "registry_generation",
            "provider_context", "provider_budget", "decision_eligibility", "frontier",
            "inventory_provenance", "runtime_safety", "pending_transition"} <= groups.keys()
    before = token.signature
    f.row["dump_tree_nodes"][0]["text"] = "mutated after capture"
    assert token.signature == before
    with pytest.raises((ValueError, TypeError)):
        flow._phase6d3a_source_seal(object())
    with pytest.raises((ValueError, TypeError)):
        flow._phase6d3a_source_seal([0]*2049)


@pytest.mark.parametrize("case", ["changed", "unavailable", "loaded_during_collector"])
def test_rf2r3_safety_policy_cache_provenance(case, monkeypatch):
    from tb_runner import action_safety
    f = _production_shaped_shadow_fixture()
    policy = action_safety._loaded_default_config
    if case != "changed":
        monkeypatch.setattr(action_safety, "_loaded_default_config", None)

    def change():
        if case == "changed":
            monkeypatch.setitem(policy, "rf2r3_test_mutation", True)
        elif case == "loaded_during_collector":
            action_safety._loaded_default_config = policy

    outcome = _run_shadow(f, collector_hook=change)
    audit = _assert_production_parity_and_no_redirect(f, outcome)
    assert audit["readiness_status"] != "READY"
    assert any("SAFETY_POLICY" in r for r in audit["reason_codes"])


def test_rf2r3_bounded_source_capture_failure_preserves_production():
    f = _production_shaped_shadow_fixture()
    f.row["dump_tree_nodes"] = [{"text": "a"}]*2049
    result = _run_shadow(f)
    audit = _assert_production_parity_and_no_redirect(f, result)
    assert audit["readiness_status"] == "UNKNOWN"
    assert audit["pre_diagnostic_capture_status"] == "UNKNOWN"


@pytest.mark.parametrize("missing", ["requests", "ack_status", "ack_result"])
def test_rf2r3_missing_helper_source_is_unknown(missing):
    f = _production_shaped_shadow_fixture()
    fields = {"requests": ("phase5c_primary_action_request_id", "smart_nav_req_id"),
              "ack_status": ("command_ack_status",),
              "ack_result": ("command_ack_result", "command_ack_raw_result")}[missing]
    for field in fields:
        f.row.pop(field, None)
    outcome = _run_shadow(f)
    audit = _assert_production_parity_and_no_redirect(f, outcome)
    assert audit["readiness_status"] == "UNKNOWN"
    assert audit["conditions"]["helper_evidence"]["effective_status"] == "UNKNOWN"


def test_rf2r3_helper_trace_frame_is_immutable():
    from tb_runner.redirect_evidence import ProductionEvidenceFrame, _evidence_document
    source = {"pre_decision": {"command_ack_result": "ACK_TIMEOUT"}}
    frame = ProductionEvidenceFrame(helper_evidence=source)
    source["pre_decision"]["command_ack_result"] = "MOVED"
    assert _evidence_document(frame.helper_evidence)["pre_decision"]["command_ack_result"] == "ACK_TIMEOUT"


@pytest.mark.parametrize("source", ["focus_boolean", "decision_boolean"])
def test_rf2r3_boolean_integer_alias_cannot_rebind_evidence(source):
    f = _production_shaped_shadow_fixture()
    if source == "focus_boolean":
        f.row["actual_focus_node"]["accessibilityFocused"] = 1
    else:
        f.record["decision_evidence_usable"] = 1

    def change():
        if source == "focus_boolean":
            f.row["actual_focus_node"]["accessibilityFocused"] = True
        else:
            f.record["decision_evidence_usable"] = True

    outcome = _run_shadow(f, collector_hook=change)
    audit = _assert_production_parity_and_no_redirect(f, outcome)
    assert audit["readiness_status"] != "READY"
    assert audit["decision_alignment"]["status"] == "UNKNOWN"



def test_rf2r3_policy_cache_clear_cannot_silently_reload_proof_source():
    from tb_runner import action_safety
    f = _production_shaped_shadow_fixture()
    try:
        outcome = _run_shadow(f, collector_hook=action_safety.default_config.cache_clear)
        audit = _assert_production_parity_and_no_redirect(f, outcome)
        assert audit["readiness_status"] != "READY"
        assert "DECISION_SAFETY_POLICY_PROVENANCE_UNAVAILABLE" in audit["reason_codes"]
    finally:
        action_safety.default_config()


@pytest.mark.parametrize("source", ["fallback_step", "timestamp"])
def test_rf2r3_observation_fallback_fields_are_decision_bound(source):
    f = _production_shaped_shadow_fixture()
    if source == "fallback_step":
        f.row.pop("step_index")
        f.row["step"] = 6
    def change():
        if source == "fallback_step":
            f.row["step"] = 7
        else:
            f.row["timestamp"] = "2026-10-22T01:03:04+09:00"
    outcome = _run_shadow(f, collector_hook=change)
    audit = _assert_production_parity_and_no_redirect(f, outcome)
    assert audit["readiness_status"] != "READY"
    assert "DECISION_ROW_CONTEXT_MISMATCH" in audit["reason_codes"]


@pytest.mark.parametrize("source", ["step_default", "coverage_default", "history_scenario_default"])
def test_rf2r3_missing_key_and_explicit_none_are_not_equivalent(source):
    f = _production_shaped_shadow_fixture()
    if source == "step_default":
        f.row["step"] = 7
        f.row["step_index"] = None
        target, key = f.row, "step_index"
    elif source == "coverage_default":
        target, key = f.row, "observation_coverage"
        target[key] = None
    else:
        target = {"scenario_id": None, "visit_record_status": "RECORDED",
                  "focus_transition_status": "CONFIRMED_MOVED", "reconciled_visit_instance_id": "visit"}
        f.phase_ctx.all_rows.append(target)
        key = "scenario_id"
    outcome = _run_shadow(f, collector_hook=lambda: target.pop(key))
    audit = _assert_production_parity_and_no_redirect(f, outcome)
    assert audit["readiness_status"] != "READY"
    assert audit["decision_alignment"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("left,right", [
    ({"a": 1}, [("a", 1)]),
    ({"a": 1}, (("a", 1),)),
    ({"a": {"b": 1}}, {"a": [("b", 1)]}),
    ({"a": [1, 2]}, {"a": (1, 2)}),
    ([], ()), ({}, []),
    (True, 1), (False, 0), (None, "None"),
])
def test_rf2r4_metadata_source_type_categories_do_not_collide(left, right):
    from tb_runner.collection_flow import _phase6d3a_freeze_decision_metadata as freeze
    assert freeze(left) != freeze(right)


def test_rf2r4_valid_mapping_and_sequence_semantics_are_stable():
    from collections import OrderedDict
    from tb_runner.collection_flow import _phase6d3a_freeze_decision_metadata as freeze
    assert freeze({"a": 1, "b": [2, {"c": True}]}) == freeze(
        OrderedDict((("b", [2, {"c": True}]), ("a", 1))))
    for value in ([1, "x", {"a": None}], (1, "x", {"a": None})):
        assert freeze(value) == freeze(deepcopy(value))
    assert freeze([1, 2]) != freeze([2, 1])
    assert freeze((1, 2)) != freeze((2, 1))


@pytest.mark.parametrize("invalid", [object(), {"a": {1, 2}}, {1: "non-string key"}, 1.5])
def test_rf2r4_unsupported_metadata_is_not_coerced(invalid):
    from tb_runner.collection_flow import _phase6d3a_freeze_decision_metadata as freeze
    with pytest.raises((TypeError, ValueError)):
        freeze(invalid)


@pytest.mark.parametrize("source", ["state", "observation", "inventory", "entry", "frontier", "combined"])
@pytest.mark.parametrize("repair_during_collector", [False, True])
def test_rf2r4_sol_raw_metadata_type_reproductions_fail_closed(source, repair_during_collector):
    from tb_runner.collection_flow import _phase6d3a_freeze_decision_metadata as freeze
    f = _production_shaped_shadow_fixture()
    sources = {"state": (f.record, "state"), "observation": (f.row, "_exploration_observation"),
        "inventory": (f.frontier_runtime._latest_inventory, "observation_ref"),
        "entry": (f.row, "phase3_entry_evidence"),
        "frontier": (f.record["selected_frontier"], "target_identity")}
    selected = list(sources.values()) if source == "combined" else [sources[source]]
    saved = [(obj, key, obj[key]) for obj, key in selected]
    for obj, key, good in saved:
        bad = list(sorted(good.items()))
        assert freeze(bad) != freeze(good)
        obj[key] = bad

    def repair():
        for obj, key, good in saved:
            obj[key] = good

    outcome = _run_shadow(f, collector_hook=repair if repair_during_collector else None)
    audit = _assert_production_parity_and_no_redirect(f, outcome)
    assert audit["readiness_status"] != "READY"
    if repair_during_collector:
        assert audit["decision_alignment"]["status"] != "MATCH"


def test_rf2r4_normalization_failure_does_not_block_production_collector():
    f = _production_shaped_shadow_fixture()
    f.record["state"] = {"unsupported": object()}
    outcome = _run_shadow(f)
    audit = _assert_production_parity_and_no_redirect(f, outcome)
    assert audit["readiness_status"] == "UNKNOWN"
    assert audit["pre_diagnostic_capture_status"] == "UNKNOWN"


def test_rf2r4_mapping_reader_rejects_pair_sequence_without_coercion():
    from tb_runner.collection_flow import _phase6d3a_freeze_decision_metadata as freeze
    from tb_runner.collection_flow import _phase6d3a_read_metadata_mapping as read
    source = {"a": [1, (True, None)], "b": {"c": "value"}}
    assert read(freeze(source)) == source
    assert type(read(freeze(source))["a"]) is list
    assert type(read(freeze(source))["a"][1]) is tuple
    with pytest.raises(TypeError, match="MAPPING_REQUIRED"):
        read(freeze([("a", 1)]))
