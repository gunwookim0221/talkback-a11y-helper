package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yHistoryManagerTest {

    @Test
    fun version_isUpdated() {
        assertEquals("1.4.0", A11yHistoryManager.VERSION)
    }

    @Test
    fun recordVisitedSignature_andSnapshot_workAsExpected() {
        A11yHistoryManager.clearVisitedHistory()

        A11yHistoryManager.recordVisitedSignature(
            label = "Privacy notice",
            viewId = "com.test:id/privacy_notice",
            bounds = Rect(0, 100, 1000, 240),
            nodeIdentity = "privacy-node"
        )

        val labels = A11yHistoryManager.snapshotVisitedHistoryLabels()
        val signatures = A11yHistoryManager.snapshotVisitedHistorySignatures()

        assertTrue(labels.contains("Privacy notice"))
        assertEquals(1, signatures.size)
    }

    @Test
    fun authoritativeFocusWindow_startAndClear_updatesWindowState() {
        val untilMs = System.currentTimeMillis() + 5_000L

        A11yHistoryManager.startAuthoritativeFocusWindow(
            untilMs = untilMs,
            label = "Committed Candidate",
            identity = "committed-node",
            bounds = Rect(0, 300, 1000, 500),
            status = "moved"
        )

        assertTrue(A11yHistoryManager.isWithinAuthoritativeFocusWindow(untilMs - 1))
        assertNotNull(A11yHistoryManager.authoritativeCommittedBounds())

        A11yHistoryManager.clearAuthoritativeFocusWindow()

        assertFalse(A11yHistoryManager.isWithinAuthoritativeFocusWindow(untilMs - 1))
        assertEquals(null, A11yHistoryManager.authoritativeCommittedBounds())
    }
}
