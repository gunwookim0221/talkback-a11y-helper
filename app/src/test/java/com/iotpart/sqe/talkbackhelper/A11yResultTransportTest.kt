package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class A11yResultTransportTest {
    @Test
    fun allResultTypesShareBoundaryAndDigestContract() {
        for (prefix in listOf("TARGET_ACTION_RESULT", "SMART_NAV_RESULT", "EVIDENCE_EVENTS_RESULT")) {
            for (size in listOf(1000, 3999, 4096, 4101, 8192, 16384)) {
                val serialized = "{\"reqId\":\"req\",\"data\":\"" + "가".repeat(size / 3) + "\"}"
                val records = A11yResultTransport.encode(prefix, "req", serialized)
                assertEquals(records, A11yResultTransport.encode(prefix, "req", serialized))
                assertTrue(records.all { it.toByteArray(Charsets.UTF_8).size < 2700 })
                if (records.first().contains("_CHUNK ")) {
                    val decoded = records.map { Base64.getDecoder().decode(it.substringAfter(" payload=")) }
                        .reduce { left, right -> left + right }
                    assertEquals(serialized, decoded.toString(Charsets.UTF_8))
                    val digest = java.security.MessageDigest.getInstance("SHA-256").digest(decoded)
                        .joinToString("") { "%02x".format(it.toInt() and 0xff) }
                    records.forEachIndexed { index, record ->
                        assertTrue(record.contains("index=$index count=${records.size} sha256=$digest "))
                    }
                } else assertEquals("$prefix $serialized", records.single())
            }
        }
    }
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

    @Test
    fun largeHierarchyResultUsesFewerBoundedChunksWithSameDigestContract() {
        val serialized = "{\"reqId\":\"hierarchy\",\"nodes\":[\"${"가".repeat(8000)}\"]}"
        val records = A11yResultTransport.encode(
            "DUMP_HIERARCHY_RESULT",
            "hierarchy",
            serialized,
            chunkBytes = A11yResultTransport.HIERARCHY_CHUNK_BYTES,
        )

        assertTrue(records.size > 1)
        assertTrue(records.all { it.toByteArray(Charsets.UTF_8).size < 4000 })
        val decodedChunks = records.map { record ->
            Base64.getDecoder().decode(record.substringAfter(" payload="))
        }
        assertTrue(decodedChunks.all { it.size <= A11yResultTransport.HIERARCHY_CHUNK_BYTES })
        assertEquals(serialized, decodedChunks.reduce { left, right -> left + right }.toString(Charsets.UTF_8))
        assertTrue(records.all { it.contains("sha256=") })
    }
}
