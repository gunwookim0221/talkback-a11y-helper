from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from qa_frontend.backend.main import StartRunRequest
from qa_frontend.backend.runner import RunManager


class _RunningProcess:
    def poll(self):
        return None


class _FakeStdout:
    def __iter__(self):
        return iter(())


class _FakeProcess:
    stdout = _FakeStdout()
    returncode = 0

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


def _language_ok(language_mode="current", device_locale="en-US"):
    return {
        "ok": True,
        "status": "ok",
        "language_mode": language_mode,
        "device_locale": device_locale,
        "changed": False,
        "verified": True,
    }


def _wait_until_not_running(manager: RunManager, timeout: float = 1.0) -> dict[str, object]:
    deadline = time.time() + timeout
    state = manager.get_status()
    while state["state"] == "running" and time.time() < deadline:
        time.sleep(0.01)
        state = manager.get_status()
    return state


def test_run_manager_initial_state_is_idle():
    state = RunManager().get_status()

    assert state["state"] == "idle"
    assert state["run_id"] is None
    assert state["mode"] is None
    assert state["log_path"] is None
    assert state["scenario_ids"] == []
    assert state["scenario_selection_applied"] is False
    assert state["runtime_config_path"] is None
    assert state["launch_mode"] == "clean"
    assert state["language_mode"] == "current"
    assert state["device_locale"] is None
    assert state["preflight_state"] is None


def test_start_run_request_defaults_launch_mode_to_clean():
    request = StartRunRequest()

    assert request.launch_mode == "clean"
    assert request.language_mode == "current"


def test_run_manager_rejects_start_when_process_is_already_running():
    manager = RunManager()
    manager._process = _RunningProcess()
    manager._state = "running"

    with pytest.raises(RuntimeError, match="already in progress"):
        manager.start_run(mode="smoke")


def test_run_manager_blocks_when_preflight_blocks(monkeypatch):
    blocked = {
        "ok": False,
        "state": "blocked",
        "reason": "talkback_disabled",
        "launch_mode": "warm",
        "adb_state": "ok",
        "helper_state": "ok",
        "talkback_state": "disabled",
        "foreground_package": None,
        "accessibility_settings_opened": True,
        "user_message": "TalkBack is disabled. Accessibility settings opened on device. Please enable TalkBack and retry.",
    }

    monkeypatch.setattr("qa_frontend.backend.runner.apply_language_mode", lambda language_mode: _language_ok(language_mode))
    monkeypatch.setattr("qa_frontend.backend.runner.run_runtime_preflight", lambda launch_mode: blocked)

    state = RunManager().start_run(mode="smoke", scenario_ids=["global_nav_main"], launch_mode="warm", language_mode="ko-KR")

    assert state["state"] == "error"
    assert state["language_mode"] == "ko-KR"
    assert state["device_locale"] == "en-US"
    assert state["preflight_state"] == "blocked"
    assert state["preflight_reason"] == "talkback_disabled"
    assert state["talkback_state"] == "disabled"
    assert state["accessibility_settings_opened"] is True
    assert "Please enable TalkBack and retry" in str(state["error"])


def test_run_manager_blocks_when_no_scenario_selected(tmp_path, monkeypatch):
    monkeypatch.setattr("qa_frontend.backend.runner.RUN_LOG_DIR", tmp_path / "runs")

    state = RunManager().start_run(mode="smoke", scenario_ids=[], launch_mode="warm")

    assert state["state"] == "error"
    assert state["error"] == "No scenario selected"
    assert state["scenario_selection_applied"] is False
    summary_path = tmp_path / "runs" / f"{state['run_id']}_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["schema_version"] == 1
    assert summary["process_status"] == "failed"
    assert summary["scenario_result_status"] == "unknown"


def test_run_manager_blocks_when_language_verify_fails(tmp_path, monkeypatch):
    source_path = tmp_path / "runtime_config.json"
    source_path.write_text(
        json.dumps({"scenarios": {"global_nav_main": {"enabled": False, "max_steps": 10}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    language_error = {
        "ok": False,
        "status": "error",
        "language_mode": "en-US",
        "device_locale": "ko-KR",
        "target_locale": "en-US",
        "verified": False,
        "manual_language_change_required": True,
        "settings_intent": "android.settings.LOCALE_SETTINGS",
        "error": "device locale did not verify as en-US",
    }

    monkeypatch.setattr("qa_frontend.backend.runner.RUNTIME_CONFIG_PATH", source_path)
    monkeypatch.setattr("qa_frontend.backend.runner.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("qa_frontend.backend.runner.apply_language_mode", lambda language_mode: language_error)

    state = RunManager().start_run(mode="smoke", scenario_ids=["global_nav_main"], language_mode="en-US")

    assert state["state"] == "error"
    assert state["language_mode"] == "en-US"
    assert state["device_locale"] == "ko-KR"
    assert state["target_locale"] == "en-US"
    assert state["manual_language_change_required"] is True
    assert state["language_error"] == "device locale did not verify as en-US"
    assert state["language_settings_intent"] == "android.settings.LOCALE_SETTINGS"
    assert "device locale did not verify" in str(state["error"])
    log_text = (tmp_path / "runs" / f"{state['run_id']}_smoke.log").read_text(encoding="utf-8")
    assert "[QA_FRONTEND][language]" in log_text
    assert "verified='false'" in log_text


def test_run_manager_writes_selected_runtime_config_and_env_without_mutating_source(tmp_path, monkeypatch):
    source_path = tmp_path / "runtime_config.json"
    source = {
        "scenarios": {
            "global_nav_main": {"enabled": False, "max_steps": 10},
            "life_family_care_plugin": {"enabled": True, "max_steps": 50},
        }
    }
    source_text = json.dumps(source, ensure_ascii=False, indent=2)
    source_path.write_text(source_text, encoding="utf-8")
    captured = {}
    passed = {
        "ok": True,
        "state": "passed",
        "reason": "ok",
        "launch_mode": "warm",
        "adb_state": "ok",
        "helper_state": "ok",
        "talkback_state": "enabled",
        "foreground_package": "com.samsung.android.oneconnect",
        "accessibility_settings_opened": False,
    }

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env")
        return _FakeProcess()

    monkeypatch.setattr("qa_frontend.backend.runner.RUNTIME_CONFIG_PATH", source_path)
    monkeypatch.setattr("qa_frontend.backend.runner.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("qa_frontend.backend.runner.apply_language_mode", lambda language_mode: _language_ok(language_mode, "ko-KR"))
    monkeypatch.setattr("qa_frontend.backend.runner.run_runtime_preflight", lambda launch_mode: passed)
    monkeypatch.setattr("qa_frontend.backend.runner.subprocess.Popen", fake_popen)

    state = RunManager().start_run(mode="smoke", scenario_ids=["global_nav_main"], launch_mode="warm", language_mode="ko-KR")

    assert state["scenario_selection_applied"] is True
    assert state["language_mode"] == "ko-KR"
    assert state["device_locale"] == "ko-KR"
    assert state["runtime_config_path"]
    assert state["max_steps_policy"] == "smoke_override"
    assert captured["env"]["TB_RUNTIME_CONFIG_PATH"] == state["runtime_config_path"]
    assert source_path.read_text(encoding="utf-8") == source_text

    selected_config = json.loads(Path(str(state["runtime_config_path"])).read_text(encoding="utf-8"))
    assert selected_config["scenarios"]["global_nav_main"]["enabled"] is True
    assert selected_config["scenarios"]["global_nav_main"]["max_steps"] == 6
    assert selected_config["scenarios"]["life_family_care_plugin"]["enabled"] is False
    assert selected_config["scenarios"]["life_family_care_plugin"]["max_steps"] == 50
    assert state["scenario_steps"]
    assert state["scenario_steps"][0]["scenario"] == "global_nav_main"
    assert state["scenario_steps"][0]["effective_max_steps"] == 6

    log_text = (tmp_path / "runs" / f"{state['run_id']}_smoke.log").read_text(encoding="utf-8")
    assert "scenario_selection_applied=true" in log_text
    assert "language_mode='ko-KR'" in log_text
    assert "[QA_FRONTEND][language]" in log_text
    assert str(state["runtime_config_path"]) in log_text
    assert "[QA_FRONTEND][runtime_config]" in log_text
    assert "max_steps_policy='smoke_override'" in log_text
    assert "scenario='global_nav_main'" in log_text
    assert "original_max_steps=10" in log_text
    assert "effective_max_steps=6" in log_text


def test_run_manager_restores_sleep_prevention_after_success(tmp_path, monkeypatch):
    source_path = tmp_path / "runtime_config.json"
    source_path.write_text(
        json.dumps({"scenarios": {"global_nav_main": {"enabled": False, "max_steps": 10}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    passed = {
        "ok": True,
        "state": "passed",
        "reason": "ok",
        "launch_mode": "warm",
        "adb_state": "ok",
        "helper_state": "ok",
        "talkback_state": "enabled",
        "foreground_package": "com.samsung.android.oneconnect",
        "accessibility_settings_opened": False,
    }
    calls = []

    monkeypatch.setattr("qa_frontend.backend.runner.RUNTIME_CONFIG_PATH", source_path)
    monkeypatch.setattr("qa_frontend.backend.runner.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("qa_frontend.backend.runner.apply_language_mode", lambda language_mode: _language_ok(language_mode))
    monkeypatch.setattr("qa_frontend.backend.runner.run_runtime_preflight", lambda launch_mode: passed)
    monkeypatch.setattr("qa_frontend.backend.runner.subprocess.Popen", lambda *args, **kwargs: _FakeProcess())
    monkeypatch.setattr("qa_frontend.backend.runner.enable_sleep_prevention", lambda: calls.append("enable"))
    monkeypatch.setattr("qa_frontend.backend.runner.disable_sleep_prevention", lambda: calls.append("disable"))

    manager = RunManager()
    state = manager.start_run(mode="smoke", scenario_ids=["global_nav_main"], launch_mode="warm")
    assert state["state"] == "running"

    final_state = _wait_until_not_running(manager)

    assert final_state["state"] == "finished"
    assert calls == ["enable", "disable"]


def test_run_manager_restores_sleep_prevention_when_preflight_blocks(tmp_path, monkeypatch):
    source_path = tmp_path / "runtime_config.json"
    source_path.write_text(
        json.dumps({"scenarios": {"global_nav_main": {"enabled": False, "max_steps": 10}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    blocked = {
        "ok": False,
        "state": "blocked",
        "reason": "talkback_disabled",
        "launch_mode": "warm",
        "adb_state": "ok",
        "helper_state": "ok",
        "talkback_state": "disabled",
        "foreground_package": None,
        "accessibility_settings_opened": True,
        "user_message": "TalkBack is disabled.",
    }
    calls = []

    monkeypatch.setattr("qa_frontend.backend.runner.RUNTIME_CONFIG_PATH", source_path)
    monkeypatch.setattr("qa_frontend.backend.runner.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("qa_frontend.backend.runner.apply_language_mode", lambda language_mode: _language_ok(language_mode))
    monkeypatch.setattr("qa_frontend.backend.runner.run_runtime_preflight", lambda launch_mode: blocked)
    monkeypatch.setattr("qa_frontend.backend.runner.enable_sleep_prevention", lambda: calls.append("enable"))
    monkeypatch.setattr("qa_frontend.backend.runner.disable_sleep_prevention", lambda: calls.append("disable"))

    state = RunManager().start_run(mode="smoke", scenario_ids=["global_nav_main"], launch_mode="warm")

    assert state["state"] == "error"
    assert state["preflight_state"] == "blocked"
    assert calls == ["enable", "disable"]


def test_run_manager_restores_sleep_prevention_when_waiter_thread_start_fails(tmp_path, monkeypatch):
    source_path = tmp_path / "runtime_config.json"
    source_path.write_text(
        json.dumps({"scenarios": {"global_nav_main": {"enabled": False, "max_steps": 10}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    passed = {
        "ok": True,
        "state": "passed",
        "reason": "ok",
        "launch_mode": "warm",
        "adb_state": "ok",
        "helper_state": "ok",
        "talkback_state": "enabled",
        "foreground_package": "com.samsung.android.oneconnect",
        "accessibility_settings_opened": False,
    }
    calls = []

    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    monkeypatch.setattr("qa_frontend.backend.runner.RUNTIME_CONFIG_PATH", source_path)
    monkeypatch.setattr("qa_frontend.backend.runner.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("qa_frontend.backend.runner.apply_language_mode", lambda language_mode: _language_ok(language_mode))
    monkeypatch.setattr("qa_frontend.backend.runner.run_runtime_preflight", lambda launch_mode: passed)
    monkeypatch.setattr("qa_frontend.backend.runner.subprocess.Popen", lambda *args, **kwargs: _FakeProcess())
    monkeypatch.setattr("qa_frontend.backend.runner.threading.Thread", FailingThread)
    monkeypatch.setattr("qa_frontend.backend.runner.enable_sleep_prevention", lambda: calls.append("enable"))
    monkeypatch.setattr("qa_frontend.backend.runner.disable_sleep_prevention", lambda: calls.append("disable"))

    manager = RunManager()

    with pytest.raises(RuntimeError, match="thread start failed"):
        manager.start_run(mode="smoke", scenario_ids=["global_nav_main"], launch_mode="warm")

    assert manager.get_status()["state"] == "error"
    assert calls == ["enable", "disable"]


def test_run_manager_uses_clean_launch_mode_when_omitted(tmp_path, monkeypatch):
    source_path = tmp_path / "runtime_config.json"
    source_path.write_text(
        json.dumps({"scenarios": {"global_nav_main": {"enabled": False, "max_steps": 10}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    captured = {}
    passed = {
        "ok": True,
        "state": "passed",
        "reason": "ok",
        "launch_mode": "clean",
        "adb_state": "ok",
        "helper_state": "ok",
        "talkback_state": "enabled",
        "foreground_package": "com.samsung.android.oneconnect",
        "accessibility_settings_opened": False,
    }

    def fake_popen(command, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeProcess()

    monkeypatch.setattr("qa_frontend.backend.runner.RUNTIME_CONFIG_PATH", source_path)
    monkeypatch.setattr("qa_frontend.backend.runner.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("qa_frontend.backend.runner.apply_language_mode", lambda language_mode: _language_ok(language_mode, "en-US"))
    monkeypatch.setattr("qa_frontend.backend.runner.run_runtime_preflight", lambda launch_mode: {**passed, "launch_mode": launch_mode})
    monkeypatch.setattr("qa_frontend.backend.runner.subprocess.Popen", fake_popen)

    state = RunManager().start_run(mode="smoke", scenario_ids=["global_nav_main"])

    assert state["launch_mode"] == "clean"
    assert state["language_mode"] == "current"
    assert state["device_locale"] == "en-US"
    assert state["preflight"]["launch_mode"] == "clean"
    assert captured["env"]["TB_RUNTIME_CONFIG_PATH"] == state["runtime_config_path"]


def test_run_manager_full_mode_preserves_source_max_steps(tmp_path, monkeypatch):
    source_path = tmp_path / "runtime_config.json"
    source = {
        "scenarios": {
            "life_family_care_plugin": {"enabled": True, "max_steps": 50},
            "device_smoke_sensor_plugin": {"enabled": True, "max_steps": 30},
        }
    }
    source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
    captured = {}
    passed = {
        "ok": True,
        "state": "passed",
        "reason": "ok",
        "launch_mode": "warm",
        "adb_state": "ok",
        "helper_state": "ok",
        "talkback_state": "enabled",
        "foreground_package": "com.samsung.android.oneconnect",
        "accessibility_settings_opened": False,
    }

    def fake_popen(command, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeProcess()

    monkeypatch.setattr("qa_frontend.backend.runner.RUNTIME_CONFIG_PATH", source_path)
    monkeypatch.setattr("qa_frontend.backend.runner.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("qa_frontend.backend.runner.apply_language_mode", lambda language_mode: _language_ok(language_mode, "en-US"))
    monkeypatch.setattr("qa_frontend.backend.runner.run_runtime_preflight", lambda launch_mode: passed)
    monkeypatch.setattr("qa_frontend.backend.runner.subprocess.Popen", fake_popen)

    state = RunManager().start_run(mode="full", scenario_ids=["life_family_care_plugin"], launch_mode="warm")

    selected_config = json.loads(Path(str(state["runtime_config_path"])).read_text(encoding="utf-8"))
    assert selected_config["scenarios"]["life_family_care_plugin"]["enabled"] is True
    assert selected_config["scenarios"]["life_family_care_plugin"]["max_steps"] == 50
    assert selected_config["scenarios"]["device_smoke_sensor_plugin"]["enabled"] is False
    assert selected_config["scenarios"]["device_smoke_sensor_plugin"]["max_steps"] == 30
    assert state["max_steps_policy"] == "source_preserved"
    assert captured["env"]["TB_RUNTIME_CONFIG_PATH"] == state["runtime_config_path"]

    log_text = (tmp_path / "runs" / f"{state['run_id']}_full.log").read_text(encoding="utf-8")
    assert "max_steps_policy='source_preserved'" in log_text
    assert "effective_max_steps=50" in log_text
