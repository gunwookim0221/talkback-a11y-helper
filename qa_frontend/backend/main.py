from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .adb import enable_helper, get_adb_status, get_helper_status, install_helper, open_accessibility_settings
from .outputs import list_outputs, safe_output_path
from .recent_runs import list_recent_runs, safe_recent_run_log_path
from .runner import RunManager
from .scenarios import list_scenarios


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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/adb/status")
def adb_status() -> dict[str, object]:
    return get_adb_status()


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
        return runner.start_run(mode=mode, scenario_ids=request.scenario_ids, launch_mode=request.launch_mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/run/stop")
def run_stop() -> dict[str, object]:
    return runner.stop_run()


@app.get("/api/run/status")
def run_status() -> dict[str, object]:
    return runner.get_status()


@app.get("/api/run/dashboard")
def run_dashboard() -> dict[str, object]:
    return runner.get_dashboard()


@app.get("/api/run/log")
def run_log() -> dict[str, object]:
    return runner.get_log_tail()


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
