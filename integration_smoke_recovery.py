"""Run one 5-step production scenario with observational Phase 3 hooks."""

from __future__ import annotations

import json
import os
import runpy
import sys
import uuid
from pathlib import Path

from talkback_lib import A11yAdbClient
from tb_runner import collection_flow
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
from tb_runner.phase3_focus import normalize_phase3_focus_transition
from tb_runner.state_registry import StateRegistry
from tb_runner.transition_observation import TransitionObserver
from tools.state_fingerprint_diagnostic import capture_observation


SERIAL = "R3CX40QFDBP"
SCENARIOS = (
    "home_main",
    "devices_main",
    "life_food_plugin",
    "life_family_care_plugin",
    "life_find_plugin",
    "device_smoke_sensor_plugin",
)


def main() -> int:
    scenario = os.environ.get("TB_PHASE3_SMOKE_SCENARIO", "").strip()
    out_value = os.environ.get("TB_PHASE3_SMOKE_OUT", "").strip()
    if scenario not in SCENARIOS or not out_value:
        print("[PHASE3_SMOKE] invalid scenario or output root", flush=True)
        return 2

    out = Path(out_value).resolve()
    run_dir = out / "run" / scenario
    run_dir.mkdir(parents=True, exist_ok=True)
    registry_path = out / "phase3_registry.json"
    observations_path = out / "phase3_observations.jsonl"
    if registry_path.is_file():
        registry = StateRegistry.load(registry_path)
    else:
        registry = StateRegistry("phase3-recovery-smoke")
    observer = TransitionObserver(registry)
    diagnostic = A11yAdbClient(start_monitor=False)
    original_loop = collection_flow._main_loop_phase
    original_move = A11yAdbClient.move_focus_smart
    active: dict[str, object] = {}
    move_counts: dict[str, int] = {}

    def save_row(row: dict) -> None:
        with observations_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
        registry.save(registry_path)

    def observed_main_loop(client, device, phase_context):
        scenario_id = str(phase_context.tab_cfg["scenario_id"])
        run_id = scenario_id + ":" + uuid.uuid4().hex
        raw = capture_observation(
            diagnostic, device, scenario_id=scenario_id, scenario_run_id=run_id
        )
        entry_evidence = phase3_entry_evidence_from_main_loop(
            phase_context, run_id, raw["timestamp"]
        )
        raw["phase3_entry_evidence"] = entry_evidence
        active.update(scenario=scenario_id, run_id=run_id, entry_evidence=entry_evidence)
        snapshot = build_discovery_snapshot(raw, registry)
        context = resolve_phase3_context(raw)
        save_row(
            dict(
                kind="ENTRY_TO_TRAVERSAL",
                scenario=scenario_id,
                scenario_run_id=run_id,
                entry_evidence=entry_evidence,
                context=context,
                raw=raw,
                snapshot=snapshot.to_dict(),
                mode="SHADOW_OBSERVATIONAL",
            )
        )
        print(
            "[PHASE3_SMOKE] "
            + json.dumps(
                dict(
                    scenario=scenario_id,
                    entry="VERIFIED_MAIN_LOOP",
                    context_status=context["status"],
                    state_id=snapshot.state_id,
                    candidates=len(snapshot.candidates),
                )
            ),
            flush=True,
        )
        try:
            return original_loop(client, device, phase_context)
        finally:
            active.clear()
            registry.save(registry_path)

    def observed_move(client, dev=None, direction="next"):
        scenario_id = active.get("scenario")
        if not scenario_id or direction != "next":
            return original_move(client, dev, direction)
        index = move_counts.get(str(scenario_id), 0)
        move_counts[str(scenario_id)] = index + 1
        run_id = str(active["run_id"])
        entry_evidence = active["entry_evidence"]
        before = capture_observation(
            diagnostic,
            dev,
            scenario_id=str(scenario_id),
            step=index,
            scenario_run_id=run_id,
        )
        before["phase3_entry_evidence"] = entry_evidence
        prepared = observer.prepare(
            before,
            dict(
                occurrence_id=f"{scenario_id}:smart_next:{index}",
                producer="existing_production_smoke",
                action_kind="FOCUS_NEXT",
                target_identity={"operation": "HELPER_SMART_NEXT_UNTARGETED"},
            ),
        )
        acknowledgement = original_move(client, dev, direction)
        after = capture_observation(
            diagnostic,
            dev,
            scenario_id=str(scenario_id),
            step=index + 1,
            scenario_run_id=run_id,
        )
        after["phase3_entry_evidence"] = entry_evidence
        raw_ack = acknowledgement.get("raw") if isinstance(acknowledgement, dict) else None
        request_id = raw_ack.get("reqId") if isinstance(raw_ack, dict) else None
        focus = normalize_phase3_focus_transition(
            before,
            after,
            acknowledgement,
            expected_request_id=request_id,
            scenario_run_id=run_id,
        )
        focus_summary = {
            key: value
            for key, value in focus.items()
            if key
            not in {
                "before_observation",
                "after_observation",
                "before_actual_focus_node",
                "after_actual_focus_node",
            }
        }
        transition = observer.complete(
            prepared,
            focus["after_observation"],
            command_ack=acknowledgement,
            action_evidence={
                "producer": "existing_production_smoke",
                "request_correlation": focus["request_correlation"],
                "phase3_focus_observation": focus_summary,
            },
        )
        save_row(
            dict(
                kind="CONTROLLED_PRODUCTION_SMART_NEXT",
                scenario=scenario_id,
                before_raw=before,
                after_raw=after,
                scenario_run_id=run_id,
                focus_observation=focus_summary,
                action=prepared.action.to_dict(),
                command_ack=acknowledgement,
                transition=transition.to_dict(),
                mode="SHADOW_OBSERVATIONAL",
            )
        )
        return acknowledgement

    collection_flow._main_loop_phase = observed_main_loop
    A11yAdbClient.move_focus_smart = observed_move

    argv = [
        "script_test.py",
        "--serial",
        SERIAL,
        "--output-dir",
        str(run_dir),
        "--language-mode",
        "current",
        "--launch-mode",
        "warm",
        "--scenario",
        scenario,
    ]
    sys.argv = argv
    print(f"[PHASE3_SMOKE] scenario_start={scenario} max_steps=5", flush=True)
    try:
        runpy.run_path("script_test.py", run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        print(f"[PHASE3_SMOKE] runner_exit_code={code}", flush=True)
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
