from __future__ import annotations

import json
from pathlib import Path

from qa_frontend.backend.runtime_config_selection import build_selected_runtime_config
from qa_frontend.backend import batch_runner
from qa_frontend.backend.scenarios import list_scenarios, read_runtime_config
from qa_frontend.backend.run_summary import build_run_summary
from tb_runner.scenario_config import (
    TAB_CONFIGS,
    canonical_full_scenario_ids,
    classify_scenario_selection,
)


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_full_scope_is_registry_based_not_runtime_enabled_based():
    runtime = read_runtime_config()
    runtime_scenarios = runtime["scenarios"]
    enabled_ids = [
        str(scenario_id)
        for scenario_id, config in runtime_scenarios.items()
        if isinstance(config, dict) and config.get("enabled") is True
    ]
    canonical_ids = canonical_full_scenario_ids()
    api_scenarios = list_scenarios()

    assert len(TAB_CONFIGS) == len(canonical_ids) == len(api_scenarios) == 32
    assert len(enabled_ids) == 1
    assert {item["id"] for item in api_scenarios if item["canonical_full"]} == set(canonical_ids)
    assert len([item for item in api_scenarios if item["canonical_full"]]) == len(canonical_ids)


def test_full_runtime_config_selection_enables_canonical_ids_without_mutating_source(tmp_path):
    source_path = ROOT / "config" / "runtime_config.json"
    source_text = source_path.read_text(encoding="utf-8")
    source = json.loads(source_text)
    canonical_ids = canonical_full_scenario_ids()

    selected, steps = build_selected_runtime_config(
        source,
        canonical_ids,
        mode="full",
    )

    enabled_ids = [
        str(scenario_id)
        for scenario_id, config in selected["scenarios"].items()
        if isinstance(config, dict) and config.get("enabled") is True
    ]
    assert set(enabled_ids) == set(canonical_ids)
    assert len(enabled_ids) == len(canonical_ids)
    assert len([step for step in steps if step["selected"]]) == len(canonical_ids)
    assert source_path.read_text(encoding="utf-8") == source_text


def test_partial_selection_is_custom_for_backend_and_summary_provenance(tmp_path):
    canonical_ids = canonical_full_scenario_ids()
    assert classify_scenario_selection(canonical_ids) == "FULL"
    assert classify_scenario_selection(canonical_ids[:1]) == "CUSTOM"
    assert classify_scenario_selection(canonical_ids[:-1]) == "CUSTOM"

    log_path = tmp_path / "20260825_000000_full.log"
    log_path.write_text("", encoding="utf-8")
    summary = build_run_summary(
        status={"state": "finished", "mode": "full", "run_kind": "FULL"},
        log_path=log_path,
        scenario_ids=canonical_ids[:1],
    )

    assert summary["run_kind"] == "CUSTOM"


def test_batch_status_exposes_selection_derived_run_kind():
    canonical_ids = canonical_full_scenario_ids()

    full_manager = batch_runner.BatchRunManager()
    full_manager._mode = "full"
    full_manager._scenario_ids = list(canonical_ids)
    full_manager._run_kind = classify_scenario_selection(full_manager._scenario_ids)
    assert full_manager.get_status()["run_kind"] == "FULL"

    custom_manager = batch_runner.BatchRunManager()
    custom_manager._mode = "full"
    custom_manager._scenario_ids = list(canonical_ids[:1])
    custom_manager._run_kind = classify_scenario_selection(custom_manager._scenario_ids)
    assert custom_manager.get_status()["run_kind"] == "CUSTOM"
