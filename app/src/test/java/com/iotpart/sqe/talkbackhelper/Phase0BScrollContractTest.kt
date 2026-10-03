package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Phase0BScrollContractTest {
    @Test fun mixedAxisUsesDirectionalDownAndNeverHorizontalForward() {
        assertEquals(16908346, A11yNavigator.verticalScrollAction("down", listOf(4096,16908346,16908347)))
        assertEquals(null, A11yNavigator.verticalScrollAction("down", listOf(4096,16908344,16908347)))
    }
    @Test fun genericHorizontalActionsHaveHorizontalAxis() {
        assertEquals("HORIZONTAL", A11yNavigator.scrollAxis("android.view.View", listOf(4096, 8192, 16908345, 16908347)))
    }
    @Test fun genericForwardAloneHasUnknownAxis() {
        assertEquals("UNKNOWN", A11yNavigator.scrollAxis("android.view.View", listOf(4096)))
        assertFalse(A11yNavigator.isVerticalScrollClass("android.view.View"))
    }
    @Test fun bidirectionalActionsRemainExplicit() {
        assertEquals("BIDIRECTIONAL", A11yNavigator.scrollAxis("android.view.View", listOf(16908344,16908345)))
    }
    @Test fun directionalActionsOverrideRecyclerClassGuess() {
        assertEquals("HORIZONTAL", A11yNavigator.scrollAxis("RecyclerView", listOf(16908345)))
    }
    @Test fun pagerDoesNotBecomeVerticalFromForwardAction() {
        assertEquals("PAGER", A11yNavigator.scrollAxis("ViewPager", listOf(4096)))
    }
    @Test fun genericDownActionsAreVertical() {
        assertEquals("VERTICAL", A11yNavigator.scrollAxis("android.view.View", listOf(16908346)))
    }
    @Test fun directionalActionFallback() {
        assertEquals(16908346, A11yNavigator.verticalScrollAction("down", listOf(16908346)))
        assertEquals(16908344, A11yNavigator.verticalScrollAction("up", listOf(16908344)))
        assertEquals(4096, A11yNavigator.verticalScrollAction("down", listOf(4096, 16908346)))
        assertEquals(null, A11yNavigator.verticalScrollAction("down", listOf(16)))
    }
    @Test fun horizontalAndPagerAreExcludedFromVerticalSelection() {
        assertFalse(A11yNavigator.isVerticalScrollClass("android.widget.HorizontalScrollView"))
        assertFalse(A11yNavigator.isVerticalScrollClass("androidx.viewpager.widget.ViewPager"))
        assertFalse(A11yNavigator.isVerticalScrollClass("CustomPager"))
    }

    @Test fun gridAndRecyclerRemainEligible() {
        assertTrue(A11yNavigator.isVerticalScrollClass("android.widget.GridView"))
        assertTrue(A11yNavigator.isVerticalScrollClass("androidx.recyclerview.widget.RecyclerView"))
    }
}
