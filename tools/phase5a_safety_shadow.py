"""Saved-observation shadow validation. Never imports a device executor."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tb_runner.action_safety import classify_action
from tb_runner.safe_action_policy import evaluate_policy
from tb_runner.phase5a_safety import SafetySession
from tb_runner.phase4a_planner import PlannerInput, plan_shadow
from tb_runner.traversal_reliability import instance_id
from tools.phase4a_shadow_validate import restore_snapshot
from tools.phase4b_gate_replay import history


def fixture_input(case):
    target = dict(resource_id="fixture:id/" + case["id"], class_name="Button", bounds="0,0,100,100")
    target["instance_id"] = instance_id(dict(scenario_id=case["scenario"], view_id=target["resource_id"], bounds=target["bounds"]))
    candidate = dict(candidate_id="fixture:" + case["id"], state_id="fixture-state", action_kind=case.get("action", "CLICK"),
        target_identity=target, target_semantics=dict(normalized_label=case["label"], role=case.get("role", "button"),
            flags=dict(clickable=True, focusable=True, enabled=True)), eligibility=dict(availability="AVAILABLE"),
        source=[], evidence=dict(current_presence=True))
    if case.get("axis"):
        candidate["evidence"].update(axis_contract="axis-v1", supporting_signals=["directional_action"])
    metadata = dict(source="CONFIGURED", effect=case["effect"], irreversible=case.get("irreversible", False)) if case.get("effect") else {}
    context = dict(surrounding_labels=case.get("surrounding", []), confirmation_verified=bool(case.get("confirmation")),
                   confirmation_risks=case.get("confirmation", []))
    conditions = dict(current_target=True, within_app=True, read_only_effect=True, recovery_verified=True,
                      modal_verified=True, cancellation_only=True, scroll_container_verified=True)
    return candidate, metadata, context, conditions


def read_lines(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--observations", type=Path, action="append", required=True)
    parser.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/phase5a_safe_actions.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out / "action_classifications.jsonl"
    if output.exists(): raise ValueError("Shadow output must be fresh")
    paths = [*args.observations, args.fixtures]
    hashes = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    counts, confidence, per_scenario, comparisons = Counter(), Counter(), defaultdict(Counter), Counter()
    fixture_results, step_results = [], []
    known = Counter()
    unique = set()
    session = SafetySession("shadow")
    executed_comparisons = Counter()
    def record(scenario, row, source):
        result, policy = row["classification"], row["policy"]
        counts[result["safety_class"]] += 1
        confidence[result["confidence"]] += 1
        per_scenario[scenario][result["safety_class"]] += 1
        per_scenario[scenario]["TOTAL_ACTIONS"] += 1
        per_scenario[scenario]["WOULD_EXECUTE" if policy["eligible"] else "WOULD_BLOCK"] += 1
        per_scenario[scenario]["WOULD_SCROLL"] += int(policy["eligible"] and result["action_type"].startswith("SCROLL"))
        unique.add(result["action_id"])
        stream.write(json.dumps(dict(scenario=scenario, source=source, **row), ensure_ascii=False) + "\n")
    with output.open("w", encoding="utf-8") as stream:
        for path in args.observations:
            trace_path = path.parent / path.name.replace("observations", "execution_trace")
            traces = {(r["scenario"], r["step"]): r for r in read_lines(trace_path)} if trace_path.exists() else {}
            for row in read_lines(path):
                if row.get("kind") != "PRE_CONTROLLED_STEP": continue
                scenario, step = row["scenario"], row["step"]
                raw = row.get("current_raw") or row["raw"]
                snapshot = restore_snapshot(row.get("current_snapshot") or row["snapshot"])
                value = PlannerInput(snapshot, row["context"]["status"], history(row.get("current_history") or row["history"]),
                                     **(row.get("current_flags") or row["planner_flags"]))
                original = deepcopy(value)
                prepared, report = session.prepare(value, raw)
                assert prepared is value and value == original and plan_shadow(prepared) == plan_shadow(original)
                off, _ = SafetySession("off").prepare(value, raw)
                assert off is value
                for result in report["candidates"]:
                    record(scenario, result, dict(kind="SAVED_DEVICE_OBSERVATION", path=str(path), step=step))
                # A factual known-safe comparison is restricted to actual Phase 4
                # focus/scroll dispatches. Other activation effects lack labels.
                trace = traces.get((scenario, step))
                comparison = "NO_CHANGE"
                selected = None
                if trace and trace.get("planner_executed"):
                    chosen = trace["shadow_recommendation"]
                    kind = "FOCUS_TARGET" if chosen["recommended_action"] == "FOCUS_CANDIDATE" else "SCROLL_FORWARD_VERTICAL"
                    selected = next((r for r in report["candidates"] if r["action_kind"] == kind
                        and r["classification"]["target_identity"].get("resource_id") == (chosen["recommended_target"] or {}).get("resource_id")
                        and r["classification"]["target_identity"].get("bounds") == (chosen["recommended_target"] or {}).get("bounds")), None)
                    if selected is None: comparison = "INSUFFICIENT_EVIDENCE"
                    elif not selected["policy"]["eligible"]: comparison = "FALSE_POSITIVE_BLOCK"
                    executed_comparisons[comparison] += 1
                comparisons[comparison] += 1
                per_scenario[scenario]["WOULD_FALLBACK"] += int(report["safety_recommendation"]["recommended_action"] == "RECOVERY_OR_NONE")
                step_results.append(dict(scenario=scenario, step=step, source=str(path), comparison=comparison,
                    phase4_executed=bool(trace and trace.get("planner_executed")),
                    phase4_recommendation=report["baseline_recommendation"], safety_recommendation=report["safety_recommendation"],
                    selected_safety=selected, blocked_candidate_count=len(report["safety_blocked_candidates"])))
        for case in json.loads(args.fixtures.read_text(encoding="utf-8"))["cases"]:
            candidate, metadata, context, conditions = fixture_input(case)
            classification = classify_action(candidate, metadata=metadata, context=context)
            policy = evaluate_policy(classification, conditions)
            result = classification.to_dict()
            correct = result["safety_class"] == case["expected"] and policy.eligible is case["eligible"]
            fixture_results.append(dict(id=case["id"], expected=case["expected"], actual=result["safety_class"], correct=correct,
                                        expected_eligible=case["eligible"], actual_eligible=policy.eligible))
            if case.get("risk"):
                known[case["risk"]] += int(result["safety_class"] == "SAFE" or policy.eligible)
            record(case["scenario"], dict(classification=result, policy=policy.to_dict(), conditions=conditions),
                   dict(kind="CONSTRUCTED_INDEPENDENT_EXPECTATION", id=case["id"]))
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    fp = executed_comparisons["FALSE_POSITIVE_BLOCK"] + sum(not r["correct"] and r["expected_eligible"] for r in fixture_results)
    fn = sum(not r["correct"] and not r["expected_eligible"] and r["actual_eligible"] for r in fixture_results)
    summary = dict(status="PASS" if fp == fn == 0 and all(r["correct"] for r in fixture_results) and not any(known.values()) else "REJECT",
        validation_mode="SAVED_DEVICE_SHADOW_PLUS_CONSTRUCTED_EXPECTATIONS", device_actions=0, new_live_run=False,
        attempt_mutations=0, visit_mutations=0, total_candidate_actions=sum(counts.values()), unique_action_identities=len(unique),
        class_counts=dict(counts), confidence_counts=dict(confidence), per_scenario={s:dict(c) for s,c in per_scenario.items()},
        phase4_comparisons=dict(comparisons), actual_phase4_executed_comparisons=dict(executed_comparisons),
        false_positive_blocks=fp, false_negative_risk_classifications=fn, known_risk_classified_safe=dict(known),
        false_negative_scope="Independent constructed expectations, not all unlabeled activation effects",
        fixture_count=len(fixture_results), fixture_results=fixture_results, step_count=len(step_results), source_sha256=hashes)
    (args.out/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out/"step_comparisons.json").write_text(json.dumps(step_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:summary[k] for k in ("status","total_candidate_actions","class_counts","step_count",
        "actual_phase4_executed_comparisons","false_positive_blocks","false_negative_risk_classifications")}, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
