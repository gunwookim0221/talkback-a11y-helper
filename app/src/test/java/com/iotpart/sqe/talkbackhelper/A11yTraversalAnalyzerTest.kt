package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yTraversalAnalyzerTest {

    @Test
    fun version_isUpdated() {
        assertEquals("1.3.0", A11yTraversalAnalyzer.VERSION)
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
