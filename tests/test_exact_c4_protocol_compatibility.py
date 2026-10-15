"""C4-0 independent wire contract checks; JVM ACK verification is a separate gate."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from talkback_lib.exact_node_protocol import (canonical_json, request_digest, ExactNodeRequest,
    ExactNodeAck, ProtocolValidationError, resolve_exact_request)

FIXTURE=Path(__file__).parent/'fixtures/exact_protocol/golden.json'

def test_python_wire_golden_and_strict_schema():
    fixture=json.loads(FIXTURE.read_text(encoding='utf-8'))
    for case in fixture['cases']:
        assert canonical_json(case['request'])==case['wire']
        assert request_digest(case['request'])==case['digest']
        if case['expected_resolved']:
            ExactNodeRequest.parse(case['wire'])
        else:
            with pytest.raises(ProtocolValidationError):ExactNodeRequest.parse(case['wire'])

@pytest.mark.parametrize('value',[1.0,float('nan'),2**63,-2**63-1,'\ud800',{'\ud800':1}])
def test_canonical_rejects_ambiguous_types(value):
    with pytest.raises((ValueError,UnicodeError)):canonical_json(value)

def test_canonical_whitespace_key_order_and_absence():
    assert canonical_json(json.loads(' { "b":2, "a":1 } '))=='{"a":1,"b":2}'
    assert canonical_json({'a':None})!=canonical_json({})
    assert canonical_json({'😀':1,'\ue000':2}).startswith('{"\\ud83d\\ude00"')

def test_registered_errors_roundtrip_and_unknown_extensions_rejected():
    case=json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'][0]
    req=ExactNodeRequest.parse(case['request'])
    h=deepcopy(case['hierarchy']);h['snapshot_id']=h['snapshotId']
    ack=resolve_exact_request(req,h)
    ack.update(ack_schema_version='1.1',failure_detail=None)
    ExactNodeAck.parse(ack,req)
    ack['unknown_critical']=True
    with pytest.raises(ProtocolValidationError):ExactNodeAck.parse(ack,req)
    del ack['unknown_critical'];del ack['perform_action_return']
    with pytest.raises(ProtocolValidationError):ExactNodeAck.parse(ack,req)

def test_read_only_version_cannot_authorize_action():
    req=json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'][0]['request']
    req['action_type']='ACTION_CLICK';req['request_digest']=request_digest(req)
    with pytest.raises(ProtocolValidationError):ExactNodeRequest.parse(req)
