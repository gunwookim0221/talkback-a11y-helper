package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yNavigationSelectionTest {

    @Test
    fun normalizedCurrentCandidate_keepsExistingNextBehavior() {
        val nextIndex = A11yNavigator.advancePastCurrentCandidateIndex(
            traversalList = listOf("Carbon monoxide detector", "History"),
            currentIndex = 0,
            nextIndex = 1,
            isSameCandidate = { current, candidate -> current == candidate }
        )

        assertEquals(1, nextIndex)
    }

    @Test
    fun focusedChildOfClickableAncestor_isNotSelectedAsNext() {
        data class Candidate(val id: String, val parent: String?)
        val ancestor = Candidate("card", null)
        val focusedChild = Candidate("title", "card")
        val history = Candidate("history", "card")

        val nextIndex = A11yNavigator.advancePastCurrentCandidateIndex(
            traversalList = listOf(ancestor, focusedChild, history),
            currentIndex = 0,
            nextIndex = 1,
            isSameCandidate = { current, candidate -> current.id == candidate.id },
            actualCurrent = focusedChild,
            isSameAsActualCurrent = { current, candidate -> current.id == candidate.id }
        )

        assertEquals(2, nextIndex)
    }

    @Test
    fun focusedChild_followedByDistinctSibling_selectsSibling() {
        data class Candidate(val id: String)
        val current = Candidate("title")
        val sibling = Candidate("history")

        val nextIndex = A11yNavigator.advancePastCurrentCandidateIndex(
            traversalList = listOf(current, current.copy(), sibling),
            currentIndex = 0,
            nextIndex = 1,
            isSameCandidate = { left, right -> left.id == right.id },
            actualCurrent = current,
            isSameAsActualCurrent = { left, right -> left.id == right.id }
        )

        assertEquals(2, nextIndex)
    }

    @Test
    fun stableEquivalentActualFocusIdentity_isExcluded() {
        data class Candidate(val stableId: String)
        val actual = Candidate("title")

        val nextIndex = A11yNavigator.advancePastCurrentCandidateIndex(
            traversalList = listOf(Candidate("card"), Candidate("title"), Candidate("history")),
            currentIndex = 0,
            nextIndex = 1,
            isSameCandidate = { left, right -> left.stableId == right.stableId },
            actualCurrent = actual,
            isSameAsActualCurrent = { left, right -> left.stableId == right.stableId }
        )

        assertEquals(2, nextIndex)
    }

    @Test
    fun ancestorWithMultipleDescendants_onlyExcludesActualDescendant() {
        data class Candidate(val id: String, val actionable: Boolean)
        val actualChild = Candidate("title", actionable = false)
        val unrelatedDescendant = Candidate("history", actionable = true)
        val otherDescendant = Candidate("clear", actionable = true)

        val nextIndex = A11yNavigator.advancePastCurrentCandidateIndex(
            traversalList = listOf(Candidate("card", actionable = true), actualChild, unrelatedDescendant, otherDescendant),
            currentIndex = 0,
            nextIndex = 1,
            isSameCandidate = { left, right -> left.id == right.id },
            actualCurrent = actualChild,
            isSameAsActualCurrent = { left, right -> left.id == right.id }
        )

        assertEquals(2, nextIndex)
        assertTrue(unrelatedDescendant.actionable)
        assertTrue(otherDescendant.actionable)
    }

    @Test
    fun noDistinctCandidate_remainsTerminal() {
        val nextIndex = A11yNavigator.advancePastCurrentCandidateIndex(
            traversalList = listOf("card", "title"),
            currentIndex = 0,
            nextIndex = 1,
            isSameCandidate = { _, _ -> true },
            actualCurrent = "title",
            isSameAsActualCurrent = { left, right -> left == right }
        )

        assertEquals(2, nextIndex)
    }

    @Test
    fun ambiguousCandidateIdentity_failsClosed() {
        val nextIndex = A11yNavigator.advancePastCurrentCandidateIndex(
            traversalList = listOf("card", "unknown", "history"),
            currentIndex = 0,
            nextIndex = 1,
            isSameCandidate = { _, _ -> false },
            actualCurrent = "title",
            isSameAsActualCurrent = { _, _ -> null }
        )

        assertEquals(3, nextIndex)
    }

    @Test
    fun staleCurrentFocusEvidence_failsClosed() {
        val nextIndex = A11yNavigator.advancePastCurrentCandidateIndex(
            traversalList = listOf("first", "second"),
            currentIndex = -1,
            nextIndex = 0,
            isSameCandidate = { _, _ -> false },
            actualCurrent = "stale",
            isSameAsActualCurrent = { _, _ -> false }
        )

        assertEquals(2, nextIndex)
    }

    @Test
    fun flatPhoneOrdering_isUnchanged() {
        val nextIndex = A11yNavigator.advancePastCurrentCandidateIndex(
            traversalList = listOf("one", "two", "three"),
            currentIndex = 1,
            nextIndex = 2,
            isSameCandidate = { left, right -> left == right }
        )

        assertEquals(2, nextIndex)
    }
}
