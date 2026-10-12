import json

from tools import phase4c_generalized_monitor as phase4
from tools import phase5b_safe_navigation_monitor as monitor


def _line(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(value,ensure_ascii=False)+'\n')


def _base(tmp_path,monkeypatch):
    monkeypatch.setattr(phase4,'validate_scenario',lambda scenario,out:{'pass':True,'reasons':[]})
    monkeypatch.setattr(phase4.monitor,'save_json',lambda path,value:None)
    scenario='home_main';out=tmp_path/'scenario'
    evidence=out/'run'/scenario/'capture.evidence.jsonl'
    return scenario,out,evidence


def _native(request='req:1'):
    return dict(event_type='ACTION_SENT',scenario_id='home_main',step_index=1,
        payload=dict(command_type='com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT',request_id=request))


def _ack(request='req:1'):
    return dict(event_type='HELPER_ACK_RECEIVED',scenario_id='home_main',step_index=1,
        payload=dict(helper_result=dict(evidenceEvents=[
            dict(eventType='ACTION_EXECUTION_STARTED',reqId=request,
                payload=dict(action='com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT')),
            dict(eventType='TARGET_REQUESTED',reqId=request,payload=dict(targetId='app:id/control',
                requestedBounds="{'l': 0, 't': 0, 'r': 100, 'b': 100}"))])))


def test_native_monitor_accepts_only_exact_correlated_safe_focus_authorization(tmp_path,monkeypatch):
    scenario,out,evidence=_base(tmp_path,monkeypatch)
    identity=dict(resource_id='app:id/control',class_name='Button',bounds='0,0,100,100')
    auth=dict(schema='phase5b-dispatch-authorization-v1',event='NATIVE_DISPATCH_AUTHORIZED',
        scenario=scenario,step=1,request_id='req:1',target_identity=identity,action_type='FOCUS',
        safety_class='SAFE',authorization_valid=True,
        classification=dict(safety_class='SAFE'),policy=dict(eligible=True),
        execution_gate=dict(allowed=True))
    _line(out/'phase5b_dispatch_authorizations.jsonl',auth)
    _line(evidence,_native());_line(evidence,_ack())
    result=monitor.validate_scenario(scenario,out)
    assert result['pass'] is True
    assert result['phase5b_metrics']['SAFE_EXECUTED']==1


def test_native_monitor_rejects_helper_focus_execution_without_authorization(tmp_path,monkeypatch):
    scenario,out,evidence=_base(tmp_path,monkeypatch)
    _line(evidence,_native());_line(evidence,_ack())
    result=monitor.validate_scenario(scenario,out)
    assert result['pass'] is False
    assert 'UNAUTHORIZED_FOCUS_DISPATCH_EXECUTED' in result['reasons']
    assert result['phase5b_metrics']['UNKNOWN_EXECUTED']==1


def test_native_monitor_rejects_authorized_request_for_different_helper_target(tmp_path,monkeypatch):
    scenario,out,evidence=_base(tmp_path,monkeypatch)
    identity=dict(resource_id='app:id/other',class_name='Button',bounds='0,0,100,100')
    auth=dict(event='NATIVE_DISPATCH_AUTHORIZED',scenario=scenario,request_id='req:1',
        target_identity=identity,action_type='FOCUS',safety_class='SAFE',authorization_valid=True,
        classification=dict(safety_class='SAFE'),policy=dict(eligible=True),execution_gate=dict(allowed=True))
    _line(out/'phase5b_dispatch_authorizations.jsonl',auth)
    _line(evidence,_native());_line(evidence,_ack())
    result=monitor.validate_scenario(scenario,out)
    assert result['pass'] is False
    assert 'FOCUS_AUTHORIZATION_TARGET_MISMATCH' in result['reasons']


def test_monitor_counts_secondary_preflight_block_without_treating_it_as_execution(tmp_path,monkeypatch):
    scenario,out,evidence=_base(tmp_path,monkeypatch)
    _line(out/'phase5b_dispatch_authorizations.jsonl',dict(
        schema='phase5b-dispatch-authorization-v1',event='BLOCKED_BEFORE_DISPATCH',
        scenario=scenario,step=1,request_id='req:secondary',dispatch_kind='SECONDARY',
        target_identity=dict(resource_id='',class_name='android.widget.ImageView',bounds='920,24,1050,160'),
        action_type='CLICK',safety_class='UNKNOWN',policy_decision='BLOCK_UNKNOWN',
        execution_gate=dict(allowed=False,reason='NO_EXACT_PHASE4_ACTION_GATE'),
        authorization_valid=False,executed=False))
    _line(out/'phase5b_dispatch_authorizations.jsonl',dict(
        schema='phase5b-dispatch-authorization-v1',event='BOUNDARY_INVALIDATION',
        scenario=scenario,step=1,dispatch_kind='NONE',authorization_valid=False,
        invalidation_reason='SECONDARY_ACTIVATION_BOUNDARY',executed=False))
    result=monitor.validate_scenario(scenario,out)
    metrics=result['phase5b_metrics']
    assert result['pass'] is True
    assert metrics['TOTAL_SECONDARY_DISPATCH_ATTEMPTS']==1
    assert metrics['SECONDARY_UNKNOWN']==1
    assert metrics['SECONDARY_BLOCKED']==1
    assert metrics['SECONDARY_AUTHORIZATION_RECHECKS']==1
    assert metrics['SECONDARY_AUTHORIZATION_FAILURES']==1
    assert metrics['FALLBACK_TARGET_CHANGES']==0
    assert metrics['FALLBACK_AUTHORIZATION_RECHECKS']==0
    assert metrics['AUTHORIZATION_INVALIDATIONS']==1
    assert metrics['SECONDARY_EXECUTED']==0 and metrics['UNKNOWN_EXECUTED']==0


def test_monitor_counts_secondary_focus_recheck_as_fallback_target_change(tmp_path,monkeypatch):
    scenario,out,evidence=_base(tmp_path,monkeypatch)
    _line(out/'phase5b_dispatch_authorizations.jsonl',dict(
        schema='phase5b-dispatch-authorization-v1',event='BLOCKED_NATIVE_DISPATCH',
        scenario=scenario,step=2,request_id='req:secondary-focus',dispatch_kind='SECONDARY',
        target_identity=dict(resource_id='app:id/label',class_name='android.widget.TextView',bounds='0,0,100,100'),
        action_type='FOCUS',safety_class='UNKNOWN',policy_decision='BLOCK_UNKNOWN',
        execution_gate=dict(allowed=False,reason='NO_CURRENT_TARGET_PERMIT'),
        authorization_valid=False,executed=False))
    _line(out/'phase5b_dispatch_authorizations.jsonl',dict(
        schema='phase5b-dispatch-authorization-v1',event='BOUNDARY_INVALIDATION',
        scenario=scenario,step=2,dispatch_kind='NONE',authorization_valid=False,
        invalidation_reason='FALLBACK_BOUNDARY',executed=False))
    result=monitor.validate_scenario(scenario,out)
    metrics=result['phase5b_metrics']
    assert result['pass'] is True
    assert metrics['TOTAL_SECONDARY_DISPATCH_ATTEMPTS']==1
    assert metrics['SECONDARY_AUTHORIZATION_RECHECKS']==1
    assert metrics['SECONDARY_AUTHORIZATION_FAILURES']==1
    assert metrics['FALLBACK_TARGET_CHANGES']==1
    assert metrics['FALLBACK_AUTHORIZATION_RECHECKS']==1
    assert metrics['FALLBACK_BLOCKED_BY_SAFETY']==1
