"""Unclassified images stay significant; missing evidence never proves decoration."""
from copy import deepcopy

import pytest

from state_model_fixtures import node, observation
from tb_runner.state_equality import evaluate_state_equality
from tb_runner.state_observation import build_state_observation
from tb_runner.state_registry import StateRegistry
from tools.camera_alert_diagnostic import parent_comparison, xml_camera_evidence


def image_observation(**values):
    raw = observation()
    raw["nodes"].append(node("pkg:id/image", "", className="android.widget.ImageView",
                             focusable=False, clickable=False, bounds="0,400,500,450", **values))
    return raw


def relation(a, b):
    return evaluate_state_equality(build_state_observation(a), build_state_observation(b)).verdict.value


def test_unclassified_blank_image_presence_remains_ambiguous():
    present = image_observation()
    absent = deepcopy(present)
    absent["nodes"].pop()
    assert relation(present, absent) == "AMBIGUOUS"


@pytest.mark.parametrize("changes", [
    {"contentDescription": "Camera offline"}, {"stateDescription": "locked"},
    {"focusable": True}, {"clickable": True}, {"text": "Warning"},
    {"text": "Error"}, {"enabled": False}, {"selected": True},
    {"contentDescription": "unlock"}, {"role": "button"},
])
def test_meaningful_image_is_never_discarded(changes):
    a = image_observation()
    a["nodes"][-1].update(changes)
    b = deepcopy(a)
    b["nodes"].pop()
    assert relation(a, b) != "SAME"


@pytest.mark.parametrize("field,before,after", [
    ("stateDescription", "locked", "unlocked"),
    ("contentDescription", "connected", "disconnected"),
    ("enabled", True, False), ("selected", False, True),
])
def test_real_image_semantic_change_is_different(field, before, after):
    a, b = image_observation(), image_observation()
    a["nodes"][-1][field], b["nodes"][-1][field] = before, after
    assert relation(a, b) == "DIFFERENT"


def test_image_order_does_not_change_identity():
    a = image_observation()
    b = deepcopy(a)
    b["nodes"].reverse()
    assert relation(a, b) == "SAME"


def test_parent_semantic_change_is_detected():
    a, b = image_observation(), image_observation()
    a["nodes"][0]["stateDescription"] = "locked"
    b["nodes"][0]["stateDescription"] = "unlocked"
    assert relation(a, b) == "DIFFERENT"


def test_partial_camera_tree_is_ambiguous():
    a = image_observation()
    b = deepcopy(a)
    b["nodes"].pop(0)
    assert relation(a, b) == "AMBIGUOUS"


def test_unresolved_variant_replays_without_unsafe_new_state(tmp_path):
    registry = StateRegistry()
    present = build_state_observation(image_observation())
    absent_raw = image_observation()
    absent_raw["nodes"].pop()
    absent = build_state_observation(absent_raw)
    first = registry.observe(present)
    assert registry.observe(absent).state_id is None
    path = tmp_path / "registry.json"
    registry.save(path)
    restarted = StateRegistry.load(path)
    assert restarted.to_json() == registry.to_json()
    assert restarted.observe(present).state_id == first.state_id
    assert restarted.observe(absent).state_id is None


def test_missing_parent_actions_and_speech_are_unknown():
    attrs = {"text": "Camera", "content-desc": "", "enabled": "true", "clickable": "true", "selected": "false"}
    result = parent_comparison(attrs, attrs)
    assert result["PARENT_TEXT_CHANGED"] is False
    assert result["PARENT_ACTIONS_CHANGED"] is None
    assert result["PARENT_STATE_DESC_CHANGED"] is None
    assert result["PARENT_SPEECH_CHANGED"] is None
    assert parent_comparison(attrs, attrs, left_speech="Camera", right_speech="Offline")["PARENT_SPEECH_CHANGED"] is True


def test_xml_records_exact_parent_siblings_and_unknown_importance():
    xml = '<hierarchy><node resource-id="com.samsung.android.oneconnect:id/favorite_device_card_camera"><node resource-id="pkg:id/sibling"/><node resource-id="com.samsung.android.oneconnect:id/camera_card_alert_animation_previous" text=""/></node></hierarchy>'
    result = xml_camera_evidence(xml)
    assert result["target_present"] is True
    assert result["node_count"] == 3
    alert = result["alerts"][0]
    assert alert["parent"]["child_count"] == 2
    assert alert["siblings"][0]["attributes"]["resource-id"] == "pkg:id/sibling"
    assert alert["node"]["unexposed"]["importantForAccessibility"] is None
