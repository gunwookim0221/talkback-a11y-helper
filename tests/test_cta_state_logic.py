import sys
from collections import deque
from types import SimpleNamespace

import pytest

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, ExcelWriter=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow


@pytest.fixture(autouse=True)
def _quiet_logs(monkeypatch):
    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: None)


class FakeCtaClient:
    def __init__(self, focus_nodes=None):
        self.focus_nodes = list(focus_nodes or [])
        self.select_calls = []
        self.get_focus_calls = []

    def normalize_for_comparison(self, value):
        return str(value or "").strip().lower()

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return True

    def get_focus(self, **kwargs):
        self.get_focus_calls.append(kwargs)
        if self.focus_nodes:
            return self.focus_nodes.pop(0)
        return {}


def _state(**overrides):
    base = {
        "cta_grace_signature": "",
        "cta_descend_grace_remaining": 0,
        "cta_cluster_nodes_by_signature": {},
        "cta_cluster_visited_rids": {},
        "cta_cluster_committed_rid": {},
        "recent_representative_signatures": deque([], maxlen=5),
        "consumed_representative_signatures": set(),
        "visited_logical_signatures": set(),
        "consumed_cluster_signatures": set(),
        "consumed_cluster_logical_signatures": set(),
        "completed_container_groups": set(),
        "active_container_group_signature": "",
        "active_container_group_remaining": set(),
        "active_container_group_labels": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _nested_state(**overrides):
    cta_state = SimpleNamespace(
        cta_grace_signature="",
        cta_descend_grace_remaining=0,
        cta_cluster_nodes_by_signature={},
        cta_cluster_visited_rids={},
        cta_cluster_committed_rid={},
    )
    base = {
        "cta_state": cta_state,
        "cta_grace_signature": "DIRECT_SENTINEL",
        "cta_descend_grace_remaining": 999,
        "cta_cluster_nodes_by_signature": {"direct": ["sentinel"]},
        "cta_cluster_visited_rids": {"direct": {"sentinel"}},
        "cta_cluster_committed_rid": {"direct": "sentinel"},
        "recent_representative_signatures": deque([], maxlen=5),
        "consumed_representative_signatures": set(),
        "visited_logical_signatures": set(),
        "consumed_cluster_signatures": set(),
        "consumed_cluster_logical_signatures": set(),
        "completed_container_groups": set(),
        "active_container_group_signature": "",
        "active_container_group_remaining": set(),
        "active_container_group_labels": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _assert_direct_cta_sentinel_unchanged(state):
    assert state.cta_grace_signature == "DIRECT_SENTINEL"
    assert state.cta_descend_grace_remaining == 999
    assert state.cta_cluster_nodes_by_signature == {"direct": ["sentinel"]}
    assert state.cta_cluster_visited_rids == {"direct": {"sentinel"}}
    assert state.cta_cluster_committed_rid == {"direct": "sentinel"}


def _cta_node(label, rid, bounds):
    return {
        "text": label,
        "contentDescription": label,
        "viewIdResourceName": rid,
        "className": "android.widget.Button",
        "clickable": True,
        "focusable": True,
        "effectiveClickable": True,
        "boundsInScreen": bounds,
        "visibleToUser": True,
        "children": [],
    }


def _cta_container_row(*, idx=1):
    return {
        "step_index": idx,
        "move_result": "moved",
        "visible_label": "Want better insight into your daily life?",
        "normalized_visible_label": "want better insight into your daily life?",
        "merged_announcement": "Want better insight into your daily life? Later Set up now",
        "focus_view_id": "com.example.plugin:id/suggestion_card_container",
        "focus_bounds": "0,10,100,80",
        "focus_node": {
            "text": "",
            "contentDescription": "",
            "viewIdResourceName": "com.example.plugin:id/suggestion_card_container",
            "className": "android.view.ViewGroup",
            "clickable": False,
            "focusable": False,
            "effectiveClickable": False,
            "hasClickableDescendant": True,
            "hasFocusableDescendant": True,
            "boundsInScreen": "0,10,100,80",
            "visibleToUser": True,
            "children": [
                _cta_node("Later", "com.example.plugin:id/first_button", "0,40,40,60"),
                _cta_node("Set up now", "com.example.plugin:id/second_button", "45,40,100,60"),
                _cta_node("Continue", "com.example.plugin:id/third_button", "105,40,160,60"),
            ],
        },
    }


def _cta_row(label, rid, *, idx=2, move_result="moved"):
    return {
        "step_index": idx,
        "move_result": move_result,
        "visible_label": label,
        "normalized_visible_label": label.lower(),
        "merged_announcement": label,
        "focus_view_id": rid,
        "focus_bounds": "0,40,100,60",
        "focus_node": _cta_node(label, rid, "0,40,100,60"),
    }


def _candidate(label, rid):
    return {
        "label": label,
        "rid": rid,
        "bounds": "0,40,100,60",
        "top": 40,
        "left": 0,
        "score": 100,
        "representative": True,
        "node": _cta_node(label, rid, "0,40,100,60"),
    }


def _cluster_signature(row):
    nodes, _hits = collection_flow._collect_actionable_cta_descendants(row)
    return collection_flow._build_cta_cluster_signature(row["focus_view_id"], nodes)


def test_cta_state_commit_records_committed_rid_and_visited_rid():
    state = _state()

    collection_flow._commit_cta_cluster_selection(
        state=state,
        cluster_signature="cluster:a",
        selected_rid="com.example.plugin:id/first_button",
        step_idx=3,
        scenario_id="s1",
    )

    assert state.cta_cluster_committed_rid["cluster:a"] == "com.example.plugin:id/first_button"
    assert state.cta_cluster_visited_rids["cluster:a"] == {"com.example.plugin:id/first_button"}


def test_cta_state_promote_stores_cluster_nodes_by_signature():
    state = _state()
    row = _cta_container_row()

    updated = collection_flow._maybe_promote_row_to_cta_child(
        row=row,
        client=FakeCtaClient(),
        state=state,
        scenario_id="s1",
        step_idx=1,
    )

    cluster_signature = updated["cta_cluster_signature"]
    assert updated["cta_promoted_from_container"] is True
    assert cluster_signature in state.cta_cluster_nodes_by_signature
    assert {node["viewIdResourceName"] for node in state.cta_cluster_nodes_by_signature[cluster_signature]} == {
        "com.example.plugin:id/first_button",
        "com.example.plugin:id/second_button",
        "com.example.plugin:id/third_button",
    }


def test_cta_state_promote_keeps_committed_rid_on_repeated_container():
    state = _state()
    seed_row = _cta_container_row()
    cluster_signature = _cluster_signature(seed_row)
    state.cta_cluster_committed_rid[cluster_signature] = "com.example.plugin:id/second_button"

    updated = collection_flow._maybe_promote_row_to_cta_child(
        row=_cta_container_row(idx=3),
        client=FakeCtaClient(),
        state=state,
        scenario_id="s1",
        step_idx=3,
    )

    assert updated["cta_promote_kept_committed"] is True
    assert updated["focus_view_id"] == "com.example.plugin:id/second_button"
    assert updated["visible_label"] == "Set up now"
    assert state.cta_cluster_committed_rid[cluster_signature] == "com.example.plugin:id/second_button"
    assert "com.example.plugin:id/second_button" in state.cta_cluster_visited_rids[cluster_signature]


def test_cta_state_sibling_progression_skips_visited_rids():
    container = _cta_container_row()
    nodes, _hits = collection_flow._collect_actionable_cta_descendants(container)
    cluster_signature = collection_flow._build_cta_cluster_signature(container["focus_view_id"], nodes)
    state = _state(
        cta_cluster_nodes_by_signature={cluster_signature: nodes},
        cta_cluster_visited_rids={
            cluster_signature: {
                "com.example.plugin:id/first_button",
                "com.example.plugin:id/second_button",
            }
        },
    )
    prev_row = {
        "cta_cluster_signature": cluster_signature,
        "focus_view_id": "com.example.plugin:id/first_button",
        "cta_promoted_container_rid": container["focus_view_id"],
    }

    updated = collection_flow._maybe_progress_row_to_cta_sibling(
        row=_cta_row("Later", "com.example.plugin:id/first_button", move_result="failed"),
        previous_row=prev_row,
        state=state,
        client=FakeCtaClient([_cta_node("Continue", "com.example.plugin:id/third_button", "105,40,160,60")]),
        scenario_id="s1",
        step_idx=4,
    )

    assert updated["cta_sibling_progressed"] is True
    assert updated["focus_view_id"] == "com.example.plugin:id/third_button"
    assert "com.example.plugin:id/third_button" in state.cta_cluster_visited_rids[cluster_signature]


def test_cta_state_sibling_progression_records_next_visited_rid():
    container = _cta_container_row()
    nodes, _hits = collection_flow._collect_actionable_cta_descendants(container)
    cluster_signature = collection_flow._build_cta_cluster_signature(container["focus_view_id"], nodes)
    state = _state(
        cta_cluster_nodes_by_signature={cluster_signature: nodes},
        cta_cluster_visited_rids={cluster_signature: {"com.example.plugin:id/first_button"}},
    )
    prev_row = {
        "cta_cluster_signature": cluster_signature,
        "focus_view_id": "com.example.plugin:id/first_button",
        "cta_promoted_container_rid": container["focus_view_id"],
    }

    updated = collection_flow._maybe_progress_row_to_cta_sibling(
        row=_cta_row("Later", "com.example.plugin:id/first_button", move_result="no_progress"),
        previous_row=prev_row,
        state=state,
        client=FakeCtaClient([_cta_node("Set up now", "com.example.plugin:id/second_button", "45,40,100,60")]),
        scenario_id="s1",
        step_idx=4,
    )

    assert updated["focus_view_id"] == "com.example.plugin:id/third_button"
    assert state.cta_cluster_committed_rid[cluster_signature] == "com.example.plugin:id/third_button"
    assert state.cta_cluster_visited_rids[cluster_signature] == {
        "com.example.plugin:id/first_button",
        "com.example.plugin:id/third_button",
    }


def test_cta_state_filter_excludes_consumed_cta_rids():
    state = _state(
        cta_cluster_visited_rids={"cluster:a": {"com.example.plugin:id/first_button"}},
    )

    meta = collection_flow._filter_content_candidates_for_phase(
        [
            _candidate("Later", "com.example.plugin:id/first_button"),
            _candidate("Set up now", "com.example.plugin:id/second_button"),
        ],
        state=state,
    )

    assert [candidate["rid"] for candidate in meta["selection_candidates"]] == ["com.example.plugin:id/second_button"]
    assert [candidate["rid"] for candidate in meta["consumed_rejected"]] == ["com.example.plugin:id/first_button"]


def test_cta_state_descend_grace_sets_signature_and_count():
    state = _state()

    stop, reason, applied = collection_flow._maybe_apply_cta_pending_grace(
        row=_cta_container_row(),
        previous_row={},
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"strict_duplicate": True, "no_progress": True},
        state=state,
        step_idx=5,
        scenario_id="s1",
    )

    assert (stop, reason, applied) == (False, "", True)
    assert state.cta_grace_signature
    assert state.cta_descend_grace_remaining == collection_flow._CTA_DESCEND_GRACE_STEPS - 1


def test_cta_state_descend_grace_decrements_without_changing_reason_contract():
    state = _state()
    first = collection_flow._maybe_apply_cta_pending_grace(
        row=_cta_container_row(),
        previous_row={},
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"strict_duplicate": True, "no_progress": True},
        state=state,
        step_idx=5,
        scenario_id="s1",
    )
    remaining_after_first = state.cta_descend_grace_remaining

    second = collection_flow._maybe_apply_cta_pending_grace(
        row=_cta_container_row(idx=2),
        previous_row={},
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"strict_duplicate": True, "no_progress": True},
        state=state,
        step_idx=6,
        scenario_id="s1",
    )

    assert first == (False, "", True)
    assert second == (False, "", True)
    assert state.cta_descend_grace_remaining == max(remaining_after_first - 1, 0)


def test_cta_state_descend_grace_clears_on_non_cta_row():
    state = _state(cta_grace_signature="cluster||card||later", cta_descend_grace_remaining=2)

    stop, reason, applied = collection_flow._maybe_apply_cta_pending_grace(
        row=_cta_row("Plain text", "com.example.plugin:id/plain", move_result="moved"),
        previous_row={},
        stop=False,
        reason="",
        stop_eval_inputs={},
        state=state,
        step_idx=7,
        scenario_id="s1",
    )

    assert (stop, reason, applied) == (False, "", False)
    assert state.cta_grace_signature == ""
    assert state.cta_descend_grace_remaining == 0


def test_cta_state_nested_commit_records_committed_rid_and_visited_rid():
    state = _nested_state()

    collection_flow._commit_cta_cluster_selection(
        state=state,
        cluster_signature="cluster:a",
        selected_rid="com.example.plugin:id/first_button",
        step_idx=3,
        scenario_id="s1",
    )

    assert state.cta_state.cta_cluster_committed_rid["cluster:a"] == "com.example.plugin:id/first_button"
    assert state.cta_state.cta_cluster_visited_rids["cluster:a"] == {"com.example.plugin:id/first_button"}
    _assert_direct_cta_sentinel_unchanged(state)


def test_cta_state_nested_promote_stores_cluster_nodes_by_signature():
    state = _nested_state()

    updated = collection_flow._maybe_promote_row_to_cta_child(
        row=_cta_container_row(),
        client=FakeCtaClient(),
        state=state,
        scenario_id="s1",
        step_idx=1,
    )

    cluster_signature = updated["cta_cluster_signature"]
    assert cluster_signature in state.cta_state.cta_cluster_nodes_by_signature
    assert {node["viewIdResourceName"] for node in state.cta_state.cta_cluster_nodes_by_signature[cluster_signature]} == {
        "com.example.plugin:id/first_button",
        "com.example.plugin:id/second_button",
        "com.example.plugin:id/third_button",
    }
    _assert_direct_cta_sentinel_unchanged(state)


def test_cta_state_nested_promote_keeps_committed_rid_on_repeated_container():
    state = _nested_state()
    cluster_signature = _cluster_signature(_cta_container_row())
    state.cta_state.cta_cluster_committed_rid[cluster_signature] = "com.example.plugin:id/second_button"

    updated = collection_flow._maybe_promote_row_to_cta_child(
        row=_cta_container_row(idx=3),
        client=FakeCtaClient(),
        state=state,
        scenario_id="s1",
        step_idx=3,
    )

    assert updated["cta_promote_kept_committed"] is True
    assert updated["focus_view_id"] == "com.example.plugin:id/second_button"
    assert state.cta_state.cta_cluster_committed_rid[cluster_signature] == "com.example.plugin:id/second_button"
    assert "com.example.plugin:id/second_button" in state.cta_state.cta_cluster_visited_rids[cluster_signature]
    _assert_direct_cta_sentinel_unchanged(state)


def test_cta_state_nested_sibling_progression_skips_visited_rids():
    container = _cta_container_row()
    nodes, _hits = collection_flow._collect_actionable_cta_descendants(container)
    cluster_signature = collection_flow._build_cta_cluster_signature(container["focus_view_id"], nodes)
    state = _nested_state()
    state.cta_state.cta_cluster_nodes_by_signature[cluster_signature] = nodes
    state.cta_state.cta_cluster_visited_rids[cluster_signature] = {
        "com.example.plugin:id/first_button",
        "com.example.plugin:id/second_button",
    }
    prev_row = {
        "cta_cluster_signature": cluster_signature,
        "focus_view_id": "com.example.plugin:id/first_button",
        "cta_promoted_container_rid": container["focus_view_id"],
    }

    updated = collection_flow._maybe_progress_row_to_cta_sibling(
        row=_cta_row("Later", "com.example.plugin:id/first_button", move_result="failed"),
        previous_row=prev_row,
        state=state,
        client=FakeCtaClient([_cta_node("Continue", "com.example.plugin:id/third_button", "105,40,160,60")]),
        scenario_id="s1",
        step_idx=4,
    )

    assert updated["focus_view_id"] == "com.example.plugin:id/third_button"
    assert "com.example.plugin:id/third_button" in state.cta_state.cta_cluster_visited_rids[cluster_signature]
    _assert_direct_cta_sentinel_unchanged(state)


def test_cta_state_nested_sibling_progression_records_next_visited_rid():
    container = _cta_container_row()
    nodes, _hits = collection_flow._collect_actionable_cta_descendants(container)
    cluster_signature = collection_flow._build_cta_cluster_signature(container["focus_view_id"], nodes)
    state = _nested_state()
    state.cta_state.cta_cluster_nodes_by_signature[cluster_signature] = nodes
    state.cta_state.cta_cluster_visited_rids[cluster_signature] = {"com.example.plugin:id/first_button"}
    prev_row = {
        "cta_cluster_signature": cluster_signature,
        "focus_view_id": "com.example.plugin:id/first_button",
        "cta_promoted_container_rid": container["focus_view_id"],
    }

    updated = collection_flow._maybe_progress_row_to_cta_sibling(
        row=_cta_row("Later", "com.example.plugin:id/first_button", move_result="no_progress"),
        previous_row=prev_row,
        state=state,
        client=FakeCtaClient([_cta_node("Set up now", "com.example.plugin:id/second_button", "45,40,100,60")]),
        scenario_id="s1",
        step_idx=4,
    )

    assert updated["focus_view_id"] == "com.example.plugin:id/third_button"
    assert state.cta_state.cta_cluster_committed_rid[cluster_signature] == "com.example.plugin:id/third_button"
    assert state.cta_state.cta_cluster_visited_rids[cluster_signature] == {
        "com.example.plugin:id/first_button",
        "com.example.plugin:id/third_button",
    }
    _assert_direct_cta_sentinel_unchanged(state)


def test_cta_state_nested_filter_excludes_consumed_cta_rids():
    state = _nested_state()
    state.cta_state.cta_cluster_visited_rids = {"cluster:a": {"com.example.plugin:id/first_button"}}

    meta = collection_flow._filter_content_candidates_for_phase(
        [
            _candidate("Later", "com.example.plugin:id/first_button"),
            _candidate("Set up now", "com.example.plugin:id/second_button"),
        ],
        state=state,
    )

    assert [candidate["rid"] for candidate in meta["selection_candidates"]] == ["com.example.plugin:id/second_button"]
    assert [candidate["rid"] for candidate in meta["consumed_rejected"]] == ["com.example.plugin:id/first_button"]
    _assert_direct_cta_sentinel_unchanged(state)


def test_cta_state_nested_descend_grace_sets_signature_and_count():
    state = _nested_state()

    stop, reason, applied = collection_flow._maybe_apply_cta_pending_grace(
        row=_cta_container_row(),
        previous_row={},
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"strict_duplicate": True, "no_progress": True},
        state=state,
        step_idx=5,
        scenario_id="s1",
    )

    assert (stop, reason, applied) == (False, "", True)
    assert state.cta_state.cta_grace_signature
    assert state.cta_state.cta_descend_grace_remaining == collection_flow._CTA_DESCEND_GRACE_STEPS - 1
    _assert_direct_cta_sentinel_unchanged(state)


def test_cta_state_nested_descend_grace_decrements_without_changing_reason_contract():
    state = _nested_state()
    first = collection_flow._maybe_apply_cta_pending_grace(
        row=_cta_container_row(),
        previous_row={},
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"strict_duplicate": True, "no_progress": True},
        state=state,
        step_idx=5,
        scenario_id="s1",
    )
    remaining_after_first = state.cta_state.cta_descend_grace_remaining

    second = collection_flow._maybe_apply_cta_pending_grace(
        row=_cta_container_row(idx=2),
        previous_row={},
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs={"strict_duplicate": True, "no_progress": True},
        state=state,
        step_idx=6,
        scenario_id="s1",
    )

    assert first == (False, "", True)
    assert second == (False, "", True)
    assert state.cta_state.cta_descend_grace_remaining == max(remaining_after_first - 1, 0)
    _assert_direct_cta_sentinel_unchanged(state)


def test_cta_state_nested_descend_grace_clears_on_non_cta_row():
    state = _nested_state()
    state.cta_state.cta_grace_signature = "cluster||card||later"
    state.cta_state.cta_descend_grace_remaining = 2

    stop, reason, applied = collection_flow._maybe_apply_cta_pending_grace(
        row=_cta_row("Plain text", "com.example.plugin:id/plain", move_result="moved"),
        previous_row={},
        stop=False,
        reason="",
        stop_eval_inputs={},
        state=state,
        step_idx=7,
        scenario_id="s1",
    )

    assert (stop, reason, applied) == (False, "", False)
    assert state.cta_state.cta_grace_signature == ""
    assert state.cta_state.cta_descend_grace_remaining == 0
    _assert_direct_cta_sentinel_unchanged(state)
