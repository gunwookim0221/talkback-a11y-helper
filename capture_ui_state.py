import os
import re
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime


ADB = "adb"

BASE_DIR = Path("captures")
DEFAULT_SESSION_NAME = "manual_capture"

# 필요하면 앱 패키지명 기본값 넣어도 됨
DEFAULT_PACKAGE = ""


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def adb_shell(command: str, check: bool = True) -> subprocess.CompletedProcess:
    return run_cmd([ADB, "shell", command], check=check)


def sanitize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name or "unnamed"


def ensure_device_connected() -> str:
    result = run_cmd([ADB, "devices"], check=True)
    lines = result.stdout.strip().splitlines()[1:]
    devices = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])

    if not devices:
        raise RuntimeError("연결된 adb 디바이스가 없습니다.")

    if len(devices) > 1:
        print("[안내] 여러 디바이스가 연결되어 있습니다. 첫 번째 디바이스를 사용합니다.")
    return devices[0]


def get_current_focus_info() -> dict:
    # 필요 최소한만 저장
    result = adb_shell("dumpsys window windows", check=False)
    text = result.stdout or ""

    focused_line = ""
    current_line = ""

    for line in text.splitlines():
        if "mCurrentFocus" in line and not current_line:
            current_line = line.strip()
        if "mFocusedApp" in line and not focused_line:
            focused_line = line.strip()

    return {
        "mCurrentFocus": current_line,
        "mFocusedApp": focused_line,
    }


def get_foreground_package() -> str:
    result = adb_shell("dumpsys window windows", check=False)
    text = result.stdout or ""

    for line in text.splitlines():
        line = line.strip()
        if "mCurrentFocus" in line:
            # 예: mCurrentFocus=Window{... u0 com.samsung.android.oneconnect/...}
            match = re.search(r"\s([A-Za-z0-9._]+)/(?:[A-Za-z0-9.$_]+)", line)
            if match:
                return match.group(1)
    return ""


def capture_xml(local_path: Path) -> None:
    remote_xml = "/sdcard/window_dump.xml"
    adb_shell(f"uiautomator dump {remote_xml}", check=True)
    run_cmd([ADB, "pull", remote_xml, str(local_path)], check=True)


def capture_screenshot(local_path: Path) -> None:
    # exec-out 사용하면 중간 파일 없이 바로 저장 가능
    with open(local_path, "wb") as f:
        proc = subprocess.run(
            [ADB, "exec-out", "screencap", "-p"],
            stdout=f,
            stderr=subprocess.PIPE,
            check=True
        )
    _ = proc


def save_meta(local_path: Path, session_name: str, tab_name: str, step: int, package_name: str) -> None:
    focus_info = get_current_focus_info()

    meta = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "session_name": session_name,
        "tab_name": tab_name,
        "step": step,
        "package_name": package_name,
        "focus_info": focus_info,
    }

    local_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def capture_once(session_dir: Path, session_name: str, tab_name: str, step: int) -> None:
    step_name = f"step_{step:02d}"

    png_path = session_dir / f"{step_name}.png"
    xml_path = session_dir / f"{step_name}.xml"
    json_path = session_dir / f"{step_name}.meta.json"

    package_name = get_foreground_package()

    capture_screenshot(png_path)
    capture_xml(xml_path)
    save_meta(json_path, session_name, tab_name, step, package_name)

    print(f"[저장 완료] {step_name}")
    print(f"  - {png_path}")
    print(f"  - {xml_path}")
    print(f"  - {json_path}")


def main() -> None:
    print("=== 수동 UI 캡처 도구 ===")
    print("엔터를 누를 때마다 현재 화면의 PNG / XML / META 를 저장합니다.")
    print("종료하려면 q 입력 후 엔터.\n")

    device_id = ensure_device_connected()
    print(f"[ADB 연결] {device_id}")

    session_input = input(f"세션 이름 입력 (기본값: {DEFAULT_SESSION_NAME}): ").strip()
    session_name = sanitize_name(session_input or DEFAULT_SESSION_NAME)

    tab_input = input("탭/화면 이름 입력 (예: menu, home, devices): ").strip()
    tab_name = sanitize_name(tab_input or "unknown")

    session_dir = BASE_DIR / session_name / tab_name
    session_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[저장 폴더] {session_dir.resolve()}")
    print("화면을 원하는 상태로 맞춘 뒤 엔터를 누르세요.\n")

    step = 0
    while True:
        user_input = input("[Enter]=캡처, q=종료 : ").strip().lower()

        if user_input == "q":
            print("종료합니다.")
            break

        try:
            capture_once(session_dir, session_name, tab_name, step)
            step += 1
        except subprocess.CalledProcessError as e:
            print("[오류] adb 명령 실행 실패")
            if e.stderr:
                print(e.stderr)
        except Exception as e:
            print(f"[오류] {e}")


if __name__ == "__main__":
    main()
