"""Read-only consistency replay; output is outside the integration source tree."""
from pathlib import Path
from collections import defaultdict, Counter
import json
from tb_runner.state_registry import StateRegistry
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.transition_observation import TransitionObserver, _focus
from tb_runner.state_observation import build_state_observation
from tb_runner import global_navigation
from tb_runner.scenario_config import BOTTOM_TAB_GLOBAL_NAV
from tb_runner.phase3_context import resolve_phase3_context, phase3_entry_evidence_from_accepted_replay

ROOT = Path('D:/Python test/talkback-a11y-helper')
OUT = Path('../replay'); OUT.mkdir(exist_ok=True)
historical = ROOT/'output/phase3d_semantic_substate_20261005/actions'
observer = TransitionObserver(StateRegistry.load(historical/'registry_seed.json'))
brackets = json.loads((historical/'brackets.json').read_text(encoding='utf-8'))
expected = [json.loads(line) for line in (historical/'transitions.jsonl').read_text(encoding='utf-8').splitlines()]
exact = 0
for case, saved in zip(brackets, expected):
    prepared = observer.prepare(case['before_raw'], case['action'], action_started_at=case['action_started_at'])
    got = observer.complete(prepared,case['after_raw'], command_ack=case['command_ack'],
        action_evidence=case['action_evidence'], action_finished_at=case['action_finished_at'], evidence_refs=case['evidence_refs'])
    exact += got.to_dict() == saved
assert exact == len(brackets) == 16, (exact,len(brackets))

scenarios = ['home_main','devices_main','life_food_plugin','life_family_care_plugin','life_find_plugin',
             'device_smoke_sensor_plugin']
run = ROOT/'qa_frontend_runs/batch_20261010_214943/device_SM-F741N_R3CX40QFDBP'
trees=defaultdict(list); transactions=defaultdict(dict); reconciliations=defaultdict(list); terminals=defaultdict(list); event_by_id={}
def focus(observation):
    return dict(viewIdResourceName=observation.get('resource_id'), boundsInScreen=observation.get('bounds'),
        className=observation.get('class_name'), text=observation.get('text'),
        contentDescription=observation.get('content_description'), accessibilityFocused=observation.get('accessibility_focused'),
        packageName=observation.get('package'), enabled=observation.get('enabled'), focusable=observation.get('focusable'))
for line in next(run.glob('*.evidence.jsonl')).open(encoding='utf-8'):
    event=json.loads(line); s=event['scenario_id']; payload=event['payload']; kind=event['event_type']
    event_by_id[event['event_id']]=event
    if s not in scenarios: continue
    if kind=='SCROLL_CAPABILITY' and len(trees[s])<8 and payload.get('nodes'):
        trees[s].append((event['event_id'],payload))
    if kind in ('PRE_FOCUS_OBSERVED','POST_FOCUS_OBSERVED'):
        transactions[(s,event['transaction_id'])][kind]=focus(payload.get('observation') or {})
    if kind=='MOVE_OUTCOME': transactions[(s,event['transaction_id'])][kind]=payload
    if kind=='FOCUS_RECONCILIATION':
        reconciliations[s].append(payload)
        transactions[(s,event['transaction_id'])][kind]=payload
    if kind=='SCENARIO_TERMINAL': terminals[s].append(event)
report={}
for s in scenarios:
    registry=StateRegistry('accepted-'+s); snapshots=[]
    for event_id,p in trees[s]:
        nodes=p['nodes']; items=global_navigation.discover(nodes,dict(global_nav=BOTTOM_TAB_GLOBAL_NAV)); selected=global_navigation.current(items)
        packages={n.get('packageName') for n in nodes if n.get('packageName')}
        source_event=event_by_id[event_id]
        tx_id=source_event.get('scenario_tx_id')
        terminal_event=next((event for event in terminals[s] if event.get('scenario_tx_id')==tx_id),None)
        observed_at=str(source_event.get('wall_time_utc') or '')
        raw=dict(nodes=nodes,package_name=next(iter(packages)) if len(packages)==1 else None,
            activity_name=None,scenario_id=s,scenario_run_id=tx_id,capture_id=event_id,timestamp=observed_at,
            selected_tab=dict(name=selected['logical_name'],verified=True,source='observed_selected_node') if selected else None,
            capability=p.get('capability'),viewport=p.get('viewport'),source='accepted_SCROLLCAPABILITY_partial',
            context_source='accepted_partial_capture',observation_coverage='OBSERVED_PARTIAL')
        if terminal_event:
            raw['phase3_entry_evidence']=phase3_entry_evidence_from_accepted_replay(
                s,tx_id,terminal_event,observed_at)
        snapshot=build_discovery_snapshot(raw,registry).to_dict(); snapshot['accepted_event_id']=event_id
        snapshot['phase3_entry_evidence_status']='VERIFIED' if raw.get('phase3_entry_evidence') else 'MISSING'
        snapshot['phase3_context']=resolve_phase3_context(raw)
        assert all(c['physical_visit_credited'] is False for c in snapshot['candidates'])
        for c in snapshot['candidates']:
            if c['action_kind']=='FOCUS_NEXT': assert not c['target_identity'].get('resource_id')
        snapshots.append(snapshot)
    focus_checks=0; mismatch=[]; unknown_focus=0
    for (scenario,tx),p in transactions.items():
        if scenario!=s or not all(k in p for k in ('PRE_FOCUS_OBSERVED','POST_FOCUS_OBSERVED','MOVE_OUTCOME')):continue
        before={'focus_node':p['PRE_FOCUS_OBSERVED']}; after={'focus_node':p['POST_FOCUS_OBSERVED']}
        proof=p.get('FOCUS_RECONCILIATION',{})
        # POST_FOCUS can precede production realignment. Preserve it as representative;
        # project the later reconciled actual identity separately, as Phase 3's API permits.
        if proof.get('focus_transition_status') in ('CONFIRMED_MOVED','CONFIRMED_UNCHANGED'):
            for raw,key in ((before,'actual_focus_before_id'),(after,'actual_focus_instance_id')):
                identity=proof.get(key)
                if identity:
                    parts=json.loads(identity)
                    raw['actual_focus_node']=dict(viewIdResourceName=parts[2],boundsInScreen=parts[4],accessibilityFocused=True)
                    raw['actual_focus_accessibility_focused']=True
                    raw['actual_focus_resource_id']=parts[2]
                    raw['actual_focus_bounds']=parts[4]
        result=_focus(before,after)
        expected_status=p['MOVE_OUTCOME'].get('focus_transition_status')
        if expected_status in ('CONFIRMED_MOVED','CONFIRMED_UNCHANGED'):
            focus_checks+=1
            if result['status'] in ('UNAVAILABLE','AMBIGUOUS'):
                unknown_focus+=1
                continue
            if result['status']!=expected_status:mismatch.append(dict(transaction_id=tx,expected=expected_status,observed=result['status']))
    false_visits=[r for r in reconciliations[s] if r.get('focus_transition_status')=='CONFIRMED_UNCHANGED' and r.get('reconciled_visit_instance_id')]
    contexts=[x.get('phase3_context',{}) for x in snapshots]
    context_status=contexts[0].get('status','UNOBSERVED') if contexts else 'UNOBSERVED'
    resolutions=[x.get('state_resolution',{}).get('status','UNRESOLVED') for x in snapshots]
    geometry_unknown=any('UNKNOWN_GEOMETRY' in x.get('state_resolution',{}).get('reasons',[]) for x in snapshots)
    report[s]=dict(status='PASS' if snapshots and not mismatch and not false_visits else 'CONFLICT',
        snapshots=len(snapshots),candidate_counts=[len(x['candidates']) for x in snapshots],
        resolved_states=sum(x['state_id'] is not None for x in snapshots),focus_checks=focus_checks,
        focus_mismatches=mismatch,focus_unknown_due_to_partial_capture=unknown_focus,false_visit_count=len(false_visits),
        entry_evidence='VERIFIED_SAME_SCENARIO_TRANSACTION' if snapshots and snapshots[0].get('phase3_entry_evidence_status')=='VERIFIED' else 'MISSING',
        plugin_context_status=context_status,
        state_resolution_statuses=resolutions,
        focus_evidence_status=('COHERENT_WITH_PRODUCTION_RECONCILIATION' if focus_checks and not unknown_focus and not mismatch
                               else 'PARTIAL_ACCEPTED_FOCUS_CAPTURE' if unknown_focus else 'NO_STRICT_FOCUS_EVIDENCE'),
        candidate_discovery='PASS' if any(report_count > 0 for report_count in [len(x['candidates']) for x in snapshots]) else 'NO_CANDIDATES',
        material_regression='NO' if snapshots and not mismatch and not false_visits else 'YES',
        limitation=('Plugin context was observed but state resolution remains partial because accepted captures omit display bounds.'
                    if geometry_unknown else
                    'Accepted partial trees omit selected-tab or plugin-body evidence; states remain safely unresolved.'
                    if not any(x['state_id'] for x in snapshots) else
                    'Accepted evidence supports context and state identity; actual traversal remains production-owned.'),
        production_terminal_evidence=[event['payload'] for event in terminals[s]])
    (OUT/(s+'.json')).write_text(json.dumps(dict(summary=report[s],snapshots=snapshots),ensure_ascii=False,indent=2),encoding='utf-8')
result=dict(historical_phase3_exact=exact,historical_metrics=observer.metrics(),accepted=report)
(OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(historical_exact=exact,accepted={s:r['status'] for s,r in report.items()})))
assert all(r['status']=='PASS' for r in report.values()), report
