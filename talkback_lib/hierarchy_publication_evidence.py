from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections import Counter
from typing import Any

from talkback_lib.logcat_reader import LogcatReader

REPORT_PREFIX = "HPUB1."
MAX_RESULT_BYTES = 16 * 1024
MAX_JSON_BYTES = 11 * 1024
MAX_PAGE_ROWS = 32
MAX_ROWS = 292
SUCCESS_RESULT_CODE = 0x4850


class PublicationEvidenceError(ValueError):
    pass


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PublicationEvidenceError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def decode_report_data(data: str, *, expected_nonce: str | None = None) -> dict[str, Any]:
    encoded = data.encode("utf-8")
    if len(encoded) > MAX_RESULT_BYTES:
        raise PublicationEvidenceError("result_data_limit")
    if not data.startswith(REPORT_PREFIX):
        raise PublicationEvidenceError("result_prefix_invalid")
    pieces = data[len(REPORT_PREFIX) :].split(".")
    if len(pieces) != 2:
        raise PublicationEvidenceError("result_envelope_invalid")
    body, expected_digest = pieces
    if not re.fullmatch(r"[A-Za-z0-9_-]+", body) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise PublicationEvidenceError("result_encoding_invalid")
    try:
        raw = base64.b64decode(body + "=" * ((4 - len(body) % 4) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PublicationEvidenceError("result_base64_invalid") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise PublicationEvidenceError("json_limit")
    actual_digest = hashlib.sha256(raw).hexdigest()
    if actual_digest != expected_digest:
        raise PublicationEvidenceError("result_digest_mismatch")
    try:
        result = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationEvidenceError("result_json_invalid") from exc
    if not isinstance(result, dict):
        raise PublicationEvidenceError("result_json_not_object")
    if expected_nonce is not None and result.get("query_nonce") != expected_nonce:
        raise PublicationEvidenceError("query_nonce_mismatch")
    if result.get("schema") != "hierarchy-publication-report.v1":
        raise PublicationEvidenceError("schema_mismatch")
    return result


def decode_broadcast_stdout(
    stdout: str,
    *,
    returncode: int,
    expected_nonce: str,
    expected_result_code: int = SUCCESS_RESULT_CODE,
) -> dict[str, Any]:
    if returncode != 0:
        raise PublicationEvidenceError(f"adb_exit:{returncode}")
    match = re.search(r'Broadcast completed: result=(-?\d+), data="(HPUB1\.[A-Za-z0-9_.-]+)"', stdout)
    if not match:
        raise PublicationEvidenceError("ordered_result_not_on_stdout")
    if int(match.group(1)) != expected_result_code:
        try:
            error = decode_report_data(match.group(2), expected_nonce=expected_nonce)
        except PublicationEvidenceError:
            raise PublicationEvidenceError(f"ordered_result_code:{match.group(1)}")
        raise PublicationEvidenceError(f"ordered_query_rejected:{error.get('status', 'unknown')}")
    result = decode_report_data(match.group(2), expected_nonce=expected_nonce)
    if result.get("status") != "OK":
        raise PublicationEvidenceError(f"ordered_query_rejected:{result.get('status', 'unknown')}")
    return result


def validate_page(
    page: dict[str, Any],
    *,
    request_id: str,
    process_epoch: str,
    service_instance_id: str | None,
    capture_generation: int,
    report_revision: int,
    report_digest: str,
    page_kind: str,
    page_index: int,
    page_count: int,
) -> list[dict[str, Any]]:
    expected = {
        "request_id": request_id,
        "process_epoch": process_epoch,
        "service_instance_id": service_instance_id,
        "capture_generation": capture_generation,
        "report_revision": report_revision,
        "report_digest": report_digest,
        "page_kind": page_kind,
        "page_index": page_index,
        "page_count": page_count,
    }
    for key, value in expected.items():
        if page.get(key) != value:
            raise PublicationEvidenceError(f"page_binding_mismatch:{key}")
    rows = page.get("records")
    if not isinstance(rows, list) or len(rows) > MAX_PAGE_ROWS or page_count > 10:
        raise PublicationEvidenceError("page_bounds_invalid")
    if any(not isinstance(row, dict) for row in rows):
        raise PublicationEvidenceError("page_row_invalid")
    if any(len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 256 for row in rows):
        raise PublicationEvidenceError("page_row_size_limit")
    return rows


def _message_from_log_line(line: str, request_id: str) -> str | None:
    candidates = (
        "DUMP_HIERARCHY_RESULT_CHUNK ",
        "DUMP_HIERARCHY_RESULT ",
        "DUMP_HIERARCHY_END ",
    )
    for marker in candidates:
        index = line.find(marker)
        if index >= 0:
            message = line[index:].strip()
            if f"reqId={request_id} " in message or message == f"DUMP_HIERARCHY_END {request_id}":
                return message
            if message.startswith(f"DUMP_HIERARCHY_RESULT {request_id} "):
                return message
    return None


def hierarchy_frame_messages(log_text: str, request_id: str) -> list[str]:
    result: list[str] = []
    for line in log_text.splitlines():
        message = _message_from_log_line(line, request_id)
        if message is not None:
            result.append(message)
    return result


def parse_hierarchy_capture(log_text: str, request_id: str) -> dict[str, Any]:
    terminal = f"DUMP_HIERARCHY_END {request_id}"
    terminal_count = sum(1 for line in log_text.splitlines() if line.strip() == terminal)
    if terminal_count != 1:
        return {"accepted": False, "reason": "terminal_count", "terminal_count": terminal_count}

    direct_payloads: list[dict[str, Any]] = []
    unmatched_result = False
    for candidate in LogcatReader.extract_all_payloads(log_text, "DUMP_HIERARCHY_RESULT"):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            if parsed.get("reqId") == request_id:
                direct_payloads.append(parsed)
            else:
                unmatched_result = True
    if len(direct_payloads) > 1:
        return {"accepted": False, "reason": "duplicate_result", "terminal_count": terminal_count}
    if direct_payloads:
        payload = direct_payloads[0]
    else:
        if unmatched_result:
            return {"accepted": False, "reason": "request_id_mismatch", "terminal_count": terminal_count}
        assembled = LogcatReader.reassemble_chunked_payload(
            log_text, "DUMP_HIERARCHY_RESULT", request_id, max_chunks=512, max_payload_bytes=1024 * 1024
        )
        if assembled.get("state") != "complete":
            return {
                "accepted": False,
                "reason": str(assembled.get("reason", assembled.get("state", "unknown"))),
                "missing": assembled.get("missing", []),
                "terminal_count": terminal_count,
            }
        try:
            payload = json.loads(str(assembled.get("payload") or ""))
        except json.JSONDecodeError:
            return {"accepted": False, "reason": "invalid_json", "terminal_count": terminal_count}
    if not isinstance(payload, dict) or payload.get("reqId") != request_id:
        return {"accepted": False, "reason": "request_id_mismatch", "terminal_count": terminal_count}
    if payload.get("success") is not True:
        return {
            "accepted": False,
            "reason": str(payload.get("reason", "helper_failure")),
            "helper_reported_failure": True,
            "terminal_count": terminal_count,
        }
    if not isinstance(payload.get("nodes"), list) or not payload["nodes"]:
        return {"accepted": False, "reason": "empty_nodes", "terminal_count": terminal_count}
    if not isinstance(payload.get("windows"), list) or not payload["windows"]:
        return {"accepted": False, "reason": "empty_windows", "terminal_count": terminal_count}
    payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return {
        "accepted": True,
        "reason": "OK",
        "terminal_count": terminal_count,
        "req_id": request_id,
        "node_count": len(payload["nodes"]),
        "window_count": len(payload["windows"]),
        "payload_sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
    }


def _digest_counts(log_text: str, request_id: str) -> Counter[str]:
    return Counter(hashlib.sha256(message.encode("utf-8")).hexdigest() for message in hierarchy_frame_messages(log_text, request_id))


def compare_publication_layers(
    summary: dict[str, Any],
    plan_rows: list[dict[str, Any]],
    attempt_rows: list[dict[str, Any]],
    raw_continuous: str,
    runner_raw: str,
    parser_result: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    complete = bool(summary.get("evidence_complete") and summary.get("finalized") and summary.get("plan_complete"))
    raw_counts = _digest_counts(raw_continuous, request_id)
    runner_counts = _digest_counts(runner_raw, request_id)
    attempts_by_sequence: dict[int, list[dict[str, Any]]] = {}
    for attempt in attempt_rows:
        if isinstance(attempt.get("s"), int):
            attempts_by_sequence.setdefault(attempt["s"], []).append(attempt)

    matrix: list[dict[str, Any]] = []
    outcomes: list[str] = []
    for descriptor in plan_rows:
        digest = str(descriptor.get("d", ""))
        sequence = descriptor.get("s")
        attempts = attempts_by_sequence.get(sequence, []) if isinstance(sequence, int) else []
        raw_count = raw_counts.get(digest, 0)
        runner_count = runner_counts.get(digest, 0)
        returns = [str(row.get("rc", "OUTCOME_UNKNOWN")) for row in attempts]
        if not attempts:
            if raw_count or runner_count:
                outcome = "OBSERVED_WITHOUT_LEDGER_RECORD"
            else:
                outcome = "NOT_ATTEMPTED" if complete else "EVIDENCE_INCOMPLETE"
        elif "NEGATIVE" in returns:
            outcome = "LOG_API_RETURN_FAILURE"
        elif "ZERO" in returns:
            outcome = "API_NO_POSITIVE_ACK"
        elif raw_count and not runner_count:
            outcome = "RAW_PRESENT_RUNNER_MISSING"
        elif runner_count and not raw_count:
            outcome = "CAPTURE_CHANNEL_DISAGREEMENT"
        elif runner_count and not parser_result.get("accepted"):
            outcome = (
                "HELPER_FAILURE_RESULT_OBSERVED"
                if parser_result.get("helper_reported_failure")
                else "RUNNER_PRESENT_PARSER_REJECTED"
            )
        elif not raw_count and any(value == "POSITIVE" for value in returns):
            outcome = "LOG_API_SUCCESS_RAW_LOGCAT_MISSING"
        elif raw_count and runner_count and parser_result.get("accepted"):
            outcome = "OBSERVED_END_TO_END"
        elif any(value in {"THREW", "OUTCOME_UNKNOWN"} for value in returns):
            outcome = "EVIDENCE_INCOMPLETE"
        else:
            outcome = "EVIDENCE_INCOMPLETE"
        outcomes.append(outcome)
        matrix.append({
            "frame_sequence": sequence,
            "frame_type": descriptor.get("t"),
            "chunk_index": descriptor.get("i"),
            "frame_digest": digest,
            "helper_attempted": bool(attempts),
            "log_api_return_classes": returns,
            "raw_logcat_observed_count": raw_count,
            "runner_observed_count": runner_count,
            "parser_accepted": bool(parser_result.get("accepted") and runner_count > 0),
            "outcome": outcome,
        })

    planned_digests = {str(row.get("d", "")) for row in plan_rows}
    observed_messages = hierarchy_frame_messages(raw_continuous, request_id)
    for message in observed_messages:
        digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
        if digest not in planned_digests:
            outcomes.append("OBSERVED_WITHOUT_LEDGER_RECORD")
            matrix.append({
                "frame_sequence": None,
                "frame_type": "UNPLANNED_OBSERVED_FRAME",
                "chunk_index": None,
                "frame_digest": digest,
                "helper_attempted": None,
                "log_api_return_classes": [],
                "raw_logcat_observed_count": raw_counts.get(digest, 0),
                "runner_observed_count": runner_counts.get(digest, 0),
                "parser_accepted": False,
                "outcome": "OBSERVED_WITHOUT_LEDGER_RECORD",
            })

    if not complete:
        primary = "H. EVIDENCE_INCOMPLETE"
    else:
        order = (
            ("NOT_ATTEMPTED", "A. HELPER_FRAME_NOT_ATTEMPTED"),
            ("OBSERVED_WITHOUT_LEDGER_RECORD", "F. REQUEST_CORRELATION_OR_INTERLEAVING_DEFECT"),
            ("LOG_API_RETURN_FAILURE", "B. LOG_API_RETURN_FAILURE"),
            ("API_NO_POSITIVE_ACK", "B. API_NO_POSITIVE_ACK"),
            ("LOG_API_SUCCESS_RAW_LOGCAT_MISSING", "C. LOG_API_SUCCESS_RAW_LOGCAT_MISSING"),
            ("RAW_PRESENT_RUNNER_MISSING", "D. RAW_LOGCAT_PRESENT_RUNNER_MISSING"),
            ("RUNNER_PRESENT_PARSER_REJECTED", "E. RUNNER_PRESENT_PARSER_REJECTED"),
            ("CAPTURE_CHANNEL_DISAGREEMENT", "H. EVIDENCE_INCOMPLETE"),
            ("EVIDENCE_INCOMPLETE", "H. EVIDENCE_INCOMPLETE"),
        )
        primary = next((label for key, label in order if key in outcomes), "G. NO_LOSS_OBSERVED_THIS_SINGLE_DIAGNOSTIC")

    expected_chunk_count = int(summary.get("expected_chunk_count") or 0)
    chunk61 = next((row for row in matrix if row.get("frame_type") == "CHUNK" and row.get("chunk_index") == 61), None)
    end = next((row for row in matrix if row.get("frame_type") == "END"), None)
    attempt_count = sum(1 for row in attempt_rows if row.get("at") is True)
    api_success_count = sum(1 for row in attempt_rows if row.get("ok") is True)
    raw_observed_count = sum(1 for row in matrix if row["raw_logcat_observed_count"] > 0)
    runner_observed_count = sum(1 for row in matrix if row["runner_observed_count"] > 0)
    parser_accepted_count = sum(1 for row in matrix if row["parser_accepted"])
    return {
        "primary_loss_layer": primary,
        "summary_complete": complete,
        "request_id": request_id,
        "expected_chunk_count": expected_chunk_count,
        "helper_attempted_frame_count": attempt_count,
        "helper_log_api_success_count": api_success_count,
        "raw_logcat_observed_frame_count": raw_observed_count,
        "runner_observed_frame_count": runner_observed_count,
        "parser_accepted_frame_count": parser_accepted_count,
        "end": end,
        "chunk61": {
            "expected": expected_chunk_count > 61,
            "constructed": chunk61 is not None,
            **(chunk61 or {}),
        },
        "parser_result": parser_result,
        "missing_frame_matrix": matrix,
        "raw_capture_has_duplicates": any(count > 1 for count in raw_counts.values()),
        "runner_snapshot_duplicate_lines": any(count > 1 for count in runner_counts.values()),
        "api_success_proves_logd_delivery": False,
        "api_success_proves_host_delivery": False,
    }
