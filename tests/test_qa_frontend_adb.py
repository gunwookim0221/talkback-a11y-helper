from qa_frontend.backend import adb


def test_helper_status_accepts_short_component_and_reports_ok(monkeypatch):
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
    assert result["package_installed"] is True
    assert result["enabled"] is True


def test_helper_status_accepts_fully_qualified_component_and_reports_ok(monkeypatch):
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


def test_helper_status_reports_installed_but_disabled_when_package_exists_without_service(monkeypatch):
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

    assert result["status"] == "installed_but_disabled"
    assert result["package_installed"] is True
    assert result["enabled"] is False


def test_helper_status_reports_not_installed_when_package_missing(monkeypatch):
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
    assert result["package_installed"] is False
    assert result["enabled"] is True


def test_helper_status_returns_error_only_when_adb_fails(monkeypatch):
    failure = {
        "ok": False,
        "status": "error",
        "error": "adb unavailable",
        "stdout": "",
        "stderr": "adb unavailable",
    }

    monkeypatch.setattr(adb, "run_adb", lambda args, timeout=10.0: failure)

    result = adb.get_helper_status()

    assert result["status"] == "adb_error"
    assert result["package_installed"] is False
    assert result["enabled"] is False
