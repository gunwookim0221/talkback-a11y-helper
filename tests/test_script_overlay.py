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
    def __init__(self, verify_rows, dump_nodes=None):
        self.verify_rows = list(verify_rows)
        self.select_calls = []
        self.dump_nodes = dump_nodes
        self.dump_tree_calls = 0

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
        return True

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
