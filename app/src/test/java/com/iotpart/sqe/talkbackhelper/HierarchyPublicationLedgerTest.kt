package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class HierarchyPublicationLedgerTest {
    private var now = 1_000_000_000L
    private val ledger = HierarchyPublicationLedger({ now }, "process-test")

    private fun begin(id: String = "req-1"): HierarchyPublicationLedger.RequestHandle {
        ledger.serviceConnected("service-test")
        return ledger.beginRequest(id, "service-test", "build", "commit", "input", "DIRTY", 35, "15")
            .handle ?: error("request admission failed")
    }

    private fun frame(
        request: HierarchyPublicationLedger.RequestHandle,
        sequence: Int,
        type: HierarchyPublicationLedger.FrameType = HierarchyPublicationLedger.FrameType.CHUNK,
        chunkIndex: Int? = sequence,
        chunkCount: Int? = 2,
        text: String = "DUMP_HIERARCHY_RESULT_CHUNK reqId=req-1 index=$sequence count=2 sha256=${"a".repeat(64)} payload=YQ==",
    ): HierarchyPublicationLedger.FrameHandle = ledger.recordConstructed(
        request,
        HierarchyPublicationLedger.FrameSpec(type, sequence, chunkIndex, chunkCount, 2, 1, ByteArray(32) { 0x61 }, 4, "Log.i(String,String)"),
        text,
    ) ?: error("frame descriptor failed")

    private fun finish(request: HierarchyPublicationLedger.RequestHandle) {
        ledger.markPlanComplete(request)
        ledger.finishRequest(request)
    }

    private fun summary(id: String = "req-1", nonce: String = "nonce-1") =
        ledger.summary(id, nonce, "process-test", "service-test")

    @Test fun recordsExactFrameFingerprintAndApiReturnWithoutClaimingDelivery() {
        val request = begin()
        val message = "DUMP_HIERARCHY_RESULT_CHUNK reqId=req-1 index=0 count=2 sha256=${"a".repeat(64)} payload=YQ=="
        val frame = frame(request, 0, text = message)
        var calls = 0
        assertEquals(1, ledger.emit(frame) { calls++; 1 })
        assertEquals(1, calls)
        finish(request)
        val plan = ledger.page("req-1", "nonce-2", "process-test", "service-test", request.generation, 1,
            summary().getString("report_digest"), "PLAN", 0)
        val attempt = ledger.page("req-1", "nonce-3", "process-test", "service-test", request.generation, 1,
            summary().getString("report_digest"), "ATTEMPTS", 0)
        val row = plan.getJSONArray("records").getJSONObject(0)
        assertEquals(HierarchyPublicationLedger.STORAGE_BYTES, ledger.storageBytesForTest())
        assertEquals(true, row.getBoolean("b"))
        assertEquals(true, row.getBoolean("at"))
        assertTrue(row.toString().toByteArray(Charsets.UTF_8).size <= HierarchyPublicationLedger.MAX_ROW_JSON_BYTES)
        assertEquals(message.toByteArray(Charsets.UTF_8).size, row.getInt("mb"))
        assertEquals(java.security.MessageDigest.getInstance("SHA-256").digest(message.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }, row.getString("d"))
        assertEquals("A11Y_HELPER", plan.optString("tag", "A11Y_HELPER"))
        assertEquals(1, attempt.getJSONArray("records").getJSONObject(0).getInt("rv"))
        assertTrue(attempt.getJSONArray("records").getJSONObject(0).getBoolean("ok"))
        assertEquals("POSITIVE", attempt.getJSONArray("records").getJSONObject(0).getString("rc"))
        assertFalse(summary().getBoolean("sha_frame_applicable"))
        assertFalse(plan.toString().contains("payload=YQ=="))
    }

    @Test fun zeroNegativeAndThrownLogResultsRemainDistinctAndOriginalThrowableEscapes() {
        val request = begin()
        val zero = frame(request, 0)
        val negative = frame(request, 1, text = "frame-negative")
        val thrown = frame(request, 2, text = "frame-thrown")
        assertEquals(0, ledger.emit(zero) { 0 })
        assertEquals(-13, ledger.emit(negative) { -13 })
        val original = IllegalStateException("logger failure")
        try {
            ledger.emit(thrown) { throw original }
            fail("logger exception must be rethrown")
        } catch (actual: Throwable) {
            assertSame(original, actual)
        }
        finish(request)
        val page = ledger.page("req-1", "nonce", "process-test", "service-test", request.generation, 1,
            summary().getString("report_digest"), "ATTEMPTS", 0).getJSONArray("records")
        assertEquals("ZERO", page.getJSONObject(0).getString("rc"))
        assertEquals("NEGATIVE", page.getJSONObject(1).getString("rc"))
        assertEquals(-13, page.getJSONObject(1).getInt("rv"))
        assertEquals("THREW", page.getJSONObject(2).getString("rc"))
        assertEquals("ILLEGAL_STATE", page.getJSONObject(2).getString("ec"))
        assertNull(page.getJSONObject(2).opt("rv").takeUnless { it == org.json.JSONObject.NULL })
        assertTrue(summary().getBoolean("evidence_complete"))
    }

    @Test fun descriptorsAndAttemptsAreIndependentAndUnattemptedDoesNotInventAnAttempt() {
        val request = begin()
        frame(request, 0)
        finish(request)
        assertEquals(1, summary().getInt("descriptor_count"))
        assertEquals(0, summary().getInt("attempt_count"))
        assertEquals(0, summary().getInt("attempt_page_count"))
    }

    @Test fun requestIsolationRetentionAndTenMinuteExpiryAreBounded() {
        val first = begin("r1"); frame(first, 0); finish(first)
        val second = begin("r2"); frame(second, 0); finish(second)
        val third = begin("r3"); frame(third, 0); finish(third)
        val fourth = begin("r4"); frame(fourth, 0); finish(fourth)
        val fifth = begin("r5"); frame(fifth, 0); finish(fifth)
        assertEquals("NOT_RETAINED_OR_NOT_REGISTERED", ledger.summary("r1", "n", "process-test", "service-test").getString("status"))
        assertEquals("r2", ledger.summary("r2", "n", "process-test", "service-test").getString("request_id"))
        now += 10L * 60L * 1_000_000_000L + 1L
        assertEquals("EXPIRED", ledger.summary("r2", "n", "process-test", "service-test").getString("status"))
        val afterExpiry = begin("r6")
        frame(afterExpiry, 0); finish(afterExpiry)
        assertEquals(4, HierarchyPublicationLedger.MAX_REQUESTS)
    }

    @Test fun activeRequestsAreNotEvictedWhenCapacityIsFull() {
        for (index in 1..4) begin("active-$index")
        val blocked = ledger.beginRequest("active-5", "service-test", "build", "commit", "input", "DIRTY", 35, "15")
        assertNull(blocked.handle)
        assertEquals("LEDGER_CAPACITY_UNAVAILABLE", blocked.reason)
    }

    @Test fun duplicateRequestIdAndRestartAreExplicitlyRejected() {
        val first = begin("same")
        val duplicate = ledger.beginRequest("same", "service-test", "build", "commit", "input", "DIRTY", 35, "15")
        assertNull(duplicate.handle)
        assertEquals("AMBIGUOUS_REQUEST_ID", duplicate.reason)
        frame(first, 0); finish(first)
        assertEquals("AMBIGUOUS_REQUEST_ID",
            ledger.summary("same", "nonce", "process-test", "service-test").getString("status"))
        assertEquals("PUBLICATION_EVIDENCE_UNAVAILABLE_AFTER_RESTART",
            ledger.summary("same", "nonce", "other-process", "service-test").getString("status"))
        ledger.serviceConnected("service-new")
        assertEquals("PUBLICATION_EVIDENCE_UNAVAILABLE_AFTER_RESTART",
            ledger.summary("same", "nonce", "process-test", "service-test").getString("status"))
        assertEquals("NOT_RETAINED_OR_NOT_REGISTERED",
            ledger.summary("same", "nonce", "process-test", "service-new").getString("status"))
    }

    @Test fun queryPagesBindNonceEpochGenerationRevisionAndDigest() {
        val request = begin()
        frame(request, 0)
        finish(request)
        val reportDigest = summary().getString("report_digest")
        assertEquals("QUERY_NONCE_INVALID", ledger.summary("r", "bad nonce", "process-test", "service-test").getString("status"))
        assertEquals("PUBLICATION_EVIDENCE_UNAVAILABLE_AFTER_RESTART", ledger.summary("req-1", "n", "other", "service-test").getString("status"))
        assertEquals("REPORT_REVISION_MISMATCH", ledger.page("req-1", "n", "process-test", "service-test", request.generation + 1, 1,
            reportDigest, "PLAN", 0).getString("status"))
        assertEquals("REPORT_REVISION_MISMATCH", ledger.page("req-1", "n", "process-test", "service-test", request.generation, 2,
            reportDigest, "PLAN", 0).getString("status"))
        assertEquals("REPORT_REVISION_MISMATCH", ledger.page("req-1", "n", "process-test", "service-test", request.generation, 1,
            "0".repeat(64), "PLAN", 0).getString("status"))
    }

    @Test fun planOverflowMakesEvidenceIncompleteWithoutChangingPublicationBehavior() {
        val request = begin()
        var constructed = 0
        repeat(HierarchyPublicationLedger.MAX_RECORDS_PER_REQUEST) { index ->
            if (frameOrNull(request, index) != null) constructed++
        }
        assertEquals(HierarchyPublicationLedger.MAX_RECORDS_PER_REQUEST, constructed)
        val overflow = ledger.recordConstructed(request,
            HierarchyPublicationLedger.FrameSpec(HierarchyPublicationLedger.FrameType.END, 292, priority = 4, overload = "Log.i(String,String)"),
            "DUMP_HIERARCHY_END req-1")
        assertNull(overflow)
        ledger.markPlanComplete(request)
        ledger.finishRequest(request)
        assertFalse(summary().getBoolean("evidence_complete"))
        assertTrue(summary().getBoolean("overflow"))
    }

    private fun frameOrNull(request: HierarchyPublicationLedger.RequestHandle, sequence: Int) = runCatching {
        frame(request, sequence, text = "message-$sequence")
    }.getOrNull()
}
