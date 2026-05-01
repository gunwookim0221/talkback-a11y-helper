import sys
import json
from collections import deque
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
        self.tap_xy_adb_calls = []
        self.select_calls = []
        self.click_focused_calls = []
        self.collect_focus_step_calls = []
        self.move_focus_smart_calls = []
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

    def move_focus_smart(self, **kwargs):
        self.move_focus_smart_calls.append(kwargs)
        return {"status": "moved", "detail": "forced_test"}

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

    def tap_xy_adb(self, **kwargs):
        self.tap_xy_adb_calls.append(kwargs)
        self.last_target_action_result = {
            "reason": "adb_input_tap_sent",
            "target": {"center": {"x": kwargs.get("x"), "y": kwargs.get("y")}},
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


def _card_body_row(idx=1):
    return {
        "step_index": idx,
        "move_result": "moved",
        "visible_label": "Want better insight into your daily life?",
        "normalized_visible_label": "want better insight into your daily life?",
        "merged_announcement": "Set up the SmartThings devices that you use to better understand your daily life.",
        "focus_view_id": "com.example.plugin:id/title",
        "focus_bounds": "0,10,100,40",
        "focus_node": {
            "text": "Want better insight into your daily life?",
            "contentDescription": "",
            "viewIdResourceName": "com.example.plugin:id/title",
            "className": "android.widget.TextView",
            "clickable": False,
            "focusable": False,
            "effectiveClickable": False,
            "hasClickableDescendant": True,
            "hasFocusableDescendant": True,
        },
    }


def _card_container_row(idx=1):
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
        },
    }


def _card_container_with_cta_children_row(idx=1):
    row = _card_container_row(idx)
    row["focus_node"] = {
        **row["focus_node"],
        "children": [
            {
                "text": "Later",
                "contentDescription": "Later",
                "viewIdResourceName": "com.example.plugin:id/first_button",
                "className": "android.widget.Button",
                "clickable": True,
                "focusable": True,
                "effectiveClickable": True,
                "boundsInScreen": "0,40,40,60",
                "visibleToUser": True,
                "children": [],
            },
            {
                "text": "Set up now",
                "contentDescription": "Set up now",
                "viewIdResourceName": "com.example.plugin:id/second_button",
                "className": "android.widget.Button",
                "clickable": True,
                "focusable": True,
                "effectiveClickable": True,
                "boundsInScreen": "45,40,100,60",
                "visibleToUser": True,
                "children": [],
            },
        ],
    }
    return row


def _cta_row(idx, label, resource_id):
    return {
        "step_index": idx,
        "move_result": "moved",
        "visible_label": label,
        "normalized_visible_label": label.lower(),
        "merged_announcement": label,
        "focus_view_id": resource_id,
        "focus_bounds": "0,40,100,60",
        "focus_node": {
            "text": label,
            "contentDescription": label,
            "viewIdResourceName": resource_id,
            "className": "android.widget.Button",
            "clickable": True,
            "focusable": True,
            "effectiveClickable": True,
        },
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


def test_collect_tab_rows_promotes_card_container_to_actionable_cta_child(monkeypatch):
    client = DummyClient([_anchor_row(), _card_container_with_cta_children_row(1)])
    logs = []

    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(message))
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("fp", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=1), [], "o.xlsx", "out")

    assert rows[1]["cta_promoted_from_container"] is True
    assert rows[1]["focus_view_id"] == "com.example.plugin:id/first_button"
    assert rows[1]["visible_label"] == "Later"
    assert rows[1]["merged_announcement"] == "Later"
    assert any("[STEP][cta_promote]" in line and "first_button" in line and "Later" in line for line in logs)


def test_collect_tab_rows_progresses_to_cta_sibling_when_same_button_repeats(monkeypatch):
    repeated_first = _cta_row(2, "Later", "com.example.plugin:id/first_button")
    repeated_first["move_result"] = "failed"
    client = DummyClient([_anchor_row(), _card_container_with_cta_children_row(1), repeated_first])
    client.focus_sequence = [
        {"viewIdResourceName": "com.example.plugin:id/second_button", "text": "Set up now"},
    ]
    logs = []

    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(message))
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (False, 0, 0, "", ("fp", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=2), [], "o.xlsx", "out")

    assert rows[1]["focus_view_id"] == "com.example.plugin:id/first_button"
    assert rows[2]["focus_view_id"] == "com.example.plugin:id/second_button"
    assert rows[2]["visible_label"] == "Set up now"
    assert rows[2]["cta_sibling_progressed"] is True
    assert any("[STEP][cta_sibling]" in line and "second_button" in line for line in logs)
    assert any("[STEP][cta_focus_align]" in line and "second_button" in line for line in logs)
    assert any(call.get("name") == "com.example.plugin:id/second_button" for call in client.select_calls)


def test_collect_tab_rows_keeps_committed_cta_sibling_on_next_container_step(monkeypatch):
    repeated_first = _cta_row(2, "Later", "com.example.plugin:id/first_button")
    repeated_first["move_result"] = "failed"
    client = DummyClient(
        [
            _anchor_row(),
            _card_container_with_cta_children_row(1),
            repeated_first,
            _card_container_with_cta_children_row(3),
        ]
    )
    logs = []

    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(message))
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (False, 0, 0, "", ("fp", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=3), [], "o.xlsx", "out")

    assert rows[1]["focus_view_id"] == "com.example.plugin:id/first_button"
    assert rows[2]["focus_view_id"] == "com.example.plugin:id/second_button"
    assert rows[3]["focus_view_id"] == "com.example.plugin:id/second_button"
    assert any("[STEP][cta_sibling_commit]" in line and "second_button" in line for line in logs)
    assert any("[STEP][cta_promote_keep]" in line and "second_button" in line for line in logs)


def test_collect_tab_rows_logs_cta_focus_align_fail_when_focus_never_matches(monkeypatch):
    repeated_first = _cta_row(2, "Later", "com.example.plugin:id/first_button")
    repeated_first["move_result"] = "failed"
    client = DummyClient([_anchor_row(), _card_container_with_cta_children_row(1), repeated_first])
    client.focus_sequence = [
        {"viewIdResourceName": "com.example.plugin:id/first_button", "text": "Later"},
        {"viewIdResourceName": "com.example.plugin:id/first_button", "text": "Later"},
    ]
    logs = []

    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(message))
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (False, 0, 0, "", ("fp", "id", "b"), {"terminal": False, "same_like_count": 0, "no_progress": False, "reason": ""}),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=2), [], "o.xlsx", "out")

    assert rows[2]["focus_view_id"] == "com.example.plugin:id/second_button"
    assert any("[STEP][cta_focus_align]" in line and "attempt=1" in line for line in logs)
    assert any("[STEP][cta_focus_align]" in line and "attempt=2" in line for line in logs)
    assert any("[STEP][cta_focus_align_fail]" in line and "no_match" in line for line in logs)


def test_collect_tab_rows_allows_bounded_cta_descend_grace_for_card_container(monkeypatch):
    client = DummyClient(
        [
            _anchor_row(),
            _card_container_row(1),
            _card_container_row(2),
            _card_container_row(3),
        ]
    )
    stop_sequence = iter(
        [
            (
                True,
                0,
                2,
                "repeat_no_progress",
                ("fp-card", "com.example.plugin:id/suggestion_card_container", "0,10,100,80"),
                {
                    "terminal": False,
                    "same_like_count": 2,
                    "no_progress": True,
                    "reason": "repeat_no_progress",
                    "scenario_type": "content",
                    "strict_duplicate": True,
                    "recent_duplicate": True,
                    "recent_semantic_duplicate": True,
                },
            ),
            (
                True,
                0,
                3,
                "repeat_no_progress",
                ("fp-card", "com.example.plugin:id/suggestion_card_container", "0,10,100,80"),
                {
                    "terminal": False,
                    "same_like_count": 3,
                    "no_progress": True,
                    "reason": "repeat_no_progress",
                    "scenario_type": "content",
                    "strict_duplicate": True,
                    "recent_duplicate": True,
                    "recent_semantic_duplicate": True,
                },
            ),
            (
                True,
                0,
                4,
                "repeat_no_progress",
                ("fp-card", "com.example.plugin:id/suggestion_card_container", "0,10,100,80"),
                {
                    "terminal": False,
                    "same_like_count": 4,
                    "no_progress": True,
                    "reason": "repeat_no_progress",
                    "scenario_type": "content",
                    "strict_duplicate": True,
                    "recent_duplicate": True,
                    "recent_semantic_duplicate": True,
                },
            ),
        ]
    )
    logs = []

    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(message))
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: next(stop_sequence))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=3), [], "o.xlsx", "out")

    assert rows[1]["status"] == "OK"
    # CTA grace can continue an intermediate duplicate step without preserving
    # that intermediate row in the final filtered rows.
    assert rows[2]["status"] == "END"
    assert rows[2]["step_index"] == 3
    assert rows[-1]["stop_reason"] in {"repeat_no_progress", "safety_limit"}
    assert rows[-1]["stop_reason"] == "repeat_no_progress"
    descend_logs = [line for line in logs if "[STOP][cta_descend]" in line]
    assert len(descend_logs) == 2
    assert any("step=1" in line and "grace_remaining=1" in line for line in descend_logs)
    assert any("step=2" in line and "grace_remaining=0" in line for line in descend_logs)
    assert any("suggestion_card_container" in line for line in descend_logs)
    assert any("Later" in line and "Set up" in line for line in descend_logs)


def test_collect_tab_rows_keeps_repeat_stop_for_non_cta_end_state(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1)])
    logs = []

    monkeypatch.setattr(collection_flow, "log", lambda message, *args, **kwargs: logs.append(message))
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(
        collection_flow,
        "should_stop",
        lambda **k: (
            True,
            0,
            2,
            "repeat_no_progress",
            ("fp", "id.1", "0,10,10,20"),
            {
                "terminal": False,
                "same_like_count": 2,
                "no_progress": True,
                "reason": "repeat_no_progress",
                "scenario_type": "content",
                "strict_duplicate": True,
                "recent_duplicate": True,
                "recent_semantic_duplicate": True,
            },
        ),
    )
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=2), [], "o.xlsx", "out")

    assert rows[1]["status"] == "END"
    assert rows[1]["stop_reason"] == "repeat_no_progress"
    assert not any("[STOP][cta_descend]" in line for line in logs)


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


def test_select_visible_plugin_candidate_defers_bottom_strip_when_content_candidates_exist(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,360,1040,760",
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
                {
                    "text": "Events",
                    "contentDescription": "",
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

    selected, reason, _, selected_meta = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i).+",
        scenario_id="life_family_care_plugin",
    )

    assert selected is not None
    assert str(selected.get("viewIdResourceName", "")).endswith("device_usage_card")
    assert reason in {"immediate_strong_single"} or reason.startswith("candidate_count=")
    assert any("[SCROLL][realign_priority]" in line for line in logs)
    assert any("[SCROLL][bottom_tabs_deferred]" in line for line in logs)
    assert str(selected_meta.get("selected_container_view_id", "")).endswith("device_usage_card")


def test_select_visible_plugin_candidate_allows_bottom_strip_when_no_content_candidates_exist(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                {
                    "text": "Events",
                    "contentDescription": "",
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

    selected, _, _, _ = collection_flow._select_visible_plugin_candidate(
        nodes=nodes,
        target=r"(?i).+",
        scenario_id="life_family_care_plugin",
    )

    assert selected is not None
    assert str(selected.get("viewIdResourceName", "")) in {
        "com.example:id/activity_button",
        "com.example:id/location_button",
        "com.example:id/events_button",
    }
    assert any("[SCROLL][bottom_tabs_allowed]" in line for line in logs)


def test_reprioritize_persistent_bottom_strip_row_prefers_content_candidates(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                    "text": "Steps",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/steps_title",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "40,260,400,340",
                    "children": [],
                },
                {
                    "text": "Device usage",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/device_usage_card",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,360,1040,760",
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
                {
                    "text": "Events",
                    "contentDescription": "",
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            local_tab_candidates_by_signature={},
            visited_local_tabs_by_signature={},
            current_local_tab_signature="",
            current_local_tab_active_rid="",
        ),
        step_idx=7,
    )

    assert updated["focus_view_id"] == "com.example:id/device_usage_card"
    assert updated["visible_label"] == "Device usage"
    assert updated["bottom_strip_deferred"] is True
    assert any("[STEP][candidate_priority]" in line and "Device usage" in line for line in logs)
    assert any("[STEP][bottom_strip_policy] content_present=true bottom_strip_deferred=true" in line for line in logs)


def test_reprioritize_persistent_bottom_strip_row_allows_fallback_when_no_content(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                {
                    "text": "Events",
                    "contentDescription": "",
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            local_tab_candidates_by_signature={},
            visited_local_tabs_by_signature={},
            current_local_tab_signature="",
            current_local_tab_active_rid="",
        ),
        step_idx=7,
    )

    assert updated["focus_view_id"] == "com.example:id/location_button"
    assert not any("[STEP][candidate_priority]" in line for line in logs)


def test_collect_step_candidate_priority_groups_uses_scalar_sort_keys():
    nodes = [
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
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,360,1040,760",
                    "children": [],
                },
                {
                    "text": "Mobile usage",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/mobile_usage_button",
                    "className": "android.widget.Button",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,360,1040,760",
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
    ]

    content_candidates, bottom_strip_candidates, _ = collection_flow._collect_step_candidate_priority_groups(nodes)

    assert len(content_candidates) >= 2
    assert len(bottom_strip_candidates) >= 2
    assert content_candidates[0]["label"] in {"Device usage", "Mobile usage"}


def test_reprioritize_persistent_bottom_strip_row_deprioritizes_leaf_text(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                    "text": "First activity View information",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/first_activity_row",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,760",
                    "children": [],
                },
                {
                    "text": "5:55",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/activity_time",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "80,500,180,560",
                    "children": [],
                },
                {
                    "text": "pm",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/activity_meridiem",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "190,500,250,560",
                    "children": [],
                },
            ],
        }
    ]
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    row = {
        "focus_view_id": "com.example:id/activity_time",
        "visible_label": "5:55",
        "merged_announcement": "5:55",
        "focus_bounds": "80,500,180,560",
        "focus_class_name": "android.widget.TextView",
        "focus_clickable": False,
        "focus_focusable": False,
        "focus_effective_clickable": False,
    }

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            local_tab_candidates_by_signature={},
            visited_local_tabs_by_signature={},
            current_local_tab_signature="",
            current_local_tab_active_rid="",
        ),
        step_idx=8,
    )

    assert updated["focus_view_id"] == "com.example:id/first_activity_row"
    assert any("[STEP][leaf_penalty]" in line and "5:55" in line for line in logs)
    assert any("reason='representative_content_preferred_over_leaf'" in line for line in logs)


def test_reprioritize_persistent_bottom_strip_row_rejects_recent_revisit(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                    "text": "First activity",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/first_activity_row",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,760",
                    "children": [],
                },
                {
                    "text": "Device usage",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/device_usage_card",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,820,1040,1180",
                    "children": [],
                },
            ],
        }
    ]
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    row = {
        "focus_view_id": "com.example:id/first_activity_row",
        "visible_label": "First activity",
        "merged_announcement": "First activity",
        "focus_bounds": "40,420,1040,760",
        "focus_class_name": "android.widget.FrameLayout",
        "focus_clickable": True,
        "focus_focusable": True,
        "focus_effective_clickable": True,
    }
    recent_signature = collection_flow._build_candidate_object_signature(
        rid="com.example:id/first_activity_row",
        bounds="40,420,1040,760",
        label="First activity",
    )

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=SimpleNamespace(
            recent_representative_signatures=[recent_signature],
            consumed_representative_signatures={recent_signature},
            local_tab_candidates_by_signature={},
            visited_local_tabs_by_signature={},
            current_local_tab_signature="",
            current_local_tab_active_rid="",
        ),
        step_idx=9,
    )

    assert updated["focus_view_id"] == "com.example:id/device_usage_card"
    assert any("[STEP][revisit_guard]" in line and "First activity" in line for line in logs)


def test_reprioritize_persistent_bottom_strip_row_separates_local_tab_strip(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                    "text": "Steps",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/steps_title",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "40,280,340,360",
                    "children": [],
                },
                {
                    "text": "Device usage",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/device_usage_card",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,760",
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
                    "selected": True,
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
                {
                    "text": "Events",
                    "contentDescription": "",
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        recent_focus_realign_signatures=set(),
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
    )
    row = {
        "focus_view_id": "com.example:id/device_usage_card",
        "visible_label": "Device usage",
        "merged_announcement": "Device usage",
        "focus_bounds": "40,420,1040,760",
        "focus_class_name": "android.widget.FrameLayout",
        "focus_clickable": True,
        "focus_focusable": True,
        "focus_effective_clickable": True,
    }

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=state,
        step_idx=11,
    )

    assert updated["focus_view_id"] == "com.example:id/device_usage_card"
    assert state.current_local_tab_active_rid == "com.example:id/activity_button"
    assert any("[STEP][local_tab_strip]" in line and "Activity|Location|Events" in line for line in logs)


def test_local_tab_strip_members_exclude_view_information(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,760",
                    "children": [],
                },
                {
                    "text": "View information",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/view_information_button",
                    "className": "android.widget.Button",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "760,1540,1040,1640",
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
                    "selected": True,
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
                {
                    "text": "Events",
                    "contentDescription": "",
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        recent_focus_realign_signatures=set(),
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
    )
    row = {
        "focus_view_id": "com.example:id/device_usage_card",
        "visible_label": "Device usage",
        "merged_announcement": "Device usage",
        "focus_bounds": "40,420,1040,760",
        "focus_class_name": "android.widget.FrameLayout",
        "focus_clickable": True,
        "focus_focusable": True,
        "focus_effective_clickable": True,
    }

    collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=state,
        step_idx=12,
    )

    assert state.current_local_tab_active_rid == "com.example:id/activity_button"
    assert any("[STEP][local_tab_strip_members]" in line and "accepted_tabs='Activity|Location|Events'" in line for line in logs)
    assert any("[STEP][local_tab_strip_members]" in line and "rejected='View information'" in line for line in logs)
    assert any("[STEP][local_tab_active]" in line and "active='Activity'" in line for line in logs)


def test_maybe_select_next_local_tab_only_after_content_exhausted(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"text": "Navigate up", "contentDescription": "Navigate up", "viewIdResourceName": "com.example:id/navigate_up", "className": "android.widget.ImageButton", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "0,0,120,120", "children": []},
        {"text": "More options", "contentDescription": "", "viewIdResourceName": "com.example:id/more_options", "className": "android.widget.ImageButton", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "920,0,1080,120", "children": []},
    ]]
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
                {"rid": "com.example:id/events_button", "label": "Events", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque(["sig1"], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=12,
    )

    assert advanced is True
    assert state.current_local_tab_active_rid == "com.example:id/location_button"
    assert client.select_calls[0]["name"] == "com.example:id/location_button"
    assert any("[STEP][representative_exhausted_eval]" in line and "exhausted=true" in line for line in logs)
    assert any("[STEP][local_tab_allowed]" in line and "Location|Events" in line for line in logs)
    assert any("[STEP][local_tab_select]" in line and "Location" in line for line in logs)


def test_maybe_select_next_local_tab_blocked_when_content_candidates_remain(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"text": "Device usage", "contentDescription": "", "viewIdResourceName": "com.example:id/device_usage_card", "className": "android.widget.FrameLayout", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,420,1040,760", "children": []},
        {"text": "Navigate up", "contentDescription": "Navigate up", "viewIdResourceName": "com.example:id/navigate_up", "className": "android.widget.ImageButton", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "0,0,120,120", "children": []},
    ]]
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
                {"rid": "com.example:id/events_button", "label": "Events", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=13,
    )

    assert advanced is False
    assert client.select_calls == []
    assert any("[STEP][representative_exhausted_eval]" in line and "Device usage" in line and "exhausted=false" in line for line in logs)


def test_maybe_select_next_local_tab_attempts_scroll_fallback_before_local_tab(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
            {"text": "Navigate up", "contentDescription": "Navigate up", "viewIdResourceName": "com.example:id/navigate_up", "className": "android.widget.ImageButton", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "0,0,120,120", "children": []},
        ],
        [
            {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
            {"text": "Device usage", "contentDescription": "", "viewIdResourceName": "com.example:id/device_usage_card", "className": "android.widget.FrameLayout", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,420,1040,760", "children": []},
        ],
    ]
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
    )
    row = {}

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
    assert client.scroll_calls[0] == "down"
    assert client.select_calls == []
    assert any("[STEP][viewport_exhausted]" in line for line in logs)
    assert any("[STEP][scroll_fallback]" in line for line in logs)
    assert any("[STEP][scroll_fallback_result]" in line and "resumed_content_phase=true" in line for line in logs)


def test_maybe_select_next_local_tab_only_advances_after_scroll_fallback_finds_no_content(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
        ],
        [
            {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
        ],
    ]
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=15,
    )

    assert advanced is True
    assert client.scroll_calls[0] == "down"
    assert client.select_calls[0]["name"] == "com.example:id/location_button"
    assert any("[STEP][scroll_fallback_result]" in line and "resumed_content_phase=false" in line for line in logs)
    assert any("[STEP][local_tab_select]" in line and "Location" in line for line in logs)


def test_maybe_select_next_local_tab_does_not_repeat_scroll_fallback_for_same_signature(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
    ]]
    existing_signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="com.example:id/activity_button||com.example:id/location_button",
        active_rid="com.example:id/activity_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature({}),
    )
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures={existing_signature},
        last_scroll_fallback_attempted_signatures={existing_signature},
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=16,
    )

    assert advanced is True
    assert client.scroll_calls == []
    assert client.select_calls[0]["name"] == "com.example:id/location_button"
    assert any("[STEP][scroll_fallback_eval]" in line and "allowed=false" in line for line in logs)


def _bottom_strip_focus_row():
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


def _last_scroll_local_tab_state(existing_signature, *, last_attempted=False):
    return SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        current_local_tab_active_rid="com.example:id/location_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
                {"rid": "com.example:id/events_button", "label": "Events", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": {
                "com.example:id/activity_button",
                "com.example:id/location_button",
                "com.example:id/events_button",
            }
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/location_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        visited_logical_signatures=set(),
        recent_scroll_fallback_signatures={existing_signature},
        last_scroll_fallback_attempted_signatures={existing_signature} if last_attempted else set(),
    )


def test_maybe_select_next_local_tab_allows_one_last_scroll_when_bottom_strip_blocks_signature(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    row = _bottom_strip_focus_row()
    existing_signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
        ],
        [
            {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
            {"text": "Device usage", "viewIdResourceName": "com.example:id/device_usage_card", "className": "android.widget.FrameLayout", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,420,1040,760", "children": []},
        ],
    ]
    state = _last_scroll_local_tab_state(existing_signature)

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=17,
    )

    assert advanced is False
    assert client.scroll_calls == ["down"]
    assert row["last_scroll_fallback_allowed"] is True
    assert row["scroll_fallback_gate_reason"] == "last_scroll_before_global_exhausted"
    assert row["last_scroll_fallback_resumed_content"] is True
    assert existing_signature in state.last_scroll_fallback_attempted_signatures
    assert any("[STEP][last_scroll_fallback_eval]" in line and "allowed=true" in line for line in logs)
    assert any("[STEP][last_scroll_fallback]" in line for line in logs)
    assert any("[STEP][last_scroll_fallback_result]" in line and "resumed_content_phase=true" in line for line in logs)


def test_maybe_select_next_local_tab_last_scroll_is_bounded_per_signature(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    row = _bottom_strip_focus_row()
    existing_signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
    ]]
    state = _last_scroll_local_tab_state(existing_signature, last_attempted=True)

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=18,
    )

    assert advanced is True
    assert client.scroll_calls == []
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert row["last_scroll_fallback_allowed"] is False
    assert row["last_scroll_block_reason"] == "last_scroll_already_attempted"
    assert any("[STEP][last_scroll_fallback_eval]" in line and "last_scroll_already_attempted" in line for line in logs)


def test_maybe_select_next_local_tab_last_scroll_no_content_marks_global_exhausted(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    row = _bottom_strip_focus_row()
    existing_signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
        ],
        [
            {"viewIdResourceName": "com.example:id/content_recycler", "className": "androidx.recyclerview.widget.RecyclerView", "scrollable": True, "visibleToUser": True, "boundsInScreen": "0,200,1080,1900", "children": []},
        ],
    ]
    state = _last_scroll_local_tab_state(existing_signature)

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=19,
    )

    assert advanced is True
    assert client.scroll_calls == ["down"]
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert row["last_scroll_fallback_resumed_content"] is False
    assert row["last_scroll_global_exhausted"] is True
    assert any("[STEP][last_scroll_fallback_result]" in line and "global_exhausted=true" in line for line in logs)


def test_maybe_select_next_local_tab_last_scroll_uses_dump_bottom_strip_evidence(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    row = {}
    existing_signature = collection_flow._build_scroll_fallback_signature(
        local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        active_rid="com.example:id/location_button",
        content_candidates=[],
        chrome_excluded=[],
        current_focus_signature=collection_flow._build_row_object_signature(row),
    )
    client = DummyClient([])
    client.dump_tree_sequence = [
        [
            {"text": "Activity", "viewIdResourceName": "com.example:id/activity_button", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,1700,300,1860", "children": []},
            {"text": "Location", "viewIdResourceName": "com.example:id/location_button", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "400,1700,660,1860", "children": []},
            {"text": "Events", "viewIdResourceName": "com.example:id/events_button", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "760,1700,1040,1860", "children": []},
        ],
        [
            {"text": "Device usage", "viewIdResourceName": "com.example:id/device_usage_card", "className": "android.widget.FrameLayout", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,420,1040,760", "children": []},
        ],
    ]
    state = _last_scroll_local_tab_state(existing_signature)

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row=row,
        scenario_id="life_family_care_plugin",
        step_idx=20,
    )

    assert advanced is False
    assert client.scroll_calls == ["down"]
    assert row["last_scroll_fallback_allowed"] is True
    assert row["last_scroll_fallback_resumed_content"] is True
    assert any("[STEP][bottom_strip_context_eval]" in line and "dump_strip_seen=true" in line for line in logs)
    assert any("[STEP][last_scroll_fallback_eval]" in line and "bottom_strip_context_scrollable_uncertain" in line for line in logs)


def test_maybe_select_next_local_tab_prefers_rightward_progression_over_visited(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
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
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/location_button", "visible_label": "Location"},
        scenario_id="life_family_care_plugin",
        step_idx=21,
    )

    assert advanced is True
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert state.pending_local_tab_rid == "com.example:id/events_button"
    assert any("[STEP][local_tab_pending]" in line and "Events" in line for line in logs)
    assert any("[STEP][local_tab_sorted]" in line and "Activity|Location|Events" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "current='Location'" in line and "next='Events'" in line for line in logs)
    assert any("[STEP][local_tab_skip_reason]" in line and "visited_ignored_for_order_progression" in line for line in logs)


def test_maybe_select_next_local_tab_recovers_missing_state_from_dump_strip(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"text": "Activity", "viewIdResourceName": "com.example:id/activity_button", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,1700,300,1860", "children": []},
        {"text": "Location", "viewIdResourceName": "com.example:id/location_button", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "400,1700,660,1860", "children": []},
        {"text": "Events", "viewIdResourceName": "com.example:id/events_button", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "760,1700,1040,1860", "children": []},
    ]]
    state = SimpleNamespace(
        current_local_tab_signature="",
        current_local_tab_active_rid="",
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/location_button", "visible_label": "Location", "focus_bounds": "400,1700,660,1860", "focus_class_name": "android.widget.Button", "focus_clickable": True, "focus_focusable": True},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/location_button", "visible_label": "Location", "focus_bounds": "400,1700,660,1860", "focus_class_name": "android.widget.Button", "focus_clickable": True, "focus_focusable": True},
        scenario_id="life_family_care_plugin",
        step_idx=22,
    )

    assert advanced is True
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert state.current_local_tab_active_rid == "com.example:id/events_button"
    assert any("[STEP][local_tab_recover]" in line and "Activity|Location|Events" in line and "active='Location'" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "current='Location'" in line and "next='Events'" in line for line in logs)


def test_maybe_select_next_local_tab_keeps_state_missing_without_strip_candidates(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"text": "Navigate up", "viewIdResourceName": "com.example:id/navigate_up", "className": "android.widget.ImageButton", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "0,0,120,120", "children": []},
    ]]
    state = SimpleNamespace(
        current_local_tab_signature="",
        current_local_tab_active_rid="",
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=23,
    )

    assert advanced is False
    assert client.select_calls == []
    assert any("[STEP][local_tab_gate]" in line and "local_tab_state_missing" in line for line in logs)


def test_maybe_select_next_local_tab_commits_pending_then_progresses_right(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    signature = "activity||location||events"
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/activity_button", "label": "Activity", "left": 40, "node": {"boundsInScreen": "40,1700,300,1860"}},
                {"rid": "com.example:id/location_button", "label": "Location", "left": 400, "node": {"boundsInScreen": "400,1700,660,1860"}},
                {"rid": "com.example:id/events_button", "label": "Events", "left": 760, "node": {"boundsInScreen": "760,1700,1040,1860"}},
            ]
        },
        visited_local_tabs_by_signature={
            signature: {"com.example:id/activity_button", "com.example:id/location_button"}
        },
        pending_local_tab_signature=signature,
        pending_local_tab_rid="com.example:id/location_button",
        pending_local_tab_label="Location",
        pending_local_tab_bounds="400,1700,660,1860",
        pending_local_tab_age=0,
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/location_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/location_button", "visible_label": "Location", "focus_bounds": "400,1700,660,1860"},
        scenario_id="life_family_care_plugin",
        step_idx=24,
    )

    assert advanced is True
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert state.current_local_tab_active_rid == "com.example:id/events_button"
    assert state.pending_local_tab_rid == "com.example:id/events_button"
    assert any("[STEP][local_tab_commit]" in line and "active='Location'" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "current='Location'" in line and "next='Events'" in line for line in logs)


def test_pending_local_tab_commit_matches_contained_label(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
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
    )

    collection_flow._maybe_commit_pending_local_tab_progression(
        state,
        {"focus_view_id": "LocationButton", "visible_label": "LocationButton", "focus_bounds": "400,1700,660,1860"},
    )

    assert state.current_local_tab_active_label == "LocationButton Location"
    assert state.pending_local_tab_label == ""
    assert any("[STEP][local_tab_commit_match]" in line and "matched_by='label_contains'" in line for line in logs)
    assert any("[STEP][local_tab_commit]" in line and "LocationButton Location" in line for line in logs)


def test_committed_local_tab_active_overrides_current_row_inference(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    signature = "activity||location||events"
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/location_button",
        current_local_tab_active_label="Location",
        current_local_tab_active_age=1,
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/activity_button", "label": "Activity", "left": 40, "node": {"boundsInScreen": "40,1700,300,1860"}},
                {"rid": "com.example:id/location_button", "label": "Location", "left": 400, "node": {"boundsInScreen": "400,1700,660,1860"}},
                {"rid": "com.example:id/events_button", "label": "Events", "left": 760, "node": {"boundsInScreen": "760,1700,1040,1860"}},
            ]
        },
        visited_local_tabs_by_signature={signature: {"com.example:id/activity_button", "com.example:id/location_button"}},
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=0,
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/activity_button", "visible_label": "Activity"},
        scenario_id="life_family_care_plugin",
        step_idx=25,
    )

    assert advanced is True
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert any("[STEP][local_tab_active_resolved]" in line and "source='committed'" in line and "Location" in line for line in logs)
    assert any("[STEP][local_tab_active_override]" in line and "committed_state_used_for_progression" in line for line in logs)
    assert any("[STEP][local_tab_active_keep]" in line and "age=1" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "current='Location'" in line and "next='Events'" in line for line in logs)


def test_last_selected_local_tab_hint_overrides_content_row(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    signature = "activity||location||events"
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="",
        current_local_tab_active_label="",
        current_local_tab_active_age=99,
        last_selected_local_tab_signature=signature,
        last_selected_local_tab_rid="com.example:id/location_button",
        last_selected_local_tab_label="Location",
        last_selected_local_tab_bounds="400,1700,660,1860",
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/activity_button", "label": "Activity", "left": 40, "bounds": "40,1700,300,1860", "node": {"boundsInScreen": "40,1700,300,1860"}},
                {"rid": "com.example:id/location_button", "label": "Location", "left": 400, "bounds": "400,1700,660,1860", "node": {"boundsInScreen": "400,1700,660,1860"}},
                {"rid": "com.example:id/events_button", "label": "Events", "left": 760, "bounds": "760,1700,1040,1860", "node": {"boundsInScreen": "760,1700,1040,1860"}},
            ]
        },
        visited_local_tabs_by_signature={signature: {"com.example:id/activity_button", "com.example:id/location_button"}},
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=0,
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/place_row", "visible_label": "Some location content"},
        scenario_id="life_family_care_plugin",
        step_idx=26,
    )

    assert advanced is True
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert any("[STEP][local_tab_active_resolved]" in line and "source='last_selected_hint'" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "current='Location'" in line and "next='Events'" in line for line in logs)


def test_last_selected_hint_survives_committed_ttl_expiry_for_progression(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    signature = "activity||location||events"
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/location_button",
        current_local_tab_active_label="Location",
        current_local_tab_active_age=4,
        last_selected_local_tab_signature=signature,
        last_selected_local_tab_rid="com.example:id/location_button",
        last_selected_local_tab_label="Location",
        last_selected_local_tab_bounds="400,1700,660,1860",
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/activity_button", "label": "Activity", "left": 40, "node": {"boundsInScreen": "40,1700,300,1860"}},
                {"rid": "com.example:id/location_button", "label": "Location", "left": 400, "node": {"boundsInScreen": "400,1700,660,1860"}},
                {"rid": "com.example:id/events_button", "label": "Events", "left": 760, "node": {"boundsInScreen": "760,1700,1040,1860"}},
            ]
        },
        visited_local_tabs_by_signature={signature: {"com.example:id/activity_button"}},
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=0,
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/activity_button", "visible_label": "Activity"},
        scenario_id="life_family_care_plugin",
        step_idx=26,
    )

    assert advanced is True
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert any("[STEP][local_tab_active_clear]" in line and "ttl_expired" in line for line in logs)
    assert any("[STEP][local_tab_active_resolved]" in line and "source='last_selected_hint'" in line and "Location" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "current='Location'" in line and "next='Events'" in line for line in logs)


def test_local_tab_progression_handles_four_tabs_with_committed_middle_active(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    signature = "tab1||tab2||tab3||tab4"
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/tab3",
        current_local_tab_active_label="Tab 3",
        current_local_tab_active_age=0,
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/tab1", "label": "Tab 1", "left": 10, "node": {"boundsInScreen": "10,1700,250,1860"}},
                {"rid": "com.example:id/tab2", "label": "Tab 2", "left": 280, "node": {"boundsInScreen": "280,1700,520,1860"}},
                {"rid": "com.example:id/tab3", "label": "Tab 3", "left": 550, "node": {"boundsInScreen": "550,1700,790,1860"}},
                {"rid": "com.example:id/tab4", "label": "Tab 4", "left": 820, "node": {"boundsInScreen": "820,1700,1060,1860"}},
            ]
        },
        visited_local_tabs_by_signature={signature: {"com.example:id/tab1", "com.example:id/tab2", "com.example:id/tab3"}},
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=0,
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/tab1", "visible_label": "Tab 1"},
        scenario_id="generic_plugin",
        step_idx=27,
    )

    assert advanced is True
    assert client.select_calls[0]["name"] == "com.example:id/tab4"
    assert any("[STEP][local_tab_sorted]" in line and "Tab 1|Tab 2|Tab 3|Tab 4" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "current='Tab 3'" in line and "next='Tab 4'" in line for line in logs)


def test_committed_local_tab_active_resolves_by_label_contains_when_rid_differs(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[]]
    signature = "activity||location||events"
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="",
        current_local_tab_active_label="LocationButton Location",
        current_local_tab_active_age=0,
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/activity_button", "label": "ActivityButton Activity", "left": 40, "node": {"boundsInScreen": "40,1700,300,1860"}},
                {"rid": "com.example:id/location_button", "label": "LocationButton Location", "left": 400, "node": {"boundsInScreen": "400,1700,660,1860"}},
                {"rid": "com.example:id/events_button", "label": "EventsButton Events", "left": 760, "node": {"boundsInScreen": "760,1700,1040,1860"}},
            ]
        },
        visited_local_tabs_by_signature={signature: {"com.example:id/activity_button", "com.example:id/location_button"}},
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=0,
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/activity_button", "visible_label": "ActivityButton Activity"},
        scenario_id="life_family_care_plugin",
        step_idx=28,
    )

    assert advanced is True
    assert client.select_calls[0]["name"] == "com.example:id/events_button"
    assert any("[STEP][local_tab_active_resolved]" in line and "source='committed'" in line and "LocationButton Location" in line for line in logs)
    assert any("[STEP][local_tab_progression]" in line and "current='LocationButton Location'" in line and "next='EventsButton Events'" in line for line in logs)


def test_local_tab_progression_records_pending_before_select_result(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[]]

    def fail_select(**kwargs):
        client.select_calls.append(kwargs)
        return False

    client.select = fail_select
    signature = "activity||location||events"
    state = SimpleNamespace(
        current_local_tab_signature=signature,
        current_local_tab_active_rid="com.example:id/activity_button",
        current_local_tab_active_label="ActivityButton Activity",
        current_local_tab_active_age=0,
        local_tab_candidates_by_signature={
            signature: [
                {"rid": "com.example:id/activity_button", "label": "ActivityButton Activity", "left": 40, "node": {"boundsInScreen": "40,1700,300,1860"}},
                {"rid": "com.example:id/location_button", "label": "LocationButton Location", "left": 400, "node": {"boundsInScreen": "400,1700,660,1860"}},
                {"rid": "com.example:id/events_button", "label": "EventsButton Events", "left": 760, "node": {"boundsInScreen": "760,1700,1040,1860"}},
            ]
        },
        visited_local_tabs_by_signature={signature: {"com.example:id/activity_button"}},
        pending_local_tab_signature="",
        pending_local_tab_rid="",
        pending_local_tab_label="",
        pending_local_tab_bounds="",
        pending_local_tab_age=0,
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
        recent_scroll_fallback_signatures=set(),
        last_scroll_fallback_attempted_signatures=set(),
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={"focus_view_id": "com.example:id/activity_button", "visible_label": "ActivityButton Activity"},
        scenario_id="life_family_care_plugin",
        step_idx=29,
    )

    assert advanced is False
    assert state.pending_local_tab_rid == "com.example:id/location_button"
    assert any("[STEP][local_tab_state_write]" in line and "kind='pending'" in line and "LocationButton Location" in line for line in logs)


def test_record_pending_local_tab_progression_sets_forced_navigation(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
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

    rid, label, bounds = collection_flow._record_pending_local_tab_progression(
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


def test_activate_forced_local_tab_target_taps_before_move_smart(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
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

    row = collection_flow._activate_forced_local_tab_target(
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
    assert client.tap_bounds_center_adb_calls == []
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


def test_activate_forced_local_tab_target_falls_back_to_move_smart(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([
        {
            "step_index": 31,
            "visible_label": "EventsButton Events",
            "merged_announcement": "EventsButton Events",
            "focus_view_id": "com.example:id/events_button",
            "focus_bounds": "760,1700,1040,1860",
        }
    ])
    client.tap_xy_adb = lambda **kwargs: False
    client.select = lambda **kwargs: False
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
    )

    row = collection_flow._activate_forced_local_tab_target(
        client=client,
        dev="SERIAL",
        state=state,
        step_idx=31,
        wait_seconds=0.1,
        announcement_wait_seconds=0.1,
        announcement_idle_wait_seconds=0.0,
        announcement_max_extra_wait_seconds=0.0,
    )

    assert row["focus_view_id"] == "com.example:id/events_button"
    assert client.move_focus_smart_calls[0]["direction"] == "next"
    assert state.current_local_tab_active_rid == "com.example:id/events_button"
    assert any("[STEP][local_tab_target_activate_fail]" in line and "fallback='move_smart_next'" in line for line in logs)


def test_record_pending_local_tab_progression_normalizes_dict_bounds(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
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

    _rid, _label, bounds = collection_flow._record_pending_local_tab_progression(
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


def test_activate_forced_local_tab_target_parses_string_bounds_and_uses_device_height(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([
        {
            "step_index": 32,
            "visible_label": "EventsButton Events",
            "merged_announcement": "EventsButton Events",
            "focus_view_id": "com.example:id/events_button",
            "focus_bounds": "710,2316,1050,2496",
        }
    ])
    client.dump_tree_sequence = [[{"boundsInScreen": "0,0,1080,2500"}]]
    state = SimpleNamespace(
        forced_local_tab_target_signature="tabs",
        forced_local_tab_target_rid="com.example:id/events_button",
        forced_local_tab_target_label="EventsButton Events",
        forced_local_tab_target_bounds="710,2316,1050,2496",
        forced_local_tab_attempt_count=0,
        current_local_tab_signature="tabs",
        current_local_tab_active_rid="com.example:id/location_button",
        current_local_tab_active_label="LocationButton Location",
        current_local_tab_active_age=0,
        visited_local_tabs_by_signature={"tabs": {"com.example:id/location_button"}},
        pending_local_tab_signature="tabs",
        pending_local_tab_rid="com.example:id/events_button",
        pending_local_tab_label="EventsButton Events",
        pending_local_tab_bounds="710,2316,1050,2496",
        pending_local_tab_age=0,
    )

    row = collection_flow._activate_forced_local_tab_target(
        client=client,
        dev="SERIAL",
        state=state,
        step_idx=32,
        wait_seconds=0.1,
        announcement_wait_seconds=0.1,
        announcement_idle_wait_seconds=0.0,
        announcement_max_extra_wait_seconds=0.0,
    )

    assert row["focus_view_id"] == "com.example:id/events_button"
    assert client.tap_xy_adb_calls[0]["x"] == 880
    assert client.tap_xy_adb_calls[0]["y"] == 2406
    assert any("method='tap_bounds_center'" in line and "tap='880,2406'" in line for line in logs)


def test_activate_forced_local_tab_target_parse_failure_uses_select_label(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([
        {
            "step_index": 33,
            "visible_label": "EventsButton Events",
            "merged_announcement": "EventsButton Events",
            "focus_view_id": "com.example:id/events_button",
            "focus_bounds": "760,1700,1040,1860",
        }
    ])
    client.select = lambda **kwargs: client.select_calls.append(kwargs) or (kwargs.get("type_") == "a")
    state = SimpleNamespace(
        forced_local_tab_target_signature="tabs",
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="EventsButton Events",
        forced_local_tab_target_bounds="not-a-bounds",
        forced_local_tab_attempt_count=0,
        current_local_tab_signature="tabs",
        current_local_tab_active_rid="com.example:id/location_button",
        current_local_tab_active_label="LocationButton Location",
        current_local_tab_active_age=0,
        visited_local_tabs_by_signature={"tabs": {"com.example:id/location_button"}},
        pending_local_tab_signature="tabs",
        pending_local_tab_rid="",
        pending_local_tab_label="EventsButton Events",
        pending_local_tab_bounds="not-a-bounds",
        pending_local_tab_age=0,
    )

    row = collection_flow._activate_forced_local_tab_target(
        client=client,
        dev="SERIAL",
        state=state,
        step_idx=33,
        wait_seconds=0.1,
        announcement_wait_seconds=0.1,
        announcement_idle_wait_seconds=0.0,
        announcement_max_extra_wait_seconds=0.0,
    )

    assert row["visible_label"] == "EventsButton Events"
    assert client.tap_xy_adb_calls == []
    assert client.select_calls[0]["name"] == "EventsButton Events"
    assert any("reason='bounds_parse_failed'" in line for line in logs)


def test_pending_local_tab_progression_expires_when_unresolved(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    state = SimpleNamespace(
        current_local_tab_signature="activity||location",
        current_local_tab_active_rid="com.example:id/activity_button",
        visited_local_tabs_by_signature={},
        pending_local_tab_signature="activity||location",
        pending_local_tab_rid="com.example:id/location_button",
        pending_local_tab_label="Location",
        pending_local_tab_bounds="400,1700,660,1860",
        pending_local_tab_age=2,
    )

    collection_flow._maybe_commit_pending_local_tab_progression(
        state,
        {"focus_view_id": "com.example:id/other_button", "visible_label": "Other"},
    )

    assert state.pending_local_tab_rid == ""
    assert any("[STEP][local_tab_pending_clear]" in line and "expired" in line for line in logs)


def test_apply_spatial_priority_to_candidates_prefers_higher_in_viewport():
    candidates = [
        {
            "label": "Weather information",
            "rid": "com.example:id/weather_card",
            "bounds": "40,920,1040,1200",
            "top": 920,
            "left": 40,
            "score": 900,
        },
        {
            "label": "Latest activity",
            "rid": "com.example:id/latest_activity_card",
            "bounds": "40,420,1040,760",
            "top": 420,
            "left": 40,
            "score": 500,
        },
        {
            "label": "View information",
            "rid": "com.example:id/view_information",
            "bounds": "760,420,1040,520",
            "top": 420,
            "left": 760,
            "score": 700,
        },
    ]

    ordered, reason, continuity_reason = collection_flow._apply_spatial_priority_to_candidates(
        candidates,
        row={"focus_bounds": ""},
        state=SimpleNamespace(previous_step_row={}),
    )

    assert reason == "top_to_bottom_bias"
    assert continuity_reason == ""
    assert [candidate["label"] for candidate in ordered] == [
        "Latest activity",
        "View information",
        "Weather information",
    ]


def test_apply_spatial_priority_to_candidates_prefers_continuity_from_previous_representative():
    candidates = [
        {
            "label": "Weather information",
            "rid": "com.example:id/weather_card",
            "bounds": "40,920,1040,1200",
            "top": 920,
            "left": 40,
            "score": 900,
        },
        {
            "label": "View information",
            "rid": "com.example:id/view_information",
            "bounds": "760,430,1040,520",
            "top": 430,
            "left": 760,
            "score": 950,
        },
        {
            "label": "Latest activity",
            "rid": "com.example:id/latest_activity_card",
            "bounds": "40,420,1040,760",
            "top": 420,
            "left": 40,
            "score": 700,
        },
    ]

    ordered, reason, continuity_reason = collection_flow._apply_spatial_priority_to_candidates(
        candidates,
        row={"focus_bounds": "400,1760,680,1860"},
        state=SimpleNamespace(
            previous_step_row={
                "visible_label": "Summary",
                "focus_bounds": "40,220,1040,360",
            }
        ),
    )

    assert reason == "top_to_bottom_bias"
    assert continuity_reason == "closest_next_representative"
    assert [candidate["label"] for candidate in ordered] == [
        "Latest activity",
        "View information",
        "Weather information",
    ]


def test_candidate_logical_signature_ignores_bounds_for_same_logical_object():
    candidate_a = {
        "label": "Weather information",
        "rid": "com.example:id/weather_card_title",
        "cluster_rid": "com.example:id/weather_card",
        "cluster_label": "Weather information",
        "cluster_role": "title",
        "bounds": "40,420,1040,760",
    }
    candidate_b = {
        "label": "Weather information",
        "rid": "com.example:id/weather_card_title",
        "cluster_rid": "com.example:id/weather_card",
        "cluster_label": "Weather information",
        "cluster_role": "title",
        "bounds": "40,920,1040,1260",
    }

    assert collection_flow._candidate_logical_signature(candidate_a) == collection_flow._candidate_logical_signature(candidate_b)


def test_filter_content_candidates_for_phase_rejects_visited_logical_candidates_before_ranking():
    visited_candidate = {
        "label": "Weather information",
        "rid": "com.example:id/weather_card",
        "cluster_rid": "com.example:id/weather_card",
        "cluster_label": "Weather information",
        "cluster_role": "container",
        "bounds": "40,420,1040,760",
        "representative": True,
        "passive_status": False,
        "low_value_leaf": False,
    }
    next_candidate = {
        "label": "Latest activity",
        "rid": "com.example:id/latest_activity_card",
        "cluster_rid": "com.example:id/latest_activity_card",
        "cluster_label": "Latest activity",
        "cluster_role": "container",
        "bounds": "40,820,1040,1160",
        "representative": True,
        "passive_status": False,
        "low_value_leaf": False,
    }
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        consumed_cluster_signatures=set(),
        visited_logical_signatures={collection_flow._candidate_logical_signature(visited_candidate)},
        cta_cluster_visited_rids={},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([visited_candidate, next_candidate], state=state)
    ordered, reason, _ = collection_flow._apply_spatial_priority_to_candidates(
        filtered["selection_candidates"],
        row={"focus_bounds": ""},
        state=SimpleNamespace(previous_step_row={}),
    )

    assert [candidate["label"] for candidate in filtered["visited_rejected"]] == ["Weather information"]
    assert [candidate["label"] for candidate in ordered] == ["Latest activity"]


def test_filter_content_candidates_for_phase_rejects_cluster_consumed_members():
    consumed_candidate = {
        "label": "Weather information",
        "rid": "com.example:id/weather_card",
        "cluster_rid": "com.example:id/weather_card",
        "cluster_signature": "cluster-weather",
        "cluster_label": "Weather information",
        "cluster_role": "description",
        "bounds": "40,420,1040,760",
        "representative": True,
        "passive_status": False,
        "low_value_leaf": False,
    }
    next_candidate = {
        "label": "Latest activity",
        "rid": "com.example:id/latest_activity_card",
        "cluster_rid": "com.example:id/latest_activity_card",
        "cluster_signature": "cluster-latest",
        "cluster_label": "Latest activity",
        "cluster_role": "container",
        "bounds": "40,820,1040,1160",
        "representative": True,
        "passive_status": False,
        "low_value_leaf": False,
    }
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        consumed_cluster_signatures={"cluster-weather"},
        visited_logical_signatures=set(),
        cta_cluster_visited_rids={},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([consumed_candidate, next_candidate], state=state)

    assert [candidate["label"] for candidate in filtered["cluster_consumed_rejected"]] == ["Weather information"]
    assert [candidate["label"] for candidate in filtered["selection_candidates"]] == ["Latest activity"]


def test_filter_content_candidates_for_phase_rejects_consumed_cluster_logical_child_with_new_bounds():
    consumed_root = {
        "label": "Weather information",
        "rid": "com.example:id/weather_title",
        "cluster_rid": "com.example:id/weather_card",
        "cluster_label": "Weather information",
        "cluster_role": "title",
    }
    child_candidate = {
        "label": "Weather information",
        "rid": "com.example:id/weather_description",
        "cluster_rid": "com.example:id/weather_card",
        "cluster_signature": "cluster-weather-new-bounds",
        "cluster_label": "Weather information",
        "cluster_role": "description",
        "bounds": "40,920,1040,1260",
        "representative": True,
        "passive_status": False,
        "low_value_leaf": False,
    }
    next_candidate = {
        "label": "Latest activity",
        "rid": "com.example:id/latest_activity_card",
        "cluster_rid": "com.example:id/latest_activity_card",
        "cluster_signature": "cluster-latest",
        "cluster_label": "Latest activity",
        "cluster_role": "container",
        "bounds": "40,1280,1040,1560",
        "representative": True,
        "passive_status": False,
        "low_value_leaf": False,
    }
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures={collection_flow._candidate_cluster_logical_signature(consumed_root)},
        visited_logical_signatures=set(),
        cta_cluster_visited_rids={},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([child_candidate, next_candidate], state=state)

    assert [candidate["label"] for candidate in filtered["cluster_consumed_rejected"]] == ["Weather information"]
    assert [candidate["label"] for candidate in filtered["selection_candidates"]] == ["Latest activity"]


def test_filter_content_candidates_for_phase_hard_filters_low_value_leaf():
    leaf_candidate = {
        "label": "8:00",
        "rid": "com.example:id/time_text",
        "cluster_rid": "com.example:id/activity_card",
        "cluster_label": "Activity",
        "cluster_role": "leaf",
        "bounds": "40,420,120,460",
        "representative": True,
        "passive_status": False,
        "low_value_leaf": True,
    }
    next_candidate = {
        "label": "Latest activity",
        "rid": "com.example:id/latest_activity_card",
        "cluster_rid": "com.example:id/latest_activity_card",
        "cluster_label": "Latest activity",
        "cluster_role": "container",
        "bounds": "40,820,1040,1160",
        "representative": True,
        "passive_status": False,
        "low_value_leaf": False,
    }
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        visited_logical_signatures=set(),
        cta_cluster_visited_rids={},
    )

    filtered = collection_flow._filter_content_candidates_for_phase([leaf_candidate, next_candidate], state=state)

    assert [candidate["label"] for candidate in filtered["leaf_rejected"]] == ["8:00"]
    assert [candidate["label"] for candidate in filtered["selection_candidates"]] == ["Latest activity"]


def test_collect_step_candidate_priority_groups_skips_consumed_cluster_logical_early():
    nodes = [
        {
            "text": "",
            "viewIdResourceName": "",
            "className": "android.widget.FrameLayout",
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "text": "Weather information",
                    "viewIdResourceName": "com.example:id/weather_card",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,760",
                    "children": [],
                },
                {
                    "text": "Latest activity",
                    "viewIdResourceName": "com.example:id/latest_activity_card",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,820,1040,1160",
                    "children": [],
                },
                {
                    "text": "Activity",
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
    ]

    content_candidates, bottom_strip_candidates, meta = collection_flow._collect_step_candidate_priority_groups(
        nodes,
        consumed_cluster_logical_signatures={"com.example:id/weather_card||weather information"},
    )

    assert [candidate["label"] for candidate in content_candidates] == ["Latest activity"]
    assert [candidate["label"] for candidate in bottom_strip_candidates] == ["Activity", "Location"]
    assert meta["cluster_pre_filter_skipped"] == ["Weather information"]


def test_should_suppress_row_persistence_for_low_value_leaf_when_parent_consumed():
    state = SimpleNamespace(
        current_local_tab_signature="",
        local_tab_candidates_by_signature={},
    )
    row = {
        "visible_label": "8:00",
        "merged_announcement": "8:00",
        "focus_view_id": "com.example:id/time_text",
        "focus_bounds": "40,420,120,460",
        "focus_node": {
            "clickable": False,
            "focusable": False,
            "effectiveClickable": False,
            "hasClickableDescendant": False,
            "hasFocusableDescendant": False,
        },
        "logical_signature_already_visited": False,
        "cluster_already_consumed_before_record": True,
    }

    suppress, reason = collection_flow._should_suppress_row_persistence(row=row, state=state, stop=False)

    assert suppress is True
    assert reason == "low_value_leaf_or_parent_consumed"


def test_should_suppress_row_persistence_for_low_value_leaf_without_parent_consumed():
    state = SimpleNamespace(
        current_local_tab_signature="",
        local_tab_candidates_by_signature={},
    )
    row = {
        "visible_label": "%",
        "merged_announcement": "%",
        "focus_view_id": "com.example:id/percent_text",
        "focus_bounds": "40,420,80,460",
        "focus_node": {
            "clickable": False,
            "focusable": False,
            "effectiveClickable": False,
            "hasClickableDescendant": False,
            "hasFocusableDescendant": False,
        },
        "logical_signature_already_visited": False,
        "cluster_already_consumed_before_record": False,
    }

    suppress, reason = collection_flow._should_suppress_row_persistence(row=row, state=state, stop=False)

    assert suppress is True
    assert reason == "low_value_leaf"


def test_reprioritize_persistent_bottom_strip_row_prefers_content_over_top_chrome(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                },
                {
                    "text": "More options",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/more_options",
                    "className": "android.widget.ImageButton",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "920,0,1080,120",
                    "children": [],
                },
                {
                    "text": "Add family member",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/add_family_member",
                    "className": "android.widget.Button",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "720,120,1040,220",
                    "children": [],
                },
                {
                    "text": "Device usage",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/device_usage_card",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,760",
                    "children": [],
                },
                {
                    "text": "Mobile usage",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/mobile_usage_button",
                    "className": "android.widget.Button",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,820,1040,1060",
                    "children": [],
                },
            ],
        }
    ]
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
    )
    row = {
        "focus_view_id": "com.example:id/navigate_up",
        "visible_label": "Navigate up",
        "merged_announcement": "Navigate up",
        "focus_bounds": "0,0,120,120",
        "focus_class_name": "android.widget.ImageButton",
        "focus_clickable": True,
        "focus_focusable": True,
        "focus_effective_clickable": True,
    }

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=state,
        step_idx=14,
    )

    assert updated["focus_view_id"] == "com.example:id/device_usage_card"
    assert any("[STEP][chrome_penalty]" in line and "Navigate up" in line for line in logs)
    assert any("[STEP][candidate_priority]" in line and "chrome_candidates='Navigate up|More options|Add family member'" in line for line in logs)
    assert any("reason='content_candidate_preferred_over_chrome'" in line for line in logs)


def test_maybe_select_next_local_tab_treats_top_chrome_only_as_exhausted(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"text": "Navigate up", "contentDescription": "Navigate up", "viewIdResourceName": "com.example:id/navigate_up", "className": "android.widget.ImageButton", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "0,0,120,120", "children": []},
        {"text": "More options", "contentDescription": "", "viewIdResourceName": "com.example:id/more_options", "className": "android.widget.ImageButton", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "920,0,1080,120", "children": []},
        {"text": "Add family member", "contentDescription": "", "viewIdResourceName": "com.example:id/add_family_member", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "720,120,1040,220", "children": []},
    ]]
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
                {"rid": "com.example:id/events_button", "label": "Events", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=15,
    )

    assert advanced is True
    assert any("[STEP][representative_exhausted_eval]" in line and "chrome_excluded='Navigate up|More options|Add family member'" in line and "exhausted=true" in line for line in logs)


def test_maybe_select_next_local_tab_treats_consumed_cta_and_banner_as_exhausted(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"text": "Weather information", "contentDescription": "", "viewIdResourceName": "com.example:id/weather_banner", "className": "android.widget.FrameLayout", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,420,1040,760", "children": []},
        {"text": "Later", "contentDescription": "", "viewIdResourceName": "com.example:id/first_button", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "60,780,420,880", "children": []},
        {"text": "Set up now", "contentDescription": "", "viewIdResourceName": "com.example:id/second_button", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "460,780,980,880", "children": []},
        {"text": "Active now", "contentDescription": "", "viewIdResourceName": "com.example:id/status_text", "className": "android.widget.TextView", "clickable": False, "focusable": False, "effectiveClickable": False, "visibleToUser": True, "boundsInScreen": "40,920,300,980", "children": []},
    ]]
    banner_sig = collection_flow._build_candidate_object_signature(
        rid="com.example:id/weather_banner",
        bounds="40,420,1040,760",
        label="Weather information",
    )
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures={banner_sig},
        cta_cluster_visited_rids={"cluster": {"com.example:id/first_button", "com.example:id/second_button"}},
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=16,
    )

    assert advanced is True
    assert any("[STEP][representative_exhausted_guard]" in line and "Weather information|Later|Set up now" in line for line in logs)
    assert any("[STEP][status_exhausted_excluded]" in line and "Active now" in line for line in logs)
    assert any("[STEP][representative_exhausted_eval]" in line and "exhausted=true" in line for line in logs)


def test_maybe_select_next_local_tab_keeps_false_when_new_representative_content_remains(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"text": "Weather information", "contentDescription": "", "viewIdResourceName": "com.example:id/weather_banner", "className": "android.widget.FrameLayout", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,420,1040,760", "children": []},
        {"text": "Device usage", "contentDescription": "", "viewIdResourceName": "com.example:id/device_usage_card", "className": "android.widget.FrameLayout", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,820,1040,1180", "children": []},
    ]]
    banner_sig = collection_flow._build_candidate_object_signature(
        rid="com.example:id/weather_banner",
        bounds="40,420,1040,760",
        label="Weather information",
    )
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button||com.example:id/events_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures={banner_sig},
        cta_cluster_visited_rids={},
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=17,
    )

    assert advanced is False
    assert any("[STEP][representative_exhausted_eval]" in line and "Device usage" in line and "exhausted=false" in line for line in logs)
    assert any("[STEP][exhaustion_candidates]" in line and "from_selection='Device usage'" in line for line in logs)


def test_selection_and_exhaustion_share_revisit_filtered_candidates(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"text": "", "contentDescription": "", "viewIdResourceName": "", "className": "android.widget.FrameLayout", "clickable": False, "focusable": False, "effectiveClickable": False, "visibleToUser": True, "boundsInScreen": "0,0,1080,2200", "children": [
            {"text": "Device usage", "contentDescription": "", "viewIdResourceName": "com.example:id/device_usage_card", "className": "android.widget.FrameLayout", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,420,1040,760", "children": []},
            {"text": "Steps", "contentDescription": "", "viewIdResourceName": "com.example:id/steps_card", "className": "android.widget.FrameLayout", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,820,1040,1180", "children": []},
            {"text": "Mobile usage", "contentDescription": "", "viewIdResourceName": "com.example:id/mobile_usage_button", "className": "android.widget.Button", "clickable": True, "focusable": True, "effectiveClickable": True, "visibleToUser": True, "boundsInScreen": "40,1240,1040,1440", "children": []},
        ]},
    ]]
    sig1 = collection_flow._build_candidate_object_signature(rid="com.example:id/device_usage_card", bounds="40,420,1040,760", label="Device usage")
    sig2 = collection_flow._build_candidate_object_signature(rid="com.example:id/steps_card", bounds="40,820,1040,1180", label="Steps")
    sig3 = collection_flow._build_candidate_object_signature(rid="com.example:id/mobile_usage_button", bounds="40,1240,1040,1440", label="Mobile usage")
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque([sig1, sig2, sig3], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=17,
    )

    assert advanced is True
    assert any("[STEP][selection_candidates]" in line and "rejected_by_revisit='Device usage|Steps|Mobile usage'" in line for line in logs)
    assert any("[STEP][exhaustion_candidates]" in line and "after_consumed_filter='none'" in line and "exhausted=true" in line for line in logs)
    assert not any("[STEP][candidate_mismatch]" in line for line in logs)


def test_maybe_select_next_local_tab_treats_passive_status_and_empty_state_as_exhausted(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    client = DummyClient([])
    client.dump_tree_sequence = [[
        {"text": "", "contentDescription": "", "viewIdResourceName": "", "className": "android.widget.FrameLayout", "clickable": False, "focusable": False, "effectiveClickable": False, "visibleToUser": True, "boundsInScreen": "0,0,1080,2200", "children": [
            {"text": "No activity", "contentDescription": "", "viewIdResourceName": "com.example:id/no_activity", "className": "android.widget.TextView", "clickable": False, "focusable": False, "effectiveClickable": False, "visibleToUser": True, "boundsInScreen": "40,420,340,500", "children": []},
            {"text": "Waiting", "contentDescription": "", "viewIdResourceName": "com.example:id/waiting_status", "className": "android.widget.TextView", "clickable": False, "focusable": False, "effectiveClickable": False, "visibleToUser": True, "boundsInScreen": "40,520,260,600", "children": []},
            {"text": "Activity will be measured again after 4:00 AM.", "contentDescription": "", "viewIdResourceName": "com.example:id/waiting_explanation", "className": "android.widget.TextView", "clickable": False, "focusable": False, "effectiveClickable": False, "visibleToUser": True, "boundsInScreen": "40,620,1040,760", "children": []},
        ]},
    ]]
    state = SimpleNamespace(
        current_local_tab_signature="com.example:id/activity_button||com.example:id/location_button",
        current_local_tab_active_rid="com.example:id/activity_button",
        local_tab_candidates_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": [
                {"rid": "com.example:id/activity_button", "label": "Activity", "node": {}},
                {"rid": "com.example:id/location_button", "label": "Location", "node": {}},
            ]
        },
        visited_local_tabs_by_signature={
            "com.example:id/activity_button||com.example:id/location_button": {"com.example:id/activity_button"}
        },
        fail_count=2,
        same_count=2,
        prev_fingerprint=("a", "b", "c"),
        previous_step_row={"focus_view_id": "com.example:id/activity_button"},
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        cta_cluster_visited_rids={},
    )

    advanced = collection_flow._maybe_select_next_local_tab(
        client=client,
        dev="SERIAL",
        state=state,
        row={},
        scenario_id="life_family_care_plugin",
        step_idx=18,
    )

    assert advanced is True
    assert any("[STEP][status_exhausted_excluded]" in line and "No activity" in line and "Waiting" in line for line in logs)
    assert any("[STEP][representative_exhausted_eval]" in line and "exhausted=true" in line for line in logs)


def test_reprioritize_prefers_representative_content_over_passive_status(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                    "text": "No activity",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/no_activity",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,340,500",
                    "children": [],
                },
                {
                    "text": "Waiting",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/waiting_status",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "40,520,260,600",
                    "children": [],
                },
                {
                    "text": "Latest activity View information",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/latest_activity_card",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,760,1040,1120",
                    "children": [],
                },
            ],
        }
    ]
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
    )
    row = {
        "focus_view_id": "com.example:id/waiting_status",
        "visible_label": "Waiting",
        "merged_announcement": "Waiting",
        "focus_bounds": "40,520,260,600",
        "focus_class_name": "android.widget.TextView",
        "focus_clickable": False,
        "focus_focusable": False,
        "focus_effective_clickable": False,
    }

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=state,
        step_idx=19,
    )

    assert updated["focus_view_id"] == "com.example:id/latest_activity_card"
    assert any("[STEP][candidate_priority]" in line and "status_candidates='No activity|Waiting'" in line for line in logs)
    assert any("reason='representative_content_preferred_over_passive_status'" in line for line in logs)


def test_reprioritize_attempts_focus_realign_when_focus_context_differs(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                {
                    "text": "Events",
                    "contentDescription": "",
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    client.focus_sequence = [
        {
            "text": "Device usage",
            "contentDescription": "",
            "viewIdResourceName": "com.example:id/device_usage_card",
            "className": "android.widget.FrameLayout",
            "boundsInScreen": "40,420,1040,760",
        }
    ]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=20,
    )

    assert updated["focus_view_id"] == "com.example:id/device_usage_card"
    assert client.select_calls[0]["name"] == "com.example:id/device_usage_card"
    assert any("[STEP][focus_anchor]" in line and "matched=false" in line for line in logs)
    assert any("[STEP][focus_context_mismatch]" in line and "selected='Device usage'" in line for line in logs)
    assert any("[STEP][focus_force_realign]" in line and "reason='strip_or_stale_focus_context'" in line for line in logs)
    assert any("[STEP][focus_force_realign_success]" in line and "resolved_focus='Device usage'" in line for line in logs)
    assert any("[STEP][focus_realign]" in line and "method='rid'" in line for line in logs)
    assert any("[STEP][focus_realign_success]" in line and "resolved_focus='Device usage'" in line for line in logs)


def test_reprioritize_focus_realign_failure_falls_back_safely(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                    "text": "Steps",
                    "contentDescription": "",
                    "viewIdResourceName": "com.example:id/steps_card",
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
                {
                    "text": "Events",
                    "contentDescription": "",
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    client.focus_sequence = [
        {
            "text": "Location",
            "contentDescription": "",
            "viewIdResourceName": "com.example:id/location_button",
            "className": "android.widget.Button",
            "boundsInScreen": "400,1760,680,1860",
        },
        {
            "text": "Location",
            "contentDescription": "",
            "viewIdResourceName": "com.example:id/location_button",
            "className": "android.widget.Button",
            "boundsInScreen": "400,1760,680,1860",
        },
    ]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=21,
    )

    assert updated["focus_view_id"] == "com.example:id/steps_card"
    assert any("[STEP][focus_realign_fail]" in line and "reason='no_match'" in line for line in logs)
    assert collection_flow._build_candidate_object_signature(
        rid="com.example:id/steps_card",
        bounds="40,420,1040,760",
        label="Steps",
    ) in state.failed_focus_realign_signatures


def test_force_realign_falls_back_to_label_select_when_rid_probe_misses():
    client = DummyClient([])
    scenario_perf = collection_flow.ScenarioPerfStats(scenario_id="s1", tab_name="tab")
    client.focus_sequence = [
        {
            "text": "Location",
            "contentDescription": "",
            "viewIdResourceName": "com.example:id/location_button",
            "boundsInScreen": "400,1760,680,1860",
        },
        {
            "text": "Mobile usage",
            "contentDescription": "",
            "viewIdResourceName": "com.example:id/generated_focus",
            "boundsInScreen": "40,420,1040,760",
        },
    ]
    ok, reason, focus_node = collection_flow._maybe_realign_focus_to_representative(
        row={
            "focus_view_id": "com.example:id/location_button",
            "visible_label": "Location",
            "focus_bounds": "400,1760,680,1860",
        },
        client=client,
        dev="SERIAL",
        selected_node={
            "text": "Mobile usage",
            "viewIdResourceName": "com.example:id/mobile_usage_card",
            "boundsInScreen": "40,420,1040,760",
        },
        selected_rid="com.example:id/mobile_usage_card",
        selected_label="Mobile usage",
        selected_bounds="40,420,1040,760",
        scenario_id="life_family_care_plugin",
        step_idx=22,
        mismatch_logged=True,
        force_reason="anchor_mismatch",
        scenario_perf=scenario_perf,
    )

    assert ok is True
    assert reason == "matched"
    assert focus_node["text"] == "Mobile usage"
    assert [call["type_"] for call in client.select_calls] == ["r", "a"]
    assert scenario_perf.realign_attempt_count == 2
    assert scenario_perf.realign_success_count == 1


def test_force_realign_fail_counts_attempt_but_not_success():
    client = DummyClient([])
    scenario_perf = collection_flow.ScenarioPerfStats(scenario_id="s1", tab_name="tab")
    client.focus_sequence = [
        {
            "text": "Location",
            "contentDescription": "",
            "viewIdResourceName": "com.example:id/location_button",
            "boundsInScreen": "400,1760,680,1860",
        },
        {
            "text": "Location",
            "contentDescription": "",
            "viewIdResourceName": "com.example:id/location_button",
            "boundsInScreen": "400,1760,680,1860",
        },
    ]

    ok, reason, focus_node = collection_flow._maybe_realign_focus_to_representative(
        row={
            "focus_view_id": "com.example:id/location_button",
            "visible_label": "Location",
            "focus_bounds": "400,1760,680,1860",
        },
        client=client,
        dev="SERIAL",
        selected_node={
            "text": "Mobile usage",
            "viewIdResourceName": "com.example:id/mobile_usage_card",
            "boundsInScreen": "40,420,1040,760",
        },
        selected_rid="com.example:id/mobile_usage_card",
        selected_label="Mobile usage",
        selected_bounds="40,420,1040,760",
        scenario_id="life_family_care_plugin",
        step_idx=22,
        mismatch_logged=True,
        force_reason="anchor_mismatch",
        scenario_perf=scenario_perf,
    )

    assert ok is False
    assert reason == "no_match"
    assert focus_node is None
    assert scenario_perf.realign_attempt_count == 2
    assert scenario_perf.realign_success_count == 0


def test_reprioritize_skips_recent_failed_focus_realign_target(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
        {
            "className": "android.widget.FrameLayout",
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "text": "Mobile usage",
                    "viewIdResourceName": "com.example:id/mobile_usage_card",
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
    failed_signature = collection_flow._build_candidate_object_signature(
        rid="com.example:id/mobile_usage_card",
        bounds="40,420,1040,760",
        label="Mobile usage",
    )
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        recent_focus_realign_signatures=set(),
        failed_focus_realign_signatures={failed_signature},
        cta_cluster_visited_rids={},
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=23,
    )

    assert updated["focus_view_id"] == "com.example:id/mobile_usage_card"
    assert client.select_calls == []
    assert any("[STEP][focus_realign_skip]" in line and "recent_realign_failed" in line for line in logs)


def test_reprioritize_skips_consumed_representative_for_focus_realign(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
                    "text": "Device usage",
                    "viewIdResourceName": "com.example:id/device_usage_card",
                    "className": "android.widget.FrameLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,800,1040,1140",
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    client.focus_sequence = [
        {
            "text": "Device usage",
            "viewIdResourceName": "com.example:id/device_usage_card",
            "className": "android.widget.FrameLayout",
            "boundsInScreen": "40,800,1040,1140",
        }
    ]
    weather_candidate = {
        "label": "Weather information",
        "rid": "com.example:id/weather_banner",
        "bounds": "40,420,1040,760",
    }
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures={collection_flow._candidate_object_signature(weather_candidate)},
        recent_focus_realign_signatures=set(),
        cta_cluster_visited_rids={},
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=22,
    )

    assert updated["focus_view_id"] == "com.example:id/device_usage_card"
    assert client.select_calls[0]["name"] == "com.example:id/device_usage_card"
    assert any("[STEP][focus_realign_candidates]" in line and "eligible='Device usage'" in line for line in logs)
    assert any("[STEP][focus_realign_candidates]" in line and "rejected_consumed='Weather information'" in line for line in logs)


def test_reprioritize_skips_already_resolved_focus_realign_target_in_same_phase(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    weather_signature = collection_flow._candidate_object_signature(
        {
            "label": "Weather information",
            "rid": "com.example:id/weather_banner",
            "bounds": "40,420,1040,760",
        }
    )
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        recent_focus_realign_signatures={weather_signature},
        cta_cluster_visited_rids={},
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=23,
    )

    assert updated["focus_view_id"] == "com.example:id/weather_banner"
    assert not client.select_calls
    assert any("[STEP][focus_realign_skip]" in line and "already_realign_resolved_in_current_phase" in line for line in logs)


def test_reprioritize_skips_focus_realign_when_no_eligible_target_exists(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    weather_signature = collection_flow._candidate_object_signature(
        {
            "label": "Weather information",
            "rid": "com.example:id/weather_banner",
            "bounds": "40,420,1040,760",
        }
    )
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        recent_focus_realign_signatures={weather_signature},
        cta_cluster_visited_rids={},
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=24,
    )

    assert updated["focus_view_id"] == "com.example:id/weather_banner"
    assert not client.select_calls
    assert any("[STEP][focus_realign_skip]" in line and "already_realign_resolved_in_current_phase" in line for line in logs)


def test_collect_step_candidate_priority_groups_collapses_same_card_cluster_nodes():
    nodes = [
        {
            "className": "android.widget.FrameLayout",
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "viewIdResourceName": "com.example:id/suggestion_card_container",
                    "className": "android.view.ViewGroup",
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,980",
                    "children": [
                        {
                            "text": "Want better insight into your daily life?",
                            "viewIdResourceName": "com.example:id/title",
                            "className": "android.widget.TextView",
                            "visibleToUser": True,
                            "boundsInScreen": "80,460,980,560",
                            "children": [],
                        },
                        {
                            "text": "Set up the SmartThings devices that you use.",
                            "viewIdResourceName": "com.example:id/tips_text",
                            "className": "android.widget.TextView",
                            "visibleToUser": True,
                            "boundsInScreen": "80,570,980,700",
                            "children": [],
                        },
                        {
                            "text": "Set up now",
                            "viewIdResourceName": "com.example:id/second_button",
                            "className": "android.widget.Button",
                            "clickable": True,
                            "focusable": True,
                            "effectiveClickable": True,
                            "visibleToUser": True,
                            "boundsInScreen": "620,820,980,920",
                            "children": [],
                        },
                    ],
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

    content_candidates, bottom_strip_candidates, meta = collection_flow._collect_step_candidate_priority_groups(nodes)

    assert len(content_candidates) == 1
    assert content_candidates[0]["rid"] == "com.example:id/second_button"
    assert content_candidates[0]["cluster_signature"]
    assert any("suggestion_card_container" in value for value in meta["clustered_candidates"])
    assert bottom_strip_candidates


def test_collect_step_candidate_priority_groups_prioritizes_clickable_containers():
    nodes = [
        {
            "className": "android.widget.FrameLayout",
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2400",
            "children": [
                {
                    "text": "",
                    "contentDescription": "Medication icon",
                    "viewIdResourceName": "com.example:id/medication_icon",
                    "className": "android.widget.ImageView",
                    "visibleToUser": True,
                    "boundsInScreen": "80,500,160,580",
                    "children": [],
                },
                {
                    "text": "Medication description",
                    "viewIdResourceName": "com.example:id/medication_desc",
                    "className": "android.widget.TextView",
                    "visibleToUser": True,
                    "boundsInScreen": "180,500,980,580",
                    "children": [],
                },
                {
                    "text": "Medication",
                    "viewIdResourceName": "com.example:id/medication_container",
                    "className": "android.widget.LinearLayout",
                    "clickable": True,
                    "focusable": True,
                    "effectiveClickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,460,1040,660",
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
                    "boundsInScreen": "400,2180,680,2320",
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
                    "boundsInScreen": "760,2180,1040,2320",
                    "children": [],
                },
            ],
        }
    ]

    content_candidates, _bottom_strip_candidates, meta = collection_flow._collect_step_candidate_priority_groups(nodes)
    filtered = collection_flow._filter_content_candidates_for_phase(
        content_candidates,
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            consumed_cluster_signatures=set(),
            consumed_cluster_logical_signatures=set(),
            visited_logical_signatures=set(),
            cta_cluster_visited_rids={},
        ),
    )

    assert filtered["representative_candidates"][0]["rid"] == "com.example:id/medication_container"
    assert "Medication" in meta["top_priority_container_candidates"]


def test_filter_content_candidates_applies_container_priority_for_repeated_group():
    candidates = [
        {
            "label": "Row one",
            "rid": "row_one",
            "bounds": "40,300,1040,480",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "top_priority_container": True,
        },
        {
            "label": "Row two",
            "rid": "row_two",
            "bounds": "40,520,1040,700",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "top_priority_container": True,
        },
        {
            "label": "Detail description remains lower priority",
            "rid": "detail_text",
            "bounds": "80,740,980,840",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
        },
    ]

    filtered = collection_flow._filter_content_candidates_for_phase(
        candidates,
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            consumed_cluster_signatures=set(),
            consumed_cluster_logical_signatures=set(),
            visited_logical_signatures=set(),
            cta_cluster_visited_rids={},
        ),
    )

    assert filtered["container_priority_applied"] is True
    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == ["row_one", "row_two"]


def test_filter_content_candidates_orders_active_container_group_only(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    candidates = [
        {
            "label": "Event",
            "rid": "event",
            "bounds": "40,740,1040,920",
            "score": 100,
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "top_priority_container": True,
        },
        {
            "label": "Hospital",
            "rid": "hospital",
            "bounds": "40,520,1040,700",
            "score": 100,
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "top_priority_container": True,
        },
        {
            "label": "Medication",
            "rid": "medication",
            "bounds": "40,300,1040,480",
            "score": 100,
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "top_priority_container": True,
        },
    ]

    filtered = collection_flow._filter_content_candidates_for_phase(
        candidates,
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            consumed_cluster_signatures=set(),
            consumed_cluster_logical_signatures=set(),
            visited_logical_signatures=set(),
            cta_cluster_visited_rids={},
        ),
    )

    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == [
        "medication",
        "hospital",
        "event",
    ]
    assert any("[STEP][container_group_visual_order]" in line and "ordered='Medication|Hospital|Event'" in line for line in logs)


def test_filter_content_candidates_does_not_visual_sort_different_scores():
    candidates = [
        {
            "label": "Lower visual",
            "rid": "lower_visual",
            "bounds": "40,740,1040,920",
            "score": 200,
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
        },
        {
            "label": "Higher visual",
            "rid": "higher_visual",
            "bounds": "40,300,1040,480",
            "score": 100,
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
        },
    ]

    filtered = collection_flow._filter_content_candidates_for_phase(
        candidates,
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            consumed_cluster_signatures=set(),
            consumed_cluster_logical_signatures=set(),
            visited_logical_signatures=set(),
            cta_cluster_visited_rids={},
        ),
    )

    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == [
        "lower_visual",
        "higher_visual",
    ]


def test_filter_content_candidates_keeps_mixed_candidates_for_single_container():
    candidates = [
        {
            "label": "Single action",
            "rid": "single_container",
            "bounds": "40,300,1040,500",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "top_priority_container": True,
        },
        {
            "label": "Detailed explanatory text",
            "rid": "detail_text",
            "bounds": "80,540,980,700",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
        },
    ]

    filtered = collection_flow._filter_content_candidates_for_phase(
        candidates,
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            consumed_cluster_signatures=set(),
            consumed_cluster_logical_signatures=set(),
            visited_logical_signatures=set(),
            cta_cluster_visited_rids={},
        ),
    )

    assert filtered["container_priority_applied"] is False
    assert {candidate["rid"] for candidate in filtered["representative_candidates"]} == {
        "single_container",
        "detail_text",
    }


def test_filter_content_candidates_keeps_container_priority_for_active_group_single_remaining():
    remaining_container = {
        "label": "Remaining row",
        "rid": "remaining_container",
        "bounds": "40,520,1040,700",
        "representative": True,
        "passive_status": False,
        "low_value_leaf": False,
        "top_priority_container": True,
    }
    remaining_signature = collection_flow._candidate_object_signature(remaining_container)
    candidates = [
        remaining_container,
        {
            "label": "Detail text should not re-enter while group active",
            "rid": "detail_text",
            "bounds": "80,740,980,840",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
        },
    ]

    filtered = collection_flow._filter_content_candidates_for_phase(
        candidates,
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            consumed_cluster_signatures=set(),
            consumed_cluster_logical_signatures=set(),
            visited_logical_signatures=set(),
            cta_cluster_visited_rids={},
            active_container_group_remaining={remaining_signature},
            active_container_group_labels={remaining_signature: "Remaining row"},
            active_container_group_signature="tabs",
        ),
    )

    assert filtered["container_priority_applied"] is True
    assert filtered["container_priority_reason"] == "active_group"
    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == ["remaining_container"]


def test_record_recent_representative_signature_updates_active_container_group(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    consumed_signature = collection_flow._build_candidate_object_signature(
        rid="row_one",
        bounds="40,300,1040,480",
        label="Row one",
    )
    remaining_signature = collection_flow._build_candidate_object_signature(
        rid="row_two",
        bounds="40,520,1040,700",
        label="Row two",
    )
    state = SimpleNamespace(
        recent_representative_signatures=deque([], maxlen=5),
        consumed_representative_signatures=set(),
        visited_logical_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        active_container_group_remaining={consumed_signature, remaining_signature},
        active_container_group_labels={
            consumed_signature: "Row one",
            remaining_signature: "Row two",
        },
        active_container_group_signature="tabs",
    )

    collection_flow._record_recent_representative_signature(
        state,
        {
            "focus_view_id": "row_one",
            "focus_bounds": "40,300,1040,480",
            "visible_label": "Row one",
            "move_result": "moved",
        },
    )

    assert state.active_container_group_remaining == {remaining_signature}
    assert any("[STEP][container_group_progress]" in line and "Row two" in line for line in logs)


def test_filter_content_candidates_skips_completed_container_group(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    containers = [
        {
            "label": "Row one",
            "rid": "row_one",
            "bounds": "40,300,1040,480",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "top_priority_container": True,
        },
        {
            "label": "Row two",
            "rid": "row_two",
            "bounds": "40,520,1040,700",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "top_priority_container": True,
        },
    ]
    group_signature = collection_flow._container_group_signature(containers)
    candidates = [
        *containers,
        {
            "label": "Other content",
            "rid": "other_content",
            "bounds": "80,760,980,900",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
        },
    ]

    filtered = collection_flow._filter_content_candidates_for_phase(
        candidates,
        state=SimpleNamespace(
            recent_representative_signatures=[],
            consumed_representative_signatures=set(),
            consumed_cluster_signatures=set(),
            consumed_cluster_logical_signatures=set(),
            visited_logical_signatures=set(),
            cta_cluster_visited_rids={},
            active_container_group_remaining=set(),
            active_container_group_labels={},
            active_container_group_signature="",
            completed_container_groups={group_signature},
        ),
    )

    assert [candidate["rid"] for candidate in filtered["representative_candidates"]] == ["other_content"]
    assert len(filtered["completed_container_rejected"]) == 2
    assert any("[STEP][container_group_skip]" in line and "group_already_consumed" in line for line in logs)


def test_filter_content_candidates_for_phase_excludes_consumed_cluster():
    cluster_signature = "com.example:id/suggestion_card_container||40,420,1040,980||"
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        consumed_cluster_signatures={cluster_signature},
        cta_cluster_visited_rids={},
    )
    candidates = [
        {
            "label": "Want better insight into your daily life?",
            "rid": "com.example:id/title",
            "bounds": "80,460,980,560",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "cluster_signature": cluster_signature,
        },
        {
            "label": "Set up the SmartThings devices that you use.",
            "rid": "com.example:id/tips_text",
            "bounds": "80,570,980,700",
            "representative": True,
            "passive_status": False,
            "low_value_leaf": False,
            "cluster_signature": cluster_signature,
        },
    ]

    filtered = collection_flow._filter_content_candidates_for_phase(candidates, state=state)

    assert filtered["selection_candidates"] == []
    assert filtered["exhaustion_candidates"] == []
    assert len(filtered["cluster_consumed_rejected"]) == 1


def test_reprioritize_skips_realign_for_already_resolved_cluster(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
        {
            "className": "android.widget.FrameLayout",
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "viewIdResourceName": "com.example:id/suggestion_card_container",
                    "className": "android.view.ViewGroup",
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,980",
                    "children": [
                        {
                            "text": "Want better insight into your daily life?",
                            "viewIdResourceName": "com.example:id/title",
                            "className": "android.widget.TextView",
                            "visibleToUser": True,
                            "boundsInScreen": "80,460,980,560",
                            "children": [],
                        },
                        {
                            "text": "Set up the SmartThings devices that you use.",
                            "viewIdResourceName": "com.example:id/tips_text",
                            "className": "android.widget.TextView",
                            "visibleToUser": True,
                            "boundsInScreen": "80,570,980,700",
                            "children": [],
                        },
                        {
                            "text": "Set up now",
                            "viewIdResourceName": "com.example:id/second_button",
                            "className": "android.widget.Button",
                            "clickable": True,
                            "focusable": True,
                            "effectiveClickable": True,
                            "visibleToUser": True,
                            "boundsInScreen": "620,820,980,920",
                            "children": [],
                        },
                    ],
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
    cluster_signature = collection_flow._build_candidate_object_signature(
        rid="com.example:id/suggestion_card_container",
        bounds="40,420,1040,980",
        label="",
    )
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        recent_focus_realign_signatures=set(),
        consumed_cluster_signatures=set(),
        recent_focus_realign_clusters={cluster_signature},
        cta_cluster_visited_rids={},
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content", "scenario_id": "life_family_care_plugin"},
        state=state,
        step_idx=25,
    )

    assert updated["focus_view_id"] == "com.example:id/second_button"
    assert not client.select_calls
    assert any("[STEP][focus_realign_skip]" in line and "cluster_already_realign_resolved" in line for line in logs)


def test_cluster_representative_prefers_container_over_title_when_actionable_missing(monkeypatch):
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    nodes = [
        {
            "className": "android.widget.FrameLayout",
            "visibleToUser": True,
            "boundsInScreen": "0,0,1080,2200",
            "children": [
                {
                    "viewIdResourceName": "com.example:id/info_card_container",
                    "className": "android.widget.FrameLayout",
                    "hasClickableDescendant": True,
                    "visibleToUser": True,
                    "boundsInScreen": "40,420,1040,980",
                    "children": [
                        {
                            "text": "Device usage",
                            "viewIdResourceName": "com.example:id/title",
                            "className": "android.widget.TextView",
                            "visibleToUser": True,
                            "boundsInScreen": "80,460,980,560",
                            "children": [],
                        },
                        {
                            "text": "Usage this week",
                            "viewIdResourceName": "com.example:id/description",
                            "className": "android.widget.TextView",
                            "visibleToUser": True,
                            "boundsInScreen": "80,580,980,720",
                            "children": [],
                        },
                    ],
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
    client = DummyClient([])
    client.dump_tree_sequence = [nodes]
    state = SimpleNamespace(
        recent_representative_signatures=[],
        consumed_representative_signatures=set(),
        local_tab_candidates_by_signature={},
        visited_local_tabs_by_signature={},
        current_local_tab_signature="",
        current_local_tab_active_rid="",
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

    updated = collection_flow._maybe_reprioritize_persistent_bottom_strip_row(
        row=row,
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_type": "content"},
        state=state,
        step_idx=26,
    )

    assert updated["focus_view_id"] == "com.example:id/info_card_container"
    assert any(
        "[STEP][cluster_representative]" in line
        and ("container_preferred" in line or "descendant_actionable_preferred" in line)
        for line in logs
    )


def test_select_better_cluster_representative_falls_back_from_title_to_container():
    title_candidate = {
        "label": "Steps",
        "rid": "com.example:id/title",
        "bounds": "80,460,980,560",
        "cluster_signature": "com.example:id/info_card_container||40,420,1040,980||",
        "cluster_role": "title",
    }
    container_candidate = {
        "label": "Steps Overview of your steps",
        "rid": "com.example:id/info_card_container",
        "bounds": "40,420,1040,980",
        "cluster_signature": "com.example:id/info_card_container||40,420,1040,980||",
        "cluster_role": "container",
        "representative": True,
        "score": 500000,
        "top": 420,
    }
    title_candidate["cluster_members"] = [
        title_candidate,
        {
            "label": "Overview of your steps",
            "rid": "com.example:id/description",
            "bounds": "80,580,980,720",
            "cluster_signature": title_candidate["cluster_signature"],
            "cluster_role": "description",
            "representative": True,
            "score": 200000,
            "top": 580,
        },
        container_candidate,
    ]
    state = SimpleNamespace(
        cluster_title_fallback_applied=set(),
    )
    row = {
        "move_result": "failed",
    }

    fallback = collection_flow._select_better_cluster_representative(
        selected_candidate=title_candidate,
        state=state,
        row=row,
    )

    assert fallback is not None
    assert fallback["rid"] == "com.example:id/info_card_container"


def test_select_better_cluster_representative_returns_none_without_better_candidate():
    title_candidate = {
        "label": "Steps",
        "rid": "com.example:id/title",
        "bounds": "80,460,980,560",
        "cluster_signature": "com.example:id/title||80,460,980,560||steps",
        "cluster_role": "title",
        "cluster_members": [],
    }
    title_candidate["cluster_members"] = [title_candidate]
    state = SimpleNamespace(
        cluster_title_fallback_applied=set(),
    )
    fallback = collection_flow._select_better_cluster_representative(
        selected_candidate=title_candidate,
        state=state,
        row={"move_result": "failed"},
    )

    assert fallback is None


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


def test_open_scenario_card_entry_keeps_normal_traversal_after_special_state_grace(monkeypatch):
    monkeypatch.setattr(collection_flow, "_verify_fresh_life_list_state", lambda *_args, **_kwargs: (True, "ready"))
    monkeypatch.setattr(collection_flow, "recover_to_start_state", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        collection_flow,
        "_analyze_current_state",
        lambda *_args, **_kwargs: {"package_signature_present": True, "app_bar_hits": 1},
    )
    monkeypatch.setattr(collection_flow, "_is_special_state_route_allowed", lambda *_args, **_kwargs: True)
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
        {"viewIdResourceName": "com.example:id/title", "text": "Family Care"},
        {"viewIdResourceName": "com.example:id/member", "text": "Add family member"},
        {"viewIdResourceName": "com.example:id/profile", "text": "View profile"},
    ]
    tab_cfg = {
        **_base_tab_cfg(),
        "scenario_id": "life_family_care_plugin",
        "entry_type": "card",
        "verify_tokens": ["family care"],
        "special_state_tokens": ["family care"],
        "special_state_cta_tokens": ["start"],
        "special_state_handling": "back_after_read",
    }
    monkeypatch.setattr(
        collection_flow,
        "_classify_special_post_open_state",
        lambda *_args, **_kwargs: (
            True,
            "setup_needed_or_empty_state",
            {
                "signals": ["long_intro", "cta", "top_chrome_intro_cta"],
                "special_hits": ["family care"],
                "cta_hits": ["start"],
                "verify_hit": True,
                "long_intro_like": True,
                "low_content_diversity": False,
                "cta_pair": False,
                "top_chrome_intro_cta": True,
                "intro_focus_like": False,
                "handling": "back_after_read",
            },
        ),
    )

    ok = collection_flow.open_scenario(client, "SERIAL", tab_cfg)

    assert ok is True
    summary = getattr(client, "last_start_open_summary", {})
    assert summary.get("entry_contract_reason") == "success_verified"
    assert summary.get("special_state_detected") is not True
    assert client.back_calls == 0


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


def test_has_global_nav_signals_requires_multiple_main_menu_resource_ids():
    plugin_like_nodes = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/plugin_bottom_tab_one", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/plugin_bottom_tab_two", "visibleToUser": True},
        {"text": "Routines", "visibleToUser": True},
    ]

    visible, hits = collection_flow._has_global_nav_signals(plugin_like_nodes)

    assert visible is False
    assert hits == 0

    mixed_nodes = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_services", "visibleToUser": True},
    ]
    visible_single, hits_single = collection_flow._has_global_nav_signals(mixed_nodes)
    assert visible_single is False
    assert hits_single == 1

    strong_nodes = [
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_services", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices", "visibleToUser": True},
    ]
    visible_strong, hits_strong = collection_flow._has_global_nav_signals(strong_nodes)
    assert visible_strong is True
    assert hits_strong == 2


def test_life_root_state_snapshot_does_not_mark_life_selected_from_label_only():
    nodes = [
        {"text": "Life", "contentDescription": "selected", "selected": True, "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_devices", "visibleToUser": True},
        {"viewIdResourceName": "com.samsung.android.oneconnect:id/menu_more", "visibleToUser": True},
    ]

    snapshot = collection_flow._life_root_state_snapshot(nodes)

    assert snapshot["life_selected"] is False


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


def test_xml_entry_strict_target_gating_ignores_descendant_body_sentence(monkeypatch):
    class XmlClient:
        def __init__(self):
            self.tap_calls = []

        def tap_xy_adb(self, dev, x, y):
            self.tap_calls.append((dev, x, y))
            return True

    nodes = [
        {
            "text": "Air Care",
            "contentDescription": "",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/service_card",
            "className": "android.widget.FrameLayout",
            "clickable": True,
            "focusable": False,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "0,260,1080,840",
            "children": [
                {
                    "text": "Monitor air quality and comfort in real time",
                    "contentDescription": "",
                    "viewIdResourceName": "",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "48,650,1032,780",
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
        tab_cfg={"scenario_id": "life_home_monitor_plugin"},
        target=r"(?i)\b(home\s*monitor)\b",
        type_="card",
        max_scroll_search_steps=0,
        step_wait_seconds=0.2,
        transition_fast_path=False,
    )

    assert ok is False
    assert reason == "target_not_found_after_scroll"
    assert client.tap_calls == []
    assert any("target_candidates=0" in line for line in logs)


def test_xml_entry_strict_target_gating_accepts_short_descendant_title_phrase(monkeypatch):
    class XmlClient:
        def __init__(self):
            self.tap_calls = []

        def tap_xy_adb(self, dev, x, y):
            self.tap_calls.append((dev, x, y))
            return True

    nodes = [
        {
            "text": "",
            "contentDescription": "",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/service_card",
            "className": "android.widget.FrameLayout",
            "clickable": True,
            "focusable": False,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "0,260,1080,840",
            "children": [
                {
                    "text": "Home Monitor",
                    "contentDescription": "",
                    "viewIdResourceName": "",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "48,320,540,380",
                    "children": [],
                },
                {
                    "text": "Monitor air quality and comfort in real time",
                    "contentDescription": "",
                    "viewIdResourceName": "",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "48,650,1032,780",
                    "children": [],
                },
            ],
        }
    ]
    logs = []
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", lambda **kwargs: (nodes, "ok"))
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **kwargs: (True, "transition_confirmed"))
    monkeypatch.setattr(collection_flow, "log", lambda message, level="NORMAL": logs.append(message))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = XmlClient()
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "life_home_monitor_plugin"},
        target=r"(?i)\b(home\s*monitor)\b",
        type_="card",
        max_scroll_search_steps=0,
        step_wait_seconds=0.2,
        transition_fast_path=False,
    )

    assert ok is True
    assert reason == "xml_entry_success"
    assert client.tap_calls
    assert any("matched_phrase='home monitor'" in line for line in logs if "[XMLENTRY][select" in line)


def test_xml_entry_strict_target_gating_rejects_descendant_match_when_own_text_conflicts(monkeypatch):
    class XmlClient:
        def __init__(self):
            self.tap_calls = []

        def tap_xy_adb(self, dev, x, y):
            self.tap_calls.append((dev, x, y))
            return True

    nodes = [
        {
            "text": "Air Care",
            "contentDescription": "",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/service_card",
            "className": "android.widget.FrameLayout",
            "clickable": True,
            "focusable": False,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "0,260,1080,840",
            "children": [
                {
                    "text": "Home Monitor",
                    "contentDescription": "",
                    "viewIdResourceName": "",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": False,
                    "boundsInScreen": "48,320,540,380",
                    "children": [],
                }
            ],
        }
    ]
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", lambda **kwargs: (nodes, "ok"))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = XmlClient()
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "life_home_monitor_plugin"},
        target=r"(?i)\b(home\s*monitor)\b",
        type_="card",
        max_scroll_search_steps=0,
        step_wait_seconds=0.2,
        transition_fast_path=False,
    )

    assert ok is False
    assert reason == "target_not_found_after_scroll"
    assert client.tap_calls == []


def test_xml_entry_strict_target_gating_rejects_partial_multiword_descendant_phrase(monkeypatch):
    class XmlClient:
        def __init__(self):
            self.tap_calls = []

        def tap_xy_adb(self, dev, x, y):
            self.tap_calls.append((dev, x, y))
            return True

    nodes = [
        {
            "text": "",
            "contentDescription": "",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/service_card",
            "className": "android.widget.FrameLayout",
            "clickable": True,
            "focusable": False,
            "effectiveClickable": True,
            "visibleToUser": True,
            "boundsInScreen": "0,260,1080,840",
            "children": [
                {
                    "text": "Smart Monitor",
                    "contentDescription": "",
                    "viewIdResourceName": "",
                    "className": "android.widget.TextView",
                    "clickable": False,
                    "focusable": False,
                    "effectiveClickable": False,
                    "visibleToUser": True,
                    "boundsInScreen": "48,320,540,380",
                    "children": [],
                }
            ],
        }
    ]
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", lambda **kwargs: (nodes, "ok"))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    client = XmlClient()
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "life_home_monitor_plugin"},
        target=r"(?i)\b(home\s*monitor)\b",
        type_="card",
        max_scroll_search_steps=0,
        step_wait_seconds=0.2,
        transition_fast_path=False,
    )

    assert ok is False
    assert reason == "target_not_found_after_scroll"
    assert client.tap_calls == []


def _phase_ordering_state():
    return SimpleNamespace(
        forced_local_tab_target_rid="",
        forced_local_tab_target_label="",
        post_realign_pending_steps=0,
        previous_step_row=_anchor_row(),
        last_fingerprint="anchor",
        fingerprint_repeat_count=0,
        fail_count=0,
        same_count=0,
        prev_fingerprint=("anchor", "anchor", "id.anchor"),
        recent_fingerprint_history=deque(),
        recent_semantic_fingerprint_history=deque(),
        recent_representative_signatures=deque(maxlen=8),
        content_phase_grace_steps=0,
        scroll_state=SimpleNamespace(
            recent_scroll_fallback_signatures=set(),
            last_scroll_fallback_attempted_signatures=set(),
            scroll_ready_retry_counts={},
            pending_scroll_ready_cluster_signature="",
        ),
        cta_grace_signature="",
        cta_descend_grace_remaining=0,
        cta_cluster_nodes_by_signature={},
        cta_cluster_visited_rids={},
        cta_cluster_committed_rid={},
        stop_triggered=False,
        stop_reason="",
        stop_step=-1,
        stall_escape_attempted=False,
        main_step_index_by_fingerprint={},
        expanded_overlay_entries=set(),
    )


def _phase_ordering_stop_inputs(**overrides):
    values = {
        "terminal_signal": False,
        "same_like_count": 0,
        "no_progress": False,
        "scenario_type": "content",
        "is_global_nav_only_scenario": False,
        "is_global_nav": False,
        "global_nav_reason": "",
        "after_realign": False,
        "recent_repeat": False,
        "bounded_two_card_loop": False,
        "semantic_same_like": False,
        "recent_duplicate": False,
        "recent_duplicate_distance": 0,
        "recent_semantic_duplicate": False,
        "recent_semantic_duplicate_distance": 0,
        "recent_semantic_unique_count": 1,
        "repeat_class": "",
        "loop_classification": "",
        "strict_duplicate": False,
        "semantic_duplicate": False,
        "hard_no_progress": False,
        "soft_no_progress": False,
        "no_progress_class": "",
        "overlay_realign_grace_active": False,
        "min_step_gate_blocked": False,
        "realign_grace_suppressed": False,
        "repeat_stop_hit": False,
        "eval_reason": "",
    }
    values.update(overrides)
    return values


def _run_phase_ordering_main_loop(monkeypatch, *, row, stop=False, reason=""):
    events = []
    state = _phase_ordering_state()
    client = DummyClient([row])
    phase_ctx = SimpleNamespace(
        tab_cfg=_base_tab_cfg(max_steps=1),
        rows=[],
        all_rows=[],
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        checkpoint_every=100,
        main_step_wait_seconds=0,
        main_announcement_wait_seconds=0,
        main_announcement_idle_wait_seconds=0,
        main_announcement_max_extra_wait_seconds=0,
        state=state,
    )

    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda _client, _dev, row, _base: row)
    monkeypatch.setattr(collection_flow, "_record_pending_scroll_ready_move", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_maybe_reprioritize_persistent_bottom_strip_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_promote_row_to_cta_child", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_progress_row_to_cta_sibling", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_record_recent_representative_signature", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(collection_flow, "_annotate_row_quality", lambda row, **kwargs: ("fp", 1))
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **kwargs: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **kwargs: (stop, 0, 0, reason, ("fp", "", ""), {}))
    monkeypatch.setattr(
        collection_flow,
        "_build_stop_evaluation_inputs",
        lambda **kwargs: _phase_ordering_stop_inputs(
            no_progress=reason == "repeat_no_progress",
            strict_duplicate=reason == "repeat_no_progress",
            repeat_stop_hit=reason == "repeat_no_progress",
            eval_reason=reason,
        ),
    )
    monkeypatch.setattr(collection_flow, "_maybe_apply_cta_pending_grace", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "_maybe_apply_scroll_ready_continue", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "classify_step_result", lambda *args, **kwargs: {})
    monkeypatch.setattr(collection_flow, "_format_stop_explain_log_fields", lambda **kwargs: "")
    monkeypatch.setattr(collection_flow, "_log_repeat_stop_debug", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_should_suppress_row_persistence", lambda **kwargs: (False, ""))
    monkeypatch.setattr(collection_flow, "_overlay_phase", lambda **kwargs: SimpleNamespace(post_realign_pending_steps_delta=0))
    monkeypatch.setattr(collection_flow, "save_excel_with_perf", lambda *args, **kwargs: None)

    def fake_select_next_local_tab(**kwargs):
        events.append((kwargs["step_idx"], kwargs["row"].get("visible_label", "")))
        return False

    monkeypatch.setattr(collection_flow, "_maybe_select_next_local_tab", fake_select_next_local_tab)
    collection_flow._main_loop_phase(client, "SERIAL", phase_ctx)
    return events, phase_ctx


def test_stop_then_cta_grace_allows_continue_then_stops_after_exhaust():
    state = _phase_ordering_state()
    row = _card_container_with_cta_children_row(1)
    stop_inputs = _phase_ordering_stop_inputs(strict_duplicate=True, no_progress=True)

    stop, reason, applied = collection_flow._maybe_apply_cta_pending_grace(
        row=row,
        previous_row=_card_container_row(0),
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs=stop_inputs,
        state=state,
        step_idx=1,
        scenario_id="cta_phase_ordering",
    )
    assert (stop, reason, applied) == (False, "", True)
    assert state.cta_descend_grace_remaining == 1

    stop, reason, applied = collection_flow._maybe_apply_cta_pending_grace(
        row=row,
        previous_row=_card_container_row(0),
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs=stop_inputs,
        state=state,
        step_idx=2,
        scenario_id="cta_phase_ordering",
    )
    assert (stop, reason, applied) == (False, "", True)
    assert state.cta_descend_grace_remaining == 0

    stop, reason, applied = collection_flow._maybe_apply_cta_pending_grace(
        row=row,
        previous_row=_card_container_row(0),
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs=stop_inputs,
        state=state,
        step_idx=3,
        scenario_id="cta_phase_ordering",
    )
    assert (stop, reason, applied) == (True, "repeat_no_progress", False)
    assert state.cta_descend_grace_remaining == 0


def test_scroll_ready_continue_does_not_override_terminal_stop():
    row = {
        **_main_row(1),
        "scroll_ready_state": True,
        "scroll_ready_cluster_signature": "cluster:medication",
    }
    for stop_inputs in (
        _phase_ordering_stop_inputs(terminal_signal=True, no_progress=True),
        _phase_ordering_stop_inputs(is_global_nav=True, no_progress=True),
    ):
        state = _phase_ordering_state()
        stop, reason, applied = collection_flow._maybe_apply_scroll_ready_continue(
            row=row,
            stop=True,
            reason="repeat_no_progress",
            stop_eval_inputs=stop_inputs,
            state=state,
            step_idx=1,
            scenario_id="scroll_phase_ordering",
        )
        assert (stop, reason, applied) == (True, "repeat_no_progress", False)
        assert state.scroll_state.pending_scroll_ready_cluster_signature == ""
        assert state.scroll_state.scroll_ready_retry_counts == {}


def test_local_tab_transition_only_on_exhaustion_or_repeat_stop(monkeypatch):
    viewport_row = {
        **_main_row(1),
        "viewport_exhausted_eval_result": True,
        "scroll_fallback_resumed_content": False,
    }
    viewport_events, _ = _run_phase_ordering_main_loop(monkeypatch, row=viewport_row, stop=False, reason="")
    assert len(viewport_events) == 1

    repeat_row = {
        **_main_row(1),
        "viewport_exhausted_eval_result": False,
        "scroll_fallback_resumed_content": False,
    }
    repeat_events, _ = _run_phase_ordering_main_loop(
        monkeypatch,
        row=repeat_row,
        stop=True,
        reason="repeat_no_progress",
    )
    assert len(repeat_events) == 1

    terminal_row = {
        **_main_row(1),
        "viewport_exhausted_eval_result": False,
        "scroll_fallback_resumed_content": False,
    }
    terminal_events, _ = _run_phase_ordering_main_loop(
        monkeypatch,
        row=terminal_row,
        stop=True,
        reason="global_nav_exit",
    )
    assert terminal_events == []


def test_row_suppression_applied_before_persistence(monkeypatch):
    captured = {}
    state = _phase_ordering_state()
    client = DummyClient([{**_main_row(1), "low_value_leaf_row": True}])
    phase_ctx = SimpleNamespace(
        tab_cfg=_base_tab_cfg(max_steps=1),
        rows=[],
        all_rows=[],
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        checkpoint_every=100,
        main_step_wait_seconds=0,
        main_announcement_wait_seconds=0,
        main_announcement_idle_wait_seconds=0,
        main_announcement_max_extra_wait_seconds=0,
        state=state,
    )

    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda _client, _dev, row, _base: row)
    monkeypatch.setattr(collection_flow, "_record_pending_scroll_ready_move", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_maybe_reprioritize_persistent_bottom_strip_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_promote_row_to_cta_child", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_progress_row_to_cta_sibling", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_record_recent_representative_signature", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(collection_flow, "_annotate_row_quality", lambda row, **kwargs: ("fp", 1))
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **kwargs: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **kwargs: (False, 0, 0, "", ("fp", "", ""), {}))
    monkeypatch.setattr(collection_flow, "_build_stop_evaluation_inputs", lambda **kwargs: _phase_ordering_stop_inputs())
    monkeypatch.setattr(collection_flow, "_maybe_apply_cta_pending_grace", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "_maybe_apply_scroll_ready_continue", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "classify_step_result", lambda *args, **kwargs: {})
    monkeypatch.setattr(collection_flow, "_format_stop_explain_log_fields", lambda **kwargs: "")
    monkeypatch.setattr(collection_flow, "_overlay_phase", lambda **kwargs: SimpleNamespace(post_realign_pending_steps_delta=0))
    monkeypatch.setattr(collection_flow, "save_excel_with_perf", lambda *args, **kwargs: None)

    def fake_suppress(**kwargs):
        captured["row"] = kwargs["row"]
        return True, "phase_ordering_suppressed"

    monkeypatch.setattr(collection_flow, "_should_suppress_row_persistence", fake_suppress)
    collection_flow._main_loop_phase(client, "SERIAL", phase_ctx)

    assert phase_ctx.rows == []
    assert phase_ctx.all_rows == []
    assert captured["row"]["row_persist_suppressed"] is True
    assert captured["row"]["row_persist_suppressed_reason"] == "phase_ordering_suppressed"


def _row_quality_state():
    return SimpleNamespace(
        recent_representative_signatures=deque(maxlen=8),
        consumed_representative_signatures=set(),
        visited_logical_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        active_container_group_remaining=set(),
        active_container_group_labels={},
        active_container_group_signature="",
        completed_container_groups=set(),
    )


def _row_quality_row(idx=1, **overrides):
    row = {
        **_main_row(idx),
        "visible_label": "Medication",
        "normalized_visible_label": "medication",
        "merged_announcement": "Medication",
        "focus_view_id": "id.medication",
        "focus_bounds": "10,20,110,120",
        "focus_cluster_signature": "cluster:medication",
        "focus_cluster_logical_signature": "cluster:logical:medication",
    }
    row.update(overrides)
    return row


def test_row_quality_records_successful_representative_signature():
    state = _row_quality_state()
    row = _row_quality_row(move_result="moved")
    object_signature = collection_flow._build_row_object_signature(row)
    logical_signature = collection_flow._row_logical_signature(row)

    collection_flow._record_recent_representative_signature(state, row)

    assert object_signature in state.recent_representative_signatures
    assert object_signature in state.consumed_representative_signatures
    assert logical_signature in state.visited_logical_signatures
    assert "cluster:medication" in state.consumed_cluster_signatures
    assert "cluster:logical:medication" in state.consumed_cluster_logical_signatures
    assert row["logical_signature"] == logical_signature
    assert row["logical_signature_already_visited"] is False
    assert row["cluster_already_consumed_before_record"] is False


def test_row_quality_does_not_record_failed_or_no_progress_row():
    for move_result in ("failed", "no_progress"):
        state = _row_quality_state()
        row = _row_quality_row(move_result=move_result)
        logical_signature = collection_flow._row_logical_signature(row)

        collection_flow._record_recent_representative_signature(state, row)

        assert logical_signature not in state.visited_logical_signatures
        assert row["logical_signature"] == logical_signature
        assert row["logical_signature_already_visited"] is False


def test_row_quality_updates_fingerprint_repeat_count():
    recent_history = deque()
    recent_semantic_history = deque()
    first = _row_quality_row(idx=1)
    last_fingerprint, repeat_count = collection_flow._annotate_row_quality(
        first,
        last_fingerprint="",
        fingerprint_repeat_count=0,
        recent_fingerprint_history=recent_history,
        recent_semantic_fingerprint_history=recent_semantic_history,
    )
    second = _row_quality_row(idx=2)
    last_fingerprint, repeat_count = collection_flow._annotate_row_quality(
        second,
        last_fingerprint=last_fingerprint,
        fingerprint_repeat_count=repeat_count,
        recent_fingerprint_history=recent_history,
        recent_semantic_fingerprint_history=recent_semantic_history,
    )
    third = _row_quality_row(idx=3, visible_label="Hospital", normalized_visible_label="hospital", merged_announcement="Hospital")
    _last_fingerprint, reset_count = collection_flow._annotate_row_quality(
        third,
        last_fingerprint=last_fingerprint,
        fingerprint_repeat_count=repeat_count,
        recent_fingerprint_history=recent_history,
        recent_semantic_fingerprint_history=recent_semantic_history,
    )

    assert first["fingerprint_repeat_count"] == 0
    assert second["fingerprint_repeat_count"] == 1
    assert second["is_duplicate_step"] is True
    assert reset_count == 0
    assert third["fingerprint_repeat_count"] == 0
    assert third["is_duplicate_step"] is False


def test_row_quality_marks_recent_duplicate_before_stop_inputs():
    row = _row_quality_row(idx=5)
    fingerprint = collection_flow.build_row_fingerprint(row)
    recent_history = deque([(2, fingerprint)])

    collection_flow._annotate_row_quality(
        row,
        last_fingerprint="different",
        fingerprint_repeat_count=0,
        recent_fingerprint_history=recent_history,
        recent_semantic_fingerprint_history=deque(),
    )
    stop_inputs = collection_flow._build_stop_evaluation_inputs(
        stop_details={
            "reason": "repeat_no_progress",
            "recent_duplicate": row["is_recent_duplicate_step"],
            "recent_duplicate_distance": row["recent_duplicate_distance"],
        },
        row=row,
        tab_cfg=_base_tab_cfg(),
    )

    assert row["is_recent_duplicate_step"] is True
    assert row["recent_duplicate_distance"] == 3
    assert stop_inputs["recent_duplicate"] is True
    assert stop_inputs["recent_duplicate_distance"] == 3


def test_row_quality_marks_semantic_duplicate():
    row = _row_quality_row(
        idx=8,
        focus_view_id="id.changed",
        focus_bounds="20,30,120,130",
    )
    semantic_fingerprint = collection_flow.build_row_semantic_fingerprint(row)
    recent_semantic_history = deque([(4, semantic_fingerprint)])

    collection_flow._annotate_row_quality(
        row,
        last_fingerprint="different",
        fingerprint_repeat_count=0,
        recent_fingerprint_history=deque(),
        recent_semantic_fingerprint_history=recent_semantic_history,
    )

    assert row["is_recent_semantic_duplicate_step"] is True
    assert row["recent_semantic_duplicate_distance"] == 4
    assert row["recent_semantic_duplicate_of_step"] == 4


def test_row_quality_sets_low_value_leaf_flag_before_persistence(monkeypatch):
    captured = {}
    row = _main_row(9)
    row.update(
        {
            "visible_label": "%",
            "normalized_visible_label": "%",
            "merged_announcement": "%",
            "focus_bounds": "0,0,20,20",
            "focus_node": {
                "clickable": False,
                "focusable": False,
                "effectiveClickable": False,
                "hasClickableDescendant": False,
                "hasFocusableDescendant": False,
            },
        }
    )

    def fake_suppress(**kwargs):
        captured["low_value_leaf_row"] = kwargs["row"].get("low_value_leaf_row")
        return False, ""

    monkeypatch.setattr(collection_flow, "_should_suppress_row_persistence", fake_suppress)
    collection_flow._apply_row_persistence_phase_impl(
        row=row,
        state=_phase_ordering_state(),
        rows=[],
        all_rows=[],
        scenario_perf=None,
        step_idx=9,
        stop=False,
        checkpoint_every=100,
        output_path="unused.xlsx",
        log_fn=lambda _message: None,
        make_fingerprint_fn=lambda _row: ("fingerprint", "label", "rid"),
        save_fn=lambda *args, **kwargs: None,
    )

    assert captured["low_value_leaf_row"] is True
    assert row["low_value_leaf_row"] is True


def test_row_quality_mismatch_detection_runs_after_quality_annotation(monkeypatch):
    events = []
    row = _main_row(10)
    state = _phase_ordering_state()
    phase_ctx = SimpleNamespace(
        tab_cfg=_base_tab_cfg(max_steps=1),
        rows=[],
        all_rows=[],
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        checkpoint_every=100,
        main_step_wait_seconds=0,
        main_announcement_wait_seconds=0,
        main_announcement_idle_wait_seconds=0,
        main_announcement_max_extra_wait_seconds=0,
        state=state,
    )

    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda _client, _dev, row, _base: row)
    monkeypatch.setattr(collection_flow, "_apply_scroll_ready_record_phase", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_maybe_reprioritize_persistent_bottom_strip_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_promote_row_to_cta_child", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_progress_row_to_cta_sibling", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_record_recent_representative_signature", lambda *_args, **_kwargs: None)

    def fake_annotate(row, **kwargs):
        events.append("annotate")
        row["fingerprint"] = "fp"
        row["normalized_fingerprint"] = "nfp"
        row["quality_ready"] = True
        return "fp", 0

    def fake_detect(**kwargs):
        events.append(("detect", kwargs["row"].get("quality_ready", False)))
        return [], []

    monkeypatch.setattr(collection_flow, "_annotate_row_quality", fake_annotate)
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", fake_detect)
    monkeypatch.setattr(collection_flow, "should_stop", lambda **kwargs: (False, 0, 0, "", ("fp", "", ""), {}))
    monkeypatch.setattr(collection_flow, "_build_stop_evaluation_inputs", lambda **kwargs: _phase_ordering_stop_inputs())
    monkeypatch.setattr(collection_flow, "_maybe_apply_cta_pending_grace", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "_maybe_apply_scroll_ready_continue", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "_maybe_select_next_local_tab", lambda **kwargs: False)
    monkeypatch.setattr(collection_flow, "classify_step_result", lambda *args, **kwargs: {})
    monkeypatch.setattr(collection_flow, "_format_stop_explain_log_fields", lambda **kwargs: "")
    monkeypatch.setattr(collection_flow, "_log_repeat_stop_debug", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_should_suppress_row_persistence", lambda **kwargs: (False, ""))
    monkeypatch.setattr(collection_flow, "_overlay_phase", lambda **kwargs: SimpleNamespace(post_realign_pending_steps_delta=0))
    monkeypatch.setattr(collection_flow, "save_excel_with_perf", lambda *args, **kwargs: None)

    collection_flow._main_loop_phase(DummyClient([row]), "SERIAL", phase_ctx)

    assert events == ["annotate", ("detect", True)]


def _run_step_collection_main_loop(
    monkeypatch,
    *,
    collect_row=None,
    forced_rid="",
    forced_label="",
    forced_activation_row=None,
    post_realign_pending_steps=0,
    capture_fn=None,
):
    captured = {}
    state = _phase_ordering_state()
    state.forced_local_tab_target_rid = forced_rid
    state.forced_local_tab_target_label = forced_label
    state.post_realign_pending_steps = post_realign_pending_steps
    client = DummyClient([collect_row or _main_row(31)])
    phase_ctx = SimpleNamespace(
        tab_cfg=_base_tab_cfg(max_steps=1),
        rows=[],
        all_rows=[],
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        checkpoint_every=100,
        main_step_wait_seconds=0,
        main_announcement_wait_seconds=0,
        main_announcement_idle_wait_seconds=0,
        main_announcement_max_extra_wait_seconds=0,
        state=state,
    )

    if forced_rid or forced_label:
        monkeypatch.setattr(collection_flow, "_activate_forced_local_tab_target", lambda **kwargs: forced_activation_row)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", capture_fn or (lambda _client, _dev, row, _base: row))
    monkeypatch.setattr(collection_flow, "_apply_scroll_ready_record_phase", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_maybe_reprioritize_persistent_bottom_strip_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_promote_row_to_cta_child", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_progress_row_to_cta_sibling", lambda **kwargs: kwargs["row"])

    def capture_quality(**kwargs):
        captured["row"] = dict(kwargs["row"])
        captured["row_ref"] = kwargs["row"]
        return [], []

    monkeypatch.setattr(collection_flow, "_apply_row_quality_phase", capture_quality)
    monkeypatch.setattr(collection_flow, "should_stop", lambda **kwargs: (False, 0, 0, "", ("fp", "", ""), {}))
    monkeypatch.setattr(collection_flow, "_build_stop_evaluation_inputs", lambda **kwargs: _phase_ordering_stop_inputs())
    monkeypatch.setattr(collection_flow, "_maybe_apply_cta_pending_grace", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "_maybe_apply_scroll_ready_continue", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "_maybe_select_next_local_tab", lambda **kwargs: False)
    monkeypatch.setattr(collection_flow, "_apply_stop_explain_phase", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_apply_row_persistence_phase", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_overlay_phase", lambda **kwargs: SimpleNamespace(post_realign_pending_steps_delta=0))

    collection_flow._main_loop_phase(client, "SERIAL", phase_ctx)
    return captured, client, phase_ctx


def test_step_collection_uses_forced_local_tab_activation_before_collect_focus(monkeypatch):
    forced_row = _main_row(31)
    forced_row.update({"visible_label": "Forced tab", "focus_view_id": "id.forced"})

    captured, client, _phase_ctx = _run_step_collection_main_loop(
        monkeypatch,
        collect_row=_main_row(32),
        forced_rid="id.forced",
        forced_label="Forced tab",
        forced_activation_row=forced_row,
    )

    assert client.collect_focus_step_calls == []
    assert captured["row"]["visible_label"] == "Forced tab"
    assert captured["row"]["focus_view_id"] == "id.forced"


def test_step_collection_sets_forced_local_tab_row_fields(monkeypatch):
    forced_row = _main_row(33)
    forced_row.update({"visible_label": "EventsButton Events", "focus_view_id": "id.events"})

    captured, _client, _phase_ctx = _run_step_collection_main_loop(
        monkeypatch,
        forced_rid="id.events",
        forced_label="EventsButton Events",
        forced_activation_row=forced_row,
    )
    row = captured["row"]

    assert row["forced_local_tab_navigation"] is True
    assert row["forced_local_tab_target"] == "EventsButton Events"
    assert row["tab_name"] == "홈"
    assert row["context_type"] == "main"
    assert row["status"] == "OK"
    assert row["stop_reason"] == ""


def test_step_collection_falls_back_to_collect_focus_when_forced_activation_returns_none(monkeypatch):
    fallback_row = _main_row(34)
    fallback_row.update({"visible_label": "Fallback row", "focus_view_id": "id.fallback"})

    captured, client, _phase_ctx = _run_step_collection_main_loop(
        monkeypatch,
        collect_row=fallback_row,
        forced_rid="id.events",
        forced_label="EventsButton Events",
        forced_activation_row=None,
    )

    assert len(client.collect_focus_step_calls) == 1
    assert captured["row"]["visible_label"] == "Fallback row"
    assert "forced_local_tab_navigation" not in captured["row"]


def test_step_collection_sets_base_fields_on_normal_row(monkeypatch):
    captured, client, _phase_ctx = _run_step_collection_main_loop(
        monkeypatch,
        collect_row=_main_row(35),
    )
    row = captured["row"]

    assert len(client.collect_focus_step_calls) == 1
    assert row["tab_name"] == "홈"
    assert row["context_type"] == "main"
    assert row["parent_step_index"] == ""
    assert row["overlay_entry_label"] == ""
    assert row["status"] == "OK"
    assert row["stop_reason"] == ""
    assert row["scenario_type"] == "content"
    assert isinstance(row["step_elapsed_sec"], float)
    assert row["step_elapsed_sec"] >= 0


def test_step_collection_sets_overlay_recovery_status_when_pending(monkeypatch):
    pending, _client, _phase_ctx = _run_step_collection_main_loop(
        monkeypatch,
        collect_row=_main_row(36),
        post_realign_pending_steps=2,
    )
    not_pending, _client, _phase_ctx = _run_step_collection_main_loop(
        monkeypatch,
        collect_row=_main_row(37),
        post_realign_pending_steps=0,
    )

    assert pending["row"]["overlay_recovery_status"] == "after_realign"
    assert not_pending["row"]["overlay_recovery_status"] == ""


def test_step_collection_crop_timing_sentinel_removed_after_capture(monkeypatch):
    crop_seen = {}

    def capture_fn(_client, _dev, row, _base):
        crop_seen["sentinel_present"] = "_step_mono_start" in row
        crop_seen["sentinel_value"] = row.get("_step_mono_start")
        row["crop_image_path"] = "crop.png"
        return row

    captured, _client, _phase_ctx = _run_step_collection_main_loop(
        monkeypatch,
        collect_row=_main_row(38),
        capture_fn=capture_fn,
    )
    row = captured["row"]

    assert crop_seen["sentinel_present"] is True
    assert isinstance(crop_seen["sentinel_value"], float)
    assert "_step_mono_start" not in row
    assert isinstance(row["step_total_elapsed_sec"], float)
    assert row["step_total_elapsed_sec"] >= row["step_elapsed_sec"]


def test_step_collection_sets_crop_image_from_capture(monkeypatch):
    def capture_fn(_client, _dev, row, _base):
        row["crop_image"] = "CAPTURED"
        row["crop_image_path"] = "captured.png"
        return row

    captured, _client, _phase_ctx = _run_step_collection_main_loop(
        monkeypatch,
        collect_row=_main_row(39),
        capture_fn=capture_fn,
    )

    assert captured["row"]["crop_image"] == "CAPTURED"
    assert captured["row"]["crop_image_path"] == "captured.png"


def _stop_explain_row(**overrides):
    row = {
        **_main_row(7),
        "move_result": "moved",
        "scroll_ready_cluster_signature": "cluster:medication",
        "focus_cluster_signature": "cluster:focus",
        "scroll_ready_state": False,
    }
    row.update(overrides)
    return row


def test_stop_explain_phase_sets_result_fields(monkeypatch):
    debug_calls = []
    monkeypatch.setattr(collection_flow, "_log_repeat_stop_debug", lambda **kwargs: debug_calls.append(kwargs))
    row = _stop_explain_row()

    collection_flow._apply_stop_explain_phase(
        row=row,
        previous_row=_anchor_row(),
        tab_cfg={"scenario_id": "stop_explain"},
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs=_phase_ordering_stop_inputs(no_progress=True, strict_duplicate=True, eval_reason="repeat_no_progress"),
        mismatch_reasons=[],
        cta_descend_applied=False,
        scroll_ready_continue_applied=False,
        local_tab_transition_applied=False,
        step_idx=7,
    )

    assert row["final_result"]
    assert "failure_reason" in row
    assert "traversal_result" in row
    assert row["is_global_nav"] is False
    assert row["global_nav_reason"] == ""
    assert len(debug_calls) == 1


def test_stop_explain_phase_handles_non_stop_row(monkeypatch):
    debug_calls = []
    monkeypatch.setattr(collection_flow, "_log_repeat_stop_debug", lambda **kwargs: debug_calls.append(kwargs))
    row = _stop_explain_row()

    collection_flow._apply_stop_explain_phase(
        row=row,
        previous_row=_anchor_row(),
        tab_cfg={"scenario_id": "stop_explain"},
        stop=False,
        reason="",
        stop_eval_inputs=_phase_ordering_stop_inputs(eval_reason=""),
        mismatch_reasons=[],
        cta_descend_applied=False,
        scroll_ready_continue_applied=False,
        local_tab_transition_applied=False,
        step_idx=7,
    )

    assert row["traversal_result"].startswith("PASS")
    assert row["failure_reason"] == ""
    assert row["is_global_nav"] is False
    assert debug_calls == []


def test_stop_explain_phase_preserves_global_nav_reason():
    row = _stop_explain_row()

    collection_flow._apply_stop_explain_phase(
        row=row,
        previous_row=_anchor_row(),
        tab_cfg={"scenario_id": "stop_explain"},
        stop=True,
        reason="global_nav_exit",
        stop_eval_inputs=_phase_ordering_stop_inputs(
            is_global_nav=True,
            global_nav_reason="matched_bottom_tab",
            terminal_signal=True,
            eval_reason="global_nav_exit",
        ),
        mismatch_reasons=[],
        cta_descend_applied=False,
        scroll_ready_continue_applied=False,
        local_tab_transition_applied=False,
        step_idx=7,
    )

    assert row["is_global_nav"] is True
    assert row["global_nav_reason"] == "matched_bottom_tab"
    assert "traversal_result" in row


def test_stop_explain_phase_calls_repeat_debug_only_for_repeat_reason(monkeypatch):
    debug_calls = []
    monkeypatch.setattr(collection_flow, "_log_repeat_stop_debug", lambda **kwargs: debug_calls.append(kwargs))

    collection_flow._apply_stop_explain_phase(
        row=_stop_explain_row(),
        previous_row=_anchor_row(),
        tab_cfg={"scenario_id": "stop_explain"},
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs=_phase_ordering_stop_inputs(no_progress=True, eval_reason="repeat_no_progress"),
        mismatch_reasons=[],
        cta_descend_applied=False,
        scroll_ready_continue_applied=False,
        local_tab_transition_applied=False,
        step_idx=7,
    )
    collection_flow._apply_stop_explain_phase(
        row=_stop_explain_row(),
        previous_row=_anchor_row(),
        tab_cfg={"scenario_id": "stop_explain"},
        stop=True,
        reason="terminal",
        stop_eval_inputs=_phase_ordering_stop_inputs(terminal_signal=True, eval_reason="terminal"),
        mismatch_reasons=[],
        cta_descend_applied=False,
        scroll_ready_continue_applied=False,
        local_tab_transition_applied=False,
        step_idx=8,
    )

    assert len(debug_calls) == 1
    assert debug_calls[0]["stop_eval_inputs"]["no_progress"] is True


def test_stop_explain_phase_uses_injected_log_and_format_functions(monkeypatch):
    logs = []
    format_calls = []
    debug_calls = []
    monkeypatch.setattr(collection_flow, "_log_repeat_stop_debug", lambda **kwargs: debug_calls.append(kwargs))

    def format_fn(**kwargs):
        format_calls.append(kwargs)
        return "formatted_fields"

    row = _stop_explain_row(scroll_ready_state=True)
    collection_flow._apply_stop_explain_phase_impl(
        row=row,
        previous_row=_anchor_row(),
        tab_cfg={"scenario_id": "stop_explain"},
        stop=True,
        reason="repeat_no_progress",
        stop_eval_inputs=_phase_ordering_stop_inputs(no_progress=True, strict_duplicate=True, eval_reason="repeat_no_progress"),
        mismatch_reasons=[],
        cta_descend_applied=False,
        scroll_ready_continue_applied=False,
        local_tab_transition_applied=False,
        step_idx=7,
        log_fn=lambda message: logs.append(message),
        format_fn=format_fn,
    )

    assert format_calls == [
        {
            "stop_eval_inputs": _phase_ordering_stop_inputs(
                no_progress=True,
                strict_duplicate=True,
                eval_reason="repeat_no_progress",
            ),
            "decision": "stop",
        }
    ]
    assert len(logs) == 2
    assert len(debug_calls) == 1


def _scroll_ready_record_state(*, pending="", retry_counts=None):
    return SimpleNamespace(
        scroll_state=SimpleNamespace(
            pending_scroll_ready_cluster_signature=pending,
            scroll_ready_retry_counts=dict(retry_counts or {}),
        )
    )


def _scroll_ready_record_callbacks(*, normalized_result="moved"):
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


def test_scroll_ready_record_phase_records_pending_cluster():
    state = _scroll_ready_record_state(
        pending="cluster:medication",
        retry_counts={"cluster:medication": 1, "cluster:hospital": 1},
    )
    row = {"move_result": "moved", "visible_label": "Medication"}
    calls, log_fn, truncate_fn, normalize_fn = _scroll_ready_record_callbacks(normalized_result="moved")

    collection_flow._apply_scroll_ready_record_phase_impl(
        row=row,
        state=state,
        scenario_id="life_family_care_plugin",
        step_idx=18,
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert state.scroll_state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_state.scroll_ready_retry_counts == {"cluster:hospital": 1}
    assert calls["normalize"] == [row]
    assert len(calls["log"]) == 1
    assert ("cluster:medication", 120) in calls["truncate"]


def test_scroll_ready_record_phase_ignores_non_scroll_ready_row():
    state = _scroll_ready_record_state(pending="", retry_counts={"cluster:medication": 1})
    row = {"move_result": "moved", "visible_label": "Medication", "scroll_ready_state": False}
    calls, log_fn, truncate_fn, normalize_fn = _scroll_ready_record_callbacks(normalized_result="moved")

    collection_flow._apply_scroll_ready_record_phase_impl(
        row=row,
        state=state,
        scenario_id="life_family_care_plugin",
        step_idx=19,
        log_fn=log_fn,
        truncate_fn=truncate_fn,
        normalize_move_result_fn=normalize_fn,
        scroll_ready_version="test-version",
    )

    assert state.scroll_state.pending_scroll_ready_cluster_signature == ""
    assert state.scroll_state.scroll_ready_retry_counts == {"cluster:medication": 1}
    assert calls == {"log": [], "truncate": [], "normalize": []}


def test_scroll_ready_record_phase_preserves_existing_retry_state():
    state = _scroll_ready_record_state(
        pending="cluster:medication",
        retry_counts={"cluster:medication": 2, "cluster:hospital": 1},
    )
    row = {"move_result": "failed", "visible_label": "Medication"}

    collection_flow._apply_scroll_ready_record_phase(
        row=row,
        state=state,
        scenario_id="life_family_care_plugin",
        step_idx=20,
    )

    assert state.scroll_state.pending_scroll_ready_cluster_signature == "cluster:medication"
    assert state.scroll_state.scroll_ready_retry_counts == {
        "cluster:medication": 2,
        "cluster:hospital": 1,
    }


def test_scroll_ready_record_phase_wrapper_delegates_to_impl(monkeypatch):
    calls = []

    def fake_impl(**kwargs):
        calls.append(kwargs)
        return "sentinel"

    monkeypatch.setattr(collection_flow, "_apply_scroll_ready_record_phase_impl", fake_impl)
    state = _scroll_ready_record_state()
    row = {"move_result": "moved"}

    result = collection_flow._apply_scroll_ready_record_phase(
        row=row,
        state=state,
        scenario_id="life_family_care_plugin",
        step_idx=21,
    )

    assert result == "sentinel"
    assert len(calls) == 1
    call = calls[0]
    assert call["row"] is row
    assert call["state"] is state
    assert call["scenario_id"] == "life_family_care_plugin"
    assert call["step_idx"] == 21
    assert call["log_fn"] is collection_flow.log
    assert call["truncate_fn"] is collection_flow._truncate_debug_text
    assert call["normalize_move_result_fn"] is collection_flow.normalize_move_result
    assert call["scroll_ready_version"] == collection_flow.COLLECTION_FLOW_SCROLL_READY_VERSION


class _PersistencePerf:
    def __init__(self):
        self.rows = []

    def record_row(self, row):
        self.rows.append(row)


class _OverlayPerf(_PersistencePerf):
    def __init__(self):
        super().__init__()
        self.overlay_count = 0
        self.realign_attempt_count = 0
        self.realign_success_count = 0


class _TrackingList(list):
    def __init__(self, name, events):
        super().__init__()
        self.name = name
        self.events = events

    def append(self, item):
        self.events.append((f"{self.name}.append", item.get("step_index")))
        super().append(item)


def _run_persistence_main_loop(
    monkeypatch,
    *,
    row,
    stop=False,
    reason="",
    suppress=False,
    suppress_reason="",
    checkpoint_every=100,
    scenario_perf=None,
    overlay_fn=None,
    rows=None,
    all_rows=None,
):
    state = _phase_ordering_state()
    phase_ctx = SimpleNamespace(
        tab_cfg=_base_tab_cfg(max_steps=1),
        rows=[] if rows is None else rows,
        all_rows=[] if all_rows is None else all_rows,
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=scenario_perf,
        checkpoint_every=checkpoint_every,
        main_step_wait_seconds=0,
        main_announcement_wait_seconds=0,
        main_announcement_idle_wait_seconds=0,
        main_announcement_max_extra_wait_seconds=0,
        state=state,
    )
    save_calls = []
    overlay_calls = []

    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda _client, _dev, row, _base: row)
    monkeypatch.setattr(collection_flow, "_apply_scroll_ready_record_phase", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_maybe_reprioritize_persistent_bottom_strip_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_promote_row_to_cta_child", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_maybe_progress_row_to_cta_sibling", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(collection_flow, "_record_recent_representative_signature", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(collection_flow, "_annotate_row_quality", lambda row, **kwargs: ("fp", 1))
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **kwargs: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **kwargs: (stop, 0, 0, reason, ("fp", "", ""), {}))
    monkeypatch.setattr(collection_flow, "_build_stop_evaluation_inputs", lambda **kwargs: _phase_ordering_stop_inputs(eval_reason=reason))
    monkeypatch.setattr(collection_flow, "_maybe_apply_cta_pending_grace", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "_maybe_apply_scroll_ready_continue", lambda **kwargs: (kwargs["stop"], kwargs["reason"], False))
    monkeypatch.setattr(collection_flow, "_maybe_select_next_local_tab", lambda **kwargs: False)
    monkeypatch.setattr(collection_flow, "classify_step_result", lambda *args, **kwargs: {})
    monkeypatch.setattr(collection_flow, "_format_stop_explain_log_fields", lambda **kwargs: "")
    monkeypatch.setattr(collection_flow, "_log_repeat_stop_debug", lambda **kwargs: None)
    monkeypatch.setattr(collection_flow, "_should_suppress_row_persistence", lambda **kwargs: (suppress, suppress_reason))

    def fake_save(*args, **kwargs):
        save_calls.append((args, kwargs))

    monkeypatch.setattr(collection_flow, "save_excel_with_perf", fake_save)

    def default_overlay(**kwargs):
        overlay_calls.append(
            {
                "rows_len": len(kwargs["rows"]),
                "all_rows_len": len(kwargs["all_rows"]),
                "row": kwargs["row"],
            }
        )
        return SimpleNamespace(post_realign_pending_steps_delta=0)

    monkeypatch.setattr(collection_flow, "_overlay_phase", overlay_fn or default_overlay)
    collection_flow._main_loop_phase(DummyClient([row]), "SERIAL", phase_ctx)
    return phase_ctx, save_calls, overlay_calls


def test_row_persistence_suppressed_row_does_not_update_anything(monkeypatch):
    perf = _PersistencePerf()
    row = _main_row(1)

    phase_ctx, save_calls, _overlay_calls = _run_persistence_main_loop(
        monkeypatch,
        row=row,
        suppress=True,
        suppress_reason="phase_test_suppressed",
        scenario_perf=perf,
    )

    assert phase_ctx.rows == []
    assert phase_ctx.all_rows == []
    assert perf.rows == []
    assert phase_ctx.state.main_step_index_by_fingerprint == {}
    assert save_calls == []


def test_row_persistence_non_suppressed_row_updates_all_targets(monkeypatch):
    perf = _PersistencePerf()
    row = _main_row(2)

    phase_ctx, _save_calls, _overlay_calls = _run_persistence_main_loop(
        monkeypatch,
        row=row,
        scenario_perf=perf,
    )

    assert len(phase_ctx.rows) == 1
    assert phase_ctx.all_rows == phase_ctx.rows
    assert perf.rows == phase_ctx.rows
    assert phase_ctx.rows[0]["visible_label"] == "item2"
    assert phase_ctx.state.main_step_index_by_fingerprint == {
        collection_flow.make_main_fingerprint(phase_ctx.rows[0]): 1
    }


def test_row_persistence_stop_row_not_suppressed():
    row = {
        **_main_row(3),
        "low_value_leaf_row": True,
        "logical_signature_already_visited": True,
        "cluster_already_consumed_before_record": True,
    }

    suppress, reason = collection_flow._should_suppress_row_persistence(
        row=row,
        state=_phase_ordering_state(),
        stop=True,
    )

    assert (suppress, reason) == (False, "")


def test_row_persistence_records_fingerprint_index_after_append(monkeypatch):
    events = []
    rows = _TrackingList("rows", events)
    all_rows = _TrackingList("all_rows", events)
    row = _main_row(4)

    def fake_fingerprint(saved_row):
        events.append(("fingerprint", len(rows), len(all_rows)))
        return ("fingerprint", "label", "rid")

    monkeypatch.setattr(collection_flow, "make_main_fingerprint", fake_fingerprint)
    phase_ctx, _save_calls, _overlay_calls = _run_persistence_main_loop(
        monkeypatch,
        row=row,
        rows=rows,
        all_rows=all_rows,
    )

    assert events[:3] == [
        ("rows.append", 4),
        ("all_rows.append", 4),
        ("fingerprint", 1, 1),
    ]
    assert phase_ctx.state.main_step_index_by_fingerprint == {
        ("fingerprint", "label", "rid"): 1
    }


def test_row_persistence_checkpoint_save_only_on_conditions(monkeypatch):
    _, no_save_calls, _ = _run_persistence_main_loop(
        monkeypatch,
        row=_main_row(5),
        checkpoint_every=100,
    )
    assert no_save_calls == []

    _, interval_save_calls, _ = _run_persistence_main_loop(
        monkeypatch,
        row=_main_row(6),
        checkpoint_every=1,
    )
    assert len(interval_save_calls) == 1

    _, stop_save_calls, _ = _run_persistence_main_loop(
        monkeypatch,
        row=_main_row(7),
        stop=True,
        reason="terminal",
        checkpoint_every=100,
    )
    assert len(stop_save_calls) == 1


def test_overlay_called_after_row_persistence(monkeypatch):
    row = _main_row(8)
    phase_ctx, _save_calls, overlay_calls = _run_persistence_main_loop(monkeypatch, row=row)

    assert len(phase_ctx.rows) == 1
    assert phase_ctx.all_rows == phase_ctx.rows
    assert phase_ctx.rows[0]["visible_label"] == "item8"
    assert overlay_calls == [{"rows_len": 1, "all_rows_len": 1, "row": phase_ctx.rows[0]}]


def test_overlay_runs_even_when_stop_triggered(monkeypatch):
    row = _main_row(16)
    phase_ctx, _save_calls, overlay_calls = _run_persistence_main_loop(
        monkeypatch,
        row=row,
        stop=True,
        reason="terminal",
    )

    assert phase_ctx.state.stop_triggered is True
    assert phase_ctx.rows[0]["status"] == "END"
    assert overlay_calls == [{"rows_len": 1, "all_rows_len": 1, "row": phase_ctx.rows[0]}]


def test_overlay_skips_already_expanded_entry(monkeypatch):
    row = _main_row(17)
    tab_cfg = _base_tab_cfg(max_steps=1)
    fingerprint = collection_flow.make_overlay_entry_fingerprint(tab_cfg["tab_name"], row)
    expanded = {fingerprint}
    calls = []

    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda row, tab_cfg: (True, "test_overlay"))
    monkeypatch.setattr(collection_flow, "_execute_overlay_for_candidate", lambda **kwargs: calls.append(kwargs))

    result = collection_flow._overlay_phase(
        client=DummyClient([]),
        dev="SERIAL",
        tab_cfg=tab_cfg,
        row=row,
        rows=[],
        all_rows=[],
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        main_step_index_by_fingerprint={},
        expanded_overlay_entries=expanded,
    )

    assert calls == []
    assert result.candidate_checked is True
    assert result.classification == "unchanged"
    assert expanded == {fingerprint}


def test_overlay_success_adds_to_expanded_entries(monkeypatch):
    rows = []
    all_rows = []
    row = _main_row(18)
    tab_cfg = _base_tab_cfg(max_steps=1)
    expanded = set()
    overlay_row = {**_main_row(180), "context_type": "overlay"}

    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda row, tab_cfg: (True, "test_overlay"))
    monkeypatch.setattr(collection_flow, "classify_post_click_result", lambda **kwargs: ("overlay", _main_row(181)))

    def fake_expand_overlay(**kwargs):
        kwargs["rows"].append(overlay_row)
        kwargs["all_rows"].append(overlay_row)
        return [overlay_row]

    monkeypatch.setattr(collection_flow, "expand_overlay", fake_expand_overlay)
    monkeypatch.setattr(collection_flow, "realign_focus_after_overlay", lambda **kwargs: {"entry_reached": False})

    result = collection_flow._overlay_phase(
        client=DummyClient([]),
        dev="SERIAL",
        tab_cfg=tab_cfg,
        row=row,
        rows=rows,
        all_rows=all_rows,
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        main_step_index_by_fingerprint={},
        expanded_overlay_entries=expanded,
    )

    assert result.classification == "overlay"
    assert expanded == {collection_flow.make_overlay_entry_fingerprint(tab_cfg["tab_name"], row)}


def test_overlay_touch_failure_skips_expand_and_realign(monkeypatch):
    class TouchFailClient(DummyClient):
        def touch(self, **kwargs):
            self.touch_calls.append(kwargs)
            return False

    calls = {"expand": 0, "realign": 0}
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda row, tab_cfg: (True, "test_overlay"))
    monkeypatch.setattr(collection_flow, "expand_overlay", lambda **kwargs: calls.__setitem__("expand", calls["expand"] + 1))
    monkeypatch.setattr(collection_flow, "realign_focus_after_overlay", lambda **kwargs: calls.__setitem__("realign", calls["realign"] + 1))

    result = collection_flow._overlay_phase(
        client=TouchFailClient([]),
        dev="SERIAL",
        tab_cfg=_base_tab_cfg(max_steps=1),
        row=_main_row(19),
        rows=[],
        all_rows=[],
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        main_step_index_by_fingerprint={},
        expanded_overlay_entries=set(),
    )

    assert result.classification == "unchanged"
    assert calls == {"expand": 0, "realign": 0}


def test_overlay_realign_delta_applied_and_decremented(monkeypatch):
    row = _main_row(20)
    tab_cfg = _base_tab_cfg(max_steps=1)
    overlay_row = {**_main_row(200), "context_type": "overlay"}

    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda row, tab_cfg: (True, "test_overlay"))
    monkeypatch.setattr(collection_flow, "classify_post_click_result", lambda **kwargs: ("overlay", _main_row(201)))

    def fake_expand_overlay(**kwargs):
        kwargs["rows"].append(overlay_row)
        kwargs["all_rows"].append(overlay_row)
        return [overlay_row]

    monkeypatch.setattr(collection_flow, "expand_overlay", fake_expand_overlay)
    monkeypatch.setattr(collection_flow, "realign_focus_after_overlay", lambda **kwargs: {"entry_reached": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})

    result = collection_flow._overlay_phase(
        client=DummyClient([]),
        dev="SERIAL",
        tab_cfg=tab_cfg,
        row=row,
        rows=[],
        all_rows=[],
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        main_step_index_by_fingerprint={},
        expanded_overlay_entries=set(),
    )
    assert result.post_realign_pending_steps_delta == 2

    phase_ctx, _save_calls, _overlay_calls = _run_persistence_main_loop(
        monkeypatch,
        row=_main_row(21),
        overlay_fn=lambda **kwargs: result,
    )
    assert phase_ctx.state.post_realign_pending_steps == 1


def test_overlay_perf_counters_updated_correctly(monkeypatch):
    rows = []
    all_rows = []
    perf = _OverlayPerf()
    overlay_row = {**_main_row(220), "context_type": "overlay"}

    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda row, tab_cfg: (True, "test_overlay"))
    monkeypatch.setattr(collection_flow, "classify_post_click_result", lambda **kwargs: ("overlay", _main_row(221)))

    def fake_expand_overlay(**kwargs):
        kwargs["rows"].append(overlay_row)
        kwargs["all_rows"].append(overlay_row)
        return [overlay_row]

    monkeypatch.setattr(collection_flow, "expand_overlay", fake_expand_overlay)
    monkeypatch.setattr(collection_flow, "realign_focus_after_overlay", lambda **kwargs: {"entry_reached": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})

    result = collection_flow._overlay_phase(
        client=DummyClient([]),
        dev="SERIAL",
        tab_cfg=_base_tab_cfg(max_steps=1),
        row=_main_row(22),
        rows=rows,
        all_rows=all_rows,
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=perf,
        main_step_index_by_fingerprint={},
        expanded_overlay_entries=set(),
    )

    assert result.classification == "overlay"
    assert perf.overlay_count == 1
    assert perf.realign_attempt_count == 1
    assert perf.realign_success_count == 1
    assert perf.rows == [overlay_row]


def test_overlay_blocked_in_global_nav_only_scenario(monkeypatch):
    calls = []
    tab_cfg = _global_nav_tab_cfg(max_steps=1)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda row, tab_cfg: calls.append((row, tab_cfg)) or (True, "test_overlay"))

    result = collection_flow._overlay_phase(
        client=DummyClient([]),
        dev="SERIAL",
        tab_cfg=tab_cfg,
        row=_main_row(23),
        rows=[],
        all_rows=[],
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        main_step_index_by_fingerprint={},
        expanded_overlay_entries=set(),
    )

    assert calls == []
    assert result.candidate_checked is False
    assert result.candidate_reason == "blocked_by_global_nav_only"


def test_overlay_rows_added_to_both_rows_and_all_rows(monkeypatch):
    rows = []
    all_rows = []
    entry_row = _main_row(9)
    overlay_row = {**_main_row(90), "context_type": "overlay"}

    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda row, tab_cfg: (True, "test_overlay"))
    monkeypatch.setattr(collection_flow, "classify_post_click_result", lambda **kwargs: ("overlay", _main_row(91)))

    def fake_expand_overlay(**kwargs):
        kwargs["rows"].append(overlay_row)
        kwargs["all_rows"].append(overlay_row)
        return [overlay_row]

    monkeypatch.setattr(collection_flow, "expand_overlay", fake_expand_overlay)
    monkeypatch.setattr(collection_flow, "realign_focus_after_overlay", lambda **kwargs: {"entry_reached": False})

    result = collection_flow._overlay_phase(
        client=DummyClient([]),
        dev="SERIAL",
        tab_cfg=_base_tab_cfg(max_steps=1),
        row=entry_row,
        rows=rows,
        all_rows=all_rows,
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        main_step_index_by_fingerprint={},
        expanded_overlay_entries=set(),
    )

    assert result.classification == "overlay"
    assert rows == [overlay_row]
    assert all_rows == [overlay_row]


def test_overlay_rows_added_to_rows_and_all_rows(monkeypatch):
    rows = []
    all_rows = []
    entry_row = _main_row(24)
    overlay_row = {**_main_row(240), "context_type": "overlay"}

    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda row, tab_cfg: (True, "test_overlay"))
    monkeypatch.setattr(collection_flow, "classify_post_click_result", lambda **kwargs: ("overlay", _main_row(241)))

    def fake_expand_overlay(**kwargs):
        kwargs["rows"].append(overlay_row)
        kwargs["all_rows"].append(overlay_row)
        return [overlay_row]

    monkeypatch.setattr(collection_flow, "expand_overlay", fake_expand_overlay)
    monkeypatch.setattr(collection_flow, "realign_focus_after_overlay", lambda **kwargs: {"entry_reached": False})

    result = collection_flow._overlay_phase(
        client=DummyClient([]),
        dev="SERIAL",
        tab_cfg=_base_tab_cfg(max_steps=1),
        row=entry_row,
        rows=rows,
        all_rows=all_rows,
        output_path="unused.xlsx",
        output_base_dir=".",
        scenario_perf=None,
        main_step_index_by_fingerprint={},
        expanded_overlay_entries=set(),
    )

    assert result.classification == "overlay"
    assert rows == [overlay_row]
    assert all_rows == [overlay_row]


def test_overlay_still_runs_even_if_row_suppressed(monkeypatch):
    row = _main_row(10)
    phase_ctx, _save_calls, overlay_calls = _run_persistence_main_loop(
        monkeypatch,
        row=row,
        suppress=True,
        suppress_reason="phase_test_suppressed",
    )

    assert phase_ctx.rows == []
    assert phase_ctx.all_rows == []
    assert len(overlay_calls) == 1
    assert overlay_calls[0]["rows_len"] == 0
    assert overlay_calls[0]["all_rows_len"] == 0
    assert overlay_calls[0]["row"]["visible_label"] == "item10"
    assert overlay_calls[0]["row"]["row_persist_suppressed"] is True
    assert overlay_calls[0]["row"]["row_persist_suppressed_reason"] == "phase_test_suppressed"


def test_row_persistence_phase_impl_suppressed_returns_not_persisted(monkeypatch):
    monkeypatch.setattr(collection_flow, "_should_suppress_row_persistence", lambda **kwargs: (True, "phase_suppressed"))
    state = _phase_ordering_state()
    rows = []
    all_rows = []
    perf = _PersistencePerf()
    save_calls = []

    persisted, reason = collection_flow._apply_row_persistence_phase_impl(
        row=_main_row(11),
        state=state,
        rows=rows,
        all_rows=all_rows,
        scenario_perf=perf,
        step_idx=11,
        stop=False,
        checkpoint_every=1,
        output_path="unused.xlsx",
        log_fn=lambda _message: None,
        make_fingerprint_fn=lambda _row: ("fingerprint", "label", "rid"),
        save_fn=lambda *args, **kwargs: save_calls.append((args, kwargs)),
    )

    assert (persisted, reason) == (True, "phase_suppressed")
    assert rows == []
    assert all_rows == []
    assert perf.rows == []
    assert state.main_step_index_by_fingerprint == {}
    assert save_calls == []


def test_row_persistence_phase_impl_non_suppressed_records_all_targets(monkeypatch):
    monkeypatch.setattr(collection_flow, "_should_suppress_row_persistence", lambda **kwargs: (False, ""))
    state = _phase_ordering_state()
    rows = []
    all_rows = []
    perf = _PersistencePerf()
    row = _main_row(12)

    persisted, reason = collection_flow._apply_row_persistence_phase_impl(
        row=row,
        state=state,
        rows=rows,
        all_rows=all_rows,
        scenario_perf=perf,
        step_idx=12,
        stop=False,
        checkpoint_every=100,
        output_path="unused.xlsx",
        log_fn=lambda _message: None,
        make_fingerprint_fn=lambda _row: ("fingerprint", "label", "rid"),
        save_fn=lambda *args, **kwargs: None,
    )

    assert (persisted, reason) == (False, "")
    assert rows == [row]
    assert all_rows == [row]
    assert perf.rows == [row]
    assert state.main_step_index_by_fingerprint == {("fingerprint", "label", "rid"): 12}


def test_row_persistence_phase_impl_saves_on_stop(monkeypatch):
    monkeypatch.setattr(collection_flow, "_should_suppress_row_persistence", lambda **kwargs: (False, ""))
    save_calls = []

    collection_flow._apply_row_persistence_phase_impl(
        row=_main_row(13),
        state=_phase_ordering_state(),
        rows=[],
        all_rows=[],
        scenario_perf=None,
        step_idx=13,
        stop=True,
        checkpoint_every=100,
        output_path="unused.xlsx",
        log_fn=lambda _message: None,
        make_fingerprint_fn=lambda _row: ("fingerprint", "label", "rid"),
        save_fn=lambda *args, **kwargs: save_calls.append((args, kwargs)),
    )

    assert len(save_calls) == 1


def test_row_persistence_phase_impl_saves_on_checkpoint_interval(monkeypatch):
    monkeypatch.setattr(collection_flow, "_should_suppress_row_persistence", lambda **kwargs: (False, ""))
    save_calls = []

    collection_flow._apply_row_persistence_phase_impl(
        row=_main_row(14),
        state=_phase_ordering_state(),
        rows=[],
        all_rows=[],
        scenario_perf=None,
        step_idx=14,
        stop=False,
        checkpoint_every=7,
        output_path="unused.xlsx",
        log_fn=lambda _message: None,
        make_fingerprint_fn=lambda _row: ("fingerprint", "label", "rid"),
        save_fn=lambda *args, **kwargs: save_calls.append((args, kwargs)),
    )

    assert len(save_calls) == 1


def test_row_persistence_phase_wrapper_injects_log_and_save(monkeypatch):
    calls = []

    def fake_impl(**kwargs):
        calls.append(kwargs)
        return "sentinel"

    monkeypatch.setattr(collection_flow, "_apply_row_persistence_phase_impl", fake_impl)
    state = _phase_ordering_state()
    rows = []
    all_rows = []
    row = _main_row(15)

    result = collection_flow._apply_row_persistence_phase(
        row=row,
        state=state,
        rows=rows,
        all_rows=all_rows,
        scenario_perf=None,
        step_idx=15,
        stop=False,
        checkpoint_every=100,
        output_path="unused.xlsx",
    )

    assert result == "sentinel"
    assert len(calls) == 1
    call = calls[0]
    assert call["row"] is row
    assert call["state"] is state
    assert call["rows"] is rows
    assert call["all_rows"] is all_rows
    assert call["step_idx"] == 15
    assert call["checkpoint_every"] == 100
    assert call["output_path"] == "unused.xlsx"
    assert call["log_fn"] is collection_flow.log
    assert call["make_fingerprint_fn"] is collection_flow.make_main_fingerprint
    assert call["save_fn"] is collection_flow.save_excel_with_perf
