"""Generic, observational plugin entry proof; no navigation or visit authority."""
from __future__ import annotations

from typing import Any, Mapping
import re
from contextlib import contextmanager

def body_resources(raw: Mapping[str, Any]) -> list[str]:
    """Observed body IDs, excluding SmartThings bottom navigation chrome."""
    return sorted({str(n.get("viewIdResourceName") or n.get("resourceId") or "")
                   for n in raw.get("nodes", []) if isinstance(n, Mapping)
                   and n.get("visibleToUser") is not False
                   and (n.get("viewIdResourceName") or n.get("resourceId"))
                   and not str(n.get("viewIdResourceName") or n.get("resourceId")).startswith(
                       "com.samsung.android.oneconnect:id/menu_")})


@contextmanager
def navigation_epoch_guard(client, invalidate, *, navigation_observer=None):
    """Observe existing navigation attempts; never issue or change an action.

    Focus targeting and scroll are not navigation. A click, tap, Back/Home or
    activity launch invalidates the proof even when its command later fails.
    Only another normal entry boundary may create a new proof.
    """
    saved = {}
    def install(name, navigates):
        original = getattr(client, name, None)
        if not callable(original): return
        saved[name] = (name in client.__dict__, client.__dict__.get(name))
        def observed(*args, **kwargs):
            event = navigates(args, kwargs)
            if event:
                invalidate()
                if navigation_observer is not None:
                    navigation_observer(event)
            return original(*args, **kwargs)
        setattr(client, name, observed)
    def command_navigation(args, kwargs):
        command = args[0] if args else kwargs.get("args", [])
        if not isinstance(command, (list, tuple)): return False
        words = [str(w).lower() for w in command]
        if words[:3] == ["shell", "am", "start"]: return dict(kind="ACTIVITY_START")
        if words[:3] == ["shell", "am", "force-stop"]: return dict(kind="FORCE_STOP")
        if words[:3] == ["shell", "input", "tap"]: return dict(kind="TAP")
        if words[:3] == ["shell", "input", "keyevent"]:
            if any(w in {"3", "keycode_home"} for w in words[3:]): return dict(kind="HOME")
            if any(w in {"4", "keycode_back"} for w in words[3:]): return dict(kind="BACK")
        return False
    install("_run", command_navigation)
    install("_broadcast", lambda args, kwargs: dict(kind="CLICK") if "CLICK" in str(args[1] if len(args)>1 else kwargs.get("action", "")).upper() else False)
    install("tap_xy_adb", lambda *_: dict(kind="TAP"))
    install("tap_bounds_center_adb", lambda *_: dict(kind="TAP"))
    try:
        yield
    finally:
        for name, (had_instance, prior) in saved.items():
            if had_instance: setattr(client, name, prior)
            else: client.__dict__.pop(name, None)


def plugin_context_evidence(entry: Mapping[str, Any], raw: Mapping[str, Any],
                            summary: Mapping[str, Any], navigation_epoch: str) -> dict[str, Any]:
    """Called at the normal production main-loop boundary, after start succeeds.

    The existing start summary proves post-open verification. Entry provenance,
    contract digest, actual anchor, current component and epoch remain separate
    requirements. A replay must reconstruct the summary from native entry logs.
    """
    if not navigation_epoch or not isinstance(summary, Mapping):
        return {}
    if (summary.get("open_completed") is not True
            or summary.get("entry_contract_reason") != "success_verified"
            or summary.get("entry_contract_detail") != "plugin_open_verified"
            or entry.get("entry_anchor_accessibility_focused") is not True
            or entry.get("entry_anchor_source") != "verified_pre_loop_anchor"):
        return {}
    return dict(schema_version="generic-plugin-context-v1", source="production_post_open_main_loop",
                scenario_id=entry.get("scenario_id"), scenario_run_id=entry.get("scenario_run_id"),
                entry_contract_digest=entry.get("entry_contract_digest"),
                destination_identity=entry.get("entry_contract_digest"),
                navigation_epoch=navigation_epoch, captured_at=raw.get("timestamp"),
                package_name=raw.get("package_name"), activity_name=raw.get("activity_name"),
                component_source=raw.get("context_source"), body_resource_ids=body_resources(raw),
                post_open_verified=True, post_open_summary=dict(summary),
                proof_capture_id=raw.get("capture_id"))


def generic_plugin_context(raw, config, *, entry_current, entry_reason, labels,
                           body_matches, selected, expected_tab, timestamp,
                           matched_profiles=()):
    """Resolve an owned proof against current observations; never infer by name."""
    proof = raw.get("phase3_plugin_context_evidence")
    def result(status, reason, signals=()):
        return dict(status=status, context_tier=("PARTIAL_PLUGIN_CONTEXT" if status == "PARTIAL_CONTEXT" else status),
                    context_type="plugin", context_id=(proof.get("destination_identity")
                        if status == "VERIFIED_PLUGIN_CONTEXT" and isinstance(proof, Mapping) else None),
                    context_source="generic_production_entry+post_open+current_runtime",
                    confidence="HIGH" if status == "VERIFIED_PLUGIN_CONTEXT" else "LOW",
                    verified=status == "VERIFIED_PLUGIN_CONTEXT", observed_signals=list(signals),
                    reasons=[reason] if reason else [])
    if not entry_current:
        return result("UNRESOLVED_CONTEXT", entry_reason)
    if not isinstance(proof, Mapping):
        return result("UNRESOLVED_CONTEXT", "MISSING_GENERIC_PLUGIN_CONTEXT_PROOF")
    entry = raw.get("phase3_entry_evidence", {})
    summary = proof.get("post_open_summary", {})
    current_time, proof_time = timestamp(raw.get("timestamp")), timestamp(proof.get("captured_at"))
    if (proof.get("schema_version") != "generic-plugin-context-v1"
            or proof.get("source") != "production_post_open_main_loop"
            or proof.get("scenario_id") != raw.get("scenario_id")
            or proof.get("scenario_run_id") != raw.get("scenario_run_id")
            or not raw.get("navigation_epoch")
            or proof.get("navigation_epoch") != raw.get("navigation_epoch")
            or proof.get("destination_identity") != entry.get("entry_contract_digest")
            or proof.get("entry_contract_digest") != entry.get("entry_contract_digest")
            or not proof.get("proof_capture_id")
            or not current_time or not proof_time or proof_time > current_time
            or proof.get("post_open_verified") is not True
            or summary.get("open_completed") is not True
            or summary.get("entry_contract_reason") != "success_verified"
            or summary.get("entry_contract_detail") != "plugin_open_verified"
            or entry.get("entry_anchor_accessibility_focused") is not True
            or entry.get("entry_anchor_source") != "verified_pre_loop_anchor"):
        return result("UNRESOLVED_CONTEXT", "STALE_OR_UNOWNED_GENERIC_PLUGIN_PROOF")
    if selected and selected != expected_tab:
        return result("CONTRADICTORY_CONTEXT", "SELECTED_TAB_MISMATCH")
    package, activity = raw.get("package_name"), raw.get("activity_name")
    if (package and package != proof.get("package_name")) or (activity and activity != proof.get("activity_name")):
        return result("CONTRADICTORY_CONTEXT", "PLUGIN_COMPONENT_CHANGED")
    if activity and str(activity).endswith("SCMainActivity"):
        return result("CONTRADICTORY_CONTEXT", "ROOT_SCREEN_IS_NOT_PLUGIN_BODY")
    # Contradictions use configured destination markers, not a plugin-name table.
    from tb_runner.scenario_config import TAB_CONFIGS
    target_body = body_matches(config, labels)
    def destination_marker(c):
        # Body contracts often include shared words such as "History". These
        # cannot independently prove a different destination. Require its
        # configured entry title/alias as well, or a strict observed profile.
        tokens = [str(token).strip() for step in c.get("pre_navigation", [])
                  for token in [step.get("target", ""), *step.get("target_stable_labels", [])]
                  if str(token).strip()]
        return any(re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", label, re.I)
                   for token in tokens for label in labels)
    others = [c["scenario_id"] for c in TAB_CONFIGS
              if c.get("screen_context_mode") == "new_screen"
              and c.get("scenario_id") != raw.get("scenario_id")
              and body_matches(c, labels) and destination_marker(c)]
    others += [s for s in matched_profiles if s != raw.get("scenario_id")]
    if len(matched_profiles) > 1:
        return result("CONTRADICTORY_CONTEXT", "MULTIPLE_PLUGIN_CONTEXT_MATCHES", matched_profiles)
    if others:
        return result("CONTRADICTORY_CONTEXT", "OTHER_CONFIGURED_DESTINATION_BODY", others)
    trusted = (package == "com.samsung.android.oneconnect" and package == proof.get("package_name")
               and bool(activity) and activity == proof.get("activity_name")
               and raw.get("context_source") in {"window_current_focus", "activity_resumed"}
               and proof.get("component_source") in {"window_current_focus", "activity_resumed"})
    shared = bool(set(body_resources(raw)) & set(proof.get("body_resource_ids") or []))
    signals = ["owned_production_entry", "production_post_open_verified", "navigation_epoch"]
    if trusted: signals.append("current_bound_component")
    if shared: signals.append("current_entry_body_resource")
    if target_body: signals.append("configured_destination_body")
    if trusted and shared and target_body:
        return result("VERIFIED_PLUGIN_CONTEXT", "", signals)
    # Incomplete noncontradictory evidence permits only independently gated
    # structural actions. The Phase 4 gate retains every focus/geometry check.
    if not trusted:
        return result("UNRESOLVED_CONTEXT", "CURRENT_PLUGIN_COMPONENT_UNPROVEN", signals)
    return result("PARTIAL_CONTEXT", "PLUGIN_BODY_EVIDENCE_INCOMPLETE", signals)
