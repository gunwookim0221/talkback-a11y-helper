from copy import deepcopy
import pytest
from talkback_lib.exact_action import parse_action_response,ActionRejected
from test_exact_c4_models import sample

def unknown(request):
    b=request['binding']
    body={key:b[key] for key in ('request_id','transaction_id','permit_id','request_nonce','ownership','helper_build_id',
        'helper_connection_epoch','boot_epoch','stop_epoch')}
    body.update(request_digest=request['request_digest'],status='UNKNOWN_EXECUTION_STATE',permit_consumed=True,
        action_request_resent=False,visit_authority=False)
    return {'reqId':'readback:1','receipt':body}

def test_unknown_receipt_is_owned_and_never_action_success():
    _,request=sample();result=parse_action_response(unknown(request),request,transport_request_id='readback:1',receipt=True)
    assert result.state=='UNKNOWN_EXECUTION_STATE' and not result.dispatch_confirmed and result.ack is None

@pytest.mark.parametrize('key',['request_id','transaction_id','permit_id','request_nonce','ownership','helper_build_id',
    'helper_connection_epoch','boot_epoch','stop_epoch','request_digest'])
def test_unknown_readback_cannot_attach_to_previous_or_foreign_action(key):
    _,request=sample();response=unknown(request);response['receipt'][key]='wrong'
    with pytest.raises(ActionRejected):parse_action_response(response,request,transport_request_id='readback:1',receipt=True)

def test_gate_disabled_reason_survives_rpc_response_without_granting_credit():
    _,request=sample();body=dict(status='REJECTED',failure_code='ACTION_GATE_DISABLED',perform_action_called=False,visit_authority=False)
    with pytest.raises(ActionRejected,match='ACTION_GATE_DISABLED'):
        parse_action_response({'reqId':'send:1','ack':body},request,transport_request_id='send:1')
    with pytest.raises(ActionRejected):parse_action_response({'reqId':'old','ack':body},request,transport_request_id='send:1')

def test_readback_cannot_claim_action_resend_or_visit_authority():
    _,request=sample()
    for key in ('action_request_resent','visit_authority'):
        response=unknown(request);response['receipt'][key]=True
        with pytest.raises(ActionRejected):parse_action_response(response,request,transport_request_id='readback:1',receipt=True)
