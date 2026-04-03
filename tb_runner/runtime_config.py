import copy
import json
from pathlib import Path
from typing import Any

from tb_runner.constants import (
    BACK_RECOVERY_WAIT_SECONDS,
    CHECKPOINT_SAVE_EVERY_STEPS,
    MAIN_ANNOUNCEMENT_WAIT_SECONDS,
    MAIN_STEP_WAIT_SECONDS,
    OVERLAY_ANNOUNCEMENT_WAIT_SECONDS,
    OVERLAY_STEP_WAIT_SECONDS,
)
from tb_runner.logging_utils import log

RUNTIME_CONFIG_VERSION = "1.7.26"
DEFAULT_RUNTIME_CONFIG_PATH = Path("config/runtime_config.json")


_DEFAULTS = {
    "tab_select_retry_count": 2,
    "anchor_retry_count": 2,
    "main_step_wait_seconds": MAIN_STEP_WAIT_SECONDS,
    "main_announcement_wait_seconds": MAIN_ANNOUNCEMENT_WAIT_SECONDS,
    "main_announcement_idle_wait_seconds": 0.5,
    "main_announcement_max_extra_wait_seconds": 1.5,
    "overlay_step_wait_seconds": OVERLAY_STEP_WAIT_SECONDS,
    "overlay_announcement_wait_seconds": OVERLAY_ANNOUNCEMENT_WAIT_SECONDS,
    "overlay_announcement_idle_wait_seconds": 0.4,
    "overlay_announcement_max_extra_wait_seconds": 1.0,
    "back_recovery_wait_seconds": BACK_RECOVERY_WAIT_SECONDS,
    "pre_navigation_retry_count": 2,
    "pre_navigation_wait_seconds": MAIN_STEP_WAIT_SECONDS,
    "screen_context_mode": "bottom_tab",
    "stabilization_mode": "anchor_then_context",
    "scenario_type": "content",
    "stop_policy": {
        "stop_on_global_nav_entry": False,
        "stop_on_global_nav_exit": False,
        "stop_on_terminal": True,
        "stop_on_repeat_no_progress": True,
    },
    "global_nav": {
        "labels": [],
        "resource_ids": [],
        "selected_pattern": "",
        "region_hint": "auto",
    },
}


_OVERRIDE_KEYS = {
    "tab_select_retry_count",
    "anchor_retry_count",
    "main_step_wait_seconds",
    "main_announcement_wait_seconds",
    "main_announcement_idle_wait_seconds",
    "main_announcement_max_extra_wait_seconds",
    "overlay_step_wait_seconds",
    "overlay_announcement_wait_seconds",
    "overlay_announcement_idle_wait_seconds",
    "overlay_announcement_max_extra_wait_seconds",
    "back_recovery_wait_seconds",
    "pre_navigation_retry_count",
    "pre_navigation_wait_seconds",
    "screen_context_mode",
    "stabilization_mode",
}


def _load_json_file(config_path: Path) -> dict[str, Any]:
    try:
        with config_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except FileNotFoundError:
        return {}
    except Exception as exc:  # defensive
        log(f"[CONFIG] runtime config load failed path='{config_path}' reason='{exc}'")
        return {}

    if not isinstance(data, dict):
        log(f"[CONFIG] runtime config ignored path='{config_path}' reason='root_not_object'")
        return {}
    return data


def _to_positive_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int) and value > 0:
        return value
    return fallback


def _to_positive_float(value: Any, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return fallback


def _to_enum_value(value: Any, allowed: set[str], fallback: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in allowed:
            return normalized
    return fallback


def _build_runtime_defaults(raw_defaults: dict[str, Any]) -> dict[str, Any]:
    raw_stop_policy = raw_defaults.get("stop_policy", {})
    if not isinstance(raw_stop_policy, dict):
        raw_stop_policy = {}
    raw_global_nav = raw_defaults.get("global_nav", {})
    if not isinstance(raw_global_nav, dict):
        raw_global_nav = {}
    return {
        "tab_select_retry_count": _to_positive_int(
            raw_defaults.get("tab_select_retry_count"),
            _DEFAULTS["tab_select_retry_count"],
        ),
        "anchor_retry_count": _to_positive_int(
            raw_defaults.get("anchor_retry_count"),
            _DEFAULTS["anchor_retry_count"],
        ),
        "main_step_wait_seconds": _to_positive_float(
            raw_defaults.get("main_step_wait_seconds"),
            _DEFAULTS["main_step_wait_seconds"],
        ),
        "main_announcement_wait_seconds": _to_positive_float(
            raw_defaults.get("main_announcement_wait_seconds"),
            _DEFAULTS["main_announcement_wait_seconds"],
        ),
        "main_announcement_idle_wait_seconds": _to_positive_float(
            raw_defaults.get("main_announcement_idle_wait_seconds"),
            _DEFAULTS["main_announcement_idle_wait_seconds"],
        ),
        "main_announcement_max_extra_wait_seconds": _to_positive_float(
            raw_defaults.get("main_announcement_max_extra_wait_seconds"),
            _DEFAULTS["main_announcement_max_extra_wait_seconds"],
        ),
        "overlay_step_wait_seconds": _to_positive_float(
            raw_defaults.get("overlay_step_wait_seconds"),
            _DEFAULTS["overlay_step_wait_seconds"],
        ),
        "overlay_announcement_wait_seconds": _to_positive_float(
            raw_defaults.get("overlay_announcement_wait_seconds"),
            _DEFAULTS["overlay_announcement_wait_seconds"],
        ),
        "overlay_announcement_idle_wait_seconds": _to_positive_float(
            raw_defaults.get("overlay_announcement_idle_wait_seconds"),
            _DEFAULTS["overlay_announcement_idle_wait_seconds"],
        ),
        "overlay_announcement_max_extra_wait_seconds": _to_positive_float(
            raw_defaults.get("overlay_announcement_max_extra_wait_seconds"),
            _DEFAULTS["overlay_announcement_max_extra_wait_seconds"],
        ),
        "back_recovery_wait_seconds": _to_positive_float(
            raw_defaults.get("back_recovery_wait_seconds"),
            _DEFAULTS["back_recovery_wait_seconds"],
        ),
        "pre_navigation_retry_count": _to_positive_int(
            raw_defaults.get("pre_navigation_retry_count"),
            _DEFAULTS["pre_navigation_retry_count"],
        ),
        "pre_navigation_wait_seconds": _to_positive_float(
            raw_defaults.get("pre_navigation_wait_seconds"),
            _DEFAULTS["pre_navigation_wait_seconds"],
        ),
        "screen_context_mode": _to_enum_value(
            raw_defaults.get("screen_context_mode"),
            {"bottom_tab", "new_screen"},
            _DEFAULTS["screen_context_mode"],
        ),
        "stabilization_mode": _to_enum_value(
            raw_defaults.get("stabilization_mode"),
            {"tab_context", "anchor_only", "anchor_then_context"},
            _DEFAULTS["stabilization_mode"],
        ),
        "scenario_type": _to_enum_value(
            raw_defaults.get("scenario_type"),
            {"content", "global_nav"},
            _DEFAULTS["scenario_type"],
        ),
        "stop_policy": {
            "stop_on_global_nav_entry": bool(raw_stop_policy.get("stop_on_global_nav_entry", False)),
            "stop_on_global_nav_exit": bool(raw_stop_policy.get("stop_on_global_nav_exit", False)),
            "stop_on_terminal": bool(raw_stop_policy.get("stop_on_terminal", True)),
            "stop_on_repeat_no_progress": bool(raw_stop_policy.get("stop_on_repeat_no_progress", True)),
        },
        "global_nav": {
            "labels": [str(item) for item in raw_global_nav.get("labels", []) if isinstance(item, str)],
            "resource_ids": [str(item) for item in raw_global_nav.get("resource_ids", []) if isinstance(item, str)],
            "selected_pattern": str(raw_global_nav.get("selected_pattern", "") or ""),
            "region_hint": _to_enum_value(
                raw_global_nav.get("region_hint"),
                {"bottom_tabs", "left_rail", "auto"},
                "auto",
            ),
        },
    }


def _fill_missing_values(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, default_value in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(default_value)
            continue
        existing_value = target.get(key)
        if isinstance(existing_value, dict) and isinstance(default_value, dict):
            _fill_missing_values(existing_value, default_value)


def load_runtime_bundle(base_tab_configs: list[dict[str, Any]], config_path: str | Path | None = None) -> dict[str, Any]:
    resolved_path = Path(config_path) if config_path else DEFAULT_RUNTIME_CONFIG_PATH
    raw_config = _load_json_file(resolved_path)

    if raw_config:
        log(f"[CONFIG] runtime config loaded path='{resolved_path}'")

    raw_global = raw_config.get("global", {})
    if not isinstance(raw_global, dict):
        raw_global = {}

    raw_defaults = raw_config.get("defaults", {})
    if not isinstance(raw_defaults, dict):
        raw_defaults = {}

    raw_scenarios = raw_config.get("scenarios", {})
    if not isinstance(raw_scenarios, dict):
        raw_scenarios = {}

    runtime_defaults = _build_runtime_defaults(raw_defaults)

    checkpoint_save_every = _to_positive_int(
        raw_global.get("checkpoint_save_every"),
        CHECKPOINT_SAVE_EVERY_STEPS,
    )

    merged_tab_configs: list[dict[str, Any]] = []
    for base_cfg in base_tab_configs:
        merged_cfg = copy.deepcopy(base_cfg)
        _fill_missing_values(merged_cfg, runtime_defaults)

        merged_cfg["checkpoint_save_every"] = checkpoint_save_every

        scenario_id = str(base_cfg.get("scenario_id", "") or "")
        scenario_override = raw_scenarios.get(scenario_id, {})
        if isinstance(scenario_override, dict):
            if "enabled" in scenario_override and isinstance(scenario_override.get("enabled"), bool):
                merged_cfg["enabled"] = scenario_override.get("enabled")
            if "max_steps" in scenario_override:
                merged_cfg["max_steps"] = _to_positive_int(
                    scenario_override.get("max_steps"),
                    int(base_cfg.get("max_steps", 1) or 1),
                )

            for key in _OVERRIDE_KEYS:
                if key in scenario_override:
                    base_value = merged_cfg.get(key, runtime_defaults[key])
                    if isinstance(base_value, int):
                        merged_cfg[key] = _to_positive_int(scenario_override.get(key), base_value)
                    elif isinstance(base_value, str):
                        allowed_values = {"bottom_tab", "new_screen"} if key == "screen_context_mode" else {
                            "tab_context",
                            "anchor_only",
                            "anchor_then_context",
                        }
                        merged_cfg[key] = _to_enum_value(scenario_override.get(key), allowed_values, base_value)
                    else:
                        merged_cfg[key] = _to_positive_float(scenario_override.get(key), float(base_value))

            if "scenario_type" in scenario_override:
                merged_cfg["scenario_type"] = _to_enum_value(
                    scenario_override.get("scenario_type"),
                    {"content", "global_nav"},
                    str(merged_cfg.get("scenario_type", "content") or "content"),
                )

            if "stop_policy" in scenario_override and isinstance(scenario_override.get("stop_policy"), dict):
                merged_policy = dict(merged_cfg.get("stop_policy", {}) or {})
                override_policy = scenario_override.get("stop_policy", {})
                merged_policy["stop_on_global_nav_entry"] = bool(
                    override_policy.get(
                        "stop_on_global_nav_entry",
                        merged_policy.get("stop_on_global_nav_entry", False),
                    )
                )
                merged_policy["stop_on_global_nav_exit"] = bool(
                    override_policy.get(
                        "stop_on_global_nav_exit",
                        merged_policy.get("stop_on_global_nav_exit", False),
                    )
                )
                merged_policy["stop_on_terminal"] = bool(
                    override_policy.get("stop_on_terminal", merged_policy.get("stop_on_terminal", True))
                )
                merged_policy["stop_on_repeat_no_progress"] = bool(
                    override_policy.get(
                        "stop_on_repeat_no_progress",
                        merged_policy.get("stop_on_repeat_no_progress", True),
                    )
                )
                merged_cfg["stop_policy"] = merged_policy

            if "global_nav" in scenario_override and isinstance(scenario_override.get("global_nav"), dict):
                merged_global_nav = dict(merged_cfg.get("global_nav", {}) or {})
                override_global_nav = scenario_override.get("global_nav", {})
                if isinstance(override_global_nav.get("labels"), list):
                    merged_global_nav["labels"] = [
                        str(item) for item in override_global_nav.get("labels", []) if isinstance(item, str)
                    ]
                if isinstance(override_global_nav.get("resource_ids"), list):
                    merged_global_nav["resource_ids"] = [
                        str(item) for item in override_global_nav.get("resource_ids", []) if isinstance(item, str)
                    ]
                if "selected_pattern" in override_global_nav:
                    merged_global_nav["selected_pattern"] = str(override_global_nav.get("selected_pattern", "") or "")
                if "region_hint" in override_global_nav:
                    merged_global_nav["region_hint"] = _to_enum_value(
                        override_global_nav.get("region_hint"),
                        {"bottom_tabs", "left_rail", "auto"},
                        str(merged_global_nav.get("region_hint", "auto") or "auto"),
                    )
                merged_cfg["global_nav"] = merged_global_nav

            if scenario_override:
                log(
                    f"[CONFIG] scenario override applied scenario='{scenario_id}' "
                    f"max_steps={merged_cfg.get('max_steps')} enabled={bool(merged_cfg.get('enabled', True))}"
                )

        merged_tab_configs.append(merged_cfg)

    return {
        "version": RUNTIME_CONFIG_VERSION,
        "config_path": str(resolved_path),
        "checkpoint_save_every": checkpoint_save_every,
        "tab_configs": merged_tab_configs,
    }
