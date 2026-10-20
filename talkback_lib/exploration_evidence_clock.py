"""Observation-only dispatch clock. No action, reconciliation, or visit authority.

Receipts mean a native dispatch was attempted, not that Android accepted it.
They are recorded after guards and before native IO, including IO failures.
Read-only traffic never advances the action epoch. Unknown shell commands
invalidate conservatively; they cannot establish a known action owner.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
import shlex
from uuid import uuid4

_owner = ContextVar("exploration_dispatch_owner", default="")
OWNERS = {"PRIMARY", "SEQUENTIAL", "TARGETED", "FALLBACK", "RECOVERY",
          "OPTIONAL_EXPANSION", "POPUP", "TAB", "OTHER"}
_READ_ACTIONS = {"DUMP_TREE", "DUMP_HIERARCHY", "GET_FOCUS", "CHECK_TARGET",
                 "PING", "RESOLVE_EXACT_NODE", "EVIDENCE_EVENTS", "ENTRY_CLICK_CAPTURE",
                 "HIERARCHY_TRANSFER_CAPABILITIES", "HIERARCHY_TRANSFER_START",
                 "HIERARCHY_TRANSFER_STATUS", "HIERARCHY_TRANSFER_ACK", "HIERARCHY_TRANSFER_CANCEL"}


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


@dataclass
class EvidenceClock:
    action_epoch: int = 0
    observation_sequence: int = 0
    context_revision: int = 0
    receipts: list[dict[str, Any]] = field(default_factory=list)
    healthy: bool = True
    # Correlation scope only. This never enters production target identity.
    scope_id: str = field(default_factory=lambda: uuid4().hex)
    _lock: Any = field(default_factory=RLock, repr=False)

    def dispatch(self, args: list[str]) -> None:
        with self._lock:
            try:
                if _history_reset(args):
                    # This changes planner history, not the physical UI. Keep
                    # action epoch honest while expiring old evidence context.
                    self.context_revision += 1
                    return
                classified = classify_dispatch(args)
                if classified is None:
                    return
                action, inferred, request = classified
                self.action_epoch += 1
                owner = _owner.get() or inferred
                self.receipts.append({"action_epoch": self.action_epoch, "action_type": action,
                                      "owner": owner, "ownership_status": "KNOWN" if owner != "OTHER" else "UNRESOLVED",
                                      "request_id": request or None,
                                      "action_id": f"dispatch:{self.scope_id}:{self.action_epoch}",
                                      "dispatch_status": "NATIVE_DISPATCH_ATTEMPTED"})
                del self.receipts[:-2048]
            except Exception:
                self.healthy = False

    def begin_observation(self) -> tuple[int, int, int]:
        with self._lock:
            self.observation_sequence += 1
            return self.action_epoch, self.observation_sequence, self.context_revision

    def finish_observation(self, token: tuple[int, int, int]) -> dict[str, Any]:
        with self._lock:
            epoch, sequence, revision = token
            return {"action_epoch": epoch, "observation_epoch": epoch,
                    "observation_id": f"observation:{self.scope_id}:{sequence}", "observation_sequence": sequence,
                    "capture_end_action_epoch": self.action_epoch,
                    "context_revision": revision,
                    "capture_complete": self.healthy and epoch == self.action_epoch and revision == self.context_revision,
                    "action_ownership": deepcopy(self.receipts[-1]) if self.receipts else {
                        "owner": "OTHER", "ownership_status": "UNRESOLVED"}}

    def current(self, observation: Any) -> bool:
        with self._lock:
            return bool(self.healthy and isinstance(observation, dict)
                        and observation.get("capture_complete") is True
                        and type(observation.get("action_epoch")) is int
                        and observation["action_epoch"] == self.action_epoch
                        and observation.get("context_revision") == self.context_revision
                        and type(observation.get("observation_sequence")) is int
                        and observation.get("observation_sequence") == self.observation_sequence)


def clock_for(client: Any) -> EvidenceClock | None:
    clock = getattr(getattr(client, "_adb_device", None), "shadow_evidence_clock", None)
    return clock if isinstance(clock, EvidenceClock) else None


@contextmanager
def dispatch_owner(owner: str):
    """Label an existing production scope; this neither dispatches nor consumes permits."""
    token = _owner.set(owner if owner in OWNERS else "OTHER")
    try:
        yield
    finally:
        _owner.reset(token)


def owned_dispatch(owner: str):
    from functools import wraps
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with dispatch_owner(owner):
                return function(*args, **kwargs)
        return wrapped
    return decorate
