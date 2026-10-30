package com.iotpart.sqe.talkbackhelper

import android.util.AtomicFile
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
class HierarchyPayloadStoreAtomicWritePruneTest {
    @get:Rule val temporaryFolder = TemporaryFolder()

    @Test
    fun statusPruningPreservesActiveAtomicFilePastRetention() {
        var elapsed = 100L
        val requestId = "0123456789abcdef0123456789abcdef"
        val clientNonce = "abcdef0123456789abcdef0123456789"
        val initialQueryNonce = "11111111111111111111111111111111"
        val statusQueryNonce = "22222222222222222222222222222222"
        val serviceId = "service-instance-test"
        val buildId = "a".repeat(64)
        val gitCommit = "b".repeat(40)
        val helperIdentity = JSONObject()
            .put("build_id", buildId)
            .put("git_commit", gitCommit)
            .put("input_digest", "c".repeat(64))
            .put("source_state", "CLEAN")
            .put("build_variant", "debug")
        val store = HierarchyPayloadStore(
            temporaryFolder.newFolder(),
            UUID.randomUUID().toString(),
            elapsedRealtimeMs = { elapsed },
            helperIdentity = helperIdentity,
        )
        store.serviceConnected(serviceId)
        val accepted = store.begin(requestId, clientNonce, initialQueryNonce, buildId, gitCommit, serviceId)
        assertEquals("ACCEPTED", accepted.getString("status"))
        val handle = HierarchyPayloadStore.RequestHandle(requestId, clientNonce, accepted.getLong("generation"))
        assertTrue(store.markCollecting(handle))
        assertNotNull(store.reserveCaptureSequence(handle))

        val recordsField = store.javaClass.getDeclaredField("records").apply { isAccessible = true }
        val records = recordsField.get(store) as Map<*, *>
        val record = records[requestId] ?: throw AssertionError("accepted record missing")
        record.javaClass.getDeclaredField("state").apply { isAccessible = true }.set(record, "WRITING")
        val readyMethod = store.javaClass.getDeclaredMethod("readyFile", record.javaClass).apply { isAccessible = true }
        val readyFile = readyMethod.invoke(store, record) as File
        val atomicFile = AtomicFile(readyFile)
        val stream = atomicFile.startWrite()
        val payload = byteArrayOf(1, 2, 3, 4)
        var finished = false
        try {
            stream.write(payload)
            stream.flush()
            val activeNewFile = File(readyFile.path + ".new")
            assertTrue("AtomicFile .new exists before status", activeNewFile.exists())
            val orphan = File(readyFile.parentFile, "hierarchy_unrelated.ready.new").apply { writeBytes(byteArrayOf(9)) }

            elapsed += HierarchyPayloadStore.RETENTION_MS + 1L
            val duringWrite = store.status(requestId, clientNonce, statusQueryNonce)
            assertEquals("WRITING", duringWrite.getString("status"))
            assertTrue("status prune removed the active AtomicFile .new", activeNewFile.exists())
            assertFalse("unrelated orphan should still be pruned", orphan.exists())

            atomicFile.finishWrite(stream)
            finished = true
            assertTrue("AtomicFile did not publish the ready file", readyFile.exists())
            val afterFinish = store.status(requestId, clientNonce, statusQueryNonce)
            assertEquals("WRITING", afterFinish.getString("status"))
            assertTrue("status prune removed the published file before record binding", readyFile.exists())
            assertArrayEquals(payload, atomicFile.openRead().use { it.readBytes() })
        } finally {
            if (!finished) runCatching { atomicFile.failWrite(stream) }
            runCatching { atomicFile.delete() }
        }
    }
}
