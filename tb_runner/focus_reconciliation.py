"""Reconcile a selected representative with the coherent post-move focus.

This module never grants a physical visit.  Callers provide the existing visit
gate decision and may apply the observed focus to traversal state only when that
gate already permits a visit.  Candidate mapping is instance based and keeps
expected-content membership separate from an observed focus outside that set.
"""

from __future__ import annotations

from typing import Any, Iterable

from tb_runner.traversal_reliability import observed_focus_instance, instance_id, normalized, normalized_bounds


_SEMANTIC_KEYS = (
    "semantic_card_id",
    "semantic_card_role",
    "semantic_card_title",
    "semantic_card_values",
    "semantic_card_actions",
    "semantic_card_bounds",
    "semantic_card_member_count",
    "semantic_card_is_value_covered",
    "semantic_card_is_action_only",
    "semantic_card_is_title_only",
)


def has_strict_post_move_focus(row: dict[str, Any], move_result: str) -> bool:
    """Whether a completed traversal move has a strict accessibility focus payload."""
    if str(move_result or "").strip().lower() not in {"moved", "scrolled", "edge_realign_then_moved"}:
        return False
    if row.get("actual_focus_accessibility_focused") is True:
        return True
    node = row.get("actual_focus_node")
    if not isinstance(node, dict):
        node = row.get("focus_node")
    return bool(isinstance(node, dict) and node.get("accessibilityFocused") is True)


def _node(candidate: dict[str, Any]) -> dict[str, Any]:
    value = candidate.get("node")
    return value if isinstance(value, dict) else candidate


def _candidate_item(candidate: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    node = _node(candidate)
    return {
        "scenario_id": candidate.get("scenario_id") or scenario_id,
        "view_id": candidate.get("rid") or candidate.get("view_id") or node.get("viewIdResourceName") or node.get("resourceId") or "",
        "bounds": candidate.get("bounds") or node.get("boundsInScreen") or node.get("bounds") or "",
        "label": candidate.get("label") or node.get("talkbackLabel") or node.get("contentDescription") or node.get("text") or "",
        "class_name": candidate.get("class_name") or node.get("className") or node.get("class") or "",
        "role": candidate.get("role") or node.get("role") or node.get("accessibilityRole") or "",
        "container_id": candidate.get("container_id") or candidate.get("ancestor_id") or node.get("containerId") or node.get("ancestorId") or node.get("parentResourceId") or "",
        "stable_node_path": candidate.get("stable_node_path") or node.get("stableNodePath") or node.get("nodePath") or node.get("path") or "",
        "candidate": candidate,
    }


def _actual_item(row: dict[str, Any], scenario_id: str) -> dict[str, Any] | None:
    # Preserve coherent before-focus evidence even when the visit gate did not
    # credit that earlier row to the ledger.
    observation_row = dict(row)
    observation_row.pop("physical_visited", None)
    observed = observed_focus_instance(observation_row)
    if observed is None:
        return None
    node = row.get("actual_focus_node")
    if not isinstance(node, dict):
        node = row.get("focus_node")
    node = node if isinstance(node, dict) else {}
    return {
        **observed,
        "scenario_id": observed.get("scenario_id") or scenario_id,
        "class_name": row.get("actual_focus_class_name") or node.get("className") or node.get("class") or "",
        "role": row.get("actual_focus_role") or node.get("role") or node.get("accessibilityRole") or "",
        "container_id": row.get("actual_focus_container_id") or node.get("containerId") or node.get("ancestorId") or node.get("parentResourceId") or "",
        "stable_node_path": row.get("actual_focus_node_path") or node.get("stableNodePath") or node.get("nodePath") or node.get("path") or "",
        "node": node,
    }


def _strict_focus_proof(row: dict[str, Any] | None, scenario_id: str) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(row, dict):
        return "UNAVAILABLE", None
    node = row.get("actual_focus_node")
    if not isinstance(node, dict):
        node = row.get("focus_node")
    node = node if isinstance(node, dict) else {}
    top_flag = row.get("actual_focus_accessibility_focused")
    node_flag = node.get("accessibilityFocused")
    if isinstance(top_flag, bool) and isinstance(node_flag, bool) and top_flag is not node_flag:
        return "AMBIGUOUS", None
    strict = top_flag is True or (top_flag is None and node_flag is True)
    if not strict:
        return "UNAVAILABLE", None
    actual = _actual_item(row, scenario_id)
    if actual is None or not normalized_bounds(actual.get("bounds")):
        return "UNAVAILABLE", None
    return "STRICT", actual


def _candidate_matches(actual: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, int]:
    """Require instance geometry and at least three compatible identity signals."""
    actual_rid = normalized(actual.get("view_id"))
    candidate_rid = normalized(candidate.get("view_id"))
    actual_bounds = normalized_bounds(actual.get("bounds"))
    candidate_bounds = normalized_bounds(candidate.get("bounds"))
    if not actual_bounds or not candidate_bounds or actual_bounds != candidate_bounds:
        return False, 0
    if actual_rid and candidate_rid and actual_rid != candidate_rid:
        return False, 0

    signals = 1  # exact bounds are required for a physical instance match
    if actual_rid and candidate_rid and actual_rid == candidate_rid:
        signals += 1
    actual_label = normalized(actual.get("label"))
    candidate_label = normalized(candidate.get("label"))
    if actual_label and candidate_label and actual_label == candidate_label:
        signals += 1
    actual_class = normalized(actual.get("class_name"))
    candidate_class = normalized(candidate.get("class_name"))
    if actual_class and candidate_class and actual_class == candidate_class:
        signals += 1
    actual_role = normalized(actual.get("role"))
    candidate_role = normalized(candidate.get("role"))
    if actual_role and candidate_role and actual_role == candidate_role:
        signals += 1
    actual_container = normalized(actual.get("container_id"))
    candidate_container = normalized(candidate.get("container_id"))
    if actual_container and candidate_container and actual_container == candidate_container:
        signals += 1
    actual_path = normalized(actual.get("stable_node_path"))
    candidate_path = normalized(candidate.get("stable_node_path"))
    if actual_path and candidate_path and actual_path == candidate_path:
        signals += 1
    return signals >= 3, signals


def _previous_actual_id(previous_row: dict[str, Any] | None, scenario_id: str) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(previous_row, dict):
        return "", None
    previous = _actual_item(previous_row, scenario_id)
    return (instance_id(previous), previous) if previous else ("", None)


def reconcile_focus(
    *,
    row: dict[str, Any],
    previous_row: dict[str, Any] | None,
    scenario_id: str,
    inventory: Iterable[dict[str, Any]],
    expected_candidates: Iterable[dict[str, Any]],
    physical_visit_confirmed: bool,
    planning_consumed: bool,
    physical_progress_confirmed: bool | None = None,
    visited_instance_ids_before: Iterable[str] = (),
    consumed_cluster_signatures: Iterable[str] = (),
) -> dict[str, Any]:
    """Build structured reconciliation facts without changing row semantics."""
    actual = _actual_item(row, scenario_id)
    actual_id = instance_id(actual) if actual else ""
    before_id, before = _previous_actual_id(previous_row, scenario_id)
    current_proof, _current_strict_item = _strict_focus_proof(row, scenario_id)
    previous_proof, _previous_strict_item = _strict_focus_proof(previous_row, scenario_id)
    actual_node = row.get("actual_focus_node")
    if not isinstance(actual_node, dict):
        actual_node = row.get("focus_node")
    strict_a11y = row.get("actual_focus_accessibility_focused")
    if strict_a11y is None and isinstance(actual_node, dict):
        strict_a11y = actual_node.get("accessibilityFocused")
    strict = strict_a11y is True

    selected: dict[str, Any] | None = None
    if str(row.get("row_source", "") or "").strip() == "representative":
        selected = {
            "scenario_id": scenario_id,
            "view_id": row.get("focus_view_id", ""),
            "bounds": row.get("focus_bounds", ""),
            "label": row.get("visible_label", "") or row.get("merged_announcement", ""),
            "class_name": row.get("focus_class_name", ""),
            "role": row.get("focus_role", ""),
            "container_id": row.get("focus_container_id", ""),
            "stable_node_path": row.get("focus_node_path", ""),
        }
    selected_id = instance_id(selected) if selected else ""
    requested_id = str(row.get("smart_nav_requested_view_id", "") or "").strip()

    inventory_items: dict[str, dict[str, Any]] = {}
    for raw in inventory:
        if not isinstance(raw, dict):
            continue
        candidate = _candidate_item(raw, scenario_id)
        key = instance_id(candidate)
        if key and key not in inventory_items:
            inventory_items[key] = candidate
    # The selected representative itself is valid inventory evidence for the
    # normal selected=A, actual=A case, even if the tree omitted the row.
    if selected is not None and selected_id:
        inventory_items.setdefault(selected_id, {**selected, "candidate": {**selected, **{k: row.get(k) for k in _SEMANTIC_KEYS}}})

    expected_ids = {
        instance_id(_candidate_item(candidate, scenario_id))
        for candidate in expected_candidates
        if isinstance(candidate, dict)
    }
    if selected is not None and selected_id:
        expected_ids.add(selected_id)

    exact = inventory_items.get(actual_id) if actual_id else None
    matched: dict[str, Any] | None = exact
    confidence = "EXACT" if exact else "UNMATCHED"
    if actual is not None and not exact:
        plausible: list[tuple[int, str, dict[str, Any]]] = []
        for candidate_id, candidate in inventory_items.items():
            match, score = _candidate_matches(actual, candidate)
            if match:
                plausible.append((score, candidate_id, candidate))
        if len(plausible) == 1:
            _score, _candidate_id, matched = plausible[0]
            confidence = "STRONG"
        elif len(plausible) > 1:
            confidence = "AMBIGUOUS"
            matched = None

    matched_id = instance_id(matched) if matched else ""
    in_expected = bool(matched_id and matched_id in expected_ids)
    sequence_changed = bool(actual_id and before_id and actual_id != before_id)
    same_instance_payload_changed = bool(
        actual is not None and before is not None and actual_id == before_id
        and any(normalized(actual.get(key)) != normalized(before.get(key))
                for key in ("class_name", "role", "container_id", "stable_node_path")
                if normalized(actual.get(key)) and normalized(before.get(key)))
    )
    if current_proof == "AMBIGUOUS" or previous_proof == "AMBIGUOUS" or confidence == "AMBIGUOUS":
        focus_transition_status = "AMBIGUOUS"
    elif current_proof != "STRICT" or previous_proof != "STRICT":
        focus_transition_status = "UNAVAILABLE"
    elif not actual_id or not before_id:
        focus_transition_status = "UNAVAILABLE"
    elif actual_id != before_id:
        focus_transition_status = "CONFIRMED_MOVED"
    elif same_instance_payload_changed:
        focus_transition_status = "AMBIGUOUS"
    else:
        focus_transition_status = "CONFIRMED_UNCHANGED"
    selected_matches_actual = bool(selected_id and actual_id and selected_id == actual_id)
    consumed_clusters = {str(item or "").strip() for item in consumed_cluster_signatures if str(item or "").strip()}
    visited_before = set(visited_instance_ids_before)
    actual_focus_new_to_run = bool(actual_id and actual_id not in visited_before)
    effective_physical_visit = bool(physical_visit_confirmed and strict)
    if focus_transition_status == "CONFIRMED_MOVED":
        effective_physical_visit = True
    elif focus_transition_status in {"CONFIRMED_UNCHANGED", "AMBIGUOUS"}:
        effective_physical_visit = False
    if focus_transition_status == "CONFIRMED_MOVED":
        visit_record_status = "RECORDED" if actual_focus_new_to_run else "ALREADY_VISITED"
        progress_status = "PROGRESS" if actual_focus_new_to_run else "NO_PROGRESS_DUPLICATE_INSTANCE"
    elif focus_transition_status == "CONFIRMED_UNCHANGED":
        visit_record_status = "ALREADY_VISITED" if actual_id in visited_before else "NOT_RECORDED_UNCHANGED"
        progress_status = "NO_PROGRESS_UNCHANGED"
    elif focus_transition_status == "AMBIGUOUS":
        visit_record_status = "NOT_RECORDED_AMBIGUOUS"
        progress_status = "NO_PROGRESS_AMBIGUOUS"
    else:
        visit_record_status = "RECORDED_BY_EXISTING_GATE" if effective_physical_visit else "UNAVAILABLE"
        if effective_physical_visit and physical_progress_confirmed is True:
            progress_status = "PROGRESS_BY_EXISTING_GATE"
        elif effective_physical_visit and sequence_changed and actual_focus_new_to_run and in_expected:
            progress_status = "PROGRESS_BY_EXISTING_GATE"
        else:
            progress_status = "UNAVAILABLE"
    mapped_candidate = matched.get("candidate", {}) if matched else {}
    mapped_cluster = str(mapped_candidate.get("cluster_signature", "") or "").strip() if isinstance(mapped_candidate, dict) else ""
    cases: list[str] = []
    if actual_id and before_id and actual_id == before_id:
        cases.append("CASE_A_SMART_NEXT_SAME_FOCUS")
    if same_instance_payload_changed:
        cases.append("CASE_B_IDENTITY_COLLAPSE")
    if sequence_changed and mapped_cluster and mapped_cluster in consumed_clusters:
        cases.append("CASE_C_SEMANTIC_CLUSTER_ALREADY_CONSUMED")
    if selected_id and actual_id and selected_id != actual_id:
        cases.append("CASE_D_SELECTION_ORDER_MISMATCH")

    if not strict or actual is None:
        classification = "NO_STRICT_ACTUAL_FOCUS"
    elif confidence == "AMBIGUOUS":
        classification = "AMBIGUOUS_ACTUAL_FOCUS"
    elif not in_expected:
        classification = "UNEXPECTED_ACTUAL_FOCUS"
    elif selected_matches_actual:
        classification = "ALIGNED"
    else:
        classification = "RECONCILED"

    return {
        "selection_candidate_instance_id": selected_id,
        "requested_target_id": requested_id,
        "requested_target_label": str(row.get("smart_nav_requested_label", "") or "").strip(),
        "actual_focus_before_id": before_id,
        "actual_focus_instance_id": actual_id,
        "reconciled_visit_instance_id": actual_id if effective_physical_visit and strict else "",
        "mapped_candidate_instance_id": matched_id,
        "mapping_confidence": confidence,
        "candidate_in_expected_population": in_expected,
        "classification": classification,
        "cases": cases,
        "focus_sequence_changed": sequence_changed,
        "focus_transition_status": focus_transition_status,
        "actual_focus_new_to_run": actual_focus_new_to_run,
        "physical_visit_confirmed": effective_physical_visit,
        "visit_record_status": visit_record_status,
        "progress_status": progress_status,
        "reconciliation_progress": bool(
            focus_transition_status == "CONFIRMED_MOVED" and actual_focus_new_to_run
        ) or bool(
            focus_transition_status == "UNAVAILABLE" and effective_physical_visit
            and sequence_changed and in_expected and actual_focus_new_to_run
        ),
        "planning_consumed": bool(planning_consumed),
        "selected_candidate_consumed": bool(physical_visit_confirmed and strict and selected_matches_actual and in_expected),
        "selected_candidate_state": "focused" if selected_matches_actual else ("selected_but_not_focused" if selected_id else "none"),
        "mapped_candidate": mapped_candidate if matched else None,
        "actual_item": actual,
    }


def apply_reconciliation_to_row(row: dict[str, Any], result: dict[str, Any]) -> None:
    """Persist reconciliation and, after a permitted visit, use actual focus as traversal context."""
    actual = result.get("actual_item")
    row.update({
        "selection_candidate_instance_id": result.get("selection_candidate_instance_id", ""),
        "requested_target_id": result.get("requested_target_id", ""),
        "requested_target_label": result.get("requested_target_label", ""),
        "actual_focus_before_id": result.get("actual_focus_before_id", ""),
        "actual_focus_instance_id": result.get("actual_focus_instance_id", ""),
        "focus_transition_status": result.get("focus_transition_status", "UNAVAILABLE"),
        "reconciled_visit_instance_id": result.get("reconciled_visit_instance_id", ""),
        "mapped_candidate_instance_id": result.get("mapped_candidate_instance_id", ""),
        "focus_reconciliation_confidence": result.get("mapping_confidence", "UNMATCHED"),
        "focus_reconciliation_classification": result.get("classification", ""),
        "focus_reconciliation_cases": list(result.get("cases", [])),
        "focus_reconciliation_candidate_in_expected_population": bool(result.get("candidate_in_expected_population", False)),
        "focus_reconciliation_applied": bool(result.get("physical_visit_confirmed", False)),
        "focus_sequence_changed": bool(result.get("focus_sequence_changed", False)),
        "focus_reconciliation_progress": bool(result.get("reconciliation_progress", False)),
        "visit_record_status": result.get("visit_record_status", "UNAVAILABLE"),
        "progress_status": result.get("progress_status", "UNAVAILABLE"),
        "selected_candidate_consumed": bool(result.get("selected_candidate_consumed", False)),
        "selected_candidate_state": result.get("selected_candidate_state", "none"),
        "focus_reconciliation_planning_consumed": bool(result.get("planning_consumed", False)),
    })
    if not result.get("physical_visit_confirmed") or not isinstance(actual, dict):
        return

    selected_id = str(result.get("selection_candidate_instance_id", "") or "")
    actual_id = str(result.get("actual_focus_instance_id", "") or "")
    if selected_id and selected_id != actual_id:
        for key in _SEMANTIC_KEYS:
            row[f"selection_candidate_{key}"] = row.get(key, "")

    row["focus_view_id"] = actual.get("view_id", "")
    row["focus_bounds"] = actual.get("bounds", "")
    row["visible_label"] = actual.get("label", "")
    row["merged_announcement"] = row.get("actual_focus_speech", "") or actual.get("label", "")
    row["normalized_visible_label"] = normalized(row["visible_label"])
    row["normalized_announcement"] = normalized(row["merged_announcement"])
    row["focus_class_name"] = actual.get("class_name", "")
    node = actual.get("node") if isinstance(actual.get("node"), dict) else {}
    if node:
        row["focus_node"] = node
        row["focus_clickable"] = bool(node.get("clickable"))
        row["focus_focusable"] = bool(node.get("focusable"))
        row["focus_effective_clickable"] = bool(node.get("effectiveClickable") or node.get("clickable"))
    row["row_source"] = "actual_focus"
    row["focus_payload_source"] = row.get("actual_focus_payload_source", row.get("focus_payload_source", "none"))

    if selected_id and selected_id != actual_id:
        candidate = result.get("mapped_candidate")
        candidate = candidate if isinstance(candidate, dict) else {}
        for key in _SEMANTIC_KEYS:
            row[key] = candidate.get(key, "")
        row["focus_cluster_signature"] = candidate.get("cluster_signature", "")
        row["focus_cluster_logical_signature"] = candidate.get("cluster_logical_signature", "")
        row["selected_candidate_state"] = "selected_but_not_focused"


__all__ = ["apply_reconciliation_to_row", "has_strict_post_move_focus", "reconcile_focus"]
