from __future__ import annotations

import ctypes
import sys
import threading


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_RUN_FLAGS = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
_RESTORE_FLAGS = ES_CONTINUOUS


class _SleepPreventionWorker:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._started_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="qa-sleep-prevention", daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._started_event.wait(timeout=1.0)

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            _set_thread_execution_state(_RUN_FLAGS)
        finally:
            self._started_event.set()
        self._stop_event.wait()
        _set_thread_execution_state(_RESTORE_FLAGS)


_lock = threading.Lock()
_request_count = 0
_worker: _SleepPreventionWorker | None = None


def enable_sleep_prevention() -> bool:
    """Keep Windows display and system sleep disabled until disabled again."""
    if not _is_windows():
        return False

    global _request_count, _worker
    with _lock:
        _request_count += 1
        if _worker is not None:
            return True
        worker = _SleepPreventionWorker()
        _worker = worker

    worker.start()
    return True


def disable_sleep_prevention() -> bool:
    """Restore the default Windows execution state when no run still needs it."""
    if not _is_windows():
        return False

    global _request_count, _worker
    worker: _SleepPreventionWorker | None = None
    with _lock:
        if _request_count <= 0:
            return False
        _request_count -= 1
        if _request_count == 0:
            worker = _worker
            _worker = None

    if worker is not None:
        worker.stop()
    return True


def _is_windows() -> bool:
    return sys.platform == "win32"


def _set_thread_execution_state(flags: int) -> int:
    return int(ctypes.windll.kernel32.SetThreadExecutionState(flags))
