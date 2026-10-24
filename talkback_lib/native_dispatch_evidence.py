"""Graph-independent evidence about entry into the native ADB boundary.

Receipts prove that a classified native command was attempted. They do not
prove Android accepted it, that accessibility focus moved, or that a visit was
earned. This module deliberately has no Phase 6 graph/clock dependency.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
import shlex
from threading import RLock
from typing import Any
from uuid import uuid4

_owner = ContextVar("exploration_dispatch_owner", default="")
_operation = ContextVar("native_dispatch_operation_id", default="")
OWNERS = {"PRIMARY", "SEQUENTIAL", "TARGETED", "FALLBACK", "RECOVERY",
          "OPTIONAL_EXPANSION", "POPUP", "TAB", "OTHER"}
_READ_ACTIONS = {"DUMP_TREE", "DUMP_HIERARCHY", "GET_FOCUS", "CHECK_TARGET",
                 "PING", "RESOLVE_EXACT_NODE", "EVIDENCE_EVENTS", "ENTRY_CLICK_CAPTURE",
                 "HIERARCHY_TRANSFER_CAPABILITIES", "HIERARCHY_TRANSFER_START",
                 "HIERARCHY_TRANSFER_STATUS", "HIERARCHY_TRANSFER_ACK", "HIERARCHY_TRANSFER_CANCEL"}
DISPATCHED = "DISPATCHED"
NOT_DISPATCHED = "NOT_DISPATCHED"
UNKNOWN = "UNKNOWN"


def _history_reset(args: list[str]) -> bool:
    try:
        return (args[:3] == ["shell", "am", "broadcast"]
                and args[args.index("-a") + 1] == "com.iotpart.sqe.talkbackhelper.ACTION_COMMAND"
                and args[args.index("command") + 1].strip("'\"").lower() == "reset")
    except (ValueError, IndexError):
        return False


def classify_dispatch(args: list[str]) -> tuple[str, str, str] | None:
    """Return bounded action/owner/request metadata, never raw shell/label data."""
    tokens = [str(x) for x in args]
    if _history_reset(tokens):
        return None
    if tokens[:1] == ["exec-out"]:
        tokens = ["shell", *tokens[1:]]
    if tokens[:1] != ["shell"]:
        return None
    shell = tokens[1:]
    while shell[:1] in (["-T"], ["-t"], ["-tt"]):
        shell = shell[1:]
    if len(shell) == 1 and " " in shell[0]:
        script = shell[0]
        if not any(x in script for x in ("$", "`", ">", "<", "\\\n")):
            try:
                lexer = shlex.shlex(script, posix=True, punctuation_chars=";|&")
                lexer.whitespace_split = True
                groups, group = [], []
                for word in lexer:
                    if word in {";", "|", "&&", "||"}:
                        groups.append(group)
                        group = []
                    else:
                        group.append(word)
                groups.append(group)
                if groups and all(group and group[0] in {"echo", "grep", "head", "tail", "cut", "tr"}
                                  or group and classify_dispatch(["shell", *group]) is None for group in groups):
                    return None
            except ValueError:
                pass
        return "OTHER", "OTHER", ""
    if shell[:2] == ["am", "broadcast"]:
        action = shell[shell.index("-a") + 1] if "-a" in shell and shell.index("-a") + 1 < len(shell) else ""
        suffix = action.rsplit(".", 1)[-1]
        if action.startswith("com.iotpart.sqe.talkbackhelper.") and suffix in _READ_ACTIONS:
            return None
        request = ""
        for i, token in enumerate(shell[:-1]):
            if token in {"request_id", "requestId", "reqId", "req_id"}:
                request = shell[i + 1][:256]
                break
        inferred = ("TARGETED" if suffix in {"FOCUS_TARGET", "FOCUS_IN_BOUNDS", "TARGET_FOCUS_COMMIT"}
                    else "SEQUENTIAL" if suffix in {"SMART_NEXT", "NEXT", "PREV"}
                    else "PRIMARY" if suffix in {"CLICK_TARGET", "CLICK_FOCUSED", "TOUCH_BOUNDS_CENTER_TARGET", "SCROLL", "SET_TEXT"}
                    else "OTHER")
        return suffix if suffix in {"FOCUS_TARGET", "FOCUS_IN_BOUNDS", "TARGET_FOCUS_COMMIT", "SMART_NEXT", "NEXT", "PREV", "CLICK_TARGET", "CLICK_FOCUSED", "TOUCH_BOUNDS_CENTER_TARGET", "SCROLL", "SET_TEXT", "SET_SYSTEM_LANGUAGE", "ACTION_COMMAND"} else "OTHER", inferred, request
    if shell[:1] == ["input"]:
        kind = shell[1].upper() if len(shell) > 1 else "OTHER"
        return "INPUT_" + kind, "OTHER", ""
    if shell[:1] and shell[0] in {"cat", "getprop", "dumpsys", "pidof", "ps", "ls", "stat", "logcat", "screencap", "wm"}:
        # wm size/density without arguments are queries only.
        if shell[0] != "wm" or len(shell) <= 2:
            return None
    if shell[:2] in (["settings", "get"], ["settings", "list"], ["content", "read"], ["content", "query"]):
        return None
    if shell[:2] in (["am", "get-current-user"], ["pm", "path"], ["pm", "list"], ["cmd", "device_state"]) and (shell[:2] != ["cmd", "device_state"] or shell[2:3] == ["print-states"]):
        return None
    # Cleanup/build/file transfer commands cannot move app focus.
    if shell[:1] and shell[0] in {"rm", "mkdir", "chmod", "sha256sum", "wc", "test"}:
        return None
    return "OTHER", "OTHER", ""


@contextmanager
def dispatch_owner(owner: str):
    """Label an existing production scope; this neither dispatches nor consumes permits."""
    token = _owner.set(owner if owner in OWNERS else "OTHER")
    try:
        yield
    finally:
        _owner.reset(token)


@contextmanager
def native_dispatch_operation(operation_id: str | None = None):
    """Correlate receipts from one operation without treating request IDs as operation IDs."""
    value = str(operation_id or "").strip() or uuid4().hex
    token = _operation.set(value)
    try:
        yield value
    finally:
        _operation.reset(token)


def current_operation_id() -> str:
    return str(_operation.get() or "")


def current_dispatch_owner() -> str:
    return str(_owner.get() or "")


def owned_dispatch(owner: str):
    from functools import wraps
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with dispatch_owner(owner):
                return function(*args, **kwargs)
        return wrapped
    return decorate


@dataclass
class NativeDispatchReceiptStore:
    """Bounded generic receipt source with a unique lifetime generation."""

    receipts: list[dict[str, Any]] = field(default_factory=list)
    receipt_sequence: int = 0
    generation_id: str = field(default_factory=lambda: uuid4().hex)
    _lock: Any = field(default_factory=RLock, repr=False)

    def observe(self, args: list[str], *, operation_id: str | None = None) -> None:
        with self._lock:
            try:
                classified = classify_dispatch(args)
                if classified is None:
                    return
                action, inferred, request = classified
                self.receipt_sequence += 1
                owner = _owner.get() or inferred
                op_id = str(operation_id or _operation.get() or "").strip()
                self.receipts.append({
                    "receipt_seq": self.receipt_sequence,
                    "store_generation": self.generation_id,
                    "operation_id": op_id or None,
                    "action_type": action,
                    "owner": owner,
                    "ownership_status": "KNOWN" if owner != "OTHER" else "UNRESOLVED",
                    "request_id": request or None,
                    "native_boundary_status": "ENTERED",
                    "dispatch_status": "NATIVE_DISPATCH_ATTEMPTED",
                })
                del self.receipts[:-2048]
            except Exception:
                # Native evidence is observational and cannot change the ADB
                # operation's production outcome.
                return

    def receipt_watermark(self) -> int:
        with self._lock:
            return self.receipt_sequence

    def reset(self) -> None:
        """Start a new evidence-source lifetime so old checkpoints go stale."""
        with self._lock:
            self.receipts.clear()
            self.receipt_sequence = 0
            self.generation_id = uuid4().hex

    def receipts_after(self, watermark: int, *, request_id: str | None = None,
                       operation_id: str | None = None) -> list[dict[str, Any]]:
        """Query by monotonic sequence, never by the current bounded-list length."""
        with self._lock:
            request = str(request_id or "").strip()
            operation = str(operation_id or "").strip()
            return [deepcopy(receipt) for receipt in self.receipts
                    if type(receipt.get("receipt_seq")) is int
                    and receipt["receipt_seq"] > watermark
                    and (not request or str(receipt.get("request_id") or "") == request)
                    and (not operation or str(receipt.get("operation_id") or "") == operation)]


@dataclass(frozen=True)
class NativeDispatchCheckpoint:
    """Pre-call receipt watermark. UNKNOWN is explicit; no zero fallback."""

    operation_id: str
    store_generation: str | None
    receipt_watermark_before: int | None
    checkpoint_status: str
    reason: str = ""


@dataclass(frozen=True)
class NativeDispatchEvidence:
    """Native boundary evidence only; never Android/focus/visit authorization."""

    operation_id: str
    request_id: str | None
    store_generation: str | None
    checkpoint_status: str
    receipt_watermark_before: int | None
    receipt_seq: int | None
    receipt_match: bool
    native_boundary_status: str
    dispatch_status: str
    evidence_source: str
    reason: str = ""


def native_dispatch_checkpoint(store: Any, *, operation_id: str | None = None) -> NativeDispatchCheckpoint:
    """Capture a typed checkpoint before a possible native call."""
    operation = str(operation_id or "").strip() or uuid4().hex
    if store is None:
        return NativeDispatchCheckpoint(operation, None, None, UNKNOWN, "RECEIPT_STORE_UNAVAILABLE")
    try:
        generation = str(getattr(store, "generation_id") or "").strip()
        watermark = store.receipt_watermark()
        if not generation or type(watermark) is not int or watermark < 0:
            return NativeDispatchCheckpoint(operation, generation or None, None, UNKNOWN,
                                            "RECEIPT_CHECKPOINT_INVALID")
        return NativeDispatchCheckpoint(operation, generation, watermark, "VALID")
    except Exception:
        return NativeDispatchCheckpoint(operation, None, None, UNKNOWN, "RECEIPT_WATERMARK_UNAVAILABLE")


def native_dispatch_evidence(checkpoint: NativeDispatchCheckpoint, store: Any, *,
                             request_id: str | None, native_boundary_entered: bool,
                             precheck_rejected: bool = False,
                             operation_error: bool = False) -> NativeDispatchEvidence:
    """Evaluate a typed receipt against its exact operation and store lifetime.

    A known pre-native rejection is NOT_DISPATCHED. Missing/stale/corrupt
    evidence is UNKNOWN whenever transmission could have occurred.
    """
    request = str(request_id or "").strip() or None
    operation = checkpoint.operation_id if isinstance(checkpoint, NativeDispatchCheckpoint) else ""
    generation = checkpoint.store_generation if isinstance(checkpoint, NativeDispatchCheckpoint) else None
    watermark = checkpoint.receipt_watermark_before if isinstance(checkpoint, NativeDispatchCheckpoint) else None
    base = dict(operation_id=operation, request_id=request, store_generation=generation,
                checkpoint_status=getattr(checkpoint, "checkpoint_status", UNKNOWN),
                receipt_watermark_before=watermark, receipt_seq=None, receipt_match=False,
                native_boundary_status="UNKNOWN", dispatch_status=UNKNOWN,
                evidence_source="GENERIC_NATIVE_RECEIPT")
    if (type(native_boundary_entered) is not bool
            or type(precheck_rejected) is not bool
            or type(operation_error) is not bool):
        return NativeDispatchEvidence(**base, reason="BOUNDARY_RESULT_UNVERIFIABLE")
    if not isinstance(checkpoint, NativeDispatchCheckpoint) or checkpoint.checkpoint_status != "VALID":
        if precheck_rejected and not native_boundary_entered:
            return NativeDispatchEvidence(**{**base,
                "native_boundary_status": "NOT_ENTERED", "dispatch_status": NOT_DISPATCHED,
            }, reason="PRECHECK_REJECTED_BEFORE_NATIVE_BOUNDARY")
        return NativeDispatchEvidence(**base, reason=getattr(checkpoint, "reason", "CHECKPOINT_UNKNOWN"))
    if (not operation or type(watermark) is not int or watermark < 0
            or store is None or not generation):
        if precheck_rejected and not native_boundary_entered:
            return NativeDispatchEvidence(**{**base,
                "native_boundary_status": "NOT_ENTERED", "dispatch_status": NOT_DISPATCHED,
            }, reason="PRECHECK_REJECTED_BEFORE_NATIVE_BOUNDARY")
        return NativeDispatchEvidence(**base, reason="CHECKPOINT_INCOMPLETE")
    try:
        current_generation = str(getattr(store, "generation_id") or "").strip()
        if current_generation != generation:
            if precheck_rejected and not native_boundary_entered:
                return NativeDispatchEvidence(**{**base,
                    "native_boundary_status": "NOT_ENTERED", "dispatch_status": NOT_DISPATCHED,
                }, reason="PRECHECK_REJECTED_BEFORE_NATIVE_BOUNDARY")
            return NativeDispatchEvidence(**base, reason="STORE_GENERATION_MISMATCH")
        receipts = store.receipts_after(watermark)
    except Exception:
        return NativeDispatchEvidence(**base, reason="RECEIPT_QUERY_FAILED")

    candidates = [row for row in receipts if isinstance(row, Mapping)
                  and row.get("store_generation") == generation
                  and type(row.get("receipt_seq")) is int
                  and row["receipt_seq"] > watermark
                  and row.get("operation_id") == operation
                  and request is not None and row.get("request_id") == request
                  and row.get("native_boundary_status") == "ENTERED"
                  and row.get("dispatch_status") == "NATIVE_DISPATCH_ATTEMPTED"]
    if candidates:
        if precheck_rejected and not native_boundary_entered:
            return NativeDispatchEvidence(**base,
                reason="PRECHECK_CONFLICTING_CURRENT_RECEIPT")
        receipt = candidates[-1]
        return NativeDispatchEvidence(**{**base,
            "receipt_seq": receipt["receipt_seq"], "receipt_match": True,
            "native_boundary_status": "ENTERED", "dispatch_status": DISPATCHED,
        }, reason="CURRENT_OPERATION_RECEIPT" if not operation_error else "CURRENT_OPERATION_RECEIPT_AFTER_ERROR")

    # Precheck rejection is conclusive only when the caller can prove the
    # native boundary was never entered. A stale or unrelated receipt alone
    # cannot be turned into a negative transmission claim.
    if precheck_rejected and not native_boundary_entered:
        return NativeDispatchEvidence(**{**base,
            "native_boundary_status": "NOT_ENTERED", "dispatch_status": NOT_DISPATCHED,
        }, reason="PRECHECK_REJECTED_BEFORE_NATIVE_BOUNDARY")
    return NativeDispatchEvidence(**{**base,
        "native_boundary_status": "ENTERED" if native_boundary_entered else "UNKNOWN",
        "dispatch_status": UNKNOWN,
    }, reason="CURRENT_OPERATION_RECEIPT_UNAVAILABLE")
