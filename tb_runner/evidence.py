"""Append-only, evidence-only traversal instrumentation.

This module is intentionally independent from production traversal semantics.  It
records facts and shadow reductions only; callers must never use a result from
this module to select a candidate, stop traversal, or alter a report row.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .evidence_identity import identity_shadow_enabled, reduce_shadow_v2


EVIDENCE_SCHEMA_VERSION = "evidence-event-v1"
EVIDENCE_ENABLED_ENV = "TB_EVIDENCE_LEDGER_ENABLED"


def evidence_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env or os.environ
    truthy = {"1", "true", "yes", "on"}
    return any(
        source.get(name, "").strip().lower() in truthy
        for name in (
            EVIDENCE_ENABLED_ENV,
            "TB_EVIDENCE_IDENTITY_SHADOW_ENABLED",
            "TB_TRAVERSAL_IDENTITY_V2_ENABLED",
        )
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_default(value: Any) -> str:
    return str(value)


def deterministic_json(value: Mapping[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def _short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_text(value: Any) -> str:
    return " ".join(_safe_text(value).lower().split())


def _bounds_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {key: value.get(key) for key in ("l", "t", "r", "b", "left", "top", "right", "bottom") if key in value}
    return {"raw": _safe_text(value)} if _safe_text(value) else {}


@dataclass(frozen=True)
class EvidenceEvent:
    schema_version: str
    event_id: str
    event_type: str
    run_id: str
    scenario_tx_id: str
    transaction_id: str
    logical_action_id: str
    attempt_id: str
    parent_transaction_id: str | None
    causation_event_id: str | None
    producer: str
    producer_instance_id: str
    producer_sequence: int
    wall_time_utc: str
    monotonic_time_ns: int
    runner_received_wall_time_utc: str | None
    scenario_id: str
    plugin_family: str
    step_index: int | str | None
    phase: str
    surface_id: str
    surface_revision: int
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NodeObservation:
    observation_id: str
    snapshot_id: str
    surface_id: str
    surface_revision: int
    captured_at: str
    package: str
    window_id: str
    class_name: str
    resource_id: str
    text: str
    normalized_text: str
    content_description: str
    normalized_content_description: str
    talkback_label: str
    normalized_talkback_label: str
    bounds: dict[str, Any]
    coordinate_space: str
    display_id: str
    focusable: bool | None
    clickable: bool | None
    accessibility_focused: bool | None
    selected: bool | None
    enabled: bool | None
    node_path: str
    parent_path: str
    child_index: int | None
    source: str
    capture_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_node_observation(
    node: Mapping[str, Any] | None,
    *,
    run_id: str,
    surface_id: str,
    surface_revision: int,
    source: str,
    snapshot_id: str | None = None,
    capture_status: str = "captured",
) -> NodeObservation:
    raw = dict(node or {})
    captured_at = _utc_now()
    snapshot = snapshot_id or _short_id("snapshot")
    package = _safe_text(raw.get("packageName") or raw.get("package"))
    window_id = _safe_text(raw.get("windowId") or raw.get("window_id"))
    class_name = _safe_text(raw.get("className") or raw.get("class"))
    resource_id = _safe_text(raw.get("viewIdResourceName") or raw.get("resourceId") or raw.get("resource_id"))
    text = _safe_text(raw.get("text"))
    content_description = _safe_text(raw.get("contentDescription") or raw.get("content_description"))
    talkback_label = _safe_text(raw.get("talkbackLabel") or raw.get("mergedLabel") or raw.get("label"))
    bounds = _bounds_value(raw.get("boundsInScreen") or raw.get("bounds"))
    node_path = _safe_text(raw.get("nodePath") or raw.get("node_path"))
    parent_path = _safe_text(raw.get("parentPath") or raw.get("parent_path"))
    child_index_raw = raw.get("childIndex", raw.get("child_index"))
    try:
        child_index = int(child_index_raw) if child_index_raw is not None and str(child_index_raw) != "" else None
    except (TypeError, ValueError):
        child_index = None
    identity_input = deterministic_json(
        {
            "run": run_id,
            "surface": surface_id,
            "revision": surface_revision,
            "snapshot": snapshot,
            "package": package,
            "window": window_id,
            "class": class_name,
            "resource": resource_id,
            "path": node_path,
            "bounds": bounds,
            "source": source,
        }
    )
    observation_id = f"oid:v1:{hashlib.sha256(identity_input.encode('utf-8')).hexdigest()[:24]}"
    return NodeObservation(
        observation_id=observation_id,
        snapshot_id=snapshot,
        surface_id=surface_id,
        surface_revision=int(surface_revision),
        captured_at=captured_at,
        package=package,
        window_id=window_id,
        class_name=class_name,
        resource_id=resource_id,
        text=text,
        normalized_text=_normalize_text(text),
        content_description=content_description,
        normalized_content_description=_normalize_text(content_description),
        talkback_label=talkback_label,
        normalized_talkback_label=_normalize_text(talkback_label),
        bounds=bounds,
        coordinate_space=_safe_text(raw.get("coordinateSpace") or raw.get("coordinate_space")) or "screen",
        display_id=_safe_text(raw.get("displayId") or raw.get("display_id")),
        focusable=raw.get("focusable") if isinstance(raw.get("focusable"), bool) else None,
        clickable=raw.get("clickable") if isinstance(raw.get("clickable"), bool) else None,
        accessibility_focused=(
            raw.get("accessibilityFocused")
            if isinstance(raw.get("accessibilityFocused"), bool)
            else raw.get("accessibility_focused") if isinstance(raw.get("accessibility_focused"), bool) else None
        ),
        selected=raw.get("selected") if isinstance(raw.get("selected"), bool) else None,
        enabled=raw.get("enabled") if isinstance(raw.get("enabled"), bool) else None,
        node_path=node_path,
        parent_path=parent_path,
        child_index=child_index,
        source=source,
        capture_status=capture_status,
    )


class AppendOnlyEvidenceLedger:
    """Failure-isolated JSONL writer.  Write failures never escape to traversal."""

    def __init__(self, path: Path, warning_fn: Callable[[str], None] | None = None) -> None:
        self.path = path
        self.warning_fn = warning_fn or (lambda _message: None)
        self._lock = threading.Lock()
        self._event_ids: set[str] = set()
        self._failed_writes = 0
        self._written = 0
        self._write_elapsed_ns = 0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "event_count": self._written,
            "duplicate_event_count": len(self._event_ids) - self._written,
            "write_failure_count": self._failed_writes,
            "ledger_write_elapsed_ms": round(self._write_elapsed_ns / 1_000_000, 3),
        }

    def append(self, event: EvidenceEvent) -> bool:
        with self._lock:
            if event.event_id in self._event_ids:
                return False
            self._event_ids.add(event.event_id)
            started = time.monotonic_ns()
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                payload = deterministic_json(event.to_dict())
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.write("\n")
                    handle.flush()
                self._written += 1
                return True
            except Exception as exc:  # evidence must not affect production execution
                self._failed_writes += 1
                self.warning_fn(f"[EVIDENCE][warning] ledger_write_failed error='{type(exc).__name__}: {exc}'")
                return False
            finally:
                self._write_elapsed_ns += time.monotonic_ns() - started


class EvidenceRuntime:
    """Run-scoped side-channel transaction and observation manager."""

    def __init__(
        self,
        *,
        output_path: str | Path,
        run_id: str | None = None,
        warning_fn: Callable[[str], None] | None = None,
        enabled: bool = True,
        identity_shadow: bool | None = None,
    ) -> None:
        prefix = Path(output_path).with_suffix("")
        self.run_id = run_id or f"run_{uuid.uuid4().hex}"
        self.enabled = bool(enabled)
        self.identity_shadow_enabled = self.enabled and (
            identity_shadow_enabled() if identity_shadow is None else bool(identity_shadow)
        )
        self.warning_fn = warning_fn or (lambda _message: None)
        self.ledger = AppendOnlyEvidenceLedger(prefix.with_suffix(".evidence.jsonl"), warning_fn=self.warning_fn)
        self.manifest_path = prefix.with_suffix(".evidence_manifest.json")
        self.reconciliation_path = prefix.with_suffix(".evidence_reconciliation.json")
        self._sequence = 0
        self._scenario_id = ""
        self._plugin_family = ""
        self._scenario_tx_id = ""
        self._step_index: int | str | None = None
        self._surface_id = ""
        self._surface_revision = 0
        self._transactions: dict[str, dict[str, Any]] = {}
        self._finalize_hooks: list[Callable[[], None]] = []
        self._latest_focus: NodeObservation | None = None
        self._all_events: list[EvidenceEvent] = []
        self._identity_shadow_results: dict[str, dict[str, Any]] = {}

    @property
    def is_enabled(self) -> bool:
        return self.enabled

    def start_scenario(self, scenario_id: str, plugin_family: str = "", step_index: int | str | None = None) -> str:
        if not self.enabled:
            return ""
        self._scenario_id = _safe_text(scenario_id)
        self._plugin_family = _safe_text(plugin_family) or self._scenario_id.split("_")[0]
        self._scenario_tx_id = _short_id("stx")
        self._step_index = step_index
        self._surface_id = f"surface:{self._scenario_tx_id}"
        self._surface_revision = 0
        self.emit("SCENARIO_TRANSACTION_OPENED", producer="runner", phase="scenario_start", payload={"scenario_id": self._scenario_id})
        return self._scenario_tx_id

    def set_step(self, step_index: int | str | None, phase: str = "main_loop") -> None:
        self._step_index = step_index
        if phase:
            self.emit("STEP_CONTEXT_SET", producer="runner", phase=phase, payload={"step_index": step_index})

    def begin_transaction(
        self,
        action_type: str,
        *,
        phase: str,
        parent_transaction_id: str | None = None,
        causation_event_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        if not self.enabled:
            return {}
        transaction_id = _short_id("tx")
        logical_action_id = _short_id("act")
        attempt_id = _short_id("att")
        context = {
            "transaction_id": transaction_id,
            "logical_action_id": logical_action_id,
            "attempt_id": attempt_id,
            "parent_transaction_id": parent_transaction_id,
            "action_type": action_type,
            "phase": phase,
            "state": "open",
        }
        event = self.emit(
            "TRANSACTION_OPENED",
            producer="runner",
            phase=phase,
            transaction=context,
            causation_event_id=causation_event_id,
            payload={"action_type": action_type, **dict(payload or {})},
        )
        if event:
            context["opened_event_id"] = event.event_id
        self._transactions[transaction_id] = context
        return context

    def close_transaction(self, transaction: Mapping[str, Any] | None, *, status: str, phase: str, payload: Mapping[str, Any] | None = None) -> None:
        if not self.enabled or not transaction:
            return
        self.emit(
            "TRANSACTION_CLOSED",
            producer="runner",
            phase=phase,
            transaction=transaction,
            causation_event_id=str(transaction.get("opened_event_id") or "") or None,
            payload={"status": status, **dict(payload or {})},
        )
        transaction_id = str(transaction.get("transaction_id") or "")
        if transaction_id in self._transactions:
            self._transactions[transaction_id]["state"] = "closed"

    def add_finalize_hook(self, hook: Callable[[], None]) -> None:
        if callable(hook) and hook not in self._finalize_hooks:
            self._finalize_hooks.append(hook)

    def emit(
        self,
        event_type: str,
        *,
        producer: str,
        phase: str,
        transaction: Mapping[str, Any] | None = None,
        causation_event_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        runner_received_wall_time_utc: str | None = None,
    ) -> EvidenceEvent | None:
        if not self.enabled:
            return None
        self._sequence += 1
        tx = dict(transaction or {})
        event = EvidenceEvent(
            schema_version=EVIDENCE_SCHEMA_VERSION,
            event_id=_short_id("evt"),
            event_type=event_type,
            run_id=self.run_id,
            scenario_tx_id=self._scenario_tx_id,
            transaction_id=str(tx.get("transaction_id") or ""),
            logical_action_id=str(tx.get("logical_action_id") or ""),
            attempt_id=str(tx.get("attempt_id") or ""),
            parent_transaction_id=tx.get("parent_transaction_id"),
            causation_event_id=causation_event_id,
            producer=producer,
            producer_instance_id="python_runner" if producer == "runner" else str(producer),
            producer_sequence=self._sequence,
            wall_time_utc=_utc_now(),
            monotonic_time_ns=time.monotonic_ns(),
            runner_received_wall_time_utc=runner_received_wall_time_utc,
            scenario_id=self._scenario_id,
            plugin_family=self._plugin_family,
            step_index=self._step_index,
            phase=phase,
            surface_id=self._surface_id,
            surface_revision=self._surface_revision,
            payload=dict(payload or {}),
            provenance={"evidence_enabled": True},
        )
        self._all_events.append(event)
        self.ledger.append(event)
        return event

    def observe(
        self,
        node: Mapping[str, Any] | None,
        *,
        source: str,
        transaction: Mapping[str, Any] | None = None,
        phase: str = "focus",
        event_type: str = "NODE_OBSERVED",
        capture_status: str = "captured",
        payload: Mapping[str, Any] | None = None,
    ) -> NodeObservation | None:
        if not self.enabled:
            return None
        observation = build_node_observation(
            node,
            run_id=self.run_id,
            surface_id=self._surface_id,
            surface_revision=self._surface_revision,
            source=source,
            capture_status=capture_status,
        )
        self.emit(
            event_type,
            producer="runner",
            phase=phase,
            transaction=transaction,
            payload={"observation": observation.to_dict(), **dict(payload or {})},
        )
        if observation.capture_status == "captured":
            self._latest_focus = observation
        return observation

    def correlation_extras(self, transaction: Mapping[str, Any] | None) -> list[str]:
        if not self.enabled or not transaction:
            return []
        mapping = {
            "evidenceRunId": self.run_id,
            "evidenceScenarioTxId": self._scenario_tx_id,
            "evidenceTransactionId": str(transaction.get("transaction_id") or ""),
            "evidenceAttemptId": str(transaction.get("attempt_id") or ""),
            "evidenceLogicalActionId": str(transaction.get("logical_action_id") or ""),
        }
        extras: list[str] = []
        for key, value in mapping.items():
            if value:
                extras.extend(["--es", key, value])
        return extras

    def transaction(self, transaction_id: str | None) -> dict[str, Any] | None:
        if not transaction_id:
            return None
        value = self._transactions.get(str(transaction_id))
        return dict(value) if isinstance(value, dict) else None

    def events_for_transaction(self, transaction_id: str | None) -> tuple[EvidenceEvent, ...]:
        """Return an immutable snapshot for read-only runtime policy checks."""
        if not self.enabled or not transaction_id:
            return ()
        return tuple(event for event in self._all_events if event.transaction_id == str(transaction_id))

    def reduce_shadow(self, transaction_id: str) -> dict[str, str]:
        events = [event for event in self._all_events if event.transaction_id == transaction_id]
        return reduce_shadow_events(events)

    def reduce_identity_shadow(self, transaction_id: str) -> dict[str, Any] | None:
        """Run V2 only when explicitly enabled; never influence legacy reduction."""
        if not self.enabled or not self.identity_shadow_enabled:
            return None
        events = [event for event in self._all_events if event.transaction_id == transaction_id]
        result = reduce_shadow_v2(events)
        self._identity_shadow_results[str(transaction_id)] = deepcopy(result)
        return result

    def identity_shadow_result(self, transaction_id: str | None) -> dict[str, Any] | None:
        """Return a defensive copy of a completed V2 transaction reduction."""
        if not self.enabled or not self.identity_shadow_enabled or not transaction_id:
            return None
        transaction = self._transactions.get(str(transaction_id))
        if not isinstance(transaction, dict) or transaction.get("state") != "closed":
            return None
        result = self._identity_shadow_results.get(str(transaction_id))
        if not isinstance(result, dict):
            return None
        copied = deepcopy(result)
        copied["runtime_transaction_id"] = str(transaction_id)
        copied["runtime_transaction_state"] = "closed"
        copied["runtime_orphan_count"] = 0
        copied["runtime_malformed_count"] = 0
        return copied

    def write_manifest(self, manifest: Mapping[str, Any]) -> None:
        if not self.enabled:
            return
        payload = {"schema_version": EVIDENCE_SCHEMA_VERSION, "run_id": self.run_id, "manifest": dict(manifest)}
        try:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            self.manifest_path.write_text(deterministic_json(payload) + "\n", encoding="utf-8")
        except Exception as exc:
            self.warning_fn(f"[EVIDENCE][warning] manifest_write_failed error='{type(exc).__name__}: {exc}'")

    def finalize(self) -> dict[str, Any]:
        if not self.enabled:
            return {}
        for hook in tuple(self._finalize_hooks):
            try:
                hook()
            except Exception as exc:
                self.warning_fn(f"[EVIDENCE][warning] finalize_hook_failed error='{type(exc).__name__}: {exc}'")
        report = build_reconciliation_report(self._all_events)
        report["run_id"] = self.run_id
        report["ledger"] = self.ledger.stats
        try:
            self.reconciliation_path.write_text(deterministic_json(report) + "\n", encoding="utf-8")
        except Exception as exc:
            self.warning_fn(f"[EVIDENCE][warning] reconciliation_write_failed error='{type(exc).__name__}: {exc}'")
        return report


def reduce_shadow_events(events: list[EvidenceEvent]) -> dict[str, str]:
    """Read-only shadow reducer.  Missing evidence intentionally stays unknown."""
    event_types = {event.event_type for event in events}
    payloads = [event.payload for event in events]

    def observation_for(event_type: str, *, last: bool = False) -> dict[str, Any] | None:
        matching = [event.payload.get("observation") for event in events if event.event_type == event_type]
        matching = [value for value in matching if isinstance(value, dict)]
        return matching[-1] if last and matching else (matching[0] if matching else None)

    def signature(node: Mapping[str, Any] | None) -> tuple[Any, ...] | None:
        if not isinstance(node, Mapping):
            return None
        bounds = node.get("boundsInScreen") or node.get("bounds") or {}
        if not isinstance(bounds, Mapping):
            bounds = {"raw": str(bounds)}
        values = (
            node.get("packageName") or node.get("package"),
            node.get("windowId") or node.get("window_id"),
            node.get("className") or node.get("class"),
            node.get("viewIdResourceName") or node.get("resourceId") or node.get("resource_id"),
            tuple(bounds.get(key) for key in ("l", "t", "r", "b", "left", "top", "right", "bottom")),
        )
        return values if any(value not in (None, "", ()) for value in values) else None

    def has_descendant(container: Mapping[str, Any] | None, child_signature: tuple[Any, ...] | None) -> bool:
        if not isinstance(container, Mapping) or child_signature is None:
            return False
        for child in container.get("children") or []:
            if signature(child) == child_signature or has_descendant(child, child_signature):
                return True
        return False

    action_api = "INDETERMINATE"
    if "ACTION_API_RESULT" in event_types:
        accepted = any(bool(payload.get("success")) or payload.get("result") == "ACCEPTED" for payload in payloads)
        action_api = "ACCEPTED" if accepted else "REJECTED"
    pre = observation_for("PRE_FOCUS_OBSERVED")
    post = observation_for("POST_ACTION_OBSERVATION", last=True) or observation_for("POST_FOCUS_OBSERVED", last=True)
    resolved = next(
        (payload.get("resolvedTarget") for payload in payloads if isinstance(payload.get("resolvedTarget"), dict)),
        None,
    )
    pre_signature = signature(pre)
    post_signature = signature(post)
    resolved_signature = signature(resolved)
    target_relation = next((str(payload.get("target_relation")) for payload in payloads if payload.get("target_relation")), "INDETERMINATE")
    if post_signature is not None and resolved_signature is not None:
        if post_signature == resolved_signature:
            target_relation = "TARGET"
        elif has_descendant(resolved, post_signature):
            target_relation = "CONTAINER_CHILD"
        else:
            target_relation = "OTHER_NODE"
    focus_claim = "CLAIMED" if "FOCUS_COMMIT_CLAIMED" in event_types else "INDETERMINATE"
    delta = "INDETERMINATE"
    if pre_signature is not None and post_signature is not None:
        delta = "UNCHANGED" if pre_signature == post_signature else "CHANGED"
    delayed_signatures = [
        signature(event.payload.get("observation"))
        for event in events
        if event.event_type == "DELAYED_OBSERVATION"
    ]
    delayed_signatures = [value for value in delayed_signatures if value is not None]
    stability = next((str(payload.get("stability")) for payload in payloads if payload.get("stability")), "INDETERMINATE")
    if delta == "CHANGED" and pre_signature is not None and any(value == pre_signature for value in delayed_signatures):
        stability = "SNAP_BACK"
    elif post_signature is not None and delayed_signatures:
        stability = "STABLE" if all(value == post_signature for value in delayed_signatures) else "UNSTABLE"
    announcement = "MATCHED" if "ANNOUNCEMENT_OBSERVED" in event_types else "INDETERMINATE"
    if stability == "SNAP_BACK":
        verdict = "SNAP_BACK"
    elif delta == "UNCHANGED" and action_api == "ACCEPTED":
        verdict = "STATIC_FOCUS"
    elif delta == "CHANGED" and target_relation in {"OTHER_NODE", "UNRELATED"}:
        verdict = "MOVE_TO_OTHER_NODE"
    elif delta == "CHANGED" and action_api == "ACCEPTED" and target_relation in {"TARGET", "CONTAINER_CHILD"}:
        verdict = "MOVE_CONFIRMED"
    else:
        verdict = "INDETERMINATE"
    completeness = "COMPLETE" if pre_signature and post_signature and "HELPER_ACK_RECEIVED" in event_types else "PARTIAL"
    return {
        "transport": "ACKED" if "HELPER_ACK_RECEIVED" in event_types else "INDETERMINATE",
        "action_api": action_api,
        "target_relation": target_relation,
        "focus_commit_claim": focus_claim,
        "physical_focus_delta": delta,
        "target_landing": "INDETERMINATE",
        "stability": stability,
        "announcement": announcement,
        "evidence_completeness": completeness,
        "verdict": verdict,
    }


def build_reconciliation_report(events: list[EvidenceEvent]) -> dict[str, Any]:
    types = {event.event_type for event in events}
    scenario_terminal = [event for event in events if event.event_type == "SCENARIO_TERMINAL"]
    terminal_reason = str(scenario_terminal[-1].payload.get("reason") or "") if scenario_terminal else ""
    # Scenario-start aborts have no action transaction by design.  Preserve them
    # against terminals from later scenarios by correlating lifecycle evidence at
    # the scenario transaction boundary (and by scenario id for legacy events).
    def scenario_key(event: EvidenceEvent) -> tuple[str, str] | None:
        if event.scenario_tx_id:
            return ("scenario_tx", event.scenario_tx_id)
        if event.scenario_id:
            return ("scenario_id", event.scenario_id)
        return None

    terminal_reasons_by_scenario: dict[tuple[str, str], set[str]] = {}
    anchor_abort_scenarios: set[tuple[str, str]] = set()
    for event in events:
        key = scenario_key(event)
        if key is None:
            continue
        if event.event_type == "ANCHOR_ABORT":
            anchor_abort_scenarios.add(key)
        elif event.event_type == "SCENARIO_TERMINAL":
            reason = str(event.payload.get("reason") or "")
            terminal_reasons_by_scenario.setdefault(key, set()).add(reason)
    # An observed abort is monotonic when no terminal is recorded, or when its
    # own scenario terminal records the same abort.  A conflicting terminal in
    # the same scenario remains a reconciliation failure.
    anchor_abort_conflicting_terminal = sorted(
        ":".join(key)
        for key in anchor_abort_scenarios
        if (reasons := terminal_reasons_by_scenario.get(key)) and "ANCHOR_ABORT" not in reasons
    )
    checks = {
        "card_found_not_regressed_to_not_found": not ("CARD_FOUND" in types and terminal_reason == "CARD_NOT_FOUND"),
        "card_activated_not_regressed_to_activation_failure": not ("CARD_ACTIVATED" in types and terminal_reason == "CARD_ACTIVATION_FAILED"),
        "screen_transition_not_regressed_to_card_absence": not ("SCREEN_TRANSITION_CONFIRMED" in types and terminal_reason == "CARD_NOT_FOUND"),
        "anchor_abort_preserved": not anchor_abort_conflicting_terminal,
        "aborted_before_collection_distinct_from_zero_valid": not ("ABORTED_BEFORE_COLLECTION" in types and "ZERO_VALID" in types),
        "no_eligible_candidate_distinct_from_not_run": not ("NO_ELIGIBLE_CANDIDATE" in types and "NOT_RUN" in types),
    }
    orphan_events = [event for event in events if event.event_type == "ORPHAN_HELPER_EVIDENCE"]
    orphan_reasons: dict[str, int] = {}
    for event in orphan_events:
        reason = str(event.payload.get("reason") or "unknown")
        orphan_reasons[reason] = orphan_reasons.get(reason, 0) + 1
    legacy_transactions = {
        event.transaction_id
        for event in events
        if event.event_type == "SHADOW_ACTION_REDUCED" and event.transaction_id
    }
    v2_by_transaction: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if event.event_type != "SHADOW_ACTION_REDUCED_V2" or not event.transaction_id:
            continue
        result = event.payload.get("result")
        v2_by_transaction[event.transaction_id] = result if isinstance(result, Mapping) else event.payload
    v2_verdicts: dict[str, int] = {}
    v2_confidence: dict[str, int] = {}
    v2_completeness = {"COMPLETE": 0, "PARTIAL": 0}
    for result in v2_by_transaction.values():
        verdict = str(result.get("verdict") or "INDETERMINATE")
        confidence = str(result.get("confidence") or "INDETERMINATE")
        completeness = (
            "COMPLETE"
            if result.get("evidence_complete") is True
            or str(result.get("evidence_completeness") or "").upper() == "COMPLETE"
            else "PARTIAL"
        )
        v2_verdicts[verdict] = v2_verdicts.get(verdict, 0) + 1
        v2_confidence[confidence] = v2_confidence.get(confidence, 0) + 1
        v2_completeness[completeness] += 1
    return {
        "schema_version": "evidence-reconciliation-v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "terminal_reason": terminal_reason or "unavailable",
        "anchor_abort_scenarios": len(anchor_abort_scenarios),
        "anchor_abort_conflicting_terminal": anchor_abort_conflicting_terminal,
        "event_count": len(events),
        "orphan_evidence": {"count": len(orphan_events), "reasons": orphan_reasons},
        "identity_shadow_v2": {
            "available": bool(v2_by_transaction),
            "transaction_count": len(v2_by_transaction),
            "legacy_transaction_count": len(legacy_transactions),
            "legacy_transactions_without_v2": len(legacy_transactions.difference(v2_by_transaction)),
            "verdicts": dict(sorted(v2_verdicts.items())),
            "confidence": dict(sorted(v2_confidence.items())),
            "completeness": v2_completeness,
        },
    }


def _status(value: Any, reason: str = "") -> dict[str, Any]:
    return {"status": "available" if value not in (None, "") else "unavailable", "value": value, "reason": reason if value in (None, "") else ""}


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None


def collect_run_provenance(
    *,
    repo_root: Path,
    runtime_config_path: str | None,
    scenario_registry_path: Path | None,
    runner_path: Path,
    client: Any | None = None,
    serial: str | None = None,
) -> dict[str, Any]:
    def git_value(*args: str) -> str | None:
        try:
            return subprocess.check_output(["git", *args], cwd=repo_root, text=True, stderr=subprocess.DEVNULL, timeout=3).strip() or None
        except Exception:
            return None

    def adb_value(command: list[str]) -> str | None:
        if client is None:
            return None
        try:
            result = client._run(command, dev=serial, timeout=5)
            return str(result).strip() or None
        except Exception:
            return None

    commit = git_value("rev-parse", "HEAD")
    dirty = git_value("status", "--porcelain")
    runtime_path = Path(runtime_config_path) if runtime_config_path else None
    helper_path = adb_value(["shell", "pm", "path", "com.iotpart.sqe.talkbackhelper"])
    helper_apk_hash = None
    if helper_path and helper_path.startswith("package:"):
        remote_path = helper_path.split("package:", 1)[1]
        helper_apk_hash = adb_value(["shell", "sha256sum", remote_path])
    return {
        "repository_commit_sha": _status(commit, "git_unavailable"),
        "working_tree_dirty": {"status": "available", "value": bool(dirty), "reason": ""},
        "runner_source_hash": _status(_sha256_file(runner_path), "runner_file_unavailable"),
        "helper_apk_sha256": _status(helper_apk_hash, "adb_or_helper_apk_unavailable"),
        "helper_version": _status(adb_value(["shell", "dumpsys", "package", "com.iotpart.sqe.talkbackhelper"]), "adb_unavailable"),
        "runtime_config_hash": _status(_sha256_file(runtime_path) if runtime_path else None, "runtime_config_unavailable"),
        "scenario_registry_hash": _status(_sha256_file(scenario_registry_path) if scenario_registry_path else None, "registry_unavailable"),
        "target_app_version": _status(adb_value(["shell", "dumpsys", "package", "com.samsung.android.oneconnect"]), "adb_unavailable"),
        "android_build": _status(adb_value(["shell", "getprop", "ro.build.fingerprint"]), "adb_unavailable"),
        "talkback_version": _status(adb_value(["shell", "dumpsys", "package", "com.google.android.marvin.talkback"]), "adb_unavailable"),
        "webview_version": _status(adb_value(["shell", "dumpsys", "package", "com.google.android.webview"]), "adb_unavailable"),
        "device_model": _status(adb_value(["shell", "getprop", "ro.product.model"]), "adb_unavailable"),
        "locale": _status(adb_value(["shell", "getprop", "persist.sys.locale"]), "adb_unavailable"),
        "display_information": _status(adb_value(["shell", "wm", "size"]), "adb_unavailable"),
        "evidence_schema_version": {"status": "available", "value": EVIDENCE_SCHEMA_VERSION, "reason": ""},
    }
