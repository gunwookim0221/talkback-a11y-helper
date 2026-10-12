"""Ordered A→B→C→D validation with the existing correlated hard-stop monitor."""
import json
import os
from collections import Counter
from pathlib import Path

from tools import phase4a_shadow_monitor as monitor
from tools.phase4b_controlled_monitor import read_lines, controlled_target_evidence_failures
from tb_runner.phase4c_traversal import STAGES, SCENARIOS, BUDGETS
from tb_runner.action_provenance import chain_gates, action_chain_failures, digest
from tb_runner.dynamic_context import ownership_failures, stable_digest

# Full32 Phase 5 acceptance may retain a larger production traversal limit
# while Phase 4C/5B controlled actions stay inside their bounded slice.
PRODUCTION_MAX_STEPS = {}


def production_step_limit(scenario):
    value = PRODUCTION_MAX_STEPS.get(scenario, BUDGETS[scenario])
    if type(value) is not int or value < 1:
        raise ValueError(f"invalid production max_steps for {scenario}: {value!r}")
    return value


def planner_loop_unbounded(rows, production_max_steps, controlled_action_budget):
    if type(production_max_steps) is not int or production_max_steps < 1:
        raise ValueError("production max_steps must be a positive integer")
    if type(controlled_action_budget) is not int or not 1 <= controlled_action_budget <= 20:
        raise ValueError("controlled action budget must be 1..20")
    controlled_actions = sum(bool(row.get("planner_executed")) for row in rows)
    return len(rows) > production_max_steps or controlled_actions > controlled_action_budget


def validate_scenario(scenario, out):
    rows = [r for r in read_lines(out / "phase4c_execution_trace.jsonl") if r["scenario"] == scenario]
    entries = [r for r in read_lines(out / "phase4c_observations.jsonl") if r["scenario"] == scenario and r["kind"] == "ENTRY_TO_TRAVERSAL"]
    terminals = [r["payload"] for p in (out / "run" / scenario).glob("*.evidence.jsonl")
        for r in read_lines(p) if r["scenario_id"] == scenario and r["event_type"] == "SCENARIO_TERMINAL"]
    terminal = terminals[-1] if terminals else {}
    status = terminal.get("termination_status")
    reason = terminal.get("termination_reason")
    reasons = []
    if len(entries) != 1:
        reasons.append("NORMAL_ENTRY_NOT_PROVEN")
    production_max_steps = production_step_limit(scenario)
    if (not rows or [r["step"] for r in rows] != list(range(1, len(rows)+1))
            or len(rows) > production_max_steps):
        reasons.append("BOUNDED_STEPS_NOT_PROVEN")
    if not any(r["planner_executed"] for r in rows):
        reasons.append("NO_CONTROLLED_EXECUTION")
    if not terminal or status in {"INCOMPLETE_ERROR", "ENTRY_FAILED", "ENTRY_ABORTED"} or "anchor" in str(reason).lower():
        reasons.append("PRODUCTION_TERMINAL_FAILURE")
    if len(rows) < production_max_steps and status == "INCOMPLETE_NO_PROGRESS" and not rows[-1].get("no_progress_proven"):
        reasons.append("EARLY_NO_PROGRESS_NOT_PROVEN")
    safety = Counter()
    audit_gates = Counter()
    observed_steps = {r['step']:r for r in read_lines(out / "phase4c_observations.jsonl")
                      if r['scenario'] == scenario and r['kind'] == 'PRE_CONTROLLED_STEP'}
    destination_events = {r['event_id']:r for r in read_lines(out / 'phase4c_destination_events.jsonl')}
    for r in rows:
        ownership_errors = ownership_failures(r)
        dynamic = r.get('dynamic_context')
        if dynamic:
            original = observed_steps.get(r['step']) or {}
            if (dynamic.get('before') != (original.get('raw') or {}).get('destination_ownership')
                    or dynamic.get('current') != (original.get('current_raw') or {}).get('destination_ownership')):
                ownership_errors.append('CROSS_DESTINATION_CONTEXT_LEAK')
            for event in dynamic.get('events', []):
                if (destination_events.get(event.get('event_id')) != event
                        or event.get('event_id') != stable_digest({k:v for k,v in event.items() if k != 'event_id'})):
                    ownership_errors.append('DESTINATION_EVENT_PROVENANCE_MISSING')
                if event.get('scenario_id') != scenario:
                    ownership_errors.append('CROSS_SCENARIO_CONTEXT_LEAK')
        reasons.extend(ownership_errors)
        for name in ("CROSS_DESTINATION_CONTEXT_LEAK", "CROSS_SCENARIO_CONTEXT_LEAK"):
            safety[name] += name in ownership_errors
        chain = r.get("action_audit_chain")
        audit_gates.update(chain_gates(chain, r))
        if action_chain_failures(chain, r):
            reasons.append("AUDIT_CHAIN_INCOMPLETE")
        ref = (r.get("production_row") or {}).get("step_action_provenance") or {}
        if chain and (ref.get("sha256") != digest(chain) or ref.get("step_action_id") != chain.get("step_action_id")):
            audit_gates["AUDIT_CHAIN_INCOMPLETE_COUNT"] += 1
            reasons.append("FINAL_ROW_PROVENANCE_MISMATCH")
        safety["UNSAFE_TARGET_EXECUTION"] += bool(r["planner_executed"] and not r["execution_gate_result"]["allowed"])
        safety["FALSE_VISIT_CREDIT"] += bool(r["phase4b_visit_credit"] or r["visit_credit"] and r["focus_transition_status"] != "CONFIRMED_MOVED")
        safety["STALE_TARGET_EXECUTION"] += bool(r.get("target_attempt_id") and not r.get("helper_result_correlated") and not r.get("fallback_used"))
        safety["AMBIGUOUS_TARGET_EXECUTION"] += bool(r["planner_executed"] and r["actual_execution_mode"] == "CONTROLLED_TARGET_FOCUS" and (r.get("target_binding") or {}).get("eligible_match_count") != 1)
        safety["FALSE_FOCUS_MOVEMENT"] += bool(controlled_target_evidence_failures(r))
        if r.get("starvation_signal"):
            reasons.append("STARVATION_PRIORITY_VIOLATION")
        if r["planner_executed"] and r["actual_execution_mode"] == "CONTROLLED_SCROLL":
            if not r.get("post_scroll_refresh") or not r.get("scroll_transition"):
                reasons.append("SCROLL_REFRESH_MISSING")
        if r.get("gate_evidence", {}).get("focus_coherent") is True and r.get("focus_preview") and not r["focus_preview"].get("actual_focus_before_id"):
            reasons.append("BEFORE_FOCUS_IDENTITY_LOST")
    safety["PLANNER_LOOP_UNBOUNDED"] = int(
        planner_loop_unbounded(rows, production_max_steps, BUDGETS[scenario])
    )
    reasons.extend(k for k,v in safety.items() if v)
    reasons.extend(k for k,v in audit_gates.items() if v)
    evidence_chains = read_lines(out / "phase4c_step_action_evidence.jsonl")
    evidence_by_id = {r["step_action_id"]: r for r in evidence_chains}
    for r in rows:
        chain = r.get("action_audit_chain") or {}
        if evidence_by_id.get(chain.get("step_action_id")) != chain:
            reasons.append("IMMUTABLE_ACTION_EVIDENCE_MISSING")
            audit_gates["AUDIT_CHAIN_INCOMPLETE_COUNT"] += 1
    moves = Counter(r.get("focus_transition_status") for r in rows)
    scrolls = Counter(r.get("scroll_result") for r in rows)
    executed = lambda mode: sum(r["planner_executed"] and r["actual_execution_mode"] == mode for r in rows)
    metrics = dict(ENTRY_RESULT="PASS" if len(entries)==1 else "FAIL", TOTAL_STEPS=len(rows),
        PLANNER_FOCUS_RECOMMENDATIONS=sum(r["planner_action"]=="FOCUS_CANDIDATE" for r in rows),
        PLANNER_FOCUS_EXECUTED=executed("CONTROLLED_TARGET_FOCUS"),
        PLANNER_SCROLL_RECOMMENDATIONS=sum(r["planner_action"]=="SCROLL_FORWARD" for r in rows),
        PLANNER_SCROLL_EXECUTED=executed("CONTROLLED_SCROLL"), PRODUCTION_FALLBACKS=sum(r["fallback_used"] for r in rows),
        CONFIRMED_FOCUS_MOVES=moves["CONFIRMED_MOVED"], FAILED_FOCUS_MOVES=moves["CONFIRMED_UNCHANGED"],
        INDETERMINATE_FOCUS=moves["UNAVAILABLE"]+moves["AMBIGUOUS"],
        SCROLL_MOVED=scrolls["SCROLL_MOVED"], SCROLL_NO_MOVEMENT=scrolls["SCROLL_NO_MOVEMENT"],
        SCROLL_EXHAUSTED=sum(r.get("scroll_state")=="SCROLL_EXHAUSTED" for r in rows),
        ATTEMPTS=sum(r["attempt_credit"] for r in rows), VISITS=sum(r["visit_credit"] for r in rows),
        UNIQUE_VISITS=terminal.get("unique_visited_instances"), NEW_CANDIDATES_DISCOVERED=sum(r.get("new_candidate_discovered",0) for r in rows),
        LOOP_EVENTS=sum(bool(r.get("loop_signal")) for r in rows), STARVATION_EVENTS=sum(bool(r.get("starvation_signal")) for r in rows),
        SATURATION_EVENTS=sum(bool(r.get("saturation_signal")) for r in rows), TERMINATION_STATUS=status, TERMINATION_REASON=reason,
        PLANNER_EXECUTION_RATE=sum(r["planner_executed"] for r in rows)/len(rows) if rows else 0,
        FALLBACK_RATE=sum(r["fallback_used"] for r in rows)/len(rows) if rows else 0,
        FALLBACK_REASONS=dict(Counter(r["fallback_reason"] for r in rows if r["fallback_used"])),
        RECOVERY_EVENTS=sum(len((r.get("action_audit_chain") or {}).get("recovery_result_event_ids", [])) for r in rows),
        AUDIT_CHAIN_COMPLETE=sum(not action_chain_failures(r.get("action_audit_chain"), r) for r in rows),
        **dict(audit_gates))
    result = dict(scenario=scenario, stage=next(i for i, stage in enumerate(STAGES,1) if scenario in stage),
        **{"pass": not reasons}, reasons=sorted(set(reasons)), metrics=metrics, planner_safety=dict(safety), audit_gates=dict(audit_gates), terminal=terminal)
    monitor.save_json(out / (scenario+"_acceptance.json"), result)
    print("[PHASE4C_SCENARIO_ACCEPTANCE] "+json.dumps(result),flush=True)
    return result


def main():
    if os.environ.get("TB_PHASE4C_CONTROLLED") != "1":
        raise ValueError("Explicit Phase 4C opt-in required")
    out = Path(os.environ["TB_PHASE4C_SMOKE_OUT"]).resolve()
    replay = json.loads(Path(os.environ["TB_PHASE4C_REPLAY_SUMMARY"]).read_text(encoding="utf-8"))
    if replay.get("status") != "PASS" or replay.get("phase4b_controlled_exact") != 30:
        raise ValueError("All replay gates must pass before live")
    if (out/"monitor_result.json").exists() or (out/"phase4c_execution_trace.jsonl").exists():
        raise ValueError("Fresh output required; no automatic acceptance retry")
    previous = monitor.OUT, monitor.SCENARIOS, monitor.SERIAL
    monitor.OUT, monitor.SCENARIOS, monitor.SERIAL = out, SCENARIOS, os.environ.get("TB_PHASE4C_SERIAL","R3CX40QFDBP")
    try:
        return monitor.main(runner_module="tools.phase4c_generalized_smoke", env_prefix="TB_PHASE4C",
            scenario_validator=validate_scenario, scenario_budgets=BUDGETS)
    finally:
        monitor.OUT, monitor.SCENARIOS, monitor.SERIAL = previous


if __name__ == "__main__":
    raise SystemExit(main())
