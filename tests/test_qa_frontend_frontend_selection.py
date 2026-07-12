from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_initial_selection_defaults_to_global_nav_not_source_enabled():
    selection_ts = (ROOT / "qa_frontend" / "frontend" / "src" / "selection.ts").read_text(encoding="utf-8")
    app_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    run_panel_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "components" / "RunPanel.tsx").read_text(encoding="utf-8")
    presets_ts = (ROOT / "qa_frontend" / "frontend" / "src" / "presets.ts").read_text(encoding="utf-8")
    api_ts = (ROOT / "qa_frontend" / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert "DEFAULT_SCENARIO_ID = 'global_nav_main'" in selection_ts
    assert "new Set([DEFAULT_SCENARIO_ID])" in selection_ts
    assert "scenario.enabled" not in selection_ts
    assert "setSelected(initialScenarioSelection(response.scenarios))" in app_tsx
    assert "setEnableCoverageProbe(plannedMode === 'full')" in app_tsx
    assert "filter((scenario) => scenario.enabled).map((scenario) => scenario.id)" not in app_tsx
    assert "useState<'warm' | 'clean'>('clean')" in app_tsx
    assert "Run blocked: language change required" in app_tsx
    assert "Open Language Settings" in app_tsx
    assert "then run again with Current device language" in app_tsx
    assert "Run blocked: TalkBack disabled" in app_tsx
    assert "Enable TalkBack via ADB" in app_tsx
    assert "scrollIntoView" in app_tsx
    assert "selectedRecentRunId" in app_tsx
    assert "All Plugins" in presets_ts
    assert "select device and life plugin scenarios only" in presets_ts
    assert "All Scenarios" in presets_ts
    assert "select navigation, main, and plugin scenarios" in presets_ts
    assert "select every available scenario" not in presets_ts
    assert "presetId === 'all_plugins'" in presets_ts
    assert "id.startsWith('device_') || (id.startsWith('life_') && id.endsWith('_plugin'))" in presets_ts
    assert "presetId === 'select_all'" in presets_ts
    assert "new Set(scenarios.map((scenario) => scenario.id))" in presets_ts
    assert "Selected Full does not mean all plugins" in app_tsx
    assert "Use All Plugins to run every plugin scenario" in app_tsx
    assert "All Scenarios to" in app_tsx
    assert "Selected Smoke" in run_panel_tsx
    assert "selected scenarios with reduced max_steps" in run_panel_tsx
    assert "Selected Full" in run_panel_tsx
    assert "selected scenarios with source max_steps" in run_panel_tsx
    assert "Runtime Coverage Probe" in run_panel_tsx
    assert "Recommended for Full runs." in run_panel_tsx
    assert "V8 Runtime Probe" not in run_panel_tsx
    assert "Experimental." not in run_panel_tsx
    assert "Full Regression Selected" not in presets_ts
    assert "full_regression_selected" not in presets_ts
    assert "recommendedMode" not in presets_ts
    assert "stopBatch: () => request<BatchStatus>('/api/batch/stop', { method: 'POST' })" in api_ts
    assert "if (batchStatus?.state === 'running')" in app_tsx
    assert "await api.stopBatch()" in app_tsx
    assert "await api.stopRun()" in app_tsx


def test_traversal_identity_v2_ui_is_default_off_and_enforces_dependencies():
    app_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    run_panel_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "components" / "RunPanel.tsx").read_text(encoding="utf-8")
    recent_runs_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "components" / "RecentRunsPanel.tsx").read_text(encoding="utf-8")
    api_ts = (ROOT / "qa_frontend" / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert "useState(false)" in app_tsx
    assert "const [traversalIdentityV2, setTraversalIdentityV2] = useState(false)" in app_tsx
    assert "setIdentityShadowV2(true); setEvidenceLedger(true);" in run_panel_tsx
    assert "setIdentityShadowV2(false); setTraversalIdentityV2(false);" in run_panel_tsx
    assert "else setTraversalIdentityV2(false)" in run_panel_tsx
    assert "Traversal Identity V2 (Experimental)" in run_panel_tsx
    assert "traversal_identity_v2: traversalIdentityV2" in run_panel_tsx
    assert "TraversalIdentityV2Card" in recent_runs_tsx
    assert "traversal_identity_v2: boolean" in api_ts
