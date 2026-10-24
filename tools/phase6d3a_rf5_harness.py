"""Bounded RF5 live validation launcher. ACTIVE is scoped to its child process."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_SCENARIO = "device_smoke_sensor_plugin"
SUPPORTED_SCENARIOS = (DEFAULT_SCENARIO, "device_air_purifier_plugin")
MAIN_STEP_BUDGET = 7
RF5_CONTROLLED_ACTION_BUDGET = 10
REDIRECT_ATTEMPT_BUDGET = 2
NATIVE_REDIRECT_DISPATCH_CAP = 1


def _scenario_config(scenario_id: str = DEFAULT_SCENARIO):
    from tb_runner.scenario_config import TAB_CONFIGS

    if scenario_id not in SUPPORTED_SCENARIOS:
        raise ValueError(f"Unsupported RF5 scenario: {scenario_id}")
    matches = [item for item in TAB_CONFIGS if item.get("scenario_id") == scenario_id]
    if len(matches) != 1:
        raise RuntimeError(f"RF5 scenario configuration is not unique: {scenario_id}")
    scenario = matches[0]
    if (scenario.get("scenario_type") != "content"
            or scenario.get("entry_type") != "card"
            or scenario.get("screen_context_mode") != "new_screen"):
        raise RuntimeError(f"RF5 scenario is outside the approved plugin-content scope: {scenario_id}")
    entry = scenario.get("pre_navigation")
    if not isinstance(entry, list) or not any(
            isinstance(item, dict)
            and item.get("action") == "enter_device_card_plugin"
            and str(item.get("target") or "").strip()
            and isinstance(item.get("target_stable_labels"), list)
            and item.get("target_stable_labels")
            for item in entry):
        raise RuntimeError(f"RF5 scenario has no approved automatic device-card entry: {scenario_id}")
    return scenario


def offline_gate(output_dir: Path, scenario_id: str = DEFAULT_SCENARIO) -> dict:
    from tb_runner.exploration_progress import ExplorationPolicy
    from tb_runner.exploration_redirect import RedirectBudget, redirect_mode_from_environment
    from tb_runner.frontier_shadow import FrontierShadowRuntime
    from tb_runner.exploration_shadow import ExplorationShadowRuntime
    from tb_runner.phase4c_traversal import BUDGETS
    from tb_runner.run_spec import RunSpec
    from tb_runner.scenario_config import canonical_full_scenario_ids

    policy = ExplorationPolicy()
    threshold = max(policy.state_plateau_threshold, policy.run_plateau_threshold)
    # Entry/anchor observation occurs before the main loop. A progressing main
    # step, four plateau results, one decision consumer/positive opportunity,
    # and one post-dispatch stale-decision check require seven main steps.
    calculated_minimum = 1 + threshold + 1 + 1
    if threshold != 4 or calculated_minimum != MAIN_STEP_BUDGET:
        raise RuntimeError("RF5 main-step allowance no longer matches current production flow")
    if scenario_id not in SUPPORTED_SCENARIOS:
        raise ValueError(f"Unsupported RF5 scenario: {scenario_id}")
    scenario = _scenario_config(scenario_id)
    if RunSpec().entry_mode != "AUTOMATED":
        raise RuntimeError("Runner no longer defaults to AUTOMATED entry")
    if scenario_id not in canonical_full_scenario_ids():
        raise RuntimeError(f"RF5 scenario is absent from the production scenario registry: {scenario_id}")
    if BUDGETS.get(scenario_id, RF5_CONTROLLED_ACTION_BUDGET) < NATIVE_REDIRECT_DISPATCH_CAP:
        raise RuntimeError(f"Existing controlled-focus budget cannot support {scenario_id}")

    base_path = ROOT / "config" / "runtime_config.json"
    with base_path.open("r", encoding="utf-8") as stream:
        config = json.load(stream)
    scenarios = config.setdefault("scenarios", {})
    for key, value in scenarios.items():
        if isinstance(value, dict):
            value["enabled"] = key == scenario_id
    selected = scenarios.setdefault(scenario_id, {})
    selected["enabled"] = True
    selected["max_steps"] = MAIN_STEP_BUDGET
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = output_dir / "runtime_config.json"
    runtime_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generated = json.loads(runtime_path.read_text(encoding="utf-8"))
    if generated["scenarios"][scenario_id]["max_steps"] != MAIN_STEP_BUDGET:
        raise RuntimeError("Generated RF5 runtime configuration failed round-trip validation")
    if any(value.get("enabled") is True for key, value in generated["scenarios"].items()
           if isinstance(value, dict) and key != scenario_id):
        raise RuntimeError("RF5 runtime configuration enabled an unselected scenario")

    valid_hint = {"state_id": "state", "frontier_id": "frontier",
                  "run_last_meaningful_progress_step": 1}
    dispatch_budget = RedirectBudget(max_per_run=NATIVE_REDIRECT_DISPATCH_CAP,
                                     max_per_state=NATIVE_REDIRECT_DISPATCH_CAP,
                                     max_per_condition=1)
    if not dispatch_budget.available(valid_hint)[0]:
        raise RuntimeError("Native redirect budget is unavailable before dispatch")
    if not dispatch_budget.dispatch_attempt(valid_hint)[0]:
        raise RuntimeError("Native redirect cap cannot admit its one bounded dispatch")
    if dispatch_budget.available(valid_hint)[0]:
        raise RuntimeError("Native redirect cap failed to block a second dispatch")

    writers = (FrontierShadowRuntime.write, ExplorationShadowRuntime.write)
    if not all(callable(writer) for writer in writers):
        raise RuntimeError("Existing runtime artifact writers are unavailable")
    if redirect_mode_from_environment({}) != "OFF":
        raise RuntimeError("Redirect mode default is not OFF")

    source = (ROOT / "tools" / "phase4b_controlled_smoke.py").read_text(encoding="utf-8")
    required_harness_hooks = (
        "_rf5_active_evaluation_count(controller)",
        "active_evaluation_eligible = bool(",
        "if not active_evaluation_eligible:",
        "controller.budget.max_per_run = 1",
        "rf5_save_runtime(client, phase_ctx.output_path",
        "MAX_CRASH_RETRY_ATTEMPTS = 0",
        "authorize_focus_target(",
    )
    missing = [needle for needle in required_harness_hooks if needle not in source]
    if missing:
        raise RuntimeError("RF5 harness bounds/evidence hooks missing: " + ", ".join(missing))
    if "_phase6_redirect_proofs[" in source:
        raise RuntimeError("RF5 harness must not synthesize production proof records")

    parent_mode = os.environ.get("TB_EXPLORATION_REDIRECT_MODE")
    child_env = os.environ.copy()
    child_env.update({
        "TB_EXPLORATION_REDIRECT_MODE": "ACTIVE",
        "TB_STATE_GRAPH_MODE": "SHADOW",
        "TB_RUNTIME_CONFIG_PATH": str(runtime_path),
        "TB_PHASE6D3A_RF5_MAIN_STEP_BUDGET": str(MAIN_STEP_BUDGET),
        "TB_PHASE6D3A_RF5_HARNESS": "1",
        "TB_PHASE4C_CONTROLLED": "1",
        "TB_PHASE4C_SMOKE_SCENARIO": scenario_id,
        "TB_PHASE4C_SMOKE_OUT": str(output_dir),
    })
    if parent_mode != os.environ.get("TB_EXPLORATION_REDIRECT_MODE"):
        raise RuntimeError("Parent process environment changed while preparing child environment")
    if os.environ.get("TB_EXPLORATION_REDIRECT_MODE") == "ACTIVE":
        raise RuntimeError("ACTIVE is already enabled in the launcher process")

    return {
        "gate": "PASS",
        "scenario": scenario_id,
        "entry_mode": "AUTOMATED",
        "entry_route": "production scenario pre_navigation -> enter_device_card_plugin -> existing anchor/context verification",
        "main_step_budget": MAIN_STEP_BUDGET,
        "plateau_threshold": threshold,
        "redirect_attempt_budget": REDIRECT_ATTEMPT_BUDGET,
        "native_redirect_dispatch_cap": NATIVE_REDIRECT_DISPATCH_CAP,
        "controlled_action_budget": BUDGETS.get(scenario_id, RF5_CONTROLLED_ACTION_BUDGET),
        "artifact_writers": ["FrontierShadowRuntime.write", "ExplorationShadowRuntime.write"],
        "default_redirect_mode": "OFF",
        "active_scope": "child process only",
        "production_policy_changed": False,
        "runtime_config_path": str(runtime_path),
        "child_environment": child_env,
    }


def _child_main() -> int:
    scenario_id = os.environ.get("TB_PHASE4C_SMOKE_SCENARIO")
    if scenario_id not in SUPPORTED_SCENARIOS:
        raise ValueError(f"Unsupported RF5 scenario: {scenario_id}")
    required = {
        "TB_EXPLORATION_REDIRECT_MODE": "ACTIVE",
        "TB_STATE_GRAPH_MODE": "SHADOW",
        "TB_PHASE6D3A_RF5_HARNESS": "1",
        "TB_PHASE4C_CONTROLLED": "1",
        "TB_PHASE4C_SMOKE_SCENARIO": scenario_id,
    }
    wrong = [key for key, value in required.items() if os.environ.get(key) != value]
    if wrong:
        raise RuntimeError("RF5 child process lacks required bounded flags: " + ", ".join(wrong))
    from tools.phase4b_controlled_smoke import main

    return int(main(generalized=True, safe_navigation=False, rf5_harness=True) or 0)


def _tail(path: Path, offset: int) -> tuple[int, list[str]]:
    if not path.exists():
        return offset, []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        stream.seek(offset)
        text = stream.read()
        return stream.tell(), text.splitlines()


def _run_result_metadata(*, scenario_id: str, serial: str, child_exit_code: int,
                         elapsed_seconds: float, log_path: Path,
                         runtime_config_path: str, evidence_path: Path) -> dict:
    """Build scenario-bound result metadata without touching a device."""
    return {
        "offline_gate": "PASS",
        "scenario": scenario_id,
        "serial": serial,
        "child_exit_code": child_exit_code,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "log_path": str(log_path),
        "runtime_config_path": runtime_config_path,
        "evidence_path": str(evidence_path),
        "parent_redirect_mode_unchanged": os.environ.get("TB_EXPLORATION_REDIRECT_MODE"),
        "device_execution": True,
    }


def run_live(output_dir: Path, serial: str, scenario_id: str = DEFAULT_SCENARIO) -> int:
    gate = offline_gate(output_dir, scenario_id)
    child_env = gate.pop("child_environment")
    gate_path = output_dir / "RF5H_OFFLINE_GATE.json"
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence_path = output_dir / "rf5h_harness_events.jsonl"
    child_env.update({
        "TB_PHASE4C_SERIAL": serial,
        "TB_PHASE4C_SMOKE_OUT": str(output_dir),
        "TB_PHASE6D3A_RF5_EVIDENCE_PATH": str(evidence_path),
        "TB_PHASE5A_ACTION_SAFETY_MODE": "off",
    })
    for name in ("TB_PHASE5C_FULL32_ACCEPTANCE", "TB_PHASE5B_CONTROLLED", "TB_PHASE4B_CONTROLLED"):
        child_env.pop(name, None)

    log_path = output_dir / "rf5h_child.log"
    command = [sys.executable, "-u", str(Path(__file__).resolve()), "--child"]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    started = time.monotonic()
    last_notice = started
    offset = 0
    last_progress = "child process started"
    with log_path.open("w", encoding="utf-8", buffering=1) as log_stream:
        process = subprocess.Popen(command, cwd=ROOT, env=child_env,
                                   stdout=log_stream, stderr=subprocess.STDOUT,
                                   creationflags=creationflags)
        try:
            while process.poll() is None:
                time.sleep(2)
                offset, lines = _tail(log_path, offset)
                for line in lines:
                    if "[SCENARIO][entry_contract]" in line or "[STEP] START" in line or "[RF5H]" in line:
                        last_progress = line[-300:]
                now = time.monotonic()
                if now - last_notice >= 30:
                    elapsed = round(now - started)
                    print(f"[RF5H] device validation running; elapsed={elapsed}s; latest={last_progress}", flush=True)
                    last_notice = now
        except KeyboardInterrupt:
            if process.poll() is None:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
                    process.wait(timeout=20)
                except Exception:
                    process.terminate()
                    process.wait(timeout=10)
            raise
        code = int(process.returncode or 0)

    result = _run_result_metadata(
        scenario_id=scenario_id, serial=serial, child_exit_code=code,
        elapsed_seconds=time.monotonic() - started, log_path=log_path,
        runtime_config_path=gate["runtime_config_path"], evidence_path=evidence_path,
    )
    (output_dir / "RF5H_RUN_RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--scenario", choices=SUPPORTED_SCENARIOS, default=DEFAULT_SCENARIO)
    parser.add_argument("--serial", default="R3CX40QFDBP")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    if args.child:
        return _child_main()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (Path(args.output_dir).resolve() if args.output_dir else
                  ROOT / "out" / f"phase6d3a_rf5h_{args.scenario}_{stamp}")
    if args.offline_only or not args.run:
        gate = offline_gate(output_dir, args.scenario)
        gate.pop("child_environment", None)
        gate_path = output_dir / "RF5H_OFFLINE_GATE.json"
        gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(gate, ensure_ascii=False, indent=2), flush=True)
        return 0
    return run_live(output_dir, args.serial, args.scenario)


if __name__ == "__main__":
    raise SystemExit(main())
