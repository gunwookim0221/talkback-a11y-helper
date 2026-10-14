from __future__ import annotations

import json

from talkback_lib.hierarchy_identity import (
    ABSENT_IN_SOURCE,
    NOT_SUPPORTED_BY_SOURCE,
    PARSE_FAILED,
    PRESENT,
    attach_hierarchy_identity_metadata,
    build_hierarchy_identity_metadata,
)


def _node(
    name: str,
    *,
    children: list[dict] | None = None,
    **overrides,
) -> dict:
    value = {
        "sourceNodeId": f"unique:{name}",
        "viewIdResourceName": f"app:id/{name}",
        "className": "android.view.ViewGroup",
        "text": name,
        "contentDescription": f"description:{name}",
        "packageName": "com.example.app",
        "boundsInScreen": {"left": 1, "top": 2, "right": 101, "bottom": 52},
        "clickable": False,
        "focusable": False,
        "enabled": True,
        "selected": False,
        "accessibilityFocused": False,
        "inputFocused": False,
        "scrollable": False,
        "visibleToUser": True,
        "windowId": 7,
        "actions": [],
        "children": children or [],
    }
    value.update(overrides)
    return value


def _snapshot(root: dict | None = None) -> dict:
    return {
        "reqId": "request-1",
        "success": True,
        "schemaVersion": "service-hierarchy-v1",
        "nodeMetadataSchemaName": "talkback.helper.read_only_node_metadata",
        "nodeMetadataSchemaVersion": "1.0",
        "nodeMetadataCapabilities": {
            "source_node_id": True,
            "resource_id": True,
            "class_name": True,
            "text": True,
            "content_description": True,
            "bounds": True,
            "clickable": True,
            "focusable": True,
            "enabled": True,
            "selected": True,
            "accessibility_focused": True,
            "input_focused": True,
            "scrollable": True,
            "visible_to_user": True,
            "actions": True,
            "window_id": True,
            "package": True,
            "semantic_role": False,
            "production_qualified_focus_identity": False,
            "activity": False,
            "platform_generation_id": False,
        },
        "source": "accessibility_service_windows",
        "windows": [{
            "order": 0,
            "id": 7,
            "type": 1,
            "layer": 2,
            "title": "Example",
            "active": True,
            "focused": True,
            "boundsInScreen": {"left": 0, "top": 0, "right": 500, "bottom": 1000},
            "root": root or _node("root"),
        }],
    }


def _nodes(metadata: dict) -> dict[str, dict]:
    return {node["node_local_id"]: node for node in metadata["nodes"]}


def test_capture_ids_are_unique_even_when_timestamp_and_source_snapshot_match():
    source = _snapshot()
    first = build_hierarchy_identity_metadata(source, captured_at="2026-10-15T00:00:00.000Z", capture_sequence=1)
    second = build_hierarchy_identity_metadata(source, captured_at="2026-10-15T00:00:00.000Z", capture_sequence=2)

    assert first["snapshot"]["capture_id"] != second["snapshot"]["capture_id"]
    assert first["snapshot"]["captured_at"]["value"] == second["snapshot"]["captured_at"]["value"]
    assert first["snapshot_fingerprint"]["value"] == second["snapshot_fingerprint"]["value"]
    assert first["snapshot_fingerprint"]["kind"] == "structural_snapshot_fingerprint"
    assert first["authorization_use"] == "none"


def test_identity_metadata_serializes_and_platform_generation_is_unavailable_not_fabricated():
    source = _snapshot()
    enriched = attach_hierarchy_identity_metadata(source, capture_id="host-capture-1", capture_sequence=4)
    restored = json.loads(json.dumps(enriched, ensure_ascii=False))
    metadata = restored["identityMetadata"]

    assert metadata["schema_name"] == "talkback.read_only_hierarchy_identity"
    assert metadata["schema_version"] == "1.0"
    assert metadata["snapshot"]["snapshot_id"] == "host-capture-1"
    assert metadata["snapshot"]["capture_sequence"]["value"] == 4
    assert metadata["snapshot"]["platform_generation_id"]["value"] is None
    assert metadata["snapshot"]["platform_generation_id"]["status"] == NOT_SUPPORTED_BY_SOURCE
    assert "platformGenerationId" not in source
    assert "identityMetadata" not in source


def test_node_raw_metadata_and_exact_action_capabilities_are_preserved():
    root = _node("root", children=[_node(
        "target",
        clickable=True,
        focusable=True,
        accessibilityFocused=True,
        inputFocused=False,
        actions=[{"id": 16, "name": "ACTION_CLICK", "label": "Activate"}, {"id": 64, "name": "ACTION_ACCESSIBILITY_FOCUS", "label": None}],
    )])
    metadata = build_hierarchy_identity_metadata(_snapshot(root), capture_id="capture-node")
    target = _nodes(metadata)["w0:0.0"]

    assert target["source_node_id"] == {"value": "unique:target", "status": PRESENT, "source_field": "sourceNodeId"}
    assert target["semantic_identifiers"]["resource_id"]["value"] == "app:id/target"
    assert target["semantic_identifiers"]["class_name"]["value"] == "android.view.ViewGroup"
    assert target["semantic_identifiers"]["text"]["value"] == "target"
    assert target["semantic_identifiers"]["content_description"]["value"] == "description:target"
    assert target["geometric_identifiers"]["bounds"]["value"] == {"left": 1, "top": 2, "right": 101, "bottom": 52}
    assert target["window_id"]["value"] == 7
    assert target["action_metadata"]["exactness"] == "SOURCE_ACTION_LIST"
    assert [action["id"] for action in target["action_metadata"]["actions"]["value"]] == [16, 64]
    assert target["action_metadata"]["actions"]["value"][0]["normalized_name"] == "ACTION_CLICK"
    assert target["focus_metadata"]["raw_accessibility_focused"]["value"] is True
    assert target["focus_metadata"]["raw_input_focused"]["value"] is False
    assert target["focus_metadata"]["production_qualified_focus_identity"]["status"] == NOT_SUPPORTED_BY_SOURCE
    assert target["focus_metadata"]["diagnostic_fallback_identity"]["reason"] == "diagnostic_only_not_production_focus_identity"


def test_absent_supported_fields_and_parser_failures_have_distinct_provenance():
    root = _node("root", children=[_node(
        "sparse",
        sourceNodeId=None,
        text=7,
        boundsInScreen="not-bounds",
        actions=[],
    )])
    metadata = build_hierarchy_identity_metadata(_snapshot(root), capture_id="capture-provenance")
    sparse = _nodes(metadata)["w0:0.0"]

    assert sparse["source_node_id"]["status"] == ABSENT_IN_SOURCE
    assert sparse["semantic_identifiers"]["text"]["status"] == PARSE_FAILED
    assert sparse["geometric_identifiers"]["bounds"]["status"] == PARSE_FAILED
    assert sparse["action_metadata"]["actions"]["status"] == PRESENT
    assert sparse["action_metadata"]["actions"]["value"] == []
    assert sparse["semantic_identifiers"]["semantic_role"]["status"] == NOT_SUPPORTED_BY_SOURCE


def test_lineage_is_full_tree_ordered_and_summarizes_actionable_relatives_without_owner_resolution():
    independent = _node("independent", clickable=True, boundsInScreen="[10,20][30,40]")
    header = _node("header", focusable=True)
    monitor = _node("monitor", children=[header, independent], clickable=True)
    root = _node("serviceCardBody", children=[monitor], clickable=True)
    metadata = build_hierarchy_identity_metadata(_snapshot(root), capture_id="capture-lineage")
    nodes = _nodes(metadata)

    service_card = nodes["w0:0"]
    monitor_card = nodes["w0:0.0"]
    monitor_header = nodes["w0:0.0.0"]
    independent_control = nodes["w0:0.0.1"]

    assert service_card["lineage"]["ordered_child_ids"]["value"] == ["w0:0.0"]
    assert monitor_card["lineage"]["parent_id"]["value"] == "w0:0"
    assert monitor_card["lineage"]["ancestor_ids_root_to_parent"]["value"] == ["w0:0"]
    assert monitor_header["structural_identifiers"]["depth"]["value"] == 2
    assert independent_control["structural_identifiers"]["sibling_index"]["value"] == 1
    assert independent_control["lineage"]["ancestor_ids_root_to_parent"]["value"] == ["w0:0", "w0:0.0"]
    assert service_card["lineage"]["actionable_descendant_ids"] == ["w0:0.0", "w0:0.0.0", "w0:0.0.1"]
    assert monitor_card["lineage"]["clickable_descendant_ids"] == ["w0:0.0.1"]
    assert independent_control["lineage"]["actionable_ancestor_ids"] == ["w0:0", "w0:0.0"]
    assert service_card["lineage"]["summary_semantics"] == "clickable_or_focusable_flags_only_no_owner_canonicalization"


def test_legacy_helper_schema_marks_unexposed_fields_as_not_supported():
    source = {
        "success": True,
        "schemaVersion": "service-hierarchy-v1",
        "windows": [{"id": 3, "root": {"text": None, "focused": False, "children": []}}],
    }
    metadata = build_hierarchy_identity_metadata(source, capture_id="legacy")
    node = metadata["nodes"][0]

    assert node["source_node_id"]["status"] == NOT_SUPPORTED_BY_SOURCE
    assert node["action_metadata"]["actions"]["status"] == NOT_SUPPORTED_BY_SOURCE
    assert node["focus_metadata"]["raw_input_focused"]["value"] is False
    assert node["focus_metadata"]["raw_input_focused"]["source_field"] == "focused"
    assert node["window_id"]["value"] == 3
    assert node["window_id"]["derivation"] == "window_membership"
