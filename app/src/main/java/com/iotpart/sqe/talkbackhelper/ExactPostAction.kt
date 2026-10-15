package com.iotpart.sqe.talkbackhelper

import android.os.Build
import android.os.SystemClock
import android.graphics.Rect
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

/** C5 observation only. No action/gate setter, no production accounting dependency. */
internal object ExactPostActionContract {
    const val VERSION="talkback.post-action.v1"
    const val WINDOW_MS=5000L
    const val GRACE_MS=1000L
    val eventTypes=setOf(1,4,8,32,2048,4096,16384,32768,4194304)
    val ownerKeys=listOf("transaction_id","request_id","permit_id","request_nonce","ownership",
        "helper_connection_epoch","boot_epoch","helper_build_id","stop_epoch")
    fun owner(request:JSONObject):JSONObject=JSONObject().apply {
        val b=request.getJSONObject("binding");for(k in ownerKeys)put(k,b.get(k))
    }
    fun ready(facts:Map<String,Boolean>,configured:Set<Int>):Boolean = eventTypes.all{it in configured} &&
        listOf("service_connected","listener_active","producer_sequence_available","cursor_registered",
            "persistent_audit_writable","no_competing_transaction","connection_epoch_current",
            "destination_contract_approved","forbidden_contract_observable").all{facts[it]==true}
    fun normalize(raw:JSONObject):JSONObject=JSONObject().apply {
        for(k in listOf("event_type","event_uptime_ms","package","window_id","source_identity","text","content_description"))
            put(k,raw.opt(k) ?: JSONObject.NULL)
        put("fingerprint",ExactProtocolJson.sha256(ExactProtocolJson.canonical(this)))
    }
}

/** Optional trusted composition for later validation; never provisioned by a receiver. */
internal data class ExactPostActionPlan(val collector:ExactPostActionCollector,val probeId:String,
    val destination:JSONObject,val baseline:JSONObject,val securityObservability:JSONObject?=null) {
    fun arm(request:JSONObject,target:ExactLiveNodeResolver.Target) {
        collector.arm(request,probeId,destination,baseline,securityObservability=securityObservability)
        collector.bindResolvedTarget(target)
    }
}

/** Single nonrenewable cursor. All sink failures poison the observer and stop C4.
 * A process restart never resumes an observation: only the immutable journal can be replayed.
 * One instance is one transaction; closed instances cannot arm again.
 */
internal class ExactPostActionCollector(private val store:ExactActionStore,
    private val uptime:()->Long={SystemClock.uptimeMillis()},
    private val wall:()->Long={System.currentTimeMillis()}) {
    private var cursor:JSONObject?=null
    private var closed=false
    private var poisoned=false
    private var observationSequence=0L
    private var lastProbeUptime:Long?=null
    private var exactTarget:ExactLiveNodeResolver.Target?=null
    private var boundIdentity:JSONObject?=null
    private var authorizedTarget:JSONObject?=null
    fun closeDeadline():Long?=synchronized(store.executionLock){cursor?.let{it.getLong("deadline_uptime_ms")+it.getLong("receive_grace_ms")}}
    fun active():Boolean=synchronized(store.executionLock){cursor!=null && !closed && !poisoned && uptime()<=cursor!!.getLong("deadline_uptime_ms")}
    fun status():JSONObject=synchronized(store.executionLock){JSONObject().put("active",active()).put("poisoned",poisoned)
        .put("post_action_verifier_ready",false).put("visit_authority",false)}

    fun bindResolvedTarget(target:ExactLiveNodeResolver.Target):Unit = synchronized(store.executionLock) {
        check(active() && exactTarget==null)
        val descriptor=target.ack.getJSONObject("resolved_target_identity")
        val c=cursor!!
        require(target.ack.getString("request_id")==c.getString("request_id"))
        // Only a validated retained C4 resolver lease can establish this binding.
        target.revalidate();exactTarget=target;boundIdentity=JSONObject(descriptor.toString())
        persist("C5_EXACT_SOURCE_BOUND",owned().put("target_identity",descriptor)
            .put("binding_provenance","C4_RETAINED_VALIDATED_REFERENCE"))
    }

    fun sourceIdentity(source:AccessibilityNodeInfo?):JSONObject? = synchronized(store.executionLock) {
        val target=exactTarget ?: return@synchronized null;val d=boundIdentity ?: return@synchronized null
        if(source==null || source!=target.node || source.windowId!=d.getInt("window_id") ||
            source.packageName?.toString()!=d.getString("package") || source.viewIdResourceName!=d.optString("resource_id") ||
            source.className?.toString()!=d.getString("class_name"))return@synchronized null
        val bounds=Rect();source.getBoundsInScreen(bounds)
        val expected=d.getJSONObject("bounds")
        if(bounds.left!=expected.getInt("left") || bounds.top!=expected.getInt("top") ||
            bounds.right!=expected.getInt("right") || bounds.bottom!=expected.getInt("bottom"))return@synchronized null
        JSONObject(d.toString())
    }

    fun arm(request:JSONObject,probeId:String,destination:JSONObject,baseline:JSONObject,
        windowMs:Long=ExactPostActionContract.WINDOW_MS,graceMs:Long=ExactPostActionContract.GRACE_MS,
        securityObservability:JSONObject?=null):JSONObject = synchronized(store.executionLock) {
        check(cursor==null && !closed && !poisoned){"OBSERVATION_ALREADY_USED"}
        require(probeId.isNotBlank() && windowMs in 1..ExactPostActionContract.WINDOW_MS && graceMs in 0..ExactPostActionContract.GRACE_MS)
        val b=request.getJSONObject("binding");val intent=b.getJSONObject("semantic_intent")
        require(destination.getString("schema_version")==ExactPostActionContract.VERSION &&
            destination.getString("destination_contract_id")==intent.getString("destination_contract_id") &&
            ExactProtocolJson.sha256(ExactProtocolJson.canonical(destination))==intent.getString("destination_contract_digest"))
        require(windowMs<=destination.getLong("timeout_ms"))
        synchronized(store.executionLock) {
            require(!store.stopped() && !store.claimed(b.getString("request_id")))
            require(store.registeredPacket(b.getString("request_id"))==ExactProtocolJson.canonical(request))
            for((key,metadata) in mapOf("helper_connection_epoch" to "connection_epoch","boot_epoch" to "boot_epoch","stop_epoch" to "stop_epoch"))
                require(b.getString(key)==store.metadata(metadata))
            val start=uptime();require(start>=0)
            val c=ExactPostActionContract.owner(request).put("schema_version",ExactPostActionContract.VERSION)
                .put("probe_id",probeId).put("target_identity_digest",b.getString("target_identity_digest"))
                .put("dispatch_reference_time",JSONObject.NULL).put("producer_sequence_cursor",store.sequence()+1)
                .put("start_uptime_ms",start).put("deadline_uptime_ms",Math.addExact(start,windowMs))
                .put("window_ms",windowMs).put("receive_grace_ms",graceMs)
                .put("destination_contract",JSONObject(destination.toString())).put("baseline_security_state",JSONObject(baseline.toString()))
                .put("security_observability",securityObservability?.let{JSONObject(it.toString())} ?: JSONObject().put("status","UNKNOWN"))
            persist("C5_CURSOR_ARMED",c,b.getString("request_id"));cursor=c
            authorizedTarget=JSONObject(request.getJSONObject("resolve_request").getJSONObject("target_identity").toString())
            persist("C5_COLLECTION_STARTED",owned().put("helper_uptime_ms",start))
            // A finite close callback exists even if the app emits no further events.
            android.os.Handler(android.os.Looper.getMainLooper()).postAtTime({
                runCatching{close()}.onFailure{interrupt("AUDIT_PERSIST_FAILED");runCatching{store.stop("AUDIT_PERSIST_FAILED")}}
            },start+windowMs+graceMs)
            JSONObject(c.toString())
        }
    }

    private fun owned():JSONObject=JSONObject().apply {
        val c=cursor ?: error("NO_OBSERVATION_CURSOR")
        for(k in ExactPostActionContract.ownerKeys)put(k,c.get(k))
        put("probe_id",c.getString("probe_id"))
    }
    private fun persist(kind:String,payload:JSONObject,id:String?=cursor?.getString("request_id")):String {
        try{return store.record(kind,id,payload)}catch(e:Exception){
            poisoned=true;runCatching{store.stop("AUDIT_PERSIST_FAILED")};throw e
        }
    }
    fun accept(raw:JSONObject):Boolean = synchronized(store.executionLock) {
        val c=cursor ?: return@synchronized false
        if(poisoned)return@synchronized false
        val receive=uptime()
        val deadline=c.getLong("deadline_uptime_ms");val after=receive>deadline+c.getLong("receive_grace_ms")
        if(after && !closed)close(receive)
        // Preserve late evidence, without changing the close record or reopening the cursor.
        val copy=JSONObject(raw.toString())
        val o=owned();for(k in ExactPostActionContract.ownerKeys)copy.put(k,o.get(k))
        copy.put("probe_id",c.getString("probe_id")).put("helper_receive_uptime_ms",receive)
            .put("helper_receive_timestamp_ms",wall()).put("helper_monotonic_ns",SystemClock.elapsedRealtimeNanos())
            .put("clock_domain","ANDROID_UPTIME_MS").put("late_evidence",closed || after)
        synchronized(store.executionLock) {
            copy.put("event_sequence",store.sequence()+1)
            persist("C5_RAW_EVENT",copy) // Immutable raw evidence first.
            persist("C5_NORMALIZED_EVENT",ExactPostActionContract.normalize(copy))
        }
        !closed
    }
    fun probe(hierarchy:JSONObject,activity:String?,context:String?,modal:String?,stateSelectors:List<String>):JSONObject = synchronized(store.executionLock) {
        check(active()){"OBSERVATION_CLOSED"}
        val now=uptime();val c=cursor!!
        require(now<=c.getLong("deadline_uptime_ms"))
        require(lastProbeUptime==null || now>lastProbeUptime!!)
        val p=ExactStructuralProbe.build(hierarchy,stateSelectors,authorizedTarget?.optString("resource_id")).apply {
            val o=owned();for(k in ExactPostActionContract.ownerKeys)put(k,o.get(k))
            put("post_action_probe_id",c.getString("probe_id"));put("observation_sequence",++observationSequence)
            put("device_uptime_ms",now);put("helper_receive_timestamp_ms",wall())
            put("activity",activity ?: JSONObject.NULL);put("context",context ?: JSONObject.NULL);put("modal",modal ?: JSONObject.NULL)
        }
        persist("C5_STRUCTURAL_PROBE",p);lastProbeUptime=now
        JSONObject(p.toString())
    }
    fun close(now:Long=uptime()):Boolean = synchronized(store.executionLock) {
        if(cursor==null || closed || poisoned)return@synchronized false
        val c=cursor!!
        require(now>=c.getLong("deadline_uptime_ms")+c.getLong("receive_grace_ms")){"OBSERVATION_WINDOW_OPEN"}
        persist("C5_COLLECTION_CLOSED",owned().put("closed_uptime_ms",now));closed=true
        true
    }
    fun interrupt(reason:String):Unit = synchronized(store.executionLock) {
        if(cursor==null || closed)return@synchronized
        runCatching{persist("C5_OBSERVATION_INTERRUPTED",owned().put("reason",reason))}
        poisoned=true;closed=true
    }
}

/** Derives structural tokens from actual read-only hierarchy, not labels supplied by an action ACK.
 * Security selectors must resolve to exactly one visible/enabled node; missing/duplicate => null.
 * Full raw hierarchy remains in the probe for offline derivation audit.
 */
internal object ExactStructuralProbe {
    fun build(hierarchy:JSONObject,stateSelectors:List<String>,targetResourceId:String?=null):JSONObject {
        val nodes=mutableListOf<JSONObject>();val structures=JSONArray();val markers=JSONArray();var limited=false
        fun walk(n:JSONObject,path:String,depth:Int) {
            if(depth>80 || nodes.size>=5000){limited=true;return}
            nodes.add(n)
            val resource=n.opt("viewIdResourceName")?.takeUnless{it==JSONObject.NULL}?.toString() ?: ""
            val clazz=n.opt("className")?.takeUnless{it==JSONObject.NULL}?.toString() ?: ""
            structures.put("$path|$resource|$clazz")
            if(n.optBoolean("visibleToUser")) {
                if(resource.isNotBlank())markers.put("id:"+resource)
                if(n.has("text") && !n.isNull("text") && n.getString("text").isNotBlank())markers.put("text:"+n.getString("text"))
            }
            val children=n.optJSONArray("children") ?: JSONArray()
            for(i in 0 until children.length())walk(children.getJSONObject(i),"$path/$i",depth+1)
        }
        val appWindows=hierarchy.optJSONArray("windows") ?: JSONArray()
        val selected=(0 until appWindows.length()).map{appWindows.getJSONObject(it)}.filter{it.optInt("type")==1 && it.optBoolean("active",it.optBoolean("isActive",false))}
        val window=selected.singleOrNull();val root=window?.optJSONObject("root")
        if(root!=null)walk(root,"0",0)
        val states=JSONObject()
        for(selector in stateSelectors) {
            val found=nodes.filter{it.optString("viewIdResourceName")==selector}
            val n=found.singleOrNull()
            states.put(selector,if(n!=null && n.optBoolean("visibleToUser") && n.optBoolean("enabled"))
                JSONObject().put("text",n.opt("text") ?: JSONObject.NULL).put("description",n.opt("contentDescription") ?: JSONObject.NULL)
                    .put("checked",n.opt("checked") ?: JSONObject.NULL).put("selected",n.opt("selected") ?: JSONObject.NULL)
                else JSONObject.NULL)
        }
        return JSONObject().put("read_succeeded",root!=null && !limited).put("raw_hierarchy",JSONObject(hierarchy.toString()))
            .put("package",root?.opt("packageName") ?: JSONObject.NULL).put("window_id",window?.opt("id") ?: JSONObject.NULL)
            .put("window_type",window?.opt("type") ?: JSONObject.NULL).put("markers",markers).put("structures",structures)
            .put("root_signature",ExactProtocolJson.sha256(ExactProtocolJson.canonical(structures)))
            .put("target_presence_count",if(targetResourceId.isNullOrBlank())JSONObject.NULL else nodes.count{it.optString("viewIdResourceName")==targetResourceId})
            .put("security_state",states)
    }
}

/** Service adapter is passive until a trusted in-process observer is registered. No RPC arms it. */
internal object ExactPostActionRuntime {
    @Volatile private var observer:ExactPostActionCollector?=null
    fun connect() { observer?.interrupt("SERVICE_RECONNECTED");observer=null }
    fun stop(reason:String) {observer?.interrupt(reason)}
    internal fun bindReadOnly(collector:ExactPostActionCollector) {check(observer==null);observer=collector}
    /** No polling extension: one finite close timer, independent of further events. */
    internal fun scheduleClose(handler:android.os.Handler) {
        val current=observer ?: return
        val deadline=current.closeDeadline() ?: return
        handler.postAtTime({runCatching{current.close()}.onFailure{current.interrupt("AUDIT_PERSIST_FAILED");ExactActionRuntime.stop("AUDIT_PERSIST_FAILED")}},deadline)
    }
    fun receive(event:AccessibilityEvent) {
        val current=observer ?: return
        runCatching {
            val source=event.source
            val exactIdentity=current.sourceIdentity(source)
            val bounds=Rect();source?.getBoundsInScreen(bounds)
            val raw=JSONObject().put("event_type",event.eventType).put("event_uptime_ms",event.eventTime)
                .put("package",event.packageName?.toString() ?: JSONObject.NULL).put("class",event.className?.toString() ?: JSONObject.NULL)
                .put("text",JSONArray(event.text.map{it?.toString()})).put("content_description",event.contentDescription?.toString() ?: JSONObject.NULL)
                .put("window_id",event.windowId).put("window_type",JSONObject.NULL)
                .put("bounds",if(source==null)JSONObject.NULL else JSONObject().put("left",bounds.left).put("top",bounds.top).put("right",bounds.right).put("bottom",bounds.bottom))
                .put("enabled",source?.isEnabled ?: JSONObject.NULL).put("clickable",source?.isClickable ?: JSONObject.NULL)
                .put("accessibility_focused",source?.isAccessibilityFocused ?: JSONObject.NULL)
                .put("input_focused",source?.isFocused ?: JSONObject.NULL)
                .put("source_resource_id",source?.viewIdResourceName ?: JSONObject.NULL)
                .put("source_node_id",if(Build.VERSION.SDK_INT>=33)source?.uniqueId ?: JSONObject.NULL else JSONObject.NULL)
                .put("source_provenance",if(exactIdentity!=null)"EXACT_RETAINED_NODE_REFERENCE" else if(source==null)"SOURCE_UNAVAILABLE" else "PARTIAL_ACCESSIBILITY_SOURCE")
                .put("source_identity",exactIdentity ?: JSONObject.NULL) // Missing exact source remains missing.
            current.accept(raw)
        }.onFailure{current.interrupt("EVENT_CAPTURE_FAILED");ExactActionRuntime.stop("POST_ACTION_PROBE_FAILED")}
    }
}
