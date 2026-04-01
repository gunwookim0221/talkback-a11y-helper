import sys
from types import SimpleNamespace

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import overlay_logic


class _Client:
    def __init__(self, post_step):
        self.post_step = post_step

    def collect_focus_step(self, **kwargs):
        return self.post_step


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

    classification, _ = overlay_logic.classify_post_click_result(_Client(post), "SERIAL", {}, pre)

    assert classification == "overlay"


def test_realign_focus_after_overlay_already_on_entry(monkeypatch):
    entry = _step(step_index=3, label="entry", view_id="id.entry")
    monkeypatch.setattr(overlay_logic, "collect_realign_probe", lambda **kwargs: _step(step_index=7, label="entry", view_id="id.entry"))

    result = overlay_logic.realign_focus_after_overlay(client=object(), dev="SERIAL", entry_step=entry, known_step_index_by_fingerprint={})

    assert result["status"] == "already_on_entry"


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
