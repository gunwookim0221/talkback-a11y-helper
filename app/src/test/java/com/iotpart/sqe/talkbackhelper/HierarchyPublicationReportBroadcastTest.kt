package com.iotpart.sqe.talkbackhelper

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowLog
import org.robolectric.shadows.ShadowLooper
import java.security.MessageDigest

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class HierarchyPublicationReportBroadcastTest {
    @Test fun capabilitiesArriveAsOrderedResultDataWithoutLogcatFallback() {
        val context = RuntimeEnvironment.getApplication()
        val action = "com.iotpart.sqe.talkbackhelper.GET_HIERARCHY_PUBLICATION_REPORT"
        val receiver = A11yCommandReceiver()
        context.registerReceiver(receiver, IntentFilter(action), Context.RECEIVER_EXPORTED)
        ShadowLog.clear()
        var resultCode = 0
        var resultData: String? = null
        val resultReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                resultCode = getResultCode()
                resultData = getResultData()
            }
        }
        try {
            context.sendOrderedBroadcast(
                Intent(action).putExtra("mode", "CAPABILITIES").putExtra("query_nonce", "capability-nonce-1"),
                null,
                resultReceiver,
                null,
                0,
                null,
                null,
            )
            ShadowLooper.idleMainLooper()
            assertEquals(HierarchyPublicationLedger.RESULT_SUCCESS, resultCode)
            val envelope = requireNotNull(resultData)
            assertTrue(envelope.startsWith("HPUB1."))
            assertTrue(envelope.toByteArray(Charsets.UTF_8).size <= HierarchyPublicationLedger.RESULT_DATA_LIMIT_BYTES)
            val pieces = envelope.removePrefix("HPUB1.").split('.')
            assertEquals(2, pieces.size)
            val bytes = android.util.Base64.decode(pieces[0], android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING)
            val digest = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 0xff) }
            assertEquals(digest, pieces[1])
            val json = JSONObject(bytes.toString(Charsets.UTF_8))
            assertEquals("capability-nonce-1", json.getString("query_nonce"))
            assertEquals(HierarchyPublicationLedger.REPORT_SCHEMA, json.getString("schema"))
            assertEquals(4, json.getInt("max_requests"))
            assertEquals(600_000, json.getLong("retention_ms"))
            assertFalse(ShadowLog.getLogsForTag("A11Y_HELPER").any { it.msg.contains("GET_HIERARCHY_PUBLICATION_REPORT") })
            assertFalse(ShadowLog.getLogsForTag("A11Y_HELPER").any { it.msg.contains("trace_enter") })
        } finally {
            context.unregisterReceiver(receiver)
        }
    }

    @Test fun orderedSummaryAndPageAreNonceEpochAndRevisionBound() {
        val ledger = A11yCommandReceiver.hierarchyPublicationLedger
        val serviceId = "query-service-" + System.nanoTime()
        ledger.serviceConnected(serviceId)
        val requestId = "query-request-" + System.nanoTime()
        val handle = requireNotNull(
            ledger.beginRequest(requestId, serviceId, "build", "commit", "input", "DIRTY", 35, "15").handle
        ) { "request must be admitted" }
        val message = "DUMP_HIERARCHY_END $requestId"
        val descriptor = requireNotNull(ledger.recordConstructed(
            handle,
            HierarchyPublicationLedger.FrameSpec(
                HierarchyPublicationLedger.FrameType.END,
                sequence = 0,
                priority = 4,
                overload = "Log.i(String,String)",
            ),
            message,
        )) { "descriptor must be recorded" }
        ledger.emit(descriptor) { 1 }
        ledger.markPlanComplete(handle)
        ledger.finishRequest(handle)

        val context = RuntimeEnvironment.getApplication()
        val action = "com.iotpart.sqe.talkbackhelper.GET_HIERARCHY_PUBLICATION_REPORT"
        val receiver = A11yCommandReceiver()
        context.registerReceiver(receiver, IntentFilter(action), Context.RECEIVER_EXPORTED)
        try {
            fun orderedQuery(intent: Intent): Pair<Int, JSONObject> {
                var code = 0
                var resultData: String? = null
                val callback = object : BroadcastReceiver() {
                    override fun onReceive(context: Context, intent: Intent) {
                        code = getResultCode()
                        resultData = getResultData()
                    }
                }
                context.sendOrderedBroadcast(intent, null, callback, null, 0, null, null)
                ShadowLooper.idleMainLooper()
                assertEquals(HierarchyPublicationLedger.RESULT_SUCCESS, code)
                val envelope = requireNotNull(resultData)
                val body = envelope.removePrefix("HPUB1.").substringBeforeLast('.')
                val bytes = android.util.Base64.decode(
                    body,
                    android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING,
                )
                return code to JSONObject(bytes.toString(Charsets.UTF_8))
            }

            val capNonce = "summary-cap-" + System.nanoTime()
            val (_, capabilities) = orderedQuery(
                Intent(action).putExtra("mode", "CAPABILITIES").putExtra("query_nonce", capNonce)
            )
            val processEpoch = capabilities.getString("process_epoch")
            val summaryNonce = "summary-" + System.nanoTime()
            val summaryIntent = Intent(action)
                .putExtra("mode", "SUMMARY")
                .putExtra("query_nonce", summaryNonce)
                .putExtra("request_id", requestId)
                .putExtra("expected_process_epoch", processEpoch)
                .putExtra("expected_service_instance_id", serviceId)
            val (_, summary) = orderedQuery(summaryIntent)
            assertEquals(summaryNonce, summary.getString("query_nonce"))
            assertTrue(summary.getBoolean("evidence_complete"))
            assertEquals(1, summary.getInt("descriptor_count"))
            val repeatedSummary = ledger.summary(requestId, "direct-repeat", processEpoch, serviceId)
            assertEquals(summary.getString("report_digest"), repeatedSummary.getString("report_digest"))

            val pageNonce = "page-" + System.nanoTime()
            val pageIntent = Intent(action)
                .putExtra("mode", "PLAN")
                .putExtra("query_nonce", pageNonce)
                .putExtra("request_id", requestId)
                .putExtra("expected_process_epoch", processEpoch)
                .putExtra("expected_service_instance_id", serviceId)
                .putExtra("capture_generation", summary.getLong("capture_generation"))
                .putExtra("report_revision", summary.getInt("report_revision"))
                .putExtra("report_digest", summary.getString("report_digest"))
                .putExtra("page_index", 0)
            val (_, page) = orderedQuery(pageIntent)
            assertEquals(requestId, page.getString("request_id"))
            assertEquals(pageNonce, page.getString("query_nonce"))
            assertEquals(summary.getString("report_digest"), page.getString("report_digest"))
            assertEquals("END", page.getJSONArray("records").getJSONObject(0).getString("t"))
        } finally {
            context.unregisterReceiver(receiver)
        }
    }
}
