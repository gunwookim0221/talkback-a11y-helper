import threading
import subprocess
import sys
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import ROOT_DIR, RUN_LOG_DIR, SCRIPT_PATH, RUNTIME_CONFIG_PATH
from tb_runner.runtime_config import RUNTIME_CONFIG_PATH_ENV
from .runtime_config_selection import write_selected_runtime_config
from .device_locale import apply_language_mode, normalize_language_mode, format_language_log_lines
from .preflight import run_runtime_preflight, normalize_launch_mode, format_preflight_log_lines

class BatchRunManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._batch_id = None
        self._state = "idle"  # idle, running, finished, error
        self._mode = None
        self._created_at = None
        self._devices = []
        self._current_device_idx = -1
        self._worker_thread = None

    def _sanitize_name(self, name: str) -> str:
        return re.sub(r'[^0-9a-zA-Z_-]+', '_', name)

    def start_batch(self, devices: list[dict], mode: str, launch_mode: str = "clean", language_mode: str = "current", scenario_ids: list[str] | None = None) -> dict:
        with self._lock:
            if self._state == "running":
                raise RuntimeError("Batch run is already in progress")

            self._batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self._state = "running"
            self._mode = mode
            self._launch_mode = normalize_launch_mode(launch_mode)
            self._language_mode = normalize_language_mode(language_mode)
            self._scenario_ids = scenario_ids or []
            self._created_at = datetime.now(timezone.utc).isoformat()
            
            batch_dir = RUN_LOG_DIR / self._batch_id
            batch_dir.mkdir(parents=True, exist_ok=True)
            
            self._devices = []
            for d in devices:
                safe_model = self._sanitize_name(d.get("model", "unknown"))
                safe_serial = self._sanitize_name(d.get("serial", "unknown"))
                dev_dir = batch_dir / f"device_{safe_model}_{safe_serial}"
                
                self._devices.append({
                    "serial": d.get("serial"),
                    "model": d.get("model"),
                    "state": "pending",
                    "output_dir": str(dev_dir.relative_to(ROOT_DIR)) if dev_dir.is_relative_to(ROOT_DIR) else str(dev_dir),
                    "return_code": None,
                    "started_at": None,
                    "finished_at": None
                })
            
            self._current_device_idx = 0
            self._write_summary_locked()
            
            self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
            self._worker_thread.start()
            
            return self.get_status_locked()

    def get_status(self) -> dict:
        with self._lock:
            return self.get_status_locked()
            
    def get_status_locked(self) -> dict:
        current_serial = None
        if 0 <= self._current_device_idx < len(self._devices):
            current_serial = self._devices[self._current_device_idx]["serial"]
            
        return {
            "batch_id": self._batch_id,
            "state": self._state,
            "mode": self._mode,
            "current_device": current_serial,
            "devices": list(self._devices)
        }

    def _write_summary_locked(self):
        if not self._batch_id:
            return
        summary_path = RUN_LOG_DIR / self._batch_id / "batch_summary.json"
        data = {
            "batch_id": self._batch_id,
            "mode": self._mode,
            "created_at": self._created_at,
            "state": self._state,
            "devices": self._devices
        }
        try:
            summary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Failed to write batch_summary.json: {e}")

    def _write_device_summary(self, device_info, dev_output_dir):
        try:
            out_dir = Path(dev_output_dir)
            log_path = None
            xlsx_path = None
            runner_log_path = None
            if out_dir.is_dir():
                runner_log_file = out_dir / "runner.log"
                if runner_log_file.is_file():
                    runner_log_path = str(runner_log_file.relative_to(ROOT_DIR)) if runner_log_file.is_relative_to(ROOT_DIR) else str(runner_log_file)
                for f in out_dir.iterdir():
                    if f.is_file():
                        if f.name.endswith(".xlsx"):
                            xlsx_path = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                        elif f.name.endswith(".log") and ".normal" in f.name:
                            log_path = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                if not log_path and out_dir.is_dir():
                    for f in out_dir.iterdir():
                        if f.is_file() and f.name.endswith(".log") and f.name != "runner.log":
                            log_path = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                            break
            
            data = {}
            summary_path = out_dir / "summary.json"
            if summary_path.is_file():
                try:
                    data = json.loads(summary_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            parsed_summary = {}
            if log_path:
                abs_log_path = ROOT_DIR / log_path
                if abs_log_path.exists():
                    try:
                        from .run_summary import build_run_summary
                        parsed_summary = build_run_summary(
                            status={"state": device_info.get("state")},
                            log_path=abs_log_path,
                            scenario_ids=self._scenario_ids
                        )
                    except Exception as e:
                        print(f"Failed to parse log for summary: {e}")

            quality = parsed_summary.get("quality")
            if quality is None and xlsx_path:
                try:
                    from .mismatch_viewer import get_mismatch_summary_from_xlsx
                    mismatch_res = get_mismatch_summary_from_xlsx(ROOT_DIR / xlsx_path)
                    if "error" not in mismatch_res and "summary" in mismatch_res:
                        msummary = mismatch_res["summary"]
                        quality = {
                            "fail": msummary.get("fail_count", 0),
                            "issue": msummary.get("issue_count", 0),
                            "review": msummary.get("review_count", 0),
                            "clean": msummary.get("clean_count", 0)
                        }
                        
                        quality_issues = []
                        for sig in mismatch_res.get("signals", []):
                            crop_thumb = sig.get("crop_thumbnail")
                            crop_path = None
                            if crop_thumb:
                                rel_out_dir = str(out_dir.relative_to(ROOT_DIR)) if out_dir.is_relative_to(ROOT_DIR) else str(out_dir)
                                crop_path = f"{rel_out_dir}/crops/{crop_thumb}".replace("\\", "/")
                            
                            quality_issues.append({
                                "scenario_id": sig.get("scenario_id", ""),
                                "step": sig.get("step", ""),
                                "context_type": sig.get("context_type", ""),
                                "visible_label": sig.get("visible_label", ""),
                                "merged_announcement": sig.get("merged_announcement", ""),
                                "mismatch_type": sig.get("mismatch_type", ""),
                                "final_result": sig.get("final_result", ""),
                                "review_note": sig.get("review_note", ""),
                                "focus_confidence": sig.get("focus_confidence", ""),
                                "crop_path": crop_path
                            })
                        data["quality_issues"] = quality_issues
                        
                except Exception as e:
                    print(f"Failed to extract quality from xlsx: {e}")

            data.update({
                "batch_id": self._batch_id,
                "serial": device_info.get("serial"),
                "model": device_info.get("model"),
                "state": device_info.get("state"),
                "output_dir": device_info.get("output_dir"),
                "return_code": device_info.get("return_code"),
                "started_at": device_info.get("started_at"),
                "finished_at": device_info.get("finished_at"),
                "runner_log_path": runner_log_path,
                "log_path": log_path,
                "xlsx_path": xlsx_path,
                "quality": quality,
                "scenarios": parsed_summary.get("scenarios", []),
                "process_status": parsed_summary.get("process_status"),
                "scenario_result_status": parsed_summary.get("scenario_result_status"),
                "passed_scenarios": parsed_summary.get("passed_scenarios", 0),
                "warning_scenarios": parsed_summary.get("warning_scenarios", 0),
                "completed_scenarios": parsed_summary.get("completed_scenarios", 0),
                "failed_scenarios": parsed_summary.get("failed_scenarios", 0)
            })
            summary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Failed to write device summary.json: {e}")

    def _run_loop(self):
        while True:
            with self._lock:
                if self._current_device_idx >= len(self._devices):
                    self._state = "finished"
                    self._write_summary_locked()
                    break
                device_info = self._devices[self._current_device_idx]
                device_info["state"] = "running"
                device_info["started_at"] = datetime.now(timezone.utc).isoformat()
                self._write_summary_locked()
            
            dev_serial = device_info["serial"]
            dev_output_dir_rel = device_info["output_dir"]
            dev_output_dir = str(ROOT_DIR / dev_output_dir_rel)
            
            Path(dev_output_dir).mkdir(parents=True, exist_ok=True)
            
            log_path = Path(dev_output_dir) / "runner.log"
            log_file = log_path.open("w", encoding="utf-8", errors="replace")
            
            env = os.environ.copy()
            env["TB_OUTPUT_DIR"] = dev_output_dir
            env["ANDROID_SERIAL"] = dev_serial
            
            try:
                # 1. Config copy
                runtime_config = write_selected_runtime_config(
                    source_path=RUNTIME_CONFIG_PATH,
                    output_path=Path(dev_output_dir) / "runtime_config.json",
                    scenario_ids=self._scenario_ids,
                    mode=self._mode,
                )
                env[RUNTIME_CONFIG_PATH_ENV] = str(runtime_config["path"])
                
                log_file.write(f"[BATCH] Config generated for {dev_serial}\n")
                log_file.flush()
                
                # 2. Language mode
                os.environ["ANDROID_SERIAL"] = dev_serial
                language_status = apply_language_mode(self._language_mode)
                for line in format_language_log_lines(language_status):
                    log_file.write(f"{line}\n")
                if not language_status.get("ok"):
                    raise Exception(f"Language setup failed: {language_status}")
                    
                # 3. Preflight
                preflight = run_runtime_preflight(self._launch_mode)
                for line in format_preflight_log_lines(preflight):
                    log_file.write(f"{line}\n")
                if not preflight.get("ok"):
                    raise Exception(f"Preflight blocked: {preflight.get('reason')}")
                
            except Exception as e:
                with self._lock:
                    device_info["state"] = "failed"
                    device_info["error"] = f"Setup error: {str(e)}"
                    device_info["finished_at"] = datetime.now(timezone.utc).isoformat()
                    self._current_device_idx += 1
                    self._write_summary_locked()
                self._write_device_summary(device_info, dev_output_dir)
                log_file.write(f"\n[BATCH ERROR] {e}\n")
                log_file.close()
                if "ANDROID_SERIAL" in os.environ:
                    del os.environ["ANDROID_SERIAL"]
                continue
                
            if "ANDROID_SERIAL" in os.environ:
                del os.environ["ANDROID_SERIAL"]
                
            cmd = [sys.executable, str(SCRIPT_PATH), "--serial", dev_serial, "--output-dir", dev_output_dir]
            
            try:
                proc = subprocess.Popen(
                    cmd, 
                    cwd=ROOT_DIR,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1
                )
                
                def _tee_output():
                    try:
                        for line in iter(proc.stdout.readline, ""):
                            log_file.write(line)
                            log_file.flush()
                        remainder = proc.stdout.read()
                        if remainder:
                            log_file.write(remainder)
                            log_file.flush()
                    except Exception as e:
                        log_file.write(f"\n[TEE ERROR] {e}\n")
                        log_file.flush()

                import threading
                tee_thread = threading.Thread(target=_tee_output, daemon=True)
                tee_thread.start()
                
                proc.wait()
                tee_thread.join(timeout=5.0)
                
                if tee_thread.is_alive():
                    log_file.write("\n[BATCH WARNING] tee_thread join timeout\n")
                log_file.flush()
                
                try:
                    file_size = log_path.stat().st_size
                    log_file.write(f"\n[BATCH] runner.log flushed bytes={file_size}\n")
                    log_file.flush()
                except Exception:
                    pass
                
                with self._lock:
                    device_info["state"] = "passed" if proc.returncode == 0 else "failed"
                    device_info["return_code"] = proc.returncode
                    device_info["finished_at"] = datetime.now(timezone.utc).isoformat()
                    self._current_device_idx += 1
                    self._write_summary_locked()
                self._write_device_summary(device_info, dev_output_dir)
                    
            except Exception as e:
                with self._lock:
                    device_info["state"] = "failed"
                    device_info["error"] = str(e)
                    device_info["finished_at"] = datetime.now(timezone.utc).isoformat()
                    self._current_device_idx += 1
                    self._write_summary_locked()
                self._write_device_summary(device_info, dev_output_dir)
                log_file.write(f"\n[BATCH ERROR] {e}\n")
            finally:
                log_file.close()

global_batch_manager = BatchRunManager()


def get_recent_batches() -> list[dict]:
    batches = []
    if not RUN_LOG_DIR.exists():
        return batches
        
    for batch_dir in sorted(RUN_LOG_DIR.iterdir(), reverse=True):
        if not batch_dir.is_dir() or not batch_dir.name.startswith("batch_"):
            continue
            
        summary_path = batch_dir / "batch_summary.json"
        if not summary_path.exists():
            continue
            
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            devices = data.get("devices", [])
            passed_count = sum(1 for d in devices if d.get("state") == "passed")
            failed_count = sum(1 for d in devices if d.get("state") in ("failed", "error"))
            devices_info = []
            for d in devices:
                out_dir_str = d.get("output_dir")
                dev_info = {
                    "serial": d.get("serial"),
                    "model": d.get("model"),
                    "state": d.get("state"),
                    "return_code": d.get("return_code"),
                    "log_path": None,
                    "xlsx_path": None,
                    "quality": None
                }
                if out_dir_str:
                    out_dir = ROOT_DIR / out_dir_str
                    if out_dir.is_dir():
                        runner_log_file = out_dir / "runner.log"
                        if runner_log_file.is_file():
                            dev_info["runner_log_path"] = str(runner_log_file.relative_to(ROOT_DIR)) if runner_log_file.is_relative_to(ROOT_DIR) else str(runner_log_file)
                        for f in out_dir.iterdir():
                            if f.is_file():
                                if f.name.endswith(".xlsx"):
                                    dev_info["xlsx_path"] = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                                elif f.name.endswith(".log") and ".normal" in f.name:
                                    dev_info["log_path"] = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                        if not dev_info.get("log_path") and out_dir.is_dir():
                            for f in out_dir.iterdir():
                                if f.is_file() and f.name.endswith(".log") and f.name != "runner.log":
                                    dev_info["log_path"] = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                                    break
                        
                        dev_summary_path = out_dir / "summary.json"
                        if dev_summary_path.exists():
                            try:
                                dev_data = json.loads(dev_summary_path.read_text(encoding="utf-8"))
                                dev_info["quality"] = dev_data.get("quality")
                                dev_info["quality_issues"] = dev_data.get("quality_issues")
                                
                                from .recent_runs import _recent_run_from_summary
                                from datetime import datetime
                                parsed = _recent_run_from_summary(
                                    summary=dev_data,
                                    path=dev_summary_path,
                                    run_id=dev_data.get("run_id", "batch"),
                                    mode=dev_data.get("mode", "unknown"),
                                    started_at=datetime.fromtimestamp(dev_summary_path.stat().st_mtime),
                                    modified_at=datetime.fromtimestamp(dev_summary_path.stat().st_mtime),
                                    current_status=None,
                                )
                                dev_info.update(parsed)
                            except Exception:
                                pass
                devices_info.append(dev_info)

            batches.append({
                "batch_id": data.get("batch_id", batch_dir.name),
                "state": data.get("state", "unknown"),
                "mode": data.get("mode", "unknown"),
                "created_at": data.get("created_at"),
                "device_count": len(devices),
                "passed_count": passed_count,
                "failed_count": failed_count,
                "summary_path": str(summary_path.relative_to(ROOT_DIR)) if summary_path.is_relative_to(ROOT_DIR) else str(summary_path),
                "devices": devices_info
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            continue
            
        if len(batches) >= 20:
            break
            
    return batches
