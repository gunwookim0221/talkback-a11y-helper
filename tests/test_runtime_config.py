import json

from tb_runner.runtime_config import load_runtime_bundle


def _base_tabs():
    return [
        {"scenario_id": "home_main", "tab_name": "Home", "enabled": True, "max_steps": 5},
        {"scenario_id": "device_detail", "tab_name": "Device", "enabled": True, "max_steps": 7},
    ]


def test_load_runtime_bundle_without_file_keeps_defaults(tmp_path):
    bundle = load_runtime_bundle(_base_tabs(), config_path=tmp_path / "missing.json")

    assert bundle["checkpoint_save_every"] == 3
    assert bundle["tab_configs"][0]["max_steps"] == 5
    assert bundle["tab_configs"][0]["enabled"] is True
    assert bundle["tab_configs"][0]["tab_select_retry_count"] == 2


def test_load_runtime_bundle_applies_partial_overrides(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "global": {"checkpoint_save_every": 5},
                "scenarios": {
                    "home_main": {"enabled": False, "max_steps": 40},
                },
            }
        ),
        encoding="utf-8",
    )

    bundle = load_runtime_bundle(_base_tabs(), config_path=path)

    assert bundle["checkpoint_save_every"] == 5
    home_cfg = bundle["tab_configs"][0]
    assert home_cfg["enabled"] is False
    assert home_cfg["max_steps"] == 40
    assert home_cfg["checkpoint_save_every"] == 5


def test_load_runtime_bundle_ignores_invalid_values(tmp_path):
    path = tmp_path / "runtime_invalid.json"
    path.write_text(
        json.dumps(
            {
                "global": {"checkpoint_save_every": 0},
                "defaults": {
                    "tab_select_retry_count": -1,
                    "main_step_wait_seconds": "x",
                },
                "scenarios": {
                    "home_main": {
                        "enabled": "no",
                        "max_steps": 0,
                        "anchor_retry_count": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    bundle = load_runtime_bundle(_base_tabs(), config_path=path)

    home_cfg = bundle["tab_configs"][0]
    assert bundle["checkpoint_save_every"] == 3
    assert home_cfg["enabled"] is True
    assert home_cfg["max_steps"] == 5
    assert home_cfg["tab_select_retry_count"] == 2
    assert home_cfg["anchor_retry_count"] == 2
    assert home_cfg["main_step_wait_seconds"] == 1.2
