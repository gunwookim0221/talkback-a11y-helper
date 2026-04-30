import sys
from collections import deque
from types import SimpleNamespace

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, ExcelWriter=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow


def _row(
    *,
    label: str = "Current",
    rid: str = "id.current",
    bounds: str = "0,0,100,100",
    move_result: str = "moved",
) -> dict:
    return {
        "step_index": 1,
        "move_result": move_result,
        "last_smart_nav_result": move_result,
        "smart_nav_success": move_result in {"moved", "scrolled", "edge_realign_then_moved"},
        "visible_label": label,
        "merged_announcement": label,
        "normalized_visible_label": label.strip().lower(),
        "normalized_announcement": label.strip().lower(),
        "focus_view_id": rid,
        "focus_bounds": bounds,
        "focus_class_name": "android.widget.TextView",
    }


def _candidate(
    label: str,
    rid: str,
    bounds: str = "0,0,100,100",
    *,
    cluster_signature: str = "",
) -> dict:
    return {
        "label": label,
        "rid": rid,
        "bounds": bounds,
        "representative": True,
        "cluster_signature": cluster_signature,
        "passive_status": False,
        "low_value_leaf": False,
    }


def _state(**overrides):
    state = SimpleNamespace(
        fail_count=2,
        same_count=2,
        prev_fingerprint=("old", "id.old", "0,0,10,10"),
        previous_step_row=_row(label="Old", rid="id.old", bounds="0,0,10,10"),
        recent_representative_signatures=deque(maxlen=5),
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
        cta_cluster_visited_rids={},
        current_local_tab_signature="sig.current",
        current_local_tab_active_rid="id.active",
        current_local_tab_active_label="Active",
        current_local_tab_active_age=3,
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        pending_local_tab_signature="sig.pending",
        pending_local_tab_rid="id.pending",
        pending_local_tab_label="Pending",
        pending_local_tab_bounds="1,1,2,2",
        pending_local_tab_age=2,
        forced_local_tab_target_signature="sig.forced",
        forced_local_tab_target_rid="id.forced",
        forced_local_tab_target_label="Forced",
        forced_local_tab_target_bounds="2,2,3,3",
        forced_local_tab_attempt_count=1,
        active_container_group_signature="container:active",
        active_container_group_remaining={"sig.remaining"},
        active_container_group_labels={"sig.remaining": "Remaining"},
        completed_container_groups={"container:done"},
        scroll_ready_retry_counts={"cluster": 1},
        pending_scroll_ready_cluster_signature="cluster",
        content_phase_grace_steps=0,
        last_selected_local_tab_signature="",
        last_selected_local_tab_rid="",
        last_selected_local_tab_label="",
        last_selected_local_tab_bounds="",
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_fail_count_increments_on_no_progress():
    state = _state(fail_count=0, same_count=0)
    row = _row(label="Same", rid="id.same", bounds="0,0,10,10", move_result="failed")
    state.previous_step_row = dict(row)
    state.prev_fingerprint = ("same", "id.same", "0,0,10,10")

    _, state.fail_count, state.same_count, _, state.prev_fingerprint, details = collection_flow.should_stop(
        row=row,
        prev_fingerprint=state.prev_fingerprint,
        fail_count=state.fail_count,
        same_count=state.same_count,
        previous_row=state.previous_step_row,
        stop_policy={"stop_on_repeat_no_progress": False},
    )

    assert state.fail_count == 1
    assert state.same_count == 1
    assert details["no_progress"] is True


def test_same_count_resets_on_new_fingerprint():
    state = _state(fail_count=2, same_count=5)
    row = _row(label="New", rid="id.new", bounds="10,10,20,20", move_result="moved")

    _, state.fail_count, state.same_count, _, state.prev_fingerprint, details = collection_flow.should_stop(
        row=row,
        prev_fingerprint=state.prev_fingerprint,
        fail_count=state.fail_count,
        same_count=state.same_count,
        previous_row=state.previous_step_row,
    )

    assert state.fail_count == 0
    assert state.same_count == 0
    assert details["no_progress"] is False


def test_prev_fingerprint_updates_correctly():
    state = _state()
    row = _row(label="Next", rid="id.next", bounds="10,20,30,40", move_result="moved")

    _, state.fail_count, state.same_count, _, state.prev_fingerprint, _ = collection_flow.should_stop(
        row=row,
        prev_fingerprint=state.prev_fingerprint,
        fail_count=state.fail_count,
        same_count=state.same_count,
        previous_row=state.previous_step_row,
    )

    assert state.prev_fingerprint == ("next", "id.next", "10,20,30,40")


def test_previous_step_row_updates_each_step():
    state = _state()
    first = _row(label="First", rid="id.first")
    second = _row(label="Second", rid="id.second")

    state.previous_step_row = first
    state.previous_step_row = second

    assert state.previous_step_row is second
    assert state.previous_step_row["focus_view_id"] == "id.second"


def test_previous_step_row_resets_on_local_tab_switch():
    state = _state(previous_step_row=_row(label="Before", rid="id.before"))

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Events",
        active_rid="id.events",
        active_signature="sig.events",
        active_bounds="0,0,10,10",
    )

    assert state.previous_step_row == {}
    assert state.last_selected_local_tab_rid == "id.events"


def test_prev_fingerprint_resets_on_tab_transition():
    state = _state(prev_fingerprint=("before", "id.before", "0,0,1,1"))

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Events",
        active_rid="id.events",
        active_signature="sig.events",
        active_bounds="0,0,10,10",
    )

    assert state.prev_fingerprint == ("", "", "")
    assert state.fail_count == 0
    assert state.same_count == 0


def test_visited_logical_signature_blocks_revisit():
    visited = _candidate("Visited", "id.visited")
    state = _state(visited_logical_signatures={collection_flow._candidate_logical_signature(visited)})

    filtered = collection_flow._filter_content_candidates_for_phase([visited], state=state)

    assert filtered["visited_rejected"] == [visited]
    assert filtered["representative_candidates"] == []


def test_consumed_cluster_signature_blocks_cluster_revisit():
    consumed = _candidate("Consumed", "id.consumed", cluster_signature="cluster:consumed")
    state = _state(consumed_cluster_signatures={"cluster:consumed"})

    filtered = collection_flow._filter_content_candidates_for_phase([consumed], state=state)

    assert filtered["cluster_consumed_rejected"] == [consumed]
    assert filtered["representative_candidates"] == []


def test_visited_resets_on_tab_switch():
    state = _state(visited_logical_signatures={"id.visited||visited||none"})

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Events",
        active_rid="id.events",
        active_signature="sig.events",
        active_bounds="0,0,10,10",
    )

    assert state.visited_logical_signatures == set()


def test_consumed_cluster_resets_on_container_clear():
    state = _state(
        consumed_cluster_signatures={"cluster:consumed"},
        consumed_cluster_logical_signatures={"cluster||consumed"},
        active_container_group_signature="container:active",
        active_container_group_remaining={"sig.remaining"},
        completed_container_groups={"container:done"},
    )

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Events",
        active_rid="id.events",
        active_signature="sig.events",
        active_bounds="0,0,10,10",
    )

    assert state.consumed_cluster_signatures == set()
    assert state.consumed_cluster_logical_signatures == set()
    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert state.completed_container_groups == set()
