"""Explicit opt-in five-step harness. Normal production imports no Phase 4B."""
from __future__ import annotations

from dataclasses import asdict, replace
from copy import deepcopy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import runpy
import sys
import uuid

from talkback_lib import A11yAdbClient
from talkback_lib.window_lifecycle import get_talkback_restart_event
from tb_runner import collection_flow
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
from tb_runner.plugin_context_contract import plugin_context_evidence, navigation_epoch_guard
from tb_runner.phase4a_inputs import production_action, runtime_input
from tb_runner.phase4a_planner import plan_shadow
from tb_runner.phase4b_authority import AuthorityEvidence, ExecutionBudget, execution_gate
from tb_runner.phase4b_execution import coherent_focus, controlled_collect, safe_scroll_container, geometry_in_viewport
from tb_runner.state_registry import StateRegistry
from tools.state_fingerprint_diagnostic import capture_observation
from tb_runner.action_provenance import build_action_chain, digest, action_chain_failures
from tb_runner.phase5c_hard_stop import Phase5CHardStopState, commit_audit_hard_stop

STAGES = (("home_main", "devices_main"), ("life_find_plugin", "device_smoke_sensor_plugin"),
          ("life_food_plugin", "life_family_care_plugin"))
SCENARIOS = tuple(s for stage in STAGES for s in stage)


def main(*, generalized=False, safe_navigation=False):
    if safe_navigation and (not generalized or os.environ.get("TB_PHASE5B_CONTROLLED") != "1"):
        raise ValueError("Safe navigation requires explicit bounded Phase 5B opt-in")
    safety_mode = os.environ.get("TB_PHASE5A_ACTION_SAFETY_MODE", "off")
    if safety_mode not in {"off", "shadow", "enforce"} or safety_mode != "off" and not generalized:
        raise ValueError("Phase 5A safety requires generalized traversal and an explicit valid mode")
    safety = None
    if safety_mode != "off":
        from tb_runner.phase5a_safety import SafetySession
        safety = SafetySession(safety_mode)
    if generalized:
        from tb_runner.phase4c_traversal import TraversalSession, SCENARIOS as selected_scenarios, BUDGETS
        from tb_runner.dynamic_context import (DestinationOwnership, rebind_execution,
                                               destination_ownership_rejection_diagnostic)
    else:
        selected_scenarios, BUDGETS = SCENARIOS, {s: 5 for s in SCENARIOS}
    if safe_navigation:
        from tb_runner.phase5b_navigation import SafeNavigationSession, SafetyBlocked, SCENARIOS as selected_scenarios, BUDGETS
        if safety_mode != "enforce":
            raise ValueError("Phase 5B requires Phase 5A enforcement")
    prefix = "TB_PHASE4C" if generalized else "TB_PHASE4B"
    file_prefix = "phase4c" if generalized else "phase4b"
    scenario = os.environ.get(prefix + "_SMOKE_SCENARIO", "")
    if os.environ.get(prefix + "_CONTROLLED") != "1" or scenario not in selected_scenarios:
        raise ValueError("Explicit Phase 4B opt-in and supported scenario required")
    out = Path(os.environ[prefix + "_SMOKE_OUT"]).resolve()
    config = json.loads(Path(os.environ["TB_RUNTIME_CONFIG_PATH"]).read_text(encoding="utf-8"))
    configured_max_steps = config.get("scenarios", {}).get(scenario, {}).get("max_steps")
    phase5c_full32 = os.environ.get("TB_PHASE5C_FULL32_ACCEPTANCE") == "1"
    controlled_action_budget = BUDGETS[scenario]
    if phase5c_full32:
        from tb_runner.phase5c_budget_policy import resolve_phase5c_budget_pair

        expected_production = os.environ.get("TB_PHASE5C_PRODUCTION_MAX_STEPS")
        expected_controlled = os.environ.get("TB_PHASE5C_CONTROLLED_ACTION_BUDGET")
        try:
            expected_production = int(expected_production) if expected_production is not None else None
            expected_controlled = int(expected_controlled) if expected_controlled is not None else None
        except ValueError as exc:
            raise ValueError("Phase 5C budget mapping environment values must be integers") from exc
        pair = resolve_phase5c_budget_pair(scenario, configured_max_steps, expected_controlled)
        if pair["production_max_steps"] != expected_production:
            raise ValueError("Phase 5C production max_steps changed after acceptance mapping")
        if pair["controlled_action_budget"] != BUDGETS[scenario]:
            raise ValueError("Phase 5C controlled action budget differs from the worker mapping")
        controlled_action_budget = pair["controlled_action_budget"]
    elif configured_max_steps != BUDGETS[scenario]:
        raise ValueError("Exactly five TOTAL production traversal steps required")
    serial = os.environ.get(prefix + "_SERIAL", "R3CX40QFDBP")
    run_dir = out / "run" / scenario
    run_dir.mkdir(parents=True, exist_ok=True)
    registry_path = out / (file_prefix + "_registry.json")
    registry = StateRegistry.load(registry_path) if registry_path.exists() else StateRegistry("phase4b-controlled-smoke")
    diagnostic = A11yAdbClient(start_monitor=False)
    budget = ExecutionBudget(max_actions=controlled_action_budget)
    session = TraversalSession(scenario, controlled_action_budget) if generalized else None
    active, pending = {}, {}
    original_loop = collection_flow._main_loop_phase
    original_step = collection_flow._apply_step_collection_phase
    original_persist = collection_flow._apply_row_persistence_phase
    original_reconcile = collection_flow._apply_focus_reconciliation
    original_terminal = collection_flow._apply_content_terminal_phase

    def save(name, value):
        with (out / name.replace("phase4b", file_prefix)).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
        registry.save(registry_path)

    navigation = SafeNavigationSession(scenario, save, safety_config=safety.config if safety else None) if safe_navigation else None

    def capture(kwargs):
        if active.get("hard_stop_state") is not None:
            active["hard_stop_state"].guard("diagnostic_observation")
        raw = capture_observation(diagnostic, kwargs["dev"], scenario_id=scenario,
                                  step=kwargs["step_idx"], scenario_run_id=active["run_id"])
        raw["phase3_entry_evidence"] = active["entry"]
        if generalized:
            raw["navigation_epoch"] = active["navigation_epoch"]
            raw["phase3_plugin_context_evidence"] = active["plugin_context"]
        context = resolve_phase3_context(raw)
        if generalized and active.get("destination_owner"):
            state = kwargs["state"]
            recovering = bool(getattr(state, "forced_local_tab_target_rid", "")
                or getattr(state, "forced_local_tab_target_action_label", "")
                or getattr(state, "post_realign_pending_steps", 0) or getattr(state, "stop_triggered", False))
            context = active["destination_owner"].assess(raw, recovery_active=recovering)
        snapshot = build_discovery_snapshot(raw, registry)
        value = runtime_input(snapshot, context["status"], scenario_id=scenario, client=kwargs["client"],
                              state=kwargs["state"], rows=kwargs["phase_ctx"].all_rows, capability=raw.get("capability"))
        value = replace(value, safety_blocked=(raw.get("overlay") or {}).get("observed") is not False)
        if session:
            value = session.prepare(raw, value)
        raw["snapshot_hash"] = snapshot.candidate_set_hash
        return raw, value, context

    def observed_loop(client, dev, phase_ctx):
        run_id = scenario + ":" + uuid.uuid4().hex
        hard_stop_state = Phase5CHardStopState(scenario=scenario, run_id=run_id) if phase5c_full32 else None
        if hard_stop_state is not None:
            client._phase5c_hard_stop_state = hard_stop_state
            # Preflight captures use a separate diagnostic client, so both
            # transports must share the same scenario hard-stop authority.
            diagnostic._phase5c_hard_stop_state = hard_stop_state
        raw = capture_observation(diagnostic, dev, scenario_id=scenario, scenario_run_id=run_id)
        entry = phase3_entry_evidence_from_main_loop(phase_ctx, run_id, raw["timestamp"])
        active.update(run_id=run_id, entry=entry, hard_stop_state=hard_stop_state)
        raw["phase3_entry_evidence"] = entry
        if generalized:
            epoch = run_id + ":production-entry"
            proof = plugin_context_evidence(entry, raw, deepcopy(getattr(client, "last_start_open_summary", {})), epoch)
            active.update(navigation_epoch=epoch, plugin_context=proof)
            raw.update(navigation_epoch=epoch, phase3_plugin_context_evidence=proof)
            entry_context = resolve_phase3_context(raw)
            if proof and (not navigation or navigation.plugin_lease_required(entry_context)):
                try:
                    active["destination_owner"] = DestinationOwnership(raw,
                        event_sink=lambda event: save("phase4c_destination_events.jsonl", event))
                except ValueError as exc:
                    save("phase4c_trusted_entry_rejections.jsonl",
                         destination_ownership_rejection_diagnostic(raw, entry_context, exc))
                    raise
                active["navigation_count"] = 0
        else:
            entry_context = resolve_phase3_context(raw)
        save("phase4b_observations.jsonl", dict(kind="ENTRY_TO_TRAVERSAL", scenario=scenario, raw=raw,
             snapshot=build_discovery_snapshot(raw, registry).to_dict(), context=entry_context))
        print("[PHASE4B_ENTRY] " + json.dumps(dict(scenario=scenario, entry="VERIFIED_MAIN_LOOP")), flush=True)
        def invalidate_context():
            active["navigation_count"] = active.get("navigation_count", 0) + 1
            active["navigation_epoch"] = run_id + ":navigation:" + str(active["navigation_count"])
        def navigation_observed(event):
            if active.get("destination_owner"):
                active["destination_owner"].navigation(event, active["navigation_epoch"])
        try:
            with navigation_epoch_guard(client, invalidate_context, navigation_observer=navigation_observed) if generalized else nullcontext():
                with navigation.firewall(client, dev) if navigation else nullcontext():
                    try:
                        return original_loop(client, dev, phase_ctx)
                    except Exception as exc:
                        if navigation and isinstance(exc, SafetyBlocked):
                            save("phase5b_failure.jsonl", dict(scenario=scenario, reason=str(exc),
                                step=(navigation.raw or {}).get("step"), raw=navigation.raw))
                            # Exit outside ordinary scenario crash/retry handling.
                            raise SystemExit(3) from exc
                        raise
        finally:
            if navigation:
                save("phase5b_session_summary.jsonl", dict(scenario=scenario, blocked_candidate_repeats=navigation.blocked_repeats,
                    blocked_scope_count=len(navigation.blocked), transport_blocks=len(navigation.command_blocks),
                    completed_navigation_probe=navigation.completed, attempt_credit=0, visit_credit=0))
            active.clear()

    def observed_step(**kwargs):
        if not active:
            return original_step(**kwargs)
        step, client, state = kwargs["step_idx"], kwargs["client"], kwargs["state"]
        if active.get("hard_stop_state") is not None:
            active["hard_stop_state"].guard(f"preflight:step:{step}")
        active["step_kwargs"] = kwargs
        raw, value, context = capture(kwargs)
        safety_before = None
        if safety:
            value, safety_before = safety.prepare(value, raw)
        active["before"] = raw, value
        recommendation = plan_shadow(value)
        # A separate immediate observation checks disappearance/semantic change.
        current_raw, current, current_context = capture(kwargs)
        safety_current = None
        if safety:
            current, safety_current = safety.prepare(current, current_raw)
        scope = all(raw.get(k) and raw.get(k) == current_raw.get(k) for k in ("package_name", "activity_name"))
        recovery = not (getattr(state, "forced_local_tab_target_rid", "")
                        or getattr(state, "forced_local_tab_target_action_label", "")
                        or getattr(state, "post_realign_pending_steps", 0)
                        or getattr(state, "stop_triggered", False))
        evidence = AuthorityEvidence(enabled=True, fresh=True, recovery_clear=recovery,
            lifecycle_clear=not bool(get_talkback_restart_event(client)),
            transport_clear=bool(client.check_helper_status(dev=kwargs["dev"])),
            focus_coherent=coherent_focus(current_raw), structural_scope_proven=scope,
            geometry_in_viewport=geometry_in_viewport(current_raw, recommendation),
            scroll_container_proven=safe_scroll_container(current_raw, recommendation))
        decision = execution_gate(value, recommendation, current, evidence,
                                  actions_used=budget.actions, degraded=budget.degraded, action_limit=controlled_action_budget)
        dynamic_context = None
        if generalized and active.get("destination_owner"):
            recommendation, decision, authority_transition = rebind_execution(value, recommendation, current, evidence,
                raw, current_raw, actions_used=budget.actions, degraded=budget.degraded, action_limit=controlled_action_budget)
            dynamic_context = dict(before=deepcopy(raw.get("destination_ownership")),
                current=deepcopy(current_raw.get("destination_ownership")),
                authority=authority_transition, events=deepcopy(active["destination_owner"].events))
            if authority_transition["rebound"]:
                active["before"] = current_raw, current
        if safety:
            decision = safety.guard(current, current_raw, recommendation, decision, safety_current)
            safety_current["before"] = safety_before
        if navigation:
            navigation.observe(current_raw, safety_current)
        chosen = recommendation.to_dict()
        audit = dict(scenario=scenario, step=step, state_id=chosen["planner_state_id"],
            context_status=current_context["status"], planner_action=chosen["recommended_action"],
            planner_target=chosen["recommended_target"], planner_rank=chosen["candidate_rank"],
            planner_reason_codes=chosen["reason_codes"], shadow_recommendation=chosen,
            execution_gate_result=decision.to_dict(), execution_gate_reason=decision.reason,
            planner_authorized=decision.allowed, planner_executed=False, planner_failed=False,
            actual_execution_mode=decision.mode, classification="PRODUCTION_ONLY",
            fallback_used=False, fallback_reason="",
            helper_request_id=None, helper_ack_result=None, attempt_credit=0, visit_credit=0,
            phase4b_visit_credit=0, production_visit_authority=True, scroll_result=None,
            actual_focus_before=current_raw.get("focus_node"), gate_evidence=asdict(evidence))
        if dynamic_context is not None:
            audit["dynamic_context"] = dynamic_context
        if safety_current is not None:
            audit["action_safety"] = safety_current
        pending[step] = audit
        save("phase4b_observations.jsonl", dict(kind="PRE_CONTROLLED_STEP", scenario=scenario, step=step,
            raw=raw, snapshot=value.snapshot.to_dict(), context=context, history=asdict(value.history),
            current_raw=current_raw, current_snapshot=current.snapshot.to_dict(), current_history=asdict(current.history),
            planner_flags={k: getattr(value, k) for k in ("scroll_exhausted", "scroll_blocked", "pending_transition", "last_movement", "focus_plateau", "safety_blocked")},
            current_flags={k: getattr(current, k) for k in ("scroll_exhausted", "scroll_blocked", "pending_transition", "last_movement", "focus_plateau", "safety_blocked")},
            gate_evidence=asdict(evidence), recommendation=chosen, gate=decision.to_dict(), dynamic_context=dynamic_context))
        collect = client.collect_focus_step
        collector_used = False
        def refresh():
            after_raw, after, after_context = capture(kwargs)
            return dict(raw=after_raw, snapshot=after.snapshot.to_dict(), context=after_context,
                        recommendation=plan_shadow(after).to_dict(), history=asdict(after.history))
        def controlled(**collect_kwargs):
            nonlocal collector_used
            collector_used = True
            return controlled_collect(client=client, dev=kwargs["dev"], scenario=scenario, step=step,
                raw=current_raw, recommendation=recommendation, decision=decision, budget=budget,
                collect=(lambda **kw: navigation.collect(collect, kw, audit, client)) if navigation else collect,
                collect_kwargs=collect_kwargs, refresh=refresh,
                output_dir=str(run_dir), audit=audit,
                audit_sink=lambda event: save("phase4b_action_audit.jsonl", event),
                focus_authorization=(lambda target, node: navigation.authorize_focus_target(
                    raw=current_raw, value=current, target=target, phase4_gate=decision,
                    step=step, dispatch_kind="PRIMARY")) if navigation else None)
        had_instance = "collect_focus_step" in client.__dict__
        prior_instance = client.__dict__.get("collect_focus_step")
        client.collect_focus_step = controlled
        try:
            row = original_step(**kwargs)
            if not collector_used:
                # Existing forced local-tab/recovery paths can collect a row
                # without calling collect_focus_step. Preserve that path and
                # audit its production authority; never require a planner hook.
                budget.fallback_count += 1
                audit.update(actual_execution_mode="FALLBACK_PRODUCTION", classification="PRODUCTION_ONLY",
                    fallback_used=True, fallback_reason=decision.reason if not decision.allowed else "PRODUCTION_RECOVERY_OWNS_STEP",
                    production_fallback_action="PRODUCTION_RECOVERY")
                save("phase4b_action_audit.jsonl", dict(event="PRODUCTION_RECOVERY_BYPASS", **audit))
            return row
        finally:
            if had_instance:
                client.collect_focus_step = prior_instance
            else:
                del client.collect_focus_step

    def reconciled(**kwargs):
        row = kwargs["row"]
        if row.get("phase4b_before_row"):
            kwargs = {**kwargs, "previous_row": row["phase4b_before_row"]}
        result = original_reconcile(**kwargs)
        if generalized:
            audit = pending.get(kwargs["row"].get("step_index"))
            if audit is not None:
                audit["primary_production_outcome"] = deepcopy({k: kwargs["row"].get(k) for k in (
                    "actual_focus_node", "get_focus_req_id", "move_result", "focus_reconciliation_evidence",
                    "focus_transition_status", "visit_record_status")})
        return result

    def observed_terminal(client, dev, state, row, phase_ctx, step_idx, stop, reason, pending=False):
        stop, reason = original_terminal(client, dev, state, row, phase_ctx, step_idx, stop, reason, pending)
        if session and active.get("step_kwargs"):
            after_raw, after, after_context = capture(active["step_kwargs"])
            active["after"] = after_raw, after
            stop, reason = session.protect_stop(stop, reason, after)
        return stop, reason

    def observed_persist(**kwargs):
        audit = pending.get(kwargs["step_idx"])
        if generalized and audit is not None:
            if audit.get("action_safety") is not None:
                audit["action_safety"]["final_outcome"] = dict(
                    planner_executed=audit.get("planner_executed"), fallback_used=audit.get("fallback_used"),
                    helper_request_id=audit.get("helper_request_id"),
                    phase4_execution_gate=audit.get("execution_gate_result"),
                    visit_record_status=kwargs["row"].get("visit_record_status"))
            if audit.get("dynamic_context") and active.get("destination_owner"):
                audit["dynamic_context"]["events"] = deepcopy(active["destination_owner"].events)
                audit["dynamic_context"]["after"] = deepcopy((active.get("after") or active["before"])[0].get("destination_ownership"))
            runtime = getattr(active["step_kwargs"]["client"], "evidence_runtime", None)
            events = runtime.events_for_step(kwargs["step_idx"]) if runtime else ()
            chain = build_action_chain(audit, kwargs["row"], events)
            # Only append provenance fields. Existing outcomes still drive every
            # budget/session/ledger decision below, including replaced-row gaps.
            save("phase4c_step_action_evidence.jsonl", chain)
            kwargs["row"]["step_action_id"] = chain["step_action_id"]
            kwargs["row"]["step_action_provenance"] = dict(
                schema=chain["schema"], step_action_id=chain["step_action_id"],
                evidence_file="phase4c_step_action_evidence.jsonl", sha256=digest(chain))
            failures = action_chain_failures(chain, audit)
            audit.update(action_audit_chain=chain, audit_chain_complete=not failures)
            if failures and phase5c_full32:
                hard_stop_state = active.get("hard_stop_state")
                if hard_stop_state is None:
                    raise RuntimeError("Phase 5C audit rejection has no authoritative stop state")
                record = commit_audit_hard_stop(
                    controller=hard_stop_state,
                    client=active["step_kwargs"]["client"],
                    state=kwargs["state"],
                    row=kwargs["row"],
                    step=kwargs["step_idx"],
                    reasons=failures,
                    action_id=chain["step_action_id"],
                )
                kwargs["stop"] = True
                save("phase5c_hard_stops.jsonl", record)
                audit["phase5c_hard_stop"] = record
        result = original_persist(**kwargs)
        audit = pending.pop(kwargs["step_idx"], None)
        if audit is not None:
            row = kwargs["row"]
            action, target = production_action(row, scenario)
            reconciliation = row.get("focus_reconciliation_evidence") or "{}"
            if isinstance(reconciliation, str):
                reconciliation = json.loads(reconciliation)
            audit.update(production_action=action, production_target=target,
                actual_focus_after=row.get("actual_focus_node"), focus_reconciliation=reconciliation,
                visit_credit=int(row.get("visit_record_status") == "RECORDED"),
                visit_record_status=row.get("visit_record_status"),
                focus_transition_status=row.get("focus_transition_status"),
                progress=row.get("progress_status"),
                termination_status=row.get("scenario_terminal_status"), termination_reason=row.get("stop_reason"),
                loop_budget=asdict(budget), production_row=deepcopy(row))
            if audit["planner_executed"]:
                budget.production_outcome(new_visit=bool(audit["visit_credit"]))
                audit["loop_budget"] = asdict(budget)
            if session:
                before_raw, before_value = active["before"]
                after_raw, after_value = active.get("after", active["before"])
                session.observe(audit, before_raw, before_value, after_raw, after_value, budget)
                audit["loop_budget"] = asdict(budget)
            # Audit credits are copies of production outcomes, not ledger writes.
            save("phase4b_execution_trace.jsonl", audit)
            print("[PHASE4B_STEP] " + json.dumps({k: audit[k] for k in ("scenario", "step", "classification", "planner_executed", "visit_credit", "fallback_used")}), flush=True)
        if navigation and kwargs["step_idx"] == 5 and not (
                active.get("hard_stop_state") is not None and active["hard_stop_state"].latched):
            def nav_capture(observe_owner=True):
                if observe_owner:
                    raw, value, context = capture(active["step_kwargs"])
                    state = active["step_kwargs"]["state"]
                    raw["phase5b_recovery_clear"] = not (getattr(state,"forced_local_tab_target_rid","")
                        or getattr(state,"forced_local_tab_target_action_label","")
                        or getattr(state,"post_realign_pending_steps",0) or getattr(state,"stop_triggered",False))
                    return raw, value, context
                raw = capture_observation(diagnostic, active["step_kwargs"]["dev"], scenario_id=scenario,
                    step=kwargs["step_idx"], scenario_run_id=active["run_id"])
                raw["phase3_entry_evidence"] = active["entry"]
                raw["navigation_epoch"] = active["navigation_epoch"]
                snapshot = build_discovery_snapshot(raw, registry)
                return raw, replace(active["before"][1], snapshot=snapshot), resolve_phase3_context(raw)
            navigation.roundtrip(client=active["step_kwargs"]["client"], dev=active["step_kwargs"]["dev"],
                capture=nav_capture, step=kwargs["step_idx"])
        return result

    collection_flow._main_loop_phase = observed_loop
    collection_flow._apply_step_collection_phase = observed_step
    collection_flow._apply_row_persistence_phase = observed_persist
    collection_flow._apply_focus_reconciliation = reconciled
    if session:
        collection_flow._apply_content_terminal_phase = observed_terminal
    previous_argv = sys.argv
    sys.argv = ["script_test.py", "--serial", serial, "--output-dir", str(run_dir),
                "--language-mode", "current", "--launch-mode", "warm", "--scenario", scenario]
    try:
        runpy.run_path("script_test.py", run_name="__main__")
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    finally:
        collection_flow._main_loop_phase = original_loop
        collection_flow._apply_step_collection_phase = original_step
        collection_flow._apply_row_persistence_phase = original_persist
        collection_flow._apply_focus_reconciliation = original_reconcile
        collection_flow._apply_content_terminal_phase = original_terminal
        sys.argv = previous_argv
        registry.save(registry_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
