from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType

import pytest

from talkback_lib import A11yAdbClient
from talkback_lib.hierarchy_file_transport import HierarchyTransportError
from talkback_lib.reliable_hierarchy_schema import (
    CANDIDATE_ALGORITHM_VERSION,
    CANDIDATE_ANALYZER_VERSION,
    CANDIDATE_CONTRACT_VERSION,
    CANDIDATE_PROFILE_ID,
    CANDIDATE_PROFILE_VERSION,
    CANDIDATE_SCHEMA_VERSION,
    LEGACY_RAW_SCHEMA_VERSION,
    RAW_SCHEMA_VERSION,
    ReliableHierarchySchemaError,
    adapt_traversal_candidates_to_legacy,
    decode_reliable_hierarchy_payload,
    get_reliable_traversal_candidates,
    legacy_dump_tree_response,
    validate_candidate_capabilities,
    capture_canonical_json,
    capture_canonical_sha256,
    capture_root_id,
    validate_capture_authority,
    validate_reliable_hierarchy_payload_body,
    CAPTURE_ENVELOPE_SCHEMA_VERSION,
    CAPTURE_CANONICALIZATION_VERSION,
    CAPTURE_ROOT_IDENTITY_VERSION,
)


def _raw_node(
    *,
    window_id: int,
    api_level: int,
    text: str | None = None,
    resource_id: str | None = None,
    bounds: tuple[int, int, int, int] = (0, 0, 100, 80),
    children: list[dict] | None = None,
    screen_reader_focusable: bool | None = False,
    range_info_present: bool = False,
    child_index: int | None = None,
) -> dict:
    node = {
        "text": text,
        "contentDescription": None,
        "viewIdResourceName": resource_id,
        "className": "android.widget.FrameLayout",
        "packageName": "com.samsung.android.oneconnect",
        "windowId": window_id,
        "boundsInScreen": dict(zip(("l", "t", "r", "b"), bounds)),
        "clickable": False,
        "effectiveClickable": False,
        "enabled": True,
        "focusable": False,
        "focused": False,
        "inputFocused": False,
        "accessibilityFocused": False,
        "selected": False,
        "scrollable": False,
        "isScrollable": False,
        "checkable": False,
        "checked": False,
        "visibleToUser": True,
        "isVisibleToUser": True,
        "screenReaderFocusable": screen_reader_focusable if api_level >= 28 else None,
        "rangeInfoPresent": range_info_present,
        "actions": [],
        "children": children or [],
    }
    if child_index is not None:
        node["childIndex"] = child_index
    return node


def _candidate(
    *,
    text: str | None = "Example",
    description: str | None = None,
    resource_id: str | None = "app:id/example",
    class_name: str | None = "android.widget.Button",
    bounds: tuple[int, int, int, int] = (0, 0, 100, 80),
    clickable: bool = True,
    focusable: bool = True,
    visible: bool = True,
    focused: bool = False,
    accessibility_focused: bool = False,
    top_bar: bool = False,
    bottom_bar: bool = False,
    has_clickable_descendant: bool = False,
    has_focusable_descendant: bool = False,
    effective_clickable: bool = True,
    actionable_resource_id: str | None = None,
    actionable_class_name: str | None = None,
    actionable_description: str | None = None,
) -> dict:
    return {
        "text": text,
        "contentDescription": description,
        "className": class_name,
        "viewIdResourceName": resource_id,
        "boundsInScreen": dict(zip(("l", "t", "r", "b"), bounds)),
        "clickable": clickable,
        "focusable": focusable,
        "isVisibleToUser": visible,
        "focused": focused,
        "accessibilityFocused": accessibility_focused,
        "isTopAppBar": top_bar,
        "isBottomNavigationBar": bottom_bar,
        "hasClickableDescendant": has_clickable_descendant,
        "hasFocusableDescendant": has_focusable_descendant,
        "effectiveClickable": effective_clickable,
        "actionableDescendantResourceId": actionable_resource_id,
        "actionableDescendantClassName": actionable_class_name,
        "actionableDescendantContentDescription": actionable_description,
    }


def _capabilities() -> dict:
    return {
        "payload_schema_version": RAW_SCHEMA_VERSION,
        "supported_payload_schema_versions": [RAW_SCHEMA_VERSION],
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "supported_candidate_schema_versions": [CANDIDATE_SCHEMA_VERSION],
        "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
        "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "supported_capture_envelope_schema_versions": [CAPTURE_ENVELOPE_SCHEMA_VERSION],
        "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
        "supported_capture_canonicalization_versions": [CAPTURE_CANONICALIZATION_VERSION],
        "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
        "supported_capture_root_id_versions": [CAPTURE_ROOT_IDENTITY_VERSION],
        "capabilities": ["content_provider_pfd", "service_hierarchy_v2", CANDIDATE_SCHEMA_VERSION,
                         CAPTURE_ENVELOPE_SCHEMA_VERSION, CAPTURE_CANONICALIZATION_VERSION,
                         CAPTURE_ROOT_IDENTITY_VERSION],
    }


def _payload(
    *,
    candidates: list[dict] | None = None,
    api_level: int = 34,
    root_ref: str = "windows[0].root",
    raw_root_ref: str | None = None,
    candidate_root_ref: str | None = None,
    window_ids: tuple[int, ...] = (17,),
    candidate_root_window_id: int | None = None,
    raw_root_window_id: int | None = None,
    raw_root_screen_reader_focusable: bool | None = True,
    root_range_info_present: bool = True,
    scroll_capabilities: list[dict] | None = None,
    device_collection: dict | None = None,
) -> dict:
    candidate_rows = deepcopy(candidates if candidates is not None else [_candidate()])
    roots: list[dict] = []
    total_nodes = 0
    for index, window_id in enumerate(window_ids):
        child = _raw_node(
            window_id=window_id,
            api_level=api_level,
            text="nested raw wrapper",
            bounds=(-8, 11, 40, 60),
            child_index=0,
            screen_reader_focusable=False,
        )
        root = _raw_node(
            window_id=window_id,
            api_level=api_level,
            text="Raw screen root",
            resource_id=f"app:id/window_root_{index}",
            children=[child],
            screen_reader_focusable=(
                raw_root_screen_reader_focusable if api_level >= 28 else None
            ),
            range_info_present=root_range_info_present,
        )
        roots.append(root)
        total_nodes += 2
    active_index = len(window_ids) - 1
    raw_ref = raw_root_ref if raw_root_ref is not None else f"windows[{active_index}].root"
    candidate_ref = candidate_root_ref if candidate_root_ref is not None else raw_ref
    raw_window_id = raw_root_window_id if raw_root_window_id is not None else window_ids[active_index]
    candidate_window_id = (
        candidate_root_window_id if candidate_root_window_id is not None else raw_window_id
    )
    payload = {
        "reqId": "request-123",
        "success": True,
        "schemaVersion": RAW_SCHEMA_VERSION,
        "platformApiLevel": api_level,
        "traversalRootRef": raw_ref,
        "traversalRootWindowId": raw_window_id,
        "nodeCount": total_nodes,
        "nodes": deepcopy(roots),
        "windows": [
            {
                "order": index,
                "id": window_id,
                "type": 1,
                "layer": index,
                "title": f"Window {index}",
                "active": index == active_index,
                "focused": index == active_index,
                "boundsInScreen": {"l": 0, "t": 0, "r": 1080, "b": 2400},
                "root": roots[index],
            }
            for index, window_id in enumerate(window_ids)
        ],
        "traversalCandidates": {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
            "algorithmVersion": CANDIDATE_ALGORITHM_VERSION,
            "analyzerVersion": CANDIDATE_ANALYZER_VERSION,
            "profileId": CANDIDATE_PROFILE_ID,
            "profileVersion": CANDIDATE_PROFILE_VERSION,
            "completion": {
                "status": "COMPLETE",
                "complete": True,
                "candidate_count": len(candidate_rows),
            },
            "traversalRootRef": candidate_ref,
            "traversalRootWindowId": candidate_window_id,
            "canScrollDown": True,
            "scrollAxisContract": "axis-v1",
            "candidates": candidate_rows,
        },
    }
    if raw_ref.startswith("windows[") and raw_ref.endswith("].root"):
        raw_window_index = int(raw_ref[len("windows["):-len("].root")])
        if raw_window_index < len(roots):
            digest_root = roots[raw_window_index]
        else:
            digest_root = roots[active_index]
    else:
        digest_root = roots[active_index]
    root_digest = capture_canonical_sha256(digest_root)
    envelope = {
        "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "canonicalization": CAPTURE_CANONICALIZATION_VERSION,
        "request_id": payload["reqId"],
        "process_epoch": "epoch-1",
        "generation": 3,
        "service_instance_id": "service-1",
        "capture_sequence": 2,
        "root_ref": raw_ref,
        "root_digest": root_digest,
    }
    projection = payload["traversalCandidates"]
    projection["source_root_digest"] = root_digest
    projection["rootCaptureId"] = capture_root_id(envelope)
    projection["candidate_digest"] = capture_canonical_sha256(projection)
    envelope["candidate_digest"] = projection["candidate_digest"]
    payload["captureEnvelope"] = envelope
    if scroll_capabilities is not None:
        payload["scrollCapabilities"] = deepcopy(scroll_capabilities)
    if device_collection is not None:
        payload["deviceCollection"] = deepcopy(device_collection)
    return payload


def _transport_metadata() -> dict:
    identity = {"build_id": "a" * 64, "git_commit": "b" * 40}
    return {
        "header": {
            "request_id": "request-123",
            "client_nonce": "nonce-1",
            "process_epoch": "epoch-1",
            "generation": 3,
            "service_instance_id": "service-1",
            "payload_schema_version": RAW_SCHEMA_VERSION,
            "capture_sequence": 2,
            "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
            "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
            "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
            "helper_build_identity": identity,
        },
        "control": {
            "request_id": "request-123",
            "client_nonce": "nonce-1",
            "payload_schema_version": RAW_SCHEMA_VERSION,
            "capture_sequence": 2,
            "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
            "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
            "generation": 3,
            "process_epoch": "epoch-1",
            "service_instance_id": "service-1",
            "capture_sequence": 2,
            "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
            "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
            "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
            "helper_build_identity": identity,
        },
    }


_decode_reliable_hierarchy_payload = decode_reliable_hierarchy_payload

def decode_reliable_hierarchy_payload(payload, *, capabilities=None, transport_metadata=None):
    if capabilities is not None and transport_metadata is None:
        transport_metadata = _transport_metadata()
    return _decode_reliable_hierarchy_payload(
        payload, capabilities=capabilities, transport_metadata=transport_metadata,
    )



def test_v2_payload_decodes_raw_and_candidate_layers_separately_and_read_only():
    body = _payload()
    decoded = decode_reliable_hierarchy_payload(
        body,
        capabilities=_capabilities(),
        transport_metadata=_transport_metadata(),
    )

    assert decoded.schema_version == RAW_SCHEMA_VERSION
    assert decoded.raw_hierarchy["platformApiLevel"] == 34
    assert "traversalCandidates" not in decoded.raw_hierarchy
    assert decoded.traversal_candidates.candidate_count == 1
    assert decoded.request_id == "request-123"
    assert decoded.helper_build_identity["build_id"] == "a" * 64
    assert decoded.generation == 3
    assert decoded.process_epoch == "epoch-1"
    assert decoded.service_instance_id == "service-1"
    assert decoded.capture_authority is not None
    assert decoded.capture_authority.capture_sequence == 2
    assert decoded.capture_authority.root_digest == body["captureEnvelope"]["root_digest"]
    assert isinstance(decoded.raw_hierarchy, MappingProxyType)
    assert isinstance(decoded.traversal_candidates.candidates, tuple)
    with pytest.raises(TypeError):
        decoded.raw_hierarchy["success"] = False


def test_candidate_adapter_exactly_matches_legacy_dump_tree_oracle_and_order():
    rows = [
        _candidate(text="Later on screen", resource_id="same-id", bounds=(4, 500, 90, 580)),
        _candidate(text="Earlier on screen", resource_id="same-id", bounds=(4, 10, 90, 90)),
        _candidate(text="Same-bounds duplicate", resource_id="duplicate", bounds=(4, 10, 90, 90)),
        _candidate(text="Same-bounds duplicate retained", resource_id="duplicate", bounds=(4, 10, 90, 90)),
    ]
    body = _payload(candidates=rows)
    decoded = decode_reliable_hierarchy_payload(body, capabilities=_capabilities())
    actual = legacy_dump_tree_response(decoded)
    oracle = {
        "algorithmVersion": CANDIDATE_ALGORITHM_VERSION,
        "canScrollDown": True,
        "nodes": rows,
    }

    assert actual == oracle
    assert adapt_traversal_candidates_to_legacy(decoded) == oracle["nodes"]
    assert [node["text"] for node in actual["nodes"]] == [
        "Later on screen", "Earlier on screen",
        "Same-bounds duplicate", "Same-bounds duplicate retained",
    ]
    assert actual["nodes"][0]["viewIdResourceName"] == actual["nodes"][1]["viewIdResourceName"]
    assert actual["nodes"][0]["boundsInScreen"] != actual["nodes"][1]["boundsInScreen"]
    assert actual["nodes"][2]["boundsInScreen"] == actual["nodes"][3]["boundsInScreen"]
    for key in ("viewIdResourceName", "text", "contentDescription", "className", "boundsInScreen"):
        assert actual["nodes"][0][key] == rows[0][key]


def test_null_empty_missing_false_zero_and_negative_bounds_are_not_normalized():
    row = _candidate(
        text="",
        description=None,
        resource_id=None,
        bounds=(-10, 0, 0, -1),
        clickable=False,
        effective_clickable=False,
    )
    row["optionalDiagnostic"] = None
    decoded = decode_reliable_hierarchy_payload(_payload(candidates=[row]), capabilities=_capabilities())
    adapted = adapt_traversal_candidates_to_legacy(decoded)[0]

    assert adapted["text"] == ""
    assert adapted["contentDescription"] is None
    assert adapted["viewIdResourceName"] is None
    assert adapted["clickable"] is False
    assert adapted["boundsInScreen"] == {"l": -10, "t": 0, "r": 0, "b": -1}
    assert "optionalDiagnostic" not in adapted
    assert "screenReaderFocusable" not in adapted


@pytest.mark.parametrize(
    ("api_level", "screen_reader"),
    [(28, True), (34, False), (26, None), (27, None)],
)
def test_raw_screen_reader_focusable_preserves_supported_false_and_unsupported_null(api_level, screen_reader):
    decoded = decode_reliable_hierarchy_payload(
        _payload(api_level=api_level, raw_root_screen_reader_focusable=screen_reader),
        capabilities=_capabilities(),
    )
    root = decoded.raw_hierarchy["windows"][0]["root"]
    assert root["screenReaderFocusable"] is screen_reader
    assert root["rangeInfoPresent"] is True
    assert root["children"][0]["rangeInfoPresent"] is False


def test_scroll_and_device_collection_metadata_are_exposed_without_moving_them_to_nodes():
    scroll = [{"path": "0.0", "axis": "VERTICAL", "actions": []}]
    collection = {"cards": [{"resourceId": "card", "bounds": "-2,0,50,60"}]}
    decoded = decode_reliable_hierarchy_payload(
        _payload(scroll_capabilities=scroll, device_collection=collection),
        capabilities=_capabilities(),
    )

    assert decoded.scroll_metadata["canScrollDown"] is True
    assert decoded.scroll_metadata["scrollAxisContract"] == "axis-v1"
    assert decoded.scroll_metadata["scrollCapabilities"] == (MappingProxyType({"path": "0.0", "axis": "VERTICAL", "actions": ()}),)
    assert decoded.device_collection["cards"][0]["resourceId"] == "card"
    assert "canScrollDown" not in adapt_traversal_candidates_to_legacy(decoded)[0]


def test_home_monitor_candidate_adapter_preserves_projected_order_and_is_observational_only():
    rows = [
        _candidate(text="Home Monitor", class_name="android.widget.TextView", clickable=False,
                   focusable=False, effective_clickable=False),
        _candidate(text="More options", resource_id="app:id/plugin_more_options",
                   class_name="android.widget.ImageButton", bounds=(900, 80, 1040, 180)),
        _candidate(text="Armed Away", resource_id="app:id/shmBannerAwayButton",
                   has_clickable_descendant=True, effective_clickable=True,
                   actionable_resource_id="app:id/away_action",
                   actionable_class_name="android.widget.Button",
                   actionable_description="Away"),
        _candidate(text="Armed Stay", resource_id="app:id/shmBannerStayButton",
                   has_focusable_descendant=True, effective_clickable=True),
        _candidate(text="Disarm", resource_id="app:id/shmBannerDisarmedButton",
                   bounds=(10, 680, 400, 780)),
    ]
    decoded = decode_reliable_hierarchy_payload(_payload(candidates=rows), capabilities=_capabilities())
    adapted = adapt_traversal_candidates_to_legacy(decoded)

    assert [node["text"] for node in adapted] == ["Home Monitor", "More options", "Armed Away", "Armed Stay", "Disarm"]
    assert [node["viewIdResourceName"] for node in adapted[1:]] == [
        "app:id/plugin_more_options", "app:id/shmBannerAwayButton",
        "app:id/shmBannerStayButton", "app:id/shmBannerDisarmedButton",
    ]
    assert all("action_permitted" not in node and "authorized" not in node for node in adapted)
    assert adapted[1]["effectiveClickable"] is True
    assert adapted[2]["actionableDescendantResourceId"] == "app:id/away_action"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda value: value.update(schemaVersion=LEGACY_RAW_SCHEMA_VERSION), "UNSUPPORTED_HIERARCHY_SCHEMA"),
        (lambda value: value.pop("schemaVersion"), "UNSUPPORTED_HIERARCHY_SCHEMA"),
        (lambda value: value.pop("traversalCandidates"), "MISSING_TRAVERSAL_CANDIDATES"),
        (lambda value: value["traversalCandidates"].update(schema_version="legacy-traversal-candidates.v2"), "UNSUPPORTED_CANDIDATE_SCHEMA"),
        (lambda value: value["traversalCandidates"].update(candidate_contract_version="unknown"), "CANDIDATE_CONTRACT_MISMATCH"),
        (lambda value: value["traversalCandidates"]["completion"].update(complete=False), "CANDIDATE_INCOMPLETE"),
        (lambda value: value["traversalCandidates"]["completion"].update(candidate_count=9), "CANDIDATE_COUNT_MISMATCH"),
        (lambda value: value.pop("traversalRootRef"), "TRAVERSAL_ROOT_MISSING"),
        (lambda value: value["traversalCandidates"].update(traversalRootRef="windows[1].root"), "TRAVERSAL_ROOT_MISMATCH"),
        (lambda value: value.update(traversalRootRef="windows[3].root"), "RAW_NODE_REFERENCE_INVALID"),
        (lambda value: value["traversalCandidates"]["candidates"][0].pop("text"), "MALFORMED_CANDIDATE"),
        (lambda value: value["traversalCandidates"]["candidates"][0].update(focused="false"), "MALFORMED_CANDIDATE"),
    ],
)
def test_schema_and_candidate_contract_errors_fail_closed(mutate, reason):
    body = _payload()
    mutate(body)
    with pytest.raises(ReliableHierarchySchemaError) as error:
        decode_reliable_hierarchy_payload(body, capabilities=_capabilities())
    assert error.value.reason == reason


def test_candidate_root_window_mismatch_is_rejected():
    body = _payload(window_ids=(17, 23), candidate_root_window_id=17)
    with pytest.raises(ReliableHierarchySchemaError, match="TRAVERSAL_ROOT_MISMATCH"):
        decode_reliable_hierarchy_payload(body, capabilities=_capabilities())


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"payload_schema_version": LEGACY_RAW_SCHEMA_VERSION}, "UNSUPPORTED_HIERARCHY_SCHEMA"),
        ({"candidate_schema_version": "unsupported"}, "UNSUPPORTED_CANDIDATE_SCHEMA"),
        ({"candidate_contract_version": "unsupported"}, "CANDIDATE_CONTRACT_MISMATCH"),
        ({"supported_candidate_schema_versions": []}, "CANDIDATE_CAPABILITY_REQUIRED"),
        ({"capture_root_id_version": "unsupported"}, "CAPTURE_ROOT_IDENTITY_CAPABILITY_REQUIRED"),
        ({"supported_capture_root_id_versions": []}, "CAPTURE_ROOT_IDENTITY_CAPABILITY_REQUIRED"),
        ({"capabilities": ["content_provider_pfd"]}, "CANDIDATE_CAPABILITY_REQUIRED"),
    ],
)
def test_helper_candidate_capability_must_be_explicit(changed, reason):
    capabilities = {**_capabilities(), **changed}
    with pytest.raises(ReliableHierarchySchemaError) as error:
        validate_candidate_capabilities(capabilities)
    assert error.value.reason == reason


def test_candidate_api_requires_capability_and_v1_cannot_be_adapted():
    with pytest.raises(ReliableHierarchySchemaError, match="CANDIDATE_CAPABILITY_REQUIRED"):
        validate_candidate_capabilities({})
    with pytest.raises(ReliableHierarchySchemaError, match="CANDIDATE_CAPABILITY_REQUIRED"):
        decode_reliable_hierarchy_payload(_payload())
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_ENVELOPE_CAPABILITY_REQUIRED"):
        validate_reliable_hierarchy_payload_body(_payload(), transport_metadata=_transport_metadata())
    with pytest.raises(ReliableHierarchySchemaError, match="UNSUPPORTED_HIERARCHY_SCHEMA"):
        decode_reliable_hierarchy_payload(
            {**_payload(), "schemaVersion": LEGACY_RAW_SCHEMA_VERSION},
            capabilities=_capabilities(),
        )


def test_transport_metadata_must_match_request_and_schema():
    wrong_request = _transport_metadata()
    wrong_request["control"]["request_id"] = "stale-request"
    with pytest.raises(ReliableHierarchySchemaError, match="RAW_NODE_REFERENCE_INVALID"):
        decode_reliable_hierarchy_payload(
            _payload(), capabilities=_capabilities(), transport_metadata=wrong_request
        )

    wrong_schema = _transport_metadata()
    wrong_schema["header"]["payload_schema_version"] = LEGACY_RAW_SCHEMA_VERSION
    with pytest.raises(ReliableHierarchySchemaError, match="UNSUPPORTED_HIERARCHY_SCHEMA"):
        decode_reliable_hierarchy_payload(
            _payload(), capabilities=_capabilities(), transport_metadata=wrong_schema
        )


def test_candidate_api_returns_legacy_nodes_only_after_capability_and_contract_validation():
    body = _payload()
    nodes = get_reliable_traversal_candidates(
        body, capabilities=_capabilities(), transport_metadata=_transport_metadata(),
    )
    assert nodes == body["traversalCandidates"]["candidates"]
    assert "screenReaderFocusable" not in nodes[0]
    assert [node["text"] for node in nodes] == ["Example"]
    assert all(node.get("text") != "nested raw wrapper" for node in nodes)


def test_client_decoded_api_and_default_candidate_api_share_validated_v2_payload():
    client = A11yAdbClient(start_monitor=False)
    body = _payload()
    client.dump_hierarchy = lambda **_kwargs: body
    client._last_hierarchy_capabilities = _capabilities()
    client._last_hierarchy_transport_metadata = _transport_metadata()
    client.check_helper_status = lambda **_kwargs: True
    legacy_broadcasts = []
    client._broadcast = lambda *args, **kwargs: legacy_broadcasts.append((args, kwargs))

    decoded = client.dump_hierarchy_decoded()
    snapshot = client.get_traversal_candidate_snapshot()

    assert decoded.raw_hierarchy["schemaVersion"] == RAW_SCHEMA_VERSION
    assert adapt_traversal_candidates_to_legacy(decoded) == body["traversalCandidates"]["candidates"]
    assert snapshot.candidates == body["traversalCandidates"]["candidates"]
    assert snapshot.response["algorithmVersion"] == body["traversalCandidates"]["algorithmVersion"]
    assert snapshot.raw_hierarchy["schemaVersion"] == RAW_SCHEMA_VERSION
    assert legacy_broadcasts == []


def test_client_decoded_api_rejects_absent_helper_candidate_capability():
    client = A11yAdbClient(start_monitor=False)
    client.dump_hierarchy = lambda **_kwargs: _payload()
    client._last_hierarchy_capabilities = None

    with pytest.raises(HierarchyTransportError, match="CANDIDATE_CAPABILITY_REQUIRED"):
        client.dump_hierarchy_decoded()


def test_capture_canonical_json_v1_cross_language_golden_vector():
    value = {"z": "é/😀", "a": -(1 << 63), "A": "\u007f\n"}
    canonical = r'{"A":"\u007f\n","a":-9223372036854775808,"z":"\u00e9/\ud83d\ude00"}'
    assert capture_canonical_json(value) == canonical
    assert capture_canonical_sha256(value) == "97f5f3ff991358c6eed142b77437d1c6989edb9044a442ab21a04b9cd8d80045"


def test_capture_root_id_v1_cross_language_golden_vector():
    envelope = {
        "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "canonicalization": CAPTURE_CANONICALIZATION_VERSION,
        "request_id": "request-1",
        "process_epoch": "epoch-1",
        "generation": 3,
        "service_instance_id": "service-1",
        "capture_sequence": 2,
        "root_ref": "windows[1].root",
        "root_digest": "a" * 64,
    }
    assert capture_root_id(envelope) == "fde8456b615adfa22d816cd1bcf7f8762265d96d3e39a2be2ee402070db50c71"


def test_capture_authority_fails_closed_on_digest_mutation_and_transfer_replay():
    payload = _payload()
    payload["captureEnvelope"]["root_digest"] = "0" * 64
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_ROOT_DIGEST_MISMATCH"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())
    payload = _payload()
    metadata = _transport_metadata()
    metadata["control"]["capture_sequence"] = 3
    with pytest.raises(ReliableHierarchySchemaError, match="RAW_NODE_REFERENCE_INVALID|CAPTURE_TRANSFER_IDENTITY_MISMATCH"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(), transport_metadata=metadata)


@pytest.mark.parametrize("mutation", ["missing", "bad"])
def test_candidate_digest_missing_or_bad_fails_closed(mutation):
    payload = _payload()
    projection = payload["traversalCandidates"]
    if mutation == "missing":
        projection.pop("candidate_digest")
    else:
        projection["candidate_digest"] = "0" * 64
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_CANDIDATE_DIGEST_MISMATCH"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())


def test_reused_window_id_with_different_subtree_is_rejected():
    payload = _payload(window_ids=(17, 17))
    assert payload["windows"][0]["root"] != payload["windows"][1]["root"]
    with pytest.raises(ReliableHierarchySchemaError, match="DUPLICATE_WINDOW_ID"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())


def test_sequential_capture_reusing_window_id_rejects_prior_subtree_digest():
    first_payload = _payload(window_ids=(17,))
    first = decode_reliable_hierarchy_payload(
        first_payload, capabilities=_capabilities(), transport_metadata=_transport_metadata())
    assert first.capture_authority is not None
    assert first.capture_authority.hierarchy_window_id == 17

    later_payload = deepcopy(first_payload)
    later_root = later_payload["windows"][0]["root"]
    later_root["children"][0]["text"] = "different screen after window id reuse"
    later_payload["nodes"][0] = deepcopy(later_root)
    later_payload["captureEnvelope"]["capture_sequence"] = 3
    later_transfer = _transport_metadata()
    later_transfer["header"]["capture_sequence"] = 3
    later_transfer["control"]["capture_sequence"] = 3

    assert later_payload["windows"][0]["id"] == first.capture_authority.hierarchy_window_id
    assert later_root != first_payload["windows"][0]["root"]
    assert capture_canonical_sha256(later_root) != first.capture_authority.root_digest
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_ROOT_DIGEST_MISMATCH"):
        decode_reliable_hierarchy_payload(
            later_payload, capabilities=_capabilities(), transport_metadata=later_transfer)


def test_capture_authority_binds_exact_root_package_window_bytes_only():
    payload = _payload()
    root = payload["windows"][0]["root"]
    decoded = _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                                 transport_metadata=_transport_metadata())
    authority = decoded.capture_authority
    assert authority is not None
    assert authority.hierarchy_package_name == root["packageName"]
    assert authority.hierarchy_window_id == root["windowId"]
    assert authority.hierarchy_root_class_name == root["className"]
    assert authority.hierarchy_root_source_node_id == root.get("sourceNodeId")
    assert authority.hierarchy_root_bounds == tuple(
        root["boundsInScreen"][key] for key in ("l", "t", "r", "b"))
    assert authority.root_digest == capture_canonical_sha256(root)
    serialized = authority.to_dict()
    unsigned_self_hash = {key: value for key, value in serialized.items()
                          if key != "validation_seal"}
    assert validate_capture_authority(unsigned_self_hash) is None
    unsigned_self_hash["capture_sequence"] += 1
    unsigned_self_hash["capture_key"] = capture_canonical_sha256({
        key: unsigned_self_hash[key] for key in (
            "schema_version", "canonicalization", "request_id", "process_epoch",
            "generation", "service_instance_id", "capture_sequence", "root_ref",
            "root_digest", "candidate_digest", "hierarchy_package_name", "hierarchy_window_id",
            "hierarchy_root_class_name", "hierarchy_root_source_node_id", "hierarchy_root_bounds",
        )
    })
    assert validate_capture_authority(unsigned_self_hash) is None
    forged_component = authority.to_dict()
    forged_component["component_activity_name"] = "pkg.ForgedActivity"
    assert validate_capture_authority(forged_component) is None

    payload_with_component = _payload()
    payload_with_component["captureEnvelope"]["component_activity_name"] = "pkg.ForgedActivity"
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_AUTHORITY_INVALID"):
        _decode_reliable_hierarchy_payload(payload_with_component, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())

    root["packageName"] = "pkg.changed"
    payload["nodes"][0]["packageName"] = "pkg.changed"
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_ROOT_DIGEST_MISMATCH"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())


def test_same_geometry_but_different_root_subtree_fails_exact_root_digest():
    payload = _payload()
    original_root = payload["windows"][0]["root"]
    changed_root = deepcopy(original_root)
    assert changed_root["packageName"] == original_root["packageName"]
    assert changed_root["windowId"] == original_root["windowId"]
    assert changed_root["boundsInScreen"] == original_root["boundsInScreen"]
    changed_root["children"][0]["text"] = "different same-window screen"
    payload["windows"][0]["root"] = changed_root
    payload["nodes"][0] = deepcopy(changed_root)
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_ROOT_DIGEST_MISMATCH"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())


@pytest.mark.parametrize("field,value", [
    ("request_id", "stale-request"),
    ("generation", 99),
    ("service_instance_id", "stale-service"),
    ("capture_sequence", 99),
])
def test_capture_envelope_request_generation_service_sequence_mismatch_fails_closed(field, value):
    payload = _payload()
    payload["captureEnvelope"][field] = value
    with pytest.raises(ReliableHierarchySchemaError):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())


@pytest.mark.parametrize("field,value", [
    ("schema_version", "phase6d-capture-envelope-v0"),
    ("canonicalization", "capture-canonical-json-v0"),
])
def test_old_capture_envelope_schema_or_canonicalization_fails_closed(field, value):
    payload = _payload()
    payload["captureEnvelope"][field] = value
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_ENVELOPE_VERSION_MISMATCH"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())


def test_missing_capture_envelope_schema_fails_closed():
    payload = _payload()
    payload["captureEnvelope"].pop("schema_version")
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_AUTHORITY_INVALID"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())


@pytest.mark.parametrize("record,field,value", [
    ("header", "request_id", "stale-request"),
    ("control", "generation", 99),
    ("header", "service_instance_id", "stale-service"),
    ("control", "capture_sequence", 99),
    ("header", "capture_root_id_version", "phase6d-root-capture-id-v0"),
])
def test_capture_transfer_header_and_control_must_match_envelope(record, field, value):
    metadata = _transport_metadata()
    metadata[record][field] = value
    with pytest.raises(ReliableHierarchySchemaError):
        _decode_reliable_hierarchy_payload(_payload(), capabilities=_capabilities(),
                                           transport_metadata=metadata)


@pytest.mark.parametrize("mutation", ["missing", "mismatch"])
def test_candidate_root_capture_id_missing_or_mismatched_fails_closed(mutation):
    payload = _payload()
    projection = payload["traversalCandidates"]
    if mutation == "missing":
        projection.pop("rootCaptureId")
    else:
        projection["rootCaptureId"] = "0" * 64
    projection["candidate_digest"] = capture_canonical_sha256(
        {key: value for key, value in projection.items() if key != "candidate_digest"})
    payload["captureEnvelope"]["candidate_digest"] = projection["candidate_digest"]
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_ROOT_CAPTURE_ID_MISMATCH"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())


@pytest.mark.parametrize("mutation", ["missing", "bad"])
def test_candidate_source_root_digest_missing_or_bad_fails_closed(mutation):
    payload = _payload()
    projection = payload["traversalCandidates"]
    if mutation == "missing":
        projection.pop("source_root_digest")
    else:
        projection["source_root_digest"] = "0" * 64
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_ROOT_DIGEST_MISMATCH"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())


def test_legacy_or_incomplete_payload_never_creates_capture_authority():
    payload = _payload()
    payload.pop("captureEnvelope")
    with pytest.raises(ReliableHierarchySchemaError, match="CAPTURE_ENVELOPE_MISSING"):
        _decode_reliable_hierarchy_payload(payload, capabilities=_capabilities(),
                                           transport_metadata=_transport_metadata())
