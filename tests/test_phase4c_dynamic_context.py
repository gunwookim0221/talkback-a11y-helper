from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from tb_runner.dynamic_context import DestinationOwnership, rebind_execution, ownership_failures
from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
from tb_runner.plugin_context_contract import plugin_context_evidence, navigation_epoch_guard
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.phase4a_planner import PlannerInput, plan_shadow
from tb_runner.phase4b_authority import AuthorityEvidence, execution_gate
from tools.phase4a_shadow_validate import restore_snapshot
from tools.phase4b_gate_replay import history


def observed(label="TV"):
    config=next(c for c in TAB_CONFIGS if c['scenario_id']=='device_tv_plugin')
    raw=dict(scenario_id='device_tv_plugin',scenario_run_id='owned-run',navigation_epoch='entry-epoch',
        timestamp='2026-10-11T08:00:01+00:00',capture_id='capture-entry',
        package_name='com.samsung.android.oneconnect',activity_name='pkg.plugin.MainActivity',
        context_source='window_current_focus',overlay=dict(observed=False),
        nodes=[dict(text=label,viewIdResourceName='pkg.plugin:id/body',visibleToUser=True)])
    entry=phase3_entry_evidence_from_main_loop(SimpleNamespace(tab_cfg=config,rows=[dict(
        actual_focus_accessibility_focused=True,actual_focus_payload_source='verified_pre_loop_anchor')]),
        raw['scenario_run_id'],raw['timestamp'])
    raw['phase3_entry_evidence']=entry
    raw['phase3_plugin_context_evidence']=plugin_context_evidence(entry,raw,dict(open_completed=True,
        entry_contract_reason='success_verified',entry_contract_detail='plugin_open_verified'),raw['navigation_epoch'])
    return raw


def capture(raw, number, **fields):
    result=deepcopy(raw)
    result.update(timestamp=f'2026-10-11T08:00:{number+2:02d}+00:00',capture_id=f'capture-{number}',**fields)
    return result


@pytest.mark.parametrize('key,value',[('state_id','changed-state'),('semantic_substates',['loading','loaded']),
    ('selected_internal_tab','detail'),('page',2)])
def test_internal_states_do_not_own_destination(key,value):
    raw=observed();owner=DestinationOwnership(raw);identity=owner.ownership_id
    new=capture(raw,1,**{key:value});context=owner.assess(new)
    assert context['status']=='VERIFIED_PLUGIN_CONTEXT'
    assert new['destination_ownership']['ownership_id']==identity
    assert owner.freshness=='FRESH_VERIFIED'


def test_recovery_blocks_then_rebinds_only_after_two_fresh_body_captures():
    raw=observed();owner=DestinationOwnership(raw)
    active=capture(raw,1);owner.assess(active,recovery_active=True)
    assert owner.recovery_state=='RECOVERY_ACTIVE' and owner.freshness=='STALE_REVALIDATABLE'
    first=capture(raw,2);assert owner.assess(first)['status']=='UNRESOLVED_CONTEXT'
    assert owner.recovery_state=='RECOVERY_REVALIDATING'
    second=capture(raw,3);assert owner.assess(second)['status']=='VERIFIED_PLUGIN_CONTEXT'
    assert owner.recovery_state=='RECOVERY_REBOUND'
    assert [e['kind'] for e in owner.events].count('RECOVERY_STARTED')==1
    assert [e['kind'] for e in owner.events].count('RECOVERY_COMPLETED')==1
    assert [e['kind'] for e in owner.events].count('RECOVERY_REBOUND')==1


def test_missing_body_is_revalidatable_not_authorized():
    raw=observed();owner=DestinationOwnership(raw)
    missing=capture(raw,1,nodes=[]);owner.assess(missing,recovery_active=True)
    assert owner.freshness=='STALE_REVALIDATABLE' and not owner.invalid
    owner.assess(capture(raw,2));restored=capture(raw,3);owner.assess(restored)
    assert owner.freshness=='FRESH_VERIFIED' and restored['destination_ownership']['revalidated']


@pytest.mark.parametrize('kind',['CLICK','TAP','BACK'])
def test_potential_internal_navigation_needs_new_epoch_and_two_owned_captures(kind):
    raw=observed();owner=DestinationOwnership(raw)
    owner.navigation(dict(kind=kind),'owned-navigation-1')
    assert owner.freshness=='STALE_REVALIDATABLE'
    a=capture(raw,1,navigation_epoch=owner.epoch);owner.assess(a)
    assert owner.freshness=='STALE_REVALIDATABLE'
    b=capture(raw,2,navigation_epoch=owner.epoch);owner.assess(b)
    assert owner.freshness=='FRESH_VERIFIED' and owner.ownership_id==a['destination_ownership']['ownership_id']
    assert raw['phase3_plugin_context_evidence']['navigation_epoch']=='entry-epoch'
    assert b['phase3_plugin_context_evidence']['navigation_epoch']==owner.epoch


@pytest.mark.parametrize('kind',['HOME','ACTIVITY_START','FORCE_STOP','SCENARIO_EXIT'])
def test_actual_destination_exit_cannot_reuse_old_ownership(kind):
    raw=observed();owner=DestinationOwnership(raw);owner.navigation(dict(kind=kind),'new-epoch')
    for n in [1,2]:assert owner.assess(capture(raw,n,navigation_epoch=owner.epoch))['status']=='UNRESOLVED_CONTEXT'
    assert owner.freshness=='STALE_INVALID'


@pytest.mark.parametrize('change',[dict(scenario_id='device_washer_plugin'),dict(scenario_run_id='another-run'),
    dict(navigation_epoch='arbitrary-epoch'),dict(timestamp='2026-10-10T08:00:00+00:00'),dict(timestamp='invalid')])
def test_owner_scope_and_time_mismatch_fail_closed(change):
    raw=observed();owner=DestinationOwnership(raw);bad=capture(raw,1);bad.update(change)
    assert owner.assess(bad)['status']=='UNRESOLVED_CONTEXT' and owner.invalid


@pytest.mark.parametrize('change',[dict(activity_name='pkg.OtherPlugin'),dict(activity_name='pkg.SCMainActivity'),
    dict(package_name='another.package'),dict(selected_tab=dict(name='life',verified=True,source='service_hierarchy_selected'))])
def test_contradictory_component_or_global_nav_drops_destination(change):
    raw=observed();owner=DestinationOwnership(raw);bad=capture(raw,1,**change)
    assert owner.assess(bad)['status']=='CONTRADICTORY_CONTEXT' and owner.invalid
    assert owner.assess(capture(raw,2))['status']=='UNRESOLVED_CONTEXT'


def test_other_plugin_body_after_recovery_cannot_rebind():
    raw=observed();owner=DestinationOwnership(raw);owner.assess(capture(raw,1),recovery_active=True)
    bad=capture(raw,2);bad['nodes'][0]['text']='Washer'
    assert owner.assess(bad)['status']=='CONTRADICTORY_CONTEXT'


def test_repeated_capture_is_not_two_fresh_observations():
    raw=observed();owner=DestinationOwnership(raw);owner.navigation(dict(kind='CLICK'),'owned-next')
    a=capture(raw,1,navigation_epoch=owner.epoch)
    owner.assess(a);owner.assess(deepcopy(a))
    assert owner.freshness=='STALE_REVALIDATABLE'


def test_initial_partial_context_keeps_independent_structural_authority():
    raw=observed('Volume');owner=DestinationOwnership(raw);a=capture(raw,1)
    assert owner.assess(a)['status']=='PARTIAL_CONTEXT' and owner.freshness=='FRESH_PARTIAL'


def test_same_activity_and_scenario_without_body_cannot_revalidate():
    raw=observed();owner=DestinationOwnership(raw);owner.navigation(dict(kind='CLICK'),'owned-next')
    for n in [1,2,3]:
        a=capture(raw,n,navigation_epoch=owner.epoch,nodes=[])
        assert owner.assess(a)['status']=='UNRESOLVED_CONTEXT'


def test_shared_generic_web_body_without_destination_title_cannot_rebind():
    raw=observed('Volume');raw['nodes'][0]['viewIdResourceName']='app';owner=DestinationOwnership(raw)
    owner.navigation(dict(kind='CLICK'),'owned-next')
    for n in [1,2,3]:owner.assess(capture(raw,n,navigation_epoch=owner.epoch))
    assert owner.freshness=='STALE_REVALIDATABLE'


def test_repeated_safe_recovery_does_not_permanently_poison_ownership():
    raw=observed();owner=DestinationOwnership(raw)
    for start in [1,4,7]:
        owner.assess(capture(raw,start),recovery_active=True)
        owner.assess(capture(raw,start+1));owner.assess(capture(raw,start+2))
        assert owner.recovery_state=='RECOVERY_REBOUND' and not owner.invalid
    assert owner.recovery_epoch==3


def test_destination_events_are_immutable_observations_not_visit_writes():
    raw=observed();original=deepcopy(raw);sink=[];owner=DestinationOwnership(raw,event_sink=sink.append)
    owner.assess(capture(raw,1));owner.navigation(dict(kind='CLICK'),'owned-next')
    owner.events[-1]['kind']='local-mutated'
    assert sink[-1]['kind']=='CONTEXT_INVALIDATED' and raw==original
    assert all('visit_credit' not in e for e in sink)


@pytest.fixture(scope='module')
def rejected():
    return json.loads((Path(__file__).parent/'fixtures/phase4c_family_dynamic_context.json').read_text(encoding='utf-8'))


def planner_pair(o, context=None, current_context=None):
    return (PlannerInput(restore_snapshot(o['snapshot']),context or o['context']['status'],history(o['history']),**o['planner_flags']),
            PlannerInput(restore_snapshot(o['current_snapshot']),current_context or resolve_phase3_context(o['current_raw'])['status'],
                history(o['current_history']),**o['current_flags']))


def test_exact_rejected_family_all_ten_old_gates(rejected):
    for row in rejected['steps']:
        o=row['observation'];a,b=planner_pair(o);rec=plan_shadow(a)
        assert rec.to_dict()==o['recommendation']
        assert execution_gate(a,rec,b,AuthorityEvidence(**o['gate_evidence']),action_limit=10).to_dict()==o['gate']
        assert row['trace']['fallback_used'] and not row['trace']['planner_executed']


def replay_family(rejected):
    owner=DestinationOwnership(rejected['entry']['raw']);results=[]
    for row in rejected['steps']:
        o=deepcopy(row['observation']);a_raw,b_raw=o['raw'],o['current_raw']
        if a_raw['navigation_epoch']!=owner.epoch:
            owner.navigation(dict(kind='BACK'),a_raw['navigation_epoch'])
        recovering=not o['gate_evidence']['recovery_clear']
        ca=owner.assess(a_raw,recovery_active=recovering);cb=owner.assess(b_raw,recovery_active=recovering)
        a,b=planner_pair(o,ca['status'],cb['status'])
        rec,gate,transition=rebind_execution(a,plan_shadow(a),b,AuthorityEvidence(**o['gate_evidence']),a_raw,b_raw,action_limit=10)
        results.append(dict(step=o['step'],allowed=gate.allowed,reason=gate.reason,transition=transition,
            before=a_raw['destination_ownership'],current=b_raw['destination_ownership']))
    return results


def test_exact_family_safe_later_steps_regain_authority(rejected):
    results=replay_family(rejected)
    assert any(r['allowed'] for r in results[2:]),results
    assert not results[1]['allowed'] and results[1]['reason']=='RECOVERY_CONFLICT'
    assert all(r['current']['freshness'] in {'FRESH_VERIFIED','FRESH_PARTIAL'} for r in results if r['allowed'])


@pytest.mark.parametrize('flag',['recovery_clear','lifecycle_clear','transport_clear','focus_coherent','enabled'])
def test_rebinding_keeps_every_existing_safety_flag(rejected,flag):
    o=deepcopy(rejected['steps'][0]['observation']);owner=DestinationOwnership(rejected['entry']['raw'])
    owner.assess(o['raw']);owner.assess(o['current_raw']);a,b=planner_pair(o)
    evidence=replace(AuthorityEvidence(**o['gate_evidence']),**{flag:False})
    _,gate,_=rebind_execution(a,plan_shadow(a),b,evidence,o['raw'],o['current_raw'],action_limit=10)
    assert not gate.allowed


def test_rebind_never_resets_budget_or_failed_execution_degrade(rejected):
    o=deepcopy(rejected['steps'][0]['observation']);owner=DestinationOwnership(rejected['entry']['raw'])
    owner.assess(o['raw']);owner.assess(o['current_raw']);a,b=planner_pair(o)
    for fields in [dict(actions_used=10),dict(degraded=True)]:
        _,gate,transition=rebind_execution(a,plan_shadow(a),b,AuthorityEvidence(**o['gate_evidence']),o['raw'],o['current_raw'],action_limit=10,**fields)
        assert not gate.allowed and not transition['rebound']


@pytest.mark.parametrize('field',['ownership_id','destination_id','scenario_id','scenario_run_id'])
def test_context_ownership_tampering_is_detected(field,rejected):
    raw=observed();owner=DestinationOwnership(raw);a=capture(raw,1);b=capture(raw,2);owner.assess(a);owner.assess(b)
    b['destination_ownership'][field]='another-owner'
    audit=dict(scenario=raw['scenario_id'],planner_executed=True,dynamic_context=dict(before=a['destination_ownership'],current=b['destination_ownership']))
    assert ownership_failures(audit)
    o,a,b=fresh_pair(rejected)
    o['current_raw']['destination_ownership'][field]='another-owner'
    _,gate,_=rebind_execution(a,plan_shadow(a),b,AuthorityEvidence(**o['gate_evidence']),o['raw'],o['current_raw'],action_limit=10)
    assert not gate.allowed and gate.reason=='DESTINATION_OWNERSHIP_UNPROVEN'


def test_navigation_observer_keeps_original_command_and_reports_boundary():
    calls=[];events=[];invalid=[]
    client=SimpleNamespace(_run=lambda command: calls.append(command) or 'original')
    command=['shell','input','keyevent','4']
    with navigation_epoch_guard(client,lambda:invalid.append(True),navigation_observer=events.append):
        assert client._run(command)=='original'
    assert calls==[command] and len(invalid)==1 and events==[dict(kind='BACK')]


def fresh_pair(rejected):
    o=deepcopy(rejected['steps'][3]['observation'])
    owner=DestinationOwnership(rejected['entry']['raw'])
    epoch=o['raw']['navigation_epoch'];owner.navigation(dict(kind='BACK'),epoch)
    from datetime import datetime,timedelta
    seed=deepcopy(rejected['entry']['raw']);base=datetime.fromisoformat(seed['timestamp'])
    for n in [1,2]:
        warm=deepcopy(seed);warm.update(navigation_epoch=epoch,capture_id=f'warm-{n}',timestamp=(base+timedelta(seconds=n)).isoformat())
        owner.assess(warm)
    ca=owner.assess(o['raw']);cb=owner.assess(o['current_raw'])
    a,b=planner_pair(o,ca['status'],cb['status'])
    # Exercise the re-entry branch, rather than an already-authorized base gate.
    snapshot=a.snapshot.to_dict();snapshot['state_id']='test-previous-state'
    a=replace(a,snapshot=restore_snapshot(snapshot))
    return o,a,b


@pytest.mark.parametrize('mutation',['missing_old_target','duplicate_old_target','old_disabled','old_unfocusable','old_unsafe'])
def test_current_replan_requires_one_safe_target_in_both_observations(rejected,mutation):
    o,a,b=fresh_pair(rejected);selected=plan_shadow(b).to_dict()['recommended_target']
    key=lambda x:{k:v for k,v in x.items() if k!='instance_id'}
    snap=a.snapshot.to_dict();matches=[c for c in snap['candidates'] if c['action_kind']=='FOCUS_TARGET' and key(c['target_identity'])==key(selected)]
    assert len(matches)==1
    if mutation=='missing_old_target':snap['candidates'].remove(matches[0])
    elif mutation=='duplicate_old_target':snap['candidates'].append(deepcopy(matches[0]))
    elif mutation=='old_disabled':matches[0]['target_semantics']['flags']['enabled']=False
    elif mutation=='old_unfocusable':matches[0]['target_semantics']['flags']['focusable']=False
    elif mutation=='old_unsafe':matches[0]['safety_hint']='UNKNOWN'
    a=replace(a,snapshot=restore_snapshot(snap))
    _,gate,_=rebind_execution(a,plan_shadow(a),b,AuthorityEvidence(**o['gate_evidence']),o['raw'],o['current_raw'],action_limit=10)
    assert not gate.allowed


def test_forged_original_recommendation_cannot_gain_rebound_authority(rejected):
    from tb_runner.phase4a_planner import ShadowRecommendation
    o,a,b=fresh_pair(rejected);selected=plan_shadow(a).to_dict();selected['reason_codes']=['FORGED']
    rec=ShadowRecommendation(json.dumps(selected))
    _,gate,transition=rebind_execution(a,rec,b,AuthorityEvidence(**o['gate_evidence']),o['raw'],o['current_raw'],action_limit=10)
    assert not gate.allowed and not transition['rebound']


def test_input_focus_without_actual_accessibility_focus_does_not_rebind(rejected):
    o,a,b=fresh_pair(rejected);snap=b.snapshot.to_dict()
    snap['strict_current_focus']['confirmed']=False
    b=replace(b,snapshot=restore_snapshot(snap))
    _,gate,_=rebind_execution(a,plan_shadow(a),b,AuthorityEvidence(**o['gate_evidence']),o['raw'],o['current_raw'],action_limit=10)
    assert not gate.allowed


def test_successful_rebinding_never_mutates_history_or_issues_actions(rejected):
    o,a,b=fresh_pair(rejected);before=deepcopy((o,a.history,b.history))
    _,gate,transition=rebind_execution(a,plan_shadow(a),b,AuthorityEvidence(**o['gate_evidence']),o['raw'],o['current_raw'],action_limit=10)
    assert gate.allowed and transition['independently_observed_target_count']==2
    assert (o,a.history,b.history)==before
