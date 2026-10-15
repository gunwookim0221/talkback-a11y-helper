"""C5 read-only verifier. Local durable evidence, never an action or visit authority.

Clock comparisons use device uptime only. Host timestamps are forensic metadata.
The v2 C4 ACK remains unchanged; C5 is a separate versioned evidence envelope.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import hashlib
from typing import Any

from .exact_action import ActionAck, ActionRejected, REQUIRED_CHECKS, validate_binding
from .exact_node_protocol import ExactNodeRequest
from .exact_action_journal import DurableActionJournal
from .exact_node_protocol import canonical_json

VERSION = 'talkback.post-action.v1'
EFFECT_WINDOW_MS = 5000
RECEIVE_GRACE_MS = 1000
REQUIRED_EVENT_TYPES = frozenset((1, 4, 8, 32, 2048, 4096, 16384, 32768, 4194304))
ACTION_EVENT_TYPES = frozenset((1, 32768))
OWNER_KEYS = ('transaction_id', 'request_id', 'permit_id', 'request_nonce', 'ownership')


class Correlation(str, Enum):
    STRONG_MATCH = 'STRONG_MATCH'
    SUPPORTING_MATCH = 'SUPPORTING_MATCH'
    AMBIGUOUS = 'AMBIGUOUS'
    NOT_MATCHED = 'NOT_MATCHED'


class Outcome(str, Enum):
    NAVIGATION_CONFIRMED = 'NAVIGATION_CONFIRMED'
    DISPATCH_ONLY = 'DISPATCH_ONLY'
    EFFECT_CONFIRMED_WRONG_DESTINATION = 'EFFECT_CONFIRMED_WRONG_DESTINATION'
    NO_EFFECT = 'NO_EFFECT'
    FORBIDDEN_EFFECT = 'FORBIDDEN_EFFECT'
    AMBIGUOUS_EFFECT = 'AMBIGUOUS_EFFECT'
    POST_ACTION_TIMEOUT = 'POST_ACTION_TIMEOUT'
    AUDIT_FAILURE = 'AUDIT_FAILURE'
    UNKNOWN_EXECUTION_STATE = 'UNKNOWN_EXECUTION_STATE'


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ActionRejected(code)


def integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def owned(value: dict, request: dict) -> bool:
    b = request['binding']
    keys = OWNER_KEYS + ('helper_connection_epoch', 'boot_epoch', 'helper_build_id', 'stop_epoch')
    return all(k in value and canonical_json(value[k]) == canonical_json(b[k]) for k in keys)


def owner(request: dict) -> dict:
    return {k: deepcopy(request['binding'][k]) for k in
            OWNER_KEYS + ('helper_connection_epoch', 'boot_epoch', 'helper_build_id', 'stop_epoch')}


def same_node(source: dict, target: dict) -> bool:
    # Snapshot/provenance record IDs change on a fresh capture. Structural identity does not.
    fields = ('package', 'window_id', 'resource_id', 'class_name', 'text', 'content_description',
              'lineage_signature', 'child_structure_signature', 'actions')
    def bounds(n):
        raw = n.get('bounds', {})
        keys = ('left', 'top', 'right', 'bottom')
        if not isinstance(raw, dict) or not all(type(raw.get(k)) is int for k in keys): return None
        if any(a in raw and raw[a] != raw[k] for a, k in zip(('l','t','r','b'), keys)): return None
        return tuple(raw[k] for k in keys)
    return (isinstance(source, dict) and all(k in source and source[k] == target.get(k) for k in fields) and
            bounds(source) is not None and bounds(source) == bounds(target) and
            (target.get('source_node_id_provenance') != 'PRESENT' or
             source.get('source_node_id') == target.get('source_node_id')))


@dataclass(frozen=True)
class DestinationContract:
    """Reviewed contract digest is already authenticated by C4 semantic_intent."""
    data: dict

    @classmethod
    def parse(cls, data: dict, request: dict):
        required = {'schema_version', 'destination_contract_id', 'expected_package', 'allowed_activities',
                    'required_root_signatures', 'required_markers', 'required_structures',
                    'source_screen_signatures', 'expected_context', 'minimum_stable_observations',
                    'settle_ms', 'timeout_ms', 'forbidden_effects'}
        require(isinstance(data, dict) and set(data) == required, 'DESTINATION_CONTRACT_INVALID')
        require(data['schema_version'] == VERSION, 'DESTINATION_CONTRACT_INVALID')
        for k in ('allowed_activities', 'required_root_signatures', 'required_markers',
                  'required_structures', 'source_screen_signatures'):
            require(isinstance(data[k], list) and bool(data[k]) and
                    all(isinstance(x, str) and bool(x.strip()) for x in data[k]), 'DESTINATION_CONTRACT_INVALID')
        require(all(isinstance(data[k], str) and bool(data[k].strip()) for k in
                    ('destination_contract_id', 'expected_package', 'expected_context')), 'DESTINATION_CONTRACT_INVALID')
        require(integer(data['minimum_stable_observations']) and data['minimum_stable_observations'] >= 2 and
                integer(data['settle_ms']) and 0 < data['settle_ms'] <= 1000 and
                integer(data['timeout_ms']) and 0 < data['timeout_ms'] <= EFFECT_WINDOW_MS, 'DESTINATION_CONTRACT_INVALID')
        f = data['forbidden_effects']
        require(isinstance(f, dict) and set(f) == {'schema_version', 'control_identities', 'forbidden_markers',
                    'forbidden_event_text', 'allowed_modal', 'required_state_selectors'} and f['schema_version'] == VERSION,
                'FORBIDDEN_CONTRACT_INVALID')
        for k in ('control_identities', 'forbidden_markers', 'forbidden_event_text', 'required_state_selectors'):
            require(isinstance(f[k], list) and all(isinstance(x, str) and bool(x.strip()) for x in f[k]),
                    'FORBIDDEN_CONTRACT_INVALID')
        require(bool(f['required_state_selectors']) and isinstance(f['allowed_modal'], str), 'FORBIDDEN_CONTRACT_INVALID')
        intent = request['binding']['semantic_intent']
        require(intent['destination_contract_id'] == data['destination_contract_id'] and
                intent['destination_contract_digest'] == digest(data) and
                request['binding']['expected_package'] == data['expected_package'], 'DESTINATION_CONTRACT_UNAPPROVED')
        return cls(deepcopy(data))


def collector_ready(facts: dict) -> bool:
    required = ('service_connected', 'listener_active', 'producer_sequence_available', 'cursor_registered',
                'persistent_audit_writable', 'no_competing_transaction', 'connection_epoch_current',
                'destination_contract_approved', 'forbidden_contract_observable')
    types = facts.get('event_types')
    return (isinstance(types, (list, tuple, set, frozenset)) and
            all(facts.get(k) is True for k in required) and REQUIRED_EVENT_TYPES <= set(types))


def verify_helper_export(rows: list[dict]) -> list[dict]:
    """Store export carries canonical record + its existing C4 SHA256 chain. No repair."""
    require(isinstance(rows, list) and bool(rows), 'AUDIT_PERSIST_FAILED')
    previous = '0' * 64
    output = []
    for seq, wrapper in enumerate(rows, 1):
        require(isinstance(wrapper, dict) and set(wrapper) == {'record', 'hash'}, 'AUDIT_PERSIST_FAILED')
        row = wrapper['record']
        require(row.get('producer_sequence') == seq and type(row.get('producer_sequence')) is int and
                row.get('previous_hash') == previous and digest(row) == wrapper['hash'], 'AUDIT_PERSIST_FAILED')
        previous = wrapper['hash']
        output.append(deepcopy(row))
    return output


def normalize(raw: dict) -> dict:
    """No missing identity is synthesized; duplicate classification never drops raw records."""
    return dict(event_type=raw.get('event_type'), event_uptime_ms=raw.get('event_uptime_ms'),
                package=raw.get('package'), window_id=raw.get('window_id'),
                source_identity=deepcopy(raw.get('source_identity')), text=deepcopy(raw.get('text')),
                content_description=raw.get('content_description'),
                fingerprint=digest({k: raw.get(k) for k in ('event_type', 'event_uptime_ms', 'package',
                    'window_id', 'source_identity', 'text', 'content_description')}))


def structural_probe(hierarchy: dict, selectors: list[str], target_resource_id: str | None = None) -> dict:
    """Independent Python replay of Helper read-only probe derivation (actual hierarchy schema)."""
    windows = [w for w in hierarchy.get('windows', []) if w.get('type') == 1 and
               (w.get('active') is True or w.get('isActive') is True)]
    window = windows[0] if len(windows) == 1 else {}
    root = window.get('root')
    nodes, structures, markers = [], [], []
    limited = False
    def walk(n, path, depth):
        nonlocal limited
        if depth > 80 or len(nodes) >= 5000:
            limited = True
            return
        nodes.append(n)
        rid, clazz = n.get('viewIdResourceName') or '', n.get('className') or ''
        structures.append(f'{path}|{rid}|{clazz}')
        if n.get('visibleToUser') is True:
            if rid: markers.append('id:' + rid)
            if n.get('text'): markers.append('text:' + n['text'])
        for i, c in enumerate(n.get('children', [])):
            walk(c, f'{path}/{i}', depth + 1)
    if root: walk(root, '0', 0)
    states = {}
    for selector in selectors:
        matches = [n for n in nodes if n.get('viewIdResourceName') == selector]
        n = matches[0] if len(matches) == 1 else {}
        states[selector] = ({'text': n.get('text'), 'description': n.get('contentDescription'),
                             'checked': n.get('checked'), 'selected': n.get('selected')}
                            if n.get('visibleToUser') is True and n.get('enabled') is True else None)
    return dict(read_succeeded=root is not None and not limited, raw_hierarchy=deepcopy(hierarchy),
                package=(root or {}).get('packageName'), window_id=window.get('id'), window_type=window.get('type'),
                markers=markers, structures=structures, root_signature=digest(structures), security_state=states,
                target_presence_count=sum(n.get('viewIdResourceName') == target_resource_id for n in nodes)
                    if target_resource_id else None)


def destination_matches(probe: dict, contract: dict) -> bool:
    return (probe.get('read_succeeded') is True and
            probe.get('root_signature') not in contract['source_screen_signatures'] and
            probe.get('package') == contract['expected_package'] and probe.get('activity') in contract['allowed_activities'] and
            probe.get('context') == contract['expected_context'] and probe.get('root_signature') in contract['required_root_signatures'] and
            set(contract['required_markers']) <= set(probe.get('markers', ())) and
            set(contract['required_structures']) <= set(probe.get('structures', ())))


def event_in_window(raw: dict, cursor: dict, dispatch_uptime: int) -> tuple[bool, str]:
    """Event time and Helper receive uptime share Android uptime, never host clocks.

    Grace is for delivery of an event generated within the effect window, not new effects.
    """
    t = raw.get('event_uptime_ms')
    receive = raw.get('helper_receive_uptime_ms')
    seq = raw.get('event_sequence')
    if not all(integer(v) for v in (t, receive, seq)):
        return False, 'EVENT_TIME_UNAVAILABLE'
    end = min(cursor['deadline_uptime_ms'], dispatch_uptime + cursor['window_ms'])
    if seq <= cursor['producer_sequence_cursor'] or t < dispatch_uptime or t < cursor['start_uptime_ms']:
        return False, 'PRE_CURSOR_EVIDENCE'
    if t > end or receive > end + cursor['receive_grace_ms']:
        return False, 'LATE_EVIDENCE'
    if receive < t:
        return False, 'EVENT_CLOCK_INVALID'
    return True, 'IN_WINDOW'


def correlate(raw: dict, cursor: dict, request: dict, dispatch_uptime: int) -> dict:
    admitted, reason = event_in_window(raw, cursor, dispatch_uptime)
    kind = Correlation.NOT_MATCHED
    if not owned(raw, request) or raw.get('probe_id') != cursor['probe_id']:
        reason = 'EVENT_OWNERSHIP_AMBIGUOUS'
    elif admitted:
        if raw.get('package') != request['binding']['expected_package']:
            reason = 'EVENT_SOURCE_MISMATCH'
        elif raw.get('window_id') != request['resolve_request']['expected_window']['id']:
            kind, reason = (Correlation.AMBIGUOUS if raw.get('event_type') in ACTION_EVENT_TYPES else Correlation.SUPPORTING_MATCH), 'WINDOW_TRANSITION_ONLY'
        else:
            source = raw.get('source_identity')
            if source and same_node(source, request['resolve_request']['target_identity']) and raw.get('source_provenance') in ('EXACT_NODE_DESCRIPTOR', 'EXACT_RETAINED_NODE_REFERENCE'):
                kind, reason = Correlation.STRONG_MATCH, 'EXACT_SOURCE'
            elif raw.get('event_type') in ACTION_EVENT_TYPES:
                kind, reason = Correlation.AMBIGUOUS, 'EVENT_SOURCE_MISMATCH' if source else 'EVENT_OWNERSHIP_AMBIGUOUS'
            else:
                kind, reason = Correlation.SUPPORTING_MATCH, 'STRUCTURE_OR_FOCUS_ONLY'
    return dict(result=kind.value, reason=reason, event_sequence=raw.get('event_sequence'), event_digest=digest(raw))


class PostActionVerifier:
    """Consumes a verified Helper export into the existing append-only host journal.

    No sender, action retry, visit writer, or C4 gate setter exists here. Replay is pure.
    """
    def __init__(self, journal: DurableActionJournal, request: dict):
        self.journal = journal
        self.request = deepcopy(request)

    def import_evidence(self, helper_export: list[dict]) -> None:
        rows = verify_helper_export(helper_export)
        # One immutable complete export. Re-import is deliberately rejected, not merged.
        require(not self._rows(), 'C5_EVIDENCE_ALREADY_IMPORTED')
        self.journal.append('C5_HELPER_EXPORT', self.request, {'rows': helper_export})

    def _rows(self) -> list[dict]:
        return [r for r in self.journal.records() if r['request_id'] == self.request['binding']['request_id']
                and r['request_digest'] == self.request['request_digest'] and r['event_type'].startswith('C5_')]

    def replay(self) -> dict:
        """Read only, including partial/crashed transactions. Never reopens observation."""
        rows = self._rows()
        exports = [r for r in rows if r['event_type'] == 'C5_HELPER_EXPORT']
        if len(exports) != 1:
            return self._result(Outcome.UNKNOWN_EXECUTION_STATE, ['UNKNOWN_EXECUTION_STATE'])
        derived = self._evaluate(verify_helper_export(exports[0]['evidence']['rows']))
        finals = [r for r in rows if r['event_type'] == 'C5_FINAL_VERDICT']
        if finals:
            require(len(finals) == 1, 'AUDIT_PERSIST_FAILED')
            persisted = deepcopy(finals[0]['evidence']['result'])
            require(persisted == dict(derived, audit_complete=True), 'AUDIT_PERSIST_FAILED')
            return dict(persisted, audit_reference=finals[0]['record_hash'])
        if derived['expected_navigation_confirmed']:
            derived['expected_navigation_confirmed'] = False
            derived['result'] = Outcome.DISPATCH_ONLY.value
            derived['failure_codes'].append('AUDIT_FINALIZATION_REQUIRED')
        return derived

    def finalize(self) -> dict:
        try:
            rows = self._rows()
            finals = [r for r in rows if r['event_type'] == 'C5_FINAL_VERDICT']
            if finals:
                require(len(finals) == 1, 'AUDIT_PERSIST_FAILED')
                return self.replay()
            exports = [r for r in rows if r['event_type'] == 'C5_HELPER_EXPORT']
            result = self._evaluate(verify_helper_export(exports[0]['evidence']['rows'])) if len(exports) == 1 else self._result(
                Outcome.UNKNOWN_EXECUTION_STATE, ['UNKNOWN_EXECUTION_STATE'])
            # All interpretation is derived, and is stored separately from immutable raw export.
            for kind, field in (('C5_NORMALIZED_EVENTS', 'normalized_events'), ('C5_CORRELATION', 'correlations'),
                                ('C5_FORBIDDEN_VERDICT', 'forbidden_effect_status'), ('C5_DESTINATION_VERDICT', 'destination')):
                self.journal.append(kind, self.request, {'value': result.get(field)})
            result['audit_complete'] = True
            row = self.journal.append('C5_FINAL_VERDICT', self.request, {'result': result})
            return dict(result, audit_reference=row['record_hash'])
        except (OSError, ValueError, KeyError, TypeError, ActionRejected):
            return self._result(Outcome.AUDIT_FAILURE, ['AUDIT_PERSIST_FAILED'])

    @staticmethod
    def _result(outcome: Outcome, failures: list[str], **extra) -> dict:
        return dict(schema_version=VERSION, result=outcome.value, failure_codes=failures,
                    action_dispatch_confirmed=False, action_effect_confirmed=False,
                    expected_navigation_confirmed=False, audit_complete=False,
                    visit_authority=False, retry_allowed=False, hard_stop=True, **extra)

    def _evaluate(self, rows: list[dict]) -> dict:
        request = self.request
        b = request['binding']
        relevant = [r for r in rows if r.get('request_id') == b['request_id']]
        def events(kind):
            return [r for r in relevant if r['event_type'] == kind]
        try:
            validate_binding(b, ExactNodeRequest.parse(request['resolve_request']))
            require(request['request_digest'] == digest({k:v for k,v in request.items() if k != 'request_digest'}), 'REQUEST_DIGEST_MISMATCH')
            # Every C4/C5 row used here has original C4 owner and producer provenance.
            require(all(all(canonical_json(r.get(k)) == canonical_json(b[k]) for k in OWNER_KEYS) and
                        r.get('boot_epoch') == b['boot_epoch'] and r.get('producer_connection_epoch') == b['helper_connection_epoch']
                        for r in relevant), 'EVENT_OWNERSHIP_AMBIGUOUS')
            received = events('REQUEST_RECEIVED')
            require(len(received) == 1 and canonical_json(received[0]['payload']) == canonical_json(request), 'OWNERSHIP_MISMATCH')
            arms, starts, consumed, acks = (events(k) for k in ('C5_CURSOR_ARMED', 'DISPATCH_STARTED', 'CONSUMED', 'ACK_PREPARED'))
            require(len(arms) == len(starts) == len(consumed) == len(acks) == 1, 'UNKNOWN_EXECUTION_STATE')
            cursor = deepcopy(arms[0]['payload'])
            require(owned(cursor, request), 'EVENT_OWNERSHIP_AMBIGUOUS')
            contract = DestinationContract.parse(cursor['destination_contract'], request).data
            require(cursor['target_identity_digest'] == b['target_identity_digest'] and
                    cursor['producer_sequence_cursor'] == arms[0]['producer_sequence'] and
                    arms[0]['producer_sequence'] < starts[0]['producer_sequence'] < consumed[0]['producer_sequence'] < acks[0]['producer_sequence'],
                    'EVENT_OWNERSHIP_AMBIGUOUS')
            require(integer(cursor['start_uptime_ms']) and integer(cursor['deadline_uptime_ms']) and
                    integer(cursor['window_ms']) and 0 < cursor['window_ms'] <= EFFECT_WINDOW_MS and
                    integer(cursor['receive_grace_ms']) and cursor['receive_grace_ms'] <= RECEIVE_GRACE_MS and
                    cursor['deadline_uptime_ms'] == cursor['start_uptime_ms'] + cursor['window_ms'] and
                    cursor['window_ms'] <= contract['timeout_ms'], 'EVENT_TIME_UNAVAILABLE')
            ack = ActionAck.parse(acks[0]['payload'], request).data
            approval = events('PRE_DISPATCH_APPROVED')
            require(len(approval) == 1 and arms[0]['producer_sequence'] < approval[0]['producer_sequence'] < starts[0]['producer_sequence'] and
                    approval[0]['payload'].get('request_digest') == request['request_digest'] and
                    all(approval[0]['payload'].get('facts', {}).get(k) is True for k in REQUIRED_CHECKS), 'PRE_DISPATCH_GATE_REJECTED')
            receipt = ack['consumption_receipt_id']
            require(receipt and starts[0]['payload'].get('consumption_receipt_id') == receipt and
                    consumed[0]['payload'].get('consumption_receipt_id') == receipt and ack['permit_consumed'] is True and
                    ack['perform_action_called'] is True and ack['perform_action_call_count'] == 1 and
                    ack['pre_dispatch_gate_verdict'] == 'APPROVED', 'UNKNOWN_EXECUTION_STATE')
            dispatch = ack['dispatch_uptime_ms']
            require(integer(dispatch) and cursor['start_uptime_ms'] <= dispatch <= cursor['deadline_uptime_ms'], 'EVENT_TIME_UNAVAILABLE')
            require(same_node(ack['resolved_target_identity'], request['resolve_request']['target_identity']), 'EVENT_SOURCE_MISMATCH')
            results = events('PERFORM_ACTION_RESULT')
            require(len(results) == 1 and results[0]['event_id'] == ack['audit_receipt_id'] and
                    results[0]['payload'].get('return') is ack['perform_action_return'] and
                    consumed[0]['producer_sequence'] < results[0]['producer_sequence'] < acks[0]['producer_sequence'],
                    'ACK_AUDIT_MISSING')
            # Connection restart or action-like command during the window cannot be silently ignored.
            require(not any(r['event_type'] == 'HELPER_CONNECTED' and r['producer_sequence'] > arms[0]['producer_sequence'] for r in rows),
                    'UNKNOWN_EXECUTION_STATE')
        except (ActionRejected, KeyError, TypeError, ValueError) as exc:
            return self._result(Outcome.UNKNOWN_EXECUTION_STATE, [str(exc)])

        raw_events = [r['payload'] for r in events('C5_RAW_EVENT')]
        integrity = all(p.get('event_sequence') == r['producer_sequence'] for r, p in
                        ((r, r['payload']) for r in events('C5_RAW_EVENT')))
        if any(e.get('source_provenance') == 'EXACT_RETAINED_NODE_REFERENCE' for e in raw_events):
            bindings = events('C5_EXACT_SOURCE_BOUND')
            integrity &= (len(bindings) == 1 and owned(bindings[0]['payload'], request) and
                          same_node(bindings[0]['payload'].get('target_identity'), request['resolve_request']['target_identity']) and
                          arms[0]['producer_sequence'] < bindings[0]['producer_sequence'] < starts[0]['producer_sequence'])
        normalized = [normalize(e) for e in raw_events]
        seen = set()
        for n in normalized:
            n['duplicate'] = n['fingerprint'] in seen
            seen.add(n['fingerprint'])
        correlations = [correlate(e, cursor, request, dispatch) for e in raw_events]
        eligible = [e for e in raw_events if event_in_window(e, cursor, dispatch)[0]]
        plausible = [e for e in eligible if e.get('event_type') in ACTION_EVENT_TYPES]
        unique_actions = {normalize(e)['fingerprint'] for e in plausible}
        competing = any(r['event_type'] == 'DISPATCH_STARTED' and r.get('request_id') != b['request_id'] and
                        arms[0]['producer_sequence'] < r['producer_sequence'] for r in rows)
        ambiguous = not integrity or competing or len(unique_actions) > 1 or any(c['result'] == Correlation.AMBIGUOUS.value or
                    c['reason'] == 'EVENT_OWNERSHIP_AMBIGUOUS' for c in correlations)
        effect = any(c['result'] == Correlation.STRONG_MATCH.value and e.get('event_type') == 1
                     for e, c in zip(raw_events, correlations))

        probes = [r['payload'] for r in events('C5_STRUCTURAL_PROBE')]
        valid = []
        stale = False
        for p in probes:
            t = p.get('device_uptime_ms')
            if not owned(p, request) or p.get('post_action_probe_id') != cursor['probe_id'] or not integer(t) or not (
                    dispatch <= t <= cursor['deadline_uptime_ms']) or not integer(p.get('observation_sequence')):
                stale = True
                continue
            valid.append(p)
            if 'raw_hierarchy' in p:
                derived = structural_probe(p['raw_hierarchy'], contract['forbidden_effects']['required_state_selectors'],
                                           request['resolve_request']['target_identity'].get('resource_id'))
                if any(p.get(k) != v for k, v in derived.items()):
                    stale = True
        # Repeated IDs/sequences, reordered probes, or a failed read cannot count as stability.
        if any(valid[i]['observation_sequence'] >= valid[i+1]['observation_sequence'] or
               valid[i]['device_uptime_ms'] >= valid[i+1]['device_uptime_ms'] for i in range(len(valid)-1)):
            stale = True
        f = contract['forbidden_effects']
        failures = [ack['failure_code']] if ack['failure_code'] else []
        forbidden = False
        for e in eligible:
            if e.get('package') not in (None, contract['expected_package']):
                failures.append('FORBIDDEN_SIDE_EFFECT'); forbidden = True
            if e.get('event_type') == 1 and e.get('source_identity') and digest(e['source_identity']) in f['control_identities']:
                failures.append('FORBIDDEN_SIDE_EFFECT'); forbidden = True; effect = True
            # Declarative deny rules may fail closed on semantic evidence. They never grant identity or success.
            if e.get('event_type') == 1 and set(e.get('text') or ()).intersection(f['forbidden_event_text']):
                failures.append('FORBIDDEN_SIDE_EFFECT'); forbidden = True
        baseline = cursor.get('baseline_security_state', {})
        coverage = cursor.get('security_observability', {})
        observable = (coverage.get('status') == 'COMPLETE' and coverage.get('independent_channel') is True and
                      coverage.get('continuous_coverage') is True and bool(coverage.get('evidence_refs')) and
                      set(f['required_state_selectors']) <= set(coverage.get('selectors', ())) and
                      all(k in baseline and baseline[k] is not None for k in f['required_state_selectors']) and bool(valid))
        matches = []
        source_active = False
        for p in valid:
            states = p.get('security_state', {})
            observable &= all(k in states and states[k] is not None for k in f['required_state_selectors'])
            if any(k in states and k in baseline and states[k] != baseline[k] for k in f['required_state_selectors']):
                forbidden = True; effect = True; failures.append('FORBIDDEN_SIDE_EFFECT')
            markers = set(p.get('markers', ()))
            if (p.get('package') != contract['expected_package'] or
                    p.get('modal') != f['allowed_modal'] or markers.intersection(f['forbidden_markers'])):
                forbidden = True; failures.append('FORBIDDEN_SIDE_EFFECT')
            is_source = p.get('root_signature') in contract['source_screen_signatures']
            source_active |= is_source
            match = destination_matches(p, contract)
            matches.append(match)
        # Two separated final observations, with the same structure; no cherry-picking early transient success.
        count = contract['minimum_stable_observations']
        tail = valid[-count:]
        stable = (not stale and len(tail) == count and all(matches[-count:]) and
                  len({p.get('root_signature') for p in tail}) == 1 and
                  all(tail[i+1]['device_uptime_ms'] - tail[i]['device_uptime_ms'] >= contract['settle_ms'] for i in range(count-1)))
        closed = events('C5_COLLECTION_CLOSED')
        complete = (len(closed) == 1 and owned(closed[0]['payload'], request) and
                    closed[0]['payload'].get('probe_id') == cursor['probe_id'] and
                    integer(closed[0]['payload'].get('closed_uptime_ms')) and
                    closed[0]['payload']['closed_uptime_ms'] >= cursor['deadline_uptime_ms'] + cursor['receive_grace_ms'])
        complete = complete and not events('C5_OBSERVATION_INTERRUPTED')
        if stale: failures.append('POST_ACTION_PROBE_STALE')
        if not observable: failures.append('SECURITY_STATE_UNOBSERVABLE')
        if source_active: failures.append('SOURCE_SCREEN_STILL_ACTIVE')
        if not stable: failures.append('DESTINATION_UNSTABLE' if any(matches) else 'DESTINATION_NOT_REACHED')
        if forbidden: outcome = Outcome.FORBIDDEN_EFFECT
        elif ack['execution_state'] == 'UNKNOWN_EXECUTION_STATE': outcome = Outcome.UNKNOWN_EXECUTION_STATE
        elif ack['perform_action_return'] is not True:
            outcome = Outcome.DISPATCH_ONLY; failures.append(ack.get('failure_code') or 'PERFORM_ACTION_FALSE')
        elif ambiguous:
            outcome = Outcome.AMBIGUOUS_EFFECT; failures.append('ACTION_EFFECT_AMBIGUOUS')
        elif not complete:
            outcome = Outcome.UNKNOWN_EXECUTION_STATE; failures.append('UNKNOWN_EXECUTION_STATE')
        elif not effect:
            outcome = Outcome.NO_EFFECT; failures.append('ACTION_EFFECT_TIMEOUT')
        elif stable and observable and not stale and not failures: outcome = Outcome.NAVIGATION_CONFIRMED
        else:
            outcome = Outcome.EFFECT_CONFIRMED_WRONG_DESTINATION; failures.append('WRONG_DESTINATION')
        result = self._result(outcome, list(dict.fromkeys(failures)), normalized_events=normalized,
                    correlations=correlations, destination={'stable': stable, 'probe_count': len(valid)},
                    forbidden_effect_status='FORBIDDEN_SIDE_EFFECT' if forbidden else
                        'FORBIDDEN_EFFECT_PROVEN_ABSENT' if observable and complete else 'FORBIDDEN_EFFECT_NOT_OBSERVED',
                    event_references=[digest(e) for e in raw_events], probe_references=[digest(p) for p in probes],
                    target_identity=deepcopy(ack['resolved_target_identity']), destination_contract_id=contract['destination_contract_id'],
                    ownership=owner(request))
        result['c4_execution_state'] = ack['execution_state']
        result['c4_failure_code'] = ack['failure_code']
        result['action_dispatch_confirmed'] = True
        result['action_effect_confirmed'] = effect and not ambiguous
        # Durable finalization is still required; replay is evidence, not a publishable successful handoff.
        result['expected_navigation_confirmed'] = outcome == Outcome.NAVIGATION_CONFIRMED
        return result

    def handoff(self) -> dict:
        rows = self._rows()
        finals = [r for r in rows if r['event_type'] == 'C5_FINAL_VERDICT']
        require(len(finals) == 1, 'AUDIT_PERSIST_FAILED')
        row = finals[0]
        result = self.replay()
        require(result['audit_complete'] is True, 'AUDIT_PERSIST_FAILED')
        return dict(schema_version=VERSION, **owner(self.request), target_identity=result.get('target_identity'),
                    dispatch_confirmed=result['action_dispatch_confirmed'], effect_confirmed=result['action_effect_confirmed'],
                    navigation_confirmed=result['expected_navigation_confirmed'], verdict=result['result'],
                    destination_contract=result.get('destination_contract_id'), event_references=result.get('event_references', []),
                    probe_references=result.get('probe_references', []), audit_reference=row['record_hash'],
                    failure_codes=result['failure_codes'], visit_authority=False, requires_production_focus_reconciliation=True)
