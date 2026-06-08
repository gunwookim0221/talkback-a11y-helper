from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "qa_frontend" / "frontend"
BACKEND_REQUIREMENTS = ROOT_DIR / "requirements-qa_frontend.txt"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from qa_frontend.backend import outputs, runner, scenarios
from qa_frontend.backend.main import app
from qa_frontend.backend.run_summary import build_run_summary
from qa_frontend.backend.runtime_dashboard import parse_runtime_log


def _record(results: list[tuple[str, bool, str]], name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))


def check_fastapi_import(results: list[tuple[str, bool, str]]) -> None:
    route_paths = {route.path for route in app.routes}
    required = {
        "/api/health",
        "/api/adb/status",
        "/api/helper/status",
        "/api/helper/install",
        "/api/helper/enable",
        "/api/helper/open-accessibility-settings",
        "/api/talkback/enable",
        "/api/device/open-language-settings",
        "/api/plugin-discovery/discover",
        "/api/plugin-probe/start",
        "/api/plugin-draft/generate",
        "/api/plugin-draft/review",
        "/api/plugin-draft/apply",
        "/api/plugin-draft/smoke",
        "/api/plugin-draft/smoke/{run_id}",
        "/api/plugin-onboarding/session",
        "/api/plugin-onboarding/session/{session_id}/step",
        "/api/plugin-onboarding/session/{session_id}",
        "/api/plugin-onboarding/session/{session_id}/restore",
        "/api/plugin-onboarding/session/{session_id}/rollback/preview",
        "/api/plugin-onboarding/session/{session_id}/rollback",
        "/api/plugin-onboarding/sessions",
        "/api/scenarios",
        "/api/run/start",
        "/api/run/stop",
        "/api/run/status",
        "/api/run/dashboard",
        "/api/run/log",
        "/api/run/log/download",
        "/api/runs/recent",
        "/api/runs/recent/{run_id}/log",
        "/api/outputs",
        "/api/outputs/{filename}",
    }
    missing = sorted(required - route_paths)
    _record(results, "fastapi_app_import", not missing, "all required routes present" if not missing else f"missing routes: {missing}")


def check_scenarios(results: list[tuple[str, bool, str]]) -> None:
    scenario_items = scenarios.list_scenarios()
    has_global_nav = any(item.get("id") == "global_nav_main" for item in scenario_items)
    _record(
        results,
        "scenario_loader",
        isinstance(scenario_items, list) and has_global_nav,
        f"loaded {len(scenario_items)} scenarios",
    )


def check_output_safe_path(results: list[tuple[str, bool, str]]) -> None:
    original_output_dir = outputs.OUTPUT_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            outputs.OUTPUT_DIR = tmp_path
            report = tmp_path / "report.log"
            report.write_text("ok\n", encoding="utf-8")
            safe_ok = outputs.safe_output_path("report.log") == report.resolve()
            traversal_blocked = False
            try:
                outputs.safe_output_path("../runtime_config.json")
            except ValueError:
                traversal_blocked = True
    finally:
        outputs.OUTPUT_DIR = original_output_dir

    _record(
        results,
        "output_safe_path",
        safe_ok and traversal_blocked,
        "allowed file resolves and traversal is blocked",
    )


def check_runner_initial_state(results: list[tuple[str, bool, str]]) -> None:
    state = runner.RunManager().get_status()
    ok = (
        state.get("state") == "idle"
        and state.get("run_id") is None
        and state.get("log_path") is None
        and state.get("scenario_selection_applied") is False
    )
    _record(results, "runner_initial_state", ok, json.dumps(state, ensure_ascii=True, sort_keys=True))


def check_runtime_dashboard_parser(results: list[tuple[str, bool, str]]) -> None:
    summary = parse_runtime_log(
        "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']\n"
        "[QA_FRONTEND][preflight] final_result='passed' reason='ok'\n"
        "[STEP] START scenario='global_nav_main' step=0\n"
        "[PERF][scenario_summary] scenario=global_nav_main total_steps=1\n"
    )
    ok = summary.get("preflight_state") == "passed" and summary.get("completed_scenarios") == 1
    _record(results, "runtime_dashboard_parser", ok, json.dumps(summary, ensure_ascii=True, sort_keys=True))


def check_run_summary_sidecar(results: list[tuple[str, bool, str]]) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = Path(tmp_dir) / "20260528_090000_smoke.log"
        log_path.write_text(
            "[QA_FRONTEND][scenario_selection] enabled_ids=['global_nav_main']\n"
            "[PERF][scenario_summary] scenario=global_nav_main total_steps=1\n"
            "[MAIN] script end\n",
            encoding="utf-8",
        )
        summary = build_run_summary(
            status={
                "state": "finished",
                "run_id": "20260528_090000",
                "mode": "smoke",
                "started_at": "2026-05-28T09:00:00",
                "finished_at": "2026-05-28T09:00:10",
            },
            log_path=log_path,
            scenario_ids=["global_nav_main"],
        )
    ok = (
        summary.get("schema_version") == 1
        and summary.get("process_status") == "success"
        and summary.get("scenario_result_status") == "passed"
    )
    _record(results, "run_summary_sidecar", ok, json.dumps(summary, ensure_ascii=True, sort_keys=True))


def check_frontend_package(results: list[tuple[str, bool, str]]) -> None:
    package_json = FRONTEND_DIR / "package.json"
    if not package_json.is_file():
        _record(results, "frontend_package", False, "package.json missing")
        return
    data = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    ok = isinstance(scripts, dict) and "build" in scripts
    _record(results, "frontend_package", ok, f"build script present={bool('build' in scripts)}")


def check_backend_requirements(results: list[tuple[str, bool, str]]) -> None:
    if not BACKEND_REQUIREMENTS.is_file():
        _record(results, "backend_requirements", False, "requirements-qa_frontend.txt missing")
        return
    content = BACKEND_REQUIREMENTS.read_text(encoding="utf-8")
    ok = "fastapi" in content and "uvicorn" in content
    _record(results, "backend_requirements", ok, "fastapi/uvicorn entries present" if ok else "required entries missing")


def check_optional_adb(results: list[tuple[str, bool, str]]) -> None:
    adb_path = shutil.which("adb")
    _record(results, "optional_adb_available", True, adb_path or "adb not found in PATH; device checks remain manual")


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    check_fastapi_import(results)
    check_scenarios(results)
    check_output_safe_path(results)
    check_runner_initial_state(results)
    check_runtime_dashboard_parser(results)
    check_run_summary_sidecar(results)
    check_frontend_package(results)
    check_backend_requirements(results)
    check_optional_adb(results)

    failed = False
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}")
        if not ok:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
