"""Typed, diagnostic-only provenance from a selected plugin card to its root.

This module records only runtime evidence.  It never grants plugin-context,
navigation, focus, visit, planner, or dispatch authority.  In particular a
card label, generic card resource ID, component, configuration digest, or
request/operation token is not an entity identity.
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
_TRUSTED_COMPONENT_SOURCES = {"window_current_focus", "activity_resumed"}


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


class EntryOperationEvidence(TypedDict, total=False):
    operation_id: str
    request_id: str | None
    request_id_status: str
    source_hierarchy_request_id: str
    source_hierarchy_capture_id: str
    source_candidate_nodes_sha256: str
    action_type: str
    dispatch_status: str
    operation_outcome: str
    native_boundary_status: str
    receipt_store_generation: str
    receipt_sequence: int
    receipt_match_count: int
    operation_started_at: str
    tap_point: list[int]
    point_inside_selected_bounds: bool
    navigation_event_kind: str
    navigation_epoch: int


class RootObservationEvidence(TypedDict, total=False):
    capture_id: str
    hierarchy_request_id: str
    hierarchy_snapshot_id: str
    hierarchy_capture_sequence: int
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


class EntityRootProvenance(TypedDict, total=False):
    schema_version: str
    scenario_id: str
    scenario_run_id: str | None
    navigation_epoch: int | None
    entry_attempts: list[dict[str, Any]]
    selected_entity: SelectedEntityEvidence
    entry_operation: EntryOperationEvidence
    resulting_root: RootObservationEvidence
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


def bind_hierarchy_transport_identity(raw: Mapping[str, Any], metadata: Any) -> dict[str, Any]:
    """Copy only the capture identifiers that match this observed request."""
    result = dict(raw)
    meta = metadata if isinstance(metadata, Mapping) else {}
    request_id = _scalar_text(raw.get("hierarchy_request_id"))
    metadata_request_id = _scalar_text(meta.get("reqId"))
    if request_id and request_id == metadata_request_id:
        result["hierarchy_snapshot_id"] = _scalar_text(meta.get("snapshotId"))
        sequence = meta.get("captureSequence")
        result["hierarchy_capture_sequence"] = sequence if type(sequence) is int and sequence > 0 else None
    else:
        result["hierarchy_snapshot_id"] = ""
        result["hierarchy_capture_sequence"] = None
    return result


def source_capture_evidence(client: Any, nodes: Any) -> dict[str, Any]:
    """Describe the exact validated candidate dump used to select a card."""
    metadata = getattr(client, "last_hierarchy_metadata", {})
    candidate = getattr(client, "last_dump_metadata", {})
    metadata = metadata if isinstance(metadata, Mapping) else {}
    candidate = candidate if isinstance(candidate, Mapping) else {}
    node_list = nodes if isinstance(nodes, list) else []
    request_id = _scalar_text(metadata.get("reqId"))
    candidate_request_id = _scalar_text(candidate.get("requestId"))
    capture_id = _scalar_text(metadata.get("snapshotId"))
    sequence = metadata.get("captureSequence")
    complete = bool(
        request_id and request_id == candidate_request_id and capture_id
        and type(sequence) is int and sequence > 0
        and candidate.get("transportMode") == "RELIABLE_FILE_PFD"
        and _scalar_text(candidate.get("candidateSchemaVersion"))
        and _scalar_text(candidate.get("candidateContractVersion"))
        and node_list
    )
    return {
        "hierarchy_request_id": request_id,
        "hierarchy_capture_id": capture_id,
        "hierarchy_capture_sequence": sequence if type(sequence) is int and sequence > 0 else None,
        "captured_at": _now(),
        "capture_complete": complete,
        "transport_mode": _scalar_text(candidate.get("transportMode")),
        "candidate_schema_version": _scalar_text(candidate.get("candidateSchemaVersion")),
        "candidate_contract_version": _scalar_text(candidate.get("candidateContractVersion")),
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
    source_request_id = _scalar_text(source_capture.get("hierarchy_request_id"))
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
    source_complete = source_capture.get("capture_complete") is True
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
        "source_hierarchy_capture_sequence": source_capture.get("hierarchy_capture_sequence"),
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
                             operation_started_at: str | None = None) -> EntryOperationEvidence:
    """Correlate one actual input-tap receipt; ADB input taps have no request ID."""
    from collections.abc import Mapping as MappingABC

    generation = _scalar_text(getattr(checkpoint, "store_generation", None))
    watermark = getattr(checkpoint, "receipt_watermark_before", None)
    op_id = _scalar_text(operation_id)
    receipts: list[dict[str, Any]] = []
    try:
        if store is not None and type(watermark) is int and generation:
            receipts = [dict(item) for item in store.receipts_after(watermark, operation_id=op_id)
                        if isinstance(item, MappingABC)]
    except Exception:
        receipts = []
    matching = [item for item in receipts if item.get("store_generation") == generation
                and item.get("operation_id") == op_id
                and item.get("request_id") in (None, "")
                and item.get("action_type") == "INPUT_TAP"
                and item.get("native_boundary_status") == "ENTERED"
                and item.get("dispatch_status") == "NATIVE_DISPATCH_ATTEMPTED"]
    point = [int(tap_point[0]), int(tap_point[1])] if tap_point is not None else []
    bounds = _parse_bounds(selected_bounds)
    inside = bool(point and bounds and bounds[0] <= point[0] <= bounds[2]
                  and bounds[1] <= point[1] <= bounds[3])
    receipt = matching[-1] if len(matching) == 1 else {}
    return EntryOperationEvidence(
        operation_id=op_id,
        request_id=None,
        request_id_status="ADB_INPUT_TAP_HAS_NO_REQUEST_ID",
        source_hierarchy_request_id=_scalar_text((source_capture or {}).get("hierarchy_request_id")),
        source_hierarchy_capture_id=_scalar_text((source_capture or {}).get("hierarchy_capture_id")),
        source_candidate_nodes_sha256=_scalar_text((source_capture or {}).get("candidate_nodes_sha256")),
        action_type="INPUT_TAP",
        dispatch_status="DISPATCHED" if receipt else "UNKNOWN",
        operation_outcome=("CALL_RETURNED_TRUE" if dispatch_succeeded else "CALL_RETURNED_FALSE_OR_RAISED"),
        native_boundary_status="ENTERED" if receipt else "UNKNOWN",
        receipt_store_generation=generation,
        receipt_sequence=receipt.get("receipt_seq") if receipt else None,
        receipt_match_count=len(matching),
        operation_started_at=str(operation_started_at or _now()),
        tap_point=point,
        point_inside_selected_bounds=inside,
        navigation_event_kind=_scalar_text(navigation_event_kind),
    )


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


def bind_resulting_root(provenance: EntityRootProvenance, raw: Mapping[str, Any], *,
                        scenario_run_id: str, current_navigation_epoch: int,
                        transition_summary: Mapping[str, Any], capture_current: bool) -> EntityRootProvenance:
    """Bind an independent current observation to the entry action, fail closed."""
    result = json.loads(json.dumps(provenance, ensure_ascii=False))
    selected = result.get("selected_entity") or {}
    action = result.get("entry_operation") or {}
    raw_capture = _scalar_text(raw.get("capture_id"))
    hierarchy_id = _scalar_text(raw.get("hierarchy_capture_id"))
    focus_id = _scalar_text(raw.get("focus_capture_id"))
    geometry_id = _scalar_text(raw.get("geometry_capture_id"))
    captured_at = _scalar_text(raw.get("timestamp"))
    package = _scalar_text(raw.get("package_name"))
    activity = _scalar_text(raw.get("activity_name"))
    source = _scalar_text(raw.get("context_source"))
    window = raw.get("window_evidence") if isinstance(raw.get("window_evidence"), Mapping) else {}
    window_component = _scalar_text(window.get("focused_window_component"))
    selected_refs = selected.get("runtime_entity_references") or []
    root_refs = _root_runtime_refs(raw)
    selected_types = selected.get("runtime_entity_types") or []
    root_types = _root_runtime_types(raw)
    summary = transition_summary if isinstance(transition_summary, Mapping) else {}
    transition_confirmed = bool(
        summary.get("open_completed") is True
        and summary.get("entry_contract_reason") == "success_verified"
        and summary.get("entry_contract_detail") == "plugin_open_verified"
        and summary.get("post_click_transition_same_screen") is False
        and bool(str(summary.get("post_click_transition_signal") or "").strip())
    )
    result["scenario_run_id"] = str(scenario_run_id or "") or None
    result["navigation_epoch"] = action.get("navigation_epoch")
    root: RootObservationEvidence = {
        "capture_id": raw_capture,
        "hierarchy_request_id": _scalar_text(raw.get("hierarchy_request_id")),
        "hierarchy_snapshot_id": _scalar_text(raw.get("hierarchy_snapshot_id")),
        "hierarchy_capture_sequence": raw.get("hierarchy_capture_sequence"),
        "captured_at": captured_at,
        "capture_status": "CURRENT_COMPLETE" if (
            capture_current is True and raw.get("snapshot_coherent") is True
            and raw.get("hierarchy_complete") is True and raw_capture
            and hierarchy_id == raw_capture and focus_id == raw_capture and geometry_id == raw_capture
            and _scalar_text(raw.get("hierarchy_request_id"))
            and _scalar_text(raw.get("hierarchy_snapshot_id"))
            and type(raw.get("hierarchy_capture_sequence")) is int
            and raw.get("hierarchy_capture_sequence") > 0
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
    if result.get("scenario_run_id") != raw.get("scenario_run_id"):
        reasons.append("RUN_MISMATCH")
    source_capture = selected.get("source_hierarchy_request_id")
    source_time = selected.get("source_capture_time")
    operation_started_at = action.get("operation_started_at")
    if (not source_capture or selected.get("status") != "OBSERVED"
            or not selected.get("source_hierarchy_capture_id")
            or not selected.get("source_candidate_nodes_sha256")):
        reasons.append("SOURCE_SELECTION_CAPTURE_INCOMPLETE")
    if (action.get("dispatch_status") != "DISPATCHED" or action.get("receipt_match_count") != 1
            or action.get("operation_outcome") != "CALL_RETURNED_TRUE"):
        reasons.append("ENTRY_OPERATION_RECEIPT_UNAVAILABLE")
    if not action.get("operation_id"):
        reasons.append("ENTRY_OPERATION_ID_MISSING")
    if action.get("navigation_event_kind") != "TAP":
        reasons.append("ENTRY_NAVIGATION_EVENT_UNBOUND")
    if action.get("point_inside_selected_bounds") is not True:
        reasons.append("ENTRY_POINT_NOT_BOUND_TO_SELECTED_NODE")
    if type(action.get("navigation_epoch")) is not int or action.get("navigation_epoch") != current_navigation_epoch:
        reasons.append("NAVIGATION_EPOCH_CHANGED")
    if root["capture_status"] != "CURRENT_COMPLETE":
        reasons.append("RESULT_CAPTURE_INCOMPLETE_OR_STALE")
    if not package or package != "com.samsung.android.oneconnect" or not activity:
        reasons.append("CURRENT_PLUGIN_COMPONENT_UNPROVEN")
    if source not in _TRUSTED_COMPONENT_SOURCES:
        reasons.append("CURRENT_COMPONENT_SOURCE_UNTRUSTED")
    explicit_window_match = window.get("focused_activity_matches")
    component_matches_window = (
        explicit_window_match is True if type(explicit_window_match) is bool else bool(
            window_component == activity or window_component == f"{package}/{activity}"
        )
    )
    if not component_matches_window:
        reasons.append("CURRENT_WINDOW_COMPONENT_UNPROVEN")
    if not transition_confirmed:
        reasons.append("ENTRY_TRANSITION_UNCONFIRMED")
    if not captured_at or not operation_started_at or (
            source_time and operation_started_at and source_time > operation_started_at):
        reasons.append("CAPTURE_ACTION_TIME_ORDER_INVALID")
    root_hierarchy_id = _scalar_text(raw.get("hierarchy_snapshot_id"))
    source_hierarchy_id = _scalar_text(selected.get("source_hierarchy_capture_id"))
    if (source_capture and _scalar_text(raw.get("hierarchy_request_id")) == source_capture) or (
            root_hierarchy_id and root_hierarchy_id == source_hierarchy_id):
        # A request-scoped source list dump cannot also be the independently
        # observed post-entry root capture.
        reasons.append("SOURCE_AND_RESULT_CAPTURE_NOT_DISTINCT")
    if "SCMainActivity" in activity:
        reasons.append("CURRENT_ROOT_IS_APP_HOME")

    one_selected = selected_refs[0] if len(selected_refs) == 1 else None
    one_root = root_refs[0] if len(root_refs) == 1 else None
    one_selected_type = selected_types[0] if len(selected_types) == 1 else None
    one_root_type = root_types[0] if len(root_types) == 1 else None
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
    result["authority"] = "DIAGNOSTIC_ONLY_NO_CONTEXT_OR_VISIT_AUTHORITY"
    return result


@dataclass
class PluginEntryProvenanceTracker:
    """Run-scoped recorder driven by the existing navigation guard callbacks."""

    scenario_id: str
    navigation_epoch: int = 0
    last_navigation_event: dict[str, Any] = field(default_factory=dict)
    source_capture: dict[str, Any] = field(default_factory=dict)
    provenance: EntityRootProvenance | None = None
    entry_attempts: list[dict[str, Any]] = field(default_factory=list)

    def invalidate(self) -> None:
        self.navigation_epoch += 1

    def observe_navigation(self, event: Any) -> None:
        self.last_navigation_event = dict(event) if isinstance(event, Mapping) else {"kind": "UNKNOWN"}

    def record_source_capture(self, evidence: Mapping[str, Any]) -> None:
        self.source_capture = dict(evidence) if isinstance(evidence, Mapping) else {}

    def record_selected_card(self, card: Mapping[str, Any], source_capture: Mapping[str, Any],
                             source_nodes: Any, operation: EntryOperationEvidence) -> EntityRootProvenance:
        selected = selected_entity_evidence(card, source_capture, source_nodes=source_nodes)
        action = dict(operation)
        action["navigation_epoch"] = self.navigation_epoch
        self.provenance = EntityRootProvenance(
            schema_version=PROVENANCE_SCHEMA,
            scenario_id=self.scenario_id,
            scenario_run_id=None,
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
                scenario_run_id=run_id,
                navigation_epoch=self.navigation_epoch,
                link_status="UNKNOWN",
                reason_codes=["SELECTED_ENTITY_ENTRY_ACTION_NOT_OBSERVED"],
                authority="DIAGNOSTIC_ONLY_NO_CONTEXT_OR_VISIT_AUTHORITY",
            )
        result = json.loads(json.dumps(self.provenance, ensure_ascii=False))
        if run_id:
            result["scenario_run_id"] = str(run_id)
        action = result.get("entry_operation") or {}
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
