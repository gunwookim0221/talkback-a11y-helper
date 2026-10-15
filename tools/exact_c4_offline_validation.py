"""Prepare preserved B3 input for the actual Kotlin resolver; no device or action RPC."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from talkback_lib.exact_node_protocol import build_target_descriptor,create_resolve_request
from tools.phase5d_c_offline_replay import TARGETS,find_raw_path,load_capture,pairwise_result

BASE=ROOT/'out/phase5d_b3_helper_refresh_20261015/resume2'
OUTPUT=ROOT/'out/phase5d_c4_20261016/offline_input.json'

def generate():
    raw={};meta={}
    for label in 'ABC':raw[label],meta[label]=load_capture(BASE,label)
    pairwise={f'{a}_to_{b}':{name:pairwise_result(meta[a],meta[b],rid) for name,rid in TARGETS.items()}
        for a,b in [('A','B'),('B','C'),('A','C')]}
    for pair in pairwise.values():assert all(row['resolved'] for row in pair.values())
    rows=[]
    for index,(name,rid) in enumerate(TARGETS.items()):
        matches=[(i,w) for i,w in enumerate(raw['B']['windows']) if w.get('type')==1]
        paths=[find_raw_path(raw['B'],rid,w['id']) for _,w in matches]
        paths=[p for p in paths if p is not None];assert len(paths)==1
        wi,path,node=paths[0]
        descriptor=build_target_descriptor(raw['B'],window_index=wi,child_indices=path,snapshot_id=meta['B']['snapshot']['snapshot_id'])
        def descendants(n):return sum(int(c.get('clickable',False) or any(a.get('id')==16 for a in c.get('actions',[])))+descendants(c) for c in n.get('children',[]))
        child_count=descendants(node)
        mutation=name in {'Away','Stay','Disarmed'}
        clazz='STATE_MUTATION_CONTROL' if mutation else 'MIXED_ACTION_CONTAINER' if child_count else 'UNKNOWN_ACTIONABLE'
        request=create_resolve_request(descriptor,request_id=f'c4-offline:{name}',transaction_id=f'c4-tx:{name}',
            permit_id=f'c4-permit:{name}',request_nonce=f'c4-nonce:{name}',ownership=dict(run_id='preserved:B3',scenario_id='life_home_monitor_plugin',
            scenario_transaction_id='offline:c4',step_action_id=f'target:{index}',parent_action_id=None),
            authorized_snapshot_id=meta['A']['snapshot']['snapshot_id'],helper_service_instance_id='preserved-helper-B3',
            host_session_id='offline-only',source_request_id='capture:B',stop_epoch='offline-stop:0',
            created_at='2026-01-01T00:00:00Z',expires_at='2035-01-01T00:00:00Z',window_type=1)
        fresh=dict(raw['C']);fresh['snapshotId']=meta['C']['snapshot']['snapshot_id']
        rows.append(dict(name=name,request=request.data,hierarchy=fresh,target_class=clazz,independent_descendants=child_count,
            semantic_approved=False,isolation_approved=False))
    cross=json.loads((ROOT/'out/phase5d_c1_c3_o1_20261015/offline_replay.json').read_text(encoding='utf-8'))['cross_scenario_replay']
    result=dict(source='preserved_B3_ABC',live_device_used=False,home_monitor=rows,cross_scenario=cross,pairwise=pairwise)
    OUTPUT.parent.mkdir(exist_ok=True,parents=True);OUTPUT.write_text(json.dumps(result,ensure_ascii=True),encoding='utf-8')
    print(f'OFFLINE_INPUT_READY home={len(rows)} cross={len(cross)}')

def verify():
    r=json.loads((ROOT/'app/build/reports/exact-protocol/safety-replay.json').read_text(encoding='utf-8'))
    assert r['source']=='preserved_B3_ABC' and len(r['home_monitor'])==6 and len(r['cross_scenario'])==6
    assert all(v['resolved'] and v['candidate_count']==1 and v['fake_action_calls']==0 for v in r['home_monitor'])
    assert all(v['fake_action_calls']==0 for v in r['cross_scenario'])
    assert r['false_safe_approval_count']==0
    print('KOTLIN_PRESERVED_HOME_MONITOR=6/6_NO_ACTION CROSS_SCENARIO=6/6_REJECT FALSE_SAFE_APPROVAL=0')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');a=p.parse_args()
    verify() if a.verify else generate()
