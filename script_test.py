import json
import time
from pathlib import Path

import pandas as pd

from talkback_lib import A11yAdbClient


DEV_SERIAL = "R3CX40QFDBP"

TAB_CONFIGS = [
    {
        "tab_name": "Home",
        "tab_type": "t",
        "anchor_name": "Location QR code",
        "anchor_type": "b",
        "max_steps": 30,
    },
    {
        "tab_name": "Devices",
        "tab_type": "b",
        "anchor_name": "Location QR code",
        "anchor_type": "b",
        "max_steps": 30,
    },
    {
        "tab_name": "Life",
        "tab_type": "b",
        "anchor_name": "Location QR code",
        "anchor_type": "b",
        "max_steps": 30,
    },
]


def to_json_text(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def open_tab_and_anchor(client: A11yAdbClient, dev: str, tab_cfg: dict) -> bool:
    print(f"\n[INFO] open tab: {tab_cfg['tab_name']}")

    ok = client.touch(
        dev=dev,
        name=tab_cfg["tab_name"],
        type_=tab_cfg["tab_type"],
        wait_=5,
    )
    if not ok:
        print(f"[ERROR] tab open failed: {tab_cfg['tab_name']}")
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
        print(f"[ERROR] anchor focus failed: {tab_cfg['anchor_name']}")
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


def collect_tab_rows(client: A11yAdbClient, dev: str, tab_cfg: dict) -> list[dict]:
    rows: list[dict] = []

    opened = open_tab_and_anchor(client, dev, tab_cfg)
    if not opened:
        rows.append(
            {
                "tab_name": tab_cfg["tab_name"],
                "step_index": -1,
                "status": "TAB_OPEN_FAILED",
                "stop_reason": "tab_or_anchor_failed",
            }
        )
        return rows

    anchor_row = client.collect_focus_step(
        dev=dev,
        step_index=0,
        move=False,
        wait_seconds=1.5,
    )
    anchor_row["tab_name"] = tab_cfg["tab_name"]
    anchor_row["status"] = "ANCHOR"
    anchor_row["stop_reason"] = ""
    rows.append(anchor_row)

    prev_visible_label = str(anchor_row.get("visible_label", "") or "").strip()
    fail_count = 0
    same_count = 0

    for step_idx in range(1, tab_cfg["max_steps"] + 1):
        row = client.collect_focus_step(
            dev=dev,
            step_index=step_idx,
            move=True,
            direction="next",
            wait_seconds=1.5,
        )
        row["tab_name"] = tab_cfg["tab_name"]
        row["status"] = "OK"
        row["stop_reason"] = ""

        stop, fail_count, same_count, reason = should_stop(
            row=row,
            prev_visible_label=prev_visible_label,
            fail_count=fail_count,
            same_count=same_count,
        )

        visible_label = str(row.get("visible_label", "") or "").strip()
        if visible_label:
            prev_visible_label = visible_label

        if stop:
            row["status"] = "END"
            row["stop_reason"] = reason
            rows.append(row)
            print(f"[INFO] stop tab={tab_cfg['tab_name']} step={step_idx} reason={reason}")
            break

        rows.append(row)

    return rows


def add_rule_compare(df: pd.DataFrame) -> pd.DataFrame:
    def compare_row(row) -> str:
        visible = str(row.get("normalized_visible_label", "") or "").strip()
        speech = str(row.get("normalized_announcement", "") or "").strip()

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


def save_excel(rows: list[dict], output_path: str) -> None:
    df = pd.DataFrame(rows)
    df = add_rule_compare(df)
    df = stringify_complex_columns(df)

    ordered_cols = [
        "tab_name",
        "step_index",
        "status",
        "stop_reason",
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
    print(f"[INFO] saved excel: {output_path}")


def main():
    client = A11yAdbClient(dev_serial=DEV_SERIAL)

    all_rows: list[dict] = []

    for tab_cfg in TAB_CONFIGS:
        tab_rows = collect_tab_rows(client, DEV_SERIAL, tab_cfg)
        all_rows.extend(tab_rows)

    save_excel(all_rows, "output/talkback_compare_result.xlsx")


if __name__ == "__main__":
    main()
