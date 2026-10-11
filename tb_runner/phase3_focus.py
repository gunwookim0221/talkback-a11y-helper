"""Request-correlated observational focus normalization for Phase 3.

The adapter reports evidence only. It never updates the production visit
ledger, selects a candidate, or changes traversal behavior.
"""
from __future__ import annotations

from typing import Any, Mapping

from tb_runner.discovery_candidates import _node
from tb_runner.traversal_reliability import focus_instance, instance_id


def _millis(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _payload_node(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    node = _node(value)
    if not node.get("boundsInScreen"):
        return None
    return node


def _current_actual(raw: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    node = raw.get("actual_focus_node")
    source = "actual_focus_node"
    if not isinstance(node, Mapping):
        node = raw.get("focus_node")
        source = "helper_focus_result"
    if not isinstance(node, Mapping):
        return None, None
    normalized = _payload_node(node)
    if normalized is None:
        return None, None
    top = raw.get("actual_focus_accessibility_focused")
    flag = node.get("accessibilityFocused")
    if isinstance(top, bool) and isinstance(flag, bool) and top is not flag:
        return None, "CONTRADICTORY_ACCESSIBILITY_FOCUS_FLAGS"
    if top is True or (top is None and flag is True):
        normalized["accessibilityFocused"] = True
        return normalized, source
    return None, "INPUT_FOCUS_ONLY" if node.get("focused") is True else "NO_STRICT_ACCESSIBILITY_FOCUS"


def _ack_ledger(command_ack: Any, expected_request_id: str | None) -> dict[str, Any]:
    if not isinstance(command_ack, Mapping):
        return {"valid": False, "reason": "MISSING_HELPER_ACK"}
    nested = command_ack.get("raw")
    payload = nested if isinstance(nested, Mapping) else command_ack
    request_id = str(payload.get("reqId") or command_ack.get("reqId") or "").strip()
    expected = str(expected_request_id or request_id).strip()
    events = payload.get("evidenceEvents") or command_ack.get("evidenceEvents") or []
    if not request_id or request_id != expected:
        return {"valid": False, "reason": "REQUEST_ID_MISMATCH", "request_id": request_id,
                "expected_request_id": expected}
    if not isinstance(events, list) or not events:
        return {"valid": False, "reason": "MISSING_HELPER_REQUEST_LEDGER", "request_id": request_id}
    if any(not isinstance(event, Mapping) or event.get("reqId") != request_id
           or event.get("schemaVersion") != "evidence-helper-v1" for event in events):
        return {"valid": False, "reason": "STALE_OR_MIXED_REQUEST_LEDGER", "request_id": request_id}
    started = [event for event in events if event.get("eventType") == "ACTION_EXECUTION_STARTED"]
    requested = [event for event in events if event.get("eventType") == "TARGET_REQUESTED"]
    completed = [event for event in events if event.get("eventType") in {"ACTION_API_RESULT", "HELPER_ACK_SENT"}]
    if (len(started) != 1 or not requested or not completed
            or not isinstance(started[0].get("payload"), Mapping)
            or str(started[0]["payload"].get("action") or "").rsplit(".", 1)[-1] != "SMART_NEXT"):
        return {"valid": False, "reason": "REQUEST_LEDGER_NOT_HELPER_SMART_NEXT", "request_id": request_id}
    api_results = [event for event in events if event.get("eventType") == "ACTION_API_RESULT"
                   and isinstance(event.get("payload"), Mapping)]
    api_success = api_results[-1]["payload"].get("success") if api_results else None
    success_value = command_ack.get("success")
    if isinstance(success_value, bool) and isinstance(api_success, bool) and success_value is not api_success:
        return {"valid": False, "reason": "ACK_STATUS_CONFLICT", "request_id": request_id}
    success = success_value if isinstance(success_value, bool) else api_success
    if not isinstance(success, bool):
        status = str(command_ack.get("status") or payload.get("status") or "").casefold()
        success = status in {"moved", "success", "succeeded", "ok"}
    return {"valid": True, "request_id": request_id,
            "started_at": _millis(started[0].get("timestamp")),
            "ack_at": _millis(payload.get("timestamp")), "success": success,
            "events": events}


def _row(raw: Mapping[str, Any], node: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _node(node)
    label = (normalized.get("talkbackLabel") or normalized.get("contentDescription")
             or normalized.get("text") or normalized.get("mergedLabel") or "")
    return dict(scenario_id="phase3-focus", focus_node=normalized,
                actual_focus_node=normalized, actual_focus_accessibility_focused=True,
                actual_focus_input_focused=normalized.get("focused"),
                actual_focus_resource_id=normalized.get("viewIdResourceName"),
                actual_focus_bounds=normalized.get("boundsInScreen"),
                actual_focus_visible=label,
                focus_view_id=normalized.get("viewIdResourceName"),
                focus_bounds=normalized.get("boundsInScreen"), visible_label=label)


def _correlated_post_focus(ledger: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    events = ledger.get("events") or []
    candidates: list[tuple[int, dict[str, Any], str]] = []
    for event in events:
        kind = event.get("eventType")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        value = None
        source = None
        if kind == "POST_ACTION_OBSERVATION":
            value = payload.get("observation")
            source = "request_correlated_post_action_observation"
        node = _payload_node(value)
        if node is None or node.get("accessibilityFocused") is not True:
            continue
        stamp = _millis(node.get("timestamp")) or _millis(event.get("timestamp")) or 0
        candidates.append((stamp, node, str(source)))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0])
    first = candidates[0][1]
    first_row = _row({}, first)
    first_id = instance_id(focus_instance(first_row) or {})
    for _, node, _source in candidates[1:]:
        candidate_id = instance_id(focus_instance(_row({}, node)) or {})
        if candidate_id != first_id:
            return None, "CONFLICTING_HELPER_FOCUS_EVENTS"
    _, node, source = candidates[-1]
    return node, source


def _attach_actual(raw: Mapping[str, Any], node: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(raw)
    if node is None:
        result["actual_focus_node"] = {}
        result["actual_focus_accessibility_focused"] = False
        result["actual_focus_input_focused"] = None
        result["actual_focus_resource_id"] = ""
        result["actual_focus_bounds"] = ""
        result["actual_focus_visible"] = ""
    else:
        normalized = _node(node)
        result["actual_focus_node"] = normalized
        result["actual_focus_accessibility_focused"] = True
        result["actual_focus_input_focused"] = normalized.get("focused")
        result["actual_focus_resource_id"] = normalized.get("viewIdResourceName") or ""
        result["actual_focus_bounds"] = normalized.get("boundsInScreen") or ""
        result["actual_focus_visible"] = (normalized.get("talkbackLabel") or normalized.get("contentDescription")
                                           or normalized.get("text") or normalized.get("mergedLabel") or "")
    return result


def normalize_phase3_focus_transition(before: Mapping[str, Any], after: Mapping[str, Any],
                                     command_ack: Any, *, expected_request_id: str | None = None,
                                     scenario_run_id: str | None = None) -> dict[str, Any]:
    """Classify one focus observation using strict actual focus and a Helper request ledger.

    The normalized before/after maps are returned for a Phase 3 transition
    observer. Their actual-focus fields are cleared whenever correlation fails.
    """
    before_node, before_reason = _current_actual(before)
    after_snapshot_node, after_reason = _current_actual(after)
    ledger = _ack_ledger(command_ack, expected_request_id)
    stale_reasons = []
    run_id = str(scenario_run_id or before.get("scenario_run_id") or "")
    if (not run_id or before.get("scenario_run_id") != run_id
            or after.get("scenario_run_id") != run_id):
        stale_reasons.append("SCENARIO_RUN_MISMATCH")
    if (not before.get("scenario_id") or before.get("scenario_id") != after.get("scenario_id")):
        stale_reasons.append("SCENARIO_MISMATCH")
    if (not before.get("capture_id") or not after.get("capture_id")
            or before.get("capture_id") == after.get("capture_id")):
        stale_reasons.append("SNAPSHOT_ID_MISSING_OR_REUSED")
    if not ledger.get("valid"):
        stale_reasons.append(str(ledger.get("reason") or "INVALID_REQUEST_LEDGER"))

    before_stamp = _millis((before.get("focus_node") or {}).get("timestamp")) if isinstance(before.get("focus_node"), Mapping) else None
    after_stamp = _millis((after.get("focus_node") or {}).get("timestamp")) if isinstance(after.get("focus_node"), Mapping) else None
    if before_stamp is None or after_stamp is None or after_stamp <= before_stamp:
        stale_reasons.append("FOCUS_SNAPSHOT_ORDER_INVALID")
    started_at = ledger.get("started_at")
    if started_at is None or before_stamp is None or before_stamp > started_at:
        stale_reasons.append("BEFORE_SNAPSHOT_NOT_BEFORE_REQUEST")
    ack_at = ledger.get("ack_at")
    if ack_at is None or after_stamp is None or after_stamp < ack_at:
        stale_reasons.append("AFTER_SNAPSHOT_NOT_AFTER_ACK")
    if before_reason == "CONTRADICTORY_ACCESSIBILITY_FOCUS_FLAGS" or after_reason == "CONTRADICTORY_ACCESSIBILITY_FOCUS_FLAGS":
        stale_reasons.append("CONTRADICTORY_ACCESSIBILITY_FOCUS_FLAGS")

    helper_node, helper_source = _correlated_post_focus(ledger) if ledger.get("valid") else (None, None)
    if helper_source == "CONFLICTING_HELPER_FOCUS_EVENTS":
        stale_reasons.append(helper_source)
    if helper_node is not None and after_snapshot_node is not None:
        helper_row = _row(after, helper_node)
        snapshot_row = _row(after, after_snapshot_node)
        helper_id = instance_id(focus_instance(helper_row) or {})
        snapshot_id = instance_id(focus_instance(snapshot_row) or {})
        if helper_id != snapshot_id:
            stale_reasons.append("HELPER_AND_FRESH_SNAPSHOT_FOCUS_CONFLICT")

    correlated_after = helper_node or after_snapshot_node
    before_row = _row(before, before_node) if before_node is not None else None
    after_row = _row(after, correlated_after) if correlated_after is not None else None
    before_id = instance_id(focus_instance(before_row) or {}) if before_row else None
    after_id = instance_id(focus_instance(after_row) or {}) if after_row else None
    if before_node is None and before_reason == "INPUT_FOCUS_ONLY":
        fallback = True
    elif correlated_after is None and after_reason == "INPUT_FOCUS_ONLY":
        fallback = True
    else:
        fallback = False

    if stale_reasons:
        status = "STALE_OR_CONTRADICTORY_EVIDENCE"
        actual_moved = None
        before_node = correlated_after = None
    elif fallback:
        status = "FALSE_FOCUS_FALLBACK"
        actual_moved = None
    elif before_id is None or after_id is None:
        status = "FOCUS_INDETERMINATE"
        actual_moved = None
    else:
        actual_moved = before_id != after_id
        if actual_moved and ledger.get("success") is False:
            status = "ACK_FAILURE_BUT_FOCUS_MOVED"
        elif actual_moved:
            status = "FOCUS_MOVE_CONFIRMED"
        elif ledger.get("success") is True:
            status = "ACK_SUCCESS_NO_FOCUS_MOVE"
        else:
            status = "ACK_FAILURE_NO_FOCUS_MOVE"

    before_projected = _attach_actual(before, before_node)
    after_projected = _attach_actual(after, correlated_after)
    return {
        "status": status,
        "actual_focus_moved": actual_moved,
        "before_instance_id": before_id if before_node is not None else None,
        "after_instance_id": after_id if correlated_after is not None else None,
        "before_focus_source": before_reason if before_node is not None else before_reason,
        "after_focus_source": helper_source or ("fresh_after_snapshot" if after_snapshot_node else after_reason),
        "ack_status": "SUCCESS" if ledger.get("success") is True else
                      "FAIL" if ledger.get("success") is False else "UNKNOWN",
        "request_correlation": {key: value for key, value in ledger.items() if key != "events"},
        "stale_reasons": sorted(set(stale_reasons)),
        "visit_credit": 0,
        "production_visit_authority": False,
        "before_actual_focus_node": before_node,
        "after_actual_focus_node": correlated_after,
        "before_observation": before_projected,
        "after_observation": after_projected,
    }
