"""Conservative completion policy for post-action focus/speech verification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VerificationCompletionDecision(str, Enum):
    WAIT = "WAIT"
    COMPLETE_FAST_PATH = "COMPLETE_FAST_PATH"
    CONSERVATIVE_FALLBACK = "CONSERVATIVE_FALLBACK"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class VerificationObservation:
    elapsed_seconds: float
    focus_confirmed: bool
    evidence_correlated: bool
    announcement_idle_seconds: float
    announcement_active: bool = False
    ambiguous_focus: bool = False
    deadline_reached: bool = False


@dataclass(frozen=True)
class VerificationWaitPolicy:
    minimum_window_seconds: float = 0.45
    announcement_idle_seconds: float = 0.5

    def evaluate(self, observation: VerificationObservation) -> VerificationCompletionDecision:
        if observation.deadline_reached:
            if observation.focus_confirmed and observation.evidence_correlated:
                return VerificationCompletionDecision.TIMEOUT
            return VerificationCompletionDecision.CONSERVATIVE_FALLBACK
        if observation.elapsed_seconds < self.minimum_window_seconds:
            return VerificationCompletionDecision.WAIT
        if observation.ambiguous_focus or not observation.focus_confirmed:
            return VerificationCompletionDecision.CONSERVATIVE_FALLBACK
        if not observation.evidence_correlated:
            return VerificationCompletionDecision.CONSERVATIVE_FALLBACK
        if observation.announcement_active:
            return VerificationCompletionDecision.WAIT
        if observation.announcement_idle_seconds < self.announcement_idle_seconds:
            return VerificationCompletionDecision.WAIT
        return VerificationCompletionDecision.COMPLETE_FAST_PATH


__all__ = [
    "VerificationCompletionDecision",
    "VerificationObservation",
    "VerificationWaitPolicy",
]
