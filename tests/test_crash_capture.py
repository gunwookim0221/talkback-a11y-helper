from __future__ import annotations

import json
import subprocess

from qa_frontend.backend.crash_capture import (
    CrashEventStore,
    LogcatCapture,
    OneConnectCrashDetector,
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


def test_detector_stores_confirmed_oneconnect_crash_event(tmp_path):
    store = CrashEventStore(tmp_path)
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


def test_detector_ignores_non_oneconnect_fatal_exception(tmp_path):
    store = CrashEventStore(tmp_path)
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

    capture = LogcatCapture(serial="SERIAL", output_dir=tmp_path, popen_factory=popen_factory)
    capture.start()
    events = capture.stop()

    assert commands == [["adb", "-s", "SERIAL", "logcat", "-v", "threadtime"]]
    assert process.terminated is True
    assert len(events) == 1
    assert "Process: com.samsung.android.oneconnect" in (tmp_path / "logcat.txt").read_text(encoding="utf-8")
    assert (tmp_path / "crashes" / "CRASH-0001" / "crash_event.json").is_file()
    assert (tmp_path / "crashes" / "CRASH-0001" / "logcat_excerpt.txt").is_file()


def test_start_capture_clears_logcat_before_background_capture(tmp_path):
    calls = []
    logs = []
    process = _FakeLogcatProcess([])

    def run_factory(command, **kwargs):
        calls.append(command)
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
    )

    assert capture is not None
    capture.stop()
    assert calls[0] == ["adb", "-s", "SERIAL", "logcat", "-c"]
    assert calls[1] == ["adb", "-s", "SERIAL", "logcat", "-v", "threadtime"]
    assert logs[0] == "[CRASH_CAPTURE] logcat_clear returncode=0"
