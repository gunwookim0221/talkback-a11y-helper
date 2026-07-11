package com.iotpart.sqe.talkbackhelper

import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import org.json.JSONObject
import org.json.JSONArray
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
