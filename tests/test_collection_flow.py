import sys
from types import SimpleNamespace

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow


class DummyClient:
    def __init__(self, steps):
        self.steps = list(steps)
        self.reset_focus_history_calls = 0
        self.touch_calls = []
        self.scroll_touch_calls = []
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
    return {"tab_name": "홈", "scenario_id": "s1", "max_steps": max_steps, "tab_type": "t", "tab_name": "홈"}


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
    client = DummyClient([_anchor_row()])

    ok = collection_flow.open_tab_and_anchor(client, "SERIAL", _base_tab_cfg())

    assert ok is False


def test_open_tab_and_anchor_returns_false_when_anchor_stabilization_fails(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": False})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])

    ok = collection_flow.open_tab_and_anchor(client, "SERIAL", _base_tab_cfg())

    assert ok is False


def test_open_tab_and_anchor_returns_true_when_both_succeed(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([_anchor_row()])

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


def test_recover_to_start_state_skips_when_already_target(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([])
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


def test_open_scenario_pre_navigation_scroll_touch_failure(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
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
