from pathlib import Path
from unittest.mock import call, patch
import subprocess

import capture_ui_state


def test_capture_screenshot_uses_device_temp_file_and_pull(tmp_path: Path):
    output = tmp_path / "screen.png"

    with patch("capture_ui_state.time.time", return_value=1700000000.123), \
         patch("capture_ui_state.adb_shell") as adb_shell_mock, \
         patch("capture_ui_state.run_cmd") as run_cmd_mock:
        capture_ui_state.capture_screenshot(output)

    remote_png = "/sdcard/__a11y_capture_1700000000123.png"
    adb_shell_mock.assert_has_calls(
        [
            call(f"screencap -p {remote_png}", check=True),
            call(f"rm -f {remote_png}", check=False),
        ]
    )
    run_cmd_mock.assert_called_once_with([capture_ui_state.ADB, "pull", remote_png, str(output)], check=True)


def test_capture_screenshot_cleans_up_remote_file_when_pull_fails(tmp_path: Path):
    output = tmp_path / "screen.png"

    with patch("capture_ui_state.time.time", return_value=1700000000.123), \
         patch("capture_ui_state.adb_shell") as adb_shell_mock, \
         patch(
             "capture_ui_state.run_cmd",
             side_effect=subprocess.CalledProcessError(1, ["adb", "pull"]),
         ):
        try:
            capture_ui_state.capture_screenshot(output)
            assert False, "CalledProcessError가 발생해야 합니다."
        except subprocess.CalledProcessError:
            pass

    remote_png = "/sdcard/__a11y_capture_1700000000123.png"
    adb_shell_mock.assert_has_calls(
        [
            call(f"screencap -p {remote_png}", check=True),
            call(f"rm -f {remote_png}", check=False),
        ]
    )
