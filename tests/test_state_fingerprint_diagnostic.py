import json
import sys

import pytest

from tools import state_fingerprint_diagnostic as diagnostic
from tb_runner.state_fingerprint import build_state_fingerprint


XML = '''<hierarchy><node resource-id="com.samsung.android.oneconnect:id/menu_favorites"
 text="Home" selected="true" enabled="true" clickable="true" focusable="true"
 bounds="[0,900][200,1000]" class="android.widget.TextView"/></hierarchy>'''


class Client:
    def __init__(self, xml=XML, focus_error=False):
        self.xml, self.focus_error, self.calls = xml, focus_error, []
        self.last_dump_metadata = {"canScrollDown": True}
        self.last_scroll_capabilities = []

    def dump_tree(self, **kwargs):
        assert kwargs["include_scroll_capabilities"] is True
        return [{"text": "Device", "boundsInScreen": "[0,100][500,200]"}]

    def get_focus(self, **kwargs):
        assert kwargs["allow_fallback_dump"] is False and kwargs["mode"] == "fast"
        self.last_dump_metadata = {"canScrollDown": False}
        if self.focus_error:
            raise RuntimeError("unavailable")
        return {"text": "Device", "accessibilityFocused": True}

    def _run(self, command, **kwargs):
        self.calls.append(command)
        if command[:3] == ["shell", "uiautomator", "dump"]:
            if self.xml is None:
                raise RuntimeError("XML unavailable")
            return "UI hierarchy dumped"
        if command[:2] == ["shell", "cat"]:
            return self.xml
        if command == ["shell", "wm", "size"]:
            return "Physical size: 1080x2640\nOverride size: 1000x1000"
        if command == ["shell", "dumpsys", "window"]:
            return "mCurrentFocus=Window{a u0 com.samsung.android.oneconnect/.MainActivity}"
        raise AssertionError("Unexpected action command: " + repr(command))


def test_capture_reuses_sources_and_copies_capability_before_focus_cache_changes():
    client = Client()
    value = diagnostic.capture_observation(client, "serial", scenario_id="home", step=2)
    assert value["capability"]["can_scroll_forward"] is True
    assert client.last_dump_metadata["canScrollDown"] is False
    assert value["selected_tab"] == {"name": "home", "verified": True, "source": "xml_selected"}
    assert value["package_name"] == "com.samsung.android.oneconnect"
    assert value["activity_name"] == ".MainActivity"
    assert value["display_bounds"] == [0, 0, 1000, 1000]
    assert value["source"] == "helper_capability+xml_semantics"
    assert value["overlay"]["source"] == "existing_popup_detector"
    assert len(client.calls) == 4


def test_absent_xml_flags_remain_unknown_instead_of_false():
    value = diagnostic.capture_observation(Client(), "serial")
    assert value["nodes"][0]["checked"] is None
    assert value["nodes"][0]["scrollable"] is None
    assert value["nodes"][0]["visibleToUser"] is None
    assert build_state_fingerprint(value).to_dict()["transient"]["unknown_node_fields"]["checked"] == 1


def test_xml_unavailable_preserves_partial_helper_and_unknown_tab():
    value = diagnostic.capture_observation(Client(xml=None), "serial")
    assert value["source"] == "helper_flat"
    assert value["selected_tab"] is None
    assert value["navigation_context"] is None
    assert value["nodes"][0]["text"] == "Device"
    assert "xml_capture:RuntimeError" in value["notes"]
    assert build_state_fingerprint(value).to_dict()["core"]["selected_tab"] is None


def test_focus_unavailable_is_diagnostic_only():
    healthy = diagnostic.capture_observation(Client(), "serial")
    missing = diagnostic.capture_observation(Client(focus_error=True), "serial")
    assert missing["focus_node"] == {} and "focus_capture:RuntimeError" in missing["notes"]
    assert build_state_fingerprint(healthy).core_signature == build_state_fingerprint(missing).core_signature


def test_multiple_focused_windows_are_unknown_without_guessing():
    class MultipleWindows(Client):
        def _run(self, command, **kwargs):
            if command == ["shell", "dumpsys", "window"]:
                return "mCurrentFocus=Window{a u0 pkg/.Main}\nmCurrentFocus=Window{b u0 other/.Main}"
            return super()._run(command, **kwargs)
    value = diagnostic.capture_observation(MultipleWindows(), "serial")
    assert value["package_name"] is None and value["activity_name"] is None
    assert "window_capture:AMBIGUOUS_FOCUSED_WINDOWS" in value["notes"]


@pytest.mark.parametrize("package,expected", [("com.samsung.android.oneconnect", "activity_resumed"),
                                              ("different.package", "conflicting_observation")])
def test_null_focus_window_uses_observed_resumed_activity_with_xml_guard(package, expected):
    class Resumed(Client):
        def _run(self, command, **kwargs):
            if command == ["shell", "dumpsys", "window"]:
                return "mCurrentFocus=null"
            if command == ["shell", "dumpsys", "activity", "activities"]:
                return "topResumedActivity=ActivityRecord{a u0 " + package + "/.MainActivity t1}"
            return super()._run(command, **kwargs)
    client = Resumed(xml=XML.replace('<node ', '<node package="com.samsung.android.oneconnect" '))
    value = diagnostic.capture_observation(client, "serial")
    assert value["context_source"] == expected
    if expected == "activity_resumed":
        assert value["package_name"] == package and value["activity_name"] == ".MainActivity"
    else:
        assert value["package_name"] is None and value["activity_name"] is None
        assert "window_capture:XML_PACKAGE_CONFLICT" in value["notes"]


def test_replay_cli_writes_jsonl_without_device(tmp_path, monkeypatch, capsys):
    source, output = tmp_path / "observations.json", tmp_path / "state_fingerprints.jsonl"
    source.write_text(json.dumps([{"nodes": [], "scenario_id": "replay", "step": 0}]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["diagnostic", "--input", str(source), "--output", str(output)])
    assert diagnostic.main() == 0
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["scenario_id"] == "replay"
    assert record["viewport"]["observation_status"] == "UNOBSERVED"
    assert json.loads(capsys.readouterr().out)["fingerprint_hash"] == record["fingerprint_hash"]


def test_capture_cli_is_explicit_and_never_installs_apk(tmp_path, monkeypatch, capsys):
    import talkback_lib
    clients = []
    def factory(**kwargs):
        assert kwargs == {"start_monitor": False}
        client = Client()
        clients.append(client)
        return client
    monkeypatch.setattr(talkback_lib, "A11yAdbClient", factory)
    path = tmp_path / "state_fingerprints.jsonl"
    monkeypatch.setattr(sys, "argv", ["diagnostic", "--capture", "--serial", "serial", "--output", str(path)])
    assert diagnostic.main() == 0
    assert len(clients) == 1
    assert path.exists()


def test_cli_requires_explicit_capture_or_replay(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["diagnostic", "--output", "unused"])
    with pytest.raises(SystemExit) as exc:
        diagnostic.main()
    assert exc.value.code == 2
