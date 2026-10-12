from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import json

import pytest

from tb_runner.phase5b_navigation import SafeNavigationSession, SafetyBlocked, default_contracts, same_parent, ownership, structure, return_scope_conflict, current_return_target, focus_target_identity, _extras
from tb_runner.action_safety import classify_action
from tb_runner.canonical_json import canonical_sha256
from tb_runner.safe_action_policy import evaluate_policy
from tb_runner.phase5a_safety import SafetySession
from tb_runner.phase4a_planner import plan_shadow
from test_phase4b_authority import value
from test_phase5a_action_safety import candidate, meta


def session():
    records=[]
    return SafeNavigationSession('synthetic',lambda name,r:records.append((name,r))),records


def broadcast(suffix):
    return ['shell','am','broadcast','-a','com.iotpart.sqe.talkbackhelper.'+suffix,'-p','com.iotpart.sqe.talkbackhelper']


class SnapshotValue:
    def __init__(self, candidates, state_id='state:dispatch'):
        self.snapshot=SimpleNamespace(to_dict=lambda:dict(candidates=deepcopy(candidates),state_id=state_id,
            semantic_substates=[],fingerprint_hash='fingerprint',viewport_signature='viewport'))


def focus_case(*, focusable=True, label='Information', resource_id='app:id/control', bounds='0,0,100,100', scenario='synthetic'):
    from tb_runner.traversal_reliability import normalized_bounds
    raw_node=dict(viewIdResourceName=resource_id,className='Button',boundsInScreen=bounds,text=label,
        contentDescription='',talkbackLabel=label,clickable=True,focusable=focusable,enabled=True,visibleToUser=True)
    c=candidate(label,'FOCUS_TARGET')
    c['target_semantics']['flags']['focusable']=focusable
    c['target_identity'].update(resource_id=resource_id,class_name='Button',bounds=normalized_bounds(bounds))
    raw=dict(scenario_id=scenario,scenario_run_id='run:dispatch',package_name='app',activity_name='app.Main',
        context_source='window_current_focus',step=3,snapshot_hash='snapshot:dispatch',
        nodes=[raw_node],destination_ownership={'destination':'app.Main'})
    return raw, SnapshotValue([c]), c


def focus_command(target=None, request='request:dispatch', action='TARGET_FOCUS_COMMIT'):
    target=target or dict(resource_id='app:id/control',class_name='Button',bounds='0,0,100,100')
    return broadcast(action)+['--es','bounds',target['bounds'],'--es','targetId',target['resource_id'],
        '--es','className',target['class_name'],'--es','targetLabel','Information','--es','reqId',request]


def focus_scope(s, raw, value, c, *, allowed=True, step=3, dispatch_kind='PRIMARY'):
    return s.authorize_focus_target(raw=raw,value=value,target=c['target_identity'],
        phase4_gate={'allowed':allowed,'mode':'CONTROLLED_TARGET_FOCUS'},step=step,dispatch_kind=dispatch_kind)


def navigation_proof(s,target,step='phase5b:entry'):
    identity=focus_target_identity(target)
    focus=dict(viewIdResourceName=identity['resource_id'],className=identity['class_name'],
        boundsInScreen=identity['bounds'],accessibilityFocused=True,focusable=False,visibleToUser=True)
    s.raw=dict(scenario_id=s.scenario,scenario_run_id='run:navigation',package_name='app',
        activity_name='app.Main',selected_tab={'name':'home'},phase3_entry_evidence={'entry_contract_digest':'entry'},
        step=step,focus_node=focus,nodes=[focus])
    state_id='state:navigation'
    return dict(target_identity=identity,action_type='NAVIGATE',safety_class='CONDITIONALLY_SAFE',
        policy={'eligible':True,'reason':'ELIGIBLE_FOR_PHASE4_GATE'},
        phase4_gate={'allowed':True,'reason':'CONTROLLED_TARGET_FOCUS'},
        destination_ownership=ownership(s.raw),state_id=state_id,step=step,
        observation_epoch=canonical_sha256(dict(scenario=s.scenario,step=step,
            ownership=ownership(s.raw),structure=structure(s.raw),state_id=state_id)))


@pytest.mark.parametrize('action',['CLICK_FOCUSED','CLICK_TARGET','CHECK_TARGET','SET_TEXT','SET_SYSTEM_LANGUAGE','TOUCH_BOUNDS_CENTER_TARGET','ACTION_COMMAND','UNKNOWN'])
def test_unapproved_native_activations_never_dispatched(action):
    s,records=session();called=[]
    client=SimpleNamespace(_run=lambda *a,**k:called.append(a))
    with s.firewall(client,'serial'):
        with pytest.raises(SafetyBlocked):client._run(broadcast(action),dev='serial')
    assert called==[] and records[-1][1]['executed'] is False
    client._run(broadcast(action))
    assert len(called)==1


@pytest.mark.parametrize('args',[
    ['shell','input','tap','5','5'], ['shell','input','text','anything'],
    ['shell','input','swipe','1','1','50','50'], ['shell','input','keyevent','4'],
    ['shell','input','keyevent','3'], ['shell','am','start','anything'],
    ['shell','am','force-stop','app'],['shell','settings','put','secure','x','y']])
def test_recovery_and_fallback_cannot_bypass_transport_gate(args):
    s,_=session();calls=[]
    device=SimpleNamespace(_run_adb_command=lambda *a,**kw:calls.append(a))
    client=SimpleNamespace(_run=lambda *a,**kw:calls.append(a),_adb_device=device)
    with s.firewall(client,'serial'):
        for run in [client._run,device._run_adb_command]:
            with pytest.raises(SafetyBlocked):run(args,dev='serial')
    assert not calls


@pytest.mark.parametrize('action',['DUMP_TREE','DUMP_HIERARCHY','GET_FOCUS','PING','EVIDENCE_EVENTS'])
def test_existing_read_only_transport_preserved(action):
    s,_=session()
    assert s.command_allowed(broadcast(action))


@pytest.mark.parametrize('action',['FOCUS_IN_BOUNDS','FOCUS_TARGET','TARGET_FOCUS_COMMIT'])
def test_unbound_focus_transport_is_not_read_only(action):
    s,_=session()
    assert not s.command_allowed(focus_command(action=action))


def test_A_same_target_same_action_is_authorized_once_for_exact_scope():
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c) as permit:
        assert s.command_allowed(focus_command(c['target_identity']))
        assert permit['consumed'] and permit['request']=='request:dispatch'
        assert not s.command_allowed(focus_command(c['target_identity'],request='request:second'))
    assert s.permit is None


def test_authorized_focus_permit_is_consumed_at_the_actual_adb_boundary():
    s,_=session();raw,v,c=focus_case();calls=[]
    device=SimpleNamespace(_run_adb_command=lambda command,**kw:calls.append(tuple(command)))
    client=SimpleNamespace(_run=lambda command,dev=None:device._run_adb_command(command,dev=dev),_adb_device=device)
    with s.firewall(client,'serial'),focus_scope(s,raw,v,c):
        client._run(focus_command(c['target_identity']),dev='serial')
        with pytest.raises(SafetyBlocked):client._run(focus_command(c['target_identity'],request='request:second'),dev='serial')
    assert len(calls)==1


def test_shell_quoted_empty_resource_id_matches_the_preflight_target_at_adb_boundary():
    s,_=session();raw,v,c=focus_case(resource_id='');calls=[]
    device=SimpleNamespace(_run_adb_command=lambda command,**kw:calls.append(tuple(command)))
    client=SimpleNamespace(_run=lambda command,dev=None:device._run_adb_command(command,dev=dev),_adb_device=device)
    target=c['target_identity'];request='request:empty-resource-id'
    command=focus_command(target,request=request)
    command[command.index('targetId')+1]='""'  # ADB shell encoding from _escape_adb_string("").
    assert _extras(command)['targetId']==''
    with s.firewall(client,'serial'),focus_scope(s,raw,v,c) as permit:
        assert client._phase5b_preflight_target_focus(target=target,request_id=request,dev='serial')
        client._run(command,dev='serial')
        assert permit['consumed'] and permit['request']==request
    assert len(calls)==1
    authorized=[r for r in s.dispatch_authorizations if r['event']=='NATIVE_DISPATCH_AUTHORIZED']
    assert len(authorized)==1 and authorized[0]['target_identity']['resource_id']==''


def test_focus_preflight_binds_request_and_actual_adb_boundary_rechecks_it():
    s,_=session();raw,v,c=focus_case();calls=[]
    device=SimpleNamespace(_run_adb_command=lambda command,**kw:calls.append(tuple(command)))
    client=SimpleNamespace(_run=lambda command,dev=None:device._run_adb_command(command,dev=dev),_adb_device=device)
    with s.firewall(client,'serial'),focus_scope(s,raw,v,c) as permit:
        request='request:preflight-bound'
        assert client._phase5b_preflight_target_focus(target=c['target_identity'],request_id=request,dev='serial')
        assert permit['request']==request and not permit['consumed']
        client._run(focus_command(c['target_identity'],request=request),dev='serial')
        assert permit['consumed']
    assert len(calls)==1
    authorized=[r for r in s.dispatch_authorizations if r['event']=='NATIVE_DISPATCH_AUTHORIZED']
    assert len(authorized)==1 and authorized[0]['request_id']=='request:preflight-bound'


def test_bounds_only_recovery_is_blocked_before_dispatch_intent():
    s,_=session()
    s.raw=dict(scenario_id='synthetic',scenario_run_id='run:observed',package_name='app',
        activity_name='app.Main',step=9,context_source='window_current_focus',nodes=[])
    client=SimpleNamespace(_run=lambda *a,**kw:pytest.fail('bounds-only preflight must not dispatch'),_adb_device=None)
    with s.firewall(client,'serial'):
        allowed=client._phase5b_preflight_bounds_focus(
            bounds='66,316,525,1012',request_id='request:bounds-only',dev='serial')
    blocked=next(r for r in s.dispatch_authorizations if r['event']=='BLOCKED_NATIVE_DISPATCH')
    assert not allowed
    assert blocked['request_id']=='request:bounds-only'
    assert blocked['invalidation_reason']=='NO_CURRENT_TARGET_PERMIT'
    assert blocked['executed'] is False


def test_unknown_secondary_focus_is_blocked_during_preflight_before_action_intent():
    s,_=session()
    rid='com.samsung.android.oneconnect:id/device_name'
    raw=dict(scenario_id='home_main',scenario_run_id='run:observed',package_name='com.samsung.android.oneconnect',
        activity_name='com.samsung.android.oneconnect.ui.scmain.SCMainActivity',step=10,
        context_source='window_current_focus',nodes=[dict(viewIdResourceName=rid,className='android.widget.TextView',
            boundsInScreen='78,635,309,683',text='세이프 버튼',talkbackLabel='세이프 버튼',clickable=False,
            focusable=False,enabled=True,visibleToUser=True)])
    s.raw=raw
    client=SimpleNamespace(_run=lambda *a,**kw:pytest.fail('blocked preflight must not dispatch'),_adb_device=None)
    with s.firewall(client,'serial'):
        allowed=client._phase5b_preflight_target_focus(
            target=dict(resource_id=rid,class_name='android.widget.TextView',bounds='78,635,309,683'),
            request_id='request:blocked-before-intent',dev='serial')
    blocked=next(r for r in s.dispatch_authorizations if r['event']=='BLOCKED_NATIVE_DISPATCH')
    assert not allowed
    assert blocked['safety_class']=='UNKNOWN' and blocked['policy_decision']=='BLOCK_UNKNOWN'
    assert blocked['request_id']=='request:blocked-before-intent' and not blocked['executed']


def test_secondary_activation_without_phase4_gate_is_classified_and_blocked_before_dispatch():
    s, _ = session()
    s.raw = dict(scenario_id='life_family_care_plugin', scenario_run_id='run:observed',
        package_name='com.samsung.android.oneconnect', activity_name='com.samsung.android.plugin.care.Main',
        context_source='window_current_focus', step=1, nodes=[dict(text='More options',
            contentDescription='', talkbackLabel='More options', viewIdResourceName='',
            className='android.widget.ImageView', boundsInScreen='924,106,1032,286',
            clickable=True, focusable=True, enabled=True, visibleToUser=True)])
    allowed = s.preflight_activation_dispatch(target=dict(action_type='CLICK',
        name=r'^More\ options$', target_type='a', target_text=None, target_id=None,
        index=0, class_name=None), request_id='request:secondary-menu')
    blocked = next(r for r in s.dispatch_authorizations if r['event']=='BLOCKED_BEFORE_DISPATCH')
    assert allowed is False
    assert blocked['dispatch_kind']=='SECONDARY'
    assert blocked['action_type']=='CLICK' and blocked['safety_class']=='UNKNOWN'
    assert blocked['policy_decision']=='BLOCK_UNKNOWN'
    assert blocked['execution_gate']=={'allowed':False,'reason':'NO_EXACT_PHASE4_ACTION_GATE'}
    assert blocked['request_id']=='request:secondary-menu'
    assert blocked['target_resolution']=='UNIQUE' and blocked['matched_target_count']==1
    assert blocked['executed'] is False and blocked['authorization_valid'] is False


def test_exact_preserved_unknown_secondary_focus_replay_is_blocked_before_helper():
    s,_=session();calls=[]
    rid='com.samsung.android.oneconnect:id/device_name'
    raw=dict(scenario_id='home_main',scenario_run_id='run:observed',package_name='com.samsung.android.oneconnect',
        activity_name='com.samsung.android.oneconnect.ui.scmain.SCMainActivity',step=10,
        context_source='window_current_focus',nodes=[dict(viewIdResourceName=rid,className='android.widget.TextView',
            boundsInScreen='78,635,309,683',text='세이프 버튼',talkbackLabel='세이프 버튼',clickable=False,
            focusable=False,enabled=True,visibleToUser=True)])
    s.raw=raw
    device=SimpleNamespace(_run_adb_command=lambda command,**kw:calls.append(tuple(command)))
    client=SimpleNamespace(_run=lambda command,dev=None:device._run_adb_command(command,dev=dev),_adb_device=device)
    command=focus_command(dict(resource_id=rid,class_name='android.widget.TextView',bounds='78,635,309,683'),
        request='895773aeb784427eade19957520d14f9')
    with s.firewall(client,'serial'):
        with pytest.raises(SafetyBlocked):client._run(command,dev='serial')
    blocked=next(r for r in s.dispatch_authorizations if r['event']=='BLOCKED_NATIVE_DISPATCH')
    assert blocked['safety_class']=='UNKNOWN'
    assert blocked['invalidation_reason']=='NO_CURRENT_TARGET_PERMIT'
    assert calls==[]


def test_B_retargeted_focus_requires_a_fresh_authorization():
    s,_=session();raw,v,c=focus_case()
    changed=dict(c['target_identity'],resource_id='app:id/other',bounds='100,0,200,100')
    with focus_scope(s,raw,v,c):
        assert not s.command_allowed(focus_command(changed))


def test_C_focus_authorization_does_not_authorize_a_different_action():
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c):
        assert not s.command_allowed(focus_command(c['target_identity'],action='FOCUS_IN_BOUNDS'))
        assert not s.command_allowed(broadcast('CLICK_FOCUSED')+['--es','reqId','request:dispatch'])


def test_D_fallback_invalidates_the_current_target_authorization():
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c):
        s.invalidate_authorization('FALLBACK_BOUNDARY')
        assert not s.command_allowed(focus_command(c['target_identity']))
    assert any(r['event']=='INVALIDATED' and r['invalidation_reason']=='FALLBACK_BOUNDARY' for r in s.dispatch_authorizations)


def test_E_secondary_safe_target_executes_only_after_fresh_authorization():
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c,dispatch_kind='SECONDARY'):
        assert s.command_allowed(focus_command(c['target_identity']))
    assert any(r['event']=='NATIVE_DISPATCH_AUTHORIZED' and r['dispatch_kind']=='SECONDARY' for r in s.dispatch_authorizations)


def test_F_secondary_unknown_target_is_blocked_with_observed_classification():
    s,_=session();raw,v,c=focus_case(focusable=False);s.raw=raw
    assert not s.command_allowed(focus_command(c['target_identity']))
    blocked=next(r for r in s.dispatch_authorizations if r['event']=='BLOCKED_NATIVE_DISPATCH')
    assert blocked['safety_class']=='UNKNOWN' and blocked['policy_decision']=='BLOCK_UNKNOWN'


def test_G_risky_secondary_activation_cannot_reuse_focus_authorization():
    risky=classify_action(candidate('Delete'),metadata=meta('delete')).to_dict()
    assert risky['safety_class']=='RISKY' and not evaluate_policy(risky).eligible
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c):
        assert not s.command_allowed(broadcast('CLICK_FOCUSED')+['--es','reqId','request:dispatch'])


def test_H_forbidden_secondary_activation_cannot_reuse_focus_authorization():
    forbidden=classify_action(candidate('Delete'),metadata=meta('delete',forbidden=True)).to_dict()
    assert forbidden['safety_class']=='FORBIDDEN' and not evaluate_policy(forbidden).eligible
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c):
        assert not s.command_allowed(broadcast('CLICK_FOCUSED')+['--es','reqId','request:dispatch'])


def test_I_post_scroll_observation_rebuild_invalidates_prior_authorization():
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c):
        s.invalidate_authorization('POST_SCROLL_REBUILD')
        assert not s.command_allowed(focus_command(c['target_identity']))


def test_J_state_or_structure_change_invalidates_authorization_epoch():
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c):
        s.raw['nodes'][0]['boundsInScreen']='0,0,101,100'
        assert not s.command_allowed(focus_command(c['target_identity']))


def test_K_same_visual_label_different_target_identity_does_not_inherit_permit():
    s,_=session();raw,v,c=focus_case(label='Information')
    other=dict(c['target_identity'],resource_id='app:id/other')
    raw['nodes'].append(dict(raw['nodes'][0],viewIdResourceName='app:id/other',boundsInScreen='100,0,200,100'))
    with focus_scope(s,raw,v,c):
        assert not s.command_allowed(focus_command(other))


def test_L_new_step_observation_rejects_stale_permit():
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c):
        next_raw=deepcopy(raw);next_raw['step']=4
        s.observe(next_raw,{})
        assert not s.command_allowed(focus_command(c['target_identity']))


def test_M_prior_scenario_permit_cannot_be_used_in_another_scenario():
    s,_=session();raw,v,c=focus_case()
    with focus_scope(s,raw,v,c):
        s.scenario='other_scenario'
        assert not s.command_allowed(focus_command(c['target_identity']))


@pytest.mark.parametrize('action',['NEXT','PREV','SMART_NEXT'])
def test_unknown_unbound_movement_cannot_reenter_through_transport(action):
    s,_=session();calls=[];s.raw={'nodes':[]}
    client=SimpleNamespace(_run=lambda *a,**kw:calls.append(a))
    with s.firewall(client,'serial'):
        with pytest.raises(SafetyBlocked):client._run(broadcast(action),dev='serial')
    assert not calls


def test_click_permit_exact_request_single_dispatch_and_wrong_device():
    s,_=session();calls=[]
    proof=navigation_proof(s,dict(resource_id='app:id/menu',class_name='Button',bounds='0,0,100,100'))
    client=SimpleNamespace(_run=lambda *a,**kw:calls.append(a))
    command=broadcast('CLICK_FOCUSED')+['--es','reqId','request']
    with s.firewall(client,'serial'),s.authorize('CLICK','request',proof):
        with pytest.raises(SafetyBlocked):client._run(command,dev='wrong')
        with pytest.raises(SafetyBlocked):client._run(broadcast('CLICK_FOCUSED')+['--es','reqId','stale'],dev='serial')
        client._run(command,dev='serial')
        with pytest.raises(SafetyBlocked):client._run(command,dev='serial')
    assert len(calls)==1 and s.permit is None


def test_back_permit_cannot_authorize_home_confirm_or_second_back():
    s,_=session();proof=navigation_proof(s,dict(resource_id='app:id/menu',class_name='Button',bounds='0,0,100,100'))
    with s.authorize('BACK'):
        assert not s.command_allowed(['shell','input','keyevent','3'])
        assert not s.command_allowed(broadcast('CLICK_FOCUSED'))
        assert not s.command_allowed(['shell','input','keyevent','4'])
    with s.authorize('BACK',authorization=proof):
        assert s.command_allowed(['shell','input','keyevent','4'])
        assert not s.command_allowed(['shell','input','keyevent','4'])


@pytest.mark.parametrize('kind',['CLICK','BACK'])
def test_real_adb_executor_forwarding_consumes_one_native_dispatch(kind):
    from talkback_lib.adb_executor import AdbExecutor
    s,_=session();calls=[]
    proof=navigation_proof(s,dict(resource_id='app:id/menu',class_name='Button',bounds='0,0,100,100'))
    device=SimpleNamespace(_run_adb_command=lambda command,**kw:calls.append(tuple(command)))
    executor=AdbExecutor(device)
    client=SimpleNamespace(_run=executor.run,_adb_device=device)
    command=broadcast('CLICK_FOCUSED')+['--es','reqId','request'] if kind=='CLICK' else ['shell','input','keyevent','4']
    with s.firewall(client,'serial'),s.authorize(kind,'request' if kind=='CLICK' else None,proof):
        client._run(command,dev='serial')
        with pytest.raises(SafetyBlocked):client._run(command,dev='serial')
        with pytest.raises(SafetyBlocked):device._run_adb_command(command,dev='serial')
    assert calls==[tuple(command)]


@pytest.mark.parametrize('change',['duplicate','command','device'])
def test_nested_forwarding_receipt_cannot_allow_second_or_changed_dispatch(change):
    s,_=session();calls=[]
    proof=navigation_proof(s,dict(resource_id='app:id/menu',class_name='Button',bounds='0,0,100,100'))
    device=SimpleNamespace(_run_adb_command=lambda command,**kw:calls.append(tuple(command)))
    command=broadcast('CLICK_FOCUSED')+['--es','reqId','request']
    def delegate(command,dev=None):
        if change=='duplicate':device._run_adb_command(command,dev=dev)
        altered=command if change!='command' else broadcast('CLICK_FOCUSED')+['--es','reqId','other']
        return device._run_adb_command(altered,dev='wrong' if change=='device' else dev)
    client=SimpleNamespace(_run=delegate,_adb_device=device)
    with s.firewall(client,'serial'),s.authorize('CLICK','request',proof):
        with pytest.raises(SafetyBlocked):client._run(command,dev='serial')
    assert len(calls)==int(change=='duplicate')


def test_direct_touch_helper_cannot_bypass_and_restores_method():
    s,_=session();calls=[]
    tap=lambda *a,**k:calls.append(a)
    device=SimpleNamespace(_tap=tap)
    with s.firewall(SimpleNamespace(_adb_device=device),'serial'):
        with pytest.raises(SafetyBlocked):device._tap(dev='serial',x=1,y=1)
    assert not calls and device._tap is tap


@pytest.mark.parametrize('control',['SeekBar','Slider','RangeControl'])
def test_smart_next_auto_scroll_not_authorized_on_adjustment_controls(control):
    s,_=session();s.raw={'nodes':[{'className':control}]}
    assert not s.command_allowed(broadcast('SMART_NEXT'))


@pytest.mark.parametrize('action',['delete','payment','physical_control','account_mutation','external_send','privacy_mutation'])
def test_known_dangerous_actions_remain_policy_blocked_before_dispatch(action):
    c=classify_action(candidate(),metadata=meta(action))
    assert c.to_dict()['safety_class'] in {'RISKY','FORBIDDEN'}
    assert not evaluate_policy(c,dict(current_target=True,within_app=True,recovery_verified=True)).eligible


@pytest.mark.parametrize('label',['OK','Next','','Unknown icon'])
def test_unknown_semantics_cannot_be_authorized_for_coverage(label):
    c=classify_action(candidate(label))
    assert not evaluate_policy(c).eligible


@pytest.mark.parametrize('changed',['scenario_id','scenario_run_id','package_name','activity_name'])
def test_return_ownership_must_match_original_parent(changed):
    _,raw=value();raw.update(scenario_id='synthetic',scenario_run_id='run',package_name='app',activity_name='app.Main')
    returned=deepcopy(raw);returned[changed]='other'
    assert not same_parent(raw,returned)


def test_safe_return_requires_original_structure_no_modal_and_ignores_focus_text_churn():
    _,raw=value();raw['overlay']={'observed':False}
    returned=deepcopy(raw)
    returned['nodes'][0]['text']='dynamic'
    returned['nodes'][0]['accessibilityFocused']=True
    assert same_parent(raw,returned)
    returned['nodes'][0]['boundsInScreen']='1,1,2,2'
    assert not same_parent(raw,returned)
    returned=deepcopy(raw);returned['overlay']['observed']=True
    assert not same_parent(raw,returned)


def test_incomplete_return_capture_is_inconclusive_but_positive_scope_change_conflicts():
    _,parent=value();parent.update(scenario_id='synthetic',scenario_run_id='run',package_name='app',activity_name='app.Main',
        selected_tab={'name':'home','verified':True},phase3_entry_evidence={'entry_contract_digest':'entry'})
    incomplete=deepcopy(parent);incomplete['selected_tab']=None;incomplete['nodes']=incomplete['nodes'][:1]
    assert not same_parent(parent,incomplete)
    assert not return_scope_conflict(parent,incomplete,'PARTIAL_CONTEXT')
    wrong_tab=deepcopy(parent);wrong_tab['selected_tab']={'name':'devices','verified':True}
    assert return_scope_conflict(parent,wrong_tab,'VERIFIED_ROOT_CONTEXT')
    wrong_run=deepcopy(parent);wrong_run['scenario_run_id']='other-run'
    assert return_scope_conflict(parent,wrong_run,'VERIFIED_ROOT_CONTEXT')


def test_safety_block_history_survives_observation_id_churn_without_visit_credit():
    s,records=session();v,raw=value();_,report=SafetySession('shadow').prepare(v,raw)
    history=deepcopy(v.history)
    s.observe(raw,report)
    changed=deepcopy(report)
    for row in changed['candidates']:row['classification']['action_id']='new-observation-'+str(row['candidate_id'])
    count=len(s.blocked);s.observe(raw,changed)
    assert len(s.blocked)==count and s.blocked_repeats==count and v.history==history
    assert all(t['executed'] is False for t in records[-1][1]['targets'])


def test_safe_next_candidate_scroll_and_no_loop_are_existing_policy_composition():
    from test_phase5a_action_safety import test_enforcement_skips_forbidden_target_preserves_order_and_history, test_all_focus_blocked_prefers_valid_scroll_otherwise_fallback
    test_enforcement_skips_forbidden_target_preserves_order_and_history()
    test_all_focus_blocked_prefers_valid_scroll_otherwise_fallback()


def test_safe_scroll_requires_exact_current_container():
    s,_=session();calls=[]
    s.raw={'capability':{'axis_contract':'axis-v1','contradictory':False,'can_scroll_forward':True,
        'container':{'path':'0.1','boundsInScreen':'0,0,100,100'}}}
    client=SimpleNamespace(scroll=lambda **kw:calls.append(kw))
    with s.firewall(client,'serial'):
        with pytest.raises(SafetyBlocked):client.scroll(dev='serial',direction='down',container_path='stale',container_bounds='0,0,100,100')
        client.scroll(dev='serial',direction='down',container_path='0.1',container_bounds='0,0,100,100')
    assert len(calls)==1


@pytest.mark.parametrize('coherent',[True,False])
def test_fallback_is_read_only_or_observation_only(monkeypatch,coherent):
    import tb_runner.phase5b_navigation as nav
    s,records=session();s.raw={'nodes':[],'step':1}
    monkeypatch.setattr(nav,'coherent_focus',lambda raw:coherent)
    calls=[];audit={}
    s.fallback(lambda **kw:calls.append(kw),{'move':True},audit)
    assert calls[0]['move'] is False
    assert audit['fallback_policy_decision']=='READ_ONLY_FOCUS_OBSERVATION'


@pytest.mark.parametrize('label',['Cancel','취소','Close','닫기'])
def test_known_cancel_is_conditional_unknown_or_destructive_confirm_blocked(label):
    conditions=dict(current_target=True,modal_verified=True,cancellation_only=True,within_app=True)
    c=classify_action(candidate(label,action='DISMISS'),context={'confirmation_verified':True,'confirmation_risks':['DESTRUCTIVE']},metadata=meta('cancel'))
    assert evaluate_policy(c,conditions).eligible
    confirm=classify_action(candidate('Confirm'),context={'confirmation_verified':True,'confirmation_risks':['DESTRUCTIVE']})
    assert not evaluate_policy(confirm,conditions).eligible


def test_no_navigation_without_verified_root_no_commands():
    s,records=session();v,raw=value()
    assert s.roundtrip(client=SimpleNamespace(),dev='serial',capture=lambda:(raw,v,{'status':'PARTIAL_CONTEXT'}),step=5) is None
    assert s.completed and not records


def test_defaults_and_no_scenario_specific_effect_rules():
    config=default_contracts()
    assert config['default_enabled'] is False and config['max_child_entries_per_scenario']==1
    assert all('scenario_id' not in c for c in config['contracts'])


def test_new_opt_in_required_before_device(monkeypatch):
    from tools.phase4b_controlled_smoke import main
    monkeypatch.delenv('TB_PHASE5B_CONTROLLED',raising=False)
    with pytest.raises(ValueError):main(generalized=True,safe_navigation=True)


def roundtrip_case(monkeypatch, defect=None):
    import tb_runner.phase5b_navigation as nav
    from tb_runner.discovery_candidates import build_discovery_snapshot
    from tb_runner.state_registry import StateRegistry
    from state_model_fixtures import node
    s,records=session();v,parent=value(context='VERIFIED_ROOT_CONTEXT')
    parent.update(package_name='com.samsung.android.oneconnect',activity_name='com.samsung.android.oneconnect.Main',scenario_id='synthetic',scenario_run_id='run',overlay={'observed':False},phase5b_recovery_clear=True)
    parent['nodes'][0].update(viewIdResourceName='com.samsung.android.oneconnect:id/more_menu_button_container',text='More options')
    focused=deepcopy(parent)
    focused['nodes'][0]['accessibilityFocused']=True
    focused['nodes'][1]['accessibilityFocused']=False
    focused['focus_node']=deepcopy(focused['nodes'][0])
    child=deepcopy(parent)
    child['nodes']=[node('android:id/title','Edit','0,0,500,100',accessibilityFocused=True)]
    child['focus_node']=deepcopy(child['nodes'][0])
    if defect=='component_alias':child['activity_name']='.Main'
    if defect=='click_only_focus':
        child['nodes'][0].update(focusable=False,clickable=True,text='Location settings')
        child['focus_node']=deepcopy(child['nodes'][0])
    returned=deepcopy(parent)
    if defect=='editable':child['nodes'][0]['editable']=True
    if defect=='external':child['package_name']='external'
    if defect=='failed_return':returned['activity_name']='wrong'
    sequence=[parent,parent,focused,child,child,returned,returned]
    if defect in {'transient_return','unstable_return'}:
        incomplete=deepcopy(returned);incomplete['selected_tab']=None;incomplete['source']='helper_flat'
        incomplete['nodes']=incomplete['nodes'][:max(1,len(incomplete['nodes'])//2)]
        tail=[returned,incomplete,returned,returned if defect=='transient_return' else incomplete]
        sequence=[parent,parent,focused,child,child,*tail]
    if defect=='wrong_tab_return':
        wrong_tab=deepcopy(returned);tab=(parent.get('selected_tab') or {}).get('name')
        wrong_tab['selected_tab']={'name':'devices' if tab!='devices' else 'home','verified':True,'source':'service_hierarchy_selected'}
        sequence=[parent,parent,focused,child,child,wrong_tab,returned]
    if defect in {'settle','never_settles'}:
        pending=deepcopy(child);pending['focus_node']['accessibilityFocused']=False
        sequence=[parent,parent,focused,pending,child,child,returned,returned] if defect=='settle' else [parent,parent,focused,pending,pending,pending]
    captures=iter(sequence)
    registry=StateRegistry('safe-roundtrip-test')
    def capture(**kwargs):
        raw=deepcopy(next(captures));snapshot=build_discovery_snapshot(raw,registry)
        raw['snapshot_hash']=snapshot.candidate_set_hash
        status='PARTIAL_CONTEXT' if raw.get('source')=='helper_flat' else 'VERIFIED_ROOT_CONTEXT'
        return raw,replace(v,snapshot=snapshot),{'status':status}
    def prepare(**kwargs):
        kwargs['audit'].update(helper_result_correlated=defect!='stale_focus',planner_failed=False)
        return {}
    monkeypatch.setattr(nav,'controlled_collect',prepare)
    monkeypatch.setattr(nav,'get_talkback_restart_event',lambda client:None)
    sent=[];request={}
    client=SimpleNamespace(check_helper_status=lambda **kw:True,collect_focus_step=lambda **kw:{},
        _evidence_set_step=lambda *a,**kw:None,_evidence_begin_step_action=lambda *a,**kw:None,
        _evidence_action_sent=lambda **kw:request.update(kw),_evidence_helper_ack=lambda *a,**kw:None,
        _run=lambda *a,**kw:sent.append(a[0]))
    client._broadcast=lambda dev,action,extras:client._run(broadcast('CLICK_FOCUSED')+extras,dev=dev)
    client._read_log_result=lambda dev,prefix,req:{'success':True,'reqId':'stale' if defect=='stale_ack' else req}
    with s.firewall(client,'serial'):
        try:
            record=s.roundtrip(client=client,dev='serial',capture=capture,step=5)
        except SafetyBlocked:
            assert defect
            return sent,records
    assert defect in {None,'component_alias','click_only_focus','settle','transient_return'} and record['entry_confirmed'] and record['return_success']
    assert record['phase4_gate']['allowed'] and record['policy']['eligible']
    assert record['attempt_credit']==record['visit_credit']==0
    assert len(sent)==2 and sent[-1]==['shell','input','keyevent','4']
    assert s.roundtrip(client=client,dev='serial',capture=capture,step=6) is None
    return sent,records


def test_safe_entry_return_actual_gate_policy_and_bound(monkeypatch):
    _,records=roundtrip_case(monkeypatch)
    chain=next(r for n,r in records if n=='phase5b_navigation_chains.jsonl')
    assert chain['return_confirmed_pair']==(0,1) and len(chain['return_observations'])==2


def test_return_confirmation_settles_over_one_incomplete_helper_capture(monkeypatch):
    sent,records=roundtrip_case(monkeypatch,'transient_return')
    chain=next(r for n,r in records if n=='phase5b_navigation_chains.jsonl')
    assert chain['return_success'] and chain['return_confirmed_pair']==(2,3)
    assert chain['return_context_statuses']==['VERIFIED_ROOT_CONTEXT','PARTIAL_CONTEXT','VERIFIED_ROOT_CONTEXT','VERIFIED_ROOT_CONTEXT']
    assert len(chain['return_observations'])==4 and len(sent)==2


@pytest.mark.parametrize('case',['unstable_return','wrong_tab_return'])
def test_return_confirmation_rejects_unstable_or_contradictory_scope(monkeypatch,case):
    sent,records=roundtrip_case(monkeypatch,case)
    chain=next(r for n,r in records if n=='phase5b_navigation_chains.jsonl')
    assert not chain['return_success'] and chain['return_attempted']
    assert len(sent)==2
    assert len(chain['return_observations'])==(1 if case=='wrong_tab_return' else 4)


@pytest.mark.parametrize('case',['component_alias','click_only_focus','settle'])
def test_real_popup_lease_scope_focus_and_read_only_settling(monkeypatch,case):
    sent,records=roundtrip_case(monkeypatch,case)
    chain=next(r for n,r in records if n=='phase5b_navigation_chains.jsonl')
    assert chain['entry_confirmed'] and chain['return_success']
    assert len(chain['child_settle_observations'])==(2 if case=='settle' else 1)
    assert len(sent)==2
    if case=='click_only_focus':
        assert chain['child_observation']['focus_node']['focusable'] is False
        assert chain['return_classification']['action_type']=='NAVIGATE'


def test_child_never_settles_cannot_authorize_back(monkeypatch):
    sent,records=roundtrip_case(monkeypatch,'never_settles')
    assert len(sent)==1
    chain=next(r for n,r in records if n=='phase5b_navigation_chains.jsonl')
    assert not chain['entry_confirmed'] and not chain['return_attempted']
    assert len(chain['child_settle_observations'])==3


@pytest.mark.parametrize('package,activity,expected',[
    ('observed.app','.Main','observed.app.Main'),
    (None,'.Main','.Main'),('observed.app','other.app.Main','other.app.Main')])
def test_lease_android_component_expansion_requires_observed_package(package,activity,expected):
    assert ownership({'package_name':package,'activity_name':activity})['activity']==expected


@pytest.mark.parametrize('defect',['editable','external','stale_focus','stale_ack','failed_return','unstable_return','wrong_tab_return'])
def test_safe_navigation_failure_preserves_evidence_and_never_blindly_returns(monkeypatch,defect):
    sent,records=roundtrip_case(monkeypatch,defect)
    assert records
    assert len(sent)==(0 if defect=='stale_focus' else 2 if defect in {'failed_return','unstable_return','wrong_tab_return'} else 1)


@pytest.mark.parametrize('status,kind,required',[
    ('VERIFIED_ROOT_CONTEXT','root_tab',False),('PARTIAL_CONTEXT','root_tab',False),
    ('VERIFIED_PLUGIN_CONTEXT','plugin',True),('PARTIAL_CONTEXT','plugin',True)])
def test_live_root_entry_does_not_construct_plugin_only_lease(status,kind,required):
    assert SafeNavigationSession.plugin_lease_required({'status':status,'context_type':kind}) is required


@pytest.mark.parametrize('stale',[False,True])
def test_observation_fallback_records_exact_native_request_and_no_move(monkeypatch,stale):
    s,records=session();_,s.raw=value();sent=[];acks=[]
    client=SimpleNamespace(last_smart_nav_result={},last_smart_nav_terminal=False,
        _evidence_set_step=lambda *a,**kw:None,_evidence_begin_step_action=lambda *a,**kw:None,
        _evidence_action_sent=lambda **kw:sent.append(kw),
        _evidence_helper_ack=lambda r,**kw:acks.append((r,kw)),
        _broadcast=lambda *a,**kw:None,
        _read_log_result=lambda *a,**kw:{'reqId':'stale' if stale else 'owned','success':True})
    prior_broadcast,prior_reader=client._broadcast,client._read_log_result
    client.get_focus=lambda **kwargs:s.raw['focus_node']
    def collect(**kwargs):
        assert kwargs['move'] is False
        client._broadcast('serial','com.iotpart.sqe.talkbackhelper.GET_FOCUS',['--es','reqId','owned'])
        client._read_log_result('serial','FOCUS_RESULT','owned')
        return {'move_result':'','actual_focus_node':s.raw['focus_node']}
    audit={};row=s.fallback(collect,{'dev':'serial','move':True,'step_index':1},audit,client)
    assert sent==[{'action':'com.iotpart.sqe.talkbackhelper.GET_FOCUS','req_id':'owned'}]
    assert acks[0][1]['req_id']=='owned'
    assert acks[0][0]['reqId']==('stale' if stale else 'owned')
    assert client.last_smart_nav_result['success'] is False
    assert row['phase4b_before_row']['actual_focus_accessibility_focused'] is True
    assert client._broadcast is prior_broadcast and client._read_log_result is prior_reader


@pytest.mark.parametrize('move',[True,False])
def test_successful_controlled_post_focus_keeps_original_transaction(monkeypatch,move):
    s,_=session();calls=[];original=lambda **kw:calls.append(('production',kw))
    monkeypatch.setattr(s,'fallback',lambda *args:calls.append(('fallback',args[1])))
    s.collect(original,{'move':move}, {}, SimpleNamespace())
    assert calls==[('fallback' if move else 'production',{'move':move})]
