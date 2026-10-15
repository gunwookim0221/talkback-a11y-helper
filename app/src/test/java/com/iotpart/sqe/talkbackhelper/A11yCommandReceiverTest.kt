package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class A11yCommandReceiverTest {

    @Test
    fun systemLanguageUsesDedicatedServiceUnavailableStatus() {
        assertEquals(
            "HELPER_SERVICE_UNAVAILABLE",
            A11yCommandReceiver.HELPER_SERVICE_UNAVAILABLE_STATUS,
        )
    }

    @Test
    fun executeDumpTreeSafely_reportsSuccessWithoutFailureCallback() {
        var dumpCount = 0
        var failureReason: String? = null

        val result = A11yCommandReceiver().executeDumpTreeSafely(
            reqId = "success-request",
            dumpTree = { dumpCount += 1 },
            reportFailure = { failureReason = it },
            logError = { _, _ -> }
        )

        assertTrue(result)
        assertEquals(1, dumpCount)
        assertEquals(null, failureReason)
    }

    @Test
    fun executeDumpTreeSafely_reportsTraversalFailureWithoutPropagatingException() {
        var failureReason: String? = null
        var loggedMessage: String? = null
        var loggedError: Throwable? = null

        val result = A11yCommandReceiver().executeDumpTreeSafely(
            reqId = "failed-request",
            dumpTree = { throw IllegalArgumentException("cyclic comparator") },
            reportFailure = { failureReason = it },
            logError = { message, error ->
                loggedMessage = message
                loggedError = error
            }
        )

        assertFalse(result)
        assertTrue(failureReason.orEmpty().contains("Traversal analysis failed"))
        assertTrue(failureReason.orEmpty().contains("cyclic comparator"))
        assertEquals("[DUMP_TREE] failed req_id='failed-request'", loggedMessage)
        assertTrue(loggedError is IllegalArgumentException)
    }

    @Test
    fun pingPayloadIncludesBuildAndServiceIdentityWithoutChangingReadyFields() {
        val payload = A11yCommandReceiver().buildPingPayload("ping-build-test")
        assertEquals("ping-build-test", payload.getString("reqId"))
        assertTrue(payload.getBoolean("success"))
        assertEquals("READY", payload.getString("status"))
        val identity = payload.getJSONObject("helper_build_identity")
        assertEquals("1", identity.getString("schema_version"))
        assertEquals("talkback.exact-navigation.v1", identity.getString("helper_protocol_version"))
        assertTrue(identity.has("versionName"))
        assertTrue(identity.has("versionCode"))
        assertTrue(identity.has("build_id"))
        assertTrue(identity.has("git_commit"))
        assertTrue(identity.has("helper_input_digest"))
        assertTrue(identity.has("source_state"))
        assertTrue(identity.has("build_variant"))
        assertTrue(payload.getString("helper_service_instance_id").isNotBlank())
    }
}
