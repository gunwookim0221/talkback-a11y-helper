from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from typing import Any

from .adb import run_adb


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


def enable_device_stay_awake(
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
) -> dict[str, object]:
    """Enable Android stay-awake and retain enough state for a safe restore."""
    before = adb_runner(["shell", "settings", "get", "global", "stay_on_while_plugged_in"], 8.0)
    original_setting = _setting_value(before)
    applied = adb_runner(["shell", "svc", "power", "stayon", "true"], 8.0)
    after = adb_runner(["shell", "settings", "get", "global", "stay_on_while_plugged_in"], 8.0)
    applied_setting = _setting_value(after)
    return {
        "ok": bool(applied.get("ok")),
        "original_setting_known": bool(before.get("ok")),
        "original_setting": original_setting,
        "applied_setting": applied_setting,
        "command": "adb shell svc power stayon true",
        "error": str(applied.get("error") or applied.get("stderr") or ""),
    }


def restore_device_stay_awake(
    state: dict[str, Any] | None,
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
) -> dict[str, object]:
    """Restore only the setting this run changed, preserving external changes."""
    if not state or not state.get("ok"):
        return {"ok": False, "restored": False, "reason": "stay_awake_not_applied"}
    if not state.get("original_setting_known"):
        return {"ok": False, "restored": False, "reason": "original_setting_unknown"}

    current_result = adb_runner(
        ["shell", "settings", "get", "global", "stay_on_while_plugged_in"],
        8.0,
    )
    current_setting = _setting_value(current_result)
    applied_setting = state.get("applied_setting")
    if not current_result.get("ok"):
        return {"ok": False, "restored": False, "reason": "current_setting_unavailable"}
    if applied_setting is not None and current_setting != applied_setting:
        return {"ok": True, "restored": False, "reason": "setting_changed_externally"}

    original_setting = state.get("original_setting")
    if original_setting is None:
        command = ["shell", "settings", "delete", "global", "stay_on_while_plugged_in"]
    else:
        command = [
            "shell",
            "settings",
            "put",
            "global",
            "stay_on_while_plugged_in",
            str(original_setting),
        ]
    restored = adb_runner(command, 8.0)
    return {
        "ok": bool(restored.get("ok")),
        "restored": bool(restored.get("ok")),
        "reason": "restored" if restored.get("ok") else "restore_failed",
        "original_setting": original_setting,
        "error": str(restored.get("error") or restored.get("stderr") or ""),
    }


def _setting_value(result: dict[str, object]) -> str | None:
    if not result.get("ok"):
        return None
    value = str(result.get("stdout", "") or "").strip()
    if not value or value.lower() == "null":
        return None
    return value


def _is_windows() -> bool:
    return sys.platform == "win32"


def _set_thread_execution_state(flags: int) -> int:
    return int(ctypes.windll.kernel32.SetThreadExecutionState(flags))
