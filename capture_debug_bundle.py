#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_debug_bundle.py

목적
- 사용자 입력 없이 Life plugin list 스크롤 상태를 자동으로 기록한다.
- 기본 동작은 scroll_capture 모드이며, 각 스텝마다 screenshot/helper dump/xml/meta를 저장한다.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SCRIPT_VERSION = "2.1.0"
OUTPUT_BASE = Path("output/capture_bundles")
DEFAULT_MODE = "scroll_capture"
DEFAULT_WAIT_SECONDS = 0.8
DEFAULT_MAX_STEPS = 10
DEFAULT_SAVE_XML = True
SCREENSHOT_FORMAT = "jpg"
SCREENSHOT_JPG_QUALITY = 85
SUMMARY_TOP_N = 8
LIFE_TAB_REGEX = "(?i).*life.*"

current_dir = os.getcwd()
print(f"현재 작업 디렉토리: {current_dir}")

if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from talkback_lib import A11yAdbClient
    print("✅ talkback_lib 로드 성공")
except ImportError as e:
    print(f"❌ talkback_lib import 실패: {e}")
    raise

try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

client = A11yAdbClient()


def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{now_str()}] {msg}")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_adb(args: list[str], serial: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def get_connected_devices() -> list[str]:
    result = run_adb(["devices"], check=True)
    devices: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        if "\tdevice" in line:
            devices.append(line.split("\t")[0].strip())
    return devices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto capture debug bundles for Life plugin scroll analysis")
    parser.add_argument("--mode", choices=["scroll_capture"], default=DEFAULT_MODE)
    parser.add_argument("--max_steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--save_xml", type=parse_bool_arg, default=DEFAULT_SAVE_XML)
    return parser.parse_args()


def parse_bool_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "false", "f", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("불리언 값은 true/false 로 입력하세요.")


def resolve_serial(serial_arg: str, serials: list[str]) -> str:
    if serial_arg:
        if serial_arg not in serials:
            raise ValueError(f"요청한 serial을 찾을 수 없습니다: {serial_arg}")
        return serial_arg
    if not serials:
        raise ValueError("연결된 Android device가 없습니다.")
    return serials[0]


def capture_uiautomator_xml(out_dir: Path, serial: str) -> tuple[bool, Optional[Path], Optional[str]]:
    remote_xml = "/sdcard/window_dump.xml"
    local_xml = out_dir / "window_dump.xml"
    try:
        run_adb(["shell", "uiautomator", "dump", remote_xml], serial=serial, check=True)
        run_adb(["pull", remote_xml, str(local_xml)], serial=serial, check=True)
        return True, local_xml, None
    except Exception as e:
        return False, None, str(e)


def capture_screenshot(out_dir: Path, serial: str) -> tuple[bool, Optional[Path], Optional[str]]:
    remote_png = "/sdcard/__capture_debug_bundle_screen.png"
    pulled_png = out_dir / "__raw_screen.png"
    final_path = out_dir / "screenshot.jpg"

    try:
        run_adb(["shell", "screencap", "-p", remote_png], serial=serial, check=True)
        run_adb(["pull", remote_png, str(pulled_png)], serial=serial, check=True)

        if PIL_AVAILABLE:
            with Image.open(pulled_png) as img:
                img.convert("RGB").save(final_path, format="JPEG", quality=SCREENSHOT_JPG_QUALITY, optimize=True)
            pulled_png.unlink(missing_ok=True)
            return True, final_path, None

        pulled_png.unlink(missing_ok=True)
        return False, None, "Pillow 미설치로 screenshot.jpg 생성 불가"
    except Exception as e:
        return False, None, str(e)


def get_helper_nodes(dev: str) -> list[dict[str, Any]]:
    dump = client.dump_tree(dev=dev)
    if isinstance(dump, list):
        return [node for node in dump if isinstance(node, dict)]
    if isinstance(dump, dict):
        nodes = dump.get("nodes")
        if isinstance(nodes, list):
            return [node for node in nodes if isinstance(node, dict)]
    return []


def _pick_str(node: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def summarize_nodes(nodes: list[dict[str, Any]], top_n: int = SUMMARY_TOP_N) -> dict[str, Any]:
    labels = []
    resource_ids = []
    class_names = []

    for node in nodes:
        label = _pick_str(node, ["text", "contentDescription", "content_desc", "description"])
        resource_id = _pick_str(node, ["view_id_resource_name", "view_id", "resourceId", "resource_id"])
        class_name = _pick_str(node, ["class_name", "className", "class"])

        if label:
            labels.append(label)
        if resource_id:
            resource_ids.append(resource_id)
        if class_name:
            class_names.append(class_name)

    def _top(values: list[str]) -> list[str]:
        return [name for name, _ in Counter(values).most_common(top_n)]

    return {
        "helper_node_count": len(nodes),
        "visible_labels_top_n": _top(labels),
        "resource_ids_top_n": _top(resource_ids),
        "class_names_top_n": _top(class_names),
    }


def enter_life_tab(dev: str) -> dict[str, Any]:
    try:
        result = client.touch(dev=dev, name=LIFE_TAB_REGEX, type_="t", wait_=4)
        return {
            "ok": bool(result.get("success")),
            "result": result,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def build_step_summary(nodes: list[dict[str, Any]], top_n: int = SUMMARY_TOP_N) -> dict[str, Any]:
    summary = summarize_nodes(nodes, top_n=top_n)
    summary_text = "||".join([
        "|".join(summary["visible_labels_top_n"]),
        "|".join(summary["resource_ids_top_n"]),
        "|".join(summary["class_names_top_n"]),
    ])
    summary_hash = hashlib.sha1(summary_text.encode("utf-8")).hexdigest()[:12]

    maybe_card_like = []
    for node in nodes:
        class_name = _pick_str(node, ["class_name", "className", "class"]).lower()
        clickable = bool(node.get("clickable"))
        label = _pick_str(node, ["text", "contentDescription", "content_desc", "description"])
        resource_id = _pick_str(node, ["view_id_resource_name", "view_id", "resourceId", "resource_id"])
        if ("card" in class_name or "item" in class_name or clickable) and (label or resource_id):
            maybe_card_like.append(f"{label or '[no-text]'}::{resource_id or '[no-id]'}")
        if len(maybe_card_like) >= top_n:
            break

    summary["duplicate_summary_hash"] = summary_hash
    summary["maybe_card_like_nodes_top_n"] = maybe_card_like
    summary["top_bar_present"] = any("toolbar" in c.lower() for c in summary["class_names_top_n"])
    summary["bottom_tab_present"] = any("tab" in c.lower() for c in summary["class_names_top_n"])
    return summary


def save_step_bundle(
    step_dir: Path,
    serial: str,
    step_index: int,
    scroll_performed: bool,
    scroll_result: str,
    save_xml: bool,
    notes: str,
) -> dict[str, Any]:
    ensure_dir(step_dir)

    helper_nodes = get_helper_nodes(serial)
    write_json(step_dir / "helper_dump.json", helper_nodes)

    summary = build_step_summary(helper_nodes)

    screenshot_ok, screenshot_path, screenshot_err = capture_screenshot(step_dir, serial)
    xml_ok = False
    xml_path: Optional[Path] = None
    xml_err: Optional[str] = None
    if save_xml:
        xml_ok, xml_path, xml_err = capture_uiautomator_xml(step_dir, serial)

    meta = {
        "script_version": SCRIPT_VERSION,
        "capture_mode": DEFAULT_MODE,
        "step_index": step_index,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "scroll_performed": scroll_performed,
        "scroll_result": scroll_result,
        "helper_node_count": summary["helper_node_count"],
        "xml_saved": xml_ok,
        "screenshot_saved": screenshot_ok,
        "visible_labels_top_n": summary["visible_labels_top_n"],
        "resource_ids_top_n": summary["resource_ids_top_n"],
        "class_names_top_n": summary["class_names_top_n"],
        "maybe_card_like_nodes_top_n": summary["maybe_card_like_nodes_top_n"],
        "duplicate_summary_hash": summary["duplicate_summary_hash"],
        "reached_end_guess": False,
        "top_bar_present": summary["top_bar_present"],
        "bottom_tab_present": summary["bottom_tab_present"],
        "notes": notes,
    }
    if screenshot_path:
        meta["screenshot_path"] = screenshot_path.name
    if xml_path:
        meta["xml_path"] = xml_path.name
    if screenshot_err:
        meta["screenshot_note"] = screenshot_err
    if xml_err:
        meta["xml_note"] = xml_err
    if not save_xml:
        meta["xml_note"] = "save_xml=false 로 XML 저장 생략"

    write_json(step_dir / "meta.json", meta)
    return {"meta": meta, "signature": summary["duplicate_summary_hash"]}


def run_scroll_capture(serial: str, max_steps: int, save_xml: bool, wait_seconds: float) -> Path:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_BASE / "life_plugin_scroll_capture" / run_id
    ensure_dir(run_dir)

    session_meta: dict[str, Any] = {
        "script_version": SCRIPT_VERSION,
        "mode": "scroll_capture",
        "serial": serial,
        "run_id": run_id,
        "max_steps": max_steps,
        "save_xml": save_xml,
        "screenshot_format": SCREENSHOT_FORMAT,
        "screenshot_quality": SCREENSHOT_JPG_QUALITY,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }

    life_result = enter_life_tab(serial)
    session_meta["life_tab_entry"] = life_result
    if life_result.get("ok"):
        log("✅ Life 탭 진입 시도 성공")
    else:
        log("⚠️ Life 탭 진입 실패(또는 이미 Life 아님), 현재 화면 기준으로 캡처 진행")

    try:
        top_result = client.scroll_to_top(dev=serial, max_swipes=5, pause=max(0.3, wait_seconds))
    except Exception as e:
        top_result = {"ok": False, "reason": "exception", "error": str(e)}
    session_meta["scroll_to_top"] = top_result

    records: list[dict[str, Any]] = []
    previous_signature = ""
    repeated_count = 0
    reached_end_guess = False

    for step in range(1, max(1, max_steps) + 1):
        step_dir = run_dir / f"step_{step:02d}"
        note = "initial_capture" if step == 1 else "after_scroll_down"
        captured = save_step_bundle(
            step_dir=step_dir,
            serial=serial,
            step_index=step,
            scroll_performed=(step > 1),
            scroll_result="captured",
            save_xml=save_xml,
            notes=note,
        )
        records.append(captured["meta"])
        signature = captured["signature"]

        if step > 1 and signature == previous_signature:
            repeated_count += 1
            reached_end_guess = True
            records[-1]["notes"] = "same_visible_summary_detected"
            records[-1]["reached_end_guess"] = True
            records[-1]["scroll_result"] = "same_summary_repeated"
            log(f"⚠️ step={step} 동일 화면 반복 감지")
            break

        previous_signature = signature

        if step >= max_steps:
            records[-1]["notes"] = "max_steps_reached"
            break

        scrolled = False
        try:
            scrolled = bool(client.scroll(dev=serial, direction="down"))
        except Exception:
            scrolled = False

        if not scrolled:
            reached_end_guess = True
            records[-1]["notes"] = "scroll_not_performed_or_end_reached"
            records[-1]["reached_end_guess"] = True
            records[-1]["scroll_result"] = "scroll_not_performed_or_end_reached"
            log(f"⚠️ step={step} 이후 스크롤 불가 추정, 종료")
            break

        time.sleep(max(0.0, wait_seconds))

    summary = {
        "script_version": SCRIPT_VERSION,
        "capture_mode": DEFAULT_MODE,
        "serial": serial,
        "run_id": run_id,
        "max_steps": max_steps,
        "save_xml": save_xml,
        "screenshot_format": SCREENSHOT_FORMAT,
        "screenshot_quality": SCREENSHOT_JPG_QUALITY,
        "started_at": session_meta["started_at"],
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "captured_steps": len(records),
        "same_screen_repeat_count": repeated_count,
        "reached_end_guess": reached_end_guess,
        "life_tab_entry": life_result,
        "scroll_to_top": top_result,
        "steps": records,
    }
    write_json(run_dir / "summary.json", summary)

    return run_dir


def main() -> None:
    args = parse_args()

    try:
        serials = get_connected_devices()
        serial = resolve_serial("", serials)
    except Exception as e:
        print(f"❌ 기기 확인 실패: {e}")
        return

    log(f"모드={args.mode}, serial={serial}, max_steps={args.max_steps}, save_xml={args.save_xml}")

    out_dir = run_scroll_capture(
        serial=serial,
        max_steps=args.max_steps,
        save_xml=args.save_xml,
        wait_seconds=DEFAULT_WAIT_SECONDS,
    )

    print(f"\n✅ 캡처 완료: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
