import sys
from collections import deque
from types import SimpleNamespace

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, Series=object, ExcelWriter=object))
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


def test_local_tab_state_defaults_are_empty():
    state = local_tab_logic.LocalTabState()

    assert state.signature == ""
    assert state.active_label == ""
    assert state.active_rid == ""
    assert state.active_age == 0
    assert state.pending_label == ""
    assert state.pending_rid == ""
    assert state.visited_by_signature == {}
    assert state.exhausted_signatures == set()
    assert state.candidates_by_signature == {}


def test_empty_state_content_label_accepts_english_and_korean_aliases():
    for label in (
        "No history",
        "기록 없음",
        "아직 없음",
        "활동 없음",
        "데이터 없음",
        "이벤트 없음",
        "내역 없음",
        "사용 기록 없음",
    ):
        assert local_tab_logic._is_empty_state_content_label(label)


def test_local_tab_state_registers_candidates_by_signature():
    state = local_tab_logic.LocalTabState()
    candidates = [{"rid": "monitor", "label": "Monitor"}]

    state.register_candidates("monitor||save", candidates)
    candidates.append({"rid": "save", "label": "Save"})

    assert state.candidates_by_signature == {
        "monitor||save": [{"rid": "monitor", "label": "Monitor"}]
    }


def test_local_tab_state_marks_visited_and_exhausted():
    state = local_tab_logic.LocalTabState()

    state.mark_visited("monitor||save", "monitor")
    state.mark_visited("monitor||save", "save")
    state.mark_exhausted("monitor||save")

    assert state.visited_by_signature["monitor||save"] == {"monitor", "save"}
    assert state.exhausted_signatures == {"monitor||save"}


def test_local_tab_state_tracks_focus_activation_and_content_separately():
    state = local_tab_logic.LocalTabState()

    state.mark_visited("monitor||save", "monitor")
    state.mark_activation_attempted("monitor||save", "monitor")

    assert state.visited_by_signature["monitor||save"] == {"monitor"}
    assert state.activation_attempted_by_signature["monitor||save"] == {"monitor"}
    assert state.content_confirmed_by_signature.get("monitor||save", set()) == set()

    state.mark_content_confirmed("monitor||save", "monitor")
    assert state.content_confirmed_by_signature["monitor||save"] == {"monitor"}


def test_label_only_local_tab_uses_child_label_for_activation_target(monkeypatch):
    _bind_local_tab_logic(monkeypatch, [])
    candidate = {
        "rid": "",
        "label": "일정버튼 일정",
        "bounds": "710,2316,1050,2496",
        "node": {
            "mergedLabel": "일정버튼 일정",
            "contentDescription": "일정버튼",
            "boundsInScreen": "710,2316,1050,2496",
            "children": [{"text": "일정"}],
        },
    }
    state = SimpleNamespace()

    _rid, action_label, _bounds = local_tab_logic._record_pending_local_tab_progression(
        state=state,
        signature="location||schedule",
        next_candidate=candidate,
        reason="unit_test",
    )

    assert action_label == "일정버튼"
    assert state.pending_local_tab_label == "일정버튼 일정"
    assert state.pending_local_tab_action_label == "일정버튼"


def test_label_only_local_tab_uses_english_child_label_for_activation_target(monkeypatch):
    _bind_local_tab_logic(monkeypatch, [])
    candidate = {
        "rid": "",
        "label": "Schedule button Schedule",
        "bounds": "710,1700,1050,1860",
        "node": {
            "mergedLabel": "Schedule button Schedule",
            "contentDescription": "Schedule button",
            "boundsInScreen": "710,1700,1050,1860",
        },
    }
    state = SimpleNamespace()

    _rid, action_label, _bounds = local_tab_logic._record_pending_local_tab_progression(
        state=state,
        signature="location||schedule",
        next_candidate=candidate,
        reason="unit_test",
    )

    assert action_label == "Schedule button"


def _recovery_dump_strip_node(display_label, concrete_label, bounds):
    return {
        "text": None,
        "contentDescription": concrete_label,
        "mergedLabel": display_label,
        "talkbackLabel": display_label,
        "className": "android.widget.LinearLayout",
        "clickable": True,
        "focusable": True,
        "effectiveClickable": True,
        "visibleToUser": True,
        "isVisibleToUser": True,
        "boundsInScreen": bounds,
        "children": [
            {
                "text": concrete_label.replace(" button", "").replace("버튼", ""),
                "visibleToUser": True,
                "boundsInScreen": bounds,
            }
        ],
    }


def _recovery_dump_strip_candidates(*labels):
    nodes = [{"visibleToUser": True, "boundsInScreen": "0,0,1080,2640", "children": []}]
    nodes.extend(
        _recovery_dump_strip_node(display, concrete, bounds)
        for display, concrete, bounds in labels
    )
    _content, tabs, _meta = collection_flow._collect_step_candidate_priority_groups(
        nodes,
        scenario_id="life_family_care_plugin",
    )
    return tabs


def test_recovery_dump_strip_keeps_korean_concrete_content_description(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = _recovery_dump_strip_candidates(
        ("위치버튼 위치", "위치버튼", "370,2316,710,2496"),
        ("일정버튼 일정", "일정버튼", "710,2316,1050,2496"),
    )
    state = SimpleNamespace(
        current_local_tab_signature="",
        current_local_tab_active_rid="",
        current_local_tab_active_label="",
        current_local_tab_active_age=0,
        pending_local_tab_rid="",
        pending_local_tab_label="",
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
    )

    _signature, rebuilt = local_tab_logic._recover_local_tab_state_from_bottom_strip(
        state=state,
        row={"visible_label": "위치버튼", "focus_bounds": "370,2316,710,2496"},
        previous_row={},
        bottom_strip_candidates=candidates,
        reason="state_missing_but_dump_strip_seen",
    )

    schedule = next(candidate for candidate in rebuilt if candidate["label"] == "일정버튼 일정")
    assert schedule["actionable_label"] == "일정버튼"
    assert schedule["canonical_visit_key"] == "일정버튼"
    assert schedule["node"]["text"] is None
    assert schedule["node"]["contentDescription"] == "일정버튼"
    assert schedule["node"]["mergedLabel"] == "일정버튼 일정"
    _rid, target, _bounds = local_tab_logic._record_pending_local_tab_progression(
        state=state,
        signature="위치버튼 위치||일정버튼 일정",
        next_candidate=schedule,
        reason="unit_test",
    )
    assert target == "일정버튼"
    assert state.pending_local_tab_visit_key == "일정버튼"
    assert any("display='일정버튼 일정'" in line and "actionable='일정버튼'" in line for line in logs)
    assert any("[LOCAL_TAB][forced_navigation]" in line and "target='일정버튼'" in line for line in logs)


def test_recovery_dump_strip_keeps_english_concrete_content_description():
    candidates = _recovery_dump_strip_candidates(
        ("Location button Location", "Location button", "370,2316,710,2496"),
        ("Schedule button Schedule", "Schedule button", "710,2316,1050,2496"),
    )

    schedule = next(candidate for candidate in candidates if candidate["label"] == "Schedule button Schedule")
    assert schedule["actionable_label"] == "Schedule button"
    assert schedule["canonical_visit_key"] == "schedule button"
    assert schedule["node"]["text"] is None
    assert schedule["node"]["contentDescription"] == "Schedule button"
    assert schedule["node"]["mergedLabel"] == "Schedule button Schedule"


def test_recovery_dump_strip_uses_distinct_concrete_keys_for_label_only_tabs():
    candidates = _recovery_dump_strip_candidates(
        ("활동버튼 활동", "활동버튼", "30,2316,370,2496"),
        ("위치버튼 위치", "위치버튼", "370,2316,710,2496"),
        ("일정버튼 일정", "일정버튼", "710,2316,1050,2496"),
    )

    assert {candidate["canonical_visit_key"] for candidate in candidates} == {"활동버튼", "위치버튼", "일정버튼"}


def test_label_only_forced_activation_uses_actionable_label_for_helper_target(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    client = DummyClient([{"visible_label": "활동버튼", "focus_bounds": "20,2316,320,2496"}])
    client.tap_xy_adb = lambda **_kwargs: False
    client.select = lambda **kwargs: client.select_calls.append(kwargs) or False
    state = SimpleNamespace(
        forced_local_tab_target_signature="activity||schedule",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="일정버튼 일정",
        forced_local_tab_target_action_label="일정버튼",
        forced_local_tab_target_visit_key="일정버튼",
        forced_local_tab_target_bounds="710,2316,1050,2496",
        forced_local_tab_attempt_count=0,
        pending_local_tab_signature="activity||schedule",
        pending_local_tab_rid="",
        pending_local_tab_label="일정버튼 일정",
        pending_local_tab_action_label="일정버튼",
        pending_local_tab_visit_key="일정버튼",
        pending_local_tab_bounds="710,2316,1050,2496",
        pending_local_tab_age=0,
        visited_local_tabs_by_signature={"activity||schedule": set()},
        local_tab_activation_failures={},
    )

    local_tab_logic._activate_forced_local_tab_target(
        client=client,
        dev="SERIAL",
        state=state,
        step_idx=1,
        wait_seconds=0.1,
        announcement_wait_seconds=0.1,
        announcement_idle_wait_seconds=0.0,
        announcement_max_extra_wait_seconds=0.0,
    )

    assert [call["name"] for call in client.select_calls] == ["일정버튼"]
    assert any("target='일정버튼'" in line and "source='actionable_label'" in line for line in logs)
    assert not any("target='일정버튼 일정'" in line and "method='select_label'" in line for line in logs)


def test_label_only_local_tab_matches_child_focus_without_exact_merged_label():
    matched, matched_by = local_tab_logic._row_matches_pending_local_tab(
        {"visible_label": "Schedule button", "merged_announcement": "Schedule button"},
        pending_rid="",
        pending_label="Schedule button Schedule",
        pending_action_label="Schedule button",
        pending_bounds="",
    )

    assert (matched, matched_by) == (True, "action_label")


def test_pending_label_only_tab_commits_when_post_activation_content_is_observed(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    signature = "location||schedule"
    state = SimpleNamespace(
        pending_local_tab_signature=signature,
        pending_local_tab_rid="",
        pending_local_tab_label="Schedule button Schedule",
        pending_local_tab_action_label="Schedule button",
        pending_local_tab_visit_key="schedule button",
        pending_local_tab_bounds="710,1700,1050,1860",
        pending_local_tab_age=1,
        current_local_tab_active_rid="",
        current_local_tab_active_label="Location button Location",
        visited_local_tabs_by_signature={signature: set()},
    )

    local_tab_logic._maybe_commit_pending_local_tab_progression(
        state,
        {
            "visible_label": "Upcoming events",
            "focus_view_id": "com.example:id/event_container",
            "focus_bounds": "30,900,1050,1040",
        },
    )

    assert state.pending_local_tab_label == ""
    assert "schedule button" in state.visited_local_tabs_by_signature[signature]
    assert "schedule button" in state.local_tab_content_confirmed_by_signature[signature]
    assert signature in state.local_tab_activation_evidence_signatures
    assert any("matched_by='observed_content_after_activation'" in line for line in logs)


def test_pending_label_only_tab_stays_unvisited_without_content_evidence(monkeypatch):
    _bind_local_tab_logic(monkeypatch, [])
    state = SimpleNamespace(
        pending_local_tab_signature="location||schedule",
        pending_local_tab_rid="",
        pending_local_tab_label="Schedule button Schedule",
        pending_local_tab_action_label="Schedule button",
        pending_local_tab_bounds="710,1700,1050,1860",
        pending_local_tab_age=1,
        visited_local_tabs_by_signature={},
    )

    local_tab_logic._maybe_commit_pending_local_tab_progression(
        state,
        {"visible_label": "", "focus_bounds": "30,900,1050,1040"},
    )

    assert state.pending_local_tab_label == "Schedule button Schedule"
    assert not getattr(state, "local_tab_activation_evidence_signatures", set())


def test_label_only_candidates_use_actionable_key_after_rebuild(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    signature = "activity||location||schedule"
    candidates = [
        {
            **_bottom_strip_candidate("활동버튼 활동", 20, 320, rid=""),
            "actionable_label": "활동버튼",
            "canonical_visit_key": "활동버튼",
        },
        {
            **_bottom_strip_candidate("위치버튼 위치", 360, 660, rid=""),
            "actionable_label": "위치버튼",
            "canonical_visit_key": "위치버튼",
        },
        {
            **_bottom_strip_candidate("일정버튼 일정", 700, 1000, rid=""),
            "actionable_label": "일정버튼",
            "canonical_visit_key": "일정버튼",
        },
    ]
    _patch_content_candidates(monkeypatch, [])
    state = _local_tab_progression_state(
        signature,
        candidates,
        active_rid="",
        active_label="일정버튼 일정",
        visited={"활동버튼", "위치버튼", "일정버튼"},
    )
    state.current_local_tab_active_label = "일정버튼 일정"

    row = {"visible_label": "일정버튼 일정", "focus_bounds": "700,2338,1000,2473"}
    advanced = local_tab_logic._maybe_select_next_local_tab(
        client=DummyClient([]),
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_plugin",
        step_idx=2,
    )

    assert advanced is False
    assert row["local_tab_block_reason"] == "no_unvisited_local_tab"
    assert any("reason='no_unvisited_local_tab'" in line for line in logs)


def test_local_tab_state_updates_active_and_pending():
    state = local_tab_logic.LocalTabState()

    state.set_active(signature="monitor||save", rid="monitor", label="Monitor", age=2)
    state.set_pending(
        signature="monitor||save",
        rid="save",
        label="Save",
        bounds="700,2338,1050,2473",
        age=1,
    )

    assert state.signature == "monitor||save"
    assert state.active_rid == "monitor"
    assert state.active_label == "Monitor"
    assert state.active_age == 2
    assert state.pending_signature == "monitor||save"
    assert state.pending_rid == "save"
    assert state.pending_label == "Save"
    assert state.pending_bounds == "700,2338,1050,2473"
    assert state.pending_age == 1


def test_local_tab_state_consistency_has_no_mismatch_when_mirror_matches():
    mirror = local_tab_logic.LocalTabState()
    mirror.set_active(signature="monitor||save", rid="monitor", label="Monitor")
    mirror.set_pending(signature="monitor||save", rid="save", label="Save", bounds="700,2338,1050,2473")
    mirror.set_forced(signature="monitor||save", rid="save", label="Save", bounds="700,2338,1050,2473")
    mirror.set_last_selected(signature="monitor||save", rid="monitor", label="Monitor", bounds="30,2338,370,2473")
    mirror.mark_visited("monitor||save", "monitor")
    mirror.register_candidates("monitor||save", [{"rid": "monitor", "label": "Monitor"}])
    state = SimpleNamespace(
        local_tab_state=mirror,
        current_local_tab_signature="monitor||save",
        current_local_tab_active_rid="monitor",
        current_local_tab_active_label="Monitor",
        pending_local_tab_signature="monitor||save",
        pending_local_tab_rid="save",
        pending_local_tab_label="Save",
        forced_local_tab_target_signature="monitor||save",
        forced_local_tab_target_rid="save",
        forced_local_tab_target_label="Save",
        last_selected_local_tab_signature="monitor||save",
        last_selected_local_tab_rid="monitor",
        last_selected_local_tab_label="Monitor",
        visited_local_tabs_by_signature={"monitor||save": {"monitor"}},
        local_tab_candidates_by_signature={"monitor||save": [{"rid": "monitor", "label": "Monitor"}]},
    )

    assert local_tab_logic._get_local_tab_state_consistency_mismatches(state) == []


def test_local_tab_state_consistency_reports_pending_label_mismatch():
    mirror = local_tab_logic.LocalTabState()
    mirror.set_pending(signature="monitor||save", rid="save", label="Savings", bounds="")
    state = SimpleNamespace(
        local_tab_state=mirror,
        pending_local_tab_signature="monitor||save",
        pending_local_tab_rid="save",
        pending_local_tab_label="Save",
    )

    assert local_tab_logic._get_local_tab_state_consistency_mismatches(state) == ["pending_label"]


def test_local_tab_state_consistency_reports_visited_mismatch():
    mirror = local_tab_logic.LocalTabState()
    mirror.mark_visited("monitor||save", "monitor")
    state = SimpleNamespace(
        local_tab_state=mirror,
        visited_local_tabs_by_signature={"monitor||save": {"monitor", "save"}},
    )

    assert local_tab_logic._get_local_tab_state_consistency_mismatches(state) == ["visited_by_signature"]


def test_local_tab_state_consistency_skips_missing_legacy_fields():
    state = SimpleNamespace(local_tab_state=local_tab_logic.LocalTabState())

    assert local_tab_logic._get_local_tab_state_consistency_mismatches(state) == []


def test_local_tab_state_consistency_logs_mismatch_only(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    mirror = local_tab_logic.LocalTabState()
    mirror.set_pending(signature="monitor||save", rid="save", label="Savings", bounds="")
    state = SimpleNamespace(
        local_tab_state=mirror,
        pending_local_tab_signature="monitor||save",
        pending_local_tab_rid="save",
        pending_local_tab_label="Save",
    )

    mismatches = local_tab_logic._log_local_tab_state_consistency_mismatch(state, context="unit_test")

    assert mismatches == ["pending_label"]
    assert logs == ["[LOCAL_TAB_STATE][mismatch] context='unit_test' fields='pending_label'"]


def test_local_tab_candidates_read_prefers_mirror_candidates():
    mirror = local_tab_logic.LocalTabState()
    mirror.register_candidates("mirror_sig", [{"rid": "mirror", "label": "Mirror"}])
    state = SimpleNamespace(
        local_tab_state=mirror,
        local_tab_candidates_by_signature={"legacy_sig": [{"rid": "legacy", "label": "Legacy"}]},
    )

    candidates_by_signature = local_tab_logic._get_local_tab_candidates_by_signature(state)

    assert list(candidates_by_signature) == ["mirror_sig"]
    assert candidates_by_signature["mirror_sig"][0]["label"] == "Mirror"


def test_local_tab_candidates_read_falls_back_to_legacy_when_mirror_empty():
    state = SimpleNamespace(
        local_tab_state=local_tab_logic.LocalTabState(),
        local_tab_candidates_by_signature={"legacy_sig": [{"rid": "legacy", "label": "Legacy"}]},
    )

    candidates_by_signature = local_tab_logic._get_local_tab_candidates_by_signature(state)

    assert list(candidates_by_signature) == ["legacy_sig"]
    assert candidates_by_signature["legacy_sig"][0]["label"] == "Legacy"


def test_local_tab_candidates_read_logs_key_mismatch_without_crash(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    mirror = local_tab_logic.LocalTabState()
    mirror.register_candidates("mirror_sig", [{"rid": "mirror", "label": "Mirror"}])
    state = SimpleNamespace(
        local_tab_state=mirror,
        local_tab_candidates_by_signature={"legacy_sig": [{"rid": "legacy", "label": "Legacy"}]},
    )

    candidates_by_signature = local_tab_logic._get_local_tab_candidates_by_signature(
        state,
        context="unit_candidates_read",
    )

    assert list(candidates_by_signature) == ["mirror_sig"]
    assert logs == [
        "[LOCAL_TAB_STATE][mismatch] context='unit_candidates_read' fields='candidates_by_signature'"
    ]


def test_active_local_tab_snapshot_prefers_mirror_active():
    mirror = local_tab_logic.LocalTabState()
    mirror.set_active(signature="mirror_sig", rid="mirror_rid", label="Mirror", age=2)
    state = SimpleNamespace(
        local_tab_state=mirror,
        current_local_tab_signature="legacy_sig",
        current_local_tab_active_rid="legacy_rid",
        current_local_tab_active_label="Legacy",
        current_local_tab_active_age=1,
    )

    snapshot = local_tab_logic._get_active_local_tab_snapshot(state)

    assert snapshot == {
        "signature": "mirror_sig",
        "rid": "mirror_rid",
        "label": "Mirror",
        "age": 2,
        "source": "mirror",
    }


def test_active_local_tab_snapshot_falls_back_to_legacy_when_mirror_empty():
    state = SimpleNamespace(
        local_tab_state=local_tab_logic.LocalTabState(),
        current_local_tab_signature="legacy_sig",
        current_local_tab_active_rid="legacy_rid",
        current_local_tab_active_label="Legacy",
        current_local_tab_active_age=3,
    )

    snapshot = local_tab_logic._get_active_local_tab_snapshot(state)

    assert snapshot == {
        "signature": "legacy_sig",
        "rid": "legacy_rid",
        "label": "Legacy",
        "age": 3,
        "source": "legacy",
    }


def test_active_local_tab_snapshot_logs_mismatch_without_crash(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    mirror = local_tab_logic.LocalTabState()
    mirror.set_active(signature="mirror_sig", rid="mirror_rid", label="Mirror", age=2)
    state = SimpleNamespace(
        local_tab_state=mirror,
        current_local_tab_signature="legacy_sig",
        current_local_tab_active_rid="legacy_rid",
        current_local_tab_active_label="Legacy",
        current_local_tab_active_age=1,
    )

    snapshot = local_tab_logic._get_active_local_tab_snapshot(state, context="unit_active_read")

    assert snapshot["source"] == "mirror"
    assert logs == [
        "[LOCAL_TAB_STATE][mismatch] context='unit_active_read' fields='active_signature,active_rid,active_label,active_age'"
    ]


def test_active_local_tab_snapshot_handles_missing_legacy_fields():
    mirror = local_tab_logic.LocalTabState()
    mirror.set_active(signature="mirror_sig", rid="mirror_rid", label="Mirror", age=2)
    state = SimpleNamespace(local_tab_state=mirror)

    snapshot = local_tab_logic._get_active_local_tab_snapshot(state)

    assert snapshot["source"] == "mirror"
    assert snapshot["label"] == "Mirror"


def test_resolve_active_local_tab_candidate_prefers_mirror_active(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    mirror = local_tab_logic.LocalTabState()
    mirror.set_active(signature="tabs", rid="save", label="Save", age=0)
    state = SimpleNamespace(
        local_tab_state=mirror,
        current_local_tab_signature="tabs",
        current_local_tab_active_rid="monitor",
        current_local_tab_active_label="Monitor",
        current_local_tab_active_age=0,
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_age=0,
        last_selected_local_tab_signature="",
        last_selected_local_tab_rid="",
        last_selected_local_tab_label="",
        last_selected_local_tab_bounds="",
    )
    candidates = [
        {"rid": "monitor", "label": "Monitor", "bounds": "30,2338,370,2473"},
        {"rid": "save", "label": "Save", "bounds": "370,2338,710,2473"},
    ]

    active, source, label = local_tab_logic._resolve_active_local_tab_candidate_for_progression(
        state=state,
        sorted_tab_candidates=candidates,
        row={},
        previous_row={},
    )

    assert active == candidates[1]
    assert source == "committed"
    assert label == "Save"


def test_pending_local_tab_snapshot_prefers_mirror_pending():
    mirror = local_tab_logic.LocalTabState()
    mirror.set_pending(
        signature="mirror_sig",
        rid="mirror_rid",
        label="Mirror",
        bounds="10,20,30,40",
        age=2,
    )
    state = SimpleNamespace(
        local_tab_state=mirror,
        pending_local_tab_signature="legacy_sig",
        pending_local_tab_rid="legacy_rid",
        pending_local_tab_label="Legacy",
        pending_local_tab_bounds="1,2,3,4",
        pending_local_tab_age=1,
    )

    snapshot = local_tab_logic._get_pending_local_tab_snapshot(state)

    assert snapshot == {
        "signature": "mirror_sig",
        "rid": "mirror_rid",
        "label": "Mirror",
        "bounds": "10,20,30,40",
        "age": 2,
        "source": "mirror",
    }


def test_pending_local_tab_snapshot_falls_back_to_legacy_when_mirror_empty():
    state = SimpleNamespace(
        local_tab_state=local_tab_logic.LocalTabState(),
        pending_local_tab_signature="legacy_sig",
        pending_local_tab_rid="legacy_rid",
        pending_local_tab_label="Legacy",
        pending_local_tab_bounds="1,2,3,4",
        pending_local_tab_age=3,
    )

    snapshot = local_tab_logic._get_pending_local_tab_snapshot(state)

    assert snapshot == {
        "signature": "legacy_sig",
        "rid": "legacy_rid",
        "label": "Legacy",
        "bounds": "1,2,3,4",
        "age": 3,
        "source": "legacy",
    }


def test_pending_local_tab_snapshot_logs_mismatch_without_crash(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    mirror = local_tab_logic.LocalTabState()
    mirror.set_pending(
        signature="mirror_sig",
        rid="mirror_rid",
        label="Mirror",
        bounds="10,20,30,40",
        age=2,
    )
    state = SimpleNamespace(
        local_tab_state=mirror,
        pending_local_tab_signature="legacy_sig",
        pending_local_tab_rid="legacy_rid",
        pending_local_tab_label="Legacy",
        pending_local_tab_bounds="1,2,3,4",
        pending_local_tab_age=1,
    )

    snapshot = local_tab_logic._get_pending_local_tab_snapshot(state, context="unit_pending_read")

    assert snapshot["source"] == "mirror"
    assert logs == [
        "[LOCAL_TAB_STATE][mismatch] context='unit_pending_read' fields='pending_signature,pending_rid,pending_label,pending_bounds,pending_age'"
    ]


def test_pending_local_tab_snapshot_handles_missing_legacy_fields():
    mirror = local_tab_logic.LocalTabState()
    mirror.set_pending(
        signature="mirror_sig",
        rid="mirror_rid",
        label="Mirror",
        bounds="10,20,30,40",
        age=2,
    )
    state = SimpleNamespace(local_tab_state=mirror)

    snapshot = local_tab_logic._get_pending_local_tab_snapshot(state)

    assert snapshot["source"] == "mirror"
    assert snapshot["label"] == "Mirror"


def test_commit_pending_local_tab_progression_prefers_mirror_pending(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    mirror = local_tab_logic.LocalTabState()
    mirror.set_pending(
        signature="tabs",
        rid="save",
        label="Save",
        bounds="370,2338,710,2473",
        age=0,
    )
    state = SimpleNamespace(
        local_tab_state=mirror,
        current_local_tab_signature="tabs",
        current_local_tab_active_rid="monitor",
        current_local_tab_active_label="Monitor",
        visited_local_tabs_by_signature={},
        pending_local_tab_signature="tabs",
        pending_local_tab_rid="legacy",
        pending_local_tab_label="Legacy",
        pending_local_tab_bounds="1,2,3,4",
        pending_local_tab_age=0,
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        forced_local_tab_target_bounds="",
    )

    local_tab_logic._maybe_commit_pending_local_tab_progression(
        state,
        {"focus_view_id": "save", "visible_label": "Save", "focus_bounds": "370,2338,710,2473"},
    )

    assert state.current_local_tab_active_rid == "save"
    assert state.current_local_tab_active_label == "Save"
    assert "save" in state.visited_local_tabs_by_signature["tabs"]


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


def test_lifecycle_marks_bottom_strip_focus_row_as_local_tab(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {
            "text": "",
            "contentDescription": "",
            "viewIdResourceName": "",
            "className": "android.widget.FrameLayout",
            "clickable": False,
            "focusable": False,
            "effectiveClickable": False,
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "text": "Device usage",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/device_usage_card",
                    "className": "android.view.ViewGroup",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "60,420,1020,760",
                    "children": [],
                },
                {
                    "text": "Activity",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/activity_button",
                    "className": "android.widget.Button",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,1760,320,1860",
                    "children": [],
                },
                {
                    "text": "Location",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/location_button",
                    "className": "android.widget.Button",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "400,1760,680,1860",
                    "children": [],
                },
            ],
        }
    ]]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
        current_local_tab_active_label="",
        current_local_tab_active_age=0,
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        forced_local_tab_target_bounds="",
    )
    row = {
        "focus_view_id": "com.example:id/location_button",
        "visible_label": "Location",
        "merged_announcement": "Location",
        "focus_bounds": "400,1760,680,1860",
        "focus_class_name": "android.widget.Button",
        "focus_clickable": True,
        "focus_focusable": True,
        "focus_effective_clickable": True,
    }

    updated = local_tab_logic._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_energy_plugin"},
        state=state,
        step_idx=9,
    )

    assert updated["row_lifecycle_kind"] == "local_tab"
    assert updated["row_lifecycle_source"] == "bottom_strip_candidate"
    assert updated["row_lifecycle_confidence"] == "high"
    assert state.local_tab_state.signature == "com.example:id/activity_button||com.example:id/location_button"
    assert state.local_tab_state.active_rid == "com.example:id/location_button"
    assert state.local_tab_state.active_label == "Location"
    assert list(state.local_tab_state.candidates_by_signature) == [
        "com.example:id/activity_button||com.example:id/location_button"
    ]
    assert any("[LIFECYCLE]" in line and "kind='local_tab'" in line for line in logs)


def test_lifecycle_marks_regular_content_row_as_content(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {
            "text": "Device usage",
            "contentDescription": "",
            "viewIdResourceName": "com.example:id/device_usage_card",
            "className": "android.view.ViewGroup",
            "clickable": True,
            "focusable": True,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "60,420,1020,760",
            "children": [],
        }
    ]]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        forced_local_tab_target_bounds="",
    )
    row = {
        "focus_view_id": "com.example:id/device_usage_card",
        "visible_label": "Device usage",
        "merged_announcement": "Device usage",
        "focus_bounds": "60,420,1020,760",
        "focus_class_name": "android.view.ViewGroup",
        "focus_clickable": True,
        "focus_focusable": True,
        "focus_effective_clickable": True,
    }

    updated = local_tab_logic._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=state,
        step_idx=10,
    )

    assert updated["row_lifecycle_kind"] == "content"
    assert updated["row_lifecycle_source"] == "content_candidates_present"
    assert updated["row_lifecycle_confidence"] == "medium"
    assert not any("[LIFECYCLE]" in line for line in logs)


def test_lifecycle_keeps_local_tab_metadata_context_off_content_kind(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    state = SimpleNamespace(
        current_local_tab_signature="activity||monitor||save",
        current_local_tab_active_rid="activity",
        current_local_tab_active_label="Activity",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        forced_local_tab_target_bounds="",
    )
    row = {
        "focus_view_id": "com.example:id/energy_card",
        "visible_label": "Energy",
        "merged_announcement": "Energy",
        "local_tab_signature_logged": "activity||monitor||save",
    }

    local_tab_logic._annotate_row_lifecycle_kind(
        row=row,
        state=state,
        step_idx=11,
        content_candidates=[{"label": "Energy"}],
    )

    assert row["row_lifecycle_kind"] == "content"
    assert row["row_lifecycle_source"] == "content_candidates_present"
    assert row["row_lifecycle_confidence"] == "medium"
    assert row["row_lifecycle_context"] == "local_tab_strip_present"
    assert not any("[LIFECYCLE]" in line and "kind='local_tab'" in line for line in logs)


def test_lifecycle_keeps_local_tab_metadata_context_off_status_kind(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    state = SimpleNamespace(
        current_local_tab_signature="activity||monitor||save",
        current_local_tab_active_rid="activity",
        current_local_tab_active_label="Activity",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        forced_local_tab_target_bounds="",
    )
    row = {
        "focus_view_id": "com.example:id/page_indicator",
        "visible_label": "Page 1 of 5",
        "merged_announcement": "Page 1 of 5",
        "local_tab_gate_evaluated": True,
    }

    local_tab_logic._annotate_row_lifecycle_kind(
        row=row,
        state=state,
        step_idx=12,
        current_row_is_passive_status=local_tab_logic._is_passive_status_text("Page 1 of 5"),
    )

    assert row["row_lifecycle_kind"] == "status"
    assert row["row_lifecycle_source"] == "passive_status_text"
    assert row["row_lifecycle_confidence"] == "medium"
    assert row["row_lifecycle_context"] == "local_tab_strip_present"
    assert any("[LIFECYCLE]" in line and "kind='status'" in line for line in logs)


def test_lifecycle_keeps_local_tab_transition_as_local_tab(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    state = SimpleNamespace(
        current_local_tab_signature="",
        current_local_tab_active_rid="",
        current_local_tab_active_label="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        forced_local_tab_target_bounds="",
    )
    row = {
        "focus_view_id": "com.example:id/activity",
        "visible_label": "Activity New notification",
        "merged_announcement": "Activity New notification",
        "local_tab_transition": True,
    }

    local_tab_logic._annotate_row_lifecycle_kind(
        row=row,
        state=state,
        step_idx=13,
        content_candidates=[{"label": "Energy"}],
    )

    assert row["row_lifecycle_kind"] == "local_tab"
    assert row["row_lifecycle_source"] == "local_tab_transition"
    assert row["row_lifecycle_confidence"] == "high"
    assert any("[LIFECYCLE]" in line and "source='local_tab_transition'" in line for line in logs)


def test_lifecycle_unknown_metadata_does_not_change_row_suppression():
    row = {
        "visible_label": "",
        "merged_announcement": "",
        "focus_view_id": "",
        "row_lifecycle_kind": "unknown",
        "row_lifecycle_source": "insufficient_signal",
        "row_lifecycle_confidence": "low",
    }
    state = SimpleNamespace(current_local_tab_signature="", local_tab_candidates_by_signature={})

    suppress, reason = collection_flow._should_suppress_row_persistence(row=row, state=state, stop=False)

    assert (suppress, reason) == (False, "")


def test_structural_local_tab_filter_accepts_korean_energy_tabs_with_canonical_identity(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("모니터링", 30, 540, rid="monitor"),
        _bottom_strip_candidate("절약", 540, 1050, rid="save"),
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert [candidate["label"] for candidate in accepted] == ["모니터링", "절약"]
    assert [candidate["canonical_label"] for candidate in accepted] == ["monitor", "save"]
    assert rejected == []


def test_structural_local_tab_filter_accepts_korean_plant_tabs_with_canonical_identity(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("내 식물", 30, 540, top=2341, bottom=2473, rid="myPlants"),
        _bottom_strip_candidate("자동화", 540, 1050, top=2341, bottom=2473, rid="routines"),
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert [candidate["label"] for candidate in accepted] == ["내 식물", "자동화"]
    assert [candidate["canonical_label"] for candidate in accepted] == ["my_plants", "routines"]
    assert rejected == []


def test_structural_local_tab_filter_rejects_duplicate_canonical_aliases(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    candidates = [
        _bottom_strip_candidate("Monitor", 30, 370, rid=""),
        _bottom_strip_candidate("모니터링", 370, 710, rid=""),
        _bottom_strip_candidate("Save", 710, 1050, rid=""),
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert accepted == []
    assert rejected == candidates


def test_structural_local_tab_filter_rejects_korean_global_bottom_nav(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    labels = ["홈", "기기", "라이프", "자동화", "메뉴"]
    candidates = [
        _bottom_strip_candidate(label, index * 216, (index + 1) * 216, rid="")
        for index, label in enumerate(labels)
    ]

    accepted, rejected = local_tab_logic._filter_local_tab_strip_candidates(candidates)

    assert accepted == []
    assert rejected == candidates


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
    assert state.local_tab_state.active_label == "LocationButton Location"
    assert state.local_tab_state.pending_label == ""
    assert state.local_tab_state.visited_by_signature == {
        "activity||location||events": {"locationbutton location"}
    }
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
    assert state.local_tab_state.pending_rid == "com.example:id/location_button"
    assert state.local_tab_state.pending_label == "LocationButton Location"
    assert state.local_tab_state.forced_rid == "com.example:id/location_button"
    assert state.local_tab_state.forced_label == "LocationButton Location"
    assert state.local_tab_state.forced_attempt_count == 0
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
    assert state.local_tab_state.active_rid == "com.example:id/events_button"
    assert state.local_tab_state.active_label == "EventsButton Events"
    assert "com.example:id/events_button" in state.local_tab_state.visited_by_signature["activity||location||events"]
    assert state.local_tab_state.pending_rid == ""
    assert state.visited_logical_signatures == set()
    assert state.consumed_cluster_signatures == set()
    assert state.recent_scroll_fallback_signatures == set()
    assert state.fail_count == 0
    assert state.same_count == 0
    assert state.forced_local_tab_target_rid == ""
    assert state.local_tab_state.forced_rid == ""
    assert any("[STEP][local_tab_target_activate]" in line and "method='tap_bounds_center'" in line for line in logs)
    assert any("[STEP][local_tab_target_activate_success]" in line and "matched_by='rid'" in line for line in logs)
    assert any("[STEP][local_tab_content_phase_reset]" in line and "EventsButton Events" in line for line in logs)
    assert any("[STEP][local_tab_commit]" in line and "target_activation_success" in line for line in logs)


def test_activate_forced_local_tab_target_accepts_observed_content_after_tap(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    signature = "location||schedule"
    client = DummyClient([
        {
            "visible_label": "상위 메뉴로 이동",
            "merged_announcement": "상위 메뉴로 이동",
            "focus_bounds": "0,118,180,310",
            "focus_clickable": True,
            "focus_focusable": True,
        }
    ])
    client.focus_in_bounds = lambda **_kwargs: {
        "success": True,
        "raw": {
            "focused": {
                "text": "약",
                "viewIdResourceName": "com.samsung.android.plugin.care:id/medicine_card",
                "className": "android.widget.TextView",
                "boundsInScreen": "30,900,1050,1040",
            }
        },
    }
    state = _local_tab_progression_state(
        signature,
        [],
        active_rid="",
        active_label="위치버튼 위치",
        visited={"위치버튼"},
    )
    state.forced_local_tab_target_signature = signature
    state.forced_local_tab_target_rid = ""
    state.forced_local_tab_target_label = "일정버튼 일정"
    state.forced_local_tab_target_action_label = "일정버튼"
    state.forced_local_tab_target_visit_key = "일정버튼"
    state.forced_local_tab_target_bounds = "710,2316,1050,2496"
    state.forced_local_tab_attempt_count = 0
    state.pending_local_tab_signature = signature
    state.pending_local_tab_label = "일정버튼 일정"
    state.pending_local_tab_action_label = "일정버튼"
    state.pending_local_tab_visit_key = "일정버튼"
    state.pending_local_tab_bounds = "710,2316,1050,2496"
    state.pending_local_tab_age = 0

    row = local_tab_logic._activate_forced_local_tab_target(
        client=client,
        dev="SERIAL",
        state=state,
        step_idx=17,
        wait_seconds=0.1,
        announcement_wait_seconds=0.1,
        announcement_idle_wait_seconds=0.0,
        announcement_max_extra_wait_seconds=0.0,
    )

    assert row["local_tab_activation_evidence"] == "observed_content_after_activation"
    assert "일정버튼" in state.visited_local_tabs_by_signature[signature]
    assert state.forced_local_tab_target_label == ""
    assert client.select_calls == []
    assert client.move_focus_smart_calls == []
    assert any("matched_by='observed_content_after_activation'" in line for line in logs)


def test_current_bottom_strip_focus_commits_visited_before_stale_ttl_state(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    signature = "위치버튼 위치||일정버튼 일정"
    candidates = [
        {
            **_bottom_strip_candidate("위치버튼 위치", 370, 710, rid=""),
            "actionable_label": "위치버튼",
            "canonical_visit_key": "위치버튼",
        },
        {
            **_bottom_strip_candidate("일정버튼 일정", 710, 1050, rid=""),
            "actionable_label": "일정버튼",
            "canonical_visit_key": "일정버튼",
        },
    ]
    _patch_content_candidates(monkeypatch, [])
    state = _local_tab_progression_state(
        signature,
        candidates,
        active_rid="",
        active_label="일정버튼 일정",
        visited={"일정버튼"},
    )
    state.current_local_tab_active_age = 1
    state.local_tab_content_confirmed_by_signature = {signature: {"일정버튼"}}
    row = {
        "visible_label": "위치버튼",
        "merged_announcement": "위치버튼",
        "focus_bounds": "370,2338,710,2473",
        "focus_clickable": True,
        "focus_focusable": True,
        "focus_effective_clickable": True,
        "focus_class_name": "android.view.View",
    }

    client = DummyClient([])
    advanced = local_tab_logic._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=27,
    )

    assert advanced is True
    assert "위치버튼" in state.visited_local_tabs_by_signature[signature]
    assert "위치버튼" not in state.local_tab_content_confirmed_by_signature[signature]
    assert row["local_tab_block_reason"] == ""
    assert client.select_calls == []
    assert len(client.click_focused_calls) == 1
    assert any("source='current_focus'" in line for line in logs)
    assert any("visit_key='위치버튼'" in line and "high_confidence_current_focus" in line for line in logs)


def test_activate_forced_local_tab_target_guard_skips_repeated_failures_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    client = DummyClient([
        {
            "step_index": 31,
            "visible_label": "Monitoring",
            "merged_announcement": "Monitoring",
            "focus_view_id": "com.example:id/monitoring_button",
            "focus_bounds": "40,1700,300,1860",
        }
    ])
    client.tap_xy_adb = lambda **kwargs: False
    client.select = lambda **kwargs: False
    signature = "monitoring||savings"
    state = SimpleNamespace(
        forced_local_tab_target_signature=signature,
        forced_local_tab_target_rid="com.example:id/savings_button",
        forced_local_tab_target_label="Savings",
        forced_local_tab_target_bounds="760,1700,1040,1860",
        forced_local_tab_attempt_count=1,
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/monitoring_button",
        current_local_tab_active_label="Monitoring",
        current_local_tab_active_age=0,
        visited_local_tabs_by_signature={signature: {"com.example:id/monitoring_button"}},
        pending_local_tab_signature=signature,
        pending_local_tab_rid="com.example:id/savings_button",
        pending_local_tab_label="Savings",
        pending_local_tab_bounds="760,1700,1040,1860",
        pending_local_tab_age=0,
        local_tab_activation_failures={
            local_tab_logic._local_tab_activation_failure_key(
                signature=signature,
                rid="com.example:id/savings_button",
                label="Savings",
            ): local_tab_logic.LOCAL_TAB_ACTIVATION_MAX_FAILURES
        },
    )

    row = local_tab_logic._activate_forced_local_tab_target(
        client=client,
        dev="SERIAL",
        state=state,
        step_idx=31,
        wait_seconds=0.1,
        announcement_wait_seconds=0.1,
        announcement_idle_wait_seconds=0.0,
        announcement_max_extra_wait_seconds=0.0,
    )

    assert row is None
    assert state.forced_local_tab_target_rid == ""
    assert state.pending_local_tab_rid == ""
    assert "com.example:id/savings_button" not in state.visited_local_tabs_by_signature[signature]
    assert "com.example:id/savings_button" in state.local_tab_activation_attempted_by_signature[signature]
    assert any("[LOCAL_TAB][activation_guard]" in line and "Savings" in line for line in logs)
    assert any("[LOCAL_TAB][skip_target]" in line and "Savings" in line for line in logs)


def test_activate_forced_local_tab_target_success_resets_failure_counter_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    client = DummyClient([
        {
            "step_index": 32,
            "visible_label": "Savings",
            "merged_announcement": "Savings",
            "focus_view_id": "com.example:id/savings_button",
            "focus_bounds": "760,1700,1040,1860",
        }
    ])
    signature = "monitoring||savings"
    failure_key = local_tab_logic._local_tab_activation_failure_key(
        signature=signature,
        rid="com.example:id/savings_button",
        label="Savings",
    )
    state = SimpleNamespace(
        forced_local_tab_target_signature=signature,
        forced_local_tab_target_rid="com.example:id/savings_button",
        forced_local_tab_target_label="Savings",
        forced_local_tab_target_bounds="760,1700,1040,1860",
        forced_local_tab_attempt_count=0,
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/monitoring_button",
        current_local_tab_active_label="Monitoring",
        current_local_tab_active_age=0,
        visited_local_tabs_by_signature={signature: {"com.example:id/monitoring_button"}},
        pending_local_tab_signature=signature,
        pending_local_tab_rid="com.example:id/savings_button",
        pending_local_tab_label="Savings",
        pending_local_tab_bounds="760,1700,1040,1860",
        pending_local_tab_age=0,
        fail_count=1,
        same_count=1,
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
        local_tab_activation_failures={failure_key: 2},
    )

    row = local_tab_logic._activate_forced_local_tab_target(
        client=client,
        dev="SERIAL",
        state=state,
        step_idx=32,
        wait_seconds=0.1,
        announcement_wait_seconds=0.1,
        announcement_idle_wait_seconds=0.0,
        announcement_max_extra_wait_seconds=0.0,
    )

    assert row["focus_view_id"] == "com.example:id/savings_button"
    assert failure_key not in state.local_tab_activation_failures
    assert state.current_local_tab_active_rid == "com.example:id/savings_button"


def test_local_tab_activation_failure_counts_are_per_target_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    state = SimpleNamespace(local_tab_activation_failures={})

    first_count, first_guarded = local_tab_logic._record_local_tab_activation_failure(
        state,
        signature="tabs",
        rid="com.example:id/savings_button",
        label="Savings",
    )
    second_count, second_guarded = local_tab_logic._record_local_tab_activation_failure(
        state,
        signature="tabs",
        rid="com.example:id/activity_button",
        label="Activity",
    )

    assert (first_count, first_guarded) == (1, False)
    assert (second_count, second_guarded) == (1, False)
    assert len(state.local_tab_activation_failures) == 2


def test_forced_local_tab_activation_fail_counter_survives_attempt_reset_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    client = DummyClient(
        [
            {
                "step_index": idx,
                "visible_label": "Monitoring",
                "merged_announcement": "Monitoring",
                "focus_view_id": "com.example:id/monitoring_button",
                "focus_bounds": "40,1700,300,1860",
            }
            for idx in range(40, 43)
        ]
    )
    client.tap_xy_adb = lambda **kwargs: False
    client.select = lambda **kwargs: False
    signature = "monitoring||savings"
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/monitoring_button",
        current_local_tab_active_label="Monitoring",
        current_local_tab_active_age=0,
        visited_local_tabs_by_signature={signature: {"com.example:id/monitoring_button"}},
        local_tab_activation_failures={},
        pending_local_tab_signature=signature,
        pending_local_tab_rid="com.example:id/savings_button",
        pending_local_tab_label="Savings",
        pending_local_tab_bounds="760,1700,1040,1860",
        pending_local_tab_age=0,
    )

    for idx in range(4):
        state.forced_local_tab_target_signature = signature
        state.forced_local_tab_target_rid = "com.example:id/savings_button"
        state.forced_local_tab_target_label = "Savings"
        state.forced_local_tab_target_bounds = "760,1700,1040,1860"
        state.forced_local_tab_attempt_count = 0
        local_tab_logic._activate_forced_local_tab_target(
            client=client,
            dev="SERIAL",
            state=state,
            step_idx=40 + idx,
            wait_seconds=0.1,
            announcement_wait_seconds=0.1,
            announcement_idle_wait_seconds=0.0,
            announcement_max_extra_wait_seconds=0.0,
        )

    failure_key = local_tab_logic._local_tab_activation_failure_key(
        signature=signature,
        rid="com.example:id/savings_button",
        label="Savings",
    )
    assert state.local_tab_activation_failures[failure_key] == 4
    assert "com.example:id/savings_button" not in state.visited_local_tabs_by_signature[signature]
    assert "com.example:id/savings_button" in state.local_tab_activation_attempted_by_signature[signature]
    assert state.pending_local_tab_rid == ""
    assert len([line for line in logs if "[STEP][local_tab_target_activate_fail]" in line]) == 4
    assert any("[LOCAL_TAB][activation_fail]" in line and "fail_count=4" in line for line in logs)
    assert sum(1 for line in logs if "[LOCAL_TAB][activation_guard]" in line) == 1
    assert sum(1 for line in logs if "[LOCAL_TAB][skip_target]" in line and "Savings" in line) >= 1
    assert len(client.move_focus_smart_calls) == 3


def test_pending_local_tab_ttl_records_failure_without_reset_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    signature = "monitoring||savings"
    failure_key = local_tab_logic._local_tab_activation_failure_key(
        signature=signature,
        rid="com.example:id/savings_button",
        label="Savings",
    )
    state = SimpleNamespace(
        pending_local_tab_signature=signature,
        pending_local_tab_rid="com.example:id/savings_button",
        pending_local_tab_label="Savings",
        pending_local_tab_bounds="760,1700,1040,1860",
        pending_local_tab_age=2,
        current_local_tab_active_rid="com.example:id/monitoring_button",
        current_local_tab_active_label="Monitoring",
        visited_local_tabs_by_signature={signature: {"com.example:id/monitoring_button"}},
        local_tab_activation_failures={failure_key: 2},
    )

    local_tab_logic._maybe_commit_pending_local_tab_progression(
        state,
        {
            "visible_label": "Monitoring",
            "merged_announcement": "Monitoring",
            "focus_view_id": "com.example:id/monitoring_button",
            "focus_bounds": "40,1700,300,1860",
        },
    )

    assert state.pending_local_tab_rid == ""
    assert state.local_tab_activation_failures[failure_key] == 3
    assert "com.example:id/savings_button" not in state.visited_local_tabs_by_signature[signature]
    assert any("[LOCAL_TAB][activation_fail]" in line and "pending_ttl_expired" in line for line in logs)
    assert not any("[LOCAL_TAB][activation_guard]" in line for line in logs)


def test_pending_local_tab_ttl_guard_skips_target_after_cap_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    signature = "monitoring||savings"
    failure_key = local_tab_logic._local_tab_activation_failure_key(
        signature=signature,
        rid="com.example:id/savings_button",
        label="Savings",
    )
    state = SimpleNamespace(
        pending_local_tab_signature=signature,
        pending_local_tab_rid="com.example:id/savings_button",
        pending_local_tab_label="Savings",
        pending_local_tab_bounds="760,1700,1040,1860",
        pending_local_tab_age=2,
        current_local_tab_active_rid="com.example:id/monitoring_button",
        current_local_tab_active_label="Monitoring",
        visited_local_tabs_by_signature={signature: {"com.example:id/monitoring_button"}},
        local_tab_activation_failures={failure_key: local_tab_logic.LOCAL_TAB_ACTIVATION_MAX_FAILURES},
    )

    local_tab_logic._maybe_commit_pending_local_tab_progression(
        state,
        {
            "visible_label": "Monitoring",
            "merged_announcement": "Monitoring",
            "focus_view_id": "com.example:id/monitoring_button",
            "focus_bounds": "40,1700,300,1860",
        },
    )

    assert state.local_tab_activation_failures[failure_key] == 4
    assert "com.example:id/savings_button" not in state.visited_local_tabs_by_signature[signature]
    assert "com.example:id/savings_button" in state.local_tab_activation_attempted_by_signature[signature]
    assert any("[LOCAL_TAB][activation_guard]" in line and "fail_count=4" in line for line in logs)
    assert any("[LOCAL_TAB][skip_target]" in line and "Savings" in line for line in logs)


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
        local_tab_content_confirmed_by_signature={
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
    assert any("[LOCAL_TAB][exhaustion]" in line and "all_tabs_content_confirmed=true" in line for line in logs)
    assert any("[STEP][local_tab_gate]" in line and "no_unvisited_local_tab" in line for line in logs)


def test_maybe_select_next_local_tab_guarded_target_converges_to_no_unvisited_direct(monkeypatch):
    logs = []
    _bind_local_tab_logic(monkeypatch, logs)
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    signature = "monitoring||savings"
    guarded_key = local_tab_logic._local_tab_activation_failure_key(
        signature=signature,
        rid="com.example:id/savings_button",
        label="Savings",
    )
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/monitoring_button",
        current_local_tab_active_label="Monitoring",
        current_local_tab_active_age=0,
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/monitoring_button", "label": "Monitoring", "left": 40, "node": {"boundsInScreen": "40,1700,300,1860"}},
                {"rid": "com.example:id/savings_button", "label": "Savings", "left": 760, "node": {"boundsInScreen": "760,1700,1040,1860"}},
            ]
        },
        visited_local_tabs_by_signature={signature: {"com.example:id/monitoring_button"}},
        local_tab_activation_failures={guarded_key: local_tab_logic.LOCAL_TAB_ACTIVATION_GUARD_TRIGGER_COUNT},
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/monitoring_button", "visible_label": "Monitoring"},
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
    row = {"focus_view_id": "com.example:id/monitoring_button", "visible_label": "Monitoring"}

    advanced = local_tab_logic._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_energy_plugin",
        step_idx=22,
    )

    assert advanced is False
    assert client.select_calls == []
    assert row["local_tab_block_reason"] == "unconfirmed_local_tab_content"
    assert state.pending_local_tab_rid == ""
    assert any("[LOCAL_TAB][skip_target]" in line and "Savings" in line for line in logs)
    assert any("[LOCAL_TAB][exhaustion]" in line and "all_tabs_content_confirmed=false" in line for line in logs)


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
