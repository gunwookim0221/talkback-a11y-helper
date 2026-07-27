from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class ReviewDomain(StrEnum):
    QA_ACCESSIBILITY = "qa_accessibility"
    AUTOMATION_ENGINE = "automation_engine"
    UNKNOWN = "unknown"


_AUTOMATION_REASONS: Final = frozenset(
    {
        "terminal_not_handled",
        "repeat_no_progress",
        "move_failed",
        "target_not_found",
        "recovery_only",
        "recovery_failed",
        "identity_indeterminate",
        "coverage_only",
        "traversal_only",
        "platform_only",
        "environment_only",
    }
)
_AUTOMATION_PREFIXES: Final = (
    "recovery_",
    "identity_",
    "coverage_",
    "traversal_",
    "platform_",
    "environment_",
)
_QA_MISMATCHES: Final = frozenset(
    {
        "EMPTY_VISIBLE",
        "EMPTY_SPEECH",
        "TEXT_MISMATCH",
        "SPEECH_MISMATCH",
        "NEW_FOCUSABLE_SPEECH_ONLY",
        "NEW_ACCESSIBILITY_FAILURE",
    }
)


@dataclass(frozen=True, slots=True)
class ReviewClassification:
    review_domain: ReviewDomain
    classification_reason: str
    source_failure_reason: str
    source_issue_type: str

    @property
    def area(self) -> str:
        return (
            "QA"
            if self.review_domain is ReviewDomain.QA_ACCESSIBILITY
            else "AUTOMATION"
        )

    @property
    def reason(self) -> str:
        return self.classification_reason


def classify_review_domain(
    *,
    mismatch_type: str,
    failure_reason: str,
) -> ReviewClassification:
    normalized_mismatch = str(mismatch_type or "").strip().upper()
    normalized_failure = str(failure_reason or "").strip().lower()
    is_automation = (
        normalized_failure in _AUTOMATION_REASONS
        or normalized_failure.startswith(_AUTOMATION_PREFIXES)
    )
    if is_automation:
        return ReviewClassification(
            ReviewDomain.AUTOMATION_ENGINE,
            normalized_failure,
            normalized_failure,
            normalized_mismatch,
        )
    if (
        "speech_visible_diverged" in normalized_failure
        or normalized_mismatch in _QA_MISMATCHES
    ):
        return ReviewClassification(
            ReviewDomain.QA_ACCESSIBILITY,
            normalized_mismatch or normalized_failure,
            normalized_failure,
            normalized_mismatch,
        )
    return ReviewClassification(
        ReviewDomain.UNKNOWN,
        normalized_failure or normalized_mismatch or "unclassified_failure",
        normalized_failure,
        normalized_mismatch,
    )


__all__ = ["ReviewClassification", "ReviewDomain", "classify_review_domain"]
