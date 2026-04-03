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
    assert bundle["tab_configs"][0]["pre_navigation_retry_count"] == 2


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
                    "pre_navigation_retry_count": 0,
                },
                "scenarios": {
                    "home_main": {
                        "enabled": "no",
                        "max_steps": 0,
                        "anchor_retry_count": 0,
                        "pre_navigation_wait_seconds": -1,
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
    assert home_cfg["pre_navigation_retry_count"] == 2
    assert home_cfg["pre_navigation_wait_seconds"] == 1.2


def test_load_runtime_bundle_applies_screen_context_overrides(tmp_path):
    path = tmp_path / "runtime_modes.json"
    path.write_text(
        json.dumps(
            {
                "defaults": {"screen_context_mode": "new_screen", "stabilization_mode": "anchor_only"},
                "scenarios": {
                    "device_detail": {"screen_context_mode": "bottom_tab", "stabilization_mode": "tab_context"}
                },
            }
        ),
        encoding="utf-8",
    )

    bundle = load_runtime_bundle(_base_tabs(), config_path=path)

    home_cfg = bundle["tab_configs"][0]
    detail_cfg = bundle["tab_configs"][1]
    assert home_cfg["screen_context_mode"] == "new_screen"
    assert home_cfg["stabilization_mode"] == "anchor_only"
    assert detail_cfg["screen_context_mode"] == "bottom_tab"
    assert detail_cfg["stabilization_mode"] == "tab_context"


def test_load_runtime_bundle_invalid_screen_context_values_fallback(tmp_path):
    path = tmp_path / "runtime_invalid_modes.json"
    path.write_text(
        json.dumps(
            {
                "defaults": {"screen_context_mode": "wrong", "stabilization_mode": "wrong"},
                "scenarios": {
                    "home_main": {"screen_context_mode": "also_wrong", "stabilization_mode": "also_wrong"}
                },
            }
        ),
        encoding="utf-8",
    )

    bundle = load_runtime_bundle(_base_tabs(), config_path=path)

    home_cfg = bundle["tab_configs"][0]
    assert home_cfg["screen_context_mode"] == "bottom_tab"
    assert home_cfg["stabilization_mode"] == "anchor_then_context"


def test_load_runtime_bundle_preserves_base_explicit_values(tmp_path):
    path = tmp_path / "runtime_preserve_base.json"
    path.write_text(
        json.dumps(
            {
                "defaults": {
                    "screen_context_mode": "bottom_tab",
                    "stabilization_mode": "anchor_then_context",
                    "pre_navigation_retry_count": 9,
                    "pre_navigation_wait_seconds": 9.9,
                    "tab_select_retry_count": 5,
                    "anchor_retry_count": 5,
                    "main_step_wait_seconds": 5.5,
                    "main_announcement_wait_seconds": 5.5,
                    "overlay_step_wait_seconds": 4.4,
                    "overlay_announcement_wait_seconds": 4.4,
                    "back_recovery_wait_seconds": 3.3,
                }
            }
        ),
        encoding="utf-8",
    )
    base_tabs = [
        {
            "scenario_id": "settings_entry_example",
            "tab_name": "Menu",
            "enabled": True,
            "max_steps": 3,
            "screen_context_mode": "new_screen",
            "stabilization_mode": "anchor_only",
            "pre_navigation_retry_count": 2,
            "pre_navigation_wait_seconds": 1.2,
            "tab_select_retry_count": 2,
            "anchor_retry_count": 2,
            "main_step_wait_seconds": 1.2,
            "main_announcement_wait_seconds": 1.2,
            "overlay_step_wait_seconds": 0.8,
            "overlay_announcement_wait_seconds": 0.8,
            "back_recovery_wait_seconds": 0.8,
        }
    ]

    bundle = load_runtime_bundle(base_tabs, config_path=path)
    cfg = bundle["tab_configs"][0]
    assert cfg["screen_context_mode"] == "new_screen"
    assert cfg["stabilization_mode"] == "anchor_only"
    assert cfg["pre_navigation_retry_count"] == 2
    assert cfg["pre_navigation_wait_seconds"] == 1.2
    assert cfg["tab_select_retry_count"] == 2
    assert cfg["anchor_retry_count"] == 2
    assert cfg["main_step_wait_seconds"] == 1.2
    assert cfg["main_announcement_wait_seconds"] == 1.2
    assert cfg["overlay_step_wait_seconds"] == 0.8
    assert cfg["overlay_announcement_wait_seconds"] == 0.8
    assert cfg["back_recovery_wait_seconds"] == 0.8


def test_load_runtime_bundle_fills_missing_then_applies_override(tmp_path):
    path = tmp_path / "runtime_fill_then_override.json"
    path.write_text(
        json.dumps(
            {
                "defaults": {
                    "screen_context_mode": "new_screen",
                    "stabilization_mode": "anchor_only",
                    "pre_navigation_retry_count": 4,
                },
                "scenarios": {
                    "home_main": {
                        "screen_context_mode": "bottom_tab",
                        "stabilization_mode": "tab_context",
                        "pre_navigation_retry_count": 7,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    bundle = load_runtime_bundle(_base_tabs(), config_path=path)
    home_cfg = bundle["tab_configs"][0]
    detail_cfg = bundle["tab_configs"][1]
    assert home_cfg["screen_context_mode"] == "bottom_tab"
    assert home_cfg["stabilization_mode"] == "tab_context"
    assert home_cfg["pre_navigation_retry_count"] == 7
    assert detail_cfg["screen_context_mode"] == "new_screen"
    assert detail_cfg["stabilization_mode"] == "anchor_only"
    assert detail_cfg["pre_navigation_retry_count"] == 4
