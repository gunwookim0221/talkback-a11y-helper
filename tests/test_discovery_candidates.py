from copy import deepcopy
import json

import pytest

from state_model_fixtures import node, observation, scroll_pair
from tb_runner import completeness, scroll_reliability
from tb_runner.canonical_json import canonical_json
from tb_runner.discovery_candidates import (
    ACTION_INVENTORY, build_discovery_snapshot, build_fingerprint_only_snapshot,
    candidate_set_delta, collect_audit_inventory, write_discovery_snapshot,
)
from tb_runner.scenario_config import BOTTOM_TAB_GLOBAL_NAV
from tb_runner.state_observation import build_state_observation
from tb_runner.state_registry import StateRegistry


def rows(snapshot,kind=None):
    return [c.to_dict() for c in snapshot.candidates if kind is None or c.action_kind==kind]


def snapshot(raw=None,registry=None,**kwargs):
    return build_discovery_snapshot(raw or observation(),registry if registry is not None else StateRegistry("test-discovery"),**kwargs)


def nav_observation(root="home"):
    raw=observation(root)
    names=("home","devices","life","routines","menu")
    raw['nodes']=[node(),*[node(rid,label,f'{i*200},900,{i*200+200},1000',role='tab',selected=name==root)
        for i,(name,label,rid) in enumerate(zip(names,BOTTOM_TAB_GLOBAL_NAV['labels'],BOTTOM_TAB_GLOBAL_NAV['resource_ids']))]]
    return raw


def test_same_observation_has_same_ids_and_fresh_serialization():
    a,b=snapshot(),snapshot()
    assert a.to_json()==b.to_json()
    registry=StateRegistry("test-discovery")
    first,second=snapshot(registry=registry),snapshot(registry=registry)
    assert first.state_id==second.state_id
    assert first.candidate_set_hash==second.candidate_set_hash
    assert {c.candidate_id for c in first.candidates}=={c.candidate_id for c in second.candidates}


def test_input_order_and_duplicate_nodes_do_not_change_candidate_set():
    raw=observation();raw['nodes'].append(node('pkg:id/other','Other','500,100,1000,200'))
    other=deepcopy(raw);other['nodes'].reverse()
    assert snapshot(raw).candidate_set_hash==snapshot(other).candidate_set_hash
    other['nodes'].append(deepcopy(other['nodes'][0]))
    assert snapshot(raw).candidate_set_hash==snapshot(other).candidate_set_hash


def test_focus_churn_changes_provenance_not_action_identity():
    raw=observation();other=deepcopy(raw)
    raw['focus_node']=deepcopy(raw['nodes'][0]);raw['focus_node']['accessibilityFocused']=True
    other['focus_node']=deepcopy(other['nodes'][1]);other['focus_node']['accessibilityFocused']=True
    raw['nodes'][0]['focused']=True;other['nodes'][1]['accessibilityFocused']=True
    registry=StateRegistry("test-discovery")
    a,b=snapshot(raw,registry),snapshot(other,registry)
    assert candidate_set_delta(a,b)['CANDIDATE_SET_STABLE'] is True
    assert a.to_dict()['strict_current_focus']['confirmed'] is True
    assert all(c['physical_visit_credited'] is False for c in rows(b))


def test_state_binding_root_guard_and_distinct_action_kinds():
    registry=StateRegistry("test-discovery")
    a,b=snapshot(observation(),registry),snapshot(observation('devices'),registry)
    assert a.state_id!=b.state_id
    assert all(c.state_id==a.state_id for c in a.candidates)
    assert all(c.state_id==b.state_id for c in b.candidates)
    target=rows(a,'CLICK')[0]['target_identity']
    focus=next(c for c in rows(a,'FOCUS_TARGET') if c['target_identity']==target)
    assert focus['candidate_id']!=rows(a,'CLICK')[0]['candidate_id']
    assert candidate_set_delta(a,b)['comparable'] is False


def test_same_resource_id_multiple_bounds_preserved():
    raw=observation();raw['nodes'].append(node(bounds='500,100,1000,200'))
    click=rows(snapshot(raw),'CLICK')
    same=[c for c in click if c['target_identity']['resource_id']=='pkg:id/card']
    assert len(same)==2 and len({c['candidate_id'] for c in same})==2


def test_global_nav_five_destinations_reuse_verified_contract():
    raw=nav_observation();a,b=snapshot(raw),snapshot(deepcopy(raw))
    nav=rows(a,'BOTTOM_NAV')
    assert {c['target_identity']['destination'] for c in nav}=={'home','devices','life','routines','menu'}
    assert len(nav)==5 and a.candidate_set_hash==b.candidate_set_hash
    assert next(c for c in nav if c['target_identity']['destination']=='home')['eligibility']['availability']=='ALREADY_SELECTED'
    assert all(c['safety_hint']=='NAVIGATION' and c['eligibility']['auto_activation_allowed'] is False for c in nav)


@pytest.mark.parametrize('axis,fields,kinds',[
    ('VERTICAL',dict(scroll_forward_supported=True,scroll_backward_supported=True),{'SCROLL_FORWARD_VERTICAL','SCROLL_BACKWARD_VERTICAL'}),
    ('HORIZONTAL',dict(scroll_right_supported=True,scroll_left_supported=True),{'SCROLL_FORWARD_HORIZONTAL','SCROLL_BACKWARD_HORIZONTAL'}),
    ('BIDIRECTIONAL',dict(scroll_right_supported=True,scroll_down_supported=True),{'SCROLL_FORWARD_HORIZONTAL','SCROLL_FORWARD_VERTICAL'}),
    ('BIDIRECTIONAL',dict(scroll_forward_supported=True),set()),
    ('UNKNOWN',dict(scroll_forward_supported=True),set()),
    ('PAGER',dict(scroll_forward_supported=True),set()),
])
def test_scroll_axes_and_generic_forward_never_invent_dimension(axis,fields,kinds):
    raw=observation();container=dict(className='android.widget.ScrollView',boundsInScreen='0,0,1000,900',axis=axis,axis_source='directional_actions',**fields)
    raw['capability']=dict(axis_contract='axis-v1',source='helper_metadata',containers=[container],contradictory=False)
    result=snapshot(raw)
    assert {c.action_kind for c in result.candidates if c.action_kind.startswith('SCROLL_')}==kinds
    for c in rows(result): assert c['eligibility']['auto_activation_allowed'] is False


@pytest.mark.parametrize('mutation',['contradiction','missing_contract','invalid_bounds','disabled','invisible'])
def test_scroll_capability_fails_closed(mutation):
    raw=observation();container=dict(className='ScrollView',boundsInScreen='0,0,1000,900',axis='VERTICAL',scroll_forward_supported=True)
    cap=dict(axis_contract='axis-v1',source='helper_metadata',containers=[container],contradictory=False)
    raw['capability']=cap
    if mutation=='contradiction':cap['contradictory']=True
    elif mutation=='missing_contract':cap.pop('axis_contract')
    elif mutation=='invalid_bounds':container['boundsInScreen']='bad'
    elif mutation=='disabled':container['isEnabled']=False
    elif mutation=='invisible':container['isVisibleToUser']=False
    assert not any(c.action_kind.startswith('SCROLL_') for c in snapshot(raw).candidates)


@pytest.mark.parametrize('a,b',[
    ('23°C','24°C'),('battery 74%','battery 73%'),('time 10:31','time 10:32'),
    ('Find, KOR003, last location check: 59 minutes ago','Find, KOR003, last location check: now'),
])
def test_typed_volatile_measurements_do_not_churn(a,b):
    raw=observation();raw['nodes'][0]=node('pkg:id/map_area',a)
    other=deepcopy(raw);other['nodes'][0]['text']=b
    registry=StateRegistry('test-discovery')
    first,second=snapshot(raw,registry),snapshot(other,registry)
    assert candidate_set_delta(first,second)['CANDIDATE_SET_STABLE'] is True


@pytest.mark.parametrize('a,b',[('Locked','Unlocked'),('Connected','Disconnected')])
def test_meaningful_state_changes_are_not_masked(a,b):
    raw=observation();raw['nodes'][0]['text']=a
    other=deepcopy(raw);other['nodes'][0]['text']=b
    registry=StateRegistry('test-discovery')
    first,second=snapshot(raw,registry),snapshot(other,registry)
    assert first.state_id!=second.state_id
    assert {c['target_semantics'].get('semantic_value') for c in rows(first,'CLICK')}!={c['target_semantics'].get('semantic_value') for c in rows(second,'CLICK')}


def test_disabled_control_availability_and_unlabeled_actionable():
    raw=observation();raw['nodes'][0]['enabled']=False
    assert any(c['eligibility']['availability']=='DISABLED' for c in rows(snapshot(raw),'CLICK'))
    raw['nodes'][0]['text']=''
    assert any(c['evidence']['eligibility_reason']=='actionable_without_label' for c in rows(snapshot(raw)))


@pytest.mark.parametrize('kind',['activity','context','popup','collision','empty'])
def test_ambiguous_state_never_binds_candidates_to_existing_state(kind):
    raw=observation();registry=StateRegistry('test-discovery');first=snapshot(raw,registry)
    other=deepcopy(raw)
    if kind=='activity':other['activity_name']=None
    elif kind=='context':other['navigation_context']=None;other['selected_tab']=None;other['nodes'][1]['selected']=False
    elif kind=='popup':other['selected_tab']=None;other['navigation_context']=None;other['nodes']=[node('dialog','Choice')];other['overlay']={'kind':'unknown','observed':False}
    elif kind=='collision':other['nodes'][0]['text']='Unknown subpage'
    elif kind=='empty':other['nodes']=[]
    result=snapshot(other,registry)
    assert result.state_id is None
    assert all(c.state_id is None for c in result.candidates)
    assert result.to_dict()['binding_status']=='UNRESOLVED'
    assert registry.state_count==1


def test_fingerprint_without_secondary_has_no_definitive_action_set():
    registry=StateRegistry('test-discovery')
    result=build_fingerprint_only_snapshot(build_state_observation(observation()).fingerprint.to_dict(),registry)
    assert result.state_id is None and result.candidates==() and registry.state_count==0


@pytest.mark.parametrize('focused,a11y',[(True,False),(False,False),(True,None)])
def test_input_only_and_false_focus_never_gain_focus_or_visit_semantics(focused,a11y):
    raw=observation();raw['focus_node']=node(focused=focused,accessibilityFocused=a11y)
    result=snapshot(raw)
    assert result.to_dict()['strict_current_focus']['confirmed'] is False
    assert all('CURRENT_FOCUS' not in c['source'] for c in rows(result))
    assert result.to_dict()['visit_credit']==0


def test_focus_flags_do_not_create_focus_target():
    raw=observation();raw['nodes'][0].update(focusable=False,clickable=False,focused=True,accessibilityFocused=False)
    result=snapshot(raw)
    assert not any(c['target_identity'].get('resource_id')=='pkg:id/card' for c in rows(result,'FOCUS_TARGET'))


@pytest.mark.parametrize('proof',[
    {'actual_focus_accessibility_focused':False},
    {'focus_transition_status':'AMBIGUOUS'},
    {'focus_reconciliation_confidence':'ambiguous'},
    {'physical_visited':False},
])
def test_conflicting_or_ambiguous_focus_proof_is_not_promoted(proof):
    raw=observation();raw['focus_node']=node(accessibilityFocused=True);raw.update(proof)
    result=snapshot(raw)
    assert result.to_dict()['strict_current_focus']['confirmed'] is False
    assert all('CURRENT_FOCUS' not in c['source'] for c in rows(result))


def test_plugin_producer_ids_and_label_dedup_do_not_replace_instances(monkeypatch):
    from tb_runner import plugin_card_discovery
    raw=observation('devices');raw['nodes'].append(node(bounds='500,100,1000,200'))
    first=snapshot(raw)
    monkeypatch.setattr(plugin_card_discovery,'discover_device_cards',lambda nodes:[
        {'id':'arbitrary-plugin-ordinal','bounds':'0,100,500,200','resource_id':'pkg:id/card','type':'device'}])
    second=snapshot(raw)
    assert second.candidate_set_hash==first.candidate_set_hash
    same=[c for c in rows(second,'CLICK') if c['target_identity']['resource_id']=='pkg:id/card']
    assert len(same)==2 and sum('PLUGIN_NAVIGATION' in c['source'] for c in same)==1


def test_scroll_records_actual_support_signal_not_only_requested_direction():
    raw=observation();raw['capability']={'axis_contract':'axis-v1','source':'helper_metadata',
        'containers':[{'className':'ScrollView','boundsInScreen':'0,0,1000,900','axis':'VERTICAL','scroll_forward_supported':True}]}
    scroll=rows(snapshot(raw),'SCROLL_FORWARD_VERTICAL')[0]
    assert scroll['evidence']['supporting_signals']==['scroll_forward_supported']
    assert scroll['evidence']['requested_direction']=='scroll_down_supported'


def test_audit_producer_is_read_only_and_requires_current_target_and_state():
    raw=observation();item=completeness.candidate(raw['nodes'][0],'synthetic')
    old=deepcopy(item);old['bounds']='0,400,500,500'
    foreign=deepcopy(item);foreign['state_id']='another-state'
    inventory=[item,old,foreign];saved=deepcopy(inventory);saved_raw=deepcopy(raw)
    result=snapshot(raw,audit_inventory=inventory)
    assert inventory==saved and raw==saved_raw
    assert any('AUDIT_EXPECTED' in c['source'] for c in rows(result))
    assert {r['reason'] for r in result.to_dict()['excluded']} >= {'STATE_SCOPE_MISMATCH','NOT_CURRENT_OBSERVATION'}


def test_existing_v7_producer_is_reused_without_a_device_or_ledger(monkeypatch):
    from tb_runner import collection_flow
    original=collection_flow._register_focusable_inventory_node
    calls=[]
    def producer(sink,**kwargs):
        calls.append((sink,kwargs));return original(sink,**kwargs)
    monkeypatch.setattr(collection_flow,'_register_focusable_inventory_node',producer)
    raw=observation();before=deepcopy(raw)
    inventory=collect_audit_inventory(raw)
    assert len(calls)==len(raw['nodes']) and inventory
    assert raw==before and not hasattr(calls[0][0],'move_focus_smart')
    assert any('AUDIT_EXPECTED' in c['source'] for c in rows(snapshot(raw)))


def test_v7_input_focus_hint_does_not_override_tree_action_support():
    raw=observation();raw['nodes'][0].update(focusable=False,clickable=False,focused=True)
    inventory=collect_audit_inventory(raw)
    assert any(i['view_id']=='pkg:id/card' and i['focusable'] for i in inventory)
    assert not any(c['target_identity'].get('resource_id')=='pkg:id/card' for c in rows(snapshot(raw),'FOCUS_TARGET'))


def test_stale_lifecycle_requires_same_state_and_epoch():
    raw=observation();registry=StateRegistry('test-discovery');first=snapshot(raw,registry)
    record=completeness.candidate(raw['nodes'][0],'synthetic')
    record.update(state_id=first.state_id,observation_id=first.to_dict()['observation_id'],lifecycle='STALE')
    before=deepcopy(record)
    result=snapshot(raw,registry,lifecycle_records=[record])
    assert not any(c['target_identity'].get('resource_id')=='pkg:id/card' for c in rows(result))
    assert record==before
    record['state_id']='foreign'
    result=snapshot(raw,registry,lifecycle_records=[record])
    assert any(c['target_identity'].get('resource_id')=='pkg:id/card' for c in rows(result))
    assert any(x['reason']=='UNVERIFIED_LIFECYCLE_SCOPE' for x in result.to_dict()['excluded'])


def test_conflicting_same_position_target_is_not_last_write_wins():
    raw=observation();other=deepcopy(raw['nodes'][0]);other['text']='Different target';raw['nodes'].append(other)
    result=snapshot(raw)
    assert result.to_dict()['candidate_id_collision_count']==1
    assert not any(c['target_identity'].get('resource_id')=='pkg:id/card' for c in rows(result))
    raw['nodes'].reverse()
    assert snapshot(raw).candidate_set_hash==result.candidate_set_hash


def test_serialization_copies_and_jsonl_bytes(tmp_path):
    result=snapshot();original=result.to_json();doc=result.to_dict();doc['candidates'].clear()
    assert result.to_json()==original and result.candidates
    p=tmp_path/'discovery_candidates.jsonl';write_discovery_snapshot(p,result);write_discovery_snapshot(p,result)
    assert p.read_bytes()==((original+'\n')*2).encode('utf-8')
    assert json.loads(original)['candidate_set_hash']==result.candidate_set_hash


def test_existing_visit_ledger_and_audit_rows_are_not_mutated(monkeypatch):
    from tb_runner.traversal_orchestration import VisitTracker
    def forbidden(**kwargs):
        raise AssertionError('Discovery invoked the runtime visit tracker')
    monkeypatch.setattr(VisitTracker,'resolve',forbidden)
    raw=observation()
    raw['traversal_ledger']={'visited_instance_ids':['existing-visit'],'unique_visited':1,'attempted':3}
    saved=deepcopy(raw)
    result=snapshot(raw)
    assert raw==saved
    assert result.to_dict()['visit_credit']==0 and result.to_dict()['action_executed'] is False


def test_scroll_same_logical_state_has_explainable_candidate_delta():
    a,b,transition,proof=scroll_pair();registry=StateRegistry('test-discovery')
    first=snapshot(a,registry);second=snapshot(b,registry,continuity=proof)
    delta=candidate_set_delta(first,second)
    assert first.state_id==second.state_id and delta['comparable'] is True
    assert first.to_dict()['viewport_signature']!=second.to_dict()['viewport_signature']
    assert delta['NEW_CANDIDATE']>0 and delta['REMOVED_CANDIDATE']>0


def test_inventory_reserves_future_actions_without_executors():
    assert ACTION_INVENTORY['MORE'][0]=='FUTURE'
    assert ACTION_INVENTORY['EXPAND'][0]=='FUTURE'
    assert ACTION_INVENTORY['BACK'][0]=='UNSAFE_FOR_AUTO_ACTIVATION'


@pytest.mark.parametrize('producer',[{},[None]])
def test_invalid_producer_payload_rejected_before_registry_mutation(producer):
    registry=StateRegistry('test-discovery')
    with pytest.raises(ValueError):snapshot(registry=registry,audit_inventory=producer)
    assert registry.observation_count==0
