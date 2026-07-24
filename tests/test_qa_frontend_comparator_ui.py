from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from qa_frontend.backend.comparator_ui import ComparatorUiService, _environment_details
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


def test_candidate_source_status_is_artifact_based():
    source = {"source_candidate_id": "candidate_a", "source_run_id": "run_a", "source_batch_id": "batch_a"}
    status = ComparatorUiService._source_status(
        candidate_id="candidate_a", source_run_id="run_a", source_batch_id="batch_a",
        approval_state="CANDIDATE", eligible=True, approved_source=source,
    )
    assert status == ("APPROVED_SOURCE", "APPROVED SOURCE")
    assert ComparatorUiService._source_status(
        candidate_id="candidate_other", source_run_id="run_a", source_batch_id="batch_a",
        approval_state="CANDIDATE", eligible=True, approved_source=source,
    ) == ("ELIGIBLE_CANDIDATE", "ELIGIBLE CANDIDATE")
    assert ComparatorUiService._source_status(
        candidate_id="candidate_a", source_run_id="run_other", source_batch_id="batch_a",
        approval_state="CANDIDATE", eligible=True, approved_source=source,
    ) == ("ELIGIBLE_CANDIDATE", "ELIGIBLE CANDIDATE")
    assert ComparatorUiService._source_status(
        candidate_id="candidate_smoke", source_run_id="run_s", source_batch_id="batch_s",
        approval_state="NOT_ELIGIBLE", eligible=False, approved_source=None,
    ) == ("NOT_ELIGIBLE", "NOT ELIGIBLE")
    assert ComparatorUiService._source_status(
        candidate_id="run_only", source_run_id="run_r", source_batch_id="batch_r",
        approval_state="RUN_ONLY", eligible=None, approved_source=None,
    ) == ("RUN_ONLY", "RUN ONLY")


def test_candidate_catalog_exposes_status_without_restricting_selection():
    client = TestClient(app)
    response = client.get("/api/comparator/candidates")
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert {item["source_status_label"] for item in candidates} >= {"APPROVED SOURCE", "NOT ELIGIBLE"}
    assert all("candidate_id" in item and "source" in item for item in candidates)
    approved = next(item for item in candidates if item["source_status_label"] == "APPROVED SOURCE")
    assert approved["approved_baseline_id"]
    assert any("SMOKE" in item["blocking_reasons"] for item in candidates)
    assert any(item["dirty"] is True and "DIRTY" in item["blocking_reasons"] for item in candidates)


def test_catalog_exposes_canonical_environment_details_additively():
    baseline_response = TestClient(app).get("/api/comparator/baselines")
    candidate_response = TestClient(app).get("/api/comparator/candidates")

    assert baseline_response.status_code == 200
    assert candidate_response.status_code == 200
    baseline = next(item for item in baseline_response.json()["baselines"] if item["device_family"] == "galaxy-z-flip6")
    candidate = next(item for item in candidate_response.json()["candidates"] if item["device_family"] == "galaxy-z-fold8")
    environment_fields = {
        "locale", "app_version", "device_family", "device_model", "form_factor",
        "android_major", "one_ui_major", "talkback_package", "talkback_major", "fingerprint_status",
    }
    assert environment_fields <= baseline.keys()
    assert environment_fields <= candidate.keys()
    assert baseline["device_model"] == "SM-F741N"
    assert str(baseline["android_major"]) == "15"
    assert str(baseline["one_ui_major"]).split(".")[0] == "7"
    assert str(baseline["talkback_major"]).startswith("15")
    assert candidate["device_model"] == "SM-F971B"
    assert str(candidate["android_major"]) == "17"
    assert str(candidate["one_ui_major"]).split(".")[0] == "9"
    assert candidate["talkback_package"] == "com.google.android.marvin.talkback"
    assert str(candidate["talkback_major"]).startswith("17")
    assert baseline["fingerprint_status"] == "COMPLETE"
    assert candidate["fingerprint_status"] == "COMPLETE"


def test_missing_environment_profile_values_are_safe():
    details = _environment_details(environment={}, fingerprint={}, profile={"device": None})

    assert details["device_family"] is None
    assert details["device_model"] is None
    assert details["fingerprint_status"] == "UNKNOWN"


def test_compact_environment_card_contract_is_not_character_broken():
    source = Path("qa_frontend/frontend/src/components/ComparePanel.tsx").read_text(encoding="utf-8")
    styles = Path("qa_frontend/frontend/src/styles.css").read_text(encoding="utf-8")

    assert "environmentCardSummary" in source
    assert "Unknown Android" in source
    card_styles = styles.split(".environmentCardSummary", 1)[1].split(".environmentNotice", 1)[0]
    assert "word-break: break-all" not in card_styles
    assert "overflow-wrap: anywhere" not in card_styles
    assert ".environmentCards { grid-template-columns: 1fr; }" in styles or ".environmentCards {" in styles
