from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

ONECONNECT_PACKAGE = "com.samsung.android.oneconnect"
FATAL_EXCEPTION_TOKEN = "FATAL EXCEPTION"
PROCESS_TOKEN = f"Process: {ONECONNECT_PACKAGE}"
CRASH_BLOCK_SOURCE_TOKEN = "AndroidRuntime"

LogWriter = Callable[[str], None]


@dataclass(frozen=True)
class CrashEvent:
    crash_event_id: str
    crash_type: str
    process: str
    exception: str | None
    top_frame: str | None
    timestamp: str
    logcat_excerpt: str

    def to_json(self) -> dict[str, object]:
        return {
            "crash_event_id": self.crash_event_id,
            "crash_type": self.crash_type,
            "process": self.process,
            "exception": self.exception,
            "top_frame": self.top_frame,
            "timestamp": self.timestamp,
        }


class CrashEventStore:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.crashes_dir = output_dir / "crashes"
        self._lock = threading.Lock()
        self._next_index = self._discover_next_index()
        self._seen_keys: set[tuple[str | None, str | None, str]] = set()

    def save_event(self, event: CrashEvent) -> None:
        event_dir = self.crashes_dir / event.crash_event_id
        event_dir.mkdir(parents=True, exist_ok=True)
        (event_dir / "crash_event.json").write_text(
            json.dumps(event.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (event_dir / "logcat_excerpt.txt").write_text(event.logcat_excerpt, encoding="utf-8", errors="replace")

    def next_event_id(self) -> str:
        with self._lock:
            event_id = f"CRASH-{self._next_index:04d}"
            self._next_index += 1
            return event_id

    def mark_seen(self, event: CrashEvent) -> bool:
        key = (event.exception, event.top_frame, event.logcat_excerpt)
        with self._lock:
            if key in self._seen_keys:
                return False
            self._seen_keys.add(key)
            return True

    def _discover_next_index(self) -> int:
        if not self.crashes_dir.is_dir():
            return 1
        highest = 0
        for path in self.crashes_dir.iterdir():
            match = re.fullmatch(r"CRASH-(\d{4})", path.name)
            if match:
                highest = max(highest, int(match.group(1)))
        return highest + 1


class OneConnectCrashDetector:
    def __init__(self, store: CrashEventStore) -> None:
        self.store = store
        self._current_block: list[str] = []
        self._in_fatal_block = False

    def feed_line(self, line: str) -> list[CrashEvent]:
        events: list[CrashEvent] = []
        if FATAL_EXCEPTION_TOKEN in line:
            events.extend(self._finish_current_block())
            self._current_block = [line]
            self._in_fatal_block = True
            return events

        if not self._in_fatal_block:
            return events

        if self._is_crash_continuation(line):
            self._current_block.append(line)
            return events

        events.extend(self._finish_current_block())
        return events

    def finish(self) -> list[CrashEvent]:
        return self._finish_current_block()

    def _finish_current_block(self) -> list[CrashEvent]:
        if not self._current_block:
            self._in_fatal_block = False
            return []
        block = self._current_block
        self._current_block = []
        self._in_fatal_block = False
        event = self._event_from_block(block)
        if not event:
            return []
        if not self.store.mark_seen(event):
            return []
        self.store.save_event(event)
        return [event]

    def _event_from_block(self, block: list[str]) -> CrashEvent | None:
        text = "".join(block)
        if FATAL_EXCEPTION_TOKEN not in text or PROCESS_TOKEN not in text:
            return None
        exception = _extract_exception(block)
        top_frame = _extract_top_frame(block)
        return CrashEvent(
            crash_event_id=self.store.next_event_id(),
            crash_type="CONFIRMED_CRASH",
            process=ONECONNECT_PACKAGE,
            exception=exception,
            top_frame=top_frame,
            timestamp=_extract_timestamp(block) or datetime.now(timezone.utc).isoformat(),
            logcat_excerpt=text,
        )

    @staticmethod
    def _is_crash_continuation(line: str) -> bool:
        if not line.strip():
            return True
        if CRASH_BLOCK_SOURCE_TOKEN in line:
            return True
        stripped = _strip_logcat_prefix(line).strip()
        return (
            stripped.startswith("at ")
            or stripped.startswith("Caused by:")
            or stripped.startswith("Suppressed:")
            or stripped.startswith("... ")
        )


class LogcatCapture:
    def __init__(
        self,
        *,
        serial: str | None,
        output_dir: Path,
        popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        self.serial = serial
        self.output_dir = output_dir
        self.logcat_path = output_dir / "logcat.txt"
        self.store = CrashEventStore(output_dir)
        self.detector = OneConnectCrashDetector(self.store)
        self._popen_factory = popen_factory
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self.events: list[CrashEvent] = []

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        command = _adb_command(self.serial, ["logcat", "-v", "threadtime"])
        self._process = self._popen_factory(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 3.0) -> list[CrashEvent]:
        process = self._process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)
        if self._thread:
            self._thread.join(timeout=timeout)
        self._record_events(self.detector.finish())
        return list(self.events)

    def _read_loop(self) -> None:
        try:
            with self.logcat_path.open("w", encoding="utf-8", errors="replace") as log_file:
                stdout = self._process.stdout if self._process else None
                if not stdout:
                    return
                for line in stdout:
                    log_file.write(line)
                    self._record_events(self.detector.feed_line(line))
        except Exception:
            return

    def _record_events(self, events: Iterable[CrashEvent]) -> None:
        self.events.extend(events)


def clear_logcat(
    *,
    serial: str | None,
    run_factory: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess[str]:
    return run_factory(
        _adb_command(serial, ["logcat", "-c"]),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def start_crash_logcat_capture(
    *,
    serial: str | None,
    output_dir: Path,
    log_writer: LogWriter | None = None,
    run_factory: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> LogcatCapture | None:
    try:
        result = clear_logcat(serial=serial, run_factory=run_factory)
        if log_writer:
            log_writer(f"[CRASH_CAPTURE] logcat_clear returncode={result.returncode}")
        capture = LogcatCapture(serial=serial, output_dir=output_dir, popen_factory=popen_factory)
        capture.start()
        if log_writer:
            log_writer(f"[CRASH_CAPTURE] logcat_capture started path='{capture.logcat_path}'")
        return capture
    except Exception as exc:
        if log_writer:
            log_writer(f"[CRASH_CAPTURE][warning] logcat_capture_unavailable error='{exc}'")
        return None


def stop_crash_logcat_capture(capture: LogcatCapture | None, *, log_writer: LogWriter | None = None) -> list[CrashEvent]:
    if not capture:
        return []
    try:
        events = capture.stop()
        if log_writer:
            log_writer(f"[CRASH_CAPTURE] logcat_capture stopped events={len(events)}")
        return events
    except Exception as exc:
        if log_writer:
            log_writer(f"[CRASH_CAPTURE][warning] logcat_capture_stop_failed error='{exc}'")
        return []


def _adb_command(serial: str | None, args: list[str]) -> list[str]:
    command = ["adb"]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    return command


def _extract_exception(block: list[str]) -> str | None:
    for line in block:
        stripped = _strip_logcat_prefix(line).strip()
        if not stripped or stripped.startswith("FATAL EXCEPTION") or stripped.startswith("Process:"):
            continue
        if stripped.startswith(("at ", "Caused by:", "Suppressed:", "... ")):
            continue
        if "." in stripped or "Exception" in stripped or "Error" in stripped:
            return stripped
    return None


def _extract_top_frame(block: list[str]) -> str | None:
    for line in block:
        stripped = _strip_logcat_prefix(line).strip()
        if stripped.startswith("at "):
            return stripped[3:]
    return None


def _extract_timestamp(block: list[str]) -> str | None:
    for line in block:
        match = re.match(r"(?P<ts>\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})", line)
        if match:
            return match.group("ts")
    return None


def _strip_logcat_prefix(line: str) -> str:
    marker = f"{CRASH_BLOCK_SOURCE_TOKEN}:"
    if marker in line:
        return line.split(marker, 1)[1]
    if ": " in line:
        return line.split(": ", 1)[-1]
    return line
