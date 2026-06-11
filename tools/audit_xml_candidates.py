import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict

from tools.audit_xml_filters import (
    classification_examples,
    classify_xml_candidate,
    sample_candidates_by_classification,
    summarize_candidate_classifications,
)
from tools.audit_xml_policy import (
    ACTIONABLE,
    CHROME,
    CONTENT_CARD,
    CTA,
    EMPTY_STATE,
    INSTRUCTIONAL,
    INSTRUCTIONAL_STATUS,
    LOW_VALUE_LABEL,
    NAV_TILE,
    ONBOARDING,
    PROMOTION_OR_SERVICE_CARD,
    SCREEN_TITLE,
    SERVICE_TILE,
    STATUS,
    STATUS_LABEL,
    STATUS_METRIC,
    UNKNOWN,
    apply_candidate_policy_diagnostics,
    life_taxonomy_summary,
    policy_examples,
    policy_recommendation_map,
    sample_candidates_by_type,
    sample_candidates_by_subtype,
    summarize_candidate_types,
    summarize_candidate_subtypes,
    summarize_policy_recommendations,
    subtype_examples,
)


EXCLUDE_RULE_TODO_LABELS = (
    "Navigate up",
    "More options",
    "SmartThings Plugin",
)
EXCLUDE_RULE_TODO_NOTE = (
    "Phase 2 does not filter candidates. Review common shell/system labels, "
    "hidden containers, TalkBack overlays, and non-verification UI before Phase 3."
)


def sample_values(values, limit: int = 10) -> str:
    return ", ".join(sorted(str(v) for v in values if str(v).strip())[:limit])


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _infer_tab_from_dump_name(xml_file: Path, current_tab: str) -> tuple[str, str]:
    stem = xml_file.stem
    match = re.search(r"(?:local_tab_transition|after_scroll)_([^_].*)$", stem)
    if match:
        tab_name = match.group(1).replace("_", " ").strip()
        if tab_name:
            return tab_name, tab_name
    if "entry" in stem:
        return "entry", current_tab
    if "viewport_exhausted" in stem:
        return current_tab or "unknown", current_tab
    return current_tab or "unknown", current_tab


def _candidate_source_summary(merged_candidates: list[dict[str, Any]]) -> str:
    if not merged_candidates:
        return ""
    top = sorted(
        merged_candidates,
        key=lambda candidate: (-int(candidate.get("xml_dump_count", 0) or 0), str(candidate.get("label", ""))),
    )[:10]
    return " | ".join(
        f"{candidate.get('label', '')} ({candidate.get('xml_dump_count', 0)} dumps; "
        f"{','.join(candidate.get('tabs', [])) or 'unknown'})"
        for candidate in top
    )


def extract_xml_candidates(xml_dir: Path | None) -> Dict[str, Any]:
    node_candidates_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    merged_candidates_by_key: dict[str, dict[str, Any]] = {}
    unique_labels = set()

    if not xml_dir or not xml_dir.exists():
        return {
            "xml_diagnostic_status": "xml_missing",
            "xml_dump_count": 0,
            "xml_candidate_count": 0,
            "xml_unique_label_count": 0,
            "xml_unique_labels": unique_labels,
            "xml_unique_labels_sample": "",
            "xml_candidates": [],
            "merged_candidate_count": 0,
            "merged_candidates": [],
            "candidate_tab_distribution": "",
            "candidate_source_summary": "",
            "candidate_exclusion_todo": EXCLUDE_RULE_TODO_NOTE,
            "candidate_classification_summary": {"KEEP": 0, "REVIEW": 0, "EXCLUDE": 0},
            "keep_candidates_sample": "",
            "review_candidates_sample": "",
            "exclude_candidates_sample": "",
            "candidate_classification_examples": "",
            "candidate_type_summary": {
                ACTIONABLE: 0,
                STATUS: 0,
                EMPTY_STATE: 0,
                INSTRUCTIONAL: 0,
                CHROME: 0,
                UNKNOWN: 0,
            },
            "candidate_subtype_summary": {},
            "candidate_subtype_examples": "",
            "life_taxonomy_summary": "",
            "cta_candidates_sample": "",
            "nav_tile_candidates_sample": "",
            "service_tile_candidates_sample": "",
            "content_card_candidates_sample": "",
            "screen_title_candidates_sample": "",
            "onboarding_candidates_sample": "",
            "promotion_or_service_card_candidates_sample": "",
            "status_metric_candidates_sample": "",
            "status_label_candidates_sample": "",
            "instructional_status_candidates_sample": "",
            "low_value_label_candidates_sample": "",
            "actionable_candidates_sample": "",
            "status_candidates_sample": "",
            "empty_state_candidates_sample": "",
            "instructional_candidates_sample": "",
            "chrome_candidates_sample": "",
            "unknown_candidates_sample": "",
            "candidate_policy_recommendations": {},
            "candidate_policy_recommendation_summary": {"KEEP": 0, "REVIEW": 0, "EXCLUDE": 0},
            "candidate_policy_examples": "",
            "hypothetical_denominator_count": 0,
            "hypothetical_denominator_delta": 0,
        }

    xml_files = sorted(xml_dir.glob("*.xml"))
    if not xml_files:
        return {
            "xml_diagnostic_status": "xml_present_empty",
            "xml_dump_count": 0,
            "xml_candidate_count": 0,
            "xml_unique_label_count": 0,
            "xml_unique_labels": unique_labels,
            "xml_unique_labels_sample": "",
            "xml_candidates": [],
            "merged_candidate_count": 0,
            "merged_candidates": [],
            "candidate_tab_distribution": "",
            "candidate_source_summary": "",
            "candidate_exclusion_todo": EXCLUDE_RULE_TODO_NOTE,
            "candidate_classification_summary": {"KEEP": 0, "REVIEW": 0, "EXCLUDE": 0},
            "keep_candidates_sample": "",
            "review_candidates_sample": "",
            "exclude_candidates_sample": "",
            "candidate_classification_examples": "",
            "candidate_type_summary": {
                ACTIONABLE: 0,
                STATUS: 0,
                EMPTY_STATE: 0,
                INSTRUCTIONAL: 0,
                CHROME: 0,
                UNKNOWN: 0,
            },
            "candidate_subtype_summary": {},
            "candidate_subtype_examples": "",
            "life_taxonomy_summary": "",
            "cta_candidates_sample": "",
            "nav_tile_candidates_sample": "",
            "service_tile_candidates_sample": "",
            "content_card_candidates_sample": "",
            "screen_title_candidates_sample": "",
            "onboarding_candidates_sample": "",
            "promotion_or_service_card_candidates_sample": "",
            "status_metric_candidates_sample": "",
            "status_label_candidates_sample": "",
            "instructional_status_candidates_sample": "",
            "low_value_label_candidates_sample": "",
            "actionable_candidates_sample": "",
            "status_candidates_sample": "",
            "empty_state_candidates_sample": "",
            "instructional_candidates_sample": "",
            "chrome_candidates_sample": "",
            "unknown_candidates_sample": "",
            "candidate_policy_recommendations": {},
            "candidate_policy_recommendation_summary": {"KEEP": 0, "REVIEW": 0, "EXCLUDE": 0},
            "candidate_policy_examples": "",
            "hypothetical_denominator_count": 0,
            "hypothetical_denominator_delta": 0,
        }

    current_tab = ""
    for xml_file in xml_files:
        inferred_tab, current_tab = _infer_tab_from_dump_name(xml_file, current_tab)
        try:
            tree = ET.parse(xml_file)
        except Exception as e:
            logging.warning(f"Failed to parse XML {xml_file}: {e}")
            continue

        labels_seen_in_dump = set()
        for node in tree.getroot().iter():
            text = node.get("text", "").strip()
            desc = node.get("content-desc", "").strip()
            rid = node.get("resource-id", "").strip()
            class_name = node.get("class", "").strip()
            bounds = node.get("bounds", "").strip()
            pkg = node.get("package", "").strip()
            focusable = node.get("focusable", "").strip().lower()
            clickable = node.get("clickable", "").strip().lower()

            if pkg and pkg != "com.samsung.android.oneconnect":
                continue
            if not bounds or bounds == "[0,0][0,0]":
                continue
            if not text and not desc and not rid:
                continue

            label = desc or text
            node_key = (label, rid, class_name, bounds)
            node_candidate = node_candidates_by_key.setdefault(
                node_key,
                {
                    "text": text,
                    "content_desc": desc,
                    "resource_id": rid,
                    "class": class_name,
                    "bounds": bounds,
                    "focusable": focusable,
                    "clickable": clickable,
                    "label": label,
                    "tabs": set(),
                    "dump_files": set(),
                },
            )
            node_candidate["tabs"].add(inferred_tab)
            node_candidate["dump_files"].add(xml_file.name)

            if not label:
                continue

            unique_labels.add(label)
            label_key = _normalize_label(label)
            labels_seen_in_dump.add(label_key)
            merged_candidate = merged_candidates_by_key.setdefault(
                label_key,
                {
                    "label": label,
                    "tabs": set(),
                    "dump_files": set(),
                    "resource_ids": set(),
                    "classes": set(),
                    "bounds": set(),
                    "focusable_values": set(),
                    "clickable_values": set(),
                },
            )
            merged_candidate["tabs"].add(inferred_tab)
            merged_candidate["dump_files"].add(xml_file.name)
            if rid:
                merged_candidate["resource_ids"].add(rid)
            if class_name:
                merged_candidate["classes"].add(class_name)
            if bounds:
                merged_candidate["bounds"].add(bounds)
            if focusable:
                merged_candidate["focusable_values"].add(focusable)
            if clickable:
                merged_candidate["clickable_values"].add(clickable)

        for label_key in labels_seen_in_dump:
            merged_candidates_by_key[label_key].setdefault("xml_dump_count", 0)
            merged_candidates_by_key[label_key]["xml_dump_count"] += 1

    xml_candidates = [
        {
            **candidate,
            "tabs": sorted(candidate["tabs"]),
            "dump_files": sorted(candidate["dump_files"]),
            "xml_dump_count": len(candidate["dump_files"]),
        }
        for candidate in node_candidates_by_key.values()
    ]
    merged_candidates = [
        {
            **candidate,
            "tabs": sorted(candidate["tabs"]),
            "dump_files": sorted(candidate["dump_files"]),
            "resource_ids": sorted(candidate["resource_ids"]),
            "classes": sorted(candidate["classes"]),
            "bounds": sorted(candidate["bounds"]),
            "focusable_values": sorted(candidate["focusable_values"]),
            "clickable_values": sorted(candidate["clickable_values"]),
            "xml_dump_count": int(candidate.get("xml_dump_count", 0) or 0),
        }
        for candidate in merged_candidates_by_key.values()
    ]
    for candidate in merged_candidates:
        candidate.update(classify_xml_candidate(candidate))
        candidate.update(apply_candidate_policy_diagnostics(candidate))
    merged_candidates = sorted(merged_candidates, key=lambda candidate: str(candidate.get("label", "")).lower())
    classification_summary = summarize_candidate_classifications(merged_candidates)
    policy_summary = summarize_policy_recommendations(merged_candidates)

    tab_counts: dict[str, int] = {}
    for candidate in merged_candidates:
        for tab_name in candidate.get("tabs", []):
            tab_counts[tab_name] = tab_counts.get(tab_name, 0) + 1

    return {
        "xml_diagnostic_status": "xml_present_parsed",
        "xml_dump_count": len(xml_files),
        "xml_candidate_count": len(node_candidates_by_key),
        "xml_unique_label_count": len(unique_labels),
        "xml_unique_labels": unique_labels,
        "xml_unique_labels_sample": sample_values(unique_labels),
        "xml_candidates": xml_candidates,
        "merged_candidate_count": len(merged_candidates),
        "merged_candidates": merged_candidates,
        "candidate_tab_distribution": ", ".join(f"{tab}: {count}" for tab, count in sorted(tab_counts.items())),
        "candidate_source_summary": _candidate_source_summary(merged_candidates),
        "candidate_exclusion_todo": (
            f"{EXCLUDE_RULE_TODO_NOTE} Labels to review: {', '.join(EXCLUDE_RULE_TODO_LABELS)}"
        ),
        "candidate_classification_summary": classification_summary,
        "keep_candidates_sample": sample_candidates_by_classification(merged_candidates, "KEEP"),
        "review_candidates_sample": sample_candidates_by_classification(merged_candidates, "REVIEW"),
        "exclude_candidates_sample": sample_candidates_by_classification(merged_candidates, "EXCLUDE"),
        "candidate_classification_examples": classification_examples(merged_candidates),
        "candidate_type_summary": summarize_candidate_types(merged_candidates),
        "candidate_subtype_summary": summarize_candidate_subtypes(merged_candidates),
        "candidate_subtype_examples": subtype_examples(merged_candidates),
        "life_taxonomy_summary": life_taxonomy_summary(merged_candidates),
        "cta_candidates_sample": sample_candidates_by_subtype(merged_candidates, CTA),
        "nav_tile_candidates_sample": sample_candidates_by_subtype(merged_candidates, NAV_TILE),
        "service_tile_candidates_sample": sample_candidates_by_subtype(merged_candidates, SERVICE_TILE),
        "content_card_candidates_sample": sample_candidates_by_subtype(merged_candidates, CONTENT_CARD),
        "screen_title_candidates_sample": sample_candidates_by_subtype(merged_candidates, SCREEN_TITLE),
        "onboarding_candidates_sample": sample_candidates_by_subtype(merged_candidates, ONBOARDING),
        "promotion_or_service_card_candidates_sample": sample_candidates_by_subtype(
            merged_candidates, PROMOTION_OR_SERVICE_CARD
        ),
        "status_metric_candidates_sample": sample_candidates_by_subtype(merged_candidates, STATUS_METRIC),
        "status_label_candidates_sample": sample_candidates_by_subtype(merged_candidates, STATUS_LABEL),
        "instructional_status_candidates_sample": sample_candidates_by_subtype(merged_candidates, INSTRUCTIONAL_STATUS),
        "low_value_label_candidates_sample": sample_candidates_by_subtype(merged_candidates, LOW_VALUE_LABEL),
        "actionable_candidates_sample": sample_candidates_by_type(merged_candidates, ACTIONABLE),
        "status_candidates_sample": sample_candidates_by_type(merged_candidates, STATUS),
        "empty_state_candidates_sample": sample_candidates_by_type(merged_candidates, EMPTY_STATE),
        "instructional_candidates_sample": sample_candidates_by_type(merged_candidates, INSTRUCTIONAL),
        "chrome_candidates_sample": sample_candidates_by_type(merged_candidates, CHROME),
        "unknown_candidates_sample": sample_candidates_by_type(merged_candidates, UNKNOWN),
        "candidate_policy_recommendations": policy_recommendation_map(merged_candidates),
        "candidate_policy_recommendation_summary": policy_summary,
        "candidate_policy_examples": policy_examples(merged_candidates),
        "hypothetical_denominator_count": policy_summary.get("KEEP", 0),
        "hypothetical_denominator_delta": classification_summary.get("KEEP", 0) - policy_summary.get("KEEP", 0),
    }
