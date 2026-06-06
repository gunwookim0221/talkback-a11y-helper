from __future__ import annotations

from qa_frontend.backend.runtime_dashboard import (
    build_runtime_dashboard,
    extract_validation_scenario_evidence_from_xlsx,
    parse_runtime_log,
)


def _write_result_xlsx(path, rows):
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "result"
    headers = ["scenario_id", "final_result", "mismatch_type", "failure_reason"]
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
    workbook.save(path)
    workbook.close()


def test_runtime_log_parser_extracts_summary_progress_and_events():
    log_text = "\n".join(
        [
            "[QA_FRONTEND] start mode='smoke' scenario_selection_applied=true scenario_ids=['global_nav_main'] runtime_config_path='x' launch_mode='clean'",
            "[QA_FRONTEND][language] language_mode='ko-KR' device_locale='ko-KR' target_locale='ko-KR' changed='true' verified='true' status='ok'",
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
    assert summary["language_mode"] == "ko-KR"
    assert summary["device_locale"] == "ko-KR"
    assert summary["popup_result"] == "cleared"
    assert summary["preflight_state"] == "passed"
    assert summary["adb_status"] == "ok"
    assert summary["helper_status"] == "ok"
    assert summary["current_scenario"] == "life_air_care_plugin"
    assert summary["total_step_count"] == 2
    assert summary["overlay_count"] == 1
    assert summary["save_excel_count"] == 1
    assert summary["passed_scenarios"] == 1
    assert summary["warning_scenarios"] == 0
    assert summary["failed_scenarios"] == 1
    assert progress["global_nav_main"]["status"] == "passed"
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
    assert progress["global_nav_main"]["status"] == "passed"
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


def test_entry_contract_failure_is_failed():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['life_find_plugin']",
            "[SCENARIO][entry_contract] failed scenario='life_find_plugin' entry_type='card' reason='verify_failed'",
            "[PERF][scenario_summary] scenario=life_find_plugin total_steps=1",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["failed_scenarios"] == 1
    assert progress["life_find_plugin"]["status"] == "failed"


def test_post_open_verify_miss_with_plugin_identity_evidence_is_warning():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['life_find_plugin']",
            "[ENTRY][post_open_identity] scenario_id='life_find_plugin' top_visible_labels='Navigate up Navigate up,More options More option,Current location Current,My devices My devices' body_texts='Current location Current location,My devices My devices,Offline 경기도 수원시' verify_hit=false",
            "[SCENARIO][entry_contract] failed scenario='life_find_plugin' entry_type='card' reason='verify_failed' detail='post_open_verify_miss'",
            "[PERF][scenario_summary] scenario=life_find_plugin total_steps=1",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["failed_scenarios"] == 0
    assert summary["warning_scenarios"] == 1
    assert progress["life_find_plugin"]["status"] == "warning"


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
    assert summary["scenario_progress"] == [{"id": "global_nav_main", "status": "passed", "steps": 6}]


def test_entry_success_summary_and_fail_stuck_is_warning():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['device_smoke_sensor_plugin']",
            "[SCENARIO][entry_contract] success scenario='device_smoke_sensor_plugin' entry_type='card'",
            "[STEP] END scenario='device_smoke_sensor_plugin' step=0 visible='Smoke detector'",
            "[STOP][eval] step=8 scenario='device_smoke_sensor_plugin' decision='stop' reason='repeat_no_progress' traversal_result='FAIL_STUCK' final_result='FAIL' failure_reason='repeat_no_progress'",
            "[PERF][scenario_summary] scenario=device_smoke_sensor_plugin total_steps=9",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["passed_scenarios"] == 0
    assert summary["warning_scenarios"] == 1
    assert summary["failed_scenarios"] == 0
    assert progress["device_smoke_sensor_plugin"]["status"] == "warning"


def test_continue_stop_fail_does_not_pin_scenario_failed_when_it_recovers():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['device_motion_sensor_plugin']",
            "[SCENARIO][entry_contract] success scenario='device_motion_sensor_plugin' entry_type='card'",
            "[STEP] END scenario='device_motion_sensor_plugin' step=0 visible='Motion sensor'",
            "[STOP][eval] step=6 scenario='device_motion_sensor_plugin' decision='continue' reason='local_tab_continue' traversal_result='FAIL_STUCK' final_result='FAIL' failure_reason='repeat_no_progress'",
            "[STEP] END scenario='device_motion_sensor_plugin' step=8 visible='Filter, All'",
            "[PERF][scenario_summary] scenario=device_motion_sensor_plugin total_steps=9",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["warning_scenarios"] == 1
    assert summary["failed_scenarios"] == 0
    assert progress["device_motion_sensor_plugin"]["status"] == "warning"


def test_validation_failure_evidence_overrides_warning_to_failed():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['life_family_care_plugin']",
            "[SCENARIO][entry_contract] success scenario='life_family_care_plugin' entry_type='card'",
            "[STEP] END scenario='life_family_care_plugin' step=0 visible='Family Care'",
            "[STOP][eval] step=4 scenario='life_family_care_plugin' decision='continue' reason='none' traversal_result='FAIL_MOVE' final_result='FAIL' failure_reason='move_failed'",
            "[PERF][scenario_summary] scenario=life_family_care_plugin total_steps=18",
        ]
    )

    summary = parse_runtime_log(log_text, validation_failed_scenarios={"life_family_care_plugin"})
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["failed_scenarios"] == 1
    assert summary["warning_scenarios"] == 0
    assert progress["life_family_care_plugin"]["status"] == "failed"


def test_xlsx_transient_exact_match_move_failed_is_warning(tmp_path):
    xlsx_path = tmp_path / "result.xlsx"
    _write_result_xlsx(
        xlsx_path,
        [
            {
                "scenario_id": "life_family_care_plugin",
                "final_result": "FAIL",
                "mismatch_type": "EXACT_MATCH",
                "failure_reason": "move_failed",
            },
            {
                "scenario_id": "life_family_care_plugin",
                "final_result": "PASS",
                "mismatch_type": "EXACT_MATCH",
                "failure_reason": "",
            },
        ],
    )

    failed, warning = extract_validation_scenario_evidence_from_xlsx(xlsx_path)

    assert failed == set()
    assert warning == {"life_family_care_plugin"}


def test_xlsx_repeat_no_progress_exact_match_is_warning(tmp_path):
    xlsx_path = tmp_path / "result.xlsx"
    _write_result_xlsx(
        xlsx_path,
        [
            {
                "scenario_id": "device_smoke_sensor_plugin",
                "final_result": "FAIL",
                "mismatch_type": "EXACT_MATCH",
                "failure_reason": "repeat_no_progress",
            }
        ],
    )

    failed, warning = extract_validation_scenario_evidence_from_xlsx(xlsx_path)

    assert failed == set()
    assert warning == {"device_smoke_sensor_plugin"}


def test_xlsx_empty_visible_remains_failed(tmp_path):
    xlsx_path = tmp_path / "result.xlsx"
    _write_result_xlsx(
        xlsx_path,
        [
            {
                "scenario_id": "life_home_monitor_plugin",
                "final_result": "FAIL",
                "mismatch_type": "EMPTY_VISIBLE",
                "failure_reason": "",
            }
        ],
    )

    failed, warning = extract_validation_scenario_evidence_from_xlsx(xlsx_path)

    assert failed == {"life_home_monitor_plugin"}
    assert warning == set()


def test_xlsx_label_mismatch_remains_failed(tmp_path):
    xlsx_path = tmp_path / "result.xlsx"
    _write_result_xlsx(
        xlsx_path,
        [
            {
                "scenario_id": "life_family_care_plugin",
                "final_result": "FAIL",
                "mismatch_type": "LABEL_MISMATCH",
                "failure_reason": "speech_visible_diverged",
            }
        ],
    )

    failed, warning = extract_validation_scenario_evidence_from_xlsx(xlsx_path)

    assert failed == {"life_family_care_plugin"}
    assert warning == set()


def test_normal_successful_traversal_is_passed():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['device_tv_plugin']",
            "[SCENARIO][entry_contract] success scenario='device_tv_plugin' entry_type='card'",
            "[STEP] END scenario='device_tv_plugin' step=0 visible='TV'",
            "[STOP][eval] step=0 scenario='device_tv_plugin' decision='continue' reason='none' traversal_result='PASS_MOVED' final_result='PASS'",
            "[PERF][scenario_summary] scenario=device_tv_plugin total_steps=1",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["passed_scenarios"] == 1
    assert summary["warning_scenarios"] == 0
    assert summary["failed_scenarios"] == 0
    assert progress["device_tv_plugin"]["status"] == "passed"


def test_device_card_missing_is_not_available():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['device_tv_plugin']",
            "[19:04:52] [SCENARIO][pre_nav] step=1 action=enter_device_card_plugin target='TV'",
            "[19:04:55] [DEVICE_ENTRY][inventory] phase='before_expand' count=1 labels='Galaxy Home Mini N7LM Melon'",
            "[19:04:55] [DEVICE_ENTRY][expand] running reason='target_not_visible'",
            "[19:04:56] [DEVICE][scroll] inventory_signature_changed=false",
            "[19:05:04] [SCENARIO][pre_nav] failed reason='action_failed' step=1",
            "[19:05:04] [PERF][scenario_summary] scenario=device_tv_plugin total_steps=1 save_excel_count=0",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["passed_scenarios"] == 0
    assert summary["executed_scenarios"] == 0
    assert summary["not_available_scenarios"] == 1
    assert summary["availability_candidate_scenarios"] == 1
    assert progress["device_tv_plugin"]["status"] == "not_available"
    assert progress["device_tv_plugin"]["availability_status"] == "NOT_AVAILABLE"
    assert progress["device_tv_plugin"]["availability_confidence"] == "high"
    assert "Galaxy Home Mini" in progress["device_tv_plugin"]["availability_reason"]


def test_life_plugin_anchor_failure_is_no_target_candidate():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['life_home_care_plugin']",
            "[18:56:22] [SCENARIO][pre_nav] step=1 action=xml_scroll_search_tap target='(?i)(^home\\\\s*care$|home\\\\s*care\\\\.|\\\\bhomecare\\\\b|홈\\\\s*케어)'",
            "[18:56:34] [ANCHOR][scenario_start] stabilization failed tab='(?i).*life.*' scenario='life_home_care_plugin' low_confidence=true reason='low_confidence_anchor_start'",
            "[18:56:34] [ANCHOR][scenario_start] abort low_confidence_fallback=false scenario='life_home_care_plugin' reason='insufficient_new_screen_evidence'",
            "[18:56:34] [PERF][scenario_summary] scenario=life_home_care_plugin total_steps=1 save_excel_count=0",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["passed_scenarios"] == 0
    assert summary["no_target_candidate_scenarios"] == 1
    assert summary["availability_candidate_scenarios"] == 1
    assert progress["life_home_care_plugin"]["status"] == "no_target_candidate"
    assert progress["life_home_care_plugin"]["availability_status"] == "NO_TARGET_CANDIDATE"
    assert progress["life_home_care_plugin"]["availability_confidence"] == "medium"


def test_crash_like_one_step_is_not_marked_not_available():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['device_tv_plugin']",
            "[19:04:52] [SCENARIO][pre_nav] step=1 action=enter_device_card_plugin target='TV'",
            "[19:04:53] APP_TERMINATED scenario='device_tv_plugin'",
            "[19:05:04] [PERF][scenario_summary] scenario=device_tv_plugin total_steps=1 save_excel_count=0",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["availability_candidate_scenarios"] == 0
    assert progress["device_tv_plugin"]["status"] == "passed"


def test_one_step_with_result_row_is_executed_not_availability_candidate():
    log_text = "\n".join(
        [
            "[QA_FRONTEND][scenario_selection] enabled_ids=['device_tv_plugin']",
            "[SCENARIO][entry_contract] success scenario='device_tv_plugin' entry_type='card'",
            "[STEP] END scenario='device_tv_plugin' step=0 visible='TV'",
            "[PERF][scenario_summary] scenario=device_tv_plugin total_steps=1 save_excel_count=1",
        ]
    )

    summary = parse_runtime_log(log_text)
    progress = {item["id"]: item for item in summary["scenario_progress"]}

    assert summary["availability_candidate_scenarios"] == 0
    assert summary["executed_scenarios"] == 1
    assert progress["device_tv_plugin"]["status"] == "passed"


def test_availability_counts_are_excluded_from_passed_and_executed_totals():
    executed_ids = [f"executed_{index}" for index in range(17)]
    not_available_ids = [f"device_missing_{index}" for index in range(12)]
    no_target_ids = ["life_food_plugin", "life_home_care_plugin"]
    selected = executed_ids + not_available_ids + no_target_ids
    lines = [f"[QA_FRONTEND][scenario_selection] enabled_ids={selected!r}"]
    for scenario_id in executed_ids:
        lines.extend(
            [
                f"[SCENARIO][entry_contract] success scenario='{scenario_id}' entry_type='card'",
                f"[STEP] END scenario='{scenario_id}' step=0 visible='{scenario_id}'",
                f"[PERF][scenario_summary] scenario={scenario_id} total_steps=1 save_excel_count=1",
            ]
        )
    for scenario_id in not_available_ids:
        lines.extend(
            [
                f"[SCENARIO][pre_nav] step=1 action=enter_device_card_plugin target='{scenario_id}'",
                "[DEVICE_ENTRY][inventory] phase='before_expand' count=1 labels='Galaxy Home Mini N7LM Melon'",
                "[DEVICE_ENTRY][expand] running reason='target_not_visible'",
                "[DEVICE][scroll] inventory_signature_changed=false",
                "[SCENARIO][pre_nav] failed reason='action_failed' step=1",
                f"[PERF][scenario_summary] scenario={scenario_id} total_steps=1 save_excel_count=0",
            ]
        )
    for scenario_id in no_target_ids:
        lines.extend(
            [
                f"[SCENARIO][pre_nav] step=1 action=xml_scroll_search_tap target='{scenario_id}'",
                f"[ANCHOR][scenario_start] abort scenario='{scenario_id}' reason='insufficient_new_screen_evidence'",
                f"[PERF][scenario_summary] scenario={scenario_id} total_steps=1 save_excel_count=0",
            ]
        )

    summary = parse_runtime_log("\n".join(lines))

    assert len(summary["scenario_progress"]) == 31
    assert summary["executed_scenarios"] == 17
    assert summary["availability_candidate_scenarios"] == 14
    assert summary["not_available_scenarios"] == 12
    assert summary["no_target_candidate_scenarios"] == 2
    assert summary["failed_scenarios"] == 0
    assert summary["passed_scenarios"] == 17
    assert summary["passed_scenarios"] + summary["availability_candidate_scenarios"] == 31
    assert summary["executed_scenarios"] + summary["availability_candidate_scenarios"] == 31


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
