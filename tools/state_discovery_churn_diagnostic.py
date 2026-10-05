"""Persist both observations before comparing discovery behavior. No UI actions.

Classification is deliberately provisional: a hash difference is UNKNOWN until
its saved raw inputs, capability, equality and semantic diff explain the change.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json
from tb_runner.discovery_candidates import DiscoverySnapshot
from tb_runner.state_equality import VerifiedScrollEvidence, evaluate_state_equality
from tb_runner.state_observation import StateObservation

SOURCES = ("AUDIT_EXPECTED", "ACCESSIBILITY_TREE", "CURRENT_FOCUS", "SMART_NEXT",
           "SCROLL_CAPABILITY", "GLOBAL_NAV", "PLUGIN_NAVIGATION")
CLASSIFICATIONS = frozenset(("REAL_UI_AVAILABILITY_CHANGE", "VOLATILE_FIELD_LEAK",
    "ORDERING_NONDETERMINISM", "TIMING_RACE", "SOURCE_PRODUCER_RACE", "STATE_BINDING_DRIFT",
    "VIEWPORT_CHANGE", "SCROLL_CAPABILITY_CHANGE", "GLOBAL_NAV_CHANGE", "STALE_CANDIDATE_CHANGE",
    "SERIALIZATION_NONDETERMINISM", "DUPLICATE_DEDUP_INSTABILITY", "UNKNOWN",
    "NON_REPRODUCED_TRANSIENT", "STABLE", "PROVENANCE_ONLY"))
BEHAVIOR_FIELDS = ("candidate_id", "state_id", "binding_status", "action_kind", "target_identity",
                   "target_semantics", "eligibility", "safety_hint")


def _behavior(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {field: candidate[field] for field in BEHAVIOR_FIELDS}


def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".churn-", delete=False) as stream:
            name = stream.name
            stream.write((canonical_json(document)+"\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name is not None and Path(name).exists():
            Path(name).unlink()


def describe_churn(before: Mapping[str, Any], after: Mapping[str, Any], *,
                   continuity: VerifiedScrollEvidence | None = None) -> dict[str, Any]:
    """Diff behavior and each source independently; do not infer legitimacy."""
    a, b = before["snapshot"], after["snapshot"]
    left = {c["candidate_id"]: c for c in a["candidates"]}
    right = {c["candidate_id"]: c for c in b["candidates"]}
    if len(left) != len(a["candidates"]) or len(right) != len(b["candidates"]):
        raise ValueError("duplicate candidate IDs in evidence")
    changed = sorted(k for k in left.keys() & right.keys() if _behavior(left[k]) != _behavior(right[k]))
    source_delta = {}
    for source in sorted(set(SOURCES) | {s for c in [*left.values(), *right.values()] for s in c["source"]}):
        x = {k for k,c in left.items() if source in c["source"]}
        y = {k for k,c in right.items() if source in c["source"]}
        source_delta[source] = dict(ADDED=sorted(y-x), REMOVED=sorted(x-y),
            CHANGED=sorted(k for k in x & y if _behavior(left[k]) != _behavior(right[k])),
            PROVENANCE_CHANGED=sorted(k for k in x & y if left[k]["source"] != right[k]["source"] or left[k]["evidence"] != right[k]["evidence"]))
    equality = evaluate_state_equality(StateObservation.from_dict(before["state_observation"]),
        StateObservation.from_dict(after["state_observation"]), continuity).to_dict()
    hash_changed = a["candidate_set_hash"] != b["candidate_set_hash"]
    return dict(schema_version="candidate-churn-diff-v1", before_record_id=before["record_id"],
        after_record_id=after["record_id"], hash_changed=hash_changed,
        classification="UNKNOWN" if hash_changed else "STABLE", expected=None if hash_changed else True,
        same_state=a["state_id"] is not None and a["state_id"]==b["state_id"],
        same_viewport=a["viewport_signature"]==b["viewport_signature"],
        state_ids=[a["state_id"],b["state_id"]], fingerprint_hashes=[a["fingerprint_hash"],b["fingerprint_hash"]],
        viewport_signatures=[a["viewport_signature"],b["viewport_signature"]],
        candidate_set_hashes=[a["candidate_set_hash"],b["candidate_set_hash"]],
        equality=equality, ADDED=sorted(right.keys()-left.keys()),REMOVED=sorted(left.keys()-right.keys()),CHANGED=changed,
        semantic_diff=dict(added=[right[k] for k in sorted(right.keys()-left.keys())],
            removed=[left[k] for k in sorted(left.keys()-right.keys())],
            changed=[dict(candidate_id=k,before=left[k],after=right[k]) for k in changed]),
        source_delta=source_delta, raw_capability_changed=before["raw_observation"].get("capability")!=after["raw_observation"].get("capability"),
        continuity=continuity.to_dict() if continuity else None)


class ChurnEvidenceRecorder:
    """New run directory required. Failed comparisons leave both durable files."""
    def __init__(self, directory: str | Path):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        if any(self.directory.iterdir()):
            raise ValueError("churn run directory must be empty")
        self.records: list[dict[str, Any]]=[]
        self.pairs: list[dict[str, Any]]=[]

    def record(self, raw: Mapping[str, Any], observation: StateObservation, snapshot: DiscoverySnapshot, *,
               producer_input: Mapping[str, Any] | None = None, phase: str = "passive") -> str:
        record_id=f"observation-{len(self.records)+1:04d}"
        doc=dict(schema_version="candidate-churn-observation-v1",record_id=record_id,phase=phase,
            raw_observation=deepcopy(dict(raw)),producer_input=deepcopy(dict(producer_input or {})),
            state_observation=observation.to_dict(),snapshot=snapshot.to_dict(),
            candidate_ids=sorted(c.candidate_id for c in snapshot.candidates))
        if observation.observation_id != doc["snapshot"]["observation_id"]:
            raise ValueError("snapshot/observation mismatch")
        path=self.directory/(record_id+".json")
        _atomic_json(path,doc)
        self.records.append(dict(record_id=record_id,file=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),phase=phase,state_id=snapshot.state_id))
        _atomic_json(self.directory/'records.json',dict(records=self.records))
        return record_id

    def _load(self, record_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        reference=next(r for r in self.records if r["record_id"]==record_id)
        payload=(self.directory/reference["file"]).read_bytes()
        if hashlib.sha256(payload).hexdigest()!=reference["sha256"]:
            raise ValueError("evidence checksum mismatch")
        return json.loads(payload),deepcopy(reference)

    def compare(self, before_id: str, after_id: str, *, continuity: VerifiedScrollEvidence | None = None) -> Path:
        before,ref_before=self._load(before_id);after,ref_after=self._load(after_id)
        doc=describe_churn(before,after,continuity=continuity)
        doc['evidence_references']=dict(before=ref_before,after=ref_after)
        path=self.directory/(f"candidate_churn_diff-{len(self.pairs)+1:04d}.json")
        _atomic_json(path,doc)
        self.pairs.append(dict(file=path.name,before=before_id,after=after_id,hash_changed=doc['hash_changed']))
        _atomic_json(self.directory/'pairs.json',dict(pairs=self.pairs))
        return path

    def classify(self, path: Path, classification: str, *, expected: bool, rationale: str) -> None:
        if classification not in CLASSIFICATIONS or not rationale or not isinstance(expected,bool):
            raise ValueError("classification requires reviewed rationale and expectation")
        doc=json.loads(path.read_text(encoding='utf-8'))
        doc.update(classification=classification,expected=expected,rationale=rationale)
        _atomic_json(path,doc)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--after',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    before=json.loads(args.before.read_text(encoding='utf-8'));after=json.loads(args.after.read_text(encoding='utf-8'))
    _atomic_json(args.output,describe_churn(before,after))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
