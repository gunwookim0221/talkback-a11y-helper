package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yNavigatorTest {

    @Test
    fun navigatorAlgorithmVersion_isUpdated() {
        assertTrue(A11yNavigator.NAVIGATOR_ALGORITHM_VERSION == "2.1.0")
    }


    @Test
    fun hasScrollableDownCandidate_returnsTrueWhenScrollableAndCanScrollDownExist() {
        data class ScrollState(val scrollable: Boolean, val canScrollDown: Boolean)
        val nodes = listOf(
            ScrollState(scrollable = false, canScrollDown = true),
            ScrollState(scrollable = true, canScrollDown = true)
        )

        val result = A11yNavigator.hasScrollableDownCandidate(
            nodesInOrder = nodes,
            isScrollable = { it.scrollable },
            canScrollVerticallyDown = { it.canScrollDown }
        )

        assertTrue(result)
    }

    @Test
    fun isSystemNavigationBarNode_returnsTrueForBottomArea() {
        val result = A11yNavigator.isSystemNavigationBarNode(
            className = "android.widget.LinearLayout",
            boundsInScreen = Rect(0, 1750, 1080, 1910),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertTrue(result)
    }

    @Test
    fun isSystemNavigationBarNode_returnsTrueForTabLayoutClass() {
        val result = A11yNavigator.isSystemNavigationBarNode(
            className = "com.google.android.material.tabs.TabLayout",
            boundsInScreen = Rect(0, 200, 1080, 320),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertTrue(result)
    }

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




    @Test
    fun shouldExcludeAsEmptyShell_returnsTrueForClickableNodeWithoutMergedLabel() {
        val excluded = A11yNavigator.shouldExcludeAsEmptyShell(
            mergedText = null,
            mergedContentDescription = "   ",
            clickable = true,
            childCount = 2
        )

        assertTrue(excluded)
    }

    @Test
    fun shouldExcludeAsEmptyShell_returnsFalseWhenMergedLabelExists() {
        val excluded = A11yNavigator.shouldExcludeAsEmptyShell(
            mergedText = "확인",
            mergedContentDescription = null,
            clickable = true,
            childCount = 3
        )

        assertFalse(excluded)
    }

    @Test
    fun shouldExcludeAsEmptyShell_returnsTrueForNonClickableLeafWithoutMergedLabel() {
        val excluded = A11yNavigator.shouldExcludeAsEmptyShell(
            mergedText = null,
            mergedContentDescription = null,
            clickable = false,
            childCount = 0
        )

        assertTrue(excluded)
    }

    @Test
    fun shouldExcludeAsEmptyShell_returnsFalseForNonClickableParentWithoutMergedLabel() {
        val excluded = A11yNavigator.shouldExcludeAsEmptyShell(
            mergedText = null,
            mergedContentDescription = null,
            clickable = false,
            childCount = 1
        )

        assertFalse(excluded)
    }

    private data class FakeNode(
        val name: String,
        val clickable: Boolean = false,
        val focusable: Boolean = false,
        val visible: Boolean = true,
        var parent: FakeNode? = null
    )

    private data class PositionedFakeNode(
        val name: String,
        val bounds: Rect,
        var parent: PositionedFakeNode? = null
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

    @Test
    fun compareByContainmentAndPosition_parentNodeComesFirstRegardlessOfCoordinates() {
        val parent = PositionedFakeNode(name = "card", bounds = Rect(200, 200, 300, 300))
        val child = PositionedFakeNode(name = "power", bounds = Rect(10, 10, 20, 20), parent = parent)

        val compared = A11yNavigator.compareByContainmentAndPosition(
            left = parent,
            right = child,
            parentOf = { it.parent },
            boundsOf = { it.bounds }
        )

        assertTrue(compared < 0)
    }

    @Test
    fun compareByContainmentAndPosition_childNodeComesAfterParentRegardlessOfCoordinates() {
        val parent = PositionedFakeNode(name = "card", bounds = Rect(200, 200, 300, 300))
        val child = PositionedFakeNode(name = "power", bounds = Rect(10, 10, 20, 20), parent = parent)

        val compared = A11yNavigator.compareByContainmentAndPosition(
            left = child,
            right = parent,
            parentOf = { it.parent },
            boundsOf = { it.bounds }
        )

        assertTrue(compared > 0)
    }

}
