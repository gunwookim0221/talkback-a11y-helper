"""Replay saved, externally controlled actions; no action execution or ADB."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tb_runner.state_registry import StateRegistry
from tb_runner.transition_observation import TransitionObserver, write_transition


def replay(values: list[dict], registry: StateRegistry):
    observer = TransitionObserver(registry)
    records = []
    for value in values:
        source = observer.prepare(value["before_raw"], value["action"], action_started_at=value.get("action_started_at"))
        records.append(observer.complete(source, value.get("after_raw"), command_ack=value.get("command_ack"),
            action_evidence=value.get("action_evidence"), action_finished_at=value.get("action_finished_at"),
            evidence_refs=value.get("evidence_refs")))
    return records, observer.metrics()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSON list of saved controlled action brackets")
    parser.add_argument("--registry-in", type=Path)
    parser.add_argument("--registry-out", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New JSONL file; existing artifacts are not overwritten")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    registry = StateRegistry.load(args.registry_in) if args.registry_in else StateRegistry("phase3b-diagnostic")
    values = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        parser.error("input must be a list")
    records, metrics = replay(values, registry)
    seen = set()
    for record in records:
        if record.transition_id not in seen:
            write_transition(args.output, record)
            seen.add(record.transition_id)
    registry.save(args.registry_out)
    print(json.dumps(metrics, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
