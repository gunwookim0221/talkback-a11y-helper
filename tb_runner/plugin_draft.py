from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from tb_runner.runtime_config import DEFAULT_RUNTIME_CONFIG_PATH
from tb_runner.scenario_config import TAB_CONFIGS

DRAFT_SCHEMA_VERSION = "plugin-draft-v1"
REVIEW_SCHEMA_VERSION = "plugin-draft-review-v1"
APPLY_SCHEMA_VERSION = "plugin-draft-apply-v1"
SMOKE_SCHEMA_VERSION = "plugin-draft-smoke-v1"
DEFAULT_SCENARIO_CONFIG_PATH = Path("tb_runner/scenario_config.py")
DEFAULT_BACKUP_ROOT = Path("output/plugin_draft_backups")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_key(value: Any) -> str:
    text = _text(value).lower()
    return re.sub(r"\s+", " ", text).strip()


def _ascii_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)
    return slug


def _failure_response(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": DRAFT_SCHEMA_VERSION,
        "draft_status": "failed",
        "draft": {
            "scenario": {},
            "runtime_config": {},
            "metadata": {
                "source_card": {},
                "probe_status": "",
                "plugin_open_verified_candidate": False,
                "headers": [],
                "local_tabs": [],
                "representative_cards": [],
                "overlay_hints": [],
                "context_verify_text_candidates": [],
                "manual_review_required": True,
            },
        },
        "diagnostics": {
            "warnings": [],
            "notes": ["Draft only. No files were modified."],
            "failure_reason": reason,
        },
    }


def _review_failure_response(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_status": "failed",
        "checks": {
            "scenario_id_exists": False,
            "runtime_config_exists": False,
            "manual_review_required": True,
            "can_apply": False,
        },
        "preview": {
            "scenario_config_insertion_hint": "",
            "runtime_config_patch": {},
            "diff_preview": "",
        },
        "diagnostics": {
            "warnings": [],
            "errors": [reason],
        },
    }


def _apply_failure_response(reason: str, *, warnings: list[str] | None = None, errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": APPLY_SCHEMA_VERSION,
        "apply_status": "blocked",
        "changed_files": [],
        "backup": {
            "created": False,
            "paths": [],
        },
        "applied": {
            "scenario_id": "",
            "runtime_config_key": "",
        },
        "diagnostics": {
            "warnings": list(warnings or []),
            "errors": list(errors or [reason]),
        },
    }


def _smoke_failure_response(reason: str, *, scenario_id: str = "", warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SMOKE_SCHEMA_VERSION,
        "smoke_status": "blocked",
        "run_id": "",
        "scenario_id": scenario_id,
        "max_steps": 0,
        "summary": {
            "pre_navigation_success": False,
            "plugin_open_verified": False,
            "steps_collected": 0,
            "failure_reason": reason,
            "result_status": "BLOCKED",
        },
        "artifacts": {
            "log_path": "",
            "xlsx_path": "",
        },
        "diagnostics": {
            "warnings": list(warnings or []),
        },
    }


def _build_life_verify_tokens(card: dict[str, Any], probe: dict[str, Any]) -> list[str]:
    seed = probe.get("seed") if isinstance(probe, dict) else {}
    candidates = []
    if isinstance(seed, dict):
        candidates.extend(seed.get("verify_tokens") or [])
        candidates.extend(seed.get("headers") or [])
    candidates.extend([card.get("stable_label"), card.get("label")])
    results: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        label = _text(candidate)
        key = _normalize_key(label)
        if not label or not key or key in seen:
            continue
        seen.add(key)
        results.append(label)
    return results[:5]


def _build_device_target_stable_labels(card: dict[str, Any], probe: dict[str, Any]) -> list[str]:
    seed = probe.get("seed") if isinstance(probe, dict) else {}
    candidates = [_text(card.get("stable_label")), _text(card.get("label"))]
    if isinstance(seed, dict):
        for candidate in seed.get("verify_tokens") or []:
            label = _text(candidate)
            if _normalize_key(label) == _normalize_key(card.get("stable_label")):
                candidates.append(label)
    results: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _normalize_key(candidate)
        if not candidate or not key or key in seen:
            continue
        seen.add(key)
        results.append(candidate)
    return results[:3]


def _build_scenario_id(card: dict[str, Any], warnings: list[str]) -> str:
    existing_scenario_id = _text(card.get("existing_scenario_id"))
    if existing_scenario_id:
        warnings.append(f"Existing scenario id already present: {existing_scenario_id}")
        return existing_scenario_id

    card_type = _text(card.get("type")).lower()
    stable_label = _text(card.get("stable_label")) or _text(card.get("label"))
    slug = _ascii_slug(stable_label)
    if slug:
        prefix = "life" if card_type == "life" else "device"
        return f"{prefix}_{slug}_plugin"

    fallback_id = f"{card_type or 'plugin'}_plugin_candidate_001"
    warnings.append(f"Non-ASCII stable_label requires manual scenario id review: {stable_label}")
    return fallback_id


def _load_runtime_scenarios(config_path: Path | None = None) -> dict[str, Any]:
    target = Path(config_path or DEFAULT_RUNTIME_CONFIG_PATH)
    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    scenarios = payload.get("scenarios")
    return scenarios if isinstance(scenarios, dict) else {}


def _format_preview_block(title: str, payload: Any) -> str:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    lines = [f"{title}:"]
    lines.extend(f"+ {line}" for line in rendered.splitlines())
    return "\n".join(lines)


def _existing_scenario_ids() -> set[str]:
    results: set[str] = set()
    for item in TAB_CONFIGS:
        if not isinstance(item, dict):
            continue
        scenario_id = _text(item.get("scenario_id"))
        if scenario_id:
            results.add(scenario_id)
    return results


def _extract_scenario_ids_from_text(text: str) -> set[str]:
    return set(re.findall(r'["\']scenario_id["\']\s*:\s*["\']([^"\']+)["\']', text))


def scenario_id_exists_for_smoke(scenario_id: str, scenario_config_path: Path | None = None) -> bool:
    scenario_id = _text(scenario_id)
    if not scenario_id:
        return False
    if scenario_id in _existing_scenario_ids():
        return True
    path = Path(scenario_config_path or DEFAULT_SCENARIO_CONFIG_PATH)
    if not path.is_file():
        return False
    try:
        return scenario_id in _extract_scenario_ids_from_text(path.read_text(encoding="utf-8"))
    except OSError:
        return False


def _scenario_entry_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    scenario = draft.get("scenario") if isinstance(draft, dict) else {}
    metadata = draft.get("metadata") if isinstance(draft, dict) else {}
    runtime_config = draft.get("runtime_config") if isinstance(draft, dict) else {}
    scenario_id = _text(scenario.get("id"))
    tab = _text(scenario.get("tab")).lower()
    source_card = metadata.get("source_card") if isinstance(metadata, dict) else {}
    stable_label = _text(source_card.get("stable_label")) or _text(source_card.get("label"))
    context_candidates = metadata.get("context_verify_text_candidates") if isinstance(metadata, dict) else []
    max_steps = 5
    if isinstance(runtime_config, dict):
        runtime_entry = runtime_config.get(scenario_id)
        if isinstance(runtime_entry, dict):
            max_steps = int(runtime_entry.get("max_steps", 5) or 5)

    entry: dict[str, Any] = {
        "scenario_id": scenario_id,
        "scenario_type": "content",
        "entry_type": "card",
        "tab_name": "(?i).*life.*" if tab == "life" else "(?i).*devices.*",
        "tab_type": "b",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "anchor_name": "(?i).*(navigate\\s*up|상위\\s*메뉴로\\s*이동).*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*(navigate\\s*up|상위\\s*메뉴로\\s*이동).*",
            "announcement_regex": "(?i).*(navigate\\s*up|상위\\s*메뉴로\\s*이동).*",
            "tie_breaker": "top_left",
        },
        "enabled": False,
        "max_steps": max_steps,
    }

    pre_navigation = _text(scenario.get("pre_navigation"))
    if tab == "life":
        verify_tokens = [token for token in scenario.get("verify_tokens", []) if _text(token)] if isinstance(scenario, dict) else []
        target_seed = stable_label or (verify_tokens[0] if verify_tokens else scenario_id)
        entry["pre_navigation"] = [
            {
                "action": pre_navigation or "xml_scroll_search_tap",
                "target": target_seed,
                "type": "a",
            }
        ]
        if verify_tokens:
            entry["verify_tokens"] = verify_tokens
    else:
        target_stable_labels = [token for token in scenario.get("target_stable_labels", []) if _text(token)] if isinstance(scenario, dict) else []
        target_seed = stable_label or (target_stable_labels[0] if target_stable_labels else scenario_id)
        entry["pre_navigation"] = [
            {
                "action": pre_navigation or "enter_device_card_plugin",
                "target": target_seed,
                "target_stable_labels": target_stable_labels or [target_seed],
                "max_scroll_search_steps": 4,
            }
        ]

    context_regex = ""
    if isinstance(context_candidates, list) and context_candidates:
        context_regex = _text(context_candidates[0])
    elif tab == "life" and isinstance(entry.get("verify_tokens"), list) and entry["verify_tokens"]:
        escaped = [re.escape(token) for token in entry["verify_tokens"][:3]]
        context_regex = "(?i).*" + ".*|.*".join(escaped) + ".*"
    elif stable_label:
        context_regex = rf"(?i).*{re.escape(stable_label)}.*"
    if context_regex:
        entry["context_verify"] = {
            "type": "screen_text",
            "text_regex": context_regex,
        }

    return entry


def _indent_block(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def _render_scenario_entry(entry: dict[str, Any]) -> str:
    rendered = json.dumps(entry, indent=4, ensure_ascii=False)
    rendered = rendered.replace("true", "True").replace("false", "False").replace("null", "None")
    return rendered


def _append_scenario_config_entry(file_path: Path, entry: dict[str, Any]) -> None:
    text = file_path.read_text(encoding="utf-8")
    marker = "\n]\n"
    idx = text.rfind(marker)
    if idx < 0:
        raise ValueError("TAB_CONFIGS list terminator not found")
    preceding_text = text[:idx]
    block = _indent_block(_render_scenario_entry(entry), 4)
    if preceding_text.rstrip().endswith(","):
        insertion = f"\n{block}\n"
    else:
        insertion = f",\n{block}\n"
    updated = preceding_text + insertion + text[idx:]
    file_path.write_text(updated, encoding="utf-8")


def _merge_runtime_config(file_path: Path, scenario_id: str, runtime_entry: dict[str, Any]) -> None:
    payload: dict[str, Any] = {}
    if file_path.is_file():
        with file_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            payload = loaded
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, dict):
        scenarios = {}
        payload["scenarios"] = scenarios
    scenarios[scenario_id] = runtime_entry
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _create_backups(paths: list[Path], backup_root: Path) -> list[Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for path in paths:
        target = backup_dir / f"{path.name}.bak"
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        created.append(target)
    return created


def find_reusable_landing_profile(probe_seed: dict[str, Any], card_type: str, existing_scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    if card_type != "life":
        return {"matched": False}

    GENERIC_TOKENS = {
        "did_opt_navigate_up", "did_opt_more_options", "more options", 
        "close", "settings", "view details",
    }

    STRONG_TITLES = {
        "home care", "smartthings home care", "video", "find", 
        "air care", "food", "family care", "clothing care", 
        "pet care", "energy", "plant care", "home monitor",
    }

    original_tokens: list[str] = []
    for key in ["verify_tokens", "headers", "local_tabs", "context_verify_text_candidates"]:
        for token in probe_seed.get(key) or []:
            text_val = _text(token)
            if text_val and text_val not in original_tokens:
                original_tokens.append(text_val)

    best_match = None
    best_score = 0
    best_matched_tokens: list[str] = []

    for scenario in existing_scenarios:
        if not isinstance(scenario, dict):
            continue
        scenario_id = _text(scenario.get("scenario_id"))
        if not scenario_id.startswith("life_") or not scenario_id.endswith("_plugin"):
            continue

        existing_tokens = set()
        for token in scenario.get("verify_tokens") or []:
            existing_tokens.add(_normalize_key(token))
        
        matched_original: list[str] = []
        matched_normalized = set()
        for orig_t in original_tokens:
            t = _normalize_key(orig_t)
            if t in existing_tokens and t not in GENERIC_TOKENS:
                if t not in matched_normalized:
                    matched_normalized.add(t)
                    matched_original.append(orig_t)
        
        if len(matched_normalized) >= 2:
            has_strong_title = any(t in STRONG_TITLES for t in matched_normalized)
            if has_strong_title:
                score = len(matched_normalized)
                if score > best_score:
                    best_score = score
                    best_match = scenario_id
                    best_matched_tokens = matched_original

    if best_match:
        return {
            "matched": True,
            "scenario_id": best_match,
            "score": best_score,
            "matched_tokens": best_matched_tokens
        }

    return {"matched": False}



def generate_plugin_draft(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _failure_response("invalid_request")
    card = request.get("card")
    probe = request.get("probe")
    if not isinstance(card, dict) or not isinstance(probe, dict):
        return _failure_response("invalid_request")

    card_type = _text(card.get("type")).lower()
    stable_label = _text(card.get("stable_label"))
    label = _text(card.get("label"))
    if card_type not in {"life", "device"} or not stable_label or not label:
        return _failure_response("invalid_request")

    summary = probe.get("summary") if isinstance(probe.get("summary"), dict) else {}
    seed = probe.get("seed") if isinstance(probe.get("seed"), dict) else {}
    diagnostics = probe.get("diagnostics") if isinstance(probe.get("diagnostics"), dict) else {}
    warnings: list[str] = []
    notes = ["Draft only. No files were modified."]

    scenario_id = _build_scenario_id(card, warnings)
    plugin_open_verified = bool(summary.get("plugin_open_verified_candidate"))
    suggested_entry_method = _text(summary.get("suggested_entry_method")) or _text(seed.get("entry_candidate", {}).get("action"))
    if not suggested_entry_method:
        suggested_entry_method = "xml_scroll_search_tap" if card_type == "life" else "enter_device_card_plugin"

    scenario: dict[str, Any] = {
        "id": scenario_id,
        "tab": "life" if card_type == "life" else "devices",
        "pre_navigation": suggested_entry_method,
        "entry_contract": "plugin_screen",
        "anchor_mode": "anchor_only",
    }
    
    failure_reason = _text(diagnostics.get("failure_reason"))
    overlay_hints = list(seed.get("overlay_hints") or [])

    metadata = {
        "source_card": card,
        "probe_status": _text(probe.get("probe_status")),
        "plugin_open_verified_candidate": plugin_open_verified,
        "headers": list(seed.get("headers") or []),
        "local_tabs": list(seed.get("local_tabs") or []),
        "representative_cards": list(seed.get("representative_cards") or []),
        "overlay_hints": overlay_hints,
        "context_verify_text_candidates": list(seed.get("context_verify_text_candidates") or []),
    }

    reused_match = find_reusable_landing_profile(seed, card_type, TAB_CONFIGS)
    if reused_match.get("matched"):
        reused_id = reused_match.get("scenario_id", "")
        reused_cfg = next((c for c in TAB_CONFIGS if isinstance(c, dict) and _text(c.get("scenario_id")) == reused_id), {})
        
        for field in ["anchor_name", "anchor", "context_verify", "verify_tokens", "special_state_tokens"]:
            if field in reused_cfg:
                scenario[field] = reused_cfg[field]
                
        metadata["reused_landing_profile_from"] = reused_id
        metadata["landing_profile_match"] = {
            "score": reused_match.get("score"),
            "matched_tokens": reused_match.get("matched_tokens"),
        }
        warnings.append(f"Reused landing profile from {reused_id}")
    else:
        if card_type == "life":
            scenario["verify_tokens"] = _build_life_verify_tokens(card, probe)
        else:
            scenario["target_stable_labels"] = _build_device_target_stable_labels(card, probe)

    manual_review_required = any(
        [
            not probe.get("ok", False),
            not plugin_open_verified,
            card_type == "life" and not scenario.get("verify_tokens"),
            "candidate_001" in scenario_id,
            bool(failure_reason),
            failure_reason == "wrong_plugin_open_suspected",
            bool(overlay_hints),
        ]
    )
    metadata["manual_review_required"] = manual_review_required

    runtime_config = {
        scenario_id: {
            "enabled": False,
            "max_steps": 5,
        }
    }

    return {
        "ok": True,
        "schema_version": DRAFT_SCHEMA_VERSION,
        "draft_status": "generated",
        "draft": {
            "scenario": scenario,
            "runtime_config": runtime_config,
            "metadata": metadata,
        },
        "diagnostics": {
            "warnings": warnings,
            "notes": notes,
            "failure_reason": "",
        },
    }


def review_plugin_draft(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _review_failure_response("invalid_request")
    draft = request.get("draft")
    options = request.get("options")
    if not isinstance(draft, dict):
        return _review_failure_response("invalid_request")
    if options is not None and not isinstance(options, dict):
        return _review_failure_response("invalid_request")

    scenario = draft.get("scenario")
    runtime_config = draft.get("runtime_config")
    metadata = draft.get("metadata")
    if not isinstance(scenario, dict) or not isinstance(runtime_config, dict) or not isinstance(metadata, dict):
        return _review_failure_response("invalid_request")

    scenario_id = _text(scenario.get("id"))
    if not scenario_id:
        return _review_failure_response("invalid_request")

    include_diff_preview = bool((options or {}).get("include_diff_preview", True))
    check_existing = bool((options or {}).get("check_existing", True))
    warnings: list[str] = []
    errors: list[str] = []

    scenario_id_exists = False
    runtime_config_exists = False
    if check_existing:
        scenario_id_exists = scenario_id in _existing_scenario_ids()
        runtime_scenarios = _load_runtime_scenarios()
        runtime_config_exists = scenario_id in runtime_scenarios

    manual_review_required = bool(metadata.get("manual_review_required"))
    candidate_id = "candidate_" in scenario_id

    if scenario_id_exists:
        warnings.append(f"Scenario id already exists: {scenario_id}")
        errors.append(f"Scenario id already exists: {scenario_id}")
    if runtime_config_exists:
        warnings.append(f"Runtime config key already exists: {scenario_id}")
    if manual_review_required:
        warnings.append("Draft metadata requires manual review before apply")
    if candidate_id:
        warnings.append("Candidate id requires manual rename before apply")

    can_apply = not scenario_id_exists and not manual_review_required and not candidate_id
    review_status = "ready" if can_apply and not warnings else "warning"
    if not can_apply:
        review_status = "blocked"

    diff_preview = ""
    if include_diff_preview:
        diff_preview = "\n\n".join(
            [
                _format_preview_block("scenario_config.py", scenario),
                _format_preview_block("runtime_config.json", runtime_config),
            ]
        )

    return {
        "ok": True,
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_status": review_status,
        "checks": {
            "scenario_id_exists": scenario_id_exists,
            "runtime_config_exists": runtime_config_exists,
            "manual_review_required": manual_review_required,
            "can_apply": can_apply,
        },
        "preview": {
            "scenario_config_insertion_hint": "append_to_scenarios",
            "runtime_config_patch": runtime_config,
            "diff_preview": diff_preview,
        },
        "diagnostics": {
            "warnings": warnings,
            "errors": errors,
        },
    }


def apply_plugin_draft(
    request: dict[str, Any],
    *,
    scenario_config_path: Path | None = None,
    runtime_config_path: Path | None = None,
    backup_root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _apply_failure_response("invalid_request")
    draft = request.get("draft")
    review = request.get("review")
    options = request.get("options")
    if not isinstance(draft, dict) or not isinstance(review, dict):
        return _apply_failure_response("invalid_request")
    if options is not None and not isinstance(options, dict):
        return _apply_failure_response("invalid_request")

    scenario = draft.get("scenario")
    runtime_config = draft.get("runtime_config")
    metadata = draft.get("metadata")
    checks = review.get("checks") if isinstance(review.get("checks"), dict) else {}
    if not isinstance(scenario, dict) or not isinstance(runtime_config, dict) or not isinstance(metadata, dict):
        return _apply_failure_response("invalid_request")

    scenario_id = _text(scenario.get("id"))
    if not scenario_id:
        return _apply_failure_response("invalid_request")
    runtime_entry = runtime_config.get(scenario_id)
    if not isinstance(runtime_entry, dict):
        return _apply_failure_response("invalid_request", errors=["Draft runtime_config entry missing"])

    warnings: list[str] = []
    errors: list[str] = []
    if not bool(checks.get("can_apply")):
        return _apply_failure_response("blocked", errors=["Review did not allow apply"])
    if bool(metadata.get("manual_review_required")):
        return _apply_failure_response("blocked", errors=["Draft metadata requires manual review"])
    if "candidate_" in scenario_id:
        return _apply_failure_response("blocked", errors=["Candidate id requires manual rename before apply"])

    scenario_config_path = Path(scenario_config_path or DEFAULT_SCENARIO_CONFIG_PATH)
    runtime_config_path = Path(runtime_config_path or DEFAULT_RUNTIME_CONFIG_PATH)
    backup_root = Path(backup_root or DEFAULT_BACKUP_ROOT)

    if not scenario_config_path.is_file() or not runtime_config_path.is_file():
        return _apply_failure_response("blocked", errors=["Target config files not found"])

    scenario_text = scenario_config_path.read_text(encoding="utf-8")
    runtime_text = runtime_config_path.read_text(encoding="utf-8")
    current_scenario_ids = _extract_scenario_ids_from_text(scenario_text)
    if scenario_id in current_scenario_ids:
        return _apply_failure_response("blocked", errors=[f"Scenario id already exists at apply time: {scenario_id}"])

    current_runtime_scenarios = _load_runtime_scenarios(runtime_config_path)
    if scenario_id in current_runtime_scenarios:
        return _apply_failure_response("blocked", errors=[f"Runtime config key already exists at apply time: {scenario_id}"])

    scenario_entry = _scenario_entry_from_draft(draft)
    if not _text(scenario_entry.get("scenario_id")) or not isinstance(scenario_entry.get("pre_navigation"), list):
        return _apply_failure_response("blocked", errors=["Draft scenario could not be converted to scenario_config entry"])

    backup_paths: list[Path] = []
    if bool((options or {}).get("create_backup", True)):
        backup_paths = _create_backups([scenario_config_path, runtime_config_path], backup_root)

    _append_scenario_config_entry(scenario_config_path, scenario_entry)
    _merge_runtime_config(runtime_config_path, scenario_id, runtime_entry)

    import ast
    try:
        ast.parse(scenario_config_path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        scenario_config_path.write_text(scenario_text, encoding="utf-8")
        runtime_config_path.write_text(runtime_text, encoding="utf-8")
        return _apply_failure_response(
            "syntax_error",
            errors=[f"Generated scenario_config.py has SyntaxError: {e}"]
        )

    return {
        "ok": True,
        "schema_version": APPLY_SCHEMA_VERSION,
        "apply_status": "applied",
        "changed_files": [
            str(scenario_config_path).replace("\\", "/"),
            str(runtime_config_path).replace("\\", "/"),
        ],
        "backup": {
            "created": bool(backup_paths),
            "paths": [str(path).replace("\\", "/") for path in backup_paths],
        },
        "applied": {
            "scenario_id": scenario_id,
            "runtime_config_key": scenario_id,
        },
        "diagnostics": {
            "warnings": warnings,
            "errors": errors,
        },
    }


def normalize_plugin_smoke_request(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _smoke_failure_response("invalid_request")
    scenario_id = _text(request.get("scenario_id"))
    if not scenario_id:
        return _smoke_failure_response("scenario_id_missing")
    mode = _text(request.get("mode") or "smoke").lower()
    if mode != "smoke":
        return _smoke_failure_response("mode_must_be_smoke", scenario_id=scenario_id)
    try:
        max_steps = int(request.get("max_steps", 5) or 5)
    except (TypeError, ValueError):
        return _smoke_failure_response("invalid_max_steps", scenario_id=scenario_id)
    if max_steps < 1:
        return _smoke_failure_response("invalid_max_steps", scenario_id=scenario_id)
    if max_steps > 10:
        return _smoke_failure_response("max_steps_too_high", scenario_id=scenario_id)
    return {
        "ok": True,
        "schema_version": SMOKE_SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "max_steps": max_steps,
        "mode": "smoke",
        "serial": request.get("serial"),
        "options": request.get("options") if isinstance(request.get("options"), dict) else {},
    }


def build_plugin_smoke_command(scenario_id: str, max_steps: int) -> dict[str, Any]:
    normalized = normalize_plugin_smoke_request(
        {
            "scenario_id": scenario_id,
            "max_steps": max_steps,
            "mode": "smoke",
        }
    )
    if not normalized.get("ok"):
        return normalized
    scenario_id = str(normalized["scenario_id"])
    max_steps = int(normalized["max_steps"])
    return {
        "ok": True,
        "mode": "smoke",
        "scenario_ids": [scenario_id],
        "launch_mode": "clean",
        "language_mode": "current",
        "max_steps_overrides": {
            scenario_id: max_steps,
        },
        "argv": [
            "python",
            "script_test.py",
            "--mode",
            "smoke",
            "--scenario",
            scenario_id,
        ],
    }


def parse_plugin_smoke_summary(log_text: str, scenario_id: str) -> dict[str, Any]:
    text = str(log_text or "")
    scenario_id = _text(scenario_id)
    scenario_fragment = re.escape(scenario_id)
    has_traceback = bool(re.search(r"(?i)(traceback|fatal)", text))
    pre_navigation_success = bool(re.search(r"\[SCENARIO\]\[pre_nav\]\s+success", text))
    entry_success = bool(
        re.search(rf"\[SCENARIO\]\[entry_contract\]\s+success\s+scenario=['\"]?{scenario_fragment}", text)
        or re.search(r"success_verified|plugin_open_verified", text, re.IGNORECASE)
    )
    steps_collected = len(re.findall(rf"\[STEP\]\s+END\s+scenario=['\"]?{scenario_fragment}", text))
    if steps_collected == 0:
        summary_match = re.search(rf"\[PERF\]\[scenario_summary\]\s+scenario={scenario_fragment}\s+total_steps=(\d+)", text)
        if summary_match:
            steps_collected = int(summary_match.group(1))

    failure_reason = ""
    failure_match = re.search(r"failure_reason=['\"]([^'\"]+)['\"]", text)
    if failure_match:
        failure_reason = failure_match.group(1)
    elif has_traceback:
        failure_reason = "traceback_or_fatal"
    elif re.search(r"\[SCENARIO\]\[entry_contract\]\s+failed", text):
        failure_reason = "entry_contract_failed"
    elif re.search(r"\[SCENARIO\]\[pre_nav\].*failed", text):
        failure_reason = "pre_navigation_failed"

    non_fatal_reasons = {"repeat_no_progress", "safety_limit", "smart_nav_terminal", "local_tab_continue"}
    result_status = "UNKNOWN"
    if has_traceback:
        result_status = "FAIL"
    elif pre_navigation_success and entry_success and not failure_reason and steps_collected >= 1:
        result_status = "PASS"
    elif pre_navigation_success and steps_collected >= 1 and (entry_success or not failure_reason):
        result_status = "WARN"
    elif failure_reason in non_fatal_reasons and steps_collected >= 1:
        result_status = "WARN"
    elif failure_reason:
        result_status = "FAIL"
    elif steps_collected == 0 and text.strip():
        result_status = "FAIL"

    return {
        "pre_navigation_success": pre_navigation_success,
        "plugin_open_verified": entry_success,
        "steps_collected": steps_collected,
        "failure_reason": failure_reason,
        "result_status": result_status,
    }


REMOVE_SCHEMA_VERSION = "plugin-remove-applied-draft-v1"

def _remove_scenario_config_entry(file_path: Path, scenario_id: str) -> None:
    text = file_path.read_text(encoding="utf-8")
    import ast
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TAB_CONFIGS":
                    if isinstance(node.value, ast.List):
                        for item in node.value.elts:
                            if isinstance(item, ast.Dict):
                                for k, v in zip(item.keys, item.values):
                                    if isinstance(k, ast.Constant) and k.value == "scenario_id":
                                        if isinstance(v, ast.Constant) and v.value == scenario_id:
                                            start_line = item.lineno - 1
                                            end_line = item.end_lineno
                                            lines = text.splitlines(keepends=True)
                                            del lines[start_line:end_line]
                                            file_path.write_text("".join(lines), encoding="utf-8")
                                            return

def _unmerge_runtime_config(file_path: Path, runtime_key: str) -> None:
    if not file_path.is_file():
        return
    import json
    with file_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    scenarios = payload.get("scenarios")
    if isinstance(scenarios, dict) and runtime_key in scenarios:
        del scenarios[runtime_key]
        with file_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

def remove_applied_plugin_draft(
    request: dict[str, Any],
    *,
    scenario_config_path: Path | None = None,
    runtime_config_path: Path | None = None,
    backup_root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {"ok": False, "schema_version": REMOVE_SCHEMA_VERSION, "remove_status": "blocked", "diagnostics": {"errors": ["invalid_request"]}}
    confirm = request.get("confirm")
    if confirm is not True:
        return {"ok": False, "schema_version": REMOVE_SCHEMA_VERSION, "remove_status": "blocked", "diagnostics": {"errors": ["confirm=true required"]}}
    
    scenario_id = _text(request.get("scenario_id"))
    runtime_config_key = _text(request.get("runtime_config_key"))
    session_id = _text(request.get("session_id"))
    
    if not scenario_id or not runtime_config_key:
        return {"ok": False, "schema_version": REMOVE_SCHEMA_VERSION, "remove_status": "blocked", "diagnostics": {"errors": ["scenario_id and runtime_config_key required"]}}

    scenario_config_path = Path(scenario_config_path or DEFAULT_SCENARIO_CONFIG_PATH)
    runtime_config_path = Path(runtime_config_path or DEFAULT_RUNTIME_CONFIG_PATH)
    backup_root = Path(backup_root or DEFAULT_BACKUP_ROOT)

    if not scenario_config_path.is_file() or not runtime_config_path.is_file():
        return {"ok": False, "schema_version": REMOVE_SCHEMA_VERSION, "remove_status": "blocked", "diagnostics": {"errors": ["Target config files not found"]}}

    scenario_text = scenario_config_path.read_text(encoding="utf-8")
    runtime_text = runtime_config_path.read_text(encoding="utf-8")
    
    backup_paths: list[Path] = []
    if bool(request.get("create_backup", True)):
        backup_paths = _create_backups([scenario_config_path, runtime_config_path], backup_root)

    _remove_scenario_config_entry(scenario_config_path, scenario_id)
    _unmerge_runtime_config(runtime_config_path, runtime_config_key)

    import ast
    import json
    errors = []
    try:
        ast.parse(scenario_config_path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        errors.append(f"SyntaxError after removal: {e}")
    try:
        with runtime_config_path.open("r", encoding="utf-8") as handle:
            json.load(handle)
    except Exception as e:
        errors.append(f"JSON error after removal: {e}")

    if errors:
        scenario_config_path.write_text(scenario_text, encoding="utf-8")
        runtime_config_path.write_text(runtime_text, encoding="utf-8")
        return {
            "ok": False,
            "schema_version": REMOVE_SCHEMA_VERSION,
            "remove_status": "blocked",
            "diagnostics": {"errors": errors}
        }

    return {
        "ok": True,
        "schema_version": REMOVE_SCHEMA_VERSION,
        "remove_status": "removed",
        "session_id": session_id,
        "removed": {
            "scenario_id": scenario_id,
            "runtime_config_key": runtime_config_key
        },
        "changed_files": [
            str(scenario_config_path).replace("\\", "/"),
            str(runtime_config_path).replace("\\", "/")
        ],
        "backup": {
            "created": bool(backup_paths),
            "paths": [str(path).replace("\\", "/") for path in backup_paths]
        },
        "diagnostics": {"warnings": [], "errors": []}
    }
