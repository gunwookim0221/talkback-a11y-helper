from copy import deepcopy
from datetime import datetime, timedelta, timezone
import subprocess
from types import MethodType, SimpleNamespace
from unittest.mock import patch

from test_talkback_lib import CollectFocusStepClient
from talkback_lib import A11yAdbClient
from tb_runner import collection_flow, focus_realign_logic
from tb_runner.phase4b_execution import controlled_collect
from tb_runner.focus_reconciliation import reconcile_focus
from tb_runner.frontier_shadow import capture_reconciled_inventory
from tb_runner.frontier_shadow import FrontierShadowRuntime
from tb_runner.phase3_context import _entry_is_current, phase3_entry_evidence_from_main_loop
from tb_runner.plugin_context_contract import plugin_context_evidence
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.state_graph import _raw_observation_from_row, build_graph_state_identity
from tb_runner.traversal_reliability import instance_id
from tools import state_fingerprint_diagnostic


SCENARIO = "device_smoke_sensor_plugin"
RUN_ID = "rf5r-smoke-sensor-replay"
PACKAGE = "com.samsung.android.oneconnect"
ACTIVITY = "com.samsung.android.oneconnect.plugin.WebPluginActivity"
CAPTURE_ID = "rf5h-post-action-capture"
CAPTURED_AT = "2026-10-22T23:55:04Z"
MARKER = {
    "scope_id": "rf5r-live-scope",
    "observation_sequence": 8,
    "action_epoch": 3,
    "observation_epoch": 3,
    "capture_end_action_epoch": 3,
    "context_revision": 0,
    "observation_id": "observation:rf5r-live-scope:8",
    "capture_complete": True,
}


def _production_raw(*, capture_id=CAPTURE_ID, coverage="OBSERVED_FULL"):
    config = next(cfg for cfg in TAB_CONFIGS if cfg["scenario_id"] == SCENARIO)
    entry = phase3_entry_evidence_from_main_loop(
        SimpleNamespace(
            tab_cfg=config,
            rows=[{"actual_focus_payload_source": "verified_pre_loop_anchor",
                   "actual_focus_accessibility_focused": True}],
        ),
        RUN_ID,
        "2026-10-22T23:54:00Z",
    )
    raw = {
        "scenario_id": SCENARIO,
        "scenario_run_id": RUN_ID,
        "capture_id": capture_id,
        "timestamp": CAPTURED_AT,
        "package_name": PACKAGE,
        "activity_name": ACTIVITY,
        "context_source": "window_current_focus",
        "navigation_context": {"bottom_tab": "devices"},
        "selected_tab": {"name": "devices", "verified": True,
                          "source": "service_hierarchy_selected"},
        "display_bounds": [0, 0, 1080, 2400],
        "observation_coverage": coverage,
        "coverage_source": ("reliable_service_hierarchy" if coverage == "OBSERVED_FULL"
                            else "reliable_snapshot_incomplete"),
        "hierarchy_complete": coverage == "OBSERVED_FULL",
        "nodes": [
            {"viewIdResourceName": f"{PACKAGE}:id/SmokeDetectorCapabilityCardView",
             "text": "Smoke sensor", "className": "android.widget.TextView",
             "boundsInScreen": "[0,400][900,600]", "visibleToUser": True,
             "focusable": True, "enabled": True},
            {"viewIdResourceName": f"{PACKAGE}:id/menu_devices", "text": "Devices",
             "className": "android.widget.TextView", "boundsInScreen": "[0,2200][200,2400]",
             "visibleToUser": True, "selected": True},
        ],
        "focus_node": {
            "viewIdResourceName": f"{PACKAGE}:id/more", "text": "More options",
            "className": "android.widget.Button", "boundsInScreen": "[912,126][1032,270]",
            "visibleToUser": True, "accessibilityFocused": True, "focused": False,
        },
        "snapshot_coherent": True,
        "focus_capture_status": "STRICT_ACCESSIBILITY_FOCUS",
        "hierarchy_capture_id": capture_id,
        "focus_capture_id": capture_id,
        "geometry_capture_id": capture_id,
        "phase3_entry_evidence": entry,
        "navigation_epoch": "rf5r-navigation-epoch-1",
    }
    raw["phase3_plugin_context_evidence"] = plugin_context_evidence(
        entry,
        raw,
        {"open_completed": True, "entry_contract_reason": "success_verified",
         "entry_contract_detail": "plugin_open_verified"},
        raw["navigation_epoch"],
    )
    raw["_exploration_observation"] = deepcopy(MARKER)
    raw["production_observation_current"] = True
    raw["production_observation_envelope"] = {
        "schema_version": "phase6-production-observation-v1",
        "scenario_id": SCENARIO,
        "scenario_run_id": RUN_ID,
        "capture_id": capture_id,
        "hierarchy_capture_id": capture_id,
        "focus_capture_id": capture_id,
        "geometry_capture_id": capture_id,
        "observation": deepcopy(MARKER),
        "capture_complete": True,
        "snapshot_coherent": True,
        "navigation_epoch": "rf5r-navigation-epoch-1",
        "coverage": coverage,
        "coverage_source": raw["coverage_source"],
        "hierarchy_complete": raw["hierarchy_complete"],
        "hierarchy_request_id": "rf5h-reliable-request-3",
    }
    return raw


def _controlled_row(*, actual=None, operation_id="operation-current", request_id="request-current"):
    target = {
        "resource_id": "com.samsung.android.oneconnect:id/more",
        "bounds": "[912,126][1032,270]",
        "label": "More options",
        "class_name": "android.widget.Button",
    }
    actual = actual or {
        "viewIdResourceName": target["resource_id"], "boundsInScreen": target["bounds"],
        "text": target["label"], "className": target["class_name"],
        "accessibilityFocused": True, "focused": False,
    }
    intent = {
        "schema_version": "phase4-controlled-focus-intent-v1",
        "scenario_id": SCENARIO,
        "step_index": 3,
        "operation_id": operation_id,
        "request_id": request_id,
        "target_attempt_id": "target-attempt-current",
        "dispatch_status": "DISPATCHED",
        "target_descriptor": deepcopy(target),
        "scope_id": MARKER["scope_id"],
        "action_epoch": MARKER["action_epoch"],
        "observation_id": MARKER["observation_id"],
        "observation_sequence": MARKER["observation_sequence"],
    }
    return {
        "scenario_id": SCENARIO,
        "step_index": 3,
        "row_source": "representative",
        "focus_view_id": target["resource_id"],
        "focus_bounds": target["bounds"],
        "visible_label": target["label"],
        "focus_class_name": target["class_name"],
        "target_focus_descriptor": deepcopy(target),
        "target_focus_attempt_id": "target-attempt-current",
        "controlled_focus_operation_id": operation_id,
        "controlled_focus_request_id": request_id,
        "controlled_focus_dispatch_status": "DISPATCHED",
        "controlled_focus_intent": intent,
        "_exploration_observation": deepcopy(MARKER),
        "move_result": {"raw": {"reqId": request_id, "success": True}},
        "actual_focus_resource_id": actual.get("viewIdResourceName", ""),
        "actual_focus_bounds": actual.get("boundsInScreen", ""),
        "actual_focus_visible": actual.get("talkbackLabel") or actual.get("text") or "",
        "actual_focus_speech": actual.get("talkbackLabel") or actual.get("text") or "",
        "actual_focus_class_name": actual.get("className", ""),
        "actual_focus_accessibility_focused": actual.get("accessibilityFocused") is True,
        "actual_focus_input_focused": actual.get("focused") is True,
        "actual_focus_node": deepcopy(actual),
        "focus_node": deepcopy(actual),
    }


def _reconcile(row, *, previous=None, expected=()):
    return reconcile_focus(
        row=row,
        previous_row=previous,
        scenario_id=SCENARIO,
        inventory=list(expected),
        expected_candidates=list(expected),
        physical_visit_confirmed=True,
        planning_consumed=True,
        visited_instance_ids_before=(),
    )


def _previous_focus():
    node = {"viewIdResourceName": "previous", "boundsInScreen": "[10,10][110,110]",
            "text": "Previous", "className": "android.widget.Button",
            "accessibilityFocused": True, "focused": False}
    return {
        "scenario_id": SCENARIO,
        "actual_focus_node": node,
        "focus_node": node,
        "actual_focus_resource_id": "previous",
        "actual_focus_bounds": "[10,10][110,110]",
        "actual_focus_visible": "Previous",
        "actual_focus_accessibility_focused": True,
        "actual_focus_input_focused": False,
    }


def test_controlled_target_intent_reconciles_actual_target_and_ignores_generic_population():
    row = _controlled_row()
    generic = {"scenario_id": SCENARIO, "rid": "different", "view_id": "different",
               "label": "Generic representative", "bounds": "[10,10][110,110]",
               "class_name": "android.widget.Button"}
    result = _reconcile(row, previous=_previous_focus(), expected=[generic])
    assert result["expected_target_source"] == "CONTROLLED_TARGET_INTENT"
    assert result["controlled_focus_intent_status"] == "CURRENT_CONTROLLED_TARGET"
    assert result["classification"] == "ALIGNED"
    assert result["candidate_in_expected_population"] is True
    assert result["focus_transition_status"] == "CONFIRMED_MOVED"
    assert result["visit_record_status"] == "RECORDED"


def test_controlled_intent_does_not_hide_actual_focus_mismatch():
    other = {"viewIdResourceName": "other", "boundsInScreen": "[100,300][200,400]",
             "text": "Other", "className": "android.widget.Button",
             "accessibilityFocused": True, "focused": False}
    result = _reconcile(_controlled_row(actual=other), previous=_previous_focus())
    assert result["expected_target_source"] == "CONTROLLED_TARGET_INTENT"
    assert result["classification"] == "UNEXPECTED_ACTUAL_FOCUS"
    assert result["candidate_in_expected_population"] is False


def test_stale_controlled_operation_falls_back_to_generic_reconciliation():
    row = _controlled_row(operation_id="old-operation")
    row["controlled_focus_operation_id"] = "current-operation"
    result = _reconcile(row, previous=_previous_focus(), expected=[{
        "scenario_id": SCENARIO, "rid": row["actual_focus_resource_id"],
        "view_id": row["actual_focus_resource_id"], "bounds": row["actual_focus_bounds"],
        "label": row["actual_focus_visible"], "class_name": row["actual_focus_class_name"],
    }])
    assert result["controlled_focus_intent_status"] == "ACTION_OWNERSHIP_MISMATCH"
    assert result["expected_target_source"] == "GENERIC_RECONCILIATION"
    assert result["classification"] == "ALIGNED"


def test_controlled_intent_alone_never_grants_focus_or_visit():
    row = _controlled_row()
    row["actual_focus_accessibility_focused"] = False
    row["actual_focus_node"]["accessibilityFocused"] = False
    row["focus_node"] = deepcopy(row["actual_focus_node"])
    result = _reconcile(row, previous=_previous_focus())
    assert result["classification"] == "NO_STRICT_ACTUAL_FOCUS"
    assert result["physical_visit_confirmed"] is False
    assert result["reconciled_visit_instance_id"] == ""


def test_confirmed_controlled_focus_skips_only_the_redundant_representative_realign():
    row = _controlled_row()
    calls = []
    client = SimpleNamespace(target_focus_commit=lambda **kwargs: calls.append(kwargs))
    result = focus_realign_logic._maybe_realign_focus_to_representative_impl(
        client=client, dev="serial", row=row,
        selected_node={"boundsInScreen": "[10,10][110,110]", "className": "android.widget.Button"},
        selected_rid="previous", selected_label="Previous", selected_bounds="[10,10][110,110]",
        scenario_id=SCENARIO, step_idx=3, mismatch_logged=False, force_reason="",
        scenario_perf=None, focus_matches_fn=lambda **kwargs: False,
        extract_label_fn=lambda _node: "", label_blob_fn=lambda _node: "",
        truncate_fn=lambda value, _limit: str(value), log_fn=lambda _message: None,
    )
    assert result == (False, "controlled_target_already_confirmed", None)
    assert calls == []


class _Clock:
    def begin_observation(self):
        return object()

    def finish_observation(self, _token):
        return deepcopy(MARKER)

    def current(self, marker):
        return marker == MARKER


def test_production_capture_handoff_preserves_one_current_entry_hierarchy_and_geometry(monkeypatch):
    raw = _production_raw()
    # The capture boundary supplies current data; entry/context proof is owned
    # by the already verified production run and bound to that same run.
    raw.pop("phase3_entry_evidence")
    raw.pop("phase3_plugin_context_evidence")
    row = {
        "scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": 3,
        "actual_focus_node": {"viewIdResourceName": "production-owner", "accessibilityFocused": True},
        "actual_focus_accessibility_focused": True,
        "phase3_entry_evidence": _production_raw()["phase3_entry_evidence"],
        "phase3_plugin_context_evidence": _production_raw()["phase3_plugin_context_evidence"],
        "navigation_epoch": "rf5r-navigation-epoch-1",
    }
    client = SimpleNamespace(_phase6c2_frontier_shadow_runtime=object(),
                             _phase6d3a_redirect_context={"scenario_run_id": RUN_ID})
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())
    monkeypatch.setattr("tools.state_fingerprint_diagnostic.capture_observation",
                        lambda *_args, **_kwargs: deepcopy(raw))

    captured = collection_flow._capture_phase6d3a_production_observation(
        client=client, dev="serial", row=row)
    identity = build_graph_state_identity(_raw_observation_from_row(row))
    assert captured["production_observation_current"] is True
    assert row["production_observation_envelope"]["capture_id"] == CAPTURE_ID
    assert row["production_observation_envelope"]["hierarchy_capture_id"] == CAPTURE_ID
    assert row["production_observation_envelope"]["focus_capture_id"] == CAPTURE_ID
    assert row["production_observation_envelope"]["geometry_capture_id"] == CAPTURE_ID
    assert row["state_graph_observation"]["phase3_entry_evidence"]["scenario_run_id"] == RUN_ID
    assert row["state_graph_observation"]["phase3_plugin_context_evidence"]["navigation_epoch"] == row["navigation_epoch"]
    assert row["dump_tree_nodes"] == raw["nodes"]
    assert row["display_bounds"] == raw["display_bounds"]
    assert row["observation_coverage"] == "OBSERVED_FULL"
    assert row["actual_focus_node"]["viewIdResourceName"] == "production-owner"
    assert row["actual_focus_accessibility_focused"] is True
    assert identity.status == "RESOLVED" and identity.state_id


def test_diagnostic_capture_uses_one_reliable_snapshot_for_focus_and_hierarchy():
    tree = {
        "success": True,
        "windows": [{"active": True, "focused": True, "root": {
            "packageName": PACKAGE, "viewIdResourceName": "root", "className": "android.widget.FrameLayout",
            "boundsInScreen": "[0,0][1080,2400]", "visibleToUser": True, "children": [
                {"packageName": PACKAGE,
                 "viewIdResourceName": f"{PACKAGE}:id/SmokeDetectorCapabilityCardView",
                 "text": "Smoke sensor", "className": "android.widget.TextView",
                 "boundsInScreen": "[0,400][900,600]", "visibleToUser": True,
                 "accessibilityFocused": True, "focusable": True},
                {"packageName": PACKAGE, "viewIdResourceName": f"{PACKAGE}:id/menu_devices",
                 "text": "Devices", "className": "android.widget.TextView",
                 "boundsInScreen": "[0,2200][200,2400]", "visibleToUser": True,
                 "selected": True},
            ],
        }}],
    }

    class Client:
        last_dump_metadata = {}
        last_scroll_capabilities = []

        def __init__(self):
            self.snapshot_calls = 0
            self.legacy_calls = []

        def get_traversal_candidate_snapshot(self, *, dev):
            assert dev == "serial"
            self.snapshot_calls += 1
            return SimpleNamespace(
                raw_hierarchy=deepcopy(tree),
                candidates=deepcopy(tree["windows"][0]["root"]["children"]),
                decoded=SimpleNamespace(
                    raw_completion_valid=True,
                    traversal_candidates=SimpleNamespace(complete=True),
                    request_id="current-request",
                ),
            )

        def get_focus(self, **_kwargs):
            self.legacy_calls.append("focus")
            raise AssertionError("reliable snapshot must supply focus")

        def dump_hierarchy(self, **_kwargs):
            self.legacy_calls.append("hierarchy")
            raise AssertionError("reliable snapshot must supply hierarchy")

        def _run(self, command, **_kwargs):
            if command == ["shell", "wm", "size"]:
                return "Physical size: 1080x2400"
            if command == ["shell", "dumpsys", "window"]:
                return f"mCurrentFocus=Window{{a u0 {PACKAGE}/.plugin.WebPluginActivity}}"
            return ""

    client = Client()
    captured = state_fingerprint_diagnostic.capture_observation(
        client, "serial", scenario_id=SCENARIO, step=3, scenario_run_id=RUN_ID)
    assert client.snapshot_calls == 1
    assert client.legacy_calls == []
    assert captured["snapshot_coherent"] is True
    assert captured["observation_coverage"] == "OBSERVED_FULL"
    assert captured["focus_node"]["accessibilityFocused"] is True
    assert captured["nodes"]
    assert captured["hierarchy_capture_id"] == captured["focus_capture_id"] == captured["geometry_capture_id"]


def test_failed_reliable_snapshot_is_not_rescued_by_legacy_focus_or_hierarchy():
    class Client:
        last_dump_metadata = {}
        last_scroll_capabilities = []

        def __init__(self):
            self.calls = []

        def get_traversal_candidate_snapshot(self, **_kwargs):
            self.calls.append("reliable")
            raise RuntimeError("incomplete response")

        def get_focus(self, **_kwargs):
            self.calls.append("focus")
            raise AssertionError("no legacy rescue")

        def dump_hierarchy(self, **_kwargs):
            self.calls.append("hierarchy")
            raise AssertionError("no legacy rescue")

        def _run(self, command, **_kwargs):
            if command == ["shell", "wm", "size"]:
                return "Physical size: 1080x2400"
            if command == ["shell", "dumpsys", "window"]:
                return "mCurrentFocus=null"
            return ""

    client = Client()
    captured = state_fingerprint_diagnostic.capture_observation(
        client, "serial", scenario_id=SCENARIO, step=3, scenario_run_id=RUN_ID)
    assert client.calls == ["reliable"]
    assert captured["source"] == "reliable_snapshot_failed"
    assert captured["snapshot_coherent"] is False
    assert captured["observation_coverage"] == "UNOBSERVED"
    assert captured["nodes"] == [] and captured["focus_node"] == {}
    assert captured["hierarchy_capture_id"] != captured["focus_capture_id"]


def test_incoherent_capture_cannot_replace_production_focus_or_claim_phase6_currentness(monkeypatch):
    raw = _production_raw()
    raw.update(snapshot_coherent=False, focus_capture_id="other-focus-capture")
    row = {
        "scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": 3,
        "actual_focus_node": {"viewIdResourceName": "production-focus", "accessibilityFocused": True},
        "actual_focus_accessibility_focused": True,
        "phase3_entry_evidence": _production_raw()["phase3_entry_evidence"],
        "phase3_plugin_context_evidence": _production_raw()["phase3_plugin_context_evidence"],
        "navigation_epoch": "rf5r-navigation-epoch-1",
    }
    client = SimpleNamespace(_phase6c2_frontier_shadow_runtime=object(),
                             _phase6d3a_redirect_context={"scenario_run_id": RUN_ID})
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())
    monkeypatch.setattr("tools.state_fingerprint_diagnostic.capture_observation",
                        lambda *_args, **_kwargs: deepcopy(raw))

    result = collection_flow._capture_phase6d3a_production_observation(
        client=client, dev="serial", row=row)
    assert result is None
    assert row["production_observation_capture_status"] == "UNALIGNED"
    assert row["state_graph_observation"]["production_observation_current"] is False
    assert row["actual_focus_node"]["viewIdResourceName"] == "production-focus"
    assert row["actual_focus_accessibility_focused"] is True


def test_envelope_fails_closed_for_missing_stale_or_cross_capture_evidence():
    base = _production_raw()

    missing_entry = deepcopy(base)
    missing_entry.pop("phase3_entry_evidence")
    missing_entry.pop("phase3_plugin_context_evidence")
    missing_result = build_graph_state_identity(missing_entry)
    assert missing_result.status == "UNRESOLVED"
    assert "MISSING_PRODUCTION_ENTRY_EVIDENCE" in missing_result.reasons

    stale_entry = deepcopy(base)
    stale_entry["phase3_entry_evidence"]["scenario_run_id"] = "prior-run"
    assert build_graph_state_identity(stale_entry).status == "UNRESOLVED"

    stale_navigation = deepcopy(base)
    stale_navigation["navigation_epoch"] = "prior-navigation-epoch"
    assert build_graph_state_identity(stale_navigation).status == "UNRESOLVED"

    cross_capture = deepcopy(base)
    cross_capture["production_observation_envelope"]["focus_capture_id"] = "older-focus-capture"
    assert build_graph_state_identity(cross_capture).status == "UNRESOLVED"


class _InventorySink:
    enabled = True

    def __init__(self):
        self.latest = None

    def capture_inventory(self, **kwargs):
        self.latest = kwargs


def test_partial_coverage_never_marks_frontier_inventory_complete():
    raw = _production_raw(coverage="OBSERVED_PARTIAL")
    row = {
        "scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": 3,
        "capture_id": CAPTURE_ID, "_exploration_observation": deepcopy(MARKER),
        "state_graph_observation": deepcopy(raw), "dump_tree_nodes": deepcopy(raw["nodes"]),
        "production_observation_envelope": deepcopy(raw["production_observation_envelope"]),
    }
    sink = _InventorySink()
    capture_reconciled_inventory(
        sink, row=row, candidates=[], scenario_id=SCENARIO,
        raw_nodes=raw["nodes"], projection_complete=True,
    )
    assert sink.latest["state_id"]
    assert sink.latest["inventory_complete"] is False


def test_frontier_rejects_inventory_nodes_from_a_different_capture():
    raw = _production_raw()
    row = {
        "scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": 3,
        "capture_id": CAPTURE_ID, "_exploration_observation": deepcopy(MARKER),
        "state_graph_observation": deepcopy(raw), "dump_tree_nodes": [],
        "production_observation_envelope": deepcopy(raw["production_observation_envelope"]),
    }
    sink = _InventorySink()
    capture_reconciled_inventory(
        sink, row=row, candidates=[], scenario_id=SCENARIO,
        raw_nodes=[], projection_complete=True,
    )
    assert sink.latest["state_id"] is None
    assert sink.latest["inventory_complete"] is False


def test_smoke_sensor_target_identity_uses_production_focus_instance_fields():
    row = _controlled_row()
    result = _reconcile(row, previous=_previous_focus())
    assert result["selection_candidate_instance_id"] == instance_id({
        "scenario_id": SCENARIO,
        "view_id": "com.samsung.android.oneconnect:id/more",
        "bounds": "[912,126][1032,270]",
    })


def test_normal_anchor_producer_records_entry_time_used_by_redirect_context(monkeypatch):
    config = next(cfg for cfg in TAB_CONFIGS if cfg["scenario_id"] == SCENARIO)
    client = SimpleNamespace(collect_focus_step=lambda **_kwargs: {
        "focus_view_id": "anchor", "actual_focus_payload_source": "verified_pre_loop_anchor",
        "actual_focus_accessibility_focused": True,
    })
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop",
                        lambda _client, _dev, row, _base: row)
    anchor = collection_flow._collect_start_anchor_row(
        client, "serial", config, scenario_id=SCENARIO, output_base_dir=".",
        main_step_wait_seconds=0, main_announcement_wait_seconds=0,
        main_announcement_idle_wait_seconds=0, main_announcement_max_extra_wait_seconds=0,
    )
    phase_ctx = SimpleNamespace(tab_cfg=config, rows=[anchor])
    owner = collection_flow._phase6d3a_initialize_redirect_context(
        client=client, dev="serial", phase_ctx=phase_ctx, run_id=RUN_ID)

    assert anchor["timestamp"]
    assert owner["phase3_entry_evidence"]["captured_at"] == anchor["timestamp"]
    current_raw = {
        "scenario_id": SCENARIO, "scenario_run_id": RUN_ID,
        "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
    }
    current, reason = _entry_is_current(current_raw | {
        "phase3_entry_evidence": owner["phase3_entry_evidence"],
    }, config)
    assert current is True
    assert reason == "PRODUCTION_ENTRY_BOUNDARY"


class _DecisionSink:
    def __init__(self):
        self.kwargs = None

    def prepare_decision(self, **kwargs):
        self.kwargs = kwargs
        return "phase6-decision-token"

    def _fail(self, *_args, **_kwargs):
        raise AssertionError("production-shaped decision preparation must not fail")


def _rf5r5_real_producer_client():
    client = CollectFocusStepClient()
    # Exercise the production SMART_NEXT implementation through the real
    # StepCollectionService row producer while keeping all device I/O offline.
    client.move_focus_smart = MethodType(A11yAdbClient.move_focus_smart, client)
    client._safe_trace_print = lambda *_args, **_kwargs: None
    return client


def _rf5r5_collect_step(client):
    return client.collect_focus_step(
        dev="offline", step_index=3, move=True, direction="next",
        wait_seconds=0, announcement_wait_seconds=0,
        announcement_idle_wait_seconds=0, announcement_max_extra_wait_seconds=0,
        focus_wait_seconds=0, allow_get_focus_fallback_dump=False,
        allow_step_dump=False,
    )


def test_smart_next_pre_request_helper_unavailable_does_not_reuse_cached_request():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client.last_smart_nav_terminal = True
    client._has_recent_helper_ok = lambda **_kwargs: False
    client.check_helper_status = lambda **_kwargs: False

    row = _rf5r5_collect_step(client)

    assert row["phase6_current_action_type"] == "SMART_NEXT"
    assert row["smart_nav_req_id"] == ""
    assert row["smart_nav_success"] is False
    assert row["last_smart_nav_terminal"] is False
    assert client.last_smart_nav_result["reqId"] == "request-old"


def test_smart_next_pre_request_failure_without_prior_cache_has_no_request():
    client = _rf5r5_real_producer_client()
    client._has_recent_helper_ok = lambda **_kwargs: False
    client.check_helper_status = lambda **_kwargs: False

    row = _rf5r5_collect_step(client)

    assert row["phase6_current_action_type"] == "SMART_NEXT"
    assert row["smart_nav_req_id"] == ""
    assert client.last_smart_nav_result == {}


def test_smart_next_current_success_selects_new_request_from_real_producer():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: True
    client._helper_bridge._request_smart_next = lambda *, dev, req_id: {
        "reqId": req_id, "success": True, "status": "moved",
    }

    row = _rf5r5_collect_step(client)

    assert row["smart_nav_req_id"]
    assert row["smart_nav_req_id"] != "request-old"
    assert row["smart_nav_req_id"] == client.last_smart_nav_result["reqId"]


def test_smart_next_post_request_failure_preserves_current_receipt():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: True
    client._helper_bridge._request_smart_next = lambda *, dev, req_id: {
        "reqId": req_id, "success": False, "status": "transport_error",
    }

    row = _rf5r5_collect_step(client)

    assert row["smart_nav_req_id"]
    assert row["smart_nav_req_id"] != "request-old"
    assert row["smart_nav_req_id"] == client.last_smart_nav_result["reqId"]
    assert row["smart_nav_success"] is False


def test_smart_next_exception_before_request_leaves_current_receipt_missing():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("pre-request"))

    row = _rf5r5_collect_step(client)

    assert row["smart_nav_req_id"] == ""
    assert row["smart_nav_success"] is False
    assert client.last_smart_nav_result["reqId"] == "request-old"


def test_smart_next_request_construction_exception_does_not_reuse_old_receipt():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: True
    client._helper_bridge._request_smart_next = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("request-construction-failed")
    )

    row = _rf5r5_collect_step(client)

    assert row["smart_nav_req_id"] == ""
    assert row["smart_nav_success"] is False
    assert client.last_smart_nav_result["reqId"] == "request-old"


def test_smart_next_adb_pre_dispatch_failure_does_not_claim_generated_id():
    from talkback_lib.adb_device import AdbCommandFailure

    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: True
    client._broadcast = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AdbCommandFailure("adb_command_failed", ["adb", "shell", "am", "broadcast"], 30.0)
    )

    row = _rf5r5_collect_step(client)

    assert row["smart_nav_req_id"] == ""
    assert client._last_smart_nav_invocation_result == {}
    assert client.last_smart_nav_result["reqId"] == "request-old"


def test_smart_next_failure_after_current_result_capture_keeps_current_receipt():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: True
    client._helper_bridge._request_smart_next = lambda *, dev, req_id: {
        "reqId": req_id, "success": False, "status": "transport_error",
    }
    client._helper_bridge.normalize_smart_next_status = lambda _result: (_ for _ in ()).throw(
        RuntimeError("post-request-normalization-failed")
    )

    row = _rf5r5_collect_step(client)

    assert row["smart_nav_req_id"]
    assert row["smart_nav_req_id"] != "request-old"
    assert row["smart_nav_req_id"] == client.last_smart_nav_result["reqId"]
    assert row["smart_nav_success"] is False


def test_smart_next_result_read_exception_keeps_dispatched_current_receipt():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: True
    client._broadcast = lambda *_args, **_kwargs: "Broadcast completed: result=0"
    client._read_log_result = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("result-read-failed-after-dispatch")
    )

    row = _rf5r5_collect_step(client)

    assert row["smart_nav_req_id"]
    assert row["smart_nav_req_id"] != "request-old"
    assert row["smart_nav_req_id"] == client._last_smart_nav_invocation_result["reqId"]
    assert row["smart_nav_success"] is False


def test_smart_previous_never_uses_prior_smart_next_receipt():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old-next", "success": True, "status": "moved",
    }
    row = client.collect_focus_step(
        dev="offline", step_index=3, move=True, direction="prev",
        wait_seconds=0, announcement_wait_seconds=0,
        announcement_idle_wait_seconds=0, announcement_max_extra_wait_seconds=0,
        focus_wait_seconds=0, allow_get_focus_fallback_dump=False,
        allow_step_dump=False,
    )
    assert row["phase6_current_action_type"] == "SMART_PREVIOUS"
    assert row["smart_nav_req_id"] == ""


def test_stale_smart_next_request_fails_closed_at_inventory_decision_and_audit(monkeypatch):
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: False
    client.check_helper_status = lambda **_kwargs: False
    row = _rf5r5_collect_step(client)
    _assert_missing_smart_next_handoff(row, monkeypatch)


def _assert_missing_smart_next_handoff(row, monkeypatch):
    raw = _production_raw()
    row.update(
        scenario_id=SCENARIO, scenario_run_id=RUN_ID,
        capture_id=CAPTURE_ID, timestamp=raw["timestamp"],
        state_graph_observation=deepcopy(raw),
        production_observation_envelope=deepcopy(raw["production_observation_envelope"]),
        _exploration_observation=deepcopy(MARKER),
        dump_tree_nodes=deepcopy(raw["nodes"]),
        actual_focus_node=deepcopy(raw["focus_node"]),
        actual_focus_accessibility_focused=True,
        actual_focus_instance_id=instance_id({
            "scenario_id": SCENARIO,
            "view_id": raw["focus_node"]["viewIdResourceName"],
            "bounds": raw["focus_node"]["boundsInScreen"],
        }),
        actual_focus_resource_id=raw["focus_node"]["viewIdResourceName"],
        actual_focus_bounds=raw["focus_node"]["boundsInScreen"],
        actual_focus_class_name=raw["focus_node"]["className"],
        focus_transition_status="CONFIRMED_UNCHANGED",
        visit_record_status="UNVISITED",
    )
    runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        runtime, row=row, candidates=[], scenario_id=SCENARIO,
        raw_nodes=raw["nodes"], projection_complete=True,
    )
    assert runtime._latest_inventory["observation_ref"]["request_id"] == ""

    decision_sink = _DecisionSink()
    decision_client = SimpleNamespace(
        _phase6c2_frontier_shadow_runtime=runtime,
        _phase6d_exploration_shadow_runtime=decision_sink,
    )
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())
    token = collection_flow._prepare_phase6d_exploration_decision(
        client=decision_client, row=row, step_idx=3,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content", "max_steps": 32},
        stop_candidate=False, stop_reason="", stop_eval_inputs={}, pre_decision_ref=None,
    )
    assert token == "phase6-decision-token"
    evaluation = decision_sink.kwargs["frontier_evaluation"]
    assert evaluation["alignment_status"] == "INCOMPLETE"
    assert evaluation["source_request_id"] is None

    pending = runtime.pre_decision(
        step=4, production_choice={"action_type": "FOCUS_NEXT"},
        state_id=runtime._latest_inventory["state_id"],
        inventory_complete=runtime._latest_inventory["inventory_complete"],
    )
    assert pending
    row["step_index"] = 4
    collection_flow._frontier_shadow_post_result(
        client=decision_client, decision_id=pending, step_idx=4,
        previous_row=None, row=row,
    )
    audit = runtime.evaluations[-1]["action_result"]
    assert audit["request_id"] is None
    assert audit["ownership_status"] == "UNKNOWN"
    assert runtime.history["attempt_events"] == []
    assert runtime.history["complete"] is False


def _rf5r6_controlled_fallback(client, audit, collect=None):
    return controlled_collect(
        client=client,
        dev="offline",
        scenario=SCENARIO,
        step=3,
        raw={},
        recommendation=None,
        decision=SimpleNamespace(allowed=False, mode="SHADOW_ONLY", reason="SHADOW_ONLY"),
        budget=SimpleNamespace(fallback_count=0),
        collect=collect or client.collect_focus_step,
        collect_kwargs={
            "dev": "offline", "step_index": 3, "move": True, "direction": "next",
            "wait_seconds": 0, "announcement_wait_seconds": 0,
            "announcement_idle_wait_seconds": 0,
            "announcement_max_extra_wait_seconds": 0, "focus_wait_seconds": 0,
            "allow_get_focus_fallback_dump": False, "allow_step_dump": False,
        },
        refresh=lambda: {},
        output_dir="",
        audit=audit,
    )


def _rf5r6_reconciliation_payload(client, row):
    row["scenario_id"] = SCENARIO
    return collection_flow._focus_reconciliation_event_payload(
        client=client,
        row=row,
        result={
            "focus_transition_status": "UNAVAILABLE",
            "classification": "NO_STRICT_ACTUAL_FOCUS",
            "reconciled_visit_instance_id": "",
            "visit_record_status": "UNAVAILABLE",
        },
    )


def test_smart_next_native_adb_timeout_preserves_current_request_from_typed_receipt():
    from talkback_lib.native_dispatch_evidence import native_dispatch_evidence as evaluate_native

    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: True
    client._broadcast = MethodType(A11yAdbClient._broadcast, client)
    native_calls = []
    evidence_results = []

    def timeout_after_native_entry(command, **kwargs):
        native_calls.append(list(command))
        raise subprocess.TimeoutExpired(
            command, kwargs.get("timeout", 0), output="Broadcasting: Intent",
        )

    def evaluate_and_record(*args, **kwargs):
        evidence = evaluate_native(*args, **kwargs)
        evidence_results.append(evidence)
        return evidence

    with patch("talkback_lib.adb_device.subprocess.run", side_effect=timeout_after_native_entry), \
            patch("talkback_lib.native_dispatch_evidence.native_dispatch_evidence",
                  side_effect=evaluate_and_record), patch("builtins.print"):
        row = _rf5r5_collect_step(client)

    assert len(native_calls) == 1
    request_id = row["smart_nav_req_id"]
    assert request_id
    assert row["move_result"]["success"] is False
    assert row["smart_nav_success"] is False
    assert client.last_smart_nav_result["reqId"] == "request-old"
    assert client._last_smart_nav_invocation_result["reqId"] == request_id
    assert len(evidence_results) == 1
    evidence = evidence_results[0]
    assert evidence.dispatch_status == "DISPATCHED"
    assert evidence.request_id == request_id
    receipts = client._adb_device.native_dispatch_receipts.receipts_after(
        0, request_id=request_id, operation_id=evidence.operation_id,
    )
    assert len(receipts) == 1
    assert receipts[0]["action_type"] == "SMART_NEXT"
    assert receipts[0]["dispatch_status"] == "NATIVE_DISPATCH_ATTEMPTED"


def test_fallback_pre_request_failure_does_not_borrow_previous_request_in_audit_or_lineage():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: False
    client.check_helper_status = lambda **_kwargs: False
    audit = {}

    row = _rf5r6_controlled_fallback(client, audit)

    assert row["smart_nav_req_id"] == ""
    assert client.last_smart_nav_result["reqId"] == "request-old"
    assert client._last_smart_nav_invocation_result == {}
    assert audit["fallback_helper_request_id"] == ""
    assert audit["fallback_helper_ack_result"] == {}
    assert audit["helper_request_id"] == ""
    assert audit["helper_ack_result"] == {}
    lineage = client._focus_reconciliation_lineage_by_step["3"]
    assert lineage["primary_action_request_id"] == ""
    assert lineage["fallback_action_request_id"] == ""
    payload = _rf5r6_reconciliation_payload(client, row)
    assert payload["primary_action_request_id"] == ""
    assert payload["action_request_id"] == ""
    assert payload["production_visit_credit"] == 0


def test_fallback_without_prior_cache_keeps_missing_current_request_unknown():
    client = _rf5r5_real_producer_client()
    client._has_recent_helper_ok = lambda **_kwargs: False
    client.check_helper_status = lambda **_kwargs: False
    audit = {}

    row = _rf5r6_controlled_fallback(client, audit)

    assert row["smart_nav_req_id"] == ""
    assert audit["fallback_helper_request_id"] == ""
    assert audit["fallback_result_correlated"] is False
    payload = _rf5r6_reconciliation_payload(client, row)
    assert payload["primary_action_request_id"] == ""
    assert payload["action_request_id"] == ""
    assert payload["production_visit_credit"] == 0


def test_fallback_audit_and_reconciliation_keep_current_invocation_request_only():
    client = _rf5r5_real_producer_client()
    client.last_smart_nav_result = {
        "reqId": "request-old", "success": True, "status": "moved",
    }
    client._has_recent_helper_ok = lambda **_kwargs: True
    client._helper_bridge._request_smart_next = lambda *, dev, req_id: {
        "reqId": req_id, "success": True, "status": "moved",
    }
    audit = {}

    row = _rf5r6_controlled_fallback(client, audit)

    request_id = row["smart_nav_req_id"]
    assert request_id and request_id != "request-old"
    assert audit["fallback_helper_request_id"] == request_id
    assert audit["fallback_helper_ack_result"]["reqId"] == request_id
    assert audit["helper_request_id"] == request_id
    lineage = client._focus_reconciliation_lineage_by_step["3"]
    assert lineage["primary_action_request_id"] == request_id
    assert lineage["fallback_action_request_id"] == request_id
    payload = _rf5r6_reconciliation_payload(client, row)
    assert payload["primary_action_request_id"] == request_id
    assert payload["action_request_id"] == request_id
    assert payload["production_visit_credit"] == 0


def _rf5r7_native_client(monkeypatch):
    client = _rf5r5_real_producer_client()
    client._has_recent_helper_ok = lambda **_kwargs: True
    client._broadcast = MethodType(A11yAdbClient._broadcast, client)
    client._read_log_result = lambda dev, prefix, req_id, **kw: {
        "reqId": req_id, "success": True, "status": "moved",
    }
    native_calls = []

    def native_success(command, **kwargs):
        native_calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="Broadcast completed: result=0", stderr="")

    monkeypatch.setattr("talkback_lib.adb_device.subprocess.run", native_success)
    return client, native_calls


def test_rf5r7_pre_action_exception_after_real_success_clears_row_and_fallback_lineage(monkeypatch):
    client, native_calls = _rf5r7_native_client(monkeypatch)
    previous = _rf5r5_collect_step(client)
    before = len(native_calls)

    def pre_action_failure(*args, **kwargs):
        raise RuntimeError("pre-action evidence failed")

    client._evidence_begin_step_action = pre_action_failure
    audit = {}
    row = _rf5r6_controlled_fallback(client, audit)

    assert len(native_calls) == before
    assert row["smart_nav_invocation_generation"] > previous["smart_nav_invocation_generation"]
    assert row["smart_nav_result_generation"] is None
    assert row["smart_nav_req_id"] == ""
    assert row["smart_nav_success"] is False
    assert client._last_smart_nav_invocation_result == {}
    assert client.last_smart_nav_result["reqId"] == previous["smart_nav_req_id"]
    assert audit["fallback_helper_request_id"] == ""
    assert audit["helper_request_id"] == ""
    assert audit["fallback_result_correlated"] is False
    payload = _rf5r6_reconciliation_payload(client, row)
    assert payload["primary_action_request_id"] == ""
    assert payload["action_request_id"] == ""
    assert payload["production_visit_credit"] == 0
    _assert_missing_smart_next_handoff(row, monkeypatch)


def test_rf5r7_pre_action_exception_without_history_has_no_current_result(monkeypatch):
    client, native_calls = _rf5r7_native_client(monkeypatch)
    client._evidence_begin_step_action = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("pre-action"))
    row = _rf5r5_collect_step(client)
    assert native_calls == []
    assert row["smart_nav_invocation_generation"] == 1
    assert row["smart_nav_result_generation"] is None
    assert row["smart_nav_req_id"] == ""
    assert row["smart_nav_success"] is False
    assert client.last_smart_nav_result == {}


def test_rf5r7_invocation_starts_before_baseline_hook_and_row_creation(monkeypatch):
    from pytest import raises

    client, native_calls = _rf5r7_native_client(monkeypatch)
    previous = _rf5r5_collect_step(client)
    client.normalize_for_comparison = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("baseline hook"))
    with raises(RuntimeError, match="baseline hook"):
        _rf5r5_collect_step(client)
    assert len(native_calls) == 1
    assert client._smart_nav_invocation_generation > previous["smart_nav_invocation_generation"]
    assert client._last_smart_nav_invocation_result == {}
    assert client._smart_nav_result_generation is None
    assert client.last_smart_nav_result["reqId"] == previous["smart_nav_req_id"]


def test_rf5r7_matching_stale_row_and_slot_cannot_authorize_fallback_lineage(monkeypatch):
    client, native_calls = _rf5r7_native_client(monkeypatch)
    previous = _rf5r5_collect_step(client)
    audit = {}
    row = _rf5r6_controlled_fallback(client, audit, collect=lambda **kw: deepcopy(previous))
    assert len(native_calls) == 1
    assert audit["fallback_helper_request_id"] == ""
    assert audit["helper_request_id"] == ""
    assert row["smart_nav_req_id"] == ""
    assert row["smart_nav_success"] is False
    assert row["move_result"]["success"] is False
    payload = _rf5r6_reconciliation_payload(client, row)
    assert payload["primary_action_request_id"] == ""
    assert payload["action_request_id"] == ""
    assert payload["production_visit_credit"] == 0
    assert client.last_smart_nav_result["reqId"] == previous["smart_nav_req_id"]


def test_rf5r7_real_current_fallback_result_has_same_invocation_and_new_request(monkeypatch):
    client, native_calls = _rf5r7_native_client(monkeypatch)
    previous = _rf5r5_collect_step(client)
    audit = {}
    row = _rf5r6_controlled_fallback(client, audit)
    assert len(native_calls) == 2
    assert row["smart_nav_req_id"] != previous["smart_nav_req_id"]
    assert row["smart_nav_result_generation"] == row["smart_nav_invocation_generation"]
    assert row["smart_nav_invocation_generation"] == client._smart_nav_result_generation
    assert audit["fallback_helper_request_id"] == row["smart_nav_req_id"]
    payload = _rf5r6_reconciliation_payload(client, row)
    assert payload["primary_action_request_id"] == row["smart_nav_req_id"]
    assert payload["action_request_id"] == row["smart_nav_req_id"]


def test_rf5r7_native_timeout_fallback_preserves_current_invocation_request(monkeypatch):
    client, native_calls = _rf5r7_native_client(monkeypatch)
    previous = _rf5r5_collect_step(client)

    def timeout(command, **kwargs):
        native_calls.append(list(command))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("talkback_lib.adb_device.subprocess.run", timeout)
    audit = {}
    row = _rf5r6_controlled_fallback(client, audit)
    assert len(native_calls) == 2
    assert row["smart_nav_req_id"] and row["smart_nav_req_id"] != previous["smart_nav_req_id"]
    assert row["smart_nav_success"] is False
    assert row["smart_nav_result_generation"] == row["smart_nav_invocation_generation"]
    assert audit["fallback_helper_request_id"] == row["smart_nav_req_id"]
    assert client.last_smart_nav_result["reqId"] == previous["smart_nav_req_id"]
    payload = _rf5r6_reconciliation_payload(client, row)
    assert payload["primary_action_request_id"] == row["smart_nav_req_id"]
    assert payload["production_visit_credit"] == 0


def _prepare_real_frontier_handoff(monkeypatch, *, snapshot_focus=None):
    raw = _production_raw()
    if snapshot_focus is not None:
        raw["focus_node"] = deepcopy(snapshot_focus)
    row = {
        "scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": 3,
        "capture_id": CAPTURE_ID, "timestamp": raw["timestamp"],
        "state_graph_observation": deepcopy(raw),
        "production_observation_envelope": deepcopy(raw["production_observation_envelope"]),
        "_exploration_observation": deepcopy(MARKER),
        "dump_tree_nodes": deepcopy(raw["nodes"]),
        "controlled_focus_request_id": "request-current",
        "phase6_current_action_type": "CONTROLLED_FOCUS",
        "target_focus_attempt_id": "target-attempt-current",
        # The ordinary Phase4 reconciliation is intentionally retained as a
        # separate observation and may name a different focus node.
        "actual_focus_node": {
            "viewIdResourceName": f"{PACKAGE}:id/more",
            "boundsInScreen": "[912,126][1032,270]",
            "className": "android.widget.Button", "accessibilityFocused": True,
        },
        "actual_focus_resource_id": f"{PACKAGE}:id/more",
        "actual_focus_bounds": "[912,126][1032,270]",
        "actual_focus_accessibility_focused": True,
        "actual_focus_instance_id": instance_id({
            "scenario_id": SCENARIO, "view_id": f"{PACKAGE}:id/more",
            "bounds": "[912,126][1032,270]",
        }),
    }
    frontier_runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        frontier_runtime, row=row, candidates=[], scenario_id=SCENARIO,
        raw_nodes=raw["nodes"], projection_complete=True,
    )
    evaluate_post_action = frontier_runtime.evaluate_post_action

    def observe_post_action(**kwargs):
        frontier_runtime.last_focus_cursor = deepcopy(kwargs.get("focus_cursor") or {})
        return evaluate_post_action(**kwargs)

    frontier_runtime.evaluate_post_action = observe_post_action
    decision_sink = _DecisionSink()
    client = SimpleNamespace(
        _phase6c2_frontier_shadow_runtime=frontier_runtime,
        _phase6d_exploration_shadow_runtime=decision_sink,
    )
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())
    decision = collection_flow._prepare_phase6d_exploration_decision(
        client=client, row=row, step_idx=3,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content", "max_steps": 32},
        stop_candidate=False, stop_reason="", stop_eval_inputs={},
        pre_decision_ref=None,
    )
    assert decision == "phase6-decision-token"
    assert decision_sink.kwargs is not None
    return frontier_runtime, decision_sink.kwargs


def test_controlled_request_id_is_same_at_inventory_and_post_action_decision(monkeypatch):
    frontier, decision = _prepare_real_frontier_handoff(monkeypatch)

    assert frontier._latest_inventory["observation_ref"]["request_id"] == "request-current"
    assert decision["frontier_evaluation"]["alignment_status"] == "ALIGNED"
    assert decision["frontier_evaluation"]["source_request_id"] == "request-current"
    assert "POST_ACTION_REQUEST_ID_MISMATCH" not in decision["stale_reasons"]


def test_frontier_post_result_uses_controlled_request_not_target_attempt_id():
    class PostResultSink:
        def __init__(self):
            self.kwargs = None

        def post_result(self, **kwargs):
            self.kwargs = kwargs

        def _fail(self, *_args, **_kwargs):
            raise AssertionError("frontier post-result hook must not fail")

    sink = PostResultSink()
    client = SimpleNamespace(_phase6c2_frontier_shadow_runtime=sink)
    row = {
        "scenario_id": SCENARIO, "step_index": 3,
        "target_focus_attempted": True, "target_focus_fallback_used": False,
        "phase6_current_action_type": "CONTROLLED_FOCUS",
        "target_focus_attempt_id": "target-attempt-current",
        "controlled_focus_request_id": "request-current",
        "target_focus_descriptor": {
            "resource_id": f"{PACKAGE}:id/more",
            "bounds": "[912,126][1032,270]",
            "class_name": "android.widget.Button",
        },
    }
    collection_flow._frontier_shadow_post_result(
        client=client, decision_id="decision-3", step_idx=3,
        previous_row=None, row=row,
    )

    assert sink.kwargs is not None
    assert sink.kwargs["result_id"] == "request-current"


def test_phase6_cursor_uses_same_snapshot_focus_not_preserved_phase4_focus(monkeypatch):
    snapshot_focus = {
        "viewIdResourceName": f"{PACKAGE}:id/SmokeDetectorCapabilityCardView",
        "boundsInScreen": "[100,400][900,600]",
        "className": "android.widget.TextView", "text": "Smoke sensor",
        "accessibilityFocused": True, "focused": False,
    }
    _frontier, decision = _prepare_real_frontier_handoff(
        monkeypatch, snapshot_focus=snapshot_focus)

    cursor = _frontier.last_focus_cursor
    assert cursor == {
        "instance_id": instance_id({
            "scenario_id": SCENARIO,
            "view_id": f"{PACKAGE}:id/SmokeDetectorCapabilityCardView",
            "bounds": "[100,400][900,600]",
        }),
        "confirmed": True,
    }


def test_phase6_cursor_fails_closed_when_snapshot_focus_capture_is_misaligned():
    raw = _production_raw()
    raw["focus_capture_id"] = "older-focus-capture"
    row = {
        "scenario_id": SCENARIO, "scenario_run_id": RUN_ID,
        "capture_id": CAPTURE_ID, "_exploration_observation": deepcopy(MARKER),
    }

    assert collection_flow._phase6d_snapshot_focus_cursor(row, raw) == {
        "instance_id": "", "confirmed": False,
    }


def _pre_decision_cursor(monkeypatch, raw, *, phase4_focus=None, clock=None):
    phase4_focus = phase4_focus or {
        "viewIdResourceName": f"{PACKAGE}:id/more",
        "boundsInScreen": "[912,126][1032,270]",
        "className": "android.widget.Button", "accessibilityFocused": True,
    }
    row = {
        "scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": 3,
        "capture_id": raw["capture_id"], "timestamp": raw["timestamp"],
        "state_graph_observation": deepcopy(raw),
        "production_observation_envelope": deepcopy(raw["production_observation_envelope"]),
        "_exploration_observation": deepcopy(raw["_exploration_observation"]),
        "dump_tree_nodes": deepcopy(raw["nodes"]),
        # Preserve the actual Phase4 focus as historical evidence. PRE_DECISION
        # must use the independently linked snapshot focus stored with inventory.
        "actual_focus_node": deepcopy(phase4_focus),
        "actual_focus_accessibility_focused": True,
        "actual_focus_resource_id": phase4_focus.get("viewIdResourceName", ""),
        "actual_focus_bounds": phase4_focus.get("boundsInScreen", ""),
        "controlled_focus_request_id": "prior-request",
        "controlled_focus_operation_id": "prior-operation",
        "target_focus_attempt_id": "prior-attempt",
    }
    runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        runtime, row=row, candidates=[], scenario_id=SCENARIO,
        raw_nodes=raw["nodes"], projection_complete=True,
    )
    client = SimpleNamespace(_phase6c2_frontier_shadow_runtime=runtime)
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: clock or _Clock())
    state = SimpleNamespace(previous_step_row=row)
    decision = collection_flow._frontier_shadow_pre_decision(
        client=client, state=state, step_idx=4,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content"},
    )
    assert decision
    return runtime._pending[decision]["pre_cursor"], row


def test_pre_decision_cursor_uses_current_snapshot_linked_focus(monkeypatch):
    raw = _production_raw()
    snapshot_focus = {
        "viewIdResourceName": f"{PACKAGE}:id/SmokeDetectorCapabilityCardView",
        "boundsInScreen": "[100,400][900,600]",
        "className": "android.widget.TextView", "text": "Smoke sensor",
        "accessibilityFocused": True, "focused": False,
    }
    raw["focus_node"] = deepcopy(snapshot_focus)
    cursor, row = _pre_decision_cursor(monkeypatch, raw)

    assert cursor == {
        "instance_id": instance_id({
            "scenario_id": SCENARIO,
            "view_id": f"{PACKAGE}:id/SmokeDetectorCapabilityCardView",
            "bounds": "[100,400][900,600]",
        }),
        "confirmed": True,
    }
    assert row["actual_focus_node"]["viewIdResourceName"] == f"{PACKAGE}:id/more"


def test_pre_decision_does_not_promote_old_phase4_focus_or_node_presence(monkeypatch):
    raw = _production_raw()
    # The old Phase4 node remains in the hierarchy, but this capture does not
    # carry strict accessibility focus on it.
    raw["nodes"].append({
        "viewIdResourceName": f"{PACKAGE}:id/more", "text": "More options",
        "className": "android.widget.Button", "boundsInScreen": "[912,126][1032,270]",
        "visibleToUser": True, "focusable": True,
    })
    raw["focus_node"] = {
        "viewIdResourceName": f"{PACKAGE}:id/more", "text": "More options",
        "className": "android.widget.Button", "boundsInScreen": "[912,126][1032,270]",
        "accessibilityFocused": False, "focused": True,
    }
    cursor, row = _pre_decision_cursor(monkeypatch, raw)

    assert cursor == {"instance_id": "", "confirmed": False}
    assert row["actual_focus_node"]["accessibilityFocused"] is True


def test_pre_decision_rejects_stale_snapshot_request_operation_focus(monkeypatch):
    raw = _production_raw()
    class StaleClock:
        def current(self, _marker):
            return False

    cursor, _row = _pre_decision_cursor(monkeypatch, raw, clock=StaleClock())

    assert cursor == {"instance_id": "", "confirmed": False}


def test_pre_decision_unlinked_snapshot_marker_is_unresolved(monkeypatch):
    raw = _production_raw()
    raw["_exploration_observation"]["observation_sequence"] += 1
    cursor, _row = _pre_decision_cursor(monkeypatch, raw)

    assert cursor == {"instance_id": "", "confirmed": False}


def test_generic_target_request_id_survives_inventory_decision_audit_and_history(monkeypatch):
    target = {
        "viewIdResourceName": f"{PACKAGE}:id/target",
        "text": "Target", "className": "android.widget.Button",
        "boundsInScreen": "[10,10][110,110]", "accessibilityFocused": True,
        "focused": False, "focusable": True, "visibleToUser": True,
    }
    client_for_target = SimpleNamespace(
        target_focus_commit=lambda **_kwargs: {
            "success": True, "status": "TARGET_MATCHED", "reqId": "helper-target-request",
        },
        get_focus=lambda **_kwargs: deepcopy(target),
    )
    row = {
        "scenario_id": SCENARIO, "step_index": 3,
        "focus_view_id": "old-focus", "focus_bounds": "[200,10][300,110]",
        "visible_label": "Old focus",
        "smart_nav_req_id": "previous-smart-next-request",
    }
    result = focus_realign_logic._maybe_realign_focus_to_representative_impl(
        client=client_for_target, dev="serial", row=row, selected_node=target,
        selected_rid=target["viewIdResourceName"], selected_label="Target",
        selected_bounds=target["boundsInScreen"], scenario_id=SCENARIO, step_idx=3,
        mismatch_logged=True, force_reason="anchor_mismatch", scenario_perf=None,
        focus_matches_fn=lambda **kwargs: focus_realign_logic._target_focus_matches(**kwargs),
        extract_label_fn=lambda node: node.get("text", ""),
        label_blob_fn=lambda node: node.get("talkbackLabel", ""),
        truncate_fn=lambda value, _limit: str(value), log_fn=lambda _message: None,
    )
    assert result[0] is True
    assert row["target_focus_request_id"] == "helper-target-request"
    assert row["target_focus_attempt_id"] != row["target_focus_request_id"]
    assert row["phase6_current_action_type"] == "TARGETED_FOCUS"

    raw = _production_raw()
    raw["focus_node"] = deepcopy(target)
    raw["nodes"].append(deepcopy(target))
    row.update(
        scenario_run_id=RUN_ID, capture_id=CAPTURE_ID,
        state_graph_observation=deepcopy(raw),
        production_observation_envelope=deepcopy(raw["production_observation_envelope"]),
        _exploration_observation=deepcopy(MARKER),
        dump_tree_nodes=deepcopy(raw["nodes"]),
        actual_focus_node=deepcopy(target), actual_focus_accessibility_focused=True,
        actual_focus_resource_id=target["viewIdResourceName"],
        actual_focus_bounds=target["boundsInScreen"],
        actual_focus_visible="Target", actual_focus_class_name=target["className"],
        actual_focus_instance_id=instance_id({
            "scenario_id": SCENARIO, "view_id": target["viewIdResourceName"],
            "bounds": target["boundsInScreen"],
        }),
        focus_transition_status="CONFIRMED_MOVED", visit_record_status="UNVISITED",
        command_ack_status="ACKED",
    )
    runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        runtime, row=row,
        candidates=[{"node": target, "view_id": target["viewIdResourceName"],
                     "bounds": target["boundsInScreen"], "class_name": target["className"],
                     "label": "Target"}],
        scenario_id=SCENARIO, raw_nodes=raw["nodes"], projection_complete=True,
    )
    assert runtime._latest_inventory["observation_ref"]["request_id"] == "helper-target-request"

    decision_sink = _DecisionSink()
    client = SimpleNamespace(
        _phase6c2_frontier_shadow_runtime=runtime,
        _phase6d_exploration_shadow_runtime=decision_sink,
    )
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())
    token = collection_flow._prepare_phase6d_exploration_decision(
        client=client, row=row, step_idx=3,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content", "max_steps": 32},
        stop_candidate=False, stop_reason="", stop_eval_inputs={}, pre_decision_ref=None,
    )
    assert token == "phase6-decision-token"
    assert decision_sink.kwargs["frontier_evaluation"]["source_request_id"] == "helper-target-request"

    pending = runtime.pre_decision(
        step=4, production_choice={"action_type": "TARGETED_FOCUS"},
        state_id=runtime._latest_inventory["state_id"],
        inventory_complete=runtime._latest_inventory["inventory_complete"],
    )
    assert pending
    row["target_focus_attempted"] = True
    row["target_focus_fallback_used"] = False
    assert collection_flow._frontier_shadow_post_result(
        client=client, decision_id=pending, step_idx=4,
        previous_row=None, row=row,
    ) is None

    audit = runtime.evaluations[-1]["action_result"]
    history = runtime.history["attempt_events"]
    assert audit["result_id"] == "helper-target-request"
    assert audit["request_id"] == "helper-target-request"
    assert audit["attempt_id"] == row["target_focus_attempt_id"]
    assert len(history) == 1
    assert history[0]["request_id"] == "helper-target-request"
    assert history[0]["attempt_id"] == row["target_focus_attempt_id"]


def test_generic_target_failure_does_not_borrow_prior_smart_next_request(monkeypatch):
    target = {
        "viewIdResourceName": f"{PACKAGE}:id/target",
        "text": "Target", "className": "android.widget.Button",
        "boundsInScreen": "[10,10][110,110]", "accessibilityFocused": False,
        "focused": False, "focusable": True, "visibleToUser": True,
    }
    previous_focus = {
        "viewIdResourceName": f"{PACKAGE}:id/more", "text": "More options",
        "className": "android.widget.Button", "boundsInScreen": "[912,126][1032,270]",
        "accessibilityFocused": True, "focused": False,
    }
    client_for_target = SimpleNamespace(
        target_focus_commit=lambda **_kwargs: {
            "success": False, "status": "ERROR", "reason": "helper_unavailable",
        },
        get_focus=lambda **_kwargs: deepcopy(previous_focus),
    )
    row = {
        "scenario_id": SCENARIO, "step_index": 3,
        "focus_view_id": previous_focus["viewIdResourceName"],
        "focus_bounds": previous_focus["boundsInScreen"],
        "visible_label": previous_focus["text"],
        "smart_nav_req_id": "previous-smart-next-request",
    }
    focus_realign_logic._maybe_realign_focus_to_representative_impl(
        client=client_for_target, dev="serial", row=row, selected_node=target,
        selected_rid=target["viewIdResourceName"], selected_label="Target",
        selected_bounds=target["boundsInScreen"], scenario_id=SCENARIO, step_idx=3,
        mismatch_logged=True, force_reason="anchor_mismatch", scenario_perf=None,
        focus_matches_fn=lambda **kwargs: focus_realign_logic._target_focus_matches(**kwargs),
        extract_label_fn=lambda node: node.get("text", ""),
        label_blob_fn=lambda node: node.get("talkbackLabel", ""),
        truncate_fn=lambda value, _limit: str(value), log_fn=lambda _message: None,
    )

    assert row["target_focus_attempted"] is True
    assert row["target_focus_request_id"] == ""
    assert row["phase6_current_action_type"] == "TARGETED_FOCUS"
    from tb_runner.frontier_shadow import canonical_action_request_id
    assert canonical_action_request_id(row) == ""

    raw = _production_raw()
    raw["focus_node"] = deepcopy(previous_focus)
    target_node = {**deepcopy(target), "accessibilityFocused": False}
    raw["nodes"].append(target_node)
    row.update(
        scenario_run_id=RUN_ID, capture_id=CAPTURE_ID, timestamp=raw["timestamp"],
        state_graph_observation=deepcopy(raw),
        production_observation_envelope=deepcopy(raw["production_observation_envelope"]),
        _exploration_observation=deepcopy(MARKER), dump_tree_nodes=deepcopy(raw["nodes"]),
        actual_focus_node=deepcopy(previous_focus),
        actual_focus_accessibility_focused=True,
        actual_focus_resource_id=previous_focus["viewIdResourceName"],
        actual_focus_bounds=previous_focus["boundsInScreen"],
        actual_focus_visible=previous_focus["text"],
        actual_focus_class_name=previous_focus["className"],
        actual_focus_instance_id=instance_id({
            "scenario_id": SCENARIO, "view_id": previous_focus["viewIdResourceName"],
            "bounds": previous_focus["boundsInScreen"],
        }),
        focus_transition_status="CONFIRMED_UNCHANGED", visit_record_status="UNVISITED",
        command_ack_status="ERROR",
    )
    runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        runtime, row=row,
        candidates=[{"node": target_node, "view_id": target_node["viewIdResourceName"],
                     "bounds": target_node["boundsInScreen"], "class_name": target_node["className"],
                     "label": "Target"}],
        scenario_id=SCENARIO, raw_nodes=raw["nodes"], projection_complete=True,
    )
    inventory_ref = runtime._latest_inventory["observation_ref"]
    assert inventory_ref["request_id"] == ""

    decision_sink = _DecisionSink()
    client = SimpleNamespace(
        _phase6c2_frontier_shadow_runtime=runtime,
        _phase6d_exploration_shadow_runtime=decision_sink,
    )
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())
    assert collection_flow._prepare_phase6d_exploration_decision(
        client=client, row=row, step_idx=3,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content", "max_steps": 32},
        stop_candidate=False, stop_reason="", stop_eval_inputs={}, pre_decision_ref=None,
    ) == "phase6-decision-token"
    frontier_decision = decision_sink.kwargs["frontier_evaluation"]
    assert frontier_decision["alignment_status"] == "INCOMPLETE"
    assert frontier_decision["source_request_id"] is None

    pending = runtime.pre_decision(
        step=4, production_choice={"action_type": "TARGETED_FOCUS"},
        state_id=runtime._latest_inventory["state_id"],
        inventory_complete=runtime._latest_inventory["inventory_complete"],
    )
    assert pending
    row["step_index"] = 4
    collection_flow._frontier_shadow_post_result(
        client=client, decision_id=pending, step_idx=4,
        previous_row=None, row=row,
    )
    audit = runtime.evaluations[-1]["action_result"]
    assert audit["request_id"] is None
    assert audit["ownership_status"] == "UNKNOWN"
    assert runtime.history["attempt_events"] == []
    assert runtime.history["complete"] is False
