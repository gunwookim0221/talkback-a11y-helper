"""Offline Audit V5 traversal-engine parser.

This tool reconstructs normalized traversal events from existing artifacts only.
It does not import or modify runner traversal behavior.
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_xml_candidates import extract_xml_candidates


SCHEMA_VERSION = "audit_v5_traversal_mvp_v1"
TOOL_VERSION = "phase5a-3-mvp"

ROOT_CAUSE_PRIORITY = (
    "ACTIVATION_FAIL",
    "REALIGN_FAIL",
    "STATE_RECOVERY_FAIL",
    "BOTTOM_STRIP_MISS",
    "LOCAL_TAB_MISS",
    "CANDIDATE_DISCARDED",
    "POLICY_DEPRIORITIZED",
    "FOCUS_DRIFT",
    "UNKNOWN",
)

EVENT_TO_SOURCE_FILE = {
    "DISCOVERED": "tools/audit_xml_candidates.py",
    "SELECTED": "tb_runner/local_tab_logic.py",
    "ACTIVATION_ATTEMPT": "tb_runner/local_tab_logic.py",
    "ACTIVATION_SUCCESS": "tb_runner/local_tab_logic.py",
    "ACTIVATION_FAIL": "tb_runner/local_tab_logic.py",
    "FOCUS_CONTEXT_MISMATCH": "tb_runner/focus_realign_logic.py",
    "FOCUS_REALIGN_ATTEMPT": "tb_runner/focus_realign_logic.py",
    "FOCUS_REALIGN_SUCCESS": "tb_runner/focus_realign_logic.py",
    "FOCUS_REALIGN_FAIL": "tb_runner/focus_realign_logic.py",
    "STATE_RECOVERY_ATTEMPT": "tb_runner/local_tab_logic.py",
    "STATE_RECOVERY_SUCCESS": "tb_runner/local_tab_logic.py",
    "STATE_RECOVERY_FAIL": "tb_runner/local_tab_logic.py",
    "LOCAL_TAB_TRANSITION_ATTEMPT": "tb_runner/local_tab_logic.py",
    "LOCAL_TAB_TRANSITION_SUCCESS": "tb_runner/local_tab_logic.py",
    "LOCAL_TAB_TRANSITION_FAIL": "tb_runner/local_tab_logic.py",
    "BOTTOM_STRIP_DEFERRED": "tb_runner/local_tab_logic.py",
    "POLICY_DEPRIORITIZED": "tb_runner/local_tab_logic.py",
    "CANDIDATE_DISCARDED": "tb_runner/local_tab_logic.py",
    "VISITED": "tb_runner/collection_flow.py",
    "MISSED": "tools/audit_v5_traversal_engine.py",
}


@dataclass
class ScenarioArtifact:
    scenario_id: str
    artifact_dir: Path
    log_file: Path | None
    xml_dir: Path | None
    xlsx_file: Path | None


@dataclass
class NormalizedEvent:
    event_id: str
    run_id: str
    scenario_id: str
    plugin_id: str
    phase: str
    event_type: str
    step_index: int | None
    timestamp: str | None
    source_file: str
    source_event_name: str
    candidate_id: str
    stable_label: str
    visible_label: str | None = None
    candidate_type: str | None = None
    candidate_subtype: str | None = None
    bounds: str | None = None
    resource_id: str | None = None
    class_name: str | None = None
    confidence: str = "medium"
    reason: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "plugin_id": self.plugin_id,
            "phase": self.phase,
            "event_type": self.event_type,
            "step_index": self.step_index,
            "timestamp": self.timestamp,
            "source_file": self.source_file,
            "source_event_name": self.source_event_name,
            "candidate_id": self.candidate_id,
            "stable_label": self.stable_label,
            "visible_label": self.visible_label,
            "candidate_type": self.candidate_type,
            "candidate_subtype": self.candidate_subtype,
            "bounds": self.bounds,
            "resource_id": self.resource_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
            "raw_payload": self.raw_payload,
        }


@dataclass
class CandidateLedger:
    candidate_id: str
    scenario_id: str
    plugin_id: str
    stable_label: str
    normalized_label: str
    candidate_type: str | None = None
    candidate_subtype: str | None = None
    policy_recommendation: str | None = None
    bounds: list[str] = field(default_factory=list)
    resource_ids: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    discovered: bool = False
    selected: bool = False
    activation_attempted: bool = False
    activation_succeeded: bool = False
    focus_drifted: bool = False
    realign_attempted: bool = False
    realign_succeeded: bool = False
    state_recovery_attempted: bool = False
    state_recovery_succeeded: bool = False
    local_tab_transition_attempted: bool = False
    local_tab_transition_succeeded: bool = False
    bottom_strip_deferred: bool = False
    policy_deprioritized: bool = False
    candidate_discarded: bool = False
    visited: bool = False
    missed: bool = False
    root_cause: str | None = None
    root_cause_confidence: str = "low"
    event_ids: list[str] = field(default_factory=list)
    last_event_type: str | None = None
    last_step_index: int | None = None
    evidence_sample: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "scenario_id": self.scenario_id,
            "plugin_id": self.plugin_id,
            "stable_label": self.stable_label,
            "normalized_label": self.normalized_label,
            "candidate_type": self.candidate_type,
            "candidate_subtype": self.candidate_subtype,
            "policy_recommendation": self.policy_recommendation,
            "bounds": self.bounds,
            "resource_ids": self.resource_ids,
            "classes": self.classes,
            "discovered": self.discovered,
            "selected": self.selected,
            "activation_attempted": self.activation_attempted,
            "activation_succeeded": self.activation_succeeded,
            "focus_drifted": self.focus_drifted,
            "realign_attempted": self.realign_attempted,
            "realign_succeeded": self.realign_succeeded,
            "state_recovery_attempted": self.state_recovery_attempted,
            "state_recovery_succeeded": self.state_recovery_succeeded,
            "local_tab_transition_attempted": self.local_tab_transition_attempted,
            "local_tab_transition_succeeded": self.local_tab_transition_succeeded,
            "bottom_strip_deferred": self.bottom_strip_deferred,
            "policy_deprioritized": self.policy_deprioritized,
            "candidate_discarded": self.candidate_discarded,
            "visited": self.visited,
            "missed": self.missed,
            "root_cause": self.root_cause,
            "root_cause_confidence": self.root_cause_confidence,
            "event_ids": self.event_ids,
            "last_event_type": self.last_event_type,
            "last_step_index": self.last_step_index,
            "evidence_sample": self.evidence_sample,
        }


class CandidateIndex:
    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        self.by_normalized_label: dict[str, dict[str, Any]] = {}
        self.by_candidate_id: dict[str, dict[str, Any]] = {}

    def add_discovered(self, candidate: dict[str, Any]) -> dict[str, Any]:
        label = str(candidate.get("label") or "").strip()
        metadata = {
            "candidate_id": make_candidate_id(
                self.scenario_id,
                label,
                first_value(candidate.get("resource_ids")),
                first_value(candidate.get("classes")),
                first_value(candidate.get("bounds")),
            ),
            "stable_label": label,
            "normalized_label": normalize_label(label),
            "candidate_type": candidate.get("candidate_type"),
            "candidate_subtype": candidate.get("candidate_subtype"),
            "policy_recommendation": candidate.get("policy_recommendation"),
            "bounds": list_values(candidate.get("bounds")),
            "resource_ids": list_values(candidate.get("resource_ids")),
            "classes": list_values(candidate.get("classes")),
            "xml_dump_count": candidate.get("xml_dump_count"),
            "dump_files": list_values(candidate.get("dump_files")),
            "tabs": list_values(candidate.get("tabs")),
        }
        self.by_candidate_id[metadata["candidate_id"]] = metadata
        if metadata["normalized_label"]:
            self.by_normalized_label.setdefault(metadata["normalized_label"], metadata)
        return metadata

    def match(self, label: str | None, *, resource_id: str | None = None, bounds: str | None = None) -> dict[str, Any]:
        cleaned = clean_log_label(label)
        normalized = normalize_label(cleaned)
        if normalized in self.by_normalized_label:
            return self.by_normalized_label[normalized]

        if normalized:
            for known_label, metadata in self.by_normalized_label.items():
                if normalized in known_label or known_label in normalized:
                    matched = dict(metadata)
                    matched["match_confidence"] = "medium"
                    return matched

        candidate_id = make_candidate_id(self.scenario_id, cleaned or "unknown", resource_id, None, bounds)
        return {
            "candidate_id": candidate_id,
            "stable_label": cleaned or "unknown",
            "normalized_label": normalized,
            "candidate_type": None,
            "candidate_subtype": None,
            "policy_recommendation": None,
            "bounds": [bounds] if bounds else [],
            "resource_ids": [resource_id] if resource_id else [],
            "classes": [],
            "match_confidence": "low",
        }


def normalize_label(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def clean_log_label(value: str | None) -> str:
    text = str(value or "").strip()
    if text in {"", "none", "None", "unknown"}:
        return ""
    return text


def first_value(value: Any) -> str | None:
    values = list_values(value)
    return values[0] if values else None


def list_values(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def make_candidate_id(
    scenario_id: str,
    stable_label: str | None,
    resource_id: str | None = None,
    class_name: str | None = None,
    bounds: str | None = None,
) -> str:
    identity = "|".join(
        [
            normalize_label(stable_label),
            normalize_label(resource_id),
            normalize_label(class_name),
            normalize_label(bounds),
        ]
    )
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"cid:v1:{scenario_id}:{digest}"


def extract_event_name(line: str) -> str | None:
    match = re.search(r"\[STEP\]\[([^\]]+)\]", line)
    if match:
        return match.group(1)
    if "[STEP] END" in line:
        return "STEP END"
    return None


def extract_step(line: str) -> int | None:
    match = re.search(r"\bstep=(\d+)\b", line)
    if match:
        return int(match.group(1))
    return None


def extract_timestamp(line: str) -> str | None:
    match = re.match(r"\[([0-9]{2}:[0-9]{2}:[0-9]{2})\]", line)
    return match.group(1) if match else None


def parse_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, quoted_value in re.findall(r"(\w+)='([^']*)'", line):
        fields[key] = quoted_value
    for key, bare_value in re.findall(r"\b(\w+)=([^\s']+)", line):
        fields.setdefault(key, bare_value)
    return fields


def split_candidate_list(value: str | None) -> list[str]:
    text = clean_log_label(value)
    if not text:
        return []
    if text == "none":
        return []
    return [item.strip() for item in text.split("|") if item.strip() and item.strip().lower() != "none"]


def find_artifacts(artifact_dir: Path) -> list[ScenarioArtifact]:
    root = artifact_dir.resolve()
    scenario_dirs = sorted({path.parent for path in root.rglob("*.normal.log")})
    if not scenario_dirs and (root / "xml_dumps").exists():
        scenario_dirs = [root]
    if not scenario_dirs and list(root.rglob("xml_dumps")):
        scenario_dirs = [root]

    artifacts: list[ScenarioArtifact] = []
    for scenario_dir in scenario_dirs:
        log_files = sorted(scenario_dir.glob("*.normal.log"))
        xlsx_files = sorted(scenario_dir.glob("*.xlsx"))
        xml_dirs = sorted(path for path in scenario_dir.rglob("xml_dumps") if path.is_dir())
        scenario_id = infer_scenario_id(scenario_dir, xml_dirs)
        artifacts.append(
            ScenarioArtifact(
                scenario_id=scenario_id,
                artifact_dir=scenario_dir,
                log_file=log_files[-1] if log_files else None,
                xml_dir=xml_dirs[-1] if xml_dirs else None,
                xlsx_file=xlsx_files[-1] if xlsx_files else None,
            )
        )
    return artifacts


def infer_scenario_id(scenario_dir: Path, xml_dirs: list[Path]) -> str:
    for path in [scenario_dir, *scenario_dir.parents]:
        if path.name.startswith(("life_", "device_")):
            return path.name
    for xml_dir in xml_dirs:
        parent = xml_dir.parent.name
        if parent.startswith(("life_", "device_")):
            return parent
    return scenario_dir.name


def build_event(
    *,
    run_id: str,
    scenario_id: str,
    event_type: str,
    source_event_name: str,
    metadata: dict[str, Any],
    event_index: int,
    step_index: int | None = None,
    timestamp: str | None = None,
    phase: str = "main_loop",
    visible_label: str | None = None,
    confidence: str = "medium",
    reason: str | None = None,
    evidence: dict[str, Any] | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=f"evt-{event_index:06d}",
        run_id=run_id,
        scenario_id=scenario_id,
        plugin_id=scenario_id,
        phase=phase,
        event_type=event_type,
        step_index=step_index,
        timestamp=timestamp,
        source_file=EVENT_TO_SOURCE_FILE.get(event_type, "unknown"),
        source_event_name=source_event_name,
        candidate_id=str(metadata["candidate_id"]),
        stable_label=str(metadata["stable_label"]),
        visible_label=visible_label,
        candidate_type=metadata.get("candidate_type"),
        candidate_subtype=metadata.get("candidate_subtype"),
        bounds=first_value(metadata.get("bounds")),
        resource_id=first_value(metadata.get("resource_ids")),
        class_name=first_value(metadata.get("classes")),
        confidence=confidence,
        reason=reason,
        evidence=evidence or {},
        raw_payload=raw_payload or {},
    )


def build_discovery_events(
    run_id: str,
    scenario: ScenarioArtifact,
    candidate_index: CandidateIndex,
    start_index: int,
) -> tuple[list[NormalizedEvent], int, dict[str, Any]]:
    xml_result = extract_xml_candidates(scenario.xml_dir)
    events: list[NormalizedEvent] = []
    event_index = start_index
    for candidate in xml_result.get("merged_candidates", []):
        metadata = candidate_index.add_discovered(candidate)
        event_index += 1
        events.append(
            build_event(
                run_id=run_id,
                scenario_id=scenario.scenario_id,
                event_type="DISCOVERED",
                source_event_name="merged_candidates",
                metadata=metadata,
                event_index=event_index,
                phase="xml_discovery",
                confidence="high",
                evidence={
                    "xml_dump_count": candidate.get("xml_dump_count"),
                    "dump_files": list_values(candidate.get("dump_files"))[:5],
                    "tabs": list_values(candidate.get("tabs")),
                    "policy_recommendation": candidate.get("policy_recommendation"),
                },
                raw_payload={"candidate": candidate},
            )
        )
    return events, event_index, xml_result


def build_log_events(
    run_id: str,
    scenario: ScenarioArtifact,
    candidate_index: CandidateIndex,
    start_index: int,
) -> tuple[list[NormalizedEvent], int]:
    if not scenario.log_file or not scenario.log_file.exists():
        return [], start_index

    events: list[NormalizedEvent] = []
    event_index = start_index
    lines = scenario.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        source_event = extract_event_name(line)
        if not source_event:
            continue
        fields = parse_fields(line)
        step_index = extract_step(line)
        timestamp = extract_timestamp(line)

        def add(
            event_type: str,
            label: str | None,
            *,
            phase: str = "main_loop",
            reason: str | None = None,
            confidence: str = "high",
            evidence: dict[str, Any] | None = None,
            visible_label: str | None = None,
        ) -> None:
            nonlocal event_index
            metadata = candidate_index.match(label, resource_id=fields.get("rid"), bounds=fields.get("bounds"))
            if metadata.get("match_confidence") == "low" and confidence == "high":
                confidence = "medium"
            event_index += 1
            events.append(
                build_event(
                    run_id=run_id,
                    scenario_id=scenario.scenario_id,
                    event_type=event_type,
                    source_event_name=source_event,
                    metadata=metadata,
                    event_index=event_index,
                    step_index=step_index,
                    timestamp=timestamp,
                    phase=phase,
                    visible_label=visible_label,
                    confidence=confidence,
                    reason=reason,
                    evidence=evidence or dict(fields),
                    raw_payload={"line": line},
                )
            )

        if source_event == "STEP END":
            label = fields.get("visible") or fields.get("speech")
            add("VISITED", label, phase="visit_commit", visible_label=label, evidence={"speech": fields.get("speech")})
        elif source_event == "candidate_priority":
            add(
                "SELECTED",
                fields.get("selected"),
                reason=fields.get("reason"),
                evidence={"content_candidates": fields.get("content_candidates"), **fields},
            )
        elif source_event in {"section_header_deferred", "status_exhausted_excluded"}:
            for label in split_candidate_list(fields.get("candidates") or fields.get("rejected")):
                add(
                    "CANDIDATE_DISCARDED",
                    label,
                    reason=fields.get("reason") or source_event,
                    confidence="medium",
                    evidence=dict(fields),
                )
                add(
                    "POLICY_DEPRIORITIZED",
                    label,
                    reason=fields.get("reason") or source_event,
                    confidence="medium",
                    evidence=dict(fields),
                )
        elif source_event == "bottom_strip_policy":
            for label in split_candidate_list(fields.get("bottom_strip_candidates") or fields.get("candidates")):
                add("BOTTOM_STRIP_DEFERRED", label, reason=fields.get("reason"), evidence=dict(fields))
                add("POLICY_DEPRIORITIZED", label, reason=fields.get("reason"), evidence=dict(fields))
        elif source_event == "focus_context_mismatch":
            add(
                "FOCUS_CONTEXT_MISMATCH",
                fields.get("selected"),
                reason=fields.get("reason"),
                evidence={"current_focus_label": fields.get("current_focus"), **fields},
            )
        elif source_event in {"focus_realign", "focus_force_realign"}:
            add(
                "FOCUS_REALIGN_ATTEMPT",
                fields.get("target"),
                reason=fields.get("reason"),
                evidence={"realign_method": fields.get("method"), **fields},
            )
        elif source_event in {"focus_realign_success", "focus_force_realign_success", "focus_realign_record"}:
            add(
                "FOCUS_REALIGN_SUCCESS",
                fields.get("target") or fields.get("resolved_focus"),
                evidence={"resolved_focus": fields.get("resolved_focus"), **fields},
            )
            if source_event == "focus_realign_record":
                add("VISITED", fields.get("target"), phase="visit_commit", evidence=dict(fields))
        elif source_event in {"focus_realign_fail", "focus_force_realign_fail"}:
            add("FOCUS_REALIGN_FAIL", fields.get("target"), reason=fields.get("reason"), evidence=dict(fields))
        elif source_event in {"local_tab_progression", "local_tab_state_write", "local_tab_select"}:
            if source_event != "local_tab_state_write" or fields.get("kind") == "pending":
                add(
                    "LOCAL_TAB_TRANSITION_ATTEMPT",
                    fields.get("next") or fields.get("selected") or fields.get("target") or fields.get("pending"),
                    phase="local_tab_transition",
                    reason=fields.get("reason"),
                    evidence=dict(fields),
                )
        elif source_event in {"local_tab_commit", "local_tab_force_navigation_resolved"}:
            label = fields.get("target") or fields.get("active") or fields.get("label")
            add("LOCAL_TAB_TRANSITION_SUCCESS", label, phase="local_tab_transition", evidence=dict(fields))
            add("VISITED", label, phase="visit_commit", evidence=dict(fields))
        elif source_event == "local_tab_target_activate":
            add(
                "ACTIVATION_ATTEMPT",
                fields.get("target"),
                phase="activation",
                evidence={"activation_method": fields.get("method"), **fields},
            )
        elif source_event in {"local_tab_target_activate_success"}:
            add("ACTIVATION_SUCCESS", fields.get("target"), phase="activation", evidence=dict(fields))
        elif source_event in {
            "local_tab_target_activate_no_match",
            "local_tab_target_activate_fail",
            "local_tab_target_activate_skip",
        }:
            add("ACTIVATION_FAIL", fields.get("target"), phase="activation", reason=fields.get("reason"), evidence=dict(fields))
        elif source_event == "local_tab_recover":
            label = fields.get("active") or fields.get("target") or fields.get("candidate")
            add("STATE_RECOVERY_ATTEMPT", label, phase="recovery", reason=fields.get("reason"), evidence=dict(fields))
            add("STATE_RECOVERY_SUCCESS", label, phase="recovery", reason=fields.get("reason"), evidence=dict(fields))
        elif source_event in {"local_tab_recover_fail", "local_tab_pending_clear"}:
            label = fields.get("pending") or fields.get("target") or fields.get("active") or "unknown"
            add("STATE_RECOVERY_FAIL", label, phase="recovery", reason=fields.get("reason") or source_event, evidence=dict(fields))
            add(
                "LOCAL_TAB_TRANSITION_FAIL",
                label,
                phase="local_tab_transition",
                reason=fields.get("reason") or source_event,
                confidence="medium",
                evidence=dict(fields),
            )
        elif source_event == "local_tab_gate" and fields.get("allowed") == "false":
            for label in split_candidate_list(fields.get("unvisited") or fields.get("tabs")):
                add(
                    "LOCAL_TAB_TRANSITION_FAIL",
                    label,
                    phase="local_tab_transition",
                    reason=fields.get("reason"),
                    confidence="medium",
                    evidence=dict(fields),
                )
    return events, event_index


def build_xlsx_visit_events(
    run_id: str,
    scenario: ScenarioArtifact,
    candidate_index: CandidateIndex,
    start_index: int,
) -> tuple[list[NormalizedEvent], int, str]:
    if not scenario.xlsx_file or not scenario.xlsx_file.exists():
        return [], start_index, "xlsx_missing"
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return [], start_index, "pandas_unavailable"

    try:
        frame = pd.read_excel(scenario.xlsx_file)
    except Exception as exc:
        return [], start_index, f"xlsx_read_failed:{exc}"

    label_column = None
    for candidate_column in ("visible_label", "visible", "speech", "merged_announcement"):
        if candidate_column in frame.columns:
            label_column = candidate_column
            break
    if not label_column:
        return [], start_index, "xlsx_label_column_missing"

    events: list[NormalizedEvent] = []
    event_index = start_index
    for raw_label in sorted({str(value).strip() for value in frame[label_column].dropna() if str(value).strip()}):
        metadata = candidate_index.match(raw_label)
        event_index += 1
        events.append(
            build_event(
                run_id=run_id,
                scenario_id=scenario.scenario_id,
                event_type="VISITED",
                source_event_name=".xlsx visible_label",
                metadata=metadata,
                event_index=event_index,
                phase="visit_commit",
                visible_label=raw_label,
                confidence="high" if metadata.get("match_confidence") != "low" else "medium",
                evidence={"xlsx_file": str(scenario.xlsx_file), "label_column": label_column},
            )
        )
    return events, event_index, "xlsx_parsed"


def ensure_ledger(ledgers: dict[str, CandidateLedger], event: NormalizedEvent) -> CandidateLedger:
    ledger = ledgers.get(event.candidate_id)
    if ledger:
        return ledger
    ledger = CandidateLedger(
        candidate_id=event.candidate_id,
        scenario_id=event.scenario_id,
        plugin_id=event.plugin_id,
        stable_label=event.stable_label,
        normalized_label=normalize_label(event.stable_label),
        candidate_type=event.candidate_type,
        candidate_subtype=event.candidate_subtype,
        bounds=[event.bounds] if event.bounds else [],
        resource_ids=[event.resource_id] if event.resource_id else [],
        classes=[event.class_name] if event.class_name else [],
    )
    ledgers[event.candidate_id] = ledger
    return ledger


def fold_events(events: list[NormalizedEvent], start_index: int = 0) -> tuple[list[CandidateLedger], list[NormalizedEvent], int]:
    ledgers: dict[str, CandidateLedger] = {}
    events_by_candidate: dict[str, list[NormalizedEvent]] = {}
    for event in events:
        ledger = ensure_ledger(ledgers, event)
        events_by_candidate.setdefault(event.candidate_id, []).append(event)
        ledger.event_ids.append(event.event_id)
        ledger.last_event_type = event.event_type
        ledger.last_step_index = event.step_index if event.step_index is not None else ledger.last_step_index
        if len(ledger.evidence_sample) < 5:
            ledger.evidence_sample.append(
                {
                    "event_type": event.event_type,
                    "source_event_name": event.source_event_name,
                    "step_index": event.step_index,
                    "reason": event.reason,
                    "evidence": event.evidence,
                }
            )

        if event.event_type == "DISCOVERED":
            ledger.discovered = True
            ledger.candidate_type = event.candidate_type
            ledger.candidate_subtype = event.candidate_subtype
            ledger.policy_recommendation = event.evidence.get("policy_recommendation") or ledger.policy_recommendation
            append_unique(ledger.bounds, event.bounds)
            append_unique(ledger.resource_ids, event.resource_id)
            append_unique(ledger.classes, event.class_name)
        elif event.event_type == "SELECTED":
            ledger.selected = True
        elif event.event_type == "ACTIVATION_ATTEMPT":
            ledger.activation_attempted = True
        elif event.event_type == "ACTIVATION_SUCCESS":
            ledger.activation_succeeded = True
        elif event.event_type == "FOCUS_CONTEXT_MISMATCH":
            ledger.focus_drifted = True
        elif event.event_type == "FOCUS_REALIGN_ATTEMPT":
            ledger.realign_attempted = True
        elif event.event_type == "FOCUS_REALIGN_SUCCESS":
            ledger.realign_succeeded = True
        elif event.event_type == "FOCUS_REALIGN_FAIL":
            ledger.realign_attempted = True
        elif event.event_type == "STATE_RECOVERY_ATTEMPT":
            ledger.state_recovery_attempted = True
        elif event.event_type == "STATE_RECOVERY_SUCCESS":
            ledger.state_recovery_succeeded = True
        elif event.event_type == "LOCAL_TAB_TRANSITION_ATTEMPT":
            ledger.selected = True
            ledger.local_tab_transition_attempted = True
        elif event.event_type == "LOCAL_TAB_TRANSITION_SUCCESS":
            ledger.local_tab_transition_succeeded = True
        elif event.event_type == "BOTTOM_STRIP_DEFERRED":
            ledger.bottom_strip_deferred = True
            ledger.policy_deprioritized = True
        elif event.event_type == "POLICY_DEPRIORITIZED":
            ledger.policy_deprioritized = True
        elif event.event_type == "CANDIDATE_DISCARDED":
            ledger.candidate_discarded = True
        elif event.event_type == "VISITED":
            ledger.visited = True
        elif event.event_type == "STATE_RECOVERY_FAIL":
            ledger.state_recovery_attempted = True
        elif event.event_type == "LOCAL_TAB_TRANSITION_FAIL":
            ledger.local_tab_transition_attempted = True

    missed_events: list[NormalizedEvent] = []
    event_index = start_index
    for ledger in ledgers.values():
        if not ledger.discovered:
            continue
        ledger.missed = not ledger.visited
        if not ledger.missed:
            ledger.root_cause = None
            ledger.root_cause_confidence = "high"
            continue
        candidate_events = events_by_candidate.get(ledger.candidate_id, [])
        ledger.root_cause, ledger.root_cause_confidence = attribute_root_cause(ledger, candidate_events)
        event_index += 1
        missed = NormalizedEvent(
            event_id=f"evt-{event_index:06d}",
            run_id=candidate_events[0].run_id if candidate_events else "",
            scenario_id=ledger.scenario_id,
            plugin_id=ledger.plugin_id,
            phase="post_analysis",
            event_type="MISSED",
            step_index=ledger.last_step_index,
            timestamp=None,
            source_file=EVENT_TO_SOURCE_FILE["MISSED"],
            source_event_name="derived_ledger_terminal_state",
            candidate_id=ledger.candidate_id,
            stable_label=ledger.stable_label,
            candidate_type=ledger.candidate_type,
            candidate_subtype=ledger.candidate_subtype,
            bounds=first_value(ledger.bounds),
            resource_id=first_value(ledger.resource_ids),
            class_name=first_value(ledger.classes),
            confidence=ledger.root_cause_confidence,
            reason=ledger.root_cause,
            evidence={"root_cause": ledger.root_cause, "event_ids": ledger.event_ids[-5:]},
        )
        ledger.event_ids.append(missed.event_id)
        ledger.last_event_type = "MISSED"
        missed_events.append(missed)
    return sorted(ledgers.values(), key=lambda item: (item.scenario_id, item.stable_label)), missed_events, event_index


def append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)


def has_event(events: list[NormalizedEvent], event_type: str) -> bool:
    return any(event.event_type == event_type for event in events)


def has_later_success(events: list[NormalizedEvent], success_type: str, fail_type: str) -> bool:
    last_fail = max((index for index, event in enumerate(events) if event.event_type == fail_type), default=-1)
    return any(index > last_fail and event.event_type in {success_type, "VISITED"} for index, event in enumerate(events))


def attribute_root_cause(ledger: CandidateLedger, events: list[NormalizedEvent]) -> tuple[str, str]:
    if has_event(events, "ACTIVATION_FAIL") and not has_later_success(events, "ACTIVATION_SUCCESS", "ACTIVATION_FAIL"):
        return "ACTIVATION_FAIL", "high"
    if has_event(events, "FOCUS_REALIGN_FAIL") and not has_later_success(events, "FOCUS_REALIGN_SUCCESS", "FOCUS_REALIGN_FAIL"):
        return "REALIGN_FAIL", "high"
    if has_event(events, "STATE_RECOVERY_FAIL") and not ledger.state_recovery_succeeded:
        return "STATE_RECOVERY_FAIL", "high"
    if ledger.bottom_strip_deferred:
        return "BOTTOM_STRIP_MISS", "medium"
    if has_event(events, "LOCAL_TAB_TRANSITION_FAIL") or (
        ledger.local_tab_transition_attempted and not ledger.local_tab_transition_succeeded
    ):
        return "LOCAL_TAB_MISS", "medium"
    if ledger.candidate_discarded and not ledger.selected:
        return "CANDIDATE_DISCARDED", "medium"
    if ledger.policy_deprioritized and not ledger.activation_attempted and not ledger.selected:
        return "POLICY_DEPRIORITIZED", "medium"
    if ledger.focus_drifted and not ledger.realign_succeeded:
        return "FOCUS_DRIFT", "medium"
    return "UNKNOWN", "low"


def summarize_metrics(events: list[NormalizedEvent], ledgers: list[CandidateLedger]) -> dict[str, Any]:
    discovered_count = sum(1 for ledger in ledgers if ledger.discovered)
    selected_count = sum(1 for ledger in ledgers if ledger.selected)
    visited_count = sum(1 for ledger in ledgers if ledger.visited)
    missed_count = sum(1 for ledger in ledgers if ledger.missed)
    activation_attempt_count = sum(1 for event in events if event.event_type == "ACTIVATION_ATTEMPT")
    activation_success_count = sum(1 for event in events if event.event_type == "ACTIVATION_SUCCESS")
    unknown_miss_count = sum(1 for ledger in ledgers if ledger.missed and ledger.root_cause == "UNKNOWN")
    return {
        "discovered_count": discovered_count,
        "selected_count": selected_count,
        "activation_attempt_count": activation_attempt_count,
        "activation_success_count": activation_success_count,
        "visited_count": visited_count,
        "missed_count": missed_count,
        "unknown_miss_count": unknown_miss_count,
        "activation_success_rate": safe_rate(activation_success_count, activation_attempt_count),
        "visit_rate": safe_rate(visited_count, discovered_count),
        "miss_attribution_rate": safe_rate(missed_count - unknown_miss_count, missed_count),
    }


def safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def root_cause_summary(ledgers: list[CandidateLedger]) -> dict[str, int]:
    summary = {cause: 0 for cause in ROOT_CAUSE_PRIORITY}
    for ledger in ledgers:
        if ledger.missed:
            summary[ledger.root_cause or "UNKNOWN"] = summary.get(ledger.root_cause or "UNKNOWN", 0) + 1
    return summary


def build_report(artifact_dir: Path) -> dict[str, Any]:
    run_id = f"audit_v5_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    scenarios = find_artifacts(artifact_dir)
    all_events: list[NormalizedEvent] = []
    all_ledgers: list[CandidateLedger] = []
    scenario_summaries: list[dict[str, Any]] = []
    event_index = 0
    loader_status: dict[str, Any] = {}

    for scenario in scenarios:
        candidate_index = CandidateIndex(scenario.scenario_id)
        discovery_events, event_index, xml_result = build_discovery_events(run_id, scenario, candidate_index, event_index)
        log_events, event_index = build_log_events(run_id, scenario, candidate_index, event_index)
        xlsx_events, event_index, xlsx_status = build_xlsx_visit_events(run_id, scenario, candidate_index, event_index)
        scenario_events = discovery_events + log_events + xlsx_events
        scenario_ledgers, missed_events, event_index = fold_events(scenario_events, event_index)
        scenario_events = scenario_events + missed_events
        metrics = summarize_metrics(scenario_events, scenario_ledgers)
        causes = root_cause_summary(scenario_ledgers)

        loader_status[scenario.scenario_id] = {
            "artifact_dir": str(scenario.artifact_dir),
            "log_file": str(scenario.log_file) if scenario.log_file else None,
            "xml_dir": str(scenario.xml_dir) if scenario.xml_dir else None,
            "xlsx_file": str(scenario.xlsx_file) if scenario.xlsx_file else None,
            "xml_diagnostic_status": xml_result.get("xml_diagnostic_status"),
            "xlsx_status": xlsx_status,
        }
        scenario_summaries.append(
            {
                "scenario_id": scenario.scenario_id,
                "plugin_id": scenario.scenario_id,
                **metrics,
                "top_root_causes": {cause: count for cause, count in causes.items() if count},
            }
        )
        all_events.extend(scenario_events)
        all_ledgers.extend(scenario_ledgers)

    metrics = summarize_metrics(all_events, all_ledgers)
    causes = root_cause_summary(all_ledgers)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_metadata": {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_output_dir": str(artifact_dir),
            "scenario_ids": [scenario.scenario_id for scenario in scenarios],
            "tool_version": TOOL_VERSION,
            "v3_authoritative": True,
            "shadow_policy_name": "balanced_v1",
            "runner_behavior_changed": False,
            "loader_status": loader_status,
        },
        "scenario_summaries": scenario_summaries,
        "candidate_ledgers": [ledger.to_dict() for ledger in all_ledgers],
        "event_samples": [event.to_dict() for event in sample_events(all_events)],
        "root_cause_summary": causes,
        "metrics": metrics,
    }


def sample_events(events: list[NormalizedEvent], limit: int = 100) -> list[NormalizedEvent]:
    priority = {
        "ACTIVATION_FAIL",
        "FOCUS_REALIGN_FAIL",
        "STATE_RECOVERY_FAIL",
        "LOCAL_TAB_TRANSITION_FAIL",
        "BOTTOM_STRIP_DEFERRED",
        "POLICY_DEPRIORITIZED",
        "CANDIDATE_DISCARDED",
        "MISSED",
    }
    selected = [event for event in events if event.event_type in priority]
    selected.extend(event for event in events if event.event_type not in priority)
    return selected[:limit]

