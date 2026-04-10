#!/usr/bin/env python3
"""ADB 기반 TalkBack A11y Helper 테스트/클라이언트."""

from __future__ import annotations

import json
import os
import re
import hashlib
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from talkback_lib.action_result_parser import ActionResultParser
from talkback_lib.adb_executor import AdbExecutor
from talkback_lib.adb_device import AdbDevice
from talkback_lib.constants import (
    ACTION_CHECK_TARGET,
    ACTION_CLICK_FOCUSED,
    ACTION_CLICK_TARGET,
    ACTION_COMMAND,
    ACTION_DUMP_TREE,
    ACTION_FOCUS_TARGET,
    ACTION_GET_FOCUS,
    ACTION_NEXT,
    ACTION_PING,
    ACTION_PREV,
    ACTION_SCROLL,
    ACTION_SET_TEXT,
    ACTION_SMART_NEXT,
    ACTION_TOUCH_BOUNDS_CENTER_TARGET,
    CLIENT_ALGORITHM_VERSION,
    DEFAULT_ADB_PATH,
    DEFAULT_PACKAGE_NAME,
    DEFAULT_TIMEOUT_SECONDS,
    LOGCAT_FILTER_SPECS,
    LOGCAT_TIME_PATTERN,
    LOG_LEVEL,
    LOG_LEVEL_ORDER,
    RED_TEXT,
    RESET_TEXT,
    STATUS_FAILED,
    STATUS_LOOPED,
    STATUS_MOVED,
    STATUS_SCROLLED,
)
from talkback_lib.helper_bridge import HelperBridge
from talkback_lib.logcat_reader import LogcatReader
from talkback_lib.focus_trace_builder import build_initial_get_focus_trace, extract_focus_payload_candidate
from talkback_lib.step_row_builder import (
    build_noise_trim_anchor_labels,
    compute_prev_speech_flags,
    create_base_step_row,
    extract_smart_nav_row_fields,
    populate_focus_fields_from_node,
    populate_get_focus_trace_fields,
)
from talkback_lib.utils import (
    json_safe_value,
    normalize_bounds,
    normalize_for_comparison,
    parse_bottom_from_bounds,
    parse_bounds_tuple,
    safe_parse_json_payload,
)

RETRY_TIMEOUT_REFACTOR_VERSION = "PR11.0"
PR12_REFACTOR_CLEANUP_VERSION = "PR12.0"
PR13_CACHE_OPT_VERSION = "PR13.1"
PR14_CLIENT_SPLIT_VERSION = "PR14-B.0"


@dataclass
class A11yAdbClient:
    adb_path: str = DEFAULT_ADB_PATH
    package_name: str = DEFAULT_PACKAGE_NAME
    dev_serial: str | None = None
    start_monitor: bool = True

    def __post_init__(self) -> None:
        self.needs_update = True
        self.last_announcements: list[str] = []
        self.last_merged_announcement: str = ""
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_proc: subprocess.Popen[str] | None = None
        self._monitor_thread: threading.Thread | None = None
        self._last_log_marker: tuple[tuple[int, int, int, int, int, int], int] | None = None
        self.last_dump_metadata: dict[str, Any] = {}
        self.last_smart_nav_result: dict[str, Any] = {}
        self.last_smart_nav_terminal: bool = False
        self.last_target_action_result: dict[str, Any] = {}
        self._helper_status_cache: dict[str, Any] = {
            "ts": 0.0,
            "serial": None,
            "result": None,
        }
        self._helper_status_cache_by_serial: dict[str, dict[str, Any]] = {}
        self.helper_status_cache_ttl_sec: float = 4.0
        self.helper_status_fail_cache_ttl_sec: float = 0.7
        self.last_get_focus_trace: dict[str, Any] = {}
        self._prev_step_merged_announcement: str = ""
        self._last_action_payload: dict[str, Any] | None = None
        self._last_action_req_id: str = ""
        self._last_action_timestamp: float = 0.0
        self.log_level = LOG_LEVEL if LOG_LEVEL in LOG_LEVEL_ORDER else "NORMAL"
        self._adb_device = AdbDevice(
            adb_path=self.adb_path,
            resolve_serial=self._resolve_serial,
        )
        self._adb_executor = AdbExecutor(self._adb_device)
        self._logcat_reader = LogcatReader(run_cmd=self._run_via_client)
        self._helper_bridge = HelperBridge(client=self)

    def _is_debug_log_enabled(self) -> bool:
        return LOG_LEVEL_ORDER.get(self.log_level, 1) >= LOG_LEVEL_ORDER["DEBUG"]

    def _debug_print(self, message: str) -> None:
        if self._is_debug_log_enabled():
            print(message)

    def _resolve_serial(self, dev: Any) -> str | None:
        if dev is None:
            return self.dev_serial
        if isinstance(dev, str):
            return dev
        serial = getattr(dev, "serial", None)
        if serial:
            return serial
        return getattr(dev, "device_id", self.dev_serial)

    @staticmethod
    def _cache_serial_key(serial: str | None) -> str:
        return serial or "default"

    def _get_cached_helper_status(self, serial: str | None, now: float | None = None) -> tuple[bool, bool]:
        now_mono = time.monotonic() if now is None else now
        key = self._cache_serial_key(serial)
        cached = self._helper_status_cache_by_serial.get(key)
        if not isinstance(cached, dict):
            return False, False

        result = cached.get("result")
        if result is None:
            return False, False

        age = now_mono - float(cached.get("ts", 0.0))
        ttl = self.helper_status_cache_ttl_sec if bool(result) else self.helper_status_fail_cache_ttl_sec
        if age <= ttl:
            return True, bool(result)
        return False, False

    def _update_helper_status_cache(self, serial: str | None, result: bool) -> None:
        now = time.monotonic()
        cache_entry = {
            "ts": now,
            "serial": serial,
            "result": bool(result),
        }
        self._helper_status_cache = cache_entry
        self._helper_status_cache_by_serial[self._cache_serial_key(serial)] = cache_entry

    def _has_recent_helper_ok(self, dev: Any = None) -> bool:
        serial = self._resolve_serial(dev)
        cache_hit, cache_result = self._get_cached_helper_status(serial=serial)
        return cache_hit and cache_result

    def is_talkback_enabled(self, dev: Any = None) -> bool:
        accessibility_enabled = self._run(
            ["shell", "settings", "get", "secure", "accessibility_enabled"],
            dev=dev,
        ).strip()
        if accessibility_enabled != "1":
            return False

        enabled_services = self._run(
            ["shell", "settings", "get", "secure", "enabled_accessibility_services"],
            dev=dev,
        )
        services_lower = enabled_services.lower()
        talkback_service_tokens = (
            "talkback",
            "com.google.android.marvin.talkback",
            "com.samsung.android.accessibility.talkback",
        )
        return any(token in services_lower for token in talkback_service_tokens)

    def check_talkback_ready(self, dev: Any = None) -> dict[str, str]:
        configured_service_found = self.is_talkback_enabled(dev=dev)
        print(f"[PREFLIGHT] configured_service_found={configured_service_found}")
        if not configured_service_found:
            print("[PREFLIGHT] final_status=disabled final_reason=talkback_off")
            return {"status": "disabled", "reason": "talkback_off"}
        helper_ready = self.check_helper_status(dev=dev)
        print(f"[PREFLIGHT] helper_ready={helper_ready}")
        if not helper_ready:
            print("[PREFLIGHT] final_status=enabled_but_not_ready final_reason=talkback_not_ready")
            return {"status": "enabled_but_not_ready", "reason": "talkback_not_ready"}
        sanity_retry_count = 2
        sanity_get_focus_success = False
        sanity_meaningful_focus = False
        for attempt in range(1, sanity_retry_count + 2):
            focus_node = self.get_focus(
                dev=dev,
                wait_seconds=1.2,
                allow_fallback_dump=False,
                mode="fast",
            )
            sanity_get_focus_success = bool(focus_node)
            sanity_meaningful_focus = self._is_meaningful_focus_node(focus_node)
            print(
                f"[PREFLIGHT][sanity] attempt={attempt} "
                f"success={sanity_get_focus_success} meaningful={sanity_meaningful_focus}"
            )
            if sanity_get_focus_success and sanity_meaningful_focus:
                break
            if attempt <= sanity_retry_count:
                print(f"[PREFLIGHT][sanity] retry={attempt}/{sanity_retry_count}")
                time.sleep(0.4)
        print(
            f"[PREFLIGHT][sanity] final success={sanity_get_focus_success} "
            f"meaningful={sanity_meaningful_focus}"
        )
        if not (sanity_get_focus_success and sanity_meaningful_focus):
            print("[PREFLIGHT] sanity failed but proceeding reason='no_initial_focus'")
            print("[PREFLIGHT] sanity failed, running readiness probe")
            self.move_focus(dev=dev, direction="next")
            probe_focus_node = self.get_focus(
                dev=dev,
                wait_seconds=1.0,
                allow_fallback_dump=False,
                mode="fast",
            )
            probe_success = bool(probe_focus_node)
            probe_meaningful = self._is_meaningful_focus_node(probe_focus_node)
            print(f"[PREFLIGHT][probe] success={probe_success} meaningful={probe_meaningful}")
            if not (probe_success and probe_meaningful):
                print("[PREFLIGHT] probe failed -> false_positive_enabled")
                print("[PREFLIGHT] final_status=enabled_but_not_ready final_reason=false_positive_enabled")
                return {"status": "enabled_but_not_ready", "reason": "false_positive_enabled"}
            print("[PREFLIGHT] probe passed -> enabled")
        print("[PREFLIGHT] final_status=enabled final_reason=ok")
        return {"status": "enabled", "reason": "ok"}

    def _run(self, args: list[str], dev: Any = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
        return self._adb_executor.run(args, dev=dev, timeout=timeout)

    def _run_via_client(self, args: list[str], dev: Any = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
        return self._run(args, dev=dev, timeout=timeout)

    def check_helper_status(self, dev: Any = None) -> bool:
        return self._helper_bridge._helper_ready_check(dev=dev)

    def ping(self, dev: Any = None, wait_: float = 3.0) -> bool:
        return self._helper_bridge._ping_helper(dev=dev, wait_=wait_)

    def _broadcast(self, dev: Any, action: str, extras: list[str] | None = None) -> str:
        cmd = ["shell", "am", "broadcast", "-a", action, "-p", self.package_name]
        if extras:
            cmd.extend(extras)
        return self._run(cmd, dev=dev)

    @staticmethod
    def _escape_adb_string(value: str) -> str:
        if value == "":
            return '""'
        return "'" + value.replace("'", "'\\''") + "'"

    @staticmethod
    def _build_target_extras(
        name: str,
        type_: str,
        index_: int,
        long_: bool = False,
        class_name: str | None = None,
        clickable: bool | None = None,
        focusable: bool | None = None,
        target_text: str | None = None,
        target_id: str | None = None,
    ) -> list[str]:
        extras = [
            "--es", "targetName", A11yAdbClient._escape_adb_string(name),
            "--es", "targetType", type_,
            "--ei", "targetIndex", str(index_),
            "--ez", "isLongClick", "true" if long_ else "false",
        ]
        if class_name is not None:
            extras += ["--es", "className", A11yAdbClient._escape_adb_string(class_name)]
        if clickable is not None:
            extras += ["--es", "clickable", "true" if clickable else "false"]
        if focusable is not None:
            extras += ["--es", "focusable", "true" if focusable else "false"]
        if target_text is not None:
            extras += ["--es", "targetText", A11yAdbClient._escape_adb_string(target_text)]
        if target_id is not None:
            extras += ["--es", "targetId", A11yAdbClient._escape_adb_string(target_id)]
        return extras

    def _refresh_tree_if_needed(self, dev: Any = None) -> None:
        if self.needs_update:
            self.dump_tree(dev)

    def _wait_for_speech_if_needed(self, dev: Any = None, enabled: bool = True) -> None:
        if not enabled:
            return
        announcement = self.get_announcements(dev=dev, wait_seconds=1.5, only_new=True)
        if announcement:
            wait_time = max(0.5, min(len(announcement) * 0.12, 4.0))
            time.sleep(wait_time)
        else:
            time.sleep(0.5)

    @staticmethod
    def _extract_json_payload(log_text: str, prefix: str) -> str | None:
        pattern = re.compile(rf"{re.escape(prefix)}\s+(.*)$")
        for line in reversed(log_text.splitlines()):
            m = pattern.search(line)
            if m:
                return m.group(1).strip()
        return None

    @staticmethod
    def _parse_json_payload(payload: str, label: str) -> dict[str, Any]:
        return safe_parse_json_payload(payload=payload, label=label)

    def _read_log_result(
        self,
        dev: Any,
        prefix: str,
        req_id: str,
        wait_seconds: float = 2.0,
        poll_interval_sec: float = 0.25,
    ) -> dict[str, Any]:
        cache_window_sec = 0.4
        now_mono = time.monotonic()
        if (
            prefix == "TARGET_ACTION_RESULT"
            and self._last_action_req_id == req_id
            and isinstance(self._last_action_payload, dict)
            and now_mono - self._last_action_timestamp < cache_window_sec
        ):
            return self._last_action_payload
        start = time.monotonic()
        interval = max(0.05, poll_interval_sec)
        print(f"[SMART_NEXT_TRACE] read_log_result_start prefix={prefix} req_id={req_id} wait_seconds={wait_seconds}")
        while time.monotonic() - start < wait_seconds:
            logs = self._logcat_reader.dump_filtered(dev=dev)
            payloads = self._extract_all_payloads(logs, prefix)
            for payload in reversed(payloads):
                parsed = self._parse_json_payload(payload, prefix)
                if parsed.get("reqId") == req_id:
                    if prefix == "TARGET_ACTION_RESULT" and bool(parsed.get("success")):
                        self._last_action_payload = parsed
                        self._last_action_req_id = req_id
                        self._last_action_timestamp = time.monotonic()
                    print(f"[SMART_NEXT_TRACE] read_log_result_match prefix={prefix} req_id={req_id} parsed={parsed}")
                    return parsed
            elapsed = time.monotonic() - start
            remaining = wait_seconds - elapsed
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
        miss = {"success": False, "reason": f"{prefix} 로그를 찾지 못했습니다.", "reqId": req_id}
        print(f"[SMART_NEXT_TRACE] read_log_result_miss prefix={prefix} req_id={req_id} parsed={miss}")
        return miss

    @staticmethod
    def _extract_all_payloads(log_text: str, prefix: str) -> list[str]:
        return LogcatReader.extract_all_payloads(log_text=log_text, prefix=prefix)

    @staticmethod
    def _extract_req_payloads(log_text: str, prefix: str, req_id: str) -> list[str]:
        return LogcatReader.extract_req_payloads(log_text=log_text, prefix=prefix, req_id=req_id)

    @staticmethod
    def _has_req_marker(log_text: str, prefix: str, req_id: str) -> bool:
        return LogcatReader.has_req_marker(log_text=log_text, prefix=prefix, req_id=req_id)

    def clear_logcat(self, dev: Any = None) -> str:
        try:
            return self._run(["logcat", "-c"], dev=dev, timeout=5.0)
        except subprocess.TimeoutExpired:
            print("[WARN] logcat -c timed out, skipping...")
            return ""

    def _take_snapshot(self, dev: Any, save_path: str) -> None:
        """ADB screencap을 수행해 현재 화면을 로컬 파일로 저장합니다."""
        self._adb_device._capture_screen(dev=dev, save_path=save_path, remote_path="/sdcard/temp.png")

    def _save_failure_image(self, snapshot_path: Path, target_name: str, actual_speech: str) -> None:
        """Fail 케이스용 이미지에 EXPECTED/ACTUAL 오버레이를 추가해 저장합니다."""
        error_dir = Path("error_log")
        error_dir.mkdir(parents=True, exist_ok=True)
        safe_target_name = re.sub(r'[\\/*?:"<>|]', "_", target_name)
        fail_path = error_dir / f"fail_{safe_target_name}.png"

        base_image = Image.open(snapshot_path).convert("RGBA")
        overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        width, height = base_image.size
        panel_top = int(height * 0.75)
        draw.rectangle([(0, panel_top), (width, height)], fill=(0, 0, 0, 170))

        font_size = max(24, int(height * 0.03))
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

        expected_text = f"[EXPECTED]: {target_name}"
        actual_text = f"[ACTUAL]: {actual_speech}"
        draw.text((20, panel_top + 20), expected_text, font=font, fill=(255, 0, 0, 255))
        draw.text((20, panel_top + 20 + font_size + 10), actual_text, font=font, fill=(255, 0, 0, 255))

        merged = Image.alpha_composite(base_image, overlay)
        merged.convert("RGB").save(fail_path)

    def verify_speech(
        self,
        dev,
        expected_regex: str,
        wait_seconds: float = 3.0,
        take_error_snapshot: bool = True,
    ) -> bool:
        """병합된 최신 발화를 기준으로 정규식 매칭을 검증합니다."""
        safe_name = re.sub(r"[^0-9A-Za-z가-힣._-]", "_", expected_regex)
        safe_name = safe_name.strip(" ._") or "target"
        temp_path = Path(f"temp_{safe_name}.png")

        self._take_snapshot(dev, str(temp_path))

        actual_speech = self.get_announcements(dev=dev, wait_seconds=wait_seconds)
        if not actual_speech:
            actual_speech = "음성 없음"

        if re.search(expected_regex, actual_speech, re.IGNORECASE):
            if temp_path.exists():
                os.remove(temp_path)
            return True

        if take_error_snapshot and temp_path.exists():
            self._save_failure_image(temp_path, expected_regex, actual_speech)
        return False

    def check_talkback_status(self, dev: Any = None) -> bool:
        try:
            enabled_services = self._run(
                ["shell", "settings", "get", "secure", "enabled_accessibility_services"],
                dev=dev,
            )
        except Exception:
            return False

        return "talkback" in enabled_services.lower()

    def dump_tree(self, dev: Any = None, wait_seconds: float = 5.0) -> list[dict[str, Any]]:
        if not self.check_helper_status(dev=dev):
            return []
        self.last_announcements = []
        self.last_merged_announcement = ""
        self.clear_logcat(dev=dev)
        req_id = str(uuid.uuid4())[:8]
        self._broadcast(dev, ACTION_DUMP_TREE, ["--es", "reqId", req_id])

        start_time = time.time()
        logs = ""
        while time.time() - start_time < wait_seconds:
            logs = self._logcat_reader.dump_raw_filtered(dev=dev)
            if self._has_req_marker(logs, "DUMP_TREE_END", req_id):
                break
            time.sleep(1.0)

        payload_parts = self._extract_req_payloads(logs, "DUMP_TREE_PART", req_id)
        if not payload_parts:
            single_result = self._extract_req_payloads(logs, "DUMP_TREE_RESULT", req_id)
            if single_result:
                payload_parts = [single_result[-1]]

        if not payload_parts:
            a11y_lines = [l for l in logs.splitlines() if "A11Y_HELPER" in l]
            print(f"[DEBUG] 발견된 로그 요약: {a11y_lines}")
            raise RuntimeError("DUMP_TREE 로그를 찾지 못했습니다.")

        payload = "".join(payload_parts)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DUMP_TREE JSON 파싱 실패: {exc}") from exc

        if isinstance(parsed, dict):
            nodes = parsed.get("nodes")
            if not isinstance(nodes, list):
                raise RuntimeError("DUMP_TREE JSON 형식이 올바르지 않습니다.")
            self.last_dump_metadata = {
                "algorithmVersion": parsed.get("algorithmVersion"),
                "canScrollDown": bool(parsed.get("canScrollDown", False)),
            }
            return nodes

        if isinstance(parsed, list):
            self.last_dump_metadata = {
                "algorithmVersion": None,
                "canScrollDown": False,
            }
            return parsed

        raise RuntimeError("DUMP_TREE JSON 형식이 올바르지 않습니다.")


    @staticmethod
    def _split_and_conditions(name: Any, type_: str) -> tuple[str, str, str | None, str | None]:
        if not (isinstance(name, list) and str(type_).strip().lower() == "and"):
            return str(name), str(type_), None, None

        target_text: str | None = None
        target_id: str | None = None
        for item in name:
            token = str(item).strip()
            if not token:
                continue
            looks_like_id = "id/" in token or token.startswith(".*")
            if looks_like_id:
                target_id = token
            else:
                target_text = token

        return "", "", target_text, target_id

    @staticmethod
    def extract_visible_label_from_focus(focus_node: Any) -> str:
        """현재 포커스 노드(필요 시 children 포함)에서 대표 visible label을 추출합니다."""
        return A11yAdbClient._extract_visible_label_recursive(focus_node)

    @staticmethod
    def _extract_first_label_value(node: Any) -> str:
        """단일 노드에서 label 우선순위 기준 첫 유효 문자열을 추출합니다."""
        if not isinstance(node, dict):
            return ""

        for key in ("text", "contentDescription", "mergedLabel", "talkback", "content_desc", "label"):
            value = node.get(key)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
        return ""

    @staticmethod
    def _extract_visible_label_recursive(node: Any) -> str:
        """DFS(pre-order)로 현재 노드→children 순서로 대표 visible label을 탐색합니다."""
        if not isinstance(node, dict):
            return ""

        current_value = A11yAdbClient._extract_first_label_value(node)
        if current_value:
            return current_value

        children = node.get("children")
        if not isinstance(children, list):
            return ""

        for child in children:
            child_value = A11yAdbClient._extract_visible_label_recursive(child)
            if child_value:
                return child_value
        return ""

    @staticmethod
    def normalize_for_comparison(text: str | None) -> str:
        """비교 전 텍스트를 가볍게 정규화합니다."""
        return normalize_for_comparison(text)

    @staticmethod
    def _json_safe_value(value: Any) -> Any:
        """dict/list/scalar 중심의 JSON 직렬화 가능한 값으로 최대한 안전하게 변환합니다."""
        return json_safe_value(value)

    @staticmethod
    def _collect_text_samples(nodes: list[dict[str, Any]], max_samples: int = 10) -> list[str]:
        samples: list[str] = []

        def visit(node: Any) -> None:
            if len(samples) >= max_samples or not isinstance(node, dict):
                return

            for key in ("text", "contentDescription", "talkback", "content_desc", "label"):
                value = node.get(key)
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped:
                        samples.append(stripped)
                        if len(samples) >= max_samples:
                            return

            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    visit(child)
                    if len(samples) >= max_samples:
                        return

        for item in nodes:
            visit(item)
            if len(samples) >= max_samples:
                break

        return samples

    @staticmethod
    def _collect_all_text_nodes(nodes: list[dict[str, Any]]) -> list[str]:
        return A11yAdbClient._collect_text_samples(nodes, max_samples=10_000)

    @staticmethod
    def _collect_matching_values(nodes: list[dict[str, Any]], type_: str) -> list[str]:
        target_keys = A11yAdbClient._selector_key_candidates(type_)
        values: list[str] = []

        def visit(node: Any) -> None:
            if not isinstance(node, dict):
                return
            for key in target_keys:
                value = node.get(key)
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped:
                        values.append(stripped)
            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    visit(child)

        for item in nodes:
            visit(item)

        return values

    @staticmethod
    def _normalize_case_insensitive_pattern(name: str | list[str]) -> str | list[str]:
        if isinstance(name, list):
            return [A11yAdbClient._normalize_case_insensitive_pattern(item) for item in name]
        text = str(name)
        if not text or text.startswith("(?i)"):
            return text
        return f"(?i){text}"

    @staticmethod
    def _tree_signature(nodes: list[dict[str, Any]]) -> str:
        return json.dumps(nodes, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _tree_node_hashes(nodes: list[dict[str, Any]]) -> list[str]:
        hashes: list[str] = []

        def visit(node: Any) -> None:
            if not isinstance(node, dict):
                return
            canonical = json.dumps(node, ensure_ascii=False, sort_keys=True)
            hashes.append(hashlib.sha1(canonical.encode("utf-8")).hexdigest())
            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    visit(child)

        for item in nodes:
            visit(item)
        return hashes

    @staticmethod
    def _normalize_bounds(node: dict[str, Any]) -> str:
        return normalize_bounds(node)

    @staticmethod
    def _parse_bottom_from_bounds(bounds: str) -> int:
        return parse_bottom_from_bounds(bounds)

    @staticmethod
    def _parse_bounds_tuple(bounds: str) -> tuple[int, int, int, int] | None:
        return parse_bounds_tuple(bounds)

    @staticmethod
    def _center_viewport_vertical_range(nodes: list[dict[str, Any]]) -> tuple[float, float]:
        tops: list[int] = []
        bottoms: list[int] = []

        def visit(node: Any) -> None:
            if not isinstance(node, dict):
                return

            parsed = A11yAdbClient._parse_bounds_tuple(A11yAdbClient._normalize_bounds(node))
            if parsed:
                _, top, _, bottom = parsed
                tops.append(top)
                bottoms.append(bottom)

            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    visit(child)

        for item in nodes:
            visit(item)

        if not tops or not bottoms:
            return 0.0, 0.0

        viewport_top = min(tops)
        viewport_bottom = max(bottoms)
        viewport_height = max(0, viewport_bottom - viewport_top)

        center_top = viewport_top + (viewport_height * 0.15)
        center_bottom = viewport_bottom - (viewport_height * 0.15)
        return center_top, center_bottom

    @staticmethod
    def _collect_center_region_text_nodes_with_bounds(nodes: list[dict[str, Any]]) -> list[tuple[str, str]]:
        center_top, center_bottom = A11yAdbClient._center_viewport_vertical_range(nodes)
        pairs: list[tuple[str, str]] = []

        def visit(node: Any) -> None:
            if not isinstance(node, dict):
                return

            bounds = A11yAdbClient._normalize_bounds(node)
            parsed = A11yAdbClient._parse_bounds_tuple(bounds)
            if parsed:
                _, top, _, bottom = parsed
                center_y = (top + bottom) / 2.0

                text_candidates = [
                    node.get("text"),
                    node.get("contentDescription"),
                    node.get("talkback"),
                    node.get("content_desc"),
                    node.get("label"),
                ]
                text = next((str(value).strip() for value in text_candidates if isinstance(value, str) and value.strip()), "")

                if text and center_top <= center_y <= center_bottom:
                    pairs.append((text, bounds))

            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    visit(child)

        for item in nodes:
            visit(item)

        return pairs

    @staticmethod
    def _collect_text_nodes_with_bounds(nodes: list[dict[str, Any]]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []

        def visit(node: Any) -> None:
            if not isinstance(node, dict):
                return
            text_candidates = [
                node.get("text"),
                node.get("contentDescription"),
                node.get("talkback"),
                node.get("content_desc"),
                node.get("label"),
            ]
            text = next((str(value).strip() for value in text_candidates if isinstance(value, str) and value.strip()), "")
            if text:
                pairs.append((text, A11yAdbClient._normalize_bounds(node)))

            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    visit(child)

        for item in nodes:
            visit(item)
        return pairs

    @staticmethod
    def _has_screen_meaningful_change(before_nodes: list[dict[str, Any]], after_nodes: list[dict[str, Any]]) -> bool:
        before_pairs = A11yAdbClient._collect_center_region_text_nodes_with_bounds(before_nodes)
        after_pairs = A11yAdbClient._collect_center_region_text_nodes_with_bounds(after_nodes)

        if not before_pairs and not after_pairs:
            before_pairs = A11yAdbClient._collect_text_nodes_with_bounds(before_nodes)
            after_pairs = A11yAdbClient._collect_text_nodes_with_bounds(after_nodes)

        return set(before_pairs) != set(after_pairs)

    @staticmethod
    def _safe_regex_search(pattern: str, value: str) -> bool:
        try:
            return bool(re.search(pattern, value, re.IGNORECASE))
        except re.error:
            return bool(re.search(re.escape(pattern), value, re.IGNORECASE))

    @staticmethod
    def _selector_key_candidates(type_: str) -> tuple[str, ...]:
        normalized = str(type_).strip().lower()
        key_map = {
            "a": ("text", "contentDescription", "talkback", "content_desc", "label", "viewIdResourceName", "resourceId"),
            "all": ("text", "contentDescription", "talkback", "content_desc", "label", "viewIdResourceName", "resourceId"),
            "t": ("text", "contentDescription"),
            "text": ("text", "contentDescription"),
            "b": ("talkback", "contentDescription", "content_desc", "label"),
            "talkback": ("talkback", "contentDescription", "content_desc", "label"),
            "r": ("viewIdResourceName", "resourceId"),
            "resourceid": ("viewIdResourceName", "resourceId"),
        }
        return key_map.get(normalized, key_map["a"])

    def _find_bounds_for_selector(self, nodes: list[dict[str, Any]], name: str | list[str], type_: str) -> str:
        if not isinstance(nodes, list) or not nodes:
            return ""

        parsed_name, parsed_type, target_text, target_id = self._split_and_conditions(name, type_)
        selector_name = parsed_name
        selector_type = parsed_type or type_
        keys = self._selector_key_candidates(selector_type)
        patterns = selector_name if isinstance(selector_name, list) else [selector_name]

        def is_match(node: dict[str, Any]) -> bool:
            if isinstance(name, list) and str(type_).strip().lower() == "and":
                text_ok = True if not target_text else any(
                    self._safe_regex_search(target_text, text) for text in self._collect_matching_values([node], "t")
                )
                id_ok = True if not target_id else any(
                    self._safe_regex_search(target_id, text) for text in self._collect_matching_values([node], "r")
                )
                return text_ok and id_ok

            for key in keys:
                value = node.get(key)
                if not isinstance(value, str):
                    continue
                stripped = value.strip()
                if not stripped:
                    continue
                if any(self._safe_regex_search(str(pattern), stripped) for pattern in patterns):
                    return True
            return False

        def walk(node: Any, parent_bounds: str) -> str:
            if not isinstance(node, dict):
                return ""
            current_bounds = self._normalize_bounds(node)
            effective_parent_bounds = current_bounds or parent_bounds

            if is_match(node):
                return current_bounds or parent_bounds

            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    found = walk(child, effective_parent_bounds)
                    if found:
                        return found
            return ""

        for root in nodes:
            found = walk(root, "")
            if found:
                return found
        return ""

    def tap_xy_adb(self, dev: Any, x: int, y: int, timeout: float = 10.0) -> bool:
        return self._adb_device._tap(dev=dev, x=x, y=y, timeout=timeout)

    def tap_bounds_center_adb(
        self,
        dev: Any,
        name: str | list[str],
        type_: str = "a",
        dump_nodes: list[dict[str, Any]] | None = None,
    ) -> bool:
        normalized_type = str(type_).strip().lower()
        selector_name = name if normalized_type in {"r", "resourceid"} else self._normalize_case_insensitive_pattern(name)
        nodes = dump_nodes if isinstance(dump_nodes, list) else []

        lazy_dump_used = False
        bounds = self._find_bounds_for_selector(nodes, selector_name, type_) if nodes else ""
        if not bounds:
            try:
                lazy_dump_used = True
                nodes = self.dump_tree(dev=dev)
                bounds = self._find_bounds_for_selector(nodes, selector_name, type_)
            except Exception:
                bounds = ""

        if not bounds:
            self.last_target_action_result = {
                "success": False,
                "reason": "bounds_not_found",
                "target": {
                    "selector": {"name": self._json_safe_value(name), "type": str(type_)},
                    "lazy_dump_used": lazy_dump_used,
                },
            }
            return False

        parsed = self._parse_bounds_tuple(bounds)
        if not parsed:
            self.last_target_action_result = {
                "success": False,
                "reason": "invalid_bounds",
                "target": {
                    "selector": {"name": self._json_safe_value(name), "type": str(type_)},
                    "bounds": bounds,
                    "lazy_dump_used": lazy_dump_used,
                },
            }
            return False

        left, top, right, bottom = parsed
        center_x = (left + right) // 2
        center_y = (top + bottom) // 2
        tap_sent = self.tap_xy_adb(dev=dev, x=center_x, y=center_y)
        self.last_target_action_result = {
            "success": bool(tap_sent),
            "reason": "adb_input_tap_sent" if tap_sent else "adb_input_tap_failed",
            "target": {
                "selector": {"name": self._json_safe_value(name), "type": str(type_)},
                "bounds": bounds,
                "center": {"x": center_x, "y": center_y},
                "lazy_dump_used": lazy_dump_used,
            },
        }
        if tap_sent:
            self._wait_for_speech_if_needed(dev)
        return bool(tap_sent)

    def _match_target_in_tree(self, nodes: list[dict[str, Any]], name: str | list[str], type_: str) -> bool:
        if isinstance(name, list) and str(type_).strip().lower() == "and":
            _, _, target_text, target_id = self._split_and_conditions(name, type_)
            text_ok = True if not target_text else any(
                self._safe_regex_search(target_text, text) for text in self._collect_matching_values(nodes, "t")
            )
            id_ok = True if not target_id else any(
                self._safe_regex_search(target_id, text) for text in self._collect_matching_values(nodes, "r")
            )
            return text_ok and id_ok

        patterns = name if isinstance(name, list) else [name]
        candidates = self._collect_matching_values(nodes, type_)
        for pattern in patterns:
            if any(self._safe_regex_search(str(pattern), text) for text in candidates):
                return True
        return False

    def _log_scrollfind_text_nodes(self, nodes: list[dict[str, Any]]) -> None:
        center_pairs = self._collect_center_region_text_nodes_with_bounds(nodes)
        center_texts = [text for text, _ in center_pairs]
        print(f"[DEBUG][scrollFind] 중앙 70% 영역 텍스트 노드 개수: {len(center_pairs)}")
        print(f"[DEBUG][scrollFind] 중앙 70% 영역 텍스트 목록: {center_texts}")

    def _log_visible_text_samples(self, dev: Any, max_samples: int = 10) -> None:
        try:
            tree_nodes = self.dump_tree(dev=dev)
            samples = self._collect_all_text_nodes(tree_nodes)
            print(f"[DEBUG][isin] 현재 화면 텍스트: {samples}")
        except Exception as exc:
            print(f"[DEBUG][isin] 텍스트 노드 샘플 수집 실패: {exc}")

    def _normalize_action_result(
        self,
        success: bool,
        status: str | None = None,
        detail: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return ActionResultParser.normalize_action_result(
            success=success,
            status=status,
            detail=detail,
            raw=raw,
        )

    def _run_with_retry(
        self,
        wait_seconds: float,
        sleep_seconds: float,
        attempt_fn: Any,
        timeout_fn: Any,
        run_immediately: bool = False,
    ) -> Any:
        deadline = time.monotonic() + wait_seconds
        if run_immediately:
            done, value = attempt_fn()
            if done:
                return value
            time.sleep(sleep_seconds)
        while time.monotonic() <= deadline:
            done, value = attempt_fn()
            if done:
                return value
            time.sleep(sleep_seconds)
        return timeout_fn()

    @staticmethod
    def _is_target_action_payload_missing(result: dict[str, Any], req_id: str) -> bool:
        return ActionResultParser.is_target_action_payload_missing(result=result, req_id=req_id)

    @staticmethod
    def _is_target_action_success(result: Any) -> bool:
        return ActionResultParser.is_target_action_success(result=result)

    @staticmethod
    def _is_target_action_payload_for_req(result: dict[str, Any], req_id: str) -> bool:
        return ActionResultParser.is_target_action_payload_for_req(result=result, req_id=req_id)

    @staticmethod
    def _normalize_target_action_payload(result: Any) -> dict[str, Any]:
        return ActionResultParser.normalize_target_action_payload(result=result)

    def touch(
        self,
        dev,
        name: str | list[str],
        wait_: int = 5,
        type_: str = "a",
        index_: int = 0,
        long_: bool = False,
        class_name: str = None,
        clickable: bool = None,
        focusable: bool = None,
    ) -> dict[str, Any]:
        if not self.check_helper_status(dev=dev):
            self.last_target_action_result = {"success": False, "reason": "helper_unavailable"}
            return self._normalize_action_result(
                success=False,
                status=STATUS_FAILED,
                detail="helper_unavailable",
                raw=self.last_target_action_result,
            )
        self.last_announcements = []
        self.last_merged_announcement = ""
        
        def _attempt_touch() -> tuple[bool, dict[str, Any]]:
            # 1) 요청 준비/전송
            self._refresh_tree_if_needed(dev)
            self.clear_logcat(dev=dev)
            req_id = str(uuid.uuid4())[:8]
            parsed_name, parsed_type, target_text, target_id = self._split_and_conditions(name, type_)
            extras = self._build_target_extras(
                name=parsed_name,
                type_=parsed_type,
                index_=index_,
                long_=long_,
                class_name=class_name,
                clickable=clickable,
                focusable=focusable,
                target_text=target_text,
                target_id=target_id,
            )
            extras += ["--es", "reqId", req_id]
            self._broadcast(
                dev,
                ACTION_CLICK_TARGET,
                extras,
            )

            # 2) payload 파싱 및 성공/실패 판정
            result = self._read_log_result(dev, "TARGET_ACTION_RESULT", req_id)
            if self._is_target_action_payload_missing(result, req_id):
                return False, {}
            self.last_target_action_result = self._normalize_target_action_payload(result)
            if self._is_target_action_success(result):
                self._wait_for_speech_if_needed(dev)
                return True, self._normalize_action_result(
                    success=True,
                    status=STATUS_MOVED,
                    detail=str(self.last_target_action_result.get("reason", "")) or None,
                    raw=self.last_target_action_result,
                )
            # 3) 실패 시 재시도 루프로 복귀
            return False, {}

        def _touch_timeout() -> dict[str, Any]:
            self.last_target_action_result = {"success": False, "reason": "timeout"}
            return self._normalize_action_result(
                success=False,
                status=STATUS_FAILED,
                detail="timeout",
                raw=self.last_target_action_result,
            )

        return self._run_with_retry(
            wait_seconds=wait_,
            sleep_seconds=0.5,
            attempt_fn=_attempt_touch,
            timeout_fn=_touch_timeout,
        )

    def touch_point(self, dev, x: int, y: int) -> bool:
        if not self.check_helper_status(dev=dev):
            return False
        try:
            self.last_announcements = []
            self.last_merged_announcement = ""
            self._run(["shell", "input", "tap", str(int(x)), str(int(y))], dev=dev)
            self._wait_for_speech_if_needed(dev)
            return True
        except Exception:
            return False

    def touch_bounds_center(
        self,
        dev,
        name: str | list[str],
        wait_: int = 5,
        type_: str = "a",
        index_: int = 0,
        class_name: str = None,
        clickable: bool = None,
        focusable: bool = None,
    ) -> bool:
        if not self.check_helper_status(dev=dev):
            self.last_target_action_result = {"success": False, "reason": "helper_unavailable"}
            return False
        self.last_announcements = []
        self.last_merged_announcement = ""
        deadline = time.monotonic() + wait_
        while time.monotonic() <= deadline:
            self._refresh_tree_if_needed(dev)
            self.clear_logcat(dev=dev)
            req_id = str(uuid.uuid4())[:8]
            parsed_name, parsed_type, target_text, target_id = self._split_and_conditions(name, type_)
            extras = self._build_target_extras(
                name=parsed_name,
                type_=parsed_type,
                index_=index_,
                class_name=class_name,
                clickable=clickable,
                focusable=focusable,
                target_text=target_text,
                target_id=target_id,
            )
            extras += ["--es", "reqId", req_id]
            self._broadcast(dev, ACTION_TOUCH_BOUNDS_CENTER_TARGET, extras)
            result = self._read_log_result(dev, "TARGET_ACTION_RESULT", req_id)
            self.last_target_action_result = result if isinstance(result, dict) else {"success": False, "reason": "unknown"}
            if bool(result.get("success")):
                self._wait_for_speech_if_needed(dev)
                return True
            time.sleep(0.5)
        self.last_target_action_result = {"success": False, "reason": "timeout"}
        return False

    def select(
        self,
        dev,
        name: str | list[str],
        wait_: int = 5,
        type_: str = "a",
        index_: int = 0,
        class_name: str = None,
        clickable: bool = None,
        focusable: bool = None,
    ) -> dict[str, Any]:
        if not self.check_helper_status(dev=dev):
            return self._normalize_action_result(
                success=False,
                status=STATUS_FAILED,
                detail="helper_unavailable",
                raw={"success": False, "reason": "helper_unavailable"},
            )
        self.last_announcements = []
        self.last_merged_announcement = ""
        normalized_type = str(type_).strip().lower()
        ci_name = name if normalized_type in {"r", "resourceid"} else self._normalize_case_insensitive_pattern(name)

        def _attempt_select() -> tuple[bool, dict[str, Any]]:
            # 1) 요청 준비/전송
            self._refresh_tree_if_needed(dev)
            self.clear_logcat(dev=dev)
            req_id = str(uuid.uuid4())[:8]
            parsed_name, parsed_type, target_text, target_id = self._split_and_conditions(ci_name, type_)
            extras = self._build_target_extras(
                name=parsed_name,
                type_=parsed_type,
                index_=index_,
                class_name=class_name,
                clickable=clickable,
                focusable=focusable,
                target_text=target_text,
                target_id=target_id,
            )
            extras += ["--es", "reqId", req_id]
            self._broadcast(
                dev,
                ACTION_FOCUS_TARGET,
                extras,
            )

            # 2) payload 파싱 및 payload_missing 우선 판정
            result = self._read_log_result(dev, "TARGET_ACTION_RESULT", req_id)
            if self._is_target_action_payload_missing(result, req_id):
                return False, {}

            # 3) req_id가 일치하는 payload면 success=false 포함 원본을 그대로 반환
            if self._is_target_action_payload_for_req(result, req_id):
                # success=false인 경우에도 helper의 원본 payload를 보존한다.
                self.last_target_action_result = result
                return True, self._normalize_action_result(
                    success=bool(result.get("success")),
                    status=STATUS_MOVED if bool(result.get("success")) else STATUS_FAILED,
                    detail=str(result.get("reason", "")) or None,
                    raw=result,
                )

            # 4) payload가 아직 준비되지 않은 경우 재시도 루프로 복귀
            return False, {}

        def _select_timeout() -> dict[str, Any]:
            self.last_target_action_result = {"success": False, "reason": "timeout"}
            return self._normalize_action_result(
                success=False,
                status=STATUS_FAILED,
                detail="timeout",
                raw=self.last_target_action_result,
            )

        return self._run_with_retry(
            wait_seconds=wait_,
            sleep_seconds=0.5,
            attempt_fn=_attempt_select,
            timeout_fn=_select_timeout,
        )

    def click_focused(self, dev: Any = None, wait_: int = 5) -> bool:
        if not self.check_helper_status(dev=dev):
            self.last_target_action_result = {"success": False, "reason": "helper_unavailable"}
            return False

        self.last_announcements = []
        self.last_merged_announcement = ""
        deadline = time.monotonic() + wait_
        while time.monotonic() <= deadline:
            self._refresh_tree_if_needed(dev)
            self.clear_logcat(dev=dev)
            req_id = str(uuid.uuid4())[:8]
            self._broadcast(
                dev,
                ACTION_CLICK_FOCUSED,
                ["--es", "reqId", req_id],
            )
            result = self._read_log_result(dev, "TARGET_ACTION_RESULT", req_id)
            self.last_target_action_result = result if isinstance(result, dict) else {"success": False, "reason": "unknown"}
            if bool(result.get("success")):
                self._wait_for_speech_if_needed(dev)
                return True
            time.sleep(0.5)
        self.last_target_action_result = {"success": False, "reason": "timeout"}
        return False

    def scroll(self, dev, direction, step_=50, time_=1000, bounds_=None) -> bool:
        if not self.check_helper_status(dev=dev):
            return False
        _ = (step_, time_, bounds_)
        direction_token = str(direction).strip().lower()

        direction_map = {
            "d": (True, "down"),
            "down": (True, "down"),
            "u": (False, "up"),
            "up": (False, "up"),
            "r": (True, "right"),
            "right": (True, "right"),
            "l": (False, "left"),
            "left": (False, "left"),
        }
        forward, normalized_direction = direction_map.get(direction_token, (True, "down"))

        self.clear_logcat(dev=dev)
        req_id = str(uuid.uuid4())[:8]
        self._broadcast(
            dev,
            ACTION_SCROLL,
            [
                "--ez", "forward", "true" if forward else "false",
                "--es", "direction", normalized_direction,
                "--es", "reqId", req_id,
            ],
        )
        time.sleep(1.5)
        result = self._read_log_result(dev, "SCROLL_RESULT", req_id)
        return bool(result.get("success"))

    @staticmethod
    def _top_visible_fingerprint(nodes: list[dict[str, Any]], max_samples: int = 6) -> str:
        pairs = A11yAdbClient._collect_text_nodes_with_bounds(nodes)
        top_candidates: list[tuple[int, int, str, str]] = []
        for text, bounds in pairs:
            parsed = A11yAdbClient._parse_bounds_tuple(bounds)
            if not parsed:
                continue
            left, top, _, _ = parsed
            normalized_text = text.strip().lower()
            if not normalized_text:
                continue
            top_candidates.append((top, left, normalized_text, bounds))

        if top_candidates:
            top_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
            return "|".join(f"{text}@{bounds}" for _, _, text, bounds in top_candidates[:max_samples])

        node_hashes = A11yAdbClient._tree_node_hashes(nodes)
        return "|".join(node_hashes[:max_samples])

    def scroll_to_top(self, dev: Any, max_swipes: int = 5, pause: float = 0.6) -> dict[str, Any]:
        attempts = max(1, int(max_swipes))
        print(f"[SCROLL_TOP] start max_swipes={attempts}")
        try:
            before_nodes = self.dump_tree(dev=dev)
        except Exception as exc:
            print(f"[SCROLL_TOP] skipped reason='screen_not_scrollable' detail='dump_tree_failed:{exc}'")
            return {"ok": False, "reached_top": False, "attempts": 0, "reason": "dump_tree_failed"}

        if not isinstance(before_nodes, list) or not before_nodes:
            print("[SCROLL_TOP] skipped reason='screen_not_scrollable' detail='empty_dump'")
            return {"ok": True, "reached_top": False, "attempts": 0, "reason": "empty_dump"}

        before_fp = self._top_visible_fingerprint(before_nodes)
        if not before_fp:
            print("[SCROLL_TOP] skipped reason='screen_not_scrollable' detail='missing_fingerprint'")
            return {"ok": True, "reached_top": False, "attempts": 0, "reason": "missing_fingerprint"}

        for attempt in range(1, attempts + 1):
            print(f"[SCROLL_TOP] swipe attempt={attempt}/{attempts}")
            scrolled = self.scroll(dev, "up")
            if not scrolled:
                print("[SCROLL_TOP] reached_top=true reason='scroll_failed'")
                return {"ok": True, "reached_top": True, "attempts": attempt, "reason": "scroll_failed"}

            time.sleep(max(0.0, pause))
            try:
                after_nodes = self.dump_tree(dev=dev)
                after_fp = self._top_visible_fingerprint(after_nodes) if isinstance(after_nodes, list) else ""
            except Exception as exc:
                print(f"[SCROLL_TOP] reached_top=false reason='dump_tree_failed' detail='{exc}'")
                return {"ok": False, "reached_top": False, "attempts": attempt, "reason": "dump_tree_failed"}

            changed = bool(after_fp and after_fp != before_fp)
            print(f"[SCROLL_TOP] changed={'true' if changed else 'false'}")
            if not changed:
                print("[SCROLL_TOP] reached_top=true reason='no_visible_change'")
                return {"ok": True, "reached_top": True, "attempts": attempt, "reason": "no_visible_change"}
            before_fp = after_fp

        print("[SCROLL_TOP] fallback_stop reason='max_swipes'")
        return {"ok": True, "reached_top": False, "attempts": attempts, "reason": "max_swipes"}

    def move_focus(self, dev: Any = None, direction: str = "next") -> bool:
        if not self.check_helper_status(dev=dev):
            return False

        direction_token = str(direction).strip().lower()
        action_map = {
            "next": ACTION_NEXT,
            "prev": ACTION_PREV,
        }
        action = action_map.get(direction_token)
        if action is None:
            print(f"[ERROR] 지원하지 않는 direction: {direction}. 'next' 또는 'prev'를 사용해 주세요.")
            return False

        self.clear_logcat(dev=dev)
        req_id = str(uuid.uuid4())[:8]
        self._broadcast(dev, action, ["--es", "reqId", req_id])

        result = self._read_log_result(dev, "NAV_RESULT", req_id)
        if bool(result.get("success")):
            self._wait_for_speech_if_needed(dev)
            return True

        print(f"[ERROR] move_focus 실패(direction={direction_token}): {result.get('reason', 'unknown')}")
        return False

    def _init_get_focus_trace(self, serial: str, req_id: str, mode: str) -> None:
        self.last_get_focus_trace = build_initial_get_focus_trace(serial=serial, req_id=req_id, mode=mode)
        self.last_get_focus_trace["started_at"] = time.time()

    def _extract_focus_payload_candidate(self, result: dict[str, Any]) -> tuple[dict[str, Any], str]:
        return extract_focus_payload_candidate(result=result)

    def _run_get_focus_fallback_dump(
        self,
        dev: Any,
        serial: str,
        req_id: str,
        started: float,
    ) -> dict[str, Any]:
        fallback_started = time.monotonic()
        try:
            dump_nodes = self.dump_tree(dev=dev)
        except Exception as exc:
            self.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
            self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            self._debug_print(
                f"[DEBUG][get_focus] dump_tree fallback failed serial={serial} req_id={req_id} "
                f"error={exc} elapsed={self.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s"
            )
            return {}
        self.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
        self.last_get_focus_trace["fallback_dump_nodes"] = dump_nodes if isinstance(dump_nodes, list) else []
        fallback_focus_node = self._find_focused_node_in_tree(dump_nodes)
        if fallback_focus_node:
            label = self.extract_visible_label_from_focus(fallback_focus_node)
            view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
            bounds = self._normalize_bounds(fallback_focus_node)
            self.last_get_focus_trace["fallback_found"] = True
            self.last_get_focus_trace["fallback_node_label"] = label
            self.last_get_focus_trace["fallback_node_view_id"] = view_id
            self.last_get_focus_trace["fallback_node_bounds"] = bounds
            self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            self.last_get_focus_trace["focus_payload_source"] = "fallback_dump"
            self.last_get_focus_trace["final_payload_source"] = "fallback_dump"
            return fallback_focus_node
        self.last_get_focus_trace["fallback_found"] = False
        self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
        self.last_get_focus_trace["final_payload_source"] = "none"
        return {}

    def get_focus(
        self,
        dev: Any = None,
        wait_seconds: float = 2.0,
        allow_fallback_dump: bool = True,
        mode: str = "normal",
    ) -> dict[str, Any]:
        started = time.monotonic()
        serial = self._resolve_serial(dev) or "default"
        req_id = str(uuid.uuid4())[:8]
        self._init_get_focus_trace(serial=serial, req_id=req_id, mode=mode)
        fast_mode = self.last_get_focus_trace["mode"] == "fast"
        helper_ok = self._has_recent_helper_ok(dev=dev) or self.check_helper_status(dev=dev)
        self.last_get_focus_trace["helper_status_ok"] = helper_ok
        self._debug_print(
            f"[DEBUG][get_focus] start serial={serial} req_id={req_id} "
            f"wait={wait_seconds:.2f}s helper_ok={helper_ok} mode={self.last_get_focus_trace['mode']}"
        )
        if not helper_ok:
            self.last_get_focus_trace["empty_reason"] = "helper_not_ready"
            self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            return {}

        try:
            result = self._helper_bridge._request_get_focus(
                dev=dev,
                req_id=req_id,
                wait_seconds=wait_seconds,
                poll_interval_sec=0.2,
            )
        except RuntimeError as exc:
            self.last_get_focus_trace["response_received"] = False
            self.last_get_focus_trace["response_success"] = False
            self.last_get_focus_trace["empty_reason"] = "parse_error"
            self.last_get_focus_trace["fallback_used"] = bool(allow_fallback_dump)
            self.last_get_focus_trace["fallback_reason"] = "parse_error"
            self.last_get_focus_trace["elapsed_before_fallback_sec"] = time.monotonic() - started
            if not allow_fallback_dump:
                self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                self.last_get_focus_trace["final_payload_source"] = "none"
                self.last_get_focus_trace["final_focus_reason"] = "parse_error_fast_path_skip_dump"
                return {}
            self._debug_print(
                f"[DEBUG][get_focus] fallback_enter serial={serial} req_id={req_id} "
                f"reason=parse_error error={exc} "
                f"elapsed_before_fallback={self.last_get_focus_trace['elapsed_before_fallback_sec']:.3f}s"
            )
            fallback_focus_node = self._run_get_focus_fallback_dump(
                dev=dev,
                serial=serial,
                req_id=req_id,
                started=started,
            )
            if fallback_focus_node:
                label = self.extract_visible_label_from_focus(fallback_focus_node)
                view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
                bounds = self._normalize_bounds(fallback_focus_node)
                self.last_get_focus_trace["final_focus_reason"] = "parse_error_fallback_dump_found"
                self._debug_print(
                    f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=True "
                    f"label='{label}' view_id='{view_id}' bounds='{bounds}' "
                    f"dump_elapsed={self.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
                    f"total_elapsed={self.last_get_focus_trace['total_elapsed_sec']:.3f}s"
                )
                return fallback_focus_node

            self.last_get_focus_trace["fallback_found"] = False
            self.last_get_focus_trace["final_focus_reason"] = "parse_error_fallback_dump_not_found"
            self._debug_print(
                f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=False "
                f"dump_elapsed={self.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
                f"total_elapsed={self.last_get_focus_trace['total_elapsed_sec']:.3f}s"
            )
            return {}

        self.last_get_focus_trace["response_received"] = bool(result)
        success_field_present = "success" in result
        response_success = bool(result.get("success"))
        self.last_get_focus_trace["response_success"] = response_success
        self.last_get_focus_trace["success_field_present"] = success_field_present
        focus_node, payload_candidate_source = self._extract_focus_payload_candidate(result=result)
        self.last_get_focus_trace["focus_payload_source"] = payload_candidate_source

        major_keys = ("text", "contentDescription", "viewIdResourceName", "boundsInScreen")
        key_presence = {k: bool(str(result.get(k, "") or "").strip()) for k in major_keys}
        self._debug_print(
            f"[DEBUG][get_focus] response serial={serial} req_id={req_id} "
            f"success={response_success} keys={key_presence} result_keys={len(result.keys())} "
            f"payload_candidate_source={payload_candidate_source}"
        )

        if self._is_meaningful_focus_node(focus_node):
            accepted_with_success_false = (
                payload_candidate_source == "top_level"
                and not response_success
            )
            self.last_get_focus_trace["accepted_with_success_false"] = accepted_with_success_false
            self.last_get_focus_trace["empty_reason"] = ""
            if accepted_with_success_false:
                normalized_bounds = self._normalize_bounds(focus_node)
                parsed_bounds = self._parse_bounds_tuple(normalized_bounds)
                view_id = str(focus_node.get("viewIdResourceName", "") or "").strip()
                text_value = str(focus_node.get("text", "") or "").strip()
                content_desc = str(focus_node.get("contentDescription", "") or "").strip()
                merged_label = str(focus_node.get("mergedLabel", "") or "").strip()
                class_name = str(focus_node.get("className", "") or "").strip()
                label = self.extract_visible_label_from_focus(focus_node)
                has_focus_flag = bool(focus_node.get("accessibilityFocused")) or bool(focus_node.get("focused"))
                has_valid_bounds = bool(parsed_bounds)
                has_text_like_label = bool(text_value or content_desc or merged_label or label)
                has_identity = bool(view_id or class_name)
                top_level_signature = f"view_id='{view_id}' bounds='{normalized_bounds}' label='{label}'"
                self.last_get_focus_trace["top_level_signature"] = top_level_signature
                strong_top_level_payload = bool(
                    has_valid_bounds and (
                        has_text_like_label
                        or (has_focus_flag and has_identity)
                        or (view_id and class_name)
                    )
                )
                if not strong_top_level_payload and fast_mode:
                    strong_top_level_payload = has_valid_bounds
                self.last_get_focus_trace["top_level_payload_sufficient"] = strong_top_level_payload
                self._debug_print(
                    f"[DEBUG][get_focus] dump_skip_candidate={strong_top_level_payload} "
                    f"{top_level_signature} has_focus_flag={has_focus_flag}"
                )
                if strong_top_level_payload:
                    self.last_get_focus_trace["success_false_top_level_dump_skipped"] = True
                    self.last_get_focus_trace["dump_skip_reason"] = "strong_top_level_payload"
                    self.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                    self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                    self.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_policy_skip_dump"
                    print(
                        f"[INFO][get_focus] success=False top_level payload kept without dump fallback "
                        f"serial={serial} req_id={req_id} reason='strong_top_level_payload'"
                    )
                    return focus_node
                if not allow_fallback_dump:
                    self.last_get_focus_trace["success_false_top_level_dump_skipped"] = True
                    self.last_get_focus_trace["dump_skip_reason"] = "fast_path_skip_dump"
                    self.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                    self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                    self.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_fast_path_skip_dump"
                    return focus_node
                print(
                    f"[WARN][get_focus] success=False top_level payload accepted; trying dump fallback "
                    f"serial={serial} req_id={req_id}"
                )
                self.last_get_focus_trace["success_false_top_level_dump_attempted"] = True
                fallback_started = time.monotonic()
                try:
                    dump_nodes = self.dump_tree(dev=dev)
                except Exception as exc:
                    self.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
                    self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                    self.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                    self.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_kept_dump_error"
                    self.last_get_focus_trace["dump_replace_reason"] = "dump_error"
                    self._debug_print(
                        f"[DEBUG][get_focus] dump_tree fallback failed serial={serial} req_id={req_id} "
                        f"error={exc} elapsed={self.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s"
                    )
                    print(
                        f"[INFO][get_focus] success=False top_level payload kept; dump fallback found nothing "
                        f"serial={serial} req_id={req_id}"
                    )
                    return focus_node
                self.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
                self.last_get_focus_trace["fallback_dump_nodes"] = dump_nodes if isinstance(dump_nodes, list) else []
                fallback_focus_node = self._find_focused_node_in_tree(dump_nodes)
                if fallback_focus_node and self._is_meaningful_focus_node(fallback_focus_node):
                    label = self.extract_visible_label_from_focus(fallback_focus_node)
                    view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
                    bounds = self._normalize_bounds(fallback_focus_node)
                    self.last_get_focus_trace["fallback_found"] = True
                    self.last_get_focus_trace["success_false_top_level_dump_found"] = True
                    self.last_get_focus_trace["fallback_node_label"] = label
                    self.last_get_focus_trace["fallback_node_view_id"] = view_id
                    self.last_get_focus_trace["fallback_node_bounds"] = bounds
                    self.last_get_focus_trace["focus_payload_source"] = "fallback_dump"
                    self.last_get_focus_trace["final_payload_source"] = "fallback_dump"
                    self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                    self.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_replaced_by_dump"
                    self.last_get_focus_trace["dump_replace_reason"] = "focused_node_from_dump"
                    print(
                        f"[INFO][get_focus] success=False top_level payload replaced by dump focused node "
                        f"serial={serial} req_id={req_id}"
                    )
                    return fallback_focus_node
                print(
                    f"[INFO][get_focus] success=False top_level payload kept; dump fallback found nothing "
                    f"serial={serial} req_id={req_id}"
                )
                self.last_get_focus_trace["fallback_found"] = False
                self.last_get_focus_trace["success_false_top_level_dump_found"] = False
                self.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                self.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_kept_after_dump"
                self.last_get_focus_trace["dump_replace_reason"] = "dump_no_focused_node"
                return focus_node
            self.last_get_focus_trace["final_payload_source"] = payload_candidate_source
            self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            self.last_get_focus_trace["final_focus_reason"] = "accepted_meaningful_payload"
            return focus_node

        empty_reason = "no_response"
        if result:
            reason_text = str(result.get("reason", "") or "").lower()
            if "찾지 못했습니다" in reason_text:
                empty_reason = "timeout"
            elif not response_success:
                empty_reason = "empty_json"
            else:
                empty_reason = "missing_required_fields"
        self.last_get_focus_trace["empty_reason"] = empty_reason
        self.last_get_focus_trace["fallback_used"] = bool(allow_fallback_dump)
        self.last_get_focus_trace["fallback_reason"] = empty_reason
        self.last_get_focus_trace["elapsed_before_fallback_sec"] = time.monotonic() - started
        if not allow_fallback_dump:
            self.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            self.last_get_focus_trace["final_payload_source"] = "none"
            self.last_get_focus_trace["final_focus_reason"] = "fast_path_skip_dump"
            return {}
        self._debug_print(
            f"[DEBUG][get_focus] fallback_enter serial={serial} req_id={req_id} "
            f"reason={empty_reason} elapsed_before_fallback={self.last_get_focus_trace['elapsed_before_fallback_sec']:.3f}s"
        )
        fallback_focus_node = self._run_get_focus_fallback_dump(
            dev=dev,
            serial=serial,
            req_id=req_id,
            started=started,
        )
        if fallback_focus_node:
            label = self.extract_visible_label_from_focus(fallback_focus_node)
            view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
            bounds = self._normalize_bounds(fallback_focus_node)
            self.last_get_focus_trace["final_focus_reason"] = "fallback_dump_found"
            self._debug_print(
                f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=True "
                f"label='{label}' view_id='{view_id}' bounds='{bounds}' "
                f"dump_elapsed={self.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
                f"total_elapsed={self.last_get_focus_trace['total_elapsed_sec']:.3f}s"
            )
            return fallback_focus_node

        self.last_get_focus_trace["fallback_found"] = False
        self.last_get_focus_trace["final_focus_reason"] = "fallback_dump_not_found"
        print(
            f"[WARN][get_focus] empty focus result serial={serial} req_id={req_id} "
            f"reason={empty_reason} fallback_found=False"
        )
        self._debug_print(
            f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=False "
            f"dump_elapsed={self.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
            f"total_elapsed={self.last_get_focus_trace['total_elapsed_sec']:.3f}s"
        )
        return {}

    def press_back_and_recover_focus(
        self,
        dev: Any = None,
        expected_parent_anchor: str | list[str] | None = None,
        wait_seconds: float = 1.0,
        retry: int = 1,
        type_: str = "a",
        index_: int = 0,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "back_sent": False,
            "focus_found": False,
            "focus_recovered": False,
            "recovered_by": "",
            "status": "failed",
            "reason": "",
            "current_label": "",
        }

        try:
            self._run(["shell", "input", "keyevent", "4"], dev=dev, timeout=5.0)
            result["back_sent"] = True
        except Exception as exc:  # pragma: no cover - best effort guard
            result["reason"] = f"adb_back_exception:{exc}"

        if wait_seconds > 0:
            time.sleep(wait_seconds)

        try:
            focus_node = self.get_focus(dev=dev, wait_seconds=max(1.0, wait_seconds + 1.0))
        except Exception as exc:  # pragma: no cover - best effort guard
            focus_node = {}
            result["reason"] = result.get("reason") or f"get_focus_exception:{exc}"

        current_label = self.extract_visible_label_from_focus(focus_node)
        result["current_label"] = current_label
        result["focus_found"] = bool(focus_node)

        if not expected_parent_anchor:
            result["focus_recovered"] = result["focus_found"]
            result["recovered_by"] = "get_focus" if result["focus_found"] else ""
            if result["back_sent"] and result["focus_found"]:
                result["status"] = "ok"
            elif result["back_sent"]:
                result["status"] = "partial"
                result["reason"] = result["reason"] or "focus_not_found_after_back"
            else:
                result["status"] = "failed"
                result["reason"] = result["reason"] or "back_not_sent"
            return result

        anchors = expected_parent_anchor if isinstance(expected_parent_anchor, list) else [expected_parent_anchor]
        normalized_label = self.normalize_for_comparison(current_label)
        anchor_matched = any(self._safe_regex_search(str(anchor), normalized_label) for anchor in anchors)

        if anchor_matched:
            result["focus_recovered"] = True
            result["recovered_by"] = "anchor_match"
            result["status"] = "ok" if result["back_sent"] else "partial"
            return result

        attempts = max(1, int(retry) if retry is not None else 1)
        for _ in range(attempts):
            try:
                recovered = self.select(
                    dev,
                    name=expected_parent_anchor,
                    wait_=max(1, int(wait_seconds) if wait_seconds > 0 else 1),
                    type_=type_,
                    index_=index_,
                )
            except Exception as exc:  # pragma: no cover - best effort guard
                recovered = False
                result["reason"] = result.get("reason") or f"select_exception:{exc}"

            if recovered:
                result["focus_recovered"] = True
                result["recovered_by"] = "select_anchor"
                try:
                    recovered_focus = self.get_focus(dev=dev, wait_seconds=max(1.0, wait_seconds + 1.0))
                    result["focus_found"] = bool(recovered_focus)
                    result["current_label"] = self.extract_visible_label_from_focus(recovered_focus)
                except Exception:
                    pass
                result["status"] = "ok" if result["back_sent"] else "partial"
                return result

        result["focus_recovered"] = False
        result["recovered_by"] = ""
        if result["back_sent"]:
            result["status"] = "partial"
            result["reason"] = result["reason"] or "anchor_mismatch_and_select_failed"
        else:
            result["status"] = "failed"
            result["reason"] = result["reason"] or "back_not_sent"
        return result

    @staticmethod
    def _is_meaningful_focus_node(node: Any) -> bool:
        if not isinstance(node, dict) or not node:
            return False

        text_value = node.get("text")
        if isinstance(text_value, str) and text_value.strip():
            return True

        content_desc = node.get("contentDescription")
        if isinstance(content_desc, str) and content_desc.strip():
            return True

        view_id = node.get("viewIdResourceName")
        if isinstance(view_id, str) and view_id.strip():
            return True

        bounds = node.get("boundsInScreen")
        if isinstance(bounds, dict) and any(key in bounds for key in ("l", "t", "r", "b", "left", "top", "right", "bottom")):
            return True

        if bool(node.get("accessibilityFocused")):
            return True

        if bool(node.get("focused")):
            return True

        return False

    @staticmethod
    def _find_focused_node_in_tree(nodes: Any) -> dict[str, Any]:
        def _walk(node: Any) -> dict[str, Any]:
            if not isinstance(node, dict):
                return {}

            if bool(node.get("accessibilityFocused")):
                return node

            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    found = _walk(child)
                    if found:
                        return found
            return {}

        def _walk_focused(node: Any) -> dict[str, Any]:
            if not isinstance(node, dict):
                return {}

            if bool(node.get("focused")):
                return node

            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    found = _walk_focused(child)
                    if found:
                        return found
            return {}

        if not isinstance(nodes, list):
            return {}

        for node in nodes:
            found = _walk(node)
            if found:
                return found

        for node in nodes:
            found = _walk_focused(node)
            if found:
                return found

        return {}

    def _focus_first_node(self, dev: Any, nodes: list[dict[str, Any]]) -> bool:
        if not nodes:
            return False

        candidates = [
            node
            for node in nodes
            if not bool(node.get("isTopAppBar", False))
            and not bool(node.get("isBottomNavigationBar", node.get("isSystemNavigationBar", False)))
        ]
        if not candidates:
            return False

        target_node = min(
            candidates,
            key=lambda node: int((node.get("boundsInScreen") or {}).get("t", 10**9))
        )

        if bool(target_node.get("accessibilityFocused")):
            print(f"[DEBUG] 타겟이 이미 포커스되어 있습니다. (이동 성공 처리)")
            return True

        target_id = target_node.get("viewIdResourceName")
        if isinstance(target_id, str) and target_id.strip():
            return self.select(dev, name=f"^{re.escape(target_id.strip())}$", type_="r", index_=0)

        target_text = target_node.get("text")
        if isinstance(target_text, str) and target_text.strip():
            return self.select(dev, name=f"^{re.escape(target_text.strip())}$", type_="a", index_=0)

        target_desc = target_node.get("contentDescription")
        if isinstance(target_desc, str) and target_desc.strip():
            return self.select(dev, name=f"^{re.escape(target_desc.strip())}$", type_="b", index_=0)

        return False

    @staticmethod
    def _match_focus_index(nodes: list[dict[str, Any]], focus_node: dict[str, Any]) -> int:
        if not nodes or not focus_node:
            return -1

        focus_index = focus_node.get("index")
        if isinstance(focus_index, int) and 0 <= focus_index < len(nodes):
            return focus_index

        key_candidates = ("viewIdResourceName", "text", "contentDescription", "className", "boundsInScreen")
        for idx, node in enumerate(nodes):
            if all(node.get(key) == focus_node.get(key) for key in key_candidates if key in focus_node):
                return idx
        return -1

    def reset_focus_history(self, dev: Any = None) -> None:
        """안드로이드 헬퍼 앱의 탐색 히스토리 인덱스를 초기화합니다."""
        device_id = self._resolve_serial(dev)
        self._broadcast(dev, ACTION_COMMAND, ["--es", "command", "reset"])
        label = device_id or "default"
        print(f"[{label}] Focus history has been explicitly reset.")

    def move_focus_smart(self, dev: Any = None, direction: str = "next") -> dict[str, Any]:
        direction_token = str(direction).strip().lower()
        print(
            f"[SMART_NEXT_TRACE] move_focus_smart_entry "
            f"action={ACTION_SMART_NEXT} req_id='' fallback={'true' if direction_token != 'next' else 'false'}"
        )
        if direction_token != "next":
            print(
                "[SMART_NEXT_TRACE] move_focus_smart_fallback "
                f"reason='direction_not_next' action={ACTION_NEXT if direction_token == 'next' else ACTION_PREV if direction_token == 'prev' else 'UNKNOWN'} "
                "req_id='' fallback=true"
            )
            moved = self.move_focus(dev=dev, direction=direction_token)
            normalized_status = STATUS_MOVED if moved else STATUS_FAILED
            return self._normalize_action_result(
                success=bool(moved),
                status=normalized_status,
                raw={"status": normalized_status, "detail": "", "fallback": True},
            )

        if not (self._has_recent_helper_ok(dev=dev) or self.check_helper_status(dev=dev)):
            return self._normalize_action_result(
                success=False,
                status=STATUS_FAILED,
                raw={"status": STATUS_FAILED, "detail": "helper_unavailable"},
            )

        self.last_announcements = []
        self.last_merged_announcement = ""
        # Keep previous logcat history for SMART_NEXT analysis continuity.
        # self.clear_logcat(dev=dev)

        def _attempt_smart_next() -> tuple[bool, dict[str, Any]]:
            req_id = str(uuid.uuid4())[:8]
            print(f"[SMART_NEXT_TRACE] req_id_generated req_id={req_id} source=move_focus_smart")
            result = self._helper_bridge._request_smart_next(dev=dev, req_id=req_id)
            self.last_smart_nav_result = result
            normalized, terminal, _, _ = self._helper_bridge.normalize_smart_next_status(result)
            self.last_smart_nav_terminal = terminal
            print(
                f"[SMART_NEXT_TRACE] move_focus_smart_result req_id={req_id} "
                f"status={result.get('status', '')} detail={result.get('detail', '')} normalized={normalized}"
            )
            return True, self._normalize_action_result(
                success=normalized != STATUS_FAILED,
                status=normalized,
                detail=str(result.get("detail", "")) or None,
                raw=result if isinstance(result, dict) else {},
            )

        def _smart_next_timeout() -> dict[str, Any]:
            return self._normalize_action_result(
                success=False,
                status=STATUS_FAILED,
                detail="timeout",
                raw={"status": STATUS_FAILED, "detail": "timeout"},
            )

        # run_immediately=True:
        # SMART_NEXT는 내부적으로 즉시 단건 처리되는 요청이라 대기 루프 진입 전에 1회 즉시 시도한다.
        return self._run_with_retry(
            wait_seconds=0.0,
            sleep_seconds=0.0,
            attempt_fn=_attempt_smart_next,
            timeout_fn=_smart_next_timeout,
            run_immediately=True,
        )

    def scrollFind(self, dev, name, wait_=30, direction_='updown', type_='all'):
        if not self.check_helper_status(dev=dev):
            return False
        type_map = {
            "all": "a",
            "text": "t",
            "talkback": "b",
            "resourceid": "r",
        }
        parsed_type = type_map.get(str(type_).strip().lower(), str(type_).strip().lower()[:1] or "a")
        deadline = time.monotonic() + wait_
        direction_token = str(direction_).strip().lower()
        if direction_token == "updown":
            current_dir = "down"
            can_flip = True
        elif direction_token == "downup":
            current_dir = "up"
            can_flip = True
        else:
            current_dir = direction_
            can_flip = False

        scroll_attempt = 0
        while time.monotonic() <= deadline:
            if self.isin(dev, name, wait_=1, type_=parsed_type):
                return True

            scroll_attempt += 1
            before_tree: list[dict[str, Any]] | None = None
            after_tree: list[dict[str, Any]] | None = None
            try:
                before_tree = self.dump_tree(dev=dev)
                self._log_scrollfind_text_nodes(before_tree)
            except Exception as exc:
                print(f"[DEBUG][scrollFind] 스크롤 전 덤프 수집 실패: {exc}")
            print(f"[DEBUG][scrollFind] 스크롤 시도 #{scroll_attempt} (direction={current_dir})")
            scrolled = self.scroll(dev, current_dir)
            try:
                after_tree = self.dump_tree(dev=dev)
            except Exception as exc:
                print(f"[DEBUG][scrollFind] 스크롤 후 덤프 수집 실패: {exc}")

            if before_tree is not None and after_tree is not None:
                if not self._has_screen_meaningful_change(before_tree, after_tree):
                    print("[DEBUG][scrollFind] 화면 끝 도달 감지: 스크롤 전/후 텍스트/위치 변화가 없습니다.")
                    break

            if scrolled:
                self.needs_update = True
            if not scrolled and can_flip:
                current_dir = "up" if current_dir == "down" else "down"
                can_flip = False
            time.sleep(0.8)

        return None

    def scrollSelect(
        self,
        dev,
        name: str | list[str],
        wait_: int = 60,
        direction_: str = "updown",
        type_: str = "a",
        index_: int = 0,
        class_name: str = None,
        clickable: bool = None,
        focusable: bool = None,
    ) -> bool:
        print(f"[DEBUG][scrollSelect] 탐색 시작 (최대 {wait_}초 대기)")
        safe_type = "a" if str(type_).strip().lower() == "all" else type_

        found = self.scrollFind(dev, name, wait_=wait_, direction_=direction_, type_=safe_type)
        if found is not True:
            print("[DEBUG][scrollSelect] scrollFind 탐색 실패 (시간 초과 또는 객체 없음)")
            return False
        print("[DEBUG][scrollSelect] 객체 발견. 화면 안정화 대기 후 포커스 시도...")
        time.sleep(1.5)

        result = self.select(
            dev,
            name,
            wait_=10,
            type_=safe_type,
            index_=index_,
            class_name=class_name,
            clickable=clickable,
            focusable=focusable,
        )
        if not result:
            print("[DEBUG][scrollSelect] 객체는 화면에 있으나 포커스(select) 실패")
        return result

    def scrollTouch(
        self,
        dev,
        name: str | list[str],
        wait_: int = 60,
        direction_: str = "updown",
        type_: str = "a",
        index_: int = 0,
        long_: bool = False,
        class_name: str = None,
        clickable: bool = None,
        focusable: bool = None,
    ) -> bool:
        print(f"[DEBUG][scrollTouch] 탐색 시작 (최대 {wait_}초 대기)")
        safe_type = "a" if str(type_).strip().lower() == "all" else type_

        found = self.scrollFind(dev, name, wait_=wait_, direction_=direction_, type_=safe_type)
        if found is not True:
            print("[DEBUG][scrollTouch] scrollFind 탐색 실패 (시간 초과 또는 객체 없음)")
            return False
        print("[DEBUG][scrollTouch] 객체 발견. 화면 안정화 대기 후 터치 시도...")
        time.sleep(1.5)

        result = self.touch(
            dev,
            name,
            wait_=10,
            type_=safe_type,
            index_=index_,
            long_=long_,
            class_name=class_name,
            clickable=clickable,
            focusable=focusable,
        )
        if not result:
            print("[DEBUG][scrollTouch] 객체는 화면에 있으나 터치(touch) 실패")
        return result

    def typing(self, dev, name: str, adbTyping=False):
        if not self.check_helper_status(dev=dev):
            return False
        try:
            if adbTyping:
                self._run(["shell", "input", "text", self._escape_adb_string(name)], dev=dev)
                return None

            self.clear_logcat(dev=dev)
            req_id = str(uuid.uuid4())[:8]
            self._broadcast(dev, ACTION_SET_TEXT, ["--es", "text", self._escape_adb_string(name), "--es", "reqId", req_id])
            result = self._read_log_result(dev, "SET_TEXT_RESULT", req_id)
            if bool(result.get("success")):
                return None
            return False
        except Exception:
            return False

    def waitForActivity(self, dev, ActivityName: str, waitTime: int) -> bool:
        deadline = time.monotonic() + (waitTime / 1000.0)
        while time.monotonic() <= deadline:
            try:
                output = self._run(["shell", "dumpsys", "window", "windows"], dev=dev)
            except Exception:
                output = ""

            if "mCurrentFocus" in output or ActivityName in output:
                return True
            time.sleep(0.8)
        return False

    def isin(
        self,
        dev,
        name: str | list[str],
        wait_: int = 5,
        type_: str = "a",
        index_: int = 0,
        class_name: str = None,
        clickable: bool = None,
        focusable: bool = None,
    ) -> bool:
        if not self.check_helper_status(dev=dev):
            return False
        self.last_announcements = []
        self.last_merged_announcement = ""
        deadline = time.monotonic() + wait_
        ci_name = self._normalize_case_insensitive_pattern(name)
        print(f"[DEBUG][isin] 검색 시작 targetName={name}, targetType={type_}")
        while time.monotonic() <= deadline:
            try:
                tree_nodes = self.dump_tree(dev=dev)
                if self._match_target_in_tree(tree_nodes, ci_name, type_):
                    return True
            except Exception as exc:
                print(f"[DEBUG][isin] 사전 트리 매칭 실패: {exc}")

            self._refresh_tree_if_needed(dev)
            self.clear_logcat(dev=dev)
            req_id = str(uuid.uuid4())[:8]
            parsed_name, parsed_type, target_text, target_id = self._split_and_conditions(ci_name, type_)
            extras = self._build_target_extras(
                name=parsed_name,
                type_=parsed_type,
                index_=index_,
                class_name=class_name,
                clickable=clickable,
                focusable=focusable,
                target_text=target_text,
                target_id=target_id,
            )
            extras += ["--es", "reqId", req_id]
            self._broadcast(
                dev,
                ACTION_CHECK_TARGET,
                extras,
            )
            result = self._read_log_result(dev, "CHECK_TARGET_RESULT", req_id)
            if bool(result.get("success")):
                return True

            self._log_visible_text_samples(dev)
            time.sleep(0.5)
        return False

    @staticmethod
    def _merge_announcements(items: list[str]) -> str:
        """발화 조각 목록을 예측 가능한 규칙으로 하나의 문자열로 병합합니다."""
        normalized = [item.strip() for item in items if item.strip()]
        return " ".join(normalized)

    @staticmethod
    def _is_meaningful_prefix(prefix: str) -> bool:
        normalized_prefix = A11yAdbClient.normalize_for_comparison(prefix)
        if not normalized_prefix:
            return False
        tokens = normalized_prefix.split()
        if len(tokens) < 2:
            return False
        return any(any(ch.isalnum() for ch in token) for token in tokens)

    @staticmethod
    def _find_visible_anchor_prefix(speech: str, visible_label: str) -> tuple[str, str]:
        raw_speech = str(speech or "")
        raw_visible = str(visible_label or "").strip()
        if not raw_speech.strip() or not raw_visible:
            return "", "empty_speech_or_visible"

        normalized_speech = A11yAdbClient.normalize_for_comparison(raw_speech)
        normalized_visible = A11yAdbClient.normalize_for_comparison(raw_visible)
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
        if not A11yAdbClient._is_meaningful_prefix(prefix):
            return "", "prefix_not_meaningful"
        return prefix, "prefix_before_visible_anchor"

    @staticmethod
    def _is_contaminated_announcement_candidate(speech: str, visible_label: str) -> tuple[bool, str]:
        prefix, reason = A11yAdbClient._find_visible_anchor_prefix(speech, visible_label)
        return bool(prefix), reason

    @staticmethod
    def _try_trim_prefix_by_visible_anchor(speech: str, visible_label: str) -> tuple[str, bool, str]:
        raw_speech = str(speech or "")
        prefix, reason = A11yAdbClient._find_visible_anchor_prefix(raw_speech, visible_label)
        if not prefix:
            return raw_speech, False, reason
        trimmed = raw_speech[len(prefix) :].lstrip(" \t,.;:-")
        if not A11yAdbClient.normalize_for_comparison(trimmed):
            return raw_speech, False, "trimmed_empty_after_visible_anchor"
        return trimmed, True, "visible_anchor_prefix_trim"

    @staticmethod
    def _is_battery_suffix_compatible(prefix: str, anchor_label: str) -> bool:
        prefix_norm = A11yAdbClient.normalize_for_comparison(prefix)
        anchor_norm = A11yAdbClient.normalize_for_comparison(anchor_label)
        if not prefix_norm or not anchor_norm:
            return False
        return prefix_norm == anchor_norm or prefix_norm in anchor_norm or anchor_norm in prefix_norm

    @staticmethod
    def _try_trim_battery_suffix_noise(speech: str, anchor_labels: list[str]) -> tuple[str, bool, str]:
        raw_speech = str(speech or "")
        if not raw_speech.strip():
            return raw_speech, False, "empty_speech"

        match = re.search(r"\s+battery\s+\d{1,3}\s*(?:per\s+cent|percent)\.?\s*$", raw_speech, flags=re.IGNORECASE)
        if not match:
            return raw_speech, False, "battery_suffix_not_found"

        prefix = raw_speech[: match.start()].rstrip(" \t,.;:-")
        if not prefix:
            return raw_speech, False, "battery_only_announcement"

        for anchor_label in anchor_labels:
            if A11yAdbClient._is_battery_suffix_compatible(prefix, anchor_label):
                return prefix, True, "battery_suffix"
        return raw_speech, False, "battery_prefix_anchor_mismatch"

    def get_partial_announcements(
        self,
        dev: Any = None,
        wait_seconds: float = 2.0,
        only_new: bool = True,
    ) -> list[str]:
        """수집된 raw 발화 조각 리스트를 반환합니다."""
        if not self.check_talkback_status(dev=dev):
            print("TalkBack이 꺼져 있어 음성을 수집할 수 없습니다")
            self.last_announcements = []
            self.last_merged_announcement = ""
            return []

        start_time = time.monotonic()
        announcements: list[str] = []
        seen: set[str] = set()

        with self._state_lock:
            last_log_marker = self._last_log_marker

        newest_log_marker = last_log_marker

        while True:
            logs = self._run(["logcat", "-v", "time", "-d", *LOGCAT_FILTER_SPECS], dev=dev)
            for line_index, line in enumerate(logs.splitlines(), start=1):
                parsed_time = self._parse_logcat_time(line)
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

        with self._state_lock:
            self._last_log_marker = newest_log_marker

        self.last_announcements = announcements
        self.last_merged_announcement = self._merge_announcements(announcements)
        return announcements

    def _collect_focus_node_with_compat(
        self,
        dev: Any,
        focus_wait: float,
        allow_get_focus_fallback_dump: bool,
        get_focus_mode: str,
    ) -> dict[str, Any]:
        try:
            try:
                return self.get_focus(
                    dev=dev,
                    wait_seconds=focus_wait,
                    allow_fallback_dump=allow_get_focus_fallback_dump,
                    mode=get_focus_mode,
                )
            except TypeError:
                try:
                    return self.get_focus(
                        dev=dev,
                        wait_seconds=focus_wait,
                        allow_fallback_dump=allow_get_focus_fallback_dump,
                    )
                except TypeError:
                    return self.get_focus(
                        dev=dev,
                        wait_seconds=focus_wait,
                    )
        except Exception:
            return {}

    def _populate_focus_fields_from_node(self, step: dict[str, Any], safe_focus_node: dict[str, Any]) -> None:
        populate_focus_fields_from_node(step=step, safe_focus_node=safe_focus_node, normalize_bounds=self._normalize_bounds)

    def _populate_get_focus_trace_fields(self, step: dict[str, Any], trace: dict[str, Any]) -> None:
        populate_get_focus_trace_fields(step=step, trace=trace)

    def _resolve_step_dump_tree(
        self,
        step: dict[str, Any],
        trace: dict[str, Any],
        safe_focus_node: dict[str, Any],
        allow_step_dump: bool,
        dev: Any,
    ) -> None:
        fallback_nodes = trace.get("fallback_dump_nodes")
        step["get_focus_fallback_dump_elapsed_sec"] = round(float(trace.get("fallback_dump_elapsed_sec", 0.0) or 0.0), 3)
        if isinstance(fallback_nodes, list) and fallback_nodes:
            step["dump_tree_nodes"] = self._json_safe_value(fallback_nodes)
            step["step_dump_tree_elapsed_sec"] = 0.0
            step["step_dump_tree_used"] = False
            step["step_dump_tree_reason"] = "fallback_nodes_reused"
            step["dump_tree_elapsed_sec"] = step["step_dump_tree_elapsed_sec"]
            return
        focus_payload_sufficient = self._is_meaningful_focus_node(safe_focus_node)
        if focus_payload_sufficient:
            step["step_dump_tree_elapsed_sec"] = 0.0
            step["step_dump_tree_used"] = False
            step["step_dump_tree_reason"] = "focus_payload_sufficient"
            step["dump_tree_elapsed_sec"] = step["step_dump_tree_elapsed_sec"]
            return
        if not allow_step_dump:
            step["step_dump_tree_elapsed_sec"] = 0.0
            step["step_dump_tree_used"] = False
            step["step_dump_tree_reason"] = "fast_path_skip_step_dump"
            step["dump_tree_elapsed_sec"] = step["step_dump_tree_elapsed_sec"]
            return
        dump_started = time.monotonic()
        step["step_dump_tree_used"] = True
        step["step_dump_tree_reason"] = "fallback_nodes_missing"
        try:
            dump_tree_nodes = self.dump_tree(dev=dev)
            step["dump_tree_nodes"] = self._json_safe_value(dump_tree_nodes)
        except Exception:
            pass
        step["step_dump_tree_elapsed_sec"] = round(time.monotonic() - dump_started, 3)
        step["dump_tree_elapsed_sec"] = step["step_dump_tree_elapsed_sec"]

    def collect_focus_step(
        self,
        dev: Any = None,
        step_index: int = 0,
        move: bool = True,
        direction: str = "next",
        wait_seconds: float = 1.5,
        announcement_wait_seconds: float | None = None,
        announcement_idle_wait_seconds: float = 0.0,
        announcement_max_extra_wait_seconds: float = 0.0,
        focus_wait_seconds: float | None = None,
        allow_get_focus_fallback_dump: bool = True,
        allow_step_dump: bool = True,
        get_focus_mode: str = "normal",
    ) -> dict[str, Any]:
        """포커스 1 step 이동/수집 결과를 엑셀 row 친화적인 dict로 반환합니다."""
        step_started = time.monotonic()
        baseline_announcement = str(self.last_merged_announcement or "").strip()
        baseline_announcement_ts = round(step_started, 3)
        baseline_norm = self.normalize_for_comparison(baseline_announcement)
        self._debug_print(
            f"[ANN][baseline] text='{baseline_announcement}' ts={baseline_announcement_ts:.3f}"
        )
        step: dict[str, Any] = create_base_step_row(step_index=step_index)

        if move:
            move_started = time.monotonic()
            try:
                if str(direction).strip().lower() == "next":
                    step["move_result"] = self.move_focus_smart(dev=dev, direction=direction)
                else:
                    step["move_result"] = self.move_focus(dev=dev, direction=direction)
            except Exception as exc:  # defensive
                step["move_result"] = f"error: {exc}"
            step["move_elapsed_sec"] = round(time.monotonic() - move_started, 3)
        else:
            step["move_elapsed_sec"] = 0.0
        smart_nav_result = self.last_smart_nav_result if isinstance(self.last_smart_nav_result, dict) else {}
        step.update(
            extract_smart_nav_row_fields(
                smart_nav_result=smart_nav_result,
                last_smart_nav_terminal=self.last_smart_nav_terminal,
            )
        )
        smart_success = bool(step.get("smart_nav_success", False))
        if smart_success and move and str(direction).strip().lower() == "next":
            step["post_move_verdict_source"] = "smart_nav_result"
        step["t_after_move"] = round(time.monotonic() - step_started, 3)

        ann_wait = wait_seconds if announcement_wait_seconds is None else announcement_wait_seconds

        ann_started = time.monotonic()
        selected_merged_announcement = ""
        raw_snapshot_announcement = ""
        trim_considered = False
        trim_applied = False
        trim_before = ""
        trim_after = ""
        trim_reason = ""
        trim_reject_reason = ""
        selected_reason = "result_row_snapshot"
        selected_source = "result_row_snapshot"
        try:
            partial_announcements = self.get_partial_announcements(
                dev=dev,
                wait_seconds=ann_wait,
                only_new=True,
            )
            stable_announcements = list(partial_announcements)
            stable_merged = self._merge_announcements(stable_announcements)
            stable_norm = self.normalize_for_comparison(stable_merged)
            newest_changed = bool(stable_norm and stable_norm != baseline_norm)
            self._debug_print(
                f"[ANN][poll] candidate='{stable_merged}' changed={newest_changed}"
            )
            stability_extra_wait = 0.0
            idle_wait = float(announcement_idle_wait_seconds or 0.0)
            max_extra_wait = float(announcement_max_extra_wait_seconds or 0.0)
            if idle_wait > 0 and max_extra_wait > 0:
                self._debug_print(
                    f"[ANN][stability] mode='step' idle_wait={idle_wait:.2f} max_extra={max_extra_wait:.2f}"
                )
                stability_started = time.monotonic()
                stable_seen = {msg for msg in stable_announcements if isinstance(msg, str) and msg.strip()}
                stable_last_change_at = stability_started if newest_changed else 0.0
                reason = "max_extra_wait"
                while True:
                    elapsed_extra = time.monotonic() - stability_started
                    if elapsed_extra >= max_extra_wait:
                        reason = "max_extra_wait"
                        break
                    remaining = max(max_extra_wait - elapsed_extra, 0.0)
                    poll_wait_seconds = min(0.15, remaining)
                    if poll_wait_seconds <= 0:
                        reason = "max_extra_wait"
                        break
                    delta_announcements = self.get_partial_announcements(
                        dev=dev,
                        wait_seconds=poll_wait_seconds,
                        only_new=True,
                    )
                    changed = False
                    if isinstance(delta_announcements, list):
                        for message in delta_announcements:
                            if not isinstance(message, str):
                                continue
                            normalized = message.strip()
                            if not normalized or normalized in stable_seen:
                                continue
                            stable_seen.add(normalized)
                            stable_announcements.append(message)
                            changed = True
                    now = time.monotonic()
                    if changed:
                        stable_merged = self._merge_announcements(stable_announcements)
                        stable_norm = self.normalize_for_comparison(stable_merged)
                        newest_changed = bool(stable_norm and stable_norm != baseline_norm)
                        if newest_changed:
                            stable_last_change_at = now
                        self._debug_print(
                            f"[ANN][poll] candidate='{stable_merged}' changed={newest_changed}"
                        )
                    if newest_changed and stable_last_change_at > 0 and (now - stable_last_change_at >= idle_wait):
                        reason = "idle_stable"
                        break
                stability_extra_wait = round(time.monotonic() - stability_started, 3)
                partial_announcements = stable_announcements
                self.last_announcements = list(stable_announcements)
                self.last_merged_announcement = self._merge_announcements(stable_announcements)
                self._debug_print(
                    f"[ANN][stable] selected='{self.last_merged_announcement}' reason='{reason}' elapsed={stability_extra_wait:.2f}"
                )
            raw_snapshot_announcement = self._merge_announcements(partial_announcements)
            selected_merged_announcement = raw_snapshot_announcement
            selected_norm = self.normalize_for_comparison(selected_merged_announcement)
            trim_considered = True
            if (
                baseline_announcement
                and baseline_norm
                and selected_norm
                and selected_norm != baseline_norm
                and len(baseline_norm) >= 8
                and selected_norm.startswith(baseline_norm)
            ):
                trimmed_merged = selected_merged_announcement[len(baseline_announcement) :].lstrip(" \t,.;:-")
                trimmed_norm = self.normalize_for_comparison(trimmed_merged)
                if trimmed_norm:
                    trim_applied = True
                    trim_before = selected_merged_announcement
                    selected_merged_announcement = trimmed_merged
                    trim_after = selected_merged_announcement
                    trim_reason = "baseline_prefix_trim"
                    trim_reject_reason = ""
                    selected_reason = "baseline_prefix_trim"
                    selected_source = "trimmed_candidate"
                else:
                    trim_reject_reason = "baseline_trimmed_empty"
            elif baseline_announcement:
                trim_reject_reason = "baseline_rule_not_matched"
            else:
                trim_reject_reason = "baseline_empty_visible_anchor_pending"
            self._debug_print(
                f"[ANN][trim] considered={str(trim_considered).lower()} applied={str(trim_applied).lower()} "
                f"before='{trim_before or selected_merged_announcement}' after='{trim_after or selected_merged_announcement}' "
                f"reject_reason='{trim_reject_reason}' reason='{trim_reason or 'baseline_trim_not_applied'}'"
            )
            used_snapshot = self.normalize_for_comparison(selected_merged_announcement) == self.normalize_for_comparison(raw_snapshot_announcement)
            self._debug_print(
                f"[ANN][select] previous='{baseline_announcement}' current='{raw_snapshot_announcement}' "
                f"final='{selected_merged_announcement}' used_snapshot={str(used_snapshot).lower()} "
                f"used_trimmed_candidate={str(not used_snapshot).lower()}"
            )
            step["partial_announcements"] = self._json_safe_value(partial_announcements)
            step["announcement_extra_wait_sec"] = stability_extra_wait
        except Exception:
            partial_announcements = []
            selected_merged_announcement = ""
            raw_snapshot_announcement = ""
        step["announcement_elapsed_sec"] = round(time.monotonic() - ann_started, 3)
        step["announcement_count"] = len(partial_announcements)
        step["announcement_window_sec"] = round(float(ann_wait) + float(step.get("announcement_extra_wait_sec", 0.0) or 0.0), 3)
        step["t_after_ann"] = round(time.monotonic() - step_started, 3)

        # 발화 수집 기준(step)을 단일화하기 위해 get_announcements 재호출을 제거합니다.
        merged_announcement = str(selected_merged_announcement or self._merge_announcements(partial_announcements))
        step["merged_announcement"] = merged_announcement
        step["normalized_announcement"] = self.normalize_for_comparison(merged_announcement)
        step["trim_considered"] = bool(trim_considered)
        step["trim_applied"] = bool(trim_applied)
        step["trim_before"] = trim_before or raw_snapshot_announcement
        step["trim_after"] = trim_after or merged_announcement
        step["trim_reason"] = trim_reason
        step["trim_reject_reason"] = trim_reject_reason
        step["announcement_stable_reason"] = selected_reason if merged_announcement else "empty"
        step["announcement_stable_source"] = selected_source if merged_announcement else "none"

        saved_last_announcements = list(self.last_announcements)
        saved_last_merged = self.last_merged_announcement

        focus_wait = wait_seconds if focus_wait_seconds is None else focus_wait_seconds
        focus_started = time.monotonic()
        focus_node = self._collect_focus_node_with_compat(
            dev=dev,
            focus_wait=focus_wait,
            allow_get_focus_fallback_dump=allow_get_focus_fallback_dump,
            get_focus_mode=get_focus_mode,
        )
        step["get_focus_elapsed_sec"] = round(time.monotonic() - focus_started, 3)
        step["t_after_get_focus"] = round(time.monotonic() - step_started, 3)
        safe_focus_node = self._json_safe_value(focus_node) if isinstance(focus_node, dict) else {}
        self._populate_focus_fields_from_node(step=step, safe_focus_node=safe_focus_node)

        visible_label = self.extract_visible_label_from_focus(safe_focus_node)
        if not visible_label and isinstance(safe_focus_node, dict):
            for fallback_key in (
                "contentDescription",
                "content_desc",
                "content_description",
                "accessibilityLabel",
                "label",
                "talkback",
            ):
                fallback_value = safe_focus_node.get(fallback_key)
                if isinstance(fallback_value, str) and fallback_value.strip():
                    visible_label = fallback_value.strip()
                    break
        step["visible_label"] = visible_label
        step["normalized_visible_label"] = self.normalize_for_comparison(visible_label)

        snapshot_contaminated, snapshot_reason = self._is_contaminated_announcement_candidate(
            raw_snapshot_announcement,
            visible_label,
        )
        if step["merged_announcement"] and visible_label:
            trimmed_by_visible, visible_trim_applied, visible_trim_reason = self._try_trim_prefix_by_visible_anchor(
                step["merged_announcement"],
                visible_label,
            )
            if visible_trim_applied:
                trim_before_value = str(step.get("merged_announcement", "") or "")
                step["merged_announcement"] = trimmed_by_visible
                step["normalized_announcement"] = self.normalize_for_comparison(trimmed_by_visible)
                step["trim_considered"] = True
                step["trim_applied"] = True
                step["trim_before"] = trim_before_value
                step["trim_after"] = trimmed_by_visible
                step["trim_reason"] = "visible_anchor_prefix_trim"
                step["trim_reject_reason"] = ""
                step["announcement_stable_reason"] = "visible_anchor_prefix_trim"
                step["announcement_stable_source"] = "trimmed_candidate"
            elif not step.get("trim_reason"):
                step["trim_considered"] = True
                step["trim_reject_reason"] = visible_trim_reason

        used_snapshot = (
            self.normalize_for_comparison(str(step.get("merged_announcement", "") or ""))
            == self.normalize_for_comparison(raw_snapshot_announcement)
        )
        step["used_snapshot"] = bool(used_snapshot)
        step["snapshot_contaminated"] = bool(snapshot_contaminated)
        if snapshot_contaminated:
            step["snapshot_reason"] = snapshot_reason if not used_snapshot else "no_better_recent_poll_candidate_contaminated"
        else:
            step["snapshot_reason"] = "no_better_recent_poll_candidate" if used_snapshot else "not_used"
        self._debug_print(
            f"[ANN][trim] considered={str(step['trim_considered']).lower()} applied={str(step['trim_applied']).lower()} "
            f"before='{step['trim_before']}' after='{step['trim_after']}' reject_reason='{step['trim_reject_reason']}' "
            f"reason='{step['trim_reason'] or 'not_applied'}' strategy='visible_anchor_prefix_trim'"
        )
        self._debug_print(
            f"[ANN][select] used_snapshot={str(step['used_snapshot']).lower()} "
            f"used_trimmed_candidate={str(step['announcement_stable_source'] == 'trimmed_candidate').lower()} "
            f"snapshot_contaminated={str(step['snapshot_contaminated']).lower()} snapshot_reason='{step['snapshot_reason']}'"
        )

        trace = self.last_get_focus_trace if isinstance(self.last_get_focus_trace, dict) else {}
        self._resolve_step_dump_tree(
            step=step,
            trace=trace,
            safe_focus_node=safe_focus_node,
            allow_step_dump=allow_step_dump,
            dev=dev,
        )
        self._populate_get_focus_trace_fields(step=step, trace=trace)
        step["t_step_start"] = 0.0

        merged_announcement = str(step.get("merged_announcement", "") or "").strip()
        if not merged_announcement:
            top_level_payload_sufficient = bool(step.get("get_focus_top_level_payload_sufficient", False))
            final_payload_source = str(step.get("get_focus_final_payload_source", "") or "").strip().lower()
            if top_level_payload_sufficient and final_payload_source == "top_level":
                fallback_announcement = ""
                fallback_source = ""

                if isinstance(partial_announcements, list):
                    fallback_announcement = self._merge_announcements(partial_announcements).strip()
                    if fallback_announcement:
                        fallback_source = "partial_announcements"

                if not fallback_announcement:
                    fallback_announcement = str(saved_last_merged or "").strip()
                    if fallback_announcement:
                        fallback_source = "last_merged_announcement"

                if not fallback_announcement and isinstance(safe_focus_node, dict):
                    for source_key in ("talkbackLabel", "mergedLabel", "contentDescription", "text"):
                        candidate = str(safe_focus_node.get(source_key, "") or "").strip()
                        if candidate:
                            fallback_announcement = candidate
                            fallback_source = source_key
                            break

                if fallback_announcement:
                    step["merged_announcement"] = fallback_announcement
                    step["normalized_announcement"] = self.normalize_for_comparison(fallback_announcement)
                    step["used_snapshot"] = (
                        self.normalize_for_comparison(fallback_announcement)
                        == self.normalize_for_comparison(raw_snapshot_announcement)
                    )
                    if not step["used_snapshot"] and step.get("snapshot_reason") == "no_better_recent_poll_candidate":
                        step["snapshot_reason"] = "not_used"
                if fallback_source in {"talkbackLabel", "mergedLabel"}:
                    print(f"[ANN][fallback] source='{fallback_source}'")

        noise_trimmed, noise_trim_applied, noise_trim_reason = self._try_trim_battery_suffix_noise(
            step.get("merged_announcement", ""),
            build_noise_trim_anchor_labels(step=step, safe_focus_node=safe_focus_node),
        )
        if noise_trim_applied:
            before_value = str(step.get("merged_announcement", "") or "")
            step["merged_announcement"] = noise_trimmed
            step["normalized_announcement"] = self.normalize_for_comparison(noise_trimmed)
            step["trim_considered"] = True
            step["trim_applied"] = True
            step["trim_before"] = before_value
            step["trim_after"] = noise_trimmed
            step["trim_reason"] = noise_trim_reason
            step["trim_reject_reason"] = ""
            print(
                f"[ANN][noise_trim] reason='{noise_trim_reason}' before='{before_value}' after='{noise_trimmed}'"
            )

        step["last_announcements"] = self._json_safe_value(saved_last_announcements)
        step["last_merged_announcement"] = saved_last_merged
        prev_merged = str(self._prev_step_merged_announcement or "").strip()
        curr_merged = str(step.get("merged_announcement", "") or "").strip()
        prev_norm = self.normalize_for_comparison(prev_merged)
        curr_norm = self.normalize_for_comparison(curr_merged)
        (
            step["prev_speech_same"],
            step["prev_speech_similar"],
        ) = compute_prev_speech_flags(
            prev_norm=prev_norm,
            curr_norm=curr_norm,
        )
        self._prev_step_merged_announcement = curr_merged

        self._debug_print(
            f"[DEBUG][collect_focus_step] step={step_index} move={step['move_elapsed_sec']:.3f}s "
            f"ann={step['announcement_elapsed_sec']:.3f}s get_focus={step['get_focus_elapsed_sec']:.3f}s "
            f"get_focus_fallback_dump={step['get_focus_fallback_dump_elapsed_sec']:.3f}s "
            f"step_dump={step['step_dump_tree_elapsed_sec']:.3f}s "
            f"step_dump_used={step['step_dump_tree_used']} "
            f"step_dump_reason='{step['step_dump_tree_reason']}' "
            f"reason='{step['get_focus_empty_reason']}'"
        )
        req_id = ""
        if isinstance(smart_nav_result, dict):
            req_id = str(smart_nav_result.get("reqId", "") or "").strip()
        focus_label_for_trace = str(step.get("visible_label", "") or step.get("focus_content_description", "") or "").replace("\n", " ").strip()
        announcement_for_trace = str(step.get("merged_announcement", "") or "").replace("\n", " ").strip()
        print(
            f"[STEP][smart_next_trace] req_id='{req_id}' "
            f"last_smart_nav_result='{step.get('last_smart_nav_result', '')}' "
            f"last_smart_nav_detail='{step.get('last_smart_nav_detail', '')}' "
            f"smart_nav_requested_view_id='{step.get('smart_nav_requested_view_id', '')}' "
            f"smart_nav_resolved_view_id='{step.get('smart_nav_resolved_view_id', '')}' "
            f"smart_nav_actual_view_id='{step.get('smart_nav_actual_view_id', '')}' "
            f"post_move_verdict_source='{step.get('post_move_verdict_source', '')}' "
            f"focus_view_id='{step.get('focus_view_id', '')}' "
            f"focus_label='{focus_label_for_trace[:96]}' "
            f"announcement='{announcement_for_trace[:96]}' "
            f"focus_payload_req_id='{step.get('get_focus_req_id', '')}' "
            f"focus_payload_source='{step.get('focus_payload_source', '')}' "
            f"focus_payload_final_source='{step.get('get_focus_final_payload_source', '')}' "
            f"t_move_done={step.get('t_after_move', 0)} "
            f"t_ann_done={step.get('t_after_ann', 0)} "
            f"t_focus_done={step.get('t_after_get_focus', 0)}"
        )
        return step

    def get_announcements(
        self,
        dev: Any = None,
        wait_seconds: float = 2.0,
        only_new: bool = True,
    ) -> str:
        """수집된 발화 조각을 병합한 최신 발화 문자열을 반환합니다."""
        announcements = self.get_partial_announcements(
            dev=dev,
            wait_seconds=wait_seconds,
            only_new=only_new,
        )
        merged = self._merge_announcements(announcements)
        self.last_merged_announcement = merged
        return merged

    @staticmethod
    def _parse_logcat_time(line: str) -> tuple[int, int, int, int, int, int] | None:
        match = LOGCAT_TIME_PATTERN.match(line)
        if not match:
            return None

        timestamp = match.group(1)
        month_day, clock = timestamp.split(" ")
        month, day = (int(value) for value in month_day.split("-"))
        hour, minute, sec_millis = clock.split(":")
        second, millis = sec_millis.split(".")
        return (month, day, int(hour), int(minute), int(second), int(millis))
