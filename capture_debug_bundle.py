#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_debug_bundle_v103.py

목적
- 특정 앱/화면 상태에서 분석용 증적 묶음(debug bundle)을 한 번에 저장한다.
- 저장 항목:
  1) helper dump
  2) get_focus 결과
  3) UIAutomator XML dump
  4) screenshot
  5) a11y helper 관련 logcat
  6) 메타데이터/요약 파일

왜 쓰는가
- smart move / candidate selection / anchor fallback / hero summary 누락 같은 문제를
  "같은 시점" 기준으로 비교 분석하기 위함.
- helper tree와 일반 XML tree, 실제 스크린샷을 묶어두면 원인 파악이 훨씬 쉬워진다.

실행 방법
1) talkback-a11y-helper 폴더 안에 이 파일을 둔다.
2) 가상환경 활성화 후 실행:
   python capture_debug_bundle_v103.py
3) 수동으로 원하는 앱/화면까지 이동한다.
4) 안내에 따라:
   - 단건(single)
   - 전/후(before_after)
   중 하나로 캡처한다.

간단 입력 예시
- 전체 설정을 한 줄로 빠르게 입력 가능:
  sma food add ba j 85

  의미:
  - 앱 이름: sma
  - 화면 이름: food
  - 버튼/동작: add
  - 모드: before_after
  - 스크린샷 포맷: jpg
  - jpg 품질: 85

- 더 짧게:
  st set gear s j 82

지원 약어
- 모드:
  s  = single
  ba = before_after
- 포맷:
  j = jpg
  p = png

주의
- JPG 저장은 Pillow(PIL)가 있으면 안정적으로 동작한다.
- Pillow가 없으면 PNG로 fallback 할 수 있다.
- adb가 PATH에 있어야 한다.
- 여러 기기 연결 시 serial 지정 가능하다.

권장
- 일반 분석용: jpg 품질 85~90
- 글자 선명도 조금 더 중요: 90~92
- 원본 보존 우선: png
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# =========================================================
# 기본 설정
# =========================================================
SCRIPT_VERSION = "1.0.3"
OUTPUT_BASE = Path("capture_bundles")
DEFAULT_WAIT_SECONDS = 1.0
DEFAULT_MODE = "single"
DEFAULT_IMAGE_FORMAT = "jpg"
DEFAULT_JPG_QUALITY = 88

# logcat 필터를 너무 강하게 잡으면 필요한 로그가 빠질 수 있어서,
# 우선 전체 로그를 가져온 뒤 helper 관련 라인 위주로 따로 summary를 만든다.
LOGCAT_FILTER_KEYWORDS = [
    "A11Y_HELPER",
    "FOCUS_RESULT",
    "FOCUS_UPDATE",
    "SMART_NEXT",
    "A11yNavigator",
    "A11yTraversalAnalyzer",
    "get_focus",
]

# =========================================================
# 현재 작업 디렉토리 / import 경로 설정
# =========================================================
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

# Pillow는 선택사항
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

client = A11yAdbClient()

# =========================================================
# 유틸
# =========================================================
def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log(msg: str) -> None:
    print(f"[{now_str()}] {msg}")

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def sanitize_name(text: str, limit: int = 80) -> str:
    text = (text or "").strip()
    if not text:
        return "unknown"
    text = re.sub(r'[<>:"/\\|?*\n\r\t]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._ ")
    if not text:
        text = "unknown"
    return text[:limit]

def unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    idx = 2
    while True:
        candidate = Path(f"{path}_v{idx}")
        if not candidate.exists():
            return candidate
        idx += 1

def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")

def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def safe_len(obj: Any) -> Optional[int]:
    try:
        return len(obj)
    except Exception:
        return None

# =========================================================
# ADB 실행
# =========================================================
def run_adb(args, serial: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """
    Windows에서 adb 출력에 UTF-8 문자열이 섞일 수 있으므로
    cp949 기본 디코딩을 쓰면 UnicodeDecodeError가 날 수 있다.
    그래서 encoding='utf-8', errors='replace'로 고정한다.
    """
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
    devices = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        if "\tdevice" in line:
            devices.append(line.split("\t")[0].strip())
    return devices

# =========================================================
# 입력 처리
# =========================================================
def normalize_mode(value: str) -> str:
    value = (value or "").strip().lower()
    mapping = {
        "s": "single",
        "single": "single",
        "1": "single",
        "ba": "before_after",
        "before_after": "before_after",
        "beforeafter": "before_after",
        "b": "before_after",
        "2": "before_after",
    }
    return mapping.get(value, DEFAULT_MODE)

def normalize_image_format(value: str) -> str:
    value = (value or "").strip().lower()
    mapping = {
        "j": "jpg",
        "jpg": "jpg",
        "jpeg": "jpg",
        "p": "png",
        "png": "png",
    }
    return mapping.get(value, DEFAULT_IMAGE_FORMAT)

def try_parse_quality(value: str) -> int:
    try:
        q = int(value)
        return max(1, min(100, q))
    except Exception:
        return DEFAULT_JPG_QUALITY

def prompt_with_default(prompt: str, default: str) -> str:
    raw = input(prompt).strip()
    return raw if raw else default

def parse_quick_line(line: str) -> Optional[Dict[str, Any]]:
    """
    빠른 입력 포맷:
      app screen action mode [imgfmt] [quality]

    예:
      sma food add ba j 85
      st settings gear s
      st device more ba png
    """
    tokens = [t for t in line.strip().split() if t]
    if len(tokens) < 4:
        return None

    app_name = tokens[0]
    screen_name = tokens[1]
    action_name = tokens[2]
    mode = normalize_mode(tokens[3])

    image_format = DEFAULT_IMAGE_FORMAT
    jpg_quality = DEFAULT_JPG_QUALITY

    if len(tokens) >= 5:
        image_format = normalize_image_format(tokens[4])

    if len(tokens) >= 6:
        jpg_quality = try_parse_quality(tokens[5])

    return {
        "app_name": app_name,
        "screen_name": screen_name,
        "action_name": action_name,
        "mode": mode,
        "image_format": image_format,
        "jpg_quality": jpg_quality,
    }

def collect_user_inputs(serials: list[str]) -> Dict[str, Any]:
    print("=" * 72)
    print("TalkBack Debug Bundle Capture")
    print("helper dump + get_focus + xml dump + screenshot + logcat 저장")
    print("=" * 72)

    default_serial = serials[0] if serials else ""
    print(f"연결된 device: {', '.join(serials) if serials else '(없음)'}")
    serial = input("serial 변경이 필요하면 입력, 그대로면 Enter: ").strip() or default_serial

    print("\n빠른 입력 가능 예시: sma food add ba j 85")
    quick = input("빠른 입력(Enter면 개별 입력): ").strip()

    parsed = parse_quick_line(quick) if quick else None

    if parsed:
        app_name = parsed["app_name"]
        screen_name = parsed["screen_name"]
        action_name = parsed["action_name"]
        mode = parsed["mode"]
        image_format = parsed["image_format"]
        jpg_quality = parsed["jpg_quality"]
        print(f"빠른 입력 해석 완료 → app={app_name}, screen={screen_name}, action={action_name}, mode={mode}, fmt={image_format}, quality={jpg_quality}")
    else:
        app_name = prompt_with_default("앱 이름(예: SmartThings): ", "app")
        screen_name = prompt_with_default("화면 이름(예: Food_detail): ", "screen")
        action_name = prompt_with_default("직전에 누른 버튼/동작(예: Add_button): ", "action")
        mode = normalize_mode(input("캡처 모드 [single/s 또는 before_after/ba] (기본 single): ").strip())
        image_format = normalize_image_format(input("스크린샷 포맷 [jpg/j 또는 png/p] (기본 jpg): ").strip())
        jpg_quality = DEFAULT_JPG_QUALITY
        if image_format == "jpg":
            jpg_quality = try_parse_quality(input(f"jpg 품질 1~100 (기본 {DEFAULT_JPG_QUALITY}): ").strip())

    wait_seconds = DEFAULT_WAIT_SECONDS
    wait_input = input(f"엔터 후 캡처 전 대기 초(기본 {DEFAULT_WAIT_SECONDS}): ").strip()
    if wait_input:
        try:
            wait_seconds = max(0.0, float(wait_input))
        except Exception:
            pass

    return {
        "serial": serial,
        "app_name": sanitize_name(app_name),
        "screen_name": sanitize_name(screen_name),
        "action_name": sanitize_name(action_name),
        "mode": mode,
        "image_format": image_format,
        "jpg_quality": jpg_quality,
        "wait_seconds": wait_seconds,
    }

# =========================================================
# talkback_lib 호출
# =========================================================
def try_call_client_method(*method_names, default=None):
    for method_name in method_names:
        if hasattr(client, method_name):
            method = getattr(client, method_name)
            try:
                return method()
            except TypeError:
                try:
                    return method(serial=None)
                except Exception:
                    continue
            except Exception:
                continue
    return default

def reset_focus_history_safe() -> Dict[str, Any]:
    try:
        client.reset_focus_history()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def capture_helper_dump(out_dir: Path) -> Dict[str, Any]:
    """
    helper dump 결과를 최대한 보존한다.
    반환 타입이 dict/list/string 무엇이든 저장 가능하게 한다.
    """
    result = try_call_client_method(
        "dump_tree",
        "dump_a11y_tree",
        "dump_current_screen",
        "get_a11y_dump",
        "get_dump",
        default=None,
    )

    summary_lines = []
    meta = {
        "available": result is not None,
        "type": type(result).__name__ if result is not None else None,
    }

    if result is None:
        summary_lines.append("helper dump를 가져오지 못했습니다.")
        write_text(out_dir / "helper_dump_summary.txt", "\n".join(summary_lines))
        write_json(out_dir / "helper_dump_metadata.json", meta)
        return meta

    if isinstance(result, dict):
        write_json(out_dir / "helper_dump_raw.json", result)
        nodes = result.get("nodes")
        metadata = result.get("metadata", {})
        if nodes is not None:
            write_json(out_dir / "helper_dump_nodes.json", nodes)
            meta["nodes_count"] = safe_len(nodes)
        if metadata:
            write_json(out_dir / "helper_dump_metadata.json", metadata)
        else:
            write_json(out_dir / "helper_dump_metadata.json", meta)

        summary_lines.append(f"type=dict")
        summary_lines.append(f"keys={list(result.keys())}")
        if nodes is not None:
            summary_lines.append(f"nodes_count={safe_len(nodes)}")

    elif isinstance(result, list):
        write_json(out_dir / "helper_dump_nodes.json", result)
        meta["nodes_count"] = safe_len(result)
        write_json(out_dir / "helper_dump_metadata.json", meta)
        summary_lines.append("type=list")
        summary_lines.append(f"nodes_count={safe_len(result)}")

    else:
        text = str(result)
        write_text(out_dir / "helper_dump_text.txt", text)
        write_json(out_dir / "helper_dump_metadata.json", meta)
        summary_lines.append(f"type={type(result).__name__}")
        summary_lines.append(f"text_length={len(text)}")

    write_text(out_dir / "helper_dump_summary.txt", "\n".join(summary_lines))
    return meta

def capture_get_focus(out_dir: Path) -> Dict[str, Any]:
    """
    get_focus 계열 메서드의 반환값을 가능한 한 그대로 저장한다.
    """
    result = try_call_client_method(
        "get_focus",
        "get_focus_info",
        "get_current_focus",
        "read_focus",
        default=None,
    )

    info = {"available": result is not None, "type": type(result).__name__ if result is not None else None}

    if result is None:
        write_text(out_dir / "focus_payload.txt", "get_focus 결과 없음")
        write_json(out_dir / "focus_trace.json", info)
        return info

    if isinstance(result, (dict, list)):
        write_json(out_dir / "focus_payload.json", result)
    else:
        write_text(out_dir / "focus_payload.txt", str(result))

    write_json(out_dir / "focus_trace.json", info)
    return info

# =========================================================
# XML / Screenshot / Logcat
# =========================================================
def capture_uiautomator_xml(out_dir: Path, serial: str) -> Path:
    remote_xml = "/sdcard/window_dump.xml"
    local_xml = out_dir / "window_dump.xml"
    run_adb(["shell", "uiautomator", "dump", remote_xml], serial=serial, check=True)
    run_adb(["pull", remote_xml, str(local_xml)], serial=serial, check=True)
    return local_xml

def capture_screenshot(out_dir: Path, serial: str, image_format: str, jpg_quality: int) -> Path:
    remote_png = "/sdcard/__capture_debug_bundle_screen.png"
    pulled_png = out_dir / "__raw_screen.png"

    run_adb(["shell", "screencap", "-p", remote_png], serial=serial, check=True)
    run_adb(["pull", remote_png, str(pulled_png)], serial=serial, check=True)

    if image_format == "png":
        final_path = out_dir / "screenshot.png"
        if final_path.exists():
            final_path.unlink()
        pulled_png.replace(final_path)
        return final_path

    # jpg 요청
    final_path = out_dir / "screenshot.jpg"
    if PIL_AVAILABLE:
        with Image.open(pulled_png) as img:
            rgb = img.convert("RGB")
            rgb.save(final_path, format="JPEG", quality=jpg_quality, optimize=True)
        try:
            pulled_png.unlink(missing_ok=True)
        except Exception:
            pass
        return final_path

    # Pillow 없으면 png fallback
    fallback = out_dir / "screenshot.png"
    if fallback.exists():
        fallback.unlink()
    pulled_png.replace(fallback)
    return fallback

def capture_logcat(out_dir: Path, serial: str) -> Dict[str, Any]:
    """
    전체 logcat 저장 + helper 관련 키워드 summary 저장.
    """
    result = run_adb(["logcat", "-d", "-v", "time"], serial=serial, check=True)
    full_text = result.stdout or ""
    full_path = out_dir / "logcat_full.txt"
    write_text(full_path, full_text)

    filtered_lines = []
    for line in full_text.splitlines():
        upper = line.upper()
        if any(keyword.upper() in upper for keyword in LOGCAT_FILTER_KEYWORDS):
            filtered_lines.append(line)

    filtered_text = "\n".join(filtered_lines)
    filtered_path = out_dir / "logcat_a11y_helper.txt"
    write_text(filtered_path, filtered_text)

    return {
        "full_lines": len(full_text.splitlines()),
        "filtered_lines": len(filtered_lines),
        "full_path": str(full_path),
        "filtered_path": str(filtered_path),
    }

# =========================================================
# 메타 정보
# =========================================================
def get_window_focus_info(serial: str) -> str:
    try:
        result = run_adb(["shell", "dumpsys", "window", "windows"], serial=serial, check=True)
        for line in result.stdout.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                return line.strip()
    except Exception:
        pass
    return "unknown_focus"

def write_readme(out_dir: Path, image_format: str, jpg_quality: int) -> None:
    content = f"""이 폴더는 TalkBack 디버그 분석용 캡처 결과입니다.

파일 설명
- meta.json: 캡처 시각, 기기, 입력값 등 메타데이터
- helper_dump_*: helper dump 원본/요약
- focus_payload.*: get_focus 응답
- focus_trace.json: get_focus 저장 메타
- window_dump.xml: UIAutomator 일반 XML dump
- screenshot.*: 스크린샷
- logcat_full.txt: 전체 logcat
- logcat_a11y_helper.txt: helper 관련 키워드만 필터한 로그
- capture_result.json: 각 단계 저장 결과 요약

스크린샷 설정
- format={image_format}
- jpg_quality={jpg_quality}

권장 비교
1. screenshot에서 실제 보이는 객체 확인
2. window_dump.xml에서 raw tree 구조 확인
3. helper_dump에서 helper 후보/노드 구조 확인
4. focus_payload에서 현재 focus 판단 확인
5. logcat_a11y_helper.txt에서 smart move / get_focus 관련 로그 확인
"""
    write_text(out_dir / "README_CAPTURE.txt", content)

# =========================================================
# 단일 캡처
# =========================================================
def do_capture_bundle(base_name: str, out_dir: Path, serial: str, image_format: str, jpg_quality: int, wait_seconds: float) -> Dict[str, Any]:
    ensure_dir(out_dir)

    time.sleep(wait_seconds)

    reset_result = reset_focus_history_safe()
    if reset_result.get("ok"):
        log("✅ focus history reset 완료")
    else:
        log(f"⚠️ focus history reset 실패: {reset_result.get('error')}")

    meta = {
        "script_version": SCRIPT_VERSION,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "base_name": base_name,
        "serial": serial,
        "cwd": os.getcwd(),
        "window_focus_info": get_window_focus_info(serial),
        "image_format_requested": image_format,
        "jpg_quality": jpg_quality,
        "pillow_available": PIL_AVAILABLE,
    }
    write_json(out_dir / "meta.json", meta)

    result = {
        "meta": meta,
        "reset_focus_history": reset_result,
    }

    try:
        helper_meta = capture_helper_dump(out_dir)
        result["helper_dump"] = helper_meta
        log(f"✅ helper dump 저장 완료 (nodes={helper_meta.get('nodes_count')})")
    except Exception as e:
        result["helper_dump"] = {"ok": False, "error": str(e)}
        log(f"⚠️ helper dump 저장 실패: {e}")

    try:
        focus_meta = capture_get_focus(out_dir)
        result["get_focus"] = focus_meta
        log("✅ get_focus 저장 완료")
    except Exception as e:
        result["get_focus"] = {"ok": False, "error": str(e)}
        log(f"⚠️ get_focus 저장 실패: {e}")

    try:
        xml_path = capture_uiautomator_xml(out_dir, serial)
        result["uiautomator_xml"] = {"ok": True, "path": str(xml_path)}
        log("✅ UIAutomator XML 저장 완료")
    except Exception as e:
        result["uiautomator_xml"] = {"ok": False, "error": str(e)}
        log(f"⚠️ UIAutomator XML 저장 실패: {e}")

    try:
        screenshot_path = capture_screenshot(out_dir, serial, image_format, jpg_quality)
        result["screenshot"] = {"ok": True, "path": str(screenshot_path)}
        log(f"✅ 스크린샷 저장 완료 ({screenshot_path.name})")
    except Exception as e:
        result["screenshot"] = {"ok": False, "error": str(e)}
        log(f"⚠️ 스크린샷 저장 실패: {e}")

    try:
        logcat_result = capture_logcat(out_dir, serial)
        result["logcat"] = {"ok": True, **logcat_result}
        log(f"✅ logcat 저장 완료 (filtered_lines={logcat_result.get('filtered_lines')})")
    except Exception as e:
        result["logcat"] = {"ok": False, "error": str(e)}
        log(f"⚠️ logcat 저장 실패: {e}")

    write_readme(out_dir, image_format, jpg_quality)
    write_json(out_dir / "capture_result.json", result)
    return result

# =========================================================
# 메인
# =========================================================
def main() -> None:
    try:
        serials = get_connected_devices()
    except Exception as e:
        print(f"❌ adb devices 실패: {e}")
        return

    if not serials:
        print("❌ 연결된 Android device가 없습니다.")
        return

    config = collect_user_inputs(serials)

    serial = config["serial"]
    app_name = config["app_name"]
    screen_name = config["screen_name"]
    action_name = config["action_name"]
    mode = config["mode"]
    image_format = config["image_format"]
    jpg_quality = config["jpg_quality"]
    wait_seconds = config["wait_seconds"]

    if not serial:
        print("❌ 사용할 serial이 없습니다.")
        return

    if mode == "single":
        input("\n[SINGLE] 원하는 화면 상태를 맞춘 뒤 Enter를 누르세요...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{timestamp}__{app_name}__{screen_name}__{action_name}"
        out_dir = unique_dir(OUTPUT_BASE / base_name)

        do_capture_bundle(
            base_name=base_name,
            out_dir=out_dir,
            serial=serial,
            image_format=image_format,
            jpg_quality=jpg_quality,
            wait_seconds=wait_seconds,
        )
        print(f"\n✅ SINGLE 저장 완료: {out_dir.resolve()}")

    else:
        input("\n[BEFORE] 원하는 화면 상태를 맞춘 뒤 Enter를 누르세요...")
        timestamp_before = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_before = f"{timestamp_before}__{app_name}__{screen_name}__{action_name}__before"
        out_before = unique_dir(OUTPUT_BASE / base_before)

        do_capture_bundle(
            base_name=base_before,
            out_dir=out_before,
            serial=serial,
            image_format=image_format,
            jpg_quality=jpg_quality,
            wait_seconds=wait_seconds,
        )
        print(f"\n✅ BEFORE 저장 완료: {out_before.resolve()}")

        input("\n[AFTER] 버튼을 누르거나 화면 전이 후 Enter를 누르세요...")
        timestamp_after = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_after = f"{timestamp_after}__{app_name}__{screen_name}__{action_name}__after"
        out_after = unique_dir(OUTPUT_BASE / base_after)

        do_capture_bundle(
            base_name=base_after,
            out_dir=out_after,
            serial=serial,
            image_format=image_format,
            jpg_quality=jpg_quality,
            wait_seconds=wait_seconds,
        )
        print(f"\n✅ AFTER 저장 완료: {out_after.resolve()}")

    print("\n완료")

if __name__ == "__main__":
    main()
