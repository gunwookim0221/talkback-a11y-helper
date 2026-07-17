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
    assert "const DEFAULT_RUN_PROFILE = RUN_PROFILES['full-validation']" in app_tsx
    assert "useState<'smoke' | 'full'>(DEFAULT_RUN_PROFILE.plannedMode)" in app_tsx
    assert "useState(DEFAULT_RUN_PROFILE.enableCoverageProbe)" in app_tsx
    assert "useState(DEFAULT_RUN_PROFILE.traversalProfiler)" in app_tsx
    assert "filter((scenario) => scenario.enabled).map((scenario) => scenario.id)" not in app_tsx
    assert "useState<'warm' | 'clean'>(DEFAULT_RUN_PROFILE.launchMode)" in app_tsx
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
    assert "Execution Options" in run_panel_tsx
    assert "Runtime Coverage Probe" in run_panel_tsx
    assert "Advanced Diagnostics" in run_panel_tsx
    assert "Collect additional coverage diagnostics after traversal." in run_panel_tsx
    assert "Collect detailed traversal evidence." in run_panel_tsx
    assert "Runtime Profiler" in run_panel_tsx
    assert "Collect runtime metrics and generate profiler artifacts. Does not change traversal behavior." in run_panel_tsx
    assert "Identity Shadow V2 (Read-only)" in run_panel_tsx
    assert "Legacy Shadow Validation (Experimental)" in run_panel_tsx
    assert "VITE_SHOW_LEGACY_SHADOW_VALIDATION" in run_panel_tsx
    assert "planned for removal" in run_panel_tsx
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


def test_traversal_identity_v2_ui_is_default_on_and_enforces_dependencies():
    app_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    run_panel_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "components" / "RunPanel.tsx").read_text(encoding="utf-8")
    recent_runs_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "components" / "RecentRunsPanel.tsx").read_text(encoding="utf-8")
    api_ts = (ROOT / "qa_frontend" / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert "useState(DEFAULT_RUN_PROFILE.traversalIdentityV2)" in app_tsx
    assert "setIdentityShadowV2(true); setEvidenceLedger(true);" in run_panel_tsx
    assert "setIdentityShadowV2(false); setTraversalIdentityV2(false);" in run_panel_tsx
    assert "else setTraversalIdentityV2(false)" in run_panel_tsx
    assert "Traversal Engine" in run_panel_tsx
    assert "Uses the production traversal engine. Turn off to run the legacy compatibility traversal." in run_panel_tsx
    assert "V2 is the production default. Turn it off to run Legacy Compatibility traversal." in run_panel_tsx
    assert "Identity Shadow V2 (Read-only)" in run_panel_tsx
    assert "Read-only comparison. Requires Evidence Ledger" in run_panel_tsx
    assert "Legacy Shadow Validation (Experimental)" in run_panel_tsx
    assert "planned for removal" in run_panel_tsx
    assert "Traversal Identity V2 (Experimental)" not in run_panel_tsx
    assert "traversal_identity_v2: traversalIdentityV2" in run_panel_tsx
    assert "traversal_profiler: traversalProfiler" in run_panel_tsx
    assert "TraversalIdentityV2Card" in recent_runs_tsx
    assert "traversal_identity_v2: boolean" in api_ts
    assert "traversal_profiler?: boolean" in api_ts


def test_run_profiles_readiness_smoke_confirmation_and_locale_are_wired():
    app_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    run_panel_tsx = (ROOT / "qa_frontend" / "frontend" / "src" / "components" / "RunPanel.tsx").read_text(encoding="utf-8")
    profiles_ts = (ROOT / "qa_frontend" / "frontend" / "src" / "runProfiles.ts").read_text(encoding="utf-8")

    assert "useState<RunProfileId>('full-validation')" in run_panel_tsx
    assert "Full Validation" in run_panel_tsx
    assert "Quick Smoke" in run_panel_tsx
    assert "Custom / Debug" in run_panel_tsx
    assert "getValidationReadiness" in run_panel_tsx
    assert "'Mode is Smoke'" in profiles_ts
    assert "'Runtime Profiler disabled'" in profiles_ts
    assert "'Coverage disabled'" in profiles_ts
    assert "'Identity disabled'" in profiles_ts
    assert "Smoke Run은 빠른 확인을 위한 실행이며" in run_panel_tsx
    assert "정식 검증 결과로 사용되지 않습니다." in run_panel_tsx
    assert "Run Smoke" in run_panel_tsx
    assert "currentLanguageLabel(effectiveLocale)" in run_panel_tsx
    assert "status?.state === 'running' || batchStatus?.state === 'running'" in app_tsx
    assert "disabled={controlsLocked}" in run_panel_tsx
