from __future__ import annotations

import hashlib
import json
import pytest

from talkback_lib import A11yAdbClient
from talkback_lib.logcat_reader import LogcatReader


def _chunk_records(req_id: str, payload: str, *, chunk_size: int = 1200, prefix: str = "TARGET_ACTION_RESULT") -> list[str]:
    encoded = payload.encode("utf-8")
    chunks = [encoded[index : index + chunk_size] for index in range(0, len(encoded), chunk_size)]
    digest = hashlib.sha256(encoded).hexdigest()
    import base64

    return [
        f"A11Y_HELPER: {prefix}_CHUNK "
        f"reqId={req_id} index={index} count={len(chunks)} sha256={digest} "
        f"payload={base64.b64encode(chunk).decode('ascii')}"
        for index, chunk in enumerate(chunks)
    ]


def test_small_legacy_target_result_remains_readable(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    payload = json.dumps({"reqId": "small", "success": True, "status": "TARGET_MATCHED"})
    monkeypatch.setattr(
        client._logcat_reader,
        "dump_filtered",
        lambda dev=None: f"I/A11Y_HELPER: TARGET_ACTION_RESULT {payload}",
    )

    result = client._read_log_result(None, "TARGET_ACTION_RESULT", "small", wait_seconds=0.1)

    assert result["success"] is True
    assert result["status"] == "TARGET_MATCHED"


def test_chunked_result_over_four_kilobytes_reassembles_with_korean_and_escapes(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    payload = json.dumps(
        {
            "reqId": "large",
            "success": True,
            "status": "TARGET_MATCHED",
            "message": '위치 설정 "완료"\n' + "가" * 1800,
        },
        ensure_ascii=False,
    )
    records = _chunk_records("large", payload)
    assert len(payload.encode("utf-8")) > 4096
    assert len(records) > 1
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: "\n".join(records))

    result = client._read_log_result(None, "TARGET_ACTION_RESULT", "large", wait_seconds=0.1)

    assert result["success"] is True
    assert result["status"] == "TARGET_MATCHED"
    assert result["message"].startswith('위치 설정 "완료"\n')
    assert len(result["message"]) > 1000


def test_reassembly_handles_payload_boundaries_near_previous_logcat_limit():
    for size in (3999, 4096, 4101):
        req_id = f"boundary-{size}"
        prefix = json.dumps({"reqId": req_id, "success": True, "status": "TARGET_MATCHED", "data": ""})
        fixed_size = len(prefix.encode("utf-8"))
        payload = prefix[:-2] + ("x" * (size - fixed_size)) + '"}'
        records = _chunk_records(req_id, payload)

        assembled = LogcatReader.reassemble_chunked_payload("\n".join(records), "TARGET_ACTION_RESULT", req_id)

        assert assembled["state"] == "complete"
        assert assembled["payload"] == payload
        assert len(assembled["payload"].encode("utf-8")) >= 3999


def test_incomplete_payload_is_rejected_and_never_matches_target(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    payload = json.dumps({"reqId": "missing", "success": True, "status": "TARGET_MATCHED", "tail": "x" * 3000})
    records = _chunk_records("missing", payload)
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: records[0])

    result = client._read_log_result(
        None, "TARGET_ACTION_RESULT", "missing", wait_seconds=0.07, poll_interval_sec=0.05
    )

    assert result["success"] is False
    assert result["status"] == "transport_error"
    assert result["reason"] == "incomplete_chunked_payload"
    assert result["reqId"] == "missing"


def test_duplicate_chunk_is_reported_as_transport_error(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    records = _chunk_records("duplicate", json.dumps({"reqId": "duplicate", "success": True}))
    monkeypatch.setattr(
        client._logcat_reader,
        "dump_filtered",
        lambda dev=None: "\n".join([records[0], records[0]]),
    )

    result = client._read_log_result(None, "TARGET_ACTION_RESULT", "duplicate", wait_seconds=0.1)

    assert result == {
        "success": False,
        "status": "transport_error",
        "reason": "duplicate_chunk",
        "reqId": "duplicate",
    }


def test_missing_chunk_index_is_detected_by_reassembler():
    records = _chunk_records("gap", json.dumps({"reqId": "gap", "success": True, "data": "x" * 5000}))

    result = LogcatReader.reassemble_chunked_payload(
        "\n".join(records[:-1]), "TARGET_ACTION_RESULT", "gap"
    )

    assert result["state"] == "incomplete"
    assert result["reason"] == "missing_chunks"
    assert result["missing"] == [len(records) - 1]


def test_truncated_legacy_target_result_stays_parse_error():
    client = A11yAdbClient(start_monitor=False)
    raw = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"reqId":"partial","success":true,"status":"TARGET_MATCHED"'
    payload = LogcatReader.extract_all_payloads(raw, "TARGET_ACTION_RESULT")[0]
    result = client._target_action_parse_error_result("partial", payload, "unterminated JSON")

    assert result["success"] is False
    assert result["status"] == "parse_error"
    assert result["reqId"] == "partial"


@pytest.mark.parametrize("prefix", ["SMART_NAV_RESULT", "EVIDENCE_EVENTS_RESULT"])
@pytest.mark.parametrize("size", [1000, 3999, 4096, 4101, 8192, 16384])
def test_non_target_transport_unicode_escapes_boundaries(monkeypatch, prefix, size):
    payload = json.dumps({"reqId": "result", "success": True, "data": '위치 설정 "완료"\n\\' + "가" * (size // 3)}, ensure_ascii=False)
    records = _chunk_records("result", payload, prefix=prefix)
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: "\n".join(reversed(records)))
    assert client._read_log_result(None, prefix, "result", wait_seconds=0.1) == json.loads(payload)


@pytest.mark.parametrize("prefix", ["SMART_NAV_RESULT", "EVIDENCE_EVENTS_RESULT"])
@pytest.mark.parametrize("fault,reason", [("missing", "incomplete_chunked_payload"), ("duplicate", "duplicate_chunk"), ("digest", "chunk_digest_mismatch")])
def test_non_target_transport_rejects_incomplete_corrupt_payload(monkeypatch, prefix, fault, reason):
    payload = json.dumps({"reqId": "result", "success": True, "data": "x" * 8000})
    records = _chunk_records("result", payload, prefix=prefix)
    if fault == "missing":
        records.pop(1)
    elif fault == "duplicate":
        records.append(records[0])
    else:
        digest = hashlib.sha256(payload.encode()).hexdigest()
        records = [record.replace(digest, "0" * 64) for record in records]
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: "\n".join(records))
    result = client._read_log_result(None, prefix, "result", wait_seconds=0.07)
    assert result["success"] is False
    assert result["status"] == "transport_error"
    assert result["reason"] == reason


@pytest.mark.parametrize("prefix", ["SMART_NAV_RESULT", "EVIDENCE_EVENTS_RESULT"])
def test_non_target_legacy_single_line(monkeypatch, prefix):
    payload = {"reqId": "legacy", "success": True, "message": "한국어"}
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(client._logcat_reader, "dump_filtered", lambda dev=None: f"A11Y_HELPER: {prefix} {json.dumps(payload)}")
    assert client._read_log_result(None, prefix, "legacy", wait_seconds=0.1) == payload
