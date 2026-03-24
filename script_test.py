import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from talkback_lib import A11yAdbClient


DEV_SERIAL = "R3CX40QFDBP"

# 처음에는 regex + b 로 시작하는 게 안전함
TAB_CONFIGS = [
    {
        "tab_name": ".*Home.*",
        "tab_type": "b",
        "anchor_name": "Location QR code",
        "anchor_type": "b",
        "max_steps": 30,
    },
    {
        "tab_name": ".*Devices.*",
        "tab_type": "b",
        "anchor_name": "Location QR code",
        "anchor_type": "b",
        "max_steps": 30,
    },
    {
        "tab_name": ".*Life.*",
        "tab_type": "b",
        "anchor_name": "Location QR code",
        "anchor_type": "b",
        "max_steps": 30,
    },
]


def now_str() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{now_str()}] {msg}")


def to_json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def collect_text_candidates_from_tree(nodes: list[dict], max_count: int = 20) -> list[str]:
    results: list[str] = []

    def visit(node: Any) -> None:
        if len(results) >= max_count:
            return
        if not isinstance(node, dict):
            return

        for key in ("text", "contentDescription", "talkback", "content_desc", "label"):
            value = node.get(key)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped and stripped not in results:
                    results.append(stripped)
                    if len(results) >= max_count:
                        return

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                visit(child)
                if len(results) >= max_count:
                    return

    for item in nodes:
        visit(item)
        if len(results) >= max_count:
            break

    return results


def debug_focus(client: A11yAdbClient, dev: str, title: str) -> None:
    try:
        focus = client.get_focus(dev=dev, wait_seconds=1.0)
        visible_label = client.extract_visible_label_from_focus(focus)
        view_id = focus.get("viewIdResourceName", "") if isinstance(focus, dict) else ""
        bounds = client._normalize_bounds(focus) if isinstance(focus, dict) else ""
        log(
            f"[FOCUS:{title}] label='{visible_label}' "
            f"view_id='{view_id}' bounds='{bounds}' raw={to_json_text(focus)}"
        )
    except Exception as exc:
        log(f"[FOCUS:{title}] failed: {exc}")


def debug_screen_summary(client: A11yAdbClient, dev: str, title: str) -> None:
    try:
        tree = client.dump_tree(dev=dev, wait_seconds=2.0)
        texts = collect_text_candidates_from_tree(tree, max_count=20)
        log(f"[SCREEN:{title}] node_count={len(tree)} text_samples={texts}")
    except Exception as exc:
        log(f"[SCREEN:{title}] failed: {exc}")


def debug_find_tab_before_touch(client: A11yAdbClient, dev: str, tab_cfg: dict) -> None:
    log(
        f"[TAB-CHECK] searching tab "
        f"name='{tab_cfg['tab_name']}' type='{tab_cfg['tab_type']}'"
    )
    try:
        found = client.isin(
            dev=dev,
            name=tab_cfg["tab_name"],
            type_=tab_cfg["tab_type"],
            wait_=2,
        )
        log(f"[TAB-CHECK] result={found}")
    except Exception as exc:
        log(f"[TAB-CHECK] failed: {exc}")


def open_tab_and_anchor(client: A11yAdbClient, dev: str, tab_cfg: dict) -> bool:
    log("=" * 80)
    log(f"[TAB-OPEN] start tab='{tab_cfg['tab_name']}'")

    debug_focus(client, dev, "before_tab_touch")
    debug_screen_summary(client, dev, "before_tab_touch")
    debug_find_tab_before_touch(client, dev, tab_cfg)

    start_touch = time.perf_counter()
    ok = client.touch(
        dev=dev,
        name=tab_cfg["tab_name"],
        type_=tab_cfg["tab_type"],
        wait_=5,
    )
    touch_elapsed = time.perf_counter() - start_touch
    log(f"[TAB-OPEN] touch_result={ok} elapsed={touch_elapsed:.2f}s")

    debug_focus(client, dev, "after_tab_touch")
    debug_screen_summary(client, dev, "after_tab_touch")

    if not ok:
        log(f"[ERROR] tab open failed: {tab_cfg['tab_name']}")
        return False

    time.sleep(1.0)
    log("[TAB-OPEN] slept 1.0s after tab touch")

    client.reset_focus_history(dev)
    log("[TAB-OPEN] focus history reset")
    time.sleep(0.5)
    log("[TAB-OPEN] slept 0.5s after reset")

    debug_focus(client, dev, "before_anchor_select")
    debug_screen_summary(client, dev, "before_anchor_select")

    start_anchor = time.perf_counter()
    ok = client.select(
        dev=dev,
        name=tab_cfg["anchor_name"],
        type_=tab_cfg["anchor_type"],
        wait_=8,
    )
    anchor_elapsed = time.perf_counter() - start_anchor
    log(
        f"[ANCHOR] select_result={ok} "
        f"name='{tab_cfg['anchor_name']}' type='{tab_cfg['anchor_type']}' "
        f"elapsed={anchor_elapsed:.2f}s"
    )

    debug_focus(client, dev, "after_anchor_select")
    debug_screen_summary(client, dev, "after_anchor_select")

    if not ok:
        log(f"[ERROR] anchor focus failed: {tab_cfg['anchor_name']}")
        return False

    time.sleep(1.0)
    log("[ANCHOR] slept 1.0s after anchor select")
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

    log(f"[TAB-TRAVERSE] collecting anchor row for tab='{tab_cfg['tab_name']}'")
    anchor_start = time.perf_counter()
    anchor_row = client.collect_focus_step(
        dev=dev,
        step_index=0,
        move=False,
        wait_seconds=1.5,
    )
    anchor_elapsed = time.perf_counter() - anchor_start
    anchor_row["tab_name"] = tab_cfg["tab_name"]
    anchor_row["status"] = "ANCHOR"
    anchor_row["stop_reason"] = ""
    anchor_row["step_elapsed_sec"] = round(anchor_elapsed, 3)
    rows.append(anchor_row)

    log(
        f"[ANCHOR-ROW] elapsed={anchor_elapsed:.2f}s "
        f"visible='{anchor_row.get('visible_label', '')}' "
        f"speech='{anchor_row.get('merged_announcement', '')}' "
        f"move_result='{anchor_row.get('move_result', '')}'"
    )

    prev_visible_label = str(anchor_row.get("visible_label", "") or "").strip()
    fail_count = 0
    same_count = 0

    for step_idx in range(1, tab_cfg["max_steps"] + 1):
        log("-" * 80)
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
        row["status"] = "OK"
        row["stop_reason"] = ""
        row["step_elapsed_sec"] = round(step_elapsed, 3)

        move_result = str(row.get("move_result", "") or "")
        visible_label = str(row.get("visible_label", "") or "").strip()
        merged_announcement = str(row.get("merged_announcement", "") or "").strip()

        log(
            f"[STEP] END tab='{tab_cfg['tab_name']}' step={step_idx} "
            f"elapsed={step_elapsed:.2f}s move_result='{move_result}' "
            f"visible='{visible_label}' speech='{merged_announcement}'"
        )

        stop, fail_count, same_count, reason = should_stop(
            row=row,
            prev_visible_label=prev_visible_label,
            fail_count=fail_count,
            same_count=same_count,
        )

        log(
            f"[STEP] counters fail_count={fail_count} "
            f"same_count={same_count} stop={stop} reason='{reason}'"
        )

        if visible_label:
            prev_visible_label = visible_label

        if stop:
            row["status"] = "END"
            row["stop_reason"] = reason
            rows.append(row)
            log(f"[INFO] stop tab={tab_cfg['tab_name']} step={step_idx} reason={reason}")
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
    log(f"[INFO] saved excel: {output_path}")


def main():
    log("[MAIN] script start")
    client = A11yAdbClient(dev_serial=DEV_SERIAL)

    all_rows: list[dict] = []

    for tab_cfg in TAB_CONFIGS:
        log(f"[MAIN] processing tab={tab_cfg['tab_name']}")
        tab_rows = collect_tab_rows(client, DEV_SERIAL, tab_cfg)
        all_rows.extend(tab_rows)

    save_excel(all_rows, "output/talkback_compare_result.xlsx")
    log("[MAIN] script end")


if __name__ == "__main__":
    main()
