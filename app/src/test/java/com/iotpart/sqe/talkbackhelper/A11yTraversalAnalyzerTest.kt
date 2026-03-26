package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yTraversalAnalyzerTest {

    @Test
    fun version_isUpdated() {
        assertEquals("1.1.0", A11yTraversalAnalyzer.VERSION)
    }

    @Test
    fun selectPostScrollCandidate_acceptsNonNegativeIndex() {
        val result = A11yTraversalAnalyzer.selectPostScrollCandidate(3)

        assertEquals(3, result.index)
        assertTrue(result.accepted)
        assertEquals("accepted", result.reasonCode)
    }

    @Test
    fun selectPostScrollCandidate_rejectsNegativeIndex() {
        val result = A11yTraversalAnalyzer.selectPostScrollCandidate(-1)

        assertEquals(-1, result.index)
        assertFalse(result.accepted)
        assertEquals("missing", result.reasonCode)
    }
}
