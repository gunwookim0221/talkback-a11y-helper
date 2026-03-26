package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import kotlin.math.abs

object A11yFocusExecutor {
    const val VERSION: String = "1.1.0"

    data class FocusExecutionResult(
        val success: Boolean,
        val attempts: Int,
        val lastFocusedBounds: Rect?
    )

    data class FocusVerificationResult(
        val resolved: Boolean,
        val snapBackDetected: Boolean,
        val actualFocusedBounds: Rect?
    )

    fun requestAccessibilityFocusWithRetry(
        target: AccessibilityNodeInfo,
        root: AccessibilityNodeInfo,
        maxAttempts: Int = 3,
        retryDelayMs: Long = 100L
    ): FocusExecutionResult {
        val targetBounds = Rect().also(target::getBoundsInScreen)
        var lastBounds: Rect? = null
        repeat(maxAttempts) { attempt ->
            target.refresh()
            val focused = target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            target.refresh()
            lastBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { Rect().also(it::getBoundsInScreen) }
            val resolved = focused || isTargetFocusResolved(target.isAccessibilityFocused, lastBounds, targetBounds)
            if (resolved) {
                return FocusExecutionResult(true, attempt + 1, lastBounds)
            }
            if (attempt < maxAttempts - 1) Thread.sleep(retryDelayMs)
        }
        return FocusExecutionResult(false, maxAttempts, lastBounds)
    }

    fun verifyFocusStabilizationAfterAction(
        root: AccessibilityNodeInfo,
        targetBounds: Rect,
        isTargetAccessibilityFocused: Boolean,
        settleDelayMs: Long = 100L
    ): FocusVerificationResult {
        Thread.sleep(settleDelayMs)
        val actualBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { Rect().also(it::getBoundsInScreen) }
        val snapBack = shouldTreatAsSnapBackAfterVerification(actualBounds, targetBounds, isTargetAccessibilityFocused)
        return FocusVerificationResult(
            resolved = !snapBack,
            snapBackDetected = snapBack,
            actualFocusedBounds = actualBounds
        )
    }

    internal fun shouldTreatAsSnapBackAfterVerification(
        actualFocusedBounds: Rect?,
        targetBounds: Rect,
        isTargetAccessibilityFocused: Boolean
    ): Boolean {
        if (isTargetAccessibilityFocused) return false
        if (actualFocusedBounds == null) return true
        return !isWithinSnapBackTolerance(targetBounds, actualFocusedBounds)
    }

    internal fun isTargetFocusResolved(
        isTargetAccessibilityFocused: Boolean,
        actualFocusedBounds: Rect?,
        targetBounds: Rect
    ): Boolean {
        if (isTargetAccessibilityFocused) return true
        if (actualFocusedBounds == null) return false
        return isWithinSnapBackTolerance(targetBounds, actualFocusedBounds)
    }

    private fun isWithinSnapBackTolerance(targetBounds: Rect, actualFocusedBounds: Rect, tolerancePx: Int = 10): Boolean {
        return abs(targetBounds.left - actualFocusedBounds.left) <= tolerancePx &&
            abs(targetBounds.top - actualFocusedBounds.top) <= tolerancePx &&
            abs(targetBounds.right - actualFocusedBounds.right) <= tolerancePx &&
            abs(targetBounds.bottom - actualFocusedBounds.bottom) <= tolerancePx
    }
}
