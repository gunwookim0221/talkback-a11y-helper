import tempfile
import time
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image

from talkback_lib import A11yAdbClient
from tb_runner.constants import ENABLE_IMAGE_CROP, ENABLE_IMAGE_INSERT_TO_EXCEL
from tb_runner.logging_utils import log
from tb_runner.utils import parse_bounds_str, sanitize_filename


def capture_full_screenshot(client: A11yAdbClient, dev: str, save_path: str) -> None:
    # talkback_lib 내부 private helper 재사용
    client._take_snapshot(dev, save_path)


def crop_image_by_bounds(
    screenshot_path: str,
    bounds_str: str,
    crop_path: str,
    shrink_px: int = 0,
) -> bool:
    bounds = parse_bounds_str(bounds_str)
    if not bounds:
        return False

    l, t, r, b = bounds
    with Image.open(screenshot_path) as img:
        width, height = img.size

        l = max(0, l + shrink_px)
        t = max(0, t + shrink_px)
        r = min(width, r - shrink_px)
        b = min(height, b - shrink_px)

        if r <= l or b <= t:
            return False

        cropped = img.crop((l, t, r, b))
        Path(crop_path).parent.mkdir(parents=True, exist_ok=True)
        cropped.save(crop_path)
        cropped.close()
    return True


def maybe_capture_focus_crop(
    client: A11yAdbClient,
    dev: str,
    row: dict,
    output_base_dir: str,
) -> dict:
    row["t_before_crop"] = round(time.monotonic() - float(row.get("_step_mono_start", time.monotonic())), 3) if row.get("_step_mono_start") else 0.0
    row["crop_image_path"] = ""
    row["crop_image_saved"] = False
    row["crop_bounds"] = str(row.get("focus_bounds", "") or "").strip()
    row["crop_source"] = "focus_bounds"
    row["crop_focus_confidence_low"] = False

    if not ENABLE_IMAGE_CROP:
        row["t_after_crop"] = row["t_before_crop"]
        return row

    bounds_str = str(row.get("focus_bounds", "") or "").strip()
    if not bounds_str:
        row["t_after_crop"] = row["t_before_crop"]
        return row

    tab_name = sanitize_filename(str(row.get("tab_name", "unknown")))
    step_index = row.get("step_index", -1)
    visible_label = sanitize_filename(str(row.get("visible_label", "") or "")[:40])

    crop_dir = Path(output_base_dir) / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)

    crop_path = crop_dir / f"{tab_name}_step_{step_index}_{visible_label}.png"

    capture_started = time.perf_counter()
    screenshot_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".png",
            prefix=f"tb_step_{step_index}_",
            delete=False,
        ) as temp_file:
            screenshot_path = temp_file.name
        capture_full_screenshot(client, dev, screenshot_path)
        ok = crop_image_by_bounds(
            screenshot_path=screenshot_path,
            bounds_str=bounds_str,
            crop_path=str(crop_path),
            shrink_px=2,
        )
        if ok:
            row["crop_image_path"] = str(crop_path)
            row["crop_image_saved"] = True
        row["screenshot_capture_elapsed"] = round(time.perf_counter() - capture_started, 3)
    except Exception as exc:
        log(f"[IMAGE] crop failed step={step_index}: {exc}")
    finally:
        if screenshot_path:
            try:
                Path(screenshot_path).unlink(missing_ok=True)
            except Exception:
                pass
        row["crop_elapsed_sec"] = round(time.perf_counter() - capture_started, 3)
        if row.get("_step_mono_start"):
            row["t_after_crop"] = round(time.monotonic() - float(row["_step_mono_start"]), 3)
        else:
            row["t_after_crop"] = row.get("t_before_crop", 0.0)
        payload_source = str(row.get("focus_payload_source", "") or "").lower()
        response_success = bool(row.get("get_focus_response_success", False))
        focus_view_id = str(row.get("focus_view_id", "") or "").strip()
        row["crop_focus_confidence_low"] = bool(
            (payload_source == "top_level" and not response_success)
            or (not focus_view_id and bool(row.get("crop_bounds", "")))
        )

    return row


def insert_images_to_excel(
    excel_path: str,
    image_col_name: str = "crop_image",
    sheet_name: str = "raw",
) -> None:
    if not ENABLE_IMAGE_INSERT_TO_EXCEL:
        return

    wb = load_workbook(excel_path)
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active

    headers = [cell.value for cell in ws[1]]
    if image_col_name not in headers or "crop_image_path" not in headers:
        wb.save(excel_path)
        return

    image_col_idx = headers.index(image_col_name) + 1
    path_col_idx = headers.index("crop_image_path") + 1

    col_letter = ws.cell(row=1, column=image_col_idx).column_letter

    for row_idx in range(2, ws.max_row + 1):
        path_value = ws.cell(row=row_idx, column=path_col_idx).value
        if not path_value:
            continue

        img_path = Path(str(path_value))
        if not img_path.exists():
            continue

        try:
            img = XLImage(str(img_path))
            img.width = 90
            img.height = 90
            ws.add_image(img, f"{col_letter}{row_idx}")
            ws.row_dimensions[row_idx].height = 72
        except Exception as exc:
            log(f"[EXCEL] image insert failed row={row_idx}: {exc}")

    ws.column_dimensions[col_letter].width = 16
    wb.save(excel_path)
