"""Phase 2D offline composition/oracle checks. No device or action executor."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.state_equality import VerifiedScrollEvidence, evaluate_state_equality
from tb_runner.state_observation import (
    OBSERVATION_SCHEMA, SECONDARY_VERSION, StateObservation,
    build_state_observation, fingerprint_from_dict,
)
from tb_runner.state_registry import StateRegistry

MANIFEST_SCHEMA = "state-replay-manifest-v1"
SUITE_SCHEMA = "state-replay-suite-v1"


def _fingerprint_only(value: Mapping[str, Any]) -> StateObservation:
    """Preserve available structure without inventing missing secondary labels.

    Coverage UNOBSERVED means unavailable equality observation, not a claim
    that the serialized fingerprint had an empty tree. It cannot resolve state.
    """
    fp = fingerprint_from_dict(value)
    data = fp.to_dict()
    def nodes(items):
        return [dict(semantic=n, label=n.get("text_fallback") or "", semantic_value=n.get("semantic_state")) for n in items]
    secondary = dict(version=SECONDARY_VERSION, nodes=nodes(data["viewport"]["semantic_nodes"]),
        markers=nodes(data["core"]["screen_markers"]), overlay_nodes=nodes(data["overlay"]["semantic_nodes"]),
        semantic_substates=[],
        environment_partition=None, locale=None, source="fingerprint_only_secondary_unavailable")
    doc = dict(schema_version=OBSERVATION_SCHEMA, fingerprint=data, coverage="UNOBSERVED", secondary=secondary)
    return StateObservation.from_dict(dict(doc, observation_id=canonical_sha256(doc)))


def replay_dataset(manifest: Mapping[str, Any], registry: StateRegistry | None = None) -> tuple[dict[str, Any], StateRegistry]:
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("incompatible replay manifest")
    name = manifest.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("missing replay name")
    sources = manifest.get("observations")
    expected = manifest.get("expected_groups")
    if not isinstance(sources, list) or not sources or not isinstance(expected, dict):
        raise ValueError("replay needs source observations and reviewed expected groups")
    observations, stable, source_modes = {}, {}, {}
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("key"), str) or not source["key"]:
            raise ValueError("invalid replay source")
        key = source["key"]
        modes = [k for k in ("raw", "observation", "fingerprint") if k in source]
        if key in observations or len(modes) != 1:
            raise ValueError("duplicate or ambiguous replay source")
        mode = modes[0]
        loader = {"raw": build_state_observation, "observation": StateObservation.from_dict,
                  "fingerprint": _fingerprint_only}[mode]
        obs, again = loader(source[mode]), loader(source[mode])
        observations[key] = obs
        stable[key] = obs.fingerprint.to_json() == again.fingerprint.to_json() and obs.to_json() == again.to_json()
        source_modes[key] = mode
    if set(expected) != set(observations) or any(v is not None and not isinstance(v,str) for v in expected.values()):
        raise ValueError("expected groups must cover every source; null means unresolved")
    order = manifest.get("registration_order", list(observations))
    if not isinstance(order, list) or not order or any(key not in observations for key in order) or set(order) != set(observations):
        raise ValueError("invalid registration order")
    by_id = {obs.observation_id: obs for obs in observations.values()}
    proofs = []
    for source in manifest.get("continuities", []):
        if "evidence" in source:
            proof = VerifiedScrollEvidence.from_dict(source["evidence"],by_id)
        else:
            try:
                proof = VerifiedScrollEvidence.from_transition(observations[source["before"]],
                    observations[source["after"]],source["transition"])
            except KeyError as exc:
                raise ValueError("orphan replay continuity") from exc
        proofs.append(proof)
    pairs = manifest.get("pairs", [])
    if not isinstance(pairs,list):
        raise ValueError("pairs must be a list")
    pair_rows, failures = [], []
    equality_stable, ambiguous_pairs = 0, 0
    namespace=manifest.get("namespace",name)
    primary=registry if registry is not None else StateRegistry(namespace)
    if primary.namespace != namespace:
        raise ValueError("registry namespace mismatch")
    for pair in pairs:
        try:
            a,b=observations[pair["left"]],observations[pair["right"]]
        except (KeyError,TypeError) as exc:
            raise ValueError("orphan replay equality pair") from exc
        if pair.get("expected") not in {"SAME","DIFFERENT","AMBIGUOUS"}:
            raise ValueError("unreviewed equality expectation")
        proof=next((p for p in proofs if p.links(a,b)),None) if pair.get("use_continuity") is True else None
        result=evaluate_state_equality(a,b,proof,matching_policy=primary.matching_policy)
        restored_a,restored_b=StateObservation.from_dict(a.to_dict()),StateObservation.from_dict(b.to_dict())
        restored_proof=VerifiedScrollEvidence.from_dict(proof.to_dict(),by_id) if proof else None
        stable_result=result.to_json()==evaluate_state_equality(restored_a,restored_b,restored_proof,
            matching_policy=primary.matching_policy).to_json()
        equality_stable+=stable_result
        ambiguous_pairs+=result.verdict.value=="AMBIGUOUS"
        passed=result.verdict.value==pair["expected"] and stable_result
        if "viewport_equal" in pair:
            if type(pair["viewport_equal"]) is not bool:
                raise ValueError("viewport oracle must be bool")
            passed=passed and result.viewport_equal is pair["viewport_equal"]
        pair_rows.append(dict(name=pair.get("name"),expected=pair["expected"],passed=passed,result=result.to_dict()))
        if not passed: failures.append("equality:"+str(pair.get("name")))

    def run(target):
        seen_ids={o["observation_id"] for o in target.to_dict()["observations"]}
        results=[]
        for key in order:
            obs=observations[key]
            proof=next((p for p in proofs if obs.observation_id in (p.before_observation_id,p.after_observation_id)
                and ({p.before_observation_id,p.after_observation_id}-{obs.observation_id}) <= seen_ids),None)
            resolution=target.observe(obs,proof)
            results.append(resolution)
            seen_ids.add(obs.observation_id)
        return results

    primary_rows=run(primary)
    restarted=StateRegistry.from_dict(primary.to_dict(),matching_policy=primary.matching_policy)
    persistence_stable=restarted.to_json()==primary.to_json()
    restarted_rows=run(restarted)
    registry_stable=0
    group_ids=defaultdict(set)
    unresolved_rows,unsafe_resolutions,unexpected_unresolved=0,0,0
    resolution_rows=[]
    for key,first,second in zip(order,primary_rows,restarted_rows):
        stable_resolution=(first.state_id==second.state_id and (first.status=="UNRESOLVED")== (second.status=="UNRESOLVED"))
        registry_stable+=stable_resolution
        group=expected[key]
        if first.status=="UNRESOLVED": unresolved_rows+=1
        if group is None and first.state_id is not None: unsafe_resolutions+=1
        if group is not None:
            if first.state_id is None: unexpected_unresolved+=1
            else: group_ids[group].add(first.state_id)
        resolution_rows.append(dict(key=key,expected_group=group,status=first.status,state_id=first.state_id,
                                    restart_status=second.status,restart_state_id=second.state_id,stable=stable_resolution))
    collisions=0
    groups=sorted(group_ids)
    for i,group in enumerate(groups):
        for other in groups[i+1:]:
            collisions+=bool(group_ids[group] & group_ids[other])
    splits=sum(max(0,len(ids)-1) for ids in group_ids.values())
    metrics=dict(TOTAL_REPLAY_CASES=len(order),FINGERPRINT_STABLE=sum(stable[key] for key in order),
        EQUALITY_CASE_COUNT=len(pairs),EQUALITY_STABLE=equality_stable,
        REGISTRY_RESOLUTION_STABLE=registry_stable,STATE_COLLISIONS=collisions,
        UNSAFE_MERGES=unsafe_resolutions+collisions,UNEXPECTED_STATE_SPLITS=splits,
        AMBIGUOUS_CASES=unresolved_rows,AMBIGUOUS_EQUALITY_PAIRS=ambiguous_pairs,
        UNEXPECTED_UNRESOLVED=unexpected_unresolved,FINGERPRINT_ONLY_CASES=sum(source_modes[k]=="fingerprint" for k in order))
    if not persistence_stable: failures.append("persistence_roundtrip")
    if metrics["FINGERPRINT_STABLE"] != len(order): failures.append("fingerprint_instability")
    if registry_stable != len(order): failures.append("restart_resolution_instability")
    if any(metrics[k] for k in ("STATE_COLLISIONS","UNSAFE_MERGES","UNEXPECTED_STATE_SPLITS","UNEXPECTED_UNRESOLVED")):
        failures.append("registry_oracle_mismatch")
    verdict="FAIL" if failures else "PASS_WITH_LIMITATIONS" if unresolved_rows else "PASS"
    report=dict(schema_version="state-replay-report-v1",name=name,verdict=verdict,metrics=metrics,
        fingerprint_stable_scope="StateFingerprint and StateObservation canonical payloads; not record envelopes",
        registry_resolution_scope="persistent state_id and unresolved status; CREATED becomes REUSED on restart",
        persistence_roundtrip=persistence_stable,registry_state_count=primary.state_count,
        pairs=pair_rows,resolutions=resolution_rows,failures=failures)
    return report,primary
