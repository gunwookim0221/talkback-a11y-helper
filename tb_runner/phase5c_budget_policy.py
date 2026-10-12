"""Separate Full32 production coverage limits from Phase 5 action limits."""
from __future__ import annotations


MAX_CONTROLLED_ACTION_BUDGET = 20
DEFAULT_CONTROLLED_ACTION_BUDGET = 10


def resolve_phase5c_budget_pair(
    scenario: str,
    production_max_steps: int,
    configured_controlled_action_budget: int | None = None,
) -> dict[str, int]:
    """Keep source coverage intact and resolve a bounded Phase 5 action slice.

    The only non-default values are the existing Phase 4C/5B policy values for
    Food and the device Camera scenario. Other Full32 scenarios use the same
    established ten-action default.
    """
    if not isinstance(scenario, str) or not scenario:
        raise ValueError("scenario id must be a non-empty string")
    if type(production_max_steps) is not int or production_max_steps < 1:
        raise ValueError("production max_steps must be a positive integer")

    if configured_controlled_action_budget is None:
        from tb_runner.phase4c_traversal import BUDGETS as EXISTING_BOUNDED_BUDGETS

        controlled = EXISTING_BOUNDED_BUDGETS.get(scenario, DEFAULT_CONTROLLED_ACTION_BUDGET)
    else:
        controlled = configured_controlled_action_budget
    if type(controlled) is not int or not 1 <= controlled <= MAX_CONTROLLED_ACTION_BUDGET:
        raise ValueError(
            f"Phase 5 controlled action budget for {scenario} must be 1..{MAX_CONTROLLED_ACTION_BUDGET}"
        )

    return {
        "production_max_steps": production_max_steps,
        "controlled_action_budget": controlled,
    }


def resolve_phase5c_budget_maps(
    scenario_ids: tuple[str, ...] | list[str],
    production_max_steps: dict[str, int],
    configured_controlled_action_budgets: dict[str, int] | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    """Return parallel production and bounded-action maps for the same IDs."""
    if configured_controlled_action_budgets is None:
        configured = {}
    elif isinstance(configured_controlled_action_budgets, dict):
        configured = configured_controlled_action_budgets
    else:
        raise ValueError("configured controlled action budgets must be an object")
    production: dict[str, int] = {}
    controlled: dict[str, int] = {}
    for scenario in scenario_ids:
        if scenario not in production_max_steps:
            raise ValueError(f"missing production max_steps for {scenario}")
        pair = resolve_phase5c_budget_pair(
            scenario,
            production_max_steps[scenario],
            configured.get(scenario),
        )
        production[scenario] = pair["production_max_steps"]
        controlled[scenario] = pair["controlled_action_budget"]
    unknown = set(configured) - set(scenario_ids)
    if unknown:
        raise ValueError(f"controlled action budgets contain unknown scenarios: {sorted(unknown)}")
    return production, controlled
