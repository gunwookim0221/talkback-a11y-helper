from __future__ import annotations

import pytest

from tb_runner.phase5b_navigation import SafeNavigationSession, SafetyBlocked
from tb_runner.state_graph import EdgeLifecycle, _evidence_from_row, recorder_from_existing_rows
from talkback_lib import A11yAdbClient
from talkback_lib.hierarchy_file_transport import (
    CONTROL_SCHEMA, PAYLOAD_SCHEMA, PROVIDER_AUTHORITY, HierarchyTransportError, encode_control,
)
from talkback_lib.reliable_hierarchy_schema import (
    CANDIDATE_CONTRACT_VERSION, CANDIDATE_SCHEMA_VERSION, RAW_SCHEMA_VERSION,
)

from test_hierarchy_file_transport import _artifact_control, _identity


PACKAGE = "com.iotpart.sqe.talkbackhelper"


def _broadcast(operation: str, extras: list[str], *, package: str = PACKAGE) -> list[str]:
    return ["shell", "am", "broadcast", "-a", f"{PACKAGE}.HIERARCHY_TRANSFER_{operation}",
            "-p", package, *extras]


class _ReliableTransportBackend:
    def __init__(self, client: A11yAdbClient, *, fail_payload: bool = False,
                 ack_mode: str = "valid", cancel_mode: str = "valid"):
        self.client = client
        self.identity = _identity()
        self.request_id = ""
        self.client_nonce = ""
        self.artifact = b""
        self.ready = {}
        self.commands: list[list[str]] = []
        self.fail_payload = fail_payload
        self.ack_mode = ack_mode
        self.cancel_mode = cancel_mode
        self.process_epoch = "process-epoch-1"
        self.token = "e" * 32
        self.helper_identity = None
        self.payload = b""

    @staticmethod
    def _pairs(extras: list[str]) -> dict[str, str]:
        return {extras[index + 1]: extras[index + 2]
                for index in range(0, len(extras), 3) if extras[index] == "--es"}

    def command(self, args, *, dev=None, timeout=None, raise_on_failure=False):
        command = [str(value) for value in args]
        self.commands.append(command)
        if command[:3] == ["shell", "am", "broadcast"]:
            action = command[4]
            operation = action.rsplit("_", 1)[-1]
            pairs = self._pairs(command[7:])
            query_nonce = pairs["queryNonce"]
            if operation == "CAPABILITIES":
                response = {
                    "schema": CONTROL_SCHEMA,
                    "protocol_version": "hierarchy-payload.v1",
                    "status": "OK",
                    "query_nonce": query_nonce,
                    "generation": 0,
                    "process_epoch": self.process_epoch,
                    "service_instance_id": self.identity["service_instance_id"],
                    "helper_build_identity": {
                        key: value for key, value in self.identity.items()
                        if key != "service_instance_id"
                    },
                    "payload_schema_version": RAW_SCHEMA_VERSION,
                    "supported_payload_schema_versions": [RAW_SCHEMA_VERSION],
                    "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
                    "supported_candidate_schema_versions": [CANDIDATE_SCHEMA_VERSION],
                    "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
                    "max_payload_bytes": 750_000,
                    "capabilities": ["content_provider_pfd", "service_hierarchy_v2",
                                     CANDIDATE_SCHEMA_VERSION],
                }
            else:
                self.request_id = pairs["requestId"]
                self.client_nonce = pairs["clientNonce"]
                self.artifact, self.ready, _, self.payload = _artifact_control(
                    self.request_id, self.client_nonce, self.identity
                )
                self.ready.update(
                    schema=CONTROL_SCHEMA,
                    protocol_version="hierarchy-payload.v1",
                    request_id=self.request_id,
                    client_nonce=self.client_nonce,
                    query_nonce=query_nonce,
                    process_epoch=self.process_epoch,
                    helper_build_identity={
                        key: value for key, value in self.identity.items()
                        if key != "service_instance_id"
                    },
                    service_instance_id=self.identity["service_instance_id"],
                    payload_schema_version=RAW_SCHEMA_VERSION,
                )
                if operation == "START":
                    response = {**self.ready, "status": "ACCEPTED", "completed": False,
                                "payload_complete": False}
                elif operation == "STATUS":
                    response = {
                        **self.ready,
                        "status": "READY",
                        "payload_uri": f"content://{PROVIDER_AUTHORITY}/v1/{self.process_epoch}/"
                                       f"{self.request_id}/1/{self.token}",
                    }
                elif operation == "ACK":
                    if self.ack_mode == "native_error":
                        raise RuntimeError("injected ACK ADB failure")
                    if self.ack_mode == "malformed":
                        return "Broadcasting: Intent {}"
                    if self.ack_mode == "protocol_error":
                        response = {
                            **self.ready, "status": "FAILED", "completed": True,
                            "payload_complete": False, "generation": None,
                            "error_code": "ACK_IDENTITY_MISMATCH",
                        }
                    else:
                        response = {**self.ready, "status": "ACKED"}
                        if self.ack_mode == "identity_mismatch":
                            response["generation"] = 2
                        elif self.ack_mode == "nonce_mismatch":
                            response["client_nonce"] = "f" * 32
                        elif self.ack_mode == "request_mismatch":
                            response["request_id"] = "f" * 32
                        elif self.ack_mode == "incomplete":
                            response["completed"] = False
                elif operation == "CANCEL":
                    if self.cancel_mode == "native_error":
                        raise RuntimeError("injected CANCEL ADB failure")
                    if self.cancel_mode == "malformed":
                        return "Broadcasting: Intent {}"
                    if self.cancel_mode == "protocol_error":
                        response = {
                            **self.ready, "status": "FAILED", "completed": True,
                            "error_code": "REQUEST_NOT_FOUND",
                        }
                    else:
                        response = {**self.ready, "status": "CANCELLED"}
                else:
                    raise AssertionError(f"unexpected Helper operation: {operation}")
            encoded = encode_control(response)
            result_code = 1 if response.get("status") in {
                "OK", "ACCEPTED", "COLLECTING", "WRITING", "READY", "ACKED", "CANCELLED",
            } else 2
            return (f'Broadcasting: Intent {{}}\n'
                    f'Broadcast completed: result={result_code}, data="{encoded}"')
        if command == ["shell", "am", "get-current-user"]:
            return "0"
        raise AssertionError(f"unexpected command reached fake ADB: {command!r}")

    def binary(self, args, **kwargs):
        command = [str(value) for value in args]
        self.commands.append(command)
        assert command[:5] == ["shell", "-T", "content", "read", "--user"]
        assert command[6] == "--uri"
        payload = b"not-a-valid-artifact" if self.fail_payload else self.artifact
        return type("BinaryResult", (), {
            "stdout": payload, "stderr": b"", "stderr_truncated": False, "returncode": 0,
        })()


def _client_and_backend(monkeypatch, *, fail_payload=False, ack_mode="valid", cancel_mode="valid"):
    import talkback_lib

    client = A11yAdbClient(start_monitor=False)
    backend = _ReliableTransportBackend(client, fail_payload=fail_payload,
                                        ack_mode=ack_mode, cancel_mode=cancel_mode)
    client.check_helper_status = lambda **_kwargs: True
    client.precheck_helper_build_identity = lambda **_kwargs: {
        "status": "COMPATIBLE_SAME_HELPER_INPUT",
        "execution_allowed": True,
        "helper_build_id": backend.identity["build_id"],
        "helper_git_commit": backend.identity["git_commit"],
        "helper_service_instance_id": backend.identity["service_instance_id"],
        "helper_input_digest": backend.identity["input_digest"],
    }
    monkeypatch.setattr(client._adb_device, "_run_adb_command", backend.command)
    monkeypatch.setattr(client._adb_device, "_run_adb_binary_command", backend.binary)
    monkeypatch.setattr(talkback_lib.time, "sleep", lambda _seconds: None)
    return client, backend


def test_real_collector_hierarchy_resolution_uses_reliable_transport_under_phase5(monkeypatch):
    client, backend = _client_and_backend(monkeypatch)
    session = SafeNavigationSession("device_smoke_sensor_plugin", lambda *_args: None)
    step = {}
    with session.firewall(client, "offline-device"):
        client._resolve_step_dump_tree(
            step, trace={}, safe_focus_node={}, allow_step_dump=True, dev="offline-device"
        )

    assert step["step_dump_tree_used"] is True
    assert len(step["dump_tree_nodes"]) == 1
    assert client.last_hierarchy_metadata["transportMode"] == "RELIABLE_FILE_PFD"
    assert session.command_blocks == []
    actions = [command[4].rsplit("_", 1)[-1] for command in backend.commands
               if command[:3] == ["shell", "am", "broadcast"]]
    assert actions == ["CAPABILITIES", "START", "STATUS", "STATUS", "ACK"]
    assert ["shell", "am", "get-current-user"] in backend.commands
    payload_reads = [command for command in backend.commands if command[:3] == ["shell", "-T", "content"]]
    assert len(payload_reads) == 1
    assert payload_reads[0][7].startswith(f"content://{PROVIDER_AUTHORITY}/v1/")
    assert "DUMP_HIERARCHY" not in " ".join(" ".join(command) for command in backend.commands)
    assert session._phase5_hierarchy_request is None
    assert client.last_hierarchy_cleanup_diagnostic["status"] == "ACKED"
    ack = next(command for command in backend.commands
               if command[:3] == ["shell", "am", "broadcast"]
               and command[4].endswith("HIERARCHY_TRANSFER_ACK"))
    ack_extras = _ReliableTransportBackend._pairs(ack[7:])
    stale_cancel = _broadcast("CANCEL", [
        "--es", "requestId", ack_extras["requestId"],
        "--es", "clientNonce", ack_extras["clientNonce"],
        "--es", "queryNonce", "9" * 32,
    ])
    assert not session.command_allowed(ack)
    assert not session.command_allowed(stale_cancel)
    assert not any(command[:3] == ["shell", "am", "broadcast"]
                   and command[4].endswith("HIERARCHY_TRANSFER_CANCEL")
                   for command in backend.commands)


def test_reliable_transport_failure_can_send_correlated_cancel_through_phase5(monkeypatch):
    client, backend = _client_and_backend(monkeypatch, fail_payload=True)
    session = SafeNavigationSession("device_smoke_sensor_plugin", lambda *_args: None)
    with session.firewall(client, "offline-device"):
        with pytest.raises(HierarchyTransportError, match="ARTIFACT_INTEGRITY_MISMATCH"):
            client.dump_hierarchy(dev="offline-device", wait_seconds=2.0)
    actions = [command[4].rsplit("_", 1)[-1] for command in backend.commands
               if command[:3] == ["shell", "am", "broadcast"]]
    assert actions == ["CAPABILITIES", "START", "STATUS", "CANCEL"]
    cancel = next(command for command in backend.commands
                  if command[:3] == ["shell", "am", "broadcast"]
                  and command[4].endswith("HIERARCHY_TRANSFER_CANCEL"))
    cancel_extras = _ReliableTransportBackend._pairs(cancel[7:])
    assert cancel_extras["requestId"] == backend.request_id
    assert cancel_extras["clientNonce"] == backend.client_nonce
    assert session.command_blocks == []
    assert session._phase5_hierarchy_request is None
    assert client.last_hierarchy_cleanup_diagnostic["status"] == "CANCELLED"


@pytest.mark.parametrize(("ack_mode", "expected_error"), [
    ("native_error", "CONTROL_ACK_FAILED"),
    ("protocol_error", "ACK_IDENTITY_MISMATCH"),
    ("malformed", "CONTROL_COMPLETION_AMBIGUOUS"),
    ("identity_mismatch", "ACK_IDENTITY_MISMATCH"),
    ("nonce_mismatch", "CONTROL_CLIENT_NONCE_MISMATCH"),
    ("request_mismatch", "CONTROL_REQUEST_ID_MISMATCH"),
    ("incomplete", "ACK_COMPLETION_INVALID"),
])
def test_ack_validation_failure_keeps_original_correlation_for_phase5_cancel(
        monkeypatch, ack_mode, expected_error):
    client, backend = _client_and_backend(monkeypatch, ack_mode=ack_mode)
    session = SafeNavigationSession("device_smoke_sensor_plugin", lambda *_args: None)
    with session.firewall(client, "offline-device"):
        with pytest.raises(HierarchyTransportError) as raised:
            client.dump_hierarchy(dev="offline-device", wait_seconds=2.0)

    assert raised.value.reason == expected_error
    operations = [command[4].rsplit("_", 1)[-1] for command in backend.commands
                  if command[:3] == ["shell", "am", "broadcast"]]
    assert operations[-2:] == ["ACK", "CANCEL"]
    cancel = next(command for command in backend.commands
                  if command[:3] == ["shell", "am", "broadcast"]
                  and command[4].endswith("HIERARCHY_TRANSFER_CANCEL"))
    cancel_extras = _ReliableTransportBackend._pairs(cancel[7:])
    assert cancel_extras["requestId"] == backend.request_id
    assert cancel_extras["clientNonce"] == backend.client_nonce
    assert session.command_blocks == []
    assert session._phase5_hierarchy_request is None
    assert client.last_hierarchy_cleanup_diagnostic["status"] == "CANCELLED"


@pytest.mark.parametrize(("cancel_mode", "expected_status"), [
    ("valid", "CANCELLED"),
    ("native_error", "FAILED"),
    ("protocol_error", "FAILED"),
    ("malformed", "FAILED"),
])
def test_cancel_terminal_outcome_releases_only_its_current_request(
        monkeypatch, cancel_mode, expected_status):
    client, backend = _client_and_backend(
        monkeypatch, fail_payload=True, cancel_mode=cancel_mode
    )
    session = SafeNavigationSession("device_smoke_sensor_plugin", lambda *_args: None)
    with session.firewall(client, "offline-device"):
        with pytest.raises(HierarchyTransportError, match="ARTIFACT_INTEGRITY_MISMATCH"):
            client.dump_hierarchy(dev="offline-device", wait_seconds=2.0)

    assert session._phase5_hierarchy_request is None
    assert client.last_hierarchy_cleanup_diagnostic["status"] == expected_status
    old_cancel = _broadcast("CANCEL", [
        "--es", "requestId", backend.request_id,
        "--es", "clientNonce", backend.client_nonce,
        "--es", "queryNonce", "9" * 32,
    ])
    assert not session.command_allowed(old_cancel)


def test_phase5_cancel_requires_exact_live_request_and_nonce_and_is_one_shot():
    session = SafeNavigationSession("synthetic", lambda *_args: None)
    request_id, client_nonce = "b" * 32, "c" * 32
    assert session.command_allowed(_broadcast("CAPABILITIES", [
        "--es", "queryNonce", "a" * 32,
    ]))
    assert session.command_allowed(_broadcast("START", [
        "--es", "requestId", request_id,
        "--es", "clientNonce", client_nonce,
        "--es", "expectedBuildId", "d" * 64,
        "--es", "expectedGitCommit", "e" * 40,
        "--es", "expectedServiceInstanceId", "service-instance",
        "--es", "queryNonce", "f" * 32,
    ]))
    wrong_request = _broadcast("CANCEL", [
        "--es", "requestId", "9" * 32,
        "--es", "clientNonce", client_nonce,
        "--es", "queryNonce", "1" * 32,
    ])
    wrong_nonce = _broadcast("CANCEL", [
        "--es", "requestId", request_id,
        "--es", "clientNonce", "8" * 32,
        "--es", "queryNonce", "1" * 32,
    ])
    good_cancel = _broadcast("CANCEL", [
        "--es", "requestId", request_id,
        "--es", "clientNonce", client_nonce,
        "--es", "queryNonce", "1" * 32,
    ])
    assert not session.command_allowed(wrong_request)
    assert not session.command_allowed(wrong_nonce)
    assert session.command_allowed(good_cancel)
    assert not session.command_allowed(good_cancel)
    session.finish_hierarchy_cancel(
        request_id=request_id, client_nonce=client_nonce, query_nonce="1" * 32
    )
    assert session._phase5_hierarchy_request is None


def test_ack_error_remains_primary_when_correlated_cancel_also_fails(monkeypatch):
    client, backend = _client_and_backend(
        monkeypatch, ack_mode="protocol_error", cancel_mode="protocol_error"
    )
    session = SafeNavigationSession("device_smoke_sensor_plugin", lambda *_args: None)
    with session.firewall(client, "offline-device"):
        with pytest.raises(HierarchyTransportError) as raised:
            client.dump_hierarchy(dev="offline-device", wait_seconds=2.0)

    assert raised.value.reason == "ACK_IDENTITY_MISMATCH"
    assert client.last_hierarchy_cleanup_diagnostic == {
        "request_id": backend.request_id,
        "status": "FAILED",
        "error_code": "CANCEL_CORRELATION_MISMATCH",
    }
    assert session._phase5_hierarchy_request is None


def test_phase5_ack_requires_ready_payload_digest_and_is_one_shot():
    session = SafeNavigationSession("synthetic", lambda *_args: None)
    request_id, client_nonce = "b" * 32, "c" * 32
    assert session.command_allowed(_broadcast("CAPABILITIES", [
        "--es", "queryNonce", "a" * 32,
    ]))
    assert session.command_allowed(_broadcast("START", [
        "--es", "requestId", request_id,
        "--es", "clientNonce", client_nonce,
        "--es", "expectedBuildId", "d" * 64,
        "--es", "expectedGitCommit", "e" * 40,
        "--es", "expectedServiceInstanceId", "service-instance",
        "--es", "queryNonce", "f" * 32,
    ]))
    request = session._phase5_hierarchy_request
    request["payload_read"] = True
    request["payload_sha256"] = "1" * 64
    wrong_digest = _broadcast("ACK", [
        "--es", "requestId", request_id,
        "--es", "clientNonce", client_nonce,
        "--es", "payloadSha256", "2" * 64,
        "--es", "queryNonce", "3" * 32,
    ])
    good_ack = _broadcast("ACK", [
        "--es", "requestId", request_id,
        "--es", "clientNonce", client_nonce,
        "--es", "payloadSha256", "1" * 64,
        "--es", "queryNonce", "3" * 32,
    ])
    assert not session.command_allowed(wrong_digest)
    assert session.command_allowed(good_ack)
    assert not session.command_allowed(good_ack)


@pytest.mark.parametrize("command", [
    ["shell", "am", "start", "com.example/.Main"],
    ["shell", "am", "force-stop", "com.example"],
    ["shell", "content", "read", "--uri", "content://example.provider/arbitrary"],
    ["shell", "-T", "content", "read", "--user", "0", "--uri",
     "content://com.iotpart.sqe.talkbackhelper.hierarchy/v1/e/" + "a" * 32 + "/1/" + "b" * 32],
    _broadcast("FUTURE", ["--es", "queryNonce", "a" * 32]),
    _broadcast("CAPABILITIES", ["--es", "queryNonce", "a" * 32], package="com.example.helper"),
    ["shell", "am", "get-current-user", "extra"],
])
def test_phase5_hierarchy_allowlist_does_not_open_general_am_or_content_access(command):
    session = SafeNavigationSession("synthetic", lambda *_args: None)
    assert not session.command_allowed(command)


def test_phase5_rejects_malformed_and_wrong_request_hierarchy_control():
    session = SafeNavigationSession("synthetic", lambda *_args: None)
    cap = _broadcast("CAPABILITIES", ["--es", "queryNonce", "a" * 32])
    assert session.command_allowed(cap)
    malformed_start = _broadcast("START", [
        "--es", "requestId", "b" * 32,
        "--es", "clientNonce", "c" * 32,
        "--es", "expectedBuildId", "d" * 64,
        "--es", "expectedGitCommit", "e" * 40,
        "--es", "expectedServiceInstanceId", "service-id",
        "--es", "queryNonce", "f" * 32,
        "--es", "unexpected", "value",
    ])
    assert not session.command_allowed(malformed_start)
    assert session._phase5_hierarchy_request is None

    good_start = _broadcast("START", [
        "--es", "requestId", "b" * 32,
        "--es", "clientNonce", "c" * 32,
        "--es", "expectedBuildId", "d" * 64,
        "--es", "expectedGitCommit", "e" * 40,
        "--es", "expectedServiceInstanceId", "service-id",
        "--es", "queryNonce", "f" * 32,
    ])
    assert session.command_allowed(good_start)
    wrong_status = _broadcast("STATUS", [
        "--es", "requestId", "9" * 32,
        "--es", "clientNonce", "c" * 32,
        "--es", "queryNonce", "1" * 32,
    ])
    assert not session.command_allowed(wrong_status)
    wrong_component = ["shell", "am", "broadcast", "-a",
                       f"{PACKAGE}.HIERARCHY_TRANSFER_STATUS", "-p", "com.example.helper",
                       "--es", "requestId", "b" * 32, "--es", "clientNonce", "c" * 32,
                       "--es", "queryNonce", "1" * 32]
    assert not session.command_allowed(wrong_component)


def test_phase5_pfd_read_requires_the_exact_uri_from_current_validated_ready(monkeypatch):
    client, _backend = _client_and_backend(monkeypatch)
    session = SafeNavigationSession("synthetic", lambda *_args: None)
    request_id, client_nonce = "b" * 32, "c" * 32
    with session.firewall(client, "offline-device"):
        assert session.command_allowed(_broadcast("CAPABILITIES", [
            "--es", "queryNonce", "a" * 32,
        ]))
        assert session.command_allowed(_broadcast("START", [
            "--es", "requestId", request_id,
            "--es", "clientNonce", client_nonce,
            "--es", "expectedBuildId", "d" * 64,
            "--es", "expectedGitCommit", "e" * 40,
            "--es", "expectedServiceInstanceId", "service-uuid",
            "--es", "queryNonce", "f" * 32,
        ]))
        assert session.command_allowed(_broadcast("STATUS", [
            "--es", "requestId", request_id,
            "--es", "clientNonce", client_nonce,
            "--es", "queryNonce", "1" * 32,
        ]))
        uri = (f"content://{PROVIDER_AUTHORITY}/v1/process-epoch-1/"
               f"{request_id}/1/{'2' * 32}")
        control = {
            "status": "READY", "completed": True, "payload_complete": True,
            "request_id": request_id, "client_nonce": client_nonce,
            "process_epoch": "process-epoch-1", "generation": 1,
        }
        session.authorize_hierarchy_payload_read(user_id="0", uri=uri, control=control)
        exact = ["shell", "-T", "content", "read", "--user", "0", "--uri", uri]
        altered = [*exact[:-1], uri[:-1] + "3"]
        assert session.command_allowed(exact)
        assert not session.command_allowed(altered)
        assert not session.command_allowed([*exact[:-1], "content://example.provider/path"])


def test_controlled_graph_projection_uses_current_request_target_and_typed_dispatch():
    row = {
        "step_index": 4,
        "phase6_current_action_type": "CONTROLLED_FOCUS",
        "controlled_focus_request_id": "request-current",
        "controlled_focus_operation_id": "operation-current",
        "controlled_focus_dispatch_status": "DISPATCHED",
        "target_focus_attempt_id": "attempt-not-request",
        "target_focus_descriptor": {
            "resource_id": "app:id/target", "class_name": "android.widget.Button",
            "bounds": "10,20,30,40", "label": "not-an-identity-field",
        },
        "controlled_focus_intent": {
            "target_descriptor": {
                "resource_id": "app:id/target", "class_name": "android.widget.Button",
                "bounds": "10,20,30,40",
            },
        },
    }
    projected = _evidence_from_row(row)
    assert projected["action"] == {
        "type": "TARGETED_FOCUS",
        "target": {"resource_id": "app:id/target", "class_name": "android.widget.Button",
                   "bounds": "10,20,30,40"},
        "request_id": "request-current",
    }
    assert projected["attempted"] is True
    assert projected["dispatched"] is True
    assert projected["dispatch_status"] == "DISPATCHED"

    recorder = recorder_from_existing_rows([{
        **row,
        "state_graph_observation": {
            "scenario_id": "home_main", "package_name": "com.example",
            "activity_name": "com.example.Main", "context_source": "window_current_focus",
            "nodes": [], "observation_coverage": "OBSERVED_PARTIAL",
        },
    }], run_id="run-graph", scenario_id="home_main")
    edge = recorder.edges[0]
    assert edge["request_id"] == "request-current"
    assert edge["target"] == projected["action"]["target"]
    assert EdgeLifecycle.DISPATCHED.value in edge["lifecycle"]
    assert recorder.to_dict()["authority"] == "OBSERVATIONAL_SHADOW_ONLY"
    assert recorder.to_dict()["decision_authority"] == "NONE"


def test_smart_next_graph_projection_keeps_action_scoped_request_and_unknown_dispatch():
    row = {
        "step_index": 2,
        "phase6_current_action_type": "SMART_NEXT",
        "smart_nav_req_id": "request-smart-next",
        "smart_nav_invocation_generation": 12,
        "smart_nav_result_generation": 12,
        "last_smart_nav_result": "success",
        "smart_nav_requested_view_id": "app:id/next",
        "smart_nav_requested_class_name": "android.widget.Button",
        "smart_nav_requested_bounds": "1,2,3,4",
        "target_focus_request_id": "stale-target-request",
        "target_focus_attempt_id": "attempt-not-request",
        "controlled_focus_request_id": "stale-controlled-request",
    }
    projected = _evidence_from_row(row)
    assert projected["action"] == {
        "type": "FOCUS_NEXT", "target": {"resource_id": "app:id/next",
                                            "class_name": "android.widget.Button",
                                            "bounds": "1,2,3,4"},
        "request_id": "request-smart-next",
    }
    # A request or ACK cannot stand in for typed dispatch evidence.
    assert projected["dispatched"] is False
    assert projected["dispatch_status"] == "UNKNOWN"
    assert projected["command_ack"] == "success"


@pytest.mark.parametrize("wrong_status", ["", "UNKNOWN", "DISPATCHED"])
def test_graph_never_infers_or_borrows_dispatch_from_another_action(wrong_status):
    row = {
        "step_index": 1,
        "phase6_current_action_type": "TARGETED_FOCUS",
        "target_focus_request_id": "request-target",
        "target_focus_attempt_id": "attempt-target",
        "smart_nav_req_id": "request-stale-smart",
        "smart_nav_dispatch_status": "DISPATCHED",
        "smart_nav_invocation_generation": 7,
        "smart_nav_result_generation": 7,
        "last_smart_nav_result": "success",
    }
    if wrong_status:
        row["target_focus_dispatch_status"] = wrong_status
        row["target_focus_dispatch_request_id"] = "request-other"
    projected = _evidence_from_row(row)
    assert projected["action"]["request_id"] == "request-target"
    assert projected["dispatched"] is False
    assert projected["dispatch_status"] == "UNKNOWN"
    assert projected["command_ack"] is None


def test_graph_uses_matching_action_specific_dispatch_status_only():
    row = {
        "step_index": 1,
        "phase6_current_action_type": "TARGETED_FOCUS",
        "target_focus_request_id": "request-target",
        "target_focus_dispatch_request_id": "request-target",
        "target_focus_dispatch_status": "NOT_DISPATCHED",
        "target_focus_descriptor": {"resource_id": "app:id/target"},
    }
    projected = _evidence_from_row(row)
    assert projected["dispatch_status"] == "NOT_DISPATCHED"
    assert projected["dispatched"] is False
