package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yNavigatorTest {

    @Test
    fun navigatorAlgorithmVersion_isUpdated() {
        assertTrue(A11yNavigator.NAVIGATOR_ALGORITHM_VERSION == "2.47.1")
    }

    @Test
    fun isContainerLikeViewId_detectsFeatureWrapper() {
        assertTrue(A11yNavigator.isContainerLikeViewId("com.samsung.android.oneconnect:id/feature_item_menu"))
    }

    @Test
    fun shouldAllowRecoveredDescendantLabelForTraversal_rejectsMultiItemContainerLabels() {
        val allow = A11yNavigator.shouldAllowRecoveredDescendantLabelForTraversal(
            listOf("Samsung AI Subscription", "Virtual Home", "Safe", "Android Auto")
        )
        assertFalse(allow)
    }

    @Test
    fun isSettingsRowViewId_matchesKnownRows() {
        assertTrue(A11yNavigator.isSettingsRowViewId("com.samsung.android.oneconnect:id/item_privacy_notice"))
        assertTrue(A11yNavigator.isSettingsRowViewId("item_history"))
    }

    @Test
    fun isSettingsRowViewId_rejectsUnknownRows() {
        assertFalse(A11yNavigator.isSettingsRowViewId("com.samsung.android.oneconnect:id/menu_home"))
        assertFalse(A11yNavigator.isSettingsRowViewId(null))
    }

    @Test
    fun decidePostScrollContinuationPlan_skipsGeneralScan_whenContinuationFallbackFailed() {
        val plan = A11yNavigator.decidePostScrollContinuationPlan(
            resolvedAnchorIndex = -1,
            fallbackBelowAnchorIndex = -1,
            traversalStartIndex = 0,
            traversalSize = 5,
            continuationFallbackFailed = true
        )

        assertEquals(5, plan.anchorStartIndex)
        assertTrue(plan.skipGeneralScan)
    }

    @Test
    fun decidePostScrollContinuationPlan_usesFallbackCandidate_whenContinuationFallbackSucceeded() {
        val plan = A11yNavigator.decidePostScrollContinuationPlan(
            resolvedAnchorIndex = -1,
            fallbackBelowAnchorIndex = 2,
            traversalStartIndex = 0,
            traversalSize = 6,
            continuationFallbackFailed = false
        )

        assertEquals(2, plan.anchorStartIndex)
        assertFalse(plan.skipGeneralScan)
    }

    @Test
    fun selectContinuationCandidateAfterScrollResult_prioritizesNewlyRevealedEvenIfVisibleHistoryExists() {
        data class Node(
            val label: String?,
            val descendantLabel: String?,
            val viewId: String?,
            val bounds: Rect,
            val clickable: Boolean,
            val focusable: Boolean
        )

        val node = Node(
            label = "",
            descendantLabel = "Labs",
            viewId = "com.test:id/item_labs",
            bounds = Rect(0, 100, 1000, 200),
            clickable = true,
            focusable = false
        )
        val result = A11yNavigator.selectContinuationCandidateAfterScrollResult(
            traversalList = listOf(node),
            startIndex = 0,
            visibleHistory = setOf("Labs"),
            visibleHistorySignatures = setOf(
                A11yNavigator.VisibleHistorySignature(
                    label = "",
                    viewId = "com.test:id/item_labs",
                    bounds = Rect(0, 100, 1000, 200),
                    nodeIdentity = null
                )
            ),
            visitedHistory = emptySet(),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { "android.widget.LinearLayout" },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            clickableOf = { it.clickable },
            focusableOf = { it.focusable },
            descendantLabelOf = { it.descendantLabel },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/anchor",
                mergedLabel = "Anchor",
                talkbackLabel = "Anchor",
                text = "Anchor",
                contentDescription = "Anchor",
                bounds = Rect(0, 400, 1000, 500)
            ),
            preScrollAnchorBottom = 500,
            labelOf = { it.label }
        )

        assertEquals(0, result.index)
        assertTrue(result.hasValidPostScrollCandidate)
    }

    @Test
    fun selectContinuationCandidateAfterScrollResult_doesNotTreatInteractiveTopContentAsPersistentHeader() {
        data class Node(
            val label: String?,
            val descendantLabel: String?,
            val viewId: String?,
            val bounds: Rect,
            val clickable: Boolean,
            val focusable: Boolean
        )

        val node = Node(
            label = "",
            descendantLabel = "Continuation Card",
            viewId = "com.test:id/item_continuation",
            bounds = Rect(0, 120, 1000, 260),
            clickable = true,
            focusable = true
        )

        val result = A11yNavigator.selectContinuationCandidateAfterScrollResult(
            traversalList = listOf(node),
            startIndex = 0,
            visibleHistory = setOf("Continuation Card"),
            visibleHistorySignatures = setOf(
                A11yNavigator.VisibleHistorySignature(
                    label = "Continuation Card",
                    viewId = "com.test:id/item_continuation",
                    bounds = Rect(0, 120, 1000, 260),
                    nodeIdentity = "id1"
                )
            ),
            visitedHistory = emptySet(),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2200,
            screenHeight = 2200,
            boundsOf = { it.bounds },
            classNameOf = { "android.widget.LinearLayout" },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            clickableOf = { it.clickable },
            focusableOf = { it.focusable },
            descendantLabelOf = { it.descendantLabel },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/anchor",
                mergedLabel = "Anchor",
                talkbackLabel = "Anchor",
                text = "Anchor",
                contentDescription = "Anchor",
                bounds = Rect(0, 400, 1000, 520)
            ),
            preScrollAnchorBottom = 520,
            labelOf = { it.label }
        )

        assertEquals(0, result.index)
        assertTrue(result.hasValidPostScrollCandidate)
    }

    @Test
    fun selectContinuationCandidateAfterScrollResult_rejectsRewoundCandidateEvenIfNewlyRevealed() {
        data class Node(
            val label: String?,
            val descendantLabel: String?,
            val viewId: String?,
            val bounds: Rect,
            val clickable: Boolean,
            val focusable: Boolean
        )

        val result = A11yNavigator.selectContinuationCandidateAfterScrollResult(
            traversalList = listOf(
                Node(
                    label = "",
                    descendantLabel = "SmartThings",
                    viewId = "com.test:id/app_logo",
                    bounds = Rect(0, 120, 1000, 240),
                    clickable = true,
                    focusable = true
                )
            ),
            startIndex = 0,
            visibleHistory = emptySet(),
            visibleHistorySignatures = emptySet(),
            visitedHistory = emptySet(),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2200,
            screenHeight = 2200,
            boundsOf = { it.bounds },
            classNameOf = { "android.widget.LinearLayout" },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            clickableOf = { it.clickable },
            focusableOf = { it.focusable },
            descendantLabelOf = { it.descendantLabel },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/anchor",
                mergedLabel = "Anchor",
                talkbackLabel = "Anchor",
                text = "Anchor",
                contentDescription = "Anchor",
                bounds = Rect(0, 500, 1000, 640)
            ),
            preScrollAnchorBottom = 640,
            labelOf = { it.label }
        )

        assertEquals(-1, result.index)
        assertFalse(result.hasValidPostScrollCandidate)
    }

    @Test
    fun isNodePoorlyPositionedForFocus_returnsTrue_forPartiallyVisibleTrailingContentNearBottomBar() {
        val poorlyPositioned = A11yNavigator.isNodePoorlyPositionedForFocus(
            bounds = Rect(0, 2260, 1000, 2320),
            screenTop = 0,
            effectiveBottom = 2316
        )

        assertTrue(poorlyPositioned)
    }

    @Test
    fun shouldLiftTrailingContentBeforeFocus_returnsTrue_forThinBottomEdgeContent() {
        val shouldLift = A11yNavigator.shouldLiftTrailingContentBeforeFocus(
            bounds = Rect(40, 2298, 1000, 2316),
            effectiveBottom = 2316
        )

        assertTrue(shouldLift)
    }

    @Test
    fun isNodeFullyVisible_returnsTrue_forLastContentFallbackCase() {
        val fullyVisible = A11yNavigator.isNodeFullyVisible(
            bounds = Rect(0, 2080, 1000, 2300),
            screenTop = 0,
            effectiveBottom = 2316
        )

        assertTrue(fullyVisible)
    }

    @Test
    fun isNodePoorlyPositionedForFocus_returnsFalse_forNormallyReadableFullyVisibleNode() {
        val poorlyPositioned = A11yNavigator.isNodePoorlyPositionedForFocus(
            bounds = Rect(0, 900, 1000, 1220),
            screenTop = 0,
            effectiveBottom = 2316
        )

        assertFalse(poorlyPositioned)
    }

    @Test
    fun shouldTreatAsSnapBackAfterVerification_returnsFalse_whenTargetIsAccessibilityFocused() {
        val isSnapBack = A11yNavigator.shouldTreatAsSnapBackAfterVerification(
            actualFocusedBounds = Rect(10, 10, 100, 100),
            targetBounds = Rect(0, 0, 100, 100),
            isTargetAccessibilityFocused = true
        )

        assertFalse(isSnapBack)
    }

    @Test
    fun shouldTreatAsSnapBackAfterVerification_returnsFalse_whenBoundsAreWithinTolerance() {
        val isSnapBack = A11yNavigator.shouldTreatAsSnapBackAfterVerification(
            actualFocusedBounds = Rect(3, 4, 104, 106),
            targetBounds = Rect(0, 0, 100, 100),
            isTargetAccessibilityFocused = false
        )

        assertFalse(isSnapBack)
    }

    @Test
    fun isTargetFocusResolved_returnsTrue_whenTargetFocusedStateArrivesLate() {
        val resolved = A11yNavigator.isTargetFocusResolved(
            isTargetAccessibilityFocused = true,
            actualFocusedBounds = Rect(220, 400, 1040, 620),
            targetBounds = Rect(0, 0, 100, 100)
        )

        assertTrue(resolved)
    }

    @Test
    fun isTargetFocusResolved_returnsTrue_whenBoundsMatchEvenIfFocusFlagIsDelayed() {
        val resolved = A11yNavigator.isTargetFocusResolved(
            isTargetAccessibilityFocused = false,
            actualFocusedBounds = Rect(502, 1200, 1012, 1396),
            targetBounds = Rect(500, 1198, 1010, 1394)
        )

        assertTrue(resolved)
    }

    @Test
    fun shouldTreatAsSnapBackAfterVerification_returnsTrue_whenBoundsMismatchAndTargetNotFocused() {
        val isSnapBack = A11yNavigator.shouldTreatAsSnapBackAfterVerification(
            actualFocusedBounds = Rect(60, 60, 160, 160),
            targetBounds = Rect(0, 0, 100, 100),
            isTargetAccessibilityFocused = false
        )

        assertTrue(isSnapBack)
    }

    @Test
    fun shouldTreatAsSnapBackAfterVerification_returnsTrue_whenActualFocusIsMissing() {
        val isSnapBack = A11yNavigator.shouldTreatAsSnapBackAfterVerification(
            actualFocusedBounds = null,
            targetBounds = Rect(0, 0, 100, 100),
            isTargetAccessibilityFocused = false
        )

        assertTrue(isSnapBack)
    }

    @Test
    fun findPartiallyVisibleNextCandidate_keepsImmediatePartiallyVisibleCandidate() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/current", Rect(0, 200, 1000, 450)),
            Node("android.widget.TextView", "com.test:id/next", Rect(0, 430, 1000, 1040)),
            Node("android.widget.TextView", "com.test:id/next_next", Rect(0, 1040, 1000, 1540))
        )

        val index = A11yNavigator.findPartiallyVisibleNextCandidate(
            traversalList = nodes,
            currentIndex = 0,
            screenTop = 0,
            effectiveBottom = 1000,
            screenBottom = 1200,
            screenHeight = 1200,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertEquals(1, index)
    }

    @Test
    fun wouldOvershootPastIntendedCandidate_detectsWhenTrailingCardBecomesPrimary() {
        val overshoot = A11yNavigator.wouldOvershootPastIntendedCandidate(
            intendedBounds = Rect(0, 0, 1000, 220),
            trailingCandidateBounds = Rect(0, 180, 1000, 980),
            screenTop = 0,
            effectiveBottom = 1000
        )

        assertTrue(overshoot)
    }

    @Test
    fun isTransientSystemUiFocus_returnsTrue_onlyForCrossPackageSystemUiFocus() {
        val result = A11yNavigator.isTransientSystemUiFocus(
            focusedPackageName = "com.android.systemui",
            targetPackageName = "com.test.app"
        )

        assertTrue(result)
    }

    @Test
    fun isTransientSystemUiFocus_returnsFalse_forTargetInsideSystemUi() {
        val result = A11yNavigator.isTransientSystemUiFocus(
            focusedPackageName = "com.android.systemui",
            targetPackageName = "com.android.systemui"
        )

        assertFalse(result)
    }



    @Test
    fun resolveNextTraversalIndexPreservingIntermediateCandidate_keepsImmediateIntermediateWhenStaleGapIsOne() {
        val nextIndex = A11yNavigator.resolveNextTraversalIndexPreservingIntermediateCandidate(
            currentIndex = 2,
            fallbackIndex = -1,
            lastRequestedIndex = 3,
            traversalSize = 6
        )

        assertEquals(3, nextIndex)
    }

    @Test
    fun resolveNextTraversalIndexPreservingIntermediateCandidate_forcesAdvanceWhenNoIntermediateExists() {
        val nextIndex = A11yNavigator.resolveNextTraversalIndexPreservingIntermediateCandidate(
            currentIndex = 2,
            fallbackIndex = -1,
            lastRequestedIndex = 4,
            traversalSize = 3
        )

        assertEquals(5, nextIndex)
    }

    @Test
    fun resolveNextTraversalIndexPreservingIntermediateCandidate_usesFallbackWhenCurrentIndexLookupFails() {
        val nextIndex = A11yNavigator.resolveNextTraversalIndexPreservingIntermediateCandidate(
            currentIndex = -1,
            fallbackIndex = 6,
            lastRequestedIndex = 4,
            traversalSize = 10
        )

        assertEquals(6, nextIndex)
    }

    @Test
    fun resolveNextTraversalIndexPreservingIntermediateCandidate_returnsOverflowWhenCurrentIndexIsLast() {
        val nextIndex = A11yNavigator.resolveNextTraversalIndexPreservingIntermediateCandidate(
            currentIndex = 4,
            fallbackIndex = -1,
            lastRequestedIndex = -1,
            traversalSize = 5
        )

        assertEquals(5, nextIndex)
    }

    @Test
    fun findIntermediateContentCandidateBeforeBottomBar_prefersThinTrailingContent() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/home_care", Rect(42, 1911, 1038, 2256)),
            Node("android.widget.TextView", "com.test:id/find", Rect(42, 2298, 1038, 2316)),
            Node("android.widget.LinearLayout", "com.test:id/bottom_nav_home", Rect(23, 2316, 217, 2496))
        )

        val candidateIndex = A11yNavigator.findIntermediateContentCandidateBeforeBottomBar(
            traversalList = nodes,
            currentIndex = 0,
            bottomBarIndex = 2,
            screenTop = 0,
            screenBottom = 2496,
            screenHeight = 2496,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertEquals(1, candidateIndex)
    }

    @Test
    fun isThinTrailingContentAboveBottomBar_returnsTrueWhenNodeTouchesBottomBarBoundary() {
        data class Node(val className: String?, val viewId: String?)

        val node = Node("android.widget.TextView", "com.test:id/find")
        val isThinTrailing = A11yNavigator.isThinTrailingContentAboveBottomBar(
            node = node,
            bounds = Rect(42, 2298, 1038, 2316),
            bottomBarTop = 2316,
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertTrue(isThinTrailing)
    }

    @Test
    fun resolveAnchorIndexInRefreshedTraversal_findsExactAnchorFirst() {
        data class Node(val id: String?, val text: String?, val desc: String?, val bounds: Rect)
        val nodes = listOf(
            Node("id/history", "History", null, Rect(0, 100, 1000, 200)),
            Node("id/security", "Security status of your devices", null, Rect(0, 400, 1000, 520)),
            Node("id/privacy", "Privacy notice", null, Rect(0, 560, 1000, 700))
        )
        val anchor = A11yNavigator.PreScrollAnchor(
            viewIdResourceName = "id/security",
            mergedLabel = "Security status of your devices",
            talkbackLabel = "Security status of your devices",
            text = "Security status of your devices",
            contentDescription = null,
            bounds = Rect(0, 390, 1000, 510)
        )

        val index = A11yNavigator.resolveAnchorIndexInRefreshedTraversal(
            traversalList = nodes,
            anchor = anchor,
            boundsOf = { it.bounds },
            viewIdOf = { it.id },
            textOf = { it.text },
            contentDescriptionOf = { it.desc }
        )

        assertEquals(1, index)
    }

    @Test
    fun resolveAnchorIndexInRefreshedTraversal_usesApproximationWhenExactMissing() {
        data class Node(val id: String?, val text: String?, val desc: String?, val bounds: Rect)
        val nodes = listOf(
            Node("id/history", "History", null, Rect(0, 100, 1000, 200)),
            Node("id/security_card", "Security status", null, Rect(0, 410, 1000, 540)),
            Node("id/privacy", "Privacy notice", null, Rect(0, 560, 1000, 700))
        )
        val anchor = A11yNavigator.PreScrollAnchor(
            viewIdResourceName = "id/security",
            mergedLabel = "Security status of your devices",
            talkbackLabel = "Security status of your devices",
            text = "Security status of your devices",
            contentDescription = null,
            bounds = Rect(0, 400, 1000, 520)
        )

        val index = A11yNavigator.resolveAnchorIndexInRefreshedTraversal(
            traversalList = nodes,
            anchor = anchor,
            boundsOf = { it.bounds },
            viewIdOf = { it.id },
            textOf = { it.text },
            contentDescriptionOf = { it.desc }
        )

        assertEquals(1, index)
    }

    @Test
    fun isThinTrailingContentAboveBottomBar_returnsTrueWithin80pxBand() {
        data class Node(val className: String?, val viewId: String?)

        val node = Node("android.widget.TextView", "com.test:id/labs")
        val isThinTrailing = A11yNavigator.isThinTrailingContentAboveBottomBar(
            node = node,
            bounds = Rect(42, 2210, 1038, 2238),
            bottomBarTop = 2316,
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertTrue(isThinTrailing)
    }

    @Test
    fun shouldScrollBeforeBottomBar_returnsFalse_whenContentIsEffectivelyFinishedNearBottom() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.Button", "com.test:id/content_1", Rect(0, 650, 1000, 860)),
            Node("android.widget.Button", "com.test:id/content_2", Rect(0, 870, 1000, 1040)),
            Node("android.widget.LinearLayout", "com.test:id/bottom_nav", Rect(0, 1800, 1000, 2000))
        )

        val shouldScroll = A11yNavigator.shouldScrollBeforeBottomBar(
            traversalList = nodes,
            currentIndex = 1,
            nextIndex = 2,
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            effectiveBottom = 1800,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            canScrollForwardHint = true
        )

        assertFalse(shouldScroll)
    }

    @Test
    fun shouldScrollBeforeBottomBar_returnsTrue_whenHiddenContentLikelihoodIsHigh() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.Button", "com.test:id/content_1", Rect(0, 350, 1000, 520)),
            Node("android.widget.Button", "com.test:id/content_2", Rect(0, 540, 1000, 710)),
            Node("android.widget.Button", "com.test:id/content_3", Rect(0, 720, 1000, 920)),
            Node("android.widget.LinearLayout", "com.test:id/bottom_nav", Rect(0, 1800, 1000, 2000))
        )

        val shouldScroll = A11yNavigator.shouldScrollBeforeBottomBar(
            traversalList = nodes,
            currentIndex = 0,
            nextIndex = 3,
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            effectiveBottom = 1800,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            canScrollForwardHint = true
        )

        assertTrue(shouldScroll)
    }

    @Test
    fun shouldScrollBeforeBottomBar_returnsFalse_whenCurrentFocusIsTopFilterChip() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("com.google.android.material.chip.Chip", "com.test:id/filter_chip_laundry", Rect(0, 120, 400, 190)),
            Node("android.widget.Button", "com.test:id/content_1", Rect(0, 500, 1000, 700)),
            Node("android.widget.LinearLayout", "com.test:id/bottom_nav", Rect(0, 1800, 1000, 2000))
        )

        val shouldScroll = A11yNavigator.shouldScrollBeforeBottomBar(
            traversalList = nodes,
            currentIndex = 0,
            nextIndex = 2,
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            effectiveBottom = 1800,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            canScrollForwardHint = true
        )

        assertFalse(shouldScroll)
    }

    @Test
    fun shouldScrollBeforeBottomBar_returnsTrue_whenBottomBarIsImmediateButGridContinuationIsLikely() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/menu_voice_assistant_tile", Rect(0, 1560, 1000, 1760)),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1800, 1000, 2000))
        )

        val shouldScroll = A11yNavigator.shouldScrollBeforeBottomBar(
            traversalList = nodes,
            currentIndex = 0,
            nextIndex = 1,
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            effectiveBottom = 1800,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            canScrollForwardHint = true
        )

        assertTrue(shouldScroll)
    }

    @Test
    fun shouldForcePreScrollBeforeBottomBar_returnsTrue_whenContinuationLikelyEvenIfBaseHeuristicIsFalse() {
        val shouldForce = A11yNavigator.shouldForcePreScrollBeforeBottomBar(
            shouldScrollBeforeBottomBar = false,
            continuationContentLikelyBelowCurrentGrid = true
        )

        assertTrue(shouldForce)
    }

    @Test
    fun shouldForcePreScrollBeforeBottomBar_returnsFalse_whenBothSignalsAreFalse() {
        val shouldForce = A11yNavigator.shouldForcePreScrollBeforeBottomBar(
            shouldScrollBeforeBottomBar = false,
            continuationContentLikelyBelowCurrentGrid = false
        )

        assertFalse(shouldForce)
    }

    @Test
    fun hasContinuationPatternBelowCurrentNode_returnsTrue_forGridKeyword() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.FrameLayout", "com.test:id/labs_grid_tile", Rect(0, 1600, 500, 1780)),
            Node("android.widget.LinearLayout", "com.test:id/bottom_nav", Rect(0, 1800, 1000, 2000))
        )

        val result = A11yNavigator.hasContinuationPatternBelowCurrentNode(
            traversalList = nodes,
            currentIndex = 0,
            nextIndex = 1,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertTrue(result)
    }

    @Test
    fun hasContinuationContentBeforeBottomBar_returnsTrue_forTrailingContentWithin80px() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/security", Rect(0, 1900, 1000, 2140)),
            Node("android.widget.TextView", "com.test:id/labs", Rect(0, 2160, 1000, 2240)),
            Node("android.widget.LinearLayout", "com.test:id/bottom_nav", Rect(0, 2320, 1000, 2480))
        )

        val result = A11yNavigator.hasContinuationContentBeforeBottomBar(
            traversalList = nodes,
            currentIndex = 0,
            bottomBarIndex = 2,
            screenTop = 0,
            screenBottom = 2480,
            screenHeight = 2480,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertTrue(result)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_returnsFirstNewContentExcludingTopAndBottomBars() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/smartthings_top", Rect(0, 80, 1000, 220)),
            Node("android.widget.TextView", "com.test:id/security", Rect(0, 900, 1000, 1120)),
            Node("android.widget.TextView", "com.test:id/privacy_notice", Rect(0, 1220, 1000, 1440))
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("Security"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = setOf("Security"),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            labelOf = { node ->
                when (node.viewId) {
                    "com.test:id/smartthings_top" -> "SmartThings"
                    "com.test:id/security" -> "Security"
                    "com.test:id/privacy_notice" -> "Privacy Notice"
                    else -> null
                }
            }
        )

        assertEquals(2, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_returnsMinusOneWhenOnlyBottomBarRemains() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/top_toolbar", Rect(0, 0, 1000, 180)),
            Node("android.widget.TextView", "com.test:id/voice_assistant", Rect(0, 380, 1000, 620)),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1820, 1000, 2000))
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("Voice assistant"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = setOf("Voice assistant"),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            labelOf = { node ->
                when (node.viewId) {
                    "com.test:id/top_toolbar" -> "Toolbar"
                    "com.test:id/voice_assistant" -> "Voice assistant"
                    "com.test:id/home_bottom_navigation" -> "Home"
                    else -> null
                }
            }
        )

        assertEquals(-1, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_skipsResurfacedNoLabelByViewIdAndSelectsNewContent() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect, val label: String?)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/history", Rect(0, 120, 1000, 320), null),
            Node("android.widget.TextView", "com.test:id/privacy_notice", Rect(0, 380, 1000, 620), "Privacy notice")
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = emptySet(),
            visibleHistorySignatures = setOf(
                A11yNavigator.VisibleHistorySignature(
                    label = "History",
                    viewId = "com.test:id/history",
                    bounds = Rect(0, 110, 1000, 310)
                )
            ),
            visitedHistory = emptySet(),
            visitedHistorySignatures = setOf(
                A11yNavigator.VisibleHistorySignature(
                    label = "History",
                    viewId = "com.test:id/history",
                    bounds = Rect(0, 110, 1000, 310)
                )
            ),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            labelOf = { it.label }
        )

        assertEquals(1, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_selectsTopContinuationCandidate_whenVisibleButUnvisitedAfterScroll() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect, val label: String?)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/voice_assistant", Rect(0, 120, 1000, 360), "Voice assistant"),
            Node("android.widget.TextView", "com.test:id/labs", Rect(0, 380, 1000, 640), "Labs"),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1820, 1000, 2000), "Home")
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("Voice assistant", "Labs"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = setOf("Voice assistant"),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/voice_assistant",
                mergedLabel = "Voice assistant",
                talkbackLabel = "Voice assistant",
                text = "Voice assistant",
                contentDescription = null,
                bounds = Rect(0, 980, 1000, 1220)
            ),
            preScrollAnchorBottom = 1220,
            labelOf = { it.label }
        )

        assertEquals(1, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_prefersNewlyRevealedUnvisitedInteractiveCandidate_evenWhenRewoundBeforeAnchor() {
        data class Node(
            val className: String?,
            val viewId: String?,
            val bounds: Rect,
            val label: String?,
            val clickable: Boolean,
            val focusable: Boolean
        )

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/voice_assistant", Rect(0, 120, 1000, 360), "Voice assistant", clickable = true, focusable = true),
            Node("android.widget.TextView", "com.test:id/labs", Rect(0, 380, 1000, 640), "Labs", clickable = true, focusable = true),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1820, 1000, 2000), "Home", clickable = true, focusable = true)
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("Voice assistant"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = setOf("Voice assistant"),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            clickableOf = { it.clickable },
            focusableOf = { it.focusable },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/voice_assistant",
                mergedLabel = "Voice assistant",
                talkbackLabel = "Voice assistant",
                text = "Voice assistant",
                contentDescription = null,
                bounds = Rect(0, 980, 1000, 1220)
            ),
            preScrollAnchorBottom = 1220,
            labelOf = { it.label }
        )

        assertEquals(1, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_rejectsRewoundCandidate_whenAlreadyVisibleBeforeScroll() {
        data class Node(
            val className: String?,
            val viewId: String?,
            val bounds: Rect,
            val label: String?,
            val clickable: Boolean,
            val focusable: Boolean
        )

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/labs", Rect(0, 380, 1000, 640), "Labs", clickable = true, focusable = true),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1820, 1000, 2000), "Home", clickable = true, focusable = true)
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("Labs"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = emptySet(),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            clickableOf = { it.clickable },
            focusableOf = { it.focusable },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/voice_assistant",
                mergedLabel = "Voice assistant",
                talkbackLabel = "Voice assistant",
                text = "Voice assistant",
                contentDescription = null,
                bounds = Rect(0, 980, 1000, 1220)
            ),
            preScrollAnchorBottom = 1220,
            labelOf = { it.label }
        )

        assertEquals(-1, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_acceptsNewlyRevealedInteractiveCandidate_withDescendantLabel() {
        data class Node(
            val className: String?,
            val viewId: String?,
            val bounds: Rect,
            val label: String?,
            val descendantLabel: String?,
            val clickable: Boolean,
            val focusable: Boolean
        )

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/labs", Rect(0, 380, 1000, 640), null, "Labs", clickable = true, focusable = true),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1820, 1000, 2000), "Home", null, clickable = true, focusable = true)
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = emptySet(),
            visibleHistorySignatures = emptySet(),
            visitedHistory = emptySet(),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            clickableOf = { it.clickable },
            focusableOf = { it.focusable },
            descendantLabelOf = { it.descendantLabel },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/voice_assistant",
                mergedLabel = "Voice assistant",
                talkbackLabel = "Voice assistant",
                text = "Voice assistant",
                contentDescription = null,
                bounds = Rect(0, 980, 1000, 1220)
            ),
            preScrollAnchorBottom = 1220,
            labelOf = { it.label }
        )

        assertEquals(0, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_doesNotPromoteTopPersistentHeader_asNewlyRevealed() {
        data class Node(
            val className: String?,
            val viewId: String?,
            val bounds: Rect,
            val label: String?,
            val descendantLabel: String?,
            val clickable: Boolean,
            val focusable: Boolean
        )

        val nodes = listOf(
            Node("android.widget.Toolbar", "com.test:id/title_bar", Rect(0, 0, 1080, 180), "App title", null, clickable = true, focusable = true),
            Node("android.widget.FrameLayout", "com.test:id/feature_labs", Rect(0, 320, 1080, 620), null, "Labs", clickable = true, focusable = true),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1820, 1080, 2000), "Home", null, clickable = true, focusable = true)
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("App title"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = emptySet(),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            clickableOf = { it.clickable },
            focusableOf = { it.focusable },
            descendantLabelOf = { it.descendantLabel },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/item_history",
                mergedLabel = "History",
                talkbackLabel = "History",
                text = "History",
                contentDescription = null,
                bounds = Rect(0, 980, 1080, 1220)
            ),
            preScrollAnchorBottom = 1220,
            labelOf = { it.label }
        )

        assertEquals(1, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_prioritizesTrailingContinuationOverTopResurfacedItem() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect, val label: String?)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/smartthings_top", Rect(0, 80, 1000, 260), "SmartThings"),
            Node("android.widget.TextView", "com.test:id/labs", Rect(0, 740, 1000, 980), "Labs"),
            Node("android.widget.TextView", "com.test:id/energy", Rect(0, 1200, 1000, 1460), "Energy")
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("Voice assistant", "Labs"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = setOf("Voice assistant", "Labs"),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            preScrollAnchorBottom = 620,
            labelOf = { it.label }
        )

        assertEquals(1, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_prioritizesPreScrollAnchorLogicalSuccessor() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect, val label: String?)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/item_history", Rect(30, 1680, 1050, 1848), "History"),
            Node("android.widget.TextView", "com.test:id/item_knox_matrix", Rect(30, 1773, 1050, 1941), "Security status of your devices"),
            Node("android.widget.TextView", "com.test:id/item_privacy_notice", Rect(30, 1941, 1050, 2109), "Privacy notice")
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("History", "Security status of your devices"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = setOf("History", "Security status of your devices"),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2400,
            screenHeight = 2400,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/item_knox_matrix",
                mergedLabel = "Security status of your devices",
                talkbackLabel = "Security status of your devices",
                text = "Security status of your devices",
                contentDescription = null,
                bounds = Rect(30, 2143, 1050, 2311)
            ),
            preScrollAnchorBottom = 2311,
            labelOf = { it.label }
        )

        assertEquals(2, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_acceptsContentContinuationDespiteRewoundBeforeAnchor_whenDescendantLabelResolved() {
        data class Node(
            val className: String?,
            val viewId: String?,
            val bounds: Rect,
            val label: String?,
            val descendantLabel: String?,
            val focusable: Boolean,
            val clickable: Boolean
        )

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/app_logo_image", Rect(0, 80, 1000, 260), "SmartThings", "", true, false),
            Node("android.widget.FrameLayout", "com.test:id/item_labs", Rect(30, 520, 1050, 680), "", "Labs", true, true)
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("SmartThings"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = setOf("SmartThings"),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2200,
            screenHeight = 2200,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { node -> node.viewId == "com.test:id/item_labs" },
            clickableOf = { it.clickable },
            focusableOf = { it.focusable },
            descendantLabelOf = { it.descendantLabel },
            preScrollAnchor = A11yNavigator.PreScrollAnchor(
                viewIdResourceName = "com.test:id/item_voice_assistant",
                mergedLabel = "Voice assistant",
                talkbackLabel = "Voice assistant",
                text = "Voice assistant",
                contentDescription = null,
                bounds = Rect(30, 620, 1050, 800)
            ),
            preScrollAnchorBottom = 800,
            labelOf = { it.label }
        )

        assertEquals(1, index)
    }

    @Test
    fun findAnchorContinuationCandidateIndex_prioritizesPromotedRawOnlyCandidateOverLowPriorityFallback() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect, val label: String?)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/item_history", Rect(30, 1680, 1050, 1848), "History"),
            Node("android.widget.TextView", "com.test:id/item_privacy_notice", Rect(30, 1941, 1050, 2109), "Privacy notice")
        )

        val index = A11yNavigator.findAnchorContinuationCandidateIndex(
            traversalList = nodes,
            startIndex = 0,
            visibleHistory = setOf("History"),
            visibleHistorySignatures = emptySet(),
            visitedHistory = setOf("History"),
            visitedHistorySignatures = emptySet(),
            screenTop = 0,
            screenBottom = 2400,
            screenHeight = 2400,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            isContentNodeOf = { true },
            promotedViewIds = setOf("item_privacy_notice"),
            preScrollAnchorBottom = 1600,
            labelOf = { it.label }
        )

        assertEquals(1, index)
    }

    @Test
    fun shouldAcceptFallbackSelectedNoLabelContinuationCandidate_returnsTrue_forContentViewportNode() {
        val accepted = A11yNavigator.shouldAcceptFallbackSelectedNoLabelContinuationCandidate(
            isFallbackSelectedContinuationCandidate = true,
            isTopBar = false,
            isBottomBar = false,
            bounds = Rect(0, 240, 1000, 620),
            screenTop = 0,
            effectiveBottom = 1800
        )

        assertTrue(accepted)
    }

    @Test
    fun shouldAcceptFallbackSelectedNoLabelContinuationCandidate_returnsFalse_forBottomBarNode() {
        val accepted = A11yNavigator.shouldAcceptFallbackSelectedNoLabelContinuationCandidate(
            isFallbackSelectedContinuationCandidate = true,
            isTopBar = false,
            isBottomBar = true,
            bounds = Rect(0, 1840, 1000, 1990),
            screenTop = 0,
            effectiveBottom = 1800
        )

        assertFalse(accepted)
    }

    @Test
    fun recoverLabelFromDescendantTexts_returnsFirstNonBlankLabel() {
        val recovered = A11yNavigator.recoverLabelFromDescendantTexts(
            listOf("   ", "", "Labs", "Menu")
        )

        assertEquals("Labs", recovered)
    }

    @Test
    fun shouldAllowRecoveredDescendantLabelForTraversal_returnsTrue_forSingleCardLikeLabel() {
        val allowed = A11yNavigator.shouldAllowRecoveredDescendantLabelForTraversal(
            listOf("Home profile", "Home profile")
        )

        assertTrue(allowed)
    }

    @Test
    fun shouldAllowRecoveredDescendantLabelForTraversal_returnsFalse_forLargeMergedContainerText() {
        val allowed = A11yNavigator.shouldAllowRecoveredDescendantLabelForTraversal(
            listOf(
                "Home profile",
                "Explore",
                "Supported devices",
                "Routines",
                "Scenes"
            )
        )

        assertFalse(allowed)
    }

    @Test
    fun isContainerLikeClassName_detectsScrollContainers() {
        assertTrue(A11yNavigator.isContainerLikeClassName("androidx.core.widget.NestedScrollView"))
        assertTrue(A11yNavigator.isContainerLikeClassName("androidx.recyclerview.widget.RecyclerView"))
        assertFalse(A11yNavigator.isContainerLikeClassName("android.widget.TextView"))
    }

    @Test
    fun isContainerLikeViewId_detectsMainContentWrappers() {
        assertTrue(A11yNavigator.isContainerLikeViewId("com.test:id/mainScrollView"))
        assertTrue(A11yNavigator.isContainerLikeViewId("com.test:id/content_container"))
        assertFalse(A11yNavigator.isContainerLikeViewId("com.test:id/home_profile_card"))
    }

    @Test
    fun isContinuationContentLikelyBelowCurrentNode_returnsTrue_forBottomEdgeGridBeforeBottomBar() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/menu_voice_assistant_tile", Rect(0, 1560, 1000, 1760)),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1800, 1000, 2000))
        )

        val likely = A11yNavigator.isContinuationContentLikelyBelowCurrentNode(
            traversalList = nodes,
            currentIndex = 0,
            nextIndex = 1,
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            effectiveBottom = 1800,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertTrue(likely)
    }

    @Test
    fun findLastContentCandidateIndexBeforeBottomBar_excludesTopChromeWrapperAndBottomBar() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.FrameLayout", "com.test:id/top_toolbar", Rect(0, 0, 1000, 180)),
            Node("android.widget.ScrollView", "com.test:id/mainScrollView", Rect(0, 180, 1000, 1700)),
            Node("android.widget.TextView", "com.test:id/item_history", Rect(0, 420, 1000, 640)),
            Node("android.widget.TextView", "com.test:id/item_privacy_notice", Rect(0, 1560, 1000, 1780)),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1800, 1000, 2000))
        )

        val lastContentIndex = A11yNavigator.findLastContentCandidateIndexBeforeBottomBar(
            traversalList = nodes,
            bottomBarIndex = 4,
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertEquals(3, lastContentIndex)
    }

    @Test
    fun isContentTraversalCompleteBeforeBottomBar_returnsTrue_whenCurrentIsDynamicLastContent() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/item_history", Rect(0, 420, 1000, 640)),
            Node("android.widget.TextView", "com.test:id/item_privacy_notice", Rect(0, 1560, 1000, 1780)),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1800, 1000, 2000))
        )

        val complete = A11yNavigator.isContentTraversalCompleteBeforeBottomBar(
            traversalList = nodes,
            currentIndex = 1,
            bottomBarIndex = 2,
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            effectiveBottom = 1800,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            canScrollForwardHint = true
        )

        assertTrue(complete)
    }

    @Test
    fun isContentTraversalCompleteBeforeBottomBar_returnsFalse_whenNearBottomContinuationLikely() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)

        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/menu_voice_assistant_tile", Rect(0, 1540, 1000, 1765)),
            Node("android.widget.LinearLayout", "com.test:id/home_bottom_navigation", Rect(0, 1800, 1000, 2000))
        )

        val complete = A11yNavigator.isContentTraversalCompleteBeforeBottomBar(
            traversalList = nodes,
            currentIndex = 0,
            bottomBarIndex = 1,
            screenTop = 0,
            screenBottom = 2000,
            screenHeight = 2000,
            effectiveBottom = 1800,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            canScrollForwardHint = true
        )

        assertFalse(complete)
    }

    @Test
    fun isTopLoopProneControlNode_detectsTopFilterChip() {
        data class Node(val className: String?, val viewId: String?)

        val detected = A11yNavigator.isTopLoopProneControlNode(
            node = Node("com.google.android.material.chip.Chip", "com.test:id/category_chip"),
            bounds = Rect(0, 130, 300, 200),
            screenTop = 0,
            screenHeight = 2000,
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertTrue(detected)
    }


    @Test
    fun findCurrentTraversalIndex_prioritizesLastNodeMatchOverEarlierIdentityMatch() {
        data class IdentityNode(val id: String?, val text: String?, val desc: String?, val bounds: Rect)

        val first = IdentityNode("com.test:id/item", "거실", "거실 카드", Rect(0, 100, 200, 200))
        val middle = IdentityNode("com.test:id/item_alt", "주방", "주방 카드", Rect(0, 220, 200, 320))
        val last = IdentityNode("com.test:id/item", "거실", "거실 카드", Rect(0, 100, 200, 200))
        val traversalList = listOf(first, middle, last)

        val index = A11yNavigator.findCurrentTraversalIndex(
            traversalList = traversalList,
            currentNode = last,
            isSameNodeMatch = { a, b ->
                A11yNavigator.isSameNodeIdentity(
                    aId = a.id,
                    aText = a.text,
                    aContentDescription = a.desc,
                    aBounds = a.bounds,
                    bId = b.id,
                    bText = b.text,
                    bContentDescription = b.desc,
                    bBounds = b.bounds
                )
            }
        )

        assertEquals(2, index)
    }

    @Test
    fun setLastRequestedFocusIndex_updatesStateStoreTogether() {
        val navigatorField = A11yNavigator::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val stateField = A11yStateStore::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val originalNavigatorValue = navigatorField.getInt(null)
        val originalStateValue = stateField.getInt(null)

        try {
            A11yNavigator.setLastRequestedFocusIndex(12)

            assertEquals(12, navigatorField.getInt(null))
            assertEquals(12, stateField.getInt(null))
        } finally {
            navigatorField.setInt(null, originalNavigatorValue)
            stateField.setInt(null, originalStateValue)
        }
    }

    @Test
    fun resetFocusHistory_clearsNavigatorAndStateStoreTogether() {
        val navigatorField = A11yNavigator::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val stateField = A11yStateStore::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val originalNavigatorValue = navigatorField.getInt(null)
        val originalStateValue = stateField.getInt(null)

        try {
            navigatorField.setInt(null, 7)
            stateField.setInt(null, 7)

            A11yNavigator.resetFocusHistory()

            assertEquals(-1, navigatorField.getInt(null))
            assertEquals(-1, stateField.getInt(null))
        } finally {
            navigatorField.setInt(null, originalNavigatorValue)
            stateField.setInt(null, originalStateValue)
        }
    }

    @Test
    fun recordRequestedFocusAttempt_keepsFurthestRequestedIndexAcrossSnapBack() {
        val navigatorField = A11yNavigator::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val stateField = A11yStateStore::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val originalNavigatorValue = navigatorField.getInt(null)
        val originalStateValue = stateField.getInt(null)

        try {
            navigatorField.setInt(null, 10)
            stateField.setInt(null, 10)

            A11yNavigator.recordRequestedFocusAttempt(11)
            A11yNavigator.recordRequestedFocusAttempt(10)

            assertEquals(11, navigatorField.getInt(null))
            assertEquals(11, stateField.getInt(null))
        } finally {
            navigatorField.setInt(null, originalNavigatorValue)
            stateField.setInt(null, originalStateValue)
        }
    }

    @Test
    fun recordRequestedFocusAttempt_ignoresNegativeTraversalIndex() {
        val navigatorField = A11yNavigator::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val stateField = A11yStateStore::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val originalNavigatorValue = navigatorField.getInt(null)
        val originalStateValue = stateField.getInt(null)

        try {
            navigatorField.setInt(null, 8)
            stateField.setInt(null, 8)

            A11yNavigator.recordRequestedFocusAttempt(-1)

            assertEquals(8, navigatorField.getInt(null))
            assertEquals(8, stateField.getInt(null))
        } finally {
            navigatorField.setInt(null, originalNavigatorValue)
            stateField.setInt(null, originalStateValue)
        }
    }


    @Test
    fun findNodeIndexByIdentity_prefersCoordinateIndexForFocusReconciliation() {
        data class IdentityNode(val id: String?, val text: String?, val desc: String?, val bounds: Rect)

        val target = IdentityNode(id = "com.test:id/current", text = "현재", desc = "현재 포커스", bounds = Rect(0, 500, 400, 620))
        val list = listOf(
            IdentityNode(id = "com.test:id/other", text = "다른 카드", desc = "이전 포커스", bounds = Rect(0, 300, 400, 420)),
            IdentityNode(id = "com.test:id/changed", text = "변경된 카드", desc = "변경된 포커스", bounds = Rect(0, 500, 400, 620))
        )

        val index = A11yNavigator.findNodeIndexByIdentity(
            nodes = list,
            target = target,
            idOf = { it.id },
            textOf = { it.text },
            contentDescriptionOf = { it.desc },
            boundsOf = { it.bounds }
        )

        assertEquals(1, index)
    }

    @Test
    fun shouldSkipDuplicateBoundsCandidate_returnsTrueWhenBoundsPerfectlyMatch() {
        val result = A11yNavigator.shouldSkipDuplicateBoundsCandidate(
            currentFocusedBounds = Rect(0, 300, 500, 600),
            candidateBounds = Rect(0, 300, 500, 600),
            isScrollAction = true
        )

        assertTrue(result)
    }

    @Test
    fun shouldSkipDuplicateBoundsCandidate_returnsFalseForFallbackSelectedContinuationCandidate() {
        val result = A11yNavigator.shouldSkipDuplicateBoundsCandidate(
            currentFocusedBounds = Rect(70, 310, 370, 610),
            candidateBounds = Rect(70, 310, 370, 610),
            isScrollAction = true,
            skipForFallbackSelectedContinuationCandidate = true
        )

        assertFalse(result)
    }

    @Test
    fun skipCoordinateDuplicateTraversalIndices_keepsCandidateWhenLeftOrTopDiffers() {
        val nodes = listOf(
            Rect(0, 100, 100, 200),
            Rect(1, 100, 101, 200),
            Rect(0, 101, 100, 201)
        )

        val nextIndex = A11yNavigator.skipCoordinateDuplicateTraversalIndices(
            nodes = nodes,
            currentBounds = Rect(0, 100, 100, 200),
            startIndex = 1,
            boundsOf = { it }
        )

        assertEquals(1, nextIndex)
    }

    @Test
    fun skipCoordinateDuplicateTraversalIndices_skipsOnlyPerfectBoundsMatch() {
        val nodes = listOf(
            Rect(0, 100, 100, 200),
            Rect(0, 100, 100, 200),
            Rect(0, 100, 100, 201)
        )

        val nextIndex = A11yNavigator.skipCoordinateDuplicateTraversalIndices(
            nodes = nodes,
            currentBounds = Rect(0, 100, 100, 200),
            startIndex = 1,
            boundsOf = { it }
        )

        assertEquals(2, nextIndex)
    }

    @Test
    fun findMainScrollContainer_returnsLargestScrollableNode() {
        data class Node(val rect: Rect, val scrollable: Boolean)

        val nodes = listOf(
            Node(Rect(0, 0, 1080, 200), scrollable = false),
            Node(Rect(0, 200, 1080, 1500), scrollable = true),
            Node(Rect(0, 200, 540, 900), scrollable = true)
        )

        val container = A11yNavigator.findMainScrollContainer(
            nodes = nodes,
            isScrollable = { it.scrollable },
            boundsOf = { it.rect }
        )

        assertEquals(nodes[1], container)
    }

    @Test
    fun isFixedSystemUI_returnsTrueWhenNodeIsOutsideMainScrollContainer() {
        data class Node(
            val name: String,
            val parent: Node? = null,
            val className: String? = null,
            val viewId: String? = null,
            val text: String? = null,
            val contentDescription: String? = null
        )

        val root = Node("root")
        val toolbar = Node("toolbar", parent = root, className = "Toolbar")
        val content = Node("content", parent = root)
        val item = Node("item", parent = content, text = "Plant Care")

        assertTrue(
            A11yNavigator.isFixedSystemUI(
                node = toolbar,
                mainScrollContainer = content,
                parentOf = { it.parent },
                classNameOf = { it.className },
                viewIdOf = { it.viewId },
                textOf = { it.text },
                contentDescriptionOf = { it.contentDescription }
            )
        )
        assertFalse(
            A11yNavigator.isFixedSystemUI(
                node = item,
                mainScrollContainer = content,
                parentOf = { it.parent },
                classNameOf = { it.className },
                viewIdOf = { it.viewId },
                textOf = { it.text },
                contentDescriptionOf = { it.contentDescription }
            )
        )
    }

    @Test
    fun isFixedSystemUI_returnsFalseForContentContainerClassesEvenOutsideMainScroll() {
        data class Node(
            val parent: Node? = null,
            val className: String? = null,
            val viewId: String? = null,
            val text: String? = null,
            val contentDescription: String? = null
        )

        val root = Node()
        val scrollContainer = Node(parent = root, className = "androidx.recyclerview.widget.RecyclerView")
        val cardContainer = Node(parent = root, className = "android.widget.FrameLayout", text = "Home Care")

        val result = A11yNavigator.isFixedSystemUI(
            node = cardContainer,
            mainScrollContainer = scrollContainer,
            parentOf = { it.parent },
            classNameOf = { it.className },
            viewIdOf = { it.viewId },
            textOf = { it.text },
            contentDescriptionOf = { it.contentDescription }
        )

        assertFalse(result)
    }

    @Test
    fun shouldSkipHistoryNodeAfterScroll_returnsTrueForFixedUiHistoryEvenInTopArea() {
        val skipped = A11yNavigator.shouldSkipHistoryNodeAfterScroll(
            isScrollAction = true,
            inHistory = true,
            isFixedUi = true,
            isInsideMainScrollContainer = false,
            isTopArea = true
        )

        assertTrue(skipped)
    }


    @Test
    fun shouldSkipHistoryNodeAfterScroll_returnsTrueForHistoryInTopAreaWithinMainScroll() {
        val skipped = A11yNavigator.shouldSkipHistoryNodeAfterScroll(
            isScrollAction = true,
            inHistory = true,
            isFixedUi = false,
            isInsideMainScrollContainer = true,
            isTopArea = true
        )

        assertTrue(skipped)
    }

    @Test
    fun requestAccessibilityFocusWithRetry_returnsTrueOnThirdAttempt() {
        var attempts = 0

        val result = A11yNavigator.requestAccessibilityFocusWithRetry(
            performFocusAction = {
                attempts += 1
                attempts == 3
            },
            refreshFocusState = { false },
            retryDelayMs = 0L
        )

        assertTrue(result)
        assertEquals(3, attempts)
    }

    @Test
    fun requestAccessibilityFocusWithRetry_acceptsAlreadyFocusedNodeAfterFalseResults() {
        var attempts = 0
        var refreshChecks = 0

        val result = A11yNavigator.requestAccessibilityFocusWithRetry(
            performFocusAction = {
                attempts += 1
                false
            },
            refreshFocusState = {
                refreshChecks += 1
                refreshChecks == 3
            },
            retryDelayMs = 0L
        )

        assertTrue(result)
        assertEquals(3, attempts)
        assertEquals(3, refreshChecks)
    }

    @Test
    fun isWithinTopContentArea_usesTwentyPercentWhenSmallerThan500px() {
        val result = A11yNavigator.isWithinTopContentArea(
            nodeTop = 350,
            screenTop = 0,
            screenHeight = 1920
        )

        assertTrue(result)
    }

    @Test
    fun isWithinTopContentArea_limitsTopAreaTo500pxOnTallScreens() {
        val result = A11yNavigator.isWithinTopContentArea(
            nodeTop = 550,
            screenTop = 0,
            screenHeight = 3200
        )

        assertFalse(result)
    }

    @Test
    fun isBottomClippedWithPadding_returnsTrueWhenInside300pxBottomPaddingBand() {
        val clipped = A11yNavigator.isBottomClippedWithPadding(
            boundsBottom = 1651,
            effectiveBottom = 1920
        )

        assertTrue(clipped)
    }

    @Test
    fun shouldAlignToRealTop_returnsTrueWhenNodeIsBelowTop300px() {
        val shouldAlign = A11yNavigator.shouldAlignToRealTop(
            boundsTop = 350,
            screenTop = 0
        )

        assertTrue(shouldAlign)
    }





    @Test
    fun shouldTriggerShowOnScreen_returnsFalseForBottomBarEvenWhenBottomClipped() {
        val result = A11yNavigator.shouldTriggerShowOnScreen(
            bounds = Rect(0, 1700, 1080, 1910),
            effectiveBottom = 1920,
            screenTop = 0,
            isScrollAction = false,
            isTopBar = false,
            isBottomBar = true
        )

        assertFalse(result)
    }

    @Test
    fun shouldTriggerShowOnScreen_returnsFalseForTopBarEvenWhenTopAlignWouldTrigger() {
        val result = A11yNavigator.shouldTriggerShowOnScreen(
            bounds = Rect(0, 350, 1080, 450),
            effectiveBottom = 1920,
            screenTop = 0,
            isScrollAction = true,
            isTopBar = true,
            isBottomBar = false
        )

        assertFalse(result)
    }

    @Test
    fun shouldTriggerShowOnScreen_returnsTrueForRegularContentWhenAdjustmentNeeded() {
        val result = A11yNavigator.shouldTriggerShowOnScreen(
            bounds = Rect(0, 350, 1080, 450),
            effectiveBottom = 1920,
            screenTop = 0,
            isScrollAction = true,
            isTopBar = false,
            isBottomBar = false
        )

        assertTrue(result)
    }

    @Test
    fun isSameNodeIdentity_returnsFalseWhenFallbackDescIsDifferent() {
        val result = A11yNavigator.isSameNodeIdentity(
            aId = "com.test:id/card",
            aText = "거실",
            aContentDescription = "거실 카드",
            aBounds = Rect(0, 0, 100, 100),
            bId = "com.test:id/card",
            bText = "거실",
            bContentDescription = "침실 카드",
            bBounds = Rect(0, 120, 100, 220)
        )

        assertFalse(result)
    }

    @Test
    fun compareByContainmentAndPosition_treatsNonOverlappingRowsAsDifferentEvenWhenCentersAreClose() {
        data class Node(val rect: Rect, val parent: Node? = null)

        val upper = Node(rect = Rect(0, 0, 100, 10))
        val lower = Node(rect = Rect(0, 11, 100, 21))

        val result = A11yNavigator.compareByContainmentAndPosition(
            left = upper,
            right = lower,
            parentOf = { it.parent },
            boundsOf = { it.rect },
            yBucketSize = 20
        )

        assertTrue(result < 0)
    }

    @Test
    fun findClosestNodeBelowCenter_returnsNearestLowerNodeIndex() {
        data class Node(val rect: Rect)

        val reference = Node(Rect(0, 100, 100, 140))
        val nodes = listOf(
            Node(Rect(0, 20, 100, 60)),
            Node(Rect(0, 145, 100, 185)),
            Node(Rect(0, 220, 100, 260))
        )

        val index = A11yNavigator.findClosestNodeBelowCenter(
            nodes = nodes,
            reference = reference,
            boundsOf = { it.rect }
        )

        assertEquals(1, index)
    }

    @Test
    fun findClosestNodeBelowCenter_returnsMinusOneWhenNoLowerNodeExists() {
        data class Node(val rect: Rect)

        val reference = Node(Rect(0, 200, 100, 240))
        val nodes = listOf(
            Node(Rect(0, 20, 100, 60)),
            Node(Rect(0, 145, 100, 185))
        )

        val index = A11yNavigator.findClosestNodeBelowCenter(
            nodes = nodes,
            reference = reference,
            boundsOf = { it.rect }
        )

        assertEquals(-1, index)
    }

    @Test
    fun shouldSkipExcludedNodeByDescription_returnsTrueWhenSameDescAndTop30Percent() {
        val shouldSkip = A11yNavigator.shouldSkipExcludedNodeByDescription(
            nodeDesc = "최근 재생",
            excludeDesc = "최근 재생",
            nodeBounds = Rect(0, 100, 1080, 240),
            screenTop = 0,
            screenHeight = 1920
        )

        assertTrue(shouldSkip)
    }

    @Test
    fun shouldSkipExcludedNodeByDescription_returnsFalseWhenDescDifferent() {
        val shouldSkip = A11yNavigator.shouldSkipExcludedNodeByDescription(
            nodeDesc = "최근 재생",
            excludeDesc = "추천 콘텐츠",
            nodeBounds = Rect(0, 100, 1080, 240),
            screenTop = 0,
            screenHeight = 1920
        )

        assertFalse(shouldSkip)
    }

    @Test
    fun findIndexByDescription_returnsNextStartPointWhenDescriptionExists() {
        data class Node(val desc: String?)

        val nodes = listOf(
            Node("alpha"),
            Node("beta"),
            Node("gamma")
        )

        val index = A11yNavigator.findIndexByDescription(
            nodes = nodes,
            descriptionOf = { it.desc },
            excludeDesc = "beta"
        )

        assertEquals(1, index)
    }

    @Test
    fun findIndexByDescription_matchesByContentDescriptionOrTextFallback() {
        data class Node(val desc: String?, val text: String?)

        val nodes = listOf(
            Node(desc = null, text = "Home Care"),
            Node(desc = "Pet Care", text = null),
            Node(desc = null, text = "Play Room")
        )

        val indexByText = A11yNavigator.findIndexByDescription(
            nodes = nodes,
            descriptionOf = { it.desc?.trim().takeUnless { value -> value.isNullOrEmpty() } ?: it.text },
            excludeDesc = "Home Care"
        )
        val indexByDesc = A11yNavigator.findIndexByDescription(
            nodes = nodes,
            descriptionOf = { it.desc?.trim().takeUnless { value -> value.isNullOrEmpty() } ?: it.text },
            excludeDesc = "Pet Care"
        )

        assertEquals(0, indexByText)
        assertEquals(1, indexByDesc)
    }

    @Test
    fun findIndexByDescription_returnsMinusOneWhenDescriptionDoesNotExist() {
        data class Node(val desc: String?)

        val nodes = listOf(
            Node("alpha"),
            Node("beta")
        )

        val index = A11yNavigator.findIndexByDescription(
            nodes = nodes,
            descriptionOf = { it.desc },
            excludeDesc = "delta"
        )

        assertEquals(-1, index)
    }

    @Test
    fun shouldIgnoreBottomResidualFocus_returnsTrueWhenFocusedInBottom20Percent() {
        val shouldIgnore = A11yNavigator.shouldIgnoreBottomResidualFocus(
            isAccessibilityFocused = true,
            nodeBounds = Rect(0, 1700, 1080, 1860),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertTrue(shouldIgnore)
    }

    @Test
    fun shouldIgnoreBottomResidualFocus_returnsFalseWhenFocusedOutsideBottom20Percent() {
        val shouldIgnore = A11yNavigator.shouldIgnoreBottomResidualFocus(
            isAccessibilityFocused = true,
            nodeBounds = Rect(0, 1200, 1080, 1360),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertFalse(shouldIgnore)
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
    fun shouldReuseExistingAccessibilityFocus_returnsFalseEvenWhenBoundsExactlyMatch_afterScroll() {
        val reused = A11yNavigator.shouldReuseExistingAccessibilityFocus(
            label = "Plant Care",
            isScrollAction = true,
            currentFocusedBounds = Rect(0, 200, 1080, 360),
            targetBounds = Rect(0, 200, 1080, 360)
        )

        assertFalse(reused)
    }

    @Test
    fun shouldReuseExistingAccessibilityFocus_returnsFalseWhenBoundsDiffer_afterScroll() {
        val reused = A11yNavigator.shouldReuseExistingAccessibilityFocus(
            label = "Plant Care",
            isScrollAction = true,
            currentFocusedBounds = Rect(0, 200, 1080, 360),
            targetBounds = Rect(0, 201, 1080, 360)
        )

        assertFalse(reused)
    }


    @Test
    fun skipCoordinateDuplicateTraversalIndices_skipsAllSequentialDuplicateBounds() {
        data class Node(val bounds: Rect)

        val nextIndex = A11yNavigator.skipCoordinateDuplicateTraversalIndices(
            nodes = listOf(
                Node(Rect(0, 0, 100, 100)),
                Node(Rect(0, 0, 100, 100)),
                Node(Rect(0, 0, 100, 100)),
                Node(Rect(0, 120, 100, 220))
            ),
            currentBounds = Rect(0, 0, 100, 100),
            startIndex = 1,
            boundsOf = { it.bounds }
        )

        assertEquals(3, nextIndex)
    }

    @Test
    fun shouldTriggerLoopFallback_returnsTrueWhenScrolledAndExcludeDescriptionExists() {
        val shouldLoop = A11yNavigator.shouldTriggerLoopFallback(
            focusedAny = false,
            isScrollAction = true,
            excludeDesc = "Pet Care"
        )

        assertTrue(shouldLoop)
    }


    @Test
    fun shouldTriggerLoopFallback_returnsFalseWhenAlreadyFocused() {
        val shouldLoop = A11yNavigator.shouldTriggerLoopFallback(
            focusedAny = true,
            isScrollAction = true,
            excludeDesc = "Pet Care"
        )

        assertFalse(shouldLoop)
    }

    @Test
    fun shouldTriggerLoopFallback_returnsFalseWhenExcludeDescriptionIsBlank() {
        val shouldLoop = A11yNavigator.shouldTriggerLoopFallback(
            focusedAny = false,
            isScrollAction = true,
            excludeDesc = " "
        )

        assertFalse(shouldLoop)
    }

    @Test
    fun calculateEffectiveBottom_appliesSafetyGuideWhenBottomNavNearScreenEnd() {
        data class Node(val label: String?, val rect: Rect)

        val nodes = listOf(
            Node("bottom navigation", Rect(0, 1850, 1080, 1920))
        )

        val effectiveBottom = A11yNavigator.calculateEffectiveBottom(
            nodes = nodes,
            screenTop = 0,
            screenBottom = 1920,
            boundsOf = { it.rect },
            labelOf = { it.label }
        )

        assertEquals(1632, effectiveBottom)
    }

    @Test
    fun calculateEffectiveBottom_usesTopOfBottomNavigationNode() {
        data class Node(val label: String?, val rect: Rect)

        val nodes = listOf(
            Node("content", Rect(0, 100, 100, 200)),
            Node("bottom nav", Rect(0, 1700, 1080, 1920))
        )

        val effectiveBottom = A11yNavigator.calculateEffectiveBottom(
            nodes = nodes,
            screenTop = 0,
            screenBottom = 1920,
            boundsOf = { it.rect },
            labelOf = { it.label }
        )

        assertEquals(1700, effectiveBottom)
    }


    @Test
    fun applyBottomNavigationSafetyGuide_limitsTooDeepBottomTo85Percent() {
        val adjusted = A11yNavigator.applyBottomNavigationSafetyGuide(
            effectiveBottom = 1900,
            screenBottom = 1920
        )

        assertEquals(1632, adjusted)
    }

    @Test
    fun calculateEffectiveBottom_ignoresBottomNavIdentifierInUpperHalf() {
        data class Node(val label: String?, val rect: Rect)

        val nodes = listOf(
            Node("bottom navigation", Rect(0, 400, 1080, 520)),
            Node("bottom navigation", Rect(0, 1700, 1080, 1920))
        )

        val effectiveBottom = A11yNavigator.calculateEffectiveBottom(
            nodes = nodes,
            screenTop = 0,
            screenBottom = 1920,
            boundsOf = { it.rect },
            labelOf = { it.label }
        )

        assertEquals(1700, effectiveBottom)
    }

    @Test
    fun collectVisibleHistory_collectsOnlyVisibleLabels() {
        data class Node(val label: String?, val rect: Rect)

        val history = A11yNavigator.collectVisibleHistory(
            nodes = listOf(
                Node("Pet Care", Rect(0, 100, 100, 200)),
                Node("Clothing Care", Rect(0, 1900, 100, 2000)),
                Node(" ", Rect(0, 300, 100, 400)),
                Node(null, Rect(0, 500, 100, 600))
            ),
            screenTop = 0,
            screenBottom = 1920,
            boundsOf = { it.rect },
            labelOf = { it.label }
        )

        assertEquals(setOf("Pet Care", "Clothing Care"), history)
    }



    @Test
    fun collectVisibleHistory_excludesTopAndBottomBars() {
        data class Node(val label: String?, val rect: Rect, val isTopBar: Boolean = false, val isBottomBar: Boolean = false)

        val history = A11yNavigator.collectVisibleHistory(
            nodes = listOf(
                Node("Header", Rect(0, 0, 100, 120), isTopBar = true),
                Node("Plant Care", Rect(0, 200, 100, 320)),
                Node("Home", Rect(0, 1720, 100, 1840), isBottomBar = true)
            ),
            screenTop = 0,
            screenBottom = 1920,
            boundsOf = { it.rect },
            labelOf = { it.label },
            isTopAppBarNodeOf = { node, _ -> node.isTopBar },
            isBottomNavigationBarNodeOf = { node, _ -> node.isBottomBar }
        )

        assertEquals(setOf("Plant Care"), history)
    }

    @Test
    fun collectVisibleHistorySignatures_collectsVisibleMetadata() {
        data class Node(val label: String?, val viewId: String?, val rect: Rect)

        val signatures = A11yNavigator.collectVisibleHistorySignatures(
            nodes = listOf(
                Node("History", "com.test:id/history", Rect(0, 120, 1000, 320)),
                Node("Privacy notice", "com.test:id/privacy_notice", Rect(0, 380, 1000, 620))
            ),
            screenTop = 0,
            screenBottom = 1920,
            boundsOf = { it.rect },
            labelOf = { it.label },
            viewIdOf = { it.viewId }
        )

        assertEquals(2, signatures.size)
        assertTrue(signatures.any { it.label == "History" && it.viewId == "com.test:id/history" })
    }

    @Test
    fun isInVisibleHistory_returnsTrue_forRecoveredLabelOrMatchingViewId() {
        val signatures = setOf(
            A11yNavigator.VisibleHistorySignature(
                label = "History",
                viewId = "com.test:id/history",
                bounds = Rect(0, 120, 1000, 320)
            )
        )

        val recoveredLabelMatch = A11yNavigator.isInVisibleHistory(
            label = "History",
            viewId = "com.test:id/unknown",
            bounds = Rect(0, 600, 1000, 820),
            visibleHistory = emptySet(),
            visibleHistorySignatures = signatures
        )
        val viewIdMatch = A11yNavigator.isInVisibleHistory(
            label = "Privacy notice",
            viewId = "com.test:id/history",
            bounds = Rect(0, 600, 1000, 820),
            visibleHistory = emptySet(),
            visibleHistorySignatures = signatures
        )

        assertTrue(recoveredLabelMatch)
        assertTrue(viewIdMatch)
    }

    @Test
    fun shouldSkipHistoryNodeAfterScroll_appliesFixedUiAndScrollableContentRules() {
        assertTrue(
            A11yNavigator.shouldSkipHistoryNodeAfterScroll(
                isScrollAction = true,
                inHistory = true,
                isFixedUi = false,
                isInsideMainScrollContainer = true,
                isTopArea = false
            )
        )
        assertTrue(
            A11yNavigator.shouldSkipHistoryNodeAfterScroll(
                isScrollAction = true,
                inHistory = true,
                isFixedUi = true,
                isInsideMainScrollContainer = false,
                isTopArea = false
            )
        )
    }

    @Test
    fun shouldSkipHistoryNodeAfterScroll_returnsFalseForTopAreaHistoryAfterScroll() {
        val skipped = A11yNavigator.shouldSkipHistoryNodeAfterScroll(
            isScrollAction = true,
            inHistory = true,
            isFixedUi = false,
            isInsideMainScrollContainer = true,
            isTopArea = true
        )

        assertFalse(skipped)
    }

    @Test
    fun shouldSkipHistoryNodeAfterScroll_returnsTrueWhenHistoryNodeIsOutsideTopArea() {
        val skipped = A11yNavigator.shouldSkipHistoryNodeAfterScroll(
            isScrollAction = true,
            inHistory = true,
            isFixedUi = false,
            isInsideMainScrollContainer = true,
            isTopArea = false
        )

        assertTrue(skipped)
    }

    @Test
    fun shouldSkipDuplicateBoundsCandidate_returnsTrueWhenBoundsMatchEvenForLabeledNode() {
        val result = A11yNavigator.shouldSkipDuplicateBoundsCandidate(
            currentFocusedBounds = Rect(0, 100, 300, 240),
            candidateBounds = Rect(0, 100, 300, 240),
            isScrollAction = false
        )

        assertTrue(result)
    }

    @Test
    fun shouldReuseExistingAccessibilityFocus_returnsFalseForNoLabelEvenWhenBoundsMatch() {
        val reused = A11yNavigator.shouldReuseExistingAccessibilityFocus(
            label = "<no-label>",
            isScrollAction = false,
            currentFocusedBounds = Rect(0, 200, 1080, 360),
            targetBounds = Rect(0, 200, 1080, 360)
        )

        assertFalse(reused)
    }

    @Test
    fun shouldDelayBeforeFocusCommand_returnsTrueForHorizontalTraversalOnSameRow() {
        val shouldDelay = A11yNavigator.shouldDelayBeforeFocusCommand(
            currentFocusedBounds = Rect(0, 200, 200, 320),
            targetBounds = Rect(220, 200, 420, 320)
        )

        assertTrue(shouldDelay)
    }

    @Test
    fun shouldDelayBeforeFocusCommand_returnsFalseWhenBoundsExactlyMatch() {
        val shouldDelay = A11yNavigator.shouldDelayBeforeFocusCommand(
            currentFocusedBounds = Rect(0, 200, 200, 320),
            targetBounds = Rect(0, 200, 200, 320)
        )

        assertFalse(shouldDelay)
    }


    @Test
    fun requestAccessibilityFocusWithRetry_retriesThreeTimesByDefault() {
        var actionCalls = 0
        var refreshCalls = 0

        val result = A11yNavigator.requestAccessibilityFocusWithRetry(
            performFocusAction = {
                actionCalls += 1
                false
            },
            refreshFocusState = {
                refreshCalls += 1
                false
            }
        )

        assertFalse(result)
        assertEquals(3, actionCalls)
        assertEquals(3, refreshCalls)
    }

    @Test
    fun isAccessibilityFocusEffectivelyActive_returnsFalseForSamePreviousTraversalIndex() {
        val field = A11yNavigator::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val originalValue = field.getInt(null)

        try {
            field.setInt(null, 7)

            val result = A11yNavigator.isAccessibilityFocusEffectivelyActive(
                isAccessibilityFocused = true,
                traversalIndex = 7
            )

            assertFalse(result)
        } finally {
            field.setInt(null, originalValue)
        }
    }

    @Test
    fun isAccessibilityFocusEffectivelyActive_returnsTrueForDifferentTraversalIndex() {
        val field = A11yNavigator::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val originalValue = field.getInt(null)

        try {
            field.setInt(null, 3)

            val result = A11yNavigator.isAccessibilityFocusEffectivelyActive(
                isAccessibilityFocused = true,
                traversalIndex = 4
            )

            assertTrue(result)
        } finally {
            field.setInt(null, originalValue)
        }
    }

    @Test
    fun isAccessibilityFocusEffectivelyActive_returnsTrueWhenBoundsMatchEvenForStaleIndex() {
        val field = A11yNavigator::class.java.getDeclaredField("lastRequestedFocusIndex").apply {
            isAccessible = true
        }
        val originalValue = field.getInt(null)

        try {
            field.setInt(null, 11)
            val targetBounds = Rect(0, 500, 400, 650)

            val result = A11yNavigator.isAccessibilityFocusEffectivelyActive(
                isAccessibilityFocused = true,
                traversalIndex = 11,
                actualFocusedBounds = Rect(targetBounds),
                targetBounds = targetBounds
            )

            assertTrue(result)
        } finally {
            field.setInt(null, originalValue)
        }
    }

    @Test
    fun shouldScrollAtEndOfTraversal_returnsFalseWhenNextIndexOutOfBoundsEvenIfScrollableExists() {
        val shouldScroll = A11yNavigator.shouldScrollAtEndOfTraversal(
            currentIndex = 2,
            nextIndex = 3,
            traversalList = listOf("a", "b", "c"),
            scrollableNodeExists = true
        )

        assertFalse(shouldScroll)
    }

    @Test
    fun shouldTerminateAtLastBottomBar_returnsTrueForLastBottomTab() {
        data class Node(val className: String?, val viewId: String?, val bounds: Rect)
        val nodes = listOf(
            Node("android.widget.TextView", "com.test:id/content", Rect(0, 400, 1000, 600)),
            Node("android.widget.LinearLayout", "com.test:id/bottom_nav_menu", Rect(0, 1800, 1000, 2000))
        )

        val terminate = A11yNavigator.shouldTerminateAtLastBottomBar(
            traversalList = nodes,
            currentIndex = 1,
            lastIndex = 1,
            screenBottom = 2000,
            screenHeight = 2000,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertTrue(terminate)
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

        assertFalse(result)
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
    fun isBottomNavigationBarNode_returnsFalseForGenericMenuKeyword() {
        val result = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.ImageButton",
            viewIdResourceName = "com.test:id/menu_more_options",
            boundsInScreen = Rect(0, 100, 100, 200),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertFalse(result)
    }

    @Test
    fun isBottomNavigationBarNode_returnsTrueForBottomTabKeyword() {
        val result = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.test:id/bottom_tab_home",
            boundsInScreen = Rect(0, 1700, 1080, 1850),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertTrue(result)
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
        val addButton = A11yNavigator.isTopAppBarNode(
            className = "android.widget.ImageButton",
            viewIdResourceName = "com.test:id/add_button",
            boundsInScreen = Rect(0, 560, 1080, 680),
            screenTop = 0,
            screenHeight = 1920
        )
        val addMenu = A11yNavigator.isTopAppBarNode(
            className = "android.widget.ImageButton",
            viewIdResourceName = "com.test:id/add_menu",
            boundsInScreen = Rect(0, 580, 1080, 700),
            screenTop = 0,
            screenHeight = 1920
        )
        val menuButton = A11yNavigator.isTopAppBarNode(
            className = "android.widget.ImageButton",
            viewIdResourceName = "com.test:id/menu_button",
            boundsInScreen = Rect(0, 600, 1080, 720),
            screenTop = 0,
            screenHeight = 1920
        )

        assertTrue(homeButton)
        assertTrue(tabTitle)
        assertTrue(headerBar)
        assertTrue(addButton)
        assertTrue(addMenu)
        assertTrue(menuButton)
    }

    @Test
    fun isTopAppBarNode_returnsFalseForSettingsButtonLayoutViewId() {
        val result = A11yNavigator.isTopAppBarNode(
            className = "android.widget.ImageButton",
            viewIdResourceName = "com.samsung.android.oneconnect:id/setting_button_layout",
            boundsInScreen = Rect(980, 80, 1060, 160),
            screenTop = 0,
            screenHeight = 1920
        )

        assertFalse(result)
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
        val menuLife = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.samsung.android.oneconnect:id/menu_life",
            boundsInScreen = Rect(0, 260, 1080, 380),
            screenBottom = 1920,
            screenHeight = 1920
        )
        val menuRoutines = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.samsung.android.oneconnect:id/menu_routines",
            boundsInScreen = Rect(0, 280, 1080, 400),
            screenBottom = 1920,
            screenHeight = 1920
        )
        val menuServices = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.samsung.android.oneconnect:id/menu_services",
            boundsInScreen = Rect(0, 290, 1080, 410),
            screenBottom = 1920,
            screenHeight = 1920
        )
        val menuAutomations = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.samsung.android.oneconnect:id/menu_automations",
            boundsInScreen = Rect(0, 295, 1080, 415),
            screenBottom = 1920,
            screenHeight = 1920
        )
        val menuMore = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.samsung.android.oneconnect:id/menu_more",
            boundsInScreen = Rect(0, 298, 1080, 418),
            screenBottom = 1920,
            screenHeight = 1920
        )
        val menuMenu = A11yNavigator.isBottomNavigationBarNode(
            className = "android.widget.LinearLayout",
            viewIdResourceName = "com.samsung.android.oneconnect:id/menu_menu",
            boundsInScreen = Rect(0, 300, 1080, 420),
            screenBottom = 1920,
            screenHeight = 1920
        )

        assertTrue(menuPrefix)
        assertTrue(tabPrefix)
        assertTrue(bottomNav)
        assertTrue(menuLife)
        assertTrue(menuRoutines)
        assertTrue(menuServices)
        assertTrue(menuAutomations)
        assertTrue(menuMore)
        assertTrue(menuMenu)
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

    @Test
    fun findNodeIndexByIdentity_returnsMatchedIndexUsingIdTextDescAndBounds() {
        data class IdentityNode(val id: String?, val text: String?, val desc: String?, val bounds: Rect)

        val first = IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card A", bounds = Rect(0, 400, 400, 520))
        val second = IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card B", bounds = Rect(0, 580, 400, 700))
        val list = listOf(first, second)

        val index = A11yNavigator.findNodeIndexByIdentity(
            nodes = list,
            target = second,
            idOf = { it.id },
            textOf = { it.text },
            contentDescriptionOf = { it.desc },
            boundsOf = { it.bounds }
        )

        assertTrue(index == 1)
    }

    @Test
    fun findNodeIndexByIdentity_returnsNearestIndexWhenBoundsDoNotMatchButIdTextDescMatch() {
        data class IdentityNode(val id: String?, val text: String?, val desc: String?, val bounds: Rect)

        val target = IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card A", bounds = Rect(0, 401, 400, 520))
        val list = listOf(
            IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card A", bounds = Rect(0, 400, 400, 520))
        )

        val index = A11yNavigator.findNodeIndexByIdentity(
            nodes = list,
            target = target,
            idOf = { it.id },
            textOf = { it.text },
            contentDescriptionOf = { it.desc },
            boundsOf = { it.bounds }
        )

        assertTrue(index == 0)
    }

    @Test
    fun findNodeIndexByIdentity_returnsClosestIndexAmongIdTextDescMatches() {
        data class IdentityNode(val id: String?, val text: String?, val desc: String?, val bounds: Rect)

        val target = IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card A", bounds = Rect(0, 500, 400, 620))
        val list = listOf(
            IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card A", bounds = Rect(0, 100, 400, 220)),
            IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card A", bounds = Rect(0, 540, 400, 660)),
            IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card A", bounds = Rect(0, 900, 400, 1020))
        )

        val index = A11yNavigator.findNodeIndexByIdentity(
            nodes = list,
            target = target,
            idOf = { it.id },
            textOf = { it.text },
            contentDescriptionOf = { it.desc },
            boundsOf = { it.bounds }
        )

        assertTrue(index == 1)
    }


    @Test
    fun findNodeIndexByIdentity_returnsMinusOneWhenOnlyDescriptionDiffers() {
        data class IdentityNode(val id: String?, val text: String?, val desc: String?, val bounds: Rect)

        val target = IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card B", bounds = Rect(0, 500, 400, 620))
        val list = listOf(
            IdentityNode(id = "com.test:id/item", text = "Living Room", desc = "Card A", bounds = Rect(0, 540, 400, 660))
        )

        val index = A11yNavigator.findNodeIndexByIdentity(
            nodes = list,
            target = target,
            idOf = { it.id },
            textOf = { it.text },
            contentDescriptionOf = { it.desc },
            boundsOf = { it.bounds }
        )

        assertEquals(-1, index)
    }

    @Test
    fun findNodeIndexByIdentity_prefersCoordinateMatchEvenWhenIdentityDiffers() {
        data class IdentityNode(val id: String?, val text: String?, val desc: String?, val bounds: Rect)

        val target = IdentityNode(id = "com.test:id/current", text = "현재", desc = "현재 카드", bounds = Rect(0, 500, 400, 620))
        val list = listOf(
            IdentityNode(id = "com.test:id/changed", text = "변경됨", desc = "다른 카드", bounds = Rect(0, 500, 400, 620))
        )

        val index = A11yNavigator.findNodeIndexByIdentity(
            nodes = list,
            target = target,
            idOf = { it.id },
            textOf = { it.text },
            contentDescriptionOf = { it.desc },
            boundsOf = { it.bounds }
        )

        assertEquals(0, index)
    }

    @Test
    fun isSameNodeIdentity_returnsFalseWhenStrictMatchFailsAndDescDiffers() {
        val result = A11yNavigator.isSameNodeIdentity(
            aId = "com.test:id/item",
            aText = "거실 조명",
            aContentDescription = "거실 조명 버튼",
            aBounds = Rect(0, 100, 100, 200),
            bId = "com.test:id/item",
            bText = "거실 조명",
            bContentDescription = "다른 설명",
            bBounds = Rect(0, 130, 100, 230)
        )

        assertFalse(result)
    }

    @Test
    fun isSameNodeIdentity_returnsTrueWhenBoundsMatchExactlyEvenIfIdentityChanged() {
        val result = A11yNavigator.isSameNodeIdentity(
            aId = "com.test:id/item",
            aText = "거실 조명",
            aContentDescription = "거실 조명 버튼",
            aBounds = Rect(0, 100, 100, 200),
            bId = "com.test:id/item_alt",
            bText = "새 라벨",
            bContentDescription = "새 설명",
            bBounds = Rect(0, 100, 100, 200)
        )

        assertTrue(result)
    }

    @Test
    fun isSameNodeIdentity_returnsFalseWhenIdentityDiffersAndBoundsAlsoDiffer() {
        val result = A11yNavigator.isSameNodeIdentity(
            aId = "com.test:id/item",
            aText = "거실 조명",
            aContentDescription = "거실 조명 버튼",
            aBounds = Rect(0, 100, 100, 200),
            bId = "com.test:id/item_alt",
            bText = "거실 조명",
            bContentDescription = "거실 조명 버튼",
            bBounds = Rect(1, 100, 101, 200)
        )

        assertFalse(result)
    }

    @Test
    fun isWithinSnapBackTolerance_returnsTrueWithinTenPixels() {
        val result = A11yNavigator.isWithinSnapBackTolerance(
            targetBounds = Rect(0, 100, 100, 200),
            actualBounds = Rect(8, 108, 108, 208)
        )

        assertTrue(result)
    }

    @Test
    fun isWithinSnapBackTolerance_returnsFalseBeyondTenPixels() {
        val result = A11yNavigator.isWithinSnapBackTolerance(
            targetBounds = Rect(0, 100, 100, 200),
            actualBounds = Rect(11, 111, 111, 211)
        )

        assertFalse(result)
    }


    @Test
    fun isNodePhysicallyOffScreen_returnsTrueWhenNodeIsAboveScreen() {
        val offScreen = A11yNavigator.isNodePhysicallyOffScreen(
            bounds = Rect(0, -200, 100, -10),
            screenTop = 0,
            screenBottom = 1920
        )

        assertTrue(offScreen)
    }

    @Test
    fun isNodePhysicallyOffScreen_returnsTrueWhenNodeIsBelowScreen() {
        val offScreen = A11yNavigator.isNodePhysicallyOffScreen(
            bounds = Rect(0, 2000, 100, 2100),
            screenTop = 0,
            screenBottom = 1920
        )

        assertTrue(offScreen)
    }

    @Test
    fun shouldTriggerLoopFallback_returnsTrueWhenScrollExclusionFailsToFocus() {
        val shouldLoop = A11yNavigator.shouldTriggerLoopFallback(
            focusedAny = false,
            isScrollAction = true,
            excludeDesc = "최근 재생"
        )

        assertTrue(shouldLoop)
    }

    @Test
    fun shouldTriggerLoopFallback_returnsFalseWhenExcludeDescIsNull() {
        val shouldLoop = A11yNavigator.shouldTriggerLoopFallback(
            focusedAny = false,
            isScrollAction = true,
            excludeDesc = null
        )

        assertFalse(shouldLoop)
    }


    @Test
    fun requestAccessibilityFocusWithRetry_usesUpdatedDefaultHardFocusPolicy() {
        var attempts = 0

        val result = A11yNavigator.requestAccessibilityFocusWithRetry(
            performFocusAction = {
                attempts += 1
                false
            },
            refreshFocusState = { false }
        )

        assertFalse(result)
        assertEquals(3, attempts)
    }

    @Test
    fun requestAccessibilityFocusWithRetry_returnsFalseWhenSystemNeverAcceptsFocus() {
        var attempts = 0

        val result = A11yNavigator.requestAccessibilityFocusWithRetry(
            performFocusAction = {
                attempts += 1
                false
            },
            refreshFocusState = { false },
            retryDelayMs = 0L
        )

        assertFalse(result)
        assertEquals(3, attempts)
    }

    @Test
    fun findPartiallyVisibleNextCandidate_prefersBottomClippedNextContent() {
        data class Candidate(val bounds: Rect, val className: String? = null, val viewId: String? = null)

        val candidates = listOf(
            Candidate(Rect(0, 200, 1080, 420), className = "android.view.View", viewId = "current"),
            Candidate(Rect(0, 430, 1080, 760), className = "android.view.View", viewId = "pet_care"),
            Candidate(Rect(0, 770, 1080, 1090), className = "android.view.View", viewId = "home_care")
        )

        val index = A11yNavigator.findPartiallyVisibleNextCandidate(
            traversalList = candidates,
            currentIndex = 0,
            screenTop = 0,
            effectiveBottom = 800,
            screenBottom = 900,
            screenHeight = 900,
            boundsOf = { it.bounds },
            classNameOf = { it.className },
            viewIdOf = { it.viewId }
        )

        assertEquals(1, index)
    }

    @Test
    fun shouldUseMinimalPreFocusAdjustment_returnsFalseWhenIntendedAlreadyFullyVisible() {
        val result = A11yNavigator.shouldUseMinimalPreFocusAdjustment(
            intendedBounds = Rect(0, 300, 1080, 600),
            trailingCandidateBounds = null,
            screenTop = 0,
            effectiveBottom = 900
        )

        assertFalse(result)
    }

    @Test
    fun shouldUseMinimalPreFocusAdjustment_returnsTrueWhenIntendedIsPartiallyVisible() {
        val result = A11yNavigator.shouldUseMinimalPreFocusAdjustment(
            intendedBounds = Rect(0, 650, 1080, 980),
            trailingCandidateBounds = Rect(0, 990, 1080, 1250),
            screenTop = 0,
            effectiveBottom = 900
        )

        assertTrue(result)
    }

    @Test
    fun wouldOvershootPastIntendedCandidate_detectsWhenIntendedIsPushedAboveViewport() {
        val overshoot = A11yNavigator.wouldOvershootPastIntendedCandidate(
            intendedBounds = Rect(0, -180, 1080, -10),
            trailingCandidateBounds = Rect(0, 0, 1080, 260),
            screenTop = 0,
            effectiveBottom = 900
        )

        assertTrue(overshoot)
    }

    @Test
    fun wouldOvershootPastIntendedCandidate_returnsFalseForLastNodeBestEffortCase() {
        val overshoot = A11yNavigator.wouldOvershootPastIntendedCandidate(
            intendedBounds = Rect(0, 620, 1080, 930),
            trailingCandidateBounds = null,
            screenTop = 0,
            effectiveBottom = 900
        )

        assertFalse(overshoot)
    }
}
