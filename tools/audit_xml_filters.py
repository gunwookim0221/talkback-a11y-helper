import re
from typing import Any


KEEP = "KEEP"
REVIEW = "REVIEW"
EXCLUDE = "EXCLUDE"


_EXCLUDE_EXACT_LABELS = {
    "navigate up",
    "more options",
}
_EXCLUDE_RESOURCE_IDS = {
    "back",
    "more",
}
_KEEP_EXACT_LABELS = {
    "controls",
    "routines",
    "history",
    "battery",
    "motion sensor",
    "motion detected",
    "no motion",
    "add routine",
    "no history",
}
_KEEP_VALUE_PATTERNS = (
    re.compile(r"^\d+%$"),
    re.compile(r"^-?\d+(?:[\.,]\d+)?\s*(?:°c|℃|°f|℉)$", re.IGNORECASE),
)
_KEEP_CONTENT_PATTERNS = (
    re.compile(r"\bnotification", re.IGNORECASE),
    re.compile(r"\bstatus\b", re.IGNORECASE),
)
_REVIEW_EXACT_LABELS = {
    "smartthings plugin",
}
_REVIEW_CONTENT_PATTERNS = (
    re.compile(r"\bexample:", re.IGNORECASE),
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


def classify_xml_candidate(candidate: dict[str, Any]) -> dict[str, str]:
    label = str(candidate.get("label", "") or "").strip()
    normalized_label = _normalize_label(label)
    resource_ids = [
        _normalize_resource_id(resource_id)
        for resource_id in candidate.get("resource_ids", [])
        if str(resource_id or "").strip()
    ]
    classes = [str(class_name or "").strip().lower() for class_name in candidate.get("classes", [])]

    if normalized_label in _EXCLUDE_EXACT_LABELS:
        return {
            "classification": EXCLUDE,
            "classification_reason": "common_shell_label",
            "classification_rule": "exclude_exact_label",
        }
    if any(resource_id in _EXCLUDE_RESOURCE_IDS for resource_id in resource_ids):
        return {
            "classification": EXCLUDE,
            "classification_reason": "common_shell_resource",
            "classification_rule": "exclude_resource_id",
        }
    if any("systemui" in resource_id for resource_id in resource_ids) or any("systemui" in class_name for class_name in classes):
        return {
            "classification": EXCLUDE,
            "classification_reason": "android_system_chrome",
            "classification_rule": "exclude_systemui",
        }

    if normalized_label in _REVIEW_EXACT_LABELS:
        return {
            "classification": REVIEW,
            "classification_reason": "ambiguous_shell_or_plugin_title",
            "classification_rule": "review_exact_label",
        }
    if any(pattern.search(label) for pattern in _REVIEW_CONTENT_PATTERNS):
        return {
            "classification": REVIEW,
            "classification_reason": "instructional_or_example_text",
            "classification_rule": "review_content_pattern",
        }

    if normalized_label in _KEEP_EXACT_LABELS:
        return {
            "classification": KEEP,
            "classification_reason": "known_plugin_or_local_tab_label",
            "classification_rule": "keep_exact_label",
        }
    if any(pattern.search(label) for pattern in _KEEP_VALUE_PATTERNS):
        return {
            "classification": KEEP,
            "classification_reason": "sensor_value_label",
            "classification_rule": "keep_value_pattern",
        }
    if any(pattern.search(label) for pattern in _KEEP_CONTENT_PATTERNS):
        return {
            "classification": KEEP,
            "classification_reason": "plugin_content_pattern",
            "classification_rule": "keep_content_pattern",
        }

    return {
        "classification": REVIEW,
        "classification_reason": "unclassified_candidate",
        "classification_rule": "default_review",
    }


def summarize_candidate_classifications(candidates: list[dict[str, Any]]) -> dict[str, int]:
    summary = {KEEP: 0, REVIEW: 0, EXCLUDE: 0}
    for candidate in candidates:
        classification = str(candidate.get("classification", REVIEW) or REVIEW)
        summary[classification] = summary.get(classification, 0) + 1
    return summary


def sample_candidates_by_classification(
    candidates: list[dict[str, Any]],
    classification: str,
    limit: int = 10,
) -> str:
    labels = [
        str(candidate.get("label", "") or "").strip()
        for candidate in candidates
        if candidate.get("classification") == classification and str(candidate.get("label", "") or "").strip()
    ]
    return ", ".join(sorted(labels)[:limit])


def classification_examples(candidates: list[dict[str, Any]], limit: int = 10) -> str:
    ordered = sorted(candidates, key=lambda candidate: str(candidate.get("label", "") or "").lower())[:limit]
    return " | ".join(
        f"{candidate.get('label', '')}: {candidate.get('classification', REVIEW)}"
        f" ({candidate.get('classification_reason', '')})"
        for candidate in ordered
    )
