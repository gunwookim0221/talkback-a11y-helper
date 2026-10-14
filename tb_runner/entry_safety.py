"""Exact, one-use authorization for a configured plugin entry tap.

This module does not grant traversal credit.  Its audit is append-only and
separate from the production attempt/visit ledgers.
"""
from __future__ import annotations

import re
import uuid
import json
import os
from pathlib import Path
from typing import Any

from tb_runner.action_safety import classify_action, configured_metadata, default_config, normalize_text
from tb_runner.canonical_json import canonical_sha256
from tb_runner.safe_action_policy import evaluate_policy
from tb_runner.utils import parse_bounds_str


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


_CLICK = re.compile(r"TYPE_VIEW_CLICKED; EventTime: (\d+); PackageName: ([^;]+);.*?"
                    r"\[ ClassName: ([^;]+); Text: (\[[^]]*\])")
_BOUNDS = re.compile(r"time:(\d+).*?sourceBoundsInScreen=Rect\((\d+), (\d+) - (\d+), (\d+)\)")


def click_events(logcat):
    bounds = {event: tuple(map(int, (x1, y1, x2, y2))) for event, x1, y1, x2, y2 in _BOUNDS.findall(logcat)}
    return {event: dict(event_time=event, package=package, class_name=klass,
                        text=text, bounds=bounds.get(event))
            for event, package, klass, text in _CLICK.findall(logcat)}


def capture_click_events(client, dev):
    run = getattr(client, "_run", None)
    if not callable(run):
        return {}
    try:
        return click_events(run(["logcat", "-d", "-t", "1500", "-s", "talkback:V"], dev=dev))
    except Exception:
        return {}


def append_entry_audit(row):
    """Phase 5C harness journal; never rewrites a prior event."""
    root = os.environ.get("TB_PHASE4C_SMOKE_OUT", "")
    if not root:
        return
    path = Path(root) / "phase5c_entry_actions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def verify_actual_hit(permit, before_events, after_events, *, package="com.samsung.android.oneconnect"):
    if not permit.get("authorized"):
        return dict(matched=False, reason="NO_ENTRY_PERMIT")
    new = [row for event, row in after_events.items() if event not in before_events
           and row.get("package") == package]
    if len(new) != 1:
        return dict(matched=False, reason="CLICK_EVENT_MISSING_OR_AMBIGUOUS", events=new)
    event = new[0]
    expected = _bounds({"boundsInScreen": permit["target_identity"]["bounds"]})
    observed_label = normalize_text(event.get("text", "").strip("[]").replace(",", " "))
    expected_label = normalize_text(permit.get("expected_label", ""))
    matched = event.get("bounds") == expected and (
        not observed_label or not expected_label or expected_label in observed_label
    )
    return dict(matched=matched, reason="EXACT_ACTIVATED_BOUNDS" if matched else "ACTIVATED_TARGET_MISMATCH",
                actual_hit=event, authorized_target=permit["target_identity"])


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
