"""Parse runtime logs and print baseline acceptance summaries.

Usage:
    python tools/runtime_report_parser.py output/talkback_compare_*.log
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


STOP_REASON_RE = re.compile(r"\[STOP\]\[summary\].*?\breason=(?:'([^']*)'|(\S+))")
TOTAL_STEPS_RE = re.compile(r"\[PERF\]\[scenario_summary\].*?\btotal_steps=(\d+)")
SAVE_ROWS_RE = re.compile(r"\[SAVE\]\s+filtered rows=(\d+),?\s+raw rows=(\d+)")
LABEL_FIELD_RE = re.compile(r"\b(visible|visible_label|speech|merged_announcement)='([^']*)'")

DEFAULT_SCENARIO = "life_family_care_plugin"
DEFAULT_EXPECTED_LABELS = ["Medication", "Hospital", "Event"]
SCENARIO_EXPECTED_LABELS = {
    "life_family_care_plugin": {
        "ready": {
            "add_family_member": [
                "Add family member",
                "가족 구성원 추가",
            ],
            "profile": [
                "Profile",
                "View profile",
                "프로필 보기",
            ],
            "active_now": [
                "Active now",
                "지금 활동 중",
            ],
            "me": [
                "Me",
                "나",
            ],
        },
        "initial": [],
    },
    "life_air_care_plugin": {
        "ready": {
            "outdoor_air_quality": [
                "Outdoor air quality",
                "실외 공기질",
                "실외 공기(미세먼지)",
            ],
            "set_geolocation": [
                "Set geolocation to monitor outdoor air quality",
                "실외 공기질 모니터링을 위해 위치를 설정하세요",
                "위치 설정",
            ],
        },
        "initial": {
            "dismiss": [
                "Dismiss",
                "닫기",
                "지우기",
            ],
        },
    },
    "life_home_care_plugin": {
        "ready": {
            "home_care": [
                "Home Care",
                "홈 케어",
                "홈케어",
            ],
            "samsung_appliances": [
                "Samsung appliances",
                "삼성 가전 기기",
                "가전 기기",
            ],
            "smart_management": [
                "Smart management",
                "똑똑한 관리",
            ],
            "device_care": ["Device care"],
            "usage_guide": ["Usage guide"],
            "smart_forward": ["Smart Forward"],
        },
        "initial": ["Start"],
    },
    "life_energy_plugin": {
        "ready": {
            "energy_title": [
                "SmartThings Energy",
                "Smart Energy",
                "Energy",
                "에너지",
            ],
            "carbon_emissions": [
                "Carbon emissions aware",
                "Carbon emissions",
                "탄소 배출량",
                "탄소 배출량 인사이트",
            ],
            "device_energy_usage": [
                "Device energy usage",
                "Energy usage",
                "기기 에너지 사용량",
            ],
            "ai_energy_mode": ["AI Energy Mode"],
            "energy_saving_tips": ["Energy saving tips"],
            "monitor": ["Monitor", "모니터링"],
            "save": ["Save", "절약"],
            "activity": ["Activity", "활동"],
        },
        "initial": [
            "Start",
        ],
    },
    "life_pet_care_plugin": {
        "ready": {
            "add_profile": [
                "Add profile",
                "프로필 추가",
            ],
            "enter_pet_info": [
                "Enter your pet information",
                "반려동물 정보를 입력하세요",
            ],
            "pet_location": [
                "Pet location",
                "Find where your pet is",
                "반려동물 위치 확인",
            ],
            "activity": [
                "Activity",
                "활동",
            ],
            "care": [
                "Care",
                "케어",
            ],
            "start_walk": ["Start walk"],
        },
        "initial": ["Start"],
    },
    "life_plant_care_plugin": {
        "ready": {
            "many_plants": [
                "Are you growing many plants in one place?",
                "한 장소에서 많은 식물을 키우고 있나요?",
            ],
            "needs_water": [
                "Needs water",
                "물 필요",
                "물 주기 필요",
            ],
            "to_do_soon": [
                "To do soon",
                "곧 할 일",
            ],
            "my_plants": [
                "My plants",
                "내 식물",
            ],
            "routines": [
                "Routines",
                "자동화",
            ],
        },
        "initial": [],
    },
    "life_clothing_care_plugin": {
        "ready": {
            "clothing_care": [
                "Clothing Care",
                "의류 관리",
                "클로딩 케어",
            ],
            "washing": [
                "Washing",
                "세탁",
            ],
            "drying": [
                "Drying",
                "건조",
            ],
            "airdresser": [
                "AirDresser",
                "에어드레서",
            ],
            "shoedresser": [
                "ShoeDresser",
                "슈드레서",
            ],
            "blanket_care": ["It's time to care for your blanket"],
            "bedding_cycle": ["Try Bedding cycle"],
            "schedule": ["Schedule"],
        },
        "initial": [
            "Start",
        ],
    },
    "life_find_plugin": {
        "ready": {
            "find_title": [
                "Smart Find",
                "Find",
                "파인드",
            ],
        },
        "initial": [
            "Allow location access",
            "Turn on location",
            "No devices found",
            "Find your device",
        ],
    },
    "life_video_plugin": {
        "ready": {
            "video_title": [
                "Smart Video",
                "Video",
                "비디오",
            ],
        },
        "initial": [
            "Experience smarter care",
            "Discover exciting new AI",
            "Get alerts for only the objects you've selected",
            "Continue",
        ],
    },
    "life_home_monitor_plugin": {
        "ready": {
            "home_monitor_title": [
                "Home Monitor",
                "홈 모니터",
            ],
            "security": [
                "Security",
                "보안",
            ],
            "smoke": [
                "Smoke",
                "연기",
            ],
            "water_leak": [
                "Water leak",
                "누수",
            ],
        },
        "initial": {
            "tap_to_set_up": [
                "Tap to set up",
            ],
        },
    },
    "life_music_sync_plugin": {
        "ready": {
            "music_sync_title": [
                "Music Sync",
                "조명을 음악에 어울리도록 동기화",
                "조명과 음악을 동기화",
                "음악 동기화",
            ],
        },
        "initial": {},
    },
    "life_food_plugin": {
        "ready": {
            "food_title": [
                "Smart Things Cooking",
                "SmartThings Cooking",
                "Food",
                "푸드",
            ],
            "recipe_optimized": ["Recipe optimized for Samsung Oven"],
            "meal_planner": ["Add to Meal planner"],
            "saved_recipes": ["Saved recipes"],
            "ingredients": ["Ingredients"],
        },
        "initial": {
            "food_title": [
                "Smart Things Cooking",
                "SmartThings Cooking",
                "Food",
                "푸드",
            ],
            "expert_recipes": ["Cook like an expert with customized recipes"],
            "start": ["Start"],
        },
    },
    "settings_entry_example": {
        "ready": {
            "smartthings_settings": [
                "SmartThings settings",
                "스마트싱스 설정",
            ],
            "app_update": [
                "App update",
                "Update app",
                "App updates",
                "앱 업데이트",
            ],
            "location_sharing": [
                "Location sharing notification",
                "위치정보 공유 알림",
            ],
        },
        "initial": [],
    },
}
EXPECTED_LABELS = SCENARIO_EXPECTED_LABELS
NOISE_LABELS = {
    "home",
    "devices",
    "life",
    "routines",
    "menu",
    "navigate",
    "navigate up",
    "back",
    "current location",
    "place",
    "map",
    "change view",
    "last updated",
}


@dataclass(frozen=True)
class RuntimeSummary:
    path: Path
    scenario: str
    expected_labels: tuple[str, ...]
    reached_labels: dict[str, bool]
    ready_expected_labels: tuple[str, ...]
    initial_expected_labels: tuple[str, ...]
    ready_matched_labels: tuple[str, ...]
    initial_matched_labels: tuple[str, ...]
    ready_matched_groups: tuple[str, ...]
    initial_matched_groups: tuple[str, ...]
    ready_match_details: tuple[str, ...]
    initial_match_details: tuple[str, ...]
    baseline_status: str
    detected_state: str
    fatal: bool
    adb_timeout: bool
    stop_reason: str | None
    total_steps: int | None
    raw_rows: int | None
    filtered_rows: int | None
    reached_medication: bool
    reached_hospital: bool
    reached_event: bool
    local_tab_force_navigation_set: int
    local_tab_commit: int

    @property
    def baseline_pass(self) -> bool:
        return self.baseline_status in {"baseline_pass", "initial_state"}

    @property
    def baseline_reason(self) -> str:
        if self.fatal:
            return "fatal_detected"
        if self.baseline_status == "baseline_pass" and not self.expected_labels:
            return "ok_no_expected_labels"
        if self.baseline_status == "baseline_pass":
            return "ok"
        if self.baseline_status == "initial_state":
            return "initial_state_detected"
        if self.stop_reason != "safety_limit":
            return "wrong_stop_reason"
        if not self.ready_expected_labels and not self.initial_expected_labels:
            return "ok_no_expected_labels"
        missing_labels = [
            label for label in self.ready_expected_labels if label not in self.ready_matched_labels
        ]
        if missing_labels:
            return f"missing_{missing_labels[0].lower().replace(' ', '_')}"
        return "baseline_fail"


def _expand_inputs(patterns: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = [Path(match) for match in glob.glob(pattern)]
        if matches:
            paths.extend(matches)
        else:
            paths.append(Path(pattern))
    return paths


def _last_int_match(regex: re.Pattern[str], text: str) -> int | None:
    value: int | None = None
    for match in regex.finditer(text):
        value = int(match.group(1))
    return value


def _last_stop_reason(text: str) -> str | None:
    value: str | None = None
    for match in STOP_REASON_RE.finditer(text):
        value = match.group(1) or match.group(2)
    return value


def _last_save_rows(text: str) -> tuple[int | None, int | None]:
    filtered_rows: int | None = None
    raw_rows: int | None = None
    for match in SAVE_ROWS_RE.finditer(text):
        filtered_rows = int(match.group(1))
        raw_rows = int(match.group(2))
    return raw_rows, filtered_rows


def _has_adb_timeout(text: str) -> bool:
    for line in text.splitlines():
        lowered = line.lower()
        if "adb" in lowered and ("timeout" in lowered or "timed out" in lowered):
            return True
    return False


def _is_address_like(label: str) -> bool:
    return bool(
        re.search(
            r"\b\d{1,6}\s+[\w .'-]+\b(st|street|rd|road|ave|avenue|blvd|drive|dr|lane|ln)\b",
            label,
            flags=re.IGNORECASE,
        )
    )


def _is_numeric_time_or_date_like(label: str) -> bool:
    digit_count = sum(ch.isdigit() for ch in label)
    alpha_count = sum(ch.isalpha() for ch in label)
    if digit_count >= 2 and digit_count >= alpha_count:
        return True
    compact = re.sub(r"[\s:/.,%+-]", "", label)
    if compact and sum(ch.isdigit() for ch in compact) / len(compact) >= 0.7:
        return True
    return bool(
        re.fullmatch(
            r"(?i)(\d{1,2}:\d{2}\s*(am|pm)?|\d{1,4}([./-]\d{1,2}){1,2}|[ap]m)",
            label.strip(),
        )
    )


def _is_noise_label(label: str) -> bool:
    normalized = re.sub(r"\s+", " ", label).strip()
    if not normalized or len(normalized) <= 1:
        return True
    lowered = normalized.lower()
    if lowered in NOISE_LABELS:
        return True
    if _is_address_like(normalized):
        return True
    if _is_numeric_time_or_date_like(normalized):
        return True
    return False


def extract_label_candidates(text: str) -> Counter[str]:
    candidates: Counter[str] = Counter()
    for match in LABEL_FIELD_RE.finditer(text):
        label = re.sub(r"\s+", " ", match.group(2)).strip()
        if not _is_noise_label(label):
            candidates[label] += 1
    return candidates


def suggest_expected_labels(text: str, limit: int = 10) -> list[str]:
    if limit <= 0:
        return []
    candidates = extract_label_candidates(text)
    return [label for label, _count in candidates.most_common(limit)]


def _match_threshold(labels: tuple[str, ...], *, initial: bool = False) -> int:
    if not labels:
        return 0
    if initial:
        return 1
    return min(2, len(labels))


def _normalize_expected_label_config(
    config: object,
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    if isinstance(config, dict):
        ready = config.get("ready", [])
        initial = config.get("initial", [])
        ready_labels, ready_groups = _normalize_expected_label_section(ready)
        initial_labels, initial_groups = _normalize_expected_label_section(initial)
        return ready_labels, initial_labels, ready_groups, initial_groups
    if config is None:
        return (), (), {}, {}
    ready_labels, ready_groups = _normalize_expected_label_section(config)
    return ready_labels, (), ready_groups, {}


def _normalize_expected_label_section(section: object) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    if isinstance(section, dict):
        groups: dict[str, tuple[str, ...]] = {}
        for group, aliases in section.items():
            group_name = str(group or "").strip()
            if not group_name:
                continue
            if isinstance(aliases, str):
                alias_values = (aliases,)
            else:
                alias_values = tuple(str(alias or "").strip() for alias in aliases or ())
            alias_values = tuple(alias for alias in alias_values if alias)
            if alias_values:
                groups[group_name] = alias_values
        return tuple(groups.keys()), groups
    if isinstance(section, str):
        return ((section,) if section else ()), {}
    return tuple(str(label or "").strip() for label in section or () if str(label or "").strip()), {}


def _resolve_expected_labels(
    *,
    scenario: str | None = None,
    expected_labels: Iterable[str] | None = None,
) -> tuple[str, tuple[str, ...], tuple[str, ...], dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    resolved_scenario = scenario or DEFAULT_SCENARIO
    if expected_labels is not None:
        labels = tuple(label for label in expected_labels if label)
        return resolved_scenario, labels, (), {}, {}
    return (resolved_scenario, *_normalize_expected_label_config(
        SCENARIO_EXPECTED_LABELS.get(resolved_scenario, DEFAULT_EXPECTED_LABELS)
    ))


def _normalize_match_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = normalized.replace("\u00a0", " ")
    normalized = re.sub(r"[\r\n\t]+", " ", normalized)
    normalized = re.sub(r"[\"'`]+", "", normalized)
    normalized = re.sub(r"[,:;.!?()\[\]{}<>/\\|_-]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _alias_matches_text(alias: str, text: str, normalized_text: str) -> bool:
    alias_value = str(alias or "").strip()
    if not alias_value:
        return False
    if alias_value in text:
        return True
    normalized_alias = _normalize_match_text(alias_value)
    if not normalized_alias:
        return False
    if len(normalized_alias) <= 2:
        return normalized_text == normalized_alias or f" {normalized_alias} " in f" {normalized_text} "
    return normalized_alias in normalized_text


def _matched_labels(labels: tuple[str, ...], text: str) -> tuple[str, ...]:
    return tuple(label for label in labels if label in text)


def _matched_label_groups(groups: dict[str, tuple[str, ...]], text: str) -> tuple[tuple[str, str, str], ...]:
    normalized_text = _normalize_match_text(text)
    matches: list[tuple[str, str, str]] = []
    for group, aliases in groups.items():
        for alias in aliases:
            if _alias_matches_text(alias, text, normalized_text):
                matches.append((group, alias, alias))
                break
    return tuple(matches)


def _evaluate_baseline_status(
    *,
    fatal: bool,
    stop_reason: str | None,
    ready_expected_labels: tuple[str, ...],
    ready_matched_labels: tuple[str, ...],
    initial_expected_labels: tuple[str, ...],
    initial_matched_labels: tuple[str, ...],
) -> tuple[str, str]:
    if fatal:
        return "baseline_fail", "unknown"

    ready_threshold = _match_threshold(ready_expected_labels)
    if ready_threshold and len(ready_matched_labels) >= ready_threshold:
        return "baseline_pass", "ready"

    initial_threshold = _match_threshold(initial_expected_labels, initial=True)
    if initial_threshold and len(initial_matched_labels) >= initial_threshold:
        return "initial_state", "initial"

    if not ready_expected_labels and not initial_expected_labels and stop_reason == "safety_limit":
        return "baseline_pass", "unknown"
    if (
        stop_reason == "safety_limit"
        and ready_expected_labels
        and len(ready_matched_labels) == len(ready_expected_labels)
    ):
        return "baseline_pass", "ready"
    return "baseline_fail", "unknown"


def _join_labels(labels: Iterable[str]) -> str:
    return ",".join(labels)


def _legacy_reached_labels(
    ready_expected_labels: tuple[str, ...],
    ready_matched_labels: tuple[str, ...],
) -> dict[str, bool]:
    return {
        label: label in ready_matched_labels
        for label in ready_expected_labels
    }


def _all_expected_labels(
    ready_expected_labels: tuple[str, ...],
    initial_expected_labels: tuple[str, ...],
) -> tuple[str, ...]:
    return (
        ready_expected_labels
        + tuple(label for label in initial_expected_labels if label not in ready_expected_labels)
    )


def parse_log(
    path: Path,
    *,
    scenario: str | None = None,
    expected_labels: Iterable[str] | None = None,
) -> RuntimeSummary:
    text = path.read_text(encoding="utf-8", errors="replace")
    adb_timeout = _has_adb_timeout(text)
    fatal = "Traceback" in text or "[ERROR]" in text or adb_timeout
    raw_rows, filtered_rows = _last_save_rows(text)
    (
        resolved_scenario,
        ready_expected_labels,
        initial_expected_labels,
        ready_expected_groups,
        initial_expected_groups,
    ) = _resolve_expected_labels(
        scenario=scenario,
        expected_labels=expected_labels,
    )
    ready_group_matches = _matched_label_groups(ready_expected_groups, text)
    initial_group_matches = _matched_label_groups(initial_expected_groups, text)
    ready_matched_labels = (
        tuple(group for group, _alias, _source in ready_group_matches)
        if ready_expected_groups
        else _matched_labels(ready_expected_labels, text)
    )
    initial_matched_labels = (
        tuple(group for group, _alias, _source in initial_group_matches)
        if initial_expected_groups
        else _matched_labels(initial_expected_labels, text)
    )
    baseline_status, detected_state = _evaluate_baseline_status(
        fatal=fatal,
        stop_reason=_last_stop_reason(text),
        ready_expected_labels=ready_expected_labels,
        ready_matched_labels=ready_matched_labels,
        initial_expected_labels=initial_expected_labels,
        initial_matched_labels=initial_matched_labels,
    )
    reached_labels = _legacy_reached_labels(ready_expected_labels, ready_matched_labels)
    return RuntimeSummary(
        path=path,
        scenario=resolved_scenario,
        expected_labels=_all_expected_labels(ready_expected_labels, initial_expected_labels),
        reached_labels=reached_labels,
        ready_expected_labels=ready_expected_labels,
        initial_expected_labels=initial_expected_labels,
        ready_matched_labels=ready_matched_labels,
        initial_matched_labels=initial_matched_labels,
        ready_matched_groups=tuple(group for group, _alias, _source in ready_group_matches),
        initial_matched_groups=tuple(group for group, _alias, _source in initial_group_matches),
        ready_match_details=tuple(f"{group}:{alias}" for group, alias, _source in ready_group_matches),
        initial_match_details=tuple(f"{group}:{alias}" for group, alias, _source in initial_group_matches),
        baseline_status=baseline_status,
        detected_state=detected_state,
        fatal=fatal,
        adb_timeout=adb_timeout,
        stop_reason=_last_stop_reason(text),
        total_steps=_last_int_match(TOTAL_STEPS_RE, text),
        raw_rows=raw_rows,
        filtered_rows=filtered_rows,
        reached_medication="Medication" in text,
        reached_hospital="Hospital" in text,
        reached_event="Event" in text,
        local_tab_force_navigation_set=text.count("[STEP][local_tab_force_navigation_set]"),
        local_tab_commit=text.count("[STEP][local_tab_commit]"),
    )


def _format_value(value: object) -> str:
    if value is None:
        return "None"
    return str(value)


def _label_output_name(label: str) -> str:
    return re.sub(r"\W+", "_", label).strip("_")


def print_summary(summary: RuntimeSummary, *, include_path: bool) -> None:
    if include_path:
        print(f"[BASELINE][file] path={summary.path}")
    print("[BASELINE][summary]")
    print(f"scenario={summary.scenario}")
    print(f"expected_labels={_join_labels(summary.expected_labels)}")
    print(f"baseline_status={summary.baseline_status}")
    print(f"detected_state={summary.detected_state}")
    print(f"ready_expected_count={len(summary.ready_expected_labels)}")
    print(f"ready_matched_count={len(summary.ready_matched_labels)}")
    print(f"ready_matched_labels={_join_labels(summary.ready_matched_labels)}")
    print(f"ready_matched_groups={_join_labels(summary.ready_matched_groups)}")
    print(f"ready_match_details={_join_labels(summary.ready_match_details)}")
    print(f"initial_expected_count={len(summary.initial_expected_labels)}")
    print(f"initial_matched_count={len(summary.initial_matched_labels)}")
    print(f"initial_matched_labels={_join_labels(summary.initial_matched_labels)}")
    print(f"initial_matched_groups={_join_labels(summary.initial_matched_groups)}")
    print(f"initial_match_details={_join_labels(summary.initial_match_details)}")
    print(f"fatal={summary.fatal}")
    print(f"stop_reason={_format_value(summary.stop_reason)}")
    print(f"total_steps={_format_value(summary.total_steps)}")
    print(f"raw_rows={_format_value(summary.raw_rows)}")
    print(f"filtered_rows={_format_value(summary.filtered_rows)}")
    for label, reached in summary.reached_labels.items():
        print(f"reached_{_label_output_name(label)}={reached}")
    print(f"reached_medication={summary.reached_medication}")
    print(f"reached_hospital={summary.reached_hospital}")
    print(f"reached_event={summary.reached_event}")
    print(f"local_tab_force_navigation_set={summary.local_tab_force_navigation_set}")
    print(f"local_tab_commit={summary.local_tab_commit}")
    print(f"baseline_pass={summary.baseline_pass}")
    print(f"baseline_reason={summary.baseline_reason}")


def print_aggregate(summaries: list[RuntimeSummary]) -> None:
    total_steps = [summary.total_steps for summary in summaries if summary.total_steps is not None]
    failed = [summary for summary in summaries if not summary.baseline_pass]
    print("[BASELINE][aggregate]")
    print(f"runs={len(summaries)}")
    print(f"passed={len(summaries) - len(failed)}")
    print(f"failed={len(failed)}")
    if total_steps:
        avg_steps = sum(total_steps) / len(total_steps)
        print(f"total_steps_min={min(total_steps)}")
        print(f"total_steps_max={max(total_steps)}")
        print(f"total_steps_avg={avg_steps:.1f}")
    if failed:
        print("failed_runs=")
        for summary in failed:
            print(f"- {summary.path}: {summary.baseline_reason}")


def print_label_suggestions(
    candidates: Counter[str],
    *,
    scenario: str | None,
    limit: int = 10,
) -> None:
    labels_with_counts = candidates.most_common(max(limit, 0))
    labels = [label for label, _count in labels_with_counts]
    print("[LABEL_SUGGESTION][top]")
    for label, count in labels_with_counts:
        print(f"{label}={count}")
    print()
    print("[LABEL_SUGGESTION][python]")
    print(f'"{scenario or "unknown"}": {labels!r},')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse TalkBack runner logs and print baseline acceptance summaries."
    )
    parser.add_argument("logs", nargs="+", help="Log path(s) or glob pattern(s).")
    parser.add_argument(
        "--scenario",
        help="Scenario id used to select expected labels. Defaults to life_family_care_plugin.",
    )
    parser.add_argument(
        "--expected-label",
        action="append",
        dest="expected_label",
        help="Expected label. Can be passed multiple times and overrides scenario defaults.",
    )
    parser.add_argument(
        "--expected-labels",
        help="Comma-separated expected labels. Overrides scenario defaults.",
    )
    parser.add_argument(
        "--suggest-labels",
        action="store_true",
        help="Print candidate expected labels extracted from visible/speech runtime log fields.",
    )
    parser.add_argument(
        "--suggest-label-limit",
        type=int,
        default=10,
        help="Maximum number of suggested labels to print. Defaults to 10.",
    )
    args = parser.parse_args(argv)

    custom_expected_labels = None
    if args.expected_labels:
        custom_expected_labels = [
            label.strip() for label in args.expected_labels.split(",") if label.strip()
        ]
    elif args.expected_label is not None:
        custom_expected_labels = [
            label.strip() for label in args.expected_label if label.strip()
        ]

    paths = _expand_inputs(args.logs)
    missing = [path for path in paths if not path.is_file()]
    if missing:
        for path in missing:
            print(f"[BASELINE][error] missing_log={path}", file=sys.stderr)
        return 2

    summaries = [
        parse_log(
            path,
            scenario=args.scenario,
            expected_labels=custom_expected_labels,
        )
        for path in paths
    ]
    multiple = len(summaries) > 1
    for index, summary in enumerate(summaries):
        if index:
            print()
        print_summary(summary, include_path=multiple)
    if multiple:
        print()
        print_aggregate(summaries)

    if args.suggest_labels:
        suggestion_candidates: Counter[str] = Counter()
        for path in paths:
            suggestion_candidates.update(
                extract_label_candidates(path.read_text(encoding="utf-8", errors="replace"))
            )
        print()
        print_label_suggestions(
            suggestion_candidates,
            scenario=args.scenario,
            limit=args.suggest_label_limit,
        )

    return 0 if all(summary.baseline_pass for summary in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
