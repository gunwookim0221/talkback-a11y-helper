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
