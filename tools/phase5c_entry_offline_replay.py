"""Replay preserved Phase 5C entry evidence without touching a device."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re

from talkback_lib.hierarchy_snapshot import legacy_scroll_nodes
from tb_runner.entry_safety import (_bounds, _walk, authorize_entry, classify_post_open,
    click_events, hierarchy_digest, resolve_navigation_owner, verify_actual_hit)


CHUNK = re.compile(r"DUMP_HIERARCHY_RESULT_CHUNK reqId=(\S+) index=(\d+) count=(\d+) sha256=(\w+) payload=(\S+)")
SELECT = re.compile(r"\[XMLENTRY\]\[select\].*?resource='([^']*)'.*?bounds='([^']+)'.*?matched_phrase='([^']+)'.*?tap_point='(\d+),(\d+)'")


def _replay_source(folder: Path):
    select_line = next(line for line in (folder / "runner.log").open(encoding="utf-8", errors="replace")
                       if "[XMLENTRY][select]" in line)
    match = SELECT.search(select_line)
    if not match:
        raise ValueError(f"Entry selection was not parseable: {folder}")
    resource, bounds, phrase, x, y = match.groups()
    tap = (int(x), int(y))
    groups, order = {}, []
    for line in (folder / "logcat.txt").open(encoding="utf-8", errors="replace"):
        chunk = CHUNK.search(line)
        if chunk:
            request, index, count, sha, payload = chunk.groups()
            if request not in groups:
                groups[request] = dict(count=int(count), sha=sha, chunks={})
                order.append(request)
            groups[request]["chunks"][int(index)] = payload
        if f"input tap {tap[0]} {tap[1]}" in line:
            break
    snapshot = None
    request_id = None
    for request in reversed(order):
        group = groups[request]
        if len(group["chunks"]) != group["count"]:
            continue
        raw = b"".join(base64.b64decode(group["chunks"][i]) for i in range(group["count"]))
        if hashlib.sha256(raw).hexdigest() != group["sha"]:
            continue
        snapshot = json.loads(raw)
        request_id = request
        break
    if snapshot is None:
        raise ValueError(f"No hash-verified pre-entry hierarchy: {folder}")
    roots = [{"children": legacy_scroll_nodes(snapshot), "boundsInScreen": "0,0,1,1"}]
    geometry = tuple(map(int, re.findall(r"\d+", bounds)))
    matching = [(node, ancestors) for node, ancestors in _walk(roots)
                if node.get("clickable") and _bounds(node) == geometry
                and str(node.get("viewIdResourceName") or "") == resource]
    if not matching:
        raise ValueError(f"Selected target absent from preserved hierarchy: {folder}")
    matching.sort(key=lambda pair: len(pair[1]))
    selected = matching[0][0]
    return roots, selected, phrase, tap, request_id


def replay(evidence_path: Path):
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    source = evidence_path.parents[2]
    failed_folder = source / "out/phase5c_clothing_care_rca_20261014/full32/31_life_home_monitor_plugin"
    roots, selected, phrase, old_tap, request = _replay_source(failed_folder)
    resolution = resolve_navigation_owner(roots, selected, phrase)
    permit = authorize_entry(resolution, roots, scenario="life_home_monitor_plugin", matched_phrase=phrase)
    click_line = evidence["wrong_security_click"][0]["text"]
    event_id = re.search(r"EventTime: (\d+)", click_line).group(1)
    event_fragment = []
    for line in (failed_folder / "logcat.txt").open(encoding="utf-8", errors="replace"):
        if f"time:{event_id}" in line and "sourceBoundsInScreen=Rect" in line:
            event_fragment.append(line)
        if f"EventTime: {event_id}" in line and "TYPE_VIEW_CLICKED" in line:
            event_fragment.append(line)
            break
    actual = click_events("".join(event_fragment)).get(event_id)
    if not actual or not actual.get("bounds"):
        raise ValueError("Preserved click event has no correlatable bounds")
    hit_nodes = [(node, ancestors) for node, ancestors in _walk(roots)
                 if node.get("clickable") and _bounds(node) == actual["bounds"]]
    hit_nodes.sort(key=lambda pair: len(pair[1]), reverse=True)
    wrong = hit_nodes[0][0] if hit_nodes else {}
    hit = verify_actual_hit(permit, {}, {event_id: actual})
    before = evidence["hierarchy_before"]["nodes"]
    after = evidence["hierarchy_after"]["nodes"]
    # The preserved normalized hierarchy is flat. Focus flags are excluded
    # from the structural digest by the production verifier.
    failed_post = classify_post_open(after, source_digest=hierarchy_digest(before),
                                     activity_changed=False, target_title_present=True)
    old_action_authorized = bool(permit.get("authorized") and permit.get("point") == old_tap)
    failed = dict(source_request_id=request, old_tap=old_tap,
                  resolved_new_owner=resolution.get("owner_identity"),
                  authorized_new_tap=permit.get("point"),
                  NAVIGATION_OWNER_PROVEN="NO" if not old_action_authorized else "YES",
                  MIXED_ACTION_PARENT_CENTER_TAP_ALLOWED="YES" if old_action_authorized else "NO",
                  ENTRY_ACTION_AUTHORIZED="YES" if old_action_authorized else "NO",
                  ACTUAL_HIT_TARGET=wrong.get("viewIdResourceName"),
                  AUTHORIZED_TARGET_MATCHES_ACTUAL_HIT="YES" if hit["matched"] else "NO",
                  UNSAFE_CHILD_DISPATCH_PREVENTED="YES" if not old_action_authorized else "NO",
                  POST_OPEN_SOURCE_LIST_FALSE_POSITIVE_REMOVED="YES" if failed_post["state"] == "SOURCE_LIST_CONTEXT" else "NO",
                  DESTINATION_IDENTITY_VERIFIED="YES" if failed_post["destination_identity"] else "NO",
                  ROOT_PLUGIN_BODY_VERIFIED="YES" if failed_post["root_plugin_body"] else "NO",
                  TRUSTED_ENTRY_VERIFIED="NO" if failed_post["state"] != "PLUGIN_BODY" else "UNPROVEN")
    cross = {}
    for comparison in evidence["cross_scenario_comparison"]:
        scenario = comparison["scenario"]
        folder = Path(comparison["folder"])
        roots, selected, phrase, old_tap, request = _replay_source(folder)
        resolution = resolve_navigation_owner(roots, selected, phrase)
        permit = authorize_entry(resolution, roots, scenario=scenario, matched_phrase=phrase)
        observation_path = Path(comparison["entry_observation_file"])
        with observation_path.open(encoding="utf-8") as stream:
            observation = json.loads(next(stream))
        raw = observation.get("raw") or {}
        post = classify_post_open(raw.get("nodes") or [], source_digest=hierarchy_digest(roots),
            activity_changed=comparison["activity"] != "com.samsung.android.oneconnect.ui.scmain.SCMainActivity",
            target_title_present=bool(comparison["post_open_summary"].get("entry_contract_detail") == "plugin_open_verified"))
        cross[scenario] = dict(source_request_id=request, navigation_owner_resolved=resolution.get("ok"),
            authorized=permit.get("authorized"), new_tap=permit.get("point"), post_open=post["state"],
            destination_ownership=comparison["context"].get("status"),
            pass_replay=bool(resolution.get("ok") and permit.get("authorized")
                             and post["state"] == "PLUGIN_BODY"
                             and comparison["context"].get("status") == "VERIFIED_PLUGIN_CONTEXT"))
    plain = {"viewIdResourceName": "app:id/plain_card", "contentDescription": "Example Service",
             "className": "android.view.ViewGroup", "boundsInScreen": "[10,10][200,100]",
             "clickable": True, "enabled": True, "children": []}
    simple_resolution = resolve_navigation_owner([plain], plain, "Example Service")
    simple_permit = authorize_entry(simple_resolution, [plain], scenario="device_example_plugin",
                                    matched_phrase="Example Service")
    verdict = bool(not old_action_authorized and not hit["matched"]
                   and failed_post["state"] == "SOURCE_LIST_CONTEXT"
                   and all(row["pass_replay"] for row in cross.values())
                   and simple_permit["authorized"])
    return dict(schema="phase5c-entry-offline-replay-v1", verdict="PASS" if verdict else "REJECT",
                scenario31=failed, cross_scenario=cross,
                simple_device_card_replay="PASS" if simple_permit["authorized"] else "REJECT")


if __name__ == "__main__":
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "out/phase5c_home_monitor_entry_rca_20261014/evidence_extracts.json")
    result = replay(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["verdict"] == "PASS" else 1)
