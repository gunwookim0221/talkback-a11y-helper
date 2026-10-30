from copy import deepcopy
from itertools import count
from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

from tb_runner.canonical_json import canonical_json_bytes, canonical_sha256
from phase6d_capture_support import attach_capture_authority, add_full_screen_hierarchy_modal
from tb_runner.state_fingerprint import (
    SCHEMA_VERSION, build_state_fingerprint, normalize_dynamic_text, write_fingerprint_record,
)


def node(rid="pkg:id/card", bounds="[0,100][500,200]", text="Device", **extra):
    return dict(viewIdResourceName=rid, className="android.widget.TextView", text=text,
                boundsInScreen=bounds, visibleToUser=True, enabled=True,
                checked=False, selected=False, clickable=True, focusable=True, scrollable=False, **extra)


def observation():
    tab = node("pkg:id/menu_favorites", "[0,900][200,1000]", "Home")
    tab["selected"] = True
    return attach_capture_authority(dict(nodes=[node(), tab], package_name="pkg", activity_name="pkg.MainActivity",
                display_bounds=[0, 0, 1000, 1000], capture_root_bounds=[0, 0, 1000, 1000],
                scenario_id="s", step=1, navigation_context={"bottom_tab": "home"},
                timestamp="2026-10-05T00:00:00Z",
                capability={"status": "SCROLL_CAPABLE", "can_scroll_forward": True, "source": "helper_metadata"}))


_CAPTURE_SEQUENCE = count(1000)


def recapture(raw):
    sequence = next(_CAPTURE_SEQUENCE)
    return attach_capture_authority(raw, sequence=sequence,
                                    request_id=f"state-fingerprint-fixture-{sequence}")


def test_determinism_and_no_input_mutation():
    value = observation()
    before = deepcopy(value)
    a, b = build_state_fingerprint(value), build_state_fingerprint(value)
    assert a.to_json().encode("utf-8") == b.to_json().encode("utf-8")
    assert a.fingerprint_hash == b.fingerprint_hash
    assert value == before
    assert a.schema_version == SCHEMA_VERSION


def test_model_is_immutable_and_export_is_independent():
    fp = build_state_fingerprint(observation())
    with pytest.raises(FrozenInstanceError):
        fp.core_signature = "bad"
    data = fp.to_dict()
    data["core"]["selected_tab"] = "bad"
    assert fp.to_dict()["core"]["selected_tab"] == "home"


def test_hash_contract_uses_versioned_normalized_sections_with_lf():
    fp = build_state_fingerprint(observation())
    payload = fp.to_dict()
    normalized = {key: payload[key] for key in ("schema_version", "core", "viewport", "overlay")}
    assert fp.fingerprint_hash == hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()
    assert fp.core_signature == canonical_sha256(payload["core"])
    assert fp.viewport_signature == canonical_sha256(payload["viewport"])
    assert fp.overlay_signature == canonical_sha256(payload["overlay"])
    assert "state_id" not in payload


def test_focus_only_changes_transient():
    a = observation()
    a["focus_node"] = dict(a["nodes"][0], accessibilityFocused=True)
    a["nodes"][0]["accessibilityFocused"] = True
    a["nodes"][1]["focused"] = False
    b = deepcopy(a)
    b["focus_node"] = dict(b["nodes"][1], accessibilityFocused=True)
    b["nodes"][0]["accessibilityFocused"] = False
    b["nodes"][1]["focused"] = True
    recapture(a); recapture(b)
    af, bf = build_state_fingerprint(a), build_state_fingerprint(b)
    assert (af.core_signature, af.viewport_signature, af.fingerprint_hash) == (
        bf.core_signature, bf.viewport_signature, bf.fingerprint_hash)
    assert af.to_dict()["transient"] != bf.to_dict()["transient"]


def test_observed_selected_tab_changes_core():
    a = observation()
    b = deepcopy(a)
    b["nodes"][1]["viewIdResourceName"] = "pkg:id/menu_devices"
    b["nodes"][1]["text"] = "Devices"
    b["navigation_context"] = {"bottom_tab": "devices"}
    recapture(b)
    assert build_state_fingerprint(a).core_signature != build_state_fingerprint(b).core_signature


@pytest.mark.parametrize("selected,status", [(None, "unknown"), (False, "unknown")])
def test_unverified_requested_tab_is_not_a_fact(selected, status):
    value = observation()
    value["nodes"][1]["selected"] = selected
    value["selected_tab"] = {"name": "devices", "verified": False}
    recapture(value)
    core = build_state_fingerprint(value).to_dict()["core"]
    assert core["selected_tab"] is None
    assert core["selected_tab_status"] == status


def test_ambiguous_selected_nodes_remain_unknown():
    value = observation()
    value["nodes"].append(deepcopy(value["nodes"][1]))
    recapture(value)
    core = build_state_fingerprint(value).to_dict()["core"]
    assert core["selected_tab"] is None and core["selected_tab_status"] == "ambiguous"


def test_display_bounds_are_diagnostic_and_mismatched_root_bounds_invalidate_capture():
    before = observation()
    display_only = deepcopy(before)
    display_only["display_bounds"] = [0, 0, 1440, 3200]
    left, right = build_state_fingerprint(before), build_state_fingerprint(display_only)
    assert left.core_signature == right.core_signature
    assert left.viewport_signature == right.viewport_signature
    assert left.fingerprint_hash == right.fingerprint_hash

    stale_root = deepcopy(before)
    stale_root["capture_root_bounds"] = [0, 0, 2000, 3000]
    stale = build_state_fingerprint(stale_root).to_dict()
    assert stale["core"]["package_name"] is None
    assert stale["viewport"]["bounds_strategy"] == "UNKNOWN_CAPTURE_ROOT_BOUNDS"


def test_authority_bound_full_screen_hierarchy_modal_is_distinct_phase2_identity():
    from tb_runner.state_equality import evaluate_state_equality
    from tb_runner.state_observation import build_state_observation

    base = observation()
    modal = deepcopy(base)
    add_full_screen_hierarchy_modal(modal, sequence=2, request_id="modal-root-capture-2")
    base_fp, modal_fp = build_state_fingerprint(base), build_state_fingerprint(modal)
    assert base_fp.core_signature == modal_fp.core_signature
    assert modal_fp.to_dict()["overlay"] == {
        "kind": "dialog", "observed": True,
        "semantic_nodes": modal_fp.to_dict()["overlay"]["semantic_nodes"],
    }
    assert modal_fp.to_dict()["overlay"]["semantic_nodes"]
    assert base_fp.overlay_signature != modal_fp.overlay_signature
    result = evaluate_state_equality(build_state_observation(base), build_state_observation(modal))
    assert result.verdict.value == "DIFFERENT"
    assert result.base_verdict.value == "SAME" and result.overlay_equal is False
    assert build_state_observation(modal).secondary["overlay_nodes"]


def test_authoritative_fingerprint_ignores_nodes_outside_sealed_root_tree():
    value = observation()
    baseline = build_state_fingerprint(value)
    value["nodes"] = [node("foreign:id/other-window", text="Other window content")]
    changed_compatibility_view = build_state_fingerprint(value)
    assert changed_compatibility_view.fingerprint_hash == baseline.fingerprint_hash
    assert changed_compatibility_view.to_dict()["viewport"] == baseline.to_dict()["viewport"]


def test_overlay_identity_requires_exact_root_tree_digest():
    base = observation()
    modal = deepcopy(base)
    add_full_screen_hierarchy_modal(modal, sequence=2, request_id="modal-root-tamper")
    modal["_capture_root_tree"]["children"][0]["text"] = "tampered after capture"
    modal["overlay"] = {"kind": "dialog", "observed": True, "source": "wms_diagnostic"}

    fingerprint = build_state_fingerprint(modal).to_dict()
    assert fingerprint["overlay"] == {"kind": "unknown", "observed": False, "semantic_nodes": []}
    assert fingerprint["core"]["package_name"] is None
    assert fingerprint["viewport"]["bounds_strategy"] == "UNKNOWN_CAPTURE_ROOT_BOUNDS"


def test_activity_and_wms_overlay_variation_leave_tree_state_identity_unchanged():
    from tb_runner.state_equality import evaluate_state_equality
    from tb_runner.state_observation import build_state_observation
    from tb_runner.state_registry import StateRegistry

    base = observation()
    diagnostics = deepcopy(base)
    diagnostics["activity_name"] = "other.diagnostic.Activity"
    diagnostics["window_evidence"] = {
        "diagnostic_focused_package": "other.package",
        "diagnostic_focused_activity": "other.diagnostic.Activity",
        "focused_window_type": "APPLICATION_ATTACHED_DIALOG",
    }
    diagnostics["overlay"] = {
        "kind": "dialog", "observed": True, "source": "wms_diagnostic",
        "classification": "VERIFIED_MODAL",
        "nodes": [node("pkg:id/wms_only_dialog", text="WMS only")],
    }
    left, right = build_state_fingerprint(base), build_state_fingerprint(diagnostics)
    assert left.fingerprint_hash == right.fingerprint_hash
    assert left.overlay_signature == right.overlay_signature
    assert evaluate_state_equality(build_state_observation(base),
                                   build_state_observation(diagnostics)).verdict.value == "SAME"
    registry = StateRegistry("diagnostic-overlay")
    first = registry.observe(build_state_observation(base))
    second = registry.observe(build_state_observation(diagnostics))
    assert first.state_id == second.state_id


def test_overlay_diagnostics_do_not_change_authoritative_fingerprint():
    base = observation()
    dialog = deepcopy(base)
    dialog["overlay"] = {"kind": "dialog", "observed": True,
                         "classification": "VERIFIED_MODAL", "source": "wms_diagnostic",
                         "nodes": [node("", text="Permission required")]}
    a, b = build_state_fingerprint(base), build_state_fingerprint(dialog)
    assert a.core_signature == b.core_signature
    assert a.overlay_signature == b.overlay_signature
    assert a.fingerprint_hash == b.fingerprint_hash
    assert b.to_dict()["overlay"]["kind"] == "unknown"
    assert b.to_dict()["transient"]["overlay_diagnostic"]["classification"] == "VERIFIED_MODAL"


@pytest.mark.parametrize("before,after", [
    ("23°C", "24°C"), ("-1.5 ℃", "+2.3 ℃"), ("74°F", "75°F"),
    ("battery 75%", "battery 74%"), ("배터리 75%", "배터리 74%"),
    ("time 10:31", "time 10:32"), ("시각 10:31", "시각 10:32"), ("10:31", "10:32"),
])
def test_typed_dynamic_values_are_normalized_and_raw_digest_retained(before, after):
    a, b = observation(), observation()
    a["nodes"][0] = node("", text=before)
    b["nodes"][0] = node("", text=after)
    recapture(a); recapture(b)
    af, bf = build_state_fingerprint(a), build_state_fingerprint(b)
    assert af.fingerprint_hash == bf.fingerprint_hash
    assert af.to_dict()["transient"]["raw_observation_digest"] != bf.to_dict()["transient"]["raw_observation_digest"]


@pytest.mark.parametrize("before,after", [("Model 23", "Model 24"), ("Price 75", "Price 74"),
                                         ("Sensor 23 ppm", "Sensor 24 ppm"), ("Door locked", "Door unlocked")])
def test_general_numbers_and_meaningful_semantics_are_not_masked(before, after):
    assert normalize_dynamic_text(before) != normalize_dynamic_text(after)


@pytest.mark.parametrize("rid", ["pkg:id/door", ""])
def test_locked_unlocked_change_is_preserved_even_with_resource_id(rid):
    a, b = observation(), observation()
    a["nodes"][0] = node(rid, text="Door locked")
    b["nodes"][0] = node(rid, text="Door unlocked")
    recapture(a); recapture(b)
    assert build_state_fingerprint(a).fingerprint_hash != build_state_fingerprint(b).fingerprint_hash


def test_open_is_not_unlocked():
    a, b = observation(), observation()
    a["nodes"][0] = node(text="문 열림")
    b["nodes"][0] = node(text="잠금 해제")
    recapture(a); recapture(b)
    assert build_state_fingerprint(a).viewport_signature != build_state_fingerprint(b).viewport_signature


def test_same_resource_id_instances_are_never_set_deduplicated():
    value = observation()
    value["nodes"] = [node(bounds="0,100,500,200"), node(bounds="0,300,500,400")]
    recapture(value)
    fp = build_state_fingerprint(value).to_dict()
    nodes = fp["viewport"]["semantic_nodes"]
    assert len(nodes) == 2 and nodes[0]["resource_id"] == nodes[1]["resource_id"]
    assert nodes[0]["layout_bucket"] != nodes[1]["layout_bucket"]
    assert len(set(fp["transient"]["positional_instance_ids"])) == 2
    value["nodes"] = [node(), node()]
    recapture(value)
    assert len(build_state_fingerprint(value).to_dict()["viewport"]["semantic_nodes"]) == 2


def test_flat_and_nested_ordering_are_stable():
    a = observation()
    a["nodes"] = [dict(node("parent"), children=a["nodes"])]
    b = deepcopy(a)
    b["nodes"][0]["children"].reverse()
    recapture(a); recapture(b)
    assert build_state_fingerprint(a).to_json() == build_state_fingerprint(b).to_json()


def test_ko_en_resource_structure_is_stable():
    a, b = observation(), observation()
    a["nodes"][0]["text"], a["nodes"][1]["text"] = "장치", "홈"
    b["nodes"][0]["text"], b["nodes"][1]["text"] = "Device", "Home"
    recapture(a); recapture(b)
    af, bf = build_state_fingerprint(a), build_state_fingerprint(b)
    assert af.core_signature == bf.core_signature
    assert af.viewport_signature == bf.viewport_signature
    assert af.to_dict()["transient"]["raw_observation_digest"] != bf.to_dict()["transient"]["raw_observation_digest"]


def test_known_state_description_is_locale_stable():
    a, b = observation(), observation()
    a["nodes"][0]["stateDescription"], b["nodes"][0]["stateDescription"] = "잠김", "Locked"
    recapture(a); recapture(b)
    assert build_state_fingerprint(a).fingerprint_hash == build_state_fingerprint(b).fingerprint_hash


def test_diagnostic_activity_does_not_change_authoritative_fingerprint():
    a, b = observation(), observation()
    b["activity_name"] = "pkg.mainActivity"
    af, bf = build_state_fingerprint(a), build_state_fingerprint(b)
    assert af.core_signature == bf.core_signature
    assert af.fingerprint_hash == bf.fingerprint_hash
    assert bf.to_dict()["transient"]["raw_context"]["activity_name"] == "pkg.mainActivity"
    b["window_evidence"] = {"focused_window_component": "com.android.systemui/.Shade",
                            "focused_window_type": "NOTIFICATION_SHADE"}
    b["overlay"] = {"kind": "wms_popup", "observed": None,
                     "classification": "UNKNOWN_COMPONENT_BINDING"}
    assert build_state_fingerprint(a).fingerprint_hash == build_state_fingerprint(b).fingerprint_hash
    b = observation()
    b["nodes"][0]["viewIdResourceName"] = "pkg:id/Card"
    recapture(b)
    assert build_state_fingerprint(a).viewport_signature != build_state_fingerprint(b).viewport_signature


def test_package_mismatch_disables_authoritative_capture_identity():
    value = observation()
    value["package_name"] = "other.package"
    fingerprint = build_state_fingerprint(value)
    assert fingerprint.to_dict()["core"]["package_name"] is None
    assert fingerprint.to_dict()["viewport"]["bounds_strategy"] == "UNKNOWN_CAPTURE_ROOT_BOUNDS"


def test_traversal_root_mismatch_disables_authoritative_capture_normalization():
    value = observation()
    value["traversal_root_window_id"] += 1
    fingerprint = build_state_fingerprint(value)
    assert fingerprint.to_dict()["core"]["package_name"] is None
    assert fingerprint.to_dict()["viewport"]["bounds_strategy"] == "UNKNOWN_CAPTURE_ROOT_BOUNDS"


def test_android_short_activity_expands_only_with_observed_package():
    a, b = observation(), observation()
    b["activity_name"] = ".MainActivity"
    af, bf = build_state_fingerprint(a), build_state_fingerprint(b)
    assert af.fingerprint_hash == bf.fingerprint_hash
    assert bf.to_dict()["transient"]["raw_context"]["activity_name"] == ".MainActivity"
    b["package_name"] = None
    assert build_state_fingerprint(b).to_dict()["core"]["activity_name"] is None


def test_idless_content_description_is_used_when_text_empty():
    value = observation()
    value["nodes"] = [node("", text="", contentDescription="Settings")]
    recapture(value)
    semantic = build_state_fingerprint(value).to_dict()["viewport"]["semantic_nodes"][0]
    assert semantic["text_fallback"] == "settings"


def test_scroll_preserves_context_and_changes_viewport():
    a, b = observation(), observation()
    b["nodes"][0]["boundsInScreen"] = "0,300,500,400"
    recapture(b)
    af, bf = build_state_fingerprint(a), build_state_fingerprint(b)
    assert af.core_signature == bf.core_signature and af.viewport_signature != bf.viewport_signature


def test_bounds_scaled_with_capture_root_and_small_motion_stay_in_bucket():
    a, b = observation(), observation()
    a["nodes"] = [node(bounds="0,100,500,200")]
    b["nodes"] = [node(bounds="0,200,1000,400")]
    recapture(a)
    b["display_bounds"] = [0, 0, 2000, 2000]
    b["capture_root_bounds"] = [0, 0, 2000, 2000]
    recapture(b)
    assert build_state_fingerprint(a).viewport_signature == build_state_fingerprint(b).viewport_signature
    b["nodes"] = [node(bounds="1,101,501,201")]
    b["display_bounds"] = a["display_bounds"]
    b["capture_root_bounds"] = a["capture_root_bounds"]
    attach_capture_authority(b)
    assert build_state_fingerprint(a).viewport_signature == build_state_fingerprint(b).viewport_signature


def test_missing_invalid_bounds_and_unknown_fields_are_explicit():
    value = {"nodes": [{"text": "hello", "bounds": "invalid"}]}
    payload = build_state_fingerprint(value).to_dict()
    assert payload["viewport"]["bounds_strategy"] == "UNKNOWN_CAPTURE_ROOT_BOUNDS"
    assert payload["viewport"]["semantic_nodes"][0]["layout_bucket"] is None
    assert payload["transient"]["invalid_bounds_count"] == 1
    assert payload["transient"]["unknown_node_fields"]["enabled"] == 1
    assert payload["core"]["selected_tab"] is None


def test_invisible_nodes_are_excluded():
    value = observation()
    invisible = node("hidden")
    invisible["visibleToUser"] = False
    value["nodes"].append(invisible)
    recapture(value)
    assert len(build_state_fingerprint(value).to_dict()["viewport"]["semantic_nodes"]) == 2


def test_persistent_markers_change_core_without_geometry():
    a, b = observation(), observation()
    a["core_nodes"] = [node("", text="Settings")]
    b["core_nodes"] = [node("", text="Details")]
    assert build_state_fingerprint(a).core_signature != build_state_fingerprint(b).core_signature
    b["core_nodes"] = [node("", bounds="0,300,500,400", text="Settings")]
    assert build_state_fingerprint(a).core_signature == build_state_fingerprint(b).core_signature


@pytest.mark.parametrize("field,value", [("nodes", {}), ("core_nodes", {}), ("capability", [1]),
                                         ("overlay", [1]), ("focus_node", [1])])
def test_invalid_input_types_raise(field, value):
    with pytest.raises(ValueError):
        build_state_fingerprint({field: value})


def test_jsonl_has_summary_hashes_and_no_raw_xml(tmp_path):
    value = observation()
    value["nodes"][0]["raw_xml"] = "<large>not copied</large>"
    recapture(value)
    fp = build_state_fingerprint(value)
    path = tmp_path / "state_fingerprints.jsonl"
    write_fingerprint_record(path, fp)
    write_fingerprint_record(path, fp)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[0] == lines[1]
    record = json.loads(lines[0])
    assert (record["scenario_id"], record["step"], record["timestamp"]) == ("s", 1, value["timestamp"])
    assert record["fingerprint_hash"] == fp.fingerprint_hash
    assert "not copied" not in lines[0]
