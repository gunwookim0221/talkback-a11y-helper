from __future__ import annotations

import hashlib

import pytest

from talkback_lib.exact_node_protocol import (
    HelperIdentityStatus,
    PROTOCOL_VERSION,
    _HELPER_BUILD_INPUTS,
    check_helper_compatibility,
    compute_repo_helper_build_identity,
    helper_compatibility_allows_execution,
)
from talkback_lib.helper_bridge import HelperBridge


GRADLE_VERSION = "9.0.0"
EXPECTED_COMMIT = "1" * 40
INSTALLED_COMMIT = "2" * 40
INPUT_DIGEST = "a" * 64
SERVICE_ID = "helper-service-instance"
_DEFAULT_CAPABILITIES = object()


def _build_id(commit: str, digest: str = INPUT_DIGEST) -> str:
    manifest = "\n".join((
        "schema=helper-build-manifest.v1",
        f"git_commit={commit}",
        f"input_digest={digest}",
        "source_state=CLEAN",
        "build_variant=debug",
        "version_name=1.0",
        "version_code=1",
        f"gradle_version={GRADLE_VERSION}",
    ))
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def _ping(*, commit: str = INSTALLED_COMMIT, digest: str = INPUT_DIGEST, **overrides):
    identity = {
        "schema_version": "1",
        "helper_protocol_version": PROTOCOL_VERSION,
        "versionName": "1.0",
        "versionCode": 1,
        "build_id": _build_id(commit, digest),
        "git_commit": commit,
        "helper_input_digest": digest,
        "source_state": "CLEAN",
        "build_variant": "debug",
        "metadata_provenance": "GENERATED_AT_BUILD",
    }
    identity.update(overrides)
    return {
        "reqId": "ping-request",
        "success": True,
        "status": "READY",
        "helper_service_instance_id": SERVICE_ID,
        "helper_build_identity": identity,
    }


def _capabilities(*, commit: str = INSTALLED_COMMIT, digest: str = INPUT_DIGEST, **overrides):
    response = {
        "schema": "hierarchy-transfer-control.v1",
        "protocol_version": "hierarchy-payload.v1",
        "request_id": None,
        "query_nonce": "b" * 32,
        "process_epoch": "process-epoch-1",
        "generation": 3,
        "service_instance_id": SERVICE_ID,
        "helper_build_identity": {
            "build_id": _build_id(commit, digest),
            "git_commit": commit,
            "input_digest": digest,
            "source_state": "CLEAN",
            "build_variant": "debug",
        },
        "payload_schema_version": "service-hierarchy-v2",
        "supported_payload_schema_versions": ["service-hierarchy-v2"],
        "candidate_schema_version": "legacy-traversal-candidates.v1",
        "supported_candidate_schema_versions": ["legacy-traversal-candidates.v1"],
        "candidate_contract_version": "legacy-traversal-candidate-contract.v1",
        "status": "OK",
        "completed": True,
        "capabilities": [
            "content_provider_pfd",
            "service_hierarchy_v2",
            "legacy-traversal-candidates.v1",
        ],
    }
    response.update(overrides)
    return response


def _check(ping=None, capabilities=_DEFAULT_CAPABILITIES, *, commit=EXPECTED_COMMIT, digest=INPUT_DIGEST, **kwargs):
    return check_helper_compatibility(
        commit,
        _ping() if ping is None else ping,
        expected_build_id=_build_id(commit, digest),
        expected_input_digest=digest,
        expected_gradle_version=GRADLE_VERSION,
        expected_version_name="1.0",
        expected_version_code=1,
        expected_variant="debug",
        capabilities=_capabilities() if capabilities is _DEFAULT_CAPABILITIES else capabilities,
        **kwargs,
    )


def test_exact_commit_and_inputs_with_required_schemas_is_exact_match():
    result = _check(ping=_ping(commit=EXPECTED_COMMIT), capabilities=_capabilities(commit=EXPECTED_COMMIT))

    assert result.status == HelperIdentityStatus.EXACT_MATCH
    assert result.reason == "EXACT_BUILD_PROVENANCE_MATCH"
    assert helper_compatibility_allows_execution(result)
    assert result.to_dict()["execution_allowed"] is True


def test_python_only_head_difference_with_same_helper_inputs_is_compatible():
    result = _check()

    assert result.status == HelperIdentityStatus.COMPATIBLE_SAME_HELPER_INPUT
    assert result.reason == "GIT_COMMIT_DIFFERENT_BUT_HELPER_INPUT_COMPATIBLE"
    assert result.helper_git_commit == INSTALLED_COMMIT
    assert helper_compatibility_allows_execution(result)
    assert result.to_dict()["execution_allowed"] is True
    assert result.to_dict()["expected_git_commit"] == EXPECTED_COMMIT
    assert result.to_dict()["required_schemas"]["raw_hierarchy_schema"] == "service-hierarchy-v2"


@pytest.mark.parametrize("generation", [0, 1, 7])
def test_prestart_capabilities_accepts_explicit_nonnegative_generation(generation):
    result = _check(capabilities=_capabilities(generation=generation))

    assert result.status == HelperIdentityStatus.COMPATIBLE_SAME_HELPER_INPUT
    assert helper_compatibility_allows_execution(result)


@pytest.mark.parametrize("generation_case", ["missing", None, -1, "invalid", True])
def test_prestart_capabilities_rejects_missing_or_invalid_generation(generation_case):
    capabilities = _capabilities()
    if generation_case == "missing":
        capabilities.pop("generation")
    else:
        capabilities["generation"] = generation_case

    result = _check(capabilities=capabilities)

    assert result.status == HelperIdentityStatus.UNKNOWN
    assert result.reason == "CAPABILITY_IDENTITY_INCONSISTENT"
    assert not helper_compatibility_allows_execution(result)


@pytest.mark.parametrize(
    "changed",
    [
        {"schema": "hierarchy-transfer-control.v0"},
        {"service_instance_id": "another-service"},
        {"process_epoch": ""},
        {"helper_build_identity": None},
    ],
)
def test_prestart_generation_zero_does_not_bypass_other_capability_identity_checks(changed):
    capabilities = _capabilities(generation=0, **changed)

    result = _check(capabilities=capabilities)

    assert result.status == HelperIdentityStatus.UNKNOWN
    assert not helper_compatibility_allows_execution(result)


def test_changed_helper_input_digest_requires_rebuild_even_if_schema_is_supported():
    old_digest = "f" * 64
    result = _check(
        ping=_ping(digest=old_digest),
        capabilities=_capabilities(digest=old_digest),
    )

    assert result.status == HelperIdentityStatus.REBUILD_REQUIRED
    assert result.reason == "HELPER_INPUT_DIGEST_MISMATCH"
    assert not helper_compatibility_allows_execution(result)


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"protocol_version": "hierarchy-payload.v0"}, "TRANSPORT_PROTOCOL_INCOMPATIBLE"),
        ({"payload_schema_version": "service-hierarchy-v1"}, "HIERARCHY_SCHEMA_OR_CAPABILITY_INCOMPATIBLE"),
        ({"candidate_schema_version": "legacy-traversal-candidates.v0"}, "HIERARCHY_SCHEMA_OR_CAPABILITY_INCOMPATIBLE"),
        ({"candidate_contract_version": "legacy-traversal-candidate-contract.v0"}, "HIERARCHY_SCHEMA_OR_CAPABILITY_INCOMPATIBLE"),
        ({"capabilities": ["content_provider_pfd"]}, "HIERARCHY_SCHEMA_OR_CAPABILITY_INCOMPATIBLE"),
    ],
)
def test_protocol_or_schema_incompatibility_is_a_hard_block(changed, reason):
    capabilities = _capabilities(**changed)
    result = _check(capabilities=capabilities)

    assert result.status == HelperIdentityStatus.PROTOCOL_INCOMPATIBLE
    assert result.reason == reason
    assert not helper_compatibility_allows_execution(result)


def test_old_pre_c2_helper_digest_is_rejected_as_rebuild_required():
    old_digest = "f" * 64
    old_ping = _ping(commit="5" * 40, digest=old_digest)

    result = _check(ping=old_ping, capabilities=None, capability_error="CAPABILITY_QUERY_FAILED:old_helper")

    assert result.status == HelperIdentityStatus.REBUILD_REQUIRED
    assert not helper_compatibility_allows_execution(result)


def test_matching_digest_without_schema_capability_evidence_is_unknown():
    result = _check(capabilities=None, capability_error="CAPABILITY_QUERY_FAILED:timeout")

    assert result.status == HelperIdentityStatus.UNKNOWN
    assert result.reason == "CAPABILITY_QUERY_FAILED:timeout"
    assert not helper_compatibility_allows_execution(result)


def test_same_git_commit_does_not_override_changed_helper_digest():
    changed_digest = "e" * 64
    result = _check(
        ping=_ping(commit=EXPECTED_COMMIT, digest=changed_digest),
        capabilities=_capabilities(commit=EXPECTED_COMMIT, digest=changed_digest),
    )

    assert result.status == HelperIdentityStatus.REBUILD_REQUIRED


@pytest.mark.parametrize(
    "mutation",
    [
        {"remove": "helper_input_digest"},
        {"set": ("helper_input_digest", "not-a-sha256")},
        {"set": ("metadata_provenance", "UNKNOWN")},
        {"set": ("schema_version", "future")},
    ],
)
def test_missing_or_malformed_identity_evidence_is_unknown(mutation):
    ping = _ping()
    identity = ping["helper_build_identity"]
    if "remove" in mutation:
        identity.pop(mutation["remove"])
    else:
        key, value = mutation["set"]
        identity[key] = value

    result = _check(ping=ping)

    assert result.status == HelperIdentityStatus.UNKNOWN
    assert not helper_compatibility_allows_execution(result)


def test_helper_control_protocol_mismatch_is_protocol_incompatible():
    result = _check(ping=_ping(helper_protocol_version="talkback.exact-navigation.v0"))

    assert result.status == HelperIdentityStatus.PROTOCOL_INCOMPATIBLE
    assert not helper_compatibility_allows_execution(result)


def test_build_id_must_remain_consistent_with_installed_commit_and_digest():
    ping = _ping()
    ping["helper_build_identity"]["build_id"] = "0" * 64
    capabilities = _capabilities()
    capabilities["helper_build_identity"]["build_id"] = "0" * 64

    result = _check(ping=ping, capabilities=capabilities)

    assert result.status == HelperIdentityStatus.UNKNOWN
    assert result.reason == "BUILD_ID_PROVENANCE_INCONSISTENT"


def test_capability_identity_must_match_ping_identity_and_service():
    capabilities = _capabilities(service_instance_id="another-service")

    result = _check(capabilities=capabilities)

    assert result.status == HelperIdentityStatus.UNKNOWN
    assert result.reason == "SERVICE_INSTANCE_IDENTITY_INCONSISTENT"


def test_compatibility_gate_rejects_conflicting_status_fields():
    assert not helper_compatibility_allows_execution({
        "status": "EXACT_MATCH",
        "compatibility_status": "REBUILD_REQUIRED",
        "execution_allowed": True,
    })


def test_boolean_generation_or_version_code_is_not_accepted_as_integer_evidence():
    ping = _ping()
    ping["helper_build_identity"]["versionCode"] = True
    result = _check(ping=ping)
    assert result.status == HelperIdentityStatus.UNKNOWN

    capabilities = _capabilities(generation=True)
    result = _check(capabilities=capabilities)
    assert result.status == HelperIdentityStatus.UNKNOWN


def test_helper_input_digest_scope_excludes_host_tests_docs_and_reports():
    expected = {
        "app/src/main",
        "app/build.gradle.kts",
        "build.gradle.kts",
        "settings.gradle.kts",
        "gradle.properties",
        "gradle/wrapper/gradle-wrapper.properties",
        "gradle/libs.versions.toml",
        "gradlew",
        "gradlew.bat",
    }

    assert set(_HELPER_BUILD_INPUTS) == expected
    assert not any(path.startswith(("talkback_lib", "tb_runner", "tests", "docs", "out")) for path in _HELPER_BUILD_INPUTS)


def test_bridge_performs_read_only_ping_then_correlated_schema_capability_check():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    expected = compute_repo_helper_build_identity(root)
    installed_commit = "f" * 40
    digest = expected["helper_input_digest"]
    ping = _ping(commit=installed_commit, digest=digest)
    cap = _capabilities(commit=installed_commit, digest=digest)
    observed = {"broadcasts": [], "capability_query": None}

    class FakeClient:
        def clear_logcat(self, dev=None):
            return None

        def _broadcast(self, dev, action, extras):
            observed["broadcasts"].append((action, list(extras)))
            observed["ping_req_id"] = extras[extras.index("--es") + 2]
            return "read-only-ping-dispatched"

        def _read_log_result(self, dev, prefix, req_id, wait_seconds):
            assert prefix == "PING_RESULT"
            assert req_id == observed["ping_req_id"]
            return {**ping, "reqId": req_id}

        def _hierarchy_transfer_control(self, dev, action, extras, *, request_id, remaining_seconds):
            observed["capability_query"] = (action, list(extras), request_id)
            query_nonce = extras[extras.index("--es") + 2]
            return {**cap, "query_nonce": query_nonce}

    bridge = HelperBridge(FakeClient())
    result = bridge.precheck_helper_build_identity(repo_root=root)

    assert result["status"] == "COMPATIBLE_SAME_HELPER_INPUT"
    assert result["execution_allowed"] is True
    assert result["expected_git_commit"] == expected["git_commit"]
    assert result["helper_git_commit"] == installed_commit
    assert result["helper_input_digest"] == digest
    assert result["capability_service_instance_id"] == SERVICE_ID
    assert result["required_schemas"]["candidate_contract"] == "legacy-traversal-candidate-contract.v1"
    assert observed["broadcasts"]
    assert observed["capability_query"][0] == "CAPABILITIES"
    assert observed["capability_query"][2] == ""
    query_extras = observed["capability_query"][1]
    assert query_extras[:2] == ["--es", "queryNonce"]
    assert len(query_extras[2]) == 32
