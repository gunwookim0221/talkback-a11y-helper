import re
from typing import Any


COVERAGE_POLICY = "denominator=KEEP_ONLY; matching=normalized_exact; verdict=diagnostic_only"
_IGNORED_TAB_NAMES = {"", "entry", "unknown"}


def normalize_coverage_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _label_sample(values: set[str], limit: int = 10) -> str:
    return ", ".join(sorted(str(value) for value in values if str(value).strip())[:limit])


def _missing_reason(candidate: dict[str, Any], traversal_labels: set[str]) -> str:
    label = str(candidate.get("label", "") or "").strip()
    normalized_label = normalize_coverage_label(label)
    traversal_norm_to_label = {
        normalize_coverage_label(traversal_label): traversal_label
        for traversal_label in traversal_labels
        if str(traversal_label or "").strip()
    }
    containing_labels = [
        traversal_label
        for normalized_traversal, traversal_label in traversal_norm_to_label.items()
        if normalized_label and normalized_label in normalized_traversal and normalized_label != normalized_traversal
    ]
    if containing_labels:
        return f"matching_mismatch_contained_in_traversal:{sorted(containing_labels)[0]}"

    classes = {str(class_name or "").strip().lower() for class_name in candidate.get("classes", [])}
    resource_ids = {str(resource_id or "").strip() for resource_id in candidate.get("resource_ids", [])}
    focusable_values = {str(value or "").strip().lower() for value in candidate.get("focusable_values", [])}
    clickable_values = {str(value or "").strip().lower() for value in candidate.get("clickable_values", [])}

    if "true" in clickable_values or any("button" in class_name for class_name in classes) or resource_ids:
        return "xml_only_actionable_candidate"
    if "false" in focusable_values and any("textview" in class_name for class_name in classes):
        return "xml_only_static_text_or_status"
    return "xml_only"


def _missing_reason_sample(missing_labels: set[str], candidates_by_label: dict[str, dict[str, Any]], traversal_labels: set[str]) -> str:
    reasons = []
    for label in sorted(missing_labels)[:10]:
        candidate = candidates_by_label.get(label, {"label": label})
        reasons.append(f"{label}: {_missing_reason(candidate, traversal_labels)}")
    return " | ".join(reasons)


def _traversal_labels_by_tab(tab_stats: dict[str, Any]) -> dict[str, set[str]]:
    labels_by_tab: dict[str, set[str]] = {}
    for tab_name, stats in (tab_stats or {}).items():
        if not isinstance(stats, dict):
            continue
        labels = {
            str(label or "").strip()
            for label in stats.get("visible_labels_set", set())
            if str(label or "").strip()
        }
        labels_by_tab[str(tab_name or "").strip()] = labels
    return labels_by_tab


def calculate_xml_coverage(merged_candidates: list[dict[str, Any]], tab_stats: dict[str, Any]) -> dict[str, Any]:
    keep_candidates = [
        candidate
        for candidate in merged_candidates
        if str(candidate.get("classification", "") or "").strip().upper() == "KEEP"
        and str(candidate.get("label", "") or "").strip()
    ]
    candidates_by_label = {str(candidate.get("label", "") or "").strip(): candidate for candidate in keep_candidates}
    denominator_labels = {str(candidate.get("label", "") or "").strip() for candidate in keep_candidates}
    denominator_norm_to_label = {normalize_coverage_label(label): label for label in denominator_labels}

    labels_by_tab = _traversal_labels_by_tab(tab_stats)
    traversal_labels = set().union(*labels_by_tab.values()) if labels_by_tab else set()
    traversal_norms = {normalize_coverage_label(label) for label in traversal_labels}

    matched_norms = set(denominator_norm_to_label).intersection(traversal_norms)
    matched_labels = {denominator_norm_to_label[norm] for norm in matched_norms}
    missing_labels = set(denominator_labels) - matched_labels
    extra_traversal_labels = {
        label
        for label in traversal_labels
        if normalize_coverage_label(label) not in set(denominator_norm_to_label)
    }

    denominator_count = len(denominator_labels)
    matched_count = len(matched_labels)
    coverage_percent = round((matched_count / denominator_count) * 100, 1) if denominator_count else 0.0

    coverage_by_tab = {}
    for candidate in keep_candidates:
        label = str(candidate.get("label", "") or "").strip()
        if not label:
            continue
        for tab_name in candidate.get("tabs", []):
            normalized_tab_name = str(tab_name or "").strip()
            if normalized_tab_name.lower() in _IGNORED_TAB_NAMES:
                continue
            tab_bucket = coverage_by_tab.setdefault(
                normalized_tab_name,
                {"_denominator_labels": set(), "_matched_labels": set()},
            )
            tab_bucket["_denominator_labels"].add(label)
            tab_labels = labels_by_tab.get(normalized_tab_name, set())
            tab_norms = {normalize_coverage_label(tab_label) for tab_label in tab_labels}
            if normalize_coverage_label(label) in tab_norms:
                tab_bucket["_matched_labels"].add(label)

    formatted_by_tab = {}
    for tab_name, bucket in sorted(coverage_by_tab.items()):
        tab_denominator = set(bucket["_denominator_labels"])
        tab_matched = set(bucket["_matched_labels"])
        tab_missing = tab_denominator - tab_matched
        tab_denominator_count = len(tab_denominator)
        tab_matched_count = len(tab_matched)
        formatted_by_tab[tab_name] = {
            "denominator": tab_denominator_count,
            "matched": tab_matched_count,
            "missing": len(tab_missing),
            "percent": round((tab_matched_count / tab_denominator_count) * 100, 1)
            if tab_denominator_count
            else 0.0,
            "matched_labels_sample": _label_sample(tab_matched),
            "missing_labels_sample": _label_sample(tab_missing),
        }

    return {
        "coverage_denominator_count": denominator_count,
        "coverage_matched_count": matched_count,
        "coverage_missing_count": len(missing_labels),
        "coverage_percent": coverage_percent,
        "coverage_matched_labels_sample": _label_sample(matched_labels),
        "coverage_missing_labels_sample": _label_sample(missing_labels),
        "coverage_missing_reason_sample": _missing_reason_sample(missing_labels, candidates_by_label, traversal_labels),
        "coverage_extra_traversal_labels_sample": _label_sample(extra_traversal_labels),
        "coverage_policy": COVERAGE_POLICY,
        "coverage_by_tab": formatted_by_tab,
    }
