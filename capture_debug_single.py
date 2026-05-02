#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SCRIPT_VERSION = "1.5.1"

OUTPUT_BASE = Path("output/capture_single")
WAIT_SECONDS_BEFORE_CAPTURE = 0.3
WAIT_SECONDS_AFTER_FOCUS = 0.6
SAVE_XML = True
TAG = "auto"

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
    summarize_nodes,
)

print("✅ talkback_lib 로드 성공")

client = A11yAdbClient()


def build_output_dir(tag: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_BASE / f"{ts}_{tag}"
    ensure_dir(out_dir)
    return out_dir


def extract_focused_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    focused = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("focused") or node.get("accessibility_focused"):
            focused.append(
                {
                    "text": node.get("text"),
                    "contentDescription": node.get("contentDescription"),
                    "resource_id": node.get("view_id_resource_name") or node.get("viewIdResourceName"),
                    "class_name": node.get("class_name") or node.get("className"),
                    "bounds": node.get("bounds"),
                    "focused": node.get("focused"),
                    "accessibility_focused": node.get("accessibility_focused"),
                    "clickable": node.get("clickable"),
                    "focusable": node.get("focusable"),
                }
            )
    return focused


def safe_str(value: Any, max_len: int = 400) -> str:
    try:
        text = str(value)
    except Exception:
        text = repr(value)
    if len(text) > max_len:
        return text[:max_len] + "...(truncated)"
    return text


def safe_str_list(value: Any, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:limit]:
        out.append(safe_str(item, 200))
    return out


def extract_nodes_from_dump_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        nodes = payload.get("nodes", [])
        return nodes if isinstance(nodes, list) else []
    if isinstance(payload, list):
        return payload
    return []


def summarize_helper_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        nodes = extract_nodes_from_dump_payload(payload)
        return {
            "type": "dict",
            "keys": sorted(list(payload.keys()))[:50],
            "success": payload.get("success"),
            "status": payload.get("status"),
            "reason": payload.get("reason"),
            "message": payload.get("message"),
            "node_count": len(nodes),
            "announcements": safe_str_list(payload.get("announcements")),
            "visible_texts": safe_str_list(payload.get("visible_texts")),
            "speech_texts": safe_str_list(payload.get("speech_texts")),
        }

    if isinstance(payload, list):
        return {
            "type": "list",
            "node_count": len(payload),
            "preview": safe_str(payload, 500),
        }

    return {
        "type": type(payload).__name__ if payload is not None else "none",
        "preview": safe_str(payload, 500),
    }


def summarize_move_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return {
            "type": "dict",
            "keys": sorted(list(result.keys()))[:30],
            "success": result.get("success"),
            "status": result.get("status"),
            "detail": result.get("detail"),
            "reason": result.get("reason"),
            "message": result.get("message"),
            "raw_preview": safe_str(result, 500),
        }
    if result is None:
        return {
            "type": "none",
            "raw_preview": "",
        }
    return {
        "type": type(result).__name__,
        "raw_preview": safe_str(result, 500),
    }


def try_move_focus_smart(serial: str) -> dict[str, Any]:
    try:
        result = client.move_focus_smart(dev=serial)
        return {
            "success": True,
            "result": result,
            "result_summary": summarize_move_result(result),
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "result_summary": {},
            "error": f"{type(e).__name__}: {e}",
        }


def capture_helper_dump_once(
    out_dir: Path,
    serial: str,
    suffix: str = "",
) -> tuple[list[dict[str, Any]], Optional[Path], Optional[Path], Optional[str], Any]:
    helper_json = out_dir / f"helper_dump{suffix}.json"
    helper_raw_json = out_dir / f"helper_dump_raw{suffix}.json"

    try:
        payload = client.dump_tree(dev=serial)
        write_json(helper_raw_json, payload)

        nodes = extract_nodes_from_dump_payload(payload)
        write_json(helper_json, {"nodes": nodes})

        return nodes, helper_json, helper_raw_json, None, payload
    except Exception as e:
        return [], None, None, f"{type(e).__name__}: {e}", None


def capture_helper_dump_prefer_current_focus(
    out_dir: Path,
    serial: str,
    max_move_attempts: int = 2,
    retry_wait: float = 0.6,
) -> tuple[
    list[dict[str, Any]],
    Optional[Path],
    Optional[Path],
    Optional[str],
    Any,
    list[dict[str, Any]],
]:
    attempts: list[dict[str, Any]] = []

    nodes, helper_json_path, helper_raw_path, helper_err, helper_payload = capture_helper_dump_once(
        out_dir, serial, suffix="_initial"
    )
    payload_summary = summarize_helper_payload(helper_payload)

    initial_attempt = {
        "attempt": 1,
        "mode": "initial_dump_without_focus_move",
        "focus_result": None,
        "node_count": len(nodes),
        "helper_error": helper_err,
        "payload_summary": payload_summary,
    }
    attempts.append(initial_attempt)

    log(
        f"[CAPTURE][helper_retry] attempt=1 "
        f"mode='initial_dump_without_focus_move' "
        f"node_count={len(nodes)} "
        f"helper_error='{helper_err or ''}' "
        f"payload_summary='{safe_str(payload_summary, 300)}'"
    )

    if len(nodes) > 0:
        return nodes, helper_json_path, helper_raw_path, helper_err, helper_payload, attempts

    final_nodes = nodes
    final_helper_json_path = helper_json_path
    final_helper_raw_path = helper_raw_path
    final_helper_err = helper_err
    final_helper_payload = helper_payload

    for idx in range(1, max_move_attempts + 1):
        focus_result = try_move_focus_smart(serial)
        time.sleep(WAIT_SECONDS_AFTER_FOCUS)

        suffix = f"_after_focus_{idx}"
        nodes, helper_json_path, helper_raw_path, helper_err, helper_payload = capture_helper_dump_once(
            out_dir, serial, suffix=suffix
        )
        payload_summary = summarize_helper_payload(helper_payload)

        attempt_info = {
            "attempt": idx + 1,
            "mode": f"dump_after_focus_move_{idx}",
            "focus_result": focus_result,
            "node_count": len(nodes),
            "helper_error": helper_err,
            "payload_summary": payload_summary,
        }
        attempts.append(attempt_info)

        log(
            f"[CAPTURE][helper_retry] attempt={idx + 1} "
            f"mode='dump_after_focus_move_{idx}' "
            f"focus_success={focus_result.get('success')} "
            f"focus_error='{focus_result.get('error') or ''}' "
            f"focus_result_summary='{safe_str(focus_result.get('result_summary'), 300)}' "
            f"node_count={len(nodes)} "
            f"helper_error='{helper_err or ''}' "
            f"payload_summary='{safe_str(payload_summary, 300)}'"
        )

        final_nodes = nodes
        final_helper_json_path = helper_json_path
        final_helper_raw_path = helper_raw_path
        final_helper_err = helper_err
        final_helper_payload = helper_payload

        if len(nodes) > 0:
            return (
                nodes,
                helper_json_path,
                helper_raw_path,
                helper_err,
                helper_payload,
                attempts,
            )

        time.sleep(retry_wait)

    if not final_helper_err and len(final_nodes) == 0:
        final_helper_err = "empty_nodes_after_initial_dump_and_focus_retries"

    return (
        final_nodes,
        final_helper_json_path,
        final_helper_raw_path,
        final_helper_err,
        final_helper_payload,
        attempts,
    )


def main() -> int:
    print(f"[START] capture_debug_single version={SCRIPT_VERSION}")

    serials = get_connected_devices()
    serial = resolve_serial("", serials)

    out_dir = build_output_dir(TAG)
    log(f"[INFO] serial={serial} out_dir='{out_dir}'")

    time.sleep(WAIT_SECONDS_BEFORE_CAPTURE)

    (
        helper_nodes,
        helper_json_path,
        helper_raw_path,
        helper_err,
        helper_payload,
        helper_attempts,
    ) = capture_helper_dump_prefer_current_focus(
        out_dir,
        serial,
        max_move_attempts=2,
        retry_wait=0.6,
    )

    helper_payload_summary = summarize_helper_payload(helper_payload)

    screenshot_ok, screenshot_path, screenshot_err = capture_screenshot(out_dir, serial)

    xml_ok = False
    xml_path = None
    xml_err = None
    if SAVE_XML:
        xml_ok, xml_path, xml_err = capture_uiautomator_xml(out_dir, serial)

    summary = summarize_nodes(helper_nodes, xml_path)
    focused_nodes = extract_focused_nodes(helper_nodes)

    meta = {
        "script_version": SCRIPT_VERSION,
        "serial": serial,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(out_dir),
        "artifacts": {
            "screenshot_ok": screenshot_ok,
            "screenshot_path": str(screenshot_path) if screenshot_path else None,
            "screenshot_error": screenshot_err,
            "helper_dump_path": str(helper_json_path) if helper_json_path else None,
            "helper_raw_path": str(helper_raw_path) if helper_raw_path else None,
            "helper_error": helper_err,
            "xml_ok": xml_ok,
            "xml_path": str(xml_path) if xml_path else None,
            "xml_error": xml_err,
        },
        "helper_attempts": helper_attempts,
        "helper_payload_summary": helper_payload_summary,
        "summary": summary,
        "focused_nodes": focused_nodes,
    }

    write_json(out_dir / "meta.json", meta)

    log(
        f"[DONE] screenshot_ok={screenshot_ok} xml_ok={xml_ok} "
        f"nodes={len(helper_nodes)} focused_nodes={len(focused_nodes)} helper_error='{helper_err or ''}'"
    )
    log(f"[DONE] output='{out_dir}'")

    print("\n=== RESULT ===")
    print(f"📁 {out_dir}")
    print(f"📊 nodes: {len(helper_nodes)}")
    print(f"🎯 focused_nodes: {len(focused_nodes)}")
    print(f"🧩 helper_error: {helper_err or ''}")
    print(f"🧩 helper_summary: {helper_payload_summary}")

    if helper_attempts:
        print("\n=== HELPER ATTEMPTS ===")
        for item in helper_attempts:
            fr = item.get("focus_result") or {}
            print(
                f"- attempt={item.get('attempt')} "
                f"mode={item.get('mode')} "
                f"focus_success={fr.get('success') if fr else ''} "
                f"focus_error={fr.get('error') if fr else ''} "
                f"node_count={item.get('node_count')} "
                f"helper_error={item.get('helper_error') or ''}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())