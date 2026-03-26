package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityEvent
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import kotlin.math.abs

object A11yNavigator {
    const val NAVIGATOR_ALGORITHM_VERSION: String = "2.38.0"
    private const val ONECONNECT_PACKAGE_NAME = "com.samsung.android.oneconnect"
    private val SETTINGS_BUTTON_KEYWORDS = listOf("setting_button_layout", "settings", "setting", "gear")
    private val TRAVERSAL_CONTAINER_CLASS_KEYWORDS = listOf(
        "scrollview",
        "horizontalscrollview",
        "nestedscrollview",
        "recyclerview"
    )
    private val TRAVERSAL_CONTAINER_VIEW_ID_KEYWORDS = listOf(
        "mainscrollview",
        "content_container",
        "root_container",
        "main_content_container",
        "feature_item_menu",
        "section_wrapper",
        "group_wrapper",
        "row_container",
        "grid_container"
    )

    private val visitedHistoryLock = Any()
    private val visitedHistoryLabels = linkedSetOf<String>()
    private val visitedHistorySignatures = mutableListOf<VisibleHistorySignature>()

    @Volatile
    private var lastRequestedFocusIndex: Int = A11yStateStore.lastRequestedFocusIndex

    data class TargetActionOutcome(
        val success: Boolean,
        val reason: String,
        val target: AccessibilityNodeInfo? = null
    )

    internal data class PreScrollAnchor(
        val viewIdResourceName: String?,
        val mergedLabel: String?,
        val talkbackLabel: String?,
        val text: String?,
        val contentDescription: String?,
        val bounds: Rect
    )

    internal data class VisibleHistorySignature(
        val label: String?,
        val viewId: String?,
        val bounds: Rect,
        val nodeIdentity: String?
    )

    internal data class PostScrollContinuationPlan(
        val anchorStartIndex: Int,
        val skipGeneralScan: Boolean
    )

    private data class CollectResult(
        val focusNodes: List<FocusedNode>,
        val traversalList: List<AccessibilityNodeInfo>,
        val focusNodeByNode: Map<AccessibilityNodeInfo, FocusedNode>
    )

    private data class NormalizeResult(
        val screenRect: Rect,
        val screenTop: Int,
        val screenBottom: Int,
        val screenHeight: Int,
        val effectiveBottom: Int
    )

    private data class SelectionDecision(
        val currentIndex: Int,
        val fallbackIndex: Int,
        val nextIndex: Int
    )

    private data class ScrollDecision(
        val shouldPreScroll: Boolean,
        val noProgressAfterScroll: Boolean = false,
        val reason: String
    )

    private data class FocusAttemptResult(
        val outcome: TargetActionOutcome,
        val verificationPassed: Boolean,
        val snapBackDetected: Boolean
    )

    private data class BottomBarEntryDecision(
        val allowBottomBarEntry: Boolean,
        val requirePreScroll: Boolean,
        val reason: String
    )

    private data class NavigationContext(
        val root: AccessibilityNodeInfo,
        val collect: CollectResult,
        val normalize: NormalizeResult,
        val currentPosition: CurrentPosition
    )

    private data class CurrentPosition(
        val resolvedCurrent: AccessibilityNodeInfo?,
        val currentIndex: Int,
        val fallbackIndex: Int,
        val nextIndex: Int
    )

    private data class PreScrollResult(
        val attempted: Boolean,
        val success: Boolean,
        val anchor: PreScrollAnchor? = null,
        val reason: String
    )

    private data class PostScrollAnalysis(
        val treeChanged: Boolean,
        val anchorMaintained: Boolean,
        val newlyExposedCandidateExists: Boolean,
        val noProgress: Boolean,
        val reason: String
    )

    private data class CandidateSelectionResult(
        val index: Int,
        val accepted: Boolean,
        val reasonCode: String
    )

    private data class FocusExecutionResult(
        val outcome: TargetActionOutcome,
        val reasonCode: String
    )

    private data class ContinuationCandidateEvaluation(
        val priority: Int,
        val rejectionReasons: List<String>,
        val isLogicalSuccessor: Boolean = false
    )

    private data class SmartNextRuntimeState(
        val root: AccessibilityNodeInfo,
        val collect: CollectResult,
        val normalize: NormalizeResult,
        val currentPosition: CurrentPosition,
        val visitedHistory: Set<String>,
        val visitedHistorySignatures: Set<VisibleHistorySignature>,
        val focusNodeByNode: Map<AccessibilityNodeInfo, FocusedNode>
    )

    private data class InitialNextTargetDecision(
        val nextIndex: Int,
        val selectionDecision: SelectionDecision
    )

    private data class NextActionDecision(
        val state: SmartNextRuntimeState,
        val initialTarget: InitialNextTargetDecision
    )

    private data class NextActionExecution(
        val outcome: TargetActionOutcome
    )

    private data class FindAndFocusPhaseContext(
        val root: AccessibilityNodeInfo,
        val traversalList: List<AccessibilityNodeInfo>,
        val screenTop: Int,
        val screenBottom: Int,
        val effectiveBottom: Int,
        val screenHeight: Int,
        val focusNodeByNode: Map<AccessibilityNodeInfo, FocusedNode>,
        val visitedHistory: Set<String>,
        val visitedHistorySignatures: Set<VisibleHistorySignature>
    )

    private data class FindAndFocusRequest(
        val statusName: String,
        val isScrollAction: Boolean = false,
        val excludeDesc: String? = null,
        val startIndex: Int = 0,
        val visibleHistory: Set<String> = emptySet(),
        val visibleHistorySignatures: Set<VisibleHistorySignature> = emptySet(),
        val allowLooping: Boolean = true,
        val preScrollAnchor: PreScrollAnchor? = null
    )

    fun resetFocusHistory() {
        setLastRequestedFocusIndex(-1)
        A11yStateStore.updateLastRequestedFocusIndex(-1)
        synchronized(visitedHistoryLock) {
            visitedHistoryLabels.clear()
            visitedHistorySignatures.clear()
        }
        Log.i("A11Y_HELPER", "Focus history has been explicitly reset by external command.")
    }

    data class TargetQuery(
        val targetName: String,
        val targetType: String,
        val targetIndex: Int,
        val className: String? = null,
        val clickable: Boolean? = null,
        val focusable: Boolean? = null,
        val targetText: String? = null,
        val targetId: String? = null
    )

    fun dumpTreeFlat(root: AccessibilityNodeInfo?): JSONObject {
        if (root == null) {
            return A11yDumpResponse(
                algorithmVersion = NAVIGATOR_ALGORITHM_VERSION,
                canScrollDown = false,
                nodes = emptyList()
            ).toJson()
        }

        val focusNodes = buildTalkBackLikeFocusNodes(root)
        val screenRect = Rect().also { root.getBoundsInScreen(it) }
        val screenTop = screenRect.top
        val screenBottom = screenRect.bottom
        val screenHeight = (screenRect.bottom - screenRect.top).coerceAtLeast(1)

        val nodeInfos = focusNodes.map { focusedNode ->
            nodeToModel(
                node = focusedNode.node,
                textOverride = focusedNode.text,
                contentDescriptionOverride = focusedNode.contentDescription,
                screenTop = screenTop,
                screenBottom = screenBottom,
                screenHeight = screenHeight
            )
        }

        return A11yDumpResponse(
            algorithmVersion = NAVIGATOR_ALGORITHM_VERSION,
            canScrollDown = hasScrollableDownCandidate(root),
            nodes = nodeInfos
        ).toJson()
    }

    fun findAndPerformAction(
        root: AccessibilityNodeInfo?,
        query: TargetQuery,
        action: Int
    ): TargetActionOutcome {
        if (root == null) {
            return TargetActionOutcome(false, "Root node is null")
        }

        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.add(root)
        var matchCount = 0

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            val targetNode = resolveMatchedTarget(node, query)
            if (targetNode != null) {
                if (matchCount != query.targetIndex) {
                    matchCount += 1
                } else {
                    val success = targetNode.performAction(action)
                    val actionName = when (action) {
                        AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS -> "ACTION_ACCESSIBILITY_FOCUS"
                        AccessibilityNodeInfo.ACTION_CLICK -> "ACTION_CLICK"
                        AccessibilityNodeInfo.ACTION_LONG_CLICK -> "ACTION_LONG_CLICK"
                        else -> "ACTION_$action"
                    }
                    return TargetActionOutcome(
                        success = success,
                        reason = if (success) "$actionName success" else "$actionName failed",
                        target = targetNode
                    )
                }
            }

            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }

        return TargetActionOutcome(false, "Target node not found")
    }

    fun findTarget(root: AccessibilityNodeInfo?, query: TargetQuery): TargetActionOutcome {
        if (root == null) {
            return TargetActionOutcome(false, "Root node is null")
        }

        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.add(root)
        var matchCount = 0

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            val targetNode = resolveMatchedTarget(node, query)
            if (targetNode != null) {
                if (matchCount == query.targetIndex) {
                    return TargetActionOutcome(success = true, reason = "Target node found", target = targetNode)
                }
                matchCount += 1
            }

            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }

        return TargetActionOutcome(false, "Target node not found")
    }

    fun matchesTarget(
        nodeText: String?,
        nodeContentDescription: String?,
        nodeViewId: String?,
        nodeClassName: String? = null,
        nodeClickable: Boolean? = null,
        nodeFocusable: Boolean? = null,
        query: TargetQuery
    ): Boolean {
        val targetName = query.targetName.trim()
        val targetType = query.targetType.lowercase().trim()
        val baseMatch = if (targetName.isNotBlank()) {
            val regexPattern = buildRegexPattern(targetName)
            val pattern = runCatching { Regex(regexPattern, setOf(RegexOption.IGNORE_CASE)) }.getOrNull()
            val byText = nodeText?.trim()?.let { text ->
                pattern?.containsMatchIn(text) ?: false
            } == true
            val byTalkback = nodeContentDescription?.trim()?.let { text ->
                pattern?.containsMatchIn(text) ?: false
            } == true
            val byResourceId = nodeViewId?.let { viewId ->
                pattern?.matches(viewId) ?: false
            } ?: false
            when (targetType) {
                "t" -> byText
                "b" -> byTalkback
                "r" -> byResourceId
                "a" -> byText || byTalkback || byResourceId
                else -> false
            }
        } else {
            true
        }

        if (!baseMatch) return false

        val targetTextMatch = query.targetText?.let { targetText ->
            nodeText?.contains(targetText, ignoreCase = true) == true || nodeContentDescription?.contains(targetText, ignoreCase = true) == true
        } ?: true
        val targetIdMatch = query.targetId?.let { targetId ->
            isViewIdMatched(nodeViewId, targetId)
        } ?: true
        val classNameMatch = query.className?.let { queryClassName ->
            nodeClassName?.contains(queryClassName, ignoreCase = true) == true
        } ?: true
        val clickableMatch = query.clickable?.let { expected ->
            nodeClickable == expected
        } ?: true
        val focusableMatch = query.focusable?.let { expected ->
            nodeFocusable == expected
        } ?: true

        return targetTextMatch && targetIdMatch && classNameMatch && clickableMatch && focusableMatch
    }

    private fun collectSmartNextInputs(root: AccessibilityNodeInfo): CollectResult {
        val focusNodes = buildTalkBackLikeFocusNodes(root)
        val traversalList = focusNodes.map { it.node }
        val focusNodeByNode = focusNodes.associateBy { it.node }
        Log.i("A11Y_HELPER", "[COLLECT] Nodes count=${traversalList.size}")
        return CollectResult(
            focusNodes = focusNodes,
            traversalList = traversalList,
            focusNodeByNode = focusNodeByNode
        )
    }

    private fun normalizeSmartNextInputs(
        root: AccessibilityNodeInfo,
        traversalList: List<AccessibilityNodeInfo>
    ): NormalizeResult {
        val screenRect = Rect().also { root.getBoundsInScreen(it) }
        val screenTop = screenRect.top
        val screenBottom = screenRect.bottom
        val screenHeight = (screenBottom - screenTop).coerceAtLeast(1)
        val effectiveBottom = calculateEffectiveBottom(
            nodes = traversalList,
            screenTop = screenTop,
            screenBottom = screenBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            labelOf = { node ->
                node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.viewIdResourceName
            }
        )
        return NormalizeResult(screenRect, screenTop, screenBottom, screenHeight, effectiveBottom)
    }

    private fun resolveCurrentAndNextIndex(
        traversalList: List<AccessibilityNodeInfo>,
        currentNode: AccessibilityNodeInfo?
    ): CurrentPosition {
        val resolvedCurrent = currentNode?.let {
            resolveToClickableAncestor(
                node = it,
                parentOf = { node -> node.parent },
                isClickable = { node -> node.isClickable }
            )
        }
        var currentIndex = resolvedCurrent?.let { resolved ->
            findCurrentTraversalIndex(
                traversalList = traversalList,
                currentNode = resolved,
                isSameNodeMatch = ::isSameNode
            )
        } ?: -1

        if (currentIndex == -1 && resolvedCurrent != null) {
            currentIndex = findNodeIndexByIdentity(
                nodes = traversalList,
                target = resolvedCurrent,
                idOf = { it.viewIdResourceName },
                textOf = { it.text?.toString() },
                contentDescriptionOf = { it.contentDescription?.toString() },
                boundsOf = { Rect().also(it::getBoundsInScreen) }
            )
        }

        if (currentIndex != -1) {
            val currentBounds = Rect().also { traversalList[currentIndex].getBoundsInScreen(it) }
            val duplicateNextBounds = traversalList.getOrNull(currentIndex + 1)?.let { nextNode ->
                Rect().also { nextNode.getBoundsInScreen(it) }
            }
            if (duplicateNextBounds != null && currentBounds == duplicateNextBounds) {
                currentIndex += 1
            }
        }

        val fallbackIndex = if (currentIndex == -1 && (currentNode ?: resolvedCurrent) != null) {
            findClosestNodeBelowCenter(
                nodes = traversalList,
                reference = (currentNode ?: resolvedCurrent)!!,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } }
            )
        } else {
            -1
        }

        val nextIndex = selectSequentialNextCandidateIndex(
            currentIndex = currentIndex,
            fallbackIndex = fallbackIndex,
            lastRequestedIndex = lastRequestedFocusIndex,
            traversalSize = traversalList.size
        )
        return CurrentPosition(
            resolvedCurrent = resolvedCurrent,
            currentIndex = currentIndex,
            fallbackIndex = fallbackIndex,
            nextIndex = nextIndex
        )
    }



    fun performSmartNext(root: AccessibilityNodeInfo?, currentNode: AccessibilityNodeInfo?): TargetActionOutcome {
        Log.i("A11Y_HELPER", "[SMART_NEXT] history policy: visited and visible histories separated")
        if (root == null) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] rootInActiveWindow is null.")
            return TargetActionOutcome(false, "Root node is null")
        }

        val runtimeState = collectSmartNextRuntimeState(root, currentNode)
        val nextActionDecision = decideNextAction(runtimeState)
        val execution = executeNextAction(nextActionDecision)
        return verifyAndFinalizeNextAction(nextActionDecision, execution)
    }

    private fun collectSmartNextRuntimeState(
        root: AccessibilityNodeInfo,
        currentNode: AccessibilityNodeInfo?
    ): SmartNextRuntimeState {
        val collectResult = collectSmartNextInputs(root)
        val focusNodes = collectResult.focusNodes
        val traversalList = collectResult.traversalList
        val focusNodeByNode = collectResult.focusNodeByNode
        focusNodes.forEachIndexed { index, focusedNode ->
            val bounds = Rect().also { focusedNode.node.getBoundsInScreen(it) }
            val label = focusedNode.text?.trim().takeUnless { it.isNullOrEmpty() }
                ?: focusedNode.contentDescription?.trim().takeUnless { it.isNullOrEmpty() }
                ?: focusedNode.node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: focusedNode.node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: "<no-label>"
            val mergedLabel = focusedNode.mergedLabel?.replace("\n", " ") ?: "<none>"
            Log.i(
                "A11Y_HELPER",
                "[NORMALIZE] #$index: ${label.replace("\n", " ")} (L: ${bounds.left}, T: ${bounds.top}, R: ${bounds.right}, B: ${bounds.bottom}) (Merged Label: $mergedLabel)"
            )
        }

        val normalizeResult = normalizeSmartNextInputs(root, traversalList)
        val currentPosition = resolveCurrentAndNextIndex(
            traversalList = traversalList,
            currentNode = currentNode
        )
        val visitedHistory = snapshotVisitedHistoryLabels()
        val visitedHistorySignatures = snapshotVisitedHistorySignatures()

        return SmartNextRuntimeState(
            root = root,
            collect = collectResult,
            normalize = normalizeResult,
            currentPosition = currentPosition,
            visitedHistory = visitedHistory,
            visitedHistorySignatures = visitedHistorySignatures,
            focusNodeByNode = focusNodeByNode
        )
    }

    private fun decideNextAction(state: SmartNextRuntimeState): NextActionDecision {
        return NextActionDecision(
            state = state,
            initialTarget = decideInitialNextTarget(state)
        )
    }

    private fun executeNextAction(decision: NextActionDecision): NextActionExecution {
        val state = decision.state
        return NextActionExecution(executeSmartNextPipeline(state, decision.initialTarget))
    }

    private fun verifyAndFinalizeNextAction(
        decision: NextActionDecision,
        execution: NextActionExecution
    ): TargetActionOutcome {
        Log.i(
            "A11Y_HELPER",
            "[SMART_NEXT][FINALIZE] nextIndex=${decision.initialTarget.nextIndex} success=${execution.outcome.success} reason=${execution.outcome.reason}"
        )
        return execution.outcome
    }

    private fun executeSmartNextPipeline(
        state: SmartNextRuntimeState,
        initialTarget: InitialNextTargetDecision
    ): TargetActionOutcome {
        val root = state.root
        val collectResult = state.collect
        val focusNodes = collectResult.focusNodes
        val traversalList = collectResult.traversalList
        val focusNodeByNode = state.focusNodeByNode
        val currentPosition = state.currentPosition
        val resolvedCurrent = currentPosition.resolvedCurrent
        val currentIndex = currentPosition.currentIndex
        val fallbackIndex = currentPosition.fallbackIndex
        var nextIndex = initialTarget.nextIndex
        val normalizeResult = state.normalize
        val screenRect = normalizeResult.screenRect
        val screenTop = normalizeResult.screenTop
        val screenBottom = normalizeResult.screenBottom
        val screenHeight = normalizeResult.screenHeight
        val effectiveBottom = normalizeResult.effectiveBottom
        val visitedHistory = state.visitedHistory
        val visitedHistorySignatureSnapshot = state.visitedHistorySignatures
        if (traversalList.isEmpty()) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Traversal list is empty, failing.")
            return TargetActionOutcome(false, "Traversal list is empty")
        }

        if (currentIndex != -1) {
            setLastRequestedFocusIndex(maxOf(lastRequestedFocusIndex, A11yStateStore.lastRequestedFocusIndex, currentIndex))
            setLastRequestedFocusIndex(maxOf(lastRequestedFocusIndex, currentIndex))
        }
        val selectionDecision = initialTarget.selectionDecision
        Log.i("A11Y_HELPER", "[SELECT_NEXT] currentIndex=${selectionDecision.currentIndex}, fallbackIndex=${selectionDecision.fallbackIndex}, lastRequestedFocusIndex=$lastRequestedFocusIndex, nextIndex=${selectionDecision.nextIndex}")
        Log.i("A11Y_HELPER", "[SMART_NEXT][GRID_TRACE] sequentialIndices current=$currentIndex next=$nextIndex total=${traversalList.size}")

        root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
            val cleared = focusedNode.performAction(AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
            val focusedBounds = Rect().also { focusedNode.getBoundsInScreen(it) }
            Log.i("A11Y_HELPER", "[SMART_NEXT] Cleared existing accessibility focus before next move: result=$cleared bounds=$focusedBounds")
        }

        if (currentIndex == -1 && fallbackIndex != -1) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Current node matching failed. Using fallback nextIndex based on vertical proximity.")
        }

        Log.i("A11Y_HELPER", "[SMART_NEXT] effectiveBottom=$effectiveBottom, screenBottom=$screenBottom")

        val findAndFocusContext = FindAndFocusPhaseContext(
            root = root,
            traversalList = traversalList,
            screenTop = screenTop,
            screenBottom = screenBottom,
            effectiveBottom = effectiveBottom,
            screenHeight = screenHeight,
            focusNodeByNode = focusNodeByNode,
            visitedHistory = visitedHistory,
            visitedHistorySignatures = visitedHistorySignatureSnapshot
        )
        val mainScrollContainer = findMainScrollContainer(root)
        val scrollableNode = findScrollableForwardAncestorCandidate(resolvedCurrent)
            ?: mainScrollContainer
            ?: findScrollableForwardCandidate(root)

        val lastIndex = traversalList.lastIndex
        val shouldHandleLastNodeGracePeriod = nextIndex !in traversalList.indices
        val shouldTerminateAtLastBottomBar = shouldTerminateAtLastBottomBar(
            traversalList = traversalList,
            currentIndex = currentIndex,
            lastIndex = lastIndex,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName }
        )

        if (shouldHandleLastNodeGracePeriod || currentIndex == lastIndex) {
            if (shouldTerminateAtLastBottomBar) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Last focused node is bottom bar and no next candidate. Terminating traversal to prevent loop.")
                return TargetActionOutcome(false, "reached_end")
            }

            val shouldScrollAtEnd = shouldScrollAtEndOfTraversal(
                currentIndex = currentIndex,
                nextIndex = nextIndex,
                traversalList = traversalList,
                scrollableNodeExists = scrollableNode != null
            )

            if (shouldScrollAtEnd && scrollableNode != null) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] End-of-traversal scroll allowed by policy -> attempting scroll first")
                val lastDesc = resolvedCurrent?.contentDescription?.toString()
                val preScrollAnchor = buildPreScrollAnchor(
                    focusNodes = focusNodes,
                    currentIndex = currentIndex,
                    resolvedCurrent = resolvedCurrent
                )
                val preScrollResult = executePreScrollIfNeeded(
                    scrollTarget = scrollableNode,
                    reason = "end_of_traversal"
                )
                if (!preScrollResult.success) {
                    if (currentIndex == lastIndex && currentIndex in traversalList.indices) {
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Ensuring last node focus visibility before termination")
                        val lastNode = traversalList[currentIndex]
                        lastNode.refresh()
                        lastNode.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
                        return TargetActionOutcome(false, "reached_end", lastNode)
                    }
                    return TargetActionOutcome(false, "failed")
                }

                val visibleHistory = collectVisibleHistory(
                    nodes = traversalList,
                    screenTop = screenTop,
                    screenBottom = screenBottom,
                    boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                    labelOf = { node ->
                        node.text?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                            ?: node.contentDescription?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                    },
                    isTopAppBarNodeOf = { node, bounds ->
                        isTopAppBarNode(
                            node.className?.toString(),
                            node.viewIdResourceName,
                            bounds,
                            screenTop,
                            screenHeight
                        )
                    },
                    isBottomNavigationBarNodeOf = { node, bounds ->
                        isBottomNavigationBarNode(
                            node.className?.toString(),
                            node.viewIdResourceName,
                            bounds,
                            screenBottom,
                            screenHeight
                        )
                    }
                )
                val visibleHistorySignatures = collectVisibleHistorySignatures(
                    nodes = traversalList,
                    screenTop = screenTop,
                    screenBottom = screenBottom,
                    boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                    labelOf = { node ->
                        node.text?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                            ?: node.contentDescription?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                    },
                    viewIdOf = { node -> node.viewIdResourceName },
                    isTopAppBarNodeOf = { node, bounds ->
                        isTopAppBarNode(
                            node.className?.toString(),
                            node.viewIdResourceName,
                            bounds,
                            screenTop,
                            screenHeight
                        )
                    },
                    isBottomNavigationBarNodeOf = { node, bounds ->
                        isBottomNavigationBarNode(
                            node.className?.toString(),
                            node.viewIdResourceName,
                            bounds,
                            screenBottom,
                            screenHeight
                        )
                    }
                )

                val service = A11yHelperService.instance
                val oldSnapshot = buildNodeTextSnapshot(traversalList)
                val newRoot = pollForUpdatedRoot(
                    service = service,
                    oldSnapshot = oldSnapshot,
                    fallbackRoot = root
                )
                if (newRoot == null) {
                    Log.e("A11Y_HELPER", "[SMART_NEXT] Root is null after scroll")
                    return TargetActionOutcome(false, "failed")
                }

                val refreshedList = buildFocusableTraversalList(newRoot)
                val refreshedSnapshot = buildNodeTextSnapshot(refreshedList)
                if (oldSnapshot == refreshedSnapshot) {
                    Log.i("A11Y_HELPER", "[SMART_NEXT] No scroll progress detected, terminating to prevent loop")
                    return TargetActionOutcome(false, "reached_end_no_scroll_progress")
                }
                val refreshedRect = Rect().also { newRoot.getBoundsInScreen(it) }
                val refreshedScreenBottom = refreshedRect.bottom
                val refreshedScreenHeight = (refreshedRect.bottom - refreshedRect.top).coerceAtLeast(1)
                val refreshedEffectiveBottom = calculateEffectiveBottom(
                    nodes = refreshedList,
                    screenTop = refreshedRect.top,
                    screenBottom = refreshedScreenBottom,
                    boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                    labelOf = { node ->
                        node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: node.viewIdResourceName
                    }
                )
                Log.i("A11Y_HELPER", "[SMART_NEXT] Refreshed node count=${refreshedList.size}")
                return findAndFocusFirstContent(
                    context = findAndFocusContext.copy(
                        traversalList = refreshedList,
                        screenTop = refreshedRect.top,
                        screenBottom = refreshedScreenBottom,
                        effectiveBottom = refreshedEffectiveBottom,
                        screenHeight = refreshedScreenHeight
                    ),
                    request = FindAndFocusRequest(
                        statusName = "scrolled",
                        isScrollAction = true,
                        excludeDesc = lastDesc,
                        startIndex = 0,
                        visibleHistory = visibleHistory,
                        visibleHistorySignatures = visibleHistorySignatures,
                        preScrollAnchor = preScrollAnchor
                    )
                )
            }

            if (shouldHandleLastNodeGracePeriod && currentIndex < lastIndex) {
                val graceIndex = currentIndex + 1
                if (graceIndex in traversalList.indices) {
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Next index overflowed after compensation; applying last-node grace focus at index $graceIndex")
                    return focusSequentiallyFromIndex(root, traversalList, graceIndex, screenTop, effectiveBottom, currentIndex, "moved")
                }
            }

            if (currentIndex == lastIndex && currentIndex in traversalList.indices) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Ensuring last node focus visibility before termination")
                val lastNode = traversalList[currentIndex]
                lastNode.refresh()
                lastNode.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
                Log.i("A11Y_HELPER", "[SMART_NEXT] Reached end of list, stopping traversal")
                return TargetActionOutcome(false, "reached_end", lastNode)
            }

            Log.i("A11Y_HELPER", "[SMART_NEXT] Reached end of list, stopping traversal")
            return TargetActionOutcome(false, "reached_end")
        }

        val nextNode = traversalList[nextIndex]
        val nextBounds = Rect().also { nextNode.getBoundsInScreen(it) }
        val nextIsBottomBar = isBottomNavigationBarNode(
            className = nextNode.className?.toString(),
            viewIdResourceName = nextNode.viewIdResourceName,
            boundsInScreen = nextBounds,
            screenBottom = screenBottom,
            screenHeight = screenHeight
        )
        if (nextIsBottomBar) {
            val intermediateTrailingContentIndex = findIntermediateContentCandidateBeforeBottomBar(
                traversalList = traversalList,
                currentIndex = currentIndex,
                bottomBarIndex = nextIndex,
                screenTop = screenTop,
                screenBottom = screenBottom,
                screenHeight = screenHeight,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                classNameOf = { node -> node.className?.toString() },
                viewIdOf = { node -> node.viewIdResourceName }
            )
            if (intermediateTrailingContentIndex != -1) {
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_NEXT] Found intermediate content before bottom bar at index=$intermediateTrailingContentIndex. Prioritizing it before bottom bar index=$nextIndex"
                )
                nextIndex = intermediateTrailingContentIndex
            }
        }

        val continuationContentLikelyBelowCurrentGrid = isContinuationContentLikelyBelowCurrentNode(
            traversalList = traversalList,
            currentIndex = currentIndex,
            nextIndex = nextIndex,
            screenTop = screenTop,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            effectiveBottom = effectiveBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName }
        )
        val contentTraversalCompleteBeforeBottomBar = nextIsBottomBar && isContentTraversalCompleteBeforeBottomBar(
            traversalList = traversalList,
            currentIndex = currentIndex,
            bottomBarIndex = nextIndex,
            screenTop = screenTop,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            effectiveBottom = effectiveBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName },
            isFixedUiOf = { node -> isFixedSystemUI(node, mainScrollContainer) },
            canScrollForwardHint = scrollableNode != null
        )
        if (contentTraversalCompleteBeforeBottomBar) {
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT] Current focus is the dynamic last content item before bottom bar. Skipping continuation pre-scroll and moving to bottom bar."
            )
            return focusOrSkip(root, traversalList, nextNode, screenTop, effectiveBottom, currentIndex, "moved_to_bottom_bar", nextIndex)
        }
        val rowOrGridContinuationDetected = hasContinuationPatternBelowCurrentNode(
            traversalList = traversalList,
            currentIndex = currentIndex,
            nextIndex = nextIndex,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName }
        )
        val shouldScrollBeforeBottomBar = shouldScrollBeforeBottomBar(
            traversalList = traversalList,
            currentIndex = currentIndex,
            nextIndex = nextIndex,
            screenTop = screenTop,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            effectiveBottom = effectiveBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName },
            canScrollForwardHint = scrollableNode != null
        )
        val isCurrentNearBottom = currentIndex in traversalList.indices &&
            isNearBottomEdge(bounds = Rect().also { traversalList[currentIndex].getBoundsInScreen(it) }, effectiveBottom = effectiveBottom)
        val continuationExistsBeforeBottomBar = nextIsBottomBar && hasContinuationContentBeforeBottomBar(
            traversalList = traversalList,
            currentIndex = currentIndex,
            bottomBarIndex = nextIndex,
            screenTop = screenTop,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            classNameOf = { node -> node.className?.toString() },
            viewIdOf = { node -> node.viewIdResourceName }
        )
        val forcePreScrollBeforeBottomBar = shouldForcePreScrollBeforeBottomBar(
            shouldScrollBeforeBottomBar = shouldScrollBeforeBottomBar,
            continuationContentLikelyBelowCurrentGrid = continuationContentLikelyBelowCurrentGrid || rowOrGridContinuationDetected
        )
        val bottomBarEntryDecision = decideBottomBarEntry(
            nextIsBottomBar = nextIsBottomBar,
            scrollableNodeExists = scrollableNode != null,
            contentTraversalCompleteBeforeBottomBar = contentTraversalCompleteBeforeBottomBar,
            continuationLikely = continuationContentLikelyBelowCurrentGrid,
            rowOrGridContinuationDetected = rowOrGridContinuationDetected,
            continuationExistsBeforeBottomBar = continuationExistsBeforeBottomBar,
            isCurrentNearBottom = isCurrentNearBottom,
            forcePreScrollBeforeBottomBar = forcePreScrollBeforeBottomBar
        )
        val scrollDecision = ScrollDecision(
            shouldPreScroll = bottomBarEntryDecision.requirePreScroll,
            reason = bottomBarEntryDecision.reason
        )
        Log.i(
            "A11Y_HELPER",
            "[BOTTOM_BAR] allow=${bottomBarEntryDecision.allowBottomBarEntry} preScroll=${scrollDecision.shouldPreScroll} reason=${scrollDecision.reason}"
        )

        if (nextIsBottomBar && continuationContentLikelyBelowCurrentGrid) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Continuation content likely -> forcing pre-scroll before bottom bar")
        }

        if (scrollDecision.shouldPreScroll) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Scrollable container found for smart scroll.")
            Log.i("A11Y_HELPER", "[SMART_NEXT] Next node is bottom bar and continuation/defer condition matched -> attempting scroll first")
            val scrollTarget = scrollableNode ?: run {
                Log.w("A11Y_HELPER", "[SMART_NEXT] Scroll target became null unexpectedly; falling back to bottom bar move.")
                return focusOrSkip(root, traversalList, nextNode, screenTop, effectiveBottom, currentIndex, "moved_to_bottom_bar_direct", nextIndex)
            }
            val lastDesc = resolvedCurrent?.contentDescription?.toString()
            val preScrollAnchor = buildPreScrollAnchor(
                focusNodes = focusNodes,
                currentIndex = currentIndex,
                resolvedCurrent = resolvedCurrent
            )
            val preScrollRawVisibleNodes = collectRawVisibleNodes(root)
            val preScrollFocusedBounds = resolvedCurrent?.let { Rect().also(it::getBoundsInScreen) }
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT][PROGRESS_DEBUG] preScroll anchor=${describePreScrollAnchor(preScrollAnchor)}"
            )
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT][PROGRESS_DEBUG] preScroll focused=${describeNodeForProgressLog(resolvedCurrent, preScrollFocusedBounds)}"
            )
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT][PROGRESS_DEBUG] preRawCount=${preScrollRawVisibleNodes.size} preTraversalCount=${traversalList.size}"
            )
            val preScrollResult = executePreScrollIfNeeded(
                scrollTarget = scrollTarget,
                reason = "bottom_bar_guard"
            )
            if (!preScrollResult.success) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Scroll failed (end of list), moving to bottom bar.")
                return focusOrSkip(root, traversalList, nextNode, screenTop, effectiveBottom, currentIndex, "moved_to_bottom_bar_direct", nextIndex)
            }

            val visibleHistory = collectVisibleHistory(
                nodes = traversalList,
                screenTop = screenTop,
                screenBottom = screenBottom,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                labelOf = { node ->
                    node.text?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                        ?: node.contentDescription?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                },
                isTopAppBarNodeOf = { node, bounds ->
                    isTopAppBarNode(
                        node.className?.toString(),
                        node.viewIdResourceName,
                        bounds,
                        screenTop,
                        screenHeight
                    )
                },
                isBottomNavigationBarNodeOf = { node, bounds ->
                    isBottomNavigationBarNode(
                        node.className?.toString(),
                        node.viewIdResourceName,
                        bounds,
                        screenBottom,
                        screenHeight
                    )
                }
            )
            val visibleHistorySignatures = collectVisibleHistorySignatures(
                nodes = traversalList,
                screenTop = screenTop,
                screenBottom = screenBottom,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                labelOf = { node ->
                    node.text?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                        ?: node.contentDescription?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                },
                viewIdOf = { node -> node.viewIdResourceName },
                isTopAppBarNodeOf = { node, bounds ->
                    isTopAppBarNode(
                        node.className?.toString(),
                        node.viewIdResourceName,
                        bounds,
                        screenTop,
                        screenHeight
                    )
                },
                isBottomNavigationBarNodeOf = { node, bounds ->
                    isBottomNavigationBarNode(
                        node.className?.toString(),
                        node.viewIdResourceName,
                        bounds,
                        screenBottom,
                        screenHeight
                    )
                }
            )

            val service = A11yHelperService.instance
            val oldSnapshot = buildNodeTextSnapshot(traversalList)
            val refreshedRoot = pollForUpdatedRoot(
                service = service,
                oldSnapshot = oldSnapshot,
                fallbackRoot = root
            )
            val refreshedTraversal = refreshedRoot?.let { buildFocusableTraversalList(it) }.orEmpty()
            val refreshedSnapshot = buildNodeTextSnapshot(refreshedTraversal)
            val postRawVisibleNodes = refreshedRoot?.let(::collectRawVisibleNodes).orEmpty()
            val anchorCandidateIndex = preScrollAnchor?.let { anchor ->
                resolveAnchorIndexInRefreshedTraversal(
                    traversalList = refreshedTraversal,
                    anchor = anchor,
                    boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                    viewIdOf = { node -> node.viewIdResourceName },
                    textOf = { node -> node.text?.toString() },
                    contentDescriptionOf = { node -> node.contentDescription?.toString() }
                )
            } ?: -1
            val anchorCandidateNode = refreshedTraversal.getOrNull(anchorCandidateIndex)
            val anchorCandidateBounds = anchorCandidateNode?.let { Rect().also(it::getBoundsInScreen) }
            val anchorSimilarCandidateFound = preScrollAnchor != null && anchorCandidateIndex >= 0
            val privacyNoticeNode = refreshedTraversal.firstOrNull {
                it.viewIdResourceName?.contains("item_privacy_notice", ignoreCase = true) == true
            }
            val privacyNoticeBounds = privacyNoticeNode?.let { Rect().also(it::getBoundsInScreen) }
            val rawPrivacyNoticeNode = postRawVisibleNodes.firstOrNull {
                it.viewId?.contains("item_privacy_notice", ignoreCase = true) == true
            }
            val privacyNoticePromotionApplied = rawPrivacyNoticeNode != null && privacyNoticeNode != null
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT][PROGRESS_DEBUG] postRawCount=${postRawVisibleNodes.size} postTraversalCount=${refreshedTraversal.size}"
            )
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT][PROGRESS_DEBUG] postAnchorCandidate found=$anchorSimilarCandidateFound index=$anchorCandidateIndex anchorShift before=${formatBoundsForLog(preScrollAnchor?.bounds)} after=${formatBoundsForLog(anchorCandidateBounds)}"
            )
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT][PROGRESS_DEBUG] privacyNotice found=${privacyNoticeNode != null} bounds=${formatBoundsForLog(privacyNoticeBounds)} clickable=${privacyNoticeNode?.isClickable} focusable=${privacyNoticeNode?.isFocusable} visible=${privacyNoticeNode?.isVisibleToUser}"
            )
            Log.i("A11Y_HELPER", "[SMART_NEXT] privacy_notice_candidate_promotion applied=$privacyNoticePromotionApplied")
            if (oldSnapshot == refreshedSnapshot) {
                val preRawSignature = preScrollRawVisibleNodes.map { raw ->
                    "${raw.viewId}|${raw.label}|${raw.bounds.left},${raw.bounds.top},${raw.bounds.right},${raw.bounds.bottom}"
                }.toSet()
                val postRawSignature = postRawVisibleNodes.map { raw ->
                    "${raw.viewId}|${raw.label}|${raw.bounds.left},${raw.bounds.top},${raw.bounds.right},${raw.bounds.bottom}"
                }.toSet()
                val preTraversalViewIds = traversalList.mapNotNull { it.viewIdResourceName }.toSet()
                val postTraversalViewIds = refreshedTraversal.mapNotNull { it.viewIdResourceName }.toSet()
                val rawTreeChanged = preRawSignature != postRawSignature
                val traversalChanged = traversalList.size != refreshedTraversal.size || oldSnapshot != refreshedSnapshot
                val anchorShifted = preScrollAnchor != null && anchorCandidateBounds != null && preScrollAnchor.bounds != anchorCandidateBounds
                val successorCandidateIndex = if (preScrollAnchor != null) {
                    val preTraversalShortViewIds = traversalList.mapNotNull { it.viewIdResourceName?.substringAfterLast('/')?.trim() }.toSet()
                    val promotedRawOnlyViewIds = postRawVisibleNodes
                        .mapNotNull { raw -> raw.viewId?.substringAfterLast('/')?.trim() }
                        .filter { shortId ->
                            isSettingsRowViewId(shortId) &&
                                !preTraversalShortViewIds.contains(shortId) &&
                                preScrollRawVisibleNodes.none { it.viewId?.substringAfterLast('/')?.trim() == shortId }
                        }
                        .toSet()
                    selectContinuationCandidateAfterScroll(
                        traversalList = refreshedTraversal,
                        startIndex = 0,
                        visibleHistory = visibleHistory,
                        visibleHistorySignatures = visibleHistorySignatures,
                        visitedHistory = visitedHistory,
                        visitedHistorySignatures = visitedHistorySignatureSnapshot,
                        screenTop = Rect().also { (refreshedRoot ?: root).getBoundsInScreen(it) }.top,
                        screenBottom = Rect().also { (refreshedRoot ?: root).getBoundsInScreen(it) }.bottom,
                        screenHeight = (Rect().also { (refreshedRoot ?: root).getBoundsInScreen(it) }.height()).coerceAtLeast(1),
                        boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                        classNameOf = { node -> node.className?.toString() },
                        viewIdOf = { node -> node.viewIdResourceName },
                        isContentNodeOf = { node ->
                            isContentNode(
                                node = node,
                                bounds = Rect().also { node.getBoundsInScreen(it) },
                                screenTop = Rect().also { (refreshedRoot ?: root).getBoundsInScreen(it) }.top,
                                screenBottom = Rect().also { (refreshedRoot ?: root).getBoundsInScreen(it) }.bottom,
                                screenHeight = (Rect().also { (refreshedRoot ?: root).getBoundsInScreen(it) }.height()).coerceAtLeast(1),
                                mainScrollContainer = mainScrollContainer
                            )
                        },
                        clickableOf = { node -> node.isClickable },
                        focusableOf = { node -> node.isFocusable },
                        descendantLabelOf = { node -> recoverDescendantLabel(node) },
                        promotedViewIds = promotedRawOnlyViewIds,
                        preScrollAnchor = preScrollAnchor,
                        preScrollAnchorBottom = preScrollAnchor.bounds.bottom,
                        labelOf = { node ->
                            node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                                ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                        }
                    )
                } else {
                    -1
                }
                val successorFound = successorCandidateIndex >= 0
                val newViewIdFound = postTraversalViewIds.any { it !in preTraversalViewIds }
                val preBottomMax = preScrollRawVisibleNodes.maxOfOrNull { it.bounds.bottom } ?: Int.MIN_VALUE
                val postBottomMax = postRawVisibleNodes.maxOfOrNull { it.bounds.bottom } ?: Int.MIN_VALUE
                val bottomAreaExpanded = postBottomMax > preBottomMax
                val analysis = analyzePostScrollState(
                    treeChanged = rawTreeChanged || traversalChanged,
                    anchorMaintained = anchorShifted || successorFound,
                    newlyExposedCandidateExists = newViewIdFound || bottomAreaExpanded
                )
                val noProgressReason = analysis.reason
                val successorCandidatesSummary = refreshedTraversal.take(8).joinToString(separator = " | ") { node ->
                    val bounds = Rect().also { node.getBoundsInScreen(it) }
                    val label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                        ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                        ?: "<no-label>"
                    "label=${label.replace("\n", " ")} viewId=${node.viewIdResourceName} bounds=$bounds"
                }
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_NEXT][PROGRESS_DEBUG] rawTreeChanged=$rawTreeChanged traversalChanged=$traversalChanged anchorShifted=$anchorShifted successorFound=$successorFound newViewIdFound=$newViewIdFound bottomAreaExpanded=$bottomAreaExpanded"
                )
                Log.i("A11Y_HELPER", "[SMART_NEXT][PROGRESS_DEBUG] noProgress=${analysis.noProgress} reason=$noProgressReason")
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_NEXT][PROGRESS_DEBUG] fallbackBeforeBottomBar successorSearchAttempted=${preScrollAnchor != null} successorCandidates=$successorCandidatesSummary"
                )
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_NEXT][PROGRESS_DEBUG] fallbackReason=no_scroll_progress_after_bottom_bar_pre_scroll"
                )
                val noProgressBottomBarDecision = decideBottomBarEntry(
                    nextIsBottomBar = true,
                    scrollableNodeExists = true,
                    contentTraversalCompleteBeforeBottomBar = false,
                    continuationLikely = false,
                    rowOrGridContinuationDetected = false,
                    continuationExistsBeforeBottomBar = false,
                    isCurrentNearBottom = false,
                    forcePreScrollBeforeBottomBar = false,
                    noProgressAfterScroll = true
                )
                Log.i(
                    "A11Y_HELPER",
                    "[BOTTOM_BAR] allow=${noProgressBottomBarDecision.allowBottomBarEntry} preScroll=${noProgressBottomBarDecision.requirePreScroll} reason=${noProgressBottomBarDecision.reason}"
                )
                Log.i("A11Y_HELPER", "[SMART_NEXT] No scroll progress detected after bottom-bar pre-scroll. Trying bottom bar fallback focus.")
                val fallbackOutcome = focusBottomBarAfterNoProgress(
                    root = root,
                    traversalList = traversalList,
                    bottomBarNode = nextNode,
                    bottomBarIndex = nextIndex
                )
                if (fallbackOutcome.success) {
                    return fallbackOutcome
                }
                syncLastRequestedFocusIndexToCurrentFocus(root, traversalList)
                return TargetActionOutcome(false, "reached_end_no_scroll_progress", fallbackOutcome.target)
            }
            val refreshedRect = Rect().also { (refreshedRoot ?: root).getBoundsInScreen(it) }
            val refreshedTop = refreshedRect.top
            val refreshedBottom = refreshedRect.bottom
            val refreshedHeight = (refreshedBottom - refreshedTop).coerceAtLeast(1)
            val refreshedEffectiveBottom = calculateEffectiveBottom(
                nodes = refreshedTraversal,
                screenTop = refreshedTop,
                screenBottom = refreshedBottom,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                labelOf = { node ->
                    node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                        ?: node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                        ?: node.viewIdResourceName
                }
            )
            val outcome = findAndFocusFirstContent(
                context = findAndFocusContext.copy(
                    traversalList = refreshedTraversal,
                    screenTop = refreshedTop,
                    screenBottom = refreshedBottom,
                    effectiveBottom = refreshedEffectiveBottom,
                    screenHeight = refreshedHeight
                ),
                request = FindAndFocusRequest(
                    statusName = "scrolled",
                    isScrollAction = true,
                    excludeDesc = lastDesc,
                    startIndex = 0,
                    visibleHistory = visibleHistory,
                    visibleHistorySignatures = visibleHistorySignatures,
                    allowLooping = false,
                    preScrollAnchor = preScrollAnchor
                )
            )
            if (outcome.success) {
                return outcome
            }
            if (outcome.reason == "continuation_candidate_unresolved") {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Intended continuation candidate unresolved after scroll; bottom bar fallback is blocked")
                return TargetActionOutcome(false, "failed")
            }
            Log.i("A11Y_HELPER", "[SMART_NEXT] No continuation content after scroll -> allowing bottom bar")
            val bottomBarOutcome = focusOrSkip(root, traversalList, nextNode, screenTop, effectiveBottom, currentIndex, "moved_to_bottom_bar", nextIndex)
            return if (bottomBarOutcome.success) {
                TargetActionOutcome(true, "moved_to_bottom_bar", nextNode)
            } else {
                bottomBarOutcome
            }
        }

        if (nextIsBottomBar && bottomBarEntryDecision.allowBottomBarEntry) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Next node is bottom bar, but hidden-content likelihood is low. Skipping pre-scroll.")
        }

        Log.i("A11Y_HELPER", "[SMART_NEXT] Performing regular next navigation")
        return focusSequentiallyFromIndex(root, traversalList, nextIndex, screenTop, effectiveBottom, currentIndex, "moved")
    }

    private fun decideInitialNextTarget(state: SmartNextRuntimeState): InitialNextTargetDecision {
        val traversalList = state.collect.traversalList
        val currentIndex = state.currentPosition.currentIndex
        val fallbackIndex = state.currentPosition.fallbackIndex
        var nextIndex = state.currentPosition.nextIndex

        if (currentIndex in traversalList.indices) {
            val currentBounds = Rect().also { traversalList[currentIndex].getBoundsInScreen(it) }
            val immediateCandidateIndex = currentIndex + 1
            if (nextIndex == immediateCandidateIndex) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Preserving immediate candidate at index=$nextIndex without duplicate-skip compensation")
            } else {
                nextIndex = skipCoordinateDuplicateTraversalIndices(
                    nodes = traversalList,
                    currentBounds = currentBounds,
                    startIndex = nextIndex,
                    boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                    onSkip = { skippedIndex, advancedIndex ->
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping invisible duplicate at index $skippedIndex")
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping coordinate duplicate: jumping from $skippedIndex to $advancedIndex")
                    }
                )
            }
        }

        return InitialNextTargetDecision(
            nextIndex = nextIndex,
            selectionDecision = SelectionDecision(
                currentIndex = currentIndex,
                fallbackIndex = fallbackIndex,
                nextIndex = nextIndex
            )
        )
    }

    private fun findAndFocusFirstContent(
        context: FindAndFocusPhaseContext,
        request: FindAndFocusRequest
    ): TargetActionOutcome {
        val root = context.root
        val traversalList = context.traversalList
        val screenTop = context.screenTop
        val screenBottom = context.screenBottom
        val effectiveBottom = context.effectiveBottom
        val screenHeight = context.screenHeight
        val focusNodeByNode = context.focusNodeByNode
        val visitedHistory = context.visitedHistory
        val visitedHistorySignatures = context.visitedHistorySignatures

        val statusName = request.statusName
        val isScrollAction = request.isScrollAction
        val excludeDesc = request.excludeDesc
        val startIndex = request.startIndex
        val visibleHistory = request.visibleHistory
        val visibleHistorySignatures = request.visibleHistorySignatures
        val allowLooping = request.allowLooping
        val preScrollAnchor = request.preScrollAnchor

        val excludedIndex = findIndexByDescription(
            nodes = traversalList,
            descriptionOf = {
                it.contentDescription?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                    ?: it.text?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
            },
            excludeDesc = excludeDesc
        )
        val localMainScrollContainer = findMainScrollContainer(
            nodes = traversalList,
            isScrollable = { it.isScrollable },
            boundsOf = { candidate -> Rect().also { candidate.getBoundsInScreen(it) } }
        )

        val traversalStartIndex = if (isScrollAction) {
            startIndex.coerceAtLeast(0)
        } else {
            if (excludedIndex != -1) excludedIndex + 1 else startIndex.coerceAtLeast(0)
        }
        var skippedExcludedNode = false
        var focusedAny = false
        var focusAttempted = false
        var focusedOutcome: TargetActionOutcome? = null

        if (excludedIndex != -1) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Excluded node found at index=$excludedIndex. Starting traversal from index=$traversalStartIndex")
        } else if (!excludeDesc.isNullOrBlank()) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Excluded node not found. Starting traversal from beginning with top-area guard")
        }

        val resolvedAnchorIndex = if (isScrollAction && preScrollAnchor != null) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Using pre-scroll anchor continuity")
            resolveAnchorIndexInRefreshedTraversal(
                traversalList = traversalList,
                anchor = preScrollAnchor,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                viewIdOf = { node -> node.viewIdResourceName },
                textOf = { node -> node.text?.toString() },
                contentDescriptionOf = { node -> node.contentDescription?.toString() }
            ).also { index ->
                Log.i("A11Y_HELPER", "[SMART_NEXT] Resolved anchor in refreshed traversal at index=$index")
            }
        } else {
            -1
        }
        val continuationFallbackAttempted = isScrollAction && preScrollAnchor != null && resolvedAnchorIndex == -1
        var continuationFallbackFailed = false
        val fallbackBelowAnchorIndex = if (continuationFallbackAttempted) {
            Log.i("A11Y_HELPER", "[POST_SCROLL] Anchor exact match failed; using continuation fallback")
            logPostScrollRawVsTraversalSnapshot(root, traversalList, focusNodeByNode)
            traversalList.forEachIndexed { index, node ->
                val bounds = Rect().also { node.getBoundsInScreen(it) }
                val focusedNode = focusNodeByNode[node]
                val label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: focusedNode?.mergedLabel?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: recoverDescendantLabel(node)?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: "<no-label>"
                val mergedLabel = focusedNode?.mergedLabel?.replace("\n", " ") ?: "<none>"
                val talkbackLabel = focusedNode?.contentDescription?.replace("\n", " ")
                    ?: node.contentDescription?.toString()?.replace("\n", " ")
                    ?: "<none>"
                val inVisibleHistory = isInVisibleHistory(
                    label = label,
                    viewId = node.viewIdResourceName,
                    bounds = bounds,
                    visibleHistory = visibleHistory,
                    visibleHistorySignatures = visibleHistorySignatures
                )
                val inVisitedHistory = isInVisitedHistory(
                    label = label,
                    viewId = node.viewIdResourceName,
                    bounds = bounds,
                    visitedHistory = visitedHistory,
                    visitedHistorySignatures = visitedHistorySignatures
                )
                if (!inVisitedHistory) {
                    logVisitedHistorySkip(
                        reason = "candidate only / post-scroll extraction",
                        label = label,
                        viewId = node.viewIdResourceName,
                        bounds = bounds
                    )
                }
                val isTopBar = isTopAppBarNode(
                    className = node.className?.toString(),
                    viewIdResourceName = node.viewIdResourceName,
                    boundsInScreen = bounds,
                    screenTop = screenTop,
                    screenHeight = screenHeight
                )
                val isBottomBar = isBottomNavigationBarNode(
                    className = node.className?.toString(),
                    viewIdResourceName = node.viewIdResourceName,
                    boundsInScreen = bounds,
                    screenBottom = screenBottom,
                    screenHeight = screenHeight
                )
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_NEXT] POST_SCROLL_CANDIDATE index=$index label=${label.replace("\n", " ")} mergedLabel=$mergedLabel talkbackLabel=$talkbackLabel viewId=${node.viewIdResourceName} className=${node.className} clickable=${node.isClickable} focusable=${node.isFocusable} bounds=$bounds visibleHistory=$inVisibleHistory visitedHistory=$inVisitedHistory isTopAppBar=$isTopBar isBottomNav=$isBottomBar"
                )
            }
            preScrollAnchor?.let { anchor ->
                val traversalViewIdSet = traversalList.mapNotNull { it.viewIdResourceName?.substringAfterLast('/')?.trim() }.toSet()
                val promotedRawOnlyViewIds = collectRawVisibleNodes(root)
                    .mapNotNull { raw -> raw.viewId?.substringAfterLast('/')?.trim() }
                    .filter { shortId -> isSettingsRowViewId(shortId) && !traversalViewIdSet.contains(shortId) }
                    .toSet()
                selectContinuationCandidateAfterScroll(
                    traversalList = traversalList,
                    startIndex = 0,
                    visibleHistory = visibleHistory,
                    visibleHistorySignatures = visibleHistorySignatures,
                    visitedHistory = visitedHistory,
                    visitedHistorySignatures = visitedHistorySignatures,
                    screenTop = screenTop,
                    screenBottom = screenBottom,
                    screenHeight = screenHeight,
                    boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                    classNameOf = { node -> node.className?.toString() },
                    viewIdOf = { node -> node.viewIdResourceName },
                    isContentNodeOf = { node ->
                        isContentNode(
                            node = node,
                            bounds = Rect().also { node.getBoundsInScreen(it) },
                            screenTop = screenTop,
                            screenBottom = screenBottom,
                            screenHeight = screenHeight,
                            mainScrollContainer = localMainScrollContainer
                        )
                    },
                    clickableOf = { node -> node.isClickable },
                    focusableOf = { node -> node.isFocusable },
                    descendantLabelOf = { node -> recoverDescendantLabel(node) },
                    promotedViewIds = promotedRawOnlyViewIds,
                    preScrollAnchor = anchor,
                    preScrollAnchorBottom = anchor.bounds.bottom,
                    labelOf = { node ->
                        node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: focusNodeByNode[node]?.mergedLabel?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: recoverDescendantLabel(node)?.trim().takeUnless { it.isNullOrEmpty() }
                    }
                ).also { candidateIndex ->
                    val analysis = analyzePostScrollState(
                        treeChanged = true,
                        anchorMaintained = true,
                        newlyExposedCandidateExists = candidateIndex >= 0
                    )
                    val selection = selectPostScrollContinuationCandidate(candidateIndex, analysis)
                    if (selection.accepted) {
                        val candidateNode = traversalList[candidateIndex]
                        val candidateLabel = candidateNode.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: candidateNode.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: focusNodeByNode[candidateNode]?.mergedLabel?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: recoverDescendantLabel(candidateNode)?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: "<no-label>"
                        Log.i(
                            "A11Y_HELPER",
                            "[SMART_NEXT] Selected new post-scroll content candidate index=$candidateIndex label=${candidateLabel.replace("\n", " ")} reason=${selection.reasonCode}"
                        )
                    } else {
                        continuationFallbackFailed = true
                        Log.i("A11Y_HELPER", "[POST_SCROLL] Continuation fallback exhausted reason=${selection.reasonCode}")
                        Log.i("A11Y_HELPER", "[SMART_NEXT] No new continuation content found; allowing bottom bar")
                    }
                }
            } ?: -1
        } else {
            -1
        }
        val postScrollPlan = decidePostScrollContinuationPlan(
            resolvedAnchorIndex = resolvedAnchorIndex,
            fallbackBelowAnchorIndex = fallbackBelowAnchorIndex,
            traversalStartIndex = traversalStartIndex,
            traversalSize = traversalList.size,
            continuationFallbackFailed = continuationFallbackFailed
        )
        val anchorStartIndex = postScrollPlan.anchorStartIndex
        if (isScrollAction && preScrollAnchor != null) {
            if (postScrollPlan.skipGeneralScan) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping general post-scroll scan because continuation fallback failed")
            } else {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting post-anchor continuation candidate index=$anchorStartIndex")
            }
        }

        for (index in anchorStartIndex until traversalList.size) {
            val node = traversalList[index]
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            var label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: "<no-label>"
            if (isScrollAction && preScrollAnchor != null && resolvedAnchorIndex >= 0 && index <= resolvedAnchorIndex) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping resurfaced pre-anchor item after scroll: $label")
                continue
            }
            val currentFocusedBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
                Rect().also { focusedNode.getBoundsInScreen(it) }
            }
            Log.i(
                "A11Y_HELPER",
                "[SMART_DEBUG] Index:$index, Label:${label.replace("\n", " ")}, Y_Bottom:${bounds.bottom}, Eff_Bottom:$effectiveBottom, InHistory:${visibleHistory.contains(label)}"
            )
            val isFallbackSelectedContinuationCandidate =
                preScrollAnchor != null &&
                    isScrollAction &&
                    resolvedAnchorIndex == -1 &&
                    fallbackBelowAnchorIndex >= 0 &&
                    index == fallbackBelowAnchorIndex
            if (isFallbackSelectedContinuationCandidate && currentFocusedBounds == bounds) {
                if (label == "<no-label>") {
                    recoverDescendantLabel(node)?.let { recoveredLabel ->
                        label = recoveredLabel
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Resolved descendant label for continuation target: $recoveredLabel")
                    }
                }
                Log.i("A11Y_HELPER", "[SMART_NEXT] Continuation candidate already focused after scroll -> treating as moved")
                Log.i("A11Y_HELPER", "[SMART_NEXT] Bottom bar fallback blocked because continuation candidate is already focused")
                recordVisitedFocus(node, label, reason = "already_focused_continuation_target")
                return TargetActionOutcome(true, "moved", node)
            }
            if (isFallbackSelectedContinuationCandidate) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping duplicate-bounds rule for fallback-selected continuation candidate")
            }
            if (shouldSkipDuplicateBoundsCandidate(
                    currentFocusedBounds = currentFocusedBounds,
                    candidateBounds = bounds,
                    isScrollAction = isScrollAction,
                    skipForFallbackSelectedContinuationCandidate = isFallbackSelectedContinuationCandidate
                )
            ) {
                val duplicateReason = if (isScrollAction) "scroll duplicate bounds" else "strict duplicate bounds precheck"
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_NEXT] Skipping candidate with identical bounds to current focus at index=$index label=$label reason=$duplicateReason"
                )
                continue
            }
            if (isNodePhysicallyOffScreen(bounds, screenTop, screenBottom)) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping off-screen node: $label")
                continue
            }
            val isTopBar = isTopAppBarNode(
                node.className?.toString(),
                node.viewIdResourceName,
                bounds,
                screenTop,
                screenHeight
            )
            val isBottomBar = isBottomNavigationBarNode(
                node.className?.toString(),
                node.viewIdResourceName,
                bounds,
                screenBottom,
                screenHeight
            )
            val isFixedUi = isFixedSystemUI(node, localMainScrollContainer)
            val isInsideMainScrollContainer = localMainScrollContainer?.let { scrollContainer ->
                node == scrollContainer || isDescendantOf(scrollContainer, node) { candidate -> candidate.parent }
            } ?: false
            val isTopContent = isWithinTopContentArea(
                nodeTop = bounds.top,
                screenTop = screenTop,
                screenHeight = screenHeight
            )
            val canAcceptFallbackSelectedNoLabelCandidate = shouldAcceptFallbackSelectedNoLabelContinuationCandidate(
                isFallbackSelectedContinuationCandidate = isFallbackSelectedContinuationCandidate,
                isTopBar = isTopBar,
                isBottomBar = isBottomBar,
                bounds = bounds,
                screenTop = screenTop,
                effectiveBottom = effectiveBottom
            )
            if (label == "<no-label>" && canAcceptFallbackSelectedNoLabelCandidate) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Accepting fallback-selected <no-label> continuation candidate")
                val recoveredLabel = recoverDescendantLabel(node)
                if (recoveredLabel != null) {
                    label = recoveredLabel
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Resolved descendant label for continuation target: $recoveredLabel")
                    val recoveredInHistory = isInVisitedHistory(
                        label = recoveredLabel,
                        viewId = node.viewIdResourceName,
                        bounds = bounds,
                        visitedHistory = visitedHistory,
                        visitedHistorySignatures = visitedHistorySignatures
                    )
                    if (recoveredInHistory) {
                        Log.i("A11Y_HELPER", "[SMART_NEXT] candidate rejected: already visited")
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping resurfaced pre-scroll item: $recoveredLabel")
                        continue
                    }
                }
            }
            val isLastFocusedNode = (excludeDesc != null && label == excludeDesc)
            val inVisibleHistory = isInVisibleHistory(
                label = label,
                viewId = node.viewIdResourceName,
                bounds = bounds,
                visibleHistory = visibleHistory,
                visibleHistorySignatures = visibleHistorySignatures
            )
            val inVisitedHistory = isInVisitedHistory(
                label = label,
                viewId = node.viewIdResourceName,
                bounds = bounds,
                visitedHistory = visitedHistory,
                visitedHistorySignatures = visitedHistorySignatures
            )
            if (isScrollAction && preScrollAnchor != null && inVisibleHistory && !inVisitedHistory) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] candidate visibleHistory=true visitedHistory=false -> accepting continuation candidate")
                Log.i("A11Y_HELPER", "[SMART_NEXT] candidate not yet visited: allowing continuation target")
            }
            if (isScrollAction && isLastFocusedNode) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Strictly excluding last focused node even in top area: $label")
                continue
            }
            val shouldSkipHistory = shouldSkipHistoryNodeAfterScroll(
                isScrollAction = isScrollAction,
                inHistory = inVisitedHistory,
                isFixedUi = isFixedUi || isTopBar || isBottomBar,
                isInsideMainScrollContainer = isInsideMainScrollContainer,
                isTopArea = isTopContent
            )
            if (shouldSkipHistory || (isScrollAction && inVisitedHistory)) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] candidate rejected: already visited")
                Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping history node after scroll: $label")
                continue
            }
            if (preScrollAnchor != null &&
                isScrollAction &&
                bounds.top <= preScrollAnchor.bounds.bottom &&
                isTopLoopProneControlNode(
                    node = node,
                    bounds = bounds,
                    screenTop = screenTop,
                    screenHeight = screenHeight,
                    classNameOf = { candidate -> candidate.className?.toString() },
                    viewIdOf = { candidate -> candidate.viewIdResourceName }
                )
            ) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping top-loop-prone control during anchored continuation: $label")
                continue
            }
            if (preScrollAnchor != null &&
                isScrollAction &&
                label == "<no-label>" &&
                !canAcceptFallbackSelectedNoLabelCandidate &&
                isTopContent &&
                bounds.top <= preScrollAnchor.bounds.bottom
            ) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Evaluating <no-label> candidate in continuation context before treating as noise")
                val recoveredLabel = recoverDescendantLabel(node)
                if (recoveredLabel != null) {
                    label = recoveredLabel
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Resolved descendant label for continuation target: $recoveredLabel")
                    val recoveredInHistory = isInVisitedHistory(
                        label = recoveredLabel,
                        viewId = node.viewIdResourceName,
                        bounds = bounds,
                        visitedHistory = visitedHistory,
                        visitedHistorySignatures = visitedHistorySignatures
                    )
                    if (recoveredInHistory) {
                        Log.i("A11Y_HELPER", "[SMART_NEXT] candidate rejected: already visited")
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping resurfaced pre-scroll item: $recoveredLabel")
                        continue
                    }
                }
            }
            if (preScrollAnchor != null &&
                isScrollAction &&
                label == "<no-label>" &&
                !canAcceptFallbackSelectedNoLabelCandidate &&
                isTopContent &&
                bounds.top <= preScrollAnchor.bounds.bottom
            ) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping top <no-label> noise node")
                continue
            }
            if (excludedIndex == -1 &&
                !skippedExcludedNode &&
                shouldSkipExcludedNodeByDescription(
                    nodeDesc = node.contentDescription?.toString(),
                    excludeDesc = excludeDesc,
                    nodeBounds = bounds,
                    screenTop = screenTop,
                    screenHeight = screenHeight
                )
            ) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Excluding node with desc=$excludeDesc once after scroll.")
                skippedExcludedNode = true
                continue
            }

            if (!isTopBar && !isBottomBar) {
                val isBottomResidualFocus = shouldIgnoreBottomResidualFocus(
                    isAccessibilityFocused = node.isAccessibilityFocused,
                    nodeBounds = bounds,
                    screenBottom = screenBottom,
                    screenHeight = screenHeight
                )
                if (isBottomResidualFocus) {
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Ignoring stale bottom focused node and checking next candidate")
                    continue
                }

                Log.i("A11Y_HELPER", "[SMART_DEBUG] Attempting focus on Index:$index, AlreadyFocused:${node.isAccessibilityFocused}")
                focusAttempted = true
                focusedOutcome = performFocusWithVisibilityCheck(
                    root = root,
                    target = node,
                    screenTop = screenTop,
                    effectiveBottom = effectiveBottom,
                    status = statusName,
                    isScrollAction = isScrollAction,
                    traversalIndex = index,
                    traversalListSnapshot = traversalList,
                    currentFocusIndexHint = index - 1
                )
                if (focusedOutcome?.success == true) {
                    focusedAny = true
                    break
                }
                Log.w("A11Y_HELPER", "[SMART_NEXT] Node focus denied, trying next candidate...")
            }
        }

        if (focusedAny) {
            return focusedOutcome ?: TargetActionOutcome(false, "failed")
        }

        if (!focusedAny && isScrollAction && !focusAttempted) {
            if (fallbackBelowAnchorIndex >= 0) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Bottom bar fallback blocked because continuation candidate is already focused")
                return TargetActionOutcome(false, "continuation_candidate_unresolved")
            }
            Log.i("A11Y_HELPER", "[SMART_NEXT] No focusable candidates remain after history/skip filtering. Treating as reached_end")
            return TargetActionOutcome(false, "reached_end")
        }

        if (shouldTriggerLoopFallback(focusedAny, isScrollAction, excludeDesc)) {
            if (!allowLooping) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Loop fallback blocked because allowLooping=false")
                return TargetActionOutcome(false, "failed_no_new_content")
            }
            Log.i("A11Y_HELPER", "[SMART_NEXT] No content after scroll. Looping to first content.")
            Log.i("A11Y_HELPER", "[SMART_NEXT] Fallback loop triggered - resetting filters")
            return findAndFocusFirstContent(
                context = context,
                request = FindAndFocusRequest(
                    statusName = "looped",
                    isScrollAction = false,
                    excludeDesc = null,
                    startIndex = 0,
                    visibleHistory = emptySet(),
                    visibleHistorySignatures = emptySet(),
                    allowLooping = true,
                    preScrollAnchor = null
                )
            )
        }

        Log.e("A11Y_HELPER", "[SMART_NEXT] Failed to focus any valid content node (status=failed)")
        return TargetActionOutcome(false, "failed")
    }

    private fun executeFocusMove(
        root: AccessibilityNodeInfo,
        target: AccessibilityNodeInfo,
        screenTop: Int,
        effectiveBottom: Int,
        traversalList: List<AccessibilityNodeInfo>,
        currentFocusIndexHint: Int,
        status: String,
        traversalIndex: Int
    ): FocusExecutionResult {
        val outcome = performFocusWithVisibilityCheck(
            root = root,
            target = target,
            screenTop = screenTop,
            effectiveBottom = effectiveBottom,
            status = status,
            isScrollAction = false,
            traversalIndex = traversalIndex,
            traversalListSnapshot = traversalList,
            currentFocusIndexHint = currentFocusIndexHint
        )
        return verifyAndCommitFocusResult(outcome)
    }

    private fun verifyAndCommitFocusResult(outcome: TargetActionOutcome): FocusExecutionResult {
        val reasonCode = if (outcome.success) "accepted:focus_verified" else "rejected:focus_verify_failed"
        return FocusExecutionResult(outcome = outcome, reasonCode = reasonCode)
    }

    private fun focusOrSkip(
        root: AccessibilityNodeInfo,
        traversalList: List<AccessibilityNodeInfo>,
        target: AccessibilityNodeInfo,
        screenTop: Int,
        effectiveBottom: Int,
        currentIndex: Int,
        status: String,
        traversalIndex: Int = -1
    ): TargetActionOutcome {
        return executeFocusMove(
            root = root,
            target = target,
            screenTop = screenTop,
            effectiveBottom = effectiveBottom,
            traversalList = traversalList,
            currentFocusIndexHint = currentIndex,
            status = status,
            traversalIndex = traversalIndex
        ).outcome
    }

    private fun focusSequentiallyFromIndex(
        root: AccessibilityNodeInfo,
        traversalList: List<AccessibilityNodeInfo>,
        startIndex: Int,
        screenTop: Int,
        effectiveBottom: Int,
        currentIndex: Int,
        status: String
    ): TargetActionOutcome {
        if (startIndex !in traversalList.indices) {
            return TargetActionOutcome(false, "failed_no_candidate_after_snap_back")
        }
        return focusOrSkip(
            root = root,
            traversalList = traversalList,
            target = traversalList[startIndex],
            screenTop = screenTop,
            effectiveBottom = effectiveBottom,
            currentIndex = currentIndex,
            status = status,
            traversalIndex = startIndex
        )
    }

    private fun executePreScrollIfNeeded(
        scrollTarget: AccessibilityNodeInfo?,
        reason: String
    ): PreScrollResult {
        if (scrollTarget == null) {
            return PreScrollResult(
                attempted = false,
                success = false,
                reason = "scroll_target_missing:$reason"
            )
        }
        val scrolled = scrollTarget.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
        Log.i("A11Y_HELPER", "[PRE_SCROLL] ACTION_SCROLL_FORWARD result=$scrolled reason=$reason")
        return PreScrollResult(
            attempted = true,
            success = scrolled,
            reason = if (scrolled) "pre_scroll_succeeded:$reason" else "pre_scroll_failed:$reason"
        )
    }



    internal fun shouldSkipDuplicateBoundsCandidate(
        currentFocusedBounds: Rect?,
        candidateBounds: Rect,
        isScrollAction: Boolean,
        skipForFallbackSelectedContinuationCandidate: Boolean = false
    ): Boolean {
        if (skipForFallbackSelectedContinuationCandidate) return false
        if (currentFocusedBounds == null || currentFocusedBounds != candidateBounds) return false
        return true
    }

    private fun isContentNode(
        node: AccessibilityNodeInfo,
        bounds: Rect,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        mainScrollContainer: AccessibilityNodeInfo?
    ): Boolean {
        val isBottomNav = isBottomNavigationBarNode(
            className = node.className?.toString(),
            viewIdResourceName = node.viewIdResourceName,
            boundsInScreen = bounds,
            screenBottom = screenBottom,
            screenHeight = screenHeight
        )
        if (isBottomNav) return false
        val isTopBar = isTopAppBarNode(
            className = node.className?.toString(),
            viewIdResourceName = node.viewIdResourceName,
            boundsInScreen = bounds,
            screenTop = screenTop,
            screenHeight = screenHeight
        )
        if (isTopBar) return false
        if (isFixedSystemUI(node, mainScrollContainer)) return false
        val hasDescendantLabel = !recoverDescendantLabel(node).isNullOrBlank()
        val usableLabel = !node.contentDescription?.toString().isNullOrBlank() || !node.text?.toString().isNullOrBlank() || hasDescendantLabel
        val traversable = node.isVisibleToUser && !isNodePhysicallyOffScreen(bounds, screenTop, screenBottom)
        val interactive = node.isClickable || node.isFocusable || hasDescendantLabel
        val isContainerOnly = node == mainScrollContainer
        return traversable && interactive && usableLabel && !isContainerOnly
    }

    internal fun resolveNextTraversalIndexPreservingIntermediateCandidate(
        currentIndex: Int,
        fallbackIndex: Int,
        lastRequestedIndex: Int,
        traversalSize: Int,
        onPreserveIntermediate: ((Int) -> Unit)? = null,
        onForcedAdvance: ((Int) -> Unit)? = null
    ): Int {
        return when {
            currentIndex == -1 && fallbackIndex != -1 -> fallbackIndex
            currentIndex != -1 && lastRequestedIndex >= 0 && currentIndex < lastRequestedIndex -> {
                val intermediateCandidate = (currentIndex + 1).takeIf { it in 0 until traversalSize && it <= lastRequestedIndex }
                if (intermediateCandidate != null) {
                    onPreserveIntermediate?.invoke(intermediateCandidate)
                    intermediateCandidate
                } else {
                    val forcedIndex = lastRequestedIndex + 1
                    onForcedAdvance?.invoke(forcedIndex)
                    forcedIndex
                }
            }
            currentIndex != -1 && lastRequestedIndex >= 0 && currentIndex == lastRequestedIndex -> {
                val forcedIndex = lastRequestedIndex + 1
                onForcedAdvance?.invoke(forcedIndex)
                forcedIndex
            }
            lastRequestedIndex >= 0 -> maxOf(currentIndex + 1, lastRequestedIndex + 1)
            else -> currentIndex + 1
        }
    }

    internal fun selectSequentialNextCandidateIndex(
        currentIndex: Int,
        fallbackIndex: Int,
        lastRequestedIndex: Int,
        traversalSize: Int,
        onPreserveIntermediate: ((Int) -> Unit)? = null,
        onForcedAdvance: ((Int) -> Unit)? = null
    ): Int {
        return resolveNextTraversalIndexPreservingIntermediateCandidate(
            currentIndex = currentIndex,
            fallbackIndex = fallbackIndex,
            lastRequestedIndex = lastRequestedIndex,
            traversalSize = traversalSize,
            onPreserveIntermediate = onPreserveIntermediate,
            onForcedAdvance = onForcedAdvance
        )
    }

    private fun decideBottomBarEntry(
        nextIsBottomBar: Boolean,
        scrollableNodeExists: Boolean,
        contentTraversalCompleteBeforeBottomBar: Boolean,
        continuationLikely: Boolean,
        rowOrGridContinuationDetected: Boolean,
        continuationExistsBeforeBottomBar: Boolean,
        isCurrentNearBottom: Boolean,
        forcePreScrollBeforeBottomBar: Boolean,
        noProgressAfterScroll: Boolean = false
    ): BottomBarEntryDecision {
        if (!nextIsBottomBar) {
            return BottomBarEntryDecision(
                allowBottomBarEntry = false,
                requirePreScroll = false,
                reason = "next_is_not_bottom_bar"
            )
        }
        if (!scrollableNodeExists) {
            return BottomBarEntryDecision(
                allowBottomBarEntry = true,
                requirePreScroll = false,
                reason = "no_scrollable_container"
            )
        }
        if (noProgressAfterScroll) {
            return BottomBarEntryDecision(
                allowBottomBarEntry = true,
                requirePreScroll = false,
                reason = "no_progress_after_scroll"
            )
        }
        if (contentTraversalCompleteBeforeBottomBar) {
            return BottomBarEntryDecision(
                allowBottomBarEntry = true,
                requirePreScroll = false,
                reason = "content_continuation_exhausted"
            )
        }
        val continuationSignals = continuationLikely || rowOrGridContinuationDetected || continuationExistsBeforeBottomBar || isCurrentNearBottom
        if (forcePreScrollBeforeBottomBar || continuationSignals) {
            return BottomBarEntryDecision(
                allowBottomBarEntry = false,
                requirePreScroll = true,
                reason = "continuation_signal_detected"
            )
        }
        return BottomBarEntryDecision(
            allowBottomBarEntry = true,
            requirePreScroll = false,
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
                !isTopAppBarNode(classNameOf(node), viewIdOf(node), bounds, screenTop, screenHeight) &&
                    !isBottomNavigationBarNode(classNameOf(node), viewIdOf(node), bounds, screenBottom, screenHeight)
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
            !isTopAppBarNode(classNameOf(node), viewIdOf(node), bounds, screenTop, screenHeight) &&
                !isBottomNavigationBarNode(classNameOf(node), viewIdOf(node), bounds, screenBottom, screenHeight)
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

    internal fun <T> skipCoordinateDuplicateTraversalIndices(
        nodes: List<T>,
        currentBounds: Rect,
        startIndex: Int,
        boundsOf: (T) -> Rect,
        onSkip: ((Int, Int) -> Unit)? = null
    ): Int {
        var nextIndex = startIndex
        while (nextIndex in nodes.indices && boundsOf(nodes[nextIndex]) == currentBounds) {
            val skippedIndex = nextIndex
            nextIndex += 1
            onSkip?.invoke(skippedIndex, nextIndex)
        }
        return nextIndex
    }

    internal fun isNearBottomEdge(bounds: Rect, effectiveBottom: Int, thresholdPx: Int = 180): Boolean {
        return bounds.bottom >= (effectiveBottom - thresholdPx)
    }

    private fun buildPreScrollAnchor(
        focusNodes: List<FocusedNode>,
        currentIndex: Int,
        resolvedCurrent: AccessibilityNodeInfo?
    ): PreScrollAnchor? {
        val focusedNode = focusNodes.getOrNull(currentIndex)
        val node = focusedNode?.node ?: resolvedCurrent ?: return null
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        return PreScrollAnchor(
            viewIdResourceName = node.viewIdResourceName,
            mergedLabel = focusedNode?.mergedLabel?.trim(),
            talkbackLabel = focusedNode?.contentDescription?.trim(),
            text = focusedNode?.text?.trim() ?: node.text?.toString()?.trim(),
            contentDescription = node.contentDescription?.toString()?.trim(),
            bounds = bounds
        )
    }

    internal fun <T> resolveAnchorIndexInRefreshedTraversal(
        traversalList: List<T>,
        anchor: PreScrollAnchor,
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

    private fun normalizedLabelSimilarity(a: String?, b: String?): Float {
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

    private fun analyzePostScrollState(
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

    private fun selectPostScrollContinuationCandidate(
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
            analysis.newlyExposedCandidateExists -> "accepted:newly_exposed_after_scroll"
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
        isTopBar: Boolean,
        isBottomBar: Boolean,
        isContentNode: Boolean,
        inVisibleHistory: Boolean,
        inVisitedHistory: Boolean,
        isPostScrollTopContinuationCandidate: Boolean,
        isTrailingContinuationCandidate: Boolean,
        isPromotedRawOnlyCandidate: Boolean,
        isNewlyExposedBottomContent: Boolean,
        isOtherUnvisitedVisible: Boolean,
        isTopResurfacedAnchorCandidate: Boolean,
        rewoundBeforeAnchor: Boolean,
        isNewlyAvailableInteractiveCandidate: Boolean,
        focusable: Boolean?,
        isOutOfScreen: Boolean,
        isLogicalSuccessor: Boolean
    ): ContinuationCandidateEvaluation {
        val reasons = mutableListOf<String>()
        if (isTopBar) reasons += "rejected:top_app_bar"
        if (isBottomBar) reasons += "rejected:bottom_nav"
        if (!isContentNode) reasons += "rejected:not_content_node"
        if (focusable == false) reasons += "rejected:not_focusable"
        if (isOutOfScreen) reasons += "rejected:outside_content_bounds"
        if (isTopResurfacedAnchorCandidate) reasons += "rejected:top_resurfaced_anchor"
        if (inVisitedHistory && !isTrailingContinuationCandidate) reasons += "rejected:already_visited"
        if (rewoundBeforeAnchor && !isLogicalSuccessor && !isNewlyAvailableInteractiveCandidate) {
            reasons += "rejected:rewound_before_anchor"
        }

        val priority = when {
            isLogicalSuccessor -> 0
            !isTopResurfacedAnchorCandidate && !isTopBar && !isBottomBar && isContentNode && isNewlyAvailableInteractiveCandidate -> 1
            !isTopResurfacedAnchorCandidate && !isTopBar && !isBottomBar && isContentNode && isPostScrollTopContinuationCandidate -> 2
            !isTopResurfacedAnchorCandidate && !isTopBar && !isBottomBar && isContentNode && isTrailingContinuationCandidate -> 3
            !isTopResurfacedAnchorCandidate && !isTopBar && !isBottomBar && isContentNode && isPromotedRawOnlyCandidate -> 4
            !isTopResurfacedAnchorCandidate && !isTopBar && !isBottomBar && isContentNode && isNewlyExposedBottomContent -> 5
            !isTopResurfacedAnchorCandidate && !isTopBar && !isBottomBar && isContentNode && isOtherUnvisitedVisible && (!inVisibleHistory || !inVisitedHistory) -> 6
            else -> Int.MAX_VALUE
        }
        return ContinuationCandidateEvaluation(
            priority = if (reasons.isEmpty()) priority else Int.MAX_VALUE,
            rejectionReasons = reasons,
            isLogicalSuccessor = isLogicalSuccessor
        )
    }

    internal fun <T> findAnchorContinuationCandidateIndex(
        traversalList: List<T>,
        startIndex: Int,
        visibleHistory: Set<String>,
        visibleHistorySignatures: Set<VisibleHistorySignature>,
        visitedHistory: Set<String>,
        visitedHistorySignatures: Set<VisibleHistorySignature>,
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
        preScrollAnchor: PreScrollAnchor? = null,
        preScrollAnchorBottom: Int? = null,
        labelOf: (T) -> String?
    ): Int = selectContinuationCandidateAfterScroll(
        traversalList = traversalList,
        startIndex = startIndex,
        visibleHistory = visibleHistory,
        visibleHistorySignatures = visibleHistorySignatures,
        visitedHistory = visitedHistory,
        visitedHistorySignatures = visitedHistorySignatures,
        screenTop = screenTop,
        screenBottom = screenBottom,
        screenHeight = screenHeight,
        boundsOf = boundsOf,
        classNameOf = classNameOf,
        viewIdOf = viewIdOf,
        isContentNodeOf = isContentNodeOf,
        clickableOf = clickableOf,
        focusableOf = focusableOf,
        descendantLabelOf = descendantLabelOf,
        promotedViewIds = promotedViewIds,
        preScrollAnchor = preScrollAnchor,
        preScrollAnchorBottom = preScrollAnchorBottom,
        labelOf = labelOf
    )

    internal fun <T> selectContinuationCandidateAfterScroll(
        traversalList: List<T>,
        startIndex: Int,
        visibleHistory: Set<String>,
        visibleHistorySignatures: Set<VisibleHistorySignature>,
        visitedHistory: Set<String>,
        visitedHistorySignatures: Set<VisibleHistorySignature>,
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
        preScrollAnchor: PreScrollAnchor? = null,
        preScrollAnchorBottom: Int? = null,
        labelOf: (T) -> String?
    ): Int = selectPostScrollContinuationCandidateIndex(
        traversalList = traversalList,
        startIndex = startIndex,
        visibleHistory = visibleHistory,
        visibleHistorySignatures = visibleHistorySignatures,
        visitedHistory = visitedHistory,
        visitedHistorySignatures = visitedHistorySignatures,
        screenTop = screenTop,
        screenBottom = screenBottom,
        screenHeight = screenHeight,
        boundsOf = boundsOf,
        classNameOf = classNameOf,
        viewIdOf = viewIdOf,
        isContentNodeOf = isContentNodeOf,
        clickableOf = clickableOf,
        focusableOf = focusableOf,
        descendantLabelOf = descendantLabelOf,
        promotedViewIds = promotedViewIds,
        preScrollAnchor = preScrollAnchor,
        preScrollAnchorBottom = preScrollAnchorBottom,
        labelOf = labelOf
    )

    internal fun <T> selectPostScrollContinuationCandidateIndex(
        traversalList: List<T>,
        startIndex: Int,
        visibleHistory: Set<String>,
        visibleHistorySignatures: Set<VisibleHistorySignature>,
        visitedHistory: Set<String>,
        visitedHistorySignatures: Set<VisibleHistorySignature>,
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
        preScrollAnchor: PreScrollAnchor? = null,
        preScrollAnchorBottom: Int? = null,
        labelOf: (T) -> String?
    ): Int {
        if (traversalList.isEmpty()) return -1
        val normalizedAnchorViewId = preScrollAnchor?.viewIdResourceName?.substringAfterLast('/')?.trim()
        val expectedSuccessorViewId = normalizedAnchorViewId
            ?.let { SETTINGS_ROW_VIEW_ID_ORDERED.indexOf(it) }
            ?.takeIf { it >= 0 && it < SETTINGS_ROW_VIEW_ID_ORDERED.lastIndex }
            ?.let { SETTINGS_ROW_VIEW_ID_ORDERED[it + 1] }
        val anchorBounds = preScrollAnchor?.bounds
        var bestIndex = -1
        var bestPriority = Int.MAX_VALUE
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
                label = label,
                viewId = rawViewId,
                bounds = bounds,
                visibleHistory = visibleHistory,
                visibleHistorySignatures = visibleHistorySignatures
            )
            val inVisitedHistory = isInVisitedHistory(
                label = label,
                viewId = viewIdOf(node),
                bounds = bounds,
                visitedHistory = visitedHistory,
                visitedHistorySignatures = visitedHistorySignatures
            )
            if (!inVisitedHistory) {
                logVisitedHistorySkip(
                    reason = "anchor continuity candidate only",
                    label = label,
                    viewId = viewIdOf(node),
                    bounds = bounds
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
            val isNewlyAvailableInteractiveCandidate =
                !inVisitedHistory &&
                    !isTopBar &&
                    !isBottomBar &&
                    isContentNode &&
                    isInteractiveCandidate &&
                    !isTopResurfacedAnchorCandidate &&
                    !isPreScrollAnchorItself
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
            val candidateEvaluation = evaluatePostScrollContinuationCandidate(
                isTopBar = isTopBar,
                isBottomBar = isBottomBar,
                isContentNode = isContentNode,
                inVisibleHistory = inVisibleHistory,
                inVisitedHistory = inVisitedHistory,
                isPostScrollTopContinuationCandidate = isPostScrollTopContinuationCandidate,
                isTrailingContinuationCandidate = isTrailingContinuationCandidate,
                isPromotedRawOnlyCandidate = isPromotedRawOnlyCandidate,
                isNewlyExposedBottomContent = isNewlyExposedBottomContent,
                isOtherUnvisitedVisible = isOtherUnvisitedVisible,
                isTopResurfacedAnchorCandidate = isTopResurfacedAnchorCandidate,
                rewoundBeforeAnchor = rewoundBeforeAnchor,
                isNewlyAvailableInteractiveCandidate = isNewlyAvailableInteractiveCandidate,
                focusable = focusableOf?.invoke(node),
                isOutOfScreen = isOutOfScreen,
                isLogicalSuccessor = false
            )
            val reasons = candidateEvaluation.rejectionReasons.toMutableList()
            val hasDescendantLabel = descendantLabelOf?.invoke(node)?.trim().isNullOrEmpty().not()
            if (label.isBlank() && descendantLabelOf != null && !hasDescendantLabel) {
                reasons += "candidate rejected: no descendant label"
            }
            if (isTopResurfacedAnchorCandidate) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Rejected top resurfaced anchor candidate after scroll")
                reasons += "candidate rejected: top resurfaced anchor"
            }
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
            if (!expectedSuccessorViewId.isNullOrBlank() && shortViewId != expectedSuccessorViewId && anchorBounds != null && bounds.top < anchorBounds.bottom) {
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_NEXT] Rejected candidate because it precedes anchor successor window index=$index label=${if (label.isBlank()) "<no-label>" else label.replace("\n", " ")} viewId=$rawViewId bounds=$bounds"
                )
            }

            val candidatePriority = if (reasons.none { it.startsWith("candidate rejected") }) {
                evaluatePostScrollContinuationCandidate(
                    isTopBar = isTopBar,
                    isBottomBar = isBottomBar,
                    isContentNode = isContentNode,
                    inVisibleHistory = inVisibleHistory,
                    inVisitedHistory = inVisitedHistory,
                    isPostScrollTopContinuationCandidate = isPostScrollTopContinuationCandidate,
                    isTrailingContinuationCandidate = isTrailingContinuationCandidate,
                    isPromotedRawOnlyCandidate = isPromotedRawOnlyCandidate,
                    isNewlyExposedBottomContent = isNewlyExposedBottomContent,
                    isOtherUnvisitedVisible = isOtherUnvisitedVisible,
                    isTopResurfacedAnchorCandidate = isTopResurfacedAnchorCandidate,
                    rewoundBeforeAnchor = rewoundBeforeAnchor,
                    isNewlyAvailableInteractiveCandidate = isNewlyAvailableInteractiveCandidate,
                    focusable = focusableOf?.invoke(node),
                    isOutOfScreen = isOutOfScreen,
                    isLogicalSuccessor = isLogicalSuccessor
                ).priority
            } else {
                Int.MAX_VALUE
            }

            if (candidatePriority != Int.MAX_VALUE && reasons.none { it.startsWith("candidate rejected") }) {
                when (candidatePriority) {
                    0 -> Log.i(
                        "A11Y_HELPER",
                        "[SMART_NEXT] Resolved post-scroll successor from pre-scroll anchor: anchorViewId=${preScrollAnchor?.viewIdResourceName} successorViewId=$rawViewId"
                    )
                    1 -> Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting newly available unvisited interactive continuation candidate")
                    2 -> Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting post-scroll top continuation candidate")
                    3 -> Log.i("A11Y_HELPER", "[SMART_NEXT] Accepted trailing continuation candidate by continuity rule")
                    4 -> Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting promoted raw-only continuation candidate")
                    5 -> Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting newly exposed bottom content continuation candidate")
                    6 -> Log.i("A11Y_HELPER", "[SMART_NEXT] Selecting low-priority unvisited continuation candidate")
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
                    Log.i(
                        "A11Y_HELPER",
                        "[SMART_NEXT] $reason index=$index label=$candidateLabel viewId=${viewIdOf(node)} className=${classNameOf(node)} clickable=${clickableOf?.invoke(node)} focusable=${focusableOf?.invoke(node)} bounds=$bounds"
                    )
                }
            }
        }
        return bestIndex
    }

    private data class RawVisibleNode(
        val label: String,
        val viewId: String?,
        val bounds: Rect
    )

    private fun describePreScrollAnchor(anchor: PreScrollAnchor?): String {
        if (anchor == null) return "null"
        val label = anchor.mergedLabel
            ?: anchor.talkbackLabel
            ?: anchor.text
            ?: anchor.contentDescription
            ?: "<no-label>"
        return "label=${label.replace("\n", " ")} viewId=${anchor.viewIdResourceName} bounds=${formatBoundsForLog(anchor.bounds)}"
    }

    private fun describeNodeForProgressLog(node: AccessibilityNodeInfo?, bounds: Rect?): String {
        if (node == null) return "null"
        val label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: "<no-label>"
        return "label=${label.replace("\n", " ")} viewId=${node.viewIdResourceName} bounds=${formatBoundsForLog(bounds)}"
    }

    private fun logPostScrollRawVsTraversalSnapshot(
        root: AccessibilityNodeInfo,
        traversalList: List<AccessibilityNodeInfo>,
        focusNodeByNode: Map<AccessibilityNodeInfo, FocusedNode>
    ) {
        val rawVisibleNodes = collectRawVisibleNodes(root)
        val rawLabels = rawVisibleNodes.map { it.label }.take(20)
        val traversalLabels = traversalList.map { node ->
            node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: focusNodeByNode[node]?.mergedLabel?.trim().takeUnless { it.isNullOrEmpty() }
                ?: "<no-label>"
        }.take(20)
        val joinedRawLabels = rawLabels.joinToString(" | ")
        val joinedTraversalLabels = traversalLabels.joinToString(" | ")
        Log.i(
            "A11Y_HELPER",
            "[SMART_NEXT] buildTraversalList() debug rawVisibleCount=${rawVisibleNodes.size} traversalCount=${traversalList.size} rawLabels=$joinedRawLabels traversalLabels=$joinedTraversalLabels"
        )

        val traversalSignatures = traversalList.map { node ->
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            val label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: focusNodeByNode[node]?.mergedLabel?.trim().takeUnless { it.isNullOrEmpty() }
                ?: "<no-label>"
            "${node.viewIdResourceName}|${bounds.left},${bounds.top},${bounds.right},${bounds.bottom}|$label"
        }.toSet()
        rawVisibleNodes.forEachIndexed { index, rawNode ->
            val signature = "${rawNode.viewId}|${rawNode.bounds.left},${rawNode.bounds.top},${rawNode.bounds.right},${rawNode.bounds.bottom}|${rawNode.label}"
            if (!traversalSignatures.contains(signature)) {
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_NEXT] RAW_ONLY_POST_SCROLL index=$index label=${rawNode.label.replace("\n", " ")} viewId=${rawNode.viewId} bounds=${rawNode.bounds}"
                )
            }
        }
    }

    private fun collectRawVisibleNodes(root: AccessibilityNodeInfo): List<RawVisibleNode> {
        val result = mutableListOf<RawVisibleNode>()
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack += root
        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            if (node.isVisibleToUser) {
                val bounds = Rect().also { node.getBoundsInScreen(it) }
                val label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: "<no-label>"
                result += RawVisibleNode(
                    label = label,
                    viewId = node.viewIdResourceName,
                    bounds = bounds
                )
                for (childIndex in node.childCount - 1 downTo 0) {
                    node.getChild(childIndex)?.let(stack::add)
                }
            }
        }
        return result
    }

    internal fun isInVisibleHistory(
        label: String?,
        viewId: String?,
        bounds: Rect,
        visibleHistory: Set<String>,
        visibleHistorySignatures: Set<VisibleHistorySignature>,
        boundsTolerancePx: Int = 24
    ): Boolean {
        val normalizedLabel = label?.trim().orEmpty()
        if (normalizedLabel.isNotEmpty() && visibleHistory.contains(normalizedLabel)) {
            return true
        }
        return visibleHistorySignatures.any { signature ->
            val sameLabel = normalizedLabel.isNotEmpty() &&
                signature.label.equals(normalizedLabel, ignoreCase = true)
            val sameViewId = !viewId.isNullOrBlank() &&
                signature.viewId.equals(viewId, ignoreCase = true)
            val similarBounds =
                abs(signature.bounds.left - bounds.left) <= boundsTolerancePx &&
                    abs(signature.bounds.top - bounds.top) <= boundsTolerancePx &&
                    abs(signature.bounds.right - bounds.right) <= boundsTolerancePx &&
                    abs(signature.bounds.bottom - bounds.bottom) <= boundsTolerancePx
            sameLabel || sameViewId || similarBounds
        }
    }

    private fun snapshotVisitedHistoryLabels(): Set<String> = synchronized(visitedHistoryLock) {
        visitedHistoryLabels.toSet()
    }

    private fun snapshotVisitedHistorySignatures(): Set<VisibleHistorySignature> = synchronized(visitedHistoryLock) {
        visitedHistorySignatures.toSet()
    }

    private fun buildNodeIdentityForHistory(node: AccessibilityNodeInfo): String {
        val windowId = node.windowId
        val className = node.className?.toString()?.trim().orEmpty()
        val packageName = node.packageName?.toString()?.trim().orEmpty()
        return "window=$windowId|class=$className|package=$packageName"
    }

    private fun logVisitedHistorySkip(reason: String, label: String?, viewId: String?, bounds: Rect? = null) {
        Log.i(
            "A11Y_HELPER",
            "[SMART_NEXT] visitedHistory skip: reason=$reason label=${label?.replace("\n", " ") ?: "<no-label>"} viewId=$viewId bounds=$bounds"
        )
    }

    private fun recordVisitedFocus(node: AccessibilityNodeInfo, label: String, reason: String) {
        val normalizedLabel = label.trim()
        val descendantTextCandidates = collectDescendantTextCandidates(node)
        if (shouldExcludeContainerNodeFromTraversal(node, descendantTextCandidates)) {
            logVisitedHistorySkip(
                reason = "container_node_excluded_from_history",
                label = normalizedLabel,
                viewId = node.viewIdResourceName,
                bounds = Rect().also { node.getBoundsInScreen(it) }
            )
            return
        }
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        val nodeIdentity = buildNodeIdentityForHistory(node)
        synchronized(visitedHistoryLock) {
            if (normalizedLabel.isNotEmpty() && normalizedLabel != "<no-label>") {
                visitedHistoryLabels += normalizedLabel
            }
            visitedHistorySignatures += VisibleHistorySignature(
                label = normalizedLabel.takeUnless { it.isBlank() || it == "<no-label>" },
                viewId = node.viewIdResourceName,
                bounds = Rect(bounds),
                nodeIdentity = nodeIdentity
            )
            if (visitedHistorySignatures.size > 120) {
                visitedHistorySignatures.removeAt(0)
            }
        }
        Log.i(
            "A11Y_HELPER",
            "[SMART_NEXT] visitedHistory add: reason=$reason label=${normalizedLabel.replace("\n", " ")} viewId=${node.viewIdResourceName} identity=$nodeIdentity bounds=$bounds"
        )
    }

    internal fun isInVisitedHistory(
        label: String?,
        viewId: String?,
        bounds: Rect,
        visitedHistory: Set<String>,
        visitedHistorySignatures: Set<VisibleHistorySignature>,
        boundsTolerancePx: Int = 24
    ): Boolean {
        val normalizedLabel = label?.trim().orEmpty()
        if (normalizedLabel.isNotEmpty() && visitedHistory.contains(normalizedLabel)) {
            return true
        }
        return visitedHistorySignatures.any { signature ->
            val sameLabel = normalizedLabel.isNotEmpty() &&
                signature.label.equals(normalizedLabel, ignoreCase = true)
            val sameViewId = !viewId.isNullOrBlank() &&
                signature.viewId.equals(viewId, ignoreCase = true)
            val similarBounds =
                abs(signature.bounds.left - bounds.left) <= boundsTolerancePx &&
                    abs(signature.bounds.top - bounds.top) <= boundsTolerancePx &&
                    abs(signature.bounds.right - bounds.right) <= boundsTolerancePx &&
                    abs(signature.bounds.bottom - bounds.bottom) <= boundsTolerancePx
            val hasStrongNodeIdentity = !signature.nodeIdentity.isNullOrBlank()
            when {
                sameLabel && sameViewId -> true
                sameLabel && similarBounds -> true
                sameViewId && similarBounds && hasStrongNodeIdentity -> true
                else -> false
            }
        }
    }

    internal fun performFocusWithVisibilityCheck(
        root: AccessibilityNodeInfo,
        target: AccessibilityNodeInfo,
        screenTop: Int,
        effectiveBottom: Int,
        status: String,
        isScrollAction: Boolean,
        traversalIndex: Int,
        traversalListSnapshot: List<AccessibilityNodeInfo>? = null,
        currentFocusIndexHint: Int = -1
    ): TargetActionOutcome {
        val label = target.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: target.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: "<no-label>"

        val rootBounds = Rect().also { root.getBoundsInScreen(it) }
        val rootHeight = (rootBounds.bottom - rootBounds.top).coerceAtLeast(1)
        val initialBounds = Rect().also { target.getBoundsInScreen(it) }
        val isTopBar = isTopAppBarNode(
            className = target.className?.toString(),
            viewIdResourceName = target.viewIdResourceName,
            boundsInScreen = initialBounds,
            screenTop = screenTop,
            screenHeight = rootHeight
        )
        val isBottomBar = isBottomNavigationBarNode(
            className = target.className?.toString(),
            viewIdResourceName = target.viewIdResourceName,
            boundsInScreen = initialBounds,
            screenBottom = rootBounds.bottom,
            screenHeight = rootHeight
        )

        val partiallyVisibleTrailingIndex = if (
            traversalListSnapshot != null &&
            traversalIndex in traversalListSnapshot.indices &&
            currentFocusIndexHint in traversalListSnapshot.indices
        ) {
            findPartiallyVisibleNextCandidate(
                traversalList = traversalListSnapshot,
                currentIndex = currentFocusIndexHint,
                screenTop = screenTop,
                effectiveBottom = effectiveBottom,
                screenBottom = rootBounds.bottom,
                screenHeight = rootHeight,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                classNameOf = { node -> node.className?.toString() },
                viewIdOf = { node -> node.viewIdResourceName }
            )
        } else {
            -1
        }
        if (partiallyVisibleTrailingIndex == traversalIndex) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Detected partially visible next candidate: index=$traversalIndex label=$label")
            logVisitedHistorySkip(
                reason = "partial visibility",
                label = label,
                viewId = target.viewIdResourceName,
                bounds = initialBounds
            )
        }

        val intendedTrailingCandidate = if (traversalListSnapshot != null && traversalIndex in traversalListSnapshot.indices) {
            findNextEligibleTraversalCandidate(
                traversalList = traversalListSnapshot,
                fromIndex = traversalIndex,
                screenTop = screenTop,
                screenBottom = rootBounds.bottom,
                screenHeight = rootHeight,
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                classNameOf = { node -> node.className?.toString() },
                viewIdOf = { node -> node.viewIdResourceName }
            )
        } else {
            null
        }

        val descendantTextCandidates = collectDescendantTextCandidates(target)
        val isSingleSemanticCandidate =
            !shouldExcludeContainerNodeFromTraversal(target, descendantTextCandidates) &&
                shouldAllowRecoveredDescendantLabelForTraversal(descendantTextCandidates)
        if (isSingleSemanticCandidate) {
            alignCandidateForReadableFocus(
                root = root,
                target = target,
                label = label,
                screenTop = screenTop,
                effectiveBottom = effectiveBottom,
                isTopBar = isTopBar,
                isBottomBar = isBottomBar,
                canScrollForwardHint = findScrollableForwardAncestorCandidate(target) != null || hasScrollableDownCandidate(root),
                intendedTrailingCandidate = intendedTrailingCandidate
            )
        } else {
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT] Skipping pre-focus alignment for container-like candidate label=$label viewId=${target.viewIdResourceName}"
            )
        }

        val targetBounds = Rect().also { target.getBoundsInScreen(it) }
        val actualFocusedBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
            Rect().also { focusedNode.getBoundsInScreen(it) }
        }
        val currentSystemFocus = target.refresh() && target.isAccessibilityFocused
        if (shouldReuseExistingAccessibilityFocus(
                label = label,
                isScrollAction = isScrollAction,
                currentFocusedBounds = actualFocusedBounds,
                targetBounds = targetBounds
            )
        ) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping duplicate focus action because current accessibility focus bounds exactly match target: $label")
            recordRequestedFocusAttempt(traversalIndex, root)
            recordVisitedFocus(target, label, reason = "focus_reused_existing_target")
            return TargetActionOutcome(true, "moved", target)
        }
        if (currentSystemFocus && actualFocusedBounds != null && actualFocusedBounds != targetBounds) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Target reports accessibilityFocused=true but actual focused bounds differ. Forcing focus action: target=$targetBounds actual=$actualFocusedBounds label=$label")
        }
        if (label == "<no-label>" && isScrollAction) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Bypassing scrolled_auto_focused reuse for <no-label> target to break focus lock")
        }

        if (shouldDelayBeforeFocusCommand(actualFocusedBounds, targetBounds)) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Delaying 100ms before focus to stabilize horizontal traversal: label=$label index=$traversalIndex")
            Thread.sleep(100)
        }

        clearAccessibilityFocusAndRefresh(root)
        requestInputFocusBeforeAccessibilityFocus(target, label)

        val beforeFocusBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
            Rect().also { focusedNode.getBoundsInScreen(it) }
        }
        Log.i(
            "A11Y_HELPER",
            "[FOCUS_VERIFY] Before Focus: System is at ${formatBoundsForLog(beforeFocusBounds)}, Target is at ${formatBoundsForLog(targetBounds)}"
        )

        val focusEventTimestampBeforeAction = A11yStateStore.lastUpdatedAt
        val focused = requestAccessibilityFocusWithRetry(
            performFocusAction = {
                target.refresh()
                target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            },
            refreshFocusState = {
                target.refresh()
                isAccessibilityFocusEffectivelyActive(
                    isAccessibilityFocused = target.isAccessibilityFocused,
                    traversalIndex = traversalIndex,
                    actualFocusedBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
                        Rect().also { focusedNode.getBoundsInScreen(it) }
                    },
                    targetBounds = targetBounds
                )
            },
            evaluateEffectiveFocus = {
                val focusedBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
                    Rect().also { focusedNode.getBoundsInScreen(it) }
                }
                target.refresh() &&
                    target.isAccessibilityFocused &&
                    focusedBounds != null &&
                    isWithinSnapBackTolerance(targetBounds, focusedBounds)
            }
        )

        val focusVerification = verifyFocusStabilizationAfterAction(
            root = root,
            target = target,
            targetBounds = targetBounds
        )
        val afterFocusBounds = focusVerification.actualBounds
        Log.i(
            "A11Y_HELPER",
            "[FOCUS_VERIFY] After Focus: System is at ${formatBoundsForLog(afterFocusBounds)}, Target is at ${formatBoundsForLog(targetBounds)}"
        )

        if (!focused) {
            val effectivelyFocused = focusVerification.isTargetAccessibilityFocused ||
                (afterFocusBounds != null && isWithinSnapBackTolerance(targetBounds, afterFocusBounds))
            if (effectivelyFocused) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_ACCESSIBILITY_FOCUS result=false but actual system focus matches target bounds. Treating as success.")
                recordRequestedFocusAttempt(traversalIndex, root)
                recordVisitedFocus(target, label, reason = "focus_action_false_but_target_confirmed")
                return TargetActionOutcome(true, status, target)
            }
            Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_ACCESSIBILITY_FOCUS result=false (status=$status)")
            syncLastRequestedFocusIndexToCurrentFocus(root, buildTalkBackLikeFocusNodes(root).map { it.node })
            return TargetActionOutcome(false, "failed", target)
        }

        if (focusVerification.matchedTarget && focusVerification.retryCount > 0) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Focus stabilized to target after delay")
        }

        val visualStabilization = stabilizeVisualFocusAfterMove(
            root = root,
            target = target,
            targetBounds = targetBounds
        )
        val focusEventConfirmed = didReceiveFocusEventAfter(
            timestampBefore = focusEventTimestampBeforeAction,
            maxWaitMs = 250L,
            retryIntervalMs = 50L
        )

        if (!visualStabilization.stabilized) {
            if (focusVerification.isTargetAccessibilityFocused && focusEventConfirmed) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Focus event confirmed after ACTION_FOCUS; treating mismatch as success without rollback")
                recordRequestedFocusAttempt(traversalIndex, root)
                recordVisitedFocus(target, label, reason = "focus_event_confirmed_after_stabilization")
                return TargetActionOutcome(true, "moved", target)
            }
            Log.w(
                "A11Y_HELPER",
                "[SMART_NEXT] Final focus mismatch after visual stabilization → snap_back: target=${formatBoundsForLog(targetBounds)} actual=${formatBoundsForLog(visualStabilization.actualBounds)} traversalIndex=$traversalIndex label=$label"
            )
            Log.i("A11Y_HELPER", "[SMART_NEXT] Delaying rollback due to pending stabilization")
            val lateFocus = verifyFocusStabilizationAfterAction(
                root = root,
                target = target,
                targetBounds = targetBounds,
                maxWaitMs = 350L,
                retryIntervalMs = 50L
            )
            val lateFocusAllowed = shouldAllowLateFocusSuccess(
                root = root,
                target = target,
                targetBounds = targetBounds,
                lateFocus = lateFocus
            )
            if (lateFocusAllowed) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Late focus detected → treat as success")
                recordRequestedFocusAttempt(traversalIndex, root)
                recordVisitedFocus(target, label, reason = "late_focus_detected_after_stabilization")
                return TargetActionOutcome(true, "moved", target)
            }
            Log.w("A11Y_HELPER", "[SMART_NEXT] Confirmed real snap_back")
            syncLastRequestedFocusIndexToCurrentFocus(root, buildTalkBackLikeFocusNodes(root).map { it.node })
            return TargetActionOutcome(false, "snap_back", target)
        }

        if (shouldTreatAsSnapBackAfterVerification(
                actualFocusedBounds = afterFocusBounds,
                targetBounds = targetBounds,
                isTargetAccessibilityFocused = focusVerification.isTargetAccessibilityFocused
            )
        ) {
            if (focusVerification.isTargetAccessibilityFocused && focusEventConfirmed) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Focus event confirmed after ACTION_FOCUS; suppressing premature snap_back")
                recordRequestedFocusAttempt(traversalIndex, root)
                recordVisitedFocus(target, label, reason = "focus_event_confirmed_after_retry")
                return TargetActionOutcome(true, "moved", target)
            }
            Log.w(
                "A11Y_HELPER",
                "[SMART_NEXT] Final focus mismatch after retries → snap_back: target=${formatBoundsForLog(targetBounds)} actual=${formatBoundsForLog(afterFocusBounds)} traversalIndex=$traversalIndex label=$label"
            )
            Log.i("A11Y_HELPER", "[SMART_NEXT] Delaying rollback due to pending stabilization")
            val lateFocus = verifyFocusStabilizationAfterAction(
                root = root,
                target = target,
                targetBounds = targetBounds,
                maxWaitMs = 350L,
                retryIntervalMs = 50L
            )
            val lateFocusAllowed = shouldAllowLateFocusSuccess(
                root = root,
                target = target,
                targetBounds = targetBounds,
                lateFocus = lateFocus
            )
            if (lateFocusAllowed) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Late focus detected → treat as success")
                recordRequestedFocusAttempt(traversalIndex, root)
                recordVisitedFocus(target, label, reason = "late_focus_detected_after_retry")
                return TargetActionOutcome(true, "moved", target)
            }
            Log.w("A11Y_HELPER", "[SMART_NEXT] Confirmed real snap_back")
            syncLastRequestedFocusIndexToCurrentFocus(root, buildTalkBackLikeFocusNodes(root).map { it.node })
            return TargetActionOutcome(false, "snap_back", target)
        }

        recordRequestedFocusAttempt(traversalIndex, root)
        Thread.sleep(100)
        val focusedBounds = Rect().also { target.getBoundsInScreen(it) }
        recordRequestedFocusAttempt(traversalIndex, root)
        recordVisitedFocus(target, label, reason = "focus_confirmed_final")
        Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_ACCESSIBILITY_FOCUS result=true (status=$status)")
        Log.i("A11Y_HELPER", "[SMART_NEXT] Focused top-most content at Y=${focusedBounds.top}")
        return TargetActionOutcome(true, "moved", target)
    }

    private fun shouldAllowLateFocusSuccess(
        root: AccessibilityNodeInfo,
        target: AccessibilityNodeInfo,
        targetBounds: Rect,
        lateFocus: FocusVerificationResult
    ): Boolean {
        val focusedNode = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val focusedBounds = focusedNode?.let { Rect().also(it::getBoundsInScreen) } ?: lateFocus.actualBounds
        val rootBounds = Rect().also(root::getBoundsInScreen)
        val rootTop = rootBounds.top
        val rootBottom = rootBounds.bottom
        val rootHeight = (rootBottom - rootTop).coerceAtLeast(1)
        val focusedClassName = focusedNode?.className?.toString()
        val focusedViewId = focusedNode?.viewIdResourceName
        val isTopChromeFocus =
            (focusedBounds != null && isTopAppBarNode(focusedClassName, focusedViewId, focusedBounds, rootTop, rootHeight)) ||
                focusedViewId?.contains("settings", ignoreCase = true) == true ||
                focusedViewId?.contains("toolbar", ignoreCase = true) == true
        val identityOrBoundsMatch = lateFocus.matchedTarget ||
            (focusedBounds != null && isWithinSnapBackTolerance(targetBounds, focusedBounds)) ||
            target.isAccessibilityFocused
        val allowed = identityOrBoundsMatch && !isTopChromeFocus
        val reason = if (allowed) "target_matched_and_not_fixed_chrome" else when {
            !identityOrBoundsMatch -> "target_mismatch"
            isTopChromeFocus -> "focused_on_top_fixed_chrome"
            else -> "rejected"
        }
        Log.i("A11Y_HELPER", "[FOCUS_VERIFY] late_success_gate allowed=$allowed reason=$reason target=${formatBoundsForLog(targetBounds)} actual=${formatBoundsForLog(focusedBounds)}")
        return allowed
    }

    internal fun isNodeFullyVisible(bounds: Rect, screenTop: Int, effectiveBottom: Int): Boolean {
        return bounds.top >= screenTop && bounds.bottom <= effectiveBottom
    }

    internal fun isNodeBottomClipped(bounds: Rect, effectiveBottom: Int, boundaryPaddingPx: Int = 16): Boolean {
        return bounds.bottom > effectiveBottom || bounds.bottom >= (effectiveBottom - boundaryPaddingPx)
    }

    internal fun shouldLiftTrailingContentBeforeFocus(
        bounds: Rect,
        effectiveBottom: Int,
        trailingEdgeThresholdPx: Int = 60,
        thinTrailingHeightPx: Int = 96
    ): Boolean {
        val height = (bounds.bottom - bounds.top).coerceAtLeast(0)
        val touchesBottomEdge = bounds.bottom >= (effectiveBottom - trailingEdgeThresholdPx)
        return height in 1..thinTrailingHeightPx && touchesBottomEdge
    }

    internal fun isNodePoorlyPositionedForFocus(
        bounds: Rect,
        screenTop: Int,
        effectiveBottom: Int,
        readableBottomZoneRatio: Float = 0.2f
    ): Boolean {
        if (!isNodeFullyVisible(bounds, screenTop, effectiveBottom)) return true
        if (isNodeBottomClipped(bounds, effectiveBottom)) return true
        if (shouldLiftTrailingContentBeforeFocus(bounds, effectiveBottom)) return true
        val safeBottom = effectiveBottom - ((effectiveBottom - screenTop) * readableBottomZoneRatio).toInt()
        return bounds.bottom > safeBottom
    }

    internal fun alignCandidateForReadableFocus(
        root: AccessibilityNodeInfo,
        target: AccessibilityNodeInfo,
        label: String,
        screenTop: Int,
        effectiveBottom: Int,
        isTopBar: Boolean,
        isBottomBar: Boolean,
        canScrollForwardHint: Boolean,
        intendedTrailingCandidate: AccessibilityNodeInfo? = null,
        maxPreFocusAdjustments: Int = 1
    ) {
        if (isTopBar) return
        if (isBottomBar) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Detected bottom navigation target -> skipping pre-focus alignment")
            return
        }
        var currentBounds = Rect().also { target.getBoundsInScreen(it) }
        val poorlyPositioned = isNodePoorlyPositionedForFocus(currentBounds, screenTop, effectiveBottom)
        if (!poorlyPositioned) return

        if (isNodeBottomClipped(currentBounds, effectiveBottom)) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Candidate is bottom-clipped, attempting pre-focus alignment")
        }

        val shouldUseMinimalAdjustment = shouldUseMinimalPreFocusAdjustment(
            intendedBounds = currentBounds,
            trailingCandidateBounds = intendedTrailingCandidate?.let { candidate ->
                Rect().also { candidate.getBoundsInScreen(it) }
            },
            screenTop = screenTop,
            effectiveBottom = effectiveBottom
        )
        if (shouldUseMinimalAdjustment) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Applying minimal pre-focus adjustment for intended candidate")
        }

        var adjustments = 0
        while (adjustments < maxPreFocusAdjustments) {
            var adjusted = false
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                target.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.id)
                adjusted = true
            } else {
                Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_SHOW_ON_SCREEN not supported on this API level")
            }

            val shouldTryContainerScroll =
                !shouldUseMinimalAdjustment &&
                canScrollForwardHint && (isNodeBottomClipped(currentBounds, effectiveBottom) || shouldLiftTrailingContentBeforeFocus(currentBounds, effectiveBottom))
            if (shouldTryContainerScroll) {
                val scrollableNode = findScrollableForwardAncestorCandidate(target) ?: findScrollableForwardCandidate(root)
                if (scrollableNode != null) {
                    val scrolled = scrollableNode.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Pre-focus readable alignment scroll result=$scrolled label=$label")
                    adjusted = adjusted || scrolled
                }
            } else if (!canScrollForwardHint) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Last content cannot be top-aligned, using fully-visible fallback")
            }

            if (!adjusted) break
            Thread.sleep(100)
            currentBounds = Rect().also { target.getBoundsInScreen(it) }
            val trailingBounds = intendedTrailingCandidate?.let { candidate ->
                Rect().also { candidate.getBoundsInScreen(it) }
            }
            if (wouldOvershootPastIntendedCandidate(currentBounds, trailingBounds, screenTop, effectiveBottom)) {
                Log.w("A11Y_HELPER", "[SMART_NEXT] Overshoot detected: adjustment exposed a later card as primary content")
                break
            }
            if (!isNodePoorlyPositionedForFocus(currentBounds, screenTop, effectiveBottom)) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Intended candidate is now fully visible")
                return
            }
            adjustments += 1
        }

        if (isNodeFullyVisible(currentBounds, screenTop, effectiveBottom)) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Intended candidate is now fully visible")
        } else {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Proceeding with best-effort focus on intended candidate")
        }
    }

    internal fun shouldUseMinimalPreFocusAdjustment(
        intendedBounds: Rect,
        trailingCandidateBounds: Rect?,
        screenTop: Int,
        effectiveBottom: Int
    ): Boolean {
        val intendedPartiallyVisible = isNodePartiallyVisible(intendedBounds, screenTop, effectiveBottom)
        val trailingPartiallyVisible = trailingCandidateBounds?.let {
            isNodePartiallyVisible(it, screenTop, effectiveBottom)
        } ?: false
        return intendedPartiallyVisible || trailingPartiallyVisible
    }

    internal fun isNodePartiallyVisible(bounds: Rect, screenTop: Int, effectiveBottom: Int): Boolean {
        val visibleTop = maxOf(bounds.top, screenTop)
        val visibleBottom = minOf(bounds.bottom, effectiveBottom)
        val visibleHeight = (visibleBottom - visibleTop).coerceAtLeast(0)
        val fullHeight = (bounds.bottom - bounds.top).coerceAtLeast(0)
        return visibleHeight > 0 && visibleHeight < fullHeight
    }

    internal fun wouldOvershootPastIntendedCandidate(
        intendedBounds: Rect,
        trailingCandidateBounds: Rect?,
        screenTop: Int,
        effectiveBottom: Int
    ): Boolean {
        if (intendedBounds.bottom <= screenTop || intendedBounds.top < screenTop) return true
        if (trailingCandidateBounds == null) return false
        val intendedVisibleHeight = visibleHeightInViewport(intendedBounds, screenTop, effectiveBottom)
        val trailingVisibleHeight = visibleHeightInViewport(trailingCandidateBounds, screenTop, effectiveBottom)
        val intendedNoLongerPrimary = intendedVisibleHeight <= 0 ||
            (intendedBounds.top < screenTop && trailingVisibleHeight > 0)
        val trailingBecamePrimary = trailingVisibleHeight > (intendedVisibleHeight + 24) &&
            trailingCandidateBounds.top < effectiveBottom
        return intendedNoLongerPrimary || trailingBecamePrimary
    }

    internal fun <T> findPartiallyVisibleNextCandidate(
        traversalList: List<T>,
        currentIndex: Int,
        screenTop: Int,
        effectiveBottom: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?
    ): Int {
        if (currentIndex !in traversalList.indices) return -1
        val currentBounds = boundsOf(traversalList[currentIndex])
        for (index in (currentIndex + 1)..traversalList.lastIndex) {
            val candidate = traversalList[index]
            val bounds = boundsOf(candidate)
            if (bounds.bottom <= currentBounds.bottom) continue
            if (isTopAppBarNode(classNameOf(candidate), viewIdOf(candidate), bounds, screenTop, screenHeight)) continue
            if (isBottomNavigationBarNode(classNameOf(candidate), viewIdOf(candidate), bounds, screenBottom, screenHeight)) continue
            return if (isNodePartiallyVisible(bounds, screenTop, effectiveBottom)) index else -1
        }
        return -1
    }

    internal fun visibleHeightInViewport(bounds: Rect, screenTop: Int, effectiveBottom: Int): Int {
        val visibleTop = maxOf(bounds.top, screenTop)
        val visibleBottom = minOf(bounds.bottom, effectiveBottom)
        return (visibleBottom - visibleTop).coerceAtLeast(0)
    }

    internal fun isTransientSystemUiFocus(
        focusedPackageName: String?,
        targetPackageName: String?
    ): Boolean {
        if (focusedPackageName.isNullOrBlank()) return false
        if (focusedPackageName != "com.android.systemui") return false
        return targetPackageName?.toString()?.trim() != "com.android.systemui"
    }

    internal data class VisualFocusStabilizationResult(
        val stabilized: Boolean,
        val fallbackApplied: Boolean,
        val actualBounds: Rect?
    )

    internal fun stabilizeVisualFocusAfterMove(
        root: AccessibilityNodeInfo,
        target: AccessibilityNodeInfo,
        targetBounds: Rect,
        maxWaitMs: Long = 200L,
        retryIntervalMs: Long = 50L,
        maxFallbackAttempts: Int = 1
    ): VisualFocusStabilizationResult {
        Log.i("A11Y_HELPER", "[SMART_NEXT] Stabilizing visual focus for target=${target.text ?: target.contentDescription ?: "<no-label>"}")
        val targetPackageName = target.packageName?.toString()
        val maxRetries = (maxWaitMs / retryIntervalMs).toInt().coerceAtLeast(0)
        var lastActualBounds: Rect? = null
        var fallbackApplied = false
        var fallbackAttempts = 0

        while (true) {
            for (retry in 0..maxRetries) {
                val focusedNode = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
                val actualBounds = focusedNode?.let { Rect().also(it::getBoundsInScreen) }
                val focusedPackageName = focusedNode?.packageName?.toString()
                lastActualBounds = actualBounds

                if (isTransientSystemUiFocus(focusedPackageName, targetPackageName)) {
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Ignoring transient system UI focus during stabilization")
                } else {
                    target.refresh()
                    val targetFocused = target.isAccessibilityFocused
                    val boundsMatched = actualBounds != null && isWithinSnapBackTolerance(targetBounds, actualBounds)
                    if (targetFocused && boundsMatched) {
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Visual focus stabilized on intended target")
                        return VisualFocusStabilizationResult(true, fallbackApplied, actualBounds)
                    }
                }

                if (retry < maxRetries) {
                    Thread.sleep(retryIntervalMs)
                }
            }

            if (fallbackAttempts >= maxFallbackAttempts) {
                return VisualFocusStabilizationResult(false, fallbackApplied, lastActualBounds)
            }

            fallbackAttempts += 1
            fallbackApplied = true
            Log.w("A11Y_HELPER", "[SMART_NEXT] Visual focus stabilization fallback applied")
            target.refresh()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                target.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.id)
            }
            target.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            Thread.sleep(retryIntervalMs)
        }
    }

    internal fun <T> findNextEligibleTraversalCandidate(
        traversalList: List<T>,
        fromIndex: Int,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?
    ): T? {
        if (fromIndex !in traversalList.indices) return null
        for (index in (fromIndex + 1)..traversalList.lastIndex) {
            val candidate = traversalList[index]
            val bounds = boundsOf(candidate)
            if (isTopAppBarNode(classNameOf(candidate), viewIdOf(candidate), bounds, screenTop, screenHeight)) continue
            if (isBottomNavigationBarNode(classNameOf(candidate), viewIdOf(candidate), bounds, screenBottom, screenHeight)) continue
            return candidate
        }
        return null
    }



    internal fun setLastRequestedFocusIndex(index: Int) {
        lastRequestedFocusIndex = index
        A11yStateStore.updateLastRequestedFocusIndex(index)
    }

    internal fun nodeObjectId(node: AccessibilityNodeInfo): Int = System.identityHashCode(node)

    internal fun recordRequestedFocusAttempt(index: Int, root: AccessibilityNodeInfo? = null) {
        if (index < 0) return

        var resolvedIndex = maxOf(lastRequestedFocusIndex, A11yStateStore.lastRequestedFocusIndex, index)
        val focusedNode = root?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        if (root != null && focusedNode != null) {
            val traversalNodes = buildTalkBackLikeFocusNodes(root).map { it.node }
            val focusedNodeObjectId = nodeObjectId(focusedNode)
            val directObjectMatchIndex = traversalNodes.indexOfFirst { nodeObjectId(it) == focusedNodeObjectId }
            if (directObjectMatchIndex != -1) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Reconciled lastRequestedFocusIndex with focused node object id at index $directObjectMatchIndex")
                resolvedIndex = maxOf(resolvedIndex, directObjectMatchIndex)
            } else {
                val focusedIndex = findNodeIndexByIdentity(
                    nodes = traversalNodes,
                    target = focusedNode,
                    idOf = { it.viewIdResourceName },
                    textOf = { it.text?.toString() },
                    contentDescriptionOf = { it.contentDescription?.toString() },
                    boundsOf = { Rect().also(it::getBoundsInScreen) },
                    onCoordinateMatch = { matchedIndex ->
                        Log.w(
                            "A11Y_HELPER",
                            "[SMART_NEXT] Ignoring coordinate-only focus reconciliation at index $matchedIndex because focused node object id did not match"
                        )
                    }
                )
                if (focusedIndex != -1) {
                    val candidate = traversalNodes[focusedIndex]
                    if (nodeObjectId(candidate) == focusedNodeObjectId) {
                        resolvedIndex = maxOf(resolvedIndex, focusedIndex)
                    }
                }
            }
        }

        setLastRequestedFocusIndex(resolvedIndex)
    }

    internal fun clearAccessibilityFocusAndRefresh(root: AccessibilityNodeInfo) {
        root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
            val cleared = focusedNode.performAction(AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
            val clearedTwice = focusedNode.performAction(AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
            Log.i("A11Y_HELPER", "[SMART_NEXT] Cleared accessibility focus before request: result=$cleared secondPass=$clearedTwice")
        }

        val service: android.accessibilityservice.AccessibilityService? = A11yHelperService.instance
        if (service != null && service is A11yHelperService) {
            root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
                ?.performAction(AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
            root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
                ?.performAction(AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
            (service as A11yHelperService).sendAccessibilityEvent(
                AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUS_CLEARED
            )
            Log.i("A11Y_HELPER", "[SMART_NEXT] Successfully sent focus clear event with explicit casting")
        }
    }

    internal fun requestInputFocusBeforeAccessibilityFocus(target: AccessibilityNodeInfo, label: String): Boolean {
        val inputFocusResult = target.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_FOCUS priming result=$inputFocusResult label=$label")
        return inputFocusResult
    }

    private fun formatBoundsForLog(bounds: Rect?): String {
        return bounds?.let { "[${it.left},${it.top},${it.right},${it.bottom}]" } ?: "[null]"
    }

    internal fun shouldDelayBeforeFocusCommand(currentFocusedBounds: Rect?, targetBounds: Rect?): Boolean {
        if (currentFocusedBounds == null || targetBounds == null) return false
        return currentFocusedBounds != targetBounds && currentFocusedBounds.top == targetBounds.top
    }

    internal fun didReceiveFocusEventAfter(
        timestampBefore: Long,
        maxWaitMs: Long = 250L,
        retryIntervalMs: Long = 50L
    ): Boolean {
        val maxRetries = (maxWaitMs / retryIntervalMs).toInt().coerceAtLeast(0)
        repeat(maxRetries + 1) { retry ->
            if (A11yStateStore.lastUpdatedAt > timestampBefore) {
                return true
            }
            if (retry < maxRetries) {
                Thread.sleep(retryIntervalMs)
            }
        }
        return false
    }

    internal fun isAccessibilityFocusEffectivelyActive(
        isAccessibilityFocused: Boolean,
        traversalIndex: Int,
        actualFocusedBounds: Rect? = null,
        targetBounds: Rect? = null
    ): Boolean {
        if (!isAccessibilityFocused) return false
        if (actualFocusedBounds != null && targetBounds != null && isWithinSnapBackTolerance(targetBounds, actualFocusedBounds)) {
            return true
        }
        if (traversalIndex != -1 && traversalIndex == lastRequestedFocusIndex) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Ignoring stale isAccessibilityFocused=true for repeated traversal index=$traversalIndex")
            return false
        }
        return true
    }

    internal fun applyBottomNavigationSafetyGuide(
        effectiveBottom: Int,
        screenBottom: Int,
        minVisibleRatio: Float = 0.85f
    ): Int {
        val minGuideBottom = (screenBottom * minVisibleRatio).toInt()
        return minOf(effectiveBottom, minGuideBottom)
    }

    internal fun requestAccessibilityFocusWithRetry(
        performFocusAction: () -> Boolean,
        refreshFocusState: () -> Boolean,
        evaluateEffectiveFocus: (() -> Boolean)? = null,
        maxAttempts: Int = 3,
        retryDelayMs: Long = 100L
    ): Boolean {
        repeat(maxAttempts) { attempt ->
            if (performFocusAction()) {
                return true
            }
            val alreadyFocused = refreshFocusState()
            if (alreadyFocused) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_ACCESSIBILITY_FOCUS returned false but node is already focused on attempt=${attempt + 1}")
                return true
            }
            if (evaluateEffectiveFocus?.invoke() == true) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_ACCESSIBILITY_FOCUS returned false but effective system focus matched target on attempt=${attempt + 1}")
                return true
            }
            if (attempt < maxAttempts - 1) {
                Thread.sleep(retryDelayMs)
            }
        }
        return false
    }

    internal data class FocusVerificationResult(
        val matchedTarget: Boolean,
        val isTargetAccessibilityFocused: Boolean,
        val actualBounds: Rect?,
        val retryCount: Int
    )

    internal fun verifyFocusStabilizationAfterAction(
        root: AccessibilityNodeInfo,
        target: AccessibilityNodeInfo,
        targetBounds: Rect,
        maxWaitMs: Long = 250L,
        retryIntervalMs: Long = 50L
    ): FocusVerificationResult {
        val maxRetries = (maxWaitMs / retryIntervalMs).toInt().coerceAtLeast(0)
        var retryCount = 0
        var lastActualBounds: Rect? = null
        var lastTargetFocused = false

        while (retryCount <= maxRetries) {
            val actualBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
                Rect().also { focusedNode.getBoundsInScreen(it) }
            }
            target.refresh()
            val targetFocused = target.isAccessibilityFocused
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT] Focus verification retry i=$retryCount, actual=${formatBoundsForLog(actualBounds)}, target=${formatBoundsForLog(targetBounds)}"
            )
            if (isTargetFocusResolved(targetFocused, actualBounds, targetBounds)) {
                return FocusVerificationResult(
                    matchedTarget = true,
                    isTargetAccessibilityFocused = targetFocused,
                    actualBounds = actualBounds,
                    retryCount = retryCount
                )
            }
            lastActualBounds = actualBounds
            lastTargetFocused = targetFocused
            if (retryCount < maxRetries) {
                Thread.sleep(retryIntervalMs)
            }
            retryCount += 1
        }

        return FocusVerificationResult(
            matchedTarget = false,
            isTargetAccessibilityFocused = lastTargetFocused,
            actualBounds = lastActualBounds,
            retryCount = maxRetries
        )
    }

    internal fun isTargetFocusResolved(
        isTargetAccessibilityFocused: Boolean,
        actualFocusedBounds: Rect?,
        targetBounds: Rect
    ): Boolean {
        if (isTargetAccessibilityFocused) return true
        if (actualFocusedBounds == null) return false
        return isWithinSnapBackTolerance(targetBounds, actualFocusedBounds)
    }

    internal fun shouldTreatAsSnapBackAfterVerification(
        actualFocusedBounds: Rect?,
        targetBounds: Rect,
        isTargetAccessibilityFocused: Boolean
    ): Boolean {
        return !isTargetFocusResolved(
            isTargetAccessibilityFocused = isTargetAccessibilityFocused,
            actualFocusedBounds = actualFocusedBounds,
            targetBounds = targetBounds
        )
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
        return isBottomNavigationBarNode(
            className = classNameOf(node),
            viewIdResourceName = viewIdOf(node),
            boundsInScreen = bounds,
            screenBottom = screenBottom,
            screenHeight = screenHeight
        )
    }

    internal fun shouldReuseExistingAccessibilityFocus(
        label: String,
        isScrollAction: Boolean,
        currentFocusedBounds: Rect?,
        targetBounds: Rect?
    ): Boolean {
        return false
    }

    internal fun isNodePhysicallyOffScreen(bounds: Rect, screenTop: Int, screenBottom: Int): Boolean {
        return bounds.bottom <= screenTop || bounds.top >= screenBottom
    }

    internal fun shouldTriggerLoopFallback(
        focusedAny: Boolean,
        isScrollAction: Boolean,
        excludeDesc: String?
    ): Boolean {
        return !focusedAny && isScrollAction && !excludeDesc.isNullOrBlank()
    }

    internal fun isBottomClippedWithPadding(boundsBottom: Int, effectiveBottom: Int, paddingPx: Int = 300): Boolean {
        return boundsBottom > (effectiveBottom - paddingPx)
    }

    internal fun shouldAlignToRealTop(boundsTop: Int, screenTop: Int, topPaddingPx: Int = 300): Boolean {
        return boundsTop > (screenTop + topPaddingPx)
    }

    internal fun shouldTriggerShowOnScreen(
        bounds: Rect,
        effectiveBottom: Int,
        screenTop: Int,
        isScrollAction: Boolean,
        isTopBar: Boolean,
        isBottomBar: Boolean
    ): Boolean {
        val isFixedBar = isTopBar || isBottomBar
        if (isFixedBar) return false

        val needBottomLift = isBottomClippedWithPadding(bounds.bottom, effectiveBottom)
        val needTopAlign = isScrollAction && shouldAlignToRealTop(bounds.top, screenTop)
        return needBottomLift || needTopAlign
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
            !isTopAppBarNode(classNameOf(candidate), viewIdOf(candidate), bounds, screenTop, screenHeight) &&
                !isBottomNavigationBarNode(classNameOf(candidate), viewIdOf(candidate), bounds, screenBottom, screenHeight)
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
            !isTopAppBarNode(classNameOf(node), viewIdOf(node), bounds, screenTop, screenHeight) &&
                !isBottomNavigationBarNode(classNameOf(node), viewIdOf(node), bounds, screenBottom, screenHeight) &&
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
            if (isTopAppBarNode(classNameOf(node), viewIdOf(node), bounds, screenTop, screenHeight)) continue
            if (isBottomNavigationBarNode(classNameOf(node), viewIdOf(node), bounds, screenBottom, screenHeight)) continue
            if (isFixedUiOf?.invoke(node) == true) continue

            val normalizedClass = classNameOf(node)?.lowercase().orEmpty()
            val normalizedViewId = viewIdOf(node)?.substringAfterLast('/')?.lowercase().orEmpty()
            val isWrapperOrContainer =
                TRAVERSAL_CONTAINER_CLASS_KEYWORDS.any { keyword -> normalizedClass.contains(keyword) } ||
                    TRAVERSAL_CONTAINER_VIEW_ID_KEYWORDS.any { keyword -> normalizedViewId.contains(keyword) }
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
        } || !isTopAppBarNode(currentClass, currentViewId, currentBounds, screenTop, screenHeight)

        if (!currentLooksLikeGridOrShortcut) return false

        val nextNode = traversalList[nextIndex]
        val nextBounds = boundsOf(nextNode)
        val nextIsBottomBar = isBottomNavigationBarNode(
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

    private fun focusBottomBarAfterNoProgress(
        root: AccessibilityNodeInfo,
        traversalList: List<AccessibilityNodeInfo>,
        bottomBarNode: AccessibilityNodeInfo,
        bottomBarIndex: Int
    ): TargetActionOutcome {
        val bottomBarBounds = Rect().also { bottomBarNode.getBoundsInScreen(it) }
        val focusedNode = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val focusedBounds = focusedNode?.let { Rect().also(it::getBoundsInScreen) }
        val rootRect = Rect().also { root.getBoundsInScreen(it) }
        val screenHeight = (rootRect.bottom - rootRect.top).coerceAtLeast(1)
        val focusIsTopLoopProne = focusedNode != null && focusedBounds != null && isTopLoopProneControlNode(
            node = focusedNode,
            bounds = focusedBounds,
            screenTop = rootRect.top,
            screenHeight = screenHeight,
            classNameOf = { it.className?.toString() },
            viewIdOf = { it.viewIdResourceName }
        )
        if (focusIsTopLoopProne) {
            Log.w("A11Y_HELPER", "[SMART_NEXT] Focus jumped to top loop-prone control after no-progress scroll. Forcing bottom bar fallback.")
        }

        val focused = performFocusWithVisibilityCheck(
            root = root,
            target = bottomBarNode,
            screenTop = rootRect.top,
            effectiveBottom = rootRect.bottom,
            status = "moved_to_bottom_bar_after_no_progress",
            isScrollAction = false,
            traversalIndex = bottomBarIndex,
            traversalListSnapshot = traversalList,
            currentFocusIndexHint = (bottomBarIndex - 1).coerceAtLeast(-1)
        )
        if (focused.success) {
            return TargetActionOutcome(true, "moved_to_bottom_bar_after_no_progress", bottomBarNode)
        }

        val actualFocusedIndex = resolveFocusedIndexInTraversal(root, traversalList)
        if (actualFocusedIndex != -1) {
            setLastRequestedFocusIndex(actualFocusedIndex)
        }
        Log.w(
            "A11Y_HELPER",
            "[SMART_NEXT] Bottom bar fallback focus failed after no-progress scroll. actualFocusedIndex=$actualFocusedIndex targetBounds=$bottomBarBounds focusedBounds=$focusedBounds"
        )
        return focused
    }

    private fun resolveFocusedIndexInTraversal(
        root: AccessibilityNodeInfo,
        traversalList: List<AccessibilityNodeInfo>
    ): Int {
        val focusedNode = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY) ?: return -1
        val focusedNodeObjectId = nodeObjectId(focusedNode)
        val directObjectIndex = traversalList.indexOfFirst { nodeObjectId(it) == focusedNodeObjectId }
        if (directObjectIndex != -1) return directObjectIndex
        return findNodeIndexByIdentity(
            nodes = traversalList,
            target = focusedNode,
            idOf = { it.viewIdResourceName },
            textOf = { it.text?.toString() },
            contentDescriptionOf = { it.contentDescription?.toString() },
            boundsOf = { Rect().also(it::getBoundsInScreen) }
        )
    }

    private fun syncLastRequestedFocusIndexToCurrentFocus(
        root: AccessibilityNodeInfo,
        traversalList: List<AccessibilityNodeInfo>
    ) {
        val focusedIndex = resolveFocusedIndexInTraversal(root, traversalList)
        if (focusedIndex == -1) {
            Log.w("A11Y_HELPER", "[SMART_NEXT] Failed to sync lastRequestedFocusIndex after no-progress scroll: focused index not found")
            return
        }
        setLastRequestedFocusIndex(focusedIndex)
        Log.i("A11Y_HELPER", "[SMART_NEXT] Synced lastRequestedFocusIndex to actual focused index=$focusedIndex after no-progress scroll")
    }

    internal fun buildNodeTextSnapshot(nodes: List<AccessibilityNodeInfo>): String {
        val screenBounds = nodes.firstOrNull()?.let { node ->
            Rect().also { node.getBoundsInScreen(it) }
        }
        val screenTop = screenBounds?.top ?: 0
        val screenBottom = screenBounds?.bottom ?: Int.MAX_VALUE
        val screenHeight = (screenBottom - screenTop).coerceAtLeast(1)

        return nodes.joinToString(separator = "") { node ->
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            val isTopBar = isTopAppBarNode(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = bounds,
                screenTop = screenTop,
                screenHeight = screenHeight
            )
            val isBottomBar = isBottomNavigationBarNode(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = bounds,
                screenBottom = screenBottom,
                screenHeight = screenHeight
            )

            if (isTopBar || isBottomBar) {
                ""
            } else {
                buildSnapshotToken(
                    text = node.text?.toString(),
                    contentDescription = node.contentDescription?.toString(),
                    viewIdResourceName = node.viewIdResourceName
                )
            }
        }.trim('\u001f')
    }

    internal fun buildNodeTextSnapshot(root: AccessibilityNodeInfo): String {
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        val tokens = mutableListOf<String>()
        val screenRect = Rect().also { root.getBoundsInScreen(it) }
        val screenTop = screenRect.top
        val screenBottom = screenRect.bottom
        val screenHeight = (screenBottom - screenTop).coerceAtLeast(1)
        stack.add(root)

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            val isTopBar = isTopAppBarNode(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = bounds,
                screenTop = screenTop,
                screenHeight = screenHeight
            )
            val isBottomBar = isBottomNavigationBarNode(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = bounds,
                screenBottom = screenBottom,
                screenHeight = screenHeight
            )
            if (!isTopBar && !isBottomBar) {
                tokens += buildSnapshotToken(
                    text = node.text?.toString(),
                    contentDescription = node.contentDescription?.toString(),
                    viewIdResourceName = node.viewIdResourceName
                )
            }

            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let(stack::add)
            }
        }

        return tokens.joinToString(separator = "")
    }

    private fun pollForUpdatedRoot(
        service: A11yHelperService?,
        oldSnapshot: String,
        fallbackRoot: AccessibilityNodeInfo?
    ): AccessibilityNodeInfo? {
        Thread.sleep(200)

        var latestRoot = fallbackRoot
        var treeUpdated = false
        for (i in 1..10) {
            Thread.sleep(150)
            val newRoot = service?.rootInActiveWindow ?: continue
            latestRoot = newRoot
            val newSnapshot = buildNodeTextSnapshot(newRoot)

            if (oldSnapshot != newSnapshot) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Tree change detected, waiting for settling...")
                Thread.sleep(300)
                latestRoot = service?.rootInActiveWindow ?: newRoot
                Log.i("A11Y_HELPER", "[SMART_NEXT] Tree updated successfully at loop $i after settling wait")
                treeUpdated = true
                break
            }
        }

        if (!treeUpdated) {
            Log.w("A11Y_HELPER", "[SMART_NEXT] Tree did not change after 10 polling loops. Applying final 500ms safeguard.")
            Thread.sleep(500)
            latestRoot = service?.rootInActiveWindow ?: latestRoot
        }

        return latestRoot
    }

    private fun buildSnapshotToken(
        text: String?,
        contentDescription: String?,
        viewIdResourceName: String?
    ): String {
        return listOf(
            text?.trim().orEmpty(),
            contentDescription?.trim().orEmpty(),
            viewIdResourceName?.trim().orEmpty()
        ).joinToString(separator = "|")
    }

    internal fun <T> calculateEffectiveBottom(
        nodes: List<T>,
        screenTop: Int,
        screenBottom: Int,
        boundsOf: (T) -> Rect,
        labelOf: (T) -> String?
    ): Int {
        var effectiveBottom = screenBottom
        val screenHeight = (screenBottom - screenTop).coerceAtLeast(1)
        val lowerHalfTopBoundary = screenBottom - (screenHeight / 2)
        nodes.forEach { node ->
            val bounds = boundsOf(node)
            val normalizedLabel = labelOf(node)?.lowercase().orEmpty()
            val isBottomNavigation = normalizedLabel.contains("bottom") ||
                normalizedLabel.contains("footer") ||
                normalizedLabel.contains("tab bar") ||
                normalizedLabel.contains("tabbar") ||
                normalizedLabel.contains("navigation") ||
                normalizedLabel.contains("menu") ||
                normalizedLabel.contains("bottom_nav") ||
                normalizedLabel.contains("bottomnav")
            val isInLowerHalf = bounds.top > lowerHalfTopBoundary
            if (isInLowerHalf && isBottomNavigation) {
                effectiveBottom = minOf(effectiveBottom, bounds.top)
                val nodeLabel = labelOf(node).orEmpty().ifBlank { "<no-label>" }
                Log.i("A11Y_HELPER", "[SMART_NEXT] Effective bottom set to $effectiveBottom by node: $nodeLabel")
            }
        }
        effectiveBottom = applyBottomNavigationSafetyGuide(
            effectiveBottom = effectiveBottom,
            screenBottom = screenBottom
        )
        return effectiveBottom
    }

    internal fun <T> findMainScrollContainer(
        nodes: List<T>,
        isScrollable: (T) -> Boolean,
        boundsOf: (T) -> Rect
    ): T? {
        return nodes
            .asSequence()
            .filter(isScrollable)
            .maxByOrNull { node ->
                val bounds = boundsOf(node)
                val width = (bounds.right - bounds.left).coerceAtLeast(0)
                val height = (bounds.bottom - bounds.top).coerceAtLeast(0)
                width.toLong() * height.toLong()
            }
    }

    private fun findMainScrollContainer(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (root == null) return null
        val nodes = mutableListOf<AccessibilityNodeInfo>()
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            if (node.isVisibleToUser) {
                nodes += node
            }
            for (index in 0 until node.childCount) {
                node.getChild(index)?.let(queue::add)
            }
        }
        return findMainScrollContainer(
            nodes = nodes,
            isScrollable = { it.isScrollable },
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } }
        )
    }

    internal fun <T> isDescendantOf(
        ancestor: T,
        node: T,
        parentOf: (T) -> T?
    ): Boolean {
        var current = parentOf(node)
        while (current != null) {
            if (current == ancestor) return true
            current = parentOf(current)
        }
        return false
    }

    internal fun <T> isFixedSystemUI(
        node: T,
        mainScrollContainer: T?,
        parentOf: (T) -> T?,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        textOf: (T) -> String?,
        contentDescriptionOf: (T) -> String?
    ): Boolean {
        val toolbarKeywords = listOf("toolbar", "actionbar", "bottomnavigationview")
        var current: T? = node
        while (current != null) {
            val className = classNameOf(current)?.lowercase().orEmpty()
            val viewId = viewIdOf(current)?.lowercase().orEmpty()
            if (toolbarKeywords.any { keyword -> className.contains(keyword) || viewId.contains(keyword) }) {
                return true
            }
            current = parentOf(current)
        }

        val className = classNameOf(node)?.substringAfterLast('.')?.lowercase().orEmpty()
        val isStrictFixedButtonClass = className == "button" || className == "imagebutton"
        if (!isStrictFixedButtonClass) {
            return false
        }

        val outsideMainScroll = mainScrollContainer == null || (node != mainScrollContainer && !isDescendantOf(mainScrollContainer, node, parentOf))
        if (outsideMainScroll) {
            return true
        }

        val normalizedLabel = listOfNotNull(textOf(node), contentDescriptionOf(node))
            .joinToString(separator = " ")
            .lowercase()
        val isSystemButton = normalizedLabel.contains("add") || normalizedLabel.contains("more options")
        return isSystemButton && outsideMainScroll
    }

    private fun isFixedSystemUI(node: AccessibilityNodeInfo, mainScrollContainer: AccessibilityNodeInfo?): Boolean {
        if (isOneConnectSettingsCandidateNode(node)) {
            return false
        }
        return isFixedSystemUI(
            node = node,
            mainScrollContainer = mainScrollContainer,
            parentOf = { it.parent },
            classNameOf = { it.className?.toString() },
            viewIdOf = { it.viewIdResourceName },
            textOf = { it.text?.toString() },
            contentDescriptionOf = { it.contentDescription?.toString() }
        )
    }

    internal fun <T> collectVisibleHistory(
        nodes: List<T>,
        screenTop: Int,
        screenBottom: Int,
        boundsOf: (T) -> Rect,
        labelOf: (T) -> String?,
        isTopAppBarNodeOf: (T, Rect) -> Boolean = { _, _ -> false },
        isBottomNavigationBarNodeOf: (T, Rect) -> Boolean = { _, _ -> false }
    ): Set<String> {
        return nodes.mapNotNull { node ->
            val bounds = boundsOf(node)
            if (isNodePhysicallyOffScreen(bounds, screenTop, screenBottom)) {
                return@mapNotNull null
            }
            if (isTopAppBarNodeOf(node, bounds) || isBottomNavigationBarNodeOf(node, bounds)) {
                return@mapNotNull null
            }
            labelOf(node)?.trim()?.takeUnless { it.isEmpty() }
        }.toSet()
    }

    internal fun <T> collectVisibleHistorySignatures(
        nodes: List<T>,
        screenTop: Int,
        screenBottom: Int,
        boundsOf: (T) -> Rect,
        labelOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        isTopAppBarNodeOf: (T, Rect) -> Boolean = { _, _ -> false },
        isBottomNavigationBarNodeOf: (T, Rect) -> Boolean = { _, _ -> false }
    ): Set<VisibleHistorySignature> {
        return nodes.mapNotNull { node ->
            val bounds = boundsOf(node)
            if (isNodePhysicallyOffScreen(bounds, screenTop, screenBottom)) {
                return@mapNotNull null
            }
            if (isTopAppBarNodeOf(node, bounds) || isBottomNavigationBarNodeOf(node, bounds)) {
                return@mapNotNull null
            }
            VisibleHistorySignature(
                label = labelOf(node)?.trim()?.takeUnless { it.isEmpty() },
                viewId = viewIdOf(node)?.trim()?.takeUnless { it.isEmpty() },
                bounds = Rect(bounds),
                nodeIdentity = null
            )
        }.toSet()
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

    internal fun isWithinTopContentArea(
        nodeTop: Int,
        screenTop: Int,
        screenHeight: Int,
        topAreaMaxPx: Int = 500
    ): Boolean {
        val topAreaBoundary = screenTop + minOf(screenHeight / 5, topAreaMaxPx)
        return nodeTop < topAreaBoundary
    }

    internal fun shouldAcceptFallbackSelectedNoLabelContinuationCandidate(
        isFallbackSelectedContinuationCandidate: Boolean,
        isTopBar: Boolean,
        isBottomBar: Boolean,
        bounds: Rect,
        screenTop: Int,
        effectiveBottom: Int
    ): Boolean {
        if (!isFallbackSelectedContinuationCandidate) return false
        if (isTopBar || isBottomBar) return false
        return isWithinContentViewport(bounds, screenTop, effectiveBottom)
    }

    internal fun isWithinContentViewport(bounds: Rect, screenTop: Int, effectiveBottom: Int): Boolean {
        return bounds.bottom > screenTop && bounds.top < effectiveBottom
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

    internal fun isContainerLikeClassName(className: String?): Boolean {
        val normalized = className?.trim()?.lowercase().orEmpty()
        if (normalized.isEmpty()) return false
        return TRAVERSAL_CONTAINER_CLASS_KEYWORDS.any { keyword -> normalized.contains(keyword) }
    }

    internal fun isContainerLikeViewId(viewIdResourceName: String?): Boolean {
        val normalized = viewIdResourceName?.substringAfterLast('/')?.trim()?.lowercase().orEmpty()
        if (normalized.isEmpty()) return false
        return TRAVERSAL_CONTAINER_VIEW_ID_KEYWORDS.any { keyword -> normalized.contains(keyword) }
    }

    private fun shouldExcludeContainerNodeFromTraversal(
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

    private fun hasMultipleSiblingLevelInteractiveDescendants(node: AccessibilityNodeInfo): Boolean {
        val directInteractiveChildren = countDirectInteractiveChildren(node, limit = 2)
        if (directInteractiveChildren >= 2) return true
        val descendantInteractiveChildren = countClickableOrFocusableDescendants(node, limit = 3)
        return descendantInteractiveChildren >= 3 && doesNodeCoverMostContentArea(node)
    }

    private fun countDirectInteractiveChildren(node: AccessibilityNodeInfo, limit: Int): Int {
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

    private fun doesNodeCoverMostContentArea(node: AccessibilityNodeInfo): Boolean {
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

    private fun resolveRootBounds(node: AccessibilityNodeInfo): Rect? {
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

    private fun countClickableOrFocusableDescendants(node: AccessibilityNodeInfo, limit: Int): Int {
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

    private fun recoverDescendantLabel(node: AccessibilityNodeInfo): String? {
        val textCandidates = collectDescendantTextCandidates(node)
        return recoverLabelFromDescendantTexts(textCandidates)
    }

    fun findSwipeTarget(
        root: AccessibilityNodeInfo?,
        currentNode: AccessibilityNodeInfo?,
        forward: Boolean
    ): AccessibilityNodeInfo? {
        if (root == null) return null
        val traversalList = buildFocusableTraversalList(root)
        if (traversalList.isEmpty()) return null

        val resolvedCurrent = currentNode?.let {
            resolveToClickableAncestor(
                node = it,
                parentOf = { node -> node.parent },
                isClickable = { node -> node.isClickable }
            )
        }

        val currentIndex = resolvedCurrent?.let { resolved ->
            findNodeIndexByIdentity(
                nodes = traversalList,
                target = resolved,
                idOf = { it.viewIdResourceName },
                textOf = { node -> node.text?.toString() },
                contentDescriptionOf = { node -> node.contentDescription?.toString() },
                boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } }
            )
        } ?: -1

        val targetIndex = if (forward) {
            currentIndex + 1
        } else {
            if (currentIndex == -1) traversalList.lastIndex else currentIndex - 1
        }

        if (targetIndex !in traversalList.indices) return null
        return traversalList[targetIndex]
    }

    internal fun <T> resolveToClickableAncestor(
        node: T,
        parentOf: (T) -> T?,
        isClickable: (T) -> Boolean
    ): T {
        if (isClickable(node)) return node

        var current = parentOf(node)
        while (current != null) {
            if (isClickable(current)) return current
            current = parentOf(current)
        }
        return node
    }

    internal fun <T> buildGroupedTraversalList(
        nodesInOrder: List<T>,
        parentOf: (T) -> T?,
        isClickable: (T) -> Boolean,
        isFocusable: (T) -> Boolean,
        isVisible: (T) -> Boolean
    ): List<T> {
        val results = mutableListOf<T>()

        for (node in nodesInOrder) {
            if (!isVisible(node)) continue
            if (hasClickableAncestor(node, parentOf, isClickable)) continue
            if (!isClickable(node) && !isFocusable(node)) continue
            results += node
        }
        return results
    }

    private fun matchesTarget(node: AccessibilityNodeInfo, query: TargetQuery): Boolean {
        val text = node.text?.toString()
        val description = node.contentDescription?.toString()
        return matchesTarget(
            text,
            description,
            node.viewIdResourceName,
            node.className?.toString(),
            node.isClickable,
            node.isFocusable,
            query
        )
    }

    private fun resolveMatchedTarget(node: AccessibilityNodeInfo, query: TargetQuery): AccessibilityNodeInfo? {
        val queryWithoutClickable = if (query.clickable != null) query.copy(clickable = null) else query
        if (!matchesTarget(node, queryWithoutClickable)) return null

        val resolvedNode = resolveToClickableAncestor(
            node = node,
            parentOf = { current -> current.parent },
            isClickable = { current -> current.isClickable }
        )

        query.clickable?.let { expected ->
            if (resolvedNode.isClickable != expected) return null
        }
        return resolvedNode
    }


    private fun <T> hasClickableAncestor(
        node: T,
        parentOf: (T) -> T?,
        isClickable: (T) -> Boolean
    ): Boolean {
        var parent = parentOf(node)
        while (parent != null) {
            if (isClickable(parent)) return true
            parent = parentOf(parent)
        }
        return false
    }

    private fun buildFocusableTraversalList(root: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
        return buildTalkBackLikeFocusNodes(root).map { it.node }
    }

    private data class FocusedNode(
        val node: AccessibilityNodeInfo,
        val text: String?,
        val contentDescription: String?,
        val mergedLabel: String?
    )

    private fun buildTalkBackLikeFocusNodes(root: AccessibilityNodeInfo): List<FocusedNode> {
        val focusNodes = mutableListOf<FocusedNode>()
        collectFocusableNodes(node = root, containerAncestor = null, sink = focusNodes)

        val filteredNodes = focusNodes
            .filterNot { shouldExcludeAsEmptyShell(it) }
            .sortedWith(spatialComparator())
        logSettingsCandidateStatus(root, filteredNodes)
        return filteredNodes
    }

    private fun collectFocusableNodes(
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

        val nextContainer = if (container) node else containerAncestor
        for (i in 0 until node.childCount) {
            node.getChild(i)?.let { child ->
                collectFocusableNodes(node = child, containerAncestor = nextContainer, sink = sink)
            }
        }
    }

    private fun collectMergedTextFromContainer(container: AccessibilityNodeInfo): List<String> {
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

    private fun collectDescendantReadableText(
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

    private fun isFocusContainer(node: AccessibilityNodeInfo): Boolean {
        val screenReaderFocusable = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && node.isScreenReaderFocusable
        return node.isClickable || node.isFocusable || screenReaderFocusable || isSettingsRowViewId(node.viewIdResourceName)
    }

    internal fun isSettingsRowViewId(viewIdResourceName: String?): Boolean {
        val normalized = viewIdResourceName?.substringAfterLast('/')?.trim().orEmpty()
        if (normalized.isEmpty()) return false
        return SETTINGS_ROW_VIEW_IDS.contains(normalized)
    }

    private val SETTINGS_ROW_VIEW_ID_ORDERED = listOf(
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
    private val SETTINGS_ROW_VIEW_IDS = SETTINGS_ROW_VIEW_ID_ORDERED.toSet()

    private fun hasAnyText(node: AccessibilityNodeInfo): Boolean {
        val text = node.text?.toString()?.trim().orEmpty()
        val description = node.contentDescription?.toString()?.trim().orEmpty()
        return text.isNotEmpty() || description.isNotEmpty()
    }

    private fun shouldExcludeAsEmptyShell(node: FocusedNode): Boolean {
        val current = node.node
        if (isSettingsRowViewId(current.viewIdResourceName) && current.isVisibleToUser && (current.isClickable || current.isFocusable)) {
            return false
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

    private fun isOneConnectSettingsCandidateNode(
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
        return SETTINGS_BUTTON_KEYWORDS.any { keyword ->
            normalizedViewId.contains(keyword) || mergedLabel.contains(keyword)
        }
    }

    private fun logSettingsCandidateStatus(root: AccessibilityNodeInfo, traversalNodes: List<FocusedNode>) {
        val rawSettingNode = findFirstMatchingNode(root) { node ->
            isOneConnectSettingsCandidateNode(node, recoverDescendantLabel(node))
        }
        Log.i("A11Y_HELPER", "[SMART_NEXT] SETTINGS_CANDIDATE raw_found=${rawSettingNode != null}")

        val traversalSettingNode = traversalNodes.firstOrNull { focused ->
            isOneConnectSettingsCandidateNode(focused.node, focused.mergedLabel ?: recoverDescendantLabel(focused.node))
        }
        Log.i("A11Y_HELPER", "[SMART_NEXT] SETTINGS_CANDIDATE in_traversal=${traversalSettingNode != null}")

        val smartThingsIndex = traversalNodes.indexOfFirst { node ->
            val label = node.text?.trim()
                ?: node.contentDescription?.trim()
                ?: node.mergedLabel?.trim()
                ?: recoverDescendantLabel(node.node)?.trim()
            label.equals("SmartThings", ignoreCase = true)
        }
        val smartThingsNextLabel = if (smartThingsIndex >= 0 && smartThingsIndex + 1 < traversalNodes.size) {
            traversalNodes[smartThingsIndex + 1].text?.trim()
                ?: traversalNodes[smartThingsIndex + 1].contentDescription?.trim()
                ?: traversalNodes[smartThingsIndex + 1].mergedLabel?.trim()
                ?: recoverDescendantLabel(traversalNodes[smartThingsIndex + 1].node)?.trim()
                ?: "<no-label>"
        } else {
            "<none>"
        }
        Log.i("A11Y_HELPER", "[SMART_NEXT] SETTINGS_CANDIDATE next_after_smartthings=$smartThingsNextLabel")
    }

    private fun findFirstMatchingNode(
        root: AccessibilityNodeInfo,
        predicate: (AccessibilityNodeInfo) -> Boolean
    ): AccessibilityNodeInfo? {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        while (queue.isNotEmpty()) {
            val current = queue.removeFirst()
            if (predicate(current)) {
                return current
            }
            for (index in 0 until current.childCount) {
                current.getChild(index)?.let(queue::add)
            }
        }
        return null
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

    private fun spatialComparator(yBucketSize: Int = 5): Comparator<FocusedNode> {
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

    private fun <T> isAncestorOf(
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

    internal fun <T> findCurrentTraversalIndex(
        traversalList: List<T>,
        currentNode: T,
        isSameNodeMatch: (T, T) -> Boolean
    ): Int {
        if (traversalList.isEmpty()) return -1
        val lastIndex = traversalList.lastIndex
        if (isSameNodeMatch(traversalList[lastIndex], currentNode)) {
            return lastIndex
        }
        return traversalList.indexOfFirst { candidate ->
            isSameNodeMatch(candidate, currentNode)
        }
    }

    internal fun isSameNode(a: AccessibilityNodeInfo, b: AccessibilityNodeInfo): Boolean {
        val aBounds = Rect().also { a.getBoundsInScreen(it) }
        val bBounds = Rect().also { b.getBoundsInScreen(it) }

        return isSameNodeIdentity(
            aId = a.viewIdResourceName,
            aText = a.text?.toString(),
            aContentDescription = a.contentDescription?.toString(),
            aBounds = aBounds,
            bId = b.viewIdResourceName,
            bText = b.text?.toString(),
            bContentDescription = b.contentDescription?.toString(),
            bBounds = bBounds
        )
    }

    internal fun isSameNodeIdentity(
        aId: String?,
        aText: String?,
        aContentDescription: String?,
        aBounds: Rect,
        bId: String?,
        bText: String?,
        bContentDescription: String?,
        bBounds: Rect
    ): Boolean {
        if (
            aBounds.left == bBounds.left &&
            aBounds.top == bBounds.top &&
            aBounds.right == bBounds.right &&
            aBounds.bottom == bBounds.bottom
        ) {
            return true
        }

        val identityMatch = aId == bId && aText == bText && aContentDescription == bContentDescription
        if (!identityMatch) {
            return false
        }

        return aBounds.left == bBounds.left &&
            aBounds.top == bBounds.top &&
            aBounds.right == bBounds.right &&
            aBounds.bottom == bBounds.bottom
    }

    internal fun isWithinSnapBackTolerance(targetBounds: Rect, actualBounds: Rect, tolerancePx: Int = 10): Boolean {
        val targetCenterX = targetBounds.centerX()
        val targetCenterY = targetBounds.centerY()
        val actualCenterX = actualBounds.centerX()
        val actualCenterY = actualBounds.centerY()
        return kotlin.math.abs(targetCenterX - actualCenterX) <= tolerancePx &&
            kotlin.math.abs(targetCenterY - actualCenterY) <= tolerancePx
    }

    internal fun <T> findClosestNodeBelowCenter(
        nodes: List<T>,
        reference: T,
        boundsOf: (T) -> Rect
    ): Int {
        val referenceBounds = boundsOf(reference)
        val referenceCenterY = (referenceBounds.top + referenceBounds.bottom) / 2

        var nearestIndex = -1
        var nearestDistance = Int.MAX_VALUE

        nodes.forEachIndexed { index, node ->
            val bounds = boundsOf(node)
            val centerY = (bounds.top + bounds.bottom) / 2
            if (centerY > referenceCenterY) {
                val distance = centerY - referenceCenterY
                if (distance < nearestDistance) {
                    nearestDistance = distance
                    nearestIndex = index
                }
            }
        }

        return nearestIndex
    }

    private fun isViewIdMatched(nodeViewId: String?, target: String): Boolean {
        val regexPattern = buildRegexPattern(target)
        return nodeViewId?.let { viewId ->
            runCatching { Regex(regexPattern, setOf(RegexOption.IGNORE_CASE)) }
                .getOrNull()
                ?.matches(viewId)
                ?: false
        } ?: false
    }

    private fun isRegexPattern(target: String): Boolean {
        return target.contains(".*") ||
            target.contains(".+") ||
            target.contains("^") ||
            target.contains("$")
    }

    private fun buildRegexPattern(target: String): String {
        return if (isRegexPattern(target)) {
            target
        } else {
            "^${Regex.escape(target)}$"
        }
    }


    internal fun <T> hasScrollableDownCandidate(
        nodesInOrder: List<T>,
        isScrollable: (T) -> Boolean,
        canScrollVerticallyDown: (T) -> Boolean
    ): Boolean {
        return nodesInOrder.any { node ->
            isScrollable(node) && canScrollVerticallyDown(node)
        }
    }

    internal fun <T> hasScrollableDownCandidateByAction(
        nodesInOrder: List<T>,
        isVisibleToUser: (T) -> Boolean,
        isScrollable: (T) -> Boolean,
        hasScrollForwardAction: (T) -> Boolean
    ): Boolean {
        return nodesInOrder.any { node ->
            isVisibleToUser(node) && isScrollable(node) && hasScrollForwardAction(node)
        }
    }

    private fun hasScrollableDownCandidate(root: AccessibilityNodeInfo?): Boolean {
        return findScrollableForwardCandidate(root) != null
    }

    private fun findScrollableForwardCandidate(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (root == null) return null

        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)

        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            val hasScrollableDown = hasScrollableDownCandidateByAction(
                nodesInOrder = listOf(node),
                isVisibleToUser = { it.isVisibleToUser },
                isScrollable = { it.isScrollable },
                hasScrollForwardAction = {
                    it.actionList.contains(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_FORWARD)
                }
            )
            if (hasScrollableDown) {
                return node
            }

            for (index in 0 until node.childCount) {
                node.getChild(index)?.let { queue.add(it) }
            }
        }
        return null
    }

    private fun findScrollableForwardAncestorCandidate(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        return findScrollableForwardAncestorCandidate(
            node = node,
            parentOf = { it.parent },
            isScrollable = { it.isScrollable },
            hasScrollForwardAction = {
                it.actionList.contains(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_FORWARD)
            }
        )
    }

    internal fun <T> findScrollableForwardAncestorCandidate(
        node: T?,
        parentOf: (T) -> T?,
        isScrollable: (T) -> Boolean,
        hasScrollForwardAction: (T) -> Boolean
    ): T? {
        var current = node?.let(parentOf)
        while (current != null) {
            if (isScrollable(current) && hasScrollForwardAction(current)) {
                return current
            }
            current = parentOf(current)
        }
        return null
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

    internal fun shouldIgnoreBottomResidualFocus(
        isAccessibilityFocused: Boolean,
        nodeBounds: Rect,
        screenBottom: Int,
        screenHeight: Int
    ): Boolean {
        if (!isAccessibilityFocused) return false
        val bottomTwentyPercentBoundary = screenBottom - (screenHeight * 0.2f).toInt()
        return nodeBounds.top >= bottomTwentyPercentBoundary
    }

    internal fun shouldExcludeNodeByIdentity(
        nodeViewId: String?,
        nodeText: String?,
        excludeViewId: String?,
        excludeText: String?
    ): Boolean {
        val normalizedNodeText = nodeText?.trim().orEmpty()
        val normalizedExcludeText = excludeText?.trim().orEmpty()

        val sameViewId = !excludeViewId.isNullOrBlank() && !nodeViewId.isNullOrBlank() && nodeViewId == excludeViewId
        val sameText = normalizedExcludeText.isNotEmpty() && normalizedNodeText.isNotEmpty() && normalizedNodeText == normalizedExcludeText
        return sameViewId || sameText
    }

    internal fun isTopAppBarNode(
        className: String?,
        viewIdResourceName: String?,
        boundsInScreen: Rect,
        screenTop: Int,
        screenHeight: Int
    ): Boolean {
        val normalizedClass = className?.lowercase().orEmpty()
        val normalizedViewId = viewIdResourceName?.lowercase().orEmpty()
        if (SETTINGS_BUTTON_KEYWORDS.any { keyword -> normalizedViewId.contains(keyword) }) {
            return false
        }

        val matchesClass = normalizedClass.contains("toolbar") ||
            normalizedClass.contains("actionbar") ||
            normalizedClass.contains("appbarlayout")
        if (matchesClass) return true

        val matchesViewId = normalizedViewId.contains("title_bar") ||
            normalizedViewId.contains("header") ||
            normalizedViewId.contains("toolbar") ||
            normalizedViewId.contains("more_menu") ||
            normalizedViewId.contains("action_bar") ||
            normalizedViewId.contains("home_button") ||
            normalizedViewId.contains("tab_title") ||
            normalizedViewId.contains("header_bar") ||
            normalizedViewId.contains("add_menu") ||
            normalizedViewId.contains("add_button") ||
            normalizedViewId.contains("menu_button")
        if (matchesViewId) return true

        return false
    }

    @Suppress("UNUSED_PARAMETER")
    internal fun isBottomNavigationBarNode(
        className: String?,
        viewIdResourceName: String?,
        boundsInScreen: Rect,
        screenBottom: Int,
        screenHeight: Int
    ): Boolean {
        // NOTE: 좌표 기반(bottom 20% 등) 판별은 컨텐츠 카드 오검출을 유발할 수 있어 사용하지 않는다.
        val normalizedClass = className?.lowercase().orEmpty()
        val normalizedViewId = viewIdResourceName?.lowercase().orEmpty()

        val matchesClass = normalizedClass.contains("bottomnavigation") ||
            normalizedClass.contains("tablayout") ||
            normalizedClass.contains("navigationbar")
        if (matchesClass) return true

        val matchesViewId = normalizedViewId.contains("bottom") ||
            normalizedViewId.contains("footer") ||
            normalizedViewId.contains("tab_bar") ||
            normalizedViewId.contains("navigation") ||
            normalizedViewId.contains("menu_bar") ||
            normalizedViewId.contains("menu_favorites") ||
            normalizedViewId.contains("menu_devices") ||
            normalizedViewId.contains("menu_life") ||
            normalizedViewId.contains("menu_services") ||
            normalizedViewId.contains("menu_automations") ||
            normalizedViewId.contains("menu_more") ||
            normalizedViewId.contains("menu_routines") ||
            normalizedViewId.contains("menu_menu") ||
            normalizedViewId.contains("bottom_menu") ||
            normalizedViewId.contains("bottom_tab") ||
            normalizedViewId.contains("bottom_nav")
        if (matchesViewId) return true

        return false
    }

    private fun nodeToModel(
        node: AccessibilityNodeInfo,
        textOverride: String? = null,
        contentDescriptionOverride: String? = null,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int
    ): A11yNodeInfo {
        val rect = Rect()
        node.getBoundsInScreen(rect)

        return A11yNodeInfo(
            text = textOverride ?: node.text?.toString(),
            contentDescription = contentDescriptionOverride ?: node.contentDescription?.toString(),
            className = node.className?.toString(),
            viewIdResourceName = node.viewIdResourceName,
            boundsInScreen = rect,
            clickable = node.isClickable,
            focusable = node.isFocusable,
            isVisibleToUser = node.isVisibleToUser,
            focused = node.isFocused,
            accessibilityFocused = node.isAccessibilityFocused,
            isTopAppBar = isTopAppBarNode(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = rect,
                screenTop = screenTop,
                screenHeight = screenHeight
            ),
            isBottomNavigationBar = isBottomNavigationBarNode(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = rect,
                screenBottom = screenBottom,
                screenHeight = screenHeight
            )
        )
    }
}
