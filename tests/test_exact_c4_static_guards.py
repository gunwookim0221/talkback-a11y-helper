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
        current=(ROOT/path).read_bytes().replace(b'\r\n',b'\n')
        if path == 'tb_runner/phase5b_navigation.py':
            # RF4R and CL-01 permit only exact read-only transport paths.
            # Strip those reviewed additions so every other byte of
            # safety/visit authority remains frozen against the baseline.
            anchor=b'    def command_allowed(self, command):\n'
            lifecycle_addition=(b'        from talkback_lib.window_lifecycle import is_lifecycle_readonly_command\n'
                                b'        if is_lifecycle_readonly_command(command):\n'
                                b'            return True\n')
            assert current.count(anchor+lifecycle_addition)==1
            current=current.replace(anchor+lifecycle_addition,anchor,1)

            def strip_once(block):
                nonlocal current
                assert current.count(block)==1
                current=current.replace(block,b'',1)

            strip_once(
                b'_HIERARCHY_TRANSFER_PREFIX = "com.iotpart.sqe.talkbackhelper.HIERARCHY_TRANSFER_"\n'
                b'_HIERARCHY_TRANSFER_OPERATIONS = {\n'
                b'    "CAPABILITIES", "START", "STATUS", "ACK", "CANCEL",\n'
                b'}\n'
                b'_HIERARCHY_EVIDENCE_EXTRAS = {\n'
                b'    "evidenceRunId", "evidenceScenarioTxId", "evidenceTransactionId",\n'
                b'    "evidenceAttemptId", "evidenceLogicalActionId",\n'
                b'}\n'
                b'_HEX32 = re.compile(r"^[0-9a-f]{32}$")\n'
                b'_HEX40 = re.compile(r"^[0-9a-f]{40}$")\n'
                b'_HEX64 = re.compile(r"^[0-9a-f]{64}$")\n'
                b'_HIERARCHY_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")\n'
                b'_HIERARCHY_PROVIDER_AUTHORITY = "com.iotpart.sqe.talkbackhelper.hierarchy"\n'
            )
            spacing=(b'BUDGETS = {s: 20 if s in {"life_food_plugin", "device_camera_plugin"} else 10 for s in SCENARIOS}\n'
                     b'\n\n\nclass SafetyBlocked(RuntimeError):')
            assert current.count(spacing)==1
            current=current.replace(spacing,spacing.replace(b'\n\n\n\nclass',b'\n\n\nclass'),1)
            strip_once(
                b'        self._phase5_hierarchy_capabilities_seen = False\n'
                b'        self._phase5_hierarchy_request = None\n'
            )
            method_start=current.index(b'    @staticmethod\n    def _hierarchy_broadcast_extras(')
            method_end=current.index(anchor,method_start)
            assert method_end>method_start
            current=current[:method_start]+current[method_end:]
            strip_once(
                b'        if words[:3] == ["shell", "am", "broadcast"]:\n'
                b'            action = words[4] if len(words) > 4 and words[3] == "-a" else ""\n'
                b'            if action.startswith(_HIERARCHY_TRANSFER_PREFIX):\n'
                b'                contract = self._phase5_hierarchy_command(words, commit=True)\n'
                b'                return bool(contract and contract.get("valid"))\n'
                b'        if words == ["shell", "am", "get-current-user"]:\n'
                b'            return True\n'
                b'        if self._phase5_hierarchy_payload_command(words):\n'
                b'            return True\n'
            )
            strip_once(
                b'        hierarchy_read_callback_name = "_phase5b_authorize_hierarchy_payload_read"\n'
                b'        hierarchy_read_callback_had = hierarchy_read_callback_name in vars(client)\n'
                b'        hierarchy_read_callback_prior = vars(client).get(hierarchy_read_callback_name)\n'
                b'        setattr(client, hierarchy_read_callback_name, self.authorize_hierarchy_payload_read)\n'
                b'        saved.append((client, hierarchy_read_callback_name,\n'
                b'                      hierarchy_read_callback_had, hierarchy_read_callback_prior))\n'
            )
            strip_once(
                b'        for callback_name, callback in (\n'
                b'            ("_phase5b_complete_hierarchy_ack", self.complete_hierarchy_ack),\n'
                b'            ("_phase5b_finish_hierarchy_cancel", self.finish_hierarchy_cancel),\n'
                b'        ):\n'
                b'            callback_had = callback_name in vars(client)\n'
                b'            callback_prior = vars(client).get(callback_name)\n'
                b'            setattr(client, callback_name, callback)\n'
                b'            saved.append((client, callback_name, callback_had, callback_prior))\n'
            )
            wrapper_addition=(b'                if name != "_run":\n'
                              b'                    result = original(command, *args, **kwargs)\n'
                              b'                    self._phase5_note_hierarchy_success([str(word) for word in command])\n'
                              b'                    return result\n')
            assert current.count(wrapper_addition)==1
            current=current.replace(
                wrapper_addition,
                b'                if name != "_run":\n'
                b'                    return original(command, *args, **kwargs)\n',
                1,
            )
            strip_once(
                b'        # Reliable hierarchy payload retrieval is binary and bypasses _run;\n'
                b'        # keep it under the same Phase5 command guard as control broadcasts.\n'
                b'        install(getattr(client, "_adb_device", None), "_run_adb_binary_command")\n'
            )
        normalized_baseline=baseline.replace(b'\r\n',b'\n')
        if normalized_baseline!=current:
            mismatch=next((index for index,(left,right) in enumerate(zip(normalized_baseline,current))
                           if left!=right),min(len(normalized_baseline),len(current)))
            raise AssertionError((path,mismatch,
                normalized_baseline[max(0,mismatch-8):mismatch+16].hex(),
                current[max(0,mismatch-8):mismatch+16].hex()))

def test_generic_runtime_has_no_home_monitor_label_or_resource_rule():
    for path in list(SRC.glob('ExactAction*.kt'))+[SRC/'ExactLiveNodeResolver.kt']:
        text=path.read_text(encoding='utf-8')
        for marker in ('Home Monitor','monitorHeaderGroup','serviceCardBody','shmBanner','life_home_monitor'):
            assert marker not in text
