"""Production decoder/factory/collector candidate binding regression coverage."""
from copy import deepcopy
from dataclasses import replace

import pytest

from talkback_lib import A11yAdbClient
from talkback_lib.reliable_hierarchy_schema import _freeze, _thaw, capture_canonical_json
from test_reliable_hierarchy_schema import _candidate, _capabilities, _payload, _transport_metadata, decode_reliable_hierarchy_payload
from tools.state_fingerprint_diagnostic import capture_observation


def _decoded(payload=None):
    payload = _payload(candidates=[_candidate(text='one'), _candidate(text='two', resource_id='app:id/two')]) if payload is None else payload
    return decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(), transport_metadata=_transport_metadata())


def _capture(decoded, mutate_snapshot=None):
    client = A11yAdbClient(start_monitor=False)
    acquisitions = []
    client.dump_hierarchy_decoded = lambda **kw: acquisitions.append(kw) or decoded
    client._run = lambda command, **kw: ('Physical size: 1080x2400' if command == ['shell', 'wm', 'size'] else '')
    client.get_focus = lambda **kw: pytest.fail('legacy focus fallback')
    client.dump_hierarchy = lambda **kw: pytest.fail('legacy hierarchy fallback')
    actual_factory = client.get_traversal_candidate_snapshot
    snapshots = []
    def factory(**kw):
        snapshot = actual_factory(**kw)
        snapshots.append(snapshot)
        return mutate_snapshot(snapshot) if mutate_snapshot else snapshot
    client.get_traversal_candidate_snapshot = factory
    result = capture_observation(client, 'serial', scenario_id='fixture')
    assert len(acquisitions) == 1 and len(snapshots) <= 1
    return result, snapshots[0] if snapshots else None


def _rejected(result):
    assert result['nodes'] == [] and result['capture_authority'] is None
    assert result['snapshot_coherent'] is False
    assert result['focus_capture_id'] is None and result['geometry_capture_id'] is None


def test_real_decoder_factory_collector_binding_and_raw_separation():
    payload = _payload(candidates=[_candidate(text='one'), _candidate(text='two', resource_id='app:id/two')])
    decoded = _decoded(payload)
    result, snapshot = _capture(decoded)
    assert 'traversalCandidates' not in decoded.raw_hierarchy and 'traversalCandidates' not in snapshot.raw_hierarchy
    assert decoded.validated_candidate_projection is not None
    assert snapshot.candidates == payload['traversalCandidates']['candidates']
    assert result['snapshot_coherent'] is True
    assert result['capture_authority']['capture_key'] == decoded.capture_authority.capture_key
    assert result['hierarchy_capture_id'] == decoded.capture_authority.capture_key
    from tb_runner.phase3_context import resolve_phase3_context
    assert result['activity_name'] is None
    assert resolve_phase3_context(result)['status'] != 'VERIFIED_PLUGIN_CONTEXT'


def test_transport_stub_runs_real_decoder_and_snapshot_factory_once():
    payload = _payload(candidates=[_candidate(text='one'), _candidate(text='two', resource_id='app:id/two')])
    client = A11yAdbClient(start_monitor=False)
    calls = []
    def transport(**kwargs):
        calls.append(kwargs)
        client._last_hierarchy_capabilities = _capabilities()
        client._last_hierarchy_transport_metadata = _transport_metadata()
        return deepcopy(payload)
    client.dump_hierarchy = transport
    client._dump_tree_legacy = lambda **kw: pytest.fail('legacy tree fallback')
    client.get_focus = lambda **kw: pytest.fail('legacy focus fallback')
    client._run = lambda command, **kw: ('Physical size: 1080x2400' if command == ['shell', 'wm', 'size'] else '')
    result = capture_observation(client, 'serial', scenario_id='fixture')
    snapshot = client._last_traversal_candidate_snapshot
    assert len(calls) == 1
    assert result['snapshot_coherent'] is True and result['hierarchy_capture_id'] == snapshot.decoded.capture_authority.capture_key
    assert 'traversalCandidates' not in snapshot.raw_hierarchy
    assert snapshot.candidates == payload['traversalCandidates']['candidates']
    assert result['activity_name'] is None
    from tb_runner.phase3_context import resolve_phase3_context
    assert resolve_phase3_context(result)['status'] != 'VERIFIED_PLUGIN_CONTEXT'

def test_retained_projection_is_deeply_immutable_lossless_and_input_isolated():
    payload = _payload(candidates=[_candidate(text='', description=None, bounds=(-10, 0, 0, -1), clickable=False)])
    projection = payload['traversalCandidates']
    projection['candidates'][0]['extension'] = {'null': None, 'false': False, 'zero': 0}
    from talkback_lib.reliable_hierarchy_schema import capture_canonical_sha256
    projection.pop('candidate_digest'); projection['candidate_digest'] = capture_canonical_sha256(projection)
    payload['captureEnvelope']['candidate_digest'] = projection['candidate_digest']
    decoded = _decoded(payload)
    original = capture_canonical_json(decoded.validated_candidate_projection)
    payload['traversalCandidates']['candidates'][0]['extension']['zero'] = 99
    assert capture_canonical_json(decoded.validated_candidate_projection) == original
    with pytest.raises(TypeError): decoded.validated_candidate_projection['completion']['complete'] = False
    with pytest.raises(TypeError): decoded.validated_candidate_projection['candidates'][0]['extension']['zero'] = 1
    result, snapshot = _capture(decoded)
    assert result['snapshot_coherent'] is True and 'extension' not in snapshot.candidates[0]
    assert snapshot.candidates[0]['boundsInScreen'] == {'l': -10, 't': 0, 'r': 0, 'b': -1}


@pytest.mark.parametrize('mutation', ['remove','substitute','reorder','count','completion','contract','digest_missing','digest_bad','source_root','root_capture','root_ref','window','bool_for_int'])
def test_retained_projection_mutations_fail_closed(mutation):
    decoded = _decoded()
    p = _thaw(decoded.validated_candidate_projection)
    if mutation == 'remove': p['candidates'].pop()
    elif mutation == 'substitute': p['candidates'][0]['text'] = 'foreign'
    elif mutation == 'reorder': p['candidates'].reverse()
    elif mutation == 'count': p['completion']['candidate_count'] += 1
    elif mutation == 'completion': p['completion']['complete'] = False
    elif mutation == 'contract': p['candidate_contract_version'] = 'foreign'
    elif mutation == 'digest_missing': p.pop('candidate_digest')
    elif mutation == 'digest_bad': p['candidate_digest'] = '0'*64
    elif mutation == 'source_root': p['source_root_digest'] = '0'*64
    elif mutation == 'root_capture': p['rootCaptureId'] = 'foreign'
    elif mutation == 'root_ref': p['traversalRootRef'] = 'windows[1].root'
    elif mutation == 'window': p['traversalRootWindowId'] += 1
    elif mutation == 'bool_for_int': p['traversalRootWindowId'] = True
    result, _ = _capture(replace(decoded, validated_candidate_projection=_freeze(p)))
    _rejected(result)


@pytest.mark.parametrize('mutation', ['rows','order','type','typed_rows','typed_count','typed_contract','decoded_schema','decoded_request','decoded_window','capability','raw_completion','mutable_projection','mutable_typed','completion','missing_projection','foreign_projection','foreign_authority'])
def test_consumed_and_decoded_candidate_substitution_is_rejected(mutation):
    decoded = _decoded()
    if mutation == 'typed_rows':
        v=decoded.traversal_candidates; decoded=replace(decoded,traversal_candidates=replace(v,candidates=tuple(reversed(v.candidates))))
    elif mutation == 'typed_count': decoded=replace(decoded,traversal_candidates=replace(decoded.traversal_candidates,candidate_count=True))
    elif mutation == 'typed_contract': decoded=replace(decoded,traversal_candidates=replace(decoded.traversal_candidates,contract_version='foreign'))
    elif mutation == 'decoded_schema': decoded=replace(decoded,schema_version='foreign')
    elif mutation == 'decoded_request': decoded=replace(decoded,request_id='foreign')
    elif mutation == 'decoded_window': decoded=replace(decoded,traversal_root_window_id=True)
    elif mutation == 'capability': decoded=replace(decoded,capability_verified=False)
    elif mutation == 'raw_completion': decoded=replace(decoded,raw_completion_valid=False)
    elif mutation == 'mutable_projection': decoded=replace(decoded,validated_candidate_projection=_thaw(decoded.validated_candidate_projection))
    elif mutation == 'mutable_typed': decoded=replace(decoded,traversal_candidates=replace(decoded.traversal_candidates,candidates=tuple(_thaw(x) for x in decoded.traversal_candidates.candidates)))
    elif mutation == 'completion': decoded=replace(decoded,traversal_candidates=replace(decoded.traversal_candidates,complete=False))
    elif mutation == 'missing_projection': decoded=replace(decoded,validated_candidate_projection=None)
    elif mutation in ('foreign_projection','foreign_authority'):
        foreign = _decoded(_payload(candidates=[_candidate(text='foreign')]))
        decoded=replace(decoded,**({'validated_candidate_projection':foreign.validated_candidate_projection} if mutation=='foreign_projection' else {'capture_authority':foreign.capture_authority}))
    def mutate(snapshot):
        if mutation not in ('rows','order','type'): return snapshot
        response=deepcopy(snapshot.response)
        if mutation=='rows': response['nodes'][0]['text']='foreign'
        elif mutation=='order': response['nodes'].reverse()
        else: response['nodes'][0]['boundsInScreen']['l']=False
        return replace(snapshot,response=response)
    result, _ = _capture(decoded,mutate)
    _rejected(result)


@pytest.mark.parametrize('mutation', ['window','package','class','bounds','source_id','subtree','root_ref','raw_schema','window_id','raw_window','flags','request','nonce','service','generation','sequence','schema','canonicalization','root_id_version','payload_schema','build_identity','missing_control'])
def test_root_and_transfer_mutations_stay_fail_closed(mutation):
    decoded=_decoded()
    def mutate(snapshot):
        raw=deepcopy(snapshot.raw_hierarchy); transfer=_thaw(snapshot.decoded.transport_metadata)
        root=raw['windows'][0]['root']
        if mutation=='window': root['windowId'] += 1
        elif mutation=='package': root['packageName']='foreign.pkg'
        elif mutation=='class': root['className']='foreign.Class'
        elif mutation=='bounds': root['boundsInScreen']['r'] += 1
        elif mutation=='source_id': root['sourceNodeId']='foreign'
        elif mutation=='subtree': root['children'][0]['text']='foreign'
        elif mutation=='root_ref': raw['traversalRootRef']='windows[1].root'
        elif mutation=='raw_schema': raw['schemaVersion']='foreign'
        elif mutation=='window_id': raw['windows'][0]['id']=True
        elif mutation=='raw_window': raw['traversalRootWindowId']=True
        elif mutation=='flags':
            other=deepcopy(raw['windows'][0]); other['id'] += 1; other['root']['windowId'] += 1
            other['active']=True; other['focused']=True
            raw['windows'][0]['active']=False; raw['windows'][0]['focused']=False; raw['windows'].append(other)
        elif mutation=='request': transfer['control']['request_id']='foreign'
        elif mutation=='nonce': transfer['control']['client_nonce']='different'
        elif mutation=='service': transfer['control']['service_instance_id']='foreign'
        elif mutation=='generation': transfer['control']['generation'] += 1
        elif mutation=='sequence': transfer['control']['capture_sequence'] += 1
        elif mutation=='schema': transfer['control']['capture_envelope_schema_version']='foreign'
        elif mutation=='canonicalization': transfer['control']['capture_canonicalization_version']='foreign'
        elif mutation=='build_identity': transfer['control']['helper_build_identity']={'build_id':'foreign'}
        elif mutation=='root_id_version': transfer['control']['capture_root_id_version']='foreign'
        elif mutation=='payload_schema': transfer['control']['payload_schema_version']='foreign'
        elif mutation=='missing_control': transfer.pop('control')
        return replace(snapshot,raw_hierarchy=raw,decoded=replace(snapshot.decoded,transport_metadata=_freeze(transfer)))
    result, _ = _capture(decoded,mutate)
    _rejected(result)

@pytest.mark.parametrize('field', ['selected_window', 'root_window', 'raw_window', 'decoded_window'])
def test_boolean_true_never_matches_integer_window_one(field):
    decoded = _decoded(_payload(window_ids=(1,)))
    def mutate(snapshot):
        raw = deepcopy(snapshot.raw_hierarchy)
        changed = snapshot.decoded
        if field == 'selected_window': raw['windows'][0]['id'] = True
        elif field == 'root_window': raw['windows'][0]['root']['windowId'] = True
        elif field == 'raw_window': raw['traversalRootWindowId'] = True
        else: changed = replace(changed, traversal_root_window_id=True)
        return replace(snapshot, raw_hierarchy=raw, decoded=changed)
    result, _ = _capture(decoded, mutate)
    _rejected(result)


@pytest.mark.parametrize('forged', [False, True])
def test_missing_or_forged_capture_authority_is_not_promoted(forged):
    decoded = _decoded()
    authority = replace(decoded.capture_authority, validation_seal='0' * 64) if forged else None
    result, _ = _capture(replace(decoded, capture_authority=authority))
    assert result['capture_authority'] is None and result['snapshot_coherent'] is False
    assert result['nodes'] == [] and result['focus_capture_id'] is None

@pytest.mark.parametrize('condition', ['valid', 'stale_scope', 'stale_epoch', 'failed_capture'])
def test_transport_through_current_collection_handoff_fail_closed(condition, monkeypatch):
    from types import SimpleNamespace
    from talkback_lib.exploration_evidence_clock import EvidenceClock
    from tb_runner import collection_flow
    from tb_runner.dynamic_context import DestinationOwnership
    from tb_runner.phase3_context import resolve_phase3_context

    payload = _payload(candidates=[_candidate(text='one'), _candidate(text='two', resource_id='app:id/two')])
    client = A11yAdbClient(start_monitor=False)
    clock = EvidenceClock(scope_id='transport-test')
    client._adb_device.shadow_evidence_clock = clock
    client._phase6d_exploration_shadow_runtime = object()
    calls = []
    def transport(**kwargs):
        calls.append(kwargs)
        client._last_hierarchy_capabilities = _capabilities()
        client._last_hierarchy_transport_metadata = _transport_metadata()
        value = deepcopy(payload)
        if condition == 'stale_scope':
            clock.scope_id = 'replacement-scope'
        elif condition == 'stale_epoch':
            clock.action_epoch += 1
        elif condition == 'failed_capture':
            value['traversalCandidates']['candidates'][0]['text'] = 'tampered'
        return value
    client.dump_hierarchy = transport
    client._dump_tree_legacy = lambda **kw: pytest.fail('legacy tree fallback')
    client.get_focus = lambda **kw: pytest.fail('legacy focus fallback')
    client._run = lambda command, **kw: ('Physical size: 1080x2400' if command == ['shell', 'wm', 'size'] else '')
    row = {'scenario_id': 'fixture', 'scenario_run_id': 'run-1', 'step_index': 0}
    result = collection_flow._capture_phase6d3a_production_observation(client=client, dev='serial', row=row)
    assert len(calls) == 1
    observed = row['state_graph_observation']
    if condition == 'valid':
        assert result is not None and row['production_observation_capture_status'] == 'CURRENT'
        assert result['production_observation_current'] is True
        assert result['capture_id'] == result['hierarchy_capture_id'] == result['capture_authority']['capture_key']
        assert result['activity_name'] is None
        context = resolve_phase3_context(result)
        assert context['status'] == 'UNRESOLVED_CONTEXT'
        from test_phase4b_authority import gate, trusted, value
        planner, _ = value(context=context['status'])
        decision = gate(planner, evidence=trusted(plugin_context_required=True))
        assert not decision.allowed and decision.reason == 'CONTEXT_INSUFFICIENT'
        with pytest.raises(ValueError, match='Trusted normal plugin entry required'):
            DestinationOwnership(result)
    else:
        assert result is None and row['production_observation_capture_status'] == 'UNALIGNED'
        assert observed['production_observation_current'] is False
        if condition == 'failed_capture':
            assert observed['nodes'] == [] and observed['capture_authority'] is None
        else:
            assert observed['_exploration_observation']['capture_complete'] is False
    assert clock.receipts == [] and clock.receipt_sequence == 0
    monkeypatch.setenv('TB_TRAVERSAL_IDENTITY_V2_ENABLED', '1')
    progress, visit = collection_flow._resolve_traversal_evidence_decision(
        client=client, row=row, state=SimpleNamespace())
    assert not visit.visited and progress.verdict == 'INDETERMINATE'
    assert visit.consumed and visit.consumption_source == 'legacy_fallback'


def test_real_capture_handoff_binds_scroll_to_current_owner_and_result():
    from phase6d_capture_support import bind_reliable_capture_envelope
    from talkback_lib.exploration_evidence_clock import EvidenceClock
    from tb_runner import collection_flow
    from tb_runner.state_graph import build_phase6e_scroll_evidence, recorder_from_existing_rows

    raw = _payload()
    root = raw['windows'][0]['root']
    root.update(className='android.widget.ScrollView', scrollable=True, isScrollable=True,
                actions=[{'id': 16908346}])
    raw['nodes'][0] = deepcopy(root)
    container = {'path': '0.0', 'boundsInScreen': root['boundsInScreen'],
                 'className': root['className'], 'isScrollable': True,
                 'actions': [{'id': 16908346}]}
    raw['scrollCapabilities'] = [container]
    before, transfer_before = bind_reliable_capture_envelope(
        raw, request_id='before', process_epoch='epoch', generation=1,
        service_instance_id='service', capture_sequence=1)
    changed = deepcopy(raw)
    changed['windows'][0]['root']['children'][0]['boundsInScreen'] = {'l': 10, 't': 40, 'r': 70, 'b': 75}
    changed['nodes'][0] = deepcopy(changed['windows'][0]['root'])
    after, transfer_after = bind_reliable_capture_envelope(
        changed, request_id='after', process_epoch='epoch', generation=1,
        service_instance_id='service', capture_sequence=2)
    decoded = iter([decode_reliable_hierarchy_payload(before, capabilities=_capabilities(), transport_metadata=transfer_before),
                    decode_reliable_hierarchy_payload(after, capabilities=_capabilities(), transport_metadata=transfer_after)])
    client = A11yAdbClient(start_monitor=False)
    clock = EvidenceClock(scope_id='scroll-test')
    client._adb_device.shadow_evidence_clock = clock
    client._phase6d_exploration_shadow_runtime = object()
    client.dump_hierarchy_decoded = lambda **kw: next(decoded)
    client._run = lambda command, **kw: 'Physical size: 100x100' if command == ['shell', 'wm', 'size'] else ''
    source_row = {'scenario_id': 'fixture', 'scenario_run_id': 'run-1', 'step_index': 1}
    source = collection_flow._capture_phase6d3a_production_observation(client=client, dev='serial', row=source_row)
    clock.dispatch(['shell', 'am', 'broadcast', '-a', 'com.iotpart.sqe.talkbackhelper.SCROLL', '--es', 'reqId', 'scroll-1'])
    result_row = {'scenario_id': 'fixture', 'scenario_run_id': 'run-1', 'step_index': 1}
    result = collection_flow._capture_phase6d3a_production_observation(client=client, dev='serial', row=result_row)
    transition = {
        'action_type': 'SCROLL_FORWARD', 'direction': 'down', 'action_success': True,
        'action_request_id': 'scroll-1', 'action_result_request_id': 'scroll-1',
        'action_result_correlated': True,
        'action_target': {'mode': 'EXPLICIT_CONTAINER', 'container_path': '0.0',
                          'container_bounds': '[0,0][100,80]'},
        'action_result': {'reqId': 'scroll-1', 'action': 'SCROLL_FORWARD', 'success': True,
                          'actionAttempted': True, 'explicitTarget': True, 'scrollContainerPath': '0.0'},
    }
    evidence = build_phase6e_scroll_evidence(source, result, transition)
    assert evidence['classification'] == 'SCROLL_MOVED'
    assert evidence['owner']['path'] == '0.0'
    row = {**source_row, 'phase6e_scroll_source_observation': source,
           'phase6e_scroll_source_marker': source['_exploration_observation'],
           'phase6e_scroll_result_observation': result,
           'phase6e_scroll_result_marker': result['_exploration_observation'],
           'scroll_transition': transition}
    graph = recorder_from_existing_rows([row], run_id='run-1', scenario_id='fixture').to_dict()
    assert len(graph['edges']) == 1
    assert graph['edges'][0]['visit_outcome'] == 'VISIT_UNKNOWN'
