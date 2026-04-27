import sys
from collections import deque
from types import SimpleNamespace

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, ExcelWriter=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow, local_tab_logic


class DummyClient:
    def __init__(self, steps):
        self.steps = list(steps)
        self.dump_tree_sequence = []
        self.select_calls = []
        self.click_focused_calls = []
        self.collect_focus_step_calls = []
        self.tap_xy_adb_calls = []
        self.move_focus_smart_calls = []

    def dump_tree(self, **_kwargs):
        if self.dump_tree_sequence:
            return self.dump_tree_sequence.pop(0)
        return []

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return True

    def click_focused(self, **kwargs):
        self.click_focused_calls.append(kwargs)
        return True

    def collect_focus_step(self, **kwargs):
        self.collect_focus_step_calls.append(kwargs)
        return dict(self.steps.pop(0))

    def tap_xy_adb(self, **kwargs):
        self.tap_xy_adb_calls.append(kwargs)
        return True

    def move_focus_smart(self, **kwargs):
        self.move_focus_smart_calls.append(kwargs)
        return {"status": "moved", "detail": "forced_test"}


def _bind_local_tab_logic(monkeypatch, logs):
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    collection_flow._sync_local_tab_logic_dependencies()


def test_last_selected_local_tab_hint_write_and_clear_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    state = SimpleNamespace(
        last_selected_local_tab_signature="",
        last_selected_local_tab_rid="",
        last_selected_local_tab_label="",
        last_selected_local_tab_bounds="",
    )

    local_tab_logic._write_last_selected_local_tab_hint(
        state,
        signature="activity||location||events",
        rid="com.example:id/location_button",
        label="Location",
        bounds="400,1700,660,1860",
        reason="pending_resolved",
    )
    local_tab_logic._clear_last_selected_local_tab_hint(state, reason="candidate_set_changed")

    assert state.last_selected_local_tab_signature == ""
    assert state.last_selected_local_tab_rid == ""
    assert state.last_selected_local_tab_label == ""
    assert state.last_selected_local_tab_bounds == ""
    assert any("[STEP][local_tab_hint_write]" in line and "Location" in line for line in logs)
    assert any("[STEP][local_tab_hint_clear]" in line and "candidate_set_changed" in line for line in logs)


def test_local_tab_strip_signature_and_left_to_right_sort_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        {"rid": "com.example:id/events_button", "label": "Events", "left": 760},
        {"rid": "com.example:id/activity_button", "label": "Activity", "left": 40},
        {"rid": "com.example:id/location_button", "label": "Location", "left": 400},
    ]

    ordered = local_tab_logic._sort_local_tab_candidates_left_to_right(candidates)
    signature = local_tab_logic._build_local_tab_strip_signature(ordered)

    assert [candidate["label"] for candidate in ordered] == ["Activity", "Location", "Events"]
    assert signature == "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button"


def test_last_selected_hint_resolves_active_candidate_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    signature = "activity||location||events"
    candidates = [
        {"rid": "com.example:id/activity_button", "label": "Activity", "left": 40, "bounds": "40,1700,300,1860"},
        {"rid": "com.example:id/location_button", "label": "Location", "left": 400, "bounds": "400,1700,660,1860"},
        {"rid": "com.example:id/events_button", "label": "Events", "left": 760, "bounds": "760,1700,1040,1860"},
    ]
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="",
        current_local_tab_active_label="",
        current_local_tab_active_age=99,
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_age=0,
        last_selected_local_tab_signature=signature,
        last_selected_local_tab_rid="com.example:id/location_button",
        last_selected_local_tab_label="Location",
        last_selected_local_tab_bounds="400,1700,660,1860",
    )

    active, source, label = local_tab_logic._resolve_active_local_tab_candidate_for_progression(
        state=state,
        sorted_tab_candidates=candidates,
        row={"focus_view_id": "com.example:id/activity_button", "visible_label": "Activity"},
        previous_row={},
    )

    assert active == candidates[1]
    assert source == "last_selected_hint"
    assert label == "Location"


def test_pending_local_tab_commit_matches_contained_label_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    state = SimpleNamespace(
        current_local_tab_signature="activity||location||events",
        current_local_tab_active_rid="com.example:id/activity_button",
        visited_local_tabs_by_signature={},
        pending_local_tab_signature="activity||location||events",
        pending_local_tab_rid="",
        pending_local_tab_label="LocationButton Location",
        pending_local_tab_bounds="400,1700,660,1860",
        pending_local_tab_age=0,
        current_local_tab_active_label="Activity",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
    )

    local_tab_logic._maybe_commit_pending_local_tab_progression(
        state,
        {"focus_view_id": "LocationButton", "visible_label": "LocationButton", "focus_bounds": "400,1700,660,1860"},
    )

    assert state.current_local_tab_active_label == "LocationButton Location"
    assert state.pending_local_tab_label == ""
    assert any("[STEP][local_tab_commit_match]" in line and "matched_by='label_contains'" in line for line in logs)
    assert any("[STEP][local_tab_commit]" in line and "LocationButton Location" in line for line in logs)


def test_record_pending_local_tab_progression_sets_forced_navigation_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    state = SimpleNamespace(
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=3,
        forced_local_tab_target_signature="",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        forced_local_tab_target_bounds="",
        forced_local_tab_attempt_count=1,
    )
    candidate = {
        "rid": "com.example:id/location_button",
        "label": "LocationButton Location",
        "bounds": "400,1700,660,1860",
    }

    rid, label, bounds = local_tab_logic._record_pending_local_tab_progression(
        state=state,
        signature="activity||location||events",
        next_candidate=candidate,
        reason="progression_selected",
    )

    assert (rid, label, bounds) == (
        "com.example:id/location_button",
        "LocationButton Location",
        "400,1700,660,1860",
    )
    assert state.pending_local_tab_rid == "com.example:id/location_button"
    assert state.forced_local_tab_target_rid == "com.example:id/location_button"
    assert state.forced_local_tab_attempt_count == 0
    assert any("[STEP][local_tab_force_navigation_set]" in line and "LocationButton Location" in line for line in logs)


def test_record_pending_local_tab_progression_normalizes_dict_bounds_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    state = SimpleNamespace(
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=0,
        forced_local_tab_target_signature="",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        forced_local_tab_target_bounds="",
        forced_local_tab_attempt_count=0,
    )

    _rid, _label, bounds = local_tab_logic._record_pending_local_tab_progression(
        state=state,
        signature="tabs",
        next_candidate={
            "rid": "com.example:id/events_button",
            "label": "EventsButton Events",
            "bounds": {"left": 710, "top": 2316, "right": 1050, "bottom": 2496},
        },
        reason="progression_selected",
    )

    assert bounds == "710,2316,1050,2496"
    assert state.forced_local_tab_target_bounds == "710,2316,1050,2496"


def test_activate_forced_local_tab_target_taps_before_move_smart_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    client = DummyClient([
        {
            "step_index": 30,
            "visible_label": "EventsButton Events",
            "merged_announcement": "EventsButton Events",
            "focus_view_id": "com.example:id/events_button",
            "focus_bounds": "760,1700,1040,1860",
        }
    ])
    state = SimpleNamespace(
        forced_local_tab_target_signature="activity||location||events",
        forced_local_tab_target_rid="com.example:id/events_button",
        forced_local_tab_target_label="EventsButton Events",
        forced_local_tab_target_bounds="760,1700,1040,1860",
        forced_local_tab_attempt_count=0,
        current_local_tab_signature="activity||location||events",
        current_local_tab_active_rid="com.example:id/location_button",
        current_local_tab_active_label="LocationButton Location",
        current_local_tab_active_age=0,
        visited_local_tabs_by_signature={"activity||location||events": {"com.example:id/location_button"}},
        pending_local_tab_signature="activity||location||events",
        pending_local_tab_rid="com.example:id/events_button",
        pending_local_tab_label="EventsButton Events",
        pending_local_tab_bounds="760,1700,1040,1860",
        pending_local_tab_age=0,
        fail_count=2,
        same_count=2,
        prev_fingerprint=("old", "old", "old"),
        previous_step_row={"visible_label": "old"},
        recent_representative_signatures=deque(["old"]),
        consumed_representative_signatures={"old"},
        visited_logical_signatures={"old"},
        consumed_cluster_signatures={"old"},
        consumed_cluster_logical_signatures={"old"},
        recent_scroll_fallback_signatures={"old"},
        last_scroll_fallback_attempted_signatures={"old"},
        scroll_ready_retry_counts={"old": 1},
        pending_scroll_ready_cluster_signature="old",
    )

    row = local_tab_logic._activate_forced_local_tab_target(
        client=client,
        dev="SERIAL",
        state=state,
        step_idx=30,
        wait_seconds=0.1,
        announcement_wait_seconds=0.1,
        announcement_idle_wait_seconds=0.0,
        announcement_max_extra_wait_seconds=0.0,
    )

    assert row["focus_view_id"] == "com.example:id/events_button"
    assert client.tap_xy_adb_calls[0]["x"] == 900
    assert client.tap_xy_adb_calls[0]["y"] == 1780
    assert client.move_focus_smart_calls == []
    assert state.current_local_tab_active_rid == "com.example:id/events_button"
    assert state.visited_logical_signatures == set()
    assert state.consumed_cluster_signatures == set()
    assert state.recent_scroll_fallback_signatures == set()
    assert state.fail_count == 0
    assert state.same_count == 0
    assert state.forced_local_tab_target_rid == ""
    assert any("[STEP][local_tab_target_activate]" in line and "method='tap_bounds_center'" in line for line in logs)
    assert any("[STEP][local_tab_target_activate_success]" in line and "matched_by='rid'" in line for line in logs)
    assert any("[STEP][local_tab_content_phase_reset]" in line and "EventsButton Events" in line for line in logs)
    assert any("[STEP][local_tab_commit]" in line and "target_activation_success" in line for line in logs)


def test_maybe_select_next_local_tab_prefers_rightward_progression_over_visited_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    signature = "activity||location||events"
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/location_button",
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/activity_button", "label": "Activity", "left": 40, "node": {"boundsInScreen": "40,1700,300,1860"}},
                {"rid": "com.example:id/location_button", "label": "Location", "left": 400, "node": {"boundsInScreen": "400,1700,660,1860"}},
                {"rid": "com.example:id/events_button", "label": "Events", "left": 760, "node": {"boundsInScreen": "760,1700,1040,1860"}},
            ]
        },
        visited_local_tabs_by_signature={
            signature: {
                "com.example:id/activity_button",
                "com.example:id/location_button",
                "com.example:id/events_button",
            }
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/location_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = local_tab_logic._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/location_button", "visible_label": "Location"},
        scenario_id="life_family_care_plugin",
        step_idx=21,
    )

    assert advanced is True
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert state.pending_local_tab_rid == "com.example:id/events_button"
    assert any("[STEP][local_tab_pending]" in line and "Events" in line for line in logs)
    assert any("[STEP][local_tab_sorted]" in line and "Activity|Location|Events" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "current='Location'" in line and "next='Events'" in line for line in logs)
    assert any("[STEP][local_tab_skip_reason]" in line and "visited_ignored_for_order_progression" in line for line in logs)
