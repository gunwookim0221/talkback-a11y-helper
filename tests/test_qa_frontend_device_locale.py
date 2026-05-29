from qa_frontend.backend.device_locale import apply_language_mode, get_device_locale, normalize_language_mode, open_language_settings


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
