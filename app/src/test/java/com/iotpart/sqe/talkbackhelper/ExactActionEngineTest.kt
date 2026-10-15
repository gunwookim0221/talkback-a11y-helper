package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import java.io.File
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
class ExactActionEngineTest {
    private val context get()=RuntimeEnvironment.getApplication()
    private class Rig(val store:ExactActionStore,val request:JSONObject,val root:AccessibilityNodeInfo,
        val target:AccessibilityNodeInfo,val window:AccessibilityWindowInfo)
    private fun node(resource:String,label:String?,clickable:Boolean,window:AccessibilityWindowInfo):AccessibilityNodeInfo {
        val n=AccessibilityNodeInfo.obtain(View(context)).apply {
            packageName="com.example.smartthings";className="android.widget.Button";viewIdResourceName=resource
            text=label;isClickable=clickable;isFocusable=true;isEnabled=true;isVisibleToUser=true
            setBoundsInScreen(Rect(0,0,100,100))
            if(clickable)addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
        }
        shadowOf(n).setAccessibilityWindowInfo(window);shadowOf(n).setRefreshReturnValue(true)
        return n
    }
    private fun rig(beforeWrite:(String)->Unit={}):Rig {
        val store=ExactActionStore(context,"test-${UUID.randomUUID()}.db",beforeWrite);store.connect("boot:test")
        val request=ExactActionTestData.request(store)
        val window=AccessibilityWindowInfo.obtain();shadowOf(window).setId(7);shadowOf(window).setType(1);shadowOf(window).setActive(true)
        val target=node("com.example.smartthings:id/navigation","Open",true,window)
        val root=node("com.example.smartthings:id/root",null,false,window)
        shadowOf(root).addChild(target);shadowOf(window).setRoot(root)
        return Rig(store,request,root,target,window)
    }
    private fun resign(r:JSONObject) {
        val b=r.getJSONObject("binding")
        b.put("authorized_intent_digest",ExactProtocolJson.hash(b.getJSONObject("semantic_intent")))
        r.put("permit_mac",ExactActionContractTest().session(r).mac(b))
        r.put("request_digest",ExactActionContract.digestWithoutSelf(r))
    }
    private fun engine(r:Rig,build:Boolean=true,runtime:Boolean=true,ready:Boolean=true,buildId:String="b".repeat(64),
        provider:(()->List<ExactApplicationWindow>)?=null):ExactActionEngine {
        val resolver=ExactLiveNodeResolver(provider ?: {listOf(ExactApplicationWindow(7,1,true,r.root))})
        return ExactActionEngine(r.store,ExactActionContractTest().session(r.request),resolver,build,runtime,
            buildId,"synthetic:1",ExactActionReadiness(ready,ready,ready,ready))
    }
    @Test fun bothExplicitTestGatesCallOneValidatedMockNodeExactlyOnceWithoutVisitCredit() {
        val r=rig();shadowOf(r.target).setOnPerformActionListener{_,_->true}
        val ack=engine(r).execute(r.request.toString())
        assertEquals(ack.toString(),true,ack.opt("perform_action_return"))
        assertEquals(listOf(16),shadowOf(r.target).performedActions)
        assertTrue(shadowOf(r.root).performedActions.isEmpty())
        assertTrue(ack.getBoolean("permit_consumed"));assertEquals(1,ack.getInt("perform_action_call_count"))
        assertFalse(ack.getBoolean("action_effect_confirmed"));assertFalse(ack.getBoolean("expected_navigation_confirmed"))
        assertFalse(ack.getBoolean("visit_authority"))
        engine(r).execute(r.request.toString());assertEquals(1,shadowOf(r.target).performedActions.size)
        var rootDir=File(".").canonicalFile
        while(!File(rootDir,"settings.gradle.kts").exists())rootDir=rootDir.parentFile ?: error("root")
        File(rootDir,"app/build/reports/exact-protocol/mock-action-result.json").apply {
            parentFile.mkdirs();writeText(JSONObject().put("evidence_type","ROBOLECTRIC_MOCK_NODE").put("request",r.request).put("ack",ack).toString(2))
        }
        r.store.close()
    }
    @Test fun defaultMissingOldMalformedAndDisabledGatesNeverCall() {
        assertFalse(BuildConfig.BUILD_EXACT_ACTION_SUPPORT)
        val status=A11yCommandReceiver().buildPingPayload("test:gate-status").getJSONObject("exact_action_state")
        assertFalse(status.getBoolean("build_gate"));assertFalse(status.getBoolean("runtime_gate"));assertFalse(status.getBoolean("c5_ready"))
        for(local in listOf(null,JSONObject(),JSONObject().put("enabled",true),JSONObject().put("mode","old").put("enabled",true),
            JSONObject().put("mode",ExactActionContract.MODE).put("enabled","true")))assertFalse(ExactActionRuntimeConfig.parse(local).enabled)
        for(gates in listOf(false to true,true to false,false to false)) {
            val r=rig();engine(r,gates.first,gates.second).execute(r.request.toString())
            assertTrue(shadowOf(r.target).performedActions.isEmpty());r.store.close()
        }
        val r=rig();engine(r,buildId="UNKNOWN").execute(r.request.toString());assertTrue(shadowOf(r.target).performedActions.isEmpty());r.store.close()
    }
    @Test fun dangerousTargetsAndChangesCannotReachNativeAction() {
        for(kind in listOf("disabled","invisible","stale","wrong_package","wrong_window","actions_changed","child_changed",
            "duplicate","same_label","sibling","hard_stop","unknown","mixed","mutation","semantics","isolation","connection","stop_epoch","not_ready")) {
            val r=rig()
            when(kind) {
                "disabled"->r.target.isEnabled=false
                "invisible"->r.target.isVisibleToUser=false
                "stale"->shadowOf(r.target).setRefreshReturnValue(false)
                "wrong_package"->r.target.packageName="wrong.package"
                "wrong_window"->shadowOf(r.window).setId(99)
                "actions_changed"->r.target.removeAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
                "child_changed"->shadowOf(r.target).addChild(node("com.example.smartthings:id/mutation","Change state",true,r.window))
                "duplicate"->shadowOf(r.root).addChild(node("com.example.smartthings:id/navigation","Open",true,r.window))
                "same_label","sibling"->shadowOf(r.root).addChild(node("com.example.smartthings:id/independent","Open",true,r.window))
                "hard_stop"->r.store.stop("test")
                "connection"->r.store.connect("boot:test")
                "stop_epoch"->r.request.getJSONObject("binding").put("stop_epoch","stale")
                "unknown","mixed","mutation","semantics","isolation"->{
                    val intent=r.request.getJSONObject("binding").getJSONObject("semantic_intent")
                    when(kind) {
                        "unknown"->intent.put("target_class","UNKNOWN_ACTIONABLE")
                        "mixed"->intent.put("target_class","MIXED_ACTION_CONTAINER")
                        "mutation"->intent.put("target_class","STATE_MUTATION_CONTROL")
                        "semantics"->intent.put("semantic_approved",false)
                        "isolation"->intent.put("isolation_approved",false)
                    }
                    resign(r.request)
                }
            }
            val result=engine(r,ready=kind!="not_ready").execute(r.request.toString())
            assertTrue("$kind: $result",shadowOf(r.target).performedActions.isEmpty())
            r.store.close()
        }
    }
    @Test fun falseAndExceptionConsumeWithoutRetryOrEffectClaims() {
        for(throwing in listOf(false,true)) {
            val r=rig();shadowOf(r.target).setOnPerformActionListener{_,_->if(throwing)throw IllegalStateException("synthetic") else false}
            val ack=engine(r).execute(r.request.toString())
            assertTrue(ack.toString(),ack.optBoolean("permit_consumed"))
            assertEquals(if(throwing)"UNKNOWN_EXECUTION_STATE" else "PERFORM_ACTION_FALSE",ack.getString("failure_code"))
            engine(r).execute(r.request.toString());assertEquals(1,shadowOf(r.target).performedActions.size)
            assertFalse(ack.getBoolean("expected_navigation_confirmed"));r.store.close()
        }
    }
    @Test fun auditFailureBeforeClaimHasZeroCallsAndAfterCallIsUnknownWithoutRetry() {
        for(stage in listOf("TARGET_RESOLVED","DISPATCH_STARTED","PERFORM_ACTION_RESULT","ACK_PREPARED")) {
            var fail=false
            val r=rig { if(fail && it==stage)throw IllegalStateException("simulated journal failure") };fail=true
            shadowOf(r.target).setOnPerformActionListener{_,_->true}
            val ack=engine(r).execute(r.request.toString())
            val expected=if(stage in listOf("TARGET_RESOLVED","DISPATCH_STARTED"))0 else 1
            assertEquals("$stage: $ack",expected,shadowOf(r.target).performedActions.size)
            engine(r).execute(r.request.toString());assertEquals(expected,shadowOf(r.target).performedActions.size)
            r.store.close()
        }
    }
    @Test fun finalReferenceRevalidationRejectsLateChangeWithoutSubstitution() {
        val r=rig();var captures=0
        val provider={captures++;if(captures==2)r.target.isVisibleToUser=false;listOf(ExactApplicationWindow(7,1,true,r.root))}
        engine(r,provider=provider).execute(r.request.toString())
        assertTrue(shadowOf(r.target).performedActions.isEmpty());r.store.close()
    }
    @Test fun changedNodeAfterDurableClaimIsConsumedButNeverCalled() {
        var target:AccessibilityNodeInfo?=null
        val r=rig { if(it=="CONSUMED")target?.isEnabled=false };target=r.target
        val ack=engine(r).execute(r.request.toString())
        assertEquals("UNKNOWN_EXECUTION_STATE",ack.getString("execution_state"))
        assertTrue(ack.getBoolean("permit_consumed"));assertTrue(shadowOf(r.target).performedActions.isEmpty())
        engine(r).execute(r.request.toString());assertTrue(shadowOf(r.target).performedActions.isEmpty());r.store.close()
    }
    @Test fun refreshedMatchingDisabledOrInvisibleReferencesAreStillRejected() {
        for(disabled in listOf(true,false)) {
            val r=rig()
            val resolver=ExactLiveNodeResolver{listOf(ExactApplicationWindow(7,1,true,r.root))}
            val lease=resolver.capture(r.request.getJSONObject("resolve_request"),r.store.metadata("connection_epoch")!!)
            if(disabled){r.target.isEnabled=false;lease.node.isEnabled=false}
            else {r.target.isVisibleToUser=false;lease.node.isVisibleToUser=false}
            assertThrows(ExactActionRejected::class.java){lease.revalidate()}
            assertTrue(shadowOf(lease.node).performedActions.isEmpty());r.store.close()
        }
    }
}
