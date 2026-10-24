from __future__ import annotations

from pathlib import Path

import pytest

import tools.hierarchy_publication_diagnostic as diagnostic_module
from tools.hierarchy_publication_diagnostic import OneShotDiagnostic
from tools.hierarchy_publication_overnight_soak import OvernightSoak, classify_iteration


CAPTURE_OK = {
    "capture_process_started": True,
    "capture_alive_before_request": True,
    "capture_alive_after_request": True,
    "stdout_drained": True,
    "stderr_drained": True,
    "capture_failure_reason": None,
    "termination_reason": "requested_after_bounded_drain",
}


def _result(*, raw: int = 63, runner: int = 63, parser: int = 63, accepted: bool = True,
            primary: str = "G. NO_LOSS_OBSERVED_THIS_SINGLE_DIAGNOSTIC") -> dict:
    return {
        "comparison": {
            "primary_loss_layer": primary,
            "helper_attempted_frame_count": 63,
            "raw_logcat_observed_frame_count": raw,
            "runner_observed_frame_count": runner,
            "parser_accepted_frame_count": parser,
            "missing_frame_matrix": [],
        },
        "summary": {"evidence_complete": True, "finalized": True, "plan_complete": True},
        "runner_parser": {"accepted": accepted},
    }


def test_clean_sample_is_pass_all_layers():
    assert classify_iteration(_result(), CAPTURE_OK, None) == "PASS_ALL_LAYERS"


def test_healthy_continuous_reader_gap_with_complete_runner_is_independent_reader_failure():
    result = _result(raw=5, runner=63, primary="H. EVIDENCE_INCOMPLETE")
    assert classify_iteration(result, CAPTURE_OK, None) == "INDEPENDENT_LOGCAT_READER_MISSING"


def test_capture_process_failure_is_not_misclassified_as_transport_loss():
    result = _result(raw=5, runner=63, primary="H. EVIDENCE_INCOMPLETE")
    broken_capture = dict(CAPTURE_OK, capture_alive_after_request=False,
                          capture_failure_reason="process_exited_during_request")
    assert classify_iteration(result, broken_capture, None) == "DIAGNOSTIC_CAPTURE_FAILURE"


def test_runner_raw_gap_remains_distinct_from_capture_failure():
    result = _result(raw=63, runner=62, parser=62, accepted=False,
                     primary="D. RAW_LOGCAT_PRESENT_RUNNER_MISSING")
    assert classify_iteration(result, CAPTURE_OK, None) == "RAW_PRESENT_RUNNER_MISSING"


def test_parser_rejection_is_separate_from_runner_raw_missing():
    result = _result(raw=63, runner=63, parser=0, accepted=False,
                     primary="E. RUNNER_PRESENT_PARSER_REJECTED")
    assert classify_iteration(result, CAPTURE_OK, None) == "RUNNER_PRESENT_PARSER_REJECTED"


def test_lifecycle_failure_is_not_called_a_capture_failure():
    assert classify_iteration(None, {}, "device_offline") == "SERVICE_LIFECYCLE_FAILURE"


def test_one_shot_starts_and_confirms_capture_before_hierarchy_dispatch(tmp_path: Path, monkeypatch):
    events: list[str] = []

    class FakeCapture:
        def __init__(self, command, stdout_path, stderr_path, **kwargs):
            self.command = command
            self.stdout_path = Path(stdout_path)
            self.stderr_path = Path(stderr_path)
            self.metadata = dict(CAPTURE_OK, capture_process_started=True, capture_pid=9,
                                 stdout_bytes=0, stderr_bytes=0, termination_reason="requested_after_bounded_drain")

        def start(self):
            events.append("capture_started")
            self.stdout_path.parent.mkdir(parents=True, exist_ok=True)
            self.stdout_path.write_bytes(b"")
            self.stderr_path.write_bytes(b"")
            return self

        def mark_request_started(self):
            events.append("capture_confirmed_alive_before_request")
            return True

        def check_health(self):
            return True

        def mark_request_completed(self):
            events.append("hierarchy_terminal_observed")
            return True

        def finish(self):
            events.append("capture_drained_and_stopped")
            return self.metadata

    monkeypatch.setattr(diagnostic_module, "ContinuousLogcatCapture", FakeCapture)
    diag = OneShotDiagnostic("adb", "serial", tmp_path / "sample", {})

    def fake_command(name, args, timeout, *, on_poll=None):
        events.append("hierarchy_dispatched")
        assert on_poll is not None
        return {"args": args, "returncode": 0, "stdout": "", "stderr": "", "stdout_bytes": 0, "stderr_bytes": 0}

    diag._command = fake_command
    diag._one_hierarchy_request()
    assert events == [
        "capture_started", "capture_confirmed_alive_before_request", "hierarchy_dispatched",
        "hierarchy_terminal_observed", "capture_drained_and_stopped",
    ]
    assert diag.hierarchy_request_count == 1
    assert (tmp_path / "sample" / "continuous_capture" / "capture_metadata.json").exists()


def test_soak_limits_cannot_exceed_sixty_iterations_or_five_hours(tmp_path: Path):
    config = Path("app/build/generated/source/buildConfig/debug/com/iotpart/sqe/talkbackhelper/BuildConfig.java")
    with pytest.raises(ValueError, match="invalid_soak_bounds"):
        OvernightSoak(adb="adb", serial="device", output=tmp_path / "bad", expected_build_config=config,
                      max_iterations=61)
    runner = OvernightSoak(adb="adb", serial="device", output=tmp_path / "bounded",
                           expected_build_config=config, max_iterations=1, duration_seconds=99_999)
    assert runner.duration_seconds == 5 * 60 * 60
