"""Parse runtime logs and print baseline acceptance summaries.

Usage:
    python tools/runtime_report_parser.py output/talkback_compare_*.log
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


STOP_REASON_RE = re.compile(r"\[STOP\]\[summary\].*?\breason=(?:'([^']*)'|(\S+))")
TOTAL_STEPS_RE = re.compile(r"\[PERF\]\[scenario_summary\].*?\btotal_steps=(\d+)")
SAVE_ROWS_RE = re.compile(r"\[SAVE\]\s+filtered rows=(\d+),?\s+raw rows=(\d+)")
LABEL_FIELD_RE = re.compile(r"\b(visible|visible_label|speech|merged_announcement)='([^']*)'")

DEFAULT_SCENARIO = "life_family_care_plugin"
DEFAULT_EXPECTED_LABELS = ["Medication", "Hospital", "Event"]
SCENARIO_EXPECTED_LABELS = {
    "life_family_care_plugin": DEFAULT_EXPECTED_LABELS,
    "life_air_care_plugin": [],
    "life_home_care_plugin": [],
    "life_energy_plugin": [],
    "life_pet_care_plugin": [],
    "life_plant_care_plugin": [],
    "life_clothing_care_plugin": [],
    "life_find_plugin": [],
    "life_video_plugin": [],
    "life_home_monitor_plugin": [],
    "life_music_sync_plugin": [],
    "life_food_plugin": [],
}
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
        return (
            not self.fatal
            and self.stop_reason == "safety_limit"
            and all(self.reached_labels.values())
        )

    @property
    def baseline_reason(self) -> str:
        if self.fatal:
            return "fatal_detected"
        if self.stop_reason != "safety_limit":
            return "wrong_stop_reason"
        if not self.expected_labels:
            return "ok_no_expected_labels"
        for label, reached in self.reached_labels.items():
            if not reached:
                return f"missing_{label.lower().replace(' ', '_')}"
        if self.local_tab_force_navigation_set < 3:
            return "low_local_tab_navigation"
        return "ok"


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


def _resolve_expected_labels(
    *,
    scenario: str | None = None,
    expected_labels: Iterable[str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    resolved_scenario = scenario or DEFAULT_SCENARIO
    if expected_labels is not None:
        labels = tuple(label for label in expected_labels if label)
        return resolved_scenario, labels
    return resolved_scenario, tuple(
        SCENARIO_EXPECTED_LABELS.get(resolved_scenario, DEFAULT_EXPECTED_LABELS)
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
    resolved_scenario, resolved_expected_labels = _resolve_expected_labels(
        scenario=scenario,
        expected_labels=expected_labels,
    )
    reached_labels = {label: label in text for label in resolved_expected_labels}
    return RuntimeSummary(
        path=path,
        scenario=resolved_scenario,
        expected_labels=resolved_expected_labels,
        reached_labels=reached_labels,
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
    print(f"expected_labels={','.join(summary.expected_labels)}")
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
