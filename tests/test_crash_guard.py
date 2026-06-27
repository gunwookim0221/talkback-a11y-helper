from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from tb_runner import collection_flow
from tb_runner import crash_guard


def _launcher_row(**overrides):
    row = {
        "step_index": 1,
        "move_result": "moved",
        "visible_label": "Messages",
        "normalized_visible_label": "messages",
        "merged_announcement": "Messages",
        "normalized_announcement": "messages",
        "focus_view_id": "com.sec.android.app.launcher:id/icon",
        "focus_bounds": "10,10,100,100",
        "focus_node": {
            "packageName": "com.sec.android.app.launcher",
            "viewIdResourceName": "com.sec.android.app.launcher:id/icon",
            "text": "Messages",
        },
        "dump_tree_nodes": [
            {
                "packageName": "com.sec.android.app.launcher",
                "viewIdResourceName": "com.sec.android.app.launcher:id/icon",
                "text": "Messages",
            }
        ],
    }
    row.update(overrides)
    return row


class GuardClient:
    def __init__(self, rows=None, *, pidof: str = "", current_package: str = "com.sec.android.app.launcher"):
        self.rows = list(rows or [])
        self.pidof = pidof
        self.current_package = current_package
        self.dump_tree_calls = 0
        self.collect_focus_step_calls = 0

    def collect_focus_step(self, **kwargs):
        self.collect_focus_step_calls += 1
        row = dict(self.rows.pop(0))
        row.setdefault("step_index", kwargs.get("step_index", 1))
        return row

    def _run(self, args, **kwargs):
        if args[:3] == ["shell", "dumpsys", "window"]:
            return f"mCurrentFocus=Window{{abc u0 {self.current_package}/{self.current_package}.Launcher}}"
        if args[:2] == ["shell", "pidof"]:
            return self.pidof
        if args[:3] == ["shell", "uiautomator", "dump"]:
            return "dumped"
        if args[:2] == ["shell", "cat"]:
            return "<hierarchy package=\"com.sec.android.app.launcher\" />"
        return ""

    def _take_snapshot(self, dev, path):
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n")

    def dump_tree(self, **kwargs):
        self.dump_tree_calls += 1
        return _launcher_row()["dump_tree_nodes"]


def test_launcher_focus_package_creates_app_terminated_event(tmp_path):
    client = GuardClient(pidof="")
    row = _launcher_row()

    inspection = crash_guard.inspect_foreground_package_exit(row=row, client=client, dev="SERIAL")
    detection = inspection["detection"]

    assert detection is not None
    assert detection["crash_type"] == "APP_TERMINATED"
    assert detection["reason"] == "app_terminated"
    assert inspection["package_sources"]["focused_package"] == "focus_payload"
    assert inspection["package_sources"]["resource_package"] == "focus_view_id"
    assert inspection["package_sources"]["current_package"] == "dumpsys_window"

    event_id = crash_guard.record_foreground_exit_event(
        output_base_dir=str(tmp_path),
        serial="SERIAL",
        row=row,
        detection=detection,
        client=client,
        dev="SERIAL",
        scenario_id="life_home_monitor_plugin",
        step_idx=7,
    )

    event_dir = tmp_path / "crashes" / event_id
    assert event_id == "CRASH-0001"
    assert (event_dir / "crash_event.json").is_file()
    assert (event_dir / "crash_context.json").is_file()
    assert (event_dir / "crash_repro.md").is_file()
    assert (event_dir / "focus_state.json").is_file()
    payload = json.loads((event_dir / "crash_context.json").read_text(encoding="utf-8"))
    assert payload["crash_type"] == "APP_TERMINATED"
    assert payload["scenario"]["name"] == "life_home_monitor_plugin"
    assert payload["step"]["index"] == 7
    assert payload["recovery"]["decision"] == "capture_only"


def test_launcher_focus_with_unknown_process_state_creates_possible_crash(tmp_path):
    class NoPidClient(GuardClient):
        def _run(self, args, **kwargs):
            if args[:2] == ["shell", "pidof"]:
                raise RuntimeError("pidof unavailable")
            return super()._run(args, **kwargs)

    client = NoPidClient()
    detection = crash_guard.detect_foreground_package_exit(row=_launcher_row(), client=client, dev="SERIAL")

    assert detection is not None
    assert detection["crash_type"] == "POSSIBLE_CRASH"

    event_id = crash_guard.record_foreground_exit_event(
        output_base_dir=str(tmp_path),
        serial="SERIAL",
        row=_launcher_row(),
        detection=detection,
        client=client,
        dev="SERIAL",
        scenario_id="life_home_monitor_plugin",
        step_idx=7,
    )

    assert (tmp_path / "crashes" / event_id / "crash_context.json").is_file()
    assert "No FATAL EXCEPTION" in (tmp_path / "crashes" / event_id / "logcat_excerpt.txt").read_text(encoding="utf-8")


def test_oneconnect_resource_package_does_not_trigger_guard():
    client = GuardClient(pidof="1234", current_package="com.samsung.android.oneconnect")
    row = _launcher_row(
        focus_view_id="com.samsung.android.oneconnect:id/title",
        focus_node={
            "packageName": "com.samsung.android.oneconnect",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/title",
            "text": "Home Monitor",
        },
        dump_tree_nodes=[
            {"packageName": "com.samsung.android.oneconnect", "viewIdResourceName": "com.samsung.android.oneconnect:id/title"}
        ],
    )

    assert crash_guard.detect_foreground_package_exit(row=row, client=client, dev="SERIAL") is None


def test_systemui_screen_off_is_environment_interruption_not_crash():
    class ScreenOffClient(GuardClient):
        def _run(self, args, **kwargs):
            if args[:3] == ["shell", "dumpsys", "power"]:
                return "mWakefulness=Asleep\nDisplay Power: state=OFF"
            if args[:4] == ["shell", "dumpsys", "window", "policy"]:
                return "isStatusBarKeyguard=true"
            if args[:3] == ["shell", "dumpsys", "statusbar"]:
                return "mExpandedVisible=false"
            return super()._run(args, **kwargs)

    client = ScreenOffClient(pidof="1234", current_package="com.android.systemui")
    inspection = crash_guard.inspect_foreground_package_exit(
        row=_launcher_row(),
        client=client,
        dev="SERIAL",
    )

    assert inspection["detection"] is None
    assert inspection["environment_interruption"] == {
        "classification": "ENVIRONMENT_ERROR",
        "reason": "screen_off_interruption",
        "package": "com.android.systemui",
        "screen_state": "SCREEN_OFF",
        "keyguard_active": True,
        "notification_shade_active": False,
        "crash_counted": False,
    }


def test_systemui_without_screen_keyguard_or_shade_still_uses_existing_crash_detection():
    class ActiveSystemUiClient(GuardClient):
        def _run(self, args, **kwargs):
            if args[:3] == ["shell", "dumpsys", "power"]:
                return "mWakefulness=Awake\nDisplay Power: state=ON"
            if args[:4] == ["shell", "dumpsys", "window", "policy"]:
                return "isStatusBarKeyguard=false"
            if args[:3] == ["shell", "dumpsys", "statusbar"]:
                return "mExpandedVisible=false"
            return super()._run(args, **kwargs)

    client = ActiveSystemUiClient(pidof="", current_package="com.android.systemui")
    detection = crash_guard.detect_foreground_package_exit(
        row=_launcher_row(),
        client=client,
        dev="SERIAL",
    )

    assert detection is not None
    assert detection["crash_type"] == "APP_TERMINATED"
    assert detection["reason"] == "app_terminated"


def test_main_loop_stops_on_launcher_focus_and_persists_crash_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(collection_flow, "save_excel_with_perf", lambda *args, **kwargs: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(str(message)))
    client = GuardClient(
        rows=[
            _launcher_row(step_index=1),
            _launcher_row(step_index=2, visible_label="Camera", merged_announcement="Camera"),
            _launcher_row(step_index=3, visible_label="Messages", merged_announcement="Messages"),
        ]
    )
    state = _main_loop_state(anchor_row=_oneconnect_anchor_row())
    phase_ctx = collection_flow.CollectionPhaseContext(
        tab_cfg={
            "tab_name": "Life",
            "scenario_id": "life_home_monitor_plugin",
            "scenario_type": "content",
            "max_steps": 6,
        },
        rows=[_oneconnect_anchor_row()],
        all_rows=[_oneconnect_anchor_row()],
        output_path=str(tmp_path / "out.xlsx"),
        output_base_dir=str(tmp_path),
        scenario_perf=None,
        checkpoint_every=1,
        main_step_wait_seconds=0.1,
        main_announcement_wait_seconds=0.1,
        main_announcement_idle_wait_seconds=0.0,
        main_announcement_max_extra_wait_seconds=0.0,
        state=state,
    )

    result_state = collection_flow._main_loop_phase(client, "SERIAL", phase_ctx)

    assert result_state.stop_triggered is True
    assert result_state.stop_reason == "app_terminated"
    assert result_state.stop_step == 1
    assert client.collect_focus_step_calls == 1
    assert phase_ctx.rows[-1]["crash_like_detected"] is True
    assert phase_ctx.rows[-1]["crash_type"] == "APP_TERMINATED"
    assert phase_ctx.rows[-1]["status"] == "END"
    assert phase_ctx.rows[-1]["stop_reason"] == "app_terminated"
    assert phase_ctx.rows[-1]["crash_terminal"] is True
    assert client.last_crash_terminal_signal["crash_event_id"] == "CRASH-0001"
    assert client.last_crash_terminal_signal["recovery_state"] == "CRASH_DETECTED"
    assert (tmp_path / "crashes" / "CRASH-0001" / "crash_context.json").is_file()
    assert any("[CRASH_GUARD] check start source='main_loop'" in entry for entry in logs)
    assert any("[CRASH_GUARD] package source='focus_payload' package='com.sec.android.app.launcher'" in entry for entry in logs)
    assert any("[CRASH_GUARD] app_terminated pidof_empty=true" in entry for entry in logs)
    assert any("[CRASH_GUARD] event_created crash_event_id='CRASH-0001'" in entry for entry in logs)
    assert sum("[CRASH_TERMINAL] scenario_exit" in entry for entry in logs) == 1
    assert any(
        "[CRASH_TERMINAL] scenario_exit scenario='life_home_monitor_plugin' step=1 "
        "reason='app_terminated' crash_event_id='CRASH-0001'" in entry
        for entry in logs
    )
    assert not any("duplicate_suppressed" in entry for entry in logs)


def test_main_loop_logs_guard_on_global_nav_path(tmp_path, monkeypatch):
    monkeypatch.setattr(collection_flow, "save_excel_with_perf", lambda *args, **kwargs: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(str(message)))
    row = _launcher_row(
        smart_nav_success=True,
        smart_nav_requested_view_id="com.sec.android.app.launcher:id/icon",
        smart_nav_resolved_view_id="com.sec.android.app.launcher:id/icon",
        smart_nav_actual_view_id="com.sec.android.app.launcher:id/icon",
    )
    client = GuardClient(rows=[row])
    state = _main_loop_state(anchor_row=_oneconnect_anchor_row())
    phase_ctx = collection_flow.CollectionPhaseContext(
        tab_cfg={
            "tab_name": "Home",
            "scenario_id": "home_main",
            "scenario_type": "global_nav",
            "max_steps": 1,
        },
        rows=[_oneconnect_anchor_row()],
        all_rows=[_oneconnect_anchor_row()],
        output_path=str(tmp_path / "out.xlsx"),
        output_base_dir=str(tmp_path),
        scenario_perf=None,
        checkpoint_every=1,
        main_step_wait_seconds=0.1,
        main_announcement_wait_seconds=0.1,
        main_announcement_idle_wait_seconds=0.0,
        main_announcement_max_extra_wait_seconds=0.0,
        state=state,
    )

    result_state = collection_flow._main_loop_phase(client, "SERIAL", phase_ctx)

    assert (tmp_path / "crashes" / "CRASH-0001" / "crash_context.json").is_file()
    assert result_state.stop_reason == "app_terminated"
    assert client.collect_focus_step_calls == 1
    assert any("[CRASH_GUARD] check start source='main_loop' scenario='home_main' step=1" in entry for entry in logs)
    assert any("[CRASH_GUARD] package source='smart_nav_actual_view_id' package='com.sec.android.app.launcher' key='smart_nav_package'" in entry for entry in logs)
    assert any("[CRASH_GUARD] app_terminated package='com.sec.android.app.launcher'" in entry for entry in logs)
    assert sum("[CRASH_TERMINAL] scenario_exit scenario='home_main'" in entry for entry in logs) == 1


def test_crash_guard_suppresses_duplicate_event_in_same_scenario_attempt(tmp_path, monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(str(message)))
    client = GuardClient()
    collection_flow._reset_crash_guard_latch(client, scenario_id="global_nav_main", attempt=0)

    first = collection_flow._run_crash_guard_check(
        client=client,
        dev="SERIAL",
        row=_launcher_row(),
        scenario_id="global_nav_main",
        step_idx=1,
        output_base_dir=str(tmp_path),
        source="main_loop",
    )
    second = collection_flow._run_crash_guard_check(
        client=client,
        dev="SERIAL",
        row=_launcher_row(visible_label="Camera", merged_announcement="Camera"),
        scenario_id="global_nav_main",
        step_idx=2,
        output_base_dir=str(tmp_path),
        source="main_loop",
    )

    assert first is not None
    assert second is not None
    assert first["crash_event_id"] == "CRASH-0001"
    assert second["crash_event_id"] == "CRASH-0001"
    assert client.last_crash_terminal_signal["crash_event_id"] == "CRASH-0001"
    assert (tmp_path / "crashes" / "CRASH-0001").is_dir()
    assert not (tmp_path / "crashes" / "CRASH-0002").exists()
    assert any(
        "[CRASH_GUARD] duplicate_suppressed scenario='global_nav_main' attempt=0 crash_event_id='CRASH-0001'" in entry
        for entry in logs
    )


def test_crash_guard_latch_reset_allows_new_event_for_next_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: None)
    client = GuardClient()
    collection_flow._reset_crash_guard_latch(client, scenario_id="global_nav_main", attempt=0)

    first = collection_flow._run_crash_guard_check(
        client=client,
        dev="SERIAL",
        row=_launcher_row(),
        scenario_id="global_nav_main",
        step_idx=1,
        output_base_dir=str(tmp_path),
        source="main_loop",
    )
    collection_flow._reset_crash_guard_latch(client, scenario_id="life_home_monitor_plugin", attempt=0)
    second = collection_flow._run_crash_guard_check(
        client=client,
        dev="SERIAL",
        row=_launcher_row(),
        scenario_id="life_home_monitor_plugin",
        step_idx=1,
        output_base_dir=str(tmp_path),
        source="main_loop",
    )

    assert first is not None
    assert second is not None
    assert first["crash_event_id"] == "CRASH-0001"
    assert second["crash_event_id"] == "CRASH-0002"
    assert (tmp_path / "crashes" / "CRASH-0001").is_dir()
    assert (tmp_path / "crashes" / "CRASH-0002").is_dir()


def test_crash_guard_latch_reset_allows_new_event_for_next_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: None)
    client = GuardClient()
    collection_flow._reset_crash_guard_latch(client, scenario_id="global_nav_main", attempt=0)

    first = collection_flow._run_crash_guard_check(
        client=client,
        dev="SERIAL",
        row=_launcher_row(attempt=0),
        scenario_id="global_nav_main",
        step_idx=1,
        output_base_dir=str(tmp_path),
        source="main_loop",
    )
    collection_flow._reset_crash_guard_latch(client, scenario_id="global_nav_main", attempt=1)
    second = collection_flow._run_crash_guard_check(
        client=client,
        dev="SERIAL",
        row=_launcher_row(attempt=1),
        scenario_id="global_nav_main",
        step_idx=1,
        output_base_dir=str(tmp_path),
        source="main_loop",
    )

    assert first is not None
    assert second is not None
    assert first["crash_event_id"] == "CRASH-0001"
    assert second["crash_event_id"] == "CRASH-0002"


def _oneconnect_anchor_row():
    return {
        "step_index": 0,
        "move_result": "moved",
        "visible_label": "Home Monitor",
        "normalized_visible_label": "home monitor",
        "merged_announcement": "Home Monitor",
        "normalized_announcement": "home monitor",
        "focus_view_id": "com.samsung.android.oneconnect:id/title",
        "focus_bounds": "10,10,100,100",
        "focus_node": {"packageName": "com.samsung.android.oneconnect"},
        "fingerprint": "Home Monitor|com.samsung.android.oneconnect:id/title|10,10,100,100",
        "normalized_fingerprint": "home monitor|com.samsung.android.oneconnect:id/title",
    }


def _main_loop_state(anchor_row):
    return collection_flow.MainLoopState(
        last_fingerprint=str(anchor_row.get("fingerprint") or ""),
        fingerprint_repeat_count=0,
        previous_step_row=dict(anchor_row),
        prev_fingerprint=collection_flow.make_main_fingerprint(anchor_row),
        fail_count=0,
        same_count=0,
        expanded_overlay_entries=set(),
        post_realign_pending_steps=0,
        main_step_index_by_fingerprint={collection_flow.make_main_fingerprint(anchor_row): 0},
        recent_fingerprint_history=deque(maxlen=5),
        recent_semantic_fingerprint_history=deque(maxlen=5),
        stop_triggered=False,
        stop_reason="",
        stop_step=-1,
        stall_escape_attempted=False,
        recent_representative_signatures=deque(maxlen=5),
        consumed_representative_signatures=set(),
        visited_logical_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_semantic_card_signatures=set(),
        current_local_tab_signature="",
        current_local_tab_active_rid="",
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=0,
        current_local_tab_active_label="",
        current_local_tab_active_age=0,
        forced_local_tab_target_signature="",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        forced_local_tab_target_bounds="",
        forced_local_tab_attempt_count=0,
        local_tab_activation_failures={},
        content_phase_grace_steps=0,
        current_local_tab_content_phase_active=False,
        current_local_tab_content_entered=False,
        current_local_tab_content_candidate_visited=False,
        current_local_tab_content_fail_recorded=False,
        current_local_tab_content_entry_probe_attempted=False,
        active_container_group_signature="",
        active_container_group_remaining=set(),
        active_container_group_labels={},
        completed_container_groups=set(),
        last_selected_local_tab_signature="",
        last_selected_local_tab_rid="",
        last_selected_local_tab_label="",
        last_selected_local_tab_bounds="",
        cta_grace_signature="",
        cta_descend_grace_remaining=0,
        cta_cluster_nodes_by_signature={},
        cta_cluster_visited_rids={},
        cta_cluster_committed_rid={},
    )
