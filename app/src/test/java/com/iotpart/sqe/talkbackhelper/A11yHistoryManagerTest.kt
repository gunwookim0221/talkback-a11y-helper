package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class A11yHistoryManagerTest {

    @Test
    fun version_isUpdated() {
        assertEquals("1.5.1", A11yHistoryManager.VERSION)
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

    @Test
    fun shouldSuppressPreCommitTransientSystemUiEvent_returnsFalse_whenNotInActiveTurn() {
        A11yHistoryManager.activeSmartNextTurnId = 0L
        A11yHistoryManager.clearTopChromeTransientSystemUiSuppression("test_setup")

        val suppressed = A11yHistoryManager.shouldSuppressPreCommitTransientSystemUiEvent(
            eventType = android.view.accessibility.AccessibilityEvent.TYPE_ANNOUNCEMENT,
            eventPackageName = "com.android.systemui",
            root = null
        )

        assertFalse(suppressed)
    }

    @Test
    fun shouldSuppressPreCommitTransientSystemUiEvent_usesFreshWorkerFocusPackageWithCurrentHistoryState() {
        A11yHistoryManager.activeSmartNextTurnId = 91L
        A11yHistoryManager.markFinalCommitTurn(0L)
        A11yHistoryManager.clearTopChromeTransientSystemUiSuppression("test_setup")
        A11yHistoryManager.startTopChromeTransientSystemUiSuppression("com.example.target")

        val suppressed = A11yHistoryManager.shouldSuppressPreCommitTransientSystemUiEvent(
            eventType = android.view.accessibility.AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            eventPackageName = "com.android.systemui",
            activeFocusPackage = "com.example.target"
        )
        val differentCurrentPackageSuppressed = A11yHistoryManager.shouldSuppressPreCommitTransientSystemUiEvent(
            eventType = android.view.accessibility.AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            eventPackageName = "com.android.systemui",
            activeFocusPackage = "com.example.other"
        )

        assertTrue(suppressed)
        assertFalse(differentCurrentPackageSuppressed)
        A11yHistoryManager.clearTopChromeTransientSystemUiSuppression("test_cleanup")
        A11yHistoryManager.activeSmartNextTurnId = 0L
    }

    @Test
    fun shouldIgnorePostCommitResurfacedHeader_dataSnapshotOverloadPreservesCurrentIdentityAndBoundsRules() {
        val committedBounds = Rect(0, 300, 800, 400)
        A11yHistoryManager.startAuthoritativeFocusWindow(
            untilMs = System.currentTimeMillis() + 5_000L,
            label = "Committed",
            identity = "stable-node-a",
            bounds = committedBounds,
            status = "moved"
        )

        val sameNodeIgnored = A11yHistoryManager.shouldIgnorePostCommitResurfacedHeader(
            candidateBounds = Rect(0, 500, 800, 600),
            candidateIdentity = "stable-node-b",
            candidateLabel = "Other",
            eventType = android.view.accessibility.AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED
        )
        val sameBoundsIgnored = A11yHistoryManager.shouldIgnorePostCommitResurfacedHeader(
            candidateBounds = Rect(committedBounds),
            candidateIdentity = "stable-node-b",
            candidateLabel = "Other",
            eventType = android.view.accessibility.AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED
        )
        val sameIdentityIgnored = A11yHistoryManager.shouldIgnorePostCommitResurfacedHeader(
            candidateBounds = Rect(0, 500, 800, 600),
            candidateIdentity = "stable-node-a",
            candidateLabel = "Other",
            eventType = android.view.accessibility.AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED
        )

        assertTrue(sameNodeIgnored)
        assertFalse(sameBoundsIgnored)
        assertFalse(sameIdentityIgnored)
        A11yHistoryManager.clearAuthoritativeFocusWindow()
    }
}
