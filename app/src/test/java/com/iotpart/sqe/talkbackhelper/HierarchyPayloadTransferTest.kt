package com.iotpart.sqe.talkbackhelper

import android.net.Uri
import android.content.pm.ProviderInfo
import android.os.ParcelFileDescriptor
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import java.io.FileNotFoundException
import java.nio.charset.StandardCharsets
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
class HierarchyPayloadTransferTest {
    @get:Rule val temporaryFolder = TemporaryFolder()

    private val requestId = "0123456789abcdef0123456789abcdef"
    private val clientNonce = "abcdef0123456789abcdef0123456789"
    private val initialQueryNonce = "11111111111111111111111111111111"
    private val serviceId = "service-instance-test"
    private val buildId = "a".repeat(64)
    private val gitCommit = "b".repeat(40)
    private val helperIdentity = JSONObject()
        .put("build_id", buildId)
        .put("git_commit", gitCommit)
        .put("input_digest", "c".repeat(64))
        .put("source_state", "CLEAN")
        .put("build_variant", "debug")

    private data class Ready(
        val store: HierarchyPayloadStore,
        val handle: HierarchyPayloadStore.RequestHandle,
        val response: JSONObject,
        val payload: ByteArray,
    )

    private fun beginAndPublish(payload: ByteArray = samplePayload()): Ready {
        val store = HierarchyPayloadStore(
            temporaryFolder.newFolder(),
            UUID.randomUUID().toString(),
            elapsedRealtimeMs = { 100L },
            helperIdentity = helperIdentity,
        )
        store.serviceConnected(serviceId)
        val accepted = store.begin(requestId, clientNonce, initialQueryNonce, buildId, gitCommit, serviceId)
        assertEquals("ACCEPTED", accepted.getString("status"))
        val handle = HierarchyPayloadStore.RequestHandle(requestId, clientNonce, accepted.getLong("generation"))
        assertTrue(store.markCollecting(handle))
        val ready = store.publish(handle, payload)
        return Ready(store, handle, ready, payload)
    }

    private fun samplePayload(): ByteArray {
        val node = JSONObject()
            .put("text", "안녕하세요 🌿\nline")
            .put("children", JSONArray())
        return JSONObject()
            .put("reqId", requestId)
            .put("success", true)
            .put("schemaVersion", HierarchyPayloadActions.PAYLOAD_SCHEMA)
            .put("nodeCount", 1)
            .put("nodes", JSONArray().put(node))
            .put("windows", JSONArray().put(JSONObject().put("root", node)))
            .toString()
            .toByteArray(StandardCharsets.UTF_8)
    }

    @Test
    fun publishPromotesRequestScopedFileAndBindsIdentityAndHashes() {
        val ready = beginAndPublish()
        val response = ready.response
        assertEquals("READY", response.getString("status"))
        assertTrue(response.getBoolean("completed"))
        assertTrue(response.getBoolean("payload_complete"))
        assertEquals(requestId, response.getString("request_id"))
        assertEquals(clientNonce, response.getString("client_nonce"))
        assertEquals(serviceId, response.getString("service_instance_id"))
        assertEquals(1, response.getLong("generation"))
        assertEquals(ready.payload.size, response.getInt("payload_bytes"))
        assertEquals(HierarchyPayloadEnvelope.sha256(ready.payload), response.getString("payload_sha256"))
        assertTrue(response.getString("payload_uri").contains("/$requestId/1/"))

        val file = ready.store.resolveReadyFile(Uri.parse(response.getString("payload_uri")))
        assertNotNull(file)
        val decoded = HierarchyPayloadEnvelope.decode(file!!.readBytes())
        assertEquals(requestId, decoded.header.getString("request_id"))
        assertEquals(serviceId, decoded.header.getString("service_instance_id"))
        assertArrayEquals(ready.payload, decoded.payload)
    }

    @Test
    fun orderedControlMetadataIsBoundedAndReportsThePayloadOnlyByHandle() {
        val ready = beginAndPublish()
        val encoded = HierarchyControlCodec.encode(ready.response)
        assertNotNull(encoded)
        assertTrue(encoded!!.length <= 12 * 1024)
        assertFalse(encoded.contains("안녕하세요"))
        val decoded = HierarchyControlCodec.decode(encoded)
        assertEquals(ready.response.getString("payload_uri"), decoded.getString("payload_uri"))
        assertEquals(ready.response.getString("payload_sha256"), decoded.getString("payload_sha256"))
    }

    @Test
    fun invalidRequestIdentityAndDuplicateRequestAreRejectedWithoutReplacingReadyFile() {
        val ready = beginAndPublish()
        val wrongNonce = ready.store.status(requestId, "0".repeat(32), "2".repeat(32))
        assertEquals("REQUEST_IDENTITY_MISMATCH", wrongNonce.getString("error_code"))
        val duplicate = ready.store.begin(requestId, "3".repeat(32), "4".repeat(32), buildId, gitCommit, serviceId)
        assertEquals("DUPLICATE_REQUEST", duplicate.getString("error_code"))
        assertEquals("READY", ready.store.status(requestId, clientNonce, "5".repeat(32)).getString("status"))
    }

    @Test
    fun serviceReconnectInvalidatesOldGenerationAndFile() {
        val ready = beginAndPublish()
        val uri = Uri.parse(ready.response.getString("payload_uri"))
        assertNotNull(ready.store.resolveReadyFile(uri))
        ready.store.serviceConnected("new-service-instance")
        assertNull(ready.store.resolveReadyFile(uri))
        val stale = ready.store.status(requestId, clientNonce, "6".repeat(32))
        assertEquals("REQUEST_NOT_FOUND", stale.getString("error_code"))
    }

    @Test
    fun providerLookupRejectsTraversalAndUnexpectedUriMetadata() {
        val ready = beginAndPublish()
        val valid = Uri.parse(ready.response.getString("payload_uri"))
        assertNull(ready.store.resolveReadyFile(Uri.parse("content://${HierarchyPayloadStore.PROVIDER_AUTHORITY}/v1/../latest")))
        assertNull(ready.store.resolveReadyFile(valid.buildUpon().appendQueryParameter("path", "../").build()))
    }

    @Test
    fun providerOpensOnlyExactReadyPayloadReadOnly() {
        val ready = beginAndPublish()
        val runtime = HierarchyPayloadRuntime
        val storeField = runtime.javaClass.getDeclaredField("store").apply { isAccessible = true }
        val previousStore = storeField.get(runtime)
        storeField.set(runtime, ready.store)
        val provider = HierarchyPayloadProvider()
        provider.attachInfo(RuntimeEnvironment.getApplication(), ProviderInfo())
        try {
            val uri = Uri.parse(ready.response.getString("payload_uri"))
            val bytes = ParcelFileDescriptor.AutoCloseInputStream(provider.openFile(uri, "r")).use { it.readBytes() }
            assertArrayEquals(ready.store.resolveReadyFile(uri)!!.readBytes(), bytes)
            assertThrows(SecurityException::class.java) { provider.openFile(uri, "w") }
            assertThrows(FileNotFoundException::class.java) {
                provider.openFile(Uri.parse("content://${HierarchyPayloadStore.PROVIDER_AUTHORITY}/v1/../../private"), "r")
            }
        } finally {
            storeField.set(runtime, previousStore)
        }
    }

    @Test
    fun payloadOverLimitFailsWithoutReadyPublication() {
        val ready = beginAndPublish(ByteArray(HierarchyPayloadEnvelope.MAX_PAYLOAD_BYTES + 1))
        assertEquals("FAILED", ready.response.getString("status"))
        assertEquals("PAYLOAD_TOO_LARGE", ready.response.getString("error_code"))
        assertFalse(ready.response.getBoolean("payload_complete"))
        assertNull(ready.store.resolveReadyFile(Uri.parse("content://${HierarchyPayloadStore.PROVIDER_AUTHORITY}/v1/x/$requestId/1/x")))
    }

    @Test
    fun serializedSizeIsBoundedBeforeCreatingThePayloadByteArray() {
        val tooLarge = JSONObject().put("text", "x".repeat(HierarchyPayloadEnvelope.MAX_PAYLOAD_BYTES + 1))
        assertTrue(HierarchyPayloadEnvelope.estimatedJsonUtf8Bytes(tooLarge) > HierarchyPayloadEnvelope.MAX_PAYLOAD_BYTES)
        val normal = JSONObject().put("text", "안녕하세요 🌿\nline")
        assertTrue(HierarchyPayloadEnvelope.estimatedJsonUtf8Bytes(normal) <= HierarchyPayloadEnvelope.MAX_PAYLOAD_BYTES)
    }

    @Test
    fun acknowledgementRequiresRequestIdentityAndBodyHashAndEchoesFreshQueryNonce() {
        val ready = beginAndPublish()
        ready.store.status(requestId, clientNonce, "7".repeat(32))
        val freshAckNonce = "8".repeat(32)
        val rejected = ready.store.acknowledge(requestId, clientNonce, freshAckNonce, "0".repeat(64))
        assertEquals("ACK_IDENTITY_MISMATCH", rejected.getString("error_code"))
        val accepted = ready.store.acknowledge(requestId, clientNonce, freshAckNonce, ready.response.getString("payload_sha256"))
        assertEquals("ACKED", accepted.getString("status"))
        assertEquals(clientNonce, accepted.getString("client_nonce"))
        assertEquals(freshAckNonce, accepted.getString("query_nonce"))
        assertNull(ready.store.resolveReadyFile(Uri.parse(ready.response.getString("payload_uri"))))
    }

    @Test
    fun cancellationRemovesReadyPayloadAndRequestRecord() {
        val ready = beginAndPublish()
        val uri = Uri.parse(ready.response.getString("payload_uri"))
        assertNotNull(ready.store.resolveReadyFile(uri))
        val cancelled = ready.store.cancel(requestId, clientNonce, "9".repeat(32))
        assertEquals("CANCELLED", cancelled.getString("status"))
        assertEquals("HOST_CANCELLED", cancelled.getString("error_code"))
        assertNull(ready.store.resolveReadyFile(uri))
        assertEquals("REQUEST_NOT_FOUND", ready.store.status(requestId, clientNonce, "a".repeat(32)).getString("error_code"))
    }

    @Test
    fun processRestartCleanupRemovesOnlyStaleEpochDirectories() {
        val root = temporaryFolder.newFolder()
        val active = java.io.File(root, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa").apply { mkdirs() }
        val stale = java.io.File(root, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb").apply { mkdirs() }
        java.io.File(stale, "hierarchy_stale.ready").writeBytes(byteArrayOf(1, 2, 3))
        val unrelated = java.io.File(root, "operator-notes").apply { mkdirs() }

        HierarchyPayloadRuntime.cleanupStaleProcessDirectories(root, active.name)

        assertTrue(active.isDirectory)
        assertFalse(stale.exists())
        assertTrue(unrelated.isDirectory)
    }

    @Test
    fun capabilityAndBeginRequireTheCurrentServiceAndCleanMatchingBuild() {
        val store = HierarchyPayloadStore(
            temporaryFolder.newFolder(),
            UUID.randomUUID().toString(),
            helperIdentity = helperIdentity.put("source_state", "DIRTY"),
        )
        store.serviceConnected(serviceId)
        val rejected = store.begin(requestId, clientNonce, initialQueryNonce, buildId, gitCommit, serviceId)
        assertEquals("IDENTITY_MISMATCH", rejected.getString("error_code"))
        val caps = store.capabilities("9".repeat(32))
        assertEquals("OK", caps.getString("status"))
        assertEquals(buildId, caps.getJSONObject("helper_build_identity").getString("build_id"))
    }

    @Test
    fun serviceUnavailableControlResponseKeepsRequestAndQueryCorrelation() {
        val response = HierarchyPayloadRuntime.unavailable(requestId, clientNonce, initialQueryNonce)
        assertEquals("FAILED", response.getString("status"))
        assertEquals("SERVICE_UNAVAILABLE", response.getString("error_code"))
        assertEquals(requestId, response.getString("request_id"))
        assertEquals(clientNonce, response.getString("client_nonce"))
        assertEquals(initialQueryNonce, response.getString("query_nonce"))
        assertFalse(response.getBoolean("payload_complete"))
    }
}
