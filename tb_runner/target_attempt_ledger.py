"""Durable, request-correlated ledger for every targeted focus attempt."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def ledger_state(status: str) -> str:
    return {
        "TARGET_MATCHED": "MATCHED", "TARGET_NOT_FOUND": "NOT_FOUND",
        "AMBIGUOUS_TARGET": "AMBIGUOUS_TARGET", "UNAVAILABLE": "UNAVAILABLE",
        "TALKBACK_RESTARTED": "INTERRUPTED_TALKBACK_RESTART",
        "TRANSPORT_ERROR": "TRANSPORT_ERROR", "PARSE_ERROR": "TRANSPORT_ERROR",
        "NO_RESULT": "NO_RESULT",
    }.get(str(status or "").upper(), "OTHER_EXPLICIT_STATE")


class TargetAttemptLedger:
    def __init__(self, output_path: str | Path | None = None):
        self.path = Path(output_path).with_suffix(".target_attempt_ledger.json") if output_path else None
        self.entries: dict[str, dict[str, Any]] = {}

    def begin(self, scenario_id: str, step: int, target: dict[str, Any]) -> str:
        attempt_id = f"target_{len(self.entries) + 1:06d}"
        self.entries[attempt_id] = {
            "attempt_id": attempt_id, "scenario_id": scenario_id, "step": step,
            "target": dict(target), "state": "NO_RESULT", "result_count": 0,
            "reason": "attempt_started_without_result", "workbook_rows": [],
            "workbook_omission": "NOT_YET_RECONCILED",
        }
        self._save()
        return attempt_id

    def finish(self, attempt_id: str, *, status: str, result: dict[str, Any] | None = None,
               restart: dict[str, Any] | None = None) -> dict[str, Any]:
        entry = self.entries[attempt_id]
        entry["result_count"] += 1
        if entry["result_count"] > 1:
            entry.update(state="TRANSPORT_ERROR", reason="duplicate_result")
        else:
            value = result or {}
            entry.update(state=ledger_state("TALKBACK_RESTARTED" if restart else status),
                         helper_status=str(value.get("status") or status),
                         req_id=value.get("reqId"), reason=str(value.get("reason") or ""))
            if restart:
                entry["restart_event"] = dict(restart)
        self._save()
        return dict(entry)

    def reconcile(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_id: dict[str, list[int]] = {}
        for index, row in enumerate(rows, start=2):
            attempt_id = str(row.get("target_focus_attempt_id") or "")
            if attempt_id:
                by_id.setdefault(attempt_id, []).append(index)
        for entry in self.entries.values():
            entry["workbook_rows"] = by_id.get(entry["attempt_id"], [])
            entry["workbook_omission"] = "" if entry["workbook_rows"] else "NO_NORMAL_WORKBOOK_ROW"
        self._save()
        return self.document()

    def interrupt_step(self, scenario_id: str, step: int, event: dict[str, Any]) -> None:
        for entry in self.entries.values():
            if entry["scenario_id"] == scenario_id and entry["step"] == step:
                if entry["state"] != "INTERRUPTED_TALKBACK_RESTART":
                    entry["state_before_interruption"] = entry["state"]
                entry.update(state="INTERRUPTED_TALKBACK_RESTART", restart_event=dict(event))
        self._save()

    def document(self) -> dict[str, Any]:
        entries = list(self.entries.values())
        return {
            "schema_version": "target-attempt-ledger-v1", "attempt_count": len(entries),
            "ledger_count": len(entries),
            "classified_outcome_count": sum(item["result_count"] > 0 for item in entries),
            "workbook_target_rows": sum(len(item["workbook_rows"]) for item in entries),
            "workbook_omitted_attempt_count": sum(item["workbook_omission"] == "NO_NORMAL_WORKBOOK_ROW" for item in entries),
            "state_counts": dict(Counter(item["state"] for item in entries)), "entries": entries,
        }

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self.document(), ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)


def get_target_attempt_ledger(client: Any) -> TargetAttemptLedger:
    ledger = getattr(client, "_target_attempt_ledger", None)
    if ledger is None:
        ledger = TargetAttemptLedger()
        client._target_attempt_ledger = ledger
    return ledger


def reconcile_saved_target_ledgers(run_root: str | Path) -> list[dict[str, Any]]:
    """Reconcile durable attempts after the subprocess has exited or been stopped.

    Read only persisted raw rows; never infer missing visit credit from a log.
    An absent workbook is an explicit omission, not a lost attempt.
    """
    import openpyxl

    results = []
    for path in Path(run_root).glob("*.target_attempt_ledger.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        entries = document["entries"]
        by_id = {entry["attempt_id"]: entry for entry in entries}
        if len(by_id) != len(entries):
            raise ValueError("Duplicate target attempt identity in saved ledger")
        workbook_path = path.with_name(path.name.removesuffix(".target_attempt_ledger.json") + ".xlsx")
        rows = []
        source = "WORKBOOK_UNAVAILABLE"
        if workbook_path.is_file():
            workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
            try:
                sheet = workbook["raw"]
                iterator = sheet.iter_rows(values_only=True)
                header = next(iterator)
                rows = [dict(zip(header, row)) for row in iterator]
                unknown = {str(row.get("target_focus_attempt_id")) for row in rows if row.get("target_focus_attempt_id")} - set(by_id)
                if unknown:
                    raise ValueError("Workbook contains an unknown target attempt identity")
                source = "PERSISTED_RAW_WORKBOOK"
            finally:
                workbook.close()
        ledger = TargetAttemptLedger(workbook_path)
        ledger.entries = by_id
        result = ledger.reconcile(rows)
        result["reconciliation_source"] = source
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        results.append(result)
    return results
