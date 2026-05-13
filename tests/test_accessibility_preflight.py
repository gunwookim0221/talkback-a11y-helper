from tb_runner.accessibility_preflight import (
    HELPER_SERVICE_COMPONENT,
    build_enabled_accessibility_services_value,
    ensure_accessibility_service_enabled,
    has_helper_service,
    is_accessibility_enabled,
    split_enabled_accessibility_services,
)


def test_build_enabled_services_does_not_duplicate_existing_helper():
    current = f"com.example/.Other:{HELPER_SERVICE_COMPONENT}"

    result = build_enabled_accessibility_services_value(current)

    assert result == current


def test_build_enabled_services_preserves_other_services_when_appending_helper():
    current = "com.example/.Other:com.vendor/.Reader"

    result = build_enabled_accessibility_services_value(current)

    assert result == f"{current}:{HELPER_SERVICE_COMPONENT}"


def test_build_enabled_services_handles_empty_and_null_values():
    assert split_enabled_accessibility_services("") == []
    assert split_enabled_accessibility_services("null") == []
    assert split_enabled_accessibility_services(None) == []
    assert build_enabled_accessibility_services_value("") == HELPER_SERVICE_COMPONENT
    assert build_enabled_accessibility_services_value("null") == HELPER_SERVICE_COMPONENT


def test_accessibility_enabled_value_parsing():
    assert is_accessibility_enabled("1") is True
    assert is_accessibility_enabled("0") is False
    assert is_accessibility_enabled("") is False
    assert is_accessibility_enabled("null") is False


def test_has_helper_service_is_case_insensitive():
    assert has_helper_service(HELPER_SERVICE_COMPONENT.upper()) is True


def test_ensure_accessibility_service_appends_and_enables_then_checks_ready():
    settings = {
        "enabled_accessibility_services": "com.example/.Other",
        "accessibility_enabled": "0",
    }
    writes = []

    def adb_get(key):
        return settings[key]

    def adb_put(key, value):
        writes.append((key, value))
        settings[key] = value
        return True

    result = ensure_accessibility_service_enabled(
        adb_get=adb_get,
        adb_put=adb_put,
        helper_ready_check=lambda: True,
        settle_seconds=0,
    )

    assert result.ok is True
    assert result.enable_attempted is True
    assert result.helper_ready is True
    assert writes == [
        ("enabled_accessibility_services", f"com.example/.Other:{HELPER_SERVICE_COMPONENT}"),
        ("accessibility_enabled", "1"),
    ]
    assert result.before.enabled_accessibility_services == "com.example/.Other"
    assert result.after.enabled_accessibility_services == f"com.example/.Other:{HELPER_SERVICE_COMPONENT}"


def test_ensure_accessibility_service_reports_enable_attempt_failure():
    settings = {
        "enabled_accessibility_services": "",
        "accessibility_enabled": "0",
    }
    logs = []

    result = ensure_accessibility_service_enabled(
        adb_get=lambda key: settings[key],
        adb_put=lambda _key, _value: False,
        helper_ready_check=lambda: True,
        log_fn=logs.append,
        settle_seconds=0,
    )

    assert result.ok is False
    assert result.reason == "enable_attempt_failed"
    assert any("accessibility_disabled" in line for line in logs)
    assert any("helper_service_missing" in line for line in logs)
    assert any("enable_attempt_failed" in line for line in logs)


def test_ensure_accessibility_service_reports_helper_ready_timeout():
    settings = {
        "enabled_accessibility_services": HELPER_SERVICE_COMPONENT,
        "accessibility_enabled": "1",
    }
    logs = []

    result = ensure_accessibility_service_enabled(
        adb_get=lambda key: settings[key],
        adb_put=lambda _key, _value: True,
        helper_ready_check=lambda: False,
        log_fn=logs.append,
        settle_seconds=0,
    )

    assert result.ok is False
    assert result.reason == "helper_ready_timeout"
    assert any("helper_ready_timeout" in line for line in logs)
