from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from tb_runner import core_preflight
from tb_runner.accessibility_preflight import AccessibilityPreflightResult, AccessibilitySettings


class _Client:
    def __init__(self):
        self.serials = []
        self.hierarchy_factory = lambda: _snapshot_from_xml(_smartthings_xml())

    def ping(self, dev=None, wait_=3.0):
        self.serials.append(("ping", dev))
        return True

    def check_talkback_ready(self, dev=None):
        self.serials.append(("talkback", dev))
        return {"status": "enabled", "reason": "ok"}

    def dump_hierarchy(self, dev=None):
        self.serials.append(("hierarchy", dev))
        return self.hierarchy_factory()


def _smartthings_foreground() -> str:
    return "mCurrentFocus=Window{abc u0 com.samsung.android.oneconnect/.ui.SCMainActivity}"


def _safe_interaction_state(args):
    responses = {
        ("shell", "dumpsys", "power"): "mWakefulness=Awake",
        ("shell", "dumpsys", "display"): "DisplayViewport{valid=true, isActive=true, displayId=0}\nDisplay State=ON",
        ("shell", "dumpsys", "window", "policy"): "mShowingLockscreen=false\ninputRestricted=false",
        ("shell", "dumpsys", "window", "windows"): "Window #0 Window{app display=0}:\n mDisplayId=0\n package=com.samsung.android.oneconnect\n isOnScreen=true\n isVisible=true",
    }
    output = responses.get(args)
    return (True, output) if output is not None else None


def _successful_adb(_adb_path, serial, *args, timeout=8.0):
    assert serial == "SERIAL"
    if args == ("get-state",):
        return True, "device"
    safe_state = _safe_interaction_state(args)
    if safe_state is not None:
        return safe_state
    if args == ("shell", "dumpsys", "window"):
        return True, _smartthings_foreground()
    if args == ("shell", "dumpsys", "window", "policy"):
        return True, "mShowingLockscreen=false\ninputRestricted=false"
    if args == ("shell", "dumpsys", "power"):
        return True, "mWakefulness=Awake"
    if args == ("shell", "dumpsys", "display"):
        return True, "DisplayViewport{valid=true, isActive=true, displayId=0}\nDisplay State=ON"
    if args == ("shell", "dumpsys", "window", "windows"):
        return True, "Window #0 Window{app display=0}:\n mDisplayId=0\n package=com.samsung.android.oneconnect\n isOnScreen=true\n isVisible=true"
    return True, ""


def _samsung_account_popup_ko_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node text="삼성 계정을 더 안전하게" resource-id="android:id/alertTitle" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[102,1500][978,1600]" />
  <node text="2단계 인증을 설정하면 다른 사람이 내 비밀번호를 알게 되어도 내 계정을 안전하게 보호할 수 있습니다." resource-id="android:id/message" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[102,1640][978,2040]" />
  <node text="나중에" resource-id="android:id/button3" class="android.widget.Button" package="com.samsung.android.oneconnect" bounds="[102,2280][463,2388]" />
  <node text="지금 설정하기" resource-id="android:id/button1" class="android.widget.Button" package="com.samsung.android.oneconnect" bounds="[466,2280][978,2388]" />
</hierarchy>"""


def _smartthings_xml() -> str:
    return f'<hierarchy><node package="{core_preflight.SMARTTHINGS_PACKAGE}" /></hierarchy>'


def _smartthings_ready_xml() -> str:
    return (
        f'<hierarchy><node package="{core_preflight.SMARTTHINGS_PACKAGE}" '
        'resource-id="com.samsung.android.oneconnect:id/bottom_navigation_tab_home" /></hierarchy>'
    )


def _snapshot_from_xml(xml_text: str) -> dict[str, object]:
    document = ET.fromstring(xml_text)

    def convert(element):
        attrs = element.attrib
        return {
            "text": attrs.get("text", ""),
            "contentDescription": attrs.get("content-desc", ""),
            "viewIdResourceName": attrs.get("resource-id", ""),
            "className": attrs.get("class", ""),
            "packageName": attrs.get("package", ""),
            "boundsInScreen": attrs.get("bounds", ""),
            "clickable": attrs.get("clickable", "false") == "true",
            "focusable": attrs.get("focusable", "false") == "true",
            "enabled": attrs.get("enabled", "true") == "true",
            "focused": attrs.get("focused", "false") == "true",
            "selected": attrs.get("selected", "false") == "true",
            "scrollable": attrs.get("scrollable", "false") == "true",
            "visibleToUser": attrs.get("visible-to-user", "true") == "true",
            "children": [convert(child) for child in list(element)],
        }

    roots = [convert(node) for node in document.findall("node")]
    first = roots[0] if roots else {}
    active_root = {
        "text": "",
        "contentDescription": "",
        "viewIdResourceName": "",
        "className": "android.widget.FrameLayout",
        "packageName": first.get("packageName", ""),
        "boundsInScreen": "",
        "children": roots,
    }
    return {
        "success": True,
        "nodes": [active_root],
        "windows": [{"root": active_root, "order": 0, "active": True, "focused": True}],
        "nodeCount": len(roots) + 1,
    }


def test_core_preflight_preserves_earlier_frontend_pid(monkeypatch):
    from talkback_lib.window_lifecycle import configure_window_lifecycle
    from tb_runner.collection_flow import _mark_start_pipeline_talkback_restart
    from types import SimpleNamespace
    monkeypatch.setenv("TB_TALKBACK_PREFLIGHT_PID", "18593")
    client = _Client()
    settings = AccessibilitySettings("helper", "1")
    monkeypatch.setattr(core_preflight, "ensure_accessibility_service_enabled",
                        lambda **kwargs: AccessibilityPreflightResult(True, "ok", settings, settings, False, True))
    result = core_preflight.run_preflight(client=client, serial="SERIAL", log_fn=lambda message: None,
                                         adb_runner=_successful_adb, sleep_fn=lambda seconds: None)
    assert result.ok
    assert client._preflight_talkback_pid == "18593"
    client._run = lambda *a, **kw: "__TB_ACTIVITY__\n__TB_ACCESSIBILITY__\n__TB_PID__\n29833"
    recorder = configure_window_lifecycle(client, "SERIAL", "home_main", None, enabled=True)
    recorder.capture("scenario_start", "SCENARIO_START", step=0)
    start = SimpleNamespace(should_enter_main_loop=True)
    assert _mark_start_pipeline_talkback_restart(client=client, result=start, scenario_id="home_main", phase="scenario_start")
    assert start.failure_reason == "talkback_restarted"
    assert start.should_enter_main_loop is False


def test_core_preflight_uses_one_serial_for_helper_and_talkback(monkeypatch):
    client = _Client()
    settings = AccessibilitySettings("helper", "1")
    logs = []

    def ensure(**kwargs):
        assert kwargs["serial"] == "SERIAL"
        assert kwargs["helper_ready_check"]() is True
        return AccessibilityPreflightResult(True, "ok", settings, settings, False, True)

    monkeypatch.setattr(core_preflight, "ensure_accessibility_service_enabled", ensure)

    result = core_preflight.run_preflight(
        client=client,
        serial="SERIAL",
        log_fn=logs.append,
        adb_runner=_successful_adb,
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is True
    assert client.serials[0] == ("ping", "SERIAL")
    assert client.serials[-1] == ("talkback", "SERIAL")
    assert any(call == ("hierarchy", "SERIAL") for call in client.serials)
    assert result.screen_awake["status"] == "PASS"
    assert result.unlock_swipe["status"] == "PASS"
    assert result.screen_awake["action_attempted"] is False
    assert result.unlock_swipe["action_attempted"] is False
    assert result.app_foreground["status"] == "PASS"
    assert (
        "[PREFLIGHT] wake_screen PASS "
        "message='Display already interactive; wake input skipped'"
    ) in logs
    assert (
        "[PREFLIGHT] unlock_swipe PASS "
        "message='Keyguard clear and no blocking SystemUI overlay; unlock input skipped'"
    ) in logs
    assert (
        "[PREFLIGHT] app_foreground PASS "
        "message='SmartThings foreground confirmed'"
    ) in logs
    assert any("samsung_account_security detected=false" in line for line in logs)


def test_core_preflight_dismisses_internal_samsung_account_popup_after_foreground_pass(monkeypatch):
    client = _Client()
    settings = AccessibilitySettings("helper", "1")
    commands = []
    dumped_popup = {"active": True}
    logs = []

    def adb_runner(_adb_path, serial, *args, timeout=8.0):
        assert serial == "SERIAL"
        commands.append(args)
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window"):
            return True, _smartthings_foreground()
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=false\ninputRestricted=false"
        if args == ("shell", "dumpsys", "power"):
            return True, "mWakefulness=Awake"
        if args == ("shell", "dumpsys", "display"):
            return True, "DisplayViewport{valid=true, isActive=true, displayId=0}\nDisplay State=ON"
        if args == ("shell", "dumpsys", "window", "windows"):
            return True, "Window #0 Window{app display=0}:\n mDisplayId=0\n package=com.samsung.android.oneconnect\n isOnScreen=true\n isVisible=true"
        if args == ("shell", "input", "tap", "282", "2334"):
            dumped_popup["active"] = False
            return True, ""
        return True, ""

    client.hierarchy_factory = lambda: _snapshot_from_xml(
        _samsung_account_popup_ko_xml() if dumped_popup["active"] else _smartthings_xml()
    )

    monkeypatch.setattr(
        core_preflight,
        "ensure_accessibility_service_enabled",
        lambda **kwargs: AccessibilityPreflightResult(
            True, "ok", settings, settings, False, bool(kwargs["helper_ready_check"]())
        ),
    )

    result = core_preflight.run_preflight(
        client=client,
        serial="SERIAL",
        log_fn=logs.append,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is True
    assert ("shell", "input", "tap", "282", "2334") in commands
    assert ("shell", "input", "tap", "722", "2334") not in commands
    assert result.app_foreground["internal_popup_check"]["detected"] is True
    assert result.app_foreground["internal_popup_check"]["dismissed"] is True
    assert any(
        "[PREFLIGHT][popup] samsung_account_security detected=true locale='ko' title='삼성 계정을 더 안전하게'"
        in line
        for line in logs
    )
    assert any(
        "[PREFLIGHT][popup] samsung_account_security dismiss method=resource_id target='android:id/button3' label='나중에' ok=true"
        in line
        for line in logs
    )


def test_wake_screen_skips_input_when_interactive_unlocked_gate_passes():
    sleeps = []

    result = core_preflight.wake_screen(
        serial="SERIAL",
        adb_runner=_successful_adb,
        sleep_fn=sleeps.append,
    )

    assert result["status"] == "PASS"
    assert result["action_attempted"] is False
    assert "wake input skipped" in result["message"]
    assert sleeps == []


def test_unlock_swipe_skips_input_when_interactive_unlocked_gate_passes():
    commands = []
    sleeps = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        return _successful_adb(_adb_path, "SERIAL", *args, timeout=timeout)

    result = core_preflight.unlock_swipe(
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=sleeps.append,
    )

    assert not any(args[:2] == ("shell", "input") for args in commands)
    assert result["status"] == "PASS"
    assert result["action_attempted"] is False
    assert result["keyguard_active"] is False
    assert sleeps == []


def test_unlock_swipe_fails_closed_when_keyguard_state_cannot_be_verified():
    commands = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        return True, ""

    result = core_preflight.unlock_swipe(
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "FAIL"
    assert result["action_attempted"] is False
    assert result["keyguard_active"] is None
    assert not any(args[:2] == ("shell", "input") for args in commands)


def test_core_preflight_stops_when_interaction_state_is_unknown_before_input(monkeypatch):
    client = _Client()
    commands = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("get-state",):
            return True, "device"
        return True, ""

    monkeypatch.setattr(
        core_preflight,
        "ensure_accessibility_service_enabled",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("helper preflight must not run")),
    )

    result = core_preflight.run_preflight(
        client=client,
        serial="SERIAL",
        log_fn=lambda _line: None,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "device_interaction_precondition_failed"
    assert result.screen_awake["status"] == "FAIL"
    assert result.screen_awake["action_attempted"] is False
    assert result.unlock_swipe["status"] == "FAIL"
    assert result.unlock_swipe["action_attempted"] is False
    assert not any(command[:2] == ("shell", "input") for command in commands)
    assert client.serials == []


def test_core_preflight_stops_when_device_is_not_connected(monkeypatch):
    client = _Client()

    monkeypatch.setattr(
        core_preflight,
        "ensure_accessibility_service_enabled",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("helper preflight must not run")),
    )

    result = core_preflight.run_preflight(
        client=client,
        serial="SERIAL",
        log_fn=lambda _line: None,
        adb_runner=lambda _adb_path, _serial, *args, timeout=8.0: (False, "device offline"),
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "device_connected_failed"
    assert result.device_connected["status"] == "FAIL"
    assert result.screen_awake["status"] == "NOT_RUN"


def test_core_preflight_locked_keyguard_blocks_before_input(monkeypatch):
    client = _Client()
    settings = AccessibilitySettings("helper", "1")
    commands = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window"):
            return True, _smartthings_foreground()
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=true\ninputRestricted=true"
        if args == ("shell", "dumpsys", "power"):
            return True, "mWakefulness=Awake"
        if args == ("shell", "dumpsys", "display"):
            return True, "DisplayViewport{valid=true, isActive=true, displayId=0}\nDisplay State=ON"
        if args == ("shell", "dumpsys", "window", "windows"):
            return True, ""
        return True, ""

    monkeypatch.setattr(
        core_preflight,
        "ensure_accessibility_service_enabled",
        lambda **kwargs: AccessibilityPreflightResult(
            True, "ok", settings, settings, False, bool(kwargs["helper_ready_check"]())
        ),
    )

    result = core_preflight.run_preflight(
        client=client,
        serial="SERIAL",
        log_fn=lambda _line: None,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "device_interaction_precondition_failed"
    assert result.unlock_swipe["status"] == "FAIL"
    assert result.unlock_swipe["action_attempted"] is False
    assert not any(command[:2] == ("shell", "input") for command in commands)
    assert client.serials == []


def test_core_preflight_visible_systemui_overlay_blocks_before_input(monkeypatch):
    client = _Client()
    commands = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "power"):
            return True, "mWakefulness=Awake"
        if args == ("shell", "dumpsys", "display"):
            return True, "DisplayViewport{valid=true, isActive=true, displayId=0}\nDisplay State=ON"
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=false\ninputRestricted=false"
        if args == ("shell", "dumpsys", "window", "windows"):
            return True, (
                "Window #3 Window{bouncer Bouncer}:\n"
                " mDisplayId=0\n package=com.android.systemui\n"
                " isOnScreen=true\n isVisible=true"
            )
        return True, _smartthings_foreground()

    monkeypatch.setattr(
        core_preflight, "ensure_accessibility_service_enabled",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must stop before helper setup")),
    )
    result = core_preflight.run_preflight(
        client=client, serial="SERIAL", log_fn=lambda _line: None,
        adb_runner=adb_runner, sleep_fn=lambda _seconds: None,
    )
    assert result.ok is False
    assert result.reason == "device_interaction_precondition_failed"
    assert result.unlock_swipe["systemui_overlay_clear"] is False
    assert result.unlock_swipe["action_attempted"] is False
    assert not any(args[:2] == ("shell", "input") for args in commands)


def test_foreground_launches_smartthings_when_another_app_is_active():
    commands = []
    focus_values = [
        "mCurrentFocus=Window{abc u0 com.example.other/.MainActivity}",
        _smartthings_foreground(),
    ]

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("shell", "dumpsys", "window"):
            return True, focus_values.pop(0)
        return True, ""

    result = core_preflight.ensure_smartthings_foreground(
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "PASS"
    assert result["launch_attempted"] is True
    assert (
        "shell", "monkey", "-p", core_preflight.SMARTTHINGS_PACKAGE,
        "-c", "android.intent.category.LAUNCHER", "1",
    ) in commands


def test_foreground_uses_display_zero_before_inactive_cover_systemui():
    commands = []
    window_dump = """
WINDOW MANAGER DISPLAY CONTENTS
Display: mDisplayId=1 (organized)
  mCurrentFocus=null
  mFocusedApp=ActivityRecord{cover u0 com.android.systemui/.subscreen.SubHomeActivity t7}
  displayId=1
Display: mDisplayId=0 (organized)
  mCurrentFocus=Window{primary u0 com.samsung.android.oneconnect/com.samsung.android.oneconnect.webplugin.WebPluginActivity}
  mFocusedApp=ActivityRecord{primary u0 com.samsung.android.oneconnect/.webplugin.WebPluginActivity t1547}
  displayId=0
"""

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=false"
        if args == ("shell", "dumpsys", "window"):
            return True, window_dump
        if args[:2] == ("shell", "monkey"):
            raise AssertionError("must not launch when display 0 is already SmartThings")
        return True, ""

    result = core_preflight.ensure_smartthings_foreground(
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "PASS"
    assert result["package"] == core_preflight.SMARTTHINGS_PACKAGE
    assert result["launch_attempted"] is False
    assert not any(args[:2] == ("shell", "monkey") for args in commands)


def test_core_preflight_stops_when_smartthings_foreground_is_not_confirmed(monkeypatch):
    client = _Client()

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        safe_state = _safe_interaction_state(args)
        if safe_state is not None:
            return safe_state
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=false"
        if args == ("shell", "dumpsys", "window"):
            return True, "mCurrentFocus=Window{abc u0 com.example.other/.MainActivity}"
        if args == ("shell", "dumpsys", "activity", "activities"):
            return True, "ResumedActivity: ActivityRecord{abc u0 com.example.other/.MainActivity}"
        return True, ""

    monkeypatch.setattr(
        core_preflight,
        "ensure_accessibility_service_enabled",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("helper preflight must not run")),
    )

    result = core_preflight.run_preflight(
        client=client,
        serial="SERIAL",
        log_fn=lambda _line: None,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "app_foreground_failed"
    assert result.app_foreground["status"] == "FAIL"
    assert "keyguard/lockscreen not detected" in result.app_foreground["message"]
    assert client.serials == []


def test_foreground_failure_mentions_keyguard_when_lockscreen_remains():
    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=true"
        if args == ("shell", "dumpsys", "window"):
            return True, "mCurrentFocus=Window{abc u0 com.example.other/.MainActivity}"
        if args == ("shell", "dumpsys", "activity", "activities"):
            return True, "ResumedActivity: ActivityRecord{abc u0 com.example.other/.MainActivity}"
        return True, ""

    result = core_preflight.ensure_smartthings_foreground(
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "FAIL"
    assert result["keyguard_active"] is True
    assert "keyguard/lockscreen may still be active" in result["message"]


def test_core_preflight_recovers_play_store_popup_after_foreground_pass(monkeypatch):
    client = _Client()
    settings = AccessibilitySettings("helper", "1")
    commands = []
    uia_packages = ["com.android.vending", core_preflight.SMARTTHINGS_PACKAGE]
    client.hierarchy_factory = lambda: _snapshot_from_xml(
        f'<hierarchy><node package="{uia_packages.pop(0) if uia_packages else core_preflight.SMARTTHINGS_PACKAGE}" /></hierarchy>'
    )
    logs = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        safe_state = _safe_interaction_state(args)
        if safe_state is not None:
            return safe_state
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=false"
        if args == ("shell", "dumpsys", "window"):
            return True, _smartthings_foreground()
        return True, ""

    monkeypatch.setattr(
        core_preflight,
        "ensure_accessibility_service_enabled",
        lambda **kwargs: AccessibilityPreflightResult(
            True, "ok", settings, settings, False, bool(kwargs["helper_ready_check"]())
        ),
    )

    result = core_preflight.run_preflight(
        client=client,
        serial="SERIAL",
        log_fn=logs.append,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is True
    assert ("shell", "input", "keyevent", "KEYCODE_BACK") in commands
    assert "[PREFLIGHT][popup] contamination package='com.android.vending'" in logs
    assert "[PREFLIGHT][popup] recovery='back_or_relaunch'" in logs
    assert "[PREFLIGHT][popup] recovered=true method='back'" in logs


def test_core_preflight_recovers_play_store_before_app_foreground_failure(monkeypatch):
    client = _Client()
    settings = AccessibilitySettings("helper", "1")
    commands = []
    recovered = False
    logs = []
    client.hierarchy_factory = lambda: _snapshot_from_xml(
        f'<hierarchy><node package="{core_preflight.SMARTTHINGS_PACKAGE if recovered else "com.android.vending"}" /></hierarchy>'
    )

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        nonlocal recovered
        commands.append(args)
        safe_state = _safe_interaction_state(args)
        if safe_state is not None:
            return safe_state
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=false"
        if args == ("shell", "dumpsys", "window"):
            package = core_preflight.SMARTTHINGS_PACKAGE if recovered else "com.android.vending"
            return True, f"mCurrentFocus=Window{{abc u0 {package}/.MainActivity}}"
        if args == ("shell", "input", "keyevent", "KEYCODE_BACK"):
            recovered = True
        return True, ""

    monkeypatch.setattr(
        core_preflight,
        "ensure_accessibility_service_enabled",
        lambda **kwargs: AccessibilityPreflightResult(
            True, "ok", settings, settings, False, bool(kwargs["helper_ready_check"]())
        ),
    )

    result = core_preflight.run_preflight(
        client=client,
        serial="SERIAL",
        log_fn=logs.append,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is True
    assert result.app_foreground["status"] == "PASS"
    assert "[PREFLIGHT][popup] contamination package='com.android.vending'" in logs
    assert "[PREFLIGHT][popup] recovery='back_or_relaunch'" in logs
    assert "[PREFLIGHT][popup] recovered=true method='back'" in logs
    assert not any("app_foreground FAIL" in line for line in logs)


def test_core_preflight_reports_popup_reason_when_early_recovery_fails(monkeypatch):
    client = _Client()
    client.hierarchy_factory = lambda: _snapshot_from_xml(
        '<hierarchy><node package="com.android.vending" /></hierarchy>'
    )
    logs = []
    settings = AccessibilitySettings("helper", "1")
    monkeypatch.setattr(
        core_preflight, "ensure_accessibility_service_enabled",
        lambda **kwargs: AccessibilityPreflightResult(True, "ok", settings, settings, False, True),
    )

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        safe_state = _safe_interaction_state(args)
        if safe_state is not None:
            return safe_state
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window"):
            return True, "mCurrentFocus=Window{abc u0 com.android.vending/.MainActivity}"
        return True, ""

    result = core_preflight.run_preflight(
        client=client,
        serial="SERIAL",
        log_fn=logs.append,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "external_popup_contamination"
    assert "[PREFLIGHT][popup] recovered=false method='force_stop_external_and_relaunch'" in logs
    assert not any("app_foreground FAIL" in line for line in logs)


def test_popup_recovery_fails_when_play_store_contamination_remains():
    commands = []
    client = _Client()
    client.hierarchy_factory = lambda: _snapshot_from_xml(
        '<hierarchy><node package="com.android.vending" /></hierarchy>'
    )

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("shell", "dumpsys", "window"):
            return True, _smartthings_foreground()
        return True, ""

    result = core_preflight.recover_external_popup_contamination(
        client=client,
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "FAIL"
    assert result["recovered"] is False
    assert result["surface_recovered"] is False
    assert result["reason"] == "external_popup_contamination"
    assert result["contamination_package"] == "com.android.vending"
    assert result["final_contamination_package"] == "com.android.vending"
    assert result["after_contamination_package"] == "com.android.vending"
    assert ("shell", "input", "keyevent", "KEYCODE_BACK") in commands
    assert (
        "shell", "monkey", "-p", core_preflight.SMARTTHINGS_PACKAGE,
        "-c", "android.intent.category.LAUNCHER", "1",
    ) in commands
    assert ("shell", "am", "force-stop", "com.android.vending") in commands
    assert ("shell", "am", "force-stop", "com.google.android.finsky") in commands
    assert result["recovery"] == "force_stop_external_and_relaunch"


def test_popup_recovery_force_stop_fallback_relaunches_smartthings():
    commands = []
    external_stopped = False
    sleeps = []
    logs = []
    client = _Client()

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        nonlocal external_stopped
        commands.append(args)
        if args == ("shell", "dumpsys", "window"):
            package = core_preflight.SMARTTHINGS_PACKAGE if external_stopped else "com.android.vending"
            return True, f"mCurrentFocus=Window{{abc u0 {package}/.MainActivity}}"
        if args == ("shell", "am", "force-stop", "com.android.vending"):
            external_stopped = True
        return True, ""

    result = core_preflight.recover_external_popup_contamination(
        client=client,
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=sleeps.append,
    )

    assert result["status"] == "PASS"
    assert result["recovered"] is True
    assert result["recovery"] == "force_stop_external_and_relaunch"
    assert ("shell", "am", "force-stop", "com.android.vending") in commands
    assert ("shell", "am", "force-stop", "com.google.android.finsky") in commands
    assert commands.count(
        (
            "shell", "monkey", "-p", core_preflight.SMARTTHINGS_PACKAGE,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
    ) == 2
    assert sleeps == [0.7, 3.0, 1.5]
    core_preflight._log_popup_recovery(logs.append, result)
    assert (
        "[PREFLIGHT][popup] recovered=true "
        "method='force_stop_external_and_relaunch'"
    ) in logs


def test_popup_recovery_dismisses_review_sheet_not_now_as_last_fallback():
    commands = []
    dismissed = False
    logs = []
    client = _Client()

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        nonlocal dismissed
        commands.append(args)
        if args == ("shell", "dumpsys", "window"):
            package = core_preflight.SMARTTHINGS_PACKAGE if dismissed else "com.android.vending"
            return True, f"mCurrentFocus=Window{{abc u0 {package}/.MainActivity}}"
        if args == ("shell", "input", "tap", "280", "1875"):
            dismissed = True
        return True, ""

    client.hierarchy_factory = lambda: _snapshot_from_xml(
        f'<hierarchy><node package="{core_preflight.SMARTTHINGS_PACKAGE}" '
        'resource-id="com.samsung.android.oneconnect:id/bottom_navigation_tab_home" /></hierarchy>'
        if dismissed
        else '<hierarchy><node package="com.android.vending" text="Submit" bounds="[600,1800][1000,1950]" />'
             '<node package="com.android.vending" content-desc="Not now" bounds="[80,1800][480,1950]" /></hierarchy>'
    )

    result = core_preflight.recover_external_popup_contamination(
        client=client,
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "PASS"
    assert result["recovery"] == "dismiss_review_sheet"
    assert ("shell", "input", "tap", "280", "1875") in commands
    assert ("shell", "input", "tap", "800", "1875") not in commands
    core_preflight._log_popup_recovery(logs.append, result)
    assert "[PREFLIGHT][popup] recovered=true method='dismiss_review_sheet'" in logs


def test_popup_recovery_does_not_tap_not_now_without_review_sheet_submit():
    commands = []
    client = _Client()

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("shell", "dumpsys", "window"):
            return True, "mCurrentFocus=Window{abc u0 com.android.vending/.MainActivity}"
        return True, ""

    client.hierarchy_factory = lambda: _snapshot_from_xml(
        '<hierarchy><node package="com.android.vending" text="Not now" bounds="[80,1800][480,1950]" /></hierarchy>'
    )

    result = core_preflight.recover_external_popup_contamination(
        client=client,
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "FAIL"
    assert not any(args[:3] == ("shell", "input", "tap") for args in commands)


def test_latest_clean_surface_is_recovery_even_without_review_sheet_candidate():
    client = _Client()
    client.hierarchy_factory = lambda: _snapshot_from_xml(_smartthings_ready_xml())
    commands = []

    def adb_runner(_adb_path, serial, *args, timeout=8.0):
        commands.append(args)
        return _successful_adb(_adb_path, serial, *args, timeout=timeout)

    result = core_preflight._dismiss_review_sheet_not_now(
        client=client, serial="SERIAL", adb_path=core_preflight.DEFAULT_ADB_PATH,
        adb_runner=adb_runner, sleep_fn=lambda _seconds: None, settle_seconds=0,
    )

    assert result["recovered"] is True
    assert result["surface_recovered"] is True
    assert result["recovery_action_attempted"] is False
    assert result["recovery_action_succeeded"] is False
    assert result["recovery"] == "surface_already_clean"
    assert result["after"]["foreground_package"] == core_preflight.SMARTTHINGS_PACKAGE
    assert result["after"]["hierarchy_ok"] is True
    assert result["after"]["bottom_tab_present"] is True
    assert not any(args[:3] == ("shell", "input", "tap") for args in commands)


def test_latest_clean_surface_at_final_read_is_accepted_without_dismiss_candidate(monkeypatch):
    client = _Client()
    reads = 0

    def hierarchy_factory():
        nonlocal reads
        reads += 1
        if reads < 5:
            return _snapshot_from_xml(
                '<hierarchy><node package="com.android.vending" /></hierarchy>'
            )
        return _snapshot_from_xml(_smartthings_ready_xml())

    client.hierarchy_factory = hierarchy_factory
    logs = []
    commands = []

    def adb_runner(adb_path, serial, *args, timeout=8.0):
        commands.append(args)
        return _successful_adb(adb_path, serial, *args, timeout=timeout)

    monkeypatch.setattr(
        core_preflight,
        "ensure_smartthings_foreground",
        lambda **_kwargs: core_preflight._step_result(
            "PASS", "SmartThings foreground", package=core_preflight.SMARTTHINGS_PACKAGE,
        ),
    )
    _enable_core_preflight_for_rf5r9(monkeypatch)

    result = core_preflight.run_preflight(
        client=client, serial="SERIAL", log_fn=logs.append,
        adb_runner=adb_runner, sleep_fn=lambda _seconds: None,
    )

    assert reads >= 5
    assert result.ok is True
    popup = result.app_foreground["popup_check"]
    assert popup["before_contamination_package"] == "com.android.vending"
    assert popup["after_contamination_package"] is None
    assert popup["final_contamination_package"] is None
    assert popup["contamination_package"] is None
    assert popup["reason"] == "ok"
    assert popup["recovered"] is True
    assert popup["surface_recovered"] is True
    assert popup["recovery"] == "surface_observed_clean"
    assert popup["recovery_action_attempted"] is True
    assert not any(args[:3] == ("shell", "input", "tap") for args in commands)
    diagnostic = next(line for line in logs if "[PREFLIGHT][readiness]" in line)
    assert "READINESS_RESULT='PASS'" in diagnostic
    assert "BEFORE_CONTAMINATION_PACKAGE='com.android.vending'" in diagnostic
    assert "FINAL_CONTAMINATION_PACKAGE=''" in diagnostic
    assert "SURFACE_RECOVERED='true'" in diagnostic


def test_review_sheet_dismiss_accepts_current_clean_surface_after_tap():
    dismissed = False
    client = _Client()

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        nonlocal dismissed
        if args == ("shell", "dumpsys", "window"):
            package = core_preflight.SMARTTHINGS_PACKAGE if dismissed else "com.android.vending"
            return True, f"mCurrentFocus=Window{{abc u0 {package}/.MainActivity}}"
        if args == ("shell", "input", "tap", "280", "1875"):
            dismissed = True
        return True, ""

    client.hierarchy_factory = lambda: _snapshot_from_xml(
        f'<hierarchy><node package="{core_preflight.SMARTTHINGS_PACKAGE}" /></hierarchy>'
        if dismissed
        else '<hierarchy><node package="com.android.vending" text="Submit" bounds="[600,1800][1000,1950]" />'
             '<node package="com.android.vending" text="Not now" bounds="[80,1800][480,1950]" /></hierarchy>'
    )

    result = core_preflight.recover_external_popup_contamination(
        client=client,
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "PASS"
    assert result["surface_recovered"] is True
    assert result["final_contamination_package"] is None
    assert result["recovery"] == "dismiss_review_sheet"


def _enable_core_preflight_for_rf5r9(monkeypatch):
    settings = AccessibilitySettings("helper", "1")
    monkeypatch.setattr(
        core_preflight,
        "ensure_accessibility_service_enabled",
        lambda **kwargs: AccessibilityPreflightResult(
            True, "ok", settings, settings, False, bool(kwargs["helper_ready_check"]())
        ),
    )


def test_preflight_hierarchy_exception_fails_closed_without_popup_misclassification(monkeypatch):
    client = _Client()
    logs = []
    client.hierarchy_factory = lambda: (_ for _ in ()).throw(
        RuntimeError("HIERARCHY_SNAPSHOT:TRANSPORT_ERROR:END_TO_END_TIMEOUT req_id=req-current")
    )
    _enable_core_preflight_for_rf5r9(monkeypatch)

    result = core_preflight.run_preflight(
        client=client, serial="SERIAL", log_fn=logs.append,
        adb_runner=_successful_adb, sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "service_hierarchy_acquisition_failed"
    assert result.reason != "external_popup_contamination"
    assert result.talkback_status == "unknown"
    assert not any(call[0] == "talkback" for call in client.serials)
    popup = result.app_foreground["popup_check"]
    assert popup["contamination_package"] is None
    assert popup["before"]["hierarchy_error_type"] == "RuntimeError"
    assert "END_TO_END_TIMEOUT" in popup["before"]["hierarchy_error_message"]
    assert popup["before"]["hierarchy_request_id"] == "req-current"
    assert popup["before"]["hierarchy_failure_stage"] == "dump_hierarchy"
    diagnostic = next(line for line in logs if "[PREFLIGHT][readiness]" in line)
    assert "READINESS_RESULT='service_hierarchy_acquisition_failed'" in diagnostic
    assert "HIERARCHY_ERROR_TYPE='RuntimeError'" in diagnostic
    assert "HIERARCHY_ERROR_MESSAGE='HIERARCHY_SNAPSHOT:TRANSPORT_ERROR:END_TO_END_TIMEOUT req_id=req-current'" in diagnostic
    assert "CONTAMINATION_PACKAGE=''" in diagnostic


def test_preflight_empty_hierarchy_fails_closed_as_surface_failure_not_popup(monkeypatch):
    client = _Client()
    client.hierarchy_factory = lambda: {"success": True, "nodes": [], "windows": []}
    _enable_core_preflight_for_rf5r9(monkeypatch)

    result = core_preflight.run_preflight(
        client=client, serial="SERIAL", log_fn=lambda _line: None,
        adb_runner=_successful_adb, sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "service_hierarchy_acquisition_failed"
    popup = result.app_foreground["popup_check"]
    assert popup["reason"] == "service_hierarchy_acquisition_failed"
    assert popup["contamination_package"] is None
    assert popup["before"]["hierarchy_ok"] is False
    assert popup["before"]["hierarchy_root_result"] == "FAIL"
    assert popup["before"]["hierarchy_error_type"] == "ValueError"


def test_fresh_clean_surface_overrides_stale_external_popup_hint():
    client = _Client()
    commands = []

    def adb_runner(_adb_path, serial, *args, timeout=8.0):
        commands.append(args)
        return _successful_adb(_adb_path, serial, *args, timeout=timeout)

    result = core_preflight.recover_external_popup_contamination(
        client=client,
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
        contamination_hint="com.android.vending",
        contamination_hint_current=True,
        contamination_hint_source="stale_previous_observation",
    )

    assert result["status"] == "PASS"
    assert result["recovery_attempted"] is False
    assert result["contamination_package"] is None
    assert result["contamination_hint"] == "com.android.vending"
    assert result["contamination_evidence_source"] == "current_clean_observation"
    assert ("shell", "input", "keyevent", "KEYCODE_BACK") not in commands


def test_current_google_play_package_still_confirms_external_contamination():
    client = _Client()
    client.hierarchy_factory = lambda: _snapshot_from_xml(
        '<hierarchy><node package="com.android.vending" /></hierarchy>'
    )
    result = core_preflight.recover_external_popup_contamination(
        client=client, serial="SERIAL", adb_runner=_successful_adb,
        sleep_fn=lambda _seconds: None,
    )

    assert result["reason"] == "external_popup_contamination"
    assert result["contamination_package"] == "com.android.vending"
    assert result["contamination_evidence_source"] == "hierarchy_package"
    assert core_preflight.EXTERNAL_POPUP_PACKAGES == {
        "com.android.vending", "com.google.android.finsky",
    }


def test_talkback_contamination_recovery_receives_current_client(monkeypatch):
    client = _Client()
    observed_clients = []
    original_recovery = core_preflight.recover_external_popup_contamination

    def recovery_spy(**kwargs):
        observed_clients.append((kwargs.get("client"), kwargs.get("contamination_hint_source")))
        return original_recovery(**kwargs)

    responses = iter([
        {"status": "enabled_but_not_ready", "reason": "external_popup_contamination", "packageName": "com.android.vending"},
        {"status": "enabled", "reason": "ok"},
    ])
    client.check_talkback_ready = lambda dev=None: next(responses)
    monkeypatch.setattr(core_preflight, "recover_external_popup_contamination", recovery_spy)
    _enable_core_preflight_for_rf5r9(monkeypatch)

    result = core_preflight.run_preflight(
        client=client, serial="SERIAL", log_fn=lambda _line: None,
        adb_runner=_successful_adb, sleep_fn=lambda _seconds: None,
    )

    assert result.ok is True
    assert observed_clients[-1] == (client, "talkback_focus")


def test_missing_popup_recovery_client_has_dependency_specific_fail_closed_result():
    commands = []

    def adb_runner(_adb_path, serial, *args, timeout=8.0):
        commands.append(args)
        return _successful_adb(_adb_path, serial, *args, timeout=timeout)

    result = core_preflight.recover_external_popup_contamination(
        client=None, serial="SERIAL", adb_runner=adb_runner,
        contamination_hint="com.android.vending", contamination_hint_current=True,
    )

    assert result["status"] == "FAIL"
    assert result["reason"] == "readiness_recovery_dependency_unavailable"
    assert result["contamination_package"] is None
    assert result["contamination_evidence_source"] == "hint_only_suspicion"
    assert result["before"]["hierarchy_error_type"] == "MissingDependency"
    assert ("shell", "input", "keyevent", "KEYCODE_BACK") not in commands


def _unknown_package_adb(_adb_path, serial, *args, timeout=8.0):
    assert serial == "SERIAL"
    safe_state = _safe_interaction_state(args)
    if safe_state is not None:
        return safe_state
    if args == ("get-state",):
        return True, "device"
    if args == ("shell", "dumpsys", "window", "policy"):
        return True, "mShowingLockscreen=false"
    if args in {
        ("shell", "dumpsys", "window"),
        ("shell", "dumpsys", "activity", "activities"),
    }:
        return True, ""
    return True, ""


def _raise_hierarchy_error(message):
    raise RuntimeError(message)


def test_current_unknown_surface_with_hint_is_suspicion_only_in_normal_preflight(monkeypatch):
    client = _Client()
    client.hierarchy_factory = lambda: _raise_hierarchy_error(
        "HIERARCHY_SNAPSHOT:TRANSPORT_ERROR:PFD_READ_FAILED req_id=req-unknown"
    )
    logs = []
    commands = []

    def adb_runner(adb_path, serial, *args, timeout=8.0):
        commands.append(args)
        return _unknown_package_adb(adb_path, serial, *args, timeout=timeout)

    monkeypatch.setattr(
        core_preflight,
        "ensure_smartthings_foreground",
        lambda **_kwargs: core_preflight._step_result(
            "FAIL", "foreground observed Google Play", package="com.android.vending",
        ),
    )
    _enable_core_preflight_for_rf5r9(monkeypatch)

    result = core_preflight.run_preflight(
        client=client, serial="SERIAL", log_fn=logs.append,
        adb_runner=adb_runner, sleep_fn=lambda _seconds: None,
    )

    popup = result.app_foreground["popup_check"]
    assert result.ok is False
    assert result.reason == "service_hierarchy_acquisition_failed"
    assert popup["reason"] == "service_hierarchy_acquisition_failed"
    assert popup["contamination_hint"] == "com.android.vending"
    assert popup["contamination_hint_current"] is True
    assert popup["contamination_hint_source"] == "app_foreground"
    assert popup["contamination_package"] is None
    assert popup["contamination_evidence_source"] == "hint_only_suspicion"
    assert popup["before"]["foreground_package"] is None
    assert popup["before"]["hierarchy_package"] is None
    assert popup["before"]["hierarchy_focused_package"] is None
    assert popup["before"]["hierarchy_ok"] is False
    assert ("shell", "input", "keyevent", "KEYCODE_BACK") not in commands
    diagnostic = next(line for line in logs if "[PREFLIGHT][readiness]" in line)
    assert "CONTAMINATION_HINT='com.android.vending'" in diagnostic
    assert "CONTAMINATION_HINT_CURRENT='true'" in diagnostic
    assert "CONTAMINATION_PACKAGE=''" in diagnostic


@pytest.mark.parametrize(
    ("package", "source"),
    [
        (package, source)
        for package in ("com.android.vending", "com.google.android.finsky")
        for source in ("foreground_package", "hierarchy_focused_package", "hierarchy_package")
    ],
)
def test_current_google_play_evidence_from_each_approved_source_is_detected(package, source):
    client = _Client()
    snapshots = iter(
        [
            _snapshot_from_xml(
                f'<hierarchy><node package="{package}" focused="true" /></hierarchy>'
                if source == "hierarchy_focused_package"
                else f'<hierarchy><node package="{package}" /></hierarchy>'
                if source == "hierarchy_package"
                else _smartthings_xml()
            ),
            _snapshot_from_xml(_smartthings_xml()),
        ]
    )
    client.hierarchy_factory = lambda: next(snapshots)
    window_reads = 0

    def adb_runner(_adb_path, serial, *args, timeout=8.0):
        nonlocal window_reads
        if args == ("shell", "dumpsys", "window"):
            window_reads += 1
            if source == "foreground_package" and window_reads == 1:
                return True, f"mCurrentFocus=Window{{abc u0 {package}/.Popup}}"
            return True, _smartthings_foreground()
        if args == ("shell", "dumpsys", "activity", "activities"):
            return True, ""
        return True, ""

    result = core_preflight.recover_external_popup_contamination(
        client=client, serial="SERIAL", adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "PASS"
    assert result["recovery_attempted"] is True
    assert result["contamination_package"] is None
    assert result["before_contamination_package"] == package
    assert result["after_contamination_package"] is None
    assert result["final_contamination_package"] is None
    assert result["contamination_evidence_source"] == source
    assert result["final_contamination_evidence_source"] is None
    assert result["surface_recovered"] is True
    assert result["recovery_action_attempted"] is True
    assert result["final_observation"] == result["after"]
    assert result["after"]["foreground_package"] == core_preflight.SMARTTHINGS_PACKAGE
    assert result["after"]["hierarchy_ok"] is True


def test_latest_recovery_hierarchy_failure_drives_final_diagnostic(monkeypatch):
    client = _Client()
    reads = 0

    def hierarchy_factory():
        nonlocal reads
        reads += 1
        if reads == 5:
            return _raise_hierarchy_error(
                "HIERARCHY_SNAPSHOT:TRANSPORT_ERROR:PFD_READ_FAILED req_id=req-latest operation_id=op-latest"
            )
        return _snapshot_from_xml(
            '<hierarchy><node package="com.android.vending" /></hierarchy>'
        )

    client.hierarchy_factory = hierarchy_factory
    logs = []
    monkeypatch.setattr(
        core_preflight,
        "ensure_smartthings_foreground",
        lambda **_kwargs: core_preflight._step_result(
            "PASS", "SmartThings foreground", package=core_preflight.SMARTTHINGS_PACKAGE,
        ),
    )
    _enable_core_preflight_for_rf5r9(monkeypatch)

    result = core_preflight.run_preflight(
        client=client, serial="SERIAL", log_fn=logs.append,
        adb_runner=_unknown_package_adb, sleep_fn=lambda _seconds: None,
    )

    assert reads == 5
    assert result.ok is False
    assert result.reason == "service_hierarchy_acquisition_failed"
    popup = result.app_foreground["popup_check"]
    assert popup["before"]["hierarchy_ok"] is True
    assert popup["before_contamination_package"] == "com.android.vending"
    assert popup["after"]["hierarchy_ok"] is False
    assert popup["after_contamination_package"] is None
    assert popup["contamination_package"] is None
    assert popup["final_contamination_package"] is None
    assert popup["reason"] == "service_hierarchy_acquisition_failed"
    assert popup["recovered"] is False
    assert popup["surface_recovered"] is False
    assert popup["final_observation"] == popup["after"]
    assert popup["after"]["hierarchy_error_type"] == "RuntimeError"
    assert "PFD_READ_FAILED" in popup["after"]["hierarchy_error_message"]
    assert popup["after"]["hierarchy_failure_stage"] == "dump_hierarchy"
    assert popup["after"]["hierarchy_transport_status"] == "TRANSPORT_ERROR"
    assert popup["after"]["hierarchy_request_id"] == "req-latest"
    assert popup["after"]["hierarchy_operation_id"] == "op-latest"
    diagnostic = next(line for line in logs if "[PREFLIGHT][readiness]" in line)
    assert "FINAL_OBSERVATION='after'" in diagnostic
    assert "BEFORE_HIERARCHY_OK='true'" in diagnostic
    assert "AFTER_HIERARCHY_OK='false'" in diagnostic
    assert "BEFORE_CONTAMINATION_PACKAGE='com.android.vending'" in diagnostic
    assert "FINAL_CONTAMINATION_PACKAGE=''" in diagnostic
    assert "CONTAMINATION_PACKAGE=''" in diagnostic
    assert "RECOVERY_ACTION_ATTEMPTED='true'" in diagnostic
    assert "SURFACE_RECOVERED='false'" in diagnostic
    assert "HIERARCHY_OK='false'" in diagnostic
    assert "HIERARCHY_ERROR_TYPE='RuntimeError'" in diagnostic
    assert "HIERARCHY_REQUEST_ID='req-latest'" in diagnostic
    assert "HIERARCHY_OPERATION_ID='op-latest'" in diagnostic
    assert "PFD_READ_FAILED" in diagnostic


def test_successful_popup_recovery_final_diagnostic_uses_fresh_clean_surface(monkeypatch):
    client = _Client()
    reads = 0

    def hierarchy_factory():
        nonlocal reads
        reads += 1
        if reads == 1:
            return _snapshot_from_xml('<hierarchy><node package="com.android.vending" /></hierarchy>')
        return _snapshot_from_xml(_smartthings_xml())

    client.hierarchy_factory = hierarchy_factory
    logs = []
    monkeypatch.setattr(
        core_preflight,
        "ensure_smartthings_foreground",
        lambda **_kwargs: core_preflight._step_result(
            "PASS", "SmartThings foreground", package=core_preflight.SMARTTHINGS_PACKAGE,
        ),
    )
    _enable_core_preflight_for_rf5r9(monkeypatch)

    result = core_preflight.run_preflight(
        client=client, serial="SERIAL", log_fn=logs.append,
        adb_runner=_successful_adb, sleep_fn=lambda _seconds: None,
    )

    assert result.ok is True
    popup = result.app_foreground["popup_check"]
    assert popup["status"] == "PASS"
    assert popup["before"]["hierarchy_package"] == "com.android.vending"
    assert popup["after"]["hierarchy_package"] == core_preflight.SMARTTHINGS_PACKAGE
    assert popup["final_observation"] == popup["after"]
    assert popup["after"]["hierarchy_ok"] is True
    assert popup["before_contamination_package"] == "com.android.vending"
    assert popup["final_contamination_package"] is None
    assert popup["contamination_package"] is None
    assert popup["surface_recovered"] is True
    diagnostic = next(line for line in logs if "[PREFLIGHT][readiness]" in line)
    assert "READINESS_RESULT='PASS'" in diagnostic
    assert "FINAL_OBSERVATION='after'" in diagnostic
    assert "BEFORE_CONTAMINATION_PACKAGE='com.android.vending'" in diagnostic
    assert "FINAL_CONTAMINATION_PACKAGE=''" in diagnostic
    assert "RECOVERY_ACTION_ATTEMPTED='true'" in diagnostic
    assert "SURFACE_RECOVERED='true'" in diagnostic
    assert "HIERARCHY_OK='true'" in diagnostic
    assert f"HIERARCHY_PACKAGE='{core_preflight.SMARTTHINGS_PACKAGE}'" in diagnostic
