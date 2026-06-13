from __future__ import annotations

import re
from typing import Any


POLICY_NAME = "balanced_v1"
KNOWN_RISK_LABELS = {"EventsButton", "LocationButton"}
MAX_KNOWN_RISK_LABELS = 5
REQUIRED_SUBTYPES = {"CTA", "NAV_TILE", "SERVICE_TILE", "LIFE_TAB"}
OPTIONAL_SUBTYPES = {
    "CONTENT_CARD",
    "SCREEN_TITLE",
    "ONBOARDING",
    "PROMOTION_OR_SERVICE_CARD",
    "STATUS_METRIC",
    "STATUS_LABEL",
    "INSTRUCTIONAL_STATUS",
    "INFO_BUTTON",
    "TIP_CARD",
    "EMPTY_OR_NO_DATA_STATUS",
}
PROVISIONAL_SUBTYPES = {"METRIC_CARD", "PROGRAM_CARD", "UNKNOWN"}
EXCLUDED_SUBTYPES = {"CHROME", "LOW_VALUE_LABEL"}
OPTIONAL_LABELS = {"Add family member", "View profile"}
STRUCTURAL_LABELS = {"Controls"}


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _split_sample_labels(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _normalize_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _strip_button_suffix(value: str) -> str:
    return re.sub(r"button$", "", value, flags=re.IGNORECASE).strip()


def _traversal_labels(tab_stats: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for stats in (tab_stats or {}).values():
        labels.update(
            str(label or "").strip()
            for label in stats.get("visible_labels_set", [])
            if str(label or "").strip()
        )
    return labels


def _shadow_eligibility(candidate: dict[str, Any], scenario_id: str = "") -> str:
    label = str(candidate.get("label", "") or "").strip()
    subtype = str(candidate.get("candidate_subtype", "") or "").strip().upper()
    candidate_type = str(candidate.get("candidate_type", "") or "").strip().upper()
    policy = str(candidate.get("policy_recommendation", "") or "").strip().upper()
    is_life = str(scenario_id or "").startswith("life_")

    if not label or label in STRUCTURAL_LABELS:
        return "STRUCTURAL"
    if label in OPTIONAL_LABELS:
        return "OPTIONAL"
    if subtype in EXCLUDED_SUBTYPES or candidate_type == "CHROME" or policy == "EXCLUDE":
        return "EXCLUDED"
    if subtype in PROVISIONAL_SUBTYPES:
        return "PROVISIONAL"
    if subtype in REQUIRED_SUBTYPES:
        return "REQUIRED"
    if is_life and (subtype in OPTIONAL_SUBTYPES or policy == "REVIEW"):
        return "OPTIONAL"
    if policy == "KEEP" and candidate_type in {"ACTIONABLE", "STATUS"}:
        return "REQUIRED"
    if subtype in OPTIONAL_SUBTYPES or policy == "REVIEW":
        return "OPTIONAL"
    if candidate_type == "UNKNOWN":
        return "PROVISIONAL"
    return "OPTIONAL"


def _match_shadow_label(label: str, traversal_norms: set[str]) -> tuple[bool, str]:
    normalized = _normalize_label(label)
    if not normalized:
        return False, "empty"
    if normalized in traversal_norms:
        return True, "exact"

    stripped = _normalize_label(_strip_button_suffix(label))
    if stripped and stripped != normalized and stripped in traversal_norms:
        return True, "button_suffix"

    containing = [value for value in traversal_norms if normalized in value and normalized != value]
    if containing:
        return True, "contained_in_compound"

    stripped_containing = [
        value for value in traversal_norms if stripped and stripped != normalized and stripped in value
    ]
    if stripped_containing:
        return True, "button_suffix_contained"

    return False, "missing"


def calculate_shadow_coverage_inputs(
    merged_candidates: list[dict[str, Any]],
    tab_stats: dict[str, Any],
    scenario_id: str = "",
) -> dict[str, Any]:
    traversal_norms = {_normalize_label(label) for label in _traversal_labels(tab_stats)}
    required_labels: list[str] = []
    required_matched: list[str] = []
    required_missing: list[str] = []
    optional_labels: list[str] = []
    optional_matched: list[str] = []
    provisional_labels: list[str] = []
    provisional_count = 0
    matching_gap_count = 0
    traversal_gap_count = 0

    for candidate in merged_candidates:
        label = str(candidate.get("label", "") or "").strip()
        if not label:
            continue
        eligibility = _shadow_eligibility(candidate, scenario_id)
        matched, match_reason = _match_shadow_label(label, traversal_norms)

        if eligibility == "REQUIRED":
            required_labels.append(label)
            if matched:
                required_matched.append(label)
            else:
                required_missing.append(label)
                classes = " ".join(str(value or "") for value in candidate.get("classes", []))
                clickable = {str(value or "").lower() for value in candidate.get("clickable_values", [])}
                if match_reason != "missing":
                    matching_gap_count += 1
                elif "true" in clickable or "button" in classes.lower():
                    traversal_gap_count += 1
        elif eligibility == "OPTIONAL":
            optional_labels.append(label)
            if matched:
                optional_matched.append(label)
        elif eligibility == "PROVISIONAL":
            provisional_count += 1
            provisional_labels.append(label)

    required_denominator = len(required_labels)
    required_matched_count = len(required_matched)
    optional_denominator = len(optional_labels)
    optional_matched_count = len(optional_matched)
    required_known_risks = [label for label in required_missing if label in KNOWN_RISK_LABELS]
    known_risks = list(required_known_risks)
    for label in sorted(provisional_labels):
        if len(known_risks) >= MAX_KNOWN_RISK_LABELS:
            break
        if label not in known_risks:
            known_risks.append(label)
    traversal_gap_count = max(traversal_gap_count, len(required_known_risks))

    return {
        "required_denominator_count": required_denominator,
        "required_matched_count": required_matched_count,
        "required_missing_count": len(required_missing),
        "required_coverage": round((required_matched_count / required_denominator) * 100, 1)
        if required_denominator
        else 0.0,
        "optional_denominator_count": optional_denominator,
        "optional_matched_count": optional_matched_count,
        "optional_coverage": round((optional_matched_count / optional_denominator) * 100, 1)
        if optional_denominator
        else 0.0,
        "provisional_candidate_count": provisional_count,
        "matching_gap_count": matching_gap_count,
        "traversal_gap_count": traversal_gap_count,
        "taxonomy_gap_count": 0,
        "known_risk_labels": known_risks,
        "required_missing_labels_sample": ", ".join(sorted(required_missing)[:10]),
        "provisional_labels_sample": ", ".join(sorted(provisional_labels)[:MAX_KNOWN_RISK_LABELS]),
    }


def _count_matching_gaps(report: dict[str, Any]) -> int:
    if "matching_gap_count" in report:
        return _int_value(report.get("matching_gap_count"))
    reason_sample = str(report.get("coverage_missing_reason_sample", "") or "")
    return reason_sample.count("matching_mismatch_")


def _count_traversal_gaps(report: dict[str, Any], known_risk_labels: list[str]) -> int:
    if "traversal_gap_count" in report:
        return _int_value(report.get("traversal_gap_count"))
    reason_sample = str(report.get("coverage_missing_reason_sample", "") or "")
    actionable_count = reason_sample.count("xml_only_actionable_candidate")
    return max(actionable_count, len(known_risk_labels))


def _count_taxonomy_gaps(report: dict[str, Any]) -> int:
    if "taxonomy_gap_count" in report:
        return _int_value(report.get("taxonomy_gap_count"))
    return 0


def _shadow_inputs_unavailable(coverage_status: str, required_denominator_count: int) -> bool:
    if required_denominator_count > 0:
        return coverage_status not in {"", "ready", "ready_empty_denominator"}
    return True


def calculate_balanced_shadow_verdict(report: dict[str, Any]) -> dict[str, Any]:
    """Calculate Audit V4 shadow verdict without changing the V3 verdict."""

    v3_verdict = str(report.get("verdict", "") or "").upper()
    environment_error = bool(report.get("environment_error")) or v3_verdict == "ENVIRONMENT_ERROR"
    coverage_status = str(report.get("coverage_diagnostic_status", "") or "")

    required_denominator_count = _int_value(
        report.get("required_denominator_count", report.get("coverage_denominator_count"))
    )
    required_matched_count = _int_value(
        report.get("required_matched_count", report.get("coverage_matched_count"))
    )
    required_missing_count = _int_value(
        report.get("required_missing_count", report.get("coverage_missing_count"))
    )
    required_coverage = _float_value(
        report.get("required_coverage", report.get("coverage_percent"))
    )
    optional_coverage = _float_value(report.get("optional_coverage"), 0.0)
    provisional_candidate_count = _int_value(report.get("provisional_candidate_count"), 0)
    known_risk_labels = _split_sample_labels(report.get("known_risk_labels"))
    if not known_risk_labels:
        missing_labels = _split_sample_labels(
            report.get("required_missing_labels_sample", report.get("coverage_missing_labels_sample"))
        )
        known_risk_labels = [label for label in missing_labels if label in KNOWN_RISK_LABELS]
    provisional_labels = _split_sample_labels(report.get("provisional_labels_sample"))
    for label in provisional_labels:
        if len(known_risk_labels) >= MAX_KNOWN_RISK_LABELS:
            break
        if label not in known_risk_labels:
            known_risk_labels.append(label)
    required_known_risks = [label for label in known_risk_labels if label in KNOWN_RISK_LABELS]
    matching_gap_count = _count_matching_gaps(report)
    traversal_gap_count = _count_traversal_gaps(report, required_known_risks)
    taxonomy_gap_count = _count_taxonomy_gaps(report)

    if environment_error:
        verdict = "ENVIRONMENT_ERROR"
        reason = "environment_error=true"
    elif v3_verdict == "FAIL":
        verdict = "FAIL"
        reason = "v3_verdict=FAIL"
    elif _shadow_inputs_unavailable(coverage_status, required_denominator_count):
        verdict = "REVIEW"
        reason = f"coverage_not_ready:{coverage_status or 'unknown'}"
    elif required_coverage < 50.0:
        verdict = "FAIL"
        reason = "required_coverage<50"
    elif required_missing_count >= 4:
        verdict = "FAIL"
        reason = "required_missing_count>=4"
    elif (
        required_coverage >= 90.0
        and required_missing_count <= 1
        and traversal_gap_count == 0
        and taxonomy_gap_count == 0
    ):
        verdict = "PASS"
        reason = "required_coverage>=90 and required_missing_count<=1 and no traversal/taxonomy gaps"
    else:
        verdict = "REVIEW"
        reason = "balanced_policy_review_threshold"

    if provisional_candidate_count > 0 and verdict != "ENVIRONMENT_ERROR":
        reason = f"{reason}; provisional_risk_count={provisional_candidate_count}"

    return {
        "policy_name": POLICY_NAME,
        "verdict": verdict,
        "required_denominator_count": required_denominator_count,
        "required_matched_count": required_matched_count,
        "required_missing_count": required_missing_count,
        "required_coverage": required_coverage,
        "optional_coverage": optional_coverage,
        "provisional_candidate_count": provisional_candidate_count,
        "matching_gap_count": matching_gap_count,
        "traversal_gap_count": traversal_gap_count,
        "taxonomy_gap_count": taxonomy_gap_count,
        "known_risk_labels": known_risk_labels,
        "reason": reason,
    }


def add_shadow_verdict_fields(report: dict[str, Any]) -> dict[str, Any]:
    shadow = calculate_balanced_shadow_verdict(report)
    report["shadow_verdict_v4"] = shadow
    report["shadow_policy_name"] = shadow["policy_name"]
    report["shadow_verdict_v4_value"] = shadow["verdict"]
    report["shadow_required_coverage"] = shadow["required_coverage"]
    report["shadow_required_missing_count"] = shadow["required_missing_count"]
    report["shadow_traversal_gap_count"] = shadow["traversal_gap_count"]
    report["shadow_taxonomy_gap_count"] = shadow["taxonomy_gap_count"]
    report["shadow_known_risks"] = ", ".join(shadow["known_risk_labels"])
    return report
