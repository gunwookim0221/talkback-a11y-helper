from __future__ import annotations

import base64
import hashlib
import json
import struct
import unittest
import uuid

from talkback_lib.hierarchy_file_transport import (
    CONTROL_PREFIX,
    CONTROL_SCHEMA,
    DEFAULT_HIERARCHY_TRANSPORT_MODE,
    MAGIC,
    MAX_ARTIFACT_BYTES,
    MAX_CONTROL_JSON_BYTES,
    MAX_PAYLOAD_BYTES,
    PAYLOAD_SCHEMA,
    PROTOCOL_VERSION,
    PROVIDER_AUTHORITY,
    TRAILER,
    HierarchyTransportError,
    decode_artifact,
    decode_control_reply,
    encode_artifact,
    encode_control,
    sha256_hex,
    validate_expected_build_precheck,
)
from talkback_lib.reliable_hierarchy_schema import (
    CANDIDATE_CONTRACT_VERSION,
    CANDIDATE_SCHEMA_VERSION,
    RAW_SCHEMA_VERSION,
)


def _node(text: str = "상태 🌱\n줄") -> dict:
    return {
        "text": text,
        "contentDescription": None,
        "viewIdResourceName": None,
        "className": "android.widget.TextView",
        "packageName": "com.example",
        "windowId": 1,
        "boundsInScreen": {"l": -2, "t": 0, "r": 100, "b": 40},
        "clickable": False,
        "effectiveClickable": False,
        "enabled": True,
        "focusable": False,
        "focused": False,
        "inputFocused": False,
        "accessibilityFocused": False,
        "selected": False,
        "scrollable": False,
        "isScrollable": False,
        "checkable": False,
        "checked": False,
        "visibleToUser": True,
        "isVisibleToUser": True,
        "screenReaderFocusable": False,
        "rangeInfoPresent": False,
        "actions": [],
        "children": [],
    }


def _candidate(text: str = "상태 🌱\n줄") -> dict:
    return {
        "text": text,
        "contentDescription": None,
        "className": "android.widget.TextView",
        "viewIdResourceName": None,
        "boundsInScreen": {"l": -2, "t": 0, "r": 100, "b": 40},
        "clickable": False,
        "focusable": False,
        "isVisibleToUser": True,
        "focused": False,
        "accessibilityFocused": False,
        "isTopAppBar": False,
        "isBottomNavigationBar": False,
        "hasClickableDescendant": False,
        "hasFocusableDescendant": False,
        "effectiveClickable": False,
        "actionableDescendantResourceId": None,
        "actionableDescendantClassName": None,
        "actionableDescendantContentDescription": None,
    }


def _payload(request_id: str, node: dict | None = None) -> bytes:
    root = node or _node()
    candidate = _candidate()
    return json.dumps(
        {
            "reqId": request_id,
            "success": True,
            "schemaVersion": RAW_SCHEMA_VERSION,
            "platformApiLevel": 34,
            "traversalRootRef": "windows[0].root",
            "traversalRootWindowId": 1,
            "nodeCount": 1,
            "nodes": [root],
            "windows": [{"id": 1, "root": root}],
            "traversalCandidates": {
                "schema_version": CANDIDATE_SCHEMA_VERSION,
                "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
                "algorithmVersion": "2.76.3",
                "analyzerVersion": "1.11.1",
                "profileId": "oneconnect-traversal-policy",
                "profileVersion": "1.0.0",
                "completion": {"status": "COMPLETE", "complete": True, "candidate_count": 1},
                "traversalRootRef": "windows[0].root",
                "traversalRootWindowId": 1,
                "canScrollDown": False,
                "scrollAxisContract": "axis-v1",
                "candidates": [candidate],
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _identity() -> dict[str, str]:
    return {
        "build_id": "a" * 64,
        "git_commit": "b" * 40,
        "input_digest": "c" * 64,
        "source_state": "CLEAN",
        "build_variant": "debug",
        "service_instance_id": "service-uuid",
    }


def _artifact_control(request_id: str, nonce: str, identity: dict[str, str], payload: bytes | None = None):
    payload = payload if payload is not None else _payload(request_id)
    created_ns, completed_ns = 100, 200
    header = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "client_nonce": nonce,
        "process_epoch": "process-epoch-1",
        "generation": 1,
        "service_instance_id": identity["service_instance_id"],
        "helper_build_identity": {k: v for k, v in identity.items() if k != "service_instance_id"},
        "payload_schema_version": PAYLOAD_SCHEMA,
        "payload_bytes": len(payload),
        "payload_sha256": sha256_hex(payload),
        "created_elapsed_realtime_ns": created_ns,
        "completed_elapsed_realtime_ns": completed_ns,
    }
    artifact = encode_artifact(header, payload)
    control = {
        "schema": CONTROL_SCHEMA,
        "protocol_version": PROTOCOL_VERSION,
        "status": "READY",
        "request_id": request_id,
        "client_nonce": nonce,
        "process_epoch": header["process_epoch"],
        "generation": header["generation"],
        "service_instance_id": identity["service_instance_id"],
        "helper_build_identity": header["helper_build_identity"],
        "payload_schema_version": PAYLOAD_SCHEMA,
        "payload_complete": True,
        "completed": True,
        "payload_bytes": len(payload),
        "payload_sha256": header["payload_sha256"],
        "artifact_bytes": len(artifact),
        "artifact_sha256": sha256_hex(artifact),
        "completed_elapsed_realtime_ns": 201,
    }
    expected = {
        "build_id": identity["build_id"],
        "git_commit": identity["git_commit"],
        "input_digest": identity["input_digest"],
        "build_variant": identity["build_variant"],
        "service_instance_id": identity["service_instance_id"],
    }
    return artifact, control, expected, payload


class HierarchyEnvelopeTests(unittest.TestCase):
    def test_binary_envelope_round_trip_and_unicode_bytes_are_exact(self):
        request_id, nonce = "1" * 32, "2" * 32
        artifact, control, expected, payload = _artifact_control(request_id, nonce, _identity())
        decoded = decode_artifact(
            artifact,
            control,
            expected_identity=expected,
            expected_request_id=request_id,
            expected_client_nonce=nonce,
        )
        self.assertEqual(payload, decoded.payload_bytes)
        self.assertIn("🌱".encode("utf-8"), decoded.payload_bytes)
        self.assertEqual(request_id, decoded.payload["reqId"])
        self.assertLessEqual(len(artifact), MAX_ARTIFACT_BYTES)

    def test_rejects_truncation_extra_bytes_and_corrupt_footer(self):
        artifact, control, expected, _ = _artifact_control("3" * 32, "4" * 32, _identity())
        for changed in (artifact[:-1], artifact + b"x", artifact[:-1] + b"x"):
            with self.subTest(size=len(changed)):
                with self.assertRaises(HierarchyTransportError):
                    decode_artifact(changed, control, expected_identity=expected,
                                    expected_request_id="3" * 32, expected_client_nonce="4" * 32)

    def test_rejects_stale_request_nonce_generation_build_and_hash(self):
        artifact, control, expected, _ = _artifact_control("5" * 32, "6" * 32, _identity())
        mutations = [
            ({**control, "request_id": "7" * 32}, "5" * 32, "6" * 32, expected),
            ({**control, "client_nonce": "8" * 32}, "5" * 32, "6" * 32, expected),
            ({**control, "generation": 99}, "5" * 32, "6" * 32, expected),
            ({**control, "artifact_sha256": "0" * 64}, "5" * 32, "6" * 32, expected),
            (control, "5" * 32, "6" * 32, {**expected, "build_id": "d" * 64}),
            ({**control, "payload_complete": False}, "5" * 32, "6" * 32, expected),
        ]
        for changed, request_id, nonce, changed_expected in mutations:
            with self.subTest(changed=changed):
                with self.assertRaises(HierarchyTransportError):
                    decode_artifact(artifact, changed, expected_identity=changed_expected,
                                    expected_request_id=request_id, expected_client_nonce=nonce)

    def test_rejects_invalid_utf8_json_duplicate_keys_and_incomplete_tree(self):
        request_id, nonce, identity = "9" * 32, "a" * 32, _identity()
        for body in (
            b"\xff",
            (b'{"reqId":"' + request_id.encode() + b'","reqId":"' + request_id.encode() + b'"}'),
            json.dumps({"reqId": request_id, "success": True, "schemaVersion": PAYLOAD_SCHEMA,
                        "nodeCount": 1, "nodes": [{"children": []}], "windows": []}).encode(),
        ):
            artifact, control, expected, _ = _artifact_control(request_id, nonce, identity, body)
            with self.subTest(body=body):
                with self.assertRaises(HierarchyTransportError):
                    decode_artifact(artifact, control, expected_identity=expected,
                                    expected_request_id=request_id, expected_client_nonce=nonce)

    def test_rejects_header_control_schema_disagreement(self):
        request_id, nonce = "f" * 32, "0" * 32
        artifact, control, expected, payload = _artifact_control(request_id, nonce, _identity())
        header_size = struct.unpack(">I", artifact[len(MAGIC):len(MAGIC) + 4])[0]
        header_start = len(MAGIC) + 12
        header = json.loads(artifact[header_start:header_start + header_size])
        header["payload_schema_version"] = "unexpected-schema"
        changed = encode_artifact(header, payload)
        changed_control = {
            **control,
            "artifact_bytes": len(changed),
            "artifact_sha256": sha256_hex(changed),
        }
        with self.assertRaises(HierarchyTransportError):
            decode_artifact(
                changed,
                changed_control,
                expected_identity=expected,
                expected_request_id=request_id,
                expected_client_nonce=nonce,
            )

    def test_size_cap_rejects_before_building_envelope(self):
        with self.assertRaisesRegex(HierarchyTransportError, "PAYLOAD_TOO_LARGE"):
            encode_artifact({"request_id": "x"}, b"x" * (MAX_PAYLOAD_BYTES + 1))


class HierarchyControlTests(unittest.TestCase):
    def test_ordered_control_reply_requires_one_bounded_prefixed_result(self):
        nonce = "b" * 32
        body = {"schema": CONTROL_SCHEMA, "protocol_version": PROTOCOL_VERSION, "status": "OK", "query_nonce": nonce}
        encoded = encode_control(body)
        self.assertTrue(encoded.startswith(CONTROL_PREFIX))
        decoded = decode_control_reply(f'Broadcasting: Intent {{}}\nBroadcast completed: result=1, data="{encoded}"')
        self.assertEqual(nonce, decoded["query_nonce"])

    def test_ordered_control_error_preserves_structured_failure_and_requires_matching_result(self):
        failure = {
            "schema": CONTROL_SCHEMA,
            "protocol_version": PROTOCOL_VERSION,
            "status": "FAILED",
            "error_code": "PAYLOAD_TOO_LARGE",
        }
        encoded = encode_control(failure)
        decoded = decode_control_reply(f'Broadcast completed: result=2, data="{encoded}"')
        self.assertEqual("PAYLOAD_TOO_LARGE", decoded["error_code"])
        with self.assertRaises(HierarchyTransportError):
            decode_control_reply(f'Broadcast completed: result=1, data="{encoded}"')

    def test_ordered_control_rejects_ambiguous_wrong_result_oversize_and_duplicate_json(self):
        encoded = encode_control({"schema": CONTROL_SCHEMA, "protocol_version": PROTOCOL_VERSION, "status": "OK"})
        cases = (
            f'Broadcast completed: result=0, data="{encoded}"',
            f'Broadcast completed: result=1, data="{encoded}"\nBroadcast completed: result=1, data="{encoded}"',
            "Broadcast completed: result=1",
            "x" * (MAX_CONTROL_JSON_BYTES * 3),
        )
        for output in cases:
            with self.subTest(output=output[:35]), self.assertRaises(HierarchyTransportError):
                decode_control_reply(output)
        duplicate = base64.urlsafe_b64encode(
            b'{"schema":"hierarchy-transfer-control.v1","schema":"hierarchy-transfer-control.v1",'
            b'"protocol_version":"hierarchy-payload.v1"}'
        ).decode().rstrip("=")
        with self.assertRaises(HierarchyTransportError):
            decode_control_reply(f'Broadcast completed: result=1, data="{CONTROL_PREFIX}{duplicate}"')

    def test_existing_build_identity_match_is_mandatory(self):
        expected = validate_expected_build_precheck({
            "status": "MATCH",
            "helper_build_id": "c" * 64,
            "helper_git_commit": "d" * 40,
            "helper_service_instance_id": "service-id",
        })
        self.assertEqual("c" * 64, expected["build_id"])
        with self.assertRaises(HierarchyTransportError):
            validate_expected_build_precheck({"status": "MISMATCH"})


class HierarchyClientIntegrationTests(unittest.TestCase):
    def _client(self):
        from talkback_lib import A11yAdbClient

        return A11yAdbClient(start_monitor=False)

    def test_reliable_mode_reads_binary_file(self):
        client = self._client()
        request_id, nonce = "" , ""
        identity = _identity()
        artifact, template_ready, expected, payload_bytes = _artifact_control("1" * 32, "2" * 32, identity)
        process_epoch = template_ready["process_epoch"]
        helper_control = template_ready["helper_build_identity"]
        token = "e" * 32
        actions: list[str] = []

        def control_response(action: str, extras: list[str]) -> dict:
            nonlocal request_id, nonce, artifact, expected, payload_bytes
            pairs = {extras[i + 1]: extras[i + 2] for i in range(0, len(extras) - 2, 3) if extras[i] == "--es"}
            query_nonce = pairs["queryNonce"]
            if action.endswith("CAPABILITIES"):
                return {
                    "schema": CONTROL_SCHEMA,
                    "protocol_version": PROTOCOL_VERSION,
                    "status": "OK",
                    "query_nonce": query_nonce,
                    "process_epoch": process_epoch,
                    "service_instance_id": identity["service_instance_id"],
                    "helper_build_identity": helper_control,
                    "payload_schema_version": PAYLOAD_SCHEMA,
                    "supported_payload_schema_versions": [PAYLOAD_SCHEMA],
                    "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
                    "supported_candidate_schema_versions": [CANDIDATE_SCHEMA_VERSION],
                    "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
                    "max_payload_bytes": MAX_PAYLOAD_BYTES,
                    "capabilities": ["content_provider_pfd", "service_hierarchy_v2", CANDIDATE_SCHEMA_VERSION],
                }
            request_id = pairs["requestId"]
            nonce = pairs.get("clientNonce", "")
            artifact, _, expected, payload_bytes = _artifact_control(request_id, nonce, identity)
            shared = {
                "schema": CONTROL_SCHEMA,
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "client_nonce": nonce,
                "query_nonce": query_nonce,
                "process_epoch": process_epoch,
                "generation": 1,
                "service_instance_id": identity["service_instance_id"],
                "helper_build_identity": helper_control,
                "payload_schema_version": PAYLOAD_SCHEMA,
                "completed": True,
                "payload_complete": True,
                "payload_bytes": len(payload_bytes),
                "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "artifact_bytes": len(artifact),
                "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
                "created_elapsed_realtime_ns": 100,
                "completed_elapsed_realtime_ns": 201,
            }
            if action.endswith("START"):
                shared.update(status="ACCEPTED", completed=False, payload_complete=False)
            elif action.endswith("STATUS"):
                shared.update(
                    status="READY",
                    payload_uri=f"content://{PROVIDER_AUTHORITY}/v1/{process_epoch}/{request_id}/1/{token}",
                )
            elif action.endswith("ACK"):
                shared.update(status="ACKED")
            else:
                shared.update(status="CANCELLED")
            return shared

        def broadcast(_dev, action, extras=None, *, timeout=30.0):
            actions.append(action)
            encoded = encode_control(control_response(action, list(extras or [])))
            return f'Broadcasting: Intent {{}}\nBroadcast completed: result=1, data="{encoded}"'

        client._broadcast = broadcast
        client._run = lambda args, **_kwargs: "0"
        client._adb_device._run_adb_binary_command = lambda args, **kwargs: type(
            "BinaryResult", (), {"stdout": artifact, "stderr": b"", "stderr_truncated": False, "returncode": 0}
        )()
        result = client.dump_hierarchy(
            transport_mode="RELIABLE_FILE_PFD",
            expected_helper_build_identity={
                "status": "MATCH",
                "helper_build_id": identity["build_id"],
                "helper_git_commit": identity["git_commit"],
                "helper_service_instance_id": identity["service_instance_id"],
            },
        )
        self.assertEqual(request_id, result["reqId"])
        self.assertEqual("RELIABLE_FILE_PFD", client.last_hierarchy_metadata["transportMode"])
        self.assertTrue(any(action.endswith("HIERARCHY_TRANSFER_START") for action in actions))
        self.assertTrue(any(action.endswith("HIERARCHY_TRANSFER_ACK") for action in actions))
        self.assertFalse(any(action.endswith("DUMP_HIERARCHY") for action in actions))

    def test_reliable_mode_requires_match_before_any_transport_command(self):
        client = self._client()
        client._broadcast = lambda *_args, **_kwargs: self.fail("transport must not start")
        with self.assertRaises(HierarchyTransportError):
            client.dump_hierarchy(transport_mode="RELIABLE_FILE_PFD", expected_helper_build_identity={"status": "UNKNOWN"})

    def test_best_effort_cancel_has_a_fresh_correlated_query_nonce(self):
        client = self._client()
        request_id, client_nonce = "d" * 32, "e" * 32
        observed: dict[str, str] = {}

        def broadcast(_dev, _action, extras=None, *, timeout=30.0):
            pairs = {extras[i + 1]: extras[i + 2] for i in range(0, len(extras) - 2, 3) if extras[i] == "--es"}
            observed.update(pairs)
            response = {
                "schema": CONTROL_SCHEMA,
                "protocol_version": PROTOCOL_VERSION,
                "status": "CANCELLED",
                "request_id": request_id,
                "client_nonce": client_nonce,
                "query_nonce": pairs["queryNonce"],
            }
            return f'Broadcast completed: result=1, data="{encode_control(response)}"'

        client._broadcast = broadcast
        client._cancel_hierarchy_transfer(None, request_id, client_nonce, 1.0)
        self.assertEqual(request_id, observed["requestId"])
        self.assertEqual(client_nonce, observed["clientNonce"])
        self.assertRegex(observed["queryNonce"], r"^[0-9a-f]{32}$")

    def test_default_mode_is_reliable_and_auto_prechecks_build_identity(self):
        client = self._client()
        identity = {
            "status": "MATCH",
            "helper_build_id": "a" * 64,
            "helper_git_commit": "b" * 40,
            "helper_service_instance_id": "service-instance",
        }
        observed: dict[str, object] = {}

        def precheck(*, dev=None, acceptance_mode=True):
            observed["precheck"] = (dev, acceptance_mode)
            return identity

        def reliable(*, dev, wait_seconds, expected_helper_build_identity):
            observed["reliable"] = (dev, wait_seconds, expected_helper_build_identity)
            return {"success": True}

        client.precheck_helper_build_identity = precheck
        client._dump_hierarchy_file_pfd = reliable
        client._logcat_reader.dump_raw_filtered = lambda **_kwargs: self.fail(
            "default reliable path must not read legacy hierarchy payloads"
        )

        result = client.dump_hierarchy()

        self.assertEqual(DEFAULT_HIERARCHY_TRANSPORT_MODE, "RELIABLE_FILE_PFD")
        self.assertEqual({"success": True}, result)
        self.assertEqual((None, True), observed["precheck"])
        self.assertEqual((None, 30.0, identity), observed["reliable"])

    def test_default_reliable_failure_does_not_fallback_to_legacy_payload(self):
        client = self._client()
        client.precheck_helper_build_identity = lambda **_kwargs: {
            "status": "MATCH",
            "helper_build_id": "a" * 64,
            "helper_git_commit": "b" * 40,
            "helper_service_instance_id": "service-instance",
        }

        def reliable_failure(**_kwargs):
            raise HierarchyTransportError("PFD_FETCH_FAILED", "request-1")

        client._dump_hierarchy_file_pfd = reliable_failure
        client._logcat_reader.dump_raw_filtered = lambda **_kwargs: self.fail(
            "reliable failure must not invoke legacy hierarchy payload retrieval"
        )
        client._broadcast = lambda *_args, **_kwargs: self.fail(
            "reliable failure must not dispatch a legacy hierarchy request"
        )

        with self.assertRaisesRegex(HierarchyTransportError, "PFD_FETCH_FAILED"):
            client.dump_hierarchy()

    def test_explicit_legacy_debug_mode_remains_available(self):
        client = self._client()
        client.check_helper_status = lambda **_kwargs: False
        with self.assertRaisesRegex(RuntimeError, "SERVICE_UNAVAILABLE"):
            client.dump_hierarchy(transport_mode="LEGACY_LOGCAT")
        with self.assertRaises(ValueError):
            client.dump_hierarchy(transport_mode="SOME_UNKNOWN_MODE")


if __name__ == "__main__":
    unittest.main()
