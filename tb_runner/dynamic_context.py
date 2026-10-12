"""Phase 4C destination leases and bounded current-state authority rebinding.

Observational adapter only: no device commands, navigation, visits or policies.
Normal entry owns a destination; mutable discovery states never own a lease.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import re

from tb_runner.plugin_context_contract import body_resources
from tb_runner.phase3_context import resolve_phase3_context
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.phase4a_planner import plan_shadow
from tb_runner.phase4b_authority import execution_gate, AuthorityDecision
from tb_runner.phase4b_execution import geometry_in_viewport

FRESH = {"FRESH_VERIFIED", "FRESH_PARTIAL"}


def stable_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def time_value(raw):
    try:
        value = datetime.fromisoformat(raw["timestamp"].replace("Z", "+00:00"))
        return value.timestamp() if value.tzinfo else None
    except (ValueError, KeyError, TypeError):
        return None


def destination_ownership_rejection_diagnostic(raw, context=None, error=None):
    """Build bounded pre-raise evidence without granting or changing authority."""
    context = context if isinstance(context, dict) else resolve_phase3_context(raw)
    scenario = str(raw.get("scenario_id") or "")
    config = next((c for c in TAB_CONFIGS if c.get("scenario_id") == scenario), {})
    tab_name = str(config.get("tab_name") or "").casefold()
    expected = next((name for name in ("home", "devices", "life", "routines", "menu") if name in tab_name), None)
    reasons = list(context.get("reasons") or [])
    evidence = context.get("destination_evidence") or {}
    labels = []
    for node in raw.get("nodes", []):
        if not isinstance(node, dict) or node.get("visibleToUser", node.get("isVisibleToUser", True)) is False:
            continue
        label = next((str(node.get(k) or "").strip() for k in
                      ("text", "contentDescription", "talkbackLabel", "mergedLabel", "label")
                      if str(node.get(k) or "").strip()), "")
        if label:
            labels.append(dict(label=label, resource_id=node.get("viewIdResourceName") or node.get("resourceId"),
                               class_name=node.get("className") or node.get("class"),
                               bounds=node.get("boundsInScreen"), role=node.get("role"),
                               stable_node_path=node.get("stable_node_path")))
    window = raw.get("window_evidence") if isinstance(raw.get("window_evidence"), dict) else {}
    return dict(
        schema_version="destination-ownership-rejection-v1",
        scenario=scenario, expected_destination=expected,
        context_status=context.get("status"), context_reason=reasons,
        failed_predicate=(reasons[0] if reasons else "DESTINATION_OWNERSHIP_STATUS_OR_IDENTITY"),
        observed_destination_signals=list(context.get("observed_signals") or []),
        other_destination_signals=dict(lexical_hints=evidence.get("lexical_hints", []),
                                       structural_evidence=evidence.get("structural_evidence", []),
                                       strict_profile_matches=evidence.get("strict_profile_matches", [])),
        navigation_epoch=raw.get("navigation_epoch"), destination_ownership=False,
        destination_identity=(raw.get("phase3_plugin_context_evidence") or {}).get("destination_identity"),
        activity=dict(package_name=raw.get("package_name"), activity_name=raw.get("activity_name"),
                      context_source=raw.get("context_source")),
        window={key: window.get(key) for key in
                ("window_count", "focused_window_type", "focused_window_component", "focused_activity_matches", "windows")},
        selected_tab=deepcopy(raw.get("selected_tab")), body_markers=dict(resource_ids=body_resources(raw), labels=labels),
        error=str(error) if error is not None else "Trusted normal plugin entry required")


class DestinationOwnership:
    """Scenario-local normal-entry ownership with explicit navigation suspension."""
    def __init__(self, entry_raw, *, event_sink=None):
        context = resolve_phase3_context(entry_raw)
        proof = entry_raw.get("phase3_plugin_context_evidence") or {}
        if context["status"] not in {"VERIFIED_PLUGIN_CONTEXT", "PARTIAL_CONTEXT"} or not proof.get("destination_identity"):
            raise ValueError("Trusted normal plugin entry required")
        self.proof = deepcopy(proof)
        self.scenario = entry_raw["scenario_id"]
        self.run = entry_raw["scenario_run_id"]
        self.epoch = proof["navigation_epoch"]
        self.destination = proof["destination_identity"]
        self.ownership_id = stable_digest([self.scenario, self.run, self.destination, self.epoch,
                                          proof["package_name"], proof["activity_name"], proof["proof_capture_id"]])
        self.pending = False
        self.invalid = False
        self.active = False
        self.recovery_epoch = 0
        self.recovery_state = "IDLE"
        self.freshness = "FRESH_VERIFIED" if context["verified"] else "FRESH_PARTIAL"
        self.good_captures = []
        self.last_time = time_value(entry_raw)
        self.events = []
        self.event_sink = event_sink
        self.event("DESTINATION_ESTABLISHED")

    def event(self, kind, **fields):
        record = dict(sequence=len(self.events)+1, kind=kind,
                                scenario_id=self.scenario, scenario_run_id=self.run, destination_id=self.destination,
                                ownership_id=self.ownership_id, navigation_epoch=self.epoch,
                                recovery_epoch=self.recovery_epoch, **fields)
        record["event_id"] = stable_digest(record)
        self.events.append(record)
        if self.event_sink is not None:
            self.event_sink(deepcopy(record))

    def navigation(self, event, epoch):
        self.epoch = epoch
        self.pending = True
        self.good_captures.clear()
        self.freshness = "STALE_REVALIDATABLE"
        # Home/launch/force-stop are actual destination boundaries. Back/click
        # suspend ownership until fresh body observations prove an internal return.
        if event.get("kind") in {"HOME", "ACTIVITY_START", "FORCE_STOP", "SCENARIO_EXIT"}:
            self.invalid = True
            self.freshness = "STALE_INVALID"
        self.event("CONTEXT_INVALIDATED", navigation_kind=event.get("kind"), recoverable=not self.invalid)

    def _strong_body(self, raw, context):
        shared = set(body_resources(raw)) & set(self.proof.get("body_resource_ids") or [])
        component = raw.get("activity_name") or ""
        namespaced = any(":id/" in rid and not rid.startswith("com.samsung.android.oneconnect:")
                         and component.startswith(rid.split(":id/", 1)[0]+".") for rid in shared)
        # A configured destination title is stronger than a shared word (History).
        from tb_runner.scenario_config import TAB_CONFIGS
        config = next(c for c in TAB_CONFIGS if c["scenario_id"] == self.scenario)
        labels = [str(n.get("text") or n.get("contentDescription") or n.get("talkbackLabel") or "")
                  for n in raw.get("nodes", []) if n.get("visibleToUser") is not False]
        title = False
        for step in config.get("pre_navigation", []):
            for token in [step.get("target", ""), *step.get("target_stable_labels", [])]:
                try:
                    pattern = token if token.startswith("(?") else r"(?<!\w)"+re.escape(token)+r"(?!\w)"
                    title |= bool(token and any(re.search(pattern, label, re.I) for label in labels))
                except re.error:
                    continue
        return bool(shared and (namespaced or title and context["status"] == "VERIFIED_PLUGIN_CONTEXT"))

    def assess(self, raw, *, recovery_active=False):
        """Attach a derived proof only after checking its immutable normal-entry owner."""
        previous = self.freshness
        now = time_value(raw)
        owned = (raw.get("scenario_id") == self.scenario and raw.get("scenario_run_id") == self.run
                 and raw.get("navigation_epoch") == self.epoch
                 and (raw.get("phase3_entry_evidence") or {}).get("entry_contract_digest") == self.destination)
        if not owned or not now or self.last_time is not None and now < self.last_time:
            self.invalid = True
        if self.invalid:
            self.freshness = "STALE_INVALID"
            context = dict(status="UNRESOLVED_CONTEXT", verified=False, reasons=["DESTINATION_OWNER_INVALID"],
                           context_source="owned_destination_revalidation")
        else:
            candidate = deepcopy(raw)
            proof = deepcopy(self.proof)
            proof.update(navigation_epoch=self.epoch)
            candidate["phase3_plugin_context_evidence"] = proof
            context = resolve_phase3_context(candidate)
            if context["status"] in {"CONTRADICTORY_CONTEXT", "WRONG_CONTEXT"}:
                self.invalid = True
                self.freshness = "CONTRADICTORY"
                self.recovery_state = "RECOVERY_FAILED" if self.active else self.recovery_state
                self.event("DESTINATION_CONTRADICTED", reasons=context.get("reasons"))
            else:
                overlay = (raw.get("overlay") or {}).get("observed")
                unsafe = recovery_active or overlay is not False
                if unsafe and not self.active:
                    self.active = True
                    self.recovery_epoch += 1
                    self.recovery_state = "RECOVERY_STARTED"
                    self.event("RECOVERY_STARTED")
                if unsafe:
                    self.recovery_state = "RECOVERY_ACTIVE"
                    self.freshness = "STALE_REVALIDATABLE"
                    self.good_captures.clear()
                else:
                    if self.active:
                        self.active = False
                        self.recovery_state = "RECOVERY_COMPLETED"
                        self.pending = True
                        self.good_captures.clear()
                        self.event("RECOVERY_COMPLETED")
                    body = bool(set(body_resources(raw)) & set(self.proof.get("body_resource_ids") or []))
                    if context["status"] not in {"VERIFIED_PLUGIN_CONTEXT", "PARTIAL_CONTEXT"} or not body:
                        self.pending = True
                        self.freshness = "STALE_REVALIDATABLE"
                        self.good_captures.clear()
                    elif self.pending:
                        self.recovery_state = "RECOVERY_REVALIDATING" if self.recovery_epoch else self.recovery_state
                        capture = raw.get("capture_id")
                        if self._strong_body(raw, context) and capture and capture not in self.good_captures:
                            self.good_captures.append(capture)
                        else:
                            self.good_captures.clear()
                        self.freshness = "STALE_REVALIDATABLE"
                        if len(self.good_captures) >= 2:
                            self.pending = False
                            self.freshness = "FRESH_VERIFIED" if context["verified"] else "FRESH_PARTIAL"
                            self.recovery_state = "RECOVERY_REBOUND" if self.recovery_epoch else self.recovery_state
                            self.event("CONTEXT_REVALIDATED", capture_ids=self.good_captures[-2:])
                            if self.recovery_epoch:
                                self.event("RECOVERY_REBOUND")
                    else:
                        self.freshness = "FRESH_VERIFIED" if context["verified"] else "FRESH_PARTIAL"
                if self.freshness in FRESH:
                    proof.update(revalidated_by="current_owned_destination_observation",
                                 destination_ownership_id=self.ownership_id,
                                 original_entry_capture_id=self.proof["proof_capture_id"])
                    raw["phase3_plugin_context_evidence"] = proof
                else:
                    context = dict(status="UNRESOLVED_CONTEXT", verified=False, reasons=[self.freshness],
                                   context_source="owned_destination_revalidation")
        if now is not None:
            self.last_time = now
        view = dict(ownership_id=self.ownership_id, destination_id=self.destination,
                    scenario_id=self.scenario, scenario_run_id=self.run, navigation_epoch=self.epoch,
                    established_by="trusted_normal_entry+post_open", entry_capture_id=self.proof["proof_capture_id"],
                    freshness=self.freshness, previous_freshness=previous, recovery_epoch=self.recovery_epoch,
                    recovery_state=self.recovery_state, contradiction=self.invalid,
                    revalidated=self.freshness in FRESH and previous not in FRESH,
                    capture_id=raw.get("capture_id"), timestamp=raw.get("timestamp"),
                    activity_name=raw.get("activity_name"), package_name=raw.get("package_name"),
                    context_status=context["status"], event_sequence=len(self.events))
        raw["destination_ownership"] = view
        return context


def rebind_execution(original, recommendation, current, evidence, before_raw, current_raw, **budget):
    """Replan a fresh state only with two owned observations of the current target.

    The unchanged Phase 4B gate still validates every target/geometry/focus/
    ranking/history/budget predicate. Scroll never uses this focus re-entry path.
    """
    decision = execution_gate(original, recommendation, current, evidence, **budget)
    transition = dict(initial_reason=decision.reason, rebound=False, final_reason=decision.reason,
                      authority_transition="AUTHORIZED" if decision.allowed else "BLOCKED",
                      initial_recommendation=recommendation.to_dict())
    a, b = before_raw.get("destination_ownership") or {}, current_raw.get("destination_ownership") or {}
    if (not b.get('ownership_id') or a.get('ownership_id') != b.get('ownership_id')
            or a.get('destination_id') != b.get('destination_id')
            or a.get('scenario_id') != b.get('scenario_id')
            or b.get('scenario_id') != current.history.scenario_id
            or a.get('scenario_run_id') != b.get('scenario_run_id')
            or a.get('navigation_epoch') != b.get('navigation_epoch')
            or any(view.get('package_name') != raw.get('package_name')
                   or view.get('activity_name') != raw.get('activity_name')
                   for raw,view in [(before_raw,a),(current_raw,b)])):
        decision = AuthorityDecision(False, 'FALLBACK_PRODUCTION', 'DESTINATION_OWNERSHIP_UNPROVEN')
        transition.update(final_reason=decision.reason, authority_transition='BLOCKED')
        return recommendation, decision, transition
    if decision.allowed and (b.get('freshness') not in FRESH or b.get('contradiction')):
        decision = AuthorityDecision(False, 'FALLBACK_PRODUCTION', 'DESTINATION_OWNERSHIP_UNPROVEN')
        transition.update(final_reason=decision.reason, authority_transition='BLOCKED')
        return recommendation, decision, transition
    if (decision.reason not in {"STATE_OR_SUBSTATE_CHANGED", "UNRESOLVED_STRUCTURAL_SCOPE_NOT_PROVEN", "STALE_CANDIDATE_OR_RANKING"}
            or a.get("ownership_id") != b.get("ownership_id") or not b.get("ownership_id")
            or a.get("navigation_epoch") != b.get("navigation_epoch")
            or a.get("capture_id") == b.get("capture_id")
            or a.get("freshness") not in FRESH or b.get("freshness") not in FRESH
            or a.get("contradiction") or b.get("contradiction")
            or recommendation.to_dict() != plan_shadow(original).to_dict()):
        return recommendation, decision, transition
    chosen = plan_shadow(current)
    selected = chosen.to_dict()
    if selected["recommended_action"] != "FOCUS_CANDIDATE":
        return recommendation, decision, transition
    def key(target):
        return {k:v for k,v in (target or {}).items() if k != "instance_id"}
    target = key(selected["recommended_target"])
    old_candidates = [c for c in original.snapshot.to_dict()["candidates"]
                      if c["action_kind"] == "FOCUS_TARGET" and key(c["target_identity"]) == target
                      and c["evidence"].get("current_presence") is True
                      and c["target_semantics"].get("flags", {}).get("focusable") is True
                      and c["target_semantics"].get("flags", {}).get("enabled") is True
                      and c["safety_hint"] == "READ_ONLY"]
    if len(old_candidates) != 1:
        return recommendation, decision, transition
    updated = replace(evidence, geometry_in_viewport=geometry_in_viewport(current_raw, chosen))
    rebound = execution_gate(current, chosen, current, updated, **budget)
    transition.update(rebound=True, final_reason=rebound.reason, current_recommendation=selected,
                      old_state_id=original.snapshot.to_dict()["state_id"],
                      current_state_id=current.snapshot.to_dict()["state_id"],
                      stable_target=target, independently_observed_target_count=2,
                      old_capture_id=a["capture_id"], current_capture_id=b["capture_id"],
                      authority_transition="BLOCKED→REVALIDATED→AUTHORIZED" if rebound.allowed else "BLOCKED→REVALIDATED→BLOCKED")
    return chosen, rebound, transition


def ownership_failures(audit):
    data = audit.get("dynamic_context")
    if not data:
        return []
    reasons = []
    before, current = data.get("before") or {}, data.get("current") or {}
    if (before.get("scenario_id") != audit.get("scenario") or current.get("scenario_id") != audit.get("scenario")
            or before.get("scenario_run_id") != current.get("scenario_run_id")):
        reasons.append("CROSS_SCENARIO_CONTEXT_LEAK")
    if (before.get("ownership_id") != current.get("ownership_id") or not current.get("ownership_id")
            or before.get("destination_id") != current.get("destination_id")):
        reasons.append("CROSS_DESTINATION_CONTEXT_LEAK")
    if audit.get("planner_executed") and (current.get("freshness") not in FRESH or current.get("contradiction")):
        reasons.append("STALE_CONTEXT_EXECUTION")
    return sorted(set(reasons))
