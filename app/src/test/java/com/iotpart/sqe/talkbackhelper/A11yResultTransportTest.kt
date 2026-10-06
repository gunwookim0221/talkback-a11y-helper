package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class A11yResultTransportTest {
    @Test
    fun smallResultKeepsLegacyLogFormat() {
        val serialized = "{\"reqId\":\"req-1\",\"success\":true}"
        val records = A11yResultTransport.encode("TARGET_ACTION_RESULT", "req-1", serialized)

        assertEquals(1, records.size)
        assertTrue(records.single().startsWith("TARGET_ACTION_RESULT {"))
    }

    @Test
    fun largeKoreanResultUsesBoundedUtf8ChunksWithDigest() {
        val message = "위치 설정 \"완료\"\\n" + "가".repeat(5000)
        val serialized = "{\"reqId\":\"req-2\",\"success\":true,\"message\":\"$message\"}"

        val records = A11yResultTransport.encode("TARGET_ACTION_RESULT", "req-2", serialized)

        assertTrue(records.size > 1)
        assertTrue(records.all { it.toByteArray(Charsets.UTF_8).size < 2700 })
        val decoded = records.map { record ->
            val payload = record.substringAfter(" payload=")
            Base64.getDecoder().decode(payload)
        }.reduce { left, right -> left + right }
        assertEquals(serialized, decoded.toString(Charsets.UTF_8))
    }
}
