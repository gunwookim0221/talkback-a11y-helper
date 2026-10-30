"""Typed entry provenance from a selected plugin card to its current root.

A resolved entry transaction establishes only the causal current root. It
never supplies semantic component identity or visit credit. Card labels,
generic resource IDs, component names, and operation tokens are not entity IDs.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Literal, TypedDict

PROVENANCE_SCHEMA = "phase6d3a-entity-root-provenance-v1"
ENTRY_DIAGNOSTICS_SCHEMA = "phase6d3a-entry-diagnostics-v1"
ROOT_AUTHORITY_RESOLVED = "ENTRY_TRANSACTION_RESOLVED"
ROOT_AUTHORITY_UNKNOWN = "UNKNOWN"
LinkStatus = Literal["VERIFIED_LINK", "PARTIAL_LINK", "UNKNOWN", "CONTRADICTORY"]

# These are the only fields treated as runtime entity identifiers.  Generic
# Android node IDs, accessibility paths, labels and scenario metadata do not
# participate.
_ENTITY_ID_KEYS = {
    "deviceid": "device_id", "device_id": "device_id",
    "entityid": "entity_id", "entity_id": "entity_id",
    "thingid": "thing_id", "thing_id": "thing_id",
}
_ENTITY_TYPE_KEYS = {
    "devicetype", "device_type", "entitytype", "entity_type",
    "plugintype", "plugin_type", "capabilitytype", "capability_type",
}
_TRUSTED_COMPONENT_SOURCES = {"helper_tree_component"}


class EntityReference(TypedDict):
    field: str
    value_sha256: str
    source: str


class SelectedEntityEvidence(TypedDict, total=False):
    status: str
    identity_kind: str
    node_locator_sha256: str
    source_hierarchy_request_id: str
    source_hierarchy_capture_id: str
    source_hierarchy_capture_sequence: int
    source_hierarchy_snapshot_id: str
    source_hierarchy_process_epoch: str
    source_hierarchy_generation: int
    source_hierarchy_service_instance_id: str
    source_hierarchy_root_ref: str
    source_hierarchy_window_id: int
    source_hierarchy_root_digest: str
    source_hierarchy_root_class_name: str | None
    source_hierarchy_root_source_node_id: str | None
    source_hierarchy_root_bounds: list[int] | None
    source_capture_authority: dict[str, Any]
    source_candidate_nodes_sha256: str
    source_capture_time: str
    source_capture_complete: bool
    selected_node_unique_in_source: bool
    resource_id: str
    class_name: str
    bounds: str
    visible_label_sha256: str
    identity_source: str
    runtime_entity_references: list[EntityReference]
    runtime_entity_types: list[str]
    source_evidence_run_id: str
    source_scenario_tx_id: str
    source_invocation_id: str


class EntryOperationEvidence(TypedDict, total=False):
    action_id: str
    operation_id: str
    checkpoint_operation_id: str
    receipt_checkpoint_status: str
    request_id: str | None
    request_id_status: str
    source_hierarchy_request_id: str
    source_hierarchy_capture_id: str
    source_hierarchy_snapshot_id: str
    source_hierarchy_capture_sequence: int
    source_hierarchy_process_epoch: str
    source_hierarchy_generation: int
    source_hierarchy_service_instance_id: str
    source_hierarchy_root_ref: str
    source_hierarchy_window_id: int
    source_hierarchy_root_digest: str
    source_hierarchy_root_class_name: str | None
    source_hierarchy_root_source_node_id: str | None
    source_hierarchy_root_bounds: list[int] | None
    source_capture_authority: dict[str, Any]
    source_candidate_nodes_sha256: str
    evidence_run_id: str
    scenario_tx_id: str
    invocation_id: str
    scenario_run_id: str
    source_navigation_epoch: int | None
    receipt_watermark_before: int | None
    action_type: str
    dispatch_status: str
    operation_outcome: str
    native_boundary_status: str
    receipt_store_generation: str
    receipt_sequence: int
    receipt_match_count: int
    native_receipt_status: str
    native_receipt: dict[str, Any] | None
    dispatch_result_status: str
    operation_started_at: str
    operation_finished_at: str
    tap_point: list[int]
    point_inside_selected_bounds: bool
    navigation_event_kind: str
    navigation_epoch: int


class RootObservationEvidence(TypedDict, total=False):
    entry_action_id: str
    entry_operation_id: str
    capture_id: str
    hierarchy_request_id: str
    hierarchy_snapshot_id: str
    hierarchy_capture_sequence: int
    hierarchy_process_epoch: str
    hierarchy_generation: int
    hierarchy_service_instance_id: str
    traversal_root_ref: str
    traversal_root_window_id: int
    traversal_root_digest: str
    traversal_root_class_name: str | None
    traversal_root_source_node_id: str | None
    traversal_root_bounds: list[int] | None
    capture_authority: dict[str, Any]
    source_result_capture_distinct: bool
    captured_at: str
    capture_status: str
    package_name: str
    activity_name: str
    component_source: str
    focused_window_component: str
    runtime_entity_references: list[EntityReference]
    runtime_entity_types: list[str]
    navigation_epoch: int
    transition_confirmed: bool
    transition_signal: str
    scenario_run_id: str
    evidence_run_id: str
    scenario_tx_id: str
    invocation_id: str
    source_result_generation_distinct: bool


class EntityRootProvenance(TypedDict, total=False):
    schema_version: str
    scenario_id: str
    scenario_run_id: str | None
    navigation_epoch: int | None
    entry_attempts: list[dict[str, Any]]
    selected_entity: SelectedEntityEvidence
    entry_operation: EntryOperationEvidence
    resulting_root: RootObservationEvidence
    semantic_component_identity: str
    root_authority: str
    root_authority_evidence: dict[str, Any]
    link_status: LinkStatus
    reason_codes: list[str]
    authority: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    value = str(value).strip()
    return value[:512] if value else ""


def _sha256_identity(field_name: str, value: Any) -> str:
    text = _scalar_text(value)
    if not text:
        return ""
    return hashlib.sha256((field_name + "\0" + text).encode("utf-8")).hexdigest()


def _canonical_sha256(value: Any) -> str:
    try:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(payload).hexdigest()


def bind_hierarchy_transport_identity(raw: Mapping[str, Any], metadata: Any = None) -> dict[str, Any]:
    """Copy identifiers from the frozen decoded capture, never mutable client metadata."""
    result = dict(raw)
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
    authority = validate_capture_authority(raw.get("capture_authority"))
    if authority is None or raw.get("capture_id") != authority.capture_key:
        for key in (
            "hierarchy_request_id", "hierarchy_snapshot_id", "hierarchy_capture_sequence",
            "hierarchy_process_epoch", "hierarchy_generation", "hierarchy_service_instance_id",
            "traversal_root_ref", "traversal_root_window_id", "traversal_root_digest",
            "traversal_root_class_name", "traversal_root_source_node_id", "traversal_root_bounds",
            "hierarchy_root_digest", "hierarchy_root_class_name", "hierarchy_root_source_node_id",
            "hierarchy_root_bounds",
        ):
            result[key] = (None if key.endswith(("sequence", "generation", "window_id", "_bounds",
                                                 "_class_name", "_source_node_id")) else "")
        return result
    result["hierarchy_request_id"] = authority.request_id
    result["hierarchy_snapshot_id"] = authority.capture_key
    result["hierarchy_capture_sequence"] = authority.capture_sequence
    result["hierarchy_process_epoch"] = authority.process_epoch
    result["hierarchy_generation"] = authority.generation
    result["hierarchy_service_instance_id"] = authority.service_instance_id
    result["traversal_root_ref"] = authority.root_ref
    result["traversal_root_window_id"] = authority.hierarchy_window_id
    result["traversal_root_digest"] = authority.root_digest
    result["traversal_root_class_name"] = authority.hierarchy_root_class_name
    result["traversal_root_source_node_id"] = authority.hierarchy_root_source_node_id
    result["traversal_root_bounds"] = (list(authority.hierarchy_root_bounds)
                                       if authority.hierarchy_root_bounds is not None else None)
    result["hierarchy_root_digest"] = authority.root_digest
    result["hierarchy_root_class_name"] = authority.hierarchy_root_class_name
    result["hierarchy_root_source_node_id"] = authority.hierarchy_root_source_node_id
    result["hierarchy_root_bounds"] = result["traversal_root_bounds"]
    return result


def evidence_invocation_identity(client: Any, scenario_id: str = "") -> dict[str, str]:
    """Read run and scenario-transaction IDs from the existing EvidenceRuntime."""
    runtime = getattr(client, "evidence_runtime", None)
    active_scenario = _scalar_text(getattr(client, "_active_evidence_scenario_id", ""))
    active_tx = _scalar_text(getattr(client, "_active_evidence_scenario_tx_id", ""))
    expected_scenario = _scalar_text(scenario_id or active_scenario)
    run_id = _scalar_text(getattr(runtime, "run_id", None))
    if (getattr(runtime, "is_enabled", False) is not True
            or not expected_scenario or active_scenario != expected_scenario
            or not run_id or not active_tx):
        return {"evidence_run_id": "", "scenario_tx_id": "", "invocation_id": ""}
    return {"evidence_run_id": run_id, "scenario_tx_id": active_tx,
            "invocation_id": active_tx}


def source_capture_evidence(client: Any, nodes: Any) -> dict[str, Any]:
    """Describe candidate selection from the immutable decoded snapshot."""
    snapshot = getattr(client, "_last_traversal_candidate_snapshot", None)
    decoded = getattr(snapshot, "decoded", None)
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
    authority = validate_capture_authority(getattr(decoded, "capture_authority", None))
    node_list = nodes if isinstance(nodes, list) else []
    snapshot_nodes = getattr(snapshot, "candidates", ())
    request_id = authority.request_id if authority is not None else ""
    candidate_nodes = [dict(node) for node in snapshot_nodes if isinstance(node, Mapping)]
    candidate = getattr(decoded, "traversal_candidates", None)
    complete = bool(
        authority is not None and getattr(decoded, "capability_verified", False) is True
        and getattr(decoded, "request_id", None) == authority.request_id
        and candidate_nodes == node_list
        and candidate is not None and getattr(candidate, "complete", False) is True
        and node_list
    )
    return {
        "hierarchy_request_id": request_id,
        "hierarchy_capture_id": authority.capture_key if authority is not None else "",
        "hierarchy_snapshot_id": authority.capture_key if authority is not None else "",
        "hierarchy_capture_sequence": authority.capture_sequence if authority is not None else None,
        "hierarchy_process_epoch": authority.process_epoch if authority is not None else "",
        "hierarchy_generation": authority.generation if authority is not None else None,
        "hierarchy_service_instance_id": authority.service_instance_id if authority is not None else "",
        "traversal_root_ref": authority.root_ref if authority is not None else "",
        "traversal_root_window_id": authority.hierarchy_window_id if authority is not None else None,
        "traversal_root_digest": authority.root_digest if authority is not None else "",
        "traversal_root_class_name": authority.hierarchy_root_class_name if authority is not None else None,
        "traversal_root_source_node_id": authority.hierarchy_root_source_node_id if authority is not None else None,
        "traversal_root_bounds": (list(authority.hierarchy_root_bounds)
                                  if authority is not None and authority.hierarchy_root_bounds is not None
                                  else None),
        "capture_authority": authority.to_dict() if authority is not None else None,
        **evidence_invocation_identity(client),
        "captured_at": _now(),
        "capture_complete": complete,
        "transport_mode": "RELIABLE_FILE_PFD" if complete else "",
        "candidate_schema_version": _scalar_text(getattr(candidate, "schema_version", "")),
        "candidate_contract_version": _scalar_text(getattr(candidate, "contract_version", "")),
        "candidate_nodes_sha256": _canonical_sha256(node_list),
    }


def _entity_refs(nodes: Any, *, source: str, recursive: bool) -> list[EntityReference]:
    if isinstance(nodes, Mapping):
        pending = [nodes]
    elif isinstance(nodes, (list, tuple)):
        pending = list(nodes)
    else:
        pending = []
    refs: dict[tuple[str, str], EntityReference] = {}
    while pending:
        node = pending.pop(0)
        if not isinstance(node, Mapping):
            continue
        for key, value in node.items():
            field_name = _ENTITY_ID_KEYS.get(str(key).casefold())
            digest = _sha256_identity(field_name or "", value) if field_name else ""
            if field_name and digest:
                refs[(field_name, digest)] = EntityReference(
                    field=field_name, value_sha256=digest, source=source,
                )
        if recursive:
            children = node.get("children")
            if isinstance(children, (list, tuple)):
                pending.extend(children)
    return [refs[key] for key in sorted(refs)]


def _entity_types(nodes: Any, *, recursive: bool) -> list[str]:
    if isinstance(nodes, Mapping):
        pending = [nodes]
    elif isinstance(nodes, (list, tuple)):
        pending = list(nodes)
    else:
        pending = []
    values: set[str] = set()
    while pending:
        node = pending.pop(0)
        if not isinstance(node, Mapping):
            continue
        for key, value in node.items():
            if str(key).casefold() not in _ENTITY_TYPE_KEYS:
                continue
            text = re.sub(r"[^a-z0-9]+", "", _scalar_text(value).casefold())
            if text:
                values.add(text)
        if recursive:
            children = node.get("children")
            if isinstance(children, (list, tuple)):
                pending.extend(children)
    return sorted(values)


def _parse_bounds(value: Any) -> tuple[int, int, int, int] | None:
    if isinstance(value, (tuple, list)) and len(value) == 4:
        try:
            return tuple(int(item) for item in value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    match = re.fullmatch(r"\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*", str(value or ""))
    return tuple(int(item) for item in match.groups()) if match else None


def _label(node: Mapping[str, Any]) -> str:
    for key in ("text", "contentDescription", "talkbackLabel", "mergedLabel", "label"):
        text = _scalar_text(node.get(key))
        if text:
            return text[:256]
    return ""


def _selected_scope_nodes(node: Mapping[str, Any], source_nodes: Any) -> list[Mapping[str, Any]]:
    """Collect only the selected node and source-capture descendants it owns."""
    scope: list[Mapping[str, Any]] = [node]
    card_path = _scalar_text(node.get("stable_node_path"))
    if not card_path or not isinstance(source_nodes, list):
        return scope
    for candidate in source_nodes:
        if not isinstance(candidate, Mapping) or candidate is node:
            continue
        ancestors = candidate.get("ancestors")
        ancestor_match = isinstance(ancestors, (list, tuple)) and any(
            isinstance(parent, Mapping) and _scalar_text(parent.get("path")) == card_path
            for parent in ancestors
        )
        candidate_path = _scalar_text(candidate.get("stable_node_path"))
        descendant_path_match = bool(candidate_path.startswith(card_path + "."))
        if ancestor_match or descendant_path_match:
            scope.append(candidate)
    return scope


def selected_entity_evidence(card: Mapping[str, Any], source_capture: Mapping[str, Any], *,
                             source_nodes: Any = None) -> SelectedEntityEvidence:
    """Describe the exact observed card node without treating its locator as an entity ID."""
    node = card.get("node") if isinstance(card.get("node"), Mapping) else {}
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
    source_authority = validate_capture_authority(source_capture.get("capture_authority"))
    source_identity_bound = bool(
        source_authority is not None
        and source_capture.get("hierarchy_request_id") == source_authority.request_id
        and source_capture.get("hierarchy_capture_id") == source_authority.capture_key
        and source_capture.get("hierarchy_snapshot_id") == source_authority.capture_key
        and source_capture.get("hierarchy_capture_sequence") == source_authority.capture_sequence
        and source_capture.get("hierarchy_process_epoch") == source_authority.process_epoch
        and source_capture.get("hierarchy_generation") == source_authority.generation
        and source_capture.get("hierarchy_service_instance_id") == source_authority.service_instance_id
        and source_capture.get("traversal_root_ref") == source_authority.root_ref
        and source_capture.get("traversal_root_window_id") == source_authority.hierarchy_window_id
        and source_capture.get("traversal_root_digest") == source_authority.root_digest
        and source_capture.get("traversal_root_class_name") == source_authority.hierarchy_root_class_name
        and source_capture.get("traversal_root_source_node_id") == source_authority.hierarchy_root_source_node_id
        and source_capture.get("traversal_root_bounds") == (list(source_authority.hierarchy_root_bounds)
                                                              if source_authority.hierarchy_root_bounds is not None else None)
    )
    source_request_id = source_authority.request_id if source_identity_bound else ""
    rid = _scalar_text(card.get("rid") or card.get("resource_id")
                       or node.get("viewIdResourceName") or node.get("resourceId"))
    class_name = _scalar_text(card.get("class_name") or node.get("className"))
    bounds = _scalar_text(card.get("bounds") or node.get("boundsInScreen") or node.get("bounds"))
    label = _scalar_text(card.get("stable_label") or _label(node))
    source_node_digest = _canonical_sha256(source_nodes if isinstance(source_nodes, list) else [])
    source_node_match = bool(
        isinstance(source_nodes, list) and node
        and source_node_digest
        and source_node_digest == _scalar_text(source_capture.get("candidate_nodes_sha256"))
        and sum(1 for item in source_nodes if isinstance(item, Mapping) and item == node) == 1
    )
    source_complete = source_capture.get("capture_complete") is True and source_identity_bound
    selected_scope = _selected_scope_nodes(node, source_nodes)
    locator_fields = {
        "source_hierarchy_request_id": source_request_id,
        "resource_id": rid,
        "class_name": class_name,
        "bounds": bounds,
        "visible_label_sha256": _sha256_identity("visible_label", label),
        "identity_source": _scalar_text(card.get("identity_source")),
    }
    locator = hashlib.sha256(json.dumps(locator_fields, sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()
    result: SelectedEntityEvidence = {
        "status": "OBSERVED" if (source_request_id and rid and bounds and label
                                   and source_complete and source_node_match) else "INCOMPLETE",
        "identity_kind": "CAPTURE_LOCAL_SELECTED_NODE_LOCATOR",
        "node_locator_sha256": locator,
        "source_hierarchy_request_id": source_request_id,
        "source_hierarchy_capture_id": _scalar_text(source_capture.get("hierarchy_capture_id")),
        "source_hierarchy_capture_sequence": (source_authority.capture_sequence if source_identity_bound else None),
        "source_hierarchy_snapshot_id": source_authority.capture_key if source_identity_bound else "",
        "source_hierarchy_process_epoch": source_authority.process_epoch if source_identity_bound else "",
        "source_hierarchy_generation": source_authority.generation if source_identity_bound else None,
        "source_hierarchy_service_instance_id": source_authority.service_instance_id if source_identity_bound else "",
        "source_hierarchy_root_ref": source_authority.root_ref if source_identity_bound else "",
        "source_hierarchy_window_id": source_authority.hierarchy_window_id if source_identity_bound else None,
        "source_hierarchy_root_digest": source_authority.root_digest if source_identity_bound else "",
        "source_hierarchy_root_class_name": source_authority.hierarchy_root_class_name if source_identity_bound else None,
        "source_hierarchy_root_source_node_id": source_authority.hierarchy_root_source_node_id if source_identity_bound else None,
        "source_hierarchy_root_bounds": (list(source_authority.hierarchy_root_bounds)
                                         if source_identity_bound and source_authority.hierarchy_root_bounds is not None
                                         else None),
        "source_evidence_run_id": _scalar_text(source_capture.get("evidence_run_id")),
        "source_scenario_tx_id": _scalar_text(source_capture.get("scenario_tx_id")),
        "source_invocation_id": _scalar_text(source_capture.get("invocation_id")),
        "source_capture_authority": source_authority.to_dict() if source_identity_bound else {},
        "source_candidate_nodes_sha256": _scalar_text(source_capture.get("candidate_nodes_sha256")),
        "source_capture_time": _scalar_text(source_capture.get("captured_at")),
        "source_capture_complete": source_complete,
        "selected_node_unique_in_source": source_node_match,
        "resource_id": rid,
        "class_name": class_name,
        "bounds": bounds,
        "visible_label_sha256": _sha256_identity("visible_label", label),
        "identity_source": _scalar_text(card.get("identity_source")),
        "runtime_entity_references": _entity_refs(selected_scope, source="selected_card_node", recursive=True),
        "runtime_entity_types": _entity_types(selected_scope, recursive=True),
    }
    return result


def entry_operation_evidence(*, operation_id: str, checkpoint: Any, store: Any,
                             dispatch_succeeded: bool, tap_point: tuple[int, int] | None,
                             selected_bounds: Any, source_capture: Mapping[str, Any] | None = None,
                             navigation_event_kind: str = "",
                             operation_started_at: str | None = None,
                             operation_finished_at: str | None = None) -> EntryOperationEvidence:
    """Correlate one input-tap action by its existing operation token and receipt."""
    from collections.abc import Mapping as MappingABC

    generation = _scalar_text(getattr(checkpoint, "store_generation", None))
    watermark = getattr(checkpoint, "receipt_watermark_before", None)
    checkpoint_operation_id = _scalar_text(getattr(checkpoint, "operation_id", None))
    checkpoint_status = _scalar_text(getattr(checkpoint, "checkpoint_status", None))
    op_id = _scalar_text(operation_id)
    receipts: list[dict[str, Any]] = []
    try:
        if (store is not None and type(watermark) is int and generation
                and checkpoint_status == "VALID" and checkpoint_operation_id == op_id):
            receipts = [dict(item) for item in store.receipts_after(watermark, operation_id=op_id)
                        if isinstance(item, MappingABC)]
    except Exception:
        receipts = []
    matching = [item for item in receipts if item.get("store_generation") == generation
                and item.get("operation_id") == op_id
                and item.get("action_type") == "INPUT_TAP"
                and item.get("native_boundary_status") == "ENTERED"
                and item.get("dispatch_status") == "NATIVE_DISPATCH_ATTEMPTED"]
    point = [int(tap_point[0]), int(tap_point[1])] if tap_point is not None else []
    bounds = _parse_bounds(selected_bounds)
    inside = bool(point and bounds and bounds[0] <= point[0] <= bounds[2]
                  and bounds[1] <= point[1] <= bounds[3])
    receipt = matching[0] if len(matching) == 1 else {}
    receipt_request_id = _scalar_text(receipt.get("request_id")) if receipt else ""
    return EntryOperationEvidence(
        action_id=op_id,
        operation_id=op_id,
        checkpoint_operation_id=checkpoint_operation_id,
        receipt_checkpoint_status=checkpoint_status,
        request_id=receipt_request_id or None,
        request_id_status=("MATCHED" if receipt_request_id else
                           "ADB_INPUT_TAP_HAS_NO_REQUEST_ID" if receipt else "UNKNOWN"),
        source_hierarchy_request_id=_scalar_text((source_capture or {}).get("hierarchy_request_id")),
        source_hierarchy_capture_id=_scalar_text((source_capture or {}).get("hierarchy_capture_id")),
        source_hierarchy_snapshot_id=_scalar_text((source_capture or {}).get("hierarchy_snapshot_id")),
        source_hierarchy_capture_sequence=((source_capture or {}).get("hierarchy_capture_sequence")),
        source_hierarchy_process_epoch=_scalar_text((source_capture or {}).get("hierarchy_process_epoch")),
        source_hierarchy_generation=(source_capture or {}).get("hierarchy_generation"),
        source_hierarchy_service_instance_id=_scalar_text((source_capture or {}).get("hierarchy_service_instance_id")),
        source_hierarchy_root_ref=_scalar_text((source_capture or {}).get("traversal_root_ref")),
        source_hierarchy_window_id=(source_capture or {}).get("traversal_root_window_id"),
        source_hierarchy_root_digest=_scalar_text((source_capture or {}).get("traversal_root_digest")),
        source_hierarchy_root_class_name=(source_capture or {}).get("traversal_root_class_name"),
        source_hierarchy_root_source_node_id=(source_capture or {}).get("traversal_root_source_node_id"),
        source_hierarchy_root_bounds=(source_capture or {}).get("traversal_root_bounds"),
        source_capture_authority=(deepcopy((source_capture or {}).get("capture_authority"))
                                  if isinstance((source_capture or {}).get("capture_authority"), Mapping) else {}),
        source_candidate_nodes_sha256=_scalar_text((source_capture or {}).get("candidate_nodes_sha256")),
        evidence_run_id=_scalar_text((source_capture or {}).get("evidence_run_id")),
        scenario_tx_id=_scalar_text((source_capture or {}).get("scenario_tx_id")),
        invocation_id=_scalar_text((source_capture or {}).get("invocation_id")),
        receipt_watermark_before=watermark if type(watermark) is int else None,
        action_type="INPUT_TAP",
        dispatch_status="DISPATCHED" if receipt else "UNKNOWN",
        operation_outcome=("CALL_RETURNED_TRUE" if dispatch_succeeded else "CALL_RETURNED_FALSE_OR_RAISED"),
        native_boundary_status="ENTERED" if receipt else "UNKNOWN",
        receipt_store_generation=generation,
        receipt_sequence=receipt.get("receipt_seq") if receipt else None,
        receipt_match_count=len(matching),
        native_receipt_status=("MATCHED" if len(matching) == 1 else
                               "AMBIGUOUS" if len(matching) > 1 else "UNAVAILABLE"),
        native_receipt=deepcopy(receipt) if len(matching) == 1 else None,
        dispatch_result_status=("CALL_RETURNED_TRUE" if dispatch_succeeded
                                else "CALL_RETURNED_FALSE_OR_RAISED"),
        operation_started_at=str(operation_started_at or "UNKNOWN"),
        operation_finished_at=str(operation_finished_at or "UNKNOWN"),
        tap_point=point,
        point_inside_selected_bounds=inside,
        navigation_event_kind=_scalar_text(navigation_event_kind),
    )


def _request_matches_native_receipt(action: Mapping[str, Any], receipt: Mapping[str, Any]) -> bool:
    """Accept this protocol's explicit no-request case; exact-match any supplied request."""
    request_id = _scalar_text(action.get("request_id"))
    receipt_request_id = _scalar_text(receipt.get("request_id"))
    status = _scalar_text(action.get("request_id_status"))
    if request_id:
        return status == "MATCHED" and request_id == receipt_request_id
    return (status == "ADB_INPUT_TAP_HAS_NO_REQUEST_ID"
            and not receipt_request_id)


def tap_dispatch_receipt_confirmation(action: Any, *, candidate_operation_correlated: bool) -> dict[str, Any]:
    """Report only an operation-matched native INPUT_TAP receipt; never infer from selection."""
    unknown = "UNKNOWN"
    evidence = action if isinstance(action, Mapping) else {}
    operation_id = evidence.get("operation_id") or unknown
    action_type = evidence.get("action_type") or unknown
    dispatch_status = evidence.get("dispatch_status") or unknown
    receipt_status = evidence.get("native_receipt_status") or unknown
    result_status = evidence.get("dispatch_result_status") or unknown
    raw_receipt = evidence.get("native_receipt")
    receipt = raw_receipt if isinstance(raw_receipt, Mapping) else {}

    receipt_fields = {}
    for key in ("operation_id", "action_type", "native_boundary_status", "dispatch_status",
                "receipt_seq", "store_generation", "request_id"):
        value = receipt.get(key)
        receipt_fields[key] = deepcopy(value) if value is not None and value != "" else unknown

    required_result = result_status in {"CALL_RETURNED_TRUE", "CALL_RETURNED_FALSE_OR_RAISED"}
    receipt_present = isinstance(raw_receipt, Mapping)
    receipt_mismatch = receipt_present and (
        (operation_id != unknown and receipt_fields["operation_id"] != unknown
         and receipt_fields["operation_id"] != operation_id)
        or (receipt_fields["action_type"] != unknown and receipt_fields["action_type"] != "INPUT_TAP")
        or (receipt_fields["native_boundary_status"] != unknown
            and receipt_fields["native_boundary_status"] != "ENTERED")
        or (receipt_fields["dispatch_status"] != unknown
            and receipt_fields["dispatch_status"] != "NATIVE_DISPATCH_ATTEMPTED")
    )
    if action_type not in {unknown, "INPUT_TAP"}:
        status = "NOT_INPUT_TAP"
    elif receipt_mismatch:
        status = "CONTRADICTORY"
    elif (
        candidate_operation_correlated
        and operation_id != unknown
        and action_type == "INPUT_TAP"
        and dispatch_status == "DISPATCHED"
        and receipt_status == "MATCHED"
        and receipt_present
        and not receipt_mismatch
        and receipt_fields["operation_id"] == operation_id
        and receipt_fields["action_type"] == "INPUT_TAP"
        and receipt_fields["native_boundary_status"] == "ENTERED"
        and receipt_fields["dispatch_status"] == "NATIVE_DISPATCH_ATTEMPTED"
        and receipt_fields["receipt_seq"] != unknown
        and receipt_fields["store_generation"] != unknown
        and evidence.get("receipt_store_generation") == receipt_fields["store_generation"]
        and evidence.get("receipt_sequence") == receipt_fields["receipt_seq"]
        and required_result
    ):
        status = "MATCHED"
    else:
        status = unknown

    return {
        "status": status,
        "operation_id": operation_id,
        "action_type": action_type,
        "dispatch_status": dispatch_status,
        "native_receipt_status": receipt_status,
        "native_receipt": receipt_fields,
        "result_status": result_status,
    }


def _root_runtime_refs(raw: Mapping[str, Any]) -> list[EntityReference]:
    nodes = raw.get("nodes")
    if not isinstance(nodes, (list, tuple)):
        return []
    visible = [node for node in nodes if isinstance(node, Mapping)
               and node.get("visibleToUser", node.get("isVisibleToUser", True)) is not False]
    return _entity_refs(visible, source="current_plugin_root", recursive=False)


def _root_runtime_types(raw: Mapping[str, Any]) -> list[str]:
    nodes = raw.get("nodes")
    if not isinstance(nodes, (list, tuple)):
        return []
    visible = [node for node in nodes if isinstance(node, Mapping)
               and node.get("visibleToUser", node.get("isVisibleToUser", True)) is not False]
    return _entity_types(visible, recursive=False)


_PLUGIN_BODY_ANCHOR_PATTERN = re.compile(
    r"(?:CapabilityCardView|PluginBody(?:View)?|PluginContent(?:View)?)", re.IGNORECASE,
)


def _current_plugin_body_anchor(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Find a structural plugin-body anchor in this hierarchy capture only.

    Scenario/tab anchors describe where navigation started. They are not body
    evidence. A visible plugin capability/body resource in the current
    captured hierarchy is the positive anchor used by entry provenance.
    """
    nodes = raw.get("nodes")
    if not isinstance(nodes, (list, tuple)):
        return {"status": "MISSING", "candidate_count": 0, "resource_ids": []}
    matches: set[str] = set()
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        if node.get("visibleToUser", node.get("isVisibleToUser", True)) is False:
            continue
        resource_id = _scalar_text(node.get("viewIdResourceName") or node.get("resourceId"))
        class_name = _scalar_text(node.get("className") or node.get("class"))
        anchor = resource_id or class_name
        if anchor and _PLUGIN_BODY_ANCHOR_PATTERN.search(anchor):
            matches.add(anchor)
    return {
        "status": "MATCHED" if matches else "MISSING",
        "candidate_count": len(matches),
        "resource_ids": sorted(matches)[:16],
    }


def bind_resulting_root(provenance: EntityRootProvenance, raw: Mapping[str, Any], *,
                        scenario_run_id: str, current_navigation_epoch: int,
                        transition_summary: Mapping[str, Any], capture_current: bool) -> EntityRootProvenance:
    """Bind an independent current observation to the entry action, fail closed."""
    result = json.loads(json.dumps(provenance, ensure_ascii=False))
    selected = result.get("selected_entity") or {}
    action = result.get("entry_operation") or {}
    action_id = _scalar_text(action.get("action_id"))
    operation_id = _scalar_text(action.get("operation_id"))
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
    authority = validate_capture_authority(raw.get("capture_authority"))
    source_authority = validate_capture_authority(selected.get("source_capture_authority"))
    raw_capture = authority.capture_key if authority is not None else ""
    hierarchy_id = _scalar_text(raw.get("hierarchy_capture_id"))
    focus_id = _scalar_text(raw.get("focus_capture_id"))
    geometry_id = _scalar_text(raw.get("geometry_capture_id"))
    captured_at = _scalar_text(raw.get("timestamp"))
    result_identity_matches = bool(
        authority is not None
        and raw.get("capture_id") == authority.capture_key
        and raw.get("hierarchy_capture_id") == authority.capture_key
        and raw.get("hierarchy_request_id") == authority.request_id
        and raw.get("hierarchy_snapshot_id") == authority.capture_key
        and raw.get("hierarchy_capture_sequence") == authority.capture_sequence
        and raw.get("hierarchy_process_epoch") == authority.process_epoch
        and raw.get("hierarchy_generation") == authority.generation
        and raw.get("hierarchy_service_instance_id") == authority.service_instance_id
        and raw.get("package_name") == authority.hierarchy_package_name
        and raw.get("traversal_root_ref") == authority.root_ref
        and raw.get("traversal_root_window_id") == authority.hierarchy_window_id
        and raw.get("traversal_root_digest") == authority.root_digest
        and raw.get("traversal_root_class_name") == authority.hierarchy_root_class_name
        and raw.get("traversal_root_source_node_id") == authority.hierarchy_root_source_node_id
        and raw.get("traversal_root_bounds") == (list(authority.hierarchy_root_bounds)
                                                  if authority.hierarchy_root_bounds is not None else None)
        and raw.get("hierarchy_root_digest") == authority.root_digest
        and raw.get("hierarchy_root_class_name") == authority.hierarchy_root_class_name
        and raw.get("hierarchy_root_source_node_id") == authority.hierarchy_root_source_node_id
        and raw.get("hierarchy_root_bounds") == (list(authority.hierarchy_root_bounds)
                                                  if authority.hierarchy_root_bounds is not None else None)
    )
    source_identity_matches = bool(
        source_authority is not None
        and selected.get("source_hierarchy_request_id") == source_authority.request_id
        and selected.get("source_hierarchy_capture_id") == source_authority.capture_key
        and selected.get("source_hierarchy_snapshot_id") == source_authority.capture_key
        and selected.get("source_hierarchy_capture_sequence") == source_authority.capture_sequence
        and selected.get("source_hierarchy_process_epoch") == source_authority.process_epoch
        and selected.get("source_hierarchy_generation") == source_authority.generation
        and selected.get("source_hierarchy_service_instance_id") == source_authority.service_instance_id
        and selected.get("source_hierarchy_root_ref") == source_authority.root_ref
        and selected.get("source_hierarchy_window_id") == source_authority.hierarchy_window_id
        and selected.get("source_hierarchy_root_digest") == source_authority.root_digest
        and selected.get("source_hierarchy_root_class_name") == source_authority.hierarchy_root_class_name
        and selected.get("source_hierarchy_root_source_node_id") == source_authority.hierarchy_root_source_node_id
        and selected.get("source_hierarchy_root_bounds") == (list(source_authority.hierarchy_root_bounds)
                                                               if source_authority.hierarchy_root_bounds is not None else None)
        and action.get("source_hierarchy_request_id") == source_authority.request_id
        and action.get("source_hierarchy_capture_id") == source_authority.capture_key
        and action.get("source_hierarchy_snapshot_id") == source_authority.capture_key
        and action.get("source_hierarchy_capture_sequence") == source_authority.capture_sequence
        and action.get("source_hierarchy_process_epoch") == source_authority.process_epoch
        and action.get("source_hierarchy_generation") == source_authority.generation
        and action.get("source_hierarchy_service_instance_id") == source_authority.service_instance_id
        and action.get("source_hierarchy_root_ref") == source_authority.root_ref
        and action.get("source_hierarchy_window_id") == source_authority.hierarchy_window_id
        and action.get("source_hierarchy_root_digest") == source_authority.root_digest
        and action.get("source_hierarchy_root_class_name") == source_authority.hierarchy_root_class_name
        and action.get("source_hierarchy_root_source_node_id") == source_authority.hierarchy_root_source_node_id
        and action.get("source_hierarchy_root_bounds") == (list(source_authority.hierarchy_root_bounds)
                                                             if source_authority.hierarchy_root_bounds is not None else None)
        and action.get("source_capture_authority") == source_authority.to_dict()
    )
    package = _scalar_text(authority.hierarchy_package_name if result_identity_matches else None)
    # Activity and component source are absent from the producer authority.
    # Leave them empty; dumpsys fields below remain diagnostics only.
    activity = ""
    source = ""
    window = raw.get("window_evidence") if isinstance(raw.get("window_evidence"), Mapping) else {}
    window_component = _scalar_text(window.get("focused_window_component"))
    selected_refs = selected.get("runtime_entity_references") or []
    root_refs = _root_runtime_refs(raw)
    selected_types = selected.get("runtime_entity_types") or []
    root_types = _root_runtime_types(raw)
    summary = transition_summary if isinstance(transition_summary, Mapping) else {}
    summary_provenance = summary.get("entity_root_provenance")
    summary_provenance = summary_provenance if isinstance(summary_provenance, Mapping) else {}
    summary_action = summary_provenance.get("entry_operation")
    summary_action = summary_action if isinstance(summary_action, Mapping) else {}
    action_trace_matches = bool(
        summary_provenance.get("scenario_id") == result.get("scenario_id")
        and summary_provenance.get("scenario_run_id") == result.get("scenario_run_id")
        and summary_action.get("action_id") == action.get("action_id")
        and summary_action.get("operation_id") == action.get("operation_id")
        and summary_action.get("checkpoint_operation_id") == action.get("checkpoint_operation_id")
        and summary_action.get("receipt_checkpoint_status") == action.get("receipt_checkpoint_status")
        and summary_action.get("request_id") == action.get("request_id")
        and summary_action.get("action_type") == action.get("action_type")
        and summary_action.get("receipt_sequence") == action.get("receipt_sequence")
        and summary_action.get("source_hierarchy_capture_id") == action.get("source_hierarchy_capture_id")
        and summary_action.get("evidence_run_id") == action.get("evidence_run_id")
        and summary_action.get("scenario_tx_id") == action.get("scenario_tx_id")
    )
    current_root_captured = bool(
        capture_current is True and result_identity_matches
        and raw.get("snapshot_coherent") is True
        and raw.get("hierarchy_complete") is True and raw_capture
        and hierarchy_id == raw_capture
        and focus_id in {"", raw_capture}
        and geometry_id in {"", raw_capture}
    )
    body_anchor_confirmed = bool(
        summary.get("entry_contract_detail") == "plugin_open_verified"
        and summary.get("post_open_state") in (None, "", "PLUGIN_BODY")
        and current_root_captured
        and _current_plugin_body_anchor(raw).get("status") == "MATCHED"
    )
    transition_confirmed = bool(
        summary.get("open_completed") is True
        and summary.get("entry_contract_reason") == "success_verified"
        and summary.get("post_click_transition_same_screen") is False
        and bool(str(summary.get("post_click_transition_signal") or "").strip())
        and body_anchor_confirmed and action_trace_matches
    )
    bound_run_id = _scalar_text(result.get("scenario_run_id"))
    requested_run_id = _scalar_text(scenario_run_id)
    result["navigation_epoch"] = action.get("navigation_epoch")
    source_result_distinct = bool(
        source_authority is not None and authority is not None
        and source_authority.capture_key != authority.capture_key
        and source_authority.request_id != authority.request_id
    )
    source_result_generation_distinct = bool(
        source_authority is not None and authority is not None
        and type(source_authority.generation) is int and type(authority.generation) is int
        and source_authority.generation != authority.generation
        and type(source_authority.capture_sequence) is int and type(authority.capture_sequence) is int
        and authority.capture_sequence > source_authority.capture_sequence
        and source_authority.process_epoch == authority.process_epoch
        and source_authority.service_instance_id == authority.service_instance_id
    )
    root: RootObservationEvidence = {
        "entry_action_id": action_id,
        "entry_operation_id": operation_id,
        "capture_id": raw_capture,
        "hierarchy_request_id": _scalar_text(raw.get("hierarchy_request_id")),
        "hierarchy_snapshot_id": _scalar_text(raw.get("hierarchy_snapshot_id")),
        "hierarchy_capture_sequence": raw.get("hierarchy_capture_sequence"),
        "hierarchy_process_epoch": _scalar_text(raw.get("hierarchy_process_epoch")),
        "hierarchy_generation": raw.get("hierarchy_generation"),
        "hierarchy_service_instance_id": _scalar_text(raw.get("hierarchy_service_instance_id")),
        "traversal_root_ref": _scalar_text(raw.get("traversal_root_ref")),
        "traversal_root_window_id": raw.get("traversal_root_window_id"),
        "traversal_root_digest": _scalar_text(raw.get("traversal_root_digest")),
        "traversal_root_class_name": raw.get("traversal_root_class_name"),
        "traversal_root_source_node_id": raw.get("traversal_root_source_node_id"),
        "traversal_root_bounds": raw.get("traversal_root_bounds"),
        "capture_authority": authority.to_dict() if authority is not None else {},
        "source_result_capture_distinct": source_result_distinct,
        "source_result_generation_distinct": source_result_generation_distinct,
        "scenario_run_id": _scalar_text(raw.get("scenario_run_id")),
        "evidence_run_id": _scalar_text(raw.get("evidence_run_id")),
        "scenario_tx_id": _scalar_text(raw.get("scenario_tx_id")),
        "invocation_id": _scalar_text(raw.get("invocation_id")),
        "captured_at": captured_at,
        "capture_status": "CURRENT_COMPLETE" if (
            capture_current is True and result_identity_matches and raw.get("snapshot_coherent") is True
            and raw.get("hierarchy_complete") is True and raw_capture
            and hierarchy_id == raw_capture
            and (focus_id in {"", raw_capture}) and (geometry_id in {"", raw_capture})
        ) else "INCOMPLETE_OR_STALE",
        "package_name": package,
        "activity_name": activity,
        "component_source": source,
        "focused_window_component": window_component,
        "runtime_entity_references": root_refs,
        "runtime_entity_types": root_types,
        "navigation_epoch": current_navigation_epoch,
        "transition_confirmed": transition_confirmed,
        "transition_signal": _scalar_text(summary.get("post_click_transition_signal")),
    }
    result["resulting_root"] = root
    reasons: list[str] = []
    if result.get("scenario_id") != raw.get("scenario_id"):
        reasons.append("SCENARIO_MISMATCH")
    if (not bound_run_id or bound_run_id != requested_run_id
            or bound_run_id != _scalar_text(raw.get("scenario_run_id"))
            or action.get("scenario_run_id") != bound_run_id):
        reasons.append("RUN_MISMATCH")
    source_evidence_run_id = _scalar_text(selected.get("source_evidence_run_id"))
    source_scenario_tx_id = _scalar_text(selected.get("source_scenario_tx_id"))
    source_invocation_id = _scalar_text(selected.get("source_invocation_id"))
    if (not source_evidence_run_id or not source_scenario_tx_id
            or not source_invocation_id
            or _scalar_text(selected.get("source_scenario_run_id")) != bound_run_id
            or source_evidence_run_id != _scalar_text(action.get("evidence_run_id"))
            or source_scenario_tx_id != _scalar_text(action.get("scenario_tx_id"))
            or source_evidence_run_id != _scalar_text(raw.get("evidence_run_id"))
            or source_scenario_tx_id != _scalar_text(raw.get("scenario_tx_id"))
            or source_invocation_id != _scalar_text(action.get("invocation_id"))
            or source_invocation_id != _scalar_text(raw.get("invocation_id"))):
        reasons.append("ENTRY_INVOCATION_MISMATCH")
    source_capture = selected.get("source_hierarchy_request_id")
    source_time = selected.get("source_capture_time")
    operation_started_at = action.get("operation_started_at")
    operation_finished_at = action.get("operation_finished_at")
    if (not source_capture or selected.get("status") != "OBSERVED"
            or not source_identity_matches
            or not selected.get("source_candidate_nodes_sha256")):
        reasons.append("SOURCE_SELECTION_CAPTURE_INCOMPLETE")
    if not source_identity_matches or action.get("source_capture_authority") != (
            source_authority.to_dict() if source_authority is not None else None):
        reasons.append("ENTRY_OPERATION_SOURCE_CAPTURE_MISMATCH")
    if (action.get("dispatch_status") != "DISPATCHED" or action.get("receipt_match_count") != 1
            or action.get("operation_outcome") != "CALL_RETURNED_TRUE"):
        reasons.append("ENTRY_OPERATION_RECEIPT_UNAVAILABLE")
    receipt = action.get("native_receipt")
    receipt = receipt if isinstance(receipt, Mapping) else {}
    watermark = action.get("receipt_watermark_before")
    receipt_sequence = action.get("receipt_sequence")
    if type(watermark) is not int or type(receipt_sequence) is not int:
        reasons.append("ENTRY_RECEIPT_WATERMARK_UNAVAILABLE")
    elif receipt_sequence <= watermark:
        reasons.append("STALE_ENTRY_OPERATION_RECEIPT")
    if not action_id or action_id != operation_id:
        reasons.append("ENTRY_ACTION_ID_MISSING_OR_MISMATCHED")
    request_matches_receipt = _request_matches_native_receipt(action, receipt)
    if not request_matches_receipt:
        reasons.append("ENTRY_REQUEST_ID_MISMATCHED")
    checkpoint_matches_action = bool(
        action.get("receipt_checkpoint_status") == "VALID"
        and action.get("checkpoint_operation_id") == operation_id
    )
    if not checkpoint_matches_action:
        reasons.append("ENTRY_RECEIPT_CHECKPOINT_MISMATCH")
    receipt_matches_action = bool(
        action_id and action_id == operation_id
        and checkpoint_matches_action and request_matches_receipt
        and action.get("native_receipt_status") == "MATCHED"
        and action.get("receipt_match_count") == 1
        and action.get("action_type") == "INPUT_TAP"
        and action.get("operation_id")
        and receipt.get("operation_id") == action.get("operation_id")
        and receipt.get("action_type") == action.get("action_type")
        and receipt.get("receipt_seq") == receipt_sequence
        and receipt.get("store_generation") == action.get("receipt_store_generation")
        and receipt.get("native_boundary_status") == "ENTERED"
        and receipt.get("dispatch_status") == "NATIVE_DISPATCH_ATTEMPTED"
    )
    if not receipt_matches_action:
        reasons.append("ENTRY_OPERATION_RECEIPT_MISMATCH")
    if not action.get("operation_id"):
        reasons.append("ENTRY_OPERATION_ID_MISSING")
    if action.get("navigation_event_kind") != "TAP":
        reasons.append("ENTRY_NAVIGATION_EVENT_UNBOUND")
    if action.get("point_inside_selected_bounds") is not True:
        reasons.append("ENTRY_POINT_NOT_BOUND_TO_SELECTED_NODE")
    before_epoch = action.get("navigation_epoch_before")
    after_epoch = action.get("navigation_epoch_after_tap")
    source_epoch = action.get("source_navigation_epoch")
    if (type(before_epoch) is not int or type(after_epoch) is not int
            or type(source_epoch) is not int or source_epoch != before_epoch
            or after_epoch != before_epoch + 1
            or action.get("navigation_epoch") != after_epoch
            or current_navigation_epoch != after_epoch):
        reasons.append("ENTRY_NAVIGATION_GENERATION_UNCLEAR_OR_INTERVENED")
    if root["capture_status"] != "CURRENT_COMPLETE":
        reasons.append("RESULT_CAPTURE_INCOMPLETE_OR_STALE")
    if not package or package != "com.samsung.android.oneconnect":
        reasons.append("CURRENT_HIERARCHY_PACKAGE_UNPROVEN")
    # WMS Activity/window fields remain diagnostic-only. Distinct validated
    # root/source captures and matching runtime entity bytes can support this
    # diagnostic link without asserting Activity identity or context.
    if not transition_confirmed:
        reasons.append("ENTRY_TRANSITION_UNCONFIRMED")
    if (not captured_at or not operation_started_at or not operation_finished_at
            or (source_time and operation_started_at and source_time > operation_started_at)
            or operation_started_at > operation_finished_at
            or operation_finished_at > captured_at):
        reasons.append("CAPTURE_ACTION_TIME_ORDER_INVALID")
    if source_authority is not None and authority is not None and not source_result_distinct:
        reasons.append("SOURCE_AND_RESULT_CAPTURE_NOT_DISTINCT")
    if source_authority is not None and authority is not None and not source_result_generation_distinct:
        reasons.append("POST_ENTRY_GENERATION_UNCLEAR_OR_NOT_DISTINCT")
    one_selected = selected_refs[0] if len(selected_refs) == 1 else None
    one_root = root_refs[0] if len(root_refs) == 1 else None
    one_selected_type = selected_types[0] if len(selected_types) == 1 else None
    one_root_type = root_types[0] if len(root_types) == 1 else None
    # Semantic-link diagnostics are independent of the causal transaction.
    # Snapshot causal failures before adding any missing/mismatched entity-ID
    # reasons below.
    causal_reasons = set(reasons)
    if reasons:
        result["link_status"] = "UNKNOWN"
    elif not one_selected or not one_root or not one_selected_type or not one_root_type:
        reasons.append("RUNTIME_ENTITY_OR_DESTINATION_TYPE_NOT_EXPOSED")
        result["link_status"] = "PARTIAL_LINK"
    elif (one_selected.get("field") != one_root.get("field")
          or one_selected.get("value_sha256") != one_root.get("value_sha256")
          or one_selected_type != one_root_type):
        reasons.append("SELECTED_ENTITY_ROOT_IDENTITY_MISMATCH")
        result["link_status"] = "CONTRADICTORY"
    else:
        result["link_status"] = "VERIFIED_LINK"
    result["reason_codes"] = sorted(set(reasons))
    result["semantic_component_identity"] = (
        "RESOLVED" if result.get("link_status") == "VERIFIED_LINK" else "UNKNOWN"
    )
    proof = {
        "scenario_id": _scalar_text(result.get("scenario_id")),
        "scenario_run_id": bound_run_id,
        "evidence_run_id": _scalar_text(action.get("evidence_run_id")),
        "scenario_tx_id": _scalar_text(action.get("scenario_tx_id")),
        "action_id": action_id,
        "operation_id": operation_id,
        "checkpoint_operation_id": _scalar_text(action.get("checkpoint_operation_id")),
        "receipt_checkpoint_status": _scalar_text(action.get("receipt_checkpoint_status")),
        "request_id": action.get("request_id"),
        "request_id_status": _scalar_text(action.get("request_id_status")),
        "invocation_id": _scalar_text(action.get("invocation_id")),
        "source_invocation_id": source_invocation_id,
        "result_invocation_id": _scalar_text(raw.get("invocation_id")),
        "action_type": _scalar_text(action.get("action_type")),
        "operation_started_at": _scalar_text(action.get("operation_started_at")),
        "operation_finished_at": _scalar_text(action.get("operation_finished_at")),
        "receipt_sequence": receipt_sequence,
        "receipt_watermark_before": watermark,
        "receipt_store_generation": _scalar_text(action.get("receipt_store_generation")),
        "source_evidence_run_id": source_evidence_run_id,
        "source_scenario_tx_id": source_scenario_tx_id,
        "source_scenario_run_id": _scalar_text(selected.get("source_scenario_run_id")),
        "source_candidate_nodes_sha256": _scalar_text(selected.get("source_candidate_nodes_sha256")),
        "selected_node_locator_sha256": _scalar_text(selected.get("node_locator_sha256")),
        "source_captured_at": _scalar_text(selected.get("source_capture_time")),
        "source_capture_id": source_authority.capture_key if source_authority is not None else "",
        "source_request_id": source_authority.request_id if source_authority is not None else "",
        "source_generation": source_authority.generation if source_authority is not None else None,
        "source_capture_sequence": source_authority.capture_sequence if source_authority is not None else None,
        "result_capture_id": raw_capture,
        "result_request_id": authority.request_id if authority is not None else "",
        "result_captured_at": captured_at,
        "result_generation": authority.generation if authority is not None else None,
        "result_capture_sequence": authority.capture_sequence if authority is not None else None,
        "result_process_epoch": authority.process_epoch if authority is not None else "",
        "result_service_instance_id": authority.service_instance_id if authority is not None else "",
        "result_capture_status": root.get("capture_status"),
        "source_result_generation_distinct": source_result_generation_distinct,
        "navigation_epoch_before": before_epoch,
        "navigation_epoch_after_tap": after_epoch,
        "navigation_epoch": current_navigation_epoch,
        "plugin_body_anchor_verified": body_anchor_confirmed,
        "plugin_body_anchor_evidence": {
            **_current_plugin_body_anchor(raw),
            "capture_id": raw_capture if body_anchor_confirmed else "",
            "current": body_anchor_confirmed,
        },
        "entry_transition_confirmed": transition_confirmed,
        "reason_codes": sorted(causal_reasons),
    }
    result["root_authority"] = (
        ROOT_AUTHORITY_RESOLVED if not causal_reasons else ROOT_AUTHORITY_UNKNOWN
    )
    result["root_authority_evidence"] = proof
    result["authority"] = "DIAGNOSTIC_ONLY_NO_CONTEXT_OR_VISIT_AUTHORITY"
    return result


def root_authority_is_current(provenance: Any, raw: Any) -> bool:
    """Validate a resolved causal root against this exact current capture."""
    if not isinstance(provenance, Mapping) or not isinstance(raw, Mapping):
        return False
    if provenance.get("root_authority") != ROOT_AUTHORITY_RESOLVED:
        return False
    # Semantic identity is independent of causal root authority.
    # A contradictory or unobserved entity reference does not undo a
    # separately proven entry transaction.
    link_status = provenance.get("link_status")
    semantic_identity = provenance.get("semantic_component_identity")
    if not ((link_status == "VERIFIED_LINK" and semantic_identity == "RESOLVED")
            or (link_status in {"PARTIAL_LINK", "CONTRADICTORY"}
                and semantic_identity == "UNKNOWN")):
        return False
    selected = provenance.get("selected_entity")
    selected = selected if isinstance(selected, Mapping) else {}
    action = provenance.get("entry_operation")
    action = action if isinstance(action, Mapping) else {}
    root = provenance.get("resulting_root")
    root = root if isinstance(root, Mapping) else {}
    proof = provenance.get("root_authority_evidence")
    proof = proof if isinstance(proof, Mapping) else {}
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
    authority = validate_capture_authority(raw.get("capture_authority"))
    source_authority = validate_capture_authority(selected.get("source_capture_authority"))
    receipt = action.get("native_receipt")
    receipt = receipt if isinstance(receipt, Mapping) else {}
    watermark = action.get("receipt_watermark_before")
    sequence = action.get("receipt_sequence")
    result_capture = authority.capture_key if authority is not None else ""
    current = bool(
        authority is not None and source_authority is not None
        and provenance.get("scenario_id") == raw.get("scenario_id")
        and provenance.get("scenario_run_id")
        and provenance.get("scenario_run_id") == raw.get("scenario_run_id")
        and action.get("scenario_run_id") == raw.get("scenario_run_id")
        and selected.get("source_scenario_run_id") == raw.get("scenario_run_id")
        and bool(_scalar_text(selected.get("source_invocation_id")))
        and selected.get("source_invocation_id") == action.get("invocation_id") == raw.get("invocation_id")
        and selected.get("status") == "OBSERVED"
        and selected.get("source_capture_complete") is True
        and selected.get("selected_node_unique_in_source") is True
        and bool(selected.get("source_candidate_nodes_sha256"))
        and selected.get("source_evidence_run_id") == action.get("evidence_run_id")
        and selected.get("source_scenario_tx_id") == action.get("scenario_tx_id")
        and action.get("evidence_run_id") == raw.get("evidence_run_id")
        and action.get("scenario_tx_id") == raw.get("scenario_tx_id")
        and bool(action.get("action_id"))
        and action.get("action_id") == action.get("operation_id") == receipt.get("operation_id")
        and action.get("checkpoint_operation_id") == action.get("operation_id")
        and action.get("receipt_checkpoint_status") == "VALID"
        and action.get("action_type") == receipt.get("action_type") == "INPUT_TAP"
        and action.get("navigation_event_kind") == "TAP"
        and action.get("point_inside_selected_bounds") is True
        and _request_matches_native_receipt(action, receipt)
        and action.get("dispatch_status") == "DISPATCHED"
        and action.get("operation_outcome") == "CALL_RETURNED_TRUE"
        and receipt.get("native_boundary_status") == "ENTERED"
        and receipt.get("dispatch_status") == "NATIVE_DISPATCH_ATTEMPTED"
        and action.get("native_receipt_status") == "MATCHED"
        and action.get("receipt_match_count") == 1
        and type(watermark) is int and type(sequence) is int and sequence > watermark
        and receipt.get("receipt_seq") == sequence
        and receipt.get("store_generation") == action.get("receipt_store_generation")
        and action.get("receipt_store_generation")
        and action.get("navigation_event_kind") == "TAP"
        and type(action.get("navigation_epoch_before")) is int
        and type(action.get("source_navigation_epoch")) is int
        and action.get("source_navigation_epoch") == action.get("navigation_epoch_before")
        and type(action.get("navigation_epoch_after_tap")) is int
        and action.get("navigation_epoch_after_tap") == action.get("navigation_epoch_before") + 1
        and action.get("navigation_epoch") == action.get("navigation_epoch_after_tap")
        and proof.get("action_id") == action.get("action_id") == root.get("entry_action_id")
        and proof.get("operation_id") == action.get("operation_id") == root.get("entry_operation_id")
        and proof.get("checkpoint_operation_id") == action.get("checkpoint_operation_id")
        and proof.get("receipt_checkpoint_status") == action.get("receipt_checkpoint_status")
        and proof.get("request_id") == action.get("request_id")
        and proof.get("request_id_status") == action.get("request_id_status")
        and proof.get("invocation_id") == action.get("invocation_id")
        and proof.get("source_invocation_id") == selected.get("source_invocation_id")
        and proof.get("result_invocation_id") == raw.get("invocation_id")
        and proof.get("action_type") == action.get("action_type")
        and proof.get("operation_started_at") == action.get("operation_started_at")
        and proof.get("operation_finished_at") == action.get("operation_finished_at")
        and proof.get("receipt_sequence") == action.get("receipt_sequence")
        and proof.get("receipt_watermark_before") == action.get("receipt_watermark_before")
        and proof.get("receipt_store_generation") == action.get("receipt_store_generation")
        and proof.get("evidence_run_id") == action.get("evidence_run_id")
        and proof.get("scenario_tx_id") == action.get("scenario_tx_id")
        and proof.get("source_evidence_run_id") == selected.get("source_evidence_run_id")
        and proof.get("source_scenario_tx_id") == selected.get("source_scenario_tx_id")
        and proof.get("source_candidate_nodes_sha256") == selected.get("source_candidate_nodes_sha256")
        and proof.get("selected_node_locator_sha256") == selected.get("node_locator_sha256")
        and proof.get("source_captured_at") == selected.get("source_capture_time")
        and proof.get("source_scenario_run_id") == selected.get("source_scenario_run_id")
        and proof.get("scenario_run_id") == raw.get("scenario_run_id")
        and proof.get("result_capture_id") == result_capture == raw.get("capture_id")
        and proof.get("result_request_id") == authority.request_id == raw.get("hierarchy_request_id")
        and proof.get("result_captured_at") == raw.get("timestamp") == root.get("captured_at")
        and proof.get("result_generation") == authority.generation == raw.get("hierarchy_generation")
        and proof.get("result_capture_sequence") == authority.capture_sequence == raw.get("hierarchy_capture_sequence")
        and proof.get("result_process_epoch") == authority.process_epoch == raw.get("hierarchy_process_epoch")
        and proof.get("result_service_instance_id") == authority.service_instance_id == raw.get("hierarchy_service_instance_id")
        and proof.get("result_capture_status") == root.get("capture_status") == "CURRENT_COMPLETE"
        and proof.get("source_capture_id") == source_authority.capture_key
        and proof.get("source_request_id") == source_authority.request_id
        and proof.get("source_generation") == source_authority.generation
        and proof.get("source_capture_sequence") == source_authority.capture_sequence
        and action.get("source_capture_authority") == source_authority.to_dict()
        and proof.get("source_result_generation_distinct") is True
        and source_authority.generation != authority.generation
        and source_authority.capture_sequence < authority.capture_sequence
        and source_authority.process_epoch == authority.process_epoch
        and source_authority.service_instance_id == authority.service_instance_id
        and proof.get("plugin_body_anchor_verified") is True
        and proof.get("reason_codes") == []
        and proof.get("navigation_epoch") == action.get("navigation_epoch_after_tap")
        and root.get("capture_id") == raw.get("capture_id") == raw.get("hierarchy_capture_id")
        and raw.get("hierarchy_snapshot_id") == result_capture
        and raw.get("package_name") == authority.hierarchy_package_name
        and raw.get("traversal_root_ref") == authority.root_ref
        and raw.get("traversal_root_window_id") == authority.hierarchy_window_id
        and raw.get("snapshot_coherent") is True and raw.get("hierarchy_complete") is True
        and raw.get("focus_capture_id") in (None, "", result_capture)
        and raw.get("geometry_capture_id") in (None, "", result_capture)
        and raw.get("evidence_run_id") == proof.get("evidence_run_id")
        and raw.get("scenario_tx_id") == proof.get("scenario_tx_id")
        and raw.get("invocation_id") == proof.get("result_invocation_id")
        and raw.get("production_observation_current") is True
    )
    envelope = raw.get("production_observation_envelope")
    current = bool(current and isinstance(envelope, Mapping)
                   and envelope.get("capture_complete") is True
                   and envelope.get("capture_id") == result_capture
                   and envelope.get("capture_authority") == authority.to_dict()
                   and envelope.get("hierarchy_capture_id") == result_capture
                   and envelope.get("hierarchy_request_id") == authority.request_id
                   and envelope.get("scenario_run_id") == raw.get("scenario_run_id"))
    return current


def scroll_target_inventory(nodes: Any, *, limit: int = 64) -> list[dict[str, Any]]:
    """Return bounded, non-authoritative identifiers for visible scroll targets."""
    if not isinstance(nodes, (list, tuple)):
        return []
    bounded_limit = max(0, min(int(limit), 64))
    if bounded_limit == 0:
        return []
    result: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            continue
        raw_actions = node.get("actions", node.get("actionNames", ()))
        if isinstance(raw_actions, str):
            actions = [raw_actions]
        elif isinstance(raw_actions, (list, tuple, set)):
            actions = [str(item)[:64] for item in raw_actions]
        else:
            actions = []
        scroll_actions = sorted({item for item in actions if "scroll" in item.lower()})[:8]
        scrollable = node.get("scrollable") is True or node.get("isScrollable") is True
        if not scrollable and not scroll_actions:
            continue
        class_name = _scalar_text(node.get("className") or node.get("class_name"))
        resource_id = _scalar_text(node.get("viewIdResourceName") or node.get("resourceId"))
        bounds = _scalar_text(node.get("boundsInScreen") or node.get("bounds"))
        result.append({
            "index": index,
            "class_name": class_name,
            "resource_id": resource_id,
            "bounds": bounds,
            "scroll_actions": scroll_actions,
            "node_locator_sha256": _canonical_sha256({
                "index": index, "class_name": class_name,
                "resource_id": resource_id, "bounds": bounds,
            }),
        })
        if len(result) >= bounded_limit:
            break
    return result


@dataclass
class PluginEntryProvenanceTracker:
    """Run-scoped recorder driven by the existing navigation guard callbacks."""

    scenario_id: str
    scenario_run_id: str | None = None
    navigation_epoch: int = 0
    source_navigation_epoch: int | None = None
    last_navigation_event: dict[str, Any] = field(default_factory=dict)
    source_capture: dict[str, Any] = field(default_factory=dict)
    provenance: EntityRootProvenance | None = None
    entry_attempts: list[dict[str, Any]] = field(default_factory=list)
    diagnostic_events: list[dict[str, Any]] = field(default_factory=list)
    source_scroll_targets: list[dict[str, Any]] = field(default_factory=list)

    def invalidate(self) -> None:
        self.navigation_epoch += 1

    def observe_navigation(self, event: Any) -> None:
        self.last_navigation_event = dict(event) if isinstance(event, Mapping) else {"kind": "UNKNOWN"}

    def record_source_capture(self, evidence: Mapping[str, Any]) -> None:
        self.source_capture = dict(evidence) if isinstance(evidence, Mapping) else {}
        self.source_navigation_epoch = self.navigation_epoch

    def record_selected_card(self, card: Mapping[str, Any], source_capture: Mapping[str, Any],
                             source_nodes: Any, operation: EntryOperationEvidence) -> EntityRootProvenance:
        self.source_scroll_targets = scroll_target_inventory(source_nodes)
        selected = selected_entity_evidence(card, source_capture, source_nodes=source_nodes)
        action = dict(operation)
        action["scenario_run_id"] = _scalar_text(self.scenario_run_id) or None
        action["source_navigation_epoch"] = self.source_navigation_epoch
        action["navigation_epoch"] = self.navigation_epoch
        selected["source_scenario_run_id"] = _scalar_text(self.scenario_run_id) or None
        self.provenance = EntityRootProvenance(
            schema_version=PROVENANCE_SCHEMA,
            scenario_id=self.scenario_id,
            scenario_run_id=_scalar_text(self.scenario_run_id) or None,
            navigation_epoch=self.navigation_epoch,
            selected_entity=selected,
            entry_operation=action,
            link_status="UNKNOWN",
            reason_codes=["RESULTING_ROOT_NOT_CAPTURED"],
            authority="DIAGNOSTIC_ONLY_NO_CONTEXT_OR_VISIT_AUTHORITY",
        )
        attempt = self.snapshot()
        attempt.pop("entry_attempts", None)
        self.entry_attempts.append(attempt)
        del self.entry_attempts[:-16]
        return self.snapshot()

    def snapshot(self, run_id: str | None = None) -> EntityRootProvenance:
        if self.provenance is None:
            return EntityRootProvenance(
                schema_version=PROVENANCE_SCHEMA,
                scenario_id=self.scenario_id,
                scenario_run_id=_scalar_text(self.scenario_run_id) or None,
                navigation_epoch=self.navigation_epoch,
                link_status="UNKNOWN",
                reason_codes=["SELECTED_ENTITY_ENTRY_ACTION_NOT_OBSERVED"],
                authority="DIAGNOSTIC_ONLY_NO_CONTEXT_OR_VISIT_AUTHORITY",
            )
        result = json.loads(json.dumps(self.provenance, ensure_ascii=False))
        action = result.get("entry_operation") or {}
        if run_id and _scalar_text(result.get("scenario_run_id")) != _scalar_text(run_id):
            result["link_status"] = "UNKNOWN"
            reasons = set(result.get("reason_codes") or [])
            reasons.add("RUN_MISMATCH" if result.get("scenario_run_id") else "ENTRY_RUN_ID_UNBOUND")
            result["reason_codes"] = sorted(reasons)
        if (type(action.get("navigation_epoch")) is int
                and action.get("navigation_epoch") != self.navigation_epoch):
            result["link_status"] = "UNKNOWN"
            reasons = set(result.get("reason_codes") or [])
            reasons.add("NAVIGATION_EPOCH_CHANGED")
            result["reason_codes"] = sorted(reasons)
            root = result.get("resulting_root")
            if isinstance(root, dict):
                root["capture_status"] = "STALE_AFTER_NAVIGATION"
        result["entry_attempts"] = deepcopy(self.entry_attempts[-16:])
        return result

    def record_diagnostic(self, event_name: str, payload: Mapping[str, Any]) -> None:
        """Store observation only; diagnostic events never affect provenance decisions."""
        event = {
            "event": _scalar_text(event_name) or "unknown",
            "timestamp": _now(),
            "diagnostic_only": True,
            "payload": deepcopy(dict(payload)) if isinstance(payload, Mapping) else {},
        }
        self.diagnostic_events.append(event)
        del self.diagnostic_events[:-64]

    def diagnostic_snapshot(self, run_id: str | None = None) -> dict[str, Any]:
        """Serialize entry and transition evidence separately from policy authority."""
        provenance = self.snapshot(run_id)
        selected = provenance.get("selected_entity") or {}
        action = provenance.get("entry_operation") or {}
        root = provenance.get("resulting_root") or {}
        unknown = "UNKNOWN"
        selected_capture_id = selected.get("source_hierarchy_capture_id") or ""
        action_capture_id = action.get("source_hierarchy_capture_id") or ""
        candidate_observed = selected.get("status") == "OBSERVED"
        operation_id = action.get("operation_id") or ""
        candidate_operation_correlated = bool(
            candidate_observed and operation_id and selected_capture_id
            and selected_capture_id == action_capture_id
        )
        candidate_operation_status = (
            "CANDIDATE_OPERATION_CORRELATED" if candidate_operation_correlated
            else "UNPROVEN" if candidate_observed or operation_id else unknown
        )
        candidate_input_tap = {
            "status": candidate_operation_status,
            "correlation_scope": "CANDIDATE_TO_OPERATION_ONLY",
            "dispatch_receipt_confirmation": tap_dispatch_receipt_confirmation(
                action, candidate_operation_correlated=candidate_operation_correlated,
            ),
            "candidate": {
                "status": selected.get("status") or unknown,
                "node_locator_sha256": selected.get("node_locator_sha256") or unknown,
                "source_capture_id": selected_capture_id or unknown,
                "resource_id": selected.get("resource_id") or unknown,
                "class_name": selected.get("class_name") or unknown,
                "bounds": selected.get("bounds") or unknown,
                "visible_label_sha256": selected.get("visible_label_sha256") or unknown,
            },
            "coordinates": {
                "tap_point": deepcopy(action.get("tap_point")) or unknown,
                "candidate_bounds": selected.get("bounds") or unknown,
                "point_inside_candidate_bounds": action.get("point_inside_selected_bounds", unknown),
            },
            "operation": {
                "operation_id": operation_id or unknown,
                "action_type": action.get("action_type") or unknown,
                "dispatch_status": action.get("dispatch_status") or unknown,
                "native_receipt_status": action.get("native_receipt_status") or unknown,
                "native_receipt": (deepcopy(action.get("native_receipt"))
                                   if isinstance(action.get("native_receipt"), Mapping) else unknown),
                "result_status": action.get("dispatch_result_status") or unknown,
                "operation_started_at": action.get("operation_started_at") or unknown,
                "operation_finished_at": action.get("operation_finished_at") or unknown,
            },
        }
        entry_tap = next((event for event in reversed(self.diagnostic_events)
                          if isinstance(event, Mapping)
                          and event.get("event") == "entry_input_tap"
                          and isinstance(event.get("payload"), Mapping)
                          and (not operation_id
                               or event["payload"].get("operation_id") == operation_id)), None)
        entry_tap_payload = entry_tap.get("payload", {}) if isinstance(entry_tap, Mapping) else {}
        transition = next((event for event in reversed(self.diagnostic_events)
                           if isinstance(event, Mapping)
                           and event.get("event") == "post_tap_transition"
                           and isinstance(event.get("payload"), Mapping)
                           and (not operation_id
                                or event["payload"].get("operation_id") == operation_id)), None)
        transition_payload = transition.get("payload", {}) if isinstance(transition, Mapping) else {}
        pre_observation = action.get("pre_observation")
        if not isinstance(pre_observation, Mapping):
            pre_observation = entry_tap_payload.get("pre_observation", unknown)
        post_observation = transition_payload.get("post_observation", unknown)
        has_pre_observation = isinstance(pre_observation, Mapping)
        has_post_observation = isinstance(post_observation, Mapping)
        observations = {
            "status": ("OBSERVED" if has_pre_observation and has_post_observation
                       else "PARTIAL" if has_pre_observation or has_post_observation else unknown),
            "pre": deepcopy(pre_observation) if has_pre_observation else unknown,
            "post": deepcopy(post_observation) if has_post_observation else unknown,
        }
        return {
            "schema_version": ENTRY_DIAGNOSTICS_SCHEMA,
            "diagnostic_only": True,
            "scenario_id": str(self.scenario_id or "")[:128],
            "navigation_epoch": self.navigation_epoch,
            "selected_card": deepcopy(selected),
            "selected_card_coordinates": {
                "bounds": selected.get("bounds", ""),
                "tap_point": deepcopy(action.get("tap_point") or []),
                "point_inside_selected_bounds": action.get("point_inside_selected_bounds"),
            },
            "candidate_input_tap": candidate_input_tap,
            "pre_post_observations": observations,
            "entry_operation": deepcopy(action),
            "resulting_root": deepcopy(root),
            "link_status": provenance.get("link_status", "UNKNOWN"),
            "semantic_component_identity": provenance.get("semantic_component_identity", "UNKNOWN"),
            "root_authority": provenance.get("root_authority", ROOT_AUTHORITY_UNKNOWN),
            "root_authority_evidence": deepcopy(provenance.get("root_authority_evidence") or {}),
            "reason_codes": deepcopy(provenance.get("reason_codes") or []),
            "source_hierarchy_capture": {
                key: deepcopy(self.source_capture.get(key))
                for key in (
                    "hierarchy_request_id", "hierarchy_capture_id",
                    "hierarchy_capture_sequence", "capture_complete",
                    "candidate_nodes_sha256",
                )
            },
            "source_scroll_targets": deepcopy(self.source_scroll_targets),
            "entry_attempts": deepcopy(provenance.get("entry_attempts") or []),
            "events": deepcopy(self.diagnostic_events[-64:]),
        }

    def bind_current_root(self, raw: Mapping[str, Any], *, run_id: str,
                          summary: Mapping[str, Any], capture_current: bool) -> EntityRootProvenance:
        entry = self.snapshot(run_id)
        entry.pop("entry_attempts", None)
        self.provenance = bind_resulting_root(
            entry, raw, scenario_run_id=run_id,
            current_navigation_epoch=self.navigation_epoch,
            transition_summary=summary, capture_current=capture_current,
        )
        return self.snapshot(run_id)


def install_navigation_observer(client: Any, tracker: PluginEntryProvenanceTracker):
    """Context manager around an existing collection call, with no UI actions."""
    from tb_runner.plugin_context_contract import navigation_epoch_guard
    return navigation_epoch_guard(client, tracker.invalidate,
                                  navigation_observer=tracker.observe_navigation)
