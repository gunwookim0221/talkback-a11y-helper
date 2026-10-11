"""Read-only authority replay; no client, device action or production credit."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.phase4a_planner import PlannerInput, ProductionHistory, plan_shadow
from tb_runner.phase4b_authority import AuthorityEvidence, execution_gate
from tb_runner.phase4b_execution import coherent_focus, safe_scroll_container, geometry_in_viewport
from tb_runner.state_registry import StateRegistry
from tools.phase4a_shadow_validate import restore_snapshot
from tools import phase4a_shadow_replay
from tools.phase4b_controlled_smoke import SCENARIOS


def history(document):
    copied = dict(document)
    for key in ("attempts", "visits", "last_attempt_steps"):
        copied[key] = tuple(tuple(x) for x in copied[key])
    for key in ("recent_attempts", "stale_ids"):
        copied[key] = tuple(copied[key])
    if copied["allowed_instance_ids"] is not None:
        copied["allowed_instance_ids"] = tuple(copied["allowed_instance_ids"])
    return ProductionHistory(**copied)


def replay(value, raw, *, hypothetical_current=False):
    recommendation = plan_shadow(value)
    evidence = AuthorityEvidence(enabled=True, fresh=hypothetical_current,
        recovery_clear=not value.pending_transition and not value.safety_blocked,
        lifecycle_clear=hypothetical_current, transport_clear=hypothetical_current,
        focus_coherent=coherent_focus(raw),
        geometry_in_viewport=geometry_in_viewport(raw, recommendation),
        structural_scope_proven=bool(raw.get("package_name") and raw.get("activity_name")),
        scroll_container_proven=safe_scroll_container(raw, recommendation))
    gate = execution_gate(value, recommendation, value, evidence)
    assert gate == execution_gate(value, recommendation, value, evidence)
    return dict(scenario=value.history.scenario_id, step=raw.get("step"),
        SHADOW_ACTION=recommendation.to_dict()["recommended_action"], EXECUTION_GATE=gate.to_dict(),
        HYPOTHETICAL_CONTROLLED_ACTION=gate.mode if gate.allowed else "FALLBACK_PRODUCTION",
        FALLBACK_REQUIRED=not gate.allowed, REASON=gate.reason,
        recommendation=recommendation.to_dict(), action_executed=False, visit_credit=0,
        evidence_basis="HYPOTHETICAL_CURRENT_RECORDED_CAPTURE" if hypothetical_current else "HISTORICAL_NOT_CURRENT")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--phase4a", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    foundation = args.out / "foundation"
    previous = sys.argv
    sys.argv = ["phase4a_shadow_replay", "--root", str(args.root), "--out", str(foundation)]
    try:
        assert phase4a_shadow_replay.main() == 0
    finally:
        sys.argv = previous
    source = args.phase4a / "phase4a_observations.jsonl"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    controlled = []
    for row in rows:
        if row["kind"] != "PRE_PRODUCTION_STEP":
            continue
        value = PlannerInput(restore_snapshot(row["snapshot"]), row["context"]["status"],
                             history(row["history"]), **row["planner_flags"])
        assert plan_shadow(value).to_dict() == row["recommendation"]
        controlled.append(replay(value, row["raw"], hypothetical_current=True))
    assert len(controlled) == 30
    assert any(r["EXECUTION_GATE"]["allowed"] for r in controlled)
    assert any(not r["EXECUTION_GATE"]["allowed"] for r in controlled)
    baseline = []
    for scenario in SCENARIOS:
        saved = json.loads((foundation / (scenario + ".json")).read_text(encoding="utf-8"))
        for row in saved:
            value = PlannerInput(build_discovery_snapshot(row["raw"], StateRegistry("phase4b-accepted-" + scenario)),
                                 row["context_status"], history(row["history"]))
            # Saved accepted captures lack an independent strict current focus.
            # Evaluate their authority hypothetically, still fail closed on it.
            got = replay(value, row["raw"], hypothetical_current=True)
            assert not got["EXECUTION_GATE"]["allowed"]
            baseline.append(got)
    assert len({r["scenario"] for r in baseline}) == 6
    historical = args.root / "output/phase3d_semantic_substate_20261005/actions"
    from tb_runner.transition_observation import TransitionObserver
    from tb_runner.phase3_context import resolve_phase3_context
    observer = TransitionObserver(StateRegistry.load(historical / "registry_seed.json"))
    cases = json.loads((historical / "brackets.json").read_text(encoding="utf-8"))
    expected = [json.loads(line) for line in (historical / "transitions.jsonl").read_text(encoding="utf-8").splitlines()]
    historical_rows = []
    for case, saved in zip(cases, expected):
        prepared = observer.prepare(case["before_raw"], case["action"], action_started_at=case["action_started_at"])
        raw = case["before_raw"]
        value = PlannerInput(prepared.source_snapshot, resolve_phase3_context(raw)["status"],
                             ProductionHistory(str(raw.get("scenario_id") or "")))
        historical_rows.append(replay(value, raw))
        result = observer.complete(prepared, case["after_raw"], command_ack=case["command_ack"],
            action_evidence=case["action_evidence"], action_finished_at=case["action_finished_at"], evidence_refs=case["evidence_refs"])
        assert result.to_dict() == saved
    assert len(historical_rows) == len(expected) == len(cases) == 16
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    for name, data in (("phase4a_input_gate_replay.json", controlled), ("accepted_gate_replay.json", baseline),
                       ("historical_gate_replay.json", historical_rows)):
        phase4a_shadow_replay.save(args.out / name, data)
    result = dict(status="PASS", historical_exact=16, accepted_scenarios=6, phase4a_input_exact=30,
        authorized=sum(r["EXECUTION_GATE"]["allowed"] for r in controlled),
        blocked=sum(not r["EXECUTION_GATE"]["allowed"] for r in controlled),
        gate_reasons=dict(Counter(r["REASON"] for r in controlled)),
        accepted_reasons=dict(Counter(r["REASON"] for r in baseline)),
        no_actions_executed=True, visit_credit=0, sources_unchanged=True,
        phase4a_source_sha256=digest)
    phase4a_shadow_replay.save(args.out / "summary.json", result)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
