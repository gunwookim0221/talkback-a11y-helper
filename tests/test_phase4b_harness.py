import json
import sys
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools import phase4b_controlled_smoke as smoke
from tools import phase4b_controlled_monitor as supervisor
from state_model_fixtures import node, observation


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


def test_normal_production_has_no_phase4b_imports():
    root = Path(__file__).resolve().parents[1]
    for name in ("script_test.py", "tb_runner/collection_flow.py", "talkback_lib/__init__.py",
                 "config/runtime_config.json"):
        assert "phase4b" not in (root / name).read_text(encoding="utf-8").lower()


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
