from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tb_runner.review_classification import ReviewDomain, classify_review_domain


CLASSIFICATION_SOURCE = "review_workbook_contract"
QUALITY_ISSUE_SCHEMA_VERSION = "quality-issues-v1"


@dataclass(frozen=True, slots=True)
class QualityIssueClassification:
    quality_issues: list[dict[str, Any]]
    automation_diagnostics: list[dict[str, Any]]
    contract: dict[str, int | str]


def _classified_signal(signal: dict[str, Any]) -> dict[str, Any]:
    classification = classify_review_domain(
        mismatch_type=str(signal.get("mismatch_type") or ""),
        failure_reason=str(signal.get("failure_reason") or ""),
    )
    review_domain = classification.review_domain.value
    if classification.review_domain is ReviewDomain.QA_ACCESSIBILITY:
        validator_status = "QA_REVIEW"
    elif classification.review_domain is ReviewDomain.AUTOMATION_ENGINE:
        validator_status = "AUTOMATION_DIAGNOSTIC"
    else:
        validator_status = "CLASSIFICATION_UNAVAILABLE"
    return {
        **signal,
        "review_domain": review_domain,
        "classification_reason": classification.classification_reason,
        "classification_source": CLASSIFICATION_SOURCE,
        "validator_status": validator_status,
        "raw_final_result": signal.get("final_result", ""),
    }


def classify_quality_signals(signals: object) -> QualityIssueClassification:
    quality_issues: list[dict[str, Any]] = []
    automation_diagnostics: list[dict[str, Any]] = []
    classification_unavailable_count = 0

    if not isinstance(signals, list):
        signals = []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        classified = _classified_signal(signal)
        if classified["review_domain"] == ReviewDomain.QA_ACCESSIBILITY.value:
            quality_issues.append(classified)
        else:
            automation_diagnostics.append(classified)
            if classified["review_domain"] == ReviewDomain.UNKNOWN.value:
                classification_unavailable_count += 1

    return QualityIssueClassification(
        quality_issues=quality_issues,
        automation_diagnostics=automation_diagnostics,
        contract={
            "schema_version": QUALITY_ISSUE_SCHEMA_VERSION,
            "classification_source": CLASSIFICATION_SOURCE,
            "qa_review_count": len(quality_issues),
            "automation_diagnostic_count": len(automation_diagnostics),
            "classification_unavailable_count": classification_unavailable_count,
        },
    )


def normalize_legacy_quality_issues(issues: object) -> list[dict[str, Any]]:
    if not isinstance(issues, list):
        return []
    normalized: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        normalized.append(
            {
                **issue,
                "review_domain": ReviewDomain.UNKNOWN.value,
                "classification_source": "legacy_summary_raw_signal",
                "classification_reason": "historical_classification_unavailable",
                "validator_status": "CLASSIFICATION_UNAVAILABLE",
                "raw_final_result": issue.get("final_result", ""),
            }
        )
    return normalized


__all__ = [
    "CLASSIFICATION_SOURCE",
    "QUALITY_ISSUE_SCHEMA_VERSION",
    "QualityIssueClassification",
    "classify_quality_signals",
    "normalize_legacy_quality_issues",
]
