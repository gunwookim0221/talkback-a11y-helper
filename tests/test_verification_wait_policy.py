from talkback_lib.verification_wait_policy import (
    VerificationCompletionDecision,
    VerificationObservation,
    VerificationWaitPolicy,
)


def _observation(**overrides):
    values = {
        "elapsed_seconds": 0.8,
        "focus_confirmed": True,
        "evidence_correlated": True,
        "announcement_idle_seconds": 0.6,
    }
    values.update(overrides)
    return VerificationObservation(**values)


def test_stable_focus_evidence_and_idle_announcement_complete_early():
    assert VerificationWaitPolicy().evaluate(_observation()) is VerificationCompletionDecision.COMPLETE_FAST_PATH


def test_minimum_window_and_active_announcement_keep_waiting():
    policy = VerificationWaitPolicy()
    assert policy.evaluate(_observation(elapsed_seconds=0.2)) is VerificationCompletionDecision.WAIT
    assert policy.evaluate(_observation(announcement_active=True)) is VerificationCompletionDecision.WAIT


def test_ambiguous_focus_or_incomplete_evidence_use_conservative_fallback():
    policy = VerificationWaitPolicy()
    assert policy.evaluate(_observation(ambiguous_focus=True)) is VerificationCompletionDecision.CONSERVATIVE_FALLBACK
    assert policy.evaluate(_observation(evidence_correlated=False)) is VerificationCompletionDecision.CONSERVATIVE_FALLBACK


def test_deadline_preserves_timeout_or_fallback_meaning():
    policy = VerificationWaitPolicy()
    assert policy.evaluate(_observation(deadline_reached=True)) is VerificationCompletionDecision.TIMEOUT
    assert policy.evaluate(_observation(deadline_reached=True, focus_confirmed=False)) is VerificationCompletionDecision.CONSERVATIVE_FALLBACK
