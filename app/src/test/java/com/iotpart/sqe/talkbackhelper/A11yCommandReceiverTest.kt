package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

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
}
