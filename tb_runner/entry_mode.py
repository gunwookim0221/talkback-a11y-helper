"""Explicit entry policy and read-only, fail-closed prepositioned handoff.

PREPOSITIONED is a CLI/RunSpec capability. It never supplies click evidence or
visit credit. The existing collector owns focus reconciliation and traversal.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
from typing import Any

from talkback_lib.hierarchy_snapshot import flatten_service_hierarchy

AUTOMATED = "AUTOMATED"
PREPOSITIONED = "PREPOSITIONED"


def normalize_entry_mode(value: str = AUTOMATED) -> str:
    if value not in {AUTOMATED, PREPOSITIONED}:
        raise ValueError("entry_mode must be AUTOMATED or PREPOSITIONED")
    return value


class PrepositionedSafetyStop(BaseException):
    """A committed stop which must bypass ordinary retry/recovery handlers."""


def _component(text: str, marker: str) -> tuple[str, str] | None:
    components = set()
    for line in text.splitlines():
        if marker not in line:
            continue
        match = re.search(r"\s([\w.]+)/([\w.$]+)", line)
        if match:
            package, activity = match.groups()
            components.add((package, package + activity if activity.startswith(".") else activity))
    return next(iter(components)) if len(components) == 1 else None


def verify_destination(contract: dict[str, Any] | None, *, activity: str,
                       window: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Pure verifier. Title text alone can never satisfy this contract."""
    result: dict[str, Any] = {"verdict": "AMBIGUOUS", "reason": "destination_contract_missing"}
    if not isinstance(contract, dict):
        return result
    package = contract.get("package")
    pattern = contract.get("activity_regex")
    required = contract.get("required_resource_ids")
    semantic = contract.get("semantic_marker")
    excluded = contract.get("excluded_resource_ids")
    if (not isinstance(package, str) or not package or not isinstance(pattern, str) or not pattern
            or not isinstance(required, list) or not all(isinstance(rid, str) and rid for rid in required)
            or len(set(required)) < 2
            or not isinstance(semantic, dict) or not semantic.get("resource_id") or not semantic.get("text_regex")
            or not isinstance(excluded, list) or not excluded):
        return result
    try:
        activity_pattern = re.compile(pattern)
        semantic_pattern = re.compile(semantic["text_regex"])
    except (re.error, TypeError):
        return dict(result, reason="destination_contract_invalid")
    component = _component(activity, "topResumedActivity=") or _component(activity, "mResumedActivity")
    focused = _component(window, "mCurrentFocus=")
    result.update(component=component, focused_component=focused,
                  contract_sha256=hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest())
    if component is None or focused is None:
        return dict(result, reason="foreground_component_unavailable_or_ambiguous")
    if component != focused or component[0] != package or not activity_pattern.fullmatch(component[1]):
        return dict(result, verdict="FAIL", reason="foreground_destination_mismatch")
    try:
        active = [w for w in snapshot.get("windows", []) if w.get("active") or w.get("focused")]
        if len(active) != 1 or active[0].get("root", {}).get("packageName") != package:
            return dict(result, reason="active_window_ambiguous")
        nodes = [n for n in flatten_service_hierarchy(snapshot) if n.get("visibleToUser") is True]
    except (ValueError, TypeError, AttributeError):
        return dict(result, reason="hierarchy_unavailable")
    ids = {n["viewIdResourceName"] for n in nodes if n.get("packageName") == package}
    source_hits = sorted(ids.intersection(excluded))
    missing = sorted(set(required) - ids)
    semantic_hit = any(n.get("packageName") == package
                       and n.get("viewIdResourceName") == semantic["resource_id"]
                       and semantic_pattern.fullmatch(str(n.get("text") or n.get("contentDescription") or ""))
                       for n in nodes)
    result.update(source_screen_excluded=not source_hits, source_hits=source_hits,
                  missing_resource_ids=missing, semantic_marker_verified=semantic_hit,
                  snapshot_request_id=snapshot.get("reqId"), visible_node_count=len(nodes))
    if source_hits:
        return dict(result, verdict="FAIL", reason="source_screen_present")
    if missing or not semantic_hit:
        return dict(result, verdict="FAIL", reason="destination_markers_missing")
    return dict(result, verdict="PASS", reason="destination_verified")


_READ_BROADCASTS = {"PING", "DUMP_TREE", "DUMP_HIERARCHY", "GET_FOCUS", "CHECK_TARGET",
                    "EVIDENCE_EVENTS", "DUMP_SCROLL_CAPABILITIES", "RESOLVE_EXACT_NODE"}
_FOCUS_SCROLL_BROADCASTS = {"NEXT", "PREV", "SMART_NEXT", "FOCUS_TARGET", "FOCUS_IN_BOUNDS",
                           "TARGET_FOCUS_COMMIT", "SCROLL"}
_DIAGNOSTIC_DUMPS = {"window", "activity", "accessibility", "power", "package", "input", "display"}


def _readonly_shell_pipeline(command: str) -> bool:
    # Lifecycle observations combine only these diagnostic commands. Do not
    # admit substitutions, redirects, background commands or arbitrary shells.
    if any(char in command for char in ("$", "`", "\n", ">", "<", "&")):
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";|")
        lexer.whitespace_split = True
        segments: list[list[str]] = [[]]
        for token in lexer:
            if token in {";", "|"}:
                if not segments[-1]:
                    return False
                segments.append([])
            else:
                segments[-1].append(token)
        return all(segment and (
            (segment[0] == "dumpsys" and len(segment) >= 2 and segment[1] in _DIAGNOSTIC_DUMPS)
            or (segment[0] == "echo" and len(segment) == 2 and segment[1] in
                {"__TB_ACTIVITY__", "__TB_ACCESSIBILITY__", "__TB_PID__"})
            or (segment[0] == "pidof" and len(segment) == 2)
            or (segment[0] == "grep" and len(segment) == 3 and segment[1] in {"-E", "-F"})
        ) for segment in segments)
    except ValueError:
        return False


class PrepositionedSession:
    """Per-run evidence and a non-activating transport interlock, never visit authority."""

    def __init__(self, client: Any, config: dict[str, Any], audit_path: str | Path,
                 log_fn=print) -> None:
        self.client = client
        self.config = config
        self.contract = config.get("prepositioned_destination")
        self.audit_path = Path(audit_path)
        self.log = log_fn
        self.phase = "READ_ONLY"
        self.latched_reason: str | None = None
        self.blocked_command: list[str] | None = None
        self.destination: dict[str, Any] = {}
        self.invariant_signature: str | None = None
        self.sequence = 0

    def record(self, event: str, **payload: Any) -> None:
        self.sequence += 1
        row = dict(schema="prepositioned-entry-v1", sequence=self.sequence,
                   timestamp=datetime.now(timezone.utc).isoformat(), event=event,
                   scenario_id=self.config.get("scenario_id"), entry_mode=PREPOSITIONED,
                   entry_action_executed=False, **payload)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        if event != "COMMAND_ALLOWED":
            self.log("[PREPOSITIONED] " + json.dumps(row, ensure_ascii=False))

    def bind(self) -> None:
        self.client._prepositioned_session = self
        self.client._adb_device.command_guard = self.guard_command
        self.client.hierarchy_observer = self.observe_hierarchy
        self.record("MODE_REQUESTED", mutating_preflight="SKIP", read_only_preflight="RUN")

    def stop(self, reason: str) -> None:
        if self.latched_reason is None:
            self.latched_reason = reason
            self.record("SAFETY_STOP", reason=reason)
        self.phase = "STOPPED"
        raise PrepositionedSafetyStop(self.latched_reason)

    def guard_command(self, args: list[str]) -> None:
        # A stop forbids every later action. Passive evidence draining remains
        # available so the blocked transaction can be closed without retrying it.
        allowed = False
        kind = "read_only"
        if args and args[0] in {"devices", "get-state", "get-serialno", "logcat", "pull"}:
            allowed = True
        elif args[:1] == ["shell"] and len(args) > 1:
            shell = args[1:]
            if len(shell) == 1:
                allowed = _readonly_shell_pipeline(shell[0])
            elif shell[0] == "am" and shell[1:2] == ["broadcast"] and "-a" in shell:
                action = shell[shell.index("-a") + 1]
                prefix = "com.iotpart.sqe.talkbackhelper."
                name = action[len(prefix):] if action.startswith(prefix) else ""
                allowed = name in _READ_BROADCASTS
                if self.phase == "TRAVERSAL" and name in _FOCUS_SCROLL_BROADCASTS:
                    allowed, kind = True, "focus_or_scroll"
                if self.phase == "TRAVERSAL" and name == "ACTION_COMMAND":
                    allowed = any(shell[i:i+3] == ["--es", "command", "reset"] for i in range(len(shell)-2))
                    kind = "history_reset"
            elif shell[0] == "dumpsys" and shell[1] in _DIAGNOSTIC_DUMPS:
                allowed = True
            elif shell[0] in {"getprop", "pidof", "screencap"}:
                allowed = True
            elif shell[:2] == ["settings", "get"] or shell[:2] in (["wm", "size"], ["wm", "density"], ["pm", "path"]):
                allowed = True
            elif shell[:2] == ["cmd", "device_state"] and shell[2:] in (["print-state"], ["print-states"]):
                allowed = True
            elif shell[0] == "sha256sum" and len(shell) == 2 and shell[1].startswith("/data/app/"):
                allowed = True
            elif shell[0] == "cat" and shell[1:] in (["/proc/uptime"], ["/proc/sys/kernel/random/boot_id"]):
                allowed = True
            elif self.phase == "TRAVERSAL" and shell[:2] == ["input", "swipe"] and len(shell) in {6, 7}:
                # Existing vertical traversal scrolling only; never a tap or
                # an edge/back gesture, and never usable during preflight.
                try:
                    x1, y1, x2, y2 = map(int, shell[2:6])
                    allowed = x1 == x2 and x1 > 0 and y1 != y2 and min(y1, y2) > 0
                    kind = "vertical_scroll"
                except ValueError:
                    pass
        if not allowed:
            if self.blocked_command is None:
                self.blocked_command = list(args)
            self.record("COMMAND_BLOCKED", command=args, phase=self.phase)
            self.stop("non_navigation_contract_violation")
        self.record("COMMAND_ALLOWED", command=args, kind=kind, phase=self.phase)

    def finalize_stop(self, *, row_count: int) -> None:
        if not self.latched_reason:
            raise ValueError("No prepositioned safety stop to finalize")
        runtime = getattr(self.client, "evidence_runtime", None)
        transaction = getattr(self.client, "_evidence_active_transaction", None)
        if runtime is not None and getattr(runtime, "is_enabled", False):
            if self.blocked_command:
                # The active owner can contain a previously executed focus
                # action. Never relabel it as an unexecuted click. The blocked
                # dispatch has its own child record and exact request ID.
                args = self.blocked_command
                request_id = args[args.index("reqId") + 1] if "reqId" in args else None
                blocked = runtime.begin_transaction("BLOCKED_COMMAND", phase="safety_stop",
                    parent_transaction_id=transaction.get("transaction_id") if transaction else None,
                    payload=dict(command=args, request_id=request_id))
                runtime.emit("ACTION_DISPATCH_BLOCKED", producer="runner", phase="safety_stop",
                             transaction=blocked, payload=dict(reason=self.latched_reason,
                             request_id=request_id, dispatch_status="BLOCKED_BEFORE_DISPATCH",
                             executed=False, visit_credit=False))
                runtime.close_transaction(blocked, status="blocked", phase="safety_stop",
                                          payload=dict(reason=self.latched_reason, executed=False))
            if transaction:
                runtime.close_transaction(transaction, status="safety_stopped", phase="safety_stop",
                    payload=dict(reason=self.latched_reason, prior_execution_evidence_preserved=True))
            runtime.emit("SCENARIO_TERMINAL", producer="runner", phase="scenario_end", payload=dict(
                reason="SAFETY_STOP", detail=self.latched_reason, entry_mode=PREPOSITIONED,
                traversal_started=self.destination.get("verdict") == "PASS" and row_count > 0,
                entry_action_executed=False))
        self.client._evidence_active_transaction = None
        self.client._evidence_active_request_id = ""
        self.record("INTERNAL_TRAVERSAL_TERMINAL", terminal="SAFETY_STOP", reason=self.latched_reason,
                    row_count=row_count, blocked_dispatch_record_closed=bool(self.blocked_command),
                    prior_transaction_closed=bool(transaction))

    def observe_hierarchy(self, snapshot: dict[str, Any]) -> None:
        if not isinstance(self.contract, dict):
            return
        try:
            nodes = flatten_service_hierarchy(snapshot)
        except (ValueError, TypeError):
            self.stop("hierarchy_observation_invalid")
        visible = [n for n in nodes if n.get("visibleToUser") is True]
        if any(n.get("packageName") and n["packageName"] != self.contract["package"] for n in visible):
            self.stop("destination_package_changed")
        ids = {n.get("viewIdResourceName") for n in visible}
        if ids.intersection(self.contract.get("excluded_resource_ids", [])):
            self.stop("source_screen_observed")
        invariant_ids = self.contract.get("invariant_resource_ids", [])
        if not invariant_ids or not set(invariant_ids).issubset(ids):
            return
        values = sorted((n["viewIdResourceName"], str(n.get("text") or ""),
                         str(n.get("contentDescription") or ""), bool(n.get("selected")), bool(n.get("checked")))
                        for n in visible if n.get("viewIdResourceName") in invariant_ids)
        signature = hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
        if self.invariant_signature is not None and signature != self.invariant_signature:
            self.stop("visible_destination_state_changed")
        if self.invariant_signature is None:
            self.invariant_signature = signature
            self.record("VISIBLE_STATE_BASELINE", signature=signature)

    def verify(self, dev: Any, *, stage: str) -> dict[str, Any]:
        try:
            activity = self.client._run(["shell", "dumpsys", "activity", "activities"], dev=dev)
            window = self.client._run(["shell", "dumpsys", "window"], dev=dev)
            snapshot = self.client.dump_hierarchy(dev=dev)
            after = self.client._run(["shell", "dumpsys", "activity", "activities"], dev=dev)
            result = verify_destination(self.contract, activity=activity, window=window, snapshot=snapshot)
            if _component(activity, "topResumedActivity=") != _component(after, "topResumedActivity="):
                result.update(verdict="AMBIGUOUS", reason="activity_changed_during_capture")
        except Exception as exc:
            result = dict(verdict="AMBIGUOUS", reason="destination_capture_failed", error=str(exc))
        self.destination = result
        self.record("DESTINATION_PRECONDITION", stage=stage, **result)
        runtime = getattr(self.client, "evidence_runtime", None)
        if runtime is not None and getattr(runtime, "is_enabled", False):
            runtime.emit("ENTRY_PRECONDITION", producer="runner", phase="entry", payload={
                "entry_mode": PREPOSITIONED, "entry_action_executed": False, **result})
        return result

    def begin_traversal(self) -> None:
        if self.destination.get("verdict") != "PASS":
            self.stop("destination_precondition_not_pass")
        self.record("POST_ENTRY_HANDOFF", destination_precondition="PASS",
                    automated_entry_attempted=False, entry_click_executed=False)
        self.phase = "TRAVERSAL"


def open_prepositioned(client: Any, dev: Any, config: dict[str, Any], *, log_fn,
                      stabilize_anchor_fn) -> bool:
    session = getattr(client, "_prepositioned_session", None)
    if session is None:
        raise ValueError("PREPOSITIONED requires an explicitly configured session")
    result = session.verify(dev, stage="post_entry_boundary")
    summary = dict(entry_mode=PREPOSITIONED, entry_action_executed=False,
                   automated_entry_attempted=False, pre_navigation_attempted=False,
                   pre_navigation_success=False, trusted_entry_verified=False,
                   destination_precondition=result, context_ok=result["verdict"] == "PASS",
                   entry_contract_reason="verify_failed", entry_contract_detail=result["reason"], open_completed=False)
    client.last_start_open_summary = summary
    if result["verdict"] != "PASS":
        return False
    session.begin_traversal()
    anchor = stabilize_anchor_fn(client=client, dev=dev, tab_cfg=config,
                                  phase="prepositioned_start",
                                  max_retries=max(1, int(config.get("anchor_retry_count", 2))), verify_reads=2)
    client.last_anchor_stabilize_result = anchor
    config.update(_scenario_start_mode="prepositioned_verified", _scenario_start_source="manual_destination_verified",
                  _scenario_anchor_stable=bool(anchor.get("ok")), _scenario_start_note="")
    summary.update(anchor_matched=bool(anchor.get("matched")), anchor_stable=bool(anchor.get("ok")),
                   open_completed=bool(anchor.get("ok")), destination_identity_verified=True,
                   root_plugin_body_verified=True,
                   entry_contract_reason="success_verified" if anchor.get("ok") else "verify_failed",
                   entry_contract_detail="prepositioned_destination_verified" if anchor.get("ok") else "prepositioned_anchor_failed")
    log_fn(f"[ENTRY] ENTRY_MODE=PREPOSITIONED DESTINATION_PRECONDITION=PASS AUTOMATED_ENTRY_ATTEMPTED=NO ENTRY_ACTION_EXECUTED=NO")
    return bool(anchor.get("ok"))


def readonly_preflight(client: Any, serial: str | None, log_fn) -> Any:
    from tb_runner.core_preflight import CorePreflightResult, _secure_lockscreen_active
    session = client._prepositioned_session
    step = lambda ok, **rest: dict(status="PASS" if ok else "FAIL", **rest)
    connected = step(client._run(["get-state"], dev=serial).strip() == "device")
    power = client._run(["shell", "dumpsys", "power"], dev=serial)
    policy = client._run(["shell", "dumpsys", "window", "policy"], dev=serial)
    # Samsung also exposes the unprefixed KeyguardServiceDelegate showing flag.
    locked = _secure_lockscreen_active(policy)
    if locked is None:
        match = re.search(r"^\s*showing=(true|false)\s*$", policy, re.MULTILINE)
        locked = match.group(1) == "true" if match else None
    awake = step("mWakefulness=Awake" in power)
    unlocked = step(locked is False, keyguard_active=locked, action_attempted=False)
    enabled = client.is_talkback_enabled(dev=serial)
    pid = client._run(["shell", "pidof", "com.samsung.android.accessibility.talkback"], dev=serial).strip()
    client._preflight_talkback_pid = pid if pid.isdigit() else None
    identity = client.precheck_helper_build_identity(dev=serial, acceptance_mode=True)
    state = identity.get("exact_action_state", {})
    idle = (not getattr(client, "_evidence_active_transaction", None)
            and not getattr(getattr(client, "_phase5c_hard_stop_state", None), "latched", False)
            and all(state.get(key) is False for key in ("build_gate", "runtime_gate", "c5_ready"))
            and state.get("helper_stopped") is True)
    helper_services = client._run(["shell", "settings", "get", "secure", "enabled_accessibility_services"], dev=serial)
    helper_enabled = "com.iotpart.sqe.talkbackhelper/." in helper_services or "com.iotpart.sqe.talkbackhelper/com.iotpart.sqe.talkbackhelper." in helper_services
    destination = session.verify(serial, stage="read_only_preflight")
    ok = (all(x["status"] == "PASS" for x in (connected, awake, unlocked)) and enabled and bool(pid)
          and helper_enabled and identity.get("status") == "MATCH" and idle and destination["verdict"] == "PASS")
    session.record("READ_ONLY_PREFLIGHT", ok=ok, helper_identity=identity, idle=idle,
                   device_connected=connected, screen_awake=awake, screen_unlocked=unlocked,
                   talkback_enabled=enabled, talkback_pid=pid, helper_enabled=helper_enabled)
    log_fn(f"[PREFLIGHT] ENTRY_MODE=PREPOSITIONED MUTATING_PREFLIGHT=SKIP READ_ONLY_PREFLIGHT={'PASS' if ok else 'FAIL'}")
    return CorePreflightResult(ok, "ok" if ok else "prepositioned_precondition_failed", None,
                               "enabled" if enabled and pid else "disabled", "read_only",
                               connected, awake, unlocked, step(destination["verdict"] == "PASS", destination=destination, launch_attempted=False))
