from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .adb import enable_helper, enable_talkback, fix_talkback, get_adb_status, get_helper_status, install_helper, open_accessibility_settings, get_devices
from .device_locale import normalize_language_mode, open_language_settings
from .outputs import list_outputs, safe_output_path
from .recent_runs import list_recent_runs, safe_recent_run_log_path
from .runner import RunManager
from .batch_runner import global_batch_manager, get_recent_batches
from .scenarios import list_scenarios
from .mismatch_viewer import get_run_mismatch_summary
from .crash_summary import build_crash_artifact_zip, build_crash_detail, build_crash_summary, safe_crash_event_dir
from .plugin_discovery import PluginDiscoveryRequest, discover_plugins
from .plugin_draft import (
    PluginDraftApplyRequest,
    PluginDraftRequest,
    PluginDraftReviewRequest,
    PluginDraftSmokeRequest,
    PluginDraftSmokeStatusRequest,
    apply_draft,
    get_draft_smoke_status,
    generate_draft,
    review_draft,
    start_draft_smoke,
)
from .plugin_probe import PluginProbeRequest, probe_plugin
from .plugin_onboarding_session import (
    PluginOnboardingSessionCreateRequest,
    PluginOnboardingSessionStepRequest,
    create_session,
    get_session,
    list_sessions,
    preview_session_rollback,
    restore_session,
    save_session_step,
)


app = FastAPI(title="TalkBack QA Local Control Panel", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

runner = RunManager()


class StartRunRequest(BaseModel):
    mode: str = "full"
    scenario_ids: list[str] | None = None
    launch_mode: str = "clean"
    language_mode: str = "current"


class BatchDeviceReq(BaseModel):
    serial: str
    model: str


class BatchStartReq(BaseModel):
    devices: list[BatchDeviceReq]
    mode: str = "smoke"
    launch_mode: str = "clean"
    language_mode: str = "current"
    scenario_ids: list[str] | None = None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/adb/status")
def adb_status() -> dict[str, object]:
    return get_adb_status()


@app.get("/api/devices")
def api_devices() -> list[dict[str, object]]:
    return get_devices()


@app.get("/api/helper/status")
def helper_status() -> dict[str, object]:
    return get_helper_status()


@app.post("/api/helper/install")
def helper_install() -> dict[str, object]:
    return install_helper()


@app.post("/api/helper/enable")
def helper_enable() -> dict[str, object]:
    return enable_helper()


@app.post("/api/helper/open-accessibility-settings")
def helper_open_accessibility_settings() -> dict[str, object]:
    return open_accessibility_settings()


@app.post("/api/talkback/enable")
def talkback_enable() -> dict[str, object]:
    return enable_talkback()


@app.post("/api/talkback/fix")
def talkback_fix() -> dict[str, object]:
    return fix_talkback()


@app.post("/api/device/open-language-settings")
def device_open_language_settings() -> dict[str, object]:
    return open_language_settings()


@app.post("/api/plugin-discovery/discover")
def plugin_discovery_discover(request: PluginDiscoveryRequest) -> dict[str, object]:
    if runner.get_status().get("state") == "running":
        raise HTTPException(status_code=409, detail="Discovery is blocked while a run is in progress")
    try:
        return discover_plugins(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/plugin-probe/start")
def plugin_probe_start(request: PluginProbeRequest) -> dict[str, object]:
    if runner.get_status().get("state") == "running":
        raise HTTPException(status_code=409, detail="Probe is blocked while a run is in progress")
    try:
        return probe_plugin(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/plugin-draft/generate")
def plugin_draft_generate(request: PluginDraftRequest) -> dict[str, object]:
    if runner.get_status().get("state") == "running":
        raise HTTPException(status_code=409, detail="Draft generation is blocked while a run is in progress")
    try:
        return generate_draft(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/plugin-draft/review")
def plugin_draft_review(request: PluginDraftReviewRequest) -> dict[str, object]:
    if runner.get_status().get("state") == "running":
        raise HTTPException(status_code=409, detail="Draft review is blocked while a run is in progress")
    try:
        return review_draft(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/plugin-draft/apply")
def plugin_draft_apply(request: PluginDraftApplyRequest) -> dict[str, object]:
    if runner.get_status().get("state") == "running":
        raise HTTPException(status_code=409, detail="Draft apply is blocked while a run is in progress")
    try:
        return apply_draft(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/plugin-draft/smoke")
def plugin_draft_smoke(request: PluginDraftSmokeRequest) -> dict[str, object]:
    if runner.get_status().get("state") == "running":
        raise HTTPException(status_code=409, detail="Draft smoke is blocked while a run is in progress")
    try:
        return start_draft_smoke(request, runner=runner)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/plugin-draft/smoke/{run_id}")
def plugin_draft_smoke_status(run_id: str, scenario_id: str) -> dict[str, object]:
    try:
        return get_draft_smoke_status(
            PluginDraftSmokeStatusRequest(run_id=run_id, scenario_id=scenario_id),
            runner=runner,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/plugin-onboarding/session")
def plugin_onboarding_create_session(request: PluginOnboardingSessionCreateRequest) -> dict[str, object]:
    try:
        return create_session(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/plugin-onboarding/session/{session_id}/step")
def plugin_onboarding_save_step(session_id: str, request: PluginOnboardingSessionStepRequest) -> dict[str, object]:
    try:
        return save_session_step(session_id, request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/plugin-onboarding/session/{session_id}")
def plugin_onboarding_get_session(session_id: str) -> dict[str, object]:
    try:
        return get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/plugin-onboarding/session/{session_id}/restore")
def plugin_onboarding_restore_session(session_id: str) -> dict[str, object]:
    try:
        return restore_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/plugin-onboarding/session/{session_id}/rollback/preview")
def plugin_onboarding_rollback_preview(session_id: str) -> dict[str, object]:
    try:
        return preview_session_rollback(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/plugin-onboarding/sessions")
def plugin_onboarding_list_sessions(limit: int = 20) -> dict[str, object]:
    try:
        return list_sessions(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/scenarios")
def scenarios() -> dict[str, object]:
    try:
        return {"scenarios": list_scenarios()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/run/start")
def run_start(request: StartRunRequest) -> dict[str, object]:
    mode = request.mode.strip().lower()
    if mode not in {"smoke", "full"}:
        raise HTTPException(status_code=400, detail="mode must be smoke or full")
    try:
        language_mode = normalize_language_mode(request.language_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return runner.start_run(
            mode=mode,
            scenario_ids=request.scenario_ids,
            launch_mode=request.launch_mode,
            language_mode=language_mode,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/run/stop")
def run_stop() -> dict[str, object]:
    return runner.stop_run()


@app.post("/api/batch/start")
def batch_start(request: BatchStartReq) -> dict[str, object]:
    try:
        devices = [d.model_dump() if hasattr(d, "model_dump") else d.dict() for d in request.devices]
        return global_batch_manager.start_batch(
            devices=devices, 
            mode=request.mode,
            launch_mode=request.launch_mode,
            language_mode=request.language_mode,
            scenario_ids=request.scenario_ids
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/batch/status")
def get_batch_status() -> dict[str, object]:
    return global_batch_manager.get_status()


@app.get("/api/batch/recent")
def api_batch_recent() -> list[dict[str, object]]:
    return get_recent_batches()


@app.get("/api/batch/file")
def api_batch_file(path: str) -> FileResponse:
    from .paths import ROOT_DIR, RUN_LOG_DIR
    target = (ROOT_DIR / path).resolve()
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_relative_to(RUN_LOG_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(target, filename=target.name)


@app.get("/api/batch/log-tail")
def api_batch_log_tail(path: str) -> dict[str, object]:
    from .paths import ROOT_DIR, RUN_LOG_DIR
    target = (ROOT_DIR / path).resolve()
    if not target.is_relative_to(RUN_LOG_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        return {"text": "Waiting for batch log..."}
    try:
        with open(target, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 10240))
            text = f.read().decode("utf-8", errors="replace")
        return {"text": text}
    except Exception as e:
        return {"text": f"Error reading log: {e}"}


@app.get("/api/run/status")
def run_status() -> dict[str, object]:
    return runner.get_status()


@app.get("/api/run/dashboard")
def run_dashboard() -> dict[str, object]:
    return runner.get_dashboard()


@app.get("/api/run/log")
def run_log() -> dict[str, object]:
    return runner.get_log_tail()


@app.get("/api/run/snapshot")
def run_snapshot() -> dict[str, object]:
    return runner.get_snapshot()


@app.get("/api/run/log/download")
def run_log_download() -> FileResponse:
    path = runner.get_log_path()
    if not path:
        raise HTTPException(status_code=404, detail="run log not found")
    return FileResponse(path, filename=path.name)


@app.get("/api/runs/recent")
def recent_runs() -> dict[str, object]:
    return {"runs": list_recent_runs(current_status=runner.get_status())}


@app.get("/api/runs/recent/{run_id}/log")
def recent_run_log_download(run_id: str) -> FileResponse:
    try:
        path = safe_recent_run_log_path(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run log not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name)


@app.get("/api/runs/recent/{run_id}/mismatch")
def recent_run_mismatch_summary(run_id: str) -> dict[str, object]:
    result = get_run_mismatch_summary(run_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=str(result["error"]))
    return result


@app.get("/api/runs/{run_id}/devices/{device_id}/crashes")
def run_device_crashes(run_id: str, device_id: str) -> dict[str, object]:
    try:
        return build_crash_summary(run_id, device_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="device run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/devices/{device_id}/crashes/{crash_event_id}")
def run_device_crash_detail(run_id: str, device_id: str, crash_event_id: str) -> dict[str, object]:
    try:
        return build_crash_detail(run_id, device_id, crash_event_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="crash event not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/devices/{device_id}/crashes/{crash_event_id}/screenshot")
def run_device_crash_screenshot(run_id: str, device_id: str, crash_event_id: str) -> FileResponse:
    try:
        event_dir = safe_crash_event_dir(run_id, device_id, crash_event_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="crash event not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    screenshot = event_dir / "crash_screenshot.png"
    if not screenshot.is_file():
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(screenshot, media_type="image/png", filename=screenshot.name)


@app.get("/api/runs/{run_id}/devices/{device_id}/crashes/{crash_event_id}/download")
def run_device_crash_download(run_id: str, device_id: str, crash_event_id: str) -> Response:
    try:
        payload, filename = build_crash_artifact_zip(run_id, device_id, crash_event_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="crash event not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/outputs")
def outputs() -> dict[str, object]:
    return {"outputs": list_outputs()}


@app.get("/api/outputs/{filename}")
def output_download(filename: str) -> FileResponse:
    try:
        path = safe_output_path(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="output file not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name)
