"""Phase 0A contracts; identities are scoped to an observed screen, not scroll pages.

Bounds are the shared discriminator in helper snapshots and focus payloads. Paths
are a fallback when geometry is absent. Mutable labels/state are evidence, except
for the last-resort geometry/path-free identity (which cannot prove a visit).
"""
from collections import defaultdict
from dataclasses import dataclass, field
import json
import re
from typing import Any

from tb_runner.diagnostics import normalize_move_result
from tb_runner.utils import parse_bounds_str


def normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def normalized_bounds(value: Any) -> str:
    bounds = parse_bounds_str(str(value or "").strip())
    if bounds is None:
        match = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", str(value or "").replace(" ", ""))
        if match:
            bounds = parse_bounds_str(",".join(match.groups()))
    return ",".join(str(part) for part in bounds) if bounds else ""


def instance_id(item: dict[str, Any]) -> str:
    scope = normalized(item.get("scenario_id", ""))
    rid = normalized(item.get("view_id", ""))
    bounds = normalized_bounds(item.get("bounds", ""))
    path = normalized(item.get("stable_node_path", "") or item.get("node_path", ""))
    container = normalized(item.get("container_id", "") or item.get("ancestor_id", ""))
    if bounds:
        discriminator = ["bounds", bounds]
    elif path:
        discriminator = ["path", container, path]
    else:
        discriminator = ["unresolved", container, normalized(item.get("label", "")), normalized(item.get("class_name", ""))]
    return json.dumps(["instance-v1", scope, rid, *discriminator], ensure_ascii=False, separators=(",", ":"))


def focus_instance(row: dict[str, Any]) -> dict[str, Any] | None:
    """Use one coherent observation; never mix planned and observed fields."""
    actual = any(str(row.get(key, "") or "").strip() for key in
                 ("actual_focus_resource_id", "actual_focus_bounds", "actual_focus_visible", "actual_focus_speech"))
    if row.get("physical_visited") is False:
        return None
    node = row.get("focus_node")
    if isinstance(node, str):
        try:
            node = json.loads(node)
        except (ValueError, TypeError):
            node = None
    node = node if isinstance(node, dict) else {}
    a11y_focused = row.get("actual_focus_accessibility_focused")
    input_focused = row.get("actual_focus_input_focused")
    if a11y_focused is None and normalized(row.get("row_source")) not in {"representative", "representative_fallback"}:
        a11y_focused, input_focused = node.get("accessibilityFocused"), node.get("focused")
    if a11y_focused is False and input_focused is False:
        return None  # A root/container fallback explicitly reporting no focus.
    if actual:
        rid, bounds = row.get("actual_focus_resource_id", ""), row.get("actual_focus_bounds", "")
        label = row.get("actual_focus_visible", "") or row.get("actual_focus_speech", "")
    else:
        if normalized(row.get("row_source")) in {"representative", "representative_fallback"}:
            return None
        if normalized(row.get("status")) in {"tab_open_failed", "fail", "error"}:
            return None
        rid, bounds = row.get("focus_view_id", ""), row.get("focus_bounds", "")
        label = row.get("visible_label", "") or row.get("merged_announcement", "")
    if not (rid or label) or not normalized_bounds(bounds):
        return None
    return dict(scenario_id=row.get("scenario_id", ""), view_id=rid, bounds=bounds, label=label)


def termination_status(reason: str) -> str:
    if reason == "content_completed":
        return "COMPLETED"
    if reason in {"content_no_progress", "content_dynamic_unsettled"}:
        return "INCOMPLETE_NO_PROGRESS"
    if reason in {"content_scroll_unverified", "content_scope_unverified"}:
        return "INCOMPLETE_SCROLL_UNVERIFIED" if reason == "content_scroll_unverified" else "INCOMPLETE_NO_PROGRESS"
    if reason == "content_error":
        return "INCOMPLETE_ERROR"
    if reason == "global_nav_verified":
        return "COMPLETED"
    if reason == "global_nav_incomplete":
        return "INCOMPLETE_GLOBAL_NAV"
    if reason == "global_nav_safety_limit":
        return "INCOMPLETE_SAFETY_LIMIT"
    if reason == "scroll_unverified":
        return "INCOMPLETE_SCROLL_UNVERIFIED"
    if reason == "scroll_error":
        return "INCOMPLETE_SCROLL_ERROR"
    if reason == "scroll_exhausted":
        return "COMPLETED"
    if reason == "safety_limit":
        return "INCOMPLETE_SAFETY_LIMIT"
    if reason in {"repeat_no_progress", "bounded_two_card_loop", "repeat_semantic_stall", "repeat_semantic_stall_after_escape", "global_nav_end",
                  "exhausted_not_scrollable_no_unvisited_local_tab", "exhausted_strip_only_terminal_state",
                  "local_tab_revisit_no_new_semantic_content"}:
        return "INCOMPLETE_NO_PROGRESS"
    if reason in {"smart_nav_terminal", "move_terminal", "global_nav_entry", "global_nav_exit", "plugin_boundary_global_nav",
                  "confirmed_local_tab_exhaustion", "special_state_handled"}:
        return "COMPLETED"
    return "INCOMPLETE_ERROR"


def identity_collisions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for item in items:
        if item.get("view_id"):
            groups[(item.get("scenario_id", ""), item["view_id"])].append(item)
    result = []
    for (scenario, rid), group in sorted(groups.items()):
        ids = {instance_id(item) for item in group}
        labels = {normalized(item.get("label")) for item in group}
        bounds = {normalized_bounds(item.get("bounds")) for item in group}
        if len(ids) > 1 or len(labels) > 1:
            result.append(dict(scenario_id=scenario, view_id=rid, instances=len(ids),
                               distinct_labels=len(labels), distinct_bounds=len(bounds)))
    return result


@dataclass
class TraversalMetrics:
    attempted_steps: int = 0
    successful_moves: int = 0
    failed_moves: int = 0
    indeterminate_moves: int = 0
    focus_moved_steps: int = 0
    ack_failed_focus_moved_steps: int = 0
    reconciled_new_visits: int = 0
    terminal_step: int = -1
    visited: set[str] = field(default_factory=set)
    focus_observations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def begin_step(self, step: int) -> None:
        self.attempted_steps += 1
        self.terminal_step = step

    def observe_move(self, row: dict[str, Any]) -> None:
        result = normalize_move_result(row)
        if result in {"moved", "scrolled", "edge_realign_then_moved"}:
            self.successful_moves += 1
        elif result in {"failed", "unchanged", "no_progress", "terminal", "end", "no_next", "no_focus", "cannot_move", "error"}:
            self.failed_moves += 1
        else:
            self.indeterminate_moves += 1

    def observe_focus(self, row: dict[str, Any]) -> None:
        observed = focus_instance(row)
        if observed:
            key = instance_id(observed)
            self.visited.add(key)
            node = row.get("focus_node", {})
            if isinstance(node, str):
                try:
                    node = json.loads(node)
                except (ValueError, TypeError):
                    node = {}
            node = node if isinstance(node, dict) else {}
            a11y = row.get("actual_focus_accessibility_focused")
            focused = row.get("actual_focus_input_focused")
            if a11y is None and normalized(row.get("row_source")) not in {"representative", "representative_fallback"}:
                a11y, focused = node.get("accessibilityFocused"), node.get("focused")
            proof = dict(scenario_id=observed["scenario_id"], step_index=row.get("step_index"),
                         actual_focus_resource_id=observed["view_id"],
                         actual_focus_bounds=normalized_bounds(observed["bounds"]), actual_focus_visible=observed["label"],
                         actual_focus_accessibility_focused=a11y, actual_focus_input_focused=focused,
                         physical_visited=row.get("physical_visited"), row_source="actual_focus",
                         evidence_source="pre_persist_coherent_focus")
            previous = self.focus_observations.get(key)
            if previous is None or (a11y is True and previous.get("actual_focus_accessibility_focused") is not True):
                self.focus_observations[key] = proof

    def observe_reconciliation(self, row: dict[str, Any]) -> None:
        transition = str(row.get("focus_transition_status", "") or "").strip().upper()
        if transition != "CONFIRMED_MOVED":
            return
        self.focus_moved_steps += 1
        if str(row.get("command_ack_status", "") or "").strip().upper() == "FAIL":
            self.ack_failed_focus_moved_steps += 1
        if str(row.get("visit_record_status", "") or "").strip().upper() == "RECORDED":
            self.reconciled_new_visits += 1

    def summary(self, rows: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        status = termination_status(reason)
        return dict(attempted_steps=self.attempted_steps, successful_moves=self.successful_moves,
                    failed_moves=self.failed_moves, indeterminate_moves=self.indeterminate_moves,
                    focus_moved_steps=self.focus_moved_steps,
                    ack_failed_focus_moved_steps=self.ack_failed_focus_moved_steps,
                    reconciled_new_visits=self.reconciled_new_visits,
                    unresolved_moves=max(0, self.attempted_steps - self.successful_moves - self.failed_moves - self.indeterminate_moves),
                    recorded_rows=len(rows), recorded_result_rows=len(rows),
                    unique_focus_instances=len(self.visited), unique_visited_instances=len(self.visited),
                    termination_status=status, termination_reason=reason,
                    termination_step=self.terminal_step, terminal_step=self.terminal_step,
                    coverage_complete=False, traversal_complete=status == "COMPLETED")
