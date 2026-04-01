import sys
from types import SimpleNamespace


class _DummyDataFrame:
    def __init__(self, rows):
        self.rows = rows
        self.columns = []
        self.empty = len(rows) == 0

    def apply(self, fn, axis=1):
        return []

    def __getitem__(self, key):
        return self

    def __setitem__(self, key, value):
        return None

    def to_excel(self, *args, **kwargs):
        return None


sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=_DummyDataFrame))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))
sys.modules.setdefault("PIL", SimpleNamespace(Image=object))

import script_test


class DummyClient:
    def __init__(self):
        self.touch_calls = []
        self.back_calls = []
        self.select_calls = []
        self.collect_calls = 0

    def touch(self, **kwargs):
        self.touch_calls.append(kwargs)
        return True

    def collect_focus_step(self, **kwargs):
        self.collect_calls += 1
        return {
            "step_index": kwargs.get("step_index", 0),
            "move_result": "ok",
            "visible_label": f"Overlay Item {self.collect_calls}",
            "normalized_visible_label": f"overlay item {self.collect_calls}",
            "merged_announcement": "",
            "focus_view_id": f"id_{self.collect_calls}",
            "focus_bounds": "0,0,10,10",
        }

    def press_back_and_recover_focus(self, **kwargs):
        self.back_calls.append(kwargs)
        return {"status": "ok"}

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return True


class RealignDummyClient:
    def __init__(self, focus_steps):
        self.focus_steps = list(focus_steps)
        self.calls = []
        self.collect_focus_step_calls = 0

    def collect_focus_step(self, **kwargs):
        self.collect_focus_step_calls += 1
        raise AssertionError("realign probe should not call collect_focus_step")

    def move_focus_smart(self, **kwargs):
        self.calls.append({"kind": "move_focus_smart", **kwargs})
        return "moved"

    def move_focus(self, **kwargs):
        self.calls.append({"kind": "move_focus", **kwargs})
        return True

    def get_focus(self, **kwargs):
        self.calls.append({"kind": "get_focus", **kwargs})
        if self.focus_steps:
            return self.focus_steps.pop(0)
        return {
            "text": "",
            "contentDescription": "",
            "viewIdResourceName": "",
            "boundsInScreen": "",
        }

    @staticmethod
    def extract_visible_label_from_focus(focus_node):
        if not isinstance(focus_node, dict):
            return ""
        return str(focus_node.get("text", "") or focus_node.get("contentDescription", "") or "").strip()

    @staticmethod
    def normalize_for_comparison(text):
        return str(text or "").strip().lower()

    @staticmethod
    def _normalize_bounds(focus_node):
        if not isinstance(focus_node, dict):
            return ""
        bounds = focus_node.get("boundsInScreen")
        return str(bounds or "").strip()


def test_should_expand_overlay_matches_allowlisted_resource_id():
    step = {
        "focus_view_id": "com.samsung.android.oneconnect:id/add_menu_button",
        "normalized_visible_label": "random",
    }
    matched, reason = script_test.is_overlay_candidate(step, tab_cfg={})
    assert matched is True
    assert reason == "matched_global_candidates"


def test_should_expand_overlay_rejects_non_allowlisted_target():
    step = {
        "focus_view_id": "com.example:id/not_allowed",
        "normalized_visible_label": "not allowed",
    }
    matched, reason = script_test.is_overlay_candidate(step, tab_cfg={})
    assert matched is False
    assert reason == "not_in_global_candidates"


def test_is_overlay_candidate_blocked_by_scenario_policy():
    step = {
        "focus_view_id": "com.samsung.android.oneconnect:id/add_menu_button",
        "normalized_visible_label": "add",
    }
    tab_cfg = {
        "overlay_policy": {
            "allow_candidates": [
                {
                    "resource_id": "com.samsung.android.oneconnect:id/add_menu_button",
                    "label": "Add",
                }
            ],
            "block_candidates": [
                {
                    "resource_id": "com.samsung.android.oneconnect:id/add_menu_button",
                    "label": "Add",
                }
            ],
        }
    }
    matched, reason = script_test.is_overlay_candidate(step, tab_cfg=tab_cfg)
    assert matched is False
    assert reason == "blocked_by_scenario_policy"


class _ClassifyClient:
    def __init__(self, post_step):
        self.post_step = post_step

    def collect_focus_step(self, **kwargs):
        return self.post_step


def test_classify_post_click_result_navigation_case():
    pre = {
        "step_index": 4,
        "normalized_visible_label": "add",
        "focus_view_id": "com.samsung.android.oneconnect:id/add_menu_button",
        "focus_bounds": "0,10,10,20",
        "dump_tree_nodes": [{"viewIdResourceName": "id_a", "text": "A", "contentDescription": ""}],
    }
    post = {
        "normalized_visible_label": "navigate up",
        "visible_label": "Navigate up",
        "merged_announcement": "Navigate up",
        "focus_view_id": "com.example:id/toolbar_back",
        "focus_bounds": "0,0,10,10",
        "dump_tree_nodes": [{"viewIdResourceName": "id_b", "text": "B", "contentDescription": ""}],
    }
    classification, _ = script_test.classify_post_click_result(
        client=_ClassifyClient(post),
        dev="SERIAL",
        tab_cfg={},
        pre_click_step=pre,
    )
    assert classification == "navigation"


def test_classify_post_click_result_overlay_case():
    pre = {
        "step_index": 4,
        "normalized_visible_label": "more options",
        "focus_view_id": "com.samsung.android.oneconnect:id/more_menu_button",
        "focus_bounds": "0,10,10,20",
        "dump_tree_nodes": [
            {"viewIdResourceName": "id_common", "text": "Room", "contentDescription": ""},
            {"viewIdResourceName": "id_more", "text": "More options", "contentDescription": ""},
        ],
    }
    post = {
        "normalized_visible_label": "edit",
        "visible_label": "Edit",
        "merged_announcement": "Edit",
        "focus_view_id": "com.samsung.android.oneconnect:id/menu_edit",
        "focus_bounds": "0,30,10,40",
        "dump_tree_nodes": [
            {"viewIdResourceName": "id_common", "text": "Room", "contentDescription": ""},
            {"viewIdResourceName": "id_menu_edit", "text": "Edit", "contentDescription": ""},
        ],
    }
    classification, _ = script_test.classify_post_click_result(
        client=_ClassifyClient(post),
        dev="SERIAL",
        tab_cfg={},
        pre_click_step=pre,
    )
    assert classification == "overlay"


def test_classify_post_click_result_overlay_candidate_guards_overlap_navigation():
    pre = {
        "step_index": 4,
        "normalized_visible_label": "add",
        "visible_label": "Add",
        "focus_view_id": "com.samsung.android.oneconnect:id/add_menu_button",
        "focus_bounds": "0,10,10,20",
        "dump_tree_nodes": [
            {"viewIdResourceName": "id_home_only", "text": "홈", "contentDescription": ""},
            {"viewIdResourceName": "id_add", "text": "Add", "contentDescription": ""},
        ],
    }
    post = {
        "normalized_visible_label": "add favourites",
        "visible_label": "Add favourites",
        "merged_announcement": "Add favourites",
        "focus_view_id": "com.samsung.android.oneconnect:id/add_favourites_title",
        "focus_bounds": "0,30,10,40",
        "dump_tree_nodes": [
            {"viewIdResourceName": "id_sheet_only", "text": "즐겨찾기 추가", "contentDescription": ""},
            {"viewIdResourceName": "id_delete", "text": "Delete", "contentDescription": ""},
        ],
    }
    classification, _ = script_test.classify_post_click_result(
        client=_ClassifyClient(post),
        dev="SERIAL",
        tab_cfg={"overlay_policy": {"allow_candidates": [{"resource_id": "com.samsung.android.oneconnect:id/add_menu_button", "label": "Add"}]}},
        pre_click_step=pre,
    )
    assert classification == "overlay"


def test_classify_post_click_result_non_overlay_candidate_keeps_overlap_navigation_rule():
    pre = {
        "step_index": 4,
        "normalized_visible_label": "location",
        "visible_label": "Location",
        "focus_view_id": "com.samsung.android.oneconnect:id/location_button",
        "focus_bounds": "0,10,10,20",
        "dump_tree_nodes": [{"viewIdResourceName": "id_a", "text": "A", "contentDescription": ""}],
    }
    post = {
        "normalized_visible_label": "add favourites",
        "visible_label": "Add favourites",
        "merged_announcement": "Add favourites",
        "focus_view_id": "com.samsung.android.oneconnect:id/add_favourites_title",
        "focus_bounds": "0,30,10,40",
        "dump_tree_nodes": [{"viewIdResourceName": "id_b", "text": "B", "contentDescription": ""}],
    }
    classification, _ = script_test.classify_post_click_result(
        client=_ClassifyClient(post),
        dev="SERIAL",
        tab_cfg={"overlay_policy": {"allow_candidates": [{"resource_id": "com.samsung.android.oneconnect:id/add_menu_button", "label": "Add"}]}},
        pre_click_step=pre,
    )
    assert classification == "navigation"


def test_expand_overlay_uses_entry_label_as_primary_recovery_anchor(monkeypatch):
    monkeypatch.setattr(script_test, "save_excel", lambda *args, **kwargs: None)
    monkeypatch.setattr(script_test, "maybe_capture_focus_crop", lambda *_args, **_kwargs: _args[2])

    client = DummyClient()
    entry_step = {
        "step_index": 3,
        "visible_label": "Add",
        "normalized_visible_label": "add",
        "focus_view_id": "com.samsung.android.oneconnect:id/add_menu_button",
    }
    rows = []
    all_rows = []

    script_test.expand_overlay(
        client=client,
        dev="SERIAL",
        tab_cfg={"tab_name": ".*Home.*", "anchor_name": ".*Location QR code.*", "anchor_type": "b"},
        entry_step=entry_step,
        rows=rows,
        all_rows=all_rows,
        output_path="output.xlsx",
        output_base_dir="output/base",
    )

    assert client.back_calls
    assert client.back_calls[0]["expected_parent_anchor"] == "add"
    assert all(row["context_type"] == "overlay" for row in rows)


def test_should_stop_same_label_different_bounds_does_not_stop():
    row1 = {
        "move_result": "ok",
        "visible_label": "Turn on",
        "normalized_visible_label": "turn on",
        "focus_view_id": "com.example:id/toggle",
        "focus_bounds": "0,0,10,10",
        "merged_announcement": "Turn on",
    }
    row2 = {
        "move_result": "ok",
        "visible_label": "Turn on",
        "normalized_visible_label": "turn on",
        "focus_view_id": "com.example:id/toggle",
        "focus_bounds": "0,20,10,30",
        "merged_announcement": "Turn on",
    }

    stop, fail_count, same_count, reason, prev_fp = script_test.should_stop(
        row=row1,
        prev_fingerprint=("", "", ""),
        fail_count=0,
        same_count=0,
    )
    assert stop is False
    assert fail_count == 0
    assert same_count == 0
    assert reason == ""

    stop, fail_count, same_count, reason, _ = script_test.should_stop(
        row=row2,
        prev_fingerprint=prev_fp,
        fail_count=fail_count,
        same_count=same_count,
    )
    assert stop is False
    assert fail_count == 0
    assert same_count == 0
    assert reason == ""


def test_should_stop_same_fingerprint_repeated_stops():
    row = {
        "move_result": "ok",
        "visible_label": "Turn off",
        "normalized_visible_label": "turn off",
        "focus_view_id": "com.example:id/toggle",
        "focus_bounds": "0,0,10,10",
        "merged_announcement": "Turn off",
    }
    prev_fp = ("", "", "")
    fail_count = 0
    same_count = 0

    for _ in range(4):
        stop, fail_count, same_count, reason, prev_fp = script_test.should_stop(
            row=row,
            prev_fingerprint=prev_fp,
            fail_count=fail_count,
            same_count=same_count,
        )

    assert stop is True
    assert same_count >= 3
    assert reason == "same_fingerprint_repeated"


def test_realign_focus_after_overlay_moves_to_entry_when_focus_is_before_entry():
    client = RealignDummyClient(
        [
            {
                "text": "Map View",
                "viewIdResourceName": "id_map",
                "boundsInScreen": "0,0,10,10",
            },
            {
                "text": "Add",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button",
                "boundsInScreen": "0,10,10,20",
            },
        ]
    )
    entry_step = {
        "step_index": 3,
        "normalized_visible_label": "add",
        "focus_view_id": "com.samsung.android.oneconnect:id/add_menu_button",
        "focus_bounds": "0,10,10,20",
    }
    known = {("our home", "id_home", "0,0,10,10"): 1, ("map view", "id_map", "0,0,10,10"): 2}

    result = script_test.realign_focus_after_overlay(
        client=client,
        dev="SERIAL",
        entry_step=entry_step,
        known_step_index_by_fingerprint=known,
    )

    assert result["entry_reached"] is True
    assert result["status"] == "realign_entry_reached"
    assert result["steps_taken"] == 1
    assert len(client.calls) == 3
    assert client.calls[0]["kind"] == "get_focus"
    assert client.calls[1]["kind"] == "move_focus_smart"
    assert client.calls[2]["kind"] == "get_focus"
    assert client.collect_focus_step_calls == 0


def test_realign_focus_after_overlay_skips_when_focus_not_known_as_prior_step():
    client = RealignDummyClient(
        [
            {
                "text": "More options",
                "viewIdResourceName": "id_more",
                "boundsInScreen": "0,20,10,30",
            }
        ]
    )
    entry_step = {
        "step_index": 3,
        "normalized_visible_label": "add",
        "focus_view_id": "com.samsung.android.oneconnect:id/add_menu_button",
        "focus_bounds": "0,10,10,20",
    }

    result = script_test.realign_focus_after_overlay(
        client=client,
        dev="SERIAL",
        entry_step=entry_step,
        known_step_index_by_fingerprint={},
    )

    assert result["entry_reached"] is False
    assert result["status"] == "skip_realign_not_before_entry"
    assert result["steps_taken"] == 0
    assert len(client.calls) == 1
    assert client.calls[0]["kind"] == "get_focus"
    assert client.collect_focus_step_calls == 0


def test_match_anchor_allows_resource_id_only():
    anchor_cfg = {
        "resource_id_regex": r"com\.example:id/anchor",
        "allow_resource_id_only": True,
    }
    candidate = {
        "resource_id": "com.example:id/anchor",
        "text": "",
        "announcement": "",
        "class_name": "",
        "top": 20,
        "left": 8,
    }

    matched = script_test.match_anchor(candidate, anchor_cfg)

    assert matched["matched"] is True
    assert "resource_id" in matched["matched_fields"]


def test_choose_best_anchor_candidate_prefers_top_left_for_tie():
    matches = [
        {"score": 100, "candidate": {"top": 50, "left": 20}},
        {"score": 100, "candidate": {"top": 10, "left": 30}},
        {"score": 100, "candidate": {"top": 10, "left": 15}},
    ]

    best = script_test.choose_best_anchor_candidate(matches, tie_breaker="top_left")

    assert best == matches[2]


class StabilizeDummyClient:
    def __init__(self, verify_rows, dump_nodes=None, select_result=True, touch_point_result=True):
        self.verify_rows = list(verify_rows)
        self.select_calls = []
        self.dump_nodes = dump_nodes
        self.dump_tree_calls = 0
        self.select_result = select_result
        self.touch_point_result = touch_point_result
        self.touch_point_calls = []

    def dump_tree(self, **_kwargs):
        self.dump_tree_calls += 1
        if isinstance(self.dump_nodes, list):
            return self.dump_nodes
        return [
            {
                "text": "Location QR code",
                "contentDescription": "Location QR code",
                "talkbackLabel": "Location QR code",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/location_qr",
                "className": "android.widget.ImageView",
                "boundsInScreen": "0,0,10,10",
            }
        ]

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return self.select_result

    def touch(self, **kwargs):
        self.select_calls.append({"touch": True, **kwargs})
        return self.select_result

    def touch_point(self, **kwargs):
        self.touch_point_calls.append(kwargs)
        return self.touch_point_result

    def collect_focus_step(self, **kwargs):
        if self.verify_rows:
            row = dict(self.verify_rows.pop(0))
        else:
            row = {}
        row.setdefault("visible_label", "")
        row.setdefault("merged_announcement", "")
        row.setdefault("focus_view_id", "com.samsung.android.oneconnect:id/location_qr")
        row.setdefault("focus_bounds", "0,0,10,10")
        row.setdefault("focus_node", {"className": "android.widget.ImageView"})
        return row


def test_verify_context_selected_bottom_tab_distinguishes_home_and_devices():
    home_step = {
        "visible_label": "Location QR code",
        "merged_announcement": "QR code",
        "dump_tree_nodes": [
            {
                "text": "Home",
                "contentDescription": "Selected, Home, Tab 1 of 5",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_home",
                "selected": True,
                "boundsInScreen": "0,1800,200,1910",
            }
        ],
    }
    devices_step = {
        "visible_label": "Location QR code",
        "merged_announcement": "QR code",
        "dump_tree_nodes": [
            {
                "text": "Devices",
                "contentDescription": "Selected, Devices, Tab 2 of 5",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_devices",
                "selected": True,
                "boundsInScreen": "200,1800,400,1910",
            }
        ],
    }
    home_cfg = {"context_verify": {"type": "selected_bottom_tab", "announcement_regex": ".*Home.*"}}
    devices_cfg = {"context_verify": {"type": "selected_bottom_tab", "announcement_regex": ".*Devices.*"}}

    assert script_test.verify_context(home_step, home_cfg)["ok"] is True
    assert script_test.verify_context(home_step, devices_cfg)["ok"] is False
    assert script_test.verify_context(devices_step, devices_cfg)["ok"] is True


def test_verify_context_selected_bottom_tab_uses_lazy_dump_when_step_cache_empty():
    step = {"visible_label": "Location QR code", "merged_announcement": "QR code", "dump_tree_nodes": []}
    devices_cfg = {"context_verify": {"type": "selected_bottom_tab", "announcement_regex": ".*Devices.*"}}
    client = StabilizeDummyClient(
        verify_rows=[],
        dump_nodes=[
            {
                "text": "Devices",
                "contentDescription": "Selected, Devices, Tab 2 of 5",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_devices",
                "selected": True,
                "boundsInScreen": "200,1800,400,1910",
            }
        ],
    )

    result = script_test.verify_context(step, devices_cfg, client=client, dev="SERIAL")

    assert result["ok"] is True
    assert result["dump_source"] == "lazy_dump"
    assert result["lazy_dump_node_count"] == 1
    assert client.dump_tree_calls == 1
    assert len(step["dump_tree_nodes"]) == 1


def test_stabilize_anchor_fails_when_anchor_matches_but_context_fails():
    client = StabilizeDummyClient(
        [
            {
                "visible_label": "Location QR code",
                "merged_announcement": "QR code",
                "dump_tree_nodes": [
                    {
                        "text": "Home",
                        "contentDescription": "Selected, Home, Tab 1 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_home",
                        "selected": True,
                        "boundsInScreen": "0,1800,200,1910",
                    }
                ],
            },
            {
                "visible_label": "Location QR code",
                "merged_announcement": "QR code",
                "dump_tree_nodes": [
                    {
                        "text": "Home",
                        "contentDescription": "Selected, Home, Tab 1 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_home",
                        "selected": True,
                        "boundsInScreen": "0,1800,200,1910",
                    }
                ],
            },
        ]
    )
    tab_cfg = {
        "scenario_id": "devices_main",
        "anchor_name": ".*Location QR code.*",
        "anchor_type": "b",
        "anchor": {
            "text_regex": ".*Location QR code.*",
            "announcement_regex": ".*QR code.*",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": ".*Devices.*",
        },
    }

    result = script_test.stabilize_anchor(client=client, dev="SERIAL", tab_cfg=tab_cfg, phase="scenario_start")

    assert result["ok"] is False
    assert result["verify"]["matched"] is True
    assert result["context"]["ok"] is False


def test_match_tab_candidate_allows_resource_id_only():
    tab_cfg = {
        "resource_id_regex": r"com\.samsung\.android\.oneconnect:id/menu_devices",
        "allow_resource_id_only": True,
    }
    node = {
        "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
        "text": "",
        "contentDescription": "",
        "className": "android.widget.Button",
        "boundsInScreen": "200,1800,400,1910",
    }

    matched = script_test.match_tab_candidate(node, tab_cfg)

    assert matched["matched"] is True
    assert "resource_id" in matched["matched_fields"]


def test_match_tab_candidate_supports_text_and_announcement_combo():
    tab_cfg = {
        "text_regex": r".*devices.*",
        "announcement_regex": r".*selected.*devices.*",
    }
    node = {
        "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
        "text": "Devices",
        "contentDescription": "Selected, Devices, Tab 2 of 5",
        "className": "android.widget.Button",
        "boundsInScreen": "200,1800,400,1910",
    }

    matched = script_test.match_tab_candidate(node, tab_cfg)

    assert matched["matched"] is True
    assert set(matched["matched_fields"]) >= {"text", "announcement"}


def test_choose_best_tab_candidate_bottom_nav_left_to_right_tie_breaker():
    matches = [
        {"score": 100, "matched_fields": ["text"], "candidate": {"top": 1000, "left": 800}},
        {"score": 100, "matched_fields": ["resource_id", "text"], "candidate": {"top": 1800, "left": 400}},
        {"score": 100, "matched_fields": ["text"], "candidate": {"top": 1800, "left": 600}},
    ]

    best = script_test.choose_best_tab_candidate(matches, tie_breaker="bottom_nav_left_to_right")

    assert best == matches[1]


def test_stabilize_tab_selection_requires_selected_bottom_tab_before_anchor():
    client = StabilizeDummyClient(
        verify_rows=[
            {
                "visible_label": "Devices",
                "merged_announcement": "Selected, Devices",
                "dump_tree_nodes": [
                    {
                        "text": "Devices",
                        "contentDescription": "Selected, Devices, Tab 2 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
                        "selected": True,
                        "boundsInScreen": "200,1800,400,1910",
                    }
                ],
            }
        ],
        dump_nodes=[
            {
                "text": "Devices",
                "contentDescription": "Devices",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
                "className": "android.widget.Button",
                "boundsInScreen": "200,1800,400,1910",
            }
        ],
    )
    tab_cfg = {
        "scenario_id": "devices_main",
        "tab_name": "(?i).*devices.*",
        "tab_type": "b",
        "tab": {"resource_id_regex": r"com\.samsung\.android\.oneconnect:id/menu_devices", "allow_resource_id_only": True},
        "context_verify": {"type": "selected_bottom_tab", "announcement_regex": ".*Devices.*"},
    }

    result = script_test.stabilize_tab_selection(client=client, dev="SERIAL", tab_cfg=tab_cfg)

    assert result["ok"] is True
    assert result["verify_context"]["ok"] is True


def test_stabilize_tab_selection_prefers_touch_point_when_best_bounds_exist():
    client = StabilizeDummyClient(
        verify_rows=[
            {
                "visible_label": "Devices",
                "merged_announcement": "Selected, Devices",
                "dump_tree_nodes": [
                    {
                        "text": "Devices",
                        "contentDescription": "Selected, Devices, Tab 2 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
                        "selected": True,
                        "boundsInScreen": "200,1800,400,1910",
                    }
                ],
            }
        ],
        dump_nodes=[
            {
                "text": "Devices",
                "contentDescription": "Devices",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
                "className": "android.widget.Button",
                "boundsInScreen": "200,1800,400,1910",
            }
        ],
    )
    tab_cfg = {
        "scenario_id": "devices_main",
        "tab_name": "(?i).*devices.*",
        "tab_type": "b",
        "tab": {"resource_id_regex": r"com\.samsung\.android\.oneconnect:id/menu_devices", "allow_resource_id_only": True},
        "context_verify": {"type": "selected_bottom_tab", "announcement_regex": ".*Devices.*"},
    }

    result = script_test.stabilize_tab_selection(client=client, dev="SERIAL", tab_cfg=tab_cfg)

    assert result["ok"] is True
    assert client.touch_point_calls
    assert client.touch_point_calls[0]["x"] == 300
    assert client.touch_point_calls[0]["y"] == 1855
    assert all("type_" not in call for call in client.touch_point_calls)


def test_stabilize_tab_selection_fallbacks_to_select_when_bounds_missing():
    client = StabilizeDummyClient(
        verify_rows=[
            {
                "visible_label": "Devices",
                "merged_announcement": "Selected, Devices",
                "dump_tree_nodes": [
                    {
                        "text": "Devices",
                        "contentDescription": "Selected, Devices, Tab 2 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
                        "selected": True,
                        "boundsInScreen": "200,1800,400,1910",
                    }
                ],
            }
        ],
        dump_nodes=[
            {
                "text": "Devices",
                "contentDescription": "Devices",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
                "className": "android.widget.Button",
                "boundsInScreen": "",
            }
        ],
    )
    tab_cfg = {
        "scenario_id": "devices_main",
        "tab_name": "(?i).*devices.*",
        "tab_type": "b",
        "tab": {"resource_id_regex": r"com\.samsung\.android\.oneconnect:id/menu_devices", "allow_resource_id_only": True},
        "context_verify": {"type": "selected_bottom_tab", "announcement_regex": ".*Devices.*"},
    }

    result = script_test.stabilize_tab_selection(client=client, dev="SERIAL", tab_cfg=tab_cfg)

    assert result["ok"] is True
    assert client.touch_point_calls == []
    assert any(call.get("type_") == "r" for call in client.select_calls if isinstance(call, dict))


def test_stabilize_tab_selection_fallbacks_to_select_when_touch_point_fails():
    client = StabilizeDummyClient(
        verify_rows=[
            {
                "visible_label": "Devices",
                "merged_announcement": "Selected, Devices",
                "dump_tree_nodes": [
                    {
                        "text": "Devices",
                        "contentDescription": "Selected, Devices, Tab 2 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
                        "selected": True,
                        "boundsInScreen": "200,1800,400,1910",
                    }
                ],
            }
        ],
        dump_nodes=[
            {
                "text": "Devices",
                "contentDescription": "Devices",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices",
                "className": "android.widget.Button",
                "boundsInScreen": "200,1800,400,1910",
            }
        ],
        touch_point_result=False,
        select_result=True,
    )
    tab_cfg = {
        "scenario_id": "devices_main",
        "tab_name": "(?i).*devices.*",
        "tab_type": "b",
        "tab": {"resource_id_regex": r"com\.samsung\.android\.oneconnect:id/menu_devices", "allow_resource_id_only": True},
        "context_verify": {"type": "selected_bottom_tab", "announcement_regex": ".*Devices.*"},
    }

    result = script_test.stabilize_tab_selection(client=client, dev="SERIAL", tab_cfg=tab_cfg)

    assert result["ok"] is True
    assert client.touch_point_calls
    assert any(call.get("type_") == "r" for call in client.select_calls if isinstance(call, dict))


def test_normalize_tab_config_keeps_backward_compatibility():
    legacy = {"tab_name": "(?i).*menu.*", "tab_type": "b"}

    normalized = script_test.normalize_tab_config(legacy)

    assert normalized["text_regex"] == "(?i).*menu.*"
    assert normalized["_fallback_to_legacy"] is True


def test_stabilize_anchor_succeeds_when_anchor_and_context_match():
    client = StabilizeDummyClient(
        [
            {
                "visible_label": "Location QR code",
                "merged_announcement": "QR code",
                "dump_tree_nodes": [
                    {
                        "text": "Devices",
                        "contentDescription": "Selected, Devices, Tab 2 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_devices",
                        "selected": True,
                        "boundsInScreen": "200,1800,400,1910",
                    }
                ],
            }
        ]
    )
    tab_cfg = {
        "scenario_id": "devices_main",
        "anchor_name": ".*Location QR code.*",
        "anchor_type": "b",
        "anchor": {
            "text_regex": ".*Location QR code.*",
            "announcement_regex": ".*QR code.*",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": ".*Devices.*",
        },
    }

    result = script_test.stabilize_anchor(client=client, dev="SERIAL", tab_cfg=tab_cfg, phase="scenario_start")

    assert result["ok"] is True
    assert result["verify"]["matched"] is True
    assert result["context"]["ok"] is True
    assert result["reason"] == "selected_and_verified"


def test_stabilize_anchor_succeeds_without_selection_when_anchor_and_context_match():
    client = StabilizeDummyClient(
        [
            {
                "visible_label": "Location QR code",
                "merged_announcement": "QR code",
                "dump_tree_nodes": [
                    {
                        "text": "Devices",
                        "contentDescription": "Selected, Devices, Tab 2 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_devices",
                        "selected": True,
                        "boundsInScreen": "200,1800,400,1910",
                    }
                ],
            }
        ],
        select_result=False,
    )
    tab_cfg = {
        "scenario_id": "devices_main",
        "anchor_name": ".*Location QR code.*",
        "anchor_type": "b",
        "anchor": {
            "text_regex": ".*Location QR code.*",
            "announcement_regex": ".*QR code.*",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": ".*Devices.*",
        },
    }

    result = script_test.stabilize_anchor(client=client, dev="SERIAL", tab_cfg=tab_cfg, phase="scenario_start")

    assert result["ok"] is True
    assert result["selected"] is False
    assert result["verify"]["matched"] is True
    assert result["context"]["ok"] is True
    assert result["reason"] == "verified_without_select"


def test_menu_main_uses_smartthings_anchor_config():
    menu_cfg = next(cfg for cfg in script_test.TAB_CONFIGS if cfg.get("scenario_id") == "menu_main")

    assert menu_cfg["anchor_name"] == "(?i).*smartthings.*"
    assert menu_cfg["anchor"]["text_regex"] == "(?i).*smartthings.*"
    assert menu_cfg["anchor"]["announcement_regex"] == "(?i).*smartthings.*"


def test_non_menu_tabs_keep_common_qr_anchor_config():
    target_ids = {"home_main", "devices_main", "life_main", "routines_main"}
    target_cfgs = [cfg for cfg in script_test.TAB_CONFIGS if cfg.get("scenario_id") in target_ids]

    assert len(target_cfgs) == 4
    for cfg in target_cfgs:
        assert cfg["anchor_name"] == "(?i).*location.*qr.*code.*"
        assert cfg["anchor"]["text_regex"] == "(?i).*location.*qr.*code.*"
        assert cfg["anchor"]["announcement_regex"] == "(?i).*qr.*code.*"


def test_life_and_routines_block_add_on_overlay_policy():
    for scenario_id in ("life_main", "routines_main"):
        cfg = next(cfg for cfg in script_test.TAB_CONFIGS if cfg.get("scenario_id") == scenario_id)
        overlay_policy = cfg.get("overlay_policy", {})
        allow_ids = {candidate.get("resource_id") for candidate in overlay_policy.get("allow_candidates", [])}
        block_ids = {candidate.get("resource_id") for candidate in overlay_policy.get("block_candidates", [])}

        assert allow_ids == {"com.samsung.android.oneconnect:id/more_menu_button"}
        assert block_ids == {"com.samsung.android.oneconnect:id/add_menu_button"}


def test_overlay_realign_anchor_match_but_wrong_tab_fails():
    client = StabilizeDummyClient(
        [
            {
                "visible_label": "Location QR code",
                "merged_announcement": "QR code",
                "dump_tree_nodes": [
                    {
                        "text": "Home",
                        "contentDescription": "Selected, Home, Tab 1 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_home",
                        "selected": True,
                        "boundsInScreen": "0,1800,200,1910",
                    }
                ],
            },
            {
                "visible_label": "Location QR code",
                "merged_announcement": "QR code",
                "dump_tree_nodes": [
                    {
                        "text": "Home",
                        "contentDescription": "Selected, Home, Tab 1 of 5",
                        "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_home",
                        "selected": True,
                        "boundsInScreen": "0,1800,200,1910",
                    }
                ],
            },
        ]
    )
    tab_cfg = {
        "scenario_id": "devices_main",
        "anchor_name": ".*Location QR code.*",
        "anchor_type": "b",
        "anchor": {
            "text_regex": ".*Location QR code.*",
            "announcement_regex": ".*QR code.*",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": ".*Devices.*",
        },
    }

    result = script_test.stabilize_anchor(client=client, dev="SERIAL", tab_cfg=tab_cfg, phase="overlay_realign")

    assert result["phase"] == "overlay_realign"
    assert result["ok"] is False
    assert result["verify"]["matched"] is True
    assert result["context"]["ok"] is False


def test_detect_step_mismatch_promotes_top_level_low_confidence_only():
    row = {
        "normalized_visible_label": "map view",
        "normalized_announcement": "map view",
        "focus_payload_source": "top_level",
        "get_focus_response_success": False,
        "get_focus_top_level_success_false": True,
        "focus_view_id": "",
        "focus_bounds": "10,10,100,100",
        "get_focus_fallback_found": False,
        "crop_focus_confidence_low": True,
        "context_type": "main",
    }

    mismatch_reasons, low_confidence_reasons = script_test.detect_step_mismatch(row=row, previous_step=None)

    assert mismatch_reasons == []
    assert "get_focus_top_level_success_false" in low_confidence_reasons
    assert "crop_low_confidence" in low_confidence_reasons


def test_detect_step_mismatch_skips_top_level_without_fallback_dump_when_dump_found():
    row = {
        "normalized_visible_label": "map view",
        "normalized_announcement": "map view",
        "focus_payload_source": "top_level",
        "get_focus_response_success": False,
        "get_focus_top_level_success_false": True,
        "focus_view_id": "com.example:id/map",
        "focus_bounds": "10,10,100,100",
        "get_focus_fallback_found": True,
        "get_focus_success_false_top_level_dump_found": True,
        "crop_focus_confidence_low": False,
        "context_type": "main",
    }

    mismatch_reasons, low_confidence_reasons = script_test.detect_step_mismatch(row=row, previous_step=None)

    assert mismatch_reasons == []
    assert "get_focus_top_level_success_false" in low_confidence_reasons
    assert "top_level_without_fallback_dump" not in low_confidence_reasons


def test_detect_step_mismatch_accepts_speech_prefix_style_match():
    row = {
        "normalized_visible_label": "explore",
        "normalized_announcement": "explore new content available details",
        "focus_payload_source": "response",
        "get_focus_response_success": True,
        "focus_view_id": "com.example:id/explore",
        "focus_bounds": "1,1,2,2",
        "context_type": "main",
    }

    mismatch_reasons, low_confidence_reasons = script_test.detect_step_mismatch(row=row, previous_step=None)

    assert mismatch_reasons == []
    assert low_confidence_reasons == []


def test_detect_step_mismatch_flags_explicit_label_divergence():
    row = {
        "normalized_visible_label": "settings",
        "normalized_announcement": "map view",
        "focus_payload_source": "response",
        "get_focus_response_success": True,
        "focus_view_id": "com.example:id/settings",
        "focus_bounds": "1,1,2,2",
        "context_type": "main",
    }

    mismatch_reasons, _ = script_test.detect_step_mismatch(row=row, previous_step=None)

    assert "speech_visible_diverged" in mismatch_reasons
