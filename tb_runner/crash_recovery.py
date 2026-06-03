from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from talkback_lib.constants import DEFAULT_ADB_PATH
from tb_runner.accessibility_preflight import HELPER_SERVICE_COMPONENT, ensure_accessibility_service_enabled, run_adb_text
from tb_runner.core_preflight import (
    EXTERNAL_POPUP_PACKAGES,
    SMARTTHINGS_PACKAGE,
    ensure_smartthings_foreground,
    recover_external_popup_contamination,
    unlock_swipe,
    wake_screen,
)

STATE_CRASH_DETECTED = "CRASH_DETECTED"
STATE_ARTIFACT_CAPTURED = "ARTIFACT_CAPTURED"
STATE_RECOVERY_NOT_IMPLEMENTED = "RECOVERY_NOT_IMPLEMENTED"
STATE_CONTINUE_WITHOUT_RETRY = "CONTINUE_WITHOUT_RETRY"

STATE_RELAUNCHING = "RELAUNCHING"
STATE_RECOVERY_PREFLIGHT = "RECOVERY_PREFLIGHT"
STATE_RECOVERY_PREFLIGHT_PASSED = "RECOVERY_PREFLIGHT_PASSED"
STATE_RECOVERY_PREFLIGHT_FAILED = "RECOVERY_PREFLIGHT_FAILED"
STATE_RETRYING_SCENARIO = "RETRYING_SCENARIO"
STATE_CRASH_RECOVERED = "CRASH_RECOVERED"
STATE_CRASH_REPEATED = "CRASH_REPEATED"

CRASH_STOP_REASONS = {"confirmed_crash", "app_terminated", "possible_crash"}
CRASH_TYPES = {"CONFIRMED_CRASH", "APP_TERMINATED", "POSSIBLE_CRASH", "ANR"}
DEFAULT_CRASH_ABORT_THRESHOLD = 5


@dataclass(frozen=True)
class CrashTerminalSignal:
    is_crash_like: bool
    scenario_id: str
    stop_reason: str
    crash_type: str
    crash_event_id: str
    attempt: int = 0
    artifact_dir: str = ""
    recovery_state: str = STATE_CRASH_DETECTED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryDecision:
    signal: CrashTerminalSignal
    decision: str
    retry_count: int
    result: str
    scenario_final_status: str
    next_action: str
    states: tuple[str, ...]
    relaunch_result: str = ""
    preflight_result: str = ""
    failure_reason: str = ""
    helper_status: str = ""
    talkback_status: str = ""
    foreground_status: str = ""
    foreground_package: str = ""

    def to_recovery_payload(self) -> dict[str, Any]:
        payload = {
            "decision": self.decision,
            "retry_count": self.retry_count,
            "result": self.result,
            "scenario_final_status": self.scenario_final_status,
            "next_action": self.next_action,
        }
        if self.relaunch_result:
            payload["relaunch_result"] = self.relaunch_result
        if self.preflight_result:
            payload["preflight_result"] = self.preflight_result
        if self.failure_reason:
            payload["failure_reason"] = self.failure_reason
        return payload


@dataclass(frozen=True)
class RecoveryPreflightResult:
    ok: bool
    reason: str
    relaunch_result: str
    preflight_result: str
    helper_status: str
    talkback_status: str
    foreground_status: str
    foreground_package: str
    wake_screen: dict[str, object]
    unlock_swipe: dict[str, object]
    app_foreground: dict[str, object]
    popup_recovery: dict[str, object]
    helper: dict[str, object]
    talkback: dict[str, object]
    final_foreground: dict[str, object]


@dataclass
class CrashRunStats:
    confirmed_crash_count: int = 0
    possible_crash_count: int = 0
    app_terminated_count: int = 0
    crash_repeated_count: int = 0
    crash_recovered_count: int = 0
    counted_crash_count: int = 0
    seen_crash_event_ids: set[str] = field(default_factory=set, repr=False)
    seen_outcome_keys: set[str] = field(default_factory=set, repr=False)

    def to_log_payload(self) -> dict[str, int]:
        return {
            "confirmed": self.confirmed_crash_count,
            "possible": self.possible_crash_count,
            "app_terminated": self.app_terminated_count,
            "repeated": self.crash_repeated_count,
            "recovered": self.crash_recovered_count,
            "counted": self.counted_crash_count,
        }


def has_crash_terminal_signal(value: Any) -> bool:
    return extract_crash_terminal_signal(value) is not None


def extract_crash_terminal_signal(value: Any) -> CrashTerminalSignal | None:
    if value is None:
        return None
    if isinstance(value, CrashTerminalSignal):
        return value if value.is_crash_like else None
    if isinstance(value, dict):
        return _signal_from_mapping(value)
    if isinstance(value, (list, tuple)):
        for item in reversed(value):
            signal = extract_crash_terminal_signal(item)
            if signal is not None:
                return signal
    return None


def build_recovery_decision(signal: CrashTerminalSignal, attempt: int = 0) -> RecoveryDecision:
    normalized_signal = CrashTerminalSignal(
        is_crash_like=signal.is_crash_like,
        scenario_id=signal.scenario_id,
        stop_reason=signal.stop_reason,
        crash_type=signal.crash_type,
        crash_event_id=signal.crash_event_id,
        attempt=max(0, int(attempt)),
        artifact_dir=signal.artifact_dir,
        recovery_state=STATE_CRASH_DETECTED,
    )
    return RecoveryDecision(
        signal=normalized_signal,
        decision="logs_only",
        retry_count=0,
        result="not_implemented",
        scenario_final_status="CRASH_CAPTURED",
        next_action="continue_without_retry",
        states=(
            STATE_CRASH_DETECTED,
            STATE_ARTIFACT_CAPTURED,
            STATE_RECOVERY_NOT_IMPLEMENTED,
            STATE_CONTINUE_WITHOUT_RETRY,
        ),
    )


def build_relaunch_recovery_decision(
    signal: CrashTerminalSignal,
    preflight: RecoveryPreflightResult,
    attempt: int = 0,
) -> RecoveryDecision:
    normalized_signal = CrashTerminalSignal(
        is_crash_like=signal.is_crash_like,
        scenario_id=signal.scenario_id,
        stop_reason=signal.stop_reason,
        crash_type=signal.crash_type,
        crash_event_id=signal.crash_event_id,
        attempt=max(0, int(attempt)),
        artifact_dir=signal.artifact_dir,
        recovery_state=STATE_CRASH_DETECTED,
    )
    preflight_state = STATE_RECOVERY_PREFLIGHT_PASSED if preflight.ok else STATE_RECOVERY_PREFLIGHT_FAILED
    return RecoveryDecision(
        signal=normalized_signal,
        decision="relaunch_only",
        retry_count=0,
        result="recovery_preflight_passed" if preflight.ok else "recovery_preflight_failed",
        scenario_final_status="CRASH_CAPTURED",
        next_action="continue_without_retry",
        states=(
            STATE_CRASH_DETECTED,
            STATE_ARTIFACT_CAPTURED,
            STATE_RELAUNCHING,
            STATE_RECOVERY_PREFLIGHT,
            preflight_state,
            STATE_CONTINUE_WITHOUT_RETRY,
        ),
        relaunch_result=preflight.relaunch_result,
        preflight_result=preflight.preflight_result,
        failure_reason="" if preflight.ok else preflight.reason,
        helper_status=preflight.helper_status,
        talkback_status=preflight.talkback_status,
        foreground_status=preflight.foreground_status,
        foreground_package=preflight.foreground_package,
    )


def build_retry_outcome_decision(
    signal: CrashTerminalSignal,
    *,
    recovered: bool,
    attempt: int = 1,
) -> RecoveryDecision:
    normalized_signal = CrashTerminalSignal(
        is_crash_like=signal.is_crash_like,
        scenario_id=signal.scenario_id,
        stop_reason=signal.stop_reason,
        crash_type=signal.crash_type,
        crash_event_id=signal.crash_event_id,
        attempt=max(0, int(attempt)),
        artifact_dir=signal.artifact_dir,
        recovery_state=STATE_CRASH_RECOVERED if recovered else STATE_CRASH_REPEATED,
    )
    return RecoveryDecision(
        signal=normalized_signal,
        decision="retry_once",
        retry_count=1,
        result="crash_recovered" if recovered else "crash_repeated",
        scenario_final_status=STATE_CRASH_RECOVERED if recovered else STATE_CRASH_REPEATED,
        next_action="continue_next_scenario" if recovered else "scenario_skip",
        states=(
            STATE_RETRYING_SCENARIO,
            STATE_CRASH_RECOVERED if recovered else STATE_CRASH_REPEATED,
        ),
    )


def run_recovery_preflight(
    *,
    client: Any,
    serial: str | None,
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
    sleep_fn: Callable[[float], None] | None = None,
) -> RecoveryPreflightResult:
    resolved_sleep_fn = sleep_fn or time.sleep
    screen_awake = wake_screen(serial=serial, adb_path=adb_path, adb_runner=adb_runner, sleep_fn=resolved_sleep_fn)
    unlock_status = unlock_swipe(serial=serial, adb_path=adb_path, adb_runner=adb_runner, sleep_fn=resolved_sleep_fn)
    app_foreground = ensure_smartthings_foreground(
        serial=serial,
        adb_path=adb_path,
        adb_runner=adb_runner,
        sleep_fn=resolved_sleep_fn,
    )

    popup_status = {"status": "PASS", "message": "No external popup contamination detected", "recovered": True}
    foreground_package = str(app_foreground.get("package") or "")
    if app_foreground.get("status") == "FAIL" and foreground_package in EXTERNAL_POPUP_PACKAGES:
        popup_status = recover_external_popup_contamination(
            serial=serial,
            adb_path=adb_path,
            adb_runner=adb_runner,
            sleep_fn=resolved_sleep_fn,
            contamination_hint=foreground_package,
        )
        app_foreground = ensure_smartthings_foreground(
            serial=serial,
            adb_path=adb_path,
            adb_runner=adb_runner,
            sleep_fn=resolved_sleep_fn,
        )
    else:
        popup_status = recover_external_popup_contamination(
            serial=serial,
            adb_path=adb_path,
            adb_runner=adb_runner,
            sleep_fn=resolved_sleep_fn,
        )

    helper_ready = False
    try:
        helper_ready = bool(client.ping(dev=serial, wait_=3.0))
    except Exception:
        helper_ready = False
    helper_result = ensure_accessibility_service_enabled(
        serial=serial,
        adb_path=adb_path,
        component=HELPER_SERVICE_COMPONENT,
        helper_ready_check=lambda: helper_ready,
    )
    helper = {
        "status": "ok" if helper_result.ok else "fail",
        "reason": helper_result.reason,
        "helper_ready": helper_result.helper_ready,
    }

    try:
        talkback_payload = client.check_talkback_ready(dev=serial)
    except Exception as exc:
        talkback_payload = {"status": "disabled", "reason": str(exc)}
    talkback_status_raw = str(talkback_payload.get("status") or "disabled")
    talkback = {
        "status": "ok" if talkback_status_raw == "enabled" else "fail",
        "raw_status": talkback_status_raw,
        "reason": str(talkback_payload.get("reason") or ""),
    }

    final_foreground = ensure_smartthings_foreground(
        serial=serial,
        adb_path=adb_path,
        adb_runner=adb_runner,
        sleep_fn=resolved_sleep_fn,
        settle_seconds=0.5,
    )
    final_package = str(final_foreground.get("package") or "")
    foreground_ok = final_foreground.get("status") == "PASS" and final_package == SMARTTHINGS_PACKAGE
    relaunch_ok = app_foreground.get("status") == "PASS" or foreground_ok
    reason = _recovery_preflight_failure_reason(
        screen_awake=screen_awake,
        popup_status=popup_status,
        helper=helper,
        talkback=talkback,
        foreground_ok=foreground_ok,
    )
    ok = reason == "ok"
    return RecoveryPreflightResult(
        ok=ok,
        reason=reason,
        relaunch_result="success" if relaunch_ok else "failed",
        preflight_result="passed" if ok else "failed",
        helper_status=str(helper["status"]),
        talkback_status=str(talkback["status"]),
        foreground_status="ok" if foreground_ok else "fail",
        foreground_package=final_package,
        wake_screen=screen_awake,
        unlock_swipe=unlock_status,
        app_foreground=app_foreground,
        popup_recovery=popup_status,
        helper=helper,
        talkback=talkback,
        final_foreground=final_foreground,
    )


def should_process_crash_recovery(signal: CrashTerminalSignal, processed_event_ids: set[str]) -> bool:
    event_id = str(signal.crash_event_id or "").strip()
    if not event_id:
        return True
    if event_id in processed_event_ids:
        return False
    processed_event_ids.add(event_id)
    return True


def resolve_crash_abort_threshold(env: dict[str, str] | None = None, default: int = DEFAULT_CRASH_ABORT_THRESHOLD) -> int:
    source = os.environ if env is None else env
    raw_value = str(source.get("TB_CRASH_ABORT_THRESHOLD", "") or "").strip()
    if not raw_value:
        return max(1, int(default))
    try:
        return max(1, int(raw_value))
    except ValueError:
        return max(1, int(default))


def update_crash_run_stats(
    stats: CrashRunStats,
    *,
    signal: CrashTerminalSignal,
    decision: RecoveryDecision,
    retry_signal: CrashTerminalSignal | None = None,
) -> CrashRunStats:
    retry_consumed = int(decision.retry_count or 0) > 0
    _record_crash_signal_for_stats(stats, signal, retry_consumed=retry_consumed)
    if retry_signal is not None:
        _record_crash_signal_for_stats(stats, retry_signal, retry_consumed=retry_consumed)

    outcome_key = f"{decision.result}:{signal.scenario_id}:{signal.crash_event_id}"
    if outcome_key not in stats.seen_outcome_keys:
        stats.seen_outcome_keys.add(outcome_key)
        if decision.result == "crash_recovered":
            stats.crash_recovered_count += 1
        elif decision.result == "crash_repeated":
            stats.crash_repeated_count += 1
    return stats


def should_abort_for_crash_policy(
    stats: CrashRunStats,
    *,
    threshold: int,
    decision: RecoveryDecision | None = None,
) -> dict[str, object]:
    if decision is not None and decision.result == "recovery_preflight_failed":
        reason = _non_recoverable_preflight_abort_reason(decision.failure_reason)
        if reason:
            return {
                "decision": "abort",
                "reason": reason,
                "counted_crash_count": stats.counted_crash_count,
                "threshold": threshold,
            }
    if stats.counted_crash_count >= threshold:
        return {
            "decision": "abort",
            "reason": "crash_threshold_exceeded",
            "counted_crash_count": stats.counted_crash_count,
            "threshold": threshold,
        }
    return {
        "decision": "continue",
        "reason": "",
        "counted_crash_count": stats.counted_crash_count,
        "threshold": threshold,
    }


def render_crash_stats_log_lines(
    stats: CrashRunStats,
    *,
    threshold: int,
    policy: dict[str, object],
) -> list[str]:
    payload = stats.to_log_payload()
    lines = [
        (
            "[CRASH_POLICY] stats "
            f"confirmed={payload['confirmed']} possible={payload['possible']} "
            f"app_terminated={payload['app_terminated']} repeated={payload['repeated']} "
            f"recovered={payload['recovered']} counted={payload['counted']} threshold={threshold}"
        )
    ]
    if str(policy.get("decision") or "") == "abort":
        lines.append(
            "[CRASH_POLICY] decision='abort' "
            f"reason='{policy.get('reason') or ''}' counted={policy.get('counted_crash_count')} "
            f"threshold={policy.get('threshold')}"
        )
    else:
        lines.append("[CRASH_POLICY] decision='continue'")
    return lines


def update_crash_context_batch_policy(signal: CrashTerminalSignal, policy: dict[str, object]) -> bool:
    if not signal.artifact_dir:
        return False
    context_path = Path(signal.artifact_dir) / "crash_context.json"
    if not context_path.exists():
        return False
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    batch_policy = {
        "counted_crash_count": int(policy.get("counted_crash_count") or 0),
        "threshold": int(policy.get("threshold") or DEFAULT_CRASH_ABORT_THRESHOLD),
        "decision": str(policy.get("decision") or "continue"),
    }
    reason = str(policy.get("reason") or "")
    if reason:
        batch_policy["reason"] = reason
    payload["batch_policy"] = batch_policy
    context_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def render_recovery_log_lines(decision: RecoveryDecision) -> list[str]:
    signal = decision.signal
    if decision.decision == "relaunch_only":
        lines = [
            (
                f"[CRASH_RECOVERY] state='{STATE_CRASH_DETECTED}' "
                f"scenario='{signal.scenario_id}' crash_event_id='{signal.crash_event_id}' "
                f"crash_type='{signal.crash_type}' attempt={signal.attempt}"
            ),
            (
                f"[CRASH_RECOVERY] state='{STATE_ARTIFACT_CAPTURED}' "
                f"scenario='{signal.scenario_id}' crash_event_id='{signal.crash_event_id}'"
            ),
            (
                f"[CRASH_RECOVERY] state='{STATE_RELAUNCHING}' "
                f"scenario='{signal.scenario_id}' crash_event_id='{signal.crash_event_id}'"
            ),
            (
                f"[CRASH_RECOVERY] relaunch_result='{decision.relaunch_result}' "
                f"foreground='{decision.foreground_package or 'unknown'}'"
            ),
            (
                f"[CRASH_RECOVERY] state='{STATE_RECOVERY_PREFLIGHT}' "
                f"scenario='{signal.scenario_id}'"
            ),
            (
                f"[CRASH_RECOVERY] preflight_result='{decision.preflight_result}' "
                f"helper='{decision.helper_status or 'unknown'}' "
                f"talkback='{decision.talkback_status or 'unknown'}' "
                f"foreground='{decision.foreground_status or 'unknown'}'"
            ),
        ]
        if decision.preflight_result == "failed" and decision.failure_reason:
            lines.append(
                f"[CRASH_RECOVERY] recovery_reason='{decision.failure_reason}' "
                f"scenario='{signal.scenario_id}'"
            )
        lines.append(
            f"[CRASH_RECOVERY] state='{STATE_CONTINUE_WITHOUT_RETRY}' "
            f"scenario='{signal.scenario_id}'"
        )
        return lines
    return [
        (
            f"[CRASH_RECOVERY] state='{STATE_CRASH_DETECTED}' "
            f"scenario='{signal.scenario_id}' crash_event_id='{signal.crash_event_id}' "
            f"crash_type='{signal.crash_type}' attempt={signal.attempt}"
        ),
        (
            f"[CRASH_RECOVERY] state='{STATE_ARTIFACT_CAPTURED}' "
            f"scenario='{signal.scenario_id}' crash_event_id='{signal.crash_event_id}'"
        ),
        (
            f"[CRASH_RECOVERY] state='{STATE_RECOVERY_NOT_IMPLEMENTED}' "
            f"scenario='{signal.scenario_id}' decision='{decision.decision}'"
        ),
        (
            f"[CRASH_RECOVERY] state='{STATE_CONTINUE_WITHOUT_RETRY}' "
            f"scenario='{signal.scenario_id}'"
        ),
    ]


def update_crash_context_recovery(signal: CrashTerminalSignal, decision: RecoveryDecision) -> bool:
    if not signal.artifact_dir:
        return False
    context_path = Path(signal.artifact_dir) / "crash_context.json"
    if not context_path.exists():
        return False
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    recovery_payload = payload.get("recovery") if isinstance(payload.get("recovery"), dict) else {}
    payload["recovery"] = {**recovery_payload, **decision.to_recovery_payload()}
    context_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _signal_from_mapping(value: dict[str, Any]) -> CrashTerminalSignal | None:
    is_crash_like = bool(value.get("is_crash_like") or value.get("crash_like_detected"))
    stop_reason = str(value.get("stop_reason") or value.get("reason") or "").strip()
    crash_type = str(value.get("crash_type") or "").strip().upper()
    if not is_crash_like and stop_reason not in CRASH_STOP_REASONS and crash_type not in CRASH_TYPES:
        return None

    scenario_id = str(value.get("scenario_id") or value.get("scenario") or "").strip()
    crash_event_id = str(value.get("crash_event_id") or "").strip()
    artifact_dir = str(value.get("artifact_dir") or value.get("event_path") or "").strip()
    attempt = _int_or_default(value.get("attempt"), 0)
    if not stop_reason:
        stop_reason = _stop_reason_for_crash_type(crash_type)
    if not crash_type:
        crash_type = _crash_type_for_stop_reason(stop_reason)

    return CrashTerminalSignal(
        is_crash_like=True,
        scenario_id=scenario_id,
        stop_reason=stop_reason,
        crash_type=crash_type or "POSSIBLE_CRASH",
        crash_event_id=crash_event_id,
        attempt=attempt,
        artifact_dir=artifact_dir,
        recovery_state=str(value.get("recovery_state") or STATE_CRASH_DETECTED),
    )


def _stop_reason_for_crash_type(crash_type: str) -> str:
    if crash_type == "CONFIRMED_CRASH":
        return "confirmed_crash"
    if crash_type == "APP_TERMINATED":
        return "app_terminated"
    if crash_type == "POSSIBLE_CRASH":
        return "possible_crash"
    return ""


def _crash_type_for_stop_reason(stop_reason: str) -> str:
    if stop_reason == "confirmed_crash":
        return "CONFIRMED_CRASH"
    if stop_reason == "app_terminated":
        return "APP_TERMINATED"
    if stop_reason == "possible_crash":
        return "POSSIBLE_CRASH"
    return ""


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _recovery_preflight_failure_reason(
    *,
    screen_awake: dict[str, object],
    popup_status: dict[str, object],
    helper: dict[str, object],
    talkback: dict[str, object],
    foreground_ok: bool,
) -> str:
    if screen_awake.get("status") == "FAIL":
        return "wake_screen_failed"
    if popup_status.get("status") == "FAIL":
        return "external_popup_contamination"
    if helper.get("status") != "ok":
        return "helper_not_ready"
    if talkback.get("status") != "ok":
        return "talkback_not_ready"
    if not foreground_ok:
        return "foreground_not_confirmed"
    return "ok"


def _record_crash_signal_for_stats(
    stats: CrashRunStats,
    signal: CrashTerminalSignal,
    *,
    retry_consumed: bool,
) -> None:
    event_id = str(signal.crash_event_id or "").strip()
    if event_id and event_id in stats.seen_crash_event_ids:
        return
    if event_id:
        stats.seen_crash_event_ids.add(event_id)

    crash_type = str(signal.crash_type or "").upper()
    if crash_type == "CONFIRMED_CRASH":
        stats.confirmed_crash_count += 1
        stats.counted_crash_count += 1
    elif crash_type == "POSSIBLE_CRASH":
        stats.possible_crash_count += 1
        if retry_consumed:
            stats.counted_crash_count += 1
    elif crash_type == "APP_TERMINATED":
        stats.app_terminated_count += 1


def _non_recoverable_preflight_abort_reason(reason: str) -> str:
    normalized = str(reason or "").strip()
    if normalized in {"helper_not_ready", "talkback_not_ready", "talkback_off", "foreground_not_confirmed"}:
        return "recovery_preflight_failed"
    return ""
