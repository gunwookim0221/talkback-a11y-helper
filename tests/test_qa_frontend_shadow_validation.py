from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from qa_frontend.backend.main import BatchStartReq, StartRunRequest
from qa_frontend.backend import main
from qa_frontend.backend.runner import RunManager
from qa_frontend.backend.shadow_pipeline import run_shadow_validation_pipeline


def _runtime_config(path: Path, *, enabled: bool) -> Path:
    path.write_text(
        json.dumps(
            {
                "v10": {
                    "feature_flags": {
                        "inventory_enabled": False,
                        "quick_identify_enabled": False,
                        "policy_mapping_enabled": False,
                        "shadow_validation_enabled": enabled,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_request_models_default_shadow_validation_off():
    assert StartRunRequest().shadow_validation is False
    assert BatchStartReq(devices=[]).shadow_validation is False
    assert StartRunRequest(shadow_validation=True).shadow_validation is True
    assert BatchStartReq(devices=[], shadow_validation=True).shadow_validation is True


def test_backend_forwards_shadow_validation_to_run_managers(monkeypatch):
    single_calls: list[dict[str, object]] = []
    batch_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        main.runner,
        "start_run",
        lambda **kwargs: single_calls.append(kwargs) or {"state": "running"},
    )
    monkeypatch.setattr(
        main.global_batch_manager,
        "start_batch",
        lambda **kwargs: batch_calls.append(kwargs) or {"state": "running"},
    )

    main.run_start(StartRunRequest(shadow_validation=True))
    main.batch_start(BatchStartReq(devices=[], shadow_validation=True))

    assert single_calls[0]["shadow_validation"] is True
    assert batch_calls[0]["shadow_validation"] is True


def test_frontend_sends_shadow_validation_for_single_and_batch_runs():
    root = Path(__file__).resolve().parents[1]
    app = (root / "qa_frontend/frontend/src/App.tsx").read_text(encoding="utf-8")
    panel = (root / "qa_frontend/frontend/src/components/RunPanel.tsx").read_text(encoding="utf-8")
    api = (root / "qa_frontend/frontend/src/api.ts").read_text(encoding="utf-8")

    assert "useState(false)" in app
    assert "setEnableCoverageProbe(plannedMode === 'full')" in app
    assert "Runtime Coverage Probe" in panel
    assert "Recommended for Full runs." in panel
    assert "Shadow Validation (Experimental)" in panel
    assert "disabled={running || plannedMode !== 'full'}" in panel
    assert "shadow_validation: plannedMode === 'full' && shadowValidation" in panel
    assert "shadow_validation: shadowValidation" in api


def test_shadow_pipeline_requires_request_and_runtime_flag(tmp_path):
    client_calls: list[dict[str, object]] = []

    def client_factory(**kwargs):
        client_calls.append(kwargs)
        return object()

    disabled_by_request = run_shadow_validation_pipeline(
        runtime_config_path=_runtime_config(tmp_path / "request-off.json", enabled=True),
        requested=False,
        output_dir=tmp_path / "request-off",
        scenario_ids=[],
        client_factory=client_factory,
    )
    disabled_by_config = run_shadow_validation_pipeline(
        runtime_config_path=_runtime_config(tmp_path / "flag-off.json", enabled=False),
        requested=True,
        output_dir=tmp_path / "flag-off",
        scenario_ids=[],
        client_factory=client_factory,
    )

    assert disabled_by_request["status"] == "disabled"
    assert disabled_by_config["status"] == "disabled"
    assert client_calls == []
    assert not (tmp_path / "request-off" / "shadow").exists()
    assert not (tmp_path / "flag-off" / "shadow").exists()


def test_both_gates_run_pipeline_and_write_run_local_artifacts(tmp_path):
    config_path = _runtime_config(tmp_path / "runtime.json", enabled=True)
    inventory = {
        "inventory_id": "inventory-001",
        "items": [
            {
                "runtime_card_id": "card-001",
                "display_label": "Motion Sensor",
                "stable_label": "Motion sensor",
            }
        ],
    }

    def inventory_runner(*args, **kwargs):
        return {"status": "captured", "inventory": inventory, "artifact_path": "staged"}

    def identify_runner(*args, **kwargs):
        return {
            "status": "identified",
            "result": {
                "identify_run_id": "identify-001",
                "inventory_id": "inventory-001",
                "runtime_card_id": "card-001",
                "plugin_family_candidate": "MotionSensorCapability",
                "confidence": 96,
                "confidence_band": "definite",
                "decision": "identified",
                "restore_success": True,
                "candidates": [
                    {
                        "plugin_family": "MotionSensorCapability",
                        "quality_gate_passed": True,
                    }
                ],
            },
            "artifact_path": "staged",
        }

    def mapping_runner(*args, **kwargs):
        return {
            "status": "eligible",
            "result": {
                "inventory_id": "inventory-001",
                "runtime_card_id": "card-001",
                "plugin_family": "MotionSensorCapability",
                "scenario_candidate": "device_motion_sensor_plugin",
                "eligibility": "eligible",
                "confidence": 96,
                "mapping_revision": 1,
                "policy_version": "v10-scenario-policy-v1",
                "registry_version": "v10-policy-registry-v1",
                "traversal_allowed": False,
                "routing_performed": False,
            },
            "artifact_path": "staged",
        }

    output_dir = tmp_path / "qa_frontend_runs/batch/device"
    result = run_shadow_validation_pipeline(
        runtime_config_path=config_path,
        requested=True,
        output_dir=output_dir,
        scenario_ids=["device_motion_sensor_plugin"],
        serial="SERIAL",
        run_id="batch-001",
        device_name="Device",
        client_factory=lambda **kwargs: object(),
        surface_preparer=lambda client, serial: None,
        inventory_runner=inventory_runner,
        identify_runner=identify_runner,
        mapping_runner=mapping_runner,
    )

    shadow_dir = output_dir / "shadow"
    assert result["status"] == "completed"
    assert result["metrics"]["match_count"] == 1
    assert sorted(path.name for path in shadow_dir.iterdir()) == [
        "shadow_compare.json",
        "shadow_identify.json",
        "shadow_inventory.json",
        "shadow_report.md",
        "shadow_routing.json",
    ]
    report = json.loads((shadow_dir / "shadow_compare.json").read_text(encoding="utf-8"))
    assert report["legacy_authoritative"] is True
    assert report["v10_routing_performed"] is False
    assert "# V10 Shadow Validation Report" in (
        shadow_dir / "shadow_report.md"
    ).read_text(encoding="utf-8")


def test_shadow_exception_is_logged_without_changing_legacy_state(tmp_path, monkeypatch):
    manager = RunManager()
    manager._state = "finished"
    manager._mode = "full"
    manager._returncode = 0
    manager._shadow_validation_requested = True
    manager._runtime_config_path = str(_runtime_config(tmp_path / "runtime.json", enabled=True))
    manager._run_dir = tmp_path / "run"
    manager._scenario_ids = ["device_motion_sensor_plugin"]
    manager._run_id = "run-001"
    manager._log_path = tmp_path / "legacy.log"
    manager._log_path.write_text("legacy-pass\n", encoding="utf-8")

    monkeypatch.setattr(
        "qa_frontend.backend.runner.run_shadow_validation_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("shadow failed")),
    )

    manager._run_shadow_validation_safe()

    assert manager._state == "finished"
    assert manager._returncode == 0
    log = manager._log_path.read_text(encoding="utf-8")
    assert "legacy-pass" in log
    assert "status='warning'" in log
    assert "legacy_result_preserved=true" in log


def test_run_manager_calls_shadow_hook_after_legacy_completion(tmp_path, monkeypatch):
    source_path = _runtime_config(tmp_path / "runtime.json", enabled=True)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["scenarios"] = {
        "device_motion_sensor_plugin": {"enabled": False, "max_steps": 40}
    }
    source_path.write_text(json.dumps(source), encoding="utf-8")
    calls: list[dict[str, object]] = []

    class Process:
        returncode = 0

        def poll(self):
            return 0

    monkeypatch.setattr("qa_frontend.backend.runner.RUNTIME_CONFIG_PATH", source_path)
    monkeypatch.setattr("qa_frontend.backend.runner.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(
        "qa_frontend.backend.runner.prepare_runtime",
        lambda spec, language_fn, preflight_fn: (
            {"ok": True, "status": "ok", "language_mode": "current"},
            {"ok": True, "state": "passed", "reason": "ok"},
        ),
    )
    monkeypatch.setattr(
        "qa_frontend.backend.runner.start_execution",
        lambda **kwargs: SimpleNamespace(process=Process()),
    )
    monkeypatch.setattr("qa_frontend.backend.runner.wait_for_execution", lambda execution: 0)
    monkeypatch.setattr("qa_frontend.backend.runner.close_execution_log", lambda execution: None)
    monkeypatch.setattr("qa_frontend.backend.runner.enable_sleep_prevention", lambda: None)
    monkeypatch.setattr("qa_frontend.backend.runner.disable_sleep_prevention", lambda: None)
    monkeypatch.setattr(
        "qa_frontend.backend.runner.enable_device_stay_awake",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "qa_frontend.backend.runner.restore_device_stay_awake",
        lambda state: {"ok": True, "restored": True},
    )
    monkeypatch.setattr(
        "qa_frontend.backend.runner.run_shadow_validation_pipeline",
        lambda **kwargs: calls.append(kwargs)
        or {"status": "completed", "artifact_dir": str(tmp_path / "runs/shadow")},
    )

    manager = RunManager()
    manager.start_run(
        mode="full",
        scenario_ids=["device_motion_sensor_plugin"],
        shadow_validation=True,
    )
    deadline = time.time() + 1
    status = manager.get_status()
    while status["state"] == "running" and time.time() < deadline:
        time.sleep(0.01)
        status = manager.get_status()

    assert status["state"] == "finished"
    assert status["returncode"] == 0
    assert status["shadow_validation"] is True
    assert len(calls) == 1
    assert calls[0]["requested"] is True
    assert calls[0]["scenario_ids"] == ["device_motion_sensor_plugin"]
