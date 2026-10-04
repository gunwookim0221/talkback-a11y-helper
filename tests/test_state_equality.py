from copy import deepcopy
import json

import pytest

from tb_runner.canonical_json import canonical_sha256
from tb_runner.state_observation import StateObservation, build_state_observation, fingerprint_from_dict
from tb_runner.state_equality import EqualityVerdict, StateIdentity, VerifiedScrollEvidence, evaluate_state_equality
from state_model_fixtures import node, observation, scroll_pair


def compare(a, b, evidence=None):
    return evaluate_state_equality(build_state_observation(a), build_state_observation(b), evidence)


def test_same_observation_same_and_deterministic():
    a = observation()
    before = deepcopy(a)
    result = compare(a, a)
    assert result.verdict == EqualityVerdict.SAME
    assert result.logical_state_equal is True and result.viewport_equal is True
    assert result.to_json() == compare(a, a).to_json()
    assert a == before


def test_focus_churn_is_same():
    a, b = observation(), observation()
    a["nodes"][0]["accessibilityFocused"] = True
    b["nodes"][1]["accessibilityFocused"] = True
    a["focus_node"], b["focus_node"] = a["nodes"][0], b["nodes"][1]
    b["timestamp"], b["step"] = "2026-10-05T01:00:10+09:00", 10
    assert compare(a, b).verdict == EqualityVerdict.SAME
    assert compare(a, b).viewport_equal is True


@pytest.mark.parametrize("root", ["devices", "life"])
def test_roots_are_different(root):
    result = compare(observation(), observation(root))
    assert result.verdict == EqualityVerdict.DIFFERENT
    assert "HARD_SCOPE_CHANGED" in result.reasons


def test_scroll_is_same_logical_state_with_different_viewport_only_when_linked():
    a, b, _, proof = scroll_pair()
    assert compare(a, b).verdict == EqualityVerdict.AMBIGUOUS
    result = compare(a, b, proof)
    assert result.verdict == EqualityVerdict.SAME
    assert result.logical_state_equal is True and result.viewport_equal is False
    assert "LINKED_VERIFIED_SCROLL_CONTINUITY" in result.reasons
    assert compare(b, a, proof).verdict == EqualityVerdict.SAME


@pytest.mark.parametrize("field,value", [("action_success", False), ("viewport_changed", False), ("status", "SCROLL_NO_CHANGE")])
def test_ack_or_failed_scroll_is_not_continuity(field, value):
    a, b, result, _ = scroll_pair()
    result[field] = value
    with pytest.raises(ValueError):
        VerifiedScrollEvidence.from_transition(build_state_observation(a), build_state_observation(b), result)


def test_scroll_evidence_cannot_link_unrelated_capture_or_changed_semantics():
    a, b, _, proof = scroll_pair()
    wrong = deepcopy(b)
    wrong["timestamp"] = "2026-10-05T01:01:00+09:00"
    assert compare(a, wrong, proof).verdict == EqualityVerdict.AMBIGUOUS
    b["nodes"][1]["enabled"] = False
    assert compare(a, b, proof).verdict == EqualityVerdict.DIFFERENT


@pytest.mark.parametrize("kind", ["dialog", "popup", "bottom_sheet", "permission_overlay"])
def test_overlay_is_distinct_interaction_on_same_base(kind):
    a, b = observation(), observation()
    b["overlay"] = dict(kind=kind, observed=True, nodes=[node("pkg:id/dialog", "Permission")])
    result = compare(a, b)
    assert result.verdict == EqualityVerdict.DIFFERENT
    assert result.base_state_equal is True and result.overlay_equal is False


@pytest.mark.parametrize("before,after", [("23°C", "24°C"), ("battery 75%", "battery 74%"), ("time 10:31", "time 10:32")])
@pytest.mark.parametrize("rid", ["pkg:id/measurement", ""])
def test_dynamic_value_is_same(before, after, rid):
    a, b = observation(), observation()
    a["nodes"][0], b["nodes"][0] = node(rid, before), node(rid, after)
    assert compare(a, b).verdict == EqualityVerdict.SAME


@pytest.mark.parametrize("before,after", [("locked", "unlocked"), ("connected", "disconnected"), ("온라인", "오프라인")])
def test_meaningful_semantic_states_are_different(before, after):
    a, b = observation(), observation()
    a["nodes"][0]["text"], b["nodes"][0]["text"] = before, after
    result = compare(a, b)
    assert result.verdict == EqualityVerdict.DIFFERENT
    assert "MEANINGFUL_SEMANTIC_STATE_CHANGED" in result.reasons


@pytest.mark.parametrize("flag", ["enabled", "checked", "selected"])
def test_boolean_semantic_states_are_different(flag):
    a, b = observation(), observation()
    b["nodes"][0][flag] = not a["nodes"][0][flag]
    assert compare(a, b).verdict == EqualityVerdict.DIFFERENT


def test_unknown_flag_is_ambiguous_not_false():
    a, b = observation(), observation()
    b["nodes"][0].pop("enabled")
    assert compare(a, b).verdict == EqualityVerdict.AMBIGUOUS


def test_node_order_and_duplicate_instances_preserved():
    a = observation()
    a["nodes"].append(node(bounds="0,300,500,400"))
    b = deepcopy(a)
    b["nodes"].reverse()
    oa = build_state_observation(a)
    assert len(oa.secondary["nodes"]) == 3
    assert compare(a, b).verdict == EqualityVerdict.SAME


def test_known_ko_en_structural_fixture_is_same_candidate():
    a, b = observation(), observation()
    a["nodes"][0]["text"], a["nodes"][1]["text"] = "장치", "홈"
    b["nodes"][0]["text"], b["nodes"][1]["text"] = "Device", "Home"
    a["locale"], b["locale"] = "ko-KR", "en-US"
    assert compare(a, b).verdict == EqualityVerdict.SAME


def test_unknown_translation_is_ambiguous_not_a_false_merge():
    a, b = observation(), observation()
    a["nodes"][0]["text"], b["nodes"][0]["text"] = "알 수 없는 제목", "Unreviewed translation"
    assert compare(a, b).verdict == EqualityVerdict.AMBIGUOUS


def test_coarse_core_and_whole_fingerprint_collision_is_reproduced_and_not_merged():
    a, b = observation(), observation()
    a["nodes"][0]["text"], b["nodes"][0]["text"] = "Settings subpage", "Details subpage"
    oa, ob = build_state_observation(a), build_state_observation(b)
    assert oa.fingerprint.core_signature == ob.fingerprint.core_signature
    assert oa.fingerprint.fingerprint_hash == ob.fingerprint.fingerprint_hash
    assert evaluate_state_equality(oa, ob).verdict == EqualityVerdict.AMBIGUOUS


@pytest.mark.parametrize("field,value", [("package_name", None), ("activity_name", None),
                                        ("navigation_context", None), ("nodes", []), ("display_bounds", None)])
def test_insufficient_identical_observation_is_ambiguous(field, value):
    raw = observation(**{field: value})
    assert compare(raw, raw).verdict == EqualityVerdict.AMBIGUOUS
    assert compare(raw, raw).logical_state_equal is None


def test_partial_full_and_partial_subset_are_not_blindly_same():
    a, b = observation(), observation(observation_coverage="OBSERVED_FULL")
    assert compare(a, b).verdict == EqualityVerdict.AMBIGUOUS
    b = deepcopy(a)
    b["nodes"].pop(0)
    assert compare(a, b).verdict == EqualityVerdict.AMBIGUOUS


def test_duplicate_same_geometry_with_different_semantics_is_ambiguous():
    a = observation()
    a["nodes"].append(deepcopy(a["nodes"][0]))
    b = deepcopy(a)
    b["nodes"][0]["enabled"] = False
    assert compare(a, b).verdict == EqualityVerdict.AMBIGUOUS


def test_neutral_layout_container_count_change_is_viewport_only_with_verified_scroll():
    a, b, transition, _ = scroll_pair()
    neutral = node("", "", "0,0,1000,1000", className="android.widget.FrameLayout")
    a["nodes"].extend([deepcopy(neutral) for _ in range(3)])
    b["nodes"].extend([deepcopy(neutral) for _ in range(4)])
    oa, ob = build_state_observation(a), build_state_observation(b)
    proof = VerifiedScrollEvidence.from_transition(oa, ob, transition)
    assert evaluate_state_equality(oa, ob).verdict == EqualityVerdict.AMBIGUOUS
    assert evaluate_state_equality(oa, ob, proof).verdict == EqualityVerdict.SAME
    b["nodes"][-1]["enabled"] = False
    ob = build_state_observation(b)
    proof = VerifiedScrollEvidence.from_transition(oa, ob, transition)
    assert evaluate_state_equality(oa, ob, proof).verdict == EqualityVerdict.AMBIGUOUS


def test_persistent_markers_distinguish_subpages():
    a, b = observation(), observation()
    a["core_nodes"] = [node("pkg:id/settings_panel")]
    b["core_nodes"] = [node("pkg:id/details_panel")]
    assert compare(a, b).verdict == EqualityVerdict.DIFFERENT


def test_environment_partition_is_hard_and_missing_is_ambiguous():
    a, b = observation(environment_partition="app-v1"), observation(environment_partition="app-v2")
    assert compare(a, b).verdict == EqualityVerdict.DIFFERENT
    b.pop("environment_partition")
    assert compare(a, b).verdict == EqualityVerdict.AMBIGUOUS


@pytest.mark.parametrize("before,after", [
    ("파인드, KOR003의 Z Fold8, 최근 위치 확인: 59분 전","파인드, KOR003의 Z Fold8, 최근 위치 확인: 1시간 전"),
    ("Find, KOR003, last location update: 59 minutes ago","Find, KOR003, last location update: 1 hour ago"),
    ("파인드, KOR003의 Z Fold8, 최근 위치 확인: 59분 전","파인드, KOR003의 Z Fold8, 최근 위치 확인: 지금"),
    ("파인드, KOR003의 Z Fold8, 최근 위치 확인: 1시간 10분 전","파인드, KOR003의 Z Fold8, 최근 위치 확인: 방금"),
    ("Find, KOR003, last location update: 59 minutes ago","Find, KOR003, last location update: now"),
    ("Find, KOR003, last location update: 1 hour 10 minutes ago","Find, KOR003, last location update: just now"),
])
def test_typed_location_age_changes_are_same_without_modifying_saved_sidecar(before,after):
    a,b=observation(),observation()
    a["nodes"][0],b["nodes"][0]=node("pkg:id/map_area",before),node("pkg:id/map_area",after)
    oa,ob=build_state_observation(a),build_state_observation(b)
    original=oa.to_json()
    assert evaluate_state_equality(oa,ob).verdict==EqualityVerdict.SAME
    assert oa.to_json()==original
    b["nodes"][0]["text"]=after.replace("KOR003","KOR004")
    assert compare(a,b).verdict==EqualityVerdict.AMBIGUOUS


def test_location_age_mask_does_not_apply_to_unrelated_id_or_context():
    a,b=observation(),observation()
    a["nodes"][0]["text"],b["nodes"][0]["text"]="최근 위치 확인: 59분 전","최근 위치 확인: 1시간 전"
    assert compare(a,b).verdict==EqualityVerdict.AMBIGUOUS
    a["nodes"][0],b["nodes"][0]=node("pkg:id/map_area","Locked 59 minutes ago"),node("pkg:id/map_area","Unlocked 1 hour ago")
    assert compare(a,b).verdict==EqualityVerdict.AMBIGUOUS


def test_model_roundtrip_and_exports_independent():
    original = build_state_observation(observation())
    restored = StateObservation.from_dict(json.loads(original.to_json()))
    assert restored.to_json() == original.to_json()
    mutated = original.secondary
    mutated["nodes"].clear()
    assert original.secondary["nodes"]
    assert evaluate_state_equality(original, restored).verdict == EqualityVerdict.SAME


def test_fingerprint_hash_is_not_state_id_and_bare_hash_is_rejected():
    obs = build_state_observation(observation())
    identity = StateIdentity("state-000001", "coarse-index")
    assert identity.state_id != obs.fingerprint.fingerprint_hash
    with pytest.raises(TypeError):
        evaluate_state_equality(obs.fingerprint, obs.fingerprint)


@pytest.mark.parametrize("component", ["core_signature", "viewport_signature", "overlay_signature", "fingerprint_hash"])
def test_corrupted_fingerprint_component_is_rejected(component):
    payload = build_state_observation(observation()).fingerprint.to_dict()
    payload[component] = "bad"
    with pytest.raises(ValueError):
        fingerprint_from_dict(payload)


def test_observation_checksum_and_version_rejected():
    obs = build_state_observation(observation())
    value = obs.to_dict()
    value["coverage"] = "OBSERVED_FULL"
    with pytest.raises(ValueError):
        StateObservation.from_dict(value)
    value = obs.to_dict()
    value["schema_version"] = "future-version"
    with pytest.raises(ValueError):
        StateObservation.from_dict(value)


def test_scroll_evidence_roundtrip_requires_referential_integrity():
    a, b, _, proof = scroll_pair()
    oa, ob = build_state_observation(a), build_state_observation(b)
    restored = VerifiedScrollEvidence.from_dict(proof.to_dict(), {oa.observation_id: oa, ob.observation_id: ob})
    assert restored.to_dict() == proof.to_dict()
    with pytest.raises(ValueError):
        VerifiedScrollEvidence.from_dict(proof.to_dict(), {})
