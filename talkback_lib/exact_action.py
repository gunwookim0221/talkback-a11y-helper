"""C4 action protocol foundation. No device transport, action or visit authority."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import hmac
import json
import time
from typing import Any
from .exact_node_protocol import ExactNodeRequest, FailureCode, canonical_json, request_digest, _pairs_no_duplicates, _timestamp

READ_ONLY_PROTOCOL_VERSION = "talkback.exact-navigation.v1"
EXACT_ACTION_PROTOCOL_VERSION = "talkback.exact-action.v2"
ACTION_ACK_SCHEMA_VERSION = "2"
ACTION_MODE = "C4_DIAGNOSTIC_ACCEPTANCE_V1"

class ActionRejected(ValueError):
    pass

class ActionState(str, Enum):
    ISSUED="ISSUED"
    VALIDATED="VALIDATED"
    RESOLVED="RESOLVED"
    PRE_DISPATCH_APPROVED="PRE_DISPATCH_APPROVED"
    DISPATCH_STARTED="DISPATCH_STARTED"
    CONSUMED="CONSUMED"
    ACKED="ACKED"
    FAILED_NOT_EXECUTED="FAILED_NOT_EXECUTED"
    FAILED_CONSUMED="FAILED_CONSUMED"
    UNKNOWN_EXECUTION_STATE="UNKNOWN_EXECUTION_STATE"

_TRANSITIONS={
    ActionState.ISSUED:{ActionState.VALIDATED,ActionState.FAILED_NOT_EXECUTED},
    ActionState.VALIDATED:{ActionState.RESOLVED,ActionState.FAILED_NOT_EXECUTED},
    ActionState.RESOLVED:{ActionState.PRE_DISPATCH_APPROVED,ActionState.FAILED_NOT_EXECUTED},
    ActionState.PRE_DISPATCH_APPROVED:{ActionState.DISPATCH_STARTED,ActionState.FAILED_NOT_EXECUTED},
    ActionState.DISPATCH_STARTED:{ActionState.CONSUMED,ActionState.UNKNOWN_EXECUTION_STATE},
    ActionState.CONSUMED:{ActionState.ACKED,ActionState.FAILED_CONSUMED,ActionState.UNKNOWN_EXECUTION_STATE},
}

@dataclass
class ActionTransaction:
    state:ActionState=ActionState.ISSUED
    consumed:bool=False

    def transition(self,new:ActionState):
        if new not in _TRANSITIONS.get(self.state,set()):raise ActionRejected("ILLEGAL_STATE_TRANSITION")
        if new in {ActionState.DISPATCH_STARTED,ActionState.CONSUMED}:self.consumed=True
        self.state=new

class TargetClass(str,Enum):
    NAVIGATION_TARGET="NAVIGATION_TARGET"
    STATE_MUTATION_CONTROL="STATE_MUTATION_CONTROL"
    UNKNOWN_ACTIONABLE="UNKNOWN_ACTIONABLE"
    CONTAINER_WRAPPER="CONTAINER_WRAPPER"
    MIXED_ACTION_CONTAINER="MIXED_ACTION_CONTAINER"

def classify_target(*,mutation:bool=False,independent_actions:int=0,wrapper:bool=False,
                    navigation_semantics:bool=False)->TargetClass:
    if mutation:return TargetClass.STATE_MUTATION_CONTROL
    if independent_actions:return TargetClass.MIXED_ACTION_CONTAINER
    if wrapper:return TargetClass.CONTAINER_WRAPPER
    return TargetClass.NAVIGATION_TARGET if navigation_semantics else TargetClass.UNKNOWN_ACTIONABLE

REQUIRED_CHECKS=tuple('build_gate runtime_gate helper_identity_match protocol_supported ownership_valid '
    'permit_authenticated request_digest_valid transaction_valid request_unique nonce_unique permit_unused '
    'unexpired host_session_match boot_epoch_match connection_epoch_match stop_epoch_match host_stop_inactive '
    'helper_stop_inactive exclusive_channel package_match window_match hierarchy_complete single_candidate '
    'identity_match lineage_match children_match action_set_match click_present enabled visible node_valid '
    'target_class_allowed semantic_approved isolation_approved observation_ready destination_ready '
    'forbidden_detector_ready audit_persisted durable_claim_available'.split())

def pre_dispatch_gate(facts:dict[str,Any])->tuple[bool,tuple[str,...]]:
    failures=tuple(k for k in REQUIRED_CHECKS if facts.get(k) is not True)
    return not failures,failures

BINDING_FIELDS=frozenset('request_id transaction_id permit_id request_nonce ownership expected_package app_version '
    'helper_build_id host_session_id boot_epoch helper_connection_epoch stop_epoch target_identity_digest '
    'authorized_intent_digest semantic_intent allowed_action max_call_count issued_at_ms expires_at_ms '
    'resolve_request_digest'.split())
INTENT_FIELDS=frozenset('kind target_class semantic_approved isolation_approved destination_contract_id '
    'destination_contract_digest evidence_refs'.split())

def digest(value:Any)->str:return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()

def validate_binding(binding:dict[str,Any],resolve:ExactNodeRequest):
    if set(binding)!=BINDING_FIELDS:raise ActionRejected("PERMIT_INVALID")
    for field in ('request_id','transaction_id','permit_id','request_nonce','ownership','expected_package','host_session_id','stop_epoch'):
        if canonical_json(binding[field])!=canonical_json(resolve.data[field]):raise ActionRejected("OWNERSHIP_MISMATCH")
    if binding['allowed_action']!=16 or type(binding['allowed_action']) is not int or binding['max_call_count']!=1 or type(binding['max_call_count']) is not int:
        raise ActionRejected("ACTION_NOT_AVAILABLE")
    for name in ('issued_at_ms','expires_at_ms'):
        if type(binding[name]) is not int:raise ActionRejected("PERMIT_INVALID")
    if not 0<binding['expires_at_ms']-binding['issued_at_ms']<=5000:raise ActionRejected("PERMIT_INVALID")
    intent=binding['semantic_intent']
    if not isinstance(intent,dict) or set(intent)!=INTENT_FIELDS:raise ActionRejected("ACTION_SEMANTICS_UNPROVEN")
    if (intent['kind']!='NAVIGATION' or intent['target_class'] not in {v.value for v in TargetClass}
            or type(intent['semantic_approved']) is not bool or type(intent['isolation_approved']) is not bool
            or not isinstance(intent['evidence_refs'],list) or not intent['evidence_refs']
            or any(not isinstance(v,str) or not v for v in intent['evidence_refs'])
            or not isinstance(intent['destination_contract_id'],str) or not intent['destination_contract_id']):
        raise ActionRejected("ACTION_SEMANTICS_UNPROVEN")
    for field in ('target_identity_digest','authorized_intent_digest','helper_build_id'):
        value=binding[field]
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ActionRejected("PERMIT_INVALID")
    destination_digest=intent['destination_contract_digest']
    if not isinstance(destination_digest,str) or len(destination_digest)!=64 or any(c not in '0123456789abcdef' for c in destination_digest):
        raise ActionRejected("PERMIT_INVALID")
    for field in ('app_version','boot_epoch','helper_connection_epoch'):
        if not isinstance(binding[field],str) or not binding[field]:raise ActionRejected("PERMIT_INVALID")
    if (binding['target_identity_digest']!=digest(resolve.data['target_identity']) or
            binding['authorized_intent_digest']!=digest(intent) or
            binding['resolve_request_digest']!=resolve.data['request_digest']):
        raise ActionRejected("REQUEST_DIGEST_MISMATCH")

@dataclass(frozen=True)
class TrustedActionSession:
    """Injected by a trusted local composition root, NEVER from RPC request fields."""
    secret:bytes
    session_id:str
    package:str
    app_version:str
    helper_build_id:str
    boot_epoch:str
    connection_epoch:str
    stop_epoch:str
    allowed_intent_digests:frozenset[str]
    allowed_target_digests:frozenset[str]
    allowed_transaction_ids:frozenset[str]
    identity_status:str="UNKNOWN"
    created_monotonic_ns:int=field(default_factory=time.monotonic_ns,repr=False)

    def __post_init__(self):
        if len(self.secret)<32 or len(self.allowed_target_digests)!=1 or len(self.allowed_transaction_ids)!=1:
            raise ActionRejected("PERMIT_AUTHENTICATION_FAILED")

    def mac(self,binding:dict)->str:
        return hmac.new(self.secret,canonical_json(binding).encode(),hashlib.sha256).hexdigest()

    def verify(self,request:dict,now_ms:int):
        if self.identity_status!='MATCH':raise ActionRejected('BUILD_IDENTITY_UNKNOWN')
        if not 0<=time.monotonic_ns()-self.created_monotonic_ns<=5_000_000_000:
            raise ActionRejected('PERMIT_EXPIRED')
        if set(request)!={'protocol_version','command','resolve_request','binding','permit_mac','request_digest'}:
            raise ActionRejected("REQUEST_INVALID")
        if request['protocol_version']!=EXACT_ACTION_PROTOCOL_VERSION or request['command']!='EXACT_ACTION':
            raise ActionRejected("PROTOCOL_VERSION_UNSUPPORTED")
        if request_digest(request)!=request['request_digest']:raise ActionRejected("REQUEST_DIGEST_MISMATCH")
        resolve=ExactNodeRequest.parse(request['resolve_request'])
        binding=request['binding'];validate_binding(binding,resolve)
        if not isinstance(request['permit_mac'],str) or not hmac.compare_digest(self.mac(binding),request['permit_mac']):
            raise ActionRejected("PERMIT_AUTHENTICATION_FAILED")
        expected={'host_session_id':self.session_id,'expected_package':self.package,'app_version':self.app_version,
            'helper_build_id':self.helper_build_id,'boot_epoch':self.boot_epoch,
            'helper_connection_epoch':self.connection_epoch,'stop_epoch':self.stop_epoch}
        for key,value in expected.items():
            if binding[key]!=value:raise ActionRejected(key.upper()+"_MISMATCH")
        if not binding['issued_at_ms']<=now_ms<binding['expires_at_ms']:raise ActionRejected("PERMIT_EXPIRED")
        if binding['authorized_intent_digest'] not in self.allowed_intent_digests:raise ActionRejected("ACTION_SEMANTICS_UNPROVEN")
        if binding['target_identity_digest'] not in self.allowed_target_digests or binding['transaction_id'] not in self.allowed_transaction_ids:
            raise ActionRejected("PERMIT_SCOPE_MISMATCH")
        return resolve

    def issue(self,resolve:ExactNodeRequest,*,intent:dict,now_ms:int,lifetime_ms:int=3000)->dict:
        b={k:resolve.data[k] for k in ('request_id','transaction_id','permit_id','request_nonce','ownership','expected_package','host_session_id','stop_epoch')}
        b.update(app_version=self.app_version,helper_build_id=self.helper_build_id,boot_epoch=self.boot_epoch,
            helper_connection_epoch=self.connection_epoch,target_identity_digest=digest(resolve.data['target_identity']),
            authorized_intent_digest=digest(intent),semantic_intent=intent,allowed_action=16,max_call_count=1,
            issued_at_ms=now_ms,expires_at_ms=now_ms+lifetime_ms,resolve_request_digest=resolve.data['request_digest'])
        request=dict(protocol_version=EXACT_ACTION_PROTOCOL_VERSION,command='EXACT_ACTION',resolve_request=resolve.data,
            binding=b,permit_mac=self.mac(b))
        request['request_digest']=request_digest(request)
        self.verify(request,now_ms)
        return request

ACTION_ACK_FIELDS=frozenset('protocol_version ack_schema_version request_id transaction_id permit_id request_nonce '
    'ownership request_digest authorized_intent_digest helper_build_id helper_connection_epoch boot_epoch stop_epoch '
    'authorized_snapshot_id reacquire_snapshot_id helper_validation_snapshot_id resolved_target_identity '
    'resolved_source_node_id source_id_provenance resolved_action_set candidate_count pre_dispatch_gate_verdict '
    'gate_evidence_refs permit_consumed consumption_receipt_id dispatch_started_at dispatch_finished_at '
    'dispatch_uptime_ms producer_sequence perform_action_called perform_action_type perform_action_call_count '
    'perform_action_return exception_detail framework_event_correlation_window post_action_probe_id failure_code '
    'failure_detail audit_receipt_id visit_authority execution_state action_effect_confirmed expected_navigation_confirmed'.split())

ACTION_FAILURE_CODES=frozenset(v.value for v in FailureCode)|frozenset('ACTION_GATE_DISABLED ACTION_SEMANTICS_UNPROVEN '
    'TARGET_CLASS_NOT_ALLOWED PERMIT_ALREADY_USED PERMIT_AUTHENTICATION_FAILED PERMIT_SCOPE_MISMATCH '
    'REQUEST_DIGEST_MISMATCH OWNERSHIP_MISMATCH BOOT_EPOCH_MISMATCH HELPER_CONNECTION_EPOCH_MISMATCH '
    'STOP_EPOCH_MISMATCH HOST_SESSION_ID_MISMATCH EXPECTED_PACKAGE_MISMATCH APP_VERSION_MISMATCH '
    'HELPER_BUILD_ID_MISMATCH BUILD_IDENTITY_MISMATCH BUILD_IDENTITY_UNKNOWN CONCURRENT_ACTION '
    'TARGET_DISABLED TARGET_NOT_VISIBLE TARGET_STALE ISOLATION_UNPROVEN PRE_DISPATCH_GATE_REJECTED '
    'PERFORM_ACTION_FALSE ACTION_EFFECT_TIMEOUT ACTION_EFFECT_AMBIGUOUS WRONG_DESTINATION '
    'FORBIDDEN_SIDE_EFFECT AUDIT_PERSIST_FAILED UNKNOWN_EXECUTION_STATE RECEIPT_NOT_FOUND REQUEST_INVALID'.split())

@dataclass(frozen=True)
class ActionAck:
    data:dict[str,Any]

    @classmethod
    def parse(cls,raw:str|dict,request:dict):
        value=json.loads(raw,object_pairs_hook=_pairs_no_duplicates) if isinstance(raw,str) else raw
        if not isinstance(value,dict) or set(value)!=ACTION_ACK_FIELDS:raise ActionRejected('ACK_SCHEMA_INVALID')
        try:canonical_json(value)
        except (ValueError,TypeError,UnicodeError) as exc:raise ActionRejected('ACK_SCHEMA_INVALID') from exc
        if value['protocol_version']!=EXACT_ACTION_PROTOCOL_VERSION or value['ack_schema_version']!=ACTION_ACK_SCHEMA_VERSION:
            raise ActionRejected('ACK_VERSION_UNSUPPORTED')
        b=request['binding'];resolve=request['resolve_request']
        for key in ('request_id','transaction_id','permit_id','request_nonce','ownership','authorized_intent_digest',
                    'helper_build_id','helper_connection_epoch','boot_epoch','stop_epoch'):
            if canonical_json(value[key])!=canonical_json(b[key]):raise ActionRejected('ACK_OWNERSHIP_MISMATCH:'+key)
        if value['request_digest']!=request['request_digest']:raise ActionRejected('ACK_DIGEST_MISMATCH')
        if value['failure_code'] is not None and (not isinstance(value['failure_code'],str) or value['failure_code'] not in ACTION_FAILURE_CODES):
            raise ActionRejected('ACK_FAILURE_CODE_UNSUPPORTED')
        for field_name in ('failure_detail','exception_detail','post_action_probe_id'):
            if value[field_name] is not None and not isinstance(value[field_name],str):raise ActionRejected('ACK_SCHEMA_INVALID')
        for field_name in ('dispatch_started_at','dispatch_finished_at'):
            if value[field_name] is not None:
                try:_timestamp(value[field_name],field_name)
                except (ValueError,TypeError) as exc:raise ActionRejected('ACK_TIME_INVALID') from exc
        if value['framework_event_correlation_window'] is not None:raise ActionRejected('ACK_C5_EVIDENCE_NOT_SUPPORTED')
        if not isinstance(value['audit_receipt_id'],str) or not value['audit_receipt_id'].strip():raise ActionRejected('ACK_AUDIT_MISSING')
        for key in ('authorized_snapshot_id','reacquire_snapshot_id'):
            if value[key]!=resolve[key]:raise ActionRejected('ACK_SNAPSHOT_MISMATCH')
        for key in ('visit_authority','action_effect_confirmed','expected_navigation_confirmed'):
            if value[key] is not False:raise ActionRejected('ACK_AUTHORITY_VIOLATION')
        try:state=ActionState(value['execution_state'])
        except ValueError as exc:raise ActionRejected('ACK_STATE_INVALID') from exc
        if type(value['permit_consumed']) is not bool:raise ActionRejected('ACK_CONSUMPTION_INVALID')
        if type(value['candidate_count']) is not int or value['candidate_count']<0:raise ActionRejected('ACK_CANDIDATE_COUNT_INVALID')
        if not isinstance(value['gate_evidence_refs'],list) or not value['gate_evidence_refs'] or any(not isinstance(v,str) or not v for v in value['gate_evidence_refs']):
            raise ActionRejected('ACK_AUDIT_MISSING')
        consumed=value['permit_consumed'];called=value['perform_action_called'];count=value['perform_action_call_count']
        if state not in {ActionState.ACKED,ActionState.FAILED_NOT_EXECUTED,ActionState.FAILED_CONSUMED,ActionState.UNKNOWN_EXECUTION_STATE}:
            raise ActionRejected('ACK_STATE_INVALID')
        if state==ActionState.FAILED_NOT_EXECUTED and consumed:raise ActionRejected('ACK_STATE_INVALID')
        if state in {ActionState.FAILED_CONSUMED,ActionState.UNKNOWN_EXECUTION_STATE} and not consumed:raise ActionRejected('ACK_STATE_INVALID')
        returned=value['perform_action_return']
        if consumed:
            if not isinstance(value['consumption_receipt_id'],str) or not value['consumption_receipt_id']:raise ActionRejected('ACK_RECEIPT_MISSING')
        elif value['consumption_receipt_id'] is not None:raise ActionRejected('ACK_CONSUMPTION_INVALID')
        if called is True:
            if (type(count) is not int or count!=1 or not consumed or value['perform_action_type']!=16
                    or value['candidate_count']!=1 or value['pre_dispatch_gate_verdict']!='APPROVED'
                    or not value['dispatch_started_at'] or not value['dispatch_finished_at']
                    or type(value['dispatch_uptime_ms']) is not int):raise ActionRejected('ACK_CALL_INVALID')
            if returned is not None and type(returned) is not bool:raise ActionRejected('ACK_RETURN_INVALID')
            if returned is None and state!=ActionState.UNKNOWN_EXECUTION_STATE:raise ActionRejected('ACK_RETURN_MISSING')
            if returned is False and (state!=ActionState.FAILED_CONSUMED or value['failure_code']!='PERFORM_ACTION_FALSE'):
                raise ActionRejected('ACK_FALSE_NOT_FAILURE')
            target=value['resolved_target_identity'];expected=resolve['target_identity']
            snapshot=value['helper_validation_snapshot_id']
            if (not isinstance(snapshot,str) or not snapshot or snapshot in {resolve['authorized_snapshot_id'],resolve['reacquire_snapshot_id']} or
                not isinstance(target,dict) or set(target)!=set(expected) or target.get('snapshot_id')!=snapshot):raise ActionRejected('ACK_IDENTITY_MISMATCH')
            provenance=target.get('field_provenance')
            if not isinstance(provenance,dict) or set(provenance)!=set(expected['field_provenance']):raise ActionRejected('ACK_IDENTITY_MISMATCH')
            for name,entry in provenance.items():
                if (not isinstance(entry,dict) or set(entry)!={'status','source_field','derivation'} or
                    entry['status'] not in {'PRESENT','ABSENT_IN_SOURCE','NOT_SUPPORTED_BY_SOURCE','PARSE_FAILED'} or
                    (entry['source_field'] is not None and not isinstance(entry['source_field'],str)) or not isinstance(entry['derivation'],str)):
                    raise ActionRejected('ACK_IDENTITY_MISMATCH')
                if name in {'package','resource_id','class_name','bounds','actions'} and entry['status']!='PRESENT':raise ActionRejected('ACK_IDENTITY_MISMATCH')
            if target.get('source_node_id_provenance')!=provenance['source_node_id']['status']:raise ActionRejected('ACK_IDENTITY_MISMATCH')
            if target.get('source_node_id') is not None and not isinstance(target['source_node_id'],str):raise ActionRejected('ACK_IDENTITY_MISMATCH')
            bounds=target.get('bounds')
            if (not isinstance(bounds,dict) or not {'left','top','right','bottom'}<=bounds.keys() or
                not set(bounds)<={'left','top','right','bottom','l','t','r','b'} or any(type(v) is not int for v in bounds.values())):
                raise ActionRejected('ACK_IDENTITY_MISMATCH')
            for field in ('package','window_id','resource_id','class_name','text','content_description','lineage_signature','child_structure_signature','actions'):
                if canonical_json(target.get(field))!=canonical_json(expected[field]):raise ActionRejected('ACK_IDENTITY_MISMATCH:'+field)
            if expected['source_node_id_provenance']=='PRESENT' and target.get('source_node_id')!=expected['source_node_id']:
                raise ActionRejected('ACK_IDENTITY_MISMATCH:source_node_id')
            if (canonical_json(value['resolved_action_set'])!=canonical_json(target['actions']) or
                value['resolved_source_node_id']!=target.get('source_node_id') or value['source_id_provenance']!=target.get('source_node_id_provenance')):
                raise ActionRejected('ACK_IDENTITY_MISMATCH')
        elif called is False:
            if type(count) is not int or count!=0 or returned is not None or value['perform_action_type'] is not None:raise ActionRejected('ACK_CALL_INVALID')
            if consumed and state!=ActionState.UNKNOWN_EXECUTION_STATE:raise ActionRejected('ACK_STATE_INVALID')
        elif called is None:
            if count is not None or returned is not None or value['perform_action_type'] is not None or not consumed or state!=ActionState.UNKNOWN_EXECUTION_STATE:raise ActionRejected('ACK_CALL_INVALID')
        else:raise ActionRejected('ACK_CALL_INVALID')
        if type(value['producer_sequence']) is not int or value['producer_sequence']<1 or not value['audit_receipt_id']:
            raise ActionRejected('ACK_AUDIT_MISSING')
        if state==ActionState.ACKED and (called is not True or returned is not True):raise ActionRejected('ACK_FALSE_SUCCESS')
        if state==ActionState.ACKED and value['failure_code'] is not None:raise ActionRejected('ACK_FALSE_SUCCESS')
        if state==ActionState.ACKED and value['exception_detail'] is not None:raise ActionRejected('ACK_FALSE_SUCCESS')
        if state in {ActionState.FAILED_NOT_EXECUTED,ActionState.FAILED_CONSUMED,ActionState.UNKNOWN_EXECUTION_STATE} and not value['failure_code']:
            raise ActionRejected('ACK_FAILURE_MISSING')
        return cls(value)

    @property
    def dispatch_confirmed(self):
        return (self.data['execution_state']==ActionState.ACKED.value and self.data['failure_code'] is None
                and self.data['perform_action_called'] is True and self.data['perform_action_return'] is True)

@dataclass(frozen=True)
class ActionResponse:
    state:str
    evidence:dict[str,Any]
    ack:ActionAck|None=None

    @property
    def dispatch_confirmed(self):return self.ack is not None and self.ack.dispatch_confirmed

def parse_action_response(raw:str|dict,request:dict,*,transport_request_id:str,receipt:bool=False)->ActionResponse:
    """Transport errors preserve their code; unknown readback never becomes execution success."""
    envelope=json.loads(raw,object_pairs_hook=_pairs_no_duplicates) if isinstance(raw,str) else raw
    field='receipt' if receipt else 'ack'
    if not isinstance(envelope,dict) or envelope.get('reqId')!=transport_request_id:raise ActionRejected('ACK_OWNERSHIP_MISMATCH')
    if set(envelope)=={'reqId','failure_code'} and envelope['failure_code'] in ACTION_FAILURE_CODES:
        raise ActionRejected(envelope['failure_code'])
    if set(envelope)!={'reqId',field} or not isinstance(envelope[field],dict):raise ActionRejected('ACK_SCHEMA_INVALID')
    body=envelope[field]
    if 'ack_schema_version' in body:
        ack=ActionAck.parse(body,request)
        return ActionResponse(ack.data['execution_state'],ack.data,ack)
    if set(body)=={'status','failure_code','perform_action_called','visit_authority'}:
        if (body['status'] in {'REJECTED','UNKNOWN_EXECUTION_STATE'} and body['failure_code'] in ACTION_FAILURE_CODES
            and (body['perform_action_called'] is False or body['perform_action_called'] is None) and body['visit_authority'] is False):
            raise ActionRejected(body['failure_code'])
    ownership_fields={'request_id','transaction_id','permit_id','request_nonce','ownership','helper_build_id',
                      'helper_connection_epoch','boot_epoch','stop_epoch'}
    expected=ownership_fields|{'request_digest','status','permit_consumed','action_request_resent','visit_authority'}
    if (not receipt or set(body)!=expected or body['status']!='UNKNOWN_EXECUTION_STATE' or
        type(body['permit_consumed']) is not bool or body['action_request_resent'] is not False or body['visit_authority'] is not False):
        raise ActionRejected('ACK_SCHEMA_INVALID')
    for key in ownership_fields:
        if canonical_json(body[key])!=canonical_json(request['binding'][key]):raise ActionRejected('ACK_OWNERSHIP_MISMATCH:'+key)
    if body['request_digest']!=request['request_digest']:raise ActionRejected('ACK_DIGEST_MISMATCH')
    return ActionResponse('UNKNOWN_EXECUTION_STATE',body)
