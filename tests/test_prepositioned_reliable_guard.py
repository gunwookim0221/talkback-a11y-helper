from __future__ import annotations

import hashlib
import json
import re
from types import SimpleNamespace

import pytest

import talkback_lib.adb_device as adb_device_module
from talkback_lib import A11yAdbClient
from talkback_lib.hierarchy_file_transport import (
    CONTROL_SCHEMA,
    DEFAULT_HIERARCHY_TRANSPORT_MODE,
    MAX_PAYLOAD_BYTES,
    PAYLOAD_SCHEMA,
    PROTOCOL_VERSION,
    PROVIDER_AUTHORITY,
    HierarchyTransportError,
    encode_artifact,
    encode_control,
    sha256_hex,
)
from talkback_lib.reliable_hierarchy_schema import (
    CANDIDATE_CONTRACT_VERSION,
    CANDIDATE_SCHEMA_VERSION,
)
from tb_runner.entry_mode import PrepositionedSafetyStop, PrepositionedSession


HELPER_ACTION_PREFIX = "com.iotpart.sqe.talkbackhelper."
HELPER_PACKAGE = "com.iotpart.sqe.talkbackhelper"
PROCESS_EPOCH = "process-epoch-1"
SERVICE_ID = "service-instance-1"
BUILD_ID = "a" * 64
GIT_COMMIT = "b" * 40
INPUT_DIGEST = "c" * 64
TOKEN = "e" * 32


def _broadcast(action: str, *extras: str) -> list[str]:
    return ["shell", "am", "broadcast", "-a", HELPER_ACTION_PREFIX + action,
            "-p", HELPER_PACKAGE, *extras]


def _client_and_session(tmp_path):
    client = A11yAdbClient(adb_path="fake-adb", dev_serial="SERIAL", start_monitor=False)
    session = PrepositionedSession(
        client,
        {"scenario_id": "life_home_monitor_plugin"},
        tmp_path / "prepositioned.jsonl",
        log_fn=lambda *_args, **_kwargs: None,
    )
    session.bind()
    return client, session


def _audit(session):
    return [json.loads(line) for line in session.audit_path.read_text(encoding="utf-8").splitlines()]


def _expected_identity():
    return {
        "status": "MATCH",
        "helper_build_id": BUILD_ID,
        "helper_git_commit": GIT_COMMIT,
        "helper_service_instance_id": SERVICE_ID,
        "helper_input_digest": INPUT_DIGEST,
        "build_variant": "debug",
    }


class _Pipe:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, _size: int = -1) -> bytes:
        value, self._payload = self._payload, b""
        return value

    def close(self) -> None:
        pass


class _FakeProcess:
    def __init__(self, payload: bytes):
        self.stdout = _Pipe(payload)
        self.stderr = _Pipe(b"")
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def _install_device_responses(monkeypatch, client, *, failure: str | None = None,
                              malformed_uri: bool = False,
                              candidate_capability: bool = True):
    """Replace only external ADB responses; real A11yAdbClient/AdbDevice guards run."""
    raw_root = {
        "text": "Home Monitor", "contentDescription": None,
        "viewIdResourceName": "app:id/home_monitor", "className": "android.widget.TextView",
        "packageName": "com.samsung.android.oneconnect", "windowId": 1,
        "boundsInScreen": {"l": 0, "t": 0, "r": 1080, "b": 2400},
        "clickable": False, "effectiveClickable": False, "enabled": True,
        "focusable": False, "focused": False, "inputFocused": False,
        "accessibilityFocused": False, "selected": False, "scrollable": False,
        "isScrollable": False, "checkable": False, "checked": False,
        "visibleToUser": True, "isVisibleToUser": True,
        "screenReaderFocusable": False, "rangeInfoPresent": False,
        "actions": [], "children": [],
    }
    candidate = {
        "text": "Home Monitor", "contentDescription": None,
        "className": "android.widget.TextView", "viewIdResourceName": "app:id/home_monitor",
        "boundsInScreen": {"l": 0, "t": 0, "r": 1080, "b": 2400},
        "clickable": False, "focusable": False, "isVisibleToUser": True,
        "focused": False, "accessibilityFocused": False,
        "isTopAppBar": False, "isBottomNavigationBar": False,
        "hasClickableDescendant": False, "hasFocusableDescendant": False,
        "effectiveClickable": False,
        "actionableDescendantResourceId": None,
        "actionableDescendantClassName": None,
        "actionableDescendantContentDescription": None,
    }
    payload = json.dumps({
        "reqId": "pending", "success": True, "schemaVersion": PAYLOAD_SCHEMA,
        "platformApiLevel": 34, "traversalRootRef": "windows[0].root",
        "traversalRootWindowId": 1, "nodeCount": 1,
        "nodes": [raw_root], "windows": [{"id": 1, "root": raw_root}],
        "traversalCandidates": {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
            "algorithmVersion": "2.76.3", "analyzerVersion": "1.11.1",
            "profileId": "oneconnect-traversal-policy", "profileVersion": "1.0.0",
            "completion": {"status": "COMPLETE", "complete": True, "candidate_count": 1},
            "traversalRootRef": "windows[0].root", "traversalRootWindowId": 1,
            "canScrollDown": False, "scrollAxisContract": "axis-v1", "candidates": [candidate],
        },
    }, separators=(",", ":")).encode("utf-8")
    state: dict[str, object] = {
        "actions": [],
        "commands": [],
        "status_count": 0,
        "request_id": "",
        "client_nonce": "",
        "artifact": b"",
        "ready": {},
    }
    helper_identity = {
        "build_id": BUILD_ID,
        "git_commit": GIT_COMMIT,
        "input_digest": INPUT_DIGEST,
        "source_state": "CLEAN",
        "build_variant": "debug",
    }

    def artifact_for(request_id: str, client_nonce: str) -> tuple[bytes, dict]:
        body = dict(json.loads(payload.decode("utf-8")), reqId=request_id)
        payload_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
        header = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "client_nonce": client_nonce,
            "process_epoch": PROCESS_EPOCH,
            "generation": 1,
            "service_instance_id": SERVICE_ID,
            "helper_build_identity": helper_identity,
            "payload_schema_version": PAYLOAD_SCHEMA,
            "payload_bytes": len(payload_bytes),
            "payload_sha256": sha256_hex(payload_bytes),
            "created_elapsed_realtime_ns": 100,
            "completed_elapsed_realtime_ns": 201,
        }
        artifact = encode_artifact(header, payload_bytes)
        ready = {
            "schema": CONTROL_SCHEMA,
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "client_nonce": client_nonce,
            "process_epoch": PROCESS_EPOCH,
            "generation": 1,
            "service_instance_id": SERVICE_ID,
            "helper_build_identity": helper_identity,
            "payload_schema_version": PAYLOAD_SCHEMA,
            "status": "READY",
            "completed": True,
            "payload_complete": True,
            "payload_bytes": len(payload_bytes),
            "payload_sha256": sha256_hex(payload_bytes),
            "artifact_bytes": len(artifact),
            "artifact_sha256": sha256_hex(artifact),
            "completed_elapsed_realtime_ns": 201,
            "payload_uri": f"content://{PROVIDER_AUTHORITY}/v1/{PROCESS_EPOCH}/{request_id}/1/{TOKEN}",
        }
        if malformed_uri:
            ready["payload_uri"] = f"content://other.provider/v1/{PROCESS_EPOCH}/{request_id}/1/{TOKEN}"
        return artifact, ready

    def message(action: str, values: dict[str, str]) -> dict:
        state["actions"].append(action)
        if action == "CAPABILITIES":
            response = {
                "schema": CONTROL_SCHEMA,
                "protocol_version": PROTOCOL_VERSION,
                "status": "OK",
                "query_nonce": values["queryNonce"],
                "process_epoch": PROCESS_EPOCH,
                "service_instance_id": SERVICE_ID,
                "helper_build_identity": helper_identity,
                "payload_schema_version": PAYLOAD_SCHEMA,
                "supported_payload_schema_versions": [PAYLOAD_SCHEMA],
                "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
                "supported_candidate_schema_versions": [CANDIDATE_SCHEMA_VERSION],
                "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
                "max_payload_bytes": MAX_PAYLOAD_BYTES,
                "capabilities": ["content_provider_pfd", "service_hierarchy_v2", CANDIDATE_SCHEMA_VERSION],
            }
            if not candidate_capability:
                response.pop("candidate_schema_version")
                response.pop("supported_candidate_schema_versions")
                response.pop("candidate_contract_version")
                response["capabilities"] = ["content_provider_pfd"]
            return response
        request_id = values["requestId"]
        client_nonce = values.get("clientNonce", "")
        if action == "START":
            state["request_id"] = request_id
            state["client_nonce"] = client_nonce
            artifact, ready = artifact_for(request_id, client_nonce)
            state["artifact"], state["ready"] = artifact, ready
            return {
                **ready,
                "status": "ACCEPTED",
                "completed": False,
                "payload_complete": False,
                "query_nonce": values["queryNonce"],
            }
        if action == "STATUS":
            state["status_count"] = int(state["status_count"]) + 1
            if failure == "status" and state["status_count"] == 1:
                return {
                    **state["ready"], "status": "FAILED", "error_code": "CAPTURE_FAILED",
                    "query_nonce": values["queryNonce"],
                }
            return {**state["ready"], "query_nonce": values["queryNonce"]}
        if action == "ACK" and failure == "ack":
            return {
                **state["ready"], "status": "FAILED", "error_code": "ACK_REJECTED",
                "query_nonce": values["queryNonce"],
            }
        if action == "ACK":
            return {**state["ready"], "status": "ACKED", "query_nonce": values["queryNonce"]}
        if action == "CANCEL":
            return {
                **state["ready"], "status": "CANCELLED", "query_nonce": values["queryNonce"],
            }
        raise AssertionError(f"unexpected reliable action: {action}")

    def fake_run(command, **_kwargs):
        state["commands"].append(command)
        shell_index = command.index("shell")
        shell = command[shell_index + 1:]
        if shell == ["am", "get-current-user"]:
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        if shell[:2] != ["am", "broadcast"]:
            raise AssertionError(f"unexpected text ADB command: {shell!r}")
        action_index = shell.index("-a")
        action = shell[action_index + 1].removeprefix(HELPER_ACTION_PREFIX)
        action = action.removeprefix("HIERARCHY_TRANSFER_")
        values = {}
        for index in range(len(shell) - 2):
            if shell[index] == "--es":
                values[shell[index + 1]] = shell[index + 2]
        response = message(action, values)
        result_code = "2" if response.get("status") == "FAILED" else "1"
        encoded = encode_control(response)
        output = f'Broadcasting: Intent {{}}\nBroadcast completed: result={result_code}, data="{encoded}"'
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    def fake_popen(command, **_kwargs):
        shell_index = command.index("shell")
        shell = command[shell_index + 1:]
        state["commands"].append(command)
        expected_prefix = ["-T", "content", "read", "--user", "0", "--uri"]
        assert shell[:6] == expected_prefix
        assert len(shell) == 7
        assert shell[6] == state["ready"]["payload_uri"]
        if failure == "content_read":
            raise FileNotFoundError("simulated provider read failure")
        return _FakeProcess(state["artifact"])

    monkeypatch.setattr(adb_device_module.subprocess, "run", fake_run)
    monkeypatch.setattr(adb_device_module.subprocess, "Popen", fake_popen)
    return state


@pytest.mark.parametrize(
    ("action", "kind"),
    [
        ("HIERARCHY_TRANSFER_CAPABILITIES", "READ_ONLY_QUERY"),
        ("HIERARCHY_TRANSFER_START", "READ_ONLY_OBSERVATION_CONTROL"),
        ("HIERARCHY_TRANSFER_STATUS", "READ_ONLY_OBSERVATION_CONTROL"),
        ("HIERARCHY_TRANSFER_ACK", "TRANSPORT_CLEANUP_CONTROL"),
        ("HIERARCHY_TRANSFER_CANCEL", "TRANSPORT_CLEANUP_CONTROL"),
    ],
)
def test_exact_reliable_action_categories_remain_narrow(tmp_path, action, kind):
    client, session = _client_and_session(tmp_path)
    session.guard_command(_broadcast(action, "--es", "queryNonce", "1" * 32))
    event = _audit(session)[-1]
    assert event["event"] == "COMMAND_ALLOWED"
    assert event["kind"] == kind
    assert event["phase"] == "READ_ONLY"
    assert client._adb_device.command_guard == session.guard_command


def test_ping_policy_is_unchanged_and_unknown_control_action_stops_with_terminal_audit(tmp_path):
    _, session = _client_and_session(tmp_path)
    session.guard_command(_broadcast("PING"))
    assert _audit(session)[-1]["kind"] == "read_only"

    command = _broadcast("HIERARCHY_TRANSFER_UNRECOGNIZED", "--es", "queryNonce", "2" * 32)
    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(command)
    rows = _audit(session)
    blocked = next(row for row in rows if row["event"] == "COMMAND_BLOCKED")
    terminal = next(row for row in rows if row["event"] == "INTERNAL_TRAVERSAL_TERMINAL")
    assert blocked["action_dispatched"] is False
    assert terminal["blocked_operation"] == command
    assert terminal["blocked_operation_dispatched"] is False


@pytest.mark.parametrize(
    "command",
    [
        ["shell", "am", "get-current-user", "extra"],
        ["shell", "am", "start", "com.example/.Activity"],
        ["shell", "am", "get-current-user; am start x"],
        ["shell", "am", "get-current-user", "|", "id"],
    ],
)
def test_only_exact_current_user_query_is_allowed(tmp_path, command):
    _, session = _client_and_session(tmp_path)
    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(command)
    rows = _audit(session)
    assert rows[-1]["event"] == "INTERNAL_TRAVERSAL_TERMINAL"
    assert rows[-1]["blocked_operation"] == command
    assert rows[-1]["blocked_operation_dispatched"] is False


def test_exact_current_user_query_is_a_read_only_query(tmp_path):
    _, session = _client_and_session(tmp_path)
    session.guard_command(["shell", "am", "get-current-user"])
    assert _audit(session)[-1]["kind"] == "READ_ONLY_QUERY"


def test_payload_read_requires_validated_one_use_uri_and_numeric_user(tmp_path):
    client, session = _client_and_session(tmp_path)
    request_id = "3" * 32
    uri = f"content://{PROVIDER_AUTHORITY}/v1/{PROCESS_EPOCH}/{request_id}/1/{TOKEN}"
    control = {"process_epoch": PROCESS_EPOCH, "request_id": request_id, "generation": 1}
    session.authorize_hierarchy_payload_read(user_id="0", uri=uri, control=control)
    with pytest.raises(ValueError, match="already authorized"):
        session.authorize_hierarchy_payload_read(user_id="0", uri=uri, control=control)
    command = ["shell", "-T", "content", "read", "--user", "0", "--uri", uri]
    session.guard_command(command)
    assert _audit(session)[-1]["kind"] == "READ_ONLY_DATA_READ"

    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(command)
    assert _audit(session)[-1]["event"] == "INTERNAL_TRAVERSAL_TERMINAL"


@pytest.mark.parametrize(
    ("user_id", "uri"),
    [
        ("../0", f"content://{PROVIDER_AUTHORITY}/v1/{PROCESS_EPOCH}/{'4' * 32}/1/{TOKEN}"),
        ("0", f"content://other.provider/v1/{PROCESS_EPOCH}/{'4' * 32}/1/{TOKEN}"),
        ("0", f"content://{PROVIDER_AUTHORITY}/v1/{PROCESS_EPOCH}/../1/{TOKEN}"),
    ],
)
def test_read_authorization_rejects_non_numeric_user_or_unvalidated_uri(tmp_path, user_id, uri):
    client, session = _client_and_session(tmp_path)
    control = {"process_epoch": PROCESS_EPOCH, "request_id": "4" * 32, "generation": 1}
    with pytest.raises(ValueError):
        session.authorize_hierarchy_payload_read(user_id=user_id, uri=uri, control=control)
    if user_id == "0":
        assert client._valid_hierarchy_uri(uri, control) is False
    else:
        assert re.fullmatch(r"[0-9]+", user_id) is None


@pytest.mark.parametrize(
    "command",
    [
        ["shell", "-T", "content", "write", "--user", "0", "--uri", f"content://{PROVIDER_AUTHORITY}/v1/x"],
        ["shell", "-T", "content", "call", "--user", "0", "--uri", f"content://{PROVIDER_AUTHORITY}/v1/x"],
        ["shell", "-T", "content", "read", "--user", "0", "--uri", "content://other.provider/v1/x"],
        ["shell", "-T", "content", "read", "--user", "0", "--uri", f"content://{PROVIDER_AUTHORITY}/v1/x"],
        ["shell", "-T", "content", "read", "--user", "0", "--uri", f"content://{PROVIDER_AUTHORITY}/v1/x", "extra"],
        ["shell", "content", "read", "--user", "0", "--uri", f"content://{PROVIDER_AUTHORITY}/v1/x"],
        ["shell", "rm", "-rf", "/data/local/tmp"],
    ],
)
def test_unapproved_shell_and_content_commands_are_blocked_with_terminal_audit(tmp_path, command):
    _, session = _client_and_session(tmp_path)
    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(command)
    rows = _audit(session)
    assert rows[-1]["event"] == "INTERNAL_TRAVERSAL_TERMINAL"
    assert rows[-1]["blocked_operation_dispatched"] is False


@pytest.mark.parametrize(
    "command",
    [
        _broadcast("CLICK_TARGET", "--es", "targetId", "plugin_more_options"),
        _broadcast("CLICK_TARGET", "--es", "targetId", "shmBannerAwayButton"),
        _broadcast("SET_SYSTEM_LANGUAGE"),
        _broadcast("SMART_NEXT"),
        _broadcast("HIERARCHY_TRANSFER_ARBITRARY"),
    ],
)
def test_ui_focus_security_and_unknown_broadcasts_remain_blocked(tmp_path, command):
    _, session = _client_and_session(tmp_path)
    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(command)
    rows = _audit(session)
    assert rows[-1]["event"] == "INTERNAL_TRAVERSAL_TERMINAL"
    assert rows[-1]["blocked_operation_dispatched"] is False


def test_normal_default_dump_reaches_ack_through_actual_adb_guard(tmp_path, monkeypatch):
    assert DEFAULT_HIERARCHY_TRANSPORT_MODE == "RELIABLE_FILE_PFD"
    client, session = _client_and_session(tmp_path)
    state = _install_device_responses(monkeypatch, client)

    result = client.dump_hierarchy(expected_helper_build_identity=_expected_identity())

    assert result["success"] is True
    assert client.last_hierarchy_metadata["transportMode"] == "RELIABLE_FILE_PFD"
    assert state["actions"] == ["CAPABILITIES", "START", "STATUS", "STATUS", "ACK"]
    rows = _audit(session)
    allowed_commands = [row["command"] for row in rows if row["event"] == "COMMAND_ALLOWED"]
    actions = [command[4].removeprefix(HELPER_ACTION_PREFIX) for command in allowed_commands
               if command[:3] == ["shell", "am", "broadcast"]]
    assert actions == [
        "HIERARCHY_TRANSFER_CAPABILITIES", "HIERARCHY_TRANSFER_START",
        "HIERARCHY_TRANSFER_STATUS", "HIERARCHY_TRANSFER_STATUS", "HIERARCHY_TRANSFER_ACK",
    ]
    assert [command[1:] for command in allowed_commands if command[:1] == ["shell"]
            and command[1:3] == ["am", "get-current-user"]] == [["am", "get-current-user"]]
    content_reads = [command for command in allowed_commands if command[:2] == ["shell", "-T"]]
    assert len(content_reads) == 1
    assert content_reads[0][2:6] == ["content", "read", "--user", "0"]
    assert content_reads[0][6] == "--uri"
    assert not any(row["event"] in {"COMMAND_BLOCKED", "SAFETY_STOP", "INTERNAL_TRAVERSAL_TERMINAL"}
                   for row in rows)


def test_missing_candidate_capability_stops_before_start_without_legacy_fallback(tmp_path, monkeypatch):
    client, _session = _client_and_session(tmp_path)
    state = _install_device_responses(monkeypatch, client, candidate_capability=False)
    client._logcat_reader.dump_raw_filtered = lambda **_kwargs: pytest.fail(
        "missing candidate capability must not fall back to logcat"
    )

    with pytest.raises(HierarchyTransportError, match="CANDIDATE_CAPABILITY_REQUIRED"):
        client.dump_hierarchy(expected_helper_build_identity=_expected_identity())

    assert state["actions"] == ["CAPABILITIES"]


@pytest.mark.parametrize(
    ("failure", "expected_reason", "expect_cancel"),
    [
        ("content_read", "ADB_EXECUTABLE_NOT_FOUND", True),
        ("status", "CAPTURE_FAILED", True),
        ("ack", "ACK_REJECTED", True),
    ],
)
def test_downstream_failures_fail_closed_and_cancel_when_budget_remains(
    tmp_path, monkeypatch, failure, expected_reason, expect_cancel
):
    client, session = _client_and_session(tmp_path)
    state = _install_device_responses(monkeypatch, client, failure=failure)

    with pytest.raises(HierarchyTransportError) as raised:
        client.dump_hierarchy(expected_helper_build_identity=_expected_identity())

    assert getattr(raised.value, "reason", None) == expected_reason
    assert ("CANCEL" in state["actions"]) is expect_cancel
    assert "ACK" not in state["actions"] or failure == "ack"
    rows = _audit(session)
    assert not any(row["event"] in {"SAFETY_STOP", "INTERNAL_TRAVERSAL_TERMINAL"} for row in rows)


def test_exhausted_deadline_does_not_send_immediate_cancel_and_preserves_failure(tmp_path, monkeypatch):
    client, session = _client_and_session(tmp_path)
    state = _install_device_responses(monkeypatch, client, failure="content_read")
    client._remaining_for_cleanup = lambda _deadline: 0.0

    with pytest.raises(HierarchyTransportError) as raised:
        client.dump_hierarchy(expected_helper_build_identity=_expected_identity())

    assert getattr(raised.value, "reason", None) == "ADB_EXECUTABLE_NOT_FOUND"
    assert "CANCEL" not in state["actions"]
    assert "ACK" not in state["actions"]


def test_malformed_ready_uri_fails_before_provider_read_and_preserves_cancel(tmp_path, monkeypatch):
    client, session = _client_and_session(tmp_path)
    state = _install_device_responses(monkeypatch, client, malformed_uri=True)

    with pytest.raises(HierarchyTransportError) as raised:
        client.dump_hierarchy(expected_helper_build_identity=_expected_identity())

    assert getattr(raised.value, "reason", None) == "PAYLOAD_URI_INVALID"
    assert "CANCEL" in state["actions"]
    assert not any(command[:2] == ["fake-adb", "-s"] and "-T" in command for command in state["commands"])


def test_optional_expansion_policy_is_unchanged():
    from tb_runner.run_spec import PREPOSITIONED, RunSpec

    assert RunSpec(entry_mode=PREPOSITIONED, scenario_ids=("life_home_monitor_plugin",)).optional_expansions == "DISABLED"
