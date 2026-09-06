package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yDeviceCollectionSelectorTest {
    private fun candidate(
        key: String,
        directCards: Int,
        ownedCards: Int = directCards,
        depth: Int = 1,
        forward: Boolean = true,
        backward: Boolean = false,
        fresh: Boolean = true,
        value: String = key,
    ) = A11yDeviceCollectionCandidate(
        value = value,
        key = key,
        visible = true,
        enabled = true,
        scrollable = true,
        directCardCount = directCards,
        ownedCardCount = ownedCards,
        minimumCardDepth = depth,
        supportsForward = forward,
        supportsBackward = backward,
        fresh = fresh,
    )

    @Test
    fun outerViewPagerAndNestedCollectionSelectNestedCollection() {
        val pager = candidate("pager", directCards = 0, ownedCards = 12, depth = 2)
        val collection = candidate("collection", directCards = 12, backward = true)

        assertEquals(collection, A11yDeviceCollectionSelector.select(listOf(pager, collection)))
    }

    @Test
    fun firstScrollableBfsOrderDoesNotDetermineTarget() {
        val pager = candidate("pager", directCards = 0, ownedCards = 12, depth = 2)
        val collection = candidate("collection", directCards = 12)

        assertEquals("collection", A11yDeviceCollectionSelector.select(listOf(pager, collection))?.key)
    }

    @Test
    fun validatedCollectionWithBackwardSupportPerformsOneBoundedBackward() {
        val selected = A11yDeviceCollectionSelector.select(
            listOf(candidate("collection", directCards = 3, backward = true))
        )

        val decision = A11yDeviceCollectionActionPolicy.decide(selected, backward = true)
        assertEquals(A11yDeviceCollectionScrollDecision.PERFORM_BACKWARD, decision)
        assertEquals(8192, A11yDeviceCollectionActionPolicy.actionId(decision))
        assertEquals(
            A11yDeviceCollectionScrollDecision.REJECT,
            A11yDeviceCollectionActionPolicy.decide(selected, backward = true, attemptsMade = 1)
        )
    }

    @Test
    fun successfulMovementRequiresFreshEvidenceAtSelectionBoundary() {
        val stale = candidate("collection", directCards = 3, backward = true, fresh = false)
        assertNull(A11yDeviceCollectionSelector.select(listOf(stale)))
    }

    @Test
    fun validatedCollectionWithoutBackwardEstablishesTopBoundary() {
        val selected = A11yDeviceCollectionSelector.select(
            listOf(candidate("collection", directCards = 3, backward = false))
        )

        assertEquals(
            A11yDeviceCollectionScrollDecision.TOP_BOUNDARY,
            A11yDeviceCollectionActionPolicy.decide(selected, backward = true)
        )
        assertNull(
            A11yDeviceCollectionActionPolicy.actionId(
                A11yDeviceCollectionActionPolicy.decide(selected, backward = true)
            )
        )
    }

    @Test
    fun arbitraryScrollableNodeWithoutBackwardCannotEstablishTop() {
        val arbitrary = candidate("arbitrary", directCards = 0, ownedCards = 0, backward = false)
        assertNull(A11yDeviceCollectionSelector.select(listOf(arbitrary)))
    }

    @Test
    fun viewPagerWithoutBackwardCannotEstablishTop() {
        val pager = candidate("pager", directCards = 0, ownedCards = 4, depth = 2, backward = false)
        assertNull(A11yDeviceCollectionSelector.select(listOf(pager)))
    }

    @Test
    fun ambiguousCollectionOwnershipFailsClosed() {
        val first = candidate("first", directCards = 3)
        val second = candidate("second", directCards = 3)
        assertNull(A11yDeviceCollectionSelector.select(listOf(first, second)))
    }

    @Test
    fun staleCollectionEvidenceFailsClosed() {
        val stale = candidate("collection", directCards = 3, fresh = false)
        assertNull(A11yDeviceCollectionSelector.select(listOf(stale)))
    }

    @Test
    fun unsupportedActionIsNeverInvoked() {
        val selected = A11yDeviceCollectionSelector.select(
            listOf(candidate("collection", directCards = 3, forward = false))
        )
        val decision = A11yDeviceCollectionActionPolicy.decide(selected, backward = false)
        assertEquals(A11yDeviceCollectionScrollDecision.REJECT, decision)
        assertNull(A11yDeviceCollectionActionPolicy.actionId(decision))
    }

    @Test
    fun boundedActionLimitIsPreserved() {
        val selected = A11yDeviceCollectionSelector.select(
            listOf(candidate("collection", directCards = 3, backward = true))
        )
        assertEquals(
            A11yDeviceCollectionScrollDecision.REJECT,
            A11yDeviceCollectionActionPolicy.decide(selected, backward = true, maxAttempts = 0)
        )
    }

    @Test
    fun phoneAndFlipCollectionTopologyRemainsCompatible() {
        val legacyRecycler = candidate("content_recycler", directCards = 2, backward = true)
        val selected = A11yDeviceCollectionSelector.select(listOf(legacyRecycler))
        assertSame(legacyRecycler, selected)
        assertTrue(selected?.supportsForward == true)
    }
}
