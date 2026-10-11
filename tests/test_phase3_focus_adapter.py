import copy

import pytest

from tb_runner.phase3_focus import normalize_phase3_focus_transition


def _node(rid="button", bounds="0,0,100,100", *, a11y=True, input_focus=False,
          label="Button", timestamp=1200):
    return {"timestamp": timestamp, "viewIdResourceName": rid,
            "boundsInScreen": bounds, "className": "android.widget.Button",
            "contentDescription": label, "talkbackLabel": label,
            "accessibilityFocused": a11y, "focused": input_focus}


def _raw(capture_id, node, *, scenario="life_food_plugin", run="run-1"):
    return {"capture_id": capture_id, "scenario_run_id": run, "scenario_id": scenario,
            "timestamp": "2026-10-11T08:00:02+00:00", "focus_node": copy.deepcopy(node)}


def _ack(after, *, success=True, request_id="req-1", started=1000, acked=1500):
    after = copy.deepcopy(after)
    events = [
        {"schemaVersion": "evidence-helper-v1", "eventType": "ACTION_EXECUTION_STARTED",
         "timestamp": started, "reqId": request_id,
         "payload": {"action": "com.iotpart.sqe.talkbackhelper.SMART_NEXT"}},
        {"schemaVersion": "evidence-helper-v1", "eventType": "TARGET_REQUESTED",
         "timestamp": started, "reqId": request_id,
         "payload": {"action": "com.iotpart.sqe.talkbackhelper.SMART_NEXT"}},
        {"schemaVersion": "evidence-helper-v1", "eventType": "TARGET_RESOLVED",
         "timestamp": after["timestamp"], "reqId": request_id,
         "payload": {"resolvedTarget": copy.deepcopy(after)}},
        {"schemaVersion": "evidence-helper-v1", "eventType": "POST_ACTION_OBSERVATION",
         "timestamp": after["timestamp"], "reqId": request_id,
         "payload": {"observation": copy.deepcopy(after)}},
        {"schemaVersion": "evidence-helper-v1", "eventType": "ACTION_API_RESULT",
         "timestamp": acked - 1, "reqId": request_id,
         "payload": {"success": success, "reason": "moved" if success else "failed"}},
        {"schemaVersion": "evidence-helper-v1", "eventType": "HELPER_ACK_SENT",
         "timestamp": acked, "reqId": request_id,
         "payload": {"status": "moved" if success else "failed"}},
    ]
    return {"success": success, "status": "moved" if success else "failed",
            "raw": {"reqId": request_id, "timestamp": acked, "evidenceEvents": events}}


def _observe(before_node, after_node, *, success=True, expected_request_id="req-1",
             before_capture="before", after_capture="after", run="run-1"):
    before = _raw(before_capture, before_node, run=run)
    snapshot_node = copy.deepcopy(after_node)
    snapshot_node["timestamp"] = max(int(snapshot_node.get("timestamp", 0)), 1600)
    after = _raw(after_capture, snapshot_node, run=run)
    ack = _ack(after_node, success=success)
    return normalize_phase3_focus_transition(before, after, ack,
        expected_request_id=expected_request_id, scenario_run_id=run)


def test_ack_success_and_actual_focus_move_confirms_observation_only():
    result = _observe(_node("a", timestamp=900), _node("b", timestamp=1300))
    assert result["status"] == "FOCUS_MOVE_CONFIRMED"
    assert result["actual_focus_moved"] is True
    assert result["visit_credit"] == 0


def test_ack_success_without_actual_focus_move_is_not_a_visit():
    result = _observe(_node("a", timestamp=900), _node("a", timestamp=1300))
    assert result["status"] == "ACK_SUCCESS_NO_FOCUS_MOVE"
    assert result["actual_focus_moved"] is False
    assert result["visit_credit"] == 0


def test_ack_failure_with_actual_focus_move_keeps_actual_observation():
    result = _observe(_node("a", timestamp=900), _node("b", timestamp=1300), success=False)
    assert result["status"] == "ACK_FAILURE_BUT_FOCUS_MOVED"
    assert result["actual_focus_moved"] is True
    assert result["visit_credit"] == 0


def test_ack_failure_without_actual_focus_move_reports_no_move():
    result = _observe(_node("a", timestamp=900), _node("a", timestamp=1300), success=False)
    assert result["status"] == "ACK_FAILURE_NO_FOCUS_MOVE"
    assert result["actual_focus_moved"] is False


def test_input_focus_fallback_never_becomes_actual_focus_or_visit():
    before = _node("a", a11y=False, input_focus=True, timestamp=900)
    after = _node("b", a11y=False, input_focus=True, timestamp=1300)
    result = _observe(before, after)
    assert result["status"] == "FALSE_FOCUS_FALLBACK"
    assert result["actual_focus_moved"] is None
    assert result["visit_credit"] == 0
    assert result["before_observation"]["actual_focus_accessibility_focused"] is False


def test_stale_before_after_snapshot_is_rejected():
    result = _observe(_node("a", timestamp=1400), _node("b", timestamp=1300))
    assert result["status"] == "STALE_OR_CONTRADICTORY_EVIDENCE"
    assert result["actual_focus_moved"] is None
    assert result["visit_credit"] == 0


def test_same_resource_id_at_different_bounds_is_a_distinct_focus_instance():
    result = _observe(_node("repeated", "0,0,100,100", timestamp=900),
                      _node("repeated", "0,120,100,220", timestamp=1300))
    assert result["status"] == "FOCUS_MOVE_CONFIRMED"
    assert result["before_instance_id"] != result["after_instance_id"]


def test_same_bounds_and_metadata_does_not_create_duplicate_visit():
    result = _observe(_node("repeated", "0,0,100,100", timestamp=900),
                      _node("repeated", "0,0,100,100", timestamp=1300))
    assert result["status"] == "ACK_SUCCESS_NO_FOCUS_MOVE"
    assert result["before_instance_id"] == result["after_instance_id"]


def test_request_id_mismatch_cannot_attribute_focus_movement():
    result = _observe(_node("a", timestamp=900), _node("b", timestamp=1300),
                      expected_request_id="stale-req")
    assert result["status"] == "STALE_OR_CONTRADICTORY_EVIDENCE"
    assert result["actual_focus_moved"] is None
    assert result["after_observation"]["actual_focus_accessibility_focused"] is False


def test_mixed_request_ids_in_helper_ledger_are_rejected():
    before = _raw("before", _node("a", timestamp=900))
    after = _raw("after", _node("b", timestamp=1300))
    ack = _ack(after["focus_node"])
    ack["raw"]["evidenceEvents"][2]["reqId"] = "previous-request"
    result = normalize_phase3_focus_transition(before, after, ack,
        expected_request_id="req-1", scenario_run_id="run-1")
    assert result["status"] == "STALE_OR_CONTRADICTORY_EVIDENCE"
    assert result["actual_focus_moved"] is None


@pytest.mark.parametrize("change", ["scenario", "run", "capture"])
def test_cross_scenario_or_reused_snapshots_are_rejected(change):
    before = _raw("before", _node("a", timestamp=900))
    after = _raw("after", _node("b", timestamp=1300))
    ack = _ack(after["focus_node"])
    if change == "scenario":
        after["scenario_id"] = "life_find_plugin"
    elif change == "run":
        after["scenario_run_id"] = "next-run"
    else:
        after["capture_id"] = before["capture_id"]
    result = normalize_phase3_focus_transition(before, after, ack,
        expected_request_id="req-1", scenario_run_id="run-1")
    assert result["status"] == "STALE_OR_CONTRADICTORY_EVIDENCE"
    assert result["actual_focus_moved"] is None
