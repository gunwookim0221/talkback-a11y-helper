"""T1/T2 request-scoped hierarchy file/PFD transport codecs and validation."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from typing import Any

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
    names = ("request_id", "client_nonce", "process_epoch", "generation", "service_instance_id")
    for name in names:
        if header.get(name) != control.get(name):
            raise HierarchyTransportError("HEADER_CONTROL_IDENTITY_MISMATCH", request_id)
    if header.get("request_id") != request_id or header.get("client_nonce") != client_nonce:
        raise HierarchyTransportError("REQUEST_IDENTITY_MISMATCH", request_id)
    if header.get("payload_schema_version") != PAYLOAD_SCHEMA or header.get("payload_schema_version") != control.get("payload_schema_version"):
        raise HierarchyTransportError("PAYLOAD_SCHEMA_MISMATCH", request_id)
    if not isinstance(header.get("generation"), int) or header["generation"] < 1:
        raise HierarchyTransportError("GENERATION_INVALID", request_id)
    if not isinstance(header.get("process_epoch"), str) or not header["process_epoch"]:
        raise HierarchyTransportError("PROCESS_EPOCH_MISSING", request_id)
    if not isinstance(header.get("service_instance_id"), str) or not header["service_instance_id"]:
        raise HierarchyTransportError("SERVICE_INSTANCE_MISSING", request_id)
    helper = header.get("helper_build_identity")
    control_helper = control.get("helper_build_identity")
    if not isinstance(helper, dict) or helper != control_helper:
        raise HierarchyTransportError("BUILD_IDENTITY_METADATA_MISMATCH", request_id)
    if helper.get("build_id") != expected["build_id"] or helper.get("git_commit") != expected["git_commit"]:
        raise HierarchyTransportError("BUILD_IDENTITY_MISMATCH", request_id)
    if helper.get("source_state") != "CLEAN" or helper.get("input_digest") != expected.get("input_digest", helper.get("input_digest")):
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


def validate_expected_build_precheck(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or value.get("status") != "MATCH":
        raise HierarchyTransportError("BUILD_IDENTITY_MATCH_REQUIRED")
    build_id = value.get("helper_build_id")
    git_commit = value.get("helper_git_commit")
    service_id = value.get("helper_service_instance_id")
    if not isinstance(build_id, str) or not re.fullmatch(r"[0-9a-f]{64}", build_id):
        raise HierarchyTransportError("BUILD_IDENTITY_PRECHECK_INVALID")
    if not isinstance(git_commit, str) or not _GIT.fullmatch(git_commit):
        raise HierarchyTransportError("BUILD_IDENTITY_PRECHECK_INVALID")
    if not isinstance(service_id, str) or not service_id:
        raise HierarchyTransportError("SERVICE_INSTANCE_PRECHECK_INVALID")
    expected = {"build_id": build_id, "git_commit": git_commit, "service_instance_id": service_id}
    for source_key, target_key in (("helper_input_digest", "input_digest"), ("build_variant", "build_variant")):
        extra = value.get(source_key)
        if extra is not None:
            expected[target_key] = str(extra)
    return expected


def validate_control_identity(value: dict[str, Any], expected: dict[str, str], *, request_id: str = "") -> None:
    if value.get("status") not in {"OK", "ACCEPTED", "COLLECTING", "WRITING", "READY", "ACKED", "CANCELLED"}:
        raise HierarchyTransportError(str(value.get("error_code") or "CONTROL_REJECTED"), request_id)
    helper = value.get("helper_build_identity")
    if not isinstance(helper, dict):
        raise HierarchyTransportError("BUILD_IDENTITY_MISSING", request_id)
    if helper.get("build_id") != expected["build_id"] or helper.get("git_commit") != expected["git_commit"]:
        raise HierarchyTransportError("BUILD_IDENTITY_MISMATCH", request_id)
    if helper.get("source_state") != "CLEAN" or (
        "input_digest" in expected and helper.get("input_digest") != expected["input_digest"]
    ) or ("build_variant" in expected and helper.get("build_variant") != expected["build_variant"]):
        raise HierarchyTransportError("BUILD_INPUT_IDENTITY_MISMATCH", request_id)
    if value.get("service_instance_id") != expected["service_instance_id"]:
        raise HierarchyTransportError("SERVICE_INSTANCE_MISMATCH", request_id)
    if value.get("payload_schema_version") not in (None, PAYLOAD_SCHEMA):
        raise HierarchyTransportError("PAYLOAD_SCHEMA_MISMATCH", request_id)


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
