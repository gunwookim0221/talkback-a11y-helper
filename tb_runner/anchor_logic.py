import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner.context_verifier import verify_context
from tb_runner.constants import MAIN_ANNOUNCEMENT_WAIT_SECONDS, MAIN_STEP_WAIT_SECONDS
from tb_runner.label_matcher import expand_verify_token_aliases
from tb_runner.logging_utils import log
from tb_runner.utils import _safe_regex_search, parse_bounds_str

_VALID_STABILIZATION_MODES = {"tab_context", "anchor_only", "anchor_then_context"}
_ANCHOR_VERIFY_SETTLE_SECONDS = 0.12
_ANCHOR_VERIFY_SCORE_THRESHOLD = 100
_POST_ENTRY_CORRELATION_MAX_AGE_SECONDS = 120.0
_PLUGIN_FALLBACK_BOILERPLATE_TOKENS = (
    "privacy policy",
    "terms",
    "conditions",
    "i agree",
    "agreement",
    "개인정보",
    "약관",
    "동의",
)
_DIRECT_SELECT_GENERIC_TOP_TOKENS = (
    " no activity",
    " activity",
    " (me)",
    " profile",
    " family",
    " member",
    "내 활동",
    "프로필",
    "가족",
)


@dataclass(frozen=True)
class PostEntryLandingEvidence:
    accepted: bool
    reason: str
    correlation_id: str = ""
    transition_signal: str = ""
    root_class: str = ""
    root_package: str = ""
    root_bounds: str = ""
    identity_source: str = ""
    identity_value: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iter_snapshot_nodes(nodes: list[dict[str, Any]] | None):
    stack = list(reversed(nodes or []))
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        yield node
        children = node.get("children", [])
        if isinstance(children, list):
            stack.extend(reversed(children))


def _normalized_node_identity(node: dict[str, Any]) -> str:
    return " ".join(
        str(node.get(key, "") or "").strip()
        for key in ("text", "contentDescription", "talkbackLabel", "viewIdResourceName", "resourceId")
        if str(node.get(key, "") or "").strip()
    ).strip()


def _node_bounds_key(node: dict[str, Any]) -> str:
    value = node.get("boundsInScreen", "")
    if isinstance(value, dict):
        try:
            return ",".join(str(int(value[key])) for key in ("l", "t", "r", "b"))
        except (KeyError, TypeError, ValueError):
            return ""
    return str(value or node.get("bounds", "") or "").strip()


def build_landing_surface_signature(nodes: list[dict[str, Any]] | None) -> str:
    """Build a bounded identity signature shared by pre-entry and post-entry checks."""
    parts: list[str] = []
    for node in _iter_snapshot_nodes(nodes):
        if node.get("visibleToUser") is False:
            continue
        identity = _normalized_node_identity(node)
        class_name = str(node.get("className", "") or "").strip()
        bounds = _node_bounds_key(node)
        if not (identity or class_name or bounds):
            continue
        parts.append(f"{class_name}|{identity}|{bounds}")
        if len(parts) >= 40:
            break
    return "||".join(parts)


def _empty_focused_webview_roots(nodes: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    for node in _iter_snapshot_nodes(nodes):
        class_name = str(node.get("className", "") or "").strip()
        if not class_name.lower().endswith("webview"):
            continue
        if _normalized_node_identity(node):
            continue
        if node.get("visibleToUser") is False or not bool(node.get("accessibilityFocused", False)):
            continue
        bounds = _node_bounds_key(node)
        parsed_bounds = parse_bounds_str(bounds)
        if not parsed_bounds:
            nums = [int(value) for value in re.findall(r"-?\d+", bounds)]
            parsed_bounds = tuple(nums[:4]) if len(nums) >= 4 else None
        if not parsed_bounds:
            continue
        roots.append(node)
    return roots


def _stable_webview_root(
    first_nodes: list[dict[str, Any]] | None,
    second_nodes: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, str]:
    first_roots = _empty_focused_webview_roots(first_nodes)
    second_roots = _empty_focused_webview_roots(second_nodes)
    if not first_roots or not second_roots:
        return None, "empty_focused_webview_absent"
    for first in first_roots:
        first_key = (
            str(first.get("packageName", "") or "").strip(),
            str(first.get("className", "") or "").strip(),
            _node_bounds_key(first),
        )
        for second in second_roots:
            second_key = (
                str(second.get("packageName", "") or "").strip(),
                str(second.get("className", "") or "").strip(),
                _node_bounds_key(second),
            )
            if first_key == second_key:
                return second, "stable_empty_focused_webview"
    return None, "delayed_webview_changed"


def _stable_webview_root_from_rows(
    verify_rows: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, str]:
    roots: list[dict[str, Any]] = []
    for row in verify_rows or []:
        if not isinstance(row, dict):
            continue
        root = row.get("get_focus_partial_root_evidence", {})
        if isinstance(root, dict) and _empty_focused_webview_roots([root]):
            roots.append(root)
    if len(roots) < 2:
        return None, "empty_focused_webview_absent"
    first_key = (
        str(roots[0].get("packageName", "") or "").strip(),
        str(roots[0].get("className", "") or "").strip(),
        _node_bounds_key(roots[0]),
    )
    second_key = (
        str(roots[1].get("packageName", "") or "").strip(),
        str(roots[1].get("className", "") or "").strip(),
        _node_bounds_key(roots[1]),
    )
    if first_key != second_key:
        return None, "delayed_webview_changed"
    return roots[1], "stable_empty_focused_webview"


def _configured_landing_patterns(tab_cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    label_patterns: list[str] = []
    resource_patterns: list[str] = []
    entry_match = tab_cfg.get("entry_match", {})
    if isinstance(entry_match, dict):
        label_patterns.extend(str(value or "") for value in entry_match.get("title_patterns", []) or [])
        resource_patterns.extend(str(value or "") for value in entry_match.get("resource_patterns", []) or [])
    context_verify = tab_cfg.get("context_verify", {})
    if isinstance(context_verify, dict):
        label_patterns.append(str(context_verify.get("text_regex", "") or ""))
    anchor_cfg = _resolve_anchor_cfg(tab_cfg)
    resource_patterns.append(str(anchor_cfg.get("resource_id_regex", "") or ""))
    return [value for value in label_patterns if value], [value for value in resource_patterns if value]


def _stable_configured_identity(
    tab_cfg: dict[str, Any],
    first_nodes: list[dict[str, Any]] | None,
    second_nodes: list[dict[str, Any]] | None,
) -> tuple[str, str]:
    label_patterns, resource_patterns = _configured_landing_patterns(tab_cfg)

    def collect(nodes: list[dict[str, Any]] | None) -> dict[tuple[str, str, str], tuple[str, str]]:
        matches: dict[tuple[str, str, str], tuple[str, str]] = {}
        for node in _iter_snapshot_nodes(nodes):
            if node.get("visibleToUser") is False:
                continue
            class_name = str(node.get("className", "") or "").strip()
            if class_name.lower().endswith("webview"):
                continue
            label = " ".join(
                str(node.get(key, "") or "").strip()
                for key in ("text", "contentDescription", "talkbackLabel")
                if str(node.get(key, "") or "").strip()
            ).strip()
            resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
            bounds = _node_bounds_key(node)
            if resource_id and any(_safe_regex_search(pattern, resource_id) for pattern in resource_patterns):
                matches[(resource_id, bounds, class_name)] = ("exact_resource", resource_id)
            if label and any(_safe_regex_search(pattern, label) for pattern in label_patterns):
                matches[(label, bounds, class_name)] = ("configured_child", label)
        return matches

    first = collect(first_nodes)
    second = collect(second_nodes)
    for key in first.keys() & second.keys():
        return second[key]
    return "", ""


def _verify_rows_allow_empty_webview_bundle(verify_rows: list[dict[str, Any]] | None) -> bool:
    observed_keys: list[tuple[str, str]] = []
    for row in verify_rows or []:
        if not isinstance(row, dict):
            continue
        focus_node = row.get("focus_node", {})
        if not focus_node and isinstance(row.get("get_focus_partial_root_evidence"), dict):
            focus_node = row.get("get_focus_partial_root_evidence", {})
        class_name = str((focus_node or {}).get("className", "") or row.get("focus_class_name", "") or "").strip()
        bounds = str(row.get("focus_bounds", "") or (focus_node or {}).get("boundsInScreen", "") or "").strip()
        label = str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
        if not (class_name or bounds or label):
            continue
        if class_name and not class_name.lower().endswith("webview"):
            return False
        observed_keys.append((class_name, bounds))
    return len(set(observed_keys)) <= 1


def evaluate_post_entry_landing_evidence(
    *,
    tab_cfg: dict[str, Any],
    phase: str,
    first_nodes: list[dict[str, Any]] | None,
    second_nodes: list[dict[str, Any]] | None,
    verify_rows: list[dict[str, Any]] | None,
    now_monotonic_ns: int | None = None,
) -> PostEntryLandingEvidence:
    transition = tab_cfg.get("entry_transition_evidence", {})
    if not isinstance(transition, dict):
        transition = {}
    scenario_id = str(tab_cfg.get("scenario_id", "") or "").strip()
    correlation_id = str(transition.get("correlation_id", "") or "").strip()
    if phase != "scenario_start" or str(tab_cfg.get("screen_context_mode", "") or "") != "new_screen":
        return PostEntryLandingEvidence(False, "scope_not_eligible")
    if str(tab_cfg.get("stabilization_mode", "") or "") != "anchor_only":
        return PostEntryLandingEvidence(False, "scope_not_eligible")
    if not correlation_id or str(transition.get("scenario_id", "") or "") != scenario_id:
        return PostEntryLandingEvidence(False, "transaction_correlation_mismatch")
    if not bool(transition.get("transition_confirmed")) or not str(transition.get("transition_signal", "") or "").strip():
        return PostEntryLandingEvidence(False, "transition_not_confirmed", correlation_id=correlation_id)
    observed_ns = int(transition.get("observed_monotonic_ns", 0) or 0)
    current_ns = int(now_monotonic_ns if now_monotonic_ns is not None else time.monotonic_ns())
    if observed_ns <= 0 or current_ns < observed_ns or (current_ns - observed_ns) / 1_000_000_000 > _POST_ENTRY_CORRELATION_MAX_AGE_SECONDS:
        return PostEntryLandingEvidence(False, "stale_transition_evidence", correlation_id=correlation_id)
    pre_signature = str(transition.get("pre_entry_surface_signature", "") or "")
    first_signature = build_landing_surface_signature(first_nodes)
    second_signature = build_landing_surface_signature(second_nodes)
    if not pre_signature or not first_signature or not second_signature:
        return PostEntryLandingEvidence(False, "surface_signature_missing", correlation_id=correlation_id)
    if pre_signature in {first_signature, second_signature}:
        return PostEntryLandingEvidence(False, "pre_post_surface_identity_unchanged", correlation_id=correlation_id)
    if not _verify_rows_allow_empty_webview_bundle(verify_rows):
        return PostEntryLandingEvidence(False, "delayed_focus_changed", correlation_id=correlation_id)
    root, root_reason = _stable_webview_root_from_rows(verify_rows)
    if root is None and root_reason == "empty_focused_webview_absent":
        root, root_reason = _stable_webview_root(first_nodes, second_nodes)
    if root is None:
        return PostEntryLandingEvidence(False, root_reason, correlation_id=correlation_id)
    identity_source, identity_value = _stable_configured_identity(tab_cfg, first_nodes, second_nodes)
    if not identity_source:
        return PostEntryLandingEvidence(False, "configured_landing_identity_absent", correlation_id=correlation_id)
    return PostEntryLandingEvidence(
        True,
        "correlated_empty_webview_landing",
        correlation_id=correlation_id,
        transition_signal=str(transition.get("transition_signal", "") or ""),
        root_class=str(root.get("className", "") or ""),
        root_package=str(root.get("packageName", "") or ""),
        root_bounds=_node_bounds_key(root),
        identity_source=identity_source,
        identity_value=identity_value,
    )


def _extract_candidate_from_node(node: dict[str, Any], index: int = -1) -> dict[str, Any]:
    text = str(node.get("text", "") or "").strip()
    description = str(node.get("contentDescription", "") or "").strip()
    announcement = str(node.get("talkbackLabel", "") or "").strip()
    if not announcement:
        announcement = f"{text} {description}".strip()
    resource_id = str(node.get("viewIdResourceName", "") or "").strip()
    class_name = str(node.get("className", "") or "").strip()
    bounds = str(node.get("boundsInScreen", "") or "").strip()
    parsed = parse_bounds_str(bounds)
    if not parsed:
        nums = [int(v) for v in re.findall(r"-?\d+", bounds)]
        if len(nums) >= 4:
            parsed = (nums[0], nums[1], nums[2], nums[3])
    top, left, right, bottom = (parsed[1], parsed[0], parsed[2], parsed[3]) if parsed else (10**9, 10**9, -1, -1)
    return {
        "source": "dump_tree",
        "index": index,
        "text": text,
        "class_name": class_name,
        "announcement": announcement,
        "resource_id": resource_id,
        "bounds": bounds,
        "top": top,
        "left": left,
        "right": right,
        "bottom": bottom,
        "focusable": bool(node.get("focusable", False)),
        "clickable": bool(node.get("clickable", False)),
        "visible_to_user": bool(node.get("visibleToUser", True)),
        "focused": bool(node.get("focused", False)),
        "accessibility_focused": bool(node.get("accessibilityFocused", False)),
        "selected": bool(node.get("selected", False)),
    }

def _extract_candidate_from_step(step: dict[str, Any]) -> dict[str, Any]:
    bounds = str(step.get("focus_bounds", "") or "").strip()
    parsed = parse_bounds_str(bounds)
    if not parsed:
        nums = [int(v) for v in re.findall(r"-?\d+", bounds)]
        if len(nums) >= 4:
            parsed = (nums[0], nums[1], nums[2], nums[3])
    top, left, right, bottom = (parsed[1], parsed[0], parsed[2], parsed[3]) if parsed else (10**9, 10**9, -1, -1)
    return {
        "source": "focus_step",
        "index": -1,
        "text": str(step.get("visible_label", "") or "").strip(),
        "class_name": str(step.get("focus_node", {}).get("className", "") or "").strip(),
        "announcement": str(step.get("merged_announcement", "") or "").strip(),
        "resource_id": str(step.get("focus_view_id", "") or "").strip(),
        "bounds": bounds,
        "top": top,
        "left": left,
        "right": right,
        "bottom": bottom,
    }

def _resolve_anchor_cfg(tab_cfg: dict[str, Any]) -> dict[str, Any]:
    anchor_cfg = dict(tab_cfg.get("anchor", {}) or {})
    if "tie_breaker" not in anchor_cfg:
        anchor_cfg["tie_breaker"] = "top_left"
    anchor_cfg["allow_resource_id_only"] = bool(anchor_cfg.get("allow_resource_id_only", False))
    if not anchor_cfg.get("text_regex") and tab_cfg.get("anchor_name"):
        anchor_type = str(tab_cfg.get("anchor_type", "") or "").lower()
        if anchor_type in {"t", "b", "a"}:
            anchor_cfg["text_regex"] = str(tab_cfg.get("anchor_name") or "")
        if anchor_type in {"r", "a"}:
            anchor_cfg["resource_id_regex"] = str(tab_cfg.get("anchor_name") or "")
    return anchor_cfg

def _match_composite_candidate(candidate: dict[str, Any], match_cfg: dict[str, Any]) -> dict[str, Any]:
    matched_fields: list[str] = []
    score = 0

    resource_id_regex = str(match_cfg.get("resource_id_regex", "") or "").strip()
    text_regex = str(match_cfg.get("text_regex", "") or "").strip()
    announcement_regex = str(match_cfg.get("announcement_regex", "") or "").strip()
    class_name_regex = str(match_cfg.get("class_name_regex", "") or "").strip()
    bounds_regex = str(match_cfg.get("bounds_regex", "") or "").strip()
    allow_resource_id_only = bool(match_cfg.get("allow_resource_id_only", False))

    if resource_id_regex and _safe_regex_search(resource_id_regex, candidate.get("resource_id", "")):
        matched_fields.append("resource_id")
        score += 100
    if text_regex and _safe_regex_search(text_regex, candidate.get("text", "")):
        matched_fields.append("text")
        score += 40
    if announcement_regex and _safe_regex_search(announcement_regex, candidate.get("announcement", "")):
        matched_fields.append("announcement")
        score += 30
    if class_name_regex and _safe_regex_search(class_name_regex, candidate.get("class_name", "")):
        matched_fields.append("class_name")
        score += 20
    if bounds_regex and _safe_regex_search(bounds_regex, candidate.get("bounds", "")):
        matched_fields.append("bounds")
        score += 10

    has_resource_match = "resource_id" in matched_fields
    has_other_match = any(field in matched_fields for field in ("text", "announcement", "class_name"))
    matched = has_resource_match and (has_other_match or allow_resource_id_only)
    if not resource_id_regex:
        matched = bool(matched_fields)

    return {
        "matched": matched,
        "score": score,
        "matched_fields": matched_fields,
        "candidate": candidate,
        "allow_resource_id_only": allow_resource_id_only,
    }

def match_anchor(candidate: dict[str, Any], anchor_cfg: dict[str, Any]) -> dict[str, Any]:
    return _match_composite_candidate(candidate, anchor_cfg)

def choose_best_anchor_candidate(matches: list[dict[str, Any]], tie_breaker: str = "top_left") -> dict[str, Any] | None:
    if not matches:
        return None
    if tie_breaker == "top_left":
        return sorted(
            matches,
            key=lambda item: (
                -int(item.get("score", 0)),
                int(item["candidate"].get("top", 10**9)),
                int(item["candidate"].get("left", 10**9)),
            ),
        )[0]
    return sorted(matches, key=lambda item: -int(item.get("score", 0)))[0]


def _has_explicit_anchor(tab_cfg: dict[str, Any], anchor_cfg: dict[str, Any]) -> bool:
    if str(tab_cfg.get("anchor_name", "") or "").strip():
        return True
    for key in ("resource_id_regex", "text_regex", "announcement_regex", "class_name_regex", "bounds_regex"):
        if str(anchor_cfg.get(key, "") or "").strip():
            return True
    return False


def _is_fallback_chrome_candidate(candidate: dict[str, Any], screen_width: int, screen_height: int) -> bool:
    top = int(candidate.get("top", 10**9))
    bottom = int(candidate.get("bottom", -1))
    left = int(candidate.get("left", 10**9))
    right = int(candidate.get("right", -1))
    class_name = str(candidate.get("class_name", "") or "").lower()
    resource_id = str(candidate.get("resource_id", "") or "").lower()
    label_blob = " ".join(
        [
            str(candidate.get("text", "") or "").lower(),
            str(candidate.get("announcement", "") or "").lower(),
        ]
    ).strip()

    if screen_height > 0 and top <= int(screen_height * 0.1):
        if any(token in f"{resource_id} {class_name} {label_blob}" for token in ("toolbar", "actionbar", "search", "뒤로", "back")):
            return True
    if screen_height > 0 and top >= int(screen_height * 0.78):
        if any(token in f"{resource_id} {class_name} {label_blob}" for token in ("bottom", "navigation", "tab", "menu_")):
            return True
    if any(
        token in f"{resource_id} {class_name} {label_blob}"
        for token in (
            "statusbar",
            "systemui",
            "more",
            "location",
            "home_button",
            "qr code",
            "change location",
            "add",
            "더보기",
            "장소",
            "장소 qr 코드",
            "장소 변경",
            "추가",
        )
    ):
        return True
    if screen_width > 0 and (right <= 0 or left >= screen_width):
        return True
    if screen_height > 0 and (bottom <= 0 or top >= screen_height):
        return True
    return False


def _is_boilerplate_like_candidate(candidate: dict[str, Any]) -> bool:
    blob = " ".join(
        [
            str(candidate.get("text", "") or "").strip().lower(),
            str(candidate.get("announcement", "") or "").strip().lower(),
            str(candidate.get("resource_id", "") or "").strip().lower(),
        ]
    ).strip()
    if not blob:
        return False
    if any(token in blob for token in _PLUGIN_FALLBACK_BOILERPLATE_TOKENS):
        return True
    compact_len = len(re.sub(r"\s+", "", blob))
    if compact_len >= 80 and ("policy" in blob or "약관" in blob):
        return True
    return False


def _is_air_plugin_context(scenario_id: str, pre_nav_target: str) -> bool:
    scenario = str(scenario_id or "").strip().lower()
    pre_nav = str(pre_nav_target or "").strip().lower()
    return "air" in scenario or ("air" in pre_nav if pre_nav else False)


def _select_focus_based_candidate(focus_node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(focus_node, dict):
        return None
    bounds = str(focus_node.get("bounds", "") or "").strip()
    if not bounds:
        return None
    parsed = parse_bounds_str(bounds)
    if not parsed:
        nums = [int(v) for v in re.findall(r"-?\d+", bounds)]
        if len(nums) >= 4:
            parsed = (nums[0], nums[1], nums[2], nums[3])
    top, left, right, bottom = (parsed[1], parsed[0], parsed[2], parsed[3]) if parsed else (10**9, 10**9, -1, -1)
    return {
        "source": "focus_fallback",
        "index": int(focus_node.get("index", -1) or -1),
        "text": str(focus_node.get("text", "") or "").strip(),
        "class_name": str(focus_node.get("class_name", "") or "").strip(),
        "announcement": str(focus_node.get("announcement", "") or "").strip(),
        "resource_id": str(focus_node.get("resource_id", "") or "").strip(),
        "bounds": bounds,
        "top": top,
        "left": left,
        "right": right,
        "bottom": bottom,
        "focusable": bool(focus_node.get("focusable", False)),
        "clickable": bool(focus_node.get("clickable", False)),
        "visible_to_user": bool(focus_node.get("visible_to_user", True)),
    }


def _pick_top_content_fallback_candidate(
    candidates: list[dict[str, Any]],
    *,
    entry_type: str = "",
    allow_readable_only_fallback: bool = False,
    verify_tokens: list[str] | None = None,
    negative_verify_tokens: list[str] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str, str]:
    if not candidates:
        return None, "", "no_candidates"
    screen_width = max((int(c.get("right", 0) or 0) for c in candidates), default=0)
    screen_height = max((int(c.get("bottom", 0) or 0) for c in candidates), default=0)
    actionable_content_candidates = [
        c
        for c in candidates
        if bool(c.get("visible_to_user", True))
        and (bool(c.get("focusable", False)) or bool(c.get("clickable", False)))
        and int(c.get("top", 10**9)) >= 0
        and int(c.get("left", 10**9)) >= 0
        and not _is_fallback_chrome_candidate(c, screen_width, screen_height)
    ]
    readable_content_candidates = [
        c
        for c in candidates
        if bool(c.get("visible_to_user", True))
        and int(c.get("top", 10**9)) >= 0
        and int(c.get("left", 10**9)) >= 0
        and (
            str(c.get("announcement", "") or "").strip()
            or str(c.get("text", "") or "").strip()
            or str(c.get("resource_id", "") or "").strip()
        )
        and not _is_fallback_chrome_candidate(c, screen_width, screen_height)
    ]
    content_candidates = actionable_content_candidates or (readable_content_candidates if allow_readable_only_fallback else [])
    if not content_candidates:
        return None, "", "no_readable_top_candidate"
    top_y = min(int(c.get("top", 10**9)) for c in content_candidates)
    top_row_tolerance = max(24, int(screen_height * 0.02)) if screen_height > 0 else 24
    top_row_candidates = [c for c in content_candidates if int(c.get("top", 10**9)) <= top_y + top_row_tolerance]
    if not top_row_candidates:
        return None, "", "no_readable_top_candidate"

    identity_candidates = [
        c
        for c in top_row_candidates
        if str(c.get("announcement", "") or "").strip()
        or str(c.get("text", "") or "").strip()
        or str(c.get("resource_id", "") or "").strip()
    ]
    if not identity_candidates:
        return None, "", "no_readable_top_candidate"
    if allow_readable_only_fallback and not actionable_content_candidates:
        non_oversized_readable_candidates = []
        for candidate in identity_candidates:
            width = max(1, int(candidate.get("right", 0) or 0) - int(candidate.get("left", 0) or 0))
            height = max(1, int(candidate.get("bottom", 0) or 0) - int(candidate.get("top", 0) or 0))
            width_ratio = width / max(1, screen_width) if screen_width > 0 else 0.0
            height_ratio = height / max(1, screen_height) if screen_height > 0 else 0.0
            class_name = str(candidate.get("class_name", "") or "").strip().lower()
            label_blob = " ".join(
                [
                    str(candidate.get("announcement", "") or "").strip().lower(),
                    str(candidate.get("text", "") or "").strip().lower(),
                ]
            ).strip()
            oversized_generic_container = bool(
                width_ratio >= 0.94
                and height_ratio >= 0.62
                and _safe_regex_search(r"(?i)(layout|viewgroup|frame)", class_name)
                and len(re.sub(r"\s+", "", label_blob)) <= 20
            )
            if oversized_generic_container:
                continue
            non_oversized_readable_candidates.append(candidate)
        if not non_oversized_readable_candidates:
            return None, "", "no_readable_top_candidate"
        identity_candidates = non_oversized_readable_candidates

    normalized_entry_type = str(entry_type or "").strip().lower()
    normalized_verify_tokens = list(expand_verify_token_aliases(verify_tokens or []))
    normalized_negative_tokens = list(expand_verify_token_aliases(negative_verify_tokens or []))
    prioritize_verify_tokens = normalized_entry_type == "direct_select" and bool(normalized_verify_tokens)
    if prioritize_verify_tokens:
        token_hit_candidates = []
        for candidate in identity_candidates:
            blob = " ".join(
                [
                    str(candidate.get("announcement", "") or "").strip().lower(),
                    str(candidate.get("text", "") or "").strip().lower(),
                    str(candidate.get("resource_id", "") or "").strip().lower(),
                ]
            )
            if any(token in blob for token in normalized_verify_tokens):
                token_hit_candidates.append(candidate)
        if token_hit_candidates:
            identity_candidates = token_hit_candidates
    if normalized_entry_type == "direct_select":
        non_generic_candidates = []
        for candidate in identity_candidates:
            blob = " ".join(
                [
                    str(candidate.get("announcement", "") or "").strip().lower(),
                    str(candidate.get("text", "") or "").strip().lower(),
                    str(candidate.get("resource_id", "") or "").strip().lower(),
                ]
            )
            if any(token in f" {blob}" for token in _DIRECT_SELECT_GENERIC_TOP_TOKENS):
                continue
            non_generic_candidates.append(candidate)
        if non_generic_candidates:
            identity_candidates = non_generic_candidates

    def _candidate_sort_key(candidate: dict[str, Any], base_sort_key: Any) -> Any:
        base_key = base_sort_key(candidate)
        blob = " ".join(
            [
                str(candidate.get("announcement", "") or "").strip().lower(),
                str(candidate.get("text", "") or "").strip().lower(),
                str(candidate.get("resource_id", "") or "").strip().lower(),
            ]
        )
        width = max(1, int(candidate.get("right", 0) or 0) - int(candidate.get("left", 0) or 0))
        height = max(1, int(candidate.get("bottom", 0) or 0) - int(candidate.get("top", 0) or 0))
        oversized_penalty = 1 if screen_width > 0 and screen_height > 0 and (
            (width / max(1, screen_width) >= 0.88) and (height / max(1, screen_height) >= 0.24)
        ) else 0
        generic_profile_penalty = 1 if normalized_entry_type == "direct_select" and any(
            token in f" {blob}" for token in _DIRECT_SELECT_GENERIC_TOP_TOKENS
        ) else 0
        if not prioritize_verify_tokens:
            return (generic_profile_penalty, oversized_penalty, base_key)
        blob = " ".join(
            [
                str(candidate.get("announcement", "") or "").strip().lower(),
                str(candidate.get("text", "") or "").strip().lower(),
                str(candidate.get("resource_id", "") or "").strip().lower(),
            ]
        )
        verify_hit = any(token in blob for token in normalized_verify_tokens)
        return (0 if verify_hit else 1, generic_profile_penalty, oversized_penalty, base_key)

    if isinstance(diagnostics, list):
        diagnostics.clear()
        for idx, candidate in enumerate(identity_candidates):
            blob = " ".join(
                [
                    str(candidate.get("announcement", "") or "").strip().lower(),
                    str(candidate.get("text", "") or "").strip().lower(),
                    str(candidate.get("resource_id", "") or "").strip().lower(),
                ]
            )
            width = max(1, int(candidate.get("right", 0) or 0) - int(candidate.get("left", 0) or 0))
            height = max(1, int(candidate.get("bottom", 0) or 0) - int(candidate.get("top", 0) or 0))
            oversized_penalty = 1 if screen_width > 0 and screen_height > 0 and (
                (width / max(1, screen_width) >= 0.88) and (height / max(1, screen_height) >= 0.24)
            ) else 0
            generic_profile_penalty = 1 if normalized_entry_type == "direct_select" and any(
                token in f" {blob}" for token in _DIRECT_SELECT_GENERIC_TOP_TOKENS
            ) else 0
            verify_hit_tokens = [token for token in normalized_verify_tokens if token and token in blob]
            negative_hit_tokens = [token for token in normalized_negative_tokens if token and token in blob]
            diagnostics.append(
                {
                    "rank_seed": idx + 1,
                    "label": str(candidate.get("announcement", "") or candidate.get("text", "") or "").strip(),
                    "normalized_label": blob,
                    "resource_id": str(candidate.get("resource_id", "") or "").strip(),
                    "class_name": str(candidate.get("class_name", "") or "").strip(),
                    "bounds": str(candidate.get("bounds", "") or "").strip(),
                    "visible": bool(candidate.get("visible_to_user", True)),
                    "clickable": bool(candidate.get("clickable", False)),
                    "focusable": bool(candidate.get("focusable", False)),
                    "effective_clickable": bool(candidate.get("clickable", False) or candidate.get("focusable", False)),
                    "verify_hit_tokens": verify_hit_tokens,
                    "negative_hit_tokens": negative_hit_tokens,
                    "generic_top_penalty": generic_profile_penalty,
                    "oversized_penalty": oversized_penalty,
                }
            )

    def _pick_non_boilerplate(bucket: list[dict[str, Any]], sort_key: Any, fallback_position: str) -> tuple[dict[str, Any] | None, str]:
        for candidate in sorted(bucket, key=lambda item: _candidate_sort_key(item, sort_key)):
            if not _is_boilerplate_like_candidate(candidate):
                return candidate, fallback_position
        return None, "boilerplate_like"

    if screen_width > 0:
        def _center_x(item: dict[str, Any]) -> int:
            return (int(item.get("left", 0)) + int(item.get("right", 0))) // 2

        left_bucket = [c for c in identity_candidates if _center_x(c) <= int(screen_width * 0.34)]
        if left_bucket:
            candidate, reason = _pick_non_boilerplate(
                left_bucket,
                lambda c: (int(c.get("left", 10**9)), int(c.get("top", 10**9))),
                "top_left",
            )
            if candidate:
                return candidate, reason, ""

        center_bucket = [
            c for c in identity_candidates if int(screen_width * 0.34) < _center_x(c) < int(screen_width * 0.66)
        ]
        if center_bucket:
            center_x = screen_width // 2
            candidate, reason = _pick_non_boilerplate(
                center_bucket,
                lambda c: (
                    abs(_center_x(c) - center_x),
                    int(c.get("left", 10**9)),
                ),
                "top_center",
            )
            if candidate:
                return candidate, reason, ""

        right_bucket = [c for c in identity_candidates if _center_x(c) >= int(screen_width * 0.66)]
        if right_bucket:
            candidate, reason = _pick_non_boilerplate(
                right_bucket,
                lambda c: (-int(c.get("right", -1)), int(c.get("top", 10**9))),
                "top_right",
            )
            if candidate:
                return candidate, reason, ""

    candidate, reason = _pick_non_boilerplate(
        identity_candidates,
        lambda c: (int(c.get("left", 10**9)), int(c.get("top", 10**9))),
        "top_left",
    )
    if candidate:
        return candidate, reason, ""
    return None, "", reason


def _build_verify_cfg_for_fallback(candidate: dict[str, Any]) -> dict[str, Any]:
    resource_id = str(candidate.get("resource_id", "") or "").strip()
    text = str(candidate.get("text", "") or "").strip()
    announcement = str(candidate.get("announcement", "") or "").strip()
    verify_cfg: dict[str, Any] = {"allow_resource_id_only": True, "tie_breaker": "top_left"}
    if resource_id:
        verify_cfg["resource_id_regex"] = f"^{re.escape(resource_id)}$"
    if text:
        verify_cfg["text_regex"] = f"^{re.escape(text)}$"
    elif announcement:
        verify_cfg["announcement_regex"] = f"^{re.escape(announcement)}$"
    bounds = str(candidate.get("bounds", "") or "").strip()
    if bounds:
        verify_cfg["bounds_regex"] = f"^{re.escape(bounds)}$"
    return verify_cfg


def _select_anchor_candidate(client: A11yAdbClient, dev: str, candidate: dict[str, Any]) -> tuple[bool, bool]:
    select_attempted = False
    selected = False
    resource_id = str(candidate.get("resource_id", "") or "").strip()
    if resource_id:
        select_attempted = True
        selected = client.select(
            dev=dev,
            name=f"^{re.escape(resource_id)}$",
            type_="r",
            wait_=8,
        )
    if selected:
        return True, True
    announcement = str(candidate.get("announcement", "") or "").strip()
    if announcement:
        select_attempted = True
        selected = client.select(
            dev=dev,
            name=f"^{re.escape(announcement)}$",
            type_="a",
            wait_=8,
        )
    return selected, select_attempted


def _is_anchor_verify_match(verify_match: dict[str, Any], anchor_cfg: dict[str, Any]) -> bool:
    score_threshold = int(anchor_cfg.get("score_threshold", _ANCHOR_VERIFY_SCORE_THRESHOLD) or _ANCHOR_VERIFY_SCORE_THRESHOLD)
    return bool(verify_match.get("matched")) or int(verify_match.get("score", 0) or 0) >= score_threshold


def stabilize_anchor_focus(
    client: A11yAdbClient,
    dev: str,
    anchor_cfg: dict[str, Any],
    *,
    attempt: int,
    max_retries: int,
    transition_fast_path: bool,
) -> dict[str, Any]:
    verify_rows: list[dict[str, Any]] = []
    verify_matches: list[dict[str, Any]] = []
    verify_flags: list[bool] = []
    for verify_idx in range(2):
        if verify_idx > 0:
            time.sleep(_ANCHOR_VERIFY_SETTLE_SECONDS)
        verify_row = client.collect_focus_step(
            dev=dev,
            step_index=-(attempt * 10 + verify_idx),
            move=False,
            wait_seconds=min(MAIN_STEP_WAIT_SECONDS, 0.25) if transition_fast_path else MAIN_STEP_WAIT_SECONDS,
            announcement_wait_seconds=min(MAIN_ANNOUNCEMENT_WAIT_SECONDS, 0.2)
            if transition_fast_path
            else MAIN_ANNOUNCEMENT_WAIT_SECONDS,
            focus_wait_seconds=0.8 if transition_fast_path else None,
            allow_get_focus_fallback_dump=not transition_fast_path,
            allow_step_dump=not transition_fast_path,
            get_focus_mode="fast" if transition_fast_path else "normal",
        )
        verify_rows.append(verify_row)
        verify_match = match_anchor(_extract_candidate_from_step(verify_row), anchor_cfg)
        verify_matches.append(verify_match)
        verify_flags.append(_is_anchor_verify_match(verify_match, anchor_cfg))

    verify1_matched = bool(verify_flags[0]) if verify_flags else False
    verify2_matched = bool(verify_flags[1]) if len(verify_flags) > 1 else False
    stable = verify1_matched and verify2_matched
    reason = "double_verified" if stable and attempt == 1 else "retry_success" if stable else "not_stable"
    return {
        "stable": stable,
        "reason": reason,
        "verify_rows": verify_rows,
        "verify_matches": verify_matches,
        "verify1_matched": verify1_matched,
        "verify2_matched": verify2_matched,
    }

def stabilize_anchor(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    phase: str,
    max_retries: int = 2,
    verify_reads: int = 2,
) -> dict[str, Any]:
    _ = verify_reads  # backward-compatible signature; anchor stabilization uses fixed double verification.
    anchor_cfg = _resolve_anchor_cfg(tab_cfg)
    explicit_anchor_configured = _has_explicit_anchor(tab_cfg, anchor_cfg)
    tie_breaker = str(anchor_cfg.get("tie_breaker", "top_left") or "top_left")
    stabilization_mode = str(tab_cfg.get("stabilization_mode", "anchor_then_context") or "anchor_then_context").strip().lower()
    if stabilization_mode not in _VALID_STABILIZATION_MODES:
        stabilization_mode = "anchor_then_context"
    last_verify: dict[str, Any] = {}
    last_context: dict[str, Any] = {"ok": True, "type": "none", "expected": ""}
    scenario_id = str(tab_cfg.get("scenario_id", "") or "")
    pre_nav_target = str(tab_cfg.get("pre_nav_target", "") or "")
    air_plugin_context = _is_air_plugin_context(scenario_id, pre_nav_target)
    pre_navigation = tab_cfg.get("pre_navigation", [])
    has_pre_navigation = isinstance(pre_navigation, list) and bool(pre_navigation)
    screen_context_mode = str(tab_cfg.get("screen_context_mode", "") or "").strip().lower()
    transition_fast_path = (
        phase == "scenario_start"
        and has_pre_navigation
        and screen_context_mode == "new_screen"
        and stabilization_mode == "anchor_only"
    )
    readable_only_fallback_scope = (
        phase == "scenario_start"
        and "plugin" in scenario_id.lower()
        and screen_context_mode == "new_screen"
        and stabilization_mode == "anchor_only"
    )
    plugin_fallback_scope = transition_fast_path or "plugin" in scenario_id.lower()
    start_candidate_source = "explicit_anchor"
    fallback_candidate_used = False
    fallback_candidate_label = ""
    fallback_candidate_resource_id = ""
    fallback_candidate_rejected_reason = ""
    last_verify_row: dict[str, Any] = {}
    landing_evidence = PostEntryLandingEvidence(False, "not_evaluated")

    for attempt in range(1, max_retries + 1):
        log(f"[ANCHOR][stabilize] attempt={attempt}/{max_retries} scenario='{scenario_id}'", level="DEBUG")
        dump_nodes = client.dump_tree(dev=dev)
        candidates = [
            _extract_candidate_from_node(node, index=i)
            for i, node in enumerate(dump_nodes if isinstance(dump_nodes, list) else [])
        ]
        matches: list[dict[str, Any]] = []
        best: dict[str, Any] | None = None
        fallback_position = ""
        fallback_skip_reason = ""
        active_anchor_cfg = dict(anchor_cfg)
        if explicit_anchor_configured:
            matches = [m for m in (match_anchor(c, anchor_cfg) for c in candidates) if m["matched"]]
            best = choose_best_anchor_candidate(matches, tie_breaker=tie_breaker)
        elif attempt == 1:
            log("[ANCHOR][fallback] no explicit anchor configured")

        fallback_candidate: dict[str, Any] | None = None
        fallback_diagnostics: list[dict[str, Any]] = []
        if best is None:
            if explicit_anchor_configured:
                log("[ANCHOR][fallback] explicit anchor not matched, trying top content fallback")
            fallback_candidate, fallback_position, fallback_skip_reason = _pick_top_content_fallback_candidate(
                candidates,
                entry_type=str(tab_cfg.get("entry_type", "") or ""),
                allow_readable_only_fallback=readable_only_fallback_scope,
                verify_tokens=tab_cfg.get("verify_tokens", []),
                negative_verify_tokens=tab_cfg.get("negative_verify_tokens", []),
                diagnostics=fallback_diagnostics,
            )
            if fallback_candidate:
                active_anchor_cfg = _build_verify_cfg_for_fallback(fallback_candidate)
                best = {"candidate": fallback_candidate, "score": 0, "matched": True, "matched_fields": ["fallback"]}
                start_candidate_source = f"fallback_{fallback_position}" if fallback_position else "fallback_top_content"
                fallback_candidate_used = True
                fallback_candidate_label = str(fallback_candidate.get("announcement", "") or fallback_candidate.get("text", "") or "").strip()
                fallback_candidate_resource_id = str(fallback_candidate.get("resource_id", "") or "").strip()
                log(
                    f"[ANCHOR][fallback] selected candidate label='{fallback_candidate.get('announcement', '')}' "
                    f"position='{fallback_position}'"
                )
                if plugin_fallback_scope:
                    log(f"[ANCHOR][plugin_fallback] using_top_start_candidate position='{fallback_position}'")
            else:
                if air_plugin_context:
                    focus_candidate = _select_focus_based_candidate(
                        next(
                            (
                                c
                                for c in candidates
                                if bool(c.get("visible_to_user", True))
                                and bool(
                                    c.get("accessibility_focused", False)
                                    or c.get("focused", False)
                                    or c.get("selected", False)
                                )
                            ),
                            None,
                        )
                    )
                    if focus_candidate:
                        fallback_candidate = focus_candidate
                        fallback_position = "focus"
                        active_anchor_cfg = _build_verify_cfg_for_fallback(fallback_candidate)
                        best = {"candidate": fallback_candidate, "score": 0, "matched": True, "matched_fields": ["fallback"]}
                        start_candidate_source = "fallback_focus"
                        fallback_candidate_used = True
                        fallback_candidate_label = str(
                            fallback_candidate.get("announcement", "") or fallback_candidate.get("text", "") or ""
                        ).strip()
                        fallback_candidate_resource_id = str(fallback_candidate.get("resource_id", "") or "").strip()
                        log("[ANCHOR][air] focus-based fallback accepted")
                    else:
                        top_level_candidate = next(
                            (
                                c
                                for c in sorted(
                                    candidates,
                                    key=lambda item: (int(item.get("top", 10**9)), int(item.get("left", 10**9))),
                                )
                                if bool(c.get("visible_to_user", True)) and str(c.get("bounds", "") or "").strip()
                            ),
                            None,
                        )
                        if top_level_candidate:
                            fallback_candidate = dict(top_level_candidate)
                            fallback_candidate["source"] = "top_level_fallback"
                            fallback_position = "top_level"
                            active_anchor_cfg = _build_verify_cfg_for_fallback(fallback_candidate)
                            best = {
                                "candidate": fallback_candidate,
                                "score": 0,
                                "matched": True,
                                "matched_fields": ["fallback"],
                            }
                            start_candidate_source = "fallback_top_level"
                            fallback_candidate_used = True
                            fallback_candidate_label = str(
                                fallback_candidate.get("announcement", "") or fallback_candidate.get("text", "") or ""
                            ).strip()
                            fallback_candidate_resource_id = str(fallback_candidate.get("resource_id", "") or "").strip()
                            log("[ANCHOR][air] top-level fallback accepted")
                            fallback_skip_reason = ""
                if fallback_candidate is None:
                    log("[ANCHOR][fallback] no usable fallback candidate")
                    fallback_candidate_rejected_reason = fallback_skip_reason
                    if plugin_fallback_scope and fallback_skip_reason == "boilerplate_like":
                        log("[ANCHOR][plugin_fallback] rejected candidate reason='boilerplate_like'")
                    elif plugin_fallback_scope:
                        log(f"[ANCHOR][plugin_fallback] failed reason='{fallback_skip_reason or 'no_readable_top_candidate'}'")
            entry_type = str(tab_cfg.get("entry_type", "") or "").strip().lower()
            scenario_id_l = scenario_id.strip().lower()
            if entry_type == "direct_select" and (
                scenario_id_l == "life_pet_care_plugin"
                or scenario_id_l.startswith("life_pet_care")
            ):
                for row in sorted(
                    fallback_diagnostics[:5],
                    key=lambda item: (
                        int(item.get("generic_top_penalty", 0)),
                        int(item.get("oversized_penalty", 0)),
                        int(item.get("rank_seed", 0)),
                    ),
                ):
                    selected = (
                        bool(fallback_candidate)
                        and str(row.get("resource_id", "") or "") == str(fallback_candidate.get("resource_id", "") or "")
                        and str(row.get("bounds", "") or "") == str(fallback_candidate.get("bounds", "") or "")
                    )
                    log(
                        "[ANCHOR][fallback][diagnostic] "
                        f"scenario='{scenario_id}' "
                        f"label='{row.get('label', '')}' "
                        f"normalized='{row.get('normalized_label', '')}' "
                        f"resource_id='{row.get('resource_id', '')}' "
                        f"class_name='{row.get('class_name', '')}' "
                        f"bounds='{row.get('bounds', '')}' "
                        f"visible={str(bool(row.get('visible', False))).lower()} "
                        f"clickable={str(bool(row.get('clickable', False))).lower()} "
                        f"focusable={str(bool(row.get('focusable', False))).lower()} "
                        f"effective_clickable={str(bool(row.get('effective_clickable', False))).lower()} "
                        f"verify_hits='{','.join(row.get('verify_hit_tokens', [])) or 'none'}' "
                        f"negative_hits='{','.join(row.get('negative_hit_tokens', [])) or 'none'}' "
                        f"generic_top_penalty={int(row.get('generic_top_penalty', 0))} "
                        f"oversized_penalty={int(row.get('oversized_penalty', 0))} "
                        f"selected={str(selected).lower()}"
                    )

        selected = False
        select_attempted = False
        if best:
            selected, select_attempted = _select_anchor_candidate(client, dev, best["candidate"])

        if not selected and fallback_candidate is None:
            select_attempted = True
            selected = client.select(
                dev=dev,
                name=str(tab_cfg.get("anchor_name", "") or ""),
                type_=str(tab_cfg.get("anchor_type", "a") or "a"),
                wait_=8,
            )

        verify_match: dict[str, Any] | None = None
        context_result: dict[str, Any] = {"ok": True, "type": "none", "expected": ""}
        verify_rows: list[dict[str, Any]] = []
        verify_results = stabilize_anchor_focus(
            client=client,
            dev=dev,
            anchor_cfg=active_anchor_cfg,
            attempt=attempt,
            max_retries=max_retries,
            transition_fast_path=transition_fast_path,
        )
        verify_rows = list(verify_results.get("verify_rows", []))
        if verify_rows and isinstance(verify_rows[-1], dict):
            last_verify_row = dict(verify_rows[-1])
        verify_matches = list(verify_results.get("verify_matches", []))
        if verify_matches:
            verify_match = verify_matches[-1]
        for verify_row in verify_rows:
            if stabilization_mode == "anchor_only":
                context_result = {
                    "ok": True,
                    "type": "skipped",
                    "expected": "",
                    "actual_text": "",
                    "actual_announcement": "",
                    "reason": "anchor_only_mode",
                }
                log("[CONTEXT] skipped reason='anchor_only_mode'")
            else:
                context_result = verify_context(verify_row, tab_cfg, client=client, dev=dev)
            if not context_result.get("ok"):
                break

        last_verify = verify_match or {}
        last_context = context_result
        log(
            f"[ANCHOR][{phase}] attempt={attempt}/{max_retries} selected={selected} "
            f"mode='{stabilization_mode}' "
            f"matched={bool(last_verify.get('matched'))} "
            f"context_ok={bool(last_context.get('ok'))} "
            f"scenario='{scenario_id}' "
            f"fields={last_verify.get('matched_fields', [])} "
            f"score={last_verify.get('score', 0)} "
            f"resource='{(last_verify.get('candidate') or {}).get('resource_id', '')}' "
            f"bounds='{(last_verify.get('candidate') or {}).get('bounds', '')}'",
            level="DEBUG",
        )
        if str(last_context.get("type", "")) == "selected_bottom_tab":
            expected_value = (
                str(dict(tab_cfg.get("context_verify", {}) or {}).get("announcement_regex", "") or "").strip()
                or str(dict(tab_cfg.get("context_verify", {}) or {}).get("text_regex", "") or "").strip()
            )
            log(
                f"[CONTEXT][dump] scenario='{scenario_id}' type='selected_bottom_tab' "
                f"expected='{expected_value}'",
                level="DEBUG",
            )
            selected_candidates = last_context.get("selected_candidates", [])
            log(
                f"[CONTEXT][dump] selected_candidates_count={len(selected_candidates) if isinstance(selected_candidates, list) else 0}",
                level="DEBUG",
            )
            log(f"[CONTEXT][dump] selected_candidates={selected_candidates}", level="DEBUG")
            log(f"[CONTEXT][dump] actual_selected_text='{last_context.get('actual_selected_text', '')}'", level="DEBUG")
            log(f"[CONTEXT][dump] source='{last_context.get('dump_source', 'step_cache')}'", level="DEBUG")
            log(f"[CONTEXT][dump] lazy_dump_node_count={int(last_context.get('lazy_dump_node_count', 0) or 0)}", level="DEBUG")
            log(f"[CONTEXT][dump] ok={bool(last_context.get('ok'))}", level="DEBUG")
        log(
            f"[CONTEXT] scenario='{scenario_id}' type='{last_context.get('type', 'none')}' "
            f"expected='{last_context.get('expected', '')}' "
            f"actual='{last_context.get('actual_selected_text', last_context.get('actual_announcement', last_context.get('actual_text', '')))}' "
            f"ok={bool(last_context.get('ok'))}"
        )
        verify_matched = bool(last_verify.get("matched"))
        verify_stable = bool(verify_results.get("stable"))
        verify1_matched = bool(verify_results.get("verify1_matched"))
        verify2_matched = bool(verify_results.get("verify2_matched"))
        context_ok = bool(last_context.get("ok"))
        if stabilization_mode == "anchor_only":
            success = verify_stable
        elif stabilization_mode == "tab_context":
            success = context_ok
        else:
            success = verify_stable and context_ok

        landing_evidence = PostEntryLandingEvidence(False, "not_evaluated")
        if not success and isinstance(tab_cfg.get("entry_transition_evidence"), dict):
            try:
                delayed_nodes = client.dump_tree(dev=dev)
            except Exception:
                delayed_nodes = []
            landing_evidence = evaluate_post_entry_landing_evidence(
                tab_cfg=tab_cfg,
                phase=phase,
                first_nodes=dump_nodes if isinstance(dump_nodes, list) else [],
                second_nodes=delayed_nodes if isinstance(delayed_nodes, list) else [],
                verify_rows=verify_rows,
            )
            log(
                "[ANCHOR][post_entry_evidence] "
                f"scenario='{scenario_id}' accepted={str(landing_evidence.accepted).lower()} "
                f"reason='{landing_evidence.reason}' correlation_id='{landing_evidence.correlation_id}' "
                f"root_class='{landing_evidence.root_class}' root_package='{landing_evidence.root_package}' "
                f"root_bounds='{landing_evidence.root_bounds}' identity_source='{landing_evidence.identity_source}' "
                f"identity_value='{landing_evidence.identity_value}'"
            )
            success = landing_evidence.accepted

        if landing_evidence.accepted:
            stabilize_reason = landing_evidence.reason
        elif select_attempted and not selected and not verify_stable:
            stabilize_reason = "select_failed"
        else:
            stabilize_reason = str(verify_results.get("reason", "not_stable") or "not_stable")
        log(
            f"[ANCHOR][stabilize] attempt={attempt}/{max_retries} "
            f"scenario='{scenario_id}' "
            f"select_attempted={str(select_attempted).lower()} "
            f"verify1_matched={str(verify1_matched).lower()} "
            f"verify2_matched={str(verify2_matched).lower()} "
            f"stable={str(verify_stable).lower()} "
            f"reason='{stabilize_reason}'",
            level="DEBUG",
        )

        if not verify_matched:
            log(f"[ANCHOR][{phase}] anchor mismatch scenario='{scenario_id}'")
        if not verify_stable and stabilization_mode != "tab_context":
            log(f"[ANCHOR][{phase}] anchor not stable scenario='{scenario_id}'")
        elif not context_ok:
            log(f"[ANCHOR][{phase}] context mismatch scenario='{scenario_id}'")
            log(f"[CONTEXT] verification failed scenario='{scenario_id}'")
        else:
            log(f"[CONTEXT] verification passed scenario='{scenario_id}'")

        if success:
            if landing_evidence.accepted:
                success_reason = landing_evidence.reason
            elif stabilization_mode == "tab_context":
                success_reason = "context_verified"
            elif selected:
                success_reason = "selected_and_verified"
            else:
                success_reason = "verified_without_select"
            log(
                f"[ANCHOR][{phase}] success scenario='{scenario_id}' selected={selected} "
                f"matched={verify_matched} stable={verify_stable} context_ok={context_ok} reason='{success_reason}'"
            )
            if plugin_fallback_scope and fallback_candidate_used:
                stabilized_by = "selected" if selected else "post_focus_verified"
                log(f"[ANCHOR][plugin_fallback] stabilized_by='{stabilized_by}'")
            return {
                "ok": True,
                "attempt": attempt,
                "selected": selected,
                "reason": success_reason,
                "verify": last_verify,
                "context": last_context,
                "verify_rows": verify_rows,
                "verify_row": last_verify_row,
                "candidate_count": len(matches),
                "phase": phase,
                "start_candidate_source": start_candidate_source,
                "fallback_candidate_used": fallback_candidate_used,
                "fallback_candidate_label": fallback_candidate_label,
                "fallback_candidate_resource_id": fallback_candidate_resource_id,
                "fallback_candidate_rejected_reason": fallback_candidate_rejected_reason,
                "post_entry_landing_evidence": landing_evidence.to_dict(),
            }

    return {
        "ok": False,
        "attempt": max_retries,
        "selected": False,
        "reason": "low_confidence_anchor_start",
        "verify": last_verify,
        "context": last_context,
        "verify_row": last_verify_row,
        "candidate_count": 0,
        "phase": phase,
        "start_candidate_source": start_candidate_source,
        "fallback_candidate_used": fallback_candidate_used,
        "fallback_candidate_label": fallback_candidate_label,
        "fallback_candidate_resource_id": fallback_candidate_resource_id,
        "fallback_candidate_rejected_reason": fallback_candidate_rejected_reason,
        "post_entry_landing_evidence": landing_evidence.to_dict(),
    }
