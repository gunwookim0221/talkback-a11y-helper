from types import SimpleNamespace

import pytest

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
        "activity_name": activity or default_activity, "context_source": "window_current_focus",
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
    return raw


@pytest.mark.parametrize("scenario_id", list(PLUGIN_CASES))
def test_verified_plugin_context_requires_entry_component_and_body(scenario_id):
    raw = _plugin_raw(scenario_id)
    result = resolve_phase3_context(raw)
    assert result["status"] == "VERIFIED_PLUGIN_CONTEXT"
    assert result["verified"] is True
    assert result["context_id"]
    snapshot = build_discovery_snapshot(raw, StateRegistry("verified-" + scenario_id))
    assert snapshot.state_id is not None


@pytest.mark.parametrize("scenario_id", list(PLUGIN_CASES))
def test_scenario_name_alone_never_resolves_plugin_context(scenario_id):
    raw = _plugin_raw(scenario_id, body="Generic settings", activity="com.samsung.android.oneconnect.ui.scmain.SCMainActivity")
    raw.pop("phase3_entry_evidence")
    result = resolve_phase3_context(raw)
    assert result["status"] != "VERIFIED_PLUGIN_CONTEXT"
    assert result["verified"] is False
    assert build_discovery_snapshot(raw, StateRegistry("scenario-only-" + scenario_id)).state_id is None


def test_wrong_plugin_body_and_component_are_rejected():
    raw = _plugin_raw("life_food_plugin", body="Current location",
                      activity="com.samsung.android.plugin.fme.MainActivity")
    raw["nodes"] = [_node("Current location", "com.samsung.android.plugin.fme:id/current_location_btn")]
    result = resolve_phase3_context(raw)
    assert result["status"] == "WRONG_CONTEXT"
    assert result["verified"] is False
    assert build_discovery_snapshot(raw, StateRegistry("wrong-body")).state_id is None


def test_stale_entry_run_cannot_resolve_current_plugin_body():
    raw = _plugin_raw("life_family_care_plugin", run_id="new-run")
    raw["phase3_entry_evidence"]["scenario_run_id"] = "old-run"
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert result["verified"] is False
    assert build_discovery_snapshot(raw, StateRegistry("stale-entry")).state_id is None


def test_global_navigation_only_does_not_resolve_plugin_context():
    raw = _plugin_raw("life_food_plugin", body="Life", selected="life")
    raw["nodes"] = [_node("Life", "com.samsung.android.oneconnect:id/menu_services", selected=True)]
    result = resolve_phase3_context(raw)
    assert result["status"] == "PARTIAL_CONTEXT"
    snapshot = build_discovery_snapshot(raw, StateRegistry("global-nav-only"))
    assert snapshot.state_id is None
    assert "UNVERIFIED_PLUGIN_CONTEXT" in snapshot.to_dict()["state_resolution"]["reasons"]


def test_wrong_selected_tab_rejects_otherwise_matching_plugin_body():
    raw = _plugin_raw("life_food_plugin", selected="devices")
    result = resolve_phase3_context(raw)
    assert result["status"] == "WRONG_CONTEXT"
    assert build_discovery_snapshot(raw, StateRegistry("wrong-tab")).state_id is None


def test_conflicting_plugin_body_evidence_stays_unresolved():
    raw = _plugin_raw("life_food_plugin")
    raw["nodes"].append(_node("Family Care", "com.samsung.android.plugin.care:id/title",
                              bounds="0,120,400,220"))
    result = resolve_phase3_context(raw)
    assert result["status"] == "CONTRADICTORY_CONTEXT"
    assert build_discovery_snapshot(raw, StateRegistry("conflicting-body")).state_id is None


def test_previous_scenario_entry_evidence_does_not_leak_to_next_scenario():
    prior = _plugin_raw("life_food_plugin", run_id="food-run")
    current = _plugin_raw("life_find_plugin", run_id="find-run")
    current["phase3_entry_evidence"] = prior["phase3_entry_evidence"]
    result = resolve_phase3_context(current)
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert build_discovery_snapshot(current, StateRegistry("no-context-leak")).state_id is None


@pytest.mark.parametrize("scenario_id", ["life_family_care_plugin", "life_find_plugin", "device_smoke_sensor_plugin"])
def test_accepted_terminal_and_plugin_body_resolve_without_lost_activity(scenario_id):
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
    assert resolve_phase3_context(raw)["status"] == "VERIFIED_PLUGIN_CONTEXT"
    assert build_discovery_snapshot(raw, StateRegistry("accepted-" + scenario_id)).state_id is not None


def test_accepted_terminal_from_another_scenario_transaction_is_rejected():
    evidence = phase3_entry_evidence_from_accepted_replay(
        "life_food_plugin", "expected-tx",
        {"event_id": "terminal-proof", "scenario_id": "life_food_plugin",
         "scenario_tx_id": "different-tx", "payload": {"traversal_started": True}},
        "2026-10-11T08:00:01+00:00",
    )
    assert evidence == {}


@pytest.mark.parametrize("scenario_id,tab", [("home_main", "home"), ("devices_main", "devices")])
def test_known_root_contexts_resolve_from_observed_tab_and_activity(scenario_id, tab):
    raw = {
        "scenario_id": scenario_id, "timestamp": "2026-10-11T08:00:01+00:00",
        "package_name": "com.samsung.android.oneconnect",
        "activity_name": "com.samsung.android.oneconnect.ui.scmain.SCMainActivity",
        "context_source": "window_current_focus", "display_bounds": "0,0,1080,2400",
        "selected_tab": {"name": tab, "verified": True, "source": "service_hierarchy_selected"},
        "navigation_context": {"bottom_tab": tab},
        "nodes": [_node(tab.title(), "com.samsung.android.oneconnect:id/menu_" +
                         ("favorites" if tab == "home" else "devices"), selected=True),
                  _node("root", "com.samsung.android.oneconnect:id/" +
                        ("mapview_layout" if tab == "home" else "device_card"),
                        bounds="0,120,400,700")],
    }
    result = resolve_phase3_context(raw)
    assert result["status"] == "VERIFIED_ROOT_CONTEXT"
    assert result["context_id"] == tab
    assert build_discovery_snapshot(raw, StateRegistry("root-" + scenario_id)).state_id is not None


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
    result = resolve_phase3_context(raw)
    assert result["status"] == "VERIFIED_ROOT_CONTEXT"
    assert build_discovery_snapshot(raw, StateRegistry("partial-root-home")).state_id is not None
