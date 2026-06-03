from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ONECONNECT_PACKAGE = "com.samsung.android.oneconnect"
FATAL_EXCEPTION_TOKEN = "FATAL EXCEPTION"
PROCESS_TOKEN = f"Process: {ONECONNECT_PACKAGE}"
CRASH_BLOCK_SOURCE_TOKEN = "AndroidRuntime"

LogWriter = Callable[[str], None]
RunFactory = Callable[..., subprocess.CompletedProcess[Any]]


@dataclass(frozen=True)
class CrashEvent:
    crash_event_id: str
    crash_type: str
    process: str
    exception: str | None
    top_frame: str | None
    timestamp: str
    logcat_excerpt: str

    def to_json(self) -> dict[str, object]:
        return {
            "crash_event_id": self.crash_event_id,
            "crash_type": self.crash_type,
            "process": self.process,
            "exception": self.exception,
            "top_frame": self.top_frame,
            "timestamp": self.timestamp,
        }


class CrashEventStore:
    def __init__(
        self,
        output_dir: Path,
        *,
        serial: str | None = None,
        runner_log_path: Path | None = None,
        run_factory: RunFactory = subprocess.run,
        helper_dump_factory: Callable[[str | None], Any] | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.crashes_dir = output_dir / "crashes"
        self.serial = serial
        self.runner_log_path = runner_log_path
        self._run_factory = run_factory
        self._helper_dump_factory = helper_dump_factory or _default_helper_dump
        self._lock = threading.Lock()
        self._next_index = self._discover_next_index()
        self._seen_keys: set[tuple[str | None, str | None, str]] = set()

    def save_event(self, event: CrashEvent) -> None:
        event_dir = self.crashes_dir / event.crash_event_id
        event_dir.mkdir(parents=True, exist_ok=True)
        (event_dir / "crash_event.json").write_text(
            json.dumps(event.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (event_dir / "logcat_excerpt.txt").write_text(event.logcat_excerpt, encoding="utf-8", errors="replace")
        capture_crash_context(
            event=event,
            event_dir=event_dir,
            output_dir=self.output_dir,
            serial=self.serial,
            runner_log_path=self.runner_log_path,
            run_factory=self._run_factory,
            helper_dump_factory=self._helper_dump_factory,
        )

    def next_event_id(self) -> str:
        with self._lock:
            event_id = f"CRASH-{self._next_index:04d}"
            self._next_index += 1
            return event_id

    def mark_seen(self, event: CrashEvent) -> bool:
        key = (event.exception, event.top_frame, event.logcat_excerpt)
        with self._lock:
            if key in self._seen_keys:
                return False
            self._seen_keys.add(key)
            return True

    def _discover_next_index(self) -> int:
        if not self.crashes_dir.is_dir():
            return 1
        highest = 0
        for path in self.crashes_dir.iterdir():
            match = re.fullmatch(r"CRASH-(\d{4})", path.name)
            if match:
                highest = max(highest, int(match.group(1)))
        return highest + 1


class OneConnectCrashDetector:
    def __init__(self, store: CrashEventStore) -> None:
        self.store = store
        self._current_block: list[str] = []
        self._in_fatal_block = False

    def feed_line(self, line: str) -> list[CrashEvent]:
        events: list[CrashEvent] = []
        if FATAL_EXCEPTION_TOKEN in line:
            events.extend(self._finish_current_block())
            self._current_block = [line]
            self._in_fatal_block = True
            return events

        if not self._in_fatal_block:
            return events

        if self._is_crash_continuation(line):
            self._current_block.append(line)
            return events

        events.extend(self._finish_current_block())
        return events

    def finish(self) -> list[CrashEvent]:
        return self._finish_current_block()

    def _finish_current_block(self) -> list[CrashEvent]:
        if not self._current_block:
            self._in_fatal_block = False
            return []
        block = self._current_block
        self._current_block = []
        self._in_fatal_block = False
        event = self._event_from_block(block)
        if not event:
            return []
        if not self.store.mark_seen(event):
            return []
        self.store.save_event(event)
        return [event]

    def _event_from_block(self, block: list[str]) -> CrashEvent | None:
        text = "".join(block)
        if FATAL_EXCEPTION_TOKEN not in text or PROCESS_TOKEN not in text:
            return None
        exception = _extract_exception(block)
        top_frame = _extract_top_frame(block)
        return CrashEvent(
            crash_event_id=self.store.next_event_id(),
            crash_type="CONFIRMED_CRASH",
            process=ONECONNECT_PACKAGE,
            exception=exception,
            top_frame=top_frame,
            timestamp=_extract_timestamp(block) or datetime.now(timezone.utc).isoformat(),
            logcat_excerpt=text,
        )

    @staticmethod
    def _is_crash_continuation(line: str) -> bool:
        if not line.strip():
            return True
        if CRASH_BLOCK_SOURCE_TOKEN in line:
            return True
        stripped = _strip_logcat_prefix(line).strip()
        return (
            stripped.startswith("at ")
            or stripped.startswith("Caused by:")
            or stripped.startswith("Suppressed:")
            or stripped.startswith("... ")
        )


class LogcatCapture:
    def __init__(
        self,
        *,
        serial: str | None,
        output_dir: Path,
        popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        run_factory: RunFactory = subprocess.run,
        runner_log_path: Path | None = None,
        helper_dump_factory: Callable[[str | None], Any] | None = None,
    ) -> None:
        self.serial = serial
        self.output_dir = output_dir
        self.logcat_path = output_dir / "logcat.txt"
        self.store = CrashEventStore(
            output_dir,
            serial=serial,
            runner_log_path=runner_log_path,
            run_factory=run_factory,
            helper_dump_factory=helper_dump_factory,
        )
        self.detector = OneConnectCrashDetector(self.store)
        self._popen_factory = popen_factory
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self.events: list[CrashEvent] = []

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        command = _adb_command(self.serial, ["logcat", "-v", "threadtime"])
        self._process = self._popen_factory(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 3.0) -> list[CrashEvent]:
        process = self._process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)
        if self._thread:
            self._thread.join(timeout=timeout)
        self._record_events(self.detector.finish())
        return list(self.events)

    def _read_loop(self) -> None:
        try:
            with self.logcat_path.open("w", encoding="utf-8", errors="replace") as log_file:
                stdout = self._process.stdout if self._process else None
                if not stdout:
                    return
                for line in stdout:
                    log_file.write(line)
                    self._record_events(self.detector.feed_line(line))
        except Exception:
            return

    def _record_events(self, events: Iterable[CrashEvent]) -> None:
        self.events.extend(events)


def clear_logcat(
    *,
    serial: str | None,
    run_factory: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess[str]:
    return run_factory(
        _adb_command(serial, ["logcat", "-c"]),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def start_crash_logcat_capture(
    *,
    serial: str | None,
    output_dir: Path,
    log_writer: LogWriter | None = None,
    run_factory: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    helper_dump_factory: Callable[[str | None], Any] | None = None,
    runner_log_path: Path | None = None,
) -> LogcatCapture | None:
    try:
        result = clear_logcat(serial=serial, run_factory=run_factory)
        if log_writer:
            log_writer(f"[CRASH_CAPTURE] logcat_clear returncode={result.returncode}")
        capture = LogcatCapture(
            serial=serial,
            output_dir=output_dir,
            popen_factory=popen_factory,
            run_factory=run_factory,
            runner_log_path=runner_log_path,
            helper_dump_factory=helper_dump_factory,
        )
        capture.start()
        if log_writer:
            log_writer(f"[CRASH_CAPTURE] logcat_capture started path='{capture.logcat_path}'")
        return capture
    except Exception as exc:
        if log_writer:
            log_writer(f"[CRASH_CAPTURE][warning] logcat_capture_unavailable error='{exc}'")
        return None


def stop_crash_logcat_capture(capture: LogcatCapture | None, *, log_writer: LogWriter | None = None) -> list[CrashEvent]:
    if not capture:
        return []
    try:
        events = capture.stop()
        if log_writer:
            log_writer(f"[CRASH_CAPTURE] logcat_capture stopped events={len(events)}")
        return events
    except Exception as exc:
        if log_writer:
            log_writer(f"[CRASH_CAPTURE][warning] logcat_capture_stop_failed error='{exc}'")
        return []


def _adb_command(serial: str | None, args: list[str]) -> list[str]:
    command = ["adb"]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    return command


def capture_crash_context(
    *,
    event: CrashEvent,
    event_dir: Path,
    output_dir: Path,
    serial: str | None,
    runner_log_path: Path | None,
    run_factory: RunFactory = subprocess.run,
    helper_dump_factory: Callable[[str | None], Any] | None = None,
) -> dict[str, object]:
    event_dir.mkdir(parents=True, exist_ok=True)
    capture_errors: dict[str, str] = {}
    runtime = _extract_runtime_context(runner_log_path)

    screenshot_path = event_dir / "crash_screenshot.png"
    screenshot_error = _capture_screenshot(serial=serial, path=screenshot_path, run_factory=run_factory)
    if screenshot_error:
        capture_errors["screenshot"] = screenshot_error

    window_path = event_dir / "crash_window_dump.xml"
    window_error = _capture_window_dump(serial=serial, path=window_path, run_factory=run_factory)
    if window_error:
        capture_errors["window_dump"] = window_error

    helper_path = event_dir / "crash_helper_dump.json"
    helper_error = _capture_helper_dump(serial=serial, path=helper_path, helper_dump_factory=helper_dump_factory)
    if helper_error:
        capture_errors["helper_dump"] = helper_error

    current_package, foreground_error = _capture_current_package(serial=serial, run_factory=run_factory)
    if foreground_error:
        capture_errors["foreground"] = foreground_error

    focus_state = {
        "timestamp": event.timestamp,
        "foreground_package_before": None,
        "foreground_package_after": current_package,
        "current_package": current_package,
        "last_known_focus_label": runtime.get("last_focus_label"),
        "last_known_talkback_speech": runtime.get("last_speech"),
        "last_known_visible_text": runtime.get("last_visible_text"),
        "last_known_action": runtime.get("last_action"),
        "latest_step_log": runtime.get("latest_step_log"),
    }
    focus_state_path = event_dir / "focus_state.json"
    focus_state_path.write_text(json.dumps(focus_state, ensure_ascii=False, indent=2), encoding="utf-8")

    context = _build_crash_context(
        event=event,
        serial=serial,
        runtime=runtime,
        current_package=current_package,
        capture_errors=capture_errors,
    )
    context_path = event_dir / "crash_context.json"
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

    repro_path = event_dir / "crash_repro.md"
    repro_path.write_text(_render_repro_guide(context, event_dir=event_dir), encoding="utf-8")
    return context


def _capture_screenshot(*, serial: str | None, path: Path, run_factory: RunFactory) -> str | None:
    try:
        result = run_factory(
            _adb_command(serial, ["exec-out", "screencap", "-p"]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10.0,
            check=False,
        )
        if result.returncode != 0:
            return _stderr_text(result) or f"returncode={result.returncode}"
        data = result.stdout if isinstance(result.stdout, bytes) else bytes(str(result.stdout or ""), "utf-8")
        if not data:
            return "empty screenshot payload"
        path.write_bytes(data)
        return None
    except Exception as exc:
        return str(exc)


def _capture_window_dump(*, serial: str | None, path: Path, run_factory: RunFactory) -> str | None:
    remote_path = f"/sdcard/tb_crash_{path.parent.name}_window_dump.xml"
    try:
        dump_result = run_factory(
            _adb_command(serial, ["shell", "uiautomator", "dump", remote_path]),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12.0,
            check=False,
        )
        if dump_result.returncode != 0:
            return str(dump_result.stdout or f"returncode={dump_result.returncode}")
        cat_result = run_factory(
            _adb_command(serial, ["shell", "cat", remote_path]),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8.0,
            check=False,
        )
        if cat_result.returncode != 0:
            return str(cat_result.stdout or f"returncode={cat_result.returncode}")
        path.write_text(str(cat_result.stdout or ""), encoding="utf-8", errors="replace")
        return None
    except Exception as exc:
        return str(exc)


def _capture_helper_dump(
    *,
    serial: str | None,
    path: Path,
    helper_dump_factory: Callable[[str | None], Any] | None,
) -> str | None:
    try:
        factory = helper_dump_factory or _default_helper_dump
        payload = factory(serial)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return None
    except Exception as exc:
        error_payload = {"nodes": None, "error": str(exc)}
        path.write_text(json.dumps(error_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(exc)


def _default_helper_dump(serial: str | None) -> dict[str, object]:
    from talkback_lib import A11yAdbClient

    client = A11yAdbClient(dev_serial=serial, start_monitor=False)
    nodes = client.dump_tree(dev=serial, wait_seconds=2.0)
    return {"nodes": nodes, "metadata": getattr(client, "last_dump_metadata", {})}


def _capture_current_package(*, serial: str | None, run_factory: RunFactory) -> tuple[str | None, str | None]:
    try:
        result = run_factory(
            _adb_command(serial, ["shell", "dumpsys", "window"]),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8.0,
            check=False,
        )
        if result.returncode != 0:
            return None, str(result.stdout or f"returncode={result.returncode}")
        return _extract_package_from_window_dump(str(result.stdout or "")), None
    except Exception as exc:
        return None, str(exc)


def _extract_package_from_window_dump(text: str) -> str | None:
    patterns = [
        r"mCurrentFocus=.*?\s([A-Za-z0-9_.]+)/",
        r"mFocusedApp=.*?\s([A-Za-z0-9_.]+)/",
        r"topResumedActivity=.*?\s([A-Za-z0-9_.]+)/",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _extract_runtime_context(runner_log_path: Path | None) -> dict[str, object]:
    if not runner_log_path or not runner_log_path.is_file():
        return _empty_runtime_context()
    try:
        lines = runner_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return _empty_runtime_context()

    current = _empty_runtime_context()
    for line in lines:
        scenario = _extract_first_match(
            line,
            [
                r"scenario='([^']+)'",
                r"scenario=([A-Za-z0-9_]+)",
                r"scenario_id='([^']+)'",
                r"scenario_id=([A-Za-z0-9_]+)",
            ],
        )
        if scenario:
            current["scenario"] = scenario
        step = _extract_first_match(line, [r"step=(\d+)"])
        if step is not None:
            current["step"] = int(step)
        action = _extract_first_match(line, [r"action='([^']*)'", r"action=([^\s]+)", r"move_result='([^']*)'"])
        target = _extract_first_match(line, [r"target='([^']*)'", r"target=([^\s]+)"])
        if action or target:
            current["last_action"] = {"type": action, "label": target, "raw": line}
        visible = _extract_first_match(line, [r"visible='([^']*)'", r"label='([^']*)'", r"talkback_label='([^']*)'"])
        if visible:
            current["last_focus_label"] = visible
            current["last_visible_text"] = [visible]
        speech = _extract_first_match(
            line,
            [
                r"merged_announcement='([^']*)'",
                r"speech='([^']*)'",
                r"actual_speech='([^']*)'",
                r"talkback='([^']*)'",
            ],
        )
        if speech:
            current["last_speech"] = speech
        if "[STEP]" in line or "[STOP][eval]" in line or "[SCENARIO][pre_nav]" in line:
            current["latest_step_log"] = line
    return current


def _empty_runtime_context() -> dict[str, object]:
    return {
        "scenario": None,
        "step": None,
        "last_action": None,
        "last_focus_label": None,
        "last_speech": None,
        "last_visible_text": None,
        "latest_step_log": None,
    }


def _build_crash_context(
    *,
    event: CrashEvent,
    serial: str | None,
    runtime: dict[str, object],
    current_package: str | None,
    capture_errors: dict[str, str],
) -> dict[str, object]:
    event_dir = f"crashes/{event.crash_event_id}"
    return {
        "schema_version": 1,
        "crash_event_id": event.crash_event_id,
        "device_id": serial,
        "package": ONECONNECT_PACKAGE,
        "crash_type": event.crash_type,
        "confidence": "high",
        "timestamp": event.timestamp,
        "scenario": {
            "name": runtime.get("scenario"),
            "plugin": runtime.get("scenario"),
            "run_mode": None,
        },
        "step": {
            "index": runtime.get("step"),
            "name": None,
            "attempt": None,
        },
        "last_action": runtime.get("last_action"),
        "last_focus_label": runtime.get("last_focus_label"),
        "last_speech": runtime.get("last_speech"),
        "last_visible_text": runtime.get("last_visible_text"),
        "foreground": {
            "before": None,
            "after": current_package,
        },
        "logcat": {
            "exception": event.exception,
            "process": event.process,
            "pid": None,
            "top_frame": event.top_frame,
            "signature": _crash_signature(event),
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
            "recovery": {
            "decision": "capture_only",
            "retry_count": 0,
            "result": "not_implemented",
        },
    }


def _format_action(last_action: object) -> str:
    if not last_action:
        return "Repeat the last recorded TalkBack navigation action"

    action_type = ""
    if isinstance(last_action, dict):
        action_type = str(last_action.get("type", "")).lower()
    elif isinstance(last_action, str):
        action_type = last_action.lower()

    if action_type in ("tap", "click", "double_tap"):
        return "Activate the focused item using TalkBack double tap"
    elif action_type in ("focus", "move_next", "smart_next"):
        return "Move TalkBack focus to the next item"
    elif action_type == "back":
        return "Press Back"
    else:
        return "Repeat the last recorded TalkBack navigation action"


def _format_crash_verification(crash_type: str | None) -> str:
    ct = str(crash_type).upper() if crash_type else ""
    if ct == "CONFIRMED_CRASH":
        return "Verify that SmartThings displays a crash dialog or terminates with a FATAL EXCEPTION."
    elif ct == "APP_TERMINATED":
        return "Verify that SmartThings leaves the foreground and Android Launcher becomes visible."
    elif ct == "POSSIBLE_CRASH":
        return "Verify that SmartThings unexpectedly leaves the expected screen or foreground."
    else:
        return "Verify that SmartThings leaves the expected screen or crashed."


def _map_resource_id(resource: str | None, label: str) -> str:
    if not resource:
        return f'the item "{label}"'
    if "folder_icon_view" in resource:
        return f'folder "{label}"'
    if "bottom_navigation" in resource:
        return "the bottom navigation tab"
    return f'the item "{label}"'


def _map_scenario(scenario: str) -> str:
    if scenario == "global_nav_main":
        return "Home"
    return scenario


def _extract_focused_node(event_dir: Path | None) -> str | None:
    if not event_dir:
        return None
    helper_path = event_dir / "crash_helper_dump.json"
    if not helper_path.is_file():
        return None
    try:
        data = json.loads(helper_path.read_text(encoding="utf-8"))
        nodes = data.get("nodes")
        if not nodes or not isinstance(nodes, list):
            return None
        for node in nodes:
            if isinstance(node, dict):
                text = node.get("text") or node.get("contentDescription")
                if text:
                    return str(text)
    except Exception:
        pass
    return None


def _render_repro_guide(context: dict[str, object], event_dir: Path | None = None) -> str:
    scenario = _nested_get(context, "scenario", "name") or "unknown"
    mapped_scenario = _map_scenario(str(scenario))
    crash_type = context.get("crash_type")
    crash_type_str = str(crash_type) if crash_type else "unknown"
    artifacts = context.get("artifacts") if isinstance(context.get("artifacts"), dict) else {}
    last_action = context.get("last_action")
    last_focus = context.get("last_focus_label") or "unknown"
    last_speech = context.get("last_speech") or "unknown"
    last_visible = context.get("last_visible_text")
    if isinstance(last_visible, list) and last_visible:
        last_visible_str = last_visible[0]
    else:
        last_visible_str = str(last_visible) if last_visible else "unknown"

    resource_id = _nested_get(context, "last_action", "resource") or context.get("resource")
    resource_id_str = str(resource_id) if resource_id else None
    mapped_focus = _map_resource_id(resource_id_str, str(last_focus))

    formatted_action = _format_action(last_action)
    formatted_verification = _format_crash_verification(crash_type_str)
    foreground_after = _nested_get(context, "foreground", "after") or "unknown"

    focused_ui_element = _extract_focused_node(event_dir)

    lines = [
        "# Manual Repro Guide",
        "",
        f"Device: {context.get('device_id') or 'unknown'}",
        f"Package: {context.get('package') or ONECONNECT_PACKAGE}",
        f"Scenario: {scenario}",
        f"Crash Type: {crash_type_str}",
        "",
        "## Preconditions",
        "",
        "1. Install the SmartThings app and sign in.",
        "2. Turn ON TalkBack.",
        "3. Enable the TalkBack A11y Helper accessibility service.",
        "4. Set the device language and region to match the test execution environment.",
        "",
        "## Manual Steps",
        "",
        "1. Launch SmartThings.",
        "2. Enable TalkBack.",
        f"3. Navigate to {mapped_scenario}.",
        f"4. Move TalkBack focus to {mapped_focus}.",
        f"5. Verify TalkBack announces \"{last_speech}\".",
        f"6. {formatted_action}.",
        f"7. {formatted_verification}",
        "",
        "## Observed Crash Context",
        "",
        f"Crash Type: {crash_type_str}",
        f"Last Focus: {last_focus}",
        f"Last Speech: {last_speech}",
        f"Foreground After Crash: {foreground_after}",
        "Detection Source: foreground_package_guard",
        "",
    ]

    if "screenshot" in artifacts:
        lines.append("Reference Screenshot:")
        screenshot_val = artifacts["screenshot"]
        screenshot_filename = Path(str(screenshot_val)).name if screenshot_val else "crash_screenshot.png"
        lines.append(screenshot_filename)
        lines.append("")

    if focused_ui_element:
        lines.append("Focused UI Element:")
        lines.append(focused_ui_element)
        lines.append("")

    lines.extend([
        "## Raw Context",
        "",
        f"- Last action (raw): {json.dumps(last_action, ensure_ascii=False) if last_action else 'null'}",
        "",
        "## Crash Evidence",
        "",
        f"- Exception: {_nested_get(context, 'logcat', 'exception') or 'unknown'}",
        f"- Top frame: {_nested_get(context, 'logcat', 'top_frame') or 'unknown'}",
        f"- Signature: {_nested_get(context, 'logcat', 'signature') or 'unknown'}",
        "",
        "## Artifacts",
        "",
    ])
    for key in ("crash_event", "logcat_excerpt", "screenshot", "window_dump", "helper_dump", "focus_state"):
        value = artifacts.get(key) if isinstance(artifacts, dict) else None
        lines.append(f"- {key}: {value or 'not available'}")

    lines.append("")

    kor_obs = ""
    ct = crash_type_str.upper()
    if ct == "APP_TERMINATED":
        kor_obs = "* SmartThings가 종료됨\n* Android Launcher로 이동\n* FATAL EXCEPTION 없음"
    elif ct == "CONFIRMED_CRASH":
        kor_obs = "* SmartThings 크래시 발생\n* FATAL EXCEPTION 확인"
    elif ct == "POSSIBLE_CRASH":
        kor_obs = "* 예상 화면 이탈\n* 확정 크래시 아님"
    else:
        kor_obs = "* 예상 화면 이탈 또는 크래시"

    lines.extend([
        "# 재현 가이드 요약 (Korean)",
        "",
        "## 재현 위치",
        f"* 시나리오: {scenario}",
        f"* 마지막 포커스: {last_focus}",
        f"* 마지막 음성: {last_speech}",
        f"* 마지막 표시 텍스트: {last_visible_str}",
        "",
        "## 재현 절차",
        "1. SmartThings 실행",
        "2. TalkBack 활성화",
        "3. 대상 화면 진입",
        "4. 마지막 포커스 요소로 이동",
        "5. 더블탭 수행",
        "6. 앱 종료 또는 크래시 여부 확인",
        "",
        "## 관찰 결과",
        f"{ct}:",
        kor_obs,
        "",
        "## 수집 정보",
        f"* Crash Type: {crash_type_str}",
        "* Detection Source: foreground_package_guard",
        f"* Last Focus: {last_focus}",
        f"* Last Speech: {last_speech}",
        f"* Foreground After Crash: {foreground_after}",
    ])

    return "\n".join(lines) + "\n"


def _crash_signature(event: CrashEvent) -> str | None:
    if event.exception and event.top_frame:
        return f"{event.exception}@{event.top_frame}"
    return event.exception or event.top_frame


def _nested_get(value: dict[str, object], *keys: str) -> object:
    current: object = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_first_match(line: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            return match.group(1)
    return None


def _stderr_text(result: subprocess.CompletedProcess[Any]) -> str:
    stderr = getattr(result, "stderr", None)
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace").strip()
    return str(stderr or "").strip()


def _extract_exception(block: list[str]) -> str | None:
    for line in block:
        stripped = _strip_logcat_prefix(line).strip()
        if not stripped or stripped.startswith("FATAL EXCEPTION") or stripped.startswith("Process:"):
            continue
        if stripped.startswith(("at ", "Caused by:", "Suppressed:", "... ")):
            continue
        if "." in stripped or "Exception" in stripped or "Error" in stripped:
            return stripped
    return None


def _extract_top_frame(block: list[str]) -> str | None:
    for line in block:
        stripped = _strip_logcat_prefix(line).strip()
        if stripped.startswith("at "):
            return stripped[3:]
    return None


def _extract_timestamp(block: list[str]) -> str | None:
    for line in block:
        match = re.match(r"(?P<ts>\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})", line)
        if match:
            return match.group("ts")
    return None


def _strip_logcat_prefix(line: str) -> str:
    marker = f"{CRASH_BLOCK_SOURCE_TOKEN}:"
    if marker in line:
        return line.split(marker, 1)[1]
    if ": " in line:
        return line.split(": ", 1)[-1]
    return line
