package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class A11yTargetFinderTest {

    @Test
    fun calculateBoundsCenter_returnsRectCenter_whenBoundsAreValid() {
        val center = A11yTargetFinder.calculateBoundsCenter(Rect(10, 20, 110, 220))
        assertEquals(Pair(60, 120), center)
    }

    @Test
    fun calculateBoundsCenter_returnsNull_whenBoundsAreEmpty() {
        val center = A11yTargetFinder.calculateBoundsCenter(Rect(0, 0, 0, 0))
        assertNull(center)
    }
}
