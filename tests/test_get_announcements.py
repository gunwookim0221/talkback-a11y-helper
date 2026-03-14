from __future__ import annotations

from talkback_lib import A11yAdbClient, LOGCAT_FILTER_SPECS


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_get_announcements_strips_and_deduplicates(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    logs = "\n".join(
        [
            "01-01 00:00:00.000 I/A11Y_HELPER: A11Y_ANNOUNCEMENT:  첫 안내  ",
            "01-01 00:00:00.100 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 첫 안내",
            "01-01 00:00:00.200 I/A11Y_HELPER: A11Y_ANNOUNCEMENT:   둘째 안내   ",
            "01-01 00:00:00.300 I/A11Y_HELPER: A11Y_ANNOUNCEMENT:   ",
        ]
    )

    monkeypatch.setattr(client, "_run", lambda args, dev=None: logs)
    monkeypatch.setattr(client, "check_talkback_status", lambda dev=None: True)

    clock = FakeClock()
    monkeypatch.setattr("talkback_lib.time.monotonic", clock.monotonic)
    monkeypatch.setattr("talkback_lib.time.sleep", clock.sleep)

    assert client.get_announcements(wait_seconds=0.1) == ["첫 안내", "둘째 안내"]
    assert client.last_announcements == ["첫 안내", "둘째 안내"]


def test_get_announcements_polls_until_wait_seconds(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    responses = [
        "01-01 00:00:00.000 I/A11Y_HELPER: unrelated",
        "01-01 00:00:00.100 I/A11Y_HELPER: unrelated",
        "01-01 00:00:00.200 I/A11Y_HELPER: A11Y_ANNOUNCEMENT:  마지막 안내 ",
    ]
    call_count = {"value": 0}

    def fake_run(args, dev=None):
        assert args == ["logcat", "-v", "time", "-d", *LOGCAT_FILTER_SPECS]
        idx = min(call_count["value"], len(responses) - 1)
        call_count["value"] += 1
        return responses[idx]

    monkeypatch.setattr(client, "_run", fake_run)
    monkeypatch.setattr(client, "check_talkback_status", lambda dev=None: True)

    clock = FakeClock()
    monkeypatch.setattr("talkback_lib.time.monotonic", clock.monotonic)
    monkeypatch.setattr("talkback_lib.time.sleep", clock.sleep)

    result = client.get_announcements(wait_seconds=0.6)

    assert result == ["마지막 안내"]
    assert call_count["value"] == 3


def test_get_announcements_only_reads_new_logs(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    responses = [
        "\n".join(
            [
                "01-01 00:00:00.100 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 기존 안내",
                "01-01 00:00:00.200 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 다음 안내",
            ]
        ),
        "\n".join(
            [
                "01-01 00:00:00.100 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 기존 안내",
                "01-01 00:00:00.200 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 다음 안내",
                "01-01 00:00:00.300 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 새 안내",
            ]
        ),
    ]
    call_count = {"value": 0}

    def fake_run(args, dev=None):
        assert args == ["logcat", "-v", "time", "-d", *LOGCAT_FILTER_SPECS]
        idx = min(call_count["value"], len(responses) - 1)
        call_count["value"] += 1
        return responses[idx]

    monkeypatch.setattr(client, "_run", fake_run)
    monkeypatch.setattr(client, "check_talkback_status", lambda dev=None: True)

    clock = FakeClock()
    monkeypatch.setattr("talkback_lib.time.monotonic", clock.monotonic)
    monkeypatch.setattr("talkback_lib.time.sleep", clock.sleep)

    assert client.get_announcements(wait_seconds=0.0) == ["기존 안내", "다음 안내"]
    assert client.get_announcements(wait_seconds=0.0) == ["새 안내"]


def test_get_announcements_can_read_all_buffer_when_only_new_is_false(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    logs = "\n".join(
        [
            "01-01 00:00:00.100 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 기존 안내",
            "01-01 00:00:00.200 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 다음 안내",
            "01-01 00:00:00.300 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 새 안내",
        ]
    )

    monkeypatch.setattr(client, "_run", lambda args, dev=None: logs)
    monkeypatch.setattr(client, "check_talkback_status", lambda dev=None: True)

    clock = FakeClock()
    monkeypatch.setattr("talkback_lib.time.monotonic", clock.monotonic)
    monkeypatch.setattr("talkback_lib.time.sleep", clock.sleep)

    assert client.get_announcements(wait_seconds=0.0) == ["기존 안내", "다음 안내", "새 안내"]
    assert client.get_announcements(wait_seconds=0.0) == []
    assert client.get_announcements(wait_seconds=0.0, only_new=False) == ["기존 안내", "다음 안내", "새 안내"]
    assert client.last_announcements == ["기존 안내", "다음 안내", "새 안내"]
