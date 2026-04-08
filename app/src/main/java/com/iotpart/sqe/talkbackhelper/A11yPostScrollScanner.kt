package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo

object A11yPostScrollScanner {
    const val VERSION: String = "1.3.3"
    private const val ONECONNECT_PACKAGE_NAME = "com.samsung.android.oneconnect"
    private const val ONECONNECT_UPDATE_APP_CARD_VIEW_ID = "com.samsung.android.oneconnect:id/update_app_card"
    private const val ONECONNECT_NOTIFICATIONS_TITLE_VIEW_ID = "com.samsung.android.oneconnect:id/noti_title"
    private const val ONECONNECT_NOTIFICATIONS_SWITCH_VIEW_ID = "com.samsung.android.oneconnect:id/notification_item_switch"

    internal fun findAndFocusFirstContent(
        context: FindAndFocusPhaseContext,
        request: FindAndFocusRequest
    ): TargetActionOutcome {
        val localMainScrollContainer = A11yNodeUtils.findBestScrollableContainer(context.root)
        val postScrollContext = buildPostScrollSearchContext(context, request, localMainScrollContainer)
        val loopState = FocusLoopState()
        val scanEndExclusive = if (request.singleTargetOnly) {
            (postScrollContext.anchorStartIndex + 1).coerceAtMost(context.traversalList.size)
        } else {
            context.traversalList.size
        }
        val scanMode = if (request.singleTargetOnly) "regular_single_target" else if (request.isScrollAction) "post_scroll_scan" else "regular_scan"
        Log.i(
            "A11Y_HELPER",
            "[SMART_NEXT] scan_mode=$scanMode start=${postScrollContext.anchorStartIndex} endExclusive=$scanEndExclusive"
        )
        if (request.singleTargetOnly) {
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT][SINGLE_TARGET] pre_scan candidateCount=${(scanEndExclusive - postScrollContext.anchorStartIndex).coerceAtLeast(0)} excludedIndex=${postScrollContext.excludedIndex} requestedStart=${request.startIndex}"
            )
        }

        for (index in postScrollContext.anchorStartIndex until scanEndExclusive) {
            val outcome = tryFocusCandidate(
                context = context,
                request = request,
                postScrollContext = postScrollContext,
                localMainScrollContainer = localMainScrollContainer,
                loopState = loopState,
                index = index
            )
            if (outcome != null) {
                return outcome
            }
        }

        if (loopState.focusedAny) {
            return loopState.focusedOutcome ?: TargetActionOutcome(false, "failed")
        }
        if (request.singleTargetOnly) {
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT] single-target mode consumed intended index without success -> stop reason=single_target_exhausted focusedAny=${loopState.focusedAny} focusAttempted=${loopState.focusAttempted}"
            )
            Log.w(
                "A11Y_HELPER",
                "[SMART_NEXT_DEBUG][fail] req_id='${A11yHistoryManager.activeSmartNextReqId}' detail='failed_single_target' branch='findAndFocusFirstContent.single_target_exhausted' start_index=${postScrollContext.anchorStartIndex} end_exclusive=$scanEndExclusive excluded_index=${postScrollContext.excludedIndex} focus_attempted=${loopState.focusAttempted} focused_any=${loopState.focusedAny}"
            )
            return TargetActionOutcome(false, "failed_single_target")
        }

        val noCandidateOutcome = handleNoCandidateAfterScroll(request, postScrollContext, loopState)
        if (noCandidateOutcome != null) {
            return noCandidateOutcome
        }
        return handleLoopFallback(context, request, loopState)
    }

    internal fun buildPostScrollSearchContext(
        context: FindAndFocusPhaseContext,
        request: FindAndFocusRequest,
        localMainScrollContainer: AccessibilityNodeInfo?
    ): PostScrollSearchContext {
        val traversalList = context.traversalList
        val excludedIndex = findIndexByDescription(
            nodes = traversalList,
            descriptionOf = {
                it.contentDescription?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                    ?: it.text?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
            },
            excludeDesc = request.excludeDesc
        )
        val traversalStartIndex = if (request.isScrollAction) {
            request.startIndex.coerceAtLeast(0)
        } else {
            if (excludedIndex != -1) excludedIndex + 1 else request.startIndex.coerceAtLeast(0)
        }
        val resolvedAnchorIndex = if (request.isScrollAction && request.preScrollAnchor != null) {
            A11yTraversalAnalyzer.resolveAnchorIndexInRefreshedTraversal(
                traversalList = traversalList,
                anchor = request.preScrollAnchor,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                viewIdOf = { node -> node.viewIdResourceName },
                textOf = { node -> node.text?.toString() },
                contentDescriptionOf = { node -> node.contentDescription?.toString() }
            )
        } else {
            -1
        }
        val continuationFallbackAttempted = request.isScrollAction && request.preScrollAnchor != null && resolvedAnchorIndex == -1
        var continuationFallbackFailed = false
        var hasValidPostScrollCandidate = false
        val fallbackBelowAnchorIndex = if (continuationFallbackAttempted) {
            val preScrollAnchor = request.preScrollAnchor
            if (preScrollAnchor == null) {
                continuationFallbackFailed = true
                -1
            } else {
                val promotedRawOnlyViewIds = A11ySnapshotTracker.collectRawVisibleNodes(context.root)
                    .mapNotNull { raw -> raw.viewId?.substringAfterLast('/')?.trim() }
                    .filter { shortId -> A11yTraversalAnalyzer.isSettingsRowViewId(shortId) }
                    .toSet()
                val continuationSearchResult = A11yTraversalAnalyzer.selectPostScrollCandidate(
                    traversalList = traversalList,
                    startIndex = 0,
                    visibleHistory = request.visibleHistory,
                    visibleHistorySignatures = request.visibleHistorySignatures,
                    visitedHistory = context.visitedHistory,
                    visitedHistorySignatures = context.visitedHistorySignatures,
                    screenTop = context.screenTop,
                    screenBottom = context.screenBottom,
                    screenHeight = context.screenHeight,
                    boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                    classNameOf = { node -> node.className?.toString() },
                    viewIdOf = { node -> node.viewIdResourceName },
                    isContentNodeOf = { node ->
                        A11yNodeUtils.isContentNode(
                            node = node,
                            bounds = Rect().also { node.getBoundsInScreen(it) },
                            screenTop = context.screenTop,
                            screenBottom = context.screenBottom,
                            screenHeight = context.screenHeight,
                            mainScrollContainer = localMainScrollContainer
                        )
                    },
                    clickableOf = { node -> node.isClickable },
                    focusableOf = { node -> node.isFocusable },
                    descendantLabelOf = { node -> A11yTraversalAnalyzer.recoverDescendantLabel(node) },
                    promotedViewIds = promotedRawOnlyViewIds,
                    preScrollAnchor = preScrollAnchor,
                    preScrollAnchorBottom = preScrollAnchor.bounds.bottom,
                    labelOf = { node ->
                        node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    },
                    isTopAppBarNode = { className, viewId, bounds, top, height ->
                        A11yNodeUtils.isTopAppBar(className, viewId, bounds, top, height)
                    },
                    isBottomNavigationBarNode = { className, viewId, bounds, bottom, height ->
                        A11yNodeUtils.isBottomNavigationBar(className, viewId, bounds, bottom, height)
                    },
                    isInVisibleHistory = { label, viewId, bounds, visibleHistory, visibleHistorySignatures ->
                        A11ySnapshotTracker.isInVisibleHistory(label, viewId, bounds, visibleHistory, visibleHistorySignatures)
                    },
                    isInVisitedHistory = { label, viewId, bounds, visitedHistory, visitedHistorySignatures ->
                        A11ySnapshotTracker.isInVisitedHistory(label, viewId, bounds, visitedHistory, visitedHistorySignatures)
                    },
                    logVisitedHistorySkip = { reason, label, viewId, bounds ->
                        A11yHistoryManager.logVisitedHistorySkip(reason, label, viewId, bounds)
                    },
                    isHeaderLikeCandidate = { className, viewId, label, bounds, top, height ->
                        A11yNodeUtils.isHeaderLikeCandidate(className, viewId, label, bounds, top, height)
                    },
                    hasPreScrollResolvedLabel = { currentLabel, currentDescendantLabel, rawViewId, bounds, visibleHistorySignatures ->
                        A11ySnapshotTracker.hasPreScrollResolvedLabel(currentLabel, currentDescendantLabel, rawViewId, bounds, visibleHistorySignatures)
                    }
                )
                val candidate = continuationSearchResult.index
                val analysis = A11yTraversalAnalyzer.analyzePostScrollState(
                    treeChanged = true,
                    anchorMaintained = true,
                    newlyExposedCandidateExists = candidate >= 0
                )
                val selection = A11yTraversalAnalyzer.selectPostScrollContinuationCandidate(candidate, analysis)
                continuationFallbackFailed = !selection.accepted
                hasValidPostScrollCandidate = continuationSearchResult.hasValidPostScrollCandidate
                if (!selection.accepted) -1 else candidate
            }.also {
                if (continuationFallbackAttempted) {
                    Log.i(
                        "A11Y_HELPER",
                        "[SMART_NEXT] skipGeneral decision reason=${
                            when {
                                !continuationFallbackFailed -> "continuation_candidate_found"
                                hasValidPostScrollCandidate -> "fallback_rejected_but_valid_candidate_existed"
                                else -> "continuation_fallback_failed_no_valid_candidate"
                            }
                        }"
                    )
                }
            }
        } else {
            -1
        }
        val continuationFallbackHardFailed = continuationFallbackFailed && !hasValidPostScrollCandidate
        val postScrollDecision = A11yNavigationPolicy.decidePostScrollContinuation(
            resolvedAnchorIndex = resolvedAnchorIndex,
            fallbackBelowAnchorIndex = fallbackBelowAnchorIndex,
            traversalStartIndex = traversalStartIndex,
            traversalSize = traversalList.size,
            continuationFallbackFailed = continuationFallbackHardFailed
        )
        val anchorStartIndex = postScrollDecision.targetIndex ?: traversalList.size
        val skipGeneralScan = continuationFallbackAttempted && continuationFallbackHardFailed
        Log.i("A11Y_HELPER", "[DECIDE] post_scroll_start=$anchorStartIndex skipGeneral=$skipGeneralScan fallbackAttempted=$continuationFallbackAttempted")
        return PostScrollSearchContext(
            excludedIndex = excludedIndex,
            traversalStartIndex = traversalStartIndex,
            resolvedAnchorIndex = resolvedAnchorIndex,
            continuationFallbackAttempted = continuationFallbackAttempted,
            continuationFallbackFailed = continuationFallbackFailed,
            fallbackBelowAnchorIndex = fallbackBelowAnchorIndex,
            anchorStartIndex = anchorStartIndex,
            skipGeneralScan = skipGeneralScan
        )
    }

    internal fun tryFocusCandidate(
        context: FindAndFocusPhaseContext,
        request: FindAndFocusRequest,
        postScrollContext: PostScrollSearchContext,
        localMainScrollContainer: AccessibilityNodeInfo?,
        loopState: FocusLoopState,
        index: Int
    ): TargetActionOutcome? {
        val traversalList = context.traversalList
        val node = traversalList[index]
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        var label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: "<no-label>"
        if (request.isScrollAction && request.preScrollAnchor != null && postScrollContext.resolvedAnchorIndex >= 0 && index <= postScrollContext.resolvedAnchorIndex) {
            Log.i("A11Y_HELPER", "[SMART_NEXT_DEBUG][candidate_skip] req_id='${A11yHistoryManager.activeSmartNextReqId}' index=$index reason='anchor_guard'")
            if (request.singleTargetOnly) {
                Log.i("A11Y_HELPER", "[SMART_NEXT][SINGLE_TARGET] skip index=$index reason=anchor_guard")
            }
            return null
        }
        val requestedFloorIndex = A11yStateStore.lastRequestedFocusIndex
        if (!request.isScrollAction && requestedFloorIndex >= 0 && index <= requestedFloorIndex) {
            Log.i("A11Y_HELPER", "[SMART_NEXT_DEBUG][candidate_skip] req_id='${A11yHistoryManager.activeSmartNextReqId}' index=$index reason='requested_floor_guard' floor=$requestedFloorIndex")
            if (request.singleTargetOnly) {
                Log.i("A11Y_HELPER", "[SMART_NEXT][SINGLE_TARGET] skip index=$index reason=requested_floor_guard floor=$requestedFloorIndex")
            }
            return null
        }
        if (A11yNodeUtils.isNodePhysicallyOffScreen(bounds, context.screenTop, context.screenBottom)) {
            Log.i("A11Y_HELPER", "[SMART_NEXT_DEBUG][candidate_skip] req_id='${A11yHistoryManager.activeSmartNextReqId}' index=$index reason='off_screen' bounds='${formatBounds(bounds)}'")
            if (request.singleTargetOnly) {
                Log.i("A11Y_HELPER", "[SMART_NEXT][SINGLE_TARGET] skip index=$index reason=off_screen")
            }
            return null
        }
        val isTopBar = A11yNodeUtils.isTopAppBar(node.className?.toString(), node.viewIdResourceName, bounds, context.screenTop, context.screenHeight)
        val isBottomBar = A11yNodeUtils.isBottomNavigationBar(node.className?.toString(), node.viewIdResourceName, bounds, context.screenBottom, context.screenHeight)
        val shouldSkipTopBar = isTopBar && request.isScrollAction
        val isFixedUi = A11yNodeUtils.isFixedSystemUI(node, localMainScrollContainer)
        val inVisitedHistory = A11ySnapshotTracker.isInVisitedHistory(
            label = label,
            viewId = node.viewIdResourceName,
            bounds = bounds,
            visitedHistory = context.visitedHistory,
            visitedHistorySignatures = context.visitedHistorySignatures
        )
        val shouldSkipHistory = shouldSkipHistoryNodeAfterScroll(
            isScrollAction = request.isScrollAction,
            inHistory = inVisitedHistory,
            isFixedUi = isFixedUi || isTopBar || isBottomBar,
            isInsideMainScrollContainer = localMainScrollContainer?.let { container -> node == container || A11yNodeUtils.isDescendantOf(container, node) { it.parent } } ?: false,
            isTopArea = A11yNodeUtils.isWithinTopContentArea(bounds.top, context.screenTop, context.screenHeight)
        )
        if (shouldSkipHistory || (request.isScrollAction && inVisitedHistory)) {
            Log.i("A11Y_HELPER", "[SMART_NEXT_DEBUG][candidate_skip] req_id='${A11yHistoryManager.activeSmartNextReqId}' index=$index reason='history_guard' in_visited=$inVisitedHistory is_fixed_ui=$isFixedUi is_top_bar=$isTopBar is_bottom_bar=$isBottomBar")
            if (request.singleTargetOnly) {
                Log.i("A11Y_HELPER", "[SMART_NEXT][SINGLE_TARGET] skip index=$index reason=history_guard inVisited=$inVisitedHistory")
            }
            return null
        }
        if (postScrollContext.excludedIndex == -1 && !loopState.skippedExcludedNode && shouldSkipExcludedNodeByDescription(
                nodeDesc = node.contentDescription?.toString(),
                excludeDesc = request.excludeDesc,
                nodeBounds = bounds,
                screenTop = context.screenTop,
                screenHeight = context.screenHeight
            )) {
            loopState.skippedExcludedNode = true
            Log.i("A11Y_HELPER", "[SMART_NEXT_DEBUG][candidate_skip] req_id='${A11yHistoryManager.activeSmartNextReqId}' index=$index reason='exclude_desc_guard'")
            if (request.singleTargetOnly) {
                Log.i("A11Y_HELPER", "[SMART_NEXT][SINGLE_TARGET] skip index=$index reason=exclude_desc_guard")
            }
            return null
        }
        if (!shouldSkipTopBar && !isBottomBar) {
            if (label == "<no-label>") {
                label = A11yTraversalAnalyzer.recoverDescendantLabel(node) ?: label
            }
            loopState.focusAttempted = true
            val debugEnabled = shouldEmitOneConnectSettingsRegularDebug(node, label)
            if (debugEnabled && request.singleTargetOnly) {
                Log.d("A11Y_HELPER", "[DEBUG][REGULAR] enter")
                Log.d(
                    "A11Y_HELPER",
                    "[DEBUG][REGULAR] intended_target=idx=$index id=${node.viewIdResourceName} bounds=${formatBounds(bounds)} label=${label.replace("\n", " ")}"
                )
            }
            val outcome = A11yFocusExecutor.requestFocusFlow(
                root = context.root,
                target = node,
                screenTop = context.screenTop,
                effectiveBottom = context.effectiveBottom,
                status = request.statusName,
                isScrollAction = request.isScrollAction,
                traversalIndex = index,
                traversalListSnapshot = traversalList,
                currentFocusIndexHint = index - 1,
                aliasMembersByTraversalIndex = context.aliasMembersByRepresentativeIndex
            )
            val mappedOutcome = TargetActionOutcome(outcome.success, outcome.status, outcome.targetNode)
            if (debugEnabled && request.singleTargetOnly) {
                Log.d("A11Y_HELPER", "[DEBUG][REGULAR] action_result=${mappedOutcome.success}")
            }
            if (mappedOutcome.success) {
                loopState.focusedAny = true
                loopState.focusedOutcome = mappedOutcome
                return mappedOutcome
            }
            if (debugEnabled && request.singleTargetOnly) {
                val focusedNode = context.root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
                val focusedBounds = focusedNode?.let { Rect().also(it::getBoundsInScreen) }
                Log.d(
                    "A11Y_HELPER",
                    "[DEBUG][REGULAR] after_failure_focus=${summarizeNode(focusedNode, focusedBounds)}"
                )
                Log.d("A11Y_HELPER", "[DEBUG][REGULAR] no_fallback_single_target=true")
            }
        }
        return null
    }

    private fun shouldEmitOneConnectSettingsRegularDebug(node: AccessibilityNodeInfo, resolvedLabel: String): Boolean {
        if (node.packageName?.toString()?.trim() == ONECONNECT_PACKAGE_NAME) return true
        val viewId = node.viewIdResourceName
        if (viewId == ONECONNECT_UPDATE_APP_CARD_VIEW_ID ||
            viewId == ONECONNECT_NOTIFICATIONS_TITLE_VIEW_ID ||
            viewId == ONECONNECT_NOTIFICATIONS_SWITCH_VIEW_ID
        ) return true
        val label = resolvedLabel.lowercase()
        return label.contains("update app") || label.contains("samsung account") || label.contains("notifications")
    }

    private fun summarizeNode(node: AccessibilityNodeInfo?, bounds: Rect?): String {
        if (node == null) return "null"
        val label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: A11yTraversalAnalyzer.recoverDescendantLabel(node)
            ?: "<no-label>"
        return "id=${node.viewIdResourceName} bounds=${formatBounds(bounds)} label=${label.replace("\n", " ")}"
    }

    private fun formatBounds(bounds: Rect?): String {
        if (bounds == null) return "null"
        return "[${bounds.left},${bounds.top}][${bounds.right},${bounds.bottom}]"
    }

    internal fun handleNoCandidateAfterScroll(
        request: FindAndFocusRequest,
        postScrollContext: PostScrollSearchContext,
        loopState: FocusLoopState
    ): TargetActionOutcome? {
        if (!request.isScrollAction || loopState.focusAttempted) return null
        if (postScrollContext.fallbackBelowAnchorIndex >= 0) {
            return TargetActionOutcome(false, "continuation_candidate_unresolved")
        }
        return TargetActionOutcome(false, "reached_end")
    }

    internal fun handleLoopFallback(
        context: FindAndFocusPhaseContext,
        request: FindAndFocusRequest,
        loopState: FocusLoopState
    ): TargetActionOutcome {
        val fallbackDecision = decideFallbackStrategy(
            focusedAny = loopState.focusedAny,
            isScrollAction = request.isScrollAction,
            allowLooping = request.allowLooping,
            excludeDesc = request.excludeDesc
        )
        return when (fallbackDecision.type) {
            SelectionType.FALLBACK -> findAndFocusFirstContent(
                context = context,
                request = FindAndFocusRequest(
                    statusName = "looped",
                    isScrollAction = false,
                    singleTargetOnly = false,
                    excludeDesc = null,
                    startIndex = 0,
                    visibleHistory = emptySet(),
                    visibleHistorySignatures = emptySet(),
                    allowLooping = true,
                    preScrollAnchor = null
                )
            )
            SelectionType.END -> {
                if (fallbackDecision.reason == "loop_blocked_allowLooping_false") {
                    TargetActionOutcome(false, "failed_no_new_content")
                } else {
                    TargetActionOutcome(false, "failed")
                }
            }
            else -> TargetActionOutcome(false, "failed")
        }
    }

    internal fun decideFallbackStrategy(
        focusedAny: Boolean,
        isScrollAction: Boolean,
        allowLooping: Boolean,
        excludeDesc: String?
    ): SelectionDecisionModel {
        if (focusedAny) {
            return SelectionDecisionModel(SelectionType.REGULAR, reason = "focus_already_succeeded")
        }
        if (shouldTriggerLoopFallback(focusedAny, isScrollAction, excludeDesc)) {
            return if (allowLooping) {
                SelectionDecisionModel(SelectionType.FALLBACK, targetIndex = 0, reason = "loop_to_first_content")
            } else {
                SelectionDecisionModel(SelectionType.END, reason = "loop_blocked_allowLooping_false")
            }
        }
        return SelectionDecisionModel(SelectionType.END, reason = "no_fallback_needed")
    }

    internal fun shouldTriggerLoopFallback(
        focusedAny: Boolean,
        isScrollAction: Boolean,
        excludeDesc: String?
    ): Boolean {
        return !focusedAny && isScrollAction && !excludeDesc.isNullOrBlank()
    }

    internal fun shouldSkipHistoryNodeAfterScroll(
        isScrollAction: Boolean,
        inHistory: Boolean,
        isFixedUi: Boolean,
        isInsideMainScrollContainer: Boolean,
        isTopArea: Boolean
    ): Boolean {
        if (!isScrollAction || !inHistory) return false
        if (isFixedUi) return true
        if (!isInsideMainScrollContainer) return true
        if (isTopArea) return true
        return true
    }

    internal fun shouldSkipExcludedNodeByDescription(
        nodeDesc: String?,
        excludeDesc: String?,
        nodeBounds: Rect,
        screenTop: Int,
        screenHeight: Int
    ): Boolean {
        val normalizedNodeDesc = nodeDesc?.trim().orEmpty()
        val normalizedExcludeDesc = excludeDesc?.trim().orEmpty()
        if (normalizedNodeDesc.isEmpty() || normalizedExcludeDesc.isEmpty()) return false
        if (normalizedNodeDesc != normalizedExcludeDesc) return false

        val topThirtyPercentBoundary = screenTop + (screenHeight * 0.3f).toInt()
        return nodeBounds.top <= topThirtyPercentBoundary
    }

    internal fun <T> findIndexByDescription(
        nodes: List<T>,
        descriptionOf: (T) -> String?,
        excludeDesc: String?
    ): Int {
        val normalizedExcludeDesc = excludeDesc?.trim().orEmpty()
        if (normalizedExcludeDesc.isEmpty()) return -1

        return nodes.indexOfFirst { node ->
            descriptionOf(node)?.trim() == normalizedExcludeDesc
        }
    }
}
