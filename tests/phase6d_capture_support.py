"""Helpers for strict Phase6D capture-bound regression fixtures."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from talkback_lib.reliable_hierarchy_schema import (
    CAPTURE_CANONICALIZATION_VERSION, CAPTURE_ENVELOPE_SCHEMA_VERSION,
    CAPTURE_ROOT_IDENTITY_VERSION, capture_canonical_sha256, capture_root_id,
)


def attach_capture_authority(raw: dict[str, Any], *, production: bool = False,
                             sequence: int = 1, request_id: str | None = None,
                             generation: int = 1,
                             window_id: int = 1, root_ref: str = "windows[0].root",
                             include_test_capture_bundle: bool = False) -> dict[str, Any]:
    """Bind a fixture through the same root/candidate/transfer checks as production."""
    if type(sequence) is not int or sequence <= 0:
        raise ValueError("capture sequence must be positive")
    nodes = deepcopy(raw.get("nodes", []))
    bounds = raw.get("capture_root_bounds") or [0, 0, 1000, 1000]
    if not (isinstance(bounds, (list, tuple)) and len(bounds) == 4
            and all(type(value) is int for value in bounds)):
        bounds = [0, 0, 1000, 1000]
    package = str(raw.get("package_name") or "").strip() or None
    root = {"packageName": package, "windowId": window_id,
            "className": raw.get("traversal_root_class_name", "android.view.View"),
            "sourceNodeId": raw.get("traversal_root_source_node_id"),
            "boundsInScreen": {"l": bounds[0], "t": bounds[1],
                               "r": bounds[2], "b": bounds[3]},
            "children": nodes}
    request = request_id or f"fixture-request-{sequence}"
    envelope = {
        "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "canonicalization": CAPTURE_CANONICALIZATION_VERSION,
        "request_id": request, "process_epoch": "fixture-process-epoch",
        "generation": generation, "service_instance_id": "fixture-service-instance",
        "capture_sequence": sequence, "root_ref": root_ref,
        "root_digest": capture_canonical_sha256(root),
    }
    candidate_projection = {
        "source_root_digest": envelope["root_digest"],
        "traversalRootRef": envelope["root_ref"],
        "traversalRootWindowId": window_id,
        "candidates": nodes,
    }
    candidate_projection["rootCaptureId"] = capture_root_id(envelope)
    candidate_projection["candidate_digest"] = capture_canonical_sha256(candidate_projection)
    envelope["candidate_digest"] = candidate_projection["candidate_digest"]
    transfer = {"header": {}, "control": {}}
    identity = {
        "request_id": request, "client_nonce": "fixture-nonce",
        "payload_schema_version": "service-hierarchy-v2",
        "process_epoch": envelope["process_epoch"], "generation": envelope["generation"],
        "service_instance_id": envelope["service_instance_id"],
        "capture_sequence": sequence,
        "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
        "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
        "helper_build_identity": {"build_id": "fixture"},
    }
    transfer["header"].update(identity)
    transfer["control"].update(identity)
    from talkback_lib.reliable_hierarchy_schema import _seal_capture_authority
    authority_obj = _seal_capture_authority(envelope, root, candidate_projection, transfer)
    if authority_obj is None:
        raise ValueError("fixture capture authority failed production validation")
    authority = authority_obj.to_dict()
    previous_capture_id = raw.get("capture_id")
    raw.update(
        capture_authority=authority, capture_id=authority["capture_key"],
        hierarchy_request_id=authority["request_id"],
        hierarchy_capture_id=authority["capture_key"],
        hierarchy_snapshot_id=authority["capture_key"],
        hierarchy_capture_sequence=authority["capture_sequence"],
        hierarchy_process_epoch=authority["process_epoch"],
        hierarchy_generation=authority["generation"],
        hierarchy_service_instance_id=authority["service_instance_id"],
        hierarchy_root_digest=authority["root_digest"],
        hierarchy_candidate_digest=authority["candidate_digest"],
        hierarchy_root_class_name=authority["hierarchy_root_class_name"],
        hierarchy_root_source_node_id=authority["hierarchy_root_source_node_id"],
        hierarchy_root_bounds=authority["hierarchy_root_bounds"],
        capture_root_bounds=list(bounds),
        traversal_root_ref=root_ref,
        traversal_root_window_id=window_id,
        traversal_root_digest=authority["root_digest"],
        traversal_root_class_name=authority["hierarchy_root_class_name"],
        traversal_root_source_node_id=authority["hierarchy_root_source_node_id"],
        traversal_root_bounds=authority["hierarchy_root_bounds"],
        _capture_root_tree=deepcopy(root),
    )
    for key in ("focus_capture_id", "geometry_capture_id"):
        if raw.get(key) == previous_capture_id and previous_capture_id:
            raw[key] = authority["capture_key"]
        else:
            raw.setdefault(key, None)
    if include_test_capture_bundle:
        import re
        match = re.fullmatch(r"windows\[(\d+)\]\.root", root_ref)
        if not match:
            raise ValueError("invalid fixture traversal root reference")
        root_index = int(match.group(1))
        windows = []
        for index in range(root_index + 1):
            if index == root_index:
                window_root = deepcopy(root)
                current_window_id = window_id
            else:
                current_window_id = window_id - (root_index - index)
                window_root = deepcopy(root)
                window_root["windowId"] = current_window_id
                window_root["children"] = []
            windows.append({"id": current_window_id, "root": window_root,
                            "active": index == root_index, "focused": False})
        raw["_phase6d_test_capture_bundle"] = {
            "capture_authority_object": authority_obj,
            "raw_hierarchy": {
                "success": True, "schemaVersion": "service-hierarchy-v2",
                "reqId": request, "traversalRootRef": root_ref,
                "traversalRootWindowId": window_id, "windows": windows,
                "nodes": [deepcopy(window["root"]) for window in windows],
                "captureEnvelope": deepcopy(envelope),
                "traversalCandidates": deepcopy(candidate_projection),
            },
            "transport_metadata": deepcopy(transfer),
        }
    if not production:
        return raw

    scenario_id = str(raw.get("scenario_id") or "fixture_scenario")
    run_id = str(raw.get("scenario_run_id") or "fixture_run")
    navigation_epoch = raw.get("navigation_epoch") or "fixture_navigation_epoch"
    coverage = raw.get("observation_coverage") or "OBSERVED_FULL"
    complete = coverage == "OBSERVED_FULL"
    coverage_source = "reliable_service_hierarchy" if complete else "reliable_snapshot_incomplete"
    raw.update(
        scenario_id=scenario_id, scenario_run_id=run_id, navigation_epoch=navigation_epoch,
        snapshot_coherent=True, observation_coverage=coverage,
        coverage_source=coverage_source, hierarchy_complete=complete,
        production_observation_current=True,
    )
    marker = {
        "scope_id": "fixture-scope", "observation_sequence": sequence,
        "action_epoch": 0, "observation_epoch": 0, "capture_end_action_epoch": 0,
        "context_revision": 0, "observation_id": f"observation:fixture-scope:{sequence}",
        "capture_complete": True,
    }
    raw["_exploration_observation"] = deepcopy(marker)
    raw["production_observation_envelope"] = {
        "schema_version": "phase6-production-observation-v1",
        "scenario_id": scenario_id, "scenario_run_id": run_id,
        "capture_id": authority["capture_key"], "capture_authority": deepcopy(authority),
        "snapshot_coherent": True, "navigation_epoch": navigation_epoch,
        "hierarchy_capture_id": authority["capture_key"],
        "focus_capture_id": raw.get("focus_capture_id"),
        "geometry_capture_id": raw.get("geometry_capture_id"),
        "observation": deepcopy(marker), "capture_complete": True,
        "coverage_source": coverage_source, "coverage": coverage,
        "hierarchy_complete": complete, "hierarchy_request_id": authority["request_id"],
    }
    return raw


def bind_reliable_capture_envelope(
    payload: dict[str, Any], *, request_id: str, process_epoch: str, generation: int,
    service_instance_id: str, capture_sequence: int, client_nonce: str = "fixture-nonce",
    helper_build_identity: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind an offline raw hierarchy fixture with D envelope and transfer identities."""
    if not isinstance(payload, dict) or not request_id or not process_epoch or not service_instance_id:
        raise ValueError("capture fixture identity is incomplete")
    if any(type(value) is not int or value <= 0
           for value in (generation, capture_sequence)):
        raise ValueError("capture fixture generation and sequence must be positive integers")
    result = deepcopy(payload)
    result["reqId"] = request_id
    root_ref = result.get("traversalRootRef")
    match = __import__("re").fullmatch(r"windows\[(\d+)\]\.root", str(root_ref or ""))
    windows = result.get("windows")
    if match is None or not isinstance(windows, list):
        raise ValueError("capture fixture traversal root is invalid")
    root_index = int(match.group(1))
    if root_index >= len(windows) or not isinstance(windows[root_index], Mapping):
        raise ValueError("capture fixture root window is missing")
    root = windows[root_index].get("root")
    if not isinstance(root, Mapping):
        raise ValueError("capture fixture root is missing")
    root_digest = capture_canonical_sha256(root)
    envelope = {
        "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "canonicalization": CAPTURE_CANONICALIZATION_VERSION,
        "request_id": request_id, "process_epoch": process_epoch,
        "generation": generation, "service_instance_id": service_instance_id,
        "capture_sequence": capture_sequence, "root_ref": root_ref,
        "root_digest": root_digest,
    }
    projection = result.get("traversalCandidates")
    if not isinstance(projection, dict):
        raise ValueError("capture fixture candidate projection is missing")
    projection.pop("candidate_digest", None)
    projection["source_root_digest"] = root_digest
    projection["rootCaptureId"] = capture_root_id(envelope)
    projection_digest = capture_canonical_sha256(projection)
    projection["candidate_digest"] = projection_digest
    envelope["candidate_digest"] = projection_digest
    result["captureEnvelope"] = envelope
    result["traversalRootWindowId"] = root.get("windowId")
    projection["traversalRootRef"] = root_ref
    projection["traversalRootWindowId"] = root.get("windowId")
    # Root-ref/window edits above are part of the candidate digest; recompute once.
    projection.pop("candidate_digest", None)
    projection_digest = capture_canonical_sha256(projection)
    projection["candidate_digest"] = projection_digest
    envelope["candidate_digest"] = projection_digest
    transfer_identity = {
        "request_id": request_id, "client_nonce": client_nonce,
        "payload_schema_version": result.get("schemaVersion"),
        "process_epoch": process_epoch, "generation": generation,
        "service_instance_id": service_instance_id, "capture_sequence": capture_sequence,
        "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
        "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
        "helper_build_identity": dict(helper_build_identity or {"build_id": "fixture"}),
    }
    return result, {"header": deepcopy(transfer_identity), "control": deepcopy(transfer_identity)}


def add_full_screen_hierarchy_modal(raw: dict[str, Any], *, kind: str = "dialog",
                                    sequence: int = 1,
                                    request_id: str | None = None) -> dict[str, Any]:
    """Add a full-screen modal node to the captured tree, then bind that tree."""
    if kind not in {"dialog", "popup", "bottom_sheet", "permission_overlay", "full_screen_mode"}:
        raise ValueError("unsupported modal fixture kind")
    package = str(raw.get("package_name") or "pkg")
    root_bounds = raw.get("capture_root_bounds") or [0, 0, 1000, 1000]
    if not (isinstance(root_bounds, (list, tuple)) and len(root_bounds) == 4):
        root_bounds = [0, 0, 1000, 1000]
    left, top, right, bottom = (int(value) for value in root_bounds)
    class_name = {
        "dialog": "android.app.Dialog",
        "popup": "android.widget.PopupWindow",
        "bottom_sheet": "com.google.android.material.bottomsheet.BottomSheetDialog",
        "permission_overlay": "android.app.Dialog",
        "full_screen_mode": "android.app.Dialog",
    }[kind]
    node = {
        "viewIdResourceName": f"{package}:id/phase6d_full_screen_{kind}",
        "className": class_name, "text": "Permission required",
        "boundsInScreen": f"[{left},{top}][{right},{bottom}]",
        "visibleToUser": True, "enabled": True, "checked": False,
        "selected": False, "clickable": False, "focusable": False,
        "scrollable": False, "children": [],
    }
    raw.setdefault("nodes", []).append(node)
    attach_capture_authority(raw, sequence=sequence,
                             request_id=request_id or f"fixture-modal-{kind}-{sequence}")
    return raw


def bind_observation_marker(raw: dict[str, Any], marker: Mapping[str, Any]) -> dict[str, Any]:
    """Bind an offline fixture's actual action-clock marker to its envelope."""
    observed = deepcopy(dict(marker))
    raw["_exploration_observation"] = observed
    envelope = raw.get("production_observation_envelope")
    if isinstance(envelope, dict):
        envelope["observation"] = deepcopy(observed)
        envelope["capture_complete"] = True
        raw["production_observation_current"] = True
    return raw
