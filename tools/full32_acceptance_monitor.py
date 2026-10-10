"""Fresh, process-aware predicates used by the monitored Korean Full32 run.

This module deliberately consumes only newly tailed lines.  Callers should
record file offsets and a UTC start time before launching a batch, then pass
only bytes appended after those offsets to this monitor.
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


TALKBACK_PACKAGE = "com.samsung.android.accessibility.talkback"
HELPER_PACKAGE = "com.iotpart.sqe.talkbackhelper"

_ISO_TS = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})\b")
_PROCESS_PID = re.compile(r"\bProcess:\s*([A-Za-z0-9_.]+)\s*,\s*PID:\s*(\d+)\b", re.I)
_PACKAGE_FIELD = re.compile(r"\bpackage\s*[:=]\s*([A-Za-z0-9_.]+)", re.I)
_PID_FIELD = re.compile(r"\b(?:target_)?pid\s*[:=]\s*(\d+)\b", re.I)
_REQUEST_ID = re.compile(r"\b(?:req_?id|request_?id|correlation_?id)['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_.:-]+)", re.I)
_SCENARIO_FIELD = re.compile(r"\bscenario(?:_id)?\s*[:=]\s*['\"]?([A-Za-z0-9_.:-]+)", re.I)
_SCENARIO_STATUS_FIELD = re.compile(
    r"\b(?:termination_status|termination|scenario_result_status|scenario_status|status)\s*[:=]\s*"
    r"(?:'([^']*)'|\"([^\"]*)\"|([A-Za-z0-9_.:-]+))",
    re.I,
)
_SCENARIO_REASON_FIELD = re.compile(
    r"\b(?:termination_reason|reason)\s*[:=]\s*(?:'([^']*)'|\"([^\"]*)\"|([A-Za-z0-9_.:-]+))",
    re.I,
)
_HELPER_ACTION = re.compile(r"\baction\s*[:=]\s*" + re.escape(HELPER_PACKAGE) + r"\.(SMART_NEXT|FOCUS_IN_BOUNDS|TARGET_FOCUS_COMMIT)\b")
_LOGCAT_HEADER = re.compile(r"^\s*\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+(\d+)\s+\d+\s+[VDIWEF]\s+([^:]+):")
_LOGCAT_LOCAL_TS = re.compile(r"^\s*(\d{2})-(\d{2})\s+(\d{2}:\d{2}:\d{2}\.\d+)")


@dataclass(frozen=True)
class MonitorHit:
    code: str
    evidence: str
    event_timestamp: str | None = None


@dataclass
class HelperRequest:
    request_id: str
    command: str
    origin_package: str
    origin_pid: str
    start_timestamp: datetime
    terminal_status: str | None = None
    terminal_timestamp: datetime | None = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _line_timestamp(line: str, start: datetime) -> datetime | None:
    match = _ISO_TS.search(line)
    if match:
        raw = match.group(0).replace("Z", "+00:00")
        try:
            return _as_utc(datetime.fromisoformat(raw))
        except ValueError:
            return None
    match = _LOGCAT_LOCAL_TS.search(line)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        try:
            local = datetime.strptime(match.group(3), "%H:%M:%S.%f").replace(
                year=start.astimezone(timezone(timedelta(hours=9))).year,
                month=month,
                day=day,
                tzinfo=timezone(timedelta(hours=9)),
            )
            # Android logcat timestamps are device-local.  Handle New Year
            # rollover by selecting the year nearest the monitor start.
            start_local = start.astimezone(timezone(timedelta(hours=9)))
            if local - start_local > timedelta(days=180):
                local = local.replace(year=local.year - 1)
            elif start_local - local > timedelta(days=180):
                local = local.replace(year=local.year + 1)
            return local.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _identity(lines: Iterable[str]) -> tuple[str | None, str | None]:
    text = "\n".join(lines)
    package = None
    pid = None
    process_match = _PROCESS_PID.search(text)
    if process_match:
        package, pid = process_match.group(1), process_match.group(2)
    else:
        package_match = _PACKAGE_FIELD.search(text)
        pid_match = _PID_FIELD.search(text)
        if package_match:
            package = package_match.group(1)
        if pid_match:
            pid = pid_match.group(1)
    return package, pid


class AcceptanceMonitor:
    """Classify fresh monitor input into hard-stop events.

    Timestamped records older than ``started_at`` are always ignored.  For
    records without a timestamp, the caller must guarantee freshness by
    passing only data appended after the recorded file offset.
    """

    def __init__(
        self,
        started_at: datetime,
        *,
        talkback_pid: str | None,
        helper_pid: str | None,
    ) -> None:
        self.started_at = _as_utc(started_at)
        self.talkback_pid = str(talkback_pid) if talkback_pid else None
        self.helper_pid = str(helper_pid) if helper_pid else None
        self._context: dict[str, deque[str]] = {
            "runner": deque(maxlen=40),
            "logcat": deque(maxlen=40),
        }
        self._context_pid: dict[str, str | None] = {"runner": None, "logcat": None}
        self._last_overlay_count = 0
        self._requests: dict[str, HelperRequest] = {}
        self._request_ttl = timedelta(minutes=5)
        self._request_limit = 512
        self._api_terminal_failures: set[str] = set()

    @staticmethod
    def _field_value(pattern: re.Pattern[str], line: str) -> str:
        match = pattern.search(line)
        if not match:
            return ""
        return next((value for value in match.groups() if value is not None), "").strip()

    def _scenario_result_hit(self, line: str, event_timestamp: str | None) -> MonitorHit | None:
        """Recognize only terminal scenario records and explicit failed statuses."""
        contract_summary = "[PERF][scenario_contract_summary]" in line
        traversal_summary = "[TRAVERSAL_SUMMARY]" in line
        explicit_result = bool(re.search(
            r"(?:\[SCENARIO_RESULT\]|\[SCENARIO\]\[(?:terminal|result)\])",
            line,
            re.I,
        ))
        scenario_match = _SCENARIO_FIELD.search(line)
        scenario_id = scenario_match.group(1) if scenario_match else "unknown"
        status = self._field_value(_SCENARIO_STATUS_FIELD, line).strip().lower()
        reason = self._field_value(_SCENARIO_REASON_FIELD, line).strip().lower()

        if contract_summary or traversal_summary:
            terminal_status = status == "incomplete_error"
            normalized_reason = re.sub(r"[\s-]+", "_", reason)
            hard_automation_reason = bool(re.search(
                r"(?:tab_or_anchor_failed|anchor_abort|entry_(?:failure|failed|error)|"
                r"unresolved_automation_failure|automation_failure)",
                normalized_reason,
            ))
            if terminal_status and hard_automation_reason:
                return MonitorHit(
                    "scenario_result_hard_failure",
                    f"scenario={scenario_id} termination_status=INCOMPLETE_ERROR reason={reason}",
                    event_timestamp,
                )
            # A parser-classified failed scenario is also an explicit terminal
            # hard stop, while warning and accepted incomplete states continue.
            if status == "failed":
                return MonitorHit(
                    "scenario_result_hard_failure",
                    f"scenario={scenario_id} status=failed reason={reason or 'explicit_failed_status'}",
                    event_timestamp,
                )

        if explicit_result and status == "failed":
            return MonitorHit(
                "scenario_result_hard_failure",
                f"scenario={scenario_id} status=failed reason={reason or 'explicit_failed_status'}",
                event_timestamp,
            )

        if line.lstrip().startswith("{"):
            try:
                event = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                event = None
            if isinstance(event, dict):
                event_type = str(event.get("event_type") or event.get("event") or event.get("type") or "").lower()
                result_status = str(event.get("scenario_status") or event.get("status") or "").lower()
                if event_type in {"scenario_result", "scenario_terminal", "scenario_terminal_result"} and result_status == "failed":
                    event_scenario = str(event.get("scenario_id") or event.get("scenario") or "unknown")
                    event_reason = str(event.get("reason") or "explicit_failed_status")
                    return MonitorHit(
                        "scenario_result_hard_failure",
                        f"scenario={event_scenario} status=failed reason={event_reason}",
                        event_timestamp,
                    )
        return None

    def observe_scenario_failure_count(
        self,
        status: dict,
        *,
        observed_at: datetime,
    ) -> list[MonitorHit]:
        """Use only API failures backed by a terminal scenario contract."""
        observed_at = _as_utc(observed_at)
        if observed_at < self.started_at or not isinstance(status, dict):
            return []
        progress = status.get("progress")
        if not isinstance(progress, dict):
            return []
        try:
            failed_count = max(0, int(progress.get("failed_scenarios") or 0))
        except (TypeError, ValueError):
            return []
        if failed_count <= 0:
            return []
        scenario_progress = progress.get("scenario_progress")
        if not isinstance(scenario_progress, list):
            return []

        hits: list[MonitorHit] = []
        for item in scenario_progress:
            if not isinstance(item, dict) or str(item.get("status") or "").lower() != "failed":
                continue
            scenario_id = str(item.get("id") or item.get("scenario_id") or "unknown")
            # The live parser can temporarily call an entered, still-running
            # scenario "failed" before its summary exists. execution_status is
            # populated only from a terminal scenario-contract summary.
            execution_status = str(item.get("execution_status") or "").strip()
            if not execution_status or scenario_id in self._api_terminal_failures:
                continue
            self._api_terminal_failures.add(scenario_id)
            comparison_status = str(item.get("comparison_status") or "").strip()
            hits.append(MonitorHit(
                "scenario_result_hard_failure",
                f"batch API terminal scenario={scenario_id} execution_status={execution_status}"
                + (f" comparison_status={comparison_status}" if comparison_status else ""),
                observed_at.isoformat(),
            ))
        return hits

    def _request_hits(self, line: str, now: datetime) -> list[MonitorHit]:
        """Correlate live runner command ownership with its terminal result."""
        for request_id, entry in list(self._requests.items()):
            if now - entry.start_timestamp > self._request_ttl:
                del self._requests[request_id]
        request = _REQUEST_ID.search(line)
        if not request:
            return []
        request_id = request.group(1)
        action = _HELPER_ACTION.search(line)
        package, pid = _identity([line])
        if (
            re.search(r"\[(?:SMART_NEXT_TRACE|FOCUS_TRANSPORT)\]\s+before_broadcast\b", line)
            and action and self.helper_pid and (pid is None or pid == self.helper_pid)
        ):
            self._requests[request_id] = HelperRequest(
                request_id, action.group(1), HELPER_PACKAGE, pid or self.helper_pid, now,
            )
            while len(self._requests) > self._request_limit:
                del self._requests[next(iter(self._requests))]
            return []
        # Keep the existing explicit, process-attributed timeout contract.
        if (
            "[HELPER_COMMAND_TIMEOUT]" in line and self.helper_pid
            and (package == HELPER_PACKAGE or pid == self.helper_pid)
            and (pid is None or pid == self.helper_pid)
            and re.search(r"\baction\s*[:=]\s*SMART_NEXT\b", line)
        ):
            return [MonitorHit("smart_next_timeout", f"SMART_NEXT timeout request_id={request_id}", now.isoformat())]
        entry = self._requests.get(request_id)
        if entry is None or entry.origin_pid != self.helper_pid or now < entry.start_timestamp:
            return []
        # Late responses to retired requests are informational, not new errors.
        if re.search(r"\blate_result\b|\bignored=true\b", line):
            return []
        terminal = bool(re.search(
            r"\[(?:SMART_NEXT_(?:TRACE|TRANSPORT)|FOCUS_TRANSPORT)\].*\b"
            r"(?:completed|delivery_failed|read_log_result_miss|read_log_result_match|parsed_broadcast_result)\b", line,
        ))
        if not terminal:
            return []
        transport_error = bool(re.search(r"\bstatus['\"]?\s*[:=]\s*['\"]?transport_error\b", line))
        timeout = bool(re.search(r"\breason['\"]?\s*[:=]\s*['\"]?(?:smart_nav_result_wait_timeout|focus_result_wait_timeout)\b", line))
        entry.terminal_status = "transport_error" if transport_error or timeout else "result_received"
        entry.terminal_timestamp = now
        del self._requests[request_id]
        if not (transport_error or timeout):
            return []
        code = "smart_next_timeout" if entry.command == "SMART_NEXT" and timeout else (
            "smart_next_transport_error" if entry.command == "SMART_NEXT" else "focus_transport_error"
        )
        return [MonitorHit(code, f"{entry.command} correlated {entry.terminal_status} request_id={request_id} package={entry.origin_package} pid={entry.origin_pid}", now.isoformat())]

    def _fresh(self, line: str) -> bool:
        timestamp = _line_timestamp(line, self.started_at)
        return timestamp is None or timestamp >= self.started_at

    def feed_lifecycle(self, raw_line: str) -> list[MonitorHit]:
        if not self._fresh(raw_line):
            return []
        try:
            event = json.loads(raw_line)
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(event, dict):
            return []

        hits: list[MonitorHit] = []
        current = event.get("talkback_pid")
        previous = event.get("previous_talkback_pid")
        current = str(current) if current not in (None, "") else None
        previous = str(previous) if previous not in (None, "") else None
        explicit_restart = event.get("talkback_restart_detected") is True
        pid_changed = bool(current and self.talkback_pid and current != self.talkback_pid)
        previous_current_changed = bool(previous and current and previous != current)
        if current and (pid_changed or previous_current_changed):
            hits.append(MonitorHit("talkback_pid_change", f"TalkBack PID {self.talkback_pid or previous} -> {current}", event.get("timestamp")))
        elif explicit_restart and current and previous and current != previous:
            hits.append(MonitorHit("talkback_restart", f"explicit restart {previous} -> {current}", event.get("timestamp")))
        if current:
            self.talkback_pid = current

        try:
            overlay_count = int(event.get("search_screen_overlay_window_count") or 0)
        except (TypeError, ValueError):
            overlay_count = 0
        if overlay_count > 1:
            hits.append(MonitorHit("search_overlay_accumulation", f"search overlay window count={overlay_count}", event.get("timestamp")))
        self._last_overlay_count = overlay_count
        return hits

    def observe_talkback_pid(self, pid: str | None, *, observed_at: datetime) -> list[MonitorHit]:
        """Compare a fresh package-specific `pidof` observation to baseline."""
        observed_at = _as_utc(observed_at)
        value = str(pid) if pid not in (None, "") else None
        if observed_at < self.started_at or not value:
            return []
        if self.talkback_pid and value != self.talkback_pid:
            previous = self.talkback_pid
            self.talkback_pid = value
            return [MonitorHit("talkback_pid_change", f"{TALKBACK_PACKAGE} pidof {previous} -> {value}", observed_at.isoformat())]
        if value:
            self.talkback_pid = value
        return []

    def feed_line(self, raw_line: str, *, source: str, observed_at: datetime | None = None) -> list[MonitorHit]:
        """Consume one fresh runner or logcat line and return any hard stops."""
        if source not in self._context:
            raise ValueError("source must be 'runner' or 'logcat'")
        if not self._fresh(raw_line):
            return []
        context = self._context[source]
        latest = raw_line.strip()
        header = _LOGCAT_HEADER.match(latest) if source == "logcat" else None
        source_pid = header.group(1) if header else None
        if source_pid and self._context_pid[source] and source_pid != self._context_pid[source]:
            context.clear()
        if source_pid:
            self._context_pid[source] = source_pid
        context.append(latest)
        lines = list(context)
        block = "\n".join(lines)
        hits: list[MonitorHit] = []
        event_time = _line_timestamp(raw_line, self.started_at)
        event_timestamp = event_time.isoformat() if event_time else None

        latest_package, latest_pid = _identity([latest])
        tag = header.group(2).strip() if header else ""

        # Helper ANR requires the exact Helper package and ActivityManager
        # attribution.  The target PID is either explicit in the record or
        # supplied by the process-aware device baseline.
        helper_anr = (
            re.search(r"\bActivityManager\b[^\n]*\bANR in\s+" + re.escape(HELPER_PACKAGE) + r"\b", latest, re.I)
            or re.search(r"\[HELPER_ANR\].*\b" + re.escape(HELPER_PACKAGE) + r"\b", latest, re.I)
        )
        if helper_anr and (latest_pid == self.helper_pid or (latest_pid is None and self.helper_pid is not None)):
            hits.append(MonitorHit("helper_anr", f"ActivityManager ANR in {HELPER_PACKAGE} pid={latest_pid or self.helper_pid}", event_timestamp))

        fatal_start = max(
            (index for index, line in enumerate(lines) if re.search(r"\bFATAL EXCEPTION\b|\bApplicationExitInfo\b", line, re.I)),
            default=0,
        )
        fatal_lines = lines[fatal_start:]
        fatal_block = "\n".join(fatal_lines)
        fatal_package, fatal_pid = _identity(fatal_lines)
        fatal_marker = bool(re.search(r"\bFATAL EXCEPTION\b|\bApplicationExitInfo\b.{0,100}\b(?:CRASH|REASON_CRASH)\b", fatal_block, re.I))
        fatal_throwable = bool(re.search(r"\b[A-Za-z0-9_$.]+(?:Exception|Error)\b", latest))
        application_exit = bool(re.search(r"\bApplicationExitInfo\b.{0,100}\b(?:CRASH|REASON_CRASH)\b", latest, re.I))
        if (
            fatal_package == HELPER_PACKAGE and fatal_pid == self.helper_pid and
            fatal_marker and (fatal_throwable or application_exit)
        ):
            hits.append(MonitorHit("helper_crash", f"AndroidRuntime fatal for {HELPER_PACKAGE} pid={fatal_pid}", event_timestamp))

        # A TalkBack fatal must identify both the TalkBack package and target
        # PID.  A BadToken is only fatal once an actual PID transition is
        # observed; caught exceptions from a live process are ignored.
        talkback_identity = (
            fatal_package == TALKBACK_PACKAGE and fatal_pid is not None and
            (self.talkback_pid is None or fatal_pid == self.talkback_pid)
        ) or (
            source == "logcat" and source_pid is not None and
            source_pid == self.talkback_pid and bool(re.search(r"\bAndroidRuntime\b", tag, re.I)) and
            TALKBACK_PACKAGE in fatal_block
        )
        badtoken = bool(re.search(r"\bBadTokenException\b", fatal_block, re.I))
        if talkback_identity and fatal_marker and (fatal_throwable or application_exit) and not badtoken:
            hits.append(MonitorHit("talkback_fatal", f"AndroidRuntime fatal for {TALKBACK_PACKAGE} pid={fatal_pid or source_pid}", event_timestamp))

        # This framework message is meaningful only when emitted by the
        # observed TalkBack process or explicitly attributed to its package.
        if re.search(r"window count is over max!!", latest, re.I):
            attributed = (
                latest_package == TALKBACK_PACKAGE and latest_pid is not None and
                (self.talkback_pid is None or latest_pid == self.talkback_pid)
            ) or (source == "logcat" and source_pid is not None and source_pid == self.talkback_pid)
            if attributed:
                hits.append(MonitorHit("talkback_window_fatal", f"TalkBack window limit marker pid={latest_pid or source_pid}", event_timestamp))

        if source == "runner":
            arrival = _as_utc(observed_at or datetime.now(timezone.utc))
            if arrival >= self.started_at:
                hits.extend(self._request_hits(latest, event_time or arrival))
                scenario_hit = self._scenario_result_hit(latest, event_timestamp)
                if scenario_hit is not None:
                    hits.append(scenario_hit)

        # Other transport/integrity stops require explicit event markers and
        # request/correlation IDs.  Informational prose cannot satisfy them.
        explicit_request_error = _REQUEST_ID.search(latest) is not None
        if source == "runner" and re.search(r"\[ADB_COMMAND_TIMEOUT\]", latest, re.I) and explicit_request_error and re.search(r"\bcommand\s*[:=]", latest, re.I):
            hits.append(MonitorHit("adb_timeout", latest, event_timestamp))
        if source == "runner" and re.search(r"\[(?:MISSING_CORRELATED_RESULT|RESULT_CORRELATION_ERROR)\]", latest, re.I) and explicit_request_error:
            hits.append(MonitorHit("missing_correlated_result", latest, event_timestamp))
        if source == "runner" and re.search(r"\[CHUNK_REASSEMBLY_FAILURE\]", latest, re.I) and explicit_request_error:
            hits.append(MonitorHit("chunk_corruption", latest, event_timestamp))
        if source == "runner" and re.search(r"\[(?:TARGET_LEDGER|DIAGNOSTIC)\].*\b(?:MISMATCH|CORRUPT)\b", latest, re.I) and explicit_request_error:
            hits.append(MonitorHit("ledger_or_diagnostic_corruption", latest, event_timestamp))
        if source == "runner" and re.search(r"\[INSPECTION_SUPPRESSION\].*\bactive\s*[:=]\s*true\b", latest, re.I):
            hits.append(MonitorHit("old_suppressing_dump", latest, event_timestamp))
        if source == "runner" and re.search(r"\[INSPECTION_RECONNECT\].*\binduced\s*[:=]\s*true\b", latest, re.I):
            hits.append(MonitorHit("inspection_reconnect", latest, event_timestamp))
        if source == "runner" and re.search(r"\[CANDIDATE_PROVENANCE\].*\bdirty\s*[:=]\s*true\b", latest, re.I):
            hits.append(MonitorHit("candidate_provenance_failure", latest, event_timestamp))
        return hits


def file_offsets(paths: Iterable[str]) -> dict[str, int]:
    """Capture tail positions before run start so existing content is stale."""
    from pathlib import Path

    result: dict[str, int] = {}
    for value in paths:
        path = Path(value)
        try:
            result[str(path)] = path.stat().st_size
        except OSError:
            result[str(path)] = 0
    return result
