from copy import deepcopy
import json
from pathlib import Path
import pytest
from talkback_lib.exact_action import ActionAck,ActionRejected

ROWS=json.loads((Path(__file__).parent/'fixtures/exact_protocol/action_ack.json').read_text(encoding='utf-8'))

def test_actual_kotlin_produced_action_acks_are_understood_without_navigation_credit():
    for row in ROWS:
        ack=ActionAck.parse(row['ack'],row['request'])
        assert not ack.dispatch_confirmed
        assert ack.data['action_effect_confirmed'] is False
        assert ack.data['expected_navigation_confirmed'] is False

@pytest.mark.parametrize('field',['request_id','transaction_id','permit_id','request_nonce','ownership','request_digest',
    'helper_build_id','helper_connection_epoch','boot_epoch','stop_epoch','authorized_intent_digest'])
def test_foreign_ack_ownership_digest_and_epoch_are_never_accepted(field):
    row=deepcopy(ROWS[0]);row['ack'][field]='wrong'
    with pytest.raises(ActionRejected):ActionAck.parse(row['ack'],row['request'])

@pytest.mark.parametrize('mutation',[{'perform_action_return':False},{'perform_action_call_count':1},
    {'visit_authority':True},{'action_effect_confirmed':True},{'expected_navigation_confirmed':True},
    {'unknown_critical':True},{'execution_state':'POST_VERIFIED'},{'audit_receipt_id':None}])
def test_malformed_partial_or_false_success_ack_is_rejected(mutation):
    row=deepcopy(ROWS[0]);row['ack'].update(mutation)
    with pytest.raises(ActionRejected):ActionAck.parse(row['ack'],row['request'])

def test_missing_return_is_not_same_as_explicit_null():
    row=deepcopy(ROWS[0]);del row['ack']['perform_action_return']
    with pytest.raises(ActionRejected):ActionAck.parse(row['ack'],row['request'])

def positive_schema_row():
    row=deepcopy(ROWS[1]);ack=row['ack'];target=deepcopy(row['request']['resolve_request']['target_identity'])
    target['snapshot_id']='helper:fresh';target['node_local_id']='helper:fresh:0:0'
    ack.update(perform_action_called=True,perform_action_call_count=1,perform_action_type=16,perform_action_return=True,
        execution_state='ACKED',failure_code=None,candidate_count=1,pre_dispatch_gate_verdict='APPROVED',
        helper_validation_snapshot_id='helper:fresh',resolved_target_identity=target,resolved_source_node_id=target['source_node_id'],
        source_id_provenance=target['source_node_id_provenance'],resolved_action_set=target['actions'],
        dispatch_started_at='2026-10-16T00:00:00Z',dispatch_finished_at='2026-10-16T00:00:01Z',dispatch_uptime_ms=100)
    return row

def test_positive_schema_is_dispatch_evidence_only():
    row=positive_schema_row();ack=ActionAck.parse(row['ack'],row['request'])
    assert ack.dispatch_confirmed and not ack.data['expected_navigation_confirmed']

@pytest.mark.parametrize('damage',['audit_bool','fractional_action','stale_snapshot','unknown_descriptor_field',
    'missing_provenance','source_id_bool','bounds_bool','exception_object','failure_code_object','timestamp_bool','framework_bool','exception_string'])
def test_malformed_positive_receipt_never_confirms_dispatch(damage):
    row=positive_schema_row();ack=row['ack'];target=ack['resolved_target_identity']
    if damage=='audit_bool':ack['audit_receipt_id']=True
    elif damage=='fractional_action':ack['perform_action_type']=16.0
    elif damage=='stale_snapshot':ack['helper_validation_snapshot_id']=target['snapshot_id']='B'
    elif damage=='unknown_descriptor_field':target['unknown_critical']=True
    elif damage=='missing_provenance':del target['field_provenance']['bounds']
    elif damage=='source_id_bool':target['source_node_id']=ack['resolved_source_node_id']=True
    elif damage=='bounds_bool':target['bounds']['left']=True
    elif damage=='exception_object':ack['exception_detail']={}
    elif damage=='failure_code_object':ack['failure_code']={}
    elif damage=='timestamp_bool':ack['dispatch_started_at']=True
    elif damage=='framework_bool':ack['framework_event_correlation_window']=True
    elif damage=='exception_string':ack['exception_detail']='unresolved exception'
    with pytest.raises(ActionRejected):ActionAck.parse(ack,row['request'])
