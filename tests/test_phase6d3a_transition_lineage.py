"""Offline implementation-local lineage diagnostics; never a live-entry reconstruction."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from talkback_lib import A11yAdbClient
from talkback_lib.hierarchy_file_transport import HierarchyTransportError
from tb_runner import collection_flow
from tb_runner.plugin_entry_provenance import PluginEntryProvenanceTracker, source_capture_evidence
from tb_runner.scenario_config import TAB_CONFIGS
from tests.test_phase6d3a_entry_recovery import RealDecoderSnapshotClient
from tests.test_reliable_hierarchy_schema import _candidate, _payload


class OfflineTransitionClient(RealDecoderSnapshotClient):
    """Run the actual decoder/publication API with entirely local fixture payloads."""

    def __init__(self, mode="published"):
        super().__init__()
        self.check_helper_status = lambda **_kwargs: True
        self.get_focus = self._get_focus
        self._run = lambda *_args, **_kwargs: (
            "mCurrentFocus=Window{123 u0 "
            "com.samsung.android.oneconnect/.webplugin.WebPluginActivity}"
        )
        self.dump_calls = 0
        self.focus_calls = 0
        self.mode = "published"
        self._phase6d3a_entity_root_tracker = PluginEntryProvenanceTracker("device_air_purifier_plugin")
        self._phase6d3a_redirect_context = {"unmodified": "redirect"}
        self._phase6d3a_visit_state = {"unmodified": "visits"}
        self.dispatches = []
        self.payload = _payload(candidates=[_candidate(text="Devices", resource_id="source/device_card")])
        self.source_nodes = self.dump_tree(dev="offline")
        self._phase6d3a_entity_root_tracker.record_source_capture(source_capture_evidence(self, self.source_nodes))
        self.source_snapshot = self._last_traversal_candidate_snapshot
        self.operation_finished_at = collection_flow._phase6d3a_transition_diagnostic_timestamp()
        self._phase6d3a_entity_root_tracker.provenance = {"entry_operation": {
            "operation_id": "offline-fixture-operation",
            "operation_finished_at": self.operation_finished_at,
        }}
        self.payload = _payload(candidates=[
            _candidate(text="Navigate up", description="Navigate up", resource_id="plugin/back"),
            _candidate(text="Air purifier", resource_id="plugin/body"),
        ])
        self.mode = mode
        self.dump_calls = 0

    def dump_tree(self, **kwargs):
        self.dump_calls += 1
        if self.mode == "reused_snapshot":
            return deepcopy(self.source_nodes)
        return A11yAdbClient.dump_tree(self, **kwargs)

    def dump_hierarchy_decoded(self, **kwargs):
        if self.mode == "acquisition_error":
            raise HierarchyTransportError("OFFLINE_INJECTED_ACQUISITION_FAILURE", "offline-failed-request")
        return super().dump_hierarchy_decoded(**kwargs)

    def _get_focus(self, **_kwargs):
        self.focus_calls += 1
        return {}


def _config():
    return deepcopy(next(c for c in TAB_CONFIGS if c.get("scenario_id") == "device_air_purifier_plugin"))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("TB_PHASE5A_ACTION_SAFETY_MODE", "enforce")
    monkeypatch.setenv("TB_PHASE5B_CONTROLLED", "1")
    monkeypatch.setattr(collection_flow.time, "sleep", lambda _seconds: None)


def _verify(client, **kwargs):
    return collection_flow._confirm_click_focused_transition_impl(
        client, "offline", _config(), transition_fast_path=True, **kwargs,
    )


def _events(client, name):
    return [r["payload"] for r in client._phase6d3a_entity_root_tracker.diagnostic_events if r["event"] == name]


def test_local_baseline_is_recorded_after_entry_with_exact_sealed_publication():
    client = OfflineTransitionClient()
    source_before = deepcopy(client._phase6d3a_entity_root_tracker.source_capture)
    assert _verify(client) == (False, "source_list_context")
    baseline, = _events(client, "transition_impl_baseline")
    polls = _events(client, "transition_impl_poll")
    assert baseline["acquisition_origin"] == "IMPLEMENTATION_LOCAL_DUMP_AFTER_VERIFIER_ENTRY"
    assert baseline["started_at"] >= client.operation_finished_at
    assert baseline["entry_operation_finished_at"] == client.operation_finished_at
    assert baseline["capture"]["hierarchy_capture_sequence"] == 2
    assert [p["capture"]["hierarchy_capture_sequence"] for p in polls] == [3, 4]
    assert baseline["publication"]["snapshot_replaced"] is True
    assert len(polls) == 2 and client.dump_calls == 3 and client.focus_calls == 2
    assert len({p["capture"]["hierarchy_capture_id"] for p in [baseline, *polls]}) == 3
    for p in [baseline, *polls]:
        capture = p["capture"]
        authority = capture["capture_authority"]
        assert capture["capture_complete"] is True
        assert capture["hierarchy_request_id"] == authority["request_id"] == p["publication"]["decoded_request_id"]
        assert capture["hierarchy_generation"] == authority["generation"]
        assert capture["hierarchy_service_instance_id"] == authority["service_instance_id"]
        assert capture["traversal_root_digest"] == authority["root_digest"]
        assert capture["traversal_root_ref"] == authority["root_ref"]
        assert p["resulting_root_candidate"] == authority
        assert p["authority"] == "NONE"
        assert p["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED_BY_DIAGNOSTICS"
    assert all(p["comparison"]["same_as_local_baseline"] is True for p in polls)
    assert all(p["comparison"]["roots_nonempty"] is True for p in polls)
    assert all(p["comparison"]["classifier"]["state"] == "SOURCE_LIST_CONTEXT" for p in polls)
    assert client._phase6d3a_entity_root_tracker.source_capture == source_before
    assert client.dispatches == []


def test_caller_baseline_avoids_an_extra_dump_and_preserves_distinct_operand_origin():
    client = OfflineTransitionClient()
    baseline_nodes = deepcopy(client.source_nodes)
    assert _verify(client, baseline_nodes=baseline_nodes) == (True, "anchor_match")
    baseline, = _events(client, "transition_impl_baseline")
    poll, = _events(client, "transition_impl_poll")
    assert baseline["acquisition_origin"] == "CALLER_ARGUMENT"
    assert baseline["capture"]["hierarchy_capture_id"] == client._phase6d3a_entity_root_tracker.source_capture["hierarchy_capture_id"]
    assert poll["comparison"]["same_as_local_baseline"] is False
    assert poll["comparison"]["baseline_digest"] == baseline["comparison"]["baseline_digest"]
    assert poll["comparison"]["classifier"]["state"] != "SOURCE_LIST_CONTEXT"
    assert client.dump_calls == 1 and client.dispatches == []
    assert baseline_nodes == client.source_nodes


def test_acquisition_failure_keeps_original_verdict_but_records_exact_loss_boundary():
    client = OfflineTransitionClient("acquisition_error")
    assert _verify(client) == (False, "source_list_context")
    records = _events(client, "transition_impl_baseline") + _events(client, "transition_impl_poll")
    assert len(records) == 3 and client.dump_calls == 3 and client.focus_calls == 2
    for p in records:
        assert p["acquisition_error"] == {
            "type": "HierarchyTransportError", "reason": "OFFLINE_INJECTED_ACQUISITION_FAILURE",
            "request_id": "offline-failed-request",
        }
        assert p["publication"]["snapshot_available"] is False
        assert p["resulting_root_candidate"] is None
        assert p["capture"]["capture_complete"] is False
        assert p["capture"]["hierarchy_generation"] is None
        assert "ACQUISITION_EXCEPTION" in p["resulting_root_rejection_reasons"]
        assert "NO_PUBLISHED_CANDIDATE_SNAPSHOT" in p["resulting_root_rejection_reasons"]
    assert all(p["comparison"]["roots_nonempty"] is False for p in records)
    assert client._phase6d3a_entity_root_tracker.provenance.get("resulting_root") is None
    assert client.dispatches == []


def test_reused_published_snapshot_is_visible_without_becoming_current():
    client = OfflineTransitionClient("reused_snapshot")
    assert _verify(client) == (False, "source_list_context")
    for p in _events(client, "transition_impl_poll"):
        assert p["publication"]["snapshot_replaced"] is False
        assert "PUBLISHED_SNAPSHOT_NOT_REPLACED" in p["resulting_root_rejection_reasons"]
        assert "REFERENCE_SOURCE_CAPTURE_REUSED" in p["resulting_root_rejection_reasons"]
        assert p["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED_BY_DIAGNOSTICS"
    assert client._phase6d3a_entity_root_tracker.entry_attempts == []
    assert client._phase6d3a_redirect_context == {"unmodified": "redirect"}
    assert client._phase6d3a_visit_state == {"unmodified": "visits"}
    assert client.dispatches == []


@pytest.mark.parametrize("mutation", ["missing_authority", "wrong_decoded_request", "unverified_capability", "tampered_root_seal"])
def test_unproven_publication_diagnostics_never_authorize_capture(mutation):
    client = OfflineTransitionClient()

    def mutate(snapshot):
        decoded = snapshot.decoded
        values = {"capture_authority": decoded.capture_authority, "request_id": decoded.request_id,
                  "capability_verified": decoded.capability_verified, "traversal_candidates": decoded.traversal_candidates}
        if mutation == "missing_authority": values["capture_authority"] = None
        elif mutation == "wrong_decoded_request": values["request_id"] = "wrong-request"
        elif mutation == "unverified_capability": values["capability_verified"] = False
        else:
            authority = decoded.capture_authority.to_dict()
            authority["root_digest"] = "0" * 64
            values["capture_authority"] = authority
        mutated = SimpleNamespace(decoded=SimpleNamespace(**values), candidates=snapshot.candidates)
        client._last_traversal_candidate_snapshot = mutated
        return mutated

    client.snapshot_transform = mutate
    # Mutation changes only evidence binding, never the existing classifier's nodes.
    assert _verify(client) == (False, "source_list_context")
    poll = _events(client, "transition_impl_poll")[-1]
    assert poll["capture"]["capture_complete"] is False
    assert "INPUT_NODES_NOT_BOUND_TO_COMPLETE_SEALED_CAPTURE" in poll["resulting_root_rejection_reasons"]
    assert poll["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED_BY_DIAGNOSTICS"
    assert client._phase6d3a_entity_root_tracker.entry_attempts == []
    assert client._phase6d3a_entity_root_tracker.provenance.get("resulting_root") is None
    assert client.dispatches == []


@pytest.mark.parametrize("mode", ["published", "acquisition_error", "reused_snapshot"])
def test_diagnostic_sink_failure_preserves_calls_verdict_and_authority_state(mode):
    normal = OfflineTransitionClient(mode)
    broken = OfflineTransitionClient(mode)
    tracker = broken._phase6d3a_entity_root_tracker
    source_before = deepcopy(tracker.source_capture)
    provenance_before = deepcopy(tracker.provenance)
    redirect = broken._phase6d3a_redirect_context
    visits = broken._phase6d3a_visit_state

    def fail(*_args, **_kwargs):
        raise OSError("offline diagnostic sink failure")

    tracker.record_diagnostic = fail
    assert _verify(broken) == _verify(normal)
    assert (broken.dump_calls, broken.focus_calls) == (normal.dump_calls, normal.focus_calls)
    assert tracker.source_capture == source_before and tracker.provenance == provenance_before
    assert tracker.entry_attempts == [] and tracker.diagnostic_events == []
    assert broken._phase6d3a_redirect_context is redirect and broken._phase6d3a_visit_state is visits
    assert broken.dispatches == normal.dispatches == []


def test_all_devices_records_actual_bound_lookup_input_without_new_acquisition(monkeypatch):
    client = OfflineTransitionClient()
    tracker = client._phase6d3a_entity_root_tracker
    tracker.source_capture["hierarchy_capture_id"] = "stale-reference-only-capture"
    reference_before = deepcopy(tracker.source_capture)
    expected = (True, client.source_nodes, "all_devices_already_selected")
    monkeypatch.setattr(collection_flow, "_ensure_all_devices_location_selected_impl",
                        lambda *args, **kwargs: expected)
    result = collection_flow._ensure_all_devices_location_selected(
        client, "offline", client.source_nodes, lambda **kwargs: pytest.fail("extra acquisition"),
        step_wait_seconds=0.25,
    )
    assert result is expected and client.dump_calls == 0
    record, = _events(client, "all_devices_impl_input")
    assert record["acquisition_origin"] == "CALLER_LOOKUP_INPUT_NO_NEW_ACQUISITION"
    assert record["capture"]["capture_complete"] is True
    assert record["capture"]["hierarchy_capture_id"] != "stale-reference-only-capture"
    assert record["reference_source_capture_id"] == "stale-reference-only-capture"
    assert record["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED_BY_DIAGNOSTICS"
    assert tracker.source_capture == reference_before and client.dispatches == []


@pytest.mark.parametrize("branch", ["direct", "before_expand", "after_expand"])
@pytest.mark.parametrize("mode", ["published", "acquisition_error", "reused_snapshot"])
@pytest.mark.parametrize("sink_broken", [False, True], ids=["sink_ok", "sink_broken"])
def test_three_card_branches_handoff_selected_pre_tap_baseline(monkeypatch, branch, mode, sink_broken):
    client = OfflineTransitionClient(mode)
    tracker = client._phase6d3a_entity_root_tracker
    source_before = deepcopy(tracker.source_capture)
    provenance_before = deepcopy(tracker.provenance)
    initial_nodes = client.source_nodes
    expanded_nodes = deepcopy(initial_nodes)
    dumps = iter([initial_nodes, expanded_nodes])
    client.scroll_to_top = lambda **kwargs: {"ok": True, "reached_top": True, "status": "VERIFIED_TOP"}
    card = {"stable_label": "Air purifier", "label": "Air purifier", "bounds": "0,0,600,600"}
    taps, confirms, expansions = [], [], []
    monkeypatch.setattr(collection_flow, "_dump_device_entry_tree", lambda *args: next(dumps))
    monkeypatch.setattr(collection_flow, "_detect_selected_device_location_with_hierarchy_fallback",
                        lambda *args: {"selected": branch == "direct", "reason": "offline_fixture"})
    monkeypatch.setattr(collection_flow, "_find_safe_visible_device_card_for_direct_entry",
                        lambda *args, **kwargs: (card, {}))
    monkeypatch.setattr(collection_flow, "_ensure_all_devices_location_selected",
                        lambda _client, _dev, nodes, *args, **kwargs: (True, nodes, "all_devices_already_selected"))
    monkeypatch.setattr(collection_flow.device_tab_logic, "collect_visible_device_cards", lambda _nodes: [])
    search_calls = []

    def find(_nodes, _labels):
        search_calls.append(_nodes)
        if branch == "after_expand" and len(search_calls) == 1:
            return None
        return card

    monkeypatch.setattr(collection_flow.device_tab_logic, "find_device_card_by_stable_label", find)
    monkeypatch.setattr(collection_flow, "_find_safe_visible_device_card_for_bounded_search",
                        lambda *args, **kwargs: (card, {}))
    monkeypatch.setattr(collection_flow.device_tab_logic, "collect_high_confidence_collapsed_room_sections",
                        lambda _nodes: [{"rid": "offline/room", "bounds": "0,0,100,100", "label": "Room"}])
    monkeypatch.setattr(collection_flow, "_tap_device_candidate_center",
                        lambda *args, **kwargs: expansions.append("expand") or True)

    def accepted_tap(_client, _dev, _card, *, nodes):
        taps.append(nodes)
        return True, "offline_accepted_card_tap"

    monkeypatch.setattr(collection_flow, "_tap_device_card_safe", accepted_tap)
    original_confirm = collection_flow._confirm_click_focused_transition

    def confirm(**kwargs):
        confirms.append(kwargs)
        # This assertion fails on the preserved pre-repair caller in every branch.
        assert "baseline_nodes" in kwargs
        assert kwargs["baseline_nodes"] is taps[-1]
        assert kwargs["baseline_nodes"] is (expanded_nodes if branch == "after_expand" else initial_nodes)
        return original_confirm(**kwargs)

    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", confirm)
    if sink_broken:
        def fail(*args, **kwargs):
            raise OSError("offline diagnostic sink failure")
        tracker.record_diagnostic = fail
    result = collection_flow._run_enter_device_card_plugin(
        client, "offline", _config(), {"target_stable_labels": ["Air purifier"], "scroll_to_top": True},
        target="Air purifier", max_scroll_search_steps=1, step_wait_seconds=0,
        transition_fast_path=True,
    )
    assert len(taps) == len(confirms) == 1
    assert len(expansions) == (1 if branch == "after_expand" else 0)
    if mode == "published":
        assert result == (True, "visible_target_direct_entry" if branch == "direct" else "device_card_opened")
        assert client.dump_calls == 1  # Only the existing post-tap poll, no late baseline acquisition.
    else:
        assert result == (False, "transition_not_confirmed:source_list_context")
        assert client.dump_calls == 2
    assert tracker.source_capture == source_before and tracker.provenance == provenance_before
    assert tracker.entry_attempts == [] and client.dispatches == []
    assert client._phase6d3a_redirect_context == {"unmodified": "redirect"}
    assert client._phase6d3a_visit_state == {"unmodified": "visits"}
    if sink_broken:
        assert tracker.diagnostic_events == []
    else:
        baseline, = _events(client, "transition_impl_baseline")
        assert baseline["acquisition_origin"] == "CALLER_ARGUMENT"
        assert baseline["capture"]["hierarchy_capture_id"] == source_before["hierarchy_capture_id"]
        assert all(p["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED_BY_DIAGNOSTICS"
                   for p in _events(client, "transition_impl_poll"))
        assert tracker.provenance.get("resulting_root") is None
