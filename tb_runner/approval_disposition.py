from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Mapping, assert_never


class QAReviewDecision(StrEnum):
    NORMAL_SPEECH = "normal_speech"
    FALSE_POSITIVE = "false_positive"
    NOT_REPRODUCIBLE = "not_reproducible"
    ACTUAL_ACCESSIBILITY_ISSUE = "actual_accessibility_issue"
    ACCEPTED_KNOWN_LIMITATION = "accepted_known_limitation"
    NEEDS_FURTHER_INVESTIGATION = "needs_further_investigation"
    UNREVIEWED = "unreviewed"


_DECISIONS_BY_VALUE: Final = {
    "정상 발화": QAReviewDecision.NORMAL_SPEECH,
    "normal speech": QAReviewDecision.NORMAL_SPEECH,
    "normal_speech": QAReviewDecision.NORMAL_SPEECH,
    "false positive": QAReviewDecision.FALSE_POSITIVE,
    "false_positive": QAReviewDecision.FALSE_POSITIVE,
    "재현 불가": QAReviewDecision.NOT_REPRODUCIBLE,
    "not reproducible": QAReviewDecision.NOT_REPRODUCIBLE,
    "not_reproducible": QAReviewDecision.NOT_REPRODUCIBLE,
    "실제 접근성 문제": QAReviewDecision.ACTUAL_ACCESSIBILITY_ISSUE,
    "actual accessibility issue": QAReviewDecision.ACTUAL_ACCESSIBILITY_ISSUE,
    "actual_accessibility_issue": QAReviewDecision.ACTUAL_ACCESSIBILITY_ISSUE,
    "accepted known limitation": QAReviewDecision.ACCEPTED_KNOWN_LIMITATION,
    "accepted_known_limitation": QAReviewDecision.ACCEPTED_KNOWN_LIMITATION,
    "known limitation 승인": QAReviewDecision.ACCEPTED_KNOWN_LIMITATION,
    "추가 조사 필요": QAReviewDecision.NEEDS_FURTHER_INVESTIGATION,
    "needs further investigation": QAReviewDecision.NEEDS_FURTHER_INVESTIGATION,
    "needs_further_investigation": QAReviewDecision.NEEDS_FURTHER_INVESTIGATION,
    "미검토": QAReviewDecision.UNREVIEWED,
    "unreviewed": QAReviewDecision.UNREVIEWED,
}


@dataclass(frozen=True, slots=True)
class ApprovalValidationReport:
    failures: tuple[str, ...]
    qa_review_rows: int
    qa_completed_rows: int
    qa_snapshot_required: int
    qa_snapshot_present: int
    automation_acknowledgments_required: int
    automation_acknowledgments_present: int


def reviewer_decision(record: Mapping[str, Any]) -> QAReviewDecision:
    value = (
        str(record.get("review_decision") or record.get("validator_decision") or "")
        .strip()
        .casefold()
    )
    return _DECISIONS_BY_VALUE.get(value, QAReviewDecision.UNREVIEWED)


def is_review_completed(decision: QAReviewDecision) -> bool:
    match decision:
        case (
            QAReviewDecision.NORMAL_SPEECH
            | QAReviewDecision.FALSE_POSITIVE
            | QAReviewDecision.NOT_REPRODUCIBLE
            | QAReviewDecision.ACTUAL_ACCESSIBILITY_ISSUE
            | QAReviewDecision.ACCEPTED_KNOWN_LIMITATION
        ):
            return True
        case QAReviewDecision.NEEDS_FURTHER_INVESTIGATION | QAReviewDecision.UNREVIEWED:
            return False
        case unreachable:
            assert_never(unreachable)


def requires_known_limitation_snapshot(decision: QAReviewDecision) -> bool:
    match decision:
        case (
            QAReviewDecision.ACTUAL_ACCESSIBILITY_ISSUE
            | QAReviewDecision.ACCEPTED_KNOWN_LIMITATION
        ):
            return True
        case (
            QAReviewDecision.NORMAL_SPEECH
            | QAReviewDecision.FALSE_POSITIVE
            | QAReviewDecision.NOT_REPRODUCIBLE
            | QAReviewDecision.NEEDS_FURTHER_INVESTIGATION
            | QAReviewDecision.UNREVIEWED
        ):
            return False
        case unreachable:
            assert_never(unreachable)


__all__ = [
    "ApprovalValidationReport",
    "QAReviewDecision",
    "is_review_completed",
    "requires_known_limitation_snapshot",
    "reviewer_decision",
]
