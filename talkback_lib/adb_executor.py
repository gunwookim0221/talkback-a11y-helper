from __future__ import annotations

from typing import Any

from talkback_lib.adb_device import AdbDevice


class AdbExecutor:
    """ADB 명령 실행을 담당하는 얇은 래퍼."""

    def __init__(self, adb_device: AdbDevice) -> None:
        self._adb_device = adb_device

    def run(self, args: list[str], dev: Any = None, timeout: float = 15.0) -> str:
        return self._adb_device._run_adb_command(args, dev=dev, timeout=timeout)
