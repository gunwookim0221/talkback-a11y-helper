from types import SimpleNamespace

import pytest

from talkback_lib.exploration_evidence_clock import EvidenceClock
from talkback_lib.native_dispatch_evidence import (
    DISPATCHED,
    NOT_DISPATCHED,
    UNKNOWN,
    NativeDispatchCheckpoint,
    NativeDispatchEvidence,
    NativeDispatchReceiptStore,
)
from tb_runner.phase4b_authority import ExecutionBudget
from tb_runner.phase4b_execution import (
    _phase4_native_dispatch_evidence,
    _target_dispatch_checkpoint,
)


def _client(store=None, clock=None):
    store = store or NativeDispatchReceiptStore()
    return SimpleNamespace(
        _evidence_active_request_id="prior-request",
        _adb_device=SimpleNamespace(
            native_dispatch_receipts=store,
            shadow_evidence_clock=clock,
        ),
    )


def _record(store, operation_id, request_id="request-current"):
    args = ["shell", "am", "broadcast", "-a",
            "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT",
            "--es", "reqId", request_id]
    store.observe(args, operation_id=operation_id)


@pytest.mark.parametrize("clock", [None, EvidenceClock()])
def test_generic_phase4_uses_typed_receipt_with_graph_off_or_shadow(clock):
    client = _client(clock=clock)
    before = _target_dispatch_checkpoint(client)
    operation_id = before["operation_id"]
    client._evidence_active_request_id = "request-current"
    _record(client._adb_device.native_dispatch_receipts, operation_id)

    evidence = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "SUCCESS", "reqId": "request-current"})

    assert evidence["dispatch_status"] == DISPATCHED
    assert evidence["dispatch_occurred"] is True
    assert evidence["operation_id"] == operation_id
    assert evidence["current_request_id"] == "request-current"
    assert evidence["native_receipt_present"] is True


def test_precheck_rejection_is_not_dispatched_even_without_a_checkpoint():
    client = _client(store=None)
    before = _target_dispatch_checkpoint(client)
    before["native_dispatch_checkpoint"] = None
    evidence = _phase4_native_dispatch_evidence(
        client, before=before,
        result={"status": "PREFLIGHT_BLOCKED", "reason": "phase5b_focus_dispatch_preflight_denied"})
    assert evidence["dispatch_status"] == NOT_DISPATCHED
    assert evidence["dispatch_occurred"] is False


def test_phase5_native_command_guard_rejection_is_not_dispatched():
    client = _client()
    before = _target_dispatch_checkpoint(client)
    evidence = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "ERROR", "reason": "SafetyBlocked"})
    assert evidence["dispatch_status"] == NOT_DISPATCHED
    assert evidence["dispatch_occurred"] is False


def test_precheck_conflicting_with_current_receipt_fails_closed_not_dispatched():
    client = _client()
    before = _target_dispatch_checkpoint(client)
    client._evidence_active_request_id = "request-current"
    _record(client._adb_device.native_dispatch_receipts, before["operation_id"])
    evidence = _phase4_native_dispatch_evidence(
        client, before=before,
        result={"status": "PREFLIGHT_BLOCKED", "reqId": "request-current"})
    assert evidence["dispatch_status"] == UNKNOWN
    assert evidence["evidence_reason"] == "PRECHECK_CONFLICTING_CURRENT_RECEIPT"


def test_missing_checkpoint_and_watermark_remain_unknown_without_false_boolean():
    client = _client()
    before = _target_dispatch_checkpoint(client)
    before["native_dispatch_checkpoint"] = None
    missing_checkpoint = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "ERROR"})
    assert missing_checkpoint["dispatch_status"] == UNKNOWN
    assert missing_checkpoint["dispatch_occurred"] is None

    class BrokenStore(NativeDispatchReceiptStore):
        def receipt_watermark(self):
            raise RuntimeError("watermark unavailable")

    broken_client = _client(store=BrokenStore())
    broken_before = _target_dispatch_checkpoint(broken_client)
    broken_client._evidence_active_request_id = "request-current"
    missing_watermark = _phase4_native_dispatch_evidence(
        broken_client, before=broken_before,
        result={"status": "ERROR", "reqId": "request-current"})
    assert missing_watermark["dispatch_status"] == UNKNOWN
    assert missing_watermark["dispatch_occurred"] is None


def test_store_generation_mismatch_is_unknown():
    client = _client()
    before = _target_dispatch_checkpoint(client)
    client._adb_device.native_dispatch_receipts = NativeDispatchReceiptStore()
    client._evidence_active_request_id = "request-current"
    evidence = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "SUCCESS", "reqId": "request-current"})
    assert evidence["dispatch_status"] == UNKNOWN


@pytest.mark.parametrize("receipt_request", ["request-old", "request-foreign"])
def test_stale_or_unrelated_request_receipt_cannot_prove_current_dispatch(receipt_request):
    client = _client()
    before = _target_dispatch_checkpoint(client)
    client._evidence_active_request_id = "request-current"
    _record(client._adb_device.native_dispatch_receipts,
            before["operation_id"], request_id=receipt_request)
    evidence = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "ERROR", "reqId": "request-current"})
    assert evidence["dispatch_status"] == UNKNOWN
    assert evidence["dispatch_occurred"] is None


def test_receipt_without_a_current_request_identity_cannot_prove_dispatch():
    client = _client()
    before = _target_dispatch_checkpoint(client)
    _record(client._adb_device.native_dispatch_receipts, before["operation_id"])
    evidence = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "ERROR"})
    assert evidence["dispatch_status"] == UNKNOWN
    assert evidence["dispatch_occurred"] is None


def test_pre_checkpoint_receipt_is_stale_even_when_request_and_operation_match():
    store = NativeDispatchReceiptStore()
    operation_id = "same-operation"
    _record(store, operation_id)
    checkpoint = NativeDispatchCheckpoint(
        operation_id=operation_id, store_generation=store.generation_id,
        receipt_watermark_before=store.receipt_watermark(), checkpoint_status="VALID")
    client = _client(store)
    client._evidence_active_request_id = "request-current"
    before = {"native_receipt_store": store, "native_dispatch_checkpoint": checkpoint,
              "active_request_id": "prior-request"}
    evidence = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "ERROR", "reqId": "request-current"})
    assert evidence["dispatch_status"] == UNKNOWN


def test_monotonic_receipt_sequence_proves_dispatch_after_full_buffer_rollover():
    store = NativeDispatchReceiptStore()
    for index in range(2048):
        _record(store, f"old-operation-{index}", request_id=f"old-request-{index}")
    client = _client(store)
    before = _target_dispatch_checkpoint(client)
    client._evidence_active_request_id = "request-current"
    _record(store, before["operation_id"])
    evidence = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "SUCCESS", "reqId": "request-current"})
    assert len(store.receipts) == 2048
    assert evidence["receipt_seq"] == 2049
    assert evidence["dispatch_status"] == DISPATCHED


def test_post_native_error_with_current_receipt_is_dispatched():
    client = _client()
    before = _target_dispatch_checkpoint(client)
    client._evidence_active_request_id = "request-current"
    _record(client._adb_device.native_dispatch_receipts, before["operation_id"])
    evidence = _phase4_native_dispatch_evidence(
        client, before=before,
        result={"status": "ERROR", "success": False, "reqId": "request-current"})
    assert evidence["dispatch_status"] == DISPATCHED


def test_phase6_clock_receipt_cannot_replace_missing_generic_receipt():
    clock = EvidenceClock()
    client = _client(clock=clock)
    before = _target_dispatch_checkpoint(client)
    client._evidence_active_request_id = "request-current"
    clock.dispatch(["shell", "am", "broadcast", "-a",
                    "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT",
                    "--es", "reqId", "request-current"])
    evidence = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "SUCCESS", "reqId": "request-current"})
    assert evidence["dispatch_status"] == UNKNOWN
    assert evidence["dispatch_occurred"] is None


def test_budget_consumes_once_per_dispatched_operation_and_zero_otherwise():
    budget = ExecutionBudget()
    dispatched = NativeDispatchEvidence(
        operation_id="operation-1", request_id="request-1", store_generation="generation-1",
        checkpoint_status="VALID", receipt_watermark_before=0, receipt_seq=1,
        receipt_match=True, native_boundary_status="ENTERED", dispatch_status=DISPATCHED,
        evidence_source="GENERIC_NATIVE_RECEIPT")
    args = dict(evidence=dispatched, mode="CONTROLLED_TARGET_FOCUS", target="candidate-1",
                inventory="inventory-1", state="state-1")
    assert budget.reserve_dispatched_once(**args) is True
    assert budget.reserve_dispatched_once(**args) is False
    assert budget.actions == 1
    for status in (NOT_DISPATCHED, UNKNOWN):
        other = NativeDispatchEvidence(
            operation_id=f"operation-{status}", request_id="request-1", store_generation="generation-1",
            checkpoint_status="VALID", receipt_watermark_before=0, receipt_seq=None,
            receipt_match=False, native_boundary_status="UNKNOWN", dispatch_status=status,
            evidence_source="GENERIC_NATIVE_RECEIPT")
        assert budget.reserve_dispatched_once(**{**args, "evidence": other}) is False
    with pytest.raises(TypeError):
        budget.reserve_dispatched_once(**{**args, "evidence": {"dispatch_status": DISPATCHED}})
    assert budget.actions == 1


def test_unknown_dispatch_blocks_followup_without_consuming_budget():
    budget = ExecutionBudget()
    budget.block_unknown_dispatch()
    assert budget.actions == 0
    assert budget.degraded is True
    assert budget.degraded_reason == "NATIVE_DISPATCH_EVIDENCE_UNKNOWN"


def test_legacy_watermark_fields_do_not_override_typed_unknown():
    client = _client()
    before = _target_dispatch_checkpoint(client)
    before["native_receipt_watermark"] = 0
    before["clock_receipt_watermark"] = 0
    client._evidence_active_request_id = "request-current"
    evidence = _phase4_native_dispatch_evidence(
        client, before=before, result={"status": "SUCCESS", "reqId": "request-current"})
    assert evidence["dispatch_status"] == UNKNOWN
