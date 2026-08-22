from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "qa_frontend" / "frontend" / "src"


def test_phase_c_main_flow_elevates_review_required_before_history() -> None:
    app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    assert app.index("<CurrentRunPanel") < app.index("<ReviewRequiredPanel") < app.index("<RecentRunsPanel")
    assert "batchId={selectedBatchId}" in app


def test_review_required_uses_authoritative_projection_and_read_only_decision_surface() -> None:
    panel = (FRONTEND / "components" / "ReviewRequiredPanel.tsx").read_text(encoding="utf-8")
    presentation = (FRONTEND / "reviewPresentation.ts").read_text(encoding="utf-8")
    assert "getReviewProjection" in panel
    assert "getBatchReviewProjection" in panel
    assert "quality_issues_contract" in presentation
    assert "automationDiagnosticCount" in presentation
    assert "검토하기 (읽기 전용)" in panel
    assert "Technical evidence" in panel
    assert "loading=\"lazy\"" in panel


def test_history_primary_rows_are_validator_oriented_and_technical_details_are_collapsed() -> None:
    history = (FRONTEND / "components" / "RecentRunsPanel.tsx").read_text(encoding="utf-8")
    assert "validatorHistoryRow" in history
    assert "historyScopeLabel" in history
    assert "historyExecutionLabel" in history
    assert "formatValidatorDateTime" in history
    assert "formatValidatorDuration" in history
    assert "Technical history details" in history
    assert "role=\"button\"" not in history


def test_phase_c_preserves_current_run_and_backend_review_boundary() -> None:
    current_run = (FRONTEND / "components" / "CurrentRunPanel.tsx").read_text(encoding="utf-8")
    backend = (ROOT / "qa_frontend" / "backend" / "mismatch_viewer.py").read_text(encoding="utf-8")
    assert "projectCurrentRun" in current_run
    assert "Stop Run" in current_run
    assert "classify_quality_signals" in backend
    assert '"quality_issues_contract"' in backend
    assert '"automation_diagnostics"' in backend
