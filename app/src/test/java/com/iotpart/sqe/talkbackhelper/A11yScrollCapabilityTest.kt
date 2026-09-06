package com.iotpart.sqe.talkbackhelper

import android.view.accessibility.AccessibilityNodeInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yScrollCapabilityTest {
    private val forward = 4096
    private val backward = 8192
    private val up = 16908344
    private val down = 16908346

    @Test
    fun extractsForwardBackwardAndVerticalCapabilities() {
        val result = A11yScrollActionCapabilities.fromActionIds(listOf(forward, backward, up, down))

        assertTrue(result.scrollForwardSupported)
        assertTrue(result.scrollBackwardSupported)
        assertTrue(result.scrollUpSupported)
        assertTrue(result.scrollDownSupported)
    }

    @Test
    fun unsupportedActionsRemainFalse() {
        val result = A11yScrollActionCapabilities.fromActionIds(listOf(16))

        assertFalse(result.scrollForwardSupported)
        assertFalse(result.scrollBackwardSupported)
        assertFalse(result.scrollUpSupported)
        assertFalse(result.scrollDownSupported)
    }

    @Test
    fun multipleActionsAreRetainedOnceAndSortedDeterministically() {
        val result = A11yScrollActionCapabilities.fromActionIds(listOf(down, forward, down, 123456))

        assertEquals(listOf(forward, 123456, down), result.actions.map { it.id })
        assertEquals("ACTION_SCROLL_FORWARD", result.actions[0].name)
        assertEquals("ACTION_SCROLL_DOWN", result.actions[2].name)
    }

    @Test
    fun emptyActionListProducesEmptyFalseCapabilities() {
        val result = A11yScrollActionCapabilities.fromActionIds(emptyList())

        assertTrue(result.actions.isEmpty())
        assertFalse(result.scrollForwardSupported)
        assertFalse(result.scrollBackwardSupported)
        assertFalse(result.scrollUpSupported)
        assertFalse(result.scrollDownSupported)
    }

    @Test
    fun actionOrderIsDeterministicForSerialization() {
        val result = A11yScrollActionCapabilities.fromActionIds(listOf(backward, forward))

        assertEquals(
            listOf(
                forward to "ACTION_SCROLL_FORWARD",
                backward to "ACTION_SCROLL_BACKWARD"
            ),
            result.actions.map { it.id to it.name }
        )
    }
}
