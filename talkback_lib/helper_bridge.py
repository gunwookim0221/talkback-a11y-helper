#!/usr/bin/env python3
"""Helper APK broadcast 프로토콜 레이어."""

from __future__ import annotations

import time
import uuid
import threading
import re
from datetime import datetime, timezone
from collections import OrderedDict
from pathlib import Path
from typing import Any

from talkback_lib.adb_device import AdbCommandFailure

from talkback_lib.constants import (
    ACTION_GET_FOCUS,
    ACTION_EVIDENCE_EVENTS,
    ACTION_PING,
    ACTION_RESOLVE_EXACT_NODE,
    ACTION_NAVIGATION_ACTION,
    ACTION_SMART_NEXT,
    ACTION_FOCUS_IN_BOUNDS,
    ACTION_TARGET_FOCUS_COMMIT,
    RED_TEXT,
    RESET_TEXT,
    STATUS_FAILED,
    STATUS_LOOPED,
    STATUS_MOVED,
    STATUS_SCROLLED,
)
from talkback_lib.exact_node_protocol import (
    ExactNodeAck,
    ExactNodeRequest,
    OneShotRequestRegistry,
    ProtocolValidationError,
    canonical_json,
    helper_compatibility_allows_execution,
    precheck_repo_helper_build_identity,
    compute_repo_helper_build_identity,
    PROTOCOL_VERSION as EXACT_NODE_PROTOCOL_VERSION,
)


_DIAGNOSTIC_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DIAGNOSTIC_GIT = re.compile(r"^[0-9a-f]{40}$")
_DIAGNOSTIC_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
NAVIGATION_ACTIVATION_DIRECT_CLICK = "DIRECT_CLICK"
NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK = "EXACT_OWNER_FOCUS_THEN_CLICK"
NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK = (
    "DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK"
)


def _precheck_diagnostic_identity_projection(ping: Any, capabilities: Any) -> dict[str, Any]:
    ping_identity = ping.get("helper_build_identity") if isinstance(ping, dict) else None
    cap_identity = capabilities.get("helper_build_identity") if isinstance(capabilities, dict) else None

    def safe(field: str, value: Any) -> Any:
        if field in {"build_id", "input_digest"}:
            return value if isinstance(value, str) and _DIAGNOSTIC_HEX64.fullmatch(value) else None
        if field == "git_commit":
            return value if isinstance(value, str) and _DIAGNOSTIC_GIT.fullmatch(value) else None
        if field == "source_state":
            return value if isinstance(value, str) and value in {"CLEAN", "DIRTY"} else None
        if field in {"generation", "version_code"}:
            return value if type(value) is int and value >= 0 else None
        return value if isinstance(value, str) and _DIAGNOSTIC_TOKEN.fullmatch(value) else None

    def identity(raw: Any, aliases: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if isinstance(raw, dict):
            for field, source_key in aliases.items():
                value = safe(field, raw.get(source_key))
                if value is not None:
                    result[field] = value
        return result

    ping_fields = identity(ping_identity, {
        "build_id": "build_id", "git_commit": "git_commit", "input_digest": "helper_input_digest",
        "source_state": "source_state", "build_variant": "build_variant",
    })
    cap_fields = identity(cap_identity, {
        "build_id": "build_id", "git_commit": "git_commit", "input_digest": "input_digest",
        "source_state": "source_state", "build_variant": "build_variant",
    })
    ping_protocol = identity(ping_identity, {
        "schema_version": "schema_version", "helper_protocol_version": "helper_protocol_version",
        "version_name": "versionName", "version_code": "versionCode", "gradle_version": "gradle_version",
        "metadata_provenance": "metadata_provenance",
    })
    cap_protocol = identity(capabilities, {
        "control_schema": "schema", "protocol_version": "protocol_version",
        "payload_schema_version": "payload_schema_version", "candidate_schema_version": "candidate_schema_version",
        "candidate_contract_version": "candidate_contract_version",
    })
    ping_service = ping.get("helper_service_instance_id") if isinstance(ping, dict) else None
    cap_service = capabilities.get("service_instance_id") if isinstance(capabilities, dict) else None
    comparisons: dict[str, str] = {}
    for field in ("build_id", "git_commit", "input_digest", "source_state", "build_variant"):
        if field not in ping_fields or field not in cap_fields:
            comparisons[field] = "UNAVAILABLE"
        else:
            comparisons[field] = "MATCH" if ping_fields[field] == cap_fields[field] else "MISMATCH"
    comparisons["service_instance_id"] = (
        "UNAVAILABLE" if not isinstance(ping_service, str) or not ping_service
        or not isinstance(cap_service, str) or not cap_service
        else "MATCH" if ping_service == cap_service else "MISMATCH"
    )
    ping_source: dict[str, Any] = {
        "available": isinstance(ping, dict), "build_identity": ping_fields,
        "schema_protocol_fields": ping_protocol,
    }
    cap_source: dict[str, Any] = {
        "available": isinstance(capabilities, dict), "build_identity": cap_fields,
        "schema_protocol_fields": cap_protocol,
    }
    if isinstance(ping_service, str) and ping_service:
        ping_source["service_identity_present"] = True
    if isinstance(cap_service, str) and cap_service:
        cap_source["service_identity_present"] = True
    generation = safe("generation", capabilities.get("generation")) if isinstance(capabilities, dict) else None
    if generation is not None:
        cap_source["generation"] = generation
    return {
        "sources": {"PING": ping_source, "CAPABILITIES": cap_source},
        "field_comparisons": comparisons,
    }

def _precheck_diagnostic_context(
    root: Path,
    result: dict[str, Any],
    ping: Any,
    capabilities: Any,
) -> dict[str, Any]:
    projection = _precheck_diagnostic_identity_projection(ping, capabilities)
    try:
        local = compute_repo_helper_build_identity(root, variant="debug")
    except Exception:
        local = {}
    def prefer_result(result_key: str, local_key: str) -> Any:
        value = result.get(result_key)
        return value if value is not None and value != "" else local.get(local_key)
    expected_manifest = {
        "build_id": prefer_result("expected_helper_build_id", "build_id"),
        "git_commit": prefer_result("expected_git_commit", "git_commit"),
        "input_digest": prefer_result("expected_helper_input_digest", "helper_input_digest"),
        "source_state": local.get("source_state"),
        "build_variant": local.get("build_variant"),
        "gradle_version": local.get("gradle_version"),
        "version_name": local.get("version_name"),
        "version_code": local.get("version_code"),
    }
    schemas = result.get("required_schemas")
    expected_schemas = dict(schemas) if isinstance(schemas, dict) else {}
    expected_schemas["helper_build_identity_schema"] = "1"
    expected_schemas["helper_protocol"] = EXACT_NODE_PROTOCOL_VERSION
    return {
        "source_projection": projection,
        "expected_local_manifest": expected_manifest,
        "expected_schemas": expected_schemas,
    }

def _validated_secondary_window_event_diagnostics(
    value: Any, *, request_id: str, transaction_id: str, service_id: str,
    window_id: int, package_name: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("evidence_role") != "SECONDARY_ONLY":
        return None
    if any(value.get(key) != expected for key, expected in (
        ("request_id", request_id), ("transaction_id", transaction_id),
        ("service_instance_id", service_id), ("connection_id", service_id),
        ("owner_window_id", window_id),
    )):
        return None
    start = value.get("action_dispatch_elapsed_realtime_ms")
    deadline = value.get("dispatch_deadline_elapsed_realtime_ms")
    events = value.get("events")
    if (type(start) is not int or type(deadline) is not int or deadline < start or
            not isinstance(events, list) or len(events) > 8 or
            type(value.get("event_count")) is not int or value.get("event_count") != len(events)):
        return None
    for event in events:
        if not isinstance(event, dict) or any(event.get(key) != expected for key, expected in (
            ("request_id", request_id), ("transaction_id", transaction_id),
            ("service_instance_id", service_id), ("connection_id", service_id),
            ("owner_window_id", window_id), ("event_window_id", window_id),
            ("event_package", package_name),
        )):
            return None
        if (type(event.get("event_type")) is not int or event["event_type"] not in (32, 0x40000000) or
                type(event.get("event_elapsed_realtime_ms")) is not int or
                not start <= event["event_elapsed_realtime_ms"] <= deadline):
            return None
    return value


class HelperBridge:
    BRIDGE_VERSION = "1.0.1"
    _PREFLIGHT_LIGHT_CMD_TIMEOUT_SEC = 5.0
    # Failed-run results arrived in 41.946–55.903s; ten broadcasts then ANRed
    # around 60s. Navigation completion is independent of the unchanged 30s
    # command-delivery limit. Never retry an action whose delivery is uncertain.
    SMART_NAV_RESULT_WAIT_SECONDS = 75.0
    # FOCUS_IN_BOUNDS already took 30.454s. These commands scan the same
    # accessibility trees as SMART_NEXT (observed up to ~60s); share its
    # bounded operation budget, independently of 30s broadcast delivery.
    FOCUS_RESULT_WAIT_SECONDS = 75.0

    def __init__(self, client: Any) -> None:
        self._client = client
        self._smart_request_lock = threading.Lock()
        self._smart_request_ids: OrderedDict[str, None] = OrderedDict()
        self._expired_smart_requests: OrderedDict[str, bool] = OrderedDict()
        self._async_lock = threading.RLock()
        self._async_in_flight: set[str] = set()
        self._focus_request_ids: OrderedDict[str, str] = OrderedDict()
        self._expired_focus_requests: OrderedDict[str, bool] = OrderedDict()
        self._exact_request_registry = OneShotRequestRegistry()

    def is_focus_request(self, req_id: str) -> bool:
        with self._async_lock:
            return req_id in self._focus_request_ids

    def observe_late_focus_results(self, logs: str) -> None:
        with self._async_lock:
            retired = list(self._expired_focus_requests.items())
        for req_id, observed in retired:
            if observed:
                continue
            transport = self._client._logcat_reader.reassemble_chunked_payload(logs, "TARGET_ACTION_RESULT", req_id)
            payloads = [transport["payload"]] if transport.get("state") == "complete" else []
            if transport.get("state") == "absent":
                payloads = self._client._extract_all_payloads(logs, "TARGET_ACTION_RESULT")
            for payload in payloads:
                try:
                    result = self._client._parse_json_payload(payload, "TARGET_ACTION_RESULT")
                except Exception:
                    continue
                if result.get("reqId") == req_id:
                    with self._async_lock:
                        self._expired_focus_requests[req_id] = True
                    self._client._safe_trace_print(f"[FOCUS_TRANSPORT] late_result req_id={req_id} ignored=true reason=retired_request")
                    break

    def request_focus_command(self, dev: Any, action: str, req_id: str, extras: list[str]) -> dict[str, Any]:
        if action not in {ACTION_FOCUS_IN_BOUNDS, ACTION_TARGET_FOCUS_COMMIT}:
            raise ValueError("Unsupported asynchronous focus command")
        with self._async_lock:
            if req_id in self._focus_request_ids:
                return {"success": False, "status": "transport_error", "reason": "duplicate_focus_request_id", "reqId": req_id}
            self._focus_request_ids[req_id] = action
            self._async_in_flight.add(req_id)
            while len(self._focus_request_ids) > 1024:
                expired = next((key for key in self._focus_request_ids if key not in self._async_in_flight), None)
                if expired is None:
                    break
                del self._focus_request_ids[expired]
        self._client._safe_trace_print(f"[FOCUS_TRANSPORT] before_broadcast action={action} req_id={req_id}")
        started = time.monotonic()
        try:
            try:
                stdout = self._client._broadcast(dev, action, extras)
            except AdbCommandFailure as exc:
                result = {"success": False, "status": "transport_error", "reason": exc.reason, "reqId": req_id,
                          "deliveryElapsedSeconds": time.monotonic() - started,
                          "command": exc.command, "commandTimeoutSeconds": exc.timeout,
                          "commandStdout": exc.stdout, "commandStderr": exc.stderr, "resultWaitStarted": False}
                self._client._safe_trace_print(f"[FOCUS_TRANSPORT] delivery_failed action={action} req_id={req_id} reason={exc.reason} retry=false")
            else:
                delivery = time.monotonic() - started
                self._client._safe_trace_print(f"[FOCUS_TRANSPORT] delivered action={action} req_id={req_id} delivery_seconds={delivery:.3f} result_pending=true")
                result = self._client._read_log_result(dev, "TARGET_ACTION_RESULT", req_id,
                    wait_seconds=self.FOCUS_RESULT_WAIT_SECONDS, poll_interval_sec=0.2)
                result.update(commandStdout=stdout, deliveryElapsedSeconds=delivery,
                              resultWaitSeconds=self.FOCUS_RESULT_WAIT_SECONDS, resultWaitStarted=True)
            if result.get("status") == "transport_error" or result.get("reason") == "json_parse_failed":
                with self._async_lock:
                    self._expired_focus_requests[req_id] = bool(result.get("lateResult"))
                    while len(self._expired_focus_requests) > 64:
                        self._expired_focus_requests.popitem(last=False)
            self._client._safe_trace_print(f"[FOCUS_TRANSPORT] completed action={action} req_id={req_id} status={result.get('status', '')} reason={result.get('reason', '')} retry=false")
            return result
        finally:
            with self._async_lock:
                self._async_in_flight.discard(req_id)

    def observe_late_smart_results(self, logs: str) -> None:
        """Classify retired responses from existing polls without issuing actions."""
        for req_id, observed in list(self._expired_smart_requests.items()):
            if observed:
                continue
            transport = self._client._logcat_reader.reassemble_chunked_payload(logs, "SMART_NAV_RESULT", req_id)
            payloads = [transport["payload"]] if transport.get("state") == "complete" else []
            if transport.get("state") == "absent":
                payloads = self._client._extract_all_payloads(logs, "SMART_NAV_RESULT")
            for payload in payloads:
                try:
                    result = self._client._parse_json_payload(payload, "SMART_NAV_RESULT")
                except Exception:
                    continue
                if result.get("reqId") == req_id:
                    self._expired_smart_requests[req_id] = True
                    self._client._safe_trace_print(f"[SMART_NEXT_TRANSPORT] late_result req_id={req_id} ignored=true reason=retired_request")
                    break

    def _retire_smart_request(self, req_id: str, *, late_observed: bool = False) -> None:
        self._expired_smart_requests[req_id] = late_observed
        while len(self._expired_smart_requests) > 64:
            self._expired_smart_requests.popitem(last=False)

    @staticmethod
    def _parse_broadcast_result(result: dict[str, Any], *, success_key: str = "success") -> bool:
        return bool(result.get(success_key))

    def _ping_helper(self, dev: Any = None, wait_: float = 3.0) -> bool:
        self._client.clear_logcat(dev=dev)
        req_id = str(uuid.uuid4())[:8]
        self._client._broadcast(dev, ACTION_PING, ["--es", "reqId", req_id])
        result = self._client._read_log_result(dev, "PING_RESULT", req_id, wait_seconds=wait_)
        return self._parse_broadcast_result(result) and result.get("status") == "READY"

    def precheck_helper_build_identity(
        self,
        dev: Any = None,
        wait_: float = 3.0,
        *,
        repo_root: str | Path | None = None,
        acceptance_mode: bool = True,
        diagnostic_observer: Any = None,
    ) -> dict[str, Any]:
        """Issue one read-only PING and compare the reported Helper inputs locally."""
        self._client.clear_logcat(dev=dev)
        req_id = str(uuid.uuid4())
        self._client._broadcast(dev, ACTION_PING, ["--es", "reqId", req_id])
        ping = self._client._read_log_result(dev, "PING_RESULT", req_id, wait_seconds=wait_)
        if not isinstance(ping, dict) or ping.get("reqId") != req_id or ping.get("success") is not True or ping.get("status") != "READY":
            ping = None
        capabilities = None
        capability_error = None
        if isinstance(ping, dict):
            query_nonce = uuid.uuid4().hex
            try:
                capabilities = self._client._hierarchy_transfer_control(
                    dev,
                    "CAPABILITIES",
                    ["--es", "queryNonce", query_nonce],
                    request_id="",
                    remaining_seconds=max(0.1, min(float(wait_), 2.0)),
                )
                if capabilities.get("query_nonce") != query_nonce:
                    capabilities = None
                    capability_error = "CAPABILITY_QUERY_NONCE_MISMATCH"
            except Exception as error:
                capabilities = None
                capability_error = f"CAPABILITY_QUERY_FAILED:{type(error).__name__}"
        root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
        result = precheck_repo_helper_build_identity(
            root,
            ping,
            capabilities=capabilities,
            capability_error=capability_error,
            acceptance_mode=acceptance_mode,
        ).to_dict()
        result["helper_service_instance_id"] = ping.get("helper_service_instance_id") if isinstance(ping, dict) else None
        result["helper_capabilities"] = list(ping.get("capabilities") or []) if isinstance(ping, dict) else []
        result["navigation_action_state"] = (dict(ping.get("navigation_action_state"))
            if isinstance(ping, dict) and isinstance(ping.get("navigation_action_state"), dict) else None)
        result["capability_service_instance_id"] = capabilities.get("service_instance_id") if isinstance(capabilities, dict) else None
        result["capability_process_epoch"] = capabilities.get("process_epoch") if isinstance(capabilities, dict) else None
        result["capability_generation"] = capabilities.get("generation") if isinstance(capabilities, dict) else None
        if isinstance(ping, dict) and isinstance(ping.get("exact_action_state"), dict):
            result["exact_action_state"] = dict(ping["exact_action_state"])
        if callable(diagnostic_observer):
            try:
                context = _precheck_diagnostic_context(root, result, ping, capabilities)
                diagnostic_observer(context)
            except Exception:
                pass
        return result

    def navigation_action_contract_for_scenario(
        self,
        dev: Any,
        scenario_id: str,
        *,
        contract_id: str | None = None,
        identity_check: dict[str, Any] | None = None,
        repo_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Return one locally packaged, build-validated nav contract for a trusted runner scenario."""
        scenario = str(scenario_id or "").strip()
        check = identity_check or self.precheck_helper_build_identity(
            dev=dev, wait_=3.0, repo_root=repo_root, acceptance_mode=True)
        if not scenario or not helper_compatibility_allows_execution(check):
            return {"eligible": False, "reason": "HELPER_IDENTITY_NOT_ACCEPTED", "identity_check": check}
        state = check.get("navigation_action_state")
        if ("navigation_action" not in (check.get("helper_capabilities") or []) or not isinstance(state, dict)
                or state.get("supported") is not True or state.get("enabled") is not True
                or state.get("ready") is not True or state.get("default_enabled") is not False
                or state.get("visit_credit") is not False or state.get("c5_credit") is not False
                or state.get("exact_action_gate_independent") is not True
                or state.get("service_instance_id") != check.get("helper_service_instance_id")):
            return {"eligible": False, "reason": "NAVIGATION_CAPABILITY_NOT_READY", "identity_check": check}
        contracts = state.get("contracts")
        if not isinstance(contracts, list):
            return {"eligible": False, "reason": "NAVIGATION_CONTRACTS_INVALID", "identity_check": check}
        requested_contract_id = str(contract_id or "").strip()
        matches = [row for row in contracts if isinstance(row, dict) and
                   isinstance(row.get("scenario_ids"), list) and scenario in row["scenario_ids"] and
                   (not requested_contract_id or row.get("contract_id") == requested_contract_id)]
        if len(matches) != 1:
            return {"eligible": False,
                    "reason": "NAVIGATION_CONTRACT_MISSING" if not matches else "NAVIGATION_CONTRACT_AMBIGUOUS",
                    "identity_check": check}
        contract = matches[0]
        contract_id = contract.get("contract_id")
        digest = contract.get("contract_digest")
        if (not isinstance(contract_id, str) or not contract_id or
                not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            return {"eligible": False, "reason": "NAVIGATION_CONTRACT_INVALID", "identity_check": check}
        return {"eligible": True, "reason": "READY", "scenario_id": scenario,
                "contract_id": contract_id, "contract_digest": digest, "identity_check": check}

    def dispatch_navigation_action(
        self,
        dev: Any,
        *,
        scenario_id: str,
        transaction_id: str,
        capture_session: dict[str, Any],
        current_lease: dict[str, Any],
        readiness: dict[str, Any],
        activation_mode: str = NAVIGATION_ACTIVATION_DIRECT_CLICK,
        wait_seconds: float = 8.0,
    ) -> dict[str, Any]:
        """Dispatch one nav request against the exact already-armed Helper capture lease."""
        if readiness.get("eligible") is not True or readiness.get("scenario_id") != scenario_id:
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_CAPABILITY_NOT_READY"}
        if activation_mode not in {NAVIGATION_ACTIVATION_DIRECT_CLICK,
                                   NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
                                   NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK}:
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_ACTIVATION_MODE_NOT_ALLOWLISTED"}
        armed = capture_session.get("armed") if isinstance(capture_session, dict) else None
        current = current_lease.get("result") if isinstance(current_lease, dict) else None
        if not isinstance(armed, dict) or not isinstance(current, dict) or current_lease.get("ok") is not True:
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_OWNER_LEASE_INVALID"}
        if activation_mode == NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK and (
                scenario_id != "life_air_care_plugin" or
                readiness.get("contract_id") != "life_service_card_read_only_navigation" or
                current.get("ownerPackageName") != "com.samsung.android.oneconnect"):
            return {"success": False, "status": "rejected",
                    "reason": "NAVIGATION_DIAGNOSTIC_MODE_SCOPE_MISMATCH"}
        if armed.get("invocationUriBound") is not True or current.get("invocationUriBound") is not True:
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_INVOCATION_NOT_BOUND"}
        fields = ("runId", "invocationId", "scenarioId", "captureId", "connectionId", "ownerLeaseId", "ownerWindowId",
                  "ownerPackageName", "ownerPath", "ownerDescriptorDigest", "sourceSnapshotId", "helperSnapshotId",
                  "baselineHierarchyDigest", "sourceCaptureRequestId", "sourceProcessEpoch", "sourceGeneration",
                  "sourceServiceInstanceId", "sourceCaptureSequence", "sourceRootDigest", "sourceCandidateDigest",
                  "sourceCaptureKey", "sourceConnectionEpoch", "sourceBootEpoch", "ownerSourceNodeId",
                  "ownerSourceNodeIdStatus")
        if any(current.get(key) != armed.get(key) for key in fields):
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_OWNER_LEASE_MISMATCH"}
        source_node_id = current.get("ownerSourceNodeId")
        source_node_id_status = current.get("ownerSourceNodeIdStatus")
        source_node_identity_valid = (
            source_node_id_status == "FIELD_PRESENT" and isinstance(source_node_id, str)
            and bool(source_node_id.strip())
        ) or (
            source_node_id_status == "FIELD_ABSENT" and isinstance(source_node_id, str)
            and not source_node_id.strip()
        )
        if not source_node_identity_valid:
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_OWNER_SOURCE_IDENTITY_INVALID"}
        identity_check = readiness.get("identity_check")
        identity_check = identity_check if isinstance(identity_check, dict) else {}
        ping_lifecycle = identity_check.get("exact_action_state")
        ping_lifecycle = ping_lifecycle if isinstance(ping_lifecycle, dict) else {}
        expected_connection_epoch = (identity_check.get("navigation_connection_epoch")
                                     or identity_check.get("helper_connection_epoch")
                                     or identity_check.get("connection_epoch")
                                     or ping_lifecycle.get("connection_epoch"))
        expected_boot_epoch = identity_check.get("boot_epoch") or ping_lifecycle.get("boot_epoch")
        if (not expected_connection_epoch or not expected_boot_epoch
                or str(current.get("sourceConnectionEpoch")) != str(expected_connection_epoch)
                or str(current.get("sourceBootEpoch")) != str(expected_boot_epoch)):
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_SOURCE_LIFECYCLE_IDENTITY_MISMATCH"}
        owner_capture_id = str(capture_session.get("req_id") or "")
        tx = str(transaction_id or "")
        if (not owner_capture_id or current.get("scenarioId") != scenario_id or current.get("transactionId") != tx or
                current.get("connectionId") != readiness.get("identity_check", {}).get("helper_service_instance_id") or
                not isinstance(current.get("ownerPath"), list) or not current["ownerPath"]):
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_BINDING_INVALID"}
        request_id = str(uuid.uuid4())
        broadcast_stdout = ""
        request = {
            "request_id": request_id,
            "action": "ACTION_CLICK",
            "scenario_id": scenario_id,
            "transaction_id": tx,
            "owner_capture_request_id": owner_capture_id,
            "owner_lease_id": current["ownerLeaseId"],
            "run_id": current["runId"],
            "invocation_id": current["invocationId"],
            "service_instance_id": current["connectionId"],
            "connection_id": current["connectionId"],
            "window_id": current["ownerWindowId"],
            "node_path": current["ownerPath"],
            "descriptor_digest": current["ownerDescriptorDigest"],
            "package_name": str(current.get("ownerPackageName") or ""),
            "source_snapshot_id": current["sourceSnapshotId"],
            "helper_snapshot_id": current["helperSnapshotId"],
            "baseline_hierarchy_digest": current["baselineHierarchyDigest"],
            "capture_id": current["captureId"],
            "source_identity": {
                "request_id": current["sourceCaptureRequestId"],
                "process_epoch": current["sourceProcessEpoch"],
                "generation": current["sourceGeneration"],
                "service_instance_id": current["sourceServiceInstanceId"],
                "capture_sequence": current["sourceCaptureSequence"],
                "root_digest": current["sourceRootDigest"],
                "candidate_digest": current["sourceCandidateDigest"],
                "capture_key": current["sourceCaptureKey"],
                "connection_epoch": current["sourceConnectionEpoch"],
                "boot_epoch": current["sourceBootEpoch"],
                "owner_source_node_id": current["ownerSourceNodeId"],
                "owner_source_node_id_status": current["ownerSourceNodeIdStatus"],
            },
            "effect_contract_id": readiness["contract_id"],
            "effect_contract_digest": readiness["contract_digest"],
        }
        if activation_mode != NAVIGATION_ACTIVATION_DIRECT_CLICK:
            request["activation_mode"] = activation_mode
        if not request["package_name"]:
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_TARGET_PACKAGE_MISSING"}
        adb_shell_escape = getattr(self._client, "_escape_adb_string", None)
        if not callable(adb_shell_escape):
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_ADB_SHELL_ESCAPE_UNAVAILABLE",
                    "reqId": request_id}
        broadcast_argv: list[str] = []
        try:
            self._client.clear_logcat(dev=dev)
            broadcast_stdout = str(self._client._broadcast(dev, ACTION_NAVIGATION_ACTION, [
                "--es", "reqId", request_id,
                "--es", "navigationActionRequest", adb_shell_escape(canonical_json(request)),
            ]) or "")
            broadcast_argv = list(getattr(self._client, "_last_broadcast_command", []) or [])
            result = self._client._read_log_result(dev, "NAVIGATION_ACTION_RESULT", request_id,
                wait_seconds=max(0.1, min(float(wait_seconds), 15.0)), poll_interval_sec=0.05)
        except Exception as error:
            failure = {"success": False, "status": "transport_error",
                       "reason": f"NAVIGATION_ACTION_TRANSPORT_ERROR:{type(error).__name__}", "reqId": request_id,
                       "broadcast_stdout": " ".join(broadcast_stdout.split())[:240],
                       "broadcast_argv": list(getattr(self._client, "_last_broadcast_command", []) or [])}
            if isinstance(error, AdbCommandFailure):
                failure.update(adb_failure_reason=error.reason, adb_returncode=error.returncode,
                               adb_stderr=" ".join(error.stderr.split())[:240],
                               adb_stdout=" ".join(error.stdout.split())[:240],
                               broadcast_argv=list(error.command))
            return failure
        reader_miss = isinstance(result, dict) and result.get("reqId") == request_id and (
            result.get("status") == "transport_error" or
            (result.get("success") is False and not result.get("status") and
             not result.get("failure_code") and not result.get("receipt") and "reason" in result)
        )
        if not isinstance(result, dict) or result.get("reqId") != request_id or reader_miss:
            return {"success": False, "status": "transport_error", "reason": "NAVIGATION_ACTION_RESULT_MISSING",
                    "reqId": request_id, "broadcast_stdout": " ".join(broadcast_stdout.split())[:240],
                    "broadcast_argv": broadcast_argv,
                    "response_keys": sorted(str(key) for key in result)[:16] if isinstance(result, dict) else [],
                    "read_result_reason": str(result.get("reason") or "")[:160] if reader_miss else "",
                    "read_result_status": str(result.get("status") or "") if reader_miss else ""}
        receipt = result.get("receipt")
        secondary_window_event_diagnostics = _validated_secondary_window_event_diagnostics(
            result.get("secondary_window_event_diagnostics"), request_id=request_id, transaction_id=tx,
            service_id=current["connectionId"], window_id=current["ownerWindowId"],
            package_name=request["package_name"],
        )
        secondary_diagnostics_field = ({"secondary_window_event_diagnostics": secondary_window_event_diagnostics}
                                       if secondary_window_event_diagnostics is not None else {})
        if not isinstance(receipt, dict):
            return {"success": False, "status": "protocol_error", "reason": "NAVIGATION_ACTION_RECEIPT_INVALID",
                    "reqId": request_id, "raw_result": result,
                    "broadcast_stdout": " ".join(broadcast_stdout.split())[:240],
                    "broadcast_argv": broadcast_argv,
                    "response_req_id": str(result.get("reqId") or ""),
                    "response_status": str(result.get("status") or ""),
                    "response_failure_code": str(result.get("failure_code") or ""),
                    "response_keys": sorted(str(key) for key in result)[:16],
                    "receipt_present": False}
        expected = {
            "request_id": request_id, "action": "ACTION_CLICK", "transaction_id": tx, "scenario_id": scenario_id,
            "owner_capture_request_id": owner_capture_id, "owner_lease_id": current["ownerLeaseId"],
            "run_id": current["runId"], "invocation_id": current["invocationId"],
            "service_instance_id": current["connectionId"], "connection_id": current["connectionId"],
            "window_id": current["ownerWindowId"], "source_capture_id": current["captureId"],
            "helper_snapshot_id": current["helperSnapshotId"],
            "source_identity": request["source_identity"],
            "effect_contract_id": readiness["contract_id"], "effect_contract_digest": readiness["contract_digest"],
        }
        if activation_mode != NAVIGATION_ACTIVATION_DIRECT_CLICK:
            expected["activation_mode"] = activation_mode
        mismatch_fields = [key for key, value in expected.items() if receipt.get(key) != value]
        if activation_mode == NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK:
            diagnostic_target = receipt.get("diagnostic_target")
            expected_target = {
                "path": current["ownerPath"] + [0],
                "class_name": "android.widget.FrameLayout",
                "resource_id": "com.samsung.android.oneconnect:id/frameLayout",
                "window_id": current["ownerWindowId"],
                "source_snapshot_id": current["sourceSnapshotId"],
                "helper_snapshot_id": current["helperSnapshotId"],
                "baseline_hierarchy_digest": current["baselineHierarchyDigest"],
                "parent_path": current["ownerPath"],
            }
            if not isinstance(diagnostic_target, dict):
                mismatch_fields.append("diagnostic_target")
            else:
                mismatch_fields.extend(f"diagnostic_target.{key}" for key, value in expected_target.items()
                                       if diagnostic_target.get(key) != value)
            if receipt.get("status") != "DIAGNOSTIC_ONLY":
                mismatch_fields.append("status")
            if receipt.get("diagnostic_only") is not True:
                mismatch_fields.append("diagnostic_only")
            if receipt.get("verified_navigation") is not False:
                mismatch_fields.append("verified_navigation")
            if receipt.get("visit_authority") is not False:
                mismatch_fields.append("visit_authority")
            if receipt.get("c5_credit") is not False:
                mismatch_fields.append("c5_credit")
            if receipt.get("traversal_credit") is not False:
                mismatch_fields.append("traversal_credit")
            if receipt.get("activation_mode") != activation_mode:
                mismatch_fields.append("activation_mode")
            if receipt.get("diagnostic_action_dispatched") not in (True, False):
                mismatch_fields.append("diagnostic_action_dispatched")
            if receipt.get("action_call_count") not in (0, 1):
                mismatch_fields.append("action_call_count")
            diagnostic_event = receipt.get("diagnostic_click_event")
            if receipt.get("diagnostic_action_dispatched") is True:
                if isinstance(diagnostic_event, dict):
                    event_expected = {
                        "exact_target_match": True,
                        "event_type": 1,
                        "request_id": request_id,
                        "transaction_id": tx,
                        "service_instance_id": current["connectionId"],
                        "connection_id": current["connectionId"],
                        "window_id": current["ownerWindowId"],
                    }
                    mismatch_fields.extend(f"diagnostic_click_event.{key}"
                                           for key, value in event_expected.items()
                                           if diagnostic_event.get(key) != value)
                elif not receipt.get("failure_code"):
                    mismatch_fields.append("diagnostic_click_event")
            if mismatch_fields:
                return {"success": False, "status": "protocol_error",
                        "reason": "NAVIGATION_DIAGNOSTIC_RECEIPT_INVALID", "reqId": request_id,
                        "receipt": receipt, "receipt_mismatch_fields": mismatch_fields,
                        "request": request, "broadcast_stdout": " ".join(broadcast_stdout.split())[:240],
                        "broadcast_argv": broadcast_argv, **secondary_diagnostics_field}
            return {"success": False, "status": "diagnostic_only",
                    "reason": "DIAGNOSTIC_ONLY_NO_NAVIGATION_CREDIT", "reqId": request_id,
                    "action_dispatched": receipt["diagnostic_action_dispatched"],
                    "receipt": receipt, "request": request,
                    "broadcast_stdout": " ".join(broadcast_stdout.split())[:240],
                    "broadcast_argv": broadcast_argv, **secondary_diagnostics_field}
        if receipt.get("status") != "VERIFIED_NAVIGATION":
            mismatch_fields.append("status")
        if receipt.get("verified_navigation") is not True:
            mismatch_fields.append("verified_navigation")
        if receipt.get("action_call_count") != 1:
            mismatch_fields.append("action_call_count")
        if receipt.get("visit_authority") is not False:
            mismatch_fields.append("visit_authority")
        if receipt.get("c5_credit") is not False:
            mismatch_fields.append("c5_credit")
        if mismatch_fields:
            post_state_diagnostics = receipt.get("post_state_diagnostics", {})
            if not isinstance(post_state_diagnostics, dict):
                post_state_diagnostics = {}
            return {"success": False, "status": "rejected", "reason": "NAVIGATION_ACTION_RECEIPT_UNVERIFIED",
                    "reqId": request_id, "receipt": receipt,
                    "receipt_mismatch_fields": mismatch_fields,
                    "post_state_mismatch_fields": receipt.get("post_state_mismatch_fields", []),
                    "post_state_diagnostics": post_state_diagnostics,
                    "receipt_status": str(receipt.get("status") or ""),
                    "receipt_failure_code": str(receipt.get("failure_code") or ""),
                    "receipt_request_id": str(receipt.get("request_id") or ""),
                    "receipt_action_call_count": receipt.get("action_call_count"),
                    "receipt_owner_receipt_reason": str(receipt.get("owner_receipt_reason") or ""),
                    "receipt_owner_click_count": receipt.get("owner_receipt_eligible_exact_click_count"),
                    "broadcast_stdout": " ".join(broadcast_stdout.split())[:240],
                    "broadcast_argv": broadcast_argv,
                    **secondary_diagnostics_field}
        return {"success": True, "status": "VERIFIED_NAVIGATION", "reqId": request_id, "receipt": receipt,
                "request": request, "broadcast_stdout": " ".join(broadcast_stdout.split())[:240],
                "broadcast_argv": broadcast_argv, **secondary_diagnostics_field}

    def resolve_exact_node_read_only(
        self,
        dev: Any,
        request: ExactNodeRequest | dict[str, Any] | str,
        wait_: float = 30.0,
        *,
        repo_root: str | Path | None = None,
        acceptance_mode: bool = True,
    ) -> dict[str, Any]:
        """Send one exact-node reacquire request; this path can only return a read-only ACK."""
        try:
            parsed_request = ExactNodeRequest.parse(request.data if isinstance(request, ExactNodeRequest) else request)
        except ProtocolValidationError as error:
            return {"success": False, "status": "protocol_reject", "failure_code": error.code.value}

        identity_check = self.precheck_helper_build_identity(
            dev=dev, wait_=min(wait_, 5.0), repo_root=repo_root, acceptance_mode=acceptance_mode
        )
        if not helper_compatibility_allows_execution(identity_check):
            return {"success": False, "status": "identity_reject", "failure_code": identity_check.get("reason"),
                    "helper_build_precheck": identity_check}
        if identity_check.get("helper_service_instance_id") != parsed_request.data["helper_service_instance_id"]:
            return {"success": False, "status": "identity_reject", "failure_code": "HELPER_SERVICE_INSTANCE_MISMATCH",
                    "helper_build_precheck": identity_check}

        try:
            self._exact_request_registry.claim(
                parsed_request,
                now=datetime.now(timezone.utc),
                expected_package=parsed_request.data["expected_package"],
                expected_window=parsed_request.data["expected_window"],
                current_snapshot_id=parsed_request.data["reacquire_snapshot_id"],
            )
        except ProtocolValidationError as error:
            return {"success": False, "status": "protocol_reject", "failure_code": error.code.value}

        req_id = parsed_request.request_id
        try:
            self._client.clear_logcat(dev=dev)
            self._client._broadcast(dev, ACTION_RESOLVE_EXACT_NODE, [
                "--es", "reqId", req_id,
                "--es", "exactNodeRequest", canonical_json(parsed_request.data),
            ])
            result = self._client._read_log_result(dev, "EXACT_NODE_RESOLVE_RESULT", req_id, wait_seconds=wait_)
        except AdbCommandFailure as error:
            return {"success": False, "status": "transport_error", "failure_code": error.reason, "reqId": req_id}
        if not isinstance(result, dict) or result.get("reqId") != req_id or result.get("status") != "ACK":
            return {"success": False, "status": "transport_error", "failure_code": "EXACT_NODE_ACK_MISSING", "reqId": req_id}
        try:
            ack = ExactNodeAck.parse(result.get("ack"), parsed_request)
        except ProtocolValidationError as error:
            return {"success": False, "status": "protocol_error", "failure_code": error.code.value, "reqId": req_id}
        return {"success": ack.data["resolved"], "status": "RESOLVED" if ack.data["resolved"] else "REJECTED",
                "reqId": req_id, "ack": ack.data, "helper_build_precheck": identity_check}

    def _helper_ready_check(self, dev: Any = None) -> bool:
        started = time.monotonic()
        serial = self._client._resolve_serial(dev)
        serial_label = serial or "default"
        cache_hit, cached_result = self._client._get_cached_helper_status(serial=serial)
        if cache_hit:
            elapsed = time.monotonic() - started
            self._client._debug_print(
                f"[DEBUG][helper_status] serial={serial_label} cached=True "
                f"result={cached_result} elapsed={elapsed:.3f}s"
            )
            return cached_result

        self._client._debug_print("[PREFLIGHT][helper] checking enabled_accessibility_services")
        try:
            enabled_services = self._client._run(
                ["shell", "settings", "get", "secure", "enabled_accessibility_services"],
                dev=dev,
                timeout=self._PREFLIGHT_LIGHT_CMD_TIMEOUT_SEC,
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print(
                f"[PREFLIGHT][helper] adb failure during enabled_accessibility_services error='{exc}'"
            )
            print(
                f"[PREFLIGHT][helper] helper_ready=False reason='adb_failure' "
                f"serial={serial_label} elapsed={elapsed:.3f}s"
            )
            return False
        if not enabled_services:
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print("[PREFLIGHT][helper] adb timeout or failure during enabled_accessibility_services")
            print(
                f"[PREFLIGHT][helper] helper_ready=False reason='adb_timeout_or_failure' "
                f"serial={serial_label} elapsed={elapsed:.3f}s"
            )
            return False
        helper_enabled = self._client.package_name in enabled_services
        if not helper_enabled:
            print(
                f"{RED_TEXT}⚠️ [ERROR] 헬퍼 앱의 접근성 서비스가 꺼져 있습니다. "
                "'설정 > 접근성 > 설치된 앱'에서 활성화해 주세요."
                f"{RESET_TEXT}"
            )
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print(f"[WARN][helper_status] serial={serial_label} result=False reason=service_disabled elapsed={elapsed:.3f}s")
            print(
                f"[PREFLIGHT][helper] helper_ready=False reason='service_disabled' "
                f"serial={serial_label} elapsed={elapsed:.3f}s"
            )
            return False

        self._client._debug_print("[PREFLIGHT][helper] checking helper ping readiness")
        if not self._client.ping(dev=dev, wait_=3.0):
            print(
                f"{RED_TEXT}⚠️ [ERROR] 헬퍼 앱 접근성 서비스가 명령 수신 준비 상태가 아닙니다. "
                "서비스를 다시 시작하거나 접근성 설정을 재확인해 주세요."
                f"{RESET_TEXT}"
            )
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print(f"[WARN][helper_status] serial={serial_label} result=False reason=ping_failed elapsed={elapsed:.3f}s")
            print(
                f"[PREFLIGHT][helper] helper_ready=False reason='ping_failed' "
                f"serial={serial_label} elapsed={elapsed:.3f}s"
            )
            return False

        self._client._update_helper_status_cache(serial=serial, result=True)
        elapsed = time.monotonic() - started
        print(
            f"[PREFLIGHT][helper] helper_ready=True reason='ok' "
            f"serial={serial_label} elapsed={elapsed:.3f}s"
        )
        self._client._debug_print(
            f"[DEBUG][helper_status] serial={serial_label} cached=False "
            f"result=True elapsed={elapsed:.3f}s"
        )
        return True

    def _request_get_focus(
        self,
        dev: Any,
        req_id: str,
        wait_seconds: float,
        poll_interval_sec: float = 0.2,
    ) -> dict[str, Any]:
        self._client.clear_logcat(dev=dev)
        self._client._broadcast(dev, ACTION_GET_FOCUS, ["--es", "reqId", req_id])
        return self._client._read_log_result(
            dev,
            "FOCUS_RESULT",
            req_id,
            wait_seconds=wait_seconds,
            poll_interval_sec=poll_interval_sec,
        )

    def _request_smart_next(self, dev: Any, req_id: str) -> dict[str, Any]:
        with self._async_lock:
            self._async_in_flight.add(req_id)
        try:
            return self._request_smart_next_impl(dev, req_id)
        finally:
            with self._async_lock:
                self._async_in_flight.discard(req_id)

    def _request_smart_next_impl(self, dev: Any, req_id: str) -> dict[str, Any]:
        with self._smart_request_lock:
            if req_id in self._smart_request_ids:
                return {"success": False, "status": "transport_error", "reason": "duplicate_smart_next_request_id", "reqId": req_id}
            self._smart_request_ids[req_id] = None
            while len(self._smart_request_ids) > 1024:
                self._smart_request_ids.popitem(last=False)
        serial = self._client._resolve_serial(dev)
        cmd_parts = [self._client.adb_path]
        if serial:
            cmd_parts.extend(["-s", serial])
        cmd_parts.extend(
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                ACTION_SMART_NEXT,
                "-p",
                self._client.package_name,
                "--es",
                "reqId",
                req_id,
            ]
        )
        full_cmd = " ".join(cmd_parts)
        self._client._safe_trace_print(
            f"[SMART_NEXT_TRACE] before_broadcast action={ACTION_SMART_NEXT} "
            f"req_id={req_id} fallback=false full_adb_command=\"{full_cmd}\""
        )
        correlation_extras = []
        get_correlation_extras = getattr(self._client, "_evidence_correlation_extras", None)
        if callable(get_correlation_extras):
            try:
                correlation_extras = list(get_correlation_extras() or [])
            except Exception:
                correlation_extras = []
        delivery_start = time.monotonic()
        try:
            raw_stdout = self._client._broadcast(
                dev,
                ACTION_SMART_NEXT,
                ["--es", "reqId", req_id, *correlation_extras],
            )
        except AdbCommandFailure as exc:
            self._retire_smart_request(req_id)
            result = {"success": False, "status": "transport_error", "reason": exc.reason, "reqId": req_id,
                      "deliveryElapsedSeconds": time.monotonic() - delivery_start,
                      "commandTimeoutSeconds": exc.timeout, "command": exc.command,
                      "commandStdout": exc.stdout, "commandStderr": exc.stderr, "resultWaitStarted": False}
            self._client._safe_trace_print(f"[SMART_NEXT_TRANSPORT] delivery_failed req_id={req_id} reason={exc.reason} retry=false")
            return result
        mark_dispatched = getattr(self._client, "_smart_nav_request_dispatched", None)
        if callable(mark_dispatched):
            try:
                mark_dispatched(req_id)
            except Exception:
                pass
        else:
            mark_action_sent = getattr(self._client, "_evidence_action_sent", None)
            if callable(mark_action_sent):
                try:
                    mark_action_sent(action=ACTION_SMART_NEXT, req_id=req_id)
                except Exception:
                    pass
        delivery_elapsed = time.monotonic() - delivery_start
        self._client._safe_trace_print(
            f"[SMART_NEXT_TRACE] adb_raw_response req_id={req_id} raw_stdout=\"{raw_stdout}\""
        )
        result = self._client._read_log_result(
            dev,
            "SMART_NAV_RESULT",
            req_id,
            wait_seconds=self.SMART_NAV_RESULT_WAIT_SECONDS,
            poll_interval_sec=0.2,
        )
        self._client._safe_trace_print(
            f"[SMART_NEXT_TRACE] parsed_broadcast_result req_id={req_id} raw_json={result}"
        )
        result.update(deliveryElapsedSeconds=delivery_elapsed, resultWaitSeconds=self.SMART_NAV_RESULT_WAIT_SECONDS)
        if not result.get("success") and result.get("status") == "transport_error":
            self._retire_smart_request(req_id, late_observed=bool(result.get("lateResult")))
        self._client._safe_trace_print(f"[SMART_NEXT_TRANSPORT] completed req_id={req_id} delivery_seconds={delivery_elapsed:.3f} result_wait_limit={self.SMART_NAV_RESULT_WAIT_SECONDS} status={result.get('status', '')} reason={result.get('reason', '')} retry=false")
        return result

    def request_evidence_events(self, dev: Any, req_id: str) -> dict[str, Any]:
        """Read an optional Helper evidence snapshot; never affects navigation results."""
        # Do not clear logcat here: delayed per-event evidence is collected by
        # the Runner immediately before this legacy snapshot request.
        self._client._broadcast(dev, ACTION_EVIDENCE_EVENTS, ["--es", "reqId", req_id])
        return self._client._read_log_result(
            dev,
            "EVIDENCE_EVENTS_RESULT",
            req_id,
            wait_seconds=0.1,
            poll_interval_sec=0.05,
        )

    @staticmethod
    def normalize_smart_next_status(result: dict[str, Any]) -> tuple[str, bool, str, set[str]]:
        detail = str(result.get("detail", "")).strip().lower()
        flags = {
            str(flag).strip().lower()
            for flag in (result.get("flags") or [])
            if str(flag).strip()
        }
        terminal = detail == "end_of_sequence" or "terminal" in flags
        if not result.get("success"):
            return STATUS_FAILED, terminal, detail, flags

        status = str(result.get("status", "failed")).strip().lower()
        normalized = {
            "moved": STATUS_MOVED,
            "scrolled": STATUS_SCROLLED,
            "looped": STATUS_LOOPED,
            "failed": STATUS_FAILED,
            # Backward compatibility for older Android helper builds.
            "moved_to_bottom_bar": STATUS_MOVED,
            "moved_to_bottom_bar_direct": STATUS_MOVED,
            "moved_aligned": STATUS_MOVED,
        }.get(status)
        if normalized is not None:
            return normalized, terminal, detail, flags

        if detail in {"moved_to_bottom_bar", "moved_to_bottom_bar_direct", "moved_aligned"}:
            return STATUS_MOVED, terminal, detail, flags
        return STATUS_FAILED, terminal, detail, flags
