"""Opt-in event-correlated camera evidence; never changes identity or production.

Capture tightly bounds a screenshot after XML dump completion. It remains a
sequential observation; timing intervals and unavailable speech stay explicit.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

from tb_runner.canonical_json import canonical_sha256
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.state_observation import build_state_observation
from tools.camera_alert_diagnostic import xml_camera_evidence
from tools.home_identity_closure import _physical_candidates
from tools.state_fingerprint_diagnostic import capture_observation


def now():
    return datetime.now(timezone.utc).isoformat()


def timing_gap(xml_end: float, shot_start: float, xml_start: float, shot_end: float):
    if not xml_start <= xml_end <= shot_start <= shot_end:
        raise ValueError("capture intervals must be chronological")
    return dict(DELTA_MS=(shot_start-xml_end)*1000,
                UI_MOMENT_BOUND_MS=(shot_end-xml_start)*1000,
                SYNCHRONIZATION="BOUNDED_SEQUENTIAL_NOT_ATOMIC")


def speech_comparison(present, absent):
    if not present or not absent:
        return "NO_RELIABLE_SPEECH_EVIDENCE"
    return "IDENTICAL" if present == absent else "DIFFERENT_REQUIRES_SEMANTIC_REVIEW"


class EventProbe:
    def __init__(self, client, serial, registry, output):
        self.client, self.serial, self.registry = client, serial, registry
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        registry.save(self.output / "registry_seed.json")
        self.rows, self.events = [], []

    def save(self, name, value):
        (self.output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def capture(self, label):
        client, serial = self.client, self.serial
        original = client._run
        index = len(self.rows)+1
        capture_timing = {}
        def hooked(args, dev=None, timeout=None):
            if len(args) >= 3 and args[:3] == ["shell", "uiautomator", "dump"]:
                start, start_time = time.perf_counter(), now()
                result = original(args, dev=dev, timeout=timeout)
                end, end_time = time.perf_counter(), now()
                shot_start, shot_start_time = time.perf_counter(), now()
                original(["shell", "screencap", "-p", "/sdcard/camera_overlay_probe.png"], dev=serial, timeout=15)
                shot_end, shot_end_time = time.perf_counter(), now()
                capture_timing.update(XML_CAPTURE_TIME=dict(start=start_time, end=end_time),
                    SCREENSHOT_CAPTURE_TIME=dict(start=shot_start_time, end=shot_end_time),
                    **timing_gap(end, shot_start, start, shot_end))
                subprocess.run(["adb", "-s", serial, "pull", "/sdcard/camera_overlay_probe.png", str(self.output/f"{index:03d}.png")],
                               check=True, capture_output=True, timeout=15)
                return result
            return original(args, dev=dev, timeout=timeout)
        t0=time.perf_counter()
        client._run=hooked
        try:
            raw=capture_observation(client, serial, scenario_id="camera-overlay-probe", step=index)
        finally:
            client._run=original
        if raw["source"] != "helper_capability+xml_semantics" or not capture_timing:
            raise RuntimeError("Reliable XML/screenshot capture unavailable; no stale XML accepted")
        xml=original(["shell", "cat", "/sdcard/phase2a_fingerprint.xml"], dev=serial, timeout=8)
        (self.output/f"{index:03d}.xml").write_text(xml, encoding="utf-8")
        camera=xml_camera_evidence(xml)
        observation=build_state_observation(raw)
        snapshot=build_discovery_snapshot(raw, self.registry).to_dict()
        row=dict(index=index, label=label, captured_at=now(), raw=raw, camera=camera,
            observation=observation.to_dict(), snapshot=snapshot,
            registry_resolution=self.registry.to_dict()["events"][-1]["result"],
            physical_candidate_hash=canonical_sha256(_physical_candidates(snapshot)),
            timing=capture_timing, total_capture_ms=(time.perf_counter()-t0)*1000,
            screenshot=f"{index:03d}.png", speech=None, speech_status="NOT_OBSERVED",
            actual_focus=deepcopy(raw.get("focus_node")), visit_credit=0)
        self.rows.append(row)
        self.save(f"observation_{index:03d}.json", row)
        self.save("index.json", [dict(index=r["index"],label=r["label"],root=(r["raw"].get("selected_tab") or {}).get("name"),
            overlay=r["camera"]["any_alert_present"], resources=[a["node"]["attributes"]["resource-id"] for a in r["camera"]["alerts"]],
            timestamp=r["timing"]["XML_CAPTURE_TIME"],gap=r["timing"]["DELTA_MS"]) for r in self.rows])
        print(json.dumps(dict(index=index,label=label,root=(raw.get("selected_tab") or {}).get("name"),
            overlay=camera["any_alert_present"],previous=camera["target_present"],gap_ms=capture_timing["DELTA_MS"])),flush=True)
        return row

    def event(self, name, kind, execute, *, after_count=2):
        before=self.capture(name+":before")
        event=dict(name=name,event_type=kind,before_index=before["index"],event_started_at=now())
        # Persist the event before invoking its already-authorized safe command.
        self.events.append(event);self.save("events.json",self.events)
        event["command_ack"]=execute(before["raw"])
        event["event_finished_at"]=now();self.save("events.json",self.events)
        after=[self.capture(name+":after_"+str(i)) for i in range(after_count)]
        event["after_indices"]=[r["index"] for r in after]
        self.save("events.json",self.events)
        self.registry.save(self.output/"registry_after.json")
        return after
