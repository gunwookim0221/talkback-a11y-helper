import sys
from collections import deque
from types import SimpleNamespace

import pytest

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, ExcelWriter=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow
from tb_runner import scroll_exhaustion_logic


class DummyClient:
    def __init__(self):
        self.dump_tree_sequence = []
        self.scroll_calls = []
        self.select_calls = []
        self.last_target_action_result = {}

    def dump_tree(self, **_kwargs):
        if self.dump_tree_sequence:
            return self.dump_tree_sequence.pop(0)
        return []

    def scroll(self, dev, direction, step_=50, time_=1000, bounds_=None):
        _ = (dev, step_, time_, bounds_)
        self.scroll_calls.append(direction)
        return True

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return True


class FailingScrollClient(DummyClient):
    def scroll(self, dev, direction, step_=50, time_=1000, bounds_=None):
        _ = (dev, step_, time_, bounds_)
        self.scroll_calls.append(direction)
        return False


@pytest.fixture(autouse=True)
def _quiet_logs(monkeypatch):
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": None)


def _candidate(label, rid, bounds, *, representative=True, passive_status=False, low_value_leaf=False):
    top = int(str(bounds).split(",")[1])
    left = int(str(bounds).split(",")[0])
    return {
        "label": label,
        "rid": rid,
        "bounds": bounds,
        "score": 100,
        "top": top,
        "left": left,
        "representative": representative,
        "passive_status": passive_status,
        "low_value_leaf": low_value_leaf,
        "top_priority_container": False,
    }


def _content_node(label, rid, bounds="40,420,1040,760"):
    return {
        "text": label,
        "contentDescription": "",
        "viewIdResourceName": rid,
        "className": "android.widget.FrameLayout",
        "clickable": True,
        "focusable": True,
        "effectiveClickable": True,
        "visibleToUser": True,
        "boundsInScreen": bounds,
        "children": [],
    }


def _scrollable_node():
    return {
        "viewIdResourceName": "com.example:id/content_recycler",
        "className": "androidx.recyclerview.widget.RecyclerView",
        "scrollable": True,
        "visibleToUser": True,
        "boundsInScreen": "0,200,1080,1900",
        "children": [],
    }


def _small_scrollable_node():
    return {
        "viewIdResourceName": "com.example:id/tiny_recycler",
        "className": "androidx.recyclerview.widget.RecyclerView",
        "scrollable": True,
        "visibleToUser": True,
        "boundsInScreen": "0,200,1080,300",
        "children": [],
    }


def _chrome_node():
    return {
        "text": "Navigate up",
        "contentDescription": "Navigate up",
        "viewIdResourceName": "com.example:id/navigate_up",
        "className": "android.widget.ImageButton",
        "clickable": True,
        "focusable": True,
        "effectiveClickable": True,
        "visibleToUser": True,
        "boundsInScreen": "0,0,120,120",
        "children": [],
    }


def _bottom_strip_row():
    return {
        "visible_label": "Location",
        "merged_announcement": "Location",
        "focus_view_id": "com.example:id/location_button",
        "focus_class_name": "android.widget.Button",
        "focus_bounds": "780,1700,1040,1860",
        "focus_clickable": True,
        "focus_focusable": True,
        "focus_effective_clickable": True,
    }


def _state(**overrides):
    signature = "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button"
    base = {
        "current_local_tab_signature": signature,
        "current_local_tab_active_rid": "com.example:id/location_button",
        "current_local_tab_active_label": "Location",
        "current_local_tab_active_age": 0,
        "local_tab_candidates_by_signature": {
            signature: [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
                {"rid": "com.example:id/events_button", "label": "Events", "node": {}},
            ]
        },
        "visited_local_tabs_by_signature": {
            signature: {"com.example:id/activity_button", "com.example:id/location_button"}
        },
        "fail_count": 2,
        "same_count": 2,
        "prev_fingerprint": ("a", "b", "c"),
        "previous_step_row": {"focus_view_id": "com.example:id/location_button"},
        "recent_representative_signatures": deque([], maxlen=5),
        "consumed_representative_signatures": set(),
        "consumed_cluster_signatures": set(),
        "consumed_cluster_logical_signatures": set(),
        "visited_logical_signatures": set(),
        "cta_cluster_visited_rids": {},
        "recent_scroll_fallback_signatures": set(),
        "last_scroll_fallback_attempted_signatures": set(),
        "scroll_ready_retry_counts": {},
        "pending_scroll_ready_cluster_signature": "",
        "active_container_group_signature": "",
        "active_container_group_remaining": set(),
        "active_container_group_labels": {},
        "completed_container_groups": set(),
        "content_phase_grace_steps": 0,
        "last_selected_local_tab_signature": "",
        "last_selected_local_tab_rid": "",
        "last_selected_local_tab_label": "",
        "last_selected_local_tab_bounds": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _state_with_scroll_state(**overrides):
    scroll_overrides = {
        key: overrides.pop(key)
        for key in list(overrides)
        if key
        in {
            "recent_scroll_fallback_signatures",
            "last_scroll_fallback_attempted_signatures",
            "scroll_ready_retry_counts",
            "pending_scroll_ready_cluster_signature",
        }
    }
    state = _state(**overrides)
    scroll_state = SimpleNamespace(
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
        scroll_ready_retry_counts={},
        pending_scroll_ready_cluster_signature="",
    )
    for key, value in scroll_overrides.items():
        setattr(scroll_state, key, value)
    state.scroll_state = scroll_state
    for key in (
        "recent_scroll_fallback_signatures",
        "last_scroll_fallback_attempted_signatures",
        "scroll_ready_retry_counts",
        "pending_scroll_ready_cluster_signature",
    ):
        if hasattr(state, key):
            delattr(state, key)
    return state


def test_viewport_not_exhausted_when_representative_candidate_remains():
    candidate = _candidate("Medication", "medicine", "40,420,1040,760")

    filtered = collection_flow._filter_content_candidates_for_phase([candidate], state=_state())

    assert filtered["representative_candidates"] == [candidate]
    assert filtered["exhaustion_candidates"] == [candidate]


def test_viewport_exhausted_when_visible_candidates_are_consumed_or_visited():
    consumed = _candidate("Medication", "medicine", "40,420,1040,760")
    visited = _candidate("Hospital", "hospital", "40,820,1040,1180")
    consumed_signature = collection_flow._candidate_object_signature(consumed)
    visited_signature = collection_flow._candidate_logical_signature(visited)

    filtered = collection_flow._filter_content_candidates_for_phase(
        [consumed, visited],
        state=_state(
            consumed_representative_signatures={consumed_signature},
            visited_logical_signatures={visited_signature},
        ),
    )

    assert filtered["representative_candidates"] == []
    assert filtered["exhaustion_candidates"] == []
    assert filtered["consumed_rejected"] == [consumed]
    assert filtered["visited_rejected"] == [visited]


def test_viewport_exhausted_when_only_status_and_leaf_candidates_remain():
    status = _candidate("No activity", "status", "40,420,1040,520", passive_status=True)
    leaf = _candidate("3", "tiny_leaf", "40,560,160,640", low_value_leaf=True)

    filtered = collection_flow._filter_content_candidates_for_phase([status, leaf], state=_state())

    assert filtered["status_candidates"] == [status]
    assert filtered["leaf_rejected"] == [leaf]
    assert filtered["representative_candidates"] == []
    assert filtered["exhaustion_candidates"] == []


def test_scroll_fallback_resumes_content_and_does_not_complete_active_container_group():
    active_group = "container_group:medication##hospital"
    row = {}
    state = _state(
        active_container_group_signature=active_group,
        active_container_group_remaining={"medication||signature"},
        active_container_group_labels={"medication||signature": "Medication"},
        completed_container_groups={"already||completed"},
    )
    client = DummyClient()
    client.dump_tree_sequence = [
        [_scrollable_node()],
        [_scrollable_node(), _content_node("Device usage", "com.example:id/device_usage_card")],
    ]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=10,
    )

    assert advanced is False
    assert client.scroll_calls == ["down"]
    assert row["scroll_fallback_resumed_content"] is True
    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert state.completed_container_groups == set()
    assert state.recent_scroll_fallback_signatures


def test_viewport_representative_candidate_blocks_scroll_fallback_gate():
    row = {}
    state = _state()
    client = DummyClient()
    client.dump_tree_sequence = [
        [_scrollable_node(), _content_node("Medication", "com.example:id/medicine_container")]
    ]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=13,
    )

    assert advanced is False
    assert client.scroll_calls == []
    assert row["viewport_exhausted_eval_result"] is False
    assert row["scroll_fallback_allowed"] is False
    assert row["scroll_fallback_gate_reason"] == "representative_still_exists"


def test_scroll_fallback_preserves_visited_and_consumed_state_after_resume():
    visited_signature = "visited||logical"
    consumed_signature = "consumed||cluster"
    row = {}
    state = _state(
        visited_logical_signatures={visited_signature},
        consumed_cluster_signatures={consumed_signature},
        consumed_cluster_logical_signatures={"consumed||logical"},
    )
    client = DummyClient()
    client.dump_tree_sequence = [
        [_scrollable_node()],
        [_scrollable_node(), _content_node("Medication", "com.example:id/medicine_container")],
    ]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=14,
    )

    assert advanced is False
    assert row["scroll_fallback_resumed_content"] is True
    assert state.visited_logical_signatures == {visited_signature}
    assert state.consumed_cluster_signatures == {consumed_signature}
    assert state.consumed_cluster_logical_signatures == {"consumed||logical"}
    assert state.completed_container_groups == set()


def test_scroll_fallback_allowed_when_only_chrome_status_and_leaf_remain():
    row = {}
    state = _state()
    client = DummyClient()
    client.dump_tree_sequence = [
        [
            _scrollable_node(),
            _chrome_node(),
            {
                "text": "No activity",
                "contentDescription": "",
                "viewIdResourceName": "com.example:id/status",
                "className": "android.widget.TextView",
                "clickable": False,
                "focusable": False,
                "effectiveClickable": False,
                "visibleToUser": True,
                "boundsInScreen": "40,420,1040,520",
                "children": [],
            },
            {
                "text": "3",
                "contentDescription": "",
                "viewIdResourceName": "com.example:id/tiny_leaf",
                "className": "android.widget.TextView",
                "clickable": False,
                "focusable": False,
                "effectiveClickable": False,
                "visibleToUser": True,
                "boundsInScreen": "40,560,160,640",
                "children": [],
            },
        ],
        [_scrollable_node(), _content_node("Medication", "com.example:id/medicine_container")],
    ]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=15,
    )

    assert advanced is False
    assert client.scroll_calls == ["down"]
    assert row["viewport_exhausted_eval_result"] is True
    assert row["scroll_fallback_allowed"] is True
    assert row["scroll_fallback_resumed_content"] is True


def test_scroll_fallback_same_signature_is_guarded_after_first_attempt():
    row = {}
    signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature=_state().current_local_tab_signature,
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    state = _state(
        recent_scroll_fallback_signatures={signature},
        last_scroll_fallback_attempted_signatures={signature},
    )
    client = DummyClient()
    client.dump_tree_sequence = [[_scrollable_node()]]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=11,
    )

    assert advanced is True
    assert client.scroll_calls == []
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert row["scroll_fallback_allowed"] is False
    assert row["scroll_fallback_gate_reason"] == "already_attempted_same_signature"


def test_scroll_fallback_new_signature_is_allowed_after_previous_attempt():
    row = {}
    current_signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature=_state().current_local_tab_signature,
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    state = _state(recent_scroll_fallback_signatures={"old||signature"})
    client = DummyClient()
    client.dump_tree_sequence = [
        [_scrollable_node()],
        [_scrollable_node(), _content_node("Medication", "com.example:id/medicine_container")],
    ]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=16,
    )

    assert advanced is False
    assert client.scroll_calls == ["down"]
    assert row["scroll_fallback_allowed"] is True
    assert row["scroll_fallback_gate_reason"] == "viewport_exhausted_direct_scroll"
    assert current_signature in state.recent_scroll_fallback_signatures
    assert "old||signature" in state.recent_scroll_fallback_signatures


def test_same_fallback_signature_guard_preserves_sets_without_tab_transition():
    row = {}
    signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature=_state().current_local_tab_signature,
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    state = _state(
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        recent_scroll_fallback_signatures={signature, "old||signature"},
        last_scroll_fallback_attempted_signatures={signature, "old||last"},
    )
    client = DummyClient()
    client.dump_tree_sequence = [[_scrollable_node()]]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=19,
    )

    assert advanced is False
    assert client.scroll_calls == []
    assert client.select_calls == []
    assert row["scroll_fallback_allowed"] is False
    assert row["scroll_fallback_gate_reason"] == "already_attempted_same_signature"
    assert state.recent_scroll_fallback_signatures == {signature, "old||signature"}
    assert state.last_scroll_fallback_attempted_signatures == {signature, "old||last"}


def test_local_tab_transition_resets_fallback_guards_and_scroll_ready_pending():
    row = {}
    signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature=_state().current_local_tab_signature,
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    state = _state(
        recent_scroll_fallback_signatures={signature, "old||signature"},
        last_scroll_fallback_attempted_signatures={signature, "old||last"},
        pending_scroll_ready_cluster_signature="cluster:pending",
        scroll_ready_retry_counts={"cluster:pending": 2},
    )
    client = DummyClient()
    client.dump_tree_sequence = [[_scrollable_node()]]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=20,
    )

    assert advanced is True
    assert client.scroll_calls == []
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert row["local_tab_transition"] is True
    assert row["scroll_fallback_gate_reason"] == "already_attempted_same_signature"
    assert state.recent_scroll_fallback_signatures == set()
    assert state.last_scroll_fallback_attempted_signatures == set()
    assert state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_ready_retry_counts == {}


def test_scroll_failure_preserves_fallback_guard_without_tab_transition():
    row = {}
    state = _state(
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        recent_scroll_fallback_signatures={"old||signature"},
        pending_scroll_ready_cluster_signature="cluster:pending",
        scroll_ready_retry_counts={"cluster:pending": 1},
    )
    client = FailingScrollClient()
    client.dump_tree_sequence = [[_scrollable_node()]]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=21,
    )

    assert advanced is False
    assert client.scroll_calls == ["down"]
    assert row["scroll_fallback_allowed"] is True
    assert row["scroll_fallback_gate_reason"] == "viewport_exhausted_direct_scroll"
    assert "old||signature" in state.recent_scroll_fallback_signatures
    assert len(state.recent_scroll_fallback_signatures) == 2
    assert state.pending_scroll_ready_cluster_signature == "cluster:pending"
    assert state.scroll_ready_retry_counts == {"cluster:pending": 1}


def test_scroll_success_records_fallback_signature_and_preserves_pending_when_content_resumes():
    row = {}
    state = _state(
        recent_scroll_fallback_signatures={"old||signature"},
        pending_scroll_ready_cluster_signature="cluster:pending",
        scroll_ready_retry_counts={"cluster:pending": 1},
    )
    client = DummyClient()
    client.dump_tree_sequence = [
        [_scrollable_node()],
        [_scrollable_node(), _content_node("Medication", "com.example:id/medicine_container")],
    ]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=22,
    )

    assert advanced is False
    assert client.scroll_calls == ["down"]
    assert row["scroll_fallback_allowed"] is True
    assert row["scroll_fallback_resumed_content"] is True
    assert "old||signature" in state.recent_scroll_fallback_signatures
    assert len(state.recent_scroll_fallback_signatures) == 2
    assert state.pending_scroll_ready_cluster_signature == "cluster:pending"
    assert state.scroll_ready_retry_counts == {"cluster:pending": 1}


def test_last_scroll_no_content_marks_global_exhausted_without_completing_group():
    row = _bottom_strip_row()
    signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature=_state().current_local_tab_signature,
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    state = _state(
        visited_local_tabs_by_signature={
            _state().current_local_tab_signature: {
                "com.example:id/activity_button",
                "com.example:id/location_button",
                "com.example:id/events_button",
            }
        },
        recent_scroll_fallback_signatures={signature},
        active_container_group_signature="container_group:old",
        active_container_group_remaining={"old||signature"},
        active_container_group_labels={"old||signature": "Old"},
        completed_container_groups={"already||completed"},
    )
    client = DummyClient()
    client.dump_tree_sequence = [[_scrollable_node()], [_scrollable_node()]]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=12,
    )

    assert advanced is True
    assert client.scroll_calls == ["down"]
    assert row["last_scroll_fallback_allowed"] is True
    assert row["last_scroll_fallback_resumed_content"] is False
    assert row["last_scroll_global_exhausted"] is True
    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert state.completed_container_groups == set()


def test_last_scroll_new_signature_allowed_when_previous_signature_attempted():
    row = _bottom_strip_row()
    current_signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature=_state().current_local_tab_signature,
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    state = _state(
        visited_local_tabs_by_signature={
            _state().current_local_tab_signature: {
                "com.example:id/activity_button",
                "com.example:id/location_button",
                "com.example:id/events_button",
            }
        },
        recent_scroll_fallback_signatures={current_signature},
        last_scroll_fallback_attempted_signatures={"old||last"},
    )
    client = DummyClient()
    client.dump_tree_sequence = [[_scrollable_node()], [_scrollable_node()]]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=17,
    )

    assert advanced is True
    assert client.scroll_calls == ["down"]
    assert row["last_scroll_fallback_allowed"] is True
    assert row["last_scroll_block_reason"] == ""
    assert row["last_scroll_global_exhausted"] is True
    assert row["local_tab_transition"] is True
    assert state.last_scroll_fallback_attempted_signatures == set()


def test_scroll_failure_does_not_complete_active_container_group():
    active_group = "container_group:medication##hospital"
    row = {}
    state = _state(
        active_container_group_signature=active_group,
        active_container_group_remaining={"medication||signature"},
        active_container_group_labels={"medication||signature": "Medication"},
        completed_container_groups={"already||completed"},
    )
    client = FailingScrollClient()
    client.dump_tree_sequence = [[_scrollable_node()]]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=18,
    )

    assert advanced is True
    assert client.scroll_calls == ["down"]
    assert row["scroll_fallback_allowed"] is True
    assert row.get("scroll_fallback_resumed_content") is not True
    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert state.completed_container_groups == set()


def test_scroll_ready_continue_does_not_override_safety_limit_stop_reason():
    state = _state(scroll_ready_retry_counts={"cluster:medication": 1})
    row = {
        "scroll_ready_state": True,
        "scroll_ready_cluster_signature": "cluster:medication",
        "move_result": "moved",
    }

    stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
        row=row,
        stop=True,
        reason="safety_limit",
        stop_eval_inputs={"terminal_signal": False, "is_global_nav": False},
        state=state,
        step_idx=13,
        scenario_id="life_family_care_plugin",
    )

    assert stop is True
    assert reason == "safety_limit"
    assert applied is False
    assert state.scroll_ready_retry_counts == {"cluster:medication": 1}
    assert state.pending_scroll_ready_cluster_signature == ""


def test_scroll_ready_continue_sets_pending_once_for_repeat_no_progress():
    state = _state()
    row = {
        "scroll_ready_state": True,
        "scroll_ready_cluster_signature": "cluster:medication",
        "move_result": "moved",
    }

    stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
        row=row,
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"terminal_signal": False, "is_global_nav": False},
        state=state,
        step_idx=14,
        scenario_id="life_family_care_plugin",
    )

    assert stop is False
    assert reason == ""
    assert applied is True
    assert state.scroll_ready_retry_counts == {"cluster:medication": 1}
    assert state.pending_scroll_ready_cluster_signature == "cluster:medication"


def test_describe_scrollable_content_phase_detects_scrollable_content_bounds():
    nodes = [_scrollable_node(), _content_node("Device usage", "com.example:id/device_usage_card")]

    scrollable, labels, bounds = collection_flow._describe_scrollable_content_phase(nodes)

    assert scrollable is True
    assert labels == ["com.example:id/content_recycler"]
    assert bounds == "0,200,1080,1900"


@pytest.mark.parametrize(
    "nodes",
    [
        [],
        [_chrome_node()],
        [_small_scrollable_node()],
        [{"viewIdResourceName": "hidden", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": False, "boundsInScreen": "0,200,1080,1900"}],
    ],
)
def test_describe_scrollable_content_phase_returns_false_without_content_scrollable(nodes):
    scrollable, labels, bounds = collection_flow._describe_scrollable_content_phase(nodes)

    assert scrollable is False
    assert bounds == ""
    if not nodes or nodes[0].get("visibleToUser") is False:
        assert labels == []


def test_build_scroll_fallback_signature_is_stable_for_same_viewport():
    content = [
        _candidate("Medication", "medicine", "40,420,1040,760"),
        _candidate("Hospital", "hospital", "40,820,1040,1180"),
    ]

    first = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="activity||location",
        active_rid="location",
        content_candidates=content,
        chrome_excluded=["Navigate up", "More options"],
        current_focus_signature="focus||location",
    )
    second = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="activity||location",
        active_rid="location",
        content_candidates=list(content),
        chrome_excluded=["Navigate up", "More options"],
        current_focus_signature="focus||location",
    )

    assert first == second


def test_build_scroll_fallback_signature_changes_when_viewport_changes():
    base = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="activity||location",
        active_rid="location",
        content_candidates=[_candidate("Medication", "medicine", "40,420,1040,760")],
        chrome_excluded=["Navigate up"],
        current_focus_signature="focus||location",
    )
    changed_content = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="activity||location",
        active_rid="location",
        content_candidates=[_candidate("Hospital", "hospital", "40,820,1040,1180")],
        chrome_excluded=["Navigate up"],
        current_focus_signature="focus||location",
    )
    changed_focus = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="activity||location",
        active_rid="location",
        content_candidates=[_candidate("Medication", "medicine", "40,420,1040,760")],
        chrome_excluded=["Navigate up"],
        current_focus_signature="focus||hospital",
    )

    assert changed_content != base
    assert changed_focus != base


def test_scroll_ready_continue_attempt_limit_clears_pending_without_overriding_reason():
    state = _state(scroll_ready_retry_counts={"cluster:medication": 2}, pending_scroll_ready_cluster_signature="cluster:medication")
    row = {
        "scroll_ready_state": True,
        "scroll_ready_cluster_signature": "cluster:medication",
        "move_result": "moved",
    }

    stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
        row=row,
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"terminal_signal": False, "is_global_nav": False},
        state=state,
        step_idx=15,
        scenario_id="life_family_care_plugin",
    )

    assert stop is True
    assert reason == "repeat_no_progress"
    assert applied is False
    assert state.scroll_ready_retry_counts == {"cluster:medication": 2}
    assert state.pending_scroll_ready_cluster_signature == ""


def test_scroll_ready_continue_ignores_terminal_and_global_nav_contexts():
    for stop_eval_inputs in [
        {"terminal_signal": True, "is_global_nav": False},
        {"terminal_signal": False, "is_global_nav": True},
    ]:
        state = _state()
        row = {
            "scroll_ready_state": True,
            "scroll_ready_cluster_signature": "cluster:medication",
            "move_result": "moved",
        }

        stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
            row=row,
            stop=True,
            reason="repeat_no_progress",
            stop_eval_inputs=stop_eval_inputs,
            state=state,
            step_idx=16,
            scenario_id="life_family_care_plugin",
        )

        assert stop is True
        assert reason == "repeat_no_progress"
        assert applied is False
        assert state.scroll_ready_retry_counts == {}
        assert state.pending_scroll_ready_cluster_signature == ""


def _pending_scroll_ready_callbacks(*, normalized_result="moved"):
    calls = {"log": [], "truncate": [], "normalize": []}

    def log_fn(message):
        calls["log"].append(message)

    def truncate_fn(value, limit):
        calls["truncate"].append((value, limit))
        return str(value)

    def normalize_move_result_fn(row):
        calls["normalize"].append(row)
        return normalized_result

    return calls, log_fn, truncate_fn, normalize_move_result_fn


def test_record_pending_scroll_ready_move_impl_no_pending_is_noop():
    state = _state(scroll_ready_retry_counts={"cluster:medication": 1}, pending_scroll_ready_cluster_signature="")
    row = {"move_result": "moved", "visible_label": "Medication"}
    calls, log_fn, truncate_fn, normalize_fn = _pending_scroll_ready_callbacks()

    scroll_exhaustion_logic._record_pending_scroll_ready_move_impl(
        row=row,
        state=state,
        step_idx=17,
        scenario_id="life_family_care_plugin",
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_ready_retry_counts == {"cluster:medication": 1}
    assert calls == {"log": [], "truncate": [], "normalize": []}


@pytest.mark.parametrize("move_result", ["moved", "scrolled", "edge_realign_then_moved"])
def test_record_pending_scroll_ready_move_impl_success_clears_pending_and_retry(move_result):
    state = _state(
        scroll_ready_retry_counts={"cluster:medication": 1, "cluster:hospital": 1},
        pending_scroll_ready_cluster_signature="cluster:medication",
    )
    row = {"move_result": move_result, "visible_label": "Medication"}
    calls, log_fn, truncate_fn, normalize_fn = _pending_scroll_ready_callbacks(normalized_result=move_result)

    scroll_exhaustion_logic._record_pending_scroll_ready_move_impl(
        row=row,
        state=state,
        step_idx=18,
        scenario_id="life_family_care_plugin",
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_ready_retry_counts == {"cluster:hospital": 1}
    assert len(calls["log"]) == 1
    assert calls["normalize"] == [row]


def test_record_pending_scroll_ready_move_impl_non_success_keeps_pending_and_retry():
    state = _state(
        scroll_ready_retry_counts={"cluster:medication": 1},
        pending_scroll_ready_cluster_signature="cluster:medication",
    )
    row = {"move_result": "failed", "visible_label": "Medication"}
    calls, log_fn, truncate_fn, normalize_fn = _pending_scroll_ready_callbacks(normalized_result="failed")

    scroll_exhaustion_logic._record_pending_scroll_ready_move_impl(
        row=row,
        state=state,
        step_idx=19,
        scenario_id="life_family_care_plugin",
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert state.pending_scroll_ready_cluster_signature == "cluster:medication"
    assert state.scroll_ready_retry_counts == {"cluster:medication": 1}
    assert len(calls["log"]) == 1
    assert calls["normalize"] == [row]


def test_record_pending_scroll_ready_move_impl_calls_normalize_with_row():
    state = _state(
        scroll_ready_retry_counts={"cluster:medication": 1},
        pending_scroll_ready_cluster_signature="cluster:medication",
    )
    row = {"move_result": "ignored-by-normalize", "visible_label": "Medication"}
    calls, log_fn, truncate_fn, normalize_fn = _pending_scroll_ready_callbacks(normalized_result="scrolled")

    scroll_exhaustion_logic._record_pending_scroll_ready_move_impl(
        row=row,
        state=state,
        step_idx=20,
        scenario_id="life_family_care_plugin",
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert calls["normalize"] == [row]
    assert state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_ready_retry_counts == {}


def test_record_pending_scroll_ready_move_impl_uses_truncate_and_log_stubs():
    state = _state(
        scroll_ready_retry_counts={"cluster:medication": 1},
        pending_scroll_ready_cluster_signature="cluster:medication",
    )
    row = {"move_result": "moved", "visible_label": "Medication"}
    calls, log_fn, truncate_fn, normalize_fn = _pending_scroll_ready_callbacks(normalized_result="moved")

    scroll_exhaustion_logic._record_pending_scroll_ready_move_impl(
        row=row,
        state=state,
        step_idx=21,
        scenario_id="life_family_care_plugin",
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert len(calls["log"]) == 1
    assert ("cluster:medication", 120) in calls["truncate"]
    assert ("moved", 48) in calls["truncate"]
    assert ("Medication", 120) in calls["truncate"]


def test_scroll_state_pending_cluster_set_on_scroll_ready_continue():
    state = _state()
    row = {
        "scroll_ready_state": True,
        "scroll_ready_cluster_signature": "cluster:medication",
        "move_result": "moved",
    }

    stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
        row=row,
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"terminal_signal": False, "is_global_nav": False},
        state=state,
        step_idx=22,
        scenario_id="life_family_care_plugin",
    )

    assert stop is False
    assert reason == ""
    assert applied is True
    assert state.pending_scroll_ready_cluster_signature == "cluster:medication"
    assert state.scroll_ready_retry_counts == {"cluster:medication": 1}


def test_scroll_state_retry_count_increments_per_cluster():
    state = _state(scroll_ready_retry_counts={"cluster:medication": 1, "cluster:hospital": 1})
    row = {
        "scroll_ready_state": True,
        "scroll_ready_cluster_signature": "cluster:medication",
        "move_result": "moved",
    }

    stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
        row=row,
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"terminal_signal": False, "is_global_nav": False},
        state=state,
        step_idx=23,
        scenario_id="life_family_care_plugin",
    )

    assert stop is False
    assert reason == ""
    assert applied is True
    assert state.pending_scroll_ready_cluster_signature == "cluster:medication"
    assert state.scroll_ready_retry_counts == {"cluster:medication": 2, "cluster:hospital": 1}


def test_scroll_state_successful_scroll_ready_move_clears_pending_and_retry():
    state = _state(
        scroll_ready_retry_counts={"cluster:medication": 1, "cluster:hospital": 1},
        pending_scroll_ready_cluster_signature="cluster:medication",
    )
    row = {"move_result": "edge_realign_then_moved", "visible_label": "Medication"}
    calls, log_fn, truncate_fn, normalize_fn = _pending_scroll_ready_callbacks(normalized_result="edge_realign_then_moved")

    scroll_exhaustion_logic._record_pending_scroll_ready_move_impl(
        row=row,
        state=state,
        step_idx=24,
        scenario_id="life_family_care_plugin",
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_ready_retry_counts == {"cluster:hospital": 1}
    assert len(calls["log"]) == 1


def test_scroll_state_non_success_move_preserves_pending_and_retry():
    state = _state(
        scroll_ready_retry_counts={"cluster:medication": 1},
        pending_scroll_ready_cluster_signature="cluster:medication",
    )
    row = {"move_result": "failed", "visible_label": "Medication"}
    calls, log_fn, truncate_fn, normalize_fn = _pending_scroll_ready_callbacks(normalized_result="failed")

    scroll_exhaustion_logic._record_pending_scroll_ready_move_impl(
        row=row,
        state=state,
        step_idx=25,
        scenario_id="life_family_care_plugin",
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert state.pending_scroll_ready_cluster_signature == "cluster:medication"
    assert state.scroll_ready_retry_counts == {"cluster:medication": 1}
    assert len(calls["log"]) == 1


def test_scroll_state_fallback_guard_prevents_duplicate_attempt():
    row = {}
    signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature=_state().current_local_tab_signature,
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    state = _state(
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        recent_scroll_fallback_signatures={signature},
        last_scroll_fallback_attempted_signatures=set(),
    )
    client = DummyClient()
    client.dump_tree_sequence = [[_scrollable_node()]]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=26,
    )

    assert advanced is False
    assert client.scroll_calls == []
    assert client.select_calls == []
    assert row["scroll_fallback_allowed"] is False
    assert row["scroll_fallback_gate_reason"] == "already_attempted_same_signature"
    assert state.recent_scroll_fallback_signatures == {signature}
    assert state.last_scroll_fallback_attempted_signatures == set()


def test_scroll_state_last_fallback_guard_blocks_repeated_attempt():
    row = _bottom_strip_row()
    signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature=_state().current_local_tab_signature,
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    state = _state(
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        recent_scroll_fallback_signatures={signature},
        last_scroll_fallback_attempted_signatures={signature},
    )
    client = DummyClient()
    client.dump_tree_sequence = [[_scrollable_node()]]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=27,
    )

    assert advanced is False
    assert client.scroll_calls == []
    assert client.select_calls == []
    assert row["last_scroll_fallback_evaluated"] is True
    assert row["last_scroll_fallback_allowed"] is False
    assert row["last_scroll_block_reason"] == "last_scroll_already_attempted"
    assert state.last_scroll_fallback_attempted_signatures == {signature}


def test_scroll_state_same_signature_allows_single_attempt():
    row = {}
    signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature=_state().current_local_tab_signature,
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    state = _state(recent_scroll_fallback_signatures=set())
    client = DummyClient()
    client.dump_tree_sequence = [
        [_scrollable_node()],
        [_scrollable_node(), _content_node("Medication", "com.example:id/medicine_container")],
    ]

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=28,
    )

    assert advanced is False
    assert client.scroll_calls == ["down"]
    assert row["scroll_fallback_allowed"] is True
    assert signature in state.recent_scroll_fallback_signatures


def test_scroll_state_local_tab_transition_resets_pending_and_retry():
    state = _state(
        pending_scroll_ready_cluster_signature="cluster:medication",
        scroll_ready_retry_counts={"cluster:medication": 2},
    )

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Event",
        active_rid="com.example:id/events_button",
        active_signature=state.current_local_tab_signature,
        active_bounds="720,1800,1060,1920",
    )

    assert state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_ready_retry_counts == {}


def test_scroll_state_local_tab_transition_clears_fallback_guards():
    state = _state(
        recent_scroll_fallback_signatures={"sig:recent"},
        last_scroll_fallback_attempted_signatures={"sig:last"},
    )

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Event",
        active_rid="com.example:id/events_button",
        active_signature=state.current_local_tab_signature,
        active_bounds="720,1800,1060,1920",
    )

    assert state.recent_scroll_fallback_signatures == set()
    assert state.last_scroll_fallback_attempted_signatures == set()


def test_scroll_state_no_cluster_signature_no_retry():
    state = _state(scroll_ready_retry_counts={"cluster:medication": 1})
    row = {
        "scroll_ready_state": True,
        "scroll_ready_cluster_signature": "",
        "move_result": "moved",
    }

    stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
        row=row,
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"terminal_signal": False, "is_global_nav": False},
        state=state,
        step_idx=29,
        scenario_id="life_family_care_plugin",
    )

    assert stop is True
    assert reason == "repeat_no_progress"
    assert applied is False
    assert state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_ready_retry_counts == {"cluster:medication": 1}


def test_scroll_state_retry_limit_does_not_increase_unbounded():
    state = _state(
        scroll_ready_retry_counts={"cluster:medication": 2},
        pending_scroll_ready_cluster_signature="cluster:medication",
    )
    row = {
        "scroll_ready_state": True,
        "scroll_ready_cluster_signature": "cluster:medication",
        "move_result": "moved",
    }

    stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
        row=row,
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"terminal_signal": False, "is_global_nav": False},
        state=state,
        step_idx=30,
        scenario_id="life_family_care_plugin",
    )

    assert stop is True
    assert reason == "repeat_no_progress"
    assert applied is False
    assert state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_ready_retry_counts == {"cluster:medication": 2}


def test_scroll_ready_continue_updates_nested_scroll_state_without_direct_fields():
    state = _state_with_scroll_state()
    row = {
        "scroll_ready_state": True,
        "scroll_ready_cluster_signature": "cluster:medication",
        "move_result": "moved",
    }

    stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
        row=row,
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"terminal_signal": False, "is_global_nav": False},
        state=state,
        step_idx=31,
        scenario_id="life_family_care_plugin",
    )

    assert stop is False
    assert reason == ""
    assert applied is True
    assert state.scroll_state.pending_scroll_ready_cluster_signature == "cluster:medication"
    assert state.scroll_state.scroll_ready_retry_counts == {"cluster:medication": 1}
    assert not hasattr(state, "pending_scroll_ready_cluster_signature")
    assert not hasattr(state, "scroll_ready_retry_counts")


def test_pending_scroll_ready_move_clears_nested_scroll_state_without_direct_fields():
    state = _state_with_scroll_state(
        scroll_ready_retry_counts={"cluster:medication": 1, "cluster:hospital": 1},
        pending_scroll_ready_cluster_signature="cluster:medication",
    )
    row = {"move_result": "moved", "visible_label": "Medication"}
    calls, log_fn, truncate_fn, normalize_fn = _pending_scroll_ready_callbacks(normalized_result="moved")

    scroll_exhaustion_logic._record_pending_scroll_ready_move_impl(
        row=row,
        state=state,
        step_idx=32,
        scenario_id="life_family_care_plugin",
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert state.scroll_state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_state.scroll_ready_retry_counts == {"cluster:hospital": 1}
    assert len(calls["log"]) == 1
    assert not hasattr(state, "pending_scroll_ready_cluster_signature")
    assert not hasattr(state, "scroll_ready_retry_counts")


def test_local_tab_transition_resets_nested_scroll_state_without_direct_fields():
    state = _state_with_scroll_state(
        recent_scroll_fallback_signatures={"sig:recent"},
        last_scroll_fallback_attempted_signatures={"sig:last"},
        scroll_ready_retry_counts={"cluster:medication": 2},
        pending_scroll_ready_cluster_signature="cluster:medication",
    )

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Event",
        active_rid="com.example:id/events_button",
        active_signature=state.current_local_tab_signature,
        active_bounds="720,1800,1060,1920",
    )

    assert state.scroll_state.recent_scroll_fallback_signatures == set()
    assert state.scroll_state.last_scroll_fallback_attempted_signatures == set()
    assert state.scroll_state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_state.scroll_ready_retry_counts == {}
    assert not hasattr(state, "recent_scroll_fallback_signatures")
    assert not hasattr(state, "last_scroll_fallback_attempted_signatures")
    assert not hasattr(state, "pending_scroll_ready_cluster_signature")
    assert not hasattr(state, "scroll_ready_retry_counts")
