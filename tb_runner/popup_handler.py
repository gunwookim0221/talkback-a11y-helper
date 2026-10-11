import re
from dataclasses import dataclass
from typing import Any

from tb_runner.samsung_account_popup import (
    LATER_RESOURCE_ID,
    SETUP_RESOURCE_ID,
    find_samsung_account_popup_candidate,
    normalize as normalize_samsung_popup_label,
)
from tb_runner.utils import parse_bounds_str


SAFE_ACTION_LABELS = {
    "확인",
    "닫기",
    "취소",
    "괜찮아요",
    "완료",
    "알겠습니다",
    "ok",
    "close",
    "dismiss",
    "not now",
    "no thanks",
    "done",
    "got it",
    "cancel",
}

SAMSUNG_ACCOUNT_LATER_RESOURCE_ID = LATER_RESOURCE_ID
SAMSUNG_ACCOUNT_SETUP_NOW_RESOURCE_ID = SETUP_RESOURCE_ID

DANGEROUS_ACTION_LABELS = {
    "삭제",
    "제거",
    "초기화",
    "탈퇴",
    "로그아웃",
    "해제",
    "연결 해제",
    "공장 초기화",
    "제출",
    "보내기",
    "구매",
    "결제",
    "동의",
    "허용",
    "delete",
    "remove",
    "reset",
    "factory reset",
    "sign out",
    "log out",
    "disconnect",
    "submit",
    "send",
    "buy",
    "purchase",
    "pay",
    "agree",
    "allow",
}

POPUP_STOP_REASONS = {
    "repeat_no_progress",
    "repeat_semantic_stall",
    "repeat_semantic_stall_after_escape",
    "bounded_two_card_loop",
}

BOTTOM_NAV_RESOURCE_TOKENS = (
    "menu_favorites",
    "menu_devices",
    "menu_services",
    "menu_automations",
    "menu_more",
    "bottom_navigation",
)
BOTTOM_NAV_LABELS = {"home", "devices", "life", "routines", "menu", "홈", "기기", "라이프", "루틴", "메뉴"}


@dataclass
class PopupCandidate:
    detected: bool
    reason: str
    title: str = ""
    signature: str = ""
    safe_buttons: list[dict[str, Any]] | None = None
    dangerous_buttons: list[dict[str, Any]] | None = None
    actionable_count: int = 0
    modal_evidence: list[str] | None = None
    popup_kind: str = ""
    modal_classification: str = "AMBIGUOUS_OVERLAY"
    candidate_evidence: list[str] | None = None
    modal_assessment: dict[str, Any] | None = None


def normalize_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def node_label(node: dict[str, Any]) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for value in (
        str(node.get("mergedLabel", "") or "").strip(),
        str(node.get("talkbackLabel", "") or "").strip(),
        str(node.get("contentDescription", "") or "").strip(),
        str(node.get("text", "") or "").strip(),
        str(node.get("label", "") or "").strip(),
    ):
        norm = normalize_label(value)
        if value and norm not in seen:
            values.append(value)
            seen.add(norm)
    return " ".join(values).strip()


def is_safe_action_label(label: str) -> bool:
    return normalize_label(label) in SAFE_ACTION_LABELS


def is_dangerous_action_label(label: str) -> bool:
    return normalize_label(label) in DANGEROUS_ACTION_LABELS


def _iter_nodes(value: Any):
    stack: list[Any] = []
    if isinstance(value, list):
        stack.extend(reversed(value))
    elif isinstance(value, dict):
        stack.append(value)
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        yield node
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(reversed(children))


def _node_visible(node: dict[str, Any]) -> bool:
    if "visibleToUser" in node:
        return bool(node.get("visibleToUser"))
    if "isVisibleToUser" in node:
        return bool(node.get("isVisibleToUser"))
    return True


def _node_actionable(node: dict[str, Any]) -> bool:
    return bool(node.get("clickable") or node.get("effectiveClickable") or node.get("focusable"))


def _node_resource_id(node: dict[str, Any]) -> str:
    return str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()


def _node_class_name(node: dict[str, Any]) -> str:
    return str(node.get("className", "") or node.get("class", "") or "").strip()


def _node_bounds(node: dict[str, Any]) -> tuple[int, int, int, int] | None:
    return parse_bounds_str(node.get("boundsInScreen", "") or node.get("bounds", ""))


def _is_bottom_nav_like(node: dict[str, Any], label: str) -> bool:
    resource_id = _node_resource_id(node).lower()
    class_name = _node_class_name(node).lower()
    norm = normalize_label(label)
    if any(token in resource_id for token in BOTTOM_NAV_RESOURCE_TOKENS):
        return True
    if "tab" in class_name and norm in BOTTOM_NAV_LABELS:
        return True
    return False


def _candidate_evidence(nodes: list[dict[str, Any]]) -> list[str]:
    """Semantic strings nominate popup candidates; they do not establish a modal."""
    evidence = set()
    for node in nodes:
        if "popup" in _node_resource_id(node).lower():
            evidence.add("popup_resource")
        if "popup" in normalize_label(node.get("text")):
            evidence.add("popup_text")
        if "popup" in normalize_label(node.get("contentDescription")):
            evidence.add("popup_description")
    return sorted(evidence)


def _bounds_tuple(value: Any) -> tuple[int, int, int, int] | None:
    if isinstance(value, dict):
        try:
            return (int(value.get("left", value.get("l"))), int(value.get("top", value.get("t"))),
                    int(value.get("right", value.get("r"))), int(value.get("bottom", value.get("b"))))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return tuple(int(v) for v in value)
        except (TypeError, ValueError):
            return None
    return parse_bounds_str(value)


def classify_modal_state(row: dict[str, Any], nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Classify overlay semantics from hierarchy/window/accessibility evidence.

    Popup-like resource/text is candidate evidence only. Unknown overlay evidence
    remains conservative. A localized control is cleared only when the active
    same-activity window, background accessibility and external TalkBack focus
    all corroborate a non-modal control.
    """
    nodes = nodes if nodes is not None else [n for n in _iter_nodes(
        [row.get("focus_node", {}), *(row.get("dump_tree_nodes") or [])]) if _node_visible(n)]
    candidate = _candidate_evidence(nodes)
    dialog_nodes = [n for n in nodes if "dialog" in _node_class_name(n).lower()
                    or "alert" in _node_class_name(n).lower()]
    win = row.get("window_evidence") or {}
    focused_type = str(win.get("focused_window_type") or row.get("focused_window_type") or "").upper()
    focused_window = str(win.get("focused_window_component") or row.get("focused_window_component") or "")
    activity = str(row.get("activity_name") or "")
    focused_activity_matches = win.get("focused_activity_matches") is True or (
        row.get("context_source") == "window_current_focus" and bool(activity)
        and (not focused_window or focused_window == activity
             or focused_window.endswith("/" + activity.split(".")[-1])))
    dialog_window = bool(win.get("focused_window_is_dialog") or row.get("focused_window_is_dialog")
                         or "DIALOG" in focused_type)
    display = _bounds_tuple(row.get("display_bounds"))
    display_area = max(0, display[2] - display[0]) * max(0, display[3] - display[1]) if display else 0
    candidate_nodes = [n for n in nodes if "popup" in _node_resource_id(n).lower()
                       or "popup" in normalize_label(n.get("text"))
                       or "popup" in normalize_label(n.get("contentDescription"))]
    rects = [_node_bounds(n) for n in candidate_nodes]
    rects = [b for b in rects if b]
    if rects and display_area:
        union = (min(b[0] for b in rects), min(b[1] for b in rects),
                 max(b[2] for b in rects), max(b[3] for b in rects))
        candidate_area_ratio = max(0, union[2]-union[0]) * max(0, union[3]-union[1]) / display_area
    else:
        candidate_area_ratio = None
    blocking_bounds = _bounds_tuple(row.get("blocking_overlay_bounds"))
    blocking_area_ratio = None
    if blocking_bounds and display_area:
        blocking_area_ratio = max(0, blocking_bounds[2]-blocking_bounds[0]) * max(0, blocking_bounds[3]-blocking_bounds[1]) / display_area
    elif row.get("blocking_overlay") is True:
        blocking_area_ratio = 1.0

    def within_candidate(bounds):
        if not bounds or not rects:
            return False
        cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in rects)

    def in_candidate_subtree(node):
        if node in candidate_nodes:
            return True
        return any("popup" in str(a.get("resource_id") or a.get("view_id_resource_name") or "").lower()
                   for a in node.get("ancestors", []) if isinstance(a, dict))

    focus = row.get("focus_node") or {}
    focus_bounds = _bounds_tuple(focus.get("boundsInScreen") or focus.get("bounds"))
    focus_outside = focus.get("accessibilityFocused") is True and bool(rects) and not within_candidate(focus_bounds)
    background_nodes = [n for n in nodes if not in_candidate_subtree(n) and _node_visible(n)
                        and n.get("enabled") is not False
                        and (bool(n.get("clickable") or n.get("effectiveClickable") or n.get("focusable"))
                             or n.get("accessibilityFocused") is True)]
    background_accessible = (row.get("background_accessible") if isinstance(row.get("background_accessible"), bool)
                             else bool(background_nodes and focus_outside))
    explicit_background_blocked = row.get("background_accessible") is False
    dismiss_action_present = row.get("dismiss_action_present") is True or any(
        node_label(n) and is_safe_action_label(node_label(n)) and _node_actionable(n) for n in nodes)
    modal_evidence = []
    if dialog_nodes:
        modal_evidence.append("dialog_class")
        body_labels = [node_label(n) for n in nodes if node_label(n)
                       and not is_safe_action_label(node_label(n))
                       and not is_dangerous_action_label(node_label(n))]
        actionable_nodes = [n for n in nodes if _node_actionable(n) and node_label(n)]
        if body_labels and actionable_nodes:
            modal_evidence.append("title_body_with_actions")
    if dialog_window:
        modal_evidence.append("focused_dialog_window")
    if explicit_background_blocked:
        modal_evidence.append("background_inaccessible")
    if blocking_area_ratio is not None and blocking_area_ratio >= 0.35:
        modal_evidence.append("blocking_region_substantial")
    if dismiss_action_present:
        modal_evidence.append("dismiss_action_present")
    if focus_outside:
        modal_evidence.append("accessibility_focus_outside_overlay")
    elif focus.get("accessibilityFocused") is True and rects:
        modal_evidence.append("accessibility_focus_inside_overlay")

    if dialog_window or (dialog_nodes and explicit_background_blocked) or (
            explicit_background_blocked and blocking_area_ratio is not None and blocking_area_ratio >= 0.35):
        classification = "VERIFIED_MODAL"
    elif dialog_nodes or (candidate_area_ratio is not None and candidate_area_ratio >= 0.35
                          and not background_accessible) or (blocking_area_ratio is not None
                          and blocking_area_ratio >= 0.35 and dismiss_action_present and not background_accessible):
        classification = "LIKELY_MODAL"
    elif (focused_activity_matches and not dialog_window and not dialog_nodes
          and candidate_area_ratio is not None and candidate_area_ratio <= 0.10
          and background_accessible and focus_outside):
        classification = "NON_MODAL_CONTROL"
    elif not candidate and not dialog_nodes and not dialog_window:
        window_context_observed = bool(win.get("window_count") or focused_type or focused_window
                                       or win.get("current_focus_line") or row.get("focused_window_type")
                                       or row.get("focused_window_component"))
        ordinary_app_window = focused_type in {"", "BASE_APPLICATION", "APPLICATION", "APPLICATION_STARTING"}
        if window_context_observed and (not focused_activity_matches or not ordinary_app_window):
            classification = "AMBIGUOUS_OVERLAY"
        else:
            classification = "NON_MODAL_CONTROL"
    else:
        classification = "AMBIGUOUS_OVERLAY"
    return dict(classification=classification, candidate_evidence=candidate,
                modal_evidence=sorted(set(modal_evidence)), focused_window_component=focused_window or None,
                focused_window_type=focused_type or None, focused_activity_matches=focused_activity_matches,
                dialog_class_count=len(dialog_nodes), background_accessible=bool(background_accessible),
                background_actionable_count=len(background_nodes), accessibility_focus_outside=focus_outside,
                candidate_area_ratio=candidate_area_ratio, blocking_area_ratio=blocking_area_ratio,
                dismiss_action_present=dismiss_action_present)


def _modal_evidence(nodes: list[dict[str, Any]], labels: list[str], action_nodes: list[dict[str, Any]],
                    row: dict[str, Any] | None = None) -> list[str]:
    """Return modal evidence only; popup strings never stand in for a modal root."""
    _ = labels, action_nodes
    result = classify_modal_state(row or {}, nodes)
    return result["modal_evidence"]


def _is_samsung_account_popup(nodes: list[dict[str, Any]], labels: list[str]) -> bool:
    _ = labels
    return find_samsung_account_popup_candidate(nodes) is not None


def _samsung_account_safe_buttons(action_nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    safe_buttons: list[dict[str, Any]] = []
    for node in action_nodes:
        label = node_label(node)
        resource_id = normalize_samsung_popup_label(_node_resource_id(node))
        normalized_label = normalize_samsung_popup_label(label)
        button = {"node": node, "label": label}
        if resource_id == SAMSUNG_ACCOUNT_SETUP_NOW_RESOURCE_ID:
            continue
        if resource_id == SAMSUNG_ACCOUNT_LATER_RESOURCE_ID and normalized_label in {"later", "나중에"}:
            safe_buttons.append(button)
        elif normalized_label in {"later", "나중에"}:
            safe_buttons.append(button)
    return safe_buttons, []


def detect_popup_candidate(row: dict[str, Any], *, max_actionable_count: int = 5) -> PopupCandidate:
    raw_nodes: list[Any] = []
    focus_node = row.get("focus_node")
    if isinstance(focus_node, dict):
        raw_nodes.append(focus_node)
    dump_nodes = row.get("dump_tree_nodes")
    if isinstance(dump_nodes, list):
        raw_nodes.extend(dump_nodes)

    nodes = [node for node in _iter_nodes(raw_nodes) if _node_visible(node)]
    labels = [label for node in nodes if (label := node_label(node))]
    safe_buttons: list[dict[str, Any]] = []
    dangerous_buttons: list[dict[str, Any]] = []
    action_nodes: list[dict[str, Any]] = []
    for node in nodes:
        label = node_label(node)
        if not label or not _node_actionable(node) or _is_bottom_nav_like(node, label):
            continue
        action_nodes.append(node)
        button = {"node": node, "label": label}
        if is_dangerous_action_label(label):
            dangerous_buttons.append(button)
        elif is_safe_action_label(label):
            safe_buttons.append(button)

    actionable_count = len(action_nodes)
    assessment = classify_modal_state(row, nodes)
    modal_evidence = assessment["modal_evidence"]
    candidate_evidence = assessment["candidate_evidence"]
    samsung_popup = _is_samsung_account_popup(nodes, labels)
    popup_kind = "samsung_account_two_step" if samsung_popup else ""
    if samsung_popup:
        safe_buttons, dangerous_buttons = _samsung_account_safe_buttons(action_nodes)
    title = next(
        (
            label
            for label in labels
            if not is_safe_action_label(label) and not is_dangerous_action_label(label)
        ),
        "",
    )
    signature_parts = sorted({normalize_label(label) for label in labels if normalize_label(label)})
    signature = "|".join(signature_parts[:12])

    def result(detected: bool, reason: str) -> PopupCandidate:
        return PopupCandidate(detected, reason, title, signature, safe_buttons, dangerous_buttons,
                              actionable_count, modal_evidence, popup_kind,
                              assessment["classification"], candidate_evidence, assessment)
    if dangerous_buttons:
        return result(False, "dangerous_action_present")
    if not safe_buttons:
        return result(False, "no_safe_action")
    if assessment["classification"] not in {"VERIFIED_MODAL", "LIKELY_MODAL"}:
        return result(False, "missing_modal_evidence")
    if actionable_count > max_actionable_count:
        return result(False, "too_many_actionable_candidates")
    return result(True, "modal_candidate")


def tap_popup_button(client: Any, dev: str, button: dict[str, Any]) -> bool:
    node = button.get("node", {})
    resource_id = _node_resource_id(node) if isinstance(node, dict) else ""
    if normalize_label(resource_id) == SAMSUNG_ACCOUNT_LATER_RESOURCE_ID:
        touched = bool(client.touch(dev=dev, type_="resourceId", name=f"^{re.escape(resource_id)}$"))
        if touched:
            return True
    label = str(button.get("label", "") or "").strip()
    if label and normalize_label(resource_id) == SAMSUNG_ACCOUNT_LATER_RESOURCE_ID:
        touched = bool(client.touch(dev=dev, type_="text", name=f"^{re.escape(label)}$"))
        if touched:
            return True
    bounds = _node_bounds(node) if isinstance(node, dict) else None
    if bounds:
        left, top, right, bottom = bounds
        tap_xy_adb = getattr(client, "tap_xy_adb", None)
        if callable(tap_xy_adb):
            return bool(tap_xy_adb(dev=dev, x=(left + right) // 2, y=(top + bottom) // 2))
    if resource_id:
        return bool(client.touch(dev=dev, type_="resourceId", name=f"^{re.escape(resource_id)}$"))
    if label:
        return bool(client.touch(dev=dev, type_="text", name=f"^{re.escape(label)}$"))
    return False
