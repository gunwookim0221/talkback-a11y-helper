from __future__ import annotations

import base64
import binascii
import hashlib
import re
from typing import Any, Callable

from talkback_lib.constants import LOGCAT_FILTER_SPECS


class LogcatReader:
    """logcat 읽기/marker 및 payload 추출을 담당하는 얇은 래퍼."""

    def __init__(self, run_cmd: Callable[..., str]) -> None:
        self._run_cmd = run_cmd

    def dump_filtered(self, dev: Any = None) -> str:
        return self._run_cmd(["logcat", "-d", *LOGCAT_FILTER_SPECS], dev=dev)

    def dump_raw_filtered(self, dev: Any = None) -> str:
        return self._run_cmd(["logcat", "-v", "raw", "-d", *LOGCAT_FILTER_SPECS], dev=dev)

    @staticmethod
    def extract_all_payloads(log_text: str, prefix: str) -> list[str]:
        pattern = re.compile(rf"{re.escape(prefix)}\s+(.*)$")
        payloads: list[str] = []
        for line in log_text.splitlines():
            match = pattern.search(line)
            if match:
                payloads.append(LogcatReader.extract_json_object_candidate(match.group(1).strip()))
        return payloads

    @staticmethod
    def reassemble_chunked_payload(
        log_text: str,
        prefix: str,
        req_id: str,
        *,
        max_chunks: int = 512,
        max_payload_bytes: int = 1024 * 1024,
    ) -> dict[str, Any]:
        """Reassemble one bounded helper payload without accepting partial data."""
        marker = f"{prefix}_CHUNK"
        pattern = re.compile(
            r"^reqId=([^\s]+) index=(\d+) count=(\d+) "
            r"sha256=([0-9a-f]{64}) payload=([A-Za-z0-9+/=]+)$"
        )
        chunks: dict[int, bytes] = {}
        expected_count: int | None = None
        expected_digest: str | None = None

        for line in log_text.splitlines():
            marker_index = line.find(marker)
            if marker_index < 0:
                continue
            record = line[marker_index + len(marker) :].strip()
            if not re.match(rf"^reqId={re.escape(req_id)}(?:\s|$)", record):
                continue
            match = pattern.fullmatch(record)
            if not match:
                return {"state": "error", "reason": "invalid_chunk_record"}
            record_req_id, raw_index, raw_count, digest, encoded = match.groups()
            if record_req_id != req_id:
                continue
            index = int(raw_index)
            count = int(raw_count)
            if count < 1 or count > max_chunks or index >= count:
                return {"state": "error", "reason": "invalid_chunk_bounds"}
            if expected_count is not None and (count != expected_count or digest != expected_digest):
                return {"state": "error", "reason": "inconsistent_chunk_metadata"}
            expected_count = count
            expected_digest = digest
            if index in chunks:
                return {"state": "error", "reason": "duplicate_chunk"}
            try:
                chunk = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                return {"state": "error", "reason": "invalid_chunk_encoding"}
            if len(chunk) > 2048:
                return {"state": "error", "reason": "chunk_exceeds_limit"}
            chunks[index] = chunk
            if sum(map(len, chunks.values())) > max_payload_bytes:
                return {"state": "error", "reason": "payload_exceeds_limit"}

        if expected_count is None:
            return {"state": "absent"}
        missing = [index for index in range(expected_count) if index not in chunks]
        if missing:
            return {"state": "incomplete", "reason": "missing_chunks", "missing": missing}

        payload_bytes = b"".join(chunks[index] for index in range(expected_count))
        actual_digest = hashlib.sha256(payload_bytes).hexdigest()
        if actual_digest != expected_digest:
            return {"state": "error", "reason": "chunk_digest_mismatch"}
        try:
            payload = payload_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return {"state": "error", "reason": "payload_not_utf8"}
        return {"state": "complete", "payload": payload}

    @staticmethod
    def extract_req_payloads(log_text: str, prefix: str, req_id: str) -> list[str]:
        pattern = re.compile(rf"{re.escape(prefix)}\s+{re.escape(req_id)}\s+(.*)$")
        payloads: list[str] = []
        for line in log_text.splitlines():
            match = pattern.search(line)
            if match:
                payloads.append(match.group(1).strip())
        return payloads

    @staticmethod
    def extract_json_object_candidate(payload: str) -> str:
        """Return the first complete JSON object after a log prefix.

        logcat lines can contain transport noise after the helper JSON.  Keep
        malformed/truncated payloads intact so the caller can return a
        parse_error result with useful raw context.
        """
        start = payload.find("{")
        if start < 0:
            return payload.strip()

        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(payload)):
            char = payload[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return payload[start : index + 1].strip()

        return payload[start:].strip()

    @staticmethod
    def has_req_marker(log_text: str, prefix: str, req_id: str) -> bool:
        marker = f"{prefix} {req_id}"
        return any(marker in line for line in log_text.splitlines())
