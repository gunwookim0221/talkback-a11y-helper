"""Replay the preserved Scenario 31 click through the bounded verifier offline."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phase5c_entry_offline_replay import _replay_source
from tb_runner.entry_safety import click_events, map_click_source_to_target, resolve_navigation_owner, authorize_entry, verify_actual_hit


DEFAULT_FOLDER = Path("out/phase5c_entry_fix_20261014/full32/31_life_home_monitor_plugin")
EXPECTED_TRANSACTION = "35eefd85362c402bbcb972ac2af44d99"
EXPECTED_RESOURCE_ID = "com.samsung.android.oneconnect:id/monitorHeaderGroup"
EXPECTED_BOUNDS = "30,1421,1050,1469"
EXPECTED_POINT = [540, 1445]
WINDOW_MS = 1000
PACKAGE = "com.samsung.android.oneconnect"


def _read_audit(folder: Path) -> list[dict[str, Any]]:
    rows = []
    with (folder / "phase5c_entry_actions.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _event_clock_ms(line: str) -> int | None:
    match = re.search(r"time=(\d{9,})", line)
    if not match:
        return None
    raw = int(match.group(1))
    return raw // 1_000_000 if raw > 10**12 else raw


def _wall_time_ms(line: str) -> int | None:
    match = re.match(r"\d{2}-\d{2} (\d{2}):(\d{2}):(\d{2})\.(\d+)", line)
    if not match:
        return None
    hour, minute, second, fraction = match.groups()
    millis = int((fraction + "000")[:3])
    return ((int(hour) * 60 + int(minute)) * 60 + int(second)) * 1000 + millis


def replay(folder: Path = DEFAULT_FOLDER) -> dict[str, Any]:
    rows = _read_audit(folder)
    authorization = next(row for row in rows if row.get("event") == "ENTRY_AUTHORIZATION")
    dispatch = next(row for row in rows if row.get("event") == "ENTRY_DISPATCH")
    old_hit = next(row for row in rows if row.get("event") == "ENTRY_ACTUAL_HIT")
    transaction_id = str(authorization.get("transaction_id") or "")
    target = authorization.get("resolved_owner") or {}
    permit_target = authorization.get("resolved_owner") or {}

    roots, selected, phrase, old_tap, _snapshot_request = _replay_source(folder)
    resolution = resolve_navigation_owner(roots, selected, phrase)
    permit = authorize_entry(resolution, roots, scenario="life_home_monitor_plugin", matched_phrase=phrase)
    log_lines = (folder / "logcat.txt").read_text(encoding="utf-8", errors="replace").splitlines()

    tap_text = f"input tap {EXPECTED_POINT[0]} {EXPECTED_POINT[1]}"
    tap_index = next((index for index, line in enumerate(log_lines) if tap_text in line), None)
    if tap_index is None:
        raise ValueError("Preserved authorized input tap is missing")
    input_line = log_lines[tap_index]
    motion_line = next((line for line in log_lines[tap_index + 1:]
                        if "InputDispatcher: Inject motion" in line and "time=" in line), None)
    if motion_line is None:
        raise ValueError("Preserved InputDispatcher event time is missing")
    dispatch_event_uptime_ms = _event_clock_ms(motion_line)
    if dispatch_event_uptime_ms is None:
        raise ValueError("InputDispatcher event time could not be parsed")
    deadline_uptime_ms = dispatch_event_uptime_ms + WINDOW_MS

    parsed = click_events("\n".join(log_lines))
    candidates = []
    for event in parsed.values():
        try:
            event_uptime_ms = int(event.get("event_time"))
        except (TypeError, ValueError):
            continue
        if dispatch_event_uptime_ms < event_uptime_ms <= deadline_uptime_ms:
            candidates.append(event)

    click_event = next((event for event in candidates if event.get("package") == PACKAGE
                        and "home monitor" in str(event.get("text") or "").lower()), None)
    if click_event is None:
        mapping = dict(status="INSUFFICIENT", reason="EXPECTED_CLICK_NOT_FOUND", candidates=[])
        hit = dict(matched=False, reason="EXPECTED_CLICK_NOT_FOUND", evidence_strength="INSUFFICIENT")
    else:
        mapping = map_click_source_to_target(click_event, permit, roots)
        # The preserved line has no explicit transaction ID. Temporal ownership
        # is replayed from the one authorized tap, its monotonic input event, and
        # the bounded 1s window. Live collection records the Helper request ID.
        hit = verify_actual_hit(
            permit, {}, candidates, roots=roots,
            dispatch_uptime_ms=dispatch_event_uptime_ms,
            collection=dict(deadline_uptime_ms=deadline_uptime_ms,
                            activity_transition=True),
        )

    click_line = next((line for line in log_lines if "EventTime: 878142546" in line
                       and "TYPE_VIEW_CLICKED" in line), "")
    activity_line = next((line for line in log_lines if "START u0 {" in line
                          and "HomeMonitorMainActivity" in line), "")
    click_wall = _wall_time_ms(click_line) if click_line else None
    tap_wall = _wall_time_ms(input_line)
    output_delay_ms = click_wall - tap_wall if click_wall is not None and tap_wall is not None else None
    source_mapping = mapping.get("status", "INSUFFICIENT")
    competing_count = max(0, len(candidates) - 1)
    target_matches = bool(
        permit.get("authorized")
        and permit_target.get("resource_id") == EXPECTED_RESOURCE_ID
        and permit_target.get("bounds") == EXPECTED_BOUNDS
        and permit.get("point") == tuple(EXPECTED_POINT)
        and target == permit_target
    )
    timing_proven = bool(click_event and dispatch_event_uptime_ms < int(click_event["event_time"])
                         <= deadline_uptime_ms and output_delay_ms is not None
                         and 0 <= output_delay_ms <= WINDOW_MS)
    actual_hit_proven = bool(hit.get("matched") and source_mapping in {"EXACT", "STRONG_UNIQUE"}
                             and len(candidates) == 1 and competing_count == 0 and target_matches)
    replay_pass = bool(timing_proven and actual_hit_proven and activity_line and
                       transaction_id == EXPECTED_TRANSACTION
                       and dispatch.get("dispatched_point") == EXPECTED_POINT
                       and old_hit.get("matched") is False)

    return dict(
        schema="phase5c-click-correlation-offline-replay-v1",
        verdict="PASS" if replay_pass else "REJECT",
        scenario="life_home_monitor_plugin",
        transaction_id=transaction_id,
        authorized_target=target,
        authorized_bounds=EXPECTED_BOUNDS,
        authorized_tap=EXPECTED_POINT,
        dispatch_wall_time=input_line[:18],
        input_event_uptime_ms=dispatch_event_uptime_ms,
        collection_window_ms=WINDOW_MS,
        deadline_uptime_ms=deadline_uptime_ms,
        click_event_time=click_event.get("event_time") if click_event else None,
        click_event_log_time=click_event.get("log_output_timestamp") if click_event else None,
        event_uptime_delta_ms=(int(click_event["event_time"]) - dispatch_event_uptime_ms
                               if click_event else None),
        output_delay_after_tap_ms=output_delay_ms,
        delayed_event_captured_by_window="YES" if timing_proven else "NO",
        event_within_transaction_window="YES" if timing_proven else "NO",
        event_source_mapping=source_mapping,
        source_mapping_evidence=mapping,
        click_event_count=len(candidates),
        competing_event_count=competing_count,
        event_bounds=click_event.get("bounds") if click_event else None,
        event_source_node_id=click_event.get("source_node_id") if click_event else None,
        event_resource_id=click_event.get("resource_id") if click_event else None,
        event_window_id=click_event.get("window_id") if click_event else None,
        activity_transition_observed=bool(activity_line),
        activity_corroboration_used="SECONDARY_ONLY" if actual_hit_proven else "NO",
        actual_hit_verdict="ACCEPT_STRONG_UNIQUE_OFFLINE_REPLAY" if actual_hit_proven else "REJECT",
        historical_runtime_actual_hit="REJECT" if old_hit.get("matched") is False else "UNAVAILABLE",
        historical_event_transaction_id="ABSENT",
        offline_transaction_association="SINGLE_DISPATCH_MONOTONIC_TIME_WINDOW",
        source_to_target_mapping_proven=actual_hit_proven,
        old_runtime_audit=old_hit,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = replay(arguments.folder)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized + "\n", encoding="utf-8")
    raise SystemExit(0 if report["verdict"] == "PASS" else 1)
