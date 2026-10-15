"""Offline Phase 5D-C replay over preserved B3 captures; never connects to ADB."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path.cwd()))

from talkback_lib.exact_node_protocol import build_target_descriptor, create_resolve_request, resolve_exact_request
from talkback_lib.node_reacquire import reacquire_node


TARGETS = {
    "serviceCardBody": "com.samsung.android.oneconnect:id/serviceCardBody",
    "monitorCardBody": "com.samsung.android.oneconnect:id/monitorCardBody",
    "monitorHeaderGroup": "com.samsung.android.oneconnect:id/monitorHeaderGroup",
    "Away": "com.samsung.android.oneconnect:id/shmBannerAwayButton",
    "Stay": "com.samsung.android.oneconnect:id/shmBannerStayButton",
    "Disarmed": "com.samsung.android.oneconnect:id/shmBannerDisarmedButton",
}


def load_capture(base: Path, label: str) -> tuple[dict, dict]:
    raw = json.loads((base / f"capture_{label}_raw.json").read_text(encoding="utf-8"))
    metadata = json.loads((base / f"capture_{label}_identity.json").read_text(encoding="utf-8"))["identityMetadata"]
    return raw, metadata


def find_identity_node(metadata: dict, resource_id: str) -> dict | None:
    matches = [node for node in metadata.get("nodes", [])
               if node.get("provenance", {}).get("fields", {}).get("resource_id", {}).get("value") == resource_id]
    return matches[0] if len(matches) == 1 else None


def pairwise_result(source: dict, destination: dict, resource_id: str) -> dict:
    old = find_identity_node(source, resource_id)
    new = find_identity_node(destination, resource_id)
    if old is None or new is None:
        return {"candidate_count": 0, "resolved": False, "reason": "TARGET_MISSING_OR_NONUNIQUE",
                "lineage_match": False, "child_structure_match": False, "action_set_match": False,
                "source_node_id_evidence": "NOT_AVAILABLE", "perform_action_called": False}
    decision = reacquire_node(source, old["node_local_id"], destination).to_dict()
    evaluations = decision.get("trace", {}).get("candidate_evaluations", [])
    selected = next((entry for entry in evaluations if entry.get("candidate_node_id") == decision.get("matched_node_id")), {})
    lineage = selected.get("lineage_comparison", {})
    children = selected.get("child_comparison", {})
    actions = selected.get("action_comparison", {})
    source_id = old.get("provenance", {}).get("fields", {}).get("source_node_id", {})
    fresh_id = new.get("provenance", {}).get("fields", {}).get("source_node_id", {})
    return {
        "candidate_count": decision.get("candidate_count", 0),
        "resolved": decision.get("status") in {"PROVEN", "STRONG_EQUIVALENT"},
        "reason": decision.get("reason_code"),
        "lineage_match": lineage.get("state") == "MATCH",
        "child_structure_match": children.get("state") == "MATCH",
        "action_set_match": actions.get("state") == "MATCH",
        "source_node_id_evidence": {"authorized": source_id, "fresh": fresh_id},
        "perform_action_called": False,
        "authorization_use": "NONE",
    }


def find_raw_path(raw: dict, resource_id: str, window_id: int) -> tuple[int, list[int], dict] | None:
    matches = []
    for window_index, window in enumerate(raw.get("windows", [])):
        if window.get("id") != window_id:
            continue
        def walk(node: dict, path: list[int]) -> None:
            if node.get("viewIdResourceName") == resource_id:
                matches.append((window_index, path, node))
            for index, child in enumerate(node.get("children", [])):
                walk(child, path + [index])
        if isinstance(window.get("root"), dict):
            walk(window["root"], [])
    return matches[0] if len(matches) == 1 else None


def helper_chain_replay(raw_b: dict, raw_c: dict, meta_a: dict, meta_b: dict, meta_c: dict,
                        target_name: str, resource_id: str) -> dict:
    authorized_snapshot = meta_a["snapshot"]["snapshot_id"]
    reacquire_snapshot = meta_b["snapshot"]["snapshot_id"]
    helper_snapshot = meta_c["snapshot"]["snapshot_id"]
    old = find_identity_node(meta_a, resource_id)
    reacquired = find_identity_node(meta_b, resource_id)
    path_info = find_raw_path(raw_b, resource_id, reacquired.get("window_id", {}).get("value")) if reacquired else None
    if old is None or reacquired is None or path_info is None:
        return {"candidate_count": 0, "resolved": False, "reason": "TARGET_MISSING_OR_NONUNIQUE",
                "lineage_match": False, "child_structure_match": False, "action_set_match": False,
                "source_node_id_evidence": "UNAVAILABLE", "perform_action_called": False}
    window_index, path, _node = path_info
    descriptor = build_target_descriptor(raw_b, window_index=window_index, child_indices=path,
                                         snapshot_id=reacquire_snapshot)
    window = raw_b["windows"][window_index]
    now = datetime.now(timezone.utc)
    request = create_resolve_request(
        descriptor,
        request_id=f"offline:{target_name}:{uuid.uuid4()}",
        transaction_id=f"offline-tx:{target_name}:{uuid.uuid4()}",
        permit_id=f"offline-permit:{target_name}:{uuid.uuid4()}",
        request_nonce=f"offline-nonce:{uuid.uuid4()}",
        ownership={"run_id": "preserved:B3", "scenario_id": "life_home_monitor_plugin",
                   "scenario_transaction_id": f"offline:{target_name}", "step_action_id": f"target:{target_name}",
                   "parent_action_id": None},
        authorized_snapshot_id=authorized_snapshot,
        helper_service_instance_id="preserved-helper-B3",
        host_session_id="offline-replay-only",
        source_request_id=f"capture:{reacquire_snapshot}",
        stop_epoch="offline-stop:0",
        created_at=now.isoformat(), expires_at=(now + timedelta(seconds=30)).isoformat(),
        window_type=window.get("type"),
    )
    helper = dict(raw_c)
    helper["snapshot_id"] = helper_snapshot
    ack = resolve_exact_request(request, helper)
    return {
        "candidate_count": ack["candidate_count"],
        "resolved": ack["resolved"],
        "reason": ack["failure_code"] or "STRONG_IDENTITY_MATCH",
        "lineage_match": ack["resolved"] and ack["identity_match_summary"]["matched"].count("lineage") == 1,
        "child_structure_match": ack["resolved"] and ack["identity_match_summary"]["matched"].count("child_structure") == 1,
        "action_set_match": ack["resolved"] and ack["identity_match_summary"]["matched"].count("action_set") == 1,
        "source_node_id_evidence": {"authorized": old.get("provenance", {}).get("fields", {}).get("source_node_id"),
                                    "python_reacquired": reacquired.get("provenance", {}).get("fields", {}).get("source_node_id"),
                                    "helper_resolved": ack.get("resolved_source_node_id"),
                                    "helper_provenance": ack.get("resolved_source_node_id_provenance")},
        "perform_action_called": ack["perform_action_called"],
        "authorization_use": "NONE",
        "request_id": request.request_id,
        "authorized_snapshot_id": authorized_snapshot,
        "reacquire_snapshot_id": reacquire_snapshot,
        "helper_validation_snapshot_id": helper_snapshot,
        "action_safety_proven": False,
    }


def cross_scenario_replay(summary_path: Path) -> list[dict]:
    document = json.loads(summary_path.read_text(encoding="utf-8"))
    output = []
    for scenario in document.get("cross_scenario_summary", []):
        nodes = scenario.get("nodes", [])
        if not nodes:
            output.append({"scenario": scenario.get("scenario"), "candidate_count": 0, "resolved": False,
                           "reason": "TARGET_NOT_FOUND", "perform_action_called": False})
            continue
        missing_resource = [node for node in nodes if not node.get("identity", {}).get("resource_id")]
        missing_actions = [node for node in nodes if node.get("source_actions") is None]
        reason = "METADATA_INCOMPLETE" if missing_resource or missing_actions else "TARGET_NOT_FOUND"
        output.append({"scenario": scenario.get("scenario"), "candidate_count": scenario.get("preserved_target_node_count", 0),
                       "resolved": False, "reason": reason,
                       "missing_resource_id": bool(missing_resource), "missing_action_provenance": bool(missing_actions),
                       "perform_action_called": False, "scenario_specific_rule": False})
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b3-dir", type=Path, required=True)
    parser.add_argument("--cross-scenario-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw, metadata = {}, {}
    for label in "ABC":
        raw[label], metadata[label] = load_capture(args.b3_dir, label)
    pairwise = {}
    for source, destination in (("A", "B"), ("B", "C"), ("A", "C")):
        pairwise[f"{source}_to_{destination}"] = {
            name: pairwise_result(metadata[source], metadata[destination], resource)
            for name, resource in TARGETS.items()
        }
    helper_chain = {
        name: helper_chain_replay(raw["B"], raw["C"], metadata["A"], metadata["B"], metadata["C"], name, resource)
        for name, resource in TARGETS.items()
    }
    report = {
        "schema": "phase5d_c_offline_resolve_only_replay_v1",
        "source": "preserved_5d_b3_captures",
        "live_device_used": False,
        "action_dispatch_used": False,
        "production_authority": False,
        "pairwise_5d_b_reacquire": pairwise,
        "helper_full_chain_A_to_B_to_C": helper_chain,
        "cross_scenario_replay": cross_scenario_replay(args.cross_scenario_summary),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "pairwise": {key: {name: value["resolved"] for name, value in pairs.items()} for key, pairs in pairwise.items()},
        "helper_chain": {name: {"resolved": row["resolved"], "reason": row["reason"], "candidate_count": row["candidate_count"]}
                         for name, row in helper_chain.items()},
        "cross_scenario": [{"scenario": row["scenario"], "resolved": row["resolved"], "reason": row["reason"]}
                           for row in report["cross_scenario_replay"]],
        "perform_action_called": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
