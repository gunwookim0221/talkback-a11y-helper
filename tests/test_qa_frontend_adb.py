from qa_frontend.backend import adb


def _fake_helper_apk(monkeypatch):
    monkeypatch.setattr(adb, "_find_helper_apk", lambda: adb.ROOT_DIR / "app/build/outputs/apk/debug/app-debug.apk")


def test_helper_status_accepts_short_component_and_reports_ok(monkeypatch):
    _fake_helper_apk(monkeypatch)
    responses = {
        ("shell", "pm", "list", "packages"): {
            "ok": True,
            "status": "ok",
            "stdout": "package:com.iotpart.sqe.talkbackhelper\npackage:com.example.app\n",
            "stderr": "",
        },
        ("shell", "settings", "get", "secure", "enabled_accessibility_services"): {
            "ok": True,
            "status": "ok",
            "stdout": "com.iotpart.sqe.talkbackhelper/.A11yHelperService:com.example/.Other\n",
            "stderr": "",
        },
    }

    monkeypatch.setattr(adb, "run_adb", lambda args, timeout=10.0: responses[tuple(args)])

    result = adb.get_helper_status()

    assert result["status"] == "ok"
    assert result["helper_name"] == "TalkBack A11y Helper"
    assert result["apk_found"] is True
    assert result["installed"] is True
    assert result["accessibility_enabled"] is True
    assert result["package_installed"] is True
    assert result["enabled"] is True


def test_helper_status_accepts_fully_qualified_component_and_reports_ok(monkeypatch):
    _fake_helper_apk(monkeypatch)
    responses = {
        ("shell", "pm", "list", "packages"): {
            "ok": True,
            "status": "ok",
            "stdout": "package:com.iotpart.sqe.talkbackhelper\n",
            "stderr": "",
        },
        ("shell", "settings", "get", "secure", "enabled_accessibility_services"): {
            "ok": True,
            "status": "ok",
            "stdout": f"{adb.HELPER_SERVICE_COMPONENT}:com.example/.Other\n",
            "stderr": "",
        },
    }

    monkeypatch.setattr(adb, "run_adb", lambda args, timeout=10.0: responses[tuple(args)])

    result = adb.get_helper_status()

    assert result["status"] == "ok"
    assert result["package_installed"] is True
    assert result["enabled"] is True


def test_helper_status_reports_disabled_when_package_exists_without_service(monkeypatch):
    _fake_helper_apk(monkeypatch)
    responses = {
        ("shell", "pm", "list", "packages"): {
            "ok": True,
            "status": "ok",
            "stdout": "package:com.iotpart.sqe.talkbackhelper\n",
            "stderr": "",
        },
        ("shell", "settings", "get", "secure", "enabled_accessibility_services"): {
            "ok": True,
            "status": "ok",
            "stdout": "com.example/.Other\n",
            "stderr": "",
        },
    }

    monkeypatch.setattr(adb, "run_adb", lambda args, timeout=10.0: responses[tuple(args)])

    result = adb.get_helper_status()

    assert result["status"] == "disabled"
    assert result["installed"] is True
    assert result["accessibility_enabled"] is False
    assert result["package_installed"] is True
    assert result["enabled"] is False


def test_helper_status_reports_not_installed_when_package_missing(monkeypatch):
    _fake_helper_apk(monkeypatch)
    responses = {
        ("shell", "pm", "list", "packages"): {
            "ok": True,
            "status": "ok",
            "stdout": "package:com.example.app\n",
            "stderr": "",
        },
        ("shell", "settings", "get", "secure", "enabled_accessibility_services"): {
            "ok": True,
            "status": "ok",
            "stdout": f"{adb.HELPER_SERVICE_COMPONENT}\n",
            "stderr": "",
        },
    }

    monkeypatch.setattr(adb, "run_adb", lambda args, timeout=10.0: responses[tuple(args)])

    result = adb.get_helper_status()

    assert result["status"] == "not_installed"
    assert result["installed"] is False
    assert result["accessibility_enabled"] is True
    assert result["package_installed"] is False
    assert result["enabled"] is True


def test_helper_status_returns_error_only_when_adb_fails(monkeypatch):
    _fake_helper_apk(monkeypatch)
    failure = {
        "ok": False,
        "status": "error",
        "error": "adb unavailable",
        "stdout": "",
        "stderr": "adb unavailable",
    }

    monkeypatch.setattr(adb, "run_adb", lambda args, timeout=10.0: failure)

    result = adb.get_helper_status()

    assert result["status"] == "error"
    assert result["adb_status"] == "adb_error"
    assert result["package_installed"] is False
    assert result["enabled"] is False


def test_helper_status_reports_apk_not_found_before_adb_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(adb, "_find_helper_apk", lambda: None)
    monkeypatch.setattr(adb, "run_adb", lambda args, timeout=10.0: calls.append(args))

    result = adb.get_helper_status()

    assert result["status"] == "apk_not_found"
    assert result["apk_found"] is False
    assert result["build_command"] == r".\gradlew.bat :app:assembleDebug"
    assert calls == []


def test_install_helper_reports_apk_not_found_with_build_command(monkeypatch):
    monkeypatch.setattr(adb, "_find_helper_apk", lambda: None)

    result = adb.install_helper()

    assert result["ok"] is False
    assert result["status"] == "apk_not_found"
    assert "TalkBack A11y Helper APK not found" in result["error"]
    assert result["apk_searched"] == adb.HELPER_APK_SEARCH_PATTERNS
    assert result["build_command"] == r".\gradlew.bat :app:assembleDebug"


def test_enable_helper_preserves_existing_services_and_appends_helper(monkeypatch):
    _fake_helper_apk(monkeypatch)
    calls = []
    before = "com.google.android.marvin.talkback/.TalkBackService:com.example/.Other"

    def fake_run_adb(args, timeout=10.0):
        calls.append(tuple(args))
        if tuple(args) == ("shell", "settings", "get", "secure", "enabled_accessibility_services"):
            return {"ok": True, "status": "ok", "stdout": before, "stderr": ""}
        if tuple(args[:5]) == ("shell", "settings", "put", "secure", "enabled_accessibility_services"):
            return {"ok": True, "status": "ok", "stdout": "", "stderr": ""}
        if tuple(args) == ("shell", "settings", "put", "secure", "accessibility_enabled", "1"):
            return {"ok": True, "status": "ok", "stdout": "", "stderr": ""}
        if tuple(args) == ("shell", "pm", "list", "packages"):
            return {"ok": True, "status": "ok", "stdout": "package:com.iotpart.sqe.talkbackhelper\n", "stderr": ""}
        raise AssertionError(f"unexpected adb args: {args}")

    monkeypatch.setattr(adb, "run_adb", fake_run_adb)

    result = adb.enable_helper()

    expected = f"{before}:{adb.HELPER_SERVICE_COMPONENT}"
    assert result["helper_service_appended"] is True
    assert result["after_enabled_accessibility_services"] == expected
    assert (
        "shell",
        "settings",
        "put",
        "secure",
        "enabled_accessibility_services",
        expected,
    ) in calls
    assert ("shell", "settings", "put", "secure", "accessibility_enabled", "1") in calls


def test_enable_helper_does_not_duplicate_existing_helper(monkeypatch):
    _fake_helper_apk(monkeypatch)
    calls = []
    before = f"com.example/.Other:{adb.HELPER_SERVICE_COMPONENT}"

    def fake_run_adb(args, timeout=10.0):
        calls.append(tuple(args))
        if tuple(args) == ("shell", "settings", "get", "secure", "enabled_accessibility_services"):
            return {"ok": True, "status": "ok", "stdout": before, "stderr": ""}
        if tuple(args) == ("shell", "settings", "put", "secure", "accessibility_enabled", "1"):
            return {"ok": True, "status": "ok", "stdout": "", "stderr": ""}
        if tuple(args) == ("shell", "pm", "list", "packages"):
            return {"ok": True, "status": "ok", "stdout": "package:com.iotpart.sqe.talkbackhelper\n", "stderr": ""}
        raise AssertionError(f"unexpected adb args: {args}")

    monkeypatch.setattr(adb, "run_adb", fake_run_adb)

    result = adb.enable_helper()

    assert result["helper_service_appended"] is False
    assert result["after_enabled_accessibility_services"] == before
    assert not any(call[:5] == ("shell", "settings", "put", "secure", "enabled_accessibility_services") for call in calls)


def test_enable_talkback_prefers_samsung_service_when_package_exists(monkeypatch):
    calls = []
    before = f"{adb.HELPER_SERVICE_COMPONENT}:com.example/.Other"
    expected = f"{before}:{adb.TALKBACK_SERVICE_CANDIDATES[0]}"

    def fake_run_adb(args, timeout=10.0):
        calls.append(tuple(args))
        if tuple(args) == ("shell", "pm", "list", "packages"):
            return {
                "ok": True,
                "status": "ok",
                "stdout": "package:com.samsung.android.accessibility.talkback\npackage:com.iotpart.sqe.talkbackhelper\n",
                "stderr": "",
            }
        if tuple(args) == ("shell", "settings", "get", "secure", "enabled_accessibility_services"):
            stdout = before if len([call for call in calls if call == tuple(args)]) == 1 else expected
            return {"ok": True, "status": "ok", "stdout": stdout, "stderr": ""}
        if tuple(args) == ("shell", "settings", "get", "secure", "accessibility_enabled"):
            return {"ok": True, "status": "ok", "stdout": "1", "stderr": ""}
        if tuple(args[:5]) == ("shell", "settings", "put", "secure", "enabled_accessibility_services"):
            return {"ok": True, "status": "ok", "stdout": "", "stderr": ""}
        if tuple(args) == ("shell", "settings", "put", "secure", "accessibility_enabled", "1"):
            return {"ok": True, "status": "ok", "stdout": "", "stderr": ""}
        raise AssertionError(f"unexpected adb args: {args}")

    monkeypatch.setattr(adb, "run_adb", fake_run_adb)

    result = adb.enable_talkback()

    assert result["ok"] is True
    assert result["status"] == "enabled"
    assert result["service_name"] == adb.TALKBACK_SERVICE_CANDIDATES[0]
    assert result["enabled_accessibility_services"] == expected
    assert result["helper_service_preserved"] is True
    assert result["talkback_service_appended"] is True


def test_enable_talkback_uses_google_service_when_only_google_package_exists(monkeypatch):
    before = "com.example/.Other"
    expected = f"{before}:{adb.TALKBACK_SERVICE_CANDIDATES[1]}"
    service_reads = {"count": 0}

    def fake_run_adb(args, timeout=10.0):
        if tuple(args) == ("shell", "pm", "list", "packages"):
            return {
                "ok": True,
                "status": "ok",
                "stdout": "package:com.google.android.marvin.talkback\n",
                "stderr": "",
            }
        if tuple(args) == ("shell", "settings", "get", "secure", "enabled_accessibility_services"):
            service_reads["count"] += 1
            return {"ok": True, "status": "ok", "stdout": before if service_reads["count"] == 1 else expected, "stderr": ""}
        if tuple(args) == ("shell", "settings", "get", "secure", "accessibility_enabled"):
            return {"ok": True, "status": "ok", "stdout": "1", "stderr": ""}
        if tuple(args[:5]) == ("shell", "settings", "put", "secure", "enabled_accessibility_services"):
            return {"ok": True, "status": "ok", "stdout": "", "stderr": ""}
        if tuple(args) == ("shell", "settings", "put", "secure", "accessibility_enabled", "1"):
            return {"ok": True, "status": "ok", "stdout": "", "stderr": ""}
        raise AssertionError(f"unexpected adb args: {args}")

    monkeypatch.setattr(adb, "run_adb", fake_run_adb)

    result = adb.enable_talkback()

    assert result["ok"] is True
    assert result["service_name"] == adb.TALKBACK_SERVICE_CANDIDATES[1]
    assert result["enabled_accessibility_services"] == expected


def test_enable_talkback_does_not_duplicate_existing_service(monkeypatch):
    before = f"{adb.HELPER_SERVICE_COMPONENT}:{adb.TALKBACK_SERVICE_CANDIDATES[1]}"
    calls = []

    def fake_run_adb(args, timeout=10.0):
        calls.append(tuple(args))
        if tuple(args) == ("shell", "pm", "list", "packages"):
            return {
                "ok": True,
                "status": "ok",
                "stdout": "package:com.google.android.marvin.talkback\npackage:com.iotpart.sqe.talkbackhelper\n",
                "stderr": "",
            }
        if tuple(args) == ("shell", "settings", "get", "secure", "enabled_accessibility_services"):
            return {"ok": True, "status": "ok", "stdout": before, "stderr": ""}
        if tuple(args) == ("shell", "settings", "get", "secure", "accessibility_enabled"):
            return {"ok": True, "status": "ok", "stdout": "1", "stderr": ""}
        if tuple(args) == ("shell", "settings", "put", "secure", "accessibility_enabled", "1"):
            return {"ok": True, "status": "ok", "stdout": "", "stderr": ""}
        raise AssertionError(f"unexpected adb args: {args}")

    monkeypatch.setattr(adb, "run_adb", fake_run_adb)

    result = adb.enable_talkback()

    assert result["ok"] is True
    assert result["talkback_service_appended"] is False
    assert result["helper_service_preserved"] is True
    assert not any(call[:5] == ("shell", "settings", "put", "secure", "enabled_accessibility_services") for call in calls)


def test_enable_talkback_returns_error_when_no_talkback_package_found(monkeypatch):
    monkeypatch.setattr(
        adb,
        "run_adb",
        lambda args, timeout=10.0: {
            "ok": True,
            "status": "ok",
            "stdout": "package:com.example.app\n" if tuple(args) == ("shell", "pm", "list", "packages") else "",
            "stderr": "",
        },
    )

    result = adb.enable_talkback()

    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["error"] == "TalkBack service package not found"
    assert result["candidates"] == adb.TALKBACK_SERVICE_CANDIDATES
