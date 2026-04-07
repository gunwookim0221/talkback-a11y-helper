#!/usr/bin/env python3
"""ADB/디바이스 IO 실행 레이어."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from talkback_lib.constants import DEFAULT_TIMEOUT_SECONDS


class AdbDevice:
    def __init__(self, adb_path: str, resolve_serial) -> None:
        self.adb_path = adb_path
        self._resolve_serial = resolve_serial

    def _run_adb_command(self, args: list[str], dev: Any = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
        serial = self._resolve_serial(dev)
        cmd = [self.adb_path]
        if serial:
            cmd += ["-s", serial]
        cmd += args
        proc = subprocess.run(
            cmd,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",
            errors="ignore",
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            print(f"[ERROR] 명령 실행 실패(returncode={proc.returncode}): {' '.join(cmd)}")
            if stderr:
                print(f"[ERROR] stderr: {stderr}")
            return ""
        return proc.stdout.strip()

    def _shell(self, dev: Any, shell_args: list[str], timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
        return self._run_adb_command(["shell", *shell_args], dev=dev, timeout=timeout)

    def _broadcast(self, dev: Any, package_name: str, action: str, extras: list[str] | None = None) -> str:
        cmd = ["shell", "am", "broadcast", "-a", action, "-p", package_name]
        if extras:
            cmd.extend(extras)
        return self._run_adb_command(cmd, dev=dev)

    def _pull(self, dev: Any, remote_path: str, local_path: str) -> str:
        return self._run_adb_command(["pull", remote_path, local_path], dev=dev)

    def _push(self, dev: Any, local_path: str, remote_path: str) -> str:
        return self._run_adb_command(["push", local_path, remote_path], dev=dev)

    def _tap(self, dev: Any, x: int, y: int, timeout: float = 10.0) -> bool:
        serial = self._resolve_serial(dev)
        cmd = [self.adb_path]
        if serial:
            cmd += ["-s", serial]
        cmd += ["shell", "input", "tap", str(int(x)), str(int(y))]
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                text=True,
                capture_output=True,
                timeout=timeout,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception as exc:
            print(f"[WARN][adb_tap] failed reason='exception' serial='{serial or 'default'}' error='{exc}'")
            return False
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            print(
                f"[WARN][adb_tap] failed reason='nonzero_return' serial='{serial or 'default'}' "
                f"returncode={proc.returncode} stderr='{stderr}'"
            )
            return False
        return True

    def _swipe(self, dev: Any, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        return self._shell(
            dev,
            ["input", "swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms))],
        )

    def _input_text(self, dev: Any, text: str) -> str:
        return self._shell(dev, ["input", "text", text])

    def _keyevent(self, dev: Any, keycode: str | int) -> str:
        return self._shell(dev, ["input", "keyevent", str(keycode)], timeout=5.0)

    def _capture_screen(self, dev: Any, save_path: str, remote_path: str = "/sdcard/temp.png") -> None:
        save_file = Path(save_path)
        save_file.parent.mkdir(parents=True, exist_ok=True)
        self._shell(dev, ["screencap", "-p", remote_path])
        self._pull(dev, remote_path, str(save_file))

    def _dump_ui(self, dev: Any, remote_path: str = "/sdcard/window_dump.xml") -> str:
        return self._shell(dev, ["uiautomator", "dump", remote_path])
