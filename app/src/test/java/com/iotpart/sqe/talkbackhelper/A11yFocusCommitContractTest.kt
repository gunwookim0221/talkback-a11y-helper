package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yFocusCommitContractTest {

    private fun identity(
        id: String? = "com.test:id/node",
        text: String? = "Node",
        bounds: Rect? = Rect(0, 100, 100, 200)
    ) = A11yFocusExecutor.FocusIdentitySnapshot(
        windowId = 1,
        packageName = "com.test",
        className = "android.widget.TextView",
        viewIdResourceName = id,
        text = text,
        contentDescription = null,
        bounds = bounds
    )

    @Test
    fun smartNext_focusAdvance_isMovedSuccess() {
        val target = identity(id = "com.test:id/next", text = "Next", bounds = Rect(0, 240, 100, 340))
        val decision = A11yFocusExecutor.decideFocusCommit(true, identity(text = "Current"), target, target, true, postFocusIsValidCandidate = true)
        assertTrue(decision.success)
        assertEquals(A11yFocusExecutor.FocusCommitDisposition.MOVED_TO_INTENDED, decision.disposition)
    }

    @Test
    fun smartNext_successfulAction_withUnchangedFocus_isNotMoved() {
        val current = identity()
        val decision = A11yFocusExecutor.decideFocusCommit(true, current, identity(), current, true, postFocusIsValidCandidate = true)
        assertFalse(decision.success)
        assertEquals(A11yFocusExecutor.FocusCommitDisposition.SAME_FOCUS, decision.disposition)
    }

    @Test
    fun unchangedFocus_cannotProduceMovedStatus() {
        val decision = A11yFocusExecutor.decideFocusCommit(
            true, identity(), identity(), identity(id = "com.test:id/next", text = "Next", bounds = Rect(0, 240, 100, 340)), true,
            postFocusIsValidCandidate = true
        )
        assertFalse(decision.success)
        assertEquals("same_focus_after_action", decision.reason)
    }

    @Test
    fun validNextCandidate_reachedByFocus_isMovedSuccess() {
        val current = identity(text = "Current")
        val next = identity(id = "com.test:id/history", text = "History", bounds = Rect(0, 240, 100, 340))
        assertTrue(A11yFocusExecutor.decideFocusCommit(true, current, next, next, true, postFocusIsValidCandidate = true).success)
    }

    @Test
    fun staleCurrentCandidate_failsClosed() {
        val next = identity(id = "com.test:id/next", text = "Next", bounds = Rect(0, 240, 100, 340))
        val decision = A11yFocusExecutor.decideFocusCommit(true, identity(), next, next, true, false, true)
        assertFalse(decision.success)
        assertEquals(A11yFocusExecutor.FocusCommitDisposition.STALE_TARGET, decision.disposition)
    }

    @Test
    fun staleNextCandidate_failsClosed() {
        val post = identity(id = "com.test:id/next", text = "Next", bounds = Rect(0, 240, 100, 340))
        val stale = identity(id = "com.test:id/stale", text = "Stale", bounds = Rect(0, 240, 100, 340))
        val decision = A11yFocusExecutor.decideFocusCommit(true, identity(text = "Current"), post, stale, false, postFocusIsValidCandidate = true)
        assertFalse(decision.success)
        assertEquals(A11yFocusExecutor.FocusCommitDisposition.STALE_TARGET, decision.disposition)
    }

    @Test
    fun ambiguousPostFocusIdentity_failsClosed() {
        val decision = A11yFocusExecutor.decideFocusCommit(
            true, identity(id = null, text = null, bounds = null), identity(id = null, text = null, bounds = null),
            identity(id = "com.test:id/next", text = "Next", bounds = Rect(0, 240, 100, 340)), true,
            postFocusIsValidCandidate = true
        )
        assertFalse(decision.success)
        assertEquals(A11yFocusExecutor.FocusCommitDisposition.AMBIGUOUS_POST_FOCUS, decision.disposition)
    }

    @Test
    fun failedFocusAction_cannotBecomeMoved() {
        val target = identity(id = "com.test:id/next", text = "Next", bounds = Rect(0, 240, 100, 340))
        val decision = A11yFocusExecutor.decideFocusCommit(false, identity(text = "Current"), target, target, true, postFocusIsValidCandidate = true)
        assertFalse(decision.success)
        assertEquals(A11yFocusExecutor.FocusCommitDisposition.ACTION_FAILED, decision.disposition)
    }

    @Test
    fun unavailablePostFocus_cannotBecomeMoved() {
        val target = identity(id = "com.test:id/next", text = "Next", bounds = Rect(0, 240, 100, 340))
        val decision = A11yFocusExecutor.decideFocusCommit(true, identity(text = "Current"), null, target, true, postFocusIsValidCandidate = false)
        assertFalse(decision.success)
        assertEquals(A11yFocusExecutor.FocusCommitDisposition.FOCUS_UNAVAILABLE, decision.disposition)
    }

    @Test
    fun duplicateText_withStrongerUnchangedIdentity_doesNotProveMovement() {
        val current = identity(id = "com.test:id/card_title", text = "History")
        val decision = A11yFocusExecutor.decideFocusCommit(
            true, current, identity(id = "com.test:id/card_title", text = "History"),
            identity(id = "com.test:id/history_button", text = "History", bounds = Rect(110, 100, 200, 200)), true,
            postFocusIsValidCandidate = true
        )
        assertFalse(decision.success)
        assertEquals(A11yFocusExecutor.FocusCommitDisposition.SAME_FOCUS, decision.disposition)
    }

    @Test
    fun normalSmartNext_advancedCandidate_remainsCompatible() {
        val next = identity(id = "com.test:id/next", text = "Next", bounds = Rect(0, 240, 100, 340))
        val decision = A11yFocusExecutor.decideFocusCommit(true, identity(text = "Current"), next, next, true, postFocusIsValidCandidate = true)
        assertTrue(decision.success)
        assertEquals(A11yFocusExecutor.FocusCommitDisposition.MOVED_TO_INTENDED, decision.disposition)
    }
}
