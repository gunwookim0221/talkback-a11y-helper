from __future__ import annotations

import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

from tb_runner.run_spec import RunSpec

from .paths import ROOT_DIR, RUN_LOG_DIR, SCRIPT_PATH, RUNTIME_CONFIG_PATH, OUTPUT_DIR
from .device_locale import apply_language_mode, format_language_log_lines, normalize_language_mode
from .preflight import (
    format_preflight_log_lines,
    normalize_launch_mode,
    run_surface_preflight as run_runtime_preflight,
)
from .run_summary import write_summary_file
from .runtime_dashboard import build_runtime_dashboard
from .runtime_config_selection import write_selected_runtime_config
from .runtime_setup import prepare_runtime
from .sleep_prevention import disable_sleep_prevention, enable_sleep_prevention
from .subprocess_executor import RunExecution, close_execution_log, start_execution, wait_for_execution

RunState = Literal["idle", "running", "stopped", "finished", "error"]


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._execution: RunExecution | None = None
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
        self._language_mode: str = "current"
        self._language_status: dict[str, object] | None = None
        self._preflight: dict[str, object] | None = None
        self._scenario_selection_applied = False
        self._runtime_config_path: str | None = None
        self._max_steps_policy: str | None = None
        self._scenario_steps: list[dict[str, object]] = []
        self._dashboard_cache_key: tuple[str, int, float, str | None] | None = None
        self._dashboard_parsed_cache: dict[str, object] | None = None
        self._last_outputs_signature: str | None = None

    def start_run(
        self,
        mode: str,
        scenario_ids: list[str] | None = None,
        launch_mode: str = "clean",
        language_mode: str = "current",
        max_steps_overrides: dict[str, int] | None = None,
    ) -> dict[str, object]:
        with self._lock:
            self._refresh_locked()
            if self._process and self._process.poll() is None:
                raise RuntimeError("a run is already in progress")

            RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = RUN_LOG_DIR / run_id
            log_path = RUN_LOG_DIR / f"{run_id}_{mode}.log"
            normalized_launch_mode = normalize_launch_mode(launch_mode)
            normalized_language_mode = normalize_language_mode(language_mode)
            sleep_prevention_enabled = False

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
                self._language_mode = normalized_language_mode
                self._language_status = None
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
                        f"scenario_ids=[] launch_mode='{normalized_launch_mode}' "
                        f"language_mode='{normalized_language_mode}'\n"
                    )
                    log_file.write("[QA_FRONTEND][scenario_selection] result='blocked' reason='no_scenario_selected'\n")
                    log_file.close()
                    self._write_summary_safe()
                    return self._status_locked()

                enable_sleep_prevention()
                sleep_prevention_enabled = True

                runtime_config = write_selected_runtime_config(
                    source_path=RUNTIME_CONFIG_PATH,
                    output_path=run_dir / "runtime_config.json",
                    scenario_ids=list(scenario_ids),
                    mode=mode,
                    max_steps_overrides=max_steps_overrides,
                )
                self._scenario_selection_applied = True
                self._runtime_config_path = str(runtime_config["path"])
                self._max_steps_policy = str(runtime_config["max_steps_policy"])
                self._scenario_steps = list(runtime_config["scenario_steps"])

                log_file.write(
                    f"[QA_FRONTEND] start mode='{mode}' "
                    f"scenario_selection_applied=true scenario_ids={scenario_ids or []} "
                    f"runtime_config_path='{self._runtime_config_path}' "
                    f"launch_mode='{normalized_launch_mode}' "
                    f"language_mode='{normalized_language_mode}'\n"
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
                spec = RunSpec(
                    mode=mode,
                    language_mode=normalized_language_mode,
                    launch_mode=normalized_launch_mode,
                    scenario_ids=tuple(scenario_ids),
                    runtime_config_path=self._runtime_config_path,
                )
                language_status, preflight = prepare_runtime(
                    spec,
                    language_fn=apply_language_mode,
                    preflight_fn=run_runtime_preflight,
                )
                self._language_status = language_status
                for line in format_language_log_lines(language_status):
                    log_file.write(f"{line}\n")
                if not language_status.get("ok"):
                    self._state = "error"
                    self._error = str(language_status.get("error") or f"language setup failed: {normalized_language_mode}")
                    self._process = None
                    self._finished_at = datetime.now().isoformat(timespec="seconds")
                    log_file.close()
                    self._write_summary_safe()
                    disable_sleep_prevention()
                    sleep_prevention_enabled = False
                    return self._status_locked()

                assert preflight is not None
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
                    disable_sleep_prevention()
                    sleep_prevention_enabled = False
                    return self._status_locked()

                execution = start_execution(
                    spec=spec,
                    script_path=SCRIPT_PATH,
                    cwd=ROOT_DIR,
                    log_file=log_file,
                    log_path=log_path,
                    popen_factory=subprocess.Popen,
                )
            except Exception as exc:
                self._state = "error"
                self._error = str(exc)
                self._process = None
                if sleep_prevention_enabled:
                    disable_sleep_prevention()
                raise

            self._execution = execution
            self._process = execution.process
            self._state = "running"
            self._error = None

            try:
                waiter = threading.Thread(target=self._wait_for_process, args=(execution,), daemon=True)
                waiter.start()
            except Exception:
                close_execution_log(execution)
                disable_sleep_prevention()
                self._state = "error"
                self._error = "failed to start run waiter thread"
                self._process = None
                self._execution = None
                self._finished_at = datetime.now().isoformat(timespec="seconds")
                raise

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
            run_id = self._run_id
            
        parsed_log = None
        if log_path and log_path.exists():
            try:
                stat = log_path.stat()
                size = stat.st_size
                mtime = stat.st_mtime
                current_key = (str(log_path), size, mtime, run_id)
                if self._dashboard_cache_key == current_key and self._dashboard_parsed_cache is not None:
                    parsed_log = self._dashboard_parsed_cache
                else:
                    from .runtime_dashboard import extract_validation_scenario_evidence_from_log, parse_runtime_log
                    log_text = log_path.read_text(encoding="utf-8", errors="replace")
                    validation_failed_scenarios, validation_warning_scenarios = extract_validation_scenario_evidence_from_log(log_text)
                    parsed_log = parse_runtime_log(
                        log_text,
                        scenario_ids=scenario_ids,
                        validation_failed_scenarios=validation_failed_scenarios,
                        validation_warning_scenarios=validation_warning_scenarios,
                    )
                    parsed_log["log_size"] = size
                    self._dashboard_cache_key = current_key
                    self._dashboard_parsed_cache = parsed_log
            except Exception:
                pass
                
        return build_runtime_dashboard(status=status, log_path=log_path, scenario_ids=scenario_ids, parsed_log=parsed_log)

    def _get_outputs_signature(self) -> str:
        if not OUTPUT_DIR.exists():
            return "none"
        try:
            stat = OUTPUT_DIR.stat()
            count = sum(1 for p in OUTPUT_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".xlsx", ".json", ".log"})
            return f"{stat.st_mtime}_{count}"
        except OSError:
            return "error"

    def get_snapshot(self) -> dict[str, object]:
        status = self.get_status()
        dashboard = self.get_dashboard()
        log_tail = self.get_log_tail()
        
        current_sig = self._get_outputs_signature()
        outputs_changed = (current_sig != self._last_outputs_signature)
        if outputs_changed:
            self._last_outputs_signature = current_sig

        return {
            "status": status,
            "dashboard": dashboard,
            "log_tail": log_tail,
            "run_id": status.get("run_id"),
            "state": status.get("state"),
            "log_path": status.get("log_path"),
            "outputs_changed": outputs_changed,
        }

    def get_log_tail(self, max_lines: int = 300) -> dict[str, object]:
        path = self._log_path
        if not path or not path.exists():
            return {"lines": [], "text": "", "log_path": str(path) if path else None}

        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max_lines:]
        return {"lines": tail, "text": "\n".join(tail), "log_path": str(path)}

    def _wait_for_process(self, execution: RunExecution) -> None:
        process = execution.process
        try:
            returncode = wait_for_execution(execution)
            with self._lock:
                if process is not self._process:
                    close_execution_log(execution)
                    return
                self._returncode = returncode
                self._finished_at = datetime.now().isoformat(timespec="seconds")
                if self._state == "stopped":
                    self._append_log_line("[QA_FRONTEND][run] final_state='stopped' returncode=0")
                    close_execution_log(execution)
                    self._write_summary_safe()
                    return
                self._state = "finished" if returncode == 0 else "error"
                if returncode != 0:
                    self._error = f"script_test.py exited with code {returncode}"
                self._append_log_line(
                    f"[QA_FRONTEND][run] final_state='{self._state}' returncode={returncode}"
                )
                close_execution_log(execution)
                self._write_summary_safe()
        finally:
            disable_sleep_prevention()

    def _refresh_locked(self) -> None:
        process = self._process
        if not process or self._state != "running":
            return
        # The waiter owns terminal state so status cannot race ahead of tee flush and summary.
        process.poll()

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
        language_status = self._language_status or {}
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
            "language_mode": self._language_mode,
            "device_locale": language_status.get("device_locale") if language_status else None,
            "target_locale": language_status.get("target_locale") if language_status else None,
            "manual_language_change_required": bool(language_status.get("manual_language_change_required")),
            "language_error": language_status.get("error") if language_status else None,
            "language_settings_intent": language_status.get("settings_intent") if language_status else None,
            "language_status": self._language_status,
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
