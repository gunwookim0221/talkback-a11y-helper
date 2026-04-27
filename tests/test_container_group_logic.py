import sys
from collections import deque
from types import SimpleNamespace

import pytest

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, ExcelWriter=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow
from tb_runner import container_group_logic


@pytest.fixture(autouse=True)
def _quiet_logs(monkeypatch):
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": None)


def _container(label, rid, bounds, *, score=100, top_priority=True):
    top = int(str(bounds).split(",")[1])
    left = int(str(bounds).split(",")[0])
    return {
        "label": label,
        "rid": rid,
        "bounds": bounds,
        "score": score,
        "top": top,
        "left": left,
        "representative": True,
        "passive_status": False,
        "low_value_leaf": False,
        "top_priority_container": top_priority,
    }


def _state(**overrides):
    base = {
        "recent_representative_signatures": deque([], maxlen=5),
        "consumed_representative_signatures": set(),
        "consumed_cluster_signatures": set(),
        "consumed_cluster_logical_signatures": set(),
        "visited_logical_signatures": set(),
        "cta_cluster_visited_rids": {},
        "active_container_group_signature": "",
        "active_container_group_remaining": set(),
        "active_container_group_labels": {},
        "completed_container_groups": set(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _progress_state_snapshot(state):
    return {
        "active_container_group_signature": state.active_container_group_signature,
        "active_container_group_remaining": set(state.active_container_group_remaining),
        "active_container_group_labels": dict(state.active_container_group_labels),
        "completed_container_groups": set(state.completed_container_groups),
        "consumed_cluster_signatures": set(state.consumed_cluster_signatures),
        "consumed_cluster_logical_signatures": set(state.consumed_cluster_logical_signatures),
        "visited_logical_signatures": set(state.visited_logical_signatures),
    }


def test_collect_step_candidate_priority_groups_promotes_clickable_container_over_leaf():
    nodes = [
        {
            "text": "Medication",
            "viewIdResourceName": "com.example:id/medication_container",
            "className": "android.widget.LinearLayout",
            "clickable": True,
            "focusable": True,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "40,320,1040,520",
            "children": [
                {
                    "text": "Medication details",
                    "viewIdResourceName": "com.example:id/medication_text",
                    "className": "android.widget.TextView",
                    "visibleToUser": True,
                    "boundsInScreen": "80,360,980,430",
                    "children": [],
                }
            ],
        },
        {
            "text": "Medication",
            "viewIdResourceName": "com.example:id/medication_text_leaf",
            "className": "android.widget.TextView",
            "visibleToUser": True,
            "boundsInScreen": "80,560,980,640",
            "children": [],
        },
    ]

    content, bottom_strip, meta = collection_flow._collect_step_candidate_priority_groups(nodes)

    assert bottom_strip == []
    assert any(candidate["rid"] == "com.example:id/medication_container" for candidate in content)
    selected = next(candidate for candidate in content if candidate["rid"] == "com.example:id/medication_container")
    assert selected["top_priority_container"] is True
    assert selected["representative"] is True
    assert "Medication" in meta["top_priority_container_candidates"]


def test_container_group_start_creates_active_state_and_narrows_candidates():
    containers = [
        _container("Medication", "medication", "40,300,1040,480"),
        _container("Hospital", "hospital", "40,520,1040,700"),
        _container("Event", "event", "40,740,1040,920"),
    ]
    candidates = [
        *containers,
        _container("Plain detail", "plain_detail", "80,960,980,1060", top_priority=False),
    ]
    state = _state()

    filtered = collection_flow._filter_content_candidates_for_phase(candidates, state=state)

    expected_signatures = {collection_flow._candidate_object_signature(candidate) for candidate in containers}
    assert filtered["container_priority_applied"] is True
    assert filtered["container_priority_reason"] == "repeated_container_group"
    assert {candidate["rid"] for candidate in filtered["representative_candidates"]} == {"medication", "hospital", "event"}
    assert state.active_container_group_signature == collection_flow._container_group_signature(containers)
    assert state.active_container_group_remaining == expected_signatures
    assert set(state.active_container_group_labels.values()) == {"Medication", "Hospital", "Event"}


def test_container_group_start_signature_is_stable_across_candidate_order():
    containers = [
        _container("Medication", "medication", "40,300,1040,480"),
        _container("Hospital", "hospital", "40,520,1040,700"),
        _container("Event", "event", "40,740,1040,920"),
    ]
    forward_state = _state()
    reversed_state = _state()

    collection_flow._filter_content_candidates_for_phase(containers, state=forward_state)
    collection_flow._filter_content_candidates_for_phase(list(reversed(containers)), state=reversed_state)

    assert forward_state.active_container_group_signature
    assert forward_state.active_container_group_signature == reversed_state.active_container_group_signature
    assert forward_state.active_container_group_remaining == reversed_state.active_container_group_remaining


def test_container_group_progress_completes_group_after_remaining_consumed():
    first = _container("Medication", "medication", "40,300,1040,480")
    second = _container("Hospital", "hospital", "40,520,1040,700")
    group_signature = collection_flow._container_group_signature([first, second])
    first_signature = collection_flow._candidate_object_signature(first)
    second_signature = collection_flow._candidate_object_signature(second)
    state = _state(
        active_container_group_signature=group_signature,
        active_container_group_remaining={first_signature, second_signature},
        active_container_group_labels={first_signature: "Medication", second_signature: "Hospital"},
    )

    collection_flow._record_active_container_group_progress(state, first_signature)
    assert state.active_container_group_remaining == {second_signature}
    assert state.completed_container_groups == set()

    collection_flow._record_active_container_group_progress(state, second_signature)
    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert group_signature in state.completed_container_groups


def test_last_container_consumed_clears_active_group_and_marks_completed():
    first = _container("Medication", "medication", "40,300,1040,480")
    group_signature = collection_flow._container_group_signature([first])
    first_signature = collection_flow._candidate_object_signature(first)
    state = _state(
        active_container_group_signature=group_signature,
        active_container_group_remaining={first_signature},
        active_container_group_labels={first_signature: "Medication"},
    )

    collection_flow._record_active_container_group_progress(state, first_signature)

    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert state.active_container_group_labels == {}
    assert group_signature in state.completed_container_groups


def test_container_group_progress_ignores_signature_not_in_remaining():
    first = _container("Medication", "medication", "40,300,1040,480")
    second = _container("Hospital", "hospital", "40,520,1040,700")
    group_signature = collection_flow._container_group_signature([first, second])
    first_signature = collection_flow._candidate_object_signature(first)
    second_signature = collection_flow._candidate_object_signature(second)
    state = _state(
        active_container_group_signature=group_signature,
        active_container_group_remaining={first_signature, second_signature},
        active_container_group_labels={first_signature: "Medication", second_signature: "Hospital"},
    )
    before = _progress_state_snapshot(state)

    collection_flow._record_active_container_group_progress(state, "missing||signature")

    assert _progress_state_snapshot(state) == before


@pytest.mark.parametrize("consumed_signature", ["", None])
def test_container_group_progress_no_signature_is_noop(consumed_signature):
    first = _container("Medication", "medication", "40,300,1040,480")
    group_signature = collection_flow._container_group_signature([first])
    first_signature = collection_flow._candidate_object_signature(first)
    state = _state(
        active_container_group_signature=group_signature,
        active_container_group_remaining={first_signature},
        active_container_group_labels={first_signature: "Medication"},
        completed_container_groups={"previous||group"},
        consumed_cluster_signatures={"cluster:existing"},
        consumed_cluster_logical_signatures={"logical:existing"},
        visited_logical_signatures={"visited:existing"},
    )
    before = _progress_state_snapshot(state)

    collection_flow._record_active_container_group_progress(state, consumed_signature)

    assert _progress_state_snapshot(state) == before


def test_container_group_progress_without_active_group_is_noop():
    state = _state(
        active_container_group_signature="",
        active_container_group_remaining=set(),
        active_container_group_labels={},
        completed_container_groups={"previous||group"},
        consumed_cluster_signatures={"cluster:existing"},
        consumed_cluster_logical_signatures={"logical:existing"},
        visited_logical_signatures={"visited:existing"},
    )
    before = _progress_state_snapshot(state)

    collection_flow._record_active_container_group_progress(state, "medication||signature")

    assert _progress_state_snapshot(state) == before


@pytest.mark.parametrize(
    ("remaining", "consumed_signature"),
    [
        ({"medication||signature"}, ""),
        ({"medication||signature"}, None),
        (set(), "medication||signature"),
        ({"hospital||signature"}, "medication||signature"),
    ],
)
def test_container_group_progress_impl_noop_paths_do_not_call_callbacks(remaining, consumed_signature):
    state = _state(
        active_container_group_signature="container_group:test",
        active_container_group_remaining=set(remaining),
        active_container_group_labels={"medication||signature": "Medication", "hospital||signature": "Hospital"},
        completed_container_groups={"previous||group"},
        consumed_cluster_signatures={"cluster:existing"},
        consumed_cluster_logical_signatures={"logical:existing"},
        visited_logical_signatures={"visited:existing"},
    )
    continue_calls = []
    consumed_calls = []
    before = _progress_state_snapshot(state)

    container_group_logic._record_active_container_group_progress_impl(
        state,
        consumed_signature,
        on_continue=lambda remaining_labels: continue_calls.append(list(remaining_labels)),
        on_consumed=lambda callback_state: consumed_calls.append(callback_state),
    )

    assert _progress_state_snapshot(state) == before
    assert continue_calls == []
    assert consumed_calls == []


def test_container_group_progress_impl_continue_path_calls_on_continue_only():
    state = _state(
        active_container_group_signature="container_group:test",
        active_container_group_remaining={"medication||signature", "hospital||signature"},
        active_container_group_labels={
            "medication||signature": "Medication",
            "hospital||signature": "Hospital",
        },
    )
    continue_calls = []
    consumed_calls = []

    container_group_logic._record_active_container_group_progress_impl(
        state,
        "medication||signature",
        on_continue=lambda remaining_labels: continue_calls.append(list(remaining_labels)),
        on_consumed=lambda callback_state: consumed_calls.append(callback_state),
    )

    assert state.active_container_group_remaining == {"hospital||signature"}
    assert continue_calls == [["Hospital"]]
    assert consumed_calls == []
    assert state.completed_container_groups == set()


def test_container_group_progress_impl_consumed_path_calls_on_consumed_only():
    state = _state(
        active_container_group_signature="container_group:test",
        active_container_group_remaining={"medication||signature"},
        active_container_group_labels={"medication||signature": "Medication"},
    )
    continue_calls = []
    consumed_calls = []

    container_group_logic._record_active_container_group_progress_impl(
        state,
        "medication||signature",
        on_continue=lambda remaining_labels: continue_calls.append(list(remaining_labels)),
        on_consumed=lambda callback_state: consumed_calls.append(callback_state),
    )

    assert state.active_container_group_remaining == set()
    assert continue_calls == []
    assert consumed_calls == [state]
    assert state.completed_container_groups == set()


def test_active_group_with_remaining_candidate_is_kept_during_filtering():
    first = _container("Medication", "medication", "40,300,1040,480")
    second = _container("Hospital", "hospital", "40,520,1040,700")
    group_signature = collection_flow._container_group_signature([first, second])
    first_signature = collection_flow._candidate_object_signature(first)
    second_signature = collection_flow._candidate_object_signature(second)
    state = _state(
        active_container_group_signature=group_signature,
        active_container_group_remaining={first_signature, second_signature},
        active_container_group_labels={first_signature: "Medication", second_signature: "Hospital"},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([first, second], state=state)

    assert filtered["container_priority_applied"] is True
    assert filtered["container_priority_reason"] == "active_group"
    assert state.active_container_group_signature == group_signature
    assert state.active_container_group_remaining == {first_signature, second_signature}
    assert state.completed_container_groups == set()


def test_active_group_with_priority_candidates_progresses_without_completion():
    candidates = [
        _container("Event", "event", "40,740,1040,920"),
        _container("Medication", "medication", "40,300,1040,480"),
        _container("Hospital", "hospital", "40,520,1040,700"),
    ]
    group_signature = collection_flow._container_group_signature(candidates)
    signatures = {collection_flow._candidate_object_signature(candidate) for candidate in candidates}
    state = _state(
        active_container_group_signature=group_signature,
        active_container_group_remaining=set(signatures),
        active_container_group_labels={
            collection_flow._candidate_object_signature(candidate): candidate["label"]
            for candidate in candidates
        },
    )

    filtered = collection_flow._filter_content_candidates_for_phase(candidates, state=state)

    assert filtered["container_priority_applied"] is True
    assert filtered["container_priority_reason"] == "active_group"
    assert [candidate["label"] for candidate in filtered["representative_candidates"]] == [
        "Medication",
        "Hospital",
        "Event",
    ]
    selected = filtered["representative_candidates"][0]
    assert selected in candidates
    assert selected["rid"] == "medication"
    assert state.active_container_group_signature == group_signature
    assert state.active_container_group_remaining == signatures
    assert state.completed_container_groups == set()

    selected_signature = collection_flow._candidate_object_signature(selected)
    row = {
        "focus_view_id": selected["rid"],
        "focus_bounds": selected["bounds"],
        "visible_label": selected["label"],
        "merged_announcement": selected["label"],
        "move_result": "moved",
        "focus_class_name": "android.widget.LinearLayout",
        "focus_cluster_signature": "cluster:medication",
        "focus_cluster_logical_signature": "medication||medication",
    }

    collection_flow._record_recent_representative_signature(state, row)

    assert selected_signature not in state.active_container_group_remaining
    assert state.active_container_group_remaining == signatures - {selected_signature}
    assert state.active_container_group_signature == group_signature
    assert state.completed_container_groups == set()
    assert "cluster:medication" in state.consumed_cluster_signatures
    assert "medication||medication" in state.consumed_cluster_logical_signatures
    assert row["logical_signature"] in state.visited_logical_signatures


def test_last_active_priority_candidate_consumed_completes_and_skips_same_group():
    first = _container("Medication", "medication", "40,300,1040,480")
    second = _container("Hospital", "hospital", "40,520,1040,700")
    group_signature = collection_flow._container_group_signature([first, second])
    first_signature = collection_flow._candidate_object_signature(first)
    second_signature = collection_flow._candidate_object_signature(second)
    state = _state(
        active_container_group_signature=group_signature,
        active_container_group_remaining={second_signature},
        active_container_group_labels={first_signature: "Medication", second_signature: "Hospital"},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([first, second], state=state)

    assert filtered["container_priority_applied"] is True
    assert filtered["container_priority_reason"] == "active_group"
    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == ["hospital"]

    collection_flow._record_active_container_group_progress(state, second_signature)

    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert state.active_container_group_labels == {}
    assert group_signature in state.completed_container_groups

    repeated = collection_flow._filter_content_candidates_for_phase([first, second], state=state)

    assert {candidate["rid"] for candidate in repeated["completed_container_rejected"]} == {
        "medication",
        "hospital",
    }
    assert repeated["representative_candidates"] == []
    assert group_signature in state.completed_container_groups


def test_active_group_signature_mismatch_clears_without_marking_completed():
    old = _container("Medication", "medication", "40,300,1040,480")
    new_first = _container("Hospital", "hospital", "40,520,1040,700")
    new_second = _container("Event", "event", "40,740,1040,920")
    old_group_signature = collection_flow._container_group_signature([old])
    old_signature = collection_flow._candidate_object_signature(old)
    state = _state(
        active_container_group_signature=old_group_signature,
        active_container_group_remaining={old_signature},
        active_container_group_labels={old_signature: "Medication"},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([new_first, new_second], state=state)

    assert filtered["container_priority_reason"] == "repeated_container_group"
    assert old_group_signature not in state.completed_container_groups
    assert state.active_container_group_signature == collection_flow._container_group_signature([new_first, new_second])
    assert state.active_container_group_remaining == {
        collection_flow._candidate_object_signature(new_first),
        collection_flow._candidate_object_signature(new_second),
    }


def test_signature_mismatch_without_repeated_group_clears_and_does_not_restart():
    old = _container("Medication", "medication", "40,300,1040,480")
    single_new = _container("Hospital", "hospital", "40,520,1040,700")
    old_group_signature = collection_flow._container_group_signature([old])
    old_signature = collection_flow._candidate_object_signature(old)
    state = _state(
        active_container_group_signature=old_group_signature,
        active_container_group_remaining={old_signature},
        active_container_group_labels={old_signature: "Medication"},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([single_new], state=state)

    assert filtered["container_priority_applied"] is False
    assert filtered["container_priority_reason"] == "single_container_keep_mixed_candidates"
    assert old_group_signature not in state.completed_container_groups
    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert state.active_container_group_labels == {}


def test_consumed_completion_and_signature_mismatch_differ_in_completed_group_recording():
    consumed = _container("Medication", "medication", "40,300,1040,480")
    mismatch_old = _container("Medication", "medication", "40,300,1040,480")
    mismatch_new_first = _container("Hospital", "hospital", "40,520,1040,700")
    mismatch_new_second = _container("Event", "event", "40,740,1040,920")
    consumed_group_signature = collection_flow._container_group_signature([consumed])
    mismatch_group_signature = collection_flow._container_group_signature([mismatch_old])
    consumed_signature = collection_flow._candidate_object_signature(consumed)
    mismatch_old_signature = collection_flow._candidate_object_signature(mismatch_old)
    consumed_state = _state(
        active_container_group_signature=consumed_group_signature,
        active_container_group_remaining={consumed_signature},
        active_container_group_labels={consumed_signature: "Medication"},
    )
    mismatch_state = _state(
        active_container_group_signature=mismatch_group_signature,
        active_container_group_remaining={mismatch_old_signature},
        active_container_group_labels={mismatch_old_signature: "Medication"},
    )

    collection_flow._record_active_container_group_progress(consumed_state, consumed_signature)
    collection_flow._filter_content_candidates_for_phase(
        [mismatch_new_first, mismatch_new_second],
        state=mismatch_state,
    )

    assert consumed_group_signature in consumed_state.completed_container_groups
    assert mismatch_group_signature not in mismatch_state.completed_container_groups


def test_active_remaining_without_active_priority_does_not_mark_completed_group():
    old = _container("Medication", "medication", "40,300,1040,480")
    fallback = _container("Plain detail", "plain_detail", "80,760,980,900", top_priority=False)
    old_group_signature = collection_flow._container_group_signature([old])
    old_signature = collection_flow._candidate_object_signature(old)
    state = _state(
        active_container_group_signature=old_group_signature,
        active_container_group_remaining={old_signature},
        active_container_group_labels={old_signature: "Medication"},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([fallback], state=state)

    assert filtered["container_priority_applied"] is False
    assert filtered["container_priority_reason"] == "no_container_candidates"
    assert old_group_signature not in state.completed_container_groups
    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == ["plain_detail"]


def test_active_remaining_completed_group_skip_does_not_complete_previous_group():
    old = _container("Medication", "medication", "40,300,1040,480")
    completed_first = _container("Hospital", "hospital", "40,520,1040,700")
    completed_second = _container("Event", "event", "40,740,1040,920")
    fallback = _container("Plain detail", "plain_detail", "80,960,980,1060", top_priority=False)
    old_group_signature = collection_flow._container_group_signature([old])
    old_signature = collection_flow._candidate_object_signature(old)
    completed_signature = collection_flow._container_group_signature([completed_first, completed_second])
    state = _state(
        active_container_group_signature=old_group_signature,
        active_container_group_remaining={old_signature},
        active_container_group_labels={old_signature: "Medication"},
        completed_container_groups={completed_signature},
    )

    filtered = collection_flow._filter_content_candidates_for_phase(
        [completed_first, completed_second, fallback],
        state=state,
    )

    assert {candidate["rid"] for candidate in filtered["completed_container_rejected"]} == {"hospital", "event"}
    assert old_group_signature not in state.completed_container_groups
    assert completed_signature in state.completed_container_groups
    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == ["plain_detail"]


def test_active_remaining_consumed_cluster_blocks_reselect_and_clears_without_completion():
    old = _container("Medication", "medication", "40,300,1040,480")
    consumed = _container("Hospital", "hospital", "40,520,1040,700")
    consumed["cluster_signature"] = "cluster:hospital"
    fallback = _container("Plain detail", "plain_detail", "80,760,980,900", top_priority=False)
    old_group_signature = collection_flow._container_group_signature([old])
    old_signature = collection_flow._candidate_object_signature(old)
    state = _state(
        active_container_group_signature=old_group_signature,
        active_container_group_remaining={old_signature},
        active_container_group_labels={old_signature: "Medication"},
        consumed_cluster_signatures={"cluster:hospital"},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([consumed, fallback], state=state)

    assert filtered["cluster_consumed_rejected"] == [consumed]
    assert old_group_signature not in state.completed_container_groups
    assert state.consumed_cluster_signatures == {"cluster:hospital"}
    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == ["plain_detail"]


def test_clear_active_container_group_marks_completed_only_when_consumed():
    first = _container("Medication", "medication", "40,300,1040,480")
    group_signature = collection_flow._container_group_signature([first])
    first_signature = collection_flow._candidate_object_signature(first)
    consumed_state = _state(
        active_container_group_signature=group_signature,
        active_container_group_remaining={first_signature},
        active_container_group_labels={first_signature: "Medication"},
    )
    scroll_state = _state(
        active_container_group_signature=group_signature,
        active_container_group_remaining={first_signature},
        active_container_group_labels={first_signature: "Medication"},
    )

    collection_flow._clear_active_container_group(consumed_state, reason="consumed")
    collection_flow._clear_active_container_group(scroll_state, reason="scroll")

    assert consumed_state.active_container_group_signature == ""
    assert consumed_state.active_container_group_remaining == set()
    assert group_signature in consumed_state.completed_container_groups
    assert scroll_state.active_container_group_signature == ""
    assert scroll_state.active_container_group_remaining == set()
    assert group_signature not in scroll_state.completed_container_groups


def test_local_tab_phase_transition_clears_active_group_without_completed_carryover():
    first = _container("Medication", "medication", "40,300,1040,480")
    group_signature = collection_flow._container_group_signature([first])
    first_signature = collection_flow._candidate_object_signature(first)
    state = _state(
        fail_count=3,
        same_count=2,
        prev_fingerprint=("old", "fingerprint", ""),
        previous_step_row={"visible_label": "Medication"},
        recent_focus_realign_signatures=set(),
        failed_focus_realign_signatures=set(),
        recent_focus_realign_clusters=set(),
        cluster_title_fallback_applied=set(),
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
        scroll_ready_retry_counts={"old": 1},
        pending_scroll_ready_cluster_signature="old",
        content_phase_grace_steps=0,
        current_local_tab_signature="local-tabs",
        last_selected_local_tab_signature="",
        last_selected_local_tab_rid="",
        last_selected_local_tab_label="",
        last_selected_local_tab_bounds="",
        active_container_group_signature=group_signature,
        active_container_group_remaining={first_signature},
        active_container_group_labels={first_signature: "Medication"},
        completed_container_groups={group_signature},
    )

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Events",
        active_rid="events",
        active_signature="local-tabs",
        active_bounds="710,2316,1050,2496",
    )

    assert state.active_container_group_signature == ""
    assert state.active_container_group_remaining == set()
    assert state.active_container_group_labels == {}
    assert state.completed_container_groups == set()
    assert state.content_phase_grace_steps == 2


def test_completed_container_group_is_removed_from_selection_candidates():
    containers = [
        _container("Medication", "medication", "40,300,1040,480"),
        _container("Hospital", "hospital", "40,520,1040,700"),
    ]
    other = _container("Other content", "other_content", "80,760,980,900", top_priority=False)
    completed_signature = collection_flow._container_group_signature(containers)

    filtered = collection_flow._filter_content_candidates_for_phase(
        [*containers, other],
        state=_state(completed_container_groups={completed_signature}),
    )

    assert {candidate["rid"] for candidate in filtered["completed_container_rejected"]} == {"medication", "hospital"}
    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == ["other_content"]
    assert all(candidate["rid"] not in {"medication", "hospital"} for candidate in filtered["selection_candidates"])


def test_completed_group_and_consumed_cluster_filter_together_prevent_reselection():
    completed_containers = [
        _container("Medication", "medication", "40,300,1040,480"),
        _container("Hospital", "hospital", "40,520,1040,700"),
    ]
    consumed = _container("Event", "event", "40,740,1040,920")
    consumed["cluster_signature"] = "cluster:event"
    survivor = _container("Plain detail", "plain_detail", "80,960,980,1060", top_priority=False)
    completed_signature = collection_flow._container_group_signature(completed_containers)

    filtered = collection_flow._filter_content_candidates_for_phase(
        [*completed_containers, consumed, survivor],
        state=_state(
            completed_container_groups={completed_signature},
            consumed_cluster_signatures={"cluster:event"},
        ),
    )

    assert {candidate["rid"] for candidate in filtered["completed_container_rejected"]} == {"medication", "hospital"}
    assert filtered["cluster_consumed_rejected"] == [consumed]
    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == ["plain_detail"]


def test_active_container_group_visual_order_uses_bounds_not_input_order():
    candidates = [
        _container("Event", "event", "40,740,1040,920"),
        _container("Medication", "medication", "40,300,1040,480"),
        _container("Hospital", "hospital", "40,520,1040,700"),
    ]
    state = _state(
        active_container_group_signature="tabs",
        active_container_group_remaining={collection_flow._candidate_object_signature(candidate) for candidate in candidates},
    )

    ordered = collection_flow._sort_active_container_group_candidates(candidates, state=state)

    assert [candidate["label"] for candidate in ordered] == ["Medication", "Hospital", "Event"]


def test_cluster_representative_prefers_container_role_over_title_leaf():
    title_candidate = {
        "label": "Medication",
        "rid": "com.example:id/title",
        "bounds": "80,340,980,420",
        "cluster_signature": "com.example:id/card||40,300,1040,520||medication",
        "cluster_role": "title",
        "representative": True,
        "score": 300000,
        "top": 340,
    }
    container_candidate = {
        "label": "Medication Medication details",
        "rid": "com.example:id/card",
        "bounds": "40,300,1040,520",
        "cluster_signature": title_candidate["cluster_signature"],
        "cluster_role": "container",
        "representative": True,
        "score": 100,
        "top": 300,
    }
    title_candidate["cluster_members"] = [title_candidate, container_candidate]

    fallback = collection_flow._select_better_cluster_representative(
        selected_candidate=title_candidate,
        state=_state(cluster_title_fallback_applied=set()),
        row={"move_result": "failed"},
    )

    assert fallback is container_candidate


def test_cluster_consumed_signature_blocks_reselecting_same_container():
    candidate = _container("Medication", "medication", "40,300,1040,480")
    candidate["cluster_signature"] = "cluster:medication"
    candidate["cluster_logical_signature"] = "medication||medication"

    filtered = collection_flow._filter_content_candidates_for_phase(
        [candidate],
        state=_state(consumed_cluster_signatures={"cluster:medication"}),
    )

    assert filtered["representative_candidates"] == []
    assert filtered["cluster_consumed_rejected"] == [candidate]


def test_record_recent_representative_marks_cluster_and_logical_visited():
    state = _state()
    row = {
        "focus_view_id": "medication",
        "focus_bounds": "40,300,1040,480",
        "visible_label": "Medication",
        "move_result": "moved",
        "focus_class_name": "android.widget.LinearLayout",
        "focus_cluster_signature": "cluster:medication",
        "focus_cluster_logical_signature": "medication||medication",
    }

    collection_flow._record_recent_representative_signature(state, row)

    assert collection_flow._build_row_object_signature(row) in state.consumed_representative_signatures
    assert "cluster:medication" in state.consumed_cluster_signatures
    assert "medication||medication" in state.consumed_cluster_logical_signatures
    assert row["logical_signature"] in state.visited_logical_signatures


def test_candidate_cluster_logical_signature_normalizes_equivalent_labels():
    candidate_a = {
        "cluster_rid": "COM.EXAMPLE:id/MEDICATION_CARD",
        "cluster_label": "  Medication   Details!  ",
    }
    candidate_b = {
        "cluster_rid": "com.example:id/medication_card",
        "cluster_label": "Medication Details",
    }

    assert container_group_logic._candidate_cluster_logical_signature(candidate_a) == (
        container_group_logic._candidate_cluster_logical_signature(candidate_b)
    )


def test_candidate_cluster_logical_signature_preserves_empty_label_fallback():
    candidate = {
        "rid": "",
        "label": None,
    }

    assert container_group_logic._candidate_cluster_logical_signature(candidate) == "none||none"


def test_candidate_cluster_logical_signature_prefers_cluster_label_over_label():
    candidate = {
        "cluster_rid": "cluster",
        "cluster_label": "Visible Cluster",
        "label": "Speech Label",
    }

    assert container_group_logic._candidate_cluster_logical_signature(candidate) == "cluster||visible cluster"
