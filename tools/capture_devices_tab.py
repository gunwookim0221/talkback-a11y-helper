#!/usr/bin/env python3
"""Capture SmartThings Devices tab structure without running runtime traversal."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SMARTTHINGS_PACKAGE = "com.samsung.android.oneconnect"
OUTPUT_BASE = Path("output")
SCRIPT_VERSION = "0.1.0"
DEFAULT_MAX_SCROLLS = 8
WAIT_AFTER_TAB_SECONDS = 1.5
WAIT_AFTER_SCROLL_SECONDS = 1.0
DYNAMIC_TOKENS = (
    "켜짐",
    "꺼짐",
    "잠김",
    "열림",
    "감지됨",
    "온도",
    "습도",
    "배터리",
    "전력량",
    "최근 감지",
    "연결됨",
    "on",
    "off",
    "locked",
    "unlocked",
    "open",
    "closed",
    "detected",
    "temperature",
    "humidity",
    "battery",
    "power",
    "connected",
)
STATUS_SUFFIXES = (
    "움직임 감지됨",
    "물기 없음",
    "감지 안 됨",
    "진동 감지됨",
    "오프라인",
    "연결됨",
    "꺼짐",
    "켜짐",
    "잠김",
    "열림",
    "감지됨",
    "안심(외출)",
    "일시중지",
    "재생 중",
    "offline",
    "connected",
    "off",
    "on",
    "locked",
    "unlocked",
    "open",
    "closed",
    "detected",
)
BOTTOM_TAB_LABELS = ("Home", "Devices", "Life", "Routines", "Menu", "홈", "기기", "라이프", "루틴", "메뉴")
TARGET_NAMESPACE_BY_CATEGORY = {
    "연기센서": "device_smoke_sensor_plugin",
    "연기": "device_smoke_sensor_plugin",
    "smoke": "device_smoke_sensor_plugin",
    "누수센서": "device_water_leak_sensor_plugin",
    "누수": "device_water_leak_sensor_plugin",
    "water leak": "device_water_leak_sensor_plugin",
    "홈카메라": "device_home_camera_plugin",
    "home camera": "device_home_camera_plugin",
    "모션센서": "device_motion_sensor_plugin",
    "motion": "device_motion_sensor_plugin",
    "카메라": "device_camera_plugin",
    "camera": "device_camera_plugin",
    "door lock": "device_door_lock_plugin",
    "도어락": "device_door_lock_plugin",
    "lock": "device_door_lock_plugin",
    "세탁기": "device_washer_plugin",
    "washer": "device_washer_plugin",
    "공기청정기": "device_air_purifier_plugin",
    "air purifier": "device_air_purifier_plugin",
    "습도센서": "device_humidity_sensor_plugin",
    "humidity sensor": "device_humidity_sensor_plugin",
    "tv": "device_tv_plugin",
    "온습도센서": "device_temperature_humidity_sensor_plugin",
    "온습도 센서": "device_temperature_humidity_sensor_plugin",
    "temperature humidity": "device_temperature_humidity_sensor_plugin",
    "audio": "device_audio_plugin",
    "오디오": "device_audio_plugin",
}


current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from talkback_lib import A11yAdbClient  # noqa: E402


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_adb(serial: str | None, *args: str, timeout: float = 20.0) -> CommandResult:
    command = ["adb"]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    completed = subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        command=tuple(command),
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def get_connected_devices() -> list[str]:
    result = run_adb(None, "devices", timeout=10.0)
    devices: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        if "\tdevice" in line:
            devices.append(line.split("\t", 1)[0].strip())
    return devices


def resolve_serial(serial: str | None) -> str:
    devices = get_connected_devices()
    if serial:
        if serial not in devices:
            raise RuntimeError(f"requested serial not connected: {serial}")
        return serial
    if not devices:
        raise RuntimeError("no connected adb device")
    return devices[0]


def bounds_to_text(bounds: Any) -> str:
    if isinstance(bounds, dict):
        l = bounds.get("l", bounds.get("left", ""))
        t = bounds.get("t", bounds.get("top", ""))
        r = bounds.get("r", bounds.get("right", ""))
        b = bounds.get("b", bounds.get("bottom", ""))
        if all(str(v) != "" for v in (l, t, r, b)):
            return f"[{l},{t}][{r},{b}]"
    if isinstance(bounds, str):
        return bounds.strip()
    return ""


def parse_bounds(bounds: Any) -> tuple[int, int, int, int] | None:
    text = bounds_to_text(bounds)
    match = re.match(r"\[(\-?\d+),(\-?\d+)\]\[(\-?\d+),(\-?\d+)\]", text)
    if not match:
        return None
    left, top, right, bottom = map(int, match.groups())
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def node_label(node: dict[str, Any]) -> str:
    for key in ("mergedLabel", "talkbackLabel", "text", "contentDescription", "content-desc"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def node_resource_id(node: dict[str, Any]) -> str:
    for key in ("viewIdResourceName", "resource-id", "resourceId", "resource_id"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_dynamic_label(label: str) -> bool:
    lowered = label.lower()
    return any(token.lower() == lowered for token in DYNAMIC_TOKENS)


def strip_status_suffix(label: str) -> str:
    stable = normalize_space(label)
    for suffix in sorted(STATUS_SUFFIXES, key=len, reverse=True):
        pattern = re.compile(rf"\s+{re.escape(suffix)}$", flags=re.IGNORECASE)
        stable = pattern.sub("", stable).strip()
    return stable


def stable_label_parts(label: str) -> list[str]:
    parts = [normalize_space(part) for part in re.split(r"[,|\n]", label) if normalize_space(part)]
    stable = [strip_status_suffix(part) for part in parts if not is_dynamic_label(part)]
    stable = [part for part in stable if part and not is_dynamic_label(part)]
    stripped = strip_status_suffix(label)
    return stable or ([stripped] if stripped and not is_dynamic_label(stripped) else [])


def infer_namespace(label: str, resource_id: str = "") -> str:
    haystack = f"{label} {resource_id}".lower()
    for token, namespace in TARGET_NAMESPACE_BY_CATEGORY.items():
        if token.lower() in haystack:
            return namespace
    return ""


def flatten_helper_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], depth: int, parent_index: int | None) -> None:
        index = len(flattened)
        record = dict(node)
        record["_depth"] = depth
        record["_parent_index"] = parent_index
        flattened.append(record)
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    visit(child, depth + 1, index)

    for root_node in nodes:
        if isinstance(root_node, dict):
            visit(root_node, 0, None)
    return flattened


def read_xml_records(xml_path: Path) -> list[dict[str, Any]]:
    if not xml_path.exists():
        return []
    try:
        root = ET.fromstring(xml_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    records: list[dict[str, Any]] = []
    for element in root.iter("node"):
        attrs = dict(element.attrib)
        records.append(
            {
                "text": attrs.get("text", ""),
                "contentDescription": attrs.get("content-desc", ""),
                "className": attrs.get("class", ""),
                "viewIdResourceName": attrs.get("resource-id", ""),
                "boundsInScreen": attrs.get("bounds", ""),
                "clickable": attrs.get("clickable", ""),
                "focusable": attrs.get("focusable", ""),
                "selected": attrs.get("selected", ""),
                "enabled": attrs.get("enabled", ""),
                "_source": "xml",
            }
        )
    return records


def capture_screenshot(serial: str, out_path: Path) -> dict[str, Any]:
    remote = "/sdcard/__devices_tab_capture.png"
    shot = run_adb(serial, "shell", "screencap", "-p", remote, timeout=20.0)
    pulled = run_adb(serial, "pull", remote, str(out_path), timeout=20.0)
    return {
        "screenshot": str(out_path),
        "screencap_returncode": shot.returncode,
        "pull_returncode": pulled.returncode,
        "stderr": "\n".join(x for x in (shot.stderr, pulled.stderr) if x),
    }


def capture_uiautomator(serial: str, out_path: Path) -> dict[str, Any]:
    remote = "/sdcard/window_dump.xml"
    dumped = run_adb(serial, "shell", "uiautomator", "dump", remote, timeout=25.0)
    pulled = run_adb(serial, "pull", remote, str(out_path), timeout=20.0)
    return {
        "xml": str(out_path),
        "dump_returncode": dumped.returncode,
        "pull_returncode": pulled.returncode,
        "stdout": "\n".join(x for x in (dumped.stdout, pulled.stdout) if x),
        "stderr": "\n".join(x for x in (dumped.stderr, pulled.stderr) if x),
    }


def current_activity(serial: str) -> str:
    result = run_adb(serial, "shell", "dumpsys", "window", timeout=20.0)
    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if "mCurrentFocus" in line or "mFocusedApp" in line or "topResumedActivity" in line
    ]
    return "\n".join(lines)


def get_locale_info(serial: str) -> dict[str, str]:
    persist = run_adb(serial, "shell", "getprop", "persist.sys.locale", timeout=10.0)
    product = run_adb(serial, "shell", "getprop", "ro.product.locale", timeout=10.0)
    return {
        "persist.sys.locale": persist.stdout,
        "ro.product.locale": product.stdout,
    }


def capture_focus(client: A11yAdbClient, serial: str) -> dict[str, Any]:
    try:
        focus = client.get_focus(
            dev=serial,
            wait_seconds=1.5,
            allow_fallback_dump=True,
            mode="normal",
        )
    except TypeError:
        focus = client.get_focus(dev=serial, wait_seconds=1.5)
    except Exception as exc:
        return {"error": str(exc)}
    return focus if isinstance(focus, dict) else {"value": focus}


def capture_step(client: A11yAdbClient, serial: str, out_dir: Path, index: int, label: str) -> dict[str, Any]:
    prefix = f"{index:02d}_{label}"
    screenshot_path = out_dir / f"{prefix}_screenshot.png"
    xml_path = out_dir / f"{prefix}_uiautomator.xml"
    helper_path = out_dir / f"{prefix}_helper_dump.json"
    focus_path = out_dir / f"{prefix}_focus.json"
    activity_path = out_dir / f"{prefix}_activity.txt"

    log(f"capture step={index} label={label}")
    screenshot_meta = capture_screenshot(serial, screenshot_path)
    xml_meta = capture_uiautomator(serial, xml_path)
    helper_nodes = client.dump_tree(dev=serial)
    if not isinstance(helper_nodes, list):
        helper_nodes = []
    focus = capture_focus(client, serial)
    activity = current_activity(serial)

    write_json(helper_path, helper_nodes)
    write_json(focus_path, focus)
    write_text(activity_path, activity)

    helper_flat = flatten_helper_nodes(helper_nodes)
    xml_records = read_xml_records(xml_path)
    return {
        "index": index,
        "label": label,
        "screenshot": screenshot_meta,
        "xml": xml_meta,
        "helper_path": str(helper_path),
        "focus_path": str(focus_path),
        "activity_path": str(activity_path),
        "activity": activity,
        "helper_node_count": len(helper_flat),
        "xml_node_count": len(xml_records),
        "helper_nodes": helper_flat,
        "xml_nodes": xml_records,
    }


def enter_devices_tab(client: A11yAdbClient, serial: str) -> dict[str, Any]:
    patterns = [
        ("(?i)^devices$", "a"),
        ("^기기$", "a"),
        ("(?i).*devices.*", "a"),
        (".*기기.*", "a"),
    ]
    attempts: list[dict[str, Any]] = []
    for pattern, target_type in patterns:
        try:
            result = client.touch(dev=serial, name=pattern, type_=target_type, wait_=4)
            attempts.append({"pattern": pattern, "type": target_type, "result": result})
            if bool(result):
                time.sleep(WAIT_AFTER_TAB_SECONDS)
                return {"ok": True, "attempts": attempts}
        except Exception as exc:
            attempts.append({"pattern": pattern, "type": target_type, "error": str(exc)})
    return {"ok": False, "attempts": attempts}


def scroll_down(client: A11yAdbClient, serial: str, method: str) -> dict[str, Any]:
    if method == "adb":
        result = run_adb(serial, "shell", "input", "swipe", "540", "1780", "540", "610", "700", timeout=10.0)
        time.sleep(WAIT_AFTER_SCROLL_SECONDS)
        return {
            "method": "adb.swipe",
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stderr": result.stderr,
        }

    try:
        helper_scrolled = bool(client.scroll(dev=serial, direction="down"))
        if helper_scrolled:
            time.sleep(WAIT_AFTER_SCROLL_SECONDS)
            return {"method": "helper.scroll", "ok": True}
    except Exception as exc:
        helper_error = str(exc)
    else:
        helper_error = ""

    result = run_adb(serial, "shell", "input", "swipe", "540", "1700", "540", "600", "650", timeout=10.0)
    time.sleep(WAIT_AFTER_SCROLL_SECONDS)
    return {
        "method": "adb.swipe",
        "ok": result.returncode == 0,
        "helper_error": helper_error,
        "returncode": result.returncode,
        "stderr": result.stderr,
    }


def bottom_nav_records(step: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    all_nodes = step["helper_nodes"] + step["xml_nodes"]
    max_bottom = max((parse_bounds(n.get("boundsInScreen")) or (0, 0, 0, 0))[3] for n in all_nodes) if all_nodes else 0
    threshold = int(max_bottom * 0.78) if max_bottom else 0
    for node in all_nodes:
        label = node_label(node)
        bounds = parse_bounds(node.get("boundsInScreen"))
        if not label or not bounds or bounds[1] < threshold:
            continue
        if (
            label in BOTTOM_TAB_LABELS
            or any(tab.lower() == label.lower() for tab in BOTTOM_TAB_LABELS)
            or "탭 5개 중" in label
        ):
            records.append(summarize_node(node, source="helper" if "_source" not in node else "xml"))
    return dedupe_by_label_bounds(records)


def summarize_node(node: dict[str, Any], source: str) -> dict[str, Any]:
    label = node_label(node)
    return {
        "source": source,
        "label": label,
        "text": str(node.get("text", "") or ""),
        "contentDescription": str(node.get("contentDescription", "") or ""),
        "mergedLabel": str(node.get("mergedLabel", "") or ""),
        "talkbackLabel": str(node.get("talkbackLabel", "") or ""),
        "resource_id": node_resource_id(node),
        "class": str(node.get("className", "") or ""),
        "bounds": bounds_to_text(node.get("boundsInScreen")),
        "clickable": node.get("clickable", ""),
        "focusable": node.get("focusable", ""),
        "selected": node.get("selected", ""),
        "focused": node.get("focused", ""),
        "accessibilityFocused": node.get("accessibilityFocused", ""),
        "effectiveClickable": node.get("effectiveClickable", ""),
        "hasClickableDescendant": node.get("hasClickableDescendant", ""),
        "actionableDescendantResourceId": node.get("actionableDescendantResourceId", ""),
    }


def dedupe_by_label_bounds(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = (record.get("label", ""), record.get("bounds", ""), record.get("resource_id", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def looks_like_device_card(node: dict[str, Any]) -> bool:
    label = node_label(node)
    if not label:
        return False
    resource_id = node_resource_id(node).lower()
    class_name = str(node.get("className", "") or "").lower()
    bounds = parse_bounds(node.get("boundsInScreen"))
    if not bounds:
        return False
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    if width < 180 or height < 70:
        return False
    if "device_card" not in resource_id:
        return False
    if any(chrome.lower() == label.lower() for chrome in BOTTOM_TAB_LABELS):
        return False
    if "bottom" in resource_id or "navigation" in resource_id:
        return False
    if "imagebutton" in class_name and height < 170:
        return False
    card_id = any(token in resource_id for token in ("card", "tile", "device", "item", "group", "container", "body", "list"))
    card_class = any(token in class_name for token in ("layout", "viewgroup", "textview", "button"))
    actionish = bool(node.get("clickable") or node.get("focusable") or node.get("effectiveClickable"))
    return card_id or (card_class and actionish)


def inventory_from_step(step: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for node in step["helper_nodes"]:
        if looks_like_device_card(node):
            summary = summarize_node(node, "helper")
            parts = stable_label_parts(summary["label"])
            summary["stable_label"] = parts[0] if parts else ""
            summary["namespace_candidate"] = infer_namespace(summary["label"], summary["resource_id"])
            summary["clickable_ancestor_likely"] = bool(summary["clickable"] or summary["effectiveClickable"])
            summary["target_allowed"] = bool(summary["stable_label"]) and not is_dynamic_label(summary["stable_label"])
            if summary["stable_label"].lower() in {"test lock"}:
                summary["target_allowed"] = False
            summary["step"] = step["label"]
            records.append(summary)
    return records


def merge_inventory(step_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in step_records:
        label_key = normalize_space(record.get("stable_label") or record.get("label") or "")
        if not label_key:
            continue
        bounds = record.get("bounds", "")
        resource_id = record.get("resource_id", "")
        key = label_key.lower()
        existing = merged.get(key)
        if existing is None:
            item = dict(record)
            item["observed_steps"] = [record.get("step", "")]
            item["observed_bounds"] = [bounds] if bounds else []
            item["resource_ids"] = [resource_id] if resource_id else []
            merged[key] = item
            continue
        step_name = record.get("step", "")
        if step_name and step_name not in existing["observed_steps"]:
            existing["observed_steps"].append(step_name)
        if bounds and bounds not in existing["observed_bounds"]:
            existing["observed_bounds"].append(bounds)
        if resource_id and resource_id not in existing["resource_ids"]:
            existing["resource_ids"].append(resource_id)
        if not existing.get("namespace_candidate") and record.get("namespace_candidate"):
            existing["namespace_candidate"] = record["namespace_candidate"]
    return sorted(merged.values(), key=lambda item: (item.get("observed_steps", [""])[0], item.get("bounds", ""), item.get("stable_label", "")))


def helper_xml_comparison(steps: list[dict[str, Any]]) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    for step in steps:
        helper_labels = Counter(node_label(n) for n in step["helper_nodes"] if node_label(n))
        xml_labels = Counter(node_label(n) for n in step["xml_nodes"] if node_label(n))
        helper_ids = Counter(node_resource_id(n) for n in step["helper_nodes"] if node_resource_id(n))
        xml_ids = Counter(node_resource_id(n) for n in step["xml_nodes"] if node_resource_id(n))
        comparisons.append(
            {
                "step": step["label"],
                "helper_node_count": step["helper_node_count"],
                "xml_node_count": step["xml_node_count"],
                "helper_labels_top": [label for label, _ in helper_labels.most_common(20)],
                "xml_labels_top": [label for label, _ in xml_labels.most_common(20)],
                "helper_resource_ids_top": [rid for rid, _ in helper_ids.most_common(20)],
                "xml_resource_ids_top": [rid for rid, _ in xml_ids.most_common(20)],
            }
        )
    return {"steps": comparisons}


def build_summary_text(
    *,
    serial: str,
    locale_info: dict[str, str],
    out_dir: Path,
    devices_entry: dict[str, Any],
    steps: list[dict[str, Any]],
    scroll_results: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"script_version: {SCRIPT_VERSION}")
    lines.append(f"serial: {serial}")
    lines.append(f"persist.sys.locale: {locale_info.get('persist.sys.locale', '')}")
    lines.append(f"ro.product.locale: {locale_info.get('ro.product.locale', '')}")
    lines.append(f"capture_dir: {out_dir.resolve()}")
    lines.append(f"devices_tab_entry_ok: {devices_entry.get('ok')}")
    lines.append("")
    lines.append("== activity ==")
    for step in steps:
        lines.append(f"[{step['label']}] {step.get('activity', '')}")
    lines.append("")
    lines.append("== bottom nav observed ==")
    for record in bottom_nav_records(steps[0]) if steps else []:
        lines.append(
            f"- {record['label']} id={record['resource_id']} selected={record['selected']} "
            f"clickable={record['clickable']} focusable={record['focusable']} bounds={record['bounds']}"
        )
    lines.append("")
    lines.append("== scroll results ==")
    for result in scroll_results:
        lines.append(f"- after {result.get('from_step')}: method={result.get('method')} ok={result.get('ok')}")
    lines.append("")
    lines.append("== observed device/plugin inventory ==")
    for item in inventory:
        lines.append(
            f"- label={item.get('label', '')} | stable={item.get('stable_label', '')} | "
            f"id={','.join(item.get('resource_ids', []) or [item.get('resource_id', '')])} | "
            f"class={item.get('class', '')} | clickable={item.get('clickable')} | "
            f"focusable={item.get('focusable')} | effectiveClickable={item.get('effectiveClickable')} | "
            f"bounds={';'.join(item.get('observed_bounds', []) or [item.get('bounds', '')])} | "
            f"steps={','.join(item.get('observed_steps', []))} | "
            f"namespace={item.get('namespace_candidate', '')}"
        )
    lines.append("")
    lines.append("== stable target alias candidates ==")
    for item in inventory:
        stable = item.get("stable_label", "")
        if stable and item.get("target_allowed") and not is_dynamic_label(stable):
            namespace = item.get("namespace_candidate", "")
            suffix = f" -> {namespace}" if namespace else ""
            lines.append(f"- {stable}{suffix}")
    lines.append("")
    lines.append("== helper dump vs xml ==")
    lines.append("helper dump includes mergedLabel/talkbackLabel and accessibility flags, so it is closer to TalkBack target structure.")
    lines.append("UIAutomator XML is useful as an independent resource-id/class/bounds cross-check but may miss merged accessibility labels.")
    lines.append("")
    lines.append("== design notes ==")
    lines.append("- Reuse bottom-tab global navigation shape for Devices tab entry.")
    lines.append("- Prefer stable card title/category labels observed in helper dump; do not target dynamic state text.")
    lines.append("- If card text nodes are not clickable, promote to clickable/effectiveClickable ancestor or use bounds-center fallback.")
    lines.append("- Keep Devices plugin traversal separate from Life plugin aliases until card structure is validated per device detail screen.")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture SmartThings Devices tab UI structure.")
    parser.add_argument("--serial", default="", help="Optional adb serial.")
    parser.add_argument("--max-scrolls", type=int, default=DEFAULT_MAX_SCROLLS, help="Maximum down-scroll captures after initial.")
    parser.add_argument("--scroll-method", choices=["helper", "adb"], default="helper", help="Scroll primitive to use.")
    parser.add_argument("--scroll-to-top", action="store_true", help="Try to normalize the Devices list to the top before capture.")
    parser.add_argument("--stop-on-repeat", action="store_true", help="Stop early when helper labels repeat.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    serial = resolve_serial(args.serial or None)
    max_scrolls = max(0, int(args.max_scrolls))

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_BASE / f"device_tab_capture_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    client = A11yAdbClient(dev_serial=serial)
    locale_info = get_locale_info(serial)
    write_json(out_dir / "locale.json", locale_info)
    write_text(out_dir / "pre_capture_activity.txt", current_activity(serial))

    devices_entry = enter_devices_tab(client, serial)
    write_json(out_dir / "devices_tab_entry.json", devices_entry)
    if not devices_entry.get("ok"):
        log("Devices tab entry did not confirm success; capturing current screen anyway")
    if args.scroll_to_top:
        try:
            top_result = client.scroll_to_top(dev=serial, max_swipes=5, pause=0.6)
        except Exception as exc:
            top_result = {"ok": False, "error": str(exc)}
        write_json(out_dir / "scroll_to_top.json", top_result)
        time.sleep(WAIT_AFTER_SCROLL_SECONDS)

    steps: list[dict[str, Any]] = []
    scroll_results: list[dict[str, Any]] = []
    steps.append(capture_step(client, serial, out_dir, 0, "initial"))

    previous_signature = ""
    for scroll_index in range(1, max_scrolls + 1):
        result = scroll_down(client, serial, method=args.scroll_method)
        result["from_step"] = scroll_index - 1
        scroll_results.append(result)
        step = capture_step(client, serial, out_dir, scroll_index, f"scroll_{scroll_index}")
        steps.append(step)
        signature = "|".join(sorted({node_label(n) for n in step["helper_nodes"] if node_label(n)}))
        if args.stop_on_repeat and signature and signature == previous_signature:
            log(f"repeat signature detected at scroll={scroll_index}; stopping")
            break
        previous_signature = signature
        if not result.get("ok"):
            log(f"scroll returned not ok at scroll={scroll_index}; stopping")
            break

    all_step_records: list[dict[str, Any]] = []
    for step in steps:
        all_step_records.extend(inventory_from_step(step))
    inventory = merge_inventory(all_step_records)

    machine_summary = {
        "script_version": SCRIPT_VERSION,
        "serial": serial,
        "locale": locale_info,
        "capture_dir": str(out_dir.resolve()),
        "devices_tab_entry": devices_entry,
        "scroll_results": scroll_results,
        "bottom_nav": bottom_nav_records(steps[0]) if steps else [],
        "inventory": inventory,
        "helper_xml_comparison": helper_xml_comparison(steps),
    }
    write_json(out_dir / "summary.json", machine_summary)
    write_text(
        out_dir / "summary.txt",
        build_summary_text(
            serial=serial,
            locale_info=locale_info,
            out_dir=out_dir,
            devices_entry=devices_entry,
            steps=steps,
            scroll_results=scroll_results,
            inventory=inventory,
        ),
    )

    log(f"capture complete: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
