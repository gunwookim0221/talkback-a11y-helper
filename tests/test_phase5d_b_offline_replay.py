"""Read-only replay checks for preserved 5C captures when local artifacts exist."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from talkback_lib.hierarchy_identity import build_hierarchy_identity_metadata
from talkback_lib.logcat_reader import LogcatReader
from talkback_lib.node_reacquire import ReacquireStatus, reacquire_node
from talkback_lib.permit_model import PermitReason, PermitState, model_short_lived_permit


ROOT = Path(__file__).resolve().parents[1]
HOME_MONITOR_LOG = ROOT / "out/phase5c_nested_hit_owner_fix_20261014/full32/31_life_home_monitor_plugin/logcat.txt"
HOME_MONITOR_CAPTURES = ("dc1d4aae-37f", "7faeae9a-3b6")
HOME_MONITOR_TARGETS = {
    "service_card_body": "com.samsung.android.oneconnect:id/serviceCardBody",
    "monitor_card_body": "com.samsung.android.oneconnect:id/monitorCardBody",
    "monitor_header_group": "com.samsung.android.oneconnect:id/monitorHeaderGroup",
    "security_away": "com.samsung.android.oneconnect:id/shmBannerAwayButton",
    "security_stay": "com.samsung.android.oneconnect:id/shmBannerStayButton",
    "security_disarmed": "com.samsung.android.oneconnect:id/shmBannerDisarmedButton",
}

CROSS_SCENARIOS = {
    "air_care": ("out/phase5c_full32_resume_20261012/air_care_recovery_20261013_retry_03/full32/05_life_air_care_plugin/logcat.txt", "2fc98162-37d", "4bd6eb0e-ee1"),
    "home_care": ("out/phase5c_full32_resume_20261012/air_care_recovery_20261013_retry_03/full32/06_life_home_care_plugin/logcat.txt", "2ba3186a-592", "f937c72c-943"),
    "energy": ("out/phase5c_energy_audit_rca_20261013/live_retry_01/full32/07_life_energy_plugin/logcat.txt", "ade029d4-a08", "2d0488b6-bb5"),
    "family_care": ("out/phase5c_devices_ownership_fix_20261013/full32/26_life_family_care_plugin/logcat.txt", "5ee5cf2b-b22", "8fc9aa01-cec"),
    "find": ("out/phase5c_clothing_care_rca_20261014/full32/29_life_find_plugin/logcat.txt", "42860292-564", "b396bcae-c81"),
    "device_plugin": ("out/phase5c_devices_ownership_fix_20261013/full32/09_device_smoke_sensor_plugin/logcat.txt", "e39c64b2-46c", "f981098b-fbb"),
}


def _metadata(path: Path, request_id: str, capture_sequence: int):
    if not path.exists():
        pytest.skip(f"preserved offline artifact is not present: {path}")
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if f"DUMP_HIERARCHY_RESULT_CHUNK reqId={request_id} " in line]
    result = LogcatReader.reassemble_chunked_payload("\n".join(lines), "DUMP_HIERARCHY_RESULT", request_id, max_chunks=512, max_payload_bytes=1024 * 1024)
    if result.get("state") != "complete":
        pytest.skip(f"preserved hierarchy capture is incomplete: {request_id}")
    raw = json.loads(result["payload"])
    return build_hierarchy_identity_metadata(raw, capture_id=f"offline-test-{request_id}", capture_sequence=capture_sequence, captured_at="2026-10-15T00:00:00.000Z")


def _node_for_resource(metadata, resource_id):
    return next((node for node in metadata["nodes"] if node.get("semantic_identifiers", {}).get("resource_id", {}).get("value") == resource_id), None)


def test_preserved_scenario31_home_monitor_reacquires_all_declared_nodes_offline():
    authorized = _metadata(HOME_MONITOR_LOG, HOME_MONITOR_CAPTURES[0], 1)
    fresh = _metadata(HOME_MONITOR_LOG, HOME_MONITOR_CAPTURES[1], 2)
    outcomes = {}
    for name, resource_id in HOME_MONITOR_TARGETS.items():
        node = _node_for_resource(authorized, resource_id)
        assert node is not None, name
        result = reacquire_node(authorized, node["node_local_id"], fresh)
        assert result.status == ReacquireStatus.PROVEN, result.to_dict()
        assert result.trace["dispatch_performed"] is False
        outcomes[name] = result

    monitor = _node_for_resource(authorized, HOME_MONITOR_TARGETS["monitor_card_body"])
    result = outcomes["monitor_card_body"]
    action_status = monitor.get("action_metadata", {}).get("actions", {}).get("status")
    modeled = model_short_lived_permit(
        reacquire_result=result,
        authorized_node_identity=monitor,
        reacquired_node_identity=_node_for_resource(fresh, HOME_MONITOR_TARGETS["monitor_card_body"]),
        action_type="ACTION_CLICK",
        action_semantics="open_home_monitor",
        authorization_time="2026-10-15T00:00:00Z",
        reacquire_time="2026-10-15T00:00:00Z",
        permit_creation_time="2026-10-15T00:00:00Z",
        exactly_one_match=True,
        no_child_action_conflict=True,
        no_critical_semantic_mismatch=True,
        snapshot_package_window_valid=True,
        required_fields_sufficient=True,
        action_set_evidence_sufficient=action_status == "PRESENT",
    )
    assert action_status == "NOT_SUPPORTED_BY_SOURCE"
    assert modeled.state == PermitState.NOT_CREATED
    assert modeled.reason_code == PermitReason.INSUFFICIENT_REQUIRED_FIELDS


@pytest.mark.parametrize("scenario", sorted(CROSS_SCENARIOS))
def test_preserved_cross_scenario_pair_fails_closed_without_false_proof(scenario):
    relative, first_id, second_id = CROSS_SCENARIOS[scenario]
    path = ROOT / relative
    authorized = _metadata(path, first_id, 1)
    fresh = _metadata(path, second_id, 2)
    representative = next((
        node for node in authorized["nodes"]
        if node.get("semantic_identifiers", {}).get("package", {}).get("value") == "com.samsung.android.oneconnect"
        and node.get("semantic_identifiers", {}).get("resource_id", {}).get("value")
        and any(node.get("provenance", {}).get("fields", {}).get(flag, {}).get("value") is True for flag in ("focusable", "clickable", "accessibility_focused"))
    ), None)
    assert representative is not None, scenario
    result = reacquire_node(authorized, representative["node_local_id"], fresh)
    assert result.status in (ReacquireStatus.AMBIGUOUS, ReacquireStatus.REJECTED), result.to_dict()
    assert result.matched_node_id is None
    assert result.trace["dispatch_performed"] is False
    json.dumps(result.to_dict(), ensure_ascii=False)
