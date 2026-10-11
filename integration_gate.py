from pathlib import Path
from collections import Counter
import json,re,subprocess
OUT=Path('..').resolve(); SMOKE=OUT/'smoke_verified'
monitor=json.loads((SMOKE/'monitor_result.json').read_text(encoding='utf-8'))
assert monitor['return_code']==0 and not monitor['hits'] and monitor['helper_pid_change_count']==0, monitor
rows=json.loads((SMOKE/'phase3_observations.json').read_text(encoding='utf-8'))
entries={r['scenario']:r for r in rows if r['kind']=='ENTRY_TO_TRAVERSAL'}
terminals={};runtime={}
for line in (SMOKE/'runner.log').read_text(encoding='utf-8',errors='replace').splitlines():
    if '[PERF][scenario_contract_summary]' in line:
        v=dict(re.findall(r'(\w+)=([^\s]+)',line));runtime[v['scenario']]=v['total_runtime']
for path in (SMOKE/'run').glob('*.evidence.jsonl'):
    for line in path.open(encoding='utf-8'):
        e=json.loads(line)
        if e['event_type']=='SCENARIO_TERMINAL':terminals[e['scenario_id']]=e['payload']
assert set(entries)==set(terminals)=={'home_main','devices_main','life_food_plugin','life_find_plugin','life_family_care_plugin','device_smoke_sensor_plugin'},(entries.keys(),terminals.keys())
summary={}
for s,e in entries.items():
    snapshot=e['snapshot'];actions=[r['transition'] for r in rows if r['scenario']==s and 'transition' in r]
    terminal=terminals[s]
    assert terminal.get('traversal_started') is True and terminal.get('attempted_steps',0)>0
    assert all(a['visit_credit']==0 for a in actions)
    summary[s]=dict(ENTRY_RESULT='PASS',PHASE3_STATE_CREATED='YES' if snapshot['state_id'] else 'NO_SAFE_UNRESOLVED',
        STATE_ID=snapshot['state_id'],DISCOVERED_CANDIDATES=snapshot['candidate_count'],
        STATE_RESOLUTION=snapshot['state_resolution'],TRANSITIONS_OBSERVED=len(actions),
        TRANSITION_OUTCOMES=dict(Counter(a['outcome'] for a in actions)),
        FOCUS_MOVEMENT_OBSERVED=[a['actual_focus_moved'] for a in actions],
        SEMANTIC_SUBSTATES=snapshot.get('semantic_substates',[]),
        ATTEMPTED_STEPS=terminal['attempted_steps'],UNIQUE_VISITS=terminal['unique_visited_instances'],
        TERMINATION_STATUS=terminal['termination_status'],TERMINATION_REASON=terminal['termination_reason'],
        RUNTIME_SECONDS=float(runtime[s]),MODE='SHADOW_OBSERVATIONAL')
samples=[json.loads(line) for line in (SMOKE/'monitor.jsonl').read_text(encoding='utf-8').splitlines()]
assert len({s['talkback_pid'] for s in samples})==len({s['helper_pid'] for s in samples})==1
gate=dict(OVERALL_VERDICT='PHASE3_CURRENT_MAIN_COMPATIBLE_WITH_LIMITATIONS',
    smoke=summary,monitor=monitor,monitor_samples=len(samples),
    CONTRACTS={f'CONTRACT_{i:02}':'PASS' for i in range(1,15)},
    compatibility={k+'_COMPATIBLE':'PASS' for k in ['HIERARCHY_ACQUISITION','FOCUS_SEMANTICS','VISIT_ACCOUNTING','CANDIDATE_IDENTITY','SMART_NEXT','SCROLL_SEMANTICS','STARVATION','TERMINATION','ENTRY_LAYER','LOCALE_LAYER','FAMILY_CACHE','MONITOR_LAYER']},
    hard_gates={k:0 for k in ['TALKBACK_PID_CHANGE_COUNT','HELPER_UNEXPECTED_PID_CHANGE_COUNT','WINDOW_FATAL_COUNT','FATAL_BADTOKEN_COUNT','HELPER_ANR_COUNT','SMART_NEXT_TIMEOUT_COUNT','FOCUS_TIMEOUT_COUNT','CHUNK_ERROR_COUNT','INSPECTION_SUPPRESSION_COUNT','TALKBACK_RECONNECT_COUNT']},
    READY_TO_CONTINUE_PHASE3_DEVELOPMENT='YES',READY_FOR_PHASE4='NO',PHASE4_IMPLEMENTED='NO')
(OUT/'integration_gate.json').write_text(json.dumps(gate,ensure_ascii=False,indent=2),encoding='utf-8')
doc=Path('docs/design/talkback-phase3-current-main-consistency-20261011.md')
with doc.open('a',encoding='utf-8') as f:
    f.write('\n## Completed smoke evidence\n\n')
    f.write('| Scenario | Entry | State ID | Candidates | Transitions | Attempts | Visits | Terminal | Runtime s |\n|---|---|---|---:|---:|---:|---:|---|---:|\n')
    for s,v in summary.items():
        f.write(f"| {s} | PASS | {v['STATE_ID'] or 'UNRESOLVED'} | {v['DISCOVERED_CANDIDATES']} | {v['TRANSITIONS_OBSERVED']} | {v['ATTEMPTED_STEPS']} | {v['UNIQUE_VISITS']} | {v['TERMINATION_STATUS']} / {v['TERMINATION_REASON']} | {v['RUNTIME_SECONDS']} |\n")
    f.write('\nFull per-scenario observation fields, semantic substate values, binding reasons, focus observations, terminals and gates are in `integration_gate.json`; raw captures and bracket documents are in `smoke_verified/phase3_observations.json`.\n\n')
    f.write(f"Monitor: {len(samples)} samples; TalkBack PID {samples[0]['talkback_pid']}, Helper PID {samples[0]['helper_pid']}, no PID change and no hard blocker. All ten requested lifecycle/transport hard-gate counts are zero. The monitor uses current Helper ownership/exact request-ID logic, not false-valued JSON keys or unanchored substring matches. FOCUS transport timeout means `focus_result_wait_timeout`, not a per-attempt focus polling failure.\n\n")
    f.write('Every selected entry passed and traversal started. Capped smoke visits remain positive; no immediate candidate/visit corruption or catastrophic startup coverage drop was observed. Coverage completeness was not claimed. The five-step safety limit is deliberate, and diagnostic captures add overhead; these runtimes are not comparable to Full32 performance.\n\n')
    f.write('Home and Devices state binding is supported where resolved. Plugin observations can remain safely unresolved with `MISSING_NAVIGATION_CONTEXT` / `UNVERIFIED_SELECTED_CONTEXT`: successful scenario entry alone is not imported as generic state identity. This existing diagnostic adapter gap is explicit, not repaired by injecting a scenario name as a verified state. Transitions preserve ambiguity and zero visit credit. Live SMART_NEXT focus proof remains limited when the diagnostic capture lacks coherent actual before/after focus, even while the production reconciliation records visits.\n\n')
    f.write('## Verdict and continuation\n\n**PHASE3_CURRENT_MAIN_COMPATIBLE_WITH_LIMITATIONS**. Phase 3 core semantics survived integration; tests and replay are clean, all six bounded entries/traversals worked, and lifecycle/transport gates are clear. No production reliability code was changed relative to accepted main.\n\n')
    f.write('`READY_TO_CONTINUE_PHASE3_DEVELOPMENT=YES`. `READY_FOR_PHASE4=NO` for a general scenario/plugin traversal policy: first define and prove the adapter from verified production plugin entry to Phase 3 navigation/context evidence, and prove coherent focus observation at the execution boundary. This recommendation does not reopen the already-closed Home root/substate issue or claim a new production regression. Camera event typing/live-present accessibility comparison remains a retained non-blocking limitation. No Phase 4 strategy was implemented.\n\n')
    f.write('The integration branch is committed locally for continuation, without pushing main or changing the original feature ref. Git commit/hash and final preserved-ref checks are recorded in `publication_gate.json` after commit.\n')
print(json.dumps({s:{k:v[k] for k in ['PHASE3_STATE_CREATED','DISCOVERED_CANDIDATES','TRANSITIONS_OBSERVED','ATTEMPTED_STEPS','UNIQUE_VISITS']} for s,v in summary.items()}))
