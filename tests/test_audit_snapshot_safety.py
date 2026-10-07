from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from tb_runner import collection_flow, scroll_reliability
from tb_runner.audit_snapshot import write_helper_snapshot_xml


def test_helper_xml_preserves_observed_unicode_bounds_and_unknowns(tmp_path):
    path = tmp_path / "snapshot.xml"
    nodes = [{"text": "한국 <&> \"문자\"", "className": "android.view.View", "boundsInScreen": {"l": 1, "t": 2, "r": 30, "b": 40}, "clickable": False, "children": [{"contentDescription": "자녀", "accessibilityFocused": True}]}]
    write_helper_snapshot_xml(nodes, path)
    root = ET.parse(path).getroot()
    assert root.get("source") == "a11y_helper"
    first, second = list(root.iter("node"))
    assert first.get("text") == nodes[0]["text"]
    assert first.get("bounds") == "[1,2][30,40]"
    assert first.get("clickable") == "false"
    assert "focusable" not in first.attrib
    assert second.get("content-desc") == "자녀"
    assert second.get("accessibility-focused") == "true"


def test_unavailable_helper_snapshot_is_not_fabricated(tmp_path):
    path = tmp_path / "missing.xml"
    with pytest.raises(ValueError, match="unavailable"):
        write_helper_snapshot_xml([], path)
    assert not path.exists()


def test_v4_audit_uses_helper_without_ui_automation(tmp_path):
    class Client:
        def dump_tree(self, **kwargs):
            raise AssertionError("Audit must not add a Helper snapshot read")
        def _run(self, *args, **kwargs):
            raise AssertionError("Audit must not connect UiAutomation")
    collection_flow._capture_audit_v4_xml(Client(), "serial", str(tmp_path), "s1", 3, "after_scroll", snapshot_nodes=[{"text": "관측", "boundsInScreen": "0,0,100,100"}])
    path = next((tmp_path / "s1" / "xml_dumps").glob("*.xml"))
    assert ET.parse(path).getroot().get("source") == "a11y_helper"


def test_scroll_xml_reuses_after_snapshot_without_extra_dump(tmp_path, monkeypatch):
    from tb_runner.scroll_reliability import capability, viewport
    node = {"text": "관측", "boundsInScreen": "0,0,100,100"}
    before = {"nodes": [node], "capability": capability([], {"canScrollDown": True}), "viewport": viewport([node], "s1")}
    after = {"nodes": [node], "capability": capability([], {"canScrollDown": False}), "viewport": viewport([node], "s1")}
    client = SimpleNamespace(scroll=lambda **kwargs: True, last_scroll_result={}, _run=lambda *args, **kwargs: pytest.fail("UiAutomation not allowed"))
    monkeypatch.setattr(scroll_reliability, "capture", lambda *args, **kwargs: after)
    monkeypatch.setattr(scroll_reliability.time, "sleep", lambda *args: None)
    result, observed = scroll_reliability.verified_scroll(client, "serial", "s1", 3, before, str(tmp_path))
    assert observed is after
    assert result["after_xml_source"] == "a11y_helper"
    assert result["status"] == "SCROLL_NO_CHANGE"
    assert result["viewport_end"] is True


def test_restart_detected_before_smart_next_prevents_action(monkeypatch):
    client = SimpleNamespace(_window_lifecycle_recorder=SimpleNamespace(restart_event=None), collect_focus_step=lambda **kwargs: pytest.fail("No action after restart"))
    def capture(*args, **kwargs):
        client._window_lifecycle_recorder.restart_event = {"previous_talkback_pid": "1", "talkback_pid": "2"}
    monkeypatch.setattr(collection_flow, "capture_window_lifecycle", capture)
    result = collection_flow._apply_step_collection_phase_impl(state=SimpleNamespace(), client=client, dev="serial", phase_ctx=SimpleNamespace(), step_idx=4, tab_cfg={}, scenario_id="s1", log_fn=lambda *args: None, capture_fn=lambda *args: None, mono_time_fn=lambda: 0)
    assert result["stop_reason"] == "talkback_restarted"


@pytest.mark.parametrize("action", ["scroll", "target_focus_commit"])
def test_client_restart_probe_prevents_action(monkeypatch, action):
    import talkback_lib
    client = talkback_lib.A11yAdbClient(start_monitor=False)
    client._window_lifecycle_recorder = SimpleNamespace(restart_event=None)
    def capture(*args, **kwargs):
        client._window_lifecycle_recorder.restart_event = {"previous_talkback_pid": "1", "talkback_pid": "2"}
    monkeypatch.setattr(talkback_lib, "capture_window_lifecycle", capture)
    monkeypatch.setattr(client, "_scroll_impl", lambda *args, **kwargs: pytest.fail("No scroll after restart"))
    monkeypatch.setattr(client, "_target_focus_commit_impl", lambda *args, **kwargs: pytest.fail("No target command after restart"))
    if action == "scroll":
        assert client.scroll("serial", "down") is False
    else:
        assert client.target_focus_commit(target={})["status"] == "TALKBACK_RESTARTED"
