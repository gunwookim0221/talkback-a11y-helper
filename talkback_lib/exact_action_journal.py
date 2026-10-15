"""Mandatory, failure-propagating C4 host journal. Never resends an action."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from typing import Any
from .exact_node_protocol import canonical_json
from .exact_action import ActionRejected
from .exact_action import TrustedActionSession

class DurableActionJournal:
    def __init__(self,path:str|Path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self._lock=threading.RLock()

    @contextmanager
    def _exclusive(self):
        with self._lock, self.path.with_suffix(self.path.suffix+'.lock').open('a+b') as lock:
            lock.seek(0,os.SEEK_END)
            if not lock.tell():lock.write(b'0');lock.flush()
            lock.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:yield
            finally:
                lock.seek(0)
                if os.name=='nt':msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)

    def _read(self):
        raw=self.path.read_bytes() if self.path.exists() else b''
        if raw and not raw.endswith(b'\n'):raise ActionRejected('AUDIT_PERSIST_FAILED:partial_record')
        records=[];previous='0'*64
        try:
            for sequence,line in enumerate(raw.splitlines(),1):
                row=json.loads(line);checksum=row.pop('record_hash')
                if row['sequence']!=sequence or row['previous_hash']!=previous or checksum!=hashlib.sha256(canonical_json(row).encode()).hexdigest():
                    raise ValueError('chain')
                row['record_hash']=checksum;records.append(row);previous=checksum
        except (ValueError,KeyError,TypeError) as exc:raise ActionRejected('AUDIT_PERSIST_FAILED:corrupt_record') from exc
        return records

    def records(self):
        with self._exclusive():return self._read()

    def append(self,event_type:str,request:dict[str,Any],evidence:dict[str,Any]|None=None):
        b=request['binding']
        with self._exclusive():
            rows=self._read()
            if event_type=='REQUEST_PREPARED':
                for row in rows:
                    if row['event_type']=='REQUEST_PREPARED' and any(row[k]==b[k] for k in ('request_id','permit_id','request_nonce','transaction_id')):
                        raise ActionRejected('REQUEST_REPLAYED')
            row=dict(schema='talkback.exact-action.host-journal.v1',sequence=len(rows)+1,
                timestamp_ms=time.time_ns()//1_000_000,monotonic_ns=time.monotonic_ns(),
                previous_hash=rows[-1]['record_hash'] if rows else '0'*64,event_type=event_type,
                request_id=b['request_id'],transaction_id=b['transaction_id'],permit_id=b['permit_id'],request_nonce=b['request_nonce'],
                ownership=b['ownership'],request_digest=request['request_digest'],evidence=evidence or {},visit_authority=False)
            row['record_hash']=hashlib.sha256(canonical_json(row).encode()).hexdigest()
            payload=(canonical_json(row)+'\n').encode('utf-8')
            fd=os.open(self.path,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
            try:
                if os.write(fd,payload)!=len(payload):raise OSError('partial audit write')
                os.fsync(fd)
            finally:os.close(fd)
            if os.name!='nt':
                parent=os.open(self.path.parent,os.O_RDONLY)
                try:os.fsync(parent)
                finally:os.close(parent)
            return row

    def unresolved_transactions(self):
        """Diagnostics only. An outstanding prepare is NEVER an instruction to resend."""
        rows=self.records()
        finished={r['transaction_id'] for r in rows if r['event_type']=='TRANSACTION_CLOSED'}
        return {r['transaction_id']:'UNKNOWN_EXECUTION_STATE' for r in rows
                if r['event_type']=='REQUEST_PREPARED' and r['transaction_id'] not in finished}

    def prepare(self,request:dict,session:TrustedActionSession,now_ms:int)->str:
        """Return immutable bytes only after mandatory durable preparation. No transport here."""
        packet=json.loads(canonical_json(request))
        session.verify(packet,now_ms)
        self.append('AUTHORIZATION_RECORDED',packet,{'authorized_intent_digest':packet['binding']['authorized_intent_digest']})
        self.append('PERMIT_CREATED',packet,{'permit_mac_verified':True})
        self.append('REQUEST_PREPARED',packet)
        return canonical_json(packet)
