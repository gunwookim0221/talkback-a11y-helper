from talkback_lib import A11yAdbClient


def test_play_store_focus_payload_is_not_meaningful():
    node = {
        "packageName": "com.android.vending",
        "text": "Rate this app",
        "accessibilityFocused": True,
    }

    assert A11yAdbClient._is_meaningful_focus_node(node) is False


def test_talkback_ready_reports_play_store_popup_contamination(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    node = {
        "packageName": "com.android.vending",
        "text": "Rate this app",
        "accessibilityFocused": True,
    }

    monkeypatch.setattr(client, "is_talkback_enabled", lambda dev=None: True)
    monkeypatch.setattr(client, "check_helper_status", lambda dev=None: True)
    monkeypatch.setattr(client, "get_focus", lambda **_kwargs: node)
    monkeypatch.setattr("talkback_lib.time.sleep", lambda _seconds: None)

    result = client.check_talkback_ready(dev="SERIAL")

    assert result == {
        "status": "enabled_but_not_ready",
        "reason": "external_popup_contamination",
        "packageName": "com.android.vending",
    }
