from copy import deepcopy
from types import SimpleNamespace

from tb_runner.dynamic_context import DestinationOwnership, destination_ownership_rejection_diagnostic
from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
from tb_runner.plugin_context_contract import plugin_context_evidence
from tb_runner.scenario_config import TAB_CONFIGS


def air_observation(nodes):
    config = next(c for c in TAB_CONFIGS if c["scenario_id"] == "life_air_care_plugin")
    raw = dict(
        scenario_id="life_air_care_plugin", scenario_run_id="air-run", navigation_epoch="air-entry",
        timestamp="2026-10-13T00:57:22.983000+00:00", capture_id="air-capture",
        package_name="com.samsung.android.oneconnect",
        activity_name="com.samsung.android.oneconnect.webplugin.WebPluginActivity",
        context_source="window_current_focus", window_evidence={"window_count": 1}, nodes=nodes)
    entry = phase3_entry_evidence_from_main_loop(
        SimpleNamespace(tab_cfg=config, rows=[dict(actual_focus_accessibility_focused=True,
            actual_focus_payload_source="verified_pre_loop_anchor")]), raw["scenario_run_id"], raw["timestamp"])
    raw["phase3_entry_evidence"] = entry
    summary = dict(open_completed=True, entry_contract_reason="success_verified",
                   entry_contract_detail="plugin_open_verified")
    raw["phase3_plugin_context_evidence"] = plugin_context_evidence(entry, raw, summary, raw["navigation_epoch"])
    return raw


def air_body():
    return [dict(text="Outdoor air quality PM 10 and PM 2.5", viewIdResourceName="mainList",
                 className="android.view.View", visibleToUser=True)]


def test_air_care_incidental_other_plugin_name_is_lexical_only():
    raw = air_observation(air_body() + [dict(
        text="Add an air conditioner or air purifier to your room to automatically manage the air.",
        viewIdResourceName="no_devices", className="android.widget.TextView",
        clickable=False, focusable=False, visibleToUser=True)])
    result = resolve_phase3_context(raw)
    assert result["status"] == "VERIFIED_PLUGIN_CONTEXT"
    assert not result["destination_evidence"]["structural_evidence"]
    assert any(h["alias"] == "Air purifier" for h in result["destination_evidence"]["lexical_hints"])
    DestinationOwnership(raw)


def test_instructional_label_that_equals_alias_without_heading_role_is_not_identity():
    raw = air_observation(air_body() + [dict(
        text="Air purifier", viewIdResourceName="no_devices",
        className="android.widget.TextView", visibleToUser=True)])
    result = resolve_phase3_context(raw)
    assert result["status"] == "VERIFIED_PLUGIN_CONTEXT"
    assert not result["destination_evidence"]["structural_evidence"]


def test_exact_configured_destination_heading_remains_contradictory():
    raw = air_observation(air_body() + [dict(
        text="Air purifier", className="android.widget.TextView", role="heading", visibleToUser=True)])
    result = resolve_phase3_context(raw)
    assert result["status"] == "CONTRADICTORY_CONTEXT"
    assert result["reasons"] == ["OTHER_CONFIGURED_DESTINATION_BODY"]
    assert any(x["kind"] == "semantic_destination_heading"
               for x in result["destination_evidence"]["structural_evidence"])


def test_destination_specific_resource_remains_contradictory():
    raw = air_observation(air_body() + [dict(
        text="Air purifier", viewIdResourceName="com.samsung.android.plugin.airpurifier:id/root",
        className="android.view.View", visibleToUser=True)])
    result = resolve_phase3_context(raw)
    assert result["status"] == "CONTRADICTORY_CONTEXT"
    assert any(x["kind"] == "destination_specific_resource"
               for x in result["destination_evidence"]["structural_evidence"])


def test_multiple_structural_destination_signals_remain_contradictory():
    raw = air_observation(air_body() + [dict(
        text="Air purifier", className="android.widget.TextView", role="heading", visibleToUser=True),
        dict(text="Air purifier controls", viewIdResourceName="com.samsung.android.plugin.airpurifier:id/root",
             className="android.view.View", visibleToUser=True)])
    result = resolve_phase3_context(raw)
    assert result["status"] == "CONTRADICTORY_CONTEXT"
    assert len(result["destination_evidence"]["structural_evidence"]) >= 2


def test_same_lexical_phrase_keeps_valid_air_care_ownership():
    raw = air_observation(air_body() + [dict(
        text="Add an air purifier to your room", className="android.widget.TextView", visibleToUser=True)])
    original = deepcopy(raw)
    owner = DestinationOwnership(raw)
    assert owner.scenario == "life_air_care_plugin"
    assert owner.freshness == "FRESH_VERIFIED"
    assert raw == original


def test_verified_entry_and_consistent_current_destination_create_owner():
    raw = air_observation(air_body())
    result = resolve_phase3_context(raw)
    owner = DestinationOwnership(raw)
    assert result["verified"] is True
    assert owner.destination == raw["phase3_entry_evidence"]["entry_contract_digest"]
    assert owner.events[0]["kind"] == "DESTINATION_ESTABLISHED"


def test_rejection_diagnostic_contains_context_and_marker_provenance_before_raise():
    raw = air_observation(air_body() + [dict(
        text="Air purifier", className="android.widget.TextView", role="heading", visibleToUser=True)])
    context = resolve_phase3_context(raw)
    diagnostic = destination_ownership_rejection_diagnostic(raw, context, ValueError("Trusted normal plugin entry required"))
    assert diagnostic["scenario"] == "life_air_care_plugin"
    assert diagnostic["expected_destination"] == "life"
    assert diagnostic["context_status"] == "CONTRADICTORY_CONTEXT"
    assert diagnostic["failed_predicate"] == "OTHER_CONFIGURED_DESTINATION_BODY"
    assert diagnostic["navigation_epoch"] == "air-entry"
    assert diagnostic["destination_ownership"] is False
    assert diagnostic["other_destination_signals"]["structural_evidence"]
    assert diagnostic["activity"]["activity_name"].endswith("WebPluginActivity")
    assert diagnostic["window"]["window_count"] == 1
