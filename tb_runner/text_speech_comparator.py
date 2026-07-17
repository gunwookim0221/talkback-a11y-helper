"""Deterministic visible-text and TalkBack-speech delta classification."""

from __future__ import annotations

from typing import Any

from tb_runner.observation_schema import CanonicalObservation


def classify_text_speech(
    baseline: CanonicalObservation | None,
    candidate: CanonicalObservation | None,
    *,
    known_empty_visible: bool = False,
    ambiguous: bool = False,
) -> dict[str, Any]:
    if ambiguous:
        return {"classification": "AMBIGUOUS", "equivalent": False}
    if baseline is None or candidate is None:
        return {"classification": "DATA_UNAVAILABLE", "equivalent": False}
    bt, ct = baseline.normalized_text, candidate.normalized_text
    bs, cs = baseline.normalized_speech, candidate.normalized_speech
    baseline_empty = baseline.mismatch_type == "EMPTY_VISIBLE"
    candidate_empty = candidate.mismatch_type == "EMPTY_VISIBLE"
    if candidate_empty and not baseline_empty:
        category = "NEW_EMPTY_VISIBLE"
    elif baseline_empty and not candidate_empty:
        category = "RESOLVED_EMPTY_VISIBLE"
    elif candidate_empty and known_empty_visible:
        category = "KNOWN_EMPTY_VISIBLE"
    elif candidate.visible_text and not candidate.talkback_speech:
        category = "SPEECH_MISSING"
    elif not candidate.visible_text and candidate.talkback_speech:
        category = "VISIBLE_LABEL_MISSING"
    elif cs.get("duplicate_segment_detected"):
        category = "DUPLICATE_SPEECH"
    elif not baseline.talkback_speech and candidate.talkback_speech:
        category = "UNEXPECTED_SPEECH"
    elif (
        bt.get("semantic") == ct.get("semantic")
        and bs.get("semantic") == cs.get("semantic")
        and (bt.get("dynamic_markers") or bs.get("dynamic_markers"))
        and (
            bt.get("dynamic_markers") != ct.get("dynamic_markers")
            or bs.get("dynamic_markers") != cs.get("dynamic_markers")
        )
    ):
        category = "DYNAMIC_VALUE_ONLY"
    elif (
        bt.get("role_stripped") == ct.get("role_stripped")
        and bs.get("role_stripped") == cs.get("role_stripped")
        and (
            bt.get("semantic") != ct.get("semantic")
            or bs.get("semantic") != cs.get("semantic")
        )
    ):
        category = "ROLE_SUFFIX_ONLY"
    elif bt.get("semantic") == ct.get("semantic") and bs.get("semantic") != cs.get("semantic"):
        category = "TEXT_MATCHED_SPEECH_CHANGED"
    elif bt.get("semantic") != ct.get("semantic") and bs.get("semantic") == cs.get("semantic"):
        category = "TEXT_CHANGED_SPEECH_MATCHED"
    elif (
        bt.get("semantic") == ct.get("semantic")
        and bs.get("semantic") == cs.get("semantic")
        and (baseline.visible_text != candidate.visible_text or baseline.talkback_speech != candidate.talkback_speech)
    ):
        if (
            bt.get("whitespace_normalized") == ct.get("whitespace_normalized")
            and bs.get("whitespace_normalized") == cs.get("whitespace_normalized")
        ):
            category = "WHITESPACE_ONLY"
        elif (
            bt.get("punctuation_normalized") == ct.get("punctuation_normalized")
            and bs.get("punctuation_normalized") == cs.get("punctuation_normalized")
        ):
            category = "PUNCTUATION_ONLY"
        else:
            category = "WHITESPACE_ONLY"
    elif (
        bt.get("semantic") != ct.get("semantic")
        or bs.get("semantic") != cs.get("semantic")
    ):
        dynamic_equivalent = (
            bt.get("semantic") == ct.get("semantic")
            and bs.get("semantic") == cs.get("semantic")
            and (bt.get("dynamic_markers") or bs.get("dynamic_markers"))
        )
        if dynamic_equivalent:
            category = "DYNAMIC_VALUE_ONLY"
        elif ct.get("semantic") == cs.get("semantic"):
            category = "BOTH_CHANGED_EQUIVALENT"
        else:
            category = "BOTH_CHANGED_DIFFERENT"
    else:
        category = "BOTH_CHANGED_EQUIVALENT"
    return {
        "classification": category,
        "equivalent": category in {
            "BOTH_CHANGED_EQUIVALENT",
            "DYNAMIC_VALUE_ONLY",
            "ROLE_SUFFIX_ONLY",
            "PUNCTUATION_ONLY",
            "WHITESPACE_ONLY",
        },
        "baseline_observation_id": baseline.observation_id,
        "candidate_observation_id": candidate.observation_id,
    }


__all__ = ["classify_text_speech"]
