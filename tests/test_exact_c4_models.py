from copy import deepcopy
import json
from pathlib import Path
import pytest
from talkback_lib.exact_action import *
from talkback_lib.exact_node_protocol import request_digest

ROOT=Path(__file__).resolve().parents[1]
NOW=1700000000000
INTENT=dict(kind='NAVIGATION',target_class='NAVIGATION_TARGET',semantic_approved=True,isolation_approved=True,
    destination_contract_id='synthetic:destination',destination_contract_digest='d'*64,evidence_refs=['synthetic:reviewed'])

def sample():
    raw=json.loads((ROOT/'tests/fixtures/exact_protocol/golden.json').read_text(encoding='utf-8'))['cases'][0]['request']
    resolve=ExactNodeRequest.parse(raw)
    session=TrustedActionSession(bytes(range(32)),'host:golden','com.example.smartthings','synthetic:1','b'*64,
        'boot:test','helper:golden','stop:0',frozenset({digest(INTENT)}),frozenset({digest(raw['target_identity'])}),frozenset({raw['transaction_id']}),'MATCH')
    return session,session.issue(resolve,intent=INTENT,now_ms=NOW)

def test_legal_and_illegal_transitions_never_resurrect_permit():
    tx=ActionTransaction()
    for state in (ActionState.VALIDATED,ActionState.RESOLVED,ActionState.PRE_DISPATCH_APPROVED,
                  ActionState.DISPATCH_STARTED,ActionState.CONSUMED,ActionState.ACKED):tx.transition(state)
    assert tx.consumed
    for state in ActionState:
        with pytest.raises(ActionRejected):tx.transition(state)
    with pytest.raises(ActionRejected):ActionTransaction().transition(ActionState.CONSUMED)

@pytest.mark.parametrize('missing',REQUIRED_CHECKS)
def test_every_pre_dispatch_condition_is_mandatory(missing):
    facts=dict.fromkeys(REQUIRED_CHECKS,True)
    assert pre_dispatch_gate(facts)[0]
    for value in (False,None,1,'true'):
        facts[missing]=value
        assert not pre_dispatch_gate(facts)[0]

@pytest.mark.parametrize('kwargs,expected',[
    ({},TargetClass.UNKNOWN_ACTIONABLE),({'mutation':True},TargetClass.STATE_MUTATION_CONTROL),
    ({'independent_actions':1,'navigation_semantics':True},TargetClass.MIXED_ACTION_CONTAINER),
    ({'wrapper':True},TargetClass.CONTAINER_WRAPPER),({'navigation_semantics':True},TargetClass.NAVIGATION_TARGET)])
def test_generic_classification(kwargs,expected):assert classify_target(**kwargs)==expected

def test_authenticated_permit_and_tamper():
    session,request=sample();session.verify(request,NOW)
    for field in request['binding']:
        damaged=deepcopy(request);damaged['binding'][field]=None
        damaged['request_digest']=request_digest(damaged)
        with pytest.raises((ActionRejected,TypeError,ValueError,KeyError)):session.verify(damaged,NOW)
    for key in ('request_id','transaction_id','permit_id','request_nonce','ownership'):
        bad=deepcopy(request);bad['binding'][key]='wrong';bad['request_digest']=request_digest(bad)
        with pytest.raises(ActionRejected):session.verify(bad,NOW)
    with pytest.raises(ActionRejected):session.verify(request,NOW+3000)
    with pytest.raises(ActionRejected):session.verify(request,NOW-1)
    bad=deepcopy(request);bad['permit_mac']='0'*64;bad['request_digest']=request_digest(bad)
    with pytest.raises(ActionRejected,match='AUTHENTICATION'):session.verify(bad,NOW)
    with pytest.raises(ActionRejected):session.verify(dict(request,protocol_version='talkback.exact-navigation.v1'),NOW)

def test_foreign_session_epoch_and_build_are_rejected():
    session,request=sample()
    for name in ('session_id','boot_epoch','connection_epoch','stop_epoch','helper_build_id'):
        fields=dict(session.__dict__);fields[name]='wrong'
        with pytest.raises(ActionRejected):TrustedActionSession(**fields).verify(request,NOW)
    for name in ('allowed_target_digests','allowed_transaction_ids'):
        fields=dict(session.__dict__);fields[name]=frozenset({'unapproved'})
        with pytest.raises(ActionRejected,match='PERMIT_SCOPE_MISMATCH'):TrustedActionSession(**fields).verify(request,NOW)
    for status in ('UNKNOWN','MISMATCH'):
        fields=dict(session.__dict__);fields['identity_status']=status
        with pytest.raises(ActionRejected,match='BUILD_IDENTITY_UNKNOWN'):TrustedActionSession(**fields).verify(request,NOW)

def test_monotonic_session_deadline_cannot_be_extended_by_wall_clock_rollback(monkeypatch):
    session,request=sample()
    monkeypatch.setattr('talkback_lib.exact_action.time.monotonic_ns',lambda:session.created_monotonic_ns+6_000_000_000)
    with pytest.raises(ActionRejected,match='PERMIT_EXPIRED'):session.verify(request,NOW)
