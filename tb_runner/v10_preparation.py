from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

V10_PREPARATION_SCHEMA_VERSION = "v10-preparation-v1"
V10_ARTIFACT_ROOT = Path("artifacts/v10")
V10_FIXTURE_ROOT = Path("tests/fixtures/v10")
V10_VALIDATION_MATRIX_PATH = Path("config/v10_validation_matrix.json")

V10_ARTIFACT_DIRECTORIES = (
    "inventory",
    "identify",
    "routing",
    "shadow",
    "validation",
)

V10_FIXTURE_REQUIRED_FILES = (
    "inventory.json",
    "helper_dump.json",
    "window_dump.xml",
    "expected.json",
    "scenario.json",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _non_empty_string(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


@dataclass(frozen=True)
class V10FeatureFlags:
    inventory_enabled: bool = False
    quick_identify_enabled: bool = False
    policy_mapping_enabled: bool = False
    shadow_validation_enabled: bool = False

    @classmethod
    def from_mapping(cls, value: Any) -> V10FeatureFlags:
        raw = _mapping(value)
        return cls(
            inventory_enabled=raw.get("inventory_enabled") is True,
            quick_identify_enabled=raw.get("quick_identify_enabled") is True,
            policy_mapping_enabled=raw.get("policy_mapping_enabled") is True,
            shadow_validation_enabled=raw.get("shadow_validation_enabled") is True,
        )

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)

    @property
    def all_disabled(self) -> bool:
        return not any(self.as_dict().values())


@dataclass(frozen=True)
class V10VersionSchema:
    policy_version: str = "v10-scenario-policy-v1"
    registry_version: str = "v10-policy-registry-v1"
    mapping_revision: int = 1
    identify_contract_version: str = "v10-quick-identify-v1"
    shadow_validation_version: str = "v10-shadow-validation-v1"

    @classmethod
    def from_mapping(cls, value: Any) -> V10VersionSchema:
        raw = _mapping(value)
        defaults = cls()
        raw_revision = raw.get("mapping_revision")
        mapping_revision = (
            raw_revision
            if isinstance(raw_revision, int) and not isinstance(raw_revision, bool) and raw_revision > 0
            else defaults.mapping_revision
        )
        return cls(
            policy_version=_non_empty_string(raw.get("policy_version"), defaults.policy_version),
            registry_version=_non_empty_string(raw.get("registry_version"), defaults.registry_version),
            mapping_revision=mapping_revision,
            identify_contract_version=_non_empty_string(
                raw.get("identify_contract_version"),
                defaults.identify_contract_version,
            ),
            shadow_validation_version=_non_empty_string(
                raw.get("shadow_validation_version"),
                defaults.shadow_validation_version,
            ),
        )

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(frozen=True)
class V10ArtifactLayout:
    root: str = V10_ARTIFACT_ROOT.as_posix()
    inventory: str = (V10_ARTIFACT_ROOT / "inventory").as_posix()
    identify: str = (V10_ARTIFACT_ROOT / "identify").as_posix()
    routing: str = (V10_ARTIFACT_ROOT / "routing").as_posix()
    shadow: str = (V10_ARTIFACT_ROOT / "shadow").as_posix()
    validation: str = (V10_ARTIFACT_ROOT / "validation").as_posix()

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def build_v10_preparation_config(value: Any = None) -> dict[str, Any]:
    raw = _mapping(value)
    flags = V10FeatureFlags.from_mapping(raw.get("feature_flags"))
    versions = V10VersionSchema.from_mapping(raw.get("versions"))
    return {
        "schema_version": V10_PREPARATION_SCHEMA_VERSION,
        "preparation_only": True,
        "runtime_activation_supported": False,
        "feature_flags": flags.as_dict(),
        "versions": versions.as_dict(),
        "artifact_layout": V10ArtifactLayout().as_dict(),
        "fixture_root": V10_FIXTURE_ROOT.as_posix(),
        "validation_matrix_path": V10_VALIDATION_MATRIX_PATH.as_posix(),
    }
