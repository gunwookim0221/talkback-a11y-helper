"""Opt-in, bounded TalkBack and WindowManager lifecycle snapshots."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TALKBACK_PACKAGE = "com.samsung.android.accessibility.talkback"
MAX_COMMAND_OUTPUT_CHARS = 256_000
MAX_WINDOW_DETAILS = 12
MAX_EVENTS = 256
_ACTIVITY_MARKER = "__TB_ACTIVITY__"
_ACCESSIBILITY_MARKER = "__TB_ACCESSIBILITY__"
_PID_MARKER = "__TB_PID__"
_WINDOW_HEADER = re.compile(r"(?m)^\s*Window #(?P<index>\d+) Window\{(?P<header>[^}]*)\}:")


def _split_sections(raw: str) -> tuple[str, str, str, str]:
    before_pid, _, pid_section = raw.partition(_PID_MARKER)
    window_section, activity_marker, after_activity = before_pid.partition(_ACTIVITY_MARKER)
    activity_section, accessibility_marker, accessibility_section = after_activity.partition(
        _ACCESSIBILITY_MARKER
    )
    if not activity_marker:
        return raw, "", "", ""
    if not accessibility_marker:
        return window_section, activity_section, "", pid_section
    return window_section, activity_section, accessibility_section, pid_section


def _window_details(window_output: str) -> list[dict[str, Any]]:
    headers = list(_WINDOW_HEADER.finditer(window_output))
    windows: list[dict[str, Any]] = []
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(window_output)
        section = window_output[match.start() : end]
        title_parts = match.group("header").split(maxsplit=2)
        title = title_parts[2] if len(title_parts) > 2 and title_parts[1].startswith("u") else ""
        package_match = re.search(r"\bpackage=([^\s]+)", section)
        type_match = re.search(r"\bty=([A-Z0-9_]+|\d+)", section)
        surface = bool(re.search(r"\bmHasSurface=true\b", section))
        ready = bool(re.search(r"\bisReadyForDisplay\(\)=true\b", section))
        windows.append(
            {
                "index": int(match.group("index")),
                "title": title[:96],
                "package": package_match.group(1)[:128] if package_match else None,
                "type": type_match.group(1)[:48] if type_match else None,
                "has_surface": surface,
                "ready": ready,
            }
        )
    return windows


def _foreground_package(activity_output: str, window_output: str) -> str | None:
    for pattern, source in (
        (r"topResumedActivity=.*?\bu\d+\s+([A-Za-z0-9_.]+)(?:/|\s)", activity_output),
        (r"mResumedActivity:.*?\bu\d+\s+([A-Za-z0-9_.]+)(?:/|\s)", activity_output),
        (r"mCurrentFocus=Window\{[^}]*?\bu\d+\s+([A-Za-z0-9_.]+)(?:/|\s)", window_output),
    ):
        match = re.search(pattern, source)
        if match:
            return match.group(1)
    return None


def _accessibility_focus_package(focus_node: Any) -> str | None:
    if isinstance(focus_node, dict):
        package = str(
            focus_node.get("packageName")
            or focus_node.get("package_name")
            or focus_node.get("package")
            or ""
        ).strip()
        if package:
            return package[:128]
        for key in (
            "actual_focus_node",
            "actualFocusNode",
            "focus_node",
            "focusNode",
            "focused",
            "node",
        ):
            nested = _accessibility_focus_package(focus_node.get(key))
            if nested:
                return nested
    elif isinstance(focus_node, list):
        for item in focus_node[:32]:
            nested = _accessibility_focus_package(item)
            if nested:
                return nested
    return None


def parse_window_lifecycle_output(
    raw_output: str,
    *,
    focus_node: Any = None,
) -> dict[str, Any]:
    """Parse a combined dumpsys snapshot without retaining unbounded device output."""
    raw = str(raw_output or "")[:MAX_COMMAND_OUTPUT_CHARS]
    window_output, activity_output, accessibility_output, pid_output = _split_sections(raw)
    windows = _window_details(window_output)
    focus_id_match = re.search(r"Accessibility Focused Window Id\s*=\s*(-?\d+)", accessibility_output)
    pid_match = re.search(r"(?m)^\s*(\d+)\s*$", pid_output)
    enabled_services = ""
    if "Enabled services:" in accessibility_output:
        enabled_services = accessibility_output.split("Enabled services:", 1)[1].splitlines()[0]
    enabled = TALKBACK_PACKAGE in enabled_services
    talkback_windows = [item for item in windows if item.get("package") == TALKBACK_PACKAGE]
    search_overlay_windows = [
        item
        for item in windows
        if "searchscreenoverlay" in str(item.get("title") or "").lower()
        or (
            item.get("package") == TALKBACK_PACKAGE
            and any(token in str(item.get("title") or "").lower() for token in ("search", "검색"))
        )
    ]
    search_overlay = bool(search_overlay_windows) or "SearchScreenOverlay" in window_output
    return {
        "window_count": len(windows),
        "snapshot_available": bool(windows),
        "surfaced_window_count": sum(bool(item["has_surface"]) for item in windows),
        "ready_window_count": sum(bool(item["ready"]) for item in windows),
        "window_packages": sorted(
            {str(item["package"]) for item in windows if item.get("package")}
        )[:MAX_WINDOW_DETAILS],
        "window_types": sorted(
            {str(item["type"]) for item in windows if item.get("type")}
        )[:MAX_WINDOW_DETAILS],
        "windows": windows[:MAX_WINDOW_DETAILS],
        "talkback_window_count": len(talkback_windows),
        "search_screen_overlay_detected": bool(search_overlay),
        "search_screen_overlay_window_count": len(search_overlay_windows),
        "search_screen_overlay_visible": any(
            bool(item["has_surface"] and item["ready"]) for item in search_overlay_windows
        ),
        "foreground_package": _foreground_package(activity_output, window_output),
        "accessibility_focus_window_id": int(focus_id_match.group(1)) if focus_id_match else None,
        "accessibility_focus_package": _accessibility_focus_package(focus_node),
        "accessibility_focus_package_source": "helper_focus_node"
        if _accessibility_focus_package(focus_node)
        else "unavailable",
        "talkback_enabled": enabled if "Enabled services:" in accessibility_output else None,
        "talkback_pid": pid_match.group(1) if pid_match else None,
        "talkback_pid_available": bool(pid_match),
        "command_output_truncated": len(str(raw_output or "")) > MAX_COMMAND_OUTPUT_CHARS,
    }


class WindowLifecycleRecorder:
    def __init__(self, client: Any, dev: Any, scenario_id: str, output_dir: str | Path | None):
        self.client = client
        self.dev = dev
        self.scenario_id = str(scenario_id or "")[:128]
        self.step: int | None = None
        self.output_path = Path(output_dir) / "talkback_window_lifecycle.jsonl" if output_dir else None
        self.event_count = 0
        self.previous_pid: str | None = getattr(client, "_preflight_talkback_pid", None)
        self.saw_enabled_process_gap = False
        self.restart_event: dict[str, Any] | None = None
        self.current_focus_package: str | None = None
        self.focus_package_age_events = 0
        self.limit_reported = False

    def set_step(self, step: int | None) -> None:
        self.step = int(step) if step is not None else None

    def _track_talkback_process(self, payload: dict[str, Any]) -> None:
        current_pid = payload.get("talkback_pid")
        previous_pid = str(self.previous_pid) if self.previous_pid else None
        restart_detected = False
        process_event = "running" if current_pid else "missing_or_unavailable"
        if current_pid:
            if self.saw_enabled_process_gap and self.previous_pid and str(current_pid) != self.previous_pid:
                restart_detected = True
                process_event = "returned_after_enabled_gap"
            elif self.previous_pid and current_pid != self.previous_pid:
                restart_detected = True
                process_event = "pid_changed"
            self.previous_pid = str(current_pid)
            self.saw_enabled_process_gap = False
        elif payload.get("talkback_enabled") is True and self.previous_pid:
            self.saw_enabled_process_gap = True
            process_event = "enabled_but_pid_missing"
        payload.update(
            {
                "talkback_restart_detected": restart_detected,
                "talkback_process_event": process_event,
                "previous_talkback_pid": previous_pid,
            }
        )
        if restart_detected and self.restart_event is None:
            self.restart_event = {
                "timestamp": payload["timestamp"],
                "scenario_id": self.scenario_id,
                "step": payload["step"],
                "phase": payload["phase"],
                "action_type": payload["action_type"],
                "previous_talkback_pid": previous_pid,
                "talkback_pid": str(current_pid) if current_pid else None,
                "talkback_process_event": process_event,
                "window_count": payload.get("window_count"),
                "talkback_window_count": payload.get("talkback_window_count"),
                "safety_probe_only": bool(payload.get("safety_probe_only", False)),
            }
            print(
                "[TALKBACK_RESTART_DETECTED] "
                + json.dumps(self.restart_event, ensure_ascii=False, separators=(",", ":"))
            )

    def _probe_talkback_process_at_limit(
        self,
        phase: str,
        action_type: str,
        step: int | None,
    ) -> None:
        run = getattr(self.client, "_run", None)
        if not callable(run):
            return
        command = (
            f"echo {_ACTIVITY_MARKER}; "
            f"echo {_ACCESSIBILITY_MARKER}; "
            "dumpsys accessibility | grep -F 'Enabled services:'; "
            f"echo {_PID_MARKER}; pidof {TALKBACK_PACKAGE}"
        )
        try:
            output = run(["shell", command], dev=self.dev, timeout=5.0)
        except Exception as exc:
            output = ""
            command_error = f"{type(exc).__name__}:{exc}"[:160]
        else:
            command_error = None
        payload = parse_window_lifecycle_output(output or "")
        payload.update(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "scenario_id": self.scenario_id,
                "step": self.step if step is None else int(step),
                "phase": str(phase or "")[:48],
                "action_type": str(action_type or "")[:48],
                "safety_probe_only": True,
            }
        )
        self._track_talkback_process(payload)
        if command_error:
            payload["snapshot_error"] = command_error
        self._write_artifact(payload)

    def _write_artifact(self, payload: dict[str, Any]) -> None:
        if self.output_path is not None:
            try:
                self.output_path.parent.mkdir(parents=True, exist_ok=True)
                with self.output_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            except OSError as exc:
                print(f"[TALKBACK_WINDOW] artifact_write_failed error='{type(exc).__name__}'")

    def capture(
        self,
        phase: str,
        action_type: str,
        *,
        step: int | None = None,
        focus_node: Any = None,
    ) -> dict[str, Any] | None:
        if self.event_count >= MAX_EVENTS:
            if not self.limit_reported:
                print(
                    f"[TALKBACK_WINDOW] capture_limit_reached max_events={MAX_EVENTS} "
                    "full_snapshot_disabled=true talkback_process_probe=enabled"
                )
                self.limit_reported = True
            self._probe_talkback_process_at_limit(phase, action_type, step)
            return None
        run = getattr(self.client, "_run", None)
        if not callable(run):
            return None
        command = (
            "dumpsys window windows | grep -E "
            "'^[[:space:]]*Window #[0-9]+ Window\\{|package=|mAttrs=.*ty=|mHasSurface=|SearchScreenOverlay'; "
            f"echo {_ACTIVITY_MARKER}; "
            "dumpsys activity activities | grep -E 'topResumedActivity=|mResumedActivity:|mCurrentFocus='; "
            f"echo {_ACCESSIBILITY_MARKER}; "
            "dumpsys accessibility | grep -E 'Enabled services:|Accessibility Focused Window Id =|A11yWindow\\['; "
            f"echo {_PID_MARKER}; pidof {TALKBACK_PACKAGE}"
        )
        try:
            output = run(["shell", command], dev=self.dev, timeout=8.0)
        except Exception as exc:
            output = ""
            command_error = f"{type(exc).__name__}:{exc}"[:160]
        else:
            command_error = None
        observed_focus_package = _accessibility_focus_package(focus_node)
        payload = parse_window_lifecycle_output(output or "", focus_node=focus_node)
        if observed_focus_package:
            self.current_focus_package = observed_focus_package
            self.focus_package_age_events = 0
            payload["accessibility_focus_package_observed_in_sample"] = True
        else:
            self.focus_package_age_events += 1
            if self.current_focus_package:
                payload["accessibility_focus_package"] = self.current_focus_package
                payload["accessibility_focus_package_source"] = "previous_helper_focus_node"
                payload["accessibility_focus_package_observed_in_sample"] = False
            else:
                payload["accessibility_focus_package_observed_in_sample"] = False
        payload["accessibility_focus_package_age_events"] = self.focus_package_age_events
        payload.update(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "scenario_id": self.scenario_id,
                "step": self.step if step is None else int(step),
                "phase": str(phase or "")[:48],
                "action_type": str(action_type or "")[:48],
            }
        )
        self._track_talkback_process(payload)
        if command_error:
            payload["snapshot_error"] = command_error
        if self.event_count < MAX_EVENTS:
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            print(f"[TALKBACK_WINDOW] {serialized}")
            self._write_artifact(payload)
            self.event_count += 1
        return payload


def configure_window_lifecycle(
    client: Any,
    dev: Any,
    scenario_id: str,
    output_dir: str | Path | None,
    *,
    enabled: bool | None = None,
) -> WindowLifecycleRecorder | None:
    if enabled is None:
        enabled = os.environ.get("TALKBACK_WINDOW_LIFECYCLE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    previous = getattr(client, "_window_lifecycle_recorder", None)
    recorder = (
        WindowLifecycleRecorder(client, dev, scenario_id, output_dir) if enabled else None
    )
    if recorder is not None and isinstance(previous, WindowLifecycleRecorder):
        recorder.previous_pid = previous.previous_pid
        recorder.saw_enabled_process_gap = previous.saw_enabled_process_gap
    try:
        setattr(client, "_window_lifecycle_recorder", recorder)
    except (AttributeError, TypeError):
        if enabled:
            raise
    return recorder


def get_talkback_restart_event(client: Any) -> dict[str, Any] | None:
    """Return the first unexpected TalkBack restart observed for this scenario."""
    recorder = getattr(client, "_window_lifecycle_recorder", None)
    event = getattr(recorder, "restart_event", None)
    return dict(event) if isinstance(event, dict) else None


def set_window_lifecycle_step(client: Any, step: int | None) -> None:
    recorder = getattr(client, "_window_lifecycle_recorder", None)
    if isinstance(recorder, WindowLifecycleRecorder):
        recorder.set_step(step)


def capture_window_lifecycle(
    client: Any,
    dev: Any,
    phase: str,
    action_type: str,
    *,
    step: int | None = None,
    focus_node: Any = None,
) -> dict[str, Any] | None:
    recorder = getattr(client, "_window_lifecycle_recorder", None)
    if not isinstance(recorder, WindowLifecycleRecorder):
        return None
    return recorder.capture(
        phase,
        action_type,
        step=step,
        focus_node=focus_node,
    )


__all__ = [
    "MAX_EVENTS",
    "MAX_WINDOW_DETAILS",
    "TALKBACK_PACKAGE",
    "WindowLifecycleRecorder",
    "capture_window_lifecycle",
    "configure_window_lifecycle",
    "parse_window_lifecycle_output",
    "set_window_lifecycle_step",
]
