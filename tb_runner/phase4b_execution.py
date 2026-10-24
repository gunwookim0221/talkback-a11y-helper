"""Controlled adapter using production actions, collection and reconciliation.

    Used by the Phase 4B harness and the independently gated Phase 6D3A
    targeted-focus path after current Phase 4 and Phase 5 revalidation.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy

from talkback_lib.window_lifecycle import get_talkback_restart_event
from talkback_lib.utils import normalize_bounds
from tb_runner import collection_flow, focus_reconciliation, scroll_reliability
from tb_runner.phase4b_authority import correlated_result
from tb_runner.phase4b_target_binding import actual_target_matches, resolve_focus_target
from tb_runner.traversal_reliability import focus_instance


def _target_dispatch_checkpoint(client):
    """Capture request and generic/Phase 6 receipt watermarks before target IO."""
    device = getattr(client, "_adb_device", None)
    native_store = getattr(device, "native_dispatch_receipts", None)
    try:
        from talkback_lib.native_dispatch_evidence import native_dispatch_checkpoint
        typed_checkpoint = native_dispatch_checkpoint(native_store)
    except Exception:
        typed_checkpoint = None
    try:
        native_watermark = native_store.receipt_watermark() if native_store is not None else None
    except Exception:
        native_watermark = None
    try:
        from talkback_lib.exploration_evidence_clock import clock_for
        clock = clock_for(client)
    except Exception:
        clock = None
    try:
        clock_watermark = clock.receipt_watermark() if clock is not None else None
    except Exception:
        clock_watermark = None
    return {
        "native_receipt_store": native_store,
        "native_receipt_watermark": native_watermark,
        # Generic Phase4 accounting uses this graph-independent checkpoint.
        # The legacy fields below are retained only for ACTIVE redirect compatibility.
        "native_dispatch_checkpoint": typed_checkpoint,
        "operation_id": getattr(typed_checkpoint, "operation_id", ""),
        "evidence_clock": clock,
        "scope_id": getattr(clock, "scope_id", None),
        "action_epoch": getattr(clock, "action_epoch", None),
        "clock_receipt_watermark": clock_watermark,
        "active_request_id": str(getattr(client, "_evidence_active_request_id", "") or "").strip(),
    }


def _redirect_dispatch_evidence_compat(client, *, before, result) -> dict[str, object]:
    """Preserve the existing ACTIVE redirect evidence adapter unchanged.

    Result status and the active request field are descriptive. Neither can
    prove dispatch by itself because both can survive an earlier operation.
    Generic Phase4 accounting does not call this compatibility function.
    """
    result = result if isinstance(result, dict) else {}
    result_request_id = str(result.get("reqId") or result.get("requestId") or "").strip()
    active_request_id = str(getattr(client, "_evidence_active_request_id", "") or "").strip()
    try:
        from talkback_lib.exploration_evidence_clock import clock_for
        clock = clock_for(client)
    except Exception:
        clock = None
    after_epoch = getattr(clock, "action_epoch", None) if clock is not None else None
    before_epoch = before.get("action_epoch") if isinstance(before, dict) else None
    epoch_delta = (after_epoch - before_epoch
                   if type(after_epoch) is int and type(before_epoch) is int else None)
    previous_request_id = str((before or {}).get("active_request_id") or "")
    current_request_id = result_request_id
    if active_request_id and active_request_id != previous_request_id:
        # The runner's newly installed request ID identifies this operation.
        # A stale/mismatched Helper result must not erase proof that the native
        # command was sent; it is rejected separately by ACK reconciliation.
        current_request_id = active_request_id
    elif current_request_id == previous_request_id:
        current_request_id = ""

    target_actions = {"TARGET_FOCUS_COMMIT", "FOCUS_TARGET", "FOCUS_IN_BOUNDS"}
    native_store = (before or {}).get("native_receipt_store")
    native_store_matches = (native_store is not None
        and native_store is getattr(getattr(client, "_adb_device", None), "native_dispatch_receipts", None))
    try:
        native_receipts = (native_store.receipts_after(
            int((before or {}).get("native_receipt_watermark") or 0),
            request_id=current_request_id)
            if native_store_matches and current_request_id else [])
    except Exception:
        native_receipts = []
    matching_native_receipt = next((receipt for receipt in native_receipts
        if isinstance(receipt, dict)
        and str(receipt.get("action_type") or "").upper() in target_actions
        and receipt.get("owner") == "TARGETED"
        and receipt.get("ownership_status") == "KNOWN"
        and receipt.get("dispatch_status") == "NATIVE_DISPATCH_ATTEMPTED"), None)
    clock_before = (before or {}).get("evidence_clock")
    scope_matches = bool(clock is not None and clock is clock_before
                         and getattr(clock, "scope_id", None) == (before or {}).get("scope_id"))
    try:
        clock_receipts = (clock.receipts_after(
            int((before or {}).get("clock_receipt_watermark") or 0),
            request_id=current_request_id)
            if scope_matches and current_request_id else [])
    except Exception:
        clock_receipts = []
    matching_clock_receipt = next((receipt for receipt in clock_receipts
        if isinstance(receipt, dict)
        and str(receipt.get("action_type") or "").upper() in target_actions
        and receipt.get("owner") == "TARGETED"
        and receipt.get("ownership_status") == "KNOWN"
        and receipt.get("dispatch_status") == "NATIVE_DISPATCH_ATTEMPTED"), None)
    generic_present = matching_native_receipt is not None
    phase6_present = bool(matching_clock_receipt is not None
                          and type(epoch_delta) is int and epoch_delta > 0)
    # Layer A is authoritative for Phase 4 accounting. Phase 6 can corroborate
    # provenance, but never substitutes for the graph-independent native proof.
    dispatched = bool(current_request_id and generic_present)
    evidence_source = ("BOTH" if generic_present and phase6_present else
                       "GENERIC_NATIVE_RECEIPT" if generic_present else "NONE")
    status = str(result.get("status") or "").strip().upper()
    reason = str(result.get("reason") or "").strip()
    preflight_statuses = {"PHASE5B_AUTHORIZATION_BLOCKED", "PREFLIGHT_BLOCKED",
                          "PHASE5_AUTHORIZATION_BLOCKED", "NOT_DISPATCHED", "NOT_SENT",
                          "TARGET_RESOLUTION_FAILED", "PRECHECK_BLOCKED"}
    preflight_block_reason = ""
    if not dispatched and (status in preflight_statuses or reason in {
            "helper_unavailable", "phase5b_focus_dispatch_preflight_denied"}):
        preflight_block_reason = reason or status.lower()
    return {
        "dispatch_occurred": dispatched,
        "dispatch_evidence_source": evidence_source,
        "current_request_id": current_request_id,
        "native_receipt_present": generic_present,
        "generic_native_receipt_present": generic_present,
        "phase6_evidence_clock_present": phase6_present,
        "action_epoch_delta": epoch_delta,
        "current_request_correlated": bool(generic_present),
        "preflight_block_reason": preflight_block_reason,
    }


def _phase4_native_dispatch_evidence(client, *, before, result,
                                     expected_request_id=None,
                                     native_boundary_entered=None,
                                     operation_exception=False) -> dict[str, object]:
    """Return the graph-independent typed dispatch verdict for Phase4.

    The legacy helper above remains isolated to the excluded ACTIVE redirect
    compatibility path. Generic controlled Phase4 accounting must use this
    result and must not infer a send from Phase6 clock state or a stale ACK.
    """
    from talkback_lib.native_dispatch_evidence import (
        DISPATCHED, NOT_DISPATCHED, UNKNOWN, native_dispatch_evidence,
    )

    result = result if isinstance(result, dict) else {}
    result_request_id = str(result.get("reqId") or result.get("requestId") or "").strip()
    active_request_id = str(getattr(client, "_evidence_active_request_id", "") or "").strip()
    previous_request_id = str((before or {}).get("active_request_id") or "")
    explicit_request_id = str(expected_request_id or "").strip()
    if expected_request_id is not None:
        current_request_id = explicit_request_id
    elif active_request_id and active_request_id != previous_request_id:
        current_request_id = active_request_id
    elif result_request_id and result_request_id != previous_request_id:
        current_request_id = result_request_id
    else:
        current_request_id = ""

    status = str(result.get("status") or "").strip().upper()
    reason = str(result.get("reason") or "").strip().lower()
    preflight_statuses = {
        "PHASE5B_AUTHORIZATION_BLOCKED", "PREFLIGHT_BLOCKED",
        "PHASE5_AUTHORIZATION_BLOCKED", "NOT_DISPATCHED", "NOT_SENT",
        "TARGET_RESOLUTION_FAILED", "PRECHECK_BLOCKED", "TALKBACK_RESTARTED",
    }
    preflight_reasons = {
        "helper_unavailable", "phase5b_focus_dispatch_preflight_denied",
        "talkback_restarted", "target_resolution_failed", "safetyblocked",
    }
    # An exception name is not a pre-native rejection: the same exception
    # can arise while reading a response after the native boundary.
    precheck_rejected = (not operation_exception and
                         (status in preflight_statuses or reason in preflight_reasons))
    boundary_entered = (not precheck_rejected if native_boundary_entered is None
                        else native_boundary_entered)
    operation_error = bool(status in {"ERROR", "FAILED", "TIMEOUT", "TALKBACK_RESTARTED"}
                           or result.get("success") is False or operation_exception)

    captured_store = (before or {}).get("native_receipt_store")
    current_store = getattr(getattr(client, "_adb_device", None),
                            "native_dispatch_receipts", None)
    store_matches = captured_store is not None and captured_store is current_store
    store = captured_store if store_matches else None
    checkpoint = (before or {}).get("native_dispatch_checkpoint")
    try:
        typed = native_dispatch_evidence(
            checkpoint, store,
            request_id=current_request_id or None,
            native_boundary_entered=boundary_entered,
            precheck_rejected=precheck_rejected,
            operation_error=operation_error,
        )
    except Exception:
        typed = None
    dispatch_status = getattr(typed, "dispatch_status", UNKNOWN)
    if dispatch_status not in {DISPATCHED, NOT_DISPATCHED, UNKNOWN}:
        dispatch_status = UNKNOWN
    occurred = (True if dispatch_status == DISPATCHED else
                False if dispatch_status == NOT_DISPATCHED else None)
    return {
        "dispatch_status": dispatch_status,
        # Tri-state compatibility: UNKNOWN is None, never a false negative.
        "dispatch_occurred": occurred,
        "dispatch_evidence_source": "GENERIC_NATIVE_RECEIPT" if dispatch_status == DISPATCHED else "NONE",
        "current_request_id": current_request_id,
        "operation_id": str(getattr(typed, "operation_id", "") or ""),
        "store_generation": getattr(typed, "store_generation", None),
        "receipt_seq": getattr(typed, "receipt_seq", None),
        "native_receipt_present": getattr(typed, "receipt_match", False) is True,
        "generic_native_receipt_present": getattr(typed, "receipt_match", False) is True,
        "phase6_evidence_clock_present": False,
        "action_epoch_delta": None,
        "current_request_correlated": getattr(typed, "receipt_match", False) is True,
        "preflight_block_reason": (reason or status.lower()) if precheck_rejected else "",
        "evidence_reason": str(getattr(typed, "reason", "EVIDENCE_UNAVAILABLE") or ""),
        "checkpoint_status": str(getattr(typed, "checkpoint_status", UNKNOWN) or UNKNOWN),
        "typed_evidence_used": typed is not None,
        "receipt_store_identity_match": store_matches,
        "_typed_evidence": typed,
    }


def focus_row(node, scenario):
    return dict(scenario_id=scenario, actual_focus_node=deepcopy(node),
                actual_focus_accessibility_focused=node.get("accessibilityFocused"),
                actual_focus_resource_id=node.get("viewIdResourceName") or node.get("resourceId") or "",
                actual_focus_bounds=normalize_bounds(node),
                actual_focus_class_name=node.get("className", ""),
                actual_focus_visible=node.get("text") or node.get("contentDescription")
                    or node.get("talkbackLabel") or node.get("mergedLabel") or "",
                actual_focus_payload_source="phase4b_fresh_strict_before")


def coherent_focus(raw):
    """Require one tree accessibility focus agreeing with the strict focus read."""
    focus = raw.get("focus_node") or {}
    if focus.get("accessibilityFocused") is not True or focus_instance(focus_row(focus, "coherence_check")) is None:
        return False
    focused = [n for n in scroll_reliability.flat_nodes(raw.get("nodes", []))
               if n.get("accessibilityFocused") is True]
    if len(focused) != 1:
        return False
    def key(n):
        return (n.get("viewIdResourceName") or n.get("resourceId") or "",
                scroll_reliability.normalized_bounds(n.get("boundsInScreen") or n.get("bounds") or ""))
    return bool(key(focus)[1] and key(focus) == key(focused[0]))


def safe_scroll_container(raw, recommendation):
    cap = raw.get("capability") or {}
    container = cap.get("container") or {}
    target = recommendation.to_dict().get("recommended_target") or {}
    return bool(cap.get("axis_contract") == "axis-v1" and cap.get("contradictory") is False
                and cap.get("can_scroll_forward") is True and container.get("path")
                and container.get("axis") in {"VERTICAL", "BIDIRECTIONAL"}
                and scroll_reliability.normalized_bounds(container.get("boundsInScreen")) == target.get("bounds"))


def geometry_in_viewport(raw, recommendation):
    from tb_runner.utils import parse_bounds_str
    bounds = parse_bounds_str((recommendation.to_dict().get("recommended_target") or {}).get("bounds", ""))
    display = raw.get("display_bounds")
    return bool(bounds and isinstance(display, (list, tuple)) and len(display) == 4
                and display[0] <= bounds[0] < bounds[2] <= display[2]
                and display[1] <= bounds[1] < bounds[3] <= display[3])


@contextmanager
def _phase4_request_capture(client, state, action):
    """Bind the request before broadcast inside the caller's operation scope.

    This is not dispatch proof: only the typed native receipt can prove entry.
    No client cache is read. Overrides are restored even when IO/parse raises.
    """
    broadcast = getattr(client, "_broadcast", None)
    had_override = "_broadcast" in vars(client)
    def observed_broadcast(*args, **kwargs):
        selected = kwargs.get("action", args[1] if len(args) > 1 else "")
        extras = kwargs.get("extras", args[2] if len(args) > 2 else [])
        if str(selected).rsplit(".", 1)[-1] == action:
            requests = [str(extras[i + 1]) for i in range(len(extras) - 1)
                        if extras[i] in {"reqId", "requestId", "request_id"}]
            # Multiple sends/IDs in one operation are ambiguous, never pick latest.
            state.setdefault("request_ids", []).extend(requests)
            state["request_id"] = state["request_ids"][0] if len(state["request_ids"]) == 1 else ""
            state["request_ambiguous"] = len(state["request_ids"]) != 1
        return broadcast(*args, **kwargs)
    if callable(broadcast):
        client._broadcast = observed_broadcast
    try:
        yield
    except Exception as exc:
        state["operation_error"] = type(exc).__name__
        raise
    finally:
        if callable(broadcast):
            if had_override:
                client._broadcast = broadcast
            else:
                del client._broadcast


def scroll_request_audit(client, scroll, audit, **kwargs):
    """Capture pre-send identity and preserve the existing reader diagnostics API."""
    state = audit.setdefault("scroll_operation_capture", {})
    reader = getattr(client, "_read_log_result", None)
    had_override = "_read_log_result" in vars(client)
    def observed_reader(*args, **read_kwargs):
        prefix = read_kwargs.get("prefix", args[1] if len(args) > 1 else None)
        request = read_kwargs.get("req_id", args[2] if len(args) > 2 else None)
        if prefix == "SCROLL_RESULT":
            # Diagnostic only. Real dispatch ownership is captured before send.
            audit.update(helper_request_id=str(request or ""),
                         helper_request_source="SCROLL_RESULT_EXPLICIT_TRANSPORT_ARGUMENT")
        result = reader(*args, **read_kwargs)
        if prefix == "SCROLL_RESULT":
            audit.update(helper_ack_result=deepcopy(result),
                         helper_result_correlated=bool(request and isinstance(result, dict)
                             and str(request) == str(result.get("reqId") or "")))
        return result
    if callable(reader):
        client._read_log_result = observed_reader
    try:
        with _phase4_request_capture(client, state, "SCROLL"):
            return scroll(**kwargs)
    finally:
        if callable(reader):
            if had_override:
                client._read_log_result = reader
            else:
                del client._read_log_result


def controlled_collect(*, client, dev, scenario, step, raw, recommendation, decision,
                       budget, collect, collect_kwargs, refresh, output_dir, audit, audit_sink=None,
                       focus_authorization=None, defer_budget_reservation=False,
                       dispatch_observer=None, native_dispatch_observer=None,
                       operation_observer=None):
    """At most one controlled action and one production fallback in a step.

    The returned row still travels through the complete production main loop.
    The pure reconciliation preview decides fallback only; its credit is never
    applied. Production reconciliation and metrics are the sole visit owners.
    """
    def attach_reconciliation_lineage(row):
        if not isinstance(row, dict):
            return row
        owner = audit.get("fallback_observation_ownership")
        owner = owner if isinstance(owner, dict) else {}
        observation_ids = owner.get("request_ids")
        observation_ids = list(observation_ids) if isinstance(observation_ids, list) else []
        production_request = str(owner.get("production_request_id") or row.get("get_focus_req_id") or "")
        if not observation_ids and production_request:
            observation_ids = [production_request]
        observation_transaction_id = str(owner.get("transaction_id") or "")
        if not observation_transaction_id:
            lookup = getattr(client, "_evidence_transaction_for_step", None)
            if callable(lookup):
                try:
                    observation_transaction_id = str(lookup(step) or "")
                except Exception:
                    observation_transaction_id = ""
        lineage = {
            "scenario_id": str(row.get("scenario_id") or scenario),
            "primary_action_request_id": str(audit.get("helper_request_id") or ""),
            "primary_action_type": str(
                audit.get("scroll_action") or audit.get("planner_action") or audit.get("production_fallback_action") or ""
            ),
            "fallback_action_request_id": str(audit.get("fallback_helper_request_id") or ""),
            "observation_transaction_id": observation_transaction_id,
            "observation_request_ids": observation_ids,
            "production_observation_request_id": production_request,
        }
        lineage_by_step = getattr(client, "_focus_reconciliation_lineage_by_step", None)
        if not isinstance(lineage_by_step, dict):
            lineage_by_step = {}
            try:
                setattr(client, "_focus_reconciliation_lineage_by_step", lineage_by_step)
            except Exception:
                row["_focus_reconciliation_lineage"] = lineage
                return row
        lineage_by_step[str(row.get("step_index", step) or step)] = lineage
        return row

    def emit(event):
        if audit_sink is not None:
            audit_sink(dict(event=event, **deepcopy(audit)))

    def fallback(reason):
        budget.fallback_count += 1
        audit.update(fallback_used=True, fallback_reason=reason,
                     production_fallback_action="FOCUS_NEXT")
        emit("BEFORE_PRODUCTION_FALLBACK")
        from talkback_lib.exploration_evidence_clock import dispatch_owner
        from talkback_lib.smart_nav_invocation import current_generation, current_result
        before_generation = current_generation(client)
        with dispatch_owner("FALLBACK"):
            row = collect(**collect_kwargs)
        # The global result cache is historical diagnostic state. Attribute a
        # fallback only when the returned row and result have the new
        # invocation generation created during this collection call.
        row_generation = row.get("smart_nav_invocation_generation") if isinstance(row, dict) else None
        fresh_boundary = (type(row_generation) is int and row_generation > 0
            and (before_generation is None or row_generation > before_generation)
            and row_generation == current_generation(client))
        fresh_invocation = fresh_boundary and row.get("smart_nav_result_generation") == row_generation
        invocation = current_result(client, row_generation) if fresh_invocation else {}
        row_request_id = str(
            row.get("smart_nav_req_id") or ""
        ).strip() if isinstance(row, dict) and row.get("phase6_current_action_type") == "SMART_NEXT" else ""
        invocation_request_id = str(invocation.get("reqId") or invocation.get("requestId") or "").strip()
        ack = (deepcopy(invocation)
               if row_request_id and row_request_id == invocation_request_id else {})
        if isinstance(row, dict) and row.get("phase6_current_action_type") == "SMART_NEXT" and not ack:
            from talkback_lib.step_row_builder import extract_smart_nav_row_fields
            row.update(extract_smart_nav_row_fields({}, False))
            if not fresh_boundary:
                row["move_result"] = {
                    "success": False, "status": "failed",
                    "raw": {"status": "transport_error", "reason": "fallback_invocation_currentness_unproven"},
                }
        fallback_request_id = str(ack.get("reqId") or ack.get("requestId") or "").strip()
        audit.update(fallback_helper_request_id=fallback_request_id, fallback_helper_ack_result=ack,
                     fallback_result_correlated=correlated_result(client, ack))
        if not audit.get("planner_executed"):
            audit.update(helper_request_id=fallback_request_id, helper_ack_result=ack)
        emit("AFTER_PRODUCTION_FALLBACK")
        return attach_reconciliation_lineage(row)

    if not decision.allowed:
        from talkback_lib.exploration_evidence_clock import clock_for
        if clock_for(client) is not None:
            client._phase6_redirect_proofs = {}
        audit["classification"] = ("PRODUCTION_ONLY" if decision.mode == "SHADOW_ONLY" else
                                    "PLANNER_NO_SAFE_ACTION" if decision.reason == "NO_SAFE_PLANNER_ACTION" else
                                    "PLANNER_BLOCKED_BY_GATE")
        audit["actual_execution_mode"] = decision.mode
        return fallback(decision.reason)
    chosen = recommendation.to_dict()
    from tb_runner.redirect_evidence import record_existing_proof
    from tb_runner.canonical_json import canonical_sha256
    gate_proof = dict(allowed=decision.allowed, mode=decision.mode, reason=decision.reason,
                      selected_instance_id=chosen["recommended_instance_id"])
    record_existing_proof(client, kind="planner", status="ELIGIBLE" if decision.mode == "CONTROLLED_TARGET_FOCUS" else "UNSUPPORTED", instance=chosen["recommended_instance_id"],
                          raw=raw, step=step, proof=gate_proof, policy_ref=canonical_sha256(gate_proof))
    audit.update(actual_execution_mode=decision.mode, planner_executed=False,
                 classification="PLANNER_EXECUTED", fallback_used=False, fallback_reason="")
    before = focus_row(raw.get("focus_node") or {}, scenario)
    audit["actual_focus_before"] = before
    if decision.mode == "CONTROLLED_SCROLL":
        observed = scroll_reliability.capture(client, dev, scenario, step_index=step,
                                              evidence="phase4b_verified_scroll_before")
        # Revalidate the actual production container; the earlier capability
        # copy must not authorize a different path/container at execution time.
        if not safe_scroll_container(dict(capability=observed["capability"]), recommendation):
            audit.update(dispatch_status="NOT_DISPATCHED", planner_failed=True,
                         classification="PLANNER_FAILED_FALLBACK_USED")
            return fallback("SCROLL_CONTAINER_CHANGED")
        audit["planner_executed"] = True
        emit("BEFORE_CONTROLLED_SCROLL")
        audit["scroll_operation_capture"] = {}
        original_scroll = getattr(client, "scroll", None)
        had_scroll_override = "scroll" in vars(client)
        def correlated_scroll(**kwargs):
            return scroll_request_audit(client, original_scroll, audit, **kwargs)
        client.scroll = correlated_scroll
        try:
            before_dispatch = _target_dispatch_checkpoint(client)
            audit["scroll_operation_capture"].update(
                operation_id=before_dispatch.get("operation_id"),
                store_generation=getattr(before_dispatch.get("native_dispatch_checkpoint"), "store_generation", None))
            try:
                from talkback_lib.native_dispatch_evidence import native_dispatch_operation, dispatch_owner
                operation_context = native_dispatch_operation(
                    before_dispatch.get("operation_id") or None)
                owner_context = dispatch_owner("TARGETED")
            except Exception:
                operation_context, owner_context = nullcontext(""), nullcontext()
            with operation_context, owner_context:
                result, after = scroll_reliability.verified_scroll(
                    client, dev, scenario, step, before=observed, output_base_dir=output_dir)
        except Exception as exc:
            # The scroll implementation may raise after entering ADB. Keep the
            # operation result uncertain until the typed receipt is evaluated.
            result = {
                "status": "SCROLL_INDETERMINATE", "action_success": False,
                "before": observed.get("viewport", {}), "after": {},
                "viewport_changed": False,
                "action_result": {"status": "ERROR", "reason": type(exc).__name__},
                "error": type(exc).__name__,
            }
            after = {}
        finally:
            if had_scroll_override:
                client.scroll = original_scroll
            else:
                del client.scroll
        scroll_action_result = result.get("action_result") if isinstance(result, dict) else {}
        capture = audit["scroll_operation_capture"]
        scroll_request_id = (capture.get("request_id") or audit.get("helper_request_id")
                             or (scroll_action_result.get("reqId") if isinstance(scroll_action_result, dict) else "")
                             or (scroll_action_result.get("requestId") if isinstance(scroll_action_result, dict) else ""))
        if capture.get("operation_error"):
            scroll_action_result = {"status": "ERROR", "reason": capture["operation_error"]}
        if capture.get("request_ambiguous"):
            scroll_request_id = ""
            scroll_action_result = {}
        dispatch_proof = _phase4_native_dispatch_evidence(
            client, before=before_dispatch, result=scroll_action_result,
            expected_request_id=scroll_request_id,
            operation_exception=bool(capture.get("operation_error") or result.get("error")))
        typed_dispatch_evidence = dispatch_proof.pop("_typed_evidence", None)
        ack = scroll_action_result if isinstance(scroll_action_result, dict) else {}
        audit.update(helper_ack_result=deepcopy(ack),
                     helper_result_correlated=bool(scroll_request_id and str(
                         ack.get("reqId") or ack.get("requestId") or "") == scroll_request_id),
                     helper_request_source="SCROLL_OPERATION_PRE_BROADCAST")
        audit.update(
            dispatch_evidence=deepcopy(dispatch_proof),
            dispatch_status=dispatch_proof["dispatch_status"],
            dispatch_occurred=dispatch_proof["dispatch_occurred"],
            planner_executed=(True if dispatch_proof["dispatch_status"] == "DISPATCHED"
                              else False if dispatch_proof["dispatch_status"] == "NOT_DISPATCHED"
                              else None),
            dispatch_evidence_source=dispatch_proof["dispatch_evidence_source"],
            current_request_id=dispatch_proof["current_request_id"],
            native_receipt_present=dispatch_proof["native_receipt_present"],
            preflight_block_reason=dispatch_proof["preflight_block_reason"],
            helper_request_id=dispatch_proof["current_request_id"],
        )
        if dispatch_proof["dispatch_status"] == "DISPATCHED":
            budget.reserve_dispatched_once(
                evidence=typed_dispatch_evidence, mode=decision.mode,
                target=chosen["recommended_instance_id"], inventory=raw["snapshot_hash"],
                state=(chosen["planner_state_id"], chosen["semantic_substates"]))
        elif dispatch_proof["dispatch_status"] == "UNKNOWN":
            budget.block_unknown_dispatch()
        before_viewport = result.get("before") if isinstance(result, dict) else {}
        after_viewport = result.get("after") if isinstance(result, dict) else {}
        status = ("SCROLL_MOVED" if result.get("status") == "SCROLL_MOVED" else
                  "SCROLL_NO_MOVEMENT" if isinstance(before_viewport, dict)
                  and before_viewport.get("valid") and isinstance(after_viewport, dict)
                  and after_viewport.get("valid") and result.get("action_success") is True
                  and result.get("viewport_changed") is False else "SCROLL_INDETERMINATE")
        audit.update(scroll_result=status, scroll_transition=result)
        emit("AFTER_CONTROLLED_SCROLL")
        if dispatch_proof["dispatch_status"] == "DISPATCHED":
            budget.outcome(status, status == "SCROLL_MOVED")
        elif dispatch_proof["dispatch_status"] == "UNKNOWN":
            audit.update(planner_failed=True, classification="PLANNER_DISPATCH_UNKNOWN_FAIL_CLOSED",
                         fallback_used=False, controlled_budget_outcome="UNKNOWN_NO_CONSUMPTION_NO_RETRY")
            row = collect(**{**collect_kwargs, "move": False})
            row.update(move_result="SCROLL_DISPATCH_UNKNOWN", scroll_transition=result,
                       phase4b_before_row=before)
            return attach_reconciliation_lineage(row)
        if capture.get("operation_error") or capture.get("request_ambiguous") or result.get("error"):
            audit.update(planner_failed=True, classification="PLANNER_EXCEPTION_NO_RETRY",
                         fallback_used=False, fallback_reason="CURRENT_OPERATION_EXCEPTION")
            row = collect(**{**collect_kwargs, "move": False})
            row.update(move_result="SCROLL_INDETERMINATE", scroll_transition=result,
                       phase4b_before_row=before)
            return attach_reconciliation_lineage(row)
        # Always refresh, even for uncertain/no movement. No old rank is reused.
        refreshed = refresh()
        audit["post_scroll_refresh"] = refreshed
        if status != "SCROLL_MOVED":
            audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED")
            return fallback(status)
        row = collect(**{**collect_kwargs, "move": False})
        row.update(move_result="scrolled", scroll_transition=result, phase4b_before_row=before)
        return attach_reconciliation_lineage(row)

    target = chosen["recommended_target"]
    # Select exactly the freshly gated node, never a label/scenario guess.
    node, binding = resolve_focus_target(raw, chosen, scenario)
    audit["target_binding"] = binding
    for kind in ("binding", "presence"):
        record_existing_proof(client, kind=kind,
            status=("RESOLVED" if kind == "binding" else "PRESENT") if node is not None else "UNRESOLVED",
            instance=chosen["recommended_instance_id"], raw=raw, step=step, proof=binding,
            policy_ref="phase4b-target-binding-v1")
    if node is None:
        audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED")
        return fallback("TARGET_DISAPPEARED_OR_AMBIGUOUS")
    target_meta = dict(focus_node=raw.get("focus_node"), actual_focus_node=raw.get("focus_node"))
    client._evidence_set_step(step, phase="main_loop")
    emit("BEFORE_CONTROLLED_TARGET_FOCUS")
    original_target_commit = client.target_focus_commit
    had_target_override = "target_focus_commit" in vars(client)
    target_dispatch = {"occurred": False, "status": "NOT_DISPATCHED",
                       "dispatch_status": "NOT_DISPATCHED", "reserved": False,
                       "accounted_operation_ids": set(), "evidence": {}}
    phase4_native_accounting = not callable(dispatch_observer)
    def focusable_commit(**kwargs):
        if (phase4_native_accounting and budget.degraded
                and budget.degraded_reason == "NATIVE_DISPATCH_EVIDENCE_UNKNOWN"):
            return {"success": False, "status": "NOT_DISPATCHED",
                    "reason": "prior_native_dispatch_evidence_unknown"}
        before_dispatch = _target_dispatch_checkpoint(client)
        result = None
        operation_capture = {"operation_id": before_dispatch.get("operation_id"),
                             "store_generation": getattr(before_dispatch.get("native_dispatch_checkpoint"), "store_generation", None)}
        try:
            try:
                from talkback_lib.native_dispatch_evidence import native_dispatch_operation
                operation_context = native_dispatch_operation(
                    before_dispatch.get("operation_id") or None)
            except Exception:
                operation_context = nullcontext("")
            capture_context = (_phase4_request_capture(client, operation_capture, "TARGET_FOCUS_COMMIT")
                               if phase4_native_accounting else nullcontext())
            with operation_context, capture_context:
                if phase4_native_accounting and callable(operation_observer):
                    operation_observer(before_dispatch.get("operation_id"),
                                       target_meta.get("target_focus_attempt_id"))
                result = original_target_commit(**{
                    **kwargs, "target": {**kwargs["target"], "require_focusable": True}})
            return result
        finally:
            # Only a direct return belongs to this invocation. The compatibility
            # cache can contain a different operation's precheck or ACK.
            result_doc = (result if isinstance(result, dict) else
                          {"status": "ERROR", "reason": operation_capture.get("operation_error", "result_unavailable")})
            if not phase4_native_accounting:
                result_doc = result or getattr(client, "last_target_action_result", {}) or {}
            target_dispatch["current_result"] = result_doc
            target_dispatch["operation_error"] = operation_capture.get("operation_error", "")
            if phase4_native_accounting:
                proof = _phase4_native_dispatch_evidence(
                    client, before=before_dispatch, result=result_doc,
                    expected_request_id=operation_capture.get("request_id"),
                    operation_exception=bool(operation_capture.get("operation_error")))
                typed_dispatch_evidence = proof.pop("_typed_evidence", None)
                dispatch_status = proof["dispatch_status"]
                occurred = dispatch_status == "DISPATCHED"
            else:
                # The ACTIVE redirect orchestrator remains on its existing
                # compatibility accounting path; RF3 does not migrate it.
                proof = _redirect_dispatch_evidence_compat(client, before=before_dispatch,
                                                           result=result_doc)
                typed_dispatch_evidence = None
                occurred = proof["dispatch_occurred"] is True
                dispatch_status = "DISPATCHED" if occurred else "NOT_DISPATCHED"
            target_dispatch["evidence"] = proof
            target_dispatch["occurred"] = bool(target_dispatch["occurred"] or occurred)
            target_dispatch["dispatch_status"] = (
                "DISPATCHED" if target_dispatch["occurred"] else dispatch_status)
            target_dispatch["operation_id"] = str(proof.get("operation_id") or "")
            status = str(result_doc.get("status") or "").strip().upper()
            target_dispatch["status"] = (
                target_dispatch["dispatch_status"] if phase4_native_accounting else
                "DISPATCH_ATTEMPTED" if occurred else
                "PREFLIGHT_BLOCKED" if proof.get("preflight_block_reason") or status in {
                    "PHASE5B_AUTHORIZATION_BLOCKED", "PREFLIGHT_BLOCKED",
                    "PHASE5_AUTHORIZATION_BLOCKED"} else "NOT_DISPATCHED")
            audit.update(
                dispatch_attempted=(bool(target_dispatch["occurred"])
                                    if target_dispatch["dispatch_status"] != "UNKNOWN" else None),
                dispatch_occurred=(bool(target_dispatch["occurred"])
                                   if target_dispatch["dispatch_status"] != "UNKNOWN" else None),
                dispatch_status=target_dispatch["status"],
                dispatch_evidence_status=target_dispatch["dispatch_status"],
                dispatch_evidence=deepcopy(proof),
                dispatch_evidence_source=proof.get("dispatch_evidence_source", "NONE"),
                current_request_id=proof.get("current_request_id", ""),
                native_receipt_present=proof.get("native_receipt_present") is True,
                action_epoch_delta=proof.get("action_epoch_delta"),
                preflight_block_reason=proof.get("preflight_block_reason", ""),
                helper_request_id=(proof.get("current_request_id", "") if occurred else ""),
                helper_ack_result=deepcopy(result_doc),
            )
            try:
                operation_id = str(proof.get("operation_id") or "")
                operation_already_accounted = (operation_id in target_dispatch["accounted_operation_ids"]
                                               if operation_id else target_dispatch["reserved"])
                if occurred and not operation_already_accounted:
                    if callable(dispatch_observer):
                        dispatch_observer()
                    elif not defer_budget_reservation:
                        budget.reserve_dispatched_once(
                            evidence=typed_dispatch_evidence,
                            mode=decision.mode, target=chosen["recommended_instance_id"],
                            inventory=raw["snapshot_hash"],
                            state=(chosen["planner_state_id"], chosen["semantic_substates"]))
                    if operation_id:
                        target_dispatch["accounted_operation_ids"].add(operation_id)
                    target_dispatch["reserved"] = True
                if (phase4_native_accounting and dispatch_status == "UNKNOWN"
                        and not defer_budget_reservation):
                    budget.block_unknown_dispatch()
            finally:
                if phase4_native_accounting and callable(native_dispatch_observer):
                    native_dispatch_observer(typed_dispatch_evidence)
    client.target_focus_commit = focusable_commit
    try:
        authorization = (focus_authorization(target, node) if focus_authorization is not None
                        else nullcontext())
        from talkback_lib.exploration_evidence_clock import dispatch_owner
        from talkback_lib.exploration_evidence_clock import clock_for
        if clock_for(client) is not None:
            sources = getattr(client, "_phase6_redirect_proofs", {})
            client._phase6_redirect_proofs = {key: value for key, value in sources.items() if key != "safety"}
        with authorization as permit, dispatch_owner("TARGETED"):
            # Observe the real Phase5 FOCUS permit yielded by the existing
            # authorization path. Never classify, authorize, or consume it here.
            from tb_runner.phase4a_planner import production_instance
            if (isinstance(permit, dict) and permit.get("kind") == "FOCUS"
                    and permit.get("action_type") == "FOCUS"
                    and production_instance(permit.get("target_identity") or {}, scenario) == chosen["recommended_instance_id"]
                    and (permit.get("policy") or {}).get("eligible") is True):
                safety_proof = {key: permit.get(key) for key in ("classification", "policy", "conditions", "authorization_epoch")}
                record_existing_proof(client, kind="safety", status="ALLOWED",
                    instance=chosen["recommended_instance_id"], raw=raw, step=step, proof=safety_proof,
                    policy_ref=canonical_sha256(safety_proof))
            _, status, observed_focus = collection_flow._maybe_realign_focus_to_representative(
                row=target_meta, client=client, dev=dev, selected_node=node,
                selected_rid=target["resource_id"], selected_label="", selected_bounds=target["bounds"],
                scenario_id=scenario, step_idx=step, force_reason="phase4b_gated_structural_target")
    finally:
        if had_target_override:
            client.target_focus_commit = original_target_commit
        else:
            del client.target_focus_commit
    ack = deepcopy(target_dispatch.get("current_result", {}) if phase4_native_accounting
                   else getattr(client, "last_target_action_result", {}) or {})
    correlated = correlated_result(client, ack)
    audit["focus_attempt_metadata"] = target_meta.get("target_focus_attempted") is True
    audit["dispatch_attempted"] = (target_dispatch["occurred"]
                                    if target_dispatch["dispatch_status"] != "UNKNOWN" else None)
    audit["dispatch_occurred"] = (target_dispatch["occurred"]
                                   if target_dispatch["dispatch_status"] != "UNKNOWN" else None)
    audit["dispatch_status"] = target_dispatch["status"]
    audit["dispatch_evidence_status"] = target_dispatch["dispatch_status"]
    audit["dispatch_evidence"] = deepcopy(target_dispatch["evidence"])
    audit["dispatch_evidence_source"] = target_dispatch["evidence"].get("dispatch_evidence_source", "NONE")
    audit["current_request_id"] = target_dispatch["evidence"].get("current_request_id", "")
    audit["native_receipt_present"] = target_dispatch["evidence"].get("native_receipt_present") is True
    audit["action_epoch_delta"] = target_dispatch["evidence"].get("action_epoch_delta")
    audit["preflight_block_reason"] = target_dispatch["evidence"].get("preflight_block_reason", "")
    audit["planner_executed"] = (target_dispatch["occurred"]
                                 if target_dispatch["dispatch_status"] != "UNKNOWN" else None)
    audit.update(helper_request_id=str(
                     target_dispatch["evidence"].get("current_request_id")
                     if target_dispatch["occurred"] else ""),
                 helper_ack_result=ack, helper_result_correlated=correlated,
                 target_attempt_id=target_meta.get("target_focus_attempt_id"),
                 attempt_credit=(int(target_dispatch["occurred"])
                                 if target_dispatch["dispatch_status"] != "UNKNOWN" else None),
                 immediate_actual_focus=observed_focus, target_focus_status=status)
    emit("AFTER_CONTROLLED_TARGET_FOCUS")
    # Prevent a previous SMART_NEXT result leaking into a target-only row.
    client.last_smart_nav_result, client.last_smart_nav_terminal = {}, False
    row = collect(**{**collect_kwargs, "move": False})
    row.update(scenario_id=scenario, scenario_type="content")
    row.update({k: v for k, v in target_meta.items() if k.startswith("target_focus_")})
    row["phase4b_before_row"] = before
    row["move_result"] = client._normalize_action_result(success=bool(ack.get("success")),
                                                         status="MOVED" if ack.get("success") else "FAILED", raw=ack)
    observation = row.get("_exploration_observation")
    observation = observation if isinstance(observation, dict) else {}
    request_id = str(target_dispatch.get("evidence", {}).get("current_request_id") or "").strip()
    operation_id = str(target_dispatch.get("operation_id") or "").strip()
    attempt_id = str(target_meta.get("target_focus_attempt_id") or "").strip()
    descriptor = target_meta.get("target_focus_descriptor")
    descriptor = deepcopy(descriptor) if isinstance(descriptor, dict) else None
    dispatch_status = str(target_dispatch.get("dispatch_status") or "UNKNOWN").upper()
    row.update(
        phase6_current_action_type="CONTROLLED_FOCUS",
        controlled_focus_operation_id=operation_id,
        controlled_focus_request_id=request_id,
        controlled_focus_dispatch_status=dispatch_status,
    )
    try:
        from talkback_lib.exploration_evidence_clock import clock_for
        evidence_clock = clock_for(client)
        observation_current = bool(evidence_clock and evidence_clock.current(observation))
    except Exception:
        observation_current = False
    if (dispatch_status == "DISPATCHED" and operation_id and request_id and attempt_id
            and isinstance(descriptor, dict) and ack.get("reqId") == request_id
            and correlated and observation_current and observation.get("scope_id")
            and type(observation.get("action_epoch")) is int):
        row["controlled_focus_intent"] = {
            "schema_version": "phase4-controlled-focus-intent-v1",
            "scenario_id": scenario,
            "step_index": step,
            "operation_id": operation_id,
            "request_id": request_id,
            "target_attempt_id": attempt_id,
            "dispatch_status": dispatch_status,
            "target_descriptor": descriptor,
            "scope_id": observation.get("scope_id"),
            "action_epoch": observation.get("action_epoch"),
            "observation_id": observation.get("observation_id"),
            "observation_sequence": observation.get("observation_sequence"),
        }
    attach_reconciliation_lineage(row)
    preview = focus_reconciliation.reconcile_focus(row=row, previous_row=before, scenario_id=scenario,
        inventory=raw.get("nodes", []), expected_candidates=raw.get("nodes", []),
        physical_visit_confirmed=False, planning_consumed=False)
    moved = preview["focus_transition_status"] == "CONFIRMED_MOVED"
    matched = (moved and preview["actual_focus_instance_id"] == chosen["recommended_instance_id"]
               and actual_target_matches(row.get("actual_focus_node"), target))
    audit["focus_preview"] = {k: v for k, v in preview.items() if k not in {"actual_item", "mapped_candidate"}}
    emit("CONTROLLED_FOCUS_PREVIEW")
    audit["result_reconciled"] = True
    if target_dispatch["dispatch_status"] == "DISPATCHED":
        budget.outcome(preview["focus_transition_status"], matched and correlated)
    else:
        audit["controlled_budget_outcome"] = (
            "UNKNOWN_NO_CONSUMPTION_NO_RETRY"
            if target_dispatch["dispatch_status"] == "UNKNOWN"
            else "NOT_APPLIED_NO_NATIVE_DISPATCH")
    if get_talkback_restart_event(client):
        # The outer monitor/main loop owns immediate hard-stop; no fallback I/O.
        audit.update(planner_failed=True, fallback_reason="LIFECYCLE_HARD_STOP")
        return row
    if phase4_native_accounting and target_dispatch["dispatch_status"] == "UNKNOWN":
        audit.update(planner_failed=True, classification="PLANNER_DISPATCH_UNKNOWN_FAIL_CLOSED",
                     fallback_used=False, fallback_reason="NATIVE_DISPATCH_EVIDENCE_UNKNOWN")
        return row
    if phase4_native_accounting and target_dispatch.get("operation_error"):
        audit.update(planner_failed=True, classification="PLANNER_EXCEPTION_NO_RETRY",
                     fallback_used=False, fallback_reason="CURRENT_OPERATION_EXCEPTION")
        return row
    if phase4_native_accounting and target_dispatch["dispatch_status"] == "NOT_DISPATCHED":
        audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED",
                     controlled_action_status="NOT_DISPATCHED")
        return fallback(target_dispatch["evidence"].get("preflight_block_reason")
                        or "NATIVE_DISPATCH_NOT_PERFORMED")
    if not correlated or not moved:
        audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED",
                     controlled_action_status="PLANNER_ACTION_FAILED")
        return fallback("STALE_REQUEST_RESULT" if not correlated else
                        "INDETERMINATE_FOCUS" if preview["focus_transition_status"] in {"UNAVAILABLE", "AMBIGUOUS"}
                        else "FOCUS_EXECUTION_FAILED")
    if not matched:
        audit.update(planner_failed=True, classification="PLANNER_FAILED_FALLBACK_USED",
                     controlled_action_status="PLANNER_ACTION_FAILED")
        return fallback("FOCUS_TARGET_MISMATCH")
    return row
