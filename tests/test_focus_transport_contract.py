import json
import subprocess
import threading
from types import SimpleNamespace

import pytest

from talkback_lib import A11yAdbClient, ACTION_FOCUS_IN_BOUNDS, ACTION_TARGET_FOCUS_COMMIT
from talkback_lib.helper_bridge import HelperBridge


@pytest.fixture
def client(monkeypatch):
    value = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(value, 'check_helper_status', lambda **kwargs: True)
    monkeypatch.setattr(HelperBridge, 'FOCUS_RESULT_WAIT_SECONDS', 1.0)
    monkeypatch.setattr(value, '_broadcast', lambda *args, **kwargs: 'Broadcast completed: result=0')
    return value


@pytest.fixture
def clock(monkeypatch):
    import talkback_lib
    state = [0.0]
    monkeypatch.setattr(talkback_lib.time, 'monotonic', lambda: state[0])
    monkeypatch.setattr(talkback_lib.time, 'sleep', lambda seconds: state.__setitem__(0, state[0] + seconds))
    return state


def payload(req_id, success=True, prefix='TARGET_ACTION_RESULT'):
    return prefix + ' ' + json.dumps({'reqId': req_id, 'success': success, 'reason': 'content_like_focused_row'})


def request(client, req_id='focus'):
    return client._helper_bridge.request_focus_command(None, ACTION_FOCUS_IN_BOUNDS, req_id, ['--es', 'reqId', req_id])


def test_delivery_and_focus_success(client, monkeypatch):
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: payload('focus'))
    result = request(client)
    assert result['success'] and result['reqId'] == 'focus'
    assert result['resultWaitStarted'] and result['resultWaitSeconds'] == 1.0


@pytest.mark.parametrize('action', [ACTION_FOCUS_IN_BOUNDS, ACTION_TARGET_FOCUS_COMMIT])
def test_strict_delivery_timeout_preserves_output_and_never_waits_or_retries(client, monkeypatch, action):
    monkeypatch.undo()
    client = A11yAdbClient(start_monitor=False)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs['timeout']))
        raise subprocess.TimeoutExpired(command, kwargs['timeout'], output=b'pending', stderr=b'delivery uncertain')
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(client, '_read_log_result', lambda *args, **kwargs: pytest.fail('No result credit after delivery failure'))
    result = client._helper_bridge.request_focus_command(None, action, 'timeout', ['--es', 'reqId', 'timeout'])
    assert result['reason'] == 'adb_command_timeout'
    assert not result['success'] and not result['resultWaitStarted']
    assert result['commandStdout'] == 'pending'
    assert result['commandStderr'] == 'delivery uncertain'
    assert len(calls) == 1 and calls[0][1] == 30.0


def test_nonzero_delivery_is_explicit(client, monkeypatch):
    monkeypatch.undo()
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='offline'))
    result = request(client)
    assert result['reason'] == 'adb_command_failed' and not result['success']


def test_delayed_result_independent_of_ack(client, monkeypatch, clock):
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: payload('focus') if clock[0] >= .4 else '')
    assert request(client)['success']
    assert .4 <= clock[0] < 1


def test_result_after_30s_boundary_within_75s_deadline(client, monkeypatch, clock):
    monkeypatch.setattr(HelperBridge, 'FOCUS_RESULT_WAIT_SECONDS', 75.0)
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: payload('focus') if clock[0] >= 30.454 else '')
    result = request(client)
    assert result['success'] and 30.454 <= clock[0] < 75
    assert result['deliveryElapsedSeconds'] == 0


def test_wrong_id_causes_result_timeout_without_credit(client, monkeypatch, clock):
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: payload('other'))
    result = request(client)
    assert not result['success'] and result['reason'] == 'focus_result_wait_timeout'
    assert result['reqId'] == 'focus'


def test_result_returned_after_deadline_rejected(client, monkeypatch, clock):
    def logs(**kwargs):
        clock[0] = 1.1
        return payload('focus')
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', logs)
    result = request(client)
    assert result['reason'] == 'late_focus_result' and not result['success']


def test_late_old_result_observed_once_not_reused(client, monkeypatch, clock):
    traces = []
    monkeypatch.setattr(client, '_safe_trace_print', traces.append)
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: '')
    assert request(client, 'old')['reason'] == 'focus_result_wait_timeout'
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: payload('old')+'\n'+payload('new', False))
    result = request(client, 'new')
    assert result['reqId'] == 'new' and not result['success']
    client._helper_bridge.observe_late_focus_results(payload('old'))
    assert sum('[FOCUS_TRANSPORT] late_result req_id=old' in line for line in traces) == 1


def test_duplicate_terminal_result_is_integrity_failure(client, monkeypatch):
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: payload('focus')+'\n'+payload('focus'))
    result = request(client)
    assert result['reason'] == 'duplicate_terminal_result' and not result['success']


def test_duplicate_request_does_not_execute_again(client, monkeypatch):
    sends = []
    monkeypatch.setattr(client, '_broadcast', lambda *args: sends.append(args) or 'ACK')
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: payload('focus'))
    assert request(client)['success']
    assert request(client)['reason'] == 'duplicate_focus_request_id'
    assert len(sends) == 1


def test_public_focus_does_not_retry_missing_result(client, monkeypatch, clock):
    sends = []
    monkeypatch.setattr(client, '_broadcast', lambda *args: sends.append(args) or 'ACK')
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: '')
    result = client.focus_in_bounds(bounds='[0,0][100,100]', wait_=100)
    assert not result['success'] and len(sends) == 1
    assert client.last_target_action_result['reason'] == 'focus_result_wait_timeout'


def test_smart_and_focus_simultaneous_ids_and_pending_results_not_cleared(client, monkeypatch):
    barrier = threading.Barrier(2)
    result = {}
    clears = []
    monkeypatch.setattr(client._adb_device, '_clear_logcat_best_effort', lambda **kwargs: clears.append(True))
    def broadcast(*args, **kwargs):
        barrier.wait(timeout=2)
        client.clear_logcat()
        return 'ACK'
    monkeypatch.setattr(client, '_broadcast', broadcast)
    logs = payload('smart', prefix='SMART_NAV_RESULT')+'\n'+payload('focus')
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: logs)
    threads = [threading.Thread(target=lambda: result.update(smart=client._helper_bridge._request_smart_next(None,'smart'))),
               threading.Thread(target=lambda: result.update(focus=request(client)))]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=3)
    assert all(not thread.is_alive() for thread in threads)
    assert result['smart']['reqId'] == 'smart' and result['focus']['reqId'] == 'focus'
    assert result['smart']['success'] and result['focus']['success'] and not clears


def test_target_focus_commit_uses_same_transport_without_changing_descriptor(client, monkeypatch):
    commands = []
    def broadcast(dev, action, extras):
        commands.append((action, extras))
        return 'ACK'
    monkeypatch.setattr(client, '_broadcast', broadcast)
    monkeypatch.setattr(client, '_read_log_result', lambda dev,prefix,rid,**kwargs: {'reqId':rid,'success':True,'status':'TARGET_MATCHED'})
    result = client._target_focus_commit_impl(target={'bounds':'[1,2][3,4]','label':'exact','resource_id':'id/exact','class_name':'Button'})
    assert result['status'] == 'TARGET_MATCHED'
    action, extras = commands[0]
    assert action == ACTION_TARGET_FOCUS_COMMIT
    assert extras[extras.index('targetId')+1] == "'id/exact'"
    assert extras[extras.index('bounds')+1] == "'[1,2][3,4]'"


def test_focus_timeout_remains_an_explicit_failed_evidence_event(client, monkeypatch, clock):
    events = []
    client.evidence_runtime = SimpleNamespace(emit=lambda kind, **kwargs: events.append((kind, kwargs)))
    client._evidence_active_transaction = {'phase':'recovery', 'transaction_id':'tx'}
    monkeypatch.setattr(client, '_evidence_is_enabled', lambda: True)
    monkeypatch.setattr(client, '_evidence_action_sent', lambda **kwargs: None)
    monkeypatch.setattr(client, '_evidence_correlation_extras', lambda: [])
    monkeypatch.setattr(client, '_evidence_helper_ack', lambda *args, **kwargs: None)
    monkeypatch.setattr(client._logcat_reader, 'dump_filtered', lambda **kwargs: '')
    assert not client.focus_in_bounds(bounds='[0,0][100,100]')['success']
    api_result = [kwargs['payload'] for kind, kwargs in events if kind == 'ACTION_API_RESULT']
    assert len(api_result) == 1
    assert api_result[0]['success'] is False
    assert api_result[0]['reason'] == 'focus_result_wait_timeout'
