import sys
from collections import deque
from types import SimpleNamespace

import pytest

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, ExcelWriter=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow
from tb_runner import overlay_logic


@pytest.fixture(autouse=True)
def _quiet_logs(monkeypatch):
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": None)
    monkeypatch.setattr(overlay_logic, "log", lambda message, level="NORMAL": None)


def _focus_node(
    *,
    rid: str = "",
    text: str = "",
    description: str = "",
    bounds: str = "0,0,100,100",
    class_name: str = "android.widget.TextView",
) -> dict:
    return {
        "viewIdResourceName": rid,
        "text": text,
        "contentDescription": description,
        "talkbackLabel": description or text,
        "boundsInScreen": bounds,
        "className": class_name,
    }


def _row(
    *,
    rid: str = "id.current",
    label: str = "Current",
    bounds: str = "0,0,100,100",
    cluster_signature: str = "",
) -> dict:
    return {
        "focus_view_id": rid,
        "visible_label": label,
        "merged_announcement": label,
        "focus_bounds": bounds,
        "focus_cluster_signature": cluster_signature,
    }


def _candidate(
    label: str,
    rid: str,
    bounds: str,
    *,
    cluster_signature: str = "",
    cluster_logical_signature: str = "",
    passive_status: bool = False,
    low_value_leaf: bool = False,
) -> dict:
    left, top, _right, _bottom = [int(part) for part in bounds.split(",")]
    return {
        "label": label,
        "rid": rid,
        "bounds": bounds,
        "top": top,
        "left": left,
        "score": 100,
        "representative": True,
        "passive_status": passive_status,
        "low_value_leaf": low_value_leaf,
        "cluster_signature": cluster_signature,
        "cluster_logical_signature": cluster_logical_signature,
        "node": {
            "viewIdResourceName": rid,
            "text": label,
            "boundsInScreen": bounds,
            "className": "android.widget.LinearLayout",
        },
    }


def _state(**overrides):
    base = {
        "recent_representative_signatures": deque([], maxlen=5),
        "consumed_representative_signatures": set(),
        "visited_logical_signatures": set(),
        "consumed_cluster_signatures": set(),
        "consumed_cluster_logical_signatures": set(),
        "cta_cluster_visited_rids": {},
        "completed_container_groups": set(),
        "active_container_group_signature": "",
        "active_container_group_remaining": set(),
        "active_container_group_labels": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeRepresentativeClient:
    def __init__(self, focus_nodes):
        self.focus_nodes = list(focus_nodes)
        self.select_calls = []
        self.get_focus_calls = []

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return True

    def get_focus(self, **kwargs):
        self.get_focus_calls.append(kwargs)
        if self.focus_nodes:
            return self.focus_nodes.pop(0)
        return {}


def _overlay_step(
    *,
    label: str = "Entry",
    view_id: str = "id.entry",
    bounds: str = "0,0,100,100",
    step_index: int = 1,
) -> dict:
    return {
        "step_index": step_index,
        "visible_label": label,
        "normalized_visible_label": label.lower(),
        "merged_announcement": label,
        "focus_view_id": view_id,
        "focus_bounds": bounds,
    }


class FakeOverlayClient:
    def __init__(self, focus_nodes):
        self.focus_nodes = list(focus_nodes)
        self.move_focus_smart_calls = []
        self.move_focus_calls = []
        self.get_focus_calls = []

    def move_focus_smart(self, **kwargs):
        self.move_focus_smart_calls.append(kwargs)
        return {"status": "moved", "detail": "test"}

    def move_focus(self, **kwargs):
        self.move_focus_calls.append(kwargs)
        return True

    def get_focus(self, **kwargs):
        self.get_focus_calls.append(kwargs)
        if self.focus_nodes:
            return self.focus_nodes.pop(0)
        return _focus_node(rid="id.unrelated", text="Unrelated", bounds="900,900,1000,1000")

    def extract_visible_label_from_focus(self, focus_node):
        return str(focus_node.get("text", "") or focus_node.get("contentDescription", "") or "").strip()

    def normalize_for_comparison(self, value):
        return str(value or "").strip().lower()

    def _normalize_bounds(self, focus_node):
        return str(focus_node.get("boundsInScreen", "") or focus_node.get("bounds", "") or "").strip()


def test_representative_focus_matches_by_resource_id():
    assert collection_flow._representative_focus_matches(
        focus_node=_focus_node(rid="id.target"),
        target_rid="id.target",
        target_label="Other",
        target_bounds="200,200,300,300",
    )


def test_representative_focus_matches_by_label():
    assert collection_flow._representative_focus_matches(
        focus_node=_focus_node(rid="id.other", text="Medication"),
        target_rid="id.target",
        target_label="Medication",
        target_bounds="200,200,300,300",
    )


def test_representative_focus_matches_by_bounds_overlap():
    assert collection_flow._representative_focus_matches(
        focus_node=_focus_node(rid="id.other", text="Other", bounds="20,20,120,120"),
        target_rid="id.target",
        target_label="Medication",
        target_bounds="0,0,100,100",
    )


def test_representative_focus_matches_returns_false_for_mismatch():
    assert not collection_flow._representative_focus_matches(
        focus_node=_focus_node(rid="id.other", text="Other", bounds="200,200,300,300"),
        target_rid="id.target",
        target_label="Medication",
        target_bounds="0,0,100,100",
    )


def test_representative_focus_matches_does_not_partial_match_label():
    assert not collection_flow._representative_focus_matches(
        focus_node=_focus_node(rid="id.other", text="Medication schedule"),
        target_rid="id.target",
        target_label="Medication",
        target_bounds="200,200,300,300",
    )


def test_focus_anchor_match_reason_by_resource_id():
    assert collection_flow._focus_anchor_match_reason(
        row=_row(rid="id.target", label="Other"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="200,200,300,300",
        selected_cluster_signature="cluster:selected",
    ) == (True, "resource_id_match")


def test_focus_anchor_match_reason_by_normalized_label():
    assert collection_flow._focus_anchor_match_reason(
        row=_row(rid="id.current", label="Medication"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="200,200,300,300",
        selected_cluster_signature="cluster:selected",
    ) == (True, "normalized_label_match")


def test_focus_anchor_match_reason_normalizes_whitespace_and_case():
    assert collection_flow._focus_anchor_match_reason(
        row=_row(rid="id.current", label="  MEDICATION   schedule  "),
        selected_rid="id.target",
        selected_label="Medication schedule",
        selected_bounds="200,200,300,300",
        selected_cluster_signature="cluster:selected",
    ) == (True, "normalized_label_match")


def test_focus_anchor_match_reason_by_bounds_overlap():
    assert collection_flow._focus_anchor_match_reason(
        row=_row(rid="id.current", label="Current", bounds="10,10,110,110"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        selected_cluster_signature="cluster:selected",
    ) == (True, "bounds_overlap")


def test_focus_anchor_match_reason_by_cluster_signature():
    assert collection_flow._focus_anchor_match_reason(
        row=_row(rid="id.current", label="Current", bounds="200,200,300,300", cluster_signature="cluster:selected"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        selected_cluster_signature="cluster:selected",
    ) == (True, "cluster_signature_match")


def test_focus_anchor_match_reason_mismatch():
    assert collection_flow._focus_anchor_match_reason(
        row=_row(rid="id.current", label="Current", bounds="200,200,300,300", cluster_signature="cluster:current"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        selected_cluster_signature="cluster:selected",
    ) == (False, "representative_focus_mismatch")


def test_maybe_realign_focus_to_representative_already_aligned():
    client = FakeRepresentativeClient([])

    result = collection_flow._maybe_realign_focus_to_representative(
        row=_row(rid="id.target", label="Medication"),
        client=client,
        dev="SERIAL",
        selected_node=_focus_node(rid="id.target", text="Medication"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        scenario_id="scenario",
        step_idx=1,
    )

    assert result == (False, "already_aligned", None)
    assert client.select_calls == []
    assert client.get_focus_calls == []


def test_maybe_realign_focus_to_representative_rid_success():
    client = FakeRepresentativeClient([_focus_node(rid="id.target", text="Medication", bounds="0,0,100,100")])

    ok, reason, focus_node = collection_flow._maybe_realign_focus_to_representative(
        row=_row(rid="id.current", label="Current", bounds="200,200,300,300"),
        client=client,
        dev="SERIAL",
        selected_node=_focus_node(rid="id.target", text="Medication"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        scenario_id="scenario",
        step_idx=2,
    )

    assert ok is True
    assert reason == "matched"
    assert focus_node["viewIdResourceName"] == "id.target"
    assert client.select_calls[0]["type_"] == "r"
    assert client.select_calls[0]["name"] == "id.target"


def test_maybe_realign_focus_to_representative_label_fallback_success():
    client = FakeRepresentativeClient([
        _focus_node(rid="id.other", text="Other", bounds="200,200,300,300"),
        _focus_node(rid="id.label", text="Medication", bounds="0,0,100,100"),
    ])

    ok, reason, focus_node = collection_flow._maybe_realign_focus_to_representative(
        row=_row(rid="id.current", label="Current", bounds="200,200,300,300"),
        client=client,
        dev="SERIAL",
        selected_node=_focus_node(rid="id.target", text="Medication"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        scenario_id="scenario",
        step_idx=3,
    )

    assert ok is True
    assert reason == "matched"
    assert focus_node["text"] == "Medication"
    assert [(call["type_"], call["name"]) for call in client.select_calls] == [
        ("r", "id.target"),
        ("a", "Medication"),
    ]


def test_maybe_realign_focus_to_representative_no_match():
    client = FakeRepresentativeClient([
        _focus_node(rid="id.other1", text="Other", bounds="200,200,300,300"),
        _focus_node(rid="id.other2", text="Different", bounds="300,300,400,400"),
    ])

    ok, reason, focus_node = collection_flow._maybe_realign_focus_to_representative(
        row=_row(rid="id.current", label="Current", bounds="200,200,300,300"),
        client=client,
        dev="SERIAL",
        selected_node=_focus_node(rid="id.target", text="Medication"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        scenario_id="scenario",
        step_idx=4,
    )

    assert ok is False
    assert reason == "no_match"
    assert focus_node is None


def test_maybe_realign_focus_to_representative_select_success_but_focus_mismatch():
    client = FakeRepresentativeClient([
        _focus_node(rid="id.other1", text="Other", bounds="200,200,300,300"),
        _focus_node(rid="id.other2", text="Different", bounds="300,300,400,400"),
    ])

    ok, reason, focus_node = collection_flow._maybe_realign_focus_to_representative(
        row=_row(rid="id.current", label="Current", bounds="200,200,300,300"),
        client=client,
        dev="SERIAL",
        selected_node=_focus_node(rid="id.target", text="Medication"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        scenario_id="scenario",
        step_idx=5,
    )

    assert ok is False
    assert reason == "no_match"
    assert focus_node is None
    assert len(client.select_calls) == 2


def test_maybe_realign_focus_to_representative_invalid_focus_payload():
    client = FakeRepresentativeClient([None, ["not", "a", "node"]])

    ok, reason, focus_node = collection_flow._maybe_realign_focus_to_representative(
        row=_row(rid="id.current", label="Current", bounds="200,200,300,300"),
        client=client,
        dev="SERIAL",
        selected_node=_focus_node(rid="id.target", text="Medication"),
        selected_rid="id.target",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        scenario_id="scenario",
        step_idx=6,
    )

    assert ok is False
    assert reason == "no_match"
    assert focus_node is None


def test_maybe_realign_focus_to_representative_label_only_success():
    client = FakeRepresentativeClient([_focus_node(rid="id.label", text="Medication", bounds="0,0,100,100")])

    ok, reason, focus_node = collection_flow._maybe_realign_focus_to_representative(
        row=_row(rid="id.current", label="Current", bounds="200,200,300,300"),
        client=client,
        dev="SERIAL",
        selected_node=_focus_node(text="Medication"),
        selected_rid="",
        selected_label="Medication",
        selected_bounds="0,0,100,100",
        scenario_id="scenario",
        step_idx=7,
    )

    assert ok is True
    assert reason == "matched"
    assert focus_node["text"] == "Medication"
    assert [(call["type_"], call["name"]) for call in client.select_calls] == [("a", "Medication")]


def test_overlay_get_entry_match_by_resource_id():
    assert overlay_logic.get_overlay_entry_match_by(
        _overlay_step(view_id="id.entry", label="Other"),
        _overlay_step(view_id="id.entry", label="Entry"),
    ) == "view_id"


def test_overlay_get_entry_match_by_label():
    assert overlay_logic.get_overlay_entry_match_by(
        _overlay_step(view_id="id.current", label="Entry"),
        _overlay_step(view_id="id.entry", label="Entry"),
    ) == "label"


def test_overlay_get_entry_match_by_partial_label():
    assert overlay_logic.get_overlay_entry_match_by(
        _overlay_step(view_id="id.current", label="Entry"),
        _overlay_step(view_id="id.entry", label="Entry settings"),
    ) == "label_partial"


def test_overlay_get_entry_match_by_bounds_overlap():
    assert overlay_logic.get_overlay_entry_match_by(
        _overlay_step(view_id="id.current", label="Current", bounds="5,5,95,95"),
        _overlay_step(view_id="id.entry", label="Entry", bounds="0,0,100,100"),
    ) == "bounds_overlap"


def test_overlay_get_entry_match_by_bounds_exact_before_overlap():
    assert overlay_logic.get_overlay_entry_match_by(
        _overlay_step(view_id="id.current", label="Current", bounds="0,0,100,100"),
        _overlay_step(view_id="id.entry", label="Entry", bounds="0,0,100,100"),
    ) == "bounds"


def test_overlay_realign_already_on_entry():
    entry = _overlay_step(view_id="id.entry", label="Entry", bounds="0,0,100,100")
    client = FakeOverlayClient([_focus_node(rid="id.entry", text="Entry", bounds="0,0,100,100")])

    result = overlay_logic.realign_focus_after_overlay(
        client=client,
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={},
    )

    assert result["status"] == "already_on_entry"
    assert result["entry_reached"] is True
    assert result["match_by"] == "view_id"
    assert client.move_focus_smart_calls == []
    assert client.move_focus_calls == []


def test_overlay_realign_next_success():
    entry = _overlay_step(view_id="id.entry", label="Entry", bounds="0,0,100,100")
    client = FakeOverlayClient([
        _focus_node(rid="id.current", text="Current", bounds="200,200,300,300"),
        _focus_node(rid="id.entry", text="Entry", bounds="0,0,100,100"),
    ])

    result = overlay_logic.realign_focus_after_overlay(
        client=client,
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={},
    )

    assert result["status"] == "realign_entry_reached"
    assert result["entry_reached"] is True
    assert result["match_by"] == "view_id"
    assert len(client.move_focus_smart_calls) == 1
    assert client.move_focus_calls == []


def test_overlay_realign_prev_success_after_next_fails(monkeypatch):
    monkeypatch.setattr(overlay_logic, "OVERLAY_REALIGN_MAX_STEPS", 1)
    entry = _overlay_step(view_id="id.entry", label="Entry", bounds="0,0,100,100")
    client = FakeOverlayClient([
        _focus_node(rid="id.current", text="Current", bounds="200,200,300,300"),
        _focus_node(rid="id.next", text="Next", bounds="300,300,400,400"),
        _focus_node(rid="id.entry", text="Entry", bounds="0,0,100,100"),
    ])

    result = overlay_logic.realign_focus_after_overlay(
        client=client,
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={},
    )

    assert result["status"] == "realign_entry_reached"
    assert result["entry_reached"] is True
    assert result["match_by"] == "view_id"
    assert len(client.move_focus_smart_calls) == 1
    assert len(client.move_focus_calls) == 1
    assert client.move_focus_calls[0]["direction"] == "prev"


def test_overlay_realign_next_partial_match_prevents_prev_probe(monkeypatch):
    monkeypatch.setattr(overlay_logic, "OVERLAY_REALIGN_MAX_STEPS", 1)
    entry = _overlay_step(view_id="id.entry", label="Entry settings", bounds="0,0,100,100")
    client = FakeOverlayClient([
        _focus_node(rid="id.current", text="Current", bounds="200,200,300,300"),
        _focus_node(rid="id.next", text="Entry", bounds="300,300,400,400"),
    ])

    result = overlay_logic.realign_focus_after_overlay(
        client=client,
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={},
    )

    assert result["status"] == "realign_entry_reached"
    assert result["entry_reached"] is True
    assert result["match_by"] == "label_partial"
    assert len(client.move_focus_smart_calls) == 1
    assert client.move_focus_calls == []


def test_overlay_realign_not_found(monkeypatch):
    monkeypatch.setattr(overlay_logic, "OVERLAY_REALIGN_MAX_STEPS", 1)
    entry = _overlay_step(view_id="id.entry", label="Entry", bounds="0,0,100,100")
    client = FakeOverlayClient([
        _focus_node(rid="id.current", text="Current", bounds="200,200,300,300"),
        _focus_node(rid="id.next", text="Next", bounds="300,300,400,400"),
        _focus_node(rid="id.prev", text="Prev", bounds="400,400,500,500"),
    ])

    result = overlay_logic.realign_focus_after_overlay(
        client=client,
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={},
    )

    assert result["status"] == "realign_entry_not_found"
    assert result["entry_reached"] is False
    assert result["match_by"] == ""


def test_filter_content_candidates_empty_candidate_set():
    filtered = collection_flow._filter_content_candidates_for_phase([], state=_state())

    assert filtered["all_candidates"] == []
    assert filtered["selection_candidates"] == []
    assert filtered["representative_candidates"] == []
    assert filtered["exhaustion_candidates"] == []


def test_filter_content_candidates_single_representative_survives():
    candidate = _candidate("Medication", "id.medication", "0,0,100,100")

    filtered = collection_flow._filter_content_candidates_for_phase([candidate], state=_state())

    assert filtered["representative_candidates"] == [candidate]
    assert filtered["selection_candidates"] == [candidate]


def test_filter_content_candidates_candidate_in_visited_and_consumed_prefers_visited():
    candidate = _candidate("Medication", "id.medication", "0,0,100,100")
    state = _state(
        visited_logical_signatures={collection_flow._candidate_logical_signature(candidate)},
        consumed_representative_signatures={collection_flow._candidate_object_signature(candidate)},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([candidate], state=state)

    assert filtered["visited_rejected"] == [candidate]
    assert filtered["consumed_rejected"] == []
    assert filtered["representative_candidates"] == []


def test_filter_content_candidates_excludes_cluster_logical_consumed():
    candidate = _candidate(
        "Medication",
        "id.medication",
        "0,0,100,100",
        cluster_signature="cluster:physical",
        cluster_logical_signature="cluster:logical",
    )
    state = _state(
        consumed_cluster_logical_signatures={collection_flow._candidate_cluster_logical_signature(candidate)}
    )

    filtered = collection_flow._filter_content_candidates_for_phase([candidate], state=state)

    assert filtered["cluster_consumed_rejected"] == [candidate]
    assert filtered["representative_candidates"] == []


def test_filter_content_candidates_excludes_visited_consumed_and_cluster_consumed():
    visited = _candidate("Visited", "id.visited", "0,0,100,100")
    consumed = _candidate("Consumed", "id.consumed", "0,120,100,220")
    cluster_consumed = _candidate(
        "Cluster",
        "id.cluster",
        "0,240,100,340",
        cluster_signature="cluster:consumed",
        cluster_logical_signature="cluster:logical",
    )
    remaining = _candidate("Remaining", "id.remaining", "0,360,100,460")
    state = _state(
        visited_logical_signatures={collection_flow._candidate_logical_signature(visited)},
        consumed_representative_signatures={collection_flow._candidate_object_signature(consumed)},
        consumed_cluster_signatures={"cluster:consumed"},
    )

    filtered = collection_flow._filter_content_candidates_for_phase(
        [visited, consumed, cluster_consumed, remaining],
        state=state,
    )

    assert filtered["visited_rejected"] == [visited]
    assert filtered["consumed_rejected"] == [consumed]
    assert filtered["cluster_consumed_rejected"] == [cluster_consumed]
    assert filtered["representative_candidates"] == [remaining]


def test_record_recent_representative_signature_records_successful_move():
    row = {
        "focus_view_id": "id.medication",
        "focus_bounds": "0,0,100,100",
        "visible_label": "Medication",
        "merged_announcement": "Medication",
        "move_result": "moved",
        "focus_cluster_signature": "cluster:medication",
        "focus_cluster_logical_signature": "cluster:logical:medication",
    }
    state = _state()
    object_signature = collection_flow._build_row_object_signature(row)
    logical_signature = collection_flow._row_logical_signature(row)

    collection_flow._record_recent_representative_signature(state, row)

    assert object_signature in state.recent_representative_signatures
    assert object_signature in state.consumed_representative_signatures
    assert logical_signature in state.visited_logical_signatures
    assert "cluster:medication" in state.consumed_cluster_signatures
    assert "cluster:logical:medication" in state.consumed_cluster_logical_signatures
    assert row["logical_signature"] == logical_signature


class FakeReprioritizeClient:
    def __init__(self, nodes):
        self.dump_tree_sequence = [nodes]
        self.select_calls = []

    def dump_tree(self, **_kwargs):
        if self.dump_tree_sequence:
            return self.dump_tree_sequence.pop(0)
        return []

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return True


def _bottom_strip_reprioritize_nodes():
    return [
        {
            "className": "android.widget.FrameLayout",
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "text": "Weather information",
                    "viewIdResourceName": "com.example:id/weather_banner",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,760",
                    "children": [],
                },
                {
                    "text": "Location",
                    "viewIdResourceName": "com.example:id/location_button",
                    "className": "android.widget.Button",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "400,1760,680,1860",
                    "children": [],
                },
                {
                    "text": "Events",
                    "viewIdResourceName": "com.example:id/events_button",
                    "className": "android.widget.Button",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "760,1760,1040,1860",
                    "children": [],
                },
            ],
        }
    ]


def _bottom_strip_row():
    return {
        "focus_view_id": "com.example:id/location_button",
        "visible_label": "Location",
        "merged_announcement": "Location",
        "focus_bounds": "400,1760,680,1860",
        "focus_class_name": "android.widget.Button",
        "focus_clickable": True,
        "focus_focusable": True,
        "focus_effective_clickable": True,
    }


def _focus_realign_state(**overrides):
    base = {
        "recent_representative_signatures": [],
        "consumed_representative_signatures": set(),
        "visited_logical_signatures": set(),
        "consumed_cluster_signatures": set(),
        "consumed_cluster_logical_signatures": set(),
        "recent_focus_realign_signatures": set(),
        "failed_focus_realign_signatures": set(),
        "recent_focus_realign_clusters": set(),
        "cluster_title_fallback_applied": set(),
        "cta_cluster_visited_rids": {},
        "local_tab_candidates_by_signature": {},
        "visited_local_tabs_by_signature": {},
        "current_local_tab_signature": "",
        "current_local_tab_active_rid": "",
        "current_local_tab_active_label": "",
        "current_local_tab_active_age": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _nested_focus_realign_state(**focus_overrides):
    focus_state = SimpleNamespace(
        recent_focus_realign_signatures=set(),
        failed_focus_realign_signatures=set(),
        recent_focus_realign_clusters=set(),
        cluster_title_fallback_applied=set(),
    )
    for key, value in focus_overrides.items():
        setattr(focus_state, key, value)
    return _focus_realign_state(
        focus_realign_state=focus_state,
        recent_focus_realign_signatures=None,
        failed_focus_realign_signatures=None,
        recent_focus_realign_clusters=None,
        cluster_title_fallback_applied=None,
    )


def _assert_direct_focus_realign_fields_untouched(state):
    assert state.recent_focus_realign_signatures is None
    assert state.failed_focus_realign_signatures is None
    assert state.recent_focus_realign_clusters is None
    assert state.cluster_title_fallback_applied is None


def test_focus_realign_state_records_success_signature_and_cluster(monkeypatch):
    def realign_success(**_kwargs):
        return True, "matched", _focus_node(
            rid="com.example:id/weather_banner",
            text="Weather information",
            bounds="40,420,1040,760",
        )

    monkeypatch.setattr(collection_flow, "_maybe_realign_focus_to_representative", realign_success)
    state = _focus_realign_state()
    client = FakeReprioritizeClient(_bottom_strip_reprioritize_nodes())

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=_bottom_strip_row(),
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=30,
    )

    signature = collection_flow._build_candidate_object_signature(
        rid="com.example:id/weather_banner",
        bounds="40,420,1040,760",
        label="Weather information",
    )
    assert updated["focus_view_id"] == "com.example:id/weather_banner"
    assert signature in state.recent_focus_realign_signatures
    assert signature not in state.failed_focus_realign_signatures
    assert updated["focus_cluster_signature"] in state.recent_focus_realign_clusters


def test_focus_realign_state_records_failed_signature_on_no_match(monkeypatch):
    def realign_failure(**_kwargs):
        return False, "no_match", None

    monkeypatch.setattr(collection_flow, "_maybe_realign_focus_to_representative", realign_failure)
    state = _focus_realign_state()
    client = FakeReprioritizeClient(_bottom_strip_reprioritize_nodes())

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=_bottom_strip_row(),
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=31,
    )

    signature = collection_flow._build_candidate_object_signature(
        rid="com.example:id/weather_banner",
        bounds="40,420,1040,760",
        label="Weather information",
    )
    assert updated["focus_view_id"] == "com.example:id/weather_banner"
    assert signature in state.failed_focus_realign_signatures
    assert signature not in state.recent_focus_realign_signatures
    assert state.recent_focus_realign_clusters == set()


def test_focus_realign_state_skips_recent_realign_signature():
    candidate = _candidate("Weather information", "com.example:id/weather_banner", "40,420,1040,760")
    state = _focus_realign_state(
        recent_focus_realign_signatures={collection_flow._candidate_object_signature(candidate)}
    )

    filtered = collection_flow._filter_realign_target_candidates([candidate], state=state)

    assert filtered["eligible"] == []
    assert filtered["rejected_resolved"] == [candidate]


def test_focus_realign_state_skips_recent_realign_cluster():
    candidate = _candidate(
        "Weather information",
        "com.example:id/weather_banner",
        "40,420,1040,760",
        cluster_signature="cluster:weather",
    )
    state = _focus_realign_state(recent_focus_realign_clusters={"cluster:weather"})

    filtered = collection_flow._filter_realign_target_candidates([candidate], state=state)

    assert filtered["eligible"] == []
    assert filtered["rejected_resolved"] == [candidate]


def test_focus_realign_state_cluster_title_fallback_applied_once():
    title_candidate = {
        "label": "Steps",
        "rid": "com.example:id/title",
        "bounds": "80,460,980,560",
        "cluster_signature": "cluster:steps",
        "cluster_role": "title",
    }
    container_candidate = {
        "label": "Steps Overview",
        "rid": "com.example:id/info_card_container",
        "bounds": "40,420,1040,980",
        "cluster_signature": "cluster:steps",
        "cluster_role": "container",
        "representative": True,
        "score": 500000,
        "top": 420,
    }
    title_candidate["cluster_members"] = [title_candidate, container_candidate]
    state = _focus_realign_state(cluster_title_fallback_applied={"cluster:steps"})

    fallback = collection_flow._select_better_cluster_representative(
        selected_candidate=title_candidate,
        state=state,
        row={"move_result": "failed"},
    )

    assert fallback is None
    assert state.cluster_title_fallback_applied == {"cluster:steps"}


def test_focus_realign_state_resets_on_local_tab_transition():
    state = SimpleNamespace(
        fail_count=2,
        same_count=3,
        prev_fingerprint=("rid", "label", "bounds"),
        previous_step_row={"focus_view_id": "id.previous"},
        recent_representative_signatures=deque(["recent"], maxlen=5),
        consumed_representative_signatures={"consumed"},
        visited_logical_signatures={"visited"},
        recent_focus_realign_signatures={"resolved"},
        failed_focus_realign_signatures={"failed"},
        consumed_cluster_signatures={"cluster"},
        consumed_cluster_logical_signatures={"cluster:logical"},
        recent_focus_realign_clusters={"cluster:resolved"},
        cluster_title_fallback_applied={"cluster:title"},
        active_container_group_signature="container_group",
        active_container_group_remaining={"remaining"},
        active_container_group_labels={"remaining": "Remaining"},
        completed_container_groups={"completed"},
        content_phase_grace_steps=0,
        current_local_tab_signature="tabs",
        last_selected_local_tab_signature="",
        last_selected_local_tab_rid="",
        last_selected_local_tab_label="",
        last_selected_local_tab_bounds="",
        scroll_state=SimpleNamespace(
            recent_scroll_fallback_signatures={"fallback"},
            last_scroll_fallback_attempted_signatures={"attempted"},
            scroll_ready_retry_counts={"cluster": 2},
            pending_scroll_ready_cluster_signature="cluster",
        ),
    )

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Medication",
        active_rid="com.example:id/medication_button",
        active_signature="tabs",
        active_bounds="40,1700,300,1860",
    )

    assert state.recent_focus_realign_signatures == set()
    assert state.failed_focus_realign_signatures == set()
    assert state.recent_focus_realign_clusters == set()
    assert state.cluster_title_fallback_applied == set()


def test_focus_realign_state_nested_records_success_signature_and_cluster(monkeypatch):
    def realign_success(**_kwargs):
        return True, "matched", _focus_node(
            rid="com.example:id/weather_banner",
            text="Weather information",
            bounds="40,420,1040,760",
        )

    monkeypatch.setattr(collection_flow, "_maybe_realign_focus_to_representative", realign_success)
    state = _nested_focus_realign_state()
    client = FakeReprioritizeClient(_bottom_strip_reprioritize_nodes())

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=_bottom_strip_row(),
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=32,
    )

    signature = collection_flow._build_candidate_object_signature(
        rid="com.example:id/weather_banner",
        bounds="40,420,1040,760",
        label="Weather information",
    )
    focus_state = state.focus_realign_state
    assert updated["focus_view_id"] == "com.example:id/weather_banner"
    assert signature in focus_state.recent_focus_realign_signatures
    assert signature not in focus_state.failed_focus_realign_signatures
    assert updated["focus_cluster_signature"] in focus_state.recent_focus_realign_clusters
    _assert_direct_focus_realign_fields_untouched(state)


def test_focus_realign_state_nested_records_failed_signature(monkeypatch):
    def realign_failure(**_kwargs):
        return False, "no_match", None

    monkeypatch.setattr(collection_flow, "_maybe_realign_focus_to_representative", realign_failure)
    state = _nested_focus_realign_state()
    client = FakeReprioritizeClient(_bottom_strip_reprioritize_nodes())

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=_bottom_strip_row(),
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=33,
    )

    signature = collection_flow._build_candidate_object_signature(
        rid="com.example:id/weather_banner",
        bounds="40,420,1040,760",
        label="Weather information",
    )
    focus_state = state.focus_realign_state
    assert updated["focus_view_id"] == "com.example:id/weather_banner"
    assert signature in focus_state.failed_focus_realign_signatures
    assert signature not in focus_state.recent_focus_realign_signatures
    assert focus_state.recent_focus_realign_clusters == set()
    _assert_direct_focus_realign_fields_untouched(state)


def test_focus_realign_state_nested_skips_recent_signature():
    candidate = _candidate("Weather information", "com.example:id/weather_banner", "40,420,1040,760")
    state = _nested_focus_realign_state(
        recent_focus_realign_signatures={collection_flow._candidate_object_signature(candidate)}
    )

    filtered = collection_flow._filter_realign_target_candidates([candidate], state=state)

    assert filtered["eligible"] == []
    assert filtered["rejected_resolved"] == [candidate]
    _assert_direct_focus_realign_fields_untouched(state)


def test_focus_realign_state_nested_skips_recent_cluster():
    candidate = _candidate(
        "Weather information",
        "com.example:id/weather_banner",
        "40,420,1040,760",
        cluster_signature="cluster:weather",
    )
    state = _nested_focus_realign_state(recent_focus_realign_clusters={"cluster:weather"})

    filtered = collection_flow._filter_realign_target_candidates([candidate], state=state)

    assert filtered["eligible"] == []
    assert filtered["rejected_resolved"] == [candidate]
    _assert_direct_focus_realign_fields_untouched(state)


def test_focus_realign_state_nested_resets_on_local_tab_transition():
    state = _nested_focus_realign_state(
        recent_focus_realign_signatures={"resolved"},
        failed_focus_realign_signatures={"failed"},
        recent_focus_realign_clusters={"cluster:resolved"},
        cluster_title_fallback_applied={"cluster:title"},
    )
    state.fail_count = 2
    state.same_count = 3
    state.prev_fingerprint = ("rid", "label", "bounds")
    state.previous_step_row = {"focus_view_id": "id.previous"}
    state.recent_representative_signatures = deque(["recent"], maxlen=5)
    state.consumed_representative_signatures = {"consumed"}
    state.visited_logical_signatures = {"visited"}
    state.consumed_cluster_signatures = {"cluster"}
    state.consumed_cluster_logical_signatures = {"cluster:logical"}
    state.active_container_group_signature = "container_group"
    state.active_container_group_remaining = {"remaining"}
    state.active_container_group_labels = {"remaining": "Remaining"}
    state.completed_container_groups = {"completed"}
    state.content_phase_grace_steps = 0
    state.current_local_tab_signature = "tabs"
    state.last_selected_local_tab_signature = ""
    state.last_selected_local_tab_rid = ""
    state.last_selected_local_tab_label = ""
    state.last_selected_local_tab_bounds = ""
    state.scroll_state = SimpleNamespace(
        recent_scroll_fallback_signatures={"fallback"},
        last_scroll_fallback_attempted_signatures={"attempted"},
        scroll_ready_retry_counts={"cluster": 2},
        pending_scroll_ready_cluster_signature="cluster",
    )

    collection_flow._reset_content_phase_after_tab_switch(
        state,
        active_label="Medication",
        active_rid="com.example:id/medication_button",
        active_signature="tabs",
        active_bounds="40,1700,300,1860",
    )

    focus_state = state.focus_realign_state
    assert focus_state.recent_focus_realign_signatures == set()
    assert focus_state.failed_focus_realign_signatures == set()
    assert focus_state.recent_focus_realign_clusters == set()
    assert focus_state.cluster_title_fallback_applied == set()
    _assert_direct_focus_realign_fields_untouched(state)


def test_focus_realign_state_nested_cluster_title_fallback_applied_once():
    title_candidate = {
        "label": "Steps",
        "rid": "com.example:id/title",
        "bounds": "80,460,980,560",
        "cluster_signature": "cluster:steps",
        "cluster_role": "title",
    }
    container_candidate = {
        "label": "Steps Overview",
        "rid": "com.example:id/info_card_container",
        "bounds": "40,420,1040,980",
        "cluster_signature": "cluster:steps",
        "cluster_role": "container",
        "representative": True,
        "score": 500000,
        "top": 420,
    }
    title_candidate["cluster_members"] = [title_candidate, container_candidate]
    state = _nested_focus_realign_state(cluster_title_fallback_applied={"cluster:steps"})

    fallback = collection_flow._select_better_cluster_representative(
        selected_candidate=title_candidate,
        state=state,
        row={"move_result": "failed"},
    )

    assert fallback is None
    assert state.focus_realign_state.cluster_title_fallback_applied == {"cluster:steps"}
    _assert_direct_focus_realign_fields_untouched(state)
