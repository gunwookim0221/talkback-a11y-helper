package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yNavigatorTest {

    @Test
    fun navigatorAlgorithmVersion_isUpdated() {
        assertTrue(A11yNavigator.NAVIGATOR_ALGORITHM_VERSION == "2.5.9")
    }



    @Test
    fun findScrollableForwardAncestorCandidate_returnsNearestScrollableAncestorWithForwardAction() {
        data class Node(
            val name: String,
            val scrollable: Boolean,
            val hasScrollForwardAction: Boolean,
            var parent: Node? = null
        )

        val root = Node(name = "root", scrollable = true, hasScrollForwardAction = true)
        val nonScrollableParent = Node(name = "nonScrollableParent", scrollable = false, hasScrollForwardAction = true, parent = root)
        val leaf = Node(name = "leaf", scrollable = false, hasScrollForwardAction = false, parent = nonScrollableParent)

        val result = A11yNavigator.findScrollableForwardAncestorCandidate(
            node = leaf,
            parentOf = { it.parent },
            isScrollable = { it.scrollable },
            hasScrollForwardAction = { it.hasScrollForwardAction }
        )

        assertTrue(result == root)
    }

    @Test
    fun shouldExcludeNodeByIdentity_returnsTrueWhenViewIdMatches() {
        val excluded = A11yNavigator.shouldExcludeNodeByIdentity(
            nodeViewId = "com.test:id/item_title",
            nodeText = "거실",
            excludeViewId = "com.test:id/item_title",
            excludeText = "다른 텍스트"
        )

        assertTrue(excluded)
    }

    @Test
    fun shouldExcludeNodeByIdentity_returnsTrueWhenTextMatches() {
        val excluded = A11yNavigator.shouldExcludeNodeByIdentity(
            nodeViewId = "com.test:id/item_title_2",
            nodeText = "  거실 조명  ",
            excludeViewId = "com.test:id/item_title",
            excludeText = "거실 조명"
        )

        assertTrue(excluded)
    }

    @Test
    fun shouldExcludeNodeByIdentity_returnsFalseWhenBothDoNotMatch() {
        val excluded = A11yNavigator.shouldExcludeNodeByIdentity(
            nodeViewId = "com.test:id/item_title_2",
            nodeText = "거실",
            excludeViewId = "com.test:id/item_title",
            excludeText = "침실"
        )

        assertFalse(excluded)
    }

    @Test
    fun shouldReuseExistingAccessibilityFocus_returnsTrueWhenAlreadyFocused_afterScroll() {
        val reused = A11yNavigator.shouldReuseExistingAccessibilityFocus(
            isAccessibilityFocused = true,
            isScrollAction = true
        )

        assertTrue(reused)
    }

    @Test
    fun shouldReuseExistingAccessibilityFocus_returnsFalseWhenNotFocused_afterScroll() {
        val reused = A11yNavigator.shouldReuseExistingAccessibilityFocus(
            isAccessibilityFocused = false,
            isScrollAction = true
        )

        assertFalse(reused)
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
    fun hasScrollableDownCandidateByAction_returnsTrueWhenVisibleScrollableAndActionExist() {
        data class ScrollActionState(
            val visible: Boolean,
            val scrollable: Boolean,
            val hasScrollForwardAction: Boolean
        )
        val nodes = listOf(
            ScrollActionState(visible = false, scrollable = true, hasScrollForwardAction = true),
            ScrollActionState(visible = true, scrollable = true, hasScrollForwardAction = true)
        )

        val result = A11yNavigator.hasScrollableDownCandidateByAction(
            nodesInOrder = nodes,
            isVisibleToUser = { it.visible },
            isScrollable = { it.scrollable },
            hasScrollForwardAction = { it.hasScrollForwardAction }
        )

        assertTrue(result)
    }

    @Test
    fun hasScrollableDownCandidateByAction_returnsFalseWhenActionDoesNotExist() {
        data class ScrollActionState(
            val visible: Boolean,
            val scrollable: Boolean,
            val hasScrollForwardAction: Boolean
        )
        val nodes = listOf(
            ScrollActionState(visible = true, scrollable = true, hasScrollForwardAction = false),
            ScrollActionState(visible = true, scrollable = false, hasScrollForwardAction = true)
        )

        val result = A11yNavigator.hasScrollableDownCandidateByAction(
            nodesInOrder = nodes,
            isVisibleToUser = { it.visible },
            isScrollable = { it.scrollable },
            hasScrollForwardAction = { it.hasScrollForwardAction }
        )

        assertFalse(result)
    }


    @Test
    fun isBottomNavigationBarNode_returnsFalseForBottomAreaWithoutIdentifier() {
        val result = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = null,
            boundsInScreen = Rect(0, 1850, 1080, 1915),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertFalse(result)
    }

    @Test
    fun isBottomNavigationBarNode_returnsTrueForTabLayoutClass() {
        val result = A11yNavigator.isBottomNavigationBarNode(
            className = "com.google.android.material.tabs.TabLayout",
            viewIdResourceName = null,
            boundsInScreen = Rect(0, 200, 1080, 320),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertTrue(result)
    }



    @Test
    fun isTopAppBarNode_returnsFalseForTopAreaWithoutIdentifier() {
        val result = A11yNavigator.isTopAppBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = null,
            boundsInScreen = Rect(0, 0, 1080, 180),
            screenTop = 0,
            screenHeight = 1920
        )

        assertFalse(result)
    }

    @Test
    fun isTopAppBarNode_returnsTrueForToolbarClass() {
        val result = A11yNavigator.isTopAppBarNode(
            className = "androidx.appcompat.widget.Toolbar",
            viewIdResourceName = null,
            boundsInScreen = Rect(0, 0, 1080, 210),
            screenTop = 0,
            screenHeight = 1920
        )

        assertTrue(result)
    }

    @Test
    fun isTopAppBarNode_returnsTrueForHeaderViewId() {
        val result = A11yNavigator.isTopAppBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.test:id/header_container",
            boundsInScreen = Rect(0, 300, 1080, 500),
            screenTop = 0,
            screenHeight = 1920
        )

        assertTrue(result)
    }


    @Test
    fun isTopAppBarNode_returnsTrueForMoreMenuViewId() {
        val result = A11yNavigator.isTopAppBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.test:id/more_menu_button",
            boundsInScreen = Rect(0, 400, 1080, 520),
            screenTop = 0,
            screenHeight = 1920
        )

        assertTrue(result)
    }


    @Test
    fun isTopAppBarNode_returnsTrueForNewViewIdKeywords() {
        val homeButton = A11yNavigator.isTopAppBarNode(
            className = "android.widget.ImageButton",
            viewIdResourceName = "com.test:id/home_button",
            boundsInScreen = Rect(0, 500, 1080, 620),
            screenTop = 0,
            screenHeight = 1920
        )
        val tabTitle = A11yNavigator.isTopAppBarNode(
            className = "android.widget.TextView",
            viewIdResourceName = "com.test:id/tab_title_main",
            boundsInScreen = Rect(0, 520, 1080, 640),
            screenTop = 0,
            screenHeight = 1920
        )
        val headerBar = A11yNavigator.isTopAppBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.test:id/header_bar",
            boundsInScreen = Rect(0, 540, 1080, 660),
            screenTop = 0,
            screenHeight = 1920
        )

        assertTrue(homeButton)
        assertTrue(tabTitle)
        assertTrue(headerBar)
    }

    @Test
    fun isBottomNavigationBarNode_returnsTrueForNewViewIdKeywords() {
        val menuPrefix = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.samsung.android.oneconnect:id/menu_favorites",
            boundsInScreen = Rect(0, 200, 1080, 320),
            screenBottom = 1920,
            screenHeight = 1920
        )
        val tabPrefix = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.test:id/tab_devices",
            boundsInScreen = Rect(0, 220, 1080, 340),
            screenBottom = 1920,
            screenHeight = 1920
        )
        val bottomNav = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.test:id/bottom_nav_host",
            boundsInScreen = Rect(0, 240, 1080, 360),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertTrue(menuPrefix)
        assertTrue(tabPrefix)
        assertTrue(bottomNav)
    }

    @Test
    fun isBottomNavigationBarNode_returnsTrueForMenuBarViewId() {
        val result = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.test:id/main_menu_bar",
            boundsInScreen = Rect(0, 600, 1080, 760),
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
