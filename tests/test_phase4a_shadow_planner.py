from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from state_model_fixtures import node, observation
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.phase4a_inputs import project_history, runtime_input, production_action
from tb_runner.phase4a_planner import PlannerInput, ProductionHistory, compare_production, plan_shadow, production_instance
from tb_runner.state_registry import StateRegistry


def inputs(*, nodes=None, focus=None, context="PARTIAL_CONTEXT", scenario="synthetic", scroll=False, **kwargs):
    raw = observation(nodes=nodes if nodes is not None else [node('id.a', 'A'), node('id.b', 'B', '0,220,500,320')])
    raw['scenario_id'] = scenario
    if focus is not None:
        raw['focus_node'] = focus
    if scroll:
        raw['capability'] = dict(axis_contract='axis-v1', contradictory=False, containers=[
            dict(className='ScrollView', boundsInScreen='0,0,1000,900', axis='VERTICAL', scroll_forward_supported=True)])
    snapshot = build_discovery_snapshot(raw, StateRegistry('planner-test'))
    return PlannerInput(snapshot, context, ProductionHistory(scenario, known=True), **kwargs)


def ids(value):
    return {c.to_dict()['target_identity']['resource_id']: production_instance(c.to_dict()['target_identity'], value.history.scenario_id)
            for c in value.snapshot.candidates if c.action_kind == 'FOCUS_TARGET'}


def decide(value, **history):
    return plan_shadow(replace(value, history=replace(value.history, **history))).to_dict()


def test_never_attempted_beats_visited():
    value = inputs(); identity = ids(value)
    got = decide(value, visits=((identity['id.a'], 1),))
    assert got['recommended_instance_id'] == identity['id.b']
    assert got['ranking'][0]['priority_tier'] == 0
    assert got['ranking'][1]['priority_tier'] == 3


def test_never_attempted_beats_repeated_attempt_and_mismatch_stays_eligible():
    value = inputs(); identity = ids(value)
    got = decide(value, attempts=((identity['id.a'], 7),), recent_attempts=(identity['id.a'],) * 7)
    assert got['recommended_instance_id'] == identity['id.b']
    assert got['attempted_unvisited_count'] == 1
    assert got['ranking'][1]['eligible'] is True
    assert got['ranking'][1]['visit_count'] == 0


def test_current_visited_focus_deprioritized_but_input_focus_not_assumed():
    value = inputs(focus=node('id.a', 'A', accessibilityFocused=True)); identity = ids(value)
    got = decide(value, visits=((identity['id.a'], 1),))
    assert got['recommended_instance_id'] == identity['id.b']
    assert 'CURRENT_FOCUS_DEPRIORITIZED' in got['ranking'][1]['reason_codes']
    fallback = inputs(focus=node('id.a', 'A', focused=True, accessibilityFocused=False))
    assert plan_shadow(fallback).to_dict()['recommended_instance_id'] == ids(fallback)['id.a']


@pytest.mark.parametrize('row', [
    dict(command_ack_status='SUCCESS', focus_transition_status='CONFIRMED_UNCHANGED', visit_record_status='NOT_RECORDED'),
    dict(command_ack_status='FAIL', focus_transition_status='CONFIRMED_MOVED', visit_record_status='REPRESENTATIVE_ONLY'),
    dict(status='FALSE_FOCUS_FALLBACK', visit_credit=0, production_visit_authority=False),
])
def test_ack_and_phase3_focus_cannot_create_visits(row):
    value = inputs(); identity = ids(value)
    row['reconciled_visit_instance_id'] = identity['id.a']
    history = project_history('synthetic', reconciled_rows=[row])
    got = plan_shadow(replace(value, history=history)).to_dict()
    assert got['visited_count'] == 0
    assert got['recommended_instance_id'] == identity['id.a']


def test_ack_failure_actual_move_uses_existing_production_reconciled_ledger():
    value = inputs(); identity = ids(value)
    row = dict(focus_transition_status='CONFIRMED_MOVED', command_ack_status='FAIL',
               visit_record_status='RECORDED', reconciled_visit_instance_id=identity['id.a'])
    history = project_history('synthetic', visited_ids=[identity['id.a']], reconciled_rows=[row])
    got = plan_shadow(replace(value, history=history)).to_dict()
    assert got['visited_count'] == 1
    assert got['recommended_instance_id'] == identity['id.b']


def test_same_resource_different_bounds_distinct_and_dynamic_text_identity_stable():
    value = inputs(nodes=[node('id.same', '1 minute'), node('id.same', '2 minutes', '0,220,500,320')])
    targets = [c.to_dict()['target_identity'] for c in value.snapshot.candidates if c.action_kind == 'FOCUS_TARGET']
    identities = [production_instance(t, 'synthetic') for t in targets]
    assert len(set(identities)) == 2
    renamed = inputs(nodes=[node('id.same', '5 minutes')])
    assert ids(renamed)['id.same'] in identities


def test_stale_excluded_and_current_unknown_ledger_not_called_never_attempted():
    value = inputs(); identity = ids(value)
    got = decide(value, stale_ids=(identity['id.a'],))
    assert got['recommended_instance_id'] == identity['id.b']
    assert any(x['exclusion_reason'] == 'STALE_CANDIDATE' for x in got['excluded'])
    unknown = decide(value, known=False)
    assert unknown['never_attempted_count'] == 0
    assert unknown['ranking'][0]['reason_codes'] == ['HISTORY_UNKNOWN_STRUCTURAL_ONLY']


def test_nonfocusable_click_is_excluded_and_never_activated():
    value = inputs(nodes=[node('id.click', 'Click only', focusable=False)])
    got = plan_shadow(value).to_dict()
    assert got['recommended_action'] == 'RECOVERY_OR_NONE'
    assert got['eligible_candidate_count'] == 0
    assert all(x['exclusion_reason'] == 'ACTION_OUTSIDE_FOCUS_PLANNER' for x in got['excluded'])


def test_no_candidates_with_valid_vertical_scroll_recommends_scroll():
    got = plan_shadow(inputs(nodes=[], scroll=True, focus_plateau=True)).to_dict()
    assert got['recommended_action'] == 'SCROLL_FORWARD'
    assert got['reason_codes'][0] == 'SCROLL_AFTER_CANDIDATE_EXHAUSTION'
    assert got['shadow_no_progress_assessment'] == 'FOCUS_PLATEAU_SCROLL_AVAILABLE'


@pytest.mark.parametrize('flags', [dict(scroll_exhausted=True), dict(scroll_blocked=True), dict(pending_transition=True)])
def test_exhausted_blocked_or_pending_scroll_gives_no_action(flags):
    assert plan_shadow(inputs(nodes=[], scroll=True, **flags)).to_dict()['recommended_action'] == 'RECOVERY_OR_NONE'


def test_fresh_focus_precedes_scroll_but_scroll_precedes_revisit():
    value = inputs(scroll=True); identity = ids(value)
    assert plan_shadow(value).to_dict()['recommended_action'] == 'FOCUS_CANDIDATE'
    visited = decide(value, visits=tuple((x, 1) for x in identity.values()))
    assert visited['recommended_action'] == 'SCROLL_FORWARD'


@pytest.mark.parametrize('context', ['PARTIAL_CONTEXT', 'UNRESOLVED_CONTEXT'])
def test_partial_context_structural_ranking_without_scenario_privilege(context):
    a, b = inputs(context=context, scenario='life_food_plugin'), inputs(context=context, scenario='anything_else')
    first, second = plan_shadow(a).to_dict(), plan_shadow(b).to_dict()
    assert {k: first['recommended_target'][k] for k in ('resource_id', 'bounds')} == {
        k: second['recommended_target'][k] for k in ('resource_id', 'bounds')}
    assert [(r['priority_tier'], r['reason_codes']) for r in first['ranking']] == [
        (r['priority_tier'], r['reason_codes']) for r in second['ranking']]
    assert first['eligible_candidate_count'] == second['eligible_candidate_count']
    assert 'STRUCTURAL_ONLY_CONTEXT' in first['reason_codes']


def test_same_inputs_deterministic_pure_and_order_independent():
    value = inputs(); before = deepcopy(value.snapshot.to_dict())
    first = plan_shadow(value).to_json()
    assert first == plan_shadow(value).to_json()
    reversed_value = inputs(nodes=[node('id.b', 'B', '0,220,500,320'), node('id.a', 'A')])
    assert first == plan_shadow(reversed_value).to_json()
    assert value.snapshot.to_dict() == before


def test_real_attempt_updates_rotate_fresh_candidates_without_shadow_consumption():
    value = inputs(nodes=[node(f'id.{i}', str(i), f'0,{i*110},500,{i*110+100}') for i in range(10)])
    attempts, picked = [], []
    for i in range(10):
        got = decide(value, attempts=tuple(attempts), recent_attempts=tuple(x[0] for x in attempts))
        target = got['recommended_instance_id']; picked.append(target); attempts.append((target, 1))
        assert got['ranking'][0]['attempt_count'] == 0
    assert len(set(picked)) == 10
    assert plan_shadow(value).to_dict()['never_attempted_count'] == 10


def test_recently_repeated_attempt_cannot_monopolize_retry_tier():
    value = inputs(); identity = ids(value)
    got = decide(value, attempts=((identity['id.a'], 2), (identity['id.b'], 2)),
                 recent_attempts=(identity['id.b'], identity['id.a'], identity['id.a']))
    assert got['recommended_instance_id'] == identity['id.b']


def test_attempt_projection_separate_from_visit_and_wrong_scenario_ignored():
    value = inputs(); target = plan_shadow(value).to_dict()['recommended_target']
    rows = [dict(scenario_id='synthetic', step=1, target=target, helper_status='TARGET_MATCHED'),
            dict(scenario_id='other', step=2, target=target)]
    before = deepcopy(rows)
    history = project_history('synthetic', attempt_entries=rows)
    assert sum(dict(history.attempts).values()) == 1
    assert history.visits == ()
    assert rows == before


def test_runtime_projection_does_not_mutate_client_or_production_state():
    value = inputs(); identity = ids(value)
    state = SimpleNamespace(reliability_metrics=SimpleNamespace(visited={identity['id.a']}), previous_step_row={})
    client = SimpleNamespace()
    before = deepcopy(vars(state))
    got = plan_shadow(runtime_input(value.snapshot, value.context_status, scenario_id='synthetic', client=client, state=state)).to_dict()
    assert vars(state) == before and vars(client) == {}
    assert got['visited_count'] == 1
    assert got['action_executed'] is False and got['visit_credit'] == 0
    assert got['production_visit_authority'] is False
    assert got['changes_traversal_order'] is False and got['changes_termination'] is False


@pytest.mark.parametrize('context', ['WRONG_CONTEXT', 'CONTRADICTORY_CONTEXT'])
def test_wrong_context_blocks_all_recommendations(context):
    assert plan_shadow(inputs(context=context, scroll=True)).to_dict()['recommended_action'] == 'RECOVERY_OR_NONE'


def test_modal_safety_block_overrides_fresh_candidates():
    assert plan_shadow(inputs(safety_blocked=True)).to_dict()['recommended_action'] == 'RECOVERY_OR_NONE'


def test_disabled_focus_candidate_has_explicit_exclusion():
    got = plan_shadow(inputs(nodes=[node(enabled=False)])).to_dict()
    assert got['eligible_candidate_count'] == 0
    assert any(r['exclusion_reason'] == 'NOT_ACTIONABLE' for r in got['excluded'])


def test_shadow_comparisons_do_not_invent_untargeted_match():
    value = inputs(); identity = ids(value)
    recommendation = plan_shadow(replace(value, history=replace(value.history, attempts=((identity['id.a'], 2),))))
    assert compare_production(recommendation, 'FOCUS_NEXT')['match_classification'] == 'INSUFFICIENT_EVIDENCE'
    assert compare_production(recommendation, 'FOCUS_CANDIDATE', identity['id.a'])['match_classification'] == 'EXPECTED_SMARTER_CHOICE'
    assert compare_production(recommendation, 'FOCUS_CANDIDATE', identity['id.b'])['match'] is True
    assert production_action(dict(target_focus_attempted=True, target_focus_descriptor=recommendation.to_dict()['recommended_target']), 'synthetic')[0] == 'FOCUS_CANDIDATE'


def test_only_current_focus_without_verified_transition_value_is_not_reselected():
    focused = node('id.a', 'A', accessibilityFocused=True)
    value = inputs(nodes=[focused], focus=focused)
    assert plan_shadow(value).to_dict()['recommended_action'] == 'RECOVERY_OR_NONE'
    identity = ids(value)['id.a']
    promoted = replace(value, transition_value_ids=(identity,))
    assert plan_shadow(promoted).to_dict()['recommended_action'] == 'FOCUS_CANDIDATE'


def test_other_visited_recovery_precedes_current_focus():
    value = inputs(focus=node('id.a', 'A', accessibilityFocused=True))
    identity = ids(value)
    got = decide(value, visits=tuple((i, 1) for i in identity.values()))
    assert got['recommended_instance_id'] == identity['id.b']


def test_horizontal_scroll_never_becomes_vertical_recommendation():
    from tools.phase4a_shadow_validate import restore_snapshot
    value = inputs(nodes=[], scroll=True)
    document = value.snapshot.to_dict()
    for candidate in document['candidates']:
        if candidate['action_kind'] == 'SCROLL_FORWARD_VERTICAL':
            candidate['action_kind'] = 'SCROLL_FORWARD_HORIZONTAL'
    got = plan_shadow(replace(value, snapshot=restore_snapshot(document))).to_dict()
    assert got['recommended_action'] == 'RECOVERY_OR_NONE'


def test_global_navigation_focus_targets_outside_content_domain():
    value = inputs(nodes=[node('pkg:id/menu_favorites', 'Home', '0,900,200,1000', selected=True, role='tab')])
    got = plan_shadow(value).to_dict()
    assert got['eligible_candidate_count'] == 0
    assert any(r['exclusion_reason'] == 'OUTSIDE_TRAVERSAL_DOMAIN' for r in got['excluded'])


def test_partial_history_preserves_positive_facts_without_claiming_freshness():
    value = inputs()
    identity = ids(value)
    got = decide(value, known=False, attempts=((identity['id.a'], 3),), visits=((identity['id.b'], 1),))
    assert got['never_attempted_count'] == 0
    assert got['attempted_unvisited_count'] == 1 and got['visited_count'] == 1
    assert got['recommended_instance_id'] == identity['id.a']


def test_unknown_enabled_with_proven_focusability_remains_structurally_eligible():
    value = inputs(nodes=[node(enabled=None)], context='UNRESOLVED_CONTEXT')
    got = plan_shadow(value).to_dict()
    assert got['recommended_action'] == 'FOCUS_CANDIDATE'
    assert got['ranking'][0]['priority_tier'] == 1
    assert 'ACTIONABILITY_PARTIAL_EVIDENCE' in got['ranking'][0]['reason_codes']
