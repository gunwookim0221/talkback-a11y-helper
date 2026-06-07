from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .paths import OUTPUT_DIR, RUN_LOG_DIR
from .recent_runs import safe_recent_run_log_path
from .run_summary import extract_saved_excel_filename, read_summary_file, summary_path_for_log
from tb_runner.plugin_draft import (
    apply_plugin_draft,
    build_plugin_smoke_command,
    generate_plugin_draft,
    normalize_plugin_smoke_request,
    parse_plugin_smoke_summary,
    review_plugin_draft,
    scenario_id_exists_for_smoke,
)


class PluginDraftCardRequest(BaseModel):
    id: str = ""
    label: str = ""
    stable_label: str = ""
    type: str = ""
    source: str = ""
    bounds: str = ""
    resource_id: str = ""
    existing_scenario_id: str = ""


class PluginDraftProbeEntryCandidateRequest(BaseModel):
    action: str = ""
    target_seed: str = ""


class PluginDraftProbeSeedRequest(BaseModel):
    verify_tokens: list[str] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    local_tabs: list[str] = Field(default_factory=list)
    representative_cards: list[str] = Field(default_factory=list)
    overlay_hints: list[str] = Field(default_factory=list)
    context_verify_text_candidates: list[str] = Field(default_factory=list)
    entry_candidate: PluginDraftProbeEntryCandidateRequest = Field(default_factory=PluginDraftProbeEntryCandidateRequest)


class PluginDraftProbeSummaryRequest(BaseModel):
    plugin_open_verified_candidate: bool = False
    suggested_entry_method: str = ""
    suggested_scenario_type: str = "content"


class PluginDraftProbeDiagnosticsRequest(BaseModel):
    warnings: list[str] = Field(default_factory=list)
    failure_reason: str = ""


class PluginDraftProbeRequest(BaseModel):
    ok: bool = False
    schema_version: str = ""
    probe_status: str = ""
    summary: PluginDraftProbeSummaryRequest = Field(default_factory=PluginDraftProbeSummaryRequest)
    seed: PluginDraftProbeSeedRequest = Field(default_factory=PluginDraftProbeSeedRequest)
    diagnostics: PluginDraftProbeDiagnosticsRequest = Field(default_factory=PluginDraftProbeDiagnosticsRequest)


class PluginDraftOptionsRequest(BaseModel):
    include_disabled_runtime_config: bool = True


class PluginDraftRequest(BaseModel):
    card: PluginDraftCardRequest
    probe: PluginDraftProbeRequest
    options: PluginDraftOptionsRequest = Field(default_factory=PluginDraftOptionsRequest)


def generate_draft(request: PluginDraftRequest) -> dict[str, Any]:
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    return generate_plugin_draft(payload)


class PluginDraftScenarioRequest(BaseModel):
    id: str = ""
    tab: str = ""
    verify_tokens: list[str] = Field(default_factory=list)
    target_stable_labels: list[str] = Field(default_factory=list)
    pre_navigation: str = ""
    entry_contract: str = ""
    anchor_mode: str = ""


class PluginDraftMetadataRequest(BaseModel):
    manual_review_required: bool = False
    source_card: dict[str, Any] = Field(default_factory=dict)
    probe_status: str = ""
    plugin_open_verified_candidate: bool = False
    headers: list[str] = Field(default_factory=list)
    local_tabs: list[str] = Field(default_factory=list)
    representative_cards: list[str] = Field(default_factory=list)
    overlay_hints: list[str] = Field(default_factory=list)
    context_verify_text_candidates: list[str] = Field(default_factory=list)


class PluginDraftBodyRequest(BaseModel):
    scenario: PluginDraftScenarioRequest
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    metadata: PluginDraftMetadataRequest = Field(default_factory=PluginDraftMetadataRequest)


class PluginDraftReviewOptionsRequest(BaseModel):
    include_diff_preview: bool = True
    check_existing: bool = True


class PluginDraftReviewRequest(BaseModel):
    draft: PluginDraftBodyRequest
    options: PluginDraftReviewOptionsRequest = Field(default_factory=PluginDraftReviewOptionsRequest)


def review_draft(request: PluginDraftReviewRequest) -> dict[str, Any]:
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    return review_plugin_draft(payload)


class PluginDraftApplyReviewChecksRequest(BaseModel):
    can_apply: bool = False
    scenario_id_exists: bool = False
    runtime_config_exists: bool = False
    manual_review_required: bool = False


class PluginDraftApplyReviewRequest(BaseModel):
    schema_version: str = ""
    checks: PluginDraftApplyReviewChecksRequest = Field(default_factory=PluginDraftApplyReviewChecksRequest)


class PluginDraftApplyOptionsRequest(BaseModel):
    create_backup: bool = True


class PluginDraftApplyRequest(BaseModel):
    draft: PluginDraftBodyRequest
    review: PluginDraftApplyReviewRequest
    options: PluginDraftApplyOptionsRequest = Field(default_factory=PluginDraftApplyOptionsRequest)


def apply_draft(request: PluginDraftApplyRequest) -> dict[str, Any]:
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    return apply_plugin_draft(payload)


class PluginDraftSmokeOptionsRequest(BaseModel):
    force_enabled_runtime_override: bool = True
    collect_summary: bool = True


class PluginDraftSmokeRequest(BaseModel):
    scenario_id: str = ""
    max_steps: int = 5
    mode: str = "smoke"
    serial: str | None = None
    options: PluginDraftSmokeOptionsRequest = Field(default_factory=PluginDraftSmokeOptionsRequest)


def start_draft_smoke(request: PluginDraftSmokeRequest, *, runner: Any) -> dict[str, Any]:
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    normalized = normalize_plugin_smoke_request(payload)
    if not normalized.get("ok"):
        return normalized
    scenario_id = str(normalized["scenario_id"])
    max_steps = int(normalized["max_steps"])
    if not scenario_id_exists_for_smoke(scenario_id):
        return {
            **normalized,
            "ok": False,
            "smoke_status": "blocked",
            "run_id": "",
            "summary": parse_plugin_smoke_summary("", scenario_id),
            "artifacts": {"log_path": "", "xlsx_path": ""},
            "diagnostics": {"warnings": [f"Scenario id not found: {scenario_id}"]},
        }
    command = build_plugin_smoke_command(scenario_id, max_steps)
    if not command.get("ok"):
        return command
    state = runner.start_run(
        mode="smoke",
        scenario_ids=[scenario_id],
        launch_mode="clean",
        language_mode="current",
        max_steps_overrides={scenario_id: max_steps},
    )
    return {
        "ok": True,
        "schema_version": "plugin-draft-smoke-v1",
        "smoke_status": "started" if state.get("state") == "running" else str(state.get("state") or "started"),
        "run_id": str(state.get("run_id") or ""),
        "scenario_id": scenario_id,
        "max_steps": max_steps,
        "command": command,
        "summary": parse_plugin_smoke_summary("", scenario_id),
        "artifacts": {
            "log_path": str(state.get("log_path") or ""),
            "xlsx_path": "",
        },
        "diagnostics": {
            "warnings": [],
        },
    }


class PluginDraftSmokeStatusRequest(BaseModel):
    run_id: str = ""
    scenario_id: str = ""


def _smoke_status_failure(reason: str, *, run_id: str = "", scenario_id: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": "plugin-draft-smoke-status-v1",
        "run_id": run_id,
        "scenario_id": scenario_id,
        "smoke_status": "unknown",
        "run_status": "unknown",
        "summary": parse_plugin_smoke_summary("", scenario_id),
        "artifacts": {
            "log_path": "",
            "xlsx_path": "",
            "summary_json_path": "",
            "display_urls": {
                "log": "",
                "xlsx": "",
            },
        },
        "diagnostics": {
            "warnings": [],
            "errors": [reason],
        },
    }


def _resolve_smoke_status(run_status: str, summary: dict[str, Any]) -> str:
    if run_status == "running":
        return "running"
    if run_status in {"finished", "success"}:
        return "completed"
    if run_status in {"error", "failed", "stopped"}:
        return "failed"
    result_status = str(summary.get("result_status") or "")
    if result_status in {"PASS", "WARN"}:
        return "completed"
    if result_status == "FAIL":
        return "failed"
    return "unknown"


def get_draft_smoke_status(
    request: PluginDraftSmokeStatusRequest,
    *,
    runner: Any,
    run_log_dir: Any = RUN_LOG_DIR,
) -> dict[str, Any]:
    run_id = str(request.run_id or "").strip()
    scenario_id = str(request.scenario_id or "").strip()
    if not run_id:
        return _smoke_status_failure("run_id_missing", scenario_id=scenario_id)
    if not scenario_id:
        return _smoke_status_failure("scenario_id_missing", run_id=run_id)

    current_status = runner.get_status() if runner is not None else {}
    run_status = "unknown"
    log_path = None
    warnings: list[str] = []
    errors: list[str] = []
    if current_status.get("run_id") == run_id:
        run_status = str(current_status.get("state") or "unknown")
        current_log_path = str(current_status.get("log_path") or "")
        if current_log_path:
            from pathlib import Path

            candidate = Path(current_log_path)
            if candidate.is_file():
                log_path = candidate

    if log_path is None:
        try:
            log_path = safe_recent_run_log_path(run_id, run_log_dir=run_log_dir)
        except (FileNotFoundError, ValueError):
            warnings.append(f"Log artifact not found for run_id: {run_id}")

    log_text = ""
    if log_path and log_path.is_file():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        if run_status == "unknown":
            lowered = log_text.lower()
            if "[qa_frontend][run] final_state='finished'" in lowered or "[main] script end" in lowered:
                run_status = "finished"
            elif "script_test.py exited with code" in lowered or "traceback" in lowered or "fatal" in lowered:
                run_status = "error"
    summary = parse_plugin_smoke_summary(log_text, scenario_id)
    smoke_status = _resolve_smoke_status(run_status, summary)

    summary_json_path = ""
    xlsx_path = ""
    xlsx_url = ""
    if log_path and log_path.is_file():
        summary_path = summary_path_for_log(log_path)
        if summary_path.is_file():
            summary_json_path = str(summary_path)
            summary_payload = read_summary_file(summary_path) or {}
            xlsx_path = str(summary_payload.get("xlsx_path") or "")
        xlsx_filename = extract_saved_excel_filename(log_text)
        if xlsx_filename:
            xlsx_candidate = OUTPUT_DIR / xlsx_filename
            if xlsx_candidate.is_file():
                xlsx_path = str(xlsx_candidate)
                xlsx_url = f"/api/outputs/{xlsx_filename}"
            else:
                warnings.append(f"XLSX artifact not found: {xlsx_filename}")
        elif smoke_status in {"completed", "failed"}:
            warnings.append("XLSX artifact not found")
    else:
        errors.append("log_not_found")

    return {
        "ok": True,
        "schema_version": "plugin-draft-smoke-status-v1",
        "run_id": run_id,
        "scenario_id": scenario_id,
        "smoke_status": smoke_status,
        "run_status": run_status,
        "summary": summary,
        "artifacts": {
            "log_path": str(log_path) if log_path else "",
            "xlsx_path": xlsx_path,
            "summary_json_path": summary_json_path,
            "display_urls": {
                "log": f"/api/runs/recent/{run_id}/log" if log_path else "",
                "xlsx": xlsx_url,
            },
        },
        "diagnostics": {
            "warnings": warnings,
            "errors": errors,
        },
    }
