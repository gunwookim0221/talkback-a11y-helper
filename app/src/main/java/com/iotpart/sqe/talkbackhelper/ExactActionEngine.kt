package com.iotpart.sqe.talkbackhelper

import android.os.SystemClock
import org.json.JSONObject
import java.time.Instant

internal data class ExactActionReadiness(val hostStopInactive:Boolean=false,val observation:Boolean=false,
    val destination:Boolean=false,val forbiddenDetector:Boolean=false)

/** Only unit tests inject enabled gates/readiness. Runtime C4 supplies neither a session nor C5 readiness. */
internal class ExactActionEngine(private val store:ExactActionStore,private val session:ExactActionSession?,
    private val resolver:ExactLiveNodeResolver,private val buildGate:Boolean=false,private val runtimeGate:Boolean=false,
    private val buildId:String,private val appVersion:String,private val readiness:ExactActionReadiness=ExactActionReadiness(),
    private val postActionPlan:ExactPostActionPlan?=null) {

    fun execute(raw:String):JSONObject {
        if(raw.toByteArray(Charsets.UTF_8).size>1024*1024)return unavailable("REQUEST_INVALID")
        if(ExactNodeResolver.hasDuplicateJsonKey(raw))return unavailable("REQUEST_INVALID")
        val request=runCatching { JSONObject(raw) }.getOrElse{return unavailable("REQUEST_INVALID")}
        if(!store.busy.compareAndSet(false,true))return unavailable("CONCURRENT_ACTION")
        try { return synchronized(store.executionLock) { executeLocked(request) } }
        catch(error:Exception) { return unavailable(if(error is ExactActionRejected)error.code else "AUDIT_PERSIST_FAILED",unknown=true) }
        finally { store.busy.set(false) }
    }

    private fun executeLocked(request:JSONObject):JSONObject {
        var consumption:String?=null
        var claimAttempted=false
        var resolved:JSONObject?=null
        val transaction=ExactActionTransaction()
        val id=request.optJSONObject("binding")?.optString("request_id") ?: return unavailable("REQUEST_INVALID")
        fun reject(code:String):JSONObject {
            val audit=store.record("VALIDATION_REJECTED",id,JSONObject().put("failure_code",code))
            return ExactActionAck.create(request,code,auditReceipt=audit,sequence=store.sequence())
        }
        try {
            if(!buildGate || !runtimeGate)return reject("ACTION_GATE_DISABLED")
            val trusted=session ?: return reject("PERMIT_AUTHENTICATION_FAILED")
            if(store.stopped())return reject("HARD_STOP_ACTIVE")
            val resolve=trusted.verify(request,System.currentTimeMillis())
            transaction.move(ExactActionState.VALIDATED)
            val b=request.getJSONObject("binding");val intent=b.getJSONObject("semantic_intent")
            store.register(request) // Unique IDs are durable even if a later validation fails.
            store.record("VALIDATION_RESULT",id,JSONObject().put("authenticated",true))
            val target=resolver.capture(resolve,trusted.connectionEpoch);resolved=target.ack
            postActionPlan?.arm(request,target) // Optional observer is armed durably BEFORE any claim/API call.
            transaction.move(ExactActionState.RESOLVED)
            store.record("TARGET_RESOLVED",id,resolved)
            // Explicit proven facts only: a newly added requirement must default to rejection.
            val facts=mutableMapOf<String,Any?>()
            for(key in listOf("protocol_supported","ownership_valid","permit_authenticated","request_digest_valid",
                "transaction_valid","request_unique","nonce_unique","permit_unused","unexpired","host_session_match"))facts[key]=true
            for(key in listOf("window_match","hierarchy_complete","single_candidate","identity_match","lineage_match",
                "children_match","action_set_match","node_valid"))facts[key]=resolved.optBoolean("resolved")
            facts["exclusive_channel"]=store.busy.get()
            facts["audit_persisted"]=true // successful mandatory TARGET_RESOLVED write immediately above
            facts["durable_claim_available"]=store.writableDatabase.isOpen
            facts["build_gate"]=buildGate;facts["runtime_gate"]=runtimeGate
            facts["helper_identity_match"]=buildId==trusted.buildId && buildId==b.getString("helper_build_id") && buildId.matches(Regex("[0-9a-f]{64}"))
            facts["host_stop_inactive"]=readiness.hostStopInactive
            facts["helper_stop_inactive"]=!store.stopped()
            facts["boot_epoch_match"]=store.metadata("boot_epoch")==trusted.bootEpoch && trusted.bootEpoch!="UNKNOWN"
            facts["connection_epoch_match"]=store.metadata("connection_epoch")==trusted.connectionEpoch
            facts["stop_epoch_match"]=store.metadata("stop_epoch")==trusted.stopEpoch
            facts["package_match"]=target.node.packageName?.toString()==trusted.packageName && b.getString("app_version")==appVersion
            facts["enabled"]=target.node.isEnabled;facts["visible"]=target.node.isVisibleToUser
            facts["click_present"]=target.node.actionList.any{it.id==16}
            val clazz=runCatching{ExactTargetClass.valueOf(intent.getString("target_class"))}.getOrNull()
            facts["target_class_allowed"]=clazz in setOf(ExactTargetClass.NAVIGATION_TARGET,ExactTargetClass.CONTAINER_WRAPPER) && target.independentDescendants==0
            facts["semantic_approved"]=intent.opt("semantic_approved")==true
            facts["isolation_approved"]=intent.opt("isolation_approved")==true && target.independentDescendants==0 && target.independentSiblings==0
            facts["observation_ready"]=readiness.observation;facts["destination_ready"]=readiness.destination
            facts["forbidden_detector_ready"]=readiness.forbiddenDetector
            val failures=ExactActionContract.failures(facts)
            store.record("PRE_DISPATCH_GATE",id,JSONObject().put("failures",org.json.JSONArray(failures)))
            if(failures.isNotEmpty())return reject(when {
                "target_class_allowed" in failures -> "TARGET_CLASS_NOT_ALLOWED"
                "semantic_approved" in failures -> "ACTION_SEMANTICS_UNPROVEN"
                "isolation_approved" in failures -> "ISOLATION_UNPROVEN"
                "helper_identity_match" in failures -> "BUILD_IDENTITY_MISMATCH"
                else -> "PRE_DISPATCH_GATE_REJECTED"
            })
            // Recheck the exact retained reference while stop/claim ordering is locked.
            if(postActionPlan!=null)ExactActionContract.requireThat(postActionPlan.collector.active(),"PRE_DISPATCH_GATE_REJECTED")
            resolved=target.revalidate();trusted.verify(request,System.currentTimeMillis())
            transaction.move(ExactActionState.PRE_DISPATCH_APPROVED)
            store.approve(request,facts)
            claimAttempted=true
            consumption=store.claim(request,System.currentTimeMillis())
            transaction.move(ExactActionState.DISPATCH_STARTED);transaction.move(ExactActionState.CONSUMED)
            // A slow durable commit may outlive freshness/expiry. Consumed does not mean we must call.
            resolved=target.revalidate();trusted.verify(request,System.currentTimeMillis())
            ExactActionContract.requireThat(!store.stopped(),"HARD_STOP_ACTIVE")
            if(postActionPlan!=null)ExactActionContract.requireThat(postActionPlan.collector.active(),"PRE_DISPATCH_GATE_REJECTED")
            val started=Instant.now().toString();val uptime=SystemClock.uptimeMillis()
            var returned:Boolean?=null;var exception:String?=null
            try { returned=target.click() } catch(error:Exception) { exception=error.javaClass.simpleName }
            val finished=Instant.now().toString()
            val state=when(returned){true->ExactActionState.ACKED;false->ExactActionState.FAILED_CONSUMED;null->ExactActionState.UNKNOWN_EXECUTION_STATE}
            val failure=when(returned){true->null;false->"PERFORM_ACTION_FALSE";null->"UNKNOWN_EXECUTION_STATE"}
            val audit=store.record("PERFORM_ACTION_RESULT",id,JSONObject().put("return",returned ?: JSONObject.NULL).put("exception",exception ?: JSONObject.NULL))
            val ack=ExactActionAck.create(request,failure,true,consumption,resolved,true,returned,state,started,finished,uptime,audit,store.sequence(),exception)
            if(postActionPlan!=null)ack.put("post_action_probe_id",postActionPlan.probeId)
            store.storeReceipt(id,ack)
            transaction.move(state)
            store.stop("C4_EFFECT_UNVERIFIED") // C4 does not authorize another action after an unverified effect.
            return ack
        } catch(error:Exception) {
            val code=if(error is ExactActionRejected)error.code else "AUDIT_PERSIST_FAILED"
            if(consumption==null) {
                if(claimAttempted && runCatching{store.claimed(id)}.getOrDefault(true))return unavailable("UNKNOWN_EXECUTION_STATE",unknown=true)
                return reject(code)
            }
            runCatching{store.stop("UNKNOWN_EXECUTION_STATE")}
            return ExactActionAck.create(request,"UNKNOWN_EXECUTION_STATE",true,consumption,resolved,null,null,
                ExactActionState.UNKNOWN_EXECUTION_STATE,auditReceipt=consumption,sequence=store.sequence(),exception=code)
        }
    }

    private fun unavailable(code:String,unknown:Boolean=false)=JSONObject().put("status",if(unknown)"UNKNOWN_EXECUTION_STATE" else "REJECTED").put("failure_code",code)
        .put("perform_action_called",if(unknown)JSONObject.NULL else false).put("visit_authority",false)
}
