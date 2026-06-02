from __future__ import annotations

from tb_runner import core_preflight
from tb_runner.accessibility_preflight import AccessibilityPreflightResult, AccessibilitySettings


class _Client:
    def __init__(self):
        self.serials = []

    def ping(self, dev=None, wait_=3.0):
        self.serials.append(("ping", dev))
        return True

    def check_talkback_ready(self, dev=None):
        self.serials.append(("talkback", dev))
        return {"status": "enabled", "reason": "ok"}


def test_core_preflight_uses_one_serial_for_helper_and_talkback(monkeypatch):
    client = _Client()
    settings = AccessibilitySettings("helper", "1")

    def ensure(**kwargs):
        assert kwargs["serial"] == "SERIAL"
        assert kwargs["helper_ready_check"]() is True
        return AccessibilityPreflightResult(True, "ok", settings, settings, False, True)

    monkeypatch.setattr(core_preflight, "ensure_accessibility_service_enabled", ensure)

    result = core_preflight.run_preflight(client=client, serial="SERIAL", log_fn=lambda _line: None)

    assert result.ok is True
    assert client.serials == [("ping", "SERIAL"), ("talkback", "SERIAL")]

