from __future__ import annotations

import copy
import json

from tb_runner.device_classification_policy import (
    DEVICE_CLASSIFICATION_POLICY_SCHEMA_VERSION,
    classify_device,
    load_device_classification_policy,
)
from tb_runner.environment_fingerprint import FingerprintStatus, build_environment_fingerprint
from tb_runner.environment_collector import EnvironmentCollector
from tb_runner.environment_profile import FieldStatus
from tb_runner.environment_validator import ValidationResult
from tests.test_environment_profile import _fingerprint_ready_payload


def _write_policy(tmp_path, devices, *, revision=1, schema=DEVICE_CLASSIFICATION_POLICY_SCHEMA_VERSION):
    path = tmp_path / "device_classification_policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": schema, "revision": revision, "devices": devices}),
        encoding="utf-8",
    )
    return path


def _device(*, form_factor="foldable_phone", foldable=True, review_status="REVIEWED"):
    return {
        "device_family": "galaxy-z-flip6",
        "form_factor": form_factor,
        "expected_capabilities": {"foldable": foldable},
        "review": {
            "status": review_status,
            "reason": "reviewed test device",
            "reviewed_at": "2026-07-15",
        },
    }


def _available(value):
    return ValidationResult(FieldStatus.AVAILABLE, value)


def test_exact_reviewed_model_and_fold_capability_are_available(tmp_path):
    path = _write_policy(tmp_path, {"SM-F741N": _device()})

    result = classify_device(_available("SM-F741N"), _available(True), policy_path=path)

    assert result.device_family.status == FieldStatus.AVAILABLE
    assert result.device_family.value == "galaxy-z-flip6"
    assert result.form_factor.status == FieldStatus.AVAILABLE
    assert result.form_factor.value == "foldable_phone"
    assert "revision-1" in result.source
    assert "sha256-" in result.source
    assert str(path) not in result.source


def test_unknown_and_prefix_models_are_not_inferred(tmp_path):
    path = _write_policy(tmp_path, {"SM-F741N": _device()})
    for model in ("SM-F741", "SM-F741N-variant", "xSM-F741N"):
        result = classify_device(_available(model), _available(True), policy_path=path)
        assert result.device_family.status == FieldStatus.MISSING
        assert result.form_factor.status == FieldStatus.MISSING


def test_foldable_and_slab_capability_contradictions_are_invalid(tmp_path):
    foldable = _write_policy(tmp_path / "foldable", {"SM-F741N": _device()})
    slab = _write_policy(
        tmp_path / "slab",
        {"SM-SLAB": _device(form_factor="slab_phone", foldable=False)},
    )

    foldable_result = classify_device(_available("SM-F741N"), _available(False), policy_path=foldable)
    slab_result = classify_device(_available("SM-SLAB"), _available(True), policy_path=slab)

    assert foldable_result.form_factor.status == FieldStatus.INVALID
    assert slab_result.form_factor.status == FieldStatus.INVALID
    assert foldable_result.form_factor.reason == "policy_capability_contradiction"
    assert slab_result.form_factor.reason == "policy_capability_contradiction"


def test_missing_capability_does_not_infer_form_factor(tmp_path):
    path = _write_policy(tmp_path, {"SM-F741N": _device()})
    result = classify_device(
        _available("SM-F741N"),
        ValidationResult(FieldStatus.MISSING, reason="device_state_unsupported"),
        policy_path=path,
    )
    assert result.device_family.status == FieldStatus.AVAILABLE
    assert result.form_factor.status == FieldStatus.MISSING


def test_malformed_schema_unsupported_form_factor_and_unreviewed_entry_are_invalid(tmp_path):
    malformed = _write_policy(tmp_path / "schema", {"SM-F741N": _device()}, schema="unknown")
    unsupported = _write_policy(tmp_path / "form", {"SM-F741N": _device(form_factor="laptop", foldable=False)})
    unreviewed = _write_policy(tmp_path / "review", {"SM-F741N": _device(review_status="DRAFT")})

    for path in (malformed, unsupported, unreviewed):
        loaded = load_device_classification_policy(path)
        assert loaded.status == FieldStatus.INVALID
        result = classify_device(_available("SM-F741N"), _available(True), policy_path=path)
        assert result.device_family.status == FieldStatus.INVALID
        assert result.form_factor.status == FieldStatus.INVALID


def test_policy_revision_and_hash_are_provenance_not_fingerprint_identity(tmp_path):
    first_path = _write_policy(tmp_path / "one", {"SM-F741N": _device()}, revision=1)
    second_path = _write_policy(tmp_path / "two", {"SM-F741N": _device()}, revision=2)
    first = classify_device(_available("SM-F741N"), _available(True), policy_path=first_path)
    second = classify_device(_available("SM-F741N"), _available(True), policy_path=second_path)
    assert first.source != second.source

    profile = _fingerprint_ready_payload()
    changed_provenance = copy.deepcopy(profile)
    changed_provenance["device"]["device_family"].update(
        {"source": second.source, "reason": "policy revision updated"}
    )
    changed_provenance["device"]["form_factor"].update(
        {"source": second.source, "reason": "policy revision updated"}
    )
    assert build_environment_fingerprint(profile).hash == build_environment_fingerprint(changed_provenance).hash

    changed_classification = copy.deepcopy(profile)
    changed_classification["device"]["device_family"]["value"] = "different-reviewed-family"
    assert build_environment_fingerprint(profile).hash != build_environment_fingerprint(changed_classification).hash


def test_unknown_and_contradictory_classification_drive_fingerprint_status(tmp_path):
    path = _write_policy(tmp_path, {"SM-F741N": _device()})
    profile = _fingerprint_ready_payload()

    unknown = classify_device(_available("UNKNOWN"), _available(True), policy_path=path)
    unknown_profile = copy.deepcopy(profile)
    unknown_profile["device"]["device_family"].update(
        {"value": unknown.device_family.value, "status": unknown.device_family.status.value}
    )
    unknown_profile["device"]["form_factor"].update(
        {"value": unknown.form_factor.value, "status": unknown.form_factor.status.value}
    )
    assert build_environment_fingerprint(unknown_profile).status == FingerprintStatus.INCOMPLETE

    contradiction = classify_device(_available("SM-F741N"), _available(False), policy_path=path)
    invalid_profile = copy.deepcopy(profile)
    invalid_profile["device"]["form_factor"].update(
        {"value": contradiction.form_factor.value, "status": contradiction.form_factor.status.value}
    )
    assert build_environment_fingerprint(invalid_profile).status == FingerprintStatus.UNUSABLE


def test_duplicate_model_key_is_rejected_before_exact_lookup(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text(
        """{
          "schema_version":"talkback-device-classification-policy-v1",
          "revision":1,
          "devices":{"SM-F741N":{},"SM-F741N":{}}
        }""",
        encoding="utf-8",
    )
    assert load_device_classification_policy(path).status == FieldStatus.INVALID


def test_collector_records_policy_revision_hash_without_absolute_policy_path(tmp_path):
    policy = _write_policy(tmp_path, {"SM-F741N": _device()})
    outputs = {
        ("shell", "getprop", "ro.product.model"): "SM-F741N",
        ("shell", "cmd", "device_state", "print-state"): "3",
        ("shell", "cmd", "device_state", "print-states"): (
            "DeviceState{identifier=0, name='CLOSED'},\n"
            "DeviceState{identifier=3, name='OPENED'}"
        ),
    }

    def adb_runner(args, _timeout):
        return {"ok": True, "stdout": outputs.get(tuple(args), ""), "stderr": ""}

    collector = EnvironmentCollector(
        adb_runner=adb_runner,
        repo_root=tmp_path,
        serial="RAW-SERIAL-DOES-NOT-ENTER-POLICY-PROVENANCE",
        runtime_config_path=None,
        scenario_registry_path=None,
        device_classification_policy_path=policy,
        git_reader=lambda _args: None,
        captured_at="2026-07-15T00:00:00.000Z",
    )
    profile = collector.collect().to_dict()
    for name, expected in (("device_family", "galaxy-z-flip6"), ("form_factor", "foldable_phone")):
        field = profile["device"][name]
        assert field["status"] == "AVAILABLE"
        assert field["value"] == expected
        assert "revision-1" in field["source"]
        assert "sha256-" in field["source"]
        assert str(policy) not in field["source"]
        assert "RAW-SERIAL" not in field["source"]
