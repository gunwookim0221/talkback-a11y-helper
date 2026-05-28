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
    assert by_id["20260528_090020"]["process_status"] == "success"


def test_list_recent_runs_marks_failures_and_stopped_states(tmp_path):
    _write_log(
        tmp_path / "20260528_100000_smoke.log",
        body="[QA_FRONTEND][run] final_state='stopped' returncode=0\n",
    )
    _write_log(
        tmp_path / "20260528_100100_smoke.log",
        body="[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']\n"
        "[08:06:57] [STOP][eval] scenario='global_nav_main' final_result='FAIL'\n"
        "[MAIN] script end\n",
    )

    runs = list_recent_runs(run_log_dir=tmp_path)
    by_id = {run["run_id"]: run for run in runs}

    assert by_id["20260528_100000"]["status"] == "stopped"
    assert by_id["20260528_100000"]["process_status"] == "stopped"
    assert by_id["20260528_100100"]["status"] == "success"
    assert by_id["20260528_100100"]["process_status"] == "success"
    assert by_id["20260528_100100"]["scenario_result_status"] == "failed"


def test_recent_run_scenario_result_passed_when_process_success_and_no_failed_scenarios(tmp_path):
    _write_log(
        tmp_path / "20260528_110000_smoke.log",
        body="\n".join(
            [
                "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']",
                "[21:04:10] [GLOBAL_NAV][start_gate] passed scenario='global_nav_main'",
                "[21:04:48] [STEP] END scenario='global_nav_main' step=5 visible='Menu, Tab 5 of 5., New content available'",
                "[21:04:48] [STOP][eval] step=5 scenario='global_nav_main' scenario_type='global_nav' decision='stop' reason='smart_nav_terminal' traversal_result='FAIL_STUCK' final_result='FAIL'",
                "[21:04:49] [PERF][scenario_summary] scenario=global_nav_main total_steps=6",
                "[MAIN] script end",
            ]
        ),
    )

    run = list_recent_runs(run_log_dir=tmp_path)[0]

    assert run["process_status"] == "success"
    assert run["scenario_result_status"] == "passed"
    assert run["completed_scenarios"] == 1
    assert run["failed_scenarios"] == 0
    assert run["total_scenarios"] == 1


def test_recent_run_scenario_result_failed_when_process_success_and_scenario_failed(tmp_path):
    _write_log(
        tmp_path / "20260528_110100_smoke.log",
        body="\n".join(
            [
                "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']",
                "[08:06:57] [TAB][select] stabilization failed scenario='global_nav_main'",
                "[08:06:57] [PERF][scenario_summary] scenario=global_nav_main total_steps=1",
                "[MAIN] script end",
            ]
        ),
    )

    run = list_recent_runs(run_log_dir=tmp_path)[0]

    assert run["process_status"] == "success"
    assert run["scenario_result_status"] == "failed"
    assert run["completed_scenarios"] == 0
    assert run["failed_scenarios"] == 1


def test_recent_run_scenario_result_partial_when_stopped_after_completed_scenario(tmp_path):
    _write_log(
        tmp_path / "20260528_110200_smoke.log",
        body="\n".join(
            [
                "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main', 'life_air_care_plugin']",
                "[08:00:04] [PERF][scenario_summary] scenario=global_nav_main total_steps=6",
                "[QA_FRONTEND][run] final_state='stopped' returncode=0",
            ]
        ),
    )

    run = list_recent_runs(run_log_dir=tmp_path)[0]

    assert run["process_status"] == "stopped"
    assert run["scenario_result_status"] == "partial"
    assert run["completed_scenarios"] == 1
    assert run["failed_scenarios"] == 0


def test_recent_run_scenario_result_unknown_when_log_has_no_parseable_scenarios(tmp_path):
    _write_log(tmp_path / "20260528_110300_smoke.log", body="unstructured log only\n[MAIN] script end\n")

    run = list_recent_runs(run_log_dir=tmp_path)[0]

    assert run["process_status"] == "success"
    assert run["scenario_result_status"] == "unknown"
    assert run["total_scenarios"] == 0


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
