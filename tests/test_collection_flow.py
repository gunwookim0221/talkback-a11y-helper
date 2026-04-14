import sys
import json
from pathlib import Path
from types import SimpleNamespace

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, ExcelWriter=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow


class DummyClient:
    def __init__(self, steps):
        self.steps = list(steps)
        self.reset_focus_history_calls = 0
        self.touch_calls = []
        self.scroll_touch_calls = []
        self.scroll_calls = []
        self.scroll_to_top_calls = []
        self.touch_bounds_center_calls = []
        self.tap_bounds_center_adb_calls = []
        self.select_calls = []
        self.click_focused_calls = []
        self.collect_focus_step_calls = []
        self.get_focus_calls = []
        self.dump_tree_calls = []
        self.dump_tree_sequence = []
        self.back_calls = 0
        self.last_target_action_result = {}
        self.focus_sequence = []

    def reset_focus_history(self, _dev):
        self.reset_focus_history_calls += 1

    def collect_focus_step(self, **kwargs):
        self.collect_focus_step_calls.append(kwargs)
        return dict(self.steps.pop(0))

    def touch(self, **kwargs):
        self.touch_calls.append(kwargs)
        return True

    def touch_bounds_center(self, **kwargs):
        self.touch_bounds_center_calls.append(kwargs)
        return True

    def scrollTouch(self, **kwargs):
        self.scroll_touch_calls.append(kwargs)
        self.last_target_action_result = {"reason": "touch_success"}
        return True

    def scroll(self, dev, direction, step_=50, time_=1000, bounds_=None):
        _ = (dev, step_, time_, bounds_)
        self.scroll_calls.append(direction)
        return True

    def scroll_to_top(self, **kwargs):
        self.scroll_to_top_calls.append(kwargs)
        return {"ok": True, "reached_top": True, "attempts": 1, "reason": "no_visible_change"}

    def tap_bounds_center_adb(self, **kwargs):
        self.tap_bounds_center_adb_calls.append(kwargs)
        self.last_target_action_result = {
            "reason": "adb_input_tap_sent",
            "target": {"bounds": "[100,200][300,500]", "center": {"x": 200, "y": 350}, "lazy_dump_used": False},
        }
        return True

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return True

    def click_focused(self, **kwargs):
        self.click_focused_calls.append(kwargs)
        return True

    def get_focus(self, **kwargs):
        self.get_focus_calls.append(kwargs)
        if self.focus_sequence:
            return self.focus_sequence.pop(0)
        return {}

    def dump_tree(self, **kwargs):
        self.dump_tree_calls.append(kwargs)
        if self.dump_tree_sequence:
            return self.dump_tree_sequence.pop(0)
        return []

    def _run(self, args, **kwargs):
        if args == ["shell", "input", "keyevent", "4"]:
            self.back_calls += 1
            return ""
        return ""


def _base_tab_cfg(max_steps=1):
    return {
        "tab_name": "홈",
        "scenario_id": "s1",
        "max_steps": max_steps,
        "tab_type": "t",
        "tab_name": "홈",
        "scenario_type": "content",
        "screen_context_mode": "bottom_tab",
    }


def _global_nav_tab_cfg(max_steps=1):
    cfg = _base_tab_cfg(max_steps=max_steps)
    cfg.update(
        {
            "scenario_id": "global_nav_main",
            "scenario_type": "global_nav",
            "global_nav": {
                "resource_ids": [
                    "com.samsung.android.oneconnect:id/menu_favorites",
                    "com.samsung.android.oneconnect:id/menu_devices",
                    "com.samsung.android.oneconnect:id/menu_services",
                    "com.samsung.android.oneconnect:id/menu_automations",
                    "com.samsung.android.oneconnect:id/menu_more",
                ]
            },
        }
    )
    return cfg


def _anchor_row():
    return {
        "step_index": 0,
        "move_result": "ok",
        "visible_label": "anchor",
        "normalized_visible_label": "anchor",
        "merged_announcement": "anchor",
        "focus_view_id": "id.anchor",
        "focus_bounds": "0,0,10,10",
    }


def _main_row(idx=1):
    return {
        "step_index": idx,
        "move_result": "moved",
        "visible_label": f"item{idx}",
        "normalized_visible_label": f"item{idx}",
        "merged_announcement": f"item{idx}",
        "focus_view_id": f"id.{idx}",
        "focus_bounds": "0,10,10,20",
    }


def test_open_tab_and_anchor_returns_false_when_tab_stabilization_fails(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": False})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])

    ok = collection_flow.open_tab_and_anchor(client, "SERIAL", _base_tab_cfg())

    assert ok is False


def test_open_tab_and_anchor_returns_false_when_anchor_stabilization_fails(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": False})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])

    ok = collection_flow.open_tab_and_anchor(client, "SERIAL", _base_tab_cfg())

    assert ok is False


def test_open_tab_and_anchor_returns_true_when_both_succeed(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])

    ok = collection_flow.open_tab_and_anchor(client, "SERIAL", _base_tab_cfg())

    assert ok is True


def test_collect_tab_rows_adds_tab_open_failed_and_saves(monkeypatch):
    save_calls = []
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: False)
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: save_calls.append((a, k)))

    rows = collection_flow.collect_tab_rows(
        client=DummyClient([]),
        dev="SERIAL",
        tab_cfg=_base_tab_cfg(),
        all_rows=[],
        output_path="out.xlsx",
        output_base_dir="out",
    )

    assert rows[0]["status"] == "TAB_OPEN_FAILED"
    assert len(save_calls) == 1


def test_collect_tab_rows_sets_end_status_when_should_stop(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (True, 0, 0, "repeat_no_progress", ("", "", ""), {"terminal": False, "same_like_count": 2, "no_progress": True, "reason": "repeat_no_progress"}))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=2), [], "o.xlsx", "out")

    assert rows[-1]["status"] == "END"
    assert rows[-1]["stop_reason"] == "repeat_no_progress"


def test_collect_tab_rows_checkpoint_save_called_by_interval(monkeypatch):
    steps = [_anchor_row(), _main_row(1), _main_row(2)]
    client = DummyClient(steps)
    save_calls = []

    monkeypatch.setattr(collection_flow, "CHECKPOINT_SAVE_EVERY_STEPS", 2)
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("fp", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: save_calls.append(1))
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    collection_flow.collect_tab_rows(
        client,
        "SERIAL",
        _base_tab_cfg(max_steps=2),
        [],
        "o.xlsx",
        "out",
        checkpoint_save_every=2,
    )

    assert len(save_calls) == 2  # anchor + checkpoint at step2


def test_collect_tab_rows_overlay_branch_calls_expand_and_realign(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    called = {"classify": 0, "expand": 0, "realign": 0}

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("f", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (True, "matched_global_candidates"))

    def _classify(**kwargs):
        called["classify"] += 1
        return "overlay", {"visible_label": "post", "focus_view_id": "id.post"}

    monkeypatch.setattr(collection_flow, "classify_post_click_result", _classify)
    monkeypatch.setattr(collection_flow, "expand_overlay", lambda **k: called.__setitem__("expand", called["expand"] + 1))
    monkeypatch.setattr(
        collection_flow,
        "realign_focus_after_overlay",
        lambda **k: called.__setitem__("realign", called["realign"] + 1) or {"status": "realign_entry_not_found", "entry_reached": False, "steps_taken": 1},
    )
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **k: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=1), [], "o.xlsx", "out")

    assert called == {"classify": 1, "expand": 1, "realign": 1}


def test_collect_tab_rows_navigation_classification_skips_overlay_routine(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    called = {"expand": 0, "realign": 0}

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("f", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (True, "matched_global_candidates"))
    monkeypatch.setattr(collection_flow, "classify_post_click_result", lambda **k: ("navigation", {}))
    monkeypatch.setattr(collection_flow, "expand_overlay", lambda **k: called.__setitem__("expand", 1))
    monkeypatch.setattr(collection_flow, "realign_focus_after_overlay", lambda **k: called.__setitem__("realign", 1))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=1), [], "o.xlsx", "out")

    assert called == {"expand": 0, "realign": 0}


def test_collect_tab_rows_unchanged_classification_skips_overlay_routine(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    called = {"expand": 0, "realign": 0}

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("f", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (True, "matched_global_candidates"))
    monkeypatch.setattr(collection_flow, "classify_post_click_result", lambda **k: ("unchanged", {}))
    monkeypatch.setattr(collection_flow, "expand_overlay", lambda **k: called.__setitem__("expand", 1))
    monkeypatch.setattr(collection_flow, "realign_focus_after_overlay", lambda **k: called.__setitem__("realign", 1))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=1), [], "o.xlsx", "out")

    assert called == {"expand": 0, "realign": 0}


def test_collect_tab_rows_global_nav_start_gate_abort_on_non_bottom_focus(monkeypatch):
    client = DummyClient([_anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/home_button"},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/home_button"},
    ]

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    rows = collection_flow.collect_tab_rows(
        client=client,
        dev="SERIAL",
        tab_cfg=_global_nav_tab_cfg(),
        all_rows=[],
        output_path="out.xlsx",
        output_base_dir="out",
    )

    assert rows[-1]["status"] == "TAB_OPEN_FAILED"
    assert rows[-1]["stop_reason"] == "global_nav_start_gate_failed"
    assert len(client.collect_focus_step_calls) == 0
    assert len(client.select_calls) == 1


def test_collect_tab_rows_global_nav_start_gate_allows_bottom_focus(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    client.focus_sequence = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites"},
    ]

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (
            True,
            0,
            0,
            "repeat_no_progress",
            ("", "", ""),
            {"terminal": False, "same_like_count": 2, "no_progress": True, "reason": "repeat_no_progress"},
        ),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _global_nav_tab_cfg(max_steps=1), [], "o.xlsx", "out")

    assert rows[0]["status"] == "ANCHOR"
    assert len(client.select_calls) == 0


def test_recover_to_start_state_skips_when_already_target(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    client.dump_tree_sequence = [
        [
            {
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites",
                "contentDescription": "Home selected",
                "selected": True,
            }
        ]
    ]

    ok = collection_flow.recover_to_start_state(client, "SERIAL", {"recovery": {"max_back_count": 2}})

    assert ok is True
    assert client.back_calls == 0


def test_recover_to_start_state_performs_back_then_select(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([])
    client.dump_tree_sequence = [
        [],
        [
            {
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites",
                "contentDescription": "Home",
                "selected": False,
            }
        ],
        [
            {
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites",
                "contentDescription": "Home selected",
                "selected": True,
            }
        ],
    ]

    ok = collection_flow.recover_to_start_state(client, "SERIAL", {"recovery": {"max_back_count": 2}})

    assert ok is True
    assert client.back_calls == 1
    assert len(client.select_calls) == 1


def test_recover_to_start_state_bottom_tab_soft_success_after_select(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([])
    client.dump_tree_sequence = [
        [],
        [
            {
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites",
                "contentDescription": "Home",
                "selected": False,
            }
        ],
        [
            {
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites",
                "contentDescription": "Home",
                "selected": False,
            }
        ],
        [
            {
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites",
                "contentDescription": "Home",
                "selected": False,
            }
        ],
    ]

    ok = collection_flow.recover_to_start_state(client, "SERIAL", {"recovery": {"max_back_count": 3}})

    assert ok is True
    assert client.back_calls == 1
    assert len(client.select_calls) == 1


def test_recover_to_start_state_fallback_select_after_resource_failure(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([])
    client.dump_tree_sequence = [
        [],
        [
            {
                "viewIdResourceName": "other:id/not_favorites",
                "contentDescription": "Home",
                "selected": False,
            }
        ],
        [
            {
                "viewIdResourceName": "other:id/not_favorites",
                "contentDescription": "Home selected",
                "selected": True,
            }
        ],
    ]

    def _select(**kwargs):
        client.select_calls.append(kwargs)
        return kwargs.get("type_") == "a"

    client.select = _select

    ok = collection_flow.recover_to_start_state(client, "SERIAL", {"recovery": {"max_back_count": 3}})

    assert ok is True
    assert client.back_calls == 1
    assert len(client.select_calls) == 2
    assert client.select_calls[0]["type_"] == "r"
    assert client.select_calls[1]["type_"] == "a"


def test_recover_to_start_state_failure_returns_false(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([])
    client.dump_tree_sequence = [[], [], []]

    ok = collection_flow.recover_to_start_state(client, "SERIAL", {"recovery": {"max_back_count": 2}})

    assert ok is False
    assert client.back_calls == 2


def test_collect_tab_rows_previous_step_not_updated_after_stop_break(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1), _main_row(2)])
    previous_steps = []

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])

    def _detect(**kwargs):
        previous_steps.append(kwargs.get("previous_step", {}).get("step_index"))
        return [], []

    monkeypatch.setattr(collection_flow, "detect_step_mismatch", _detect)
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (True, 0, 0, "repeat_no_progress", ("", "", ""), {"terminal": False, "same_like_count": 2, "no_progress": True, "reason": "repeat_no_progress"}))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=2), [], "o.xlsx", "out")

    assert previous_steps == [0]


def test_collect_tab_rows_global_nav_only_skips_non_global_nav_rows(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1), _main_row(2)])
    client.focus_sequence = [{"viewIdResourceName": "id.2"}]
    tab_cfg = {
        **_base_tab_cfg(max_steps=2),
        "scenario_type": "global_nav",
        "global_nav": {
            "resource_ids": ["id.2"],
            "labels": ["item2"],
            "selected_pattern": "",
            "region_hint": "auto",
        },
    }

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("f", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (True, "matched_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", tab_cfg, [], "o.xlsx", "out")

    assert [row["step_index"] for row in rows] == [0, 2]
    assert rows[1]["is_global_nav"] is True


def test_collect_tab_rows_global_nav_only_disables_overlay(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    client.focus_sequence = [{"viewIdResourceName": "id.1"}]
    called = {"is_overlay_candidate": 0}
    tab_cfg = {
        **_base_tab_cfg(max_steps=1),
        "scenario_type": "global_nav",
        "global_nav": {"resource_ids": ["id.1"], "labels": ["item1"]},
    }

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("f", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)

    def _overlay_candidate(*args, **kwargs):
        called["is_overlay_candidate"] += 1
        return True, "matched_global_candidates"

    monkeypatch.setattr(collection_flow, "is_overlay_candidate", _overlay_candidate)

    collection_flow.collect_tab_rows(client, "SERIAL", tab_cfg, [], "o.xlsx", "out")

    assert called["is_overlay_candidate"] == 0


def test_open_scenario_pre_navigation_success(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
        "pre_navigation_retry_count": 2,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert client.reset_focus_history_calls == 1
    assert len(client.select_calls) == 1


def test_open_scenario_pre_navigation_failure(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = DummyClient([])
    client.select = lambda **kwargs: False
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
        "pre_navigation_retry_count": 2,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False


def test_open_scenario_pre_navigation_retry_then_success(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = DummyClient([_anchor_row()])
    attempts = {"count": 0}

    def _select(**kwargs):
        attempts["count"] += 1
        return attempts["count"] == 2

    client.select = _select
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
        "pre_navigation_retry_count": 2,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert attempts["count"] == 2


def test_open_scenario_pre_navigation_logs_reason_on_retry_and_failure(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([])

    def _select(**kwargs):
        client.last_target_action_result = {"reason": "ACTION_CLICK failed (resourceId=id.settings)"}
        return False

    client.select = _select
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
        "pre_navigation_retry_count": 2,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    assert any("retry step=1 attempt=1/2 reason='ACTION_CLICK failed (resourceId=id.settings)'" in line for line in logs)
    assert any("failed reason='action_failed' detail='ACTION_CLICK failed (resourceId=id.settings)' step=1" in line for line in logs)


def test_open_scenario_pre_navigation_logs_reason_on_success(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])

    def _select(**kwargs):
        client.last_target_action_result = {"reason": "moved_to_target"}
        return True

    client.select = _select
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
        "pre_navigation_retry_count": 2,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert any("success step=1 reason='moved_to_target'" in line for line in logs)


def test_open_scenario_pre_navigation_touch_bounds_center_success(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "touch_bounds_center", "target": "com.test:id/settings_button", "type": "r"}],
        "pre_navigation_retry_count": 2,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.touch_bounds_center_calls) == 1
    assert client.touch_bounds_center_calls[0]["type_"] == "r"


def test_open_scenario_pre_navigation_scroll_touch_success(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "scrollTouch", "target": "(?i).*food.*", "type": "a"}],
        "pre_navigation_retry_count": 1,
        "pre_navigation_wait_seconds": 0.1,
        "anchor": {"target": "anchor", "type": "t"},
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.scroll_touch_calls) == 1
    assert client.scroll_touch_calls[0]["name"] == "(?i).*food.*"
    assert client.scroll_touch_calls[0]["type_"] == "a"


def test_open_scenario_pre_navigation_scroll_touch_lowercase_success(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "scrolltouch", "target": "(?i).*cooking.*", "type": "a"}],
        "pre_navigation_retry_count": 1,
        "pre_navigation_wait_seconds": 0.1,
        "anchor": {"target": "anchor", "type": "t"},
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.scroll_touch_calls) == 1
    assert client.scroll_touch_calls[0]["name"] == "(?i).*cooking.*"


def test_open_scenario_pre_navigation_scroll_touch_invokes_scroll_to_top(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "scrollTouch", "target": "(?i).*food.*", "type": "a"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.scroll_to_top_calls) == 1
    assert len(client.scroll_touch_calls) == 1
    assert any("before scrolltouch, scroll_to_top invoked" in line for line in logs)
    assert any("scroll_to_top result=" in line for line in logs)


def test_open_scenario_pre_navigation_scroll_touch_continues_when_scroll_to_top_fails(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    client = DummyClient([_anchor_row()])

    def _broken_scroll_to_top(**kwargs):
        raise RuntimeError("boom")

    client.scroll_to_top = _broken_scroll_to_top
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "scrollTouch", "target": "(?i).*food.*", "type": "a"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.scroll_touch_calls) == 1
    assert any("scroll_to_top failed reason='boom'" in line for line in logs)


def test_open_scenario_pre_navigation_scroll_touch_failure(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    client = DummyClient([_anchor_row()])

    def _scroll_touch(**kwargs):
        client.scroll_touch_calls.append(kwargs)
        client.last_target_action_result = {"reason": "target_not_found"}
        return False

    client.scrollTouch = _scroll_touch
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "scrollTouch", "target": "(?i).*pet care.*", "type": "a"}],
        "pre_navigation_retry_count": 1,
        "anchor": {"target": "anchor", "type": "t"},
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    assert len(client.scroll_touch_calls) == 1
    assert any("[SCENARIO][pre_nav][scrolltouch][debug]" in line for line in logs)
    assert any("[SCENARIO][pre_nav][scrolltouch][inspect]" in line for line in logs)
    assert any("exact_match_count=" in line for line in logs)
    assert any("rejections='" in line for line in logs)
    assert any("fallback='helper_scrollTouch'" in line for line in logs)


def test_run_pre_navigation_scrolltouch_dispatch_false_but_transition_success_logs_success(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    monkeypatch.setattr(
        collection_flow,
        "_select_visible_plugin_candidate",
        lambda **kwargs: (
            {"text": "Energy", "clickable": True, "viewIdResourceName": "com.test:id/preInstalledServiceCard"},
            "candidate_found",
            {"candidate_committed": True, "visible_candidate_count": 1, "partial_match_count": 1},
            {},
        ),
    )
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **kwargs: (True, "screen_text"))

    client = DummyClient([_anchor_row()])
    client.tap_bounds_center_adb = lambda **kwargs: False
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "scrollTouch", "target": "(?i).*energy.*", "type": "a"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow._run_pre_navigation_steps(client, "SERIAL", tab_cfg)

    assert ok is True
    assert any("candidate_click_dispatch_result success=false" in line for line in logs)
    assert any("post_click_transition same_screen=false" in line for line in logs)
    assert any("candidate_click_result=success" in line for line in logs)
    assert not any("candidate_click_failed:dispatch_failed" in line for line in logs)


def test_run_pre_navigation_scrolltouch_dispatch_false_and_same_screen_logs_dispatch_failed(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    monkeypatch.setattr(
        collection_flow,
        "_select_visible_plugin_candidate",
        lambda **kwargs: (
            {"text": "Energy", "clickable": True, "viewIdResourceName": "com.test:id/preInstalledServiceCard"},
            "candidate_found",
            {"candidate_committed": True, "visible_candidate_count": 1, "partial_match_count": 1},
            {},
        ),
    )
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **kwargs: (False, "same_screen"))

    client = DummyClient([])
    client.tap_bounds_center_adb = lambda **kwargs: False
    client.scrollTouch = lambda **kwargs: False
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "scrollTouch", "target": "(?i).*energy.*", "type": "a"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow._run_pre_navigation_steps(client, "SERIAL", tab_cfg)

    assert ok is False
    assert any("candidate_click_dispatch_result success=false" in line for line in logs)
    assert any("post_click_transition same_screen=true" in line for line in logs)
    assert any("candidate_click_failed:dispatch_failed" in line for line in logs)


def test_open_scenario_pre_navigation_scroll_touch_plugin_uses_cumulative_downward_search(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    page1 = [
        {
            "text": "Life root",
            "boundsInScreen": "0,0,1080,2000",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Food",
                    "boundsInScreen": "100,500,980,760",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                }
            ],
        }
    ]
    page2 = [
        {
            "text": "Life root",
            "boundsInScreen": "0,0,1080,2000",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Energy. Monitor and control your home energy usage.",
                    "boundsInScreen": "100,700,980,980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "children": [
                        {
                            "text": "Energy",
                            "boundsInScreen": "150,740,500,820",
                            "visibleToUser": True,
                        }
                    ],
                }
            ],
        }
    ]
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.dump_tree_sequence = [page1, page2]
    monkeypatch.setattr(collection_flow, "_verify_plugin_entry_root_state", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr(collection_flow, "_verify_scroll_top_state", lambda *args, **kwargs: (True, "life_root_marker_visible", page1))
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_energy_plugin",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [{"action": "scrollTouch", "target": "(?i).*energy.*", "type": "a"}],
        "pre_navigation_retry_count": 3,
        "max_scroll_search_steps": 4,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.scroll_to_top_calls) == 1
    assert len(client.scroll_calls) >= 1
    assert any("cumulative_mode=true" in line for line in logs)
    assert any("scroll_forward_and_retry_local_search" in line for line in logs)
    assert any("settle_wait_ms=250" in line for line in logs)


def test_select_visible_plugin_candidate_promotes_clickable_card_from_descendant_label():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": False,
            "children": [
                {
                    "boundsInScreen": "100,620,980,980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "children": [
                        {
                            "text": "Air Care",
                            "boundsInScreen": "140,680,520,760",
                            "visibleToUser": False,
                            "viewIdResourceName": "com.test:id/tvHeaderTitle",
                        }
                    ],
                }
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i).*air\s*care.*",
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert stats.get("visible_candidate_count", 0) >= 1
    assert stats.get("partial_match_count", 0) >= 1
    assert selected_meta.get("promoted_to", "").endswith("preInstalledServiceCard")
    assert any("reason='survive_candidate'" in sample for sample in stats.get("inspect_samples", []))


def test_select_visible_plugin_candidate_collects_rejection_reasons_and_pre_candidate_samples():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": False,
            "children": [
                {
                    "text": "Air Care",
                    "boundsInScreen": "100,600,980,920",
                    "visibleToUser": False,
                    "viewIdResourceName": "com.test:id/titleHidden",
                },
                {
                    "text": "Container without bounds",
                    "boundsInScreen": "",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "children": [
                        {
                            "text": "Air Care",
                            "boundsInScreen": "160,1040,400,1120",
                            "visibleToUser": True,
                            "viewIdResourceName": "com.test:id/tvHeaderTitle",
                        },
                    ],
                },
            ],
        }
    ]

    selected, reason, stats, _ = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i).*air\s*care.*",
    )

    assert selected is None
    assert reason == "no_visible_candidate"
    assert stats.get("rejection_counts", {}).get("invisible_node", 0) >= 1
    assert stats.get("rejection_counts", {}).get("no_click_node_bounds", 0) >= 1
    assert any("reason='invisible_node'" in sample for sample in stats.get("inspect_samples", []))
    assert any("promotion_fail:no_click_node_bounds" in sample for sample in stats.get("pre_candidate_fail_samples", []))


def test_select_visible_plugin_candidate_promotes_non_clickable_description_to_overlapping_card():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": False,
            "children": [
                {
                    "text": "맞춤형 Air Care 서비스를 이용해보세요.",
                    "boundsInScreen": "180,760,920,860",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvCardDescription",
                },
                {
                    "boundsInScreen": "100,620,980,980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "className": "android.widget.FrameLayout",
                    "children": [
                        {
                            "text": "온도 관리",
                            "boundsInScreen": "150,680,560,750",
                            "visibleToUser": True,
                            "viewIdResourceName": "com.test:id/tvHeaderTitle",
                        }
                    ],
                },
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i).*air\s*care.*",
        scenario_id="life_air_care_plugin",
        entry_spec={
            "title_patterns": [r"(?i).*air\s*care.*"],
            "description_patterns": [r"(?i)(air\s*quality|air\s*comfort)"],
            "allow_description_match": True,
        },
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert stats.get("partial_match_count", 0) >= 1
    assert selected_meta.get("promoted_container") is True
    assert selected_meta.get("promoted_to", "").endswith("preInstalledServiceCard")
    assert any("matched_text_node='com.test:id/tvCardDescription'" in sample for sample in stats.get("inspect_samples", []))


def test_select_visible_plugin_candidate_life_air_care_description_keyword_promotes_card_container():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": False,
            "children": [
                {
                    "text": "Monitor air quality and air comfort in each room of your home.",
                    "boundsInScreen": "170,760,930,850",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                },
                {
                    "boundsInScreen": "100,620,980,980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "className": "android.widget.FrameLayout",
                },
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i).*air\s*care.*",
        scenario_id="life_air_care_plugin",
        entry_spec={
            "title_patterns": [r"(?i).*air\s*care.*"],
            "description_patterns": [r"(?i)(air\s*quality|air\s*comfort)"],
            "allow_description_match": True,
        },
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert stats.get("visible_candidate_count", 0) >= 1
    assert stats.get("partial_match_count", 0) >= 1
    assert selected_meta.get("promoted_container") is True
    assert selected_meta.get("promotion_reason") in {
        "helper_containment_container",
        "helper_nearby_container",
        "helper_nearest_actionable_ancestor",
    }
    assert selected_meta.get("promoted_from", "").endswith("tvHeaderTitle")
    assert selected_meta.get("promoted_to", "").endswith("preInstalledServiceCard")


def test_select_visible_plugin_candidate_description_keyword_is_scoped_to_life_air_care():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Monitor air quality and air comfort in each room of your home.",
                    "boundsInScreen": "170,760,930,850",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                },
                {
                    "boundsInScreen": "100,620,980,980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "className": "android.widget.FrameLayout",
                },
            ],
        }
    ]

    selected, reason, stats, _ = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i).*air\s*care.*",
        scenario_id="life_energy_plugin",
    )

    assert selected is None
    assert reason == "no_visible_candidate"
    assert stats.get("rejection_counts", {}).get("filtered_before_candidate", 0) >= 1


def test_select_visible_plugin_candidate_rejects_non_actionable_match_without_promotion():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Air Care",
                    "boundsInScreen": "170,760,930,850",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                }
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i).*air\s*care.*",
        scenario_id="life_air_care_plugin",
        entry_spec={
            "title_patterns": [r"(?i).*air\s*care.*"],
            "description_patterns": [r"(?i)(air\s*quality|air\s*comfort)"],
            "allow_description_match": True,
        },
    )

    assert selected is None
    assert reason == "no_visible_candidate"
    assert selected_meta.get("promoted_container") is False
    assert stats.get("rejection_counts", {}).get("non_actionable_without_promotion", 0) >= 1
    assert any(
        "reason='non_actionable_without_promotion'" in sample for sample in stats.get("inspect_samples", [])
    )
    assert any(
        "actionability_fail:non_actionable_without_promotion" in sample
        for sample in stats.get("pre_candidate_fail_samples", [])
    )


def test_select_visible_plugin_candidate_promotes_to_effective_clickable_card_for_air_care():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Monitor air quality and air comfort in each room of your home.",
                    "boundsInScreen": "180,760,920,860",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                },
                {
                    "boundsInScreen": "100,620,980,980",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": True,
                    "viewIdResourceName": "com.test:id/pluginCardContainer",
                    "className": "android.widget.LinearLayout",
                },
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i)(^smart\s*air\s*care$|^air\s*care$|air\s*care\.|\baircare\b|에어\s*케어)",
        scenario_id="life_air_care_plugin",
        entry_spec={
            "title_patterns": [r"(?i).*air\s*care.*"],
            "description_patterns": [r"(?i)(air\s*quality|air\s*comfort)"],
            "allow_description_match": True,
        },
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert selected_meta.get("promoted_container") is True
    assert selected_meta.get("promotion_source") == "helper"
    assert selected_meta.get("promotion_attempted") is True
    assert selected_meta.get("promoted_to", "").endswith("pluginCardContainer")
    assert stats.get("rejection_counts", {}).get("non_actionable_without_promotion", 0) == 0


def test_select_visible_plugin_candidate_xml_fallback_promotes_clickable_container():
    helper_nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Monitor air quality and air comfort in each room of your home.",
                    "boundsInScreen": "180,760,920,860",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                }
            ],
        }
    ]
    xml_nodes = [
        {
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "boundsInScreen": "100,620,980,980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "className": "android.widget.FrameLayout",
                }
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=helper_nodes,
        target=r"(?i).*air\s*care.*",
        scenario_id="life_air_care_plugin",
        xml_nodes=xml_nodes,
        entry_spec={
            "title_patterns": [r"(?i).*air\s*care.*"],
            "description_patterns": [r"(?i)(air\s*quality|air\s*comfort)"],
            "allow_description_match": True,
        },
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert selected_meta.get("promoted_container") is True
    assert selected_meta.get("promotion_source") == "xml_live"
    assert selected_meta.get("promotion_attempted") is True
    assert selected_meta.get("promoted_to", "").endswith("preInstalledServiceCard")
    assert stats.get("rejection_counts", {}).get("non_actionable_without_promotion", 0) == 0


def test_select_visible_plugin_candidate_accepts_actionable_viewgroup_container_with_food_title_descendant():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": True,
            "children": [
                {
                    "boundsInScreen": "120,620,960,980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/serviceCardContainer",
                    "className": "android.view.ViewGroup",
                    "children": [
                        {
                            "text": "SmartThings Cooking",
                            "boundsInScreen": "180,700,840,760",
                            "visibleToUser": True,
                            "clickable": False,
                            "focusable": False,
                            "viewIdResourceName": "com.test:id/tvHeaderTitle",
                            "className": "android.widget.TextView",
                        }
                    ],
                }
            ],
        }
    ]

    selected, reason, stats, _ = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i)(^food$|food\.|smart\s*things\s*cooking|\bcooking\b)",
        scenario_id="life_food_plugin",
        entry_spec={
            "title_patterns": [r"(?i)(^food$|food\.|smart\s*things\s*cooking|\bcooking\b)"],
            "description_patterns": [],
            "resource_patterns": [r"(?i)(servicecard|card|container|food|cook)"],
            "allow_description_match": False,
        },
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert stats.get("visible_candidate_count", 0) >= 1


def test_select_visible_plugin_candidate_card_entry_spec_description_match_promotes_energy_xml_container():
    helper_nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Add an appliance to start measuring energy usage.",
                    "boundsInScreen": "180,760,920,860",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                }
            ],
        }
    ]
    xml_nodes = [
        {
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "boundsInScreen": "100,620,980,980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "className": "android.widget.FrameLayout",
                }
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=helper_nodes,
        target=r"(?i)(^energy$|energy\.|\bsmart\s*energy\b|\benergy\b)",
        scenario_id="life_energy_plugin",
        xml_nodes=xml_nodes,
        entry_spec={
            "title_patterns": [r"(?i)(^energy$|energy\.|\bsmart\s*energy\b|\benergy\b)"],
            "description_patterns": [r"(?i)(energy\s*usage|measuring\s*energy\s*usage|appliance)"],
            "allow_description_match": True,
        },
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert selected_meta.get("promotion_source") == "xml_live"
    assert stats.get("partial_match_count", 0) >= 1


def test_run_pre_navigation_steps_forces_xml_live_fallback_when_visible_candidate_count_zero(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = DummyClient([_anchor_row()])
    client.scrollTouch = lambda **kwargs: False
    client.dump_tree_sequence = [
        [
            {
                "text": "Life",
                "boundsInScreen": "0,0,1080,2200",
                "visibleToUser": True,
                "children": [],
            }
        ]
    ]

    select_calls = {"count": 0}

    def _select_candidate(**kwargs):
        select_calls["count"] += 1
        if select_calls["count"] == 1:
            return None, "no_visible_candidate", {"visible_candidate_count": 0, "rejection_counts": {}}, {}
        return None, "still_no_visible_candidate", {"visible_candidate_count": 0, "rejection_counts": {}}, {}

    xml_calls = {"count": 0}

    def _load_xml(**kwargs):
        xml_calls["count"] += 1
        return (
            [
                {
                    "visibleToUser": True,
                    "boundsInScreen": "0,0,1080,2200",
                    "children": [],
                }
            ],
            "ok",
        )

    monkeypatch.setattr(collection_flow, "_select_visible_plugin_candidate", _select_candidate)
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", _load_xml)

    ok = collection_flow._run_pre_navigation_steps(
        client=client,
        dev="SERIAL",
        tab_cfg={
            "scenario_id": "life_food_plugin",
            "screen_context_mode": "new_screen",
            "stabilization_mode": "anchor_only",
            "entry_type": "card",
            "max_scroll_search_steps": 1,
            "pre_navigation_retry_count": 1,
            "pre_navigation_wait_seconds": 0.1,
            "pre_navigation": [{"action": "scrolltouch", "target": "(?i).*food.*", "type": "a"}],
            "anchor": {"target": "anchor", "type": "t"},
        },
    )

    assert ok is False
    assert select_calls["count"] >= 2
    assert xml_calls["count"] == 1
    assert any("xml_fallback_attempted=true" in line for line in logs)


def test_select_visible_plugin_candidate_card_entry_spec_description_match_promotes_pet_care_xml_container():
    helper_nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": True,
            "children": [
                {
                    "text": "You can take care of your pet with devices connected to SmartThings while you're away from home. Start by entering your pet's profile.",
                    "boundsInScreen": "180,760,920,860",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                }
            ],
        }
    ]
    xml_nodes = [
        {
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "boundsInScreen": "100,620,980,980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "className": "android.widget.FrameLayout",
                }
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=helper_nodes,
        target=r"(?i)(^pet\s*care$|.*pet\s*care.*|.*펫\s*케어.*)",
        scenario_id="life_pet_care_plugin",
        xml_nodes=xml_nodes,
        entry_spec={
            "title_patterns": [r"(?i)^pet\s*care$", r"(?i).*pet\s*care.*", r"(?i).*펫\s*케어.*"],
            "description_patterns": [
                r"(?i).*take care of your pet.*",
                r"(?i).*connected to SmartThings.*",
                r"(?i).*entering your pet'?s profile.*",
            ],
            "allow_description_match": True,
        },
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert selected_meta.get("promotion_source") == "xml_live"
    assert stats.get("partial_match_count", 0) >= 1


def test_select_visible_plugin_candidate_xml_live_prefers_specific_small_candidate_over_oversized_wrapper():
    helper_nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2340",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Monitor air quality and air comfort in each room of your home.",
                    "boundsInScreen": "120,1760,980,1860",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                }
            ],
        }
    ]
    xml_nodes = [
        {
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2340",
            "children": [
                {
                    "boundsInScreen": "42,1752,1038,2316",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "",
                    "className": "android.widget.RelativeLayout",
                },
                {
                    "boundsInScreen": "96,1728,984,2088",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/preInstalledServiceCard",
                    "className": "android.widget.FrameLayout",
                },
            ],
        }
    ]

    selected, reason, _, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=helper_nodes,
        target=r"(?i).*air\s*care.*",
        scenario_id="life_air_care_plugin",
        xml_nodes=xml_nodes,
        entry_spec={
            "title_patterns": [r"(?i).*air\s*care.*"],
            "description_patterns": [r"(?i)(air\s*quality|air\s*comfort)"],
            "allow_description_match": True,
        },
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert str(selected.get("viewIdResourceName", "")).endswith("preInstalledServiceCard")
    assert selected_meta.get("promotion_source") == "xml_live"


def test_select_visible_plugin_candidate_xml_live_oversized_generic_wrapper_is_demoted():
    helper_nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2340",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Monitor air quality and air comfort in each room of your home.",
                    "boundsInScreen": "120,1760,980,1860",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                }
            ],
        }
    ]
    xml_nodes = [
        {
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2340",
            "children": [
                {
                    "boundsInScreen": "0,1200,1080,2340",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "",
                    "className": "android.widget.RelativeLayout",
                }
            ],
        }
    ]

    selected, reason, _, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=helper_nodes,
        target=r"(?i).*air\s*care.*",
        scenario_id="life_air_care_plugin",
        xml_nodes=xml_nodes,
        entry_spec={
            "title_patterns": [r"(?i).*air\s*care.*"],
            "description_patterns": [r"(?i)(air\s*quality|air\s*comfort)"],
            "allow_description_match": True,
        },
    )

    assert selected is None
    assert reason == "no_visible_candidate"
    assert selected_meta.get("promoted_container") is False


def test_select_visible_plugin_candidate_xml_live_generic_wrapper_uses_refined_tap_strategy():
    helper_nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2340",
            "visibleToUser": True,
            "children": [
                {
                    "text": "Monitor air quality and air comfort in each room of your home.",
                    "boundsInScreen": "180,1780,920,1880",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                }
            ],
        }
    ]
    xml_nodes = [
        {
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2340",
            "children": [
                {
                    "boundsInScreen": "42,1700,1038,2300",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "",
                    "className": "android.widget.RelativeLayout",
                }
            ],
        }
    ]

    selected, _, _, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=helper_nodes,
        target=r"(?i).*air\s*care.*",
        scenario_id="life_air_care_plugin",
        xml_nodes=xml_nodes,
        entry_spec={
            "title_patterns": [r"(?i).*air\s*care.*"],
            "description_patterns": [r"(?i)(air\s*quality|air\s*comfort)"],
            "allow_description_match": True,
        },
    )

    assert selected is not None
    assert selected_meta.get("promotion_source") == "xml_live"
    assert selected_meta.get("tap_strategy") in {"text_center", "refined_body_point"}


def test_select_visible_plugin_candidate_rejects_oversized_root_during_promotion():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": True,
            "children": [
                {
                    "boundsInScreen": "0,0,1080,2200",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "android:id/content",
                    "className": "android.widget.FrameLayout",
                },
                {
                    "text": "Monitor air quality and air comfort in each room of your home.",
                    "boundsInScreen": "180,760,920,860",
                    "visibleToUser": True,
                    "clickable": False,
                    "focusable": False,
                    "viewIdResourceName": "com.test:id/tvHeaderTitle",
                    "className": "android.widget.TextView",
                },
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i).*air\s*care.*",
        scenario_id="life_air_care_plugin",
        entry_spec={
            "title_patterns": [r"(?i).*air\s*care.*"],
            "description_patterns": [r"(?i)(air\s*quality|air\s*comfort)"],
            "allow_description_match": True,
        },
    )

    assert selected is None
    assert reason == "no_visible_candidate"
    assert selected_meta.get("promoted_container") is False
    assert stats.get("rejection_counts", {}).get("non_actionable_without_promotion", 0) >= 1
    assert "rejected_large_container_count" in stats


def test_select_visible_plugin_candidate_promotion_skips_list_like_container_and_keeps_card_parent():
    nodes = [
        {
            "text": "Life",
            "boundsInScreen": "0,0,1080,2200",
            "visibleToUser": True,
            "children": [
                {
                    "boundsInScreen": "30,420,1050,1980",
                    "visibleToUser": True,
                    "clickable": True,
                    "focusable": True,
                    "viewIdResourceName": "com.test:id/recycler_view",
                    "className": "androidx.recyclerview.widget.RecyclerView",
                    "children": [
                        {
                            "boundsInScreen": "90,700,990,980",
                            "visibleToUser": True,
                            "clickable": True,
                            "focusable": True,
                            "viewIdResourceName": "com.test:id/pluginCardContainer",
                            "className": "android.widget.FrameLayout",
                            "children": [
                                {
                                    "boundsInScreen": "120,730,960,960",
                                    "visibleToUser": True,
                                    "clickable": False,
                                    "focusable": False,
                                    "viewIdResourceName": "com.test:id/pluginBody",
                                    "className": "android.widget.LinearLayout",
                                    "children": [
                                        {
                                            "text": "SmartThings Cooking",
                                            "boundsInScreen": "160,760,880,830",
                                            "visibleToUser": True,
                                            "clickable": False,
                                            "focusable": False,
                                            "viewIdResourceName": "com.test:id/tvHeaderTitle",
                                            "className": "android.widget.TextView",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    selected, reason, stats, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i)(^food$|food\.|smart\s*things\s*cooking|\bcooking\b)",
        scenario_id="life_food_plugin",
        entry_spec={
            "title_patterns": [r"(?i)(^food$|food\.|smart\s*things\s*cooking|\bcooking\b)"],
            "description_patterns": [],
            "allow_description_match": False,
        },
    )

    assert selected is not None
    assert "candidate_count=" in reason
    assert selected_meta.get("selected_container_view_id", "").endswith("pluginCardContainer")
    assert "recycler_view" not in selected_meta.get("selected_container_view_id", "")
    assert stats.get("rejected_list_like_container_count", 0) >= 1


def test_confirm_click_focused_transition_life_energy_rejects_weak_signal(monkeypatch):
    client = DummyClient([])
    baseline_nodes = [
        {"text": "Energy", "viewIdResourceName": "id.card.energy"},
    ]
    current_nodes = [
        {"text": "Navigate up", "contentDescription": "Navigate up", "viewIdResourceName": ""},
    ]
    client.dump_tree_sequence = [current_nodes, current_nodes, current_nodes]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_energy_plugin",
        "anchor": {"text_regex": "(?i).*navigate\\s*up.*"},
        "context_verify": {"type": "screen_text", "text_regex": "(?i).*energy.*"},
    }

    ok, reason = collection_flow._confirm_click_focused_transition(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        transition_fast_path=False,
        baseline_nodes=baseline_nodes,
    )

    assert ok is False
    assert reason == "weak_transition_signal_only"


def test_confirm_click_focused_transition_life_air_care_requires_plugin_specific_verify(monkeypatch):
    client = DummyClient([])
    baseline_nodes = [{"text": "Air Care", "viewIdResourceName": "id.card.aircare"}]
    current_nodes = [
        {"text": "Navigate up", "contentDescription": "Navigate up", "viewIdResourceName": ""},
    ]
    client.dump_tree_sequence = [current_nodes, current_nodes, current_nodes]
    client.focus_sequence = [{"text": "Navigate up", "contentDescription": "Navigate up", "viewIdResourceName": ""}]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_air_care_plugin",
        "anchor": {"text_regex": "(?i).*navigate\\s*up.*"},
    }

    ok, reason = collection_flow._confirm_click_focused_transition(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        transition_fast_path=False,
        baseline_nodes=baseline_nodes,
    )

    assert ok is False
    assert reason == "air_care_verify_missing"


def test_open_scenario_life_energy_guard_rejects_family_care_entry(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": False, "reason": "verified_without_select", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [{"text": "Navigate up", "contentDescription": "Navigate up", "viewIdResourceName": ""}]
    client.dump_tree_sequence = [[{"text": "Family Care"}, {"text": "Add family member"}]]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_energy_plugin",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    assert any("[SCENARIO][life_energy_guard] failed" in line for line in logs)


def test_open_scenario_life_energy_guard_recheck_recovers_energy_entry(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": False, "reason": "verified_without_select", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [{"text": "Navigate up", "contentDescription": "Navigate up", "viewIdResourceName": ""}]
    client.dump_tree_sequence = [
        [{"text": "Navigate up"}],
        [{"text": "Energy score"}, {"text": "Battery usage"}],
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_energy_plugin",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert any("[SCENARIO][life_energy_guard] recheck" in line for line in logs)
    assert not any("[SCENARIO][life_energy_guard] failed" in line for line in logs)


def test_open_scenario_direct_select_blocks_home_button_by_false_success_guard(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True, "fallback_candidate_used": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/home_button", "text": "Home"},
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_pet_care_plugin",
        "entry_type": "direct_select",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "context_verify": {"type": "focused_anchor", "text_regex": "(?i).*pet\\s*care.*"},
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "false_success_guard"


def test_open_scenario_air_card_rejects_list_screen_focus_even_with_transition_and_fallback(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {
            "ok": True,
            "selected": True,
            "reason": "selected_and_verified",
            "matched": True,
            "fallback_candidate_used": True,
            "start_candidate_source": "fallback_top_level",
        },
    )
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    def _pre_nav_success(**kwargs):
        client = kwargs["client"]
        setattr(client, "last_post_click_transition_same_screen", False)
        setattr(client, "last_post_click_transition_signal", "air_care_verify")
        return True

    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _pre_nav_success)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(message))
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/home_button", "text": "Home"},
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_air_care_plugin",
        "entry_type": "card",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "false_success_guard"
    assert summary.get("entry_contract_detail") == "negative_post_open_focus"
    assert any("[ENTRY][air] rejected plugin entry due to list_screen_focus" in line for line in logs)


def test_open_scenario_air_card_keeps_false_success_guard_without_transition_verify(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {
            "ok": True,
            "selected": True,
            "reason": "selected_and_verified",
            "matched": True,
            "fallback_candidate_used": True,
            "start_candidate_source": "fallback_top_level",
        },
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/home_button", "text": "Home"},
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_air_care_plugin",
        "entry_type": "card",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "false_success_guard"


def test_open_scenario_direct_select_fails_when_post_open_verify_missing(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [{"viewIdResourceName": "com.example:id/content", "text": "Unknown screen"}]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_pet_care_plugin",
        "entry_type": "direct_select",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "verify_tokens": ["pet care", "smartthings pet care"],
        "context_verify": {"type": "focused_anchor", "text_regex": "(?i).*pet\\s*care.*"},
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "verify_failed"


def test_open_scenario_direct_select_recovers_with_visible_plugin_token(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {
            "ok": True,
            "selected": True,
            "reason": "selected_and_verified",
            "matched": True,
            "fallback_candidate_label": "Pet Care",
            "fallback_candidate_resource_id": "com.example:id/pet_card",
            "verify_row": {"visible_label": "Pet Care"},
        },
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "", "text": "Navigate up", "contentDescription": "Navigate up"},
        {"viewIdResourceName": "", "text": "Navigate up", "contentDescription": "Navigate up"},
    ]
    client.dump_tree_sequence = [
        [{"text": "Pet Care Dashboard", "viewIdResourceName": "com.example:id/title"}],
        [{"text": "SmartThings Pet Care", "viewIdResourceName": "com.example:id/title"}],
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_pet_care_plugin",
        "entry_type": "direct_select",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "verify_tokens": ["pet care", "smartthings pet care"],
        "context_verify": {"type": "focused_anchor", "text_regex": "(?i).*pet\\s*care.*"},
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "success_verified"


def test_open_scenario_direct_select_keeps_wrong_open_on_negative_verify_token(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [{"viewIdResourceName": "com.example:id/content", "text": "Unknown screen"}]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_pet_care_plugin",
        "entry_type": "direct_select",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "verify_tokens": ["pet care", "smartthings pet care"],
        "negative_verify_tokens": ["qr code", "home_button"],
        "context_verify": {"type": "focused_anchor", "text_regex": "(?i).*pet\\s*care.*"},
    }
    monkeypatch.setattr(collection_flow, "_collect_post_open_visible_text", lambda *_args, **_kwargs: "QR code Change location")

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "wrong_open"
    assert summary.get("entry_contract_detail") == "post_open_negative_verify_token"


def test_open_scenario_direct_select_transient_negative_verify_then_plugin_token_succeeds(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "com.example:id/content", "text": "Unknown screen"},
        {"viewIdResourceName": "com.example:id/pet_dashboard", "text": "SmartThings Pet Care"},
    ]
    visible_samples = iter(["Add More options", "SmartThings Pet Care Dashboard"])
    monkeypatch.setattr(
        collection_flow,
        "_collect_post_open_visible_text",
        lambda *_args, **_kwargs: next(visible_samples, "SmartThings Pet Care Dashboard"),
    )
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_pet_care_plugin",
        "entry_type": "direct_select",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "verify_tokens": ["pet care", "smartthings pet care"],
        "negative_verify_tokens": ["add", "more options", "qr code"],
        "context_verify": {"type": "focused_anchor", "text_regex": "(?i).*pet\\s*care.*"},
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "success_verified"


def test_open_scenario_card_entry_keeps_air_care_success(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": False, "reason": "verified_without_select", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [{"viewIdResourceName": "com.samsung.android.oneconnect:id/card", "text": "Air Care"}]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_air_care_plugin",
        "entry_type": "card",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "success_verified"


def test_open_scenario_card_entry_pet_care_uses_card_verify_flow(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": False, "reason": "verified_without_select", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [{"viewIdResourceName": "com.example:id/title", "text": "Pet Care"}]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_pet_care_plugin",
        "entry_type": "card",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "verify_tokens": ["pet care", "pet's profile"],
        "negative_verify_tokens": ["qr code", "change location", "home_button"],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_type") == "card"
    assert summary.get("entry_contract_reason") == "success_verified"


def test_open_scenario_card_entry_pre_nav_failure_reason_maps_no_match(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True, "matched": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    def _pre_nav_fail(**kwargs):
        client = kwargs["client"]
        setattr(client, "last_pre_nav_failure_reason", "no_local_match")
        return False

    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _pre_nav_fail)
    client = DummyClient([_anchor_row(), _anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_home_care_plugin",
        "entry_type": "card",
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "no_match"


def test_open_scenario_card_entry_pre_nav_failure_reason_maps_text_only_no_promotion(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True, "matched": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    def _pre_nav_fail(**kwargs):
        client = kwargs["client"]
        setattr(client, "last_pre_nav_failure_reason", "non_actionable_without_promotion")
        return False

    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _pre_nav_fail)
    client = DummyClient([_anchor_row(), _anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_energy_plugin",
        "entry_type": "card",
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "text_only_no_promotion"


def test_open_scenario_card_entry_verify_tokens_miss_maps_verify_failed(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [{"viewIdResourceName": "com.example:id/content", "text": "Unknown screen"}]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_energy_plugin",
        "entry_type": "card",
        "verify_tokens": ["energy", "energy usage"],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "verify_failed"


def test_open_scenario_card_entry_recovers_when_initial_focus_is_navigate_up(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    def _pre_nav_success(**kwargs):
        client = kwargs["client"]
        setattr(client, "last_post_click_transition_same_screen", False)
        setattr(client, "last_post_click_transition_signal", "air_care_verify")
        return True

    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _pre_nav_success)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "", "text": "Navigate up", "contentDescription": "Navigate up"},
        {"viewIdResourceName": "", "text": "Navigate up", "contentDescription": "Navigate up"},
        {"viewIdResourceName": "", "text": "Navigate up", "contentDescription": "Navigate up"},
    ]
    client.dump_tree_sequence = [
        [{"text": "Navigate up", "viewIdResourceName": ""}],
        [{"text": "Smart Air Care", "viewIdResourceName": "com.example:id/title"}],
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_air_care_plugin",
        "entry_type": "card",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "verify_tokens": ["air care"],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "success_verified"


def test_open_scenario_card_entry_energy_succeeds_with_smartthings_energy_verify_token(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "com.example:id/title", "text": "SmartThings Energy"},
        {"viewIdResourceName": "com.example:id/title", "text": "SmartThings Energy"},
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_energy_plugin",
        "entry_type": "card",
        "verify_tokens": ["smartthings energy"],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "success_verified"


def test_open_scenario_card_entry_energy_recheck_uses_visible_text_after_transition(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    def _pre_nav_success(**kwargs):
        client = kwargs["client"]
        setattr(client, "last_post_click_transition_same_screen", False)
        setattr(client, "last_post_click_transition_signal", "screen_text")
        return True

    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _pre_nav_success)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "", "text": "Navigate up", "contentDescription": "Navigate up"},
        {"viewIdResourceName": "", "text": "Navigate up", "contentDescription": "Navigate up"},
        {"viewIdResourceName": "com.example:id/title", "text": "SmartThings Energy"},
    ]
    client.dump_tree_sequence = [
        [{"text": "Navigate up", "viewIdResourceName": ""}],
        [{"text": "SmartThings Energy", "viewIdResourceName": "com.example:id/title"}],
        [{"text": "Energy usage", "viewIdResourceName": "com.example:id/subtitle"}],
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_energy_plugin",
        "entry_type": "card",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "verify_tokens": ["smartthings energy", "energy usage"],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "success_verified"


def test_open_scenario_card_entry_handles_special_state_with_back(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "com.example:id/title", "text": "SmartThings Home Care"},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_services", "text": "Life"},
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_home_care_plugin",
        "entry_type": "card",
        "verify_tokens": ["home care", "smart care", "home appliances"],
        "special_state_tokens": [
            "smartthings home care",
            "always manage your home appliances optimally",
            "home care constantly monitors devices",
        ],
        "special_state_cta_tokens": ["start"],
        "special_state_handling": "back_after_read",
    }
    monkeypatch.setattr(
        collection_flow,
        "_collect_post_open_visible_text",
        lambda *_args, **_kwargs: "SmartThings Home Care Always manage your home appliances optimally Start",
    )

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "special_state_handled"
    assert summary.get("special_state_detected") is True
    assert summary.get("special_state_kind") == "onboarding_or_empty_state"
    assert summary.get("special_state_handling") == "back_after_read"
    assert summary.get("special_state_back_status") == "back_sent_exit"
    assert client.back_calls == 1


def test_open_scenario_card_entry_handles_pet_care_onboarding_special_state(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [
        {"viewIdResourceName": "com.example:id/title", "text": "PetCare Service Plugin"},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_services", "text": "Life"},
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_pet_care_plugin",
        "entry_type": "card",
        "verify_tokens": ["pet care", "petcare service plugin", "pet profile"],
        "special_state_tokens": [
            "petcare service plugin",
            "care for your pet",
            "leaving your pet alone",
            "keep them safe and entertained",
        ],
        "special_state_cta_tokens": ["start"],
        "special_state_handling": "back_after_read",
        "special_state_intro_like_min_length": 70,
    }
    monkeypatch.setattr(
        collection_flow,
        "_collect_post_open_visible_text",
        lambda *_args, **_kwargs: (
            "PetCare Service Plugin Care for your pet, even when you're not home. "
            "Leaving your pet alone can be stressful. Keep them safe and entertained Start"
        ),
    )

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "special_state_handled"
    assert summary.get("entry_contract_detail") == "onboarding_back_exit"
    assert summary.get("special_state_detected") is True
    assert summary.get("special_state_kind") == "onboarding_or_empty_state"
    assert summary.get("special_state_handling") == "back_after_read"
    assert summary.get("special_state_back_status") == "back_sent_exit"
    assert client.back_calls == 1


def test_open_scenario_card_entry_does_not_misclassify_air_care_normal_content(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [{"viewIdResourceName": "com.example:id/title", "text": "Smart Air Care PM 2.5"}]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_air_care_plugin",
        "entry_type": "card",
        "verify_tokens": ["air care"],
        "special_state_tokens": ["smartthings home care", "home care constantly monitors devices"],
        "special_state_cta_tokens": ["start"],
        "special_state_handling": "back_after_read",
    }
    monkeypatch.setattr(collection_flow, "_collect_post_open_visible_text", lambda *_args, **_kwargs: "Smart Air Care PM 2.5")

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "success_verified"
    assert summary.get("special_state_detected") is not True
    assert client.back_calls == 0


def test_collect_tab_rows_adds_special_state_handled_row_and_skips_main_loop(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(collection_flow, "save_excel_with_perf", lambda *_args, **_kwargs: None)

    client = DummyClient([])
    client.focus_sequence = [
        {"viewIdResourceName": "com.example:id/title", "text": "SmartThings Home Care"},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_services", "text": "Life"},
    ]
    tab_cfg = {
        **_base_tab_cfg(max_steps=3),
        "scenario_id": "life_home_care_plugin",
        "entry_type": "card",
        "verify_tokens": ["home care", "smart care", "home appliances"],
        "special_state_tokens": [
            "smartthings home care",
            "always manage your home appliances optimally",
            "home care constantly monitors devices",
        ],
        "special_state_cta_tokens": ["start"],
        "special_state_handling": "back_after_read",
    }
    monkeypatch.setattr(
        collection_flow,
        "_collect_post_open_visible_text",
        lambda *_args, **_kwargs: "SmartThings Home Care Always manage your home appliances optimally Start",
    )

    rows = collection_flow.collect_tab_rows(client, "SERIAL", tab_cfg, [], "o.xlsx", "out")

    assert len(rows) == 1
    assert rows[0]["status"] == "SPECIAL_STATE_HANDLED"
    assert rows[0]["stop_reason"] == "special_state_handled"
    assert rows[0]["special_state_kind"] == "onboarding_or_empty_state"
    assert rows[0]["special_state_handling"] == "back_after_read"
    assert rows[0]["special_state_back_status"] == "back_sent_exit"
    assert client.back_calls == 1
    assert client.collect_focus_step_calls == []


def test_open_scenario_card_entry_does_not_misclassify_energy_normal_content(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {"ok": True, "selected": True, "reason": "selected_and_verified", "matched": True},
    )
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row(), _anchor_row()])
    client.focus_sequence = [{"viewIdResourceName": "com.example:id/title", "text": "SmartThings Energy usage"}]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_energy_plugin",
        "entry_type": "card",
        "verify_tokens": ["smartthings energy", "energy usage"],
        "special_state_tokens": ["smartthings home care", "home care constantly monitors devices"],
        "special_state_cta_tokens": ["start"],
        "special_state_handling": "back_after_read",
    }
    monkeypatch.setattr(collection_flow, "_collect_post_open_visible_text", lambda *_args, **_kwargs: "SmartThings Energy usage")

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "success_verified"
    assert summary.get("special_state_detected") is not True
    assert client.back_calls == 0


def test_open_scenario_pre_navigation_touch_bounds_center_bounds_unavailable_failure(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    client = DummyClient([])

    def _touch_bounds_center(**kwargs):
        client.last_target_action_result = {"reason": "Bounds unavailable"}
        return False

    client.touch_bounds_center = _touch_bounds_center
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "touch_bounds_center", "target": "com.test:id/settings_button", "type": "r"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)
    assert ok is False
    assert any("failed reason='action_failed' detail='Bounds unavailable' step=1" in line for line in logs)


def test_open_scenario_pre_navigation_tap_bounds_center_adb_success(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "tap_bounds_center_adb", "target": "com.test:id/settings_image", "type": "r"}],
        "pre_navigation_retry_count": 1,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.tap_bounds_center_adb_calls) == 1
    assert any("action=tap_bounds_center_adb" in line for line in logs)
    assert any("bounds='[100,200][300,500]'" in line for line in logs)


def test_open_scenario_pre_navigation_tap_bounds_center_adb_retry_on_bounds_not_found(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])
    attempts = {"count": 0}

    def _tap_bounds_center_adb(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            client.last_target_action_result = {"reason": "bounds_not_found", "target": {"lazy_dump_used": True}}
            return False
        client.last_target_action_result = {"reason": "adb_input_tap_sent", "target": {"bounds": "[1,1][11,21]"}}
        return True

    client.tap_bounds_center_adb = _tap_bounds_center_adb
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "tap_bounds_center_adb", "target": "com.test:id/settings_image", "type": "r"}],
        "pre_navigation_retry_count": 2,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert attempts["count"] == 2
    assert any("retry step=1 attempt=1/2 reason='bounds_not_found'" in line for line in logs)


def test_open_scenario_pre_navigation_select_and_click_focused_success(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select_and_click_focused", "target": "com.test:id/settings_button", "type": "r"}],
        "pre_navigation_retry_count": 1,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.select_calls) == 1
    assert len(client.click_focused_calls) == 1
    assert client.select_calls[0]["type_"] == "r"


def test_open_scenario_pre_navigation_select_and_click_focused_select_failure(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([])

    def _select(**kwargs):
        client.last_target_action_result = {"reason": "target_not_found"}
        return False

    client.select = _select
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select_and_click_focused", "target": "com.test:id/settings_button", "type": "r"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    assert len(client.click_focused_calls) == 0
    assert any("select returned false and accessibilityFocused not confirmed" in line for line in logs)
    assert any("failed reason='action_failed' detail='target_not_found' step=1" in line for line in logs)


def test_open_scenario_pre_navigation_select_and_click_focused_select_false_with_focused_target(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])

    def _select(**kwargs):
        client.last_target_action_result = {
            "reason": "ACTION_ACCESSIBILITY_FOCUS failed",
            "target": {"accessibilityFocused": True},
        }
        return False

    client.select = _select
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select_and_click_focused", "target": "com.test:id/settings_button", "type": "r"}],
        "pre_navigation_retry_count": 1,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.click_focused_calls) == 1
    assert any("select returned false but accessibilityFocused=true; continuing with click_focused" in line for line in logs)


def test_open_scenario_pre_navigation_select_and_click_focused_select_false_then_delayed_focus_payload(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})

    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])
    state = {"pending_focus_result": False}

    def _sleep(seconds):
        if state["pending_focus_result"] and abs(seconds - 0.12) < 1e-6:
            client.last_target_action_result = {
                "reason": "ACTION_ACCESSIBILITY_FOCUS failed",
                "target": {"accessibilityFocused": True},
            }
            state["pending_focus_result"] = False

    monkeypatch.setattr(collection_flow.time, "sleep", _sleep)

    def _select(**kwargs):
        client.last_target_action_result = {"reason": "ACTION_ACCESSIBILITY_FOCUS failed"}
        state["pending_focus_result"] = True
        return False

    client.select = _select
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select_and_click_focused", "target": "com.test:id/settings_button", "type": "r"}],
        "pre_navigation_retry_count": 1,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.click_focused_calls) == 1
    assert any("select returned false but accessibilityFocused=true; continuing with click_focused" in line for line in logs)


def test_open_scenario_pre_navigation_select_and_click_focused_click_failure(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([])
    client.select = lambda **kwargs: True

    def _click_focused(**kwargs):
        client.last_target_action_result = {"reason": "focused_click_failed"}
        return False

    client.click_focused = _click_focused
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select_and_click_focused", "target": "com.test:id/settings_button", "type": "r"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False
    assert any("failed reason='action_failed' detail='focused_click_failed' step=1" in line for line in logs)


def test_open_scenario_pre_navigation_select_and_tap_bounds_center_adb_uses_tap_target(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [
            {
                "action": "select_and_tap_bounds_center_adb",
                "target": "com.test:id/setting_button_layout",
                "type": "r",
                "tap_target": "com.test:id/settings_image",
                "tap_type": "r",
            }
        ],
        "pre_navigation_retry_count": 1,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.select_calls) == 1
    assert len(client.tap_bounds_center_adb_calls) == 1
    assert client.tap_bounds_center_adb_calls[0]["name"] == "com.test:id/settings_image"


def test_open_scenario_pre_navigation_focus_first_action_enters_by_click_focused(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])

    def _select(**kwargs):
        client.last_target_action_result = {
            "reason": "moved_to_target",
            "target": {
                "accessibilityFocused": True,
                "viewIdResourceName": "com.test:id/setting_button_layout",
            },
        }
        return True

    client.select = _select
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [
            {
                "action": "select_and_click_focused_or_tap_bounds_center_adb",
                "target": "com.test:id/setting_button_layout",
                "type": "r",
                "tap_target": "com.test:id/settings_image",
                "tap_type": "r",
            }
        ],
        "pre_navigation_retry_count": 1,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.click_focused_calls) == 1
    assert len(client.tap_bounds_center_adb_calls) == 0
    assert any("[SCENARIO][pre_nav][focus_check]" in line and "matched=true" in line for line in logs)
    assert any("enter_by='click_focused'" in line for line in logs)


def test_open_scenario_pre_navigation_focus_first_action_fallbacks_to_tap(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])

    def _select(**kwargs):
        client.last_target_action_result = {"reason": "target_not_found", "target": {"accessibilityFocused": False}}
        return False

    client.select = _select
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [
            {
                "action": "select_and_click_focused_or_tap_bounds_center_adb",
                "target": "com.test:id/setting_button_layout",
                "type": "r",
                "tap_target": "com.test:id/settings_image",
                "tap_type": "r",
            }
        ],
        "pre_navigation_retry_count": 1,
        "pre_navigation_wait_seconds": 0.1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.click_focused_calls) == 0
    assert len(client.tap_bounds_center_adb_calls) == 1
    assert any("focus_first_failed fallback='tap_bounds_center_adb'" in line for line in logs)


def test_open_scenario_pre_navigation_focus_first_action_uses_get_focus_match(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])
    client.select = lambda **kwargs: True
    client.get_focus = lambda **kwargs: {
        "viewIdResourceName": "com.test:id/setting_button_layout",
        "accessibilityFocused": True,
    }
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [
            {
                "action": "select_and_click_focused_or_tap_bounds_center_adb",
                "target": "com.test:id/setting_button_layout",
                "type": "r",
            }
        ],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.click_focused_calls) == 1
    assert any("source='get_focus'" in line for line in logs)


def test_open_scenario_pre_navigation_focus_first_confirms_by_anchor_match(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])
    client.select = lambda **kwargs: True
    client.get_focus = lambda **kwargs: {"viewIdResourceName": "com.test:id/setting_button_layout", "accessibilityFocused": True}
    client.dump_tree_sequence = [
        [{"text": "Settings button", "viewIdResourceName": "com.test:id/setting_button_layout"}],
        [{"text": "Navigate up", "contentDescription": "Navigate up"}],
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "anchor_name": "(?i).*navigate up.*",
        "anchor_type": "a",
        "pre_navigation": [{"action": "select_and_click_focused_or_tap_bounds_center_adb", "target": "com.test:id/setting_button_layout", "type": "r"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.click_focused_calls) == 1
    assert len(client.tap_bounds_center_adb_calls) == 0
    assert any("signal='anchor_match' success=true" in line for line in logs)


def test_open_scenario_pre_navigation_focus_first_confirms_by_screen_text(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])
    client.select = lambda **kwargs: True
    client.get_focus = lambda **kwargs: {"viewIdResourceName": "com.test:id/setting_button_layout", "accessibilityFocused": True}
    client.dump_tree_sequence = [
        [{"text": "Settings button", "viewIdResourceName": "com.test:id/setting_button_layout"}],
        [{"text": "SmartThings settings", "contentDescription": ""}],
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "context_verify": {"type": "screen_text", "text_regex": "(?i).*smartthings settings.*"},
        "pre_navigation": [{"action": "select_and_click_focused_or_tap_bounds_center_adb", "target": "com.test:id/setting_button_layout", "type": "r"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.click_focused_calls) == 1
    assert len(client.tap_bounds_center_adb_calls) == 0
    assert any("signal='screen_text' success=true" in line for line in logs)


def test_open_scenario_pre_navigation_focus_first_fallbacks_only_when_no_confirm_signal(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])
    client.select = lambda **kwargs: True
    client.get_focus = lambda **kwargs: {"viewIdResourceName": "com.test:id/setting_button_layout", "accessibilityFocused": True}
    client.dump_tree_sequence = [
        [{"text": "Settings button", "viewIdResourceName": "com.test:id/setting_button_layout"}],
        [{"text": "Settings button", "viewIdResourceName": "com.test:id/setting_button_layout"}],
        [{"text": "Settings button", "viewIdResourceName": "com.test:id/setting_button_layout"}],
        [{"text": "Settings button", "viewIdResourceName": "com.test:id/setting_button_layout"}],
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "anchor_name": "(?i).*navigate up.*",
        "anchor_type": "a",
        "context_verify": {"type": "screen_text", "text_regex": "(?i).*smartthings settings.*"},
        "pre_navigation": [{"action": "select_and_click_focused_or_tap_bounds_center_adb", "target": "com.test:id/setting_button_layout", "type": "r"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.click_focused_calls) == 1
    assert len(client.tap_bounds_center_adb_calls) == 1
    assert any("signal='none' success=false" in line for line in logs)
    assert any("reason='transition_not_confirmed:none'" in line for line in logs)


def test_open_scenario_pre_navigation_focus_first_confirm_reuses_scenario_metadata(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message: logs.append(message))

    client = DummyClient([_anchor_row()])
    client.select = lambda **kwargs: True
    client.get_focus = lambda **kwargs: {"viewIdResourceName": "com.test:id/setting_button_layout", "accessibilityFocused": True}
    client.dump_tree_sequence = [
        [{"text": "Settings button", "viewIdResourceName": "com.test:id/setting_button_layout"}],
        [{"text": "Back", "viewIdResourceName": "com.test:id/nav_up_button"}],
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "anchor": {"resource_id_regex": "com\\.test:id/nav_up_button"},
        "context_verify": {"type": "screen_text", "text_regex": "(?i).*smartthings settings.*"},
        "pre_navigation": [{"action": "select_and_click_focused_or_tap_bounds_center_adb", "target": "com.test:id/setting_button_layout", "type": "r"}],
        "pre_navigation_retry_count": 1,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert len(client.tap_bounds_center_adb_calls) == 0
    assert any("signal='anchor_match' success=true" in line for line in logs)


def test_run_pre_navigation_steps_transition_fast_path_uses_bounded_waits(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
        "pre_navigation_wait_seconds": 1.0,
    }

    ok = collection_flow._run_pre_navigation_steps(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        transition_fast_path=True,
    )

    assert ok is True
    assert client.select_calls[0]["wait_"] == 2
    assert client.collect_focus_step_calls[0]["wait_seconds"] == 0.25
    assert client.collect_focus_step_calls[0]["announcement_wait_seconds"] == 0.2
    assert client.collect_focus_step_calls[0]["allow_get_focus_fallback_dump"] is False
    assert client.collect_focus_step_calls[0]["get_focus_mode"] == "fast"


def test_open_scenario_new_screen_anchor_only_skips_tab_context(monkeypatch):
    captured = {}
    def _tab_stabilize(**kwargs):
        captured["tab_cfg"] = kwargs["tab_cfg"]
        return {"ok": True}

    def _anchor_stabilize(**kwargs):
        captured["anchor_cfg"] = kwargs["tab_cfg"]
        return {"ok": True}

    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", _tab_stabilize)
    monkeypatch.setattr(collection_flow, "stabilize_anchor", _anchor_stabilize)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "context_verify": {"type": "selected_bottom_tab", "announcement_regex": ".*menu.*"},
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert captured["tab_cfg"]["context_verify"]["type"] == "none"
    assert captured["anchor_cfg"]["stabilization_mode"] == "anchor_only"


def test_open_scenario_new_screen_defaults_to_anchor_only(monkeypatch):
    captured = {}
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    def _anchor_stabilize(**kwargs):
        captured["mode"] = kwargs["tab_cfg"]["stabilization_mode"]
        return {"ok": True}

    monkeypatch.setattr(collection_flow, "stabilize_anchor", _anchor_stabilize)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])

    ok = collection_flow.open_scenario(client, "SERIAL", {**_base_tab_cfg(), "screen_context_mode": "new_screen"})

    assert ok is True
    assert captured["mode"] == "anchor_only"


def test_open_scenario_invalid_modes_fallback_to_legacy(monkeypatch):
    captured = {}
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    def _anchor_stabilize(**kwargs):
        captured["mode"] = kwargs["tab_cfg"]["stabilization_mode"]
        return {"ok": True}

    monkeypatch.setattr(collection_flow, "stabilize_anchor", _anchor_stabilize)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])

    ok = collection_flow.open_scenario(
        client,
        "SERIAL",
        {**_base_tab_cfg(), "screen_context_mode": "unexpected", "stabilization_mode": "unexpected"},
    )

    assert ok is True
    assert captured["mode"] == "anchor_then_context"


def test_open_scenario_transition_allows_tab_verify_failure_and_runs_pre_navigation(monkeypatch):
    logs = []
    called = {"pre_nav": 0}

    monkeypatch.setattr(
        collection_flow,
        "stabilize_tab_selection",
        lambda **kwargs: {
            "ok": False,
            "selected": True,
            "best": {"score": 2},
            "focus_align": {"attempted": True, "ok": False},
        },
    )
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))

    def _pre_nav(**kwargs):
        called["pre_nav"] += 1
        return True

    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _pre_nav)

    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "settings_entry_example",
        "screen_context_mode": "new_screen",
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert called["pre_nav"] == 1
    assert any("[TAB][select][warn]" in line for line in logs)


def test_open_scenario_main_tab_keeps_strict_when_tab_verify_fails(monkeypatch):
    monkeypatch.setattr(
        collection_flow,
        "stabilize_tab_selection",
        lambda **kwargs: {
            "ok": False,
            "selected": True,
            "best": {"score": 2},
            "focus_align": {"attempted": True, "ok": False},
        },
    )
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "home_main",
        "screen_context_mode": "new_screen",
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False


def test_open_scenario_transition_focus_align_failure_soft_proceeds(monkeypatch):
    monkeypatch.setattr(
        collection_flow,
        "stabilize_tab_selection",
        lambda **kwargs: {"ok": True, "focus_align": {"attempted": True, "ok": False}},
    )
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    called = {"pre_nav": 0}

    def _pre_nav(**kwargs):
        called["pre_nav"] += 1
        return True

    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _pre_nav)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "settings_entry_example",
        "screen_context_mode": "new_screen",
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert called["pre_nav"] == 1


def test_open_scenario_transition_fast_path_uses_short_waits(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)

    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "settings_entry_example",
        "screen_context_mode": "new_screen",
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
        "main_step_wait_seconds": 1.2,
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert 0.25 in sleep_calls
    assert 0.1 in sleep_calls
    assert sleep_calls.count(0.25) >= 2  # tab settle + scenario_start post anchor are both fast-bounded


def test_open_scenario_transition_fast_path_passes_fast_flags_to_pre_nav(monkeypatch):
    captured = {}
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    def _pre_nav(**kwargs):
        captured["transition_fast_path"] = kwargs.get("transition_fast_path")
        return True

    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _pre_nav)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "settings_entry_example",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert captured["transition_fast_path"] is True


def test_open_scenario_main_tab_does_not_use_transition_fast_path(monkeypatch):
    captured = {}
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    def _pre_nav(**kwargs):
        captured["transition_fast_path"] = kwargs.get("transition_fast_path")
        return True

    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _pre_nav)
    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "home_main",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert captured["transition_fast_path"] is False


def test_open_scenario_transition_fast_focus_align_failure_logs_and_proceeds(monkeypatch):
    logs = []
    monkeypatch.setattr(
        collection_flow,
        "stabilize_tab_selection",
        lambda **kwargs: {"ok": True, "focus_align": {"attempted": True, "ok": False, "fast_mode": True}},
    )
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))

    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "settings_entry_example",
        "screen_context_mode": "new_screen",
        "pre_navigation": [{"action": "select", "target": ".*Settings.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert any("[TAB][focus_align_fast]" in line and "failed but proceeding" in line for line in logs)


def test_open_scenario_main_tab_focus_align_failure_is_strict(monkeypatch):
    monkeypatch.setattr(
        collection_flow,
        "stabilize_tab_selection",
        lambda **kwargs: {"ok": True, "focus_align": {"attempted": True, "ok": False}},
    )
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])
    tab_cfg = {**_base_tab_cfg(), "scenario_id": "home_main"}

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False


def test_open_scenario_new_screen_allows_low_confidence_fallback_start(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {
            "ok": False,
            "reason": "low_confidence_anchor_start",
            "fallback_candidate_used": True,
            "fallback_candidate_label": "Life 홈케어",
            "start_candidate_source": "fallback_top_content",
            "verify_row": {
                "visible_label": "Life 홈케어",
                "merged_announcement": "홈케어",
                "get_focus_top_level_payload_sufficient": True,
            },
        },
    )
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))

    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_home_care_plugin",
        "screen_context_mode": "new_screen",
        "pre_navigation": [{"action": "select", "target": ".*홈케어.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert tab_cfg["_scenario_start_mode"] == "low_confidence_fallback"
    assert tab_cfg["_scenario_anchor_stable"] is False
    assert any("proceeding with low-confidence fallback start" in line for line in logs)
    assert any("mode='low_confidence_fallback'" in line for line in logs)


def test_open_scenario_new_screen_anchor_fail_without_evidence_aborts(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {
            "ok": False,
            "reason": "low_confidence_anchor_start",
            "fallback_candidate_used": False,
            "verify_row": {},
        },
    )
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_home_care_plugin",
        "screen_context_mode": "new_screen",
        "pre_navigation": [{"action": "select", "target": ".*홈케어.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False


def test_open_scenario_plugin_new_screen_boilerplate_only_candidate_aborts(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {
            "ok": False,
            "reason": "low_confidence_anchor_start",
            "fallback_candidate_used": False,
            "fallback_candidate_rejected_reason": "boilerplate_like",
            "verify_row": {},
        },
    )
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_food_plugin",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [{"action": "select", "target": ".*food.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False


def test_open_scenario_non_plugin_new_screen_does_not_allow_low_confidence_fallback(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(
        collection_flow,
        "stabilize_anchor",
        lambda **kwargs: {
            "ok": False,
            "reason": "low_confidence_anchor_start",
            "fallback_candidate_used": True,
            "fallback_candidate_label": "설정",
            "verify_row": {"visible_label": "설정", "get_focus_top_level_payload_sufficient": True},
        },
    )
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "settings_entry_example",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "tab_context",
        "pre_navigation": [{"action": "select", "target": ".*설정.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is False


def test_collect_tab_rows_marks_low_confidence_start_metadata(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (
            True,
            0,
            0,
            "repeat_no_progress",
            ("fp", "id", "b"),
            {"terminal": False, "same_like_count": 2, "no_progress": True, "reason": "repeat_no_progress"},
        ),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    def _open(*_args, **_kwargs):
        tab_cfg["__scenario_opened"] = True
        tab_cfg["_scenario_start_mode"] = "low_confidence_fallback"
        tab_cfg["_scenario_start_source"] = "fallback_top_content"
        tab_cfg["_scenario_anchor_stable"] = False
        tab_cfg["_scenario_start_note"] = "scenario start anchor unstable; proceeded with low-confidence fallback start"
        return True

    monkeypatch.setattr(collection_flow, "open_scenario", _open)
    tab_cfg = _base_tab_cfg(max_steps=1)
    rows = collection_flow.collect_tab_rows(client, "SERIAL", tab_cfg, [], "o.xlsx", "out")

    assert rows[0]["scenario_start_mode"] == "low_confidence_fallback"
    assert rows[0]["anchor_stable"] is False
    assert "low-confidence fallback start" in rows[0]["review_note"]


def test_open_scenario_anchor_stable_keeps_existing_mode(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", lambda **kwargs: True)
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = DummyClient([_anchor_row()])
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_home_care_plugin",
        "screen_context_mode": "new_screen",
        "pre_navigation": [{"action": "select", "target": ".*홈케어.*", "type": "a"}],
    }

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    assert tab_cfg["_scenario_start_mode"] == "anchor_stable"
    assert tab_cfg["_scenario_anchor_stable"] is True


def test_build_row_fingerprint_prefers_resource_id():
    row = {
        "focus_view_id": "com.example:id/title",
        "visible_label": "Visible Label",
        "merged_announcement": "Speech Value",
        "focus_bounds": "10,20,30,40",
    }

    fingerprint = collection_flow.build_row_fingerprint(row)

    assert fingerprint.startswith("com.example:id/title|visible label|speech value|20,30")


def test_collect_tab_rows_sets_duplicate_flag_for_repeated_fingerprint(monkeypatch):
    repeated_row = {
        "step_index": 1,
        "move_result": "moved",
        "visible_label": "same",
        "normalized_visible_label": "same",
        "merged_announcement": "same",
        "focus_view_id": "id.same",
        "focus_bounds": "0,10,10,20",
    }
    client = DummyClient([_anchor_row(), repeated_row, {**repeated_row, "step_index": 2}])

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (
            False,
            0,
            0,
            "",
            ("same", "id.same", "0,10,10,20"),
            {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""},
        ),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=2), [], "o.xlsx", "out")

    assert rows[2]["fingerprint_repeat_count"] == 1
    assert rows[2]["is_duplicate_step"] is True
    assert rows[2]["is_recent_duplicate_step"] is True
    assert rows[2]["recent_duplicate_distance"] == 1
    assert rows[2]["recent_duplicate_of_step"] == 1


def test_collect_tab_rows_marks_non_consecutive_recent_duplicate(monkeypatch):
    row_b = {
        "step_index": 1,
        "move_result": "moved",
        "visible_label": "b",
        "normalized_visible_label": "b",
        "merged_announcement": "b",
        "focus_view_id": "id.b",
        "focus_bounds": "0,10,10,20",
    }
    row_c = {**row_b, "step_index": 2, "visible_label": "c", "normalized_visible_label": "c", "merged_announcement": "c", "focus_view_id": "id.c"}
    row_a_again = {
        "step_index": 3,
        "move_result": "moved",
        "visible_label": "anchor",
        "normalized_visible_label": "anchor",
        "merged_announcement": "anchor",
        "focus_view_id": "id.anchor",
        "focus_bounds": "0,0,10,10",
    }
    client = DummyClient([_anchor_row(), row_b, row_c, row_a_again])

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (
            False,
            0,
            0,
            "",
            ("anchor", "id.anchor", "0,0,10,10"),
            {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""},
        ),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=3), [], "o.xlsx", "out")

    assert rows[3]["is_duplicate_step"] is False
    assert rows[3]["is_recent_duplicate_step"] is True
    assert rows[3]["recent_duplicate_distance"] == 3
    assert rows[3]["recent_duplicate_of_step"] == 0


def test_collect_tab_rows_marks_recent_duplicate_false_when_no_match(monkeypatch):
    row_b = {
        "step_index": 1,
        "move_result": "moved",
        "visible_label": "b",
        "normalized_visible_label": "b",
        "merged_announcement": "b",
        "focus_view_id": "id.b",
        "focus_bounds": "0,10,10,20",
    }
    row_c = {**row_b, "step_index": 2, "visible_label": "c", "normalized_visible_label": "c", "merged_announcement": "c", "focus_view_id": "id.c"}
    row_d = {**row_b, "step_index": 3, "visible_label": "d", "normalized_visible_label": "d", "merged_announcement": "d", "focus_view_id": "id.d"}
    client = DummyClient([_anchor_row(), row_b, row_c, row_d])

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (
            False,
            0,
            0,
            "",
            ("d", "id.d", "0,10,10,20"),
            {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""},
        ),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=3), [], "o.xlsx", "out")

    assert rows[3]["is_recent_duplicate_step"] is False
    assert rows[3]["recent_duplicate_distance"] == 0
    assert rows[3]["recent_duplicate_of_step"] == -1


def test_collect_tab_rows_marks_noise_when_speech_is_empty(monkeypatch):
    noise_row = {
        "step_index": 1,
        "move_result": "moved",
        "visible_label": "Wi-Fi",
        "normalized_visible_label": "wi-fi",
        "merged_announcement": "",
        "focus_view_id": "id.wifi",
        "focus_bounds": "0,10,10,20",
    }
    client = DummyClient([_anchor_row(), noise_row])

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (
            True,
            0,
            0,
            "repeat_no_progress",
            ("wi-fi", "id.wifi", "0,10,10,20"),
            {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": "repeat_no_progress"},
        ),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=1), [], "o.xlsx", "out")

    assert rows[1]["is_noise_step"] is True
    assert rows[1]["noise_reason"] == "speech_empty"


def test_normalize_row_decision_inputs_builds_duplicate_and_semantic_snapshot():
    row = {
        "step_index": 5,
        "visible_label": "Wi-Fi",
        "normalized_visible_label": "wi-fi",
        "merged_announcement": "Wi-Fi",
        "focus_view_id": "id.wifi",
        "focus_bounds": "0,10,10,20",
    }
    recent_fingerprint_history = collection_flow.deque(
        [
            (3, collection_flow.build_row_fingerprint(row)),
            (4, "another-fingerprint"),
        ],
        maxlen=5,
    )
    recent_semantic_fingerprint_history = collection_flow.deque(
        [
            (2, "semantic-x"),
            (3, collection_flow.build_row_semantic_fingerprint(row)),
            (4, "semantic-y"),
        ],
        maxlen=5,
    )

    snapshot = collection_flow._normalize_row_decision_inputs(
        row,
        last_fingerprint=collection_flow.build_row_fingerprint(row),
        fingerprint_repeat_count=2,
        recent_fingerprint_history=recent_fingerprint_history,
        recent_semantic_fingerprint_history=recent_semantic_fingerprint_history,
    )

    assert snapshot["fingerprint_repeat_count"] == 3
    assert snapshot["is_duplicate_step"] is True
    assert snapshot["is_recent_duplicate_step"] is True
    assert snapshot["recent_duplicate_distance"] == 2
    assert snapshot["recent_duplicate_of_step"] == 3
    assert snapshot["is_recent_semantic_duplicate_step"] is True
    assert snapshot["recent_semantic_duplicate_distance"] == 2
    assert snapshot["recent_semantic_duplicate_of_step"] == 3
    assert snapshot["recent_semantic_unique_count"] == 3


def test_build_stop_evaluation_inputs_applies_global_nav_override(monkeypatch):
    row = {
        "visible_label": "홈",
        "focus_view_id": "com.example:id/home",
    }
    tab_cfg = {**_base_tab_cfg(), "scenario_type": "global_nav"}
    stop_details = {
        "scenario_type": "global_nav",
        "is_global_nav": False,
        "global_nav_reason": "from_stop_details",
        "repeat_class": "strict",
        "loop_classification": "none",
    }
    monkeypatch.setattr(collection_flow, "is_global_nav_row", lambda *_args, **_kwargs: (True, "from_override"))

    snapshot = collection_flow._build_stop_evaluation_inputs(stop_details=stop_details, row=row, tab_cfg=tab_cfg)

    assert snapshot["scenario_type"] == "global_nav"
    assert snapshot["is_global_nav_only_scenario"] is True
    assert snapshot["is_global_nav"] is True
    assert snapshot["global_nav_reason"] == "from_override"
    assert snapshot["repeat_class"] == "strict"


def test_collect_tab_rows_attempts_stall_escape_once_before_stop(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1), _main_row(2)])
    stop_sequence = iter(
        [
            (
                True,
                0,
                8,
                "repeat_semantic_stall",
                ("item1", "id.1", "0,10,10,20"),
                {
                    "terminal": False,
                    "same_like_count": 8,
                    "no_progress": True,
                    "reason": "repeat_semantic_stall",
                    "repeat_stop_hit": True,
                    "scenario_type": "content",
                    "recent_duplicate": True,
                    "recent_semantic_duplicate": True,
                    "recent_semantic_unique_count": 1,
                    "semantic_same_like": True,
                },
            ),
            (
                True,
                0,
                8,
                "repeat_no_progress",
                ("item2", "id.2", "0,10,10,20"),
                {"terminal": False, "same_like_count": 8, "no_progress": True, "reason": "repeat_no_progress"},
            ),
        ]
    )
    calls = {"escape": 0}

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: next(stop_sequence))
    monkeypatch.setattr(collection_flow, "attempt_stall_escape", lambda **k: calls.__setitem__("escape", calls["escape"] + 1) or {"success": True, "reason": "semantic_changed"})
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    tab_cfg = {**_base_tab_cfg(max_steps=2), "group": "plugin_screen", "screen_context_mode": "new_screen", "scenario_type": "content"}
    rows = collection_flow.collect_tab_rows(client, "SERIAL", tab_cfg, [], "o.xlsx", "out")

    assert calls["escape"] == 1
    assert rows[1]["status"] == "OK"
    assert rows[1]["stall_escape_result"] == "success"
    assert rows[2]["status"] == "END"


def test_collect_tab_rows_stops_with_after_escape_reason_when_escape_fails(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (
            True,
            0,
            8,
            "repeat_semantic_stall",
            ("item1", "id.1", "0,10,10,20"),
            {
                "terminal": False,
                "same_like_count": 8,
                "no_progress": True,
                "reason": "repeat_semantic_stall",
                "repeat_stop_hit": True,
                "scenario_type": "content",
                "recent_duplicate": True,
                "recent_semantic_duplicate": True,
                "recent_semantic_unique_count": 1,
                "semantic_same_like": True,
            },
        ),
    )
    monkeypatch.setattr(collection_flow, "attempt_stall_escape", lambda **k: {"success": False, "reason": "same_semantic_object_after_escape"})
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))
    tab_cfg = {**_base_tab_cfg(max_steps=1), "group": "plugin_screen", "screen_context_mode": "new_screen", "scenario_type": "content"}

    rows = collection_flow.collect_tab_rows(client, "SERIAL", tab_cfg, [], "o.xlsx", "out")

    assert rows[1]["status"] == "END"
    assert rows[1]["stop_reason"] == "repeat_semantic_stall_after_escape"


def test_collect_tab_rows_stall_escape_is_only_attempted_once_per_scenario(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1), _main_row(2)])
    stop_sequence = iter(
        [
            (
                True,
                0,
                8,
                "repeat_semantic_stall",
                ("item1", "id.1", "0,10,10,20"),
                {
                    "terminal": False,
                    "same_like_count": 8,
                    "no_progress": True,
                    "reason": "repeat_semantic_stall",
                    "repeat_stop_hit": True,
                    "scenario_type": "content",
                    "recent_duplicate": True,
                    "recent_semantic_duplicate": True,
                    "recent_semantic_unique_count": 1,
                    "semantic_same_like": True,
                },
            ),
            (
                True,
                0,
                9,
                "repeat_semantic_stall",
                ("item2", "id.2", "0,10,10,20"),
                {
                    "terminal": False,
                    "same_like_count": 9,
                    "no_progress": True,
                    "reason": "repeat_semantic_stall",
                    "repeat_stop_hit": True,
                    "scenario_type": "content",
                    "recent_duplicate": True,
                    "recent_semantic_duplicate": True,
                    "recent_semantic_unique_count": 1,
                    "semantic_same_like": True,
                },
            ),
        ]
    )
    calls = {"escape": 0}
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: next(stop_sequence))
    monkeypatch.setattr(collection_flow, "attempt_stall_escape", lambda **k: calls.__setitem__("escape", calls["escape"] + 1) or {"success": True, "reason": "semantic_changed"})
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))
    tab_cfg = {**_base_tab_cfg(max_steps=2), "group": "plugin_screen", "screen_context_mode": "new_screen", "scenario_type": "content"}

    rows = collection_flow.collect_tab_rows(client, "SERIAL", tab_cfg, [], "o.xlsx", "out")

    assert calls["escape"] == 1
    assert rows[2]["status"] == "END"
    assert rows[2]["stop_reason"] == "repeat_semantic_stall_after_escape"


def test_collect_tab_rows_main_tabs_do_not_apply_stall_escape(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    calls = {"escape": 0}
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (
            True,
            0,
            8,
            "repeat_semantic_stall",
            ("item1", "id.1", "0,10,10,20"),
            {
                "terminal": False,
                "same_like_count": 8,
                "no_progress": True,
                "reason": "repeat_semantic_stall",
                "repeat_stop_hit": True,
                "scenario_type": "content",
                "recent_duplicate": True,
                "recent_semantic_duplicate": True,
                "recent_semantic_unique_count": 1,
                "semantic_same_like": True,
            },
        ),
    )
    monkeypatch.setattr(collection_flow, "attempt_stall_escape", lambda **k: calls.__setitem__("escape", calls["escape"] + 1) or {"success": True, "reason": "semantic_changed"})
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))
    tab_cfg = {**_base_tab_cfg(max_steps=1), "group": "main_tabs", "screen_context_mode": "bottom_tab", "scenario_type": "content"}

    rows = collection_flow.collect_tab_rows(client, "SERIAL", tab_cfg, [], "o.xlsx", "out")

    assert calls["escape"] == 0
    assert rows[1]["status"] == "END"
    assert rows[1]["stop_reason"] == "repeat_semantic_stall"


def test_life_root_state_snapshot_allows_unselected_life_tab_with_strong_root_signature():
    nodes = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_services", "selected": False, "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/preInstalledServiceCard", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/serviceCard", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/divider_text", "text": "More services", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/cardTitle", "text": "Energy", "visibleToUser": True},
    ]

    snapshot = collection_flow._life_root_state_snapshot(nodes)

    assert snapshot["life_selected"] is False
    assert snapshot["life_root_signature_present"] is True
    assert snapshot["final_score"] >= 3
    assert snapshot["ok"] is True


def test_life_root_state_snapshot_fails_when_root_signature_missing():
    nodes = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/random_card_container", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/random_card_container2", "visibleToUser": True},
    ]

    snapshot = collection_flow._life_root_state_snapshot(nodes)

    assert snapshot["life_root_signature_present"] is False
    assert snapshot["ok"] is False
    assert snapshot["fail_reason"] == "life_root_not_stable"


def test_verify_plugin_entry_root_state_allows_life_energy_transient_recheck(monkeypatch):
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/random_card_container", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/random_card_container2", "visibleToUser": True},
        ],
        [
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/preInstalledServiceCard", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/serviceCard", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/divider_text", "text": "More services", "visibleToUser": True},
        ],
    ]
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    ok, reason = collection_flow._verify_plugin_entry_root_state(
        client,
        "SERIAL",
        phase="before_pre_navigation",
        scenario_id="life_energy_plugin",
    )

    assert ok is True
    assert reason == "root_state_stable_recheck"


def test_verify_plugin_entry_root_state_allows_life_energy_relaxed_scrolltouch_gate(monkeypatch):
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_services", "selected": True, "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/random_container", "visibleToUser": True},
        ]
    ]
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    ok, reason = collection_flow._verify_plugin_entry_root_state(
        client,
        "SERIAL",
        phase="before_pre_navigation",
        scenario_id="life_energy_plugin",
    )

    assert ok is True
    assert reason in {"root_state_stable", "root_state_scrolltouch_entry_relaxed"}


def test_verify_plugin_entry_root_state_allows_relaxed_gate_with_family_care_card_in_list(monkeypatch):
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_services", "selected": True, "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/cardTitle", "text": "Family Care", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/cardDescription", "text": "Add family member", "visibleToUser": True},
        ]
    ]
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    ok, reason = collection_flow._verify_plugin_entry_root_state(
        client,
        "SERIAL",
        phase="before_pre_navigation",
        scenario_id="life_energy_plugin",
    )

    assert ok is True
    assert reason in {"root_state_stable", "root_state_scrolltouch_entry_relaxed"}


def test_verify_plugin_entry_root_state_allows_life_air_care_relaxed_gate_with_family_care_signal(monkeypatch):
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/cardTitle", "text": "Family Care", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/cardDescription", "text": "Add family member", "visibleToUser": True},
        ]
    ]
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    ok, reason = collection_flow._verify_plugin_entry_root_state(
        client,
        "SERIAL",
        phase="before_pre_navigation",
        scenario_id="life_air_care_plugin",
    )

    assert ok is True
    assert reason in {"root_state_stable", "root_state_scrolltouch_entry_relaxed"}


def test_verify_plugin_entry_root_state_allows_focus_align_recheck_relaxed_gate(monkeypatch):
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
            {"viewIdResourceName": "com.samsung.android.oneconnect:id/cardTitle", "text": "Family Care", "visibleToUser": True},
        ]
    ]
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    ok, reason = collection_flow._verify_plugin_entry_root_state(
        client,
        "SERIAL",
        phase="focus_align_recheck",
        scenario_id="life_air_care_plugin",
    )

    assert ok is True
    assert reason == "root_state_scrolltouch_entry_relaxed"


def test_verify_plugin_entry_root_state_relaxed_gate_blocks_navigate_up_detail(monkeypatch):
    client = DummyClient([])
    fail_nodes = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_services", "selected": True, "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
        {"text": "Family Care", "visibleToUser": True},
        {"contentDescription": "Navigate up", "visibleToUser": True},
    ]
    client.dump_tree_sequence = [fail_nodes, fail_nodes, fail_nodes, fail_nodes, fail_nodes, fail_nodes]
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    ok, reason = collection_flow._verify_plugin_entry_root_state(
        client,
        "SERIAL",
        phase="before_pre_navigation",
        scenario_id="life_energy_plugin",
    )

    assert ok is False
    assert reason == "life_root_not_stable"


def test_verify_plugin_entry_root_state_does_not_apply_transient_recheck_to_other_scenarios(monkeypatch):
    client = DummyClient([])
    fail_nodes = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/location_home_button", "text": "Location", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/add_menu_button", "text": "Add", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/random_card_container", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/random_card_container2", "visibleToUser": True},
    ]
    client.dump_tree_sequence = [fail_nodes, fail_nodes]
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    ok, reason = collection_flow._verify_plugin_entry_root_state(
        client,
        "SERIAL",
        phase="before_pre_navigation",
        scenario_id="other_plugin",
    )

    assert ok is False
    assert reason == "life_root_not_stable"
    assert len(client.dump_tree_calls) == collection_flow._PLUGIN_ENTRY_RETRY_COUNT


def test_capture_pre_navigation_failure_bundle_saves_expected_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = DummyClient([])
    client.dump_tree_sequence = [[{"text": "Air Care", "visibleToUser": True}]]
    monkeypatch.setattr(client, "_take_snapshot", lambda _dev, save_path: Path(save_path).write_bytes(b"png"), raising=False)
    monkeypatch.setattr(client, "_resolve_serial", lambda _dev: "SERIAL123", raising=False)

    def _run(args, **kwargs):
        if args[:3] == ["pull", "/sdcard/window_dump_20260101_120000.xml", str(Path("x"))]:
            return ""
        if args[0] == "pull":
            Path(args[2]).write_text("<hierarchy/>", encoding="utf-8")
        return ""

    monkeypatch.setattr(client, "_run", _run, raising=False)
    monkeypatch.setattr(collection_flow, "datetime", SimpleNamespace(
        now=lambda tz=None: __import__("datetime").datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz),
    ))

    bundle_path = collection_flow._capture_pre_navigation_failure_bundle(
        client,
        "SERIAL",
        scenario_id="life_air_care_plugin",
        failure_phase="pre_navigation",
        failure_reason="no_local_match",
        step_index=3,
        target_regex="(?i).*air care.*",
    )

    bundle = Path(bundle_path)
    assert bundle.exists()
    assert bundle.name == "final_failure"
    assert (bundle / "screenshot.png").exists()
    assert (bundle / "window_dump.xml").exists()
    assert (bundle / "helper_dump.json").exists()
    assert (bundle / "focus_payload.json").exists()
    meta = json.loads((bundle / "meta.json").read_text(encoding="utf-8"))
    assert meta["scenario_id"] == "life_air_care_plugin"
    assert meta["failure_reason"] == "no_local_match"
    assert meta["step_index"] == 3


def test_capture_scrolltouch_step_bundle_saves_expected_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = DummyClient([])
    client.dump_tree_sequence = [[{"text": "Air Care", "visibleToUser": True}]]
    monkeypatch.setattr(client, "_take_snapshot", lambda _dev, save_path: Path(save_path).write_bytes(b"png"), raising=False)
    monkeypatch.setattr(client, "_resolve_serial", lambda _dev: "SERIAL123", raising=False)
    monkeypatch.setattr(collection_flow, "datetime", SimpleNamespace(
        now=lambda tz=None: __import__("datetime").datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz),
    ))

    bundle_path = collection_flow._capture_scrolltouch_step_bundle(
        client,
        "SERIAL",
        scenario_id="life_air_care_plugin",
        capture_run_id="20260101_120000",
        step_index=1,
        scroll_step=2,
        target_regex="(?i).*air care.*",
        selected=False,
        selected_reason="no_visible_candidate",
        candidate_stats={"visible_candidate_count": 0, "partial_match_count": 0, "exact_match_count": 0},
    )

    bundle = Path(bundle_path)
    assert bundle.exists()
    assert bundle.name == "step_02"
    assert (bundle / "screenshot.png").exists()
    assert (bundle / "helper_dump.json").exists()
    meta = json.loads((bundle / "meta.json").read_text(encoding="utf-8"))
    assert meta["phase"] == "scrolltouch_step"
    assert meta["scroll_step"] == 2
    assert meta["visible_candidate_count"] == 0
    assert meta["selected"] is False


def test_run_pre_navigation_steps_triggers_capture_for_life_air_care_failure(monkeypatch):
    client = DummyClient([])
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(client, "select", lambda **kwargs: False)
    client.last_target_action_result = {"reason": "Target node not found"}

    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return "output/capture_bundles/life_air_care_plugin/test"

    monkeypatch.setattr(collection_flow, "_capture_pre_navigation_failure_bundle", lambda *args, **kwargs: _capture(**kwargs))

    ok = collection_flow._run_pre_navigation_steps(
        client=client,
        dev="SERIAL",
        tab_cfg={
            "scenario_id": "life_air_care_plugin",
            "pre_navigation": [{"action": "select", "target": "foo", "type": "a"}],
            "pre_navigation_retry_count": 1,
        },
    )

    assert ok is False
    assert captured["scenario_id"] == "life_air_care_plugin"
    assert captured["failure_phase"] == "pre_navigation"
    assert captured["failure_reason"] == "Target node not found"


def test_run_pre_navigation_steps_scrolltouch_accumulates_step_and_final_capture_in_same_run(monkeypatch):
    client = DummyClient([])
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append((level, message)))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(collection_flow, "datetime", SimpleNamespace(
        now=lambda tz=None: __import__("datetime").datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz),
    ))

    client.dump_tree_sequence = [
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    ]
    monkeypatch.setattr(client, "scroll_to_top", lambda **kwargs: {"ok": True}, raising=False)
    monkeypatch.setattr(collection_flow, "_verify_scroll_top_state", lambda *args, **kwargs: (True, "ok", []))
    monkeypatch.setattr(client, "scroll", lambda **kwargs: True, raising=False)
    monkeypatch.setattr(client, "scrollTouch", lambda **kwargs: False, raising=False)

    ok = collection_flow._run_pre_navigation_steps(
        client=client,
        dev="SERIAL",
        tab_cfg={
            "scenario_id": "life_air_care_plugin",
            "screen_context_mode": "new_screen",
            "stabilization_mode": "anchor_only",
            "pre_navigation": [{"action": "scrollTouch", "target": "(?i).*air care.*", "type": "a"}],
            "pre_navigation_retry_count": 1,
            "max_scroll_search_steps": 2,
        },
    )

    assert ok is False
    assert any("[CAPTURE][scrolltouch_step]" in line for _, line in logs)
    assert any("[CAPTURE][pre_nav_failure]" in line and "/final_failure'" in line for _, line in logs)
    step_dir = Path("output/capture_bundles/life_air_care_plugin/20260101_120000/step_01")
    final_dir = Path("output/capture_bundles/life_air_care_plugin/20260101_120000/final_failure")
    assert step_dir.exists()
    assert final_dir.exists()


def test_capture_pre_navigation_failure_bundle_logs_partial_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = DummyClient([])
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append((level, message)))
    monkeypatch.setattr(client, "_take_snapshot", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("snap_fail")), raising=False)
    monkeypatch.setattr(client, "_resolve_serial", lambda _dev: "SERIAL123", raising=False)

    def _run(args, **kwargs):
        _ = kwargs
        if args[0] == "pull":
            raise RuntimeError("pull_fail")
        return ""

    monkeypatch.setattr(client, "_run", _run, raising=False)
    monkeypatch.setattr(collection_flow, "datetime", SimpleNamespace(
        now=lambda tz=None: __import__("datetime").datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz),
    ))

    bundle_path = collection_flow._capture_pre_navigation_failure_bundle(
        client,
        "SERIAL",
        scenario_id="life_air_care_plugin",
        failure_phase="pre_navigation",
        failure_reason="action_failed",
        step_index=1,
        target_regex="foo",
        log_fn=collection_flow.log,
    )

    assert Path(bundle_path).exists()
    assert any("[CAPTURE][pre_nav_failure] start" in line and "phase='pre_navigation'" in line for _, line in logs)
    assert any(
        "[CAPTURE][pre_nav_failure] failed" in line
        and "saved_files='helper_dump.json,focus_payload.json,meta.json'" in line
        and "failed_files='screenshot.png:snap_fail,window_dump.xml:pull_fail'" in line
        for _, line in logs
    )


def test_open_scenario_focus_align_strict_failure_triggers_capture(monkeypatch):
    client = DummyClient([])
    logs = []
    capture_calls = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append((level, message)))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    monkeypatch.setattr(
        collection_flow,
        "stabilize_tab_selection",
        lambda **kwargs: {
            "ok": True,
            "selected": True,
            "context": {"ok": True},
            "focus_align": {"attempted": True, "ok": False, "fast_mode": True, "reason": "focus_miss"},
        },
    )
    monkeypatch.setattr(
        collection_flow,
        "_verify_plugin_entry_root_state",
        lambda *args, **kwargs: (False, "life_root_not_stable"),
    )
    monkeypatch.setattr(
        collection_flow,
        "_capture_pre_navigation_failure_bundle",
        lambda *args, **kwargs: capture_calls.append(kwargs) or "output/capture_bundles/life_air_care_plugin/test",
    )

    ok = collection_flow.open_scenario(
        client,
        "SERIAL",
        {
            "scenario_id": "life_air_care_plugin",
            "tab_name": "홈",
            "tab_type": "t",
            "scenario_type": "content",
            "screen_context_mode": "new_screen",
            "stabilization_mode": "anchor_only",
            "pre_navigation": [{"action": "scrollTouch", "target": "foo", "type": "a"}],
        },
    )

    assert ok is False
    assert capture_calls
    assert capture_calls[0]["failure_phase"] == "focus_align_recheck"
    assert capture_calls[0]["failure_reason"] == "life_root_not_stable"
    assert any("strict failure for plugin pre_navigation" in line for _, line in logs)


def test_open_scenario_focus_align_recheck_relaxed_gate_proceeds_to_pre_navigation(monkeypatch):
    client = DummyClient([])
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    pre_nav_called = {"value": False}

    monkeypatch.setattr(
        collection_flow,
        "stabilize_tab_selection",
        lambda **kwargs: {
            "ok": True,
            "selected": True,
            "context": {"ok": True},
            "focus_align": {"attempted": True, "ok": False, "fast_mode": True, "reason": "focus_miss"},
        },
    )
    monkeypatch.setattr(collection_flow, "_verify_plugin_entry_root_state", lambda *args, **kwargs: (True, "root_state_scrolltouch_entry_relaxed"))
    monkeypatch.setattr(
        collection_flow,
        "_run_pre_navigation_steps",
        lambda **kwargs: pre_nav_called.__setitem__("value", True) or True,
    )
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True, "matched": True})

    ok = collection_flow.open_scenario(
        client,
        "SERIAL",
        {
            "scenario_id": "life_air_care_plugin",
            "tab_name": "홈",
            "tab_type": "t",
            "scenario_type": "content",
            "screen_context_mode": "new_screen",
            "stabilization_mode": "anchor_only",
            "pre_navigation": [{"action": "scrollTouch", "target": "foo", "type": "a"}],
        },
    )

    assert ok is True
    assert pre_nav_called["value"] is True


def test_xml_entry_strict_target_gating_scrolls_until_target_then_selects(monkeypatch):
    class XmlClient:
        def __init__(self):
            self.scroll_calls = []
            self.tap_calls = []

        def scroll(self, dev, direction, step_=50, time_=1000, bounds_=None):
            _ = (dev, step_, time_, bounds_)
            self.scroll_calls.append(direction)
            return True

        def tap_xy_adb(self, dev, x, y):
            self.tap_calls.append((dev, x, y))
            return True

    first_nodes = [
        {
            "text": "Family Care",
            "contentDescription": "",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/service_card",
            "className": "android.widget.FrameLayout",
            "clickable": True,
            "focusable": False,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "0,300,1080,760",
            "children": [],
        }
    ]
    second_nodes = [
        {
            "text": "Air Care",
            "contentDescription": "",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/service_card",
            "className": "android.widget.FrameLayout",
            "clickable": True,
            "focusable": False,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "0,280,1080,740",
            "children": [],
        }
    ]
    dumps = iter([(first_nodes, "ok"), (second_nodes, "ok")])
    logs = []
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", lambda **kwargs: next(dumps))
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **kwargs: (True, "transition_confirmed"))
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = XmlClient()
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "life_air_care_plugin"},
        target=r"(?i)\b(air\s*care|smart\s*air\s*care|에어\s*케어)\b",
        type_="card",
        max_scroll_search_steps=2,
        step_wait_seconds=0.2,
        transition_fast_path=False,
    )

    assert ok is True
    assert reason == "xml_entry_success"
    assert client.scroll_calls == ["down"]
    assert len(client.tap_calls) == 1
    assert any("target_candidates=0" in line for line in logs)
    assert any("[XMLENTRY][scroll]" in line and "reason='no_strict_target_candidate'" in line for line in logs)
    assert any("[XMLENTRY][select]" in line and "target_match=true" in line and "matched_phrase='air care'" in line for line in logs)


def test_xml_entry_strict_target_gating_returns_not_found_when_target_missing(monkeypatch):
    class XmlClient:
        def __init__(self):
            self.scroll_calls = []
            self.tap_calls = []

        def scroll(self, dev, direction, step_=50, time_=1000, bounds_=None):
            _ = (dev, step_, time_, bounds_)
            self.scroll_calls.append(direction)
            return True

        def tap_xy_adb(self, dev, x, y):
            self.tap_calls.append((dev, x, y))
            return True

    nodes = [
        {
            "text": "Family Care",
            "contentDescription": "",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/service_card",
            "className": "android.widget.FrameLayout",
            "clickable": True,
            "focusable": False,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "0,300,1080,760",
            "children": [],
        }
    ]
    logs = []
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", lambda **kwargs: (nodes, "ok"))
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = XmlClient()
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "life_air_care_plugin"},
        target=r"(?i)\b(air\s*care|smart\s*air\s*care|에어\s*케어)\b",
        type_="card",
        max_scroll_search_steps=1,
        step_wait_seconds=0.2,
        transition_fast_path=False,
    )

    assert ok is False
    assert reason == "target_not_found_after_scroll"
    assert client.scroll_calls == ["down"]
    assert client.tap_calls == []
    assert any("[XMLENTRY][result] success=false reason='target_not_found_after_scroll'" in line for line in logs)


def test_xml_entry_strict_target_gating_rejects_cross_plugin_negative_phrase(monkeypatch):
    class XmlClient:
        def __init__(self):
            self.scroll_calls = []
            self.tap_calls = []

        def scroll(self, dev, direction, step_=50, time_=1000, bounds_=None):
            _ = (dev, step_, time_, bounds_)
            self.scroll_calls.append(direction)
            return True

        def tap_xy_adb(self, dev, x, y):
            self.tap_calls.append((dev, x, y))
            return True

    nodes = [
        {
            "text": "Home Care",
            "contentDescription": "",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/service_card",
            "className": "android.widget.FrameLayout",
            "clickable": True,
            "focusable": False,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "0,260,1080,720",
            "children": [
                {
                    "text": "Get smart care now",
                    "contentDescription": "",
                    "viewIdResourceName": "",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "40,300,700,360",
                    "children": [],
                }
            ],
        }
    ]
    logs = []
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", lambda **kwargs: (nodes, "ok"))
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = XmlClient()
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "life_air_care_plugin"},
        target=r"(?i)\b(air\s*care|smart\s*air\s*care|에어\s*케어)\b",
        type_="card",
        max_scroll_search_steps=0,
        step_wait_seconds=0.2,
        transition_fast_path=False,
    )

    assert ok is False
    assert reason == "target_not_found_after_scroll"
    assert client.tap_calls == []
    assert any("target_match=false" in line and "negative_plugin_phrase='home care'" in line for line in logs)
