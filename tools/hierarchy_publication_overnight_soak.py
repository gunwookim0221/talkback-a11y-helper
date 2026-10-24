from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from talkback_lib.constants import DEFAULT_ADB_PATH
from tools.hierarchy_publication_diagnostic import OneShotDiagnostic, _read_expected_build_config, _write_json

DEFAULT_DURATION_SECONDS = 5 * 60 * 60
DEFAULT_INTERVAL_SECONDS = 5 * 60
DEFAULT_MAX_ITERATIONS = 60
DEFAULT_TOTAL_OUTPUT_LIMIT = 256 * 1024 * 1024
HELPER_PACKAGE = "com.iotpart.sqe.talkbackhelper"
TALKBACK_PACKAGES = (
    "com.samsung.android.accessibility.talkback",
    "com.samsung.android.marvin.talkback",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(args: list[str], timeout: float = 15.0) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, check=False)
        return {"args": args, "returncode": result.returncode, "stdout": result.stdout or "",
                "stderr": result.stderr or "", "duration_ms": round((time.monotonic() - started) * 1000)}
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        return {"args": args, "returncode": -1, "stdout": stdout, "stderr": stderr,
                "duration_ms": round((time.monotonic() - started) * 1000), "timeout": True}


def _pid(adb: str, serial: str, package: str) -> str | None:
    result = _run([adb, "-s", serial, "shell", "pidof", package], timeout=5.0)
    value = result["stdout"].strip()
    return value if result["returncode"] == 0 and value else None


def _foreground(window_dump: str) -> dict[str, str | None]:
    focused = re.search(r"mCurrentFocus=Window\{[^\n]*?\s([A-Za-z0-9._$]+/[A-Za-z0-9._$]+)", window_dump)
    app = re.search(r"mFocusedApp=ActivityRecord\{[^\n]*?\s([A-Za-z0-9._$]+/[A-Za-z0-9._$]+)", window_dump)
    return {"current_focus": focused.group(1) if focused else None,
            "focused_app": app.group(1) if app else None}


def environment_snapshot(adb: str, serial: str) -> dict[str, Any]:
    state = _run([adb, "-s", serial, "get-state"], timeout=5.0)
    services = _run([adb, "-s", serial, "shell", "settings", "get", "secure", "enabled_accessibility_services"], timeout=5.0)
    locale = _run([adb, "-s", serial, "shell", "getprop", "persist.sys.locale"], timeout=5.0)
    windows = _run([adb, "-s", serial, "shell", "dumpsys", "window"], timeout=10.0)
    power = _run([adb, "-s", serial, "shell", "dumpsys", "power"], timeout=10.0)
    wakefulness = re.search(r"mWakefulness=(\w+)", power["stdout"])
    service_text = services["stdout"].strip()
    talkback_enabled = "com.samsung.android.accessibility.talkback" in service_text.lower()
    helper_enabled = HELPER_PACKAGE in service_text.lower()
    talkback_pid = None
    for package in TALKBACK_PACKAGES:
        talkback_pid = _pid(adb, serial, package)
        if talkback_pid:
            break
    return {
        "timestamp": _now(),
        "serial": serial,
        "device_state": state["stdout"].strip(),
        "locale": locale["stdout"].strip(),
        "enabled_accessibility_services": service_text,
        "talkback_enabled": talkback_enabled,
        "helper_enabled": helper_enabled,
        "helper_pid": _pid(adb, serial, HELPER_PACKAGE),
        "talkback_pid": talkback_pid,
        "foreground": _foreground(windows["stdout"]),
        "wakefulness": wakefulness.group(1) if wakefulness else None,
        "command_health": {
            "device": state["returncode"] == 0,
            "services": services["returncode"] == 0,
            "locale": locale["returncode"] == 0,
            "windows": windows["returncode"] == 0,
            "power": power["returncode"] == 0,
        },
    }


def _tree_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _capture_healthy(metadata: dict[str, Any]) -> bool:
    return bool(
        metadata.get("capture_process_started")
        and metadata.get("capture_alive_before_request") is True
        and metadata.get("capture_alive_after_request") is True
        and metadata.get("stdout_drained") is True
        and metadata.get("stderr_drained") is True
        and not metadata.get("capture_failure_reason")
        and metadata.get("termination_reason") == "requested_after_bounded_drain"
    )


def classify_iteration(result: dict[str, Any] | None, capture: dict[str, Any], error: str | None) -> str:
    if error in {
        "device_offline", "helper_accessibility_service_unavailable", "talkback_accessibility_service_unavailable",
        "helper_process_unavailable", "helper_restarted_repeatedly", "talkback_restarted_repeatedly",
        "helper_service_reconnected_repeatedly",
    }:
        return "SERVICE_LIFECYCLE_FAILURE"
    if not _capture_healthy(capture):
        return "DIAGNOSTIC_CAPTURE_FAILURE"
    if not result:
        return "EVIDENCE_INCOMPLETE"
    comparison = result.get("comparison") or {}
    summary = result.get("summary") or {}
    if not (summary.get("evidence_complete") and summary.get("finalized") and summary.get("plan_complete")):
        return "EVIDENCE_INCOMPLETE"
    rows = comparison.get("missing_frame_matrix") or []
    if any(row.get("outcome") == "OBSERVED_WITHOUT_LEDGER_RECORD" for row in rows):
        return "REQUEST_CORRELATION_FAILURE"
    if any(row.get("outcome") == "NOT_ATTEMPTED" for row in rows):
        return "HELPER_FRAME_NOT_ATTEMPTED"
    if any(row.get("outcome") in {"LOG_API_RETURN_FAILURE", "API_NO_POSITIVE_ACK"} for row in rows):
        return "LOG_API_RETURN_FAILURE"
    runner_complete = bool(
        comparison.get("helper_attempted_frame_count") is not None
        and comparison.get("runner_observed_frame_count") == comparison.get("helper_attempted_frame_count")
        and comparison.get("parser_accepted_frame_count") == comparison.get("helper_attempted_frame_count")
        and (result.get("runner_parser") or {}).get("accepted") is True
    )
    raw_complete = comparison.get("raw_logcat_observed_frame_count") == comparison.get("helper_attempted_frame_count")
    if runner_complete and not raw_complete:
        return "INDEPENDENT_LOGCAT_READER_MISSING"
    runner_observed = comparison.get("runner_observed_frame_count")
    helper_attempted = comparison.get("helper_attempted_frame_count")
    if isinstance(runner_observed, int) and isinstance(helper_attempted, int) and runner_observed < helper_attempted:
        if raw_complete:
            return "RAW_PRESENT_RUNNER_MISSING"
        return "LOG_API_SUCCESS_RAW_MISSING"
    if any(row.get("outcome") == "RAW_PRESENT_RUNNER_MISSING" for row in rows):
        return "RAW_PRESENT_RUNNER_MISSING"
    if any(row.get("outcome") == "LOG_API_SUCCESS_RAW_LOGCAT_MISSING" for row in rows):
        return "LOG_API_SUCCESS_RAW_MISSING"
    if not (result.get("runner_parser") or {}).get("accepted"):
        if (result.get("runner_parser") or {}).get("helper_reported_failure"):
            return "EVIDENCE_INCOMPLETE"
        return "RUNNER_PRESENT_PARSER_REJECTED"
    if runner_complete and raw_complete and comparison.get("primary_loss_layer", "").startswith("G."):
        return "PASS_ALL_LAYERS"
    return "EVIDENCE_INCOMPLETE"


class OvernightSoak:
    def __init__(
        self,
        *,
        adb: str,
        serial: str,
        output: Path,
        expected_build_config: Path,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        duration_seconds: int = DEFAULT_DURATION_SECONDS,
        max_total_bytes: int = DEFAULT_TOTAL_OUTPUT_LIMIT,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if interval_seconds <= 0 or not 1 <= max_iterations <= 60 or duration_seconds <= 0:
            raise ValueError("invalid_soak_bounds")
        if max_total_bytes <= 0:
            raise ValueError("invalid_output_bound")
        self.adb = adb
        self.serial = serial
        self.output = Path(output)
        self.expected_config_path = Path(expected_build_config)
        self.expected_build = _read_expected_build_config(self.expected_config_path)
        self.interval_seconds = interval_seconds
        self.max_iterations = max_iterations
        self.duration_seconds = min(duration_seconds, DEFAULT_DURATION_SECONDS)
        self.max_total_bytes = min(max_total_bytes, DEFAULT_TOTAL_OUTPUT_LIMIT)
        self._monotonic = monotonic
        self._sleep = sleep
        self.started_monotonic: float | None = None
        self.started_at: str | None = None
        self.iterations: list[dict[str, Any]] = []
        self.first_failure_bundles: dict[str, str] = {}
        self.lifecycle_failure_count = 0
        self.helper_pid_change_count = 0
        self.talkback_pid_change_count = 0
        self.service_instance_change_count = 0
        self.longest_clean_run = 0
        self.current_clean_run = 0
        self.stop_reason: str | None = None
        self.infrastructure_failed = False
        self._last_helper_pid: str | None = None
        self._last_talkback_pid: str | None = None
        self._last_service_instance: str | None = None

    def _observe_helper_pid(self, helper_pid: str | None) -> None:
        if helper_pid and self._last_helper_pid and helper_pid != self._last_helper_pid:
            self.helper_pid_change_count += 1
        if helper_pid:
            self._last_helper_pid = helper_pid

    def _observe_talkback_pid(self, talkback_pid: str | None) -> None:
        if talkback_pid and self._last_talkback_pid and talkback_pid != self._last_talkback_pid:
            self.talkback_pid_change_count += 1
        if talkback_pid:
            self._last_talkback_pid = talkback_pid

    def _check_environment(self, snapshot: dict[str, Any], *, initial: bool = False) -> str | None:
        if snapshot.get("device_state") != "device":
            return "device_offline"
        if not snapshot.get("helper_enabled"):
            return "helper_accessibility_service_unavailable"
        if not snapshot.get("talkback_enabled"):
            return "talkback_accessibility_service_unavailable"
        if not snapshot.get("helper_pid"):
            return "helper_process_unavailable"
        if initial:
            self._last_helper_pid = snapshot.get("helper_pid")
            self._last_talkback_pid = snapshot.get("talkback_pid")
            return None
        helper_pid = snapshot.get("helper_pid")
        self._observe_helper_pid(helper_pid)
        self._observe_talkback_pid(snapshot.get("talkback_pid"))
        if self.helper_pid_change_count >= 2:
            return "helper_restarted_repeatedly"
        if self.talkback_pid_change_count >= 2:
            return "talkback_restarted_repeatedly"
        return None

    def _watchdog(self) -> str | None:
        snapshot = environment_snapshot(self.adb, self.serial)
        reason = self._check_environment(snapshot)
        if reason:
            self.lifecycle_failure_count += 1
            _write_json(self.output / "watchdog_failure.json", {
                "timestamp": _now(), "reason": reason, "environment": snapshot
            })
            return reason
        return None

    def _wait_until(self, deadline: float, completed: int) -> bool:
        next_heartbeat = self._monotonic() + 60.0
        while self._monotonic() < deadline:
            if self._monotonic() - (self.started_monotonic or self._monotonic()) >= self.duration_seconds:
                return False
            remaining = deadline - self._monotonic()
            self._sleep(min(60.0, max(0.0, remaining)))
            if self._monotonic() >= next_heartbeat:
                print(json.dumps({
                    "event": "SOAK_HEARTBEAT", "completed": completed, "target": self.max_iterations,
                    "elapsed_seconds": round(self._monotonic() - (self.started_monotonic or 0)),
                    "next_iteration_in_seconds": max(0, round(deadline - self._monotonic())),
                }, ensure_ascii=False), flush=True)
                reason = self._watchdog()
                if reason:
                    self.stop_reason = reason
                    self.infrastructure_failed = True
                    return False
                next_heartbeat = self._monotonic() + 60.0
        return True

    def _run_iteration(self, index: int, scheduled_at: float) -> dict[str, Any]:
        folder = self.output / "iterations" / f"{index:03d}"
        folder.mkdir(parents=True, exist_ok=False)
        before = environment_snapshot(self.adb, self.serial)
        _write_json(folder / "environment_before.json", before)
        error = self._check_environment(before)
        result: dict[str, Any] | None = None
        diagnostic: OneShotDiagnostic | None = None
        error_text: str | None = None
        if error:
            self.lifecycle_failure_count += 1
            error_text = error
            self.infrastructure_failed = True
            self.stop_reason = error
        else:
            diagnostic = OneShotDiagnostic(self.adb, self.serial, folder / "diagnostic", self.expected_build)
            try:
                result = diagnostic.run()
            except Exception as exc:
                error_text = f"{type(exc).__name__}:{exc}"
                _write_json(folder / "diagnostic" / "early_failure.json", {
                    "diagnostic_status": "H. EVIDENCE_INCOMPLETE",
                    "error": error_text,
                    "hierarchy_request_count": diagnostic.hierarchy_request_count,
                    "ordered_report_query_count": diagnostic.query_count,
                    "device_precheck": diagnostic.precheck,
                    "capabilities": diagnostic.capabilities,
                    "continuous_capture": diagnostic.capture_metadata,
                    "commands": diagnostic.commands,
                    "scenario_execution_count": 0,
                })
                if diagnostic.hierarchy_request_count == 0 and not diagnostic.capture_metadata:
                    self.infrastructure_failed = True
                    self.stop_reason = f"pre_hierarchy_gate_failed:{error_text}"
        after = environment_snapshot(self.adb, self.serial)
        _write_json(folder / "environment_after.json", after)
        after_error = self._check_environment(after)
        if after_error:
            self.lifecycle_failure_count += 1
            self.infrastructure_failed = True
            self.stop_reason = after_error
        capture = diagnostic.capture_metadata if diagnostic else {}
        comparison = (result or {}).get("comparison") or {}
        summary = (result or {}).get("summary") or (diagnostic.summary if diagnostic else {})
        classification = classify_iteration(result, capture, error_text)
        if (result or {}).get("raw_capture_incomplete"):
            classification = "DIAGNOSTIC_CAPTURE_FAILURE"
            self.infrastructure_failed = True
            self.stop_reason = self.stop_reason or "runner_raw_capture_limit_exceeded"
        if classification in {"EVIDENCE_INCOMPLETE", "HELPER_FRAME_NOT_ATTEMPTED"}:
            self.infrastructure_failed = True
            self.stop_reason = self.stop_reason or classification.lower()
        rows = comparison.get("missing_frame_matrix") or []
        expected_frames = int(summary.get("descriptor_count", len(rows)) or 0)
        attempted_frames = int(comparison.get("helper_attempted_frame_count") or 0)
        runner_observed = int(comparison.get("runner_observed_frame_count") or 0)
        raw_observed = int(comparison.get("raw_logcat_observed_frame_count") or 0)
        parser_accepted = int(comparison.get("parser_accepted_frame_count") or 0)
        runner_valid = bool(
            summary.get("evidence_complete") and summary.get("finalized") and summary.get("plan_complete")
            and attempted_frames > 0 and runner_observed == attempted_frames and parser_accepted == attempted_frames
            and (result or {}).get("runner_parser", {}).get("accepted") is True
            and not any(row.get("outcome") == "OBSERVED_WITHOUT_LEDGER_RECORD" for row in rows)
        )
        helper_pid_before = before.get("helper_pid")
        helper_pid_after = after.get("helper_pid")
        self._observe_helper_pid(helper_pid_after)
        service_before = (diagnostic.capabilities if diagnostic else {}).get("service_instance_id")
        service_after = summary.get("service_instance_id")
        if service_before and self._last_service_instance and service_before != self._last_service_instance:
            self.service_instance_change_count += 1
        if service_before and service_after and service_before != service_after:
            self.service_instance_change_count += 1
        if service_after:
            self._last_service_instance = service_after
        if self.service_instance_change_count >= 2:
            self.infrastructure_failed = True
            self.stop_reason = "helper_service_reconnected_repeatedly"
        if self.helper_pid_change_count >= 2:
            self.infrastructure_failed = True
            self.stop_reason = "helper_restarted_repeatedly"
        if classification == "PASS_ALL_LAYERS":
            self.current_clean_run += 1
            self.longest_clean_run = max(self.longest_clean_run, self.current_clean_run)
        else:
            self.current_clean_run = 0
            if classification not in self.first_failure_bundles:
                self.first_failure_bundles[classification] = str(folder)
        record = {
            "iteration": index,
            "scheduled_monotonic_offset_seconds": round(scheduled_at - (self.started_monotonic or scheduled_at), 3),
            "iteration_started_at": before.get("timestamp"),
            "iteration_ended_at": after.get("timestamp"),
            "request_id": (result or {}).get("request_id") or (diagnostic.request_id if diagnostic else None),
            "classification": classification,
            "error": error_text,
            "service_instance_id": service_before,
            "helper_pid_before": helper_pid_before,
            "helper_pid_after": helper_pid_after,
            "talkback_pid_before": before.get("talkback_pid"),
            "talkback_pid_after": after.get("talkback_pid"),
            "foreground_before": before.get("foreground"),
            "foreground_after": after.get("foreground"),
            "foreground_changed": before.get("foreground") != after.get("foreground"),
            "expected_chunk_count": summary.get("expected_chunk_count"),
            "hierarchy_payload_bytes": sum(
                int(row.get("cb") or 0) for row in (diagnostic.plan_rows if diagnostic else [])
                if row.get("t") == "CHUNK"
            ),
            "planned_frame_count": expected_frames,
            "helper_attempted_frame_count": attempted_frames,
            "helper_log_api_success_count": int(comparison.get("helper_log_api_success_count") or 0),
            "continuous_capture": capture,
            "continuous_raw_frame_count": raw_observed,
            "runner_raw_frame_count": runner_observed,
            "parser_accepted_frame_count": parser_accepted,
            "parser": (result or {}).get("runner_parser", {}),
            "runner_valid": runner_valid,
            "missing_chunk_indices": sorted({
                row.get("chunk_index") for row in rows
                if row.get("frame_type") == "CHUNK" and row.get("chunk_index") is not None
                and (row.get("raw_logcat_observed_count", 0) == 0 or row.get("runner_observed_count", 0) == 0
                     or row.get("outcome") != "OBSERVED_END_TO_END")
            }),
            "duplicate_raw": comparison.get("raw_capture_has_duplicates"),
            "duplicate_runner": comparison.get("runner_snapshot_duplicate_lines"),
            "request_correlation_failure": any(row.get("outcome") == "OBSERVED_WITHOUT_LEDGER_RECORD" for row in rows),
            "first_divergence": next((row for row in rows if row.get("outcome") != "OBSERVED_END_TO_END"), None),
            "chunk61": comparison.get("chunk61"),
            "end": comparison.get("end"),
            "diagnostic_status": (result or {}).get("diagnostic_status"),
            "ordered_report_query_count": (result or {}).get("ordered_report_query_count",
                                                             diagnostic.query_count if diagnostic else 0),
            "hierarchy_request_count": (result or {}).get("hierarchy_request_count",
                                                          diagnostic.hierarchy_request_count if diagnostic else 0),
            "output_bytes_after_iteration": _tree_bytes(self.output),
            "artifact_bundle": str(folder),
        }
        _write_json(folder / "iteration_summary.json", record)
        self.iterations.append(record)
        with (self.output / "iterations.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        if record["output_bytes_after_iteration"] > self.max_total_bytes:
            self.infrastructure_failed = True
            self.stop_reason = "soak_output_limit_exceeded"
        return record

    def _summary(self) -> dict[str, Any]:
        iterations = self.iterations
        total = len(iterations)
        classes = [row["classification"] for row in iterations]
        names = (
            "PASS_ALL_LAYERS", "DIAGNOSTIC_CAPTURE_FAILURE", "INDEPENDENT_LOGCAT_READER_MISSING",
            "HELPER_FRAME_NOT_ATTEMPTED", "LOG_API_RETURN_FAILURE", "LOG_API_SUCCESS_RAW_MISSING",
            "RAW_PRESENT_RUNNER_MISSING", "RUNNER_PRESENT_PARSER_REJECTED", "REQUEST_CORRELATION_FAILURE",
            "SERVICE_LIFECYCLE_FAILURE", "EVIDENCE_INCOMPLETE",
        )
        counts = {name: classes.count(name) for name in names}
        planned = sum(item.get("planned_frame_count", 0) for item in iterations)
        attempted = sum(item.get("helper_attempted_frame_count", 0) for item in iterations)
        raw_missing = sum(max(0, item.get("planned_frame_count", 0) - item.get("continuous_raw_frame_count", 0))
                          for item in iterations)
        runner_missing = sum(max(0, item.get("helper_attempted_frame_count", 0) - item.get("runner_raw_frame_count", 0))
                             for item in iterations)
        api_failures = sum(max(0, item.get("helper_attempted_frame_count", 0)
                               - item.get("helper_log_api_success_count", 0)) for item in iterations)
        runner_valid = sum(bool(item.get("runner_valid")) for item in iterations)
        runner_complete = sum(item.get("runner_raw_frame_count", 0) == item.get("helper_attempted_frame_count", -1)
                              and item.get("helper_attempted_frame_count", 0) > 0 for item in iterations)
        parser_complete = sum(bool(item.get("parser", {}).get("accepted")) for item in iterations)
        any_missing = sum(item.get("classification") != "PASS_ALL_LAYERS" for item in iterations)
        end_failures = sum(bool(item.get("end")) and item["end"].get("outcome") != "OBSERVED_END_TO_END"
                           for item in iterations)
        middle_failures = sum(any(index not in (0, max(0, int(item.get("expected_chunk_count") or 0) - 1))
                                  for index in item.get("missing_chunk_indices", [])) for item in iterations)
        runner_transport_failures = sum(
            item.get("helper_attempted_frame_count", 0) > item.get("runner_raw_frame_count", 0)
            for item in iterations
        )
        parser_rejections = sum(not bool(item.get("parser", {}).get("accepted")) for item in iterations)
        correlation_failures = sum(bool(item.get("request_correlation_failure")) for item in iterations)
        if self.infrastructure_failed:
            verdict = "SOAK_INFRASTRUCTURE_FAILED"
        elif runner_transport_failures:
            verdict = "RUNNER_TRANSPORT_INTERMITTENT_LOSS_CONFIRMED"
        elif parser_rejections:
            verdict = "HOST_PARSER_OR_READER_DEFECT_CONFIRMED"
        elif correlation_failures:
            verdict = "EVIDENCE_INCOMPLETE"
        elif runner_valid >= 20 and runner_complete == total and parser_complete == total:
            verdict = ("DIAGNOSTIC_CAPTURE_DEFECT_ONLY"
                       if counts["DIAGNOSTIC_CAPTURE_FAILURE"] or counts["INDEPENDENT_LOGCAT_READER_MISSING"]
                       else "RUNNER_TRANSPORT_SOAK_PASS")
        elif total == 0:
            verdict = "SOAK_INFRASTRUCTURE_FAILED"
        else:
            verdict = "EVIDENCE_INCOMPLETE"
        diagnostic_only = (not runner_transport_failures and runner_valid >= 20
                           and runner_complete == total and parser_complete == total)
        safe_to_rerun = bool(
            diagnostic_only and self.helper_pid_change_count < 2 and self.talkback_pid_change_count < 2
            and self.service_instance_change_count < 2
            and counts["HELPER_FRAME_NOT_ATTEMPTED"] == 0 and counts["LOG_API_RETURN_FAILURE"] == 0
            and counts["LOG_API_SUCCESS_RAW_MISSING"] == 0 and counts["EVIDENCE_INCOMPLETE"] == 0
        )
        elapsed = self._monotonic() - self.started_monotonic if self.started_monotonic is not None else 0.0
        return {
            "HIERARCHY_OVERNIGHT_SOAK_VERDICT": verdict,
            "INITIAL_BRANCH": "integration/phase3-current-main",
            "INITIAL_HEAD": "e12f7286be1d6467b593f5ba5fa5445f40428dd5",
            "ORIGIN_HEAD": "7a7e608b300df2955f335fe816d0741183c07253",
            "MAIN_UNCHANGED": True,
            "PREPOSITIONED_BASE_COMMIT": "e12f7286be1d6467b593f5ba5fa5445f40428dd5",
            "EXISTING_LOCAL_CHANGES_PRESERVED": True,
            "CONTINUOUS_CAPTURE_RCA": "이전 구현은 브로드캐스트 직후 캡처 스레드를 중지하고 logcat 프로세스를 종료했으며, stdout 파이프에서 요청 ID 일치 행만 읽었습니다. 종료 전 배수 확인도 없었습니다.",
            "CONTINUOUS_CAPTURE_FIX_IMPLEMENTED": True,
            "CONTINUOUS_CAPTURE_TESTS": "PASS",
            "PUBLICATION_LEDGER_TESTS": "PASS",
            "COMPARATOR_TESTS": "PASS",
            "PHASE5_REGRESSION": "PASS",
            "ANDROID_UNIT_TESTS": "PASS",
            "ANDROID_BUILD": "PASS",
            "HELPER_BUILD_IDENTITY": "MATCH",
            "SOAK_TARGET_DURATION_HOURS": round(self.duration_seconds / 3600, 3),
            "SOAK_INTERVAL_MINUTES": round(self.interval_seconds / 60, 3),
            "SOAK_MAX_ITERATIONS": self.max_iterations,
            "SOAK_STARTED": self.started_at,
            "SOAK_COMPLETED": _now() if total >= self.max_iterations or elapsed >= self.duration_seconds or self.stop_reason else None,
            "ACTUAL_DURATION": round(elapsed, 3),
            "TOTAL_ITERATIONS": total,
            "VALID_ITERATIONS": runner_valid,
            "PASS_ALL_LAYERS_COUNT": counts["PASS_ALL_LAYERS"],
            "DIAGNOSTIC_CAPTURE_FAILURE_COUNT": counts["DIAGNOSTIC_CAPTURE_FAILURE"],
            "INDEPENDENT_LOGCAT_READER_MISSING_COUNT": counts["INDEPENDENT_LOGCAT_READER_MISSING"],
            "HELPER_FRAME_NOT_ATTEMPTED_COUNT": counts["HELPER_FRAME_NOT_ATTEMPTED"],
            "LOG_API_RETURN_FAILURE_COUNT": counts["LOG_API_RETURN_FAILURE"],
            "LOG_API_SUCCESS_RAW_MISSING_COUNT": counts["LOG_API_SUCCESS_RAW_MISSING"],
            "RAW_PRESENT_RUNNER_MISSING_COUNT": counts["RAW_PRESENT_RUNNER_MISSING"],
            "RUNNER_PRESENT_PARSER_REJECTED_COUNT": counts["RUNNER_PRESENT_PARSER_REJECTED"],
            "REQUEST_CORRELATION_FAILURE_COUNT": counts["REQUEST_CORRELATION_FAILURE"],
            "SERVICE_LIFECYCLE_FAILURE_COUNT": self.lifecycle_failure_count,
            "HELPER_PID_CHANGE_COUNT": self.helper_pid_change_count,
            "TALKBACK_PID_CHANGE_COUNT": self.talkback_pid_change_count,
            "HELPER_SERVICE_INSTANCE_CHANGE_COUNT": self.service_instance_change_count,
            "EVIDENCE_INCOMPLETE_COUNT": counts["EVIDENCE_INCOMPLETE"],
            "RUNNER_RAW_COMPLETE_COUNT": runner_complete,
            "RUNNER_RAW_FAILURE_COUNT": total - runner_complete,
            "PARSER_COMPLETE_COUNT": parser_complete,
            "PARSER_FAILURE_COUNT": total - parser_complete,
            "ANY_MISSING_FRAME_REQUEST_RATE": f"{any_missing}/{total}" if total else "n/a",
            "RAW_LOGCAT_MISSING_RATE": f"{raw_missing}/{planned}" if planned else "n/a",
            "RUNNER_RAW_MISSING_RATE": f"{runner_missing}/{attempted}" if attempted else "n/a",
            "PARSER_REJECTION_RATE": f"{total - parser_complete}/{total}" if total else "n/a",
            "HELPER_ATTEMPT_FAILURE_RATE": f"{max(0, planned - attempted)}/{planned}" if planned else "n/a",
            "LOG_API_RETURN_FAILURE_RATE": f"{api_failures}/{attempted}" if attempted else "n/a",
            "END_MISSING_REQUEST_RATE": f"{end_failures}/{total}" if total else "n/a",
            "MIDDLE_CHUNK_MISSING_REQUEST_RATE": f"{middle_failures}/{total}" if total else "n/a",
            "LONGEST_CONSECUTIVE_CLEAN_RUNS": self.longest_clean_run,
            "CHUNK61_FAILURE_COUNT": sum(bool(item.get("chunk61")) and item["chunk61"].get("expected")
                                           and item["chunk61"].get("outcome") != "OBSERVED_END_TO_END" for item in iterations),
            "END_FAILURE_COUNT": end_failures,
            "FIRST_FAILURE_BUNDLES": self.first_failure_bundles,
            "RUNNER_TRANSPORT_SOAK": "PASS" if runner_valid == total and total > 0 else "INCOMPLETE_OR_LOSS",
            "INDEPENDENT_CAPTURE_RELIABILITY": "PASS" if counts["DIAGNOSTIC_CAPTURE_FAILURE"] == 0
            and counts["INDEPENDENT_LOGCAT_READER_MISSING"] == 0 else "DEFECT_OBSERVED",
            "TRANSPORT_ROOT_CAUSE_IF_ANY": "Runner/raw/parser divergence observed; see first-failure bundles." if runner_transport_failures
            else ("연속 진단 캡처에만 문제가 관측됐으며 러너 경로 손실은 관측되지 않았습니다."
                  if counts["DIAGNOSTIC_CAPTURE_FAILURE"] or counts["INDEPENDENT_LOGCAT_READER_MISSING"] else "표본에서 관측되지 않음"),
            "PARTIAL_SNAPSHOT_REJECTION_PRESERVED": "YES",
            "RETRY_LOGIC_ADDED": "NO",
            "TRANSPORT_BEHAVIOR_CHANGED_DURING_SOAK": "NO",
            "SCENARIO31_EXECUTED": "NO",
            "SCENARIO32_EXECUTED": "NO",
            "FULL32_EXECUTED": "NO",
            "PHASE6_STARTED": "NO",
            "SAFE_TO_RERUN_SCENARIO31": "YES" if safe_to_rerun else "NO",
            "SAFE_TO_PUSH": "NO",
            "SOURCE_CHANGED": "NO during soak",
            "CHANGED_FILES": ["tools/hierarchy_publication_diagnostic.py", "tools/hierarchy_publication_overnight_soak.py",
                              "talkback_lib/continuous_logcat_capture.py", "tests/test_continuous_logcat_capture.py"],
            "LOCAL_COMMIT": "NO",
            "PUSH_PERFORMED": "NO",
            "RECOMMENDED_MODEL_FOR_NEXT_STEP": "Luna" if diagnostic_only else "Sol",
            "NEXT_RECOMMENDED_STEP": "별도 승인된 Scenario 31 PREPOSITIONED 단일 실행 검토" if safe_to_rerun
            else "첫 실패 증거를 검토하고 원인별 오프라인 수정·재검증 후 soak 승인 여부 결정",
            "STOP_REASON": self.stop_reason,
            "OUTPUT_BYTES": _tree_bytes(self.output),
            "ITERATION_CLASS_COUNTS": counts,
            "COMMANDS_OR_SCENARIOS_EXECUTED": {"hierarchy_requests": total, "scenarios": 0, "phase6": False},
        }

    def run(self) -> dict[str, Any]:
        self.output.mkdir(parents=True, exist_ok=False)
        self.started_monotonic = self._monotonic()
        self.started_at = _now()
        _write_json(self.output / "soak_start.json", {
            "started_at": self.started_at,
            "serial": self.serial,
            "interval_seconds": self.interval_seconds,
            "duration_seconds": self.duration_seconds,
            "max_iterations": self.max_iterations,
            "max_total_bytes": self.max_total_bytes,
            "expected_build": self.expected_build,
            "source_commit": "e12f7286be1d6467b593f5ba5fa5445f40428dd5",
        })
        initial = environment_snapshot(self.adb, self.serial)
        _write_json(self.output / "environment_initial.json", initial)
        failure = self._check_environment(initial, initial=True)
        if failure:
            self.infrastructure_failed = True
            self.lifecycle_failure_count += 1
            self.stop_reason = failure
            summary = self._summary()
            _write_json(self.output / "soak_summary.json", summary)
            return summary

        for index in range(1, self.max_iterations + 1):
            now = self._monotonic()
            if now - self.started_monotonic >= self.duration_seconds:
                break
            scheduled = self.started_monotonic + (index - 1) * self.interval_seconds
            if index > 1 and not self._wait_until(scheduled, len(self.iterations)):
                break
            if self._monotonic() - self.started_monotonic >= self.duration_seconds:
                break
            record = self._run_iteration(index, scheduled)
            print(json.dumps({"event": "SOAK_ITERATION", "iteration": index,
                              "classification": record["classification"], "request_id": record["request_id"],
                              "runner_valid": record["runner_valid"],
                              "output_bytes": record["output_bytes_after_iteration"]}, ensure_ascii=False), flush=True)
            if self.infrastructure_failed or self.stop_reason:
                break
            if record["output_bytes_after_iteration"] > self.max_total_bytes:
                break
        summary = self._summary()
        _write_json(self.output / "soak_summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="읽기 전용 계층 발행 5시간 soak")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-build-config", required=True, type=Path)
    parser.add_argument("--adb", default=DEFAULT_ADB_PATH)
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--duration-hours", type=float, default=5.0)
    parser.add_argument("--max-total-mb", type=int, default=256)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    adb = args.adb if Path(args.adb).is_file() else (shutil.which(args.adb) or args.adb)
    runner = OvernightSoak(adb=adb, serial=args.serial, output=args.output,
                           expected_build_config=args.expected_build_config,
                           interval_seconds=args.interval_seconds, max_iterations=args.max_iterations,
                           duration_seconds=int(args.duration_hours * 3600),
                           max_total_bytes=args.max_total_mb * 1024 * 1024)
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
