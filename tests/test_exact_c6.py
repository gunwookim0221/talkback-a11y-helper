"""C6 adversarial, cross-layer validation. All action effects are synthetic."""
from copy import deepcopy
import json

import pytest

from talkback_lib.exact_action import ActionRejected, REQUIRED_CHECKS
from talkback_lib.exact_action_journal import DurableActionJournal
from talkback_lib.exact_post_action import (
    Correlation,
    Outcome,
    PostActionVerifier,
    digest,
    verify_helper_export,
)
from tools.exact_c5_fixture import ROOT, export, fixture


def _rechain(rows):
    """Rehash deliberately changed synthetic producer evidence as a valid chain."""
    previous = '0' * 64
    for wrapper in rows:
        record = wrapper['record']
        record['previous_hash'] = previous
        wrapper['hash'] = digest(record)
        previous = wrapper['hash']
    return rows


def evaluate(tmp_path, edit=None):
    request, records = fixture()
    if edit:
        edit(request, records)
    verifier = PostActionVerifier(DurableActionJournal(tmp_path / 'audit.jsonl'), request)
    verifier.import_evidence(export(request, records))
    return verifier, verifier.finalize()


@pytest.mark.parametrize('condition', sorted(REQUIRED_CHECKS))
def test_every_c4_authority_fact_is_required_across_c4_c5_replay(tmp_path, condition):
    request, records = fixture()
    helper = export(request, records)
    approval = next(row['record'] for row in helper if row['record']['event_type'] == 'PRE_DISPATCH_APPROVED')
    approval['payload']['facts'][condition] = False
    _rechain(helper)
    verifier = PostActionVerifier(DurableActionJournal(tmp_path / 'audit.jsonl'), request)
    verifier.import_evidence(helper)
    result = verifier.finalize()
    assert result['result'] == Outcome.UNKNOWN_EXECUTION_STATE.value, condition
    assert 'PRE_DISPATCH_GATE_REJECTED' in result['failure_codes']
    assert result['action_dispatch_confirmed'] is False
    assert result['expected_navigation_confirmed'] is False
    assert result['visit_authority'] is False


@pytest.mark.parametrize('field', [
    'lineage_signature', 'child_structure_signature', 'actions', 'class_name',
    'resource_id', 'text', 'content_description',
])
def test_target_descriptor_parent_child_sibling_confusion_cannot_become_strong(tmp_path, field):
    def attack(request, records):
        value = ['changed'] if field.endswith('signature') or field == 'actions' else 'changed'
        records[6][1]['source_identity'][field] = value

    _, result = evaluate(tmp_path, attack)
    assert result['result'] == Outcome.AMBIGUOUS_EFFECT.value, result
    assert result['expected_navigation_confirmed'] is False
    assert any(r['result'] in (Correlation.AMBIGUOUS.value, Correlation.NOT_MATCHED.value)
               for r in result['correlations'])


@pytest.mark.parametrize('field', ['package', 'window_id', 'event_type', 'source_provenance'])
def test_wrong_package_window_or_nonexact_source_is_not_target_effect(tmp_path, field):
    def attack(request, records):
        event = records[6][1]
        event[field] = {
            'package': 'com.attacker', 'window_id': 99, 'event_type': 4,
            'source_provenance': 'PARTIAL_ACCESSIBILITY_SOURCE',
        }[field]

    _, result = evaluate(tmp_path, attack)
    assert result['expected_navigation_confirmed'] is False
    assert result['result'] in (
        Outcome.AMBIGUOUS_EFFECT.value, Outcome.NO_EFFECT.value,
        Outcome.EFFECT_CONFIRMED_WRONG_DESTINATION.value, Outcome.FORBIDDEN_EFFECT.value,
    )


def test_two_identical_platform_click_callbacks_are_not_deduplicated_into_success(tmp_path):
    def attack(request, records):
        records.insert(7, deepcopy(records[6]))

    verifier, result = evaluate(tmp_path, attack)
    assert result['result'] == Outcome.AMBIGUOUS_EFFECT.value
    assert not result['action_effect_confirmed'] and not result['expected_navigation_confirmed']
    wrappers = verifier.journal.records()[0]['evidence']['rows']
    raw = [row['record'] for row in wrappers]
    assert sum(row['event_type'] == 'C5_RAW_EVENT' for row in raw) == 2
    assert len(result['normalized_events']) == 2
    assert result['normalized_events'][1]['duplicate'] is True


def test_transaction_tie_same_millisecond_as_dispatch_is_order_ambiguous(tmp_path):
    def attack(request, records):
        event = records[6][1]
        event['event_uptime_ms'] = 100
        event['helper_receive_uptime_ms'] = 100

    _, result = evaluate(tmp_path, attack)
    assert result['result'] == Outcome.AMBIGUOUS_EFFECT.value
    assert 'ACTION_EFFECT_AMBIGUOUS' in result['failure_codes']
    assert not result['expected_navigation_confirmed']


@pytest.mark.parametrize('edit', [
    'source_label_only', 'source_plus_destination', 'wrong_modal_same_label',
    'same_activity_wrong_structure', 'transient_once', 'partial_structure',
    'wrong_activity_same_label',
])
def test_destination_marker_cannot_override_source_or_incomplete_structure(tmp_path, edit):
    def attack(request, records):
        probe = records[7][1]
        if edit in ('source_label_only', 'source_plus_destination'):
            probe['root_signature'] = 'source:structure:v1'
            if edit == 'source_plus_destination':
                probe['markers'].append('destination:root')
        elif edit == 'wrong_modal_same_label':
            probe['modal'] = 'UNEXPECTED'
            probe['markers'] = ['destination:root']
        elif edit == 'same_activity_wrong_structure':
            probe['root_signature'] = 'wrong:structure'
            probe['activity'] = 'example.Destination'
        elif edit == 'transient_once':
            records[8][1]['root_signature'] = 'source:structure:v1'
        elif edit == 'partial_structure':
            probe['structures'] = []
        elif edit == 'wrong_activity_same_label':
            probe['activity'] = 'example.Other'
            probe['markers'] = ['destination:root']

    _, result = evaluate(tmp_path, attack)
    assert not result['expected_navigation_confirmed'], (edit, result)
    assert result['result'] in (
        Outcome.EFFECT_CONFIRMED_WRONG_DESTINATION.value, Outcome.FORBIDDEN_EFFECT.value,
    )


@pytest.mark.parametrize('stage', range(1, 11))
def test_kill_process_at_each_durable_boundary_never_replays_success(tmp_path, stage):
    request, records = fixture()
    verifier = PostActionVerifier(DurableActionJournal(tmp_path / 'partial.jsonl'), request)
    verifier.import_evidence(export(request, records[:stage]))
    before = verifier.journal.path.read_bytes()
    recovered = PostActionVerifier(DurableActionJournal(verifier.journal.path), request).replay()
    assert not recovered['expected_navigation_confirmed']
    if stage == len(records):
        assert recovered['result'] == Outcome.DISPATCH_ONLY.value
        assert recovered['audit_complete'] is False
    else:
        assert recovered['result'] == Outcome.UNKNOWN_EXECUTION_STATE.value
    assert verifier.journal.path.read_bytes() == before


def test_missing_audit_has_unknown_state_and_does_not_create_records(tmp_path):
    request, _ = fixture()
    journal = DurableActionJournal(tmp_path / 'missing.jsonl')
    recovered = PostActionVerifier(journal, request).replay()
    assert recovered['result'] == Outcome.UNKNOWN_EXECUTION_STATE.value
    assert not recovered['expected_navigation_confirmed']
    assert not journal.path.exists()


@pytest.mark.parametrize('damage', [
    'delete_middle', 'duplicate_seq', 'change_payload', 'change_prevhash', 'wrong_tx',
])
def test_corrupted_hash_chain_is_rejected_on_import(tmp_path, damage):
    request, records = fixture()
    rows = export(request, records)
    if damage == 'delete_middle':
        rows.pop(3)
    elif damage == 'duplicate_seq':
        rows[3]['record']['producer_sequence'] = rows[2]['record']['producer_sequence']
    elif damage == 'change_payload':
        rows[4]['record']['payload']['return'] = False
    elif damage == 'change_prevhash':
        rows[4]['record']['previous_hash'] = 'f' * 64
    elif damage == 'wrong_tx':
        rows[6]['record']['transaction_id'] = 'foreign'
    verifier = PostActionVerifier(DurableActionJournal(tmp_path / 'corrupt.jsonl'), request)
    with pytest.raises(ActionRejected):
        verifier.import_evidence(rows)
    assert not verifier.journal.path.exists() or verifier.journal.path.stat().st_size == 0


@pytest.mark.parametrize('damage', ['wrong_receipt', 'drop_ack', 'drop_cursor'])
def test_semantically_incomplete_but_well_chained_evidence_never_finalizes_success(tmp_path, damage):
    request, records = fixture()
    if damage == 'wrong_receipt':
        records[2][1]['consumption_receipt_id'] = 'foreign'
    elif damage == 'drop_ack':
        records = [row for row in records if row[0] != 'ACK_PREPARED']
    elif damage == 'drop_cursor':
        records = [row for row in records if row[0] != 'C5_CURSOR_ARMED']
    verifier = PostActionVerifier(DurableActionJournal(tmp_path / 'semantic.jsonl'), request)
    verifier.import_evidence(export(request, records))
    result = verifier.finalize()
    assert result['result'] in (Outcome.UNKNOWN_EXECUTION_STATE.value, Outcome.AUDIT_FAILURE.value)
    assert not result['expected_navigation_confirmed']
    assert result['visit_authority'] is False


def test_host_restart_and_replay_are_byte_for_byte_read_only(tmp_path):
    request, records = fixture()
    verifier = PostActionVerifier(DurableActionJournal(tmp_path / 'audit'), request)
    verifier.import_evidence(export(request, records))
    verdict = verifier.finalize()
    before = verifier.journal.path.read_bytes()
    for _ in range(3):
        recovered = PostActionVerifier(DurableActionJournal(verifier.journal.path), request).replay()
        assert recovered['result'] == verdict['result']
        assert recovered['expected_navigation_confirmed'] is True
        assert verifier.journal.path.read_bytes() == before
    foreign = {**request, 'request_digest': 'foreign'}
    with pytest.raises((ActionRejected, KeyError)):
        PostActionVerifier(DurableActionJournal(verifier.journal.path), foreign).handoff()


@pytest.mark.parametrize('request_change', ['id', 'permit', 'nonce', 'owner', 'epoch', 'build'])
def test_replayed_ack_cannot_cross_request_or_helper_epochs(tmp_path, request_change):
    def attack(request, records):
        keys = {
            'id': 'request_id', 'permit': 'permit_id', 'nonce': 'request_nonce', 'owner': 'ownership',
            'epoch': 'helper_connection_epoch', 'build': 'helper_build_id',
        }
        records[5][1][keys[request_change]] = 'foreign'

    _, result = evaluate(tmp_path, attack)
    assert result['result'] == Outcome.UNKNOWN_EXECUTION_STATE.value
    assert not result['expected_navigation_confirmed'] and not result['visit_authority']


def test_perform_action_true_without_attributable_effect_does_not_navigate(tmp_path):
    def attack(request, records):
        records.pop(6)  # No ACTION_CLICK event exists in the collection window.

    _, result = evaluate(tmp_path, attack)
    assert result['action_dispatch_confirmed'] is True
    assert result['action_effect_confirmed'] is False
    assert result['expected_navigation_confirmed'] is False
    assert result['result'] == Outcome.NO_EFFECT.value
    assert result['retry_allowed'] is False


def test_forbidden_effect_signal_is_never_expected_navigation(tmp_path):
    def attack(request, records):
        event = records[6][1]
        event['text'] = ['forbidden:state-control']

    _, result = evaluate(tmp_path, attack)
    assert result['action_dispatch_confirmed'] is True
    assert result['result'] == Outcome.FORBIDDEN_EFFECT.value
    assert not result['expected_navigation_confirmed']
    assert 'FORBIDDEN_SIDE_EFFECT' in result['failure_codes']


def test_home_monitor_six_targets_keep_current_fail_closed_policy():
    data = json.loads((ROOT / 'out/phase5d_c4_20261016/offline_input.json').read_text())
    rows = {row['name']: row for row in data['home_monitor']}
    assert set(rows) == {'serviceCardBody', 'monitorCardBody', 'monitorHeaderGroup', 'Away', 'Stay', 'Disarmed'}
    assert rows['serviceCardBody']['target_class'] == 'MIXED_ACTION_CONTAINER'
    assert rows['monitorCardBody']['target_class'] == 'MIXED_ACTION_CONTAINER'
    assert rows['monitorHeaderGroup']['target_class'] == 'UNKNOWN_ACTIONABLE'
    for row in rows.values():
        assert row['semantic_approved'] is False and row['isolation_approved'] is False
    assert sum(row['semantic_approved'] and row['isolation_approved'] for row in rows.values()) == 0


def test_cross_scenario_incomplete_evidence_never_becomes_approval():
    data = json.loads((ROOT / 'out/phase5d_c4_20261016/offline_input.json').read_text())
    rows = data['cross_scenario']
    names = {row['scenario'] for row in rows}
    assert {
        'life_air_care_plugin', 'life_home_care_plugin', 'life_energy_plugin',
        'life_family_care_plugin', 'life_find_plugin', 'device_smoke_sensor_plugin',
    } <= names
    assert all(row.get('perform_action_called') is False for row in rows)
    assert all(row.get('resolved') is not True or row.get('authorization_use') == 'NONE' for row in rows)
    assert all(not row.get('semantic_approved', False) or not row.get('isolation_approved', False) for row in rows)


def test_only_production_reconciliation_can_issue_visit_authority():
    c5 = (ROOT / 'talkback_lib/exact_post_action.py').read_text(encoding='utf-8')
    kotlin = (ROOT / 'app/src/main/java/com/iotpart/sqe/talkbackhelper/ExactPostAction.kt').read_text(encoding='utf-8')
    runtime = (ROOT / 'app/src/main/java/com/iotpart/sqe/talkbackhelper/ExactActionRuntime.kt').read_text(encoding='utf-8')
    assert 'visit_authority=False' in c5 and '"visit_authority",false' in kotlin
    assert 'ExactActionReadiness()' in runtime and '.performAction(' not in c5 + kotlin
    for forbidden in ('mark_visit(', 'increment_coverage(', 'scenario_pass=', 'coverage +='):
        assert forbidden not in c5 + kotlin
