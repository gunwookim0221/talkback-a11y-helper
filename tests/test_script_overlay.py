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


def test_should_expand_overlay_matches_allowlisted_resource_id():
    step = {
        "focus_view_id": "com.samsung.android.oneconnect:id/add_menu_button",
        "normalized_visible_label": "random",
    }
    assert script_test.should_expand_overlay(step) is True


def test_should_expand_overlay_rejects_non_allowlisted_target():
    step = {
        "focus_view_id": "com.example:id/not_allowed",
        "normalized_visible_label": "not allowed",
    }
    assert script_test.should_expand_overlay(step) is False


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
