"""Diagnostic synchronization cannot turn missing speech into equivalence."""
import pytest

from tools.camera_overlay_probe import speech_comparison, timing_gap


def test_bounded_timing_is_not_reported_as_atomic():
    result = timing_gap(2.0, 2.001, 1.0, 2.5)
    assert result["DELTA_MS"] == pytest.approx(1.0)
    assert result["UI_MOMENT_BOUND_MS"] == pytest.approx(1500.0)
    assert result["SYNCHRONIZATION"] == "BOUNDED_SEQUENTIAL_NOT_ATOMIC"


@pytest.mark.parametrize("times", [(2,1,0,3), (1,2,3,4), (1,2,0,1)])
def test_reversed_capture_intervals_are_rejected(times):
    with pytest.raises(ValueError, match="chronological"):
        timing_gap(*times)


@pytest.mark.parametrize("present,absent", [(None,None), ([],["Camera"]), (["Camera"],[]), (None,["Camera"])])
def test_empty_or_missing_speech_does_not_prove_same(present,absent):
    assert speech_comparison(present,absent) == "NO_RELIABLE_SPEECH_EVIDENCE"


def test_observed_identical_speech_requires_both_nonempty_sides():
    assert speech_comparison(["Camera", "button"],["Camera", "button"]) == "IDENTICAL"


def test_speech_difference_requires_review_not_automatic_volatile_discount():
    assert speech_comparison(["Camera offline"],["Camera connected"]) == "DIFFERENT_REQUIRES_SEMANTIC_REVIEW"
