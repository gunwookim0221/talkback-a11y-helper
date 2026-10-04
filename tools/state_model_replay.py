"""Explicit offline Phase 2D replay; never connects to ADB or activates UI."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

from tb_runner.canonical_json import canonical_json_bytes
from tb_runner.state_registry import StateRegistry
from tb_runner.state_replay import MANIFEST_SCHEMA, SUITE_SCHEMA, replay_dataset


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--registry-in",type=Path)
    parser.add_argument("--registry-out",type=Path,required=True)
    parser.add_argument("--report-out",type=Path,required=True)
    args=parser.parse_args()
    value=json.loads(args.manifest.read_text(encoding="utf-8"))
    is_suite=value.get("schema_version")==SUITE_SCHEMA
    datasets=value.get("datasets") if is_suite else [value]
    if not isinstance(datasets,list) or not datasets:
        raise ValueError("empty replay suite")
    names=set()
    reports=[]
    for dataset in datasets:
        name=dataset.get("name","")
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}",name) or name in names:
            raise ValueError("invalid/duplicate dataset name")
        names.add(name)
        source=args.registry_in/(name+".json") if args.registry_in and is_suite else args.registry_in
        destination=args.registry_out/(name+".json") if is_suite else args.registry_out
        loaded=StateRegistry.load(source) if source else None
        report,registry=replay_dataset(dataset,loaded)
        registry.save(destination)
        reports.append(report)
    metrics={key:sum(r["metrics"][key] for r in reports) for key in reports[0]["metrics"]}
    verdict="FAIL" if any(r["verdict"]=="FAIL" for r in reports) else "PASS_WITH_LIMITATIONS" if metrics["AMBIGUOUS_CASES"] else "PASS"
    output=dict(schema_version="state-replay-suite-report-v1",verdict=verdict,metrics=metrics,datasets=reports)
    args.report_out.parent.mkdir(parents=True,exist_ok=True)
    args.report_out.write_bytes(canonical_json_bytes(output))
    print(json.dumps(dict(verdict=verdict,**metrics)))
    return 1 if verdict=="FAIL" else 0


if __name__=="__main__":
    raise SystemExit(main())
