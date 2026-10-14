"""Exact, one-use authorization for a configured plugin entry tap.

This module does not grant traversal credit.  Its audit is append-only and
separate from the production attempt/visit ledgers.
"""
from __future__ import annotations

import re
import uuid
import json
import os
import time
from pathlib import Path
from typing import Any

from tb_runner.action_safety import classify_action, configured_metadata, default_config, normalize_text
from tb_runner.canonical_json import canonical_sha256
from tb_runner.safe_action_policy import evaluate_policy
from tb_runner.utils import parse_bounds_str

# The preserved failure delivered its click after 243 ms. One second gives
# roughly four times that observed lag; device eventTime still imposes the hard
# dispatch+window cutoff, so later unrelated clicks cannot be accepted.
ENTRY_CLICK_WINDOW_MS = 1000
ENTRY_CLICK_POLL_INTERVAL_MS = 100
ENTRY_CLICK_CAPTURE_ACTION = "com.iotpart.sqe.talkbackhelper.ENTRY_CLICK_CAPTURE"
_FIELD_ABSENT = "FIELD_ABSENT"
_FIELD_PARSE_FAILED = "FIELD_PARSE_FAILED"


def _walk(roots):
    stack = [(node, ()) for node in reversed(roots) if isinstance(node, dict)]
    while stack:
        node, ancestry = stack.pop()
        yield node, ancestry
        stack.extend((child, (*ancestry, node)) for child in reversed(node.get("children") or [])
                     if isinstance(child, dict))


def _bounds(node):
    return parse_bounds_str(str(node.get("boundsInScreen") or node.get("bounds") or ""))


def _actionable(node):
    actions = node.get("actions") or []
    click_action = any((action.get("id") if isinstance(action, dict) else action) == 16
                       for action in actions) if isinstance(actions, (list, tuple)) else False
    return (node.get("clickable") is True or node.get("effectiveClickable") is True
            or click_action) and node.get("enabled") is not False


def _own_label(node):
    return " ".join(str(node.get(key) or "").strip() for key in
                    ("text", "contentDescription", "talkbackLabel") if str(node.get(key) or "").strip())


def _words(value):
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zA-Z가-힣]+", " ", str(value or "").lower())).strip()


def _contains(bounds, point):
    return bool(bounds and bounds[0] <= point[0] < bounds[2] and bounds[1] <= point[1] < bounds[3])


def _identity(node):
    return dict(resource_id=str(node.get("viewIdResourceName") or node.get("resourceId") or ""),
                class_name=str(node.get("className") or ""), bounds=str(node.get("boundsInScreen") or ""))


def hierarchy_digest(roots):
    """Focus and mutable status are excluded; target geometry and topology are not."""
    return canonical_sha256([([_identity(parent) for parent in ancestors], _identity(node),
                              _own_label(node), node.get("clickable"), node.get("focusable"),
                              node.get("checkable"), node.get("enabled"), node.get("role"),
                              node.get("actions")) for node, ancestors in _walk(roots)])


def _point_for_owner(owner, roots):
    bounds = _bounds(owner)
    if not bounds:
        return None
    x1, y1, x2, y2 = bounds
    points = [((x1 + x2) // 2, (y1 + y2) // 2)]
    for x_ratio, y_ratio in ((.25, .2), (.5, .2), (.75, .2), (.25, .5), (.75, .5),
                             (.25, .8), (.5, .8), (.75, .8)):
        points.append((int(x1 + (x2-x1)*x_ratio), int(y1 + (y2-y1)*y_ratio)))
    descendants = [(node, ancestors) for node, ancestors in _walk(roots)
                   if any(ancestor is owner for ancestor in ancestors)]
    # Equal-geometry wrappers are equivalent only when they have no separate
    # activation semantics. A full-size switch/button is an independent owner.
    if any(_actionable(node) and _bounds(node) == bounds
           and (node.get("checkable") is True
                or re.search(r"(?i)(switch|toggle|button|checkbox)", str(node.get("className") or ""))
                or (_own_label(node) and normalize_text(_own_label(node)) != normalize_text(_own_label(owner))))
           for node, _ in descendants):
        return None
    for point in points:
        if any(_actionable(node) and _contains(_bounds(node), point)
               and _bounds(node) != bounds for node, _ in descendants):
            continue
        return point
    return None


def resolve_navigation_owner(roots, selected, matched_phrase):
    """Prefer a unique actionable own-label target; otherwise an exposed card area.

    Every proposed point is checked against independent actionable descendants.
    Overlapping wrappers of identical geometry remain one logical hit area.
    """
    phrase = normalize_text(matched_phrase)
    if not phrase or not isinstance(selected, dict):
        return dict(ok=False, reason="TARGET_PHRASE_OR_CANDIDATE_MISSING")
    subtree = [(node, ancestors) for node, ancestors in _walk([selected]) if _bounds(node)]
    exact = [(node, ancestors) for node, ancestors in subtree if _actionable(node)
             and normalize_text(_own_label(node)) == phrase]
    # Distinct own-label actions are ambiguous; nested equal-bounds wrappers
    # are resolved to the deepest observed node.
    exact_bounds = {_bounds(node) for node, _ in exact}
    if len(exact_bounds) > 1:
        return dict(ok=False, reason="MULTIPLE_NAMED_ACTION_OWNERS")
    if exact:
        exact.sort(key=lambda pair: len(pair[1]), reverse=True)
        owner = exact[0][0]
        reason = "UNIQUE_NAMED_ACTION_OWNER"
    elif _actionable(selected):
        same_geometry_named = [(node, chain) for node, chain in subtree
            if node is not selected and _actionable(node) and _bounds(node) == _bounds(selected)
            and (_words(_own_label(node)) == _words(phrase)
                 or _words(_own_label(node)).startswith(_words(phrase) + " "))]
        if len({_identity(node)["resource_id"] for node, _ in same_geometry_named}) > 1:
            return dict(ok=False, reason="MULTIPLE_EQUAL_GEOMETRY_ACTION_OWNERS")
        same_geometry_named.sort(key=lambda pair: len(pair[1]), reverse=True)
        owner = same_geometry_named[0][0] if same_geometry_named else selected
        reason = "NAMED_EQUAL_GEOMETRY_OWNER" if same_geometry_named else "EXPOSED_ACTIONABLE_CARD_AREA"
    else:
        return dict(ok=False, reason="NAVIGATION_OWNER_UNPROVEN")
    point = _point_for_owner(owner, roots)
    if point is None:
        return dict(ok=False, reason="NO_UNOCCUPIED_OWNER_HIT_AREA")
    owner_bounds = _bounds(owner)
    # A click at this point must not be owned by another independent control.
    owner_ancestors = {id(ancestor) for node, chain in subtree if node is owner for ancestor in chain}
    conflicts = [(node, ancestors) for node, ancestors in _walk(roots)
                 if node is not owner and id(node) not in owner_ancestors
                 and _actionable(node) and _contains(_bounds(node), point)
                 and _bounds(node) != owner_bounds]
    if conflicts:
        return dict(ok=False, reason="HIT_OWNER_AMBIGUOUS")
    return dict(ok=True, reason=reason, owner=owner, owner_identity=_identity(owner),
                point=point, snapshot_digest=hierarchy_digest(roots),
                candidate_identity=_identity(selected))


def authorize_entry(resolution, roots, *, scenario, matched_phrase):
    """Only the exact configured, current, read-only navigation target can tap."""
    if not resolution.get("ok"):
        return dict(authorized=False, reason=resolution.get("reason") or "UNRESOLVED")
    if hierarchy_digest(roots) != resolution["snapshot_digest"]:
        return dict(authorized=False, reason="HIERARCHY_CHANGED")
    owner = resolution["owner"]
    if _identity(owner) != resolution["owner_identity"] or not _actionable(owner):
        return dict(authorized=False, reason="TARGET_CHANGED")
    label = _own_label(owner) or matched_phrase
    identity = resolution["owner_identity"]
    candidate = dict(action_kind="CLICK", candidate_id=canonical_sha256(identity),
        target_identity={**identity, "instance_id": canonical_sha256(identity)},
        target_semantics=dict(role=str(owner.get("role") or ""), normalized_label=normalize_text(label),
            text=str(owner.get("text") or ""), contentDescription=str(owner.get("contentDescription") or ""),
            flags=dict(clickable=owner.get("clickable") is True or owner.get("effectiveClickable") is True,
                       focusable=owner.get("focusable") is True,
                       enabled=True, checkable=owner.get("checkable") is True),
            actions=owner.get("actions") or []),
        evidence=dict(current_presence=True), eligibility=dict(availability="AVAILABLE"))
    context = dict(destination=scenario, context_kind="plugin_entry")
    configured = configured_metadata(candidate, context, default_config())
    baseline = classify_action(candidate, action_type="CLICK", context=context,
                               metadata=configured).to_dict()
    if baseline["safety_class"] in {"RISKY", "FORBIDDEN"} or configured.get("effect") not in {None, "", "read_only_navigation"}:
        return dict(authorized=False, reason="ENTRY_TARGET_RISK_OR_CONFIG_CONFLICT",
                    classification=baseline, target_identity=identity)
    classification = classify_action(candidate, action_type="CLICK", context=dict(destination=scenario),
        metadata=dict(source="CONFIGURED", effect="read_only_navigation")).to_dict()
    policy = evaluate_policy(classification, dict(current_target=True, within_app=True,
        read_only_effect=True, recovery_verified=True)).to_dict()
    authorized = policy["eligible"] and classification["safety_class"] in {"SAFE", "CONDITIONALLY_SAFE"}
    return dict(authorized=authorized, reason=policy["reason"], classification=classification,
                policy=policy, target_identity=identity, point=resolution["point"],
                expected_label=_own_label(owner), snapshot_digest=resolution["snapshot_digest"],
                transaction_id=uuid.uuid4().hex)


_CLICK = re.compile(r"EventType: TYPE_VIEW_CLICKED; EventTime: (\d+); PackageName: ([^;]+);.*?"
                    r"\[ ClassName: ([^;]+); Text: (.*?)"
                    r"(?:; ContentDescription: ([^;]*))?(?:; ItemCount:|; Enabled:|; Password:| \])")
_BOUNDS = re.compile(r"time:(\d+).*?sourceBoundsInScreen=Rect\(\s*(-?\d+),\s*(-?\d+)\s*-\s*(-?\d+),\s*(-?\d+)\s*\)")
_LOG_PID = re.compile(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+\s+\d+\s+(\d+)\s+[VDIWEF]\s+talkback:")


def _optional_log_field(line, patterns, *, cast=str, presence_patterns=()):
    for pattern in patterns:
        match = re.search(pattern, line, re.I)
        if match:
            value = match.group(1).strip().strip('"')
            if not value or value.lower() in {"null", "none"}:
                return None, _FIELD_ABSENT
            try:
                return cast(value), "FIELD_PRESENT"
            except (TypeError, ValueError):
                return None, _FIELD_PARSE_FAILED
    if any(re.search(pattern, line, re.I) for pattern in presence_patterns):
        return None, _FIELD_PARSE_FAILED
    return None, _FIELD_ABSENT


def click_events(logcat):
    bounds = {}
    bounds_status = {}
    for source_line in str(logcat or "").splitlines():
        if "sourceBoundsInScreen" not in source_line:
            continue
        time_match = re.search(r"time:(\d+)", source_line)
        if not time_match:
            continue
        event_key = time_match.group(1)
        bounds_match = _BOUNDS.search(source_line)
        if not bounds_match:
            bounds_status[event_key] = _FIELD_PARSE_FAILED
            continue
        _, x1, y1, x2, y2 = bounds_match.groups()
        bounds[event_key] = tuple(map(int, (x1, y1, x2, y2)))
        bounds_status[event_key] = "FIELD_PRESENT"
    parsed = {}
    for line in str(logcat or "").splitlines():
        match = _CLICK.search(line)
        if not match:
            continue
        event_time, package, klass, text, description = match.groups()
        description = description or ""
        event_id = str(event_time)
        pid_match = _LOG_PID.search(line)
        rect = bounds.get(event_id)
        source_node_id, source_node_status = _optional_log_field(
            line, (r"eventSourceNode\s*=\s*([^,;\s]+)", r"sourceNodeId\s*[:=]\s*([^,;\s]+)"),
            presence_patterns=(r"eventSourceNode\s*=", r"sourceNodeId\s*[:=]"),
        )
        resource_id, resource_status = _optional_log_field(
            line, (r"viewIdResName\s*[:=]\s*([^,;\s]+)", r"resourceId\s*[:=]\s*([^,;\s]+)"),
            presence_patterns=(r"viewIdResName\s*[:=]", r"resourceId\s*[:=]"),
        )
        window_id, window_status = _optional_log_field(
            line, (r"windowId\s*[:=]\s*(-?\d+)",), cast=int,
            presence_patterns=(r"windowId\s*[:=]",),
        )
        enabled, enabled_status = _optional_log_field(
            line, (r";\s*Enabled\s*:\s*(true|false)", r"\benabled\s*[:=]\s*(true|false)"),
            cast=lambda value: value.lower() == "true",
            presence_patterns=(r";\s*Enabled\s*:", r"\benabled\s*[:=]"),
        )
        clickable, clickable_status = _optional_log_field(
            line, (r"\bclickable\s*[:=]\s*(true|false)",),
            cast=lambda value: value.lower() == "true",
            presence_patterns=(r"\bclickable\s*[:=]",),
        )
        focusable, focusable_status = _optional_log_field(
            line, (r"\bfocusable\s*[:=]\s*(true|false)",),
            cast=lambda value: value.lower() == "true",
            presence_patterns=(r"\bfocusable\s*[:=]",),
        )
        row = dict(
            event_id=event_id,
            event_time=event_id,
            event_type="TYPE_VIEW_CLICKED",
            package=package.strip(),
            class_name=klass.strip(),
            text=text.strip(),
            content_description=description.strip(),
            bounds=rect,
            source_node_id=source_node_id,
            resource_id=resource_id,
            window_id=window_id,
            enabled=enabled,
            clickable=clickable,
            focusable=focusable,
            source_status=("FIELD_PRESENT" if source_node_id is not None else
                           "FIELD_PARSE_FAILED" if source_node_status == _FIELD_PARSE_FAILED else _FIELD_ABSENT),
            field_status=dict(
                bounds="FIELD_PRESENT" if rect is not None else
                       bounds_status.get(event_id, _FIELD_ABSENT),
                source_node_id=source_node_status,
                resource_id=resource_status,
                window_id=window_status,
                enabled=enabled_status,
                clickable=clickable_status,
                focusable=focusable_status,
            ),
            logger_pid=int(pid_match.group(1)) if pid_match else None,
            process_pid=None,
            log_output_timestamp=(re.match(r"^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)", line).group(1)
                                 if re.match(r"^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)", line) else None),
            parser_source="talkback_logcat",
            raw_line=line,
            raw_reference=f"talkback:EventTime:{event_id}",
        )
        if event_id in parsed and parsed[event_id].get("raw_line") != line:
            duplicate_id = f"{event_id}#{sum(key.startswith(event_id + '#') for key in parsed) + 1}"
            row["event_id"] = duplicate_id
            row["raw_reference"] = f"talkback:EventTime:{event_id}:duplicate:{duplicate_id.rsplit('#', 1)[-1]}"
            parsed[duplicate_id] = row
        else:
            parsed[event_id] = row
    return parsed


def capture_click_events(client, dev):
    run = getattr(client, "_run", None)
    if not callable(run):
        return {}
    try:
        return click_events(run(["logcat", "-d", "-t", "1500", "-s", "talkback:V"], dev=dev, timeout=2.0))
    except Exception:
        return {}


def _entry_capture_request(client, dev, *, req_id, transaction_id, operation, wait_seconds=0.15,
                           dispatch_uptime_ms=None):
    broadcast = getattr(client, "_broadcast", None)
    read_result = getattr(client, "_read_log_result", None)
    if not callable(broadcast) or not callable(read_result):
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_TRANSPORT_UNAVAILABLE", evidenceEvents=[])
    # Each RPC gets a fresh transport request id. Reusing the capture owner id
    # would allow _read_log_result to return an earlier BEGIN/SNAPSHOT response.
    response_req_id = f"{req_id}_{operation}_{uuid.uuid4().hex[:12]}"
    extras = ["--es", "reqId", response_req_id, "--es", "captureReqId", req_id,
              "--es", "transactionId", transaction_id,
              "--es", "evidenceTransactionId", transaction_id, "--es", "operation", operation]
    if operation == "begin":
        extras.extend(["--el", "leaseMs", "2500"])
    if dispatch_uptime_ms is not None:
        extras.extend(["--el", "dispatchUptimeMs", str(int(dispatch_uptime_ms))])
    try:
        broadcast(dev, ENTRY_CLICK_CAPTURE_ACTION, extras)
        result = read_result(dev, "ENTRY_CLICK_CAPTURE_RESULT", response_req_id,
                             wait_seconds=max(0.01, float(wait_seconds)), poll_interval_sec=0.025)
    except Exception as exc:
        return dict(ok=False, reason=f"ENTRY_CLICK_CAPTURE_TRANSPORT_ERROR:{type(exc).__name__}", evidenceEvents=[])
    if not isinstance(result, dict):
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_RESULT_INVALID", evidenceEvents=[])
    if str(result.get("transactionId") or "") != transaction_id:
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_TRANSACTION_MISMATCH", evidenceEvents=[])
    if str(result.get("operation") or "") != operation:
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_OPERATION_RESPONSE_MISMATCH", evidenceEvents=[])
    result["responseReqId"] = response_req_id
    result.setdefault("evidenceEvents", [])
    return result


def _helper_click_events(snapshot, *, req_id, transaction_id):
    events = []
    for item in snapshot.get("evidenceEvents") or []:
        if not isinstance(item, dict) or str(item.get("eventType") or "") != "ENTRY_CLICK_OBSERVED":
            continue
        correlation = item.get("correlation") if isinstance(item.get("correlation"), dict) else {}
        if str(item.get("reqId") or "") != req_id:
            continue
        if str(correlation.get("transaction_id") or "") != transaction_id:
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        source = payload.get("source") if isinstance(payload.get("source"), dict) else None
        bounds_obj = (source or {}).get("bounds") if source else None
        if isinstance(bounds_obj, dict):
            bounds = tuple(int(bounds_obj.get(key, 0)) for key in ("left", "top", "right", "bottom"))
        else:
            bounds = None
        source_status = str(payload.get("source_status") or _FIELD_ABSENT)
        fields = payload.get("field_status") if isinstance(payload.get("field_status"), dict) else {}
        if not fields and isinstance(source, dict):
            fields = {key: source.get(f"{key}_status", _FIELD_ABSENT) for key in
                      ("resource_id", "class_name", "text", "content_description", "bounds", "window_id")}
        events.append(dict(
            event_id=str(item.get("eventId") or ""),
            event_time=str(payload.get("event_time_uptime_ms") or ""),
            event_type=str(payload.get("event_type") or "TYPE_VIEW_CLICKED"),
            package=str(payload.get("package") or ""),
            class_name=str((source or {}).get("class_name") or payload.get("class_name") or ""),
            text=str((source or {}).get("text") or payload.get("text") or ""),
            content_description=str((source or {}).get("content_description") or payload.get("content_description") or ""),
            bounds=bounds,
            source_node_id=payload.get("source_node_id"),
            resource_id=(source or {}).get("resource_id"),
            window_id=(source or {}).get("window_id", payload.get("window_id")),
            enabled=(source or {}).get("enabled", payload.get("enabled")),
            clickable=(source or {}).get("clickable"),
            focusable=(source or {}).get("focusable"),
            source_status=source_status,
            field_status=dict(fields),
            process_pid=payload.get("source_process_id"),
            logger_pid=None,
            parser_source=str(payload.get("parser_source") or "helper_accessibility_event"),
            raw_line=None,
            raw_reference=str(payload.get("raw_reference") or item.get("eventId") or ""),
            event_ingestion_time_ms=item.get("timestamp"),
            event_ingestion_elapsed_realtime_ms=payload.get("captured_elapsed_realtime_ms"),
            transaction_id=transaction_id,
            request_id=req_id,
            cursor_event_sequence=payload.get("cursor_event_sequence"),
        ))
    return events


def _merge_click_channels(helper_events, talkback_events):
    def key(event):
        return (str(event.get("event_time") or ""), str(event.get("package") or ""),
                str(event.get("class_name") or ""), normalize_text(event.get("text") or ""),
                normalize_text(event.get("content_description") or ""))

    # Preserve every Helper event. Two clicks can share millisecond event time
    # and labels; collapsing same-channel rows would hide a real competitor.
    helper_rows = [dict(event) for event in helper_events]
    talkback_rows = [dict(event) for event in talkback_events.values()]
    helper_by_key = {}
    for index, event in enumerate(helper_rows):
        helper_by_key.setdefault(key(event), []).append(index)
    paired_helper = set()
    retained_talkback = []
    for event in talkback_rows:
        matches = helper_by_key.get(key(event), [])
        available = [index for index in matches if index not in paired_helper]
        if len(available) == 1 and len(matches) == 1:
            index = available[0]
            helper = helper_rows[index]
            helper["parser_sources"] = ["talkback_logcat", "helper_accessibility_event"]
            helper["talkback_raw_line"] = event.get("raw_line")
            if helper.get("bounds") is None and event.get("bounds") is not None:
                helper["bounds"] = event["bounds"]
            paired_helper.add(index)
        else:
            # Pairing is uncertain (including multiple same-key Helper rows),
            # so keep the record as a competing observation.
            retained_talkback.append(event)
    return [*helper_rows, *retained_talkback]


def _uptime_from_shell_output(output):
    match = re.search(r"(?m)^\s*(\d+(?:\.\d+)?)\s+\d+(?:\.\d+)?\s*$", str(output or ""))
    return int(float(match.group(1)) * 1000) if match else None


def dispatch_authorized_entry_tap(client, dev, point):
    """Record device uptime and issue one tap in the same remote shell process."""
    run = getattr(client, "_run", None)
    if not callable(run):
        return dict(executed=False, dispatch_uptime_ms=None, reason="ADB_RUN_UNAVAILABLE")
    x, y = (int(point[0]), int(point[1]))
    command = f"cat /proc/uptime; input tap {x} {y}"
    started_ns = time.monotonic_ns()
    try:
        output = run(["shell", "sh", "-c", command], dev=dev, timeout=10.0)
    except Exception as exc:
        return dict(executed=False, dispatch_uptime_ms=None, reason=f"ADB_TAP_ERROR:{type(exc).__name__}",
                    dispatch_started_monotonic_ns=started_ns, command=command)
    ended_ns = time.monotonic_ns()
    uptime_ms = _uptime_from_shell_output(output)
    return dict(executed=True, command_completed=True, dispatch_uptime_ms=uptime_ms,
                dispatch_cursor_available=uptime_ms is not None,
                reason="DISPATCHED_WITH_DEVICE_UPTIME_CURSOR" if uptime_ms is not None else "DEVICE_UPTIME_CURSOR_MISSING",
                dispatch_started_monotonic_ns=started_ns, dispatch_completed_monotonic_ns=ended_ns,
                command=command, stdout=str(output or ""))


def collect_transaction_click_events(client, dev, *, transaction_id, hierarchy_roots, permit,
                                     before_talkback_events=None, window_ms=ENTRY_CLICK_WINDOW_MS,
                                     poll_interval_ms=ENTRY_CLICK_POLL_INTERVAL_MS, capture_session=None,
                                     dispatch_started_monotonic_ns=None,
                                     dispatch_completed_monotonic_ns=None):
    """Collect Helper source events and TalkBack click records until one fixed deadline."""
    window_ms = int(max(100, min(window_ms, 2000)))
    poll_interval_ms = int(max(20, min(poll_interval_ms, 250)))
    capture_session = capture_session or begin_transaction_click_capture(
        client, dev, transaction_id=transaction_id,
    )
    req_id = str(capture_session.get("req_id") or "")
    armed = capture_session.get("armed") if isinstance(capture_session.get("armed"), dict) else {}
    result = dict(req_id=req_id, transaction_id=transaction_id, armed=armed,
                  collection_window_ms=window_ms,
                  cursor_started_monotonic_ns=capture_session.get("cursor_started_monotonic_ns", time.monotonic_ns()),
                  candidate_events=[], competing_event_count=0, polls=[],
                  talkback_baseline_count=len(before_talkback_events or {}))
    if not req_id or armed.get("ok") is not True:
        result.update(ok=False, reason=armed.get("reason") or "ENTRY_CLICK_CAPTURE_ARM_FAILED")
        return result

    dispatch_started_monotonic_ns = dispatch_started_monotonic_ns or time.monotonic_ns()
    host_window_anchor_ns = dispatch_completed_monotonic_ns or dispatch_started_monotonic_ns
    deadline = (host_window_anchor_ns / 1_000_000_000) + (window_ms / 1000.0)
    helper_events_by_id = {}
    talkback_after = {}
    talkback_collection_cursor = dict(
        request_id=req_id,
        transaction_id=transaction_id,
        pre_dispatch_cursor_monotonic_ns=result["cursor_started_monotonic_ns"],
        collection_window_start_monotonic_ns=dispatch_started_monotonic_ns,
    )
    poll_error = ""
    authoritative_hard_stop = False
    try:
        while True:
            hard_stop = getattr(client, "_phase5c_hard_stop_state", None)
            if hard_stop is not None:
                try:
                    hard_stop.guard("entry_click_collection")
                except Exception as exc:
                    authoritative_hard_stop = True
                    poll_error = f"AUTHORITATIVE_HARD_STOP:{type(exc).__name__}"
                    break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            poll_start = time.monotonic_ns()
            snapshot = _entry_capture_request(
                client, dev, req_id=req_id, transaction_id=transaction_id,
                operation="snapshot", wait_seconds=min(0.12, max(0.025, remaining)),
            )
            if snapshot.get("ok") is not True:
                poll_error = str(snapshot.get("reason") or "SNAPSHOT_FAILED")
            for event in _helper_click_events(snapshot, req_id=req_id, transaction_id=transaction_id):
                if event.get("event_id"):
                    helper_events_by_id[event["event_id"]] = event
            try:
                current = capture_click_events(client, dev)
                baseline = before_talkback_events or {}
                for event_id, event in current.items():
                    if event_id not in baseline:
                        event.setdefault("transaction_id", transaction_id)
                        event.setdefault("request_id", req_id)
                        event.setdefault("cursor_provenance", dict(talkback_collection_cursor))
                        talkback_after[event_id] = event
            except Exception as exc:
                poll_error = poll_error or f"TALKBACK_POLL_ERROR:{type(exc).__name__}"
            result["polls"].append(dict(
                started_monotonic_ns=poll_start,
                completed_monotonic_ns=time.monotonic_ns(),
                helper_event_count=len(helper_events_by_id),
                talkback_event_count=len(talkback_after),
                helper_snapshot_ok=snapshot.get("ok") is True,
            ))
            if time.monotonic() >= deadline:
                break
            time.sleep(min(poll_interval_ms / 1000.0, max(0.0, deadline - time.monotonic())))
    finally:
        if authoritative_hard_stop:
            # The Helper's short lease disarms itself; do not issue further
            # broadcasts or device reads after the authoritative hard stop.
            ended = dict(ok=False, reason="AUTHORITATIVE_HARD_STOP", evidenceEvents=[])
        else:
            ended = end_transaction_click_capture(
                client, dev, capture_session=capture_session, transaction_id=transaction_id,
            )
            for event in _helper_click_events(ended, req_id=req_id, transaction_id=transaction_id):
                if event.get("event_id"):
                    helper_events_by_id[event["event_id"]] = event
            # One final logcat read closes the same fixed window. Events after
            # the deadline are filtered by device uptime during verification.
            try:
                final_talkback = capture_click_events(client, dev)
                for event_id, event in final_talkback.items():
                    if event_id not in (before_talkback_events or {}):
                        event.setdefault("transaction_id", transaction_id)
                        event.setdefault("request_id", req_id)
                        event.setdefault("cursor_provenance", dict(talkback_collection_cursor))
                        talkback_after[event_id] = event
            except Exception as exc:
                poll_error = poll_error or f"FINAL_TALKBACK_POLL_ERROR:{type(exc).__name__}"

    combined = _merge_click_channels(list(helper_events_by_id.values()), talkback_after)
    dispatch_uptime_ms = permit.get("dispatch_uptime_ms")
    deadline_uptime_ms = (int(dispatch_uptime_ms) + window_ms) if dispatch_uptime_ms is not None else None
    in_window = []
    stale = []
    for event in combined:
        try:
            event_ms = int(event.get("event_time"))
        except (TypeError, ValueError):
            event["correlation_status"] = "EVENT_TIME_UNAVAILABLE"
            in_window.append(event)
            continue
        if dispatch_uptime_ms is None or deadline_uptime_ms is None:
            event["correlation_status"] = "DISPATCH_CURSOR_UNAVAILABLE"
            in_window.append(event)
        elif event_ms <= int(dispatch_uptime_ms):
            event["correlation_status"] = "PRE_DISPATCH_EVENT"
            stale.append(event)
        elif event_ms > deadline_uptime_ms:
            event["correlation_status"] = "OUTSIDE_TRANSACTION_WINDOW"
            stale.append(event)
        else:
            event["correlation_status"] = "IN_TRANSACTION_WINDOW"
            in_window.append(event)
    result.update(ok=not poll_error and ended.get("ok") is True,
                  reason=poll_error or ("COLLECTION_COMPLETE" if ended.get("ok") is True else ended.get("reason")),
                  collection_window_start_monotonic_ns=dispatch_started_monotonic_ns,
                  post_dispatch_collection_anchor_monotonic_ns=host_window_anchor_ns,
                  collection_deadline_monotonic_ns=int(deadline * 1_000_000_000),
                  collection_end_monotonic_ns=time.monotonic_ns(),
                  dispatch_uptime_ms=dispatch_uptime_ms, deadline_uptime_ms=deadline_uptime_ms,
                  candidate_events=in_window, stale_events=stale,
                  candidate_click_event_count=len(in_window),
                  competing_event_count=max(0, len(in_window) - 1),
                  competing_click_event_count=max(0, len(in_window) - 1),
                  helper_event_count=len(helper_events_by_id),
                  talkback_event_count=len(talkback_after),
                  helper_capture_closed=ended.get("ok") is True)
    return result


def begin_transaction_click_capture(client, dev, *, transaction_id):
    """Arm Helper click collection and establish a pre-dispatch TalkBack cursor."""
    req_id = f"entry_click_{uuid.uuid4().hex}"
    cursor_started = time.monotonic_ns()
    armed = _entry_capture_request(client, dev, req_id=req_id, transaction_id=transaction_id,
                                   operation="begin", wait_seconds=0.25)
    baseline = capture_click_events(client, dev) if armed.get("ok") is True else {}
    return dict(req_id=req_id, transaction_id=transaction_id, armed=armed,
                cursor_started_monotonic_ns=cursor_started,
                talkback_baseline=baseline,
                helper_cursor_event_sequence=armed.get("cursorEventSequence"))


def mark_transaction_click_dispatch(client, dev, *, capture_session, transaction_id, dispatch_uptime_ms):
    req_id = str(capture_session.get("req_id") or "")
    return _entry_capture_request(client, dev, req_id=req_id, transaction_id=transaction_id,
                                  operation="mark_dispatch", wait_seconds=0.15,
                                  dispatch_uptime_ms=dispatch_uptime_ms)


def end_transaction_click_capture(client, dev, *, capture_session, transaction_id):
    req_id = str(capture_session.get("req_id") or "")
    if not req_id:
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_REQUEST_ID_MISSING", evidenceEvents=[])
    return _entry_capture_request(client, dev, req_id=req_id, transaction_id=transaction_id,
                                  operation="end", wait_seconds=0.15)


def map_click_source_to_target(event, permit, roots):
    """Map an event source to exactly one hierarchy node, then require owner identity."""
    target = permit.get("target_identity") if isinstance(permit.get("target_identity"), dict) else {}
    source = event.get("source") if isinstance(event.get("source"), dict) else None
    source = source or event
    source_status = str(event.get("source_status") or _FIELD_ABSENT)
    field_status = event.get("field_status") if isinstance(event.get("field_status"), dict) else {}
    source_field_status = source.get("field_status") if isinstance(source.get("field_status"), dict) else {}
    source_field_status = {**field_status, **source_field_status}
    parse_failed_fields = [key for key in
                           ("source_node_id", "resource_id", "class_name", "text",
                            "content_description", "bounds", "window_id")
                           if source_field_status.get(key) == _FIELD_PARSE_FAILED]
    if source_status == _FIELD_PARSE_FAILED or parse_failed_fields:
        return dict(status="INSUFFICIENT", reason="SOURCE_FIELD_PARSE_FAILED",
                    parse_failed_fields=parse_failed_fields, candidates=[])
    rid = str(source.get("resource_id") or "").strip()
    class_name = str(source.get("class_name") or event.get("class_name") or "").strip()
    event_labels = {
        normalize_text(str(source.get("text") or event.get("text") or "").strip("[] ")),
        normalize_text(str(source.get("content_description") or event.get("content_description") or "").strip()),
    }
    event_labels.discard("")
    bounds = source.get("bounds", event.get("bounds"))
    if isinstance(bounds, dict):
        bounds = tuple(int(bounds.get(key, 0)) for key in ("left", "top", "right", "bottom"))
    elif bounds is not None:
        bounds = tuple(bounds)
    candidates = []
    for node, _ in _walk(roots or []):
        node_rid = str(node.get("viewIdResourceName") or node.get("resourceId") or "").strip()
        node_class = str(node.get("className") or "").strip()
        node_bounds = _bounds(node)
        node_label = _own_label(node)
        if rid:
            if node_rid != rid or (class_name and node_class != class_name):
                continue
            if bounds is not None and node_bounds != tuple(bounds):
                continue
            candidates.append(node)
        elif bounds is not None:
            if node_bounds != tuple(bounds) or (class_name and node_class != class_name):
                continue
            node_labels = {normalize_text(str(node.get(key) or "")) for key in
                           ("text", "contentDescription", "talkbackLabel")}
            node_labels.discard("")
            if event_labels and not event_labels.intersection(node_labels):
                continue
            candidates.append(node)
        elif class_name and event_labels:
            node_labels = {normalize_text(str(node.get(key) or "")) for key in
                           ("text", "contentDescription", "talkbackLabel")}
            node_labels.discard("")
            if node_class == class_name and event_labels.intersection(node_labels):
                candidates.append(node)
    identities = [_identity(node) for node in candidates]
    if len(candidates) != 1:
        return dict(status="AMBIGUOUS" if candidates else "INSUFFICIENT",
                    reason="SOURCE_MAP_NOT_UNIQUE", candidates=identities)
    mapped = identities[0]
    if mapped != target:
        return dict(status="AMBIGUOUS", reason="SOURCE_MAP_IS_NOT_AUTHORIZED_OWNER",
                    candidates=identities, mapped_identity=mapped)
    return dict(status="STRONG_UNIQUE" if bounds is None else "EXACT",
                reason="UNIQUE_SOURCE_NODE_MATCH", candidates=identities,
                mapped_identity=mapped)


def append_entry_audit(row):
    """Phase 5C harness journal; never rewrites a prior event."""
    root = os.environ.get("TB_PHASE4C_SMOKE_OUT", "")
    if not root:
        return
    path = Path(root) / "phase5c_entry_actions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def verify_actual_hit(permit, before_events, after_events, *, package="com.samsung.android.oneconnect",
                      roots=None, dispatch_uptime_ms=None, collection=None):
    if not permit.get("authorized"):
        return dict(matched=False, reason="NO_ENTRY_PERMIT")
    if isinstance(after_events, list):
        new = [row for row in after_events if isinstance(row, dict)]
    else:
        new = [row for event, row in after_events.items() if event not in before_events]
    if dispatch_uptime_ms is not None:
        new = [row for row in new if _event_in_uptime_window(row, dispatch_uptime_ms,
                                                              (collection or {}).get("deadline_uptime_ms"))]
    if len(new) != 1:
        return dict(matched=False, reason="CLICK_EVENT_MISSING_OR_AMBIGUOUS", events=new,
                    evidence_strength="AMBIGUOUS" if len(new) > 1 else "INSUFFICIENT",
                    candidate_count=len(new), competing_event_count=max(0, len(new) - 1))
    event = new[0]
    if str(event.get("package") or "") != package:
        return dict(matched=False, reason="CLICK_EVENT_PACKAGE_MISMATCH", actual_hit=event,
                    evidence_strength="INSUFFICIENT", candidate_count=1, competing_event_count=0)
    expected = _bounds({"boundsInScreen": permit["target_identity"]["bounds"]})
    observed_label = normalize_text(str(event.get("text", "")).strip("[]").replace(",", " "))
    observed_label = observed_label or normalize_text(event.get("content_description", ""))
    expected_label = normalize_text(permit.get("expected_label", ""))
    semantic_match = bool(not observed_label or not expected_label or expected_label in observed_label)
    source_mapping = map_click_source_to_target(event, permit, roots) if roots is not None else dict(status="INSUFFICIENT", reason="HIERARCHY_UNAVAILABLE")
    if event.get("bounds") is not None and tuple(event["bounds"]) == expected and semantic_match:
        if source_mapping.get("status") == "AMBIGUOUS":
            return dict(matched=False, reason="ACTIVATED_SOURCE_AMBIGUOUS", actual_hit=event,
                        source_mapping=source_mapping, evidence_strength="AMBIGUOUS",
                        authorized_target=permit["target_identity"])
        return dict(matched=True, reason="EXACT_ACTIVATED_BOUNDS", actual_hit=event,
                    source_mapping=source_mapping, evidence_strength="EXACT",
                    authorized_target=permit["target_identity"], candidate_count=1,
                    competing_event_count=0)
    if source_mapping.get("status") == "STRONG_UNIQUE" and semantic_match:
        return dict(matched=True, reason="STRONG_UNIQUE_SOURCE_MAPPING", actual_hit=event,
                    source_mapping=source_mapping, evidence_strength="STRONG_UNIQUE",
                    authorized_target=permit["target_identity"], candidate_count=1,
                    competing_event_count=0,
                    activity_transition_secondary=bool((collection or {}).get("activity_transition")))
    return dict(matched=False, reason="ACTIVATED_TARGET_MISMATCH" if source_mapping.get("status") != "AMBIGUOUS"
                else "ACTIVATED_SOURCE_AMBIGUOUS", actual_hit=event,
                source_mapping=source_mapping, evidence_strength=source_mapping.get("status", "INSUFFICIENT"),
                authorized_target=permit["target_identity"], candidate_count=1,
                competing_event_count=0)


def _event_in_uptime_window(event, dispatch_uptime_ms, deadline_uptime_ms):
    try:
        event_ms = int(event.get("event_time"))
        return event_ms > int(dispatch_uptime_ms) and (
            deadline_uptime_ms is None or event_ms <= int(deadline_uptime_ms)
        )
    except (TypeError, ValueError):
        return False


def classify_post_open(roots, *, source_digest, activity_changed=False, target_title_present=False):
    """A source-list token alone never constitutes a plugin body."""
    nodes = list(_walk(roots))
    resources = [str(node.get("viewIdResourceName") or "").lower() for node, _ in nodes]
    has_bottom_nav = any("bottom_navigation" in rid for rid in resources)
    has_service_cards = any("servicecard" in rid.lower() for rid in resources)
    changed = bool(roots) and hierarchy_digest(roots) != source_digest
    if has_bottom_nav and has_service_cards:
        return dict(state="SOURCE_LIST_CONTEXT", destination_identity=False, root_plugin_body=False)
    if not changed and not activity_changed:
        return dict(state="SOURCE_LIST_CONTEXT" if target_title_present else "AMBIGUOUS",
                    destination_identity=False, root_plugin_body=False)
    has_back = any("navigate up" in _own_label(node).lower() or "navigate_up" in rid
                   for (node, _), rid in zip(nodes, resources))
    has_body_resource = any(rid and not rid.startswith("com.samsung.android.oneconnect:id/")
                            and rid not in {"android:id/content", "android:id/navigationbarbackground"}
                            for rid in resources)
    if (activity_changed or not has_bottom_nav) and (has_back or has_body_resource) and target_title_present:
        return dict(state="PLUGIN_BODY", destination_identity=True, root_plugin_body=True)
    return dict(state="INTERMEDIATE_STATE", destination_identity=False, root_plugin_body=False)
