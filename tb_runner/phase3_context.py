"""Evidence-gated Phase 3 context adapter.

This is a diagnostic projection over the current production entry contract and
the current observed screen. It never initiates navigation or drives traversal.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_sha256
from tb_runner.scenario_config import SCENARIO_CONFIG_VERSION, TAB_CONFIGS


_CONTRACT_FIELDS = (
    "scenario_id", "scenario_type", "entry_type", "tab_name", "tab_type",
    "pre_navigation", "entry_match", "context_verify",
)
_PLUGIN_IDS = {
    "life_food_plugin": ("life_plugin", "food", "life", r"(?:^|\.)WebPluginActivity$", None),
    "life_family_care_plugin": ("life_plugin", "family_care", "life",
                                r"(?:^|\.)plugin\.care\.MainActivity$",
                                r"com\.samsung\.android\.plugin\.care:id/"),
    "life_find_plugin": ("life_plugin", "find", "life",
                          r"(?:^|\.)plugin\.fme\.MainActivity$",
                          r"com\.samsung\.android\.plugin\.fme:id/"),
    "device_smoke_sensor_plugin": ("device_plugin", "smoke_sensor", "devices",
                                   r"(?:^|\.)WebPluginActivity$",
                                   r"SmokeDetectorCapabilityCardView(?:_[A-Za-z0-9_]+)?$"),
}
_ROOT_IDS = {"home_main": "home", "devices_main": "devices"}
_ROOT_MARKERS = {
    "home": (r"com\.samsung\.android\.oneconnect:id/(?:mapview_layout|dashboard_layout|dashboard_card)",),
    "devices": (r"com\.samsung\.android\.oneconnect:id/(?:card_recycler|device_card|view_pager)",),
}
_TAB_LABELS = {"favorites": "home", "home": "home", "devices": "devices",
               "life": "life", "services": "life", "routines": "routines", "menu": "menu"}
_TRUSTED_TAB_SOURCES = {"service_hierarchy_selected", "helper_selected", "observed_selected_node"}


def _scenario_config(scenario_id: str) -> dict[str, Any] | None:
    return next((dict(cfg) for cfg in TAB_CONFIGS if cfg.get("scenario_id") == scenario_id), None)


def _entry_contract_digest(config: Mapping[str, Any]) -> str:
    return canonical_sha256({"version": SCENARIO_CONFIG_VERSION,
                             "contract": {key: config.get(key) for key in _CONTRACT_FIELDS}})


def phase3_entry_evidence_from_main_loop(phase_ctx: Any, scenario_run_id: str,
                                        captured_at: str | None = None) -> dict[str, Any]:
    """Attest the already-entered production main-loop boundary for diagnostics.

    The caller must invoke this from the existing collection main-loop hook.
    The body and runtime component are independently re-checked by the adapter.
    """
    tab_cfg = getattr(phase_ctx, "tab_cfg", None)
    scenario_id = str(tab_cfg.get("scenario_id", "") or "") if isinstance(tab_cfg, Mapping) else ""
    config = _scenario_config(scenario_id)
    run_id = str(scenario_run_id or "").strip()
    if config is None or not run_id:
        return {}
    rows = getattr(phase_ctx, "rows", None)
    anchor = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], Mapping) else {}
    return {
        "schema_version": "phase3-entry-evidence-v1",
        "source": "collection_flow._main_loop_phase",
        "status": "TRAVERSAL_STARTED",
        "scenario_id": scenario_id,
        "scenario_run_id": run_id,
        "entry_contract_version": SCENARIO_CONFIG_VERSION,
        "entry_contract_digest": _entry_contract_digest(config),
        "captured_at": captured_at,
        "entry_anchor_source": anchor.get("actual_focus_payload_source"),
        "entry_anchor_accessibility_focused": anchor.get("actual_focus_accessibility_focused"),
    }


def phase3_entry_evidence_from_accepted_replay(scenario_id: str, scenario_tx_id: str,
                                               terminal_event: Mapping[str, Any],
                                               observed_at: str) -> dict[str, Any]:
    """Adapt an accepted terminal record for replay only when it proves this transaction started traversal."""
    config = _scenario_config(str(scenario_id or ""))
    payload = terminal_event.get("payload") if isinstance(terminal_event, Mapping) else None
    if (config is None or not isinstance(payload, Mapping)
            or terminal_event.get("scenario_id") != scenario_id
            or terminal_event.get("scenario_tx_id") != scenario_tx_id
            or payload.get("traversal_started") is not True):
        return {}
    return {
        "schema_version": "phase3-entry-evidence-v1",
        "source": "accepted_fullrun_scenario_terminal",
        "status": "TRAVERSAL_STARTED",
        "scenario_id": scenario_id,
        "scenario_run_id": scenario_tx_id,
        "entry_contract_version": SCENARIO_CONFIG_VERSION,
        "entry_contract_digest": _entry_contract_digest(config),
        "captured_at": observed_at,
        "terminal_event_id": terminal_event.get("event_id"),
    }


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed
    except ValueError:
        return None


def _labels_and_ids(raw: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    labels: list[str] = []
    resource_ids: list[str] = []
    pending = list(raw.get("nodes") or [])
    while pending:
        node = pending.pop()
        if not isinstance(node, Mapping):
            continue
        if node.get("visibleToUser", node.get("isVisibleToUser", True)) is not False:
            label = next((str(node.get(key) or "").strip() for key in
                          ("text", "contentDescription", "talkbackLabel", "mergedLabel", "label")
                          if str(node.get(key) or "").strip()), "")
            if label:
                labels.append(label)
            resource_id = next((str(node.get(key) or "").strip() for key in
                                ("viewIdResourceName", "resourceId", "resource_id", "view_id")
                                if str(node.get(key) or "").strip()), "")
            if resource_id:
                resource_ids.append(resource_id)
        children = node.get("children")
        if isinstance(children, list):
            pending.extend(children)
    return labels, resource_ids


def _selected_tab(raw: Mapping[str, Any]) -> tuple[str | None, str | None]:
    selected = raw.get("selected_tab")
    if not isinstance(selected, Mapping) or selected.get("verified") is not True:
        return None, None
    source = str(selected.get("source") or "").strip()
    if source not in _TRUSTED_TAB_SOURCES:
        return None, source or None
    name = str(selected.get("logical_name") or selected.get("name") or "").strip().casefold()
    return (_TAB_LABELS.get(name), source) if name in _TAB_LABELS else (None, source)


def _body_matches(config: Mapping[str, Any], labels: list[str]) -> bool:
    context = config.get("context_verify")
    pattern = str(context.get("text_regex") or "").strip() if isinstance(context, Mapping) else ""
    if not pattern:
        return False
    try:
        return any(re.search(pattern, label, re.IGNORECASE) is not None for label in labels)
    except re.error:
        return False


def _body_match_scenarios(labels: list[str]) -> list[str]:
    return [scenario_id for scenario_id in _PLUGIN_IDS
            if (config := _scenario_config(scenario_id)) is not None and _body_matches(config, labels)]


def _profile_match(scenario_id: str, raw: Mapping[str, Any], labels: list[str],
                   resource_ids: list[str]) -> bool:
    profile = _PLUGIN_IDS[scenario_id]
    config = _scenario_config(scenario_id)
    if config is None:
        return False
    package = str(raw.get("package_name") or "").strip()
    activity = str(raw.get("activity_name") or "").strip()
    source = str(raw.get("context_source") or "").strip()
    if package and package != "com.samsung.android.oneconnect":
        return False
    _kind, _context_id, expected_tab, activity_pattern, resource_pattern = profile
    activity_match = bool(activity and re.search(activity_pattern, activity, re.IGNORECASE))
    resource_match = bool(resource_pattern and any(re.search(resource_pattern, rid, re.IGNORECASE)
                                                   for rid in resource_ids))
    if activity and not activity_match:
        return False
    if not activity_match and not resource_match:
        return False
    if activity and source != "helper_tree_component":
        return False
    if not _body_matches(config, labels):
        return False
    if resource_pattern and activity_match and not resource_match:
        return False
    selected, _ = _selected_tab(raw)
    return selected is None or selected == expected_tab


def _entry_is_current(raw: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[bool, str]:
    evidence = raw.get("phase3_entry_evidence")
    if not isinstance(evidence, Mapping):
        return False, "MISSING_PRODUCTION_ENTRY_EVIDENCE"
    scenario_id = str(raw.get("scenario_id") or "")
    run_id = str(raw.get("scenario_run_id") or "")
    if (evidence.get("schema_version") != "phase3-entry-evidence-v1"
            or evidence.get("source") not in {"collection_flow._main_loop_phase", "accepted_fullrun_scenario_terminal"}
            or evidence.get("status") != "TRAVERSAL_STARTED"
            or evidence.get("scenario_id") != scenario_id
            or not run_id or evidence.get("scenario_run_id") != run_id):
        return False, "STALE_OR_MISMATCHED_ENTRY_EVIDENCE"
    if (evidence.get("entry_contract_version") != SCENARIO_CONFIG_VERSION
            or evidence.get("entry_contract_digest") != _entry_contract_digest(config)):
        return False, "ENTRY_CONTRACT_MISMATCH"
    if evidence.get("source") == "accepted_fullrun_scenario_terminal" and not evidence.get("terminal_event_id"):
        return False, "MISSING_ACCEPTED_RUN_TERMINAL_PROVENANCE"
    current = _timestamp(raw.get("timestamp"))
    entered = _timestamp(evidence.get("captured_at"))
    if current is None or entered is None or entered > current:
        return False, "STALE_OR_UNORDERED_ENTRY_EVIDENCE"
    return True, "PRODUCTION_ENTRY_BOUNDARY"


def resolve_phase3_context(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Keep context unknown until a producer can bind trusted component evidence."""
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
    authority = validate_capture_authority(raw.get("capture_authority"))
    if authority is None or raw.get("capture_id") != authority.capture_key:
        return dict(status="UNRESOLVED_CONTEXT", context_type=None, context_id=None,
                    context_source="capture_authority_missing", confidence="NONE", verified=False,
                    observed_signals=[], reasons=["CAPTURE_AUTHORITY_MISSING"])
    if raw.get("hierarchy_capture_id") != authority.capture_key:
        return dict(status="UNRESOLVED_CONTEXT", context_type=None, context_id=None,
                    context_source="capture_authority_mismatch", confidence="NONE", verified=False,
                    observed_signals=[], reasons=["CAPTURE_AUTHORITY_MISMATCH"])
    if (raw.get("package_name") != authority.hierarchy_package_name
            or raw.get("traversal_root_ref") != authority.root_ref
            or raw.get("traversal_root_window_id") != authority.hierarchy_window_id):
        return dict(status="UNRESOLVED_CONTEXT", context_type=None, context_id=None,
                    context_source="capture_root_mismatch", confidence="NONE", verified=False,
                    observed_signals=[], reasons=["CAPTURE_ROOT_PACKAGE_WINDOW_MISMATCH"])
    # The producer binds exact root/package/window bytes only. This does not
    # establish Activity identity or screen-transition continuity. Configured
    # destination conflicts remain actionable diagnostics, but never VERIFIED.
    scenario_id = str(raw.get("scenario_id") or "")
    config = _scenario_config(scenario_id)
    if config and config.get("screen_context_mode") == "new_screen":
        from tb_runner.plugin_context_contract import generic_plugin_context
        current, entry_reason = _entry_is_current(raw, config)
        selected, _selected_source = _selected_tab(raw)
        expected_tab = next((name for name in ("home", "devices", "life", "routines", "menu")
                             if name in str(config.get("tab_name", "")).casefold()), None)
        labels, resource_ids = _labels_and_ids(raw)
        result = generic_plugin_context(
            raw, config, entry_current=current, entry_reason=entry_reason,
            labels=labels, body_matches=_body_matches, selected=selected,
            expected_tab=expected_tab, timestamp=_timestamp,
            matched_profiles=[candidate for candidate in _PLUGIN_IDS
                              if _profile_match(candidate, raw, labels, resource_ids)],
        )
        if result.get("status") == "CONTRADICTORY_CONTEXT":
            return result
    context = dict(status="UNRESOLVED_CONTEXT", context_type=None, context_id=None,
                   context_source="capture_local_hierarchy_only", confidence="NONE", verified=False,
                   semantic_component_identity="UNKNOWN", root_authority="UNKNOWN",
                   observed_signals=["capture_root_package_window"],
                   destination_evidence=(result.get("destination_evidence") if config and
                                         config.get("screen_context_mode") == "new_screen" else None),
                   reasons=["CAPTURE_COMPONENT_UNKNOWN"])
    from tb_runner.plugin_entry_provenance import root_authority_is_current
    provenance = raw.get("phase6d3a_entity_root_provenance")
    if root_authority_is_current(provenance, raw):
        root_provenance = provenance if isinstance(provenance, Mapping) else {}
        context.update(
            root_authority=root_provenance.get("root_authority", "UNKNOWN"),
            root_authority_evidence=deepcopy(root_provenance.get("root_authority_evidence") or {}),
            scenario_run_id=raw.get("scenario_run_id"),
            proof_capture_id=authority.capture_key,
            observation_id=((raw.get("_exploration_observation") or {}).get("observation_id")
                            if isinstance(raw.get("_exploration_observation"), Mapping) else None),
        )
    return context
