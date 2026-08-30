from qa_frontend.backend.device_locale import (
    apply_language_mode,
    get_device_locale,
    is_verified_samsung_oneui,
    normalize_language_mode,
    open_language_settings,
    _locale_picker_failure_status,
    _read_locale_picker_semantics,
)


def test_normalize_language_mode_accepts_phase_a_modes():
    assert normalize_language_mode(None) == "current"
    assert normalize_language_mode("current") == "current"
    assert normalize_language_mode("ko-KR") == "ko-KR"
    assert normalize_language_mode("en-US") == "en-US"


def test_normalize_language_mode_rejects_unsupported_mode():
    try:
        normalize_language_mode("ko-KR,en-US")
    except ValueError as exc:
        assert "language_mode" in str(exc)
    else:
        raise AssertionError("unsupported language mode should fail")


def test_get_device_locale_reads_persist_locale():
    def fake_adb(args, timeout=10.0):
        if args == ["shell", "getprop", "persist.sys.locale"]:
            return {"ok": True, "stdout": "ko_KR\n", "stderr": ""}
        if args == ["shell", "settings", "get", "system", "system_locales"]:
            return {"ok": True, "stdout": "en-US\n", "stderr": ""}
        raise AssertionError(args)

    result = get_device_locale(fake_adb)

    assert result["status"] == "ok"
    assert result["device_locale"] == "ko-KR"
    assert result["source"] == "persist.sys.locale"
    assert result["system_locale"] == "en-US"


def test_current_language_mode_does_not_change_locale():
    calls = []

    def fake_adb(args, timeout=10.0):
        calls.append(args)
        if args == ["shell", "getprop", "persist.sys.locale"]:
            return {"ok": True, "stdout": "en-US\n", "stderr": ""}
        if args == ["shell", "settings", "get", "system", "system_locales"]:
            return {"ok": True, "stdout": "en-US\n", "stderr": ""}
        raise AssertionError(args)

    result = apply_language_mode("current", fake_adb)

    assert result["ok"] is True
    assert result["language_mode"] == "current"
    assert result["device_locale"] == "en-US"
    assert result["changed"] is False
    assert calls == [
        ["shell", "getprop", "persist.sys.locale"],
        ["shell", "settings", "get", "system", "system_locales"],
    ]


def test_current_language_mode_does_not_block_when_locale_read_fails():
    def fake_adb(args, timeout=10.0):
        return {"ok": False, "stderr": "adb unavailable", "stdout": ""}

    result = apply_language_mode("current", fake_adb)

    assert result["ok"] is True
    assert result["status"] == "unknown"
    assert result["language_mode"] == "current"
    assert result["changed"] is False
    assert result["verified"] is False


def test_target_language_mode_changes_and_verifies_locale():
    calls = []
    locale_reads = iter(["en-US\n", "ko-KR\n"])

    def fake_adb(args, timeout=10.0):
        calls.append(args)
        if args == ["shell", "getprop", "persist.sys.locale"]:
            return {"ok": True, "stdout": next(locale_reads), "stderr": ""}
        if args == ["shell", "settings", "get", "system", "system_locales"]:
            return {"ok": True, "stdout": "ko-KR\n", "stderr": ""}
        return {"ok": True, "stdout": "", "stderr": ""}

    result = apply_language_mode("ko-KR", fake_adb, sleep=lambda seconds: None)

    assert result["ok"] is True
    assert result["language_mode"] == "ko-KR"
    assert result["device_locale"] == "ko-KR"
    assert result["changed"] is True
    assert ["shell", "settings", "put", "system", "system_locales", "ko-KR"] in calls


def test_target_language_mode_repairs_system_locale_even_when_effective_locale_already_matches():
    calls = []
    persist_reads = iter(["ko-KR\n", "ko-KR\n"])
    system_reads = iter(["en-US\n", "ko-KR\n"])

    def fake_adb(args, timeout=10.0):
        calls.append(args)
        if args == ["shell", "getprop", "persist.sys.locale"]:
            return {"ok": True, "stdout": next(persist_reads), "stderr": ""}
        if args == ["shell", "settings", "get", "system", "system_locales"]:
            return {"ok": True, "stdout": next(system_reads), "stderr": ""}
        return {"ok": True, "stdout": "", "stderr": ""}

    result = apply_language_mode("ko-KR", fake_adb, sleep=lambda seconds: None)

    assert result["ok"] is True
    assert result["changed"] is True
    assert ["shell", "settings", "put", "system", "system_locales", "ko-KR"] in calls


def test_target_language_mode_reports_manual_change_required_when_system_locales_changes_only():
    def fake_adb(args, timeout=10.0):
        if args == ["shell", "getprop", "persist.sys.locale"]:
            return {"ok": True, "stdout": "ko-KR\n", "stderr": ""}
        if args == ["shell", "settings", "get", "system", "system_locales"]:
            return {"ok": True, "stdout": "en-US\n", "stderr": ""}
        return {"ok": True, "stdout": "", "stderr": ""}

    result = apply_language_mode("en-US", fake_adb, sleep=lambda seconds: None)

    assert result["ok"] is False
    assert result["language_mode"] == "en-US"
    assert result["device_locale"] == "ko-KR"
    assert result["verified"] is False
    assert result["manual_language_change_required"] is True
    assert "Manual language change required" in result["error"]


def test_open_language_settings_uses_locale_settings_first():
    calls = []

    def fake_adb(args, timeout=10.0):
        calls.append(args)
        return {"ok": True, "stdout": "Starting", "stderr": ""}

    result = open_language_settings(fake_adb)

    assert result["ok"] is True
    assert result["status"] == "opened"
    assert result["intent"] == "android.settings.LOCALE_SETTINGS"
    assert calls == [["shell", "am", "start", "-a", "android.settings.LOCALE_SETTINGS"]]


def test_open_language_settings_falls_back_to_general_settings():
    calls = []

    def fake_adb(args, timeout=10.0):
        calls.append(args)
        if args[-1] == "android.settings.LOCALE_SETTINGS":
            return {"ok": False, "stdout": "", "stderr": "Activity not found"}
        return {"ok": True, "stdout": "Starting", "stderr": ""}

    result = open_language_settings(fake_adb)

    assert result["ok"] is True
    assert result["status"] == "opened"
    assert result["intent"] == "android.settings.SETTINGS"
    assert calls == [
        ["shell", "am", "start", "-a", "android.settings.LOCALE_SETTINGS"],
        ["shell", "am", "start", "-a", "android.settings.SETTINGS"],
    ]


def test_samsung_oneui_capability_gate_requires_samsung_and_oneui():
    def fake_adb(args, timeout=10.0):
        if args[-1] == "ro.product.manufacturer":
            return {"ok": True, "stdout": "samsung\n", "stderr": ""}
        if args[-1] == "ro.build.version.oneui":
            return {"ok": True, "stdout": "70000\n", "stderr": ""}
        raise AssertionError(args)

    result = is_verified_samsung_oneui(fake_adb)

    assert result == {
        "supported": True,
        "manufacturer": "samsung",
        "oneui_version": "70000",
        "reason": "samsung_oneui_verified",
    }


def test_manual_language_fallback_is_not_attempted_without_verified_samsung_oneui():
    calls = []

    def fake_adb(args, timeout=10.0):
        calls.append(args)
        if args == ["shell", "getprop", "persist.sys.locale"]:
            return {"ok": True, "stdout": "ko-KR\n", "stderr": ""}
        if args == ["shell", "settings", "get", "system", "system_locales"]:
            return {"ok": True, "stdout": "en-US\n", "stderr": ""}
        return {"ok": True, "stdout": "", "stderr": ""}

    helper_calls = []

    def helper_factory(**kwargs):
        helper_calls.append(kwargs)
        raise AssertionError("helper fallback must remain gated")

    result = apply_language_mode(
        "en-US",
        fake_adb,
        sleep=lambda seconds: None,
        helper_client_factory=helper_factory,
        device_serial="test-device",
    )

    assert result["manual_language_change_required"] is True
    assert "fallback_attempted" not in result
    assert helper_calls == []
    assert ["shell", "getprop", "ro.product.manufacturer"] in calls


def test_samsung_fallback_verifies_effective_locale_after_one_helper_action():
    state = {"effective": "en-US", "system": "en-US"}
    helper_calls = []
    locale_xml = _locale_picker_xml()

    class FakeHelper:
        def check_helper_status(self, dev=None):
            helper_calls.append(("ready", dev))
            return True

        def set_system_language(self, dev=None, locale="", current_locale=None, wait_=5.0):
            helper_calls.append(("set", dev, locale, current_locale))
            state["effective"] = locale
            return {
                "success": False,
                "status": "ACTION_PERFORMED",
                "actionPerformed": True,
                "targetLocale": locale,
            }

        def dump_tree(self, dev=None, wait_seconds=3.0):
            return []

    def fake_adb(args, timeout=10.0):
        if args == ["shell", "getprop", "persist.sys.locale"]:
            return {"ok": True, "stdout": f"{state['effective']}\n", "stderr": ""}
        if args == ["shell", "settings", "get", "system", "system_locales"]:
            return {"ok": True, "stdout": f"{state['system']}\n", "stderr": ""}
        if args == ["shell", "settings", "put", "system", "system_locales", "ko-KR"]:
            state["system"] = "ko-KR"
            return {"ok": True, "stdout": "", "stderr": ""}
        if args == ["shell", "getprop", "ro.product.manufacturer"]:
            return {"ok": True, "stdout": "samsung\n", "stderr": ""}
        if args == ["shell", "getprop", "ro.build.version.oneui"]:
            return {"ok": True, "stdout": "70000\n", "stderr": ""}
        if args == ["shell", "am", "start", "-a", "android.settings.LOCALE_SETTINGS"]:
            return {"ok": True, "stdout": "Starting", "stderr": ""}
        if args == ["shell", "dumpsys", "window"]:
            return {"ok": True, "stdout": "mCurrentFocus=com.android.settings/.Settings$LocalePickerActivity", "stderr": ""}
        if args == ["shell", "uiautomator", "dump", "/sdcard/talkback_helper_locale_picker.xml"]:
            return {"ok": True, "stdout": "UI hierchary dumped", "stderr": ""}
        if args == ["shell", "cat", "/sdcard/talkback_helper_locale_picker.xml"]:
            return {"ok": True, "stdout": locale_xml, "stderr": ""}
        raise AssertionError(args)

    result = apply_language_mode(
        "ko-KR",
        fake_adb,
        sleep=lambda seconds: None,
        helper_client_factory=lambda **kwargs: FakeHelper(),
        device_serial="test-device",
    )

    assert result["ok"] is True
    assert result["verified"] is True
    assert result["fallback_status"] == "SUCCESS"
    assert result["device_locale"] == "ko-KR"
    assert result["readiness"]["targetMatchCount"] == 1
    assert result["readiness"]["targetClickable"] is True
    assert helper_calls == [
        ("ready", "test-device"),
        ("set", "test-device", "ko-KR", "en-US"),
    ]


def test_samsung_fallback_stops_on_confirmation_without_executing_confirmation_action():
    state = {"effective": "en-US", "system": "en-US"}
    locale_xml = _locale_picker_xml()
    confirmation_actions = []

    class FakeHelper:
        def check_helper_status(self, dev=None):
            return True

        def set_system_language(self, dev=None, locale="", current_locale=None, wait_=5.0):
            return {"success": False, "status": "ACTION_PERFORMED", "actionPerformed": True}

        def dump_tree(self, dev=None, wait_seconds=3.0):
            return [{"text": "Confirm", "clickable": True}]

    def fake_adb(args, timeout=10.0):
        if args == ["shell", "getprop", "persist.sys.locale"]:
            return {"ok": True, "stdout": f"{state['effective']}\n", "stderr": ""}
        if args == ["shell", "settings", "get", "system", "system_locales"]:
            return {"ok": True, "stdout": f"{state['system']}\n", "stderr": ""}
        if args == ["shell", "settings", "put", "system", "system_locales", "ko-KR"]:
            state["system"] = "ko-KR"
            return {"ok": True, "stdout": "", "stderr": ""}
        if args == ["shell", "getprop", "ro.product.manufacturer"]:
            return {"ok": True, "stdout": "samsung\n", "stderr": ""}
        if args == ["shell", "getprop", "ro.build.version.oneui"]:
            return {"ok": True, "stdout": "70000\n", "stderr": ""}
        if args == ["shell", "am", "start", "-a", "android.settings.LOCALE_SETTINGS"]:
            return {"ok": True, "stdout": "Starting", "stderr": ""}
        if args == ["shell", "dumpsys", "window"]:
            return {"ok": True, "stdout": "mCurrentFocus=com.android.settings/.Settings$LocalePickerActivity", "stderr": ""}
        if args == ["shell", "uiautomator", "dump", "/sdcard/talkback_helper_locale_picker.xml"]:
            return {"ok": True, "stdout": "UI hierchary dumped", "stderr": ""}
        if args == ["shell", "cat", "/sdcard/talkback_helper_locale_picker.xml"]:
            return {"ok": True, "stdout": locale_xml, "stderr": ""}
        if args == ["shell", "input", "tap"]:
            confirmation_actions.append(args)
            return {"ok": True, "stdout": "", "stderr": ""}
        raise AssertionError(args)

    result = apply_language_mode(
        "ko-KR",
        fake_adb,
        sleep=lambda seconds: None,
        helper_client_factory=lambda **kwargs: FakeHelper(),
        device_serial="test-device",
    )

    assert result["ok"] is False
    assert result["fallback_status"] == "CONFIRMATION_REQUIRED"
    assert result["confirmation_ui"] == "DISCOVERED"
    assert result["confirmation_action_executed"] is False
    assert state["effective"] == "en-US"
    assert confirmation_actions == []


def test_samsung_fallback_propagates_helper_service_unavailable_without_retry():
    state = {"effective": "en-US", "system": "en-US"}
    helper_calls = []

    class FakeHelper:
        def check_helper_status(self, dev=None):
            helper_calls.append(("ready", dev))
            return True

        def set_system_language(self, dev=None, locale="", current_locale=None, wait_=5.0):
            helper_calls.append(("set", dev, locale, current_locale))
            return {
                "success": False,
                "status": "HELPER_SERVICE_UNAVAILABLE",
                "reason": "service_instance_unavailable_deadline_expired",
            }

    def fake_adb(args, timeout=10.0):
        if args == ["shell", "getprop", "persist.sys.locale"]:
            return {"ok": True, "stdout": f"{state['effective']}\n", "stderr": ""}
        if args == ["shell", "settings", "get", "system", "system_locales"]:
            return {"ok": True, "stdout": f"{state['system']}\n", "stderr": ""}
        if args == ["shell", "settings", "put", "system", "system_locales", "ko-KR"]:
            state["system"] = "ko-KR"
            return {"ok": True, "stdout": "", "stderr": ""}
        if args == ["shell", "getprop", "ro.product.manufacturer"]:
            return {"ok": True, "stdout": "samsung\n", "stderr": ""}
        if args == ["shell", "getprop", "ro.build.version.oneui"]:
            return {"ok": True, "stdout": "70000\n", "stderr": ""}
        if args == ["shell", "am", "start", "-a", "android.settings.LOCALE_SETTINGS"]:
            return {"ok": True, "stdout": "Starting", "stderr": ""}
        if args == ["shell", "dumpsys", "window"]:
            return {"ok": True, "stdout": "mCurrentFocus=com.android.settings/.Settings$LocalePickerActivity", "stderr": ""}
        if args == ["shell", "uiautomator", "dump", "/sdcard/talkback_helper_locale_picker.xml"]:
            return {"ok": True, "stdout": "UI hierchary dumped", "stderr": ""}
        if args == ["shell", "cat", "/sdcard/talkback_helper_locale_picker.xml"]:
            return {"ok": True, "stdout": _locale_picker_xml(), "stderr": ""}
        raise AssertionError(args)

    result = apply_language_mode(
        "ko-KR",
        fake_adb,
        sleep=lambda seconds: None,
        helper_client_factory=lambda **kwargs: FakeHelper(),
        device_serial="test-device",
    )

    assert result["ok"] is False
    assert result["fallback_status"] == "HELPER_SERVICE_UNAVAILABLE"
    assert helper_calls == [("ready", "test-device"), ("set", "test-device", "ko-KR", "en-US")]


def test_preflight_and_production_contract_fields_are_ready_for_both_supported_locales():
    korean = _read_locale_picker_semantics(_xml_reader(_locale_picker_xml()), target_locale="ko-KR")
    english = _read_locale_picker_semantics(_xml_reader(_locale_picker_xml()), target_locale="en-US")

    for screen in (korean, english):
        readiness = screen["readiness"]
        assert readiness["packageMatches"] is True
        assert readiness["localeListPresent"] is True
        assert readiness["localeRecyclerPresent"] is True
        assert readiness["languageDescriptionPresent"] is True
        assert readiness["expectedAncestry"] is True
        assert readiness["targetMatchCount"] == 1
        assert readiness["targetVisible"] is True
        assert readiness["targetEnabled"] is True
        assert readiness["targetClickable"] is True

    assert korean["english_match_count"] == 1
    assert korean["korean_match_count"] == 1
    assert english["english_match_count"] == 1
    assert english["korean_match_count"] == 1


def test_preflight_reports_the_same_named_missing_marker_predicate():
    xml = _locale_picker_xml()
    cases = (
        (xml.replace("com.android.settings:id/locale_recycler_view", "com.android.settings:id/not_locale_recycler"), "locale_recycler_missing"),
        (xml.replace("com.android.settings:id/language_desc", "com.android.settings:id/not_language_desc"), "language_desc_missing"),
    )

    for case_xml, expected_reason in cases:
        screen = _read_locale_picker_semantics(_xml_reader(case_xml), target_locale="ko-KR")

        assert screen["visible"] is False
        assert screen["reason"] == expected_reason
        assert screen["readiness"]["packageMatches"] is True


def test_preflight_accepts_valid_recycler_context_when_locale_list_is_absent():
    xml = _locale_picker_xml().replace(
        '<node package="com.android.settings" resource-id="com.android.settings:id/locale_list_view" class="android.widget.ScrollView">',
        '',
    ).replace('</node></node></node></hierarchy>', '</node></node></hierarchy>')

    screen = _read_locale_picker_semantics(_xml_reader(xml), target_locale="ko-KR")

    assert screen["visible"] is True
    assert "reason" not in screen
    assert screen["readiness"]["localeListPresent"] is False
    assert screen["readiness"]["localeRecyclerPresent"] is True
    assert screen["readiness"]["languageDescriptionPresent"] is True
    assert screen["readiness"]["expectedAncestry"] is True
    assert screen["readiness"]["targetMatchCount"] == 1
    assert screen["target_match_count"] == 1


def test_preflight_keeps_missing_recycler_and_context_fail_closed_when_list_is_absent():
    no_list = _locale_picker_xml().replace(
        '<node package="com.android.settings" resource-id="com.android.settings:id/locale_list_view" class="android.widget.ScrollView">',
        '',
    ).replace('</node></node></node></hierarchy>', '</node></node></hierarchy>')
    no_recycler = no_list.replace(
        '<node package="com.android.settings" resource-id="com.android.settings:id/locale_recycler_view" class="androidx.recyclerview.widget.RecyclerView">',
        '<node package="com.android.settings" resource-id="com.android.settings:id/not_locale_recycler" class="androidx.recyclerview.widget.RecyclerView">',
    )
    no_description = no_list.replace(
        'resource-id="com.android.settings:id/language_desc"',
        'resource-id="com.android.settings:id/not_language_desc"',
    )
    invalid_context = no_list.replace(
        'package="com.android.settings" resource-id="com.android.settings:id/locale_recycler_view"',
        'package="com.samsung.android.oneconnect" resource-id="com.android.settings:id/locale_recycler_view"',
    )

    missing_recycler = _read_locale_picker_semantics(_xml_reader(no_recycler), target_locale="ko-KR")
    missing_description = _read_locale_picker_semantics(_xml_reader(no_description), target_locale="ko-KR")
    wrong_context = _read_locale_picker_semantics(_xml_reader(invalid_context), target_locale="ko-KR")

    assert missing_recycler["visible"] is False
    assert missing_recycler["reason"] == "locale_recycler_missing"
    assert missing_recycler["readiness"]["localeListPresent"] is False
    assert missing_description["visible"] is False
    assert missing_description["reason"] == "language_desc_missing"
    assert missing_description["readiness"]["localeListPresent"] is False
    assert wrong_context["visible"] is False
    assert wrong_context["reason"] == "expected_ancestry_missing"
    assert wrong_context["readiness"]["localeRecyclerPresent"] is True
    assert wrong_context["readiness"]["targetMatchCount"] == 0


def test_preflight_uses_canonical_korean_content_description_without_native_text():
    native_only_xml = _locale_picker_xml().replace(
        'text="한국어(대한민국)" content-desc="Korean (South Korea)"',
        'text="한국어(대한민국)" content-desc=""',
    )

    screen = _read_locale_picker_semantics(_xml_reader(native_only_xml), target_locale="ko-KR")

    assert screen["target_match_count"] == 1
    assert screen["readiness"]["targetMatchCount"] == 1


def test_semantic_failure_status_distinguishes_unavailable_root_from_wrong_package():
    assert _locale_picker_failure_status({
        "readiness": {
            "rootAvailable": False,
            "rootPackage": None,
            "packageMatches": False,
        },
    }) == "WINDOW_NOT_READY"
    assert _locale_picker_failure_status({
        "readiness": {
            "rootAvailable": True,
            "rootPackage": "com.android.systemui",
            "packageMatches": False,
        },
    }) == "WRONG_SCREEN"


def _xml_reader(xml_text):
    def fake_adb(args, timeout=8.0):
        if args == ["shell", "uiautomator", "dump", "/sdcard/talkback_helper_locale_picker.xml"]:
            return {"ok": True, "stdout": "UI hierchary dumped", "stderr": ""}
        if args == ["shell", "cat", "/sdcard/talkback_helper_locale_picker.xml"]:
            return {"ok": True, "stdout": xml_text, "stderr": ""}
        raise AssertionError(args)

    return fake_adb


def _locale_picker_xml():
    return (
        '<hierarchy>'
        '<node package="com.android.settings" resource-id="" class="android.widget.FrameLayout">'
        '<node package="com.android.settings" resource-id="com.android.settings:id/language_desc" class="android.widget.TextView" />'
        '<node package="com.android.settings" resource-id="com.android.settings:id/locale_list_view" class="android.widget.ScrollView">'
        '<node package="com.android.settings" resource-id="com.android.settings:id/locale_recycler_view" class="androidx.recyclerview.widget.RecyclerView">'
        '<node package="com.android.settings" resource-id="" class="android.widget.LinearLayout" clickable="true" enabled="true" visible-to-user="true">'
        '<node package="com.android.settings" resource-id="com.android.settings:id/label" text="English (United States)" content-desc="English (United States)" />'
        '</node>'
        '<node package="com.android.settings" resource-id="" class="android.widget.LinearLayout" clickable="true" enabled="true" visible-to-user="true">'
        '<node package="com.android.settings" resource-id="com.android.settings:id/label" text="한국어(대한민국)" content-desc="Korean (South Korea)" />'
        '</node>'
        '</node></node></node></hierarchy>'
    )
