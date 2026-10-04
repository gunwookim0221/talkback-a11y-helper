"""Explicit Phase 2A diagnostic collector/replay. Never selects or activates UI.

Run via python -m tools.state_fingerprint_diagnostic --input snapshot.json
or --capture --serial SERIAL. Capture is opt-in and only observes the current UI.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

from tb_runner import global_navigation, scroll_reliability
from tb_runner.popup_handler import detect_popup_candidate
from tb_runner.scenario_config import BOTTOM_TAB_GLOBAL_NAV
from tb_runner.state_fingerprint import build_state_fingerprint, write_fingerprint_record


def capture_observation(client: Any, serial: str | None, *, scenario_id: str = "diagnostic", step: int = 0) -> dict[str, Any]:
    """Read existing Helper/XML/focus sources; no gesture, click, recovery or APK.

    Keep transport capability copies before later reads mutate the client cache.
    XML complements missing selected/enabled/checked flags in flat Helper nodes.
    Capture sources are sequential, not claimed to be one atomic UI snapshot.
    """
    nodes = scroll_reliability.dump_with_capabilities(client, serial)
    metadata = deepcopy(getattr(client, "last_dump_metadata", {}))
    capabilities = deepcopy(getattr(client, "last_scroll_capabilities", []))
    cap = scroll_reliability.capability(nodes, metadata, capabilities)
    notes = []
    try:
        focus = client.get_focus(dev=serial, allow_fallback_dump=False, mode="fast") or {}
    except Exception as exc:
        focus = {}
        notes.append("focus_capture:" + type(exc).__name__)
    observed_nodes = nodes
    source = "helper_flat"
    xml_packages = set()
    try:
        remote = "/sdcard/phase2a_fingerprint.xml"
        client._run(["shell", "uiautomator", "dump", remote], dev=serial, timeout=12)
        raw = client._run(["shell", "cat", remote], dev=serial, timeout=8)
        observed_nodes = global_navigation.xml_nodes(raw)
        root = ET.fromstring(raw[raw.find("<hierarchy"):])
        attributes = [n.attrib for n in root.iter("node")]
        xml_packages = {attrs["package"] for attrs in attributes if attrs.get("package")}
        # Preserve unknown flags rather than adopting XML parser defaults when
        # attributes are genuinely absent. No tree XML is stored twice.
        for node, attrs in zip(observed_nodes, attributes):
            for field, xml_name in (("selected", "selected"), ("checked", "checked"),
                                    ("enabled", "enabled"), ("clickable", "clickable"),
                                    ("focusable", "focusable"), ("focused", "focused"),
                                    ("scrollable", "scrollable"), ("visibleToUser", "visible-to-user")):
                node[field] = attrs[xml_name] == "true" if xml_name in attrs else None
        source = "helper_capability+xml_semantics"
    except Exception as exc:
        notes.append("xml_capture:" + type(exc).__name__)
    items = global_navigation.discover(observed_nodes, dict(global_nav=BOTTOM_TAB_GLOBAL_NAV))
    selected = global_navigation.current(items)
    display = None
    package = None
    activity = None
    context_source = "unobserved"
    try:
        size = client._run(["shell", "wm", "size"], dev=serial, timeout=5)
        sizes = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", size)
        if sizes:
            width, height = map(int, sizes[-1])
            display = [0, 0, width, height]
        window = client._run(["shell", "dumpsys", "window"], dev=serial, timeout=8)
        focused_windows = set(re.findall(r"mCurrentFocus=[^\n]*?\s([\w.]+)/([\w.$]+)", window))
        if len(focused_windows) == 1:
            package, activity = focused_windows.pop()
            context_source = "window_current_focus"
        elif focused_windows:
            notes.append("window_capture:AMBIGUOUS_FOCUSED_WINDOWS")
        else:
            # UIAutomator can temporarily leave mCurrentFocus=null. An observed
            # resumed activity is a separate OS source, never a cached guess.
            activities = client._run(["shell", "dumpsys", "activity", "activities"], dev=serial, timeout=8)
            resumed = set(re.findall(r"(?:topResumedActivity|mResumedActivity)=[^\n]*?\s([\w.]+)/([\w.$]+)", activities))
            if len(resumed) == 1:
                package, activity = resumed.pop()
                context_source = "activity_resumed"
            elif resumed:
                notes.append("window_capture:AMBIGUOUS_RESUMED_ACTIVITIES")
        if package and xml_packages and package not in xml_packages:
            package = activity = None
            context_source = "conflicting_observation"
            notes.append("window_capture:XML_PACKAGE_CONFLICT")
    except Exception as exc:
        notes.append("window_capture:" + type(exc).__name__)
    popup = detect_popup_candidate(dict(dump_tree_nodes=observed_nodes, focus_node=focus))
    # This existing detector is bounded dismissal-oriented, not an overlay
    # absence oracle. Even detected=False can retain modal evidence.
    overlay = dict(kind="popup" if popup.modal_evidence else "unknown",
                   observed=bool(popup.modal_evidence), source="existing_popup_detector",
                   nodes=list(popup.safe_buttons or []))
    if popup.dangerous_buttons:
        overlay["nodes"].extend(popup.dangerous_buttons)
    return dict(nodes=observed_nodes, package_name=package, activity_name=activity,
                navigation_context={"bottom_tab": selected["logical_name"]} if selected else None,
                selected_tab=dict(name=selected["logical_name"], verified=True,
                                  source="xml_selected" if source == "helper_capability+xml_semantics" else "helper_selected") if selected else None,
                display_bounds=display, capability=cap, focus_node=focus, overlay=overlay,
                viewport=scroll_reliability.viewport(nodes, scenario_id, cap.get("container")),
                timestamp=datetime.now(timezone.utc).isoformat(), scenario_id=scenario_id, step=step,
                source=source, context_source=context_source, notes=notes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", type=Path, help="Saved observation mapping or list; no device I/O")
    mode.add_argument("--capture", action="store_true", help="Explicit current-screen observation only")
    parser.add_argument("--serial")
    parser.add_argument("--scenario-id", default="diagnostic")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.capture:
        from talkback_lib import A11yAdbClient
        client = A11yAdbClient(start_monitor=False)
        observations = [capture_observation(client, args.serial, scenario_id=args.scenario_id)]
    else:
        value = json.loads(args.input.read_text(encoding="utf-8"))
        observations = value if isinstance(value, list) else [value]
    for observation in observations:
        fp = build_state_fingerprint(observation)
        write_fingerprint_record(args.output, fp)
        print(json.dumps(dict(scenario_id=observation.get("scenario_id"), core_signature=fp.core_signature,
                              viewport_signature=fp.viewport_signature, fingerprint_hash=fp.fingerprint_hash)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
