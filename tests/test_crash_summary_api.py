from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from qa_frontend.backend import crash_summary
from qa_frontend.backend.main import app


def _device_dir(tmp_path: Path) -> Path:
    path = tmp_path / "qa_frontend_runs" / "batch_20260603_010203" / "device_Model_SERIAL"
    path.mkdir(parents=True)
    return path


def _write_crash(
    device_dir: Path,
    event_id: str,
    *,
    crash_type: str = "APP_TERMINATED",
    scenario: str = "global_nav_main",
    recovery: dict[str, object] | None = None,
    screenshot: bool = True,
) -> Path:
    event_dir = device_dir / "crashes" / event_id
    event_dir.mkdir(parents=True)
    (event_dir / "crash_context.json").write_text(
        json.dumps(
            {
                "crash_event_id": event_id,
                "crash_type": crash_type,
                "scenario": {"name": scenario},
                "timestamp": "2026-06-04T01:23:45+09:00",
                "recovery": recovery or {"scenario_final_status": "CRASH_CAPTURED"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (event_dir / "crash_event.json").write_text(
        json.dumps({"crash_event_id": event_id, "crash_type": crash_type}, ensure_ascii=False),
        encoding="utf-8",
    )
    (event_dir / "crash_repro.md").write_text("# Manual Repro Guide\n\n1. Open SmartThings.\n", encoding="utf-8")
    (event_dir / "focus_state.json").write_text("{}", encoding="utf-8")
    (event_dir / "logcat_excerpt.txt").write_text("launcher package detected", encoding="utf-8")
    (event_dir / "crash_helper_dump.json").write_text("{}", encoding="utf-8")
    (event_dir / "crash_window_dump.xml").write_text("<hierarchy />", encoding="utf-8")
    if screenshot:
        (event_dir / "crash_screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return event_dir


def test_build_crash_summary_returns_empty_when_no_crash_directory(tmp_path):
    _device_dir(tmp_path)

    summary = crash_summary.build_crash_summary(
        "batch_20260603_010203",
        "device_Model_SERIAL",
        run_log_dir=tmp_path / "qa_frontend_runs",
    )

    assert summary == {"crash_count": 0, "crashes": []}


def test_build_crash_summary_includes_artifact_metadata(tmp_path):
    device_dir = _device_dir(tmp_path)
    _write_crash(device_dir, "CRASH-0001", crash_type="APP_TERMINATED")

    summary = crash_summary.build_crash_summary(
        "batch_20260603_010203",
        "device_Model_SERIAL",
        run_log_dir=tmp_path / "qa_frontend_runs",
    )

    assert summary["crash_count"] == 1
    assert summary["crashes"] == [
        {
            "crash_event_id": "CRASH-0001",
            "crash_type": "APP_TERMINATED",
            "scenario": "global_nav_main",
            "timestamp": "2026-06-04T01:23:45+09:00",
            "recovery_result": "CRASH_CAPTURED",
            "repro_guide_exists": True,
            "screenshot_exists": True,
            "helper_dump_exists": True,
            "window_dump_exists": True,
        }
    ]


def test_build_crash_summary_maps_crash_recovered(tmp_path):
    device_dir = _device_dir(tmp_path)
    _write_crash(device_dir, "CRASH-0001", recovery={"result": "crash_recovered"})

    summary = crash_summary.build_crash_summary(
        "batch_20260603_010203",
        "device_Model_SERIAL",
        run_log_dir=tmp_path / "qa_frontend_runs",
    )

    assert summary["crashes"][0]["recovery_result"] == "CRASH_RECOVERED"


def test_build_crash_summary_maps_crash_repeated(tmp_path):
    device_dir = _device_dir(tmp_path)
    _write_crash(device_dir, "CRASH-0001", recovery={"scenario_final_status": "CRASH_REPEATED"})

    summary = crash_summary.build_crash_summary(
        "batch_20260603_010203",
        "device_Model_SERIAL",
        run_log_dir=tmp_path / "qa_frontend_runs",
    )

    assert summary["crashes"][0]["recovery_result"] == "CRASH_REPEATED"


def test_build_crash_summary_marks_missing_screenshot_false(tmp_path):
    device_dir = _device_dir(tmp_path)
    _write_crash(device_dir, "CRASH-0001", screenshot=False)

    summary = crash_summary.build_crash_summary(
        "batch_20260603_010203",
        "device_Model_SERIAL",
        run_log_dir=tmp_path / "qa_frontend_runs",
    )

    assert summary["crashes"][0]["screenshot_exists"] is False


def test_crash_summary_api_returns_device_crashes(tmp_path, monkeypatch):
    device_dir = _device_dir(tmp_path)
    _write_crash(device_dir, "CRASH-0001", recovery={"scenario_final_status": "CRASH_RECOVERED"})
    monkeypatch.setattr(crash_summary, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")
    client = TestClient(app)

    response = client.get("/api/runs/batch_20260603_010203/devices/device_Model_SERIAL/crashes")

    assert response.status_code == 200
    assert response.json()["crashes"][0]["recovery_result"] == "CRASH_RECOVERED"


def test_crash_detail_api_returns_repro_guide_and_artifacts(tmp_path, monkeypatch):
    device_dir = _device_dir(tmp_path)
    _write_crash(device_dir, "CRASH-0001", recovery={"scenario_final_status": "CRASH_RECOVERED"})
    monkeypatch.setattr(crash_summary, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")
    client = TestClient(app)

    response = client.get("/api/runs/batch_20260603_010203/devices/device_Model_SERIAL/crashes/CRASH-0001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["crash_event_id"] == "CRASH-0001"
    assert payload["repro_guide"].startswith("# Manual Repro Guide")
    assert payload["artifacts"] == {
        "screenshot": True,
        "helper_dump": True,
        "window_dump": True,
    }


def test_crash_detail_api_handles_missing_artifacts(tmp_path, monkeypatch):
    device_dir = _device_dir(tmp_path)
    event_dir = _write_crash(device_dir, "CRASH-0001", screenshot=False)
    (event_dir / "crash_repro.md").unlink()
    (event_dir / "crash_helper_dump.json").unlink()
    monkeypatch.setattr(crash_summary, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")
    client = TestClient(app)

    response = client.get("/api/runs/batch_20260603_010203/devices/device_Model_SERIAL/crashes/CRASH-0001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["repro_guide"] is None
    assert payload["artifacts"]["screenshot"] is False
    assert payload["artifacts"]["helper_dump"] is False
    assert payload["artifacts"]["window_dump"] is True


def test_crash_screenshot_api_returns_png(tmp_path, monkeypatch):
    device_dir = _device_dir(tmp_path)
    _write_crash(device_dir, "CRASH-0001")
    monkeypatch.setattr(crash_summary, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")
    client = TestClient(app)

    response = client.get("/api/runs/batch_20260603_010203/devices/device_Model_SERIAL/crashes/CRASH-0001/screenshot")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content.startswith(b"\x89PNG")


def test_crash_download_api_returns_best_effort_zip(tmp_path, monkeypatch):
    device_dir = _device_dir(tmp_path)
    event_dir = _write_crash(device_dir, "CRASH-0001")
    (event_dir / "crash_helper_dump.json").unlink()
    monkeypatch.setattr(crash_summary, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")
    client = TestClient(app)

    response = client.get("/api/runs/batch_20260603_010203/devices/device_Model_SERIAL/crashes/CRASH-0001/download")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
    assert "crash_event.json" in names
    assert "crash_context.json" in names
    assert "crash_repro.md" in names
    assert "crash_screenshot.png" in names
    assert "crash_helper_dump.json" not in names
