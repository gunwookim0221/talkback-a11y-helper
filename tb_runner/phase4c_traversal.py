"""Bounded opt-in traversal evidence. Production owns all actions and visits.

The four-step observation window follows production runtime_input's plateau
threshold. Two failed controlled results retain Phase 4B's degradation rule.
Saturation is diagnostic only; an ambiguous focus can never prove exhaustion.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections import deque
import json

from tb_runner.phase4a_planner import plan_shadow, production_instance
from tb_runner.phase4b_execution import focus_row
from tb_runner.traversal_reliability import focus_instance, instance_id

STAGES = (("home_main", "devices_main", "life_main"),
          ("life_find_plugin", "device_smoke_sensor_plugin", "device_tv_plugin", "device_washer_plugin"),
          ("life_energy_plugin", "life_food_plugin", "life_family_care_plugin"),
          ("device_camera_plugin",))
SCENARIOS = tuple(s for stage in STAGES for s in stage)
BUDGETS = {s: 20 if s in {"life_food_plugin", "device_camera_plugin"} else 10 for s in SCENARIOS}
WINDOW = 4


def inventory(value):
    return {production_instance(c["target_identity"], value.history.scenario_id)
            for c in value.snapshot.to_dict()["candidates"] if c["action_kind"] == "FOCUS_TARGET"}


def scope_key(raw, value):
    snap = value.snapshot.to_dict()
    container = (raw.get("capability") or {}).get("container") or {}
    return json.dumps([snap["state_id"], snap.get("semantic_substates"),
        raw.get("package_name"), raw.get("activity_name"), container.get("path"),
        container.get("boundsInScreen"), (raw.get("viewport") or {}).get("stable_signature")], sort_keys=True)


@dataclass
class TraversalSession:
    scenario: str
    max_steps: int
    seen_candidates: set = field(default_factory=set)
    seen_visits: set = field(default_factory=set)
    no_move_scrolls: dict = field(default_factory=dict)
    exhausted_scopes: set = field(default_factory=set)
    recent: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    last_focus: str | None = None
    last_state: object = None
    last_target: str | None = None
    last_inventory: set | None = None
    repeat_target: int = 0
    repeat_focus: int = 0
    resolution_failures: int = 0
    focus_failures: int = 0
    fallback_streak: int = 0
    last_new_candidate_step: int | None = None
    last_new_visit_step: int | None = None

    def __post_init__(self):
        if type(self.max_steps) is not int or not 1 <= self.max_steps <= 20:
            raise ValueError("Phase 4C validation budget must be 1..20")

    def prepare(self, raw, value):
        key = scope_key(raw, value)
        cap = raw.get("capability") or {}
        unavailable = cap.get("can_scroll_forward") is False and cap.get("contradictory") is False
        return replace(value, scroll_exhausted=value.scroll_exhausted or key in self.exhausted_scopes or unavailable)

    def observe(self, audit, raw, before, after_raw, after, budget):
        """Copy real outcomes; never write a production attempt or visit ledger."""
        step = audit["step"]
        chosen = audit["shadow_recommendation"]
        after_plan = plan_shadow(after).to_dict()
        candidates = inventory(before) | inventory(after)
        new_candidates = candidates - self.seen_candidates
        self.seen_candidates.update(candidates)
        visit_id = (audit.get("focus_reconciliation") or {}).get("actual_focus_instance_id")
        new_visit = bool(audit.get("visit_credit") and visit_id and visit_id not in self.seen_visits)
        if audit.get("visit_credit") and visit_id:
            self.seen_visits.add(visit_id)
        if new_candidates:
            self.last_new_candidate_step = step
        if new_visit:
            self.last_new_visit_step = step
        state = (after.snapshot.to_dict()["state_id"], after.snapshot.to_dict().get("semantic_substates", []))
        before_state = (before.snapshot.to_dict()["state_id"], before.snapshot.to_dict().get("semantic_substates", []))
        state_changed = before_state != state or self.last_state is not None and self.last_state != state
        node = audit.get("actual_focus_after") or {}
        actual = focus_instance(focus_row(node, self.scenario))
        focus_id = instance_id(actual) if actual else None
        target = chosen.get("recommended_instance_id")
        self.repeat_target = self.repeat_target + 1 if target and target == self.last_target else 1 if target else 0
        self.repeat_focus = self.repeat_focus + 1 if focus_id and focus_id == self.last_focus else 1 if focus_id else 0
        self.fallback_streak = self.fallback_streak + 1 if audit.get("fallback_used") else 0
        self.resolution_failures = self.resolution_failures + 1 if audit.get("fallback_reason") == "TARGET_DISAPPEARED_OR_AMBIGUOUS" else 0
        self.focus_failures = self.focus_failures + 1 if audit.get("planner_failed") and audit.get("planner_action") == "FOCUS_CANDIDATE" else 0
        scroll = audit.get("scroll_result")
        key = scope_key(raw, before)
        if scroll == "SCROLL_NO_MOVEMENT":
            self.no_move_scrolls[key] = self.no_move_scrolls.get(key, 0) + 1
            transition = audit.get("scroll_transition") or {}
            if transition.get("viewport_end") is True or self.no_move_scrolls[key] >= 2:
                self.exhausted_scopes.add(key)
        after = self.prepare(after_raw, after)
        cap = after_raw.get("capability") or {}
        scroll_state = ("SCROLL_MOVED" if scroll == "SCROLL_MOVED" else
            "SCROLL_EXHAUSTED" if scope_key(after_raw, after) in self.exhausted_scopes or after.scroll_exhausted else
            "SCROLL_AVAILABLE" if cap.get("can_scroll_forward") is True and not cap.get("contradictory") else
            "SCROLL_EXHAUSTED" if cap.get("can_scroll_forward") is False and not cap.get("contradictory") else "SCROLL_UNKNOWN")
        useful = any(r["priority_tier"] < 3 for r in after_plan["ranking"])
        ambiguous = not actual or audit.get("focus_transition_status") in {"AMBIGUOUS", "UNAVAILABLE"} or self.resolution_failures > 0
        progress = bool(new_candidates or new_visit or state_changed or scroll == "SCROLL_MOVED"
                        or audit.get("focus_transition_status") == "CONFIRMED_MOVED")
        self.recent.append(dict(progress=progress, new_candidate=bool(new_candidates), new_visit=new_visit,
            state_changed=bool(state_changed), scroll_moved=scroll == "SCROLL_MOVED", ambiguous=ambiguous))
        bounded_window = len(self.recent) == WINDOW
        no_progress = (bounded_window and not any(r["progress"] or r["ambiguous"] for r in self.recent)
                       and not useful and scroll_state == "SCROLL_EXHAUSTED"
                       and not after.pending_transition and not after.safety_blocked)
        saturation = (bounded_window and not any(r["new_candidate"] or r["new_visit"] or r["state_changed"]
                      or r["scroll_moved"] or r["ambiguous"] for r in self.recent)
                      and after_plan["never_attempted_count"] == 0 and not useful and scroll_state == "SCROLL_EXHAUSTED")
        loop = (not progress and (self.repeat_target >= 2 or self.repeat_focus >= WINDOW
                 or self.resolution_failures >= 2 or self.focus_failures >= 2 or self.fallback_streak >= WINDOW))
        starvation = (any(r["never_attempted"] and not r["visit_count"] and r["priority_tier"] < 3 for r in chosen["ranking"])
                      and audit.get("planner_executed")
                      and audit.get("planner_action") == "FOCUS_CANDIDATE"
                      and not any(r["instance_id"] == target and r["never_attempted"] and not r["visit_count"]
                                  for r in chosen["ranking"]))
        # Recovery is allowed only on new production progress, not on a repeated
        # failed recommendation. The scenario budget remains the absolute bound.
        if budget.degraded and (new_visit or state_changed or new_candidates):
            budget.degraded = False
            budget.failure_streak = 0
            budget.degraded_reason = "RECOVERED_AFTER_FRESH_PRODUCTION_PROGRESS"
        audit.update(substate=chosen["semantic_substates"], candidate_count=chosen["candidate_count"],
            eligible_count=chosen["eligible_candidate_count"], never_attempted_count=chosen["never_attempted_count"],
            attempted_unvisited_count=chosen["attempted_unvisited_count"], visited_count=chosen["visited_count"],
            execution_gate=audit["execution_gate_result"], focus_before=audit.get("actual_focus_before"),
            focus_after=node, focus_identity_type=("UNAVAILABLE" if not actual else "RESOURCE_ID" if actual["view_id"]
                else "SEMANTIC_LABEL" if actual["label"] else "ANONYMOUS_BOUNDS_CLASS"),
            scroll_capability=raw.get("capability"), scroll_action="SCROLL_FORWARD" if scroll else None,
            scroll_state=scroll_state, state_changed=bool(state_changed),
            new_candidate_discovered=len(new_candidates), new_candidate_ids=sorted(new_candidates),
            new_visit_created=new_visit, loop_signal="PLANNER_REPEAT_NO_PROGRESS" if loop else None,
            starvation_signal="STARVATION_PRIORITY_VIOLATION" if starvation else None,
            saturation_signal="PLANNER_CONTENT_SATURATED_SHADOW" if saturation else None,
            no_progress_proven=no_progress, useful_candidate_remains=useful, identity_ambiguity=ambiguous,
            termination_decision="INCOMPLETE_NO_PROGRESS" if no_progress else "CONTINUE",
            loop_evidence=dict(repeated_target=self.repeat_target, repeated_focus=self.repeat_focus,
                unchanged_inventory=self.last_inventory == inventory(after), unchanged_state=self.last_state == state,
                target_resolution_failures=self.resolution_failures, focus_failures=self.focus_failures,
                fallback_streak=self.fallback_streak, no_movement_scrolls=self.no_move_scrolls.get(key, 0),
                canonical_binding=audit.get("target_binding")),
            after_refresh=dict(raw=after_raw, snapshot=after.snapshot.to_dict(), recommendation=plan_shadow(after).to_dict()))
        self.last_focus, self.last_target, self.last_state, self.last_inventory = focus_id, target, state, inventory(after)
        return audit

    def protect_stop(self, stop, reason, value):
        """Preserve production errors/completion; guard premature repeat stops."""
        if not stop or reason not in {"content_no_progress", "repeat_no_progress", "bounded_two_card_loop", "repeat_semantic_stall", "repeat_semantic_stall_after_escape"}:
            return stop, reason
        plan = plan_shadow(value).to_dict()
        safe_no_progress = (len(self.recent) == WINDOW and not any(r["progress"] or r["ambiguous"] for r in self.recent)
            and not any(r["priority_tier"] < 3 for r in plan["ranking"])
            and value.scroll_exhausted and not value.pending_transition and not value.safety_blocked)
        return (True, "repeat_no_progress") if safe_no_progress else (False, "")
