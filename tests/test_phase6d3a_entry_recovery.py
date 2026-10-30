from copy import deepcopy
from dataclasses import replace
from types import MappingProxyType, MethodType, SimpleNamespace

import pytest

from tb_runner import collection_flow
from tb_runner.scenario_config import TAB_CONFIGS
from talkback_lib import A11yAdbClient, TraversalCandidateSnapshot
from talkback_lib.hierarchy_identity import attach_hierarchy_identity_metadata
from talkback_lib.reliable_hierarchy_schema import (
    ReliableHierarchyPayload,
    TraversalCandidateProjection,
    decode_reliable_hierarchy_payload,
    legacy_dump_tree_response,
)
from tests.test_reliable_hierarchy_schema import _candidate, _capabilities, _payload, _transport_metadata
from phase6d_capture_support import bind_reliable_capture_envelope


SMARTTHINGS = "com.samsung.android.oneconnect"


def _device_config(scenario_id):
    matches = [cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == scenario_id]
    assert len(matches) == 1
    return deepcopy(matches[0])


def _global_nav_nodes(selected="Devices"):
    return [
        {
            "viewIdResourceName": f"{SMARTTHINGS}:id/{resource_id}",
            "contentDescription": f"{label} selected" if label == selected else label,
            "selected": label == selected,
            "visibleToUser": True,
        }
        for resource_id, label in (
            ("menu_favorites", "Home"),
            ("menu_devices", "Devices"),
            ("menu_services", "Life"),
            ("menu_automations", "Routines"),
            ("menu_more", "Menu"),
        )
    ]


def _plugin_detail_nodes(label="Navigate up"):
    return [
        {
            "className": "android.widget.Button",
            "viewIdResourceName": "back",
            "text": label,
            "clickable": True,
            "focusable": True,
            "visibleToUser": True,
        }
    ]


def _production_shaped_plugin_candidates():
    candidates = _plugin_detail_nodes("상위 메뉴로 이동")
    candidates.extend(
        {
            "className": "android.widget.Button",
            "viewIdResourceName": f"device_action_{index}",
            "contentDescription": f"Sensor action {index}",
            "clickable": True,
            "focusable": True,
            "visibleToUser": True,
        }
        for index in range(9)
    )
    return candidates


class RecoveryClient:
    def __init__(self, states=(), *, foreground_package=SMARTTHINGS, snapshot_screen_package=None):
        self.dump_tree_sequence = list(states)
        self.foreground_package = foreground_package
        self.snapshot_screen_package = (
            foreground_package if snapshot_screen_package is None else snapshot_screen_package
        )
        self.last_dump = self.dump_tree_sequence[-1] if self.dump_tree_sequence else []
        self.back_calls = 0
        self.select_calls = []
        self.reset_focus_history_calls = 0
        self.last_device_tab_context_verified = False
        self.last_hierarchy_metadata = {}
        self.capture_index = 0

    def dump_tree(self, **_kwargs):
        if self.dump_tree_sequence:
            self.last_dump = self.dump_tree_sequence.pop(0)
        return self.last_dump

    def get_traversal_candidate_snapshot(self, **_kwargs):
        if self.dump_tree_sequence:
            candidates = self.dump_tree_sequence.pop(0)
            self.last_dump = candidates
        else:
            candidates = self.last_dump
        self.capture_index += 1
        request_id = f"request-{self.capture_index}"
        capture_id = f"{request_id}:1:capture-{self.capture_index}"
        return _candidate_snapshot(
            candidates,
            request_id=request_id,
            capture_id=capture_id,
            screen_package=self.snapshot_screen_package,
            metadata_sink=self,
        )

    def _run(self, args, **_kwargs):
        if args[:3] == ["shell", "dumpsys", "window"]:
            if not self.foreground_package:
                return ""
            return (
                "mCurrentFocus=Window{123 u0 "
                f"{self.foreground_package}/.MainActivity}}"
            )
        if args[:4] == ["shell", "dumpsys", "activity", "activities"]:
            return ""
        if args == ["shell", "input", "keyevent", "4"]:
            self.back_calls += 1
        return ""

    def reset_focus_history(self, _dev):
        self.reset_focus_history_calls += 1


class RealDecoderSnapshotClient:
    """Use the production decoder and snapshot API with an offline payload."""

    def __init__(self):
        self.payload = _payload(
            candidates=[
                _candidate(
                    text="상위 메뉴로 이동",
                    description="상위 메뉴로 이동",
                    resource_id="back",
                )
            ]
        )
        self.capture_sequence = 0
        self.last_hierarchy_metadata = {}
        self.snapshot_override = None
        self.snapshot_transform = None
        self.identity_mutator = None
        self.metadata_mutator = None
        self.snapshots = []
        self._run = lambda *_args, **_kwargs: (
            "mCurrentFocus=Window{123 u0 "
            f"{SMARTTHINGS}/.MainActivity}}"
        )
        self.get_traversal_candidate_snapshot = MethodType(
            RealDecoderSnapshotClient._get_traversal_candidate_snapshot,
            self,
        )

    def dump_hierarchy_decoded(self, **_kwargs):
        self.capture_sequence += 1
        capture_id = f"request-123:{self.capture_sequence}:capture-{self.capture_sequence}"
        payload = attach_hierarchy_identity_metadata(
            deepcopy(self.payload),
            capture_id=capture_id,
            capture_sequence=self.capture_sequence,
        )
        payload, transfer = bind_reliable_capture_envelope(
            payload, request_id="request-123", process_epoch="epoch-1", generation=3,
            service_instance_id="service-1", capture_sequence=self.capture_sequence,
            client_nonce="nonce-1",
            helper_build_identity={"build_id": "a" * 64, "git_commit": "b" * 40},
        )
        if self.identity_mutator is not None:
            self.identity_mutator(payload["identityMetadata"]["snapshot"])
        decoded = decode_reliable_hierarchy_payload(
            payload, capabilities=_capabilities(), transport_metadata=transfer,
        )
        self._last_hierarchy_transport_metadata = transfer
        self._last_hierarchy_capabilities = _capabilities()
        self.last_hierarchy_metadata = {
            "reqId": decoded.request_id,
            "snapshotId": capture_id,
            "captureSequence": self.capture_sequence,
        }
        if self.metadata_mutator is not None:
            self.metadata_mutator(self.last_hierarchy_metadata)
        return decoded

    def _get_traversal_candidate_snapshot(self, **kwargs):
        snapshot = A11yAdbClient.get_traversal_candidate_snapshot(self, **kwargs)
        if self.snapshot_transform is not None:
            snapshot = self.snapshot_transform(snapshot)
        if self.snapshot_override is not None:
            snapshot = self.snapshot_override
        self.snapshots.append(snapshot)
        return snapshot


def _verified_devices_tab(**_kwargs):
    return {
        "ok": True,
        "selected": True,
        "context": {
            "ok": True,
            "type": "selected_bottom_tab",
            "actual_selected_text": "Devices selected",
        },
    }


def _candidate_snapshot(
    candidates,
    *,
    request_id="request-current",
    capture_id="request-current:1:capture-current",
    screen_package=SMARTTHINGS,
    extra_windows=(),
    response_candidates=None,
    decoded_request_id=None,
    metadata_sink=None,
):
    legacy_fields = (
        "text", "contentDescription", "className", "viewIdResourceName", "boundsInScreen",
        "clickable", "focusable", "isVisibleToUser", "focused", "accessibilityFocused",
        "isTopAppBar", "isBottomNavigationBar", "hasClickableDescendant", "hasFocusableDescendant",
        "effectiveClickable", "actionableDescendantResourceId", "actionableDescendantClassName",
        "actionableDescendantContentDescription",
    )
    bool_fields = (
        "clickable", "focusable", "isVisibleToUser", "focused", "accessibilityFocused",
        "isTopAppBar", "isBottomNavigationBar", "hasClickableDescendant", "hasFocusableDescendant",
        "effectiveClickable",
    )
    candidate_records = []
    for source in candidates:
        candidate = {
            "text": "",
            "contentDescription": "",
            "className": "",
            "viewIdResourceName": "",
            "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 100},
            **{key: False for key in bool_fields},
            "actionableDescendantResourceId": None,
            "actionableDescendantClassName": None,
            "actionableDescendantContentDescription": None,
        }
        candidate.update({key: source[key] for key in legacy_fields if key in source})
        # Raw hierarchy fixtures use Android's visibleToUser spelling while
        # the traversal projection contract uses isVisibleToUser.
        if "isVisibleToUser" not in source and "visibleToUser" in source:
            candidate["isVisibleToUser"] = bool(source["visibleToUser"])
        candidate_records.append(MappingProxyType(candidate))

    root = {
        "packageName": screen_package,
        "windowId": 1,
        "children": [
            {
                "packageName": str(candidate.get("packageName") or screen_package),
                "windowId": 1,
                "children": [],
                "text": str(candidate.get("text") or ""),
            }
            for candidate in candidates
        ],
    }
    windows = [{"id": 1, "active": True, "focused": True, "root": root}, *extra_windows]
    raw_request_id = decoded_request_id or request_id
    raw = {
        "success": True,
        "reqId": raw_request_id,
        "windows": windows,
        "nodes": [window["root"] for window in windows],
        "identityMetadata": {
            "snapshot": {
                "request_id": {"value": raw_request_id, "status": "PRESENT"},
                "snapshot_id": {"value": capture_id, "status": "PRESENT"},
                "capture_id": {"value": capture_id, "status": "PRESENT"},
                "capture_sequence": {
                    "value": int(capture_id.split(":", 2)[1]),
                    "status": "PRESENT",
                },
            }
        },
    }
    projection = TraversalCandidateProjection(
        schema_version="legacy-traversal-candidates.v1",
        contract_version="legacy-traversal-candidate-contract.v1",
        algorithm_version="2.76.3",
        analyzer_version="1.11.1",
        profile_id="oneconnect-traversal-policy",
        profile_version="1.0.0",
        completion_status="COMPLETE",
        complete=True,
        candidate_count=len(candidate_records),
        traversal_root_ref="windows[0].root",
        traversal_root_window_id=1,
        can_scroll_down=False,
        scroll_axis_contract="axis-v1",
        candidates=tuple(candidate_records),
    )
    decoded = ReliableHierarchyPayload(
        raw_hierarchy=raw,
        traversal_candidates=projection,
        schema_version="service-hierarchy-v2",
        request_id=request_id,
        platform_api_level=35,
        traversal_root_ref="windows[0].root",
        traversal_root_window_id=1,
        raw_node_count=1 + len(candidate_records),
        raw_completion_valid=True,
        scroll_metadata={},
        device_collection={},
        transport_metadata={},
        capability_verified=True,
    )
    response = legacy_dump_tree_response(decoded)
    if response_candidates is not None:
        response["nodes"] = response_candidates
    if metadata_sink is not None:
        metadata_sink.last_hierarchy_metadata = {
            "reqId": request_id,
            "snapshotId": capture_id,
            "captureSequence": int(capture_id.split(":", 2)[1]),
        }
    return TraversalCandidateSnapshot(response=response, raw_hierarchy=raw, decoded=decoded)


def test_valid_smartthings_root_skips_recovery(monkeypatch):
    client = RecoveryClient([_global_nav_nodes()])
    monkeypatch.setattr(
        collection_flow,
        "recover_to_start_state",
        lambda *_args: pytest.fail("valid root should not invoke recovery"),
    )

    ok, reason = collection_flow._prepare_device_card_plugin_start_state(
        client, "SERIAL", _device_config("device_air_purifier_plugin")
    )

    assert ok is True
    assert reason == "global_navigation_available"
    assert client.back_calls == 0


def test_real_producer_shaped_package_less_navigate_up_is_recoverable(monkeypatch):
    candidates = _production_shaped_plugin_candidates()
    assert len(candidates) == 10
    assert all(
        not any(key in candidate for key in ("packageName", "package_name", "package"))
        for candidate in candidates
    )
    # The start gate captures once, then recovery captures again before its
    # bounded Back dispatch. Keep the detail present for both observations.
    client = RecoveryClient(
        [
            candidates,
            _production_shaped_plugin_candidates(),
            _global_nav_nodes(),
            _global_nav_nodes(),
        ]
    )
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", _verified_devices_tab)

    ok, reason = collection_flow._prepare_device_card_plugin_start_state(
        client, "SERIAL", _device_config("device_air_purifier_plugin")
    )

    assert ok is True
    assert reason == "devices_root_verified"
    assert client.back_calls == 1


def test_package_less_candidate_is_accepted_with_same_capture_smartthings_authority():
    # Exercise the production classifier with a real shaped snapshot through the
    # same capture adapter, including package-less legacy candidates.
    client = RecoveryClient([_plugin_detail_nodes("상위 메뉴로 이동")])
    observation, reason = collection_flow._capture_device_plugin_start_observation(client, "SERIAL")

    assert reason == "current_snapshot_verified"
    assert observation["screen_package"] == SMARTTHINGS
    assert observation["capture_id"] == client.last_hierarchy_metadata["reqId"] + ":1:capture-1"
    assert collection_flow._is_known_smartthings_plugin_detail(
        observation["nodes"], screen_package=observation["screen_package"], capture_bound=True
    ) is True


def test_real_decoder_snapshot_chain_normalizes_representation_and_binds_recovery():
    client = RealDecoderSnapshotClient()
    first_snapshot = client.get_traversal_candidate_snapshot(dev="OFFLINE")

    assert first_snapshot.decoded.capability_verified is True
    assert type(first_snapshot.raw_hierarchy["windows"]) is list
    assert type(first_snapshot.decoded.raw_hierarchy["windows"]) is tuple
    assert first_snapshot.raw_hierarchy != first_snapshot.decoded.raw_hierarchy
    assert collection_flow._canonical_hierarchy_content(
        first_snapshot.raw_hierarchy
    ) == collection_flow._canonical_hierarchy_content(first_snapshot.decoded.raw_hierarchy)
    assert all(
        not any(key in candidate for key in ("packageName", "package_name", "package"))
        for candidate in first_snapshot.candidates
    )

    observation, reason = collection_flow._capture_device_plugin_start_observation(
        client, "OFFLINE"
    )

    assert reason == "current_snapshot_verified"
    assert observation is not None
    current_snapshot = client.snapshots[-1]
    assert observation["request_id"] == current_snapshot.decoded.request_id
    assert observation["capture_id"] == client.last_hierarchy_metadata["snapshotId"]
    assert observation["capture_id"] == current_snapshot.decoded.raw_hierarchy[
        "identityMetadata"
    ]["snapshot"]["capture_id"]
    assert collection_flow._is_known_smartthings_plugin_detail(
        observation["nodes"],
        screen_package=observation["screen_package"],
        capture_bound=True,
    ) is True


def test_real_snapshot_semantic_hierarchy_mismatch_fails_closed():
    client = RealDecoderSnapshotClient()

    def _change_content(snapshot):
        raw = deepcopy(snapshot.raw_hierarchy)
        raw["windows"][0]["root"]["packageName"] = "external.app"
        return replace(snapshot, raw_hierarchy=raw)

    client.snapshot_transform = _change_content
    observation, reason = collection_flow._capture_device_plugin_start_observation(
        client, "OFFLINE"
    )

    assert observation is None
    assert reason == "raw_hierarchy_capture_mismatch"


def test_real_snapshot_request_identity_mismatch_fails_closed():
    client = RealDecoderSnapshotClient()
    client.snapshot_transform = lambda snapshot: replace(
        snapshot,
        decoded=replace(snapshot.decoded, request_id="request-other"),
    )

    observation, reason = collection_flow._capture_device_plugin_start_observation(
        client, "OFFLINE"
    )

    assert observation is None
    assert reason == "hierarchy_request_id_mismatch"


def test_real_snapshot_capture_identity_mismatch_fails_closed():
    client = RealDecoderSnapshotClient()

    def _change_capture_metadata(metadata):
        metadata["captureSequence"] -= 1

    client.metadata_mutator = _change_capture_metadata
    observation, reason = collection_flow._capture_device_plugin_start_observation(
        client, "OFFLINE"
    )

    assert observation is None
    assert reason == "hierarchy_capture_identity_mismatch"


def test_stale_identical_content_snapshot_is_rejected_by_current_capture_metadata():
    client = RealDecoderSnapshotClient()
    stale_snapshot = client.get_traversal_candidate_snapshot(dev="OFFLINE")
    current_snapshot = client.get_traversal_candidate_snapshot(dev="OFFLINE")
    assert stale_snapshot.response["nodes"] == current_snapshot.response["nodes"]
    assert stale_snapshot.raw_hierarchy["windows"] == current_snapshot.raw_hierarchy["windows"]
    assert (
        stale_snapshot.raw_hierarchy["identityMetadata"]["snapshot"]["capture_id"]
        != current_snapshot.raw_hierarchy["identityMetadata"]["snapshot"]["capture_id"]
    )
    client.snapshot_override = stale_snapshot

    observation, reason = collection_flow._capture_device_plugin_start_observation(
        client, "OFFLINE"
    )

    assert observation is None
    assert reason == "hierarchy_capture_identity_mismatch"


def test_candidate_package_explicitly_smartthings_is_still_accepted():
    candidate = _plugin_detail_nodes("Navigate up")[0]
    candidate["packageName"] = SMARTTHINGS
    assert collection_flow._is_known_smartthings_plugin_detail(
        [candidate], screen_package=SMARTTHINGS, capture_bound=True
    ) is True


@pytest.mark.parametrize("screen_package", ["external.app", ""])
def test_package_less_navigate_up_is_blocked_for_external_or_unknown_screen(screen_package):
    client = RecoveryClient(
        [_plugin_detail_nodes("Navigate up")],
        foreground_package=SMARTTHINGS,
        snapshot_screen_package=screen_package,
    )

    observation, reason = collection_flow._capture_device_plugin_start_observation(client, "SERIAL")

    assert observation is None
    assert reason in {"external_app_contamination", "ambiguous_hierarchy_package_authority"}


def test_foreground_hierarchy_package_mismatch_fails_closed():
    client = RecoveryClient(
        [_plugin_detail_nodes("Navigate up")], snapshot_screen_package="external.app"
    )

    observation, reason = collection_flow._capture_device_plugin_start_observation(client, "SERIAL")

    assert observation is None
    assert reason == "external_app_contamination"


def test_stale_candidate_projection_mismatch_fails_closed():
    stale = _candidate_snapshot(_global_nav_nodes(), request_id="request-old")
    client = RecoveryClient([_plugin_detail_nodes("Navigate up")])
    client.get_traversal_candidate_snapshot = lambda **_kwargs: _candidate_snapshot(
        _plugin_detail_nodes("Navigate up"),
        request_id="request-current",
        capture_id="request-current:1:capture-current",
        response_candidates=stale.candidates,
        metadata_sink=client,
    )

    observation, reason = collection_flow._capture_device_plugin_start_observation(client, "SERIAL")

    assert observation is None
    assert reason == "candidate_projection_capture_mismatch"


def test_navigation_label_without_smartthings_context_is_not_accepted():
    nodes = _plugin_detail_nodes("Navigate up")

    assert collection_flow._is_known_smartthings_plugin_detail(
        nodes, screen_package="", capture_bound=True
    ) is False
    assert collection_flow._is_known_smartthings_plugin_detail(
        nodes, screen_package=SMARTTHINGS, capture_bound=False
    ) is False


def test_smoke_sensor_detail_recovers_through_shared_path_for_air_purifier(monkeypatch):
    detail = _plugin_detail_nodes()
    root = _global_nav_nodes()
    client = RecoveryClient([detail, detail, root, root])
    before_entry = deepcopy(_device_config("device_air_purifier_plugin")["pre_navigation"])
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", _verified_devices_tab)

    ok, reason = collection_flow._prepare_device_card_plugin_start_state(
        client, "SERIAL", _device_config("device_air_purifier_plugin")
    )

    assert ok is True
    assert reason == "devices_root_verified"
    assert client.back_calls == 1
    assert client.last_device_tab_context_verified is True
    assert _device_config("device_air_purifier_plugin")["pre_navigation"] == before_entry


def test_other_device_plugin_uses_same_detail_recovery_without_scenario_branch(monkeypatch):
    detail = _plugin_detail_nodes("상위 메뉴로 이동")
    root = _global_nav_nodes()
    client = RecoveryClient([detail, detail, root, root])
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", _verified_devices_tab)

    ok, reason = collection_flow._prepare_device_card_plugin_start_state(
        client, "SERIAL", _device_config("device_washer_plugin")
    )

    assert ok is True
    assert reason == "devices_root_verified"
    assert client.back_calls == 1


def test_external_foreground_fails_without_back_or_recovery(monkeypatch):
    client = RecoveryClient([_plugin_detail_nodes()], foreground_package="com.android.vending")
    monkeypatch.setattr(
        collection_flow,
        "recover_to_start_state",
        lambda *_args: pytest.fail("external app must never be navigated by recovery"),
    )

    ok, reason = collection_flow._prepare_device_card_plugin_start_state(
        client, "SERIAL", _device_config("device_air_purifier_plugin")
    )

    assert ok is False
    assert reason == "external_app_contamination"
    assert client.back_calls == 0


def test_unknown_smartthings_state_fails_closed_without_back(monkeypatch):
    client = RecoveryClient(
        [[{"packageName": SMARTTHINGS, "text": "Unknown screen", "visibleToUser": True}]]
    )
    monkeypatch.setattr(
        collection_flow,
        "recover_to_start_state",
        lambda *_args: pytest.fail("unknown SmartThings state must fail closed"),
    )

    ok, reason = collection_flow._prepare_device_card_plugin_start_state(
        client, "SERIAL", _device_config("device_air_purifier_plugin")
    )

    assert ok is False
    assert reason == "unknown_smartthings_start_state"
    assert client.back_calls == 0


def test_focused_external_popup_blocks_detail_recovery(monkeypatch):
    detail = _plugin_detail_nodes()
    detail.append(
        {
            "packageName": "com.android.vending",
            "className": "android.widget.Button",
            "text": "Continue",
            "accessibilityFocused": True,
            "visibleToUser": True,
        }
    )
    client = RecoveryClient([detail])
    monkeypatch.setattr(
        collection_flow,
        "recover_to_start_state",
        lambda *_args: pytest.fail("popup contamination must stop before recovery"),
    )

    ok, reason = collection_flow._prepare_device_card_plugin_start_state(
        client, "SERIAL", _device_config("device_air_purifier_plugin")
    )

    assert ok is False
    assert reason in {
        "external_popup_contamination",
        "ambiguous_hierarchy_package_authority",
        "mismatched_current_window_package",
    }
    assert client.back_calls == 0


def test_device_recovery_back_budget_is_enforced(monkeypatch):
    client = RecoveryClient([_plugin_detail_nodes()] * 4)
    log_lines = []
    monkeypatch.setattr(collection_flow, "log", log_lines.append)

    ok, reason = collection_flow.recover_to_device_start_state(
        client,
        "SERIAL",
        {"scenario_id": "device_air_purifier_plugin", "recovery": {"max_back_count": 2}},
    )

    assert ok is False
    assert reason == "global_nav_not_visible"
    assert client.back_calls == 2
    back_diagnostics = [line for line in log_lines if "[DEVICE_RESET][back_action]" in line]
    assert len(back_diagnostics) == 2
    assert all("recovery_target='devices_tab'" in line for line in back_diagnostics)
    assert all("action_type='INPUT_BACK'" in line for line in back_diagnostics)
    assert all("runner_call_result='RETURNED'" in line for line in back_diagnostics)
    assert all("operation_id='UNKNOWN'" in line for line in back_diagnostics)
    assert all("native_receipt_status='UNAVAILABLE'" in line for line in back_diagnostics)


def test_device_reset_capture_transport_failure_records_stage_and_ids(monkeypatch):
    client = RecoveryClient([_plugin_detail_nodes()] * 2)
    original_capture = client.get_traversal_candidate_snapshot
    calls = 0
    transport_error = RuntimeError("transport details intentionally not logged")
    transport_error.reason = "END_TO_END_TIMEOUT"
    transport_error.request_id = "request-after-back"

    def capture_with_failure(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_capture(**kwargs)
        raise transport_error

    client.get_traversal_candidate_snapshot = capture_with_failure
    log_lines = []
    monkeypatch.setattr(collection_flow, "log", log_lines.append)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)

    ok, reason = collection_flow.recover_to_device_start_state(
        client,
        "SERIAL",
        {"scenario_id": "device_air_purifier_plugin", "recovery": {"max_back_count": 2}},
    )

    assert ok is False
    assert reason == "hierarchy_unavailable"
    assert calls == 2
    assert client.back_calls == 1
    joined_logs = "\n".join(log_lines)
    assert "observed stage='device_reset.gate_attempt_1'" in joined_logs
    assert "request_id='request-1'" in joined_logs
    assert "capture_id='request-1:1:capture-1'" in joined_logs
    assert "response_status='CAPTURED_COMPLETE'" in joined_logs
    assert "recovery_target='devices_tab' action_type='INPUT_BACK'" in joined_logs
    assert "runner_call_result='RETURNED'" in joined_logs
    assert "native_receipt_status='UNAVAILABLE'" in joined_logs
    assert "failed stage='device_reset.gate_attempt_2'" in joined_logs
    assert "transport_reason='END_TO_END_TIMEOUT'" in joined_logs
    assert "request_id='request-after-back'" in joined_logs
    assert "capture_id='UNKNOWN' response_status='UNKNOWN'" in joined_logs


@pytest.mark.parametrize("scenario_id", ["device_air_purifier_plugin", "device_smoke_sensor_plugin"])
def test_open_scenario_enters_only_after_start_state_gate(monkeypatch, scenario_id):
    cfg = _device_config(scenario_id)
    original_entry = deepcopy(cfg["pre_navigation"])
    client = RecoveryClient()
    order = []

    def _verified_start_state(*_args):
        order.append("verified_start_state")
        client.last_device_tab_context_verified = True
        summary = getattr(client, "last_start_open_summary", {})
        summary["start_state_verified"] = True
        client.last_start_open_summary = summary
        return True, "devices_root_verified"

    def _stabilize(**_kwargs):
        order.append("tab_stabilization")
        return {
            "ok": True,
            "selected": True,
            "context": {"ok": True, "type": "selected_bottom_tab"},
            "focus_align": {"attempted": False, "ok": False},
        }

    def _entry(*_args, tab_cfg, **_kwargs):
        assert client.last_start_open_summary["start_state_verified"] is True
        assert tab_cfg["pre_navigation"] == original_entry
        order.append("existing_card_entry")
        return False

    monkeypatch.setattr(collection_flow, "_prepare_device_card_plugin_start_state", _verified_start_state)
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", _stabilize)
    monkeypatch.setattr(collection_flow, "_run_pre_navigation_steps", _entry)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)

    assert collection_flow.open_scenario(client, "SERIAL", cfg) is False
    assert order == ["verified_start_state", "tab_stabilization", "existing_card_entry"]
    assert cfg["pre_navigation"] == original_entry


def test_failed_start_state_gate_prevents_scenario_entry(monkeypatch):
    cfg = _device_config("device_air_purifier_plugin")
    client = RecoveryClient()
    monkeypatch.setattr(
        collection_flow,
        "_prepare_device_card_plugin_start_state",
        lambda *_args: (False, "unknown_smartthings_start_state"),
    )
    monkeypatch.setattr(
        collection_flow,
        "stabilize_tab_selection",
        lambda **_kwargs: pytest.fail("tab/entry work must not continue after recovery failure"),
    )
    monkeypatch.setattr(
        collection_flow,
        "_run_pre_navigation_steps",
        lambda **_kwargs: pytest.fail("target card entry must not run after recovery failure"),
    )

    assert collection_flow.open_scenario(client, "SERIAL", cfg) is False
    assert client.last_start_open_summary["entry_contract_detail"] == (
        "START_STATE_RECOVERY_FAILED:unknown_smartthings_start_state"
    )


def test_navigation_recovery_does_not_mutate_active_or_traversal_budgets(monkeypatch):
    from tb_runner.exploration_redirect import ExplorationRedirectController

    detail, root = _plugin_detail_nodes(), _global_nav_nodes()
    client = RecoveryClient([detail, detail, root, root])
    controller = ExplorationRedirectController(mode="ACTIVE", graph_mode="SHADOW")
    client._phase6d3a_redirect_controller = controller
    client._phase6d3a_controlled_budget = SimpleNamespace(actions=2, max_actions=5)
    client._active_traversal_metrics = SimpleNamespace(attempted_steps=7, unique_visits=4)
    before_events = list(controller.events)
    before_counters = dict(controller.metrics.counters)
    before_budget = (
        controller.budget.redirects_used,
        dict(controller.budget.state_counts),
        dict(controller.budget.condition_counts),
    )
    controlled_budget = client._phase6d3a_controlled_budget
    traversal_metrics = client._active_traversal_metrics
    monkeypatch.setattr(collection_flow, "stabilize_tab_selection", _verified_devices_tab)

    ok, _ = collection_flow._prepare_device_card_plugin_start_state(
        client, "SERIAL", _device_config("device_air_purifier_plugin")
    )

    assert ok is True
    assert controller.events == before_events
    assert dict(controller.metrics.counters) == before_counters
    assert (
        controller.budget.redirects_used,
        dict(controller.budget.state_counts),
        dict(controller.budget.condition_counts),
    ) == before_budget
    assert client._phase6d3a_controlled_budget is controlled_budget
    assert client._phase6d3a_controlled_budget.actions == 2
    assert client._active_traversal_metrics is traversal_metrics
    assert client._active_traversal_metrics.attempted_steps == 7
    assert client._active_traversal_metrics.unique_visits == 4
