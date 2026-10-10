from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from talkback_lib.hierarchy_snapshot import (
    flatten_service_hierarchy,
    legacy_scroll_nodes,
    service_hierarchy_to_xml,
)
from tb_runner import global_navigation
from tb_runner.anchor_logic import _extract_candidate_from_node
from tb_runner.content_terminal import ContentTerminal
from tb_runner.context_verifier import _matches_bottom_tab_expectation, _read_service_hierarchy_selected_bottom_tab
from tb_runner.core_preflight import _has_smartthings_bottom_tab, _has_smartthings_bottom_tab_nodes
from tb_runner.scroll_reliability import capability, viewport
from tb_runner.tab_logic import choose_best_tab_candidate, match_tab_candidate, normalize_tab_config


APP = "com.samsung.android.oneconnect"
NAV_LABELS = ("홈", "기기", "라이프", "자동화", "메뉴")
NAV_KEYS = ("home", "devices", "life", "routines", "menu")
NAV_IDS = tuple(f"{APP}:id/bottom_{key}" for key in NAV_KEYS)
NAV_CONFIG = {
    "scenario_id": "global_nav_main",
    "global_nav": {"labels": list(NAV_LABELS), "resource_ids": list(NAV_IDS)},
}


def _node(
    *,
    text: str = "",
    description: str = "",
    resource_id: str = "",
    class_name: str = "android.view.View",
    bounds: str = "[0,0][100,100]",
    clickable: bool = False,
    focusable: bool = False,
    selected: bool = False,
    accessibility_focused: bool = False,
    scrollable: bool = False,
    children: list[ET.Element] | None = None,
) -> ET.Element:
    attrs = {
        "text": text,
        "content-desc": description,
        "resource-id": resource_id,
        "class": class_name,
        "package": APP,
        "bounds": bounds,
        "clickable": str(clickable).lower(),
        "focusable": str(focusable).lower(),
        "enabled": "true",
        "focused": "false",
        "accessibility-focused": str(accessibility_focused).lower(),
        "selected": str(selected).lower(),
        "scrollable": str(scrollable).lower(),
        "checked": "false",
        "visible-to-user": "true",
    }
    result = ET.Element("node", attrs)
    for child in children or []:
        result.append(child)
    return result


def _cases() -> list[tuple[str, str, str]]:
    return [
        ("home_main", "home", "거실"),
        ("devices_main", "devices", "기기 목록"),
        ("life_main", "life", "라이프 서비스"),
        ("menu_main", "menu", "설정"),
        ("global_nav_main", "home", "전체 메뉴"),
        ("life_air_care_plugin", "life", "에어 케어"),
        ("overlay_present", "home", "장소 추가"),
        ("scrollable_page", "devices", "기기 목록"),
        ("dynamic_content_page", "home", "마지막 업데이트 10/09 08:25 AM"),
    ]


def _old_xml_and_service_snapshot(case_id: str, selected_key: str, body_label: str):
    nav_container = ET.Element(
        "node",
        {
            "text": "",
            "content-desc": "",
            "resource-id": f"{APP}:id/bottom_navigation_container",
            "class": "android.widget.LinearLayout",
            "package": APP,
            "bounds": "[0,2300][1080,2460]",
            "clickable": "false",
            "focusable": "false",
            "enabled": "true",
            "focused": "false",
            "accessibility-focused": "false",
            "selected": "false",
            "scrollable": "false",
            "checked": "false",
            "visible-to-user": "true",
        },
    )
    for index, (label, key, resource_id) in enumerate(zip(NAV_LABELS, NAV_KEYS, NAV_IDS)):
        nav_container.append(
            _node(
                text=label,
                description=label,
                resource_id=resource_id,
                class_name="android.widget.FrameLayout",
                bounds=f"[{index * 216},2300][{(index + 1) * 216},2460]",
                clickable=True,
                focusable=True,
                selected=key == selected_key,
            )
        )

    body = _node(
        text=body_label,
        description=body_label,
        resource_id=f"{APP}:id/{case_id}_anchor",
        class_name="android.widget.Button",
        bounds="[48,360][980,520]",
        clickable=True,
        focusable=True,
        accessibility_focused=True,
    )
    page_children = [body, nav_container]
    if case_id == "scrollable_page":
        scroll_container = _node(
            resource_id=f"{APP}:id/content_scroll",
            class_name="android.widget.ScrollView",
            bounds="[0,260][1080,2260]",
            scrollable=True,
            children=[body],
        )
        page_children = [scroll_container, nav_container]
    app_root = _node(
        resource_id=f"{APP}:id/{case_id}_root",
        class_name="android.widget.FrameLayout",
        bounds="[0,0][1080,2640]",
        children=page_children,
    )

    hierarchy = ET.Element("hierarchy", {"rotation": "0"})
    if case_id == "overlay_present":
        # UIAutomator's old compatibility view is the app's active hierarchy;
        # the service snapshot keeps this separate overlay root as raw evidence.
        _node(
            text="대화상자",
            resource_id=f"{APP}:id/dialog_root",
            class_name="android.app.Dialog",
            bounds="[100,500][980,2100]",
        )
    hierarchy.append(app_root)
    old_xml = ET.tostring(hierarchy, encoding="unicode")

    def to_service_node(element: ET.Element, child_index: int) -> dict:
        a = element.attrib
        node = {
            "text": a.get("text") or None,
            "contentDescription": a.get("content-desc") or None,
            "viewIdResourceName": a.get("resource-id") or None,
            "className": a.get("class") or None,
            "packageName": a.get("package") or None,
            "boundsInScreen": a.get("bounds"),
            "childIndex": child_index,
            "children": [to_service_node(child, index) for index, child in enumerate(element)],
        }
        for xml_name, service_name in (
            ("clickable", "clickable"),
            ("focusable", "focusable"),
            ("enabled", "enabled"),
            ("focused", "focused"),
            ("accessibility-focused", "accessibilityFocused"),
            ("selected", "selected"),
            ("scrollable", "scrollable"),
            ("checked", "checked"),
            ("visible-to-user", "visibleToUser"),
        ):
            if xml_name in a:
                node[service_name] = a[xml_name] == "true"
        return node

    raw_overlay = {
        "text": "대화상자",
        "className": "android.app.Dialog",
        "packageName": APP,
        "boundsInScreen": "[100,500][980,2100]",
        "children": [],
    }
    roots = []
    if case_id == "overlay_present":
        roots.append({"root": raw_overlay, "order": 0, "active": False, "focused": False, "type": "APPLICATION"})
    roots.append({
        "root": to_service_node(app_root, 0),
        "order": len(roots),
        "active": True,
        "focused": True,
        "type": "APPLICATION",
        "title": case_id,
    })
    snapshot = {
        "reqId": f"fixture-{case_id}",
        "success": True,
        "schemaVersion": "service-hierarchy-v1",
        "source": "accessibility_service_windows",
        "windowCoverage": "all_service_visible_windows",
        "windows": roots,
    }
    return old_xml, snapshot


def _tree_semantics(raw_xml: str):
    root = ET.fromstring(raw_xml)
    semantic_defaults = {
        "text": "",
        "content-desc": "",
        "resource-id": "",
        "class": "",
        "package": "",
        "bounds": "",
        "clickable": "false",
        "focusable": "false",
        "enabled": "true",
        "focused": "false",
        "accessibility-focused": "false",
        "selected": "false",
        "scrollable": "false",
        "checked": "false",
        "visible-to-user": "true",
    }

    def visit(element: ET.Element):
        return (
            element.tag,
            tuple((key, element.attrib.get(key, default)) for key, default in semantic_defaults.items()),
            tuple(visit(child) for child in element),
        )

    return tuple(visit(node) for node in root.findall("node"))


def _node_decisions(nodes: list[dict], config: dict):
    return [
        {
            key: item.get(key)
            for key in (
                "logical_name",
                "selected",
                "actionable",
                "bounds",
                "semantic_label",
                "view_id",
                "stable_node_path",
                "container_id",
                "evidence_source",
                "instance_id",
            )
        }
        for item in global_navigation.discover(nodes, config)
    ]


@pytest.mark.parametrize("case_id,selected_key,body_label", _cases())
def test_service_snapshot_matches_old_xml_semantics_and_consumer_decisions(case_id, selected_key, body_label):
    old_xml, snapshot = _old_xml_and_service_snapshot(case_id, selected_key, body_label)
    adapted_xml = service_hierarchy_to_xml(snapshot)
    old_nodes = global_navigation.xml_nodes(old_xml)
    service_nodes = flatten_service_hierarchy(snapshot)
    expected_label = NAV_LABELS[NAV_KEYS.index(selected_key)]

    # Node fields, ancestry order, and the active root match the old XML view.
    assert _tree_semantics(adapted_xml) == _tree_semantics(old_xml)
    assert len(service_nodes) == len(old_nodes)
    assert [(n["stable_node_path"], n["text"], n["contentDescription"], n["viewIdResourceName"],
             n["className"], n["boundsInScreen"], n["clickable"], n["focusable"], n["selected"],
             n["visibleToUser"])
            for n in service_nodes] == [
        (n["stable_node_path"], n["text"], n["contentDescription"], n["viewIdResourceName"],
         n["className"], n["boundsInScreen"], n["clickable"], n["focusable"], n["selected"],
         n.get("visibleToUser", True))
        for n in old_nodes
    ]

    # Anchor, tab/context, global-navigation, and preflight decisions match.
    old_anchor = next(n for n in old_nodes if n.get("viewIdResourceName", "").endswith(f"{case_id}_anchor"))
    new_anchor = next(n for n in service_nodes if n.get("viewIdResourceName", "").endswith(f"{case_id}_anchor"))
    old_anchor_xml = next(
        node for node in ET.fromstring(old_xml).iter("node")
        if node.get("resource-id", "").endswith(f"{case_id}_anchor")
    )
    old_anchor_inputs = {
        **old_anchor,
        "accessibilityFocused": old_anchor_xml.get("accessibility-focused") == "true",
        "focused": old_anchor_xml.get("focused") == "true",
    }
    assert _extract_candidate_from_node(old_anchor_inputs) == _extract_candidate_from_node(new_anchor)
    assert _node_decisions(old_nodes, NAV_CONFIG) == _node_decisions(service_nodes, NAV_CONFIG)
    assert _has_smartthings_bottom_tab(old_xml) is _has_smartthings_bottom_tab_nodes(service_nodes)
    old_selected_label = next(
        n.get("contentDescription") or n.get("text")
        for n in old_nodes
        if n.get("selected") and _matches_bottom_tab_expectation(n.get("contentDescription") or n.get("text"), selected_key)
    )

    class Client:
        def dump_hierarchy(self, **_kwargs):
            return snapshot

    assert old_selected_label == expected_label
    assert _read_service_hierarchy_selected_bottom_tab(Client(), "fixture", selected_key) == old_selected_label

    tab_config = normalize_tab_config({
        "tab": {
            "text_regex": f"(?i).*{expected_label}.*",
            "resource_id_regex": NAV_IDS[NAV_KEYS.index(selected_key)],
        },
        "global_nav": NAV_CONFIG["global_nav"],
    })
    old_matches = [match_tab_candidate(node, tab_config) for node in old_nodes]
    service_matches = [match_tab_candidate(node, tab_config) for node in service_nodes]
    old_best = choose_best_tab_candidate([item for item in old_matches if item.get("matched")], tab_config["tie_breaker"])
    service_best = choose_best_tab_candidate([item for item in service_matches if item.get("matched")], tab_config["tie_breaker"])
    assert old_best["candidate"]["resource_id"] == service_best["candidate"]["resource_id"] == NAV_IDS[NAV_KEYS.index(selected_key)]

    # Collection's content-scope and scroll inputs remain semantically equal.
    old_items = global_navigation.discover(old_nodes, NAV_CONFIG)
    service_items = global_navigation.discover(service_nodes, NAV_CONFIG)
    old_regions = [item["bounds"] for item in old_items]
    service_regions = [item["bounds"] for item in service_items]
    expected = set(global_navigation.expected_destinations(NAV_CONFIG))
    old_scope = expected <= {item["logical_name"] for item in old_items}
    service_scope = expected <= {item["logical_name"] for item in service_items}
    assert old_regions == service_regions and old_scope is service_scope is True
    old_terminal = ContentTerminal(case_id, nav_regions=old_regions, scope_verified=old_scope)
    service_terminal = ContentTerminal(case_id, nav_regions=service_regions, scope_verified=service_scope)
    old_observation = {"nodes": old_nodes, "viewport": viewport(old_nodes, case_id)}
    service_observation = {"nodes": service_nodes, "viewport": viewport(service_nodes, case_id)}
    assert old_terminal.observe(old_observation, 1) == service_terminal.observe(service_observation, 1)

    old_scroll = capability([], raw_xml=old_xml)
    service_scroll = capability(legacy_scroll_nodes(snapshot))
    assert (old_scroll["status"], old_scroll["axis"], old_scroll["can_scroll_forward"],
            (old_scroll.get("container") or {}).get("boundsInScreen")) == (
        service_scroll["status"], service_scroll["axis"], service_scroll["can_scroll_forward"],
        (service_scroll.get("container") or {}).get("boundsInScreen"),
    )

    if case_id == "overlay_present":
        assert len(snapshot["windows"]) == 2
        assert len(flatten_service_hierarchy(snapshot, include_all_windows=True)) > len(service_nodes)
