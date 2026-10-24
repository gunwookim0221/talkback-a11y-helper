"""Observation-only dispatch clock. No action, reconciliation, or visit authority.

Receipts mean a native dispatch was attempted, not that Android accepted it.
They are recorded after guards and before native IO, including IO failures.
Read-only traffic never advances the action epoch. Unknown shell commands
invalidate conservatively; they cannot establish a known action owner.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from uuid import uuid4

from talkback_lib.native_dispatch_evidence import (
    NativeDispatchReceiptStore,
    OWNERS,
    _history_reset as _native_history_reset,
    classify_dispatch as _classify_dispatch,
    current_dispatch_owner,
    dispatch_owner,
    owned_dispatch,
)


def classify_dispatch(args: list[str]) -> tuple[str, str, str] | None:
    """Compatibility export retained for Phase 6 callers and existing tests."""
    return _classify_dispatch(args)


def _history_reset(args: list[str]) -> bool:
    return _native_history_reset(args)


@dataclass
class EvidenceClock:
    action_epoch: int = 0
    observation_sequence: int = 0
    context_revision: int = 0
    receipts: list[dict[str, Any]] = field(default_factory=list)
    receipt_sequence: int = 0
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
                self.receipt_sequence += 1
                owner = current_dispatch_owner() or inferred
                self.receipts.append({"receipt_seq": self.receipt_sequence,
                                      "action_epoch": self.action_epoch, "action_type": action,
                                      "owner": owner, "ownership_status": "KNOWN" if owner != "OTHER" else "UNRESOLVED",
                                      "request_id": request or None,
                                      "action_id": f"dispatch:{self.scope_id}:{self.action_epoch}",
                                      "dispatch_status": "NATIVE_DISPATCH_ATTEMPTED"})
                del self.receipts[:-2048]
            except Exception:
                self.healthy = False

    def receipt_watermark(self) -> int:
        with self._lock:
            return self.receipt_sequence

    def receipts_after(self, watermark: int, *, request_id: str | None = None) -> list[dict[str, Any]]:
        """Return retained receipts newer than a monotonic sequence watermark."""
        with self._lock:
            request = str(request_id or "").strip()
            return [deepcopy(receipt) for receipt in self.receipts
                    if type(receipt.get("receipt_seq")) is int
                    and receipt["receipt_seq"] > watermark
                    and (not request or str(receipt.get("request_id") or "") == request)]


    def begin_observation(self) -> tuple[str, int, int, int]:
        with self._lock:
            self.observation_sequence += 1
            return self.scope_id, self.action_epoch, self.observation_sequence, self.context_revision

    def finish_observation(self, token: tuple[str, int, int, int]) -> dict[str, Any]:
        with self._lock:
            if not isinstance(token, tuple) or len(token) != 4:
                return {"scope_id": "", "action_epoch": None, "observation_epoch": None,
                        "observation_id": "", "observation_sequence": None,
                        "capture_end_action_epoch": self.action_epoch,
                        "context_revision": None, "capture_complete": False,
                        "action_ownership": deepcopy(self.receipts[-1]) if self.receipts else {
                            "owner": "OTHER", "ownership_status": "UNRESOLVED"}}
            token_scope_id, epoch, sequence, revision = token
            scope_matches = (isinstance(token_scope_id, str) and bool(token_scope_id)
                             and token_scope_id == self.scope_id)
            return {"scope_id": token_scope_id if isinstance(token_scope_id, str) else "",
                    "action_epoch": epoch, "observation_epoch": epoch,
                    "observation_id": f"observation:{token_scope_id}:{sequence}",
                    "observation_sequence": sequence,
                    "capture_end_action_epoch": self.action_epoch,
                    "context_revision": revision,
                    "capture_complete": (self.healthy and scope_matches and epoch == self.action_epoch
                                         and revision == self.context_revision),
                    "action_ownership": deepcopy(self.receipts[-1]) if self.receipts else {
                        "owner": "OTHER", "ownership_status": "UNRESOLVED"}}

    def current(self, observation: Any) -> bool:
        with self._lock:
            if not self.healthy or not isinstance(observation, dict):
                return False
            scope_id = observation.get("scope_id")
            sequence = observation.get("observation_sequence")
            epoch = observation.get("action_epoch")
            return bool(
                isinstance(scope_id, str) and scope_id and scope_id == self.scope_id
                and type(sequence) is int and sequence == self.observation_sequence
                and type(epoch) is int and epoch == self.action_epoch
                and observation.get("observation_epoch") == epoch
                and observation.get("observation_id") == f"observation:{scope_id}:{sequence}"
                and observation.get("capture_end_action_epoch") == epoch
                and observation.get("context_revision") == self.context_revision
                and observation.get("capture_complete") is True
            )


def clock_for(client: Any) -> EvidenceClock | None:
    clock = getattr(getattr(client, "_adb_device", None), "shadow_evidence_clock", None)
    return clock if isinstance(clock, EvidenceClock) else None
