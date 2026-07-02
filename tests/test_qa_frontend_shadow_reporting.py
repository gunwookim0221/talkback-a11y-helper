from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from qa_frontend.backend.batch_runner import get_recent_batches
from qa_frontend.backend.main import app
from qa_frontend.backend.shadow_reporting import (
    load_shadow_validation_summary,
    open_shadow_folder,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_completed_shadow(device_dir: Path) -> None:
    shadow_dir = device_dir / "shadow"
    _write_json(
        shadow_dir / "shadow_inventory.json",
        {
            "inventory": {
                "item_count": 15,
                "captured_at": "2026-07-02T00:00:00Z",
                "items": [{"runtime_card_id": f"card-{index}"} for index in range(15)],
            }
        },
    )
    _write_json(
        shadow_dir / "shadow_identify.json",
        {
            "results": [
                {
                    "runtime_card_id": "card-motion",
                    "decision": "identified",
                    "plugin_family_candidate": "MotionSensorCapability",
                },
                *[
                    {
                        "runtime_card_id": f"card-identified-{index}",
                        "decision": "identified",
                        "plugin_family_candidate": "GenericLockCapability",
                    }
                    for index in range(5)
                ],
                *[
                    {
                        "runtime_card_id": f"card-unknown-{index}",
                        "decision": "unknown",
                        "plugin_family_candidate": "unknown",
                    }
                    for index in range(9)
                ],
            ]
        },
    )
    comparisons = [
        {
            "runtime_card_id": "card-motion",
            "legacy_scenario": "device_motion_sensor_plugin",
            "shadow_candidate": "device_motion_sensor_plugin",
            "comparison_result": "MATCH",
            "promotion_eligible": True,
            "legacy_authoritative": True,
        },
        *[
            {
                "runtime_card_id": f"card-match-{index}",
                "legacy_scenario": "device_door_lock_plugin",
                "shadow_candidate": "device_door_lock_plugin",
                "comparison_result": "MATCH",
                "promotion_eligible": True,
                "legacy_authoritative": True,
            }
            for index in range(5)
        ],
        *[
            {
                "runtime_card_id": f"card-unknown-{index}",
                "legacy_scenario": "device_audio_plugin",
                "shadow_candidate": "",
                "comparison_result": "UNKNOWN",
                "promotion_eligible": False,
                "legacy_authoritative": True,
            }
            for index in range(9)
        ],
    ]
    _write_json(
        shadow_dir / "shadow_compare.json",
        {
            "created_at": "2026-07-02T00:04:00Z",
            "legacy_authoritative": True,
            "metrics": {
                "attempt_count": 15,
                "match_count": 6,
                "unknown_count": 9,
                "ambiguous_count": 0,
                "mismatch_count": 0,
                "failed_count": 0,
                "promotion_eligible_count": 6,
            },
            "comparisons": comparisons,
        },
    )
    (shadow_dir / "shadow_report.md").write_text("# report", encoding="utf-8")
    _write_json(
        shadow_dir / "promotion_readiness.json",
        {
            "overall_status": "HOLD",
            "legacy_preserved": True,
            "controlled_routing_enabled": False,
            "status_counts": {
                "READY": 1,
                "HOLD": 1,
                "BLOCKED": 0,
                "INSUFFICIENT_DATA": 1,
                "UNKNOWN_ONLY": 0,
            },
            "families": [
                {
                    "plugin_family": "Door Lock",
                    "status": "READY",
                    "reason": "readiness_gates_satisfied",
                }
            ],
        },
    )
    (shadow_dir / "promotion_readiness.md").write_text(
        "# readiness", encoding="utf-8"
    )


def test_shadow_summary_matches_completed_artifacts(tmp_path):
    device_dir = tmp_path / "qa_frontend_runs/batch_1/device_Model_SERIAL"
    _write_completed_shadow(device_dir)

    summary = load_shadow_validation_summary(device_dir, root_dir=tmp_path)

    assert summary is not None
    assert summary["status"] == "completed"
    assert summary["inventory_count"] == 15
    assert summary["identified_count"] == 6
    assert summary["identify_unknown_count"] == 9
    assert summary["match_count"] == 6
    assert summary["unknown_count"] == 9
    assert summary["ambiguous_count"] == 0
    assert summary["mismatch_count"] == 0
    assert summary["failed_count"] == 0
    assert summary["promotion_eligible_count"] == 6
    assert summary["legacy_preserved"] is True
    assert summary["runtime_seconds"] == 240.0
    assert summary["result_groups"]["MATCH"] == ["Motion", "Door Lock"]
    assert summary["result_groups"]["UNKNOWN"] == ["Audio"]
    assert summary["promotion_readiness"]["overall_status"] == "HOLD"
    assert summary["promotion_readiness"]["status_counts"]["READY"] == 1
    assert summary["artifacts"]["readiness_report"].endswith(
        "shadow/promotion_readiness.md"
    )
    assert summary["artifacts"]["report"].endswith("shadow/shadow_report.md")
    assert summary["artifacts"]["compare"].endswith("shadow/shadow_compare.json")


def test_shadow_summary_is_absent_without_shadow_artifacts(tmp_path):
    device_dir = tmp_path / "device_Model_SERIAL"
    device_dir.mkdir()

    assert load_shadow_validation_summary(device_dir, root_dir=tmp_path) is None


def test_recent_batches_include_optional_shadow_summary(tmp_path, monkeypatch):
    run_log_dir = tmp_path / "qa_frontend_runs"
    batch_dir = run_log_dir / "batch_1"
    device_dir = batch_dir / "device_Model_SERIAL"
    _write_completed_shadow(device_dir)
    _write_json(
        batch_dir / "batch_summary.json",
        {
            "batch_id": "batch_1",
            "mode": "full",
            "created_at": "2026-07-02T00:00:00+00:00",
            "state": "finished",
            "devices": [
                {
                    "serial": "SERIAL",
                    "model": "Model",
                    "state": "passed",
                    "return_code": 0,
                    "output_dir": "qa_frontend_runs/batch_1/device_Model_SERIAL",
                }
            ],
        },
    )
    monkeypatch.setattr("qa_frontend.backend.batch_runner.RUN_LOG_DIR", run_log_dir)
    monkeypatch.setattr("qa_frontend.backend.batch_runner.ROOT_DIR", tmp_path)

    batches = get_recent_batches()

    assert batches[0]["devices"][0]["shadow_validation"]["inventory_count"] == 15
    assert batches[0]["devices"][0]["shadow_validation"]["match_count"] == 6


def test_shadow_failure_is_visible_and_preserves_legacy(tmp_path):
    device_dir = tmp_path / "device_Model_SERIAL"
    _write_json(
        device_dir / "shadow/shadow_error.json",
        {
            "stage": "inventory",
            "error": "device_tab_selection_failed",
            "legacy_result_preserved": True,
        },
    )
    (device_dir / "shadow/shadow_report.md").write_text("# failed", encoding="utf-8")

    summary = load_shadow_validation_summary(device_dir, root_dir=tmp_path)

    assert summary is not None
    assert summary["status"] == "failed"
    assert summary["error_stage"] == "inventory"
    assert summary["error"] == "device_tab_selection_failed"
    assert summary["legacy_preserved"] is True


def test_open_shadow_folder_uses_validated_device_path(tmp_path):
    shadow_dir = tmp_path / "batch_1/device_Model_SERIAL/shadow"
    shadow_dir.mkdir(parents=True)
    opened: list[Path] = []

    result = open_shadow_folder(
        "batch_1",
        "device_Model_SERIAL",
        run_log_dir=tmp_path,
        opener=opened.append,
    )

    assert result == shadow_dir.resolve()
    assert opened == [shadow_dir.resolve()]


def test_shadow_folder_endpoint_opens_folder(monkeypatch, tmp_path):
    opened = tmp_path / "shadow"
    monkeypatch.setattr(
        "qa_frontend.backend.main.open_shadow_folder",
        lambda run_id, device_id: opened,
    )

    response = TestClient(app).post(
        "/api/runs/batch_1/devices/device_Model_SERIAL/shadow/open-folder"
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "path": str(opened)}


def test_frontend_renders_shadow_summary_and_artifact_actions():
    panel = Path("qa_frontend/frontend/src/components/RecentRunsPanel.tsx").read_text(
        encoding="utf-8"
    )
    api = Path("qa_frontend/frontend/src/api.ts").read_text(encoding="utf-8")

    assert "V10 Shadow Validation" in panel
    assert "Promotion Eligible" in panel
    assert "Legacy Preserved" in panel
    assert "Open Shadow Report" in panel
    assert "Open Compare JSON" in panel
    assert "Open Shadow Folder" in panel
    assert "Promotion Readiness" in panel
    assert "Controlled routing remains disabled" in panel
    assert "Open Readiness Report" in panel
    assert "shadowValidation?.available" in panel
    assert "openShadowFolder" in api
