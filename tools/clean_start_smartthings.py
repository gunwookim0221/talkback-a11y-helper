"""Clean-launch SmartThings before runtime smoke runs.

This is intentionally a small wrapper around adb commands. It does not change
runner traversal behavior; it only removes known foreground contamination before
the Python runner starts.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass


SMARTTHINGS_PACKAGE = "com.samsung.android.oneconnect"
SMARTTHINGS_ACTIVITY = "com.samsung.android.oneconnect/.ui.SCMainActivity"
PLAY_STORE_PACKAGE = "com.android.vending"


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def _adb_command(serial: str | None, *args: str) -> list[str]:
    command = ["adb"]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    return command


def run_adb(serial: str | None, *args: str, timeout: float = 15.0) -> CommandResult:
    command = tuple(_adb_command(serial, *args))
    completed = subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def current_focus(serial: str | None = None) -> str:
    result = run_adb(serial, "shell", "dumpsys", "window", timeout=20.0)
    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if "mCurrentFocus" in line or "mFocusedApp" in line or "topResumedActivity" in line
    ]
    return "\n".join(lines)


def is_smartthings_foreground(focus_text: str) -> bool:
    return SMARTTHINGS_PACKAGE in focus_text and PLAY_STORE_PACKAGE not in focus_text


def clean_start_smartthings(
    *,
    serial: str | None = None,
    wait_seconds: float = 8.0,
    max_attempts: int = 2,
) -> tuple[bool, list[CommandResult], str]:
    results: list[CommandResult] = []
    focus = ""
    attempts = max(1, int(max_attempts))
    for attempt in range(attempts):
        results.append(run_adb(serial, "shell", "input", "keyevent", "KEYCODE_HOME"))
        time.sleep(1.0)
        results.append(run_adb(serial, "shell", "am", "force-stop", PLAY_STORE_PACKAGE))
        results.append(run_adb(serial, "shell", "am", "force-stop", SMARTTHINGS_PACKAGE))
        time.sleep(1.0)
        results.append(run_adb(serial, "shell", "am", "start", "-n", SMARTTHINGS_ACTIVITY))
        time.sleep(max(0.0, wait_seconds))
        focus = current_focus(serial)
        if is_smartthings_foreground(focus):
            return True, results, focus
        if PLAY_STORE_PACKAGE in focus:
            results.append(run_adb(serial, "shell", "am", "force-stop", PLAY_STORE_PACKAGE))
            time.sleep(1.0)
            results.append(run_adb(serial, "shell", "am", "start", "-n", SMARTTHINGS_ACTIVITY))
            time.sleep(max(0.0, wait_seconds))
            focus = current_focus(serial)
            if is_smartthings_foreground(focus):
                return True, results, focus
    return False, results, focus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean-start SmartThings before a runtime smoke run.")
    parser.add_argument("--serial", help="Optional adb serial.")
    parser.add_argument("--wait", type=float, default=8.0, help="Seconds to wait after launching SmartThings.")
    parser.add_argument("--attempts", type=int, default=2, help="Maximum clean-launch attempts.")
    args = parser.parse_args(argv)

    ok, results, focus = clean_start_smartthings(
        serial=args.serial,
        wait_seconds=args.wait,
        max_attempts=args.attempts,
    )
    for result in results:
        print(f"$ {' '.join(result.command)}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    print("--- focus ---")
    print(focus)
    print(f"smartthings_foreground={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
