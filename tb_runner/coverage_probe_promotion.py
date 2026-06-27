from __future__ import annotations

from typing import Any


PROMOTABLE = "PROMOTABLE"
NOT_PROMOTABLE = "NOT_PROMOTABLE"
ALLOWED_SUCCESS_SOURCES = {"HELPER_SUCCESS", "LATE_FOCUS_VERIFIED"}


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def evaluate_probe_promotion(item: dict[str, Any]) -> dict[str, str]:
    skipped = _bool_value(item.get("probe_skipped"))
    skip_reason = str(item.get("skip_reason", "") or "").strip().lower()
    if skipped:
        if skip_reason in {"screen_not_active", "screen_off", "keyguard_active"}:
            reason = "screen_skip"
        elif skip_reason == "foreground_not_target_app" or skip_reason.startswith("environment"):
            reason = "environment_skip"
        else:
            reason = "probe_skipped"
        return {"promotion_status": NOT_PROMOTABLE, "promotion_reason": reason}

    if not _bool_value(item.get("probe_success")):
        return {"promotion_status": NOT_PROMOTABLE, "promotion_reason": "probe_failed"}

    validation_status = str(item.get("validation_status", "") or "").strip().upper()
    if validation_status == "PARTIAL_MATCH":
        return {"promotion_status": NOT_PROMOTABLE, "promotion_reason": "partial_validation"}
    if validation_status != "MATCH":
        return {"promotion_status": NOT_PROMOTABLE, "promotion_reason": "validation_not_match"}

    success_source = str(item.get("probe_success_source", "") or "").strip().upper()
    if success_source not in ALLOWED_SUCCESS_SOURCES:
        return {"promotion_status": NOT_PROMOTABLE, "promotion_reason": "unsupported_success_source"}

    return {"promotion_status": PROMOTABLE, "promotion_reason": "exact_probe_match"}


def apply_probe_promotion(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, **evaluate_probe_promotion(item)}
