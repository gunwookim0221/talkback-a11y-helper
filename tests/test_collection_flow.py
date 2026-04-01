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
        self.select_calls = []

    def reset_focus_history(self, _dev):
        self.reset_focus_history_calls += 1

    def collect_focus_step(self, **kwargs):
        return dict(self.steps.pop(0))

    def touch(self, **kwargs):
        self.touch_calls.append(kwargs)
        return True

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return True


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
    client = DummyClient([])

    ok = collection_flow.open_tab_and_anchor(client, "SERIAL", _base_tab_cfg())

    assert ok is False


def test_open_tab_and_anchor_returns_false_when_anchor_stabilization_fails(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": False})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([])

    ok = collection_flow.open_tab_and_anchor(client, "SERIAL", _base_tab_cfg())

    assert ok is False


def test_open_tab_and_anchor_returns_true_when_both_succeed(monkeypatch):
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow, "stabilize_anchor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = DummyClient([])

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
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (True, 0, 0, "empty_visible_and_speech", ("", "", "")))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    rows = collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=2), [], "o.xlsx", "out")

    assert rows[-1]["status"] == "END"
    assert rows[-1]["stop_reason"] == "empty_visible_and_speech"


def test_collect_tab_rows_checkpoint_save_called_by_interval(monkeypatch):
    steps = [_anchor_row(), _main_row(1), _main_row(2)]
    client = DummyClient(steps)
    save_calls = []

    monkeypatch.setattr(collection_flow, "CHECKPOINT_SAVE_EVERY_STEPS", 2)
    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])
    monkeypatch.setattr(collection_flow, "detect_step_mismatch", lambda **k: ([], []))
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("fp", "id", "b")))
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
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("f", "id", "b")))
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
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("f", "id", "b")))
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
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (False, 0, 0, "", ("f", "id", "b")))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (True, "matched_global_candidates"))
    monkeypatch.setattr(collection_flow, "classify_post_click_result", lambda **k: ("unchanged", {}))
    monkeypatch.setattr(collection_flow, "expand_overlay", lambda **k: called.__setitem__("expand", 1))
    monkeypatch.setattr(collection_flow, "realign_focus_after_overlay", lambda **k: called.__setitem__("realign", 1))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)

    collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=1), [], "o.xlsx", "out")

    assert called == {"expand": 0, "realign": 0}


def test_collect_tab_rows_previous_step_not_updated_after_stop_break(monkeypatch):
    client = DummyClient([_anchor_row(), _main_row(1), _main_row(2)])
    previous_steps = []

    monkeypatch.setattr(collection_flow, "open_scenario", lambda *a, **k: True)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda *a, **k: a[2])

    def _detect(**kwargs):
        previous_steps.append(kwargs.get("previous_step", {}).get("step_index"))
        return [], []

    monkeypatch.setattr(collection_flow, "detect_step_mismatch", _detect)
    monkeypatch.setattr(collection_flow, "should_stop", lambda **k: (True, 0, 0, "move_failed_twice", ("", "", "")))
    monkeypatch.setattr(collection_flow, "save_excel", lambda *a, **k: None)
    monkeypatch.setattr(collection_flow, "is_overlay_candidate", lambda *a, **k: (False, "not_in_global_candidates"))

    collection_flow.collect_tab_rows(client, "SERIAL", _base_tab_cfg(max_steps=2), [], "o.xlsx", "out")

    assert previous_steps == [0]


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
