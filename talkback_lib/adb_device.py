#!/usr/bin/env python3
"""ADB/디바이스 IO 실행 레이어."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from talkback_lib.constants import DEFAULT_TIMEOUT_SECONDS


class AdbCommandFailure(RuntimeError):
    """Delivery failure for commands that require an explicit transport verdict."""

    def __init__(self, reason: str, command: list[str], timeout: float, *, stdout: str = "", stderr: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.command = command
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class AdbBinaryCommandResult:
    stdout: bytes
    stderr: bytes
    stderr_truncated: bool
    returncode: int


class AdbBinaryCommandFailure(RuntimeError):
    """Bounded binary ADB transfer failure without text decoding."""

    def __init__(
        self,
        reason: str,
        command: list[str],
        timeout: float,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        stderr_truncated: bool = False,
        returncode: int | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.command = command
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr
        self.stderr_truncated = stderr_truncated
        self.returncode = returncode


class AdbDevice:
    def __init__(self, adb_path: str, resolve_serial) -> None:
        self.adb_path = adb_path
        self._resolve_serial = resolve_serial
        self.command_guard = None

    @staticmethod
    def _effective_timeout(args: list[str], timeout: float | None) -> float:
        if timeout is not None and timeout > 0:
            return float(timeout)
        lightweight_shell_cmds = {"settings", "getprop", "dumpsys"}
        if len(args) >= 3 and args[0] == "shell" and args[1] in lightweight_shell_cmds:
            return 5.0
        return DEFAULT_TIMEOUT_SECONDS

    def _run_adb_command(self, args: list[str], dev: Any = None, timeout: float | None = DEFAULT_TIMEOUT_SECONDS, *, raise_on_failure: bool = False) -> str:
        if self.command_guard is not None:
            self.command_guard(args)
        serial = self._resolve_serial(dev)
        cmd = [self.adb_path]
        if serial:
            cmd += ["-s", serial]
        cmd += args
        effective_timeout = self._effective_timeout(args, timeout)
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                text=True,
                capture_output=True,
                timeout=effective_timeout,
                encoding="utf-8",
                errors="ignore",
            )
        except KeyboardInterrupt:
            raise
        except subprocess.TimeoutExpired as exc:
            print(
                f"[ERROR][adb] timeout after {effective_timeout:.1f}s: {' '.join(cmd)}"
            )
            if raise_on_failure:
                def decode(value):
                    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
                raise AdbCommandFailure("adb_command_timeout", cmd, effective_timeout, stdout=decode(exc.stdout), stderr=decode(exc.stderr)) from exc
            return ""
        except FileNotFoundError as exc:
            print(f"[ERROR][adb] executable_not_found path='{self.adb_path}' error='{exc}'")
            if raise_on_failure:
                raise AdbCommandFailure("adb_executable_not_found", cmd, effective_timeout, stderr=str(exc)) from exc
            return ""
        except OSError as exc:
            print(f"[ERROR][adb] execution_failed cmd='{' '.join(cmd)}' error='{exc}'")
            if raise_on_failure:
                raise AdbCommandFailure("adb_execution_failed", cmd, effective_timeout, stderr=str(exc)) from exc
            return ""
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            print(f"[ERROR] 명령 실행 실패(returncode={proc.returncode}): {' '.join(cmd)}")
            if stderr:
                print(f"[ERROR] stderr: {stderr}")
            if raise_on_failure:
                raise AdbCommandFailure("adb_command_failed", cmd, effective_timeout, stdout=proc.stdout or "", stderr=stderr)
            return ""
        return proc.stdout.strip()

    def _run_adb_binary_command(
        self,
        args: list[str],
        dev: Any = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        *,
        max_stdout_bytes: int,
        max_stderr_bytes: int = 64 * 1024,
    ) -> AdbBinaryCommandResult:
        """Read bounded stdout bytes without newline or character conversion."""
        if self.command_guard is not None:
            self.command_guard(args)
        serial = self._resolve_serial(dev)
        command = [self.adb_path]
        if serial:
            command += ["-s", serial]
        command += args
        if max_stdout_bytes < 0 or max_stderr_bytes < 0 or timeout <= 0:
            raise ValueError("binary ADB limits must be non-negative and timeout positive")
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            raise AdbBinaryCommandFailure("adb_executable_not_found", command, timeout) from exc
        except OSError as exc:
            raise AdbBinaryCommandFailure("adb_execution_failed", command, timeout, stderr=str(exc).encode("utf-8", errors="replace")) from exc

        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()
        stderr_truncated = threading.Event()

        def drain_stdout() -> None:
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read(16 * 1024)
                if not chunk:
                    return
                remaining = max_stdout_bytes - len(stdout)
                if remaining > 0:
                    stdout.extend(chunk[:remaining])
                if len(chunk) > max(remaining, 0):
                    overflow.set()
                    try:
                        proc.kill()
                    except OSError:
                        pass

        def drain_stderr() -> None:
            assert proc.stderr is not None
            while True:
                chunk = proc.stderr.read(16 * 1024)
                if not chunk:
                    return
                remaining = max_stderr_bytes - len(stderr)
                if remaining > 0:
                    stderr.extend(chunk[:remaining])
                if len(chunk) > max(remaining, 0):
                    stderr_truncated.set()

        stdout_thread = threading.Thread(target=drain_stdout, name="adb-binary-stdout", daemon=True)
        stderr_thread = threading.Thread(target=drain_stderr, name="adb-binary-stderr", daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
        finally:
            stdout_thread.join(timeout=2.0)
            stderr_thread.join(timeout=2.0)
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
        if timed_out:
            raise AdbBinaryCommandFailure(
                "adb_command_timeout", command, timeout, stdout=bytes(stdout), stderr=bytes(stderr),
                stderr_truncated=stderr_truncated.is_set(), returncode=proc.returncode,
            )
        if overflow.is_set():
            raise AdbBinaryCommandFailure(
                "stdout_limit_exceeded", command, timeout, stdout=bytes(stdout), stderr=bytes(stderr),
                stderr_truncated=stderr_truncated.is_set(), returncode=proc.returncode,
            )
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            raise AdbBinaryCommandFailure(
                "pipe_drain_incomplete", command, timeout, stdout=bytes(stdout), stderr=bytes(stderr),
                stderr_truncated=stderr_truncated.is_set(), returncode=proc.returncode,
            )
        if proc.returncode != 0:
            raise AdbBinaryCommandFailure(
                "adb_command_failed", command, timeout, stdout=bytes(stdout), stderr=bytes(stderr),
                stderr_truncated=stderr_truncated.is_set(), returncode=proc.returncode,
            )
        return AdbBinaryCommandResult(
            stdout=bytes(stdout), stderr=bytes(stderr), stderr_truncated=stderr_truncated.is_set(),
            returncode=proc.returncode,
        )

    def _clear_logcat_best_effort(self, dev: Any = None, timeout: float = 1.5) -> str:
        serial = self._resolve_serial(dev)
        cmd = [self.adb_path]
        if serial:
            cmd += ["-s", serial]
        cmd += ["logcat", "-c"]
        safe_timeout = max(0.2, float(timeout))
        try:
            with subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
            ) as proc:
                try:
                    stdout, stderr = proc.communicate(timeout=safe_timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    print(
                        f"[WARN][adb] best_effort logcat -c timeout after {safe_timeout:.1f}s: {' '.join(cmd)}"
                    )
                    return ""
        except KeyboardInterrupt:
            print("[WARN][adb] best_effort logcat -c interrupted, skipping...")
            return ""
        except FileNotFoundError as exc:
            print(f"[WARN][adb] best_effort logcat -c executable_not_found path='{self.adb_path}' error='{exc}'")
            return ""
        except OSError as exc:
            print(f"[WARN][adb] best_effort logcat -c execution_failed cmd='{' '.join(cmd)}' error='{exc}'")
            return ""

        if proc.returncode != 0:
            print(
                f"[WARN][adb] best_effort logcat -c failed returncode={proc.returncode} stderr='{(stderr or '').strip()}'"
            )
            return ""
        return (stdout or "").strip()

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
        if self.command_guard is not None:
            self.command_guard(["shell", "input", "tap", str(int(x)), str(int(y))])
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

