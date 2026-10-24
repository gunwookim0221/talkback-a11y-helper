from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContinuousLogcatCapture:
    """Bounded raw logcat capture with file-backed stdout/stderr and explicit lifecycle evidence."""

    def __init__(
        self,
        command: Sequence[str],
        stdout_path: Path,
        stderr_path: Path,
        *,
        max_output_bytes: int = 8 * 1024 * 1024,
        drain_window_seconds: float = 1.0,
        stop_timeout_seconds: float = 3.0,
        startup_delay_seconds: float = 0.1,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        utc_now: Callable[[], str] = _utc_now,
    ) -> None:
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes_must_be_positive")
        if min(drain_window_seconds, stop_timeout_seconds, startup_delay_seconds) < 0:
            raise ValueError("capture_durations_must_be_nonnegative")
        self.command = list(command)
        self.stdout_path = Path(stdout_path)
        self.stderr_path = Path(stderr_path)
        self.max_output_bytes = max_output_bytes
        self.drain_window_seconds = drain_window_seconds
        self.stop_timeout_seconds = stop_timeout_seconds
        self.startup_delay_seconds = startup_delay_seconds
        self._popen_factory = popen_factory
        self._monotonic = monotonic
        self._sleep = sleep
        self._utc_now = utc_now
        self._process: Any | None = None
        self._stdout_file: Any | None = None
        self._stderr_file: Any | None = None
        self._started_monotonic: float | None = None
        self._ended_monotonic: float | None = None
        self._request_started_monotonic: float | None = None
        self._request_completed_monotonic: float | None = None
        self._failure_reason: str | None = None
        self._termination_reason: str | None = None
        self._stdout_drained = False
        self._stderr_drained = False
        self._finalized = False
        self._alive_before_request: bool | None = None
        self._alive_after_request: bool | None = None
        self._metadata: dict[str, Any] = {
            "command": self.command,
            "capture_pid": None,
            "capture_started_at": None,
            "hierarchy_request_started_at": None,
            "hierarchy_request_completed_at": None,
            "capture_ended_at": None,
            "exit_code": None,
            "termination_reason": None,
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "stdout_drained": False,
            "stderr_drained": False,
            "capture_process_started": False,
            "capture_alive_before_request": None,
            "capture_alive_after_request": None,
            "capture_duration_ms": None,
            "capture_failure_reason": None,
            "max_output_bytes": self.max_output_bytes,
            "stdout_sink": "direct_file",
            "stderr_sink": "direct_file",
        }

    @property
    def metadata(self) -> dict[str, Any]:
        self._refresh_metadata()
        return dict(self._metadata)

    @property
    def process(self) -> Any | None:
        return self._process

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None and not self._finalized

    def start(self) -> "ContinuousLogcatCapture":
        if self._started_monotonic is not None:
            raise RuntimeError("capture_already_started")
        self.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self._started_monotonic = self._monotonic()
        self._metadata["capture_started_at"] = self._utc_now()
        try:
            self._stdout_file = self.stdout_path.open("wb")
            self._stderr_file = self.stderr_path.open("wb")
            self._process = self._popen_factory(
                self.command,
                stdin=subprocess.DEVNULL,
                stdout=self._stdout_file,
                stderr=self._stderr_file,
                bufsize=0,
            )
            self._metadata["capture_pid"] = getattr(self._process, "pid", None)
            self._metadata["capture_process_started"] = True
            self._sleep(self.startup_delay_seconds)
            if self._process.poll() is not None:
                self._failure_reason = "process_exited_before_request"
                self._termination_reason = "early_process_exit"
        except Exception as exc:
            self._failure_reason = f"start_error:{type(exc).__name__}"
            self._termination_reason = "start_error"
            self._close_sinks()
        self._refresh_metadata()
        return self

    def mark_request_started(self) -> bool:
        if self._request_started_monotonic is not None:
            raise RuntimeError("request_start_already_recorded")
        self._request_started_monotonic = self._monotonic()
        self._metadata["hierarchy_request_started_at"] = self._utc_now()
        self._alive_before_request = self.is_alive
        if not self._alive_before_request:
            self._failure_reason = self._failure_reason or "capture_not_alive_before_request"
        self._refresh_metadata()
        return bool(self._alive_before_request)

    def check_health(self) -> bool:
        """Check liveness and the per-capture raw byte bound while a request is running."""
        if self._finalized:
            return False
        if self._process is None or self._process.poll() is not None:
            if self._request_started_monotonic is not None and self._request_completed_monotonic is None:
                self._failure_reason = self._failure_reason or "process_exited_during_request"
            elif self._process is not None and self._request_completed_monotonic is not None:
                self._failure_reason = self._failure_reason or "process_exited_before_capture_stop"
            return False
        if self._current_output_bytes() > self.max_output_bytes:
            self._failure_reason = "raw_output_limit_exceeded"
            self._termination_reason = "raw_output_limit_exceeded"
            try:
                self._process.terminate()
            except Exception:
                pass
            return False
        return True

    def mark_request_completed(self) -> bool:
        if self._request_started_monotonic is None:
            raise RuntimeError("request_start_not_recorded")
        if self._request_completed_monotonic is not None:
            raise RuntimeError("request_completion_already_recorded")
        self._request_completed_monotonic = self._monotonic()
        self._metadata["hierarchy_request_completed_at"] = self._utc_now()
        self._alive_after_request = self.is_alive
        if not self._alive_after_request:
            self._failure_reason = self._failure_reason or "process_exited_before_request_completed"
        self._refresh_metadata()
        return bool(self._alive_after_request)

    def finish(self) -> dict[str, Any]:
        if self._finalized:
            return self.metadata
        if self._request_completed_monotonic is not None and self.drain_window_seconds:
            deadline = self._monotonic() + self.drain_window_seconds
            while self._monotonic() < deadline:
                if not self.check_health():
                    break
                self._sleep(min(0.05, max(0.0, deadline - self._monotonic())))

        if self._process is not None:
            if self._process.poll() is None:
                self._termination_reason = self._termination_reason or "requested_after_bounded_drain"
                try:
                    self._process.terminate()
                except Exception:
                    self._failure_reason = self._failure_reason or "terminate_error"
                try:
                    self._process.wait(timeout=self.stop_timeout_seconds)
                except subprocess.TimeoutExpired:
                    self._termination_reason = "stop_timeout_kill"
                    self._failure_reason = self._failure_reason or "capture_stop_timeout"
                    try:
                        self._process.kill()
                    except Exception:
                        self._failure_reason = self._failure_reason or "kill_error"
                    try:
                        self._process.wait(timeout=self.stop_timeout_seconds)
                    except Exception:
                        self._failure_reason = self._failure_reason or "capture_process_not_reaped"
            else:
                self._termination_reason = self._termination_reason or "process_exited_early"
        self._ended_monotonic = self._monotonic()
        self._metadata["capture_ended_at"] = self._utc_now()
        self._close_sinks()
        self._finalized = True
        self._refresh_metadata()
        return self.metadata

    def _current_output_bytes(self) -> int:
        total = 0
        for path in (self.stdout_path, self.stderr_path):
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    def _close_sinks(self) -> None:
        for attribute, status_name in (("_stdout_file", "_stdout_drained"), ("_stderr_file", "_stderr_drained")):
            sink = getattr(self, attribute)
            if sink is None:
                continue
            if getattr(sink, "closed", False):
                setattr(self, status_name, True)
                continue
            try:
                sink.flush()
                os.fsync(sink.fileno())
            except Exception:
                self._failure_reason = self._failure_reason or f"{status_name.removeprefix('_')}_error"
            finally:
                try:
                    sink.close()
                    setattr(self, status_name, True)
                except Exception:
                    self._failure_reason = self._failure_reason or f"{status_name.removeprefix('_')}_close_error"

    def _refresh_metadata(self) -> None:
        self._metadata["capture_alive_before_request"] = self._alive_before_request
        self._metadata["capture_alive_after_request"] = self._alive_after_request
        self._metadata["stdout_drained"] = self._stdout_drained
        self._metadata["stderr_drained"] = self._stderr_drained
        self._metadata["capture_failure_reason"] = self._failure_reason
        self._metadata["termination_reason"] = self._termination_reason
        if self._process is not None:
            try:
                self._metadata["exit_code"] = self._process.poll()
            except Exception:
                self._metadata["exit_code"] = None
        for key, path in (("stdout_bytes", self.stdout_path), ("stderr_bytes", self.stderr_path)):
            try:
                self._metadata[key] = path.stat().st_size
            except OSError:
                self._metadata[key] = 0
        if self._started_monotonic is not None and self._ended_monotonic is not None:
            self._metadata["capture_duration_ms"] = round((self._ended_monotonic - self._started_monotonic) * 1000)
