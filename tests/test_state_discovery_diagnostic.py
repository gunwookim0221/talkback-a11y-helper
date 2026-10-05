import json
from pathlib import Path
import subprocess
import sys

import pytest

from state_model_fixtures import observation
from tb_runner.state_observation import build_state_observation
from tb_runner.state_registry import StateRegistry
from tools import state_discovery_diagnostic


def run_cli(tmp_path,input_value,*,extra=(),fingerprint=False):
    source=tmp_path/'input.json';source.write_text(json.dumps(input_value),encoding='utf-8')
    root=Path(__file__).resolve().parents[1]
    output=tmp_path/'discovery_candidates.jsonl';registry=tmp_path/'registry.json'
    result=subprocess.run([sys.executable,'-m','tools.state_discovery_diagnostic',
        '--fingerprint-input' if fingerprint else '--input',str(source),
        '--output',str(output),'--registry-out',str(registry),*extra],cwd=root,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    return [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()],registry,json.loads(result.stdout.strip())


def test_offline_cli_repeats_and_restart_mapping(tmp_path):
    snapshots,registry,counts=run_cli(tmp_path,[observation()]*3)
    assert counts['snapshots']==counts['resolved']==3
    assert counts['auto_activation'] is False and counts['visit_credit']==0
    assert len({s['state_id'] for s in snapshots})==len({s['candidate_set_hash'] for s in snapshots})==1
    loaded=StateRegistry.load(registry)
    assert loaded.state_count==1 and loaded.observation_count==3
    again,registry,counts=run_cli(tmp_path,observation(),extra=['--registry-in',str(registry)])
    assert len(again)==4 and again[-1]['state_id']==snapshots[0]['state_id']
    assert again[-1]['candidate_set_hash']==snapshots[0]['candidate_set_hash']


def test_offline_cli_unknown_state_retains_null_binding(tmp_path):
    raw=observation();raw['activity_name']=None
    snapshots,registry,counts=run_cli(tmp_path,raw)
    assert snapshots[0]['state_id'] is None and counts['unresolved']==1
    assert all(c['state_id'] is None for c in snapshots[0]['candidates'])
    assert StateRegistry.load(registry).state_count==0


def test_fingerprint_only_cli_is_unresolved(tmp_path):
    fp=build_state_observation(observation()).fingerprint.to_dict()
    snapshots,registry,counts=run_cli(tmp_path,fp,fingerprint=True)
    assert counts['unresolved']==1 and counts['candidates']==0
    assert snapshots[0]['fingerprint_hash']==fp['fingerprint_hash']


def test_explicit_capture_path_observes_without_actions(tmp_path,monkeypatch,capsys):
    import talkback_lib
    from tools import state_fingerprint_diagnostic
    calls=[]
    class Client:
        def __init__(self,**kwargs): calls.append(('construct',kwargs))
        def touch_point(self,*a,**k): raise AssertionError('Unexpected click')
        def move_focus_smart(self,*a,**k): raise AssertionError('Unexpected move')
        def scroll(self,*a,**k): raise AssertionError('Unexpected scroll')
    def capture(client,serial,**kwargs):
        calls.append(('capture',serial,kwargs));return observation()
    monkeypatch.setattr(talkback_lib,'A11yAdbClient',Client)
    monkeypatch.setattr(state_fingerprint_diagnostic,'capture_observation',capture)
    monkeypatch.setattr(sys,'argv',['discovery','--capture','--serial','device',
        '--output',str(tmp_path/'snapshots.jsonl'),'--registry-out',str(tmp_path/'registry.json')])
    assert state_discovery_diagnostic.main()==0
    assert len(calls)==2 and calls[1][0]=='capture'
    assert json.loads(capsys.readouterr().out)['auto_activation'] is False


def test_input_capture_exclusive_and_required_outputs(monkeypatch):
    monkeypatch.setattr(sys,'argv',['discovery','--capture','--input','x'])
    with pytest.raises(SystemExit):state_discovery_diagnostic.main()
