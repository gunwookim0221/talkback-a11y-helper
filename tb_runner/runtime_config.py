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

RUNTIME_CONFIG_VERSION = "1.8.0"
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
    "recovery": {
        "enabled": True,
        "target_type": "bottom_tab",
        "target": "(?i).*home.*",
        "resource_id": "com.samsung.android.oneconnect:id/menu_favorites",
        "max_back_count": 5,
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

_ALLOWED_SCREEN_CONTEXT_MODE = {"bottom_tab", "new_screen"}
_ALLOWED_STABILIZATION_MODE = {"tab_context", "anchor_only", "anchor_then_context"}
_ALLOWED_SCENARIO_TYPE = {"content", "global_nav"}
_ALLOWED_REGION_HINT = {"bottom_tabs", "left_rail", "auto"}


def _normalize_global_nav(raw_global_nav: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    base = dict(fallback or {})
    if not isinstance(raw_global_nav, dict):
        return base

    if isinstance(raw_global_nav.get("labels"), list):
        base["labels"] = [str(item) for item in raw_global_nav.get("labels", []) if isinstance(item, str)]
    if isinstance(raw_global_nav.get("resource_ids"), list):
        base["resource_ids"] = [str(item) for item in raw_global_nav.get("resource_ids", []) if isinstance(item, str)]
    if "selected_pattern" in raw_global_nav:
        base["selected_pattern"] = str(raw_global_nav.get("selected_pattern", "") or "")
    if "region_hint" in raw_global_nav:
        base["region_hint"] = _to_enum_value(
            raw_global_nav.get("region_hint"),
            _ALLOWED_REGION_HINT,
            str(base.get("region_hint", "auto") or "auto"),
        )
    return base


def _merge_stop_policy(base_policy: dict[str, Any], override_policy: Any) -> dict[str, Any]:
    merged_policy = dict(base_policy or {})
    if not isinstance(override_policy, dict):
        return merged_policy
    merged_policy["stop_on_global_nav_entry"] = bool(
        override_policy.get("stop_on_global_nav_entry", merged_policy.get("stop_on_global_nav_entry", False))
    )
    merged_policy["stop_on_global_nav_exit"] = bool(
        override_policy.get("stop_on_global_nav_exit", merged_policy.get("stop_on_global_nav_exit", False))
    )
    merged_policy["stop_on_terminal"] = bool(
        override_policy.get("stop_on_terminal", merged_policy.get("stop_on_terminal", True))
    )
    merged_policy["stop_on_repeat_no_progress"] = bool(
        override_policy.get("stop_on_repeat_no_progress", merged_policy.get("stop_on_repeat_no_progress", True))
    )
    return merged_policy


def _apply_typed_override(merged_cfg: dict[str, Any], override_cfg: dict[str, Any], runtime_defaults: dict[str, Any]) -> None:
    if not isinstance(override_cfg, dict):
        return

    if "enabled" in override_cfg and isinstance(override_cfg.get("enabled"), bool):
        merged_cfg["enabled"] = override_cfg.get("enabled")
    if "max_steps" in override_cfg:
        merged_cfg["max_steps"] = _to_positive_int(
            override_cfg.get("max_steps"),
            int(merged_cfg.get("max_steps", 1) or 1),
        )

    for key in _OVERRIDE_KEYS:
        if key not in override_cfg:
            continue
        base_value = merged_cfg.get(key, runtime_defaults[key])
        if isinstance(base_value, int):
            merged_cfg[key] = _to_positive_int(override_cfg.get(key), base_value)
        elif isinstance(base_value, str):
            allowed_values = _ALLOWED_SCREEN_CONTEXT_MODE if key == "screen_context_mode" else _ALLOWED_STABILIZATION_MODE
            merged_cfg[key] = _to_enum_value(override_cfg.get(key), allowed_values, base_value)
        else:
            merged_cfg[key] = _to_positive_float(override_cfg.get(key), float(base_value))

    if "scenario_type" in override_cfg:
        merged_cfg["scenario_type"] = _to_enum_value(
            override_cfg.get("scenario_type"),
            _ALLOWED_SCENARIO_TYPE,
            str(merged_cfg.get("scenario_type", "content") or "content"),
        )

    if "stop_policy" in override_cfg:
        merged_cfg["stop_policy"] = _merge_stop_policy(
            dict(merged_cfg.get("stop_policy", {}) or {}),
            override_cfg.get("stop_policy"),
        )

    if "global_nav" in override_cfg:
        merged_cfg["global_nav"] = _normalize_global_nav(
            override_cfg.get("global_nav"),
            dict(merged_cfg.get("global_nav", runtime_defaults["global_nav"]) or runtime_defaults["global_nav"]),
        )

    if "recovery" in override_cfg:
        merged_cfg["recovery"] = _normalize_recovery_config(
            override_cfg.get("recovery"),
            dict(merged_cfg.get("recovery", runtime_defaults["recovery"]) or runtime_defaults["recovery"]),
        )

    if "anchor" in override_cfg and isinstance(override_cfg.get("anchor"), dict):
        merged_cfg["anchor"] = copy.deepcopy(override_cfg.get("anchor"))
    if "anchor_name" in override_cfg:
        merged_cfg["anchor_name"] = str(override_cfg.get("anchor_name", "") or "")
    if "anchor_type" in override_cfg:
        merged_cfg["anchor_type"] = str(override_cfg.get("anchor_type", "") or "")
    if "pre_navigation" in override_cfg and isinstance(override_cfg.get("pre_navigation"), list):
        merged_cfg["pre_navigation"] = copy.deepcopy(override_cfg.get("pre_navigation"))


def _normalize_recovery_config(raw_recovery: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    base = dict(fallback or {})
    if not isinstance(raw_recovery, dict):
        return base

    if "enabled" in raw_recovery:
        base["enabled"] = bool(raw_recovery.get("enabled"))
    if "target_type" in raw_recovery:
        base["target_type"] = _to_enum_value(
            raw_recovery.get("target_type"),
            {"bottom_tab", "anchor", "resource_id"},
            str(base.get("target_type", "bottom_tab") or "bottom_tab"),
        )
    if "target" in raw_recovery:
        base["target"] = str(raw_recovery.get("target", "") or "")
    if "resource_id" in raw_recovery:
        base["resource_id"] = str(raw_recovery.get("resource_id", "") or "")
    if "max_back_count" in raw_recovery:
        base["max_back_count"] = _to_positive_int(
            raw_recovery.get("max_back_count"),
            int(base.get("max_back_count", 5) or 5),
        )
    return base


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
        "screen_context_mode": _to_enum_value(raw_defaults.get("screen_context_mode"), _ALLOWED_SCREEN_CONTEXT_MODE, _DEFAULTS["screen_context_mode"]),
        "stabilization_mode": _to_enum_value(raw_defaults.get("stabilization_mode"), _ALLOWED_STABILIZATION_MODE, _DEFAULTS["stabilization_mode"]),
        "scenario_type": _to_enum_value(raw_defaults.get("scenario_type"), _ALLOWED_SCENARIO_TYPE, _DEFAULTS["scenario_type"]),
        "stop_policy": {
            "stop_on_global_nav_entry": bool(raw_stop_policy.get("stop_on_global_nav_entry", False)),
            "stop_on_global_nav_exit": bool(raw_stop_policy.get("stop_on_global_nav_exit", False)),
            "stop_on_terminal": bool(raw_stop_policy.get("stop_on_terminal", True)),
            "stop_on_repeat_no_progress": bool(raw_stop_policy.get("stop_on_repeat_no_progress", True)),
        },
        "global_nav": _normalize_global_nav(raw_global_nav, _DEFAULTS["global_nav"]),
        "recovery": _normalize_recovery_config(
            raw_defaults.get("recovery"),
            _DEFAULTS["recovery"],
        ),
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
    raw_shared_navigation = raw_config.get("shared_navigation", {})
    if not isinstance(raw_shared_navigation, dict):
        raw_shared_navigation = {}
    raw_shared_anchors = raw_config.get("shared_anchors", {})
    if not isinstance(raw_shared_anchors, dict):
        raw_shared_anchors = {}
    raw_shared_pre_navigation = raw_config.get("shared_pre_navigation", {})
    if not isinstance(raw_shared_pre_navigation, dict):
        raw_shared_pre_navigation = {}
    raw_scenario_groups = raw_config.get("scenario_groups", {})
    if not isinstance(raw_scenario_groups, dict):
        raw_scenario_groups = {}

    runtime_defaults = _build_runtime_defaults(raw_defaults)

    shared_navigation: dict[str, dict[str, Any]] = {}
    for nav_name, nav_cfg in raw_shared_navigation.items():
        if isinstance(nav_name, str) and isinstance(nav_cfg, dict):
            shared_navigation[nav_name] = _normalize_global_nav(nav_cfg, runtime_defaults["global_nav"])

    if not shared_navigation and isinstance(raw_defaults.get("global_nav"), dict):
        shared_navigation["__legacy_defaults_global_nav__"] = _normalize_global_nav(
            raw_defaults.get("global_nav"),
            runtime_defaults["global_nav"],
        )

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
        if not isinstance(scenario_override, dict):
            scenario_override = {}

        group_name = str(scenario_override.get("group", "") or "")
        group_cfg = raw_scenario_groups.get(group_name, {}) if group_name else {}
        if not isinstance(group_cfg, dict):
            group_cfg = {}
        if group_cfg:
            _apply_typed_override(merged_cfg, group_cfg, runtime_defaults)

        applied_shared_navigation = ""
        use_shared_navigation = scenario_override.get("use_shared_navigation")
        if not isinstance(use_shared_navigation, str) or not use_shared_navigation.strip():
            use_shared_navigation = group_cfg.get("use_shared_navigation")
        if isinstance(use_shared_navigation, str) and use_shared_navigation in shared_navigation:
            _apply_typed_override(
                merged_cfg,
                {"global_nav": shared_navigation.get(use_shared_navigation)},
                runtime_defaults,
            )
            applied_shared_navigation = use_shared_navigation

        applied_anchor_ref = ""
        anchor_ref = scenario_override.get("anchor_ref")
        if not isinstance(anchor_ref, str) or not anchor_ref.strip():
            anchor_ref = group_cfg.get("anchor_ref")
        if isinstance(anchor_ref, str):
            anchor_cfg = raw_shared_anchors.get(anchor_ref, {})
            if isinstance(anchor_cfg, dict):
                if isinstance(anchor_cfg.get("anchor"), dict):
                    _apply_typed_override(merged_cfg, {"anchor": anchor_cfg.get("anchor")}, runtime_defaults)
                elif anchor_cfg:
                    _apply_typed_override(merged_cfg, {"anchor": anchor_cfg}, runtime_defaults)
                _apply_typed_override(merged_cfg, anchor_cfg, runtime_defaults)
                applied_anchor_ref = anchor_ref

        applied_pre_navigation_ref = ""
        pre_navigation_ref = scenario_override.get("pre_navigation_ref")
        if not isinstance(pre_navigation_ref, str) or not pre_navigation_ref.strip():
            pre_navigation_ref = group_cfg.get("pre_navigation_ref")
        if isinstance(pre_navigation_ref, str):
            pre_navigation_cfg = raw_shared_pre_navigation.get(pre_navigation_ref)
            if isinstance(pre_navigation_cfg, list):
                _apply_typed_override(merged_cfg, {"pre_navigation": pre_navigation_cfg}, runtime_defaults)
                applied_pre_navigation_ref = pre_navigation_ref

        _apply_typed_override(merged_cfg, scenario_override, runtime_defaults)

        if scenario_override or group_cfg:
            log(
                f"[CONFIG] scenario resolved scenario='{scenario_id}' group='{group_name or '-'}' "
                f"max_steps={merged_cfg.get('max_steps')} enabled={bool(merged_cfg.get('enabled', True))}"
            )
            if applied_shared_navigation:
                log(f"[CONFIG] applied shared_navigation='{applied_shared_navigation}'")
            if applied_anchor_ref:
                log(f"[CONFIG] applied anchor_ref='{applied_anchor_ref}'")
            if applied_pre_navigation_ref:
                log(f"[CONFIG] applied pre_navigation_ref='{applied_pre_navigation_ref}'")

        merged_tab_configs.append(merged_cfg)

    return {
        "version": RUNTIME_CONFIG_VERSION,
        "config_path": str(resolved_path),
        "checkpoint_save_every": checkpoint_save_every,
        "tab_configs": merged_tab_configs,
    }
