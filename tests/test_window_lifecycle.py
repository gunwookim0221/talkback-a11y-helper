from __future__ import annotations

import json

from talkback_lib.window_lifecycle import (
    MAX_EVENTS,
    WindowLifecycleRecorder,
    configure_window_lifecycle,
    parse_window_lifecycle_output,
)


def _snapshot(pid: str, *, include_enabled_service: bool = True) -> str:
    enabled = (
        "Enabled services: {com.samsung.android.accessibility.talkback/com.samsung.android.marvin.talkback.TalkBackService}"
        if include_enabled_service
        else "Enabled services: {}"
    )
    return "\n".join(
        [
            "Window #0 Window{abc u0 SmartThings}: ",
            "    mOwnerUid=10001 package=com.example.app appop=NONE",
            "    mAttrs={(0,0)(fillxfill) ty=BASE_APPLICATION",
            "    mHasSurface=true isReadyForDisplay()=true",
            "Window #1 Window{def u0 화면 검색}: ",
            "    mOwnerUid=10155 package=com.samsung.android.accessibility.talkback appop=CREATE_ACCESSIBILITY_OVERLAY",
            "    mAttrs={(0,0)(fillxfill) ty=ACCESSIBILITY_OVERLAY",
            "    mHasSurface=false isReadyForDisplay()=false",
            "__TB_ACTIVITY__",
            "topResumedActivity=ActivityRecord{123 u0 com.example.app/.MainActivity t1}",
            "__TB_ACCESSIBILITY__",
            enabled,
            "Accessibility Focused Window Id = 42",
            "__TB_PID__",
            pid,
        ]
    )


def test_window_lifecycle_parser_extracts_bounded_window_and_focus_state():
    parsed = parse_window_lifecycle_output(
        _snapshot("321"),
        focus_node={"actual_focus_node": {"packageName": "com.example.app"}},
    )

    assert parsed["window_count"] == 2
    assert parsed["surfaced_window_count"] == 1
    assert parsed["ready_window_count"] == 1
    assert parsed["foreground_package"] == "com.example.app"
    assert parsed["accessibility_focus_window_id"] == 42
    assert parsed["accessibility_focus_package"] == "com.example.app"
    assert parsed["talkback_enabled"] is True
    assert parsed["talkback_pid"] == "321"
    assert parsed["search_screen_overlay_detected"] is True
    assert parsed["search_screen_overlay_window_count"] == 1
    assert parsed["search_screen_overlay_visible"] is False
    assert parsed["window_types"] == ["ACCESSIBILITY_OVERLAY", "BASE_APPLICATION"]


def test_window_lifecycle_recorder_marks_pid_return_after_enabled_gap(tmp_path):
    class FakeClient:
        def __init__(self):
            self.outputs = [_snapshot("123"), _snapshot(""), _snapshot("456")]

        def _run(self, _args, **_kwargs):
            return self.outputs.pop(0)

    recorder = WindowLifecycleRecorder(FakeClient(), "serial", "life_main", tmp_path)
    first = recorder.capture("before", "SMART_NEXT", step=1)
    gap = recorder.capture("during", "SMART_NEXT", step=1)
    returned = recorder.capture("after", "SMART_NEXT", step=1)

    assert first["talkback_restart_detected"] is False
    assert gap["talkback_process_event"] == "enabled_but_pid_missing"
    assert returned["talkback_restart_detected"] is True
    assert returned["talkback_process_event"] == "returned_after_enabled_gap"
    artifact = [json.loads(line) for line in (tmp_path / "talkback_window_lifecycle.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [item["talkback_pid"] for item in artifact] == ["123", None, "456"]


def test_window_lifecycle_event_limit_stops_additional_device_reads():
    class FakeClient:
        calls = 0

        def _run(self, _args, **_kwargs):
            self.calls += 1
            return _snapshot("123")

    client = FakeClient()
    recorder = WindowLifecycleRecorder(client, "serial", "life_main", None)
    recorder.event_count = MAX_EVENTS

    assert recorder.capture("before", "SMART_NEXT") is None
    assert client.calls == 0


def test_window_lifecycle_tracks_pid_changes_across_scenarios(tmp_path):
    class FakeClient:
        def __init__(self):
            self.outputs = [_snapshot("123"), _snapshot("456")]

        def _run(self, _args, **_kwargs):
            return self.outputs.pop(0)

    client = FakeClient()
    first_run = configure_window_lifecycle(
        client, "serial", "life_main", tmp_path / "life_main", enabled=True
    )
    first_run.capture("scenario_start", "SCENARIO_START")
    second_run = configure_window_lifecycle(
        client, "serial", "life_home_monitor_plugin", tmp_path / "life_home_monitor", enabled=True
    )

    restarted = second_run.capture("scenario_start", "SCENARIO_START")

    assert restarted["talkback_restart_detected"] is True
    assert restarted["talkback_process_event"] == "pid_changed"


def test_window_lifecycle_carries_last_observed_accessibility_focus_package(tmp_path):
    class FakeClient:
        def __init__(self):
            self.outputs = [_snapshot("123"), _snapshot("123")]

        def _run(self, _args, **_kwargs):
            return self.outputs.pop(0)

    recorder = WindowLifecycleRecorder(FakeClient(), "serial", "life_main", tmp_path)
    first = recorder.capture(
        "after", "SMART_NEXT", focus_node={"packageName": "com.example.app"}
    )
    following = recorder.capture("before", "SMART_NEXT")

    assert first["accessibility_focus_package"] == "com.example.app"
    assert following["accessibility_focus_package"] == "com.example.app"
    assert following["accessibility_focus_package_source"] == "previous_helper_focus_node"
    assert following["accessibility_focus_package_observed_in_sample"] is False
    assert following["accessibility_focus_package_age_events"] == 1


def test_window_lifecycle_configuration_is_opt_in(monkeypatch):
    class FakeClient:
        pass

    client = FakeClient()
    monkeypatch.delenv("TALKBACK_WINDOW_LIFECYCLE", raising=False)

    assert configure_window_lifecycle(client, "serial", "life_main", None) is None
    assert getattr(client, "_window_lifecycle_recorder") is None
