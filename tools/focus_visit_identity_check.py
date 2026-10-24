"""Offline identity consistency check; reads artifacts and never contacts a device."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tb_runner.traversal_reliability import instance_id, normalized, normalized_bounds


def document(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def check_credited_visit(row, cursor=None):
    rec = document(row.get("focus_reconciliation_evidence"))
    if row.get("visit_record_status") != "RECORDED" and not rec.get("production_visit_credit"):
        return {"step": row.get("step_index"), "status": "NOT_CREDITED", "reasons": []}
    node = document(row.get("actual_focus_node"))
    expected = {
        "resource_id": str(node.get("viewIdResourceName") or node.get("resourceId") or ""),
        "class": str(node.get("className") or node.get("class") or ""),
        "bounds": normalized_bounds(node.get("boundsInScreen") or node.get("bounds")),
    }
    reasons = []
    if node.get("accessibilityFocused") is not True or not expected["bounds"] or not expected["class"]:
        reasons.append("ACTUAL_FOCUS_PROOF_INCOMPLETE")
    for field, key in (("resource_id", "actual_focus_resource_id"),
                       ("class", "actual_focus_class_name"), ("bounds", "actual_focus_bounds")):
        normalize = normalized_bounds if field == "bounds" else normalized
        if normalize(row.get(key)) != normalize(expected[field]):
            reasons.append("ACTUAL_PROJECTION_" + field.upper() + "_MISMATCH")
    expected_id = instance_id({"scenario_id": row.get("scenario_id"),
                               "view_id": expected["resource_id"], "bounds": expected["bounds"]})
    visit_id = rec.get("reconciled_visit_instance_id") or row.get("reconciled_visit_instance_id")
    if visit_id != expected_id:
        reasons.append("VISIT_IDENTITY_MISMATCH")
    if cursor is not None and (cursor.get("confirmed") is not True or cursor.get("instance_id") != expected_id):
        reasons.append("CURSOR_IDENTITY_MISMATCH")
    return {"step": row.get("step_index"), "status": "FAIL" if reasons else "PASS",
            "reasons": reasons, "actual_identity": expected, "expected_instance_id": expected_id,
            "visit_instance_id": visit_id, "cursor_checked": cursor is not None}


def check_workbook(workbook, trace=None):
    from openpyxl import load_workbook
    cursors = {}
    if trace is not None:
        for line in Path(trace).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if (event.get("event") == "PRODUCTION_DECISION_BOUNDARY" and event.get("phase") == "return"
                    and event.get("function") == "_prepare_phase6d_exploration_decision"):
                ref = (event.get("frontier") or {}).get("source_observation_ref") or {}
                cursors[event.get("step")] = (event.get("capture_id"), ref.get("focus_cursor") or {})
    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        sheet = book["raw"]
        headers = [cell.value for cell in sheet[1]]
        results = []
        for values in sheet.iter_rows(min_row=2, values_only=True):
            row = dict(zip(headers, values))
            capture, cursor = cursors.get(row.get("step_index"), (None, None))
            result = check_credited_visit(row, cursor)
            if trace is not None and result["status"] != "NOT_CREDITED":
                if cursor is None or not capture or capture != row.get("capture_id"):
                    result["reasons"].append("CURSOR_CAPTURE_MISSING_OR_MISMATCH")
                    result["status"] = "FAIL"
            results.append(result)
        return {"status": "FAIL" if any(r["status"] == "FAIL" for r in results) else "PASS", "rows": results}
    finally:
        book.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--trace", type=Path)
    args = parser.parse_args()
    result = check_workbook(args.workbook, args.trace)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
