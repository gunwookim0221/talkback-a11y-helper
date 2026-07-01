from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from tb_runner.run_selection import normalize_mode, resolve_effective_max_steps


_V10_SHADOW_FEATURE_FLAGS = (
    "inventory_enabled",
    "quick_identify_enabled",
    "policy_mapping_enabled",
    "shadow_validation_enabled",
)


def _normalize_mode(mode: str) -> str:
    return normalize_mode(mode)


def _resolve_effective_max_steps(scenario_id: str, original_max_steps: Any, mode: str) -> Any:
    return resolve_effective_max_steps(scenario_id, original_max_steps, mode)


def build_selected_runtime_config(
    source_config: dict[str, Any],
    scenario_ids: list[str],
    *,
    mode: str,
    max_steps_overrides: dict[str, int] | None = None,
    shadow_validation: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected = {scenario_id for scenario_id in scenario_ids if scenario_id}
    normalized_mode = _normalize_mode(mode)
    selected_policy = "source_preserved" if normalized_mode == "full" else "smoke_override"
    max_steps_overrides = max_steps_overrides or {}
    next_config = copy.deepcopy(source_config)
    shadow_enabled = normalized_mode == "full" and shadow_validation is True
    v10 = next_config.get("v10")
    if not isinstance(v10, dict):
        v10 = {}
        next_config["v10"] = v10
    feature_flags = v10.get("feature_flags")
    if not isinstance(feature_flags, dict):
        feature_flags = {}
        v10["feature_flags"] = feature_flags
    for flag_name in _V10_SHADOW_FEATURE_FLAGS:
        feature_flags[flag_name] = shadow_enabled

    scenarios = next_config.get("scenarios")
    if not isinstance(scenarios, dict):
        scenarios = {}
        next_config["scenarios"] = scenarios

    scenario_steps: list[dict[str, Any]] = []
    for scenario_id, raw_cfg in list(scenarios.items()):
        cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
        if cfg is not raw_cfg:
            scenarios[scenario_id] = cfg
        scenario_key = str(scenario_id)
        is_selected = scenario_key in selected
        original_max_steps = cfg.get("max_steps")
        cfg["enabled"] = is_selected
        effective_max_steps = original_max_steps
        policy = "source_preserved"
        if is_selected:
            if scenario_key in max_steps_overrides:
                effective_max_steps = max_steps_overrides[scenario_key]
                policy = "explicit_override"
            else:
                effective_max_steps = _resolve_effective_max_steps(scenario_key, original_max_steps, normalized_mode)
                policy = selected_policy
            cfg["max_steps"] = effective_max_steps
        scenario_steps.append(
            {
                "scenario": scenario_key,
                "selected": is_selected,
                "original_max_steps": original_max_steps,
                "effective_max_steps": effective_max_steps,
                "policy": policy,
            }
        )

    return next_config, scenario_steps


def write_selected_runtime_config(
    *,
    source_path: Path,
    output_path: Path,
    scenario_ids: list[str],
    mode: str,
    max_steps_overrides: dict[str, int] | None = None,
    shadow_validation: bool = False,
) -> dict[str, object]:
    source_text = source_path.read_text(encoding="utf-8")
    source_config = json.loads(source_text)
    if not isinstance(source_config, dict):
        raise ValueError("runtime_config root must be an object")

    selected_config, scenario_steps = build_selected_runtime_config(
        source_config,
        scenario_ids,
        mode=mode,
        max_steps_overrides=max_steps_overrides,
        shadow_validation=shadow_validation,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(selected_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    scenarios = selected_config.get("scenarios", {})
    enabled_ids = [
        str(scenario_id)
        for scenario_id, cfg in scenarios.items()
        if isinstance(cfg, dict) and cfg.get("enabled") is True
    ] if isinstance(scenarios, dict) else []
    return {
        "path": str(output_path),
        "enabled_ids": enabled_ids,
        "max_steps_policy": "source_preserved" if _normalize_mode(mode) == "full" else "smoke_override",
        "scenario_steps": scenario_steps,
        "shadow_validation_enabled": (
            _normalize_mode(mode) == "full" and shadow_validation is True
        ),
        "source_unchanged": source_path.read_text(encoding="utf-8") == source_text,
    }
