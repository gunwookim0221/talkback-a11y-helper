from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from tb_runner.runtime_config import load_runtime_bundle
from tb_runner.v10_preparation import (
    V10_ARTIFACT_DIRECTORIES,
    V10_ARTIFACT_ROOT,
    V10_FIXTURE_REQUIRED_FILES,
    V10_FIXTURE_ROOT,
    V10_VALIDATION_MATRIX_PATH,
    V10ArtifactLayout,
    V10FeatureFlags,
    V10VersionSchema,
    build_v10_preparation_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_feature_flags_default_off_and_invalid_values_stay_off():
    defaults = V10FeatureFlags()
    invalid = V10FeatureFlags.from_mapping(
        {
            "inventory_enabled": "true",
            "quick_identify_enabled": 1,
            "policy_mapping_enabled": None,
            "shadow_validation_enabled": [],
        }
    )

    assert defaults.all_disabled is True
    assert invalid.all_disabled is True
    assert defaults.as_dict() == {
        "inventory_enabled": False,
        "quick_identify_enabled": False,
        "policy_mapping_enabled": False,
        "shadow_validation_enabled": False,
    }


def test_feature_flags_can_be_parsed_independently_without_runtime_activation():
    prepared = build_v10_preparation_config(
        {
            "feature_flags": {
                "inventory_enabled": True,
                "quick_identify_enabled": False,
                "policy_mapping_enabled": True,
                "shadow_validation_enabled": False,
            }
        }
    )

    assert prepared["feature_flags"]["inventory_enabled"] is True
    assert prepared["feature_flags"]["quick_identify_enabled"] is False
    assert prepared["feature_flags"]["policy_mapping_enabled"] is True
    assert prepared["feature_flags"]["shadow_validation_enabled"] is False
    assert prepared["preparation_only"] is True
    assert prepared["runtime_activation_supported"] is False


def test_version_schema_defaults_and_rejects_invalid_values():
    defaults = V10VersionSchema()
    parsed = V10VersionSchema.from_mapping(
        {
            "policy_version": " custom-policy-v2 ",
            "registry_version": "",
            "mapping_revision": 0,
            "identify_contract_version": None,
            "shadow_validation_version": "shadow-v2",
        }
    )

    assert parsed.policy_version == "custom-policy-v2"
    assert parsed.registry_version == defaults.registry_version
    assert parsed.mapping_revision == defaults.mapping_revision
    assert parsed.identify_contract_version == defaults.identify_contract_version
    assert parsed.shadow_validation_version == "shadow-v2"


def test_runtime_bundle_exposes_default_off_v10_section_without_changing_scenarios(tmp_path):
    base_tabs = [
        {
            "scenario_id": "device_motion_sensor_plugin",
            "tab_name": "Devices",
            "enabled": False,
            "max_steps": 40,
        }
    ]

    bundle = load_runtime_bundle(base_tabs, config_path=tmp_path / "missing.json")

    assert all(value is False for value in bundle["v10"]["feature_flags"].values())
    assert bundle["v10"]["runtime_activation_supported"] is False
    assert bundle["tab_configs"][0]["scenario_id"] == "device_motion_sensor_plugin"
    assert bundle["tab_configs"][0]["enabled"] is False
    assert bundle["tab_configs"][0]["max_steps"] == 40


def test_repository_runtime_config_keeps_every_v10_feature_off():
    raw = json.loads((REPO_ROOT / "config/runtime_config.json").read_text(encoding="utf-8"))
    flags = V10FeatureFlags.from_mapping(raw["v10"]["feature_flags"])
    versions = V10VersionSchema.from_mapping(raw["v10"]["versions"])

    assert flags.all_disabled is True
    assert versions.as_dict() == V10VersionSchema().as_dict()


def test_v10_section_does_not_change_legacy_scenario_resolution(tmp_path):
    base_tabs = [
        {
            "scenario_id": "device_motion_sensor_plugin",
            "tab_name": "Devices",
            "enabled": False,
            "max_steps": 40,
        }
    ]
    legacy_config = {
        "global": {"checkpoint_save_every": 5},
        "scenarios": {
            "device_motion_sensor_plugin": {
                "enabled": True,
                "max_steps": 12,
            }
        },
    }
    v10_config = {
        **legacy_config,
        "v10": {
            "feature_flags": {
                "inventory_enabled": True,
                "quick_identify_enabled": True,
                "policy_mapping_enabled": True,
                "shadow_validation_enabled": True,
            }
        },
    }
    legacy_path = tmp_path / "legacy.json"
    v10_path = tmp_path / "v10.json"
    legacy_path.write_text(json.dumps(legacy_config), encoding="utf-8")
    v10_path.write_text(json.dumps(v10_config), encoding="utf-8")

    legacy_bundle = load_runtime_bundle(base_tabs, config_path=legacy_path)
    v10_bundle = load_runtime_bundle(base_tabs, config_path=v10_path)

    assert v10_bundle["tab_configs"] == legacy_bundle["tab_configs"]
    assert v10_bundle["checkpoint_save_every"] == legacy_bundle["checkpoint_save_every"]
    assert v10_bundle["v10"]["runtime_activation_supported"] is False


def test_artifact_layout_matches_prepared_directories():
    layout = V10ArtifactLayout().as_dict()

    assert layout["root"] == V10_ARTIFACT_ROOT.as_posix()
    for directory in V10_ARTIFACT_DIRECTORIES:
        assert layout[directory] == (V10_ARTIFACT_ROOT / directory).as_posix()
        assert (REPO_ROOT / V10_ARTIFACT_ROOT / directory).is_dir()


def test_fixture_template_contains_required_parseable_files():
    template_dir = REPO_ROOT / V10_FIXTURE_ROOT / "cases/_template"

    assert template_dir.is_dir()
    for filename in V10_FIXTURE_REQUIRED_FILES:
        assert (template_dir / filename).is_file()

    for filename in V10_FIXTURE_REQUIRED_FILES:
        path = template_dir / filename
        if path.suffix == ".json":
            assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
        elif path.suffix == ".xml":
            assert ET.fromstring(path.read_text(encoding="utf-8")).tag == "hierarchy"


def test_validation_matrix_covers_current_device_scenarios_and_dimensions():
    matrix = json.loads((REPO_ROOT / V10_VALIDATION_MATRIX_PATH).read_text(encoding="utf-8"))
    families = matrix["device_families"]
    scenario_ids = {item["scenario_id"] for item in families}
    pilot_families = {item["family"] for item in families if item["pilot"]}

    assert len(families) == 12
    assert len(scenario_ids) == 12
    assert {"en-US", "ko-KR"}.issubset(matrix["languages"])
    assert {target["api_level"] for target in matrix["android_targets"]} == {33, 34, 35, 36}
    assert {
        "smoke_sensor",
        "water_leak_sensor",
        "motion_sensor",
        "door_lock",
        "tv",
        "washer",
    } == pilot_families
    assert {
        "device_family",
        "plugin_type",
        "language",
        "android_version",
        "app_version",
        "helper_version",
        "account",
        "location",
    } == set(matrix["required_dimensions"])
