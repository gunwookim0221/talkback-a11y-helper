from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_PACKAGE = "com.samsung.android.oneconnect"
LAUNCHER_PACKAGES = {
    "com.sec.android.app.launcher",
    "com.android.launcher",
    "com.android.launcher3",
}


def inspect_foreground_package_exit(
    *,
    row: dict[str, Any],
    client: Any,
    dev: str | None,
) -> dict[str, Any]:
    packages, package_sources = _collect_row_packages(row)
    current_package = _current_package(client=client, dev=dev)
    if current_package:
        packages["current_package"] = current_package
        package_sources["current_package"] = "dumpsys_window"

    launcher_hit = any(value in LAUNCHER_PACKAGES for value in packages.values() if value)
    non_oneconnect_current = bool(current_package and current_package != EXPECTED_PACKAGE)
    launcher_focus = bool(
        packages.get("focused_package")
        and packages["focused_package"] in LAUNCHER_PACKAGES
    )
    launcher_resource = bool(
        packages.get("resource_package")
        and packages["resource_package"] in LAUNCHER_PACKAGES
    )
    helper_alive_not_oneconnect = _helper_dump_alive_but_not_oneconnect(row)
    process_running = _oneconnect_process_running(client=client, dev=dev)
    signals = {
        "launcher_hit": launcher_hit,
        "non_oneconnect_current": non_oneconnect_current,
        "launcher_focus": launcher_focus,
        "launcher_resource": launcher_resource,
        "helper_alive_not_oneconnect": helper_alive_not_oneconnect,
    }

    detection: dict[str, Any] | None = None
    if launcher_hit or non_oneconnect_current or launcher_focus or launcher_resource or helper_alive_not_oneconnect:
        crash_type = "APP_TERMINATED" if process_running is False else "POSSIBLE_CRASH"
        reason = "app_terminated" if crash_type == "APP_TERMINATED" else "possible_crash"
        detection = {
            "crash_type": crash_type,
            "reason": reason,
            "packages": packages,
            "package_sources": package_sources,
            "process_running": process_running,
            "signals": signals,
        }

    return {
        "packages": packages,
        "package_sources": package_sources,
        "process_running": process_running,
        "signals": signals,
        "detection": detection,
    }


def detect_foreground_package_exit(
    *,
    row: dict[str, Any],
    client: Any,
    dev: str | None,
) -> dict[str, Any] | None:
    inspection = inspect_foreground_package_exit(row=row, client=client, dev=dev)
    detection = inspection.get("detection")
    return detection if isinstance(detection, dict) else None


def record_foreground_exit_event(
    *,
    output_base_dir: str,
    serial: str | None,
    row: dict[str, Any],
    detection: dict[str, Any],
    client: Any,
    dev: str | None,
    scenario_id: str,
    step_idx: int,
) -> str:
    output_dir = Path(output_base_dir or os.environ.get("TB_OUTPUT_DIR", "output"))
    event_id = _next_event_id(output_dir)
    event_dir = output_dir / "crashes" / event_id
    event_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    crash_type = str(detection.get("crash_type") or "POSSIBLE_CRASH")
    packages = detection.get("packages") if isinstance(detection.get("packages"), dict) else {}
    current_package = str(packages.get("current_package") or "") or None

    event_payload = {
        "crash_event_id": event_id,
        "crash_type": crash_type,
        "process": EXPECTED_PACKAGE,
        "exception": None,
        "top_frame": None,
        "timestamp": timestamp,
        "detection_source": "foreground_package_guard",
        "reason": str(detection.get("reason") or "possible_crash"),
        "packages": packages,
        "signals": detection.get("signals") if isinstance(detection.get("signals"), dict) else {},
    }
    _write_json(event_dir / "crash_event.json", event_payload)
    (event_dir / "logcat_excerpt.txt").write_text(
        "No FATAL EXCEPTION logcat block was observed for this crash-like event.\n"
        f"detection_source=foreground_package_guard reason={event_payload['reason']}\n",
        encoding="utf-8",
    )

    capture_errors: dict[str, str] = {}
    screenshot_error = _capture_screenshot(client=client, dev=dev, path=event_dir / "crash_screenshot.png")
    if screenshot_error:
        capture_errors["screenshot"] = screenshot_error
    window_error = _capture_window_dump(client=client, dev=dev, path=event_dir / "crash_window_dump.xml", event_id=event_id)
    if window_error:
        capture_errors["window_dump"] = window_error
    helper_error = _capture_helper_dump(client=client, dev=dev, path=event_dir / "crash_helper_dump.json", row=row)
    if helper_error:
        capture_errors["helper_dump"] = helper_error

    focus_state = {
        "timestamp": timestamp,
        "foreground_package_before": None,
        "foreground_package_after": current_package,
        "current_package": current_package,
        "last_known_focus_label": _row_label(row),
        "last_known_talkback_speech": str(row.get("merged_announcement", "") or "") or None,
        "last_known_visible_text": [_row_label(row)] if _row_label(row) else None,
        "last_known_action": _row_action(row),
        "latest_step_log": _step_log(row=row, scenario_id=scenario_id, step_idx=step_idx),
        "packages": packages,
    }
    _write_json(event_dir / "focus_state.json", focus_state)

    context = _build_context(
        event_id=event_id,
        crash_type=crash_type,
        timestamp=timestamp,
        serial=serial,
        scenario_id=scenario_id,
        step_idx=step_idx,
        row=row,
        current_package=current_package,
        capture_errors=capture_errors,
    )
    _write_json(event_dir / "crash_context.json", context)
    (event_dir / "crash_repro.md").write_text(_render_repro(context), encoding="utf-8")
    return event_id


def _collect_row_packages(row: dict[str, Any]) -> tuple[dict[str, str | None], dict[str, str]]:
    focus_node = row.get("focus_node") if isinstance(row.get("focus_node"), dict) else {}
    focused_package, focused_source = _first_package_with_source(
        ("focus_payload", focus_node.get("packageName")),
        ("focus_payload", focus_node.get("package_name")),
        ("row_payload", row.get("packageName")),
        ("row_payload", row.get("package_name")),
    )
    resource_package, resource_source = _package_from_resource_candidates(
        ("focus_view_id", row.get("focus_view_id")),
        ("resource_id", row.get("resource_id")),
        ("focus_payload_view_id", focus_node.get("viewIdResourceName")),
        ("focus_payload_resource_id", focus_node.get("resourceId")),
    )
    smart_package, smart_source = _package_from_resource_candidates(
        ("smart_nav_actual_view_id", row.get("smart_nav_actual_view_id")),
        ("smart_nav_resolved_view_id", row.get("smart_nav_resolved_view_id")),
        ("smart_nav_requested_view_id", row.get("smart_nav_requested_view_id")),
    )
    packages = {
        "focused_package": focused_package,
        "resource_package": resource_package,
        "smart_nav_package": smart_package,
    }
    package_sources: dict[str, str] = {}
    if focused_source:
        package_sources["focused_package"] = focused_source
    if resource_source:
        package_sources["resource_package"] = resource_source
    if smart_source:
        package_sources["smart_nav_package"] = smart_source
    return packages, package_sources


def _helper_dump_alive_but_not_oneconnect(row: dict[str, Any]) -> bool:
    nodes = row.get("dump_tree_nodes")
    if not isinstance(nodes, list) or not nodes:
        return False
    packages = {_node_package(node) for node in _iter_nodes(nodes)}
    packages.discard(None)
    if not packages:
        return False
    return EXPECTED_PACKAGE not in packages and bool(packages & LAUNCHER_PACKAGES)


def _iter_nodes(nodes: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stack = list(reversed(nodes))
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        out.append(node)
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(reversed(children))
    return out


def _node_package(node: dict[str, Any]) -> str | None:
    return _first_package(
        node.get("packageName"),
        node.get("package_name"),
        _package_from_resource_id(node.get("viewIdResourceName") or node.get("resourceId")),
    )


def _first_package(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _first_package_with_source(*pairs: tuple[str, Any]) -> tuple[str | None, str | None]:
    for source, value in pairs:
        text = str(value or "").strip()
        if text:
            return text, source
    return None, None


def _package_from_resource_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if ":id/" not in text:
        return None
    return text.split(":id/", 1)[0] or None


def _package_from_resource_candidates(*pairs: tuple[str, Any]) -> tuple[str | None, str | None]:
    for source, value in pairs:
        package_name = _package_from_resource_id(value)
        if package_name:
            return package_name, source
    return None, None


def _current_package(*, client: Any, dev: str | None) -> str | None:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return None
    try:
        output = run_fn(["shell", "dumpsys", "window"], dev=dev, timeout=5.0)
    except TypeError:
        try:
            output = run_fn(["shell", "dumpsys", "window"], dev=dev)
        except Exception:
            return None
    except Exception:
        return None
    return _extract_package_from_window_text(str(output or ""))


def _extract_package_from_window_text(text: str) -> str | None:
    for pattern in (
        r"mCurrentFocus=.*?\s([A-Za-z0-9_.]+)/",
        r"mFocusedApp=.*?\s([A-Za-z0-9_.]+)/",
        r"topResumedActivity=.*?\s([A-Za-z0-9_.]+)/",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _oneconnect_process_running(*, client: Any, dev: str | None) -> bool | None:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return None
    try:
        output = run_fn(["shell", "pidof", EXPECTED_PACKAGE], dev=dev, timeout=3.0)
    except TypeError:
        try:
            output = run_fn(["shell", "pidof", EXPECTED_PACKAGE], dev=dev)
        except Exception:
            return None
    except Exception:
        return None
    return bool(str(output or "").strip())


def _next_event_id(output_dir: Path) -> str:
    crashes_dir = output_dir / "crashes"
    crashes_dir.mkdir(parents=True, exist_ok=True)
    highest = 0
    for path in crashes_dir.iterdir():
        match = re.fullmatch(r"CRASH-(\d{4})", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"CRASH-{highest + 1:04d}"


def _capture_screenshot(*, client: Any, dev: str | None, path: Path) -> str | None:
    snapshot_fn = getattr(client, "_take_snapshot", None)
    if not callable(snapshot_fn):
        return "snapshot_not_supported"
    try:
        snapshot_fn(dev, str(path))
        return None
    except Exception as exc:
        return str(exc)


def _capture_window_dump(*, client: Any, dev: str | None, path: Path, event_id: str) -> str | None:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return "adb_run_not_supported"
    remote = f"/sdcard/tb_{event_id}_window_dump.xml"
    try:
        run_fn(["shell", "uiautomator", "dump", remote], dev=dev)
        xml = run_fn(["shell", "cat", remote], dev=dev)
        path.write_text(str(xml or ""), encoding="utf-8", errors="replace")
        return None
    except Exception as exc:
        return str(exc)


def _capture_helper_dump(*, client: Any, dev: str | None, path: Path, row: dict[str, Any]) -> str | None:
    dump_fn = getattr(client, "dump_tree", None)
    try:
        nodes = dump_fn(dev=dev) if callable(dump_fn) else row.get("dump_tree_nodes", [])
        _write_json(path, {"nodes": nodes if isinstance(nodes, list) else nodes})
        return None
    except Exception as exc:
        _write_json(path, {"nodes": None, "error": str(exc)})
        return str(exc)


def _build_context(
    *,
    event_id: str,
    crash_type: str,
    timestamp: str,
    serial: str | None,
    scenario_id: str,
    step_idx: int,
    row: dict[str, Any],
    current_package: str | None,
    capture_errors: dict[str, str],
) -> dict[str, Any]:
    event_dir = f"crashes/{event_id}"
    return {
        "schema_version": 1,
        "crash_event_id": event_id,
        "device_id": serial,
        "package": EXPECTED_PACKAGE,
        "crash_type": crash_type,
        "confidence": "medium" if crash_type == "POSSIBLE_CRASH" else "high",
        "timestamp": timestamp,
        "scenario": {"name": scenario_id, "plugin": scenario_id, "run_mode": None},
        "step": {"index": step_idx, "name": None, "attempt": None},
        "last_action": _row_action(row),
        "last_focus_label": _row_label(row),
        "last_speech": str(row.get("merged_announcement", "") or "") or None,
        "last_visible_text": [_row_label(row)] if _row_label(row) else None,
        "foreground": {"before": None, "after": current_package},
        "logcat": {
            "exception": None,
            "process": EXPECTED_PACKAGE,
            "pid": None,
            "top_frame": None,
            "signature": None,
        },
        "artifacts": {
            "crash_event": f"{event_dir}/crash_event.json",
            "logcat_excerpt": f"{event_dir}/logcat_excerpt.txt",
            "screenshot": f"{event_dir}/crash_screenshot.png",
            "window_dump": f"{event_dir}/crash_window_dump.xml",
            "helper_dump": f"{event_dir}/crash_helper_dump.json",
            "focus_state": f"{event_dir}/focus_state.json",
            "repro_guide": f"{event_dir}/crash_repro.md",
        },
        "capture_errors": capture_errors,
        "recovery": {"decision": "capture_only", "retry_count": 0, "result": "not_implemented"},
    }


def _row_label(row: dict[str, Any]) -> str | None:
    value = str(row.get("visible_label", "") or row.get("actual_focus_visible", "") or "").strip()
    return value or None


def _row_action(row: dict[str, Any]) -> dict[str, Any] | None:
    action = str(row.get("last_smart_nav_result", "") or row.get("move_result", "") or "").strip()
    label = _row_label(row)
    raw = _step_log(row=row, scenario_id=str(row.get("scenario_id", "") or ""), step_idx=int(row.get("step_index", -1) or -1))
    if not any((action, label, raw)):
        return None
    return {"type": action or None, "label": label, "raw": raw}


def _step_log(*, row: dict[str, Any], scenario_id: str, step_idx: int) -> str:
    return (
        f"[STEP] END scenario='{scenario_id}' step={step_idx} "
        f"visible='{str(row.get('visible_label', '') or '')}' "
        f"speech='{str(row.get('merged_announcement', '') or '')}' "
        f"resource='{str(row.get('focus_view_id', '') or '')}'"
    )


def _render_repro(context: dict[str, Any]) -> str:
    scenario = ((context.get("scenario") or {}).get("name") if isinstance(context.get("scenario"), dict) else None) or "unknown"
    step = ((context.get("step") or {}).get("index") if isinstance(context.get("step"), dict) else None)
    logcat = context.get("logcat") if isinstance(context.get("logcat"), dict) else {}
    artifacts = context.get("artifacts") if isinstance(context.get("artifacts"), dict) else {}
    return "\n".join(
        [
            "# Manual Repro Guide",
            "",
            f"Device: {context.get('device_id') or 'unknown'}",
            f"Package: {context.get('package') or EXPECTED_PACKAGE}",
            f"Scenario: {scenario}",
            f"Crash Type: {context.get('crash_type') or 'unknown'}",
            "",
            "## Preconditions",
            "",
            "1. SmartThings 앱을 설치하고 로그인 상태를 준비합니다.",
            "2. TalkBack을 ON으로 설정합니다.",
            "3. TalkBack A11y Helper accessibility service를 활성화합니다.",
            "4. 디바이스 언어와 region을 테스트 실행 당시 설정과 맞춥니다.",
            "",
            "## Manual Steps",
            "",
            "1. SmartThings를 실행합니다.",
            f"2. {scenario} 시나리오 위치로 이동합니다.",
            f"3. 자동화가 마지막으로 기록한 step {step if step is not None else 'unknown'} 지점까지 이동합니다.",
            "4. Last Automation Context의 action/focus 정보를 기준으로 동일 동작을 수행합니다.",
            "5. 앱이 종료되거나 launcher로 이탈하는지 확인합니다.",
            "",
            "## Last Automation Context",
            "",
            f"- Last action: {json.dumps(context.get('last_action'), ensure_ascii=False)}",
            f"- Last focus: {context.get('last_focus_label') or 'unknown'}",
            f"- Last speech: {context.get('last_speech') or 'unknown'}",
            f"- Foreground after crash: {(context.get('foreground') or {}).get('after') if isinstance(context.get('foreground'), dict) else 'unknown'}",
            "",
            "## Crash Evidence",
            "",
            f"- Exception: {logcat.get('exception') or 'not observed'}",
            f"- Top frame: {logcat.get('top_frame') or 'not observed'}",
            "",
            "## Artifacts",
            "",
            *[f"- {key}: {value}" for key, value in artifacts.items()],
            "",
        ]
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
