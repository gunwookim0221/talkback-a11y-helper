"""Offline review of the interrupted 2026-10-11 Stage 1; never runs a device."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from tb_runner import focus_reconciliation
from tb_runner.phase4b_execution import focus_row
from tb_runner.traversal_reliability import focus_instance, instance_id
from tools.phase4b_controlled_monitor import read_lines, validate_scenario


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def test_count(path):
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    return dict(passed=sum(not any(c.find(k) is not None for k in ("failure", "error", "skipped")) for c in cases),
                skipped=sum(c.find("skipped") is not None for c in cases),
                failed=sum(c.find("failure") is not None or c.find("error") is not None for c in cases))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    parent = out.parent
    monitored = json.loads((out / "monitor_result.json").read_text(encoding="utf-8"))
    assert monitored["smoke_stopped"] and monitored["scenarios_started"] == 2
    assert all(v == 0 for v in monitored["lifecycle_gates"].values())
    source_paths = [out / "phase4b_observations.jsonl", out / "phase4b_execution_trace.jsonl", out / "monitor_result.json"]
    for scenario in ("home_main", "devices_main"):
        source_paths.extend((out / "run" / scenario).glob("*.evidence.jsonl"))
        source_paths.extend((out / "run" / scenario).glob("*.target_attempt_ledger.json"))
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    traces = read_lines(out / "phase4b_execution_trace.jsonl")
    observations = read_lines(out / "phase4b_observations.jsonl")
    assert len(traces) == 5 and all(r["scenario"] == "home_main" for r in traces)
    cases = []
    for trace in traces:
        if trace["step"] not in (1, 3):
            continue
        assert trace["focus_preview"]["focus_transition_status"] == "UNAVAILABLE"
        assert not trace["focus_preview"]["actual_focus_before_id"]
        before_node = trace["actual_focus_before"]["actual_focus_node"]
        after_node = trace["immediate_actual_focus"]
        before, after = focus_row(before_node, "home_main"), focus_row(after_node, "home_main")
        raw = next(r["current_raw"] for r in observations if r["kind"] == "PRE_CONTROLLED_STEP"
                   and r["scenario"] == "home_main" and r["step"] == trace["step"])
        got = focus_reconciliation.reconcile_focus(row=after, previous_row=before, scenario_id="home_main",
            inventory=raw["nodes"], expected_candidates=raw["nodes"], physical_visit_confirmed=False, planning_consumed=False)
        assert focus_instance(before) is not None
        assert got["focus_transition_status"] == "CONFIRMED_MOVED"
        cases.append(dict(scenario="home_main", step=trace["step"],
            original_before_resource_id=before_node.get("viewIdResourceName"), original_text=before_node.get("text"),
            original_talkback_label=before_node.get("talkbackLabel"),
            old_before_identity=trace["focus_preview"]["actual_focus_before_id"],
            fixed_before_identity=instance_id(focus_instance(before)),
            original_preview="UNAVAILABLE", fixed_offline_preview=got["focus_transition_status"],
            actual_after_identity=got["actual_focus_instance_id"],
            interpretation="Saved immediate actual focus replay; not a live retry or retroactive visit credit",
            visit_credit_applied=0))
    assert len(cases) == 2
    save(out / "adapter_fix_offline_replay.json", dict(status="PASS", cases=cases, live_retry=False, visit_credit_applied=0))
    # Preserve the original supervisor decision before applying the stricter
    # artifact-backed contract review. The original raw trace is untouched.
    original = out / "home_main_acceptance.json"
    archive = out / "home_main_original_stage_gate.json"
    if not archive.exists():
        archive.write_bytes(original.read_bytes())
    reviewed_home = validate_scenario("home_main", out)
    assert not reviewed_home["pass"]
    assert "CONFIRMED_BEFORE_FOCUS_IDENTITY_LOST_BY_ADAPTER" in reviewed_home["reasons"]
    # validate_scenario attaches the same existing terminal; require exact bytes.
    assert hashlib.sha256((out / "phase4b_execution_trace.jsonl").read_bytes()).hexdigest() == hashes[str(out / "phase4b_execution_trace.jsonl")]
    current = next(r for r in observations if r["kind"] == "PRE_CONTROLLED_STEP" and r["scenario"] == "devices_main")
    ledger_path = next((out / "run" / "devices_main").glob("*.target_attempt_ledger.json"))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["attempt_count"] == 1
    attempt = ledger["entries"][0]
    assert attempt["step"] == 1 and attempt["state"] == "MATCHED"
    partial = dict(scenario="devices_main", step=1, state_id=current["recommendation"]["planner_state_id"],
        context_status=current["recommendation"]["context_status"],
        planner_action=current["recommendation"]["recommended_action"],
        planner_target=current["recommendation"]["recommended_target"],
        planner_rank=current["recommendation"]["candidate_rank"],
        planner_reason_codes=current["recommendation"]["reason_codes"],
        execution_gate_result=current["gate"], execution_gate_reason=current["gate"]["reason"],
        actual_execution_mode="CONTROLLED_TARGET_FOCUS", planner_authorized=True, planner_executed=True,
        helper_request_id=attempt["req_id"], helper_ack_result=attempt["helper_status"],
        actual_focus_before=current["current_raw"]["focus_node"], actual_focus_after=None,
        focus_reconciliation=None, attempt_credit=1, visit_credit=None, phase4b_visit_credit=0,
        fallback_used=None, fallback_reason=None, scroll_result=None,
        classification="PLANNER_EXECUTED", termination_status="INTERRUPTED_FIRST_STEP",
        termination_reason="AGENT_STOP_AFTER_CONFIRMED_HOME_ADAPTER_REGRESSION",
        evidence_source="Production attempt ledger + saved pre-step; no final row persisted",
        evidence_path=str(ledger_path), final_step_completed=False)
    reviewed_trace = deepcopy(traces) + [partial]
    reviewed_path = out / "phase4b_execution_trace_reviewed.jsonl"
    reviewed_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in reviewed_trace), encoding="utf-8")
    original_stage = json.loads(archive.read_text(encoding="utf-8"))
    baseline_root = parent / "phase4a_shadow_acceptance_20261011"
    baseline = [r for r in read_lines(baseline_root / "phase4a_shadow_trace.jsonl") if r["scenario"] == "home_main"]
    baseline_visits = sum(r["production_result"].get("visit_record_status") == "RECORDED" for r in baseline)
    comparison = dict(scenario="home_main", recent_production_steps=len(baseline), controlled_completed_steps=5,
        recent_production_new_visits=baseline_visits, controlled_production_new_visits=5,
        catastrophic_visit_reduction=False, controlled_target_failures=2, controlled_fallbacks=2,
        abnormal_fallback_rate=True, anchor_failure=False, unsafe_visit_credit=False,
        regression=True, regression_reason="Before-focus adapter loses real Helper talkbackLabel-only identities",
        full_content_reachability="Not established by five-step smoke", family_state_comparison="NOT_RUN")
    save(out / "production_comparison.json", comparison)
    tests = {name: test_count(parent / file) for name, file in dict(
        authority="phase4b_final_authority_tests.xml", planner="phase4b_final_planner.xml",
        phase3="phase4b_final_phase3.xml", production="phase4b_final_production.xml",
        additional="phase4b_final_additional.xml", full="phase4b_final_full_python.xml").items()}
    assert all(r["failed"] == 0 for r in tests.values())
    assert tests["full"]["passed"] == 3545 + tests["authority"]["passed"]
    scenario_metrics = {"home_main": reviewed_home["metrics"]}
    required = ("TOTAL_STEPS", "PLANNER_RECOMMENDATIONS", "PLANNER_AUTHORIZED", "PLANNER_EXECUTED",
        "PLANNER_BLOCKED", "PLANNER_FAILED", "PRODUCTION_FALLBACKS", "CONFIRMED_FOCUS_MOVES",
        "FAILED_FOCUS_MOVES", "INDETERMINATE_FOCUS", "ATTEMPTS", "VISITS", "SCROLL_RECOMMENDATIONS",
        "SCROLL_EXECUTED", "SCROLL_MOVED", "SCROLL_NO_MOVEMENT", "STATE_TRANSITIONS")
    devices = {key: None for key in required}
    devices.update(ENTRY_RESULT="PASS", TOTAL_STEPS=0, PLANNER_RECOMMENDATIONS=1,
        PLANNER_AUTHORIZED=1, PLANNER_EXECUTED=1, PLANNER_BLOCKED=0, ATTEMPTS=1,
        SCROLL_RECOMMENDATIONS=0, SCROLL_EXECUTED=0, SCROLL_MOVED=0, SCROLL_NO_MOVEMENT=0,
        TERMINATION_STATUS="INTERRUPTED_FIRST_STEP", TERMINATION_REASON=partial["termination_reason"],
        COMPLETED_STEPS=0, ATTEMPTED_STEP_STARTED=1, TARGET_ATTEMPTS=1,
        OUTCOME_NOTE="No final production reconciliation; null outcomes are unknown, not zero")
    scenario_metrics["devices_main"] = devices
    for scenario in ("life_find_plugin", "device_smoke_sensor_plugin", "life_food_plugin", "life_family_care_plugin"):
        scenario_metrics[scenario] = {**dict.fromkeys(required, 0), "ENTRY_RESULT": "NOT_STARTED",
            "TERMINATION_STATUS": "NOT_RUN", "TERMINATION_REASON": "STAGE1_REJECTED"}
    save(out / "per_scenario_metrics.json", scenario_metrics)
    refs = subprocess.check_output(["git", "rev-parse", "HEAD", "origin/integration/phase3-current-main", "main", "origin/main",
                                  "feature/phase3c-transition-stability-closure"], text=True).splitlines()
    assert refs[0] == refs[1] == "ef3d1c92bdbb4716a1b0525ba715622c75f52756"
    assert refs[2] == refs[3] == "6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee"
    assert refs[4] == "fb4d01c489a0b3d56883e074771eb823c453d4f2"
    replay = json.loads((parent / "phase4b_final_gate_replay_20261011/summary.json").read_text(encoding="utf-8"))
    report = dict(OVERALL_VERDICT="PHASE4B_CONTROLLED_EXECUTION_REJECT",
        START_INTEGRATION_HEAD=refs[0], FINAL_INTEGRATION_HEAD=refs[0], ORIGIN_INTEGRATION_HEAD=refs[1],
        MAIN_HEAD=refs[2], ORIGIN_MAIN=refs[3], MAIN_CHANGED="NO", ORIGINAL_PHASE3_HEAD=refs[4], ORIGINAL_PHASE3_BRANCH_CHANGED="NO",
        PHASE4B_IMPLEMENTED="YES_LOCAL_FIX_NOT_LIVE_ACCEPTED", PLANNER_AUTHORITY="LIMITED",
        DEFAULT_PRODUCTION_PLANNER_EXECUTION="OFF", TARGETED_FOCUS_EXECUTION="6_ATTEMPTS_5_COMPLETED_STEPS_STAGE1_REJECTED",
        CONTROLLED_SCROLL_EXECUTION="IMPLEMENTED_UNIT_VERIFIED_NOT_LIVE_EXERCISED", PRODUCTION_FALLBACK="BOUNDED_OBSERVED_2",
        FAILURE_DEGRADE_TO_PRODUCTION="IMPLEMENTED_UNIT_VERIFIED",
        AUTHORITY_GATE_TESTS=f'{tests["authority"]["passed"]} PASSED', PLANNER_TESTS=f'{tests["planner"]["passed"]} PASSED',
        PHASE3_TESTS=f'{tests["phase3"]["passed"]} PASSED', PRODUCTION_TESTS=f'{tests["production"]["passed"]} PASSED; ADDITIONAL {tests["additional"]["passed"]} PASSED',
        FULL_PYTHON_SUITE=f'{tests["full"]["passed"]} PASSED, {tests["full"]["skipped"]} SKIPPED', HELPER_TESTS="NOT_REQUIRED",
        HISTORICAL_TRANSITION_REPLAY=f'{replay["historical_exact"]}/16 EXACT', ACCEPTED_BASELINE_REPLAY=f'{replay["accepted_scenarios"]}/6 PASS',
        HOME_CONTROLLED_SMOKE="REJECT_BEFORE_FOCUS_ADAPTER_REGRESSION", DEVICES_CONTROLLED_SMOKE="INTERRUPTED_FIRST_STEP",
        FIND_CONTROLLED_SMOKE="NOT_RUN_STAGE1_REJECTED", SMOKE_SENSOR_CONTROLLED_SMOKE="NOT_RUN_STAGE1_REJECTED",
        FOOD_CONTROLLED_SMOKE="NOT_RUN_STAGE1_REJECTED", FAMILY_CONTROLLED_SMOKE="NOT_RUN_STAGE1_REJECTED",
        TOTAL_PLANNER_RECOMMENDATIONS=6, TOTAL_PLANNER_AUTHORIZED=6, TOTAL_PLANNER_EXECUTED=6, TOTAL_PLANNER_BLOCKED=0,
        TOTAL_PLANNER_FAILED=2, TOTAL_PRODUCTION_FALLBACKS=2, TOTAL_CONFIRMED_FOCUS_MOVES=5, TOTAL_VISITS=5,
        TOTAL_SCROLL_RECOMMENDATIONS=0, TOTAL_SCROLL_EXECUTED=0, TOTAL_SCROLL_MOVED=0,
        CONTROLLED_EXECUTION_REGRESSION="YES", **monitored["lifecycle_gates"],
        PHASE4C_IMPLEMENTED="NO", PHASE5_IMPLEMENTED="NO", READY_FOR_PHASE4C="NO", EXECUTION_TRACE_PATH=str(reviewed_path),
        INTEGRATION_COMMIT="NOT_CREATED_REJECT", INTEGRATION_BRANCH_PUSHED="NO", DOCUMENT_PATH=str(Path(__file__).resolve().parents[1] / "docs/design/talkback-phase4b-controlled-execution-20261011.md"),
        NEXT_STEP="Review local adapter fix; a newly authorized Stage 1 acceptance run is required. No automatic retry.")
    save(out / "final_report.json", report)
    (out / "final_report.txt").write_text("\n".join(f"{k}={v}" for k, v in report.items()) + "\n", encoding="utf-8")
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    save(out / "stage1_stop_review.json", dict(verdict=report["OVERALL_VERDICT"], corrected_home_acceptance=reviewed_home,
        original_home_stage_decision=original_stage["pass"], tests=tests, comparison=comparison,
        live_fix_retested=False, source_hashes_unchanged=True, source_hashes=hashes,
        completed_steps=5, interrupted_steps=1, partial_step_visit_credit="UNKNOWN_NOT_COUNTED",
        stage2_started=False, stage3_started=False, production_visit_authority=True,
        phase4b_visit_credit=0, no_automatic_retry=True))
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
