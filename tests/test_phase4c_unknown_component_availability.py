"""Phase 4C stays unavailable when the capture has no trusted component evidence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from phase6d_capture_support import attach_capture_authority
from tb_runner.dynamic_context import DestinationOwnership
from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
from tb_runner.plugin_context_contract import plugin_context_evidence
from tb_runner.scenario_config import TAB_CONFIGS


def hierarchy_capture():
    scenario = "device_tv_plugin"
    config = next(row for row in TAB_CONFIGS if row["scenario_id"] == scenario)
    raw = {
        "scenario_id": scenario, "scenario_run_id": "phase4c-unknown-run",
        "navigation_epoch": "phase4c-entry-epoch",
        "timestamp": "2026-10-25T00:00:01+00:00",
        "package_name": "com.samsung.android.oneconnect", "activity_name": None,
        "context_source": "capture_local_hierarchy_only", "overlay": {"observed": None},
        "capture_root_bounds": [0, 0, 1000, 1000],
        "nodes": [{"text": "TV", "viewIdResourceName": "pkg.plugin:id/body",
                   "visibleToUser": True}],
    }
    entry = phase3_entry_evidence_from_main_loop(SimpleNamespace(
        tab_cfg=config, rows=[{"actual_focus_accessibility_focused": True,
                              "actual_focus_payload_source": "verified_pre_loop_anchor"}]),
        raw["scenario_run_id"], raw["timestamp"])
    raw["phase3_entry_evidence"] = entry
    attach_capture_authority(raw, sequence=700, request_id="phase4c-unknown-request-700")
    raw["phase3_plugin_context_evidence"] = plugin_context_evidence(
        entry, raw, {"open_completed": True, "entry_contract_reason": "success_verified",
                    "entry_contract_detail": "plugin_open_verified"}, raw["navigation_epoch"])
    return raw


def test_capture_bound_helper_entry_evidence_does_not_invent_component_or_owner():
    raw = hierarchy_capture()
    context = resolve_phase3_context(raw)
    proof = raw["phase3_plugin_context_evidence"]
    assert proof["proof_capture_id"] == raw["capture_authority"]["capture_key"]
    assert proof["capture_authority"]["capture_key"] == raw["capture_id"]
    assert context["status"] == "UNRESOLVED_CONTEXT"
    assert context["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]
    before = deepcopy(raw)
    with pytest.raises(ValueError, match="Trusted normal plugin entry required"):
        DestinationOwnership(raw)
    assert raw == before
    assert "destination_ownership" not in raw


@pytest.mark.parametrize("diagnostic", [
    {"activity_name": "com.samsung.android.oneconnect.plugin.MainActivity"},
    {"activity_name": "other.package.OtherActivity",
     "window_evidence": {"diagnostic_focused_package": "other.package",
                         "diagnostic_focused_activity": "OtherActivity"}},
])
def test_activity_and_window_diagnostics_cannot_promote_component_unknown(diagnostic):
    raw = hierarchy_capture()
    raw.update(diagnostic)
    assert resolve_phase3_context(raw)["status"] == "UNRESOLVED_CONTEXT"
    with pytest.raises(ValueError, match="Trusted normal plugin entry required"):
        DestinationOwnership(raw)
