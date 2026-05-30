from __future__ import annotations

import re
from typing import Any

from talkback_lib.constants import STATUS_FAILED, STATUS_MOVED


class _NormalizedActionResult(dict):
    def __bool__(self) -> bool:
        return bool(self.get("success"))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return str(self.get("status", "")) == other
        return super().__eq__(other)


class ActionResultParser:
    """action result 저수준 판정/정규화 보조 래퍼."""

    @staticmethod
    def target_action_parse_error_result(
        req_id: str,
        raw_payload: str,
        error: Exception | str,
    ) -> dict[str, Any]:
        return ActionResultParser.log_parse_error_result(
            prefix="TARGET_ACTION_RESULT",
            req_id=req_id,
            raw_payload=raw_payload,
            error=error,
        )

    @staticmethod
    def focus_parse_error_result(
        req_id: str,
        raw_payload: str,
        error: Exception | str,
    ) -> dict[str, Any]:
        return ActionResultParser.log_parse_error_result(
            prefix="FOCUS_RESULT",
            req_id=req_id,
            raw_payload=raw_payload,
            error=error,
        )

    @staticmethod
    def log_parse_error_result(
        prefix: str,
        req_id: str,
        raw_payload: str,
        error: Exception | str,
    ) -> dict[str, Any]:
        raw_text = str(raw_payload)
        raw_snippet = raw_text.replace("\n", "\\n")[:240]
        result: dict[str, Any] = {
            "success": False,
            "status": "parse_error",
            "reason": "json_parse_failed",
            "prefix": prefix,
            "reqId": req_id,
            "rawSnippet": raw_snippet,
            "parseError": str(error),
        }
        for key in ("packageName", "className"):
            match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', raw_text)
            if match:
                result[key] = match.group(1)
        return result

    @staticmethod
    def normalize_action_result(
        success: bool,
        status: str | None = None,
        detail: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_status = status or (STATUS_MOVED if bool(success) else STATUS_FAILED)
        result: dict[str, Any] = _NormalizedActionResult(
            {
                "success": bool(success),
                "status": normalized_status,
            }
        )
        if detail is not None:
            result["detail"] = detail
        if isinstance(raw, dict):
            result["raw"] = raw
        return result

    @staticmethod
    def is_target_action_payload_missing(result: dict[str, Any], req_id: str) -> bool:
        return (
            isinstance(result, dict)
            and result.get("reqId") == req_id
            and str(result.get("reason", "")).strip() == "TARGET_ACTION_RESULT 로그를 찾지 못했습니다."
        )

    @staticmethod
    def is_target_action_success(result: Any) -> bool:
        return isinstance(result, dict) and bool(result.get("success"))

    @staticmethod
    def is_target_action_payload_for_req(result: dict[str, Any], req_id: str) -> bool:
        return isinstance(result, dict) and result.get("reqId") == req_id

    @staticmethod
    def normalize_target_action_payload(result: Any) -> dict[str, Any]:
        return result if isinstance(result, dict) else {"success": False, "reason": "unknown"}
