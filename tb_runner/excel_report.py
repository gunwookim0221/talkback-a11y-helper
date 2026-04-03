from pathlib import Path

import pandas as pd

from tb_runner.image_utils import insert_images_to_excel
from tb_runner.logging_utils import log
from tb_runner.utils import to_json_text


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


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _extract_status_tokens(text: object) -> tuple[str, list[str]]:
    normalized = _normalize_text(text)
    if not normalized:
        return "", []

    status_tokens: list[str] = []
    main_parts: list[str] = []
    for raw_part in normalized.split(","):
        part = " ".join(raw_part.strip().split())
        if not part:
            continue
        is_status = (
            "new content available" in part
            or "새 콘텐츠 사용 가능" in part
            or part in {"selected", "선택됨"}
            or ("tab " in part and " of " in part)
            or ("탭" in part and "중" in part and "번째" in part)
            or "expanded" in part
            or "collapsed" in part
            or "battery" in part
            or "percent" in part
        )
        if is_status:
            status_tokens.append(part)
        else:
            main_parts.append(part)
    return ", ".join(main_parts), status_tokens


def add_status_columns(df: pd.DataFrame) -> pd.DataFrame:
    def _resolve_source_series(priorities: list[str]) -> pd.Series:
        for col in priorities:
            if col in df.columns:
                return df[col]
        return pd.Series([""] * len(df), index=df.index, dtype=object)

    speech_series = _resolve_source_series(
        ["merged_announcement", "speech", "announcement", "normalized_announcement"]
    )
    visible_series = _resolve_source_series(
        ["visible_label", "normalized_visible_label", "text"]
    )

    speech_split = speech_series.apply(_extract_status_tokens)
    visible_split = visible_series.apply(_extract_status_tokens)

    df["speech_main"] = speech_split.apply(lambda item: item[0])
    df["speech_status_tokens"] = speech_split.apply(lambda item: item[1])
    df["visible_main"] = visible_split.apply(lambda item: item[0])
    df["visible_status_tokens"] = visible_split.apply(lambda item: item[1])
    return df


def make_filtered_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    def _bool_series(col: str) -> pd.Series:
        if col not in raw_df.columns:
            return pd.Series([False] * len(raw_df), index=raw_df.index, dtype=bool)
        return raw_df[col].fillna(False).astype(bool)

    is_noise = _bool_series("is_noise_step")
    is_duplicate = _bool_series("is_duplicate_step")
    is_recent_duplicate = _bool_series("is_recent_duplicate_step")
    keep_mask = ~(is_noise | is_duplicate | is_recent_duplicate)
    return raw_df[keep_mask].copy()


def make_summary_df(raw_df: pd.DataFrame, filtered_df: pd.DataFrame) -> pd.DataFrame:
    def _bool_series(col: str) -> pd.Series:
        if col not in raw_df.columns:
            return pd.Series([False] * len(raw_df), index=raw_df.index, dtype=bool)
        return raw_df[col].fillna(False).astype(bool)

    if "mismatch_reasons" in raw_df.columns:
        mismatch_count = int(
            raw_df["mismatch_reasons"].apply(
                lambda x: bool(x) if isinstance(x, list) else bool(str(x or "").strip())
            ).sum()
        )
    else:
        mismatch_count = int((raw_df.get("rule_compare", pd.Series(index=raw_df.index, dtype=str)) == "DIFF").sum())
    rows: list[dict[str, object]] = [
        {"section": "overall", "metric": "total_rows", "value": int(len(raw_df))},
        {"section": "overall", "metric": "raw_rows", "value": int(len(raw_df))},
        {"section": "overall", "metric": "filtered_rows", "value": int(len(filtered_df))},
        {"section": "overall", "metric": "noise_count", "value": int(_bool_series("is_noise_step").sum())},
        {"section": "overall", "metric": "duplicate_count", "value": int(_bool_series("is_duplicate_step").sum())},
        {"section": "overall", "metric": "recent_duplicate_count", "value": int(_bool_series("is_recent_duplicate_step").sum())},
        {"section": "overall", "metric": "mismatch_count", "value": mismatch_count},
    ]

    if "scenario_id" in raw_df.columns:
        scenario_df = (
            raw_df.groupby("scenario_id", dropna=False)
            .size()
            .reset_index(name="value")
            .rename(columns={"scenario_id": "metric"})
        )
        scenario_df["section"] = "scenario_id"
        rows.extend(scenario_df[["section", "metric", "value"]].to_dict("records"))

    return pd.DataFrame(rows)


def save_excel(rows: list[dict], output_path: str, with_images: bool = True) -> None:
    df = pd.DataFrame(rows)
    if df.empty:
        log("[SAVE] skip: no rows")
        return

    df = add_rule_compare(df)
    df = add_status_columns(df)
    raw_df = df.copy()
    filtered_df = make_filtered_df(raw_df)
    summary_df = make_summary_df(raw_df, filtered_df)

    log("[SAVE] writing sheets raw/filtered/summary")
    log(f"[SAVE] filtered rows={len(filtered_df)}, raw rows={len(raw_df)}")

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
        "fingerprint",
        "is_duplicate_step",
        "is_recent_duplicate_step",
        "recent_duplicate_distance",
        "recent_duplicate_of_step",
        "is_noise_step",
        "noise_reason",
        "speech_main",
        "speech_status_tokens",
        "visible_main",
        "visible_status_tokens",
    ]

    def _reorder_columns(frame: pd.DataFrame) -> pd.DataFrame:
        existing_cols = [c for c in ordered_cols if c in frame.columns]
        remaining_cols = [c for c in frame.columns if c not in existing_cols]
        return frame[existing_cols + remaining_cols]

    raw_df = _reorder_columns(raw_df)
    filtered_df = _reorder_columns(filtered_df)
    raw_df = stringify_complex_columns(raw_df)
    filtered_df = stringify_complex_columns(filtered_df)
    summary_df = stringify_complex_columns(summary_df)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path) as writer:
        raw_df.to_excel(writer, sheet_name="raw", index=False)
        filtered_df.to_excel(writer, sheet_name="filtered", index=False)
        summary_df.to_excel(writer, sheet_name="summary", index=False)

    if with_images and "crop_image" in raw_df.columns:
        insert_images_to_excel(output_path, image_col_name="crop_image")

    log(f"[SAVE] saved excel: {output_path} rows={len(raw_df)} with_images={with_images}")
