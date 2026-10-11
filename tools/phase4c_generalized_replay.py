"""Replay accepted Phase 3/4 evidence without device actions or ledger changes."""
import argparse
import json
import sys
import hashlib
from pathlib import Path
from tb_runner.phase4a_planner import PlannerInput, plan_shadow
from tb_runner.phase4b_authority import AuthorityEvidence, execution_gate
from tools.phase4a_shadow_validate import restore_snapshot
from tools.phase4b_gate_replay import history
from tools.phase4b_controlled_monitor import controlled_target_evidence_failures, read_lines
from tools import phase4b_gate_replay


def main():
    parser=argparse.ArgumentParser(__doc__)
    for flag in ("root","phase4a","phase4b","out"):
        parser.add_argument("--"+flag,type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    old=sys.argv
    sys.argv=["replay","--root",str(args.root),"--phase4a",str(args.phase4a),"--out",str(args.out/"foundation")]
    try: assert phase4b_gate_replay.main()==0
    finally: sys.argv=old
    observations=args.phase4b/"phase4b_observations.jsonl"
    traces=args.phase4b/"phase4b_execution_trace.jsonl"
    paths=[observations,traces]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    records=[]
    for row in read_lines(observations):
        if row["kind"]!="PRE_CONTROLLED_STEP": continue
        before=PlannerInput(restore_snapshot(row["snapshot"]),row["context"]["status"],history(row["history"]),**row["planner_flags"])
        after=PlannerInput(restore_snapshot(row["current_snapshot"]),row["context"]["status"],history(row["current_history"]),**row["current_flags"])
        recommendation=plan_shadow(before)
        assert recommendation.to_dict()==row["recommendation"]
        gate=execution_gate(before,recommendation,after,AuthorityEvidence(**row["gate_evidence"]))
        assert gate.to_dict()==row["gate"]
        records.append(dict(scenario=row["scenario"],step=row["step"],recommendation_exact=True,gate_exact=True))
    assert len(records)==30
    for row in read_lines(traces):
        assert not controlled_target_evidence_failures(row)
        assert row["phase4b_visit_credit"]==0
        assert not row["visit_credit"] or row["focus_transition_status"]=="CONFIRMED_MOVED"
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p)] for p in paths)
    (args.out/"phase4b_controlled_replay.json").write_text(json.dumps(records,indent=2))
    summary=json.loads((args.out/"foundation/summary.json").read_text())
    summary.update(phase4b_controlled_exact=30,phase4b_sources=hashes,device_actions=0,production_ledger_mutations=0)
    (args.out/"summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))
    return 0

if __name__=="__main__": raise SystemExit(main())
