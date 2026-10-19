from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tb_runner.entry_mode import (
    AUTOMATED, PREPOSITIONED, PrepositionedSafetyStop, PrepositionedSession,
    verify_destination,
)
from tb_runner.run_spec import RunSpec

PKG = "example.app"
ACTIVITY = "topResumedActivity=ActivityRecord{abc u0 example.app/.DetailActivity t1}"
WINDOW = "mCurrentFocus=Window{abc u0 example.app/.DetailActivity}"
CONTRACT = dict(package=PKG, activity_regex=r"example\.app\.DetailActivity",
                required_resource_ids=["body", "controls"],
                semantic_marker=dict(resource_id="section", text_regex="Security"),
                excluded_resource_ids=["source_life"], invariant_resource_ids=["state"])


def snapshot():
    children = [dict(packageName=PKG, viewIdResourceName=rid, text=text,
                     visibleToUser=True, childIndex=i, children=[])
                for i, (rid, text) in enumerate((('body', ''), ('controls', ''),
                                                 ('section', 'Security'), ('state', 'Disarmed')))]
    root = dict(packageName=PKG, visibleToUser=True, children=children)
    return dict(success=True, reqId="fresh-request", nodes=[root],
                windows=[dict(active=True, focused=True, root=root)])


class Client:
    def __init__(self):
        self.calls = []
        self._adb_device = SimpleNamespace(command_guard=None)
        self.state = snapshot()
        self.activity = ACTIVITY
        self.window = WINDOW
        self.power = "mWakefulness=Awake"
        self.policy = "showing=false"
        self.enabled = True
        self.identity = dict(status="EXACT_MATCH", compatibility_status="EXACT_MATCH", execution_allowed=True,
                             helper_service_instance_id="helper-service",
                             capability_service_instance_id="helper-service", exact_action_state=dict(
            build_gate=False, runtime_gate=False, c5_ready=False, helper_stopped=True))
        self.services = "com.iotpart.sqe.talkbackhelper/com.iotpart.sqe.talkbackhelper.A11yHelperService"

    def _run(self, args, dev=None):
        if self._adb_device.command_guard:
            self._adb_device.command_guard(args)
        self.calls.append(tuple(args))
        return {('get-state',): 'device',
                ('shell', 'dumpsys', 'activity', 'activities'): self.activity,
                ('shell', 'dumpsys', 'window'): self.window,
                ('shell', 'dumpsys', 'power'): self.power,
                ('shell', 'dumpsys', 'window', 'policy'): self.policy,
                ('shell', 'pidof', 'com.samsung.android.accessibility.talkback'): '123',
                ('shell', 'settings', 'get', 'secure', 'enabled_accessibility_services'): self.services}[tuple(args)]

    def dump_hierarchy(self, dev=None):
        observer = getattr(self, 'hierarchy_observer', None)
        if observer:
            observer(self.state)
        return deepcopy(self.state)

    def is_talkback_enabled(self, dev=None):
        return self.enabled

    def precheck_helper_build_identity(self, dev=None, acceptance_mode=True):
        assert acceptance_mode is True
        return self.identity


@pytest.fixture
def setup(tmp_path):
    client = Client()
    config = dict(scenario_id="any_plugin", entry_mode=PREPOSITIONED,
                  prepositioned_destination=deepcopy(CONTRACT))
    session = PrepositionedSession(client, config, tmp_path/'entry.jsonl', lambda _: None)
    session.bind()
    return client, config, session


def test_default_mode_ignores_environment_and_existing_cli_is_unchanged(monkeypatch):
    monkeypatch.setenv('TB_ENTRY_MODE', PREPOSITIONED)
    assert RunSpec().entry_mode == AUTOMATED
    assert '--entry-mode' not in RunSpec().build_script_command('script_test.py')
    spec = RunSpec(entry_mode=PREPOSITIONED, scenario_ids=('any_plugin',))
    assert spec.optional_expansions == 'DISABLED'
    command = spec.build_script_command('script_test.py')
    assert command[command.index('--entry-mode')+1] == PREPOSITIONED
    assert command[command.index('--optional-expansions')+1] == 'DISABLED'


def test_optional_expansion_policy_is_scoped_to_prepositioned_mode():
    assert RunSpec().optional_expansions == 'ENABLED'
    assert RunSpec(entry_mode=PREPOSITIONED, scenario_ids=('one',),
                   optional_expansions='ENABLED').optional_expansions == 'ENABLED'
    with pytest.raises(ValueError, match='only be disabled'):
        RunSpec(optional_expansions='DISABLED')


def test_prepositioned_optional_expansion_enabled_keeps_existing_overlay_path(setup, monkeypatch):
    from tb_runner import collection_flow as flow

    client, config, session = setup
    session.destination = dict(component=(PKG, 'example.app.DetailActivity'))
    config.update(scenario_id='life_home_monitor_plugin', tab_name='Life',
                  plugin_more_options_enabled=True, entry_mode=PREPOSITIONED,
                  optional_expansions='ENABLED')
    node = dict(packageName=PKG, className='android.widget.ImageView',
                contentDescription='More options', clickable=True, focusable=True,
                enabled=True, visibleToUser=True, boundsInScreen='900,20,1040,150',
                children=[])
    root = dict(packageName=PKG, className='android.widget.FrameLayout',
                viewIdResourceName='screen_root', visibleToUser=True,
                boundsInScreen='0,0,1080,2400', children=[node])
    row = dict(step_index=1, visible_label='Home Monitor', focus_view_id='body',
               dump_tree_nodes=[root])
    calls = []
    expected = flow.OverlayPhaseResult(True, 'existing_overlay_path', 'plugin_more_options', 0)

    def existing_path(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(flow, '_execute_overlay_for_candidate', existing_path)
    result = flow._overlay_phase(
        client=client, dev='SERIAL', tab_cfg=config, row=row, rows=[], all_rows=[],
        output_path='unused.xlsx', output_base_dir='.', scenario_perf=None,
        main_step_index_by_fingerprint={}, expanded_overlay_entries=set(),
        skipped_optional_expansion_scopes=set())

    assert result is expected
    assert len(calls) == 1
    assert not any('CLICK_TARGET' in call for call in client.calls)


def test_prepositioned_more_options_skip_is_audited_before_any_action_and_scoped(setup, monkeypatch):
    from tb_runner import collection_flow as flow

    client, config, session = setup
    session.destination = dict(component=(PKG, 'example.app.DetailActivity'))
    config.update(scenario_id='life_home_monitor_plugin', tab_name='Life',
                  plugin_more_options_enabled=True, entry_mode=PREPOSITIONED,
                  optional_expansions='DISABLED')
    monkeypatch.setattr(flow, 'log', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flow, '_execute_overlay_for_candidate',
                        lambda **_kwargs: pytest.fail('optional skip entered dispatch preparation'))

    def traversal_row(extra_id=''):
        root = dict(packageName=PKG, className='android.widget.FrameLayout',
            viewIdResourceName='screen_root', visibleToUser=True,
            boundsInScreen='0,0,1080,2400', children=[
                dict(packageName=PKG, className='android.widget.TextView',
                    viewIdResourceName='screen_title', text='Home Monitor',
                    visibleToUser=True, boundsInScreen='20,20,500,120', children=[]),
                dict(packageName=PKG, className='android.widget.Button',
                    viewIdResourceName='shmBannerAwayButton', text='Arm away',
                    clickable=True, focusable=True, visibleToUser=True,
                    boundsInScreen='20,400,500,600', children=[]),
                dict(packageName=PKG, className='android.widget.ImageView',
                    contentDescription='More options', clickable=True, focusable=True,
                    enabled=True, visibleToUser=True, boundsInScreen='900,20,1040,150',
                    children=[]),
            ])
        if extra_id:
            root['children'].append(dict(packageName=PKG, className='android.widget.TextView',
                viewIdResourceName=extra_id, text='Additional section', visibleToUser=True,
                boundsInScreen='20,700,500,800', children=[]))
        return dict(step_index=1, visible_label='Arm away', focus_view_id='shmBannerAwayButton',
            focus_class_name='android.widget.Button', focus_bounds='20,400,500,600',
            focus_node=root['children'][1], dump_tree_nodes=[root])

    row = traversal_row()
    skipped = set()
    kwargs = dict(client=client, dev='SERIAL', tab_cfg=config, row=row, rows=[], all_rows=[],
        output_path='unused.xlsx', output_base_dir='.', scenario_perf=None,
        main_step_index_by_fingerprint={}, expanded_overlay_entries=set(),
        skipped_optional_expansion_scopes=skipped)
    first = flow._overlay_phase(**kwargs)
    second = flow._overlay_phase(**kwargs)
    assert first.classification == 'optional_expansion_skipped'
    assert first.optional_expansion_skip['dispatch_attempted'] is False
    assert first.optional_expansion_skip['visit_credit'] is False
    assert first.optional_expansion_skip['transition_credit'] is False
    assert first.optional_expansion_skip['execution_credit'] is False
    assert second.classification == 'optional_expansion_already_skipped'
    assert len(skipped) == 1
    assert not any('CLICK_TARGET' in call for call in client.calls)

    other_screen = traversal_row(extra_id='other_screen_section')
    other_kwargs = {**kwargs, 'row': other_screen}
    other = flow._overlay_phase(**other_kwargs)
    assert other.classification == 'optional_expansion_skipped'
    assert len(skipped) == 2

    events = [json.loads(line) for line in session.audit_path.read_text(encoding='utf-8').splitlines()]
    skip_events = [event for event in events if event['event'] == 'OPTIONAL_ACTION_SKIPPED']
    assert len(skip_events) == 2
    for event in skip_events:
        assert event['action_requirement'] == 'OPTIONAL_EXPANSION'
        assert event['decision'] == 'SKIPPED'
        assert event['skip_reason'] == 'PREPOSITIONED_EXPANSIONS_DISABLED'
        assert event['dispatch_attempted'] is False
        assert event['visit_credit'] is False
        assert event['transition_credit'] is False
        assert event['execution_credit'] is False
        assert event['coverage_impact'] is True


def test_optional_expansion_continuation_audit_is_explicit(setup):
    _, _, session = setup
    skip = dict(skip_id='skip-1', scope_id='scope-1')
    session.record_optional_expansion_continued(skip=skip, continued=True,
                                                step_index=2, reason='next_traversal_step_started')
    event = json.loads(session.audit_path.read_text(encoding='utf-8').splitlines()[-1])
    assert event['event'] == 'OPTIONAL_ACTION_SKIP_CONTINUATION'
    assert event['traversal_continued'] is True
    assert event['continuation_step'] == 2
    assert event['dispatch_attempted'] is False


@pytest.mark.parametrize('ids', [(), ('a', 'b')])
def test_prepositioned_requires_one_explicit_scenario(ids):
    with pytest.raises(ValueError):
        RunSpec(entry_mode=PREPOSITIONED, scenario_ids=ids)


@pytest.mark.parametrize('mode', ['', 'current', 'prepositioned', 'UNKNOWN'])
def test_invalid_mode_cannot_silently_become_automated(mode):
    with pytest.raises(ValueError):
        RunSpec(entry_mode=mode)


def test_prepositioned_does_not_admit_a_second_exploratory_probe():
    with pytest.raises(ValueError, match='second exploratory'):
        RunSpec(entry_mode=PREPOSITIONED, scenario_ids=('any_plugin',), enable_coverage_probe=True)


def test_generic_destination_requires_component_structure_and_semantic_evidence():
    result = verify_destination(CONTRACT, activity=ACTIVITY, window=WINDOW, snapshot=snapshot())
    assert result['verdict'] == 'PASS'
    assert result['source_screen_excluded'] is True
    assert result['snapshot_request_id'] == 'fresh-request'


@pytest.mark.parametrize('change,expected', [
    ('title_only', 'FAIL'), ('wrong_activity', 'FAIL'), ('wrong_focus', 'FAIL'),
    ('source_screen', 'FAIL'), ('hidden_marker', 'FAIL'), ('missing_semantic', 'FAIL'),
    ('missing_component', 'AMBIGUOUS'), ('multiple_windows', 'AMBIGUOUS'),
    ('invalid_hierarchy', 'AMBIGUOUS'), ('missing_contract', 'AMBIGUOUS'),
])
def test_destination_failures_are_closed(change, expected):
    data = snapshot(); activity = ACTIVITY; window = WINDOW; contract = CONTRACT
    children = data['windows'][0]['root']['children']
    if change == 'title_only':
        children[:] = [dict(packageName=PKG, text='Home Monitor', viewIdResourceName='title')]
    elif change == 'wrong_activity': activity = ACTIVITY.replace('DetailActivity', 'LifeActivity')
    elif change == 'wrong_focus': window = WINDOW.replace('DetailActivity', 'OtherActivity')
    elif change == 'source_screen': children.append(dict(packageName=PKG, viewIdResourceName='source_life'))
    elif change == 'hidden_marker': children[0]['visibleToUser'] = False
    elif change == 'missing_semantic': children[2]['text'] = 'Home Monitor'
    elif change == 'missing_component': activity = ''
    elif change == 'multiple_windows': data['windows'].append(deepcopy(data['windows'][0]))
    elif change == 'invalid_hierarchy': data['success'] = False
    elif change == 'missing_contract': contract = None
    assert verify_destination(contract, activity=activity, window=window, snapshot=data)['verdict'] == expected


def test_prepositioned_preflight_is_read_only_and_does_not_probe_focus(setup):
    from tb_runner.core_preflight import run_preflight
    client, _, session = setup
    result = run_preflight(client=client, serial='S', log_fn=lambda _: None, entry_mode=PREPOSITIONED,
                           adb_runner=lambda *a, **kw: pytest.fail('mutating legacy preflight reached'))
    assert result.ok
    assert result.unlock_swipe['action_attempted'] is False
    assert result.app_foreground['launch_attempted'] is False
    assert session.phase == 'READ_ONLY'
    assert not any('input' in command or 'monkey' in command or 'broadcast' in command for command in client.calls)


@pytest.mark.parametrize('failure', ['locked', 'unknown_lock', 'asleep', 'talkback_off', 'helper_mismatch',
                                      'active_transaction', 'exact_gate_on', 'helper_disabled'])
def test_preflight_failures_never_fall_back_or_move_focus(setup, failure):
    from tb_runner.core_preflight import run_preflight
    client, _, session = setup
    if failure == 'locked': client.policy = 'showing=true'
    elif failure == 'unknown_lock': client.policy = ''
    elif failure == 'asleep': client.power = 'mWakefulness=Asleep'
    elif failure == 'talkback_off': client.enabled = False
    elif failure == 'helper_mismatch':
        client.identity.update(status='REBUILD_REQUIRED', compatibility_status='REBUILD_REQUIRED', execution_allowed=False)
    elif failure == 'active_transaction': client._evidence_active_transaction = {'id': 'stale'}
    elif failure == 'exact_gate_on': client.identity['exact_action_state']['runtime_gate'] = True
    elif failure == 'helper_disabled': client.services = ''
    result = run_preflight(client=client, serial='S', log_fn=lambda _: None, entry_mode=PREPOSITIONED)
    assert not result.ok
    assert session.phase == 'READ_ONLY'
    assert not any('input' in command or 'monkey' in command for command in client.calls)


def test_real_open_boundary_skips_all_entry_paths_and_uses_existing_anchor(setup, monkeypatch):
    from tb_runner import collection_flow as flow
    client, config, session = setup
    for name in ('_verify_fresh_life_list_state', 'stabilize_tab_selection', '_run_pre_navigation_steps'):
        monkeypatch.setattr(flow, name, lambda *a, **kw: pytest.fail('automated entry reached'))
    calls = []
    monkeypatch.setattr(flow, 'stabilize_anchor', lambda **kw: calls.append(kw) or dict(ok=True, matched=True))
    assert flow.open_scenario(client, 'S', config)
    assert len(calls) == 1 and calls[0]['phase'] == 'prepositioned_start'
    assert session.phase == 'TRAVERSAL'
    summary = client.last_start_open_summary
    assert summary['entry_action_executed'] is False
    assert summary['pre_navigation_attempted'] is False
    assert summary['pre_navigation_success'] is False
    assert summary['trusted_entry_verified'] is False
    assert 'visit_credit' not in summary


@pytest.mark.parametrize('verdict', ['FAIL', 'AMBIGUOUS'])
def test_open_failure_never_calls_anchor_or_automated_entry(setup, monkeypatch, verdict):
    from tb_runner import collection_flow as flow
    client, config, session = setup
    monkeypatch.setattr(session, 'verify', lambda *a, **kw: dict(verdict=verdict, reason='fixture'))
    monkeypatch.setattr(flow, 'stabilize_anchor', lambda **kw: pytest.fail('traversal started'))
    monkeypatch.setattr(flow, '_run_pre_navigation_steps', lambda **kw: pytest.fail('entry fallback'))
    assert flow.open_scenario(client, 'S', config) is False
    assert session.phase == 'READ_ONLY'


def test_recovery_is_a_terminal_stop_not_an_entry_retry(setup):
    from tb_runner.collection_flow import recover_to_start_state
    client, config, _ = setup
    with pytest.raises(PrepositionedSafetyStop, match='automated_recovery_forbidden'):
        recover_to_start_state(client, 'S', config)
    assert not client.calls


def broadcast(name, *extra):
    return ['shell', 'am', 'broadcast', '-a', 'com.iotpart.sqe.talkbackhelper.'+name, '-p',
            'com.iotpart.sqe.talkbackhelper', *extra]


@pytest.mark.parametrize('command', [
    broadcast('CLICK_TARGET'), broadcast('CLICK_FOCUSED'), broadcast('TOUCH_BOUNDS_CENTER_TARGET'),
    broadcast('ENTRY_CLICK_CAPTURE'), broadcast('ACTION_COMMAND', '--es', 'command', 'activate'),
    ['shell', 'input', 'tap', '500', '500'], ['shell', 'input', 'keyevent', '4'],
    ['shell', 'monkey', '-p', PKG, '1'], ['shell', 'am', 'start', '-n', PKG+'/.DetailActivity'],
    ['shell', 'am', 'force-stop', PKG], ['shell', 'settings', 'put', 'secure', 'anything', '1'],
    ['shell', 'echo ok; input tap 1 1'], ['shell', 'cmd', 'device_state', 'state', '1'],
])
def test_activation_and_navigation_blocked_before_dispatch_and_latched(setup, command):
    _, _, session = setup
    session.destination = {'verdict': 'PASS'}; session.begin_traversal()
    with pytest.raises(PrepositionedSafetyStop): session.guard_command(command)
    with pytest.raises(PrepositionedSafetyStop): session.guard_command(broadcast('NEXT'))
    assert session.latched_reason


def test_direct_adb_tap_cannot_bypass_interlock(setup, monkeypatch):
    from talkback_lib.adb_device import AdbDevice
    _, _, session = setup
    device = AdbDevice('adb', lambda dev: 'S'); device.command_guard = session.guard_command
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: pytest.fail('device dispatch occurred'))
    with pytest.raises(PrepositionedSafetyStop): device._tap('S', 1, 1)


def test_safety_stop_bypasses_ordinary_recovery_handlers(setup):
    _, _, session = setup
    with pytest.raises(PrepositionedSafetyStop):
        try: session.guard_command(broadcast('CLICK_TARGET'))
        except Exception: pytest.fail('ordinary recovery swallowed safety stop')


def test_safety_stop_permits_only_passive_evidence_finalization(setup, tmp_path):
    from tb_runner.evidence import EvidenceRuntime
    client, _, session = setup
    runtime = EvidenceRuntime(output_path=tmp_path/'output.xlsx')
    runtime.start_scenario('any_plugin')
    transaction = runtime.begin_transaction('TARGET_FOCUS_COMMIT', phase='main_loop')
    runtime.emit('ACTION_SENT', producer='runner', phase='main_loop', transaction=transaction,
                 payload=dict(request_id='prior-focus-request'))
    runtime.emit('HELPER_ACK_RECEIVED', producer='runner', phase='main_loop', transaction=transaction,
                 payload=dict(request_id='prior-focus-request', success=True))
    original_events = [e.to_dict() for e in runtime._all_events]
    client.evidence_runtime = runtime
    client._evidence_active_transaction = transaction
    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(broadcast('CLICK_TARGET', '--es', 'reqId', 'blocked-click-request'))
    session.guard_command(['logcat', '-d', 'A11Y_HELPER:V'])
    session.guard_command(broadcast('EVIDENCE_EVENTS'))
    with pytest.raises(PrepositionedSafetyStop): session.guard_command(broadcast('SCROLL'))
    runtime.add_finalize_hook(lambda: session.guard_command(['logcat', '-d']))
    session.finalize_stop(row_count=2)
    report = runtime.finalize()
    assert runtime.reconciliation_path.is_file()
    assert report['terminal_reason'] == 'SAFETY_STOP'
    assert runtime._transactions[transaction['transaction_id']]['state'] == 'closed'
    events = [json.loads(line) for line in runtime.ledger.path.read_text(encoding='utf-8').splitlines()]
    blocked = next(e for e in events if e['event_type']=='ACTION_DISPATCH_BLOCKED')
    assert blocked['payload']['executed'] is False
    assert blocked['payload']['visit_credit'] is False
    assert blocked['payload']['request_id'] == 'blocked-click-request'
    assert blocked['transaction_id'] != transaction['transaction_id']
    child = next(e for e in events if e['event_type']=='TRANSACTION_OPENED'
                 and e['transaction_id']==blocked['transaction_id'])
    assert child['parent_transaction_id'] == transaction['transaction_id']
    sent = [e for e in events if e['event_type']=='ACTION_SENT']
    assert len(sent)==1 and sent[0]['payload']['request_id']=='prior-focus-request'
    assert [e.to_dict() for e in runtime._all_events[:len(original_events)]] == original_events
    parent_close = next(e for e in events if e['event_type']=='TRANSACTION_CLOSED'
                        and e['transaction_id']==transaction['transaction_id'])
    assert parent_close['payload']['status']=='safety_stopped'
    assert 'executed' not in parent_close['payload']
    assert not any(e['event_type']=='VISIT_DECIDED' for e in events)
    assert client._evidence_active_transaction is None


def test_focus_is_allowed_only_after_verified_handoff_and_audit_is_append_only(setup):
    _, _, session = setup
    session.verify('S', stage='fixture')
    session.begin_traversal()
    session.guard_command(broadcast('SMART_NEXT'))
    session.guard_command(broadcast('FOCUS_TARGET'))
    session.guard_command(broadcast('SCROLL'))
    rows = [json.loads(line) for line in session.audit_path.read_text(encoding='utf-8').splitlines()]
    assert [r['sequence'] for r in rows] == list(range(1, len(rows)+1))
    assert next(i for i,r in enumerate(rows) if r['event']=='POST_ENTRY_HANDOFF') < next(
        i for i,r in enumerate(rows) if r.get('kind')=='focus_or_scroll')
    assert all(r['entry_action_executed'] is False for r in rows)


def test_focus_before_destination_verification_is_blocked(setup):
    _, _, session = setup
    with pytest.raises(PrepositionedSafetyStop): session.guard_command(broadcast('NEXT'))


def test_focus_state_does_not_look_like_security_mutation_but_value_change_stops(setup):
    _, _, session = setup
    data = snapshot(); session.observe_hierarchy(data)
    node = data['windows'][0]['root']['children'][-1]
    node.update(accessibilityFocused=True, focused=True)
    session.observe_hierarchy(data)
    node['text'] = 'Armed stay'
    with pytest.raises(PrepositionedSafetyStop, match='visible_destination_state_changed'):
        session.observe_hierarchy(data)


def test_missing_contract_never_becomes_fake_success(setup):
    _, _, session = setup
    session.contract = None
    assert session.verify('S', stage='fixture')['verdict'] == 'AMBIGUOUS'
    with pytest.raises(PrepositionedSafetyStop): session.begin_traversal()


def test_scenario31_status_remains_supplemental_and_other_scenarios_not_modified():
    from tb_runner.scenario_config import TAB_CONFIGS
    config = next(c for c in TAB_CONFIGS if c['scenario_id'] == 'life_home_monitor_plugin')
    assert config['pre_navigation'][0]['action'] == 'xml_scroll_search_tap'
    assert 'entry_mode' not in config
    assert all('entry_mode' not in c for c in TAB_CONFIGS)
    canonical = json.loads((Path(__file__).resolve().parents[1] /
                           'docs/design/talkback-phase5-final-closure-20261017.json').read_text(encoding='utf-8'))
    row = next(c for c in canonical['scenarios'] if c['scenario_id'] == 31)
    assert row['status'] == 'INCOMPLETE_SAFETY_LIMIT'
    assert row['counts_as_pass'] is False


def test_automated_open_uses_the_existing_entry_path(monkeypatch):
    from tb_runner import collection_flow as flow
    from tb_runner.scenario_config import TAB_CONFIGS
    class ExistingEntryReached(Exception): pass
    def existing(*args, **kwargs): raise ExistingEntryReached()
    monkeypatch.setattr(flow, '_verify_fresh_life_list_state', existing)
    config = deepcopy(next(c for c in TAB_CONFIGS if c['scenario_id']=='life_home_monitor_plugin'))
    with pytest.raises(ExistingEntryReached):
        flow.open_scenario(SimpleNamespace(), 'S', config)
