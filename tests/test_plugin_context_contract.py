from copy import deepcopy
from types import SimpleNamespace

import pytest

from phase6d_capture_support import attach_capture_authority
from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
from tb_runner.plugin_context_contract import plugin_context_evidence, navigation_epoch_guard
from tb_runner.scenario_config import TAB_CONFIGS


def observation(scenario="device_tv_plugin", label="TV"):
    config = next(c for c in TAB_CONFIGS if c["scenario_id"] == scenario)
    raw = dict(scenario_id=scenario, scenario_run_id="run-1", navigation_epoch="epoch-1",
               timestamp="2026-10-11T08:00:01+00:00", capture_id="capture-1",
               package_name="com.samsung.android.oneconnect", activity_name="pkg.WebPluginActivity",
               context_source="helper_tree_component", nodes=[dict(text=label,
               viewIdResourceName="content-root", visibleToUser=True)])
    entry = phase3_entry_evidence_from_main_loop(SimpleNamespace(tab_cfg=config, rows=[dict(
        actual_focus_accessibility_focused=True, actual_focus_payload_source="verified_pre_loop_anchor")]),
        "run-1", raw["timestamp"])
    raw["phase3_entry_evidence"] = entry
    summary = dict(open_completed=True, entry_contract_reason="success_verified",
                   entry_contract_detail="plugin_open_verified")
    raw["hierarchy_capture_id"] = raw["capture_id"]
    attach_capture_authority(raw)
    raw["phase3_plugin_context_evidence"] = plugin_context_evidence(entry, raw, summary, "epoch-1")
    return raw


@pytest.mark.parametrize("scenario,label", [("device_tv_plugin", "TV"), ("device_washer_plugin", "Washer"),
    ("life_energy_plugin", "Energy"), ("device_camera_plugin", "Camera"),
    ("life_food_plugin", "SmartThings Cooking"), ("life_find_plugin", "Current location"),
    ("life_family_care_plugin", "Family Care"), ("device_smoke_sensor_plugin", "Smoke detector")])
def test_generic_contract_across_configured_plugins(scenario, label):
    result = resolve_phase3_context(observation(scenario, label))
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert result["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]


def test_entry_post_open_with_incomplete_body_is_explicit_partial():
    raw = observation()
    raw["nodes"][0]["text"] = "Volume"
    result = resolve_phase3_context(raw)
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert not result["verified"]
    assert result["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]


def test_context_contract_key_and_legacy_alias_remain_contract_only():
    raw = observation()
    proof = raw["phase3_plugin_context_evidence"]
    assert proof["schema_version"] == "generic-plugin-entry-observation-v1"
    assert proof["proof_capture_id"] == raw["capture_authority"]["capture_key"]
    assert "activity_name" not in proof and "component_capture_key" not in proof
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"


def test_mutable_dumpsys_component_label_cannot_verify_context():
    raw = observation()
    raw["context_source"] = "window_current_focus"
    raw["activity_name"] = "pkg.ForgedActivity"
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"
    assert resolve_phase3_context(raw)["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]


def test_delayed_activity_and_dumpsys_component_never_join_capture_local_context():
    raw = observation()
    baseline = resolve_phase3_context(raw)
    raw["activity_name"] = "pkg.OtherScreenActivity"
    raw["context_source"] = "window_current_focus"
    raw["window_evidence"] = {
        "diagnostic_focused_package": "other.package",
        "diagnostic_focused_activity": "pkg.OtherScreenActivity",
        "focused_window_component": "pkg.OtherScreenActivity",
    }
    assert resolve_phase3_context(raw) == baseline
    assert baseline["status"] == "UNRESOLVED_CONTEXT"
    assert baseline["verified"] is False


def test_forged_activity_and_resource_profile_without_authority_component_stay_unknown():
    raw = observation()
    attach_capture_authority(raw)
    raw["activity_name"] = "pkg.WebPluginActivity"
    raw["context_source"] = "helper_tree_component"
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"
    assert resolve_phase3_context(raw)["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]
    assert plugin_context_evidence(raw["phase3_entry_evidence"], raw,
        {"open_completed": True}, "epoch-1") == {}


def test_scenario_name_only_cannot_authorize_context():
    assert resolve_phase3_context(dict(scenario_id="device_tv_plugin"))["status"] == "UNRESOLVED_CONTEXT"


@pytest.mark.parametrize("key,value", [("scenario_id", "device_washer_plugin"),
    ("scenario_run_id", "old-run"), ("navigation_epoch", "previous-epoch"),
    ("context_contract_id", "wrong-contract"), ("entry_contract_digest", "old-config"),
    ("captured_at", "2026-10-12T08:00:01+00:00"), ("proof_capture_id", ""),
    ("post_open_verified", False), ("schema_version", "unknown")])
def test_stale_or_mismatched_proof_is_unresolved(key, value):
    raw = observation()
    raw["phase3_plugin_context_evidence"][key] = value
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"


@pytest.mark.parametrize("key,value", [("scenario_run_id", "new-run"),
    ("scenario_id", "device_washer_plugin"), ("navigation_epoch", "new-navigation")])
def test_evidence_expires_on_owner_or_epoch_change(key, value):
    raw = observation()
    raw[key] = value
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"


def test_wrong_selected_tab_is_contradictory():
    raw = observation()
    raw["selected_tab"] = dict(name="life", verified=True, source="service_hierarchy_selected")
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"


def test_different_runtime_destination_is_contradictory():
    raw = observation()
    raw["nodes"][0]["text"] = "Washer"
    raw["nodes"][0]["role"] = "heading"
    assert resolve_phase3_context(raw)["status"] == "CONTRADICTORY_CONTEXT"


def test_shared_history_word_does_not_prove_a_different_destination():
    raw = observation(label="History")
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"


def test_capture_authority_rejects_activity_component_fields():
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
    raw = observation()
    forged = dict(raw["capture_authority"], component_activity_name="pkg.WebPluginActivity")
    assert validate_capture_authority(forged) is None


def test_root_only_authority_cannot_verify_caller_supplied_activity():
    raw = observation()
    raw["activity_name"] = "pkg.WebPluginActivity"
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"
    assert resolve_phase3_context(raw)["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]


def test_post_open_summary_cannot_promote_root_only_authority():
    raw = observation()
    raw["phase3_plugin_context_evidence"] = {"post_open_verified": True,
        "post_open_summary": {"entry_contract_reason": "success_verified"}}
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"


def test_proof_builder_cannot_attest_input_focus_or_failed_entry():
    raw = observation()
    entry = deepcopy(raw["phase3_entry_evidence"])
    summary = {"open_completed": True, "entry_contract_reason": "success_verified"}
    entry["entry_anchor_accessibility_focused"] = False
    assert plugin_context_evidence(entry, raw, summary, "epoch-1") == {}
    assert plugin_context_evidence(raw["phase3_entry_evidence"], raw, {}, "epoch-1") == {}


def test_context_projection_does_not_mutate_observation_or_ledger():
    raw = observation()
    original = deepcopy(raw)
    resolve_phase3_context(raw)
    assert raw == original


@pytest.mark.parametrize("command,navigation", [(["shell","input","keyevent","4"], True),
    (["shell","am","start","pkg/activity"], True), (["shell","input","tap","10","20"], True),
    (["shell","dumpsys","window"], False), (["shell","wm","size"], False)])
def test_native_navigation_invalidates_epoch_without_altering_commands(command, navigation):
    calls, invalidations = [], []
    class Client:
        def _run(self, args, **kwargs): calls.append((args,kwargs)); return "original"
    client=Client()
    with navigation_epoch_guard(client, lambda: invalidations.append(True)):
        assert client._run(command, dev="serial") == "original"
    assert calls == [(command,dict(dev="serial"))]
    assert bool(invalidations) == navigation
    assert "_run" not in client.__dict__


def test_focus_and_scroll_preserve_epoch_but_click_expires_it():
    events=[]
    client=SimpleNamespace(_broadcast=lambda dev, action: action)
    original=client._broadcast
    with navigation_epoch_guard(client,lambda:events.append("navigation")):
        assert client._broadcast("serial","FOCUS_TARGET") == "FOCUS_TARGET"
        assert client._broadcast("serial","SCROLL") == "SCROLL"
        assert not events
        client._broadcast("serial","CLICK_FOCUSED")
    assert events == ["navigation"]
    assert client._broadcast is original


def test_navigation_guard_restores_client_after_exception():
    client=SimpleNamespace(tap_xy_adb=lambda *a: (_ for _ in ()).throw(RuntimeError("command")))
    original=client.tap_xy_adb
    with pytest.raises(RuntimeError), navigation_epoch_guard(client,lambda:None):
        client.tap_xy_adb("serial",1,2)
    assert client.tap_xy_adb is original
