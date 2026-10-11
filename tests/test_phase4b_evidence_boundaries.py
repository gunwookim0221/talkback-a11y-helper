from copy import deepcopy
import pytest
from state_model_fixtures import node
from tb_runner.phase4a_planner import production_instance
from tools.phase4b_controlled_monitor import controlled_target_evidence_failures


def evidence():
    target = dict(resource_id="id/a",bounds="0,100,500,200",class_name="android.widget.TextView")
    identity = production_instance(target,"generic")
    actual = node("id/a","A",accessibilityFocused=True)
    return dict(scenario="generic",planner_executed=True,actual_execution_mode="CONTROLLED_TARGET_FOCUS",
        target_binding=dict(eligible_match_count=1),fallback_used=False,planner_target=target,
        immediate_actual_focus=actual, actual_focus_after=deepcopy(actual),
        shadow_recommendation=dict(recommended_instance_id=identity),
        focus_preview=dict(focus_transition_status="CONFIRMED_MOVED",actual_focus_instance_id=identity),
        helper_result_correlated=True,helper_ack_result=dict(requestedTarget=dict(requireFocusable=True)),
        focus_reconciliation=dict(actual_focus_instance_id=identity))


def test_later_production_realignment_keeps_its_own_actual_focus_authority():
    row = evidence()
    final = node("id/b","B","0,220,500,320",accessibilityFocused=True)
    row["actual_focus_after"] = final
    row["focus_reconciliation"]["actual_focus_instance_id"] = production_instance(dict(resource_id="id/b",bounds="0,220,500,320"),"generic")
    assert controlled_target_evidence_failures(row) == []


@pytest.mark.parametrize("kind", ["wrong_immediate", "false_immediate_focus", "stale_request", "unconfirmed_move", "wrong_preview_identity", "unknown_predicate", "false_final_focus", "wrong_final_reconciliation"])
def test_boundary_separation_does_not_weaken_focus_or_request_proof(kind):
    row = deepcopy(evidence())
    if kind == "wrong_immediate": row["immediate_actual_focus"]["viewIdResourceName"] = "id/other"
    elif kind == "false_immediate_focus": row["immediate_actual_focus"]["accessibilityFocused"] = False
    elif kind == "stale_request": row["helper_result_correlated"] = False
    elif kind == "unconfirmed_move": row["focus_preview"]["focus_transition_status"] = "UNAVAILABLE"
    elif kind == "wrong_preview_identity": row["focus_preview"]["actual_focus_instance_id"] = "other"
    elif kind == "unknown_predicate": row["helper_ack_result"]["requestedTarget"]["requireFocusable"] = None
    elif kind == "false_final_focus": row["actual_focus_after"]["accessibilityFocused"] = False
    else: row["focus_reconciliation"]["actual_focus_instance_id"] = "other"
    assert controlled_target_evidence_failures(row)
