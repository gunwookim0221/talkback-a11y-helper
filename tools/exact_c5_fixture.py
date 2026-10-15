"""Deterministic synthetic C4/C5 evidence. No device, transport, or native actions."""
from copy import deepcopy
import json
from pathlib import Path

from talkback_lib.exact_node_protocol import canonical_json
from talkback_lib.exact_post_action import VERSION, digest, owner
from talkback_lib.exact_action import REQUIRED_CHECKS

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    request = json.loads((ROOT/'tests/fixtures/exact_protocol/action.json').read_text())['request']
    b = request['binding']
    package = b['expected_package']
    contract = dict(schema_version=VERSION, destination_contract_id='synthetic:destination', expected_package=package,
        allowed_activities=['example.Destination'], required_root_signatures=['destination:structure:v1'],
        required_markers=['destination:root'], required_structures=['root/content/navigation'],
        source_screen_signatures=['source:structure:v1'], expected_context='destination',
        minimum_stable_observations=2, settle_ms=100, timeout_ms=5000,
        forbidden_effects=dict(schema_version=VERSION, control_identities=['sibling:control'],
            forbidden_markers=['wrong:modal'], forbidden_event_text=['forbidden:state-control'], allowed_modal='NONE', required_state_selectors=['security:status']))
    b['semantic_intent']['destination_contract_digest'] = digest(contract)
    b['authorized_intent_digest'] = digest(b['semantic_intent'])
    # Fixture MAC is explicitly synthetic; no session verifier or live consumer accepts it.
    request['request_digest'] = digest({k:v for k,v in request.items() if k!='request_digest'})
    ack = json.loads((ROOT/'tests/fixtures/exact_protocol/action_ack.json').read_text())[0]['ack']
    for k in ('request_id','transaction_id','permit_id','request_nonce','ownership','helper_build_id',
              'helper_connection_epoch','boot_epoch','stop_epoch','authorized_intent_digest'):
        ack[k] = deepcopy(b[k])
    target = deepcopy(request['resolve_request']['target_identity']);target['snapshot_id']='fresh:helper'
    ack.update(request_digest=request['request_digest'], helper_validation_snapshot_id='fresh:helper',
        resolved_target_identity=target, resolved_source_node_id=target.get('source_node_id'),
        source_id_provenance=target['source_node_id_provenance'], resolved_action_set=target['actions'],
        candidate_count=1, pre_dispatch_gate_verdict='APPROVED', permit_consumed=True,
        consumption_receipt_id='consumed:synthetic', dispatch_started_at='2026-10-16T00:00:00Z',
        dispatch_finished_at='2026-10-16T00:00:00Z', dispatch_uptime_ms=100, producer_sequence=6,
        perform_action_called=True, perform_action_type=16, perform_action_call_count=1,
        perform_action_return=True, failure_code=None, execution_state='ACKED', audit_receipt_id='result:synthetic')
    cursor = dict(**owner(request), schema_version=VERSION, probe_id='probe:synthetic',
        target_identity_digest=b['target_identity_digest'], producer_sequence_cursor=2,
        start_uptime_ms=90, deadline_uptime_ms=5090, window_ms=5000, receive_grace_ms=1000,
        destination_contract=contract, baseline_security_state={'security:status':'unchanged'})
    cursor['security_observability']=dict(status='COMPLETE',independent_channel=True,continuous_coverage=True,
        selectors=['security:status'],evidence_refs=['SYNTHETIC_FULL_STATE_CHANNEL'])
    event = dict(**owner(request), probe_id=cursor['probe_id'], event_type=1, event_uptime_ms=110,
        helper_receive_uptime_ms=120, helper_receive_timestamp_ms=99999999, helper_monotonic_ns=333333333,
        host_receive_timestamp_ms=0, host_monotonic_ns=99999999999999999,
        package=package, window_id=7, window_type=1, **{'class':'android.widget.Button'},
        text=['Open'], content_description=None, source_identity=deepcopy(target), source_provenance='EXACT_NODE_DESCRIPTOR',
        enabled=True, clickable=True, bounds=target['bounds'])
    def probe(t, seq):
        return dict(**owner(request), post_action_probe_id=cursor['probe_id'], observation_sequence=seq,
            device_uptime_ms=t, package=package, activity='example.Destination', context='destination', modal='NONE',
            root_signature='destination:structure:v1', markers=['destination:root'], structures=['root/content/navigation'],
            security_state={'security:status':'unchanged'}, read_succeeded=True)
    records = [
        ('REQUEST_RECEIVED',request), ('C5_CURSOR_ARMED',cursor),
        ('DISPATCH_STARTED',{'consumption_receipt_id':'consumed:synthetic'}),
        ('CONSUMED',{'consumption_receipt_id':'consumed:synthetic'}),
        ('PERFORM_ACTION_RESULT',{'return':True,'exception':None}), ('ACK_PREPARED',ack),
        ('C5_RAW_EVENT',event), ('C5_STRUCTURAL_PROBE',probe(200,1)), ('C5_STRUCTURAL_PROBE',probe(400,2)),
        ('C5_COLLECTION_CLOSED',dict(**owner(request),probe_id=cursor['probe_id'],closed_uptime_ms=6090))]
    return request, records


def export(request, records):
    b=request['binding'];out=[];previous='0'*64
    records=deepcopy(records)
    if any(k=='C5_CURSOR_ARMED' for k,p in records):
        index=next((i for i,(k,p) in enumerate(records) if k=='DISPATCH_STARTED'),None)
        if index is not None:
            records.insert(index,('PRE_DISPATCH_APPROVED',dict(request_digest=request['request_digest'],facts={k:True for k in REQUIRED_CHECKS})))
    for seq,(kind,payload) in enumerate(records,1):
        payload=deepcopy(payload)
        if kind=='C5_CURSOR_ARMED':payload['producer_sequence_cursor']=seq
        if kind=='C5_RAW_EVENT':payload['event_sequence']=seq
        row=dict(event_id='result:synthetic' if kind=='PERFORM_ACTION_RESULT' else f'event:{seq}',
            event_type=kind,request_id=b['request_id'],producer_sequence=seq,timestamp_ms=0,
            payload=payload,previous_hash=previous,producer_connection_epoch=b['helper_connection_epoch'],
            boot_epoch=b['boot_epoch'],stop_epoch=b['stop_epoch'],ownership_status='REGISTERED_REQUEST',failure_code=None)
        for key in ('transaction_id','permit_id','request_nonce','ownership','host_session_id'):row[key]=deepcopy(b[key])
        previous=digest(row);out.append(dict(record=row,hash=previous))
    return out


if __name__=='__main__':
    request,records=fixture()
    path=ROOT/'tests/fixtures/exact_protocol/post_action.json'
    path.write_text(canonical_json(dict(request=request,helper_export=export(request,records))),encoding='utf-8')
    print('C5_SYNTHETIC_FIXTURE_WRITTEN')
