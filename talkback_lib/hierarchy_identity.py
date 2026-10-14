"""Read-only identity metadata for captured AccessibilityService hierarchies.

The identifiers produced here are diagnostic and snapshot-local. They do not
establish cross-capture equivalence and must not be used to authorize actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from typing import Any, Callable


SCHEMA_NAME = "talkback.read_only_hierarchy_identity"
SCHEMA_VERSION = "1.0"

PRESENT = "PRESENT"
ABSENT_IN_SOURCE = "ABSENT_IN_SOURCE"
PARSE_FAILED = "PARSE_FAILED"
NOT_SUPPORTED_BY_SOURCE = "NOT_SUPPORTED_BY_SOURCE"

_SERVICE_V1_SUPPORTED = {
    "resource_id", "class_name", "text", "content_description", "bounds",
    "clickable", "focusable", "enabled", "selected", "accessibility_focused",
    "input_focused", "scrollable", "visible_to_user", "package", "window_id",
}

_ACTION_NAMES = {
    1: "ACTION_FOCUS",
    2: "ACTION_CLEAR_FOCUS",
    16: "ACTION_CLICK",
    32: "ACTION_LONG_CLICK",
    64: "ACTION_ACCESSIBILITY_FOCUS",
    128: "ACTION_CLEAR_ACCESSIBILITY_FOCUS",
    256: "ACTION_NEXT_AT_MOVEMENT_GRANULARITY",
    512: "ACTION_PREVIOUS_AT_MOVEMENT_GRANULARITY",
    1024: "ACTION_NEXT_HTML_ELEMENT",
    2048: "ACTION_PREVIOUS_HTML_ELEMENT",
    4096: "ACTION_SCROLL_FORWARD",
    8192: "ACTION_SCROLL_BACKWARD",
    16384: "ACTION_COPY",
    32768: "ACTION_PASTE",
    65536: "ACTION_CUT",
    131072: "ACTION_SET_SELECTION",
    2097152: "ACTION_SET_TEXT",
    16908344: "ACTION_SCROLL_UP",
    16908346: "ACTION_SCROLL_DOWN",
}


def _field_support(snapshot: dict[str, Any], field: str) -> bool:
    capabilities = snapshot.get("nodeMetadataCapabilities")
    if isinstance(capabilities, dict) and field in capabilities:
        return capabilities[field] is True
    if snapshot.get("schemaVersion") == "service-hierarchy-v1":
        return field in _SERVICE_V1_SUPPORTED
    return False


def _result(
    value: Any,
    status: str,
    *,
    source_field: str | None = None,
    derivation: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"value": value, "status": status}
    if source_field is not None:
        result["source_field"] = source_field
    if derivation is not None:
        result["derivation"] = derivation
    if reason is not None:
        result["reason"] = reason
    return result


def _parse_string(value: Any) -> tuple[Any, str]:
    if value is None or value == "":
        return value, ABSENT_IN_SOURCE
    if not isinstance(value, str):
        return None, PARSE_FAILED
    return value, PRESENT


def _parse_boolean(value: Any) -> tuple[Any, str]:
    if type(value) is not bool:
        return None, PARSE_FAILED
    return value, PRESENT


def _parse_window_id(value: Any) -> tuple[Any, str]:
    if type(value) is int and value >= 0:
        return value, PRESENT
    if value is None or value == -1:
        return None, ABSENT_IN_SOURCE
    return None, PARSE_FAILED


def _parse_bounds(value: Any) -> tuple[Any, str]:
    if value is None or value == "":
        return None, ABSENT_IN_SOURCE
    if isinstance(value, dict):
        aliases = (("left", "l"), ("top", "t"), ("right", "r"), ("bottom", "b"))
        parsed: list[int] = []
        for names in aliases:
            raw = next((value[name] for name in names if name in value), None)
            if type(raw) is not int:
                return None, PARSE_FAILED
            parsed.append(raw)
        return {"left": parsed[0], "top": parsed[1], "right": parsed[2], "bottom": parsed[3]}, PRESENT
    if isinstance(value, str):
        match = re.fullmatch(r"\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]\s*", value)
        if not match:
            return None, PARSE_FAILED
        left, top, right, bottom = (int(part) for part in match.groups())
        return {"left": left, "top": top, "right": right, "bottom": bottom}, PRESENT
    return None, PARSE_FAILED


def _read_field(
    node: dict[str, Any],
    snapshot: dict[str, Any],
    field: str,
    aliases: tuple[str, ...],
    parser: Callable[[Any], tuple[Any, str]],
) -> dict[str, Any]:
    source_field = next((key for key in aliases if key in node), None)
    if source_field is not None:
        value, status = parser(node[source_field])
        return _result(value, status, source_field=source_field)
    status = ABSENT_IN_SOURCE if _field_support(snapshot, field) else NOT_SUPPORTED_BY_SOURCE
    return _result(None, status, reason="source_field_not_present")


def _read_actions(node: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    source_field = next((key for key in ("actions", "actionList") if key in node), None)
    if source_field is None:
        status = ABSENT_IN_SOURCE if _field_support(snapshot, "actions") else NOT_SUPPORTED_BY_SOURCE
        return _result(None, status, reason="action_list_not_exposed")

    raw_actions = node[source_field]
    if not isinstance(raw_actions, list):
        return _result(None, PARSE_FAILED, source_field=source_field, reason="expected_list")

    actions: list[dict[str, Any]] = []
    for index, action in enumerate(raw_actions):
        if type(action) is int:
            action_id = action
            raw_name = None
            raw_label = None
            exactness = "IDS_ONLY"
        elif isinstance(action, dict) and type(action.get("id")) is int:
            action_id = action["id"]
            raw_name = action.get("name")
            raw_label = action.get("label")
            if raw_name is not None and not isinstance(raw_name, str):
                return _result(None, PARSE_FAILED, source_field=source_field, reason=f"invalid_action_name:{index}")
            if raw_label is not None and not isinstance(raw_label, str):
                return _result(None, PARSE_FAILED, source_field=source_field, reason=f"invalid_action_label:{index}")
            exactness = "ID_NAME_LABEL" if raw_name is not None or raw_label is not None else "ID_ONLY"
        else:
            return _result(None, PARSE_FAILED, source_field=source_field, reason=f"invalid_action:{index}")
        actions.append({
            "id": action_id,
            "raw_name": raw_name,
            "normalized_name": raw_name or _ACTION_NAMES.get(action_id, f"ACTION_{action_id}"),
            "raw_label": raw_label,
            "exactness": exactness,
        })
    return _result(actions, PRESENT, source_field=source_field, derivation="source_action_list_order_preserved")


def _walk_roots(snapshot: dict[str, Any]) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    windows = snapshot.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("HIERARCHY_IDENTITY:INVALID_WINDOWS")
    roots: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index, window in enumerate(windows):
        if not isinstance(window, dict) or not isinstance(window.get("root"), dict):
            raise ValueError(f"HIERARCHY_IDENTITY:INVALID_WINDOW_ROOT:{index}")
        roots.append((index, window, window["root"]))
    return roots


def _fingerprint_node(node: dict[str, Any]) -> dict[str, Any]:
    bounds, bounds_status = _parse_bounds(node.get("boundsInScreen", node.get("bounds")))
    actions = node.get("actions", node.get("actionList"))
    action_ids: list[int] | None = None
    if isinstance(actions, list):
        action_ids = []
        for action in actions:
            if type(action) is int:
                action_ids.append(action)
            elif isinstance(action, dict) and type(action.get("id")) is int:
                action_ids.append(action["id"])
            else:
                action_ids = None
                break
    children = node.get("children")
    if not isinstance(children, list):
        children = []
    return {
        "resource_id": node.get("viewIdResourceName") if isinstance(node.get("viewIdResourceName"), str) else None,
        "class_name": node.get("className") if isinstance(node.get("className"), str) else None,
        "package": node.get("packageName") if isinstance(node.get("packageName"), str) else None,
        "bounds": bounds if bounds_status == PRESENT else None,
        "clickable": node.get("clickable") if type(node.get("clickable")) is bool else None,
        "focusable": node.get("focusable") if type(node.get("focusable")) is bool else None,
        "enabled": node.get("enabled") if type(node.get("enabled")) is bool else None,
        "action_ids": action_ids,
        "children": [_fingerprint_node(child) for child in children if isinstance(child, dict)],
    }


def _snapshot_fingerprint(snapshot: dict[str, Any], roots: list[tuple[int, dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    normalized = {
        "schema_version": snapshot.get("schemaVersion"),
        "windows": [
            {
                "type": window.get("type"),
                "bounds": _parse_bounds(window.get("boundsInScreen"))[0],
                "root": _fingerprint_node(root),
            }
            for _index, window, root in roots
        ],
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {
        "algorithm": "sha256",
        "kind": "structural_snapshot_fingerprint",
        "value": hashlib.sha256(encoded).hexdigest(),
        "components": ["schema_version", "window_type", "window_bounds", "node_order", "resource_id", "class_name", "package", "bounds", "clickable", "focusable", "enabled", "action_ids"],
        "excludes": ["capture_id", "captured_at", "request_id", "text", "content_description", "focus_state", "selection_state", "window_id"],
        "authorization_use": "none",
    }


def build_hierarchy_identity_metadata(
    snapshot: dict[str, Any],
    *,
    capture_id: str | None = None,
    capture_sequence: int | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Build an additive metadata envelope without changing the source hierarchy."""
    if not isinstance(snapshot, dict) or snapshot.get("success") is not True:
        raise ValueError("HIERARCHY_IDENTITY:INVALID_SNAPSHOT")
    roots = _walk_roots(snapshot)
    capture_id = capture_id or str(uuid.uuid4())
    captured_at = captured_at or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    records: list[dict[str, Any]] = []
    node_by_id: dict[str, dict[str, Any]] = {}
    pending_lineage: list[dict[str, Any]] = []
    package_names: set[str] = set()
    parse_errors: list[str] = []

    def visit(
        node: dict[str, Any],
        *,
        window_index: int,
        window: dict[str, Any],
        path_parts: tuple[int, ...],
        sibling_index: int,
        parent_id: str | None,
        ancestor_ids: list[str],
    ) -> None:
        node_id = f"w{window_index}:" + ".".join(str(part) for part in path_parts)
        raw_children = node.get("children", [])
        children_valid = isinstance(raw_children, list)
        if not children_valid:
            parse_errors.append(f"{node_id}:children_not_list")
            raw_children = []
        valid_children = [child for child in raw_children if isinstance(child, dict)]
        if len(valid_children) != len(raw_children):
            parse_errors.append(f"{node_id}:child_not_object")

        fields = {
            "source_node_id": _read_field(node, snapshot, "source_node_id", ("sourceNodeId", "uniqueId"), _parse_string),
            "resource_id": _read_field(node, snapshot, "resource_id", ("viewIdResourceName", "resourceId"), _parse_string),
            "class_name": _read_field(node, snapshot, "class_name", ("className", "class"), _parse_string),
            "text": _read_field(node, snapshot, "text", ("text",), _parse_string),
            "content_description": _read_field(node, snapshot, "content_description", ("contentDescription", "content-desc"), _parse_string),
            "bounds": _read_field(node, snapshot, "bounds", ("boundsInScreen", "bounds"), _parse_bounds),
            "clickable": _read_field(node, snapshot, "clickable", ("clickable",), _parse_boolean),
            "focusable": _read_field(node, snapshot, "focusable", ("focusable",), _parse_boolean),
            "enabled": _read_field(node, snapshot, "enabled", ("enabled",), _parse_boolean),
            "selected": _read_field(node, snapshot, "selected", ("selected",), _parse_boolean),
            "accessibility_focused": _read_field(node, snapshot, "accessibility_focused", ("accessibilityFocused", "accessibility-focused"), _parse_boolean),
            "input_focused": _read_field(node, snapshot, "input_focused", ("inputFocused", "focused"), _parse_boolean),
            "scrollable": _read_field(node, snapshot, "scrollable", ("scrollable", "isScrollable"), _parse_boolean),
            "visible_to_user": _read_field(node, snapshot, "visible_to_user", ("visibleToUser", "isVisibleToUser"), _parse_boolean),
            "package": _read_field(node, snapshot, "package", ("packageName", "package"), _parse_string),
            "semantic_role": _read_field(node, snapshot, "semantic_role", ("role", "roleDescription"), _parse_string),
            "actions": _read_actions(node, snapshot),
            "node_window_id": _read_field(node, snapshot, "window_id", ("windowId",), _parse_window_id),
        }
        if fields["package"]["status"] == PRESENT:
            package_names.add(fields["package"]["value"])

        actual_window_id = _read_field(window, snapshot, "window_id", ("id",), _parse_window_id)
        node_window_id = fields["node_window_id"]
        if node_window_id["status"] == PRESENT:
            window_id = node_window_id
        elif actual_window_id["status"] == PRESENT:
            window_id = _result(actual_window_id["value"], PRESENT, source_field="windows[].id", derivation="window_membership")
        else:
            window_id = _result(None, actual_window_id["status"], source_field="windows[].id")

        child_ids = [f"w{window_index}:" + ".".join(str(part) for part in (*path_parts, index)) for index in range(len(valid_children))]
        clickable = fields["clickable"]["value"] is True
        focusable = fields["focusable"]["value"] is True
        actionable_by_flags = clickable or focusable
        record = {
            "snapshot_id": capture_id,
            "node_local_id": node_id,
            "source_node_id": fields["source_node_id"],
            "window_id": window_id,
            "strong_raw_identifiers": {
                "source_node_id": fields["source_node_id"],
                "resource_id": fields["resource_id"],
            },
            "structural_identifiers": {
                "node_local_id": _result(node_id, PRESENT, derivation="window_index_and_full_tree_child_order"),
                "window_index": _result(window_index, PRESENT, derivation="snapshot_windows_order"),
                "hierarchy_path": _result(list(path_parts), PRESENT, derivation="full_tree_child_order"),
                "depth": _result(len(path_parts) - 1, PRESENT, derivation="full_tree_depth"),
                "sibling_index": _result(sibling_index, PRESENT, derivation="source_children_order"),
            },
            "semantic_identifiers": {
                "resource_id": fields["resource_id"], "class_name": fields["class_name"],
                "text": fields["text"], "content_description": fields["content_description"],
                "semantic_role": fields["semantic_role"], "package": fields["package"],
            },
            "geometric_identifiers": {"bounds": fields["bounds"]},
            "action_metadata": {
                "actions": fields["actions"],
                "exactness": "SOURCE_ACTION_LIST" if fields["actions"]["status"] == PRESENT else fields["actions"]["status"],
                "clickable_flag_is_not_used_to_infer_actions": True,
            },
            "focus_metadata": {
                "raw_accessibility_focused": fields["accessibility_focused"],
                "raw_input_focused": fields["input_focused"],
                "production_qualified_focus_identity": _result(None, NOT_SUPPORTED_BY_SOURCE, reason="not_computed_by_read_only_metadata_parser"),
                "diagnostic_fallback_identity": _result(node_id, PRESENT, derivation="snapshot_local_structural_path", reason="diagnostic_only_not_production_focus_identity"),
                "rejection_reason": _result(None, NOT_SUPPORTED_BY_SOURCE, reason="no_focus_rejection_field_in_source"),
            },
            "lineage": {
                "parent_id": _result(parent_id, PRESENT if parent_id is not None else ABSENT_IN_SOURCE, derivation="full_tree_parent_relation"),
                "ordered_child_ids": _result(child_ids, PRESENT, derivation="full_tree_children_order"),
                "ancestor_ids_root_to_parent": _result(list(ancestor_ids), PRESENT, derivation="full_tree_parent_chain"),
                "actionable_by_flags": actionable_by_flags,
                "actionable_ancestor_ids": [],
                "actionable_descendant_ids": [],
                "clickable_descendant_ids": [],
                "focusable_descendant_ids": [],
                "summary_semantics": "clickable_or_focusable_flags_only_no_owner_canonicalization",
            },
            "provenance": {"fields": fields, "source": snapshot.get("source"), "source_schema_version": snapshot.get("schemaVersion")},
            "node_fingerprint": {
                "algorithm": "sha256",
                "kind": "snapshot_local_structural_node_fingerprint",
                "value": hashlib.sha256(json.dumps({"node_id": node_id, "resource_id": fields["resource_id"]["value"], "class_name": fields["class_name"]["value"], "bounds": fields["bounds"]["value"]}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
                "authorization_use": "none",
            },
        }
        records.append(record)
        node_by_id[node_id] = record
        pending_lineage.append({"record": record, "parent_id": parent_id, "ancestor_ids": list(ancestor_ids)})

        for order, child in enumerate(valid_children):
            visit(child, window_index=window_index, window=window, path_parts=(*path_parts, order), sibling_index=order,
                  parent_id=node_id, ancestor_ids=[*ancestor_ids, node_id])

    for window_index, window, root in roots:
        visit(root, window_index=window_index, window=window, path_parts=(0,), sibling_index=0,
              parent_id=None, ancestor_ids=[])

    for item in pending_lineage:
        record = item["record"]
        actionable_ancestors = [ancestor_id for ancestor_id in item["ancestor_ids"] if node_by_id[ancestor_id]["lineage"]["actionable_by_flags"]]
        record["lineage"]["actionable_ancestor_ids"] = actionable_ancestors
        descendants: list[dict[str, Any]] = []
        for child_id in record["lineage"]["ordered_child_ids"]["value"]:
            descendants.append(node_by_id[child_id])
            descendants.extend(_descendant_records(node_by_id, child_id))
        record["lineage"]["actionable_descendant_ids"] = [entry["node_local_id"] for entry in descendants if entry["lineage"]["actionable_by_flags"]]
        record["lineage"]["clickable_descendant_ids"] = [entry["node_local_id"] for entry in descendants if entry["provenance"]["fields"]["clickable"]["value"] is True]
        record["lineage"]["focusable_descendant_ids"] = [entry["node_local_id"] for entry in descendants if entry["provenance"]["fields"]["focusable"]["value"] is True]

    root_package_status = PRESENT if package_names else NOT_SUPPORTED_BY_SOURCE
    package_field = _result(sorted(package_names), root_package_status, derivation="unique_packages_in_snapshot")
    activity = _read_field(snapshot, snapshot, "activity", ("activity", "activityName"), _parse_string)
    platform_generation = _read_field(snapshot, snapshot, "platform_generation_id", ("platformGenerationId", "generationId"), _parse_string)

    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "snapshot": {
            "snapshot_id": capture_id,
            "capture_id": capture_id,
            "capture_sequence": _result(capture_sequence, PRESENT if capture_sequence is not None else NOT_SUPPORTED_BY_SOURCE, derivation="host_client_sequence" if capture_sequence is not None else None),
            "captured_at": _result(captured_at, PRESENT, derivation="host_receive_utc"),
            "request_id": _read_field(snapshot, snapshot, "request_id", ("reqId", "requestId"), _parse_string),
            "platform_generation_id": platform_generation,
            "source": _result(snapshot.get("source"), PRESENT if isinstance(snapshot.get("source"), str) else NOT_SUPPORTED_BY_SOURCE, source_field="source" if "source" in snapshot else None),
            "package": package_field,
            "activity": activity,
            "windows": [
                {
                    "window_index": index,
                    "window_id": _read_field(window, snapshot, "window_id", ("id",), _parse_window_id),
                    "type": _result(window.get("type"), PRESENT if window.get("type") is not None else ABSENT_IN_SOURCE, source_field="type" if "type" in window else None),
                    "layer": _result(window.get("layer"), PRESENT if window.get("layer") is not None else ABSENT_IN_SOURCE, source_field="layer" if "layer" in window else None),
                    "title": _result(window.get("title"), PRESENT if isinstance(window.get("title"), str) and window.get("title") else ABSENT_IN_SOURCE, source_field="title" if "title" in window else None),
                    "active": _result(window.get("active"), PRESENT if type(window.get("active")) is bool else ABSENT_IN_SOURCE, source_field="active" if "active" in window else None),
                    "focused": _result(window.get("focused"), PRESENT if type(window.get("focused")) is bool else ABSENT_IN_SOURCE, source_field="focused" if "focused" in window else None),
                    "bounds": _result(*_parse_bounds(window.get("boundsInScreen")), source_field="boundsInScreen" if "boundsInScreen" in window else None),
                }
                for index, window, _root in roots
            ],
        },
        "snapshot_fingerprint": _snapshot_fingerprint(snapshot, roots),
        "nodes": records,
        "parse_errors": parse_errors,
        "equivalence_policy": "not_decided_in_phase_5d_a",
        "authorization_use": "none",
    }


def _descendant_records(node_by_id: dict[str, dict[str, Any]], node_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    record = node_by_id[node_id]
    for child_id in record["lineage"]["ordered_child_ids"]["value"]:
        child = node_by_id[child_id]
        result.append(child)
        result.extend(_descendant_records(node_by_id, child_id))
    return result


def attach_hierarchy_identity_metadata(
    snapshot: dict[str, Any],
    *,
    capture_id: str | None = None,
    capture_sequence: int | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Return a shallow snapshot copy with a serializable metadata envelope."""
    result = dict(snapshot)
    result["identityMetadata"] = build_hierarchy_identity_metadata(
        snapshot,
        capture_id=capture_id,
        capture_sequence=capture_sequence,
        captured_at=captured_at,
    )
    return result
