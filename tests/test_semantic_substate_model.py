"""Phase 3D root identity and versioned semantic child contract."""
from copy import deepcopy
import json

import pytest

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.discovery_candidates import build_discovery_snapshot, candidate_set_delta
from tb_runner.semantic_substate import LEGACY_SIDECAR_VERSION, SUBSTATE_SCHEMA
from tb_runner.state_equality import EqualityVerdict, evaluate_state_equality
from tb_runner.state_observation import StateObservation, build_state_observation
from tb_runner.state_registry import StateRegistry
from tb_runner.transition_observation import TransitionObserver
from state_model_fixtures import node, observation


CARD = "pkg:id/favorite_device_card_camera"
ALERT = "pkg:id/camera_card_alert_animation_current"


def camera_raw(*, root="home", event="NONE", camera_focusable=False, partial=False):
    raw = observation(root)
    card = dict(node(CARD, "Camera card", "100,300,900,700", clickable=True, focusable=True),
                stable_node_path="root.camera", ancestors=[])
    raw["nodes"].append(card)
    if event in {"HUMAN", "MOTION", "PET", "UNKNOWN"}:
        child = dict(node(ALERT, "", "400,550,500,650", focusable=camera_focusable),
            stable_node_path="root.camera.0", ancestors=[dict(resource_id=CARD, class_name="android.widget.FrameLayout")])
        raw["nodes"].append(child)
    if event in {"HUMAN", "MOTION", "PET"}:
        raw["semantic_substates"] = [dict(schema_version=SUBSTATE_SCHEMA, category="CAMERA",
            key="detection_event", value=event, confidence="OBSERVED_EXACT",
            evidence={"producer_value": event, "source_node": ALERT if event != "NONE" else CARD},
            provenance={"producer": "test-observed-camera-payload", "source": "fixture"})]
    if partial:
        raw["navigation_context"] = None
    return raw


def pair(left, right):
    return evaluate_state_equality(build_state_observation(left), build_state_observation(right))


@pytest.mark.parametrize("event", ["HUMAN", "MOTION", "PET"])
def test_home_event_and_none_share_root_and_report_child_difference(event):
    result = pair(camera_raw(event="NONE"), camera_raw(event=event))
    assert result.verdict is EqualityVerdict.SAME
    doc = result.to_dict()
    assert doc["logical_state_equal"] is True
    assert doc["root_verdict"] == "SAME"
    assert doc["semantic_substate_relation"] == "DIFFERENT"
    assert {change["key"] for change in doc["semantic_substate_changes"]} >= {"detection_event"}


def test_home_human_and_motion_share_root_without_state_explosion():
    result = pair(camera_raw(event="HUMAN"), camera_raw(event="MOTION"))
    assert result.verdict is EqualityVerdict.SAME
    assert result.to_dict()["semantic_substate_relation"] == "DIFFERENT"


def test_home_camera_change_is_not_ambiguous_but_root_devices_is_different():
    assert pair(camera_raw(event="NONE"), camera_raw(event="UNKNOWN")).verdict is EqualityVerdict.SAME
    assert pair(camera_raw(event="NONE"), camera_raw(root="devices")).verdict is EqualityVerdict.DIFFERENT
    assert pair(camera_raw(event="NONE"), camera_raw(root="life")).verdict is EqualityVerdict.DIFFERENT


def test_unobserved_camera_event_is_unknown_substate_not_unknown_root():
    raw = camera_raw(event="UNKNOWN")
    obs = build_state_observation(raw)
    event = next(x for x in obs.semantic_substates if x["key"] == "detection_event")
    assert event["value"] == "UNKNOWN"
    assert event["confidence"] == "UNKNOWN"
    assert build_state_observation(camera_raw(event="NONE")).fingerprint.to_dict()["core"] == obs.fingerprint.to_dict()["core"]
    assert pair(camera_raw(event="NONE"), raw).verdict is EqualityVerdict.SAME


def test_partial_home_remains_ambiguous_even_with_same_root_and_substate():
    result = pair(camera_raw(event="HUMAN"), camera_raw(event="HUMAN", partial=True))
    assert result.verdict is EqualityVerdict.AMBIGUOUS
    assert result.logical_state_equal is None


@pytest.mark.parametrize("kind", ["dialog", "popup", "permission_sheet", "full_screen_mode"])
def test_full_screen_context_overlay_is_not_a_card_semantic_substate(kind):
    a = camera_raw(event="NONE")
    b = deepcopy(a)
    b["overlay"] = dict(kind=kind, observed=True, nodes=[node("pkg:id/dialog", "Permission")])
    result = pair(a, b)
    assert result.verdict is EqualityVerdict.DIFFERENT
    assert result.base_verdict is EqualityVerdict.SAME


def test_timestamp_only_remains_same_and_substate_payload_is_deterministic():
    a, b = camera_raw(event="NONE"), camera_raw(event="NONE")
    b["timestamp"] = "2026-10-05T02:00:00+09:00"
    left, right = build_state_observation(a), build_state_observation(b)
    assert evaluate_state_equality(left, right).verdict is EqualityVerdict.SAME
    restored = StateObservation.from_dict(json.loads(left.to_json()))
    assert restored.to_json() == left.to_json()
    assert restored.semantic_substates == left.semantic_substates


def test_legacy_phase23_sidecar_is_read_without_rewriting_its_document():
    current = build_state_observation(camera_raw(event="HUMAN")).to_dict()
    document = {k: v for k, v in current.items() if k != "observation_id"}
    document["secondary"]["version"] = LEGACY_SIDECAR_VERSION
    document["secondary"].pop("semantic_substates")
    legacy = dict(document, observation_id=canonical_sha256(document))
    restored = StateObservation.from_dict(legacy)
    assert restored.to_dict() == legacy
    assert restored.semantic_substates[0]["provenance"]["mapping_version"] == "legacy-camera-alert-family-adapter-v1"


def test_registry_reuses_root_but_persists_all_substate_observations_and_restart(tmp_path):
    registry = StateRegistry("phase3d-camera")
    first = registry.observe(build_state_observation(camera_raw(event="NONE")))
    second = registry.observe(build_state_observation(camera_raw(event="HUMAN")))
    third = registry.observe(build_state_observation(camera_raw(event="MOTION")))
    assert first.status == "CREATED"
    assert second.status == third.status == "REUSED"
    assert first.state_id == second.state_id == third.state_id
    assert registry.state_count == 1
    state = registry.states[0]
    assert len(state["semantic_substate_observations"]) == 3
    values = {tuple((v["key"], v["value"]) for v in row["values"])
              for row in state["semantic_substate_observations"]}
    assert len(values) == 3
    registry.save(tmp_path / "registry.json")
    restarted = StateRegistry.load(tmp_path / "registry.json")
    next_resolution = restarted.observe(build_state_observation(camera_raw(event="PET")))
    assert next_resolution.state_id == first.state_id
    assert StateRegistry.from_dict(restarted.to_dict()).to_json() == restarted.to_json()


def test_candidate_binding_uses_root_and_retains_substate_specific_candidate_changes():
    registry = StateRegistry("phase3d-candidates")
    normal = camera_raw(event="NONE")
    active = camera_raw(event="HUMAN", camera_focusable=True)
    normal_snapshot = build_discovery_snapshot(normal, registry)
    active_snapshot = build_discovery_snapshot(active, registry)
    assert normal_snapshot.state_id == active_snapshot.state_id
    assert normal_snapshot.to_dict()["semantic_substates"] != active_snapshot.to_dict()["semantic_substates"]
    delta = candidate_set_delta(normal_snapshot, active_snapshot)
    assert delta["comparable"] is True
    assert delta["NEW_CANDIDATE"] + delta["REMOVED_CANDIDATE"] >= 1
    assert all(c.state_id == normal_snapshot.state_id for c in active_snapshot.candidates)


def test_transition_keeps_source_result_substates_and_does_not_attribute_change_to_action():
    registry = StateRegistry("phase3d-transition")
    observer = TransitionObserver(registry)
    before = camera_raw(event="NONE")
    after = camera_raw(event="HUMAN")
    prepared = observer.prepare(before, dict(occurrence_id="device-camera-change", producer="fixture",
        action_kind="FOCUS_NEXT", target_identity={}))
    transition = observer.complete(prepared, after, command_ack={"success": True})
    doc = transition.to_dict()
    assert doc["source_state_id"] == doc["resulting_state_id"]
    assert doc["semantic_identity"]["equality_relation"] == "SAME"
    assert doc["semantic_identity"]["semantic_substate_relation"] == "DIFFERENT"
    assert doc["semantic_identity"]["substate_change_attribution"] == "UNATTRIBUTED_BETWEEN_CAPTURE_BOUNDARIES"
    assert doc["semantic_identity"]["source_semantic_substates"] != doc["semantic_identity"]["resulting_semantic_substates"]


def test_camera_node_evidence_remains_in_fingerprint_secondary_and_candidate_record():
    raw = camera_raw(event="HUMAN")
    obs = build_state_observation(raw)
    assert any(n["resource_id"] == ALERT for n in obs.fingerprint.to_dict()["viewport"]["semantic_nodes"])
    assert any(n["semantic"]["resource_id"] == ALERT for n in obs.secondary["nodes"])
    event = next(x for x in obs.semantic_substates if x["key"] == "detection_event")
    assert event["evidence"]["root_projection_nodes"]


@pytest.mark.parametrize("mutation", ["substate_checksum", "foreign_root_evidence"])
def test_corrupt_semantic_substate_is_rejected(mutation):
    doc = build_state_observation(camera_raw(event="HUMAN")).to_dict()
    if mutation == "substate_checksum":
        doc["secondary"]["semantic_substates"][0]["value"] = "MOTION"
    else:
        doc["secondary"]["semantic_substates"][0]["evidence"]["root_projection_nodes"].append({"resource_id": "fake"})
    with pytest.raises(ValueError):
        StateObservation.from_dict(doc)
