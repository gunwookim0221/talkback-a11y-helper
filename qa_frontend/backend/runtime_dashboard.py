from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import OUTPUT_DIR


SCENARIO_RE = re.compile(r"scenario='([^']+)'|scenario=([A-Za-z0-9_]+)|scenario_id='([^']+)'|scenario_id=([A-Za-z0-9_]+)")
STEP_RE = re.compile(r"step=(\d+)")
TOTAL_STEPS_RE = re.compile(r"total_steps=(\d+)")
ENABLED_IDS_RE = re.compile(r"enabled_ids=(\[[^\]]*\])")
FOCUS_PACKAGE_RE = re.compile(r"packageName': '([^']+)'|packageName=\"([^\"]+)\"|packageName=([^\s,]+)")
FOCUS_LABEL_RE = re.compile(r"talkbackLabel': '([^']+)'|focus_label='([^']*)'|visible='([^']*)'")
FINAL_RESULT_RE = re.compile(r"final_result='([^']+)'")
TRAVERSAL_RESULT_RE = re.compile(r"traversal_result='([^']+)'")
STOP_REASON_RE = re.compile(r"reason='([^']+)'")
POPUP_RESULT_RE = re.compile(r"\[QA_FRONTEND\]\[preflight\]\[popup\].*result='([^']*)'")
PREFLIGHT_FINAL_RE = re.compile(r"\[QA_FRONTEND\]\[preflight\] final_result='([^']*)'")
PRE_STATUS_RE = re.compile(r"\[QA_FRONTEND\]\[preflight\]\[(adb|helper)\] status='([^']*)'")
RUN_START_RE = re.compile(r"\[QA_FRONTEND\] start mode='([^']*)'.*launch_mode='([^']*)'(?:.*language_mode='([^']*)')?")
LANGUAGE_RE = re.compile(r"\[QA_FRONTEND\]\[language\].*language_mode='([^']*)'.*device_locale='([^']*)'")
SAVED_EXCEL_RE = re.compile(r"saved excel:\s+output/(?P<filename>[^/\s]+\.xlsx)", re.IGNORECASE)
ACCESSIBILITY_PASS_MISMATCH_TYPES = {
    "EXACT_MATCH",
    "NORMALIZED_MATCH",
    "PARTIAL_MATCH",
    "REPRESENTATIVE_CONTEXT",
}
SCENARIO_HARD_MISMATCH_TYPES = {
    "EMPTY_VISIBLE",
    "EMPTY_SPEECH",
    "LABEL_MISMATCH",
}
TRANSIENT_PRESENTATION_FAILURE_REASONS = {
    "move_failed",
    "repeat_no_progress",
    "terminal_not_handled",
    "no_unvisited_local_tab",
    "viewport_exhausted",
}


def build_runtime_dashboard(
    *,
    status: dict[str, object],
    log_path: Path | None,
    scenario_ids: list[str] | None = None,
    parsed_log: dict[str, object] | None = None,
) -> dict[str, object]:
    started_at = _string_or_none(status.get("started_at"))
    dashboard = _empty_dashboard(status=status, started_at=started_at, scenario_ids=scenario_ids or [])
    if not log_path or not log_path.exists():
        return dashboard

    try:
        if parsed_log is not None:
            parsed = parsed_log
        else:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            validation_failed_scenarios, validation_warning_scenarios = extract_validation_scenario_evidence_from_log(log_text)
            parsed = parse_runtime_log(
                log_text,
                scenario_ids=scenario_ids or [],
                validation_failed_scenarios=validation_failed_scenarios,
                validation_warning_scenarios=validation_warning_scenarios,
            )
            parsed["log_size"] = log_path.stat().st_size
        dashboard.update(parsed)
    except Exception as exc:
        dashboard["parse_error"] = str(exc)

    dashboard["elapsed_seconds"] = _elapsed_seconds(started_at, _string_or_none(status.get("finished_at")))
    dashboard["run_id"] = status.get("run_id")
    dashboard["mode"] = status.get("mode")
    dashboard["launch_mode"] = status.get("launch_mode")
    dashboard["language_mode"] = status.get("language_mode")
    dashboard["device_locale"] = status.get("device_locale") or dashboard.get("device_locale")
    dashboard["state"] = status.get("state")
    dashboard["preflight_state"] = status.get("preflight_state") or dashboard.get("preflight_state")
    dashboard["popup_result"] = status.get("popup_result") or dashboard.get("popup_result")
    dashboard["helper_status"] = status.get("helper_state") or dashboard.get("helper_status")
    return dashboard


def parse_runtime_log(
    log_text: str,
    *,
    scenario_ids: list[str] | None = None,
    validation_failed_scenarios: set[str] | None = None,
    validation_warning_scenarios: set[str] | None = None,
) -> dict[str, object]:
    lines = log_text.splitlines()
    selected_ids = list(scenario_ids or []) or _extract_enabled_ids(log_text)
    selected_filter = set(selected_ids)
    progress = {scenario_id: {"id": scenario_id, "status": "queued", "steps": 0} for scenario_id in selected_ids}
    step_end_counts: dict[str, int] = {}
    summary_steps: dict[str, int] = {}
    entry_success_scenarios: set[str] = set()
    soft_entry_evidence_scenarios: set[str] = set()
    summary_scenarios: set[str] = set()
    global_nav_start_gate_passed: set[str] = set()
    global_nav_menu_reached: set[str] = set()
    global_nav_terminal: set[str] = set()
    events: list[dict[str, object]] = []
    current_scenario = None
    current_step = None
    total_step_count = 0
    overlay_count = 0
    save_excel_count = 0
    hard_failed_scenarios: set[str] = set(validation_failed_scenarios or set())
    warning_scenarios: set[str] = set(validation_warning_scenarios or set())
    last_focus_label = None
    last_focus_package = None
    stop_reason = None
    traversal_result = None
    popup_result = None
    preflight_state = None
    adb_status = None
    helper_status = None
    mode = None
    launch_mode = None
    language_mode = None
    device_locale = None

    for index, line in enumerate(lines):
        raw_scenario = _extract_scenario(line)
        scenario = raw_scenario if raw_scenario and (not selected_filter or raw_scenario in selected_filter) else None
        step = _extract_step(line)
        if scenario:
            current_scenario = scenario
            progress.setdefault(scenario, {"id": scenario, "status": "queued", "steps": 0})

        if "[GLOBAL_NAV][start_gate] passed" in line and scenario:
            global_nav_start_gate_passed.add(scenario)
        if scenario and _line_reaches_menu_tab(line):
            global_nav_menu_reached.add(scenario)
        if scenario and "[SCENARIO][entry_contract] success" in line:
            entry_success_scenarios.add(scenario)
        if scenario and "[ENTRY][post_open_identity]" in line and _has_plugin_entry_identity_evidence(scenario, line):
            soft_entry_evidence_scenarios.add(scenario)
        if scenario and "[SCENARIO][entry_contract]" in line and " fail" in line.lower():
            if "post_open_verify_miss" in line and scenario in soft_entry_evidence_scenarios:
                warning_scenarios.add(scenario)
                progress[scenario]["status"] = "warning"
                _add_event(events, index, "scenario_warning", line, scenario=scenario)
            else:
                hard_failed_scenarios.add(scenario)
                progress[scenario]["status"] = "failed"
                _add_event(events, index, "scenario_failed", line, scenario=scenario)

        if "[QA_FRONTEND] start" in line:
            run_match = RUN_START_RE.search(line)
            if run_match:
                mode = run_match.group(1)
                launch_mode = run_match.group(2)
                language_mode = run_match.group(3)
                _add_event(events, index, "run_started", line, scenario=None)
        elif "[QA_FRONTEND][language]" in line:
            language_match = LANGUAGE_RE.search(line)
            if language_match:
                language_mode = language_match.group(1)
                device_locale = language_match.group(2) or None
                _add_event(events, index, "language_ready", line, scenario=None)
        elif "[QA_FRONTEND][preflight][popup]" in line:
            popup_match = POPUP_RESULT_RE.search(line)
            if popup_match:
                popup_result = popup_match.group(1)
                _add_event(events, index, f"popup_{popup_result or 'observed'}", line, scenario=None)
        elif "[QA_FRONTEND][preflight]" in line:
            final_match = PREFLIGHT_FINAL_RE.search(line)
            if final_match:
                preflight_state = final_match.group(1)
                _add_event(events, index, f"preflight_{preflight_state or 'unknown'}", line, scenario=None)
            status_match = PRE_STATUS_RE.search(line)
            if status_match:
                if status_match.group(1) == "adb":
                    adb_status = status_match.group(2)
                if status_match.group(1) == "helper":
                    helper_status = status_match.group(2)
        elif "[STEP] START" in line:
            current_step = step
            total_step_count += 1
            if scenario:
                progress[scenario]["status"] = "running"
                progress[scenario]["steps"] = max(int(progress[scenario].get("steps", 0)), step + 1 if step is not None else 0)
                _add_event(events, index, "scenario_running", line, scenario=scenario)
        elif "[STEP] END" in line:
            current_step = step
            if scenario:
                step_end_counts[scenario] = step_end_counts.get(scenario, 0) + 1
                progress[scenario]["steps"] = max(int(progress[scenario].get("steps", 0)), step + 1 if step is not None else 0)
            last_focus_label = _extract_focus_label(line) or last_focus_label
        elif "[OVERLAY]" in line:
            overlay_count += 1
        elif "[SAVE] saved excel:" in line:
            save_excel_count += 1
            _add_event(events, index, "save_excel", line, scenario=current_scenario)
        elif "[STOP][eval]" in line:
            final_result = _extract_first(FINAL_RESULT_RE, line)
            traversal_result = _extract_first(TRAVERSAL_RESULT_RE, line) or traversal_result
            stop_reason = _extract_first(STOP_REASON_RE, line) or stop_reason
            if scenario and _is_global_nav_terminal(line, scenario):
                global_nav_terminal.add(scenario)
                progress[scenario]["status"] = "passed"
                _add_event(events, index, "traversal_terminal", line, scenario=scenario)
            elif scenario and str(final_result).upper() == "FAIL":
                warning_scenarios.add(scenario)
                if progress[scenario].get("status") not in {"failed"}:
                    progress[scenario]["status"] = "warning"
                _add_event(events, index, "scenario_warning", line, scenario=scenario)
            elif scenario and "decision='stop'" in line:
                _add_event(events, index, "traversal_terminal", line, scenario=scenario)
        elif "[TAB][select] stabilization failed" in line or "no_bottom_nav_candidates" in line:
            if scenario:
                hard_failed_scenarios.add(scenario)
                progress[scenario]["status"] = "failed"
                _add_event(events, index, "scenario_failed", line, scenario=scenario)
        elif "[PERF][scenario_summary]" in line:
            if scenario:
                summary_scenarios.add(scenario)
                total_steps = _extract_total_steps(line)
                if total_steps is not None:
                    summary_steps[scenario] = total_steps
                    progress[scenario]["steps"] = total_steps
                if progress[scenario].get("status") not in {"failed", "warning"}:
                    progress[scenario]["status"] = "passed"
                _add_event(events, index, "scenario_completed", line, scenario=scenario)
        elif "[FATAL]" in line or "Traceback" in line or "Exception" in line:
            if scenario:
                hard_failed_scenarios.add(scenario)
                progress[scenario]["status"] = "failed"
                _add_event(events, index, "scenario_failed", line, scenario=scenario)
        elif "[MAIN] skip disabled scenario_id=" in line:
            skipped = _extract_skip_scenario(line)
            if skipped in progress:
                progress[skipped]["status"] = "skipped"
        elif "[FOCUS_RESULT" in line or "packageName" in line:
            last_focus_package = _extract_focus_package(line) or last_focus_package
            last_focus_label = _extract_focus_label(line) or last_focus_label
        elif "[QA_FRONTEND][run] stop_requested=true" in line:
            _add_event(events, index, "stop_requested", line, scenario=current_scenario)

    for scenario_id, item in progress.items():
        if scenario_id in summary_steps:
            item["steps"] = summary_steps[scenario_id]
        elif scenario_id in step_end_counts:
            item["steps"] = step_end_counts[scenario_id]
        elif item.get("steps") in {None, 0} and current_scenario == scenario_id and current_step is not None:
            item["steps"] = current_step + 1
        if _is_completed_global_nav_terminal(
            scenario_id,
            start_gate_passed=global_nav_start_gate_passed,
            menu_reached=global_nav_menu_reached,
            terminal=global_nav_terminal,
        ):
            hard_failed_scenarios.discard(scenario_id)
            warning_scenarios.discard(scenario_id)
            item["status"] = "passed"
            continue
        if scenario_id in hard_failed_scenarios:
            item["status"] = "failed"
            continue
        if scenario_id in warning_scenarios and scenario_id in soft_entry_evidence_scenarios:
            item["status"] = "warning"
            continue
        has_summary = scenario_id in summary_scenarios
        has_rows = step_end_counts.get(scenario_id, 0) > 0 or int(item.get("steps") or 0) > 0
        has_entry = scenario_id in entry_success_scenarios or scenario_id.startswith("global_nav")
        if item.get("status") == "skipped":
            continue
        if not has_summary or not has_rows:
            if has_entry or item.get("status") not in {"queued", "running"}:
                item["status"] = "failed"
            continue
        if scenario_id in warning_scenarios:
            item["status"] = "warning"
        elif item.get("status") not in {"failed", "warning"}:
            item["status"] = "passed"

    passed_count = len([item for item in progress.values() if item["status"] == "passed"])
    warning_count = len([item for item in progress.values() if item["status"] == "warning"])
    failed_count = len([item for item in progress.values() if item["status"] == "failed"])
    completed_count = len([item for item in progress.values() if item["status"] in {"passed", "warning", "failed", "skipped"}])
    return {
        "mode": mode,
        "launch_mode": launch_mode,
        "language_mode": language_mode,
        "device_locale": device_locale,
        "current_scenario": current_scenario,
        "passed_scenarios": passed_count,
        "warning_scenarios": warning_count,
        "completed_scenarios": passed_count + warning_count,
        "remaining_scenarios": len([item for item in progress.values() if item["status"] in {"queued", "running"}]),
        "failed_scenarios": failed_count,
        "scenario_progress": list(progress.values()),
        "current_step": current_step,
        "total_step_count": total_step_count,
        "overlay_count": overlay_count,
        "save_excel_count": save_excel_count,
        "popup_result": popup_result,
        "preflight_state": preflight_state,
        "helper_status": helper_status,
        "adb_status": adb_status,
        "last_focus_label": last_focus_label,
        "last_focus_package": last_focus_package,
        "stop_reason": stop_reason,
        "traversal_result": traversal_result,
        "event_feed": events[-30:],
        "completed_or_terminal_scenarios": completed_count,
        "parse_error": None,
    }


def _empty_dashboard(*, status: dict[str, object], started_at: str | None, scenario_ids: list[str]) -> dict[str, object]:
    return {
        "run_id": status.get("run_id"),
        "mode": status.get("mode"),
        "launch_mode": status.get("launch_mode"),
        "language_mode": status.get("language_mode"),
        "device_locale": status.get("device_locale"),
        "state": status.get("state"),
        "started_at": started_at,
        "elapsed_seconds": _elapsed_seconds(started_at, _string_or_none(status.get("finished_at"))),
        "current_scenario": None,
        "completed_scenarios": 0,
        "remaining_scenarios": len(scenario_ids),
        "failed_scenarios": 0,
        "scenario_progress": [{"id": item, "status": "queued", "steps": 0} for item in scenario_ids],
        "passed_scenarios": 0,
        "warning_scenarios": 0,
        "current_step": None,
        "total_step_count": 0,
        "overlay_count": 0,
        "save_excel_count": 0,
        "popup_result": status.get("popup_result"),
        "preflight_state": status.get("preflight_state"),
        "helper_status": status.get("helper_state"),
        "adb_status": None,
        "last_focus_label": None,
        "last_focus_package": None,
        "stop_reason": None,
        "traversal_result": None,
        "event_feed": [],
        "log_size": 0,
        "parse_error": None,
    }


def _extract_enabled_ids(log_text: str) -> list[str]:
    match = ENABLED_IDS_RE.search(log_text)
    if not match:
        return []
    try:
        value = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def extract_validation_scenario_evidence_from_log(log_text: str) -> tuple[set[str], set[str]]:
    filename = _extract_saved_excel_filename(log_text)
    if not filename:
        return set(), set()
    return extract_validation_scenario_evidence_from_xlsx(OUTPUT_DIR / filename)


def extract_validation_scenario_evidence_from_xlsx(path: Path) -> tuple[set[str], set[str]]:
    if not path.exists():
        return set(), set()
    try:
        import openpyxl
    except ImportError:
        return set(), set()
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        if "result" not in workbook.sheetnames:
            return set(), set()
        sheet = workbook["result"]
        headers = [sheet.cell(1, column).value for column in range(1, sheet.max_column + 1)]
        scenario_col = headers.index("scenario_id") + 1
        result_col = headers.index("final_result") + 1
        failure_col = headers.index("failure_reason") + 1 if "failure_reason" in headers else None
        mismatch_col = headers.index("mismatch_type") + 1 if "mismatch_type" in headers else None
    except (OSError, ValueError, KeyError):
        return set(), set()

    failed: set[str] = set()
    warning: set[str] = set()
    try:
        for row in range(2, sheet.max_row + 1):
            result = str(sheet.cell(row, result_col).value or "").strip().upper()
            scenario = str(sheet.cell(row, scenario_col).value or "").strip()
            if not scenario:
                continue
            if result == "WARN":
                warning.add(scenario)
            elif result == "FAIL":
                failure_reason = str(sheet.cell(row, failure_col).value or "").strip() if failure_col else ""
                mismatch_type = str(sheet.cell(row, mismatch_col).value or "").strip().upper() if mismatch_col else ""
                normalized_failure = failure_reason.lower()
                if mismatch_type in SCENARIO_HARD_MISMATCH_TYPES:
                    failed.add(scenario)
                elif (
                    mismatch_type in ACCESSIBILITY_PASS_MISMATCH_TYPES
                    and normalized_failure in TRANSIENT_PRESENTATION_FAILURE_REASONS
                ):
                    warning.add(scenario)
                elif failure_reason:
                    failed.add(scenario)
                else:
                    warning.add(scenario)
    finally:
        try:
            workbook.close()
        except Exception:
            pass
    return failed, warning


def _extract_saved_excel_filename(log_text: str) -> str | None:
    matches = SAVED_EXCEL_RE.findall(log_text)
    return matches[-1] if matches else None


def _extract_scenario(line: str) -> str | None:
    match = SCENARIO_RE.search(line)
    if not match:
        return None
    return match.group(1) or match.group(2) or match.group(3) or match.group(4)


def _extract_skip_scenario(line: str) -> str | None:
    match = re.search(r"scenario_id='([^']+)'", line)
    return match.group(1) if match else None


def _extract_step(line: str) -> int | None:
    match = STEP_RE.search(line)
    if not match:
        return None
    return int(match.group(1))


def _extract_total_steps(line: str) -> int | None:
    match = TOTAL_STEPS_RE.search(line)
    if not match:
        return None
    return int(match.group(1))


def _extract_focus_package(line: str) -> str | None:
    match = FOCUS_PACKAGE_RE.search(line)
    if not match:
        return None
    return match.group(1) or match.group(2) or match.group(3)


def _extract_focus_label(line: str) -> str | None:
    match = FOCUS_LABEL_RE.search(line)
    if not match:
        return None
    return match.group(1) or match.group(2) or match.group(3)


def _line_reaches_menu_tab(line: str) -> bool:
    return "Menu, Tab 5 of 5" in line or "menu tab 5 of 5" in line.lower()


def _is_global_nav_terminal(line: str, scenario: str) -> bool:
    return (
        scenario == "global_nav_main"
        or "scenario_type='global_nav'" in line
        or "is_global_nav=true" in line
    ) and "reason='smart_nav_terminal'" in line


def _is_completed_global_nav_terminal(
    scenario: str,
    *,
    start_gate_passed: set[str],
    menu_reached: set[str],
    terminal: set[str],
) -> bool:
    return (
        scenario in terminal
        and scenario in menu_reached
        and (scenario in start_gate_passed or scenario == "global_nav_main")
    )


def _has_plugin_entry_identity_evidence(scenario: str, line: str) -> bool:
    lowered = line.lower()
    evidence_tokens = {
        "life_find_plugin": (
            "current location",
            "my devices",
            "offline",
            "com.samsung.android.plugin.fme",
        ),
        "life_video_plugin": (
            "live view",
            "daily clips",
            "home camera",
            "홈카메라",
        ),
    }.get(scenario, ())
    if not evidence_tokens:
        return False
    negative_tokens = ("location qr code", "change location")
    has_evidence = any(token in lowered for token in evidence_tokens)
    has_negative_only = any(token in lowered for token in negative_tokens) and not has_evidence
    return bool(has_evidence and not has_negative_only)


def _extract_first(pattern: re.Pattern[str], line: str) -> str | None:
    match = pattern.search(line)
    return match.group(1) if match else None


def _add_event(events: list[dict[str, object]], line_index: int, event_type: str, line: str, *, scenario: str | None) -> None:
    events.append(
        {
            "line": line_index + 1,
            "type": event_type,
            "scenario": scenario,
            "message": _trim(line),
        }
    )


def _trim(value: str, limit: int = 240) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3]}..."


def _string_or_none(value: object) -> str | None:
    return str(value) if value else None


def _elapsed_seconds(started_at: str | None, finished_at: str | None) -> int:
    if not started_at:
        return 0
    try:
        started = datetime.fromisoformat(started_at)
        finished = datetime.fromisoformat(finished_at) if finished_at else datetime.now()
    except ValueError:
        return 0
    if started.tzinfo is not None:
        finished = finished.replace(tzinfo=timezone.utc) if finished.tzinfo is None else finished
    return max(0, int((finished - started).total_seconds()))
