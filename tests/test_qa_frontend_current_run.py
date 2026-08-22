from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "qa_frontend" / "frontend" / "src"


def test_current_run_projection_uses_existing_runtime_source_and_keeps_details_available():
    app_tsx = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    current_run_tsx = (FRONTEND / "components" / "CurrentRunPanel.tsx").read_text(encoding="utf-8")
    run_panel_tsx = (FRONTEND / "components" / "RunPanel.tsx").read_text(encoding="utf-8")
    polling_ts = (FRONTEND / "hooks" / "useRunPolling.ts").read_text(encoding="utf-8")

    assert "<CurrentRunPanel" in app_tsx
    assert "batchStatus={batchStatus}" in app_tsx
    assert "<summary>Runtime Preflight details</summary>" in app_tsx
    assert "<summary>Run diagnostics</summary>" in app_tsx
    assert "projectCurrentRun" in current_run_tsx
    assert "Stop Run" in current_run_tsx
    assert "Preparing next scenario…" in current_run_tsx
    assert "Run details" in current_run_tsx
    assert "getBatchStatus" in polling_ts
    assert "shouldUseBatch(batchStatusRef, snapshot.status)" in polling_ts
    assert "batchStatusRef.state === 'stopped' ? 'stopped'" in polling_ts
    assert "setInterval" not in run_panel_tsx
    assert "getBatchStatus" not in run_panel_tsx


def test_current_run_preserves_phase_a_setup_safety_contracts():
    app_tsx = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    run_panel_tsx = (FRONTEND / "components" / "RunPanel.tsx").read_text(encoding="utf-8")
    current_run_ts = (FRONTEND / "currentRun.ts").read_text(encoding="utf-8")

    assert "initialScenarioSelection(response.scenarios)" in app_tsx
    assert "Select at least one ready device" in (FRONTEND / "runProfiles.ts").read_text(encoding="utf-8")
    assert "launchInFlightRef.current" in run_panel_tsx
    assert "launchAccepted = res.state === 'running'" in run_panel_tsx
    assert "batchStatus?.state === 'running'" in run_panel_tsx
    assert "scenarioDisplayName" in current_run_ts
