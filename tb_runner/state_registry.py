"""Phase 2C diagnostic registry and corruption-safe persistence.

No action selection, explored flag, traversal feedback, or navigation. Logical
IDs are allocated then persisted; fingerprints and coarse keys are not IDs.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json, canonical_json_bytes, canonical_sha256
from tb_runner.state_equality import (
    EQUALITY_SCHEMA, EqualityVerdict, StateIdentity, VerifiedScrollEvidence,
    _matching_nodes, evaluate_state_equality, scope_index_key,
)
from tb_runner.state_observation import OBSERVATION_SCHEMA, StateObservation, observation_problems

REGISTRY_SCHEMA = "state-registry-v1"
_PAYLOAD_FIELDS = frozenset({"schema_version", "equality_schema", "observation_schema", "namespace",
                           "next_state_sequence", "states", "observations", "continuities", "events"})


@dataclass(frozen=True)
class StateResolution:
    status: str
    state_id: str | None
    observation_id: str
    candidate_state_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    _evaluations_json: str = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return dict(status=self.status, state_id=self.state_id, observation_id=self.observation_id,
                    candidate_state_ids=list(self.candidate_state_ids), reasons=list(self.reasons),
                    equality_evidence=json.loads(self._evaluations_json))


def _validate_secondary(observation: StateObservation) -> None:
    fp, secondary = observation.fingerprint.to_dict(), observation.secondary
    for key, expected in (("nodes", fp["viewport"]["semantic_nodes"]),
                          ("markers", fp["core"]["screen_markers"]),
                          ("overlay_nodes", fp["overlay"]["semantic_nodes"])):
        actual = sorted((n["semantic"] for n in secondary[key]), key=canonical_json)
        if actual != sorted(expected, key=canonical_json):
            raise ValueError("secondary/fingerprint structure mismatch: " + key)
        for semantic in actual:
            flags = semantic.get("flags")
            if not isinstance(flags, dict) or any(v is not None and not isinstance(v, bool) for v in flags.values()):
                raise ValueError("invalid saved semantic flags")
            bounds = semantic.get("layout_bucket")
            if bounds is not None and (not isinstance(bounds, list) or len(bounds) != 4
                                       or any(type(v) is not int for v in bounds)):
                raise ValueError("invalid saved semantic geometry")


class StateRegistry:
    def __init__(self, namespace: str = "phase2-diagnostic"):
        if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", namespace):
            raise ValueError("invalid registry namespace")
        self.namespace = namespace
        self._next_state = 1
        self._states: dict[str, dict[str, Any]] = {}
        self._observations: dict[str, StateObservation] = {}
        self._continuities: dict[str, VerifiedScrollEvidence] = {}
        self._events: list[dict[str, Any]] = []
        self._extra_fields: dict[str, Any] = {}
        self._behavior_keys: dict[str, str] = {}

    @property
    def state_count(self) -> int:
        return len(self._states)

    @property
    def observation_count(self) -> int:
        return len(self._events)

    @property
    def unresolved_count(self) -> int:
        return sum(e["result"]["status"] == "UNRESOLVED" for e in self._events)

    @property
    def states(self) -> list[dict[str, Any]]:
        return deepcopy([self._states[k] for k in sorted(self._states)])

    def _behavior_key(self, observation: StateObservation) -> str:
        key = self._behavior_keys.get(observation.observation_id)
        if key is not None:
            return key
        fp, secondary = observation.fingerprint.to_dict(), observation.secondary
        return canonical_sha256(dict(core=fp["core"], viewport=fp["viewport"], overlay=fp["overlay"],
            coverage=observation.coverage, nodes=_matching_nodes(secondary["nodes"]), markers=secondary["markers"],
            overlay_nodes=secondary["overlay_nodes"], environment_partition=secondary.get("environment_partition")))

    def observe(self, observation: StateObservation,
                continuity: VerifiedScrollEvidence | None = None) -> StateResolution:
        if not isinstance(observation, StateObservation):
            raise TypeError("registry requires StateObservation")
        # Validate immutable serialized truth, not a caller-forged dataclass.
        observation = StateObservation.from_dict(observation.to_dict())
        _validate_secondary(observation)
        oid = observation.observation_id
        if oid in self._observations and self._observations[oid].to_json() != observation.to_json():
            raise ValueError("conflicting observation ID")
        proof_key = None
        if continuity is not None:
            known = dict(self._observations, **{oid: observation})
            continuity = VerifiedScrollEvidence.from_dict(continuity.to_dict(), known)
            if oid not in {continuity.before_observation_id, continuity.after_observation_id}:
                raise ValueError("continuity does not reference incoming observation")
            proof_key = canonical_sha256(continuity.to_dict())
        evaluations = []
        for sid in sorted(self._states):
            state = self._states[sid]
            member_ids = list(state["representative_observation_ids"])
            if continuity is not None:
                member_ids.extend(oid2 for oid2 in (continuity.before_observation_id, continuity.after_observation_id)
                                  if oid2 != oid and oid2 in state["observation_ids"])
            results = []
            for member_id in dict.fromkeys(member_ids):
                existing = self._observations[member_id]
                proof = continuity if continuity and continuity.links(existing, observation) else None
                if proof is None:
                    proof = next((p for p in self._continuities.values() if p.links(existing, observation)), None)
                results.append(evaluate_state_equality(existing, observation, proof).to_dict())
            verdicts = {r["verdict"] for r in results}
            if "SAME" in verdicts and "DIFFERENT" not in verdicts:
                verdict = "SAME"
            elif verdicts == {"DIFFERENT"}:
                verdict = "DIFFERENT"
            else:
                verdict = "AMBIGUOUS"
            evaluations.append(dict(state_id=sid, verdict=verdict, comparisons=results))
        same = [e["state_id"] for e in evaluations if e["verdict"] == "SAME"]
        ambiguous = [e["state_id"] for e in evaluations if e["verdict"] == "AMBIGUOUS"]
        problems = observation_problems(observation)
        candidate_ids = tuple(sorted(set(same + ambiguous)))
        state_id = None
        if problems:
            status, reasons = "UNRESOLVED", problems
        elif len(same) == 1 and not ambiguous:
            status, reasons, state_id = "REUSED", ("UNIQUE_OBSERVED_STATE_MATCH",), same[0]
        elif same or ambiguous:
            status, reasons = "UNRESOLVED", ("AMBIGUOUS_STATE_RESOLUTION",)
        else:
            status, reasons = "CREATED", ("NO_EXISTING_STATE" if not self._states else "DISTINCT_OBSERVED_STATE",)
            state_id = f"{self.namespace}:state:{self._next_state:08d}"
        result = StateResolution(status, state_id, oid, candidate_ids, tuple(sorted(reasons)), canonical_json(evaluations))
        # Mutate only after validation/evaluation finishes. Unknown observations
        # are retained without inventing a state or unsafe merge.
        self._observations[oid] = observation
        self._behavior_keys[oid] = self._behavior_key(observation)
        if proof_key is not None:
            self._continuities[proof_key] = continuity
        seen = dict(sequence=len(self._events)+1, timestamp=observation.fingerprint.to_dict()["transient"].get("timestamp"))
        if status == "CREATED":
            identity = StateIdentity(state_id, scope_index_key(observation))
            overlay_observed = observation.fingerprint.to_dict()["overlay"].get("observed") is True
            bases = [e["state_id"] for e in evaluations if overlay_observed and any(r["base_state_equal"] is True for r in e["comparisons"])
                     and not self._observations[self._states[e["state_id"]]["canonical_observation_id"]].fingerprint.to_dict()["overlay"].get("observed")]
            self._states[state_id] = dict(state_id=identity.state_id, identity_schema=identity.schema_version,
                scope_index_key=identity.scope_index_key, canonical_observation_id=oid,
                first_seen=seen, last_seen=seen, observation_count=0, observation_ids=[],
                representative_observation_ids=[], viewport_observations={}, scenario_context_provenance=[],
                base_state_id=bases[0] if len(bases)==1 else None)
            self._next_state += 1
        if state_id is not None:
            state = self._states[state_id]
            state["observation_count"] += 1
            state["last_seen"] = seen
            if oid not in state["observation_ids"]:
                state["observation_ids"].append(oid)
                metadata = observation.fingerprint.to_dict()["transient"]
                state["scenario_context_provenance"].append(dict(observation_id=oid,
                    scenario_id=metadata.get("scenario_id"), step=metadata.get("step"), source=metadata.get("source")))
            if self._behavior_keys[oid] not in {self._behavior_keys[r] for r in state["representative_observation_ids"]}:
                state["representative_observation_ids"].append(oid)
            vp = observation.fingerprint.viewport_signature
            entry = state["viewport_observations"].setdefault(vp, dict(viewport_signature=vp,
                first_seen=seen, last_seen=seen, observation_count=0, observation_ids=[]))
            entry["observation_count"] += 1
            entry["last_seen"] = seen
            if oid not in entry["observation_ids"]:
                entry["observation_ids"].append(oid)
        self._events.append(dict(sequence=len(self._events)+1, observation_id=oid,
                                 continuity_id=proof_key, result=result.to_dict()))
        return result

    def _payload(self) -> dict[str, Any]:
        return dict(self._extra_fields, schema_version=REGISTRY_SCHEMA, equality_schema=EQUALITY_SCHEMA,
                    observation_schema=OBSERVATION_SCHEMA, namespace=self.namespace,
                    next_state_sequence=self._next_state, states=self.states,
                    observations=[self._observations[k].to_dict() for k in sorted(self._observations)],
                    continuities=[dict(evidence_id=k, evidence=self._continuities[k].to_dict()) for k in sorted(self._continuities)],
                    events=deepcopy(self._events))

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        return dict(payload, content_sha256=canonical_sha256(payload))

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateRegistry":
        if not isinstance(value, Mapping):
            raise ValueError("registry must be a mapping")
        payload = {k: v for k, v in value.items() if k != "content_sha256"}
        if not _PAYLOAD_FIELDS <= payload.keys() or payload.get("schema_version") != REGISTRY_SCHEMA:
            raise ValueError("incompatible or incomplete registry schema")
        if payload.get("equality_schema") != EQUALITY_SCHEMA or payload.get("observation_schema") != OBSERVATION_SCHEMA:
            raise ValueError("incompatible registry contracts")
        if value.get("content_sha256") != canonical_sha256(payload):
            raise ValueError("registry checksum mismatch")
        if type(payload.get("next_state_sequence")) is not int or payload["next_state_sequence"] < 1:
            raise ValueError("invalid state sequence")
        if any(not isinstance(payload.get(k), list) for k in ("states", "observations", "continuities", "events")):
            raise ValueError("invalid registry collections")
        observations = {}
        for document in payload["observations"]:
            obs = StateObservation.from_dict(document)
            _validate_secondary(obs)
            if obs.observation_id in observations:
                raise ValueError("duplicate saved observation")
            observations[obs.observation_id] = obs
        proofs = {}
        for document in payload["continuities"]:
            if not isinstance(document, dict) or document.get("evidence_id") != canonical_sha256(document.get("evidence")):
                raise ValueError("invalid continuity checksum")
            proof = VerifiedScrollEvidence.from_dict(document["evidence"], observations)
            if document["evidence_id"] in proofs:
                raise ValueError("duplicate continuity evidence")
            proofs[document["evidence_id"]] = proof
        rebuilt = cls(payload["namespace"])
        for index, event in enumerate(payload["events"], 1):
            if not isinstance(event, dict) or type(event.get("sequence")) is not int or event["sequence"] != index:
                raise ValueError("invalid event sequence")
            try:
                obs = observations[event["observation_id"]]
                proof = proofs[event["continuity_id"]] if event.get("continuity_id") is not None else None
            except KeyError as exc:
                raise ValueError("orphan event reference") from exc
            result = rebuilt.observe(obs, proof)
            if result.to_dict() != event.get("result"):
                raise ValueError("saved resolution does not replay")
        known_expected = {k: payload[k] for k in _PAYLOAD_FIELDS}
        if rebuilt._payload() != known_expected:
            raise ValueError("registry state/count/reference invariants do not replay")
        # Forward fields at the envelope level are preserved, not executed.
        rebuilt._extra_fields = deepcopy({k: v for k, v in payload.items() if k not in _PAYLOAD_FIELDS})
        return rebuilt

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix="."+target.name+".", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(canonical_json_bytes(self.to_dict()))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @classmethod
    def load(cls, path: str | Path) -> "StateRegistry":
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate registry JSON key")
                result[key] = value
            return result
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("registry cannot be loaded") from exc
        return cls.from_dict(value)
