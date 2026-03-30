import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image

from talkback_lib import A11yAdbClient


DEV_SERIAL = "R3CX40QFDBP"
SCRIPT_VERSION = "1.3.0"

OVERLAY_ENTRY_ALLOWLIST = [
    {
        "resource_id": "com.samsung.android.oneconnect:id/add_menu_button",
        "label": "Add",
    },
    {
        "resource_id": "com.samsung.android.oneconnect:id/more_menu_button",
        "label": "More options",
    },
]

OVERLAY_MAX_STEPS = 12

TAB_CONFIGS = [
    {
        "tab_name": ".*Home.*",
        "tab_type": "b",
        "anchor_name": ".*Location QR code.*",
        "anchor_type": "b",
        "max_steps": 30,
    },
]

ENABLE_IMAGE_CROP = True
ENABLE_IMAGE_INSERT_TO_EXCEL = True
IMAGE_DIR = "output/crops"


def now_str() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{now_str()}] {msg}")


def generate_output_path() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"output/talkback_compare_{timestamp}.xlsx"


def to_json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def parse_bounds_str(bounds_str: str) -> tuple[int, int, int, int] | None:
    if not bounds_str:
        return None
    try:
        parts = [int(x.strip()) for x in bounds_str.split(",")]
        if len(parts) != 4:
            return None
        l, t, r, b = parts
        if r <= l or b <= t:
            return None
        return l, t, r, b
    except Exception:
        return None


def sanitize_filename(value: str) -> str:
    keep = []
    for ch in value:
        if ch.isalnum() or ch in ("_", "-", "."):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep).strip("_") or "item"


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
    img = Image.open(screenshot_path)
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
    return True


def maybe_capture_focus_crop(
    client: A11yAdbClient,
    dev: str,
    row: dict,
    output_base_dir: str,
) -> dict:
    row["crop_image_path"] = ""
    row["crop_image_saved"] = False

    if not ENABLE_IMAGE_CROP:
        return row

    bounds_str = str(row.get("focus_bounds", "") or "").strip()
    if not bounds_str:
        return row

    tab_name = sanitize_filename(str(row.get("tab_name", "unknown")))
    step_index = row.get("step_index", -1)
    visible_label = sanitize_filename(str(row.get("visible_label", "") or "")[:40])

    screenshot_dir = Path(output_base_dir) / "screens"
    crop_dir = Path(output_base_dir) / "crops"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)

    screenshot_path = screenshot_dir / f"{tab_name}_step_{step_index}.png"
    crop_path = crop_dir / f"{tab_name}_step_{step_index}_{visible_label}.png"

    try:
        capture_full_screenshot(client, dev, str(screenshot_path))
        ok = crop_image_by_bounds(
            screenshot_path=str(screenshot_path),
            bounds_str=bounds_str,
            crop_path=str(crop_path),
            shrink_px=2,
        )
        if ok:
            row["crop_image_path"] = str(crop_path)
            row["crop_image_saved"] = True
    except Exception as exc:
        log(f"[IMAGE] crop failed step={step_index}: {exc}")

    return row


def add_rule_compare(df: pd.DataFrame) -> pd.DataFrame:
    def compare_row(row) -> str:
        visible = str(row.get("normalized_visible_label", "") or "").strip()
        speech = str(row.get("normalized_announcement", "") or "").strip()

        if row.get("status") == "ANCHOR":
            return "SKIP"

        if not visible and not speech:
            return "EMPTY"
        if visible == speech:
            return "EXACT"
        if visible and speech and (visible in speech or speech in visible):
            return "PARTIAL"
        return "DIFF"

    df["rule_compare"] = df.apply(compare_row, axis=1)
    return df


def stringify_complex_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        df[col] = df[col].apply(
            lambda x: to_json_text(x) if isinstance(x, (list, dict)) else x
        )
    return df


def insert_images_to_excel(excel_path: str, image_col_name: str = "crop_image") -> None:
    if not ENABLE_IMAGE_INSERT_TO_EXCEL:
        return

    wb = load_workbook(excel_path)
    ws = wb.active

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


def save_excel(rows: list[dict], output_path: str) -> None:
    df = pd.DataFrame(rows)
    if df.empty:
        log("[SAVE] skip: no rows")
        return

    df = add_rule_compare(df)
    df = stringify_complex_columns(df)

    ordered_cols = [
        "tab_name",
        "context_type",
        "parent_step_index",
        "overlay_entry_label",
        "overlay_recovery_status",
        "step_index",
        "status",
        "stop_reason",
        "step_elapsed_sec",
        "move_result",
        "visible_label",
        "normalized_visible_label",
        "merged_announcement",
        "normalized_announcement",
        "rule_compare",
        "focus_text",
        "focus_content_description",
        "focus_view_id",
        "focus_bounds",
        "crop_image",
        "crop_image_path",
        "crop_image_saved",
        "partial_announcements",
        "last_announcements",
        "last_merged_announcement",
        "focus_node",
        "dump_tree_nodes",
    ]

    existing_cols = [c for c in ordered_cols if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in existing_cols]
    df = df[existing_cols + remaining_cols]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False)

    if "crop_image" in df.columns:
        insert_images_to_excel(output_path, image_col_name="crop_image")

    log(f"[SAVE] saved excel: {output_path} rows={len(df)}")


def should_expand_overlay(step: dict[str, Any]) -> bool:
    focus_view_id = str(step.get("focus_view_id", "") or "").strip()
    normalized_visible_label = str(step.get("normalized_visible_label", "") or "").strip()

    for entry in OVERLAY_ENTRY_ALLOWLIST:
        allowed_view_id = str(entry.get("resource_id", "") or "").strip()
        if allowed_view_id and focus_view_id == allowed_view_id:
            return True

    for entry in OVERLAY_ENTRY_ALLOWLIST:
        allowed_label = str(entry.get("label", "") or "").strip().lower()
        if allowed_label and normalized_visible_label == allowed_label.lower():
            return True

    return False


def make_overlay_entry_fingerprint(tab_name: str, step: dict[str, Any]) -> str:
    focus_view_id = str(step.get("focus_view_id", "") or "").strip()
    normalized_visible_label = str(step.get("normalized_visible_label", "") or "").strip()
    return f"{tab_name}|{focus_view_id}|{normalized_visible_label}"


def expand_overlay(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    entry_step: dict[str, Any],
    rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    output_path: str,
    output_base_dir: str,
) -> list[dict[str, Any]]:
    overlay_rows: list[dict[str, Any]] = []
    entry_label = str(entry_step.get("visible_label", "") or "").strip()
    entry_view_id = str(entry_step.get("focus_view_id", "") or "").strip()

    clicked = False
    if entry_view_id:
        clicked = client.touch(
            dev=dev,
            name=f"^{re.escape(entry_view_id)}$",
            type_="r",
            wait_=3,
        )
    elif entry_label:
        clicked = client.touch(
            dev=dev,
            name=f"^{re.escape(entry_label)}$",
            type_="a",
            wait_=3,
        )

    recovery_status = "not_attempted"
    if not clicked:
        recovery_status = "entry_click_failed"
        return overlay_rows

    time.sleep(1.0)

    parent_step_index = entry_step.get("step_index")
    overlay_prev_visible_label = ""
    overlay_fail_count = 0
    overlay_same_count = 0
    for overlay_step_idx in range(1, OVERLAY_MAX_STEPS + 1):
        overlay_row = client.collect_focus_step(
            dev=dev,
            step_index=overlay_step_idx,
            move=True,
            direction="next",
            wait_seconds=1.0,
        )
        overlay_row["tab_name"] = tab_cfg["tab_name"]
        overlay_row["context_type"] = "overlay"
        overlay_row["parent_step_index"] = parent_step_index
        overlay_row["overlay_entry_label"] = entry_label
        overlay_row["overlay_recovery_status"] = ""
        overlay_row["status"] = "OK"
        overlay_row["stop_reason"] = ""
        overlay_row["crop_image"] = "IMAGE"
        overlay_row = maybe_capture_focus_crop(client, dev, overlay_row, output_base_dir)

        overlay_rows.append(overlay_row)
        rows.append(overlay_row)
        all_rows.append(overlay_row)
        save_excel(all_rows, output_path)

        should_end_overlay, overlay_fail_count, overlay_same_count, overlay_reason = should_stop(
            row=overlay_row,
            prev_visible_label=overlay_prev_visible_label,
            fail_count=overlay_fail_count,
            same_count=overlay_same_count,
        )
        overlay_visible_label = str(overlay_row.get("visible_label", "") or "").strip()
        if overlay_visible_label:
            overlay_prev_visible_label = overlay_visible_label
        if should_end_overlay:
            overlay_row["status"] = "END"
            overlay_row["stop_reason"] = overlay_reason
            break

    recovery_anchor = str(entry_step.get("normalized_visible_label", "") or "").strip()
    scenario_anchor = str(tab_cfg.get("anchor_name", "") or "").strip()
    expected_anchor: str | None = recovery_anchor or scenario_anchor or None

    recovery_result = client.press_back_and_recover_focus(
        dev=dev,
        expected_parent_anchor=expected_anchor,
        wait_seconds=1.0,
        retry=1,
    )
    recovery_status = str(recovery_result.get("status", "") or "")
    if recovery_status != "ok" and scenario_anchor:
        select_ok = client.select(
            dev=dev,
            name=scenario_anchor,
            type_=str(tab_cfg.get("anchor_type", "a") or "a"),
            wait_=3,
        )
        recovery_status = "ok_select_fallback" if select_ok else f"{recovery_status}_select_fallback_failed"

    if overlay_rows:
        overlay_rows[-1]["overlay_recovery_status"] = recovery_status
    return overlay_rows


def open_tab_and_anchor(client: A11yAdbClient, dev: str, tab_cfg: dict) -> bool:
    ok = client.touch(
        dev=dev,
        name=tab_cfg["tab_name"],
        type_=tab_cfg["tab_type"],
        wait_=5,
    )
    if not ok:
        return False

    time.sleep(1.0)
    client.reset_focus_history(dev)
    time.sleep(0.5)

    ok = client.select(
        dev=dev,
        name=tab_cfg["anchor_name"],
        type_=tab_cfg["anchor_type"],
        wait_=8,
    )
    if not ok:
        return False

    time.sleep(1.0)
    return True


def should_stop(
    row: dict,
    prev_visible_label: str,
    fail_count: int,
    same_count: int,
) -> tuple[bool, int, int, str]:
    move_result = str(row.get("move_result", "") or "")
    visible_label = str(row.get("visible_label", "") or "").strip()
    merged_announcement = str(row.get("merged_announcement", "") or "").strip()

    reason = ""

    if move_result == "failed":
        fail_count += 1
    else:
        fail_count = 0

    if visible_label and visible_label == prev_visible_label:
        same_count += 1
    else:
        same_count = 0

    if fail_count >= 2:
        reason = "move_failed_twice"
        return True, fail_count, same_count, reason

    if same_count >= 3:
        reason = "same_visible_repeated"
        return True, fail_count, same_count, reason

    if not visible_label and not merged_announcement:
        reason = "empty_visible_and_speech"
        return True, fail_count, same_count, reason

    return False, fail_count, same_count, reason


def collect_tab_rows(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict,
    all_rows: list[dict],
    output_path: str,
    output_base_dir: str,
) -> list[dict]:
    rows: list[dict] = []

    opened = open_tab_and_anchor(client, dev, tab_cfg)
    if not opened:
        row = {
            "tab_name": tab_cfg["tab_name"],
            "step_index": -1,
            "status": "TAB_OPEN_FAILED",
            "stop_reason": "tab_or_anchor_failed",
            "crop_image": "",
            "crop_image_path": "",
            "crop_image_saved": False,
        }
        rows.append(row)
        all_rows.append(row)
        save_excel(all_rows, output_path)
        return rows

    anchor_start = time.perf_counter()
    anchor_row = client.collect_focus_step(
        dev=dev,
        step_index=0,
        move=False,
        wait_seconds=1.5,
    )
    anchor_elapsed = time.perf_counter() - anchor_start

    anchor_row["tab_name"] = tab_cfg["tab_name"]
    anchor_row["context_type"] = "main"
    anchor_row["parent_step_index"] = ""
    anchor_row["overlay_entry_label"] = ""
    anchor_row["overlay_recovery_status"] = ""
    anchor_row["status"] = "ANCHOR"
    anchor_row["stop_reason"] = ""
    anchor_row["step_elapsed_sec"] = round(anchor_elapsed, 3)
    anchor_row["crop_image"] = "IMAGE"
    anchor_row = maybe_capture_focus_crop(client, dev, anchor_row, output_base_dir)

    rows.append(anchor_row)
    all_rows.append(anchor_row)
    save_excel(all_rows, output_path)

    prev_visible_label = str(anchor_row.get("visible_label", "") or "").strip()
    fail_count = 0
    same_count = 0
    expanded_overlay_entries: set[str] = set()

    for step_idx in range(1, tab_cfg["max_steps"] + 1):
        log(f"[STEP] START tab='{tab_cfg['tab_name']}' step={step_idx}")
        step_start = time.perf_counter()

        row = client.collect_focus_step(
            dev=dev,
            step_index=step_idx,
            move=True,
            direction="next",
            wait_seconds=1.5,
        )
        step_elapsed = time.perf_counter() - step_start

        row["tab_name"] = tab_cfg["tab_name"]
        row["context_type"] = "main"
        row["parent_step_index"] = ""
        row["overlay_entry_label"] = ""
        row["overlay_recovery_status"] = ""
        row["status"] = "OK"
        row["stop_reason"] = ""
        row["step_elapsed_sec"] = round(step_elapsed, 3)
        row["crop_image"] = "IMAGE"
        row = maybe_capture_focus_crop(client, dev, row, output_base_dir)

        move_result = str(row.get("move_result", "") or "")
        visible_label = str(row.get("visible_label", "") or "").strip()
        merged_announcement = str(row.get("merged_announcement", "") or "").strip()

        log(
            f"[STEP] END tab='{tab_cfg['tab_name']}' step={step_idx} "
            f"elapsed={step_elapsed:.2f}s move_result='{move_result}' "
            f"visible='{visible_label}' speech='{merged_announcement}' "
            f"crop='{row.get('crop_image_path', '')}'"
        )

        stop, fail_count, same_count, reason = should_stop(
            row=row,
            prev_visible_label=prev_visible_label,
            fail_count=fail_count,
            same_count=same_count,
        )

        if visible_label:
            prev_visible_label = visible_label

        if stop:
            row["status"] = "END"
            row["stop_reason"] = reason

        rows.append(row)
        all_rows.append(row)
        save_excel(all_rows, output_path)

        if should_expand_overlay(row):
            fingerprint = make_overlay_entry_fingerprint(tab_cfg["tab_name"], row)
            if fingerprint not in expanded_overlay_entries:
                log(
                    f"[OVERLAY] expand entry step={row.get('step_index')} "
                    f"view_id='{row.get('focus_view_id', '')}' label='{row.get('visible_label', '')}'"
                )
                expand_overlay(
                    client=client,
                    dev=dev,
                    tab_cfg=tab_cfg,
                    entry_step=row,
                    rows=rows,
                    all_rows=all_rows,
                    output_path=output_path,
                    output_base_dir=output_base_dir,
                )
                expanded_overlay_entries.add(fingerprint)
            else:
                log(f"[OVERLAY] skip already expanded entry fingerprint='{fingerprint}'")

        if stop:
            log(f"[INFO] stop tab={tab_cfg['tab_name']} step={step_idx} reason={reason}")
            break

    return rows


def main():
    log(f"[MAIN] script start (version={SCRIPT_VERSION})")
    client = A11yAdbClient(dev_serial=DEV_SERIAL)

    all_rows: list[dict] = []
    output_path = generate_output_path()
    output_base_dir = str(Path(output_path).with_suffix(""))

    log(f"[MAIN] output file: {output_path}")
    log(f"[MAIN] image dir base: {output_base_dir}")

    try:
        for tab_cfg in TAB_CONFIGS:
            collect_tab_rows(
                client,
                DEV_SERIAL,
                tab_cfg,
                all_rows,
                output_path,
                output_base_dir,
            )

    except Exception as exc:
        log(f"[FATAL] script interrupted: {exc}")
        save_excel(all_rows, output_path)
        raise

    finally:
        save_excel(all_rows, output_path)
        log("[MAIN] final save complete")

    log("[MAIN] script end")


if __name__ == "__main__":
    main()
    
