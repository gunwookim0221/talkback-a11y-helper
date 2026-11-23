from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

from phase6d_capture_support import attach_capture_authority
from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
from tb_runner import collection_flow


def _sealed_snapshot_fixture():
    raw = attach_capture_authority(
        {
            "nodes": [
                {
                    "className": "android.widget.TextView",
                    "text": "Air Care",
                    "contentDescription": None,
                    "viewIdResourceName": "com.samsung.android.oneconnect:id/name",
                    "boundsInScreen": {"l": 1, "t": 2, "r": 3, "b": 4},
                    "clickable": False,
                    "accessibilityFocused": False,
                    "children": [],
                }
            ],
            "package_name": "com.samsung.android.oneconnect",
            "traversal_root_class_name": "android.widget.FrameLayout",
        },
        request_id="independent-helper-request",
        sequence=9,
        generation=8,
        window_id=26,
    )
    authority = validate_capture_authority(raw["capture_authority"])
    assert authority is not None
    decoded = SimpleNamespace(request_id=authority.request_id, capture_authority=authority)
    return raw, authority, SimpleNamespace(raw_hierarchy=raw, decoded=decoded)


class _ReadOnlyObserverClient:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail
        self.raw, self.authority, self.snapshot = _sealed_snapshot_fixture()
        self.last_hierarchy_metadata = {
            "captureAuthority": self.authority.to_dict(),
            "helperServiceInstanceId": self.authority.service_instance_id,
            "helperProcessEpoch": self.authority.process_epoch,
            "captureGeneration": self.authority.generation,
            "captureSequence": self.authority.capture_sequence,
            "snapshotId": self.authority.capture_key,
            "helperConnectionEpoch": "connection-current",
            "bootEpoch": "boot-current",
        }

    def _run(self, command, *, dev, timeout):
        self.calls.append((list(command), dev, timeout))
        if self.fail:
            raise TimeoutError("fixture timeout")
        if command[1:3] == ["dumpsys", "activity"]:
            return "topResumedActivity=ActivityRecord{pkg/.AirCareActivity}"
        if command[1:3] == ["dumpsys", "window"]:
            return "mCurrentFocus=Window{26 pkg/.AirCareActivity}"
        if command[1:3] == ["uiautomator", "dump"]:
            return f"UI hierarchy dumped to: {command[3]}"
        if command[1] == "cat":
            return '<hierarchy><node class="android.widget.TextView" text="Air Care"/></hierarchy>'
        raise AssertionError(f"unexpected read-only command: {command}")

    def get_traversal_candidate_snapshot(self, *, dev, wait_seconds):
        self.calls.append(("sealed_snapshot", dev, wait_seconds))
        if self.fail:
            raise TimeoutError("fixture snapshot timeout")
        return self.snapshot


def test_navigation_bridge_request_id_accepts_both_canonical_result_keys():
    assert collection_flow._navigation_action_request_id({"reqId": "req-camel"}) == "req-camel"
    assert collection_flow._navigation_action_request_id({"request_id": "req-snake"}) == "req-snake"
    assert collection_flow._navigation_action_request_id({"reqId": "", "request_id": "req-fallback"}) == "req-fallback"
    assert collection_flow._navigation_action_request_id({"reqId": "", "request_id": ""}) == ""


def test_independent_post_action_observations_are_secondary_and_keep_separate_identities(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    client = _ReadOnlyObserverClient()
    strict_result = {
        "success": False,
        "status": "protocol_error",
        "reason": "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
        "reqId": "navigation-request",
        "receipt_status": "REJECTED",
        "receipt_failure_code": "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
        "post_state_mismatch_fields": ["accessibility_focus_missing"],
        "receipt": {
            "verified_navigation": False,
            "activation_diagnostics": {
                "activation_mode": "EXACT_OWNER_FOCUS_THEN_CLICK",
                "focus_event_status": "FOCUSED_HIERARCHY_REVALIDATION_FAILED",
                "focus_revalidation": {
                    "prepared_deadline_valid": True,
                    "service_identity_matches": True,
                    "connection_identity_matches": True,
                    "window_identity_matches": True,
                    "focus_event_owner_matches": True,
                    "aggregate_accepted": False,
                    "target_currentness": {
                        "diagnostics_available": True,
                        "capture_lease_fresh": True,
                        "retained_node_accessibility_focused": True,
                        "focus_neutral_descriptor_matches": True,
                        "focus_neutral_hierarchy_digest_matches": False,
                        "capture_complete": True,
                        "capture_lease_age_ms": 104,
                        "first_failed_check": "focus_neutral_hierarchy_digest_matches",
                        "expected_focus_neutral_hierarchy_digest": "a" * 64,
                        "current_focus_neutral_hierarchy_digest": "b" * 64,
                        "focus_neutral_descriptor_mismatch_fields": [
                            "boundsInScreen", "text", "private_node_text",
                        ],
                        "focus_neutral_action_ids_added": [128, 64, True, "16", 0, -1, 2_147_483_648],
                        "focus_neutral_action_ids_removed": [64, 16],
                        "focus_neutral_action_id_delta_complete": True,
                        "private_node_text": "must not be persisted",
                    },
                    "private_node_text": "must not be persisted",
                },
            },
        },
    }
    strict_before = deepcopy(strict_result)
    action_context = {
        "request_id": "navigation-request",
        "transaction_id": "tx-independent",
        "service_instance_id": "service-before",
        "connection_id": "connection-before",
        "window_id": 26,
        "source_capture_key": "capture-key-before",
        "source_generation": 17,
        "source_capture_sequence": 9,
    }

    diagnostic = collection_flow._capture_navigation_independent_observations(
        client,
        "serial-1",
        request_id="navigation-request",
        transaction_id="tx-independent",
        navigation_action_result=strict_result,
        action_context=action_context,
        action_result_received_monotonic_ns=1,
    )

    assert strict_result == strict_before
    assert diagnostic["evidence_role"] == "SECONDARY_ONLY"
    assert diagnostic["action_request_id"] == "navigation-request"
    assert diagnostic["transaction_id"] == "tx-independent"
    assert diagnostic["strict_navigation_result"] == {
        "success": False,
        "status": "protocol_error",
        "reason": "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
        "reqId": "navigation-request",
        "receipt_status": "REJECTED",
        "receipt_failure_code": "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
        "post_state_mismatch_fields": ["accessibility_focus_missing"],
        "activation_diagnostics": {
            "activation_mode": "EXACT_OWNER_FOCUS_THEN_CLICK",
            "focus_event_status": "FOCUSED_HIERARCHY_REVALIDATION_FAILED",
            "focus_revalidation": {
                "prepared_deadline_valid": True,
                "service_identity_matches": True,
                "connection_identity_matches": True,
                "window_identity_matches": True,
                "focus_event_owner_matches": True,
                "aggregate_accepted": False,
                "target_currentness": {
                    "diagnostics_available": True,
                    "capture_lease_fresh": True,
                    "retained_node_accessibility_focused": True,
                    "focus_neutral_descriptor_matches": True,
                    "focus_neutral_hierarchy_digest_matches": False,
                    "capture_complete": True,
                    "capture_lease_age_ms": 104,
                    "first_failed_check": "focus_neutral_hierarchy_digest_matches",
                    "expected_focus_neutral_hierarchy_digest": "a" * 64,
                    "current_focus_neutral_hierarchy_digest": "b" * 64,
                    "focus_neutral_descriptor_mismatch_fields": ["boundsInScreen", "text"],
                    "focus_neutral_action_ids_added": [0, 64, 128],
                    "focus_neutral_action_ids_removed": [16, 64],
                    "focus_neutral_action_id_delta_complete": False,
                },
            },
        },
    }
    assert "private_node_text" not in json.dumps(diagnostic["strict_navigation_result"])
    oversized = collection_flow._navigation_action_evidence_projection({
        "receipt": {"activation_diagnostics": {"focus_revalidation": {"target_currentness": {
            "focus_neutral_action_ids_added": list(range(1, 70)),
            "focus_neutral_action_ids_removed": [],
            "focus_neutral_action_id_delta_complete": True,
        }}}},
    })["activation_diagnostics"]["focus_revalidation"]["target_currentness"]
    assert len(oversized["focus_neutral_action_ids_added"]) == \
        collection_flow._NAVIGATION_FOCUS_ACTION_ID_DIAGNOSTIC_LIMIT
    assert oversized["focus_neutral_action_ids_added"] == sorted(oversized["focus_neutral_action_ids_added"])
    assert oversized["focus_neutral_action_id_delta_complete"] is False
    assert {key: diagnostic["action_context"][key] for key in action_context} == action_context
    assert diagnostic["action_result_received_monotonic_ns"] == 1
    assert diagnostic["observer_call_started_monotonic_ns"] == diagnostic["started_monotonic_ns"]
    assert diagnostic["observer_call_completed_monotonic_ns"] == diagnostic["completed_monotonic_ns"]
    assert diagnostic["observer_delay_from_result_ns"] >= 0
    assert diagnostic["observer_status"] == "COMPLETE"
    assert diagnostic["observer_error_stages"] == []
    observations = diagnostic["observations"]
    assert observations["activity"]["foreground_lines"] == [
        "topResumedActivity=ActivityRecord{pkg/.AirCareActivity}"
    ]
    assert observations["window"]["foreground_lines"] == [
        "mCurrentFocus=Window{26 pkg/.AirCareActivity}"
    ]
    xml = observations["uiautomator_xml"]["read"]
    assert xml["node_count"] == 1
    assert Path(xml["local_path"]).read_text(encoding="utf-8").startswith("<hierarchy>")
    helper = observations["sealed_helper_hierarchy"]
    assert helper["status"] == "CAPTURED"
    assert helper["capture_authority_valid"] is True
    assert helper["metadata_authority_matches"] is True
    assert helper["request_id"] == "independent-helper-request"
    assert helper["capture_sequence"] == 9
    assert helper["window_id"] == 26
    assert helper["transport_identity_fields"]["helperConnectionEpoch"] == "connection-current"
    saved = json.loads(Path(helper["local_path"]).read_text(encoding="utf-8"))
    assert saved["capture_authority"]["capture_key"] == helper["capture_key"]
    assert hashlib.sha256(Path(helper["local_path"]).read_bytes()).hexdigest() == helper["saved_sha256"]

    timestamped = [
        observations["activity"], observations["window"],
        observations["uiautomator_xml"]["dump"], observations["uiautomator_xml"]["read"],
        helper,
    ]
    assert all(isinstance(row["started_monotonic_ns"], int) for row in timestamped)
    assert all(row["completed_monotonic_ns"] >= row["started_monotonic_ns"] for row in timestamped)
    commands = [call[0] for call in client.calls if isinstance(call[0], list)]
    assert commands[:2] == [
        ["shell", "dumpsys", "activity", "activities"],
        ["shell", "dumpsys", "window", "windows"],
    ]
    assert len(commands) == 4
    assert commands[2][:3] == ["shell", "uiautomator", "dump"]
    assert commands[3][:2] == ["shell", "cat"]
    assert not any(any(token in command for token in ("input", "tap", "broadcast")) for command in commands)


def test_independent_observer_failures_are_recorded_without_raising_or_changing_strict_result(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    client = _ReadOnlyObserverClient(fail=True)
    strict_result = {"success": False, "reason": "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE"}
    strict_before = deepcopy(strict_result)

    diagnostic = collection_flow._capture_navigation_independent_observations(
        client,
        "serial-1",
        request_id="navigation-request",
        transaction_id="tx-independent",
        navigation_action_result=strict_result,
    )

    assert strict_result == strict_before
    assert diagnostic["evidence_role"] == "SECONDARY_ONLY"
    assert diagnostic["observations"]["activity"]["error"] == "TimeoutError"
    assert diagnostic["observations"]["window"]["error"] == "TimeoutError"
    assert diagnostic["observations"]["uiautomator_xml"]["read"]["error"] == "TimeoutError"
    assert diagnostic["observations"]["sealed_helper_hierarchy"]["error"] == "TimeoutError"
    assert diagnostic["observer_status"] == "FAILED"
    assert diagnostic["observer_error_stages"] == [
        "activity", "window", "uiautomator_xml.dump", "uiautomator_xml.read", "sealed_helper_hierarchy"
    ]
    assert diagnostic["observer_timeout_stages"] == diagnostic["observer_error_stages"]
