from types import SimpleNamespace

import pytest

from phase6d_capture_support import attach_capture_authority
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.phase3_context import (
    phase3_entry_evidence_from_accepted_replay,
    phase3_entry_evidence_from_main_loop,
    resolve_phase3_context,
)
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.state_registry import StateRegistry


PLUGIN_CASES = {
    "life_food_plugin": (
        "com.samsung.android.oneconnect.webplugin.WebPluginActivity",
        "SmartThings Cooking", "app"),
    "life_family_care_plugin": (
        "com.samsung.android.plugin.care.MainActivity",
        "Family Care", "com.samsung.android.plugin.care:id/title"),
    "life_find_plugin": (
        "com.samsung.android.plugin.fme.MainActivity",
        "Current location", "com.samsung.android.plugin.fme:id/current_location_btn"),
    "device_smoke_sensor_plugin": (
        "com.samsung.android.oneconnect.webplugin.WebPluginActivity",
        "Smoke detector", "SmokeDetectorCapabilityCardView_header_title"),
}


def _config(scenario_id):
    return next(cfg for cfg in TAB_CONFIGS if cfg["scenario_id"] == scenario_id)


def _node(label, rid, *, bounds="0,0,400,100", selected=False):
    return {"text": label, "viewIdResourceName": rid, "className": "android.widget.TextView",
            "boundsInScreen": bounds, "visibleToUser": True, "selected": selected,
            "enabled": True, "clickable": False, "focusable": False}


def _plugin_raw(scenario_id, *, body=None, activity=None, selected=None, run_id="run-current"):
    default_activity, default_body, rid = PLUGIN_CASES[scenario_id]
    config = _config(scenario_id)
    timestamp = "2026-10-11T08:00:01+00:00"
    raw = {
        "scenario_id": scenario_id, "scenario_run_id": run_id, "capture_id": "capture-current",
        "timestamp": timestamp, "package_name": "com.samsung.android.oneconnect",
        "activity_name": activity or default_activity, "context_source": "helper_tree_component",
        "display_bounds": "0,0,1080,2400", "nodes": [_node(body or default_body, rid)],
        "observation_coverage": "OBSERVED_FULL",
    }
    if selected is not None:
        raw["selected_tab"] = {"name": selected, "verified": True,
                               "source": "service_hierarchy_selected"}
        raw["navigation_context"] = {"bottom_tab": selected}
    evidence = phase3_entry_evidence_from_main_loop(
        SimpleNamespace(tab_cfg=config, rows=[]), run_id, timestamp)
    raw["phase3_entry_evidence"] = evidence
    attach_capture_authority(raw)
    return raw


@pytest.mark.parametrize("scenario_id", list(PLUGIN_CASES))
def test_capture_local_root_authority_cannot_verify_plugin_context(scenario_id):
    raw = _plugin_raw(scenario_id)
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert result["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]
    assert result["verified"] is False



@pytest.mark.parametrize("scenario_id", list(PLUGIN_CASES))
def test_scenario_name_alone_never_resolves_plugin_context(scenario_id):
    raw = _plugin_raw(scenario_id, body="Generic settings", activity="com.samsung.android.oneconnect.ui.scmain.SCMainActivity")
    raw.pop("phase3_entry_evidence")
    result = resolve_phase3_context(raw)
    assert result["status"] != "VERIFIED_PLUGIN_CONTEXT"
    assert result["verified"] is False


def test_wrong_plugin_body_and_component_are_rejected():
    raw = _plugin_raw("life_food_plugin", body="Current location",
                      activity="com.samsung.android.plugin.fme.MainActivity")
    raw["nodes"] = [_node("Current location", "com.samsung.android.plugin.fme:id/current_location_btn")]
    result = resolve_phase3_context(raw)
    assert result["status"] == "CONTRADICTORY_CONTEXT"
    assert result["verified"] is False


def test_stale_entry_run_cannot_resolve_current_plugin_body():
    raw = _plugin_raw("life_family_care_plugin", run_id="new-run")
    raw["phase3_entry_evidence"]["scenario_run_id"] = "old-run"
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert result["verified"] is False


def test_global_navigation_only_does_not_resolve_plugin_context():
    raw = _plugin_raw("life_food_plugin", body="Life", selected="life")
    raw["nodes"] = [_node("Life", "com.samsung.android.oneconnect:id/menu_services", selected=True)]
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"



def test_wrong_selected_tab_rejects_otherwise_matching_plugin_body():
    raw = _plugin_raw("life_food_plugin", selected="devices")
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"


def test_conflicting_plugin_body_evidence_stays_unresolved():
    raw = _plugin_raw("life_food_plugin")
    raw["nodes"].append(_node("Family Care", "com.samsung.android.plugin.care:id/title",
                              bounds="0,120,400,220"))
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"


def test_previous_scenario_entry_evidence_does_not_leak_to_next_scenario():
    prior = _plugin_raw("life_food_plugin", run_id="food-run")
    current = _plugin_raw("life_find_plugin", run_id="find-run")
    current["phase3_entry_evidence"] = prior["phase3_entry_evidence"]
    result = resolve_phase3_context(current)
    assert result["status"] == "UNRESOLVED_CONTEXT"


def test_package_mismatch_cannot_use_capture_local_profile_or_resource_evidence():
    raw = _plugin_raw("life_food_plugin")
    raw["package_name"] = "com.other.package"
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert result["reasons"] == ["CAPTURE_ROOT_PACKAGE_WINDOW_MISMATCH"]
    assert result["verified"] is False


def test_profile_resource_fast_path_cannot_use_forged_unbound_activity():
    raw = _plugin_raw("life_food_plugin")
    attach_capture_authority(raw)
    raw["activity_name"] = "pkg.FoodPluginActivity"
    raw["context_source"] = "helper_tree_component"
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert result["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]


@pytest.mark.parametrize("scenario_id", ["life_family_care_plugin", "life_find_plugin", "device_smoke_sensor_plugin"])
def test_accepted_terminal_and_plugin_body_resolve_from_bound_capture_after_activity_metadata_loss(scenario_id):
    raw = _plugin_raw(scenario_id, run_id="accepted-tx")
    raw["activity_name"] = None
    raw["package_name"] = None
    raw["context_source"] = "accepted_partial_capture"
    raw["phase3_entry_evidence"] = phase3_entry_evidence_from_accepted_replay(
        scenario_id, "accepted-tx",
        {"event_id": "terminal-proof", "scenario_id": scenario_id,
         "scenario_tx_id": "accepted-tx", "payload": {"traversal_started": True}},
        raw["timestamp"],
    )
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"


def test_accepted_terminal_from_another_scenario_transaction_is_rejected():
    evidence = phase3_entry_evidence_from_accepted_replay(
        "life_food_plugin", "expected-tx",
        {"event_id": "terminal-proof", "scenario_id": "life_food_plugin",
         "scenario_tx_id": "different-tx", "payload": {"traversal_started": True}},
        "2026-10-11T08:00:01+00:00",
    )
    assert evidence == {}


@pytest.mark.parametrize("scenario_id,tab", [("home_main", "home"), ("devices_main", "devices")])
def test_root_tab_marker_and_wms_activity_remain_diagnostic(scenario_id, tab):
    raw = {
        "scenario_id": scenario_id, "timestamp": "2026-10-11T08:00:01+00:00",
        "package_name": "com.samsung.android.oneconnect",
        "activity_name": "com.samsung.android.oneconnect.ui.scmain.SCMainActivity",
        "context_source": "helper_tree_component", "display_bounds": "0,0,1080,2400",
        "selected_tab": {"name": tab, "verified": True, "source": "service_hierarchy_selected"},
        "navigation_context": {"bottom_tab": tab},
        "nodes": [_node(tab.title(), "com.samsung.android.oneconnect:id/menu_" +
                         ("favorites" if tab == "home" else "devices"), selected=True),
                  _node("root", "com.samsung.android.oneconnect:id/" +
                        ("mapview_layout" if tab == "home" else "device_card"),
                        bounds="0,120,400,700")],
    }
    attach_capture_authority(raw)
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert result["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]


def test_partial_accepted_root_resolves_from_selected_tab_and_unique_root_resource():
    raw = {
        "scenario_id": "home_main", "timestamp": "2026-10-11T08:00:01+00:00",
        "package_name": None, "activity_name": None, "context_source": "accepted_partial_capture",
        "selected_tab": {"name": "home", "verified": True, "source": "observed_selected_node"},
        "navigation_context": {"bottom_tab": "home"}, "display_bounds": "0,0,1080,2400",
        "nodes": [_node("Home", "com.samsung.android.oneconnect:id/menu_favorites", selected=True),
                  _node("Map View", "com.samsung.android.oneconnect:id/mapview_layout",
                        bounds="0,120,500,900")],
    }
    attach_capture_authority(raw)
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert result["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]
