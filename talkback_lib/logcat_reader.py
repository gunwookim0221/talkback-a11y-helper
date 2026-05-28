from __future__ import annotations

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
