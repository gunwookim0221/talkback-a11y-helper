from __future__ import annotations

import base64
import hashlib
import json

import pytest

from talkback_lib.hierarchy_publication_evidence import (
    PublicationEvidenceError,
    compare_publication_layers,
    decode_broadcast_stdout,
    decode_report_data,
    parse_hierarchy_capture,
    validate_page,
)


REQUEST = "hpub-test-req"
NONCE = "page-nonce-01"
PAYLOAD = json.dumps(
    {"reqId": REQUEST, "success": True, "nodes": [{"className": "Button"}], "windows": [{"id": 1}]},
    separators=(",", ":"),
)
PAYLOAD_BYTES = PAYLOAD.encode("utf-8")
PAYLOAD_SHA = hashlib.sha256(PAYLOAD_BYTES).hexdigest()
CHUNK_MESSAGE = (
    f"DUMP_HIERARCHY_RESULT_CHUNK reqId={REQUEST} index=0 count=1 "
    f"sha256={PAYLOAD_SHA} payload={base64.b64encode(PAYLOAD_BYTES).decode('ascii')}"
)
END_MESSAGE = f"DUMP_HIERARCHY_END {REQUEST}"


def _row(message: str, *, sequence: int, frame_type: str, index: int | None = None) -> dict:
    return {"s": sequence, "t": frame_type, "i": index, "c": 1 if frame_type == "CHUNK" else None,
            "rb": len(PAYLOAD_BYTES), "cb": len(PAYLOAD_BYTES) if frame_type == "CHUNK" else None,
            "mb": len(message.encode()), "d": hashlib.sha256(message.encode()).hexdigest(), "rd": PAYLOAD_SHA}


def _attempt(sequence: int, *, return_class: str = "POSITIVE", accepted: bool | None = True) -> dict:
    return {"s": sequence, "p": sequence + 1, "a": 1, "at": True, "rv": 1 if accepted else -13,
            "ok": accepted, "rc": return_class, "ec": None}


def _summary(*, complete: bool = True) -> dict:
    return {"request_id": REQUEST, "expected_chunk_count": 1, "descriptor_count": 2, "attempt_count": 2,
            "evidence_complete": complete, "plan_complete": complete, "finalized": True, "report_revision": 1}


def _frames(*, include_chunk: bool = True, include_end: bool = True) -> str:
    return "\n".join(([CHUNK_MESSAGE] if include_chunk else []) + ([END_MESSAGE] if include_end else []))


def _plans() -> list[dict]:
    return [_row(CHUNK_MESSAGE, sequence=0, frame_type="CHUNK", index=0),
            _row(END_MESSAGE, sequence=1, frame_type="END")]


def _compare(*, raw: str | None = None, runner: str | None = None, parser: dict | None = None,
             plans: list[dict] | None = None, attempts: list[dict] | None = None, complete: bool = True,
             expected_chunk_count: int = 1) -> dict:
    raw_value = _frames() if raw is None else raw
    runner_value = _frames() if runner is None else runner
    parser_value = parse_hierarchy_capture(runner_value, REQUEST) if parser is None else parser
    attempt_values = [_attempt(0), _attempt(1)] if attempts is None else attempts
    plan_values = _plans() if plans is None else plans
    summary = _summary(complete=complete)
    summary["expected_chunk_count"] = expected_chunk_count
    return compare_publication_layers(summary, plan_values, attempt_values,
                                      raw_value, runner_value, parser_value, REQUEST)


def _report(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"HPUB1.{body}.{hashlib.sha256(raw).hexdigest()}"


def test_all_chunks_end_and_parser_acceptance_are_observed_end_to_end():
    result = _compare()
    assert result["primary_loss_layer"].startswith("G.")
    assert result["helper_attempted_frame_count"] == 2
    assert result["raw_logcat_observed_frame_count"] == 2
    assert result["runner_observed_frame_count"] == 2
    assert result["parser_accepted_frame_count"] == 2
    assert result["api_success_proves_logd_delivery"] is False
    assert result["api_success_proves_host_delivery"] is False


def test_negative_chunk_log_return_is_distinct():
    result = _compare(attempts=[_attempt(0, return_class="NEGATIVE", accepted=False), _attempt(1)])
    assert result["primary_loss_layer"] == "B. LOG_API_RETURN_FAILURE"
    assert result["missing_frame_matrix"][0]["outcome"] == "LOG_API_RETURN_FAILURE"


def test_zero_return_is_not_misreported_as_native_rejection():
    result = _compare(attempts=[_attempt(0, return_class="ZERO", accepted=False), _attempt(1)])
    assert result["missing_frame_matrix"][0]["outcome"] == "API_NO_POSITIVE_ACK"


def test_positive_api_return_with_missing_chunk_is_layer_c():
    result = _compare(raw=_frames(include_chunk=False), runner=_frames(include_chunk=False))
    assert result["primary_loss_layer"] == "C. LOG_API_SUCCESS_RAW_LOGCAT_MISSING"
    assert result["parser_result"]["accepted"] is False


def test_positive_api_return_with_missing_end_is_layer_c():
    result = _compare(raw=_frames(include_end=False), runner=_frames(include_end=False))
    assert result["primary_loss_layer"] == "C. LOG_API_SUCCESS_RAW_LOGCAT_MISSING"
    assert result["end"]["frame_type"] == "END"
    assert result["end"]["outcome"] == "LOG_API_SUCCESS_RAW_LOGCAT_MISSING"


def test_raw_frame_missing_from_runner_snapshot_is_layer_d():
    result = _compare(raw=_frames(), runner=END_MESSAGE)
    assert result["primary_loss_layer"] == "D. RAW_LOGCAT_PRESENT_RUNNER_MISSING"


def test_runner_frame_with_parser_rejection_is_layer_e():
    result = _compare(parser={"accepted": False, "reason": "missing_chunks"})
    assert result["primary_loss_layer"] == "E. RUNNER_PRESENT_PARSER_REJECTED"


def test_duplicate_observation_is_reported_without_combining_reader_counts():
    result = _compare(raw=_frames() + "\n" + CHUNK_MESSAGE, runner=_frames())
    assert result["raw_capture_has_duplicates"] is True
    assert result["runner_snapshot_duplicate_lines"] is False
    chunk = next(row for row in result["missing_frame_matrix"] if row["frame_type"] == "CHUNK")
    assert chunk["raw_logcat_observed_count"] == 2
    assert chunk["runner_observed_count"] == 1


def test_observed_frame_without_ledger_record_is_a_correlation_defect():
    extra = f"DUMP_HIERARCHY_RESULT_CHUNK reqId={REQUEST} index=2 count=3 sha256={'f' * 64} payload=YQ=="
    result = _compare(raw=_frames() + "\n" + extra, plans=_plans(), attempts=[_attempt(0), _attempt(1)])
    assert result["primary_loss_layer"] == "F. REQUEST_CORRELATION_OR_INTERLEAVING_DEFECT"
    assert any(row["outcome"] == "OBSERVED_WITHOUT_LEDGER_RECORD" for row in result["missing_frame_matrix"])


def test_incomplete_ledger_never_infers_not_attempted_or_no_loss():
    result = _compare(plans=[_plans()[0]], attempts=[], raw="", runner="", complete=False,
                      parser={"accepted": False, "reason": "missing_chunks"})
    assert result["primary_loss_layer"] == "H. EVIDENCE_INCOMPLETE"
    assert result["missing_frame_matrix"][0]["outcome"] == "EVIDENCE_INCOMPLETE"


def test_exact_chunk_61_surfaces_without_changing_transport_behavior():
    row = _row(CHUNK_MESSAGE.replace("index=0", "index=61").replace("count=1", "count=62"),
               sequence=61, frame_type="CHUNK", index=61)
    row["d"] = hashlib.sha256(CHUNK_MESSAGE.replace("index=0", "index=61").replace("count=1", "count=62").encode()).hexdigest()
    result = _compare(raw="", runner="", plans=[row], attempts=[_attempt(61)], complete=True, expected_chunk_count=62,
                      parser={"accepted": False, "reason": "missing_chunks"})
    assert result["chunk61"]["expected"] is True
    assert result["chunk61"]["constructed"] is True
    assert result["chunk61"]["chunk_index"] == 61


def test_end_is_independently_auditable():
    result = _compare()
    assert result["end"]["frame_type"] == "END"
    assert result["end"]["helper_attempted"] is True
    assert result["end"]["outcome"] == "OBSERVED_END_TO_END"


def test_report_envelope_is_verified_and_nonce_bound():
    data = {"schema": "hierarchy-publication-report.v1", "status": "OK", "query_nonce": NONCE}
    encoded = _report(data)
    assert decode_report_data(encoded, expected_nonce=NONCE)["status"] == "OK"
    stdout = f'Broadcast completed: result={0x4850}, data="{encoded}"\n'
    assert decode_broadcast_stdout(stdout, returncode=0, expected_nonce=NONCE)["query_nonce"] == NONCE


def test_envelope_rejects_truncation_digest_and_duplicate_json_keys():
    data = _report({"schema": "hierarchy-publication-report.v1", "status": "OK"})
    with pytest.raises(PublicationEvidenceError):
        decode_report_data(data[:-5])
    with pytest.raises(PublicationEvidenceError, match="digest"):
        decode_report_data(data[:-1] + ("0" if data[-1] != "0" else "1"))
    duplicate_json = b'{"schema":"hierarchy-publication-report.v1","status":"OK","status":"OK"}'
    body = base64.urlsafe_b64encode(duplicate_json).decode().rstrip("=")
    duplicate = f"HPUB1.{body}.{hashlib.sha256(duplicate_json).hexdigest()}"
    with pytest.raises(PublicationEvidenceError, match="duplicate_json_key"):
        decode_report_data(duplicate)


def test_failed_stdout_result_never_falls_back_to_logcat():
    with pytest.raises(PublicationEvidenceError, match="ordered_result_not_on_stdout"):
        decode_broadcast_stdout("Broadcast completed: result=0, data=\"\"", returncode=0,
                                expected_nonce=NONCE)
    error = _report({"schema": "hierarchy-publication-report.v1", "status": "NOT_FOUND", "query_nonce": NONCE})
    stdout = f'Broadcast completed: result={0x4851}, data="{error}"'
    with pytest.raises(PublicationEvidenceError, match="ordered_query_rejected"):
        decode_broadcast_stdout(stdout, returncode=0, expected_nonce=NONCE)


def test_page_binding_rejects_wrong_epoch_revision_or_request():
    good = {"request_id": REQUEST, "process_epoch": "p", "service_instance_id": "s",
            "capture_generation": 3, "report_revision": 1, "report_digest": "a" * 64,
            "page_kind": "PLAN", "page_index": 0, "page_count": 1, "records": [{"s": 0}]}
    assert validate_page(good, request_id=REQUEST, process_epoch="p", service_instance_id="s",
                         capture_generation=3, report_revision=1, report_digest="a" * 64,
                         page_kind="PLAN", page_index=0, page_count=1) == [{"s": 0}]
    for key, value in (("process_epoch", "other"), ("report_revision", 2), ("request_id", "other")):
        broken = dict(good, **{key: value})
        with pytest.raises(PublicationEvidenceError, match="page_binding_mismatch"):
            validate_page(broken, request_id=REQUEST, process_epoch="p", service_instance_id="s",
                          capture_generation=3, report_revision=1, report_digest="a" * 64,
                          page_kind="PLAN", page_index=0, page_count=1)


def test_raw_logcat_parser_still_rejects_missing_end_and_missing_chunks():
    assert parse_hierarchy_capture(CHUNK_MESSAGE, REQUEST)["reason"] == "terminal_count"
    incomplete = CHUNK_MESSAGE.replace("index=0", "index=1").replace("count=1", "count=2")
    parsed = parse_hierarchy_capture(incomplete + "\n" + END_MESSAGE, REQUEST)
    assert parsed["accepted"] is False
    assert parsed["reason"] == "missing_chunks"
