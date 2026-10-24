import json
from pathlib import Path

import pytest

from tools import phase4b_controlled_smoke as smoke
from tools import phase6d3a_rf5_harness as rf5
from tb_runner.phase4c_traversal import BUDGETS
from tb_runner.run_spec import RunSpec
from tb_runner.scenario_config import TAB_CONFIGS, canonical_full_scenario_ids


def _production_config(scenario_id):
    matches = [item for item in TAB_CONFIGS if item.get("scenario_id") == scenario_id]
    assert len(matches) == 1
    return matches[0]


def test_rf5_launcher_defaults_to_smoke_sensor_and_accepts_explicit_selection(tmp_path):
    default = rf5.offline_gate(tmp_path / "default")
    explicit_smoke = rf5.offline_gate(tmp_path / "smoke", "device_smoke_sensor_plugin")

    assert rf5.DEFAULT_SCENARIO == "device_smoke_sensor_plugin"
    assert default["scenario"] == explicit_smoke["scenario"] == rf5.DEFAULT_SCENARIO
    assert default["child_environment"]["TB_PHASE4C_SMOKE_SCENARIO"] == rf5.DEFAULT_SCENARIO
    assert explicit_smoke["child_environment"]["TB_PHASE4C_SMOKE_SCENARIO"] == rf5.DEFAULT_SCENARIO


def test_rf5_air_purifier_uses_production_config_and_automatic_entry(tmp_path):
    scenario_id = "device_air_purifier_plugin"
    production = _production_config(scenario_id)
    selected = rf5._scenario_config(scenario_id)
    gate = rf5.offline_gate(tmp_path / "air", scenario_id)
    runtime = json.loads(Path(gate["runtime_config_path"]).read_text(encoding="utf-8"))

    assert selected is production
    assert RunSpec().entry_mode == "AUTOMATED"
    assert scenario_id in canonical_full_scenario_ids()
    assert BUDGETS.get(scenario_id, rf5.RF5_CONTROLLED_ACTION_BUDGET) >= rf5.NATIVE_REDIRECT_DISPATCH_CAP
    assert gate["scenario"] == scenario_id
    assert gate["entry_mode"] == "AUTOMATED"
    assert gate["child_environment"]["TB_PHASE4C_SMOKE_SCENARIO"] == scenario_id
    assert gate["controlled_action_budget"] == BUDGETS.get(
        scenario_id, rf5.RF5_CONTROLLED_ACTION_BUDGET)
    assert runtime["scenarios"][scenario_id]["enabled"] is True
    assert runtime["scenarios"][scenario_id]["max_steps"] == rf5.MAIN_STEP_BUDGET
    assert all(value.get("enabled") is False for key, value in runtime["scenarios"].items()
               if key != scenario_id and isinstance(value, dict))
    assert gate["entry_route"].startswith("production scenario pre_navigation")
    assert "연기" not in gate["entry_route"] and "Smoke sensor" not in gate["entry_route"]
    assert selected["pre_navigation"] == production["pre_navigation"]
    assert any(item.get("action") == "enter_device_card_plugin"
               for item in selected["pre_navigation"])


def test_rf5_allowlist_rejects_unsupported_scenarios_without_fallback(tmp_path):
    with pytest.raises(ValueError, match="Unsupported RF5 scenario"):
        rf5.offline_gate(tmp_path / "unsupported", "device_camera_plugin")

    assert rf5.SUPPORTED_SCENARIOS == (
        "device_smoke_sensor_plugin", "device_air_purifier_plugin")


@pytest.mark.parametrize("scenario_id", rf5.SUPPORTED_SCENARIOS)
def test_rf5_scenario_id_reaches_runner_gate_before_any_device_client(monkeypatch, tmp_path, scenario_id):
    gate = rf5.offline_gate(tmp_path / scenario_id, scenario_id)
    for key, value in gate["child_environment"].items():
        monkeypatch.setenv(key, value)

    class ReachedRunnerGate(Exception):
        pass

    def no_device_client(**_kwargs):
        raise ReachedRunnerGate(scenario_id)

    monkeypatch.setattr(smoke, "A11yAdbClient", no_device_client, raising=False)
    with pytest.raises(ReachedRunnerGate, match=scenario_id):
        smoke.main(generalized=True, rf5_harness=True)


def test_rf5_result_metadata_keeps_selected_scenario_identity(monkeypatch, tmp_path):
    monkeypatch.delenv("TB_EXPLORATION_REDIRECT_MODE", raising=False)
    result = rf5._run_result_metadata(
        scenario_id="device_air_purifier_plugin",
        serial="offline",
        child_exit_code=0,
        elapsed_seconds=1.23456,
        log_path=tmp_path / "air.log",
        runtime_config_path=str(tmp_path / "runtime_config.json"),
        evidence_path=tmp_path / "air-events.jsonl",
    )

    assert result["scenario"] == "device_air_purifier_plugin"
    assert "device_smoke_sensor_plugin" not in json.dumps(result)
    assert result["device_execution"] is True


def test_rf5_cli_scenario_selection_is_bounded_and_written_to_gate(monkeypatch, tmp_path, capsys):
    output = tmp_path / "cli-output"
    monkeypatch.setattr("sys.argv", ["phase6d3a_rf5_harness", "--offline-only",
                                     "--scenario", "device_air_purifier_plugin",
                                     "--output-dir", str(output)])

    assert rf5.main() == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads((output / "RF5H_OFFLINE_GATE.json").read_text(encoding="utf-8"))
    assert printed["scenario"] == written["scenario"] == "device_air_purifier_plugin"
    assert "child_environment" not in written


def test_rf5_cli_rejects_unsupported_scenario_before_gate(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["phase6d3a_rf5_harness", "--offline-only",
                                     "--scenario", "device_home_camera_plugin",
                                     "--output-dir", str(tmp_path / "rejected")])

    with pytest.raises(SystemExit) as exc:
        rf5.main()
    assert exc.value.code == 2
    assert not (tmp_path / "rejected").exists()


def test_rf5_child_rejects_missing_scenario_without_default_fallback(monkeypatch):
    monkeypatch.delenv("TB_PHASE4C_SMOKE_SCENARIO", raising=False)

    with pytest.raises(ValueError, match="Unsupported RF5 scenario"):
        rf5._child_main()


def test_rf5_scenario_selection_preserves_bounded_redirect_contract(tmp_path):
    for scenario_id in rf5.SUPPORTED_SCENARIOS:
        gate = rf5.offline_gate(tmp_path / scenario_id, scenario_id)
        assert gate["redirect_attempt_budget"] == 2
        assert gate["native_redirect_dispatch_cap"] == 1

    assert rf5.REDIRECT_ATTEMPT_BUDGET == 2
    assert rf5.NATIVE_REDIRECT_DISPATCH_CAP == 1
