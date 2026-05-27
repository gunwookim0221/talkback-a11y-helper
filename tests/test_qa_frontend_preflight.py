from __future__ import annotations

from qa_frontend.backend import preflight


def _ok(stdout: str = "") -> dict[str, object]:
    return {"ok": True, "status": "ok", "stdout": stdout, "stderr": ""}


def _adb_status() -> dict[str, object]:
    return {"ok": True, "status": "ok", "devices": [{"serial": "SERIAL", "state": "device"}]}


def _helper_ok() -> dict[str, object]:
    return {"ok": True, "status": "ok", "enabled": True}


def _window_focus(package: str) -> str:
    return f"mCurrentFocus=Window{{abc u0 {package}/.Activity}}\n"


def _popup_xml(*labels: str) -> str:
    nodes = []
    for index, label in enumerate(labels):
        top = 100 + index * 80
        nodes.append(
            f'<node text="{label}" content-desc="" bounds="[10,{top}][210,{top + 60}]" />'
        )
    return f'<?xml version="1.0" encoding="UTF-8"?><hierarchy>{"".join(nodes)}</hierarchy>'


def _package_xml(package: str, *, focused_package: str | None = None) -> str:
    focused = focused_package or package
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hierarchy><node package="{package}" text="" bounds="[0,0][100,100]">'
        f'<node package="{focused}" text="" focused="true" bounds="[0,0][100,100]" />'
        "</node></hierarchy>"
    )


def test_warm_launch_does_not_force_stop_and_calls_monkey():
    calls = []

    def adb_runner(args, timeout):
        calls.append(args)
        return _ok()

    result = preflight.launch_smartthings("warm", adb_runner=adb_runner, sleep_fn=lambda _seconds: None)

    assert result["monkey_success"] is True
    assert result["force_stop_attempted"] is False
    assert ["shell", "am", "force-stop", preflight.SMARTTHINGS_PACKAGE] not in calls
    assert [
        "shell",
        "monkey",
        "-p",
        preflight.SMARTTHINGS_PACKAGE,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
    ] in calls


def test_clean_launch_force_stops_before_monkey():
    calls = []

    def adb_runner(args, timeout):
        calls.append(args)
        return _ok()

    result = preflight.launch_smartthings("clean", adb_runner=adb_runner, sleep_fn=lambda _seconds: None)

    assert result["force_stop_attempted"] is True
    assert result["force_stop_ok"] is True
    assert calls[0] == ["shell", "am", "force-stop", preflight.SMARTTHINGS_PACKAGE]
    assert calls[1] == [
        "shell",
        "monkey",
        "-p",
        preflight.SMARTTHINGS_PACKAGE,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
    ]


def test_normalize_launch_mode_defaults_to_clean_when_missing():
    assert preflight.normalize_launch_mode(None) == "clean"
    assert preflight.normalize_launch_mode("") == "clean"


def test_foreground_package_unknown_is_not_fatal_for_preflight():
    calls = []

    def adb_runner(args, timeout):
        calls.append(args)
        if args[:4] == ["shell", "settings", "get", "secure"]:
            return _ok("com.google.android.marvin.talkback/.TalkBackService\n")
        return _ok("")

    result = preflight.run_runtime_preflight(
        "warm",
        adb_status_fn=_adb_status,
        helper_status_fn=_helper_ok,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["state"] == "passed"
    assert result["foreground_package"] is None
    assert result["foreground_matches_expected"] is False
    assert ["shell", "dumpsys", "window"] in calls
    assert ["shell", "dumpsys", "activity", "activities"] in calls


def test_talkback_disabled_opens_accessibility_settings_and_blocks_run():
    calls = []

    def adb_runner(args, timeout):
        calls.append(args)
        if args[:4] == ["shell", "settings", "get", "secure"]:
            return _ok("com.example/.Other\n")
        return _ok("Starting: Intent\n")

    result = preflight.run_runtime_preflight(
        "warm",
        adb_status_fn=_adb_status,
        helper_status_fn=_helper_ok,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["state"] == "blocked"
    assert result["reason"] == "talkback_disabled"
    assert result["talkback_state"] == "disabled"
    assert result["accessibility_settings_opened"] is True
    assert ["shell", "am", "start", "-a", "android.settings.ACCESSIBILITY_SETTINGS"] in calls
    assert "Please enable TalkBack and retry" in str(result["user_message"])


def test_talkback_enabled_accepts_samsung_and_google_packages():
    assert preflight.is_talkback_enabled("com.samsung.android.accessibility.talkback/.TalkBackService")
    assert preflight.is_talkback_enabled("com.google.android.marvin.talkback/.TalkBackService")
    assert not preflight.is_talkback_enabled("com.example/.Other")


def test_popup_dismiss_candidate_prefers_safe_label_priority():
    candidate = preflight.find_dismiss_candidate_in_uiautomator_xml(_popup_xml("Later", "Not now"))

    assert candidate is not None
    assert candidate["label"] == "Not now"


def test_popup_dismiss_candidate_ignores_rating_and_submit_labels():
    candidate = preflight.find_dismiss_candidate_in_uiautomator_xml(
        _popup_xml("Rate", "Submit", "평가", "No thanks")
    )

    assert candidate is not None
    assert candidate["label"] == "No thanks"


def test_popup_dismiss_candidate_returns_none_for_dangerous_only_labels():
    candidate = preflight.find_dismiss_candidate_in_uiautomator_xml(_popup_xml("Rate", "Submit", "리뷰 작성"))

    assert candidate is None


def test_external_popup_detection_clicks_dismiss_candidate_and_clears_to_smartthings():
    calls = []
    foreground_outputs = [
        _window_focus("com.android.vending"),
        _window_focus(preflight.SMARTTHINGS_PACKAGE),
    ]

    def adb_runner(args, timeout):
        calls.append(args)
        if args == ["shell", "dumpsys", "window"]:
            return _ok(foreground_outputs.pop(0) if foreground_outputs else _window_focus(preflight.SMARTTHINGS_PACKAGE))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_surface.xml"]:
            return _ok()
        if args == ["shell", "cat", "/sdcard/qa_frontend_surface.xml"]:
            return _ok(_package_xml(preflight.SMARTTHINGS_PACKAGE))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_popup.xml"]:
            return _ok("UI hierchary dumped")
        if args == ["shell", "cat", "/sdcard/qa_frontend_popup.xml"]:
            return _ok(_popup_xml("Not now"))
        if args[:4] == ["shell", "input", "tap", "110"]:
            return _ok()
        return _ok()

    result = preflight.stabilize_external_popup(adb_runner=adb_runner, sleep_fn=lambda _seconds: None)

    assert result["popup_detected"] is True
    assert result["popup_package"] == "com.android.vending"
    assert result["popup_result"] == "cleared"
    assert result["popup_dismissed"] is True
    assert ["shell", "input", "tap", "110", "130"] in calls


def test_foreground_smartthings_with_uiautomator_focus_vending_detects_popup():
    def adb_runner(args, timeout):
        if args == ["shell", "dumpsys", "window"]:
            return _ok(_window_focus(preflight.SMARTTHINGS_PACKAGE))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_surface.xml"]:
            return _ok()
        if args == ["shell", "cat", "/sdcard/qa_frontend_surface.xml"]:
            return _ok(_package_xml(preflight.SMARTTHINGS_PACKAGE, focused_package="com.android.vending"))
        return _ok()

    status = preflight.poll_launch_surface_status(adb_runner=adb_runner, sleep_fn=lambda _seconds: None)

    assert status["foreground_package"] == preflight.SMARTTHINGS_PACKAGE
    assert status["uiautomator_focused_package"] == "com.android.vending"
    assert status["external_popup_package"] == "com.android.vending"
    assert status["external_popup_reason"] == "post_launch_uiautomator_focus"


def test_focus_package_polling_retries_until_surface_is_available():
    dumps = ["", _package_xml(preflight.SMARTTHINGS_PACKAGE)]
    sleep_calls = []

    def adb_runner(args, timeout):
        if args == ["shell", "dumpsys", "window"]:
            return _ok(_window_focus(preflight.SMARTTHINGS_PACKAGE))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_surface.xml"]:
            return _ok()
        if args == ["shell", "cat", "/sdcard/qa_frontend_surface.xml"]:
            return _ok(dumps.pop(0))
        return _ok()

    status = preflight.poll_launch_surface_status(
        adb_runner=adb_runner,
        sleep_fn=lambda seconds: sleep_calls.append(seconds),
        timeout_seconds=2.0,
        interval_seconds=0.5,
    )

    assert status["smartthings_ready"] is True
    assert sleep_calls


def test_external_popup_falls_back_to_back_when_no_candidate():
    calls = []
    foreground_outputs = [
        _window_focus("com.android.vending"),
        _window_focus(preflight.SMARTTHINGS_PACKAGE),
    ]

    def adb_runner(args, timeout):
        calls.append(args)
        if args == ["shell", "dumpsys", "window"]:
            return _ok(foreground_outputs.pop(0) if foreground_outputs else _window_focus(preflight.SMARTTHINGS_PACKAGE))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_surface.xml"]:
            return _ok()
        if args == ["shell", "cat", "/sdcard/qa_frontend_surface.xml"]:
            return _ok(_package_xml(preflight.SMARTTHINGS_PACKAGE))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_popup.xml"]:
            return _ok()
        if args == ["shell", "cat", "/sdcard/qa_frontend_popup.xml"]:
            return _ok(_popup_xml("Rate", "Submit"))
        return _ok()

    result = preflight.stabilize_external_popup(adb_runner=adb_runner, sleep_fn=lambda _seconds: None)

    assert result["popup_result"] == "cleared"
    assert ["shell", "input", "keyevent", "KEYCODE_BACK"] in calls
    assert result["attempts"][0]["dismiss_method"] == "back"


def test_external_popup_dismiss_exception_is_captured_without_crash():
    calls = []

    def adb_runner(args, timeout):
        calls.append(args)
        if args == ["shell", "dumpsys", "window"]:
            return _ok(_window_focus("com.android.vending"))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_popup.xml"]:
            raise RuntimeError("dump failed")
        return _ok()

    result = preflight.stabilize_external_popup(adb_runner=adb_runner, sleep_fn=lambda _seconds: None, max_attempts=1)

    assert result["popup_detected"] is True
    assert result["popup_result"] == "uncleared"
    assert result["attempts"][0]["dismiss_method"] == "exception"


def test_runtime_preflight_passes_when_popup_clears_to_smartthings():
    foreground_outputs = [
        _window_focus("com.android.vending"),
        _window_focus(preflight.SMARTTHINGS_PACKAGE),
    ]

    def adb_runner(args, timeout):
        if args[:4] == ["shell", "settings", "get", "secure"]:
            return _ok("com.google.android.marvin.talkback/.TalkBackService\n")
        if args == ["shell", "dumpsys", "window"]:
            return _ok(foreground_outputs.pop(0) if foreground_outputs else _window_focus(preflight.SMARTTHINGS_PACKAGE))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_surface.xml"]:
            return _ok()
        if args == ["shell", "cat", "/sdcard/qa_frontend_surface.xml"]:
            return _ok(_package_xml(preflight.SMARTTHINGS_PACKAGE))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_popup.xml"]:
            return _ok()
        if args == ["shell", "cat", "/sdcard/qa_frontend_popup.xml"]:
            return _ok(_popup_xml("No thanks"))
        return _ok()

    result = preflight.run_runtime_preflight(
        "clean",
        adb_status_fn=_adb_status,
        helper_status_fn=_helper_ok,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["state"] == "passed"
    assert result["popup_detected"] is True
    assert result["popup_result"] == "cleared"
    assert result["foreground_package"] == preflight.SMARTTHINGS_PACKAGE


def test_runtime_preflight_blocks_when_vending_remains_foreground():
    def adb_runner(args, timeout):
        if args[:4] == ["shell", "settings", "get", "secure"]:
            return _ok("com.google.android.marvin.talkback/.TalkBackService\n")
        if args == ["shell", "dumpsys", "window"]:
            return _ok(_window_focus("com.android.vending"))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_popup.xml"]:
            return _ok()
        if args == ["shell", "cat", "/sdcard/qa_frontend_popup.xml"]:
            return _ok(_popup_xml("Rate", "Submit"))
        return _ok()

    result = preflight.run_runtime_preflight(
        "clean",
        adb_status_fn=_adb_status,
        helper_status_fn=_helper_ok,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["state"] == "blocked"
    assert result["reason"] == "external_popup_uncleared"
    assert result["popup_detected"] is True
    assert result["popup_result"] == "uncleared"
    assert result["foreground_package"] == "com.android.vending"


def test_runtime_preflight_blocks_when_foreground_smartthings_but_uiautomator_focus_vending_remains():
    def adb_runner(args, timeout):
        if args[:4] == ["shell", "settings", "get", "secure"]:
            return _ok("com.google.android.marvin.talkback/.TalkBackService\n")
        if args == ["shell", "dumpsys", "window"]:
            return _ok(_window_focus(preflight.SMARTTHINGS_PACKAGE))
        if args == ["shell", "uiautomator", "dump", "/sdcard/qa_frontend_surface.xml"]:
            return _ok()
        if args == ["shell", "cat", "/sdcard/qa_frontend_surface.xml"]:
            return _ok(_package_xml(preflight.SMARTTHINGS_PACKAGE, focused_package="com.android.vending"))
        return _ok()

    result = preflight.run_runtime_preflight(
        "clean",
        adb_status_fn=_adb_status,
        helper_status_fn=_helper_ok,
        adb_runner=adb_runner,
        sleep_fn=lambda _seconds: None,
    )

    assert result["state"] == "blocked"
    assert result["reason"] == "external_popup_uncleared"
    assert result["foreground_package"] == preflight.SMARTTHINGS_PACKAGE
    assert result["popup_package"] == "com.android.vending"
