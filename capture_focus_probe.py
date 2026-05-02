#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_VERSION = "1.0.0"
OUTPUT_BASE = Path("output/capture_focus_probe")
TAG = "auto"
WAIT_SECONDS = 0.3
SAVE_XML = True
SAVE_SCREENSHOT = True

current_dir = os.getcwd()
print(f"[INFO] cwd: {current_dir}")

if current_dir not in sys.path:
    sys.path.append(current_dir)

from talkback_lib import A11yAdbClient
from capture_debug_bundle import (
    log,
    ensure_dir,
    write_json,
    resolve_serial,
    get_connected_devices,
    capture_screenshot,
    capture_uiautomator_xml,
)

print("✅ talkback_lib 로드 성공")

client = A11yAdbClient()


def build_output_dir(tag: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_BASE / f"{ts}_{tag}"
    ensure_dir(out_dir)
    return out_dir


def safe_str(value: Any, max_len: int = 500) -> str:
    try:
        text = str(value)
    except Exception:
        text = repr(value)
    if len(text) > max_len:
        return text[:max_len] + "...(truncated)"
    return text


def summarize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "type": type(payload).__name__,
            "preview": safe_str(payload),
        }

    summary = {
        "keys": sorted(list(payload.keys()))[:50],
    }

    for key in [
        "success",
        "status",
        "reason",
        "message",
        "text",
        "visible_text",
        "speech_text",
        "announcement",
        "resource_id",
        "class_name",
        "bounds",
        "focused",
        "accessibility_focused",
    ]:
        if key in payload:
            summary[key] = payload.get(key)

    return summary


def try_get_focus(serial: str) -> tuple[Any, str | None]:
    try:
        payload = client.get_focus(dev=serial)
        return payload, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def try_dump_tree(serial: str) -> tuple[Any, str | None]:
    try:
        payload = client.dump_tree(dev=serial)
        return payload, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    print(f"[START] capture_focus_probe version={SCRIPT_VERSION}")

    serials = get_connected_devices()
    serial = resolve_serial("", serials)

    out_dir = build_output_dir(TAG)
    log(f"[INFO] serial={serial} out_dir='{out_dir}'")

    time.sleep(WAIT_SECONDS)

    # 1. get_focus 먼저
    focus_payload, focus_error = try_get_focus(serial)
    focus_summary = summarize_payload(focus_payload)

    write_json(out_dir / "get_focus_raw.json", focus_payload if focus_payload is not None else {"error": focus_error})
    write_json(out_dir / "get_focus_summary.json", focus_summary)

    # 2. 비교용 dump_tree도 같이 저장
    dump_payload, dump_error = try_dump_tree(serial)
    dump_summary = summarize_payload(dump_payload)

    node_count = None
    if isinstance(dump_payload, dict) and isinstance(dump_payload.get("nodes"), list):
        node_count = len(dump_payload["nodes"])
        dump_summary["node_count"] = node_count

    write_json(out_dir / "dump_tree_raw.json", dump_payload if dump_payload is not None else {"error": dump_error})
    write_json(out_dir / "dump_tree_summary.json", dump_summary)

    # 3. screenshot
    screenshot_ok = False
    screenshot_path = None
    screenshot_error = None
    if SAVE_SCREENSHOT:
        screenshot_ok, screenshot_path, screenshot_error = capture_screenshot(out_dir, serial)

    # 4. xml
    xml_ok = False
    xml_path = None
    xml_error = None
    if SAVE_XML:
        xml_ok, xml_path, xml_error = capture_uiautomator_xml(out_dir, serial)

    meta = {
        "script_version": SCRIPT_VERSION,
        "serial": serial,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(out_dir),
        "get_focus_error": focus_error,
        "get_focus_summary": focus_summary,
        "dump_tree_error": dump_error,
        "dump_tree_summary": dump_summary,
        "artifacts": {
            "screenshot_ok": screenshot_ok,
            "screenshot_path": str(screenshot_path) if screenshot_path else None,
            "screenshot_error": screenshot_error,
            "xml_ok": xml_ok,
            "xml_path": str(xml_path) if xml_path else None,
            "xml_error": xml_error,
        },
    }

    write_json(out_dir / "meta.json", meta)

    log(
        f"[DONE] get_focus_error='{focus_error or ''}' "
        f"dump_tree_error='{dump_error or ''}' node_count={node_count}"
    )
    log(f"[DONE] output='{out_dir}'")

    print("\n=== RESULT ===")
    print(f"📁 {out_dir}")
    print(f"get_focus_error: {focus_error or ''}")
    print(f"get_focus_summary: {safe_str(focus_summary, 700)}")
    print(f"dump_tree_error: {dump_error or ''}")
    print(f"dump_tree_summary: {safe_str(dump_summary, 700)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())