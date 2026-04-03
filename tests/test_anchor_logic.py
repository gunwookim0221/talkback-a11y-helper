from unittest.mock import Mock

from tb_runner import anchor_logic


class FakeAnchorClient:
    def __init__(self):
        self.dump_tree = Mock(return_value=[])
        self.select = Mock(return_value=False)
        self.collect_focus_step = Mock(return_value={})


def _tab_cfg():
    return {
        "scenario_id": "s1",
        "anchor_name": "anchor_text",
        "anchor_type": "a",
        "anchor": {"resource_id_regex": "anchor_id", "text_regex": "anchor_text"},
    }


def _node(view_id="anchor_id", text="anchor_text", bounds="[0,0][10,10]"):
    return {"viewIdResourceName": view_id, "text": text, "boundsInScreen": bounds, "className": "TextView"}


def _focusable_node(
    view_id: str,
    text: str,
    bounds: str,
    *,
    focusable: bool = True,
    clickable: bool = True,
    visible_to_user: bool = True,
):
    return {
        "viewIdResourceName": view_id,
        "text": text,
        "boundsInScreen": bounds,
        "className": "TextView",
        "focusable": focusable,
        "clickable": clickable,
        "visibleToUser": visible_to_user,
    }


def _verify_step(view_id="anchor_id", label="anchor_text", bounds="0,0,10,10"):
    return {"focus_view_id": view_id, "visible_label": label, "merged_announcement": label, "focus_bounds": bounds}


def test_stabilize_anchor_selects_best_candidate_resource_id(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert result["selected"] is True
    assert client.dump_tree.call_count == 1
    assert client.select.call_count == 1
    assert client.collect_focus_step.call_count == 2


def test_stabilize_anchor_fallback_select_when_best_select_fails(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.side_effect = [False, True]
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert client.select.call_count == 2


def test_stabilize_anchor_ok_when_verify_match_and_context_ok(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step()
    verify_context = Mock(return_value={"ok": True})
    monkeypatch.setattr(anchor_logic, "verify_context", verify_context)

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert verify_context.call_count == 2


def test_stabilize_anchor_fails_when_match_but_context_fail(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": False})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is False


def test_stabilize_anchor_retries_and_fails_when_verify_match_fails(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step(view_id="different", label="different")
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=2)

    assert result["ok"] is False
    assert client.dump_tree.call_count == 2


def test_stabilize_anchor_verified_without_select_reason(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = []
    client.select.return_value = False
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert result["selected"] is False
    assert result["reason"] == "verified_without_select"


def test_stabilize_anchor_fails_when_not_double_verified(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = []
    client.select.return_value = False
    client.collect_focus_step.side_effect = [_verify_step(), _verify_step(view_id="different", label="different")]
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is False
    assert result["reason"] == "low_confidence_anchor_start"


def test_stabilize_anchor_anchor_only_ignores_context_failure(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": False})
    tab_cfg = {**_tab_cfg(), "stabilization_mode": "anchor_only"}

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert result["context"]["type"] == "skipped"


def test_stabilize_anchor_tab_context_ignores_anchor_mismatch(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step(view_id="different", label="different")
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {**_tab_cfg(), "stabilization_mode": "tab_context"}

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is True


def test_stabilize_anchor_uses_content_fallback_when_anchor_missing(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [
        _focusable_node("toolbar_back", "Back", "[0,0][120,120]"),
        _focusable_node("content_top_left", "Start", "[40,260][220,340]"),
    ]
    client.select.return_value = True
    captured_cfg = {}

    def _fake_stabilize_anchor_focus(**kwargs):
        captured_cfg.update(kwargs.get("anchor_cfg", {}))
        return {
            "stable": True,
            "reason": "double_verified",
            "verify_rows": [_verify_step(view_id="content_top_left", label="Start"), _verify_step(view_id="content_top_left", label="Start")],
            "verify_matches": [{"matched": True, "score": 100}, {"matched": True, "score": 100}],
            "verify1_matched": True,
            "verify2_matched": True,
        }

    monkeypatch.setattr(anchor_logic, "stabilize_anchor_focus", _fake_stabilize_anchor_focus)
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {"scenario_id": "s1", "anchor_name": "", "anchor_type": "a", "anchor": {}}

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert client.select.call_args.kwargs["type_"] == "r"
    assert "content_top_left" in client.select.call_args.kwargs["name"]
    assert "content_top_left" in captured_cfg.get("resource_id_regex", "")


def test_stabilize_anchor_fallback_prefers_top_center_then_right(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [
        _focusable_node("top_toolbar", "Search", "[10,0][300,120]"),
        _focusable_node("top_center_item", "Center", "[430,260][650,340]"),
        _focusable_node("top_right_item", "Right", "[820,260][1040,340]"),
    ]
    client.select.return_value = True
    monkeypatch.setattr(
        anchor_logic,
        "stabilize_anchor_focus",
        lambda **kwargs: {
            "stable": True,
            "reason": "double_verified",
            "verify_rows": [_verify_step(view_id="top_center_item", label="Center"), _verify_step(view_id="top_center_item", label="Center")],
            "verify_matches": [{"matched": True, "score": 100}, {"matched": True, "score": 100}],
            "verify1_matched": True,
            "verify2_matched": True,
        },
    )
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {
        **_tab_cfg(),
        "anchor": {"resource_id_regex": "not_found", "text_regex": "not_found"},
    }

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert "top_center_item" in client.select.call_args.kwargs["name"]
