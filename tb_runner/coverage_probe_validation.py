from __future__ import annotations

import json
import re
import string
from pathlib import Path
from typing import Any


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


def coverage_probe_validation_path(output_path: str) -> Path:
    path = Path(output_path)
    return path.with_name(f"{path.stem}.coverage_probe_validation.json")


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
        "probe_success": bool(result.get("probe_success")),
        "probe_success_source": str(result.get("probe_success_source", "") or ""),
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

    containment_channels = _matched_channels(channels, lambda value: bool(normalized_label and normalized_label in value))
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
    validations = [validate_probe_result(result) for result in results if isinstance(result, dict)]
    summary = {
        "result_count": len(validations),
        "validated_count": sum(1 for item in validations if item["validation_status"] not in {"NOT_VALIDATED"}),
        "match_count": sum(1 for item in validations if item["validation_status"] == "MATCH"),
        "partial_match_count": sum(1 for item in validations if item["validation_status"] == "PARTIAL_MATCH"),
        "mismatch_count": sum(1 for item in validations if item["validation_status"] == "MISMATCH"),
        "no_speech_or_text_count": sum(1 for item in validations if item["validation_status"] == "NO_SPEECH_OR_TEXT"),
        "not_validated_count": sum(1 for item in validations if item["validation_status"] == "NOT_VALIDATED"),
    }
    return {
        "schema_version": 1,
        "source": VALIDATION_SOURCE,
        "probe_results_path": str(probe_results_path),
        "output_path": str(output_path),
        "summary": summary,
        "validations": validations,
    }


def write_validation_file(
    probe_results_payload: dict[str, Any],
    *,
    probe_results_path: str | Path,
    output_path: str,
) -> dict[str, Any]:
    payload = build_validation_payload(
        probe_results_payload,
        probe_results_path=str(probe_results_path),
        output_path=output_path,
    )
    target = coverage_probe_validation_path(output_path)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
