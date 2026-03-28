package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yTraversalAnalyzerTest {

    @Test
    fun version_isUpdated() {
        assertEquals("1.8.1", A11yTraversalAnalyzer.VERSION)
    }

    @Test
    fun isCompositeContentCardCandidate_acceptsLargeClickableFocusableCard() {
        val accepted = A11yTraversalAnalyzer.isCompositeContentCardCandidate(
            clickable = true,
            focusable = true,
            widthRatio = 0.93f,
            heightRatio = 0.24f,
            areaRatio = 0.22f,
            hasCompactRecoveredLabel = true,
            descendantInteractiveCount = 2
        )

        assertTrue(accepted)
    }

    @Test
    fun isCompositeContentCardCandidate_rejectsOverlyLargeContainer() {
        val accepted = A11yTraversalAnalyzer.isCompositeContentCardCandidate(
            clickable = true,
            focusable = true,
            widthRatio = 1.0f,
            heightRatio = 0.80f,
            areaRatio = 0.70f,
            hasCompactRecoveredLabel = true,
            descendantInteractiveCount = 3
        )

        assertFalse(accepted)
    }

    @Test
    fun selectPostScrollContinuationCandidate_acceptsNonNegativeIndex() {
        val analysis = A11yTraversalAnalyzer.analyzePostScrollState(
            treeChanged = true,
            anchorMaintained = true,
            newlyExposedCandidateExists = true
        )
        val result = A11yTraversalAnalyzer.selectPostScrollContinuationCandidate(3, analysis)

        assertEquals(3, result.index)
        assertTrue(result.accepted)
        assertEquals("accepted:newly_revealed_after_scroll", result.reasonCode)
    }

    @Test
    fun selectPostScrollContinuationCandidate_rejectsNegativeIndex() {
        val analysis = A11yTraversalAnalyzer.analyzePostScrollState(
            treeChanged = false,
            anchorMaintained = false,
            newlyExposedCandidateExists = false
        )
        val result = A11yTraversalAnalyzer.selectPostScrollContinuationCandidate(-1, analysis)

        assertEquals(-1, result.index)
        assertFalse(result.accepted)
        assertEquals("rejected:no_progress_after_scroll", result.reasonCode)
    }
}
