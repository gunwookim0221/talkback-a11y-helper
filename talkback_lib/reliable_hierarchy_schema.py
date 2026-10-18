"""Strict host decoder and legacy-shape adapter for reliable hierarchy v2.

This module only decodes Helper-produced facts. It deliberately does not
reconstruct candidate selection, labels, deduplication, or traversal order.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
import re


RAW_SCHEMA_VERSION = "service-hierarchy-v2"
LEGACY_RAW_SCHEMA_VERSION = "service-hierarchy-v1"
CANDIDATE_SCHEMA_VERSION = "legacy-traversal-candidates.v1"
CANDIDATE_CONTRACT_VERSION = "legacy-traversal-candidate-contract.v1"
CANDIDATE_ALGORITHM_VERSION = "2.76.3"
CANDIDATE_ANALYZER_VERSION = "1.11.1"
CANDIDATE_PROFILE_ID = "oneconnect-traversal-policy"
CANDIDATE_PROFILE_VERSION = "1.0.0"
MAX_RAW_NODES = 4096
MAX_RAW_DEPTH = 80
_ROOT_REF = re.compile(r"^windows\[(0|[1-9][0-9]*)\]\.root$")

_LEGACY_NODE_FIELDS = (
    "text",
    "contentDescription",
    "className",
    "viewIdResourceName",
    "boundsInScreen",
    "clickable",
    "focusable",
    "isVisibleToUser",
    "focused",
    "accessibilityFocused",
    "isTopAppBar",
    "isBottomNavigationBar",
    "hasClickableDescendant",
    "hasFocusableDescendant",
    "effectiveClickable",
    "actionableDescendantResourceId",
    "actionableDescendantClassName",
    "actionableDescendantContentDescription",
)
_CANDIDATE_BOOL_FIELDS = (
    "clickable",
    "focusable",
    "isVisibleToUser",
    "focused",
    "accessibilityFocused",
    "isTopAppBar",
    "isBottomNavigationBar",
    "hasClickableDescendant",
    "hasFocusableDescendant",
    "effectiveClickable",
)
_CANDIDATE_NULLABLE_STRING_FIELDS = (
    "text",
    "contentDescription",
    "className",
    "viewIdResourceName",
    "actionableDescendantResourceId",
    "actionableDescendantClassName",
    "actionableDescendantContentDescription",
)
_NODE_NULLABLE_STRING_FIELDS = (
    "text",
    "contentDescription",
    "viewIdResourceName",
    "className",
    "packageName",
)
_NODE_BOOL_FIELDS = (
    "clickable",
    "effectiveClickable",
    "enabled",
    "focusable",
    "focused",
    "inputFocused",
    "accessibilityFocused",
    "selected",
    "scrollable",
    "isScrollable",
    "checkable",
    "checked",
    "visibleToUser",
    "isVisibleToUser",
    "rangeInfoPresent",
)


class ReliableHierarchySchemaError(ValueError):
    """A fail-closed reliable hierarchy or candidate-contract error."""

    def __init__(self, reason: str, request_id: str = "") -> None:
        self.reason = reason
        self.request_id = request_id
        suffix = f" req_id={request_id}" if request_id else ""
        super().__init__(f"HIERARCHY_SCHEMA:{reason}{suffix}")


@dataclass(frozen=True)
class TraversalCandidateProjection:
    schema_version: str
    contract_version: str
    algorithm_version: str
    analyzer_version: str
    profile_id: str
    profile_version: str
    completion_status: str
    complete: bool
    candidate_count: int
    traversal_root_ref: str
    traversal_root_window_id: int
    can_scroll_down: bool
    scroll_axis_contract: str
    candidates: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ReliableHierarchyPayload:
    """Validated, read-only views over the raw body and Helper candidate list."""

    raw_hierarchy: Mapping[str, Any]
    traversal_candidates: TraversalCandidateProjection
    schema_version: str
    request_id: str
    platform_api_level: int
    traversal_root_ref: str
    traversal_root_window_id: int
    raw_node_count: int
    raw_completion_valid: bool
    scroll_metadata: Mapping[str, Any]
    device_collection: Mapping[str, Any] | None
    transport_metadata: Mapping[str, Any]
    capability_verified: bool

    @property
    def helper_build_identity(self) -> Mapping[str, Any] | None:
        value = self.transport_metadata.get("helper_build_identity")
        return value if isinstance(value, Mapping) else None

    @property
    def generation(self) -> int | None:
        value = self.transport_metadata.get("generation")
        return value if type(value) is int else None

    @property
    def process_epoch(self) -> str | None:
        value = self.transport_metadata.get("process_epoch")
        return value if isinstance(value, str) else None

    @property
    def service_instance_id(self) -> str | None:
        value = self.transport_metadata.get("service_instance_id")
        return value if isinstance(value, str) else None


def _fail(reason: str, request_id: str = "") -> None:
    raise ReliableHierarchySchemaError(reason, request_id)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _require_string_or_null(value: Mapping[str, Any], key: str, request_id: str) -> None:
    if key not in value or (value[key] is not None and not isinstance(value[key], str)):
        _fail("MALFORMED_CANDIDATE", request_id)


def _validate_bounds(value: Any, request_id: str, *, candidate: bool) -> None:
    if not isinstance(value, Mapping):
        _fail("MALFORMED_CANDIDATE" if candidate else "RAW_NODE_REFERENCE_INVALID", request_id)
    keys = ("l", "t", "r", "b")
    if any(type(value.get(key)) is not int for key in keys):
        _fail("MALFORMED_CANDIDATE" if candidate else "RAW_NODE_REFERENCE_INVALID", request_id)


def _validate_candidate(candidate: Any, request_id: str) -> Mapping[str, Any]:
    if not isinstance(candidate, Mapping):
        _fail("MALFORMED_CANDIDATE", request_id)
    if any(key not in candidate for key in _LEGACY_NODE_FIELDS):
        _fail("MALFORMED_CANDIDATE", request_id)
    for key in _CANDIDATE_NULLABLE_STRING_FIELDS:
        _require_string_or_null(candidate, key, request_id)
    _validate_bounds(candidate.get("boundsInScreen"), request_id, candidate=True)
    if any(type(candidate.get(key)) is not bool for key in _CANDIDATE_BOOL_FIELDS):
        _fail("MALFORMED_CANDIDATE", request_id)
    return candidate


def _validate_raw_node(
    node: Any,
    *,
    api_level: int,
    request_id: str,
    depth: int,
    is_root: bool,
    expected_child_index: int | None = None,
    expected_window_id: int | None = None,
) -> int:
    if not isinstance(node, Mapping) or depth > MAX_RAW_DEPTH:
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    for key in _NODE_NULLABLE_STRING_FIELDS:
        if key not in node or (node[key] is not None and not isinstance(node[key], str)):
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    for key in _NODE_BOOL_FIELDS:
        if key not in node or type(node[key]) is not bool:
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    if "boundsInScreen" not in node:
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    _validate_bounds(node.get("boundsInScreen"), request_id, candidate=False)
    if api_level >= 28:
        if type(node.get("screenReaderFocusable")) is not bool:
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    elif node.get("screenReaderFocusable", object()) is not None:
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    if "screenReaderFocusable" not in node:
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    node_window_id = node.get("windowId")
    if type(node_window_id) is not int:
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    if expected_window_id is not None and node_window_id != expected_window_id:
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    if expected_child_index is not None and (
        type(node.get("childIndex")) is not int or node.get("childIndex") != expected_child_index
    ):
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    children = node.get("children")
    if not isinstance(children, list):
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    count = 1
    for index, child in enumerate(children):
        count += _validate_raw_node(
            child,
            api_level=api_level,
            request_id=request_id,
            depth=depth + 1,
            is_root=False,
            expected_child_index=index,
            expected_window_id=node_window_id,
        )
        if count > MAX_RAW_NODES:
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    return count


def validate_candidate_capabilities(
    capabilities: Mapping[str, Any], *, request_id: str = ""
) -> None:
    """Require explicit PFD, raw-v2, and candidate-contract capability proof."""
    if not isinstance(capabilities, Mapping):
        _fail("CANDIDATE_CAPABILITY_REQUIRED", request_id)
    payload_schema = capabilities.get("payload_schema_version")
    if payload_schema is None:
        _fail("CANDIDATE_CAPABILITY_REQUIRED", request_id)
    if payload_schema != RAW_SCHEMA_VERSION:
        _fail("UNSUPPORTED_HIERARCHY_SCHEMA", request_id)
    raw_versions = capabilities.get("supported_payload_schema_versions")
    if not isinstance(raw_versions, list) or RAW_SCHEMA_VERSION not in raw_versions:
        _fail("CANDIDATE_CAPABILITY_REQUIRED", request_id)
    candidate_versions = capabilities.get("supported_candidate_schema_versions")
    if not isinstance(candidate_versions, list) or CANDIDATE_SCHEMA_VERSION not in candidate_versions:
        _fail("CANDIDATE_CAPABILITY_REQUIRED", request_id)
    if capabilities.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION:
        _fail("UNSUPPORTED_CANDIDATE_SCHEMA", request_id)
    if capabilities.get("candidate_contract_version") != CANDIDATE_CONTRACT_VERSION:
        _fail("CANDIDATE_CONTRACT_MISMATCH", request_id)
    declared = capabilities.get("capabilities")
    required = {"content_provider_pfd", "service_hierarchy_v2", CANDIDATE_SCHEMA_VERSION}
    if not isinstance(declared, list) or not required.issubset(set(declared)):
        _fail("CANDIDATE_CAPABILITY_REQUIRED", request_id)


def _decode_reliable_hierarchy_payload(
    payload: Mapping[str, Any],
    *,
    capability_verified: bool,
    transport_metadata: Mapping[str, Any] | None = None,
) -> ReliableHierarchyPayload:
    """Decode and validate raw hierarchy and candidate envelope independently."""
    if not isinstance(payload, Mapping):
        _fail("RAW_NODE_REFERENCE_INVALID")
    request_id = payload.get("reqId") if isinstance(payload.get("reqId"), str) else ""
    if payload.get("schemaVersion") != RAW_SCHEMA_VERSION:
        _fail("UNSUPPORTED_HIERARCHY_SCHEMA", request_id)
    if payload.get("success") is not True or not request_id:
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    api_level = payload.get("platformApiLevel")
    if type(api_level) is not int or api_level < 26:
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)

    windows = payload.get("windows")
    roots = payload.get("nodes")
    if not isinstance(windows, list) or not windows or not isinstance(roots, list) or len(roots) != len(windows):
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    actual_node_count = 0
    window_roots: list[Mapping[str, Any]] = []
    for index, window in enumerate(windows):
        if not isinstance(window, Mapping) or type(window.get("id")) is not int:
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
        root = window.get("root")
        if not isinstance(root, Mapping) or roots[index] != root:
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
        if root.get("windowId") != window.get("id"):
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
        actual_node_count += _validate_raw_node(
            root,
            api_level=api_level,
            request_id=request_id,
            depth=0,
            is_root=True,
            expected_window_id=window.get("id"),
        )
        window_roots.append(root)
        if actual_node_count > MAX_RAW_NODES:
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    if type(payload.get("nodeCount")) is not int or payload.get("nodeCount") != actual_node_count:
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)

    root_ref = payload.get("traversalRootRef")
    match = _ROOT_REF.fullmatch(root_ref) if isinstance(root_ref, str) else None
    if not match:
        _fail("TRAVERSAL_ROOT_MISSING", request_id)
    window_index = int(match.group(1))
    if window_index >= len(windows):
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    root_window_id = payload.get("traversalRootWindowId")
    window_root = window_roots[window_index]
    if (type(root_window_id) is not int or root_window_id != windows[window_index].get("id")
            or root_window_id != window_root.get("windowId")):
        _fail("TRAVERSAL_ROOT_MISMATCH", request_id)

    projection = payload.get("traversalCandidates")
    if projection is None:
        _fail("MISSING_TRAVERSAL_CANDIDATES", request_id)
    if not isinstance(projection, Mapping):
        _fail("MALFORMED_CANDIDATE", request_id)
    if projection.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        _fail("UNSUPPORTED_CANDIDATE_SCHEMA", request_id)
    if projection.get("candidate_contract_version") != CANDIDATE_CONTRACT_VERSION:
        _fail("CANDIDATE_CONTRACT_MISMATCH", request_id)
    for key, expected in (
        ("algorithmVersion", CANDIDATE_ALGORITHM_VERSION),
        ("analyzerVersion", CANDIDATE_ANALYZER_VERSION),
        ("profileId", CANDIDATE_PROFILE_ID),
        ("profileVersion", CANDIDATE_PROFILE_VERSION),
    ):
        if projection.get(key) != expected:
            _fail("CANDIDATE_CONTRACT_MISMATCH", request_id)
    completion = projection.get("completion")
    if (not isinstance(completion, Mapping) or completion.get("status") != "COMPLETE"
            or completion.get("complete") is not True):
        _fail("CANDIDATE_INCOMPLETE", request_id)
    candidates = projection.get("candidates")
    if not isinstance(candidates, list):
        _fail("MALFORMED_CANDIDATE", request_id)
    if type(completion.get("candidate_count")) is not int or completion.get("candidate_count") != len(candidates):
        _fail("CANDIDATE_COUNT_MISMATCH", request_id)
    if projection.get("traversalRootRef") != root_ref:
        _fail("TRAVERSAL_ROOT_MISMATCH", request_id)
    if (type(projection.get("traversalRootWindowId")) is not int
            or projection.get("traversalRootWindowId") != root_window_id):
        _fail("TRAVERSAL_ROOT_MISMATCH", request_id)
    if type(projection.get("canScrollDown")) is not bool or projection.get("scrollAxisContract") != "axis-v1":
        _fail("CANDIDATE_CONTRACT_MISMATCH", request_id)
    validated_candidates = tuple(_validate_candidate(candidate, request_id) for candidate in candidates)

    if transport_metadata is not None:
        _validate_transport_metadata(transport_metadata, request_id)

    raw = {key: value for key, value in payload.items() if key != "traversalCandidates"}
    scroll: dict[str, Any] = {
        "canScrollDown": projection["canScrollDown"],
        "scrollAxisContract": projection["scrollAxisContract"],
    }
    if "scrollCapabilities" in payload:
        if not isinstance(payload["scrollCapabilities"], list):
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
        scroll["scrollCapabilities"] = payload["scrollCapabilities"]
    device_collection = payload.get("deviceCollection")
    if device_collection is not None and not isinstance(device_collection, Mapping):
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    context = dict(transport_metadata or {})
    header = context.get("header")
    control = context.get("control")
    identity = None
    if isinstance(control, Mapping):
        identity = control.get("helper_build_identity")
        context.setdefault("generation", control.get("generation"))
        context.setdefault("process_epoch", control.get("process_epoch"))
        context.setdefault("service_instance_id", control.get("service_instance_id"))
    if identity is None and isinstance(header, Mapping):
        identity = header.get("helper_build_identity")
    if identity is not None:
        context["helper_build_identity"] = identity

    return ReliableHierarchyPayload(
        raw_hierarchy=_freeze(raw),
        traversal_candidates=TraversalCandidateProjection(
            schema_version=CANDIDATE_SCHEMA_VERSION,
            contract_version=CANDIDATE_CONTRACT_VERSION,
            algorithm_version=CANDIDATE_ALGORITHM_VERSION,
            analyzer_version=CANDIDATE_ANALYZER_VERSION,
            profile_id=CANDIDATE_PROFILE_ID,
            profile_version=CANDIDATE_PROFILE_VERSION,
            completion_status="COMPLETE",
            complete=True,
            candidate_count=len(validated_candidates),
            traversal_root_ref=root_ref,
            traversal_root_window_id=root_window_id,
            can_scroll_down=projection["canScrollDown"],
            scroll_axis_contract=projection["scrollAxisContract"],
            candidates=tuple(_freeze(candidate) for candidate in validated_candidates),
        ),
        schema_version=RAW_SCHEMA_VERSION,
        request_id=request_id,
        platform_api_level=api_level,
        traversal_root_ref=root_ref,
        traversal_root_window_id=root_window_id,
        raw_node_count=actual_node_count,
        raw_completion_valid=True,
        scroll_metadata=_freeze(scroll),
        device_collection=_freeze(device_collection) if device_collection is not None else None,
        transport_metadata=_freeze(context),
        capability_verified=capability_verified,
    )


def decode_reliable_hierarchy_payload(
    payload: Mapping[str, Any],
    *,
    capabilities: Mapping[str, Any] | None = None,
    transport_metadata: Mapping[str, Any] | None = None,
) -> ReliableHierarchyPayload:
    """Decode a candidate-capable payload only after explicit Helper capability proof."""
    request_id = payload.get("reqId") if isinstance(payload, Mapping) and isinstance(payload.get("reqId"), str) else ""
    validate_candidate_capabilities(capabilities, request_id=request_id)
    return _decode_reliable_hierarchy_payload(
        payload,
        capability_verified=True,
        transport_metadata=transport_metadata,
    )


def validate_reliable_hierarchy_payload_body(
    payload: Mapping[str, Any],
    *,
    transport_metadata: Mapping[str, Any] | None = None,
) -> None:
    """Validate artifact contents without exposing candidate data to callers.

    The transport uses this when validating an artifact without a capability
    response. Candidate-consuming APIs must use the capability-gated decoder.
    """
    _decode_reliable_hierarchy_payload(
        payload,
        capability_verified=False,
        transport_metadata=transport_metadata,
    )


def _validate_transport_metadata(metadata: Mapping[str, Any], request_id: str) -> None:
    if not isinstance(metadata, Mapping):
        _fail("RAW_NODE_REFERENCE_INVALID", request_id)
    header = metadata.get("header")
    control = metadata.get("control")
    records: list[Mapping[str, Any]] = []
    for record in (header, control):
        if record is not None and not isinstance(record, Mapping):
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
        if isinstance(record, Mapping):
            if record.get("request_id") != request_id:
                _fail("RAW_NODE_REFERENCE_INVALID", request_id)
            if record.get("payload_schema_version") != RAW_SCHEMA_VERSION:
                _fail("UNSUPPORTED_HIERARCHY_SCHEMA", request_id)
            records.append(record)
    if len(records) == 2:
        for key in ("client_nonce", "generation", "process_epoch", "service_instance_id", "helper_build_identity"):
            if records[0].get(key) != records[1].get(key):
                _fail("RAW_NODE_REFERENCE_INVALID", request_id)


def adapt_traversal_candidates_to_legacy(
    payload: ReliableHierarchyPayload,
) -> list[dict[str, Any]]:
    """Return dump_tree()-compatible candidate dictionaries in Helper order."""
    if not isinstance(payload, ReliableHierarchyPayload):
        _fail("MISSING_TRAVERSAL_CANDIDATES")
    if not payload.capability_verified:
        _fail("CANDIDATE_CAPABILITY_REQUIRED", payload.request_id)
    return [
        {key: _thaw(candidate[key]) for key in _LEGACY_NODE_FIELDS}
        for candidate in payload.traversal_candidates.candidates
    ]


def get_reliable_traversal_candidates(
    body: Mapping[str, Any],
    *,
    capabilities: Mapping[str, Any],
    transport_metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Capability-gated candidate API for offline comparison and future C4 use."""
    decoded = decode_reliable_hierarchy_payload(
        body,
        capabilities=capabilities,
        transport_metadata=transport_metadata,
    )
    return adapt_traversal_candidates_to_legacy(decoded)


def legacy_dump_tree_response(payload: ReliableHierarchyPayload) -> dict[str, Any]:
    """Represent the original Kotlin dump response envelope without rewriting nodes."""
    if not isinstance(payload, ReliableHierarchyPayload) or not payload.capability_verified:
        _fail("CANDIDATE_CAPABILITY_REQUIRED", getattr(payload, "request_id", ""))
    return {
        "algorithmVersion": payload.traversal_candidates.algorithm_version,
        "canScrollDown": payload.traversal_candidates.can_scroll_down,
        "nodes": adapt_traversal_candidates_to_legacy(payload),
    }
