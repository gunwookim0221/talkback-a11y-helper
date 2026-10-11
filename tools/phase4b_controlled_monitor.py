"""Sequential staged supervisor using the accepted correlated lifecycle monitor."""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path

from tools import phase4a_shadow_monitor as monitor
from tools.phase4b_controlled_smoke import SCENARIOS, STAGES
from tb_runner.phase4b_target_binding import actual_target_matches
from tb_runner.phase4b_execution import focus_row
from tb_runner.traversal_reliability import focus_instance, instance_id
from tb_runner.action_provenance import final_actor_proven


def controlled_target_evidence_failures(row):
    """Verify each actor at its observation boundary; never award a visit.

    Production may realign after the controlled action. Its final actual focus
    must agree with production reconciliation, not with an earlier target.
    """
    if not row.get("planner_executed") or row.get("actual_execution_mode") != "CONTROLLED_TARGET_FOCUS":
        return []
    reasons = []
    if (row.get("target_binding") or {}).get("eligible_match_count") != 1:
        reasons.append("CANONICAL_TARGET_BINDING_NOT_PROVEN")
    if not row.get("fallback_used"):
        if not actual_target_matches(row.get("immediate_actual_focus"), row["planner_target"]):
            reasons.append("CONTROLLED_IMMEDIATE_TARGET_METADATA_MISMATCH")
        preview = row.get("focus_preview") or {}
        if (preview.get("focus_transition_status") != "CONFIRMED_MOVED"
                or preview.get("actual_focus_instance_id") != row["shadow_recommendation"]["recommended_instance_id"]):
            reasons.append("CONTROLLED_TARGET_MOVEMENT_NOT_PROVEN")
        if row.get("helper_result_correlated") is not True:
            reasons.append("CONTROLLED_HELPER_RESULT_NOT_CORRELATED")
        if (row.get("helper_ack_result") or {}).get("requestedTarget", {}).get("requireFocusable") is not True:
            reasons.append("CONTROLLED_HELPER_PREDICATE_NOT_OBSERVED")
    actual = focus_instance(focus_row(row.get("actual_focus_after") or {}, row["scenario"]))
    reconciled = (row.get("focus_reconciliation") or {}).get("actual_focus_instance_id")
    if not actual or instance_id(actual) != reconciled:
        if row.get("action_audit_chain") and final_actor_proven(row):
            return reasons
        reasons.append("FINAL_ACTUAL_FOCUS_DISAGREES_WITH_PRODUCTION_RECONCILIATION")
    return reasons


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def validate_scenario(scenario, out):
    traces = [r for r in read_lines(out / "phase4b_execution_trace.jsonl") if r["scenario"] == scenario]
    entries = [r for r in read_lines(out / "phase4b_observations.jsonl")
               if r["scenario"] == scenario and r["kind"] == "ENTRY_TO_TRAVERSAL"]
    terminal_events = [r for p in (out / "run" / scenario).glob("*.evidence.jsonl")
                       for r in read_lines(p) if r["event_type"] == "SCENARIO_TERMINAL" and r["scenario_id"] == scenario]
    terminal = terminal_events[-1]["payload"] if terminal_events else {}
    reasons = []
    if len(entries) != 1:
        reasons.append("NORMAL_PRODUCTION_ENTRY_NOT_PROVEN")
    if [r["step"] for r in traces] != list(range(1, 6)):
        reasons.append("FIVE_TOTAL_STEPS_NOT_OBSERVED")
    if not any(r["planner_executed"] for r in traces):
        reasons.append("NO_REAL_CONTROLLED_ACTION")
    if sum(r["planner_executed"] for r in traces) > 5:
        reasons.append("ACTION_BUDGET_EXCEEDED")
    for r in traces:
        if r["planner_executed"] and not r["execution_gate_result"]["allowed"]:
            reasons.append("GATE_BYPASSED")
        if r["phase4b_visit_credit"] != 0:
            reasons.append("PLANNER_VISIT_AUTHORITY")
        if r["visit_credit"] and r["focus_transition_status"] != "CONFIRMED_MOVED":
            reasons.append("VISIT_WITHOUT_CONFIRMED_MOVEMENT")
        if r.get("target_attempt_id") and not r.get("helper_result_correlated") and not r.get("fallback_used"):
            reasons.append("STALE_RESULT_ATTRIBUTION")
        if r["planner_executed"] and r["actual_execution_mode"] == "CONTROLLED_TARGET_FOCUS":
            preview = r.get("focus_preview") or {}
            if r.get("gate_evidence", {}).get("focus_coherent") is True and not preview.get("actual_focus_before_id"):
                reasons.append("CONFIRMED_BEFORE_FOCUS_IDENTITY_LOST_BY_ADAPTER")
    if not terminal:
        reasons.append("MISSING_PRODUCTION_TERMINAL")
    status = terminal.get("termination_status") or terminal.get("terminal_status") or terminal.get("status")
    reason = terminal.get("termination_reason") or terminal.get("reason") or terminal.get("stop_reason")
    if status in {"INCOMPLETE_ERROR", "ENTRY_ABORTED", "ENTRY_FAILED"} or "anchor" in str(reason).lower():
        reasons.append("PRODUCTION_TERMINAL_FAILURE")
    moves = Counter(r.get("focus_transition_status") for r in traces)
    if traces and not moves["CONFIRMED_MOVED"]:
        reasons.append("NO_CONFIRMED_PROGRESS")
    metrics = dict(ENTRY_RESULT="PASS" if len(entries) == 1 else "FAIL", TOTAL_STEPS=len(traces),
        PLANNER_RECOMMENDATIONS=len(traces), PLANNER_AUTHORIZED=sum(r["planner_authorized"] for r in traces),
        PLANNER_EXECUTED=sum(r["planner_executed"] for r in traces),
        PLANNER_BLOCKED=sum(not r["planner_authorized"] for r in traces),
        PLANNER_FAILED=sum(r["planner_failed"] for r in traces),
        PRODUCTION_FALLBACKS=sum(r["fallback_used"] for r in traces),
        CONFIRMED_FOCUS_MOVES=moves["CONFIRMED_MOVED"], FAILED_FOCUS_MOVES=moves["CONFIRMED_UNCHANGED"],
        INDETERMINATE_FOCUS=moves["UNAVAILABLE"] + moves["AMBIGUOUS"],
        ATTEMPTS=terminal.get("attempted_steps", len(traces)),
        TARGET_ATTEMPTS=sum(r["attempt_credit"] for r in traces), VISITS=sum(r["visit_credit"] for r in traces),
        UNIQUE_VISITS=terminal.get("unique_visited_instances"),
        SCROLL_RECOMMENDATIONS=sum(r["planner_action"] == "SCROLL_FORWARD" for r in traces),
        SCROLL_EXECUTED=sum(r["actual_execution_mode"] == "CONTROLLED_SCROLL" for r in traces),
        SCROLL_MOVED=sum(r["scroll_result"] == "SCROLL_MOVED" for r in traces),
        SCROLL_NO_MOVEMENT=sum(r["scroll_result"] == "SCROLL_NO_MOVEMENT" for r in traces),
        STATE_TRANSITIONS=sum(a["state_id"] != b["state_id"] for a, b in zip(traces, traces[1:])),
        TERMINATION_STATUS=status, TERMINATION_REASON=reason)
    result = dict(scenario=scenario, stage=next(i for i, stage in enumerate(STAGES, 1) if scenario in stage),
                  **{"pass": not reasons}, reasons=sorted(set(reasons)), metrics=metrics, terminal=terminal)
    monitor.save_json(out / (scenario + "_acceptance.json"), result)
    if traces:
        all_traces = read_lines(out / "phase4b_execution_trace.jsonl")
        for row in all_traces:
            if row["scenario"] == scenario and row["step"] == traces[-1]["step"]:
                row.update(termination_status=status, termination_reason=reason)
        (out / "phase4b_execution_trace.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in all_traces), encoding="utf-8")
    print("[PHASE4B_SCENARIO_ACCEPTANCE] " + json.dumps(result), flush=True)
    return result


def main():
    if os.environ.get("TB_PHASE4B_CONTROLLED") != "1":
        raise ValueError("Explicit TB_PHASE4B_CONTROLLED=1 required")
    out = Path(os.environ["TB_PHASE4B_SMOKE_OUT"]).resolve()
    replay = json.loads(Path(os.environ["TB_PHASE4B_REPLAY_SUMMARY"]).read_text(encoding="utf-8"))
    if replay.get("status") != "PASS" or replay.get("historical_exact") != 16 or replay.get("accepted_scenarios") != 6:
        raise ValueError("Offline gate, exact historical16 and accepted6 replay must pass before live")
    if (out / "monitor_result.json").exists() or (out / "phase4b_execution_trace.jsonl").exists():
        raise ValueError("Use a fresh output root; no automatic scenario retry")
    previous = monitor.OUT, monitor.SCENARIOS, monitor.SERIAL
    monitor.OUT, monitor.SCENARIOS = out, SCENARIOS
    monitor.SERIAL = os.environ.get("TB_PHASE4B_SERIAL", "R3CX40QFDBP")
    try:
        return monitor.main(runner_module="tools.phase4b_controlled_smoke", env_prefix="TB_PHASE4B",
                            scenario_validator=validate_scenario)
    finally:
        monitor.OUT, monitor.SCENARIOS, monitor.SERIAL = previous


if __name__ == "__main__":
    raise SystemExit(main())
