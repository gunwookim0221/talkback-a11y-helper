package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import kotlin.math.abs

object A11yTraversalAnalyzer {
    const val VERSION: String = "1.4.5"
    private const val ONECONNECT_PACKAGE_NAME = "com.samsung.android.oneconnect"

    data class CandidateSelectionResult(
        val index: Int,
        val accepted: Boolean,
        val reasonCode: String
    )

    internal data class FocusedNode(
        val node: AccessibilityNodeInfo,
        val text: String?,
        val contentDescription: String?,
        val mergedLabel: String?
    )

    internal fun buildTalkBackLikeFocusNodes(root: AccessibilityNodeInfo): List<FocusedNode> {
        val focusNodes = mutableListOf<FocusedNode>()
        collectFocusableNodes(node = root, containerAncestor = null, sink = focusNodes)

        val filteredNodes = focusNodes
            .filterNot { shouldExcludeAsEmptyShell(it) }
            .sortedWith(spatialComparator())
        return filteredNodes
    }

    internal fun collectFocusableNodes(
        node: AccessibilityNodeInfo,
        containerAncestor: AccessibilityNodeInfo?,
        sink: MutableList<FocusedNode>
    ) {
        if (!node.isVisibleToUser) return

        val container = isFocusContainer(node)
        if (container) {
            val mergedContent = collectMergedTextFromContainer(node)
            val mergedText = mergedContent.firstOrNull()
            val mergedDescription = mergedContent.getOrNull(1)
            sink += FocusedNode(node, mergedText, mergedDescription, mergedText)
        } else if (containerAncestor == null && hasAnyText(node)) {
            sink += FocusedNode(
                node = node,
                text = node.text?.toString(),
                contentDescription = node.contentDescription?.toString(),
                mergedLabel = null
            )
        }

        // RecyclerView 등 구조적 컨테이너는 텍스트 병합 주체로 동작하지 않도록 투명 처리한다.
        val className = node.className?.toString() ?: ""
        val viewId = node.viewIdResourceName ?: ""
        val isStructural = isContainerLikeClassName(className) ||
            isContainerLikeViewId(viewId) ||
            className.contains("GridView", ignoreCase = true) ||
            className.contains("RecyclerView", ignoreCase = true) ||
            viewId.contains("recycler_view", ignoreCase = true)
        val nextContainer = if (container && !isStructural) node else containerAncestor
        for (i in 0 until node.childCount) {
            node.getChild(i)?.let { child ->
                collectFocusableNodes(node = child, containerAncestor = nextContainer, sink = sink)
            }
        }
    }

    internal fun collectMergedTextFromContainer(container: AccessibilityNodeInfo): List<String> {
        val merged = mutableListOf<String>()
        collectDescendantReadableText(
            node = container,
            includeCurrentNode = true,
            sink = merged
        )

        if (merged.isEmpty()) return emptyList()
        val mergedText = merged.joinToString(separator = " ")
        return listOf(mergedText, mergedText)
    }

    internal fun collectDescendantReadableText(
        node: AccessibilityNodeInfo,
        includeCurrentNode: Boolean,
        sink: MutableList<String>
    ) {
        if (!node.isVisibleToUser) return

        if (includeCurrentNode) {
            node.text?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let(sink::add)
            node.contentDescription?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let(sink::add)
        }

        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            if (!child.isVisibleToUser) continue

            if (isFocusContainer(child)) {
                child.text?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let(sink::add)
                child.contentDescription?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let(sink::add)
                continue
            }

            collectDescendantReadableText(
                node = child,
                includeCurrentNode = true,
                sink = sink
            )
        }
    }

    internal fun isFocusContainer(node: AccessibilityNodeInfo): Boolean {
        val screenReaderFocusable = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && node.isScreenReaderFocusable
        return node.isClickable || node.isFocusable || screenReaderFocusable || isSettingsRowViewId(node.viewIdResourceName)
    }

    internal fun isSettingsRowViewId(viewIdResourceName: String?): Boolean {
        val normalized = viewIdResourceName?.substringAfterLast('/')?.trim().orEmpty()
        if (normalized.isEmpty()) return false
        return SETTINGS_ROW_VIEW_IDS.contains(normalized)
    }

    internal val SETTINGS_ROW_VIEW_ID_ORDERED = listOf(
        "item_history",
        "item_notification",
        "item_customer_service",
        "item_repair_history",
        "item_how_to_use",
        "item_notices",
        "item_contact_us",
        "item_offline_diag",
        "item_knox_matrix",
        "item_privacy_notice"
    )
    internal val SETTINGS_ROW_VIEW_IDS = SETTINGS_ROW_VIEW_ID_ORDERED.toSet()

    internal fun hasAnyText(node: AccessibilityNodeInfo): Boolean {
        val text = node.text?.toString()?.trim().orEmpty()
        val description = node.contentDescription?.toString()?.trim().orEmpty()
        return text.isNotEmpty() || description.isNotEmpty()
    }

    internal fun shouldExcludeAsEmptyShell(node: FocusedNode): Boolean {
        val current = node.node
        if (isSettingsRowViewId(current.viewIdResourceName) && current.isVisibleToUser && (current.isClickable || current.isFocusable)) {
            return false
        }

        if (current.text.isNullOrBlank() && current.contentDescription.isNullOrBlank()) {
            val interactiveDescendantCount = countClickableOrFocusableDescendants(current, limit = 2)
            if (interactiveDescendantCount == 1) {
                return true
            }
        }

        val descendantTextCandidates = collectDescendantTextCandidates(current)
        val recoveredDescendantLabel = recoverLabelFromDescendantTexts(descendantTextCandidates)
        if (shouldExcludeContainerNodeFromTraversal(current, descendantTextCandidates)) {
            return true
        }
        if (
            !recoveredDescendantLabel.isNullOrBlank() &&
            (current.isClickable || current.isFocusable) &&
            shouldAllowRecoveredDescendantLabelForTraversal(descendantTextCandidates)
        ) {
            return false
        }
        if (isOneConnectSettingsCandidateNode(current, recoveredDescendantLabel)) {
            return false
        }
        return shouldExcludeAsEmptyShell(
            mergedText = node.text,
            mergedContentDescription = node.contentDescription,
            clickable = current.isClickable,
            childCount = current.childCount
        )
    }

    internal fun isOneConnectSettingsCandidateNode(
        node: AccessibilityNodeInfo,
        recoveredLabel: String? = recoverDescendantLabel(node)
    ): Boolean {
        if (!node.isVisibleToUser) return false
        val packageName = node.packageName?.toString()?.trim().orEmpty()
        if (packageName != ONECONNECT_PACKAGE_NAME) return false
        if (!node.isClickable && !node.isFocusable) return false
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        if (bounds.top <= 0 || bounds.left < 0) return false

        val viewId = node.viewIdResourceName?.substringAfterLast('/')?.trim().orEmpty()
        val ownLabel = node.contentDescription?.toString()?.trim().orEmpty()
        val mergedLabel = listOfNotNull(ownLabel.takeIf { it.isNotEmpty() }, recoveredLabel?.trim())
            .joinToString(separator = " ")
            .lowercase()
        val normalizedViewId = viewId.lowercase()
        return A11yNodeUtils.containsSettingsKeyword(normalizedViewId) || A11yNodeUtils.containsSettingsKeyword(mergedLabel)
    }

    internal fun shouldExcludeAsEmptyShell(
        mergedText: String?,
        mergedContentDescription: String?,
        clickable: Boolean,
        childCount: Int
    ): Boolean {
        val hasMergedLabel = !mergedText.isNullOrBlank() || !mergedContentDescription.isNullOrBlank()
        if (hasMergedLabel) return false

        if (clickable) {
            return true
        }

        return childCount == 0
    }

    internal fun spatialComparator(yBucketSize: Int = 5): Comparator<FocusedNode> {
        return Comparator { left, right ->
            compareByContainmentAndPosition(
                left = left.node,
                right = right.node,
                parentOf = { node -> node.parent },
                boundsOf = { node ->
                    Rect().also { rect ->
                        node.getBoundsInScreen(rect)
                    }
                },
                yBucketSize = yBucketSize
            )
        }
    }

    internal fun <T> compareByContainmentAndPosition(
        left: T,
        right: T,
        parentOf: (T) -> T?,
        boundsOf: (T) -> Rect,
        yBucketSize: Int = 5
    ): Int {
        if (left == right) return 0
        if (isAncestorOf(ancestor = left, descendant = right, parentOf = parentOf)) return -1
        if (isAncestorOf(ancestor = right, descendant = left, parentOf = parentOf)) return 1

        val leftRect = boundsOf(left)
        val rightRect = boundsOf(right)

        val leftCenterY = (leftRect.top + leftRect.bottom) / 2
        val rightCenterY = (rightRect.top + rightRect.bottom) / 2
        if (kotlin.math.abs(leftCenterY - rightCenterY) < yBucketSize) {
            if (leftRect.bottom <= rightRect.top) return -1
            if (rightRect.bottom <= leftRect.top) return 1
        }

        val leftCenterYBucket = leftCenterY / yBucketSize
        val rightCenterYBucket = rightCenterY / yBucketSize
        if (leftCenterYBucket != rightCenterYBucket) return leftCenterYBucket - rightCenterYBucket
        if (leftRect.left != rightRect.left) return leftRect.left - rightRect.left
        return leftRect.top - rightRect.top
    }

    internal fun <T> isAncestorOf(
        ancestor: T,
        descendant: T,
        parentOf: (T) -> T?
    ): Boolean {
        var current = parentOf(descendant)
        while (current != null) {
            if (current == ancestor) return true
            current = parentOf(current)
        }
        return false
    }

    internal fun analyzePostScrollState(
        treeChanged: Boolean,
        anchorMaintained: Boolean,
        newlyExposedCandidateExists: Boolean
    ): PostScrollAnalysis {
        val noProgress = !treeChanged && !anchorMaintained && !newlyExposedCandidateExists
        val reason = when {
            noProgress -> "no_progress"
            newlyExposedCandidateExists -> "newly_exposed_after_scroll"
            anchorMaintained -> "anchor_maintained"
            treeChanged -> "tree_changed"
            else -> "unknown"
        }
        return PostScrollAnalysis(
            treeChanged = treeChanged,
            anchorMaintained = anchorMaintained,
            newlyExposedCandidateExists = newlyExposedCandidateExists,
            noProgress = noProgress,
            reason = reason
        )
    }

    internal fun selectPostScrollContinuationCandidate(
        candidateIndex: Int,
        analysis: PostScrollAnalysis
    ): CandidateSelectionResult {
        if (candidateIndex < 0) {
            return CandidateSelectionResult(
                index = -1,
                accepted = false,
                reasonCode = if (analysis.noProgress) "rejected:no_progress_after_scroll" else "rejected:no_valid_continuation_candidate"
            )
        }
        val reason = when {
            analysis.newlyExposedCandidateExists -> "accepted:newly_revealed_after_scroll"
            analysis.anchorMaintained -> "accepted:logical_successor"
            else -> "accepted:post_scroll_continuation"
        }
        return CandidateSelectionResult(
            index = candidateIndex,
            accepted = true,
            reasonCode = reason
        )
    }

    private fun evaluatePostScrollContinuationCandidate(
        isBottomBar: Boolean,
        classification: CandidateClassification,
        inVisibleHistory: Boolean,
        inVisitedHistory: Boolean,
        hasUnvisitedLabeledContentCandidate: Boolean,
        continuationFallbackCandidate: Boolean,
        rewoundBeforeAnchor: Boolean,
        headerResurfacedBeforeAnchor: Boolean,
        prioritizedNewlyRevealed: Boolean,
        focusable: Boolean?,
        isOutOfScreen: Boolean,
        isLogicalSuccessor: Boolean,
        rewoundNonContentCandidate: Boolean,
        descendantLabelResolved: Boolean,
        hasResolvedLabel: Boolean
    ): ContinuationCandidateEvaluation {
        val reasons = mutableListOf<String>()
        val allowContinuationDespiteRewoundBeforeAnchor =
            rewoundBeforeAnchor &&
                !classification.isTopChrome &&
                !classification.isPersistentHeader &&
                classification.isContentNode &&
                descendantLabelResolved &&
                hasResolvedLabel &&
                (isLogicalSuccessor || continuationFallbackCandidate || hasUnvisitedLabeledContentCandidate)
        if (classification.isTopChrome) reasons += "rejected:top_resurfaced_header"
        if (!classification.isContentNode) reasons += "rejected:not_content_node"
        if (focusable == false) reasons += "rejected:not_focusable"
        if (isOutOfScreen) reasons += "rejected:outside_content_bounds"
        if (inVisitedHistory && !continuationFallbackCandidate) reasons += "rejected:already_visited"
        if (headerResurfacedBeforeAnchor) reasons += "rejected:header_resurfaced_before_anchor"
        if (rewoundNonContentCandidate) reasons += "rejected:rewound_before_anchor"
        if (rewoundBeforeAnchor && !allowContinuationDespiteRewoundBeforeAnchor) {
            reasons += "rejected:rewound_before_anchor"
        }

        val priority = when {
            prioritizedNewlyRevealed && !classification.isTopChrome && !isBottomBar && classification.isContentNode -> 0
            hasUnvisitedLabeledContentCandidate && !classification.isTopChrome && !isBottomBar && classification.isContentNode -> 1
            continuationFallbackCandidate && !classification.isTopChrome && !isBottomBar && classification.isContentNode -> 2
            isBottomBar -> 3
            else -> Int.MAX_VALUE
        }
        return ContinuationCandidateEvaluation(
            priority = if (reasons.isEmpty()) priority else Int.MAX_VALUE,
            rejectionReasons = reasons,
            isLogicalSuccessor = isLogicalSuccessor,
            acceptedDespiteRewoundBeforeAnchor = allowContinuationDespiteRewoundBeforeAnchor
        )
    }

    private fun classifyPostScrollCandidate(
        isTopBar: Boolean,
        isContentNode: Boolean,
        isTopResurfacedAnchorCandidate: Boolean,
        isHeaderLikeNode: Boolean,
        inVisibleHistory: Boolean,
        isAfterPreScrollAnchor: Boolean,
        isInteractiveCandidate: Boolean,
        bounds: Rect,
        screenTop: Int,
        screenHeight: Int
    ): CandidateClassification {
        val isTopArea = bounds.top <= screenTop + (screenHeight / 4)
        val isPersistentHeader = isTopBar || (isTopArea && isHeaderLikeNode && !isContentNode)
        val isTopChrome = isTopResurfacedAnchorCandidate || isPersistentHeader || (isTopArea && !isContentNode && !isInteractiveCandidate)
        return CandidateClassification(
            isTopChrome = isTopChrome,
            isPersistentHeader = isPersistentHeader,
            isContentNode = isContentNode
        )
    }

    private fun evaluateNewlyRevealedCandidate(
        isInteractiveCandidate: Boolean,
        inVisitedHistory: Boolean,
        hasResolvedLabel: Boolean,
        isBottomBar: Boolean,
        preScrollSeen: Boolean,
        isPreScrollContinuationCandidate: Boolean,
        preScrollHadResolvedLabel: Boolean,
        classification: CandidateClassification,
        rewoundBeforeAnchor: Boolean
    ): NewlyRevealedEvaluation {
        val reasons = mutableListOf<String>()
        val notInPreScrollTraversal = !preScrollSeen
        val notInPreScrollAnchorContinuation = !isPreScrollContinuationCandidate
        val resolvedLabelNewlyAcquiredPostScroll = hasResolvedLabel && !preScrollHadResolvedLabel

        if (notInPreScrollTraversal) reasons += "not_in_pre_scroll_traversal"
        if (notInPreScrollAnchorContinuation) reasons += "not_in_pre_scroll_anchor_continuation"
        if (resolvedLabelNewlyAcquiredPostScroll) reasons += "resolved_label_newly_acquired_post_scroll"

        val prioritized = isInteractiveCandidate &&
            !inVisitedHistory &&
            hasResolvedLabel &&
            !isBottomBar &&
            !classification.isTopChrome &&
            !classification.isPersistentHeader &&
            !rewoundBeforeAnchor &&
            (notInPreScrollTraversal || notInPreScrollAnchorContinuation || resolvedLabelNewlyAcquiredPostScroll)

        return NewlyRevealedEvaluation(
            prioritizedNewlyRevealed = prioritized,
            reasons = reasons
        )
    }

    internal fun <T> selectPostScrollCandidate(
        traversalList: List<T>,
        startIndex: Int,
        visibleHistory: Set<String>,
        visibleHistorySignatures: Set<A11yHistoryManager.VisibleHistorySignature>,
        visitedHistory: Set<String>,
        visitedHistorySignatures: Set<A11yHistoryManager.VisibleHistorySignature>,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        isContentNodeOf: (T) -> Boolean = { true },
        clickableOf: ((T) -> Boolean)? = null,
        focusableOf: ((T) -> Boolean)? = null,
        descendantLabelOf: ((T) -> String?)? = null,
        promotedViewIds: Set<String> = emptySet(),
        preScrollAnchor: A11yHistoryManager.PreScrollAnchor? = null,
        preScrollAnchorBottom: Int? = null,
        labelOf: (T) -> String?,
        isTopAppBarNode: (String?, String?, Rect, Int, Int) -> Boolean,
        isBottomNavigationBarNode: (String?, String?, Rect, Int, Int) -> Boolean,
        isInVisibleHistory: (String, String?, Rect, Set<String>, Set<A11yHistoryManager.VisibleHistorySignature>) -> Boolean,
        isInVisitedHistory: (String, String?, Rect, Set<String>, Set<A11yHistoryManager.VisibleHistorySignature>) -> Boolean,
        logVisitedHistorySkip: (String, String, String?, Rect) -> Unit,
        isHeaderLikeCandidate: (String?, String?, String, Rect, Int, Int) -> Boolean,
        hasPreScrollResolvedLabel: (String, String, String?, Rect, Set<A11yHistoryManager.VisibleHistorySignature>) -> Boolean
    ): PostScrollContinuationSearchResult {
        if (traversalList.isEmpty()) {
            return PostScrollContinuationSearchResult(
                index = -1,
                hasValidPostScrollCandidate = false
            )
        }
        val normalizedAnchorViewId = preScrollAnchor?.viewIdResourceName?.substringAfterLast('/')?.trim()
        val expectedSuccessorViewId = normalizedAnchorViewId
            ?.let { SETTINGS_ROW_VIEW_ID_ORDERED.indexOf(it) }
            ?.takeIf { it >= 0 && it < SETTINGS_ROW_VIEW_ID_ORDERED.lastIndex }
            ?.let { SETTINGS_ROW_VIEW_ID_ORDERED[it + 1] }
        val anchorBounds = preScrollAnchor?.bounds
        var bestIndex = -1
        var bestPriority = Int.MAX_VALUE
        var hasValidPostScrollCandidate = false
        for (index in startIndex until traversalList.size) {
            val node = traversalList[index]
            val bounds = boundsOf(node)
            val isTopBar = isTopAppBarNode(classNameOf(node), viewIdOf(node), bounds, screenTop, screenHeight)
            val isBottomBar = isBottomNavigationBarNode(classNameOf(node), viewIdOf(node), bounds, screenBottom, screenHeight)
            val label = labelOf(node)?.trim().orEmpty()
            val rawViewId = viewIdOf(node)
            val normalizedViewId = rawViewId?.lowercase().orEmpty()
            val shortViewId = rawViewId?.substringAfterLast('/')?.trim().orEmpty()
            val inVisibleHistory = isInVisibleHistory(
                label,
                rawViewId,
                bounds,
                visibleHistory,
                visibleHistorySignatures
            )
            val inVisitedHistory = isInVisitedHistory(
                label,
                viewIdOf(node),
                bounds,
                visitedHistory,
                visitedHistorySignatures
            )
            if (!inVisitedHistory) {
                logVisitedHistorySkip(
                    "anchor continuity candidate only",
                    label,
                    viewIdOf(node),
                    bounds
                )
            }
            val isContentNode = isContentNodeOf(node)
            val isTopResurfacedAnchorCandidate =
                bounds.top <= screenTop + (screenHeight / 4) &&
                    (isTopBar || normalizedViewId.contains("toolbar") || normalizedViewId.contains("appbar"))
            val isAfterPreScrollAnchor = preScrollAnchorBottom?.let { bounds.top >= it } ?: false
            val isTrailingContinuationCandidate = inVisibleHistory && isAfterPreScrollAnchor
            val isTopViewportContent = bounds.top in screenTop..(screenTop + screenHeight / 3)
            val isPreScrollAnchorItself = preScrollAnchor?.viewIdResourceName?.equals(rawViewId, ignoreCase = true) == true
            val rewoundBeforeAnchor = anchorBounds != null && bounds.bottom <= anchorBounds.bottom
            val isInteractiveCandidate = (focusableOf?.invoke(node) == true) || (clickableOf?.invoke(node) == true)
            val isHeaderLikeNode = isHeaderLikeCandidate(
                classNameOf(node),
                rawViewId,
                label,
                bounds,
                screenTop,
                screenHeight
            )
            val descendantLabel = descendantLabelOf?.invoke(node)?.trim().orEmpty()
            val hasResolvedLabel = label.isNotBlank() || descendantLabel.isNotBlank()
            val preScrollSeen = inVisibleHistory
            val postScrollSeen = true
            val isPreScrollContinuationCandidate = preScrollSeen && isAfterPreScrollAnchor
            val preScrollHadResolvedLabel = preScrollSeen && hasPreScrollResolvedLabel(
                label,
                descendantLabel,
                rawViewId,
                bounds,
                visibleHistorySignatures
            )
            val descendantLabelResolved = descendantLabel.isNotBlank()
            val candidateClassification = classifyPostScrollCandidate(
                isTopBar = isTopBar,
                isContentNode = isContentNode,
                isTopResurfacedAnchorCandidate = isTopResurfacedAnchorCandidate,
                isHeaderLikeNode = isHeaderLikeNode,
                inVisibleHistory = inVisibleHistory,
                isAfterPreScrollAnchor = isAfterPreScrollAnchor,
                isInteractiveCandidate = isInteractiveCandidate,
                bounds = bounds,
                screenTop = screenTop,
                screenHeight = screenHeight
            )
            val headerResurfacedBeforeAnchor = anchorBounds != null &&
                bounds.top < anchorBounds.top &&
                (candidateClassification.isPersistentHeader || isTopResurfacedAnchorCandidate || isHeaderLikeNode)
            val newlyRevealedEvaluation = evaluateNewlyRevealedCandidate(
                isInteractiveCandidate = isInteractiveCandidate,
                inVisitedHistory = inVisitedHistory,
                hasResolvedLabel = hasResolvedLabel,
                isBottomBar = isBottomBar,
                preScrollSeen = preScrollSeen,
                isPreScrollContinuationCandidate = isPreScrollContinuationCandidate,
                preScrollHadResolvedLabel = preScrollHadResolvedLabel,
                classification = candidateClassification,
                rewoundBeforeAnchor = rewoundBeforeAnchor
            )
            val isNewlyRevealedAfterScroll = newlyRevealedEvaluation.reasons.isNotEmpty()
            val newlyRevealedReason = if (newlyRevealedEvaluation.reasons.isEmpty()) "none" else newlyRevealedEvaluation.reasons.joinToString("|")
            val shouldPrioritizeNewlyRevealedInteractiveCandidate =
                newlyRevealedEvaluation.prioritizedNewlyRevealed && !isPreScrollAnchorItself
            val rewoundNonContentCandidate = rewoundBeforeAnchor && !isContentNode
            if (!isBottomBar && isInteractiveCandidate && hasResolvedLabel && isNewlyRevealedAfterScroll) {
                hasValidPostScrollCandidate = true
            }
            val isPostScrollTopContinuationCandidate =
                preScrollAnchor != null &&
                    isTopViewportContent &&
                    !isPreScrollAnchorItself &&
                    !isTopResurfacedAnchorCandidate &&
                    !isTopBar &&
                    !isBottomBar &&
                    isContentNode &&
                    !inVisitedHistory
            val isPromotedRawOnlyCandidate = promotedViewIds.contains(shortViewId) && !inVisibleHistory && !inVisitedHistory
            val isNewlyExposedBottomContent = !inVisibleHistory && !inVisitedHistory && bounds.bottom >= (screenBottom - screenHeight / 3)
            val isOtherUnvisitedVisible = !inVisitedHistory && !inVisibleHistory
            val isOutOfScreen = bounds.bottom <= screenTop || bounds.top >= screenBottom
            val withinAnchorSuccessorWindow = anchorBounds?.let { anchor ->
                val horizontalOverlap = minOf(anchor.right, bounds.right) - maxOf(anchor.left, bounds.left)
                bounds.top >= anchor.bottom && horizontalOverlap > 0
            } ?: false
            val isLogicalSuccessor = !expectedSuccessorViewId.isNullOrBlank() &&
                shortViewId == expectedSuccessorViewId &&
                withinAnchorSuccessorWindow &&
                !isTopBar &&
                !isBottomBar &&
                isContentNode
            val hasUnvisitedLabeledContentCandidate =
                !inVisitedHistory &&
                    hasResolvedLabel &&
                    isContentNode &&
                    !candidateClassification.isTopChrome &&
                    !isBottomBar &&
                    !isPreScrollAnchorItself
            val continuationFallbackCandidate =
                (isLogicalSuccessor || isPostScrollTopContinuationCandidate || isTrailingContinuationCandidate || isPromotedRawOnlyCandidate || isNewlyExposedBottomContent || isOtherUnvisitedVisible) &&
                    !isPreScrollAnchorItself
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT] candidate_classification index=$index isTopChrome=${candidateClassification.isTopChrome} isPersistentHeader=${candidateClassification.isPersistentHeader} isContentNode=${candidateClassification.isContentNode}"
            )
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT] newly_revealed_eval index=$index prioritized=${newlyRevealedEvaluation.prioritizedNewlyRevealed} reasons=${if (newlyRevealedEvaluation.reasons.isEmpty()) "none" else newlyRevealedEvaluation.reasons.joinToString("|")}"
            )
            val candidateEvaluation = evaluatePostScrollContinuationCandidate(
                isBottomBar = isBottomBar,
                classification = candidateClassification,
                inVisibleHistory = inVisibleHistory,
                inVisitedHistory = inVisitedHistory,
                hasUnvisitedLabeledContentCandidate = hasUnvisitedLabeledContentCandidate,
                continuationFallbackCandidate = continuationFallbackCandidate,
                rewoundBeforeAnchor = rewoundBeforeAnchor,
                headerResurfacedBeforeAnchor = headerResurfacedBeforeAnchor,
                prioritizedNewlyRevealed = shouldPrioritizeNewlyRevealedInteractiveCandidate,
                focusable = focusableOf?.invoke(node),
                isOutOfScreen = isOutOfScreen,
                isLogicalSuccessor = isLogicalSuccessor,
                rewoundNonContentCandidate = rewoundNonContentCandidate,
                descendantLabelResolved = descendantLabelResolved,
                hasResolvedLabel = hasResolvedLabel
            )
            val reasons = candidateEvaluation.rejectionReasons.toMutableList()
            if (label.isBlank() && descendantLabelOf != null && descendantLabel.isBlank()) {
                reasons += "candidate rejected: no descendant label"
            }
            if (isTopResurfacedAnchorCandidate) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Rejected top resurfaced anchor candidate after scroll")
                reasons += "rejected:top_resurfaced_header"
            }
            if (!expectedSuccessorViewId.isNullOrBlank() && shortViewId != expectedSuccessorViewId && anchorBounds != null && bounds.top < anchorBounds.bottom) {
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_NEXT] Rejected candidate because it precedes anchor successor window index=$index label=${if (label.isBlank()) "<no-label>" else label.replace("\n", " ")} viewId=$rawViewId bounds=$bounds"
                )
            }

            val candidatePriority = if (reasons.none { it.startsWith("candidate rejected") }) {
                evaluatePostScrollContinuationCandidate(
                    isBottomBar = isBottomBar,
                    classification = candidateClassification,
                    inVisibleHistory = inVisibleHistory,
                    inVisitedHistory = inVisitedHistory,
                    hasUnvisitedLabeledContentCandidate = hasUnvisitedLabeledContentCandidate,
                    continuationFallbackCandidate = continuationFallbackCandidate,
                    rewoundBeforeAnchor = rewoundBeforeAnchor,
                    headerResurfacedBeforeAnchor = headerResurfacedBeforeAnchor,
                    prioritizedNewlyRevealed = shouldPrioritizeNewlyRevealedInteractiveCandidate,
                    focusable = focusableOf?.invoke(node),
                    isOutOfScreen = isOutOfScreen,
                    isLogicalSuccessor = isLogicalSuccessor,
                    rewoundNonContentCandidate = rewoundNonContentCandidate,
                    descendantLabelResolved = descendantLabelResolved,
                    hasResolvedLabel = hasResolvedLabel
                ).priority
            } else {
                Int.MAX_VALUE
            }

            if (candidatePriority != Int.MAX_VALUE && reasons.none { it.startsWith("candidate rejected") }) {
                if (candidateEvaluation.acceptedDespiteRewoundBeforeAnchor) {
                    Log.i(
                        "A11Y_HELPER",
                        "[SMART_NEXT] accepted:continuation_candidate_despite_rewound_before_anchor index=$index label=${if (label.isBlank()) "<no-label>" else label.replace("\n", " ")} descendantLabel=${if (descendantLabel.isBlank()) "<no-label>" else descendantLabel.replace("\n", " ")} actualCandidateMatchLikely=${isLogicalSuccessor || continuationFallbackCandidate || hasUnvisitedLabeledContentCandidate}"
                    )
                }
                when (candidatePriority) {
                    0 -> {
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting newly available unvisited interactive continuation candidate")
                        Log.i(
                            "A11Y_HELPER",
                            "[SMART_NEXT] accepted:newly_revealed_after_scroll index=$index label=${if (label.isBlank()) "<no-label>" else label.replace("\n", " ")} descendantLabel=${if (descendantLabel.isBlank()) "<no-label>" else descendantLabel.replace("\n", " ")} rewoundBeforeAnchor=$rewoundBeforeAnchor inVisibleHistory=$inVisibleHistory inVisitedHistory=$inVisitedHistory preScrollSeen=$preScrollSeen postScrollSeen=$postScrollSeen descendantLabelResolved=$descendantLabelResolved newlyRevealedReason=$newlyRevealedReason"
                        )
                    }
                    1 -> Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting unvisited labeled content candidate")
                    2 -> Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting continuation fallback candidate")
                    3 -> Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting bottom bar fallback candidate")
                }
                if (candidatePriority < bestPriority) {
                    bestPriority = candidatePriority
                    bestIndex = index
                    if (candidatePriority == 0) {
                        Log.i(
                            "A11Y_HELPER",
                            "[SMART_NEXT] Selected successor candidate label=${if (label.isBlank()) "<no-label>" else label.replace("\n", " ")} viewId=$rawViewId"
                        )
                    }
                }
            } else {
                if (!isContentNode && reasons.none { it == "candidate rejected: outside content bounds" }) {
                    reasons += "candidate rejected: outside content bounds"
                }
                if (inVisitedHistory && label.isNotBlank()) {
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping resurfaced pre-scroll item: $label")
                }
                val candidateLabel = if (label.isBlank()) "<no-label>" else label.replace("\n", " ")
                if (reasons.isEmpty()) reasons += "Candidate rejected: unvisited but not part of downward continuation"
                reasons.forEach { reason ->
                    if (reason == "rejected:rewound_before_anchor") {
                        Log.i(
                            "A11Y_HELPER",
                            "[SMART_NEXT] rejected:rewound_before_anchor index=$index label=$candidateLabel descendantLabel=${if (descendantLabel.isBlank()) "<no-label>" else descendantLabel.replace("\n", " ")} rewoundBeforeAnchor=$rewoundBeforeAnchor inVisibleHistory=$inVisibleHistory inVisitedHistory=$inVisitedHistory prioritizedNewlyRevealed=$shouldPrioritizeNewlyRevealedInteractiveCandidate preScrollSeen=$preScrollSeen postScrollSeen=$postScrollSeen descendantLabelResolved=$descendantLabelResolved newlyRevealedReason=$newlyRevealedReason"
                        )
                    }
                    if (reason == "rejected:header_resurfaced_before_anchor") {
                        Log.i(
                            "A11Y_HELPER",
                            "[SMART_NEXT] rejected:header_resurfaced_before_anchor index=$index label=$candidateLabel rewoundBeforeAnchor=$rewoundBeforeAnchor headerLike=$isHeaderLikeNode"
                        )
                    }
                    Log.i(
                        "A11Y_HELPER",
                        "[SMART_NEXT] $reason index=$index label=$candidateLabel viewId=${viewIdOf(node)} className=${classNameOf(node)} clickable=${clickableOf?.invoke(node)} focusable=${focusableOf?.invoke(node)} bounds=$bounds"
                    )
                }
            }
            val decisionSummary = if (candidatePriority != Int.MAX_VALUE) "accepted" else "rejected"
            val reasonsSummary = if (reasons.isEmpty()) "none" else reasons.joinToString("|")
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT] successor_candidate_eval index=$index decision=$decisionSummary rewoundBeforeAnchor=$rewoundBeforeAnchor headerResurfacedBeforeAnchor=$headerResurfacedBeforeAnchor reason=$reasonsSummary"
            )
        }
        return PostScrollContinuationSearchResult(
            index = bestIndex,
            hasValidPostScrollCandidate = bestIndex >= 0 || hasValidPostScrollCandidate
        )
    }

    internal fun recoverLabelFromDescendantTexts(textCandidates: List<String>): String? {
        return textCandidates
            .asSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .firstOrNull()
    }

    private fun collectDescendantTextCandidates(node: AccessibilityNodeInfo): List<String> {
        val textCandidates = mutableListOf<String>()
        collectDescendantReadableText(
            node = node,
            includeCurrentNode = true,
            sink = textCandidates
        )
        return textCandidates
    }

    internal fun shouldAllowRecoveredDescendantLabelForTraversal(textCandidates: List<String>): Boolean {
        val normalized = textCandidates
            .asSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .distinct()
            .toList()
        if (normalized.isEmpty()) return false
        if (normalized.size <= 2) return true

        val mergedLength = normalized.joinToString(separator = " ").length
        return normalized.size <= 3 && mergedLength <= 60
    }

    private fun isContainerLikeClassName(className: String?): Boolean {
        return A11yNodeUtils.isContainerLikeClassName(className)
    }

    private fun isContainerLikeViewId(viewIdResourceName: String?): Boolean {
        return A11yNodeUtils.isContainerLikeViewId(viewIdResourceName)
    }

    internal fun shouldExcludeContainerNodeFromTraversal(
        node: AccessibilityNodeInfo,
        descendantTextCandidates: List<String>
    ): Boolean {
        if (isContainerLikeClassName(node.className?.toString())) return true
        if (isContainerLikeViewId(node.viewIdResourceName)) return true
        if (hasMultipleSiblingLevelInteractiveDescendants(node)) return true

        val coversMostContentArea = doesNodeCoverMostContentArea(node)
        if (!coversMostContentArea) return false

        val clickableDescendantCount = countClickableOrFocusableDescendants(node, limit = 3)
        if (clickableDescendantCount < 2) return false

        return !shouldAllowRecoveredDescendantLabelForTraversal(descendantTextCandidates)
    }

    internal fun hasMultipleSiblingLevelInteractiveDescendants(node: AccessibilityNodeInfo): Boolean {
        val directInteractiveChildren = countDirectInteractiveChildren(node, limit = 2)
        if (directInteractiveChildren >= 2) return true
        val descendantInteractiveChildren = countClickableOrFocusableDescendants(node, limit = 3)
        return descendantInteractiveChildren >= 3 && doesNodeCoverMostContentArea(node)
    }

    internal fun countDirectInteractiveChildren(node: AccessibilityNodeInfo, limit: Int): Int {
        var count = 0
        for (index in 0 until node.childCount) {
            val child = node.getChild(index) ?: continue
            if (!child.isVisibleToUser) continue
            val screenReaderFocusable = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && child.isScreenReaderFocusable
            if (child.isClickable || child.isFocusable || screenReaderFocusable) {
                count += 1
                if (count >= limit) break
            }
        }
        return count
    }

    internal fun doesNodeCoverMostContentArea(node: AccessibilityNodeInfo): Boolean {
        val nodeBounds = Rect().also { node.getBoundsInScreen(it) }
        if (nodeBounds.width() <= 0 || nodeBounds.height() <= 0) return false

        val rootBounds = resolveRootBounds(node) ?: return false
        if (rootBounds.width() <= 0 || rootBounds.height() <= 0) return false

        val widthRatio = nodeBounds.width().toFloat() / rootBounds.width().toFloat()
        val heightRatio = nodeBounds.height().toFloat() / rootBounds.height().toFloat()
        val areaRatio = (nodeBounds.width().toLong() * nodeBounds.height().toLong()).toFloat() /
            (rootBounds.width().toLong() * rootBounds.height().toLong()).toFloat()
        return widthRatio >= 0.85f && heightRatio >= 0.45f && areaRatio >= 0.40f
    }

    internal fun resolveRootBounds(node: AccessibilityNodeInfo): Rect? {
        var current: AccessibilityNodeInfo? = node
        var latest: AccessibilityNodeInfo? = node
        while (current != null) {
            latest = current
            current = current.parent
        }
        return latest?.let {
            Rect().also { rootBounds -> it.getBoundsInScreen(rootBounds) }
        }
    }

    internal fun countClickableOrFocusableDescendants(node: AccessibilityNodeInfo, limit: Int): Int {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue += node
        var count = 0
        while (queue.isNotEmpty() && count < limit) {
            val current = queue.removeFirst()
            if (current !== node && current.isVisibleToUser) {
                val screenReaderFocusable = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && current.isScreenReaderFocusable
                if (current.isClickable || current.isFocusable || screenReaderFocusable) {
                    count += 1
                    if (count >= limit) break
                }
            }
            for (index in 0 until current.childCount) {
                current.getChild(index)?.let(queue::addLast)
            }
        }
        return count
    }

    internal fun recoverDescendantLabel(node: AccessibilityNodeInfo): String? {
        val textCandidates = collectDescendantTextCandidates(node)
        return recoverLabelFromDescendantTexts(textCandidates)
    }

    internal fun <T> findNodeIndexByIdentity(
        nodes: List<T>,
        target: T,
        idOf: (T) -> String?,
        textOf: (T) -> String?,
        contentDescriptionOf: (T) -> String?,
        boundsOf: (T) -> Rect,
        onCoordinateMatch: ((Int) -> Unit)? = null
    ): Int {
        val targetId = idOf(target)
        val targetText = textOf(target)
        val targetContentDescription = contentDescriptionOf(target)
        val targetBounds = boundsOf(target)

        val coordinateMatchIndex = nodes.indexOfFirst { candidate ->
            val candidateBounds = boundsOf(candidate)
            candidateBounds == targetBounds
        }

        if (coordinateMatchIndex != -1) {
            onCoordinateMatch?.invoke(coordinateMatchIndex)
            return coordinateMatchIndex
        }

        return nodes.withIndex()
            .asSequence()
            .filter { (_, candidate) ->
                idOf(candidate) == targetId &&
                    textOf(candidate) == targetText &&
                    contentDescriptionOf(candidate) == targetContentDescription
            }
            .minByOrNull { (_, candidate) ->
                val candidateBounds = boundsOf(candidate)
                val dx = ((candidateBounds.left + candidateBounds.right) / 2) - ((targetBounds.left + targetBounds.right) / 2)
                val dy = ((candidateBounds.top + candidateBounds.bottom) / 2) - ((targetBounds.top + targetBounds.bottom) / 2)
                (dx * dx) + (dy * dy)
            }
            ?.index
            ?: -1
    }

    internal fun <T> resolveAnchorIndexInRefreshedTraversal(
        traversalList: List<T>,
        anchor: A11yHistoryManager.PreScrollAnchor,
        boundsOf: (T) -> Rect,
        viewIdOf: (T) -> String?,
        textOf: (T) -> String?,
        contentDescriptionOf: (T) -> String?
    ): Int {
        if (traversalList.isEmpty()) return -1
        val exact = traversalList.indexOfFirst { candidate ->
            val label = textOf(candidate)?.trim().takeUnless { it.isNullOrEmpty() }
                ?: contentDescriptionOf(candidate)?.trim().takeUnless { it.isNullOrEmpty() }
            val merged = listOfNotNull(textOf(candidate), contentDescriptionOf(candidate))
                .joinToString(" ").trim().takeUnless { it.isNullOrEmpty() }
            viewIdOf(candidate) == anchor.viewIdResourceName &&
                (label == anchor.talkbackLabel || label == anchor.text || merged == anchor.mergedLabel)
        }
        if (exact >= 0) return exact

        return traversalList.indices
            .map { index ->
                val candidate = traversalList[index]
                val bounds = boundsOf(candidate)
                val candidateLabel = textOf(candidate)?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: contentDescriptionOf(candidate)?.trim().takeUnless { it.isNullOrEmpty() }
                val anchorLabel = anchor.mergedLabel ?: anchor.talkbackLabel ?: anchor.text ?: anchor.contentDescription
                val labelSimilarity = normalizedLabelSimilarity(anchorLabel, candidateLabel)
                val boundsDistance = abs(bounds.top - anchor.bounds.top) + abs(bounds.bottom - anchor.bounds.bottom)
                Triple(index, labelSimilarity, boundsDistance)
            }
            .filter { (_, similarity, _) -> similarity >= 0.4f }
            .minWithOrNull(compareByDescending<Triple<Int, Float, Int>> { it.second }.thenBy { it.third })
            ?.first ?: -1
    }

    internal fun normalizedLabelSimilarity(a: String?, b: String?): Float {
        val left = a?.trim()?.lowercase().orEmpty()
        val right = b?.trim()?.lowercase().orEmpty()
        if (left.isBlank() || right.isBlank()) return 0f
        if (left == right) return 1f
        if (left.contains(right) || right.contains(left)) return 0.8f
        val leftTokens = left.split(" ").filter { it.isNotBlank() }.toSet()
        val rightTokens = right.split(" ").filter { it.isNotBlank() }.toSet()
        if (leftTokens.isEmpty() || rightTokens.isEmpty()) return 0f
        val intersection = leftTokens.intersect(rightTokens).size.toFloat()
        val union = leftTokens.union(rightTokens).size.toFloat().coerceAtLeast(1f)
        return intersection / union
    }
}
