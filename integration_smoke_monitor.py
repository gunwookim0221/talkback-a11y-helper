import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from tools.full32_acceptance_monitor import AcceptanceMonitor
OUT=Path('../smoke_context_focus_20261011').resolve();OUT.mkdir(exist_ok=True)
SERIAL='R3CX40QFDBP'
def adb(*args):return subprocess.check_output(['adb','-s',SERIAL,*args],text=True,timeout=15).strip()
start=datetime.now(timezone.utc)
tb=adb('shell','pidof','com.samsung.android.accessibility.talkback')
helper=adb('shell','pidof','com.iotpart.sqe.talkbackhelper')
precheck=dict(time=start.isoformat(),serial=SERIAL,locale=adb('shell','getprop','persist.sys.locale'),talkback_pid=tb,helper_pid=helper,
    accessibility_services=adb('shell','settings','get','secure','enabled_accessibility_services'),
    foreground=adb('shell','dumpsys','window'),helper_package=adb('shell','pm','path','com.iotpart.sqe.talkbackhelper'),
    smartthings_package=adb('shell','pm','path','com.samsung.android.oneconnect'))
(OUT/'precheck.json').write_text(json.dumps(precheck,indent=2),encoding='utf-8')
assert tb and helper and 'talkback' in precheck['accessibility_services'] and 'talkbackhelper' in precheck['accessibility_services']
assert precheck['helper_package'].startswith('package:') and precheck['smartthings_package'].startswith('package:')
assert precheck['locale'], precheck
monitor=AcceptanceMonitor(start,talkback_pid=tb,helper_pid=helper)
lc=open(OUT/'logcat.txt','wb'); runner=open(OUT/'runner.log','wb')
logcat=subprocess.Popen(['adb','-s',SERIAL,'logcat','-v','threadtime','-T','1'],stdout=lc,stderr=subprocess.STDOUT)
run_env=os.environ.copy();run_env['TB_TALKBACK_PREFLIGHT_PID']=tb
process=subprocess.Popen([sys.executable,'integration_smoke.py'],stdout=runner,stderr=subprocess.STDOUT,env=run_env)
offsets={'runner':0,'logcat':0};pending={'runner':'','logcat':''};hits=[];helper_changes=0
with (OUT/'monitor.jsonl').open('w',encoding='utf-8') as samples:
    while True:
        for source in offsets:
            with (OUT/('runner.log' if source=='runner' else 'logcat.txt')).open('rb') as f:
                f.seek(offsets[source]);data=f.read();offsets[source]=f.tell()
            chunk=pending[source]+data.decode('utf-8',errors='replace');lines=chunk.split('\n');pending[source]=lines.pop()
            for line in lines:
                hits.extend(monitor.feed_line(line,source=source,observed_at=datetime.now(timezone.utc)))
        current_tb=adb('shell','pidof','com.samsung.android.accessibility.talkback')
        current_helper=adb('shell','pidof','com.iotpart.sqe.talkbackhelper')
        hits.extend(monitor.observe_talkback_pid(current_tb,observed_at=datetime.now(timezone.utc)))
        if current_helper!=helper:helper_changes+=1
        sample=dict(timestamp=datetime.now(timezone.utc).isoformat(),talkback_pid=current_tb,helper_pid=current_helper,
            hard_blockers=[dict(code=h.code,evidence=h.evidence) for h in hits])
        samples.write(json.dumps(sample)+'\n');samples.flush()
        if hits or helper_changes:
            process.terminate();print('HARD_RUNTIME_STOP',sample,flush=True);break
        if process.poll() is not None:break
        time.sleep(5)
process.wait();logcat.terminate();logcat.wait();lc.close();runner.close()
result=dict(start_time=start.isoformat(),end_time=datetime.now(timezone.utc).isoformat(),return_code=process.returncode,
    helper_pid_change_count=helper_changes,hits=[dict(code=h.code,evidence=h.evidence) for h in hits])
(OUT/'monitor_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result),flush=True)
raise SystemExit(process.returncode or bool(hits) or bool(helper_changes))
