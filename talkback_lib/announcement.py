from __future__ import annotations

import time
from typing import Any

from talkback_lib.constants import LOGCAT_FILTER_SPECS


def merge_announcements(items: list[str]) -> str:
    """발화 조각 목록을 예측 가능한 규칙으로 하나의 문자열로 병합합니다."""
    normalized = [item.strip() for item in items if item.strip()]
    return " ".join(normalized)


def is_meaningful_prefix(client: Any, prefix: str) -> bool:
    normalized_prefix = client.normalize_for_comparison(prefix)
    if not normalized_prefix:
        return False
    tokens = normalized_prefix.split()
    if len(tokens) < 2:
        return False
    return any(any(ch.isalnum() for ch in token) for token in tokens)


def find_visible_anchor_prefix(client: Any, speech: str, visible_label: str) -> tuple[str, str]:
    raw_speech = str(speech or "")
    raw_visible = str(visible_label or "").strip()
    if not raw_speech.strip() or not raw_visible:
        return "", "empty_speech_or_visible"

    normalized_speech = client.normalize_for_comparison(raw_speech)
    normalized_visible = client.normalize_for_comparison(raw_visible)
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
    if not is_meaningful_prefix(client, prefix):
        return "", "prefix_not_meaningful"
    return prefix, "prefix_before_visible_anchor"


def is_contaminated_announcement_candidate(client: Any, speech: str, visible_label: str) -> tuple[bool, str]:
    prefix, reason = find_visible_anchor_prefix(client, speech, visible_label)
    return bool(prefix), reason


def try_trim_prefix_by_visible_anchor(client: Any, speech: str, visible_label: str) -> tuple[str, bool, str]:
    raw_speech = str(speech or "")
    prefix, reason = find_visible_anchor_prefix(client, raw_speech, visible_label)
    if not prefix:
        return raw_speech, False, reason
    trimmed = raw_speech[len(prefix) :].lstrip(" \t,.;:-")
    if not client.normalize_for_comparison(trimmed):
        return raw_speech, False, "trimmed_empty_after_visible_anchor"
    return trimmed, True, "visible_anchor_prefix_trim"


def get_partial_announcements(client: Any, dev: Any = None, wait_seconds: float = 2.0, only_new: bool = True) -> list[str]:
    """수집된 raw 발화 조각 리스트를 반환합니다."""
    if not client.check_talkback_status(dev=dev):
        print("TalkBack이 꺼져 있어 음성을 수집할 수 없습니다")
        client.last_announcements = []
        client.last_merged_announcement = ""
        return []

    start_time = time.monotonic()
    announcements: list[str] = []
    seen: set[str] = set()

    with client._state_lock:
        last_log_marker = client._last_log_marker

    newest_log_marker = last_log_marker

    while True:
        logs = client._run(["logcat", "-v", "time", "-d", *LOGCAT_FILTER_SPECS], dev=dev)
        for line_index, line in enumerate(logs.splitlines(), start=1):
            parsed_time = client._parse_logcat_time(line)
            if parsed_time is None:
                continue

            marker = (parsed_time, line_index)
            if newest_log_marker is None or marker > newest_log_marker:
                newest_log_marker = marker

            if only_new and last_log_marker is not None and marker <= last_log_marker:
                continue

            if "A11Y_ANNOUNCEMENT:" not in line:
                continue

            _, payload = line.split("A11Y_ANNOUNCEMENT:", 1)
            message = payload.strip()
            if message and message not in seen:
                seen.add(message)
                announcements.append(message)

        elapsed = time.monotonic() - start_time
        if elapsed >= wait_seconds:
            break

        time.sleep(min(0.3, wait_seconds - elapsed))

    with client._state_lock:
        client._last_log_marker = newest_log_marker

    client.last_announcements = announcements
    client.last_merged_announcement = client._merge_announcements(announcements)
    return announcements


def get_announcements(client: Any, dev: Any = None, wait_seconds: float = 2.0, only_new: bool = True) -> str:
    """수집된 발화 조각을 병합한 최신 발화 문자열을 반환합니다."""
    announcements = client.get_partial_announcements(
        dev=dev,
        wait_seconds=wait_seconds,
        only_new=only_new,
    )
    merged = client._merge_announcements(announcements)
    client.last_merged_announcement = merged
    return merged
