from copy import deepcopy
import json

import pytest

from state_model_fixtures import node, observation, scroll_pair
from tb_runner.canonical_json import canonical_json
from tb_runner.discovery_candidates import build_discovery_snapshot, collect_audit_inventory
from tb_runner.state_observation import build_state_observation
from tb_runner.state_registry import StateRegistry
from tools.state_discovery_churn_diagnostic import ChurnEvidenceRecorder, describe_churn


def bundle(raw, registry=None, **kwargs):
    obs=build_state_observation(raw)
    snap=build_discovery_snapshot(raw,registry if registry is not None else StateRegistry('churn-test'),**kwargs)
    return dict(record_id=obs.observation_id,raw_observation=deepcopy(raw),state_observation=obs.to_dict(),snapshot=snap.to_dict()),obs,snap


def diff(a,b,**kwargs):
    registry=StateRegistry('churn-test')
    before,_,_=bundle(a,registry)
    after,_,_=bundle(b,registry,**kwargs)
    return describe_churn(before,after,continuity=kwargs.get('continuity'))


def test_candidate_order_permutations_are_stable():
    a=observation();a['nodes'].append(node('pkg:id/other','Other','500,100,1000,200'))
    b=deepcopy(a);b['nodes'].reverse()
    result=diff(a,b)
    assert not result['hash_changed'] and not result['ADDED'] and not result['REMOVED'] and not result['CHANGED']


def test_focus_only_changes_source_provenance_without_hash_churn():
    a=observation();b=deepcopy(a)
    b['focus_node']=deepcopy(b['nodes'][0]);b['focus_node']['accessibilityFocused']=True
    result=diff(a,b)
    assert result['same_state'] and result['same_viewport'] and not result['hash_changed']
    assert result['source_delta']['CURRENT_FOCUS']['ADDED']


def test_duplicate_producer_arrival_and_provenance_order_are_stable():
    raw=observation();inventory=collect_audit_inventory(raw)
    extra=deepcopy(inventory[0]);extra['source']='another-producer'
    a,_,_=bundle(raw,audit_inventory=inventory+[extra,extra])
    b,_,_=bundle(raw,audit_inventory=[extra,*reversed(inventory)])
    assert a['snapshot']['candidate_set_hash']==b['snapshot']['candidate_set_hash']
    assert a['snapshot']['candidates']==b['snapshot']['candidates']


@pytest.mark.parametrize('change',['timestamp','step','scenario','measurement','focus'])
def test_volatile_metadata_does_not_enter_behavior_hash(change):
    a=observation();a['nodes'][0]['text']='battery 74%';b=deepcopy(a)
    if change=='timestamp':b['timestamp']='2099-01-02T03:04:05Z'
    elif change=='step':b['step']=98765
    elif change=='scenario':b['scenario_id']='different-diagnostic-entry'
    elif change=='measurement':b['nodes'][0]['text']='battery 73%'
    else:b['nodes'][0].update(focused=True,accessibilityFocused=True)
    result=diff(a,b)
    assert not result['hash_changed'] and result['same_state'] and result['same_viewport']


def test_passive_same_state_same_viewport_repeats_byte_stable_candidates():
    raw=observation();registry=StateRegistry('churn-test')
    candidates=[]
    for i in range(12):
        document,_,_=bundle(raw,registry)
        candidates.append(canonical_json(document['snapshot']['candidates']))
    assert len(set(candidates))==1


def test_scroll_diff_keeps_both_semantic_deltas_and_valid_equality():
    a,b,_,proof=scroll_pair()
    result=diff(a,b,continuity=proof)
    assert result['hash_changed'] and result['same_state'] and not result['same_viewport']
    assert result['equality']['logical_state_equal'] is True
    assert result['ADDED'] and result['REMOVED']
    assert result['source_delta']['ACCESSIBILITY_TREE']['ADDED']
    assert result['classification']=='UNKNOWN' and result['expected'] is None


def test_real_enabled_availability_change_is_not_hidden():
    a=observation();b=deepcopy(a);b['nodes'][0]['enabled']=False
    result=diff(a,b)
    assert result['hash_changed'] and not result['same_state']
    assert result['equality']['verdict']=='DIFFERENT'
    before=next(c for c in result['semantic_diff']['removed'] if c['action_kind']=='CLICK' and c['target_identity']['resource_id']=='pkg:id/card')
    after=next(c for c in result['semantic_diff']['added'] if c['action_kind']=='CLICK' and c['target_identity']['resource_id']=='pkg:id/card')
    assert before['target_identity']['bounds']==after['target_identity']['bounds']
    assert before['eligibility']['availability']=='AVAILABLE' and after['eligibility']['availability']=='DISABLED'


def test_ambiguous_state_never_unsafe_binds():
    raw=observation();raw['activity_name']=None
    document,_,snap=bundle(raw)
    assert snap.state_id is None and all(c.state_id is None for c in snap.candidates)
    assert document['snapshot']['binding_status']=='UNRESOLVED'


def test_snapshot_serialization_key_order_and_export_copies_are_byte_stable():
    _,_,snap=bundle(observation())
    original=snap.to_json();a=snap.to_dict();b=dict(reversed(list(a.items())))
    assert canonical_json(a)==canonical_json(b)==original
    a['candidates'].clear()
    assert snap.to_json()==original


@pytest.mark.parametrize('offset',[1,2,3])
def test_bounds_jitter_is_explicit_positional_delta_not_silently_coalesced(offset):
    a=observation();b=deepcopy(a)
    b['nodes'][0]['boundsInScreen']=f'{offset},100,{500+offset},200'
    result=diff(a,b)
    assert result['same_state'] and result['hash_changed'] and result['ADDED'] and result['REMOVED']
    assert result['classification']=='UNKNOWN'
    # Phase 0 exact instance distinction is retained; this is not hash bypass.
    assert result['semantic_diff']['added'][0]['target_identity']['bounds']!=result['semantic_diff']['removed'][0]['target_identity']['bounds']


def test_recorder_persists_both_observations_before_an_assertion_failure(tmp_path):
    recorder=ChurnEvidenceRecorder(tmp_path/'run');registry=StateRegistry('churn-test')
    a=observation();b=deepcopy(a);b['nodes'][0]['enabled']=False
    _,obs,snap=bundle(a,registry);before=recorder.record(a,obs,snap)
    _,obs,snap=bundle(b,registry);after=recorder.record(b,obs,snap)
    path=recorder.compare(before,after)
    with pytest.raises(AssertionError):assert not json.loads(path.read_text())['hash_changed']
    doc=json.loads(path.read_text())
    for name in ('before','after'):
        reference=doc['evidence_references'][name]
        saved=json.loads((recorder.directory/reference['file']).read_text())
        assert saved['raw_observation'] and saved['state_observation'] and saved['snapshot']['candidates']
        assert saved['candidate_ids']
    assert doc['semantic_diff']['added'] and doc['semantic_diff']['removed']


def test_comparison_exception_does_not_remove_raw_evidence(tmp_path,monkeypatch):
    import tools.state_discovery_churn_diagnostic as tool
    recorder=ChurnEvidenceRecorder(tmp_path/'run');raw=observation();_,obs,snap=bundle(raw)
    ids=[recorder.record(raw,obs,snap) for _ in range(2)]
    def fail(*args,**kwargs):raise RuntimeError('injected comparison failure')
    monkeypatch.setattr(tool,'describe_churn',fail)
    with pytest.raises(RuntimeError):recorder.compare(*ids)
    assert all((recorder.directory/(key+'.json')).is_file() for key in ids)


def test_corrupt_evidence_is_rejected_and_original_record_not_rewritten(tmp_path):
    recorder=ChurnEvidenceRecorder(tmp_path/'run');raw=observation();_,obs,snap=bundle(raw)
    ids=[recorder.record(raw,obs,snap) for _ in range(2)]
    path=recorder.directory/(ids[1]+'.json');path.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='checksum'):recorder.compare(*ids)
    assert (recorder.directory/(ids[0]+'.json')).is_file()


def test_unknown_change_requires_reviewed_rationale_and_preserves_refs(tmp_path):
    recorder=ChurnEvidenceRecorder(tmp_path/'run');registry=StateRegistry('churn-test')
    a=observation();b=deepcopy(a);b['nodes'][0]['enabled']=False
    _,o,s=bundle(a,registry);x=recorder.record(a,o,s)
    _,o,s=bundle(b,registry);y=recorder.record(b,o,s)
    path=recorder.compare(x,y);original=json.loads(path.read_text())
    with pytest.raises(ValueError):recorder.classify(path,'REAL_UI_AVAILABILITY_CHANGE',expected=True,rationale='')
    recorder.classify(path,'REAL_UI_AVAILABILITY_CHANGE',expected=True,rationale='Observed enabled true -> false at the same target')
    result=json.loads(path.read_text())
    assert result['expected'] and result['evidence_references']==original['evidence_references']


def test_existing_run_directory_is_never_overwritten(tmp_path):
    folder=tmp_path/'run';folder.mkdir();p=folder/'existing.json';p.write_text('preserve')
    with pytest.raises(ValueError,match='empty'):ChurnEvidenceRecorder(folder)
    assert p.read_text()=='preserve'
