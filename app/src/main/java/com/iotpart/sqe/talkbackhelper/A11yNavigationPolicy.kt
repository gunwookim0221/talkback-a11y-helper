package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.util.Log
import com.iotpart.sqe.talkbackhelper.A11yNavigator.isContainerLikeClassName
import com.iotpart.sqe.talkbackhelper.A11yNavigator.isContainerLikeViewId
import com.iotpart.sqe.talkbackhelper.A11yNavigator.isNodePhysicallyOffScreen
import com.iotpart.sqe.talkbackhelper.A11yNavigator.isWithinTopContentArea

object A11yNavigationPolicy {

    internal fun decideSmartNextNavigationDecision(
        state: SmartNextRuntimeState,
        initialTarget: InitialNextTargetDecision,
        smartNextState: SmartNextState
    ): NavigationDecision {
        val traversalList = state.normalize.traversalList
        val normalize = state.normalize
        val collect = state.collect
        val currentIndex = state.currentPosition.currentIndex
        var nextIndex = initialTarget.nextIndex
        val nextIndexInitial = nextIndex
        val lastIndex = traversalList.lastIndex
        val isOutOfBounds = nextIndex !in traversalList.indices
        val isCurrentAtLastIndex = currentIndex == lastIndex
        val shouldTerminateAtLastBottomBar = shouldTerminateAtLastBottomBar(
            traversalList = traversalList,
            currentIndex = currentIndex,
            lastIndex = lastIndex,
            screenBottom = normalize.screenBottom,
            screenHeight = normalize.screenHeight,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName }
        )
        val shouldScrollAtEnd = shouldScrollAtEndOfTraversal(
            currentIndex = currentIndex,
            nextIndex = nextIndex,
            traversalList = traversalList,
            scrollableNodeExists = collect.scrollState.scrollableNode != null
        )

        var nextIsBottomBar = nextIndex in traversalList.indices && A11yNodeUtils.isBottomNavigationBar(
            className = traversalList[nextIndex].className?.toString(),
            viewIdResourceName = traversalList[nextIndex].viewIdResourceName,
            boundsInScreen = Rect().also { traversalList[nextIndex].getBoundsInScreen(it) },
            screenBottom = normalize.screenBottom,
            screenHeight = normalize.screenHeight
        )
        if (nextIsBottomBar) {
            val intermediateTrailingContentIndex = findIntermediateContentCandidateBeforeBottomBar(
                traversalList = traversalList,
                currentIndex = currentIndex,
                bottomBarIndex = nextIndex,
                screenTop = normalize.screenTop,
                screenBottom = normalize.screenBottom,
                screenHeight = normalize.screenHeight,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                classNameOf = { node -> node.className?.toString() },
                viewIdOf = { node -> node.viewIdResourceName }
            )
            val continuationDecision = decideContinuationBeforeBottomBar(
                nextIsBottomBar = true,
                intermediateTrailingContentIndex = intermediateTrailingContentIndex,
                defaultNextIndex = nextIndex
            )
            if (continuationDecision.type == SelectionType.CONTINUATION && continuationDecision.targetIndex != null) {
                nextIndex = continuationDecision.targetIndex
                nextIsBottomBar = false
            }
        }

        val continuationLikely = isContinuationContentLikelyBelowCurrentNode(
            traversalList = traversalList,
            currentIndex = currentIndex,
            nextIndex = nextIndex,
            screenTop = normalize.screenTop,
            screenBottom = normalize.screenBottom,
            screenHeight = normalize.screenHeight,
            effectiveBottom = normalize.effectiveBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName }
        )
        val rowOrGridContinuationDetected = hasContinuationPatternBelowCurrentNode(
            traversalList = traversalList,
            currentIndex = currentIndex,
            nextIndex = nextIndex,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName }
        )
        val continuationExistsBeforeBottomBar = nextIsBottomBar && hasContinuationContentBeforeBottomBar(
            traversalList = traversalList,
            currentIndex = currentIndex,
            bottomBarIndex = nextIndex,
            screenTop = normalize.screenTop,
            screenBottom = normalize.screenBottom,
            screenHeight = normalize.screenHeight,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName }
        )
        val shouldScrollBeforeBottomBar = shouldScrollBeforeBottomBar(
            traversalList = traversalList,
            currentIndex = currentIndex,
            nextIndex = nextIndex,
            screenTop = normalize.screenTop,
            screenBottom = normalize.screenBottom,
            screenHeight = normalize.screenHeight,
            effectiveBottom = normalize.effectiveBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName },
            canScrollForwardHint = collect.scrollState.scrollableNode != null
        )
        val isCurrentNearBottom = currentIndex in traversalList.indices &&
            isNearBottomEdge(bounds = Rect().also { traversalList[currentIndex].getBoundsInScreen(it) }, effectiveBottom = normalize.effectiveBottom)
        val forcePreScrollBeforeBottomBar = shouldForcePreScrollBeforeBottomBar(
            shouldScrollBeforeBottomBar = shouldScrollBeforeBottomBar,
            continuationContentLikelyBelowCurrentGrid = continuationLikely || rowOrGridContinuationDetected
        )
        val contentTraversalCompleteBeforeBottomBar = nextIsBottomBar && isContentTraversalCompleteBeforeBottomBar(
            traversalList = traversalList,
            currentIndex = currentIndex,
            bottomBarIndex = nextIndex,
            screenTop = normalize.screenTop,
            screenBottom = normalize.screenBottom,
            screenHeight = normalize.screenHeight,
            effectiveBottom = normalize.effectiveBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName },
            isFixedUiOf = { node -> A11yNodeUtils.isFixedSystemUI(node, collect.scrollState.mainScrollContainer) },
            canScrollForwardHint = collect.scrollState.scrollableNode != null
        )
        val navigationDecision = decideNextNavigationType(
            nextIsBottomBar = nextIsBottomBar,
            scrollableNodeExists = smartNextState.scrollableContainer != null,
            contentTraversalCompleteBeforeBottomBar = contentTraversalCompleteBeforeBottomBar,
            continuationLikely = continuationLikely,
            rowOrGridContinuationDetected = rowOrGridContinuationDetected,
            continuationExistsBeforeBottomBar = continuationExistsBeforeBottomBar,
            isCurrentNearBottom = isCurrentNearBottom,
            forcePreScrollBeforeBottomBar = forcePreScrollBeforeBottomBar,
            isOutOfBounds = isOutOfBounds,
            isCurrentAtLastIndex = isCurrentAtLastIndex,
            shouldScrollAtEnd = shouldScrollAtEnd,
            shouldTerminateAtLastBottomBar = shouldTerminateAtLastBottomBar,
            nextIndex = nextIndex
        )
        Log.i(
            "A11Y_HELPER",
            "[DECIDE] current=$currentIndex next=$nextIndex nav=${navigationDecision.type} outOfBounds=$isOutOfBounds atLast=$isCurrentAtLastIndex nextIsBottomBar=$nextIsBottomBar reason=${navigationDecision.reason}"
        )
        Log.w(
            "A11Y_HELPER",
            "[SMART_NEXT][policy] current_index=$currentIndex next_index_initial=$nextIndexInitial next_index_final=$nextIndex next_is_bottom_bar=$nextIsBottomBar continuation_likely=$continuationLikely row_or_grid_continuation=$rowOrGridContinuationDetected continuation_exists_before_bottom_bar=$continuationExistsBeforeBottomBar is_current_near_bottom=$isCurrentNearBottom force_pre_scroll_before_bottom_bar=$forcePreScrollBeforeBottomBar nav_type=${navigationDecision.type}"
        )
        return navigationDecision
    }


    internal fun decideSmartNextExecution(
        state: SmartNextRuntimeState,
        initialTarget: InitialNextTargetDecision,
        navigationDecision: NavigationDecision
    ): SmartNextExecutionDecision {
        val traversalList = state.normalize.traversalList
        val currentIndex = state.currentPosition.currentIndex
        val nextIndex = initialTarget.nextIndex
        val lastIndex = traversalList.lastIndex
        val isOutOfBounds = nextIndex !in traversalList.indices
        val isCurrentAtLastIndex = currentIndex == lastIndex
        val shouldTerminateAtLastBottomBar = shouldTerminateAtLastBottomBar(
            traversalList = traversalList,
            currentIndex = currentIndex,
            lastIndex = lastIndex,
            screenBottom = state.normalize.screenBottom,
            screenHeight = state.normalize.screenHeight,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName }
        )
        val shouldScrollAtEnd = shouldScrollAtEndOfTraversal(
            currentIndex = currentIndex,
            nextIndex = nextIndex,
            traversalList = traversalList,
            scrollableNodeExists = state.collect.scrollState.scrollableNode != null
        )
        val expectedStatus = when (navigationDecision.type) {
            NavigationType.BOTTOM_BAR -> "moved"
            NavigationType.PRE_SCROLL -> "scrolled"
            NavigationType.END -> "reached_end"
            NavigationType.REGULAR -> "moved"
        }
        return SmartNextExecutionDecision(
            nextIndex = nextIndex,
            currentIndex = currentIndex,
            isOutOfBounds = isOutOfBounds,
            isCurrentAtLastIndex = isCurrentAtLastIndex,
            shouldTerminateAtLastBottomBar = shouldTerminateAtLastBottomBar,
            shouldScrollAtEnd = shouldScrollAtEnd,
            navigationDecision = navigationDecision,
            postScrollScanStartIndex = 0,
            allowLooping = false,
            allowBottomBarEntry = navigationDecision.type == NavigationType.BOTTOM_BAR,
            expectedStatus = expectedStatus
        )
    }



    internal fun decideContinuationBeforeBottomBar(
        nextIsBottomBar: Boolean,
        intermediateTrailingContentIndex: Int,
        defaultNextIndex: Int
    ): SelectionDecisionModel {
        if (!nextIsBottomBar) {
            return SelectionDecisionModel(
                type = SelectionType.REGULAR,
                targetIndex = defaultNextIndex,
                reason = "next_not_bottom_bar"
            )
        }
        if (intermediateTrailingContentIndex >= 0) {
            return SelectionDecisionModel(
                type = SelectionType.CONTINUATION,
                targetIndex = intermediateTrailingContentIndex,
                reason = "intermediate_content_before_bottom_bar"
            )
        }
        return SelectionDecisionModel(
            type = SelectionType.BOTTOM_BAR,
            targetIndex = defaultNextIndex,
            reason = "no_intermediate_continuation"
        )
    }


    internal fun decidePostScrollContinuation(
        resolvedAnchorIndex: Int,
        fallbackBelowAnchorIndex: Int,
        traversalStartIndex: Int,
        traversalSize: Int,
        continuationFallbackFailed: Boolean
    ): SelectionDecisionModel {
        val plan = decidePostScrollContinuationPlan(
            resolvedAnchorIndex = resolvedAnchorIndex,
            fallbackBelowAnchorIndex = fallbackBelowAnchorIndex,
            traversalStartIndex = traversalStartIndex,
            traversalSize = traversalSize,
            continuationFallbackFailed = continuationFallbackFailed
        )
        val decisionType = when {
            plan.skipGeneralScan -> SelectionType.END
            plan.anchorStartIndex >= traversalSize -> SelectionType.END
            else -> SelectionType.CONTINUATION
        }
        return SelectionDecisionModel(
            type = decisionType,
            targetIndex = plan.anchorStartIndex,
            reason = if (plan.skipGeneralScan) "continuation_fallback_failed" else "continuation_scan_ready"
        )
    }



    internal fun decideNextNavigationType(
        nextIsBottomBar: Boolean,
        scrollableNodeExists: Boolean,
        contentTraversalCompleteBeforeBottomBar: Boolean,
        continuationLikely: Boolean,
        rowOrGridContinuationDetected: Boolean,
        continuationExistsBeforeBottomBar: Boolean,
        isCurrentNearBottom: Boolean,
        forcePreScrollBeforeBottomBar: Boolean,
        isOutOfBounds: Boolean,
        isCurrentAtLastIndex: Boolean,
        shouldScrollAtEnd: Boolean,
        shouldTerminateAtLastBottomBar: Boolean,
        nextIndex: Int,
        noProgressAfterScroll: Boolean = false
    ): NavigationDecision {
        if (isOutOfBounds || isCurrentAtLastIndex) {
            return if (shouldScrollAtEnd && !shouldTerminateAtLastBottomBar && scrollableNodeExists) {
                NavigationDecision(
                    type = NavigationType.PRE_SCROLL,
                    targetIndex = nextIndex,
                    reason = "end_of_traversal_scroll"
                )
            } else {
                NavigationDecision(type = NavigationType.END, reason = "end_boundary")
            }
        }
        if (!nextIsBottomBar) {
            return NavigationDecision(
                type = NavigationType.REGULAR,
                targetIndex = nextIndex,
                reason = "regular_candidate"
            )
        }
        if (!scrollableNodeExists) {
            return NavigationDecision(
                type = NavigationType.BOTTOM_BAR,
                targetIndex = nextIndex,
                reason = "no_scrollable_container"
            )
        }
        if (noProgressAfterScroll) {
            return NavigationDecision(
                type = NavigationType.BOTTOM_BAR,
                targetIndex = nextIndex,
                reason = "no_progress_after_scroll"
            )
        }
        if (contentTraversalCompleteBeforeBottomBar) {
            return NavigationDecision(
                type = NavigationType.BOTTOM_BAR,
                targetIndex = nextIndex,
                reason = "content_continuation_exhausted"
            )
        }
        val continuationSignals = continuationLikely || rowOrGridContinuationDetected || continuationExistsBeforeBottomBar || isCurrentNearBottom
        if (forcePreScrollBeforeBottomBar || continuationSignals) {
            return NavigationDecision(
                type = NavigationType.PRE_SCROLL,
                targetIndex = nextIndex,
                reason = "continuation_signal_detected"
            )
        }
        return NavigationDecision(
            type = NavigationType.BOTTOM_BAR,
            targetIndex = nextIndex,
            reason = "no_valid_continuation_signal"
        )
    }


    internal fun decidePostScrollContinuationPlan(
        resolvedAnchorIndex: Int,
        fallbackBelowAnchorIndex: Int,
        traversalStartIndex: Int,
        traversalSize: Int,
        continuationFallbackFailed: Boolean
    ): PostScrollContinuationPlan {
        val anchorStartIndex = when {
            resolvedAnchorIndex >= 0 -> (resolvedAnchorIndex + 1).coerceAtLeast(traversalStartIndex)
            fallbackBelowAnchorIndex >= 0 -> fallbackBelowAnchorIndex.coerceAtLeast(traversalStartIndex)
            continuationFallbackFailed -> traversalSize
            else -> traversalStartIndex
        }
        return PostScrollContinuationPlan(
            anchorStartIndex = anchorStartIndex,
            skipGeneralScan = continuationFallbackFailed
        )
    }


    internal fun <T> isThinTrailingContentAboveBottomBar(
        node: T,
        bounds: Rect,
        bottomBarTop: Int,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        thinBandPx: Int = 80
    ): Boolean {
        if (bottomBarTop <= 0) return false
        if (bounds.height() <= 0) return false
        if (bounds.bottom > bottomBarTop) return false
        val gapToBottomBar = bottomBarTop - bounds.bottom
        if (gapToBottomBar !in 0..thinBandPx) return false

        val className = classNameOf(node)?.lowercase().orEmpty()
        val viewId = viewIdOf(node)?.lowercase().orEmpty()
        val isFixedBarLike = listOf("toolbar", "actionbar", "appbar", "bottomnavigation", "tablayout", "navigationbar")
            .any { keyword -> className.contains(keyword) || viewId.contains(keyword) }
        if (isFixedBarLike) return false

        return true
    }


    internal fun <T> isLastContentCandidateBeforeBottomBar(
        traversalList: List<T>,
        candidateIndex: Int,
        bottomBarIndex: Int,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?
    ): Boolean {
        if (candidateIndex !in traversalList.indices || bottomBarIndex !in traversalList.indices) return false
        if (candidateIndex >= bottomBarIndex) return false
        val lastContentIndex = ((candidateIndex + 1) until bottomBarIndex)
            .lastOrNull { index ->
                val node = traversalList[index]
                val bounds = boundsOf(node)
                !A11yNodeUtils.isTopAppBar(classNameOf(node), viewIdOf(node), bounds, screenTop, screenHeight) &&
                    !A11yNodeUtils.isBottomNavigationBar(classNameOf(node), viewIdOf(node), bounds, screenBottom, screenHeight)
            } ?: candidateIndex
        return candidateIndex >= lastContentIndex
    }


    internal fun <T> findIntermediateContentCandidateBeforeBottomBar(
        traversalList: List<T>,
        currentIndex: Int,
        bottomBarIndex: Int,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?
    ): Int {
        if (bottomBarIndex !in traversalList.indices) return -1
        val bottomBarTop = boundsOf(traversalList[bottomBarIndex]).top
        val start = (currentIndex + 1).coerceAtLeast(0)
        if (start >= bottomBarIndex) return -1

        val contentIndices = (start until bottomBarIndex).filter { index ->
            val node = traversalList[index]
            val bounds = boundsOf(node)
            !A11yNodeUtils.isTopAppBar(classNameOf(node), viewIdOf(node), bounds, screenTop, screenHeight) &&
                !A11yNodeUtils.isBottomNavigationBar(classNameOf(node), viewIdOf(node), bounds, screenBottom, screenHeight)
        }
        if (contentIndices.isEmpty()) return -1

        val thinTrailingIndex = contentIndices.lastOrNull { index ->
            val node = traversalList[index]
            val bounds = boundsOf(node)
            isThinTrailingContentAboveBottomBar(
                node = node,
                bounds = bounds,
                bottomBarTop = bottomBarTop,
                classNameOf = classNameOf,
                viewIdOf = viewIdOf
            ) && isLastContentCandidateBeforeBottomBar(
                traversalList = traversalList,
                candidateIndex = index,
                bottomBarIndex = bottomBarIndex,
                screenTop = screenTop,
                screenBottom = screenBottom,
                screenHeight = screenHeight,
                boundsOf = boundsOf,
                classNameOf = classNameOf,
                viewIdOf = viewIdOf
            )
        }
        return thinTrailingIndex ?: contentIndices.last()
    }



    internal fun isNearBottomEdge(bounds: Rect, effectiveBottom: Int, thresholdPx: Int = 180): Boolean {
        return bounds.bottom >= (effectiveBottom - thresholdPx)
    }



    internal fun <T> shouldScrollAtEndOfTraversal(
        currentIndex: Int,
        nextIndex: Int,
        traversalList: List<T>,
        scrollableNodeExists: Boolean
    ): Boolean {
        if (!scrollableNodeExists) return false
        val lastIndex = traversalList.lastIndex
        if (currentIndex !in traversalList.indices) return false
        if (currentIndex >= lastIndex) return false
        if (nextIndex !in traversalList.indices) return false
        if (nextIndex <= currentIndex) return false
        return false
    }


    internal fun <T> shouldTerminateAtLastBottomBar(
        traversalList: List<T>,
        currentIndex: Int,
        lastIndex: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?
    ): Boolean {
        if (currentIndex != lastIndex || currentIndex !in traversalList.indices) return false
        val node = traversalList[currentIndex]
        val bounds = boundsOf(node)
        return A11yNodeUtils.isBottomNavigationBar(
            className = classNameOf(node),
            viewIdResourceName = viewIdOf(node),
            boundsInScreen = bounds,
            screenBottom = screenBottom,
            screenHeight = screenHeight
        )
    }



    internal fun <T> shouldScrollBeforeBottomBar(
        traversalList: List<T>,
        currentIndex: Int,
        nextIndex: Int,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        effectiveBottom: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        canScrollForwardHint: Boolean,
        nearBottomThresholdPx: Int = 180
    ): Boolean {
        if (!canScrollForwardHint) return false
        if (currentIndex !in traversalList.indices || nextIndex !in traversalList.indices) return false
        if (nextIndex <= currentIndex) return false

        val currentNode = traversalList[currentIndex]
        val currentBounds = boundsOf(currentNode)
        if (isTopLoopProneControlNode(currentNode, currentBounds, screenTop, screenHeight, classNameOf, viewIdOf)) {
            return false
        }

        val contentIndicesBeforeBottomBar = (0 until nextIndex).filter { index ->
            val candidate = traversalList[index]
            val bounds = boundsOf(candidate)
            !A11yNodeUtils.isTopAppBar(classNameOf(candidate), viewIdOf(candidate), bounds, screenTop, screenHeight) &&
                !A11yNodeUtils.isBottomNavigationBar(classNameOf(candidate), viewIdOf(candidate), bounds, screenBottom, screenHeight)
        }
        if (contentIndicesBeforeBottomBar.isEmpty()) return false

        val remainingContentCount = contentIndicesBeforeBottomBar.count { it > currentIndex }
        if (remainingContentCount <= 0) return false

        val isCurrentNearEffectiveBottom = currentBounds.bottom >= (effectiveBottom - nearBottomThresholdPx)
        val continuationLikelyBelowCurrentNode = isContinuationContentLikelyBelowCurrentNode(
            traversalList = traversalList,
            currentIndex = currentIndex,
            nextIndex = nextIndex,
            screenTop = screenTop,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            effectiveBottom = effectiveBottom,
            boundsOf = boundsOf,
            classNameOf = classNameOf,
            viewIdOf = viewIdOf
        )
        if (remainingContentCount <= 1 && isCurrentNearEffectiveBottom && !continuationLikelyBelowCurrentNode) {
            return false
        }

        return true
    }


    internal fun shouldForcePreScrollBeforeBottomBar(
        shouldScrollBeforeBottomBar: Boolean,
        continuationContentLikelyBelowCurrentGrid: Boolean
    ): Boolean {
        return shouldScrollBeforeBottomBar || continuationContentLikelyBelowCurrentGrid
    }


    internal fun <T> hasContinuationPatternBelowCurrentNode(
        traversalList: List<T>,
        currentIndex: Int,
        nextIndex: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?
    ): Boolean {
        if (currentIndex !in traversalList.indices || nextIndex !in traversalList.indices) return false
        if (nextIndex <= currentIndex) return false

        val currentNode = traversalList[currentIndex]
        val currentBounds = boundsOf(currentNode)
        val currentClass = classNameOf(currentNode)?.lowercase().orEmpty()
        val currentViewId = viewIdOf(currentNode)?.lowercase().orEmpty()
        val hasGridKeyword = listOf("grid", "tile", "card", "shortcut", "menu", "row", "lab")
            .any { keyword -> currentClass.contains(keyword) || currentViewId.contains(keyword) }
        if (hasGridKeyword) return true

        return (0 until currentIndex).any { index ->
            val bounds = boundsOf(traversalList[index])
            val similarTop = kotlin.math.abs(bounds.top - currentBounds.top) <= 20
            val similarHeight = kotlin.math.abs(bounds.height() - currentBounds.height()) <= 32
            similarTop || similarHeight
        }
    }


    internal fun <T> hasContinuationContentBeforeBottomBar(
        traversalList: List<T>,
        currentIndex: Int,
        bottomBarIndex: Int,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        trailingBandPx: Int = 80
    ): Boolean {
        if (currentIndex !in traversalList.indices || bottomBarIndex !in traversalList.indices) return false
        if (bottomBarIndex <= currentIndex) return false
        val bottomBarTop = boundsOf(traversalList[bottomBarIndex]).top

        return ((currentIndex + 1) until bottomBarIndex).any { index ->
            val node = traversalList[index]
            val bounds = boundsOf(node)
            !A11yNodeUtils.isTopAppBar(classNameOf(node), viewIdOf(node), bounds, screenTop, screenHeight) &&
                !A11yNodeUtils.isBottomNavigationBar(classNameOf(node), viewIdOf(node), bounds, screenBottom, screenHeight) &&
                (bounds.bottom <= bottomBarTop && (bottomBarTop - bounds.bottom) in 0..trailingBandPx)
        }
    }


    internal fun <T> findLastContentCandidateIndexBeforeBottomBar(
        traversalList: List<T>,
        bottomBarIndex: Int,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        isFixedUiOf: ((T) -> Boolean)? = null
    ): Int {
        if (bottomBarIndex !in traversalList.indices) return -1
        if (bottomBarIndex <= 0) return -1
        for (index in bottomBarIndex - 1 downTo 0) {
            val node = traversalList[index]
            val bounds = boundsOf(node)
            if (isNodePhysicallyOffScreen(bounds, screenTop, screenBottom)) continue
            if (A11yNodeUtils.isTopAppBar(classNameOf(node), viewIdOf(node), bounds, screenTop, screenHeight)) continue
            if (A11yNodeUtils.isBottomNavigationBar(classNameOf(node), viewIdOf(node), bounds, screenBottom, screenHeight)) continue
            if (isFixedUiOf?.invoke(node) == true) continue

            val isWrapperOrContainer =
                isContainerLikeClassName(classNameOf(node)) ||
                    isContainerLikeViewId(viewIdOf(node))
            if (isWrapperOrContainer) continue
            return index
        }
        return -1
    }


    internal fun <T> isContentTraversalCompleteBeforeBottomBar(
        traversalList: List<T>,
        currentIndex: Int,
        bottomBarIndex: Int,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        effectiveBottom: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        isFixedUiOf: ((T) -> Boolean)? = null,
        canScrollForwardHint: Boolean = false,
        continuationNearBottomThresholdPx: Int = 160,
        trailingThinContentHeightPx: Int = 120
    ): Boolean {
        if (currentIndex !in traversalList.indices || bottomBarIndex !in traversalList.indices) return false
        if (bottomBarIndex <= currentIndex) return false
        val lastContentIndex = findLastContentCandidateIndexBeforeBottomBar(
            traversalList = traversalList,
            bottomBarIndex = bottomBarIndex,
            screenTop = screenTop,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            boundsOf = boundsOf,
            classNameOf = classNameOf,
            viewIdOf = viewIdOf,
            isFixedUiOf = isFixedUiOf
        )
        if (currentIndex != lastContentIndex) return false
        if (!canScrollForwardHint) return true

        val currentNode = traversalList[currentIndex]
        val currentBounds = boundsOf(currentNode)
        val normalizedClass = classNameOf(currentNode)?.lowercase().orEmpty()
        val normalizedViewId = viewIdOf(currentNode)?.lowercase().orEmpty()
        val continuationKeywordDetected = listOf("grid", "shortcut", "menu", "tile", "icon", "card", "assistant", "lab")
            .any { keyword -> normalizedClass.contains(keyword) || normalizedViewId.contains(keyword) }
        val nearBottomEdge = currentBounds.bottom >= (effectiveBottom - continuationNearBottomThresholdPx)
        val isBottomClipped = currentBounds.bottom > effectiveBottom
        val isTrailingThinContent = currentBounds.height() <= trailingThinContentHeightPx && nearBottomEdge

        return !(isBottomClipped || isTrailingThinContent || (nearBottomEdge && continuationKeywordDetected))
    }


    internal fun <T> isContinuationContentLikelyBelowCurrentNode(
        traversalList: List<T>,
        currentIndex: Int,
        nextIndex: Int,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        effectiveBottom: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        nearBottomThresholdPx: Int = 240
    ): Boolean {
        if (currentIndex !in traversalList.indices || nextIndex !in traversalList.indices) return false
        if (nextIndex <= currentIndex) return false
        if (nextIndex - currentIndex != 1) return false

        val currentNode = traversalList[currentIndex]
        val currentBounds = boundsOf(currentNode)
        val currentIsBottomEdgeContent = currentBounds.bottom >= (effectiveBottom - nearBottomThresholdPx)
        if (!currentIsBottomEdgeContent) return false

        val currentClass = classNameOf(currentNode)?.lowercase().orEmpty()
        val currentViewId = viewIdOf(currentNode)?.lowercase().orEmpty()
        val gridOrShortcutKeywords = listOf("grid", "shortcut", "menu", "tile", "icon", "assistant", "lab")
        val currentLooksLikeGridOrShortcut = gridOrShortcutKeywords.any { keyword ->
            currentClass.contains(keyword) || currentViewId.contains(keyword)
        } || !A11yNodeUtils.isTopAppBar(currentClass, currentViewId, currentBounds, screenTop, screenHeight)

        if (!currentLooksLikeGridOrShortcut) return false

        val nextNode = traversalList[nextIndex]
        val nextBounds = boundsOf(nextNode)
        val nextIsBottomBar = A11yNodeUtils.isBottomNavigationBar(
            className = classNameOf(nextNode),
            viewIdResourceName = viewIdOf(nextNode),
            boundsInScreen = nextBounds,
            screenBottom = screenBottom,
            screenHeight = screenHeight
        )
        if (!nextIsBottomBar) return false

        return true
    }


    internal fun <T> isTopLoopProneControlNode(
        node: T,
        bounds: Rect,
        screenTop: Int,
        screenHeight: Int,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?
    ): Boolean {
        if (!isWithinTopContentArea(bounds.top, screenTop, screenHeight)) return false

        val normalizedClass = classNameOf(node)?.lowercase().orEmpty()
        val normalizedViewId = viewIdOf(node)?.lowercase().orEmpty()
        val controlKeywords = listOf("chip", "filter", "category", "segment", "segmented", "tab", "sort")

        return controlKeywords.any { keyword ->
            normalizedClass.contains(keyword) || normalizedViewId.contains(keyword)
        }
    }

}
