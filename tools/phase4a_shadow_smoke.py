"""Explicit bounded smoke harness; production receives no planner decisions.

Run a single scenario after the supervised clean-start precondition. The
supervisor supplies a five-step runtime configuration and the lifecycle monitor.
All wrapper replacements are restored; imported production modules are unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import runpy
import sys
import uuid

from talkback_lib import A11yAdbClient
from tb_runner import collection_flow
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
from tb_runner.phase4a_inputs import production_action, runtime_input
from tb_runner.phase4a_planner import compare_production, plan_shadow
from tb_runner.state_registry import StateRegistry
from tools.state_fingerprint_diagnostic import capture_observation

SCENARIOS = ("home_main", "devices_main", "life_food_plugin", "life_family_care_plugin",
             "life_find_plugin", "device_smoke_sensor_plugin")


def main() -> int:
    scenario = os.environ.get("TB_PHASE4A_SMOKE_SCENARIO", "")
    out_value = os.environ.get("TB_PHASE4A_SMOKE_OUT", "")
    serial = os.environ.get("TB_PHASE4A_SERIAL", "R3CX40QFDBP")
    if scenario not in SCENARIOS or not out_value:
        raise ValueError("Explicit supported scenario and output root required")
    config = json.loads(Path(os.environ["TB_RUNTIME_CONFIG_PATH"]).read_text(encoding="utf-8"))
    if config.get("scenarios", {}).get(scenario, {}).get("max_steps") != 5:
        raise ValueError("Bounded shadow smoke requires exactly a five-step override")
    out = Path(out_value).resolve()
    run_dir = out / "run" / scenario
    run_dir.mkdir(parents=True, exist_ok=True)
    registry_path = out / "phase4a_registry.json"
    registry = StateRegistry.load(registry_path) if registry_path.exists() else StateRegistry("phase4a-shadow-smoke")
    diagnostic = A11yAdbClient(start_monitor=False)
    original_loop = collection_flow._main_loop_phase
    original_step = collection_flow._apply_step_collection_phase
    original_persist = collection_flow._apply_row_persistence_phase
    active, pending = {}, {}

    def save(name, row):
        with (out / name).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        registry.save(registry_path)

    def observed_loop(client, dev, phase_ctx):
        run_id = scenario + ":" + uuid.uuid4().hex
        raw = capture_observation(diagnostic, dev, scenario_id=scenario, scenario_run_id=run_id)
        entry = phase3_entry_evidence_from_main_loop(phase_ctx, run_id, raw["timestamp"])
        raw["phase3_entry_evidence"] = entry
        snapshot = build_discovery_snapshot(raw, registry)
        context = resolve_phase3_context(raw)
        active.update(run_id=run_id, entry=entry, phase_ctx=phase_ctx)
        save("phase4a_observations.jsonl", dict(kind="ENTRY_TO_TRAVERSAL", scenario=scenario, raw=raw,
                                              snapshot=snapshot.to_dict(), context=context))
        print("[PHASE4A_SHADOW] " + json.dumps(dict(scenario=scenario, entry="VERIFIED_MAIN_LOOP",
                                                   context_status=context["status"])), flush=True)
        try:
            return original_loop(client, dev, phase_ctx)
        finally:
            active.clear()

    def observed_step(**kwargs):
        if not active:
            return original_step(**kwargs)
        step = kwargs["step_idx"]
        raw = capture_observation(diagnostic, kwargs["dev"], scenario_id=scenario, step=step,
                                  scenario_run_id=active["run_id"])
        raw["phase3_entry_evidence"] = active["entry"]
        snapshot = build_discovery_snapshot(raw, registry)
        context = resolve_phase3_context(raw)
        value = runtime_input(snapshot, context["status"], scenario_id=scenario, client=kwargs["client"],
                              state=kwargs["state"], rows=kwargs["phase_ctx"].all_rows,
                              capability=raw.get("capability"))
        value = replace(value, safety_blocked=(raw.get("overlay") or {}).get("observed") is True)
        recommendation = plan_shadow(value)
        pending[step] = recommendation
        save("phase4a_observations.jsonl", dict(kind="PRE_PRODUCTION_STEP", scenario=scenario, step=step,
                                              raw=raw, snapshot=snapshot.to_dict(), context=context,
                                              history=asdict(value.history), planner_flags=dict(
                                                  scroll_exhausted=value.scroll_exhausted, scroll_blocked=value.scroll_blocked,
                                                  pending_transition=value.pending_transition, last_movement=value.last_movement,
                                                  focus_plateau=value.focus_plateau, safety_blocked=value.safety_blocked),
                                              recommendation=recommendation.to_dict()))
        # The returned recommendation is never supplied to original_step.
        return original_step(**kwargs)

    def observed_persist(**kwargs):
        result = original_persist(**kwargs)
        step = kwargs["step_idx"]
        recommendation = pending.pop(step, None)
        if recommendation is not None:
            row = kwargs["row"]
            action, target = production_action(row, scenario)
            decision = recommendation.to_dict()
            comparison = compare_production(recommendation, action, target)
            trace = dict(scenario=scenario, step=step, state_id=decision["planner_state_id"],
                         context_status=decision["context_status"], **comparison,
                         shadow_rank=decision["candidate_rank"], shadow_reason_codes=decision["reason_codes"],
                         candidate_count=decision["candidate_count"], eligible_count=decision["eligible_candidate_count"],
                         never_attempted_count=decision["never_attempted_count"],
                         attempted_unvisited_count=decision["attempted_unvisited_count"],
                         visited_count=decision["visited_count"], scroll_opportunity=decision["scroll_opportunity"],
                         recommendation=decision, production_result={k: row.get(k) for k in (
                             "target_focus_status", "target_focus_attempt_id", "focus_transition_status",
                             "visit_record_status", "reconciled_visit_instance_id", "actual_focus_instance_id")},
                         action_executed_by_planner=False, production_visit_authority=False, visit_credit=0)
            save("phase4a_shadow_trace.jsonl", trace)
            print("[PHASE4A_SHADOW_STEP] " + json.dumps({k: trace[k] for k in (
                "scenario", "step", "shadow_action", "production_action", "match_classification")}), flush=True)
        return result

    collection_flow._main_loop_phase = observed_loop
    collection_flow._apply_step_collection_phase = observed_step
    collection_flow._apply_row_persistence_phase = observed_persist
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
        sys.argv = previous_argv
        registry.save(registry_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
