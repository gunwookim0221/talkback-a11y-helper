from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
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

from talkback_lib.constants import DEFAULT_ADB_PATH, DEFAULT_PACKAGE_NAME
from talkback_lib.hierarchy_publication_evidence import (
    PublicationEvidenceError,
    compare_publication_layers,
    decode_broadcast_stdout,
    hierarchy_frame_messages,
    parse_hierarchy_capture,
    validate_page,
)
from talkback_lib import A11yAdbClient
from talkback_lib.continuous_logcat_capture import ContinuousLogcatCapture

ACTION_REPORT = "com.iotpart.sqe.talkbackhelper.GET_HIERARCHY_PUBLICATION_REPORT"
ACTION_DUMP = "com.iotpart.sqe.talkbackhelper.DUMP_HIERARCHY"
RECEIVER = "com.iotpart.sqe.talkbackhelper/.A11yCommandReceiver"
MAX_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_CONTINUOUS_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_DIAGNOSTIC_SECONDS = 180.0
MAX_QUERY_SECONDS = 5.0
EXPECTED_BUILD_FIELDS = ("HELPER_BUILD_ID", "HELPER_GIT_COMMIT", "HELPER_INPUT_DIGEST", "HELPER_SOURCE_STATE")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(
    args: list[str],
    *,
    timeout: float,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    on_poll: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    try:
        if on_poll is None:
            completed = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                       timeout=timeout, check=False)
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            returncode = completed.returncode
        else:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic() + timeout
            timed_out = False
            while process.poll() is None:
                on_poll()
                if time.monotonic() >= deadline:
                    timed_out = True
                    process.terminate()
                    break
                time.sleep(0.05)
            try:
                stdout_bytes, stderr_bytes = process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout_bytes, stderr_bytes = process.communicate()
                timed_out = True
            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            returncode = -1 if timed_out else int(process.returncode or 0)
    except subprocess.TimeoutExpired as exc:
        stdout_value = exc.stdout or ""
        stderr_value = exc.stderr or ""
        stdout = stdout_value.decode("utf-8", errors="replace") if isinstance(stdout_value, bytes) else str(stdout_value)
        stderr = stderr_value.decode("utf-8", errors="replace") if isinstance(stderr_value, bytes) else str(stderr_value)
        returncode = -1
    if stdout_path is not None:
        stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    if stderr_path is not None:
        stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
    return {
        "args": args,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_bytes": len(stdout.encode("utf-8")),
        "stderr_bytes": len(stderr.encode("utf-8")),
    }


def _read_expected_build_config(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    result: dict[str, str] = {}
    for key in EXPECTED_BUILD_FIELDS:
        match = re.search(rf'public static final String {key} = "([^"]*)";', text)
        if not match:
            raise RuntimeError(f"build_config_field_missing:{key}")
        result[key] = match.group(1)
    return result


def _nonce() -> str:
    return secrets.token_hex(8)


class OneShotDiagnostic:
    def __init__(self, adb: str, serial: str, output: Path, expected_build: dict[str, str]) -> None:
        self.adb = adb
        self.serial = serial
        self.output = output
        self.expected_build = expected_build
        self.started = time.monotonic()
        self.commands: list[dict[str, Any]] = []
        self.query_count = 0
        self.hierarchy_request_count = 0
        self.request_id = f"hpub-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(6)}"
        self.capabilities: dict[str, Any] = {}
        self.summary: dict[str, Any] = {}
        self.plan_rows: list[dict[str, Any]] = []
        self.attempt_rows: list[dict[str, Any]] = []
        self.continuous_lines: list[str] = []
        self.continuous_raw = ""
        self.capture_metadata: dict[str, Any] = {}
        self.capture: ContinuousLogcatCapture | None = None
        self.runner_raw = ""
        self.runner_parser: dict[str, Any] = {"accepted": False, "reason": "not_captured"}
        self.precheck: dict[str, Any] = {}
        self.stop_reason: str | None = None
        self.capture_incomplete: bool = False
        self.stream_bytes = 0
        self.stream_error = ""

    def _command(
        self,
        name: str,
        args: list[str],
        timeout: float,
        *,
        on_poll: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        index = len(self.commands) + 1
        base = self.output / "commands" / f"{index:02d}_{name}"
        base.parent.mkdir(parents=True, exist_ok=True)
        result = _run(args, timeout=timeout, stdout_path=base.with_suffix(".stdout.txt"),
                      stderr_path=base.with_suffix(".stderr.txt"), on_poll=on_poll)
        row = {key: value for key, value in result.items() if key not in {"stdout", "stderr"}}
        row.update({"name": name, "stdout_file": str(base.with_suffix(".stdout.txt")),
                    "stderr_file": str(base.with_suffix(".stderr.txt"))})
        self.commands.append(row)
        return result

    def _adb_command(self, *parts: str, timeout: float = 10.0) -> dict[str, Any]:
        return self._command(f"adb_{len(self.commands) + 1}", [self.adb, "-s", self.serial, *parts], timeout)

    def _query(self, mode: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        if time.monotonic() - self.started > MAX_DIAGNOSTIC_SECONDS:
            raise PublicationEvidenceError("diagnostic_wall_limit")
        self.query_count += 1
        if self.query_count > 22:
            raise PublicationEvidenceError("query_count_limit")
        nonce = _nonce()
        args = [
            self.adb, "-s", self.serial, "shell", "am", "broadcast",
            "-a", ACTION_REPORT, "-n", RECEIVER,
            "--es", "mode", mode, "--es", "query_nonce", nonce,
        ]
        for key, value in (extra or {}).items():
            if isinstance(value, bool):
                args.extend(["--ez", key, "true" if value else "false"])
            elif isinstance(value, int):
                args.extend(["--el" if key.endswith("_ns") or key == "capture_generation" else "--ei", key, str(value)])
            elif value is not None:
                args.extend(["--es", key, str(value)])
        result = self._command(f"publication_query_{mode.lower()}_{self.query_count:02d}", args, MAX_QUERY_SECONDS)
        decoded = decode_broadcast_stdout(
            result["stdout"], returncode=result["returncode"], expected_nonce=nonce
        )
        decoded["_query_nonce"] = nonce
        return decoded

    def _device_precheck(self) -> None:
        state = self._adb_command("get-state")
        if state["returncode"] != 0 or state["stdout"].strip() != "device":
            raise RuntimeError("device_not_ready")
        services = self._adb_command("shell", "settings", "get", "secure", "enabled_accessibility_services")
        if services["returncode"] != 0 or "com.iotpart.sqe.talkbackhelper" not in services["stdout"].lower():
            raise RuntimeError("helper_accessibility_service_not_enabled")
        self.precheck = {
            "serial": self.serial,
            "device_state": state["stdout"].strip(),
            "enabled_accessibility_services": services["stdout"].strip(),
            "locale": self._adb_command("shell", "getprop", "persist.sys.locale")["stdout"].strip(),
        }

    def _capability_gate(self) -> None:
        self.capabilities = self._query("CAPABILITIES")
        comparisons = {
            "HELPER_BUILD_ID": "build_id",
            "HELPER_GIT_COMMIT": "git_commit",
            "HELPER_INPUT_DIGEST": "input_digest",
            "HELPER_SOURCE_STATE": "source_state",
        }
        for local, remote in comparisons.items():
            if self.capabilities.get(remote) != self.expected_build[local]:
                raise RuntimeError(f"installed_build_identity_mismatch:{remote}")
        if not self.capabilities.get("service_instance_id"):
            raise RuntimeError("helper_service_not_connected")
        if self.capabilities.get("max_requests") != 4 or self.capabilities.get("retention_ms") != 600_000:
            raise RuntimeError("helper_ledger_capabilities_mismatch")

    def _one_hierarchy_request(self) -> dict[str, Any]:
        if self.hierarchy_request_count != 0:
            raise RuntimeError("hierarchy_request_count_violation")
        capture_dir = self.output / "continuous_capture"
        capture = ContinuousLogcatCapture(
            [self.adb, "-s", self.serial, "logcat", "-v", "raw", "-T", "1", "A11Y_HELPER:I", "*:S"],
            capture_dir / "raw_stdout.bin",
            capture_dir / "raw_stderr.bin",
            max_output_bytes=MAX_CONTINUOUS_CAPTURE_BYTES,
            drain_window_seconds=1.0,
        ).start()
        self.capture = capture
        if not capture.mark_request_started():
            self.capture_metadata = capture.finish()
            self._persist_capture_outputs()
            raise RuntimeError("diagnostic_capture_failure_before_request")
        self.hierarchy_request_count += 1
        try:
            result = self._command(
                "single_readonly_hierarchy_broadcast",
                [
                    self.adb, "-s", self.serial, "shell", "am", "broadcast",
                    "-a", ACTION_DUMP, "-n", RECEIVER,
                    "--es", "reqId", self.request_id,
                    "--ez", "publicationEvidence", "true",
                ],
                35.0,
                on_poll=capture.check_health,
            )
        finally:
            capture.mark_request_completed()
            self.capture_metadata = capture.finish()
            self._persist_capture_outputs()
        if self.capture_metadata.get("capture_failure_reason"):
            self.capture_incomplete = True
        self.stream_bytes = int(self.capture_metadata.get("stdout_bytes", 0))
        self.stream_error = str(self.capture_metadata.get("capture_failure_reason") or "")
        raw_bytes = capture.stdout_path.read_bytes() if capture.stdout_path.exists() else b""
        if len(raw_bytes) > MAX_CONTINUOUS_CAPTURE_BYTES:
            self.capture_incomplete = True
            raise PublicationEvidenceError("continuous_raw_capture_limit")
        self.continuous_raw = raw_bytes.decode("utf-8", errors="replace")
        self.continuous_lines = hierarchy_frame_messages(self.continuous_raw, self.request_id)
        return {key: value for key, value in result.items() if key not in {"stdout", "stderr"}}

    def _persist_capture_outputs(self) -> None:
        capture_dir = self.output / "continuous_capture"
        capture_dir.mkdir(parents=True, exist_ok=True)
        _write_json(capture_dir / "capture_metadata.json", self.capture_metadata)

    def _capture_runner_raw_once(self) -> None:
        client = A11yAdbClient(adb_path=self.adb, package_name=DEFAULT_PACKAGE_NAME,
                               dev_serial=self.serial, start_monitor=False)
        self.runner_raw = client._logcat_reader.dump_raw_filtered(dev=self.serial)
        raw_bytes = self.runner_raw.encode("utf-8", errors="replace")
        runner_raw_path = self.output / "runner_raw_logcat_poll.txt"
        if len(raw_bytes) > MAX_CAPTURE_BYTES:
            runner_raw_path.write_bytes(raw_bytes[:MAX_CAPTURE_BYTES])
            _write_json(self.output / "runner_raw_capture_limit.json", {
                "truncated": True,
                "observed_bytes": len(raw_bytes),
                "preserved_prefix_bytes": MAX_CAPTURE_BYTES,
                "full_observation_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "limit_bytes": MAX_CAPTURE_BYTES,
            })
            self.runner_raw = ""
            self.capture_incomplete = True
            raise PublicationEvidenceError("runner_raw_capture_limit")
        runner_raw_path.write_bytes(raw_bytes)
        self.runner_parser = parse_hierarchy_capture(self.runner_raw, self.request_id)

    def _collect_report(self) -> None:
        self.summary = self._query("SUMMARY", {
            "request_id": self.request_id,
            "expected_process_epoch": self.capabilities["process_epoch"],
            "expected_service_instance_id": self.capabilities.get("service_instance_id") or "",
        })
        if self.summary.get("request_id") != self.request_id:
            raise PublicationEvidenceError("summary_request_mismatch")
        if self.summary.get("process_epoch") != self.capabilities.get("process_epoch"):
            raise PublicationEvidenceError("summary_process_epoch_mismatch")
        if self.summary.get("service_instance_id") != self.capabilities.get("service_instance_id"):
            raise PublicationEvidenceError("summary_service_epoch_mismatch")
        plan_pages = int(self.summary.get("plan_page_count", 0))
        attempt_pages = int(self.summary.get("attempt_page_count", 0))
        if plan_pages > 10 or attempt_pages > 10:
            raise PublicationEvidenceError("page_count_limit")
        for kind, count, sink in (
            ("PLAN", plan_pages, self.plan_rows),
            ("ATTEMPTS", attempt_pages, self.attempt_rows),
        ):
            for page_index in range(count):
                page = self._query(kind, {
                    "request_id": self.request_id,
                    "expected_process_epoch": self.capabilities["process_epoch"],
                    "expected_service_instance_id": self.capabilities.get("service_instance_id") or "",
                    "capture_generation": int(self.summary["capture_generation"]),
                    "report_revision": int(self.summary["report_revision"]),
                    "report_digest": self.summary["report_digest"],
                    "page_index": page_index,
                })
                rows = validate_page(
                    page,
                    request_id=self.request_id,
                    process_epoch=str(self.capabilities["process_epoch"]),
                    service_instance_id=self.capabilities.get("service_instance_id"),
                    capture_generation=int(self.summary["capture_generation"]),
                    report_revision=int(self.summary["report_revision"]),
                    report_digest=str(self.summary["report_digest"]),
                    page_kind=kind,
                    page_index=page_index,
                    page_count=count,
                )
                sink.extend(rows)
        if len(self.plan_rows) != int(self.summary.get("descriptor_count", -1)):
            raise PublicationEvidenceError("descriptor_count_mismatch")
        if len(self.attempt_rows) != int(self.summary.get("attempt_count", -1)):
            raise PublicationEvidenceError("attempt_count_mismatch")

    def run(self) -> dict[str, Any]:
        self.output.mkdir(parents=True, exist_ok=True)
        self._device_precheck()
        self._capability_gate()
        dump_broadcast = self._one_hierarchy_request()
        try:
            self._capture_runner_raw_once()
        except Exception as exc:
            self.stop_reason = f"{type(exc).__name__}:{exc}"
            self.capture_incomplete = True
            self.runner_parser = {"accepted": False, "reason": "runner_raw_unavailable"}
        raw_continuous = self.continuous_raw
        filtered_frames = "\n".join(self.continuous_lines)
        (self.output / "raw_continuous_hierarchy_frames.log").write_text(
            filtered_frames + ("\n" if filtered_frames else ""), encoding="utf-8"
        )
        try:
            self._collect_report()
            comparison = compare_publication_layers(
                self.summary,
                self.plan_rows,
                self.attempt_rows,
                raw_continuous,
                self.runner_raw,
                self.runner_parser,
                self.request_id,
            )
        except Exception as exc:
            self.stop_reason = f"{type(exc).__name__}:{exc}"
            comparison = {
                "primary_loss_layer": "H. EVIDENCE_INCOMPLETE",
                "summary_complete": False,
                "request_id": self.request_id,
                "expected_chunk_count": self.summary.get("expected_chunk_count"),
                "helper_attempted_frame_count": None,
                "helper_log_api_success_count": None,
                "raw_logcat_observed_frame_count": None,
                "runner_observed_frame_count": None,
                "parser_accepted_frame_count": None,
                "end": None,
                "chunk61": {"expected": None, "constructed": None},
                "parser_result": self.runner_parser,
                "missing_frame_matrix": [],
                "error": self.stop_reason,
                "api_success_proves_logd_delivery": False,
                "api_success_proves_host_delivery": False,
            }
        _write_json(self.output / "helper_publication_report.json", {
            "request_id": self.request_id,
            "capabilities": self.capabilities,
            "summary": self.summary,
            "plan_rows": self.plan_rows,
            "attempt_rows": self.attempt_rows,
        })
        _write_json(self.output / "comparison.json", comparison)
        final = {
            "diagnostic_status": comparison["primary_loss_layer"],
            "request_id": self.request_id,
            "hierarchy_request_count": self.hierarchy_request_count,
            "ordered_report_query_count": self.query_count,
            "device_precheck": self.precheck,
            "capabilities": self.capabilities,
            "summary": self.summary,
            "dump_broadcast": dump_broadcast,
            "raw_continuous_frame_count": len(self.continuous_lines),
            "raw_continuous_bytes": self.stream_bytes,
            "raw_stream_reader_error": self.stream_error or None,
            "raw_capture_incomplete": self.capture_incomplete,
            "continuous_capture": self.capture_metadata,
            "runner_raw_bytes": len(self.runner_raw.encode("utf-8", errors="replace")),
            "runner_parser": self.runner_parser,
            "comparison": comparison,
            "source_changed_by_script": False,
            "scenario_execution_count": 0,
            "phase6_started": False,
            "push_performed": False,
            "safe_for_scenario31_rerun": False,
            "wall_seconds": round(time.monotonic() - self.started, 3),
            "stop_reason": self.stop_reason,
            "commands": self.commands,
        }
        _write_json(self.output / "diagnostic_result.json", final)
        return final


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="한 번의 읽기 전용 Helper 계층 발행 진단")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-build-config", required=True, type=Path)
    parser.add_argument("--adb", default=DEFAULT_ADB_PATH)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    adb = args.adb if Path(args.adb).is_file() else (shutil.which(args.adb) or args.adb)
    diagnostic: OneShotDiagnostic | None = None
    try:
        expected = _read_expected_build_config(args.expected_build_config)
        diagnostic = OneShotDiagnostic(adb, args.serial, args.output, expected)
        result = diagnostic.run()
        print(json.dumps({
            "diagnostic_status": result["diagnostic_status"],
            "request_id": result["request_id"],
            "hierarchy_request_count": result["hierarchy_request_count"],
            "ordered_report_query_count": result["ordered_report_query_count"],
            "safe_for_scenario31_rerun": result["safe_for_scenario31_rerun"],
            "artifact_dir": str(args.output.resolve()),
        }, ensure_ascii=False, indent=2))
        return 0 if result["diagnostic_status"].startswith("G.") else 2
    except Exception as exc:
        if diagnostic is not None:
            _write_json(args.output / "early_failure.json", {
                "diagnostic_status": "H. EVIDENCE_INCOMPLETE",
                "error": f"{type(exc).__name__}:{exc}",
                "hierarchy_request_count": diagnostic.hierarchy_request_count,
                "ordered_report_query_count": diagnostic.query_count,
                "device_precheck": diagnostic.precheck,
                "capabilities": diagnostic.capabilities,
                "continuous_capture": diagnostic.capture_metadata,
                "commands": diagnostic.commands,
                "scenario_execution_count": 0,
            })
        print(json.dumps({"diagnostic_status": "H. EVIDENCE_INCOMPLETE", "error": f"{type(exc).__name__}:{exc}",
                          "hierarchy_request_count": diagnostic.hierarchy_request_count if diagnostic else 0,
                          "ordered_report_query_count": diagnostic.query_count if diagnostic else 0,
                          "scenario_execution_count": 0},
                         ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
