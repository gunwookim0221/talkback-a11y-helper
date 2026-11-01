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
    validate_control_identity,
    validate_prestart_capability_generation,
    validate_request_generation,
)
from talkback_lib.reliable_hierarchy_schema import (
    CANDIDATE_CONTRACT_VERSION,
    CANDIDATE_SCHEMA_VERSION,
    RAW_SCHEMA_VERSION,
    capture_canonical_sha256,
    capture_root_id,
    CAPTURE_ENVELOPE_SCHEMA_VERSION,
    CAPTURE_CANONICALIZATION_VERSION,
    CAPTURE_ROOT_IDENTITY_VERSION,
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
    value = {
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
    }
    root_digest = capture_canonical_sha256(root)
    envelope = {
        "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "canonicalization": CAPTURE_CANONICALIZATION_VERSION,
        "request_id": request_id,
        "process_epoch": "process-epoch-1",
        "generation": 1,
        "service_instance_id": "service-uuid",
        "capture_sequence": 1,
        "root_ref": "windows[0].root",
        "root_digest": root_digest,
    }
    projection = value["traversalCandidates"]
    projection["source_root_digest"] = root_digest
    projection["rootCaptureId"] = capture_root_id(envelope)
    projection["candidate_digest"] = capture_canonical_sha256(projection)
    envelope["candidate_digest"] = projection["candidate_digest"]
    value["captureEnvelope"] = envelope
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _capabilities() -> dict:
    return {
        "payload_schema_version": PAYLOAD_SCHEMA,
        "supported_payload_schema_versions": [PAYLOAD_SCHEMA],
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "supported_candidate_schema_versions": [CANDIDATE_SCHEMA_VERSION],
        "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
        "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "supported_capture_envelope_schema_versions": [CAPTURE_ENVELOPE_SCHEMA_VERSION],
        "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
        "supported_capture_canonicalization_versions": [CAPTURE_CANONICALIZATION_VERSION],
        "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
        "supported_capture_root_id_versions": [CAPTURE_ROOT_IDENTITY_VERSION],
        "capabilities": ["content_provider_pfd", "service_hierarchy_v2", CANDIDATE_SCHEMA_VERSION,
                         CAPTURE_ENVELOPE_SCHEMA_VERSION, CAPTURE_CANONICALIZATION_VERSION,
                         CAPTURE_ROOT_IDENTITY_VERSION],
    }


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
        "capture_sequence": 1,
        "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
        "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
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
        "capture_sequence": 1,
        "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
        "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
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
        "source_state": identity["source_state"],
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
            capabilities=_capabilities(),
        )
        self.assertEqual(payload, decoded.payload_bytes)
        self.assertIn("🌱".encode("utf-8"), decoded.payload_bytes)
        self.assertEqual(request_id, decoded.payload["reqId"])
        self.assertLessEqual(len(artifact), MAX_ARTIFACT_BYTES)

    def test_dirty_candidate_identity_is_bound_through_control_and_payload(self):
        identity = _identity()
        identity["source_state"] = "DIRTY"
        artifact, control, expected, payload = _artifact_control("7" * 32, "8" * 32, identity)

        decoded = decode_artifact(
            artifact, control, expected_identity=expected,
            expected_request_id="7" * 32, expected_client_nonce="8" * 32,
            capabilities=_capabilities(),
        )
        self.assertEqual(payload, decoded.payload_bytes)
        validate_control_identity(control, expected)

        for field, wrong in (("input_digest", "f" * 64), ("source_state", "CLEAN")):
            with self.subTest(field=field):
                changed = dict(control)
                changed["helper_build_identity"] = dict(control["helper_build_identity"])
                changed["helper_build_identity"][field] = wrong
                with self.assertRaises(HierarchyTransportError):
                    validate_control_identity(changed, expected)

        incomplete = {key: value for key, value in expected.items() if key != "source_state"}
        with self.assertRaises(HierarchyTransportError):
            validate_control_identity(control, incomplete)

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

    def test_artifact_generation_zero_remains_invalid(self):
        request_id, nonce = "5" * 32, "6" * 32
        artifact, control, expected, payload = _artifact_control(request_id, nonce, _identity())
        header_size = struct.unpack(">I", artifact[len(MAGIC):len(MAGIC) + 4])[0]
        header_start = len(MAGIC) + 12
        header = json.loads(artifact[header_start:header_start + header_size])
        header["generation"] = 0
        changed_artifact = encode_artifact(header, payload)
        changed_control = {
            **control,
            "generation": 0,
            "artifact_bytes": len(changed_artifact),
            "artifact_sha256": sha256_hex(changed_artifact),
        }

        with self.assertRaisesRegex(HierarchyTransportError, "GENERATION_INVALID"):
            decode_artifact(
                changed_artifact,
                changed_control,
                expected_identity=expected,
                expected_request_id=request_id,
                expected_client_nonce=nonce,
            )

    def test_request_generation_requires_positive_non_boolean_integer(self):
        for generation in (0, None, -1, True, "1"):
            with self.subTest(generation=generation), self.assertRaisesRegex(
                HierarchyTransportError, "GENERATION_INVALID"
            ):
                validate_request_generation({"generation": generation}, request_id="request-1")
        self.assertEqual(1, validate_request_generation({"generation": 1}, request_id="request-1"))

    def test_prestart_capability_generation_requires_explicit_nonnegative_integer(self):
        for generation in (0, 1, 8):
            with self.subTest(generation=generation):
                self.assertEqual(
                    generation,
                    validate_prestart_capability_generation({"generation": generation}, request_id="request-1"),
                )
        for value in ({}, {"generation": None}, {"generation": -1}, {"generation": "0"}, {"generation": True}):
            with self.subTest(value=value), self.assertRaisesRegex(
                HierarchyTransportError, "CAPABILITY_GENERATION_INVALID"
            ):
                validate_prestart_capability_generation(value, request_id="request-1")

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

    def test_explicit_zero_generation_parses_as_zero_without_coercion(self):
        nonce = "b" * 32
        body = {
            "schema": CONTROL_SCHEMA,
            "protocol_version": PROTOCOL_VERSION,
            "status": "OK",
            "query_nonce": nonce,
            "request_id": None,
            "generation": 0,
        }
        decoded = decode_control_reply(
            f'Broadcast completed: result=1, data="{encode_control(body)}"'
        )
        self.assertIs(type(decoded["generation"]), int)
        self.assertEqual(0, decoded["generation"])

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

    def test_existing_build_compatibility_precheck_is_mandatory(self):
        expected = validate_expected_build_precheck({
            "status": "EXACT_MATCH",
            "execution_allowed": True,
            "helper_build_id": "c" * 64,
            "helper_git_commit": "d" * 40,
            "helper_service_instance_id": "service-id",
            "helper_input_digest": "f" * 64,
            "installed_metadata": {"source_state": "DIRTY"},
        })
        self.assertEqual("c" * 64, expected["build_id"])
        self.assertEqual("f" * 64, expected["input_digest"])
        self.assertEqual("DIRTY", expected["source_state"])
        with self.assertRaises(HierarchyTransportError):
            validate_expected_build_precheck({"status": "REBUILD_REQUIRED", "execution_allowed": False})

    def test_missing_source_state_identity_fails_closed(self):
        with self.assertRaises(HierarchyTransportError) as caught:
            validate_expected_build_precheck({
                "status": "EXACT_MATCH", "execution_allowed": True,
                "helper_build_id": "c" * 64, "helper_git_commit": "d" * 40,
                "helper_service_instance_id": "service-id", "helper_input_digest": "f" * 64,
                "installed_metadata": {},
            })
        self.assertEqual("BUILD_IDENTITY_PRECHECK_INVALID", caught.exception.reason)


class HierarchyClientIntegrationTests(unittest.TestCase):
    def _client(self):
        from talkback_lib import A11yAdbClient

        return A11yAdbClient(start_monitor=False)

    def test_reliable_mode_reads_binary_file(self):
        client = self._client()
        request_id, nonce = "" , ""
        identity = _identity()
        identity["source_state"] = "DIRTY"
        artifact, template_ready, expected, payload_bytes = _artifact_control("1" * 32, "2" * 32, identity)
        process_epoch = template_ready["process_epoch"]
        helper_control = template_ready["helper_build_identity"]
        token = "e" * 32
        actions: list[str] = []
        start_pairs: dict[str, str] = {}

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
                    "generation": 0,
                    "process_epoch": process_epoch,
                    "service_instance_id": identity["service_instance_id"],
                    "helper_build_identity": helper_control,
                    "payload_schema_version": PAYLOAD_SCHEMA,
                    "supported_payload_schema_versions": [PAYLOAD_SCHEMA],
                    "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
                    "supported_candidate_schema_versions": [CANDIDATE_SCHEMA_VERSION],
                    "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
                    "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
                    "supported_capture_envelope_schema_versions": [CAPTURE_ENVELOPE_SCHEMA_VERSION],
                    "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
                    "supported_capture_canonicalization_versions": [CAPTURE_CANONICALIZATION_VERSION],
                    "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
                    "supported_capture_root_id_versions": [CAPTURE_ROOT_IDENTITY_VERSION],
                    "max_payload_bytes": MAX_PAYLOAD_BYTES,
                    "capabilities": ["content_provider_pfd", "service_hierarchy_v2", CANDIDATE_SCHEMA_VERSION,
                                     CAPTURE_ENVELOPE_SCHEMA_VERSION, CAPTURE_CANONICALIZATION_VERSION,
                                     CAPTURE_ROOT_IDENTITY_VERSION],
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
                "capture_sequence": 1,
                "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
                "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
                "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
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
            if action.endswith("HIERARCHY_TRANSFER_START"):
                pairs = {extras[i + 1]: extras[i + 2] for i in range(0, len(extras or []) - 2, 3) if extras[i] == "--es"}
                start_pairs.update(pairs)
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
                "status": "COMPATIBLE_SAME_HELPER_INPUT",
                "execution_allowed": True,
                "helper_build_id": identity["build_id"],
                "helper_git_commit": identity["git_commit"],
                "helper_service_instance_id": identity["service_instance_id"],
                "helper_input_digest": identity["input_digest"],
                "installed_metadata": {"source_state": identity["source_state"]},
            },
            hierarchy_diagnostic_context={
                "run_id": "trace-run-1",
                "scenario_id": "trace-scenario-2",
                "step": 3,
            },
        )
        self.assertEqual(request_id, result["reqId"])
        self.assertEqual("RELIABLE_FILE_PFD", client.last_hierarchy_metadata["transportMode"])
        self.assertTrue(any(action.endswith("HIERARCHY_TRANSFER_START") for action in actions))
        self.assertEqual(identity["input_digest"], start_pairs["expectedInputDigest"])
        self.assertEqual("DIRTY", start_pairs["expectedSourceState"])
        self.assertEqual("trace-run-1", start_pairs["hierarchyDiagnosticRunId"])
        self.assertEqual("trace-scenario-2", start_pairs["hierarchyDiagnosticScenarioId"])
        self.assertEqual("3", start_pairs["hierarchyDiagnosticStep"])
        self.assertTrue(any(action.endswith("HIERARCHY_TRANSFER_ACK") for action in actions))
        self.assertFalse(any(action.endswith("DUMP_HIERARCHY") for action in actions))
        stages = [record["stage"] for record in client.last_hierarchy_transport_diagnostics]
        self.assertIn("HOST_CONTROL_SEND", stages)
        self.assertIn("HOST_CONTROL_REPLY_RECEIVED", stages)
        self.assertIn("HOST_CONTROL_FRAME_PARSED", stages)
        correlation_events = [record for record in client.last_hierarchy_transport_diagnostics if record["stage"] == "HOST_CONTROL_CORRELATION_VALIDATED"]
        self.assertTrue(correlation_events)
        self.assertTrue(all(event["query_nonce"] == event["response_query_nonce"] for event in correlation_events))
        self.assertIn("HOST_ARTIFACT_SIZE_DIGEST_VALIDATED", stages)
        self.assertIn("HOST_ARTIFACT_SCHEMA_CURRENTNESS_VALIDATED", stages)
        self.assertIn("HOST_HIERARCHY_SNAPSHOT_COMPLETE", stages)
        self.assertTrue(all(record["request_id"] == result["reqId"] for record in client.last_hierarchy_transport_diagnostics))
        self.assertTrue(all(record["run_id"] == "trace-run-1" for record in client.last_hierarchy_transport_diagnostics))

        from unittest import mock
        with mock.patch("talkback_lib.time.monotonic_ns", side_effect=OSError("diagnostic clock unavailable")):
            result_when_trace_fails = client.dump_hierarchy(
                transport_mode="RELIABLE_FILE_PFD",
                expected_helper_build_identity={
                    "status": "COMPATIBLE_SAME_HELPER_INPUT",
                    "execution_allowed": True,
                    "helper_build_id": identity["build_id"],
                    "helper_git_commit": identity["git_commit"],
                    "helper_service_instance_id": identity["service_instance_id"],
                    "helper_input_digest": identity["input_digest"],
                    "installed_metadata": {"source_state": identity["source_state"]},
                },
                hierarchy_diagnostic_context={"run_id": "trace-run-1"},
            )
        self.assertTrue(result_when_trace_fails["success"])
        self.assertEqual([], client.last_hierarchy_transport_diagnostics)

    def test_reliable_mode_rejects_zero_generation_on_accepted_start(self):
        client = self._client()
        identity = _identity()
        process_epoch = "process-epoch-1"
        actions: list[str] = []
        expected_build = {
            "status": "COMPATIBLE_SAME_HELPER_INPUT",
            "execution_allowed": True,
            "helper_build_id": identity["build_id"],
            "helper_git_commit": identity["git_commit"],
            "helper_service_instance_id": identity["service_instance_id"],
            "helper_input_digest": identity["input_digest"],
            "installed_metadata": {"source_state": identity["source_state"]},
        }

        def broadcast(_dev, action, extras=None, *, timeout=30.0):
            actions.append(action)
            pairs = {
                extras[index + 1]: extras[index + 2]
                for index in range(0, len(extras or []) - 2, 3)
                if extras[index] == "--es"
            }
            query_nonce = pairs["queryNonce"]
            shared = {
                "schema": CONTROL_SCHEMA,
                "protocol_version": PROTOCOL_VERSION,
                "query_nonce": query_nonce,
                "process_epoch": process_epoch,
                "service_instance_id": identity["service_instance_id"],
                "helper_build_identity": {
                    key: value for key, value in identity.items() if key != "service_instance_id"
                },
                "payload_schema_version": PAYLOAD_SCHEMA,
                "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
                "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
                "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
            }
            if action.endswith("CAPABILITIES"):
                shared.update(
                    status="OK",
                    request_id=None,
                    generation=0,
                    completed=True,
                    payload_complete=True,
                    supported_payload_schema_versions=[PAYLOAD_SCHEMA],
                    candidate_schema_version=CANDIDATE_SCHEMA_VERSION,
                    supported_candidate_schema_versions=[CANDIDATE_SCHEMA_VERSION],
                    candidate_contract_version=CANDIDATE_CONTRACT_VERSION,
                    capture_envelope_schema_version=CAPTURE_ENVELOPE_SCHEMA_VERSION,
                    supported_capture_envelope_schema_versions=[CAPTURE_ENVELOPE_SCHEMA_VERSION],
                    capture_canonicalization_version=CAPTURE_CANONICALIZATION_VERSION,
                    supported_capture_canonicalization_versions=[CAPTURE_CANONICALIZATION_VERSION],
                    capture_root_id_version=CAPTURE_ROOT_IDENTITY_VERSION,
                    supported_capture_root_id_versions=[CAPTURE_ROOT_IDENTITY_VERSION],
                    max_payload_bytes=MAX_PAYLOAD_BYTES,
                    capabilities=["content_provider_pfd", "service_hierarchy_v2", CANDIDATE_SCHEMA_VERSION,
                                  CAPTURE_ENVELOPE_SCHEMA_VERSION, CAPTURE_CANONICALIZATION_VERSION,
                                  CAPTURE_ROOT_IDENTITY_VERSION],
                )
            elif action.endswith("START"):
                shared.update(
                    status="ACCEPTED",
                    request_id=pairs["requestId"],
                    client_nonce=pairs["clientNonce"],
                    generation=0,
                    completed=False,
                    payload_complete=False,
                )
            elif action.endswith("CANCEL"):
                shared.update(
                    status="CANCELLED",
                    request_id=pairs["requestId"],
                    client_nonce=pairs["clientNonce"],
                    generation=1,
                    completed=True,
                )
            else:
                self.fail(f"unexpected transport action: {action}")
            encoded = encode_control(shared)
            return f'Broadcasting: Intent {{}}\nBroadcast completed: result=1, data="{encoded}"'

        client._broadcast = broadcast
        with self.assertRaisesRegex(HierarchyTransportError, "GENERATION_INVALID"):
            client.dump_hierarchy(
                transport_mode="RELIABLE_FILE_PFD",
                expected_helper_build_identity=expected_build,
            )

        self.assertTrue(actions[0].endswith("HIERARCHY_TRANSFER_CAPABILITIES"))
        self.assertTrue(actions[1].endswith("HIERARCHY_TRANSFER_START"))
        self.assertNotIn("HIERARCHY_TRANSFER_STATUS", " ".join(actions))

    def test_reliable_mode_rejects_missing_prestart_generation_before_start(self):
        client = self._client()
        identity = _identity()
        actions: list[str] = []
        expected_build = {
            "status": "COMPATIBLE_SAME_HELPER_INPUT",
            "execution_allowed": True,
            "helper_build_id": identity["build_id"],
            "helper_git_commit": identity["git_commit"],
            "helper_service_instance_id": identity["service_instance_id"],
            "helper_input_digest": identity["input_digest"],
            "installed_metadata": {"source_state": identity["source_state"]},
        }

        def broadcast(_dev, action, extras=None, *, timeout=30.0):
            actions.append(action)
            pairs = {
                extras[index + 1]: extras[index + 2]
                for index in range(0, len(extras or []) - 2, 3)
                if extras[index] == "--es"
            }
            response = {
                "schema": CONTROL_SCHEMA,
                "protocol_version": PROTOCOL_VERSION,
                "status": "OK",
                "request_id": None,
                "query_nonce": pairs["queryNonce"],
                "process_epoch": "process-epoch-1",
                "service_instance_id": identity["service_instance_id"],
                "helper_build_identity": {
                    key: value for key, value in identity.items() if key != "service_instance_id"
                },
                "payload_schema_version": PAYLOAD_SCHEMA,
            }
            encoded = encode_control(response)
            return f'Broadcasting: Intent {{}}\nBroadcast completed: result=1, data="{encoded}"'

        client._broadcast = broadcast
        with self.assertRaisesRegex(HierarchyTransportError, "CAPABILITY_GENERATION_INVALID"):
            client.dump_hierarchy(
                transport_mode="RELIABLE_FILE_PFD",
                expected_helper_build_identity=expected_build,
            )

        self.assertEqual(1, len(actions))
        self.assertTrue(actions[0].endswith("HIERARCHY_TRANSFER_CAPABILITIES"))

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
                "process_epoch": "process-epoch-1",
                "generation": 7,
                "completed": True,
            }
            return f'Broadcast completed: result=1, data="{encode_control(response)}"'

        client._broadcast = broadcast
        client._cancel_hierarchy_transfer(None, request_id, client_nonce, 1.0,
                                          expected_process_epoch="process-epoch-1", expected_generation=7)
        self.assertEqual(request_id, observed["requestId"])
        self.assertEqual(client_nonce, observed["clientNonce"])
        self.assertEqual("process-epoch-1", observed["expectedProcessEpoch"])
        self.assertEqual("7", observed["expectedGeneration"])
        self.assertEqual("CANCELLED", client.last_hierarchy_cleanup_diagnostic["status"])
        self.assertRegex(observed["queryNonce"], r"^[0-9a-f]{32}$")

    def test_cancel_without_confirmed_start_binding_fails_closed(self):
        client = self._client()
        client._broadcast = lambda *_args, **_kwargs: self.fail("unbound cancel must not be sent")
        client._cancel_hierarchy_transfer(None, "d" * 32, "e" * 32, 1.0)
        self.assertEqual("SKIPPED", client.last_hierarchy_cleanup_diagnostic["status"])
        self.assertEqual("CLEANUP_BINDING_UNAVAILABLE", client.last_hierarchy_cleanup_diagnostic["error_code"])

    def test_default_mode_is_reliable_and_auto_prechecks_build_identity(self):
        client = self._client()
        identity = {
            "status": "EXACT_MATCH",
            "execution_allowed": True,
            "helper_build_id": "a" * 64,
            "helper_git_commit": "b" * 40,
            "helper_service_instance_id": "service-instance",
            "helper_input_digest": "c" * 64,
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
            "status": "EXACT_MATCH",
            "execution_allowed": True,
            "helper_build_id": "a" * 64,
            "helper_git_commit": "b" * 40,
            "helper_service_instance_id": "service-instance",
            "helper_input_digest": "c" * 64,
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



class BuildIdentityPrecheckDiagnosticTests(unittest.TestCase):
    SERVICE = "raw-service-id-sentinel"
    NONCE = "raw-nonce-sentinel"
    PII = "private-window-title-sentinel"

    def _projection(self, ping_build="b" * 64, cap_build="b" * 64):
        from talkback_lib.exact_node_protocol import PROTOCOL_VERSION as helper_protocol
        fields = {
            "build_id": ping_build, "git_commit": "c" * 40, "input_digest": "d" * 64,
            "source_state": "CLEAN", "build_variant": "debug",
        }
        cap_fields = dict(fields)
        cap_fields["build_id"] = cap_build
        return {
            "sources": {
                "PING": {
                    "available": True, "build_identity": fields,
                    "schema_protocol_fields": {
                        "schema_version": "1", "helper_protocol_version": helper_protocol,
                        "version_name": "1.0", "version_code": 1, "gradle_version": "9.0.0",
                    },
                    "service_identity_present": True,
                },
                "CAPABILITIES": {
                    "available": True, "build_identity": cap_fields,
                    "schema_protocol_fields": {
                        "control_schema": CONTROL_SCHEMA, "protocol_version": PROTOCOL_VERSION,
                        "payload_schema_version": RAW_SCHEMA_VERSION,
                        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
                        "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
                    },
                    "generation": 3, "service_identity_present": True,
                    "service_instance_id": self.SERVICE, "nonce": self.NONCE, "raw_payload": self.PII,
                },
            },
            "field_comparisons": {
                "build_id": "MATCH" if ping_build == cap_build else "MISMATCH",
                "git_commit": "MATCH", "input_digest": "MATCH", "source_state": "MATCH",
                "build_variant": "MATCH", "service_instance_id": "MATCH",
            },
            "unexpected": self.PII,
        }

    def _context(self, *, build_id="b" * 64, git_commit="c" * 40, input_digest="d" * 64,
                 projection=None):
        from talkback_lib.exact_node_protocol import PROTOCOL_VERSION as helper_protocol
        return {
            "source_projection": projection or self._projection(),
            "expected_local_manifest": {
                "build_id": build_id, "git_commit": git_commit, "input_digest": input_digest,
                "source_state": "CLEAN", "build_variant": "debug", "gradle_version": "9.0.0",
                "version_name": "1.0", "version_code": 1, "java_version": "private",
                "helper_input_files": ["private/path"],
            },
            "expected_schemas": {
                "helper_build_identity_schema": "1", "helper_protocol": helper_protocol,
                "control_schema": CONTROL_SCHEMA, "transport_protocol": PROTOCOL_VERSION,
                "raw_hierarchy_schema": RAW_SCHEMA_VERSION, "candidate_schema": CANDIDATE_SCHEMA_VERSION,
                "candidate_contract": CANDIDATE_CONTRACT_VERSION, "extra": self.PII,
            },
        }

    def _value(self, **changes):
        value = {
            "status": "EXACT_MATCH", "compatibility_status": "EXACT_MATCH", "execution_allowed": True,
            "reason": "EXACT_BUILD_PROVENANCE_MATCH",
            "expected_helper_build_id": "b" * 64, "helper_build_id": "b" * 64,
            "expected_git_commit": "c" * 40, "helper_git_commit": "c" * 40,
            "expected_helper_input_digest": "d" * 64, "helper_input_digest": "d" * 64,
            "helper_service_instance_id": self.SERVICE,
            "installed_metadata": {"source_state": "CLEAN"},
            "request_nonce": self.NONCE, "raw_payload": self.PII,
            "arbitrary_exception_text": self.PII,
        }
        value.update(changes)
        return value

    def test_matching_return_and_sink_failure_preserve_gate_behavior(self):
        value = self._value()
        context = self._context()
        baseline = validate_expected_build_precheck(value)
        records = []
        with_sink = validate_expected_build_precheck(
            value, diagnostic_sink=records.append, diagnostic_context=context
        )

        def failing_serialization_sink(record):
            json.dumps({"record": record, "unsupported": object()})

        with_failing_sink = validate_expected_build_precheck(
            value, diagnostic_sink=failing_serialization_sink, diagnostic_context=context
        )
        self.assertEqual(baseline, with_sink)
        self.assertEqual(baseline, with_failing_sink)
        record = records[0]
        self.assertEqual("PASS", record["decision"])
        self.assertEqual("EXACT_MATCH", record["precheck_status"])
        self.assertEqual("EXACT_BUILD_PROVENANCE_MATCH", record["precheck_reason"])
        self.assertEqual("MATCH", record["field_comparisons"]["source_state"])
        self.assertEqual("MATCH", record["field_comparisons"]["build_variant"])
        self.assertEqual("MATCH", record["field_comparisons"]["version_name"])
        self.assertTrue(all(outcome == "MATCH" for outcome in record["schema_comparisons"].values()))

    def test_rejection_behavior_is_identical_with_disabled_working_and_failing_sinks(self):
        value = self._value(
            status="REBUILD_REQUIRED", compatibility_status="REBUILD_REQUIRED", execution_allowed=False,
            reason="HELPER_VERSION_MISMATCH", expected_helper_build_id="a" * 64,
        )
        context = self._context(build_id="a" * 64)
        def outcome(sink):
            try:
                validate_expected_build_precheck(value, diagnostic_sink=sink, diagnostic_context=context)
            except HierarchyTransportError as error:
                return type(error), error.reason
            self.fail("rejected precheck unexpectedly passed")

        disabled = outcome(None)
        records = []
        enabled = outcome(records.append)
        def failing_sink(_record):
            raise OSError("private sink failure")
        failed_sink = outcome(failing_sink)
        self.assertEqual(disabled, enabled)
        self.assertEqual(disabled, failed_sink)
        self.assertEqual((HierarchyTransportError, "BUILD_IDENTITY_COMPATIBILITY_REQUIRED"), disabled)
        self.assertEqual("HELPER_VERSION_MISMATCH", records[0]["precheck_reason"])

    def test_one_and_multiple_mismatches_keep_required_error_and_underlying_reason(self):
        cases = (
            ("a" * 64, "b" * 64, "c" * 40, "c" * 40, "d" * 64, "d" * 64, {"build_id"}),
            ("a" * 64, "b" * 64, "e" * 40, "c" * 40, "f" * 64, "d" * 64,
             {"build_id", "git_commit", "input_digest"}),
        )
        for expected_build, observed_build, expected_git, observed_git, expected_digest, observed_digest, mismatch in cases:
            with self.subTest(mismatch=mismatch):
                value = self._value(
                    status="REBUILD_REQUIRED", compatibility_status="REBUILD_REQUIRED", execution_allowed=False,
                    reason="HELPER_VERSION_MISMATCH",
                    expected_helper_build_id=expected_build, helper_build_id=observed_build,
                    expected_git_commit=expected_git, helper_git_commit=observed_git,
                    expected_helper_input_digest=expected_digest, helper_input_digest=observed_digest,
                )
                context = self._context(
                    build_id=expected_build, git_commit=expected_git, input_digest=expected_digest
                )
                records = []
                with self.assertRaises(HierarchyTransportError) as caught:
                    validate_expected_build_precheck(
                        value, diagnostic_sink=records.append, diagnostic_context=context
                    )
                self.assertEqual("BUILD_IDENTITY_COMPATIBILITY_REQUIRED", caught.exception.reason)
                record = records[0]
                self.assertEqual("BUILD_IDENTITY_COMPATIBILITY_REQUIRED", record["generic_code"])
                self.assertEqual("BUILD_IDENTITY_COMPATIBILITY_REQUIRED", record["transport_error_code"])
                self.assertEqual("REBUILD_REQUIRED", record["precheck_status"])
                self.assertEqual("HELPER_VERSION_MISMATCH", record["precheck_reason"])
                actual = {key for key, result in record["field_comparisons"].items() if result == "MISMATCH"}
                self.assertEqual(mismatch, actual)

    def test_missing_input_is_unknown_and_marks_unallocated_ids_unavailable(self):
        records = []
        with self.assertRaises(HierarchyTransportError) as caught:
            validate_expected_build_precheck(None, diagnostic_sink=records.append)
        self.assertEqual("BUILD_IDENTITY_COMPATIBILITY_REQUIRED", caught.exception.reason)
        record = records[0]
        self.assertEqual("UNKNOWN", record["precheck_status"])
        self.assertIsNone(record["precheck_reason"])
        self.assertEqual({}, record["expected_identity"])
        self.assertEqual({}, record["observed_identity"])
        self.assertFalse(record["request_identity"]["request_id_available"])
        self.assertFalse(record["request_identity"]["capture_sequence_available"])

    def test_sidecar_reject_leaves_client_authority_and_visit_state_unchanged(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from talkback_lib import A11yAdbClient
        from tb_runner.target_attempt_ledger import TargetAttemptLedger

        with tempfile.TemporaryDirectory(prefix="phase6d-precheck-") as temp:
            client = A11yAdbClient(start_monitor=False)
            ledger = TargetAttemptLedger(Path(temp) / "run.xlsx")
            ledger.entries = {"existing": {"state": "MATCHED", "workbook_rows": [3]}}
            client._target_attempt_ledger = ledger
            client._hierarchy_capture_sequence = 17
            client._last_hierarchy_capabilities = {"capture_sequence": 17, "authority_marker": "before"}
            client._last_hierarchy_transport_metadata = {"capture_sequence": 17, "authority_marker": "before"}
            client.last_hierarchy_metadata = {"captureSequence": 17, "captureAuthority": {"key": "before"}}
            client.last_hierarchy_cleanup_diagnostic = {"status": "KEEP_BEFORE"}
            snapshot = object()
            client._last_traversal_candidate_snapshot = snapshot
            before = {
                "capture_sequence": client._hierarchy_capture_sequence,
                "capabilities": dict(client._last_hierarchy_capabilities),
                "transport_metadata": dict(client._last_hierarchy_transport_metadata),
                "hierarchy_metadata": json.loads(json.dumps(client.last_hierarchy_metadata)),
                "cleanup": dict(client.last_hierarchy_cleanup_diagnostic),
                "ledger_entries": json.loads(json.dumps(ledger.entries)),
            }
            client._hierarchy_transfer_control = lambda *_args, **_kwargs: self.fail("rejected precheck dispatched")
            value = self._value(
                status="REBUILD_REQUIRED", compatibility_status="REBUILD_REQUIRED", execution_allowed=False,
                reason="HELPER_INPUT_DIGEST_MISMATCH", expected_helper_input_digest="f" * 64,
            )
            context = self._context(input_digest="f" * 64)
            with mock.patch("talkback_lib.uuid.uuid4") as uuid4:
                with self.assertRaises(HierarchyTransportError) as caught:
                    client._dump_hierarchy_file_pfd(
                        dev=None, wait_seconds=1.0, expected_helper_build_identity=value,
                        diagnostic_context=context,
                    )
            self.assertEqual("BUILD_IDENTITY_COMPATIBILITY_REQUIRED", caught.exception.reason)
            uuid4.assert_not_called()
            self.assertEqual(before["capture_sequence"], client._hierarchy_capture_sequence)
            self.assertEqual(before["capabilities"], client._last_hierarchy_capabilities)
            self.assertEqual(before["transport_metadata"], client._last_hierarchy_transport_metadata)
            self.assertEqual(before["hierarchy_metadata"], client.last_hierarchy_metadata)
            self.assertEqual(before["cleanup"], client.last_hierarchy_cleanup_diagnostic)
            self.assertIs(snapshot, client._last_traversal_candidate_snapshot)
            self.assertEqual(before["ledger_entries"], ledger.entries)

            sidecar = ledger.path.with_suffix(".build_identity_precheck.jsonl")
            serialized = sidecar.read_text(encoding="utf-8")
            record = json.loads(serialized)
            for secret in (self.SERVICE, self.NONCE, self.PII, "private/path"):
                self.assertNotIn(secret, serialized)
            self.assertEqual("HELPER_INPUT_DIGEST_MISMATCH", record["precheck_reason"])
            self.assertFalse(record["request_identity"]["request_id_available"])
            self.assertFalse(record["request_identity"]["capture_sequence_available"])
            self.assertEqual("MISMATCH", record["field_comparisons"]["input_digest"])
            self.assertEqual("MATCH", record["schema_comparisons"]["candidate_contract"])
            self.assertNotIn("visit_credit", record)
            self.assertNotIn("dispatch_authorized", record)

if __name__ == "__main__":
    unittest.main()
