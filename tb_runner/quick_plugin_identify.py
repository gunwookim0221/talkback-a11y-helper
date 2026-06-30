from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from tb_runner import device_tab_logic
from tb_runner.device_inventory import _client_scroll_down
from tb_runner.plugin_card_discovery import parse_uiautomator_xml
from tb_runner.v10_preparation import V10_ARTIFACT_ROOT

IDENTIFY_SCHEMA_VERSION = "v10-quick-identify-result-v1"
IDENTIFY_ARTIFACT_VERSION = "v10-identify-artifact-v1"
ALLOWED_DECISIONS = {"identified", "unknown", "ambiguous", "failed"}

Clock = Callable[[], datetime]
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class FamilySignature:
    family: str
    resource_patterns: tuple[str, ...]
    structure_patterns: tuple[str, ...]
    header_patterns: tuple[str, ...]
    label_patterns: tuple[str, ...]


SIGNATURES = (
    FamilySignature(
        "MotionSensorCapability",
        (r"motionsensorcapabilitycardview",),
        (r"motion.*sensor.*capability",),
        (r"\bmotion\b", r"움직임", r"모션"),
        (r"\bmotion\b", r"움직임", r"모션"),
    ),
    FamilySignature(
        "GenericLockCapability",
        (r"(?:generic)?lockcapabilitycardview", r"doorlockcapabilitycardview"),
        (r"(?:door)?lock.*capability",),
        (r"\blocked\b", r"\bunlocked\b", r"잠김", r"열림"),
        (r"\block\b", r"도어락", r"잠금"),
    ),
    FamilySignature(
        "SmokeDetectorCapability",
        (r"smoke(?:sensor|detector)capabilitycardview",),
        (r"smoke.*(?:sensor|detector).*capability",),
        (r"\bsmoke\b", r"연기"),
        (r"\bsmoke\b", r"연기"),
    ),
    FamilySignature(
        "LeakSensorCapability",
        (r"water(?:sensor|leak)capabilitycardview", r"leaksensorcapabilitycardview"),
        (r"(?:water|leak).*(?:sensor|capability)",),
        (r"\b(?:wet|dry|leak)\b", r"누수", r"물기"),
        (r"\b(?:water leak|leak)\b", r"누수"),
    ),
    FamilySignature(
        "LaundryWasherCapability",
        (r"laundrywasher[a-z0-9_]*capabilitycardview", r"washercapabilitycardview"),
        (r"washer.*(?:cycle|rinse|spin|capability)",),
        (r"\b(?:cycle|rinse|spin|washer)\b", r"세탁", r"헹굼", r"탈수"),
        (r"\bwasher\b", r"세탁기"),
    ),
    FamilySignature(
        "TVCapabilitySet",
        (r"tv[a-z0-9_]*capabilitycardview", r"(?:remote|channel|source|volume)capabilitycardview"),
        (r"(?:remote|channel|source).*(?:volume|channel|source)",),
        (r"\b(?:channel|source|volume|remote)\b", r"채널", r"외부입력", r"볼륨"),
        (r"\b(?:tv|television)\b", r"티비", r"텔레비전"),
    ),
)


@dataclass(frozen=True)
class IdentifyEvidence:
    evidence_id: str
    source: str
    kind: str
    observed_value: str
    polarity: str
    candidate_types: list[str]
    weight: int
    reliability: str
    reason: str


@dataclass
class CandidateScore:
    plugin_family: str
    score: int = 0
    confidence_band: str = "unknown"
    positive_evidence_ids: list[str] = field(default_factory=list)
    negative_evidence_ids: list[str] = field(default_factory=list)
    quality_gate_passed: bool = False
    sources: list[str] = field(default_factory=list)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _flatten(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    queue = [node for node in nodes if isinstance(node, dict)]
    while queue:
        node = queue.pop(0)
        result.append(node)
        children = node.get("children")
        if isinstance(children, list):
            queue.extend(child for child in children if isinstance(child, dict))
    return result


def _node_resource_id(node: Mapping[str, Any]) -> str:
    for key in ("viewIdResourceName", "resourceId", "resource-id", "resource_id", "id"):
        value = _text(node.get(key))
        if value:
            return value
    return ""


def _node_labels(node: Mapping[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for key in ("text", "contentDescription", "content-desc", "mergedLabel"):
        value = _text(node.get(key))
        if value:
            values.append(("representative_label", value))
    for key in ("talkbackLabel", "mergedAnnouncement", "announcement"):
        value = _text(node.get(key))
        if value:
            values.append(("talkback_speech", value))
    return values


def _matches_any(patterns: tuple[str, ...], value: str) -> bool:
    return any(re.search(pattern, value, re.IGNORECASE) for pattern in patterns)


def _band(score: int) -> str:
    if score >= 95:
        return "definite"
    if score >= 80:
        return "high"
    if score >= 60:
        return "medium"
    if score >= 40:
        return "low"
    return "unknown"


def _add_evidence(
    evidence: list[IdentifyEvidence],
    seen: set[tuple[str, str, str, str]],
    *,
    source: str,
    kind: str,
    observed_value: str,
    candidates: list[str],
    weight: int,
    reliability: str,
    reason: str,
) -> None:
    key = (source, kind, observed_value.lower(), "|".join(sorted(candidates)))
    if key in seen:
        return
    seen.add(key)
    evidence.append(
        IdentifyEvidence(
            evidence_id=f"evidence-{len(evidence) + 1:04d}",
            source=source,
            kind=kind,
            observed_value=observed_value,
            polarity="positive",
            candidate_types=candidates,
            weight=weight,
            reliability=reliability,
            reason=reason,
        )
    )


def collect_identify_evidence(
    helper_nodes: list[dict[str, Any]],
    xml_text: str,
    inventory_item: Mapping[str, Any],
    *,
    talkback_speech: str = "",
) -> list[IdentifyEvidence]:
    evidence: list[IdentifyEvidence] = []
    seen: set[tuple[str, str, str, str]] = set()
    xml_nodes = parse_uiautomator_xml(xml_text) if _text(xml_text) else []

    for source, nodes in (("helper", _flatten(helper_nodes)), ("xml", _flatten(xml_nodes))):
        resource_ids = sorted({_node_resource_id(node) for node in nodes if _node_resource_id(node)})
        labels = [entry for node in nodes for entry in _node_labels(node)]
        source_blob = " ".join(resource_ids + [value for _, value in labels])
        for signature in SIGNATURES:
            matched_resources = [
                resource_id
                for resource_id in resource_ids
                if _matches_any(signature.resource_patterns, resource_id)
            ]
            for resource_id in matched_resources:
                kind = "capability_header" if "header" in resource_id.lower() else "capability_resource_id"
                _add_evidence(
                    evidence,
                    seen,
                    source=source,
                    kind=kind,
                    observed_value=resource_id,
                    candidates=[signature.family],
                    weight=55 if kind == "capability_resource_id" else 35,
                    reliability="very_high" if kind == "capability_resource_id" else "high",
                    reason="family-specific capability resource signature",
                )
            if _matches_any(signature.structure_patterns, source_blob) and len(matched_resources) >= 2:
                _add_evidence(
                    evidence,
                    seen,
                    source=source,
                    kind="xml_structure" if source == "xml" else "helper_structure",
                    observed_value=f"{signature.family}:family_subtree",
                    candidates=[signature.family],
                    weight=30,
                    reliability="high",
                    reason="multiple family-consistent structural signals",
                )
            for label_kind, label in labels:
                if not _matches_any(signature.header_patterns, label):
                    continue
                _add_evidence(
                    evidence,
                    seen,
                    source=source,
                    kind="talkback_speech" if label_kind == "talkback_speech" else "representative_label",
                    observed_value=label,
                    candidates=[signature.family],
                    weight=15 if label_kind == "talkback_speech" else 18,
                    reliability="medium",
                    reason="family-consistent semantic label",
                )

    if _text(talkback_speech):
        for signature in SIGNATURES:
            if _matches_any(signature.label_patterns, talkback_speech):
                _add_evidence(
                    evidence,
                    seen,
                    source="talkback",
                    kind="talkback_speech",
                    observed_value=_text(talkback_speech),
                    candidates=[signature.family],
                    weight=15,
                    reliability="medium",
                    reason="captured TalkBack announcement",
                )

    display_name = _text(inventory_item.get("display_label") or inventory_item.get("stable_label"))
    if display_name:
        matched = [
            signature.family
            for signature in SIGNATURES
            if _matches_any(signature.label_patterns, display_name)
        ]
        _add_evidence(
            evidence,
            seen,
            source="inventory",
            kind="display_name",
            observed_value=display_name,
            candidates=matched,
            weight=5 if matched else 0,
            reliability="low",
            reason="locator hint only; never satisfies the structural quality gate",
        )
    return evidence


def classify_plugin_family(evidence: list[IdentifyEvidence]) -> dict[str, Any]:
    candidates = {signature.family: CandidateScore(signature.family) for signature in SIGNATURES}
    structural_kinds = {
        "capability_resource_id",
        "capability_header",
        "xml_structure",
        "helper_structure",
    }
    strong_families: set[str] = set()

    for record in evidence:
        for family in record.candidate_types:
            candidate = candidates.get(family)
            if candidate is None:
                continue
            candidate.positive_evidence_ids.append(record.evidence_id)
            if record.source not in candidate.sources:
                candidate.sources.append(record.source)
            if record.kind in structural_kinds:
                candidate.quality_gate_passed = True
                if record.reliability in {"very_high", "high"}:
                    strong_families.add(family)

    for candidate in candidates.values():
        records = [record for record in evidence if candidate.plugin_family in record.candidate_types]
        structural = [record for record in records if record.kind in structural_kinds]
        weak = [record for record in records if record.kind not in structural_kinds]
        structural_sources = {record.source for record in structural}
        has_very_high = any(record.reliability == "very_high" for record in structural)
        has_high = any(record.reliability == "high" for record in structural)
        weak_support = min(12, sum(record.weight for record in weak))

        if len(structural_sources) >= 2 and has_very_high:
            candidate.score = min(100, 95 + min(5, weak_support))
        elif has_very_high:
            candidate.score = min(94, 82 + weak_support)
        elif has_high:
            candidate.score = min(84, 72 + weak_support)
        else:
            candidate.score = min(39, weak_support)
        candidate.confidence_band = _band(candidate.score)

    ranked = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
    top, second = ranked[:2]
    contradictions: list[str] = []
    if len(strong_families) > 1:
        contradictions.append("conflicting_structural_families:" + ",".join(sorted(strong_families)))

    close_structural_candidates = (
        top.quality_gate_passed
        and second.quality_gate_passed
        and top.score >= 80
        and second.score >= 80
        and top.score - second.score < 15
    )
    if contradictions or close_structural_candidates:
        decision, family, confidence, confidence_band = "ambiguous", "unknown", 0, "unknown"
    elif top.quality_gate_passed and top.score >= 80:
        decision = "identified"
        family = top.plugin_family
        confidence = top.score
        confidence_band = top.confidence_band
    else:
        decision = "unknown"
        family = "unknown"
        confidence = top.score
        confidence_band = top.confidence_band if top.score else "unknown"

    return {
        "decision": decision,
        "plugin_family_candidate": family,
        "confidence": confidence,
        "confidence_band": confidence_band,
        "candidates": [asdict(candidate) for candidate in ranked if candidate.score > 0],
        "contradictions": contradictions,
    }


def _result(
    *,
    inventory_id: str,
    runtime_card_id: str,
    started: datetime,
    completed: datetime,
    decision: str,
    plugin_family_candidate: str = "unknown",
    confidence: int = 0,
    confidence_band: str = "unknown",
    evidence: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    contradictions: list[str] | None = None,
    errors: list[str] | None = None,
    restore_success: bool = False,
    snapshot_refs: Mapping[str, Any] | None = None,
    stabilization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"unsupported identify decision: {decision}")
    duration = max(0.0, (completed - started).total_seconds())
    return {
        "schema_version": IDENTIFY_SCHEMA_VERSION,
        "artifact_version": IDENTIFY_ARTIFACT_VERSION,
        "identify_run_id": f"identify-{uuid.uuid4().hex[:12]}",
        "inventory_id": inventory_id,
        "runtime_card_id": runtime_card_id,
        "plugin_family_candidate": plugin_family_candidate,
        "confidence": int(max(0, min(100, confidence))),
        "confidence_band": confidence_band,
        "decision": decision,
        "evidence": list(evidence or []),
        "candidates": list(candidates or []),
        "contradictions": list(contradictions or []),
        "snapshot_timestamp": _timestamp(completed),
        "started_at": _timestamp(started),
        "completed_at": _timestamp(completed),
        "identify_duration": duration,
        "identify_duration_ms": int(duration * 1000),
        "restore_success": bool(restore_success),
        "snapshot_refs": dict(snapshot_refs or {}),
        "stabilization": dict(stabilization or {}),
        "errors": list(errors or []),
    }


def identify_from_snapshots(
    inventory: Mapping[str, Any],
    runtime_card_id: str,
    *,
    helper_nodes: list[dict[str, Any]],
    xml_text: str,
    talkback_speech: str = "",
    restore_success: bool = True,
    clock: Clock = _utc_now,
) -> dict[str, Any]:
    started = clock()
    items = [
        item
        for item in inventory.get("items", [])
        if isinstance(item, Mapping) and item.get("runtime_card_id") == runtime_card_id
    ]
    if len(items) != 1:
        return _result(
            inventory_id=_text(inventory.get("inventory_id")),
            runtime_card_id=runtime_card_id,
            started=started,
            completed=clock(),
            decision="ambiguous" if len(items) > 1 else "unknown",
            errors=["runtime_card_not_unique" if len(items) > 1 else "runtime_card_not_found"],
            restore_success=restore_success,
        )

    evidence = collect_identify_evidence(
        helper_nodes,
        xml_text,
        items[0],
        talkback_speech=talkback_speech,
    )
    classification = classify_plugin_family(evidence)
    completed = clock()
    decision = classification["decision"] if restore_success else "failed"
    return _result(
        inventory_id=_text(inventory.get("inventory_id")),
        runtime_card_id=runtime_card_id,
        started=started,
        completed=completed,
        decision=decision,
        plugin_family_candidate=classification["plugin_family_candidate"],
        confidence=classification["confidence"],
        confidence_band=classification["confidence_band"],
        evidence=[asdict(record) for record in evidence],
        candidates=classification["candidates"],
        contradictions=classification["contradictions"],
        errors=[] if restore_success else ["inventory_restore_failed"],
        restore_success=restore_success,
    )


def _capture_helper(client: Any, dev: str | None) -> tuple[list[dict[str, Any]], str]:
    dump_tree = getattr(client, "dump_tree", None)
    if not callable(dump_tree):
        return [], "helper_dump_unavailable"
    try:
        payload = dump_tree(dev=dev)
    except Exception as exc:
        return [], f"helper_dump_failed:{exc}"
    if isinstance(payload, Mapping) and isinstance(payload.get("nodes"), list):
        payload = payload["nodes"]
    nodes = [node for node in payload if isinstance(node, dict)] if isinstance(payload, list) else []
    return nodes, ""


def _structural_snapshot_signature(nodes: list[dict[str, Any]]) -> str:
    resource_ids = sorted(
        {
            resource_id
            for node in _flatten(nodes)
            if (resource_id := _node_resource_id(node))
        }
    )
    if not resource_ids:
        return ""
    return hashlib.sha256("|".join(resource_ids).encode("utf-8")).hexdigest()


def _capture_stable_helper(
    client: Any,
    dev: str | None,
    *,
    sleep: Sleep,
    max_attempts: int = 3,
    settle_seconds: float = 0.25,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    previous_signature = ""
    latest_nodes: list[dict[str, Any]] = []
    errors: list[str] = []
    attempts = max(2, min(4, int(max_attempts)))
    for attempt in range(1, attempts + 1):
        latest_nodes, error = _capture_helper(client, dev)
        if error:
            errors.append(error)
        signature = _structural_snapshot_signature(latest_nodes)
        if signature and signature == previous_signature:
            return latest_nodes, {
                "status": "stable",
                "attempts": attempt,
                "signature": signature,
            }, ""
        previous_signature = signature
        if attempt < attempts:
            sleep(max(0.0, settle_seconds))
    return latest_nodes, {
        "status": "unstable",
        "attempts": attempts,
        "signature": previous_signature,
    }, errors[-1] if errors else "screen_stabilization_unconfirmed"


def _capture_xml(client: Any, dev: str | None) -> tuple[str, str]:
    run = getattr(client, "_run", None)
    if not callable(run):
        return "", "xml_dump_unavailable"
    remote = f"/sdcard/v10_quick_identify_{uuid.uuid4().hex[:8]}.xml"
    try:
        run(["shell", "uiautomator", "dump", remote], dev=dev)
        xml_text = str(run(["shell", "cat", remote], dev=dev) or "")
        return xml_text, "" if xml_text.strip() else "xml_dump_empty"
    except Exception as exc:
        return "", f"xml_dump_failed:{exc}"
    finally:
        try:
            run(["shell", "rm", "-f", remote], dev=dev)
        except Exception:
            pass


def _candidate_values(card: Mapping[str, Any]) -> dict[str, str]:
    return {
        "stable_label": _text(card.get("stable_label")),
        "display_label": _text(card.get("label")),
        "resource_id": _text(card.get("resource_id") or card.get("rid")),
        "class_name": _text(card.get("class_name")),
        "bounds": _text(card.get("bounds")),
    }


def _locate_inventory_item(
    nodes: list[dict[str, Any]],
    item: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    expected = {
        "stable_label": _text(item.get("stable_label")),
        "display_label": _text(item.get("display_label")),
        "resource_id": _text(item.get("resource_id")),
        "class_name": _text(item.get("class_name")),
        "bounds": _text(item.get("bounds")),
    }
    ranked: list[tuple[int, dict[str, Any]]] = []
    for card in device_tab_logic.collect_visible_device_cards(nodes):
        actual = _candidate_values(card)
        score = 0
        score += 4 if expected["resource_id"] and actual["resource_id"] == expected["resource_id"] else 0
        score += 3 if expected["class_name"] and actual["class_name"] == expected["class_name"] else 0
        score += 3 if expected["stable_label"] and actual["stable_label"] == expected["stable_label"] else 0
        score += 2 if expected["display_label"] and actual["display_label"] == expected["display_label"] else 0
        score += 2 if expected["bounds"] and actual["bounds"] == expected["bounds"] else 0
        if score >= 7:
            ranked.append((score, card))
    if not ranked:
        return None, "runtime_card_not_visible"
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None, "runtime_card_ambiguous"
    return ranked[0][1], ""


def _viewport_signature(nodes: list[dict[str, Any]]) -> str:
    cards = device_tab_logic.collect_visible_device_cards(nodes)
    values = [
        "|".join(
            (
                _text(card.get("stable_label")),
                _text(card.get("resource_id") or card.get("rid")),
                _text(card.get("bounds")),
            )
        )
        for card in cards
    ]
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def _locate_inventory_item_bounded(
    client: Any,
    dev: str | None,
    item: Mapping[str, Any],
    *,
    sleep: Sleep,
    max_scrolls: int,
    settle_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    scroll_to_top = getattr(client, "scroll_to_top", None)
    if callable(scroll_to_top):
        try:
            scroll_to_top(dev=dev, max_swipes=max(1, max_scrolls + 1), pause=0.2)
        except Exception:
            pass

    expected_viewports = {
        int(value)
        for value in item.get("observed_viewport_indexes", [])
        if isinstance(value, int) and value >= 0
    }
    if not expected_viewports:
        expected_viewports = {max(0, int(item.get("viewport_index", 0) or 0))}

    seen: set[str] = set()
    latest_nodes: list[dict[str, Any]] = []
    for viewport_index in range(max(0, int(max_scrolls)) + 1):
        latest_nodes, capture_error = _capture_helper(client, dev)
        if capture_error:
            return latest_nodes, None, capture_error
        signature = _viewport_signature(latest_nodes)
        if signature in seen:
            return latest_nodes, None, "runtime_card_viewport_repeated"
        seen.add(signature)

        if viewport_index in expected_viewports:
            card, locate_error = _locate_inventory_item(latest_nodes, item)
            if card is not None or locate_error == "runtime_card_ambiguous":
                return latest_nodes, card, locate_error

        if viewport_index >= max_scrolls:
            break
        if not _client_scroll_down(client, dev, latest_nodes):
            return latest_nodes, None, "runtime_card_scroll_exhausted"
        sleep(max(0.0, settle_seconds))
    return latest_nodes, None, "runtime_card_not_found_within_bound"


def _tap_card(client: Any, dev: str | None, card: Mapping[str, Any], nodes: list[dict[str, Any]]) -> bool:
    match = re.fullmatch(r"(\d+),(\d+),(\d+),(\d+)", _text(card.get("bounds")))
    if not match:
        return False
    bounds = tuple(int(value) for value in match.groups())
    avoid = [
        candidate.get("bounds", "")
        for candidate in device_tab_logic.collect_device_card_tap_avoid_bounds(nodes)
    ]
    point = device_tab_logic.compute_safe_device_card_tap_point(bounds, avoid)
    if not point:
        return False
    tap = getattr(client, "tap_xy_adb", None)
    if not callable(tap):
        tap = getattr(client, "touch_point", None)
    return bool(tap(dev=dev, x=int(point["x"]), y=int(point["y"]))) if callable(tap) else False


def _send_back(client: Any, dev: str | None) -> bool:
    run = getattr(client, "_run", None)
    if not callable(run):
        return False
    try:
        run(["shell", "input", "keyevent", "4"], dev=dev, timeout=5.0)
        return True
    except Exception:
        return False


def _snapshot_hash(value: Any) -> str:
    serialized = (
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        if not isinstance(value, str)
        else value
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def write_identify_artifact(
    result: Mapping[str, Any],
    *,
    artifact_dir: str | Path = V10_ARTIFACT_ROOT / "identify",
) -> Path:
    output_dir = Path(artifact_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{result.get('identify_run_id', 'identify-unknown')}.json"
    output_path.write_text(
        json.dumps(dict(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _lifecycle_failure(
    inventory: Mapping[str, Any],
    runtime_card_id: str,
    started: datetime,
    clock: Clock,
    decision: str,
    errors: list[str],
    artifact_dir: str | Path,
) -> dict[str, Any]:
    result = _result(
        inventory_id=_text(inventory.get("inventory_id")),
        runtime_card_id=runtime_card_id,
        started=started,
        completed=clock(),
        decision=decision,
        errors=errors,
        restore_success=False,
    )
    path = write_identify_artifact(result, artifact_dir=artifact_dir)
    return {"status": decision, "result": result, "artifact_path": str(path)}


def run_quick_identify_if_enabled(
    client: Any,
    dev: str | None,
    v10_config: Mapping[str, Any] | None,
    inventory: Mapping[str, Any],
    runtime_card_id: str,
    *,
    artifact_dir: str | Path = V10_ARTIFACT_ROOT / "identify",
    stabilize_seconds: float = 1.2,
    restore_seconds: float = 0.8,
    locate_max_scrolls: int = 6,
    locate_scroll_settle_seconds: float = 0.5,
    clock: Clock = _utc_now,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    raw = v10_config if isinstance(v10_config, Mapping) else {}
    flags = raw.get("feature_flags") if isinstance(raw.get("feature_flags"), Mapping) else {}
    if flags.get("quick_identify_enabled") is not True:
        return {"status": "disabled", "result": None, "artifact_path": ""}

    started = clock()
    items = [
        item
        for item in inventory.get("items", [])
        if isinstance(item, Mapping) and item.get("runtime_card_id") == runtime_card_id
    ]
    if len(items) != 1:
        return _lifecycle_failure(
            inventory,
            runtime_card_id,
            started,
            clock,
            "ambiguous" if len(items) > 1 else "unknown",
            ["runtime_card_not_unique" if len(items) > 1 else "runtime_card_not_found"],
            artifact_dir,
        )

    item = items[0]
    before_nodes, card, locate_error = _locate_inventory_item_bounded(
        client,
        dev,
        item,
        sleep=sleep,
        max_scrolls=locate_max_scrolls,
        settle_seconds=locate_scroll_settle_seconds,
    )
    if locate_error or card is None:
        return _lifecycle_failure(
            inventory,
            runtime_card_id,
            started,
            clock,
            "ambiguous" if locate_error == "runtime_card_ambiguous" else "unknown",
            [locate_error] if locate_error else ["runtime_card_not_found"],
            artifact_dir,
        )
    if not _tap_card(client, dev, card, before_nodes):
        return _lifecycle_failure(
            inventory,
            runtime_card_id,
            started,
            clock,
            "failed",
            ["card_open_failed"],
            artifact_dir,
        )

    talkback_speech = _text(
        getattr(client, "last_merged_announcement", "")
        or " ".join(getattr(client, "last_announcements", []) or [])
    )
    sleep(max(0.0, stabilize_seconds))
    helper_nodes, stabilization, helper_error = _capture_stable_helper(
        client,
        dev,
        sleep=sleep,
    )
    xml_text, xml_error = _capture_xml(client, dev)

    back_sent = _send_back(client, dev)
    sleep(max(0.0, restore_seconds))
    restored_nodes, restore_error = _capture_helper(client, dev)
    restored_card, restored_locate_error = _locate_inventory_item(restored_nodes, item)
    location_state = device_tab_logic.detect_selected_device_location(restored_nodes)
    restore_success = bool(
        back_sent
        and not restore_error
        and not restored_locate_error
        and restored_card is not None
        and location_state.get("selected")
    )

    evidence = collect_identify_evidence(
        helper_nodes,
        xml_text,
        item,
        talkback_speech=talkback_speech,
    )
    classification = classify_plugin_family(evidence)
    errors = [error for error in (helper_error, xml_error) if error]
    if stabilization.get("status") != "stable":
        errors.append("screen_stabilization_unconfirmed")
    if not restore_success:
        errors.append("inventory_restore_failed")
    if not restore_success:
        decision = "failed"
    elif stabilization.get("status") != "stable":
        decision = "unknown"
    else:
        decision = classification["decision"]
    result = _result(
        inventory_id=_text(inventory.get("inventory_id")),
        runtime_card_id=runtime_card_id,
        started=started,
        completed=clock(),
        decision=decision,
        plugin_family_candidate=classification["plugin_family_candidate"],
        confidence=classification["confidence"],
        confidence_band=classification["confidence_band"],
        evidence=[asdict(record) for record in evidence],
        candidates=classification["candidates"],
        contradictions=classification["contradictions"],
        errors=errors,
        restore_success=restore_success,
        snapshot_refs={
            "helper_sha256": _snapshot_hash(helper_nodes) if helper_nodes else "",
            "xml_sha256": _snapshot_hash(xml_text) if xml_text else "",
        },
        stabilization=stabilization,
    )
    path = write_identify_artifact(result, artifact_dir=artifact_dir)
    return {"status": decision, "result": result, "artifact_path": str(path)}
