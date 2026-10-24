from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from talkback_lib.continuous_logcat_capture import ContinuousLogcatCapture
from talkback_lib.hierarchy_publication_evidence import hierarchy_frame_messages, parse_hierarchy_capture


def _fixture(request_id: str, *, omit_chunk: int | None = None, include_end: bool = True) -> bytes:
    payload = json.dumps(
        {"reqId": request_id, "success": True, "nodes": [{"className": "Button"}],
         "windows": [{"id": 1}], "pad": "x" * 1800},
        separators=(",", ":"),
    ).encode()
    count = 62
    chunks = [payload[(len(payload) * i) // count:(len(payload) * (i + 1)) // count] for i in range(count)]
    digest = hashlib.sha256(payload).hexdigest()
    lines = [
        f"DUMP_HIERARCHY_RESULT_CHUNK reqId={request_id} index={index} count={count} "
        f"sha256={digest} payload={base64.b64encode(chunk).decode('ascii')}"
        for index, chunk in enumerate(chunks) if index != omit_chunk
    ]
    if include_end:
        lines.append(f"DUMP_HIERARCHY_END {request_id}")
    return ("\n".join(lines) + "\n").encode()


def _child(command_file: Path) -> list[str]:
    code = (
        "import pathlib,sys,time; "
        "sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes()); sys.stdout.flush(); "
        "sys.stderr.write('capture-stderr-marker\\n'); sys.stderr.flush(); time.sleep(30)"
    )
    return [sys.executable, "-u", "-c", code, str(command_file)]


def _capture(tmp_path: Path, name: str, data: bytes, **kwargs) -> ContinuousLogcatCapture:
    source = tmp_path / f"{name}.input"
    source.write_bytes(data)
    return ContinuousLogcatCapture(
        _child(source), tmp_path / f"{name}.stdout.raw", tmp_path / f"{name}.stderr.raw",
        startup_delay_seconds=0.05, drain_window_seconds=0.05, stop_timeout_seconds=1.0, **kwargs,
    )


def _wait_for_size(path: Path, expected_size: int, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while path.exists() and path.stat().st_size < expected_size and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists() and path.stat().st_size >= expected_size


def test_capture_starts_and_is_confirmed_alive_before_request_dispatch(tmp_path: Path):
    request_id = "capture-order"
    capture = _capture(tmp_path, "order", _fixture(request_id)).start()
    assert capture.is_alive
    assert capture.mark_request_started() is True
    assert capture.metadata["capture_alive_before_request"] is True
    capture.mark_request_completed()
    capture.finish()


def test_capture_survives_the_complete_request_and_bounded_drain(tmp_path: Path):
    capture = _capture(tmp_path, "survive", _fixture("capture-survive")).start()
    assert capture.mark_request_started()
    time.sleep(0.08)
    assert capture.check_health()
    assert capture.is_alive
    assert capture.mark_request_completed()
    metadata = capture.finish()
    assert metadata["capture_alive_after_request"] is True
    assert metadata["termination_reason"] == "requested_after_bounded_drain"


def test_stdout_is_drained_after_process_termination(tmp_path: Path):
    expected = _fixture("capture-drain")
    capture = _capture(tmp_path, "drain", expected).start()
    assert capture.mark_request_started()
    _wait_for_size(capture.stdout_path, len(expected))
    capture.mark_request_completed()
    metadata = capture.finish()
    assert capture.process.poll() is not None
    assert metadata["stdout_drained"] is True
    assert capture.stdout_path.read_bytes() == expected


def test_stderr_is_retained_after_process_termination(tmp_path: Path):
    capture = _capture(tmp_path, "stderr", _fixture("capture-stderr")).start()
    assert capture.mark_request_started()
    _wait_for_size(capture.stderr_path, len(b"capture-stderr-marker\n"))
    capture.mark_request_completed()
    metadata = capture.finish()
    assert metadata["stderr_drained"] is True
    assert b"capture-stderr-marker" in capture.stderr_path.read_bytes()


def test_early_process_exit_is_classified_as_diagnostic_capture_failure(tmp_path: Path):
    capture = ContinuousLogcatCapture(
        [sys.executable, "-c", "print('early-exit')"], tmp_path / "early.out", tmp_path / "early.err",
        startup_delay_seconds=0.2, drain_window_seconds=0.0,
    ).start()
    assert capture.mark_request_started() is False
    metadata = capture.finish()
    assert metadata["capture_failure_reason"] == "process_exited_before_request"
    assert metadata["capture_alive_before_request"] is False
    assert metadata["stdout_drained"] is True


def test_stop_timeout_is_reported_and_process_is_killed(tmp_path: Path):
    class StuckProcess:
        pid = 43210
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            pass

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired("fake-logcat", timeout)
            return self.returncode

        def kill(self):
            self.returncode = -9

    fake = StuckProcess()
    capture = ContinuousLogcatCapture(
        ["fake-logcat"], tmp_path / "timeout.out", tmp_path / "timeout.err", startup_delay_seconds=0.0,
        drain_window_seconds=0.0, stop_timeout_seconds=0.001, popen_factory=lambda *a, **k: fake,
    ).start()
    assert capture.mark_request_started()
    capture.mark_request_completed()
    metadata = capture.finish()
    assert metadata["capture_failure_reason"] == "capture_stop_timeout"
    assert metadata["termination_reason"] == "stop_timeout_kill"
    assert metadata["exit_code"] == -9


def test_raw_capture_is_preserved_before_filtering_and_parser_runs(tmp_path: Path):
    request_id = "capture-preserve"
    expected = _fixture(request_id)
    capture = _capture(tmp_path, "preserve", expected).start()
    assert capture.mark_request_started()
    _wait_for_size(capture.stdout_path, len(expected))
    capture.mark_request_completed()
    metadata = capture.finish()
    raw = capture.stdout_path.read_bytes()
    assert metadata["stdout_drained"] is True
    assert raw == expected
    filtered = "\n".join(hierarchy_frame_messages(raw.decode(), request_id))
    assert len(filtered.splitlines()) == 63
    assert parse_hierarchy_capture(raw.decode(), request_id)["accepted"] is True


def test_complete_63_frame_capture_is_retained_and_parses(tmp_path: Path):
    request_id = "capture-63"
    capture = _capture(tmp_path, "complete63", _fixture(request_id)).start()
    assert capture.mark_request_started()
    _wait_for_size(capture.stdout_path, len(_fixture(request_id)))
    capture.mark_request_completed()
    capture.finish()
    raw = capture.stdout_path.read_bytes().decode()
    assert len(hierarchy_frame_messages(raw, request_id)) == 63
    assert parse_hierarchy_capture(raw, request_id)["terminal_count"] == 1
    assert parse_hierarchy_capture(raw, request_id)["accepted"] is True


def test_missing_middle_frame_is_detected_after_raw_preservation(tmp_path: Path):
    request_id = "capture-middle-missing"
    expected = _fixture(request_id, omit_chunk=31)
    capture = _capture(tmp_path, "middle", expected).start()
    assert capture.mark_request_started()
    _wait_for_size(capture.stdout_path, len(expected))
    capture.mark_request_completed()
    capture.finish()
    raw = capture.stdout_path.read_bytes().decode()
    parsed = parse_hierarchy_capture(raw, request_id)
    assert parsed["accepted"] is False
    assert parsed["reason"] == "missing_chunks"
    assert parsed["missing"] == [31]


def test_missing_end_is_detected_after_raw_preservation(tmp_path: Path):
    request_id = "capture-end-missing"
    capture = _capture(tmp_path, "noend", _fixture(request_id, include_end=False)).start()
    assert capture.mark_request_started()
    expected = _fixture(request_id, include_end=False)
    _wait_for_size(capture.stdout_path, len(expected))
    capture.mark_request_completed()
    capture.finish()
    raw = capture.stdout_path.read_bytes().decode()
    parsed = parse_hierarchy_capture(raw, request_id)
    assert parsed["accepted"] is False
    assert parsed["reason"] == "terminal_count"
    assert parsed["terminal_count"] == 0


def test_sequential_captures_keep_raw_outputs_and_metadata_isolated(tmp_path: Path):
    first = _capture(tmp_path, "first", b"first-request\n").start()
    assert first.mark_request_started()
    _wait_for_size(first.stdout_path, len(b"first-request\n"))
    first.mark_request_completed()
    first_metadata = first.finish()

    second = _capture(tmp_path, "second", b"second-request\n").start()
    assert second.mark_request_started()
    _wait_for_size(second.stdout_path, len(b"second-request\n"))
    second.mark_request_completed()
    second_metadata = second.finish()

    assert first.stdout_path.read_bytes() == b"first-request\n"
    assert second.stdout_path.read_bytes() == b"second-request\n"
    assert first_metadata["stdout_path"] != second_metadata["stdout_path"]
    assert first_metadata["capture_started_at"] != second_metadata["capture_started_at"]
