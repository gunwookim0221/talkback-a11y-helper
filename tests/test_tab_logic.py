from unittest.mock import Mock

from tb_runner import tab_logic
from tb_runner.bottom_nav import annotate_bottom_nav_candidates


class FakeTabClient:
    def __init__(self):
        self.dump_tree = Mock(return_value=[])
        self.touch_point = Mock(return_value=False)
        self.select = Mock(return_value=False)
        self.touch = Mock(return_value=False)
        self.get_focus = Mock(return_value={})
        self.collect_focus_step = Mock(return_value={})


def _tab_cfg():
    return {
        "scenario_id": "s1",
        "tab_name": "홈",
        "tab_type": "t",
        "tab": {"resource_id_regex": "tab_id", "text_regex": "홈"},
    }


def _r2_bottom_nav_nodes():
    labels = ["홈", "기기", "라이프", "자동화", "메뉴, 새 콘텐츠 사용 가능"]
    return [
        {
            "text": "",
            "contentDescription": label,
            "className": "android.widget.LinearLayout",
            "viewIdResourceName": None,
            "boundsInScreen": {"l": index * 180, "t": 900, "r": index * 180 + 150, "b": 1000},
            "clickable": index > 0,
            "focusable": True,
            "visibleToUser": True,
        }
        for index, label in enumerate(labels)
    ]


def test_r2_bottom_nav_row_is_discovered_without_resource_ids():
    nodes = annotate_bottom_nav_candidates(_r2_bottom_nav_nodes(), expected_count=5)

    assert [node["_bottom_nav_candidate"] for node in nodes] == [True] * 5
    tab_cfg = tab_logic.normalize_tab_config({"tab_name": "(?i).*devices.*", "tab_type": "b"})

    result = tab_logic.match_tab_candidate(nodes[1], tab_cfg)

    assert result["matched"] is True
    assert "bottom_tab_alias" in result["matched_fields"]
    assert result["candidate"]["resource_id"] == ""


def test_stabilize_r2_tab_uses_semantic_touch_without_legacy_header_fallback():
    client = FakeTabClient()
    client.dump_tree.return_value = _r2_bottom_nav_nodes()
    client.touch_point.return_value = True
    client.select.return_value = True
    client.collect_focus_step.return_value = {
        "visible_label": "기기 기기",
        "merged_announcement": "기기 기기",
        "focus_node": {"text": "기기 기기", "contentDescription": "기기 기기"},
    }
    config = {
        "scenario_id": "devices_main",
        "tab_name": "(?i).*devices.*",
        "tab_type": "b",
        "global_nav": {"labels": ["Home", "Devices", "Life", "Routines", "Menu"]},
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(devices|기기).*",
        },
    }

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", config, max_retries=1)

    assert result["ok"] is True
    client.touch_point.assert_called_once()
    client.touch.assert_not_called()


def test_stabilize_tab_selection_touch_point_success(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "0,0,10,10", "text": "홈"}]
    client.touch_point.return_value = True
    client.select.return_value = True
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    monkeypatch.setattr(tab_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", _tab_cfg(), max_retries=1)

    assert result["ok"] is True
    assert result["focus_align"]["ok"] is True
    client.dump_tree.assert_called_once()
    client.touch_point.assert_called_once()
    client.select.assert_called_once()
    client.touch.assert_not_called()
    client.collect_focus_step.assert_called_once()


def test_stabilize_tab_selection_select_fallback_when_bounds_missing(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "", "text": "홈"}]
    client.select.return_value = True
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    monkeypatch.setattr(tab_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", _tab_cfg(), max_retries=1)

    assert result["ok"] is True
    client.touch_point.assert_not_called()
    assert client.select.call_count == 2
    client.touch.assert_not_called()


def test_stabilize_tab_selection_select_fallback_when_touch_point_fails(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "0,0,10,10", "text": "홈"}]
    client.touch_point.return_value = False
    client.select.return_value = True
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    monkeypatch.setattr(tab_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", _tab_cfg(), max_retries=1)

    assert result["ok"] is True
    client.touch_point.assert_called_once()
    assert client.select.call_count == 2
    client.touch.assert_not_called()


def test_stabilize_tab_selection_legacy_touch_when_no_best_candidate(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "other", "text": "다른 탭", "boundsInScreen": "0,0,10,10"}]
    client.touch.return_value = True
    client.select.return_value = True
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    monkeypatch.setattr(tab_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", _tab_cfg(), max_retries=1)

    assert result["ok"] is True
    assert result["focus_align"]["ok"] is True
    client.touch.assert_called_once()
    client.select.assert_called_once()
    client.touch_point.assert_not_called()


def test_stabilize_tab_selection_success_when_selected_and_context_ok(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "0,0,10,10", "text": "홈"}]
    client.touch_point.return_value = True
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    verify_context = Mock(return_value={"ok": True})
    monkeypatch.setattr(tab_logic, "verify_context", verify_context)

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", _tab_cfg(), max_retries=2)

    assert result["ok"] is True
    verify_context.assert_called_once()


def test_stabilize_tab_selection_retries_and_can_fail_when_context_not_ok(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "0,0,10,10", "text": "홈"}]
    client.touch_point.return_value = True
    client.collect_focus_step.return_value = {"visible_label": "bad"}
    verify_context = Mock(return_value={"ok": False})
    monkeypatch.setattr(tab_logic, "verify_context", verify_context)

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", _tab_cfg(), max_retries=2)

    assert result["ok"] is False
    assert client.dump_tree.call_count == 2
    assert client.collect_focus_step.call_count == 2
    assert verify_context.call_count == 2


def test_stabilize_tab_selection_focus_align_failure_is_reported(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "0,0,10,10", "text": "홈"}]
    client.touch_point.return_value = True
    client.select.return_value = False
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    monkeypatch.setattr(tab_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", _tab_cfg(), max_retries=1)

    assert result["ok"] is True
    assert result["focus_align"]["attempted"] is True
    assert result["focus_align"]["ok"] is False


def test_stabilize_tab_selection_transition_uses_fast_focus_align(monkeypatch):
    client = FakeTabClient()
    logs = []
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "0,0,10,10", "text": "홈"}]
    client.touch_point.return_value = True
    client.select.return_value = True
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    monkeypatch.setattr(tab_logic, "verify_context", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(tab_logic, "log", lambda message, level="NORMAL": logs.append(message))
    monkeypatch.setattr(tab_logic.time, "sleep", lambda *_: None)

    result = tab_logic.stabilize_tab_selection(
        client,
        "SERIAL",
        {**_tab_cfg(), "screen_context_mode": "new_screen", "pre_navigation": [{"action": "select", "target": "x"}]},
        max_retries=1,
    )

    assert result["ok"] is True
    assert result["focus_align"]["fast_mode"] is True
    assert any("[TAB][focus_align_fast] path='touch_immediate'" in line for line in logs)
    assert any("[TAB][focus_align_fast] attempt=1/2" in line for line in logs)
    assert client.select.call_args.kwargs["wait_"] == 1
    assert client.collect_focus_step.call_count == 0


def test_stabilize_tab_selection_transition_fast_focus_align_is_bounded(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "0,0,10,10", "text": "홈"}]
    client.touch_point.return_value = True
    client.select.return_value = False
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    monkeypatch.setattr(tab_logic, "verify_context", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(tab_logic.time, "sleep", lambda *_: None)

    result = tab_logic.stabilize_tab_selection(
        client,
        "SERIAL",
        {
            **_tab_cfg(),
            "screen_context_mode": "new_screen",
            "pre_navigation": [{"action": "select", "target": "x"}],
            "tab_focus_align_retry_count": 8,
        },
        max_retries=1,
    )

    assert result["ok"] is True
    assert result["focus_align"]["fast_mode"] is True
    assert result["focus_align"]["attempt"] == 2
    assert client.select.call_count == 2


def test_stabilize_tab_selection_main_tab_keeps_verify_step(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "0,0,10,10", "text": "홈"}]
    client.touch_point.return_value = True
    client.select.return_value = True
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    monkeypatch.setattr(tab_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", _tab_cfg(), max_retries=1)

    assert result["ok"] is True
    assert client.collect_focus_step.call_count == 1


def test_stabilize_tab_selection_focus_align_promoted_by_get_focus(monkeypatch):
    client = FakeTabClient()
    client.dump_tree.return_value = [{"viewIdResourceName": "tab_id", "boundsInScreen": "0,0,10,10", "text": "홈"}]
    client.touch_point.return_value = True
    client.select.return_value = False
    client.get_focus.return_value = {"viewIdResourceName": "tab_id", "accessibilityFocused": True, "text": "홈"}
    client.collect_focus_step.return_value = {"visible_label": "ok"}
    monkeypatch.setattr(tab_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = tab_logic.stabilize_tab_selection(client, "SERIAL", _tab_cfg(), max_retries=1)

    assert result["ok"] is True
    assert result["focus_align"]["ok"] is True
    assert result["focus_align"]["reason"] == "post_focus_verified"
    client.get_focus.assert_called_once()
