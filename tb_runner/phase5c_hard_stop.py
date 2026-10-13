"""Monotonic Phase 5C scenario hard-stop latch for controlled acceptance runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any


class Phase5CHardStopError(RuntimeError):
    """Raised when new work crosses a committed Phase 5C hard-stop boundary."""


@dataclass
class Phase5CHardStopState:
    scenario: str
    run_id: str
    _record: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    @property
    def latched(self) -> bool:
        with self._lock:
            return self._record is not None

    def latch(self, *, step: int, reasons: list[str], action_id: str) -> dict[str, Any]:
        with self._lock:
            if self._record is None:
                self._record = {
                    "schema": "phase5c-hard-stop-v1",
                    "status": "COMMITTED",
                    "scenario": self.scenario,
                    "run_id": self.run_id,
                    "step": step,
                    "reason": "audit_chain_incomplete",
                    "audit_reasons": sorted(set(reasons)),
                    "step_action_id": action_id,
                    "terminal_status": "INCOMPLETE_ERROR",
                    "terminal_reason": "audit_chain_incomplete",
                    "later_work_permitted": False,
                }
            return dict(self._record)

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._record) if self._record is not None else None

    def guard(self, operation: str) -> None:
        record = self.snapshot()
        if record is not None:
            raise Phase5CHardStopError(
                f"PHASE5C_HARD_STOP:{record['scenario']}:{record['step']}:{operation}"
            )


def commit_audit_hard_stop(*, controller: Phase5CHardStopState, client: Any, state: Any,
                           row: dict[str, Any], step: int, reasons: list[str],
                           action_id: str) -> dict[str, Any]:
    """Latch the audit rejection and mark its already completed production row terminal."""
    record = controller.latch(step=step, reasons=reasons, action_id=action_id)
    client._phase5c_hard_stop_state = controller
    state.stop_triggered = True
    state.stop_reason = record["terminal_reason"]
    state.stop_step = step
    row.update(
        status="END",
        stop_triggered=True,
        stop_step=step,
        stop_reason=record["terminal_reason"],
        scenario_terminal_status=record["terminal_status"],
        scenario_terminal_reason=record["terminal_reason"],
        phase5c_hard_stop=record,
    )
    return record
