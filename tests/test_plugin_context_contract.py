from copy import deepcopy
from types import SimpleNamespace

import pytest

from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
from tb_runner.plugin_context_contract import plugin_context_evidence, navigation_epoch_guard
from tb_runner.scenario_config import TAB_CONFIGS


def observation(scenario="device_tv_plugin", label="TV"):
    config = next(c for c in TAB_CONFIGS if c["scenario_id"] == scenario)
    raw = dict(scenario_id=scenario, scenario_run_id="run-1", navigation_epoch="epoch-1",
               timestamp="2026-10-11T08:00:01+00:00", capture_id="capture-1",
               package_name="com.samsung.android.oneconnect", activity_name="pkg.WebPluginActivity",
               context_source="window_current_focus", nodes=[dict(text=label,
               viewIdResourceName="content-root", visibleToUser=True)])
    entry = phase3_entry_evidence_from_main_loop(SimpleNamespace(tab_cfg=config, rows=[dict(
        actual_focus_accessibility_focused=True, actual_focus_payload_source="verified_pre_loop_anchor")]),
        "run-1", raw["timestamp"])
    raw["phase3_entry_evidence"] = entry
    summary = dict(open_completed=True, entry_contract_reason="success_verified",
                   entry_contract_detail="plugin_open_verified")
    raw["phase3_plugin_context_evidence"] = plugin_context_evidence(entry, raw, summary, "epoch-1")
    return raw


@pytest.mark.parametrize("scenario,label", [("device_tv_plugin", "TV"), ("device_washer_plugin", "Washer"),
    ("life_energy_plugin", "Energy"), ("device_camera_plugin", "Camera"),
    ("life_food_plugin", "SmartThings Cooking"), ("life_find_plugin", "Current location"),
    ("life_family_care_plugin", "Family Care"), ("device_smoke_sensor_plugin", "Smoke detector")])
def test_generic_contract_across_configured_plugins(scenario, label):
    assert resolve_phase3_context(observation(scenario, label))["status"] == "VERIFIED_PLUGIN_CONTEXT"


def test_entry_post_open_with_incomplete_body_is_explicit_partial():
    raw = observation()
    raw["nodes"][0]["text"] = "Volume"
    result = resolve_phase3_context(raw)
    assert result["status"] == "PARTIAL_CONTEXT"
    assert result["context_tier"] == "PARTIAL_PLUGIN_CONTEXT"
    assert not result["verified"]


def test_scenario_name_only_cannot_authorize_context():
    assert resolve_phase3_context(dict(scenario_id="device_tv_plugin"))["status"] == "UNRESOLVED_CONTEXT"


@pytest.mark.parametrize("key,value", [("scenario_id", "device_washer_plugin"),
    ("scenario_run_id", "old-run"), ("navigation_epoch", "previous-epoch"),
    ("destination_identity", "wrong-destination"), ("entry_contract_digest", "old-config"),
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
    assert resolve_phase3_context(raw)["status"] == "CONTRADICTORY_CONTEXT"


def test_different_runtime_destination_is_contradictory():
    raw = observation()
    raw["nodes"][0]["text"] = "Washer"
    raw["nodes"][0]["role"] = "heading"
    assert resolve_phase3_context(raw)["status"] == "CONTRADICTORY_CONTEXT"


def test_shared_history_word_does_not_prove_a_different_destination():
    raw = observation(label="History")
    assert resolve_phase3_context(raw)["status"] == "PARTIAL_CONTEXT"


@pytest.mark.parametrize("key,value", [("activity_name", "pkg.OtherPluginActivity"),
    ("activity_name", "pkg.SCMainActivity"), ("package_name", "other.package")])
def test_current_component_cannot_reuse_previous_entry(key, value):
    raw = observation()
    raw[key] = value
    assert resolve_phase3_context(raw)["status"] == "CONTRADICTORY_CONTEXT"


def test_missing_current_component_is_not_verified_or_partial():
    raw = observation()
    raw["activity_name"] = None
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"


def test_successful_post_open_summary_is_required():
    raw = observation()
    raw["phase3_plugin_context_evidence"]["post_open_summary"]["entry_contract_reason"] = "verify_failed"
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"


def test_proof_builder_cannot_attest_input_focus_or_failed_entry():
    raw = observation()
    entry = deepcopy(raw["phase3_entry_evidence"])
    summary = raw["phase3_plugin_context_evidence"]["post_open_summary"]
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
