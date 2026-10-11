"""Explicit opt-in five-step harness. Normal production imports no Phase 4B."""
from __future__ import annotations

from dataclasses import asdict, replace
from copy import deepcopy
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
from tb_runner.phase4a_inputs import production_action, runtime_input
from tb_runner.phase4a_planner import plan_shadow
from tb_runner.phase4b_authority import AuthorityEvidence, ExecutionBudget, execution_gate
from tb_runner.phase4b_execution import coherent_focus, controlled_collect, safe_scroll_container, geometry_in_viewport
from tb_runner.state_registry import StateRegistry
from tools.state_fingerprint_diagnostic import capture_observation

STAGES = (("home_main", "devices_main"), ("life_find_plugin", "device_smoke_sensor_plugin"),
          ("life_food_plugin", "life_family_care_plugin"))
SCENARIOS = tuple(s for stage in STAGES for s in stage)


def main():
    scenario = os.environ.get("TB_PHASE4B_SMOKE_SCENARIO", "")
    if os.environ.get("TB_PHASE4B_CONTROLLED") != "1" or scenario not in SCENARIOS:
        raise ValueError("Explicit Phase 4B opt-in and supported scenario required")
    out = Path(os.environ["TB_PHASE4B_SMOKE_OUT"]).resolve()
    config = json.loads(Path(os.environ["TB_RUNTIME_CONFIG_PATH"]).read_text(encoding="utf-8"))
    if config.get("scenarios", {}).get(scenario, {}).get("max_steps") != 5:
        raise ValueError("Exactly five TOTAL production traversal steps required")
    serial = os.environ.get("TB_PHASE4B_SERIAL", "R3CX40QFDBP")
    run_dir = out / "run" / scenario
    run_dir.mkdir(parents=True, exist_ok=True)
    registry_path = out / "phase4b_registry.json"
    registry = StateRegistry.load(registry_path) if registry_path.exists() else StateRegistry("phase4b-controlled-smoke")
    diagnostic = A11yAdbClient(start_monitor=False)
    budget = ExecutionBudget()
    active, pending = {}, {}
    original_loop = collection_flow._main_loop_phase
    original_step = collection_flow._apply_step_collection_phase
    original_persist = collection_flow._apply_row_persistence_phase
    original_reconcile = collection_flow._apply_focus_reconciliation

    def save(name, value):
        with (out / name).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
        registry.save(registry_path)

    def capture(kwargs):
        raw = capture_observation(diagnostic, kwargs["dev"], scenario_id=scenario,
                                  step=kwargs["step_idx"], scenario_run_id=active["run_id"])
        raw["phase3_entry_evidence"] = active["entry"]
        snapshot = build_discovery_snapshot(raw, registry)
        context = resolve_phase3_context(raw)
        value = runtime_input(snapshot, context["status"], scenario_id=scenario, client=kwargs["client"],
                              state=kwargs["state"], rows=kwargs["phase_ctx"].all_rows, capability=raw.get("capability"))
        value = replace(value, safety_blocked=(raw.get("overlay") or {}).get("observed") is not False)
        raw["snapshot_hash"] = snapshot.candidate_set_hash
        return raw, value, context

    def observed_loop(client, dev, phase_ctx):
        run_id = scenario + ":" + uuid.uuid4().hex
        raw = capture_observation(diagnostic, dev, scenario_id=scenario, scenario_run_id=run_id)
        entry = phase3_entry_evidence_from_main_loop(phase_ctx, run_id, raw["timestamp"])
        active.update(run_id=run_id, entry=entry)
        raw["phase3_entry_evidence"] = entry
        save("phase4b_observations.jsonl", dict(kind="ENTRY_TO_TRAVERSAL", scenario=scenario, raw=raw,
             snapshot=build_discovery_snapshot(raw, registry).to_dict(), context=resolve_phase3_context(raw)))
        print("[PHASE4B_ENTRY] " + json.dumps(dict(scenario=scenario, entry="VERIFIED_MAIN_LOOP")), flush=True)
        try:
            return original_loop(client, dev, phase_ctx)
        finally:
            active.clear()

    def observed_step(**kwargs):
        if not active:
            return original_step(**kwargs)
        step, client, state = kwargs["step_idx"], kwargs["client"], kwargs["state"]
        raw, value, context = capture(kwargs)
        recommendation = plan_shadow(value)
        # A separate immediate observation checks disappearance/semantic change.
        current_raw, current, current_context = capture(kwargs)
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
                                  actions_used=budget.actions, degraded=budget.degraded)
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
        pending[step] = audit
        save("phase4b_observations.jsonl", dict(kind="PRE_CONTROLLED_STEP", scenario=scenario, step=step,
            raw=raw, snapshot=value.snapshot.to_dict(), context=context, history=asdict(value.history),
            current_raw=current_raw, current_snapshot=current.snapshot.to_dict(), current_history=asdict(current.history),
            planner_flags={k: getattr(value, k) for k in ("scroll_exhausted", "scroll_blocked", "pending_transition", "last_movement", "focus_plateau", "safety_blocked")},
            current_flags={k: getattr(current, k) for k in ("scroll_exhausted", "scroll_blocked", "pending_transition", "last_movement", "focus_plateau", "safety_blocked")},
            gate_evidence=asdict(evidence), recommendation=chosen, gate=decision.to_dict()))
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
                collect=collect, collect_kwargs=collect_kwargs, refresh=refresh,
                output_dir=str(run_dir), audit=audit,
                audit_sink=lambda event: save("phase4b_action_audit.jsonl", event))
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
        return original_reconcile(**kwargs)

    def observed_persist(**kwargs):
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
            # Audit credits are copies of production outcomes, not ledger writes.
            save("phase4b_execution_trace.jsonl", audit)
            print("[PHASE4B_STEP] " + json.dumps({k: audit[k] for k in ("scenario", "step", "classification", "planner_executed", "visit_credit", "fallback_used")}), flush=True)
        return result

    collection_flow._main_loop_phase = observed_loop
    collection_flow._apply_step_collection_phase = observed_step
    collection_flow._apply_row_persistence_phase = observed_persist
    collection_flow._apply_focus_reconciliation = reconciled
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
        sys.argv = previous_argv
        registry.save(registry_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
