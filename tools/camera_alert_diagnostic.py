"""Explicit camera-node evidence collector; never changes equality or activates UI.

Missing accessibility/speech metadata stays unknown. Sequential XML, Helper,
and screenshot captures are timestamped rather than claimed to be atomic.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from tb_runner.canonical_json import canonical_sha256
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.state_observation import build_state_observation
from tb_runner.state_registry import StateRegistry
from tools.home_identity_closure import _physical_candidates, pair_diff, summarize


CAMERA_CARD = "com.samsung.android.oneconnect:id/favorite_device_card_camera"
ALERT_PREFIX = "com.samsung.android.oneconnect:id/camera_card_alert_"
TARGET = ALERT_PREFIX + "animation_previous"
UNEXPOSED = ("stateDescription", "hint", "paneTitle", "importantForAccessibility",
             "traversalBefore", "traversalAfter", "actions", "sourceId", "windowId")


def xml_camera_evidence(xml: str) -> dict:
    root = ET.fromstring(xml[xml.find("<hierarchy"):])
    parents = {child: parent for parent in root.iter() for child in parent}
    paths = {}
    def walk(element, path):
        paths[element] = path
        for index, child in enumerate(element):
            walk(child, path + "/" + str(index))
    walk(root, "hierarchy")
    def describe(element):
        if element is None:
            return None
        return dict(attributes=dict(element.attrib), path=paths[element],
                    child_count=len(element), unexposed={k: None for k in UNEXPOSED})
    cards = [n for n in root.iter("node") if n.get("resource-id") == CAMERA_CARD]
    alerts = [n for n in root.iter("node") if n.get("resource-id", "").startswith(ALERT_PREFIX)]
    return dict(target_present=any(n.get("resource-id") == TARGET for n in alerts),
        any_alert_present=bool(alerts), node_count=sum(1 for _ in root.iter("node")),
        alerts=[dict(node=describe(n), parent=describe(parents.get(n)),
                     siblings=[describe(s) for s in parents.get(n, []) if s is not n]) for n in alerts],
        cards=[dict(node=describe(n), descendants=[describe(d) for d in n.iter("node") if d is not n]) for n in cards])


def parent_comparison(left: dict, right: dict, *, left_speech=None, right_speech=None) -> dict:
    """Tri-valued evidence comparison; absence of a field is not equivalence."""
    def changed(field):
        if field not in left or field not in right:
            return None
        return left[field] != right[field]
    result = {"PARENT_" + name + "_CHANGED": changed(field) for name, field in (
        ("TEXT", "text"), ("CONTENT_DESC", "content-desc"), ("STATE_DESC", "stateDescription"),
        ("ACTIONS", "actions"), ("ENABLED", "enabled"), ("CLICKABLE", "clickable"),
        ("SELECTED", "selected"))}
    result["PARENT_SPEECH_CHANGED"] = (left_speech != right_speech
        if left_speech is not None and right_speech is not None else None)
    return result


def capture(client, serial, registry, output, count=30):
    from tools.state_fingerprint_diagnostic import capture_observation
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    registry.save(output / "registry_seed.json")
    bundles = []
    for index in range(1, count + 1):
        started = datetime.now(timezone.utc).isoformat()
        raw = capture_observation(client, serial, scenario_id="camera-alert-semantics", step=index)
        if (raw.get("selected_tab") or {}).get("name") != "home":
            raise RuntimeError("Passive collector requires Home already selected")
        xml = client._run(["shell", "cat", "/sdcard/phase2a_fingerprint.xml"], dev=serial, timeout=8)
        (output / f"{index:03d}.xml").write_text(xml, encoding="utf-8")
        metadata = xml_camera_evidence(xml)
        observation = build_state_observation(raw)
        snapshot = build_discovery_snapshot(raw, registry).to_dict()
        shot_started = datetime.now(timezone.utc).isoformat()
        # Match the existing screenshot path: a foldable can print a display
        # warning into exec-out stdout before PNG bytes. Pull the file instead.
        client._run(["shell", "screencap", "-p", "/sdcard/camera_semantics.png"], dev=serial, timeout=15)
        shot_path = output / f"{index:03d}.png"
        subprocess.run(["adb", "-s", serial, "pull", "/sdcard/camera_semantics.png", str(shot_path)],
                       check=True, capture_output=True, timeout=15)
        screenshot = shot_path.read_bytes()
        if not screenshot.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Invalid screenshot")
        compressed = None
        if index in {1, count // 2, count}:
            client._run(["shell", "uiautomator", "dump", "--compressed", "/sdcard/camera_semantics_compressed.xml"], dev=serial, timeout=12)
            compressed_xml = client._run(["shell", "cat", "/sdcard/camera_semantics_compressed.xml"], dev=serial, timeout=8)
            (output / f"{index:03d}_compressed.xml").write_text(compressed_xml, encoding="utf-8")
            compressed = xml_camera_evidence(compressed_xml)
        bundle = dict(index=index, started_at=started, screenshot_started_at=shot_started,
            completed_at=datetime.now(timezone.utc).isoformat(), raw=raw, observation=observation.to_dict(),
            snapshot=snapshot, registry_resolution=registry.to_dict()["events"][-1]["result"],
            camera=metadata, compressed_camera=compressed,
            physical_candidate_hash=canonical_sha256(_physical_candidates(snapshot)),
            speech=None, speech_status="NOT_OBSERVED_DURING_PASSIVE_CAPTURE",
            screenshot=f"{index:03d}.png", actions_executed=0, visit_credit=0)
        bundles.append(bundle)
        (output / f"observation_{index:03d}.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(dict(index=index, nodes=metadata["node_count"], previous=metadata["target_present"],
            any_alert=metadata["any_alert_present"], state_id=snapshot["state_id"])), flush=True)
    pairs = [pair_diff(a, b) for i, a in enumerate(bundles) for b in bundles[i + 1:]]
    (output / "pairs.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pairs), encoding="utf-8")
    summary = summarize(bundles, pairs)
    summary.update(CAMERA_ALERT_NODE_PRESENT_COUNT=sum(b["camera"]["target_present"] for b in bundles),
                   CAMERA_ALERT_NODE_ABSENT_COUNT=sum(not b["camera"]["target_present"] for b in bundles),
                   ANY_CAMERA_ALERT_PRESENT_COUNT=sum(b["camera"]["any_alert_present"] for b in bundles))
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    registry.save(output / "registry_after.json")
    print(json.dumps(summary), flush=True)
    return bundles, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--registry-in", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=30)
    args = parser.parse_args()
    from talkback_lib import A11yAdbClient
    capture(A11yAdbClient(start_monitor=False), args.serial, StateRegistry.load(args.registry_in), args.output, args.count)


if __name__ == "__main__":
    main()
