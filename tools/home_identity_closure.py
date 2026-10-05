"""Opt-in passive identity evidence and pairwise RCA; never executes UI actions.

Raw normalized trees are saved once per bundle, with no duplicated raw XML.
Diagnostic comparisons never grant identity or action/visit credit.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.state_equality import _matching_nodes, evaluate_state_equality
from tb_runner.state_observation import StateObservation, build_state_observation, observation_problems
from tb_runner.state_registry import StateRegistry


def _delta(left, right):
    a, b = Counter(map(canonical_json, left)), Counter(map(canonical_json, right))
    return {name: [dict(value=json.loads(k), count=n) for k, n in sorted(values.items())]
            for name, values in (("REMOVED", a-b), ("ADDED", b-a))}


def _physical_candidates(snapshot):
    # Remove only binding/epoch IDs, preserving actual position and semantics.
    result = []
    for candidate in snapshot["candidates"]:
        target = {k: v for k, v in candidate["target_identity"].items() if k != "instance_id"}
        result.append(dict(action_kind=candidate["action_kind"], target=target,
                           semantics=candidate["target_semantics"], eligibility=candidate["eligibility"],
                           safety=candidate["safety_hint"]))
    return sorted(result, key=canonical_json)


def _source_candidates(snapshot):
    groups = {}
    for c in snapshot["candidates"]:
        for source in c["source"]:
            groups.setdefault(source, []).append(dict(kind=c["action_kind"],
                target={k:v for k,v in c["target_identity"].items() if k != "instance_id"},
                semantics=c["target_semantics"]))
    return groups


def _source_delta(left, right):
    def keyed(values):
        return {canonical_json(dict(kind=v["kind"],target=v["target"])):v for v in values}
    a,b=keyed(left),keyed(right)
    return dict(ADDED=[b[k] for k in sorted(b.keys()-a.keys())],
                REMOVED=[a[k] for k in sorted(a.keys()-b.keys())],
                CHANGED=[dict(before=a[k],after=b[k]) for k in sorted(a.keys() & b.keys()) if a[k]!=b[k]])


def _control_state(nodes):
    return sorted([dict(instance={k:n["semantic"].get(k) for k in ("resource_id","class_name","role","layout_bucket")},
        value=n.get("semantic_value"), state=n["semantic"].get("semantic_state"),
        description=n["semantic"].get("state_description"),
        flags={k:n["semantic"].get("flags",{}).get(k) for k in ("enabled","checked","selected")})
        for n in nodes if (n.get("semantic_value") is not None
            or n["semantic"].get("semantic_state") is not None or n["semantic"].get("state_description") is not None
            or n["semantic"].get("flags",{}).get("enabled") is False
            or any(n["semantic"].get("flags",{}).get(k) is True for k in ("clickable","focusable","checked","selected")))],key=canonical_json)


def pair_diff(left, right):
    a, b = (StateObservation.from_dict(x["observation"]) for x in (left, right))
    af, bf = a.fingerprint.to_dict(), b.fingerprint.to_dict()
    secondary_delta = _delta(a.secondary["nodes"], b.secondary["nodes"])
    projection_delta = _delta(_matching_nodes(a.secondary["nodes"]), _matching_nodes(b.secondary["nodes"]))
    physical_delta = _delta(_physical_candidates(left["snapshot"]), _physical_candidates(right["snapshot"]))
    lc, rc = _source_candidates(left["snapshot"]), _source_candidates(right["snapshot"])
    sources = {s: _source_delta(lc.get(s, []), rc.get(s, [])) for s in sorted(lc.keys() | rc.keys())}
    differences = {
        "CORE": af["core"] != bf["core"], "SECONDARY": a.secondary["nodes"] != b.secondary["nodes"],
        "VIEWPORT": af["viewport"] != bf["viewport"], "OVERLAY": af["overlay"] != bf["overlay"],
        "TRANSIENT": af["transient"] != bf["transient"],
        "ACTIVITY_CONTEXT": any(af["core"][k] != bf["core"][k] for k in ("package_name", "activity_name", "navigation_context")),
        "OBSERVATION_COMPLETENESS": a.coverage != b.coverage or observation_problems(a) != observation_problems(b),
        "NODE_SET": bool(secondary_delta["ADDED"] or secondary_delta["REMOVED"]),
        "CANDIDATE_SET": left["snapshot"]["candidate_set_hash"] != right["snapshot"]["candidate_set_hash"],
        "CANDIDATE_SOURCE": any(v["ADDED"] or v["REMOVED"] or v["CHANGED"] for v in sources.values()),
        "SEMANTIC_CONTROL_STATE": _control_state(a.secondary["nodes"]) != _control_state(b.secondary["nodes"]),
    }
    classifications = []
    if differences["TRANSIENT"]:
        classifications.append(dict(component="TRANSIENT", kind="VOLATILE_FIELD", detail="capture timestamp/step/raw digest/focus diagnostics; preserved outside logical identity"))
    if differences["SECONDARY"]:
        classifications.append(dict(component="SECONDARY", kind="LABEL_ONLY_VARIATION" if not differences["VIEWPORT"] else "UNKNOWN",
                                    detail=secondary_delta, comparison_projection_delta=projection_delta))
    if differences["CANDIDATE_SET"]:
        empty = not physical_delta["ADDED"] and not physical_delta["REMOVED"]
        classifications.append(dict(component="CANDIDATE_SET", kind="VOLATILE_FIELD" if empty else "CANDIDATE_PRODUCER_VARIATION",
            detail="unresolved observation-scoped IDs" if empty else physical_delta))
    if differences["CANDIDATE_SOURCE"]:
        classifications.append(dict(component="CANDIDATE_SOURCE", kind="CANDIDATE_PRODUCER_VARIATION", detail=sources))
    for component, kind in (("CORE", "UNKNOWN"), ("ACTIVITY_CONTEXT", "WINDOW_CONTEXT_CHANGE"),
                            ("VIEWPORT", "VIEWPORT_CHANGE"), ("OVERLAY", "OVERLAY_CHANGE"),
                            ("OBSERVATION_COMPLETENESS", "PARTIAL_OBSERVATION")):
        if differences[component]: classifications.append(dict(component=component, kind=kind))
    return dict(record_type="HOME_OBSERVATION_PAIR_DIFF", left=left["index"], right=right["index"],
                equality=evaluate_state_equality(a, b).to_dict(), differences=differences,
                secondary_delta=secondary_delta, candidate_physical_delta=physical_delta,
                candidate_source_delta=sources, classifications=classifications)


def summarize(bundles, pairs):
    states = {b["snapshot"]["state_id"] for b in bundles if b["snapshot"]["state_id"]}
    resolved = sum(b["snapshot"]["state_id"] is not None for b in bundles)
    unexpected_churn = sum(p["equality"]["verdict"] == "SAME" and
        bundles[p["left"]-1]["snapshot"]["state_id"] is not None and
        bundles[p["left"]-1]["snapshot"]["state_id"] == bundles[p["right"]-1]["snapshot"]["state_id"] and
        bool(p["candidate_physical_delta"]["ADDED"] or p["candidate_physical_delta"]["REMOVED"])
        for p in pairs)
    unsafe = sum(p["equality"]["verdict"] != "SAME" and
        bundles[p["left"]-1]["snapshot"]["state_id"] is not None and
        bundles[p["left"]-1]["snapshot"]["state_id"] == bundles[p["right"]-1]["snapshot"]["state_id"] for p in pairs)
    return dict(HOME_OBSERVATIONS_TOTAL=len(bundles), HOME_RESOLVED_COUNT=resolved,
        HOME_UNRESOLVED_COUNT=len(bundles)-resolved, HOME_UNIQUE_LOGICAL_STATE_COUNT=len(states),
        HOME_UNSAFE_MERGE_COUNT=unsafe, HOME_UNEXPECTED_SPLIT_COUNT=sum(p["equality"]["verdict"] == "SAME" and
            all(bundles[p[k]-1]["snapshot"]["state_id"] for k in ("left", "right")) and
            bundles[p["left"]-1]["snapshot"]["state_id"] != bundles[p["right"]-1]["snapshot"]["state_id"] for p in pairs),
        HOME_CORE_VARIATION_COUNT=max(0, len({b["observation"]["fingerprint"]["core_signature"] for b in bundles})-1),
        HOME_SECONDARY_VARIATION_COUNT=max(0, len({canonical_sha256(b["observation"]["secondary"]["nodes"]) for b in bundles})-1),
        HOME_CANDIDATE_UNEXPECTED_CHURN_COUNT=unexpected_churn,
        candidate_id_collision_count=sum(b["snapshot"]["candidate_id_collision_count"] for b in bundles),
        pair_count=len(pairs), pair_verdicts=dict(Counter(p["equality"]["verdict"] for p in pairs)),
        candidate_physical_variants=len({canonical_sha256(_physical_candidates(b["snapshot"])) for b in bundles}))


def capture_passive(client, serial, registry, output, count=21):
    from tools.state_fingerprint_diagnostic import capture_observation
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    registry.save(output / "registry_seed.json")
    bundles = []
    for index in range(1, count+1):
        mode = ("immediate", "short_stabilization", "existing_helper_ready")[(index-1) % 3]
        if mode == "short_stabilization": time.sleep(.45)  # existing matrix settle interval
        if mode == "existing_helper_ready" and not client.check_helper_status(dev=serial):
            raise RuntimeError("existing Helper readiness check failed")
        started = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()
        raw = capture_observation(client, serial, scenario_id="home-identity-closure", step=index)
        elapsed = (time.perf_counter()-t0)*1000
        observation = build_state_observation(raw)
        if (raw.get("selected_tab") or {}).get("name") != "home":
            raise RuntimeError("Home must already be selected; passive collector cannot navigate")
        snapshot = build_discovery_snapshot(raw, registry)
        event = registry.to_dict()["events"][-1]
        window = client._run(["shell", "dumpsys", "window", "windows"], dev=serial, timeout=8)
        window_summary = [line.strip() for line in window.splitlines() if re.search(r"mCurrentFocus=|mFocusedApp=", line)]
        resources = Counter(str(n.get("viewIdResourceName") or "") for n in raw["nodes"])
        bundle = dict(index=index, timing_mode=mode, started_at=started, capture_ms=elapsed,
            raw=raw, observation=observation.to_dict(), snapshot=snapshot.to_dict(),
            registry_resolution=event["result"], root_window_identity=dict(window=window_summary,
                root_nodes=[{k:n.get(k) for k in ("viewIdResourceName", "className", "boundsInScreen", "stable_node_path")}
                            for n in raw["nodes"][:2]]),
            completeness=dict(coverage=observation.coverage, problems=list(observation_problems(observation)),
                node_count=len(raw["nodes"]), resource_counts=dict(sorted(resources.items())),
                selected_navigation=raw.get("selected_tab"), scroll_container=raw.get("capability", {}).get("container")),
            candidate_source_breakdown={k:len(v) for k,v in _source_candidates(snapshot.to_dict()).items()},
            actions_executed=0, visit_credit=0)
        bundles.append(bundle)
        (output/f"observation_{index:03d}.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(dict(index=index, timing=mode, state_id=snapshot.state_id, nodes=len(raw["nodes"]),
            candidates=len(snapshot.candidates), capture_ms=round(elapsed, 1))), flush=True)
    pairs = [pair_diff(a,b) for i,a in enumerate(bundles) for b in bundles[i+1:]]
    (output/"pairs.jsonl").write_text("".join(canonical_json(p)+"\n" for p in pairs), encoding="utf-8")
    summary = summarize(bundles,pairs)
    (output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    registry.save(output/"registry_after.json")
    print(json.dumps(summary), flush=True)
    return bundles, summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--registry-in", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=21)
    args=parser.parse_args()
    if args.count < 20: parser.error("closure requires at least 20 passive observations")
    from talkback_lib import A11yAdbClient
    capture_passive(A11yAdbClient(start_monitor=False),args.serial,StateRegistry.load(args.registry_in),args.output,args.count)


if __name__ == "__main__": main()
