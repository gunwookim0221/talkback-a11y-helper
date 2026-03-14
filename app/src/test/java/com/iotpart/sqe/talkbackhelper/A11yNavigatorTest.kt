package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yNavigatorTest {

    @Test
    fun matchesTarget_typeT_matchesTrimmedTextWithExactRegexFallback() {
        val query = A11yNavigator.TargetQuery(targetName = "수면환경", targetType = "t", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "  수면환경\n",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/title",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_typeB_matchesContentDescriptionWithExactRegexFallback() {
        val query = A11yNavigator.TargetQuery(targetName = "확인", targetType = "b", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "버튼",
            nodeContentDescription = "  확인  ",
            nodeViewId = "com.test:id/ok",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_typeT_matchesRegexPattern() {
        val query = A11yNavigator.TargetQuery(targetName = "수면.*설정", targetType = "t", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "수면환경 설정",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/title",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_typeB_matchesRegexPattern() {
        val query = A11yNavigator.TargetQuery(targetName = "확인\\s+버튼", targetType = "b", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "버튼",
            nodeContentDescription = "확인   버튼",
            nodeViewId = "com.test:id/ok",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_typeT_returnsFalseWhenRegexIsInvalid() {
        val query = A11yNavigator.TargetQuery(targetName = "수면[환경", targetType = "t", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "수면환경 설정",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/title",
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_typeB_returnsFalseWhenRegexIsInvalid() {
        val query = A11yNavigator.TargetQuery(targetName = "확인(버튼", targetType = "b", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "버튼",
            nodeContentDescription = "확인 버튼",
            nodeViewId = "com.test:id/ok",
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_typeR_matchesResourceIdRegex() {
        val query = A11yNavigator.TargetQuery(targetName = "com\\.test:id/sub.*", targetType = "r", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "제출",
            nodeContentDescription = "제출 버튼",
            nodeViewId = "com.test:id/submit",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_typeR_plainStringStillMatchesExactResourceId() {
        val query = A11yNavigator.TargetQuery(targetName = "com.test:id/submit", targetType = "r", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "제출",
            nodeContentDescription = "제출 버튼",
            nodeViewId = "com.test:id/submit",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_typeR_returnsFalseWhenRegexIsInvalid() {
        val query = A11yNavigator.TargetQuery(targetName = "com.test:id/[submit", targetType = "r", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "제출",
            nodeContentDescription = "제출 버튼",
            nodeViewId = "com.test:id/submit",
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_typeR_returnsFalseWhenNodeViewIdIsNull() {
        val query = A11yNavigator.TargetQuery(targetName = "com\\.test:id/sub.*", targetType = "r", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "제출",
            nodeContentDescription = "제출 버튼",
            nodeViewId = null,
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_typeA_matchesAnyCondition() {
        val query = A11yNavigator.TargetQuery(targetName = "안내", targetType = "a", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = null,
            nodeContentDescription = "안내",
            nodeViewId = "com.test:id/other",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_returnsFalseForUnsupportedType() {
        val query = A11yNavigator.TargetQuery(targetName = "확인", targetType = "x", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "확인",
            nodeContentDescription = "확인 버튼",
            nodeViewId = "com.test:id/ok",
            query = query
        )

        assertFalse(matched)
    }


    @Test
    fun matchesTarget_additionalConditions_allMustMatch() {
        val query = A11yNavigator.TargetQuery(
            targetName = "",
            targetType = "",
            targetIndex = 0,
            className = "Button",
            clickable = true,
            focusable = true,
            targetText = "확인",
            targetId = "com\\.test:id/ok.*"
        )

        val matched = A11yNavigator.matchesTarget(
            nodeText = "확인",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/ok_button",
            nodeClassName = "android.widget.Button",
            nodeClickable = true,
            nodeFocusable = true,
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_additionalConditions_returnsFalseWhenAnyFilterFails() {
        val query = A11yNavigator.TargetQuery(
            targetName = "",
            targetType = "",
            targetIndex = 0,
            clickable = false,
            targetText = "확인"
        )

        val matched = A11yNavigator.matchesTarget(
            nodeText = "확인",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/ok_button",
            nodeClassName = "android.widget.Button",
            nodeClickable = true,
            nodeFocusable = true,
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_typeT_dotInPlainText_isNotTreatedAsRegex() {
        val query = A11yNavigator.TargetQuery(targetName = "ver.1", targetType = "t", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "verx1 안내",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/title",
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_typeR_dotInPlainId_isExactMatchOnly() {
        val query = A11yNavigator.TargetQuery(targetName = "com.test:id/btn.ok", targetType = "r", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "확인",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/btnXok",
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_typeT_plainTextNoLongerContainsMatch() {
        val query = A11yNavigator.TargetQuery(targetName = "수면환경", targetType = "t", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "수면환경 설정",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/title",
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_typeB_plainTextNoLongerContainsMatch() {
        val query = A11yNavigator.TargetQuery(targetName = "확인", targetType = "b", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "버튼",
            nodeContentDescription = "확인 버튼",
            nodeViewId = "com.test:id/ok",
            query = query
        )

        assertFalse(matched)
    }

    @Test
    fun matchesTarget_typeT_regexIsCaseInsensitive() {
        val query = A11yNavigator.TargetQuery(targetName = "Pet.*", targetType = "t", targetIndex = 0)

        val matched = A11yNavigator.matchesTarget(
            nodeText = "pets",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/title",
            query = query
        )

        assertTrue(matched)
    }

    @Test
    fun matchesTarget_targetTextFilter_isCaseInsensitive() {
        val query = A11yNavigator.TargetQuery(
            targetName = "",
            targetType = "",
            targetIndex = 0,
            targetText = "Pet"
        )

        val matched = A11yNavigator.matchesTarget(
            nodeText = "pets",
            nodeContentDescription = null,
            nodeViewId = "com.test:id/title",
            query = query
        )

        assertTrue(matched)
    }



    private data class FakeNode(
        val name: String,
        val clickable: Boolean = false,
        val focusable: Boolean = false,
        val visible: Boolean = true,
        var parent: FakeNode? = null
    )

    @Test
    fun resolveToClickableAncestor_returnsNearestClickableParent() {
        val root = FakeNode(name = "root", clickable = false)
        val card = FakeNode(name = "card", clickable = true, parent = root)
        val title = FakeNode(name = "title", clickable = false, parent = card)

        val resolved = A11yNavigator.resolveToClickableAncestor(
            node = title,
            parentOf = { it.parent },
            isClickable = { it.clickable }
        )

        assertTrue(resolved == card)
    }

    @Test
    fun resolveToClickableAncestor_returnsOriginalNodeWhenNoClickableAncestor() {
        val root = FakeNode(name = "root", clickable = false)
        val title = FakeNode(name = "title", clickable = false, parent = root)

        val resolved = A11yNavigator.resolveToClickableAncestor(
            node = title,
            parentOf = { it.parent },
            isClickable = { it.clickable }
        )

        assertTrue(resolved == title)
    }

    @Test
    fun buildGroupedTraversalList_excludesChildrenInsideClickableParent() {
        val root = FakeNode(name = "root", clickable = false, focusable = false)
        val card = FakeNode(name = "card", clickable = true, focusable = true, parent = root)
        val icon = FakeNode(name = "icon", clickable = false, focusable = true, parent = card)
        val text = FakeNode(name = "text", clickable = false, focusable = true, parent = card)
        val standalone = FakeNode(name = "standalone", clickable = false, focusable = true, parent = root)

        val list = A11yNavigator.buildGroupedTraversalList(
            nodesInOrder = listOf(root, card, icon, text, standalone),
            parentOf = { it.parent },
            isClickable = { it.clickable },
            isFocusable = { it.focusable },
            isVisible = { it.visible }
        )

        assertTrue(list == listOf(card, standalone))
    }

    @Test
    fun buildGroupedTraversalList_excludesInvisibleNodes() {
        val root = FakeNode(name = "root", clickable = false, focusable = false)
        val visible = FakeNode(name = "visible", clickable = true, focusable = true, visible = true, parent = root)
        val invisible = FakeNode(name = "invisible", clickable = true, focusable = true, visible = false, parent = root)

        val list = A11yNavigator.buildGroupedTraversalList(
            nodesInOrder = listOf(root, visible, invisible),
            parentOf = { it.parent },
            isClickable = { it.clickable },
            isFocusable = { it.focusable },
            isVisible = { it.visible }
        )

        assertTrue(list == listOf(visible))
    }

}
