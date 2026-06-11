import re
from typing import Any


ACTIONABLE = "ACTIONABLE"
STATUS = "STATUS"
EMPTY_STATE = "EMPTY_STATE"
INSTRUCTIONAL = "INSTRUCTIONAL"
CHROME = "CHROME"
UNKNOWN = "UNKNOWN"

CTA = "CTA"
NAV_TILE = "NAV_TILE"
SERVICE_TILE = "SERVICE_TILE"
CONTENT_CARD = "CONTENT_CARD"
SCREEN_TITLE = "SCREEN_TITLE"
ONBOARDING = "ONBOARDING"
PROMOTION_OR_SERVICE_CARD = "PROMOTION_OR_SERVICE_CARD"
STATUS_METRIC = "STATUS_METRIC"
STATUS_LABEL = "STATUS_LABEL"
INSTRUCTIONAL_STATUS = "INSTRUCTIONAL_STATUS"
LOW_VALUE_LABEL = "LOW_VALUE_LABEL"
UNKNOWN_SUBTYPE = "UNKNOWN"

KEEP = "KEEP"
REVIEW = "REVIEW"
EXCLUDE = "EXCLUDE"

_LOCAL_TAB_LABELS = {"controls", "history", "routines"}
_CHROME_LABELS = {"navigate up", "more options"}
_REVIEW_TITLE_LABELS = {"smartthings plugin"}
_ACTION_REVIEW_LABELS = {"add routine"}
_STATUS_LABELS = {"battery", "motion sensor", "motion detected", "no motion"}
_EMPTY_STATE_PREFIXES = ("no ", "empty ")
_INSTRUCTION_PATTERNS = (
    re.compile(r"\bexample:", re.IGNORECASE),
    re.compile(r"\bevery day\b", re.IGNORECASE),
)
_VALUE_PATTERNS = (
    re.compile(r"^\d+%$"),
    re.compile(r"^-?\d+(?:[\.,]\d+)?\s*(?:°c|℃|°f|℉)$", re.IGNORECASE),
)
_TIME_OR_NUMBER_PATTERNS = (
    re.compile(r"^\d+$"),
    re.compile(r"^\d{1,2}:\d{2}$"),
)
_UNIT_LABELS = {"%", "/", "h", "m", "am", "pm"}
_CTA_LABELS = {
    "add family member",
    "connect home appliances",
    "view information",
    "view profile",
}
_NAV_TILE_LABELS = {
    "activitybutton",
    "eventsbutton",
    "locationbutton",
    "mobile usagebutton",
}
_SERVICE_TILE_LABELS = {
    "device care",
}
_ONBOARDING_LABELS = {
    "add home information",
    "usage guide",
    "weather information, icon. add home information",
}
_PROMOTION_LABELS = {
    "samsung care+",
    "smart forward, update your device and check out the new features of home life service.",
}
_SCREEN_TITLE_LABELS = {
    "family care",
    "home care",
    "smartthings home care",
}
_STATUS_LABELS_LIFE = {
    "active now",
    "activity",
    "avg (week)",
    "device usage",
    "events",
    "first activity",
    "latest activity",
    "location",
    "me",
    "mobile usage",
    "steps",
    "today",
}


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _normalize_resource_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    if ":" in normalized:
        normalized = normalized.rsplit(":", 1)[-1]
    return normalized


def _candidate_sets(candidate: dict[str, Any]) -> tuple[set[str], set[str], set[str], set[str]]:
    resource_ids = {
        _normalize_resource_id(resource_id)
        for resource_id in candidate.get("resource_ids", [])
        if str(resource_id or "").strip()
    }
    classes = {str(class_name or "").strip().lower() for class_name in candidate.get("classes", [])}
    focusable_values = {str(value or "").strip().lower() for value in candidate.get("focusable_values", [])}
    clickable_values = {str(value or "").strip().lower() for value in candidate.get("clickable_values", [])}
    return resource_ids, classes, focusable_values, clickable_values


def classify_candidate_type(candidate: dict[str, Any]) -> dict[str, str]:
    label = str(candidate.get("label", "") or "").strip()
    normalized_label = _normalize_label(label)
    resource_ids, classes, focusable_values, clickable_values = _candidate_sets(candidate)

    if normalized_label in _CHROME_LABELS or resource_ids.intersection({"back", "more"}):
        return {"candidate_type": CHROME, "candidate_type_reason": "common_shell_or_toolbar_control"}

    if normalized_label in _LOCAL_TAB_LABELS:
        return {"candidate_type": ACTIONABLE, "candidate_type_reason": "local_tab_control"}

    if normalized_label in _ACTION_REVIEW_LABELS:
        return {"candidate_type": ACTIONABLE, "candidate_type_reason": "toolbar_or_secondary_action"}

    if any(pattern.search(label) for pattern in _INSTRUCTION_PATTERNS):
        return {"candidate_type": INSTRUCTIONAL, "candidate_type_reason": "example_or_instructional_text"}

    if normalized_label.startswith(_EMPTY_STATE_PREFIXES):
        return {"candidate_type": EMPTY_STATE, "candidate_type_reason": "empty_state_or_absence_message"}

    if normalized_label in _STATUS_LABELS or any(pattern.search(label) for pattern in _VALUE_PATTERNS):
        return {"candidate_type": STATUS, "candidate_type_reason": "device_state_or_sensor_value"}

    if "true" in clickable_values or any("button" in class_name for class_name in classes):
        return {"candidate_type": ACTIONABLE, "candidate_type_reason": "clickable_or_button_node"}

    if "false" in focusable_values and any("textview" in class_name for class_name in classes):
        return {"candidate_type": STATUS, "candidate_type_reason": "static_text_or_status_node"}

    return {"candidate_type": UNKNOWN, "candidate_type_reason": "policy_not_classified"}


def recommend_candidate_policy(candidate: dict[str, Any]) -> dict[str, str]:
    candidate_type = str(candidate.get("candidate_type", "") or "")
    classification = str(candidate.get("classification", REVIEW) or REVIEW).upper()
    normalized_label = _normalize_label(str(candidate.get("label", "") or ""))

    if candidate_type == CHROME:
        recommendation = EXCLUDE
        reason = "chrome_candidates_should_stay_out_of_coverage_denominator"
    elif candidate_type in {EMPTY_STATE, INSTRUCTIONAL}:
        recommendation = REVIEW
        reason = "static_or_instructional_text_needs_policy_review_before_denominator"
    elif normalized_label in _ACTION_REVIEW_LABELS:
        recommendation = REVIEW
        reason = "secondary_action_may_be_toolbar_chrome_not_core_plugin_content"
    elif normalized_label in _REVIEW_TITLE_LABELS:
        recommendation = REVIEW
        reason = "plugin_or_shell_title_is_ambiguous"
    elif candidate_type in {ACTIONABLE, STATUS}:
        recommendation = KEEP
        reason = "candidate_type_is_initially_valid_for_traversal_coverage"
    else:
        recommendation = classification if classification in {KEEP, REVIEW, EXCLUDE} else REVIEW
        reason = "no_policy_override_recommended"

    return {
        "policy_recommendation": recommendation,
        "policy_recommendation_reason": reason,
    }


def classify_candidate_subtype(candidate: dict[str, Any]) -> dict[str, str]:
    label = str(candidate.get("label", "") or "").strip()
    normalized_label = _normalize_label(label)
    resource_ids, classes, _focusable_values, _clickable_values = _candidate_sets(candidate)
    candidate_type = str(candidate.get("candidate_type", UNKNOWN) or UNKNOWN)

    if candidate_type == CHROME:
        return {"candidate_subtype": CHROME, "candidate_subtype_reason": "shell_or_toolbar_chrome"}

    if normalized_label == ",":
        return {"candidate_subtype": LOW_VALUE_LABEL, "candidate_subtype_reason": "punctuation_only_label"}

    if normalized_label in _CTA_LABELS or any("invite_member" in resource_id for resource_id in resource_ids):
        return {"candidate_subtype": CTA, "candidate_subtype_reason": "life_primary_action_or_profile_cta"}

    if normalized_label in _NAV_TILE_LABELS or normalized_label.endswith("button"):
        return {"candidate_subtype": NAV_TILE, "candidate_subtype_reason": "life_navigation_tile_button"}

    if normalized_label in _PROMOTION_LABELS:
        return {
            "candidate_subtype": PROMOTION_OR_SERVICE_CARD,
            "candidate_subtype_reason": "life_promotional_or_service_card",
        }

    if normalized_label in _ONBOARDING_LABELS:
        return {"candidate_subtype": ONBOARDING, "candidate_subtype_reason": "life_setup_or_guide_entry"}

    if normalized_label in _SERVICE_TILE_LABELS:
        return {"candidate_subtype": SERVICE_TILE, "candidate_subtype_reason": "life_service_dashboard_tile"}

    if normalized_label in _SCREEN_TITLE_LABELS:
        return {"candidate_subtype": SCREEN_TITLE, "candidate_subtype_reason": "life_screen_or_service_title"}

    if "self-diagnosis" in normalized_label or "how to " in normalized_label:
        return {"candidate_subtype": CONTENT_CARD, "candidate_subtype_reason": "life_article_or_content_card"}

    if normalized_label in _UNIT_LABELS or any(pattern.search(label) for pattern in _TIME_OR_NUMBER_PATTERNS):
        return {"candidate_subtype": STATUS_METRIC, "candidate_subtype_reason": "life_numeric_or_unit_metric"}

    if normalized_label in _STATUS_LABELS_LIFE:
        return {"candidate_subtype": STATUS_LABEL, "candidate_subtype_reason": "life_status_or_dashboard_label"}

    if candidate_type == STATUS and any("textview" in class_name for class_name in classes):
        return {"candidate_subtype": STATUS_LABEL, "candidate_subtype_reason": "static_status_text"}

    if candidate_type == INSTRUCTIONAL:
        return {"candidate_subtype": INSTRUCTIONAL_STATUS, "candidate_subtype_reason": "instructional_or_example_text"}

    return {"candidate_subtype": UNKNOWN_SUBTYPE, "candidate_subtype_reason": "subtype_not_classified"}


def apply_candidate_policy_diagnostics(candidate: dict[str, Any]) -> dict[str, str]:
    typed = classify_candidate_type(candidate)
    enriched = {**candidate, **typed}
    policy = recommend_candidate_policy(enriched)
    return {**typed, **classify_candidate_subtype({**enriched, **policy}), **policy}


def summarize_candidate_types(candidates: list[dict[str, Any]]) -> dict[str, int]:
    summary = {ACTIONABLE: 0, STATUS: 0, EMPTY_STATE: 0, INSTRUCTIONAL: 0, CHROME: 0, UNKNOWN: 0}
    for candidate in candidates:
        candidate_type = str(candidate.get("candidate_type", UNKNOWN) or UNKNOWN)
        summary[candidate_type] = summary.get(candidate_type, 0) + 1
    return summary


def sample_candidates_by_type(candidates: list[dict[str, Any]], candidate_type: str, limit: int = 10) -> str:
    labels = [
        str(candidate.get("label", "") or "").strip()
        for candidate in candidates
        if candidate.get("candidate_type") == candidate_type and str(candidate.get("label", "") or "").strip()
    ]
    return ", ".join(sorted(labels)[:limit])


def summarize_candidate_subtypes(candidates: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        CTA: 0,
        NAV_TILE: 0,
        SERVICE_TILE: 0,
        CONTENT_CARD: 0,
        SCREEN_TITLE: 0,
        ONBOARDING: 0,
        PROMOTION_OR_SERVICE_CARD: 0,
        STATUS_METRIC: 0,
        STATUS_LABEL: 0,
        INSTRUCTIONAL_STATUS: 0,
        LOW_VALUE_LABEL: 0,
        CHROME: 0,
        UNKNOWN_SUBTYPE: 0,
    }
    for candidate in candidates:
        subtype = str(candidate.get("candidate_subtype", UNKNOWN_SUBTYPE) or UNKNOWN_SUBTYPE)
        summary[subtype] = summary.get(subtype, 0) + 1
    return summary


def sample_candidates_by_subtype(candidates: list[dict[str, Any]], subtype: str, limit: int = 10) -> str:
    labels = [
        str(candidate.get("label", "") or "").strip()
        for candidate in candidates
        if candidate.get("candidate_subtype") == subtype and str(candidate.get("label", "") or "").strip()
    ]
    return ", ".join(sorted(labels)[:limit])


def summarize_policy_recommendations(candidates: list[dict[str, Any]]) -> dict[str, int]:
    summary = {KEEP: 0, REVIEW: 0, EXCLUDE: 0}
    for candidate in candidates:
        recommendation = str(candidate.get("policy_recommendation", REVIEW) or REVIEW)
        summary[recommendation] = summary.get(recommendation, 0) + 1
    return summary


def policy_recommendation_map(candidates: list[dict[str, Any]], limit: int = 20) -> dict[str, str]:
    ordered = sorted(candidates, key=lambda candidate: str(candidate.get("label", "") or "").lower())[:limit]
    return {
        str(candidate.get("label", "") or "").strip(): str(candidate.get("policy_recommendation", REVIEW) or REVIEW)
        for candidate in ordered
        if str(candidate.get("label", "") or "").strip()
    }


def policy_examples(candidates: list[dict[str, Any]], limit: int = 10) -> str:
    ordered = sorted(candidates, key=lambda candidate: str(candidate.get("label", "") or "").lower())[:limit]
    return " | ".join(
        f"{candidate.get('label', '')}: {candidate.get('candidate_type', UNKNOWN)}"
        f" -> {candidate.get('policy_recommendation', REVIEW)}"
        f" ({candidate.get('policy_recommendation_reason', '')})"
        for candidate in ordered
    )


def subtype_examples(candidates: list[dict[str, Any]], limit: int = 12) -> str:
    ordered = sorted(candidates, key=lambda candidate: str(candidate.get("label", "") or "").lower())[:limit]
    return " | ".join(
        f"{candidate.get('label', '')}: {candidate.get('candidate_type', UNKNOWN)}"
        f"/{candidate.get('candidate_subtype', UNKNOWN_SUBTYPE)}"
        f" ({candidate.get('candidate_subtype_reason', '')})"
        for candidate in ordered
    )


def life_taxonomy_summary(candidates: list[dict[str, Any]]) -> str:
    subtype_summary = summarize_candidate_subtypes(candidates)
    meaningful = [
        f"{subtype}: {count}"
        for subtype, count in sorted(subtype_summary.items())
        if count
    ]
    return ", ".join(meaningful)
