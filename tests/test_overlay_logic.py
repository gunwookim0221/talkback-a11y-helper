import sys
from types import SimpleNamespace

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, ExcelWriter=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import overlay_logic


class _Client:
    def __init__(self, post_step):
        self.post_step = post_step

    def collect_focus_step(self, **kwargs):
        return self.post_step


class _OverlayClient:
    def __init__(self, steps):
        self.steps = list(steps)
        self._index = 0

    def collect_focus_step(self, **kwargs):
        if self._index < len(self.steps):
            step = self.steps[self._index]
            self._index += 1
            return step.copy()
        return self.steps[-1].copy()

    def press_back_and_recover_focus(self, **kwargs):
        return {"status": "ok"}


def _step(step_index=1, label="add", view_id="id.add", bounds="0,0,10,10", nodes=None):
    return {
        "step_index": step_index,
        "visible_label": label,
        "normalized_visible_label": label.lower(),
        "merged_announcement": label,
        "focus_view_id": view_id,
        "focus_bounds": bounds,
        "dump_tree_nodes": nodes or [],
    }


def test_classify_post_click_result_unchanged():
    pre = _step(nodes=[{"viewIdResourceName": "id.a", "text": "A", "contentDescription": ""}])
    client = _Client(post_step=pre.copy())

    classification, _ = overlay_logic.classify_post_click_result(client, "SERIAL", {}, pre)

    assert classification == "unchanged"


def test_classify_post_click_result_navigation_with_explicit_cue():
    pre = _step(nodes=[{"viewIdResourceName": "id.a", "text": "A", "contentDescription": ""}])
    post = _step(label="Navigate up", view_id="id.back", nodes=[{"viewIdResourceName": "id.b", "text": "B", "contentDescription": ""}])

    classification, _ = overlay_logic.classify_post_click_result(_Client(post), "SERIAL", {}, pre)

    assert classification == "navigation"


def test_classify_post_click_result_navigation_with_low_overlap_not_guarded():
    pre = _step(label="menu", view_id="id.pre", nodes=[{"viewIdResourceName": "id.a", "text": "A", "contentDescription": ""}])
    post = _step(label="post", view_id="id.post", nodes=[{"viewIdResourceName": "id.b", "text": "B", "contentDescription": ""}])

    classification, _ = overlay_logic.classify_post_click_result(_Client(post), "SERIAL", {}, pre)

    assert classification == "navigation"


def test_classify_post_click_result_overlay_default_path():
    pre = _step(nodes=[
        {"viewIdResourceName": "id.common", "text": "A", "contentDescription": ""},
        {"viewIdResourceName": "id.pre", "text": "B", "contentDescription": ""},
    ])
    post = _step(label="Edit", view_id="id.edit", nodes=[
        {"viewIdResourceName": "id.common", "text": "A", "contentDescription": ""},
        {"viewIdResourceName": "id.post", "text": "C", "contentDescription": ""},
    ])

    classification, _ = overlay_logic.classify_post_click_result(_Client(post), "SERIAL", {}, pre)

    assert classification == "overlay"


def test_classify_post_click_result_guarded_low_overlap_keeps_overlay():
    pre = _step(
        label="Add",
        view_id="com.samsung.android.oneconnect:id/add_menu_button",
        nodes=[{"viewIdResourceName": "id.a", "text": "A", "contentDescription": ""}],
    )
    post = _step(label="Edit", view_id="id.edit", nodes=[{"viewIdResourceName": "id.b", "text": "B", "contentDescription": ""}])

    tab_cfg = {
        "overlay_policy": {
            "allow_candidates": [
                {"resource_id": "com.samsung.android.oneconnect:id/add_menu_button", "label": "Add"}
            ],
            "block_candidates": [],
        }
    }
    classification, _ = overlay_logic.classify_post_click_result(_Client(post), "SERIAL", tab_cfg, pre)

    assert classification == "overlay"


def test_realign_focus_after_overlay_already_on_entry(monkeypatch):
    entry = _step(step_index=3, label="entry", view_id="id.entry")
    monkeypatch.setattr(overlay_logic, "collect_realign_probe", lambda **kwargs: _step(step_index=7, label="entry", view_id="id.entry"))

    result = overlay_logic.realign_focus_after_overlay(client=object(), dev="SERIAL", entry_step=entry, known_step_index_by_fingerprint={})

    assert result["status"] == "already_on_entry"


def test_realign_focus_after_overlay_matches_partial_label(monkeypatch):
    entry = _step(step_index=3, label="add device", view_id="", bounds="0,0,10,10")
    monkeypatch.setattr(
        overlay_logic,
        "collect_realign_probe",
        lambda **kwargs: _step(step_index=7, label="add", view_id="", bounds="20,20,30,30"),
    )

    result = overlay_logic.realign_focus_after_overlay(client=object(), dev="SERIAL", entry_step=entry, known_step_index_by_fingerprint={})

    assert result["status"] == "already_on_entry"
    assert result["match_by"] == "label_partial"


def test_realign_focus_after_overlay_matches_bounds_overlap(monkeypatch):
    entry = _step(step_index=3, label="entry", view_id="", bounds="0,0,100,100")
    monkeypatch.setattr(
        overlay_logic,
        "collect_realign_probe",
        lambda **kwargs: _step(step_index=7, label="other", view_id="", bounds="5,5,95,95"),
    )

    result = overlay_logic.realign_focus_after_overlay(client=object(), dev="SERIAL", entry_step=entry, known_step_index_by_fingerprint={})

    assert result["status"] == "already_on_entry"
    assert result["match_by"] == "bounds_overlap"


def test_realign_focus_after_overlay_skip_when_not_before_entry(monkeypatch):
    entry = _step(step_index=3, label="entry", view_id="id.entry", bounds="0,0,10,10")
    current = _step(step_index=7, label="current", view_id="id.current", bounds="10,10,20,20")
    fp = overlay_logic.make_main_fingerprint(current)
    monkeypatch.setattr(overlay_logic, "collect_realign_probe", lambda **kwargs: current)

    result = overlay_logic.realign_focus_after_overlay(
        client=object(),
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={fp: 3},
    )

    assert result["status"] == "skip_realign_not_before_entry"


def test_realign_focus_after_overlay_unknown_fingerprint_keeps_realign(monkeypatch):
    entry = _step(step_index=3, label="entry", view_id="id.entry", bounds="0,0,10,10")
    current = _step(step_index=7, label="current", view_id="id.current", bounds="10,10,20,20")
    probes = [current, _step(step_index=8, label="entry", view_id="id.entry", bounds="0,0,10,10")]

    def _probe(**kwargs):
        return probes.pop(0)

    monkeypatch.setattr(overlay_logic, "collect_realign_probe", _probe)

    result = overlay_logic.realign_focus_after_overlay(
        client=object(),
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={},
    )

    assert result["status"] == "realign_entry_reached"


def test_realign_focus_after_overlay_entry_reached(monkeypatch):
    entry = _step(step_index=3, label="entry", view_id="id.entry", bounds="0,0,10,10")
    current = _step(step_index=7, label="current", view_id="id.current", bounds="10,10,20,20")
    probes = [current, _step(step_index=8, label="entry", view_id="id.entry", bounds="0,0,10,10")]

    def _probe(**kwargs):
        return probes.pop(0)

    monkeypatch.setattr(overlay_logic, "collect_realign_probe", _probe)
    fp = overlay_logic.make_main_fingerprint(current)

    result = overlay_logic.realign_focus_after_overlay(
        client=object(),
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={fp: 1},
    )

    assert result["status"] == "realign_entry_reached"


def test_realign_focus_after_overlay_entry_not_found(monkeypatch):
    entry = _step(step_index=3, label="entry", view_id="id.entry", bounds="0,0,10,10")
    current = _step(step_index=7, label="current", view_id="id.current", bounds="10,10,20,20")

    def _probe(**kwargs):
        if kwargs.get("move"):
            return _step(step_index=8, label="other", view_id="id.other", bounds="20,20,30,30")
        return current

    monkeypatch.setattr(overlay_logic, "collect_realign_probe", _probe)
    monkeypatch.setattr(overlay_logic, "OVERLAY_REALIGN_MAX_STEPS", 2)
    fp = overlay_logic.make_main_fingerprint(current)

    result = overlay_logic.realign_focus_after_overlay(
        client=object(),
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={fp: 1},
    )

    assert result["status"] == "realign_entry_not_found"


def test_realign_focus_after_overlay_falls_back_to_prev_direction(monkeypatch):
    entry = _step(step_index=3, label="entry", view_id="id.entry", bounds="0,0,10,10")
    current = _step(step_index=7, label="current", view_id="id.current", bounds="10,10,20,20")

    def _probe(**kwargs):
        if not kwargs.get("move"):
            return current
        direction = kwargs.get("direction")
        if direction == "next":
            return _step(step_index=8, label="other", view_id="id.other", bounds="20,20,30,30")
        return _step(step_index=9, label="entry", view_id="id.entry", bounds="0,0,10,10")

    monkeypatch.setattr(overlay_logic, "collect_realign_probe", _probe)
    monkeypatch.setattr(overlay_logic, "OVERLAY_REALIGN_MAX_STEPS", 2)

    result = overlay_logic.realign_focus_after_overlay(
        client=object(),
        dev="SERIAL",
        entry_step=entry,
        known_step_index_by_fingerprint={},
    )

    assert result["status"] == "realign_entry_reached"
    assert result["entry_reached"] is True
    assert result["match_by"] == "view_id"


def test_expand_overlay_dedups_repeated_item_rows(monkeypatch):
    first = _step(
        step_index=1,
        label="Add device",
        view_id="com.samsung.android.oneconnect:id/title",
        bounds="582,356,824,422",
    )
    second = first.copy()
    second["step_index"] = 2
    second["move_result"] = "ok"

    client = _OverlayClient([first, second])
    tab_cfg = {"tab_name": "Home"}
    entry_step = _step(step_index=3, label="Add", view_id="com.samsung.android.oneconnect:id/add_menu_button")
    rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []

    monkeypatch.setattr(overlay_logic, "maybe_capture_focus_crop", lambda *_args, **_kwargs: _args[2])
    monkeypatch.setattr(overlay_logic, "save_excel_with_perf", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay_logic, "OVERLAY_MAX_STEPS", 2)

    overlay_rows = overlay_logic.expand_overlay(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        entry_step=entry_step,
        rows=rows,
        all_rows=all_rows,
        output_path="out.xlsx",
        output_base_dir="output",
        skip_entry_click=True,
    )

    assert len(overlay_rows) == 1
    assert overlay_rows[0]["focus_view_id"] == first["focus_view_id"]


def test_expand_overlay_skips_duplicate_then_keeps_next_changed_item(monkeypatch):
    first = _step(
        step_index=1,
        label="Add device",
        view_id="com.samsung.android.oneconnect:id/title",
        bounds="582,356,824,422",
    )
    second = first.copy()
    second["step_index"] = 2
    second["move_result"] = "ok"
    third = _step(
        step_index=3,
        label="Add service",
        view_id="com.samsung.android.oneconnect:id/title",
        bounds="582,430,824,496",
    )

    client = _OverlayClient([first, second, third])
    tab_cfg = {"tab_name": "Home"}
    entry_step = _step(step_index=3, label="Add", view_id="com.samsung.android.oneconnect:id/add_menu_button")
    rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []

    monkeypatch.setattr(overlay_logic, "maybe_capture_focus_crop", lambda *_args, **_kwargs: _args[2])
    monkeypatch.setattr(overlay_logic, "save_excel_with_perf", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay_logic, "OVERLAY_MAX_STEPS", 3)

    overlay_rows = overlay_logic.expand_overlay(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        entry_step=entry_step,
        rows=rows,
        all_rows=all_rows,
        output_path="out.xlsx",
        output_base_dir="output",
        skip_entry_click=True,
    )

    assert len(overlay_rows) == 2
    assert overlay_rows[0]["visible_label"] == "Add device"
    assert overlay_rows[1]["visible_label"] == "Add service"


def test_expand_overlay_keeps_collecting_when_focus_changes(monkeypatch):
    first = _step(step_index=1, label="Add device", view_id="id/title", bounds="10,10,40,40")
    second = _step(step_index=2, label="Kitchen", view_id="id/item", bounds="10,50,40,80")

    client = _OverlayClient([first, second])
    tab_cfg = {"tab_name": "Home"}
    entry_step = _step(step_index=3, label="Add", view_id="id/add")
    rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []

    monkeypatch.setattr(overlay_logic, "maybe_capture_focus_crop", lambda *_args, **_kwargs: _args[2])
    monkeypatch.setattr(overlay_logic, "save_excel_with_perf", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay_logic, "OVERLAY_MAX_STEPS", 2)

    overlay_rows = overlay_logic.expand_overlay(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        entry_step=entry_step,
        rows=rows,
        all_rows=all_rows,
        output_path="out.xlsx",
        output_base_dir="output",
        skip_entry_click=True,
    )

    assert len(overlay_rows) == 2
    assert overlay_rows[0]["focus_view_id"] != overlay_rows[1]["focus_view_id"]


def test_expand_overlay_does_not_stall_on_repeated_label_only(monkeypatch):
    first = _step(step_index=1, label="Delete", view_id="id/item1", bounds="10,10,40,40")
    second = _step(step_index=2, label="Delete", view_id="id/item2", bounds="10,50,40,80")
    third = _step(step_index=3, label="Delete", view_id="id/item3", bounds="10,90,40,120")
    fourth = _step(step_index=4, label="Delete", view_id="id/item4", bounds="10,130,40,160")
    fifth = _step(step_index=5, label="Import QR code", view_id="id/item5", bounds="10,170,40,200")

    client = _OverlayClient([first, second, third, fourth, fifth])
    tab_cfg = {
        "tab_name": "Routines",
        "overlay_max_advancement_failures": 2,
    }
    entry_step = _step(step_index=3, label="More options", view_id="id/more")
    rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []

    monkeypatch.setattr(overlay_logic, "maybe_capture_focus_crop", lambda *_args, **_kwargs: _args[2])
    monkeypatch.setattr(overlay_logic, "save_excel_with_perf", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay_logic, "OVERLAY_MAX_STEPS", 5)

    overlay_rows = overlay_logic.expand_overlay(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        entry_step=entry_step,
        rows=rows,
        all_rows=all_rows,
        output_path="out.xlsx",
        output_base_dir="output",
        skip_entry_click=True,
    )

    assert len(overlay_rows) == 5
    assert overlay_rows[-1]["visible_label"] == "Import QR code"


def test_expand_overlay_keeps_trying_before_two_rows_even_with_no_progress(monkeypatch):
    first = _step(step_index=1, label="Delete", view_id="id/title", bounds="10,10,40,40")
    first["move_result"] = "ok"
    second = first.copy()
    second["step_index"] = 2
    second["move_result"] = "ok"
    third = first.copy()
    third["step_index"] = 3
    third["move_result"] = "no_progress"
    fourth = first.copy()
    fourth["step_index"] = 4
    fourth["move_result"] = "no_progress"

    client = _OverlayClient([first, second, third, fourth])
    tab_cfg = {"tab_name": "Life"}
    entry_step = _step(step_index=5, label="More options", view_id="id/more")
    rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []

    monkeypatch.setattr(overlay_logic, "maybe_capture_focus_crop", lambda *_args, **_kwargs: _args[2])
    monkeypatch.setattr(overlay_logic, "save_excel_with_perf", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay_logic, "OVERLAY_MAX_STEPS", 6)

    overlay_rows = overlay_logic.expand_overlay(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        entry_step=entry_step,
        rows=rows,
        all_rows=all_rows,
        output_path="out.xlsx",
        output_base_dir="output",
        skip_entry_click=True,
    )

    assert len(overlay_rows) == 1
    assert overlay_rows[-1]["stop_reason"] == ""


def test_expand_overlay_no_progress_with_actionable_change_is_not_stall(monkeypatch):
    first = _step(step_index=1, label="Sort", view_id="id/title", bounds="10,10,40,40")
    second = _step(step_index=2, label="Sort", view_id="id/title", bounds="10,50,40,80")
    second["move_result"] = "no_progress"

    client = _OverlayClient([first, second])
    tab_cfg = {"tab_name": "Routines", "overlay_max_advancement_failures": 1}
    entry_step = _step(step_index=3, label="More options", view_id="id/more")
    rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []

    monkeypatch.setattr(overlay_logic, "maybe_capture_focus_crop", lambda *_args, **_kwargs: _args[2])
    monkeypatch.setattr(overlay_logic, "save_excel_with_perf", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay_logic, "OVERLAY_MAX_STEPS", 2)

    overlay_rows = overlay_logic.expand_overlay(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        entry_step=entry_step,
        rows=rows,
        all_rows=all_rows,
        output_path="out.xlsx",
        output_base_dir="output",
        skip_entry_click=True,
    )

    assert len(overlay_rows) == 2
    assert overlay_rows[-1]["focus_bounds"] == "10,50,40,80"


def test_expand_overlay_keeps_initial_post_click_focus_as_first_row(monkeypatch):
    next_row = _step(step_index=2, label="Add service", view_id="id/title", bounds="20,20,40,40")
    client = _OverlayClient([next_row])
    tab_cfg = {"tab_name": "Home"}
    entry_step = _step(step_index=3, label="Add", view_id="id/add")
    initial_overlay_step = _step(step_index=99, label="Add favourites", view_id="id/title", bounds="10,10,30,30")
    rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []

    monkeypatch.setattr(overlay_logic, "maybe_capture_focus_crop", lambda *_args, **_kwargs: _args[2])
    monkeypatch.setattr(overlay_logic, "save_excel_with_perf", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay_logic, "OVERLAY_MAX_STEPS", 2)

    overlay_rows = overlay_logic.expand_overlay(
        client=client,
        dev="SERIAL",
        tab_cfg=tab_cfg,
        entry_step=entry_step,
        rows=rows,
        all_rows=all_rows,
        output_path="out.xlsx",
        output_base_dir="output",
        skip_entry_click=True,
        initial_overlay_step=initial_overlay_step,
    )

    assert len(overlay_rows) == 2
    assert overlay_rows[0]["visible_label"] == "Add favourites"
    assert overlay_rows[1]["visible_label"] == "Add service"
