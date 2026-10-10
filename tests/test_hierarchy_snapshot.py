from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from talkback_lib.hierarchy_snapshot import (
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
        "className": "android.widget.Button",
        "packageName": "com.example.app",
        "boundsInScreen": {"left": 0, "top": 2100, "right": 180, "bottom": 2400},
        "clickable": True,
        "focusable": True,
        "enabled": True,
        "selected": True,
        "visibleToUser": True,
        "childIndex": 0,
        "children": [],
    }
    second = {
        "text": "Life",
        "contentDescription": "",
        "viewIdResourceName": "app:id/life",
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
    assert [node["text"] for node in legacy_scroll_nodes(snapshot, include_all_windows=True)] == ["Dialog", ""]


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
