import re
from dataclasses import dataclass
from typing import Any

from tb_runner.utils import parse_bounds_str


SAFE_ACTION_LABELS = {
    "확인",
    "닫기",
    "취소",
    "나중에",
    "나중에 하기",
    "괜찮아요",
    "완료",
    "알겠습니다",
    "ok",
    "close",
    "dismiss",
    "later",
    "not now",
    "no thanks",
    "done",
    "got it",
    "cancel",
}

SAMSUNG_ACCOUNT_TITLE_TOKEN = "protect your samsung account"
SAMSUNG_ACCOUNT_MESSAGE_TOKEN = "two-step verification"
SAMSUNG_ACCOUNT_LATER_RESOURCE_ID = "android:id/button3"
SAMSUNG_ACCOUNT_SETUP_NOW_RESOURCE_ID = "android:id/button1"

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


def _modal_evidence(nodes: list[dict[str, Any]], labels: list[str], action_nodes: list[dict[str, Any]]) -> list[str]:
    evidence: list[str] = []
    if any("dialog" in _node_class_name(node).lower() or "alert" in _node_class_name(node).lower() for node in nodes):
        evidence.append("dialog_class")
    if any("dialog" in _node_resource_id(node).lower() or "popup" in _node_resource_id(node).lower() for node in nodes):
        evidence.append("popup_resource")
    non_action_labels = [
        label
        for label in labels
        if label and not is_safe_action_label(label) and not is_dangerous_action_label(label)
    ]
    modal_container_seen = any(
        "dialog" in _node_class_name(node).lower()
        or "alert" in _node_class_name(node).lower()
        or "popup" in _node_resource_id(node).lower()
        for node in nodes
    )
    if modal_container_seen and non_action_labels and action_nodes:
        evidence.append("title_body_with_actions")
    action_bounds = [_node_bounds(node) for node in action_nodes]
    if action_bounds and all(bounds is not None for bounds in action_bounds):
        tops = [bounds[1] for bounds in action_bounds if bounds is not None]
        if tops and min(tops) >= 900:
            evidence.append("bottom_sheet_actions")
    return evidence


def _is_samsung_account_popup(nodes: list[dict[str, Any]], labels: list[str]) -> bool:
    title_match = False
    message_match = False
    for node in nodes:
        resource_id = normalize_label(_node_resource_id(node))
        label = normalize_label(node_label(node))
        if resource_id == "android:id/alerttitle" and SAMSUNG_ACCOUNT_TITLE_TOKEN in label:
            title_match = True
        if resource_id == "android:id/message" and SAMSUNG_ACCOUNT_MESSAGE_TOKEN in label:
            message_match = True
    if title_match or message_match:
        return True
    return any(SAMSUNG_ACCOUNT_TITLE_TOKEN in normalize_label(label) for label in labels) or any(
        SAMSUNG_ACCOUNT_MESSAGE_TOKEN in normalize_label(label) for label in labels
    )


def _samsung_account_safe_buttons(action_nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    safe_buttons: list[dict[str, Any]] = []
    for node in action_nodes:
        label = node_label(node)
        resource_id = normalize_label(_node_resource_id(node))
        button = {"node": node, "label": label}
        if resource_id == SAMSUNG_ACCOUNT_LATER_RESOURCE_ID or normalize_label(label) == "later":
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
    modal_evidence = _modal_evidence(nodes, labels, action_nodes)
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

    if dangerous_buttons:
        return PopupCandidate(False, "dangerous_action_present", title, signature, safe_buttons, dangerous_buttons, actionable_count, modal_evidence, popup_kind)
    if not safe_buttons:
        return PopupCandidate(False, "no_safe_action", title, signature, safe_buttons, dangerous_buttons, actionable_count, modal_evidence, popup_kind)
    if not modal_evidence:
        return PopupCandidate(False, "missing_modal_evidence", title, signature, safe_buttons, dangerous_buttons, actionable_count, modal_evidence, popup_kind)
    if actionable_count > max_actionable_count:
        return PopupCandidate(False, "too_many_actionable_candidates", title, signature, safe_buttons, dangerous_buttons, actionable_count, modal_evidence, popup_kind)
    return PopupCandidate(True, "modal_candidate", title, signature, safe_buttons, dangerous_buttons, actionable_count, modal_evidence, popup_kind)


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
