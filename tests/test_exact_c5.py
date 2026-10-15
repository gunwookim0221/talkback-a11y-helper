from copy import deepcopy
import json
from pathlib import Path
import pytest

from talkback_lib.exact_action import ActionRejected, ActionAck
from talkback_lib.exact_action_journal import DurableActionJournal
from talkback_lib.exact_post_action import (PostActionVerifier, Correlation, Outcome, DestinationContract,
    collector_ready, REQUIRED_EVENT_TYPES, event_in_window, correlate, normalize, verify_helper_export, digest)
from tools.exact_c5_fixture import fixture, export


def run(tmp_path, modify=None):
    request, records=fixture()
    if modify:modify(request,records)
    v=PostActionVerifier(DurableActionJournal(tmp_path/'journal.jsonl'),request)
    v.import_evidence(export(request,records))
    return v,v.finalize()


def test_positive_and_production_evidence_only(tmp_path):
    v,result=run(tmp_path)
    assert result['result']=='NAVIGATION_CONFIRMED',result
    assert result['action_dispatch_confirmed'] and result['action_effect_confirmed'] and result['expected_navigation_confirmed']
    assert result['audit_complete'] and not result['visit_authority']
    h=v.handoff()
    assert h['navigation_confirmed'] and h['requires_production_focus_reconciliation']
    assert not h['visit_authority']
    assert not any(k in h for k in ('coverage','visit_count','scenario_pass'))
    assert result['forbidden_effect_status']=='FORBIDDEN_EFFECT_PROVEN_ABSENT'


@pytest.mark.parametrize('field', ['request_id','permit_id','transaction_id','request_nonce','ownership','boot_epoch',
                                  'helper_connection_epoch','helper_build_id','stop_epoch'])
def test_stale_ownership_is_never_attributed(tmp_path,field):
    def change(r,rows):rows[6][1][field]='stale'
    _,result=run(tmp_path,change)
    assert not result['expected_navigation_confirmed']


@pytest.mark.parametrize('case', ['two_clicks','parent','child','no_source','same_label','different_window',
    'old_event','outside_window','old_request','competing_transaction','partial_ack','stale_probe','source_screen',
    'unstable','missing_state','duplicate_probe','no_close','interrupted','missing_arm','missing_consumed',
    'missing_dispatch','missing_result','missing_ack','no_events','no_probes','return_false','unknown','no_unique_source'])
def test_rejections(tmp_path,case):
    def change(r,rows):
        event=rows[6][1];p=rows[8][1]
        if case in ('two_clicks','same_label'):
            other=deepcopy(event);other['event_uptime_ms']+=1;other['source_identity']['resource_id']='sibling'
            rows.insert(7,('C5_RAW_EVENT',other))
        elif case in ('parent','child'):event['source_identity']['lineage_signature']=[case]
        elif case=='no_source':event['source_identity']=None
        elif case=='no_unique_source':event['source_provenance']='PARTIAL_ACCESSIBILITY_SOURCE'
        elif case=='different_window':event['window_id']=99
        elif case=='old_event':event['event_uptime_ms']=99
        elif case=='outside_window':event['event_uptime_ms']=5091;event['helper_receive_uptime_ms']=5092
        elif case=='old_request':event['request_id']='previous'
        elif case=='competing_transaction':
            rows.append(('DISPATCH_STARTED',{'consumption_receipt_id':'other'}))
        elif case=='partial_ack':rows[5][1].pop('ownership')
        elif case=='stale_probe':p['post_action_probe_id']='previous'
        elif case=='source_screen':
            for i in (7,8):rows[i][1]['root_signature']='source:structure:v1'
        elif case=='unstable':p['root_signature']='other'
        elif case=='missing_state':p['security_state']={}
        elif case=='duplicate_probe':p['observation_sequence']=1
        elif case=='no_close':rows.pop()
        elif case=='interrupted':rows.append(('C5_OBSERVATION_INTERRUPTED',{'reason':'restart'}))
        elif case in ('missing_arm','missing_consumed','missing_dispatch','missing_result','missing_ack'):
            rows.pop({'missing_arm':1,'missing_dispatch':2,'missing_consumed':3,'missing_result':4,'missing_ack':5}[case])
        elif case=='no_events':rows.pop(6)
        elif case=='no_probes':del rows[7:9]
        elif case=='return_false':
            rows[4][1]['return']=False
            rows[5][1].update(perform_action_return=False,execution_state='FAILED_CONSUMED',failure_code='PERFORM_ACTION_FALSE')
        elif case=='unknown':
            rows[4][1]['return']=None
            rows[5][1].update(perform_action_return=None,execution_state='UNKNOWN_EXECUTION_STATE',failure_code='UNKNOWN_EXECUTION_STATE')
    _,result=run(tmp_path,change)
    assert not result['expected_navigation_confirmed'],(case,result)
    assert result['hard_stop'] and not result['retry_allowed'] and not result['visit_authority']


@pytest.mark.parametrize('case',['sibling','wrong_modal','wrong_package','wrong_destination','state_only',
    'wrapper','child','source_unchanged','unknown_activity'])
def test_wrong_effects(tmp_path,case):
    def change(r,rows):
        event=rows[6][1]
        if case in ('sibling','wrapper','child'):
            event['source_identity']['resource_id']=case
            c=rows[1][1]['destination_contract'];c['forbidden_effects']['control_identities']=[digest(event['source_identity'])]
            # Re-approve only this synthetic fixture's declarative contract.
            r['binding']['semantic_intent']['destination_contract_digest']=digest(c)
            r['binding']['authorized_intent_digest']=digest(r['binding']['semantic_intent'])
            r['request_digest']=digest({k:v for k,v in r.items() if k!='request_digest'})
            rows[5][1]['authorized_intent_digest']=r['binding']['authorized_intent_digest']
            rows[5][1]['request_digest']=r['request_digest']
        for i in (7,8):
            p=rows[i][1]
            if case=='wrong_modal':p['modal']='UNEXPECTED'
            if case=='wrong_package':p['package']='other.app'
            if case=='wrong_destination':p['root_signature']='wrong:structure'
            if case=='state_only':p['security_state']['security:status']='changed'
            if case=='source_unchanged':p['root_signature']='source:structure:v1'
            if case=='unknown_activity':p['activity']='other.Activity'
    _,result=run(tmp_path,change)
    assert not result['expected_navigation_confirmed']
    assert result['hard_stop']


@pytest.mark.parametrize('t,receive,expected,reason',[(99,110,False,'PRE_CURSOR_EVIDENCE'),
    (100,100,False,'EVENT_ORDER_AMBIGUOUS'),(101,110,True,'IN_WINDOW'),(5089,5090,True,'IN_WINDOW'),
    (5090,6090,True,'IN_WINDOW'),(5091,5092,False,'LATE_EVIDENCE'),
    (5090,6091,False,'LATE_EVIDENCE'),(110,109,False,'EVENT_CLOCK_INVALID')])
def test_window_boundaries(t,receive,expected,reason):
    r,rows=fixture();c=rows[1][1];e=rows[6][1]
    e.update(event_uptime_ms=t,helper_receive_uptime_ms=receive,event_sequence=7)
    assert event_in_window(e,c,100)==(expected,reason)


@pytest.mark.parametrize('host_clock',[0,-99999999999999,9999999999999999])
def test_host_clocks_are_not_compared(tmp_path,host_clock):
    def change(r,rows):rows[6][1].update(host_receive_timestamp_ms=host_clock,host_monotonic_ns=host_clock)
    _,result=run(tmp_path,change)
    assert result['expected_navigation_confirmed']


def test_duplicate_click_callbacks_are_ambiguous_and_raw_is_preserved(tmp_path):
    def change(r,rows):rows.insert(7,deepcopy(rows[6]))
    v,result=run(tmp_path,change)
    assert not result['expected_navigation_confirmed']
    assert result['result']=='AMBIGUOUS_EFFECT'
    assert 'ACTION_EFFECT_AMBIGUOUS' in result['failure_codes']
    assert len(result['normalized_events'])==2 and result['normalized_events'][1]['duplicate']
    assert len(v.journal.records()[0]['evidence']['rows'])==12


@pytest.mark.parametrize('stage',[4,5,7,8,9])
def test_crash_partial_export_never_promotes_success(tmp_path,stage):
    r,rows=fixture();v=PostActionVerifier(DurableActionJournal(tmp_path/'j'),r)
    v.import_evidence(export(r,rows[:stage]))
    before=v.journal.path.read_bytes()
    recovered=PostActionVerifier(DurableActionJournal(v.journal.path),r).replay()
    assert not recovered['expected_navigation_confirmed']
    assert before==v.journal.path.read_bytes()


def test_persist_failure_never_returns_success(tmp_path,monkeypatch):
    r,rows=fixture();v=PostActionVerifier(DurableActionJournal(tmp_path/'j'),r);v.import_evidence(export(r,rows))
    def fail(*a,**kw):raise OSError('disk full')
    monkeypatch.setattr(v.journal,'append',fail)
    result=v.finalize()
    assert result['result']=='AUDIT_FAILURE' and not result['expected_navigation_confirmed']
    with pytest.raises(ActionRejected):v.handoff()


def test_chain_tamper_and_duplicate_import_rejected(tmp_path):
    r,rows=fixture();e=export(r,rows);e[6]['record']['payload']['text']=['tampered']
    with pytest.raises(ActionRejected):verify_helper_export(e)
    v,result=run(tmp_path)
    with pytest.raises(ActionRejected):v.import_evidence(export(r,rows))
    before=v.journal.path.read_bytes();v.replay();assert v.journal.path.read_bytes()==before


@pytest.mark.parametrize('field',['service_connected','listener_active','producer_sequence_available','cursor_registered',
    'persistent_audit_writable','no_competing_transaction','connection_epoch_current','destination_contract_approved','forbidden_contract_observable'])
def test_readiness_is_all_required(field):
    facts={k:True for k in ['service_connected','listener_active','producer_sequence_available','cursor_registered',
        'persistent_audit_writable','no_competing_transaction','connection_epoch_current','destination_contract_approved','forbidden_contract_observable']}
    facts['event_types']=REQUIRED_EVENT_TYPES
    assert collector_ready(facts)
    facts[field]=False;assert not collector_ready(facts)
    facts[field]='true';assert not collector_ready(facts)


def test_no_action_no_second_authority_static():
    root=Path(__file__).resolve().parents[1]
    paths=[root/'talkback_lib/exact_post_action.py',root/'app/src/main/java/com/iotpart/sqe/talkbackhelper/ExactPostAction.kt']
    for path in paths:
        code=path.read_text(encoding='utf-8')
        for token in ('.performAction(','.dispatchGesture(','.tap(','.click(','.mark_visit(','.increment_coverage(', 'configureTrustedLocalSession('):
            assert token not in code
    runtime=(root/'app/src/main/java/com/iotpart/sqe/talkbackhelper/ExactActionRuntime.kt').read_text()
    assert 'BuildConfig.HELPER_BUILD_ID,version,ExactActionReadiness()' in runtime


def test_security_observability_unknown_cannot_be_claimed_absent(tmp_path):
    def change(r,rows):rows[1][1]['security_observability']={'status':'UNKNOWN'}
    _,result=run(tmp_path,change)
    assert result['action_dispatch_confirmed'] and result['action_effect_confirmed']
    assert not result['expected_navigation_confirmed']
    assert result['forbidden_effect_status']=='FORBIDDEN_EFFECT_NOT_OBSERVED'
    assert 'SECURITY_STATE_UNOBSERVABLE' in result['failure_codes']


def test_replay_before_finalization_is_not_navigation_success(tmp_path):
    r,rows=fixture();v=PostActionVerifier(DurableActionJournal(tmp_path/'j'),r);v.import_evidence(export(r,rows))
    assert not v.replay()['expected_navigation_confirmed']
    with pytest.raises(ActionRejected):v.handoff()
    assert v.finalize()['expected_navigation_confirmed']
    assert v.replay()['expected_navigation_confirmed']


def test_truthy_call_ack_no_effect_is_not_success(tmp_path):
    def change(r,rows):rows.pop(6)
    _,result=run(tmp_path,change)
    assert result['result']=='NO_EFFECT' and result['action_dispatch_confirmed']
    assert not result['action_effect_confirmed'] and not result['expected_navigation_confirmed']


def test_wrong_state_effect_has_independent_three_flags(tmp_path):
    def change(r,rows):rows[8][1]['security_state']['security:status']='mutated'
    _,result=run(tmp_path,change)
    assert result['result']=='FORBIDDEN_EFFECT' and result['action_dispatch_confirmed'] and result['action_effect_confirmed']
    assert not result['expected_navigation_confirmed']


def test_missing_event_types_are_not_ready():
    assert not collector_ready({'event_types':None})
    assert not collector_ready({})


def test_existing_helper_bounds_aliases_are_canonical_not_new_identity(tmp_path):
    def change(r,rows):
        bounds=rows[6][1]['source_identity']['bounds']
        for a,k in zip(('l','t','r','b'),('left','top','right','bottom')):bounds[a]=bounds[k]
    _,result=run(tmp_path,change)
    assert result['expected_navigation_confirmed']


def test_contradictory_bounds_aliases_are_not_equivalent(tmp_path):
    def change(r,rows):rows[6][1]['source_identity']['bounds']['l']=999
    _,result=run(tmp_path,change)
    assert not result['expected_navigation_confirmed']
