"""Opt-in current-state discovery snapshots; never selects or executes actions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tb_runner.discovery_candidates import (
    build_discovery_snapshot, build_fingerprint_only_snapshot, write_discovery_snapshot,
)
from tb_runner.state_registry import StateRegistry


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input",type=Path,help="One saved raw observation or a list")
    source.add_argument("--fingerprint-input",type=Path,help="Insufficient secondary evidence; unresolved snapshot")
    source.add_argument("--capture",action="store_true",help="Observe current screen only")
    parser.add_argument("--serial")
    parser.add_argument("--scenario-id",default="discovery_diagnostic")
    parser.add_argument("--registry-in",type=Path)
    parser.add_argument("--registry-out",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--producer-input",type=Path,help="Optional Audit inventory / scoped lifecycle output")
    args=parser.parse_args()
    registry=StateRegistry.load(args.registry_in) if args.registry_in else StateRegistry("phase3-diagnostic")
    producers=json.loads(args.producer_input.read_text(encoding="utf-8")) if args.producer_input else {}
    if args.capture:
        from talkback_lib import A11yAdbClient
        from tools.state_fingerprint_diagnostic import capture_observation
        raw=capture_observation(A11yAdbClient(start_monitor=False),args.serial,scenario_id=args.scenario_id)
    else:
        raw=json.loads((args.input or args.fingerprint_input).read_text(encoding="utf-8"))
    values=raw if isinstance(raw,list) else [raw]
    counts={"snapshots":0,"resolved":0,"unresolved":0,"candidates":0,"candidate_id_collisions":0}
    for value in values:
        snapshot=build_fingerprint_only_snapshot(value,registry) if args.fingerprint_input else build_discovery_snapshot(
            value,registry,audit_inventory=producers.get("audit_inventory"),lifecycle_records=producers.get("lifecycle_records"))
        write_discovery_snapshot(args.output,snapshot)
        counts["snapshots"]+=1
        counts["resolved" if snapshot.state_id else "unresolved"]+=1
        counts["candidates"]+=len(snapshot.candidates)
        counts["candidate_id_collisions"]+=snapshot.to_dict()["candidate_id_collision_count"]
    registry.save(args.registry_out)
    print(json.dumps(dict(**counts,auto_activation=False,visit_credit=0)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
