from copy import deepcopy
import json

import pytest

from state_model_fixtures import node, observation
from tb_runner.canonical_json import canonical_sha256
from tb_runner.state_registry import StateRegistry
from tb_runner.state_observation import build_state_observation
from tb_runner.transition_observation import TransitionObserver
from tools.phase3c_transition_closure import audit_transitions, make_case, write_report


def _pair():
    before, after = observation(), observation()
    before["focus_node"] = deepcopy(before["nodes"][0])
    after["focus_node"] = deepcopy(after["nodes"][1])
    before["focus_node"]["accessibilityFocused"] = True
    after["focus_node"]["accessibilityFocused"] = True
    return before, after


def _case(before=None, after=None, *, occurrence="closure:1", kind="FOCUS_NEXT", ack=None):
    before, after = _pair() if before is None else (before, after)
    observer = TransitionObserver(StateRegistry("phase3c-test"))
    action = dict(occurrence_id=occurrence, producer="controlled-phase3c-test", action_kind=kind,
                  target_identity={} if kind == "FOCUS_NEXT" else {"destination": "devices"})
    prepared = observer.prepare(before, action)
    result = observer.complete(prepared, after,
        command_ack=ack or {"success": True, "status": "moved"})
    return make_case(result.to_dict(), prepared.source_snapshot.to_dict(),
                     result.resulting_snapshot.to_dict(), prepared.source_observation,
                     result.resulting_snapshot and build_state_observation(after),
                     before_raw=before)


def _rehash(transition):
    semantic = transition["semantic_identity"]
    transition["semantic_hash"] = canonical_sha256(semantic)
    transition["transition_id"] = "transition:" + canonical_sha256(
        dict(occurrence_id=transition["occurrence_id"], semantic=semantic))


def test_real_transition_cross_layer_contract_has_zero_contradictions():
    result = audit_transitions([_case()])
    assert result["status"] == "PASS"
    assert result["metrics"]["CROSS_LAYER_CONTRADICTION_COUNT"] == 0
    assert result["metrics"]["STABLE_TRANSITIONS"] == 1


def test_source_snapshot_mismatch_detected():
    case = _case();case["source_snapshot"]["state_id"] = "wrong-state"
    assert audit_transitions([case])["metrics"]["SOURCE_STATE_SNAPSHOT_MISMATCH_COUNT"] == 1


def test_source_observation_must_match_snapshot_fingerprint():
    case = _case();case["source_observation"]["fingerprint"]["fingerprint_hash"] = "wrong"
    assert audit_transitions([case])["metrics"]["SOURCE_STATE_SNAPSHOT_MISMATCH_COUNT"] == 1


def test_mapped_candidate_must_exist_in_source_snapshot():
    case = _case();case["transition"]["action_candidate_id"] = "discovery:missing"
    case["transition"]["action_binding"]["candidate_id"] = "discovery:missing"
    case["transition"]["semantic_identity"]["action_candidate_id"] = "discovery:missing"
    _rehash(case["transition"])
    assert audit_transitions([case])["metrics"]["ACTION_NOT_IN_SOURCE_SNAPSHOT_COUNT"] == 1


def test_mapped_candidate_kind_must_match_controlled_action():
    case = _case()
    mapped_id = case["transition"]["action_candidate_id"]
    candidate = next(c for c in case["source_snapshot"]["candidates"] if c["candidate_id"] == mapped_id)
    candidate["action_kind"] = "CLICK"
    assert audit_transitions([case])["metrics"]["ACTION_NOT_IN_SOURCE_SNAPSHOT_COUNT"] == 1


def test_result_fingerprint_reference_mismatch_detected():
    case = _case();case["transition"]["resulting_fingerprint"]["fingerprint_hash"] = "wrong"
    assert audit_transitions([case])["metrics"]["RESULT_STATE_FINGERPRINT_MISMATCH_COUNT"] == 1


def test_result_fingerprint_state_must_match_result_snapshot():
    case = _case();case["transition"]["resulting_fingerprint"]["state_id"] = "wrong-state"
    assert audit_transitions([case])["metrics"]["RESULT_STATE_FINGERPRINT_MISMATCH_COUNT"] == 1


def test_outcome_must_agree_with_phase2_equality():
    case = _case();case["transition"]["outcome"] = "STATE_CHANGED"
    case["transition"]["semantic_identity"]["outcome"] = "STATE_CHANGED";_rehash(case["transition"])
    assert audit_transitions([case])["metrics"]["OUTCOME_STATE_EQUALITY_MISMATCH_COUNT"] == 1


def test_viewport_result_must_agree_with_equality():
    case = _case();case["transition"]["viewport_changed"] = True
    assert audit_transitions([case])["metrics"]["VIEWPORT_OUTCOME_MISMATCH_COUNT"] == 1


def test_focus_result_must_agree_with_strict_focus_evidence():
    case = _case();case["transition"]["focus"]["actual_focus_moved"] = False
    assert audit_transitions([case])["metrics"]["FOCUS_OUTCOME_MISMATCH_COUNT"] == 1


def test_ack_fail_without_observed_change_requires_failure_outcome():
    before, after = observation(), observation()
    case = _case(before, after, ack={"success": False, "status": "failed"})
    t = case["transition"];t["outcome"] = "SAME_STATE";t["semantic_identity"]["outcome"] = "SAME_STATE";_rehash(t)
    assert audit_transitions([case])["metrics"]["ACK_RECONCILIATION_MISMATCH_COUNT"] == 1


def test_ack_failure_with_actual_move_is_reconciled_not_flagged():
    before, after = _pair()
    result = audit_transitions([_case(before, after, ack={"success": False, "status": "failed"})])
    assert result["metrics"]["ACK_RECONCILIATION_MISMATCH_COUNT"] == 0


def test_transition_hash_replay_mismatch_detected():
    case = _case();case["transition"]["semantic_hash"] = "wrong"
    assert audit_transitions([case])["metrics"]["TRANSITION_HASH_REPLAY_MISMATCH_COUNT"] == 1


def test_result_state_collision_and_snapshot_link_mismatch_detected():
    before, after = observation(), observation("devices")
    case = _case(before, after, kind="BOTTOM_NAV")
    case["result_snapshot"]["state_id"] = case["source_snapshot"]["state_id"]
    metrics = audit_transitions([case])["metrics"]
    assert metrics["STATE_COLLISION_COUNT"] == 1
    assert metrics["RESULT_STATE_FINGERPRINT_MISMATCH_COUNT"] == 1


def test_candidate_id_assigned_to_different_targets_is_collision():
    a = _case(occurrence="candidate:1");b = deepcopy(a)
    b["transition"]["occurrence_id"] = "candidate:2"
    b["source_snapshot"]["candidates"][0]["target_identity"]["bounds"] = "900,900,1000,1000"
    metrics = audit_transitions([a,b])["metrics"]
    assert metrics["CANDIDATE_ID_COLLISION_COUNT"] >= 1


def test_same_transition_id_for_different_semantics_is_collision():
    a = _case(occurrence="collision:1");b = _case(occurrence="collision:2")
    b["transition"]["transition_id"] = a["transition"]["transition_id"]
    assert audit_transitions([a,b])["metrics"]["TRANSITION_ID_COLLISION_COUNT"] == 1


def test_same_occurrence_split_into_different_ids_is_detected():
    a = _case(occurrence="split:1");b = deepcopy(a)
    b["transition"]["semantic_identity"]["command_ack"]["result"] = "other"
    _rehash(b["transition"])
    assert audit_transitions([a,b])["metrics"]["UNEXPECTED_TRANSITION_SPLIT_COUNT"] == 1


def test_ambiguous_source_and_result_remain_safe_and_unbound():
    before, after = observation(activity_name=None), observation(activity_name=None)
    case = _case(before, after, occurrence="unknown:1")
    metrics = audit_transitions([case])["metrics"]
    assert metrics["AMBIGUOUS_BUT_SAFE_COUNT"] == 1
    assert metrics["UNSAFE_STATE_BIND_COUNT"] == 0
    assert metrics["UNSAFE_TRANSITION_BIND_COUNT"] == 0
    assert metrics["ACTION_NOT_IN_SOURCE_SNAPSHOT_COUNT"] == 0


def test_plugin_context_mismatch_remains_unbound_and_safe():
    before, after = observation(), observation()
    after["activity_name"] = "com.example.vibration.VibrationPluginActivity"
    case = _case(before, after, occurrence="plugin:mismatch", kind="CLICK")
    transition = case["transition"]
    transition["resulting_state_id"] = None
    transition["resulting_fingerprint"]["state_id"] = None
    transition["resulting_fingerprint"]["state_resolution"] = {"status": "UNRESOLVED"}
    transition["definitive_state_binding"] = False
    transition["outcome"] = "AMBIGUOUS_RESULT"
    transition["evidence"]["plugin_context_verification"] = {
        "ok": False, "requested_plugin": "humidity", "observed_plugin": "vibration"}
    transition["semantic_identity"].update(resulting_state_id=None, outcome="AMBIGUOUS_RESULT")
    case["result_snapshot"]["state_id"] = None
    case["result_snapshot"]["state_resolution"] = {"status": "UNRESOLVED"}
    _rehash(transition)
    metrics = audit_transitions([case])["metrics"]
    assert metrics["AMBIGUOUS_BUT_SAFE_COUNT"] == 1
    assert metrics["UNSAFE_STATE_BIND_COUNT"] == 0
    assert metrics["UNSAFE_TRANSITION_BIND_COUNT"] == 0


def test_duplicate_occurrence_keeps_prior_cross_layer_fault():
    faulty = _case(occurrence="duplicate:1")
    faulty["source_snapshot"]["state_id"] = "wrong-state"
    clean = _case(occurrence="duplicate:1")
    assert audit_transitions([faulty, clean])["metrics"]["CROSS_LAYER_CONTRADICTION_COUNT"] == 1


def test_process_restart_replay_preserves_transition_identity(tmp_path):
    before, after = _pair()
    action = dict(occurrence_id="restart:1", producer="controlled-phase3c-restart",
                  action_kind="FOCUS_NEXT", target_identity={})
    ack = {"success": True, "status": "moved"}
    first_registry = StateRegistry("phase3c-process-restart")
    first_observer = TransitionObserver(first_registry)
    first_prepared = first_observer.prepare(before, action)
    first = first_observer.complete(first_prepared, after, command_ack=ack)
    saved_registry = tmp_path / "registry.json"
    first_registry.save(saved_registry)

    restarted_registry = StateRegistry.load(saved_registry)
    restarted_observer = TransitionObserver(restarted_registry)
    restarted_prepared = restarted_observer.prepare(before, action)
    restarted = restarted_observer.complete(restarted_prepared, after, command_ack=ack)
    assert restarted.transition_id == first.transition_id
    assert restarted.to_dict()["transition_type_hash"] == first.to_dict()["transition_type_hash"]


def test_incompatible_schema_is_reported_and_not_reinterpreted():
    case = _case();case["transition"]["schema_version"] = "future-v9"
    result = audit_transitions([case])
    assert result["metrics"]["INCOMPATIBLE_SCHEMA_COUNT"] == 1
    assert result["status"] == "FAIL"


def test_focus_variability_is_classified_from_observed_proof():
    a = _case(*_pair(), occurrence="focus:1")
    before, after = _pair();before["focus_node"]["accessibilityFocused"] = False
    b = _case(before, after, occurrence="focus:2")
    # Preserve the real no-proof input: the second movement is not claimed.
    b["transition"]["actual_focus_moved"] = None;b["transition"]["focus"]["actual_focus_moved"] = None
    b["transition"]["focus"]["status"] = "UNAVAILABLE"
    b["transition"]["outcome"] = "SAME_STATE"
    b["transition"]["semantic_identity"].update(actual_focus_moved=None,focus_status="UNAVAILABLE",outcome="SAME_STATE")
    _rehash(b["transition"])
    result = audit_transitions([a,b])
    assert result["metrics"]["EXPECTED_VARIABILITY_COUNT"] == 2
    assert result["metrics"]["UNEXPECTED_TRANSITION_CHURN_COUNT"] == 0


def test_report_json_is_parseable_deterministic_and_safe_to_overwrite(tmp_path):
    result = audit_transitions([_case()]);path=tmp_path/"phase3c.json"
    write_report(path,result);first=path.read_bytes();write_report(path,result)
    assert path.read_bytes() == first
    assert json.loads(first)["metrics"]["TOTAL_REPLAY_CASES"] == 1
