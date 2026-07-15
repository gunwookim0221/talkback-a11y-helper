from __future__ import annotations

import copy
import json
from pathlib import Path

from qa_frontend.backend.batch_runner import _environment_profile_reference_from_dir
from qa_frontend.backend.run_summary import extract_environment_profile_reference
from tb_runner.canonical_json import canonical_json, canonical_json_bytes, canonical_sha256
from tb_runner.environment_collector import (
    EnvironmentCollector,
    capture_and_write_environment,
    environment_profile_reference,
)
from tb_runner.environment_fingerprint import (
    ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION,
    FingerprintStatus,
    build_environment_fingerprint,
)
from tb_runner.environment_profile import (
    ENVIRONMENT_PROFILE_SCHEMA_VERSION,
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
)
from tb_runner.environment_redaction import redact_environment_profile
from tb_runner.environment_validator import (
    DisplayDensityMetadata,
    DisplaySizeMetadata,
    normalize_locale,
    parse_active_display,
    parse_display_density,
    parse_display_size,
    parse_fold_state,
    parse_one_ui_version,
    parse_package_metadata,
    select_active_talkback_package,
)
from tb_runner.evidence import collect_run_provenance


CAPTURED_AT = "2026-07-15T00:00:00.000Z"


def _field(value, status=FieldStatus.AVAILABLE, source="test", reason=""):
    return EnvironmentField(value, status, source, CAPTURED_AT, reason)


def _profile() -> EnvironmentProfile:
    package = PackageEnvironment(_field("pkg"), _field("1.0"), _field(1))
    return EnvironmentProfile(
        schema_version=ENVIRONMENT_PROFILE_SCHEMA_VERSION,
        captured_at=CAPTURED_AT,
        device=DeviceEnvironment(
            model=_field("SM-F741N"),
            serial=_field("SERIAL-123"),
            serial_token=_field(None, FieldStatus.MISSING),
            device_family=_field(None, FieldStatus.MISSING),
            form_factor=_field(None, FieldStatus.MISSING),
        ),
        android=AndroidEnvironment(
            release=_field("15"),
            sdk=_field(35),
            build_fingerprint=_field(
                "samsung/b6qksx/b6q:15/AP3A.240905.015.A2/F741NKSU2BYCA:user/release-keys"
            ),
            one_ui_version=_field("7.0"),
        ),
        talkback=package,
        target_app=package,
        helper=HelperEnvironment(_field("helper"), _field("1.0"), _field(1), _field("a" * 64)),
        locale=_field("en-US"),
        display=DisplayEnvironment(
            physical_size=_field({"width": 1080, "height": 2640}),
            logical_size=_field({"width": 1080, "height": 2640}),
            override_size=_field(None, FieldStatus.MISSING),
            density=_field(480),
            physical_density=_field(480),
            override_density=_field(None, FieldStatus.MISSING),
        ),
        fold=FoldEnvironment(_field(True), _field("OPENED"), _field(None, FieldStatus.MISSING)),
        repository=RepositoryEnvironment(_field("a" * 40), _field(False)),
        runtime=RuntimeEnvironment(
            scenario_registry_hash=_field("b" * 64),
            runtime_config_hash=_field("c" * 64),
            traversal_contract=_field("production-traversal-v2"),
            identity_contract=_field("target-relation-v2+canonical-observation-v1"),
            feature_flags=_field({"b": False, "a": True}),
            collection_schema_versions=_field({"evidence": "evidence-event-v1"}),
        ),
    )


def _fingerprint_ready_payload() -> dict:
    payload = redact_environment_profile(_profile(), serial_token_provider=_TokenProvider())
    payload["device"]["device_family"].update(
        {"value": "galaxy-z-flip6", "status": "AVAILABLE", "reason": ""}
    )
    payload["device"]["form_factor"].update(
        {"value": "foldable_phone", "status": "AVAILABLE", "reason": ""}
    )
    return payload


def _replace_capture_time(payload: dict, captured_at: str) -> None:
    payload["captured_at"] = captured_at

    def visit(value):
        if isinstance(value, dict):
            if "captured_at" in value:
                value["captured_at"] = captured_at
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)


def test_package_not_found_is_invalid():
    result = parse_package_metadata(
        "com.google.android.marvin.talkback",
        "Unable to find package: com.google.android.marvin.talkback",
    )
    assert result.status == FieldStatus.INVALID
    assert result.reason == "semantic_error_output"


def test_samsung_talkback_is_selected_from_active_service():
    result = select_active_talkback_package(
        "com.samsung.android.accessibility.talkback/"
        "com.samsung.android.marvin.talkback.TalkBackService:helper/.Service"
    )
    assert result.status == FieldStatus.AVAILABLE
    assert result.value == "com.samsung.android.accessibility.talkback"


def test_google_talkback_is_selected_from_active_service():
    result = select_active_talkback_package(
        "com.google.android.marvin.talkback/com.google.android.marvin.talkback.TalkBackService"
    )
    assert result.status == FieldStatus.AVAILABLE
    assert result.value == "com.google.android.marvin.talkback"


def test_package_version_requires_package_identity_and_both_versions():
    result = parse_package_metadata(
        "com.example.app",
        "Package [com.example.app]\n  versionCode=42 minSdk=30\n  versionName=2.4.1\n",
    )
    assert result.status == FieldStatus.AVAILABLE
    assert result.value.version_name == "2.4.1"
    assert result.value.version_code == 42


class _FakeAdb:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def __call__(self, args, timeout=8.0):
        self.calls.append(tuple(args))
        value = self.values.get(tuple(args), "")
        return {"ok": True, "stdout": value, "stderr": ""}


def test_one_ui_fallback_uses_next_semantically_valid_property(tmp_path):
    adb = _FakeAdb(
        {
            ("shell", "getprop", "ro.build.version.oneui"): "",
            ("shell", "getprop", "ro.build.version.oneui.version"): "60101",
        }
    )
    collector = EnvironmentCollector(
        adb_runner=adb,
        repo_root=tmp_path,
        serial="SERIAL",
        runtime_config_path=None,
        scenario_registry_path=None,
        captured_at=CAPTURED_AT,
        git_reader=lambda _args: None,
    )
    field = collector._collect_one_ui()
    assert field.status == FieldStatus.AVAILABLE
    assert field.value == "6.1.1"
    assert field.source.endswith("ro.build.version.oneui.version")
    assert len(adb.calls) == 2


def test_one_ui_missing_property_chain_is_missing(tmp_path):
    collector = EnvironmentCollector(
        adb_runner=_FakeAdb({}),
        repo_root=tmp_path,
        serial="SERIAL",
        runtime_config_path=None,
        scenario_registry_path=None,
        captured_at=CAPTURED_AT,
        git_reader=lambda _args: None,
    )
    field = collector._collect_one_ui()
    assert field.status == FieldStatus.MISSING
    assert field.value is None


def test_runtime_feature_flags_include_v10_config_flags(tmp_path):
    runtime_config = tmp_path / "runtime_config.json"
    runtime_config.write_text(
        json.dumps(
            {
                "v10": {
                    "feature_flags": {
                        "inventory_enabled": False,
                        "shadow_validation_enabled": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    collector = EnvironmentCollector(
        adb_runner=_FakeAdb({}),
        repo_root=tmp_path,
        serial="SERIAL",
        runtime_config_path=runtime_config,
        scenario_registry_path=None,
        feature_flags={"evidence_ledger": True},
        captured_at=CAPTURED_AT,
        git_reader=lambda _args: None,
    )

    field = collector._collect_feature_flags()

    assert field.status == FieldStatus.AVAILABLE
    assert field.value == {
        "evidence_ledger": True,
        "v10.inventory_enabled": False,
        "v10.shadow_validation_enabled": True,
    }


def test_one_ui_encoded_and_plain_versions_are_normalized():
    assert parse_one_ui_version("70000").value == "7.0"
    assert parse_one_ui_version("6.1").value == "6.1"


def test_invalid_locale_is_not_available():
    result = normalize_locale("not_a_valid_locale_value")
    assert result.status == FieldStatus.INVALID


def test_display_size_parser_separates_physical_logical_and_override():
    result = parse_display_size("Physical size: 1080x2640\nOverride size: 720x1760")
    assert result.status == FieldStatus.AVAILABLE
    assert result.value == DisplaySizeMetadata(
        physical={"width": 1080, "height": 2640},
        logical={"width": 720, "height": 1760},
        override={"width": 720, "height": 1760},
    )


def test_display_density_parser_separates_physical_logical_and_override():
    result = parse_display_density("Physical density: 480\nOverride density: 420")
    assert result.status == FieldStatus.AVAILABLE
    assert result.value == DisplayDensityMetadata(physical=480, logical=420, override=420)


def test_display_unparseable_is_invalid():
    assert parse_display_size("size unknown").status == FieldStatus.INVALID
    assert parse_display_density("density unknown").status == FieldStatus.INVALID


def test_fold_capability_and_posture_are_parsed_without_model_inference():
    result = parse_fold_state(
        "3",
        "Supported states: [\n"
        "DeviceState{identifier=0, name='CLOSED'},\n"
        "DeviceState{identifier=3, name='OPENED'}\n]",
    )
    assert result.status == FieldStatus.AVAILABLE
    assert result.value.capability is True
    assert result.value.posture == "OPENED"


def test_active_display_preserves_id_without_inferring_cover_or_main_role():
    result = parse_active_display(
        "Display: mDisplayId=1 (organized)\n"
        "  mCurrentFocus=Window{abc u0 Cover}\n"
        "  mFocusedApp=ActivityRecord{abc u0 com.android.systemui/.subscreen.SubHomeActivity t7}\n"
        "Display: mDisplayId=0\n"
        "  mCurrentFocus=null\n"
        "  mFocusedApp=null\n"
    )
    assert result.status == FieldStatus.AVAILABLE
    assert result.value == {
        "display_id": 1,
        "focused_package": "com.android.systemui",
        "role": "UNKNOWN",
    }


def test_canonical_hash_is_deterministic_and_order_independent():
    left = {"b": ["e\u0301", 2], "a": {"z": True, "x": None}}
    right = {"a": {"x": None, "z": True}, "b": ["é", 2]}
    assert canonical_json(left) == canonical_json(right)
    assert canonical_sha256(left) == canonical_sha256(right)


class _TokenProvider:
    def token_for(self, serial: str) -> str | None:
        return f"token:{serial[-3:]}"


def test_capture_time_changes_document_digest_but_not_fingerprint():
    first = _fingerprint_ready_payload()
    second = copy.deepcopy(first)
    _replace_capture_time(second, "2026-07-15T00:00:01.000Z")

    first_fingerprint = build_environment_fingerprint(first)
    second_fingerprint = build_environment_fingerprint(second)

    assert canonical_sha256(first) != canonical_sha256(second)
    assert first_fingerprint.status == FingerprintStatus.COMPLETE
    assert first_fingerprint.hash == second_fingerprint.hash


def test_direct_field_change_changes_fingerprint():
    first = _fingerprint_ready_payload()
    second = copy.deepcopy(first)
    second["target_app"]["package"]["value"] = "com.example.other"

    assert build_environment_fingerprint(first).hash != build_environment_fingerprint(second).hash


def test_family_field_change_changes_fingerprint():
    first = _fingerprint_ready_payload()
    second = copy.deepcopy(first)
    second["android"]["release"]["value"] = "16"

    assert build_environment_fingerprint(first).hash != build_environment_fingerprint(second).hash


def test_profile_json_formatting_does_not_change_fingerprint():
    payload = _fingerprint_ready_payload()
    pretty_round_trip = json.loads(json.dumps(payload, ensure_ascii=False, indent=4))

    assert build_environment_fingerprint(payload).hash == build_environment_fingerprint(
        pretty_round_trip
    ).hash


def test_invalid_critical_field_makes_fingerprint_unusable():
    payload = _fingerprint_ready_payload()
    payload["target_app"]["package"].update(
        {"value": None, "status": "INVALID", "reason": "package_not_found"}
    )

    fingerprint = build_environment_fingerprint(payload)

    assert fingerprint.status == FingerprintStatus.UNUSABLE
    assert fingerprint.hash is None
    assert fingerprint.invalid_fields == ("target_app_package",)


def test_missing_critical_field_makes_fingerprint_incomplete():
    payload = _fingerprint_ready_payload()
    payload["device"]["device_family"].update(
        {"value": None, "status": "MISSING", "reason": "mapping_unavailable"}
    )

    fingerprint = build_environment_fingerprint(payload)

    assert fingerprint.status == FingerprintStatus.INCOMPLETE
    assert fingerprint.hash is None
    assert fingerprint.missing_fields == ("device_family",)


def test_fingerprint_source_serialization_is_deterministic_and_excludes_provenance():
    payload = _fingerprint_ready_payload()
    fingerprint = build_environment_fingerprint(payload)
    source = fingerprint.fingerprint_source.to_dict()

    assert source["fingerprint_schema"] == ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION
    assert canonical_sha256(source) == fingerprint.hash
    serialized = canonical_json(source)
    for excluded in ("captured_at", "source", "reason", "serial", "status_counts"):
        assert f'"{excluded}"' not in serialized


def test_redaction_removes_raw_serial_and_incremental_fingerprint():
    local = _profile()
    shared = redact_environment_profile(local, serial_token_provider=_TokenProvider())
    assert local.device.serial.value == "SERIAL-123"
    assert shared["device"]["serial"]["status"] == "REDACTED"
    assert shared["device"]["serial"]["value"] is None
    assert shared["device"]["serial_token"]["value"] == "token:123"
    fingerprint = shared["android"]["build_fingerprint"]
    assert fingerprint["status"] == "REDACTED"
    assert fingerprint["value"]["release"] == "15"
    assert "F741NKSU2BYCA" not in json.dumps(fingerprint)


def test_schema_serialization_keeps_status_source_and_capture_time():
    profile = _profile()
    payload = json.loads(profile.to_canonical_json())
    assert payload["schema_version"] == ENVIRONMENT_PROFILE_SCHEMA_VERSION
    assert payload["device"]["model"] == {
        "captured_at": CAPTURED_AT,
        "reason": "",
        "source": "test",
        "status": "AVAILABLE",
        "value": "SM-F741N",
    }


def test_environment_reference_hashes_canonical_shared_profile():
    payload = redact_environment_profile(_profile(), serial_token_provider=_TokenProvider())
    reference = environment_profile_reference(filename="run.environment_profile.json", payload=payload)
    assert reference["schema_version"] == ENVIRONMENT_PROFILE_SCHEMA_VERSION
    assert reference["sha256"] == canonical_sha256(payload)
    assert reference["document_digest"]["value"] == reference["sha256"]
    assert reference["fingerprint_status"] == "INCOMPLETE"
    assert reference["environment_fingerprint"]["hash"] is None
    assert reference["status_counts"]["REDACTED"] == 2


def test_capture_embeds_fingerprint_before_calculating_document_digest(tmp_path):
    class _StaticCollector:
        def collect(self):
            return _profile()

    result = capture_and_write_environment(
        output_path=tmp_path / "run.xlsx",
        collector=_StaticCollector(),
        serial_token_provider=_TokenProvider(),
    )
    payload = json.loads(result.path.read_text(encoding="utf-8"))

    assert payload["environment_fingerprint"]["status"] == "INCOMPLETE"
    assert result.document_digest == canonical_sha256(payload)
    assert result.environment_hash == result.document_digest
    assert result.reference["sha256"] == result.document_digest
    assert result.reference["document_digest"]["value"] == result.document_digest


def test_run_summary_environment_reference_marker_is_additive():
    digest = "a" * 64
    reference = extract_environment_profile_reference(
        "[12:00:00] [ENVIRONMENT] profile filename='run.environment_profile.json' "
        f"schema='{ENVIRONMENT_PROFILE_SCHEMA_VERSION}' sha256='{digest}' status_counts='{{}}'"
    )
    assert reference == {
        "filename": "run.environment_profile.json",
        "schema_version": ENVIRONMENT_PROFILE_SCHEMA_VERSION,
        "sha256": digest,
    }


def test_run_summary_extracts_document_digest_and_fingerprint():
    document_digest = "a" * 64
    fingerprint_digest = "b" * 64
    reference = extract_environment_profile_reference(
        "[ENVIRONMENT] profile filename='run.environment_profile.json' "
        f"schema='{ENVIRONMENT_PROFILE_SCHEMA_VERSION}' sha256='{document_digest}' "
        f"document_digest='{document_digest}' "
        f"fingerprint_schema='{ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION}' "
        "fingerprint_status='COMPLETE' "
        f"fingerprint_sha256='{fingerprint_digest}' status_counts='{{}}'"
    )

    assert reference["document_digest"]["value"] == document_digest
    assert reference["fingerprint_status"] == "COMPLETE"
    assert reference["environment_fingerprint"]["hash"] == fingerprint_digest


def test_evidence_manifest_provenance_adds_environment_reference(tmp_path):
    runner = tmp_path / "runner.py"
    runtime_config = tmp_path / "runtime_config.json"
    scenario_registry = tmp_path / "scenario.py"
    runner.write_text("print('runner')\n", encoding="utf-8")
    runtime_config.write_text("{}\n", encoding="utf-8")
    scenario_registry.write_text("SCENARIOS = []\n", encoding="utf-8")
    reference = {
        "filename": "run.environment_profile.json",
        "schema_version": ENVIRONMENT_PROFILE_SCHEMA_VERSION,
        "sha256": "d" * 64,
        "document_digest": {"algorithm": "SHA-256", "scope": "test", "value": "d" * 64},
        "environment_fingerprint": {
            "fingerprint_schema": ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION,
            "status": "COMPLETE",
            "hash": "e" * 64,
            "fingerprint_source": {"direct": {}, "family": {}},
        },
    }
    manifest = collect_run_provenance(
        repo_root=tmp_path,
        runtime_config_path=str(runtime_config),
        scenario_registry_path=scenario_registry,
        runner_path=runner,
        environment_profile_reference=reference,
    )
    assert manifest["environment_profile"] == reference
    assert "repository_commit_sha" in manifest


def test_batch_summary_reference_discovers_one_canonical_profile(tmp_path):
    payload = redact_environment_profile(_profile(), serial_token_provider=_TokenProvider())
    path = tmp_path / "run.environment_profile.json"
    path.write_bytes(canonical_json_bytes(payload))
    reference = _environment_profile_reference_from_dir(tmp_path)
    assert reference is not None
    assert reference["filename"] == path.name
    assert reference["schema_version"] == ENVIRONMENT_PROFILE_SCHEMA_VERSION
    assert reference["sha256"] == canonical_sha256(payload)
    assert reference["document_digest"]["value"] == reference["sha256"]
    assert reference["fingerprint_status"] == "INCOMPLETE"
