from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from qa_frontend.backend.main import app, runner
from qa_frontend.backend.recent_runs import list_recent_runs, safe_recent_run_log_path


def _write_log(path: Path, *, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_list_recent_runs_limits_to_newest_twenty_and_extracts_excel(tmp_path):
    for index in range(21):
        run_id = f"20260528_{90000 + index:06d}"
        mode = "smoke" if index % 2 == 0 else "full"
        body = "[MAIN] script end\n"
        if index == 20:
            body += "[SAVE] saved excel: output/talkback_compare_20260528_090020.xlsx rows=6 with_images=True\n"
        _write_log(tmp_path / f"{run_id}_{mode}.log", body=body)

    runs = list_recent_runs(run_log_dir=tmp_path)
    by_id = {run["run_id"]: run for run in runs}

    assert len(runs) == 20
    assert runs[0]["run_id"] > runs[-1]["run_id"]
    assert by_id["20260528_090020"]["xlsx_filename"] == "talkback_compare_20260528_090020.xlsx"
    assert by_id["20260528_090020"]["status"] == "success"


def test_list_recent_runs_marks_failures_and_stopped_states(tmp_path):
    _write_log(
        tmp_path / "20260528_100000_smoke.log",
        body="[QA_FRONTEND][run] final_state='stopped' returncode=0\n",
    )
    _write_log(
        tmp_path / "20260528_100100_smoke.log",
        body="[08:06:57] [STOP][eval] final_result='FAIL'\n[MAIN] script end\n",
    )

    runs = list_recent_runs(run_log_dir=tmp_path)
    by_id = {run["run_id"]: run for run in runs}

    assert by_id["20260528_100000"]["status"] == "stopped"
    assert by_id["20260528_100100"]["status"] == "failed"


def test_safe_recent_run_log_path_returns_matching_log(tmp_path):
    path = tmp_path / "20260528_101500_smoke.log"
    _write_log(path, body="ok\n")

    assert safe_recent_run_log_path("20260528_101500", run_log_dir=tmp_path) == path.resolve()


def test_run_log_download_returns_current_log(tmp_path, monkeypatch):
    path = tmp_path / "20260528_101700_smoke.log"
    _write_log(path, body="current\n")
    client = TestClient(app)
    monkeypatch.setattr(runner, "get_log_path", lambda: path)

    response = client.get("/api/run/log/download")

    assert response.status_code == 200
    assert "current" in response.text


def test_recent_run_log_download_returns_requested_log(tmp_path, monkeypatch):
    path = tmp_path / "20260528_101800_smoke.log"
    _write_log(path, body="recent\n")
    client = TestClient(app)
    monkeypatch.setattr("qa_frontend.backend.main.safe_recent_run_log_path", lambda run_id: path)

    response = client.get("/api/runs/recent/20260528_101800/log")

    assert response.status_code == 200
    assert "recent" in response.text
