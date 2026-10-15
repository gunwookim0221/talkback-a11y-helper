"""C5 preserved evidence replay and measured offline cost. No device access.

Historical logs lack C4 permits/cursors. They stay unowned; no ownership is fabricated.
Synthetic positive and actual JVM mock export are reported separately.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import time

from talkback_lib.exact_action_journal import DurableActionJournal
from talkback_lib.exact_post_action import (PostActionVerifier, structural_probe, destination_matches,
    correlate, digest, normalize, verify_helper_export)
from tools.exact_c5_fixture import fixture, export, ROOT


def historical_event(path: Path, token: str):
    for number,line in enumerate(path.read_text(encoding='utf-8',errors='replace').splitlines(),1):
        if 'TYPE_VIEW_CLICKED;' in line and token in line:
            t=re.search(r'EventTime: (\d+)',line)
            package=re.search(r'PackageName: ([^;]+)',line)
            text=re.search(r'Text: \[([^]]*)\]',line)
            return dict(raw_line=line,event_type=1,event_uptime_ms=int(t.group(1)),
                package=package.group(1),text=text.group(1).split(', ') if text else [],
                source_identity=None,source_provenance='HISTORICAL_SOURCE_UNAVAILABLE',
                source_ref={'path':str(path.relative_to(ROOT)), 'line':number,'file_sha256':digest_bytes(path.read_bytes())},
                helper_receive_uptime_ms=None,helper_connection_epoch=None,event_sequence=None)
    raise ValueError(f'보존 이벤트를 찾지 못함: {path.name}/{token}')


def digest_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def main(output:Path):
    output.mkdir(parents=True,exist_ok=True)
    request,records=fixture();cursor=records[1][1]
    historical=[]
    for name,path,token in [
        ('historical_stay','out/phase5c_clothing_care_rca_20261014/full32/31_life_home_monitor_plugin/logcat.txt','Text: [Armed, Stay]'),
        ('historical_insufficient_source','out/phase5c_entry_fix_20261014/full32/31_life_home_monitor_plugin/logcat.txt','Text: [Home Monitor]')]:
        raw=historical_event(ROOT/path,token)
        c=correlate(raw,cursor,request,100)
        assert c['result']!='STRONG_MATCH'
        entry={'name':name,'raw':raw,'correlation':c,'navigation_confirmed':False,
               'c4_dispatch_ownership':'UNAVAILABLE','result':'UNKNOWN_EXECUTION_STATE',
               'forbidden_semantic_observation':bool(set(raw['text']).intersection(['Away','Stay','Disarmed']))}
        # Preserve raw historical input in the same durable host audit, as diagnostics only.
        journal=DurableActionJournal(output/f'{name}.jsonl')
        journal.append('C5_HISTORICAL_RAW_EVENT',request,entry)
        v=PostActionVerifier(journal,request)
        assert v.finalize()['result']=='UNKNOWN_EXECUTION_STATE'
        historical.append(entry)
    # Delay case uses original eventTime; no invented receive timestamp/ownership.
    delay=deepcopy(historical[1]);delay['name']='historical_delayed_event'
    delay['raw']['original_return_vs_log_evidence']='보존 RCA: 17:46:26.265 수집 요청, 26.325 이벤트 로그; EventTime 별도'
    historical.append(delay)

    b3=ROOT/'out/phase5d_b3_helper_refresh_20261015/resume2/capture_B_raw.json'
    raw=json.loads(b3.read_text(encoding='utf-8'))
    if 'hierarchy' in raw:raw=raw['hierarchy']
    # Actual B3 service hierarchy is the source screen, not a proven destination.
    begin=time.perf_counter_ns();probe=structural_probe(raw,[]);probe_ns=time.perf_counter_ns()-begin
    assert probe['read_succeeded'], 'B3 구조를 실제로 읽을 수 있어야 함'
    source_contract=deepcopy(cursor['destination_contract'])
    source_contract.update(expected_package=probe['package'],required_root_signatures=[probe['root_signature']],
        source_screen_signatures=[probe['root_signature']],required_structures=probe['structures'][:1],
        required_markers=['text:Home Monitor'])
    probe.update(activity='example.Destination',context='destination')
    assert 'text:Home Monitor' in probe['markers']
    assert not destination_matches(probe,source_contract)

    positive=PostActionVerifier(DurableActionJournal(output/'positive.jsonl'),request)
    positive.import_evidence(export(request,records));positive_result=positive.finalize()
    assert positive_result['expected_navigation_confirmed']
    before=positive.journal.path.read_bytes();assert positive.replay()['expected_navigation_confirmed']
    assert before==positive.journal.path.read_bytes()

    interoperability=[]
    for filename in ('post-action-export.json','c4-c5-integration.json'):
        data=json.loads((ROOT/'app/build/reports/exact-protocol'/filename).read_text(encoding='utf-8'))
        helper=verify_helper_export(data['helper_export'])
        for r in helper:
            if r['event_type']=='C5_STRUCTURAL_PROBE':
                p=r['payload'];selectors=list(p['security_state'])
                derived=structural_probe(p['raw_hierarchy'],selectors,data['request']['resolve_request']['target_identity']['resource_id'])
                assert all(p.get(k)==v for k,v in derived.items())
        verifier=PostActionVerifier(DurableActionJournal(output/(filename+'.jsonl')),data['request'])
        verifier.import_evidence(data['helper_export']);result=verifier.finalize()
        assert result['expected_navigation_confirmed']==(filename=='c4-c5-integration.json'),result
        interoperability.append(dict(file=filename,evidence_type=data['evidence_type'],result=result['result'],
            row_count=len(helper),action_dispatch_confirmed=result['action_dispatch_confirmed'],
            action_effect_confirmed=result['action_effect_confirmed'],navigation_confirmed=result['expected_navigation_confirmed']))

    event=records[6][1];event['event_sequence']=7
    begin=time.perf_counter_ns()
    for _ in range(1000):correlate(event,cursor,request,100)
    correlation_ns=(time.perf_counter_ns()-begin)//1000
    report=dict(historical=historical,b3_source_screen_excluded=True,b3_probe_node_count=len(probe['structures']),
        b3_source_sha256=digest_bytes(b3.read_bytes()),synthetic_positive=positive_result['result'],
        actual_python_kotlin_interoperability=interoperability,false_navigation_confirm_count=0,
        performance=dict(events_per_synthetic_transaction=1,event_serialization_bytes=len(json.dumps(event).encode()),
            correlation_mean_ns=correlation_ns,b3_probe_ns=probe_ns,
            completed_host_audit_bytes=positive.journal.path.stat().st_size,
            helper_export_bytes=len(json.dumps(export(request,records)).encode())),
        live_action_executed=False,scenario31_retried=False,scenario32_started=False)
    (output/'replay_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='historical'},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.output)
