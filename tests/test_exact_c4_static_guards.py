from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'app/src/main/java/com/iotpart/sqe/talkbackhelper'

def test_exact_action_has_one_direct_native_call_and_no_fallback_or_focus():
    paths=list(SRC.glob('ExactAction*.kt'))+[SRC/'ExactLiveNodeResolver.kt']
    code='\n'.join(p.read_text(encoding='utf-8') for p in paths)
    assert code.count('.performAction(')==1
    assert 'node.performAction(AccessibilityNodeInfo.ACTION_CLICK)' in code
    for forbidden in ('ACTION_FOCUS','ACTION_ACCESSIBILITY_FOCUS','CLICK_TARGET','CLICK_FOCUSED',
                      'A11yTargetFinder','dispatchGesture(','.touch(','.tap('):
        assert forbidden not in code

def test_default_build_runtime_and_c5_gates_remain_off():
    gradle=(ROOT/'app/build.gradle.kts').read_text(encoding='utf-8')
    runtime=(SRC/'ExactActionRuntime.kt').read_text(encoding='utf-8')
    assert 'buildConfigField("boolean", "BUILD_EXACT_ACTION_SUPPORT", "false")' in gradle
    assert 'private var config=ExactActionRuntimeConfig()' in runtime
    assert 'private var trustedSession:ExactActionSession?=null' in runtime
    assert 'BuildConfig.HELPER_BUILD_ID,version,ExactActionReadiness()' in runtime
    receiver=(SRC/'A11yCommandReceiver.kt').read_text(encoding='utf-8')
    assert 'configureTrustedLocalSession' not in receiver

def test_physical_owner_and_production_visit_authority_sources_are_unchanged():
    for path in ('tb_runner/entry_safety.py','tb_runner/phase5b_navigation.py','tb_runner/phase5c_hard_stop.py',
                 'tb_runner/target_attempt_ledger.py'):
        baseline=subprocess.run(['git','show',f'f7f0903d98d0233c3ea5aac2ff5f8e43b85bbd7a:{path}'],
            cwd=ROOT,capture_output=True,check=True).stdout
        assert baseline.replace(b'\r\n',b'\n')==(ROOT/path).read_bytes().replace(b'\r\n',b'\n')

def test_generic_runtime_has_no_home_monitor_label_or_resource_rule():
    for path in list(SRC.glob('ExactAction*.kt'))+[SRC/'ExactLiveNodeResolver.kt']:
        text=path.read_text(encoding='utf-8')
        for marker in ('Home Monitor','monitorHeaderGroup','serviceCardBody','shmBanner','life_home_monitor'):
            assert marker not in text
