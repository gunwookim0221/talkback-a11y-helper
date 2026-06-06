from __future__ import annotations

import openpyxl
from pathlib import Path
from .paths import OUTPUT_DIR
from .recent_runs import safe_recent_run_log_path
from .run_summary import read_summary_file, summary_path_for_log

def get_run_mismatch_summary(run_id: str) -> dict[str, object]:
    try:
        log_path = safe_recent_run_log_path(run_id)
    except (FileNotFoundError, ValueError):
        return {"error": "run not found"}

    summary = read_summary_file(summary_path_for_log(log_path))
    xlsx_path = None
    if summary:
        if summary.get("xlsx_path"):
            xlsx_path = Path(str(summary["xlsx_path"]))
        elif summary.get("xlsx_filename"):
            xlsx_path = OUTPUT_DIR / str(summary["xlsx_filename"])

    if not xlsx_path:
        return {"error": "xlsx output not available"}

    return get_mismatch_summary_from_xlsx(xlsx_path)

def get_mismatch_summary_from_xlsx(xlsx_path: Path) -> dict[str, object]:
    if not xlsx_path.exists():
        return {"error": "xlsx file not found"}

    try:
        workbook = openpyxl.load_workbook(xlsx_path, data_only=True)
        if "result" not in workbook.sheetnames:
            return {"error": "result sheet not found"}
        
        sheet = workbook["result"]
        headers = [str(sheet.cell(1, c).value or "") for c in range(1, sheet.max_column + 1)]
        
        def _get_col(name: str) -> int | None:
            return headers.index(name) + 1 if name in headers else None

        scenario_col = _get_col("scenario_id") or _get_col("scenario")
        plugin_name_col = _get_col("plugin_name")
        step_col = _get_col("step")
        visible_col = _get_col("visible_label")
        speech_col = _get_col("merged_announcement")
        mismatch_col = _get_col("mismatch_type")
        result_col = _get_col("final_result")
        failure_col = _get_col("failure_reason")
        focus_col = _get_col("focus_confidence")
        context_col = _get_col("context_type")
        note_col = _get_col("review_note")
        crop_col = _get_col("result_crop_thumbnail")
        repeat_count_col = _get_col("repeat_count")
        first_step_col = _get_col("first_step")
        last_step_col = _get_col("last_step")
        steps_col = _get_col("steps")
        repeated_group_col = _get_col("is_repeated_issue_group")

        def _int_cell(row: int, col: int | None, default: int = 0) -> int:
            if not col:
                return default
            try:
                return int(sheet.cell(row, col).value or default)
            except (TypeError, ValueError):
                return default

        summary_matched = 0
        summary_true_mismatch = 0
        summary_empty_speech = 0
        summary_empty_visible = 0
        summary_review = 0
        summary_runtime_warning = 0

        summary_fail_count = 0
        summary_issue_count = 0
        summary_review_count = 0
        summary_clean_count = 0
        
        scenario_stats = {}
        all_previews = []

        for row in range(2, sheet.max_row + 1):
            scenario = str(sheet.cell(row, scenario_col).value or "").strip() if scenario_col else ""
            if not scenario:
                scenario = "unknown"
            
            if scenario not in scenario_stats:
                scenario_stats[scenario] = {
                    "scenario_id": scenario,
                    "plugin_name": "",
                    "matched": 0,
                    "true_mismatch": 0,
                    "empty_speech": 0,
                    "empty_visible": 0,
                    "review": 0,
                    "runtime_warning": 0,
                    "fail_count": 0,
                    "issue_count": 0,
                    "review_count": 0,
                    "clean_count": 0,
                    "status": "clean"
                }

            plugin_name = str(sheet.cell(row, plugin_name_col).value or "").strip() if plugin_name_col else ""
            step = str(sheet.cell(row, step_col).value or "").strip() if step_col else ""
            visible = str(sheet.cell(row, visible_col).value or "").strip() if visible_col else ""
            speech = str(sheet.cell(row, speech_col).value or "").strip() if speech_col else ""
            mismatch_type = str(sheet.cell(row, mismatch_col).value or "").strip().upper() if mismatch_col else ""
            final_result = str(sheet.cell(row, result_col).value or "").strip().upper() if result_col else ""
            failure_reason = str(sheet.cell(row, failure_col).value or "").strip() if failure_col else ""
            focus_confidence = str(sheet.cell(row, focus_col).value or "").strip() if focus_col else ""
            context_type = str(sheet.cell(row, context_col).value or "").strip() if context_col else ""
            review_note = str(sheet.cell(row, note_col).value or "").strip() if note_col else ""
            crop_thumbnail = str(sheet.cell(row, crop_col).value or "").strip() if crop_col else ""
            repeat_count = _int_cell(row, repeat_count_col, 1)
            first_step = str(sheet.cell(row, first_step_col).value or "").strip() if first_step_col else step
            last_step = str(sheet.cell(row, last_step_col).value or "").strip() if last_step_col else step
            repeated_steps = str(sheet.cell(row, steps_col).value or "").strip() if steps_col else step
            is_repeated_issue_group = False
            if repeated_group_col:
                raw_repeated = sheet.cell(row, repeated_group_col).value
                is_repeated_issue_group = str(raw_repeated).strip().lower() in {"true", "1", "yes"}

            if not scenario_stats[scenario]["plugin_name"] and plugin_name:
                scenario_stats[scenario]["plugin_name"] = plugin_name

            category = ""
            is_fail = False
            is_issue = False
            is_review = False
            is_clean = False

            both_text_empty = not visible and not speech
            exact_visible_speech_match = bool(visible and speech and visible == speech)

            if mismatch_type == "EMPTY_VISIBLE" or both_text_empty:
                summary_empty_visible += 1
                scenario_stats[scenario]["empty_visible"] += 1
                if both_text_empty:
                    summary_review += 1
                    scenario_stats[scenario]["review"] += 1
                    is_review = True
                    category = "REVIEW"
                else:
                    is_issue = True
                    category = "EMPTY_VISIBLE"
            elif mismatch_type == "EMPTY_SPEECH" or (visible and not speech):
                summary_empty_speech += 1
                scenario_stats[scenario]["empty_speech"] += 1
                is_fail = True
                category = "EMPTY_SPEECH"
            elif mismatch_type in {"PARTIAL_MATCH", "REPRESENTATIVE_CONTEXT"}:
                summary_review += 1
                scenario_stats[scenario]["review"] += 1
                is_review = True
                category = "REVIEW"
            elif mismatch_type in {"TEXT_MISMATCH", "LABEL_MISMATCH", "SPOKEN_MISMATCH", "MISMATCH", "FAIL_MISMATCH"} or (mismatch_type and "MATCH" not in mismatch_type and "EMPTY" not in mismatch_type):
                summary_true_mismatch += 1
                scenario_stats[scenario]["true_mismatch"] += 1
                is_fail = True
                category = "TRUE_MISMATCH"
            elif mismatch_type in {"EXACT_MATCH", "NORMALIZED_MATCH"} or (final_result == "PASS" and visible and speech):
                summary_matched += 1
                scenario_stats[scenario]["matched"] += 1
                is_clean = True
                category = "MATCHED"
            else:
                # Catch-all
                if final_result == "PASS":
                    summary_matched += 1
                    scenario_stats[scenario]["matched"] += 1
                    is_clean = True
                    category = "MATCHED"
                else:
                    summary_review += 1
                    scenario_stats[scenario]["review"] += 1
                    is_review = True
                    category = "REVIEW"

            # Runtime Warning Override
            if final_result == "WARN" and failure_reason:
                lower_reason = failure_reason.lower()
                if any(ignored in lower_reason for ignored in ["repeat_no_progress", "viewport_exhausted", "terminal_reached", "end_of_content", "no_unvisited_local_tab"]):
                    # Ignored warning, treated as clean
                    pass
                elif any(reason in lower_reason for reason in ["plugin_open_failed", "terminal_not_handled", "activation_fail", "parse_error", "fatal", "exception"]):
                    summary_runtime_warning += 1
                    scenario_stats[scenario]["runtime_warning"] += 1
                    is_issue = True
                    category = "RUNTIME_WARNING"

            # Top-level Categorization
            if is_fail:
                summary_fail_count += 1
                scenario_stats[scenario]["fail_count"] += 1
                top_category = "FAIL"
            elif is_issue:
                summary_issue_count += 1
                scenario_stats[scenario]["issue_count"] += 1
                top_category = "ISSUE"
            elif is_review:
                summary_review_count += 1
                scenario_stats[scenario]["review_count"] += 1
                top_category = "REVIEW"
            else:
                summary_clean_count += 1
                scenario_stats[scenario]["clean_count"] += 1
                top_category = "CLEAN"

            add_to_preview = top_category in {"FAIL", "ISSUE"}
            if exact_visible_speech_match or both_text_empty:
                add_to_preview = False

            if add_to_preview:
                all_previews.append({
                    "scenario_id": scenario,
                    "plugin_name": plugin_name,
                    "step": step,
                    "context_type": context_type,
                    "visible_label": visible,
                    "merged_announcement": speech,
                    "mismatch_type": mismatch_type,
                    "final_result": final_result,
                    "failure_reason": failure_reason,
                    "focus_confidence": focus_confidence,
                    "review_note": review_note,
                    "crop_thumbnail": crop_thumbnail,
                    "repeat_count": repeat_count,
                    "first_step": first_step,
                    "last_step": last_step,
                    "steps": repeated_steps,
                    "is_repeated_issue_group": is_repeated_issue_group,
                    "category": category,
                    "top_category": top_category
                })

        workbook.close()

        # Sort previews by priority: FAIL > ISSUE > REVIEW
        priority_map = {
            "FAIL": 1,
            "ISSUE": 2,
            "REVIEW": 3
        }
        all_previews.sort(key=lambda x: priority_map.get(x["top_category"], 99))
        previews = all_previews[:20]

        # Calculate scenario status
        scenario_summary = []
        for s_id, stats in scenario_stats.items():
            if stats["fail_count"] > 0:
                stats["status"] = "fail"
            elif stats["issue_count"] > 0:
                stats["status"] = "issue"
            elif stats["review_count"] > 0:
                stats["status"] = "review"
            else:
                stats["status"] = "clean"
            scenario_summary.append(stats)

        return {
            "summary": {
                "fail_count": summary_fail_count,
                "issue_count": summary_issue_count,
                "review_count": summary_review_count,
                "clean_count": summary_clean_count,
                "matched": summary_matched,
                "true_mismatch": summary_true_mismatch,
                "empty_speech": summary_empty_speech,
                "empty_visible": summary_empty_visible,
                "review": summary_review,
                "runtime_warning": summary_runtime_warning,
            },
            "scenario_summary": scenario_summary,
            "signals": previews,
            "debug": {
                "xlsx_path": xlsx_path.name,
                "result_rows": sheet.max_row - 1 if sheet.max_row > 1 else 0
            }
        }

    except Exception as exc:
        return {"error": f"Failed to parse xlsx: {str(exc)}"}
