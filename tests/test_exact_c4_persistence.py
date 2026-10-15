from concurrent.futures import ThreadPoolExecutor
import os
import pytest
from talkback_lib.exact_action import ActionRejected
from talkback_lib.exact_action_journal import DurableActionJournal
from test_exact_c4_models import sample
from test_exact_c4_models import NOW

def test_host_fsync_journal_survives_reopen_and_never_resends(tmp_path):
    _,r=sample();path=tmp_path/'action.jsonl';j=DurableActionJournal(path)
    j.append('REQUEST_PREPARED',r)
    assert DurableActionJournal(path).unresolved_transactions()=={r['binding']['transaction_id']:'UNKNOWN_EXECUTION_STATE'}
    with pytest.raises(ActionRejected):DurableActionJournal(path).append('REQUEST_PREPARED',r)
    j.append('ACK_RECEIVED',r,{'perform_action_return':True})
    assert len(j.records())==2
    j.append('TRANSACTION_CLOSED',r)
    assert not j.unresolved_transactions()

@pytest.mark.parametrize('failure',['fsync','partial','disk_full'])
def test_host_audit_failure_is_not_swallowed(tmp_path,monkeypatch,failure):
    _,r=sample();j=DurableActionJournal(tmp_path/'audit.jsonl')
    def bad(*args):raise OSError('simulated disk full / sync failure')
    if failure=='fsync':monkeypatch.setattr(os,'fsync',bad)
    elif failure=='disk_full':monkeypatch.setattr(os,'write',bad)
    else:
        real=os.write
        monkeypatch.setattr(os,'write',lambda fd,data:real(fd,data[:7]))
    with pytest.raises(OSError):j.append('REQUEST_PREPARED',r)

def test_partial_and_corrupted_records_poison_reopen(tmp_path):
    _,r=sample();path=tmp_path/'audit.jsonl';j=DurableActionJournal(path);j.append('REQUEST_PREPARED',r)
    original=path.read_bytes();path.write_bytes(original[:-1])
    with pytest.raises(ActionRejected):j.records()
    path.write_bytes(original.replace(b'REQUEST_PREPARED',b'REQUEST_REPLACED'))
    with pytest.raises(ActionRejected):j.records()

def test_concurrent_process_style_writers_cannot_duplicate_prepare(tmp_path):
    _,r=sample();path=tmp_path/'audit.jsonl'
    def write(_):
        try:DurableActionJournal(path).append('REQUEST_PREPARED',r);return True
        except (ActionRejected,OSError):return False
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(write,range(12)))==1
    assert len(DurableActionJournal(path).records())==1

def test_prepared_packet_is_returned_only_after_durable_writes(tmp_path,monkeypatch):
    session,r=sample();j=DurableActionJournal(tmp_path/'packet.jsonl')
    assert j.prepare(r,session,NOW)
    assert [v['event_type'] for v in j.records()]==['AUTHORIZATION_RECORDED','PERMIT_CREATED','REQUEST_PREPARED']
    fail=DurableActionJournal(tmp_path/'failure.jsonl')
    def bad(*_):raise OSError('sync failure')
    monkeypatch.setattr(os,'fsync',bad)
    with pytest.raises(OSError):fail.prepare(r,session,NOW)
