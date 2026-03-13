from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from talkback_lib import A11yAdbClient


def take_snapshot(dev_serial: str, save_path: str) -> None:
    """ADB screencap을 수행해 현재 화면을 로컬 파일로 저장합니다."""
    remote_path = "/sdcard/temp.png"
    save_file = Path(save_path)
    save_file.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["adb", "-s", dev_serial, "shell", "screencap", "-p", remote_path],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["adb", "-s", dev_serial, "pull", remote_path, str(save_file)],
        check=True,
        capture_output=True,
        text=True,
    )


def _save_failure_image(snapshot_path: Path, target_name: str, actual_speech: str) -> None:
    """Fail 케이스용 이미지에 EXPECTED/ACTUAL 오버레이를 추가해 저장합니다."""
    error_dir = Path("error_log")
    error_dir.mkdir(parents=True, exist_ok=True)
    fail_path = error_dir / f"fail_{target_name}.png"

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


def verify_talkback_speech(dev_serial: str, client: A11yAdbClient, target_name: str) -> bool:
    """선 스냅샷/후 검증 패턴으로 TalkBack 발화를 검증합니다."""
    temp_path = Path(f"temp_{target_name}.png")

    focused = client.select(dev_serial, target_name)
    if not focused:
        print(f"[WARN] 타겟 포커스 실패: {target_name}")

    take_snapshot(dev_serial, str(temp_path))

    announcements = client.get_announcements(dev_serial, wait_seconds=3.0)
    actual_speech = announcements[-1] if announcements else "음성 없음"

    if target_name in actual_speech:
        if temp_path.exists():
            os.remove(temp_path)
        return True

    _save_failure_image(temp_path, target_name, actual_speech)
    return False


def main() -> None:
    client = A11yAdbClient()
    dev_serial = "R3CX40QFDBP"
    target_name = "수면 환경"

    print("=== TalkBack 선스냅샷/후검증 테스트 시작 ===")
    found = client.scrollFind(dev_serial, target_name, direction_="down")
    if not found:
        print(f"[FAIL] 스크롤 탐색 실패: {target_name}")
        return

    result = verify_talkback_speech(dev_serial, client, target_name)
    if result:
        print(f"[PASS] 발화 검증 성공: {target_name}")
    else:
        print(f"[FAIL] 발화 검증 실패: {target_name} (error_log 폴더 확인)")


if __name__ == "__main__":
    main()
