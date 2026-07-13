"""Behavior-preserving orchestration for production traversal decisions.

This module owns only coordination and typed decision projection.  Candidate
selection, Android actions, evidence capture, stop thresholds, and row mutation
remain in their existing policy modules and collection flow phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from tb_runner.traversal_evidence_gate import (
    ProgressDecision,
    VisitDecision,
    evaluate_traversal_gate,
)


@dataclass(frozen=True)
class TraversalDecision:
    """The progress and visit projections produced for one closed action."""

    progress: ProgressDecision
    visit: VisitDecision


@dataclass(frozen=True)
class VisitTrackingDecision:
    """Existing planning-consumed and physical-visited meanings for one row."""

    gate_applied: bool
    planning_consumed: bool
    physical_visited: bool


class VisitTracker:
    """Project gate decisions without owning or mutating traversal state."""

    @staticmethod
    def resolve(
        *,
        progress: ProgressDecision | None,
        visit: VisitDecision | None,
        legacy_move_result: str,
    ) -> VisitTrackingDecision:
        gate_applied = bool(progress is not None and progress.gate_applied and visit is not None)
        planning_consumed = bool(visit.consumed) if gate_applied and visit is not None else True
        physical_visited = (
            bool(visit.visited)
            if gate_applied and visit is not None
            else legacy_move_result in {"moved", "scrolled", "edge_realign_then_moved"}
        )
        return VisitTrackingDecision(
            gate_applied=gate_applied,
            planning_consumed=planning_consumed,
            physical_visited=physical_visited,
        )


@dataclass(frozen=True)
class RecoveryOutcome:
    """Typed view of the established recovery executor mapping contract."""

    attempted: bool = False
    recovered: bool = False
    block_stop: bool = False
    row: dict[str, Any] | None = None
    progress: ProgressDecision | None = None
    visit: VisitDecision | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RecoveryOutcome":
        source = value or {}
        return cls(
            attempted=bool(source.get("attempted", False)),
            recovered=bool(source.get("recovered", False)),
            block_stop=bool(source.get("block_stop", False)),
            row=source.get("row") if isinstance(source.get("row"), dict) else None,
            progress=source.get("progress"),
            visit=source.get("visit"),
        )


@dataclass(frozen=True)
class StopPolicy:
    """Recovery eligibility only; stop calculation remains authoritative elsewhere."""

    recovery_reasons: frozenset[str]

    def allows_recovery(self, *, stop: bool, reason: str) -> bool:
        return bool(stop and reason in self.recovery_reasons)


class RecoveryCoordinator:
    """Repeat the existing one-candidate executor until it settles."""

    @staticmethod
    def run(attempt: Callable[[], Mapping[str, Any]]) -> RecoveryOutcome:
        outcome = RecoveryOutcome.from_mapping(attempt())
        while outcome.attempted and outcome.block_stop and not outcome.recovered:
            outcome = RecoveryOutcome.from_mapping(attempt())
        return outcome


@dataclass(frozen=True)
class RecoveryExecutionServices:
    """Injected seams for the established recovery action implementation."""

    enabled: Callable[[], bool]
    select_candidate: Callable[[], Any | None]
    resolve_decision: Callable[[dict[str, Any]], tuple[ProgressDecision | None, VisitDecision | None]]
    emit_evidence: Callable[[dict[str, Any], str, str, dict[str, Any]], None]
    capture_crop: Callable[[Any, str, dict[str, Any], str], dict[str, Any]]
    register_inventory: Callable[[dict[str, Any]], None]
    log: Callable[[str], None]
    truncate: Callable[[str, int], str]
    monotonic: Callable[[], float]
    action_wait_seconds: float


class RecoveryExecutor:
    """Execute one existing FOCUS_IN_BOUNDS recovery attempt unchanged."""

    @staticmethod
    def execute(
        *,
        client: Any,
        dev: str,
        phase_ctx: Any,
        state: Any,
        row: dict[str, Any],
        step_idx: int,
        services: RecoveryExecutionServices,
    ) -> dict[str, Any]:
        outcome: dict[str, Any] = {
            "attempted": False,
            "recovered": False,
            "block_stop": False,
            "row": None,
            "progress": None,
            "visit": None,
        }
        if not services.enabled():
            return outcome
        candidate = services.select_candidate()
        if candidate is None:
            return outcome

        begin_target_action = getattr(client, "_evidence_begin_target_action", None)
        set_evidence_step = getattr(client, "_evidence_set_step", None)
        if not callable(begin_target_action):
            services.log("[TRAVERSAL_V2][recovery_skip] reason='evidence_transaction_unavailable'")
            return outcome

        recovery_number = state.traversal_diagnostics.recovered_candidate_attempts + 1
        recovery_step_key = f"{step_idx}:recovery:{recovery_number}"
        if callable(set_evidence_step):
            try:
                set_evidence_step(recovery_step_key, phase="recovery")
            except Exception:
                pass
        transaction = begin_target_action(
            "FOCUS_IN_BOUNDS",
            requested_target=candidate.requested_observation(),
            phase="recovery",
        )
        if not transaction:
            services.log("[TRAVERSAL_V2][recovery_skip] reason='evidence_transaction_not_opened'")
            return outcome

        state.recovery_attempted_candidate_ids.update({candidate.candidate_id, candidate.canonical_key})
        state.traversal_diagnostics = state.traversal_diagnostics.record_recovery_attempt()
        outcome["attempted"] = True
        bounds = ",".join(str(value) for value in candidate.bounds)
        services.log(
            f"[TRAVERSAL_V2][recovery_attempt] step={step_idx} candidate='{candidate.candidate_id}' "
            f"label='{services.truncate(candidate.label, 96)}' bounds='{bounds}'"
        )

        action_result: dict[str, Any] = {}
        recovery_row: dict[str, Any] | None = None
        try:
            action_result = client.focus_in_bounds(
                dev=dev,
                bounds=bounds,
                wait_=services.action_wait_seconds,
                prefer_empty_state=False,
                exclude_top_chrome=True,
                exclude_bottom_nav=True,
            )
            recovery_row = client.collect_focus_step(
                dev=dev,
                step_index=recovery_step_key,
                move=False,
                direction="next",
                wait_seconds=phase_ctx.main_step_wait_seconds,
                announcement_wait_seconds=phase_ctx.main_announcement_wait_seconds,
                announcement_idle_wait_seconds=phase_ctx.main_announcement_idle_wait_seconds,
                announcement_max_extra_wait_seconds=phase_ctx.main_announcement_max_extra_wait_seconds,
            )
        except Exception as exc:
            services.log(
                f"[TRAVERSAL_V2][recovery_error] candidate='{candidate.candidate_id}' "
                f"error='{type(exc).__name__}'"
            )
            runtime = getattr(client, "evidence_runtime", None)
            active = getattr(client, "_evidence_active_transaction", None)
            if runtime is not None and active:
                try:
                    runtime.close_transaction(
                        active,
                        status="failed",
                        phase="recovery",
                        payload={"reason": type(exc).__name__},
                    )
                except Exception:
                    pass
                setattr(client, "_evidence_active_transaction", None)

        if not isinstance(recovery_row, dict):
            state.recovery_hard_failed_candidate_ids.update({candidate.candidate_id, candidate.canonical_key})
        else:
            recovery_row["tab_name"] = phase_ctx.tab_cfg["tab_name"]
            recovery_row["context_type"] = "main"
            recovery_row["parent_step_index"] = ""
            recovery_row["overlay_entry_label"] = ""
            recovery_row["overlay_recovery_status"] = ""
            recovery_row["status"] = "OK"
            recovery_row["stop_reason"] = ""
            recovery_row["scenario_type"] = str(phase_ctx.tab_cfg.get("scenario_type", "content") or "content")
            recovery_row["scenario_id"] = str(phase_ctx.tab_cfg.get("scenario_id", "") or "")
            recovery_row["last_smart_nav_result"] = ""
            recovery_row["last_smart_nav_detail"] = ""
            recovery_row["last_smart_nav_terminal"] = False
            progress, visit = services.resolve_decision(recovery_row)
            outcome["progress"] = progress
            outcome["visit"] = visit
            strong_recovery = bool(
                progress is not None
                and visit is not None
                and progress.gate_applied
                and progress.verdict == "MOVE_CONFIRMED"
                and progress.physical_progress is True
                and visit.visited
            )
            services.emit_evidence(
                recovery_row,
                "RECOVERY_CANDIDATE_RESULT",
                "recovery",
                {
                    "candidate": candidate.to_payload(),
                    "helper_success": bool(action_result.get("success")),
                    "strong_recovery": strong_recovery,
                    "progress_reason": progress.reason if progress is not None else "unavailable",
                },
            )
            if strong_recovery:
                recovery_row["move_result"] = "moved"
                recovery_row["step_index"] = step_idx
                recovery_row["crop_image"] = "IMAGE"
                recovery_row["_step_mono_start"] = services.monotonic() - float(
                    recovery_row.get("t_step_start", 0.0) or 0.0
                )
                recovery_row = services.capture_crop(client, dev, recovery_row, phase_ctx.output_base_dir)
                recovery_row.pop("_step_mono_start", None)
                services.register_inventory(recovery_row)
                state.recovery_visited_candidate_ids.update({candidate.candidate_id, candidate.canonical_key})
                state.traversal_diagnostics = (
                    state.traversal_diagnostics.record_recovery_visit().record_stop_prevented()
                )
                outcome.update({"recovered": True, "block_stop": True, "row": recovery_row})
                return outcome
            if bool(action_result.get("success")) is False or (
                progress is not None and progress.gate_applied and progress.verdict == "STATIC_FOCUS"
            ):
                state.recovery_hard_failed_candidate_ids.update({candidate.candidate_id, candidate.canonical_key})

        remaining = services.select_candidate()
        if remaining is not None:
            outcome["block_stop"] = True
            services.log(
                "[TRAVERSAL_V2][recovery_continue] "
                "reason='eligible_recovery_candidate_remaining' "
                f"next_candidate='{remaining.candidate_id}'"
            )
        return outcome


class TraversalCoordinator:
    """Facade used by collection_flow while it remains the outer orchestrator."""

    def __init__(self, *, stop_policy: StopPolicy) -> None:
        self.stop_policy = stop_policy

    @staticmethod
    def resolve_decision(
        *,
        result: dict[str, Any] | None,
        transaction_id: str,
        evidence_transaction_id: str,
        legacy_progressed: bool,
        row: dict[str, Any],
    ) -> TraversalDecision:
        progress, visit = evaluate_traversal_gate(
            result,
            transaction_id=transaction_id,
            evidence_transaction_id=evidence_transaction_id,
            legacy_progressed=legacy_progressed,
            legacy_visited=legacy_progressed,
            # Consumption records the planning attempt and remains distinct
            # from physical visit credit.
            legacy_consumed=True,
            row=row,
            enabled=True,
        )
        return TraversalDecision(progress=progress, visit=visit)

    def recover(
        self,
        *,
        stop: bool,
        reason: str,
        attempt: Callable[[], Mapping[str, Any]],
    ) -> RecoveryOutcome | None:
        if not self.stop_policy.allows_recovery(stop=stop, reason=reason):
            return None
        return RecoveryCoordinator.run(attempt)


TRAVERSAL_V2_STOP_POLICY = StopPolicy(
    recovery_reasons=frozenset(
        {
            "repeat_no_progress",
            "bounded_two_card_loop",
            "repeat_semantic_stall",
            "repeat_semantic_stall_after_escape",
        }
    )
)
TRAVERSAL_COORDINATOR = TraversalCoordinator(stop_policy=TRAVERSAL_V2_STOP_POLICY)


__all__ = [
    "RecoveryCoordinator",
    "RecoveryExecutionServices",
    "RecoveryExecutor",
    "RecoveryOutcome",
    "StopPolicy",
    "TRAVERSAL_COORDINATOR",
    "TRAVERSAL_V2_STOP_POLICY",
    "TraversalCoordinator",
    "TraversalDecision",
    "VisitTracker",
    "VisitTrackingDecision",
]
