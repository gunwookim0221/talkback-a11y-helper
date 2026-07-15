from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tb_runner.baseline_artifact_store import ContentAddressedArtifactStore, sha256_file
from tb_runner.baseline_candidate_builder import build_baseline_candidate
from tb_runner.baseline_repository import (
    ApprovalRequest,
    ArtifactPinPolicy,
    BaselineRepository,
    BaselineRepositoryError,
)
from tb_runner.baseline_repository_validator import offline_revalidate_candidate
from tb_runner.baseline_cli import main as baseline_cli_main
from tb_runner.canonical_json import canonical_json_bytes
from tb_runner.environment_fingerprint import build_environment_fingerprint
from tests.test_baseline_candidate_builder import CAPTURED_AT, _create_run, _write_json


ACTOR = {"identity": "qa.reviewer", "authentication_source": "local-test"}
APPROVED_AT = "2026-07-15T12:00:00.000Z"


def _candidate(tmp_path: Path, **run_options):
    run_root = _create_run(tmp_path, **run_options)
    result = build_baseline_candidate(
        run_root, write=True, integrate=False, created_at=CAPTURED_AT
    )
    assert result.path is not None
    return run_root, result


def _repository(tmp_path: Path, name="baselines", *, clock=APPROVED_AT):
    return BaselineRepository(
        tmp_path / name,
        artifact_root=tmp_path / f".{name}-artifacts",
        clock=lambda: clock,
    )


def _request(result, **overrides):
    values = {
        "candidate_path": result.path,
        "candidate_digest": result.document_digest,
        "reviewer": ACTOR,
        "reason": "reviewed full-run baseline",
        "acceptance_result": "PASS",
    }
    values.update(overrides)
    return ApprovalRequest(**values)


def _second_candidate(tmp_path: Path, *, incompatible=False):
    run_root = _create_run(tmp_path)
    evidence_path = run_root / "talkback_compare.evidence_manifest.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["run_id"] = "run_evidence_replacement"
    _write_json(evidence_path, evidence)
    if incompatible:
        environment_path = run_root / "talkback_compare.environment_profile.json"
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        environment["device"]["device_family"]["value"] = "another-reviewed-family"
        environment["environment_fingerprint"] = build_environment_fingerprint(environment).to_dict()
        _write_json(environment_path, environment)
    result = build_baseline_candidate(
        run_root, write=True, integrate=False, created_at="2026-07-16T00:00:00.000Z"
    )
    return run_root, result


def _reviewed_limitation():
    return {
        "issue_id": "TB-KI-TEST-1",
        "revision": 1,
        "owner": "accessibility-team",
        "scenario_id": "menu_main",
        "environment_scope": {"locale": "en-US", "app_release_train": "1.8.47.24"},
        "match_signature": {"mismatch_type": "EMPTY_VISIBLE", "node_signature": "stable-1"},
        "review_at": "2026-10-15T00:00:00Z",
        "evidence_references": ["qa-run://batch_test/device/evidence"],
    }


def test_eligible_candidate_approval_materializes_core_catalog_and_index(tmp_path):
    _, candidate = _candidate(tmp_path / "run")
    repository = _repository(tmp_path)

    approved = repository.approve(_request(candidate))

    assert approved.baseline_id.endswith("_r0001")
    assert {path.name for path in approved.package_path.iterdir()} == {
        "baseline.json",
        "environment_profile.json",
        "artifact_manifest.json",
    }
    baseline = json.loads((approved.package_path / "baseline.json").read_text(encoding="utf-8"))
    manifest = json.loads((approved.package_path / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert baseline["lifecycle"]["state"] == "APPROVED"
    assert baseline["source_candidate_id"] == candidate.candidate.candidate_id
    assert baseline["environment_fingerprint"]["status"] == "COMPLETE"
    assert all(item["pinned_reference"].startswith("artifact://sha256/") for item in manifest["artifacts"] if item["required"])
    assert repository.catalog_path.is_file()
    assert (approved.package_path.parent / "index.json").is_file()
    assert repository.verify().valid is True


@pytest.mark.parametrize("mutation,expected", [
    ("not_eligible", "candidate_validator"),
    ("dirty", "candidate_validator"),
])
def test_not_eligible_and_dirty_candidate_are_blocked(tmp_path, mutation, expected):
    run_root = _create_run(tmp_path / "run", complete_environment=mutation != "not_eligible")
    if mutation == "dirty":
        path = run_root / "talkback_compare.environment_profile.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        profile["repository"]["dirty"]["value"] = True
        _write_json(path, profile)
    candidate = build_baseline_candidate(run_root, write=True, integrate=False)
    repository = _repository(tmp_path)

    with pytest.raises(BaselineRepositoryError, match="validation failed"):
        repository.approve(_request(candidate))

    assert expected in repository.lifecycle_path.read_text(encoding="utf-8")


def test_missing_required_artifact_and_checksum_mismatch_are_blocked(tmp_path):
    run_root, candidate = _candidate(tmp_path / "run")
    repository = _repository(tmp_path)
    (run_root / "talkback_compare.profiler.zip").unlink()
    with pytest.raises(BaselineRepositoryError, match="required_artifact:profiler_archive"):
        repository.approve(_request(candidate))

    _, other = _candidate(tmp_path / "other")
    with pytest.raises(BaselineRepositoryError, match="candidate_document_digest"):
        repository.approve(_request(other, candidate_digest="0" * 64))


def test_incomplete_and_complete_pass_with_limitations(tmp_path):
    run_root = _create_run(tmp_path / "run")
    summary_path = run_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["scenario_result_status"] = "warning"
    summary["quality_issues"] = [
        {"mismatch_type": "EMPTY_VISIBLE", "scenario_id": "menu_main", "final_result": "FAIL"}
    ]
    _write_json(summary_path, summary)
    candidate = build_baseline_candidate(run_root, write=True, integrate=False)
    repository = _repository(tmp_path)

    with pytest.raises(BaselineRepositoryError, match="limitation"):
        repository.approve(
            _request(
                candidate,
                acceptance_result="PASS WITH LIMITATIONS",
                structured_limitations=({"owner": "team"},),
                limitations_explicitly_accepted=True,
            )
        )

    reviewed = _reviewed_limitation()
    approved = repository.approve(
        _request(
            candidate,
            acceptance_result="PASS WITH LIMITATIONS",
            structured_limitations=(reviewed,),
            known_limitation_snapshot=(reviewed,),
            limitations_explicitly_accepted=True,
        )
    )
    baseline = json.loads((approved.package_path / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["acceptance_result"] == "PASS WITH LIMITATIONS"
    assert baseline["candidate_limitations"][0]["raw_result"] == "FAIL"
    assert baseline["known_limitation_snapshot"][0]["issue_id"] == "TB-KI-TEST-1"


def test_approved_package_modification_and_duplicate_approval_are_detected(tmp_path):
    _, candidate = _candidate(tmp_path / "run")
    repository = _repository(tmp_path)
    approved = repository.approve(_request(candidate))

    with pytest.raises(BaselineRepositoryError, match="already approved"):
        repository.approve(_request(candidate))

    baseline_path = approved.package_path / "baseline.json"
    baseline_path.write_bytes(baseline_path.read_bytes() + b" ")
    verification = repository.verify()
    assert verification.valid is False
    assert any("core_checksum_mismatch" in error for error in verification.errors)


def test_reject_archive_and_lifecycle_hash_chain(tmp_path):
    _, candidate = _candidate(tmp_path / "candidate", complete_environment=False)
    repository = _repository(tmp_path)
    rejected = repository.reject(
        candidate.path,
        reviewer=ACTOR,
        reason="environment incomplete",
        category="INCOMPLETE_ENVIRONMENT",
        candidate_digest=candidate.document_digest,
    )
    archived = repository.archive(
        candidate.candidate.candidate_id,
        actor=ACTOR,
        reason="retention completed",
    )
    assert rejected["event_type"] == "REJECTED"
    assert archived["event_type"] == "ARCHIVED"
    assert repository.verify().valid is True

    lines = repository.lifecycle_path.read_text(encoding="utf-8").splitlines()
    second = json.loads(lines[1])
    first = json.loads(lines[0])
    assert second["previous_event_hash"] == first["event_hash"]


def test_supersede_keeps_one_active_and_archive_never_deletes_package(tmp_path):
    _, first_candidate = _candidate(tmp_path / "first")
    repository = _repository(tmp_path)
    first = repository.approve(_request(first_candidate))
    _, second_candidate = _second_candidate(tmp_path / "second")

    with pytest.raises(BaselineRepositoryError, match="explicitly superseded"):
        repository.approve(_request(second_candidate))
    second = repository.approve(_request(second_candidate, supersedes=first.baseline_id))

    active = repository.list_baselines(include_inactive=False)
    assert [item["baseline_id"] for item in active] == [second.baseline_id]
    first_state = repository.inspect_baseline(first.baseline_id)
    assert first_state["repository_state"] == "SUPERSEDED"
    assert first_state["superseded_by"] == second.baseline_id
    repository.archive(first.baseline_id, actor=ACTOR, reason="old revision retention")
    assert first.package_path.is_dir()
    assert repository.inspect_baseline(first.baseline_id)["repository_state"] == "ARCHIVED"


def test_incompatible_supersede_is_blocked(tmp_path):
    _, first_candidate = _candidate(tmp_path / "first")
    repository = _repository(tmp_path)
    first = repository.approve(_request(first_candidate))
    _, incompatible = _second_candidate(tmp_path / "other", incompatible=True)
    with pytest.raises(BaselineRepositoryError, match="not active APPROVED|incompatible"):
        repository.approve(_request(incompatible, supersedes=first.baseline_id))


def test_catalog_corruption_rebuild_and_missing_package_detection(tmp_path):
    _, candidate = _candidate(tmp_path / "run")
    repository = _repository(tmp_path)
    approved = repository.approve(_request(candidate))
    repository.catalog_path.write_text("{broken", encoding="utf-8")
    assert repository.verify().valid is False

    rebuilt = repository.rebuild_indexes()
    assert rebuilt["active_baselines"][approved.baseline_key_digest] == approved.baseline_id
    assert repository.verify().valid is True

    shutil.rmtree(approved.package_path)
    verification = repository.verify()
    assert any(error == f"package_missing:{approved.baseline_id}" for error in verification.errors)


def test_artifact_store_checksum_deduplication_and_atomic_layout(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"artifact-payload")
    digest = sha256_file(source)
    store = ContentAddressedArtifactStore(tmp_path / "store", clock=lambda: APPROVED_AT)

    first = store.pin(
        source,
        digest,
        media_type="application/octet-stream",
        schema_version=None,
        contains_sensitive_data=False,
        retention_class="TEST",
    )
    second = store.pin(
        source,
        digest,
        media_type="application/octet-stream",
        schema_version=None,
        contains_sensitive_data=False,
        retention_class="TEST",
    )
    assert first.reference == second.reference
    assert second.deduplicated is True
    assert first.payload_path.read_bytes() == b"artifact-payload"
    assert not list(first.payload_path.parent.parent.glob(".*.tmp-*"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        store.pin(
            source,
            "0" * 64,
            media_type="application/octet-stream",
            schema_version=None,
            contains_sensitive_data=False,
            retention_class="TEST",
        )


def test_required_pin_failure_blocks_and_optional_pin_failure_warns(tmp_path, monkeypatch):
    _, candidate = _candidate(tmp_path / "required")
    repository = _repository(tmp_path / "required-repository")
    monkeypatch.setattr(repository.artifacts, "pin", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(BaselineRepositoryError, match="required artifact pin failed"):
        repository.approve(_request(candidate))
    assert not repository._packages()

    run_root, optional_candidate = _candidate(tmp_path / "optional")
    repository = _repository(tmp_path / "optional-repository")
    original_pin = repository.artifacts.pin

    def fail_runtime(source, *args, **kwargs):
        if Path(source).name == "runtime_config.json":
            raise OSError("optional pin failed")
        return original_pin(source, *args, **kwargs)

    monkeypatch.setattr(repository.artifacts, "pin", fail_runtime)
    approved = repository.approve(
        _request(
            optional_candidate,
            artifact_pin_policy=ArtifactPinPolicy(optional_artifact_types=("runtime_config",)),
        )
    )
    assert approved.warnings == ("optional_artifact_pin_failed:runtime_config",)


def test_privacy_determinism_and_timestamp_independent_key(tmp_path):
    _, candidate = _candidate(tmp_path / "run")
    first_repo = _repository(tmp_path / "one", clock="2026-07-15T12:00:00.000Z")
    second_repo = _repository(tmp_path / "two", clock="2026-07-15T12:00:00.000Z")
    first = first_repo.approve(_request(candidate))
    second = second_repo.approve(_request(candidate))
    assert first.baseline_key_digest == second.baseline_key_digest
    for filename in ("baseline.json", "environment_profile.json", "artifact_manifest.json"):
        assert (first.package_path / filename).read_bytes() == (second.package_path / filename).read_bytes()
    joined = b"".join((first.package_path / name).read_bytes() for name in ("baseline.json", "environment_profile.json", "artifact_manifest.json"))
    assert str(candidate.path.parent).encode() not in joined
    assert b"device_safe" not in joined

    later_repo = _repository(tmp_path / "later", clock="2026-07-20T12:00:00.000Z")
    later = later_repo.approve(_request(candidate))
    assert later.baseline_key_digest == first.baseline_key_digest


def test_offline_validation_detects_environment_and_artifact_tamper(tmp_path):
    run_root, candidate = _candidate(tmp_path / "run")
    environment = run_root / "talkback_compare.environment_profile.json"
    environment.write_bytes(environment.read_bytes() + b" ")
    result = offline_revalidate_candidate(candidate.path, expected_candidate_digest=candidate.document_digest)
    assert result.valid is False
    assert "environment_document_digest" in result.failures


def test_broad_wildcard_limitation_is_blocked(tmp_path):
    run_root = _create_run(tmp_path / "run")
    summary_path = run_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["scenario_result_status"] = "warning"
    summary["quality_issues"] = [
        {"mismatch_type": "EMPTY_VISIBLE", "scenario_id": "menu_main", "final_result": "FAIL"}
    ]
    _write_json(summary_path, summary)
    candidate = build_baseline_candidate(run_root, write=True, integrate=False)
    limitation = _reviewed_limitation()
    limitation["environment_scope"] = {"locale": "*"}
    repository = _repository(tmp_path)
    with pytest.raises(BaselineRepositoryError, match="broad_wildcard"):
        repository.approve(
            _request(
                candidate,
                acceptance_result="PASS WITH LIMITATIONS",
                structured_limitations=(limitation,),
                known_limitation_snapshot=(limitation,),
                limitations_explicitly_accepted=True,
            )
        )


def test_raw_serial_is_never_materialized(tmp_path):
    run_root = _create_run(tmp_path / "run")
    environment_path = run_root / "talkback_compare.environment_profile.json"
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    environment["device"]["serial"] = {
        "value": "R3CX40QFDBP",
        "status": "AVAILABLE",
        "source": "test",
        "captured_at": CAPTURED_AT,
        "reason": "",
    }
    environment["environment_fingerprint"] = build_environment_fingerprint(environment).to_dict()
    _write_json(environment_path, environment)
    candidate = build_baseline_candidate(run_root, write=True, integrate=False)
    repository = _repository(tmp_path)
    with pytest.raises(BaselineRepositoryError, match="raw serial"):
        repository.approve(_request(candidate))
    assert not repository._packages()


def test_lifecycle_tamper_is_detected_and_validate_cli_is_read_only(tmp_path, capsys):
    _, candidate = _candidate(tmp_path / "run")
    assert baseline_cli_main(
        ["validate-candidate", str(candidate.path), "--digest", candidate.document_digest]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True

    repository = _repository(tmp_path)
    repository.approve(_request(candidate))
    events = repository.lifecycle_path.read_text(encoding="utf-8")
    repository.lifecycle_path.write_text(events.replace("reviewed full-run baseline", "tampered"), encoding="utf-8")
    verification = repository.verify()
    assert verification.valid is False
    assert "lifecycle event hash mismatch" in verification.errors[0]


def test_semantic_lifecycle_cycle_and_missing_pinned_artifact_are_detected(tmp_path):
    _, first_candidate = _candidate(tmp_path / "first")
    repository = _repository(tmp_path)
    first = repository.approve(_request(first_candidate))
    _, second_candidate = _second_candidate(tmp_path / "second")
    second = repository.approve(_request(second_candidate, supersedes=first.baseline_id))

    repository._append_event(
        "SUPERSEDED",
        baseline_id=second.baseline_id,
        actor=ACTOR,
        reason="semantic corruption fixture",
        superseded_by=first.baseline_id,
    )
    cycle_verification = repository.verify()
    assert any("lifecycle_relation_cycle" in error for error in cycle_verification.errors)

    manifest = json.loads((second.package_path / "artifact_manifest.json").read_text(encoding="utf-8"))
    required = next(item for item in manifest["artifacts"] if item["required"])
    digest = required["content_digest"]["value"]
    repository.artifacts.location(digest).joinpath("payload").unlink()
    artifact_verification = repository.verify()
    assert any("pinned_artifact_missing" in error for error in artifact_verification.errors)
