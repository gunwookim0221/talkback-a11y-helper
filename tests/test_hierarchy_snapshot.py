from __future__ import annotations

import xml.etree.ElementTree as ET
import hashlib

import pytest

from talkback_lib.hierarchy_snapshot import (
    _exact_canonical_json,
    flatten_service_hierarchy,
    hierarchy_package,
    legacy_scroll_nodes,
    service_hierarchy_to_xml,
)


def _fixture_snapshot():
    first = {
        "text": "Home",
        "contentDescription": "Home tab",
        "viewIdResourceName": "app:id/home",
        "sourceNodeId": "unique-home",
        "windowId": 1,
        "className": "android.widget.Button",
        "packageName": "com.example.app",
        "boundsInScreen": {"l": 0, "t": 2100, "r": 180, "b": 2400,
                           "left": 0, "top": 2100, "right": 180, "bottom": 2400},
        "clickable": True,
        "focusable": True,
        "enabled": True,
        "selected": True,
        "visibleToUser": True,
        "isVisibleToUser": True,
        "childIndex": 0,
        "children": [],
    }
    second = {
        "text": "Life",
        "contentDescription": "",
        "viewIdResourceName": "app:id/life",
        "sourceNodeId": "unique-life",
        "windowId": 1,
        "className": "android.widget.Button",
        "packageName": "com.example.app",
        "boundsInScreen": "[180,2100][360,2400]",
        "clickable": True,
        "focusable": True,
        "enabled": False,
        "selected": False,
        "visibleToUser": True,
        "childIndex": 1,
        "children": [],
    }
    root = {
        "text": "",
        "className": "android.widget.FrameLayout",
        "packageName": "com.example.app",
        "windowId": 1,
        "boundsInScreen": "[0,0][1080,2400]",
        "children": [first, second],
    }
    overlay = {
        "text": "Dialog",
        "contentDescription": "",
        "viewIdResourceName": "",
        "className": "android.widget.Dialog",
        "packageName": "com.example.dialog",
        "boundsInScreen": "[100,600][980,1800]",
        "clickable": False,
        "focusable": False,
        "enabled": True,
        "focused": False,
        "accessibilityFocused": False,
        "selected": False,
        "scrollable": False,
        "checkable": False,
        "checked": False,
        "visibleToUser": True,
        "children": [],
    }
    return {
        "reqId": "fixture",
        "success": True,
        "nodes": [overlay, root],
        "windows": [
            {"root": overlay, "order": 0, "id": 2, "type": "SYSTEM", "active": False, "focused": False},
            {"root": root, "order": 1, "id": 1, "type": "APPLICATION", "active": True, "focused": True},
        ],
        "nodeCount": 4,
        "windowCoverage": "all_service_visible_windows",
        "snapshotId": "helper-capture-1",
    }


def _semantic_xml_node(element):
    return element.tag, tuple(sorted(element.attrib.items())), tuple(_semantic_xml_node(child) for child in element)


def test_flatten_preserves_window_and_accessibility_child_order_and_paths():
    flattened = flatten_service_hierarchy(_fixture_snapshot())

    assert [(node["text"], node["stable_node_path"], node["windowIndex"], node["serviceWindowIndex"]) for node in flattened] == [
        ("", "0.0", 0, 1),
        ("Home", "0.0.0", 0, 1),
        ("Life", "0.0.1", 0, 1),
    ]
    assert flattened[1]["content-desc"] == "Home tab"
    assert flattened[1]["resource-id"] == "app:id/home"
    assert flattened[2]["enabled"] is False
    assert flattened[1]["bounds"] == "[0,2100][180,2400]"
    assert hierarchy_package(_fixture_snapshot()) == "com.example.app"

    all_nodes = flatten_service_hierarchy(_fixture_snapshot(), include_all_windows=True)
    assert [(node["text"], node["stable_node_path"], node["serviceWindowIndex"]) for node in all_nodes] == [
        ("Dialog", "0.0", 0),
        ("", "1.0", 1),
        ("Home", "1.0.0", 1),
        ("Life", "1.0.1", 1),
    ]


def test_service_xml_adapter_preserves_legacy_semantics_and_window_order():
    snapshot = _fixture_snapshot()
    service_xml = ET.fromstring(service_hierarchy_to_xml(snapshot))
    legacy_xml = ET.fromstring(
        '<hierarchy rotation="0">'
        '<node text="" class="android.widget.FrameLayout" package="com.example.app" bounds="[0,0][1080,2400]" visible-to-user="true" '
        '>'
        '<node text="Home" content-desc="Home tab" resource-id="app:id/home" class="android.widget.Button" '
        'package="com.example.app" bounds="[0,2100][180,2400]" clickable="true" focusable="true" enabled="true" '
        'selected="true" visible-to-user="true" />'
        '<node text="Life" content-desc="" resource-id="app:id/life" class="android.widget.Button" '
        'package="com.example.app" bounds="[180,2100][360,2400]" clickable="true" focusable="true" enabled="false" '
        'selected="false" visible-to-user="true" />'
        '</node>'
        '</hierarchy>'
    )

    assert [_semantic_xml_node(node) for node in service_xml.findall("node")] == [
        _semantic_xml_node(node) for node in legacy_xml.findall("node")
    ]
    all_windows_xml = ET.fromstring(service_hierarchy_to_xml(snapshot, include_all_windows=True))
    assert [node.get("text") for node in all_windows_xml.findall("node")] == ["Dialog", ""]
    scroll_roots = legacy_scroll_nodes(snapshot)
    assert [node["text"] for node in scroll_roots] == [""]
    assert scroll_roots[0]["children"][0]["selected"] is True
    assert scroll_roots[0]["children"][0]["sourceNodeId"] == "unique-home"
    assert scroll_roots[0]["children"][0]["windowId"] == 1
    assert scroll_roots[0]["children"][0]["_helperNodePath"] == [0]
    assert len(scroll_roots[0]["children"][0]["_helperNodeDescriptorDigest"]) == 64
    raw_home = snapshot["windows"][1]["root"]["children"][0]
    descriptor = {key: raw_home.get(key) for key in (
        "text", "contentDescription", "viewIdResourceName", "className", "packageName",
        "sourceNodeId", "windowId", "boundsInScreen", "clickable", "effectiveClickable",
        "enabled", "focusable", "focused", "inputFocused", "accessibilityFocused", "selected",
        "scrollable", "isScrollable", "checkable", "checked", "visibleToUser",
        "isVisibleToUser", "actions",
    )}
    assert scroll_roots[0]["children"][0]["_helperNodeDescriptorDigest"] == hashlib.sha256(
        _exact_canonical_json(descriptor).encode("utf-8")
    ).hexdigest()
    assert scroll_roots[0]["children"][0]["_helperSourceSnapshotId"] == "helper-capture-1"
    assert [node["text"] for node in legacy_scroll_nodes(snapshot, include_all_windows=True)] == ["Dialog", ""]


@pytest.mark.parametrize("label", ["AirCare", "상위 메뉴로 이동", "café", "😀", "A\x7fB"])
def test_descriptor_digest_matches_helper_exact_canonical_for_ascii_and_unicode(label):
    snapshot = _fixture_snapshot()
    raw_node = snapshot["windows"][1]["root"]["children"][0]
    raw_node["text"] = label

    projected = legacy_scroll_nodes(snapshot)[0]["children"][0]
    descriptor_fields = (
        "text", "contentDescription", "viewIdResourceName", "className",
        "packageName", "sourceNodeId", "windowId", "boundsInScreen",
        "clickable", "effectiveClickable", "enabled", "focusable",
        "focused", "inputFocused", "accessibilityFocused", "selected",
        "scrollable", "isScrollable", "checkable", "checked",
        "visibleToUser", "isVisibleToUser", "actions",
    )
    descriptor = {key: raw_node.get(key) for key in descriptor_fields}
    expected = hashlib.sha256(_exact_canonical_json(descriptor).encode("utf-8")).hexdigest()

    assert projected["_helperNodeDescriptorDigest"] == expected


def test_exact_canonical_json_matches_helper_scalar_and_unicode_escaping():
    assert _exact_canonical_json({"text": "AirCare", "enabled": True, "count": 2, "missing": None}) == (
        '{"count":2,"enabled":true,"missing":null,"text":"AirCare"}'
    )
    assert _exact_canonical_json({"text": "상위 메뉴로 이동"}) == (
        '{"text":"\\uc0c1\\uc704 \\uba54\\ub274\\ub85c \\uc774\\ub3d9"}'
    )
    assert _exact_canonical_json({"text": "😀"}) == '{"text":"\\ud83d\\ude00"}'
    assert _exact_canonical_json({"text": "A\x7fB"}) == '{"text":"A\\u007fB"}'
    with pytest.raises(ValueError, match="DESCRIPTOR_UNSUPPORTED_JSON_VALUE"):
        _exact_canonical_json({"fraction": 1.25})


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        ({"success": False, "windows": []}, "HIERARCHY_SNAPSHOT:SERIALIZATION_ERROR:invalid_snapshot"),
        ({"success": True, "windows": []}, "HIERARCHY_SNAPSHOT:NO_ROOT:window_list_empty"),
        ({"success": True, "windows": [{"root": None}]}, "HIERARCHY_SNAPSHOT:NO_ROOT:window_root_missing:0"),
    ],
)
def test_flatten_fails_closed_for_missing_or_invalid_roots(snapshot, message):
    with pytest.raises(ValueError, match=message):
        flatten_service_hierarchy(snapshot)
