"""Validate saved smoke inputs against the final planner without device actions."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from tb_runner.canonical_json import canonical_json
from tb_runner.discovery_candidates import DiscoveryActionCandidate, DiscoverySnapshot
from tb_runner.phase4a_planner import PlannerInput, ProductionHistory, plan_shadow
from tools.phase4a_shadow_smoke import SCENARIOS


def restore_snapshot(document):
    candidates = tuple(DiscoveryActionCandidate(c['candidate_id'], c['state_id'], c['action_kind'], canonical_json(c))
                       for c in document['candidates'])
    return DiscoverySnapshot(document['state_id'], document['candidate_set_hash'], candidates, canonical_json(document))


def validate(root: Path):
    monitor = json.loads((root / 'monitor_result.json').read_text(encoding='utf-8'))
    assert monitor['scenarios_completed'] == 6 and not monitor['smoke_stopped']
    assert all(v == 0 for v in monitor['lifecycle_gates'].values())
    observations = [json.loads(line) for line in (root / 'phase4a_observations.jsonl').read_text(encoding='utf-8').splitlines()]
    traces = [json.loads(line) for line in (root / 'phase4a_shadow_trace.jsonl').read_text(encoding='utf-8').splitlines()]
    steps = [r for r in observations if r['kind'] == 'PRE_PRODUCTION_STEP']
    assert len(steps) == len(traces) == 30
    for scenario in SCENARIOS:
        assert [r['step'] for r in steps if r['scenario'] == scenario] == list(range(1, 6))
        assert [r['step'] for r in traces if r['scenario'] == scenario] == list(range(1, 6))
        assert len([r for r in observations if r['scenario'] == scenario and r['kind'] == 'ENTRY_TO_TRAVERSAL']) == 1
    for row in steps:
        document = row['history'].copy()
        for key in ('attempts', 'visits', 'last_attempt_steps'):
            document[key] = tuple(tuple(x) for x in document[key])
        for key in ('recent_attempts', 'stale_ids'):
            document[key] = tuple(document[key])
        if document['allowed_instance_ids'] is not None:
            document['allowed_instance_ids'] = tuple(document['allowed_instance_ids'])
        value = PlannerInput(restore_snapshot(row['snapshot']), row['context']['status'],
                             ProductionHistory(**document), **row['planner_flags'])
        first = plan_shadow(value)
        assert first.to_json() == plan_shadow(value).to_json()
        assert first.to_dict() == row['recommendation'], (row['scenario'], row['step'])
    assert all(not r['action_executed_by_planner'] and not r['production_visit_authority'] and r['visit_credit'] == 0 for r in traces)
    result = dict(status='PASS', final_planner_exact_replay=30, entry_failures=0,
                  lifecycle_gates=monitor['lifecycle_gates'], scenarios={s: dict(
                      steps=5, contexts=dict(Counter(r['context_status'] for r in traces if r['scenario'] == s)),
                      shadow_actions=dict(Counter(r['shadow_action'] for r in traces if r['scenario'] == s)),
                      comparisons=dict(Counter(r['match_classification'] for r in traces if r['scenario'] == s))) for s in SCENARIOS},
                  execution_authority=False, visit_authority=False)
    (root / 'shadow_validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('root', type=Path)
    print(json.dumps(validate(parser.parse_args().root)))
