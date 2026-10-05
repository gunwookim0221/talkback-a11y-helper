from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from state_model_fixtures import node, observation, scroll_pair
from tb_runner.canonical_json import canonical_json
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.state_registry import StateRegistry
from tb_runner.transition_observation import ControlledAction, TransitionObserver, write_transition


def action(kind="FOCUS_NEXT", occurrence="test:1", **values):
    return dict(occurrence_id=occurrence, action_kind=kind, producer="controlled-test", **values)


def focus_pair():
    a = observation()
    b = deepcopy(a)
    a["focus_node"] = deepcopy(a["nodes"][0])
    b["focus_node"] = deepcopy(b["nodes"][1])
    for raw in (a, b):
        raw["focus_node"]["accessibilityFocused"] = True
    return a, b


def observe(a=None, b=None, ack=None, controlled=None, evidence=None, registry=None):
    a = observation() if a is None else a
    b = deepcopy(a) if b is None else b
    observer = TransitionObserver(registry if registry is not None else StateRegistry("transition-test"))
    prepared = observer.prepare(a, controlled or action())
    result = observer.complete(prepared, b, command_ack=ack or {"success": True, "status": "moved"}, action_evidence=evidence)
    return observer, prepared, result


def test_same_inputs_deterministic_immutable_and_no_visit_credit(tmp_path):
    first = observe()[2]
    second = observe()[2]
    assert first.to_json() == second.to_json()
    assert first.to_dict()["visit_credit"] == 0
    assert first.to_dict()["action_executed_by_observer"] is False
    with pytest.raises(FrozenInstanceError):
        first.outcome = "BAD"
    copy = first.to_dict()
    copy["command_ack"]["raw"]["success"] = False
    assert first.to_json() == second.to_json()
    path = tmp_path / "state_transitions.jsonl"
    write_transition(path, first)
    write_transition(path, first)
    lines = path.read_bytes().splitlines()
    assert lines == [first.to_json().encode(), first.to_json().encode()]


def test_timestamps_ack_request_ids_and_reference_paths_are_diagnostic():
    a, b = focus_pair()
    first = observe(a, b, ack=dict(success=True, status="moved", requestId="old", timestamp="old"))[2]
    a["timestamp"] = b["timestamp"] = "2030-01-01T00:00:00Z"
    observer = TransitionObserver(StateRegistry("transition-test"))
    prepared = observer.prepare(a, action(), action_started_at="new")
    second = observer.complete(prepared, b, command_ack=dict(success=True, status="moved", requestId="new", timestamp="new"),
                               action_finished_at="new", evidence_refs={"before": "different/path"})
    assert first.semantic_hash == second.semantic_hash
    assert first.transition_id == second.transition_id
    assert first.to_json() != second.to_json()


@pytest.mark.parametrize("success", [True, False])
def test_actual_focus_movement_preserved_regardless_of_ack(success):
    a, b = focus_pair()
    _, _, result = observe(a, b, dict(success=success, status="moved" if success else "failed"))
    doc = result.to_dict()
    assert result.outcome == "FOCUS_ONLY"
    assert doc["source_state_id"] == doc["resulting_state_id"]
    assert doc["actual_focus_moved"] is True
    assert doc["viewport_changed"] is False
    assert doc["command_ack"]["normalized"]["status"] == ("SUCCESS" if success else "FAIL")
    assert doc["visit_credit"] == 0
    assert "physical_visit_confirmed" not in doc["focus"]
    assert "node" not in doc["focus"]["actual_observed_target"]


@pytest.mark.parametrize("status,success,outcome", [("moved", True, "SAME_STATE"), ("failed", False, "ACTION_FAILED"),
                                                      ("moved", False, "ACTION_FAILED"), ("error", True, "SAME_STATE")])
def test_ack_does_not_prove_ui_movement(status, success, outcome):
    a, _ = focus_pair()
    result = observe(a, a, dict(status=status, success=success))[2]
    assert result.outcome == outcome
    assert result.to_dict()["actual_focus_moved"] is False


@pytest.mark.parametrize("flag", ["input_only", "false_fallback", "conflicting_top", "ambiguous", "no_before"])
def test_focus_fallback_input_and_incoherent_flags_do_not_prove_movement(flag):
    a, b = focus_pair()
    if flag == "input_only":
        for raw in (a, b):
            raw["focus_node"].update(accessibilityFocused=False, focused=True)
    elif flag == "false_fallback":
        b["focus_node"].update(accessibilityFocused=False, focused=False)
    elif flag == "conflicting_top":
        b["actual_focus_accessibility_focused"] = False
    elif flag == "ambiguous":
        b["focus_transition_status"] = "ambiguous"
    else:
        a["focus_node"] = {}
    result = observe(a, b)[2]
    assert result.outcome == "SAME_STATE"
    assert result.to_dict()["actual_focus_moved"] is None
    assert result.to_dict()["visit_credit"] == 0


def test_input_focus_only_does_not_change_semantic_hash():
    a = observation()
    b = deepcopy(a)
    a["focus_node"] = node(accessibilityFocused=False, focused=False)
    b["focus_node"] = node(accessibilityFocused=False, focused=True)
    assert observe(a, a)[2].semantic_hash == observe(a, b)[2].semantic_hash


def test_scroll_reuses_verified_continuity_and_retains_scope():
    a, b, evidence, _ = scroll_pair()
    controlled = action("SCROLL_FORWARD_VERTICAL", target_identity={"bounds": a["capability"]["container"]["boundsInScreen"]})
    observer, _, result = observe(a, b, controlled=controlled, evidence={"scroll_transition": evidence})
    doc = result.to_dict()
    assert result.outcome == "VIEWPORT_CHANGED"
    assert doc["source_state_id"] == doc["resulting_state_id"]
    assert doc["viewport_changed"] is True
    assert doc["action_binding"]["status"] == "MAPPED"
    assert doc["evidence"]["scroll_continuity"]["kind"] == "VERIFIED_SCROLL"
    assert observer.metrics()["UNSAFE_TRANSITION_BIND_COUNT"] == 0


@pytest.mark.parametrize("invalid", ["ack_only", "wrong_viewport", "wrong_axis", "contradictory"])
def test_scroll_invalid_proof_cannot_merge_state(invalid):
    a, b, evidence, _ = scroll_pair()
    evidence = deepcopy(evidence)  # Producer transition shares raw viewport dictionaries.
    if invalid == "ack_only":
        evidence = dict(status="SCROLL_MOVED", action_success=True)
    elif invalid == "wrong_viewport":
        evidence["after"]["signature"] = "wrong"
    elif invalid == "wrong_axis":
        evidence["capability_before"]["axis"] = "HORIZONTAL"
    else:
        evidence["capability_before"]["contradictory"] = True
    result = observe(a, b, evidence={"scroll_transition": evidence})[2]
    assert result.outcome == "AMBIGUOUS_RESULT"
    assert result.to_dict()["resulting_state_id"] is None
    assert result.to_dict()["evidence"]["scroll_continuity_rejected"]


def nav_raw(root):
    from tb_runner.scenario_config import BOTTOM_TAB_GLOBAL_NAV
    raw = observation(root)
    names = ("home", "devices", "life", "routines", "menu")
    raw["nodes"] = [node(), *[node(rid, label, f"{i*200},900,{i*200+200},1000", role="tab", selected=name == root)
        for i, (name, label, rid) in enumerate(zip(names, BOTTOM_TAB_GLOBAL_NAV["labels"], BOTTOM_TAB_GLOBAL_NAV["resource_ids"]))]]
    return raw


@pytest.mark.parametrize("success", [True, False])
def test_root_navigation_actual_state_independent_of_ack(success):
    result = observe(nav_raw("home"), nav_raw("devices"), dict(success=success, status="moved" if success else "failed"),
                     action("BOTTOM_NAV", target_identity={"destination": "devices"}),
                     {"global_navigation": {"selected_before": "home", "selected_after": "devices"}})[2]
    doc = result.to_dict()
    assert result.outcome == "STATE_CHANGED"
    assert doc["source_state_id"] != doc["resulting_state_id"]
    assert doc["action_binding"]["status"] == "MAPPED"
    assert doc["evidence"]["producer"]["global_navigation"]["selected_after"] == "devices"


@pytest.mark.parametrize("mutation", ["enabled", "checked", "semantic", "overlay"])
def test_phase2_semantic_changes_still_create_distinct_state(mutation):
    a = observation()
    b = deepcopy(a)
    if mutation in {"enabled", "checked"}:
        b["nodes"][0][mutation] = not b["nodes"][0][mutation]
    elif mutation == "semantic":
        a["nodes"][0]["text"] = "Locked"
        b["nodes"][0]["text"] = "Unlocked"
    else:
        b["overlay"] = dict(kind="dialog", observed=True, nodes=[node("dialog", "Permission")])
    result = observe(a, b)[2]
    assert result.outcome == "STATE_CHANGED"
    assert result.to_dict()["equality_relation"]["verdict"] == "DIFFERENT"


@pytest.mark.parametrize("side", ["source", "result", "both"])
def test_unresolved_source_result_never_bind_definitively(side):
    a, b = observation(), observation()
    for raw in ([a] if side == "source" else [b] if side == "result" else [a, b]):
        raw["activity_name"] = None
    observer, _, result = observe(a, b)
    doc = result.to_dict()
    assert result.outcome == "AMBIGUOUS_RESULT"
    assert doc["definitive_state_binding"] is False
    if side != "result":
        assert doc["source_state_id"] is None and doc["action_candidate_id"] is None
    if side != "source":
        assert doc["resulting_state_id"] is None
    assert observer.metrics()["UNSAFE_TRANSITION_BIND_COUNT"] == 0


def test_requested_candidate_and_actual_target_mismatch_preserved():
    a, b = focus_pair()
    observer, prepared, result = observe(a, b, controlled=action("FOCUS_TARGET", target_identity=a["nodes"][0]))
    doc = result.to_dict()
    assert doc["action_binding"]["status"] == "MAPPED"
    assert doc["requested_target_matches_actual_focus"] is False
    assert doc["target_identity"]["resource_id"] != doc["focus"]["actual_observed_target"]["view_id"]
    assert doc["action_candidate_id"] in {c.candidate_id for c in prepared.source_snapshot.candidates}
    assert observer.metrics()["MAPPED_ACTION_TRANSITIONS"] == 1


@pytest.mark.parametrize("kind,target", [("BACK", {}), ("PLUGIN_NAVIGATION", {}), ("CLICK", {}),
                                         ("FOCUS_NEXT", {"resource_id": "not-an-untargeted-next"}),
                                         ("BOTTOM_NAV", {"destination": "missing"})])
def test_unmapped_controlled_action_is_explicit(kind, target):
    result = observe(controlled=action(kind, target_identity=target))[2]
    assert result.to_dict()["action_binding"]["status"] == "UNMAPPED_CONTROLLED_ACTION"
    assert result.to_dict()["action_candidate_id"] is None


def test_foreign_candidate_id_not_rewritten_to_available_candidate():
    result = observe(controlled=action(requested_candidate_id="discovery:foreign"))[2]
    assert result.to_dict()["action_candidate_id"] is None
    assert result.to_dict()["controlled_action"]["requested_candidate_id"] == "discovery:foreign"


def test_collision_targets_require_exact_instance_not_resource_id_only():
    raw = observation()
    raw["nodes"].append(node(bounds="500,100,1000,200"))
    result = observe(raw, controlled=action("CLICK", target_identity={"resource_id": "pkg:id/card"}))[2]
    # An incomplete identity cannot distinguish same-resource instances.
    assert result.to_dict()["action_candidate_id"] is None
    target = raw["nodes"][-1]
    result = observe(raw, controlled=action("CLICK", target_identity=target))[2]
    assert result.to_dict()["target_identity"]["bounds"] == "500,100,1000,200"
    assert result.to_dict()["action_binding"]["status"] == "MAPPED"


def test_executed_target_contradiction_does_not_rewrite_history():
    a = observation()
    result = observe(a, controlled=action("CLICK", target_identity=a["nodes"][0]),
                     evidence={"executed_target_identity": a["nodes"][1]})[2]
    doc = result.to_dict()
    assert doc["action_candidate_id"] is None
    assert doc["controlled_action"]["target_identity"]["resource_id"] == "pkg:id/card"
    assert doc["evidence"]["producer"]["executed_target_identity"]["viewIdResourceName"] != "pkg:id/card"


def test_missing_post_observation_is_error_not_success():
    observer = TransitionObserver(StateRegistry("transition-test"))
    result = observer.complete(observer.prepare(observation(), action()), None, command_ack={"success": True},
                               action_evidence={"error": "transport lost"})
    assert result.outcome == "ERROR"
    assert result.to_dict()["resulting_state_id"] is None
    assert result.to_dict()["definitive_state_binding"] is False


def test_foreign_or_forged_prepared_source_rejected():
    observer, prepared, _ = observe()
    other = TransitionObserver(StateRegistry("other"))
    for forged in (prepared, replace(prepared, source_snapshot=build_discovery_snapshot(observation("devices"), other.registry))):
        with pytest.raises(ValueError, match="foreign or forged"):
            other.complete(forged, observation())


def test_inconsistent_registry_result_is_quarantined(monkeypatch):
    observer, prepared, _ = observe()
    resolution = observer.registry.observe(prepared.source_observation)
    monkeypatch.setattr(observer.registry, "observe", lambda *args, **kwargs: resolution)
    next_source = observer.prepare(observation(), action(occurrence="mismatch:1"))
    result = observer.complete(next_source, observation("devices"), command_ack={"success": True})
    doc = result.to_dict()
    assert doc["outcome"] == "AMBIGUOUS_RESULT"
    assert doc["resulting_state_id"] is None
    assert doc["definitive_state_binding"] is False
    assert observer.metrics()["STATE_BINDING_MISMATCH_COUNT"] == 1
    assert observer.metrics()["UNSAFE_TRANSITION_BIND_COUNT"] == 0


def test_identical_occurrence_replay_does_not_double_count():
    observer, prepared, first = observe()
    second = observer.complete(prepared, observation(), command_ack={"success": True, "status": "moved"})
    assert first.transition_id == second.transition_id
    assert observer.metrics()["TOTAL_TRANSITIONS_OBSERVED"] == 1


def test_conflicting_occurrence_is_rejected_and_counted():
    observer, prepared, _ = observe()
    with pytest.raises(ValueError, match="unexpected transition churn"):
        observer.complete(prepared, observation("devices"), command_ack={"success": True, "status": "moved"})
    assert observer.metrics()["UNEXPECTED_TRANSITION_CHURN_COUNT"] == 1
    assert observer.metrics()["TOTAL_TRANSITIONS_OBSERVED"] == 1


def test_actual_hash_collision_rejected(monkeypatch):
    import tb_runner.transition_observation as module
    observer, _, _ = observe()
    existing_hash = next(iter(observer._identities)).split(":", 1)[1]
    monkeypatch.setattr(module, "canonical_sha256", lambda _: existing_hash)
    prepared = observer.prepare(observation(), action(occurrence="test:2"))
    with pytest.raises(ValueError, match="transition ID collision"):
        observer.complete(prepared, observation("devices"))
    assert observer.metrics()["TRANSITION_ID_COLLISION_COUNT"] == 1


def test_real_occurrences_distinct_but_repeated_type_stable():
    a, b = focus_pair()
    first = observe(a, b)[2]
    second = observe(a, b, controlled=action(occurrence="test:2"))[2]
    assert first.transition_id != second.transition_id
    assert first.semantic_hash == second.semantic_hash
    assert first.to_dict()["transition_type_hash"] == second.to_dict()["transition_type_hash"]


def test_replay_order_stable_with_persisted_registry(tmp_path):
    registry = StateRegistry("transition-test")
    for root in ("home", "devices", "life"):
        build_discovery_snapshot(nav_raw(root), registry)
    path = tmp_path / "registry.json"
    registry.save(path)
    pairs = [(nav_raw("home"), nav_raw("devices"), action("BOTTOM_NAV", "nav:1", target_identity={"destination": "devices"})),
             (nav_raw("devices"), nav_raw("life"), action("BOTTOM_NAV", "nav:2", target_identity={"destination": "life"}))]
    sets = []
    for values in (pairs, list(reversed(pairs))):
        observer = TransitionObserver(StateRegistry.load(path))
        records = {}
        for a, b, controlled in values:
            record = observer.complete(observer.prepare(a, controlled), b, command_ack={"success": True})
            records[controlled["occurrence_id"]] = record.to_json()
        sets.append(records)
    # Registry event sequence is diagnostic; IDs and semantic representations
    # remain stable across order with the same saved allocation namespace.
    for occurrence in sets[0]:
        left, right = (json.loads(records[occurrence]) for records in sets)
        assert left["transition_id"] == right["transition_id"]
        assert left["semantic_identity"] == right["semantic_identity"]


@pytest.mark.parametrize("bad", [{}, {"occurrence_id": "", "producer": "x", "action_kind": "FOCUS_NEXT"},
                                  {"occurrence_id": "a", "producer": "x", "action_kind": "AUTO_CHOOSE"}])
def test_invalid_actions_rejected(bad):
    with pytest.raises(ValueError):
        ControlledAction.from_dict(bad)


def test_diagnostic_input_not_mutated_and_has_no_runtime_client():
    a, b = focus_pair()
    controlled = action()
    evidence = {"raw_producer": {"a": [1, 2]}}
    original = canonical_json([a, b, controlled, evidence])
    observe(a, b, controlled=controlled, evidence=evidence)
    assert canonical_json([a, b, controlled, evidence]) == original
