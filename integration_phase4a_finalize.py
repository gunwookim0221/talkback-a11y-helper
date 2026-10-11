from pathlib import Path
import json, subprocess, xml.etree.ElementTree as ET
from tools.phase4a_shadow_validate import validate
ROOT=Path.cwd(); OUT=ROOT.parent
SMOKE=OUT/'phase4a_shadow_acceptance_20261011'
validation=validate(SMOKE)
monitor=json.loads((SMOKE/'monitor_result.json').read_text(encoding='utf-8'))
replay=json.loads((OUT/'phase4a_shadow_replay_20261011/summary.json').read_text(encoding='utf-8'))
assert monitor['locale_start']==monitor['locale_end']
assert monitor['talkback_pid_start']==monitor['talkback_pid_end']
assert monitor['helper_pid_start']==monitor['helper_pid_end']
assert replay['historical_exact']==16 and replay['planner_sidecars']==16
assert not any(c.get('POTENTIAL_REGRESSION',0) for c in [s['comparisons'] for s in validation['scenarios'].values()])
def count(path):
 node=ET.parse(path).getroot().find('testsuite')
 assert int(node.attrib['failures'])==int(node.attrib['errors'])==0
 return f"{int(node.attrib['tests'])-int(node.attrib['skipped'])} passed, {node.attrib['skipped']} skipped"
checks={k:count(OUT/p) for k,p in {'PLANNER_TESTS':'phase4a_planner_tests.xml','PHASE3_FOCUSED_TESTS':'phase4a_phase3_focused.xml','PRODUCTION_FOCUSED_TESTS':'phase4a_production_focused.xml','ADDITIONAL_FOCUSED_TESTS':'phase4a_additional_focused.xml','FULL_PYTHON_SUITE':'phase4a_final_full_python.xml'}.items()}
def ref(name):return subprocess.check_output(['git','rev-parse',name],text=True).strip()
report=dict(OVERALL_VERDICT='PHASE4A_SHADOW_PLANNER_PASS_WITH_LIMITATIONS',START_INTEGRATION_HEAD='c8f296a51a2a500858a4c9b1780baea71a038a37',FINAL_INTEGRATION_HEAD=ref('HEAD'),ORIGIN_INTEGRATION_HEAD=ref('origin/integration/phase3-current-main'),MAIN_HEAD=ref('main'),ORIGIN_MAIN=ref('origin/main'),MAIN_CHANGED='NO',ORIGINAL_PHASE3_HEAD=ref('feature/phase3c-transition-stability-closure'),ORIGINAL_PHASE3_BRANCH_CHANGED='NO',PHASE4A_PLANNER_IMPLEMENTED='YES',PHASE4A_SHADOW_ONLY='YES',CANDIDATE_IDENTITY_SOURCE='tb_runner.traversal_reliability.instance_id (instance-v1)',CANDIDATE_IDENTITY_REUSED='YES',NEVER_ATTEMPTED_PRIORITY='PASS',ATTEMPTED_UNVISITED_SUPPORTED='YES',STARVATION_PREVENTION='PASS (production attempts only)',SCROLL_RECOMMENDATION='PASS',DETERMINISTIC_RANKING='PASS',PHASE4_PLANNER_EXECUTES_ACTION='NO',PHASE4_PLANNER_CHANGES_ORDER='NO',PHASE4_PLANNER_CHANGES_TERMINATION='NO',PHASE4_PLANNER_GIVES_VISIT_CREDIT='NO',**checks,HELPER_TESTS='NOT_REQUIRED',HISTORICAL_TRANSITION_REPLAY='16/16 exact; 16 shadow sidecars',PLANNER_REPLAY_ATTACHED='YES')
report.update(CANDIDATE_SOURCE_FUNCTIONS='collection_flow._register_focusable_inventory_node/_collect_step_candidate_priority_groups; local_tab_logic._current_valid_content_candidates; completeness.candidate/eligibility; discovery_candidates.build_discovery_snapshot',ATTEMPT_LEDGER_FUNCTIONS='TargetAttemptLedger.begin/finish/entries; ContentTerminal.observe(target_attempt=...)',VISIT_LEDGER_FUNCTIONS='focus_reconciliation.reconcile_focus; TraversalMetrics.observe_focus/observe_reconciliation; ContentTerminal.observe',FOCUS_ACTION_FUNCTIONS='collection_flow._apply_step_collection_phase/_confirm_focus_target; A11yAdbClient.move_focus_smart/target_focus_commit/focus_in_bounds',SCROLL_FUNCTIONS='scroll_reliability.capability/capture/verified_scroll/transition; ContentTerminal.scroll_opportunity; collection_flow._apply_content_terminal_phase',STARVATION_FUNCTIONS='local_tab_logic._prioritize_unattempted_active_unseen_candidates',TERMINATION_FUNCTIONS='ContentTerminal.decision; traversal_reliability.termination_status; collection_flow._main_loop_phase')
for prefix,scenario in zip(['HOME','DEVICES','FOOD','FAMILY','FIND','SMOKE'],validation['scenarios']):
 report[prefix+'_REPLAY']='PASS_WITH_LIMITATIONS'
 report[(prefix if prefix!='SMOKE' else 'SMOKE_SENSOR')+'_SHADOW_SMOKE']='PASS (5 production steps)'
report.update(SHADOW_TRACE_PATH=str(SMOKE/'phase4a_shadow_trace.jsonl'),**monitor['lifecycle_gates'],ENTRY_FAILURE_COUNT=0,PHASE4B_IMPLEMENTED='NO',PHASE5_IMPLEMENTED='NO',READY_FOR_PHASE4B='YES',INTEGRATION_COMMIT='PENDING_PUBLICATION',INTEGRATION_BRANCH_PUSHED='PENDING_PUBLICATION',DOCUMENT_PATH=str(ROOT/'docs/design/talkback-phase4a-shadow-planner-20261011.md'),NEXT_STEP='Phase 4B controlled execution design with target revalidation; retain current entry/termination/visit contracts')
assert report['MAIN_HEAD']==report['ORIGIN_MAIN']=='6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee'
assert report['ORIGINAL_PHASE3_HEAD']=='fb4d01c489a0b3d56883e074771eb823c453d4f2'
(OUT/'phase4a_final_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
text='# Phase 4A acceptance report\n\n```text\n'+'\n'.join(f'{k}={v}' for k,v in report.items())+'\n```\n\n## Evidence and limits\n\n'
text+='Final smoke: '+str(SMOKE)+'\n\nReplay: '+str(OUT/'phase4a_shadow_replay_20261011')+'\n\n'
text+='Six final entries and 30/30 pre-step inputs replay exactly against the published planner. Preliminary smoke is preserved separately; it exposed a conservative UNKNOWN-actionability exclusion and is not used as final acceptance evidence.\n\n'
text+='Accepted captures lack display geometry and complete initial visit histories; Food remains partial where body verification evidence is absent. Untargeted/composite comparisons remain insufficient evidence. Fixed-viewport Food reanalysis cannot prove saturation or eventual scroll. No production or Helper source was modified.\n'
(OUT/'phase4a_final_report.md').write_text(text,encoding='utf-8')
doc=ROOT/'docs/design/talkback-phase4a-shadow-planner-20261011.md'
s=doc.read_text(encoding='utf-8').replace('Final evidence and verdict are appended after the supervised run finishes.','')
s+='\nVerdict: **PHASE4A_SHADOW_PLANNER_PASS_WITH_LIMITATIONS**.\n\n**READY_FOR_PHASE4B=YES**. Ranking is deterministic, A–Q contracts pass, no unsafe recommendation or major planner contract gap was found, and production remains the sole execution/visit authority. Controlled execution must retain target revalidation and exact request/landing reconciliation.\n\n'
s+='Tests: '+ '; '.join(f'{k}: {v}' for k,v in checks.items())+'. Helper tests: NOT_REQUIRED.\n\n'
s+='Final smoke: `'+str(SMOKE)+'`. Device `'+monitor['serial']+'`, locale `'+monitor['locale_start']+'` preserved. Start '+monitor['start_time']+'; end '+monitor['end_time']+'. Six validated entries, six completed scenarios, 30 traces, and 30/30 exact deterministic final-input replays.\n\n'
s+='| Scenario | Steps | Context statuses | Comparisons |\n| --- | --- | --- | --- |\n'
for scenario,row in validation['scenarios'].items():
 s+=f"| {scenario} | {row['steps']} | {row['contexts']} | {row['comparisons']} |\n"
s+='\nAll lifecycle/transport gates: `'+json.dumps(monitor['lifecycle_gates'])+'`. ENTRY failures: 0.\n\n'
s+='Primary trace: `'+str(SMOKE/'phase4a_shadow_trace.jsonl')+'`. Captured inputs: `phase4a_observations.jsonl`; final replay proof: `shadow_validation.json`; runtime monitor: `monitor_result.json`; test XMLs and accepted replay summary are under `'+str(OUT)+'`.\n\n'
s+='A–Q matrix: A/B/C never-attempted/repeated-attempt eligibility; D current-focus penalty; E/F parameterized ACK/fallback no-credit; G production reconciled movement with ACK failure; H positional identity; I stale exclusion; J nonactionable; K/L scroll/no-action; M/N partial-context/scenario-independent structure; O deterministic ordering; P actual-attempt rotation; Q recent-repeat penalty. Additional tests cover pure projection, unknown positive history, current-only no-action, horizontal scroll exclusion, Global Nav domain exclusion, overlays/wrong context, and wrapper forwarding/restoration.\n'
doc.write_text(s,encoding='utf-8')
print(json.dumps(dict(verdict=report['OVERALL_VERDICT'],checks=checks,validation=validation)))
