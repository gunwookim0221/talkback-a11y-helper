import pytest
from tb_runner.scroll_reliability import scroll_axis,capability,viewport
from tb_runner.content_terminal import ContentTerminal
from tb_runner.completeness import candidate,reconcile
from tb_runner.traversal_reliability import instance_id

@pytest.mark.parametrize('cls,actions,axis',[
    ('HorizontalScrollView',[],'HORIZONTAL'),('RecyclerView',[],'VERTICAL'),('ViewPager',[4096],'PAGER'),
    ('android.view.View',[4096,16908345,16908347],'HORIZONTAL'),('android.view.View',[4096],'UNKNOWN'),
    ('android.view.View',[16908346,16908345],'BIDIRECTIONAL'),('RecyclerView',[16908345],'HORIZONTAL')])
def test_axis(cls,actions,axis):
    assert scroll_axis(dict(className=cls,actions=actions))[0]==axis

def container(cls='GridView',forward=False,actions=()):
    return dict(className=cls,isScrollable=True,path='0.1',boundsInScreen='0,0,1000,1000',
                scroll_forward_supported=forward,actions=list(actions))

def test_horizontal_forward_never_contaminates_vertical_end():
    caps=[container(),container('android.view.View',True,[16908345,16908347,4096])]
    c=capability([],dict(canScrollDown=True),caps)
    assert c['can_scroll_forward'] is False and c['horizontal_can_scroll_forward'] is True
    assert c['legacy_axis_filtered'] and not c['contradictory']
    assert c['container']['axis']=='VERTICAL'

def test_unknown_axis_blocks_false_completion():
    c=capability([],dict(canScrollDown=False),[container(),container('android.view.View',True,[4096])])
    assert c['can_scroll_forward'] is None and c['unknown_axis_containers']==1

def test_vertical_forward_is_preserved():
    assert capability([],dict(canScrollDown=True),[container(forward=True)])['can_scroll_forward'] is True

def test_axis_payload_survives_helper_transport(monkeypatch):
    import json
    from talkback_lib import A11yAdbClient
    client=A11yAdbClient(start_monitor=False);broadcast={}
    monkeypatch.setattr(client,'check_helper_status',lambda dev=None:True)
    monkeypatch.setattr(client,'clear_logcat',lambda dev=None:'')
    monkeypatch.setattr(client,'_broadcast',lambda dev,action,extras:broadcast.update(extras=extras) or '')
    payload=dict(algorithmVersion='test',scrollAxisContract='axis-v1',canScrollDown=False,nodes=[{'text':'node'}],
                 scrollCapabilities=[dict(container('android.view.View',True,[16908345,16908347]),axis='HORIZONTAL',axis_source='directional_actions',vertical_can_scroll_forward=False)])
    monkeypatch.setattr(client._logcat_reader,'dump_raw_filtered',lambda dev=None:
        f'DUMP_TREE_RESULT {broadcast["extras"][2]} '+json.dumps(payload))
    assert client.dump_tree(dev='SERIAL',wait_seconds=.1,include_scroll_capabilities=True)==[{'text':'node'}]
    assert client.last_dump_metadata['scrollAxisContract']=='axis-v1'
    assert client.last_scroll_capabilities[0]['axis']=='HORIZONTAL'
    assert capability([],client.last_dump_metadata,client.last_scroll_capabilities)['vertical_can_scroll_forward'] is False

def test_bidirectional_forward_does_not_substitute_for_directional_down():
    c=capability([],dict(canScrollDown=False),[container('android.view.View',True,[4096,16908344,16908347])])
    assert c['can_scroll_forward'] is False and not c['contradictory']
    assert c['horizontal_can_scroll_forward'] is True
    c=capability([],dict(canScrollDown=True),[container('android.view.View',True,[4096,16908344,16908347])])
    assert c['can_scroll_forward'] is False and c['legacy_axis_filtered']
    c=capability([],dict(canScrollDown=True),[container('android.view.View',True,[4096,16908346,16908347])])
    assert c['can_scroll_forward'] is True

def nodes(offset=0,duplicate=False,state_label=False):
    result=[]
    for i in range(4):
        result.append(dict(viewIdResourceName='card' if duplicate else f'card{i}',text='Same' if duplicate else f'Card{i}',
                           className='TextView',boundsInScreen=f'10,{100+i*100+offset},110,{150+i*100+offset}',focusable=True,clickable=False))
    if state_label:
        result[3]['stableLogicalId']='object-status';result[3]['text']='Updated' if offset else 'Previous'
    return result

def obs(ns,forward=False):
    cap=capability(ns,dict(canScrollDown=forward),[container(forward=forward)])
    return dict(nodes=ns,capability=cap,viewport=viewport(ns,'s'))

def proof(n):
    return dict(scenario_id='s',actual_focus_resource_id=n['viewIdResourceName'],actual_focus_bounds=n['boundsInScreen'],
                actual_focus_visible=n['text'],actual_focus_accessibility_focused=True,physical_visited=True)

def pair(ns=None,shifted=None):
    t=ContentTerminal('s');old=ns or nodes();new=shifted or nodes(-50)
    t.observe(obs(old),0);t.observe(obs(new),1)
    return t,old,new

def test_relocated_old_alias_stale_and_successor_obligation_retained():
    t,old,new=pair()
    assert len(t.lifecycle.aliases)==4
    assert t.latest['historical_unseen_count']==8 and t.latest['active_unseen']==4
    assert t.latest['visited_candidates']==0
    assert {r['relation'] for r in t.lifecycle.events}=={'RELOCATED_AFTER_SCROLL'}
    assert {r['lifecycle'] for r in t.artifact('content_no_progress',1)['records']}=={'STALE','ACTIVE'}

def test_duplicate_same_label_id_siblings_never_merge():
    t,_,_=pair(nodes(duplicate=True),nodes(-50,duplicate=True))
    assert not t.lifecycle.aliases and t.latest['active_unseen']==8

def test_absence_alone_does_not_retire_unseen():
    t,_,_=pair(shifted=[nodes()[0]])
    assert not t.lifecycle.aliases and t.latest['active_unseen']==4

def test_genuinely_distinct_labels_not_merged():
    new=nodes(-50)
    for n in new: n['text']='Different '+n['text']
    t,_,_=pair(shifted=new)
    assert not t.lifecycle.aliases and t.latest['active_unseen']==8

def test_single_object_motion_is_not_enough():
    t,_,_=pair([nodes()[0]],[nodes(-50)[0]])
    assert not t.lifecycle.aliases

def test_horizontal_motion_is_diagnosed_without_vertical_aliases():
    from tb_runner.candidate_lifecycle import relocation_cohort
    old={instance_id(candidate(n,'s')):candidate(n,'s') for n in nodes()}
    shifted=nodes()
    for n in shifted:
        b=[int(v) for v in n['boundsInScreen'].split(',')];b[0]+=100;b[2]+=100
        n['boundsInScreen']=','.join(map(str,b))
    new={instance_id(candidate(n,'s')):candidate(n,'s') for n in shifted}
    pairs,movement=relocation_cohort(old,new)
    assert not pairs and movement['axis']=='HORIZONTAL' and movement['matched_objects']==4

def test_missing_snapshot_breaks_relocation_evidence_chain():
    t=ContentTerminal('s');t.observe(obs(nodes()),0)
    t.observe(dict(nodes=[],capability={},viewport={'valid':False}),1)
    t.observe(obs(nodes(-50)),2)
    assert not t.lifecycle.aliases and t.latest['active_unseen']==8

def test_changed_label_without_stable_logical_token_retains_obligation():
    new=nodes(-50);new[3]['text']='Changed'
    t,_,_=pair(shifted=new)
    assert len(t.lifecycle.aliases)==3 and t.latest['active_unseen']==5

def test_current_and_old_objects_both_visible_no_alias():
    t,_,_=pair(shifted=nodes()+nodes(-50))
    assert not t.lifecycle.aliases

def test_reappearance_reactivates_stale_and_no_cycles():
    t,old,new=pair()
    t.observe(obs(old),2)
    assert set(t.lifecycle.aliases)=={instance_id(candidate(n,'s')) for n in new}
    assert not any(k==t.lifecycle.successor(k) for k in t.lifecycle.aliases)

def test_real_focus_old_covers_logical_successor_without_new_actual_credit():
    t=ContentTerminal('s');old,new=nodes(),nodes(-50)
    t.observe(obs(old),0,[proof(n) for n in old])
    t.observe(obs(new),1,[proof(n) for n in old]);t.observe(obs(new),2,[proof(n) for n in old])
    assert t.latest['active_unseen']==0 and t.latest['visited_candidates']==4
    assert t.decision()=='content_completed'
    assert all(instance_id(candidate(n,'s')) not in t.visited for n in new)

def test_stale_only_unseen_completes_after_actual_successors_visited():
    t,old,new=pair()
    t.observe(obs(new),2,[proof(n) for n in new])
    assert t.latest['historical_unseen_count']==4 and t.latest['active_unseen']==0
    assert t.latest['visited_candidates']==4 and t.decision()=='content_completed'

def test_active_unseen_forbids_completion_despite_stale_retirement():
    t,_,new=pair();t.observe(obs(new),2,[proof(new[0])])
    assert t.latest['active_unseen']==3 and t.decision()!='content_completed'

def test_stable_logical_token_and_cohort_allow_state_refresh():
    t,_,_=pair(nodes(state_label=True),nodes(-50,state_label=True))
    assert len(t.lifecycle.aliases)==4

def test_horizontal_only_remaining_allows_vertical_terminal():
    ns=nodes();c=capability(ns,dict(canScrollDown=False),[container('HorizontalScrollView',True)])
    t=ContentTerminal('s')
    for step in range(2): t.observe(dict(nodes=ns,capability=c,viewport=viewport(ns,'s')),step,[proof(n) for n in ns])
    assert t.decision()=='content_completed' and t.latest['horizontal_can_scroll_forward']

def test_completeness_stale_not_missed_or_actual():
    t,old,new=pair()
    c=reconcile('s',[],[],observations=[obs(old),obs(new)],stale_aliases=t.lifecycle.aliases)
    assert c['summary']['completeness_stale']==4 and c['summary']['completeness_actual_visited']==0
    assert c['summary']['completeness_missed']==4 and c['summary']['completeness_expected']==4
    assert len(c['expected_instances'])==4
