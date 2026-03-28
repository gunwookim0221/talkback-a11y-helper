package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yFocusExecutorTest {

    @Test
    fun shouldTreatAsSnapBackAfterVerification_returnsFalse_whenTargetIsAccessibilityFocused() {
        val isSnapBack = A11yFocusExecutor.shouldTreatAsSnapBackAfterVerification(
            actualFocusedBounds = Rect(10, 10, 100, 100),
            targetBounds = Rect(0, 0, 100, 100),
            actualMatch = true
        )

        assertFalse(isSnapBack)
    }

    @Test
    fun shouldTreatAsSnapBackAfterVerification_returnsFalse_whenBoundsAreWithinTolerance() {
        val isSnapBack = A11yFocusExecutor.shouldTreatAsSnapBackAfterVerification(
            actualFocusedBounds = Rect(3, 4, 104, 106),
            targetBounds = Rect(0, 0, 100, 100),
            actualMatch = false
        )

        assertFalse(isSnapBack)
    }

    @Test
    fun isTargetFocusResolved_returnsFalse_whenActualFocusedNodeMissing() {
        val resolved = A11yFocusExecutor.isTargetFocusResolved(
            actualFocusedNode = null,
            actualFocusedBounds = Rect(220, 400, 1040, 620),
            targetBounds = Rect(220, 400, 1040, 620),
            expectedPackageName = "com.sample.app"
        )

        assertFalse(resolved)
    }

    @Test
    fun shouldTreatAsSnapBackAfterVerification_returnsTrue_whenBoundsMismatchAndTargetNotFocused() {
        val isSnapBack = A11yFocusExecutor.shouldTreatAsSnapBackAfterVerification(
            actualFocusedBounds = Rect(60, 60, 160, 160),
            targetBounds = Rect(0, 0, 100, 100),
            actualMatch = false
        )

        assertTrue(isSnapBack)
    }

    @Test
    fun isTargetFocusResolved_returnsFalse_whenActualBoundsMissing() {
        val resolved = A11yFocusExecutor.isTargetFocusResolved(
            actualFocusedNode = null,
            actualFocusedBounds = null,
            targetBounds = Rect(0, 0, 100, 100),
            expectedPackageName = "com.sample.app"
        )

        assertFalse(resolved)
    }
}
