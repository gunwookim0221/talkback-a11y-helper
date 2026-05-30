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
    xlsx_filename = None
    if summary:
        xlsx_filename = summary.get("xlsx_filename")
    
    if not xlsx_filename:
        return {"error": "xlsx output not available"}

    xlsx_path = OUTPUT_DIR / str(xlsx_filename)
    if not xlsx_path.exists():
        return {"error": "xlsx file not found"}

    try:
        workbook = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
        if "result" not in workbook.sheetnames:
            return {"error": "result sheet not found"}
        
        sheet = workbook["result"]
        headers = [str(sheet.cell(1, c).value or "") for c in range(1, sheet.max_column + 1)]
        
        def _get_col(name: str) -> int | None:
            return headers.index(name) + 1 if name in headers else None

        scenario_col = _get_col("scenario_id")
        plugin_name_col = _get_col("plugin_name")
        step_col = _get_col("step")
        visible_col = _get_col("visible_label")
        speech_col = _get_col("merged_announcement")
        mismatch_col = _get_col("mismatch_type")
        result_col = _get_col("final_result")
        failure_col = _get_col("failure_reason")
        focus_col = _get_col("focus_confidence")

        summary_matched = 0
        summary_true_mismatch = 0
        summary_empty_speech = 0
        summary_empty_visible = 0
        summary_review = 0
        summary_runtime_warning = 0
        
        scenario_stats = {}
        all_previews = []

        for row in range(2, sheet.max_row + 1):
            scenario = str(sheet.cell(row, scenario_col).value or "").strip() if scenario_col else ""
            if not scenario:
                continue
            
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

            category = ""

            if not scenario_stats[scenario]["plugin_name"] and plugin_name:
                scenario_stats[scenario]["plugin_name"] = plugin_name

            if mismatch_type == "EMPTY_VISIBLE" or (not visible and not speech):
                summary_empty_visible += 1
                scenario_stats[scenario]["empty_visible"] += 1
                category = "EMPTY_VISIBLE"
            elif mismatch_type == "EMPTY_SPEECH" or (visible and not speech):
                summary_empty_speech += 1
                scenario_stats[scenario]["empty_speech"] += 1
                category = "EMPTY_SPEECH"
            elif mismatch_type in {"PARTIAL_MATCH", "REPRESENTATIVE_CONTEXT"}:
                summary_review += 1
                scenario_stats[scenario]["review"] += 1
                category = "REVIEW"
            elif mismatch_type in {"TEXT_MISMATCH", "LABEL_MISMATCH", "SPOKEN_MISMATCH", "MISMATCH", "FAIL_MISMATCH"} or (mismatch_type and "MATCH" not in mismatch_type and "EMPTY" not in mismatch_type):
                summary_true_mismatch += 1
                scenario_stats[scenario]["true_mismatch"] += 1
                category = "TRUE_MISMATCH"
            elif final_result == "WARN" and failure_reason and any(reason in failure_reason.lower() for reason in ["move_failed", "terminal_not_handled", "plugin_boundary", "focus_lost"]):
                summary_runtime_warning += 1
                scenario_stats[scenario]["runtime_warning"] += 1
                category = "RUNTIME_WARNING"
            elif mismatch_type == "EXACT_MATCH" or (final_result == "PASS" and visible and speech):
                summary_matched += 1
                scenario_stats[scenario]["matched"] += 1
                category = "MATCHED"
            else:
                # Catch-all
                if final_result == "PASS":
                    summary_matched += 1
                    scenario_stats[scenario]["matched"] += 1
                    category = "MATCHED"
                else:
                    summary_review += 1
                    scenario_stats[scenario]["review"] += 1
                    category = "REVIEW"

            if category and category != "MATCHED":
                all_previews.append({
                    "scenario": scenario,
                    "plugin_name": plugin_name,
                    "step": step,
                    "visible": visible,
                    "spoken": speech,
                    "mismatch_type": mismatch_type,
                    "final_result": final_result,
                    "failure_reason": failure_reason,
                    "focus_confidence": focus_confidence,
                    "category": category
                })

        workbook.close()

        # Sort previews by priority: TRUE_MISMATCH > EMPTY_SPEECH > EMPTY_VISIBLE > REVIEW > RUNTIME_WARNING
        priority_map = {
            "TRUE_MISMATCH": 1,
            "EMPTY_SPEECH": 2,
            "EMPTY_VISIBLE": 3,
            "REVIEW": 4,
            "RUNTIME_WARNING": 5
        }
        all_previews.sort(key=lambda x: priority_map.get(x["category"], 99))
        previews = all_previews[:10]

        # Calculate scenario status
        scenario_summary = []
        for s_id, stats in scenario_stats.items():
            if stats["true_mismatch"] > 0 or stats["empty_speech"] > 0:
                stats["status"] = "fail"
            elif stats["empty_visible"] > 0 or stats["runtime_warning"] > 0:
                stats["status"] = "issue"
            elif stats["review"] > 0:
                stats["status"] = "review"
            else:
                stats["status"] = "clean"
            scenario_summary.append(stats)

        return {
            "summary": {
                "matched": summary_matched,
                "true_mismatch": summary_true_mismatch,
                "empty_speech": summary_empty_speech,
                "empty_visible": summary_empty_visible,
                "review": summary_review,
                "runtime_warning": summary_runtime_warning,
            },
            "scenario_summary": scenario_summary,
            "signals": previews
        }

    except Exception as exc:
        return {"error": f"Failed to parse xlsx: {str(exc)}"}
