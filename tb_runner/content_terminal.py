"""Root-content closure from observed instances, never from a step cap.

Actual visits remain positional (Phase 0A). Conservative relocation aliases
remove duplicate obligations without promoting aliases to actual visits.
Readable candidates and semantic coverage remain explicit. No focus request,
representative consumption, or input focus is an actual accessibility visit.
"""
from dataclasses import dataclass, field
import hashlib
import json

from tb_runner.completeness import candidate, confirmed_focus, eligibility
from tb_runner.scroll_reliability import classify_container, flat_nodes
from tb_runner.traversal_reliability import instance_id, normalized_bounds, termination_status
from tb_runner.utils import parse_bounds_str
from tb_runner.candidate_lifecycle import CandidateLifecycle


def enabled(config):
    return (config.get("scenario_type", "content") == "content"
            and config.get("screen_context_mode") == "bottom_tab")


def failed_scroll_reason(transition):
    result = transition.get("action_result", {})
    if result.get("error") or result.get("after_dump_error"):
        return "content_error"
    if result.get("actionSupported") is False and result.get("actionAttempted") is False:
        return "content_scroll_unverified"
    return "content_error"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _contained(bounds, region):
    b, r = parse_bounds_str(bounds), parse_bounds_str(normalized_bounds(region))
    return bool(b and r and r[0] <= b[0] < b[2] <= r[2] and r[1] <= b[1] < b[3] <= r[3])


@dataclass
class ContentTerminal:
    scenario_id: str
    nav_regions: list = field(default_factory=list)
    scope_verified: bool = True
    records: dict = field(default_factory=dict)
    visited: set = field(default_factory=set)
    semantic: set = field(default_factory=set)
    history: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)
    signature: str = ""
    stable_observations: int = 0
    no_progress_steps: int = 0
    no_focus_progress_steps: int = 0
    last_progress_step: int = 0
    last_step: int = -1
    stable_scroll_attempts: int = 0
    stable_scroll_signature: str = ""
    latest: dict = field(default_factory=dict)
    scroll_attempted_viewports: set = field(default_factory=set)
    lifecycle: CandidateLifecycle = field(default_factory=CandidateLifecycle)

    def observe(self, observation, step, focus_observations=(), semantic_ids=(), scroll=None, pending=False,
                focus_sequence_progress=False):
        previous = set(self.records)
        visible, excluded = set(), {}
        structure, strict = [], []
        for node in flat_nodes(observation.get("nodes", [])):
            item = candidate(node, self.scenario_id)
            key = instance_id(item)
            state, reason = eligibility(item)
            if reason == "no_label_or_role" and (item["focusable"] is True or item["clickable"] is True):
                state, reason = "EXPECTED", "actionable_without_label"
            # Explicit subtree/chrome scope evidence, never a text-only heuristic.
            if node.get("isBottomNavigationBar") or any(_contained(item["bounds"], r) for r in self.nav_regions):
                state, reason = "OUT_OF_SCOPE", "global_navigation_scope"
            elif node.get("isTopAppBar") and "textview" not in item["class_name"].lower() and "viewgroup" not in item["class_name"].lower():
                state, reason = "OUT_OF_SCOPE", "helper_top_app_bar"
            kind = classify_container(item["class_name"])
            if kind in {"PAGER", "HORIZONTAL_TAB_SCROLL"}:
                # Exclude the navigation container action, not its visible children.
                state, reason = "OUT_OF_SCOPE", "OUT_OF_SCOPE_FOR_CONTENT_TERMINAL"
            if state == "OUT_OF_SCOPE":
                excluded[key] = dict(item, instance_id=key, exclusion_reason=reason,lifecycle="EXCLUDED")
                continue
            visible.add(key)
            self.records[key] = dict(item, instance_id=key, eligibility=state)
            self.labels.setdefault(key, set()).add(str(item["label"]))
            structural = (key, item["class_name"], item["role"], item["focusable"], item["clickable"])
            structure.append(structural)
            strict.append((*structural, item["label"]))
        previous_visits, previous_semantic = set(self.visited), set(self.semantic)
        for proof in focus_observations:
            actual = confirmed_focus(proof)
            if actual:
                self.visited.add(instance_id(actual))
        self.semantic.update(set(semantic_ids) & set(self.records))
        cap = observation.get("capability", {})
        container = cap.get("container") or {}
        cap_state = (cap.get("can_scroll_forward"), cap.get("contradictory", False),
                     container.get("instance_id"), container.get("kind"))
        signature = _digest([sorted(structure), cap_state, self.nav_regions])
        self.stable_observations = self.stable_observations + 1 if signature == self.signature else 1
        self.signature = signature
        new = set(self.records) - previous
        focus_progress = bool((self.visited - previous_visits) & set(self.records)
                              or self.semantic - previous_semantic)
        focus_sequence_progress = bool(focus_sequence_progress)
        moved = bool(scroll and scroll.get("status") == "SCROLL_MOVED")
        if step != self.last_step:
            self.no_progress_steps = 0 if focus_progress or new or moved or focus_sequence_progress else self.no_progress_steps + 1
            self.no_focus_progress_steps = 0 if focus_progress or moved or focus_sequence_progress else self.no_focus_progress_steps + 1
            self.last_step = step
        elif focus_progress or new or moved or focus_sequence_progress:
            self.no_progress_steps = 0
            self.no_focus_progress_steps = 0
        if focus_progress or new or moved or focus_sequence_progress:
            self.last_progress_step = step
        if scroll:
            attempted_signature = scroll.get("before", {}).get("stable_signature")
            if attempted_signature:
                self.scroll_attempted_viewports.add(attempted_signature)
            stable_scroll = bool(scroll.get("action_success") and not scroll.get("viewport_changed")
                                 and scroll.get("new_count") == 0 and scroll.get("before", {}).get("valid")
                                 and scroll.get("after", {}).get("valid"))
            if stable_scroll:
                self.stable_scroll_attempts = self.stable_scroll_attempts + 1 if signature == self.stable_scroll_signature else 1
                self.stable_scroll_signature = signature
            else:
                self.stable_scroll_attempts = 0
                self.stable_scroll_signature = ""
        elif signature != self.stable_scroll_signature:
            self.stable_scroll_attempts = 0
        coherent = cap.get("can_scroll_forward") is not None and not cap.get("contradictory", False)
        exhausted = bool(coherent and cap.get("can_scroll_forward") is False)
        semantic_readable = {key for key in self.semantic if self.records[key].get("focusable") is not True
                             and self.records[key].get("clickable") is not True}
        # A compound reading can cover a readable leaf, but cannot prove that a
        # separate actionable/focusable object received accessibility focus.
        observation_valid=bool(observation.get("nodes")) and observation.get("viewport", {}).get("valid", False)
        reconciliation=self.lifecycle.observe({k:self.records[k] for k in visible},cap,step,
                                             valid=observation_valid,scope_verified=self.scope_verified)
        historical_unseen=set(self.records)-self.visited-semantic_readable
        logical_covered=self.lifecycle.covered_targets(self.visited|semantic_readable)
        active=set(self.records)-set(self.lifecycle.aliases)
        unseen=active-logical_covered
        self.latest = dict(scenario_id=self.scenario_id, content_terminal_contract="phase0eb-observed-instance-v1",
            visible_candidates=len(visible), visited_candidates=len(set(self.records) & self.visited),
            logical_reconciliation_contract="phase0ga-unique-translation-alias-v1",
            semantically_covered_candidates=len((set(self.records) & self.semantic) - self.visited),
            unseen_candidates=len(unseen), remaining_unseen_count=len(unseen), excluded_candidates=len(excluded),
            visible_candidate_ids=sorted(visible), visited_candidate_ids=sorted(set(self.records) & self.visited),
            semantic_candidate_ids=sorted((set(self.records) & self.semantic) - self.visited),
            unseen_candidate_ids=sorted(unseen), excluded_candidate_records=list(excluded.values()),
            historical_unseen_count=len(historical_unseen),historical_unseen_candidate_ids=sorted(historical_unseen),
            active_candidates=len(active),active_unseen=len(unseen),stale_candidates=len(self.lifecycle.aliases),
            stale_unseen_candidates=len(historical_unseen & set(self.lifecycle.aliases)),
            stale_candidate_ids=sorted(self.lifecycle.aliases),logical_covered_candidate_ids=sorted(active & logical_covered),
            instance_reconciliation=reconciliation,movement_direction=self.lifecycle.last_movement,
            vertical_can_scroll_forward=cap.get("vertical_can_scroll_forward",cap.get("can_scroll_forward")),
            horizontal_can_scroll_forward=cap.get("horizontal_can_scroll_forward"),
            scroll_axis_source=cap.get("axis_source"),unknown_axis_containers=cap.get("unknown_axis_containers",0),
            scroll_viewport_signature=observation.get("viewport", {}).get("stable_signature", ""),
            scroll_attempted_viewports=sorted(self.scroll_attempted_viewports),
            strict_viewport_signature=_digest([sorted(strict), cap_state]), semantic_viewport_signature=signature,
            viewport_stable=self.stable_observations >= 2, stable_observations=self.stable_observations,
            scroll_exhausted=exhausted, can_scroll_forward=cap.get("can_scroll_forward"),
            scroll_capability_source=cap.get("source", "unknown"), scroll_capability_contradictory=cap.get("contradictory", False),
            stable_scroll_attempts=self.stable_scroll_attempts, new_instances=len(new), last_progress_step=self.last_progress_step,
            focus_sequence_progress=focus_sequence_progress,
            no_progress_steps=self.no_progress_steps, no_focus_progress_steps=self.no_focus_progress_steps,
            volatile_candidate_ids=sorted(k for k, values in self.labels.items() if len(values) >= 3),
            pending_transition=bool(pending), scope_verified=self.scope_verified,
            observation_valid=bool(observation.get("nodes")) and observation.get("viewport", {}).get("valid", False),
            step_index=step)
        if not self.latest["observation_valid"] and not self.records:
            for key in ("visible_candidates", "visited_candidates", "semantically_covered_candidates",
                        "unseen_candidates", "remaining_unseen_count", "new_instances", "active_candidates",
                        "active_unseen", "stale_candidates", "stale_unseen_candidates", "historical_unseen_count"):
                self.latest[key] = None
        self.history.append(dict(self.latest))
        return self.latest

    def scroll_opportunity(self):
        """Consume verified vertical continuation before a focus plateau stop.

        One attempt per observed positional viewport; movement opens a new
        viewport. A no-change action with forward still true is unverified,
        never evidence of exhaustion or an invitation to retry forever.
        """
        e = self.latest
        return bool(e.get("observation_valid") and self.scope_verified
                    and not e.get("pending_transition") and e.get("viewport_stable")
                    and e.get("vertical_can_scroll_forward") is True
                    and not e.get("scroll_capability_contradictory")
                    and not e.get("scroll_exhausted")
                    and e.get("scroll_viewport_signature")
                    and e["scroll_viewport_signature"] not in self.scroll_attempted_viewports
                    and (not e.get("unseen_candidates") or self.no_progress_steps >= 4
                         or self.no_focus_progress_steps >= 8))

    def decision(self):
        e = self.latest
        if not e.get("observation_valid"):
            return "content_error"
        if e.get("pending_transition"):
            return "content_no_progress" if self.no_focus_progress_steps >= 8 else ""
        if not self.scope_verified:
            return "content_scope_unverified" if self.no_focus_progress_steps >= 4 else ""
        if e["scroll_capability_contradictory"] or e["can_scroll_forward"] is None:
            return "content_scroll_unverified" if (e["viewport_stable"] and not e["unseen_candidates"]) or self.no_focus_progress_steps >= 4 else ""
        if self.scroll_opportunity():
            return ""
        if (e.get("vertical_can_scroll_forward") is True
                and e.get("scroll_viewport_signature") in self.scroll_attempted_viewports
                and e.get("viewport_stable")):
            return "content_scroll_unverified"
        if e["unseen_candidates"] == 0 and e["scroll_exhausted"] and e["viewport_stable"]:
            return "content_completed"
        if e["viewport_stable"] and self.no_progress_steps >= 4:
            return "content_no_progress"
        if self.no_focus_progress_steps >= 8:
            return "content_dynamic_unsettled"
        return ""

    def summary(self, reason, step):
        e = self.latest
        fields = ("content_terminal_contract", "logical_reconciliation_contract", "visible_candidates", "visited_candidates", "semantically_covered_candidates",
                  "active_candidates", "active_unseen", "stale_candidates", "stale_unseen_candidates", "historical_unseen_count",
                  "vertical_can_scroll_forward", "horizontal_can_scroll_forward", "scroll_axis_source", "unknown_axis_containers",
                  "unseen_candidates", "excluded_candidates", "remaining_unseen_count", "scroll_exhausted", "viewport_stable",
                  "can_scroll_forward", "scroll_capability_source", "scroll_capability_contradictory", "stable_observations",
                  "stable_scroll_attempts", "new_instances", "last_progress_step", "no_progress_steps",
                  "focus_sequence_progress",
                  "pending_transition", "scope_verified", "observation_valid", "strict_viewport_signature",
                  "semantic_viewport_signature")
        return {**{k: e.get(k) for k in fields}, "termination_status": termination_status(reason),
                "termination_reason": reason, "termination_step": step, "terminal_step": step,
                "volatile_candidates": len(e.get("volatile_candidate_ids", []))}

    def artifact(self, reason, step):
        return dict(schema_version="phase0eb-content-terminal-v1", scenario_id=self.scenario_id,
                    summary=self.summary(reason, step), records=self.lifecycle.lifecycle_records(self.records,self.visited,self.semantic),
                    instance_reconciliations=self.lifecycle.events,stale_aliases=dict(self.lifecycle.aliases),
                    final_evidence=self.latest, observations=self.history,
                    nav_regions=self.nav_regions, scope_snapshot_path=getattr(self, "scope_snapshot_path", ""))
