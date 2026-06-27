from __future__ import annotations

import json
import re
import string
from pathlib import Path
from typing import Any

from tb_runner.coverage_probe_promotion import PROMOTABLE, apply_probe_promotion


VALIDATION_SOURCE = "v8_coverage_probe_validation"
WEAK_TOKENS = {
    "button",
    "graph",
    "collapsed",
    "expanded",
    "tab",
    "card",
    "view",
    "sensor",
    "history",
    "smartthings",
    "plugin",
}
BOUNDARY_ONLY_TOKENS = {"on", "off", "tv", "up"}


def coverage_probe_validation_path(output_path: str) -> Path:
    path = Path(output_path)
    return path.with_name(f"{path.stem}.coverage_probe_validation.json")


def coverage_probe_validation_aggregate_path(output_path: str) -> Path:
    path = Path(output_path)
    return path.with_name(f"{path.stem}.coverage_probe_validation.aggregate.json")


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("％", "%")
    punctuation = "".join(ch for ch in string.punctuation if ch != "%")
    text = text.translate(str.maketrans({ch: " " for ch in punctuation}))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _value_forms(value: str) -> set[str]:
    normalized = _normalize_text(value)
    forms = {normalized} if normalized else set()
    forms.add(re.sub(r"\b(\d+)\s+percent\b", r"\1%", normalized))
    forms.add(re.sub(r"\b(\d+)%\b", r"\1 percent", normalized))
    return {form.strip() for form in forms if form.strip()}


def _meaningful_tokens(value: Any) -> list[str]:
    normalized = _normalize_text(value)
    tokens = re.findall(r"\d+%|[a-z0-9]+", normalized)
    return [token for token in tokens if token and token not in WEAK_TOKENS]


def _token_phrase_matches(label: str, value: str) -> bool:
    normalized_label = _normalize_text(label)
    normalized_value = _normalize_text(value)
    if not normalized_label or not normalized_value:
        return False
    label_tokens = _meaningful_tokens(normalized_label)
    if not label_tokens:
        return False
    if any(len(token) <= 2 or token in BOUNDARY_ONLY_TOKENS for token in label_tokens):
        pattern = r"\b" + r"\s+".join(re.escape(token) for token in label_tokens) + r"\b"
        return bool(re.search(pattern, normalized_value))
    return normalized_label in normalized_value


def _short_token_false_positive_prevented(label: str, value: str) -> bool:
    normalized_value = _normalize_text(value)
    short_tokens = [
        token for token in _meaningful_tokens(label) if len(token) <= 2 or token in BOUNDARY_ONLY_TOKENS
    ]
    value_tokens = set(_meaningful_tokens(value))
    return any(token in normalized_value and token not in value_tokens for token in short_tokens)


def _result_label(result: dict[str, Any]) -> str:
    for key in ("label", "normalized_label"):
        value = str(result.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _matched_channels(channels: dict[str, str], predicate) -> list[str]:
    return [name for name, value in channels.items() if value and predicate(value)]


def validate_probe_result(result: dict[str, Any]) -> dict[str, Any]:
    label = _result_label(result)
    normalized_label = _normalize_text(label)
    captured_speech = str(result.get("captured_speech", "") or "").strip()
    captured_visible = str(result.get("captured_visible_text", "") or "").strip()
    channels = {
        "speech": _normalize_text(captured_speech),
        "visible_text": _normalize_text(captured_visible),
    }
    base = {
        "label": str(result.get("label", "") or ""),
        "normalized_label": normalized_label,
        "scenario_id": str(result.get("scenario_id", "") or ""),
        "tab_name": str(result.get("tab_name", "") or ""),
        "view_id": str(result.get("view_id", "") or ""),
        "taxonomy": str(result.get("taxonomy", "") or ""),
        "coverage_status": str(result.get("coverage_status", "") or ""),
        "coverage_reason": str(result.get("coverage_reason", "") or ""),
        "probe_intent": str(result.get("probe_intent", "") or ""),
        "probe_target_strategy": str(result.get("probe_target_strategy", "") or ""),
        "probe_target_label": str(result.get("probe_target_label", "") or ""),
        "probe_target_view_id": str(result.get("probe_target_view_id", "") or ""),
        "bounds": str(result.get("bounds", "") or ""),
        "probe_bounds": str(result.get("probe_bounds", "") or ""),
        "probe_success": bool(result.get("probe_success")),
        "probe_success_source": str(result.get("probe_success_source", "") or ""),
        "probe_skipped": bool(result.get("probe_skipped")),
        "skip_reason": str(result.get("skip_reason", "") or ""),
        "failure_reason": str(result.get("failure_reason", "") or ""),
        "foreground_package": str(result.get("foreground_package", "") or ""),
        "screen_state": str(result.get("screen_state", "") or ""),
        "captured_speech": captured_speech,
        "captured_visible_text": captured_visible,
        "validation_status": "",
        "validation_reason": "",
        "validation_confidence": "",
        "matched_channels": [],
        "expected_terms": _meaningful_tokens(label),
        "matched_terms": [],
        "missing_terms": [],
        "notes": [],
    }
    false_positive_prevented = any(
        _short_token_false_positive_prevented(label, channel_value)
        for channel_value in (captured_speech, captured_visible)
    )
    if false_positive_prevented:
        base["notes"] = ["short_token_boundary_prevented_false_positive"]

    if not bool(result.get("attempted")):
        return {
            **base,
            "validation_status": "NOT_VALIDATED",
            "validation_reason": "probe_skipped",
            "validation_confidence": "NONE",
            "notes": ["probe_skipped"],
        }
    if not bool(result.get("probe_success")):
        return {
            **base,
            "validation_status": "NOT_VALIDATED",
            "validation_reason": "probe_failed",
            "validation_confidence": "NONE",
            "notes": ["probe_failed"],
        }
    if not captured_speech and not captured_visible:
        return {
            **base,
            "validation_status": "NO_SPEECH_OR_TEXT",
            "validation_reason": "no_speech_or_visible_text",
            "validation_confidence": "NONE",
            "notes": ["no_speech_or_visible_text"],
        }

    exact_channels = _matched_channels(channels, lambda value: bool(normalized_label and value == normalized_label))
    if exact_channels:
        return {
            **base,
            "validation_status": "MATCH",
            "validation_reason": "exact_normalized_match",
            "validation_confidence": "HIGH",
            "matched_channels": exact_channels,
            "matched_terms": base["expected_terms"],
            "missing_terms": [],
        }

    label_forms = _value_forms(label)
    value_channels = _matched_channels(
        channels,
        lambda value: any(
            label_form and any(label_form in value_form for value_form in _value_forms(value))
            for label_form in label_forms
        ),
    )
    if value_channels and re.search(r"\d+%", " ".join(label_forms)):
        return {
            **base,
            "validation_status": "MATCH",
            "validation_reason": "numeric_value_match",
            "validation_confidence": "HIGH",
            "matched_channels": value_channels,
            "matched_terms": base["expected_terms"],
            "missing_terms": [],
        }

    containment_channels = _matched_channels(channels, lambda value: _token_phrase_matches(label, value))
    if containment_channels:
        return {
            **base,
            "validation_status": "MATCH",
            "validation_reason": "captured_text_contains_expected_label",
            "validation_confidence": "HIGH",
            "matched_channels": containment_channels,
            "matched_terms": base["expected_terms"],
            "missing_terms": [],
        }

    expected_terms = base["expected_terms"]
    all_token_channels = _matched_channels(
        channels,
        lambda value: bool(expected_terms) and all(term in _meaningful_tokens(value) for term in expected_terms),
    )
    if all_token_channels:
        return {
            **base,
            "validation_status": "MATCH",
            "validation_reason": "captured_text_contains_all_expected_terms",
            "validation_confidence": "HIGH",
            "matched_channels": all_token_channels,
            "matched_terms": expected_terms,
            "missing_terms": [],
        }

    captured_terms_by_channel = {name: set(_meaningful_tokens(value)) for name, value in channels.items()}
    matched_terms = sorted({term for term in expected_terms if any(term in terms for terms in captured_terms_by_channel.values())})
    missing_terms = [term for term in expected_terms if term not in matched_terms]
    if matched_terms:
        return {
            **base,
            "validation_status": "PARTIAL_MATCH",
            "validation_reason": "meaningful_token_overlap",
            "validation_confidence": "MEDIUM",
            "matched_channels": [name for name, terms in captured_terms_by_channel.items() if any(term in terms for term in matched_terms)],
            "matched_terms": matched_terms,
            "missing_terms": missing_terms,
        }

    return {
        **base,
        "validation_status": "MISMATCH",
        "validation_reason": "no_meaningful_token_overlap",
        "validation_confidence": "LOW",
        "matched_channels": [],
        "matched_terms": [],
        "missing_terms": expected_terms,
    }


def build_validation_payload(probe_results_payload: dict[str, Any], *, probe_results_path: str, output_path: str) -> dict[str, Any]:
    results = probe_results_payload.get("results", []) if isinstance(probe_results_payload, dict) else []
    validations = [
        apply_probe_promotion(validate_probe_result(result))
        for result in results
        if isinstance(result, dict)
    ]
    summary = {
        "result_count": len(validations),
        "validated_count": sum(1 for item in validations if item["validation_status"] not in {"NOT_VALIDATED"}),
        "match_count": sum(1 for item in validations if item["validation_status"] == "MATCH"),
        "partial_match_count": sum(1 for item in validations if item["validation_status"] == "PARTIAL_MATCH"),
        "mismatch_count": sum(1 for item in validations if item["validation_status"] == "MISMATCH"),
        "no_speech_or_text_count": sum(1 for item in validations if item["validation_status"] == "NO_SPEECH_OR_TEXT"),
        "not_validated_count": sum(1 for item in validations if item["validation_status"] == "NOT_VALIDATED"),
        "promotable_count": sum(1 for item in validations if item["promotion_status"] == PROMOTABLE),
        "not_promotable_count": sum(1 for item in validations if item["promotion_status"] != PROMOTABLE),
        "scenario_filtered_count": int(probe_results_payload.get("summary", {}).get("scenario_filtered_count", 0) or 0),
        "screen_skipped_count": int(probe_results_payload.get("summary", {}).get("screen_skipped_count", 0) or 0),
        "validation_false_positive_prevented_count": sum(
            1
            for item in validations
            if "short_token_boundary_prevented_false_positive" in item.get("notes", [])
        ),
    }
    return {
        "schema_version": 1,
        "source": VALIDATION_SOURCE,
        "probe_results_path": str(probe_results_path),
        "output_path": str(output_path),
        "summary": summary,
        "validations": validations,
    }


def _int_summary(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _validation_plugin_name(validations: list[Any]) -> str:
    for item in validations:
        if not isinstance(item, dict):
            continue
        for key in ("plugin_name", "plugin", "tab_name"):
            value = str(item.get(key, "") or "").strip()
            if value:
                return value
    return ""


def _validation_aggregate_entry(payload: dict[str, Any], current_scenario_id: str) -> dict[str, Any]:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    validations = payload.get("validations", []) if isinstance(payload.get("validations"), list) else []
    scenario_id = str(current_scenario_id or "").strip()
    if not scenario_id:
        for item in validations:
            if isinstance(item, dict) and str(item.get("scenario_id", "") or "").strip():
                scenario_id = str(item.get("scenario_id", "") or "").strip()
                break
    return {
        "scenario_id": scenario_id,
        "plugin_name": _validation_plugin_name(validations),
        "result_count": _int_summary(summary, "result_count"),
        "validated_count": _int_summary(summary, "validated_count"),
        "match_count": _int_summary(summary, "match_count"),
        "partial_match_count": _int_summary(summary, "partial_match_count"),
        "mismatch_count": _int_summary(summary, "mismatch_count"),
        "not_validated_count": _int_summary(summary, "not_validated_count"),
        "promotable_count": _int_summary(summary, "promotable_count"),
        "not_promotable_count": _int_summary(summary, "not_promotable_count"),
        "screen_skipped_count": _int_summary(summary, "screen_skipped_count"),
        "scenario_filtered_count": _int_summary(summary, "scenario_filtered_count"),
        "validation_false_positive_prevented_count": _int_summary(
            summary,
            "validation_false_positive_prevented_count",
        ),
        "summary": dict(summary),
        "validations": validations,
    }


def _build_validation_aggregate(output_path: str, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    validations = [
        validation
        for scenario in scenarios
        for validation in scenario.get("validations", [])
        if isinstance(validation, dict)
    ]
    return {
        "schema_version": 1,
        "source": "v8_probe_validation_aggregate",
        "run_id": Path(output_path).stem,
        "output_path": str(output_path),
        "scenario_count": len(scenarios),
        "total_result_count": sum(_int_summary(item, "result_count") for item in scenarios),
        "total_validated_count": sum(_int_summary(item, "validated_count") for item in scenarios),
        "total_match_count": sum(_int_summary(item, "match_count") for item in scenarios),
        "total_partial_match_count": sum(_int_summary(item, "partial_match_count") for item in scenarios),
        "total_mismatch_count": sum(_int_summary(item, "mismatch_count") for item in scenarios),
        "total_not_validated_count": sum(_int_summary(item, "not_validated_count") for item in scenarios),
        "promotable_count": sum(_int_summary(item, "promotable_count") for item in scenarios),
        "not_promotable_count": sum(_int_summary(item, "not_promotable_count") for item in scenarios),
        "total_screen_skipped_count": sum(_int_summary(item, "screen_skipped_count") for item in scenarios),
        "total_scenario_filtered_count": sum(_int_summary(item, "scenario_filtered_count") for item in scenarios),
        "total_validation_false_positive_prevented_count": sum(
            _int_summary(item, "validation_false_positive_prevented_count") for item in scenarios
        ),
        "scenarios": scenarios,
        "validations": validations,
    }


def append_validation_aggregate_file(
    payload: dict[str, Any],
    *,
    output_path: str,
    current_scenario_id: str = "",
) -> dict[str, Any]:
    target = coverage_probe_validation_aggregate_path(output_path)
    scenarios: list[dict[str, Any]] = []
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            existing_scenarios = existing.get("scenarios", []) if isinstance(existing, dict) else []
            if isinstance(existing_scenarios, list):
                scenarios = [item for item in existing_scenarios if isinstance(item, dict)]
        except Exception:
            scenarios = []
    scenarios.append(_validation_aggregate_entry(payload, current_scenario_id))
    aggregate = _build_validation_aggregate(output_path, scenarios)
    target.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    return aggregate


def write_validation_file(
    probe_results_payload: dict[str, Any],
    *,
    probe_results_path: str | Path,
    output_path: str,
    current_scenario_id: str = "",
) -> dict[str, Any]:
    payload = build_validation_payload(
        probe_results_payload,
        probe_results_path=str(probe_results_path),
        output_path=output_path,
    )
    target = coverage_probe_validation_path(output_path)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    append_validation_aggregate_file(
        payload,
        output_path=output_path,
        current_scenario_id=current_scenario_id,
    )
    return payload
