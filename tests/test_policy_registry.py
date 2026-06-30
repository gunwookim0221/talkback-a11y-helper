from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tb_runner.policy_registry import (
    ALLOWED_ELIGIBILITY,
    POLICY_REGISTRY_SCHEMA_VERSION,
    ROUTING_CANDIDATE_ARTIFACT_VERSION,
    SCENARIO_CANDIDATE_SCHEMA_VERSION,
    PolicyRegistryEntry,
    build_policy_registry,
    map_quick_identify_result,
    run_policy_mapping_if_enabled,
    write_routing_candidate_artifact,
)
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.v10_preparation import V10VersionSchema

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests/fixtures/v10/routing/policy_mapping_cases.json"


def _clock():
    return datetime(2026, 7, 1, 3, 0, 0, tzinfo=timezone.utc)


def _identify(
    family: str,
    *,
    decision: str = "identified",
    confidence: int = 98,
    confidence_band: str = "definite",
    restore_success: bool = True,
    quality_gate_passed: bool = True,
) -> dict:
    return {
        "schema_version": "v10-quick-identify-result-v1",
        "identify_run_id": "identify-test",
        "inventory_id": "inventory-test",
        "runtime_card_id": "card-test",
        "decision": decision,
        "plugin_family_candidate": family,
        "confidence": confidence,
        "confidence_band": confidence_band,
        "restore_success": restore_success,
        "candidates": [
            {
                "plugin_family": family,
                "quality_gate_passed": quality_gate_passed,
            }
        ] if family != "unknown" else [],
    }


def test_registry_contains_all_current_device_scenarios_and_versions():
    versions = V10VersionSchema(
        policy_version="policy-test-v2",
        registry_version="registry-test-v3",
        mapping_revision=7,
    )
    registry = build_policy_registry(versions)
    configured = {
        config["scenario_id"]
        for config in TAB_CONFIGS
        if config["scenario_id"].startswith("device_")
        and config["scenario_id"].endswith("_plugin")
    }
    mapped = {entry.scenario_candidate for entry in registry.entries}

    assert registry.as_dict()["schema_version"] == POLICY_REGISTRY_SCHEMA_VERSION
    assert registry.policy_version == "policy-test-v2"
    assert registry.registry_version == "registry-test-v3"
    assert registry.mapping_revision == 7
    assert mapped == configured
    assert len(registry.entries) == 12
    assert all(entry.supported_capabilities for entry in registry.entries)


def test_exact_capability_mapping_creates_candidate_without_routing():
    candidate = map_quick_identify_result(
        _identify("MotionSensorCapability", confidence=87, confidence_band="high"),
        clock=_clock,
    )

    assert candidate["schema_version"] == SCENARIO_CANDIDATE_SCHEMA_VERSION
    assert candidate["artifact_version"] == ROUTING_CANDIDATE_ARTIFACT_VERSION
    assert candidate["plugin_family"] == "MotionSensorCapability"
    assert candidate["scenario_candidate"] == "device_motion_sensor_plugin"
    assert candidate["eligibility"] == "eligible"
    assert candidate["traversal_allowed"] is False
    assert candidate["routing_performed"] is False
    assert "scenario_id" not in candidate


def test_all_supported_families_map_to_expected_scenarios():
    expected = {
        "MotionSensorCapability": "device_motion_sensor_plugin",
        "SmokeDetectorCapability": "device_smoke_sensor_plugin",
        "LeakSensorCapability": "device_water_leak_sensor_plugin",
        "GenericLockCapability": "device_door_lock_plugin",
        "LaundryWasherCapability": "device_washer_plugin",
        "TVCapabilitySet": "device_tv_plugin",
        "AudioCapabilitySet": "device_audio_plugin",
        "CameraCapabilitySet": "device_camera_plugin",
        "HomeCamera360CapabilitySet": "device_home_camera_plugin",
        "AirPurifierCapabilitySet": "device_air_purifier_plugin",
        "HumiditySensorCapability": "device_humidity_sensor_plugin",
        "TemperatureHumiditySensorCapabilitySet": "device_temperature_humidity_sensor_plugin",
    }

    for family, scenario in expected.items():
        candidate = map_quick_identify_result(_identify(family), clock=_clock)
        assert candidate["scenario_candidate"] == scenario
        assert candidate["eligibility"] == "eligible"


def test_confidence_and_quality_gates_are_shadow_only():
    below_gate = map_quick_identify_result(
        _identify("MotionSensorCapability", confidence=72, confidence_band="medium"),
        clock=_clock,
    )
    quality_unconfirmed = map_quick_identify_result(
        _identify("TVCapabilitySet", quality_gate_passed=False),
        clock=_clock,
    )
    subtype_not_definite = map_quick_identify_result(
        _identify("HomeCamera360CapabilitySet", confidence=90, confidence_band="high"),
        clock=_clock,
    )

    assert below_gate["eligibility"] == "shadow_only"
    assert quality_unconfirmed["eligibility"] == "shadow_only"
    assert subtype_not_definite["eligibility"] == "shadow_only"
    assert all(
        item["scenario_candidate"]
        for item in (below_gate, quality_unconfirmed, subtype_not_definite)
    )


def test_fail_closed_states_never_return_scenario_candidate():
    cases = (
        _identify("unknown", decision="unknown"),
        _identify("unknown", decision="ambiguous"),
        _identify("MotionSensorCapability", decision="failed"),
        _identify("RobotVacuumCapabilitySet"),
        _identify("MotionSensorCapability", restore_success=False),
    )
    expected = ("unknown", "ambiguous", "failed", "unsupported", "failed")

    for identify_result, eligibility in zip(cases, expected):
        candidate = map_quick_identify_result(identify_result, clock=_clock)
        assert candidate["eligibility"] == eligibility
        assert candidate["eligibility"] in ALLOWED_ELIGIBILITY
        assert candidate["scenario_candidate"] == ""
        assert candidate["traversal_allowed"] is False


def test_duplicate_registry_mapping_is_ambiguous():
    duplicate = PolicyRegistryEntry(
        "MotionSensorCapability",
        ("MotionSensorCapability",),
        "device_smoke_sensor_plugin",
        "high",
        "eligible",
        "Intentional conflict fixture.",
    )
    base = build_policy_registry()
    registry = build_policy_registry(entries=(*base.entries, duplicate))

    candidate = map_quick_identify_result(
        _identify("MotionSensorCapability"),
        registry=registry,
        clock=_clock,
    )

    assert candidate["eligibility"] == "ambiguous"
    assert candidate["scenario_candidate"] == ""
    assert candidate["reason"] == "multiple_registry_mappings"


def test_version_schema_is_reused_in_candidate():
    versions = V10VersionSchema(
        policy_version="policy-v9",
        registry_version="registry-v8",
        mapping_revision=42,
    )
    candidate = map_quick_identify_result(
        _identify("GenericLockCapability"),
        versions=versions,
        clock=_clock,
    )

    assert candidate["policy_version"] == versions.policy_version
    assert candidate["registry_version"] == versions.registry_version
    assert candidate["mapping_revision"] == versions.mapping_revision


def test_artifact_schema_and_routing_directory(tmp_path):
    candidate = map_quick_identify_result(
        _identify("LaundryWasherCapability"),
        clock=_clock,
    )
    path = write_routing_candidate_artifact(candidate, artifact_dir=tmp_path / "routing")
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert path.parent.name == "routing"
    assert saved == candidate
    assert saved["artifact_version"] == ROUTING_CANDIDATE_ARTIFACT_VERSION
    assert saved["routing_performed"] is False
    assert saved["traversal_allowed"] is False


def test_feature_flag_off_performs_no_lookup_or_artifact(tmp_path):
    output = run_policy_mapping_if_enabled(
        {"feature_flags": {"policy_mapping_enabled": False}},
        _identify("MotionSensorCapability"),
        artifact_dir=tmp_path,
        clock=_clock,
    )

    assert output == {"status": "disabled", "result": None, "artifact_path": ""}
    assert list(tmp_path.iterdir()) == []


def test_feature_flag_on_creates_shadow_candidate_only(tmp_path):
    versions = V10VersionSchema(
        policy_version="policy-config",
        registry_version="registry-config",
        mapping_revision=3,
    )
    output = run_policy_mapping_if_enabled(
        {
            "feature_flags": {"policy_mapping_enabled": True},
            "versions": versions.as_dict(),
        },
        _identify("TVCapabilitySet"),
        artifact_dir=tmp_path,
        clock=_clock,
    )

    assert output["status"] == "eligible"
    assert output["result"]["scenario_candidate"] == "device_tv_plugin"
    assert output["result"]["routing_performed"] is False
    assert output["result"]["traversal_allowed"] is False
    assert Path(output["artifact_path"]).is_file()


def test_fixture_replay():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for case in payload["cases"]:
        result = map_quick_identify_result(
            {
                "identify_run_id": f"identify-{case['id']}",
                "inventory_id": "inventory-fixture",
                "runtime_card_id": f"card-{case['id']}",
                "decision": case["decision"],
                "plugin_family_candidate": case["plugin_family_candidate"],
                "confidence": case["confidence"],
                "confidence_band": case["confidence_band"],
                "restore_success": case["restore_success"],
                "candidates": [],
            },
            clock=_clock,
        )
        assert result["scenario_candidate"] == case["expected_scenario"]
        assert result["eligibility"] == case["expected_eligibility"]
