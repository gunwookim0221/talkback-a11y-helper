"""Read-only EnvironmentProfile collection for Phase 10.1A."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from tb_runner.canonical_json import canonical_json_bytes, canonical_sha256
from tb_runner.environment_profile import (
    ENVIRONMENT_PROFILE_SCHEMA_VERSION,
    TRAVERSAL_CONTRACT_VERSION,
    AndroidEnvironment,
    DeviceEnvironment,
    DisplayEnvironment,
    EnvironmentField,
    EnvironmentProfile,
    FieldStatus,
    FoldEnvironment,
    HelperEnvironment,
    PackageEnvironment,
    RepositoryEnvironment,
    RuntimeEnvironment,
    profile_status_counts,
)
from tb_runner.environment_fingerprint import (
    build_environment_fingerprint,
    document_digest_reference,
)
from tb_runner.environment_redaction import SerialTokenProvider, redact_environment_profile
from tb_runner.environment_validator import (
    DisplayDensityMetadata,
    DisplaySizeMetadata,
    FoldMetadata,
    PackageMetadata,
    ValidationResult,
    normalize_locale,
    parse_active_display,
    parse_display_density,
    parse_display_size,
    parse_fold_state,
    parse_one_ui_version,
    parse_package_metadata,
    select_active_talkback_package,
    validate_git_commit,
    validate_int,
    validate_nonempty_text,
)
from tb_runner.evidence import EVIDENCE_SCHEMA_VERSION
from tb_runner.evidence_identity import IDENTITY_NORMALIZATION_VERSION, IDENTITY_RULE_VERSION
from tb_runner.runtime_config import RUNTIME_CONFIG_VERSION
from tb_runner.traversal_profiler import PROFILER_SCHEMA_VERSION


TARGET_APP_PACKAGE = "com.samsung.android.oneconnect"
HELPER_PACKAGE = "com.iotpart.sqe.talkbackhelper"
ONE_UI_PROPERTIES = (
    "ro.build.version.oneui",
    "ro.build.version.oneui.version",
    "ro.build.version.oneui_version",
)
COLLECTION_SCHEMA_VERSIONS = {
    "evidence": EVIDENCE_SCHEMA_VERSION,
    "evidence_reconciliation": "evidence-reconciliation-v1",
    "focusable_inventory": "audit-v7-focusable-inventory-v1",
    "focusable_coverage": "audit-v7-focusable-coverage-v1",
    "profiler": PROFILER_SCHEMA_VERSION,
    "runtime_config": RUNTIME_CONFIG_VERSION,
}
IDENTITY_CONTRACT_VERSION = f"{IDENTITY_RULE_VERSION}+{IDENTITY_NORMALIZATION_VERSION}"

AdbRunner = Callable[[list[str], float], Mapping[str, Any]]
GitReader = Callable[[tuple[str, ...]], str | None]


@dataclass(frozen=True)
class EnvironmentCaptureResult:
    local_profile: EnvironmentProfile
    shared_profile: dict[str, Any]
    document_digest: str
    path: Path | None
    reference: dict[str, Any]

    @property
    def environment_hash(self) -> str:
        """Deprecated compatibility alias for document_digest."""
        return self.document_digest


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_file(path: Path | None) -> ValidationResult:
    if path is None or not path.is_file():
        return ValidationResult(FieldStatus.MISSING, reason="file_unavailable")
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return ValidationResult(FieldStatus.AVAILABLE, digest.hexdigest())
    except OSError as exc:
        return ValidationResult(FieldStatus.INVALID, reason=f"file_hash_failed:{type(exc).__name__}")


def _default_git_reader(repo_root: Path) -> GitReader:
    def read(args: tuple[str, ...]) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    return read


class EnvironmentCollector:
    def __init__(
        self,
        *,
        adb_runner: AdbRunner,
        repo_root: Path,
        serial: str | None,
        runtime_config_path: str | Path | None,
        scenario_registry_path: str | Path | None,
        feature_flags: Mapping[str, Any] | None = None,
        git_reader: GitReader | None = None,
        captured_at: str | None = None,
    ) -> None:
        self.adb_runner = adb_runner
        self.repo_root = Path(repo_root)
        self.serial = str(serial or "").strip()
        self.runtime_config_path = Path(runtime_config_path) if runtime_config_path else None
        self.scenario_registry_path = Path(scenario_registry_path) if scenario_registry_path else None
        self.feature_flags = dict(feature_flags or {})
        self.git_reader = git_reader or _default_git_reader(self.repo_root)
        self.captured_at = captured_at or utc_now()

    def _adb_text(self, args: list[str], timeout: float = 8.0) -> ValidationResult:
        try:
            result = self.adb_runner(args, timeout)
        except Exception as exc:
            return ValidationResult(FieldStatus.MISSING, reason=f"adb_exception:{type(exc).__name__}")
        if not result.get("ok"):
            return ValidationResult(
                FieldStatus.MISSING,
                reason=str(result.get("error") or result.get("stderr") or "adb_command_failed").strip(),
            )
        return validate_nonempty_text(result.get("stdout"))

    def _field(self, result: ValidationResult, source: str) -> EnvironmentField:
        return EnvironmentField(
            value=result.value,
            status=result.status,
            source=source,
            captured_at=self.captured_at,
            reason=result.reason,
        )

    def _missing(self, source: str, reason: str) -> EnvironmentField:
        return self._field(ValidationResult(FieldStatus.MISSING, reason=reason), source)

    def _collect_one_ui(self) -> EnvironmentField:
        invalid_reason = ""
        attempted: list[str] = []
        for prop in ONE_UI_PROPERTIES:
            attempted.append(prop)
            raw = self._adb_text(["shell", "getprop", prop])
            if raw.status == FieldStatus.MISSING:
                continue
            parsed = parse_one_ui_version(raw.value)
            if parsed.status == FieldStatus.AVAILABLE:
                return self._field(parsed, f"adb:getprop:{prop}")
            invalid_reason = parsed.reason
        status = FieldStatus.INVALID if invalid_reason else FieldStatus.MISSING
        return self._field(
            ValidationResult(status, reason=invalid_reason or "one_ui_property_unavailable"),
            "adb:getprop:fallback(" + ",".join(attempted) + ")",
        )

    def _collect_package(self, package: str) -> tuple[EnvironmentField, EnvironmentField, EnvironmentField]:
        source = f"adb:dumpsys:package:{package}"
        raw = self._adb_text(["shell", "dumpsys", "package", package])
        if raw.status != FieldStatus.AVAILABLE:
            field = self._field(raw, source)
            return field, field, field
        parsed = parse_package_metadata(package, raw.value)
        if parsed.status != FieldStatus.AVAILABLE:
            field = self._field(parsed, source)
            return field, field, field
        metadata = parsed.value
        assert isinstance(metadata, PackageMetadata)
        return (
            self._field(ValidationResult(FieldStatus.AVAILABLE, metadata.package), source),
            self._field(ValidationResult(FieldStatus.AVAILABLE, metadata.version_name), source),
            self._field(ValidationResult(FieldStatus.AVAILABLE, metadata.version_code), source),
        )

    def _collect_talkback(self) -> PackageEnvironment:
        service_source = "adb:settings:secure:enabled_accessibility_services"
        services = self._adb_text(
            ["shell", "settings", "get", "secure", "enabled_accessibility_services"]
        )
        if services.status != FieldStatus.AVAILABLE:
            unavailable = self._field(services, service_source)
            return PackageEnvironment(unavailable, unavailable, unavailable)
        selected = select_active_talkback_package(services.value)
        if selected.status != FieldStatus.AVAILABLE:
            unavailable = self._field(selected, service_source)
            return PackageEnvironment(unavailable, unavailable, unavailable)
        package = str(selected.value)
        package_field, version_name, version_code = self._collect_package(package)
        package_field = self._field(ValidationResult(FieldStatus.AVAILABLE, package), service_source)
        return PackageEnvironment(package_field, version_name, version_code)

    def _collect_helper(self) -> HelperEnvironment:
        package, version, version_code = self._collect_package(HELPER_PACKAGE)
        path_source = f"adb:pm:path:{HELPER_PACKAGE}"
        apk_path = self._adb_text(["shell", "pm", "path", HELPER_PACKAGE])
        apk_hash_result = ValidationResult(FieldStatus.MISSING, reason="helper_apk_path_unavailable")
        hash_source = path_source
        if apk_path.status == FieldStatus.AVAILABLE:
            match = re.search(r"(?m)^package:(/[^\r\n]+)$", str(apk_path.value))
            if not match:
                apk_hash_result = ValidationResult(FieldStatus.INVALID, reason="helper_apk_path_unparseable")
            else:
                remote_path = match.group(1).strip()
                hash_source = f"adb:sha256sum:{HELPER_PACKAGE}"
                raw_hash = self._adb_text(["shell", "sha256sum", remote_path])
                if raw_hash.status == FieldStatus.AVAILABLE:
                    digest_match = re.match(r"^([0-9a-fA-F]{64})(?:\s|$)", str(raw_hash.value))
                    apk_hash_result = (
                        ValidationResult(FieldStatus.AVAILABLE, digest_match.group(1).lower())
                        if digest_match
                        else ValidationResult(FieldStatus.INVALID, reason="helper_apk_hash_unparseable")
                    )
                else:
                    apk_hash_result = raw_hash
        return HelperEnvironment(
            package=package,
            version=version,
            version_code=version_code,
            apk_sha256=self._field(apk_hash_result, hash_source),
        )

    def _collect_locale(self) -> EnvironmentField:
        for prop in ("persist.sys.locale", "ro.product.locale"):
            raw = self._adb_text(["shell", "getprop", prop])
            if raw.status == FieldStatus.MISSING:
                continue
            parsed = normalize_locale(raw.value)
            return self._field(parsed, f"adb:getprop:{prop}")
        return self._missing(
            "adb:getprop:fallback(persist.sys.locale,ro.product.locale)",
            "locale_property_unavailable",
        )

    def _collect_display(self) -> DisplayEnvironment:
        size_source = "adb:wm:size"
        density_source = "adb:wm:density"
        size_raw = self._adb_text(["shell", "wm", "size"])
        size_result = parse_display_size(size_raw.value) if size_raw.status == FieldStatus.AVAILABLE else size_raw
        density_raw = self._adb_text(["shell", "wm", "density"])
        density_result = (
            parse_display_density(density_raw.value) if density_raw.status == FieldStatus.AVAILABLE else density_raw
        )

        if size_result.status == FieldStatus.AVAILABLE and isinstance(size_result.value, DisplaySizeMetadata):
            size = size_result.value
            physical = self._field(
                ValidationResult(FieldStatus.AVAILABLE, size.physical)
                if size.physical
                else ValidationResult(FieldStatus.MISSING, reason="physical_size_unavailable"),
                size_source,
            )
            logical = self._field(ValidationResult(FieldStatus.AVAILABLE, size.logical), size_source)
            override = self._field(
                ValidationResult(FieldStatus.AVAILABLE, size.override)
                if size.override
                else ValidationResult(FieldStatus.MISSING, reason="override_size_not_set"),
                size_source,
            )
        else:
            physical = logical = override = self._field(size_result, size_source)

        if density_result.status == FieldStatus.AVAILABLE and isinstance(
            density_result.value, DisplayDensityMetadata
        ):
            density = density_result.value
            logical_density = self._field(
                ValidationResult(FieldStatus.AVAILABLE, density.logical), density_source
            )
            physical_density = self._field(
                ValidationResult(FieldStatus.AVAILABLE, density.physical)
                if density.physical is not None
                else ValidationResult(FieldStatus.MISSING, reason="physical_density_unavailable"),
                density_source,
            )
            override_density = self._field(
                ValidationResult(FieldStatus.AVAILABLE, density.override)
                if density.override is not None
                else ValidationResult(FieldStatus.MISSING, reason="override_density_not_set"),
                density_source,
            )
        else:
            logical_density = physical_density = override_density = self._field(density_result, density_source)
        return DisplayEnvironment(
            physical_size=physical,
            logical_size=logical,
            override_size=override,
            density=logical_density,
            physical_density=physical_density,
            override_density=override_density,
        )

    def _collect_fold(self) -> FoldEnvironment:
        source = "adb:cmd:device_state"
        current = self._adb_text(["shell", "cmd", "device_state", "print-state"])
        supported = self._adb_text(["shell", "cmd", "device_state", "print-states"])
        active_display_raw = self._adb_text(["shell", "dumpsys", "window", "displays"], timeout=12.0)
        active_display_result = (
            parse_active_display(active_display_raw.value)
            if active_display_raw.status == FieldStatus.AVAILABLE
            else active_display_raw
        )
        active_display = self._field(active_display_result, "adb:dumpsys:window:displays")
        if supported.status != FieldStatus.AVAILABLE:
            unavailable = self._field(supported, source)
            return FoldEnvironment(unavailable, unavailable, active_display)
        parsed = parse_fold_state(
            current.value if current.status == FieldStatus.AVAILABLE else None,
            supported.value,
        )
        if parsed.status != FieldStatus.AVAILABLE or not isinstance(parsed.value, FoldMetadata):
            unavailable = self._field(parsed, source)
            return FoldEnvironment(unavailable, unavailable, active_display)
        metadata = parsed.value
        capability = self._field(ValidationResult(FieldStatus.AVAILABLE, metadata.capability), source)
        posture = self._field(
            ValidationResult(FieldStatus.AVAILABLE, metadata.posture)
            if metadata.posture
            else ValidationResult(FieldStatus.MISSING, reason="posture_not_applicable"),
            source,
        )
        return FoldEnvironment(
            capability=capability,
            posture=posture,
            active_display=active_display,
        )

    def _collect_repository(self) -> RepositoryEnvironment:
        commit = validate_git_commit(self.git_reader(("rev-parse", "HEAD")))
        dirty_output = self.git_reader(("status", "--porcelain"))
        dirty = (
            ValidationResult(FieldStatus.AVAILABLE, bool(dirty_output))
            if dirty_output is not None
            else ValidationResult(FieldStatus.MISSING, reason="git_status_unavailable")
        )
        return RepositoryEnvironment(
            commit=self._field(commit, "git:rev-parse:HEAD"),
            dirty=self._field(dirty, "git:status:porcelain"),
        )

    def _collect_feature_flags(self) -> EnvironmentField:
        flags = dict(self.feature_flags)
        source = "runtime:resolved_feature_flags"
        if self.runtime_config_path is None or not self.runtime_config_path.is_file():
            return self._field(
                ValidationResult(
                    FieldStatus.MISSING,
                    value=dict(sorted(flags.items())),
                    reason="runtime_config_unavailable_for_feature_flags",
                ),
                source,
            )
        try:
            payload = json.loads(self.runtime_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return self._field(
                ValidationResult(
                    FieldStatus.INVALID,
                    value=dict(sorted(flags.items())),
                    reason=f"runtime_feature_flags_unparseable:{type(exc).__name__}",
                ),
                source,
            )
        v10 = payload.get("v10") if isinstance(payload, dict) else None
        v10_flags = v10.get("feature_flags") if isinstance(v10, dict) else None
        if isinstance(v10_flags, dict):
            for name, value in v10_flags.items():
                if isinstance(name, str) and isinstance(value, bool):
                    flags[f"v10.{name}"] = value
        return self._field(
            ValidationResult(FieldStatus.AVAILABLE, dict(sorted(flags.items()))),
            source + "+file:runtime_config:v10.feature_flags",
        )

    def collect(self) -> EnvironmentProfile:
        model_raw = self._adb_text(["shell", "getprop", "ro.product.model"])
        serial_source = "runspec:serial"
        if self.serial:
            serial_result = ValidationResult(FieldStatus.AVAILABLE, self.serial)
        else:
            serial_source = "adb:get-serialno"
            serial_result = self._adb_text(["get-serialno"])
        device = DeviceEnvironment(
            model=self._field(model_raw, "adb:getprop:ro.product.model"),
            serial=self._field(serial_result, serial_source),
            serial_token=self._missing("redaction:serial_token_provider", "not_applied_to_local_profile"),
            device_family=self._missing("policy:device_family", "device_family_mapping_not_configured"),
            form_factor=self._missing("policy:form_factor", "form_factor_mapping_not_configured"),
        )

        release_raw = self._adb_text(["shell", "getprop", "ro.build.version.release"])
        sdk_raw = self._adb_text(["shell", "getprop", "ro.build.version.sdk"])
        fingerprint_raw = self._adb_text(["shell", "getprop", "ro.build.fingerprint"])
        android = AndroidEnvironment(
            release=self._field(release_raw, "adb:getprop:ro.build.version.release"),
            sdk=self._field(
                validate_int(sdk_raw.value, minimum=1)
                if sdk_raw.status == FieldStatus.AVAILABLE
                else sdk_raw,
                "adb:getprop:ro.build.version.sdk",
            ),
            build_fingerprint=self._field(fingerprint_raw, "adb:getprop:ro.build.fingerprint"),
            one_ui_version=self._collect_one_ui(),
        )

        target_package, target_version, target_code = self._collect_package(TARGET_APP_PACKAGE)
        runtime_config_hash = sha256_file(self.runtime_config_path)
        scenario_registry_hash = sha256_file(self.scenario_registry_path)
        runtime = RuntimeEnvironment(
            scenario_registry_hash=self._field(scenario_registry_hash, "file:scenario_registry:sha256"),
            runtime_config_hash=self._field(runtime_config_hash, "file:runtime_config:sha256"),
            traversal_contract=self._field(
                ValidationResult(FieldStatus.AVAILABLE, TRAVERSAL_CONTRACT_VERSION),
                "constant:traversal_contract",
            ),
            identity_contract=self._field(
                ValidationResult(FieldStatus.AVAILABLE, IDENTITY_CONTRACT_VERSION),
                "constant:identity_contract",
            ),
            feature_flags=self._collect_feature_flags(),
            collection_schema_versions=self._field(
                ValidationResult(FieldStatus.AVAILABLE, COLLECTION_SCHEMA_VERSIONS),
                "constants:collection_schema_versions",
            ),
        )
        return EnvironmentProfile(
            schema_version=ENVIRONMENT_PROFILE_SCHEMA_VERSION,
            captured_at=self.captured_at,
            device=device,
            android=android,
            talkback=self._collect_talkback(),
            target_app=PackageEnvironment(target_package, target_version, target_code),
            helper=self._collect_helper(),
            locale=self._collect_locale(),
            display=self._collect_display(),
            fold=self._collect_fold(),
            repository=self._collect_repository(),
            runtime=runtime,
        )


def environment_profile_path(output_path: str | Path) -> Path:
    return Path(output_path).with_suffix(".environment_profile.json")


def write_shared_environment_profile(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def environment_profile_reference(
    *,
    filename: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    digest = canonical_sha256(payload)
    fingerprint_value = payload.get("environment_fingerprint")
    fingerprint = (
        dict(fingerprint_value)
        if isinstance(fingerprint_value, Mapping)
        else build_environment_fingerprint(payload).to_dict()
    )
    return {
        "schema_version": ENVIRONMENT_PROFILE_SCHEMA_VERSION,
        "filename": filename,
        # Compatibility alias: sha256 has always represented the entire document.
        "sha256": digest,
        "document_digest": document_digest_reference(digest),
        "environment_fingerprint": fingerprint,
        "fingerprint_schema": fingerprint.get("fingerprint_schema"),
        "fingerprint_status": fingerprint.get("status"),
        "status_counts": profile_status_counts(dict(payload)),
    }


def capture_and_write_environment(
    *,
    output_path: str | Path,
    collector: EnvironmentCollector,
    serial_token_provider: SerialTokenProvider | None = None,
) -> EnvironmentCaptureResult:
    local_profile = collector.collect()
    shared_profile = redact_environment_profile(
        local_profile,
        serial_token_provider=serial_token_provider,
    )
    fingerprint = build_environment_fingerprint(shared_profile)
    shared_profile["environment_fingerprint"] = fingerprint.to_dict()
    target = environment_profile_path(output_path)
    write_shared_environment_profile(target, shared_profile)
    reference = environment_profile_reference(filename=target.name, payload=shared_profile)
    return EnvironmentCaptureResult(
        local_profile=local_profile,
        shared_profile=shared_profile,
        document_digest=str(reference["sha256"]),
        path=target,
        reference=reference,
    )


__all__ = [
    "COLLECTION_SCHEMA_VERSIONS",
    "EnvironmentCaptureResult",
    "EnvironmentCollector",
    "HELPER_PACKAGE",
    "IDENTITY_CONTRACT_VERSION",
    "ONE_UI_PROPERTIES",
    "TARGET_APP_PACKAGE",
    "capture_and_write_environment",
    "environment_profile_path",
    "environment_profile_reference",
    "sha256_file",
    "write_shared_environment_profile",
]
