from copy import deepcopy
import json

import pytest

from tb_runner.canonical_json import canonical_sha256
from tb_runner.state_observation import build_state_observation
from tb_runner.state_equality import VerifiedScrollEvidence
from tb_runner.state_registry import REGISTRY_SCHEMA, StateRegistry
from state_model_fixtures import node, observation, scroll_pair


def observe(registry, raw, proof=None):
    return registry.observe(build_state_observation(raw), proof)


def reseal(value):
    value["content_sha256"] = canonical_sha256({k:v for k,v in value.items() if k != "content_sha256"})
    return value


def test_empty_registry_is_deterministic_and_roundtrips():
    registry = StateRegistry()
    assert registry.state_count == registry.observation_count == registry.unresolved_count == 0
    assert registry.to_dict()["schema_version"] == REGISTRY_SCHEMA
    assert StateRegistry.from_dict(registry.to_dict()).to_json() == registry.to_json()


def test_first_observation_creates_and_repeated_observation_reuses_with_counts():
    registry = StateRegistry()
    first = observe(registry, observation())
    second = observe(registry, observation())
    assert (first.status, second.status) == ("CREATED", "REUSED")
    assert first.state_id == second.state_id
    state = registry.states[0]
    assert state["observation_count"] == 2 and len(state["observation_ids"]) == 1
    assert state["last_seen"]["sequence"] == 2
    assert registry.observation_count == 2
    assert first.state_id != build_state_observation(observation()).fingerprint.fingerprint_hash


def test_focus_only_does_not_create_state():
    registry = StateRegistry()
    a, b = observation(), observation()
    b["focus_node"] = node(accessibilityFocused=True)
    b["nodes"][0]["accessibilityFocused"] = True
    b["step"] = 1
    assert observe(registry,a).state_id == observe(registry,b).state_id
    assert registry.state_count == 1 and len(registry.states[0]["observation_ids"]) == 2


def test_scroll_retains_logical_state_and_adds_viewport():
    registry = StateRegistry()
    a, b, _, proof = scroll_pair()
    first = observe(registry,a)
    second = observe(registry,b,proof)
    assert second.status == "REUSED" and second.state_id == first.state_id
    assert registry.state_count == 1
    assert len(registry.states[0]["viewport_observations"]) == 2
    assert observe(registry,a).state_id == first.state_id


def test_scroll_evidence_can_compare_nonrepresentative_before_capture():
    registry = StateRegistry()
    a, b, _, proof = scroll_pair()
    earlier = deepcopy(a)
    earlier["timestamp"] = "2026-10-05T00:59:59+09:00"
    observe(registry,earlier)
    observe(registry,a)
    assert len(registry.states[0]["representative_observation_ids"]) == 1
    assert observe(registry,b,proof).status == "REUSED"


def test_roots_create_separate_states_and_home_reentry_reuses():
    registry = StateRegistry()
    ids = [observe(registry,observation(root)).state_id for root in ("home","devices","life")]
    assert len(set(ids)) == registry.state_count == 3
    assert observe(registry,observation()).state_id == ids[0]


def test_overlay_creates_interaction_state_and_records_base_relation():
    registry = StateRegistry()
    a,b = observation(),observation()
    b["overlay"] = {"kind":"dialog","observed":True,"nodes":[node("dialog","Permission")]}
    base = observe(registry,a)
    dialog = observe(registry,b)
    assert dialog.status == "CREATED" and dialog.state_id != base.state_id
    assert registry.states[1]["base_state_id"] == base.state_id
    assert observe(registry,a).state_id == base.state_id


@pytest.mark.parametrize("field", ["enabled","checked","selected"])
def test_meaningful_boolean_change_creates_distinct_state(field):
    registry = StateRegistry()
    a,b = observation(),observation()
    b["nodes"][0][field] = not a["nodes"][0][field]
    assert observe(registry,a).state_id != observe(registry,b).state_id
    assert registry.state_count == 2


@pytest.mark.parametrize("before,after", [("locked","unlocked"),("connected","disconnected")])
def test_semantic_change_creates_state_even_if_fingerprint_collides(before,after):
    registry = StateRegistry()
    a,b = observation(),observation()
    a["nodes"][0]["text"], b["nodes"][0]["text"] = before,after
    assert observe(registry,a).state_id != observe(registry,b).state_id
    assert registry.state_count == 2


def test_unknown_collision_does_not_merge_or_create_and_is_retained():
    registry = StateRegistry()
    a,b = observation(),observation()
    a["nodes"][0]["text"],b["nodes"][0]["text"] = "Settings subpage","Details subpage"
    first = observe(registry,a)
    unresolved = observe(registry,b)
    assert unresolved.status == "UNRESOLVED" and unresolved.state_id is None
    assert unresolved.candidate_state_ids == (first.state_id,)
    assert registry.state_count == registry.unresolved_count == 1
    assert len(registry.to_dict()["observations"]) == 2


def test_insufficient_first_observation_does_not_invent_state():
    registry = StateRegistry()
    result = observe(registry,observation(activity_name=None))
    assert result.status == "UNRESOLVED" and result.state_id is None
    assert registry.state_count == 0 and registry.observation_count == 1


def test_structural_ko_en_equivalent_reuses():
    registry = StateRegistry()
    a,b = observation(),observation()
    a["nodes"][0]["text"],a["nodes"][1]["text"] = "장치","홈"
    b["nodes"][0]["text"],b["nodes"][1]["text"] = "Device","Home"
    assert observe(registry,a).state_id == observe(registry,b).state_id


def test_typed_location_age_does_not_add_state_or_semantic_representative():
    registry=StateRegistry()
    a,b=observation(),observation()
    a["nodes"][0]=node("pkg:id/map_area","Device KOR003, 최근 위치 확인: 59분 전")
    b["nodes"][0]=node("pkg:id/map_area","Device KOR003, 최근 위치 확인: 1시간 전")
    assert observe(registry,a).state_id==observe(registry,b).state_id
    assert registry.state_count==1 and len(registry.states[0]["representative_observation_ids"])==1
    assert StateRegistry.from_dict(registry.to_dict()).to_json()==registry.to_json()


def test_save_load_roundtrip_and_restart_then_reuse(tmp_path):
    registry = StateRegistry()
    a,b,_,proof = scroll_pair()
    home = observe(registry,a)
    observe(registry,b,proof)
    observe(registry,observation("devices"))
    observe(registry,observation(activity_name=None))
    path = tmp_path/"state_registry.json"
    registry.save(path)
    before = path.read_bytes()
    restored = StateRegistry.load(path)
    assert restored.to_json() == registry.to_json()
    restored.save(path)
    assert path.read_bytes() == before
    assert observe(restored,a).state_id == home.state_id
    assert restored.state_count == 2 and restored.unresolved_count == 1


def test_deterministic_input_replay_and_export_is_independent():
    first,second = StateRegistry(),StateRegistry()
    for raw in (observation(),observation("devices"),observation(),observation("life")):
        observe(first,raw); observe(second,raw)
    assert first.to_json() == second.to_json()
    export = first.states
    export[0]["observation_ids"].clear()
    assert first.states[0]["observation_ids"]


@pytest.mark.parametrize("mutation", ["checksum","schema","counts","next_sequence","orphan","resolution","duplicate_observation","secondary"])
def test_corruption_fails_even_when_outer_checksum_recomputed(mutation):
    registry = StateRegistry()
    observe(registry,observation())
    value = registry.to_dict()
    if mutation == "checksum":
        value["content_sha256"] = "bad"
    elif mutation == "schema":
        value["schema_version"] = "future-registry"
    elif mutation == "counts":
        value["states"][0]["observation_count"] = 100
    elif mutation == "next_sequence":
        value["next_state_sequence"] = 999
    elif mutation == "orphan":
        value["events"][0]["observation_id"] = "missing"
    elif mutation == "resolution":
        value["events"][0]["result"]["state_id"] = "other-state"
    elif mutation == "duplicate_observation":
        value["observations"].append(deepcopy(value["observations"][0]))
    elif mutation == "secondary":
        value["observations"][0]["secondary"]["nodes"][0]["semantic"]["flags"]["enabled"] = "not-a-bool"
    if mutation != "checksum":
        reseal(value)
    with pytest.raises(ValueError):
        StateRegistry.from_dict(value)


def test_forward_envelope_fields_preserved_without_changing_resolution():
    registry = StateRegistry()
    observe(registry,observation())
    value = registry.to_dict()
    value["future_annotations"] = {"note":"not runtime control"}
    reseal(value)
    loaded = StateRegistry.from_dict(value)
    assert loaded.to_dict()["future_annotations"] == value["future_annotations"]
    assert loaded.state_count == 1


@pytest.mark.parametrize("text", ["{", "", "[]", '{"schema_version":1,"schema_version":2}'])
def test_invalid_json_load_fails_safely(tmp_path,text):
    path = tmp_path/"state_registry.json"
    path.write_text(text,encoding="utf-8")
    with pytest.raises(ValueError):
        StateRegistry.load(path)


def test_failed_atomic_replace_preserves_previous_file_and_cleans_temp(tmp_path,monkeypatch):
    from tb_runner import state_registry as module
    registry = StateRegistry()
    observe(registry,observation())
    path=tmp_path/"state_registry.json"
    registry.save(path)
    prior=path.read_bytes()
    observe(registry,observation("devices"))
    def fail(*args): raise OSError("simulated interrupted replacement")
    monkeypatch.setattr(module.os,"replace",fail)
    with pytest.raises(OSError): registry.save(path)
    assert path.read_bytes()==prior
    assert list(tmp_path.iterdir())==[path]


def test_orphan_continuity_rejected_before_any_registry_mutation():
    registry = StateRegistry()
    a,b,_,proof=scroll_pair()
    original=registry.to_json()
    with pytest.raises(ValueError): observe(registry,b,proof)
    assert registry.to_json()==original


def test_loaded_overlay_base_reference_and_proof_are_validated():
    registry = StateRegistry()
    a,b,_,proof=scroll_pair()
    observe(registry,a); observe(registry,b,proof)
    value=registry.to_dict()
    value["states"][0]["base_state_id"]="orphan"
    reseal(value)
    with pytest.raises(ValueError): StateRegistry.from_dict(value)
