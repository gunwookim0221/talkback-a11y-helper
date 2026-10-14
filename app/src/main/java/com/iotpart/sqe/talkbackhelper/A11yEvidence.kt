package com.iotpart.sqe.talkbackhelper

import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.graphics.Rect
import org.json.JSONObject
import org.json.JSONArray
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

/**
 * Opt-in correlation-only evidence channel.
 *
 * It never participates in navigation, success, history, or reporting decisions.
 * The Python runner only supplies these extras when TB_EVIDENCE_LEDGER_ENABLED is on.
 */
object A11yEvidence {
    private const val TAG = "A11Y_HELPER"
    private const val EVENT_LOG_PREFIX = "EVIDENCE_HELPER_EVENT"
    private const val MAX_EVENT_LOG_CHARS = 3200
    private const val MAX_TRANSPORT_TEXT_CHARS = 256
    private val correlationByReqId = ConcurrentHashMap<String, JSONObject>()
    private val eventsByReqId = ConcurrentHashMap<String, MutableList<JSONObject>>()
    private val eventSequence = AtomicLong(0L)
    private val cleanupHandler = Handler(Looper.getMainLooper())
    private data class EntryClickCapture(
        val reqId: String,
        val transactionId: String,
        val armedElapsedRealtimeMs: Long,
        val leaseDeadlineElapsedRealtimeMs: Long,
        val cursorEventSequence: Long,
        val dispatchUptimeMs: Long? = null,
    )
    @Volatile private var activeEntryClickCapture: EntryClickCapture? = null

    private val extraKeys = mapOf(
        "run_id" to "evidenceRunId",
        "scenario_tx_id" to "evidenceScenarioTxId",
        "transaction_id" to "evidenceTransactionId",
        "attempt_id" to "evidenceAttemptId",
        "logical_action_id" to "evidenceLogicalActionId"
    )

    fun capture(intent: Intent?, reqId: String) {
        if (intent == null || reqId.isBlank() || reqId == "none") return
        val correlation = JSONObject()
        extraKeys.forEach { (field, extra) ->
            intent.getStringExtra(extra)?.trim()?.takeIf { it.isNotEmpty() }?.let { correlation.put(field, it) }
        }
        if (correlation.length() > 0) {
            correlationByReqId[reqId] = correlation
            eventsByReqId.putIfAbsent(reqId, mutableListOf())
            Log.i(TAG, "[EVIDENCE][helper_start] requestId=$reqId transactionId=${correlation.optString("transaction_id")} enabled=true action=${intent?.action.orEmpty()}")
        }
    }

    fun hasCorrelation(reqId: String): Boolean = correlationByReqId.containsKey(reqId)

    fun armEntryClickCapture(reqId: String, transactionId: String, leaseMs: Long): JSONObject {
        val safeReqId = reqId.trim()
        val safeTransactionId = transactionId.trim()
        if (safeReqId.isEmpty() || safeReqId == "none" || safeTransactionId.isEmpty()) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_CORRELATION_MISSING")
        }
        val now = SystemClock.elapsedRealtime()
        val capture = EntryClickCapture(
            reqId = safeReqId,
            transactionId = safeTransactionId,
            armedElapsedRealtimeMs = now,
            leaseDeadlineElapsedRealtimeMs = now + leaseMs.coerceIn(500L, 5000L),
            cursorEventSequence = eventSequence.get(),
        )
        synchronized(this) {
            if (activeEntryClickCapture != null) {
                return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_ALREADY_ACTIVE")
            }
            correlationByReqId[safeReqId] = JSONObject().put("transaction_id", safeTransactionId)
            eventsByReqId[safeReqId] = mutableListOf()
            activeEntryClickCapture = capture
        }
        cleanupHandler.postDelayed({
            synchronized(this) {
                if (activeEntryClickCapture?.reqId == safeReqId) {
                    activeEntryClickCapture = null
                    correlationByReqId.remove(safeReqId)
                    eventsByReqId.remove(safeReqId)
                }
            }
        }, capture.leaseDeadlineElapsedRealtimeMs - now + 250L)
        Log.i(TAG, "[ENTRY_CLICK_CAPTURE][armed] reqId=$safeReqId transactionId=$safeTransactionId cursor=${capture.cursorEventSequence}")
        return entryClickSnapshot(safeReqId).put("ok", true).put("reason", "ARMED")
    }

    fun markEntryClickDispatch(reqId: String, dispatchUptimeMs: Long): JSONObject {
        if (dispatchUptimeMs < 0L) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_DISPATCH_CURSOR_INVALID")
        }
        synchronized(this) {
            val capture = activeEntryClickCapture
                ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_NOT_ARMED")
            if (capture.reqId != reqId) return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_REQUEST_MISMATCH")
            activeEntryClickCapture = capture.copy(dispatchUptimeMs = dispatchUptimeMs)
        }
        return entryClickSnapshot(reqId).put("ok", true).put("reason", "DISPATCH_MARKED")
    }

    fun captureEntryClickEvent(event: AccessibilityEvent): Boolean {
        val capture = activeEntryClickCapture ?: return false
        if (SystemClock.elapsedRealtime() > capture.leaseDeadlineElapsedRealtimeMs) return false
        val receivedElapsed = SystemClock.elapsedRealtime()
        val payload = runCatching {
            val source = event.source
            val sourceStatus = if (source == null) "FIELD_ABSENT" else "FIELD_PRESENT"
            val sourceData = source?.let { node ->
                val bounds = Rect()
                node.getBoundsInScreen(bounds)
                val hasBounds = bounds.width() > 0 && bounds.height() > 0
                JSONObject().apply {
                    put("resource_id", node.viewIdResourceName ?: JSONObject.NULL)
                    put("class_name", node.className?.toString() ?: JSONObject.NULL)
                    put("text", node.text?.toString() ?: JSONObject.NULL)
                    put("content_description", node.contentDescription?.toString() ?: JSONObject.NULL)
                    put("bounds", if (hasBounds) JSONObject().put("left", bounds.left).put("top", bounds.top)
                        .put("right", bounds.right).put("bottom", bounds.bottom) else JSONObject.NULL)
                    put("window_id", if (node.windowId >= 0) node.windowId else JSONObject.NULL)
                    put("enabled", node.isEnabled)
                    put("clickable", node.isClickable)
                    put("focusable", node.isFocusable)
                    put("resource_id_status", if (node.viewIdResourceName.isNullOrBlank()) "FIELD_ABSENT" else "FIELD_PRESENT")
                    put("class_name_status", if (node.className == null) "FIELD_ABSENT" else "FIELD_PRESENT")
                    put("text_status", if (node.text == null) "FIELD_ABSENT" else "FIELD_PRESENT")
                    put("content_description_status", if (node.contentDescription == null) "FIELD_ABSENT" else "FIELD_PRESENT")
                    put("bounds_status", if (hasBounds) "FIELD_PRESENT" else "FIELD_ABSENT")
                    put("window_id_status", if (node.windowId >= 0) "FIELD_PRESENT" else "FIELD_ABSENT")
                }
            }
            JSONObject().apply {
                put("event_type", "TYPE_VIEW_CLICKED")
                put("event_time_uptime_ms", event.eventTime)
                put("package", event.packageName?.toString() ?: JSONObject.NULL)
                put("class_name", event.className?.toString() ?: JSONObject.NULL)
                put("text", event.text.joinToString(" ") { it?.toString().orEmpty() }.takeIf { it.isNotBlank() } ?: JSONObject.NULL)
                put("content_description", source?.contentDescription?.toString() ?: JSONObject.NULL)
                put("enabled", event.isEnabled)
                put("window_id", if (event.windowId >= 0) event.windowId else JSONObject.NULL)
                put("source", sourceData ?: JSONObject.NULL)
                put("source_status", sourceStatus)
                put("source_node_id", JSONObject.NULL)
                put("source_node_id_status", "FIELD_ABSENT")
                put("source_process_id", JSONObject.NULL)
                put("source_process_id_status", "FIELD_ABSENT")
                put("parser_source", "helper_accessibility_event")
                put("raw_reference", "${capture.reqId}:${event.eventTime}:${event.packageName}")
                put("captured_elapsed_realtime_ms", receivedElapsed)
                put("dispatch_uptime_ms", capture.dispatchUptimeMs ?: JSONObject.NULL)
                put("cursor_event_sequence", capture.cursorEventSequence)
            }
        }.getOrElse { error ->
            JSONObject().put("event_type", "TYPE_VIEW_CLICKED")
                .put("event_time_uptime_ms", event.eventTime)
                .put("package", event.packageName?.toString() ?: JSONObject.NULL)
                .put("source_status", "FIELD_PARSE_FAILED")
                .put("source_parse_error", error.javaClass.simpleName)
                .put("parser_source", "helper_accessibility_event")
                .put("raw_reference", "${capture.reqId}:${event.eventTime}:${event.packageName}")
                .put("captured_elapsed_realtime_ms", receivedElapsed)
                .put("cursor_event_sequence", capture.cursorEventSequence)
        }
        emit("ENTRY_CLICK_OBSERVED", capture.reqId, payload)
        return true
    }

    fun disarmEntryClickCapture(reqId: String): JSONObject {
        synchronized(this) {
            val capture = activeEntryClickCapture
            if (capture != null && capture.reqId != reqId) {
                return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_REQUEST_MISMATCH")
            }
            if (capture?.reqId == reqId) activeEntryClickCapture = null
        }
        val snapshot = entryClickSnapshot(reqId).put("ok", true).put("reason", "DISARMED")
        synchronized(this) {
            correlationByReqId.remove(reqId)
            eventsByReqId.remove(reqId)
        }
        return snapshot
    }

    fun entryClickSnapshot(reqId: String): JSONObject {
        val events = synchronized(eventsByReqId.getOrPut(reqId) { mutableListOf() }) {
            JSONArray().apply { eventsByReqId[reqId]?.forEach { put(JSONObject(it.toString())) } }
        }
        val capture = activeEntryClickCapture?.takeIf { it.reqId == reqId }
        return JSONObject().apply {
            put("reqId", reqId)
            put("transactionId", correlationByReqId[reqId]?.optString("transaction_id") ?: "")
            put("cursorEventSequence", capture?.cursorEventSequence ?: JSONObject.NULL)
            put("dispatchUptimeMs", capture?.dispatchUptimeMs ?: JSONObject.NULL)
            put("armedElapsedRealtimeMs", capture?.armedElapsedRealtimeMs ?: JSONObject.NULL)
            put("active", capture != null)
            put("evidenceEvents", events)
        }
    }

    fun requestedTarget(intent: Intent?): JSONObject {
        return JSONObject().apply {
            put("action", intent?.action ?: JSONObject.NULL)
            put("direction", intent?.getStringExtra("direction") ?: JSONObject.NULL)
            put("targetName", intent?.getStringExtra("targetName") ?: JSONObject.NULL)
            put("targetType", intent?.getStringExtra("targetType") ?: JSONObject.NULL)
            put("targetId", intent?.getStringExtra("targetId") ?: JSONObject.NULL)
            put("targetText", intent?.getStringExtra("targetText") ?: JSONObject.NULL)
            put("requestedBounds", intent?.getStringExtra("bounds") ?: JSONObject.NULL)
        }
    }

    fun attach(result: JSONObject, reqId: String): JSONObject {
        val correlation = correlationByReqId[reqId] ?: return result
        val events = synchronized(eventsByReqId.getOrPut(reqId) { mutableListOf() }) {
            JSONArray().apply { eventsByReqId[reqId]?.forEach { put(JSONObject(it.toString())) } }
        }
        Log.i(TAG, "[EVIDENCE][helper_response] requestId=$reqId transactionId=${correlation.optString("transaction_id")} SMART_NAV_RESULT_evidenceEvents=${events.length()}")
        return result
            .put("evidenceCorrelation", JSONObject(correlation.toString()))
            .put("evidenceEvents", events)
    }

    fun emit(eventType: String, reqId: String, payload: JSONObject = JSONObject()) {
        val correlation = correlationByReqId[reqId] ?: return
        runCatching {
            val event = JSONObject().apply {
                put("schemaVersion", "evidence-helper-v1")
                put("eventId", "helper_${reqId}_${eventSequence.incrementAndGet()}")
                put("eventType", eventType)
                put("timestamp", System.currentTimeMillis())
                put("reqId", reqId)
                put("correlation", JSONObject(correlation.toString()))
                put("payload", payload)
            }
            synchronized(eventsByReqId.getOrPut(reqId) { mutableListOf() }) {
                eventsByReqId[reqId]?.add(JSONObject(event.toString()))
            }
            emitTransportEvent(event, correlation)
        }
    }

    /**
     * Primary Helper-to-Runner transport.  Keep each record below logcat's
     * practical line limit; the full event remains available in the in-memory
     * snapshot for backward compatibility.
     */
    private fun emitTransportEvent(event: JSONObject, correlation: JSONObject) {
        val transport = JSONObject().apply {
            put("requestId", event.optString("reqId"))
            put("reqId", event.optString("reqId"))
            put("transactionId", correlation.optString("transaction_id"))
            put("eventId", event.optString("eventId"))
            put("eventType", event.optString("eventType"))
            put("timestamp", event.optLong("timestamp"))
            put("correlation", JSONObject(correlation.toString()))
            put("payload", boundValue(event.opt("payload"), 0))
            put("chunkCount", 1)
        }
        // The bounded payload normally fits.  Preserve required correlation and
        // event identity even if an unexpected value still makes it too large.
        if (transport.toString().length > MAX_EVENT_LOG_CHARS) {
            transport.put("payload", JSONObject().put("transportTruncated", true))
        }
        val serialized = transport.toString()
        Log.i(
            TAG,
            "[EVIDENCE][event_emit] requestId=${transport.optString("requestId")} " +
                "transactionId=${transport.optString("transactionId")} eventId=${transport.optString("eventId")} " +
                "eventType=${transport.optString("eventType")} serializedLength=${serialized.length} chunkCount=1"
        )
        Log.i(TAG, "$EVENT_LOG_PREFIX $serialized")
    }

    private fun boundValue(value: Any?, depth: Int): Any {
        if (depth >= 5) return JSONObject.NULL
        return when (value) {
            is JSONObject -> JSONObject().apply {
                val keys = value.keys()
                var kept = 0
                while (keys.hasNext() && kept < 32) {
                    val key = keys.next()
                    if (key == "children") {
                        put("childrenOmitted", true)
                    } else {
                        put(key, boundValue(value.opt(key), depth + 1))
                    }
                    kept += 1
                }
                if (keys.hasNext()) put("fieldsOmitted", true)
            }
            is JSONArray -> JSONArray().apply {
                val limit = minOf(value.length(), 8)
                for (index in 0 until limit) put(boundValue(value.opt(index), depth + 1))
                if (value.length() > limit) put(JSONObject().put("itemsOmitted", value.length() - limit))
            }
            is String -> if (value.length <= MAX_TRANSPORT_TEXT_CHARS) value else value.take(MAX_TRANSPORT_TEXT_CHARS)
            else -> value ?: JSONObject.NULL
        }
    }

    fun clear(reqId: String) {
        correlationByReqId.remove(reqId)
        eventsByReqId.remove(reqId)
    }

    fun snapshotAndClear(reqId: String): JSONObject {
        val result = JSONObject().apply {
            put("reqId", reqId)
            put("evidenceEvents", synchronized(eventsByReqId[reqId] ?: mutableListOf<JSONObject>()) {
                JSONArray().apply { eventsByReqId[reqId]?.forEach { put(JSONObject(it.toString())) } }
            })
        }
        val eventTypes = (0 until result.getJSONArray("evidenceEvents").length())
            .map { index -> result.getJSONArray("evidenceEvents").optJSONObject(index)?.optString("eventType").orEmpty() }
            .filter { it.isNotBlank() }
        Log.i(TAG, "[EVIDENCE][helper_buffer] lookupKey=$reqId eventCount=${eventTypes.size} eventTypes=$eventTypes")
        // Retain correlation through the final 1000ms delayed observation.  This
        // never changes navigation and lets the primary per-event log transport
        // carry late records even when the legacy snapshot is requested early.
        cleanupHandler.postDelayed({ clear(reqId) }, 1500L)
        return result
    }
}
