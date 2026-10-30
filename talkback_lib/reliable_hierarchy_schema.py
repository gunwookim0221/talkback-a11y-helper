"""Strict host decoder and legacy-shape adapter for reliable hierarchy v2.

This module only decodes Helper-produced facts. It deliberately does not
reconstruct candidate selection, labels, deduplication, or traversal order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
import hashlib
import hmac
import re
import secrets


RAW_SCHEMA_VERSION = "service-hierarchy-v2"
LEGACY_RAW_SCHEMA_VERSION = "service-hierarchy-v1"
CANDIDATE_SCHEMA_VERSION = "legacy-traversal-candidates.v1"
CANDIDATE_CONTRACT_VERSION = "legacy-traversal-candidate-contract.v1"
CANDIDATE_ALGORITHM_VERSION = "2.76.3"
CANDIDATE_ANALYZER_VERSION = "1.11.1"
CANDIDATE_PROFILE_ID = "oneconnect-traversal-policy"
CANDIDATE_PROFILE_VERSION = "1.0.0"
CAPTURE_ENVELOPE_SCHEMA_VERSION = "phase6d-capture-envelope-v1"
CAPTURE_CANONICALIZATION_VERSION = "capture-canonical-json-v1"
CAPTURE_ROOT_IDENTITY_VERSION = "phase6d-root-capture-id-v1"
CAPTURE_ENVELOPE_FIELDS = frozenset({
    "schema_version", "canonicalization", "request_id", "process_epoch",
    "generation", "service_instance_id", "capture_sequence", "root_ref",
    "root_digest", "candidate_digest",
})
MAX_RAW_NODES = 4096
MAX_RAW_DEPTH = 80
_ROOT_REF = re.compile(r"^windows\[(0|[1-9][0-9]*)\]\.root$")
_CAPTURE_AUTHORITY_SECRET = secrets.token_bytes(32)

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


def capture_canonical_json(value: Any) -> str:
    """Serialize the Phase6D cross-language digest domain exactly."""
    def checked_text(text: str) -> str:
        try:
            text.encode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError("CAPTURE_CANONICAL_UNPAIRED_SURROGATE") from error
        return text

    def quote(text: str) -> str:
        checked_text(text)
        out = ['"']
        for char in text:
            code = ord(char)
            if char == '"':
                out.append(r'\"')
            elif char == "\\":
                out.append(r"\\")
            elif char == "\b":
                out.append(r"\b")
            elif char == "\f":
                out.append(r"\f")
            elif char == "\n":
                out.append(r"\n")
            elif char == "\r":
                out.append(r"\r")
            elif char == "\t":
                out.append(r"\t")
            elif code < 0x20:
                out.append("\\u" + f"{code:04x}")
            elif code <= 0x7e:
                out.append(char)
            elif code <= 0xffff:
                out.append("\\u" + f"{code:04x}")
            else:
                scalar = code - 0x10000
                high = 0xd800 + (scalar >> 10)
                low = 0xdc00 + (scalar & 0x3ff)
                out.extend(("\\u" + f"{high:04x}", "\\u" + f"{low:04x}"))
        out.append('"')
        return "".join(out)

    def sort_key(key: str) -> bytes:
        checked_text(key)
        return key.encode("utf-16-be", errors="strict")

    def emit(item: Any) -> str:
        if item is None:
            return "null"
        if type(item) is bool:
            return "true" if item else "false"
        if type(item) is str:
            return quote(item)
        if type(item) is int:
            if not -(1 << 63) <= item < (1 << 63):
                raise ValueError("CAPTURE_CANONICAL_INTEGER_RANGE")
            return str(item)
        if isinstance(item, (list, tuple)):
            return "[" + ",".join(emit(child) for child in item) + "]"
        if isinstance(item, Mapping):
            if any(type(key) is not str for key in item):
                raise ValueError("CAPTURE_CANONICAL_OBJECT_KEY")
            return "{" + ",".join(quote(key) + ":" + emit(item[key]) for key in sorted(item, key=sort_key)) + "}"
        raise ValueError("CAPTURE_CANONICAL_TYPE_UNSUPPORTED")

    return emit(value)


def capture_canonical_sha256(value: Any) -> str:
    return hashlib.sha256(capture_canonical_json(value).encode("utf-8", errors="strict")).hexdigest()


def capture_root_id(envelope: Mapping[str, Any]) -> str:
    if not isinstance(envelope, Mapping):
        raise ValueError("capture envelope must be a mapping")
    identity = {
        "identity_schema": CAPTURE_ROOT_IDENTITY_VERSION,
        "schema_version": envelope.get("schema_version"),
        "canonicalization": envelope.get("canonicalization"),
        "request_id": envelope.get("request_id"),
        "process_epoch": envelope.get("process_epoch"),
        "generation": envelope.get("generation"),
        "service_instance_id": envelope.get("service_instance_id"),
        "capture_sequence": envelope.get("capture_sequence"),
        "root_ref": envelope.get("root_ref"),
        "root_digest": envelope.get("root_digest"),
    }
    if (identity["schema_version"] != CAPTURE_ENVELOPE_SCHEMA_VERSION
            or identity["canonicalization"] != CAPTURE_CANONICALIZATION_VERSION
            or not isinstance(identity["request_id"], str) or not identity["request_id"]
            or not isinstance(identity["process_epoch"], str) or not identity["process_epoch"]
            or not isinstance(identity["service_instance_id"], str) or not identity["service_instance_id"]
            or type(identity["generation"]) is not int or identity["generation"] <= 0
            or type(identity["capture_sequence"]) is not int or identity["capture_sequence"] <= 0
            or not isinstance(identity["root_ref"], str) or not _ROOT_REF.fullmatch(identity["root_ref"])
            or not isinstance(identity["root_digest"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", identity["root_digest"])):
        raise ValueError("capture envelope identity is invalid")
    return capture_canonical_sha256(identity)


class ReliableHierarchySchemaError(ValueError):
    """A fail-closed reliable hierarchy or candidate-contract error."""

    def __init__(self, reason: str, request_id: str = "") -> None:
        self.reason = reason
        self.request_id = request_id
        suffix = f" req_id={request_id}" if request_id else ""
        super().__init__(f"HIERARCHY_SCHEMA:{reason}{suffix}")


@dataclass(frozen=True)
class CaptureAuthority:
    schema_version: str
    canonicalization: str
    request_id: str
    process_epoch: str
    generation: int
    service_instance_id: str
    capture_sequence: int
    root_ref: str
    root_digest: str
    candidate_digest: str
    hierarchy_package_name: str | None
    hierarchy_window_id: int
    hierarchy_root_class_name: str | None
    hierarchy_root_source_node_id: str | None
    hierarchy_root_bounds: tuple[int, int, int, int] | None
    capture_key: str
    validation_seal: str = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "canonicalization": self.canonicalization,
            "request_id": self.request_id,
            "process_epoch": self.process_epoch,
            "generation": self.generation,
            "service_instance_id": self.service_instance_id,
            "capture_sequence": self.capture_sequence,
            "root_ref": self.root_ref,
            "root_digest": self.root_digest,
            "candidate_digest": self.candidate_digest,
            "hierarchy_package_name": self.hierarchy_package_name,
            "hierarchy_window_id": self.hierarchy_window_id,
            "hierarchy_root_class_name": self.hierarchy_root_class_name,
            "hierarchy_root_source_node_id": self.hierarchy_root_source_node_id,
            "hierarchy_root_bounds": (list(self.hierarchy_root_bounds)
                                       if self.hierarchy_root_bounds is not None else None),
            "capture_key": self.capture_key,
            "validation_seal": self.validation_seal,
        }


def capture_authority_fields(envelope: Mapping[str, Any], root: Mapping[str, Any]) -> dict[str, Any]:
    """Create host capture identity with package/window facts read from root bytes."""
    core = {key: envelope.get(key) for key in (
        "schema_version", "canonicalization", "request_id", "process_epoch",
        "generation", "service_instance_id", "capture_sequence", "root_ref",
        "root_digest", "candidate_digest",
    )}
    core["hierarchy_package_name"] = root.get("packageName")
    core["hierarchy_window_id"] = root.get("windowId")
    core["hierarchy_root_class_name"] = root.get("className")
    core["hierarchy_root_source_node_id"] = root.get("sourceNodeId")
    bounds = root.get("boundsInScreen")
    if isinstance(bounds, Mapping) and all(type(bounds.get(k)) is int for k in ("l", "t", "r", "b")):
        core["hierarchy_root_bounds"] = [bounds[k] for k in ("l", "t", "r", "b")]
    else:
        core["hierarchy_root_bounds"] = None
    return {**core, "capture_key": capture_canonical_sha256(core)}


def _capture_authority_mac(fields: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in fields.items() if key != "validation_seal"}
    body = capture_canonical_json(unsigned).encode("utf-8", errors="strict")
    return hmac.new(_CAPTURE_AUTHORITY_SECRET, body, hashlib.sha256).hexdigest()


def validate_capture_authority(value: Any) -> CaptureAuthority | None:
    """Accept only authority minted after host validation of tree, candidates, and transfer."""
    if isinstance(value, CaptureAuthority):
        fields = value.to_dict()
    elif isinstance(value, Mapping):
        fields = dict(value)
    else:
        return None
    seal = fields.get("validation_seal")
    if (not isinstance(seal, str) or not re.fullmatch(r"[0-9a-f]{64}", seal)
            or not hmac.compare_digest(seal, _capture_authority_mac(fields))):
        return None
    required = {
        "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "canonicalization": CAPTURE_CANONICALIZATION_VERSION,
    }
    if any(fields.get(key) != expected for key, expected in required.items()):
        return None
    request_id = fields.get("request_id")
    process_epoch = fields.get("process_epoch")
    generation = fields.get("generation")
    service_instance_id = fields.get("service_instance_id")
    sequence = fields.get("capture_sequence")
    root_ref = fields.get("root_ref")
    root_digest = fields.get("root_digest")
    candidate_digest = fields.get("candidate_digest")
    if not isinstance(request_id, str) or not request_id:
        return None
    if not isinstance(process_epoch, str) or not process_epoch:
        return None
    if type(generation) is not int or generation <= 0 or type(sequence) is not int or sequence <= 0:
        return None
    if not isinstance(service_instance_id, str) or not service_instance_id:
        return None
    if not isinstance(root_ref, str) or not _ROOT_REF.fullmatch(root_ref):
        return None
    if not isinstance(root_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", root_digest):
        return None
    if not isinstance(candidate_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", candidate_digest):
        return None
    # Reject unrecognized or Activity/component fields. The seal authenticates
    # a host-minted capture identity; it does not add component authority.
    allowed = {
        "schema_version", "canonicalization", "request_id", "process_epoch",
        "generation", "service_instance_id", "capture_sequence", "root_ref",
        "root_digest", "candidate_digest", "hierarchy_package_name",
        "hierarchy_window_id", "hierarchy_root_class_name", "hierarchy_root_source_node_id",
        "hierarchy_root_bounds", "capture_key", "validation_seal",
    }
    if set(fields) != allowed:
        return None
    hierarchy_package = fields.get("hierarchy_package_name")
    hierarchy_window = fields.get("hierarchy_window_id")
    hierarchy_root_class = fields.get("hierarchy_root_class_name")
    hierarchy_root_source_node_id = fields.get("hierarchy_root_source_node_id")
    if hierarchy_package is not None and (not isinstance(hierarchy_package, str) or not hierarchy_package.strip()):
        return None
    if type(hierarchy_window) is not int:
        return None
    if hierarchy_root_class is not None and not isinstance(hierarchy_root_class, str):
        return None
    if hierarchy_root_source_node_id is not None and not isinstance(hierarchy_root_source_node_id, str):
        return None
    root_bounds_value = fields.get("hierarchy_root_bounds")
    if root_bounds_value is None:
        root_bounds = None
    elif (isinstance(root_bounds_value, (list, tuple)) and len(root_bounds_value) == 4
          and all(type(value) is int and -(1 << 31) <= value < (1 << 31)
                  for value in root_bounds_value)):
        root_bounds = tuple(root_bounds_value)
    else:
        return None
    core = {k: fields[k] for k in (
        "schema_version", "canonicalization", "request_id", "process_epoch",
        "generation", "service_instance_id", "capture_sequence", "root_ref",
        "root_digest", "candidate_digest", "hierarchy_package_name", "hierarchy_window_id",
        "hierarchy_root_class_name", "hierarchy_root_source_node_id",
    )}
    core["hierarchy_root_bounds"] = list(root_bounds) if root_bounds is not None else None
    expected_key = capture_canonical_sha256(core)
    if fields.get("capture_key") != expected_key:
        return None
    immutable_core = dict(core, hierarchy_root_bounds=root_bounds)
    return CaptureAuthority(**immutable_core, capture_key=expected_key, validation_seal=seal)


def _seal_capture_authority(
    envelope: Mapping[str, Any], root: Mapping[str, Any],
    projection: Mapping[str, Any], transport_metadata: Mapping[str, Any],
) -> CaptureAuthority | None:
    """Mint authority only after independently rechecking all capture inputs."""
    request_id = envelope.get("request_id")
    root_ref = envelope.get("root_ref")
    if not isinstance(request_id, str) or not request_id or not isinstance(root_ref, str):
        return None
    try:
        root_digest = capture_canonical_sha256(root)
        candidate_input = dict(projection)
        candidate_digest = candidate_input.pop("candidate_digest", None)
        if (envelope.get("request_id") != request_id
                or envelope.get("root_digest") != root_digest
                or projection.get("source_root_digest") != root_digest
                or projection.get("rootCaptureId") != capture_root_id(envelope)
                or envelope.get("candidate_digest") != candidate_digest
                or not isinstance(candidate_digest, str)
                or capture_canonical_sha256(candidate_input) != candidate_digest
                or projection.get("traversalRootRef") != root_ref
                or type(root.get("windowId")) is not int
                or projection.get("traversalRootWindowId") != root.get("windowId")):
            return None
        _validate_transport_metadata(transport_metadata, request_id)
        header, control = transport_metadata.get("header"), transport_metadata.get("control")
        if not isinstance(header, Mapping) or not isinstance(control, Mapping):
            return None
        for record in (header, control):
            if (record.get("request_id") != request_id
                    or record.get("process_epoch") != envelope.get("process_epoch")
                    or record.get("generation") != envelope.get("generation")
                    or record.get("service_instance_id") != envelope.get("service_instance_id")
                    or record.get("capture_sequence") != envelope.get("capture_sequence")
                    or record.get("capture_envelope_schema_version") != CAPTURE_ENVELOPE_SCHEMA_VERSION
                    or record.get("capture_canonicalization_version") != CAPTURE_CANONICALIZATION_VERSION
                    or record.get("capture_root_id_version") != CAPTURE_ROOT_IDENTITY_VERSION):
                return None
        fields = capture_authority_fields(envelope, root)
        unsigned = {**fields, "validation_seal": ""}
        seal = _capture_authority_mac(unsigned)
        return validate_capture_authority({**fields, "validation_seal": seal})
    except (TypeError, ValueError, KeyError):
        return None


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
    capture_authority: CaptureAuthority | None = None
    # Exact digest-bound producer projection, separate from the raw tree.
    validated_candidate_projection: Mapping[str, Any] | None = None

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
    if ("sourceNodeId" in node and node["sourceNodeId"] is not None
            and not isinstance(node["sourceNodeId"], str)):
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
    if capabilities.get("capture_envelope_schema_version") != CAPTURE_ENVELOPE_SCHEMA_VERSION:
        _fail("CAPTURE_ENVELOPE_CAPABILITY_REQUIRED", request_id)
    capture_versions = capabilities.get("supported_capture_envelope_schema_versions")
    if not isinstance(capture_versions, list) or CAPTURE_ENVELOPE_SCHEMA_VERSION not in capture_versions:
        _fail("CAPTURE_ENVELOPE_CAPABILITY_REQUIRED", request_id)
    if capabilities.get("capture_canonicalization_version") != CAPTURE_CANONICALIZATION_VERSION:
        _fail("CAPTURE_CANONICALIZATION_REQUIRED", request_id)
    canonical_versions = capabilities.get("supported_capture_canonicalization_versions")
    if not isinstance(canonical_versions, list) or CAPTURE_CANONICALIZATION_VERSION not in canonical_versions:
        _fail("CAPTURE_CANONICALIZATION_REQUIRED", request_id)
    if capabilities.get("capture_root_id_version") != CAPTURE_ROOT_IDENTITY_VERSION:
        _fail("CAPTURE_ROOT_IDENTITY_CAPABILITY_REQUIRED", request_id)
    root_id_versions = capabilities.get("supported_capture_root_id_versions")
    if not isinstance(root_id_versions, list) or CAPTURE_ROOT_IDENTITY_VERSION not in root_id_versions:
        _fail("CAPTURE_ROOT_IDENTITY_CAPABILITY_REQUIRED", request_id)
    declared = capabilities.get("capabilities")
    required = {
        "content_provider_pfd", "service_hierarchy_v2", CANDIDATE_SCHEMA_VERSION,
        CAPTURE_ENVELOPE_SCHEMA_VERSION, CAPTURE_CANONICALIZATION_VERSION,
        CAPTURE_ROOT_IDENTITY_VERSION,
    }
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
    seen_window_ids: set[int] = set()
    for index, window in enumerate(windows):
        if not isinstance(window, Mapping) or type(window.get("id")) is not int:
            _fail("RAW_NODE_REFERENCE_INVALID", request_id)
        if window["id"] in seen_window_ids:
            _fail("DUPLICATE_WINDOW_ID", request_id)
        seen_window_ids.add(window["id"])
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

    capture_authority = None
    envelope = payload.get("captureEnvelope")
    if envelope is not None:
        if not capability_verified:
            _fail("CAPTURE_ENVELOPE_CAPABILITY_REQUIRED", request_id)
        if not isinstance(envelope, Mapping):
            _fail("CAPTURE_ENVELOPE_INVALID", request_id)
        if set(envelope) != CAPTURE_ENVELOPE_FIELDS:
            _fail("CAPTURE_AUTHORITY_INVALID", request_id)
        if envelope.get("schema_version") != CAPTURE_ENVELOPE_SCHEMA_VERSION or envelope.get("canonicalization") != CAPTURE_CANONICALIZATION_VERSION:
            _fail("CAPTURE_ENVELOPE_VERSION_MISMATCH", request_id)
        root_digest = capture_canonical_sha256(window_root)
        if envelope.get("request_id") != request_id or envelope.get("root_ref") != root_ref:
            _fail("CAPTURE_ENVELOPE_IDENTITY_MISMATCH", request_id)
        if envelope.get("root_digest") != root_digest:
            _fail("CAPTURE_ROOT_DIGEST_MISMATCH", request_id)
        if projection.get("source_root_digest") != root_digest:
            _fail("CAPTURE_ROOT_DIGEST_MISMATCH", request_id)
        try:
            expected_root_capture_id = capture_root_id(envelope)
        except (TypeError, ValueError):
            _fail("CAPTURE_ROOT_CAPTURE_ID_MISMATCH", request_id)
        if projection.get("rootCaptureId") != expected_root_capture_id:
            _fail("CAPTURE_ROOT_CAPTURE_ID_MISMATCH", request_id)
        candidate_digest_input = dict(projection)
        candidate_digest = candidate_digest_input.pop("candidate_digest", None)
        if not isinstance(candidate_digest, str) or capture_canonical_sha256(candidate_digest_input) != candidate_digest:
            _fail("CAPTURE_CANDIDATE_DIGEST_MISMATCH", request_id)
        if envelope.get("candidate_digest") != candidate_digest:
            _fail("CAPTURE_CANDIDATE_DIGEST_MISMATCH", request_id)
        if transport_metadata is not None:
            _validate_transport_metadata(transport_metadata, request_id)
            header = transport_metadata.get("header")
            control = transport_metadata.get("control")
            if not isinstance(header, Mapping) or not isinstance(control, Mapping):
                _fail("CAPTURE_TRANSFER_IDENTITY_MISSING", request_id)
            for record in (header, control):
                if (record.get("request_id") != request_id
                        or record.get("process_epoch") != envelope.get("process_epoch")
                        or record.get("generation") != envelope.get("generation")
                        or record.get("service_instance_id") != envelope.get("service_instance_id")
                        or record.get("capture_sequence") != envelope.get("capture_sequence")
                        or record.get("capture_envelope_schema_version") != CAPTURE_ENVELOPE_SCHEMA_VERSION
                        or record.get("capture_canonicalization_version") != CAPTURE_CANONICALIZATION_VERSION
                        or record.get("capture_root_id_version") != CAPTURE_ROOT_IDENTITY_VERSION):
                    _fail("CAPTURE_TRANSFER_IDENTITY_MISMATCH", request_id)
            # root_digest was recomputed from window_root above. Package/window
            # identity is now copied from those same immutable bytes, never WMS.
            capture_authority = _seal_capture_authority(
                envelope, window_root, projection, transport_metadata,
            )
            if capture_authority is None:
                _fail("CAPTURE_AUTHORITY_INVALID", request_id)
        elif capability_verified:
            _fail("CAPTURE_TRANSFER_IDENTITY_MISSING", request_id)
    elif capability_verified:
        _fail("CAPTURE_ENVELOPE_MISSING", request_id)

    if transport_metadata is not None and envelope is None:
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
        validated_candidate_projection=_freeze(projection),
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
        capture_authority=capture_authority,
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
        for key in (
            "client_nonce", "generation", "process_epoch", "service_instance_id",
            "helper_build_identity", "capture_sequence",
            "capture_envelope_schema_version", "capture_canonicalization_version",
        ):
            if records[0].get(key) != records[1].get(key):
                _fail("RAW_NODE_REFERENCE_INVALID", request_id)


def _is_deeply_frozen(value: Any) -> bool:
    if isinstance(value, MappingProxyType):
        return all(type(key) is str and _is_deeply_frozen(item) for key, item in value.items())
    if isinstance(value, tuple):
        return all(_is_deeply_frozen(item) for item in value)
    return value is None or type(value) in (str, int, bool)

def candidate_projection_matches_decoded(payload: ReliableHierarchyPayload) -> bool:
    """Check the reduced candidate view against the exact retained producer projection.

    This is a binding check only; capture authority is verified separately.
    Canonical comparison distinguishes booleans, integers, nulls, and ordering.
    """
    try:
        if (not isinstance(payload, ReliableHierarchyPayload) or payload.capability_verified is not True
                or payload.raw_completion_valid is not True):
            return False
        original = payload.validated_candidate_projection
        view = payload.traversal_candidates
        if (not isinstance(original, Mapping) or not isinstance(view, TraversalCandidateProjection)
                or view.complete is not True or not _is_deeply_frozen(original)
                or not _is_deeply_frozen(view.candidates)):
            return False
        completion = original.get("completion")
        if not isinstance(completion, Mapping):
            return False
        original_view = {
            "schema_version": original.get("schema_version"),
            "contract_version": original.get("candidate_contract_version"),
            "algorithm_version": original.get("algorithmVersion"),
            "analyzer_version": original.get("analyzerVersion"),
            "profile_id": original.get("profileId"),
            "profile_version": original.get("profileVersion"),
            "completion_status": completion.get("status"),
            "complete": completion.get("complete"),
            "candidate_count": completion.get("candidate_count"),
            "traversal_root_ref": original.get("traversalRootRef"),
            "traversal_root_window_id": original.get("traversalRootWindowId"),
            "can_scroll_down": original.get("canScrollDown"),
            "scroll_axis_contract": original.get("scrollAxisContract"),
            "candidates": original.get("candidates"),
        }
        decoded_view = {name: getattr(view, name) for name in original_view}
        return capture_canonical_json(original_view) == capture_canonical_json(decoded_view)
    except (AttributeError, TypeError, ValueError):
        return False


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
