"""Opt-in safety composition around the unchanged Phase 4 focus/scroll planner.

Shadow/off return the original PlannerInput and never alter its history. Enforce
intersects eligible target IDs with the existing allowed domain and then calls
the same planner. Blocked observations are never attempts or visits.
"""
from dataclasses import dataclass, field, replace
from copy import deepcopy

from tb_runner.action_safety import classify_action, configured_metadata, default_config, normalize_action, matches
from tb_runner.safe_action_policy import evaluate_policy
from tb_runner.phase4a_planner import plan_shadow, production_instance
from tb_runner.phase4b_authority import AuthorityDecision
from tb_runner.canonical_json import canonical_json

MODES = ("off", "shadow", "enforce")


def safety_context(raw, value):
    snapshot = value.snapshot.to_dict()
    overlay = raw.get("overlay") or {}
    labels = [str(n.get("text") or n.get("contentDescription") or n.get("talkbackLabel") or "")
              for n in raw.get("nodes", []) if isinstance(n, dict)]
    modal_verified = overlay.get("classification") == "VERIFIED_MODAL"
    risks = [category for category, words in default_config()["lexicon"].items()
             if matches(" ".join(labels), words)] if modal_verified else []
    return dict(state_id=snapshot["state_id"], substate=snapshot.get("semantic_substates", []),
        destination=(raw.get("destination_ownership") or {}).get("destination") or raw.get("activity_name"),
        within_app=bool(raw.get("package_name") and raw.get("activity_name")
            and raw.get("context_source") == "window_current_focus"),
        # Ownership is diagnostic evidence, not a claim that navigation recovery
        # exists. Conditional activation needs a separate configured contract.
        recovery_verified=False, surrounding_labels=labels, confirmation_verified=modal_verified,
        modal_verified=modal_verified, confirmation_risks=risks)


def conditions_for(candidate, context, metadata, raw):
    evidence = candidate.get("evidence", {})
    cap, target = raw.get("capability") or {}, candidate.get("target_identity", {})
    container = cap.get("container") or {}
    from tb_runner.traversal_reliability import normalized_bounds
    scroll = normalize_action(candidate.get("action_kind"))
    capability = cap.get("can_scroll_forward") if scroll == "SCROLL_FORWARD" else cap.get("can_scroll_backward")
    configured = metadata.get("source") == "CONFIGURED"
    return dict(current_target=evidence.get("current_presence") is True or
        (evidence.get("axis_contract") == "axis-v1" and bool(evidence.get("supporting_signals"))),
        within_app=context.get("within_app") is True,
        recovery_verified=context.get("recovery_verified") is True,
        modal_verified=context.get("modal_verified") is True,
        cancellation_only=configured and metadata.get("effect") in {"cancel", "informational_dismiss"},
        read_only_effect=configured and metadata.get("effect") in {"read_only", "read_only_navigation", "read_only_expansion", "ui_filter"},
        scroll_container_verified=bool(cap.get("axis_contract") == "axis-v1" and cap.get("contradictory") is False
            and capability is True and container.get("path")
            and normalized_bounds(container.get("boundsInScreen")) == normalized_bounds(target.get("bounds"))))


@dataclass
class SafetySession:
    mode: str = "off"
    config: dict | None = None
    blocked_candidates: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError("Action safety mode must be off, shadow, or enforce")
        self.config = deepcopy(self.config if self.config is not None else default_config())

    def assess(self, value, raw):
        context = safety_context(raw, value)
        rows = []
        for candidate in value.snapshot.to_dict()["candidates"]:
            metadata = configured_metadata(candidate, context, self.config)
            classification = classify_action(candidate, context=context, metadata=metadata, config=self.config)
            conditions = conditions_for(candidate, context, metadata, raw)
            policy = evaluate_policy(classification, conditions)
            record = dict(candidate_id=candidate["candidate_id"], action_kind=candidate["action_kind"],
                instance_id=production_instance(candidate["target_identity"], value.history.scenario_id),
                classification=classification.to_dict(), policy=policy.to_dict(), conditions=conditions)
            rows.append(record)
            if not policy.eligible:
                self.blocked_candidates[classification.to_dict()["action_id"]] = record
        return rows

    def prepare(self, value, raw):
        if self.mode == "off":
            return value, None
        rows = self.assess(value, raw)
        allowed = {row["instance_id"] for row in rows if row["action_kind"] == "FOCUS_TARGET" and row["policy"]["eligible"]}
        if value.history.allowed_instance_ids is not None:
            allowed &= set(value.history.allowed_instance_ids)
        scroll_allowed = any(row["action_kind"] == "SCROLL_FORWARD_VERTICAL" and row["policy"]["eligible"] for row in rows)
        filtered = replace(value, history=replace(value.history, allowed_instance_ids=tuple(sorted(allowed))),
                           scroll_blocked=value.scroll_blocked or not scroll_allowed)
        report = dict(schema="phase5a-safety-step-v1", mode=self.mode, scenario=value.history.scenario_id,
            step=raw.get("step"), capture_id=raw.get("capture_id"), snapshot_hash=value.snapshot.candidate_set_hash,
            candidates=rows, safety_blocked_candidates=sorted(row["classification"]["action_id"] for row in rows if not row["policy"]["eligible"]),
            baseline_recommendation=plan_shadow(value).to_dict(), safety_recommendation=plan_shadow(filtered).to_dict(),
            selected=None, action_executed=False, attempt_credit=0, visit_credit=0)
        return (filtered if self.mode == "enforce" else value), report

    def guard(self, value, raw, recommendation, phase4_decision, report):
        if self.mode == "off":
            return phase4_decision
        chosen = recommendation.to_dict()
        kind = {"FOCUS_CANDIDATE":"FOCUS_TARGET", "SCROLL_FORWARD":"SCROLL_FORWARD_VERTICAL"}.get(chosen["recommended_action"])
        def key(target):
            return canonical_json({k:v for k,v in (target or {}).items() if k != "instance_id"})
        candidates = [row for row in value.snapshot.to_dict()["candidates"] if row["action_kind"] == kind
            and key(row["target_identity"]) == key(chosen["recommended_target"])]
        context = safety_context(raw, value)
        if len(candidates) == 1:
            candidate = candidates[0]
            metadata = configured_metadata(candidate, context, self.config)
            classification = classify_action(candidate, context=context, metadata=metadata, config=self.config)
            conditions = conditions_for(candidate, context, metadata, raw)
            policy = evaluate_policy(classification, conditions)
            selected = dict(candidate_id=candidate["candidate_id"], classification=classification.to_dict(),
                            policy=policy.to_dict(), conditions=conditions)
        else:
            selected = dict(candidate_id=None, classification=dict(safety_class="UNKNOWN", confidence="LOW",
                reason="SELECTED_TARGET_NOT_UNIQUE"), policy=dict(eligible=False, reason="SELECTED_TARGET_NOT_UNIQUE"))
        report.update(selected=selected, phase4_gate=phase4_decision.to_dict(),
                      would_execute=selected["policy"]["eligible"] and phase4_decision.allowed)
        if self.mode == "enforce" and phase4_decision.allowed and not selected["policy"]["eligible"]:
            return AuthorityDecision(False, "FALLBACK_PRODUCTION", "ACTION_SAFETY_" + selected["policy"]["reason"])
        return phase4_decision
