import json
import sys
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools import phase4b_controlled_smoke as smoke
from tools import phase4b_controlled_monitor as supervisor
from state_model_fixtures import node, observation
from tb_runner import collection_flow


@pytest.mark.parametrize("failure", [False, True])
def test_process_local_hooks_and_argv_restored(tmp_path, monkeypatch, failure):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"scenarios": {"home_main": {"max_steps": 5}}}))
    for key, value in {"TB_PHASE4B_CONTROLLED": "1", "TB_PHASE4B_SMOKE_SCENARIO": "home_main",
                       "TB_PHASE4B_SMOKE_OUT": str(tmp_path), "TB_RUNTIME_CONFIG_PATH": str(config)}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(smoke, "A11yAdbClient", lambda **kw: object())
    hooks = ("_main_loop_phase", "_apply_step_collection_phase", "_apply_row_persistence_phase", "_apply_focus_reconciliation")
    original = {k: getattr(smoke.collection_flow, k) for k in hooks}
    argv = sys.argv
    def run(*args, **kwargs):
        assert all(getattr(smoke.collection_flow, k) is not v for k, v in original.items())
        assert sys.argv[-1] == "home_main"
        if failure:
            raise RuntimeError("runner failed")
        raise SystemExit(0)
    monkeypatch.setattr(smoke.runpy, "run_path", run)
    if failure:
        with pytest.raises(RuntimeError, match="runner failed"):
            smoke.main()
    else:
        assert smoke.main() == 0
    assert sys.argv is argv
    assert all(getattr(smoke.collection_flow, k) is v for k, v in original.items())


def test_default_off_before_device_or_runner(monkeypatch):
    monkeypatch.delenv("TB_PHASE4B_CONTROLLED", raising=False)
    monkeypatch.setattr(smoke, "A11yAdbClient", lambda **kw: pytest.fail("Default OFF must not create a client"))
    with pytest.raises(ValueError, match="opt-in"):
        smoke.main()


def test_reject_unbounded_steps(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"scenarios": {"home_main": {"max_steps": 100}}}))
    monkeypatch.setenv("TB_PHASE4B_CONTROLLED", "1")
    monkeypatch.setenv("TB_PHASE4B_SMOKE_SCENARIO", "home_main")
    monkeypatch.setenv("TB_PHASE4B_SMOKE_OUT", str(tmp_path))
    monkeypatch.setenv("TB_RUNTIME_CONFIG_PATH", str(config))
    with pytest.raises(ValueError, match="five TOTAL"):
        smoke.main()


def test_staged_supervisor_uses_exact_order_and_restores_monitor(tmp_path, monkeypatch):
    summary = tmp_path / "replay.json"
    summary.write_text(json.dumps(dict(status="PASS", historical_exact=16, accepted_scenarios=6)))
    monkeypatch.setenv("TB_PHASE4B_CONTROLLED", "1")
    monkeypatch.setenv("TB_PHASE4B_SMOKE_OUT", str(tmp_path))
    monkeypatch.setenv("TB_PHASE4B_REPLAY_SUMMARY", str(summary))
    original = supervisor.monitor.OUT, supervisor.monitor.SCENARIOS, supervisor.monitor.SERIAL
    def run(**kwargs):
        assert supervisor.monitor.SCENARIOS == ("home_main", "devices_main", "life_find_plugin",
            "device_smoke_sensor_plugin", "life_food_plugin", "life_family_care_plugin")
        assert kwargs["scenario_validator"] is supervisor.validate_scenario
        assert kwargs["runner_module"] == "tools.phase4b_controlled_smoke"
        return 0
    monkeypatch.setattr(supervisor.monitor, "main", run)
    assert supervisor.main() == 0
    assert original == (supervisor.monitor.OUT, supervisor.monitor.SCENARIOS, supervisor.monitor.SERIAL)


def test_missing_replay_prevents_live_and_existing_run_cannot_retry(tmp_path, monkeypatch):
    summary = tmp_path / "replay.json"
    summary.write_text(json.dumps(dict(status="FAIL", historical_exact=16, accepted_scenarios=6)))
    monkeypatch.setenv("TB_PHASE4B_CONTROLLED", "1")
    monkeypatch.setenv("TB_PHASE4B_SMOKE_OUT", str(tmp_path))
    monkeypatch.setenv("TB_PHASE4B_REPLAY_SUMMARY", str(summary))
    with pytest.raises(ValueError, match="before live"):
        supervisor.main()
    summary.write_text(json.dumps(dict(status="PASS", historical_exact=16, accepted_scenarios=6)))
    (tmp_path / "monitor_result.json").write_text("{}")
    with pytest.raises(ValueError, match="no automatic scenario retry"):
        supervisor.main()


def test_phase4b_execution_dependencies_are_confined_to_explicit_redirect_adapter():
    import ast

    root = Path(__file__).resolve().parents[1]
    for name in ("script_test.py", "talkback_lib/__init__.py", "config/runtime_config.json"):
        assert "phase4b" not in (root / name).read_text(encoding="utf-8").lower()
    source = (root / "tb_runner/collection_flow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def enclosing_function(node):
        current = parents.get(node)
        while current is not None and not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            current = parents.get(current)
        return current.name if current is not None else ""

    def inside_redirect_adapter(node):
        current = node
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)) and current.name == "_phase6d3a_intercept_focus_step":
                return True
            current = parents.get(current)
        return False

    protected = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = " ".join(alias.name for alias in node.names).lower()
            if "phase4b" in names:
                protected.append(node)
        elif isinstance(node, ast.ImportFrom) and "phase4b" in (node.module or "").lower():
            protected.append(node)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "__import__" and node.args
              and isinstance(node.args[0], ast.Constant)
              and "phase4b" in str(node.args[0].value).lower()):
            protected.append(node)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                "controlled_collect", "execution_gate", "resolve_focus_target",
                "dispatch_provenance_current"}:
            protected.append(node)
        elif isinstance(node, ast.Name) and node.id == "ExecutionBudget":
            protected.append(node)
    assert protected
    offenders = [(type(node).__name__, getattr(node, "lineno", None), enclosing_function(node),
                  ast.dump(node, include_attributes=False))
                 for node in protected
                 if not inside_redirect_adapter(node)]
    assert not offenders, offenders

    adapter = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "_phase6d3a_intercept_focus_step")
    adapter_calls = [node for node in ast.walk(adapter) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name)]
    controlled_calls = [node for node in adapter_calls if node.func.id == "controlled_collect"]
    gate_calls = [node for node in adapter_calls if node.func.id == "execution_gate"]
    resolver_calls = [node for node in adapter_calls if node.func.id == "resolve_focus_target"]
    # RF4 isolates ACTIVE orchestration behind the existing mode branch.
    assert not controlled_calls and not gate_calls and not resolver_calls
    active_calls = [node for node in adapter_calls if node.func.id == "collect_active_redirect"]
    assert len(active_calls) == 1
    active_tree = ast.parse(Path("tb_runner/active_redirect.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(active_tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)]
    controlled = [n for n in calls if n.func.id == "controlled_collect"]
    assert len(controlled) == 1
    assert len([n for n in calls if n.func.id == "execution_gate"]) == 2
    assert len([n for n in calls if n.func.id == "resolve_focus_target"]) == 2
    keywords = {k.arg for k in controlled[0].keywords}
    assert "native_dispatch_observer" in keywords
    assert "dispatch_observer" not in keywords
    assert "defer_budget_reservation" not in keywords
    adapter_ifs = [node for node in ast.walk(adapter) if isinstance(node, ast.If)]

    def mode_comparison(node, operator, values):
        for part in ast.walk(node):
            if (isinstance(part, ast.Compare) and isinstance(part.left, ast.Name)
                    and part.left.id == "mode" and len(part.ops) == 1
                    and isinstance(part.ops[0], operator)):
                comparator = part.comparators[0]
                observed = ({item.value for item in comparator.elts if isinstance(item, ast.Constant)}
                            if isinstance(comparator, ast.Set) else
                            {comparator.value} if isinstance(comparator, ast.Constant) else set())
                if observed == set(values):
                    return True
        return False

    mode_guard = next(node for node in adapter_ifs if mode_comparison(node.test, ast.NotIn,
                                                                       {"SHADOW", "ACTIVE"}))
    shadow_branch = next(node for node in adapter_ifs if mode_comparison(node.test, ast.Eq, {"SHADOW"}))
    assert mode_guard.lineno < active_calls[0].lineno
    assert shadow_branch.lineno < active_calls[0].lineno
    assert "redirect_mode_from_environment" in source


def test_stage_cannot_pass_on_all_fallbacks_or_missing_entry(tmp_path):
    result = supervisor.validate_scenario("home_main", tmp_path)
    assert not result["pass"]
    assert "NO_REAL_CONTROLLED_ACTION" in result["reasons"]
    assert "NORMAL_PRODUCTION_ENTRY_NOT_PROVEN" in result["reasons"]


def test_stage_rejects_confirmed_before_focus_lost_by_adapter(tmp_path):
    scenario = "home_main"
    run = tmp_path / "run" / scenario
    run.mkdir(parents=True)
    (run / "capture.evidence.jsonl").write_text(json.dumps(dict(event_type="SCENARIO_TERMINAL", scenario_id=scenario,
        payload=dict(termination_status="INCOMPLETE_SAFETY_LIMIT", termination_reason="safety_limit", attempted_steps=5))) + "\n")
    (tmp_path / "phase4b_observations.jsonl").write_text(json.dumps(dict(scenario=scenario, kind="ENTRY_TO_TRAVERSAL")) + "\n")
    traces = [dict(scenario=scenario, step=i, planner_executed=True, planner_authorized=True, planner_failed=True,
        actual_execution_mode="CONTROLLED_TARGET_FOCUS", execution_gate_result=dict(allowed=True),
        phase4b_visit_credit=0, visit_credit=1, focus_transition_status="CONFIRMED_MOVED",
        fallback_used=True, attempt_credit=1, planner_action="FOCUS_CANDIDATE", scroll_result=None,
        state_id="same", gate_evidence=dict(focus_coherent=True), focus_preview=dict(actual_focus_before_id=""))
        for i in range(1, 6)]
    (tmp_path / "phase4b_execution_trace.jsonl").write_text("".join(json.dumps(r) + "\n" for r in traces))
    result = supervisor.validate_scenario(scenario, tmp_path)
    assert not result["pass"]
    assert "CONFIRMED_BEFORE_FOCUS_IDENTITY_LOST_BY_ADAPTER" in result["reasons"]


def test_existing_production_recovery_can_bypass_controlled_collector(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"scenarios": {"home_main": {"max_steps": 5}}}))
    for key, value in {"TB_PHASE4B_CONTROLLED": "1", "TB_PHASE4B_SMOKE_SCENARIO": "home_main",
                       "TB_PHASE4B_SMOKE_OUT": str(tmp_path), "TB_RUNTIME_CONFIG_PATH": str(config)}.items():
        monkeypatch.setenv(key, value)
    raw = observation(nodes=[node("id.a", "A"), node("id.b", "B", "0,220,500,320", accessibilityFocused=True)],
                      focus_node=node("id.b", "B", "0,220,500,320", accessibilityFocused=True))
    monkeypatch.setattr(smoke, "A11yAdbClient", lambda **kw: object())
    monkeypatch.setattr(smoke, "capture_observation", lambda *a, **kw: deepcopy(raw))
    monkeypatch.setattr(smoke, "phase3_entry_evidence_from_main_loop", lambda *a: {})
    original_collect = lambda **kw: pytest.fail("Production recovery does not use the controlled collector")
    client = SimpleNamespace(collect_focus_step=original_collect, check_helper_status=lambda **kw: True)
    state = SimpleNamespace(forced_local_tab_target_rid="real_production_local_tab")
    phase = SimpleNamespace(all_rows=[])
    kwargs = dict(step_idx=1, state=state, client=client, dev="synthetic-device", phase_ctx=phase,
                  tab_cfg={}, scenario_id="home_main")
    expected_row = dict(move_result="MOVED", actual_focus_node=raw["focus_node"],
                        visit_record_status="RECORDED", focus_transition_status="CONFIRMED_MOVED")
    def original_step(**received):
        assert received == kwargs
        return expected_row
    monkeypatch.setattr(smoke.collection_flow, "_apply_step_collection_phase", original_step)
    monkeypatch.setattr(smoke.collection_flow, "_apply_row_persistence_phase", lambda **kw: "saved")
    def original_loop(received_client, dev, received_phase):
        assert smoke.collection_flow._apply_step_collection_phase(**kwargs) is expected_row
        assert client.collect_focus_step is original_collect
        assert smoke.collection_flow._apply_row_persistence_phase(step_idx=1, row=expected_row) == "saved"
    monkeypatch.setattr(smoke.collection_flow, "_main_loop_phase", original_loop)
    def run(*a, **kw):
        smoke.collection_flow._main_loop_phase(client, "synthetic-device", phase)
        raise SystemExit(0)
    monkeypatch.setattr(smoke.runpy, "run_path", run)
    assert smoke.main() == 0
    audit = json.loads((tmp_path / "phase4b_execution_trace.jsonl").read_text(encoding="utf-8"))
    assert audit["classification"] == "PRODUCTION_ONLY" and audit["fallback_used"]
    assert audit["actual_execution_mode"] == "FALLBACK_PRODUCTION"
    assert not audit["planner_executed"] and not audit["planner_authorized"]


def test_controlled_collector_is_downstream_of_interceptor_without_changing_move_flags(monkeypatch):
    from tb_runner.exploration_redirect import ExplorationRedirectController

    base_calls = []
    base_collector = lambda **kwargs: base_calls.append(kwargs) or {"move_result": "OBSERVED"}
    client = SimpleNamespace(
        collect_focus_step=base_collector,
        _phase6d3a_redirect_controller=ExplorationRedirectController(mode="ACTIVE", graph_mode="SHADOW"),
    )
    monkeypatch.setattr(collection_flow, "_frontier_shadow_pre_decision", lambda **_kwargs: "pre")
    intercepted_calls = []

    def observe_interceptor(**kwargs):
        intercepted_calls.append(kwargs)
        return kwargs["original_collect"](**kwargs["collect_kwargs"])

    monkeypatch.setattr(collection_flow, "_phase6d3a_intercept_focus_step", observe_interceptor)
    controlled_calls = []

    def controlled_collector(**kwargs):
        controlled_calls.append(kwargs)
        assert kwargs["move"] is True
        # Match controlled_collect's post-action observation shape.
        return client.collect_focus_step(move=False, direction="next", step_index=1)

    def production_step():
        return smoke._invoke_step_with_controlled_collector(
            client=client, controlled_collector=controlled_collector,
            step_call=lambda: client.collect_focus_step(move=True, direction="next", step_index=1),
        )

    row, decision_id = collection_flow._run_main_step_with_frontier_shadow(
        client=client, state=SimpleNamespace(previous_step_row={}), step_idx=1,
        tab_cfg={"scenario_id": "life_sample_plugin", "scenario_type": "content"},
        collect_step_fn=production_step, phase_ctx=SimpleNamespace(), dev="offline",
    )

    assert decision_id == "pre"
    assert row == {"move_result": "OBSERVED"}
    assert len(controlled_calls) == 1 and controlled_calls[0]["move"] is True
    assert [call["collect_kwargs"]["move"] for call in intercepted_calls] == [True, False]
    assert intercepted_calls[0]["original_collect"] is controlled_collector
    assert intercepted_calls[1]["original_collect"] is base_collector
    assert [call["move"] for call in base_calls] == [False]
    assert client.collect_focus_step is base_collector
    assert not hasattr(client, "_phase6d3a_interceptor_installed")
    assert not hasattr(client, "_phase6d3a_controlled_collect_delegate")


def test_previous_wrapper_order_keeps_active_adapter_unreachable(monkeypatch):
    from tb_runner import active_redirect
    from test_phase6d3a_rf4_active import active_fixture

    f = active_fixture(monkeypatch)
    base_collector = f.collect
    f.client.collect_focus_step = base_collector
    adapter_calls = []
    original_adapter = active_redirect.collect_active_redirect

    def observe_adapter(**kwargs):
        adapter_calls.append(kwargs)
        return original_adapter(**kwargs)

    monkeypatch.setattr(active_redirect, "collect_active_redirect", observe_adapter)

    # Recreate the prior ordering: capture the interceptor, then replace the
    # public collector with Phase4B's controlled wrapper. Only its move=False
    # follow-up reaches the captured interceptor, where production falls through.
    def intercepted(**kwargs):
        return collection_flow._phase6d3a_intercept_focus_step(
            original_collect=base_collector, collect_kwargs=kwargs,
            client=f.client, dev="offline", state=f.state, phase_ctx=f.phase_ctx,
            step_idx=8, tab_cfg={**f.tab_cfg, "max_steps": 20},
        )

    f.client.collect_focus_step = intercepted
    saved_interceptor = f.client.collect_focus_step
    def old_controlled_wrapper(**kwargs):
        assert kwargs["move"] is True
        return saved_interceptor(move=False, direction="next", step_index=8)

    f.client.collect_focus_step = old_controlled_wrapper
    result = f.client.collect_focus_step(move=True, direction="next", step_index=8)

    assert result["focus_node"] == f.focus
    assert adapter_calls == []
    assert f.native == []
    assert len(f.collected) == 1 and f.collected[0]["move"] is False


def test_active_adapter_positive_candidate_reached_through_production_wrapper(monkeypatch):
    from tb_runner import active_redirect
    from tb_runner.phase4b_authority import ExecutionBudget
    from tb_runner.phase4b_execution import focus_row
    from test_phase6d3a_rf4_active import active_fixture

    f = active_fixture(monkeypatch)
    f.client.collect_focus_step = f.collect
    f.controller.budget.max_per_run = 1
    f.controller.budget.max_per_state = 1
    f.controller.budget.max_per_condition = 1
    monkeypatch.setattr(collection_flow, "_frontier_shadow_pre_decision", lambda **_kwargs: "pre")
    adapter_calls = []
    original_adapter = active_redirect.collect_active_redirect

    def observe_adapter(**kwargs):
        adapter_calls.append(kwargs)
        return original_adapter(**kwargs)

    monkeypatch.setattr(active_redirect, "collect_active_redirect", observe_adapter)
    controlled_fallback_calls = []

    def controlled_fallback(**kwargs):
        controlled_fallback_calls.append(kwargs)
        return pytest.fail("valid ACTIVE candidate must be evaluated before ordinary controlled fallback")

    def production_step():
        return smoke._invoke_step_with_controlled_collector(
            client=f.client, controlled_collector=controlled_fallback,
            step_call=lambda: f.client.collect_focus_step(move=True, direction="next", step_index=8),
        )

    row, decision_id = collection_flow._run_main_step_with_frontier_shadow(
        client=f.client, state=f.state, step_idx=8,
        tab_cfg={**f.tab_cfg, "max_steps": 20}, collect_step_fn=production_step,
        phase_ctx=f.phase_ctx, dev="offline",
    )

    audit = row["phase6d3a_redirect"]
    assert decision_id == "pre"
    assert len(adapter_calls) == 1
    assert adapter_calls[0]["original_collect"] is f.collect
    assert adapter_calls[0]["fallback_collect"] is controlled_fallback
    assert not controlled_fallback_calls
    assert audit["common_readiness"]["readiness_status"] == "READY"
    assert audit["ready"] is True
    assert audit["final_revalidation"] == "FINAL_REVALIDATION_PASS"
    assert audit["dispatch_count"] == 1
    assert len(f.native) == 1
    assert len(f.collected) == 1 and f.collected[0]["move"] is False
    assert f.controller.budget.redirects_used == 1
    assert f.client._phase6d3a_controlled_budget.actions == 1
    assert f.controller.budget.available(audit)[0] is False
    assert any(e["record"].get("event") == "NATIVE_DISPATCH_AUTHORIZED"
               for e in audit["phase5_authorization_events"])
    assert audit["common_readiness"].get("phase5_permit_issued") is False

    # The redirect result proceeds through the ordinary production reconciliation.
    collection_flow._apply_focus_reconciliation(
        client=f.client, dev="offline", row=row,
        previous_row=focus_row(f.raw["focus_node"], f.scenario_id),
        state=SimpleNamespace(reliability_metrics=None, consumed_cluster_signatures=set()),
        progress_decision=None, visit_decision=None,
    )
    assert row["focus_transition_status"] == "CONFIRMED_MOVED"
    assert row["visit_record_status"] == "RECORDED"
    collection_flow._phase6d3a_record_production_reconciliation(client=f.client, row=row)
    assert row["phase6d3a_redirect"]["production_reconciliation_recorded"] is True
    assert row["phase6d3a_redirect"]["production_target_reached"] is True
    assert len(controlled_fallback_calls) == 0
    assert isinstance(f.client._phase6d3a_controlled_budget, ExecutionBudget)


def test_active_adapter_no_candidate_falls_through_controlled_path_and_keeps_unknown(monkeypatch):
    from tb_runner import active_redirect
    from test_phase6d3a_rf4_active import active_fixture

    f = active_fixture(monkeypatch)
    f.client.collect_focus_step = f.collect
    # An incomplete current decision has no P0 candidate and remains UNKNOWN.
    incomplete = deepcopy(f.record)
    incomplete.update(shadow_decision="CONTINUE", selected_frontier=None,
                     frontier_exhaustion="UNKNOWN", evidence_complete=False)
    f.client._phase6d_exploration_shadow_runtime.decisions = [incomplete]
    monkeypatch.setattr(collection_flow, "_frontier_shadow_pre_decision", lambda **_kwargs: "pre")
    adapter_calls = []
    original_adapter = active_redirect.collect_active_redirect

    def observe_adapter(**kwargs):
        adapter_calls.append(kwargs)
        return original_adapter(**kwargs)

    monkeypatch.setattr(active_redirect, "collect_active_redirect", observe_adapter)
    action_calls, observation_calls = [], []

    def controlled_collector(**kwargs):
        action_calls.append(kwargs)
        assert kwargs["move"] is True
        row = f.client.collect_focus_step(move=False, direction="next", step_index=8)
        observation_calls.append(row)
        return row

    def production_step():
        return smoke._invoke_step_with_controlled_collector(
            client=f.client, controlled_collector=controlled_collector,
            step_call=lambda: f.client.collect_focus_step(move=True, direction="next", step_index=8),
        )

    row, _decision_id = collection_flow._run_main_step_with_frontier_shadow(
        client=f.client, state=f.state, step_idx=8,
        tab_cfg={**f.tab_cfg, "max_steps": 20}, collect_step_fn=production_step,
        phase_ctx=f.phase_ctx, dev="offline",
    )

    assert len(adapter_calls) == 1
    assert len(action_calls) == 1 and action_calls[0]["move"] is True
    assert len(observation_calls) == 1
    assert len(f.collected) == 1 and f.collected[0]["move"] is False
    assert row.get("phase6d3a_redirect") is None
    assert incomplete["frontier_exhaustion"] == "UNKNOWN"
    assert incomplete["evidence_complete"] is False
    assert f.controller.metrics.counters["REDIRECT_DISPATCH_COUNT"] == 0
    assert f.controller.budget.redirects_used == 0
    assert f.client._phase6d3a_controlled_budget.actions == 0
    assert f.native == []


def _run_rf5_actual_hook_actions(monkeypatch, tmp_path, fixture, actions, *, no_candidate=False):
    """Run the real RF5 launcher hook and production main-step wrapper offline."""
    import json
    import sys
    from types import SimpleNamespace

    from tb_runner import collection_flow as flow

    fixture.phase_ctx.output_path = str(tmp_path)
    fixture.client.collect_focus_step = fixture.collect
    if no_candidate:
        incomplete = deepcopy(fixture.record)
        incomplete.update(shadow_decision="CONTINUE", selected_frontier=None,
                         frontier_exhaustion="UNKNOWN", evidence_complete=False)
        fixture.client._phase6d_exploration_shadow_runtime.decisions = [incomplete]

    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"scenarios": {
        "device_smoke_sensor_plugin": {"max_steps": 7},
    }}), encoding="utf-8")
    evidence_path = tmp_path / "rf5-events.jsonl"
    for key, value in {
        "TB_PHASE4C_CONTROLLED": "1",
        "TB_PHASE4C_SMOKE_SCENARIO": "device_smoke_sensor_plugin",
        "TB_PHASE4C_SMOKE_OUT": str(tmp_path),
        "TB_RUNTIME_CONFIG_PATH": str(config),
        "TB_PHASE6D3A_RF5_MAIN_STEP_BUDGET": "7",
        "TB_PHASE6D3A_RF5_EVIDENCE_PATH": str(evidence_path),
        "TB_PHASE5A_ACTION_SAFETY_MODE": "off",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(smoke, "A11yAdbClient", lambda **_kwargs: object())

    observations = []
    controller_counts = []

    def fake_script_main():
        flow._phase6d3a_initialize_redirect_context(
            client=fixture.client, dev="offline", phase_ctx=fixture.phase_ctx,
            run_id=str((getattr(fixture.client, "_phase6d3a_redirect_context", {}) or {}).get(
                "scenario_run_id") or "rf5-counter-integration-test"),
        )
        for index, action in enumerate(actions, start=8):
            def step_call():
                if action == "observe":
                    return fixture.client.collect_focus_step(
                        move=False, direction="next", step_index=index)
                if action in {"focus", "stale_focus"}:
                    if action == "stale_focus":
                        decisions = fixture.client._phase6d_exploration_shadow_runtime.decisions
                        decisions[-1]["decision_evidence_usable"] = False
                    def controlled_fallback(**kwargs):
                        assert kwargs.get("move") is True
                        return fixture.client.collect_focus_step(
                            move=False, direction="next", step_index=index)
                    # Invoke the RF5-installed production interceptor with the
                    # same collector split used by the main-step wrapper. The
                    # read-only observations below still traverse the real
                    # production main-step wrapper; keeping these focus calls
                    # on the fixture's current closed decision lets the real
                    # ACTIVE controller produce two bounded evaluations.
                    return flow._phase6d3a_intercept_focus_step(
                        original_collect=controlled_fallback,
                        adapter_original_collect=fixture.collect,
                        collect_kwargs={"move": True, "direction": "next", "step_index": index},
                        client=fixture.client, dev="offline", state=fixture.state,
                        phase_ctx=fixture.phase_ctx, step_idx=index,
                        tab_cfg={**fixture.tab_cfg, "max_steps": 20},
                    )
                if action == "local_tab":
                    from tb_runner import local_tab_logic
                    from types import SimpleNamespace
                    monkeypatch.setattr(local_tab_logic, "_tap_local_tab_bounds_center",
                                        lambda **_kwargs: True)
                    monkeypatch.setattr(local_tab_logic, "_row_matches_pending_local_tab",
                                        lambda *_args, **_kwargs: (True, "fixture_match"))
                    monkeypatch.setattr(local_tab_logic, "_attempt_local_tab_content_entry_probe",
                                        lambda **_kwargs: None)
                    local_state = SimpleNamespace(
                        forced_local_tab_target_rid="com.example:id/tab",
                        forced_local_tab_target_label="Tab",
                        forced_local_tab_target_action_label="Tab",
                        forced_local_tab_target_signature="plugin||tab",
                        forced_local_tab_target_bounds="10,10,100,100",
                        forced_local_tab_attempt_count=0,
                        visited_local_tabs_by_signature={},
                    )
                    return local_tab_logic._activate_forced_local_tab_target(
                        client=fixture.client, dev="offline", state=local_state,
                        step_idx=index, wait_seconds=0,
                        announcement_wait_seconds=0,
                        announcement_idle_wait_seconds=0,
                        announcement_max_extra_wait_seconds=0,
                    )
                raise AssertionError(action)

            row, _decision_id = flow._run_main_step_with_frontier_shadow(
                client=fixture.client, state=fixture.state, step_idx=index,
                tab_cfg={**fixture.tab_cfg, "max_steps": 20},
                collect_step_fn=step_call, phase_ctx=fixture.phase_ctx, dev="offline",
            )
            observations.append(row)
            controller_counts.append(smoke._rf5_active_evaluation_count(fixture.controller))
        return 0

    monkeypatch.setitem(sys.modules, "script_test", SimpleNamespace(main=fake_script_main))
    result = smoke.main(generalized=True, rf5_harness=True)
    records = ([json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
               if evidence_path.exists() else [])
    return result, observations, controller_counts, records


def test_rf5_installed_hook_observations_do_not_consume_evaluation_cap(monkeypatch, tmp_path):
    from test_phase6d3a_rf4_active import active_fixture

    f = active_fixture(monkeypatch)
    result, rows, counts, records = _run_rf5_actual_hook_actions(
        monkeypatch, tmp_path, f, ["observe", "observe", "observe", "observe"])

    assert result == 0
    assert len(rows) == 4 and all(call.get("move") is False for call in f.collected)
    assert counts == [0, 0, 0, 0]
    assert smoke._rf5_active_evaluation_count(f.controller) == 0
    assert not f.controller.events
    assert f.controller.metrics.counters["REDIRECT_DISPATCH_COUNT"] == 0
    assert f.native == []
    assert not any(record.get("reason") == "RF5_EVALUATED_ATTEMPT_CAP" for record in records)


def test_rf5_installed_hook_counts_only_real_active_controller_evaluations(monkeypatch, tmp_path):
    from test_phase6d3a_rf4_active import active_fixture

    f = active_fixture(monkeypatch)
    result, rows, counts, records = _run_rf5_actual_hook_actions(
        monkeypatch, tmp_path, f, ["focus", "focus"])

    assert result == 0
    assert counts == [1, 2]
    assert [call.get("move") for call in f.collected] == [False, False]
    active_events = [event for event in f.controller.events
                     if event.get("mode") == "ACTIVE"
                     and event.get("schema_version") == "phase6d3a-redirect-attempt-v1"]
    assert len(active_events) == 2
    assert len(f.native) == 1
    assert f.controller.metrics.counters["REDIRECT_DISPATCH_COUNT"] == 1
    assert rows[0]["phase6d3a_redirect"]["dispatch_count"] == 1
    assert not any(record.get("reason") == "RF5_EVALUATED_ATTEMPT_CAP" for record in records)


def test_rf5_installed_hook_blocks_third_true_evaluation_from_controller_history(monkeypatch, tmp_path):
    from test_phase6d3a_rf4_active import active_fixture

    f = active_fixture(monkeypatch)
    result, rows, counts, records = _run_rf5_actual_hook_actions(
        monkeypatch, tmp_path, f, ["focus", "focus", "focus"])

    assert result == 0
    assert counts == [1, 2]
    assert len(rows) == 2
    assert smoke._rf5_active_evaluation_count(f.controller) == 2
    assert f.controller.metrics.counters["REDIRECT_DISPATCH_COUNT"] == 1
    assert len(f.native) == 1
    stops = [record for record in records if record.get("event") == "RF5_CONTROLLED_STOP"]
    assert len(stops) == 1
    assert stops[0]["reason"] == "RF5_EVALUATED_ATTEMPT_CAP"
    assert stops[0]["production_evaluation_count"] == 2


def test_rf5_stale_closed_decision_does_not_consume_evaluation_budget(monkeypatch, tmp_path):
    from test_phase6d3a_rf4_active import active_fixture

    f = active_fixture(monkeypatch)
    result, rows, counts, records = _run_rf5_actual_hook_actions(
        monkeypatch, tmp_path, f, ["focus", "stale_focus"])

    assert result == 0
    assert counts == [1]
    assert len(rows) == 1
    assert smoke._rf5_active_evaluation_count(f.controller) == 1
    assert f.controller.metrics.counters["REDIRECT_DISPATCH_COUNT"] == 1
    filters = [record for record in records if record.get("event") == "RF5_REDIRECT_FILTER"]
    assert [record["filter_kind"] for record in filters] == [
        "CANDIDATE_OPPORTUNITY", "STALE_CURRENTNESS_REJECTION"]
    stops = [record for record in records if record.get("event") == "RF5_CONTROLLED_STOP"]
    assert len(stops) == 1
    assert stops[0]["reason"] == "STALE_DECISION_REJECTED_WITH_ZERO_REDIRECT_DISPATCH"


def test_rf5_local_tab_move_false_post_action_observation_does_not_count(monkeypatch, tmp_path):
    from test_phase6d3a_rf4_active import active_fixture

    f = active_fixture(monkeypatch)
    result, _rows, counts, _records = _run_rf5_actual_hook_actions(
        monkeypatch, tmp_path, f, ["local_tab", "local_tab", "local_tab"])

    assert result == 0
    assert counts == [0, 0, 0]
    assert [call.get("move") for call in f.collected] == [False, False, False]
    assert not f.controller.events
    assert f.controller.metrics.counters["REDIRECT_DISPATCH_COUNT"] == 0
    assert f.native == []


def test_rf5_no_candidate_true_call_uses_fallback_without_evaluation(monkeypatch, tmp_path):
    from test_phase6d3a_rf4_active import active_fixture

    f = active_fixture(monkeypatch)
    result, rows, counts, _records = _run_rf5_actual_hook_actions(
        monkeypatch, tmp_path, f, ["focus"], no_candidate=True)

    assert result == 0
    assert counts == [0]
    assert len(rows) == 1 and rows[0].get("phase6d3a_redirect") is None
    assert [call.get("move") for call in f.collected] == [False]
    assert not f.controller.events
    assert f.controller.metrics.counters["REDIRECT_DISPATCH_COUNT"] == 0
    assert f.native == []
