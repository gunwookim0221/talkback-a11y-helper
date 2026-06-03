from qa_frontend.backend import batch_runner


def test_parse_live_log_extracts_current_progress_and_preflight():
    log_text = "\n".join(
        [
            "[PREFLIGHT] device_connected PASS",
            "[PREFLIGHT] wake_screen PASS message='Wake keyevent sent'",
            "[PREFLIGHT] unlock_swipe WARN message='secure lock state not verified'",
            "[PREFLIGHT] app_foreground PASS message='SmartThings foreground confirmed'",
            "[PREFLIGHT][accessibility] helper_ready=true result='ok'",
            "[PREFLIGHT] talkback status='enabled'",
            "[SCENARIO][entry_contract] success scenario='global_nav_main' entry_type='tab'",
            "[STEP] START scenario='global_nav_main' step=0 target='Home' action='smart_next'",
            "[STEP] END scenario='global_nav_main' step=0 visible='Home, Tab 1 of 5' move_result='moved' final_result='PASS'",
            "[QUALITY] step=0 final_result='REVIEW'",
            "[PERF][scenario_summary] scenario=global_nav_main total_steps=1",
        ]
    )

    live = batch_runner._parse_live_log(log_text, scenario_ids=["global_nav_main"])

    assert live["current"]["current_scenario_id"] == "global_nav_main"
    assert live["current"]["current_scenario_state"] == "passed"
    assert live["current"]["current_step_index"] == 0
    assert live["current"]["current_step_label"] == "Home, Tab 1 of 5"
    assert live["current"]["current_step_action"] == "moved"
    assert live["current"]["current_step_target"] == "Home"
    assert live["current"]["current_step_result"] == "PASS"
    assert live["current"]["current_step_log"].startswith("[STEP] END")
    assert live["current"]["latest_step_log"].startswith("[STEP] END")
    assert live["current"]["latest_runtime_event"].startswith("[STEP] END")
    assert live["current"]["latest_scenario_event"] == "pass"
    assert live["progress"]["selected_scenarios"] == 1
    assert live["progress"]["observed_scenarios"] == 1
    assert live["progress"]["observed_runtime_events"] > 0
    assert live["progress"]["observed_steps"] == 1
    assert live["progress"]["total_scenarios"] == 1
    assert live["progress"]["completed_steps"] == 1
    assert live["progress"]["pass_count"] == 1
    assert live["progress"]["review_count"] == 1
    assert live["logs"]["latest_preflight_status"]["device_connected"] == "PASS"
    assert live["logs"]["latest_preflight_status"]["screen_awake"] == "PASS"
    assert live["logs"]["latest_preflight_status"]["unlock_swipe"] == "WARN"
    assert live["logs"]["latest_preflight_status"]["app_foreground"] == "PASS"
    assert live["logs"]["latest_preflight_status"]["helper"] == "PASS"
    assert live["logs"]["latest_preflight_status"]["talkback"] == "enabled"
    assert live["logs"]["latest_quality_event"] == "[QUALITY] step=0 final_result='REVIEW'"


def test_batch_status_includes_stable_live_dashboard_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(batch_runner, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")

    out_dir = tmp_path / "qa_frontend_runs" / "batch_20260603_010203" / "device_Model_SERIAL"
    out_dir.mkdir(parents=True)
    (out_dir / "runner.log").write_text(
        "\n".join(
            [
                "[PREFLIGHT] app_foreground PASS message='SmartThings foreground confirmed'",
                "[STEP] START scenario='global_nav_main' step=2 target='Menu' action='next'",
                "[STEP] END scenario='global_nav_main' step=2 visible='Menu' final_result='PASS'",
            ]
        ),
        encoding="utf-8",
    )

    manager = batch_runner.BatchRunManager()
    manager._batch_id = "batch_20260603_010203"
    manager._state = "running"
    manager._mode = "smoke"
    manager._created_at = "2026-06-03T01:02:03+00:00"
    manager._scenario_ids = ["global_nav_main"]
    manager._current_device_idx = 0
    manager._devices = [
        {
            "serial": "SERIAL",
            "model": "Model",
            "state": "running",
            "output_dir": "qa_frontend_runs/batch_20260603_010203/device_Model_SERIAL",
            "return_code": None,
            "started_at": "2026-06-03T01:02:04+00:00",
            "finished_at": None,
        }
    ]

    status = manager.get_status()

    assert status["batch"]["batch_id"] == "batch_20260603_010203"
    assert status["batch"]["state"] == "running"
    assert status["batch"]["total_devices"] == 1
    assert status["current"]["current_device_serial"] == "SERIAL"
    assert status["current"]["current_scenario_id"] == "global_nav_main"
    assert status["current"]["current_scenario_runtime_state"] == "running"
    assert status["current"]["current_step_index"] == 2
    assert status["current"]["current_step_label"] == "Menu"
    assert status["progress"]["completed_steps"] == 1
    assert status["logs"]["latest_log_line"].endswith("final_result='PASS'")
    assert status["devices"][0]["runner_log_path"].endswith("runner.log")


def test_parse_live_log_uses_step_bearing_non_step_lines_as_fallback():
    log_text = "\n".join(
        [
            "[SCENARIO][pre_nav] step=1 action=select_and_tap_bounds_center_adb target='Menu'",
            "[STOP][eval] step=1 scenario='global_nav_main' decision='continue' traversal_result='FAIL_STUCK' final_result='FAIL'",
        ]
    )

    live = batch_runner._parse_live_log(log_text, scenario_ids=["global_nav_main"])

    assert live["current"]["current_scenario_id"] == "global_nav_main"
    assert live["current"]["current_step_index"] == 1
    assert live["current"]["current_step_action"] == "select_and_tap_bounds_center_adb"
    assert live["current"]["current_step_target"] == "Menu"
    assert live["current"]["current_step_result"] == "FAIL"
    assert live["current"]["current_step_log"].startswith("[STOP][eval]")


def test_parse_live_log_counts_runtime_events_without_step_index():
    log_text = "\n".join(
        [
            "[SCENARIO][entry_contract] failed scenario='global_nav_main' entry_type='tab' reason='no_bottom_nav_candidates'",
            "[TAB][select] stabilization failed reason='no_bottom_nav_candidates'",
            "[SCENARIO][pre_nav] failed reason='action_failed'",
        ]
    )

    live = batch_runner._parse_live_log(log_text, scenario_ids=["global_nav_main"])

    assert live["progress"]["selected_scenarios"] == 1
    assert live["progress"]["observed_scenarios"] == 1
    assert live["progress"]["observed_runtime_events"] == 3
    assert live["progress"]["observed_steps"] == 0
    assert live["current"]["current_scenario_id"] == "global_nav_main"
    assert live["current"]["latest_scenario_event"] == "failed"
    assert "action_failed" in live["current"]["latest_runtime_event"]


def test_parse_live_log_excludes_disabled_config_scenarios_from_observed_count():
    log_text = "\n".join(
        [
            "[CONFIG] scenario enabled scenario='global_nav_main' source='runtime' base_enabled=True enabled=True",
            "[CONFIG] scenario enabled scenario='life_air_care_plugin' source='runtime' base_enabled=False enabled=False",
            "[CONFIG] scenario enabled scenario='device_tv_plugin' source='runtime' base_enabled=False enabled=False",
            "[SCENARIO][entry_contract] success scenario='global_nav_main' entry_type='tab'",
            "[STEP] END scenario='global_nav_main' step=0 visible='Home'",
        ]
    )

    live = batch_runner._parse_live_log(log_text, scenario_ids=["global_nav_main"])

    assert live["progress"]["selected_scenarios"] == 1
    assert live["progress"]["observed_scenarios"] == 1
    assert live["progress"]["total_scenarios"] == 1
