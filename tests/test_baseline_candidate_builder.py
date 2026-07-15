from __future__ import annotations

import json
import zipfile
from pathlib import Path

from tb_runner.baseline_candidate_builder import build_baseline_candidate
from tb_runner.baseline_candidate_schema import BASELINE_CANDIDATE_SCHEMA_VERSION
from tb_runner.baseline_candidate_validator import validate_baseline_candidate
from tb_runner.canonical_json import canonical_json_bytes
from tb_runner.environment_fingerprint import build_environment_fingerprint
from tb_runner.environment_profile import ENVIRONMENT_PROFILE_SCHEMA_VERSION
from tb_runner.scenario_config import TAB_CONFIGS


CAPTURED_AT = "2026-07-15T00:00:00.000Z"


def _field(value, status="AVAILABLE"):
    return {
        "value": value,
        "status": status,
        "source": "test",
        "captured_at": CAPTURED_AT,
        "reason": "",
    }


def _environment_profile(*, complete: bool = True):
    profile = {
        "schema_version": ENVIRONMENT_PROFILE_SCHEMA_VERSION,
        "captured_at": CAPTURED_AT,
        "device": {
            "model": _field("SM-F741N"),
            "serial": _field(None, "REDACTED"),
            "serial_token": _field(None, "MISSING"),
            "device_family": _field("galaxy-z-flip6" if complete else None, "AVAILABLE" if complete else "MISSING"),
            "form_factor": _field("foldable_phone"),
        },
        "android": {
            "release": _field("15"),
            "sdk": _field(35),
            "build_fingerprint": _field(None, "REDACTED"),
            "one_ui_version": _field("7.0"),
        },
        "talkback": {
            "package": _field("com.samsung.android.accessibility.talkback"),
            "version_name": _field("15.1.01.1"),
            "version_code": _field(1510101000),
        },
        "target_app": {
            "package": _field("com.samsung.android.oneconnect"),
            "version_name": _field("1.8.47.24"),
            "version_code": _field(184724010),
        },
        "helper": {
            "package": _field("com.iotpart.sqe.talkbackhelper"),
            "version": _field("1.0"),
            "version_code": _field(1),
            "apk_sha256": _field("a" * 64),
        },
        "locale": _field("en-US"),
        "display": {},
        "fold": {},
        "repository": {"commit": _field("b" * 40), "dirty": _field(False)},
        "runtime": {
            "scenario_registry_hash": _field("c" * 64),
            "runtime_config_hash": _field("d" * 64),
            "traversal_contract": _field("production-traversal-v2"),
            "identity_contract": _field("target-relation-v2+canonical-observation-v1"),
            "feature_flags": _field(
                {
                    "evidence_ledger": True,
                    "identity_shadow_v2": True,
                    "traversal_identity_v2": True,
                    "runtime_profiler": True,
                }
            ),
            "collection_schema_versions": _field(
                {
                    "evidence": "evidence-event-v1",
                    "coverage": "audit-v7-focusable-coverage-v1",
                    "profiler": "traversal-profiler-v1",
                }
            ),
        },
    }
    profile["environment_fingerprint"] = build_environment_fingerprint(profile).to_dict()
    return profile


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _create_run(tmp_path: Path, *, complete_environment=True, targeted=False, legacy=False) -> Path:
    scenario_ids = [str(item["scenario_id"]) for item in TAB_CONFIGS]
    selected = scenario_ids[:2] if targeted else scenario_ids
    batch_root = tmp_path / "batch_test"
    run_root = batch_root / "device_safe"
    run_root.mkdir(parents=True)
    summary = {
        "state": "passed",
        "process_status": "passed",
        "scenario_result_status": "passed",
        "completed_scenarios": len(selected),
        "executed_scenarios": len(selected),
        "passed_scenarios": len(selected),
        "warning_scenarios": 0,
        "failed_scenarios": 0,
        "not_available_scenarios": 0,
        "feature_flags": {"evidence_ledger": True},
        "scenarios": [
            {"id": scenario_id, "status": "passed", "steps": 1, "stop_reason": "terminal"}
            for scenario_id in selected
        ],
        "quality_issues": [],
    }
    _write_json(run_root / "summary.json", summary)
    _write_json(
        batch_root / "batch_summary.json",
        {
            "batch_id": "batch_test",
            "mode": "full",
            "devices": [
                {"output_dir": str(run_root), "observed_scenario_ids": selected}
            ],
        },
    )
    if not legacy:
        _write_json(
            run_root / "talkback_compare.environment_profile.json",
            _environment_profile(complete=complete_environment),
        )
    manifest = {
        "schema_version": "evidence-event-v1",
        "run_id": "run_evidence_test",
        "manifest": {
            "repository_commit_sha": _field("b" * 40),
            "working_tree_dirty": _field(False),
            "runtime_config_hash": _field("d" * 64),
            "scenario_registry_hash": _field("c" * 64),
            "target_app_version": _field(
                "Package [com.samsung.android.oneconnect]\n"
                "versionCode=184724010\nversionName=1.8.47.24\n"
            ),
            "locale": _field("en-US"),
            "evidence_schema_version": _field("evidence-event-v1"),
            "feature_flags": {"evidence_ledger": True},
        },
    }
    # Historical evidence used lowercase status tokens.
    for value in manifest["manifest"].values():
        if isinstance(value, dict) and "status" in value:
            value["status"] = value["status"].lower()
    _write_json(run_root / "talkback_compare.evidence_manifest.json", manifest)
    _write_json(
        run_root / "talkback_compare.evidence_reconciliation.json",
        {
            "schema_version": "evidence-reconciliation-v1",
            "status": "PASS",
            "event_count": 100,
            "anchor_abort_scenarios": 0,
            "orphan_evidence": {"count": 0},
            "ledger": {"duplicate_event_count": 0, "write_failure_count": 0},
            "identity_shadow_v2": {
                "available": True,
                "transaction_count": 10,
                "verdicts": {"MOVE_CONFIRMED": 10},
            },
        },
    )
    _write_json(
        run_root / "talkback_compare.focusable_coverage.json",
        {
            "schema_version": "audit-v7-focusable-coverage-v1",
            "summary": [
                {
                    "scenario_id": scenario_id,
                    "expected_count": 1,
                    "covered_count": 1,
                    "missed_count": 0,
                    "unknown_count": 0,
                }
                for scenario_id in selected
            ],
            "records": [
                {
                    "scenario_id": scenario_id,
                    "canonical_id": f"{scenario_id}|view_id|target",
                    "taxonomy": "REQUIRED",
                }
                for scenario_id in selected
            ],
        },
    )
    _write_json(run_root / "runtime_config.json", {"scenarios": {}})
    with zipfile.ZipFile(run_root / "talkback_compare.profiler.zip", "w") as archive:
        for scenario_id in selected:
            archive.writestr(
                f"profiler/{scenario_id}.profiler.json",
                json.dumps(
                    {
                        "schema_version": "traversal-profiler-v1",
                        "scenario": scenario_id,
                        "runtime_ms": 1.0,
                        "metrics": {"scenario": {"count": 1, "duration_ms": 1.0}},
                        "counters": {},
                        "recovery": [],
                    }
                ),
            )
    return run_root


def test_complete_full_environment_is_approval_eligible(tmp_path):
    run_root = _create_run(tmp_path)
    result = build_baseline_candidate(run_root, write=False, created_at=CAPTURED_AT)

    assert result.candidate.candidate_schema == BASELINE_CANDIDATE_SCHEMA_VERSION
    assert result.candidate.environment_fingerprint["status"] == "COMPLETE"
    assert result.candidate.approval_state.value == "CANDIDATE"
    assert result.candidate.approval_eligibility.eligible is True


def test_incomplete_environment_creates_not_eligible_candidate(tmp_path):
    run_root = _create_run(tmp_path, complete_environment=False)
    result = build_baseline_candidate(run_root, write=False)

    assert result.candidate.environment_fingerprint["status"] == "INCOMPLETE"
    assert result.candidate.approval_state.value == "NOT_ELIGIBLE"
    assert result.candidate.approval_eligibility.eligible is False


def test_missing_required_artifact_is_validation_failure(tmp_path):
    run_root = _create_run(tmp_path)
    (run_root / "talkback_compare.focusable_coverage.json").unlink()
    result = build_baseline_candidate(run_root, write=False)

    assert "coverage_summary" in result.candidate.approval_eligibility.reasons
    assert "required_artifacts" in result.candidate.approval_eligibility.reasons


def test_targeted_run_has_stable_scenario_contract_and_is_not_eligible(tmp_path):
    run_root = _create_run(tmp_path, targeted=True)
    result = build_baseline_candidate(run_root, write=False)
    scenario_set = result.candidate.comparison_contract["scenario_set"]

    assert scenario_set["run_kind"] == "TARGETED"
    assert scenario_set["is_targeted"] is True
    assert scenario_set["selected_scenario_count"] == 2
    assert len(scenario_set["selected_scenario_hash"]) == 64
    assert len(scenario_set["scenario_order_hash"]) == 64
    assert result.candidate.approval_eligibility.eligible is False


def test_all_registry_scenarios_are_classified_as_full_run(tmp_path):
    run_root = _create_run(tmp_path)
    result = build_baseline_candidate(run_root, write=False)
    scenario_set = result.candidate.comparison_contract["scenario_set"]

    assert scenario_set["selected_scenario_count"] == len(TAB_CONFIGS) == 32
    assert scenario_set["run_kind"] == "FULL"
    assert scenario_set["is_targeted"] is False


def test_legacy_run_backfill_succeeds_but_is_not_eligible(tmp_path):
    run_root = _create_run(tmp_path, legacy=True)
    result = build_baseline_candidate(run_root, write=False)
    codes = {item["code"] for item in result.candidate.limitations}

    assert result.candidate.environment_fingerprint["status"] == "INCOMPLETE"
    assert result.candidate.approval_eligibility.eligible is False
    assert {"HISTORICAL_BACKFILL", "HISTORICAL_PARITY_UNAVAILABLE"} <= codes


def test_candidate_id_is_deterministic_across_creation_times(tmp_path):
    run_root = _create_run(tmp_path)
    first = build_baseline_candidate(run_root, write=False, created_at="2026-07-15T00:00:00Z")
    second = build_baseline_candidate(run_root, write=False, created_at="2026-07-16T00:00:00Z")

    assert first.candidate.candidate_id == second.candidate.candidate_id
    assert first.document_digest != second.document_digest


def test_validator_reports_pass_warning_and_fail(tmp_path):
    eligible = build_baseline_candidate(_create_run(tmp_path / "eligible"), write=False)
    assert eligible.candidate.validation_report["counts"]["PASS"] > 0
    assert eligible.candidate.validation_report["counts"]["WARNING"] == 0
    assert eligible.candidate.validation_report["counts"]["FAIL"] == 0

    payload = eligible.candidate.to_dict()
    payload["limitations"] = [{"code": "EMPTY_VISIBLE"}]
    warning_report = validate_baseline_candidate(payload)
    assert warning_report["counts"]["WARNING"] == 1

    payload["environment_fingerprint"]["status"] = "INVALID"
    fail_report = validate_baseline_candidate(payload)
    assert fail_report["counts"]["FAIL"] >= 1


def test_builder_writes_candidate_and_additive_references(tmp_path):
    run_root = _create_run(tmp_path)
    result = build_baseline_candidate(run_root, write=True, integrate=True, created_at=CAPTURED_AT)

    assert result.path is not None and result.path.is_file()
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    evidence = json.loads(
        (run_root / "talkback_compare.evidence_manifest.json").read_text(encoding="utf-8")
    )
    batch = json.loads((run_root.parent / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary["baseline_candidate"]["candidate_id"] == result.candidate.candidate_id
    assert evidence["manifest"]["baseline_candidate"]["candidate_id"] == result.candidate.candidate_id
    assert batch["devices"][0]["baseline_candidate"]["candidate_id"] == result.candidate.candidate_id


def test_artifact_manifest_uses_logical_references_and_structured_metadata(tmp_path):
    run_root = _create_run(tmp_path)
    result = build_baseline_candidate(run_root, write=False)
    artifacts = result.candidate.artifact_manifest["artifacts"]
    profiler = next(item for item in artifacts if item["artifact_type"] == "profiler_archive")

    assert profiler["relative_reference"].startswith("qa-run://batch_test/device/")
    assert profiler["document_digest"]["algorithm"] == "SHA-256"
    assert len(profiler["document_digest"]["value"]) == 64
    assert profiler["schema_version"] == "traversal-profiler-v1"
    assert profiler["size"] > 0
    assert profiler["created_at"].endswith("Z")
    assert str(run_root) not in result.candidate.to_canonical_json()
