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
from uuid import uuid4
from typing import Any
import xml.etree.ElementTree as ET

from tb_runner import global_navigation, scroll_reliability
from tb_runner.popup_handler import detect_popup_candidate
from tb_runner.scenario_config import BOTTOM_TAB_GLOBAL_NAV
from tb_runner.state_fingerprint import build_state_fingerprint, write_fingerprint_record
from talkback_lib.hierarchy_snapshot import service_hierarchy_to_xml


def _validated_capture_snapshot(snapshot: Any) -> tuple[Any, dict[str, Any]]:
    """Rebind the mutable snapshot to its already validated Helper capture."""
    from talkback_lib.reliable_hierarchy_schema import (
        _decode_reliable_hierarchy_payload, _thaw, candidate_projection_matches_decoded,
        capture_canonical_json, legacy_dump_tree_response, validate_capture_authority,
    )

    decoded = snapshot.decoded
    authority = validate_capture_authority(decoded.capture_authority)
    if authority is None or not candidate_projection_matches_decoded(decoded):
        raise ValueError("capture authority or candidate projection invalid")
    raw = deepcopy(snapshot.raw_hierarchy)
    if capture_canonical_json(raw) != capture_canonical_json(decoded.raw_hierarchy):
        raise ValueError("hierarchy snapshot differs from decoded capture")
    if capture_canonical_json(snapshot.response) != capture_canonical_json(legacy_dump_tree_response(decoded)):
        raise ValueError("consumed candidates differ from decoded capture")
    payload = dict(raw, traversalCandidates=_thaw(decoded.validated_candidate_projection))
    verified = _decode_reliable_hierarchy_payload(
        payload, capability_verified=True, transport_metadata=_thaw(decoded.transport_metadata))
    fields = ("schema_version", "request_id", "platform_api_level", "traversal_root_ref",
              "traversal_root_window_id", "raw_node_count", "raw_completion_valid")
    if (any(type(getattr(decoded, key)) is not type(getattr(verified, key))
            or getattr(decoded, key) != getattr(verified, key) for key in fields)
            or validate_capture_authority(verified.capture_authority) != authority):
        raise ValueError("decoded capture identity mismatch")
    match = re.fullmatch(r"windows\[(\d+)\]\.root", authority.root_ref)
    if match is None:
        raise ValueError("invalid capture root reference")
    root = deepcopy(raw["windows"][int(match.group(1))]["root"])
    return authority, root


def capture_observation(client: Any, serial: str | None, *, scenario_id: str = "diagnostic", step: int = 0,
                       scenario_run_id: str | None = None) -> dict[str, Any]:
    """Read existing Helper/XML/focus sources; no gesture, click, recovery or APK.

    Keep transport capability copies before later reads mutate the client cache.
    Service-owned XML complements flags missing in flat Helper nodes.
    Capture sources are sequential, not claimed to be one atomic UI snapshot.
    """
    notes: list[str] = []
    reliable_snapshot_used = callable(getattr(client, "get_traversal_candidate_snapshot", None))
    snapshot_coherent = False
    capture_authority = None
    capture_root = None
    if reliable_snapshot_used:
        try:
            snapshot = client.get_traversal_candidate_snapshot(dev=serial)
            from talkback_lib.hierarchy_snapshot import flatten_service_hierarchy, hierarchy_package

            raw_hierarchy = snapshot.raw_hierarchy
            if not isinstance(raw_hierarchy, dict) or raw_hierarchy.get("success") is not True:
                raise ValueError("invalid reliable hierarchy snapshot")
            capture_authority, capture_root = _validated_capture_snapshot(snapshot)
            observed_nodes = flatten_service_hierarchy(raw_hierarchy)
            nodes = list(snapshot.candidates)
            metadata = deepcopy(getattr(client, "last_dump_metadata", {}))
            capabilities = deepcopy(getattr(client, "last_scroll_capabilities", []))
            cap = scroll_reliability.capability(nodes, metadata, capabilities)
            focused_nodes = [node for node in observed_nodes
                             if node.get("accessibilityFocused") is True
                             and node.get("visibleToUser") is not False]
            focus = deepcopy(focused_nodes[0]) if len(focused_nodes) == 1 else {}
            if len(focused_nodes) != 1:
                notes.append("focus_capture:" + ("no_strict_accessibility_focus" if not focused_nodes
                                                   else "ambiguous_accessibility_focus"))
            package = hierarchy_package(raw_hierarchy)
            xml_packages = {str(node.get("packageName") or "") for node in observed_nodes
                            if node.get("packageName")}
            decoded = getattr(snapshot, "decoded", None)
            projection = getattr(decoded, "traversal_candidates", None)
            complete = bool(getattr(decoded, "raw_completion_valid", False)
                            and getattr(projection, "complete", False) and observed_nodes)
            observation_coverage = "OBSERVED_FULL" if complete else "OBSERVED_PARTIAL"
            coverage_source = "reliable_service_hierarchy" if complete else "reliable_snapshot_incomplete"
            hierarchy_request_id = str(getattr(decoded, "request_id", "") or "")
            source = "reliable_service_hierarchy_snapshot"
            snapshot_coherent = True
        except Exception as exc:
            # Do not rescue a failed reliable hierarchy read with another source.
            nodes, observed_nodes, focus = [], [], {}
            metadata, capabilities = {}, []
            cap = scroll_reliability.capability([], {})
            package, xml_packages = None, set()
            observation_coverage, coverage_source = "UNOBSERVED", "reliable_snapshot_failed"
            hierarchy_request_id = ""
            source = "reliable_snapshot_failed"
            snapshot_coherent = False
            capture_authority = capture_root = None
            notes.append("hierarchy_capture:" + type(exc).__name__)
    else:
        nodes = scroll_reliability.dump_with_capabilities(client, serial)
        metadata = deepcopy(getattr(client, "last_dump_metadata", {}))
        capabilities = deepcopy(getattr(client, "last_scroll_capabilities", []))
        cap = scroll_reliability.capability(nodes, metadata, capabilities)
        try:
            focus = client.get_focus(dev=serial, allow_fallback_dump=False, mode="fast") or {}
        except Exception as exc:
            focus = {}
            notes.append("focus_capture:" + type(exc).__name__)
        observed_nodes = nodes
        package = None
        observation_coverage = "OBSERVED_PARTIAL" if nodes else "UNOBSERVED"
        coverage_source = "helper_flat_candidates" if nodes else "no_hierarchy"
        hierarchy_request_id = str(metadata.get("requestId") or "")
        source = "helper_flat"
    if not reliable_snapshot_used:
        xml_packages = set()
        try:
            raw = service_hierarchy_to_xml(client.dump_hierarchy(dev=serial))
            observed_nodes = global_navigation.xml_nodes(raw)
            root = ET.fromstring(raw[raw.find("<hierarchy"):])
            attributes = [n.attrib for n in root.iter("node")]
            xml_packages = {attrs["package"] for attrs in attributes if attrs.get("package")}
            # Preserve unknown flags rather than adopting parser defaults when
            # the source omits them. No tree XML is stored twice.
            for node, attrs in zip(observed_nodes, attributes):
                for field, xml_name in (("selected", "selected"), ("checked", "checked"),
                                        ("enabled", "enabled"), ("clickable", "clickable"),
                                        ("focusable", "focusable"), ("focused", "focused"),
                                        ("accessibilityFocused", "accessibility-focused"),
                                        ("scrollable", "scrollable"), ("visibleToUser", "visible-to-user")):
                    node[field] = attrs[xml_name] == "true" if xml_name in attrs else None
            source = "helper_capability+service_hierarchy_semantics"
            if observed_nodes:
                observation_coverage, coverage_source = "OBSERVED_FULL", "service_hierarchy_xml"
        except Exception as exc:
            notes.append("hierarchy_capture:" + type(exc).__name__)
    items = global_navigation.discover(observed_nodes, dict(global_nav=BOTTOM_TAB_GLOBAL_NAV))
    selected = global_navigation.current(items)
    display = None
    activity = None
    context_source = "service_hierarchy" if reliable_snapshot_used and source == "reliable_service_hierarchy_snapshot" else "unobserved"
    window_evidence = {}
    try:
        size = client._run(["shell", "wm", "size"], dev=serial, timeout=5)
        sizes = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", size)
        if sizes:
            width, height = map(int, sizes[-1])
            display = [0, 0, width, height]
        window = client._run(["shell", "dumpsys", "window"], dev=serial, timeout=8)
        window_evidence = summarize_window_evidence(window)
        focused_windows = set(re.findall(r"mCurrentFocus=[^\n]*?\s([\w.]+)/([\w.$]+)", window))
        if len(focused_windows) == 1:
            window_package, window_activity = focused_windows.pop()
            if package and package != window_package:
                package = activity = None
                context_source = "conflicting_observation"
                notes.append("window_capture:HIERARCHY_PACKAGE_CONFLICT")
            else:
                package, activity = window_package, window_activity
                context_source = "window_current_focus"
                window_evidence["focused_activity_matches"] = (
                    window_evidence.get("focused_window_component") == activity
                    or window_evidence.get("focused_window_component") == f"{package}/{activity}"
                )
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
    popup_row = dict(dump_tree_nodes=observed_nodes, focus_node=focus,
                     window_evidence=window_evidence, display_bounds=display,
                     package_name=package, activity_name=activity, context_source=context_source)
    popup = detect_popup_candidate(popup_row)
    # This existing detector is bounded dismissal-oriented, not an overlay
    # absence oracle. Even detected=False can retain modal evidence.
    overlay = dict(kind="popup_candidate" if popup.candidate_evidence else popup.modal_classification.lower(),
                   observed=popup.modal_classification != "NON_MODAL_CONTROL", source="evidence_modal_classifier",
                   candidate_present=bool(popup.candidate_evidence),
                   candidate_evidence=list(popup.candidate_evidence or []),
                   classification=popup.modal_classification,
                   modal_evidence=list(popup.modal_evidence or []),
                   modal_assessment=dict(classification=popup.modal_classification,
                       focused_activity_matches=window_evidence.get("focused_activity_matches", False),
                       focused_window_type=window_evidence.get("focused_window_type"),
                       window_count=window_evidence.get("window_count"),
                       background_accessible=popup.modal_assessment.get("background_accessible"),
                       background_actionable_count=popup.modal_assessment.get("background_actionable_count"),
                       accessibility_focus_outside=popup.modal_assessment.get("accessibility_focus_outside"),
                       candidate_area_ratio=popup.modal_assessment.get("candidate_area_ratio")),
                   nodes=list(popup.safe_buttons or []))
    if popup.dangerous_buttons:
        overlay["nodes"].extend(popup.dangerous_buttons)
    capture_id = (capture_authority.capture_key if capture_authority is not None else
                  None if reliable_snapshot_used else uuid4().hex)
    focus_capture_id = capture_id if snapshot_coherent else None
    geometry_capture_id = capture_id if snapshot_coherent else None
    focus_capture_status = ("STRICT_ACCESSIBILITY_FOCUS" if isinstance(focus, dict)
                            and focus.get("accessibilityFocused") is True else "FOCUS_UNAVAILABLE")
    observation = dict(nodes=observed_nodes, package_name=package, activity_name=activity,
                navigation_context={"bottom_tab": selected["logical_name"]} if selected else None,
                selected_tab=dict(name=selected["logical_name"], verified=True,
                                  source=("service_hierarchy_selected" if source in {
                                      "helper_capability+service_hierarchy_semantics",
                                      "reliable_service_hierarchy_snapshot",
                                  } else "helper_selected")) if selected else None,
                display_bounds=display, capability=cap, focus_node=focus, window_evidence=window_evidence, overlay=overlay,
                viewport=scroll_reliability.viewport(nodes, scenario_id, cap.get("container")),
                timestamp=datetime.now(timezone.utc).isoformat(), scenario_id=scenario_id, step=step,
                capture_id=capture_id, snapshot_coherent=snapshot_coherent,
                focus_capture_id=focus_capture_id,
                focus_capture_status=focus_capture_status,
                scenario_run_id=scenario_run_id, observation_coverage=observation_coverage,
                coverage_source=coverage_source, hierarchy_request_id=hierarchy_request_id,
                hierarchy_complete=(observation_coverage == "OBSERVED_FULL"),
                hierarchy_capture_id=capture_id, geometry_capture_id=geometry_capture_id,
                source=source, context_source=context_source, notes=notes,
                capture_authority=capture_authority.to_dict() if capture_authority is not None else None)
    if capture_authority is not None:
        bounds = (list(capture_authority.hierarchy_root_bounds)
                  if capture_authority.hierarchy_root_bounds is not None else None)
        observation.update(
            hierarchy_snapshot_id=capture_id,
            hierarchy_capture_sequence=capture_authority.capture_sequence,
            hierarchy_process_epoch=capture_authority.process_epoch,
            hierarchy_generation=capture_authority.generation,
            hierarchy_service_instance_id=capture_authority.service_instance_id,
            hierarchy_root_digest=capture_authority.root_digest,
            hierarchy_candidate_digest=capture_authority.candidate_digest,
            hierarchy_root_class_name=capture_authority.hierarchy_root_class_name,
            hierarchy_root_source_node_id=capture_authority.hierarchy_root_source_node_id,
            hierarchy_root_bounds=bounds, capture_root_bounds=bounds,
            traversal_root_ref=capture_authority.root_ref,
            traversal_root_window_id=capture_authority.hierarchy_window_id,
            traversal_root_digest=capture_authority.root_digest,
            traversal_root_class_name=capture_authority.hierarchy_root_class_name,
            traversal_root_source_node_id=capture_authority.hierarchy_root_source_node_id,
            traversal_root_bounds=bounds, _capture_root_tree=capture_root,
        )
    return observation


def summarize_window_evidence(window_dump: str) -> dict[str, Any]:
    """Keep bounded WMS window identity/type evidence without storing dumpsys text."""
    headers = list(re.finditer(r"(?m)^\s*Window\s+#\d+\s+(Window\{[^\n]+)", window_dump or ""))
    windows = []
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(window_dump)
        block = window_dump[match.start():end]
        header = match.group(1)
        token = re.search(r"Window\{([^\s}]+)", header)
        owner = re.search(r"\bu\d+\s+([^\s}]+)", header)
        kind = re.search(r"\bty=([A-Z][A-Z0-9_]+)", block)
        frame = re.search(r"\bmFrame=\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", block)
        windows.append(dict(token=token.group(1) if token else None,
            owner=owner.group(1) if owner else None,
            window_type=kind.group(1) if kind else None,
            bounds=[int(v) for v in frame.groups()] if frame else None))
    focus_lines = [line.strip() for line in (window_dump or "").splitlines() if "mCurrentFocus=" in line]
    # Foldable/multi-display WMS output can report mCurrentFocus=null for a
    # non-interactive cover display before the active display's focused window.
    # Prefer the last concrete Window{} entry; retain the last null line only
    # when WMS did not report any focused window.
    current_line = next((line for line in reversed(focus_lines) if re.search(r"mCurrentFocus\s*=\s*Window\{", line)),
                        focus_lines[-1] if focus_lines else "")
    current = re.search(r"Window\{([^}]+)", current_line)
    current_token = re.match(r"([^\s]+)", current.group(1)).group(1) if current and re.match(r"([^\s]+)", current.group(1)) else None
    current_owner = re.search(r"\bu\d+\s+([^\s}]+)", current.group(1)) if current else None
    focused = next((w for w in windows if current_token and w.get("token") == current_token), {})
    owner = current_owner.group(1) if current_owner else focused.get("owner")
    component = None
    if owner and "/" in owner:
        pkg, cls = owner.split("/", 1)
        component = cls if cls.startswith(pkg + ".") else cls
    app_line = next((line.strip() for line in (window_dump or "").splitlines() if "mFocusedApp=" in line), "")
    return dict(window_count=len(windows), windows=windows,
        window_types=sorted({w["window_type"] for w in windows if w.get("window_type")}),
        current_focus_line=current_line or None, focused_window_token=current_token,
        focused_window_owner=owner, focused_window_component=component,
        focused_window_type=focused.get("window_type"), focused_window_bounds=focused.get("bounds"),
        focused_window_is_dialog="DIALOG" in str(focused.get("window_type") or "").upper(),
        focused_app_line=app_line or None)


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
