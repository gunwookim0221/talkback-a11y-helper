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


def _smartthings_foreground() -> str:
    return "mCurrentFocus=Window{abc u0 com.samsung.android.oneconnect/.ui.SCMainActivity}"


def _successful_adb(_adb_path, serial, *args, timeout=8.0):
    assert serial == "SERIAL"
    if args == ("get-state",):
        return True, "device"
    if args == ("shell", "dumpsys", "window"):
        return True, _smartthings_foreground()
    if args == ("shell", "dumpsys", "window", "policy"):
        return True, "mShowingLockscreen=false"
    return True, ""


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
    assert client.serials == [("ping", "SERIAL"), ("talkback", "SERIAL")]
    assert result.screen_awake["status"] == "PASS"
    assert result.unlock_swipe["status"] == "PASS"
    assert result.app_foreground["status"] == "PASS"
    assert (
        "[PREFLIGHT] wake_screen PASS "
        "message='Wake keyevent sent; screen settle completed'"
    ) in logs
    assert (
        "[PREFLIGHT] unlock_swipe PASS "
        "message='Swipe command sent; keyguard not active after 1 attempt(s)'"
    ) in logs
    assert (
        "[PREFLIGHT] app_foreground PASS "
        "message='SmartThings foreground confirmed'"
    ) in logs


def test_wake_screen_waits_for_screen_settle():
    sleeps = []

    result = core_preflight.wake_screen(
        serial="SERIAL",
        adb_runner=lambda _adb_path, _serial, *args, timeout=8.0: (True, ""),
        sleep_fn=sleeps.append,
    )

    assert result["status"] == "PASS"
    assert sleeps == [0.75]


def test_unlock_swipe_uses_screen_size_and_retries_until_keyguard_clears():
    commands = []
    keyguard_states = iter(
        [
            "mShowingLockscreen=true",
            "mShowingLockscreen=false",
        ]
    )
    sleeps = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("shell", "wm", "size"):
            return True, "Physical size: 1080x2400"
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, next(keyguard_states)
        return True, ""

    result = core_preflight.unlock_swipe(
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=sleeps.append,
    )

    swipe_commands = [
        args for args in commands if args[:3] == ("shell", "input", "swipe")
    ]
    assert swipe_commands == [
        ("shell", "input", "swipe", "540", "2040", "540", "600"),
        ("shell", "input", "swipe", "540", "2040", "540", "600"),
    ]
    assert result["status"] == "PASS"
    assert result["keyguard_active"] is False
    assert len(result["attempts"]) == 2
    assert sleeps == [0.6, 0.6]


def test_unlock_swipe_warns_when_keyguard_state_cannot_be_verified():
    result = core_preflight.unlock_swipe(
        serial="SERIAL",
        adb_runner=lambda _adb_path, _serial, *args, timeout=8.0: (True, ""),
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "WARN"
    assert result["keyguard_active"] is None
    assert "secure lock state not verified" in result["message"]
    assert len(result["attempts"]) == 3


def test_core_preflight_stops_when_wake_screen_fails(monkeypatch):
    client = _Client()
    commands = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "input", "keyevent", "KEYCODE_WAKEUP"):
            return False, "device offline"
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
    assert result.reason == "wake_screen_failed"
    assert result.screen_awake["status"] == "FAIL"
    assert result.unlock_swipe["status"] == "NOT_RUN"
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


def test_core_preflight_unlock_warn_continues_to_helper(monkeypatch):
    client = _Client()
    settings = AccessibilitySettings("helper", "1")

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window"):
            return True, _smartthings_foreground()
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=true"
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

    assert result.ok is True
    assert result.unlock_swipe["status"] == "WARN"
    assert "secure lockscreen may still be active" in result.unlock_swipe["message"]
    assert len(result.unlock_swipe["attempts"]) == 3
    assert client.serials == [("ping", "SERIAL"), ("talkback", "SERIAL")]


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


def test_core_preflight_stops_when_smartthings_foreground_is_not_confirmed(monkeypatch):
    client = _Client()

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
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
    uia_packages = iter(["com.android.vending", core_preflight.SMARTTHINGS_PACKAGE])
    logs = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=false"
        if args == ("shell", "dumpsys", "window"):
            return True, _smartthings_foreground()
        if args == ("shell", "cat", core_preflight.PREFLIGHT_UI_DUMP_PATH):
            return True, f'<hierarchy><node package="{next(uia_packages)}" /></hierarchy>'
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

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        nonlocal recovered
        commands.append(args)
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window", "policy"):
            return True, "mShowingLockscreen=false"
        if args == ("shell", "dumpsys", "window"):
            package = core_preflight.SMARTTHINGS_PACKAGE if recovered else "com.android.vending"
            return True, f"mCurrentFocus=Window{{abc u0 {package}/.MainActivity}}"
        if args == ("shell", "cat", core_preflight.PREFLIGHT_UI_DUMP_PATH):
            package = core_preflight.SMARTTHINGS_PACKAGE if recovered else "com.android.vending"
            return True, f'<hierarchy><node package="{package}" /></hierarchy>'
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


def test_core_preflight_reports_popup_reason_when_early_recovery_fails():
    client = _Client()
    logs = []

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        if args == ("get-state",):
            return True, "device"
        if args == ("shell", "dumpsys", "window"):
            return True, "mCurrentFocus=Window{abc u0 com.android.vending/.MainActivity}"
        if args == ("shell", "cat", core_preflight.PREFLIGHT_UI_DUMP_PATH):
            return True, '<hierarchy><node package="com.android.vending" /></hierarchy>'
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

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("shell", "dumpsys", "window"):
            return True, _smartthings_foreground()
        if args == ("shell", "cat", core_preflight.PREFLIGHT_UI_DUMP_PATH):
            return True, '<hierarchy><node package="com.android.vending" /></hierarchy>'
        return True, ""

    result = core_preflight.recover_external_popup_contamination(
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "FAIL"
    assert result["recovered"] is False
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

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        nonlocal external_stopped
        commands.append(args)
        if args == ("shell", "dumpsys", "window"):
            package = core_preflight.SMARTTHINGS_PACKAGE if external_stopped else "com.android.vending"
            return True, f"mCurrentFocus=Window{{abc u0 {package}/.MainActivity}}"
        if args == ("shell", "cat", core_preflight.PREFLIGHT_UI_DUMP_PATH):
            package = core_preflight.SMARTTHINGS_PACKAGE if external_stopped else "com.android.vending"
            return True, f'<hierarchy><node package="{package}" /></hierarchy>'
        if args == ("shell", "am", "force-stop", "com.android.vending"):
            external_stopped = True
        return True, ""

    result = core_preflight.recover_external_popup_contamination(
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

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        nonlocal dismissed
        commands.append(args)
        if args == ("shell", "dumpsys", "window"):
            package = core_preflight.SMARTTHINGS_PACKAGE if dismissed else "com.android.vending"
            return True, f"mCurrentFocus=Window{{abc u0 {package}/.MainActivity}}"
        if args == ("shell", "cat", core_preflight.PREFLIGHT_UI_DUMP_PATH):
            if dismissed:
                return True, (
                    f'<hierarchy><node package="{core_preflight.SMARTTHINGS_PACKAGE}" '
                    'resource-id="com.samsung.android.oneconnect:id/bottom_navigation_tab_home" /></hierarchy>'
                )
            return True, (
                '<hierarchy>'
                '<node package="com.android.vending" text="Submit" bounds="[600,1800][1000,1950]" />'
                '<node package="com.android.vending" content-desc="Not now" bounds="[80,1800][480,1950]" />'
                '</hierarchy>'
            )
        if args == ("shell", "input", "tap", "280", "1875"):
            dismissed = True
        return True, ""

    result = core_preflight.recover_external_popup_contamination(
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

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        commands.append(args)
        if args == ("shell", "dumpsys", "window"):
            return True, "mCurrentFocus=Window{abc u0 com.android.vending/.MainActivity}"
        if args == ("shell", "cat", core_preflight.PREFLIGHT_UI_DUMP_PATH):
            return True, (
                '<hierarchy>'
                '<node package="com.android.vending" text="Not now" bounds="[80,1800][480,1950]" />'
                '</hierarchy>'
            )
        return True, ""

    result = core_preflight.recover_external_popup_contamination(
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "FAIL"
    assert not any(args[:3] == ("shell", "input", "tap") for args in commands)


def test_review_sheet_dismiss_requires_smartthings_bottom_tab_after_tap():
    dismissed = False

    def adb_runner(_adb_path, _serial, *args, timeout=8.0):
        nonlocal dismissed
        if args == ("shell", "dumpsys", "window"):
            package = core_preflight.SMARTTHINGS_PACKAGE if dismissed else "com.android.vending"
            return True, f"mCurrentFocus=Window{{abc u0 {package}/.MainActivity}}"
        if args == ("shell", "cat", core_preflight.PREFLIGHT_UI_DUMP_PATH):
            if dismissed:
                return True, f'<hierarchy><node package="{core_preflight.SMARTTHINGS_PACKAGE}" /></hierarchy>'
            return True, (
                '<hierarchy>'
                '<node package="com.android.vending" text="Submit" bounds="[600,1800][1000,1950]" />'
                '<node package="com.android.vending" text="Not now" bounds="[80,1800][480,1950]" />'
                '</hierarchy>'
            )
        if args == ("shell", "input", "tap", "280", "1875"):
            dismissed = True
        return True, ""

    result = core_preflight.recover_external_popup_contamination(
        serial="SERIAL",
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "FAIL"
    assert result["recovery"] == "dismiss_review_sheet"
