package com.iotpart.sqe.talkbackhelper

import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.io.File
import java.util.concurrent.atomic.AtomicLong

/** Opt-in caller/relationship evidence. Never returns a cached node or changes an action. */
internal class SmartNextLookupTrace(private val requestId: String, private val directory: File) {
    companion object {
        private val structuralEpoch = AtomicLong()
        fun structureChanged() { structuralEpoch.incrementAndGet() }
        fun generation(): Long = structuralEpoch.get()
    }
    private val started = System.nanoTime()
    private val startedWall = System.currentTimeMillis()
    private val bytes = ByteArrayOutputStream()
    private val records = DataOutputStream(bytes)
    // Android equals compares source/window identity; hash collisions are resolved by equals.
    private val nodes = HashMap<AccessibilityNodeInfo, Int>()
    private val nodeDescriptions = JSONArray()
    private val callers = linkedMapOf<String, Int>()
    private val phases = linkedMapOf<String, Int>()
    private val snapshots = JSONArray()
    private var snapshot = 0
    private var epoch = structuralEpoch.get()
    private var count = 0

    fun newSnapshot(reason: String, phase: String) {
        epoch = structuralEpoch.get()
        snapshot++
        snapshots.put(JSONObject().put("id", snapshot).put("reason", reason).put("phase", phase)
            .put("epoch", epoch).put("elapsed_ns", System.nanoTime() - started)
            .put("timestamp", System.currentTimeMillis()))
    }

    private fun key(node: AccessibilityNodeInfo?): Int {
        node ?: return -1
        return nodes[node] ?: nodes.size.also { index ->
            nodes[node] = index
            nodeDescriptions.put(JSONObject().put("id", index).put("window_id", node.windowId).put("hash", node.hashCode()))
        }
    }

    fun lookup(node: AccessibilityNodeInfo, childIndex: Int, caller: String, phase: String,
               action: () -> AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (snapshot == 0 || epoch != structuralEpoch.get()) newSnapshot("structural_event_or_initial", phase)
        val scope = snapshot
        val nodeKey = key(node)
        val callerKey = callers.getOrPut(caller) { callers.size }
        val phaseKey = phases.getOrPut(phase) { phases.size }
        val begin = System.nanoTime()
        var result: AccessibilityNodeInfo? = null
        var threw = true
        try {
            result = action()
            threw = false
            return result
        } finally {
            val elapsed = System.nanoTime() - begin
            val epochAfter = structuralEpoch.get()
            records.writeInt(scope)
            records.writeInt(nodeKey)
            records.writeByte(if (childIndex < 0) 0 else 1)
            records.writeInt(childIndex)
            records.writeInt(callerKey)
            records.writeInt(phaseKey)
            records.writeLong(elapsed)
            records.writeLong(begin - started)
            records.writeInt(if (threw) -2 else key(result))
            records.writeLong(epochAfter)
            count++
        }
    }

    fun writeArtifact(): File {
        val header = JSONObject().put("schema", "smart-next-lookups-v1").put("request_id", requestId)
            .put("record_count", count).put("record_size", 49).put("started_wall_ms", startedWall)
            .put("nodes", nodeDescriptions).put("callers", JSONArray(callers.keys.toList()))
            .put("phases", JSONArray(phases.keys.toList())).put("snapshots", snapshots)
            .toString().toByteArray(Charsets.UTF_8)
        val outputDirectory = File(directory, "smart_next_lookups").apply { mkdirs() }
        val file = File(outputDirectory, requestId.replace(Regex("[^a-zA-Z0-9_-]"), "_").take(80) + ".bin")
        DataOutputStream(file.outputStream().buffered()).use { output ->
            output.writeInt(header.size)
            output.write(header)
            bytes.writeTo(output)
        }
        nodes.clear()
        return file
    }
}
