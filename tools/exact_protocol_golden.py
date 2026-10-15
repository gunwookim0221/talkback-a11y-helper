"""Produce Python wire fixtures / validate real JVM-produced ACKs. Never uses ADB."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from talkback_lib.exact_node_protocol import (ExactNodeAck, ExactNodeRequest, build_target_descriptor,
    canonical_json, create_resolve_request, request_digest)
from talkback_lib.exact_action import ActionAck,parse_action_response

FIXTURE = ROOT / "tests/fixtures/exact_protocol/golden.json"
JVM_OUTPUT = ROOT / "app/build/reports/exact-protocol/acks.json"

def generate():
    cases = []
    for index, text in enumerate(['Open', '한글 English 😀', 'quote " slash / backslash \\', 'line\nnext\ttab', '', None]):
        def node(resource, children, label=None, actions=None):
            return dict(packageName="com.example.smartthings", viewIdResourceName=resource,
                className="android.widget.Button", text=label, contentDescription=None,
                sourceNodeId=None, boundsInScreen=dict(left=0,top=0,right=100,bottom=100),
                clickable=bool(actions),focusable=True,enabled=True,visibleToUser=True,
                actions=actions or [],children=children)
        actions=[dict(id=16,name="ACTION_CLICK",label=None)]
        if index == 1: actions += [dict(id=64,name="ACTION_ACCESSIBILITY_FOCUS",label="포커스")]
        target=node("com.example.smartthings:id/navigation",[],text,actions)
        if index == 1:
            target['sourceNodeId']='synthetic:public-unique-id'
            target['contentDescription']='탐색 "Navigation" / 경로'
        wrapper=node("com.example.smartthings:id/wrapper",[target]) if index == 1 else target
        root=node("com.example.smartthings:id/root",[wrapper])
        hierarchy=dict(snapshotId="helper-C",success=True,windows=[dict(id=7,type=1,root=root)])
        descriptor=build_target_descriptor(hierarchy,window_index=0,child_indices=[0,0] if index == 1 else [0],snapshot_id="B")
        request=create_resolve_request(descriptor,request_id=f"golden:{index}",transaction_id=f"tx:{index}",
            permit_id=f"permit:{index}",request_nonce=f"nonce:{index}",ownership=dict(run_id="run:golden",
            scenario_id="synthetic",scenario_transaction_id="scenario:1",step_action_id=f"step:{index}",parent_action_id=None),
            authorized_snapshot_id="A",helper_service_instance_id="helper:golden",host_session_id="host:golden",
            source_request_id="capture:B",stop_epoch="stop:0",created_at="2026-01-01T00:00:00Z",
            expires_at="2035-01-01T00:00:00Z",window_type=1)
        if index == 1:
            request.data['ownership']['parent_action_id']='parent:golden'
            request.data['expected_window']['context_epoch']='context:golden'
            request.data['evidence_refs']=['fixture:maximal','fixture:independent-lineage']
            request.data['request_digest']=request_digest(request.data)
            ExactNodeRequest.parse(request.data)
        name='minimal-valid' if index == 0 else 'maximal-valid' if index == 1 else f'request-{index}'
        cases.append(dict(name=name,request=request.data,wire=canonical_json(request.data),
            digest=request.data['request_digest'],hierarchy=hierarchy,expected_resolved=True))
    for name, mutation in [('unknown-critical',lambda d:d.update(unknown_critical=True)),
                           ('wrong-id-type',lambda d:d.update(request_id=17)),
                           ('failure-ack',lambda d:d.update(expected_package="wrong.package"))]:
        case=deepcopy(cases[0]);case['name']=name
        for k in ('request_id','transaction_id','permit_id','request_nonce'):case['request'][k]+=':'+name
        mutation(case['request']);case['request']['request_digest']=request_digest(case['request'])
        case.update(wire=canonical_json(case['request']),digest=case['request']['request_digest'],expected_resolved=False)
        cases.append(case)
    values=[dict(z=None,a=[True,False,[],{},'한글 😀 " \\ /\n\t']),dict(a=-9223372036854775808,b=9223372036854775807)]
    document=dict(schema="exact-canonical.v1",cases=cases,values=[dict(value=v,canonical=canonical_json(v),
        digest=hashlib.sha256(canonical_json(v).encode()).hexdigest()) for v in values])
    FIXTURE.parent.mkdir(parents=True,exist_ok=True)
    FIXTURE.write_text(json.dumps(document,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')

def verify(action=False):
    fixture=json.loads(FIXTURE.read_text(encoding='utf-8'))
    output=json.loads(JVM_OUTPUT.read_text(encoding='utf-8'))
    assert len(output)==len(fixture['cases'])
    for case,row in zip(fixture['cases'],output):
        assert row['name']==case['name'] and row['canonical']==case['wire']
        assert row['digest']==case['digest']
        request=ExactNodeRequest.parse(case['request']) if case['expected_resolved'] else None
        ack=ExactNodeAck.parse(row['ack_wire'],request)
        assert ack.data['resolved']==case['expected_resolved']
        assert ack.data['perform_action_call_count']==0
    print(f"PYTHON_KOTLIN_INTEROP_PASS cases={len(output)}")
    if action:
        action_rows=json.loads((JVM_OUTPUT.parent/'action-acks.json').read_text(encoding='utf-8'))
        for row in action_rows:ActionAck.parse(row['ack'],row['request'])
        print(f"KOTLIN_PYTHON_ACTION_ACK_PASS cases={len(action_rows)}")
        errors=json.loads((JVM_OUTPUT.parent/'error-acks.json').read_text(encoding='utf-8'))
        for raw in errors:
            ack=ExactNodeAck.parse(raw)
            assert ack.data['failure_code'] and not ack.data['resolved']
        positive=json.loads((JVM_OUTPUT.parent/'mock-action-result.json').read_text(encoding='utf-8'))
        assert positive['evidence_type']=='ROBOLECTRIC_MOCK_NODE'
        assert ActionAck.parse(positive['ack'],positive['request']).dispatch_confirmed
        unknown=json.loads((JVM_OUTPUT.parent/'unknown-receipt.json').read_text(encoding='utf-8'))
        assert not parse_action_response(unknown['response'],unknown['request'],transport_request_id='readback:synthetic',receipt=True).dispatch_confirmed
        print(f"KOTLIN_ERROR_DETAILS_PASS cases={len(errors)} MOCK_DISPATCH_ACK_PASS=1")

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--generate',action='store_true');parser.add_argument('--action',action='store_true');args=parser.parse_args()
    generate() if args.generate else verify(args.action)
