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
    client.collect_focus_step.assert_called_once()


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
    verify_context.assert_called_once()


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
