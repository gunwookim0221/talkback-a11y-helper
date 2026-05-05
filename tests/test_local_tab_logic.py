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


def _bottom_strip_candidate(label, left, right, *, top=2338, bottom=2473, rid="", clickable=True, focusable=True):
    bounds = f"{left},{top},{right},{bottom}"
    return {
        "rid": rid,
        "label": label,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "center_x": (left + right) // 2,
        "center_y": (top + bottom) // 2,
        "width": right - left,
        "height": bottom - top,
        "bounds": bounds,
        "node": {
            "text": label,
            "viewIdResourceName": rid,
            "className": "android.view.View",
            "clickable": clickable,
            "effectiveClickable": clickable,
            "focusable": focusable,
            "isVisibleToUser": True,
            "visibleToUser": True,
            "boundsInScreen": bounds,
        },
    }


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


def test_structural_local_tab_filter_accepts_energy_badged_activity(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("Monitor", 30, 370, rid="monitor"),
        _bottom_strip_candidate("Save", 370, 710, rid="save"),
        _bottom_strip_candidate("Activity New notification", 710, 1050, rid="activity"),
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert [candidate["label"] for candidate in accepted] == ["Monitor", "Save", "Activity"]
    assert accepted[2]["original_label"] == "Activity New notification"
    assert accepted[2]["label_canonicalized"] is True
    assert rejected == []


def test_collect_groups_keeps_badged_activity_as_local_tab(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    nodes = [
        {
            "text": "",
            "boundsInScreen": "0,0,1080,2473",
            "visibleToUser": True,
            "children": [
                _bottom_strip_candidate("Monitor", 30, 370, rid="monitor")["node"],
                _bottom_strip_candidate("Save", 370, 710, rid="save")["node"],
                _bottom_strip_candidate("Activity New notification", 710, 1050, rid="activity")["node"],
            ],
        }
    ]

    _content, bottom_strip, meta = collection_flow._collect_step_candidate_priority_groups(
        nodes,
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
    )

    assert meta["raw_bottom_strip_candidates"] == ["Monitor", "Save", "Activity New notification"]
    assert [candidate["label"] for candidate in bottom_strip] == ["Monitor", "Save", "Activity"]


def test_collect_groups_keeps_pet_half_width_numeric_tabs(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    nodes = [
        {
            "text": "",
            "boundsInScreen": "0,0,1080,2473",
            "visibleToUser": True,
            "children": [
                _bottom_strip_candidate("Activity", 30, 540, rid="0")["node"],
                _bottom_strip_candidate("Care", 540, 1050, rid="2")["node"],
            ],
        }
    ]

    _content, bottom_strip, meta = collection_flow._collect_step_candidate_priority_groups(
        nodes,
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
    )

    assert meta["raw_bottom_strip_candidates"] == ["Activity", "Care"]
    assert [candidate["label"] for candidate in bottom_strip] == ["Activity", "Care"]


def test_collect_groups_keeps_plant_half_width_tabs(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    nodes = [
        {
            "text": "",
            "boundsInScreen": "0,0,1080,2473",
            "visibleToUser": True,
            "children": [
                _bottom_strip_candidate("My plants", 30, 540, top=2341, bottom=2473, rid="myPlants")["node"],
                _bottom_strip_candidate("Routines", 540, 1050, top=2341, bottom=2473, rid="routines")["node"],
            ],
        }
    ]

    _content, bottom_strip, meta = collection_flow._collect_step_candidate_priority_groups(
        nodes,
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
    )

    assert meta["raw_bottom_strip_candidates"] == ["My plants", "Routines"]
    assert [candidate["label"] for candidate in bottom_strip] == ["My plants", "Routines"]


def test_structural_local_tab_filter_accepts_two_generic_tabs(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("TabA", 30, 540, rid="0"),
        _bottom_strip_candidate("TabB", 540, 1050, rid="2"),
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert [candidate["label"] for candidate in accepted] == ["TabA", "TabB"]
    assert rejected == []


def test_structural_local_tab_filter_does_not_create_single_button_tab(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [_bottom_strip_candidate("Start", 240, 840, rid="start_button")]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert accepted == []
    assert rejected == candidates


def test_structural_local_tab_filter_rejects_global_bottom_nav(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    labels = ["Home", "Devices", "Life", "Routines", "Menu"]
    candidates = [
        _bottom_strip_candidate(label, index * 216, (index + 1) * 216, rid=label.lower())
        for index, label in enumerate(labels)
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert accepted == []
    assert rejected == candidates


def test_structural_local_tab_filter_rejects_content_cards(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("Card A", 30, 1050, top=900, bottom=1180, rid="card_a"),
        _bottom_strip_candidate("Card B", 30, 1050, top=1220, bottom=1520, rid="card_b"),
        _bottom_strip_candidate("Card C", 30, 1050, top=1560, bottom=1880, rid="card_c"),
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert accepted == []
    assert rejected == candidates


def test_structural_local_tab_filter_accepts_pet_numeric_resource_ids(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("Activity", 30, 540, rid="0"),
        _bottom_strip_candidate("Care", 540, 1050, rid="2"),
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert [candidate["label"] for candidate in accepted] == ["Activity", "Care"]
    assert rejected == []


def test_structural_local_tab_filter_accepts_plant_two_tab_strip(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("My plants", 30, 540, top=2341, bottom=2473, rid="myPlants"),
        _bottom_strip_candidate("Routines", 540, 1050, top=2341, bottom=2473, rid="routines"),
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert [candidate["label"] for candidate in accepted] == ["My plants", "Routines"]
    assert rejected == []


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


def test_maybe_select_next_local_tab_blocks_already_committed_progression_direct(monkeypatch):
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
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=0,
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

    assert advanced is False
    assert client.select_calls == []
    assert state.pending_local_tab_rid == ""
    assert any("[STEP][local_tab_sorted]" in line and "Activity|Location|Events" in line for line in logs)
    assert any("[STEP][local_tab_skip_reason]" in line and "visited_progression_tab" in line for line in logs)
    assert any("[STEP][local_tab_gate]" in line and "no_unvisited_local_tab" in line for line in logs)


def _location_progression_state(*, active_label="LocationButton Location"):
    signature = "activity||location||events"
    return SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/location_button",
        current_local_tab_active_label=active_label,
        current_local_tab_active_age=0,
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/activity_button", "label": "ActivityButton Activity", "left": 40, "node": {"boundsInScreen": "40,1700,300,1860"}},
                {"rid": "com.example:id/location_button", "label": active_label, "left": 400, "node": {"boundsInScreen": "400,1700,660,1860"}},
                {"rid": "com.example:id/events_button", "label": "EventsButton Events", "left": 760, "node": {"boundsInScreen": "760,1700,1040,1860"}},
            ]
        },
        visited_local_tabs_by_signature={signature: {"com.example:id/activity_button", "com.example:id/location_button"}},
        previous_step_row={"focus_view_id": "com.example:id/location_button", "visible_label": active_label},
        content_phase_grace_steps=0,
        last_selected_local_tab_signature=signature,
        last_selected_local_tab_rid="com.example:id/location_button",
        last_selected_local_tab_label=active_label,
        last_selected_local_tab_bounds="400,1700,660,1860",
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
        fail_count=0,
        same_count=0,
        prev_fingerprint=("", "", ""),
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        visited_logical_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        recent_focus_realign_signatures=set(),
        failed_focus_realign_signatures=set(),
        recent_focus_realign_clusters=set(),
        cluster_title_fallback_applied=set(),
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
        scroll_ready_retry_counts={},
        pending_scroll_ready_cluster_signature="",
        completed_container_groups=set(),
    )


def _patch_content_candidates(monkeypatch, candidates):
    def fake_collect(_nodes, **_kwargs):
        return list(candidates), [], {
            "chrome_excluded_candidates": ["Navigate up", "Family Care", "Add family member", "More options"],
            "container_promoted_candidates": [],
            "top_priority_container_candidates": [],
            "raw_bottom_strip_candidates": [],
        }

    def fake_filter(content_candidates, **_kwargs):
        return {
            "all_candidates": list(content_candidates),
            "selection_candidates": list(content_candidates),
            "exhaustion_candidates": list(content_candidates),
            "representative_candidates": list(content_candidates),
            "status_candidates": [],
            "section_header_deferred": [],
            "revisit_rejected": [],
            "consumed_rejected": [],
            "leaf_rejected": [],
        }

    monkeypatch.setattr(local_tab_logic, "_collect_step_candidate_priority_groups", fake_collect)
    monkeypatch.setattr(local_tab_logic, "_filter_content_candidates_for_phase", fake_filter)
    monkeypatch.setattr(local_tab_logic, "_clear_active_container_group", lambda *_args, **_kwargs: None)


def _local_tab_progression_state(signature, candidates, *, active_rid, active_label, visited=None):
    return SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid=active_rid,
        current_local_tab_active_label=active_label,
        current_local_tab_active_age=0,
        local_tab_candidates_by_signature={signature: list(candidates)},
        visited_local_tabs_by_signature={signature: set(visited or {active_rid})},
        previous_step_row={"focus_view_id": active_rid, "visible_label": active_label},
        content_phase_grace_steps=0,
        last_selected_local_tab_signature="",
        last_selected_local_tab_rid="",
        last_selected_local_tab_label="",
        last_selected_local_tab_bounds="",
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
        fail_count=0,
        same_count=0,
        prev_fingerprint=("", "", ""),
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        visited_logical_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        recent_focus_realign_signatures=set(),
        failed_focus_realign_signatures=set(),
        recent_focus_realign_clusters=set(),
        cluster_title_fallback_applied=set(),
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
        scroll_ready_retry_counts={},
        pending_scroll_ready_cluster_signature="",
        completed_container_groups=set(),
    )


def _assert_next_local_tab(monkeypatch, logs, *, signature, candidates, current_rid, current_label, expected_rid, expected_label):
    _patch_content_candidates(monkeypatch, [])
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    state = _local_tab_progression_state(
        signature,
        candidates,
        active_rid=current_rid,
        active_label=current_label,
        visited={current_rid},
    )

    advanced = local_tab_logic._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": current_rid, "visible_label": current_label},
        scenario_id="life_plugin",
        step_idx=40,
    )

    assert advanced is True
    assert state.pending_local_tab_rid == expected_rid
    assert state.pending_local_tab_label == expected_label
    assert client.select_calls[0]["name"] == expected_rid
    assert any(
        "[STEP][local_tab_progression]" in line
        and f"current='{current_label}'" in line
        and f"next='{expected_label}'" in line
        for line in logs
    )


def test_plant_local_tab_progression_wraps_from_routines_to_my_plants(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("My plants", 30, 540, top=2341, bottom=2473, rid="myPlants"),
        _bottom_strip_candidate("Routines", 540, 1050, top=2341, bottom=2473, rid="routines"),
    ]

    _assert_next_local_tab(
        monkeypatch,
        logs,
        signature="myplants||routines",
        candidates=candidates,
        current_rid="routines",
        current_label="Routines",
        expected_rid="myPlants",
        expected_label="My plants",
    )


def test_plant_local_tab_progression_moves_from_my_plants_to_routines(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("My plants", 30, 540, top=2341, bottom=2473, rid="myPlants"),
        _bottom_strip_candidate("Routines", 540, 1050, top=2341, bottom=2473, rid="routines"),
    ]

    _assert_next_local_tab(
        monkeypatch,
        logs,
        signature="myplants||routines",
        candidates=candidates,
        current_rid="myPlants",
        current_label="My plants",
        expected_rid="routines",
        expected_label="Routines",
    )


def test_pet_local_tab_progression_wraps_from_care_to_activity(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("Activity", 30, 540, rid="0"),
        _bottom_strip_candidate("Care", 540, 1050, rid="2"),
    ]

    _assert_next_local_tab(
        monkeypatch,
        logs,
        signature="0||2",
        candidates=candidates,
        current_rid="2",
        current_label="Care",
        expected_rid="0",
        expected_label="Activity",
    )


def test_single_local_tab_does_not_select_next(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    _patch_content_candidates(monkeypatch, [])
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    candidates = [_bottom_strip_candidate("Monitor", 30, 1050, rid="monitor")]
    state = _local_tab_progression_state(
        "monitor",
        candidates,
        active_rid="monitor",
        active_label="Monitor",
        visited={"monitor"},
    )

    advanced = local_tab_logic._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "monitor", "visible_label": "Monitor"},
        scenario_id="life_plugin",
        step_idx=40,
    )

    assert advanced is False
    assert state.pending_local_tab_rid == ""
    assert client.select_calls == []
    assert any("single_local_tab_no_progression" in line for line in logs)


def test_location_map_utility_candidates_do_not_block_local_tab_progression(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    _patch_content_candidates(monkeypatch, [
        {"label": "Place Place", "rid": "com.samsung.android.plugin.care:id/refresh_button", "node": {"boundsInScreen": "540,1699,1008,1867"}},
        {"label": "Current location Current location", "rid": "", "node": {"boundsInScreen": "100,1500,500,1660"}},
        {"label": "Change view", "rid": "com.samsung.android.plugin.care:id/layerButton", "node": {"boundsInScreen": "800,1500,1000,1660"}},
        {"label": "Map", "rid": "", "node": {"boundsInScreen": "100,1200,1000,1490"}},
    ])
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    state = _location_progression_state()

    advanced = local_tab_logic._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/location_button", "visible_label": "LocationButton Location"},
        scenario_id="life_family_care_plugin",
        step_idx=48,
    )

    assert advanced is True
    assert state.pending_local_tab_rid == "com.example:id/events_button"
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert not any("content_not_exhausted" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "EventsButton Events" in line for line in logs)


def test_location_real_content_still_blocks_local_tab_progression(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    _patch_content_candidates(monkeypatch, [
        {"label": "Medication", "rid": "com.example:id/medication_card", "node": {"boundsInScreen": "80,900,1000,1100"}},
        {"label": "Place Place", "rid": "com.samsung.android.plugin.care:id/refresh_button", "node": {"boundsInScreen": "540,1699,1008,1867"}},
    ])
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    state = _location_progression_state()

    advanced = local_tab_logic._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/location_button", "visible_label": "LocationButton Location"},
        scenario_id="life_family_care_plugin",
        step_idx=48,
    )

    assert advanced is False
    assert state.pending_local_tab_rid == ""
    assert client.select_calls == []
    assert any("content_not_exhausted" in line for line in logs)


def test_map_utility_filter_is_scoped_to_location_tab(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    _patch_content_candidates(monkeypatch, [
        {"label": "Place Place", "rid": "com.samsung.android.plugin.care:id/refresh_button", "node": {"boundsInScreen": "540,1699,1008,1867"}},
        {"label": "Map", "rid": "", "node": {"boundsInScreen": "100,1200,1000,1490"}},
    ])
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    state = _location_progression_state(active_label="ActivityButton Activity")
    state.current_local_tab_active_rid = "com.example:id/activity_button"
    state.last_selected_local_tab_rid = "com.example:id/activity_button"
    state.last_selected_local_tab_label = "ActivityButton Activity"

    advanced = local_tab_logic._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/activity_button", "visible_label": "ActivityButton Activity"},
        scenario_id="life_family_care_plugin",
        step_idx=48,
    )

    assert advanced is False
    assert state.pending_local_tab_rid == ""
    assert client.select_calls == []
    assert any("content_not_exhausted" in line for line in logs)


def test_location_map_utility_candidates_mark_viewport_exhausted_before_continuation(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    _patch_content_candidates(monkeypatch, [
        {"label": "Place Place", "rid": "com.samsung.android.plugin.care:id/refresh_button", "node": {"boundsInScreen": "540,1699,1008,1867"}},
        {"label": "Current location Current location", "rid": "", "node": {"boundsInScreen": "100,1500,500,1660"}},
        {"label": "Change view", "rid": "com.samsung.android.plugin.care:id/layerButton", "node": {"boundsInScreen": "800,1500,1000,1660"}},
    ])
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    state = _location_progression_state()

    row = local_tab_logic._maybe_reprioritize_persistent_bottom_strip_row(
        row={
            "focus_view_id": "com.example:id/location_button",
            "visible_label": "LocationButton Location",
            "merged_announcement": "LocationButton Location",
            "focus_bounds": "400,1700,660,1860",
            "focus_class_name": "android.widget.Button",
            "focus_clickable": True,
            "focus_focusable": True,
            "move_result": "moved",
        },
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=48,
    )

    assert row["viewport_exhausted_eval_result"] is True
    assert row["viewport_exhausted_eval_reason"] == "no_representative_candidates"
