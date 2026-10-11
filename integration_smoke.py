"""Bounded existing traversal with opt-in Phase 3 observations; no new policy."""
import json, os, runpy, sys, uuid
from pathlib import Path
from datetime import datetime, timezone
from talkback_lib import A11yAdbClient
from tb_runner import collection_flow
from tb_runner.state_registry import StateRegistry
from tb_runner.transition_observation import TransitionObserver
from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
from tb_runner.phase3_focus import normalize_phase3_focus_transition
from tools.state_fingerprint_diagnostic import capture_observation

OUT=Path('../smoke_context_focus_20261011').resolve();OUT.mkdir(exist_ok=True)
SERIAL='R3CX40QFDBP'
SCENARIOS=['home_main','devices_main','life_food_plugin','life_family_care_plugin','life_find_plugin','device_smoke_sensor_plugin']
config=json.loads(Path('config/runtime_config.json').read_text(encoding='utf-8'))
for scenario in SCENARIOS:
    config.setdefault('scenarios',{}).setdefault(scenario,{})['max_steps']=5
(OUT/'runtime_config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
os.environ['TB_RUNTIME_CONFIG_PATH']=str(OUT/'runtime_config.json')
os.environ['TB_EVIDENCE_LEDGER']='1'
os.environ['TB_TRAVERSAL_PROFILER']='1'
diagnostic=A11yAdbClient(start_monitor=False)
registry=StateRegistry('phase3-main-smoke');observer=TransitionObserver(registry)
original_loop=collection_flow._main_loop_phase
original_move=A11yAdbClient.move_focus_smart
active={};counts={};rows=[]
def save():
    (OUT/'phase3_observations.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    registry.save(OUT/'phase3_registry.json')
def loop(client,dev,phase_ctx):
    s=phase_ctx.tab_cfg['scenario_id'];run_id=s+':'+uuid.uuid4().hex
    raw=capture_observation(diagnostic,dev,scenario_id=s,scenario_run_id=run_id)
    entry=phase3_entry_evidence_from_main_loop(phase_ctx,run_id,raw['timestamp'])
    raw['phase3_entry_evidence']=entry
    active.update(scenario=s,run_id=run_id,entry_evidence=entry)
    from tb_runner.discovery_candidates import build_discovery_snapshot
    snapshot=build_discovery_snapshot(raw,registry)
    context=resolve_phase3_context(raw)
    rows.append(dict(kind='ENTRY_TO_TRAVERSAL',scenario=s,scenario_run_id=run_id,entry_evidence=entry,
        context=context,raw=raw,snapshot=snapshot.to_dict(),mode='SHADOW_OBSERVATIONAL'))
    save(); print('[PHASE3_SMOKE] '+json.dumps(dict(scenario=s,entry='VERIFIED_MAIN_LOOP',
        context_status=context['status'],state_id=snapshot.state_id,candidates=len(snapshot.candidates))),flush=True)
    try:return original_loop(client,dev,phase_ctx)
    finally:active.clear();save()
def move(client,dev=None,direction='next'):
    s=active.get('scenario');n=counts.get(s,0)
    if not s or n>=2 or direction!='next':return original_move(client,dev,direction)
    counts[s]=n+1
    run_id=active['run_id'];entry=active['entry_evidence']
    before=capture_observation(diagnostic,dev,scenario_id=s,step=n,scenario_run_id=run_id)
    before['phase3_entry_evidence']=entry
    prepared=observer.prepare(before,dict(occurrence_id=s+':smart_next:'+str(n),producer='existing_production_smoke',
        action_kind='FOCUS_NEXT',target_identity={'operation':'HELPER_SMART_NEXT_UNTARGETED'}))
    ack=original_move(client,dev,direction)
    after=capture_observation(diagnostic,dev,scenario_id=s,step=n+1,scenario_run_id=run_id)
    after['phase3_entry_evidence']=entry
    request_id=((ack.get('raw') or {}).get('reqId') if isinstance(ack,dict) and isinstance(ack.get('raw'),dict) else None)
    focus=normalize_phase3_focus_transition(before,after,ack,expected_request_id=request_id,scenario_run_id=run_id)
    before_projected=focus['before_observation'];after_projected=focus['after_observation']
    focus_summary={key:value for key,value in focus.items()
        if key not in {'before_observation','after_observation','before_actual_focus_node','after_actual_focus_node'}}
    transition=observer.complete(prepared,after_projected,command_ack=ack,action_evidence={
        'producer':'existing_production_smoke','request_correlation':focus['request_correlation'],
        'phase3_focus_observation':focus_summary})
    rows.append(dict(kind='CONTROLLED_PRODUCTION_SMART_NEXT',scenario=s,before_raw=before,after_raw=after,
        scenario_run_id=run_id,focus_observation=focus_summary,
        action=prepared.action.to_dict(),command_ack=ack,transition=transition.to_dict(),mode='SHADOW_OBSERVATIONAL'))
    save();return ack
collection_flow._main_loop_phase=loop
A11yAdbClient.move_focus_smart=move
sys.argv=['script_test.py','--serial',SERIAL,'--output-dir',str(OUT/'run'),'--language-mode','current','--launch-mode','warm']
for s in SCENARIOS:sys.argv+=['--scenario',s]
runpy.run_path('script_test.py',run_name='__main__')
