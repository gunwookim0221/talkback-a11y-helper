import pytest

from tb_runner.phase5c_budget_policy import (
    resolve_phase5c_budget_maps,
    resolve_phase5c_budget_pair,
)


@pytest.mark.parametrize("production_steps", [100, 20, 10])
def test_large_or_small_production_budget_keeps_bounded_phase5_slice(production_steps):
    pair = resolve_phase5c_budget_pair("home_main", production_steps)
    assert pair == {
        "production_max_steps": production_steps,
        "controlled_action_budget": 10,
    }


def test_full32_mapping_preserves_food_camera_coverage_and_existing_bounded_overrides():
    ids = ["life_food_plugin", "device_camera_plugin", "device_home_camera_plugin"]
    production, controlled = resolve_phase5c_budget_maps(
        ids,
        {scenario: 100 for scenario in ids},
    )
    assert production == {scenario: 100 for scenario in ids}
    assert controlled == {
        "life_food_plugin": 20,
        "device_camera_plugin": 20,
        "device_home_camera_plugin": 10,
    }


def test_initial_and_continuation_use_the_same_deterministic_budget_mapping():
    fresh_full32 = resolve_phase5c_budget_pair("home_main", 100)
    continuation = resolve_phase5c_budget_pair("home_main", 100)
    assert continuation == fresh_full32


def test_missing_controlled_budget_uses_deterministic_default():
    assert resolve_phase5c_budget_pair("life_music_sync_plugin", 100) == {
        "production_max_steps": 100,
        "controlled_action_budget": 10,
    }


@pytest.mark.parametrize("invalid", [0, 21, 100, True, 1.5])
def test_invalid_configured_controlled_budget_fails_before_runner_entry(invalid):
    with pytest.raises(ValueError, match="controlled action budget.*1..20"):
        resolve_phase5c_budget_pair("home_main", 100, invalid)


def test_configured_budget_for_unknown_scenario_is_rejected():
    with pytest.raises(ValueError, match="unknown scenarios"):
        resolve_phase5c_budget_maps(
            ["home_main"], {"home_main": 100}, {"not_a_scenario": 10}
        )


def test_phase4c_acceptance_keeps_production_step_limit_separate(monkeypatch):
    from tools import phase4c_generalized_monitor as monitor

    monkeypatch.setattr(monitor, "BUDGETS", {"home_main": 10})
    monkeypatch.setattr(monitor, "PRODUCTION_MAX_STEPS", {"home_main": 100})
    assert monitor.production_step_limit("home_main") == 100


def test_planner_loop_guard_separates_production_steps_from_controlled_actions():
    from tools.phase4c_generalized_monitor import planner_loop_unbounded

    rows = [{"planner_executed": index < 9} for index in range(14)]
    assert planner_loop_unbounded(rows, production_max_steps=100, controlled_action_budget=10) is False
    assert planner_loop_unbounded(rows, production_max_steps=13, controlled_action_budget=10) is True
    rows.append({"planner_executed": True})
    assert planner_loop_unbounded(rows, production_max_steps=100, controlled_action_budget=9) is True
