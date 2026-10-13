from copy import deepcopy
import json
from pathlib import Path

import pytest

from tb_runner.action_provenance import (
    action_chain_failures, build_action_chain, chain_gates, digest, final_actor_proven,
)
from tb_runner.evidence import EvidenceRuntime
from tools.phase4b_controlled_monitor import controlled_target_evidence_failures

FIXTURE = Path(__file__).parent / 'fixtures/phase4c_food_step11_audit.json'


def food():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def linked(value=None):
    value = deepcopy(value or food())
    audit = value['audit']
    chain = build_action_chain(audit, audit['production_row'], value['events'])
    audit['action_audit_chain'] = chain
    audit['production_row']['step_action_provenance'] = dict(step_action_id=chain['step_action_id'], sha256=digest(chain))
    return audit, chain


def primary_only():
    value = food()
    value['events'] = [e for e in value['events'] if str(e['step_index']) == '11']
    audit = value['audit']
    row = audit['production_row']
    row['actual_focus_node'] = deepcopy(audit['immediate_actual_focus'])
    row['actual_focus_resource_id'] = ''
    reconciliation = next(e['payload'] for e in value['events'] if e['event_type'] == 'FOCUS_RECONCILIATION')
    row['focus_reconciliation_evidence'] = deepcopy(reconciliation)
    row['focus_transition_status'] = 'CONFIRMED_MOVED'
    row['visit_record_status'] = 'RECORDED'
    audit['actual_focus_after'] = deepcopy(row['actual_focus_node'])
    audit['focus_reconciliation'] = deepcopy(reconciliation)
    return value


def devices_scroll_case(requests=("focus-before", "focus-production")):
    value = primary_only()
    audit = value["audit"]
    row = audit["production_row"]
    source = value["events"][0]
    action_request = "scroll-action"
    transaction = "tx:post-scroll-observation"
    scenario = audit["scenario"]
    step = audit["step"]
    owner = dict(status="PROVEN", step=step, transaction_id=transaction,
        request_ids=list(requests), acknowledged_request_ids=list(requests),
        request_domains={request: "FOCUS_OBSERVATION" for request in requests},
        request_domain="FOCUS_OBSERVATION", read_only=True, observation_type="POST_ACTION",
        source_action_request_id=action_request, production_request_id=requests[-1])
    next_sequence = max(event["producer_sequence"] for event in value["events"]) + 1
    for request in requests:
        common = {key: source[key] for key in (
            "schema_version", "run_id", "scenario_tx_id", "logical_action_id", "attempt_id",
            "producer", "producer_instance_id", "scenario_id", "plugin_family", "phase",
            "surface_id", "surface_revision")}
        common.update(transaction_id=transaction, step_index=step, parent_transaction_id=None,
            causation_event_id=None, provenance={"evidence_enabled": True},
            runner_received_wall_time_utc=None)
        sent = dict(common, event_id=f"evt:{request}:sent", event_type="ACTION_SENT",
            producer_sequence=next_sequence, wall_time_utc="2026-01-01T00:00:00Z",
            payload={"command_type":"com.iotpart.sqe.talkbackhelper.GET_FOCUS","request_id":request})
        next_sequence += 1
        ack = dict(common, event_id=f"evt:{request}:ack", event_type="HELPER_ACK_RECEIVED",
            producer_sequence=next_sequence, wall_time_utc="2026-01-01T00:00:01Z",
            payload={"request_id":request,"helper_result":{"reqId":request,"success":True}})
        next_sequence += 1
        value["events"].extend((sent, ack))
    row["get_focus_req_id"] = requests[-1]
    row["actual_focus_node"]["reqId"] = requests[-1]
    audit.update(actual_execution_mode="CONTROLLED_SCROLL", planner_action="SCROLL_FORWARD",
        planner_authorized=True, planner_executed=True,
        execution_gate_result={"allowed":True,"mode":"CONTROLLED_SCROLL"},
        helper_request_id=action_request,
        helper_ack_result={"reqId":action_request,"success":True,"action":"SCROLL_FORWARD"},
        helper_result_correlated=True,
        helper_request_source="SCROLL_RESULT_EXPLICIT_TRANSPORT_ARGUMENT",
        scroll_action="SCROLL_FORWARD",
        primary_production_outcome={"get_focus_req_id":requests[-1],
            "actual_focus_node":deepcopy(row["actual_focus_node"]),
            "focus_reconciliation_evidence":deepcopy(row["focus_reconciliation_evidence"])},
        fallback_observation_ownership=owner)
    return value


def test_exact_food_old_mismatch_and_new_complete_actor_chain():
    value = food()
    assert controlled_target_evidence_failures(value['audit']) == ['FINAL_ACTUAL_FOCUS_DISAGREES_WITH_PRODUCTION_RECONCILIATION']
    old = deepcopy(value)
    audit, chain = linked(value)
    assert action_chain_failures(chain, audit) == []
    assert controlled_target_evidence_failures(audit) == []
    assert final_actor_proven(audit)
    assert len(chain['recovery_result_event_ids']) == 3
    assert chain['final_outcome']['actor'] == 'RECOVERY_ACTION'
    assert audit['visit_credit'] == old['audit']['visit_credit'] == 0
    assert chain['audit_visit_authority'] is False
    assert 'focus_reconciliation_evidence' not in audit['production_row']
    assert value == old


def test_primary_success_no_recovery_retains_one_chain():
    audit, chain = linked(primary_only())
    assert action_chain_failures(chain, audit) == []
    assert chain['final_outcome']['actor'] == 'PRIMARY_ACTION'
    assert chain['recovery_result_event_ids'] == []


@pytest.mark.parametrize('primary_status', ['failure', 'ambiguous', 'ack_failure_actual_move'])
def test_primary_status_is_not_rewritten_by_recovery(primary_status):
    value = food()
    value['audit']['helper_ack_result']['success'] = False
    for e in value['events']:
        if str(e['step_index']) == '11' and e['event_type'] == 'HELPER_ACK_RECEIVED':
            e['payload']['helper_result']['success'] = False
        if str(e['step_index']) == '11' and e['event_type'] == 'FOCUS_RECONCILIATION' and primary_status != 'ack_failure_actual_move':
            e['payload']['focus_transition_status'] = 'AMBIGUOUS' if primary_status == 'ambiguous' else 'UNAVAILABLE'
            e['payload']['visit_record_status'] = 'NOT_RECORDED'
    audit, chain = linked(value)
    assert action_chain_failures(chain, audit) == []
    assert chain['primary_helper_result']['success'] is False
    primary = next(e for e in chain['events'] if e['event_type'] == 'FOCUS_RECONCILIATION')
    assert primary['payload']['focus_transition_status'] == ('CONFIRMED_MOVED' if primary_status == 'ack_failure_actual_move' else 'AMBIGUOUS' if primary_status == 'ambiguous' else 'UNAVAILABLE')


def test_ack_failure_actual_move_without_recovery_keeps_reconciliation():
    value = primary_only()
    value['audit']['helper_ack_result']['success'] = False
    for e in value['events']:
        if e['event_type'] == 'HELPER_ACK_RECEIVED': e['payload']['helper_result']['success'] = False
    audit, chain = linked(value)
    assert action_chain_failures(chain, audit) == []
    assert chain['final_outcome']['reconciliation']['visit_record_status'] == 'RECORDED'


def test_final_recovery_row_and_primary_are_separate_immutable_facts():
    value = food()
    audit, chain = linked(value)
    row = deepcopy(audit['production_row'])
    assert chain['original_focus_after']['className'] == 'android.widget.Button'
    assert chain['final_outcome']['actual_focus']['className'] == 'android.view.View'
    assert len({a['request_ids'][0] for a in chain['actions']}) == 4
    value['events'][0]['payload'].clear()
    value['audit']['production_row'].clear()
    assert audit['production_row'] == row
    assert not action_chain_failures(chain, audit)


def test_production_fallback_keeps_original_planner_decision():
    value = food()
    value['audit']['fallback_used'] = True
    audit, chain = linked(value)
    assert chain['planner']['production_fallback_used'] is True
    assert chain['planner']['action'] == value['audit']['planner_action']
    assert not action_chain_failures(chain, audit)


def test_current_fallback_observation_ownership_is_explicit_and_fail_closed():
    audit,chain=linked(devices_scroll_case())
    owner=chain['fallback_observation_ownership']
    assert chain['primary_request_id']=='scroll-action'
    assert chain['primary_request_domain']=='ACTION_DISPATCH'
    assert owner['request_ids']==['focus-before','focus-production']
    assert chain['action_to_observation_lineage']['source_request_domain']=='ACTION_DISPATCH'
    assert chain['action_to_observation_lineage']['production_observation_request_id']=='focus-production'
    assert action_chain_failures(chain,audit)==[]
    chain['fallback_observation_ownership']['acknowledged_request_ids']=[]
    audit['fallback_observation_ownership']['acknowledged_request_ids']=[]
    assert 'FALLBACK_OBSERVATION_OWNERSHIP_UNPROVEN' in action_chain_failures(chain,audit)


def test_controlled_scroll_and_multiple_current_get_focus_requests_have_separate_domains():
    audit,chain=linked(devices_scroll_case())
    assert chain['primary_request_id'] not in chain['fallback_observation_ownership']['request_ids']
    obs_action=next(a for a in chain['actions'] if a['transaction_id']=='tx:post-scroll-observation')
    assert obs_action['request_domains']=={
        'focus-before':['FOCUS_OBSERVATION'],'focus-production':['FOCUS_OBSERVATION']}
    assert chain['action_to_observation_lineage']['source_action_acknowledged'] is True
    assert action_chain_failures(chain,audit)==[]


def test_scroll_request_is_validated_in_its_action_domain():
    audit,chain=linked(devices_scroll_case())
    scroll=next(a for a in chain['actions'] if a['transaction_id']=='')
    assert scroll['request_domains']['scroll-action']==['ACTION_DISPATCH']
    scroll['correlated']=False
    assert 'MISMATCHED_REQUEST_OWNERSHIP' in action_chain_failures(chain,audit)


@pytest.mark.parametrize('mutation',[
    'observation_ack_missing','previous_step_receipt','primary_substitution',
    'wrong_request_domain','broken_action_lineage','wrong_production_request',
])
def test_observation_ownership_remains_current_and_fail_closed(mutation):
    audit,chain=linked(devices_scroll_case())
    owner=chain['fallback_observation_ownership']
    obs=next(a for a in chain['actions'] if a['transaction_id']==owner['transaction_id'])
    if mutation=='observation_ack_missing':
        owner['acknowledged_request_ids']=['focus-before']
        audit['fallback_observation_ownership']=deepcopy(owner)
    elif mutation=='previous_step_receipt':
        owner['request_ids']=['receipt:previous-step']
        owner['acknowledged_request_ids']=['receipt:previous-step']
        audit['fallback_observation_ownership']=deepcopy(owner)
    elif mutation=='primary_substitution':
        owner['request_ids']=['scroll-action']
        owner['acknowledged_request_ids']=['scroll-action']
        audit['fallback_observation_ownership']=deepcopy(owner)
    elif mutation=='wrong_request_domain':
        owner['request_domains']['focus-production']='ACTION_DISPATCH'
        audit['fallback_observation_ownership']=deepcopy(owner)
    elif mutation=='broken_action_lineage':
        chain['action_to_observation_lineage']['observation_transaction_id']='tx:other'
    else:
        chain['action_to_observation_lineage']['production_observation_request_id']='focus-before'
    assert 'FALLBACK_OBSERVATION_OWNERSHIP_UNPROVEN' in action_chain_failures(chain,audit)


def test_true_request_mismatch_still_fails_closed():
    audit,chain=linked(devices_scroll_case())
    obs=next(a for a in chain['actions'] if a['transaction_id']=='tx:post-scroll-observation')
    ack=next(event for event in chain['events']
        if event['event_type']=='HELPER_ACK_RECEIVED' and event['payload']['request_id']=='focus-production')
    ack['payload']['helper_result']['reqId']='stale'
    assert 'MISMATCHED_REQUEST_OWNERSHIP' in action_chain_failures(chain,audit)


def test_controlled_action_must_still_have_current_execution_authority():
    audit,chain=linked(devices_scroll_case())
    audit['execution_gate_result']['allowed']=False
    chain['planner']['gate']['allowed']=False
    assert 'UNAUTHORIZED_PRIMARY_ACTION' in action_chain_failures(chain,audit)


def test_phase5b_passive_fallback_receipt_is_a_focus_observation():
    value=devices_scroll_case()
    audit=value['audit']
    audit['actual_execution_mode']='FALLBACK_PRODUCTION'
    audit['planner_executed']=False
    audit['fallback_used']=True
    audit['helper_request_id']='focus-production'
    audit['helper_ack_result']={'reqId':'focus-production','success':False,'status':'OBSERVED_NO_MOVE'}
    owner=audit['fallback_observation_ownership']
    owner['observation_type']='FALLBACK'
    owner['source_action_request_id']='focus-production'
    audit['fallback_observation_ownership']=owner
    # Provenance input remains immutable and production visit ownership is unchanged.
    before=deepcopy(value)
    linked_audit,chain=linked(value)
    assert chain['audit_visit_authority'] is False
    assert linked_audit['production_row']['visit_record_status']==before['audit']['production_row']['visit_record_status']
    assert not action_chain_failures(chain,linked_audit)


def test_air_care_and_home_care_saved_acceptance_invariants_are_not_special_cased():
    audit,chain=linked(primary_only())
    assert not action_chain_failures(chain,audit)
    assert chain['audit_visit_authority'] is False


def test_current_fallback_observation_with_stale_step_is_rejected():
    audit,chain=linked()
    action=chain['actions'][0];request=action['request_ids'][0]
    owner=dict(status='PROVEN',step=audit['step']-1,transaction_id=action['transaction_id'],
        request_ids=[request],acknowledged_request_ids=[request])
    audit['helper_request_id']=request;audit['fallback_observation_ownership']=owner
    chain['fallback_observation_ownership']=deepcopy(owner)
    assert 'FALLBACK_OBSERVATION_OWNERSHIP_UNPROVEN' in action_chain_failures(chain,audit)


def test_step_action_identity_is_deterministic_and_scoped():
    audit, chain = linked()
    assert linked()[1]['step_action_id'] == chain['step_action_id']
    other = json.loads(json.dumps(food()).replace('life_food_plugin', 'another_plugin'))
    assert linked(other)[1]['step_action_id'] != chain['step_action_id']
    assert not action_chain_failures(linked(other)[1], linked(other)[0])
    assert chain_gates(chain, audit) == {name: 0 for name in chain_gates(chain)}


@pytest.mark.parametrize('mutation', [
    'missing_primary_ack', 'missing_recovery_ack', 'wrong_ack_req', 'wrong_ack_tx',
    'wrong_ack_scenario_owner', 'wrong_ack_run', 'wrong_final_tx', 'wrong_post_focus',
    'false_post_focus', 'input_focus_only', 'wrong_post_class', 'no_strong_recovery',
    'wrong_gate_tx', 'no_physical_move', 'no_visit', 'missing_primary_reconciliation',
    'missing_recovery_result', 'cross_step', 'cross_scenario', 'cross_run',
    'wrong_primary_req', 'action_id', 'duplicate_event', 'visit_authority',
    'missing_action_reference', 'wrong_action_role', 'primary_result_req',
])
def test_stale_or_incomplete_evidence_never_completes_a_chain(mutation):
    audit, chain = linked()
    tx = chain['final_outcome']['actor_transaction_id']
    ack = next(e for e in chain['events'] if e['event_type'] == 'HELPER_ACK_RECEIVED' and e['transaction_id'] == tx)
    post = next(e for e in chain['events'] if e['event_type'] == 'POST_FOCUS_OBSERVED' and e['transaction_id'] == tx and e['producer'] == 'runner')
    gate = next(e for e in chain['events'] if e['event_type'] == 'PRODUCTION_TRAVERSAL_GATE_DECIDED' and e['transaction_id'] == tx)
    result = next(e for e in chain['events'] if e['event_type'] == 'RECOVERY_CANDIDATE_RESULT' and e['transaction_id'] == tx)
    if mutation.startswith('missing_') and mutation in {'missing_primary_ack','missing_recovery_ack'}:
        role_recovery = mutation == 'missing_recovery_ack'
        chain['events'] = [e for e in chain['events'] if not (e['event_type']=='HELPER_ACK_RECEIVED' and (':recovery:' in str(e['step_index'])) == role_recovery)]
    elif mutation == 'wrong_ack_req': ack['payload']['helper_result']['reqId'] = 'stale'
    elif mutation == 'wrong_ack_tx': ack['payload']['helper_result']['evidenceCorrelation']['transaction_id'] = 'stale'
    elif mutation == 'wrong_ack_scenario_owner': ack['payload']['helper_result']['evidenceCorrelation']['scenario_tx_id'] = 'stale'
    elif mutation == 'wrong_ack_run': ack['payload']['helper_result']['evidenceCorrelation']['run_id'] = 'stale'
    elif mutation == 'wrong_final_tx': chain['final_outcome']['actor_transaction_id'] = 'stale'
    elif mutation == 'wrong_post_focus': post['payload']['observation']['resource_id'] = 'wrong'
    elif mutation in {'false_post_focus','input_focus_only'}:
        post['payload']['observation']['accessibility_focused'] = False
        post['payload']['observation']['focused'] = True
    elif mutation == 'wrong_post_class': post['payload']['observation']['class_name'] = 'wrong'
    elif mutation == 'no_strong_recovery': result['payload']['strong_recovery'] = False
    elif mutation == 'wrong_gate_tx': gate['payload']['progress']['transaction_id'] = 'stale'
    elif mutation == 'no_physical_move': gate['payload']['progress']['physical_progress'] = False
    elif mutation == 'no_visit': gate['payload']['visit']['visited'] = False
    elif mutation == 'missing_primary_reconciliation': chain['primary_reconciliation_event_ids'] = []
    elif mutation == 'missing_recovery_result': chain['events'].remove(result)
    elif mutation == 'cross_step': chain['events'][0]['step_index'] = 12
    elif mutation == 'cross_scenario': chain['events'][0]['scenario_id'] = 'another'
    elif mutation == 'cross_run': chain['events'][0]['run_id'] = 'stale'
    elif mutation == 'wrong_primary_req': chain['primary_request_id'] = 'stale'
    elif mutation == 'action_id': chain['step_action_id'] = 'arbitrary'
    elif mutation == 'duplicate_event': chain['events'].append(deepcopy(chain['events'][0]))
    elif mutation == 'visit_authority': chain['audit_visit_authority'] = True
    elif mutation == 'missing_action_reference': chain['actions'][-1]['event_ids'].append('missing')
    elif mutation == 'wrong_action_role': chain['actions'][-1]['role'] = 'PRIMARY_ACTION'
    elif mutation == 'primary_result_req': chain['primary_helper_result']['reqId'] = 'stale'
    assert action_chain_failures(chain, audit)
    assert chain_gates(chain, audit)['AUDIT_CHAIN_INCOMPLETE_COUNT'] == 1
    assert not final_actor_proven(audit)


@pytest.mark.parametrize('mutation', ['hash', 'final_focus', 'wrong_step', 'wrong_scenario', 'primary_target', 'primary_correlation'])
def test_acceptance_still_rejects_false_actor_or_target_evidence(mutation):
    audit, chain = linked()
    if mutation == 'hash': audit['production_row']['step_action_provenance']['sha256'] = 'wrong'
    elif mutation == 'final_focus': audit['actual_focus_after']['accessibilityFocused'] = False
    elif mutation == 'wrong_step': audit['step'] = 12
    elif mutation == 'wrong_scenario': audit['scenario'] = 'another'
    elif mutation == 'primary_target': audit['immediate_actual_focus']['viewIdResourceName'] = 'wrong'
    else: audit['helper_result_correlated'] = False
    assert controlled_target_evidence_failures(audit)


def test_native_step_reader_does_not_leak_previous_step_or_scenario(tmp_path):
    runtime = EvidenceRuntime(output_path=tmp_path / 'proof', enabled=True)
    runtime.start_scenario('generic')
    for step in [1, '1:recovery:1', 2]:
        runtime.set_step(step)
        runtime.emit('EXAMPLE', producer='runner', phase='recovery')
    assert {str(e.step_index) for e in runtime.events_for_step(1)} == {'1','1:recovery:1'}
    before = tuple(runtime._all_events)
    assert runtime.events_for_step(2)
    assert tuple(runtime._all_events) == before
    runtime.start_scenario('another')
    assert runtime.events_for_step(1) == ()
