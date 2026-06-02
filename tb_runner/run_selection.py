from __future__ import annotations

import copy
from typing import Any, Iterable


SMOKE_EXACT_STEP_OVERRIDES: dict[str, int] = {
    "global_nav_main": 6,
    "home_main": 6,
    "devices_main": 6,
    "life_main": 6,
    "routines_main": 6,
    "menu_main": 6,
    "settings_entry_example": 6,
}
SMOKE_PREFIX_STEP_OVERRIDES: tuple[tuple[str, int], ...] = (
    ("life_", 8),
    ("device_", 8),
)
SMOKE_FALLBACK_MAX_STEPS = 8


def normalize_mode(mode: str) -> str:
    return "full" if str(mode).lower() == "full" else "smoke"


def resolve_effective_max_steps(scenario_id: str, original_max_steps: Any, mode: str) -> Any:
    if normalize_mode(mode) == "full":
        return original_max_steps
    if scenario_id in SMOKE_EXACT_STEP_OVERRIDES:
        return SMOKE_EXACT_STEP_OVERRIDES[scenario_id]
    for prefix, steps in SMOKE_PREFIX_STEP_OVERRIDES:
        if scenario_id.startswith(prefix):
            return steps
    return SMOKE_FALLBACK_MAX_STEPS


def apply_run_selection(
    tab_configs: Iterable[dict[str, Any]],
    scenario_ids: Iterable[str],
    *,
    mode: str,
) -> list[dict[str, Any]]:
    selected = {scenario_id for scenario_id in scenario_ids if scenario_id}
    configs = copy.deepcopy(list(tab_configs))
    if not selected:
        return configs

    for cfg in configs:
        scenario_id = str(cfg.get("scenario_id", "") or "")
        cfg["enabled"] = scenario_id in selected
        if cfg["enabled"]:
            cfg["max_steps"] = resolve_effective_max_steps(scenario_id, cfg.get("max_steps"), mode)
    return configs
