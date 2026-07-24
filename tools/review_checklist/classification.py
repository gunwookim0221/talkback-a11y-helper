from dataclasses import dataclass
from typing import Final

AUTOMATION_REASONS: Final = frozenset({
    "terminal_not_handled", "repeat_no_progress", "move_failed", "target_not_found",
    "recovery_only", "recovery_failed", "identity_indeterminate", "coverage_only",
    "traversal_only", "platform_only", "environment_only",
})
HUMAN_MISMATCHES: Final = frozenset({
    "EMPTY_VISIBLE", "EMPTY_SPEECH", "TEXT_MISMATCH", "SPEECH_MISMATCH",
    "NEW_FOCUSABLE_SPEECH_ONLY", "NEW_ACCESSIBILITY_FAILURE",
})


@dataclass(frozen=True, slots=True)
class ReviewClassification:
    area: str
    reason: str


def classify_review(*, mismatch_type: str, failure_reason: str) -> ReviewClassification:
    normalized_mismatch = mismatch_type.strip().upper()
    normalized_failure = failure_reason.strip().lower()
    if normalized_failure in AUTOMATION_REASONS:
        return ReviewClassification("AUTOMATION", normalized_failure)
    if "speech_visible_diverged" in normalized_failure or normalized_mismatch in HUMAN_MISMATCHES:
        return ReviewClassification("QA", normalized_mismatch or normalized_failure)
    return ReviewClassification("AUTOMATION", normalized_failure or normalized_mismatch or "unclassified_failure")
