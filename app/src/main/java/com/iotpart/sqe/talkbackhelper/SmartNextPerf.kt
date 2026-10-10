package com.iotpart.sqe.talkbackhelper

import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap
import java.io.File

/** Opt-in measurements only. Never supplies a navigation or eligibility input. */
internal object SmartNextPerf {
    private val requested = ConcurrentHashMap<String, File?>()
    private val plainRequested = ConcurrentHashMap.newKeySet<String>()
    private val current = ThreadLocal<Profile>()

    internal class Profile(val requestId: String, val started: Long = System.nanoTime(), val lookup: SmartNextLookupTrace? = null) {
        val spans = linkedMapOf<String, Span>()
        val stack = ArrayDeque<Token>()
        val counters = linkedMapOf<String, Long>()
        val unique = mutableMapOf<String, MutableSet<Int>>()
        var enumerationDepth = 0
        var maxDepth = 0
        val treeNodes = mutableSetOf<Int>()
        val visibleNodes = mutableSetOf<Int>()
    }
    internal class Span(var nanos: Long = 0, var exclusive: Long = 0, var calls: Long = 0)
    internal class Token(val profile: Profile, val name: String, val started: Long, var children: Long = 0)

    fun request(requestId: String, enabled: Boolean, lookupDirectory: File? = null) {
        if (enabled) {
            plainRequested.add(requestId)
            if (lookupDirectory != null) requested[requestId] = lookupDirectory
        }
    }
    fun cancel(requestId: String) { requested.remove(requestId); plainRequested.remove(requestId) }
    fun begin(requestId: String) {
        if (!plainRequested.remove(requestId)) return
        val directory = requested.remove(requestId)
        current.set(Profile(requestId, lookup = directory?.let { SmartNextLookupTrace(requestId, it) }))
        mark("T0_request_start")
    }
    fun mark(stage: String) {
        val p = current.get() ?: return
        Log.i("A11Y_HELPER", "[SMART_NEXT_DEEP] " + JSONObject()
            .put("kind", "marker").put("request_id", p.requestId).put("stage", stage)
            .put("timestamp", System.currentTimeMillis()).put("elapsed_ms", (System.nanoTime() - p.started) / 1e6))
    }
    @PublishedApi internal fun start(name: String): Token? {
        val p = current.get() ?: return null
        if (name in setOf("root_acquisition", "runtime_state", "post_state", "service_verification")) {
            p.lookup?.newSnapshot("begin_$name", name)
        }
        return Token(p, name, System.nanoTime()).also { p.stack.addLast(it) }
    }
    @PublishedApi internal fun finish(token: Token?) {
        token ?: return
        val elapsed = System.nanoTime() - token.started
        val p = token.profile
        check(p.stack.removeLast() === token)
        p.stack.lastOrNull()?.let { it.children += elapsed }
        val span = p.spans.getOrPut(token.name) { Span() }
        span.nanos += elapsed
        span.exclusive += elapsed - token.children
        span.calls++
    }
    inline fun <T> measure(name: String, block: () -> T): T {
        val token = start(name)
        try { return block() } finally { finish(token) }
    }
    fun count(name: String, amount: Long = 1) {
        val p = current.get() ?: return
        p.counters[name] = (p.counters[name] ?: 0) + amount
    }
    fun value(name: String, amount: Long) { current.get()?.counters?.set(name, amount) }
    fun descendantVisit(node: AccessibilityNodeInfo) {
        val p = current.get() ?: return
        count("total_descendant_visits")
        p.unique.getOrPut("descendant_visit") { mutableSetOf() }.add(node.hashCode())
    }
    fun scan(name: String, node: AccessibilityNodeInfo) {
        val p = current.get() ?: return
        count("${name}_scan_calls")
        // Android node hash is a local source/window identity hash, not an IPC/tree read.
        p.unique.getOrPut(name) { mutableSetOf() }.add(node.hashCode())
    }
    fun enterEnumeration(node: AccessibilityNodeInfo, visible: Boolean) {
        val p = current.get() ?: return
        p.treeNodes.add(node.hashCode())
        if (visible) p.visibleNodes.add(node.hashCode())
        p.maxDepth = maxOf(p.maxDepth, p.enumerationDepth)
        p.enumerationDepth++
        count("enumeration_visits")
    }
    fun leaveEnumeration() { current.get()?.let {
        it.enumerationDepth--
        if (it.enumerationDepth == 0) mark("T2_visible_enumeration_complete")
    } }
    private fun phase(): String {
        val names = current.get()?.stack?.map { it.name }.orEmpty().filterNot { it.startsWith("ipc_") }
        return (if ("runtime_state" in names) "runtime_state/" else "") + names.lastOrNull().orEmpty()
    }
    fun getChild(node: AccessibilityNodeInfo, index: Int, caller: String = "UNATTRIBUTED"): AccessibilityNodeInfo? =
        SnapshotRelationshipAccess.child(node, index) { measure("ipc_get_child") {
            count("get_child_calls")
            val trace = current.get()?.lookup
            if (trace == null) node.getChild(index) else trace.lookup(node, index, caller, phase()) { node.getChild(index) }
        } }
    fun getParent(node: AccessibilityNodeInfo, caller: String = "UNATTRIBUTED"): AccessibilityNodeInfo? =
        SnapshotRelationshipAccess.parent(node) { measure("ipc_get_parent") {
            count("get_parent_calls")
            val trace = current.get()?.lookup
            if (trace == null) node.parent else trace.lookup(node, -1, caller, phase()) { node.parent }
        } }
    fun rootBoundary(caller: String) {
        SnapshotRelationshipAccess.invalidate()
        current.get()?.lookup?.newSnapshot("root_$caller", phase())
    }
    inline fun <T> acquireRoot(caller: String, block: () -> T): T {
        rootBoundary(caller)
        return block()
    }
    fun refresh(node: AccessibilityNodeInfo): Boolean =
        measure("ipc_refresh") {
            count("refresh_calls")
            SnapshotRelationshipAccess.invalidate()
            node.refresh().also {
                SnapshotRelationshipAccess.invalidate()
                current.get()?.lookup?.newSnapshot("refresh", phase())
            }
        }
    fun findFocus(node: AccessibilityNodeInfo, focus: Int) =
        measure("ipc_find_focus") { count("find_focus_calls"); node.findFocus(focus) }
    fun performAction(node: AccessibilityNodeInfo, action: Int): Boolean = measure("focus_action") {
        SnapshotRelationshipAccess.invalidate()
        mark("T7_action_issued")
        count("perform_action_calls")
        node.performAction(action).also {
            mark("T8_action_returned")
            SnapshotRelationshipAccess.invalidate()
            current.get()?.lookup?.newSnapshot("action_$action", phase())
        }
    }
    fun end() {
        val p = current.get() ?: return
        try {
            val total = (System.nanoTime() - p.started) / 1e6
            p.spans.forEach { (name, span) ->
                Log.i("A11Y_HELPER", "[SMART_NEXT_DEEP] " + JSONObject()
                    .put("kind", "span").put("request_id", p.requestId).put("stage", name)
                    .put("timestamp", System.currentTimeMillis()).put("elapsed_ms", span.nanos / 1e6)
                    .put("exclusive_ms", span.exclusive / 1e6).put("calls", span.calls))
            }
            val counts = JSONObject(p.counters as Map<*, *>)
                .put("tree_node_count", p.treeNodes.size).put("visible_node_count", p.visibleNodes.size)
                .put("max_tree_depth", p.maxDepth)
            p.unique.forEach { (name, nodes) -> counts.put("${name}_unique_subtrees", nodes.size) }
            Log.i("A11Y_HELPER", "[SMART_NEXT_DEEP] " + JSONObject()
                .put("kind", "summary").put("request_id", p.requestId).put("timestamp", System.currentTimeMillis())
                .put("elapsed_ms", total).put("counts", counts))
            p.lookup?.let { trace ->
                runCatching { trace.writeArtifact() }.fold(
                    onSuccess = { file -> Log.i("A11Y_HELPER", "[SMART_NEXT_LOOKUP_ARTIFACT] request_id=${p.requestId} file=${file.name} bytes=${file.length()}") },
                    onFailure = { error -> Log.e("A11Y_HELPER", "[SMART_NEXT_LOOKUP_ARTIFACT_FAILED] request_id=${p.requestId} error=${error.javaClass.simpleName}") }
                )
            }
        } finally { current.remove() }
    }
}
