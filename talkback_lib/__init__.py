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
from talkback_lib import announcement as announcement_reader
from talkback_lib import focus_reader
from talkback_lib.utils import (
    json_safe_value,
    normalize_bounds,
    normalize_for_comparison,
    parse_bottom_from_bounds,
    parse_bounds_tuple,
    safe_parse_json_payload,
)


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
        self.log_level = LOG_LEVEL if LOG_LEVEL in LOG_LEVEL_ORDER else "NORMAL"
        self._adb_device = AdbDevice(
            adb_path=self.adb_path,
            resolve_serial=self._resolve_serial,
        )
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
        return self._adb_device._run_adb_command(args, dev=dev, timeout=timeout)

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
        return focus_reader.parse_json_payload(payload=payload, label=label)

    def _read_log_result(
        self,
        dev: Any,
        prefix: str,
        req_id: str,
        wait_seconds: float = 2.0,
        poll_interval_sec: float = 0.25,
    ) -> dict[str, Any]:
        start = time.monotonic()
        interval = max(0.05, poll_interval_sec)
        while time.monotonic() - start < wait_seconds:
            logs = self._run(["logcat", "-d", *LOGCAT_FILTER_SPECS], dev=dev)
            payloads = self._extract_all_payloads(logs, prefix)
            for payload in reversed(payloads):
                parsed = self._parse_json_payload(payload, prefix)
                if parsed.get("reqId") == req_id:
                    return parsed
            elapsed = time.monotonic() - start
            remaining = wait_seconds - elapsed
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
        return {"success": False, "reason": f"{prefix} 로그를 찾지 못했습니다."}

    @staticmethod
    def _extract_all_payloads(log_text: str, prefix: str) -> list[str]:
        pattern = re.compile(rf"{re.escape(prefix)}\s+(.*)$")
        payloads: list[str] = []
        for line in log_text.splitlines():
            m = pattern.search(line)
            if m:
                payloads.append(m.group(1).strip())
        return payloads

    @staticmethod
    def _extract_req_payloads(log_text: str, prefix: str, req_id: str) -> list[str]:
        pattern = re.compile(rf"{re.escape(prefix)}\s+{re.escape(req_id)}\s+(.*)$")
        payloads: list[str] = []
        for line in log_text.splitlines():
            m = pattern.search(line)
            if m:
                payloads.append(m.group(1).strip())
        return payloads

    @staticmethod
    def _has_req_marker(log_text: str, prefix: str, req_id: str) -> bool:
        marker = f"{prefix} {req_id}"
        return any(marker in line for line in log_text.splitlines())

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
            logs = self._run(["logcat", "-v", "raw", "-d", *LOGCAT_FILTER_SPECS], dev=dev)
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
        return focus_reader.normalize_focus_bounds(node)

    @staticmethod
    def _parse_bottom_from_bounds(bounds: str) -> int:
        return parse_bottom_from_bounds(bounds)

    @staticmethod
    def _parse_bounds_tuple(bounds: str) -> tuple[int, int, int, int] | None:
        return focus_reader.parse_focus_bounds_tuple(bounds)

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
            result = self._read_log_result(dev, "TARGET_ACTION_RESULT", req_id)
            self.last_target_action_result = result if isinstance(result, dict) else {"success": False, "reason": "unknown"}
            if bool(result.get("success")):
                self._wait_for_speech_if_needed(dev)
                return True
            time.sleep(0.5)
        self.last_target_action_result = {"success": False, "reason": "timeout"}
        return False

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
    ) -> bool:
        if not self.check_helper_status(dev=dev):
            return False
        self.last_announcements = []
        self.last_merged_announcement = ""
        deadline = time.monotonic() + wait_
        normalized_type = str(type_).strip().lower()
        ci_name = name if normalized_type in {"r", "resourceid"} else self._normalize_case_insensitive_pattern(name)
        while time.monotonic() <= deadline:
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
            result = self._read_log_result(dev, "TARGET_ACTION_RESULT", req_id)
            if isinstance(result, dict) and result.get("reqId") == req_id:
                # success=false인 경우에도 helper의 원본 payload를 보존한다.
                self.last_target_action_result = result
                return bool(result.get("success"))
            time.sleep(0.5)
        self.last_target_action_result = {"success": False, "reason": "timeout"}
        return False

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

    def get_focus(
        self,
        dev: Any = None,
        wait_seconds: float = 2.0,
        allow_fallback_dump: bool = True,
        mode: str = "normal",
    ) -> dict[str, Any]:
        return focus_reader.get_focus(
            client=self,
            dev=dev,
            wait_seconds=wait_seconds,
            allow_fallback_dump=allow_fallback_dump,
            mode=mode,
        )

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
        return focus_reader.is_meaningful_focus_node(node)

    @staticmethod
    def _find_focused_node_in_tree(nodes: Any) -> dict[str, Any]:
        return focus_reader.find_focused_node_in_tree(nodes)

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

    def move_focus_smart(self, dev: Any = None, direction: str = "next") -> str:
        direction_token = str(direction).strip().lower()
        if direction_token != "next":
            return STATUS_MOVED if self.move_focus(dev=dev, direction=direction_token) else STATUS_FAILED

        if not (self._has_recent_helper_ok(dev=dev) or self.check_helper_status(dev=dev)):
            return STATUS_FAILED

        self.last_announcements = []
        self.last_merged_announcement = ""
        # Keep previous logcat history for SMART_NEXT analysis continuity.
        # self.clear_logcat(dev=dev)
        req_id = str(uuid.uuid4())[:8]
        result = self._helper_bridge._request_smart_next(dev=dev, req_id=req_id)
        self.last_smart_nav_result = result
        normalized, terminal, _, _ = self._helper_bridge.normalize_smart_next_status(result)
        self.last_smart_nav_terminal = terminal
        return normalized

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
        return announcement_reader.merge_announcements(items)

    @staticmethod
    def _is_meaningful_prefix(prefix: str) -> bool:
        return announcement_reader.is_meaningful_prefix(A11yAdbClient, prefix)

    @staticmethod
    def _find_visible_anchor_prefix(speech: str, visible_label: str) -> tuple[str, str]:
        return announcement_reader.find_visible_anchor_prefix(A11yAdbClient, speech, visible_label)

    @staticmethod
    def _is_contaminated_announcement_candidate(speech: str, visible_label: str) -> tuple[bool, str]:
        return announcement_reader.is_contaminated_announcement_candidate(A11yAdbClient, speech, visible_label)

    @staticmethod
    def _try_trim_prefix_by_visible_anchor(speech: str, visible_label: str) -> tuple[str, bool, str]:
        return announcement_reader.try_trim_prefix_by_visible_anchor(A11yAdbClient, speech, visible_label)

    def get_partial_announcements(
        self,
        dev: Any = None,
        wait_seconds: float = 2.0,
        only_new: bool = True,
    ) -> list[str]:
        return announcement_reader.get_partial_announcements(
            client=self,
            dev=dev,
            wait_seconds=wait_seconds,
            only_new=only_new,
        )

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
        step: dict[str, Any] = {
            "step_index": step_index,
            "move_result": None,
            "last_smart_nav_result": "",
            "last_smart_nav_detail": "",
            "last_smart_nav_terminal": False,
            "focus_node": {},
            "focus_text": "",
            "focus_content_description": "",
            "visible_label": "",
            "normalized_visible_label": "",
            "partial_announcements": [],
            "merged_announcement": "",
            "normalized_announcement": "",
            "dump_tree_nodes": [],
            "focus_view_id": "",
            "focus_bounds": "",
            "last_announcements": [],
            "last_merged_announcement": "",
            "get_focus_fallback_dump_elapsed_sec": 0.0,
            "step_dump_tree_elapsed_sec": 0.0,
            "step_dump_tree_used": False,
            "step_dump_tree_reason": "",
            "t_step_start": 0.0,
            "t_after_move": 0.0,
            "t_after_ann": 0.0,
            "t_after_get_focus": 0.0,
            "announcement_count": 0,
            "announcement_window_sec": 0.0,
            "announcement_extra_wait_sec": 0.0,
            "prev_speech_same": False,
            "prev_speech_similar": False,
            "focus_payload_source": "none",
            "get_focus_response_success": False,
            "get_focus_top_level_success_false": False,
            "get_focus_success_false_top_level_dump_attempted": False,
            "get_focus_success_false_top_level_dump_found": False,
            "get_focus_success_false_top_level_dump_skipped": False,
            "get_focus_dump_skip_reason": "",
            "get_focus_top_level_signature": "",
            "get_focus_top_level_payload_sufficient": False,
            "get_focus_final_payload_source": "none",
            "get_focus_final_focus_reason": "",
            "get_focus_dump_replace_reason": "",
            "trim_considered": False,
            "trim_applied": False,
            "trim_before": "",
            "trim_after": "",
            "trim_reason": "",
            "trim_reject_reason": "",
            "announcement_stable_reason": "",
            "announcement_stable_source": "",
            "snapshot_reason": "",
            "used_snapshot": False,
            "snapshot_contaminated": False,
        }

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
        step["last_smart_nav_result"] = str(smart_nav_result.get("status", "") or "").strip().lower()
        step["last_smart_nav_detail"] = str(smart_nav_result.get("detail", "") or "").strip().lower()
        step["last_smart_nav_terminal"] = bool(self.last_smart_nav_terminal)
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
        try:
            try:
                focus_node = self.get_focus(
                    dev=dev,
                    wait_seconds=focus_wait,
                    allow_fallback_dump=allow_get_focus_fallback_dump,
                    mode=get_focus_mode,
                )
            except TypeError:
                try:
                    focus_node = self.get_focus(
                        dev=dev,
                        wait_seconds=focus_wait,
                        allow_fallback_dump=allow_get_focus_fallback_dump,
                    )
                except TypeError:
                    focus_node = self.get_focus(
                        dev=dev,
                        wait_seconds=focus_wait,
                    )
        except Exception:
            focus_node = {}
        step["get_focus_elapsed_sec"] = round(time.monotonic() - focus_started, 3)
        step["t_after_get_focus"] = round(time.monotonic() - step_started, 3)
        safe_focus_node = self._json_safe_value(focus_node) if isinstance(focus_node, dict) else {}
        step["focus_node"] = safe_focus_node
        step["focus_text"] = safe_focus_node.get("text", "") if isinstance(safe_focus_node, dict) else ""
        step["focus_content_description"] = safe_focus_node.get("contentDescription", "") if isinstance(safe_focus_node, dict) else ""
        step["focus_view_id"] = safe_focus_node.get("viewIdResourceName", "") if isinstance(safe_focus_node, dict) else ""
        step["focus_bounds"] = self._normalize_bounds(safe_focus_node) if isinstance(safe_focus_node, dict) else ""

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
        fallback_nodes = trace.get("fallback_dump_nodes")
        step["get_focus_fallback_dump_elapsed_sec"] = round(float(trace.get("fallback_dump_elapsed_sec", 0.0) or 0.0), 3)
        if isinstance(fallback_nodes, list) and fallback_nodes:
            step["dump_tree_nodes"] = self._json_safe_value(fallback_nodes)
            step["step_dump_tree_elapsed_sec"] = 0.0
            step["step_dump_tree_used"] = False
            step["step_dump_tree_reason"] = "fallback_nodes_reused"
            step["dump_tree_elapsed_sec"] = step["step_dump_tree_elapsed_sec"]
        else:
            focus_payload_sufficient = self._is_meaningful_focus_node(safe_focus_node)
            if focus_payload_sufficient:
                step["step_dump_tree_elapsed_sec"] = 0.0
                step["step_dump_tree_used"] = False
                step["step_dump_tree_reason"] = "focus_payload_sufficient"
                step["dump_tree_elapsed_sec"] = step["step_dump_tree_elapsed_sec"]
            elif not allow_step_dump:
                step["step_dump_tree_elapsed_sec"] = 0.0
                step["step_dump_tree_used"] = False
                step["step_dump_tree_reason"] = "fast_path_skip_step_dump"
                step["dump_tree_elapsed_sec"] = step["step_dump_tree_elapsed_sec"]
            else:
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

        step["get_focus_empty_reason"] = str(trace.get("empty_reason", "") or "")
        step["get_focus_fallback_used"] = bool(trace.get("fallback_used", False))
        step["get_focus_fallback_found"] = bool(trace.get("fallback_found", False))
        step["get_focus_req_id"] = str(trace.get("req_id", "") or "")
        step["get_focus_total_elapsed_sec"] = round(float(trace.get("total_elapsed_sec", 0.0) or 0.0), 3)
        step["focus_payload_source"] = str(trace.get("focus_payload_source", "none") or "none")
        step["get_focus_response_success"] = bool(trace.get("response_success", False))
        step["get_focus_top_level_success_false"] = bool(trace.get("accepted_with_success_false", False))
        step["get_focus_success_false_top_level_dump_attempted"] = bool(
            trace.get("success_false_top_level_dump_attempted", False)
        )
        step["get_focus_success_false_top_level_dump_found"] = bool(
            trace.get("success_false_top_level_dump_found", False)
        )
        step["get_focus_success_false_top_level_dump_skipped"] = bool(
            trace.get("success_false_top_level_dump_skipped", False)
        )
        step["get_focus_dump_skip_reason"] = str(trace.get("dump_skip_reason", "") or "")
        step["get_focus_top_level_signature"] = str(trace.get("top_level_signature", "") or "")
        step["get_focus_top_level_payload_sufficient"] = bool(trace.get("top_level_payload_sufficient", False))
        step["get_focus_final_payload_source"] = str(trace.get("final_payload_source", "none") or "none")
        step["get_focus_final_focus_reason"] = str(trace.get("final_focus_reason", "") or "")
        step["get_focus_dump_replace_reason"] = str(trace.get("dump_replace_reason", "") or "")
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

        step["last_announcements"] = self._json_safe_value(saved_last_announcements)
        step["last_merged_announcement"] = saved_last_merged
        prev_merged = str(self._prev_step_merged_announcement or "").strip()
        curr_merged = str(step.get("merged_announcement", "") or "").strip()
        prev_norm = self.normalize_for_comparison(prev_merged)
        curr_norm = self.normalize_for_comparison(curr_merged)
        step["prev_speech_same"] = bool(prev_norm and curr_norm and prev_norm == curr_norm)
        step["prev_speech_similar"] = bool(
            prev_norm and curr_norm and prev_norm != curr_norm and (prev_norm in curr_norm or curr_norm in prev_norm)
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
        return step

    def get_announcements(
        self,
        dev: Any = None,
        wait_seconds: float = 2.0,
        only_new: bool = True,
    ) -> str:
        return announcement_reader.get_announcements(
            client=self,
            dev=dev,
            wait_seconds=wait_seconds,
            only_new=only_new,
        )

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
