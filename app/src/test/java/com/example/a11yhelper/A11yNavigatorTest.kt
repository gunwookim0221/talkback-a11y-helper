package com.example.a11yhelper

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yNavigatorTest {

    @Test
    fun matchesTarget_matchesText() {
        val query = A11yNavigator.TargetQuery(targetText = "확인", targetViewId = null, targetClassName = null)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "확인",
            nodeViewId = "com.test:id/ok",
            nodeClassName = "android.widget.Button",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_matchesViewId() {
        val query = A11yNavigator.TargetQuery(targetText = null, targetViewId = "com.test:id/submit", targetClassName = null)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "제출",
            nodeViewId = "com.test:id/submit",
            nodeClassName = "android.widget.Button",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_returnsFalseWhenNoMatch() {
        val query = A11yNavigator.TargetQuery(targetText = "확인", targetViewId = "com.test:id/ok", targetClassName = null)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "취소",
            nodeViewId = "com.test:id/cancel",
            nodeClassName = "android.widget.Button",
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_requiresAllProvidedConditions() {
        val query = A11yNavigator.TargetQuery(
            targetText = "확인",
            targetViewId = "com.test:id/ok",
            targetClassName = "android.widget.Button"
        )

        val matched = A11yNavigator.matchesTarget(
            nodeText = "확인",
            nodeViewId = "com.test:id/ok",
            nodeClassName = "android.widget.TextView",
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_matchesWhenAllProvidedConditionsMeet() {
        val query = A11yNavigator.TargetQuery(
            targetText = "확인",
            targetViewId = "com.test:id/ok",
            targetClassName = "android.widget.Button"
        )

        val matched = A11yNavigator.matchesTarget(
            nodeText = "확인",
            nodeViewId = "com.test:id/ok",
            nodeClassName = "android.widget.Button",
            query = query
        )

        assertTrue(matched)
    }
}
