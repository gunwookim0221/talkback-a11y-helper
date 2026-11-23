"""Exact, one-use authorization for a configured plugin entry tap.

This module does not grant traversal credit.  Its audit is append-only and
separate from the production attempt/visit ledgers.
"""
from __future__ import annotations

import re
import uuid
import json
import base64
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

_OWNER_REJECTION_DIAGNOSTIC_STRINGS = {
    "stage": 64, "code": 96, "request_id": 128, "transaction_id": 128,
    "expected_package": 128, "expected_descriptor_digest": 64,
    "expected_source_node_id_status": 32, "source_capture_request_id": 128,
    "source_process_epoch": 128, "source_service_instance_id": 128,
    "source_connection_epoch": 128, "source_boot_epoch": 128,
    "source_root_digest": 64, "source_candidate_digest": 64, "source_capture_key": 64,
    "current_service_instance_id": 128, "current_process_epoch": 128,
    "current_connection_epoch": 128, "current_boot_epoch": 128,
}
_OWNER_REJECTION_DIAGNOSTIC_INTS = {
    "expected_window_id", "source_generation", "source_capture_sequence",
    "current_generation", "current_capture_sequence",
}
_OWNER_REJECTION_CURRENTNESS_FIELDS = {
    "source_capture_current", "request_id_matches", "process_epoch_matches",
    "service_instance_matches", "generation_matches", "capture_sequence_matches",
    "capture_key_matches", "connection_epoch_matches", "boot_epoch_matches",
    "root_digest_matches", "candidate_digest_matches", "window_package_matches",
    "capture_fresh",
}


def _bounded_owner_rejection_diagnostics(value):
    """Retain only the non-text, non-authorizing owner-resolution projection."""
    if not isinstance(value, dict):
        return None
    safe = {key: str(value[key])[:limit] for key, limit in _OWNER_REJECTION_DIAGNOSTIC_STRINGS.items()
            if isinstance(value.get(key), str)}
    for key in _OWNER_REJECTION_DIAGNOSTIC_INTS:
        if type(value.get(key)) is int:
            safe[key] = value[key]
    path = value.get("expected_path")
    if isinstance(path, list) and len(path) <= 80 and all(type(item) is int and 0 <= item <= 4096 for item in path):
        safe["expected_path"] = list(path)
    actual = value.get("actual_live_node")
    if isinstance(actual, dict):
        node = {}
        for key, limit in (("package_name", 128), ("class_name", 192), ("resource_id", 256)):
            if isinstance(actual.get(key), str):
                node[key] = actual[key][:limit]
        if type(actual.get("window_id")) is int:
            node["window_id"] = actual["window_id"]
        for key in ("visible", "enabled", "clickable", "action_click"):
            if type(actual.get(key)) is bool:
                node[key] = actual[key]
        safe["actual_live_node"] = node
    currentness = value.get("currentness")
    if isinstance(currentness, dict):
        safe["currentness"] = {key: currentness[key] for key in _OWNER_REJECTION_CURRENTNESS_FIELDS
                               if type(currentness.get(key)) is bool}
    return safe or None


def _walk(roots):
    stack = [(node, ()) for node in reversed(roots) if isinstance(node, dict)]
    while stack:
        node, ancestry = stack.pop()
        yield node, ancestry
        stack.extend((child, (*ancestry, node)) for child in reversed(node.get("children") or [])
                     if isinstance(child, dict))


def _index_full_hierarchy(roots):
    """Return a validated full-tree index with ancestry from the current roots.

    Candidate identity is object-bound to this snapshot. A detached candidate,
    a repeated node object, or malformed child collection cannot supply a
    trustworthy lineage and must not be resolved by a partial subtree.
    """
    if not isinstance(roots, (list, tuple)):
        return None, "HIERARCHY_LINEAGE_UNPROVEN"
    indexed = []
    seen = set()
    stack = [(node, ()) for node in reversed(roots)]
    while stack:
        node, ancestry = stack.pop()
        if not isinstance(node, dict) or id(node) in seen:
            return None, "HIERARCHY_LINEAGE_UNPROVEN"
        seen.add(id(node))
        indexed.append((node, ancestry))
        children = node.get("children")
        if children is None:
            children = []
        if not isinstance(children, (list, tuple)):
            return None, "HIERARCHY_LINEAGE_UNPROVEN"
        if any(not isinstance(child, dict) for child in children):
            return None, "HIERARCHY_LINEAGE_UNPROVEN"
        stack.extend((child, (*ancestry, node)) for child in reversed(children))
    return indexed, None


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


def _action_semantics(node):
    """Return complete, comparable action semantics or None when incomplete."""
    role = normalize_text(node.get("role"))
    actions = node.get("actions")
    if not role or not isinstance(actions, (list, tuple)) or not actions:
        return None
    normalized_actions = []
    for action in actions:
        if isinstance(action, dict):
            action_id = action.get("id")
            action_name = normalize_text(action.get("name") or action.get("label"))
            if action_id is None and not action_name:
                return None
            normalized_actions.append((str(action_id or ""), action_name))
        elif isinstance(action, (str, int)):
            normalized_actions.append((str(action), ""))
        else:
            return None
    if not normalized_actions:
        return None
    return (
        role,
        normalize_text(_own_label(node)),
        tuple(sorted(normalized_actions)),
        node.get("clickable") is True,
        node.get("effectiveClickable") is True,
        node.get("focusable") is True,
        node.get("checkable") is True,
        node.get("enabled") is not False,
    )


def _proven_equivalent_owner_ancestor(ancestor, owner, matched_phrase, indexed):
    """Whether an actionable ancestor is evidenced as the same nav action.

    Containment alone is insufficient. Require matching explicit navigation
    semantics and a structural container class before excluding an ancestor
    from independent hit-owner competition.
    """
    class_name = str(ancestor.get("className") or "").lower()
    structural = any(token in class_name for token in ("viewgroup", "layout", "container"))
    ancestor_bounds, owner_bounds = _bounds(ancestor), _bounds(owner)
    if (not structural or not ancestor_bounds or not owner_bounds
            or not (ancestor_bounds[0] <= owner_bounds[0] and ancestor_bounds[1] <= owner_bounds[1]
                    and ancestor_bounds[2] >= owner_bounds[2] and ancestor_bounds[3] >= owner_bounds[3])):
        return False
    ancestor_semantics = _action_semantics(ancestor)
    owner_semantics = _action_semantics(owner)
    ancestor_label, owner_label = _words(_own_label(ancestor)), _words(_own_label(owner))
    if ancestor_label and ancestor_label != _words(matched_phrase):
        return False
    has_ancestor_semantics = bool(normalize_text(ancestor.get("role")) or ancestor.get("actions"))
    has_owner_semantics = bool(normalize_text(owner.get("role")) or owner.get("actions"))
    if has_ancestor_semantics or has_owner_semantics:
        return (ancestor_label == _words(matched_phrase) and ancestor_semantics is not None
                and owner_semantics is not None and ancestor_semantics == owner_semantics)
    # Legacy dumps may omit role/actions. For an equal-bounds wrapper, require
    # the same exposed click/focus state and one phrase-matched navigation target
    # in that branch. A distinct same-area control keeps the chain unresolved.
    capability = lambda node: (
        node.get("clickable") is True, node.get("effectiveClickable") is True,
        node.get("focusable") is True, node.get("checkable") is True,
        node.get("enabled") is not False,
    )
    owner_label = _words(_own_label(owner))
    phrase_words = _words(matched_phrase)
    if (ancestor_bounds != owner_bounds or capability(ancestor) != capability(owner)
            or ancestor.get("checkable") is True or owner.get("checkable") is True
            or not (owner_label == phrase_words or owner_label.startswith(phrase_words + " "))):
        return False
    if ancestor_label and ancestor_label != owner_label:
        return False
    for node, ancestors in indexed:
        if (node is owner or not any(parent is ancestor for parent in ancestors)
                or not _actionable(node) or _bounds(node) != owner_bounds):
            continue
        node_class = str(node.get("className") or "")
        node_label = _words(_own_label(node))
        if (node.get("checkable") is True
                or re.search(r"(?i)(switch|toggle|button|checkbox)", node_class)
                or (node_label and not (node_label == phrase_words or node_label.startswith(phrase_words + " ")))):
            return False
    return True


def _words(value):
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zA-Z가-힣]+", " ", str(value or "").lower())).strip()


def _contains(bounds, point):
    return bool(bounds and bounds[0] <= point[0] < bounds[2] and bounds[1] <= point[1] < bounds[3])


def _identity(node):
    return dict(resource_id=str(node.get("viewIdResourceName") or node.get("resourceId") or ""),
                class_name=str(node.get("className") or ""), bounds=str(node.get("boundsInScreen") or ""),
                source_node_id=str(node.get("sourceNodeId") or ""),
                window_id=_strict_window_id(node.get("windowId")))


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

    Candidate and owner ancestry are derived from the full current hierarchy.
    Overlapping ancestors are excluded only when explicit action semantics prove
    that they are structural wrappers for the same navigation owner.
    """
    phrase = normalize_text(matched_phrase)
    if not phrase or not isinstance(selected, dict):
        return dict(ok=False, reason="TARGET_PHRASE_OR_CANDIDATE_MISSING")
    indexed, index_error = _index_full_hierarchy(roots)
    if index_error:
        return dict(ok=False, reason=index_error)
    selected_records = [(node, ancestors) for node, ancestors in indexed if node is selected]
    if len(selected_records) != 1:
        return dict(ok=False, reason="HIERARCHY_LINEAGE_UNPROVEN")
    subtree = [(node, ancestors) for node, ancestors in indexed
               if (node is selected or any(ancestor is selected for ancestor in ancestors))
               and _bounds(node)]
    exact = [(node, ancestors) for node, ancestors in subtree if _actionable(node)
             and normalize_text(_own_label(node)) == phrase]
    if exact:
        exact.sort(key=lambda pair: len(pair[1]), reverse=True)
        owner = exact[0][0]
        owner_ancestors = exact[0][1]
        # Multiple exact-label nodes are one owner only when they form a single
        # ancestor chain and every clickable wrapper is proven equivalent.
        # Siblings or incomplete semantics stay distinct.
        for candidate, _ in exact[1:]:
            if not any(candidate is ancestor for ancestor in owner_ancestors) or not _proven_equivalent_owner_ancestor(
                    candidate, owner, phrase, indexed):
                return dict(ok=False, reason="MULTIPLE_NAMED_ACTION_OWNERS")
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
    owner_records = [(node, ancestors) for node, ancestors in indexed if node is owner]
    if len(owner_records) != 1:
        return dict(ok=False, reason="HIERARCHY_LINEAGE_UNPROVEN")
    owner_ancestors = owner_records[0][1]
    # All other actionable nodes at the proposed point remain competitors,
    # including equal-bounds descendants and unrelated overlapping siblings.
    conflicts = []
    for node, ancestors in indexed:
        if node is owner or not _actionable(node) or not _contains(_bounds(node), point):
            continue
        # _point_for_owner already checks every actionable descendant and only
        # permits equal-geometry descendants that expose no separate semantics.
        if any(ancestor is owner for ancestor in ancestors):
            continue
        if any(node is ancestor for ancestor in owner_ancestors) and _proven_equivalent_owner_ancestor(
                node, owner, phrase, indexed):
            continue
        conflicts.append(node)
    if conflicts:
        return dict(ok=False, reason="HIT_OWNER_AMBIGUOUS",
                    owner_identity=_identity(owner), point=point,
                    candidate_identity=_identity(selected),
                    candidate_lineage=[_identity(node) for node in selected_records[0][1]],
                    owner_lineage=[_identity(node) for node in owner_ancestors],
                    conflicting_owner_identities=[_identity(node) for node in conflicts])
    return dict(ok=True, reason=reason, owner=owner, owner_identity=_identity(owner),
                point=point, snapshot_digest=hierarchy_digest(roots),
                candidate_identity=_identity(selected),
                candidate_lineage=[_identity(node) for node in selected_records[0][1]],
                owner_lineage=[_identity(node) for node in owner_ancestors])


def authorize_entry(resolution, roots, *, scenario, matched_phrase, preflight=False,
                    observation_lease=None, capture_req_id="", transaction_id=None):
    """Only the exact configured, current, read-only navigation target can tap."""
    if not resolution.get("ok"):
        return dict(authorized=False, reason=resolution.get("reason") or "UNRESOLVED")
    if hierarchy_digest(roots) != resolution["snapshot_digest"]:
        return dict(authorized=False, reason="HIERARCHY_CHANGED")
    owner = resolution["owner"]
    if _identity(owner) != resolution["owner_identity"] or not _actionable(owner):
        return dict(authorized=False, reason="TARGET_CHANGED")
    if _strict_window_id(owner.get("windowId")) is None:
        return dict(authorized=False, reason="ENTRY_TARGET_WINDOW_ID_UNAVAILABLE",
                    target_identity=resolution["owner_identity"], snapshot_digest=resolution.get("snapshot_digest"))
    transaction_id = str(transaction_id or uuid.uuid4().hex)
    label = _own_label(owner) or matched_phrase
    identity = dict(resolution["owner_identity"])
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
    baseline = classify_action(candidate, action_type="CLICK", context=context, metadata={}).to_dict()
    if (baseline["safety_class"] in {"RISKY", "FORBIDDEN"}
            or configured.get("effect") != "read_only_navigation"
            or configured.get("forbidden") is True):
        return dict(authorized=False, reason="ENTRY_TARGET_RISK_OR_CONFIG_CONFLICT",
                    classification=baseline, target_identity=identity)
    classification = classify_action(candidate, action_type="CLICK", context=dict(destination=scenario),
        metadata=dict(source="CONFIGURED", effect="read_only_navigation")).to_dict()
    policy = evaluate_policy(classification, dict(current_target=True, within_app=True,
        read_only_effect=True, recovery_verified=True)).to_dict()
    policy_eligible = policy["eligible"] and classification["safety_class"] in {"SAFE", "CONDITIONALLY_SAFE"}
    if preflight:
        return dict(authorized=False, preflight_eligible=policy_eligible,
                    reason="ENTRY_TARGET_OBSERVATION_LEASE_REQUIRED" if policy_eligible else policy["reason"],
                    classification=classification, policy=policy, target_identity=identity,
                    point=resolution["point"], expected_label=_own_label(owner),
                    snapshot_digest=resolution["snapshot_digest"], transaction_id=transaction_id,
                    owner_node_path=owner.get("_helperNodePath"),
                    owner_descriptor_digest=owner.get("_helperNodeDescriptorDigest"),
                    source_snapshot_id=owner.get("_helperSourceSnapshotId"))
    stable_id_available = bool(str(owner.get("sourceNodeId") or "").strip())
    lease = observation_lease if isinstance(observation_lease, dict) else {}
    owner_path = owner.get("_helperNodePath")
    owner_digest = str(owner.get("_helperNodeDescriptorDigest") or "")
    lease_path = lease.get("ownerPath")
    lease_path_matches = isinstance(lease_path, list) and isinstance(owner_path, list) and lease_path == owner_path
    try:
        lease_deadline = int(lease.get("leaseDeadlineElapsedRealtimeMs") or 0)
    except (TypeError, ValueError):
        lease_deadline = 0
    lease_ok = (
        lease.get("ok") is True and bool(str(lease.get("ownerLeaseId") or ""))
        and str(lease.get("captureReqId") or "") == str(capture_req_id)
        and str(lease.get("requestedTransactionId") or lease.get("transactionId") or "") == transaction_id
        and str(lease.get("connectionId") or "") != ""
        and str(lease.get("runId") or "") != ""
        and str(lease.get("invocationId") or "") != ""
        and str(lease.get("captureId") or "") != ""
        and lease_deadline > 0
        and str(lease.get("helperSnapshotId") or "") != ""
        and _strict_window_id(lease.get("ownerWindowId")) == _strict_window_id(owner.get("windowId"))
        and lease_path_matches
        and str(lease.get("ownerDescriptorDigest") or "") == owner_digest
        and str(lease.get("sourceSnapshotId") or "") == str(owner.get("_helperSourceSnapshotId") or "")
    )
    if not stable_id_available and not lease_ok:
        return dict(authorized=False, reason="ENTRY_TARGET_STABLE_IDENTITY_UNAVAILABLE",
                    target_identity=identity, snapshot_digest=resolution.get("snapshot_digest"),
                    transaction_id=transaction_id, point=resolution.get("point"))
    if lease and not lease_ok:
        return dict(authorized=False, reason="ENTRY_TARGET_OBSERVATION_LEASE_MISMATCH",
                    target_identity=identity, snapshot_digest=resolution.get("snapshot_digest"),
                    transaction_id=transaction_id, point=resolution.get("point"))
    authorized = policy_eligible and (stable_id_available or lease_ok)
    return dict(authorized=authorized, reason=policy["reason"], classification=classification,
                policy=policy, target_identity=identity, point=resolution["point"],
                expected_label=_own_label(owner), snapshot_digest=resolution["snapshot_digest"],
                transaction_id=transaction_id,
                owner_lease_id=lease.get("ownerLeaseId") if lease_ok else None,
                capture_id=lease.get("captureId") if lease_ok else None,
                connection_id=lease.get("connectionId") if lease_ok else None,
                run_id=lease.get("runId") if lease_ok else None,
                invocation_id=lease.get("invocationId") if lease_ok else None,
                helper_snapshot_id=lease.get("helperSnapshotId") if lease_ok else None,
                capture_req_id=capture_req_id if lease_ok else None,
                owner_descriptor_digest=owner_digest if lease_ok else None)


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
                           dispatch_uptime_ms=None, after_event_sequence=None, owner_lease_request=None,
                           invocation_id=None):
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
        if isinstance(owner_lease_request, dict):
            owner_invocation_id = str(owner_lease_request.get("invocation_id") or "").strip()
            if invocation_id is not None:
                selected_invocation_id = str(invocation_id or "").strip()
                if (not selected_invocation_id or not owner_invocation_id
                        or selected_invocation_id != owner_invocation_id):
                    return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_INVOCATION_IDENTITY_INVALID",
                                stage="request", operation=operation, evidenceEvents=[])
                # The data URI and owner lease carry the same canonical
                # EvidenceRuntime invocation. Never make an ID for transport.
                extras.extend(["-d", f"invocation_id:{selected_invocation_id}",
                               "--ez", "canonicalInvocation", "true"])
            # ADB shell tokenization can strip JSON quotes from a --es value.
            # Carry the exact host-built request as URL-safe Base64 so the
            # Helper parses the same bytes without shell metacharacters.
            owner_request_json = json.dumps(owner_lease_request, ensure_ascii=False,
                                            sort_keys=True, separators=(",", ":"))
            owner_request_b64 = base64.urlsafe_b64encode(
                owner_request_json.encode("utf-8")).decode("ascii")
            extras.extend(["--es", "ownerLeaseRequestBase64", owner_request_b64])
        elif invocation_id is not None:
            return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_OWNER_LEASE_REQUEST_MISSING",
                        stage="request", operation=operation, evidenceEvents=[])
    if dispatch_uptime_ms is not None:
        extras.extend(["--el", "dispatchUptimeMs", str(int(dispatch_uptime_ms))])
    if after_event_sequence is not None:
        extras.extend(["--el", "afterEventSequence", str(max(0, int(after_event_sequence)))])
    if operation == "begin" and isinstance(owner_lease_request, dict):
        owner_path = owner_lease_request.get("node_path")
        owner_path_text = (".".join(str(part) for part in owner_path)
                           if isinstance(owner_path, list) else "invalid")
        print("[ENTRY_CLICK_CAPTURE][host][source_identity] "
              f"responseReqId={response_req_id} captureReqId={req_id} transactionId={transaction_id} "
              f"sourceRequestId={str(owner_lease_request.get('source_capture_request_id') or '')[:128]} "
              f"sourceProcessEpoch={str(owner_lease_request.get('source_process_epoch') or '')[:128]} "
              f"sourceGeneration={owner_lease_request.get('source_generation')} "
              f"sourceServiceInstanceId={str(owner_lease_request.get('source_service_instance_id') or '')[:128]} "
              f"sourceCaptureSequence={owner_lease_request.get('source_capture_sequence')} "
              f"sourceCaptureKey={str(owner_lease_request.get('source_capture_key') or '')[:64]} "
              f"ownerWindowId={owner_lease_request.get('window_id')} ownerPath={owner_path_text[:240]} "
              f"ownerDescriptorDigest={str(owner_lease_request.get('descriptor_digest') or '')[:64]}")
    print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} captureReqId={req_id} "
          f"transactionId={transaction_id} operation={operation} stage=request")
    try:
        broadcast_output = broadcast(dev, ENTRY_CLICK_CAPTURE_ACTION, extras)
    except Exception as exc:
        # ADB failures must remain distinguishable from a missing Helper
        # response. In either case this operation has no lease authority.
        error = str(getattr(exc, "reason", "") or type(exc).__name__)[:120]
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              f"stage=broadcast status=failed error={error}")
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_BROADCAST_FAILED", stage="broadcast",
                    responseReqId=response_req_id, operation=operation,
                    broadcastError=error,
                    evidenceEvents=[])
    broadcast_text = " ".join(str(broadcast_output or "").split())[:240]
    result_match = re.search(r"\bBroadcast completed:\s*result=(-?\d+)\b", str(broadcast_output or ""))
    result_code = int(result_match.group(1)) if result_match else None
    delivery_error = bool(re.search(
        r"(?i)(permission denial|securityexception|receiver not found|error:|broadcast failed)",
        str(broadcast_output or ""),
    ))
    broadcast_status = (
        "REJECTED" if delivery_error or result_code not in (None, 0)
        else "COMPLETED" if result_code == 0
        else "UNCLASSIFIED"
    )
    broadcast_output_summary = json.dumps(broadcast_text, ensure_ascii=True, separators=(",", ":"))
    print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
          f"stage=broadcast status={broadcast_status} resultCode={result_code if result_code is not None else 'unknown'} "
          f"stdout={broadcast_output_summary}")
    if broadcast_status == "REJECTED":
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_BROADCAST_REJECTED", stage="broadcast",
                    responseReqId=response_req_id, operation=operation,
                    broadcastDiagnostics={"status": broadcast_status, "resultCode": result_code,
                                          "output": broadcast_text}, evidenceEvents=[])
    try:
        result = read_result(dev, "ENTRY_CLICK_CAPTURE_RESULT", response_req_id,
                             wait_seconds=max(0.01, float(wait_seconds)), poll_interval_sec=0.025)
    except Exception as exc:
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              f"stage=response_read status=failed error={type(exc).__name__}")
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_RESPONSE_READ_FAILED", stage="response_read",
                    responseReqId=response_req_id, operation=operation,
                    responseReadError=type(exc).__name__, evidenceEvents=[])
    if not isinstance(result, dict):
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              f"stage=response_read status=invalid_result")
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_RESULT_INVALID", stage="response_read",
                    responseReqId=response_req_id, operation=operation, evidenceEvents=[])
    if str(result.get("reqId") or "") != response_req_id:
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              f"stage=response_read status=request_mismatch")
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_RESPONSE_REQUEST_MISMATCH", stage="response_read",
                    responseReqId=response_req_id, operation=operation, evidenceEvents=[])
    # _read_log_result represents a bounded wait miss as a failure object with
    # only success/reason/reqId. Do not misreport that transport miss as a
    # transaction or owner-lease mismatch.
    if (result.get("success") is False
            and not any(key in result for key in
                        ("operation", "requestedTransactionId", "captureReqId", "transactionId"))):
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              f"stage=response_read status=missing broadcastStatus={broadcast_status}")
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_RESULT_UNAVAILABLE",
                    responseReqId=response_req_id,
                    operation=operation, stage="response_read",
                    responseError=str(result.get("reason") or ""),
                    broadcastDiagnostics={"status": broadcast_status, "resultCode": result_code,
                                          "output": broadcast_text}, evidenceEvents=[])
    # First validate the non-authorizing correlation envelope. A Helper-side
    # rejection is a terminal negative response and intentionally has no
    # transaction/lease fields; preserve its reason without promoting it.
    requested_transaction_id = str(result.get("requestedTransactionId") or "")
    response_capture_req_id = str(result.get("captureReqId") or "")
    if requested_transaction_id != transaction_id or response_capture_req_id != req_id:
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              f"stage=response_read status=transaction_mismatch")
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_TRANSACTION_MISMATCH", stage="response_read",
                    responseReqId=response_req_id, operation=operation, evidenceEvents=[])
    if str(result.get("operation") or "") != operation:
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              f"stage=response_read status=operation_mismatch")
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_OPERATION_RESPONSE_MISMATCH", stage="response_read",
                    responseReqId=response_req_id, operation=operation, evidenceEvents=[])
    if result.get("ok") is not True:
        helper_reason = str(result.get("reason") or "UNKNOWN")[:96]
        helper_diagnostics = _bounded_owner_rejection_diagnostics(result.get("diagnostics"))
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              f"stage=helper_result status=rejected reason={helper_reason}")
        if helper_diagnostics is not None:
            print("[ENTRY_CLICK_CAPTURE][host][owner_rejection_diagnostics] " +
                  json.dumps(helper_diagnostics, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return dict(ok=False,
                    reason=f"ENTRY_CLICK_CAPTURE_HELPER_REJECTED:{helper_reason}",
                    stage="helper_result", responseReqId=response_req_id, operation=operation,
                    helperReason=str(result.get("reason") or "UNKNOWN")[:120],
                    captureReqId=req_id, requestedTransactionId=transaction_id,
                    helperDiagnostics=helper_diagnostics, evidenceEvents=[])
    if operation == "begin" and invocation_id is not None and (
            result.get("invocationUriBound") is not True
            or str(result.get("invocationId") or "") != str(invocation_id)):
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              "stage=helper_result status=invocation_binding_unproven")
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_INVOCATION_BINDING_UNPROVEN",
                    stage="helper_result", responseReqId=response_req_id, operation=operation,
                    evidenceEvents=[])
    response_transaction_id = str(result.get("transactionId") or "")
    transaction_matches = True
    if operation == "end":
        transaction_matches = (
            response_transaction_id in {"", transaction_id}
            and result.get("active") is False
        )
    else:
        transaction_matches = response_transaction_id == transaction_id
    if not transaction_matches:
        print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
              f"stage=response_read status=transaction_mismatch")
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_TRANSACTION_MISMATCH", stage="response_read",
                    responseReqId=response_req_id, operation=operation, evidenceEvents=[])
    print(f"[ENTRY_CLICK_CAPTURE][host] responseReqId={response_req_id} operation={operation} "
          f"stage=helper_result status=accepted")
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
        fields = dict(fields)
        fields["source_node_id"] = payload.get("source_node_id_status", _FIELD_ABSENT)
        events.append(dict(
            event_id=str(item.get("eventId") or ""),
            event_sequence=item.get("sequence"),
            event_time=str(payload.get("event_time_uptime_ms") or ""),
            event_time_elapsed_realtime_ms=payload.get("event_time_elapsed_realtime_ms"),
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
            capture_id=str(payload.get("capture_id") or ""),
            connection_id=str(payload.get("connection_id") or ""),
            run_id=str(payload.get("run_id") or ""),
            invocation_id=str(payload.get("invocation_id") or ""),
            owner_lease_id=str(payload.get("owner_lease_id") or ""),
            owner_relation=str(payload.get("owner_relation") or ""),
            owner_exact=payload.get("owner_exact") is True,
            owner_window_id=payload.get("owner_window_id"),
            owner_helper_snapshot_id=str(payload.get("owner_helper_snapshot_id") or ""),
            owner_descriptor_digest=str(payload.get("owner_descriptor_digest") or ""),
            dispatch_correlation_status=str(payload.get("dispatch_correlation_status") or ""),
            dispatch_uptime_ms=payload.get("dispatch_uptime_ms"),
            transaction_id=transaction_id,
            request_id=req_id,
            cursor_event_sequence=payload.get("cursor_event_sequence"),
        ))
    return events


def _helper_post_action_events(snapshot, *, req_id, transaction_id):
    events = []
    for item in snapshot.get("evidenceEvents") or []:
        if not isinstance(item, dict) or str(item.get("eventType") or "") != "ENTRY_CLICK_POST_ACTION_OBSERVED":
            continue
        correlation = item.get("correlation") if isinstance(item.get("correlation"), dict) else {}
        if str(item.get("reqId") or "") != req_id:
            continue
        if str(correlation.get("transaction_id") or "") != transaction_id:
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        events.append(dict(
            event_id=str(item.get("eventId") or ""),
            event_sequence=item.get("sequence"),
            request_id=req_id,
            transaction_id=transaction_id,
            capture_id=str(payload.get("capture_id") or ""),
            connection_id=str(payload.get("connection_id") or ""),
            source_click_event_id=str(payload.get("source_click_event_id") or ""),
            dispatch_uptime_ms=payload.get("dispatch_uptime_ms"),
            source_click_captured_elapsed_realtime_ms=payload.get("source_click_captured_elapsed_realtime_ms"),
            captured_elapsed_realtime_ms=payload.get("captured_elapsed_realtime_ms"),
            current_capture_id=str(payload.get("current_capture_id") or ""),
            root_window_id=payload.get("root_window_id"),
            focus_node_id=payload.get("focus_node_id"),
                focus_node_path=payload.get("focus_node_path"),
            focus_window_id=payload.get("focus_window_id"),
            accessibility_focused=payload.get("accessibility_focused"),
            current_hierarchy=payload.get("current_hierarchy"),
            current_hierarchy_status=str(payload.get("current_hierarchy_status") or _FIELD_ABSENT),
                run_id=str(payload.get("run_id") or ""),
                invocation_id=str(payload.get("invocation_id") or ""),
                owner_lease_id=str(payload.get("owner_lease_id") or ""),
                owner_window_id=payload.get("owner_window_id"),
                owner_helper_snapshot_id=str(payload.get("owner_helper_snapshot_id") or ""),
                owner_descriptor_digest=str(payload.get("owner_descriptor_digest") or ""),
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
        # Keep the uptime sample and tap in one remote-shell command argument;
        # nested sh -c arguments are split by the ADB shell transport.
        output = run(["shell", command], dev=dev, timeout=10.0)
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
                  capture_id=str(armed.get("captureId") or ""),
                  connection_id=str(armed.get("connectionId") or ""),
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
    helper_post_action_by_id = {}
    try:
        event_sequence_cursor = int(capture_session.get("helper_cursor_event_sequence") or 0)
    except (TypeError, ValueError):
        event_sequence_cursor = 0
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
                after_event_sequence=event_sequence_cursor,
            )
            if snapshot.get("ok") is not True:
                poll_error = str(snapshot.get("reason") or "SNAPSHOT_FAILED")
            for event in _helper_click_events(snapshot, req_id=req_id, transaction_id=transaction_id):
                if event.get("dispatch_uptime_ms") is None:
                    event["dispatch_uptime_ms"] = permit.get("dispatch_uptime_ms")
                if event.get("event_id"):
                    helper_events_by_id[event["event_id"]] = event
            for event in _helper_post_action_events(snapshot, req_id=req_id, transaction_id=transaction_id):
                if event.get("event_id"):
                    helper_post_action_by_id[event["event_id"]] = event
            for item in snapshot.get("evidenceEvents") or []:
                if isinstance(item, dict):
                    try:
                        event_sequence_cursor = max(event_sequence_cursor, int(item.get("sequence")))
                    except (TypeError, ValueError):
                        pass
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
                after_event_sequence=event_sequence_cursor,
            )
            for event in _helper_click_events(ended, req_id=req_id, transaction_id=transaction_id):
                if event.get("event_id"):
                    helper_events_by_id[event["event_id"]] = event
            for event in _helper_post_action_events(ended, req_id=req_id, transaction_id=transaction_id):
                if event.get("event_id"):
                    helper_post_action_by_id[event["event_id"]] = event
            # One final logcat read closes the same fixed window. Events after
            # the elapsed-realtime deadline are rejected by the shared clock check.
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
        if dispatch_uptime_ms is None or deadline_uptime_ms is None:
            event["correlation_status"] = "DISPATCH_CURSOR_UNAVAILABLE"
            in_window.append(event)
            continue
        try:
            # Helper captured_elapsed_realtime_ms shares /proc/uptime's clock.
            # event_time is uptimeMillis and can lag after device deep sleep.
            event_ms = int(event.get("event_ingestion_elapsed_realtime_ms"))
        except (TypeError, ValueError):
            event["correlation_status"] = "EVENT_CLOCK_DOMAIN_UNAVAILABLE"
            stale.append(event)
            continue
        if event_ms <= int(dispatch_uptime_ms):
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
                  post_action_observations=list(helper_post_action_by_id.values()),
                  candidate_click_event_count=len(in_window),
                  competing_event_count=max(0, len(in_window) - 1),
                  competing_click_event_count=max(0, len(in_window) - 1),
                  helper_event_count=len(helper_events_by_id),
                  talkback_event_count=len(talkback_after),
                  helper_capture_closed=ended.get("ok") is True)
    return result


def begin_transaction_click_capture(client, dev, *, transaction_id, target_node=None, scenario_id="",
                                   include_talkback_baseline=True, result_wait_seconds=0.25,
                                   require_canonical_invocation=False):
    """Arm a bounded Helper observation lease for the exact current target node."""
    req_id = f"entry_click_{uuid.uuid4().hex}"
    cursor_started = time.monotonic_ns()
    path = target_node.get("_helperNodePath") if isinstance(target_node, dict) else None
    digest = str(target_node.get("_helperNodeDescriptorDigest") or "") if isinstance(target_node, dict) else ""
    source_snapshot_id = str(target_node.get("_helperSourceSnapshotId") or "") if isinstance(target_node, dict) else ""
    window_id = _strict_window_id(target_node.get("windowId")) if isinstance(target_node, dict) else None
    package = str(target_node.get("packageName") or "").strip() if isinstance(target_node, dict) else ""
    owner_lease_request = None
    canonical_identity = None
    source_capture_authority = None
    if require_canonical_invocation:
        from tb_runner.plugin_entry_provenance import evidence_invocation_identity
        from talkback_lib.reliable_hierarchy_schema import validate_capture_authority

        canonical_identity = evidence_invocation_identity(client, scenario_id)
        if not canonical_identity.get("evidence_run_id") or not canonical_identity.get("invocation_id"):
            return dict(req_id=req_id, transaction_id=transaction_id,
                        armed=dict(ok=False, reason="CANONICAL_INVOCATION_IDENTITY_UNAVAILABLE",
                                   reqId=req_id, requestedTransactionId=transaction_id),
                        capture_id="", connection_id="", cursor_started_monotonic_ns=cursor_started,
                        talkback_baseline={}, helper_cursor_event_sequence=None)
        authority = validate_capture_authority(
            target_node.get("_helperCaptureAuthority") if isinstance(target_node, dict) else None)
        if (authority is None or authority.capture_key != source_snapshot_id
                or authority.request_id != str(target_node.get("_helperCaptureRequestId") or "")
                or authority.hierarchy_window_id != window_id
                or authority.hierarchy_package_name != package):
            return dict(req_id=req_id, transaction_id=transaction_id,
                        armed=dict(ok=False, reason="SOURCE_CAPTURE_AUTHORITY_UNAVAILABLE",
                                   reqId=req_id, requestedTransactionId=transaction_id),
                        capture_id="", connection_id="", cursor_started_monotonic_ns=cursor_started,
                        talkback_baseline={}, helper_cursor_event_sequence=None)
        source_capture_authority = authority
    if isinstance(path, list) and digest and source_snapshot_id and window_id is not None and package:
        owner_lease_request = dict(
            request_id=req_id,
            transaction_id=transaction_id,
            run_id=(canonical_identity["evidence_run_id"] if canonical_identity is not None else
                    str(getattr(client, "active_run_id", "") or getattr(client, "run_id", "") or scenario_id)),
            invocation_id=(canonical_identity["invocation_id"] if canonical_identity is not None else
                           f"{scenario_id}:{req_id}"),
            scenario_id=str(scenario_id or ""),
            source_snapshot_id=source_snapshot_id,
            window_id=window_id,
            package=package,
            node_path=path,
            descriptor_digest=digest,
        )
        if source_capture_authority is not None:
            source_connection_epoch = str(target_node.get("_helperConnectionEpoch") or "").strip()
            source_boot_epoch = str(target_node.get("_helperBootEpoch") or "").strip()
            owner_source_node_id = str(target_node.get("_helperOwnerSourceNodeId") or
                                       target_node.get("sourceNodeId") or "").strip()
            owner_source_node_id_status = str(target_node.get("_helperOwnerSourceNodeIdStatus") or "")
            source_node_status_valid = (
                (owner_source_node_id_status == "FIELD_PRESENT" and bool(owner_source_node_id)) or
                (owner_source_node_id_status == "FIELD_ABSENT" and not owner_source_node_id
                 and "sourceNodeId" in target_node)
            )
            if (require_canonical_invocation and
                    (not source_connection_epoch or source_connection_epoch.upper() == "UNKNOWN"
                     or not source_boot_epoch or source_boot_epoch.upper() == "UNKNOWN"
                     or not source_node_status_valid)):
                return dict(req_id=req_id, transaction_id=transaction_id,
                            armed=dict(ok=False, reason="NAVIGATION_SOURCE_LIFECYCLE_OR_OWNER_IDENTITY_MISSING",
                                       reqId=req_id, requestedTransactionId=transaction_id),
                            capture_id="", connection_id="", cursor_started_monotonic_ns=cursor_started,
                            talkback_baseline={}, helper_cursor_event_sequence=None)
            owner_lease_request.update(
                source_capture_request_id=source_capture_authority.request_id,
                source_process_epoch=source_capture_authority.process_epoch,
                source_generation=source_capture_authority.generation,
                source_service_instance_id=source_capture_authority.service_instance_id,
                source_capture_sequence=source_capture_authority.capture_sequence,
                source_root_digest=source_capture_authority.root_digest,
                source_candidate_digest=source_capture_authority.candidate_digest,
                source_capture_key=source_capture_authority.capture_key,
                source_connection_epoch=source_connection_epoch,
                source_boot_epoch=source_boot_epoch,
                owner_source_node_id=owner_source_node_id,
                owner_source_node_id_status=owner_source_node_id_status,
            )
    if require_canonical_invocation and owner_lease_request is None:
        return dict(req_id=req_id, transaction_id=transaction_id,
                    armed=dict(ok=False, reason="NAVIGATION_OWNER_IDENTITY_INVALID",
                               reqId=req_id, requestedTransactionId=transaction_id),
                    capture_id="", connection_id="", cursor_started_monotonic_ns=cursor_started,
                    talkback_baseline={}, helper_cursor_event_sequence=None)
    armed = _entry_capture_request(client, dev, req_id=req_id, transaction_id=transaction_id,
                                   operation="begin", wait_seconds=result_wait_seconds,
                                   owner_lease_request=owner_lease_request,
                                   invocation_id=(canonical_identity["invocation_id"]
                                                  if canonical_identity is not None else None))
    baseline = (capture_click_events(client, dev)
                if include_talkback_baseline and armed.get("ok") is True else {})
    return dict(req_id=req_id, transaction_id=transaction_id, armed=armed,
                capture_id=str(armed.get("captureId") or ""),
                connection_id=str(armed.get("connectionId") or ""),
                cursor_started_monotonic_ns=cursor_started,
                talkback_baseline=baseline,
                helper_cursor_event_sequence=armed.get("cursorEventSequence"))


def mark_transaction_click_dispatch(client, dev, *, capture_session, transaction_id, dispatch_uptime_ms):
    req_id = str(capture_session.get("req_id") or "")
    return _entry_capture_request(client, dev, req_id=req_id, transaction_id=transaction_id,
                                  operation="mark_dispatch", wait_seconds=0.15,
                                  dispatch_uptime_ms=dispatch_uptime_ms)


def validate_transaction_click_capture(client, dev, *, capture_session, transaction_id, result_wait_seconds=0.15):
    req_id = str(capture_session.get("req_id") or "")
    armed = capture_session.get("armed") if isinstance(capture_session.get("armed"), dict) else {}
    result = _entry_capture_request(client, dev, req_id=req_id, transaction_id=transaction_id,
                                    operation="validate", wait_seconds=result_wait_seconds)
    owner_path = result.get("ownerPath")
    try:
        expected_deadline = int(armed.get("leaseDeadlineElapsedRealtimeMs") or 0)
        actual_deadline = int(result.get("leaseDeadlineElapsedRealtimeMs") or 0)
    except (TypeError, ValueError):
        expected_deadline = actual_deadline = 0
    exact = (
        result.get("ok") is True and result.get("reason") == "TARGET_CURRENT"
        and result.get("scenarioId") == armed.get("scenarioId")
        and result.get("captureId") == armed.get("captureId")
        and result.get("connectionId") == armed.get("connectionId")
        and result.get("runId") == armed.get("runId")
        and result.get("invocationId") == armed.get("invocationId")
        and result.get("ownerLeaseId") == armed.get("ownerLeaseId")
        and result.get("ownerWindowId") == armed.get("ownerWindowId")
        and isinstance(owner_path, list) and owner_path == armed.get("ownerPath")
        and result.get("ownerDescriptorDigest") == armed.get("ownerDescriptorDigest")
        and result.get("sourceSnapshotId") == armed.get("sourceSnapshotId")
        and result.get("helperSnapshotId") == armed.get("helperSnapshotId")
        and expected_deadline > 0 and actual_deadline == expected_deadline
    )
    return dict(ok=exact, reason="TARGET_CURRENT" if exact else
                result.get("reason") or "ENTRY_CLICK_CAPTURE_VALIDATION_MISMATCH", result=result)


def end_transaction_click_capture(client, dev, *, capture_session, transaction_id, after_event_sequence=None):
    req_id = str(capture_session.get("req_id") or "")
    if not req_id:
        return dict(ok=False, reason="ENTRY_CLICK_CAPTURE_REQUEST_ID_MISSING", evidenceEvents=[])
    return _entry_capture_request(client, dev, req_id=req_id, transaction_id=transaction_id,
                                  operation="end", wait_seconds=0.15,
                                  after_event_sequence=after_event_sequence)


def map_click_source_to_target(event, permit, roots):
    """Require either the bound Helper object lease or an exact stable source ID."""
    target = permit.get("target_identity") if isinstance(permit.get("target_identity"), dict) else {}
    source = event.get("source") if isinstance(event.get("source"), dict) else None
    source = source or event
    field_status = event.get("field_status") if isinstance(event.get("field_status"), dict) else {}
    source_field_status = source.get("field_status") if isinstance(source.get("field_status"), dict) else {}
    source_field_status = {**field_status, **source_field_status}
    if source_field_status.get("source_node_id") == _FIELD_PARSE_FAILED or \
            source_field_status.get("window_id") == _FIELD_PARSE_FAILED:
        return dict(status="INSUFFICIENT", reason="SOURCE_FIELD_PARSE_FAILED",
                    candidates=[])
    expected_lease_id = str(permit.get("owner_lease_id") or "")
    if expected_lease_id:
        lease_exact = (
            event.get("owner_exact") is True
            and event.get("owner_relation") == "EXACT_RETAINED_NODE_REFERENCE"
            and str(event.get("owner_lease_id") or "") == expected_lease_id
            and str(event.get("request_id") or "") == str(permit.get("capture_req_id") or "")
            and str(event.get("transaction_id") or "") == str(permit.get("transaction_id") or "")
            and str(event.get("capture_id") or "") == str(permit.get("capture_id") or "")
            and str(event.get("connection_id") or "") == str(permit.get("connection_id") or "")
            and str(event.get("run_id") or "") == str(permit.get("run_id") or "")
            and str(event.get("invocation_id") or "") == str(permit.get("invocation_id") or "")
            and str(event.get("owner_helper_snapshot_id") or "") == str(permit.get("helper_snapshot_id") or "")
            and str(event.get("owner_descriptor_digest") or "") == str(permit.get("owner_descriptor_digest") or "")
            and _strict_window_id(event.get("owner_window_id")) == _strict_window_id(target.get("window_id"))
        )
        if not lease_exact:
            return dict(status="AMBIGUOUS", reason="RETAINED_NODE_OWNER_LEASE_MISMATCH", candidates=[])
        return dict(status="EXACT", reason="EXACT_RETAINED_HELPER_NODE_REFERENCE",
                    mapped_identity=dict(owner_lease_id=expected_lease_id,
                                         window_id=_strict_window_id(target.get("window_id")),
                                         helper_snapshot_id=permit.get("helper_snapshot_id")))
    source_id = str(source.get("source_node_id") or event.get("source_node_id") or "").strip()
    target_id = str(target.get("source_node_id") or "").strip()
    source_window = _strict_window_id(source.get("window_id", event.get("window_id")))
    target_window = _strict_window_id(target.get("window_id"))
    if not source_id or not target_id or source_window is None or target_window is None:
        return dict(status="INSUFFICIENT", reason="STABLE_SOURCE_IDENTITY_UNAVAILABLE", candidates=[])
    if source_id != target_id or source_window != target_window:
        return dict(status="AMBIGUOUS", reason="SOURCE_MAP_IS_NOT_AUTHORIZED_OWNER",
                    candidates=[], mapped_identity=dict(source_node_id=source_id, window_id=source_window))
    matches = [node for node, _ in _walk(roots or [])
               if str(node.get("sourceNodeId") or "").strip() == source_id
               and _strict_window_id(node.get("windowId")) == source_window]
    identities = [dict(source_node_id=str(node.get("sourceNodeId") or ""),
                       window_id=_strict_window_id(node.get("windowId"))) for node in matches]
    if len(matches) != 1:
        return dict(status="AMBIGUOUS" if matches else "INSUFFICIENT",
                    reason="SOURCE_STABLE_ID_NOT_UNIQUE_IN_AUTHORIZED_SNAPSHOT",
                    candidates=identities)
    return dict(status="EXACT", reason="EXACT_STABLE_SOURCE_ID_AND_WINDOW_MATCH",
                candidates=identities, mapped_identity=identities[0])


def _strict_window_id(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _required_anchor_matches(node, patterns):
    if not isinstance(patterns, dict):
        return False
    text_blob = " ".join(str(node.get(key) or "") for key in
                          ("text", "contentDescription", "talkbackLabel"))
    resource_id = str(node.get("viewIdResourceName") or node.get("resourceId") or "")
    checks = ((patterns.get("anchor_text"), text_blob),
              (patterns.get("anchor_resource"), resource_id))
    if not any(str(pattern or "").strip() for pattern, _ in checks):
        return False
    for pattern, value in checks:
        if not str(pattern or "").strip():
            continue
        try:
            if re.search(str(pattern), value, re.I):
                return True
        except re.error:
            return False
    return False


def _verify_post_action_focus_anchor(event, collection, *, dispatch_uptime_ms,
                                     required_anchor_patterns):
    observations = collection.get("post_action_observations") if isinstance(collection, dict) else None
    observations = [row for row in observations or [] if isinstance(row, dict)]
    if len(observations) != 1:
        return dict(ok=False, reason="POST_ACTION_FOCUS_OBSERVATION_MISSING_OR_AMBIGUOUS",
                    observation_count=len(observations))
    observation = observations[0]
    expected_req = str(event.get("request_id") or "")
    expected_tx = str(event.get("transaction_id") or "")
    expected_capture = str(event.get("capture_id") or "")
    expected_connection = str(event.get("connection_id") or "")
    click_event_id = str(event.get("event_id") or "")
    expected_lease = str(event.get("owner_lease_id") or "")
    if not all((expected_req, expected_tx, expected_capture, expected_connection, click_event_id)):
        return dict(ok=False, reason="CLICK_CAPTURE_IDENTITY_INCOMPLETE")
    if (observation.get("request_id") != expected_req
            or observation.get("transaction_id") != expected_tx
            or observation.get("capture_id") != expected_capture
            or observation.get("connection_id") != expected_connection
            or observation.get("source_click_event_id") != click_event_id
            or str(collection.get("req_id") or "") != expected_req
            or str(collection.get("transaction_id") or "") != expected_tx
            or str(collection.get("capture_id") or "") != expected_capture
            or str(collection.get("connection_id") or "") != expected_connection):
        return dict(ok=False, reason="POST_ACTION_CAPTURE_IDENTITY_MISMATCH")
    if expected_lease and (
        observation.get("owner_lease_id") != expected_lease
        or observation.get("run_id") != event.get("run_id")
        or observation.get("invocation_id") != event.get("invocation_id")
        or observation.get("owner_helper_snapshot_id") != event.get("owner_helper_snapshot_id")
        or observation.get("owner_descriptor_digest") != event.get("owner_descriptor_digest")
    ):
        return dict(ok=False, reason="POST_ACTION_OWNER_LEASE_MISMATCH")
    try:
        dispatch = int(dispatch_uptime_ms)
        click_dispatch = int(event.get("dispatch_uptime_ms"))
        post_dispatch = int(observation.get("dispatch_uptime_ms"))
        post_time = int(observation.get("captured_elapsed_realtime_ms"))
        click_time = int(event.get("event_ingestion_elapsed_realtime_ms"))
        observation_click_time = int(observation.get("source_click_captured_elapsed_realtime_ms"))
        deadline = int(collection.get("deadline_uptime_ms"))
    except (TypeError, ValueError):
        return dict(ok=False, reason="POST_ACTION_CLOCK_EVIDENCE_MISSING")
    if click_dispatch != dispatch or post_dispatch != dispatch:
        return dict(ok=False, reason="POST_ACTION_DISPATCH_RECEIPT_MISMATCH")
    if observation_click_time != click_time:
        return dict(ok=False, reason="POST_ACTION_CLICK_EVENT_TIME_MISMATCH")
    if not (dispatch < click_time < post_time <= deadline):
        return dict(ok=False, reason="POST_ACTION_OBSERVATION_STALE_OR_OUTSIDE_WINDOW")
    if not str(observation.get("current_capture_id") or ""):
        return dict(ok=False, reason="CURRENT_HIERARCHY_CAPTURE_ID_MISSING")
    if observation.get("accessibility_focused") is not True:
        return dict(ok=False, reason="CURRENT_ACCESSIBILITY_FOCUS_NOT_PROVEN")
    roots = observation.get("current_hierarchy")
    if isinstance(roots, dict):
        roots = [roots]
    if not isinstance(roots, list) or not roots:
        return dict(ok=False, reason="CURRENT_HIERARCHY_MISSING")
    root_window = _strict_window_id(observation.get("root_window_id"))
    focus_window = _strict_window_id(observation.get("focus_window_id"))
    focus_id = str(observation.get("focus_node_id") or "").strip()
    focus_path = observation.get("focus_node_path")
    if root_window is None or focus_window != root_window:
        return dict(ok=False, reason="CURRENT_FOCUS_WINDOW_MISMATCH")
    root_nodes = list(_walk(roots))
    root_window_ids = {_strict_window_id(root.get("windowId")) for root in roots if isinstance(root, dict)}
    if root_window_ids != {root_window}:
        return dict(ok=False, reason="CURRENT_HIERARCHY_WINDOW_MISMATCH")
    if focus_id:
        focused = [node for node, _ in root_nodes
                   if str(node.get("sourceNodeId") or "").strip() == focus_id
                   and _strict_window_id(node.get("windowId")) == focus_window]
        if len(focused) != 1:
            return dict(ok=False, reason="CURRENT_FOCUSED_NODE_NOT_UNIQUE_IN_HIERARCHY",
                        focused_node_count=len(focused))
        focus_node = focused[0]
    elif isinstance(focus_path, list) and all(isinstance(index, int) and not isinstance(index, bool) and index >= 0
                                               for index in focus_path):
        focus_node = roots[0]
        try:
            for index in focus_path:
                focus_node = (focus_node.get("children") or [])[index]
        except (IndexError, TypeError):
            return dict(ok=False, reason="CURRENT_FOCUS_PATH_INVALID")
        if _strict_window_id(focus_node.get("windowId")) != focus_window:
            return dict(ok=False, reason="CURRENT_FOCUS_PATH_WINDOW_MISMATCH")
    else:
        return dict(ok=False, reason="CURRENT_FOCUS_ID_AND_PATH_MISSING")
    if focus_node.get("accessibilityFocused") is not True:
        return dict(ok=False, reason="CURRENT_FOCUSED_NODE_NOT_MARKED_ACCESSIBILITY_FOCUSED")
    focused_nodes = [node for node, _ in root_nodes if node.get("accessibilityFocused") is True]
    if len(focused_nodes) != 1 or focused_nodes[0] is not focus_node:
        return dict(ok=False, reason="CURRENT_ACCESSIBILITY_FOCUS_AMBIGUOUS",
                    accessibility_focused_node_count=len(focused_nodes))
    anchors = [node for node, _ in root_nodes if _required_anchor_matches(node, required_anchor_patterns)]
    if len(anchors) != 1 or anchors[0] is not focus_node:
        return dict(ok=False, reason="CURRENT_REQUIRED_ANCHOR_MISSING_OR_AMBIGUOUS",
                    anchor_node_count=len(anchors))
    if not _required_anchor_matches(focus_node, required_anchor_patterns):
        return dict(ok=False, reason="CURRENT_FOCUS_DOES_NOT_MATCH_REQUIRED_ANCHOR")
    return dict(ok=True, reason="CURRENT_FOCUS_AND_REQUIRED_ANCHOR_MATCHED",
                current_capture_id=observation.get("current_capture_id"),
                focused_identity=dict(source_node_id=focus_id, window_id=focus_window))


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
                      roots=None, dispatch_uptime_ms=None, collection=None,
                      required_anchor_patterns=None):
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
    if str(event.get("transaction_id") or "") != str(permit.get("transaction_id") or ""):
        return dict(matched=False, reason="CLICK_TRANSACTION_MISMATCH", actual_hit=event,
                    evidence_strength="INSUFFICIENT", candidate_count=1, competing_event_count=0)
    if permit.get("owner_lease_id"):
        try:
            event_time_elapsed = int(event.get("event_time_elapsed_realtime_ms"))
            dispatch_elapsed = int(dispatch_uptime_ms)
            deadline_elapsed = int((collection or {}).get("deadline_uptime_ms"))
        except (TypeError, ValueError):
            return dict(matched=False, reason="CLICK_EVENT_CLOCK_EVIDENCE_MISSING", actual_hit=event,
                        evidence_strength="INSUFFICIENT", candidate_count=1, competing_event_count=0)
        if not (dispatch_elapsed < event_time_elapsed <= deadline_elapsed):
            return dict(matched=False, reason="CLICK_EVENT_OUTSIDE_DISPATCH_WINDOW", actual_hit=event,
                        evidence_strength="INSUFFICIENT", candidate_count=1, competing_event_count=0)
    source_mapping = map_click_source_to_target(event, permit, roots) if roots is not None else dict(status="INSUFFICIENT", reason="HIERARCHY_UNAVAILABLE")
    if source_mapping.get("status") != "EXACT":
        return dict(matched=False, reason="ACTIVATED_SOURCE_AMBIGUOUS"
                    if source_mapping.get("status") == "AMBIGUOUS" else "ACTIVATED_SOURCE_IDENTITY_UNPROVEN",
                    actual_hit=event, source_mapping=source_mapping,
                    evidence_strength=source_mapping.get("status", "INSUFFICIENT"),
                    authorized_target=permit["target_identity"], candidate_count=1,
                    competing_event_count=0)
    post_focus = _verify_post_action_focus_anchor(
        event, collection or {}, dispatch_uptime_ms=dispatch_uptime_ms,
        required_anchor_patterns=required_anchor_patterns,
    )
    if not post_focus.get("ok"):
        return dict(matched=False, reason=post_focus.get("reason"), actual_hit=event,
                    source_mapping=source_mapping, post_action_focus=post_focus,
                    evidence_strength="INSUFFICIENT", authorized_target=permit["target_identity"],
                    candidate_count=1, competing_event_count=0)
    return dict(matched=True, reason="EXACT_OWNER_AND_CURRENT_FOCUS_ANCHOR",
                actual_hit=event, source_mapping=source_mapping,
                post_action_focus=post_focus, evidence_strength="EXACT",
                authorized_target=permit["target_identity"], candidate_count=1,
                competing_event_count=0)


def _event_in_uptime_window(event, dispatch_uptime_ms, deadline_uptime_ms):
    try:
        # /proc/uptime supplies elapsed realtime; event_time is uptimeMillis.
        # Use Helper ingestion time, which shares the dispatch clock and survives deep sleep offsets.
        event_ms = int(event.get("event_ingestion_elapsed_realtime_ms"))
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
