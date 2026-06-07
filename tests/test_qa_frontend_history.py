from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from qa_frontend.backend.main import app, runner
from qa_frontend.backend.batch_runner import get_recent_batches
from qa_frontend.backend.recent_runs import list_recent_runs, safe_recent_run_log_path
from qa_frontend.backend.run_summary import build_run_summary, summary_path_for_log, write_summary_file


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
    assert run["scenarios"][0]["id"] == "global_nav_main"
    assert run["scenarios"][0]["status"] == "failed"
    assert run["scenarios"][0]["reason"]


def test_recent_run_scenario_result_warning_when_warning_scenarios_exist(tmp_path):
    _write_log(
        tmp_path / "20260528_110150_smoke.log",
        body="\n".join(
            [
                "[QA_FRONTEND][scenario_selection] enabled_ids=['device_smoke_sensor_plugin']",
                "[SCENARIO][entry_contract] success scenario='device_smoke_sensor_plugin' entry_type='card'",
                "[STEP] END scenario='device_smoke_sensor_plugin' step=0 visible='Smoke detector'",
                "[STOP][eval] step=8 scenario='device_smoke_sensor_plugin' decision='stop' reason='repeat_no_progress' traversal_result='FAIL_STUCK' final_result='FAIL' failure_reason='repeat_no_progress'",
                "[PERF][scenario_summary] scenario=device_smoke_sensor_plugin total_steps=9",
                "[MAIN] script end",
            ]
        ),
    )

    run = list_recent_runs(run_log_dir=tmp_path)[0]

    assert run["process_status"] == "success"
    assert run["scenario_result_status"] == "warning"
    assert run["warning_scenarios"] == 1
    assert run["failed_scenarios"] == 0
    assert run["scenarios"][0]["id"] == "device_smoke_sensor_plugin"
    assert run["scenarios"][0]["status"] == "warning"
    assert run["scenarios"][0]["reason"] == "repeat_no_progress"


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


def test_build_run_summary_contains_sidecar_schema(tmp_path):
    log_path = tmp_path / "20260528_120000_smoke.log"
    _write_log(
        log_path,
        body="\n".join(
            [
                "[QA_FRONTEND] start mode='smoke' scenario_selection_applied=true scenario_ids=['global_nav_main'] runtime_config_path='x' launch_mode='clean'",
                "[QA_FRONTEND][language] language_mode='ko-KR' device_locale='ko-KR' target_locale='ko-KR' changed='true' verified='true' status='ok'",
                "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']",
                "[QA_FRONTEND][preflight][popup] foreground_after='com.samsung.android.oneconnect' result='cleared'",
                "[QA_FRONTEND][preflight] final_result='passed' reason='ok'",
                "[21:04:10] [GLOBAL_NAV][start_gate] passed scenario='global_nav_main'",
                "[21:04:48] [STEP] END scenario='global_nav_main' step=5 visible='Menu, Tab 5 of 5., New content available'",
                "[21:04:48] [STOP][eval] step=5 scenario='global_nav_main' scenario_type='global_nav' decision='stop' reason='smart_nav_terminal' traversal_result='FAIL_STUCK' final_result='FAIL'",
                "[21:04:49] [PERF][scenario_summary] scenario=global_nav_main total_steps=6",
                "[SAVE] saved excel: output/talkback_compare_20260528_120000.xlsx rows=6",
                "[MAIN] script end",
            ]
        ),
    )

    summary = build_run_summary(
        status={
            "state": "finished",
            "run_id": "20260528_120000",
            "mode": "smoke",
            "launch_mode": "clean",
            "language_mode": "ko-KR",
            "device_locale": "ko-KR",
            "started_at": "2026-05-28T12:00:00",
            "finished_at": "2026-05-28T12:01:26",
        },
        log_path=log_path,
        scenario_ids=["global_nav_main"],
    )

    assert summary["schema_version"] == 1
    assert summary["process_status"] == "success"
    assert summary["scenario_result_status"] == "passed"
    assert summary["language_mode"] == "ko-KR"
    assert summary["device_locale"] == "ko-KR"
    assert summary["completed_scenarios"] == 1
    assert summary["failed_scenarios"] == 0
    assert summary["scenario_completed_count"] == 1
    assert summary["scenario_failed_count"] == 0
    assert summary["scenario_passed_count"] == 1
    assert summary["total_steps"] == 6
    assert summary["popup_result"] == "cleared"
    assert summary["xlsx_filename"] == "talkback_compare_20260528_120000.xlsx"
    assert summary["event_counts"]["popup_cleared"] == 1
    assert summary["scenarios"][0]["id"] == "global_nav_main"
    assert summary["scenarios"][0]["status"] == "passed"
    assert summary["scenarios"][0]["steps"] == 6


def test_run_summary_and_recent_runs_preserve_availability_counts(tmp_path):
    log_path = tmp_path / "20260606_184848_full.log"
    body = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['device_tv_plugin', 'life_home_care_plugin']",
            "[SCENARIO][pre_nav] step=1 action=enter_device_card_plugin target='TV'",
            "[DEVICE_ENTRY][inventory] phase='before_expand' count=1 labels='Galaxy Home Mini N7LM Melon'",
            "[DEVICE_ENTRY][expand] running reason='target_not_visible'",
            "[DEVICE][scroll] inventory_signature_changed=false",
            "[SCENARIO][pre_nav] failed reason='action_failed' step=1",
            "[PERF][scenario_summary] scenario=device_tv_plugin total_steps=1 save_excel_count=0",
            "[SCENARIO][pre_nav] step=1 action=xml_scroll_search_tap target='Home Care'",
            "[ANCHOR][scenario_start] abort scenario='life_home_care_plugin' reason='insufficient_new_screen_evidence'",
            "[PERF][scenario_summary] scenario=life_home_care_plugin total_steps=1 save_excel_count=0",
            "[MAIN] script end",
        ]
    )
    _write_log(log_path, body=body)

    summary = build_run_summary(
        status={"state": "finished", "run_id": "20260606_184848", "mode": "full"},
        log_path=log_path,
        scenario_ids=["device_tv_plugin", "life_home_care_plugin"],
    )
    run = list_recent_runs(run_log_dir=tmp_path)[0]

    assert summary["executed_scenarios"] == 0
    assert summary["not_available_scenarios"] == 1
    assert summary["no_target_candidate_scenarios"] == 1
    assert summary["availability_candidate_scenarios"] == 2
    assert run["executed_scenarios"] == summary["executed_scenarios"]
    assert run["not_available_scenarios"] == summary["not_available_scenarios"]
    assert run["no_target_candidate_scenarios"] == summary["no_target_candidate_scenarios"]
    assert run["availability_candidate_scenarios"] == summary["availability_candidate_scenarios"]
    assert run["scenarios"][0]["availability_status"] == "NOT_AVAILABLE"
    assert run["scenarios"][1]["availability_status"] == "NO_TARGET_CANDIDATE"


def test_recent_runs_uses_summary_fast_path_when_available(tmp_path):
    log_path = tmp_path / "20260528_120100_smoke.log"
    _write_log(log_path, body="unstructured log only\n")
    summary_path_for_log(log_path).write_text(
        """{
  "schema_version": 1,
  "run_id": "20260528_120100",
  "mode": "smoke",
  "language_mode": "en-US",
  "device_locale": "en-US",
  "started_at": "2026-05-28T12:01:00",
  "elapsed_seconds": 42,
  "process_status": "success",
  "scenario_result_status": "warning",
  "passed_scenarios": 0,
  "warning_scenarios": 1,
  "completed_scenarios": 1,
  "failed_scenarios": 0,
  "total_scenarios": 1,
  "event_warning_count": 0,
  "scenarios": [
    {
      "id": "life_family_care_plugin",
      "status": "warning",
      "steps": 41,
      "stop_reason": "repeat_no_progress",
      "traversal_result": "FAIL_STUCK"
    }
  ],
  "xlsx_filename": "talkback_compare_cached.xlsx"
}""",
        encoding="utf-8",
    )

    run = list_recent_runs(run_log_dir=tmp_path)[0]

    assert run["summary_exists"] is True
    assert run["summary_source"] == "summary_json"
    assert run["language_mode"] == "en-US"
    assert run["device_locale"] == "en-US"
    assert run["scenario_result_status"] == "warning"
    assert run["warning_scenarios"] == 1
    assert run["completed_scenarios"] == 1
    assert run["duration_seconds"] == 42
    assert run["xlsx_filename"] == "talkback_compare_cached.xlsx"
    assert run["scenarios"] == [
        {
            "id": "life_family_care_plugin",
            "status": "warning",
            "steps": 41,
            "reason": "repeat_no_progress",
            "stop_reason": "repeat_no_progress",
            "traversal_result": "FAIL_STUCK",
        }
    ]


def test_recent_runs_falls_back_to_log_parse_when_summary_is_malformed(tmp_path):
    log_path = tmp_path / "20260528_120200_smoke.log"
    _write_log(
        log_path,
        body="\n".join(
            [
                "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']",
                "[PERF][scenario_summary] scenario=global_nav_main total_steps=2",
                "[MAIN] script end",
            ]
        ),
    )
    summary_path_for_log(log_path).write_text("{broken json", encoding="utf-8")

    run = list_recent_runs(run_log_dir=tmp_path)[0]

    assert run["summary_exists"] is False
    assert run["summary_source"] == "log_parse"
    assert run["process_status"] == "success"
    assert run["scenario_result_status"] == "passed"
    assert run["completed_scenarios"] == 1


def test_write_summary_file_handles_stopped_partial_run(tmp_path):
    log_path = tmp_path / "20260528_120300_smoke.log"
    _write_log(
        log_path,
        body="\n".join(
            [
                "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main', 'life_air_care_plugin']",
                "[PERF][scenario_summary] scenario=global_nav_main total_steps=6",
                "[QA_FRONTEND][run] final_state='stopped' returncode=0",
            ]
        ),
    )

    summary = write_summary_file(
        status={
            "state": "stopped",
            "run_id": "20260528_120300",
            "mode": "smoke",
            "started_at": "2026-05-28T12:03:00",
            "finished_at": "2026-05-28T12:03:20",
        },
        log_path=log_path,
        scenario_ids=["global_nav_main", "life_air_care_plugin"],
    )

    assert summary_path_for_log(log_path).exists()
    assert summary["process_status"] == "stopped"
    assert summary["scenario_result_status"] == "partial"
    assert summary["completed_scenarios"] == 1
    assert summary["total_scenarios"] == 2


def test_write_summary_file_marks_failed_scenario(tmp_path):
    log_path = tmp_path / "20260528_120400_smoke.log"
    _write_log(
        log_path,
        body="\n".join(
            [
                "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']",
                "[TAB][select] stabilization failed scenario='global_nav_main'",
                "[PERF][scenario_summary] scenario=global_nav_main total_steps=1",
                "[MAIN] script end",
            ]
        ),
    )

    summary = write_summary_file(
        status={"state": "finished", "run_id": "20260528_120400", "mode": "smoke"},
        log_path=log_path,
        scenario_ids=["global_nav_main"],
    )

    assert summary["process_status"] == "success"
    assert summary["scenario_result_status"] == "failed"
    assert summary["failed_scenarios"] == 1
    assert summary["scenarios"][0]["status"] == "failed"


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


def test_recent_batches_include_duration_for_finished_batch(tmp_path, monkeypatch):
    run_log_dir = tmp_path / "qa_frontend_runs"
    batch_dir = run_log_dir / "batch_20260606_184840"
    batch_dir.mkdir(parents=True)
    (batch_dir / "batch_summary.json").write_text(
        """{
  "batch_id": "batch_20260606_184840",
  "mode": "full",
  "created_at": "2026-06-06T18:48:40+09:00",
  "state": "finished",
  "devices": [
    {
      "serial": "SERIAL1",
      "model": "Model",
      "state": "passed",
      "return_code": 0,
      "output_dir": "qa_frontend_runs/batch_20260606_184840/device_Model_SERIAL1",
      "finished_at": "2026-06-06T19:01:14+09:00"
    }
  ]
}""",
        encoding="utf-8",
    )
    monkeypatch.setattr("qa_frontend.backend.batch_runner.RUN_LOG_DIR", run_log_dir)
    monkeypatch.setattr("qa_frontend.backend.batch_runner.ROOT_DIR", tmp_path)

    batches = get_recent_batches()

    assert len(batches) == 1
    assert batches[0]["batch_id"] == "batch_20260606_184840"
    assert batches[0]["duration_seconds"] == 754


def test_open_language_settings_endpoint(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(
        "qa_frontend.backend.main.open_language_settings",
        lambda: {"ok": True, "status": "opened", "intent": "android.settings.LOCALE_SETTINGS"},
    )

    response = client.post("/api/device/open-language-settings")

    assert response.status_code == 200
    assert response.json()["status"] == "opened"
    assert response.json()["intent"] == "android.settings.LOCALE_SETTINGS"
