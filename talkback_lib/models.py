"""talkback_lib 데이터 구조 (점진 도입용)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Bounds:
    left: int
    top: int
    right: int
    bottom: int


@dataclass
class FocusResult:
    found: bool
    text: str | None = None
    content_desc: str | None = None
    resource_id: str | None = None
    bounds: Bounds | None = None
    source: str | None = None


@dataclass
class SmartNextResult:
    success: bool
    status: str
    detail: str | None = None
    terminal: bool = False
    payload: dict[str, Any] | None = None


@dataclass
class AnnouncementResult:
    partial_announcements: list[str]
    merged_announcement: str
    only_new: bool = True
