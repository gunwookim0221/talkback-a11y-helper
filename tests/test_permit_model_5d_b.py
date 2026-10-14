from __future__ import annotations

from datetime import datetime, timezone

from talkback_lib.node_reacquire import ReacquireStatus
from talkback_lib.permit_model import (
    PermitReason,
    PermitState,
    evaluate_modeled_permit,
    model_short_lived_permit,
)


T0 = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)


def _permit(**overrides):
    values = {
        "reacquire_result": {
            "status": ReacquireStatus.PROVEN.value,
            "authorized_snapshot_id": "snapshot-a",
            "fresh_snapshot_id": "snapshot-b",
            "candidate_count": 1,
        },
        "authorized_node_identity": {"resource_id": "app:id/button", "class_name": "Button"},
        "reacquired_node_identity": {"resource_id": "app:id/button", "class_name": "Button"},
        "action_type": "ACTION_CLICK",
        "action_semantics": "open_details",
        "authorization_time": T0,
        "reacquire_time": T0,
        "permit_creation_time": T0,
        "ttl_seconds": 2.0,
        "exactly_one_match": True,
        "no_child_action_conflict": True,
        "no_critical_semantic_mismatch": True,
        "snapshot_package_window_valid": True,
        "required_fields_sufficient": True,
        "action_set_evidence_sufficient": True,
        "permit_id": "permit-test",
        "transaction_id": "txn-test",
    }
    values.update(overrides)
    return model_short_lived_permit(**values)


def test_permit_is_only_a_non_runtime_data_record_and_has_required_schema():
    result = _permit()
    assert result.state == PermitState.MODELED_VALID
    record = result.permit
    assert record["permit_id"] == "permit-test"
    assert record["transaction_id"] == "txn-test"
    assert record["authorized_snapshot_id"] == "snapshot-a"
    assert record["reacquired_snapshot_id"] == "snapshot-b"
    assert record["action_type"] == "ACTION_CLICK"
    assert record["action_semantics"] == "open_details"
    assert record["reacquire_result"] == "PROVEN"
    assert record["invalidation_state"] == "MODELED_VALID"
    assert record["runtime_authority"] is False
    assert record["dispatch_performed"] is False
    assert result.reason_code == PermitReason.MODEL_ONLY_NOT_RUNTIME_AUTHORITY


def test_ambiguous_rejected_or_insufficient_reacquire_never_creates_permit():
    ambiguous = _permit(reacquire_result={"status": "AMBIGUOUS", "candidate_count": 2})
    assert ambiguous.state == PermitState.NOT_CREATED
    assert ambiguous.reason_code == PermitReason.REACQUIRE_NOT_PROVEN

    multiple = _permit(reacquire_result={"status": "PROVEN", "authorized_snapshot_id": "a", "fresh_snapshot_id": "b", "candidate_count": 2})
    assert multiple.reason_code == PermitReason.MULTIPLE_OR_ZERO_MATCHES

    insufficient = _permit(action_set_evidence_sufficient=False)
    assert insufficient.reason_code == PermitReason.INSUFFICIENT_REQUIRED_FIELDS


def test_conflicts_hard_stop_and_invalid_context_never_create_permit():
    conflict = _permit(no_child_action_conflict=False)
    assert conflict.reason_code == PermitReason.ACTION_OR_CHILD_CONFLICT
    invalid_context = _permit(snapshot_package_window_valid=False)
    assert invalid_context.reason_code == PermitReason.INVALID_SNAPSHOT_CONTEXT
    hard_stop_is_not_a_creation_input_and_runtime_authority_stays_false()


def hard_stop_is_not_a_creation_input_and_runtime_authority_stays_false():
    created = _permit()
    evaluated = evaluate_modeled_permit(
        created.permit,
        now=T0,
        current_snapshot_id="snapshot-b",
        package_unchanged=True,
        window_unchanged=True,
        uniquely_reacquired=True,
        action_set_unchanged=True,
        child_structure_unchanged=True,
        semantic_role_unchanged=True,
        hard_stop=True,
    )
    assert evaluated.state == PermitState.INVALIDATED
    assert evaluated.reason_code == PermitReason.HARD_STOP
    assert evaluated.permit["runtime_authority"] is False


def test_expiry_intervening_snapshot_package_window_and_uniqueness_invalidate():
    permit = _permit().permit
    common = {
        "now": T0,
        "current_snapshot_id": "snapshot-b",
        "package_unchanged": True,
        "window_unchanged": True,
        "uniquely_reacquired": True,
        "action_set_unchanged": True,
        "child_structure_unchanged": True,
        "semantic_role_unchanged": True,
    }
    assert evaluate_modeled_permit(permit, **{**common, "now": T0.replace(second=2)}).reason_code == PermitReason.EXPIRED
    assert evaluate_modeled_permit(permit, **{**common, "current_snapshot_id": "snapshot-c"}).reason_code == PermitReason.SNAPSHOT_CHANGED
    assert evaluate_modeled_permit(permit, **{**common, "package_unchanged": False}).reason_code == PermitReason.PACKAGE_CHANGED
    assert evaluate_modeled_permit(permit, **{**common, "window_unchanged": False}).reason_code == PermitReason.WINDOW_CHANGED
    assert evaluate_modeled_permit(permit, **{**common, "uniquely_reacquired": False}).reason_code == PermitReason.UNIQUE_REACQUIRE_LOST


def test_action_child_role_other_target_and_cancel_invalidate():
    permit = _permit().permit
    common = {
        "now": T0,
        "current_snapshot_id": "snapshot-b",
        "package_unchanged": True,
        "window_unchanged": True,
        "uniquely_reacquired": True,
        "action_set_unchanged": True,
        "child_structure_unchanged": True,
        "semantic_role_unchanged": True,
    }
    assert evaluate_modeled_permit(permit, **{**common, "action_set_unchanged": False}).reason_code == PermitReason.ACTION_SET_CHANGED
    assert evaluate_modeled_permit(permit, **{**common, "child_structure_unchanged": False}).reason_code == PermitReason.CHILD_STRUCTURE_CHANGED
    assert evaluate_modeled_permit(permit, **{**common, "semantic_role_unchanged": False}).reason_code == PermitReason.SEMANTIC_ROLE_CHANGED
    assert evaluate_modeled_permit(permit, **{**common, "another_target_observed": True}).reason_code == PermitReason.OTHER_TARGET_OBSERVED
    assert evaluate_modeled_permit(permit, **{**common, "cancelled": True}).reason_code == PermitReason.CANCELLED


def test_toctou_expiry_and_valid_hypothetical_dispatch_are_recorded_not_executed():
    permit = _permit().permit
    common = {
        "now": T0,
        "current_snapshot_id": "snapshot-b",
        "package_unchanged": True,
        "window_unchanged": True,
        "uniquely_reacquired": True,
        "action_set_unchanged": True,
        "child_structure_unchanged": True,
        "semantic_role_unchanged": True,
    }
    valid = evaluate_modeled_permit(permit, **common, hypothetical_dispatch_time=T0.replace(microsecond=500000))
    assert valid.state == PermitState.MODELED_VALID
    assert valid.permit["time_of_check_use"]["hypothetical_dispatch_time"].endswith("Z")
    assert valid.permit["dispatch_performed"] is False

    expired = evaluate_modeled_permit(permit, **common, hypothetical_dispatch_time=T0.replace(second=2))
    assert expired.state == PermitState.INVALIDATED
    assert expired.reason_code == PermitReason.TOCTOU_EXPIRED


def test_creation_rejects_nonmonotonic_times_and_naive_datetimes():
    assert _permit(reacquire_time=T0.replace(second=1), permit_creation_time=T0).reason_code == PermitReason.INVALID_TIME_ORDER
    assert _permit(authorization_time=datetime(2026, 10, 15)).reason_code == PermitReason.INVALID_TIME_ORDER
