import time
from types import SimpleNamespace

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


def test_batch_status_accumulates_observed_scenarios_across_log_tails(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(batch_runner, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")

    out_dir = tmp_path / "qa_frontend_runs" / "batch_20260605_010203" / "device_Model_SERIAL"
    out_dir.mkdir(parents=True)
    log_path = out_dir / "runner.log"
    log_path.write_text("[STEP] END scenario='s1' step=0 visible='One' final_result='PASS'\n", encoding="utf-8")

    manager = batch_runner.BatchRunManager()
    manager._batch_id = "batch_20260605_010203"
    manager._state = "running"
    manager._mode = "full"
    manager._created_at = "2026-06-05T01:02:03+00:00"
    manager._scenario_ids = ["s1", "s2"]
    manager._current_device_idx = 0
    manager._devices = [
        {
            "serial": "SERIAL",
            "model": "Model",
            "state": "running",
            "output_dir": "qa_frontend_runs/batch_20260605_010203/device_Model_SERIAL",
            "return_code": None,
            "started_at": "2026-06-05T01:02:04+00:00",
            "finished_at": None,
            "observed_scenario_ids": [],
        }
    ]

    first_status = manager.get_status()
    assert first_status["progress"]["observed_scenarios"] == 1
    assert manager._devices[0]["observed_scenario_ids"] == ["s1"]

    log_path.write_text("[STEP] END scenario='s2' step=0 visible='Two' final_result='PASS'\n", encoding="utf-8")

    second_status = manager.get_status()
    assert second_status["progress"]["observed_scenarios"] == 2
    assert second_status["progress"]["selected_scenarios"] == 2
    assert manager._devices[0]["observed_scenario_ids"] == ["s1", "s2"]


def test_finished_batch_status_uses_last_device_progress_after_current_device_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(batch_runner, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")

    out_dir = tmp_path / "qa_frontend_runs" / "batch_20260605_020304" / "device_Model_SERIAL"
    out_dir.mkdir(parents=True)
    (out_dir / "runner.log").write_text(
        "[STEP] END scenario='s2' step=0 visible='Two' final_result='PASS'\n",
        encoding="utf-8",
    )

    manager = batch_runner.BatchRunManager()
    manager._batch_id = "batch_20260605_020304"
    manager._state = "finished"
    manager._mode = "full"
    manager._created_at = "2026-06-05T02:03:04+00:00"
    manager._scenario_ids = ["s1", "s2"]
    manager._current_device_idx = 1
    manager._devices = [
        {
            "serial": "SERIAL",
            "model": "Model",
            "state": "passed",
            "output_dir": "qa_frontend_runs/batch_20260605_020304/device_Model_SERIAL",
            "return_code": 0,
            "started_at": "2026-06-05T02:03:05+00:00",
            "finished_at": "2026-06-05T02:04:05+00:00",
            "observed_scenario_ids": ["s1", "s2"],
        }
    ]

    status = manager.get_status()

    assert status["current"]["current_device_serial"] == "SERIAL"
    assert status["progress"]["observed_scenarios"] == 2
    assert status["progress"]["selected_scenarios"] == 2


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


def test_parse_live_log_separates_smart_navigation_result_from_final_result():
    log_text = "\n".join(
        [
            "[STEP][smart_next_trace] step=3 scenario='global_nav_main' last_smart_nav_result='failed' last_smart_nav_detail='reached_end'",
        ]
    )

    live = batch_runner._parse_live_log(log_text, scenario_ids=["global_nav_main"])

    assert live["current"]["current_step_index"] == 3
    assert live["current"]["current_step_result"] is None
    assert live["current"]["current_navigation_result"] == "failed"
    assert live["current"]["current_navigation_detail"] == "reached_end"


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


def test_batch_run_manager_restores_sleep_prevention_after_device_run(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(batch_runner, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")
    monkeypatch.setattr(batch_runner, "RUNTIME_CONFIG_PATH", tmp_path / "runtime_config.json")
    monkeypatch.setattr(batch_runner, "enable_sleep_prevention", lambda: calls.append("enable"))
    monkeypatch.setattr(batch_runner, "disable_sleep_prevention", lambda: calls.append("disable"))
    monkeypatch.setattr(batch_runner, "start_crash_logcat_capture", lambda **kwargs: None)
    monkeypatch.setattr(batch_runner, "stop_crash_logcat_capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        batch_runner,
        "write_selected_runtime_config",
        lambda **kwargs: {
            "path": tmp_path / "runtime_config.json",
            "enabled_ids": ["global_nav_main"],
            "max_steps_policy": "smoke_override",
            "scenario_steps": [],
        },
    )
    monkeypatch.setattr(
        batch_runner,
        "prepare_runtime",
        lambda spec, language_fn, preflight_fn: (
            {"ok": True, "status": "ok", "language_mode": "current"},
            {"ok": True, "state": "passed", "reason": "ok"},
        ),
    )
    monkeypatch.setattr(batch_runner, "start_execution", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(batch_runner, "wait_for_execution", lambda execution: 0)
    monkeypatch.setattr(batch_runner, "close_execution_log", lambda execution: None)
    monkeypatch.setattr(batch_runner.BatchRunManager, "_write_device_summary", lambda *args, **kwargs: None)

    manager = batch_runner.BatchRunManager()
    manager.start_batch(
        devices=[{"serial": "SERIAL", "model": "Model"}],
        mode="smoke",
        scenario_ids=["global_nav_main"],
    )

    deadline = time.time() + 1.0
    status = manager.get_status()
    while status["state"] == "running" and time.time() < deadline:
        time.sleep(0.01)
        status = manager.get_status()

    assert status["state"] == "finished"
    assert calls == ["enable", "disable"]


class _StopFakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self._done = False

    def poll(self):
        return 0 if self._done else None

    def terminate(self):
        self.terminated = True
        self._done = True

    def kill(self):
        self.killed = True
        self._done = True

    def wait(self, timeout=None):
        self._done = True
        return 0


class _TimeoutThenKillProcess(_StopFakeProcess):
    def __init__(self):
        super().__init__()
        self._wait_calls = 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls == 1:
            raise batch_runner.subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        self._done = True
        return 0


class _BlockingFakeProcess(_StopFakeProcess):
    def __init__(self):
        super().__init__()
        import threading

        self._event = threading.Event()

    def terminate(self):
        self.terminated = True
        self._done = True
        self._event.set()

    def kill(self):
        self.killed = True
        self._done = True
        self._event.set()

    def wait(self, timeout=None):
        if timeout is not None and not self._event.wait(timeout):
            raise batch_runner.subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        self._event.wait()
        return 0


def test_batch_stop_terminates_current_process():
    process = _StopFakeProcess()
    manager = batch_runner.BatchRunManager()
    manager._state = "running"
    manager._current_execution = SimpleNamespace(process=process)

    status = manager.stop_batch()

    assert process.terminated is True
    assert process.killed is False
    assert status["state"] == "stopped"


def test_batch_stop_kills_process_after_terminate_timeout():
    process = _TimeoutThenKillProcess()
    manager = batch_runner.BatchRunManager()
    manager._state = "running"
    manager._current_execution = SimpleNamespace(process=process)

    status = manager.stop_batch()

    assert process.terminated is True
    assert process.killed is True
    assert status["state"] == "stopped"


def test_batch_stop_when_not_running_is_noop():
    manager = batch_runner.BatchRunManager()

    status = manager.stop_batch()

    assert status["state"] == "idle"


def test_batch_stop_stops_current_process_and_does_not_start_next_device(tmp_path, monkeypatch):
    calls = []
    process = _BlockingFakeProcess()

    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(batch_runner, "RUN_LOG_DIR", tmp_path / "qa_frontend_runs")
    monkeypatch.setattr(batch_runner, "RUNTIME_CONFIG_PATH", tmp_path / "runtime_config.json")
    monkeypatch.setattr(batch_runner, "enable_sleep_prevention", lambda: calls.append("enable"))
    monkeypatch.setattr(batch_runner, "disable_sleep_prevention", lambda: calls.append("disable"))
    monkeypatch.setattr(batch_runner, "start_crash_logcat_capture", lambda **kwargs: None)
    monkeypatch.setattr(batch_runner, "stop_crash_logcat_capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        batch_runner,
        "write_selected_runtime_config",
        lambda **kwargs: {
            "path": tmp_path / "runtime_config.json",
            "enabled_ids": ["global_nav_main"],
            "max_steps_policy": "smoke_override",
            "scenario_steps": [],
        },
    )
    monkeypatch.setattr(
        batch_runner,
        "prepare_runtime",
        lambda spec, language_fn, preflight_fn: (
            {"ok": True, "status": "ok", "language_mode": "current"},
            {"ok": True, "state": "passed", "reason": "ok"},
        ),
    )

    started = []

    def fake_start_execution(**kwargs):
        started.append(kwargs["spec"].serial)
        return SimpleNamespace(process=process)

    monkeypatch.setattr(batch_runner, "start_execution", fake_start_execution)
    monkeypatch.setattr(batch_runner, "wait_for_execution", lambda execution: execution.process.wait())
    monkeypatch.setattr(batch_runner, "close_execution_log", lambda execution: None)
    monkeypatch.setattr(batch_runner.BatchRunManager, "_write_device_summary", lambda *args, **kwargs: None)

    manager = batch_runner.BatchRunManager()
    manager.start_batch(
        devices=[
            {"serial": "SERIAL1", "model": "Model1"},
            {"serial": "SERIAL2", "model": "Model2"},
        ],
        mode="smoke",
        scenario_ids=["global_nav_main"],
    )

    deadline = time.time() + 1.0
    while not started and time.time() < deadline:
        time.sleep(0.01)

    status = manager.stop_batch()
    deadline = time.time() + 1.0
    while manager._worker_thread and manager._worker_thread.is_alive() and time.time() < deadline:
        time.sleep(0.01)

    assert status["state"] == "stopped"
    assert process.terminated is True
    assert started == ["SERIAL1"]
    assert manager.get_status()["state"] == "stopped"
    assert calls == ["enable", "disable"]
