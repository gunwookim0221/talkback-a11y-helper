from pathlib import Path
import re

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


def _normalize_compare_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("\n", " ")
    text = re.sub(r"[\.,!?;:\-_/()\[\]{}\"'`]+", " ", text)
    return " ".join(text.split())


def make_result_df(filtered_df: pd.DataFrame) -> pd.DataFrame:
    if filtered_df.empty:
        return pd.DataFrame(
            columns=[
                "scenario_id",
                "tab",
                "step",
                "context_type",
                "visible",
                "speech",
                "move_result",
                "resource_id",
                "bounds",
                "fallback_used",
                "step_dump_used",
                "req_id",
                "timing_move",
                "timing_get_focus",
                "timing_total",
                "traversal_result",
                "speech_match_result",
                "focus_confidence",
                "final_result",
                "failure_reason",
                "review_note",
                "crop_image_path",
            ]
        )

    result = pd.DataFrame(index=filtered_df.index)

    def _pick_col(target: str, candidates: list[str], default: object = "") -> None:
        for col in candidates:
            if col in filtered_df.columns:
                result[target] = filtered_df[col]
                return
        result[target] = default

    _pick_col("scenario_id", ["scenario_id"])
    _pick_col("tab", ["tab", "tab_name"])
    _pick_col("step", ["step", "step_index"])
    _pick_col("context_type", ["context_type"])

    _pick_col("visible", ["visible_label", "normalized_visible_label", "text"])
    _pick_col(
        "speech",
        ["merged_announcement", "speech", "announcement", "normalized_announcement"],
    )
    _pick_col("move_result", ["move_result"])
    _pick_col("resource_id", ["focus_view_id", "resource_id"])
    _pick_col("bounds", ["focus_bounds", "bounds"])
    _pick_col("fallback_used", ["fallback_used"], default=False)
    _pick_col("step_dump_used", ["step_dump_used"], default=False)
    _pick_col("req_id", ["req_id"])

    _pick_col("timing_move", ["timing_move", "move_elapsed_sec"])
    _pick_col("timing_get_focus", ["timing_get_focus", "step_elapsed_sec"])
    _pick_col("timing_total", ["timing_total", "step_elapsed_sec"])
    _pick_col("crop_image_path", ["crop_image_path", "crop_path", "result_crop"])

    result["move_result"] = result["move_result"].fillna("").astype(str).str.lower().str.strip()
    result["fallback_used"] = result["fallback_used"].fillna(False).astype(bool)
    result["step_dump_used"] = result["step_dump_used"].fillna(False).astype(bool)

    result["_norm_visible"] = result["visible"].apply(_normalize_compare_text)
    result["_norm_speech"] = result["speech"].apply(_normalize_compare_text)
    if "mismatch_reasons" in filtered_df.columns:
        result["_mismatch_reasons"] = filtered_df["mismatch_reasons"]
    else:
        result["_mismatch_reasons"] = ""

    def _same_topic(a: str, b: str) -> bool:
        if not a or not b:
            return False
        a_tokens = [tok for tok in a.split(" ") if len(tok) > 1]
        b_tokens = [tok for tok in b.split(" ") if len(tok) > 1]
        if not a_tokens or not b_tokens:
            return False
        a_set = set(a_tokens)
        b_set = set(b_tokens)
        return len(a_set & b_set) >= max(1, min(len(a_set), len(b_set)) // 2)

    def _speech_match(row) -> str:
        visible = row["_norm_visible"]
        speech = row["_norm_speech"]
        mismatch_reasons = str(row.get("_mismatch_reasons", "") or "")
        if "speech_visible_diverged" in mismatch_reasons:
            return "FAIL_MISMATCH"
        if visible and speech and visible == speech:
            return "PASS_EXACT"
        if visible and speech and (visible in speech or speech in visible):
            if _same_topic(visible, speech):
                length_gap = abs(len(visible.split(" ")) - len(speech.split(" ")))
                return "WARN_CONTEXT_ADDED" if length_gap >= 2 else "PASS_CONTAINS"
            return "PASS_CONTAINS"
        if _same_topic(visible, speech):
            return "WARN_CONTEXT_ADDED"
        return "FAIL_MISMATCH"

    result["speech_match_result"] = result.apply(_speech_match, axis=1)

    group_keys = [k for k in ["scenario_id", "tab", "context_type"] if k in result.columns]
    if not group_keys:
        group_keys = [result.index]

    for _, group in result.groupby(group_keys, dropna=False, sort=False):
        group_idx = group.index.tolist()
        moved_idx = [idx for idx in group_idx if result.at[idx, "move_result"] == "moved"]
        last_moved_idx = moved_idx[-1] if moved_idx else None

        traversal = []
        failure = []
        for idx in group_idx:
            move_result = result.at[idx, "move_result"]
            is_followup_noise = False
            if last_moved_idx is not None and idx > last_moved_idx:
                same_visible = result.at[idx, "_norm_visible"] == result.at[last_moved_idx, "_norm_visible"]
                same_speech = result.at[idx, "_norm_speech"] == result.at[last_moved_idx, "_norm_speech"]
                is_repeat_stop = "repeat_no_progress" in str(result.at[idx, "req_id"] or "")
                is_followup_noise = move_result == "failed" and (same_visible or same_speech or is_repeat_stop)

            if idx == last_moved_idx and any(i > last_moved_idx for i in group_idx if result.at[i, "move_result"] == "failed"):
                traversal.append("WARN_TERMINAL_BY_REPEAT_STOP")
                failure.append("terminal_not_handled")
            elif move_result == "moved":
                traversal.append("PASS_MOVED")
                failure.append("")
            elif is_followup_noise:
                traversal.append("WARN_TERMINAL_BY_REPEAT_STOP")
                failure.append("terminal_followup_noise")
            elif move_result == "failed":
                if moved_idx:
                    traversal.append("FAIL_STUCK")
                    failure.append("repeat_no_progress")
                else:
                    traversal.append("FAIL_MOVE")
                    failure.append("move_failed")
            else:
                traversal.append("FAIL_MOVE")
                failure.append("move_failed")

        result.loc[group_idx, "traversal_result"] = traversal
        result.loc[group_idx, "failure_reason"] = failure

    def _focus_confidence(row) -> str:
        if row["fallback_used"] or row["step_dump_used"]:
            return "LOW"
        if row["speech_match_result"] in {"PASS_EXACT", "PASS_CONTAINS"} and row["traversal_result"] == "PASS_MOVED":
            return "HIGH"
        if row["speech_match_result"] == "FAIL_MISMATCH" or row["traversal_result"].startswith("FAIL"):
            return "LOW"
        return "MEDIUM"

    result["focus_confidence"] = result.apply(_focus_confidence, axis=1)

    def _final_result(row) -> str:
        if row["traversal_result"] in {"FAIL_MOVE", "FAIL_STUCK"} or row["speech_match_result"] == "FAIL_MISMATCH":
            return "FAIL"
        if (
            row["traversal_result"] == "WARN_TERMINAL_BY_REPEAT_STOP"
            or row["speech_match_result"] == "WARN_CONTEXT_ADDED"
            or row["focus_confidence"] == "LOW"
        ):
            return "WARN"
        if row["traversal_result"] == "PASS_MOVED" and row["speech_match_result"] in {"PASS_EXACT", "PASS_CONTAINS"}:
            return "PASS"
        return "WARN"

    def _review_note(row) -> str:
        if row["final_result"] == "PASS":
            return "정상 이동 및 발화 일치"
        if row["traversal_result"] == "WARN_TERMINAL_BY_REPEAT_STOP":
            return "실제 마지막 항목으로 보이나 종료 판정 미흡"
        if row["speech_match_result"] == "WARN_CONTEXT_ADDED":
            return "정상 이동, speech에 상위 문맥 포함"
        if row["traversal_result"] == "FAIL_STUCK":
            return "동일 항목 반복 후 종료"
        if row["speech_match_result"] == "FAIL_MISMATCH":
            return "speech와 visible 불일치"
        return "이동/발화 결과 재검토 필요"

    result["final_result"] = result.apply(_final_result, axis=1)
    result["review_note"] = result.apply(_review_note, axis=1)
    result["failure_reason"] = result.apply(
        lambda row: row["failure_reason"]
        if row["failure_reason"]
        else ("speech_visible_diverged" if row["speech_match_result"] == "FAIL_MISMATCH" else ("fallback_dependent" if row["focus_confidence"] == "LOW" and row["final_result"] != "FAIL" else "")),
        axis=1,
    )

    return result[
        [
            "scenario_id",
            "tab",
            "step",
            "context_type",
            "visible",
            "speech",
            "move_result",
            "resource_id",
            "bounds",
            "fallback_used",
            "step_dump_used",
            "req_id",
            "timing_move",
            "timing_get_focus",
            "timing_total",
            "traversal_result",
            "speech_match_result",
            "focus_confidence",
            "final_result",
            "failure_reason",
            "review_note",
            "crop_image_path",
        ]
    ]


def _apply_result_crop_hyperlinks(writer: pd.ExcelWriter, result_df: pd.DataFrame) -> None:
    if "result" not in writer.sheets or "crop_image_path" not in result_df.columns:
        return

    valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

    def _to_hyperlink_target(path_text: str, *, xlsxwriter_mode: bool) -> tuple[str | None, str | None]:
        normalized = path_text.strip()
        if not normalized:
            return None, "empty_path"

        path_obj = Path(normalized)
        if path_obj.suffix and path_obj.suffix.lower() not in valid_exts:
            return None, "unsupported_extension"

        if not xlsxwriter_mode:
            return normalized, None

        if normalized.startswith(("http://", "https://", "file://", "mailto:", "internal:", "external:")):
            return normalized, None

        safe_path = normalized.replace("\\", "/")
        if not safe_path:
            return None, "unsupported_path_format"
        return f"external:{safe_path}", None

    ws = writer.sheets["result"]
    crop_col_idx = result_df.columns.get_loc("crop_image_path")
    is_openpyxl_sheet = hasattr(ws, "cell")
    is_xlsxwriter_sheet = hasattr(ws, "write_url")
    skipped_reasons: dict[str, int] = {}

    for row_idx, crop_path in enumerate(result_df["crop_image_path"].tolist(), start=2):
        path_text = str(crop_path or "").strip()
        if not path_text:
            continue
        display_text = Path(path_text).name or path_text
        target, skip_reason = _to_hyperlink_target(path_text, xlsxwriter_mode=is_xlsxwriter_sheet)
        if skip_reason:
            skipped_reasons[skip_reason] = skipped_reasons.get(skip_reason, 0) + 1
            if is_openpyxl_sheet:
                ws.cell(row=row_idx, column=crop_col_idx + 1).value = display_text
            elif hasattr(ws, "write"):
                ws.write(row_idx - 1, crop_col_idx, display_text)
            continue
        try:
            if is_openpyxl_sheet:
                cell = ws.cell(row=row_idx, column=crop_col_idx + 1)
                cell.value = display_text
                cell.hyperlink = target
                cell.style = "Hyperlink"
            elif is_xlsxwriter_sheet:
                ws.write_url(row_idx - 1, crop_col_idx, target, string=display_text)
            else:
                ws.write(row_idx - 1, crop_col_idx, display_text)
        except Exception as exc:
            skipped_reasons[str(exc)] = skipped_reasons.get(str(exc), 0) + 1
            try:
                if is_openpyxl_sheet:
                    ws.cell(row=row_idx, column=crop_col_idx + 1).value = display_text
                elif hasattr(ws, "write"):
                    ws.write(row_idx - 1, crop_col_idx, display_text)
            except Exception:
                continue

    skipped_total = sum(skipped_reasons.values())
    if skipped_total:
        reason_summary = ", ".join(
            f"{reason} x{count}" for reason, count in sorted(skipped_reasons.items(), key=lambda item: item[0])
        )
        log(
            f"[WARN][excel] result crop hyperlink skipped for {skipped_total} rows reasons='{reason_summary}'"
        )


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
    result_df = make_result_df(filtered_df)

    log("[SAVE] writing sheets raw/filtered/summary/result")
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
    result_df = stringify_complex_columns(result_df)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path) as writer:
        raw_df.to_excel(writer, sheet_name="raw", index=False)
        filtered_df.to_excel(writer, sheet_name="filtered", index=False)
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        result_df.to_excel(writer, sheet_name="result", index=False)
        _apply_result_crop_hyperlinks(writer, result_df)

    if with_images and "crop_image" in raw_df.columns:
        insert_images_to_excel(output_path, image_col_name="crop_image")

    log(f"[SAVE] saved excel: {output_path} rows={len(raw_df)} with_images={with_images}")
