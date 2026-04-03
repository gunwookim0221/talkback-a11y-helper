import json
import os
import re
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


# ============================================================
# 추천 파일명:
#   capture_debug_bundle.py
# 목적:
#   특정 화면 시점의 증적 묶음(helper dump / get_focus / xml dump / screenshot)
#   을 한 번에 저장해서 smart move / anchor / candidate 분석에 활용
# ============================================================

SCRIPT_VERSION = "1.0.0"
OUTPUT_BASE = Path("capture_bundles")
REMOTE_XML_PATH = "/sdcard/window_dump.xml"


# ------------------------------------------------------------
# 환경 준비
# ------------------------------------------------------------
def bootstrap_import() -> Any:
    current_dir = os.getcwd()
    print(f"현재 작업 디렉토리: {current_dir}")

    if current_dir not in sys.path:
        sys.path.append(current_dir)

    try:
        from talkback_lib import A11yAdbClient
        print("✅ talkback_lib 로드 성공")
        return A11yAdbClient
    except ImportError as exc:
        print(f"❌ talkback_lib import 실패: {exc}")
        raise


A11yAdbClient = bootstrap_import()


# ------------------------------------------------------------
# 유틸
# ------------------------------------------------------------
def now_str() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{now_str()}] {msg}")


def sanitize_name(value: str, max_len: int = 80) -> str:
    value = (value or "").strip()
    value = re.sub(r"[\\/:*?\"<>|\s]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:max_len] or "unknown"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_input(prompt: str, default: str = "") -> str:
    value = input(prompt).strip()
    return value if value else default


def build_adb_base(serial: str | None) -> list[str]:
    base = ["adb"]
    if serial:
        base += ["-s", serial]
    return base


def run_adb(serial: str | None, args: list[str], timeout: float = 20.0, check: bool = True) -> subprocess.CompletedProcess:
    cmd = build_adb_base(serial) + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)


def get_connected_devices() -> list[str]:
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10, check=True)
    except Exception:
        return []

    devices: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line or "\tdevice" not in line:
            continue
        devices.append(line.split("\t")[0].strip())
    return devices


def detect_foreground_window(serial: str | None) -> dict[str, str]:
    info = {
        "window_line": "",
        "package": "unknown",
        "activity": "unknown",
    }
    try:
        result = run_adb(serial, ["shell", "dumpsys", "window", "windows"], timeout=15, check=True)
        lines = result.stdout.splitlines()
        focus_line = ""
        for line in lines:
            stripped = line.strip()
            if "mCurrentFocus" in stripped:
                focus_line = stripped
                break
        if not focus_line:
            for line in lines:
                stripped = line.strip()
                if "mFocusedApp" in stripped:
                    focus_line = stripped
                    break
        info["window_line"] = focus_line

        m = re.search(r"\s([A-Za-z0-9_.$]+)/(?:[A-Za-z0-9_.$]+|\.[A-Za-z0-9_.$]+)", focus_line)
        if m:
            info["package"] = m.group(1)

        m2 = re.search(r"\s([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)", focus_line)
        if m2:
            info["activity"] = m2.group(1)
    except Exception as exc:
        info["window_line"] = f"detect_failed: {exc}"
    return info


def next_versioned_dir(base_dir: Path) -> Path:
    if not base_dir.exists():
        return base_dir
    idx = 2
    while True:
        candidate = Path(f"{base_dir}_v{idx}")
        if not candidate.exists():
            return candidate
        idx += 1


# ------------------------------------------------------------
# 캡처 함수
# ------------------------------------------------------------
def capture_helper_dump(client: Any, serial: str | None, out_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": False,
        "error": "",
        "node_count": 0,
        "metadata": {},
        "files": [],
    }
    try:
        nodes = client.dump_tree(dev=serial)
        metadata = getattr(client, "last_dump_metadata", {}) or {}
        write_json(out_dir / "helper_dump_nodes.json", nodes)
        write_json(out_dir / "helper_dump_metadata.json", metadata)
        write_text(out_dir / "helper_dump_summary.txt", f"node_count: {len(nodes)}\nmetadata: {json.dumps(metadata, ensure_ascii=False)}\n")
        result["success"] = True
        result["node_count"] = len(nodes)
        result["metadata"] = metadata
        result["files"] = [
            "helper_dump_nodes.json",
            "helper_dump_metadata.json",
            "helper_dump_summary.txt",
        ]
        log(f"✅ helper dump 저장 완료 (nodes={len(nodes)})")
    except Exception as exc:
        result["error"] = str(exc)
        write_text(out_dir / "helper_dump_error.txt", str(exc))
        log(f"⚠️ helper dump 실패: {exc}")
    return result


def capture_focus_info(client: Any, serial: str | None, out_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": False,
        "error": "",
        "files": [],
    }
    try:
        focus = client.get_focus(dev=serial, wait_seconds=2.0, allow_fallback_dump=True, mode="normal")
        trace = getattr(client, "last_get_focus_trace", {}) or {}
        write_json(out_dir / "focus_payload.json", focus)
        write_json(out_dir / "focus_trace.json", trace)
        result["success"] = True
        result["files"] = ["focus_payload.json", "focus_trace.json"]
        log("✅ get_focus 저장 완료")
    except Exception as exc:
        result["error"] = str(exc)
        write_text(out_dir / "focus_error.txt", str(exc))
        log(f"⚠️ get_focus 실패: {exc}")
    return result


def capture_uiautomator_xml(serial: str | None, out_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": False,
        "error": "",
        "files": [],
    }
    local_xml = out_dir / "window_dump.xml"
    try:
        run_adb(serial, ["shell", "uiautomator", "dump", REMOTE_XML_PATH], timeout=20, check=True)
        run_adb(serial, ["pull", REMOTE_XML_PATH, str(local_xml)], timeout=20, check=True)
        result["success"] = True
        result["files"] = [local_xml.name]
        log("✅ UIAutomator XML 저장 완료")
    except Exception as exc:
        result["error"] = str(exc)
        write_text(out_dir / "window_dump_error.txt", str(exc))
        log(f"⚠️ UIAutomator dump 실패: {exc}")
    return result


def capture_screenshot(client: Any, serial: str | None, out_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": False,
        "error": "",
        "files": [],
    }
    screenshot_path = out_dir / "screenshot.png"
    try:
        client._take_snapshot(serial, str(screenshot_path))
        result["success"] = True
        result["files"] = [screenshot_path.name]
        log("✅ 스크린샷 저장 완료")
    except Exception as exc:
        result["error"] = str(exc)
        write_text(out_dir / "screenshot_error.txt", str(exc))
        log(f"⚠️ 스크린샷 저장 실패: {exc}")
    return result


def capture_logcat(serial: str | None, out_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": False,
        "error": "",
        "files": [],
    }
    log_path = out_dir / "logcat_a11y_helper.txt"
    try:
        completed = run_adb(serial, ["logcat", "-v", "time", "-d"], timeout=20, check=True)
        lines = []
        for line in completed.stdout.splitlines():
            if "A11Y_HELPER" in line or "FOCUS_" in line or "SMART_" in line:
                lines.append(line)
        write_text(log_path, "\n".join(lines))
        result["success"] = True
        result["files"] = [log_path.name]
        log("✅ 관련 logcat 저장 완료")
    except Exception as exc:
        result["error"] = str(exc)
        write_text(out_dir / "logcat_error.txt", str(exc))
        log(f"⚠️ logcat 저장 실패: {exc}")
    return result


# ------------------------------------------------------------
# 실행 흐름
# ------------------------------------------------------------
def create_capture_bundle(
    client: Any,
    serial: str | None,
    app_name: str,
    screen_name: str,
    action_name: str,
    stage_label: str,
    wait_seconds: float,
) -> Path:
    fg = detect_foreground_window(serial)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    base_name = "__".join(
        [
            timestamp,
            sanitize_name(app_name or fg.get("package", "unknown")),
            sanitize_name(screen_name),
            sanitize_name(action_name),
            sanitize_name(stage_label),
        ]
    )
    out_dir = next_versioned_dir(OUTPUT_BASE / base_name)
    ensure_dir(out_dir)

    meta = {
        "script_version": SCRIPT_VERSION,
        "captured_at": timestamp,
        "device_serial": serial or "default",
        "app_name": app_name,
        "screen_name": screen_name,
        "action_name": action_name,
        "stage_label": stage_label,
        "wait_seconds_before_capture": wait_seconds,
        "foreground_package": fg.get("package", "unknown"),
        "foreground_activity": fg.get("activity", "unknown"),
        "foreground_window_line": fg.get("window_line", ""),
        "cwd": os.getcwd(),
    }
    write_json(out_dir / "meta.json", meta)

    try:
        client.reset_focus_history()
        log("✅ focus history reset 완료")
    except Exception as exc:
        write_text(out_dir / "reset_focus_history_error.txt", str(exc))
        log(f"⚠️ reset_focus_history 실패: {exc}")

    time.sleep(max(wait_seconds, 0.0))

    result_bundle = {
        "helper_dump": capture_helper_dump(client, serial, out_dir),
        "focus": capture_focus_info(client, serial, out_dir),
        "uiautomator_xml": capture_uiautomator_xml(serial, out_dir),
        "screenshot": capture_screenshot(client, serial, out_dir),
        "logcat": capture_logcat(serial, out_dir),
    }
    write_json(out_dir / "capture_result.json", result_bundle)

    summary_lines = [
        f"output_dir: {out_dir}",
        f"foreground_package: {meta['foreground_package']}",
        f"foreground_activity: {meta['foreground_activity']}",
        f"helper_dump_success: {result_bundle['helper_dump']['success']}",
        f"helper_node_count: {result_bundle['helper_dump'].get('node_count', 0)}",
        f"focus_success: {result_bundle['focus']['success']}",
        f"xml_success: {result_bundle['uiautomator_xml']['success']}",
        f"screenshot_success: {result_bundle['screenshot']['success']}",
        f"logcat_success: {result_bundle['logcat']['success']}",
    ]
    write_text(out_dir / "README_CAPTURE.txt", "\n".join(summary_lines) + "\n")
    return out_dir


def pick_serial_interactively() -> str | None:
    devices = get_connected_devices()
    if not devices:
        print("⚠️ adb devices 기준 연결된 device를 찾지 못했습니다. default adb 대상 사용")
        typed = safe_input("직접 serial 입력(없으면 Enter): ", "")
        return typed or None

    if len(devices) == 1:
        print(f"연결된 device: {devices[0]}")
        typed = safe_input("serial 변경이 필요하면 입력, 그대로면 Enter: ", devices[0])
        return typed or devices[0]

    print("연결된 devices:")
    for idx, item in enumerate(devices, start=1):
        print(f"  {idx}. {item}")
    raw = safe_input("사용할 번호 또는 serial 입력: ", devices[0])
    if raw.isdigit():
        index = int(raw) - 1
        if 0 <= index < len(devices):
            return devices[index]
    return raw or devices[0]


def main() -> None:
    print("=" * 72)
    print("TalkBack Debug Bundle Capture")
    print("helper dump + get_focus + xml dump + screenshot + logcat 저장")
    print("=" * 72)

    serial = pick_serial_interactively()
    app_name = safe_input("앱 이름(예: SmartThings): ", "SmartThings")
    screen_name = safe_input("화면 이름(예: Food_detail): ", "unknown_screen")
    action_name = safe_input("직전에 누른 버튼/동작(예: Add_button): ", "manual_capture")
    stage_mode = safe_input("캡처 모드 [single / before_after] (기본 single): ", "single").lower()
    wait_seconds = float(safe_input("엔터 후 캡처 전 대기 초(기본 1.0): ", "1.0"))

    client = A11yAdbClient()

    if stage_mode == "before_after":
        input("[BEFORE] 원하는 화면 상태를 맞춘 뒤 Enter를 누르세요...")
        before_dir = create_capture_bundle(
            client=client,
            serial=serial,
            app_name=app_name,
            screen_name=screen_name,
            action_name=action_name,
            stage_label="before",
            wait_seconds=wait_seconds,
        )
        print(f"\n✅ BEFORE 저장 완료: {before_dir.resolve()}\n")

        input("[AFTER] 버튼을 누르거나 화면 전이 후 Enter를 누르세요...")
        after_dir = create_capture_bundle(
            client=client,
            serial=serial,
            app_name=app_name,
            screen_name=screen_name,
            action_name=action_name,
            stage_label="after",
            wait_seconds=wait_seconds,
        )
        print(f"\n✅ AFTER 저장 완료: {after_dir.resolve()}\n")
    else:
        stage_label = safe_input("stage 라벨(예: before / after / settled, 기본 single): ", "single")
        input("원하는 화면까지 이동한 뒤 Enter를 누르세요...")
        out_dir = create_capture_bundle(
            client=client,
            serial=serial,
            app_name=app_name,
            screen_name=screen_name,
            action_name=action_name,
            stage_label=stage_label,
            wait_seconds=wait_seconds,
        )
        print(f"\n✅ 저장 완료: {out_dir.resolve()}\n")

    print("완료")


if __name__ == "__main__":
    main()
