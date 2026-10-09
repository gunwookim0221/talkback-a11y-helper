from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tools.full32_acceptance_monitor import AcceptanceMonitor, HELPER_PACKAGE, TALKBACK_PACKAGE


START = datetime(2026, 10, 9, 7, 40, 0, tzinfo=timezone.utc)


def monitor() -> AcceptanceMonitor:
    return AcceptanceMonitor(START, talkback_pid="17467", helper_pid="28110")


def lifecycle(**overrides: object) -> str:
    event = {
        "timestamp": "2026-10-09T07:40:01.000+00:00",
        "talkback_pid": "17467",
        "previous_talkback_pid": "17467",
        "talkback_restart_detected": False,
        "search_screen_overlay_window_count": 1,
    }
    event.update(overrides)
    return json.dumps(event)


def test_real_helper_anr_stops_only_for_helper_process_identity() -> None:
    result = monitor().feed_line(
        "10-09 16:40:01.100  1000  1000 E ActivityManager: ANR in " + HELPER_PACKAGE,
        source="logcat",
    )
    assert [hit.code for hit in result] == ["helper_anr"]
    assert "pid=28110" in result[0].evidence


def test_real_helper_crash_requires_helper_package_and_pid() -> None:
    subject = monitor()
    lines = [
        "10-09 16:40:01.100 28110 28110 E AndroidRuntime: FATAL EXCEPTION: main",
        f"10-09 16:40:01.110 28110 28110 E AndroidRuntime: Process: {HELPER_PACKAGE}, PID: 28110",
        "10-09 16:40:01.120 28110 28110 E AndroidRuntime: java.lang.IllegalStateException: test crash",
    ]
    hits = [hit for line in lines for hit in subject.feed_line(line, source="logcat")]
    assert [hit.code for hit in hits] == ["helper_crash"]

    unrelated = monitor()
    lines = [
        "10-09 16:40:01.100 2100 2100 E AndroidRuntime: FATAL EXCEPTION: main",
        "10-09 16:40:01.110 2100 2100 E AndroidRuntime: Process: com.samsung.android.oneconnect, PID: 2100",
        "10-09 16:40:01.120 2100 2100 E AndroidRuntime: java.lang.IllegalStateException: test crash",
    ]
    assert not [hit for line in lines for hit in unrelated.feed_line(line, source="logcat")]


def test_unrelated_oneconnect_anr_text_is_ignored() -> None:
    result = monitor().feed_line(
        "10-09 16:40:01.100  1000  1000 E ActivityManager: ANR in com.samsung.android.oneconnect",
        source="logcat",
    )
    assert result == []


def test_caught_nonfatal_talkback_badtoken_with_same_pid_is_ignored() -> None:
    subject = monitor()
    result = subject.feed_line(
        "10-09 16:40:01.100 17467 17467 W TalkBack: caught BadTokenException; continuing",
        source="logcat",
    )
    result += subject.feed_lifecycle(lifecycle())
    assert result == []


def test_fatal_talkback_badtoken_stops_when_pid_restarts() -> None:
    subject = monitor()
    lines = [
        "10-09 16:40:01.100 17467 17467 E AndroidRuntime: FATAL EXCEPTION: main",
        f"10-09 16:40:01.110 17467 17467 E AndroidRuntime: Process: {TALKBACK_PACKAGE}, PID: 17467",
        "10-09 16:40:01.120 17467 17467 E AndroidRuntime: android.view.WindowManager$BadTokenException",
    ]
    hits = [hit for line in lines for hit in subject.feed_line(line, source="logcat")]
    assert hits == []
    hits = subject.feed_lifecycle(lifecycle(
        timestamp="2026-10-09T07:40:02.000+00:00",
        talkback_pid="19001",
        previous_talkback_pid="17467",
        talkback_restart_detected=True,
    ))
    assert [hit.code for hit in hits] == ["talkback_pid_change"]


def test_talkback_window_limit_marker_requires_talkback_identity() -> None:
    result = monitor().feed_line(
        f"[TALKBACK_WINDOW_FATAL] package={TALKBACK_PACKAGE} pid=17467 window count is over max!!",
        source="runner",
    )
    assert [hit.code for hit in result] == ["talkback_window_fatal"]


def test_old_stale_fatal_line_before_monitor_start_is_ignored() -> None:
    result = monitor().feed_line(
        "2026-10-09T07:39:59.000+00:00 AndroidRuntime FATAL EXCEPTION: main "
        f"Process: {TALKBACK_PACKAGE}, PID: 17467",
        source="runner",
    )
    assert result == []


def test_talkback_pid_change_is_a_hard_stop() -> None:
    subject = monitor()
    subject.feed_lifecycle(lifecycle())
    result = subject.feed_lifecycle(lifecycle(
        timestamp="2026-10-09T07:40:02.000+00:00",
        talkback_pid="19001",
        previous_talkback_pid="17467",
    ))
    assert [hit.code for hit in result] == ["talkback_pid_change"]


def test_unrelated_warning_with_crash_text_is_ignored() -> None:
    result = monitor().feed_line(
        "10-09 16:40:01.100  2100  2100 W OneConnect: crash recovery warning handled",
        source="logcat",
    )
    assert result == []


def test_smart_next_timeout_requires_fresh_correlated_helper_request() -> None:
    subject = monitor()
    result = subject.feed_line(
        f"[HELPER_COMMAND_TIMEOUT] action=SMART_NEXT request_id=SN-42 package={HELPER_PACKAGE} pid=28110 timeout_ms=5000",
        source="runner",
    )
    assert [hit.code for hit in result] == ["smart_next_timeout"]

    uncorrelated = subject.feed_line(
        "SMART_NEXT timeout while waiting for device",
        source="runner",
    )
    assert uncorrelated == []


def test_false_talkback_restart_json_key_is_not_a_restart_marker() -> None:
    result = monitor().feed_line(
        '[TALKBACK_WINDOW] {"talkback_restart_detected":false,"talkback_pid":"17467"}',
        source="runner",
    )
    assert result == []


def broadcast(request_id="real-req", command="SMART_NEXT", timestamp=""):
    tag = "SMART_NEXT_TRACE" if command == "SMART_NEXT" else "FOCUS_TRANSPORT"
    return f"{timestamp}[{tag}] before_broadcast action={HELPER_PACKAGE}.{command} req_id={request_id} fallback=false"


def terminal(request_id="real-req", command="SMART_NEXT", status="transport_error", reason="smart_nav_result_wait_timeout"):
    tag = "SMART_NEXT_TRANSPORT" if command == "SMART_NEXT" else "FOCUS_TRANSPORT"
    return f"[{tag}] completed req_id={request_id} status={status} reason={reason} retry=false"


def test_actual_smart_next_trace_format_correlates_owned_timeout_once():
    subject = monitor()
    assert subject.feed_line(broadcast(), source="runner") == []
    hit = subject.feed_line(terminal(), source="runner")
    assert [h.code for h in hit] == ["smart_next_timeout"]
    assert "request_id=real-req" in hit[0].evidence
    assert subject.feed_line(terminal(), source="runner") == []
    assert subject._requests == {}


def test_success_retires_request_and_does_not_stop_on_late_timeout():
    subject = monitor()
    subject.feed_line(broadcast(), source="runner")
    assert subject.feed_line(terminal(status="moved", reason=""), source="runner") == []
    assert subject.feed_line(terminal(), source="runner") == []


def test_unknown_or_different_request_timeout_is_ignored():
    subject = monitor()
    subject.feed_line(broadcast(), source="runner")
    assert subject.feed_line(terminal("different"), source="runner") == []
    assert subject.feed_line("OneConnect warning: SMART_NEXT timeout", source="runner") == []


def test_stale_broadcast_does_not_create_owned_request():
    subject = monitor()
    subject.feed_line(broadcast(timestamp="2026-10-09T07:39:59+00:00 "), source="runner")
    assert subject.feed_line(terminal(), source="runner") == []


def test_expired_request_is_evicted_and_cannot_attribute_timeout():
    subject = monitor()
    subject.feed_line(broadcast(), source="runner", observed_at=START)
    assert subject.feed_line(terminal(), source="runner", observed_at=START+timedelta(minutes=6)) == []
    assert subject._requests == {}


def test_request_ledger_remains_bounded():
    subject = monitor()
    for i in range(520):
        subject.feed_line(broadcast(str(i)), source="runner", observed_at=START)
    assert len(subject._requests) == 512
    assert subject.feed_line(terminal("0"), source="runner", observed_at=START) == []


@pytest.mark.parametrize("command", ["FOCUS_IN_BOUNDS", "TARGET_FOCUS_COMMIT"])
def test_correlated_focus_target_transport_timeout_remains_a_blocker(command):
    subject = monitor()
    subject.feed_line(broadcast(command=command), source="runner")
    hits = subject.feed_line(terminal(command=command, reason="focus_result_wait_timeout"), source="runner")
    assert [h.code for h in hits] == ["focus_transport_error"]


def test_python_repr_reqid_timeout_trace_matches_real_runner_format():
    subject = monitor()
    subject.feed_line(broadcast(), source="runner")
    line = "[SMART_NEXT_TRACE] read_log_result_miss prefix=SMART_NAV_RESULT req_id=real-req parsed={'success': False, 'reason': 'smart_nav_result_wait_timeout', 'reqId': 'real-req', 'status': 'transport_error'}"
    assert [h.code for h in subject.feed_line(line, source="runner")] == ["smart_next_timeout"]


def test_other_process_or_logcat_broadcast_cannot_own_runner_request():
    subject = monitor()
    subject.feed_line(broadcast().replace(HELPER_PACKAGE, "com.unrelated.helper"), source="runner")
    subject.feed_line(broadcast(), source="logcat")
    assert subject.feed_line(terminal(), source="runner") == []


def test_known_request_non_timeout_transport_error_is_a_blocker():
    subject = monitor()
    subject.feed_line(broadcast(), source="runner")
    hits = subject.feed_line(terminal(reason="chunk_digest_mismatch"), source="runner")
    assert [h.code for h in hits] == ["smart_next_transport_error"]
