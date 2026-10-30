from copy import deepcopy
from dataclasses import replace
from talkback_lib import TraversalCandidateSnapshot
from talkback_lib.reliable_hierarchy_schema import (
    ReliableHierarchyPayload, TraversalCandidateProjection, _freeze, _seal_capture_authority,
    capture_canonical_sha256, capture_root_id, legacy_dump_tree_response,
    RAW_SCHEMA_VERSION, CANDIDATE_SCHEMA_VERSION, CANDIDATE_CONTRACT_VERSION,
    CANDIDATE_ALGORITHM_VERSION, CANDIDATE_ANALYZER_VERSION, CANDIDATE_PROFILE_ID,
    CANDIDATE_PROFILE_VERSION,
)
from test_reliable_hierarchy_schema import _candidate
from tb_runner.traversal_reliability import normalized_bounds


def fixture_snapshot(hierarchy, transfer, *, mutation=None):
    """Convert legacy handoff fixtures to the explicit separated snapshot contract."""
    hierarchy, transfer = deepcopy(hierarchy), deepcopy(transfer)
    envelope = hierarchy['captureEnvelope']
    index = int(envelope['root_ref'].split('[')[1].split(']')[0])
    root = hierarchy['windows'][index]['root']
    rows = []
    for n in hierarchy['traversalCandidates']['candidates']:
        b = n.get('boundsInScreen', {})
        if isinstance(b, dict): bounds = tuple(b.get(k, 0) for k in ('l', 't', 'r', 'b'))
        else: bounds = tuple(int(x) for x in normalized_bounds(b).split(','))
        rows.append(_candidate(text=n.get('text'), description=n.get('contentDescription'),
            resource_id=n.get('viewIdResourceName'), class_name=n.get('className'), bounds=tuple(bounds),
            clickable=bool(n.get('clickable')), focusable=bool(n.get('focusable')),
            visible=n.get('visibleToUser', n.get('isVisibleToUser', True)) is True,
            focused=n.get('focused') is True, accessibility_focused=n.get('accessibilityFocused') is True,
            effective_clickable=bool(n.get('effectiveClickable', n.get('clickable')))))
    projection = {'schema_version':CANDIDATE_SCHEMA_VERSION,'candidate_contract_version':CANDIDATE_CONTRACT_VERSION,
        'algorithmVersion':CANDIDATE_ALGORITHM_VERSION,'analyzerVersion':CANDIDATE_ANALYZER_VERSION,
        'profileId':CANDIDATE_PROFILE_ID,'profileVersion':CANDIDATE_PROFILE_VERSION,
        'completion':{'status':'COMPLETE','complete':True,'candidate_count':len(rows)},
        'traversalRootRef':envelope['root_ref'],'traversalRootWindowId':envelope['root_ref'] and root['windowId'],
        'canScrollDown':False,'scrollAxisContract':'axis-v1','candidates':rows,
        'source_root_digest':envelope['root_digest'],'rootCaptureId':capture_root_id(envelope)}
    projection['candidate_digest']=capture_canonical_sha256(projection)
    envelope['candidate_digest']=projection['candidate_digest']
    authority=_seal_capture_authority(envelope,root,projection,transfer)
    assert authority is not None
    view=TraversalCandidateProjection(schema_version=CANDIDATE_SCHEMA_VERSION,contract_version=CANDIDATE_CONTRACT_VERSION,
        algorithm_version=CANDIDATE_ALGORITHM_VERSION,analyzer_version=CANDIDATE_ANALYZER_VERSION,
        profile_id=CANDIDATE_PROFILE_ID,profile_version=CANDIDATE_PROFILE_VERSION,completion_status='COMPLETE',
        complete=True,candidate_count=len(rows),traversal_root_ref=authority.root_ref,
        traversal_root_window_id=authority.hierarchy_window_id,can_scroll_down=False,
        scroll_axis_contract='axis-v1',candidates=tuple(_freeze(x) for x in rows))
    hierarchy['traversalCandidates']=projection
    if mutation: mutation(hierarchy,transfer)
    retained=hierarchy.pop('traversalCandidates')
    decoded=ReliableHierarchyPayload(raw_hierarchy=_freeze(hierarchy),traversal_candidates=view,
        schema_version=RAW_SCHEMA_VERSION,request_id=authority.request_id,platform_api_level=34,
        traversal_root_ref=authority.root_ref,traversal_root_window_id=authority.hierarchy_window_id,
        raw_node_count=1,raw_completion_valid=True,scroll_metadata=_freeze({}),device_collection=None,
        transport_metadata=_freeze(transfer),capability_verified=True,capture_authority=authority,
        validated_candidate_projection=_freeze(retained))
    return TraversalCandidateSnapshot(response=legacy_dump_tree_response(decoded),
        raw_hierarchy=deepcopy(hierarchy),decoded=decoded)