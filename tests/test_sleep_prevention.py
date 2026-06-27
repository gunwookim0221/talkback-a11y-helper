from qa_frontend.backend import sleep_prevention


def _reset_sleep_prevention_state() -> None:
    with sleep_prevention._lock:
        sleep_prevention._request_count = 0
        sleep_prevention._worker = None


def test_enable_disable_sleep_prevention_calls_windows_execution_state(monkeypatch):
    _reset_sleep_prevention_state()
    calls = []

    monkeypatch.setattr(sleep_prevention.sys, "platform", "win32")
    monkeypatch.setattr(sleep_prevention, "_set_thread_execution_state", lambda flags: calls.append(flags) or 1)

    assert sleep_prevention.enable_sleep_prevention() is True
    assert sleep_prevention.disable_sleep_prevention() is True

    assert calls == [
        sleep_prevention.ES_CONTINUOUS
        | sleep_prevention.ES_SYSTEM_REQUIRED
        | sleep_prevention.ES_DISPLAY_REQUIRED,
        sleep_prevention.ES_CONTINUOUS,
    ]


def test_sleep_prevention_is_noop_off_windows(monkeypatch):
    _reset_sleep_prevention_state()
    calls = []

    monkeypatch.setattr(sleep_prevention.sys, "platform", "linux")
    monkeypatch.setattr(sleep_prevention, "_set_thread_execution_state", lambda flags: calls.append(flags) or 1)

    assert sleep_prevention.enable_sleep_prevention() is False
    assert sleep_prevention.disable_sleep_prevention() is False
    assert calls == []


def test_device_stay_awake_applies_setting_15_and_restores_original_setting():
    calls = []
    settings = iter(["3", "15", "15"])

    def adb_runner(args, timeout):
        calls.append(args)
        if args[:5] == ["shell", "settings", "get", "global", "stay_on_while_plugged_in"]:
            return {"ok": True, "stdout": next(settings)}
        return {"ok": True, "stdout": ""}

    state = sleep_prevention.enable_device_stay_awake(adb_runner)
    restored = sleep_prevention.restore_device_stay_awake(state, adb_runner)

    assert state["ok"] is True
    assert state["original_setting"] == "3"
    assert [
        "shell",
        "settings",
        "put",
        "global",
        "stay_on_while_plugged_in",
        "15",
    ] in calls
    assert calls[-1] == [
        "shell",
        "settings",
        "put",
        "global",
        "stay_on_while_plugged_in",
        "3",
    ]
    assert restored["restored"] is True


def test_device_stay_awake_does_not_overwrite_setting_changed_during_run():
    settings = iter(["0", "15", "1"])
    calls = []

    def adb_runner(args, timeout):
        calls.append(args)
        if args[:5] == ["shell", "settings", "get", "global", "stay_on_while_plugged_in"]:
            return {"ok": True, "stdout": next(settings)}
        return {"ok": True, "stdout": ""}

    state = sleep_prevention.enable_device_stay_awake(adb_runner)
    restored = sleep_prevention.restore_device_stay_awake(state, adb_runner)

    assert restored == {"ok": True, "restored": False, "reason": "setting_changed_externally"}
    assert not any(
        args[:5] == ["shell", "settings", "put", "global", "stay_on_while_plugged_in"]
        and args[-1] == "0"
        for args in calls
    )


def test_device_stay_awake_targets_serial_and_restores_nonzero_value():
    calls = []
    settings = iter(["7", "15", "15"])

    def adb_runner(args, timeout):
        calls.append(args)
        command = args[2:] if args[:2] == ["-s", "SERIAL"] else args
        if command[:5] == ["shell", "settings", "get", "global", "stay_on_while_plugged_in"]:
            return {"ok": True, "stdout": next(settings)}
        return {"ok": True, "stdout": ""}

    state = sleep_prevention.enable_device_stay_awake(adb_runner, serial="SERIAL")
    restored = sleep_prevention.restore_device_stay_awake(state, adb_runner)

    assert state["serial"] == "SERIAL"
    assert restored["original_setting"] == "7"
    assert all(args[:2] == ["-s", "SERIAL"] for args in calls)
    assert calls[-1] == [
        "-s",
        "SERIAL",
        "shell",
        "settings",
        "put",
        "global",
        "stay_on_while_plugged_in",
        "7",
    ]
