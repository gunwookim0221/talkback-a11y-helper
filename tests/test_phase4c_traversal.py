from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import json
from pathlib import Path

import pytest

from test_phase4b_authority import value, gate
from tb_runner.phase4a_planner import plan_shadow
from tb_runner.phase4b_authority import ExecutionBudget
from tb_runner.phase4c_traversal import TraversalSession, BUDGETS, SCENARIOS, WINDOW, inventory
from tb_runner.traversal_reliability import focus_instance, instance_id
from tb_runner.phase4b_execution import focus_row
from tb_runner.phase4b_execution import scroll_request_audit
from tools import phase4b_controlled_smoke as harness


def audit(v, raw, step=1, **overrides):
    chosen=plan_shadow(v).to_dict()
    actual=focus_instance(focus_row(raw["focus_node"], "synthetic"))
    return dict(step=step, shadow_recommendation=chosen, focus_reconciliation={"actual_focus_instance_id":instance_id(actual)},
        actual_focus_after=raw["focus_node"], actual_focus_before=raw["focus_node"], visit_credit=0,
        focus_transition_status="CONFIRMED_UNCHANGED", planner_action=chosen["recommended_action"], planner_executed=False,
        planner_failed=False, fallback_used=True, fallback_reason="NO_SAFE_PLANNER_ACTION", scroll_result=None,
        execution_gate_result={"allowed":False}, **overrides)


def exhausted_value():
    v,raw=value(only_current=True)
    current=plan_shadow(v).to_dict()["ranking"][0]["instance_id"]
    v=replace(v,history=replace(v.history,attempts=((current,1),),visits=((current,1),)))
    raw["capability"]={"can_scroll_forward":False,"contradictory":False}
    return v,raw


def test_budget_defaults_unchanged_and_generalized_explicit():
    v,_=value()
    assert not gate(v,actions_used=5).allowed
    assert gate(v,actions_used=5,action_limit=10).allowed
    assert not gate(v,actions_used=10,action_limit=10).allowed
    assert not gate(v,action_limit=100).allowed
    budget=ExecutionBudget(max_actions=10)
    for i in range(10):
        budget.reserve("CONTROLLED_TARGET_FOCUS",str(i),"viewport","state")
    with pytest.raises(RuntimeError): budget.reserve("CONTROLLED_TARGET_FOCUS","x","viewport","state")
    with pytest.raises(ValueError): ExecutionBudget(max_actions=100)


def test_exact_stage_order_budgets_and_production_default_off():
    assert len(SCENARIOS)==11 and sum(BUDGETS.values())==130
    assert SCENARIOS[:3]==("home_main","devices_main","life_main")
    assert SCENARIOS[-1]=="device_camera_plugin"
    root=Path(__file__).resolve().parents[1]
    for name in ("script_test.py","tb_runner/collection_flow.py","config/runtime_config.json"):
        assert "phase4c" not in (root/name).read_text(encoding="utf-8").lower()


def test_no_progress_requires_window_and_exhaustion():
    v,raw=exhausted_value(); session=TraversalSession("synthetic",10); b=ExecutionBudget(10)
    v=session.prepare(raw,v)
    for step in range(1,6):
        row=audit(v,raw,step)
        session.observe(row,raw,v,raw,v,b)
        assert row["no_progress_proven"] is (step>=5) # initial inventory discovery is progress
    assert row["saturation_signal"]=="PLANNER_CONTENT_SATURATED_SHADOW"
    assert session.protect_stop(True,"repeat_no_progress",v)==(True,"repeat_no_progress")


@pytest.mark.parametrize("condition",["scroll","unknown_scroll","candidate","ambiguous","pending"])
def test_plateau_cannot_end_with_unresolved_opportunity(condition):
    v,raw=exhausted_value()
    if condition=="scroll": raw["capability"]["can_scroll_forward"]=True
    if condition=="unknown_scroll": raw["capability"]["can_scroll_forward"]=None
    if condition=="candidate": v,raw=value()
    if condition=="pending": v=replace(v,pending_transition=True)
    session=TraversalSession("synthetic",10); v=session.prepare(raw,v)
    for i in range(6):
        row=audit(v,raw,i+1)
        if condition=="ambiguous": row["focus_transition_status"]="AMBIGUOUS"
        session.observe(row,raw,v,raw,v,ExecutionBudget(10))
    assert not row["no_progress_proven"]
    assert session.protect_stop(True,"repeat_no_progress",v)==(False,"")


def test_errors_and_production_completions_never_reclassified():
    v,raw=value(); session=TraversalSession("synthetic",10)
    for reason in ("content_error","talkback_restart","scroll_exhausted","confirmed_local_tab_exhaustion"):
        assert session.protect_stop(True,reason,v)==(True,reason)


def test_scroll_exhaustion_needs_two_unchanged_results_or_confirmed_end():
    v,raw=value(); raw["capability"]={"can_scroll_forward":True,"contradictory":False}
    session=TraversalSession("synthetic",10)
    row=audit(v,raw); row.update(scroll_result="SCROLL_NO_MOVEMENT",scroll_transition={"viewport_end":False})
    session.observe(row,raw,v,raw,v,ExecutionBudget(10))
    assert not session.prepare(raw,v).scroll_exhausted
    session.observe(row,raw,v,raw,v,ExecutionBudget(10))
    assert session.prepare(raw,v).scroll_exhausted
    changed=deepcopy(raw); changed["viewport"]={"stable_signature":"new-viewport"}
    assert not session.prepare(changed,v).scroll_exhausted
    fresh=TraversalSession("synthetic",10); row["scroll_transition"]["viewport_end"]=True
    fresh.observe(row,raw,v,raw,v,ExecutionBudget(10))
    assert fresh.prepare(raw,v).scroll_exhausted


def test_scroll_move_refresh_exposes_candidates_and_blocks_saturation():
    v,raw=exhausted_value(); after,after_raw=value()
    s=TraversalSession("synthetic",10); row=audit(v,raw)
    row["scroll_result"]="SCROLL_MOVED"
    s.observe(row,raw,v,after_raw,after,ExecutionBudget(10))
    assert row["scroll_state"]=="SCROLL_MOVED" and row["new_candidate_discovered"]==2
    assert row["useful_candidate_remains"] and not row["no_progress_proven"]


def test_starvation_reports_only_actual_priority_violation():
    v,raw=value(); s=TraversalSession("synthetic",10); row=audit(v,raw)
    row["planner_executed"]=True
    s.observe(row,raw,v,raw,v,ExecutionBudget(10))
    assert not row["starvation_signal"]
    row["shadow_recommendation"]["recommended_instance_id"]="unrelated-target"
    s.observe(row,raw,v,raw,v,ExecutionBudget(10))
    assert row["starvation_signal"]=="STARVATION_PRIORITY_VIOLATION"


def test_no_visit_authority_and_bounded_degraded_recovery():
    v,raw=value(); s=TraversalSession("synthetic",10); row=audit(v,raw); b=ExecutionBudget(10)
    b.degraded=True
    s.observe(row,raw,v,raw,v,b)
    assert not b.degraded # initial freshly discovered candidates
    b.degraded=True
    s.observe(row,raw,v,raw,v,b)
    assert b.degraded and not s.seen_visits
    row["visit_credit"]=1; row["focus_transition_status"]="CONFIRMED_MOVED"
    s.observe(row,raw,v,raw,v,b)
    assert not b.degraded and row["new_visit_created"]
    row["visit_credit"]=0
    s.observe(row,raw,v,raw,v,b)
    assert not row["new_visit_created"]


def test_generalized_optin_required_before_device(monkeypatch):
    monkeypatch.delenv("TB_PHASE4C_CONTROLLED",raising=False)
    monkeypatch.setattr(harness,"A11yAdbClient",lambda **kw:pytest.fail("must remain off"))
    with pytest.raises(ValueError): harness.main(generalized=True)


@pytest.mark.parametrize("failure", [False, True])
def test_generalized_harness_runs_refresh_and_restores_hooks(tmp_path, monkeypatch, failure):
    v, raw = value()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"scenarios": {"home_main": {"max_steps":10}}}))
    for key, val in {"TB_PHASE4C_CONTROLLED":"1", "TB_PHASE4C_SMOKE_SCENARIO":"home_main",
            "TB_PHASE4C_SMOKE_OUT":str(tmp_path), "TB_RUNTIME_CONFIG_PATH":str(config)}.items():
        monkeypatch.setenv(key, val)
    monkeypatch.setattr(harness,"A11yAdbClient",lambda **kw:object())
    monkeypatch.setattr(harness,"capture_observation",lambda *a,**kw:deepcopy(raw))
    monkeypatch.setattr(harness,"phase3_entry_evidence_from_main_loop",lambda *a:{})
    client=SimpleNamespace(collect_focus_step=lambda **kw:None,check_helper_status=lambda **kw:True)
    state=SimpleNamespace(forced_local_tab_target_rid="production-recovery")
    phase=SimpleNamespace(all_rows=[])
    row=dict(actual_focus_node=raw["focus_node"],visit_record_status="NOT_RECORDED",focus_transition_status="CONFIRMED_UNCHANGED")
    monkeypatch.setattr(harness.collection_flow,"_apply_step_collection_phase",lambda **kw:row)
    monkeypatch.setattr(harness.collection_flow,"_apply_row_persistence_phase",lambda **kw:None)
    monkeypatch.setattr(harness.collection_flow,"_apply_content_terminal_phase",lambda *a,**kw:(False,""))
    def loop(*a):
        kwargs=dict(step_idx=1,state=state,client=client,dev="synthetic",phase_ctx=phase)
        harness.collection_flow._apply_step_collection_phase(**kwargs)
        harness.collection_flow._apply_content_terminal_phase(client,"synthetic",state,row,phase,1,False,"")
        harness.collection_flow._apply_row_persistence_phase(step_idx=1,row=row)
        if failure: raise RuntimeError("bounded runner failure")
    monkeypatch.setattr(harness.collection_flow,"_main_loop_phase",loop)
    names=("_main_loop_phase","_apply_step_collection_phase","_apply_row_persistence_phase","_apply_content_terminal_phase","_apply_focus_reconciliation")
    hooks={name:getattr(harness.collection_flow,name) for name in names}
    def run(*a,**kw):
        harness.collection_flow._main_loop_phase(client,"synthetic",phase)
    monkeypatch.setattr(harness.runpy,"run_path",run)
    if failure:
        with pytest.raises(RuntimeError): harness.main(generalized=True)
    else:
        assert harness.main(generalized=True)==0
    assert all(getattr(harness.collection_flow,name) is fn for name,fn in hooks.items())
    result=json.loads((tmp_path/"phase4c_execution_trace.jsonl").read_text())
    assert result["after_refresh"]["snapshot"] and result["candidate_count"]>0
    assert result["fallback_used"] and result["phase4b_visit_credit"]==0
    assert not result["no_progress_proven"]


@pytest.mark.parametrize("ack,correlation_id",[(True,"current"),(False,"current"),(True,"stale")])
def test_scroll_audit_uses_native_request_not_focus_transaction(ack, correlation_id):
    result=dict(success=ack,reqId=correlation_id)
    calls=[]
    def reader(*args,**kwargs):
        calls.append((args,kwargs))
        return result
    client=SimpleNamespace(_read_log_result=reader,_evidence_active_request_id="unrelated-focus-request")
    audit={}
    def scroll(**kwargs):
        assert kwargs==dict(dev="device",direction="down")
        assert client._read_log_result("device","SCROLL_RESULT","current") is result
        return result["success"]
    assert scroll_request_audit(client,scroll,audit,dev="device",direction="down") is ack
    assert client._read_log_result is reader
    assert calls==[(("device","SCROLL_RESULT","current"),{})]
    assert audit["helper_request_id"]=="current"
    assert audit["helper_result_correlated"] is (correlation_id=="current")
    assert audit["helper_ack_result"]==result


def test_scroll_audit_restores_reader_on_failure():
    class Client:
        def _read_log_result(self,*args): raise RuntimeError("transport failure")
    client=Client()
    def scroll(**kwargs): return client._read_log_result("device","SCROLL_RESULT","current")
    with pytest.raises(RuntimeError): scroll_request_audit(client,scroll,{})
    assert "_read_log_result" not in vars(client)
