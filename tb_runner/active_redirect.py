"""OFF-default ACTIVE coordination over existing RF2/RF3R and Phase4/5 authorities.

No capture is performed for readiness. The only execution is controlled_collect
under the existing Phase5 firewall/FOCUS permit. This module awards no visits.
"""
from copy import deepcopy
from collections.abc import Mapping


_REVALIDATION_FIELDS = (
    "decision_id", "decision_watermark", "scope_id", "action_epoch", "observation_id",
    "observation_sequence", "observation_epoch", "context_revision", "proof", "conditions",
    "identity_bridge", "target_identity", "state_id", "frontier_id",
)


def lifecycle_revalidation_state(conditions, token, process_observation, continuity_revision):
    """Project lifecycle safety identity plus a separately checked version.

    No permit/READY is produced. The common evaluator still must say READY.
    Only recorder counters/step may advance; PID, recorder, scope and stable
    process evidence cannot change. Missing evidence fails closed.
    """
    if (not isinstance(token, tuple) or len(token) != 9 or token[0] is not True
            or type(token[1]) is not int or not token[1]
            or type(token[2]) is not str or not token[2]
            or type(token[3]) is not int or token[3] <= 0
            or type(token[4]) is not int or token[4] < 0
            or token[5] is not False or type(token[6]) is not str or not token[6]
            or token[7] != "NONE" or token[8] is not None):
        raise ValueError("LIFECYCLE_EXECUTION_EVIDENCE_UNKNOWN_OR_BLOCKED")
    sample = process_observation
    if (not isinstance(sample, Mapping) or sample.get("schema") != "lifecycle-process-observation-v1"
            or type(sample.get("event_count")) is not int or sample["event_count"] != token[3]
            or sample.get("pid") != token[6] or sample.get("enabled") is not True
            or sample.get("process_event") != "running" or sample.get("restart_detected") is not False
            or sample.get("snapshot_error") is not False
            or type(continuity_revision) is not int or continuity_revision < 0):
        raise ValueError("CURRENT_LIFECYCLE_PROCESS_SAMPLE_UNKNOWN_OR_BLOCKED")
    if conditions.get("lifecycle_status") != "CLEAR":
        raise ValueError("LIFECYCLE_NOT_CLEAR")
    evidence = conditions.get("lifecycle_evidence")
    if not isinstance(evidence, Mapping) or evidence.get("lifecycle_effective_for_readiness") != "CLEAR":
        raise ValueError("LIFECYCLE_EFFECTIVE_EVIDENCE_UNAVAILABLE")

    def critical(doc, *, current=False, nested=False):
        if (not isinstance(doc, Mapping) or doc.get("source") != "WindowLifecycleRecorder"
                or doc.get("recorder_present") is not True or doc.get("scenario_match") is not True
                or type(doc.get("recorder_reference")) is not int or doc["recorder_reference"] != token[1]
                or doc.get("previous_pid_present") is not True
                or doc.get("enabled_process_gap") is not False
                or doc.get("restart_event_present") is not False
                or doc.get("restart_process_event") is not None
                or doc.get("process_evidence") != "STABLE"
                or type(doc.get("event_count")) is not int or doc["event_count"] <= 0
                or type(doc.get("row_step")) is not int
                or type(doc.get("recorder_step")) is not int
                or doc["recorder_step"] < doc["row_step"]
                or (nested and doc.get("status") != "CLEAR")):
            raise ValueError("LIFECYCLE_PROCESS_OR_CONTINUITY_NOT_PROVEN")
        if current and (doc["event_count"] != token[3] or doc["recorder_step"] != token[4]):
            raise ValueError("LIFECYCLE_SNAPSHOT_TOKEN_MISMATCH")
        # Versions are validated above and below, not used as execution identity.
        # Human reason strings/merge descriptions are diagnostics only.
        return (doc["source"], doc["recorder_reference"], doc["row_step"],
                "STABLE", "NO_RESTART", "NO_ENABLED_GAP", "PID_PRESENT")

    identity = ("active-lifecycle-semantic-v1", token[1], token[2], token[6], continuity_revision,
                critical(evidence, current=True),
                critical(evidence.get("lifecycle_pre_decision"), nested=True),
                critical(evidence.get("lifecycle_post_collector"), current=True, nested=True))
    return identity, (token[3], token[4])


def active_revalidation_document(diagnostic, lifecycle_token, process_observation, continuity_revision):
    """Keep existing provenance/proofs exact; normalize lifecycle semantics only."""
    conditions = deepcopy(diagnostic["conditions"])
    identity, version = lifecycle_revalidation_state(conditions, lifecycle_token,
                                                    process_observation, continuity_revision)
    conditions["lifecycle_evidence"] = identity
    document = {key: diagnostic.get(key) for key in _REVALIDATION_FIELDS}
    document["conditions"] = conditions
    return document, version


def collect_active_redirect(*, original_collect, collect_kwargs, client, dev,
                            fallback_collect=None,
                            state, phase_ctx, step_idx, tab_cfg, controller):
    from tb_runner import collection_flow as flow
    from tb_runner.exploration_redirect import selected_redirect_hint
    from tb_runner.phase4b_authority import ExecutionBudget, execution_gate, AuthorityEvidence
    from tb_runner.phase4b_execution import controlled_collect, coherent_focus, geometry_in_viewport
    from tb_runner.phase4a_planner import plan_shadow
    from tb_runner.phase4b_target_binding import resolve_focus_target
    from tb_runner.phase5b_navigation import SafeNavigationSession
    from tb_runner.canonical_json import canonical_sha256

    scenario = str(tab_cfg.get("scenario_id") or "")
    inputs = flow._phase6d3a_shadow_decision_inputs(client, state, phase_ctx, tab_cfg)
    hint, reason = selected_redirect_hint(inputs["record"], scenario_id=scenario,
        scenario_type=str(tab_cfg.get("scenario_type", "content")),
        screen_context_mode=str(tab_cfg.get("screen_context_mode", "")),
        require_execution_ready=False)
    if hint is None:
        # No redirect candidate means continue through the harness's normal
        # controlled path when present. The ACTIVE adapter's own observation
        # and fallback calls still use the base production collector supplied
        # as original_collect, avoiding wrapper recursion.
        collector = fallback_collect if callable(fallback_collect) else original_collect
        return collector(**dict(collect_kwargs))
    run_limit = int(tab_cfg.get("max_steps", 0) or 0) or None
    audit = {**hint, "mode": "ACTIVE", "schema_version": "phase6d3a-redirect-attempt-v1",
             "status": "PREPARING", "recommendation": True, "ready": False,
             "dispatch_attempted": False, "dispatch_count": 0, "attempt_credit": 0,
             "visit_credit": 0, "fallback_count": 0}
    client._phase6d3a_last_step_audit = audit
    events, controlled_audit = [], {}
    session = SafeNavigationSession(scenario, lambda name, record: events.append(
        {"name": name, "record": deepcopy(record)}))
    fallback = {"attempted": False, "row": None, "observation": None}
    recorded = False

    def finish(row):
        nonlocal recorded
        audit["phase5_authorization_events"] = events[-8:]
        if not recorded:
            recorded = True
            controller.record(audit)
        row["phase6d3a_redirect"] = deepcopy(audit)
        client._phase6d3a_last_step_audit = deepcopy(audit)
        return row

    def passive(reason):
        if fallback["attempted"]:
            return fallback["row"]
        fallback["attempted"] = True
        audit.update(fallback_count=1, fallback_attempted=True, fallback_used=True,
                     fallback_trigger=reason, fallback_action_type="SAFE_FALLBACK_OBSERVATION")
        try:
            # Existing Phase5-safe observation fallback; never raw SMART_NEXT.
            observed = fallback["observation"]
            audit["fallback_observation_reused"] = isinstance(observed, dict)
            collector = (lambda **_kwargs: observed) if isinstance(observed, dict) else original_collect
            row = session.collect(collector, dict(collect_kwargs), audit, client)
            if not isinstance(row, dict):
                raise TypeError("fallback returned a non-row")
            audit["fallback_ownership"] = deepcopy(audit.get("fallback_observation_ownership") or {})
        except Exception as exc:
            from talkback_lib.step_row_builder import create_base_step_row
            row = create_base_step_row(step_idx)
            row.update(status="ERROR", final_result="ERROR", move_result="NOT_DISPATCHED",
                       actual_focus_node={}, actual_focus_accessibility_focused=False,
                       visit_record_status="UNVISITED_NOT_CREDITED",
                       reconciled_visit_instance_id="", focus_transition_status="UNAVAILABLE")
            audit["fallback_error"] = type(exc).__name__
        fallback["row"] = row
        return row

    def blocked(reason, status="BLOCKED_BEFORE_DISPATCH"):
        audit.update(status=status, reason=reason)
        return finish(passive(reason))

    budget = getattr(client, "_phase6d3a_controlled_budget", None)
    if not isinstance(budget, ExecutionBudget):
        budget = ExecutionBudget(max_actions=min(5, max(1, run_limit or 5)))
        client._phase6d3a_controlled_budget = budget

    pending = {}
    prior_entries = deepcopy(getattr(getattr(client, "_target_attempt_ledger", None), "entries", {}))
    try:
        token = flow._phase6d3a_capture_shadow_decision_token(
            client=client, state=state, phase_ctx=phase_ctx, tab_cfg=tab_cfg)

        def readiness():
            evidence_client = client
            if pending:
                # Only the Phase4-owned current pending attempt is not prior
                # planner history. Never hide a result or an unrelated mutation.
                entries = getattr(getattr(client, "_target_attempt_ledger", None), "entries", {})
                attempt_id = pending["attempt_id"]
                entry = entries.get(attempt_id, {})
                target = entry.get("target") or {}
                if (set(entries) != set(prior_entries) | {attempt_id}
                        or any(entries[k] != v for k, v in prior_entries.items())
                        or entry.get("state") != "NO_RESULT" or entry.get("result_count") != 0
                        or entry.get("scenario_id") != scenario or entry.get("step") != step_idx
                        or target.get("resource_id") != chosen["recommended_target"].get("resource_id")
                        or target.get("bounds") != chosen["recommended_target"].get("bounds")
                        or target.get("class_name") != chosen["recommended_target"].get("class_name")):
                    raise RuntimeError("PENDING_ATTEMPT_OWNERSHIP_MISMATCH")
                from copy import copy
                from types import SimpleNamespace
                evidence_client = copy(client)
                evidence_client._target_attempt_ledger = SimpleNamespace(entries=deepcopy(prior_entries))
            current = flow._phase6d3a_shadow_decision_inputs(evidence_client, state, phase_ctx, tab_cfg)
            current["source_signature"] = dict(flow._phase6d3a_decision_signature(current))
            current["inventory_reference"] = current["source_signature"]["inventory_reference"]
            current["history_reference"] = current["source_signature"]["history_reference"]
            alignment = flow._phase6d3a_bind_shadow_decision_token(token, current)
            clock = current["clock"]
            if clock is None or not clock.current(current["record"].get("observation_alignment") or {}):
                alignment = {**alignment, "status": "UNKNOWN",
                             "reason_codes": alignment["reason_codes"] + ["ACTIVE_CLOCK_NOT_CURRENT"]}
            projection = {}
            owner = dict(current["owner"])
            owner["registry"] = deepcopy(owner.get("registry"))
            diagnostic = flow._phase6d3a_shadow_readiness(
                record=current["record"], inventory_record=current["inventory"],
                scenario_id=scenario, scenario_type=str(tab_cfg.get("scenario_type", "content")),
                screen_context_mode=str(tab_cfg.get("screen_context_mode", "")),
                evidence_current=alignment["status"] == "MATCH", client=evidence_client, state=state,
                phase_ctx=phase_ctx, previous_rows=current["rows"], previous_row=current["row"],
                authority_evidence_type=AuthorityEvidence, coherent_focus_fn=coherent_focus,
                geometry_in_viewport_fn=geometry_in_viewport, decision_token=token,
                decision_alignment=alignment, decision_owner=owner,
                execution_projection=projection)
            return diagnostic, projection

        diagnostic, projection = readiness()
        audit["common_readiness"] = diagnostic
        audit["readiness_status"] = diagnostic["readiness_status"]
        audit["ready"] = diagnostic["readiness_status"] == "READY"
        if not audit["ready"]:
            return blocked(diagnostic["reason"], diagnostic["readiness_status"])
        recorder = getattr(client, "_window_lifecycle_recorder", None)
        try:
            baseline_document, lifecycle_version = active_revalidation_document(
                diagnostic, flow._phase6d3a_capture_lifecycle_token(client),
                getattr(recorder, "last_process_observation", None),
                getattr(recorder, "process_continuity_revision", None))
        except ValueError as exc:
            return blocked(str(exc), "UNKNOWN")
        baseline = canonical_sha256(baseline_document)
        audit["lifecycle_version_before"] = lifecycle_version
        raw, value = projection["raw"], projection["value"]
        raw["snapshot_hash"] = value.snapshot.candidate_set_hash
        recommendation = plan_shadow(value)
        chosen = recommendation.to_dict()
        gate = execution_gate(value, recommendation, projection["current"], projection["authority"],
            actions_used=budget.actions, degraded=budget.degraded or controller.budget.active_disabled,
            action_limit=budget.max_actions)
        if not gate.allowed or gate.mode != "CONTROLLED_TARGET_FOCUS":
            return blocked("PHASE4_GATE_" + gate.reason)
        node, binding = resolve_focus_target(raw, chosen, scenario)
        if node is None:
            return blocked("EXACT_TARGET_BINDING_REQUIRED")

        def revalidate():
            allowed, reason = controller.budget.available(hint, run_limit=run_limit)
            if not allowed or budget.degraded or budget.actions >= budget.max_actions:
                return False, reason if not allowed else "CONTROLLED_BUDGET_EXHAUSTED"
            fresh, current_projection = readiness()
            if fresh["readiness_status"] != "READY":
                return False, "DECISION_REVALIDATION_NONREADY"
            try:
                document, current_version = active_revalidation_document(
                    fresh, flow._phase6d3a_capture_lifecycle_token(client),
                    getattr(getattr(client, "_window_lifecycle_recorder", None), "last_process_observation", None),
                    getattr(getattr(client, "_window_lifecycle_recorder", None), "process_continuity_revision", None))
            except ValueError:
                return False, "LIFECYCLE_REVALIDATION_UNKNOWN_OR_BLOCKED"
            if (current_version[0] < lifecycle_version[0]
                    or current_version[1] < lifecycle_version[1]):
                return False, "LIFECYCLE_VERSION_REGRESSED"
            audit["lifecycle_version_current"] = current_version
            if canonical_sha256(document) != baseline:
                return False, "DECISION_REVALIDATION_STALE_OR_NONREADY"
            current_value = current_projection["value"]
            current_plan = plan_shadow(current_value)
            current_gate = execution_gate(current_value, current_plan, current_projection["current"],
                current_projection["authority"], actions_used=budget.actions,
                degraded=budget.degraded, action_limit=budget.max_actions)
            current_node, current_binding = resolve_focus_target(
                current_projection["raw"], current_plan.to_dict(), scenario)
            if (not current_gate.allowed or current_gate.mode != "CONTROLLED_TARGET_FOCUS"
                    or current_plan.to_dict() != chosen or current_node is None
                    or current_binding != binding):
                return False, "PLANNER_OR_BINDING_REVALIDATION_FAILED"
            return True, "FINAL_REVALIDATION_PASS"

        base_gate = session._focus_command_allowed
        def guarded_gate(command, *, dispatch_boundary=True):
            ok, reason = revalidate()
            audit["final_revalidation"] = reason
            if not ok:
                return False
            return base_gate(command, dispatch_boundary=dispatch_boundary)
        session._focus_command_allowed = guarded_gate
        ok, reason = revalidate()
        if not ok:
            return blocked(reason)

        def dispatched(evidence):
            # Phase4 owns this typed native event, including accounting errors.
            if evidence is not None:
                audit.update(dispatch_status=evidence.dispatch_status, operation_id=evidence.operation_id,
                             helper_request_id=evidence.request_id,
                             dispatch_attempted=evidence.dispatch_status == "DISPATCHED",
                             dispatch_count=int(evidence.dispatch_status == "DISPATCHED"),
                             attempt_credit=int(evidence.dispatch_status == "DISPATCHED"))
            controller.account_dispatch(evidence, hint=hint, run_limit=run_limit)

        def collect(**kwargs):
            if kwargs.get("move") is True:
                return passive(controlled_audit.get("fallback_reason") or "PHASE4_SAFE_FALLBACK")
            row = session.collect(original_collect, kwargs, controlled_audit, client)
            fallback["observation"] = row
            return row

        with session.firewall(client, dev):
            row = controlled_collect(client=client, dev=dev, scenario=scenario, step=step_idx,
                raw=raw, recommendation=recommendation, decision=gate, budget=budget,
                collect=collect, collect_kwargs=dict(collect_kwargs), refresh=lambda: {},
                output_dir="", audit=controlled_audit,
                focus_authorization=lambda target, node: session.authorize_focus_target(
                    raw=raw, value=value, target=target, phase4_gate=gate, step=step_idx,
                    dispatch_kind="PHASE6D3A_REDIRECT"),
                native_dispatch_observer=dispatched,
                operation_observer=lambda operation, attempt: pending.update(
                    operation_id=operation, attempt_id=attempt))
        audit.update(controlled_path_audit=deepcopy(controlled_audit),
                     helper_result_correlated=bool(controlled_audit.get("helper_result_correlated")),
                     dispatch_evidence=deepcopy(controlled_audit.get("dispatch_evidence") or {}),
                     status="AWAITING_PRODUCTION_RECONCILIATION" if audit["dispatch_attempted"]
                         else "UNKNOWN" if controlled_audit.get("dispatch_status") == "UNKNOWN"
                         else "BLOCKED_BEFORE_DISPATCH")
        return finish(row)
    except Exception as exc:
        audit.update(reason="ACTIVE_ADAPTER_ERROR_" + type(exc).__name__,
                     controlled_path_audit=deepcopy(controlled_audit))
        if audit.get("dispatch_attempted") or controlled_audit.get("dispatch_status") == "UNKNOWN":
            audit["status"] = "ADAPTER_ERROR_AFTER_DISPATCH" if audit.get("dispatch_attempted") else "UNKNOWN"
            # No exception recovery can issue a second native command/fallback.
            finish({})
            raise
        return blocked(audit["reason"])
