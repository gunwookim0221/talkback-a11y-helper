from __future__ import annotations

import re
import unicodedata


LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "bottom_home": ("Home", "홈"),
    "bottom_devices": ("Devices", "기기"),
    "bottom_life": ("Life", "라이프"),
    "bottom_routines": ("Routines", "자동화", "루틴"),
    "bottom_menu": ("Menu", "메뉴"),
    "selected": ("Selected", "선택됨"),
    "more_options": ("More options", "더보기"),
    "navigate_up": ("Navigate up", "위로 이동", "상위 메뉴로 이동"),
    "back": ("Back", "뒤로"),
    "dismiss": ("Dismiss", "닫기"),
    "start": ("Start", "시작"),
    "open": ("Open", "열기"),
    "skip": ("Skip", "건너뛰기"),
    "continue": ("Continue", "계속"),
    "next": ("Next", "다음"),
    "checkbox": ("Checkbox", "Check box", "체크박스"),
    "set_up": ("Set up", "설정", "설정하기"),
    "next_time": ("Next time", "다음에", "나중에"),
    "terms": ("Terms", "약관"),
    "privacy": ("Privacy", "개인정보"),
    "consent": ("Consent", "동의"),
    "allow": ("Allow", "허용"),
    "add_device": ("Add device", "기기 추가"),
    "add": ("Add", "추가"),
    "history": ("History", "기록"),
    "controls": ("Controls", "제어"),
    "events": ("Events", "이벤트"),
    "location": ("Location", "장소"),
    "local_monitor": ("Monitor", "Monitoring", "모니터링"),
    "local_save": ("Save", "Saving", "Savings", "절약"),
    "local_activity": ("Activity", "활동"),
    "local_my_plants": ("My plants", "My plant", "내 식물"),
    "local_routines": ("Routines", "Routine", "자동화"),
}

VERIFY_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "outdoor air quality": ("실외 공기질", "실외 공기(미세먼지)"),
    "air quality": ("실외 공기질", "실외 공기(미세먼지)"),
    "air care": ("에어 케어", "실외 공기질", "실외 공기(미세먼지)"),
    "pm 10": ("미세먼지", "pm10"),
    "pm 2.5": ("초미세먼지", "pm2.5"),
    "home care": ("홈 케어", "홈케어"),
    "smart care": ("똑똑한 관리",),
    "home appliances": ("가전 기기", "삼성 가전 기기"),
    "clothing care": ("의류 관리", "클로딩 케어", "에어드레서", "슈드레서"),
    "shoe care": ("슈드레서",),
    "smart find": ("파인드", "내 기기"),
    "find": ("파인드", "내 기기"),
    "smart video": ("비디오",),
    "video": ("비디오",),
    "smartthings settings": ("스마트싱스 설정",),
    "settings": ("스마트싱스 설정",),
    "navigate up": ("위로 이동", "상위 메뉴로 이동"),
    "more options": ("더보기",),
    "location qr code": ("장소 QR 코드", "장소 qr 코드"),
    "change location": ("장소 변경",),
    "add": ("추가",),
    "smartthings energy": ("스마트싱스 에너지", "에너지"),
    "energy usage": ("에너지 사용량", "기기 에너지 사용량"),
    "monitor": ("모니터링",),
    "my plants": ("내 식물",),
    "plants": ("식물", "내 식물"),
    "routines": ("자동화",),
    "add device": ("기기 추가",),
    "not now": ("다음에", "나중에"),
    "next time": ("다음에", "나중에"),
    "dismiss": ("닫기",),
}

EMPTY_STATE_LABEL_ALIASES: tuple[str, ...] = (
    "nothing yet",
    "no history",
    "no activity",
    "no data",
    "no events",
    "아직 없음",
    "기록 없음",
    "활동 없음",
    "데이터 없음",
    "이벤트 없음",
    "내역 없음",
    "사용 기록 없음",
)

ONBOARDING_CTA_ALIASES: tuple[str, ...] = (
    "later",
    "not now",
    "skip",
    "start",
    "get started",
    "open",
    "continue",
    "next",
    "set up",
    "setup",
    "set up now",
    "allow",
    "agree",
    "consent",
    "terms",
    "privacy",
    "checkbox",
    "나중에",
    "건너뛰기",
    "시작",
    "시작하기",
    "열기",
    "계속",
    "다음",
    "설정",
    "설정하기",
    "지금 설정하기",
    "허용",
    "동의",
    "약관",
    "개인정보",
    "체크박스",
)

FAMILY_CARE_ONBOARDING_BODY_ALIASES: tuple[str, ...] = (
    "want better insight into your daily life",
    "daily life",
    "일상 생활",
    "더 잘 이해",
)

FAMILY_CARE_LATER_ALIASES: tuple[str, ...] = ("later", "나중에")
FAMILY_CARE_SETUP_ALIASES: tuple[str, ...] = ("set up now", "set up", "setup", "지금 설정하기", "설정하기")

_BOTTOM_TAB_CANONICAL_KEYS: tuple[tuple[str, str], ...] = (
    ("bottom_home", "home"),
    ("bottom_devices", "devices"),
    ("bottom_life", "life"),
    ("bottom_routines", "routines"),
    ("bottom_menu", "menu"),
)

_LOCAL_TAB_CANONICAL_KEYS: tuple[tuple[str, str], ...] = (
    ("local_monitor", "monitor"),
    ("local_save", "save"),
    ("local_activity", "activity"),
    ("local_my_plants", "my_plants"),
    ("local_routines", "routines"),
)

_TRAILING_ROLE_SUFFIXES = (
    "button",
    "tab",
    "버튼",
    "탭",
)


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_trailing_role_suffix(text: str) -> str:
    value = text
    for suffix in _TRAILING_ROLE_SUFFIXES:
        pattern = rf"(?:^|\s){re.escape(suffix)}$"
        value = re.sub(pattern, "", value).strip()
    return value


def normalize_label(text: str | None) -> str:
    if text is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    normalized = normalized.replace("\u00a0", " ")
    normalized = re.sub(r"[\r\n\t]+", " ", normalized)
    normalized = re.sub(r"[\"'`]+", "", normalized)
    normalized = re.sub(r"[,:;.!?()\[\]{}<>/\\|_-]+", " ", normalized)
    normalized = _collapse_whitespace(normalized)
    normalized = _strip_trailing_role_suffix(normalized)
    return _collapse_whitespace(normalized)


def _aliases_for_key(key: str) -> tuple[str, ...]:
    return LABEL_ALIASES.get(str(key or "").strip(), ())


def expand_verify_token_aliases(tokens: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    expanded: list[str] = []
    seen: set[str] = set()
    for token in tokens or ():
        raw_token = str(token or "").strip()
        if not raw_token:
            continue
        normalized_token = raw_token.casefold()
        candidates = (raw_token, *VERIFY_TOKEN_ALIASES.get(normalized_token, ()))
        for candidate in candidates:
            normalized_candidate = str(candidate or "").strip().casefold()
            if not normalized_candidate or normalized_candidate in seen:
                continue
            seen.add(normalized_candidate)
            expanded.append(normalized_candidate)
    return tuple(expanded)


def _tokenize(text: str) -> tuple[str, ...]:
    normalized = normalize_label(text)
    return tuple(part for part in normalized.split(" ") if part)


def _contains_token_sequence(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    last_start = len(haystack) - len(needle)
    return any(haystack[start : start + len(needle)] == needle for start in range(last_start + 1))


def matches_alias(text: str | None, key: str, *, mode: str = "exact") -> bool:
    aliases = _aliases_for_key(key)
    if not aliases:
        return False

    normalized_text = normalize_label(text)
    if not normalized_text:
        return False

    normalized_aliases = tuple(normalize_label(alias) for alias in aliases)
    normalized_aliases = tuple(alias for alias in normalized_aliases if alias)
    if not normalized_aliases:
        return False

    normalized_mode = str(mode or "exact").strip().casefold()
    if normalized_mode == "exact":
        return normalized_text in normalized_aliases
    if normalized_mode == "contains":
        return any(alias in normalized_text for alias in normalized_aliases)
    if normalized_mode == "token":
        text_tokens = _tokenize(normalized_text)
        return any(_contains_token_sequence(text_tokens, _tokenize(alias)) for alias in normalized_aliases)
    return False


def _canonicalize_bottom_tab(text: str | None) -> str | None:
    for key, canonical in _BOTTOM_TAB_CANONICAL_KEYS:
        if matches_alias(text, key, mode="token") or matches_alias(text, key, mode="contains"):
            return canonical
    return None


def _canonicalize_local_tab(text: str | None) -> str | None:
    normalized = normalize_label(text)
    if not normalized:
        return None
    normalized = re.sub(r"\s+\d+\s+new notifications?$", "", normalized).strip()
    normalized = re.sub(r"\s+new notifications?$", "", normalized).strip()
    normalized = re.sub(r"\s+new notification$", "", normalized).strip()
    normalized = re.sub(r"\s+\d+\s+새\s+알림$", "", normalized).strip()
    normalized = re.sub(r"\s+새\s+알림$", "", normalized).strip()
    normalized = re.sub(r"\s+알림$", "", normalized).strip()
    normalized = re.sub(r"\s+새\s+콘텐츠\s+사용\s+가능$", "", normalized).strip()
    for key, canonical in _LOCAL_TAB_CANONICAL_KEYS:
        if matches_alias(normalized, key, mode="exact"):
            return canonical
    return _collapse_whitespace(normalized) or None


def canonicalize_label(text: str | None, *, domain: str) -> str | None:
    normalized_domain = str(domain or "").strip().casefold()
    if normalized_domain == "bottom_tab":
        return _canonicalize_bottom_tab(text)
    if normalized_domain in {"local_tab", "generic"}:
        return _canonicalize_local_tab(text)
    return None
