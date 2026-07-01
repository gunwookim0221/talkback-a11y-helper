from __future__ import annotations

import json

from qa_frontend.backend.runtime_config_selection import write_selected_runtime_config
from tb_runner.runtime_config import RUNTIME_CONFIG_PATH_ENV, load_runtime_bundle


def test_write_selected_runtime_config_enables_only_selected_and_preserves_values(tmp_path):
    source_path = tmp_path / "runtime_config.json"
    output_path = tmp_path / "run" / "runtime_config.json"
    source = {
        "scenarios": {
            "global_nav_main": {"enabled": False, "max_steps": 10},
            "life_family_care_plugin": {"enabled": True, "max_steps": 50},
        }
    }
    source_text = json.dumps(source, ensure_ascii=False, indent=2)
    source_path.write_text(source_text, encoding="utf-8")

    result = write_selected_runtime_config(
        source_path=source_path,
        output_path=output_path,
        scenario_ids=["global_nav_main"],
        mode="full",
    )

    generated = json.loads(output_path.read_text(encoding="utf-8"))
    assert generated["scenarios"]["global_nav_main"]["enabled"] is True
    assert generated["scenarios"]["global_nav_main"]["max_steps"] == 10
    assert generated["scenarios"]["life_family_care_plugin"]["enabled"] is False
    assert generated["scenarios"]["life_family_care_plugin"]["max_steps"] == 50
    assert source_path.read_text(encoding="utf-8") == source_text
    assert result["source_unchanged"] is True
    assert result["enabled_ids"] == ["global_nav_main"]
    assert result["max_steps_policy"] == "source_preserved"


def test_write_selected_runtime_config_smoke_overrides_selected_max_steps(tmp_path):
    source_path = tmp_path / "runtime_config.json"
    output_path = tmp_path / "run" / "runtime_config.json"
    source = {
        "scenarios": {
            "global_nav_main": {"enabled": False, "max_steps": 40},
            "life_family_care_plugin": {"enabled": True, "max_steps": 50},
            "device_smoke_sensor_plugin": {"enabled": True, "max_steps": 30},
            "menu_main": {"enabled": True, "max_steps": 22},
        }
    }
    source_text = json.dumps(source, ensure_ascii=False, indent=2)
    source_path.write_text(source_text, encoding="utf-8")

    result = write_selected_runtime_config(
        source_path=source_path,
        output_path=output_path,
        scenario_ids=["global_nav_main", "life_family_care_plugin", "device_smoke_sensor_plugin"],
        mode="smoke",
    )

    generated = json.loads(output_path.read_text(encoding="utf-8"))
    assert generated["scenarios"]["global_nav_main"]["enabled"] is True
    assert generated["scenarios"]["global_nav_main"]["max_steps"] == 6
    assert generated["scenarios"]["life_family_care_plugin"]["enabled"] is True
    assert generated["scenarios"]["life_family_care_plugin"]["max_steps"] == 8
    assert generated["scenarios"]["device_smoke_sensor_plugin"]["enabled"] is True
    assert generated["scenarios"]["device_smoke_sensor_plugin"]["max_steps"] == 8
    assert generated["scenarios"]["menu_main"]["enabled"] is False
    assert generated["scenarios"]["menu_main"]["max_steps"] == 22
    assert source_path.read_text(encoding="utf-8") == source_text
    assert result["source_unchanged"] is True
    assert result["max_steps_policy"] == "smoke_override"
    assert result["enabled_ids"] == [
        "global_nav_main",
        "life_family_care_plugin",
        "device_smoke_sensor_plugin",
    ]
    scenario_steps = {entry["scenario"]: entry for entry in result["scenario_steps"]}
    assert scenario_steps["global_nav_main"]["effective_max_steps"] == 6
    assert scenario_steps["global_nav_main"]["original_max_steps"] == 40
    assert scenario_steps["global_nav_main"]["policy"] == "smoke_override"
    assert scenario_steps["life_family_care_plugin"]["effective_max_steps"] == 8
    assert scenario_steps["device_smoke_sensor_plugin"]["effective_max_steps"] == 8
    assert scenario_steps["menu_main"]["policy"] == "source_preserved"


def test_runtime_config_env_path_is_used_by_runner_loader(tmp_path, monkeypatch):
    path = tmp_path / "runtime_env.json"
    path.write_text(
        json.dumps({"scenarios": {"home_main": {"enabled": True, "max_steps": 12}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(RUNTIME_CONFIG_PATH_ENV, str(path))

    bundle = load_runtime_bundle([{"scenario_id": "home_main", "enabled": False, "max_steps": 5}])

    home_cfg = bundle["tab_configs"][0]
    assert home_cfg["enabled"] is True
    assert home_cfg["max_steps"] == 12


def test_full_shadow_request_enables_only_run_local_v10_flags(tmp_path):
    source_path = tmp_path / "runtime_config.json"
    output_path = tmp_path / "run" / "runtime_config.json"
    source = {
        "v10": {
            "feature_flags": {
                "inventory_enabled": False,
                "quick_identify_enabled": False,
                "policy_mapping_enabled": False,
                "shadow_validation_enabled": False,
            }
        },
        "scenarios": {"devices_main": {"enabled": False, "max_steps": 20}},
    }
    source_text = json.dumps(source, ensure_ascii=False, indent=2)
    source_path.write_text(source_text, encoding="utf-8")

    result = write_selected_runtime_config(
        source_path=source_path,
        output_path=output_path,
        scenario_ids=["devices_main"],
        mode="full",
        shadow_validation=True,
    )

    generated = json.loads(output_path.read_text(encoding="utf-8"))
    assert all(generated["v10"]["feature_flags"].values())
    assert result["shadow_validation_enabled"] is True
    assert source_path.read_text(encoding="utf-8") == source_text


def test_shadow_flags_stay_off_for_off_request_and_smoke_request(tmp_path):
    source_path = tmp_path / "runtime_config.json"
    source_path.write_text(
        json.dumps(
            {
                "v10": {
                    "feature_flags": {
                        "inventory_enabled": True,
                        "quick_identify_enabled": True,
                        "policy_mapping_enabled": True,
                        "shadow_validation_enabled": True,
                    }
                },
                "scenarios": {"devices_main": {"enabled": False, "max_steps": 20}},
            }
        ),
        encoding="utf-8",
    )

    for name, mode, requested in (
        ("full-off", "full", False),
        ("smoke-on", "smoke", True),
    ):
        output_path = tmp_path / name / "runtime_config.json"
        result = write_selected_runtime_config(
            source_path=source_path,
            output_path=output_path,
            scenario_ids=["devices_main"],
            mode=mode,
            shadow_validation=requested,
        )
        generated = json.loads(output_path.read_text(encoding="utf-8"))
        assert not any(generated["v10"]["feature_flags"].values())
        assert result["shadow_validation_enabled"] is False
