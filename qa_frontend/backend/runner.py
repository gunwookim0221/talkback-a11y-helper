from __future__ import annotations

import subprocess
import sys
import threading
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from tb_runner.runtime_config import RUNTIME_CONFIG_PATH_ENV

from .paths import ROOT_DIR, RUN_LOG_DIR, SCRIPT_PATH, RUNTIME_CONFIG_PATH
from .preflight import format_preflight_log_lines, normalize_launch_mode, run_runtime_preflight
from .run_summary import write_summary_file
from .runtime_dashboard import build_runtime_dashboard
from .runtime_config_selection import write_selected_runtime_config

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
        self._launch_mode: str = "clean"
        self._preflight: dict[str, object] | None = None
        self._scenario_selection_applied = False
        self._runtime_config_path: str | None = None
        self._max_steps_policy: str | None = None
        self._scenario_steps: list[dict[str, object]] = []

    def start_run(
        self,
        mode: str,
        scenario_ids: list[str] | None = None,
        launch_mode: str = "clean",
    ) -> dict[str, object]:
        with self._lock:
            self._refresh_locked()
            if self._process and self._process.poll() is None:
                raise RuntimeError("a run is already in progress")

            RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = RUN_LOG_DIR / run_id
            log_path = RUN_LOG_DIR / f"{run_id}_{mode}.log"
            command = [sys.executable, str(SCRIPT_PATH)]
            normalized_launch_mode = normalize_launch_mode(launch_mode)

            try:
                log_file = log_path.open("w", encoding="utf-8", errors="replace")
                self._run_id = run_id
                self._mode = mode
                self._log_path = log_path
                self._started_at = datetime.now().isoformat(timespec="seconds")
                self._finished_at = None
                self._returncode = None
                self._scenario_ids = list(scenario_ids or [])
                self._launch_mode = normalized_launch_mode
                self._scenario_selection_applied = False
                self._runtime_config_path = None
                self._max_steps_policy = None
                self._scenario_steps = []
                self._preflight = None

                if not scenario_ids:
                    self._state = "error"
                    self._error = "No scenario selected"
                    self._finished_at = datetime.now().isoformat(timespec="seconds")
                    log_file.write(
                        f"[QA_FRONTEND] start mode='{mode}' scenario_selection_applied=false "
                        f"scenario_ids=[] launch_mode='{normalized_launch_mode}'\n"
                    )
                    log_file.write("[QA_FRONTEND][scenario_selection] result='blocked' reason='no_scenario_selected'\n")
                    log_file.close()
                    self._write_summary_safe()
                    return self._status_locked()

                runtime_config = write_selected_runtime_config(
                    source_path=RUNTIME_CONFIG_PATH,
                    output_path=run_dir / "runtime_config.json",
                    scenario_ids=list(scenario_ids),
                    mode=mode,
                )
                self._scenario_selection_applied = True
                self._runtime_config_path = str(runtime_config["path"])
                self._max_steps_policy = str(runtime_config["max_steps_policy"])
                self._scenario_steps = list(runtime_config["scenario_steps"])

                log_file.write(
                    f"[QA_FRONTEND] start mode='{mode}' "
                    f"scenario_selection_applied=true scenario_ids={scenario_ids or []} "
                    f"runtime_config_path='{self._runtime_config_path}' "
                    f"launch_mode='{normalized_launch_mode}'\n"
                )
                log_file.write(
                    "[QA_FRONTEND][scenario_selection] "
                    f"scenario_selection_applied=true runtime_config_path='{self._runtime_config_path}' "
                    f"enabled_ids={runtime_config['enabled_ids']}\n"
                )
                log_file.write(
                    "[QA_FRONTEND][runtime_config] "
                    f"mode='{mode}' "
                    "scenario_selection_applied=true "
                    f"runtime_config_path='{self._runtime_config_path}' "
                    f"enabled_ids={runtime_config['enabled_ids']} "
                    f"max_steps_policy='{self._max_steps_policy}'\n"
                )
                for scenario_step in self._scenario_steps:
                    if not scenario_step.get("selected"):
                        continue
                    log_file.write(
                        "[QA_FRONTEND][runtime_config] "
                        f"scenario='{scenario_step['scenario']}' "
                        f"original_max_steps={scenario_step['original_max_steps']!r} "
                        f"effective_max_steps={scenario_step['effective_max_steps']!r} "
                        f"policy='{scenario_step['policy']}'\n"
                    )
                preflight = run_runtime_preflight(normalized_launch_mode)
                for line in format_preflight_log_lines(preflight):
                    log_file.write(f"{line}\n")
                log_file.flush()
                self._preflight = preflight

                if not preflight.get("ok"):
                    self._state = "error"
                    self._error = str(preflight.get("user_message") or f"runtime preflight blocked: {preflight.get('reason')}")
                    self._process = None
                    self._finished_at = datetime.now().isoformat(timespec="seconds")
                    log_file.close()
                    self._write_summary_safe()
                    return self._status_locked()

                env = os.environ.copy()
                env[RUNTIME_CONFIG_PATH_ENV] = self._runtime_config_path
                process = subprocess.Popen(
                    command,
                    cwd=ROOT_DIR,
                    env=env,
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
            self._error = None

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
            self._append_log_line("[QA_FRONTEND][run] stop_requested=true")

        process.terminate()
        try:
            process.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
        return self.get_status()

    def get_log_path(self) -> Path | None:
        return self._log_path if self._log_path and self._log_path.exists() else None

    def get_status(self) -> dict[str, object]:
        with self._lock:
            self._refresh_locked()
            return self._status_locked()

    def get_dashboard(self) -> dict[str, object]:
        with self._lock:
            self._refresh_locked()
            status = self._status_locked()
            log_path = self._log_path
            scenario_ids = list(self._scenario_ids)
        return build_runtime_dashboard(status=status, log_path=log_path, scenario_ids=scenario_ids)

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
                self._append_log_line("[QA_FRONTEND][run] final_state='stopped' returncode=0")
                self._write_summary_safe()
                return
            self._state = "finished" if returncode == 0 else "error"
            if returncode != 0:
                self._error = f"script_test.py exited with code {returncode}"
            self._append_log_line(
                f"[QA_FRONTEND][run] final_state='{self._state}' returncode={returncode}"
            )
            self._write_summary_safe()

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

    def _append_log_line(self, line: str) -> None:
        if not self._log_path:
            return
        try:
            with self._log_path.open("a", encoding="utf-8", errors="replace") as log_file:
                log_file.write(f"{line}\n")
        except OSError:
            return

    def _write_summary_safe(self) -> None:
        if not self._log_path:
            return
        try:
            write_summary_file(
                status=self._status_locked(),
                log_path=self._log_path,
                scenario_ids=list(self._scenario_ids),
            )
        except Exception as exc:
            self._append_log_line(f"[QA_FRONTEND][summary] write_failed error='{exc}'")

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
            "scenario_selection_applied": self._scenario_selection_applied,
            "runtime_config_path": self._runtime_config_path,
            "max_steps_policy": self._max_steps_policy,
            "scenario_steps": self._scenario_steps,
            "launch_mode": self._launch_mode,
            "preflight_state": self._preflight.get("state") if self._preflight else None,
            "preflight_reason": self._preflight.get("reason") if self._preflight else None,
            "talkback_state": self._preflight.get("talkback_state") if self._preflight else None,
            "helper_state": self._preflight.get("helper_state") if self._preflight else None,
            "foreground_package": self._preflight.get("foreground_package") if self._preflight else None,
            "popup_preflight_state": self._preflight.get("popup_result") if self._preflight else None,
            "popup_detected": self._preflight.get("popup_detected") if self._preflight else False,
            "popup_package": self._preflight.get("popup_package") if self._preflight else None,
            "popup_dismissed": self._preflight.get("popup_dismissed") if self._preflight else False,
            "popup_result": self._preflight.get("popup_result") if self._preflight else None,
            "accessibility_settings_opened": self._preflight.get("accessibility_settings_opened") if self._preflight else False,
            "preflight": self._preflight,
        }
