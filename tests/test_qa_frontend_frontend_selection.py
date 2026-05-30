from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_initial_selection_defaults_to_global_nav_not_source_enabled():
    selection_ts = (ROOT / "qa_frontend" / "frontend" / "src" / "selection.ts").read_text(encoding="utf-8")
    app_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    presets_ts = (ROOT / "qa_frontend" / "frontend" / "src" / "presets.ts").read_text(encoding="utf-8")

    assert "DEFAULT_SCENARIO_ID = 'global_nav_main'" in selection_ts
    assert "new Set([DEFAULT_SCENARIO_ID])" in selection_ts
    assert "scenario.enabled" not in selection_ts
    assert "setSelected(initialScenarioSelection(scenarioResponse.scenarios))" in app_tsx
    assert "filter((scenario) => scenario.enabled).map((scenario) => scenario.id)" not in app_tsx
    assert "useState<'warm' | 'clean'>('clean')" in app_tsx
    assert "Recommended. Restarts SmartThings before running." in app_tsx
    assert "Download Log" in app_tsx
    assert "Recent Runs" in app_tsx
    assert "Runtime Dashboard" in app_tsx
    assert "Run blocked: language change required" in app_tsx
    assert "Open Language Settings" in app_tsx
    assert "then run again with Current device language" in app_tsx
    assert "Run blocked: TalkBack disabled" in app_tsx
    assert "Enable TalkBack via ADB" in app_tsx
    assert "scrollIntoView" in app_tsx
    assert "Scenario Progress" in app_tsx
    assert "Event Feed" in app_tsx
    assert "process_status" in app_tsx
    assert "scenario_result_status" in app_tsx
    assert "Scenarios failed" in app_tsx
    assert "Scenarios warning" in app_tsx
    assert "warning_scenarios" in app_tsx
    assert "summary cached" in app_tsx
    assert "Run Details" in app_tsx
    assert "selectedRecentRunId" in app_tsx
    assert "reason={scenarioReasonText(scenario) || 'failed'}" in app_tsx
    assert "Failed ({selectedFailedScenarios.length})" in app_tsx
    assert "Warning ({selectedWarningScenarios.length})" in app_tsx
    assert "Passed ({selectedPassedScenarios.length})" in app_tsx
    assert "Global Nav Smoke" in presets_ts
    assert "Life Smoke" in presets_ts
    assert "Device Smoke" in presets_ts
    assert "Select All Scenarios" in presets_ts
    assert "select every available scenario" in presets_ts
    assert "presetId === 'select_all'" in presets_ts
    assert "new Set(scenarios.map((scenario) => scenario.id))" in presets_ts
    assert "Full Regression Selected" not in presets_ts
    assert "full_regression_selected" not in presets_ts
    assert "recommendedMode" not in presets_ts
