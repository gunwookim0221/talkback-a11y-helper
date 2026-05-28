from __future__ import annotations

from qa_frontend.backend.runtime_dashboard import build_runtime_dashboard, parse_runtime_log


def test_runtime_log_parser_extracts_summary_progress_and_events():
    log_text = "\n".join(
        [
            "[QA_FRONTEND] start mode='smoke' scenario_selection_applied=true scenario_ids=['global_nav_main'] runtime_config_path='x' launch_mode='clean'",
            "[QA_FRONTEND][scenario_selection] scenario_selection_applied=true runtime_config_path='x' enabled_ids=['global_nav_main', 'life_air_care_plugin']",
            "[QA_FRONTEND][preflight][adb] status='ok'",
            "[QA_FRONTEND][preflight][helper] status='ok'",
            "[QA_FRONTEND][preflight][popup] foreground_after='com.samsung.android.oneconnect' result='cleared'",
            "[QA_FRONTEND][preflight] final_result='passed' reason='ok'",
            "[08:00:00] [STEP] START scenario='global_nav_main' step=0",
            "[08:00:01] [STEP] END scenario='global_nav_main' step=0 visible='Home, Tab 1 of 5'",
            "[08:00:02] [OVERLAY] blocked by scenario policy scenario='global_nav_main'",
            "[08:00:03] [STOP][eval] step=0 scenario='global_nav_main' decision='stop' reason='smart_nav_terminal' traversal_result='PASS_MOVED' final_result='PASS'",
            "[08:00:04] [PERF][scenario_summary] scenario=global_nav_main total_steps=1 save_excel_count=1",
            "[08:00:05] [SAVE] saved excel: output/talkback_compare_20260528_080000.xlsx rows=1 with_images=True",
            "[08:00:06] [STEP] START scenario='life_air_care_plugin' step=0",
            "[08:00:07] [TAB][select] stabilization failed scenario='life_air_care_plugin'",
            "[08:00:08] [STOP][eval] step=0 scenario='life_air_care_plugin' decision='stop' reason='tab_context_failed' traversal_result='FAIL_STUCK' final_result='FAIL'",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["mode"] == "smoke"
    assert summary["launch_mode"] == "clean"
    assert summary["popup_result"] == "cleared"
    assert summary["preflight_state"] == "passed"
    assert summary["adb_status"] == "ok"
    assert summary["helper_status"] == "ok"
    assert summary["current_scenario"] == "life_air_care_plugin"
    assert summary["total_step_count"] == 2
    assert summary["overlay_count"] == 1
    assert summary["save_excel_count"] == 1
    assert summary["failed_scenarios"] == 1
    assert progress["global_nav_main"]["status"] == "completed"
    assert progress["life_air_care_plugin"]["status"] == "failed"
    assert any(event["type"] == "popup_cleared" for event in summary["event_feed"])
    assert any(event["type"] == "scenario_failed" for event in summary["event_feed"])


def test_global_nav_smart_terminal_at_menu_is_completed_even_when_stop_eval_says_fail():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']",
            "[21:04:10] [GLOBAL_NAV][start_gate] passed scenario='global_nav_main'",
            "[21:04:41] [STEP] END scenario='global_nav_main' step=4 visible='Menu, Tab 5 of 5., New content available'",
            "[21:04:48] [STEP] END scenario='global_nav_main' step=5 visible='Menu, Tab 5 of 5., New content available'",
            "[21:04:48] [STOP][eval] step=5 scenario='global_nav_main' terminal=true scenario_type='global_nav' is_global_nav=true decision='stop' reason='smart_nav_terminal' traversal_result='FAIL_STUCK' final_result='FAIL' failure_reason='repeat_no_progress'",
            "[21:04:49] [PERF][scenario_summary] scenario=global_nav_main total_steps=6 save_excel_count=1",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["failed_scenarios"] == 0
    assert summary["completed_scenarios"] == 1
    assert progress["global_nav_main"]["status"] == "completed"
    assert progress["global_nav_main"]["steps"] == 6
    assert any(event["type"] == "traversal_terminal" for event in summary["event_feed"])


def test_global_nav_no_bottom_nav_candidates_remains_failed():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']",
            "[08:06:57] [TAB][verify_debug] reason='no_bottom_nav_candidates' candidates='none'",
            "[08:06:57] [TAB][select] stabilization failed scenario='global_nav_main'",
            "[08:06:57] [PERF][scenario_summary] scenario=global_nav_main total_steps=1",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["failed_scenarios"] == 1
    assert progress["global_nav_main"]["status"] == "failed"
    assert progress["global_nav_main"]["steps"] == 1


def test_parser_ignores_disabled_skip_lines_when_enabled_ids_are_known():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']",
            "[21:04:10] [GLOBAL_NAV][start_gate] passed scenario='global_nav_main'",
            "[21:04:48] [STEP] END scenario='global_nav_main' step=5 visible='Menu, Tab 5 of 5., New content available'",
            "[21:04:48] [STOP][eval] step=5 scenario='global_nav_main' scenario_type='global_nav' decision='stop' reason='smart_nav_terminal' traversal_result='FAIL_STUCK' final_result='FAIL'",
            "[21:04:49] [PERF][scenario_summary] scenario=global_nav_main total_steps=6",
            "[21:04:50] [MAIN] skip disabled scenario_id='life_air_care_plugin' tab='(?i).*life.*'",
        ]
    )

    summary = parse_runtime_log(log_text)

    assert len(summary["scenario_progress"]) == 1
    assert summary["scenario_progress"] == [{"id": "global_nav_main", "status": "completed", "steps": 6}]


def test_runtime_log_parser_handles_malformed_log_without_exception():
    summary = parse_runtime_log("[QA_FRONTEND][scenario_selection] enabled_ids=[not valid\n\0\0bad")

    assert summary["scenario_progress"] == []
    assert summary["parse_error"] is None


def test_dashboard_aggregation_survives_missing_log(tmp_path):
    dashboard = build_runtime_dashboard(
        status={
            "state": "running",
            "run_id": "20260528_090000",
            "mode": "smoke",
            "launch_mode": "clean",
            "started_at": "2026-05-28T09:00:00",
            "preflight_state": "passed",
            "popup_result": "cleared",
            "helper_state": "ok",
        },
        log_path=tmp_path / "missing.log",
        scenario_ids=["global_nav_main"],
    )

    assert dashboard["run_id"] == "20260528_090000"
    assert dashboard["scenario_progress"] == [{"id": "global_nav_main", "status": "queued", "steps": 0}]
    assert dashboard["preflight_state"] == "passed"
    assert dashboard["popup_result"] == "cleared"
