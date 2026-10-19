"""Phase 6C2 bounded, observation-only adapter for the 6C1 frontier core.

The adapter accepts only candidate inventories and evidence already produced
by the ordinary production pipeline.  PRE_DECISION inputs are detached before
the action is dispatched; POST_RESULT can update history only through the
matching in-memory decision token and exact owner evidence.  Nothing here is
used to dispatch, stop traversal, scroll, or grant visits.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from tb_runner.canonical_json import canonical_json, canonical_json_bytes, canonical_sha256
from tb_runner.frontier_scheduler import FRONTIER_SCHEMA_VERSION, build_frontier_id, evaluate_frontier
from tb_runner.state_graph import GraphMode, graph_mode_from_environment, state_graph_artifact_path


FRONTIER_SHADOW_SCHEMA_VERSION = "phase6-frontier-shadow.v1"
MAX_EVALUATIONS = 2_048
MAX_FRONTIER_ITEMS = 512
MAX_RUN_HISTORY_RECORDS = 16_384
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
_OWNERS = {"PRIMARY", "FALLBACK", "RECOVERY", "TARGETED", "SEQUENTIAL",
           "OPTIONAL_EXPANSION", "OTHER", "UNKNOWN"}
_PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def shadow_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Share the Phase 6B gate; there is no independent frontier mode."""
    return graph_mode_from_environment(environ) == GraphMode.SHADOW


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _stable_candidates(value: Sequence[Mapping[str, Any]], state_id: str) -> list[dict[str, Any]]:
    """Normalize existing production candidates without discovering new ones."""
    rows: list[dict[str, Any]] = []
    for candidate in value:
        target = _mapping(candidate.get("target_identity"))
        instance = _text(target.get("instance_id") or candidate.get("production_instance_id"))
        candidate_id = _text(candidate.get("candidate_id"))
        if not candidate_id or not instance:
            continue
        row = deepcopy(dict(candidate))
        row["candidate_id"] = candidate_id
        row["state_id"] = state_id or None
        row["target_identity"] = {"instance_id": instance}
        row["edge_type"] = "TARGETED_FOCUS"
        row["currently_present"] = True
        row["target_binding_status"] = "RESOLVED" if state_id else "UNKNOWN"
        rows.append(row)
    rows.sort(key=lambda item: (item["candidate_id"], canonical_json(item)))
    return rows


def _compact_evaluation(result: Mapping[str, Any]) -> dict[str, Any]:
    counts = _mapping(result.get("counts"))
    return {
        "state_id": result.get("state_id"),
        "shadow_choice": result.get("shadow_next_candidate_id"),
        "shadow_frontier": result.get("shadow_next_frontier"),
        "shadow_action_type": result.get("shadow_next_action_type"),
        "priority_class": next((item.get("priority_class") for item in result.get("frontier_items", [])
                                 if item.get("candidate_id") == result.get("shadow_next_candidate_id")), None),
        "reason_codes": list(result.get("shadow_next_reason_codes") or []),
        "eligible_count": int(counts.get("eligible_count", 0) or 0),
        "never_attempted_count": int(counts.get("never_attempted_count", 0) or 0),
        "unvisited_count": int(counts.get("unvisited_count", 0) or 0),
        "unknown_count": int(counts.get("unknown_count", 0) or 0),
        "retryable_count": int(counts.get("retryable_count", 0) or 0),
        "revisit_only_count": int(counts.get("revisit_only_count", 0) or 0),
        "frontier_exhausted": result.get("frontier_exhausted", "UNKNOWN"),
        "exhaustion_scope": result.get("exhaustion_scope"),
        "evidence_complete": result.get("evidence_complete") is True,
        "truncated": result.get("truncated") is True,
        "inventory_complete": result.get("inventory_complete") is True,
        "history_complete": result.get("history_complete") is True,
        "frontier_items": deepcopy(result.get("frontier_items") or []),
    }


@dataclass
class FrontierShadowRuntime:
    run_id: str
    scenario_id: str
    enabled: bool = True
    source_graph_path: str = ""
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    history: dict[str, Any] = field(default_factory=lambda: {
        "complete": True, "attempt_events": [], "visit_events": [],
        "exploration_events": [], "validated_aliases": {}, "visits_by_instance": {},
    })
    metrics: dict[str, int] = field(default_factory=lambda: {
        "REVISIT_SELECTION_COUNT": 0,
        "COMPARABLE_REVISIT_SELECTION_COUNT": 0,
        "OBSERVED_REVISIT_MOVE_COUNT": 0,
        "NEVER_ATTEMPTED_AVAILABLE_WHEN_REVISIT_SELECTED": 0,
        "FRONTIER_MISS_COUNT": 0,
        "NO_EFFECT_REPEAT_COUNT": 0,
        "NOT_COMPARABLE_COUNT": 0,
        "UNKNOWN_COMPARISON_COUNT": 0,
        "SHADOW_RECOMMENDATION_COUNT": 0,
    })
    failures: list[dict[str, Any]] = field(default_factory=list)
    truncation_reasons: set[str] = field(default_factory=set)
    _pending: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    _seen_results: set[str] = field(default_factory=set, repr=False)
    _last_post_step: int = field(default=-1, repr=False)
    _history_record_count: int = field(default=0, repr=False)

    @classmethod
    def for_run(cls, *, run_id: str, scenario_id: str, output_path: str | Path,
                environ: Mapping[str, str] | None = None) -> "FrontierShadowRuntime | None":
        if not shadow_enabled(environ):
            return None
        return cls(run_id=run_id, scenario_id=scenario_id,
                   source_graph_path=state_graph_artifact_path(output_path).name)

    def _fail(self, phase: str, exc: BaseException, *, step: int | None = None) -> None:
        self.history["complete"] = False
        self.failures.append({"phase": phase, "step": step,
                              "error_type": type(exc).__name__})

    def capture_inventory(self, *, step: int, state_id: str | None,
                          candidates: Sequence[Mapping[str, Any]],
                          inventory_complete: bool,
                          observation_ref: Mapping[str, Any] | None = None) -> None:
        """Cache an inventory already assembled by production reconciliation."""
        if not self.enabled:
            return
        try:
            normalized = _stable_candidates(candidates, state_id or "")
            truncated = len(normalized) > MAX_FRONTIER_ITEMS
            if truncated:
                normalized = normalized[:MAX_FRONTIER_ITEMS]
                self.truncation_reasons.add("MAX_FRONTIER_ITEMS")
                self.history["complete"] = False
            self._latest_inventory = {
                "source_step": int(step), "state_id": state_id,
                "candidates": normalized,
                "inventory_complete": bool(inventory_complete and not truncated and state_id),
                "observation_ref": deepcopy(dict(observation_ref or {})),
            }
        except Exception as exc:  # shadow-only isolation
            self._fail("inventory_capture", exc, step=step)
            self._latest_inventory = {"source_step": int(step), "state_id": None,
                                      "candidates": [], "inventory_complete": False,
                                      "observation_ref": {}}

    def pre_decision(self, *, step: int, production_choice: Mapping[str, Any],
                     focus_cursor: Mapping[str, Any] | None = None,
                     planner_evidence: Mapping[str, Mapping[str, Any]] | None = None,
                     safety_evidence: Mapping[str, Mapping[str, Any]] | None = None,
                     current_inventory: Sequence[Mapping[str, Any]] | None = None,
                     state_id: str | None = None, inventory_complete: bool | None = None,
                     observation_ref: Mapping[str, Any] | None = None) -> str | None:
        if not self.enabled:
            return None
        try:
            if len(self.evaluations) >= MAX_EVALUATIONS:
                self.truncation_reasons.add("MAX_EVALUATIONS")
                self.history["complete"] = False
                return None
            cached = getattr(self, "_latest_inventory", None)
            if current_inventory is None and isinstance(cached, Mapping) and cached.get("source_step") == step - 1:
                current_inventory = cached.get("candidates") or []
                state_id = state_id or cached.get("state_id")
                inventory_complete = bool(cached.get("inventory_complete"))
                observation_ref = observation_ref or cached.get("observation_ref")
            else:
                current_inventory = current_inventory or []
            state_resolved = bool(state_id)
            state = {"state_id": state_id or "", "resolved": state_resolved,
                     "identity_status": "RESOLVED" if state_resolved else "UNRESOLVED",
                     "inventory_complete": bool(inventory_complete)}
            candidates = _stable_candidates(current_inventory, state_id or "")
            if len(candidates) > MAX_FRONTIER_ITEMS:
                candidates = candidates[:MAX_FRONTIER_ITEMS]
                self.truncation_reasons.add("MAX_FRONTIER_ITEMS")
                state["inventory_complete"] = False
            # No planner/safety evidence means UNKNOWN. Never manufacture either.
            planners = deepcopy(dict(planner_evidence or {}))
            safeties = deepcopy(dict(safety_evidence or {}))
            result = evaluate_frontier(state, candidates, deepcopy(self.history), planners, safeties,
                                       focus_cursor=deepcopy(dict(focus_cursor or {}))) .to_dict()
            decision_id = f"frontier-decision:{len(self.evaluations) + 1}:{int(step)}"
            choice = deepcopy(dict(production_choice or {}))
            evaluation = _compact_evaluation(result)
            comparison, reason = compare_choices(choice, evaluation)
            record = {
                "phase": "PRE_DECISION_POST_RESULT_BOUND",
                "decision_id": decision_id,
                "step": int(step),
                "state_id": result.get("state_id"),
                "observation_ref": deepcopy(dict(observation_ref or {})),
                "production_choice": choice,
                "shadow_choice": evaluation["shadow_choice"],
                "comparison": comparison,
                "comparison_reason": reason,
                **evaluation,
                "attempt_owner": "UNKNOWN",
                "action_result": None,
            }
            self.evaluations.append(record)
            self._pending[decision_id] = {
                "step": int(step), "state_id": result.get("state_id"),
                "evaluation": result, "record": record,
                "pre_state": deepcopy(state), "pre_cursor": deepcopy(dict(focus_cursor or {})),
                "production_choice": choice,
            }
            if evaluation["shadow_choice"]:
                self.metrics["SHADOW_RECOMMENDATION_COUNT"] += 1
            if comparison == "NOT_COMPARABLE":
                self.metrics["NOT_COMPARABLE_COUNT"] += 1
            elif comparison == "UNKNOWN":
                self.metrics["UNKNOWN_COMPARISON_COUNT"] += 1
            prod_id = _text(choice.get("candidate_id"))
            prod_item = next((item for item in result.get("frontier_items", [])
                              if item.get("candidate_id") == prod_id), None)
            revisit_selected = bool(prod_item and prod_item.get("visit_status") in {"RECORDED", "ALREADY_VISITED"})
            if revisit_selected and evaluation["evidence_complete"]:
                self.metrics["REVISIT_SELECTION_COUNT"] += 1
                if comparison in {"SAME", "DIFFERENT"}:
                    self.metrics["COMPARABLE_REVISIT_SELECTION_COUNT"] += 1
                if evaluation["never_attempted_count"]:
                    self.metrics["NEVER_ATTEMPTED_AVAILABLE_WHEN_REVISIT_SELECTED"] += 1
            if comparison == "DIFFERENT" and evaluation["evidence_complete"]:
                prod_id = _text(choice.get("candidate_id"))
                prod_item = next((item for item in result.get("frontier_items", [])
                                  if item.get("candidate_id") == prod_id), None)
                recommended = next((item for item in result.get("frontier_items", [])
                                    if item.get("candidate_id") == evaluation["shadow_choice"]), None)
                if (prod_item and recommended and recommended.get("priority_class") in _PRIORITY
                        and (prod_item.get("priority_class") not in _PRIORITY
                             or _PRIORITY[prod_item["priority_class"]] > _PRIORITY[recommended["priority_class"]])):
                    self.metrics["FRONTIER_MISS_COUNT"] += 1
            return decision_id
        except Exception as exc:  # shadow-only isolation
            self._fail("pre_decision", exc, step=step)
            return None

    def post_result(self, *, decision_id: str | None, step: int,
                    result: Mapping[str, Any], owner: str,
                    ownership_status: str = "UNKNOWN", result_id: str = "",
                    action_type: str = "", target_instance_id: str = "",
                    before_observation_valid: bool = False,
                    after_observation_valid: bool = False,
                    outcome_observation_complete: bool = False,
                    state_changed: bool | None = None) -> bool:
        if not self.enabled or not decision_id:
            return False
        try:
            pending = self._pending.get(decision_id)
            if (pending is None or pending["step"] != int(step) or int(step) < self._last_post_step
                    or not isinstance(result, Mapping)):
                self.history["complete"] = False
                self.truncation_reasons.add("STALE_OR_UNBOUND_RESULT")
                return False
            result_id = _text(result_id) or decision_id
            if result_id in self._seen_results:
                return False
            self._seen_results.add(result_id)
            self._last_post_step = max(self._last_post_step, int(step))
            owner_value = str(owner or "UNKNOWN").strip().upper()
            if owner_value not in _OWNERS:
                owner_value = "UNKNOWN"
            exact = ownership_status == "EXACT_MATCH" and owner_value != "UNKNOWN"
            action = _text(action_type).upper()
            target = _text(target_instance_id)
            row = deepcopy(dict(result))
            pending["record"]["attempt_owner"] = owner_value if exact else "UNKNOWN"
            pending["record"]["action_result"] = {
                "ownership_status": "EXACT_MATCH" if exact else "UNKNOWN",
                "owner": owner_value if exact else "UNKNOWN",
                "action_type": action or "UNKNOWN",
                "result_id": result_id,
                "request_id": _text(row.get("phase5c_primary_action_request_id") or row.get("smart_nav_req_id")
                                     or row.get("target_focus_attempt_id")) or None,
                "focus_transition_status": _text(row.get("focus_transition_status")).upper() or "UNKNOWN",
                "actual_focus_instance_id": _text(row.get("actual_focus_instance_id")) or None,
                "visit_record_status": _text(row.get("visit_record_status")).upper() or "UNKNOWN",
            }
            if (_text(row.get("focus_transition_status")).upper() == "CONFIRMED_MOVED"
                    and _text(row.get("visit_record_status")).upper() == "ALREADY_VISITED"
                    and _text(row.get("actual_focus_instance_id"))):
                self.metrics["OBSERVED_REVISIT_MOVE_COUNT"] += 1
            if not exact:
                self.history["complete"] = False
            else:
                attempt = self._attempt_event(pending, row, owner_value, action, target,
                    before_observation_valid, after_observation_valid,
                    outcome_observation_complete, state_changed)
                if attempt is not None:
                    if self._append_history("attempt_events", attempt):
                        if (attempt.get("effect_observed") is False
                                and any(event.get("frontier_id") == attempt.get("frontier_id")
                                        and event.get("ownership_status") == "EXACT_MATCH"
                                        and event.get("effect_observed") is False
                                        for event in self.history["attempt_events"][:-1])):
                            self.metrics["NO_EFFECT_REPEAT_COUNT"] += 1
            self._record_production_visit(pending, row)
            self._pending.pop(decision_id, None)
            return True
        except Exception as exc:  # shadow-only isolation
            self._fail("post_result", exc, step=step)
            self._pending.pop(decision_id, None)
            return False

    def _attempt_event(self, pending: Mapping[str, Any], row: Mapping[str, Any], owner: str,
                       action_type: str, target_instance_id: str,
                       before_valid: bool, after_valid: bool, outcome_complete: bool,
                       state_changed: bool | None) -> dict[str, Any] | None:
        if owner not in {"PRIMARY", "TARGETED", "RECOVERY", "FALLBACK"} or not target_instance_id:
            return None
        if action_type not in {"TARGETED_FOCUS", "FOCUS_TARGET", "FOCUS"}:
            return None
        state_id = _text(pending.get("state_id"))
        if not state_id:
            self.history["complete"] = False
            return None
        edge = "TARGETED_FOCUS"
        frontier_id = build_frontier_id(state_id, edge, target_instance_id)
        item = next((item for item in pending["evaluation"].get("frontier_items", [])
                     if item.get("frontier_id") == frontier_id), None)
        if item is None:
            self.history["complete"] = False
            return None
        moved = _text(row.get("focus_transition_status")).upper() == "CONFIRMED_MOVED"
        complete = bool(before_valid and after_valid and outcome_complete)
        same_state = bool(state_changed is False)
        no_effect = complete and same_state and not moved and _text(row.get("focus_transition_status")).upper() == "CONFIRMED_UNCHANGED"
        return {
            "state_id": state_id, "frontier_id": frontier_id,
            "action_type": edge, "target_instance_id": target_instance_id,
            "attempted": True, "ownership_status": "EXACT_MATCH",
            "step": int(pending["step"]),
            "before_observation_valid": bool(before_valid),
            "after_observation_valid": bool(after_valid),
            "outcome_observation_complete": complete,
            "effect_observed": False if no_effect else True if moved or state_changed is True else None,
            "actual_focus_moved": moved if complete else None,
            "state_changed": state_changed if complete else None,
            "ack_status": _text(row.get("command_ack_status") or row.get("last_smart_nav_result")).upper() or "UNKNOWN",
            "condition_fingerprint": _text(item.get("condition_fingerprint")) or "same",
            "request_id": _text(row.get("phase5c_primary_action_request_id") or row.get("smart_nav_req_id")
                                 or row.get("target_focus_attempt_id")) or None,
        }

    def _record_production_visit(self, pending: Mapping[str, Any], row: Mapping[str, Any]) -> None:
        status = _text(row.get("visit_record_status")).upper()
        transition = _text(row.get("focus_transition_status")).upper()
        target = _text(row.get("reconciled_visit_instance_id"))
        if status not in {"RECORDED", "ALREADY_VISITED"} or transition != "CONFIRMED_MOVED" or not target:
            if transition == "CONFIRMED_MOVED" and not target:
                self.history["complete"] = False
            return
        state_id = _text(pending.get("state_id"))
        if not state_id:
            self.history["complete"] = False
            return
        if not any(item.get("target_identity", {}).get("instance_id") == target
                   for item in pending["evaluation"].get("frontier_items", [])):
            # A landing outside the decision-time inventory cannot be attached
            # to an opportunity in that state.
            self.history["complete"] = False
            return
        self._append_history("visit_events", {
            "state_id": state_id, "target_instance_id": target,
            "production_authority": True, "accessibility_focus_confirmed": True,
            "focus_transition_status": transition, "visit_record_status": status,
            "ownership_status": "EXACT_MATCH", "step": int(pending["step"]),
        })

    def _append_history(self, field_name: str, event: Mapping[str, Any]) -> bool:
        if self._history_record_count >= MAX_RUN_HISTORY_RECORDS:
            self.truncation_reasons.add("MAX_RUN_HISTORY_RECORDS")
            self.history["complete"] = False
            return False
        key = canonical_json(dict(event))
        existing = self.history[field_name]
        if any(canonical_json(item) == key for item in existing):
            return False
        existing.append(deepcopy(dict(event)))
        existing.sort(key=lambda item: (item.get("step", -1), canonical_json(item)))
        self._history_record_count += 1
        return True

    def bind_followup(self, *, decision_id: str | None, step: int,
                      result: Mapping[str, Any], owner: str,
                      ownership_status: str = "UNKNOWN", result_id: str = "") -> bool:
        """Record a later fallback/recovery action without changing PRE data."""
        record = next((item for item in self.evaluations if item.get("decision_id") == decision_id), None)
        if not self.enabled or record is None or record.get("step") != int(step):
            self.history["complete"] = False
            return False
        owner = str(owner or "UNKNOWN").strip().upper()
        exact = ownership_status == "EXACT_MATCH" and owner in _OWNERS - {"UNKNOWN"}
        result_id = _text(result_id) or f"{decision_id}:followup:{owner}"
        if result_id in self._seen_results:
            return False
        self._seen_results.add(result_id)
        record.setdefault("followup_actions", []).append({
            "owner": owner if exact else "UNKNOWN",
            "ownership_status": "EXACT_MATCH" if exact else "UNKNOWN",
            "result_id": result_id,
            "action_type": _text(result.get("action_type") or result.get("planner_action")).upper() or "UNKNOWN",
            "result": _text(result.get("status") or result.get("move_result")).upper() or "UNKNOWN",
        })
        if not exact:
            self.history["complete"] = False
        return True

    def artifact(self) -> dict[str, Any]:
        truncated = bool(self.truncation_reasons or self._pending)
        evaluations = deepcopy(self.evaluations)
        if truncated:
            for item in evaluations:
                item["evidence_complete"] = False
                item["frontier_exhausted"] = "UNKNOWN"
                item["truncated"] = True
        return {
            "schema_version": FRONTIER_SHADOW_SCHEMA_VERSION,
            "frontier_evaluation_schema_version": FRONTIER_SCHEMA_VERSION,
            "mode": "SHADOW_ONLY", "authority": "SHADOW_ONLY",
            "production_control": False, "termination_control": False,
            "scroll_control": False, "safety_control": False,
            "run": {"run_id": self.run_id, "scenario_id": self.scenario_id},
            "source_graph_artifact": self.source_graph_path or None,
            "evaluations": evaluations,
            "metrics": dict(sorted(self.metrics.items())),
            "evidence_complete": self.history.get("complete") is True and not truncated and not self.failures,
            "truncated": truncated,
            "truncation_reasons": sorted(self.truncation_reasons),
            "shadow_failures": deepcopy(self.failures),
            "limits": {"max_evaluations": MAX_EVALUATIONS,
                       "max_frontier_items_per_evaluation": MAX_FRONTIER_ITEMS,
                       "max_run_history_records": MAX_RUN_HISTORY_RECORDS,
                       "max_artifact_bytes": MAX_ARTIFACT_BYTES},
        }

    def write(self, output_path: str | Path) -> Path:
        target = Path(output_path)
        target = target.with_name(target.stem + ".frontier_shadow.json")
        if not self.enabled:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        document = self.artifact()
        payload = canonical_json_bytes(document)
        while len(payload) > MAX_ARTIFACT_BYTES and document["evaluations"]:
            document["evaluations"].pop(0)
            document["truncated"] = True
            document["evidence_complete"] = False
            document["truncation_reasons"] = sorted(set(document["truncation_reasons"]) | {"MAX_ARTIFACT_BYTES"})
            for item in document["evaluations"]:
                item["evidence_complete"] = False
                item["frontier_exhausted"] = "UNKNOWN"
                item["truncated"] = True
            payload = canonical_json_bytes(document)
        if len(payload) > MAX_ARTIFACT_BYTES:
            raise ValueError("frontier shadow artifact exceeds configured byte bound")
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(target)
        return target


def compare_choices(production: Mapping[str, Any], evaluation: Mapping[str, Any]) -> tuple[str, str]:
    action = _text(production.get("action_type")).upper()
    if action in {"FOCUS_NEXT_UNTARGETED", "FOCUS_NEXT", "SEQUENTIAL"}:
        return "NOT_COMPARABLE", "UNTARGETED_SMART_NEXT"
    if action in {"TAB_CHANGE_TARGETED", "OPTIONAL_EXPANSION", "OTHER"}:
        return "NOT_COMPARABLE", "ACTION_OUTSIDE_CANDIDATE_FOCUS_SCOPE"
    production_id = _text(production.get("candidate_id"))
    shadow_id = _text(evaluation.get("shadow_choice"))
    if not production_id or not shadow_id or not evaluation.get("evidence_complete"):
        return "UNKNOWN", "IDENTITY_OR_EVIDENCE_INCOMPLETE"
    return ("SAME", "EXACT_TARGET_MATCH") if production_id == shadow_id else ("DIFFERENT", "EXACT_TARGET_MISMATCH")


def production_candidate(*, state_id: str, scenario_id: str, candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    """Adapt one candidate already supplied by production reconciliation."""
    from tb_runner.focus_reconciliation import _candidate_item
    from tb_runner.traversal_reliability import instance_id, normalized_bounds

    item = _candidate_item(dict(candidate), scenario_id)
    if not normalized_bounds(item.get("bounds")):
        return None
    instance = instance_id(item)
    if not instance:
        return None
    candidate_id = "frontier_candidate_" + canonical_sha256({
        "state_id": state_id, "edge_type": "TARGETED_FOCUS", "instance_id": instance,
    })
    return {
        "candidate_id": candidate_id,
        "edge_type": "TARGETED_FOCUS",
        "state_id": state_id,
        "target_identity": {"instance_id": instance},
        "currently_present": True,
        "target_binding_status": "RESOLVED" if state_id else "UNKNOWN",
    }


def capture_reconciled_inventory(runtime: FrontierShadowRuntime | None, *,
                                 row: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]],
                                 scenario_id: str, raw_nodes: Sequence[Any] | None = None,
                                 projection_complete: bool = True) -> None:
    """Reuse the exact candidate groups already computed for reconciliation."""
    if runtime is None or not runtime.enabled:
        return
    from tb_runner.state_graph import _raw_observation_from_row, build_graph_state_identity

    raw = _raw_observation_from_row(row)
    if raw_nodes is not None:
        raw["nodes"] = deepcopy(list(raw_nodes))
    identity = build_graph_state_identity(raw)
    state_id = identity.state_id
    normalized: list[dict[str, Any]] = []
    for candidate in candidates:
        node = candidate.get("node") if isinstance(candidate, Mapping) else None
        node = node if isinstance(node, Mapping) else candidate
        if not isinstance(node, Mapping) or node.get("focusable") is not True:
            continue
        item = production_candidate(state_id=state_id or "", scenario_id=scenario_id,
                                   candidate=candidate)
        if item is not None:
            normalized.append(item)
    try:
        step = int(row.get("step_index", 0) or 0)
    except (TypeError, ValueError):
        step = 0
    coverage = str(raw.get("observation_coverage", "") or "").upper()
    complete = bool(state_id and raw.get("nodes") and projection_complete
                    and coverage in {"OBSERVED_FULL", "COMPLETE"})
    runtime.capture_inventory(
        step=step, state_id=state_id, candidates=normalized,
        inventory_complete=complete,
        observation_ref={"source_step": step, "state_id": state_id,
                         "state_resolution": identity.status},
    )


__all__ = [
    "FRONTIER_SHADOW_SCHEMA_VERSION", "MAX_ARTIFACT_BYTES", "MAX_EVALUATIONS",
    "MAX_FRONTIER_ITEMS", "MAX_RUN_HISTORY_RECORDS", "FrontierShadowRuntime",
    "capture_reconciled_inventory", "compare_choices", "production_candidate", "shadow_enabled",
]
