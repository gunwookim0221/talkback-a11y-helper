"""Staged Phase 5B validation using the existing request-correlated monitor."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from tools import phase4c_generalized_monitor as phase4
from tools.phase4b_controlled_monitor import read_lines
from tb_runner.phase5b_navigation import STAGES, BUDGETS
from tb_runner.safe_action_policy import evaluate_policy
from tb_runner.canonical_json import canonical_sha256
from tb_runner.traversal_reliability import normalized_bounds


FOCUS_COMMANDS={"TARGET_FOCUS_COMMIT","FOCUS_IN_BOUNDS","FOCUS_TARGET"}


def _native_focus_events(out, scenario):
    events=[]
    for path in (out/'run'/scenario).glob('*.evidence.jsonl'):
        events.extend(read_lines(path))
    helper=[]
    for event in events:
        payload=event.get('payload') or {}
        result=payload.get('helper_result') or {}
        helper.extend(result.get('evidenceEvents') or [])
    return events,helper


def _request_target(helper_events, request_id):
    for event in helper_events:
        if str(event.get('reqId') or '')==str(request_id) and event.get('eventType')=='TARGET_REQUESTED':
            return event.get('payload') or {}
    return {}


def _request_started(helper_events, request_id, command):
    return any(str(event.get('reqId') or '')==str(request_id)
        and event.get('eventType')=='ACTION_EXECUTION_STARTED'
        and str((event.get('payload') or {}).get('action') or '').rsplit('.',1)[-1]==command
        for event in helper_events)


def validate_scenario(scenario, out):
    previous=phase4.STAGES,phase4.BUDGETS
    phase4.STAGES,phase4.BUDGETS=STAGES,BUDGETS
    try:
        result=phase4.validate_scenario(scenario,out)
    finally:
        phase4.STAGES,phase4.BUDGETS=previous
    reasons=list(result['reasons'])
    counters=Counter()
    blocked_ids=set()
    traces=[r for r in read_lines(out/'phase4c_execution_trace.jsonl') if r['scenario']==scenario]
    for row in traces:
        report=row.get('action_safety') or {}
        if report.get('mode')!='enforce':reasons.append('SAFETY_ENFORCEMENT_NOT_PROVEN')
        candidates=report.get('candidates',[])
        counters['TOTAL_STEPS']+=1
        for candidate in candidates:
            classification=candidate['classification']
            kind=classification['safety_class']
            counters[kind+'_CANDIDATES']+=1
            if not candidate['policy']['eligible']:
                counters['SAFETY_BLOCKED']+=1
                blocked_ids.add(classification['action_id'])
        selected=report.get('selected') or {}
        if row.get('planner_executed'):
            classification=selected.get('classification') or {}
            policy=evaluate_policy(classification,selected.get('conditions') or {})
            counters[classification.get('safety_class','UNKNOWN')+'_EXECUTED']+=1
            if not policy.eligible:reasons.append('UNSAFE_ACTION_EXECUTED')
            counters['SAFE_ALTERNATIVE_SELECTED']+=bool(report.get('safety_blocked_candidates'))
            counters['SAFE_SCROLL_SELECTED']+=row.get('actual_execution_mode')=='CONTROLLED_SCROLL'
        if row.get('fallback_used'):
            policy=row.get('fallback_policy_decision')
            if policy != 'READ_ONLY_FOCUS_OBSERVATION':
                reasons.append('FALLBACK_SAFETY_NOT_PROVEN')
            counters['SAFE_FALLBACK_SELECTED']+=policy=='READ_ONLY_FOCUS_OBSERVATION'
        unknown=sum(c['classification']['safety_class']=='UNKNOWN' for c in candidates)
        counters['UNKNOWN_VISIBLE']+=unknown
        counters['UNKNOWN_BLOCKED']+=sum(c['classification']['safety_class']=='UNKNOWN' and not c['policy']['eligible'] for c in candidates)
        counters['UNKNOWN_WITH_SAFE_ALTERNATIVE']+=int(unknown>0 and row.get('planner_executed'))
        counters['UNKNOWN_CAUSED_NO_PROGRESS']+=int(unknown>0 and not row.get('planner_executed') and not row.get('fallback_used'))
        counters['DESTINATION_REVALIDATIONS']+=bool((row.get('dynamic_context') or {}).get('current',{}).get('freshness') in {'FRESH_VERIFIED','FRESH_PARTIAL'})
        counters['RECOVERY_REBINDS']+=bool((row.get('dynamic_context') or {}).get('authority',{}).get('rebound'))
    nav_path=out/'phase5b_navigation_chains.jsonl'
    chains=[r for r in read_lines(nav_path) if r['scenario']==scenario] if nav_path.exists() else []
    permitted={}
    for chain in chains:
        if chain.get('entry_executed'):
            counters['CONDITIONALLY_SAFE_EXECUTED']+=1
            if not chain['phase4_gate']['allowed'] or not evaluate_policy(chain['classification'],chain['conditions']).eligible:
                reasons.append('SAFE_ENTRY_AUTHORITY_INCOMPLETE')
            permitted[chain['entry_request_id']]='CLICK_FOCUSED'
            if not chain.get('entry_correlated'):reasons.append('SAFE_ENTRY_STALE_REQUEST')
        counters['SAFE_CHILD_ENTRIES']+=bool(chain.get('entry_confirmed'))
        counters['SAFE_RETURN_ATTEMPTS']+=bool(chain.get('return_attempted'))
        counters['SAFE_RETURN_SUCCESSES']+=bool(chain.get('return_success'))
        counters['SAFE_RETURN_FAILURES']+=bool(chain.get('return_attempted') and not chain.get('return_success'))
        if chain.get('return_attempted'):
            counters['CONDITIONALLY_SAFE_EXECUTED']+=1
            if not evaluate_policy(chain['return_classification'],chain['return_conditions']).eligible:
                reasons.append('UNSAFE_RETURN_EXECUTED')
        if chain.get('return_success'):
            if not chain.get('return_ownership_match') or not chain.get('return_context_revalidated'):
                reasons.append('FALSE_SAFE_RETURN')
            if chain.get('chain_id')!=canonical_sha256({k:v for k,v in chain.items() if k!='chain_id'}):
                reasons.append('SAFE_NAVIGATION_CHAIN_HASH_MISMATCH')
            native=chain.get('native_entry_events') or []
            if not any(e.get('event_type')=='ACTION_SENT' and e.get('payload',{}).get('request_id')==chain['entry_request_id'] for e in native):
                reasons.append('SAFE_NAVIGATION_NATIVE_LINK_MISSING')
        if chain.get('failure') or chain.get('entry_executed') and not chain.get('return_success'):
            reasons.append('SAFE_NAVIGATION_ROUNDTRIP_FAILED')
        if chain.get('attempt_credit') or chain.get('visit_credit'):
            reasons.append('NAVIGATION_GRANTED_VISIT_AUTHORITY')
    # Independently bind every actual focus request to its exact one-use permit.
    auth_path=out/'phase5b_dispatch_authorizations.jsonl'
    auth_rows=[r for r in read_lines(auth_path) if r.get('scenario')==scenario] if auth_path.exists() else []
    authorized={str(r.get('request_id')):r for r in auth_rows
        if r.get('event')=='NATIVE_DISPATCH_AUTHORIZED' and r.get('request_id')}
    blocks={str(r.get('request_id')):r for r in auth_rows
        if r.get('event')=='BLOCKED_NATIVE_DISPATCH' and r.get('request_id')}
    native_events,helper_events=_native_focus_events(out,scenario)
    native_focus=[]
    sent_requests=set()
    for event in native_events:
        if event.get('event_type')!='ACTION_SENT':continue
        payload=event.get('payload') or {}
        command=str(payload.get('command_type') or '').rsplit('.',1)[-1]
        request=str(payload.get('request_id') or '')
        if command in FOCUS_COMMANDS:
            sent_requests.add(request)
            native_focus.append((event,command,request))
            started=_request_started(helper_events,request,command)
            permit=authorized.get(request)
            if permit is None:
                if started:
                    reasons.append('UNAUTHORIZED_FOCUS_DISPATCH_EXECUTED')
                    counters['UNKNOWN_EXECUTED']+=1
                elif request in blocks:
                    counters['SECONDARY_BLOCKED']+=1
                else:
                    counters['FOCUS_DISPATCH_NOT_EXECUTED']+=1
                continue
            target=permit.get('target_identity') or {}
            classification=permit.get('classification') or {}
            policy=permit.get('policy') or {}
            gate=permit.get('execution_gate') or {}
            if (permit.get('action_type')!='FOCUS' or permit.get('authorization_valid') is not True
                or classification.get('safety_class') not in {'SAFE','CONDITIONALLY_SAFE'}
                or not policy.get('eligible') or not gate.get('allowed')):
                reasons.append('INVALID_FOCUS_AUTHORIZATION')
            requested=_request_target(helper_events,request)
            requested_bounds=normalized_bounds(requested.get('requestedBounds') or '')
            if requested and (str(requested.get('targetId') or '')!=str(target.get('resource_id') or '')
                or requested_bounds and requested_bounds!=normalized_bounds(target.get('bounds') or '')):
                reasons.append('FOCUS_AUTHORIZATION_TARGET_MISMATCH')
            if started:
                counters[classification.get('safety_class','UNKNOWN')+'_EXECUTED']+=1
                if not requested:
                    reasons.append('FOCUS_HELPER_TARGET_EVIDENCE_MISSING')
        elif command=='CLICK_FOCUSED' and permitted.get(request)==command:
            continue
        elif command=='BACK' and str(event.get('step_index','')).startswith('phase5b:') and any(c.get('return_attempted') for c in chains):
            continue
        elif command not in {'GET_FOCUS','SCROLL'}:
            reasons.append('UNAPPROVED_NATIVE_ACTION:'+command)
    for request,row in blocks.items():
        if _request_started(helper_events,request,'TARGET_FOCUS_COMMIT'):
            reasons.append('BLOCKED_FOCUS_REQUEST_REACHED_HELPER')
            counters['UNKNOWN_EXECUTED']+=1
    # Include request-scoped preflight denials that correctly produced no
    # ACTION_SENT/native request. The in-loop count above handles blocked
    # focus requests that reached the runner ledger, so exclude those IDs here.
    counters['SECONDARY_BLOCKED']+=sum(
        r.get('dispatch_kind')=='SECONDARY'
        and r.get('event') in {'BLOCKED_BEFORE_DISPATCH','BLOCKED_NATIVE_DISPATCH'}
        and (not r.get('request_id') or str(r.get('request_id')) not in sent_requests)
        for r in auth_rows)
    for helper_event in helper_events:
        if helper_event.get('eventType')!='ACTION_EXECUTION_STARTED':continue
        request=str(helper_event.get('reqId') or '')
        command=str((helper_event.get('payload') or {}).get('action') or '').rsplit('.',1)[-1]
        if command in FOCUS_COMMANDS and request not in authorized and request not in blocks and request not in sent_requests:
            reasons.append('HELPER_FOCUS_DISPATCH_WITHOUT_RUNNER_AUTHORIZATION')
            counters['UNKNOWN_EXECUTED']+=1
    counters['TOTAL_SECONDARY_DISPATCH_ATTEMPTS']+=sum(r.get('dispatch_kind')=='SECONDARY'
        for r in auth_rows if r.get('event') in {'NATIVE_DISPATCH_AUTHORIZED','BLOCKED_NATIVE_DISPATCH','BLOCKED_BEFORE_DISPATCH'})
    counters['SECONDARY_SAFE']+=sum(r.get('dispatch_kind')=='SECONDARY' and r.get('safety_class')=='SAFE'
        for r in auth_rows if r.get('event') in {'NATIVE_DISPATCH_AUTHORIZED','BLOCKED_NATIVE_DISPATCH','BLOCKED_BEFORE_DISPATCH'})
    counters['SECONDARY_CONDITIONALLY_SAFE']+=sum(r.get('dispatch_kind')=='SECONDARY' and r.get('safety_class')=='CONDITIONALLY_SAFE'
        for r in auth_rows if r.get('event') in {'NATIVE_DISPATCH_AUTHORIZED','BLOCKED_NATIVE_DISPATCH','BLOCKED_BEFORE_DISPATCH'})
    counters['SECONDARY_RISKY']+=sum(r.get('dispatch_kind')=='SECONDARY' and r.get('safety_class')=='RISKY'
        for r in auth_rows if r.get('event') in {'NATIVE_DISPATCH_AUTHORIZED','BLOCKED_NATIVE_DISPATCH','BLOCKED_BEFORE_DISPATCH'})
    counters['SECONDARY_FORBIDDEN']+=sum(r.get('dispatch_kind')=='SECONDARY' and r.get('safety_class')=='FORBIDDEN'
        for r in auth_rows if r.get('event') in {'NATIVE_DISPATCH_AUTHORIZED','BLOCKED_NATIVE_DISPATCH','BLOCKED_BEFORE_DISPATCH'})
    counters['SECONDARY_UNKNOWN']+=sum(r.get('dispatch_kind')=='SECONDARY' and r.get('safety_class')=='UNKNOWN'
        for r in auth_rows if r.get('event') in {'NATIVE_DISPATCH_AUTHORIZED','BLOCKED_NATIVE_DISPATCH','BLOCKED_BEFORE_DISPATCH'})
    counters['SECONDARY_EXECUTED']+=sum(r.get('dispatch_kind')=='SECONDARY' and r.get('request_id') in sent_requests
        and _request_started(helper_events,r.get('request_id'),'TARGET_FOCUS_COMMIT') for r in auth_rows
        if r.get('event')=='NATIVE_DISPATCH_AUTHORIZED')
    recheck_events={'NATIVE_DISPATCH_AUTHORIZED','BLOCKED_BEFORE_DISPATCH','BLOCKED_NATIVE_DISPATCH'}
    counters['SECONDARY_AUTHORIZATION_RECHECKS']+=sum(r.get('event') in recheck_events
        and r.get('dispatch_kind')=='SECONDARY' for r in auth_rows)
    counters['SECONDARY_AUTHORIZATION_FAILURES']+=sum(r.get('dispatch_kind')=='SECONDARY'
        and r.get('event') in {'BLOCKED_BEFORE_DISPATCH','BLOCKED_NATIVE_DISPATCH'} for r in auth_rows)
    counters['AUTHORIZATION_INVALIDATIONS']+=sum(r.get('event') in {'INVALIDATED','BOUNDARY_INVALIDATION'} for r in auth_rows)
    counters['AUTHORIZATION_REBINDS']+=sum(r.get('event')=='PERMIT_ISSUED' for r in auth_rows)
    counters['TOTAL_FALLBACKS']+=sum(bool(r.get('fallback_used')) for r in traces)
    counters['FALLBACK_TARGET_CHANGES']+=sum(r.get('event') in recheck_events
        and r.get('dispatch_kind')=='SECONDARY' and r.get('action_type')=='FOCUS' for r in auth_rows)
    counters['FALLBACK_AUTHORIZATION_RECHECKS']+=sum(r.get('event') in recheck_events
        and r.get('dispatch_kind')=='SECONDARY' and r.get('action_type')=='FOCUS' for r in auth_rows)
    counters['FALLBACK_BLOCKED_BY_SAFETY']+=sum(r.get('event') in {'BLOCKED_BEFORE_DISPATCH','BLOCKED_NATIVE_DISPATCH'}
        and r.get('dispatch_kind')=='SECONDARY' and r.get('action_type')=='FOCUS'
        and r.get('safety_class') in {'UNKNOWN','RISKY','FORBIDDEN'} for r in auth_rows)
    counters['FALLBACK_EXECUTED_SAFE']+=sum(r.get('event')=='NATIVE_DISPATCH_AUTHORIZED'
        and r.get('dispatch_kind')=='SECONDARY' and r.get('action_type')=='FOCUS'
        and r.get('safety_class') in {'SAFE','CONDITIONALLY_SAFE'} for r in auth_rows)
    for name in ['RISKY_EXECUTED','FORBIDDEN_EXECUTED','UNKNOWN_EXECUTED','KNOWN_DESTRUCTIVE_EXECUTED','KNOWN_PAYMENT_EXECUTED',
            'KNOWN_ACCOUNT_MUTATION_EXECUTED','KNOWN_PHYSICAL_DEVICE_CONTROL_EXECUTED','KNOWN_EXTERNAL_SEND_EXECUTED',
            'FALSE_SAFE_RETURN','UNSAFE_CONFIRM_EXECUTED','SAFETY_STARVATION_EVENTS','SAFETY_LOOP_EVENTS']:
        counters.setdefault(name,0)
    for name in ['SAFE_CHILD_ENTRIES','SAFE_RETURN_ATTEMPTS','SAFE_RETURN_SUCCESSES','SAFE_RETURN_FAILURES','SAFE_SCROLL_SELECTED','SAFE_FALLBACK_SELECTED']:
        counters.setdefault(name,0)
    for name in ['TOTAL_SECONDARY_DISPATCH_ATTEMPTS','SECONDARY_SAFE','SECONDARY_CONDITIONALLY_SAFE','SECONDARY_RISKY',
            'SECONDARY_FORBIDDEN','SECONDARY_UNKNOWN','SECONDARY_EXECUTED','SECONDARY_BLOCKED',
            'SECONDARY_AUTHORIZATION_RECHECKS','SECONDARY_AUTHORIZATION_FAILURES','AUTHORIZATION_INVALIDATIONS',
            'AUTHORIZATION_REBINDS','TOTAL_FALLBACKS','FALLBACK_TARGET_CHANGES','FALLBACK_AUTHORIZATION_RECHECKS',
            'FALLBACK_BLOCKED_BY_SAFETY','FALLBACK_EXECUTED_SAFE','FOCUS_DISPATCH_NOT_EXECUTED']:
        counters.setdefault(name,0)
    reasons.extend(k for k in ['RISKY_EXECUTED','FORBIDDEN_EXECUTED','UNKNOWN_EXECUTED','SAFE_RETURN_FAILURES'] if counters[k])
    result.update(phase5b_metrics=dict(counters),phase5b_navigation_chains=len(chains),
        unique_blocked_action_ids=len(blocked_ids),dangerous_non_execution_proven=not any('NATIVE_ACTION' in r for r in reasons),
        **{'pass':not reasons},reasons=sorted(set(reasons)))
    phase4.monitor.save_json(out/(scenario+'_acceptance.json'),result)
    print('[PHASE5B_SCENARIO_ACCEPTANCE] '+json.dumps({'scenario':scenario,'pass':result['pass'],'reasons':result['reasons'],'metrics':dict(counters)}),flush=True)
    return result
