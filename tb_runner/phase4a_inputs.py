"""Read-only projections from production ledgers into Phase 4A inputs."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from tb_runner.discovery_candidates import DiscoverySnapshot
from tb_runner.phase4a_planner import PlannerInput, ProductionHistory, production_instance


def project_history(scenario_id: str, *, attempt_entries: Iterable[Mapping[str, Any]] = (),
                    visited_ids: Iterable[str] = (), reconciled_rows: Iterable[Mapping[str, Any]] = (),
                    attempted_ids: Iterable[str] = (), stale_ids: Iterable[str] = (),
                    allowed_ids: Iterable[str] | None = None, known: bool = True,
                    source: str = "PRODUCTION_LEDGER") -> ProductionHistory:
    """Copy exact attempts and reconciled visits; never infer them from ACKs.

    A successful target request is still just an attempt. Neither Phase 3 focus
    observations nor representative rows can supply visit authority here.
    """
    attempts, last_steps, recent = Counter(), {}, []
    for entry in attempt_entries:
        if entry.get("scenario_id") != scenario_id:
            continue
        target = entry.get("target")
        if not isinstance(target, Mapping) or not target.get("bounds"):
            continue
        identity = production_instance(target, scenario_id)
        attempts[identity] += 1
        recent.append(identity)
        if isinstance(entry.get("step"), int):
            last_steps[identity] = entry["step"]
    for identity in attempted_ids:
        attempts[identity] = max(1, attempts[identity])
    # The caller supplies existing production ledger membership. Reconciliation
    # rows may count recorded visits only for that membership, never create it.
    visits = Counter({identity: 1 for identity in visited_ids})
    recorded = Counter()
    for row in reconciled_rows:
        if row.get("scenario_id", scenario_id) != scenario_id:
            continue
        identity = row.get("reconciled_visit_instance_id")
        if (identity in visits and row.get("visit_record_status") == "RECORDED"
                and row.get("focus_transition_status") == "CONFIRMED_MOVED"):
            recorded[identity] += 1
    for identity, count in recorded.items():
        visits[identity] = max(visits[identity], count)
    return ProductionHistory(scenario_id, known, tuple(sorted(attempts.items())),
                             tuple(sorted(visits.items())), tuple(recent), tuple(sorted(last_steps.items())),
                             tuple(sorted(stale_ids)), None if allowed_ids is None else tuple(sorted(allowed_ids)), source)


def runtime_input(snapshot: DiscoverySnapshot, context_status: str, *, scenario_id: str,
                  client: Any, state: Any, rows: Iterable[Mapping[str, Any]] = (),
                  capability: Mapping[str, Any] | None = None) -> PlannerInput:
    """Read existing state/client data. No discovery, device I/O or mutation."""
    tracker = getattr(state, "content_terminal", None)
    metrics = getattr(state, "reliability_metrics", None)
    ledger = getattr(client, "_target_attempt_ledger", None)
    entries = tuple(getattr(ledger, "entries", {}).values())
    visited = set(getattr(metrics, "visited", ()) or ()) | set(getattr(tracker, "visited", ()) or ())
    history = project_history(scenario_id, attempt_entries=entries, visited_ids=visited,
                              reconciled_rows=rows,
                              attempted_ids=getattr(tracker, "target_attempted_ids", ()) or (),
                              stale_ids=getattr(getattr(tracker, "lifecycle", None), "aliases", {}) or (),
                              allowed_ids=getattr(tracker, "planner_candidate_ids", None),
                              source="PRODUCTION_RUNTIME_TARGET_ATTEMPTS_AND_RECONCILED_VISITS")
    cap = capability or {}
    latest = getattr(tracker, "latest", {}) or {}
    exhausted = latest.get("scroll_exhausted") is True
    blocked = bool(cap.get("contradictory") or latest.get("scroll_capability_contradictory"))
    signature = latest.get("scroll_viewport_signature")
    if signature and signature in (getattr(tracker, "scroll_attempted_viewports", ()) or ()):
        blocked = True
    previous = getattr(state, "previous_step_row", {}) or {}
    return PlannerInput(snapshot, context_status, history, exhausted, blocked,
                        latest.get("pending_transition") is True,
                        str(previous.get("focus_transition_status") or "UNKNOWN"),
                        bool(getattr(tracker, "no_progress_steps", 0) >= 4
                             or previous.get("focus_transition_status") == "CONFIRMED_UNCHANGED"))


def production_action(row: Mapping[str, Any], scenario_id: str) -> tuple[str, str | None]:
    """Describe an existing intended action, not its eventual focus landing."""
    if row.get("scroll_transition"):
        return ("COMPOSITE" if row.get("target_focus_attempted") or row.get("move_result") else "SCROLL_FORWARD", None)
    if row.get("target_focus_attempted") is True:
        target = row.get("target_focus_descriptor") or {}
        return "FOCUS_CANDIDATE", production_instance(target, scenario_id) if target.get("bounds") else None
    return "FOCUS_NEXT", None
