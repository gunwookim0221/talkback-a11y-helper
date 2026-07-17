from __future__ import annotations

from fastapi.testclient import TestClient

from qa_frontend.backend.comparator_ui import ComparatorUiService
from qa_frontend.backend.main import app


def test_comparator_catalog_and_reports_are_read_only(tmp_path, monkeypatch):
    """The UI API exposes catalogues and keeps reports in process memory only."""
    service = ComparatorUiService(root_dir=tmp_path, run_log_dir=tmp_path / "runs")
    monkeypatch.setattr("qa_frontend.backend.main.comparator_ui", service)
    client = TestClient(app)

    response = client.get("/api/comparator/baselines")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "BASELINE_REPOSITORY_UNAVAILABLE"

    response = client.get("/api/comparator/candidates")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NO_CANDIDATES"
    assert list(tmp_path.iterdir()) == []


def test_comparator_result_routes_expose_session_report(monkeypatch):
    service = ComparatorUiService()
    entry = {
        "comparison_id": "cmp_ui_test", "baseline_id": "baseline_a", "candidate_id": "candidate_a",
        "compared_at": "2026-07-17T00:00:00+00:00", "verdict": {"overall": "PASS"},
        "result": {"comparison_id": "cmp_ui_test", "verdict": {"overall": "PASS"}},
        "markdown": "# Comparison\n", "canonical_json": "{\"comparison_id\":\"cmp_ui_test\"}",
    }
    service._reports["cmp_ui_test"] = entry
    monkeypatch.setattr("qa_frontend.backend.main.comparator_ui", service)
    client = TestClient(app)

    assert client.get("/api/comparator/history").json()["comparisons"][0]["comparison_id"] == "cmp_ui_test"
    assert client.get("/api/comparator/results/cmp_ui_test").json()["result"]["verdict"]["overall"] == "PASS"
    assert client.get("/api/comparator/results/cmp_ui_test/markdown").text == "# Comparison\n"
    download = client.get("/api/comparator/results/cmp_ui_test/report.json")
    assert download.headers["content-disposition"] == 'attachment; filename="cmp_ui_test.json"'
    assert download.text == '{"comparison_id":"cmp_ui_test"}'
