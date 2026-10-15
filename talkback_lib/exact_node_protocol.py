"""Phase 5D-C read-only exact-node protocol models.

This module validates and audits *resolution only*.  It deliberately has no
connection to an action dispatcher and never grants production visit credit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


PROTOCOL_VERSION = "talkback.exact-navigation.v1"
REQUEST_COMMAND = "RESOLVE_EXACT_NODE"
ACTION_TYPE = "EXACT_READ_ONLY_NAVIGATION"
ACK_SCHEMA_VERSION = "1"


class FailureCode(str, Enum):
    PROTOCOL_VERSION_UNSUPPORTED = "PROTOCOL_VERSION_UNSUPPORTED"
    REQUEST_INVALID = "REQUEST_INVALID"
    REQUEST_EXPIRED = "REQUEST_EXPIRED"
    REQUEST_REPLAYED = "REQUEST_REPLAYED"
    PERMIT_INVALID = "PERMIT_INVALID"
    PERMIT_EXPIRED = "PERMIT_EXPIRED"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"
    PACKAGE_MISMATCH = "PACKAGE_MISMATCH"
    WINDOW_MISMATCH = "WINDOW_MISMATCH"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_MULTI_MATCH = "TARGET_MULTI_MATCH"
    TARGET_IDENTITY_MISMATCH = "TARGET_IDENTITY_MISMATCH"
    TARGET_LINEAGE_MISMATCH = "TARGET_LINEAGE_MISMATCH"
    TARGET_CHILD_STRUCTURE_CHANGED = "TARGET_CHILD_STRUCTURE_CHANGED"
    ACTION_SET_CHANGED = "ACTION_SET_CHANGED"
    ACTION_NOT_AVAILABLE = "ACTION_NOT_AVAILABLE"
    SOURCE_NODE_ID_MISMATCH = "SOURCE_NODE_ID_MISMATCH"
    HELPER_REACQUIRE_FAILED = "HELPER_REACQUIRE_FAILED"
    HELPER_SERVICE_INSTANCE_MISMATCH = "HELPER_SERVICE_INSTANCE_MISMATCH"
    HARD_STOP_ACTIVE = "HARD_STOP_ACTIVE"
    ACTION_EXECUTION_DISABLED = "ACTION_EXECUTION_DISABLED"
    TRANSACTION_MISMATCH = "TRANSACTION_MISMATCH"
    METADATA_INCOMPLETE = "METADATA_INCOMPLETE"


class ProtocolValidationError(ValueError):
    def __init__(self, code: FailureCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}{':' + detail if detail else ''}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, f"duplicate_key:{key}")
        result[key] = value
    return result


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_digest(data: dict[str, Any]) -> str:
    body = {key: value for key, value in data.items() if key != "request_digest"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _nonblank(value: Any, field: str, *, max_len: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise ProtocolValidationError(FailureCode.REQUEST_INVALID, f"invalid_{field}")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _nonblank(value, field)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", text):
        raise ProtocolValidationError(FailureCode.REQUEST_INVALID, f"invalid_identifier:{field}")
    return text


def _timestamp(value: Any, field: str) -> datetime:
    raw = _nonblank(value, field, max_len=64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProtocolValidationError(FailureCode.REQUEST_INVALID, f"invalid_{field}") from error
    if parsed.tzinfo is None:
        raise ProtocolValidationError(FailureCode.REQUEST_INVALID, f"timezone_required_{field}")
    return parsed.astimezone(timezone.utc)


def _required_keys(obj: dict[str, Any], required: Iterable[str], allowed: Iterable[str], where: str) -> None:
    missing = sorted(set(required) - obj.keys())
    unknown = sorted(obj.keys() - set(allowed))
    if missing or unknown:
        raise ProtocolValidationError(
            FailureCode.REQUEST_INVALID,
            f"{where}:missing={','.join(missing)}:unknown={','.join(unknown)}",
        )


def _validate_action_list(actions: Any, field: str) -> None:
    if not isinstance(actions, list):
        raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, f"{field}_must_be_array")
    for index, action in enumerate(actions):
        if (not isinstance(action, dict) or set(action) != {"id", "name", "label"}
                or type(action.get("id")) is not int
                or (action.get("name") is not None and not isinstance(action.get("name"), str))
                or (action.get("label") is not None and not isinstance(action.get("label"), str))):
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, f"{field}_item_{index}_invalid")


_SIGNATURE_FIELDS = {"resource_id", "class_name", "package", "text", "content_description", "clickable",
                     "focusable", "enabled", "visible", "child_index", "actions"}


def _validate_signature_node(node: Any, *, nested: bool = False) -> None:
    allowed = _SIGNATURE_FIELDS | ({"children"} if nested else set())
    if not isinstance(node, dict) or set(node) != allowed:
        raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "structural_signature_shape_invalid")
    if not isinstance(node.get("class_name"), str) or not node["class_name"]:
        raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "structural_class_missing")
    if not isinstance(node.get("package"), str) or not node["package"]:
        raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "structural_package_missing")
    if type(node.get("child_index")) is not int or node["child_index"] < 0:
        raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "structural_child_index_invalid")
    for flag in ("clickable", "focusable", "enabled", "visible"):
        if type(node.get(flag)) is not bool:
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, f"structural_flag_missing:{flag}")
    _validate_action_list(node.get("actions"), "structural_actions")
    if nested:
        children = node.get("children")
        if not isinstance(children, list):
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "structural_children_missing")
        for child in children:
            _validate_signature_node(child, nested=True)


def _validate_signature_list(signatures: Any, field: str, *, allow_empty: bool, nested: bool = False) -> None:
    if not isinstance(signatures, list) or (not allow_empty and not signatures):
        raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, f"{field}_signature_array_required")
    for item in signatures:
        _validate_signature_node(item, nested=nested)


REQUEST_FIELDS = frozenset({
    "protocol_version", "command", "request_id", "transaction_id", "permit_id",
    "request_nonce", "ownership", "action_type", "expected_package", "expected_window",
    "authorized_snapshot_id", "reacquire_snapshot_id", "target_identity_schema",
    "target_identity", "target_action_set", "target_lineage_signature",
    "target_child_structure_signature", "created_at", "expires_at", "permit_created_at", "permit_expires_at", "hard_stop_active",
    "source_request_id", "helper_service_instance_id", "host_session_id", "stop_epoch",
    "request_digest", "evidence_refs",
})
REQUEST_REQUIRED_FIELDS = REQUEST_FIELDS - {"evidence_refs"}


@dataclass(frozen=True)
class ExactNodeRequest:
    data: dict[str, Any]

    @property
    def request_id(self) -> str:
        return self.data["request_id"]

    @property
    def transaction_id(self) -> str:
        return self.data["transaction_id"]

    @property
    def permit_id(self) -> str:
        return self.data["permit_id"]

    @property
    def nonce(self) -> str:
        return self.data["request_nonce"]

    @classmethod
    def parse(cls, raw: str | dict[str, Any], *, now: datetime | str | None = None) -> "ExactNodeRequest":
        if isinstance(raw, str):
            try:
                value = json.loads(raw, object_pairs_hook=_pairs_no_duplicates)
            except ProtocolValidationError:
                raise
            except (json.JSONDecodeError, TypeError) as error:
                raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "malformed_json") from error
        else:
            value = raw
        if not isinstance(value, dict):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "object_required")
        if value.get("protocol_version") != PROTOCOL_VERSION:
            raise ProtocolValidationError(FailureCode.PROTOCOL_VERSION_UNSUPPORTED)
        _required_keys(value, REQUEST_REQUIRED_FIELDS, REQUEST_FIELDS, "request")
        for field in ("request_id", "transaction_id", "permit_id", "request_nonce", "expected_package",
                      "authorized_snapshot_id", "reacquire_snapshot_id", "helper_service_instance_id",
                      "host_session_id", "stop_epoch"):
            _identifier(value[field], field)
        _identifier(value["source_request_id"], "source_request_id")
        if value["command"] != REQUEST_COMMAND:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "command_not_resolve_only")
        if value["action_type"] != ACTION_TYPE:
            raise ProtocolValidationError(FailureCode.ACTION_EXECUTION_DISABLED, "action_type_not_read_only")
        if value["hard_stop_active"] is not False:
            raise ProtocolValidationError(FailureCode.HARD_STOP_ACTIVE)
        if value["authorized_snapshot_id"] == value["reacquire_snapshot_id"]:
            raise ProtocolValidationError(FailureCode.SNAPSHOT_STALE, "same_authorized_and_reacquire_snapshot")
        if not isinstance(value["expected_window"], dict):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "expected_window_object_required")
        _required_keys(value["expected_window"], {"id", "type"}, {"id", "type", "context_epoch"}, "window")
        if value["expected_window"]["id"] is None or value["expected_window"]["type"] is None:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "window_binding_required")
        ownership = value["ownership"]
        owner_required = {"run_id", "scenario_id", "scenario_transaction_id", "step_action_id", "parent_action_id"}
        if not isinstance(ownership, dict):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "ownership_object_required")
        _required_keys(ownership, owner_required, owner_required, "ownership")
        for field in owner_required - {"parent_action_id"}:
            _identifier(ownership[field], f"ownership.{field}")
        if ownership["parent_action_id"] is not None:
            _identifier(ownership["parent_action_id"], "ownership.parent_action_id")
        target = value["target_identity"]
        target_fields = {
            "package", "window_id", "resource_id", "class_name", "text", "content_description",
            "bounds", "source_node_id", "source_node_id_provenance", "node_local_id",
            "hierarchy_path", "parent_identity", "lineage_signature", "child_structure_signature",
            "actions", "semantic_role", "snapshot_id", "field_provenance",
        }
        if not isinstance(target, dict):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "target_identity_object_required")
        _required_keys(target, target_fields, target_fields, "target_identity")
        if value["target_identity_schema"] != "talkback.exact-node-descriptor.v1":
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "target_schema_unsupported")
        _nonblank(target["package"], "target.package")
        _nonblank(target["resource_id"], "target.resource_id")
        _nonblank(target["class_name"], "target.class_name")
        _nonblank(target["node_local_id"], "target.node_local_id")
        if target["package"] != value["expected_package"]:
            raise ProtocolValidationError(FailureCode.PACKAGE_MISMATCH, "request_target_package")
        if target["window_id"] != value["expected_window"]["id"]:
            raise ProtocolValidationError(FailureCode.WINDOW_MISMATCH, "request_target_window")
        if target["snapshot_id"] != value["reacquire_snapshot_id"]:
            raise ProtocolValidationError(FailureCode.SNAPSHOT_STALE, "target_snapshot_mismatch")
        if not isinstance(target["field_provenance"], dict):
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "field_provenance_required")
        for field in ("resource_id", "class_name", "package", "actions", "bounds"):
            prov = target["field_provenance"].get(field)
            if not isinstance(prov, dict) or prov.get("status") != "PRESENT":
                raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, f"provenance_{field}")
        valid_provenance = {"PRESENT", "ABSENT_IN_SOURCE", "NOT_SUPPORTED_BY_SOURCE", "PARSE_FAILED"}
        for field in ("text", "content_description", "semantic_role", "source_node_id"):
            prov = target["field_provenance"].get(field)
            if not isinstance(prov, dict) or prov.get("status") not in valid_provenance:
                raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, f"provenance_{field}")
        if target["source_node_id_provenance"] != target["field_provenance"]["source_node_id"]["status"]:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "source_node_id_provenance_mismatch")
        if not isinstance(target["bounds"], dict) or any(type(target["bounds"].get(k)) is not int for k in ("left", "top", "right", "bottom")):
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "bounds_required")
        if not isinstance(value["target_action_set"], list) or not value["target_action_set"]:
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "action_set_required")
        _validate_action_list(value["target_action_set"], "target_action_set")
        if canonical_json(value["target_action_set"]) != canonical_json(target["actions"]):
            raise ProtocolValidationError(FailureCode.ACTION_SET_CHANGED, "request_action_set_disagrees_with_identity")
        _validate_signature_list(value["target_lineage_signature"], "lineage", allow_empty=True)
        _validate_signature_list(value["target_child_structure_signature"], "children", allow_empty=True, nested=True)
        if canonical_json(value["target_lineage_signature"]) != canonical_json(target["lineage_signature"]):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "lineage_binding_mismatch")
        if canonical_json(value["target_child_structure_signature"]) != canonical_json(target["child_structure_signature"]):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "child_structure_binding_mismatch")
        expected_parent = target["lineage_signature"][-1] if target["lineage_signature"] else None
        if canonical_json(target["parent_identity"]) != canonical_json(expected_parent):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "parent_lineage_binding_mismatch")
        path = target["hierarchy_path"]
        if (not isinstance(path, dict) or set(path) != {"window_order", "child_indices"}
                or type(path.get("window_order")) is not int or path["window_order"] < 0
                or not isinstance(path.get("child_indices"), list)
                or any(type(index) is not int or index < 0 for index in path["child_indices"])):
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "hierarchy_path_malformed")
        provenance_fields = {"package", "resource_id", "class_name", "text", "content_description", "bounds",
                             "actions", "source_node_id", "semantic_role"}
        if set(target["field_provenance"]) != provenance_fields:
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "field_provenance_fields_mismatch")
        for name, provenance in target["field_provenance"].items():
            if (not isinstance(provenance, dict) or set(provenance) != {"status", "source_field", "derivation"}
                    or provenance.get("status") not in valid_provenance
                    or (provenance.get("source_field") is not None and not isinstance(provenance.get("source_field"), str))
                    or not isinstance(provenance.get("derivation"), str)):
                raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, f"invalid_field_provenance:{name}")
        if not isinstance(value["created_at"], str) or not isinstance(value["expires_at"], str):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "timestamps_required")
        expires_at = _timestamp(value["expires_at"], "expires_at")
        if expires_at <= _timestamp(value["created_at"], "created_at"):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "non_positive_lifetime")
        if _utc(now or datetime.now(timezone.utc)) >= expires_at:
            raise ProtocolValidationError(FailureCode.REQUEST_EXPIRED)
        permit_created = _timestamp(value["permit_created_at"], "permit_created_at")
        permit_expires = _timestamp(value["permit_expires_at"], "permit_expires_at")
        current_time = _utc(now or datetime.now(timezone.utc))
        if permit_expires <= permit_created:
            raise ProtocolValidationError(FailureCode.PERMIT_INVALID, "invalid_permit_lifetime")
        if current_time >= permit_expires:
            raise ProtocolValidationError(FailureCode.PERMIT_EXPIRED)
        digest = value.get("request_digest")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "request_digest_required")
        if request_digest(value) != digest:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "request_digest_mismatch")
        return cls(value)


ACK_FIELDS = frozenset({
    "protocol_version", "request_id", "transaction_id", "permit_id", "request_nonce", "resolved",
    "candidate_count", "reacquire_verdict", "resolved_target_identity", "resolved_source_node_id",
    "resolved_source_node_id_provenance", "resolved_resource_id", "resolved_class", "resolved_bounds",
    "resolved_action_set", "resolved_lineage_summary", "resolved_child_structure_summary",
    "identity_match_summary", "perform_action_called", "perform_action_call_count",
    "perform_action_return", "failure_code", "timestamp", "authorized_snapshot_id",
    "reacquire_snapshot_id", "helper_validation_snapshot_id", "helper_service_instance_id",
    "audit_event_id", "visit_authority",
})


@dataclass(frozen=True)
class ExactNodeAck:
    data: dict[str, Any]

    @classmethod
    def parse(cls, raw: str | dict[str, Any], request: ExactNodeRequest | None = None) -> "ExactNodeAck":
        try:
            value = json.loads(raw, object_pairs_hook=_pairs_no_duplicates) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError) as error:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "malformed_ack_json") from error
        if not isinstance(value, dict):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "ack_object_required")
        _required_keys(value, ACK_FIELDS, ACK_FIELDS, "ack")
        if value["protocol_version"] != PROTOCOL_VERSION:
            raise ProtocolValidationError(FailureCode.PROTOCOL_VERSION_UNSUPPORTED)
        if (value["perform_action_called"] is not False or type(value["perform_action_call_count"]) is not int
                or value["perform_action_call_count"] != 0):
            raise ProtocolValidationError(FailureCode.ACTION_EXECUTION_DISABLED, "action_call_detected")
        if value["perform_action_return"] is not None:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "read_only_return_must_be_null")
        if value["visit_authority"] is not False:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "ack_cannot_be_visit_authority")
        if type(value["resolved"]) is not bool:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "ack_resolved_boolean_required")
        _nonblank(value["request_id"], "ack.request_id")
        _nonblank(value["transaction_id"], "ack.transaction_id")
        _nonblank(value["permit_id"], "ack.permit_id")
        _nonblank(value["request_nonce"], "ack.request_nonce")
        if type(value["candidate_count"]) is not int or value["candidate_count"] < 0:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "invalid_candidate_count")
        if value["failure_code"] is not None:
            try:
                FailureCode(value["failure_code"])
            except ValueError as error:
                raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "unknown_ack_failure_code") from error
        if not isinstance(value["timestamp"], str):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "ack_timestamp_required")
        _timestamp(value["timestamp"], "ack.timestamp")
        if request is not None:
            for field, expected in (("request_id", request.request_id), ("transaction_id", request.transaction_id),
                                    ("permit_id", request.permit_id), ("request_nonce", request.nonce)):
                if value[field] != expected:
                    raise ProtocolValidationError(FailureCode.REQUEST_INVALID, f"ack_{field}_mismatch")
        if value["resolved"] is True and (value["candidate_count"] != 1 or value["failure_code"] is not None):
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "invalid_resolved_ack")
        if value["resolved"] is True:
            identity = value["resolved_target_identity"]
            if not isinstance(identity, dict):
                raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "resolved_identity_required")
            provenance = identity.get("field_provenance")
            if not isinstance(provenance, dict):
                raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "resolved_provenance_required")
            for field in ("package", "resource_id", "class_name", "actions", "bounds"):
                item = provenance.get(field)
                if not isinstance(item, dict) or item.get("status") != "PRESENT":
                    raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, f"resolved_provenance:{field}")
            bounds = identity.get("bounds")
            if not isinstance(bounds, dict) or any(type(bounds.get(key)) is not int for key in ("left", "top", "right", "bottom")):
                raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "resolved_bounds_required")
            if identity.get("snapshot_id") != value["helper_validation_snapshot_id"]:
                raise ProtocolValidationError(FailureCode.SNAPSHOT_STALE, "resolved_descriptor_snapshot_mismatch")
            for ack_field, identity_field in (("resolved_source_node_id", "source_node_id"),
                                              ("resolved_resource_id", "resource_id"),
                                              ("resolved_class", "class_name"),
                                              ("resolved_bounds", "bounds"),
                                              ("resolved_action_set", "actions")):
                if canonical_json(value[ack_field]) != canonical_json(identity.get(identity_field)):
                    raise ProtocolValidationError(FailureCode.REQUEST_INVALID, f"{ack_field}_descriptor_mismatch")
            if value["resolved_source_node_id_provenance"] != identity.get("source_node_id_provenance"):
                raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "resolved_source_provenance_mismatch")
            if (canonical_json(identity.get("lineage_signature")) != canonical_json(value["resolved_lineage_summary"])
                    or canonical_json(identity.get("child_structure_signature")) != canonical_json(value["resolved_child_structure_summary"])):
                raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "resolved_structure_summary_mismatch")
            if request is not None:
                target = request.data["target_identity"]
                for field in ("package", "window_id", "resource_id", "class_name", "text", "content_description"):
                    if canonical_json(identity.get(field)) != canonical_json(target.get(field)):
                        raise ProtocolValidationError(FailureCode.TARGET_IDENTITY_MISMATCH, f"resolved_{field}_mismatch")
                if (target["source_node_id_provenance"] == "PRESENT"
                        and canonical_json(identity.get("source_node_id")) != canonical_json(target.get("source_node_id"))):
                    raise ProtocolValidationError(FailureCode.SOURCE_NODE_ID_MISMATCH, "resolved_source_node_id_mismatch")
                if identity.get("source_node_id_provenance") != provenance.get("source_node_id", {}).get("status"):
                    raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "resolved_source_provenance_mismatch")
                if canonical_json(identity.get("actions")) != canonical_json(request.data["target_action_set"]):
                    raise ProtocolValidationError(FailureCode.ACTION_SET_CHANGED, "resolved_descriptor_action_set_mismatch")
                if canonical_json(value["resolved_action_set"]) != canonical_json(request.data["target_action_set"]):
                    raise ProtocolValidationError(FailureCode.ACTION_SET_CHANGED, "resolved_ack_action_set_mismatch")
                if canonical_json(value["resolved_lineage_summary"]) != canonical_json(request.data["target_lineage_signature"]):
                    raise ProtocolValidationError(FailureCode.TARGET_LINEAGE_MISMATCH, "resolved_lineage_mismatch")
                if canonical_json(value["resolved_child_structure_summary"]) != canonical_json(request.data["target_child_structure_signature"]):
                    raise ProtocolValidationError(FailureCode.TARGET_CHILD_STRUCTURE_CHANGED, "resolved_child_structure_mismatch")
                if value["helper_service_instance_id"] != request.data["helper_service_instance_id"]:
                    raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "helper_service_instance_mismatch")
                if value["helper_validation_snapshot_id"] in (request.data["authorized_snapshot_id"], request.data["reacquire_snapshot_id"]):
                    raise ProtocolValidationError(FailureCode.SNAPSHOT_STALE, "helper_validation_snapshot_stale")
        if value["resolved"] is False and value["failure_code"] is None:
            raise ProtocolValidationError(FailureCode.REQUEST_INVALID, "rejected_ack_requires_failure_code")
        return cls(value)


def _utc(value: datetime | str) -> datetime:
    return value.astimezone(timezone.utc) if isinstance(value, datetime) else _timestamp(value, "now")


class OneShotRequestRegistry:
    """In-memory C1 replay/expiry model; not a durable runtime permit service."""

    def __init__(self) -> None:
        self._requests: set[str] = set()
        self._nonces: set[str] = set()
        self._permits: dict[str, str] = {}
        self._transactions: dict[str, str] = {}

    def claim(
        self,
        request: ExactNodeRequest,
        *,
        now: datetime | str,
        expected_package: str,
        expected_window: dict[str, Any],
        current_snapshot_id: str,
        hard_stop_active: bool = False,
    ) -> None:
        data = request.data
        if hard_stop_active or data["hard_stop_active"] is not False:
            raise ProtocolValidationError(FailureCode.HARD_STOP_ACTIVE)
        if _utc(now) >= _timestamp(data["expires_at"], "expires_at"):
            raise ProtocolValidationError(FailureCode.REQUEST_EXPIRED)
        if _utc(now) >= _timestamp(data["permit_expires_at"], "permit_expires_at"):
            raise ProtocolValidationError(FailureCode.PERMIT_EXPIRED)
        if expected_package != data["expected_package"]:
            raise ProtocolValidationError(FailureCode.PACKAGE_MISMATCH)
        if expected_window != data["expected_window"]:
            raise ProtocolValidationError(FailureCode.WINDOW_MISMATCH)
        if current_snapshot_id != data["reacquire_snapshot_id"] or current_snapshot_id == data["authorized_snapshot_id"]:
            raise ProtocolValidationError(FailureCode.SNAPSHOT_STALE)
        if request.request_id in self._requests or request.nonce in self._nonces or request.permit_id in self._permits:
            raise ProtocolValidationError(FailureCode.REQUEST_REPLAYED)
        prior_tx = self._transactions.get(request.transaction_id)
        if prior_tx is not None and prior_tx != request.permit_id:
            raise ProtocolValidationError(FailureCode.TRANSACTION_MISMATCH)
        self._requests.add(request.request_id)
        self._nonces.add(request.nonce)
        self._permits[request.permit_id] = request.transaction_id
        self._transactions[request.transaction_id] = request.permit_id


def _canonical_actions(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    try:
        canonical = []
        for entry in value:
            if isinstance(entry, dict) and type(entry.get("id")) is int:
                canonical.append({"id": entry["id"], "name": entry.get("name"), "label": entry.get("label")})
            else:
                return None
        return canonical_json(canonical)
    except (TypeError, ValueError):
        return None


def _protocol_node_signature(node: dict[str, Any], child_index: int, *, include_children: bool) -> dict[str, Any]:
    actions = node.get("actions")
    canonical_actions = []
    if isinstance(actions, list):
        for item in actions:
            if isinstance(item, dict):
                canonical_actions.append({"id": item.get("id"), "name": item.get("name"), "label": item.get("label")})
    signature = {
        "resource_id": _field(node, "viewIdResourceName", "resource_id"),
        "class_name": _field(node, "className", "class_name"),
        "package": _field(node, "packageName", "package", "package_name"),
        "text": node.get("text"),
        "content_description": _field(node, "contentDescription", "content_description"),
        "clickable": node.get("clickable"),
        "focusable": node.get("focusable"),
        "enabled": node.get("enabled"),
        "visible": _field(node, "visibleToUser", "visible_to_user"),
        "child_index": child_index,
        "actions": canonical_actions,
    }
    if include_children:
        children = node.get("children")
        signature["children"] = [
            _protocol_node_signature(child, index, include_children=True)
            for index, child in enumerate(children or []) if isinstance(child, dict)
        ]
    return signature


def _protocol_child_signature(node: dict[str, Any]) -> list[dict[str, Any]]:
    children = node.get("children")
    if not isinstance(children, list):
        return []
    return [_protocol_node_signature(child, index, include_children=True)
            for index, child in enumerate(children) if isinstance(child, dict)]


def _flatten_hierarchy(hierarchy: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    found: list[tuple[dict[str, Any], dict[str, Any]]] = []
    windows = hierarchy.get("windows")
    if isinstance(windows, list):
        for window_order, window in enumerate(windows):
            if not isinstance(window, dict) or not isinstance(window.get("root"), dict):
                continue
            path: list[tuple[dict[str, Any], int]] = []
            def walk(node: dict[str, Any], child_index: int, child_indices: list[int]) -> None:
                lineage = [_protocol_node_signature(parent, index, include_children=False) for parent, index in path]
                found.append((node, {"window": window, "lineage": lineage, "child_index": child_index,
                                     "child_signature": _protocol_child_signature(node),
                                     "window_order": window_order, "child_indices": list(child_indices)}))
                children = node.get("children")
                if not isinstance(children, list):
                    return
                path.append((node, child_index))
                for index, child in enumerate(children):
                    if isinstance(child, dict):
                        walk(child, index, [*child_indices, index])
                path.pop()
            walk(window["root"], 0, [])
    else:
        nodes = hierarchy.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, dict):
                    found.append((node, {"window": hierarchy.get("window", {}), "lineage": node.get("lineage_signature"),
                                         "child_index": node.get("child_index", 0),
                                         "child_signature": node.get("child_structure_signature"),
                                         "window_order": node.get("window_order", 0),
                                         "child_indices": node.get("hierarchy_path", {}).get("child_indices", [])
                                         if isinstance(node.get("hierarchy_path"), dict) else []}))
    return found


def _field(node: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in node:
            return node[name]
    return None


def build_target_descriptor(
    hierarchy: dict[str, Any],
    *,
    window_index: int,
    child_indices: list[int],
    snapshot_id: str,
) -> dict[str, Any]:
    """Create the inspectable protocol descriptor from one source hierarchy node."""
    windows = hierarchy.get("windows")
    if not isinstance(windows, list) or not 0 <= window_index < len(windows):
        raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "window_path_invalid")
    window = windows[window_index]
    if not isinstance(window, dict) or not isinstance(window.get("root"), dict):
        raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "window_root_missing")
    node = window["root"]
    ancestors: list[tuple[dict[str, Any], int]] = []
    current_sibling_index = 0
    for child_index in child_indices:
        children = node.get("children")
        if not isinstance(children, list) or type(child_index) is not int or not 0 <= child_index < len(children):
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "hierarchy_path_invalid")
        ancestors.append((node, current_sibling_index))
        node = children[child_index]
        if not isinstance(node, dict):
            raise ProtocolValidationError(FailureCode.METADATA_INCOMPLETE, "hierarchy_node_missing")
        current_sibling_index = child_index
    actions = node.get("actions")
    if not isinstance(actions, list):
        actions = None
    else:
        actions = [{"id": action.get("id"), "name": action.get("name"), "label": action.get("label")}
                   for action in actions if isinstance(action, dict)]
    provenance: dict[str, dict[str, Any]] = {}
    for name, aliases in {
        "package": ("packageName", "package"), "resource_id": ("viewIdResourceName", "resource_id"),
        "class_name": ("className", "class_name"), "text": ("text",),
        "content_description": ("contentDescription", "content_description"),
        "bounds": ("boundsInScreen", "bounds"), "actions": ("actions", "action_set"),
        "source_node_id": ("sourceNodeId", "source_node_id"), "semantic_role": ("semanticRole", "semantic_role"),
    }.items():
        source_name = next((alias for alias in aliases if alias in node), None)
        if source_name is None:
            status = "NOT_SUPPORTED_BY_SOURCE"
        elif node[source_name] is None:
            status = "ABSENT_IN_SOURCE"
        else:
            status = "PRESENT"
        provenance[name] = {"status": status, "source_field": source_name, "derivation": "source_value"}
    source_node_id = _field(node, "sourceNodeId", "source_node_id")
    source_id_status = provenance["source_node_id"]["status"]
    lineage = [_protocol_node_signature(parent, index, include_children=False) for parent, index in ancestors]
    children_signature = _protocol_child_signature(node)
    node_resource = _field(node, "viewIdResourceName", "resource_id")
    node_class = _field(node, "className", "class_name")
    return {
        "package": _field(node, "packageName", "package", "package_name"),
        "window_id": window.get("id"),
        "resource_id": node_resource,
        "class_name": node_class,
        "text": node.get("text"),
        "content_description": _field(node, "contentDescription", "content_description"),
        "bounds": _field(node, "boundsInScreen", "bounds"),
        "source_node_id": source_node_id,
        "source_node_id_provenance": source_id_status,
        "node_local_id": f"{snapshot_id}:{window_index}:{'.'.join(map(str, child_indices)) or 'root'}",
        "hierarchy_path": {"window_order": window_index, "child_indices": list(child_indices)},
        "parent_identity": lineage[-1] if lineage else None,
        "lineage_signature": lineage,
        "child_structure_signature": children_signature,
        "actions": actions,
        "semantic_role": _field(node, "semanticRole", "semantic_role"),
        "snapshot_id": snapshot_id,
        "field_provenance": provenance,
    }


def create_resolve_request(
    target_identity: dict[str, Any],
    *,
    request_id: str,
    transaction_id: str,
    permit_id: str,
    request_nonce: str,
    ownership: dict[str, Any],
    authorized_snapshot_id: str,
    helper_service_instance_id: str,
    host_session_id: str,
    source_request_id: str,
    stop_epoch: str,
    created_at: str,
    expires_at: str,
    window_type: int | str,
    hard_stop_active: bool = False,
) -> ExactNodeRequest:
    data = {
        "protocol_version": PROTOCOL_VERSION,
        "command": REQUEST_COMMAND,
        "request_id": request_id,
        "transaction_id": transaction_id,
        "permit_id": permit_id,
        "request_nonce": request_nonce,
        "ownership": dict(ownership),
        "action_type": ACTION_TYPE,
        "expected_package": target_identity["package"],
        "expected_window": {"id": target_identity["window_id"], "type": window_type},
        "authorized_snapshot_id": authorized_snapshot_id,
        "reacquire_snapshot_id": target_identity["snapshot_id"],
        "target_identity_schema": "talkback.exact-node-descriptor.v1",
        "target_identity": dict(target_identity),
        "target_action_set": target_identity["actions"],
        "target_lineage_signature": target_identity["lineage_signature"],
        "target_child_structure_signature": target_identity["child_structure_signature"],
        "created_at": created_at,
        "expires_at": expires_at,
        "permit_created_at": created_at,
        "permit_expires_at": expires_at,
        "hard_stop_active": hard_stop_active,
        "source_request_id": source_request_id,
        "helper_service_instance_id": helper_service_instance_id,
        "host_session_id": host_session_id,
        "stop_epoch": stop_epoch,
        "evidence_refs": [],
    }
    data["request_digest"] = request_digest(data)
    return ExactNodeRequest.parse(data)


def _node_raw_actions(node: dict[str, Any]) -> Any:
    return _field(node, "actions", "action_set")


def _mismatch_for_candidate(request: ExactNodeRequest, candidate: dict[str, Any], context: dict[str, Any]) -> FailureCode | None:
    target = request.data["target_identity"]
    package = _field(candidate, "packageName", "package", "package_name")
    resource = _field(candidate, "viewIdResourceName", "resource_id")
    class_name = _field(candidate, "className", "class_name")
    if package != target["package"] or resource != target["resource_id"] or class_name != target["class_name"]:
        return FailureCode.TARGET_IDENTITY_MISMATCH
    if _field(candidate, "text") != target["text"] or _field(candidate, "contentDescription", "content_description") != target["content_description"]:
        return FailureCode.TARGET_IDENTITY_MISMATCH
    source = _field(candidate, "sourceNodeId", "source_node_id")
    source_provenance = "PRESENT" if source is not None else "ABSENT_IN_SOURCE"
    expected_source = target["source_node_id"]
    expected_source_prov = target["source_node_id_provenance"]
    if expected_source_prov == "PRESENT" and (source_provenance != "PRESENT" or source != expected_source):
        return FailureCode.SOURCE_NODE_ID_MISMATCH
    lineage = context.get("lineage")
    if lineage is None:
        lineage = _field(candidate, "lineage_signature")
    if lineage is None or canonical_json(lineage) != canonical_json(request.data["target_lineage_signature"]):
        return FailureCode.TARGET_LINEAGE_MISMATCH
    children = context.get("child_signature")
    if children is None:
        children = _field(candidate, "child_structure_signature")
    if children is None:
        children = candidate.get("children")
    if children is None or canonical_json(children) != canonical_json(request.data["target_child_structure_signature"]):
        return FailureCode.TARGET_CHILD_STRUCTURE_CHANGED
    actions = _canonical_actions(_node_raw_actions(candidate))
    expected_actions = _canonical_actions(request.data["target_action_set"])
    if actions is None or expected_actions is None or actions != expected_actions:
        return FailureCode.ACTION_SET_CHANGED
    return None


def _resolved_target_descriptor(node: dict[str, Any], context: dict[str, Any], target: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    """Serialize the Helper's freshly observed descriptor, not the host request echo."""
    source_fields = {
        "package": ("packageName", "package", "package_name"),
        "resource_id": ("viewIdResourceName", "resource_id"),
        "class_name": ("className", "class_name"),
        "text": ("text",),
        "content_description": ("contentDescription", "content_description"),
        "bounds": ("boundsInScreen", "bounds"),
        "actions": ("actions", "action_set"),
        "source_node_id": ("sourceNodeId", "source_node_id"),
        "semantic_role": ("semanticRole", "semantic_role"),
    }
    current: dict[str, Any] = {
        "package": _field(node, *source_fields["package"]),
        "window_id": context.get("window", {}).get("id"),
        "resource_id": _field(node, *source_fields["resource_id"]),
        "class_name": _field(node, *source_fields["class_name"]),
        "text": _field(node, *source_fields["text"]),
        "content_description": _field(node, *source_fields["content_description"]),
        "bounds": _field(node, *source_fields["bounds"]),
        "source_node_id": _field(node, *source_fields["source_node_id"]),
        "source_node_id_provenance": "ABSENT_IN_SOURCE",
        "node_local_id": "",
        "hierarchy_path": {"window_order": context.get("window_order", 0),
                           "child_indices": list(context.get("child_indices", []))},
        "parent_identity": None,
        "lineage_signature": context.get("lineage"),
        "child_structure_signature": context.get("child_signature"),
        "actions": _node_raw_actions(node),
        "semantic_role": _field(node, *source_fields["semantic_role"]),
        "snapshot_id": snapshot_id,
        "field_provenance": {},
    }
    for name, aliases in source_fields.items():
        source_name = next((alias for alias in aliases if alias in node), None)
        value = current.get(name)
        status = "NOT_SUPPORTED_BY_SOURCE" if source_name is None else ("ABSENT_IN_SOURCE" if value is None else "PRESENT")
        current["field_provenance"][name] = {"status": status, "source_field": source_name, "derivation": "source_value"}
    current["source_node_id_provenance"] = current["field_provenance"]["source_node_id"]["status"]
    current["parent_identity"] = current["lineage_signature"][-1] if current["lineage_signature"] else None
    path = current["hierarchy_path"]
    current["node_local_id"] = f"{snapshot_id}:{path['window_order']}:{'.'.join(map(str, path['child_indices'])) or 'root'}"
    # Preserve the full inspectable schema and replace each value with Helper evidence.
    # This also makes the Helper snapshot and path explicit in the ACK audit record.
    result = dict(target)
    result.update(current)
    return result


def resolve_exact_request(request: ExactNodeRequest, hierarchy: dict[str, Any], *, hard_stop_active: bool = False) -> dict[str, Any]:
    """Resolve one full-tree target descriptor without invoking any action."""
    if hard_stop_active or request.data["hard_stop_active"] is not False:
        failure = FailureCode.HARD_STOP_ACTIVE
        base: list[tuple[dict[str, Any], dict[str, Any]]] = []
    elif hierarchy.get("success") is False:
        failure = FailureCode.HELPER_REACQUIRE_FAILED
        base = []
    elif hierarchy.get("snapshot_id") in {request.data["authorized_snapshot_id"], request.data["reacquire_snapshot_id"]}:
        failure = FailureCode.SNAPSHOT_STALE
        base = []
    elif hierarchy.get("packageName") is not None and request.data["expected_package"] != hierarchy.get("packageName"):
        failure = FailureCode.PACKAGE_MISMATCH
        base = []
    else:
        expected_window = request.data["expected_window"]
        windows = hierarchy.get("windows")
        if isinstance(windows, list) and not any(w.get("id") == expected_window["id"] and w.get("type") == expected_window["type"] for w in windows if isinstance(w, dict)):
            failure = FailureCode.WINDOW_MISMATCH
            base = []
        else:
            all_nodes = _flatten_hierarchy(hierarchy)
            target = request.data["target_identity"]
            expected_window = request.data["expected_window"]
            same_identity = [(n, c) for n, c in all_nodes
                    if _field(n, "viewIdResourceName", "resource_id") == target["resource_id"]
                    and _field(n, "className", "class_name") == target["class_name"]
                    and c.get("window", {}).get("id") == expected_window["id"]
                    and c.get("window", {}).get("type") == expected_window["type"]]
            base = [(n, c) for n, c in same_identity
                    if _field(n, "packageName", "package", "package_name") == request.data["expected_package"]]
            failure = FailureCode.PACKAGE_MISMATCH if same_identity and not base else FailureCode.TARGET_NOT_FOUND
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    rejected: list[str] = []
    if failure not in (FailureCode.HARD_STOP_ACTIVE, FailureCode.PACKAGE_MISMATCH, FailureCode.WINDOW_MISMATCH,
                       FailureCode.SNAPSHOT_STALE, FailureCode.HELPER_REACQUIRE_FAILED):
        for node, context in base:
            mismatch = _mismatch_for_candidate(request, node, context)
            if mismatch is None:
                matches.append((node, context))
            else:
                rejected.append(mismatch.value)
        if len(base) > 1:
            failure = FailureCode.TARGET_MULTI_MATCH
        elif len(matches) == 1:
            failure = None  # type: ignore[assignment]
        elif rejected:
            priority = (FailureCode.TARGET_LINEAGE_MISMATCH, FailureCode.TARGET_CHILD_STRUCTURE_CHANGED,
                        FailureCode.ACTION_SET_CHANGED, FailureCode.SOURCE_NODE_ID_MISMATCH,
                        FailureCode.TARGET_IDENTITY_MISMATCH)
            failure = next((item for item in priority if item.value in rejected), FailureCode.TARGET_IDENTITY_MISMATCH)
        elif not base:
            failure = FailureCode.TARGET_NOT_FOUND
    node = matches[0][0] if failure is None and len(matches) == 1 else None
    identity = _resolved_target_descriptor(node, matches[0][1], request.data["target_identity"], str(hierarchy.get("snapshot_id"))) if node is not None else None
    result = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request.request_id,
        "transaction_id": request.transaction_id,
        "permit_id": request.permit_id,
        "request_nonce": request.nonce,
        "resolved": node is not None,
        "candidate_count": 1 if node is not None else len(base),
        "reacquire_verdict": "RESOLVED" if node is not None else "REJECTED",
        "resolved_target_identity": identity,
        "resolved_source_node_id": _field(node, "sourceNodeId", "source_node_id") if node else None,
        "resolved_source_node_id_provenance": "PRESENT" if node and _field(node, "sourceNodeId", "source_node_id") is not None else "ABSENT_IN_SOURCE",
        "resolved_resource_id": _field(node, "viewIdResourceName", "resource_id") if node else None,
        "resolved_class": _field(node, "className", "class_name") if node else None,
        "resolved_bounds": _field(node, "boundsInScreen", "bounds") if node else None,
        "resolved_action_set": _node_raw_actions(node) if node else None,
        "resolved_lineage_summary": matches[0][1].get("lineage") if node else None,
        "resolved_child_structure_summary": matches[0][1].get("child_signature") if node else None,
        "identity_match_summary": {"matched": sorted({"package", "resource_id", "class_name", "lineage", "child_structure", "action_set"}) if node else [], "rejected_reasons": sorted(set(rejected)), "bounds_policy": "SUPPORTING_ONLY", "source_node_id_policy": "OPTIONAL_PROVENANCE_NO_GLOBAL_STABILITY"},
        "perform_action_called": False,
        "perform_action_call_count": 0,
        "perform_action_return": None,
        "failure_code": failure.value if failure else None,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "authorized_snapshot_id": request.data["authorized_snapshot_id"],
        "reacquire_snapshot_id": request.data["reacquire_snapshot_id"],
        "helper_validation_snapshot_id": hierarchy.get("snapshot_id"),
        "helper_service_instance_id": request.data["helper_service_instance_id"],
        "audit_event_id": hashlib.sha256(f"{request.request_id}:helper-resolution".encode()).hexdigest(),
        "visit_authority": False,
    }
    return result


@dataclass(frozen=True)
class AuditRecord:
    event_id: str
    event_type: str
    request_id: str
    transaction_id: str
    permit_id: str
    parent_event_id: str | None
    timestamp: str
    evidence_json: str
    visit_authority: bool = False

    @property
    def evidence(self) -> dict[str, Any]:
        return json.loads(self.evidence_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "event_type": self.event_type, "request_id": self.request_id,
            "transaction_id": self.transaction_id, "permit_id": self.permit_id,
            "parent_event_id": self.parent_event_id, "timestamp": self.timestamp,
            "evidence": self.evidence, "visit_authority": self.visit_authority,
        }


class AppendOnlyProtocolAudit:
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    @property
    def records(self) -> tuple[AuditRecord, ...]:
        return tuple(self._records)

    def append(self, *, event_type: str, request: ExactNodeRequest, parent_event_id: str | None,
               evidence: dict[str, Any]) -> AuditRecord:
        record = AuditRecord(
            event_id=hashlib.sha256(f"{request.request_id}:{len(self._records)}:{event_type}".encode()).hexdigest(),
            event_type=event_type, request_id=request.request_id, transaction_id=request.transaction_id,
            permit_id=request.permit_id, parent_event_id=parent_event_id,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            evidence_json=canonical_json(dict(evidence)), visit_authority=False,
        )
        self._records.append(record)
        return record


class HelperIdentityStatus(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HelperIdentityPrecheck:
    status: HelperIdentityStatus
    reason: str
    helper_build_id: str | None
    helper_git_commit: str | None
    policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value, "reason": self.reason,
            "helper_build_id": self.helper_build_id, "helper_git_commit": self.helper_git_commit,
            "policy": self.policy,
            "acceptance_hard_stop": self.status != HelperIdentityStatus.MATCH and self.policy == "ACCEPTANCE_HARD_STOP",
        }


def parse_helper_build_identity(ping: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if isinstance(ping, str):
        try:
            ping = json.loads(ping)
        except json.JSONDecodeError:
            return None
    if not isinstance(ping, dict):
        return None
    identity = ping.get("helper_build_identity")
    if not isinstance(identity, dict):
        return None
    return identity


def precheck_helper_build_identity(
    repo_head: str,
    ping: dict[str, Any] | str | None,
    *,
    expected_build_id: str | None = None,
    expected_input_digest: str | None = None,
    acceptance_mode: bool = True,
) -> HelperIdentityPrecheck:
    identity = parse_helper_build_identity(ping)
    policy = "ACCEPTANCE_HARD_STOP" if acceptance_mode else "DIAGNOSTIC_WARNING_ONLY"
    if identity is None:
        return HelperIdentityPrecheck(HelperIdentityStatus.UNKNOWN, "HELPER_BUILD_IDENTITY_UNAVAILABLE", None, None, policy)
    required = ("helper_protocol_version", "versionName", "versionCode", "build_id", "git_commit",
                "helper_input_digest", "source_state", "build_variant", "metadata_provenance")
    if any(identity.get(key) in (None, "", "UNKNOWN") for key in required):
        return HelperIdentityPrecheck(HelperIdentityStatus.UNKNOWN, "IDENTITY_FIELDS_INCOMPLETE", identity.get("build_id"), identity.get("git_commit"), policy)
    mismatch = None
    if identity["git_commit"].lower() != repo_head.lower():
        mismatch = "GIT_COMMIT_MISMATCH"
    elif identity["source_state"] != "CLEAN":
        mismatch = "HELPER_SOURCE_NOT_CLEAN"
    elif expected_build_id is not None and identity["build_id"] != expected_build_id:
        mismatch = "BUILD_ID_MISMATCH"
    elif expected_input_digest is not None and identity["helper_input_digest"] != expected_input_digest:
        mismatch = "HELPER_INPUT_DIGEST_MISMATCH"
    elif not re.fullmatch(r"[0-9a-f]{64}", str(identity["build_id"])):
        return HelperIdentityPrecheck(HelperIdentityStatus.UNKNOWN, "BUILD_ID_MALFORMED", identity.get("build_id"), identity.get("git_commit"), policy)
    if mismatch:
        return HelperIdentityPrecheck(HelperIdentityStatus.MISMATCH, mismatch, identity.get("build_id"), identity.get("git_commit"), policy)
    if identity.get("helper_protocol_version") != PROTOCOL_VERSION:
        return HelperIdentityPrecheck(HelperIdentityStatus.MISMATCH, "HELPER_PROTOCOL_VERSION_MISMATCH", identity.get("build_id"), identity.get("git_commit"), policy)
    if expected_build_id is None or expected_input_digest is None:
        return HelperIdentityPrecheck(HelperIdentityStatus.UNKNOWN, "TRUSTED_LOCAL_MANIFEST_REQUIRED", identity.get("build_id"), identity.get("git_commit"), policy)
    return HelperIdentityPrecheck(HelperIdentityStatus.MATCH, "IDENTITY_MATCH", identity.get("build_id"), identity.get("git_commit"), policy)


_HELPER_BUILD_INPUTS = (
    "app/src/main", "app/build.gradle.kts", "build.gradle.kts", "settings.gradle.kts",
    "gradle.properties", "gradle/wrapper/gradle-wrapper.properties", "gradle/libs.versions.toml",
    "gradlew", "gradlew.bat",
)


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def compute_repo_helper_build_identity(repo_root: str | Path, *, variant: str = "debug") -> dict[str, Any]:
    """Compute the same read-only source manifest used by the Gradle BuildConfig fields."""
    repo = Path(repo_root).resolve()
    paths: list[Path] = []
    for relative in _HELPER_BUILD_INPUTS:
        path = repo / relative
        if path.is_file():
            paths.append(path)
        elif path.is_dir():
            paths.extend(item for item in path.rglob("*") if item.is_file())
    paths = sorted(set(paths), key=lambda path: path.relative_to(repo).as_posix())
    input_lines = "\n".join(
        f"{path.relative_to(repo).as_posix()}={hashlib.sha256(path.read_bytes()).hexdigest()}" for path in paths
    )
    input_digest = hashlib.sha256(input_lines.encode("utf-8")).hexdigest()
    commit = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain", "--untracked-files=all", "--", *_HELPER_BUILD_INPUTS)
    source_state = "UNKNOWN" if commit is None or status is None else ("CLEAN" if not status else "DIRTY")
    gradle_wrapper = repo / "gradle/wrapper/gradle-wrapper.properties"
    wrapper_text = gradle_wrapper.read_text(encoding="utf-8") if gradle_wrapper.exists() else ""
    match = re.search(r"gradle-(\d+(?:\.\d+)+)-(?:bin|all)\.zip", wrapper_text)
    gradle_version = match.group(1) if match else "UNKNOWN"
    java_version = "UNKNOWN"
    try:
        java = subprocess.run(["java", "-XshowSettings:properties", "-version"], capture_output=True, text=True, check=False)
        java_version_match = re.search(r"java\.version\s*=\s*(\S+)", java.stderr + java.stdout)
        if java_version_match:
            java_version = java_version_match.group(1)
    except OSError:
        pass
    build_id = "UNKNOWN"
    if commit is not None and source_state != "UNKNOWN":
        manifest = "\n".join((
            "schema=helper-build-manifest.v1", f"git_commit={commit}", f"input_digest={input_digest}",
            f"source_state={source_state}", f"build_variant={variant}", "version_name=1.0", "version_code=1",
            f"gradle_version={gradle_version}",
        ))
        build_id = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    return {
        "build_id": build_id,
        "git_commit": commit or "UNKNOWN",
        "helper_input_digest": input_digest,
        "source_state": source_state,
        "build_variant": variant,
        "gradle_version": gradle_version,
        "java_version": java_version,
    }


def precheck_repo_helper_build_identity(
    repo_root: str | Path,
    ping: dict[str, Any] | str | None,
    *,
    variant: str = "debug",
    acceptance_mode: bool = True,
) -> HelperIdentityPrecheck:
    expected = compute_repo_helper_build_identity(repo_root, variant=variant)
    if expected["source_state"] != "CLEAN":
        return HelperIdentityPrecheck(HelperIdentityStatus.MISMATCH, "REPOSITORY_SOURCE_NOT_CLEAN", None, expected["git_commit"],
                                      "ACCEPTANCE_HARD_STOP" if acceptance_mode else "DIAGNOSTIC_WARNING_ONLY")
    return precheck_helper_build_identity(
        str(expected["git_commit"]), ping,
        expected_build_id=str(expected["build_id"]),
        expected_input_digest=str(expected["helper_input_digest"]),
        acceptance_mode=acceptance_mode,
    )
