package com.example.a11yhelper

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yNavigatorTest {

    @Test
    fun matchesTarget_matchesText() {
        val query = A11yNavigator.TargetQuery(targetText = "확인", targetViewId = null)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "확인",
            nodeViewId = "com.test:id/ok",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_matchesViewId() {
        val query = A11yNavigator.TargetQuery(targetText = null, targetViewId = "com.test:id/submit")

        val matched = A11yNavigator.matchesTarget(
            nodeText = "제출",
            nodeViewId = "com.test:id/submit",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_returnsFalseWhenNoMatch() {
        val query = A11yNavigator.TargetQuery(targetText = "확인", targetViewId = "com.test:id/ok")

        val matched = A11yNavigator.matchesTarget(
            nodeText = "취소",
            nodeViewId = "com.test:id/cancel",
            query = query
        )

        assertFalse(matched)
    }
}
