"""Explicit bounded safe execution. Existing classifiers and ledgers unchanged.

A navigation lease adds a reviewed UI effect and bounded return contract to the
Phase 4 gated focus target. BACK is a NAVIGATE/return action whose transport is
Android BACK, not a reclassification of Phase 5A's unproven generic BACK.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import re
import uuid

from tb_runner.action_safety import classify_action
from tb_runner.action_safety import default_config, normalize_text
from tb_runner.safe_action_policy import evaluate_policy
from tb_runner.phase4a_planner import plan_shadow, production_instance
from tb_runner.phase4b_authority import AuthorityEvidence, ExecutionBudget, execution_gate
from tb_runner.phase4b_execution import coherent_focus, geometry_in_viewport, controlled_collect
from tb_runner.traversal_reliability import normalized_bounds
from tb_runner.canonical_json import canonical_sha256
from talkback_lib.constants import ACTION_CLICK_FOCUSED, ACTION_FOCUS_IN_BOUNDS, ACTION_TARGET_FOCUS_COMMIT
from talkback_lib.window_lifecycle import get_talkback_restart_event

STAGES = (("home_main", "devices_main", "life_main"), ("life_food_plugin", "life_family_care_plugin"),
          ("device_smoke_sensor_plugin", "device_door_lock_plugin", "device_tv_plugin", "device_washer_plugin", "device_camera_plugin"))
SCENARIOS = tuple(s for stage in STAGES for s in stage)
BUDGETS = {s: 20 if s in {"life_food_plugin", "device_camera_plugin"} else 10 for s in SCENARIOS}


class SafetyBlocked(RuntimeError):
    pass


def default_contracts():
    return json.loads((Path(__file__).resolve().parents[1]/"config/safe_navigation_contracts.json").read_text(encoding="utf-8"))


def ownership(raw):
    """Separate navigation lease; production destination ownership is untouched."""
    package, activity = raw.get("package_name"), raw.get("activity_name")
    if package and activity and activity.startswith("."):
        activity = package + activity
    return dict(scenario=raw.get("scenario_id"), run=raw.get("scenario_run_id"),
        package=package, activity=activity,
        tab=(raw.get("selected_tab") or {}).get("name"),
        entry=(raw.get("phase3_entry_evidence") or {}).get("entry_contract_digest"))


def structure(raw):
    # Focus changes and mutable values do not create another destination.
    return sorted(set((str(n.get("viewIdResourceName") or n.get("resourceId") or ""),
        str(n.get("className") or ""), normalized_bounds(n.get("boundsInScreen") or n.get("bounds") or ""))
        for n in raw.get("nodes", []) if n.get("visibleToUser") is not False))


def same_parent(parent, returned):
    return (ownership(parent) == ownership(returned) and structure(parent) == structure(returned)
        and (returned.get("overlay") or {}).get("observed") is False)


def return_scope_conflict(parent, returned, context_status):
    """Detect positive evidence that a return observation left its owned scope.

    Missing tab or hierarchy evidence is inconclusive; it cannot confirm a
    return, but a later bounded read-only capture may provide a complete pair.
    Positive app/run/entry, tab, modal, or Phase 3 context contradictions stop
    confirmation immediately.
    """
    expected, observed = ownership(parent), ownership(returned)
    for key in ("scenario", "run", "package", "activity", "entry"):
        if expected.get(key) and observed.get(key) and expected[key] != observed[key]:
            return True
    if expected.get("tab") and observed.get("tab") and expected["tab"] != observed["tab"]:
        return True
    if (returned.get("overlay") or {}).get("observed") is True:
        return True
    return context_status in {"WRONG_CONTEXT", "CONTRADICTORY_CONTEXT", "VERIFIED_PLUGIN_CONTEXT"}


def activation_observations(report):
    return [r for r in (report or {}).get("candidates", []) if r["classification"]["action_type"] != "FOCUS"]


def focus_target_identity(target):
    """Stable exact identity carried by TARGET_FOCUS_COMMIT's native extras."""
    target = target or {}
    return dict(resource_id=str(target.get("resource_id") or target.get("resourceId")
                               or target.get("rid") or target.get("viewIdResourceName") or "").strip(),
        class_name=str(target.get("class_name") or target.get("className") or target.get("class") or "").strip(),
        bounds=normalized_bounds(target.get("bounds") or target.get("boundsInScreen") or ""))


def _identity_matches(left, right):
    return focus_target_identity(left) == focus_target_identity(right)


def _extras(command):
    values = {}
    i = 0
    while i + 2 < len(command):
        if command[i] in {"--es", "--ez", "--ei"}:
            value = str(command[i + 2])
            # _escape_adb_string uses a paired double-quote token to preserve
            # an empty extra through adb shell argument parsing. At the runner
            # boundary that token denotes the empty string, not a resource ID
            # whose literal characters are two quotes.
            if value == '""':
                value = ""
            elif len(value) >= 2 and value[0] == value[-1] == "'":
                value = value[1:-1].replace("'\\''", "'")
            values[str(command[i + 1])] = value
            i += 3
        else:
            i += 1
    return values


def _raw_focus_candidate(node, identity):
    """Build classifier input for an observed node omitted from planner candidates."""
    label = " ".join(str(node.get(key) or "") for key in ("text", "contentDescription", "talkbackLabel", "mergedLabel"))
    return dict(action_kind="FOCUS_TARGET", state_id=None,
        target_identity={**identity},
        target_semantics=dict(role=node.get("role") or "", normalized_label=normalize_text(label),
            text=str(node.get("text") or ""), contentDescription=str(node.get("contentDescription") or ""),
            talkbackLabel=str(node.get("talkbackLabel") or ""), flags=dict(
                clickable=node.get("clickable") is True, focusable=node.get("focusable") is True,
                enabled=node.get("enabled") is not False, checkable=node.get("checkable") is True,
                editable=node.get("editable") is True), actions=deepcopy(node.get("actions") or [])),
        evidence=dict(current_presence=node.get("visibleToUser") is not False),
        eligibility=dict(availability="AVAILABLE" if node.get("enabled") is not False else "DISABLED"))


def current_return_target(raw, value):
    """Bind BACK's lease identity to the actual child focus, never click it.

    Accessibility focus does not imply focusable=True. Existing discovery may
    represent a focused actionable menu row as CLICK rather than FOCUS_TARGET.
    Keep both flags and candidate/production identities exactly as observed.
    """
    if not coherent_focus(raw): return {}
    focus = raw.get("focus_node") or {}
    matching = [c for c in value.snapshot.to_dict()["candidates"]
        if c["action_kind"] in {"FOCUS_TARGET", "CLICK"}
        and c["target_identity"].get("resource_id") == str(focus.get("viewIdResourceName") or focus.get("resourceId") or "")
        and c["target_identity"].get("bounds") == normalized_bounds(focus.get("boundsInScreen"))
        and c["target_identity"].get("class_name") == focus.get("className")]
    for kind in ("FOCUS_TARGET", "CLICK"):
        candidates = [c for c in matching if c["action_kind"] == kind]
        if len(candidates) == 1: return candidates[0]
        if candidates: return {}
    return {}


class SafeNavigationSession:
    def __init__(self, scenario, sink, contracts=None, safety_config=None):
        self.scenario, self.sink = scenario, sink
        self.contracts = deepcopy(contracts if contracts is not None else default_contracts())
        self.safety_config = deepcopy(safety_config if safety_config is not None else default_config())
        self.permit = None
        self.raw = None
        self.authorization_epoch = 0
        self.authorization_invalidations = 0
        self.authorization_rechecks = 0
        self.authorization_failures = 0
        self.authorization_rebinds = 0
        self.used_focus_request_ids = set()
        self.dispatch_authorizations = []
        self.last_safety_report = None
        self.completed = False
        self.blocked = {}
        self.command_blocks = []
        self._active_client = None
        self.blocked_repeats = 0

    def _guard_hard_stop(self, operation):
        client = self._active_client
        hard_stop = getattr(client, "_phase5c_hard_stop_state", None) if client is not None else None
        if hard_stop is not None:
            hard_stop.guard(operation)

    @staticmethod
    def plugin_lease_required(context):
        return context.get('context_type') != 'root_tab' and context.get('status') != 'VERIFIED_ROOT_CONTEXT'

    def observe(self, raw, report):
        self.invalidate_authorization("NEW_OBSERVATION")
        self.raw = deepcopy(raw)
        self.last_safety_report = deepcopy(report or {})
        for row in (report or {}).get("candidates", []):
            if not row["policy"]["eligible"]:
                classification = row["classification"]
                key = (production_instance(classification.get("target_identity") or {}, self.scenario),
                    classification["action_type"], canonical_sha256([ownership(raw), structure(raw),
                        (report.get("baseline_recommendation") or {}).get("semantic_substates")]))
                self.blocked_repeats += key in self.blocked
                self.blocked[key] = deepcopy(row)
        self.sink("phase5b_blocked_actions.jsonl", dict(scenario=self.scenario, step=raw.get("step"),
            ownership=ownership(raw), targets=[dict(target=r["classification"].get("target_identity"),
                action_type=r["classification"]["action_type"], safety_class=r["classification"]["safety_class"],
                block_reason=r["policy"]["reason"], executed=False) for r in (report or {}).get("candidates", []) if not r["policy"]["eligible"]]))

    def _authorization_event(self, event, **fields):
        row = dict(schema="phase5b-dispatch-authorization-v1", event=event,
            scenario=self.scenario, step=(self.raw or {}).get("step"),
            authorization_epoch=self.authorization_epoch, **deepcopy(fields))
        self.dispatch_authorizations.append(row)
        self.sink("phase5b_dispatch_authorizations.jsonl", row)
        return row

    def invalidate_authorization(self, reason):
        self.authorization_epoch += 1
        if self.permit and self.permit.get("kind") == "FOCUS":
            prior = self.permit
            self.permit = None
            self.authorization_invalidations += 1
            self._authorization_event("INVALIDATED", target_identity=prior.get("target_identity"),
                action_type=prior.get("action_type"), safety_class=prior.get("safety_class"),
                authorization_target_id=prior.get("authorization_target_id"), authorization_valid=False,
                invalidation_reason=reason, dispatch_kind=prior.get("dispatch_kind"), executed=False)
        else:
            self.authorization_invalidations += 1
            self._authorization_event("BOUNDARY_INVALIDATION", authorization_valid=False,
                invalidation_reason=reason, dispatch_kind="NONE", executed=False)

    @contextmanager
    def authorize_focus_target(self, *, raw, value, target, phase4_gate, step,
                               dispatch_kind="PRIMARY"):
        """Issue one native-focus permit for the exact Phase 4/5A gated target."""
        self._guard_hard_stop("planner_target_authorization")
        from tb_runner.phase5a_safety import safety_context, conditions_for
        from tb_runner.action_safety import configured_metadata
        from tb_runner.safe_action_policy import evaluate_policy

        self.authorization_rechecks += 1
        gate = phase4_gate.to_dict() if hasattr(phase4_gate, "to_dict") else dict(phase4_gate or {})
        state = value.snapshot.to_dict()
        candidates = [c for c in state.get("candidates", []) if c.get("action_kind") == "FOCUS_TARGET"
            and _identity_matches(c.get("target_identity"), target)]
        if not gate.get("allowed") or len(candidates) != 1:
            self.authorization_failures += 1
            self._authorization_event("BLOCKED_BEFORE_DISPATCH", dispatch_kind=dispatch_kind,
                target_identity=focus_target_identity(target), action_type="FOCUS", safety_class="UNKNOWN",
                policy_decision="BLOCK_PHASE4_GATE_OR_NON_UNIQUE_TARGET", execution_gate=gate,
                authorization_valid=False, executed=False)
            raise SafetyBlocked("Focus dispatch lacks exact Phase 4 target authorization")

        candidate = deepcopy(candidates[0])
        context = safety_context(raw, value)
        metadata = configured_metadata(candidate, context, self.safety_config)
        classification = classify_action(candidate, action_type="FOCUS", context=context,
            metadata=metadata, config=self.safety_config).to_dict()
        conditions = conditions_for(candidate, context, metadata, raw)
        policy = evaluate_policy(classification, conditions).to_dict()
        if not policy.get("eligible"):
            self.authorization_failures += 1
            self._authorization_event("BLOCKED_BEFORE_DISPATCH", dispatch_kind=dispatch_kind,
                target_identity=focus_target_identity(target), action_type="FOCUS",
                safety_class=classification.get("safety_class"), policy_decision=policy.get("reason"),
                classification=classification, policy=policy, execution_gate=gate,
                authorization_valid=False, executed=False)
            raise SafetyBlocked("Focus dispatch blocked by Phase 5A policy")

        exact = focus_target_identity(target)
        if not exact["bounds"] or not exact["class_name"] or exact != focus_target_identity(candidate["target_identity"]):
            self.authorization_failures += 1
            self._authorization_event("BLOCKED_BEFORE_DISPATCH", dispatch_kind=dispatch_kind,
                target_identity=exact, action_type="FOCUS", safety_class="UNKNOWN",
                policy_decision="BLOCK_TARGET_IDENTITY_MISMATCH", execution_gate=gate,
                authorization_valid=False, executed=False)
            raise SafetyBlocked("Focus dispatch target identity changed")

        if self.permit is not None:
            raise SafetyBlocked("Nested execution permit")
        self.invalidate_authorization("FOCUS_AUTHORIZATION_REBIND")
        self.raw = deepcopy(raw)
        self.authorization_epoch += 1
        self.authorization_rebinds += 1
        epoch = canonical_sha256(dict(step=step, scenario=self.scenario, ownership=ownership(raw),
            structure=structure(raw), snapshot_hash=raw.get("snapshot_hash"), state_id=state.get("state_id")))
        permit = dict(kind="FOCUS", request=None, consumed=False, target_identity=exact,
            action_type="FOCUS", safety_class=classification["safety_class"],
            policy_decision=policy["reason"], classification=classification, policy=policy,
            conditions=conditions, candidate=candidate, context=context, execution_gate=gate,
            destination_ownership=ownership(raw), state_id=state.get("state_id"),
            observation_epoch=epoch, authorization_epoch=self.authorization_epoch,
            authorization_target_id=classification.get("action_id"), step=step,
            dispatch_kind=dispatch_kind)
        self.permit = permit
        self._authorization_event("PERMIT_ISSUED", dispatch_kind=dispatch_kind,
            target_identity=exact, action_type="FOCUS", safety_class=classification["safety_class"],
            policy_decision=policy["reason"], authorization_target_id=classification.get("action_id"),
            authorization_valid=True, destination_ownership=ownership(raw), state_id=state.get("state_id"),
            observation_epoch=epoch, execution_gate=gate, candidate_id=candidate.get("candidate_id"),
            policy=policy, executed=False)
        try:
            yield permit
        finally:
            if self.permit is permit:
                if not permit["consumed"]:
                    self._authorization_event("PERMIT_EXPIRED", dispatch_kind=dispatch_kind,
                        target_identity=exact, action_type="FOCUS", safety_class=classification["safety_class"],
                        policy_decision=policy["reason"], authorization_target_id=classification.get("action_id"),
                        authorization_valid=False, invalidation_reason="DISPATCH_SCOPE_EXIT", executed=False)
                self.permit = None

    @contextmanager
    def authorize(self, kind, request=None, authorization=None):
        self._guard_hard_stop(f"authorize:{kind}")
        if self.permit is not None:
            raise SafetyBlocked("Nested execution permit")
        self.permit = dict(kind=kind, request=request, consumed=False,
            authorization=deepcopy(authorization) if authorization is not None else None)
        try:
            yield
        finally:
            self.permit = None

    def _classify_unpermitted_focus_target(self, identity):
        from tb_runner.action_safety import configured_metadata
        from tb_runner.safe_action_policy import evaluate_policy
        from tb_runner.scroll_reliability import flat_nodes

        raw = self.raw or {}
        nodes = flat_nodes(raw.get("nodes", []))
        matches = [n for n in nodes if _identity_matches({
            "resource_id": n.get("viewIdResourceName") or n.get("resourceId"),
            "class_name": n.get("className"),
            "bounds": n.get("boundsInScreen") or n.get("bounds")}, identity)]
        node = matches[0] if len(matches) == 1 else {}
        candidate = _raw_focus_candidate(node, identity)
        report = self.last_safety_report or {}
        baseline = report.get("baseline_recommendation") or {}
        context = dict(state_id=baseline.get("planner_state_id"),
            substate=baseline.get("semantic_substates", []),
            destination=(raw.get("destination_ownership") or {}).get("destination") or raw.get("activity_name"),
            within_app=bool(raw.get("package_name") and raw.get("activity_name")
                and raw.get("context_source") == "window_current_focus"),
            recovery_verified=False, surrounding_labels=[], confirmation_verified=False,
            modal_verified=False, confirmation_risks=[])
        metadata = configured_metadata(candidate, context, self.safety_config)
        classification = classify_action(candidate, action_type="FOCUS", context=context,
            metadata=metadata, config=self.safety_config).to_dict()
        policy = evaluate_policy(classification, dict(current_target=bool(node), within_app=context["within_app"])).to_dict()
        return classification, policy

    def preflight_activation_dispatch(self, *, target, request_id, dev=None):
        """Fail closed for secondary activation without an exact Phase 4 lease.

        Production overlay handling can request CLICK_TARGET outside the
        controlled planner step. Classify the observed target for audit, but
        do not infer a Phase 4 execution gate or inherit a focus permit.
        """
        self._guard_hard_stop("preflight:activation")
        from tb_runner.action_safety import configured_metadata
        from tb_runner.safe_action_policy import evaluate_policy
        from tb_runner.scroll_reliability import flat_nodes

        raw = self.raw or {}
        requested = target if isinstance(target, dict) else {}
        self.invalidate_authorization("SECONDARY_ACTIVATION_BOUNDARY")
        token = str(requested.get("target_type") or "a").strip().lower()
        selector = str(requested.get("target_id") or requested.get("target_text")
            or requested.get("name") or "")
        if requested.get("target_id"):
            token, selector = "r", str(requested["target_id"])
        elif requested.get("target_text"):
            token, selector = "t", str(requested["target_text"])

        def matches(pattern, value):
            if not pattern:
                return False
            try:
                return re.search(pattern, str(value or ""), flags=re.IGNORECASE) is not None
            except re.error:
                return normalize_text(pattern) == normalize_text(value)

        matched = []
        for node in flat_nodes(raw.get("nodes", [])):
            if node.get("visibleToUser") is False:
                continue
            values = {
                "r": [node.get("viewIdResourceName") or node.get("resourceId")],
                "t": [node.get("text")],
                "b": [node.get("talkbackLabel") or node.get("talkback")],
                "a": [node.get("text"), node.get("contentDescription"), node.get("talkbackLabel"), node.get("mergedLabel")],
            }.get(token, [])
            if any(matches(selector, value) for value in values):
                if requested.get("class_name") and str(node.get("className") or "") != str(requested["class_name"]):
                    continue
                matched.append(node)

        node = matched[0] if len(matched) == 1 else {}
        identity = focus_target_identity(dict(
            resource_id=node.get("viewIdResourceName") or node.get("resourceId") or requested.get("target_id"),
            class_name=node.get("className") or requested.get("class_name"),
            bounds=node.get("boundsInScreen") or node.get("bounds")))
        label = " ".join(str(node.get(key) or "") for key in ("text", "contentDescription", "talkbackLabel", "mergedLabel"))
        action_type = str(requested.get("action_type") or "CLICK").upper()
        candidate = dict(action_kind=action_type, state_id=None, target_identity=identity,
            target_semantics=dict(role=node.get("role") or "", normalized_label=normalize_text(label),
                text=str(node.get("text") or ""), contentDescription=str(node.get("contentDescription") or ""),
                talkbackLabel=str(node.get("talkbackLabel") or ""), flags=dict(
                    clickable=node.get("clickable") is True, focusable=node.get("focusable") is True,
                    enabled=node.get("enabled") is not False, checkable=node.get("checkable") is True,
                    editable=node.get("editable") is True), actions=deepcopy(node.get("actions") or [])),
            evidence=dict(current_presence=len(matched) == 1),
            eligibility=dict(availability="AVAILABLE" if node.get("enabled") is not False else "DISABLED"))
        context = dict(state_id=(self.last_safety_report or {}).get("baseline_recommendation", {}).get("planner_state_id"),
            substate=(self.last_safety_report or {}).get("baseline_recommendation", {}).get("semantic_substates", []),
            destination=(raw.get("destination_ownership") or {}).get("destination") or raw.get("activity_name"),
            within_app=bool(raw.get("package_name") and raw.get("activity_name")
                and raw.get("context_source") == "window_current_focus"),
            recovery_verified=False, surrounding_labels=[], confirmation_verified=False,
            modal_verified=False, confirmation_risks=[])
        metadata = configured_metadata(candidate, context, self.safety_config)
        classification = classify_action(candidate, action_type=action_type, context=context, metadata=metadata,
            config=self.safety_config).to_dict()
        policy = evaluate_policy(classification, dict(current_target=len(matched) == 1,
            within_app=context["within_app"])).to_dict()
        self.authorization_failures += 1
        self._authorization_event("BLOCKED_BEFORE_DISPATCH", dispatch_kind="SECONDARY",
            request_id=str(request_id or ""), target_identity=identity, action_type=action_type,
            safety_class=classification.get("safety_class", "UNKNOWN"),
            policy_decision=policy.get("reason", "BLOCK_UNKNOWN"), classification=classification,
            policy=policy, target_resolution="UNIQUE" if len(matched) == 1 else "AMBIGUOUS_OR_MISSING",
            matched_target_count=len(matched), execution_gate=dict(allowed=False,
                reason="NO_EXACT_PHASE4_ACTION_GATE"), authorization_valid=False,
            invalidation_reason="NO_EXACT_SECONDARY_ACTION_AUTHORIZATION", executed=False)
        return False

    def _focus_command_allowed(self, command, *, dispatch_boundary=True):
        self._guard_hard_stop("preflight:focus_dispatch")
        permit = self.permit
        supplied = _extras(command)
        command_type = str(command[command.index("-a") + 1]).rsplit(".", 1)[-1]
        actual = focus_target_identity(dict(resource_id=supplied.get("targetId"),
            class_name=supplied.get("className"), bounds=supplied.get("bounds")))
        request_id = str(supplied.get("reqId") or "")
        reason = "" if command_type == "TARGET_FOCUS_COMMIT" else "UNSUPPORTED_FOCUS_COMMAND"
        classification, policy = None, None
        if not request_id:
            reason = "MISSING_REQUEST_ID"
        elif request_id in self.used_focus_request_ids:
            reason = "REUSED_REQUEST_ID"
        elif not permit or permit.get("kind") != "FOCUS" or permit.get("consumed"):
            reason = "NO_CURRENT_TARGET_PERMIT"
        elif permit.get("request") not in {None, request_id}:
            reason = "REQUEST_ID_MISMATCH"
        elif permit.get("authorization_epoch") != self.authorization_epoch:
            reason = "STALE_AUTHORIZATION_EPOCH"
        elif not permit.get("execution_gate", {}).get("allowed"):
            reason = "PHASE4_GATE_NOT_ALLOWED"
        elif permit.get("action_type") != "FOCUS":
            reason = "ACTION_TYPE_MISMATCH"
        elif actual != permit.get("target_identity"):
            reason = "TARGET_IDENTITY_MISMATCH"
        elif ownership(self.raw or {}) != permit.get("destination_ownership"):
            reason = "DESTINATION_OWNERSHIP_CHANGED"
        else:
            expected_epoch = canonical_sha256(dict(step=permit.get("step"), scenario=self.scenario,
                ownership=ownership(self.raw or {}), structure=structure(self.raw or {}),
                snapshot_hash=(self.raw or {}).get("snapshot_hash"), state_id=permit.get("state_id")))
            if expected_epoch != permit.get("observation_epoch"):
                reason = "OBSERVATION_EPOCH_CHANGED"
            else:
                from tb_runner.action_safety import configured_metadata
                from tb_runner.phase5a_safety import conditions_for
                from tb_runner.safe_action_policy import evaluate_policy
                candidate = permit["candidate"]
                metadata = configured_metadata(candidate, permit["context"], self.safety_config)
                classification = classify_action(candidate, action_type="FOCUS", context=permit["context"],
                    metadata=metadata, config=self.safety_config).to_dict()
                conditions = conditions_for(candidate, permit["context"], metadata, self.raw)
                policy = evaluate_policy(classification, conditions).to_dict()
                if classification.get("safety_class") not in {"SAFE", "CONDITIONALLY_SAFE"} or not policy.get("eligible"):
                    reason = "PHASE5A_POLICY_RECHECK_FAILED"
                elif classification.get("action_id") != permit.get("authorization_target_id"):
                    reason = "AUTHORIZATION_TARGET_CHANGED"

        if reason:
            if permit and permit.get("kind") == "FOCUS":
                self.authorization_failures += 1
            observed_classification, observed_policy = self._classify_unpermitted_focus_target(actual)
            row = self._authorization_event("BLOCKED_NATIVE_DISPATCH", dispatch_kind=(permit or {}).get("dispatch_kind", "SECONDARY"),
                request_id=request_id, target_identity=actual, action_type="FOCUS",
                safety_class=observed_classification.get("safety_class", "UNKNOWN"),
                policy_decision=observed_policy.get("reason", "BLOCK_UNKNOWN"),
                authorization_target_id=(permit or {}).get("authorization_target_id"),
                authorization_valid=False, invalidation_reason=reason,
                classification=observed_classification, policy=observed_policy,
                execution_gate=(permit or {}).get("execution_gate"), executed=False)
            self.command_blocks.append(dict(scenario=self.scenario, step=(self.raw or {}).get("step"),
                command=list(command), safety_class=row["safety_class"], policy_decision=reason, executed=False))
            return False

        if dispatch_boundary:
            permit["consumed"] = True
            permit["request"] = request_id
            self.used_focus_request_ids.add(request_id)
            self._authorization_event("NATIVE_DISPATCH_AUTHORIZED", dispatch_kind=permit["dispatch_kind"],
                request_id=request_id, target_identity=actual, action_type="FOCUS",
                safety_class=classification["safety_class"], policy_decision=policy["reason"],
                authorization_target_id=permit["authorization_target_id"], authorization_valid=True,
                destination_ownership=permit["destination_ownership"], state_id=permit["state_id"],
                observation_epoch=permit["observation_epoch"], execution_gate=permit["execution_gate"],
                classification=classification, policy=policy, executed=False)
        else:
            # Bind the one-use permit to the request before the client records
            # ACTION_SENT. The native ADB boundary repeats the full check and
            # consumes it only if this exact request is still valid.
            permit["request"] = request_id
        return True

    def preflight_focus_dispatch(self, *, target, request_id, dev=None):
        """Authorize before the client journals ACTION_SENT; ADB still rechecks."""
        self._guard_hard_stop("preflight:focus_dispatch")
        identity = focus_target_identity(target)
        command = ["shell", "am", "broadcast", "-a", ACTION_TARGET_FOCUS_COMMIT,
            "-p", "com.iotpart.sqe.talkbackhelper"] + [
            "--es", "bounds", identity["bounds"], "--es", "targetId", identity["resource_id"],
            "--es", "className", identity["class_name"], "--es", "reqId", str(request_id or "")]
        return self._focus_command_allowed(command, dispatch_boundary=False)

    def preflight_bounds_focus_dispatch(self, *, bounds, request_id, dev=None):
        """Reject bounds-only recovery before it can be journaled as dispatched."""
        self._guard_hard_stop("preflight:bounds_focus_dispatch")
        command = ["shell", "am", "broadcast", "-a", ACTION_FOCUS_IN_BOUNDS,
            "-p", "com.iotpart.sqe.talkbackhelper", "--es", "bounds", str(bounds or ""),
            "--es", "reqId", str(request_id or "")]
        return self._focus_command_allowed(command, dispatch_boundary=False)

    def command_allowed(self, command):
        words = [str(w) for w in command]
        upper = " ".join(words).upper()
        if words[:3] == ["shell", "am", "broadcast"]:
            try: action = words[words.index("-a")+1]
            except (ValueError, IndexError): return False
            if not action.startswith("com.iotpart.sqe.talkbackhelper.") or "-p" not in words or words[words.index("-p")+1] != "com.iotpart.sqe.talkbackhelper":
                return False
            suffix = action.rsplit(".",1)[-1]
            if suffix in {"DUMP_TREE", "DUMP_HIERARCHY", "GET_FOCUS", "PING", "EVIDENCE_EVENTS"}:
                return True
            if suffix == "TARGET_FOCUS_COMMIT":
                return self._focus_command_allowed(words)
            if suffix in {"FOCUS_TARGET", "FOCUS_IN_BOUNDS"}:
                return self._focus_command_allowed(words)
            if suffix in {"SMART_NEXT", "NEXT", "PREV"}:
                # Phase5A's unbound inventory movement is UNKNOWN. The bounded
                # adapter uses gated exact targets or passive GET_FOCUS fallback.
                return False
            if suffix == "SCROLL":
                return bool(self.permit and self.permit["kind"] == "SCROLL")
            if action == ACTION_CLICK_FOCUSED:
                p = self.permit
                proof = (p or {}).get("authorization") or {}
                target = proof.get("target_identity") or {}
                focused = (self.raw or {}).get("focus_node") or {}
                valid = bool(p and p["kind"] == "CLICK" and not p["consumed"] and "--es" in words
                    and "reqId" in words and words[words.index("reqId")+1] == p["request"]
                    and proof.get("action_type") == "NAVIGATE"
                    and proof.get("safety_class") in {"SAFE","CONDITIONALLY_SAFE"}
                    and (proof.get("policy") or {}).get("eligible") is True
                    and (proof.get("phase4_gate") or {}).get("allowed") is True
                    and proof.get("destination_ownership") == ownership(self.raw or {})
                    and proof.get("observation_epoch") == canonical_sha256(dict(
                        scenario=self.scenario,step=proof.get("step"),ownership=ownership(self.raw or {}),
                        structure=structure(self.raw or {}),state_id=proof.get("state_id")))
                    and _identity_matches(focused,target))
                if valid: p["consumed"] = True
                return valid
            return False
        if words[:3] == ["shell", "input", "keyevent"]:
            p = self.permit
            proof = (p or {}).get("authorization") or {}
            valid = bool(words[3:] == ["4"] and p and p["kind"] == "BACK" and not p["consumed"]
                and proof.get("action_type") == "NAVIGATE"
                and proof.get("safety_class") in {"SAFE","CONDITIONALLY_SAFE"}
                and (proof.get("policy") or {}).get("eligible") is True
                and proof.get("destination_ownership") == ownership(self.raw or {})
                and _identity_matches((self.raw or {}).get("focus_node") or {},proof.get("target_identity") or {})
                and proof.get("observation_epoch") == canonical_sha256(dict(
                    scenario=self.scenario,step=proof.get("step"),ownership=ownership(self.raw or {}),
                    structure=structure(self.raw or {}),state_id=proof.get("state_id"))))
            if valid: p["consumed"] = True
            return valid
        if words[:2] == ["shell", "input"]:
            return bool(words[2:3] == ["swipe"] and self.permit and self.permit["kind"] == "SCROLL")
        if words[:3] in (["shell", "am", "start"], ["shell", "am", "force-stop"]):
            return False
        if any(token in upper for token in ("SET_TEXT", "CHECK_TARGET", "CLICK_TARGET", "TOUCH_BOUNDS", "SET_SYSTEM_LANGUAGE")):
            return False
        # Read/diagnostic and existing screenshot/log transport are unaffected.
        if words[:1] in (["pull"],["logcat"],["get-state"],["devices"]): return True
        if words[:2] == ["shell","settings"]: return words[2:3] == ["get"]
        if words[:2] == ["shell","wm"]: return words[2:3] == ["size"]
        if words[:2] == ["shell","pm"]: return words[2:3] in (["path"],["list"])
        if words[:2] == ["shell","rm"]: return all(w in {"-f","/sdcard/temp.png","/sdcard/talkback_temp.png"} for w in words[2:])
        return bool(len(words)>1 and words[0]=="shell" and words[1] in {"dumpsys","pidof","getprop","cat","ls","screencap"})

    @contextmanager
    def firewall(self, client, dev):
        """Lowest existing ADB dispatch boundary, covering recovery and fallback."""
        saved = []
        forwarding = []
        prior_active_client = self._active_client
        self._active_client = client
        callback_name = "_phase5b_preflight_target_focus"
        bounds_callback_name = "_phase5b_preflight_bounds_focus"
        activation_callback_name = "_phase5b_preflight_activation"
        callback_had = callback_name in vars(client)
        callback_prior = vars(client).get(callback_name)
        setattr(client, callback_name, self.preflight_focus_dispatch)
        saved.append((client, callback_name, callback_had, callback_prior))
        bounds_callback_had = bounds_callback_name in vars(client)
        bounds_callback_prior = vars(client).get(bounds_callback_name)
        setattr(client, bounds_callback_name, self.preflight_bounds_focus_dispatch)
        saved.append((client, bounds_callback_name, bounds_callback_had, bounds_callback_prior))
        activation_callback_had = activation_callback_name in vars(client)
        activation_callback_prior = vars(client).get(activation_callback_name)
        setattr(client, activation_callback_name, self.preflight_activation_dispatch)
        saved.append((client, activation_callback_name, activation_callback_had, activation_callback_prior))
        def install(obj, name):
            original = getattr(obj, name, None)
            if not callable(original): return
            had, prior = name in vars(obj), vars(obj).get(name)
            def guarded(command, *args, **kwargs):
                self._guard_hard_stop(f"transport:{name}")
                requested_dev = kwargs.get("dev", args[0] if args else dev)
                # TalkBackClient._run -> AdbExecutor.run -> AdbDevice is one
                # dispatch. Consume its permit once, then accept exactly one
                # identical nested forwarding call at the lower boundary.
                receipt = forwarding[-1] if forwarding else None
                forwarded = bool(name == "_run_adb_command" and receipt
                    and not receipt["used"] and tuple(command) == receipt["command"]
                    and requested_dev == receipt["dev"])
                if requested_dev not in {None, dev} or not (forwarded or self.command_allowed(command)):
                    record = dict(scenario=self.scenario, step=(self.raw or {}).get("step"),
                        command=list(command), safety_class="UNKNOWN", policy_decision="BLOCK_UNAPPROVED_TRANSPORT", executed=False)
                    self.command_blocks.append(record)
                    self.sink("phase5b_transport_blocks.jsonl", record)
                    raise SafetyBlocked("Unapproved navigation/mutation transport")
                if forwarded: receipt["used"] = True
                if name != "_run":
                    return original(command, *args, **kwargs)
                forwarding.append(dict(command=tuple(command), dev=requested_dev, used=False))
                try:
                    return original(command, *args, **kwargs)
                finally:
                    forwarding.pop()
            setattr(obj, name, guarded)
            saved.append((obj,name,had,prior))
        # _run, target broadcasts and touch helpers use these two native paths.
        install(client, "_run")
        # _run_adb_command delegates to the executor directly, not client._run.
        install(getattr(client, "_adb_device", None), "_run_adb_command")
        device = getattr(client, "_adb_device", None)
        if callable(getattr(device, "_tap", None)):
            had, prior = "_tap" in vars(device), vars(device).get("_tap")
            def blocked_tap(*args, **kwargs):
                record = dict(scenario=self.scenario, step=(self.raw or {}).get("step"),
                    command=["DIRECT_TOUCH"], safety_class="UNKNOWN", policy_decision="BLOCK_UNAPPROVED_TOUCH", executed=False)
                self.command_blocks.append(record)
                self.sink("phase5b_transport_blocks.jsonl",record)
                raise SafetyBlocked("Touch has no Phase 5B effect contract")
            device._tap = blocked_tap
            saved.append((device,"_tap",had,prior))
        original_scroll = getattr(client, "scroll", None)
        had_scroll, prior_scroll = "scroll" in vars(client), vars(client).get("scroll")
        if callable(original_scroll):
            def safe_scroll(*args, **kwargs):
                self._guard_hard_stop("planner_scroll")
                cap = (self.raw or {}).get("capability") or {}
                container = cap.get("container") or {}
                if not (cap.get("axis_contract") == "axis-v1" and cap.get("contradictory") is False
                    and container.get("path") and kwargs.get("container_path") == container.get("path")
                    and normalized_bounds(kwargs.get("container_bounds")) == normalized_bounds(container.get("boundsInScreen"))
                    and cap.get("can_scroll_forward") is True and kwargs.get("direction") in {"forward", "down"}
                    and not re.search(r"(?i)seekbar|slider|range",str(container.get("className")))):
                    raise SafetyBlocked("Scroll container not independently proven")
                with self.authorize("SCROLL"):
                    return original_scroll(*args, **kwargs)
            client.scroll = safe_scroll
        try:
            yield
        finally:
            self._active_client = prior_active_client
            if callable(original_scroll):
                if had_scroll: client.scroll = prior_scroll
                else: vars(client).pop("scroll", None)
            for obj,name,had,prior in reversed(saved):
                if had: setattr(obj,name,prior)
                else: vars(obj).pop(name,None)

    def collect(self, collect, kwargs, audit, client):
        self._guard_hard_stop("fallback_or_collection")
        # A controlled action has already opened the current step transaction;
        # its move=False collection is the post-action observation. Other
        # move=False callers (for example local-tab recovery) still need a
        # separately owned, read-only observation transaction.
        if kwargs.get('move') is False:
            runtime = getattr(client, "evidence_runtime", None)
            active = getattr(client, "_evidence_active_transaction", None)
            step = kwargs.get("step_index")
            owned_here = bool(
                getattr(runtime, "is_enabled", False)
                and isinstance(active, dict)
                and active.get("state") == "open"
                and step is not None
                and str(active.get("step_index")) == str(step)
            )
            if getattr(runtime, "is_enabled", False) and not owned_here:
                return self.fallback(collect, kwargs, audit, client)
            return collect(**kwargs)
        return self.fallback(collect, kwargs, audit, client)

    def fallback(self, collect, kwargs, audit, client=None):
        """Pure production observation, never execute the UNKNOWN FOCUS_NEXT.

        Journal the actual exact GET_FOCUS request/ACK as the primary read-only
        operation so audit ownership is complete without inventing a focus move.
        """
        self._guard_hard_stop("fallback_observation")
        self.invalidate_authorization("FALLBACK_BOUNDARY")
        raw = self.raw or {}
        audit.update(fallback_safety_class="SAFE", fallback_policy_decision="READ_ONLY_FOCUS_OBSERVATION")
        self.sink("phase5b_fallback_safety.jsonl", dict(scenario=self.scenario, step=raw.get("step"),
            classification="SAFE", policy=audit["fallback_policy_decision"], focus_move_executed=False, navigation_executed=False))
        kwargs={**kwargs,"move":False}
        if client is None: return collect(**kwargs)
        client.last_smart_nav_result,client.last_smart_nav_terminal={},False
        client._evidence_set_step(kwargs.get("step_index"),phase="main_loop")
        client._evidence_begin_step_action("SAFE_FALLBACK_OBSERVATION")
        reader,broadcast=client._read_log_result,client._broadcast
        saved={name:(name in vars(client),vars(client).get(name)) for name in ["_read_log_result","_broadcast"]}
        request={"ids": [], "acknowledged_ids": [], "transaction_id": ""}
        source_request_id = str(audit.get("helper_request_id") or "")
        observation_type = ("POST_ACTION" if audit.get("planner_executed") else
                            "FALLBACK" if audit.get("fallback_used") else "RECOVERY")
        audit["fallback_observation_ownership"] = dict(
            status="UNRESOLVED", step=kwargs.get("step_index"),
            transaction_id="", request_ids=[], acknowledged_request_ids=[],
            request_domains={},
            request_domain="FOCUS_OBSERVATION", read_only=True,
            observation_type=observation_type, source_action_request_id=source_request_id)
        def observed_broadcast(dev,action,extras=None):
            if action.endswith('.GET_FOCUS') and extras and 'reqId' in extras:
                req=extras[extras.index('reqId')+1]
                request['id']=str(req)
                request["ids"].append(str(req))
                active=getattr(client,"_evidence_active_transaction",None)
                request["transaction_id"]=(str(active.get("transaction_id") or "")
                    if isinstance(active,dict) else "")
                client._evidence_action_sent(action=action,req_id=req)
                audit["fallback_observation_ownership"] = dict(
                    status="UNRESOLVED", step=kwargs.get("step_index"),
                    transaction_id=request["transaction_id"], request_ids=list(request["ids"]),
                    acknowledged_request_ids=list(request["acknowledged_ids"]),
                    request_domains={req: "FOCUS_OBSERVATION" for req in request["ids"]},
                    request_domain="FOCUS_OBSERVATION", read_only=True,
                    observation_type=observation_type, source_action_request_id=source_request_id)
            return broadcast(dev,action,extras)
        def observed_reader(*args,**kw):
            result=reader(*args,**kw)
            prefix=kw.get('prefix',args[1] if len(args)>1 else None)
            req=kw.get('req_id',args[2] if len(args)>2 else None)
            if prefix=='FOCUS_RESULT' and str(req)==request.get('id'):
                client._evidence_helper_ack(result,req_id=req,source='phase5b_read_only_fallback')
                response_req=str((result or {}).get("reqId") or (result or {}).get("requestId") or "")
                if response_req == str(req):
                    request["acknowledged_ids"].append(str(req))
                    audit["fallback_observation_ownership"] = dict(
                        status="PROVEN" if request["transaction_id"] and getattr(
                            getattr(client,"evidence_runtime",None),"is_enabled",False) else "UNRESOLVED",
                        step=kwargs.get("step_index"), transaction_id=request["transaction_id"],
                        request_ids=list(request["ids"]),
                        acknowledged_request_ids=list(request["acknowledged_ids"]),
                        request_domains={req: "FOCUS_OBSERVATION" for req in request["ids"]},
                        request_domain="FOCUS_OBSERVATION", read_only=True,
                        observation_type=observation_type, source_action_request_id=source_request_id)
                    # This is an exact read-only receipt, never movement success.
                    client.last_smart_nav_result=dict(reqId=str(req),success=False,status='OBSERVED_NO_MOVE')
                else:
                    # A stale/mismatched Helper payload cannot become this
                    # step's receipt, even when the query used the new ID.
                    client.last_smart_nav_result={}
            return result
        client._broadcast,client._read_log_result=observed_broadcast,observed_reader
        try:
            # Failed controlled focus may already have moved. Read its actual
            # landing before the passive collection so the read itself cannot
            # inherit movement from an earlier request/navigation transaction.
            before_focus=client.get_focus(dev=kwargs.get('dev'),allow_fallback_dump=False,mode='fast') or {}
            row=collect(**kwargs)
            owner = audit.get("fallback_observation_ownership")
            if isinstance(owner, dict):
                node = row.get("actual_focus_node") if isinstance(row, dict) else None
                owner["production_request_id"] = (
                    row.get("get_focus_req_id") if isinstance(row, dict) else None
                ) or ((node or {}).get("reqId") if isinstance(node, dict) else None) or ""
            from tb_runner.phase4b_execution import focus_row
            row['phase4b_before_row']=focus_row(before_focus,self.scenario)
            return row
        finally:
            for name,(had,prior) in saved.items():
                if had:setattr(client,name,prior)
                else:vars(client).pop(name,None)

    def roundtrip(self, *, client, dev, capture, step):
        """At most one reviewed read-only menu roundtrip, no graph exploration."""
        if self.completed: return None
        self.completed = True
        parent, value, context = capture()
        if context["status"] != "VERIFIED_ROOT_CONTEXT" or (parent.get("overlay") or {}).get("observed") is not False:
            return None
        candidates = value.snapshot.to_dict()["candidates"]
        options = [(c,k) for c in candidates if c["action_kind"] == "FOCUS_TARGET" for k in self.contracts["contracts"]
            if parent.get("package_name") == k["package"] and c["target_identity"].get("resource_id") == k["resource_id"]
            and re.fullmatch(k["label_pattern"], c["target_semantics"].get("normalized_label") or "")]
        if len(options) != 1: return None
        target, contract = options[0]
        allowed = {production_instance(target["target_identity"],self.scenario)}
        # Separate reviewed navigation task domain. Content-only production
        # allowlists intentionally omit toolbar chrome; they remain unchanged
        # for traversal. This projection authorizes only this menu task, using
        # the exact same Phase 4 ranking, actual histories and fresh gates.
        value = replace(value, history=replace(value.history, allowed_instance_ids=tuple(allowed)))
        rec = plan_shadow(value)
        fresh, current, _ = capture()
        current = replace(current, history=replace(current.history, allowed_instance_ids=tuple(allowed)))
        evidence = AuthorityEvidence(enabled=True, fresh=True, recovery_clear=fresh.get("phase5b_recovery_clear") is True,
            lifecycle_clear=not bool(get_talkback_restart_event(client)), transport_clear=client.check_helper_status(dev=dev),
            focus_coherent=coherent_focus(fresh), structural_scope_proven=ownership(parent)==ownership(fresh),
            geometry_in_viewport=geometry_in_viewport(fresh,rec), scroll_container_proven=False)
        gate = execution_gate(value,rec,current,evidence,action_limit=3)
        nav_context = dict(destination=ownership(parent), state_id=target.get("state_id"))
        classification = classify_action(target, action_type="NAVIGATE", context=nav_context,
            metadata=dict(source="CONFIGURED",effect=contract["effect"]))
        conditions = dict(current_target=True,within_app=ownership(parent)==ownership(fresh),
            read_only_effect=True,recovery_verified=contract["return_transport"]=="BACK" and coherent_focus(fresh))
        policy = evaluate_policy(classification,conditions)
        record = dict(schema="phase5b-navigation-chain-v1", scenario=self.scenario, step=step,
            action_id=classification.to_dict()["action_id"], classification=classification.to_dict(), conditions=conditions,
            policy=policy.to_dict(), phase4_gate=gate.to_dict(), parent_destination=ownership(parent),
            parent_state=value.snapshot.state_id, navigation_epoch=parent.get("navigation_epoch"),
            expected_return_scope=ownership(parent), entry_confirmed=False, return_required=False,
            return_attempted=False, return_success=False, attempt_credit=0, visit_credit=0)
        if not gate.allowed or not policy.eligible:
            self.sink("phase5b_navigation_chains.jsonl",record)
            return record
        nav_step=f"phase5b:{step}:navigation"
        client._evidence_set_step(nav_step,phase="safe_navigation")
        focus_audit = {}
        focus_row = controlled_collect(client=client,dev=dev,scenario=self.scenario,step=nav_step,raw=fresh,
            recommendation=rec,decision=gate,budget=ExecutionBudget(3),collect=client.collect_focus_step,
            collect_kwargs=dict(dev=dev,step_index=nav_step,move=False,wait_seconds=0.2),
            refresh=lambda: {},output_dir="",audit=focus_audit,
            focus_authorization=lambda exact_target, node: self.authorize_focus_target(
                raw=fresh, value=current, target=exact_target, phase4_gate=gate,
                step=nav_step, dispatch_kind="NAVIGATION_PREPARATION"))
        record["focus_preparation"] = focus_audit
        focused, focused_value, _ = capture()
        if focus_audit.get("planner_failed") or not focus_audit.get("helper_result_correlated") or not coherent_focus(focused):
            record["failure"]="SAFE_NAVIGATION_FOCUS_PREPARATION_FAILED"
            self.sink("phase5b_navigation_chains.jsonl",record)
            raise SafetyBlocked(record["failure"])
        focus = focused.get("focus_node") or {}
        t=target["target_identity"]
        if (focus.get("viewIdResourceName") or focus.get("resourceId") or "") != t["resource_id"] or normalized_bounds(focus.get("boundsInScreen")) != t["bounds"] or ownership(focused)!=ownership(parent) or structure(focused)!=structure(fresh):
            raise SafetyBlocked("SAFE_NAVIGATION_FOCUS_TARGET_CHANGED")
        if get_talkback_restart_event(client) or not client.check_helper_status(dev=dev):
            raise SafetyBlocked("SAFE_NAVIGATION_LIFECYCLE_OR_TRANSPORT_CHANGED")
        request=uuid.uuid4().hex
        self.invalidate_authorization("NAVIGATION_ENTRY_TARGET_REFRESH")
        self.raw=deepcopy(focused)
        focus_state=focused_value.snapshot.to_dict()
        entry_authorization=dict(target_identity=focus_target_identity(t),action_type="NAVIGATE",
            safety_class=classification.to_dict()["safety_class"],policy=policy.to_dict(),phase4_gate=gate.to_dict(),
            destination_ownership=ownership(focused),state_id=focus_state.get("state_id"),step=nav_step,
            observation_epoch=canonical_sha256(dict(scenario=self.scenario,step=nav_step,
                ownership=ownership(focused),structure=structure(focused),state_id=focus_state.get("state_id"))))
        client._evidence_set_step(nav_step,phase="safe_navigation")
        client._evidence_begin_step_action("SAFE_NAVIGATION_ENTRY")
        client._evidence_action_sent(action=ACTION_CLICK_FOCUSED,req_id=request)
        with self.authorize("CLICK",request,entry_authorization):
            client._broadcast(dev,ACTION_CLICK_FOCUSED,["--es","reqId",request])
        ack=client._read_log_result(dev,"TARGET_ACTION_RESULT",request)
        client._evidence_helper_ack(ack,req_id=request,source="phase5b_single_dispatch")
        record.update(entry_executed=True,entry_request_id=request,entry_ack=deepcopy(ack),
            entry_correlated=str(ack.get("reqId") or "")==request)
        child_reads=[]
        for _ in range(3):
            child, child_value, _ = capture(observe_owner=False)
            child_reads.append(deepcopy(child))
            child_changed=structure(child)!=structure(parent)
            component_match=all(ownership(child)[k]==ownership(parent)[k] for k in ("package","activity","scenario","run","entry"))
            no_mutation=not any(n.get("editable") is True or n.get("checkable") is True
                or re.search(r"(?i)edittext|checkbox|switch|seekbar|slider",str(n.get("className"))) for n in child.get("nodes",[]))
            safe_child=component_match and child_changed and no_mutation
            # Only bounded read-only settling; entry is dispatched exactly once.
            # Wrong scope or mutation stops immediately, never waits it away.
            if not component_match or not no_mutation or safe_child and coherent_focus(child): break
        record.update(child_destination=ownership(child),child_state=canonical_sha256(structure(child)),
            entry_confirmed=bool(record["entry_correlated"] and ack.get("success") is True and safe_child and coherent_focus(child)),
            child_observation=deepcopy(child),child_settle_observations=child_reads,return_required=bool(child_changed))
        if not record["entry_confirmed"]:
            self.sink("phase5b_navigation_chains.jsonl",record)
            raise SafetyBlocked("SAFE_CHILD_ENTRY_NOT_PROVEN")
        # Return inherits this exact entered, non-mutating menu lease. No
        # arbitrary generic BACK or OK is authorized.
        return_target=current_return_target(child,child_value)
        return_class=classify_action(return_target,action_type="NAVIGATE",context={**nav_context,"destination":ownership(child),"substate":["RETURN"]},
            metadata=dict(source="CONFIGURED",effect="read_only_navigation"))
        return_conditions=dict(current_target=True,within_app=True,read_only_effect=safe_child,recovery_verified=True)
        return_policy=evaluate_policy(return_class,return_conditions)
        record.update(return_action="BACK",return_classification=return_class.to_dict(),
            return_conditions=return_conditions,return_policy=return_policy.to_dict(),return_attempted=False)
        if not return_policy.eligible or get_talkback_restart_event(client):
            record["failure"]="SAFE_RETURN_GATE_FAILED"
            self.sink("phase5b_navigation_chains.jsonl",record)
            raise SafetyBlocked("SAFE_RETURN_GATE_FAILED")
        immediate,immediate_value,_=capture(observe_owner=False)
        if ownership(immediate)!=ownership(child) or structure(immediate)!=structure(child) or not coherent_focus(immediate) or not client.check_helper_status(dev=dev):
            record["failure"]="SAFE_RETURN_CHILD_CHANGED"
            record["immediate_return_observation"]=immediate
            self.sink("phase5b_navigation_chains.jsonl",record)
            raise SafetyBlocked("SAFE_RETURN_CHILD_CHANGED")
        record["immediate_return_observation"]=immediate
        self.invalidate_authorization("SAFE_RETURN_TARGET_REFRESH")
        self.raw=deepcopy(immediate)
        return_state=immediate_value.snapshot.to_dict()
        return_authorization=dict(target_identity=focus_target_identity(return_target.get("target_identity") or {}),
            action_type="NAVIGATE",safety_class=return_class.to_dict()["safety_class"],
            policy=return_policy.to_dict(),destination_ownership=ownership(immediate),
            state_id=return_state.get("state_id"),step=nav_step+":return",
            observation_epoch=canonical_sha256(dict(scenario=self.scenario,step=nav_step+":return",
                ownership=ownership(immediate),structure=structure(immediate),state_id=return_state.get("state_id"))))
        client._evidence_set_step(nav_step+":return",phase="safe_navigation")
        client._evidence_begin_step_action("SAFE_NAVIGATION_RETURN")
        client._evidence_action_sent(action="BACK",req_id=uuid.uuid4().hex)
        with self.authorize("BACK",authorization=return_authorization):
            client._run(["shell","input","keyevent","4"],dev=dev)
        record["return_attempted"]=True
        # Capture can fall back from service hierarchy to a shorter Helper
        # tree. Such a sample is inconclusive when its selected-tab evidence
        # disappears. Allow only bounded passive settling, and require two
        # consecutive complete matches. No navigation action is retried.
        return_observations=[]
        return_contexts=[]
        return_checks=[]
        confirmed_pair=None
        for _ in range(4):
            returned,_,returned_context=capture()
            status=returned_context.get("status")
            conflict=return_scope_conflict(parent,returned,status)
            complete=(not conflict and status==context["status"] and same_parent(parent,returned))
            return_observations.append(returned)
            return_contexts.append(status)
            return_checks.append(dict(context_status=status,complete_parent_match=complete,scope_conflict=conflict))
            if conflict:
                break
            if len(return_checks)>=2 and return_checks[-2]["complete_parent_match"] and complete:
                confirmed_pair=(len(return_checks)-2,len(return_checks)-1)
                break
        match=confirmed_pair is not None
        returned_last=return_observations[-1]
        record.update(return_destination=ownership(returned_last),return_ownership_match=match,
            return_context_revalidated=match,return_success=match,
            return_observations=return_observations,return_context_statuses=return_contexts,
            return_observation_checks=return_checks,return_confirmed_pair=confirmed_pair)
        runtime=getattr(client,"evidence_runtime",None)
        record["native_entry_events"]=[e.to_dict() for e in runtime.events_for_step(nav_step)] if runtime else []
        record["native_return_events"]=[e.to_dict() for e in runtime.events_for_step(nav_step+":return")] if runtime else []
        record["chain_id"]=canonical_sha256(record)
        self.sink("phase5b_navigation_chains.jsonl",record)
        client._evidence_set_step(step,phase="main_loop")
        if not record["return_success"]: raise SafetyBlocked("SAFE_RETURN_OWNERSHIP_NOT_PROVEN")
        return record
