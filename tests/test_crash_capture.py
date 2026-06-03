from __future__ import annotations

import json
import subprocess

from qa_frontend.backend.crash_capture import (
    CrashEvent,
    CrashEventStore,
    LogcatCapture,
    OneConnectCrashDetector,
    _render_repro_guide,
    capture_crash_context,
    start_crash_logcat_capture,
)


CRASH_LINES = [
    "06-03 19:42:11.111 12345 12345 E AndroidRuntime: FATAL EXCEPTION: main\n",
    "06-03 19:42:11.112 12345 12345 E AndroidRuntime: Process: com.samsung.android.oneconnect, PID: 12345\n",
    "06-03 19:42:11.113 12345 12345 E AndroidRuntime: java.lang.NullPointerException: boom\n",
    "06-03 19:42:11.114 12345 12345 E AndroidRuntime: \tat com.samsung.android.oneconnect.HomeMonitorActivity.onCreate(HomeMonitorActivity.kt:12)\n",
    "06-03 19:42:11.115 12345 12345 I ActivityTaskManager: unrelated next line\n",
]


class _Stdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)


class _FakeLogcatProcess:
    def __init__(self, lines):
        self.stdout = _Stdout(lines)
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


def _ok_context_run_factory(command, **kwargs):
    if command[-3:] == ["exec-out", "screencap", "-p"]:
        return subprocess.CompletedProcess(command, 0, stdout=b"\x89PNG\r\n\x1a\n", stderr=b"")
    if "uiautomator" in command:
        return subprocess.CompletedProcess(command, 0, stdout="UI hierchary dumped to: /sdcard/window.xml")
    if "cat" in command:
        return subprocess.CompletedProcess(command, 0, stdout="<hierarchy package=\"com.samsung.android.oneconnect\" />")
    if "dumpsys" in command:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="mCurrentFocus=Window{abc u0 com.sec.android.app.launcher/com.sec.android.app.launcher.Launcher}",
        )
    return subprocess.CompletedProcess(command, 0, stdout="")


def _helper_dump(serial):
    return {"nodes": [{"text": "Home Monitor", "packageName": "com.samsung.android.oneconnect"}], "serial": serial}


def test_detector_stores_confirmed_oneconnect_crash_event(tmp_path):
    log_path = tmp_path / "runner.log"
    log_path.write_text(
        "[STEP] END scenario='life_home_monitor_plugin' step=7 visible='Home Monitor' "
        "action='tap' target='Home Monitor' merged_announcement='Home Monitor, button'\n",
        encoding="utf-8",
    )
    store = CrashEventStore(
        tmp_path,
        serial="SERIAL",
        runner_log_path=log_path,
        run_factory=_ok_context_run_factory,
        helper_dump_factory=_helper_dump,
    )
    detector = OneConnectCrashDetector(store)

    events = []
    for line in CRASH_LINES:
        events.extend(detector.feed_line(line))
    events.extend(detector.finish())

    assert len(events) == 1
    event = events[0]
    assert event.crash_event_id == "CRASH-0001"
    assert event.crash_type == "CONFIRMED_CRASH"
    assert event.process == "com.samsung.android.oneconnect"
    assert event.exception == "java.lang.NullPointerException: boom"
    assert event.top_frame == "com.samsung.android.oneconnect.HomeMonitorActivity.onCreate(HomeMonitorActivity.kt:12)"
    assert event.timestamp == "06-03 19:42:11.111"

    event_dir = tmp_path / "crashes" / "CRASH-0001"
    payload = json.loads((event_dir / "crash_event.json").read_text(encoding="utf-8"))
    assert payload == {
        "crash_event_id": "CRASH-0001",
        "crash_type": "CONFIRMED_CRASH",
        "process": "com.samsung.android.oneconnect",
        "exception": "java.lang.NullPointerException: boom",
        "top_frame": "com.samsung.android.oneconnect.HomeMonitorActivity.onCreate(HomeMonitorActivity.kt:12)",
        "timestamp": "06-03 19:42:11.111",
    }
    assert "FATAL EXCEPTION" in (event_dir / "logcat_excerpt.txt").read_text(encoding="utf-8")
    assert (event_dir / "crash_context.json").is_file()
    assert (event_dir / "crash_repro.md").is_file()
    assert (event_dir / "crash_screenshot.png").is_file()
    assert (event_dir / "crash_window_dump.xml").is_file()
    assert (event_dir / "crash_helper_dump.json").is_file()
    assert (event_dir / "focus_state.json").is_file()


def test_detector_ignores_non_oneconnect_fatal_exception(tmp_path):
    store = CrashEventStore(tmp_path, run_factory=_ok_context_run_factory, helper_dump_factory=_helper_dump)
    detector = OneConnectCrashDetector(store)

    lines = [
        "06-03 19:42:11.111 12345 12345 E AndroidRuntime: FATAL EXCEPTION: main\n",
        "06-03 19:42:11.112 12345 12345 E AndroidRuntime: Process: com.example.other, PID: 12345\n",
        "06-03 19:42:11.113 12345 12345 E AndroidRuntime: java.lang.IllegalStateException: other\n",
        "06-03 19:42:11.114 12345 12345 I ActivityTaskManager: unrelated next line\n",
    ]

    events = []
    for line in lines:
        events.extend(detector.feed_line(line))
    events.extend(detector.finish())

    assert events == []
    assert not (tmp_path / "crashes").exists()


def test_logcat_capture_writes_full_logcat_and_crash_artifacts(tmp_path):
    process = _FakeLogcatProcess(CRASH_LINES)
    commands = []

    def popen_factory(command, **kwargs):
        commands.append(command)
        return process

    capture = LogcatCapture(
        serial="SERIAL",
        output_dir=tmp_path,
        popen_factory=popen_factory,
        run_factory=_ok_context_run_factory,
        helper_dump_factory=_helper_dump,
    )
    capture.start()
    events = capture.stop()

    assert commands == [["adb", "-s", "SERIAL", "logcat", "-v", "threadtime"]]
    assert process.terminated is True
    assert len(events) == 1
    assert "Process: com.samsung.android.oneconnect" in (tmp_path / "logcat.txt").read_text(encoding="utf-8")
    assert (tmp_path / "crashes" / "CRASH-0001" / "crash_event.json").is_file()
    assert (tmp_path / "crashes" / "CRASH-0001" / "logcat_excerpt.txt").is_file()
    assert (tmp_path / "crashes" / "CRASH-0001" / "crash_context.json").is_file()


def test_start_capture_clears_logcat_before_background_capture(tmp_path):
    calls = []
    logs = []
    process = _FakeLogcatProcess([])

    def run_factory(command, **kwargs):
        calls.append(command)
        if command[-3:] == ["exec-out", "screencap", "-p"]:
            return subprocess.CompletedProcess(command, 0, stdout=b"\x89PNG\r\n\x1a\n", stderr=b"")
        return subprocess.CompletedProcess(command, 0, stdout="")

    def popen_factory(command, **kwargs):
        calls.append(command)
        return process

    capture = start_crash_logcat_capture(
        serial="SERIAL",
        output_dir=tmp_path,
        log_writer=logs.append,
        run_factory=run_factory,
        popen_factory=popen_factory,
        helper_dump_factory=_helper_dump,
    )

    assert capture is not None
    capture.stop()
    assert calls[0] == ["adb", "-s", "SERIAL", "logcat", "-c"]
    assert calls[1] == ["adb", "-s", "SERIAL", "logcat", "-v", "threadtime"]
    assert logs[0] == "[CRASH_CAPTURE] logcat_clear returncode=0"


def test_context_artifacts_include_minimum_schema_and_repro(tmp_path):
    event = _event()
    log_path = tmp_path / "runner.log"
    log_path.write_text(
        "[STEP] END scenario='life_home_monitor_plugin' step=7 visible='Home Monitor' "
        "action='tap' target='Home Monitor' merged_announcement='Home Monitor, button'\n",
        encoding="utf-8",
    )

    context = capture_crash_context(
        event=event,
        event_dir=tmp_path / "crashes" / "CRASH-0001",
        output_dir=tmp_path,
        serial="SERIAL",
        runner_log_path=log_path,
        run_factory=_ok_context_run_factory,
        helper_dump_factory=_helper_dump,
    )

    event_dir = tmp_path / "crashes" / "CRASH-0001"
    payload = json.loads((event_dir / "crash_context.json").read_text(encoding="utf-8"))
    assert context["crash_event_id"] == "CRASH-0001"
    assert payload["schema_version"] == 1
    assert payload["device_id"] == "SERIAL"
    assert payload["package"] == "com.samsung.android.oneconnect"
    assert payload["crash_type"] == "CONFIRMED_CRASH"
    assert payload["confidence"] == "high"
    assert payload["scenario"]["name"] == "life_home_monitor_plugin"
    assert payload["step"]["index"] == 7
    assert payload["last_action"]["type"] == "tap"
    assert payload["artifacts"]["screenshot"] == "crashes/CRASH-0001/crash_screenshot.png"
    assert payload["recovery"]["decision"] == "capture_only"
    assert payload["capture_errors"] == {}

    repro = (event_dir / "crash_repro.md").read_text(encoding="utf-8")
    assert "# Manual Repro Guide" in repro
    assert "Scenario: life_home_monitor_plugin" in repro
    assert "## Crash Evidence" in repro


def test_repro_guide_formatting_confirmed_crash():
    context = {"crash_type": "CONFIRMED_CRASH"}
    repro = _render_repro_guide(context)
    assert "Verify that SmartThings displays a crash dialog or terminates with a FATAL EXCEPTION." in repro
    assert "SmartThings 크래시 발생" in repro


def test_repro_guide_formatting_app_terminated():
    context = {"crash_type": "APP_TERMINATED"}
    repro = _render_repro_guide(context)
    assert "Verify that SmartThings leaves the foreground and Android Launcher becomes visible." in repro
    assert "Android Launcher로 이동" in repro


def test_repro_guide_formatting_possible_crash():
    context = {"crash_type": "POSSIBLE_CRASH"}
    repro = _render_repro_guide(context)
    assert "Verify that SmartThings unexpectedly leaves the expected screen or foreground." in repro
    assert "예상 화면 이탈" in repro


def test_repro_guide_action_formatting_dict():
    context = {"last_action": {"type": "click", "label": "Button"}}
    repro = _render_repro_guide(context)
    assert "Activate the focused item using TalkBack double tap" in repro
    assert '"type": "click"' in repro  # Should be in Raw Context


def test_repro_guide_action_formatting_null():
    context = {"last_action": None}
    repro = _render_repro_guide(context)
    assert "Repeat the last recorded TalkBack navigation action" in repro
    assert "null" in repro  # Should be in Raw Context


def test_repro_guide_korean_summary():
    context = {
        "scenario": {"name": "test_scenario"},
        "last_focus_label": "Test Item",
        "last_speech": "Test Speech",
        "last_visible_text": ["Test Visible"],
        "crash_type": "APP_TERMINATED"
    }
    repro = _render_repro_guide(context)
    assert "# 재현 가이드 요약 (Korean)" in repro
    assert "시나리오: test_scenario" in repro
    assert "마지막 포커스: Test Item" in repro
    assert "마지막 표시 텍스트: Test Visible" in repro


def test_repro_guide_screenshot_filename():
    context = {"artifacts": {"screenshot": "crashes/CRASH-0001/crash_screenshot.png"}}
    repro = _render_repro_guide(context)
    assert "Reference Screenshot:" in repro
    assert "crash_screenshot.png" in repro


def test_repro_guide_resource_mapping():
    context = {"last_action": {"resource": "folder_icon_view"}, "last_focus_label": "Samsung"}
    repro = _render_repro_guide(context)
    assert 'Move TalkBack focus to folder "Samsung".' in repro


def test_context_is_created_when_screenshot_capture_fails(tmp_path):
    def failing_screenshot_run_factory(command, **kwargs):
        if command[-3:] == ["exec-out", "screencap", "-p"]:
            return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"screencap failed")
        return _ok_context_run_factory(command, **kwargs)

    capture_crash_context(
        event=_event(),
        event_dir=tmp_path / "crashes" / "CRASH-0001",
        output_dir=tmp_path,
        serial="SERIAL",
        runner_log_path=None,
        run_factory=failing_screenshot_run_factory,
        helper_dump_factory=_helper_dump,
    )

    payload = json.loads((tmp_path / "crashes" / "CRASH-0001" / "crash_context.json").read_text(encoding="utf-8"))
    assert "screenshot" in payload["capture_errors"]
    assert not (tmp_path / "crashes" / "CRASH-0001" / "crash_screenshot.png").exists()
    assert (tmp_path / "crashes" / "CRASH-0001" / "crash_repro.md").is_file()


def test_context_is_created_when_helper_dump_fails(tmp_path):
    def failing_helper(serial):
        raise RuntimeError("helper unavailable")

    capture_crash_context(
        event=_event(),
        event_dir=tmp_path / "crashes" / "CRASH-0001",
        output_dir=tmp_path,
        serial="SERIAL",
        runner_log_path=None,
        run_factory=_ok_context_run_factory,
        helper_dump_factory=failing_helper,
    )

    event_dir = tmp_path / "crashes" / "CRASH-0001"
    payload = json.loads((event_dir / "crash_context.json").read_text(encoding="utf-8"))
    helper_payload = json.loads((event_dir / "crash_helper_dump.json").read_text(encoding="utf-8"))
    assert payload["capture_errors"]["helper_dump"] == "helper unavailable"
    assert helper_payload["nodes"] is None
    assert helper_payload["error"] == "helper unavailable"


def _event():
    return CrashEvent(
        crash_event_id="CRASH-0001",
        crash_type="CONFIRMED_CRASH",
        process="com.samsung.android.oneconnect",
        exception="java.lang.NullPointerException: boom",
        top_frame="com.samsung.android.oneconnect.HomeMonitorActivity.onCreate(HomeMonitorActivity.kt:12)",
        timestamp="06-03 19:42:11.111",
        logcat_excerpt="".join(CRASH_LINES[:-1]),
    )
