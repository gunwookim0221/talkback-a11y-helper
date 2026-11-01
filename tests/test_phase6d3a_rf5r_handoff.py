"""Functional reconstruction of Phase6D RF5 capture-handoff regression coverage.

Reconstructed from RCA #31, current production callsites, phase6d_capture_support,
and the RF5 contract fragments. This is not a byte-exact restoration.
"""
from phase6d_projection_fixture import fixture_snapshot
from copy import deepcopy
from types import SimpleNamespace

import pytest

from phase6d_capture_support import (
    attach_capture_authority,
    bind_observation_marker,
)
from talkback_lib.reliable_hierarchy_schema import _freeze
from tb_runner import collection_flow, focus_realign_logic
from tb_runner.frontier_shadow import (
    FrontierShadowRuntime,
    capture_reconciled_inventory,
)
from tb_runner.phase3_context import resolve_phase3_context
from tb_runner.state_graph import _raw_observation_from_row, build_graph_state_identity
from tb_runner.traversal_reliability import instance_id
from tools import state_fingerprint_diagnostic


SCENARIO = "device_smoke_sensor_plugin"
RUN_ID = "rf5r-functional-reconstruction"
PACKAGE = "com.samsung.android.oneconnect"
NAVIGATION_EPOCH = "rf5r-navigation-epoch"
REQUEST_ID = "rf5r-capture-request-8"
MARKER = {
    "scope_id": "rf5r-offline-scope",
    "observation_sequence": 8,
    "action_epoch": 3,
    "observation_epoch": 3,
    "capture_end_action_epoch": 3,
    "context_revision": 0,
    "observation_id": "observation:rf5r-offline-scope:8",
    "capture_complete": True,
}


def _production_raw(*, coverage="OBSERVED_FULL", focused="more",
                    request_id=REQUEST_ID, include_snapshot_bundle=True):
    nodes = [
        {
            "packageName": PACKAGE,
            "viewIdResourceName": f"{PACKAGE}:id/SmokeDetectorCapabilityCardView",
            "text": "Smoke sensor",
            "className": "android.widget.TextView",
            "boundsInScreen": "[100,400][900,600]",
            "visibleToUser": True,
            "focusable": True,
            "enabled": True,
            "accessibilityFocused": focused == "sensor",
        },
        {
            "packageName": PACKAGE,
            "viewIdResourceName": f"{PACKAGE}:id/menu_devices",
            "text": "Devices",
            "className": "android.widget.TextView",
            "boundsInScreen": "[0,2200][200,2400]",
            "visibleToUser": True,
            "selected": True,
            "focusable": True,
            "accessibilityFocused": False,
        },
        {
            "packageName": PACKAGE,
            "viewIdResourceName": f"{PACKAGE}:id/more",
            "text": "More options",
            "className": "android.widget.Button",
            "boundsInScreen": "[912,126][1032,270]",
            "visibleToUser": True,
            "focusable": True,
            "enabled": True,
            "accessibilityFocused": focused == "more",
            "focused": False,
        },
        {
            "packageName": PACKAGE,
            "viewIdResourceName": f"{PACKAGE}:id/target",
            "text": "Target",
            "className": "android.widget.Button",
            "boundsInScreen": "[10,700][200,780]",
            "visibleToUser": True,
            "focusable": True,
            "enabled": True,
            "accessibilityFocused": focused == "target",
            "focused": False,
        },
    ]
    focus_node = next(
        node for node in nodes
        if node["viewIdResourceName"] == f"{PACKAGE}:id/{focused}"
        or (focused == "sensor" and node["viewIdResourceName"].endswith("CapabilityCardView"))
    )
    raw = {
        "scenario_id": SCENARIO,
        "scenario_run_id": RUN_ID,
        "timestamp": "2026-10-25T00:00:08+00:00",
        "package_name": PACKAGE,
        # Activity and window diagnostics never provide trusted component proof.
        "activity_name": None,
        "context_source": "capture_local_hierarchy_root",
        "navigation_context": {"bottom_tab": "devices"},
        "selected_tab": {
            "name": "devices", "verified": True,
            "source": "service_hierarchy_selected",
        },
        "display_bounds": [0, 0, 1080, 2400],
        "capture_root_bounds": [0, 0, 1080, 2400],
        "observation_coverage": coverage,
        "nodes": nodes,
        "focus_node": deepcopy(focus_node),
        "navigation_epoch": NAVIGATION_EPOCH,
    }
    attach_capture_authority(
        raw, production=True, sequence=8, request_id=request_id,
        window_id=17, include_test_capture_bundle=include_snapshot_bundle,
    )
    capture_id = raw["capture_authority"]["capture_key"]
    raw["focus_capture_id"] = capture_id if focus_node.get("accessibilityFocused") is True else None
    raw["geometry_capture_id"] = capture_id if any(
        node.get("boundsInScreen") for node in nodes
    ) else None
    envelope = raw["production_observation_envelope"]
    envelope["focus_capture_id"] = raw["focus_capture_id"]
    envelope["geometry_capture_id"] = raw["geometry_capture_id"]
    bind_observation_marker(raw, MARKER)
    return raw


def _row_for(raw, *, request_id="controlled-request-current",
             action_type="CONTROLLED_FOCUS"):
    return {
        "scenario_id": SCENARIO,
        "scenario_run_id": RUN_ID,
        "step_index": 3,
        "capture_id": raw["capture_id"],
        "timestamp": raw["timestamp"],
        "state_graph_observation": deepcopy(raw),
        "production_observation_envelope": deepcopy(raw["production_observation_envelope"]),
        "_exploration_observation": deepcopy(raw["_exploration_observation"]),
        "dump_tree_nodes": deepcopy(raw["nodes"]),
        "phase6_current_action_type": action_type,
        "controlled_focus_request_id": request_id if action_type == "CONTROLLED_FOCUS" else "",
        "target_focus_request_id": request_id if action_type == "TARGETED_FOCUS" else "",
        "target_focus_attempt_id": "target-attempt-current",
        "target_focus_fallback_used": False,
        "controlled_focus_dispatch_status": "DISPATCHED",
        "actual_focus_node": {
            "viewIdResourceName": f"{PACKAGE}:id/more",
            "boundsInScreen": "[912,126][1032,270]",
            "text": "More options",
            "className": "android.widget.Button",
            "accessibilityFocused": True,
            "focused": False,
        },
        "actual_focus_resource_id": f"{PACKAGE}:id/more",
        "actual_focus_bounds": "[912,126][1032,270]",
        "actual_focus_visible": "More options",
        "actual_focus_class_name": "android.widget.Button",
        "actual_focus_accessibility_focused": True,
        "actual_focus_instance_id": instance_id({
            "scenario_id": SCENARIO,
            "view_id": f"{PACKAGE}:id/more",
            "bounds": "[912,126][1032,270]",
        }),
        "focus_transition_status": "CONFIRMED_MOVED",
        "visit_record_status": "UNVISITED_NOT_CREDITED",
    }


class _Clock:
    scope_id = MARKER["scope_id"]

    def begin_observation(self):
        return object()

    def finish_observation(self, _token):
        return deepcopy(MARKER)

    def current(self, marker):
        return marker == MARKER


class _DecisionSink:
    def __init__(self):
        self.kwargs = None

    def prepare_decision(self, **kwargs):
        self.kwargs = kwargs
        return "phase6-decision-token"


def _snapshot_client(raw, *, mutation=None, fail=False):
    bundle = raw["_phase6d_test_capture_bundle"]
    hierarchy = deepcopy(bundle["raw_hierarchy"])
    transfer = deepcopy(bundle["transport_metadata"])
    snapshot = fixture_snapshot(hierarchy, transfer, mutation=mutation)

    class Client:
        last_dump_metadata = {}
        last_scroll_capabilities = []

        def __init__(self):
            self.snapshot_calls = 0
            self.legacy_calls = []

        def get_traversal_candidate_snapshot(self, *, dev):
            assert dev == "serial"
            self.snapshot_calls += 1
            if fail:
                raise RuntimeError("reliable snapshot incomplete")
            return snapshot

        def get_focus(self, **_kwargs):
            self.legacy_calls.append("focus")
            raise AssertionError("legacy focus must not rescue a reliable capture")

        def dump_hierarchy(self, **_kwargs):
            self.legacy_calls.append("hierarchy")
            raise AssertionError("legacy hierarchy must not rescue a reliable capture")

        def _run(self, command, **_kwargs):
            if command == ["shell", "wm", "size"]:
                return "Physical size: 1080x2400"
            if command == ["shell", "dumpsys", "window"]:
                return f"mCurrentFocus=Window{{a u0 {PACKAGE}/.MainActivity}}"
            return ""

    return Client()


def _prepare_frontier_handoff(monkeypatch, raw, *, request_id):
    row = _row_for(raw, request_id=request_id)
    runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        runtime, row=row, candidates=[], scenario_id=SCENARIO,
        raw_nodes=raw["nodes"], projection_complete=True,
    )
    original_evaluate = runtime.evaluate_post_action

    def capture_cursor(**kwargs):
        runtime.last_focus_cursor = deepcopy(kwargs.get("focus_cursor") or {})
        return original_evaluate(**kwargs)

    runtime.evaluate_post_action = capture_cursor
    sink = _DecisionSink()
    client = SimpleNamespace(
        _phase6c2_frontier_shadow_runtime=runtime,
        _phase6d_exploration_shadow_runtime=sink,
    )
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())
    decision_token = collection_flow._prepare_phase6d_exploration_decision(
        client=client, row=row, step_idx=3,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content", "max_steps": 32},
        stop_candidate=False, stop_reason="", stop_eval_inputs={},
        pre_decision_ref=None,
    )
    assert decision_token == "phase6-decision-token"
    return runtime, sink, row, client


def test_reliable_capture_uses_one_snapshot_for_focus_and_hierarchy():
    raw = _production_raw()
    client = _snapshot_client(raw)

    captured = state_fingerprint_diagnostic.capture_observation(
        client, "serial", scenario_id=SCENARIO, step=3, scenario_run_id=RUN_ID,
    )

    assert client.snapshot_calls == 1
    assert client.legacy_calls == []
    assert captured["snapshot_coherent"] is True
    assert captured["package_name"] == PACKAGE
    assert captured["activity_name"] == ".MainActivity"
    assert captured["context_source"] == "window_current_focus"
    assert captured["focus_node"]["accessibilityFocused"] is True
    assert captured["focus_node"]["viewIdResourceName"] == f"{PACKAGE}:id/more"
    assert captured["nodes"]
    assert captured["capture_authority"]["capture_key"] == captured["capture_id"]
    assert captured["hierarchy_capture_id"] == captured["focus_capture_id"]
    assert captured["hierarchy_capture_id"] == captured["geometry_capture_id"]
    assert captured["overlay"]["classification"] == "UNKNOWN_COMPONENT_BINDING"


@pytest.mark.parametrize("mutation", [
    lambda hierarchy, _transfer: hierarchy["captureEnvelope"].update(request_id="stale-request"),
    lambda hierarchy, _transfer: hierarchy["traversalCandidates"].update(rootCaptureId="foreign-root"),
    lambda _hierarchy, transfer: transfer["control"].update(capture_sequence=99),
])
def test_stale_or_cross_capture_envelope_is_rejected(mutation):
    raw = _production_raw()
    client = _snapshot_client(raw, mutation=mutation)

    captured = state_fingerprint_diagnostic.capture_observation(
        client, "serial", scenario_id=SCENARIO, step=3, scenario_run_id=RUN_ID,
    )

    assert captured["snapshot_coherent"] is False
    assert captured["capture_authority"] is None
    assert captured["hierarchy_capture_id"] is None
    assert captured["focus_capture_id"] is None
    assert captured["geometry_capture_id"] is None
    assert captured["focus_node"] == {}
    assert any(note.startswith(("hierarchy_capture:ValueError", "hierarchy_capture:ReliableHierarchySchemaError"))
               for note in captured["notes"])

    stale = _production_raw()
    stale["focus_capture_id"] = "other-capture"
    stale["production_observation_envelope"]["focus_capture_id"] = "other-capture"
    assert build_graph_state_identity(stale).status == "UNRESOLVED"


def test_failed_reliable_snapshot_is_not_rescued_by_legacy_focus_or_hierarchy():
    client = _snapshot_client(_production_raw(), fail=True)

    captured = state_fingerprint_diagnostic.capture_observation(
        client, "serial", scenario_id=SCENARIO, step=3, scenario_run_id=RUN_ID,
    )

    assert client.snapshot_calls == 1
    assert client.legacy_calls == []
    assert captured["source"] == "reliable_snapshot_failed"
    assert captured["snapshot_coherent"] is False
    assert captured["observation_coverage"] == "UNOBSERVED"
    assert captured["nodes"] == []
    assert captured["focus_node"] == {}
    assert captured["hierarchy_capture_id"] is None
    assert captured["focus_capture_id"] is None
    assert captured["geometry_capture_id"] is None


def test_production_handoff_preserves_current_entry_tree_focus_and_geometry(monkeypatch):
    raw = _production_raw()
    phase4_focus = {
        "viewIdResourceName": "production-phase4-focus",
        "accessibilityFocused": True,
    }
    row = {
        "scenario_id": SCENARIO,
        "scenario_run_id": RUN_ID,
        "step_index": 3,
        "navigation_epoch": NAVIGATION_EPOCH,
        "actual_focus_node": deepcopy(phase4_focus),
        "actual_focus_accessibility_focused": True,
    }
    client = SimpleNamespace(
        _phase6c2_frontier_shadow_runtime=object(),
        _phase6d3a_redirect_context={"scenario_run_id": RUN_ID},
    )
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())
    monkeypatch.setattr(
        "tools.state_fingerprint_diagnostic.capture_observation",
        lambda *_args, **_kwargs: deepcopy(raw),
    )

    captured = collection_flow._capture_phase6d3a_production_observation(
        client=client, dev="serial", row=row,
    )

    authority = raw["capture_authority"]
    assert captured["production_observation_current"] is True
    assert row["production_observation_capture_status"] == "CURRENT"
    assert row["production_observation_envelope"]["capture_id"] == authority["capture_key"]
    assert row["production_observation_envelope"]["hierarchy_capture_id"] == authority["capture_key"]
    assert row["production_observation_envelope"]["focus_capture_id"] == authority["capture_key"]
    assert row["production_observation_envelope"]["geometry_capture_id"] == authority["capture_key"]
    assert row["dump_tree_nodes"] == raw["nodes"]
    assert row["actual_focus_node"] == phase4_focus
    assert row["actual_focus_accessibility_focused"] is True
    identity = build_graph_state_identity(_raw_observation_from_row(row))
    assert identity.status == "RESOLVED"
    assert identity.context["status"] == "UNRESOLVED_CONTEXT"
    assert resolve_phase3_context(row["state_graph_observation"])["verified"] is False


def test_partial_capture_coverage_never_marks_frontier_inventory_complete():
    raw = _production_raw(coverage="OBSERVED_PARTIAL")
    row = _row_for(raw, request_id="partial-request")
    sink = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)

    capture_reconciled_inventory(
        sink, row=row, candidates=[], scenario_id=SCENARIO,
        raw_nodes=raw["nodes"], projection_complete=True,
    )

    assert sink._latest_inventory["state_id"]
    assert sink._latest_inventory["inventory_complete"] is False


def test_controlled_request_id_matches_inventory_and_post_action_decision(monkeypatch):
    raw = _production_raw()
    request_id = "controlled-request-unique"
    runtime, sink, _row, _client = _prepare_frontier_handoff(
        monkeypatch, raw, request_id=request_id,
    )

    assert runtime._latest_inventory["observation_ref"]["request_id"] == request_id
    decision = sink.kwargs
    assert decision["frontier_evaluation"]["alignment_status"] == "ALIGNED"
    assert decision["frontier_evaluation"]["source_request_id"] == request_id
    assert "POST_ACTION_REQUEST_ID_MISMATCH" not in decision["stale_reasons"]


def test_frontier_cursor_uses_snapshot_focus_not_preserved_phase4_focus(monkeypatch):
    raw = _production_raw(focused="sensor")
    runtime, _sink, row, _client = _prepare_frontier_handoff(
        monkeypatch, raw, request_id="cursor-request",
    )

    expected = {
        "instance_id": instance_id({
            "scenario_id": SCENARIO,
            "view_id": f"{PACKAGE}:id/SmokeDetectorCapabilityCardView",
            "bounds": "[100,400][900,600]",
        }),
        "confirmed": True,
    }
    assert row["actual_focus_node"]["viewIdResourceName"] == f"{PACKAGE}:id/more"
    assert runtime.last_focus_cursor == expected


def test_pre_decision_cursor_links_current_snapshot_focus(monkeypatch):
    raw = _production_raw(focused="sensor")
    row = _row_for(raw, request_id="predecision-request")
    row["actual_focus_node"] = {
        "viewIdResourceName": f"{PACKAGE}:id/more",
        "boundsInScreen": "[912,126][1032,270]",
        "className": "android.widget.Button",
        "accessibilityFocused": True,
    }
    runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        runtime, row=row, candidates=[], scenario_id=SCENARIO,
        raw_nodes=raw["nodes"], projection_complete=True,
    )
    client = SimpleNamespace(_phase6c2_frontier_shadow_runtime=runtime)
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())

    decision = collection_flow._frontier_shadow_pre_decision(
        client=client,
        state=SimpleNamespace(previous_step_row=row),
        step_idx=4,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content"},
    )

    expected = {
        "instance_id": instance_id({
            "scenario_id": SCENARIO,
            "view_id": f"{PACKAGE}:id/SmokeDetectorCapabilityCardView",
            "bounds": "[100,400][900,600]",
        }),
        "confirmed": True,
    }
    assert decision in runtime._pending
    assert runtime._pending[decision]["pre_cursor"] == expected
    assert row["actual_focus_node"]["viewIdResourceName"] == f"{PACKAGE}:id/more"


def test_pre_decision_does_not_reuse_inventory_invalidated_by_scroll(monkeypatch):
    raw = _production_raw(focused="sensor")
    row = _row_for(raw, request_id="pre-scroll-request")
    runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        runtime, row=row, candidates=[], scenario_id=SCENARIO,
        raw_nodes=raw["nodes"], projection_complete=True,
    )
    client = SimpleNamespace(_phase6c2_frontier_shadow_runtime=runtime)
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: SimpleNamespace(current=lambda _marker: False))

    decision = collection_flow._frontier_shadow_pre_decision(
        client=client, state=SimpleNamespace(previous_step_row=row), step_idx=4,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content"},
    )

    record = runtime._pending[decision]["record"]
    assert record["state_id"] is None
    assert record["observation_ref"]["state_resolution"] == "UNRESOLVED"
    assert record["observation_ref"]["production_capture_id"] is None
    assert record["observation_ref"]["request_id"] is None
    assert record["frontier_items"] == []
    assert record["evidence_complete"] is False


def test_initial_pre_decision_seeds_step_zero_from_current_production_capture(monkeypatch):
    raw = _production_raw(focused="sensor")
    raw.update(scenario_id=SCENARIO, scenario_run_id=RUN_ID,
               production_observation_current=True, snapshot_coherent=True,
               hierarchy_complete=True)
    envelope = raw["production_observation_envelope"]
    envelope.update(
        capture_complete=True, snapshot_coherent=True,
        scenario_id=SCENARIO, scenario_run_id=RUN_ID,
        capture_id=raw["capture_id"],
        hierarchy_capture_id=raw["hierarchy_capture_id"],
        focus_capture_id=raw["focus_capture_id"],
        geometry_capture_id=raw["geometry_capture_id"],
    )
    anchor = {"scenario_id": SCENARIO, "scenario_run_id": RUN_ID, "step_index": 0}

    def capture_initial(*, client, dev, row):
        assert dev == "serial"
        row.update(
            scenario_id=SCENARIO, scenario_run_id=RUN_ID,
            capture_id=raw["capture_id"], timestamp=raw["timestamp"],
            state_graph_observation=deepcopy(raw),
            production_observation_envelope=deepcopy(envelope),
            _exploration_observation=deepcopy(raw["_exploration_observation"]),
            dump_tree_nodes=deepcopy(raw["nodes"]),
        )
        return raw

    monkeypatch.setattr(collection_flow, "_capture_phase6d3a_production_observation", capture_initial)
    monkeypatch.setattr(
        collection_flow, "_collect_step_candidate_priority_groups",
        lambda *_args, **_kwargs: ([], [], {}),
    )
    runtime = FrontierShadowRuntime(
        run_id=RUN_ID, scenario_id=SCENARIO, evidence_clock=_Clock(),
    )
    client = SimpleNamespace(_phase6c2_frontier_shadow_runtime=runtime)
    state = SimpleNamespace(previous_step_row=anchor)

    seeded = collection_flow._seed_initial_frontier_shadow_observation(
        client=client, dev="serial", state=state,
        tab_cfg={"scenario_id": SCENARIO}, scenario_run_id=RUN_ID,
    )
    assert seeded is True

    decision = collection_flow._frontier_shadow_pre_decision(
        client=client, state=state, step_idx=1,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content"},
    )
    assert decision in runtime._pending
    assert runtime._pending[decision]["pre_cursor"]["confirmed"] is True
    assert runtime._latest_inventory["observation_ref"]["source_step"] == 0
    assert runtime._latest_inventory["observation_ref"]["production_capture_id"] == raw["capture_id"]


def test_main_loop_invokes_initial_capture_seed_only_for_first_shadow_step(monkeypatch, tmp_path):
    from tb_runner.exploration_shadow import ExplorationShadowRuntime

    monkeypatch.setenv("TB_STATE_GRAPH_MODE", "SHADOW")
    monkeypatch.setenv("TB_EXPLORATION_REDIRECT_MODE", "OFF")
    monkeypatch.setattr(
        FrontierShadowRuntime, "for_run",
        classmethod(lambda cls, **_kwargs: cls(run_id=RUN_ID, scenario_id=SCENARIO)),
    )
    monkeypatch.setattr(
        ExplorationShadowRuntime, "for_run",
        classmethod(lambda cls, **_kwargs: cls(run_id=RUN_ID, scenario_id=SCENARIO)),
    )
    monkeypatch.setattr(collection_flow, "_phase6d3a_reset_run_state", lambda **_kwargs: None)
    monkeypatch.setattr(collection_flow, "_phase6d3a_initialize_redirect_context", lambda **_kwargs: {})
    seeded = []
    monkeypatch.setattr(
        collection_flow, "_seed_initial_frontier_shadow_observation",
        lambda **kwargs: seeded.append(kwargs) or True,
    )
    state = SimpleNamespace(previous_step_row={"step_index": 0})
    phase_ctx = SimpleNamespace(
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content",
                 "tab_name": "Devices", "max_steps": 0},
        rows=[], all_rows=[], scenario_perf=None, state=state,
        start_step_index=1, output_path=str(tmp_path),
    )

    collection_flow._main_loop_phase(SimpleNamespace(), "serial", phase_ctx)

    assert len(seeded) == 1
    assert seeded[0]["state"] is state
    assert seeded[0]["scenario_run_id"]


def test_generic_request_id_reaches_inventory_decision_audit_and_history(monkeypatch):
    target = {
        "packageName": PACKAGE,
        "viewIdResourceName": f"{PACKAGE}:id/target",
        "text": "Target",
        "className": "android.widget.Button",
        "boundsInScreen": "[10,700][200,780]",
        "accessibilityFocused": True,
        "focused": False,
        "focusable": True,
        "visibleToUser": True,
        "enabled": True,
    }
    request_id = "helper-generic-target-request"
    client_for_target = SimpleNamespace(
        target_focus_commit=lambda **_kwargs: {
            "success": True, "status": "TARGET_MATCHED", "reqId": request_id,
        },
        get_focus=lambda **_kwargs: deepcopy(target),
    )
    row = {
        "scenario_id": SCENARIO,
        "step_index": 3,
        "focus_view_id": "old-focus",
        "focus_bounds": "[300,10][400,110]",
        "visible_label": "Old focus",
        "smart_nav_req_id": "prior-smart-next-request",
    }
    result = focus_realign_logic._maybe_realign_focus_to_representative_impl(
        client=client_for_target, dev="serial", row=row, selected_node=target,
        selected_rid=target["viewIdResourceName"], selected_label="Target",
        selected_bounds=target["boundsInScreen"], scenario_id=SCENARIO,
        step_idx=3, mismatch_logged=True, force_reason="anchor_mismatch",
        scenario_perf=None,
        focus_matches_fn=focus_realign_logic._target_focus_matches,
        extract_label_fn=lambda node: node.get("text", ""),
        label_blob_fn=lambda node: node.get("talkbackLabel", ""),
        truncate_fn=lambda value, _limit: str(value),
        log_fn=lambda _message: None,
    )

    assert result[0] is True
    assert row["target_focus_request_id"] == request_id
    assert row["target_focus_attempt_id"] != request_id
    assert row["phase6_current_action_type"] == "TARGETED_FOCUS"

    raw = _production_raw(focused="target")
    row.update({
        "scenario_run_id": RUN_ID,
        "capture_id": raw["capture_id"],
        "state_graph_observation": deepcopy(raw),
        "production_observation_envelope": deepcopy(raw["production_observation_envelope"]),
        "_exploration_observation": deepcopy(raw["_exploration_observation"]),
        "dump_tree_nodes": deepcopy(raw["nodes"]),
        "target_focus_attempted": True,
        "target_focus_fallback_used": False,
        "actual_focus_node": deepcopy(target),
        "actual_focus_accessibility_focused": True,
        "actual_focus_resource_id": target["viewIdResourceName"],
        "actual_focus_bounds": target["boundsInScreen"],
        "actual_focus_visible": "Target",
        "actual_focus_class_name": target["className"],
        "actual_focus_instance_id": instance_id({
            "scenario_id": SCENARIO,
            "view_id": target["viewIdResourceName"],
            "bounds": target["boundsInScreen"],
        }),
        "focus_transition_status": "CONFIRMED_MOVED",
        "visit_record_status": "UNVISITED_NOT_CREDITED",
    })
    runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        runtime, row=row,
        candidates=[{"node": target, "view_id": target["viewIdResourceName"],
                     "bounds": target["boundsInScreen"],
                     "class_name": target["className"], "label": "Target"}],
        scenario_id=SCENARIO, raw_nodes=raw["nodes"], projection_complete=True,
    )
    assert runtime._latest_inventory["observation_ref"]["request_id"] == request_id

    decision_sink = _DecisionSink()
    client = SimpleNamespace(
        _phase6c2_frontier_shadow_runtime=runtime,
        _phase6d_exploration_shadow_runtime=decision_sink,
    )
    monkeypatch.setattr(collection_flow, "clock_for", lambda _client: _Clock())
    token = collection_flow._prepare_phase6d_exploration_decision(
        client=client, row=row, step_idx=3,
        tab_cfg={"scenario_id": SCENARIO, "scenario_type": "content", "max_steps": 32},
        stop_candidate=False, stop_reason="", stop_eval_inputs={},
        pre_decision_ref=None,
    )
    assert token == "phase6-decision-token"
    assert decision_sink.kwargs["frontier_evaluation"]["source_request_id"] == request_id

    decision_id = runtime.pre_decision(
        step=4, production_choice={"action_type": "TARGETED_FOCUS"},
        state_id=runtime._latest_inventory["state_id"],
        inventory_complete=runtime._latest_inventory["inventory_complete"],
        focus_cursor=collection_flow._phase6d_snapshot_focus_cursor(row, raw),
    )
    assert decision_id
    collection_flow._frontier_shadow_post_result(
        client=client, decision_id=decision_id, step_idx=4,
        previous_row=None, row=row,
    )

    audit = runtime.evaluations[-1]["action_result"]
    history = runtime.history["attempt_events"]
    assert audit["result_id"] == request_id
    assert audit["request_id"] == request_id
    assert audit["attempt_id"] == row["target_focus_attempt_id"]
    assert len(history) == 1
    assert history[0]["request_id"] == request_id
    assert history[0]["attempt_id"] == row["target_focus_attempt_id"]

def test_generic_target_failure_does_not_borrow_prior_smart_next_request(monkeypatch):
    target = {
        "viewIdResourceName": f"{PACKAGE}:id/target",
        "text": "Target", "className": "android.widget.Button",
        "boundsInScreen": "[10,700][200,780]", "accessibilityFocused": False,
        "focused": False, "focusable": True, "visibleToUser": True,
    }
    previous_focus = {
        "viewIdResourceName": f"{PACKAGE}:id/more", "text": "More options",
        "className": "android.widget.Button", "boundsInScreen": "[912,126][1032,270]",
        "accessibilityFocused": True, "focused": False,
    }
    prior_request_id = "prior-smart-next-request"
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
        "phase6_current_action_type": "SMART_NEXT",
        "smart_nav_req_id": prior_request_id,
    }
    result = focus_realign_logic._maybe_realign_focus_to_representative_impl(
        client=client_for_target, dev="serial", row=row, selected_node=target,
        selected_rid=target["viewIdResourceName"], selected_label="Target",
        selected_bounds=target["boundsInScreen"], scenario_id=SCENARIO, step_idx=3,
        mismatch_logged=True, force_reason="anchor_mismatch", scenario_perf=None,
        focus_matches_fn=focus_realign_logic._target_focus_matches,
        extract_label_fn=lambda node: node.get("text", ""),
        label_blob_fn=lambda node: node.get("talkbackLabel", ""),
        truncate_fn=lambda value, _limit: str(value), log_fn=lambda _message: None,
    )

    assert result[:2] == (False, "ERROR")
    assert row["target_focus_attempted"] is True
    assert row["target_focus_attempt_id"] != prior_request_id
    assert row["target_focus_request_id"] == ""
    assert row["phase6_current_action_type"] == "TARGETED_FOCUS"
    from tb_runner.frontier_shadow import canonical_action_request_id
    assert canonical_action_request_id(row) == ""

    raw = _production_raw(request_id="current-observation-capture-request")
    assert raw["hierarchy_request_id"] != prior_request_id
    assert raw["capture_id"] != prior_request_id
    target_node = next(
        node for node in raw["nodes"]
        if node["viewIdResourceName"] == target["viewIdResourceName"]
    )
    row.update({
        "scenario_run_id": RUN_ID,
        "capture_id": raw["capture_id"],
        "timestamp": raw["timestamp"],
        "state_graph_observation": deepcopy(raw),
        "production_observation_envelope": deepcopy(raw["production_observation_envelope"]),
        "_exploration_observation": deepcopy(raw["_exploration_observation"]),
        "dump_tree_nodes": deepcopy(raw["nodes"]),
        "actual_focus_node": deepcopy(previous_focus),
        "actual_focus_accessibility_focused": True,
        "actual_focus_resource_id": previous_focus["viewIdResourceName"],
        "actual_focus_bounds": previous_focus["boundsInScreen"],
        "actual_focus_visible": previous_focus["text"],
        "actual_focus_class_name": previous_focus["className"],
        "actual_focus_instance_id": instance_id({
            "scenario_id": SCENARIO,
            "view_id": previous_focus["viewIdResourceName"],
            "bounds": previous_focus["boundsInScreen"],
        }),
        "focus_transition_status": "CONFIRMED_UNCHANGED",
        "visit_record_status": "NOT_RECORDED_UNCHANGED",
        "reconciled_visit_instance_id": "",
        "command_ack_status": "ERROR",
    })
    runtime = FrontierShadowRuntime(run_id=RUN_ID, scenario_id=SCENARIO)
    capture_reconciled_inventory(
        runtime, row=row,
        candidates=[{"node": target_node, "view_id": target_node["viewIdResourceName"],
                     "bounds": target_node["boundsInScreen"],
                     "class_name": target_node["className"], "label": target_node["text"]}],
        scenario_id=SCENARIO, raw_nodes=raw["nodes"], projection_complete=True,
    )
    inventory_ref = runtime._latest_inventory["observation_ref"]
    assert inventory_ref["production_capture_id"] == raw["capture_id"]
    assert inventory_ref["production_capture_id"] != prior_request_id
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
    assert runtime.history["visit_events"] == []
    assert runtime.history["complete"] is False
