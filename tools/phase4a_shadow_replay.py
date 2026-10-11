"""Attach read-only shadow sidecars to historical and accepted production evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from tb_runner import global_navigation
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.phase3_context import phase3_entry_evidence_from_accepted_replay, resolve_phase3_context
from tb_runner.phase4a_inputs import project_history
from tb_runner.phase4a_planner import PlannerInput, ProductionHistory, compare_production, plan_shadow, production_instance
from tb_runner.scenario_config import BOTTOM_TAB_GLOBAL_NAV
from tb_runner.state_registry import StateRegistry
from tb_runner.transition_observation import TransitionObserver
from tools.phase4a_shadow_smoke import SCENARIOS


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def checked_decision(value):
    first = plan_shadow(value)
    assert first.to_json() == plan_shadow(value).to_json()
    document = first.to_dict()
    assert document['action_executed'] is False and document['visit_credit'] == 0
    assert document['production_visit_authority'] is False
    return first


def accepted_raw(event, terminal):
    payload = event['payload']
    nodes = payload['nodes']
    selected = global_navigation.current(global_navigation.discover(nodes, dict(global_nav=BOTTOM_TAB_GLOBAL_NAV)))
    packages = {n.get('packageName') for n in nodes if n.get('packageName')}
    raw = dict(nodes=nodes, package_name=next(iter(packages)) if len(packages) == 1 else None,
               activity_name=None, scenario_id=event['scenario_id'], scenario_run_id=event['scenario_tx_id'],
               capture_id=event['event_id'], timestamp=event['wall_time_utc'],
               selected_tab=dict(name=selected['logical_name'], verified=True, source='observed_selected_node') if selected else None,
               capability=payload.get('capability'), viewport=payload.get('viewport'),
               source='accepted_SCROLLCAPABILITY_partial', context_source='accepted_partial_capture',
               observation_coverage='OBSERVED_PARTIAL')
    raw['phase3_entry_evidence'] = phase3_entry_evidence_from_accepted_replay(
        event['scenario_id'], event['scenario_tx_id'], terminal, event['wall_time_utc'])
    return raw


def history_before(scenario, step, entries, events):
    # Persisted attempts are admitted only when their production step precedes
    # this capture. Final outcomes never supply visit credit or ranking inputs.
    attempts = [dict(scenario_id=e['scenario_id'], step=e['step'], target=e['target']) for e in entries
                if e['scenario_id'] == scenario and isinstance(e.get('step'), int) and e['step'] < step]
    rows = [e['payload'] for e in events if e['event_type'] == 'FOCUS_RECONCILIATION'
            and e['scenario_id'] == scenario and isinstance(e.get('step_index'), int) and e['step_index'] < step]
    visited = {r['reconciled_visit_instance_id'] for r in rows
               if r.get('visit_record_status') == 'RECORDED' and r.get('physical_visit_confirmed') is True
               and r.get('focus_transition_status') == 'CONFIRMED_MOVED' and r.get('reconciled_visit_instance_id')}
    # Partial saved evidence cannot prove the initial production visited set.
    # Explicitly unknown history prevents unsupported never-attempted claims.
    return project_history(scenario, attempt_entries=attempts, visited_ids=visited, reconciled_rows=rows,
                           known=False, source='PARTIAL_ACCEPTED_PRODUCTION_HISTORY')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    historical = args.root / 'output/phase3d_semantic_substate_20261005/actions'
    paths = [historical / 'brackets.json', historical / 'transitions.jsonl', historical / 'registry_seed.json']
    run = args.root / 'qa_frontend_runs/batch_20261010_214943/device_SM-F741N_R3CX40QFDBP'
    evidence_path = next(run.glob('*.evidence.jsonl'))
    ledger_path = next(run.glob('*.target_attempt_ledger.json'))
    paths.extend([evidence_path, ledger_path])
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    observer = TransitionObserver(StateRegistry.load(paths[2]))
    cases = json.loads(paths[0].read_text(encoding='utf-8'))
    expected = [json.loads(line) for line in paths[1].read_text(encoding='utf-8').splitlines()]
    attached = []
    for index, (case, saved) in enumerate(zip(cases, expected), 1):
        prepared = observer.prepare(case['before_raw'], case['action'], action_started_at=case['action_started_at'])
        raw = case['before_raw']
        value = PlannerInput(prepared.source_snapshot, resolve_phase3_context(raw)['status'],
                             ProductionHistory(str(raw.get('scenario_id') or ''), source='HISTORICAL_HISTORY_UNAVAILABLE'))
        shadow = checked_decision(value)
        got = observer.complete(prepared, case['after_raw'], command_ack=case['command_ack'],
                                action_evidence=case['action_evidence'], action_finished_at=case['action_finished_at'],
                                evidence_refs=case['evidence_refs'])
        assert got.to_dict() == saved, index
        attached.append(dict(case=index, transition_exact=True, recommendation=shadow.to_dict(),
                             comparison=compare_production(shadow, 'UNKNOWN'), historical_action=case['action']))
    assert len(attached) == len(cases) == len(expected) == 16
    save(args.out / 'historical_shadow_sidecars.json', attached)
    events = [json.loads(line) for line in evidence_path.read_text(encoding='utf-8').splitlines()]
    entries = json.loads(ledger_path.read_text(encoding='utf-8'))['entries']
    accepted = {}
    for scenario in SCENARIOS:
        captures = [e for e in events if e['scenario_id'] == scenario and e['event_type'] == 'SCROLL_CAPABILITY'
                    and e['payload'].get('nodes')]
        registry = StateRegistry('phase4a-accepted-' + scenario)
        results = []
        for event in captures:
            terminal = next(e for e in events if e['event_type'] == 'SCENARIO_TERMINAL'
                            and e['scenario_tx_id'] == event['scenario_tx_id'])
            raw = accepted_raw(event, terminal)
            snapshot = build_discovery_snapshot(raw, registry)
            context = resolve_phase3_context(raw)
            step = int(event.get('step_index') or 0)
            history = history_before(scenario, step, entries, events)
            shadow = checked_decision(PlannerInput(snapshot, context['status'], history))
            action_event = next((e for e in events if e['scenario_tx_id'] == event['scenario_tx_id']
                                 and e['event_type'] == 'ACTION_SENT' and e['producer'] == 'runner'
                                 and e.get('phase') == 'main_loop' and e['wall_time_utc'] > event['wall_time_utc']), None)
            action, target = 'UNKNOWN', None
            if action_event:
                command = action_event['payload'].get('command_type', '')
                attempt = next((e for e in entries if e['scenario_id'] == scenario
                                and e.get('req_id') == action_event['payload'].get('request_id')), None)
                if attempt:
                    action, target = 'FOCUS_CANDIDATE', production_instance(attempt['target'], scenario)
                elif command.endswith('.SMART_NEXT'):
                    action = 'FOCUS_NEXT'
            row = dict(event_id=event['event_id'], step=step, context_status=context['status'],
                       state_resolution=snapshot.to_dict()['state_resolution'], raw=raw, history=asdict(history),
                       production_action_event_id=action_event['event_id'] if action_event else None,
                       recommendation=shadow.to_dict(), comparison=compare_production(shadow, action, target))
            results.append(row)
        assert results, scenario
        # Confirm unchanged-focus reconciliation never grants a new visit.
        invalid = [e for e in events if e['scenario_id'] == scenario and e['event_type'] == 'FOCUS_RECONCILIATION'
                   and e['payload'].get('focus_transition_status') == 'CONFIRMED_UNCHANGED'
                   and e['payload'].get('reconciled_visit_instance_id')]
        assert not invalid, scenario
        accepted[scenario] = dict(status='PASS_WITH_LIMITATIONS', captures=len(results),
                                  context_statuses=[r['context_status'] for r in results],
                                  candidate_counts=[r['recommendation']['candidate_count'] for r in results],
                                  comparisons=dict(Counter(r['comparison']['match_classification'] for r in results)))
        save(args.out / (scenario + '.json'), results)
    food_events = [e for e in events if e['scenario_id'] == 'life_food_plugin' and e['event_type'] == 'FOCUS_RECONCILIATION']
    food_attempts = [e for e in entries if e['scenario_id'] == 'life_food_plugin']
    initial_food = json.loads((args.out / 'life_food_plugin.json').read_text(encoding='utf-8'))[0]
    # This is a fixed-inventory history experiment, never a claim that the old
    # viewport remains current at step 100. Each history is contemporaneous.
    from tools.phase4a_shadow_validate import restore_snapshot
    fixed_snapshot = restore_snapshot(build_discovery_snapshot(
        initial_food['raw'], StateRegistry('food-fixed-inventory-analysis')).to_dict())
    progression = []
    for event in food_events:
        step = event['step_index']
        history = history_before('life_food_plugin', step, entries, events)
        shadow = checked_decision(PlannerInput(fixed_snapshot, initial_food['context_status'], history))
        progression.append(dict(step=step, viewport_evidence='INITIAL_VIEWPORT_REUSED_NOT_CURRENT',
                                history=asdict(history), recommendation=shadow.to_dict()))
    save(args.out / 'food_fixed_inventory_history_experiment.json', progression)
    food = dict(production_steps=len(food_events), recorded_viewports=accepted['life_food_plugin']['captures'],
                targeted_attempts=len(food_attempts), distinct_attempted_targets=len({production_instance(e['target'], 'life_food_plugin') for e in food_attempts}),
                focus_outcomes=dict(Counter(e['payload'].get('focus_transition_status') for e in food_events)),
                fixed_inventory_shadow_actions=dict(Counter(r['recommendation']['recommended_action'] for r in progression)),
                fixed_inventory_distinct_recommendations=len({r['recommendation']['recommended_instance_id'] for r in progression}),
                complete_history_available=False, never_attempted_claims=0,
                limitation='One recorded viewport cannot prove changing viewport eligibility, saturation, or eventual scroll. Shadow recommendations are not attempts.',
                production_modified=False, early_termination_implemented=False)
    save(args.out / 'food_repeat_observation.json', food)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    result = dict(historical_exact=16, planner_sidecars=16, accepted=accepted, food=food,
                  determinism='PASS', source_evidence_hashes_unchanged=True, source_hashes=hashes)
    save(args.out / 'summary.json', result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
