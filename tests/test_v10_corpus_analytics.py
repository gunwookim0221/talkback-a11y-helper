from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from qa_frontend.backend import main
from qa_frontend.backend.v10_corpus_analytics import (
    load_corpus_dashboard,
    open_corpus_target,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _corpus(tmp_path: Path) -> Path:
    corpus_dir = tmp_path / "corpus"
    _write_json(
        corpus_dir / "index.json",
        {"entry_count": 1, "updated_at": "2026-07-06T12:00:00Z"},
    )
    _write_json(
        corpus_dir / "summaries" / "family_summary.json",
        {
            "families": [
                {
                    "family": "Door Lock",
                    "total_runs": 1,
                    "total_observations": 4,
                    "match_count": 2,
                    "unknown_count": 2,
                    "mismatch_count": 0,
                    "failed_count": 0,
                    "readiness_distribution": {"HOLD": 1},
                    "unique_device_labels": ["Door Lock", "Test lock"],
                    "unique_device_label_count": 2,
                    "unique_device_models": ["MODEL-1"],
                    "unique_device_model_count": 1,
                    "unique_device_serial_count": 1,
                    "unique_locales": ["ko-KR"],
                    "unique_locale_count": 1,
                    "unique_app_versions": ["1.0"],
                    "unique_app_version_count": 1,
                    "last_seen_at": "2026-07-06T11:59:00Z",
                    "candidate_for_v11_pilot": False,
                },
                {
                    "family": "Unknown",
                    "total_runs": 1,
                    "total_observations": 1,
                    "unknown_count": 1,
                    "readiness_distribution": {"UNKNOWN_ONLY": 1},
                    "unique_device_labels": ["Unknown device"],
                    "unique_device_models": ["MODEL-1"],
                    "unique_device_serial_count": 1,
                    "unique_locales": ["ko-KR"],
                    "unique_app_versions": ["1.0"],
                    "last_seen_at": "2026-07-06T11:59:00Z",
                    "candidate_for_v11_pilot": True,
                },
            ]
        },
    )
    _write_json(
        corpus_dir / "summaries" / "readiness_summary.json",
        {
            "updated_at": "2026-07-06T12:01:00Z",
            "overall_readiness_distribution": {"HOLD": 1},
            "v11_pilot_candidate_families": ["Unknown"],
            "controlled_routing_enabled": False,
        },
    )
    return corpus_dir


def test_dashboard_returns_no_data_when_corpus_is_missing(tmp_path):
    result = load_corpus_dashboard(tmp_path / "missing")

    assert result["available"] is False
    assert result["entry_count"] == 0
    assert result["families"] == []


def test_dashboard_parses_family_and_readiness_summaries(tmp_path):
    result = load_corpus_dashboard(_corpus(tmp_path))

    assert result["available"] is True
    assert result["entry_count"] == 1
    assert result["last_updated"] == "2026-07-06T12:01:00Z"
    assert result["overall_readiness"] == "HOLD"
    assert result["totals"]["MATCH"] == 2
    assert result["totals"]["UNKNOWN"] == 3
    assert result["families"][0]["readiness"] == "HOLD"
    assert result["families"][0]["unique_locale_count"] == 1
    assert result["family_readiness_counts"] == {
        "READY": 0,
        "HOLD": 1,
        "BLOCKED": 0,
        "INSUFFICIENT_DATA": 0,
        "UNKNOWN_ONLY": 1,
    }
    assert result["candidate_for_v11_pilot"] == ["Unknown"]
    assert result["unknown_only_families"] == ["Unknown"]
    assert result["controlled_routing_enabled"] is False


def test_summary_endpoint_uses_dashboard_reader(monkeypatch):
    payload = {"available": False, "entry_count": 0}
    monkeypatch.setattr(main, "load_corpus_dashboard", lambda: payload)

    response = TestClient(main.app).get("/api/v10/corpus/summary")

    assert response.status_code == 200
    assert response.json() == payload


def test_open_corpus_targets_are_fixed(tmp_path):
    corpus_dir = _corpus(tmp_path)
    opened = []

    path = open_corpus_target(
        "family-summary", corpus_dir=corpus_dir, opener=opened.append
    )

    assert path == (
        corpus_dir / "summaries" / "family_summary.json"
    ).resolve()
    assert opened == [path]


def test_open_endpoint_rejects_unknown_target():
    response = TestClient(main.app).post("/api/v10/corpus/open/not-a-target")

    assert response.status_code == 400
