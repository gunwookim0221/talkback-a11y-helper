import re
from typing import Any


ACTIONABLE = "ACTIONABLE"
STATUS = "STATUS"
EMPTY_STATE = "EMPTY_STATE"
INSTRUCTIONAL = "INSTRUCTIONAL"
CHROME = "CHROME"
UNKNOWN = "UNKNOWN"

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


def apply_candidate_policy_diagnostics(candidate: dict[str, Any]) -> dict[str, str]:
    typed = classify_candidate_type(candidate)
    enriched = {**candidate, **typed}
    return {**typed, **recommend_candidate_policy(enriched)}


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
