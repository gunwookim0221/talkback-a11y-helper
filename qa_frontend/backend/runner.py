from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

from .paths import ROOT_DIR, RUN_LOG_DIR, SCRIPT_PATH

RunState = Literal["idle", "running", "stopped", "finished", "error"]


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._state: RunState = "idle"
        self._run_id: str | None = None
        self._mode: str | None = None
        self._log_path: Path | None = None
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._returncode: int | None = None
        self._error: str | None = None
        self._scenario_ids: list[str] = []

    def start_run(self, mode: str, scenario_ids: list[str] | None = None) -> dict[str, object]:
        with self._lock:
            self._refresh_locked()
            if self._process and self._process.poll() is None:
                raise RuntimeError("a run is already in progress")

            RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = RUN_LOG_DIR / f"{run_id}_{mode}.log"
            command = [sys.executable, str(SCRIPT_PATH)]

            try:
                log_file = log_path.open("w", encoding="utf-8", errors="replace")
                log_file.write(
                    f"[QA_FRONTEND] start mode='{mode}' "
                    f"scenario_selection_applied=false scenario_ids={scenario_ids or []}\n"
                )
                log_file.flush()
                process = subprocess.Popen(
                    command,
                    cwd=ROOT_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except Exception as exc:
                self._state = "error"
                self._error = str(exc)
                self._process = None
                raise

            self._process = process
            self._state = "running"
            self._run_id = run_id
            self._mode = mode
            self._log_path = log_path
            self._started_at = datetime.now().isoformat(timespec="seconds")
            self._finished_at = None
            self._returncode = None
            self._error = None
            self._scenario_ids = list(scenario_ids or [])

            threading.Thread(target=self._tee_output, args=(process, log_file), daemon=True).start()
            threading.Thread(target=self._wait_for_process, args=(process,), daemon=True).start()

            return self._status_locked()

    def stop_run(self) -> dict[str, object]:
        with self._lock:
            self._refresh_locked()
            process = self._process
            if not process or process.poll() is not None:
                return self._status_locked()
            self._state = "stopped"

        process.terminate()
        try:
            process.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
        return self.get_status()

    def get_status(self) -> dict[str, object]:
        with self._lock:
            self._refresh_locked()
            return self._status_locked()

    def get_log_tail(self, max_lines: int = 300) -> dict[str, object]:
        path = self._log_path
        if not path or not path.exists():
            return {"lines": [], "text": "", "log_path": str(path) if path else None}

        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max_lines:]
        return {"lines": tail, "text": "\n".join(tail), "log_path": str(path)}

    def _tee_output(self, process: subprocess.Popen[str], log_file) -> None:
        try:
            if process.stdout:
                for line in process.stdout:
                    log_file.write(line)
                    log_file.flush()
        finally:
            log_file.close()

    def _wait_for_process(self, process: subprocess.Popen[str]) -> None:
        returncode = process.wait()
        with self._lock:
            if process is not self._process:
                return
            self._returncode = returncode
            self._finished_at = datetime.now().isoformat(timespec="seconds")
            if self._state == "stopped":
                return
            self._state = "finished" if returncode == 0 else "error"
            if returncode != 0:
                self._error = f"script_test.py exited with code {returncode}"

    def _refresh_locked(self) -> None:
        process = self._process
        if not process or self._state != "running":
            return
        returncode = process.poll()
        if returncode is None:
            return
        self._returncode = returncode
        self._finished_at = self._finished_at or datetime.now().isoformat(timespec="seconds")
        self._state = "finished" if returncode == 0 else "error"
        if returncode != 0:
            self._error = f"script_test.py exited with code {returncode}"

    def _status_locked(self) -> dict[str, object]:
        return {
            "state": self._state,
            "run_id": self._run_id,
            "mode": self._mode,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "returncode": self._returncode,
            "error": self._error,
            "log_path": str(self._log_path) if self._log_path else None,
            "scenario_ids": self._scenario_ids,
            "scenario_selection_applied": False,
        }
