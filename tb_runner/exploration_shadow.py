"""Phase 6D2 bounded SHADOW adapter for the pure exploration evaluator.

The adapter accepts only already-collected production observations. It never
dispatches actions, changes production stop decisions, or grants visits. A
decision is staged before production terminal commit and its proposed history
is committed only after later same-step actions are known not to have made the
snapshot stale.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json_bytes
from tb_runner.exploration_progress import (
    ExplorationDecision, ExplorationHistory, ExplorationPolicy,
    evaluate_exploration_progress, history_to_dict,
)
from tb_runner.state_graph import GraphMode, graph_mode_from_environment


EXPLORATION_SHADOW_SCHEMA_VERSION = "phase6-exploration-shadow.v1"
MAX_DECISIONS = 2_048
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_FAILURES = 128
_SOFT_STOP_REASONS = {
    "repeat_no_progress", "bounded_two_card_loop", "repeat_semantic_stall",
    "repeat_semantic_stall_after_escape", "content_no_progress",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(value: Any) -> int | None:
    return value if type(value) is int else None


def _dict(value: Any) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def normalize_production_decision(*, row: Mapping[str, Any], stop_candidate: bool,
                                  stop_reason: str, final_terminal: bool,
                                  recovery_occurred: bool = False) -> dict[str, Any]:
    """Describe the already-made production outcome without rewriting it."""
    reason = _text(stop_reason or row.get("stop_reason"))
    if recovery_occurred:
        outcome = "PRODUCTION_RECOVERY"
    elif isinstance(row.get("scroll_transition"), Mapping):
        outcome = "PRODUCTION_SCROLL_CONTINUE"
    elif final_terminal:
        outcome = "PRODUCTION_TERMINATED"
    elif stop_candidate:
        outcome = "PRODUCTION_STOP_CANDIDATE"
    else:
        outcome = "CONTINUE"
    return {
        "outcome": outcome,
        "stop_candidate": bool(stop_candidate),
        "stop_candidate_reason": reason if stop_candidate else "",
        "final_terminal": bool(final_terminal),
        "final_terminal_reason": reason if final_terminal else "",
        "production_status": _text(row.get("status")),
        "production_final_result": _text(row.get("final_result")),
    }


def compare_production_and_shadow(*, production: Mapping[str, Any],
                                  shadow_decision: str,
                                  frontier_status: str,
                                  hard_bound_reached: bool = False,
                                  stale: bool = False,
                                  comparable_scope: bool = True,
                                  comparable_stage: bool = True) -> tuple[str, str]:
    if stale:
        return "STALE_EVIDENCE", "POST_ACTION_SNAPSHOT_INVALIDATED"
    if not comparable_scope:
        return "NOT_COMPARABLE_SCOPE", "EXPLORATION_SCOPE_MISMATCH"
    if not comparable_stage:
        return "NOT_COMPARABLE_STAGE", "DECISION_STAGE_MISMATCH"
    outcome = _text(production.get("outcome")).upper()
    reason = _text(production.get("final_terminal_reason") or production.get("stop_candidate_reason")).lower()
    stopped = outcome == "PRODUCTION_TERMINATED"
    if stopped and production.get("authoritative_error") is True:
        if shadow_decision == ExplorationDecision.TERMINATE_ERROR.value:
            return "SAME_INTENT", "ERROR_TERMINAL_MATCH"
        return "SHADOW_ERROR_PRECEDENCE_MISMATCH", "PRODUCTION_ERROR_HAS_PRIORITY"
    if shadow_decision == ExplorationDecision.COMPLETE_CURRENT_SCOPE.value:
        return (("SAME_INTENT", "SCOPE_TERMINAL_MATCH") if stopped else
                ("SHADOW_COMPLETE_PRODUCTION_CONTINUED", "SCOPE_COMPLETE_RECOMMENDED"))
    if shadow_decision == ExplorationDecision.REDIRECT_FRONTIER.value:
        return (("SHADOW_REDIRECT_PRODUCTION_SOFT_STOP", "FRONTIER_REMAINS_AFTER_SOFT_STOP") if stopped else
                ("SHADOW_REDIRECT_PRODUCTION_CONTINUED", "FRONTIER_REDIRECT_RECOMMENDED"))
    if shadow_decision == ExplorationDecision.CONTINUE.value and stopped:
        return "SHADOW_CONTINUE_PRODUCTION_SOFT_STOP", "SHADOW_CONTINUE_AFTER_PRODUCTION_STOP"
    if (shadow_decision == ExplorationDecision.TERMINATE_HARD_BOUND.value
            and stopped and hard_bound_reached):
        return "SAME_INTENT", "MAX_STEPS_BOUND_MATCH"
    if shadow_decision in {
        ExplorationDecision.TERMINATE_INCOMPLETE_POLICY_LIMIT.value,
        ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN.value,
        ExplorationDecision.TERMINATE_INCOMPLETE_NO_PROGRESS.value,
        ExplorationDecision.TERMINATE_HARD_BOUND.value,
        ExplorationDecision.TERMINATE_SAFETY_LIMIT.value,
        ExplorationDecision.TERMINATE_ERROR.value,
    }:
        if stopped and reason in {"safety_limit", "possible_crash", "crash", "fatal", "app_terminated"}:
            return "SAME_INTENT", "PRIORITY_TERMINAL_CLASS_MATCH"
        return (("SHADOW_UNKNOWN_PRODUCTION_STOP", "SHADOW_TERMINAL_RECOMMENDATION") if stopped else
                ("UNKNOWN", "SHADOW_TERMINAL_RECOMMENDATION_NOT_COMMITTED"))
    if frontier_status == "UNKNOWN":
        return (("SHADOW_UNKNOWN_PRODUCTION_STOP", "FRONTIER_UNKNOWN") if stopped else
                ("UNKNOWN", "FRONTIER_UNKNOWN"))
    return "UNKNOWN", "SEMANTIC_INTENT_NOT_COMPARABLE"


@dataclass
class _PendingDecision:
    token: str
    decision_id: str
    watermark: int
    step: int
    evaluation: Any
    record: dict[str, Any]
    production: dict[str, Any]
    frontier: dict[str, Any]
    stale_reasons: list[str]
    state_was_plateaued: bool
    run_was_plateaued: bool


@dataclass
class ExplorationShadowRuntime:
    run_id: str
    scenario_id: str
    enabled: bool = True
    policy: ExplorationPolicy = field(default_factory=ExplorationPolicy)
    history: ExplorationHistory = field(default_factory=ExplorationHistory)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=lambda: {
        "MEANINGFUL_PROGRESS_COUNT": 0,
        "CURSOR_ONLY_PROGRESS_COUNT": 0,
        "REVISIT_WITH_FRONTIER_AVAILABLE_COUNT": 0,
        "PRODUCTION_TERMINATED_WITH_FRONTIER_NO_COUNT": 0,
        "PLATEAU_ENTRY_COUNT": 0,
        "PLATEAU_EXIT_COUNT": 0,
        "STATE_PLATEAU_ENTRY_COUNT": 0,
        "STATE_PLATEAU_EXIT_COUNT": 0,
        "RUN_PLATEAU_ENTRY_COUNT": 0,
        "RUN_PLATEAU_EXIT_COUNT": 0,
        "SHADOW_REDIRECT_RECOMMENDATION_COUNT": 0,
        "SHADOW_TERMINATE_RECOMMENDATION_COUNT": 0,
        "SHADOW_SCOPE_COMPLETE_COUNT": 0,
        "VALID_CLOSED_DECISION_COUNT": 0,
        "STALE_DECISION_COUNT": 0,
    })
    failures: list[dict[str, Any]] = field(default_factory=list)
    truncation_reasons: set[str] = field(default_factory=set)
    _pending: dict[str, _PendingDecision] = field(default_factory=dict, repr=False)
    _seen_decision_ids: set[str] = field(default_factory=set, repr=False)
    _seen_watermarks: set[int] = field(default_factory=set, repr=False)

    @classmethod
    def for_run(cls, *, run_id: str, scenario_id: str,
                environ: Mapping[str, str] | None = None) -> "ExplorationShadowRuntime | None":
        if graph_mode_from_environment(environ) != GraphMode.SHADOW:
            return None
        return cls(run_id=run_id, scenario_id=scenario_id)

    def _fail(self, phase: str, exc: BaseException, *, step: int | None = None) -> None:
        if len(self.failures) < MAX_FAILURES:
            self.failures.append({"phase": phase, "step": step,
                                  "error_type": type(exc).__name__})
        else:
            self.truncation_reasons.add("MAX_SHADOW_FAILURES")

    def prepare_decision(self, *, decision_id: str, step: int, watermark: int,
                         current_state: Mapping[str, Any],
                         frontier_evaluation: Mapping[str, Any],
                         production_result: Mapping[str, Any],
                         repetition_state: Mapping[str, Any] | None = None,
                         scroll_evidence: Mapping[str, Any] | None = None,
                         safety_state: Mapping[str, Any] | None = None,
                         hard_bounds: Mapping[str, Any] | None = None,
                         recovery_budget: Mapping[str, Any] | None = None,
                         production_stop_candidate: Mapping[str, Any] | None = None,
                         stale_reasons: list[str] | tuple[str, ...] = ()) -> str | None:
        """Stage one result before terminal commit; history commits at finalize."""
        if not self.enabled:
            return None
        try:
            decision_id = _text(decision_id)
            step, watermark = int(step), int(watermark)
            if len(self.decisions) + len(self._pending) >= MAX_DECISIONS:
                self.truncation_reasons.add("MAX_DECISIONS")
                return None
            stale = list(sorted(set(_text(item) for item in stale_reasons if _text(item))))
            if decision_id in self._seen_decision_ids or watermark in self._seen_watermarks:
                stale.append("DUPLICATE_DECISION_OR_WATERMARK")
            if watermark <= self.history.last_decision_watermark:
                stale.append("NON_MONOTONIC_DECISION_WATERMARK")
            if not decision_id:
                stale.append("DECISION_ID_MISSING")
                decision_id = f"phase6d:missing:{step}:{watermark}"
            self._seen_decision_ids.add(decision_id)
            self._seen_watermarks.add(watermark)

            current = _dict(current_state)
            frontier = _dict(frontier_evaluation)
            production = _dict(production_result)
            if (_text(current.get("evidence_stage", current.get("stage"))).upper()
                    not in {"POST_ACTION", "CLOSED_DECISION", "AFTER_ACTION"}):
                stale.append("CURRENT_STATE_NOT_POST_ACTION")
            if (_text(frontier.get("evidence_stage", frontier.get("stage"))).upper()
                    not in {"POST_ACTION", "CLOSED_DECISION", "AFTER_ACTION"}):
                stale.append("FRONTIER_NOT_POST_ACTION")
            if (_int(current.get("evidence_watermark", current.get("decision_watermark", current.get("watermark"))))
                    != watermark):
                stale.append("CURRENT_STATE_WATERMARK_MISMATCH")
            if (_int(frontier.get("evidence_watermark", frontier.get("decision_watermark", frontier.get("watermark"))))
                    != watermark):
                stale.append("FRONTIER_WATERMARK_MISMATCH")
            if _text(current.get("decision_id")) not in {"", decision_id}:
                stale.append("CURRENT_STATE_DECISION_ID_MISMATCH")
            if _text(frontier.get("decision_id")) not in {"", decision_id}:
                stale.append("FRONTIER_DECISION_ID_MISMATCH")
            if (_text(production.get("decision_id")) != decision_id
                    or _int(production.get("decision_watermark", production.get("watermark"))) != watermark
                    or _int(production.get("decision_step", production.get("step"))) != step
                    or production.get("decision_closed") is not True
                    or _text(production.get("decision_stage", production.get("stage"))).upper()
                       not in {"POST_ACTION", "CLOSED_DECISION", "AFTER_ACTION"}):
                stale.append("PRODUCTION_DECISION_IDENTITY_MISMATCH")
            if _text(frontier.get("alignment_status")).upper() == "STALE":
                stale.append("FRONTIER_SNAPSHOT_STALE")
            current_state_id = _text(current.get("state_id"))
            frontier_state_id = _text(frontier.get("state_id"))
            if current_state_id and frontier_state_id != current_state_id:
                stale.append("FRONTIER_STATE_ID_MISMATCH")
            if _int(frontier.get("source_step")) != step:
                stale.append("FRONTIER_SOURCE_STEP_MISMATCH")
            stale = sorted(set(stale))
            if stale:
                current["evidence_stage"] = "STALE"
                frontier["evidence_stage"] = "STALE"
                frontier["frontier_exhausted"] = "UNKNOWN"
                frontier["evidence_complete"] = False
                production["decision_closed"] = False
            evaluation = evaluate_exploration_progress(
                current_state=current,
                frontier_evaluation=frontier,
                production_result=production,
                progress_history=self.history,
                repetition_state=repetition_state,
                scroll_evidence=scroll_evidence,
                safety_state=safety_state,
                hard_bounds=hard_bounds,
                recovery_budget=recovery_budget,
                policy=self.policy,
            )
            previous_state = self.history.state_plateau(_text(current.get("state_id")))
            state_was_plateaued = bool(
                previous_state and previous_state.age >= self.policy.state_plateau_threshold)
            run_was_plateaued = self.history.run_plateau_age >= self.policy.run_plateau_threshold
            # Pending storage needs a unique in-memory key even when two bad
            # callers submit the same decision concurrently. The stable
            # decision identity remains in the evidence; this suffix is only
            # an internal transaction discriminator.
            token = f"{decision_id}@{watermark}#{len(self.decisions) + len(self._pending) + 1}"
            evaluation_doc = evaluation.to_dict()
            evaluation_doc.pop("proposed_history", None)
            record = {
                "decision_id": decision_id,
                "decision_watermark": watermark,
                "step": step,
                "decision_stage": "POST_RESULT_N",
                "pre_decision_ref": _text(production.get("pre_decision_ref")) or None,
                "next_decision_step": step + 1,
                "state": {
                    "state_id": current.get("state_id"),
                    "identity_status": current.get("state_resolution", "UNRESOLVED"),
                    "evidence_stage": current.get("evidence_stage"),
                    "evidence_watermark": current.get("evidence_watermark"),
                },
                "scope": evaluation.scope,
                "frontier_evaluation_ref": {
                    "decision_id": frontier.get("decision_id"),
                    "source_step": frontier.get("source_step"),
                    "state_id": frontier.get("state_id"),
                    "stage": frontier.get("evidence_stage"),
                    "alignment_status": frontier.get("alignment_status"),
                },
                "frontier": {
                    "frontier_exhausted": evaluation.frontier_exhausted,
                    "exhaustion_scope": frontier.get("exhaustion_scope"),
                    "evidence_complete": evaluation.evidence_complete,
                    "counts": {
                        "eligible_count": evaluation.eligible_count,
                        "unknown_count": evaluation.unknown_count,
                        "never_attempted_count": evaluation.never_attempted_count,
                        "retryable_count": evaluation.retryable_count,
                        "revisit_only_count": evaluation.revisit_only_count,
                        "policy_limited_count": evaluation.policy_limited_count,
                        "blocked_count": ((frontier.get("counts") or {}).get("blocked_count", 0)
                                          if isinstance(frontier.get("counts"), Mapping) else 0),
                    },
                    "exhaustion_reason_codes": deepcopy(frontier.get("exhaustion_reason_codes") or []),
                    "blocked_reason_summary": _dict(frontier.get("blocked_reason_summary")),
                    "policy_limit_summary": _dict(frontier.get("policy_limit_summary")),
                    "truncation_summary": _dict(frontier.get("truncation_summary")),
                    "truncated": frontier.get("truncated") is True,
                },
                "progress_events": list(evaluation.progress_types and
                                         (item.value for item in evaluation.progress_types) or ()),
                "progress_reasons": list(evaluation.reason_codes),
                "state_plateau_age": evaluation.state_plateau_age,
                "run_plateau_age": evaluation.run_plateau_age,
                "state_last_meaningful_progress_step": evaluation.state_last_meaningful_progress_step,
                "run_last_meaningful_progress_step": evaluation.run_last_meaningful_progress_step,
                "thresholds": {"state": evaluation.state_plateau_threshold,
                               "run": evaluation.run_plateau_threshold},
                "scroll_evidence": _dict(scroll_evidence),
                "hard_bound_evidence": _dict(hard_bounds),
                "safety_evidence": _dict(safety_state),
                "error_evidence": {
                    "authoritative_error": production.get("authoritative_error") is True,
                    "error_code": _text(production.get("error_code")) or None,
                },
                "production_stop_candidate": _dict(production_stop_candidate),
                "production": {
                    key: deepcopy(production.get(key)) for key in (
                        "outcome", "stop_candidate", "stop_candidate_reason", "final_terminal",
                        "final_terminal_reason", "production_status", "production_final_result",
                        "authoritative_error", "error_code",
                    ) if key in production
                },
                "shadow_decision": evaluation.decision.value,
                "comparison_category": "PENDING_FINAL_TERMINAL_COMMIT",
                "comparison_reason": "AWAITING_POST_ACTION_INVALIDATION_CHECK",
                "stale_status": "PENDING",
                "stale_reasons": stale,
                "metrics_delta": dict(evaluation.metrics_delta),
                "evaluation": evaluation_doc,
            }
            self._pending[token] = _PendingDecision(
                token=token, decision_id=decision_id, watermark=watermark, step=step,
                evaluation=evaluation, record=record, production=production,
                frontier=frontier, stale_reasons=stale,
                state_was_plateaued=state_was_plateaued,
                run_was_plateaued=run_was_plateaued,
            )
            return token
        except Exception as exc:  # SHADOW errors are isolated from production.
            self._fail("prepare_decision", exc, step=step if type(step) is int else None)
            return None

    def finalize_decision(self, *, token: str | None,
                          final_terminal: bool,
                          final_terminal_reason: str = "",
                          final_error: bool = False,
                          snapshot_invalidated: bool = False,
                          invalidation_reason: str = "") -> bool:
        """Commit shadow history only if no later action invalidated its evidence."""
        if not self.enabled or not token:
            return False
        pending = self._pending.pop(token, None)
        if pending is None:
            return False
        try:
            record = pending.record
            production = dict(pending.production)
            production["final_terminal"] = bool(final_terminal)
            production["final_terminal_reason"] = _text(final_terminal_reason)
            if final_terminal:
                production["outcome"] = "PRODUCTION_TERMINATED"
            if final_error:
                production.update(authoritative_error=True, error_stop=True,
                                  error_code=_text(final_terminal_reason) or "AUTHORITATIVE_PRODUCTION_ERROR")
            stale_reasons = list(pending.stale_reasons)
            if snapshot_invalidated:
                stale_reasons.append(_text(invalidation_reason) or "POST_ACTION_SNAPSHOT_INVALIDATED")
            stale_reasons = sorted(set(stale_reasons))
            evaluation = pending.evaluation
            shadow_decision = evaluation.decision.value
            valid = not stale_reasons and evaluation.proposed_history.last_decision_watermark == pending.watermark
            if valid:
                self.history = evaluation.proposed_history
                self.metrics["VALID_CLOSED_DECISION_COUNT"] += 1
                self._accumulate_metrics(pending, final_terminal=final_terminal,
                                         final_terminal_reason=final_terminal_reason)
                record["stale_status"] = "NO"
                record["stale_reasons"] = []
            else:
                self.metrics["STALE_DECISION_COUNT"] += 1
                record["stale_status"] = "YES"
                record["stale_reasons"] = stale_reasons or ["HISTORY_WATERMARK_NOT_COMMITTED"]
                record["original_shadow_decision"] = shadow_decision
                record["shadow_decision"] = "UNKNOWN"
                record["decision_evidence_usable"] = False
            record["production"]["final_terminal"] = bool(final_terminal)
            record["production"]["final_terminal_reason"] = _text(final_terminal_reason)
            if final_terminal:
                record["production"]["outcome"] = "PRODUCTION_TERMINATED"
            elif record["production"].get("outcome") == "PRODUCTION_TERMINATED":
                record["production"]["outcome"] = (
                    "PRODUCTION_STOP_CANDIDATE" if record["production"].get("stop_candidate") is True
                    else "CONTINUE")
            if final_error:
                record["production"].update(authoritative_error=True,
                    error_code=_text(final_terminal_reason) or "AUTHORITATIVE_PRODUCTION_ERROR")
                record["error_evidence"] = {
                    "authoritative_error": True,
                    "error_code": _text(final_terminal_reason) or "AUTHORITATIVE_PRODUCTION_ERROR",
                }
            if valid:
                category, reason = compare_production_and_shadow(
                    production=production, shadow_decision=shadow_decision,
                    frontier_status=evaluation.frontier_exhausted,
                    hard_bound_reached=dict(evaluation.hard_bound_summary).get("reached") is True,
                    comparable_scope=record.get("scope") == "CURRENT_STATE_CANDIDATE_FOCUS",
                    comparable_stage=record.get("decision_stage") == "POST_RESULT_N",
                )
            else:
                category, reason = "STALE_EVIDENCE", ";".join(record["stale_reasons"])
            record["comparison_category"] = category
            record["comparison_reason"] = reason
            record["decision_evidence_usable"] = bool(valid)
            self.decisions.append(record)
            return valid
        except Exception as exc:  # SHADOW errors are isolated from production.
            self._fail("finalize_decision", exc, step=pending.step)
            return False

    def _accumulate_metrics(self, pending: _PendingDecision, *, final_terminal: bool,
                            final_terminal_reason: str) -> None:
        evaluation = pending.evaluation
        delta = dict(evaluation.metrics_delta)
        for key in ("MEANINGFUL_PROGRESS_COUNT", "CURSOR_ONLY_PROGRESS_COUNT",
                    "SHADOW_REDIRECT_RECOMMENDATION_COUNT",
                    "SHADOW_TERMINATE_RECOMMENDATION_COUNT"):
            self.metrics[key] += max(0, int(delta.get(key, 0) or 0))
        if evaluation.decision == ExplorationDecision.COMPLETE_CURRENT_SCOPE:
            self.metrics["SHADOW_SCOPE_COMPLETE_COUNT"] += 1
        state_is_plateaued = bool(
            evaluation.state_plateau_age is not None
            and evaluation.state_plateau_age >= evaluation.state_plateau_threshold)
        run_is_plateaued = evaluation.run_plateau_age >= evaluation.run_plateau_threshold
        state_entry = not pending.state_was_plateaued and state_is_plateaued
        run_entry = not pending.run_was_plateaued and run_is_plateaued
        state_exit = pending.state_was_plateaued and not state_is_plateaued
        run_exit = pending.run_was_plateaued and not run_is_plateaued
        self.metrics["PLATEAU_ENTRY_COUNT"] += int(state_entry or run_entry)
        self.metrics["PLATEAU_EXIT_COUNT"] += int(state_exit or run_exit)
        self.metrics["STATE_PLATEAU_ENTRY_COUNT"] += int(state_entry)
        self.metrics["RUN_PLATEAU_ENTRY_COUNT"] += int(run_entry)
        self.metrics["STATE_PLATEAU_EXIT_COUNT"] += int(state_exit)
        self.metrics["RUN_PLATEAU_EXIT_COUNT"] += int(run_exit)

        frontier = pending.frontier
        frontier_counts = frontier.get("counts") if isinstance(frontier.get("counts"), Mapping) else {}
        frontier_complete = (frontier.get("evidence_complete") is True
                             and frontier.get("history_complete") is True
                             and frontier.get("inventory_complete") is True
                             and frontier.get("truncated") is not True)
        if (evaluation.frontier_exhausted == "NO" and frontier_complete
                and int(frontier_counts.get("eligible_count", 0) or 0) > 0
                and _text(final_terminal_reason).lower() in _SOFT_STOP_REASONS
                and final_terminal
                and evaluation.decision not in {
                    ExplorationDecision.TERMINATE_SAFETY_LIMIT,
                    ExplorationDecision.TERMINATE_ERROR,
                    ExplorationDecision.TERMINATE_HARD_BOUND,
                }):
            self.metrics["PRODUCTION_TERMINATED_WITH_FRONTIER_NO_COUNT"] += 1

        production = pending.production
        if (evaluation.frontier_exhausted == "NO" and frontier_complete
                and int(frontier_counts.get("eligible_count", 0) or 0) > 0
                and _text(production.get("visit_record_status")).upper() == "ALREADY_VISITED"
                and _text(production.get("visit_authority")).upper() == "PRODUCTION"
                and _text(production.get("visit_instance_id"))
                and _text(production.get("focus_transition_status")).upper() == "CONFIRMED_MOVED"):
            self.metrics["REVISIT_WITH_FRONTIER_AVAILABLE_COUNT"] += 1

    def artifact(self) -> dict[str, Any]:
        decisions = deepcopy(self.decisions)
        pending_records = []
        for pending in self._pending.values():
            record = deepcopy(pending.record)
            record.update(stale_status="YES", stale_reasons=["DECISION_NOT_FINALIZED"],
                          original_shadow_decision=record.get("shadow_decision"),
                          shadow_decision="UNKNOWN", decision_evidence_usable=False,
                          comparison_category="STALE_EVIDENCE",
                          comparison_reason="DECISION_NOT_FINALIZED")
            pending_records.append(record)
        return {
            "schema_version": EXPLORATION_SHADOW_SCHEMA_VERSION,
            "mode": "SHADOW_ONLY",
            "authority": "SHADOW_ONLY",
            "production_control": False,
            "scheduler_control": False,
            "termination_control": False,
            "scroll_control": False,
            "safety_control": False,
            "run": {"run_id": self.run_id, "scenario_id": self.scenario_id},
            "history": history_to_dict(self.history),
            "decisions": decisions + pending_records,
            "metrics": dict(sorted(self.metrics.items())),
            "evidence_complete": (not self.truncation_reasons and not self.failures
                                  and not pending_records and not self.history.truncated),
            "truncated": bool(self.truncation_reasons or self.history.truncated),
            "truncation_reasons": sorted(self.truncation_reasons),
            "shadow_failures": deepcopy(self.failures),
            "limits": {"max_decisions": MAX_DECISIONS,
                       "max_history_items": self.policy.max_history_items,
                       "max_artifact_bytes": MAX_ARTIFACT_BYTES},
        }

    def write(self, output_path: str | Path) -> Path:
        target = Path(output_path)
        target = target.with_name(target.stem + ".exploration_shadow.json")
        if not self.enabled:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        document = self.artifact()
        payload = canonical_json_bytes(document)
        while len(payload) > MAX_ARTIFACT_BYTES and document["decisions"]:
            document["decisions"].pop(0)
            document["truncated"] = True
            document["evidence_complete"] = False
            document["truncation_reasons"] = sorted(
                set(document["truncation_reasons"]) | {"MAX_ARTIFACT_BYTES"})
            for item in document["decisions"]:
                item["frontier"]["frontier_exhausted"] = "UNKNOWN"
                item["frontier"]["evidence_complete"] = False
                item["decision_evidence_usable"] = False
                if item.get("shadow_decision") == ExplorationDecision.COMPLETE_CURRENT_SCOPE.value:
                    item["completion_proof_usable"] = False
            payload = canonical_json_bytes(document)
        if len(payload) > MAX_ARTIFACT_BYTES:
            raise ValueError("exploration shadow artifact exceeds configured byte bound")
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(target)
        return target


__all__ = [
    "EXPLORATION_SHADOW_SCHEMA_VERSION", "ExplorationShadowRuntime",
    "compare_production_and_shadow", "normalize_production_decision",
]
