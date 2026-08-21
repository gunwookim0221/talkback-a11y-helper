from __future__ import annotations

from pathlib import Path

from PIL import Image

import tb_runner.image_utils as image_utils


def test_focus_crops_include_scenario_identity_to_prevent_overwrite(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(image_utils, "ENABLE_IMAGE_CROP", True)
    monkeypatch.setattr(image_utils, "ENABLE_FULL_SCREEN_EVIDENCE", False)

    def fake_capture(_client, _device, save_path: str) -> None:
        Image.new("RGB", (120, 120), "white").save(save_path)

    def fake_crop(*, crop_path: str, **_kwargs) -> bool:
        crop_file = Path(crop_path)
        crop_file.parent.mkdir(parents=True, exist_ok=True)
        crop_file.write_bytes(b"crop")
        return True

    monkeypatch.setattr(image_utils, "capture_full_screenshot", fake_capture)
    monkeypatch.setattr(image_utils, "crop_image_by_bounds", fake_crop)

    first = image_utils.maybe_capture_focus_crop(
        None,
        "SERIAL",
        {
            "scenario_id": "device_water_leak_sensor_plugin",
            "context_type": "main",
            "tab_name": "main",
            "step_index": 2,
            "visible_label": "",
            "focus_bounds": "10,10,50,50",
        },
        str(tmp_path / "run"),
    )
    second = image_utils.maybe_capture_focus_crop(
        None,
        "SERIAL",
        {
            "scenario_id": "device_motion_sensor_plugin",
            "context_type": "main",
            "tab_name": "main",
            "step_index": 2,
            "visible_label": "",
            "focus_bounds": "10,10,50,50",
        },
        str(tmp_path / "run"),
    )

    first_path = Path(first["crop_image_path"])
    second_path = Path(second["crop_image_path"])
    assert first_path != second_path
    assert "device_water_leak_sensor_plugin" in first_path.name
    assert "device_motion_sensor_plugin" in second_path.name
    assert first_path.is_file()
    assert second_path.is_file()
