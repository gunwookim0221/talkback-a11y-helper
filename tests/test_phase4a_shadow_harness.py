import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools import phase4a_shadow_smoke as smoke
from state_model_fixtures import observation


@pytest.mark.parametrize('failure', [False, True])
def test_explicit_harness_restores_production_functions_and_argv(tmp_path, monkeypatch, failure):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'scenarios': {'home_main': {'max_steps': 5}}}))
    monkeypatch.setenv('TB_RUNTIME_CONFIG_PATH', str(config))
    monkeypatch.setenv('TB_PHASE4A_SMOKE_SCENARIO', 'home_main')
    monkeypatch.setenv('TB_PHASE4A_SMOKE_OUT', str(tmp_path))
    monkeypatch.setattr(smoke, 'A11yAdbClient', lambda **kwargs: object())
    names = ('_main_loop_phase', '_apply_step_collection_phase', '_apply_row_persistence_phase')
    original = {name: getattr(smoke.collection_flow, name) for name in names}
    argv = sys.argv

    def run(*args, **kwargs):
        assert all(getattr(smoke.collection_flow, name) is not original[name] for name in names)
        # An inactive wrapper forwards precisely the original production arguments.
        monkeypatch.setattr(smoke, 'capture_observation', lambda *a, **k: pytest.fail('unexpected I/O'))
        if failure:
            raise RuntimeError('simulated runner failure')
        raise SystemExit(0)

    monkeypatch.setattr(smoke.runpy, 'run_path', run)
    if failure:
        with pytest.raises(RuntimeError, match='simulated runner failure'):
            smoke.main()
    else:
        assert smoke.main() == 0
    assert sys.argv is argv
    assert all(getattr(smoke.collection_flow, name) is original[name] for name in names)


def test_harness_rejects_unbounded_configuration(tmp_path, monkeypatch):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'scenarios': {'home_main': {'max_steps': 100}}}))
    monkeypatch.setenv('TB_RUNTIME_CONFIG_PATH', str(config))
    monkeypatch.setenv('TB_PHASE4A_SMOKE_SCENARIO', 'home_main')
    monkeypatch.setenv('TB_PHASE4A_SMOKE_OUT', str(tmp_path))
    with pytest.raises(ValueError, match='five-step'):
        smoke.main()


def test_each_observation_forwards_original_arguments_without_decision_authority(tmp_path, monkeypatch):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'scenarios': {'home_main': {'max_steps': 5}}}))
    for key, value in {'TB_RUNTIME_CONFIG_PATH': str(config), 'TB_PHASE4A_SMOKE_SCENARIO': 'home_main',
                       'TB_PHASE4A_SMOKE_OUT': str(tmp_path)}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(smoke, 'A11yAdbClient', lambda **kwargs: object())
    monkeypatch.setattr(smoke, 'capture_observation', lambda *a, **k: deepcopy(observation()))
    monkeypatch.setattr(smoke, 'phase3_entry_evidence_from_main_loop', lambda *a: {})
    state, client = SimpleNamespace(), SimpleNamespace()
    phase = SimpleNamespace(all_rows=[])
    arguments = dict(step_idx=1, state=state, client=client, dev='mock-device', phase_ctx=phase,
                     tab_cfg={}, scenario_id='home_main')
    persisted = dict(step_idx=1, row={'move_result': 'MOVED'}, marker=object())
    called = []

    def original_step(**kwargs):
        assert kwargs == arguments
        assert kwargs['state'] is state and kwargs['client'] is client
        called.append('step')
        return 'production-result'

    def original_persist(**kwargs):
        assert kwargs == persisted
        called.append('persist')
        return False, ''

    def original_loop(received_client, dev, received_phase):
        assert received_client is client and received_phase is phase
        assert smoke.collection_flow._apply_step_collection_phase(**arguments) == 'production-result'
        assert smoke.collection_flow._apply_row_persistence_phase(**persisted) == (False, '')
        return 'original-loop-result'

    monkeypatch.setattr(smoke.collection_flow, '_main_loop_phase', original_loop)
    monkeypatch.setattr(smoke.collection_flow, '_apply_step_collection_phase', original_step)
    monkeypatch.setattr(smoke.collection_flow, '_apply_row_persistence_phase', original_persist)
    monkeypatch.setattr(smoke.runpy, 'run_path', lambda *a, **k:
                        smoke.collection_flow._main_loop_phase(client, 'mock-device', phase))
    assert smoke.main() == 0
    assert called == ['step', 'persist'] and vars(state) == {} and vars(client) == {}
    trace = json.loads((tmp_path / 'phase4a_shadow_trace.jsonl').read_text())
    assert trace['visit_credit'] == 0 and trace['action_executed_by_planner'] is False
