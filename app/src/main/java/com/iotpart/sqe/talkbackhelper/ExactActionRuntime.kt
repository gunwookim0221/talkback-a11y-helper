package com.iotpart.sqe.talkbackhelper

import android.provider.Settings
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.SynchronousQueue
import java.util.concurrent.TimeUnit

internal data class ExactActionRuntimeConfig(val enabled:Boolean=false) {
    companion object {
        fun parse(local:JSONObject?):ExactActionRuntimeConfig = ExactActionRuntimeConfig(
            local != null && local.keys().asSequence().toSet()==setOf("mode","enabled") &&
                local.optString("mode")==ExactActionContract.MODE && local.opt("enabled")==true)
    }
}

/** No RPC provisions a secret, clears stop, enables a gate, or supplies C5 readiness. */
internal object ExactActionRuntime {
    @Volatile private var store:ExactActionStore?=null
    @Volatile private var config=ExactActionRuntimeConfig() // OFF; no production callsite provisions this.
    @Volatile private var trustedSession:ExactActionSession?=null
    private val worker=ThreadPoolExecutor(1,1,0L,TimeUnit.MILLISECONDS,SynchronousQueue<Runnable>(),
        { runnable -> Thread(runnable,"exact-action").apply{isDaemon=true} })

    fun connect(service:A11yHelperService):String {
        config=ExactActionRuntimeConfig();trustedSession=null
        return runCatching {
            store?.let { synchronized(it.executionLock){it.stop("SERVICE_RECONNECTED");it.close()} }
            val current=ExactActionStore(service)
            store=current
            val boot=Settings.Global.getString(service.contentResolver,"boot_count")?.toLongOrNull()?.takeIf { it>=0 }?.let { "boot:$it" } ?: "UNKNOWN"
            val connection=current.connect(boot)
            current.record("FEATURE_GATES",null,JSONObject().put("build_gate",BuildConfig.BUILD_EXACT_ACTION_SUPPORT)
                .put("runtime_gate",false).put("c5_ready",false))
            connection
        }.getOrElse { store=null; UUID.randomUUID().toString() }
    }
    fun stop(reason:String) { runCatching { store?.stop(reason) } }
    /** Trusted in-process composition only. Never exposed by a receiver or old configuration. */
    fun configureTrustedLocalSession(local:JSONObject,trusted:ExactActionSession):Boolean {
        if(!BuildConfig.BUILD_EXACT_ACTION_SUPPORT)return false
        val current=store ?: return false
        return synchronized(current.executionLock) {
            val next=ExactActionRuntimeConfig.parse(local)
            if(!next.enabled || current.stopped() || trusted.identityStatus!="MATCH" || BuildConfig.HELPER_SOURCE_STATE!="CLEAN" || trusted.buildId!=BuildConfig.HELPER_BUILD_ID ||
                trusted.connectionEpoch!=current.metadata("connection_epoch") || trusted.bootEpoch!=current.metadata("boot_epoch") ||
                trusted.stopEpoch!=current.metadata("stop_epoch") || trusted.bootEpoch=="UNKNOWN")return@synchronized false
            current.record("TRUSTED_SESSION_BOUND",null,JSONObject().put("host_session_id",trusted.sessionId)
                .put("helper_build_id",trusted.buildId).put("connection_epoch",trusted.connectionEpoch)
                .put("mode",ExactActionContract.MODE).put("runtime_gate",true).put("c5_ready",false))
            trustedSession=trusted;config=next
            true // C5 readiness is still false: this does not make a live action executable in C4.
        }
    }
    fun dispatch(service:A11yHelperService,raw:String,transportRequestId:String,complete:(JSONObject)->Unit) {
        if(!BuildConfig.BUILD_EXACT_ACTION_SUPPORT || !config.enabled) {complete(rejected("ACTION_GATE_DISABLED"));return}
        try { worker.execute { complete(handle(service,raw,transportRequestId)) } }
        catch(error:java.util.concurrent.RejectedExecutionException) { complete(rejected("CONCURRENT_ACTION")) }
    }
    fun handle(service:A11yHelperService,raw:String,transportRequestId:String):JSONObject {
        if(!BuildConfig.BUILD_EXACT_ACTION_SUPPORT || !config.enabled)return rejected("ACTION_GATE_DISABLED")
        if(ExactNodeResolver.hasDuplicateJsonKey(raw))return rejected("REQUEST_INVALID")
        val parsed=runCatching{JSONObject(raw)}.getOrElse{return rejected("REQUEST_INVALID")}
        if(parsed.optJSONObject("binding")?.optString("request_id")!=transportRequestId)return rejected("OWNERSHIP_MISMATCH")
        val current=store ?: return rejected("AUDIT_PERSIST_FAILED")
        val trusted=trustedSession ?: return rejected("PERMIT_AUTHENTICATION_FAILED")
        if(trusted.packageName!="com.samsung.android.oneconnect")return rejected("PACKAGE_MISMATCH")
        val version=runCatching{service.packageManager.getPackageInfo(trusted.packageName,0).versionName}.getOrNull()
            ?: return rejected("PACKAGE_MISMATCH")
        val resolver=ExactLiveNodeResolver {
            service.windows.map { ExactApplicationWindow(it.id,it.type,it.isActive,it.root) }
        }
        return ExactActionEngine(current,trusted,resolver,BuildConfig.BUILD_EXACT_ACTION_SUPPORT,config.enabled,
            BuildConfig.HELPER_BUILD_ID,version,ExactActionReadiness()).execute(raw)
    }
    fun readback(raw:String):JSONObject {
        if(ExactNodeResolver.hasDuplicateJsonKey(raw))return rejected("REQUEST_INVALID")
        return runCatching { store?.readback(JSONObject(raw)) ?: rejected("RECEIPT_NOT_FOUND") }
            .getOrElse{rejected(if(it is ExactActionRejected)it.code else "AUDIT_PERSIST_FAILED")}
    }
    fun markAckEmitted(ack:JSONObject) {
        val id=ack.optString("request_id")
        if(id.isBlank() || !ack.has("audit_receipt_id"))return
        runCatching { store?.record("ACK_EMITTED",id,JSONObject().put("transport","logcat_chunks").put("delivery_confirmed",false)) }
            .onFailure { stop("AUDIT_PERSIST_FAILED_AFTER_ACK") }
    }
    fun status():JSONObject {
        val current=store
        return JSONObject().put("protocol_version",ExactActionContract.VERSION)
            .put("build_gate",BuildConfig.BUILD_EXACT_ACTION_SUPPORT).put("runtime_gate",config.enabled)
            .put("mode",if(config.enabled)ExactActionContract.MODE else "OFF").put("c5_ready",false)
            .put("helper_stopped",runCatching{current?.stopped() ?: true}.getOrDefault(true))
            .put("connection_epoch",runCatching{current?.metadata("connection_epoch")}.getOrNull() ?: JSONObject.NULL)
            .put("boot_epoch",runCatching{current?.metadata("boot_epoch")}.getOrNull() ?: "UNKNOWN")
            .put("stop_epoch",runCatching{current?.metadata("stop_epoch")}.getOrNull() ?: JSONObject.NULL)
    }
    private fun rejected(code:String)=JSONObject().put("status","REJECTED").put("failure_code",code)
        .put("perform_action_called",false).put("visit_authority",false)
}
