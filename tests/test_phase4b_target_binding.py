"""Generic wrapper cases reconstructed from the rejected fresh capture shape."""
from copy import deepcopy
from dataclasses import replace

import pytest

from state_model_fixtures import node
from tb_runner.phase4a_inputs import project_history
from tb_runner.phase4a_planner import production_instance
from tb_runner.phase4b_target_binding import actual_target_matches, resolve_focus_target
from tb_runner.traversal_reliability import instance_id


def wrappers():
    # Observed chain: FrameLayout -> WebView -> focusable WebView -> View.
    # The fixture intentionally has no scenario-specific condition or label.
    nodes = [node("", "", "0,0,1080,2640", className=cls, clickable=False,
        focusable=i == 2, accessibilityFocused=False, stable_node_path="0." + ".".join(["0"] * (i+1)))
        for i, cls in enumerate(["android.widget.FrameLayout", "android.webkit.WebView",
                               "android.webkit.WebView", "android.view.View"])]
    target = dict(resource_id="", bounds="0,0,1080,2640", class_name="android.webkit.WebView")
    chosen = dict(recommended_target=target, recommended_instance_id=production_instance(target,"generic"))
    return dict(nodes=nodes), chosen


def test_saved_wrapper_shape_has_one_canonical_target_and_no_new_identity():
    raw, chosen = wrappers()
    original = deepcopy(raw)
    selected, proof = resolve_focus_target(raw, chosen, "generic")
    assert selected is raw["nodes"][2]
    assert proof["positional_match_count"] == 4 and proof["eligible_match_count"] == 1
    assert proof["reason"] == "CANONICAL_FOCUSABLE_NODE_WITH_NON_ACTIONABLE_WRAPPERS"
    assert proof["production_instance_id"] == chosen["recommended_instance_id"]
    assert raw == original


@pytest.mark.parametrize("kind", ["two_focusable", "different_class_control", "clickable_wrapper", "unknown_focusable",
                                 "focused_wrapper", "separate_sibling", "missing_path", "duplicate_path", "semantic_wrapper"])
def test_ambiguous_or_unproven_targets_never_pick_the_first_node(kind):
    raw, chosen = wrappers()
    other = raw["nodes"][1]
    if kind == "two_focusable": other["focusable"] = True
    elif kind == "different_class_control": raw["nodes"][0]["focusable"] = True
    elif kind == "clickable_wrapper": other["clickable"] = True
    elif kind == "unknown_focusable": other["focusable"] = None
    elif kind == "focused_wrapper": other["accessibilityFocused"] = True
    elif kind == "separate_sibling": other["stable_node_path"] = "0.1"
    elif kind == "missing_path": other.pop("stable_node_path")
    elif kind == "duplicate_path": other["stable_node_path"] = raw["nodes"][2]["stable_node_path"]
    else: other["text"] = "Independent semantic control"
    selected, proof = resolve_focus_target(raw, chosen, "generic")
    assert selected is None and proof["reason"] != "CANONICAL_FOCUSABLE_NODE_WITH_NON_ACTIONABLE_WRAPPERS"


@pytest.mark.parametrize("flag", ["enabled", "focusable", "visibleToUser"])
@pytest.mark.parametrize("value", [False, None])
def test_disabled_invisible_or_unknown_canonical_target_denied(flag, value):
    raw, chosen = wrappers()
    raw["nodes"][2][flag] = value
    assert resolve_focus_target(raw, chosen, "generic")[0] is None


def test_class_alone_does_not_resolve_two_actionable_nodes():
    raw, chosen = wrappers()
    raw["nodes"][1]["focusable"] = True
    assert resolve_focus_target(raw, chosen, "generic")[0] is None


def test_dynamic_label_and_hierarchy_shift_keep_attempt_visit_starvation_identity():
    raw, chosen = wrappers()
    identity = chosen["recommended_instance_id"]
    history = project_history("generic", attempt_entries=[dict(scenario_id="generic",step=3,target=chosen["recommended_target"])], visited_ids=[identity])
    raw["nodes"][2]["text"] = "Temperature 27 C"
    for n in raw["nodes"]: n["stable_node_path"] = "9." + n["stable_node_path"]
    selected, proof = resolve_focus_target(raw, chosen, "generic")
    assert selected is not None and proof["production_instance_id"] == identity
    assert dict(history.attempts) == {identity:1} and dict(history.visits) == {identity:1}
    assert instance_id(dict(scenario_id="generic",view_id="",bounds=chosen["recommended_target"]["bounds"],label="changed",class_name="changed")) == identity


def test_same_resource_id_different_bounds_stay_distinct():
    first = production_instance(dict(resource_id="id/a",bounds="0,0,100,100"),"generic")
    second = production_instance(dict(resource_id="id/a",bounds="0,100,100,200"),"generic")
    assert first != second


@pytest.mark.parametrize("kind", ["different_class", "different_rid", "different_bounds", "input_focus_only"])
def test_actual_positional_alias_never_verifies_wrong_target(kind):
    raw, chosen = wrappers()
    actual = deepcopy(raw["nodes"][2])
    actual["accessibilityFocused"] = True
    assert actual_target_matches(actual,chosen["recommended_target"])
    if kind == "different_class": actual["className"] = "android.view.View"
    elif kind == "different_rid": actual["viewIdResourceName"] = "id/other"
    elif kind == "different_bounds": actual["boundsInScreen"] = "0,0,100,100"
    else: actual.update(accessibilityFocused=False,focused=True)
    assert not actual_target_matches(actual,chosen["recommended_target"])
