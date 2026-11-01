"""T1/T2 request-scoped hierarchy file/PFD transport codecs and validation."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from typing import Any

from talkback_lib.exact_node_protocol import helper_compatibility_allows_execution
from talkback_lib.reliable_hierarchy_schema import (
    LEGACY_RAW_SCHEMA_VERSION,
    RAW_SCHEMA_VERSION,
    ReliableHierarchySchemaError,
    decode_reliable_hierarchy_payload,
    validate_reliable_hierarchy_payload_body,
)

CONTROL_PREFIX = "HPT1:"
CONTROL_SCHEMA = "hierarchy-transfer-control.v1"
PROTOCOL_VERSION = "hierarchy-payload.v1"
PAYLOAD_SCHEMA = RAW_SCHEMA_VERSION
LEGACY_DIAGNOSTIC_PAYLOAD_SCHEMA = LEGACY_RAW_SCHEMA_VERSION
PROVIDER_AUTHORITY = "com.iotpart.sqe.talkbackhelper.hierarchy"
DEFAULT_HIERARCHY_TRANSPORT_MODE = "RELIABLE_FILE_PFD"
MAGIC = b"TBHIER01"
TRAILER = b"TBHEND01"
MAX_CONTROL_JSON_BYTES = 8 * 1024
MAX_CONTROL_BASE64_CHARS = 12 * 1024
MAX_HEADER_BYTES = 8 * 1024
MAX_PAYLOAD_BYTES = 750_000
MAX_ARTIFACT_BYTES = 758_220
MAX_NODES = 4096
MAX_DEPTH = 80
MAX_STDERR_BYTES = 64 * 1024
MAX_CONTROL_REPLY_CHARS = 16 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID32 = re.compile(r"^[0-9a-f]{32}$")
_GIT = re.compile(r"^[0-9a-f]{40}$")


class HierarchyTransportError(RuntimeError):
    """Fail-closed reliable hierarchy transport error."""

    def __init__(self, reason: str, request_id: str = "") -> None:
        self.reason = reason
        self.request_id = request_id
        super().__init__(f"HIERARCHY_SNAPSHOT:TRANSPORT_ERROR:{reason} req_id={request_id}")


@dataclass(frozen=True)
class DecodedArtifact:
    header: dict[str, Any]
    payload_bytes: bytes
    payload: dict[str, Any]
    artifact_sha256: str


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encode_control(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="strict")
    if len(raw) > MAX_CONTROL_JSON_BYTES:
        raise HierarchyTransportError("CONTROL_TOO_LARGE", str(value.get("request_id") or ""))
    return CONTROL_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_control_reply(stdout: str, *, request_id: str = "") -> dict[str, Any]:
    if not isinstance(stdout, str) or len(stdout) > MAX_CONTROL_REPLY_CHARS:
        raise HierarchyTransportError("CONTROL_REPLY_TOO_LARGE", request_id)
    completed = [line for line in stdout.splitlines() if "Broadcast completed:" in line]
    if len(completed) != 1:
        raise HierarchyTransportError("CONTROL_COMPLETION_AMBIGUOUS", request_id)
    line = completed[0]
    result_codes = re.findall(r"\bresult=(-?\d+)\b", line)
    if len(result_codes) != 1 or result_codes[0] not in {"1", "2"}:
        raise HierarchyTransportError("CONTROL_RESULT_CODE_REJECTED", request_id)
    matches = re.findall(r'data="(HPT1:[A-Za-z0-9_-]+)"', line)
    if len(matches) != 1:
        raise HierarchyTransportError("CONTROL_RESULT_MISSING_OR_AMBIGUOUS", request_id)
    encoded = matches[0][len(CONTROL_PREFIX):]
    if len(encoded) > MAX_CONTROL_BASE64_CHARS:
        raise HierarchyTransportError("CONTROL_TOO_LARGE", request_id)
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * ((-len(encoded)) % 4))
        if len(raw) > MAX_CONTROL_JSON_BYTES:
            raise ValueError("limit")
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_reject_duplicate_json_keys)
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise HierarchyTransportError("CONTROL_INVALID", request_id) from error
    if not isinstance(value, dict) or value.get("schema") != CONTROL_SCHEMA or value.get("protocol_version") != PROTOCOL_VERSION:
        raise HierarchyTransportError("CONTROL_SCHEMA_INVALID", request_id)
    success_statuses = {"OK", "ACCEPTED", "COLLECTING", "WRITING", "READY", "ACKED", "CANCELLED"}
    expected_result = "1" if value.get("status") in success_statuses else "2"
    if result_codes[0] != expected_result:
        raise HierarchyTransportError("CONTROL_RESULT_STATUS_MISMATCH", request_id)
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def encode_artifact(header: dict[str, Any], payload_bytes: bytes) -> bytes:
    if len(payload_bytes) > MAX_PAYLOAD_BYTES:
        raise HierarchyTransportError("PAYLOAD_TOO_LARGE", str(header.get("request_id") or ""))
    header_bytes = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="strict")
    if len(header_bytes) > MAX_HEADER_BYTES:
        raise HierarchyTransportError("HEADER_TOO_LARGE", str(header.get("request_id") or ""))
    artifact = MAGIC + struct.pack(">IQ", len(header_bytes), len(payload_bytes)) + header_bytes + payload_bytes + TRAILER
    if len(artifact) > MAX_ARTIFACT_BYTES:
        raise HierarchyTransportError("ARTIFACT_TOO_LARGE", str(header.get("request_id") or ""))
    return artifact


def decode_artifact(
    artifact: bytes,
    control: dict[str, Any],
    *,
    expected_identity: dict[str, str],
    expected_request_id: str,
    expected_client_nonce: str,
    capabilities: dict[str, Any] | None = None,
    transport_metadata: dict[str, Any] | None = None,
) -> DecodedArtifact:
    request_id = expected_request_id
    if not isinstance(artifact, bytes) or not (20 + len(TRAILER) <= len(artifact) <= MAX_ARTIFACT_BYTES):
        raise HierarchyTransportError("ARTIFACT_SIZE_INVALID", request_id)
    if control.get("status") != "READY" or control.get("completed") is not True or control.get("payload_complete") is not True:
        raise HierarchyTransportError("COMPLETION_NOT_PROVEN", request_id)
    if control.get("request_id") != request_id or control.get("client_nonce") != expected_client_nonce:
        raise HierarchyTransportError("REQUEST_IDENTITY_MISMATCH", request_id)
    if control.get("payload_schema_version") != PAYLOAD_SCHEMA:
        raise HierarchyTransportError("PAYLOAD_SCHEMA_MISMATCH", request_id)
    header = _decode_envelope_header(artifact, request_id)
    artifact_digest = sha256_hex(artifact)
    if control.get("artifact_bytes") != len(artifact) or control.get("artifact_sha256") != artifact_digest:
        raise HierarchyTransportError("ARTIFACT_INTEGRITY_MISMATCH", request_id)
    header_len, payload_len = struct.unpack(">IQ", artifact[len(MAGIC):len(MAGIC) + 12])
    header_start = len(MAGIC) + 12
    payload_start = header_start + header_len
    payload_bytes = artifact[payload_start:payload_start + payload_len]
    if len(payload_bytes) != payload_len:
        raise HierarchyTransportError("TRUNCATED", request_id)
    if control.get("payload_bytes") != payload_len or header.get("payload_bytes") != payload_len:
        raise HierarchyTransportError("PAYLOAD_LENGTH_MISMATCH", request_id)
    payload_digest = sha256_hex(payload_bytes)
    if control.get("payload_sha256") != payload_digest or header.get("payload_sha256") != payload_digest:
        raise HierarchyTransportError("PAYLOAD_HASH_MISMATCH", request_id)
    _validate_identity(header, control, expected_identity, request_id, expected_client_nonce)
    payload = _parse_payload(
        payload_bytes,
        request_id,
        capabilities=capabilities,
        transport_metadata=transport_metadata or {"header": header, "control": control},
    )
    return DecodedArtifact(header, payload_bytes, payload, artifact_digest)


def _decode_envelope_header(artifact: bytes, request_id: str) -> dict[str, Any]:
    if artifact[:len(MAGIC)] != MAGIC:
        raise HierarchyTransportError("MAGIC_INVALID", request_id)
    header_len, payload_len = struct.unpack(">IQ", artifact[len(MAGIC):len(MAGIC) + 12])
    if header_len < 1 or header_len > MAX_HEADER_BYTES or payload_len > MAX_PAYLOAD_BYTES:
        raise HierarchyTransportError("LENGTH_INVALID", request_id)
    expected_size = len(MAGIC) + 12 + header_len + payload_len + len(TRAILER)
    if expected_size != len(artifact):
        raise HierarchyTransportError("LENGTH_MISMATCH", request_id)
    if artifact[-len(TRAILER):] != TRAILER:
        raise HierarchyTransportError("TRAILER_INVALID", request_id)
    raw_header = artifact[len(MAGIC) + 12:len(MAGIC) + 12 + header_len]
    try:
        header = json.loads(raw_header.decode("utf-8", errors="strict"), object_pairs_hook=_reject_duplicate_json_keys)
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise HierarchyTransportError("HEADER_INVALID", request_id) from error
    if not isinstance(header, dict) or header.get("protocol_version") != PROTOCOL_VERSION:
        raise HierarchyTransportError("HEADER_SCHEMA_INVALID", request_id)
    return header


def _validate_identity(
    header: dict[str, Any],
    control: dict[str, Any],
    expected: dict[str, str],
    request_id: str,
    client_nonce: str,
) -> None:
    names = (
        "request_id", "client_nonce", "process_epoch", "generation", "service_instance_id",
        "capture_sequence", "capture_envelope_schema_version", "capture_canonicalization_version",
    )
    for name in names:
        if header.get(name) != control.get(name):
            raise HierarchyTransportError("HEADER_CONTROL_IDENTITY_MISMATCH", request_id)
    if header.get("request_id") != request_id or header.get("client_nonce") != client_nonce:
        raise HierarchyTransportError("REQUEST_IDENTITY_MISMATCH", request_id)
    if header.get("payload_schema_version") != PAYLOAD_SCHEMA or header.get("payload_schema_version") != control.get("payload_schema_version"):
        raise HierarchyTransportError("PAYLOAD_SCHEMA_MISMATCH", request_id)
    if (header.get("capture_envelope_schema_version") != "phase6d-capture-envelope-v1"
            or control.get("capture_envelope_schema_version") != header.get("capture_envelope_schema_version")
            or header.get("capture_canonicalization_version") != "capture-canonical-json-v1"
            or control.get("capture_canonicalization_version") != header.get("capture_canonicalization_version")):
        raise HierarchyTransportError("CAPTURE_SCHEMA_MISMATCH", request_id)
    if type(header.get("capture_sequence")) is not int or header["capture_sequence"] < 1:
        raise HierarchyTransportError("CAPTURE_SEQUENCE_INVALID", request_id)
    if type(header.get("generation")) is not int or header["generation"] < 1:
        raise HierarchyTransportError("GENERATION_INVALID", request_id)
    if not isinstance(header.get("process_epoch"), str) or not header["process_epoch"]:
        raise HierarchyTransportError("PROCESS_EPOCH_MISSING", request_id)
    if not isinstance(header.get("service_instance_id"), str) or not header["service_instance_id"]:
        raise HierarchyTransportError("SERVICE_INSTANCE_MISSING", request_id)
    helper = header.get("helper_build_identity")
    control_helper = control.get("helper_build_identity")
    if not isinstance(helper, dict) or helper != control_helper:
        raise HierarchyTransportError("BUILD_IDENTITY_METADATA_MISMATCH", request_id)
    expected_source_state = expected.get("source_state")
    expected_input_digest = expected.get("input_digest")
    if (expected_source_state not in {"CLEAN", "DIRTY"}
            or not isinstance(expected_input_digest, str) or not _SHA256.fullmatch(expected_input_digest)):
        raise HierarchyTransportError("BUILD_INPUT_IDENTITY_MISMATCH", request_id)
    if helper.get("build_id") != expected["build_id"] or helper.get("git_commit") != expected["git_commit"]:
        raise HierarchyTransportError("BUILD_IDENTITY_MISMATCH", request_id)
    if (helper.get("source_state") != expected_source_state
            or helper.get("input_digest") != expected_input_digest):
        raise HierarchyTransportError("BUILD_INPUT_IDENTITY_MISMATCH", request_id)
    if helper.get("build_variant") != expected.get("build_variant", helper.get("build_variant")):
        raise HierarchyTransportError("BUILD_VARIANT_MISMATCH", request_id)
    if control.get("service_instance_id") != expected["service_instance_id"]:
        raise HierarchyTransportError("SERVICE_INSTANCE_MISMATCH", request_id)
    if not isinstance(control.get("process_epoch"), str) or not control.get("process_epoch"):
        raise HierarchyTransportError("PROCESS_EPOCH_MISSING", request_id)
    if not isinstance(header.get("created_elapsed_realtime_ns"), int) or not isinstance(
        header.get("completed_elapsed_realtime_ns"), int
    ) or header["completed_elapsed_realtime_ns"] < header["created_elapsed_realtime_ns"]:
        raise HierarchyTransportError("CAPTURE_CLOCK_INVALID", request_id)
    if control.get("completed_elapsed_realtime_ns", 0) < header["completed_elapsed_realtime_ns"]:
        raise HierarchyTransportError("CONTROL_CAPTURE_CLOCK_MISMATCH", request_id)


def _parse_payload(
    payload_bytes: bytes,
    request_id: str,
    *,
    capabilities: dict[str, Any] | None = None,
    transport_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        text = payload_bytes.decode("utf-8", errors="strict")
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys, parse_constant=_reject_json_constant)
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise HierarchyTransportError("PAYLOAD_JSON_INVALID", request_id) from error
    if not isinstance(payload, dict) or payload.get("reqId") != request_id or payload.get("success") is not True:
        raise HierarchyTransportError("PAYLOAD_IDENTITY_OR_SUCCESS_INVALID", request_id)
    try:
        if capabilities is None:
            validate_reliable_hierarchy_payload_body(payload, transport_metadata=transport_metadata)
        else:
            decode_reliable_hierarchy_payload(
                payload,
                capabilities=capabilities,
                transport_metadata=transport_metadata,
            )
    except ReliableHierarchySchemaError as error:
        raise HierarchyTransportError(error.reason, request_id) from error
    return payload


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


_PRECHECK_DIAGNOSTIC_STATUSES = frozenset({
    "EXACT_MATCH", "COMPATIBLE_SAME_HELPER_INPUT", "REBUILD_REQUIRED",
    "PROTOCOL_INCOMPATIBLE", "UNKNOWN",
})
_PRECHECK_DIAGNOSTIC_REASONS = frozenset({
    "HELPER_BUILD_IDENTITY_UNAVAILABLE", "PING_ENVELOPE_INVALID", "IDENTITY_FIELDS_INCOMPLETE",
    "IDENTITY_SCHEMA_UNSUPPORTED", "BUILD_METADATA_MALFORMED", "HELPER_PROTOCOL_VERSION_MISMATCH",
    "IDENTITY_DIGEST_OR_PROVENANCE_MALFORMED", "TRUSTED_LOCAL_MANIFEST_REQUIRED",
    "LOCAL_HELPER_MANIFEST_MALFORMED", "BUILD_METADATA_PROVENANCE_UNTRUSTED",
    "HELPER_VERSION_MISMATCH", "HELPER_BUILD_VARIANT_MISMATCH", "HELPER_SOURCE_NOT_CLEAN",
    "BUILD_ID_PROVENANCE_INCONSISTENT", "HELPER_INPUT_DIGEST_MISMATCH",
    "HELPER_CAPABILITY_EVIDENCE_UNAVAILABLE", "CAPABILITY_IDENTITY_INCONSISTENT",
    "SERVICE_INSTANCE_IDENTITY_INCONSISTENT", "TRANSPORT_PROTOCOL_INCOMPATIBLE",
    "HIERARCHY_SCHEMA_OR_CAPABILITY_INCOMPATIBLE", "LOCAL_BUILD_MANIFEST_INCONSISTENT",
    "EXACT_BUILD_PROVENANCE_MATCH", "GIT_COMMIT_DIFFERENT_BUT_HELPER_INPUT_COMPATIBLE",
    "REPOSITORY_HELPER_INPUTS_NOT_CLEAN", "CAPABILITY_QUERY_NONCE_MISMATCH", "CAPABILITY_QUERY_FAILED",
})
_PRECHECK_DIAGNOSTIC_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_PRECHECK_DIAGNOSTIC_BUILD_FIELDS = (
    "build_id", "git_commit", "input_digest", "source_state", "build_variant",
    "version_name", "version_code", "gradle_version",
)
_PRECHECK_DIAGNOSTIC_SCHEMA_FIELDS = (
    "helper_build_identity_schema", "helper_protocol", "control_schema", "transport_protocol",
    "raw_hierarchy_schema", "candidate_schema", "candidate_contract",
)
_PRECHECK_DIAGNOSTIC_PROTOCOL_FIELDS = frozenset({
    "schema_version", "helper_protocol_version", "helper_build_identity_schema", "helper_protocol",
    "control_schema", "protocol_version", "transport_protocol", "payload_schema_version",
    "raw_hierarchy_schema", "candidate_schema_version", "candidate_schema",
    "candidate_contract_version", "candidate_contract", "version_name", "version_code",
    "gradle_version", "metadata_provenance",
})


def _safe_precheck_diagnostic_value(field: str, value: Any) -> Any:
    if field in {"build_id", "input_digest"}:
        return value if isinstance(value, str) and _SHA256.fullmatch(value) else None
    if field == "git_commit":
        return value if isinstance(value, str) and _GIT.fullmatch(value) else None
    if field == "source_state":
        return value if isinstance(value, str) and value in {"CLEAN", "DIRTY", "UNKNOWN"} else None
    if field in {"version_code", "generation"}:
        return value if type(value) is int and value >= 0 else None
    if field in {"build_variant", "version_name", "gradle_version"}:
        return value if isinstance(value, str) and _PRECHECK_DIAGNOSTIC_TOKEN.fullmatch(value) else None
    if field in _PRECHECK_DIAGNOSTIC_PROTOCOL_FIELDS:
        return value if isinstance(value, str) and _PRECHECK_DIAGNOSTIC_TOKEN.fullmatch(value) else None
    return None


def _sanitize_precheck_manifest(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for field in _PRECHECK_DIAGNOSTIC_BUILD_FIELDS:
            safe = _safe_precheck_diagnostic_value(field, value.get(field))
            if safe is not None:
                result[field] = safe
    return result


def _sanitize_precheck_schemas(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for field in _PRECHECK_DIAGNOSTIC_SCHEMA_FIELDS:
            safe = _safe_precheck_diagnostic_value(field, value.get(field))
            if safe is not None:
                result[field] = safe
    return result


def _sanitize_precheck_diagnostic_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"sources": {}, "field_comparisons": {}}
    sources: dict[str, Any] = {}
    raw_sources = value.get("sources")
    for label in ("PING", "CAPABILITIES"):
        raw = raw_sources.get(label) if isinstance(raw_sources, dict) else None
        if not isinstance(raw, dict):
            continue
        source: dict[str, Any] = {"available": raw.get("available") is True}
        identity: dict[str, Any] = {}
        raw_identity = raw.get("build_identity")
        if isinstance(raw_identity, dict):
            for field in ("build_id", "git_commit", "input_digest", "source_state", "build_variant"):
                safe = _safe_precheck_diagnostic_value(field, raw_identity.get(field))
                if safe is not None:
                    identity[field] = safe
        source["build_identity"] = identity
        protocol: dict[str, Any] = {}
        raw_protocol = raw.get("schema_protocol_fields")
        if isinstance(raw_protocol, dict):
            for field in (
                "schema_version", "helper_protocol_version", "control_schema", "protocol_version",
                "payload_schema_version", "candidate_schema_version", "candidate_contract_version",
                "version_name", "version_code", "gradle_version", "metadata_provenance",
            ):
                safe = _safe_precheck_diagnostic_value(field, raw_protocol.get(field))
                if safe is not None:
                    protocol[field] = safe
        source["schema_protocol_fields"] = protocol
        if type(raw.get("service_identity_present")) is bool:
            source["service_identity_present"] = raw["service_identity_present"]
        if label == "CAPABILITIES" and type(raw.get("generation")) is int and raw["generation"] >= 0:
            source["generation"] = raw["generation"]
        sources[label] = source
    comparisons: dict[str, str] = {}
    raw_comparisons = value.get("field_comparisons")
    if isinstance(raw_comparisons, dict):
        for field in (*_PRECHECK_DIAGNOSTIC_BUILD_FIELDS[:5], "service_instance_id"):
            outcome = raw_comparisons.get(field)
            if isinstance(outcome, str) and outcome in {"MATCH", "MISMATCH", "UNAVAILABLE"}:
                comparisons[field] = outcome
    return {"sources": sources, "field_comparisons": comparisons}


def _precheck_observed_manifest(projection: dict[str, Any], source: str) -> dict[str, Any]:
    source_data = projection["sources"].get(source, {})
    identity = source_data.get("build_identity", {})
    protocol = source_data.get("schema_protocol_fields", {})
    observed: dict[str, Any] = dict(identity)
    for field in ("version_name", "version_code", "gradle_version"):
        if field in protocol:
            observed[field] = protocol[field]
    return observed


def _precheck_observed_schemas(projection: dict[str, Any]) -> dict[str, Any]:
    ping = projection["sources"].get("PING", {}).get("schema_protocol_fields", {})
    capabilities = projection["sources"].get("CAPABILITIES", {}).get("schema_protocol_fields", {})
    values = {
        "helper_build_identity_schema": ping.get("schema_version"),
        "helper_protocol": ping.get("helper_protocol_version"),
        "control_schema": capabilities.get("control_schema"),
        "transport_protocol": capabilities.get("protocol_version"),
        "raw_hierarchy_schema": capabilities.get("payload_schema_version"),
        "candidate_schema": capabilities.get("candidate_schema_version"),
        "candidate_contract": capabilities.get("candidate_contract_version"),
    }
    return _sanitize_precheck_schemas(values)


def _precheck_compare(expected: dict[str, Any], observed: dict[str, Any],
                      fields: tuple[str, ...]) -> dict[str, str]:
    comparisons: dict[str, str] = {}
    for field in fields:
        if field not in expected or field not in observed:
            comparisons[field] = "UNAVAILABLE"
        else:
            comparisons[field] = "MATCH" if expected[field] == observed[field] else "MISMATCH"
    return comparisons


def _safe_precheck_diagnostic_reason(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value in _PRECHECK_DIAGNOSTIC_REASONS:
        return value
    if value.startswith("CAPABILITY_QUERY_FAILED:"):
        return "CAPABILITY_QUERY_FAILED"
    return None


def _precheck_diagnostic_record(value: Any, *, decision: str, error_code: str | None,
                                expected: dict[str, str] | None,
                                diagnostic_context: Any) -> dict[str, Any]:
    precheck = value if isinstance(value, dict) else {}
    raw_status = precheck.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status in _PRECHECK_DIAGNOSTIC_STATUSES else "UNKNOWN"
    reason_present = "reason" in precheck and precheck.get("reason") is not None
    reason = _safe_precheck_diagnostic_reason(precheck.get("reason"))

    context = diagnostic_context if isinstance(diagnostic_context, dict) else {}
    projection = _sanitize_precheck_diagnostic_projection(context.get("source_projection"))
    expected_manifest = _sanitize_precheck_manifest(context.get("expected_local_manifest"))
    expected_fallbacks = {
        "build_id": "expected_helper_build_id",
        "git_commit": "expected_git_commit",
        "input_digest": "expected_helper_input_digest",
    }
    for field, key in expected_fallbacks.items():
        if field not in expected_manifest:
            safe = _safe_precheck_diagnostic_value(field, precheck.get(key))
            if safe is not None:
                expected_manifest[field] = safe

    observed_ping = _precheck_observed_manifest(projection, "PING")
    for field, key in (
        ("build_id", "helper_build_id"), ("git_commit", "helper_git_commit"),
        ("input_digest", "helper_input_digest"),
    ):
        if field not in observed_ping:
            safe = _safe_precheck_diagnostic_value(field, precheck.get(key))
            if safe is not None:
                observed_ping[field] = safe
    observed_capabilities = _precheck_observed_manifest(projection, "CAPABILITIES")
    expected_schemas = _sanitize_precheck_schemas(context.get("expected_schemas"))
    observed_schemas = _precheck_observed_schemas(projection)
    manifest_comparisons = {
        "PING": _precheck_compare(expected_manifest, observed_ping, _PRECHECK_DIAGNOSTIC_BUILD_FIELDS),
        "CAPABILITIES": _precheck_compare(
            expected_manifest, observed_capabilities,
            ("build_id", "git_commit", "input_digest", "source_state", "build_variant"),
        ),
    }
    schema_comparisons = _precheck_compare(
        expected_schemas, observed_schemas, _PRECHECK_DIAGNOSTIC_SCHEMA_FIELDS
    )
    accepted: dict[str, Any] = {}
    if isinstance(expected, dict):
        for field in ("build_id", "git_commit", "input_digest", "build_variant"):
            safe = _safe_precheck_diagnostic_value(field, expected.get(field))
            if safe is not None:
                accepted[field] = safe
    generic_code = (
        "BUILD_IDENTITY_COMPATIBLE" if decision == "PASS"
        else "BUILD_IDENTITY_COMPATIBILITY_REQUIRED"
        if error_code == "BUILD_IDENTITY_COMPATIBILITY_REQUIRED"
        else "BUILD_IDENTITY_PRECHECK_REJECT"
    )
    return {
        "diagnostic_schema": "phase6d-build-precheck-diagnostic-v1",
        "diagnostic_only": True,
        "decision": decision,
        "generic_code": generic_code,
        "transport_error_code": error_code,
        "precheck_status": status,
        "precheck_reason": reason,
        "precheck_reason_available": reason_present,
        "precheck_reason_redacted": reason_present and reason is None,
        "expected_identity": expected_manifest,
        "observed_identity": observed_ping,
        "accepted_identity": accepted,
        "field_comparisons": manifest_comparisons["PING"],
        "manifest_comparisons": manifest_comparisons,
        "expected_schemas": expected_schemas,
        "observed_schemas": observed_schemas,
        "schema_comparisons": schema_comparisons,
        "source_projection": projection,
        "request_identity": {"request_id_available": False, "capture_sequence_available": False},
    }


def _emit_precheck_diagnostic(sink: Any, value: Any, *, decision: str, error_code: str | None,
                              expected: dict[str, str] | None = None,
                              diagnostic_context: Any = None) -> None:
    if not callable(sink):
        return
    try:
        sink(_precheck_diagnostic_record(
            value, decision=decision, error_code=error_code, expected=expected,
            diagnostic_context=diagnostic_context,
        ))
    except Exception:
        pass


def validate_expected_build_precheck(
    value: Any,
    *,
    diagnostic_sink: Any = None,
    diagnostic_context: Any = None,
) -> dict[str, str]:
    try:
        if not isinstance(value, dict) or not helper_compatibility_allows_execution(value):
            raise HierarchyTransportError("BUILD_IDENTITY_COMPATIBILITY_REQUIRED")
        build_id = value.get("helper_build_id")
        git_commit = value.get("helper_git_commit")
        service_id = value.get("helper_service_instance_id")
        if not isinstance(build_id, str) or not re.fullmatch(r"[0-9a-f]{64}", build_id):
            raise HierarchyTransportError("BUILD_IDENTITY_PRECHECK_INVALID")
        if not isinstance(git_commit, str) or not _GIT.fullmatch(git_commit):
            raise HierarchyTransportError("BUILD_IDENTITY_PRECHECK_INVALID")
        if not isinstance(service_id, str) or not service_id:
            raise HierarchyTransportError("SERVICE_INSTANCE_PRECHECK_INVALID")
        input_digest = value.get("helper_input_digest")
        if not isinstance(input_digest, str) or not _SHA256.fullmatch(input_digest):
            raise HierarchyTransportError("BUILD_IDENTITY_PRECHECK_INVALID")
        installed_metadata = value.get("installed_metadata")
        source_state = installed_metadata.get("source_state") if isinstance(installed_metadata, dict) else None
        if source_state not in {"CLEAN", "DIRTY"}:
            raise HierarchyTransportError("BUILD_IDENTITY_PRECHECK_INVALID")
        expected = {"build_id": build_id, "git_commit": git_commit, "service_instance_id": service_id}
        expected["input_digest"] = input_digest
        expected["source_state"] = source_state
        for source_key, target_key in (("helper_input_digest", "input_digest"), ("build_variant", "build_variant")):
            extra = value.get(source_key)
            if extra is not None:
                expected[target_key] = str(extra)
    except HierarchyTransportError as error:
        _emit_precheck_diagnostic(
            diagnostic_sink, value, decision="REJECT", error_code=error.reason,
            diagnostic_context=diagnostic_context,
        )
        raise
    _emit_precheck_diagnostic(
        diagnostic_sink, value, decision="PASS", error_code=None, expected=expected,
        diagnostic_context=diagnostic_context,
    )
    return expected

def validate_control_identity(value: dict[str, Any], expected: dict[str, str], *, request_id: str = "") -> None:
    if value.get("status") not in {"OK", "ACCEPTED", "COLLECTING", "WRITING", "READY", "ACKED", "CANCELLED"}:
        raise HierarchyTransportError(str(value.get("error_code") or "CONTROL_REJECTED"), request_id)
    helper = value.get("helper_build_identity")
    if not isinstance(helper, dict):
        raise HierarchyTransportError("BUILD_IDENTITY_MISSING", request_id)
    expected_source_state = expected.get("source_state")
    expected_input_digest = expected.get("input_digest")
    if (expected_source_state not in {"CLEAN", "DIRTY"}
            or not isinstance(expected_input_digest, str) or not _SHA256.fullmatch(expected_input_digest)):
        raise HierarchyTransportError("BUILD_INPUT_IDENTITY_MISMATCH", request_id)
    if helper.get("build_id") != expected["build_id"] or helper.get("git_commit") != expected["git_commit"]:
        raise HierarchyTransportError("BUILD_IDENTITY_MISMATCH", request_id)
    if (helper.get("source_state") != expected_source_state
            or helper.get("input_digest") != expected_input_digest
            or helper.get("build_variant") != expected.get("build_variant", helper.get("build_variant"))):
        raise HierarchyTransportError("BUILD_INPUT_IDENTITY_MISMATCH", request_id)
    if value.get("service_instance_id") != expected["service_instance_id"]:
        raise HierarchyTransportError("SERVICE_INSTANCE_MISMATCH", request_id)
    if value.get("payload_schema_version") not in (None, PAYLOAD_SCHEMA):
        raise HierarchyTransportError("PAYLOAD_SCHEMA_MISMATCH", request_id)


def validate_prestart_capability_generation(value: dict[str, Any], *, request_id: str = "") -> int:
    """Accept only an explicit nonnegative integer on prestart CAPABILITIES."""
    generation = value.get("generation")
    if type(generation) is not int or generation < 0:
        raise HierarchyTransportError("CAPABILITY_GENERATION_INVALID", request_id)
    return generation


def validate_request_generation(value: dict[str, Any], *, request_id: str = "") -> int:
    """Require a positive generation on request-scoped control responses.

    Prestart CAPABILITIES has a separate empty-counter baseline of zero; this
    validator is for ACCEPTED/STATUS/READY/ACK request records only.
    """
    generation = value.get("generation")
    if type(generation) is not int or generation < 1:
        raise HierarchyTransportError("GENERATION_INVALID", request_id)
    return generation


def validate_control_response(
    value: dict[str, Any],
    *,
    expected_statuses: set[str],
    expected_nonce: str,
    expected_request_id: str | None = None,
) -> None:
    if value.get("query_nonce") != expected_nonce:
        raise HierarchyTransportError("CONTROL_NONCE_MISMATCH", expected_request_id or "")
    if expected_request_id is not None and value.get("request_id") != expected_request_id:
        raise HierarchyTransportError("CONTROL_REQUEST_ID_MISMATCH", expected_request_id)
    if value.get("status") not in expected_statuses:
        raise HierarchyTransportError(str(value.get("error_code") or "CONTROL_STATUS_INVALID"), expected_request_id or "")
