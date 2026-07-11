"""Read-only Canonical Identity Shadow evidence reporting for the QA frontend."""
from __future__ import annotations

import json
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .crash_summary import safe_device_run_dir
from .paths import RUN_LOG_DIR

_LOCK = threading.Lock()
_CACHE: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}
_EVENTS = {
    "SHADOW_ACTION_REDUCED", "SHADOW_ACTION_REDUCED_V2", "TARGET_RESOLVED",
    "POST_ACTION_OBSERVATION", "DELAYED_OBSERVATION", "REPRESENTATIVE_SELECTED",
    "TRANSACTION_CLOSED",
}


def identity_shadow_report(run_id: str, device_id: str, *, run_log_dir: Path = RUN_LOG_DIR) -> dict[str, Any]:
    """Return a safe, derived report.  It never changes the ledger or run artifacts."""
    device_dir = safe_device_run_dir(run_id, device_id, run_log_dir=run_log_dir)
    ledgers = sorted(device_dir.glob("*.evidence.jsonl"), key=lambda p: p.stat().st_mtime_ns if p.exists() else 0, reverse=True)
    if not ledgers:
        return _unavailable("NO_EVIDENCE_FILE")
    return _load(ledgers[0])


def _unavailable(state: str) -> dict[str, Any]:
    return {"available": False, "schema": "identity-shadow-report-v1", "availability": state,
            "legacy_available": False, "v2_available": False, "summary": _summary([]), "transactions": []}


def _load(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat(); key = (int(stat.st_size), int(stat.st_mtime_ns)); resolved = path.resolve()
    except OSError:
        return _unavailable("NO_EVIDENCE_FILE")
    with _LOCK:
        cached = _CACHE.get(resolved)
        if cached and cached[0] == key:
            return cached[1]
    transactions: dict[str, dict[str, Any]] = {}; seen: set[str] = set(); malformed = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return _unavailable("NO_EVIDENCE_FILE")
    for line in lines:
        if not line.strip(): continue
        try: event = json.loads(line)
        except json.JSONDecodeError: malformed += 1; continue
        if not isinstance(event, Mapping) or event.get("event_type") not in _EVENTS: continue
        eid = str(event.get("event_id") or "")
        if eid and eid in seen: continue
        seen.add(eid)
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        txid = str(event.get("transaction_id") or payload.get("transaction_id") or "")
        if not txid: continue
        tx = transactions.setdefault(txid, {"transaction_id": txid, "events": {}})
        tx["events"][str(event["event_type"])] = payload
        for field in ("scenario_id", "plugin_family", "step_index", "logical_action_id", "action_type"):
            if field not in tx and (event.get(field) is not None or payload.get(field) is not None): tx[field] = event.get(field, payload.get(field))
    rows = [_row(tx) for tx in transactions.values() if "SHADOW_ACTION_REDUCED" in tx["events"] or "SHADOW_ACTION_REDUCED_V2" in tx["events"]]
    rows.sort(key=lambda r: (str(r["scenario_id"]), int(r["step_index"] or 0), r["transaction_id"]))
    legacy = any(r["legacy_verdict"] for r in rows); v2 = any(r["v2_verdict"] for r in rows)
    state = "MALFORMED_EVIDENCE" if malformed and not rows else ("V2_AVAILABLE" if v2 and all(r["v2_verdict"] for r in rows) else "V2_PARTIAL" if v2 else "LEGACY_ONLY")
    report = {"available": bool(rows), "schema": "identity-shadow-report-v1", "availability": state,
              "legacy_available": legacy, "v2_available": v2, "summary": _summary(rows), "transactions": rows,
              "parse_warnings": malformed}
    with _LOCK: _CACHE[resolved] = (key, report)
    return report


def _row(tx: Mapping[str, Any]) -> dict[str, Any]:
    events = tx["events"]; legacy = events.get("SHADOW_ACTION_REDUCED", {}); v2 = events.get("SHADOW_ACTION_REDUCED_V2", {})
    result = v2.get("result", v2) if isinstance(v2, Mapping) else {}; result = result if isinstance(result, Mapping) else {}
    verdict = lambda value: str(value or "") or None
    supporting = result.get("supporting_fields", result.get("supporting", [])); missing = result.get("missing_fields", result.get("missing", []))
    return {"transaction_id": tx["transaction_id"], "scenario_id": tx.get("scenario_id"), "plugin_family": tx.get("plugin_family"),
      "step_index": tx.get("step_index"), "logical_action_id": tx.get("logical_action_id"), "action_type": tx.get("action_type"),
      "legacy_verdict": verdict(legacy.get("verdict") if isinstance(legacy, Mapping) else None), "v2_verdict": verdict(result.get("verdict")),
      "verdict_changed": bool(legacy and result and legacy.get("verdict") != result.get("verdict")),
      "target_relation": verdict(result.get("target_relation")), "physical_relation": verdict(result.get("physical_relation")),
      "semantic_relation": verdict(result.get("semantic_relation")), "hierarchy_relation": verdict(result.get("hierarchy_relation")),
      "temporal_relation": verdict(result.get("temporal_relation")), "confidence": verdict(result.get("confidence")),
      "supporting_fields": list(supporting) if isinstance(supporting, list) else [], "contradicting_fields": list(result.get("contradicting_fields", [])),
      "missing_fields": list(missing) if isinstance(missing, list) else [], "evidence_complete": result.get("evidence_complete") is True,
      "reducer_version": result.get("reducer_version", "v2" if result else "legacy"), "normalization_version": result.get("normalization_version"),
      "pre_focus_summary": _safe(events.get("PRE_FOCUS_OBSERVED", {})), "resolved_target_summary": _safe(events.get("TARGET_RESOLVED", {})),
      "landing_summary": _safe(events.get("POST_ACTION_OBSERVATION", {})), "delayed_stability_summary": _safe(events.get("DELAYED_OBSERVATION", {})),
      "representative_summary": _safe(events.get("REPRESENTATIVE_SELECTED", {}))}


def _safe(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping): return None
    source = value.get("observation") if isinstance(value.get("observation"), Mapping) else value
    return {k: source.get(k) for k in ("text", "content_description", "resource_id", "class_name", "bounds", "window_id", "capture_source") if source.get(k) is not None} or None


def _summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(r.get("v2_verdict") or "NO_V2") for r in rows); relations = Counter(str(r.get("target_relation") or "INSUFFICIENT_EVIDENCE") for r in rows)
    return {"transactions": len(rows), "v2_verdicts": dict(counts), "target_relations": dict(relations),
      "changed": sum(bool(r.get("verdict_changed")) for r in rows), "incomplete": sum(not bool(r.get("evidence_complete")) for r in rows),
      "strong_physical": sum(r.get("target_relation") in {"EXACT_PHYSICAL_NODE", "STRONG_PHYSICAL_LINK"} for r in rows),
      "insufficient": sum(r.get("target_relation") == "INSUFFICIENT_EVIDENCE" for r in rows)}
