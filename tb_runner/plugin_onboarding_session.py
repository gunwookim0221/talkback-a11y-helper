from __future__ import annotations

import json
import re
import shutil
from difflib import unified_diff
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SESSION_SCHEMA_VERSION = "plugin-onboarding-session-v1"
RESTORE_SCHEMA_VERSION = "plugin-onboarding-restore-v1"
ROLLBACK_PREVIEW_SCHEMA_VERSION = "plugin-rollback-preview-v1"
ROLLBACK_EXECUTE_SCHEMA_VERSION = "plugin-rollback-execute-v1"
DEFAULT_SESSION_ROOT = Path("output/plugin_onboarding_sessions")
DEFAULT_PROJECT_ROOT = Path(".")
VALID_STEPS = {"discovery", "probe", "draft", "review", "apply", "smoke", "rollback"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    text = re.sub(r"_+", "_", text)
    return text or "plugin"


def _safe_session_id(session_id: str) -> str:
    session_id = _text(session_id)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", session_id):
        raise ValueError("invalid_session_id")
    return session_id


def _session_path(session_id: str, session_root: Path) -> Path:
    return session_root / f"{_safe_session_id(session_id)}.json"


def _project_path(path: Any, project_root: Path) -> Path:
    candidate = Path(_text(path))
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate


def _write_session(session: dict[str, Any], session_root: Path) -> None:
    session_root.mkdir(parents=True, exist_ok=True)
    path = _session_path(str(session.get("session_id") or ""), session_root)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(session, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _read_session(session_id: str, session_root: Path) -> dict[str, Any]:
    path = _session_path(session_id, session_root)
    if not path.is_file():
        raise FileNotFoundError("session_not_found")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("invalid_session_file")
    return payload


def _step_payload(session: dict[str, Any], step: str) -> dict[str, Any]:
    steps = session.get("steps") if isinstance(session.get("steps"), dict) else {}
    item = steps.get(step) if isinstance(steps.get(step), dict) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return payload


def _step_status(session: dict[str, Any], step: str) -> str:
    steps = session.get("steps") if isinstance(session.get("steps"), dict) else {}
    item = steps.get(step) if isinstance(steps.get(step), dict) else {}
    return _text(item.get("status"))


def _extract_scenario_id(payload: dict[str, Any]) -> str:
    candidates: list[Any] = []
    if isinstance(payload.get("scenario_id"), str):
        candidates.append(payload.get("scenario_id"))
    applied = payload.get("applied")
    if isinstance(applied, dict):
        candidates.append(applied.get("scenario_id"))
    draft = payload.get("draft")
    if isinstance(draft, dict):
        scenario = draft.get("scenario")
        if isinstance(scenario, dict):
            candidates.append(scenario.get("id"))
    scenario = payload.get("scenario")
    if isinstance(scenario, dict):
        candidates.append(scenario.get("id"))
    for candidate in candidates:
        text = _text(candidate)
        if text:
            return text
    return ""


def _extract_runtime_key(payload: dict[str, Any]) -> str:
    applied = payload.get("applied")
    if isinstance(applied, dict):
        runtime_key = _text(applied.get("runtime_config_key"))
        if runtime_key:
            return runtime_key
    return _extract_scenario_id(payload)


def calculate_session_status(step: str, status: str, payload: dict[str, Any]) -> str:
    step = _text(step).lower()
    status = _text(status).lower()
    result_status = _text((payload.get("summary") or {}).get("result_status") if isinstance(payload.get("summary"), dict) else "").upper()

    if step == "discovery" and status == "completed":
        return "discovered"
    if step == "probe" and status == "completed":
        return "probed"
    if step == "draft" and status == "completed":
        return "draft_generated"
    if step == "review":
        if status == "ready":
            return "review_ready"
        if status == "blocked":
            return "review_blocked"
    if step == "apply" and status == "applied":
        return "applied"
    if step == "rollback" and status == "rolled_back":
        return "rolled_back"
    if step == "smoke":
        if status in {"started", "running"}:
            return "smoke_started"
        if result_status == "PASS" or status == "passed":
            return "smoke_passed"
        if result_status == "WARN" or status == "warn":
            return "smoke_warn"
        if result_status == "FAIL" or status == "failed":
            return "smoke_failed"
    return status or "created"


def _feedback_from_smoke(payload: dict[str, Any]) -> dict[str, list[str]]:
    feedback = {"warnings": [], "errors": [], "suggestions": []}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    result_status = _text(summary.get("result_status")).upper()
    failure_reason = _text(summary.get("failure_reason"))
    warnings = [_text(item) for item in diagnostics.get("warnings", []) if _text(item)] if isinstance(diagnostics.get("warnings"), list) else []
    errors = [_text(item) for item in diagnostics.get("errors", []) if _text(item)] if isinstance(diagnostics.get("errors"), list) else []

    if result_status == "PASS":
        feedback["suggestions"].append("Ready for manual validation")
    elif result_status == "WARN":
        feedback["warnings"].extend(warnings or [failure_reason or "Smoke completed with warnings"])
    elif result_status == "FAIL":
        feedback["errors"].extend(errors or [failure_reason or "Smoke failed"])
    feedback["warnings"].extend(warning for warning in warnings if warning not in feedback["warnings"])
    feedback["errors"].extend(error for error in errors if error not in feedback["errors"])
    return feedback


def _merge_feedback(session: dict[str, Any], payload: dict[str, Any], step: str) -> None:
    feedback = session.setdefault("feedback", {"warnings": [], "errors": [], "suggestions": []})
    for key in ("warnings", "errors", "suggestions"):
        if not isinstance(feedback.get(key), list):
            feedback[key] = []
    if step != "smoke":
        return
    smoke_feedback = _feedback_from_smoke(payload)
    for key, values in smoke_feedback.items():
        for value in values:
            if value and value not in feedback[key]:
                feedback[key].append(value)


def create_onboarding_session(card: dict[str, Any], session_root: Path | None = None) -> dict[str, Any]:
    if not isinstance(card, dict):
        raise ValueError("invalid_card")
    label = _text(card.get("label"))
    stable_label = _text(card.get("stable_label")) or label
    plugin_type = _text(card.get("type")).lower()
    if not stable_label or plugin_type not in {"life", "device"}:
        raise ValueError("invalid_card")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    session_id = f"onboarding_{timestamp}_{_slug(stable_label)}"
    now = _now_iso()
    session = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "plugin": {
            "label": label,
            "stable_label": stable_label,
            "type": plugin_type,
            "scenario_id": _text(card.get("existing_scenario_id")),
        },
        "status": "created",
        "steps": {},
        "feedback": {
            "warnings": [],
            "errors": [],
            "suggestions": [],
        },
        "created_at": now,
        "updated_at": now,
    }
    _write_session(session, Path(session_root or DEFAULT_SESSION_ROOT))
    return {
        "ok": True,
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": session_id,
    }


def save_onboarding_step(
    session_id: str,
    step: str,
    status: str,
    payload: dict[str, Any] | None = None,
    session_root: Path | None = None,
) -> dict[str, Any]:
    step = _text(step).lower()
    if step not in VALID_STEPS:
        raise ValueError("invalid_step")
    payload = payload if isinstance(payload, dict) else {}
    root = Path(session_root or DEFAULT_SESSION_ROOT)
    session = _read_session(session_id, root)
    now = _now_iso()
    session.setdefault("steps", {})[step] = {
        "status": _text(status),
        "payload": payload,
        "updated_at": now,
    }
    scenario_id = _extract_scenario_id(payload)
    if scenario_id:
        session.setdefault("plugin", {})["scenario_id"] = scenario_id
    session["status"] = calculate_session_status(step, _text(status), payload)
    session["updated_at"] = now
    _merge_feedback(session, payload, step)
    _write_session(session, root)
    return {
        "ok": True,
        "schema_version": SESSION_SCHEMA_VERSION,
        "session": session,
    }


def get_onboarding_session(session_id: str, session_root: Path | None = None) -> dict[str, Any]:
    session = _read_session(session_id, Path(session_root or DEFAULT_SESSION_ROOT))
    return {
        "ok": True,
        "schema_version": SESSION_SCHEMA_VERSION,
        "session": session,
    }


def list_onboarding_sessions(session_root: Path | None = None, limit: int = 20) -> dict[str, Any]:
    root = Path(session_root or DEFAULT_SESSION_ROOT)
    sessions: list[dict[str, Any]] = []
    if root.is_dir():
        for path in root.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict):
                    sessions.append(payload)
            except Exception:
                continue
    sessions.sort(key=lambda item: _text(item.get("updated_at")), reverse=True)
    return {
        "ok": True,
        "schema_version": SESSION_SCHEMA_VERSION,
        "sessions": sessions[: max(1, int(limit or 20))],
    }


def build_restored_state(session: dict[str, Any]) -> dict[str, Any]:
    discovery = _step_payload(session, "discovery")
    smoke = _step_payload(session, "smoke")
    smoke_status = _text(smoke.get("smoke_status")).lower()
    smoke_result_status = _text((smoke.get("summary") or {}).get("result_status") if isinstance(smoke.get("summary"), dict) else "").upper()

    selected_card: dict[str, Any] = {}
    if isinstance(discovery.get("card"), dict):
        selected_card = discovery["card"]
    elif isinstance(discovery.get("cards"), list) and discovery["cards"]:
        first_card = discovery["cards"][0]
        selected_card = first_card if isinstance(first_card, dict) else {}

    smoke_start_result: dict[str, Any] = {}
    smoke_status_result: dict[str, Any] = {}
    if smoke_status in {"started", "running"} and not smoke_result_status:
        smoke_start_result = smoke
    elif smoke:
        smoke_status_result = smoke
        if smoke_status in {"started", "running"}:
            smoke_start_result = smoke

    return {
        "selected_card": selected_card,
        "probe_result": _step_payload(session, "probe"),
        "draft_result": _step_payload(session, "draft"),
        "review_result": _step_payload(session, "review"),
        "apply_result": _step_payload(session, "apply"),
        "rollback_result": _step_payload(session, "rollback"),
        "smoke_start_result": smoke_start_result,
        "smoke_status_result": smoke_status_result,
    }


def recommend_next_action(session: dict[str, Any], restored_state: dict[str, Any] | None = None) -> dict[str, Any]:
    restored_state = restored_state or build_restored_state(session)
    status = _text(session.get("status")).lower()
    review_payload = restored_state.get("review_result") if isinstance(restored_state.get("review_result"), dict) else {}
    apply_payload = restored_state.get("apply_result") if isinstance(restored_state.get("apply_result"), dict) else {}
    smoke_payload = restored_state.get("smoke_status_result") or restored_state.get("smoke_start_result") or {}
    smoke_summary = smoke_payload.get("summary") if isinstance(smoke_payload.get("summary"), dict) else {}
    result_status = _text(smoke_summary.get("result_status")).upper()
    failure_reason = _text(smoke_summary.get("failure_reason"))
    backup = apply_payload.get("backup") if isinstance(apply_payload.get("backup"), dict) else {}
    backup_paths = backup.get("paths") if isinstance(backup.get("paths"), list) else []

    if status == "rolled_back":
        return {
            "next_action": "rollback_completed",
            "severity": "info",
            "reasons": ["Draft changes restored from backup"],
            "allowed_actions": ["review_restore_state", "retry_probe"],
            "blocked_actions": ["apply_draft"],
        }

    if status == "smoke_passed" or result_status == "PASS":
        return {
            "next_action": "ready_for_manual_validation",
            "severity": "success",
            "reasons": ["Smoke result PASS", "Plugin open verified"],
            "allowed_actions": ["manual_validation", "commit_changes"],
            "blocked_actions": [],
        }

    if status == "smoke_warn" or result_status == "WARN":
        return {
            "next_action": "ready_with_warning",
            "severity": "warning",
            "reasons": ["Smoke result WARN"],
            "allowed_actions": ["manual_validation", "review_logs"],
            "blocked_actions": [],
        }

    review_checks = review_payload.get("checks") if isinstance(review_payload.get("checks"), dict) else {}
    review_status = _text(review_payload.get("review_status")).lower() or _step_status(session, "review").lower()
    review_warnings = review_payload.get("diagnostics", {}).get("warnings", []) if isinstance(review_payload.get("diagnostics"), dict) else []
    review_warning_text = " ".join(_text(item).lower() for item in review_warnings if _text(item))
    if (
        status == "review_blocked"
        or review_status == "blocked"
        or bool(review_checks.get("manual_review_required"))
        or "candidate id" in review_warning_text
        or bool(review_checks.get("scenario_id_exists"))
    ):
        reasons = ["Review is blocked"]
        if review_checks.get("manual_review_required"):
            reasons.append("Manual review required")
        if review_checks.get("scenario_id_exists"):
            reasons.append("Duplicate scenario id")
        if "candidate id" in review_warning_text:
            reasons.append("Candidate id fallback")
        return {
            "next_action": "review_blocked",
            "severity": "danger",
            "reasons": reasons,
            "allowed_actions": ["edit_draft_manually", "regenerate_draft"],
            "blocked_actions": ["apply_draft"],
        }

    failed_entry_reasons = {"transition_not_confirmed", "plugin_open_failed", "wrong_plugin_open_suspected", "tap_failed"}
    if (status == "smoke_failed" or result_status == "FAIL") and backup_paths:
        return {
            "next_action": "apply_rollback_candidate",
            "severity": "danger",
            "reasons": ["Smoke failed after apply", "Backup is available"],
            "allowed_actions": ["rollback_from_backup", "review_failure"],
            "blocked_actions": ["commit_changes"],
        }

    if status == "smoke_failed" or result_status == "FAIL":
        action = "needs_probe_revision" if failure_reason in failed_entry_reasons else "review_failure"
        allowed = ["retry_probe", "regenerate_draft"] if action == "needs_probe_revision" else ["review_logs", "retry_smoke"]
        return {
            "next_action": action,
            "severity": "danger",
            "reasons": [f"Smoke result FAIL: {failure_reason or 'unknown'}"],
            "allowed_actions": allowed,
            "blocked_actions": ["commit_changes"],
        }

    return {
        "next_action": "incomplete",
        "severity": "info",
        "reasons": [f"Session status is {status or 'created'}"],
        "allowed_actions": ["continue_onboarding"],
        "blocked_actions": ["commit_changes"],
    }


def restore_onboarding_session(session_id: str, session_root: Path | None = None) -> dict[str, Any]:
    session = _read_session(session_id, Path(session_root or DEFAULT_SESSION_ROOT))
    restored_state = build_restored_state(session)
    return {
        "ok": True,
        "schema_version": RESTORE_SCHEMA_VERSION,
        "session": session,
        "restored_state": restored_state,
        "recommendation": recommend_next_action(session, restored_state),
    }


def _backup_paths_by_name(paths: list[Any], project_root: Path) -> dict[str, Path]:
    results: dict[str, Path] = {}
    for value in paths:
        path = _project_path(value, project_root)
        normalized = path.name.lower()
        if normalized == "scenario_config.py.bak":
            results["scenario_config"] = path
        elif normalized == "runtime_config.json.bak":
            results["runtime_config"] = path
    return results


def _short_diff(current_path: Path, backup_path: Path, label: str, limit: int = 120) -> str:
    current_text = current_path.read_text(encoding="utf-8", errors="replace")
    backup_text = backup_path.read_text(encoding="utf-8", errors="replace")
    diff_lines = list(
        unified_diff(
            current_text.splitlines(),
            backup_text.splitlines(),
            fromfile=f"current/{label}",
            tofile=f"backup/{label}",
            lineterm="",
        )
    )
    if len(diff_lines) > limit:
        diff_lines = diff_lines[:limit] + [f"... truncated {len(diff_lines) - limit} lines ..."]
    return "\n".join(diff_lines) if diff_lines else f"{label}: no content difference"


def preview_onboarding_rollback(
    session_id: str,
    session_root: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root or DEFAULT_PROJECT_ROOT)
    session = _read_session(session_id, Path(session_root or DEFAULT_SESSION_ROOT))
    apply_payload = _step_payload(session, "apply")
    warnings: list[str] = []
    errors: list[str] = []
    target_files = ["tb_runner/scenario_config.py", "config/runtime_config.json"]
    scenario_config_path = root / target_files[0]
    runtime_config_path = root / target_files[1]

    if not apply_payload:
        errors.append("apply payload missing")

    scenario_id = _extract_scenario_id(apply_payload) or _text((session.get("plugin") or {}).get("scenario_id") if isinstance(session.get("plugin"), dict) else "")
    runtime_key = _extract_runtime_key(apply_payload)
    if not scenario_id:
        errors.append("scenario id missing")
    if not runtime_key:
        errors.append("runtime key missing")

    backup = apply_payload.get("backup") if isinstance(apply_payload.get("backup"), dict) else {}
    backup_paths = backup.get("paths") if isinstance(backup.get("paths"), list) else []
    if not backup_paths:
        errors.append("backup missing")
    backup_by_name = _backup_paths_by_name(backup_paths, root)
    scenario_backup = backup_by_name.get("scenario_config")
    runtime_backup = backup_by_name.get("runtime_config")

    for label, path in {
        "scenario_config.py.bak": scenario_backup,
        "runtime_config.json.bak": runtime_backup,
    }.items():
        if path is None or not path.is_file():
            errors.append(f"backup file missing: {label}")
    for label, path in {
        "tb_runner/scenario_config.py": scenario_config_path,
        "config/runtime_config.json": runtime_config_path,
    }.items():
        if not path.is_file():
            errors.append(f"current file missing: {label}")

    scenario_entry_will_be_removed = False
    runtime_config_entry_will_be_removed = False
    diff_preview = ""
    if not errors and scenario_backup and runtime_backup:
        current_scenario = scenario_config_path.read_text(encoding="utf-8", errors="replace")
        backup_scenario = scenario_backup.read_text(encoding="utf-8", errors="replace")
        current_runtime = runtime_config_path.read_text(encoding="utf-8", errors="replace")
        backup_runtime = runtime_backup.read_text(encoding="utf-8", errors="replace")
        scenario_entry_will_be_removed = bool(scenario_id and scenario_id in current_scenario and scenario_id not in backup_scenario)
        runtime_config_entry_will_be_removed = bool(runtime_key and runtime_key in current_runtime and runtime_key not in backup_runtime)
        if not scenario_entry_will_be_removed:
            warnings.append(f"Scenario id removal not confirmed: {scenario_id}")
        if not runtime_config_entry_will_be_removed:
            warnings.append(f"Runtime key removal not confirmed: {runtime_key}")
        diff_preview = "\n\n".join(
            [
                "scenario_config.py:",
                f"- current has scenario_id {scenario_id}: {scenario_id in current_scenario}",
                f"+ backup will restore previous state: {scenario_id not in backup_scenario}",
                _short_diff(scenario_config_path, scenario_backup, "scenario_config.py"),
                "runtime_config.json:",
                f"- current has key {runtime_key}: {runtime_key in current_runtime}",
                f"+ backup will restore previous state: {runtime_key not in backup_runtime}",
                _short_diff(runtime_config_path, runtime_backup, "runtime_config.json"),
            ]
        )

    can_rollback = not errors and scenario_entry_will_be_removed and runtime_config_entry_will_be_removed
    return {
        "ok": True,
        "schema_version": ROLLBACK_PREVIEW_SCHEMA_VERSION,
        "rollback_status": "preview_ready" if can_rollback else "blocked",
        "can_rollback": can_rollback,
        "target_files": target_files,
        "backup": {
            "found": bool(not errors and scenario_backup and runtime_backup),
            "paths": [str(path).replace("\\", "/") for path in backup_paths],
        },
        "preview": {
            "scenario_entry_will_be_removed": scenario_entry_will_be_removed,
            "runtime_config_entry_will_be_removed": runtime_config_entry_will_be_removed,
            "diff_preview": diff_preview,
        },
        "diagnostics": {
            "warnings": warnings,
            "errors": errors,
        },
    }


def execute_onboarding_rollback(
    session_id: str,
    confirm: bool,
    session_root: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    root = Path(session_root or DEFAULT_SESSION_ROOT)
    repo_root = Path(project_root or DEFAULT_PROJECT_ROOT)
    safe_session_id = _safe_session_id(session_id)

    if confirm is not True:
        return {
            "ok": False,
            "schema_version": ROLLBACK_EXECUTE_SCHEMA_VERSION,
            "rollback_status": "blocked",
            "session_id": safe_session_id,
            "restored_files": [],
            "backup": {"paths": []},
            "pre_rollback_backup": [],
            "diagnostics": {
                "warnings": [],
                "errors": ["confirm=true required"],
            },
        }

    preview = preview_onboarding_rollback(safe_session_id, root, repo_root)
    preview_backup = preview.get("backup") if isinstance(preview.get("backup"), dict) else {}
    preview_diagnostics = preview.get("diagnostics") if isinstance(preview.get("diagnostics"), dict) else {}
    preview_warnings = [_text(item) for item in preview_diagnostics.get("warnings", []) if _text(item)] if isinstance(preview_diagnostics.get("warnings"), list) else []
    preview_errors = [_text(item) for item in preview_diagnostics.get("errors", []) if _text(item)] if isinstance(preview_diagnostics.get("errors"), list) else []

    if not preview.get("can_rollback"):
        return {
            "ok": False,
            "schema_version": ROLLBACK_EXECUTE_SCHEMA_VERSION,
            "rollback_status": "blocked",
            "session_id": safe_session_id,
            "restored_files": [],
            "backup": {"paths": preview_backup.get("paths", []) if isinstance(preview_backup.get("paths"), list) else []},
            "pre_rollback_backup": [],
            "diagnostics": {
                "warnings": preview_warnings,
                "errors": ["Rollback preview is not ready", *preview_errors],
            },
        }

    backup_by_name = _backup_paths_by_name(
        preview_backup.get("paths", []) if isinstance(preview_backup.get("paths"), list) else [],
        repo_root,
    )
    scenario_current = repo_root / "tb_runner" / "scenario_config.py"
    runtime_current = repo_root / "config" / "runtime_config.json"
    scenario_backup = backup_by_name.get("scenario_config")
    runtime_backup = backup_by_name.get("runtime_config")
    if not scenario_backup or not runtime_backup or not scenario_backup.is_file() or not runtime_backup.is_file():
        return {
            "ok": False,
            "schema_version": ROLLBACK_EXECUTE_SCHEMA_VERSION,
            "rollback_status": "blocked",
            "session_id": safe_session_id,
            "restored_files": [],
            "backup": {"paths": preview_backup.get("paths", []) if isinstance(preview_backup.get("paths"), list) else []},
            "pre_rollback_backup": [],
            "diagnostics": {
                "warnings": preview_warnings,
                "errors": ["backup missing"],
            },
        }

    pre_backup_root = repo_root / "output" / "plugin_rollback_execute_backups" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    pre_backup_root.mkdir(parents=True, exist_ok=True)
    scenario_before_path = pre_backup_root / "scenario_config.py.before_rollback"
    runtime_before_path = pre_backup_root / "runtime_config.json.before_rollback"
    shutil.copy2(scenario_current, scenario_before_path)
    shutil.copy2(runtime_current, runtime_before_path)
    shutil.copy2(scenario_backup, scenario_current)
    shutil.copy2(runtime_backup, runtime_current)

    restored_files = ["tb_runner/scenario_config.py", "config/runtime_config.json"]
    pre_rollback_backup = [
        str(scenario_before_path.relative_to(repo_root)).replace("\\", "/"),
        str(runtime_before_path.relative_to(repo_root)).replace("\\", "/"),
    ]
    backup_paths = preview_backup.get("paths", []) if isinstance(preview_backup.get("paths"), list) else []
    result = {
        "ok": True,
        "schema_version": ROLLBACK_EXECUTE_SCHEMA_VERSION,
        "rollback_status": "rolled_back",
        "session_id": safe_session_id,
        "restored_files": restored_files,
        "backup": {"paths": backup_paths},
        "pre_rollback_backup": pre_rollback_backup,
        "diagnostics": {
            "warnings": preview_warnings,
            "errors": [],
        },
    }
    save_onboarding_step(
        safe_session_id,
        "rollback",
        "rolled_back",
        {
            "schema_version": ROLLBACK_EXECUTE_SCHEMA_VERSION,
            "rollback_status": "rolled_back",
            "restored_files": restored_files,
            "backup": {"paths": backup_paths},
            "pre_rollback_backup": pre_rollback_backup,
        },
        root,
    )
    return result
