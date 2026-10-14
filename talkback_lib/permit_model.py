"""Pure data-model for hypothetical, short-lived Phase 5D-B permits.

This namespace is deliberately disconnected from navigation and dispatch.  A
modeled permit is evidence only and cannot authorize a runtime action.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import uuid
from typing import Any

from .node_reacquire import ReacquireResult, ReacquireStatus


class PermitState(str, Enum):
    MODELED_VALID = "MODELED_VALID"
    INVALIDATED = "INVALIDATED"
    NOT_CREATED = "NOT_CREATED"


class PermitReason(str, Enum):
    MODEL_ONLY_NOT_RUNTIME_AUTHORITY = "MODEL_ONLY_NOT_RUNTIME_AUTHORITY"
    REACQUIRE_NOT_PROVEN = "REACQUIRE_NOT_PROVEN"
    MULTIPLE_OR_ZERO_MATCHES = "MULTIPLE_OR_ZERO_MATCHES"
    INSUFFICIENT_REQUIRED_FIELDS = "INSUFFICIENT_REQUIRED_FIELDS"
    ACTION_OR_CHILD_CONFLICT = "ACTION_OR_CHILD_CONFLICT"
    INVALID_SNAPSHOT_CONTEXT = "INVALID_SNAPSHOT_CONTEXT"
    INVALID_TIME_ORDER = "INVALID_TIME_ORDER"
    EXPIRED = "EXPIRED"
    SNAPSHOT_CHANGED = "SNAPSHOT_CHANGED"
    PACKAGE_CHANGED = "PACKAGE_CHANGED"
    WINDOW_CHANGED = "WINDOW_CHANGED"
    UNIQUE_REACQUIRE_LOST = "UNIQUE_REACQUIRE_LOST"
    ACTION_SET_CHANGED = "ACTION_SET_CHANGED"
    CHILD_STRUCTURE_CHANGED = "CHILD_STRUCTURE_CHANGED"
    SEMANTIC_ROLE_CHANGED = "SEMANTIC_ROLE_CHANGED"
    HARD_STOP = "HARD_STOP"
    OTHER_TARGET_OBSERVED = "OTHER_TARGET_OBSERVED"
    CANCELLED = "CANCELLED"
    TOCTOU_EXPIRED = "TOCTOU_EXPIRED"


@dataclass(frozen=True)
class PermitModelResult:
    state: PermitState
    reason_code: PermitReason
    permit: dict[str, Any] | None
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state"] = self.state.value
        result["reason_code"] = self.reason_code.value
        return result


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("timestamp must be datetime or ISO-8601 string")
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _result_fields(value: ReacquireResult | dict[str, Any]) -> tuple[str, str | None, str | None, int]:
    if isinstance(value, ReacquireResult):
        return value.status.value, value.authorized_snapshot_id, value.fresh_snapshot_id, value.candidate_count
    if isinstance(value, dict):
        status = value.get("status")
        status = status.value if isinstance(status, ReacquireStatus) else status
        return str(status), value.get("authorized_snapshot_id"), value.get("fresh_snapshot_id"), int(value.get("candidate_count", 0))
    return "INVALID", None, None, 0


def model_short_lived_permit(
    *,
    reacquire_result: ReacquireResult | dict[str, Any],
    authorized_node_identity: dict[str, Any],
    reacquired_node_identity: dict[str, Any],
    action_type: str,
    action_semantics: str,
    authorization_time: datetime | str,
    reacquire_time: datetime | str,
    permit_creation_time: datetime | str,
    ttl_seconds: float = 1.0,
    exactly_one_match: bool = False,
    no_child_action_conflict: bool = False,
    no_critical_semantic_mismatch: bool = False,
    snapshot_package_window_valid: bool = False,
    required_fields_sufficient: bool = False,
    action_set_evidence_sufficient: bool = False,
    permit_id: str | None = None,
    transaction_id: str | None = None,
) -> PermitModelResult:
    """Create only a non-enforcing permit record when all model gates pass."""
    status, auth_snapshot, fresh_snapshot, candidate_count = _result_fields(reacquire_result)
    evidence = {
        "model_only": True,
        "runtime_authority": False,
        "dispatch_performed": False,
        "reacquire_status": status,
        "candidate_count": candidate_count,
        "exactly_one_match": exactly_one_match,
        "required_fields_sufficient": required_fields_sufficient,
        "action_set_evidence_sufficient": action_set_evidence_sufficient,
    }
    if status != ReacquireStatus.PROVEN.value:
        return PermitModelResult(PermitState.NOT_CREATED, PermitReason.REACQUIRE_NOT_PROVEN, None, evidence)
    if not exactly_one_match or candidate_count != 1:
        return PermitModelResult(PermitState.NOT_CREATED, PermitReason.MULTIPLE_OR_ZERO_MATCHES, None, evidence)
    if not no_child_action_conflict or not no_critical_semantic_mismatch:
        return PermitModelResult(PermitState.NOT_CREATED, PermitReason.ACTION_OR_CHILD_CONFLICT, None, evidence)
    if not snapshot_package_window_valid or not auth_snapshot or not fresh_snapshot or auth_snapshot == fresh_snapshot:
        return PermitModelResult(PermitState.NOT_CREATED, PermitReason.INVALID_SNAPSHOT_CONTEXT, None, evidence)
    if not required_fields_sufficient or not action_set_evidence_sufficient:
        return PermitModelResult(PermitState.NOT_CREATED, PermitReason.INSUFFICIENT_REQUIRED_FIELDS, None, evidence)
    if not action_type or not action_semantics or not isinstance(authorized_node_identity, dict) or not isinstance(reacquired_node_identity, dict):
        return PermitModelResult(PermitState.NOT_CREATED, PermitReason.INSUFFICIENT_REQUIRED_FIELDS, None, evidence)
    if ttl_seconds <= 0:
        return PermitModelResult(PermitState.NOT_CREATED, PermitReason.INVALID_TIME_ORDER, None, evidence)
    try:
        authorization = _utc(authorization_time)
        reacquired = _utc(reacquire_time)
        created = _utc(permit_creation_time)
    except (TypeError, ValueError):
        return PermitModelResult(PermitState.NOT_CREATED, PermitReason.INVALID_TIME_ORDER, None, evidence)
    if not authorization <= reacquired <= created:
        return PermitModelResult(PermitState.NOT_CREATED, PermitReason.INVALID_TIME_ORDER, None, evidence)
    expires = created + timedelta(seconds=ttl_seconds)
    permit = {
        "schema_name": "talkback.phase5d_b.offline_permit_model",
        "schema_version": "1.0",
        "permit_id": permit_id or str(uuid.uuid4()),
        "transaction_id": transaction_id or str(uuid.uuid4()),
        "authorized_snapshot_id": auth_snapshot,
        "reacquired_snapshot_id": fresh_snapshot,
        "authorized_node_identity": authorized_node_identity,
        "reacquired_node_identity": reacquired_node_identity,
        "action_type": action_type,
        "action_semantics": action_semantics,
        "created_at": _iso(created),
        "expires_at": _iso(expires),
        "reacquire_result": status,
        "evidence_summary": evidence,
        "invalidation_state": PermitState.MODELED_VALID.value,
        "invalidation_reason": None,
        "time_of_check_use": {
            "authorization_time": _iso(authorization),
            "reacquire_time": _iso(reacquired),
            "permit_creation_time": _iso(created),
            "hypothetical_dispatch_time": None,
            "dispatch_is_hypothetical": True,
            "maximum_lifetime_seconds": ttl_seconds,
        },
        "runtime_authority": False,
        "dispatch_performed": False,
    }
    return PermitModelResult(PermitState.MODELED_VALID, PermitReason.MODEL_ONLY_NOT_RUNTIME_AUTHORITY, permit, evidence)


def evaluate_modeled_permit(
    permit: dict[str, Any],
    *,
    now: datetime | str,
    current_snapshot_id: str,
    package_unchanged: bool,
    window_unchanged: bool,
    uniquely_reacquired: bool,
    action_set_unchanged: bool,
    child_structure_unchanged: bool,
    semantic_role_unchanged: bool,
    hard_stop: bool = False,
    another_target_observed: bool = False,
    cancelled: bool = False,
    hypothetical_dispatch_time: datetime | str | None = None,
) -> PermitModelResult:
    """Evaluate modeled invalidation conditions without invoking a dispatcher."""
    if not isinstance(permit, dict) or permit.get("schema_name") != "talkback.phase5d_b.offline_permit_model":
        return PermitModelResult(PermitState.INVALIDATED, PermitReason.INVALID_SNAPSHOT_CONTEXT, None, {"model_only": True})
    try:
        observed_at = _utc(now)
        expires = _utc(permit["expires_at"])
    except (TypeError, ValueError, KeyError):
        return PermitModelResult(PermitState.INVALIDATED, PermitReason.INVALID_TIME_ORDER, None, {"model_only": True})

    checks = [
        (cancelled, PermitReason.CANCELLED),
        (hard_stop, PermitReason.HARD_STOP),
        (another_target_observed, PermitReason.OTHER_TARGET_OBSERVED),
        (observed_at >= expires, PermitReason.EXPIRED),
        (current_snapshot_id != permit.get("reacquired_snapshot_id"), PermitReason.SNAPSHOT_CHANGED),
        (not package_unchanged, PermitReason.PACKAGE_CHANGED),
        (not window_unchanged, PermitReason.WINDOW_CHANGED),
        (not uniquely_reacquired, PermitReason.UNIQUE_REACQUIRE_LOST),
        (not action_set_unchanged, PermitReason.ACTION_SET_CHANGED),
        (not child_structure_unchanged, PermitReason.CHILD_STRUCTURE_CHANGED),
        (not semantic_role_unchanged, PermitReason.SEMANTIC_ROLE_CHANGED),
    ]
    reason = next((reason for failed, reason in checks if failed), None)
    hypothetical_time: datetime | None = None
    if hypothetical_dispatch_time is not None:
        try:
            hypothetical_time = _utc(hypothetical_dispatch_time)
        except (TypeError, ValueError):
            reason = reason or PermitReason.INVALID_TIME_ORDER
        else:
            if hypothetical_time >= expires:
                reason = reason or PermitReason.TOCTOU_EXPIRED
    evidence = {
        "model_only": True,
        "runtime_authority": False,
        "dispatch_performed": False,
        "current_snapshot_id": current_snapshot_id,
        "permit_snapshot_id": permit.get("reacquired_snapshot_id"),
        "hypothetical_dispatch_time": _iso(hypothetical_time) if hypothetical_time else None,
        "toctou_check": "PASS" if reason is None else "INVALIDATED",
    }
    if reason is not None:
        invalidated = dict(permit)
        invalidated["invalidation_state"] = PermitState.INVALIDATED.value
        invalidated["invalidation_reason"] = reason.value
        if isinstance(invalidated.get("time_of_check_use"), dict):
            invalidated["time_of_check_use"]["hypothetical_dispatch_time"] = evidence["hypothetical_dispatch_time"]
        return PermitModelResult(PermitState.INVALIDATED, reason, invalidated, evidence)
    still_valid = dict(permit)
    still_valid["time_of_check_use"] = dict(permit.get("time_of_check_use", {}))
    still_valid["time_of_check_use"]["hypothetical_dispatch_time"] = evidence["hypothetical_dispatch_time"]
    return PermitModelResult(PermitState.MODELED_VALID, PermitReason.MODEL_ONLY_NOT_RUNTIME_AUTHORITY, still_valid, evidence)
