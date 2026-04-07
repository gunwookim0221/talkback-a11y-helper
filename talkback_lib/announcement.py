#!/usr/bin/env python3
"""Announcement parsing helpers."""

from __future__ import annotations

from talkback_lib.utils import normalize_for_comparison


def merge_announcements(items: list[str]) -> str:
    """발화 조각 목록을 예측 가능한 규칙으로 하나의 문자열로 병합합니다."""
    normalized = [item.strip() for item in items if item.strip()]
    return " ".join(normalized)


def is_meaningful_prefix(prefix: str) -> bool:
    normalized_prefix = normalize_for_comparison(prefix)
    if not normalized_prefix:
        return False
    tokens = normalized_prefix.split()
    if len(tokens) < 2:
        return False
    return any(any(ch.isalnum() for ch in token) for token in tokens)


def find_visible_anchor_prefix(speech: str, visible_label: str) -> tuple[str, str]:
    raw_speech = str(speech or "")
    raw_visible = str(visible_label or "").strip()
    if not raw_speech.strip() or not raw_visible:
        return "", "empty_speech_or_visible"

    normalized_speech = normalize_for_comparison(raw_speech)
    normalized_visible = normalize_for_comparison(raw_visible)
    if not normalized_speech or not normalized_visible:
        return "", "empty_normalized_speech_or_visible"
    if normalized_visible not in normalized_speech:
        return "", "visible_anchor_not_in_speech"
    if len(normalized_visible.split()) < 2:
        return "", "visible_anchor_too_short"

    anchor_start = raw_speech.lower().find(raw_visible.lower())
    if anchor_start < 0:
        return "", "visible_anchor_not_found_raw"
    if anchor_start <= 0:
        return "", "visible_anchor_at_start"

    prefix = raw_speech[:anchor_start]
    if not is_meaningful_prefix(prefix):
        return "", "prefix_not_meaningful"
    return prefix, "prefix_before_visible_anchor"


def is_contaminated_announcement_candidate(speech: str, visible_label: str) -> tuple[bool, str]:
    prefix, reason = find_visible_anchor_prefix(speech, visible_label)
    return bool(prefix), reason


def try_trim_prefix_by_visible_anchor(speech: str, visible_label: str) -> tuple[str, bool, str]:
    raw_speech = str(speech or "")
    prefix, reason = find_visible_anchor_prefix(raw_speech, visible_label)
    if not prefix:
        return raw_speech, False, reason
    trimmed = raw_speech[len(prefix) :].lstrip(" \t,.;:-")
    if not normalize_for_comparison(trimmed):
        return raw_speech, False, "trimmed_empty_after_visible_anchor"
    return trimmed, True, "visible_anchor_prefix_trim"
