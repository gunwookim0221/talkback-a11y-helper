package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityEvent
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat
import org.json.JSONObject
import kotlin.math.abs

typealias PreScrollAnchor = A11yHistoryManager.PreScrollAnchor
typealias VisibleHistorySignature = A11yHistoryManager.VisibleHistorySignature

object A11yNavigator {
    const val NAVIGATOR_ALGORITHM_VERSION: String = "2.50.0"
    private const val RETARGET_SUPPRESSION_WINDOW_MS: Long = 400L
    private const val ONECONNECT_PACKAGE_NAME = "com.samsung.android.oneconnect"

    private val visitedHistoryLock = Any()
    private val visitedHistoryLabels = linkedSetOf<String>()
    private val visitedHistorySignatures = mutableListOf<VisibleHistorySignature>()

    @Volatile
    private var lastRequestedFocusIndex: Int = A11yStateStore.lastRequestedFocusIndex

    internal data class PostScrollContinuationPlan(
        val anchorStartIndex: Int,
        val skipGeneralScan: Boolean
    )

    private data class CollectResult(
        val focusNodes: List<FocusedNode>,
        val traversalList: List<AccessibilityNodeInfo>,
        val focusNodeByNode: Map<AccessibilityNodeInfo, FocusedNode>,
        val focusState: FocusState,
        val scrollState: ScrollState
    )

    private data class NormalizeResult(
        val normalizedNodes: List<FocusedNode>,
        val traversalList: List<AccessibilityNodeInfo>,
        val screenRect: Rect,
        val screenTop: Int,
        val screenBottom: Int,
        val screenHeight: Int,
        val effectiveBottom: Int
    )

    private data class FocusState(
        val resolvedCurrent: AccessibilityNodeInfo?,
        val currentIndex: Int,
        val fallbackIndex: Int,
        val nextIndex: Int
    )

    private data class ScrollState(
        val mainScrollContainer: AccessibilityNodeInfo?,
        val scrollableNode: AccessibilityNodeInfo?
    )

    private enum class SelectionType {
        CONTINUATION,
        SCROLL,
        BOTTOM_BAR,
        END,
        REGULAR,
        FALLBACK
    }

    private data class SelectionDecisionModel(
        val type: SelectionType,
        val targetIndex: Int? = null,
        val reason: String
    )

    private data class SelectionDecision(
        val currentIndex: Int,
        val fallbackIndex: Int,
        val nextIndex: Int
    )

    private data class FocusAttemptResult(
        val outcome: TargetActionOutcome,
        val verificationPassed: Boolean,
        val snapBackDetected: Boolean
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

    internal data class CandidateSelectionResult(
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
        val isLogicalSuccessor: Boolean = false,
        val acceptedDespiteRewoundBeforeAnchor: Boolean = false
    )

    private data class NewlyRevealedEvaluation(
        val prioritizedNewlyRevealed: Boolean,
        val reasons: List<String>
    )

    private data class CandidateClassification(
        val isTopChrome: Boolean,
        val isPersistentHeader: Boolean,
        val isContentNode: Boolean
    )

    private data class FocusRetargetDecision(
        val finalTarget: AccessibilityNodeInfo,
        val finalLabel: String,
        val source: String,
        val retargeted: Boolean,
        val authoritativeOverride: Boolean
    )

    @Volatile
    private var authoritativeFocusWindowUntilMs: Long = 0L
    @Volatile
    private var activeSmartNextTurnId: Long = 0L
    @Volatile
    private var lastFinalCommitTurnId: Long = 0L
    @Volatile
    private var smartNextTurnSeed: Long = 0L
    @Volatile
    private var authoritativeCommittedBounds: Rect? = null
    @Volatile
    private var authoritativeCommittedIdentity: String? = null
    @Volatile
    private var authoritativeCommittedLabel: String? = null
    @Volatile
    private var authoritativeCommittedNode: AccessibilityNodeInfo? = null
    @Volatile
    private var authoritativeCommittedStatus: String = "moved"

    internal data class PostScrollContinuationSearchResult(
        val index: Int,
        val hasValidPostScrollCandidate: Boolean
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

    private data class SmartNextExecutionDecision(
        val nextIndex: Int,
        val currentIndex: Int,
        val isOutOfBounds: Boolean,
        val isCurrentAtLastIndex: Boolean,
        val shouldTerminateAtLastBottomBar: Boolean,
        val shouldScrollAtEnd: Boolean,
        val navigationDecision: NavigationDecision,
        val postScrollScanStartIndex: Int,
        val allowLooping: Boolean,
        val allowBottomBarEntry: Boolean,
        val expectedStatus: String
    )

    private data class NextActionDecision(
        val state: SmartNextRuntimeState,
        val smartNextState: SmartNextState,
        val initialTarget: InitialNextTargetDecision,
        val navigationDecision: NavigationDecision
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

    private data class PostScrollSearchContext(
        val excludedIndex: Int,
        val traversalStartIndex: Int,
        val resolvedAnchorIndex: Int,
        val continuationFallbackAttempted: Boolean,
        val continuationFallbackFailed: Boolean,
        val fallbackBelowAnchorIndex: Int,
        val anchorStartIndex: Int,
        val skipGeneralScan: Boolean
    )

    private data class FocusLoopState(
        var skippedExcludedNode: Boolean = false,
        var focusedAny: Boolean = false,
        var focusAttempted: Boolean = false,
        var focusedOutcome: TargetActionOutcome? = null
    )

    private data class SmartNextExecutionContext(
        val root: AccessibilityNodeInfo,
        val traversalList: List<AccessibilityNodeInfo>,
        val focusNodes: List<FocusedNode>,
        val currentIndex: Int,
        val fallbackIndex: Int,
        val nextIndex: Int,
        val resolvedCurrent: AccessibilityNodeInfo?,
        val screenTop: Int,
        val screenBottom: Int,
        val screenHeight: Int,
        val effectiveBottom: Int,
        val scrollableNode: AccessibilityNodeInfo?,
        val mainScrollContainer: AccessibilityNodeInfo?,
        val findAndFocusContext: FindAndFocusPhaseContext
    )

    fun resetFocusHistory() {
        setLastRequestedFocusIndex(-1)
        A11yStateStore.updateLastRequestedFocusIndex(-1)
        A11yHistoryManager.clearVisitedHistory()
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

    private fun collectNodes(root: AccessibilityNodeInfo): List<FocusedNode> = buildTalkBackLikeFocusNodes(root)

    private fun buildTraversalList(normalizedNodes: List<FocusedNode>): List<AccessibilityNodeInfo> = normalizedNodes.map { it.node }

    private fun resolvePrimaryLabel(node: AccessibilityNodeInfo?): String? {
        if (node == null) return null
        return node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
    }

    private fun collectFocusState(
        traversalList: List<AccessibilityNodeInfo>,
        currentNode: AccessibilityNodeInfo?
    ): FocusState {
        val current = resolveCurrentAndNextIndex(
            traversalList = traversalList,
            currentNode = currentNode
        )
        return FocusState(
            resolvedCurrent = current.resolvedCurrent,
            currentIndex = current.currentIndex,
            fallbackIndex = current.fallbackIndex,
            nextIndex = current.nextIndex
        )
    }

    private fun collectScrollState(
        root: AccessibilityNodeInfo,
        resolvedCurrent: AccessibilityNodeInfo?
    ): ScrollState {
        val mainScrollContainer = findMainScrollContainer(root)
        val scrollableNode = findScrollableForwardAncestorCandidate(resolvedCurrent)
            ?: mainScrollContainer
            ?: findScrollableForwardCandidate(root)
        return ScrollState(
            mainScrollContainer = mainScrollContainer,
            scrollableNode = scrollableNode
        )
    }

    private fun collectSmartNextInputs(
        root: AccessibilityNodeInfo,
        currentNode: AccessibilityNodeInfo?
    ): CollectResult {
        val focusNodes = collectNodes(root)
        val traversalList = buildTraversalList(focusNodes)
        val focusState = collectFocusState(traversalList, currentNode)
        val scrollState = collectScrollState(root, focusState.resolvedCurrent)
        val focusNodeByNode = focusNodes.associateBy { it.node }
        Log.i(
            "A11Y_HELPER",
            "[COLLECT] nodes=${traversalList.size} focusedSnapshot=${focusState.currentIndex} scrollContainer=${scrollState.mainScrollContainer != null} scrollable=${scrollState.scrollableNode != null}"
        )
        return CollectResult(
            focusNodes = focusNodes,
            traversalList = traversalList,
            focusNodeByNode = focusNodeByNode,
            focusState = focusState,
            scrollState = scrollState
        )
    }

    private fun normalizeNodes(focusNodes: List<FocusedNode>): List<FocusedNode> = focusNodes

    private fun normalizeSmartNextInputs(
        root: AccessibilityNodeInfo,
        collectResult: CollectResult
    ): NormalizeResult {
        val normalizedNodes = normalizeNodes(collectResult.focusNodes)
        val traversalList = buildTraversalList(normalizedNodes)
        val screenRect = Rect().also { root.getBoundsInScreen(it) }
        val screenTop = screenRect.top
        val screenBottom = screenRect.bottom
        val screenHeight = (screenBottom - screenTop).coerceAtLeast(1)
        val effectiveBottom = calculateEffectiveBottom(
            nodes = traversalList,
            screenTop = screenTop,
            screenBottom = screenBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            labelOf = { node -> resolvePrimaryLabel(node) ?: node.viewIdResourceName }
        )
        Log.i("A11Y_HELPER", "[NORMALIZE] traversal=${traversalList.size} screen=($screenTop,$screenBottom) effectiveBottom=$effectiveBottom")
        return NormalizeResult(
            normalizedNodes = normalizedNodes,
            traversalList = traversalList,
            screenRect = screenRect,
            screenTop = screenTop,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            effectiveBottom = effectiveBottom
        )
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
        val turnId = synchronized(this) {
            smartNextTurnSeed += 1L
            smartNextTurnSeed
        }
        activeSmartNextTurnId = turnId
        return try {
            val runtimeState = collectSmartNextRuntimeState(root, currentNode)
            val nextActionDecision = decideNextAction(runtimeState)
            val execution = executeNextAction(nextActionDecision)
            verifyAndFinalizeNextAction(nextActionDecision, execution)
        } finally {
            if (activeSmartNextTurnId == turnId) {
                activeSmartNextTurnId = 0L
            }
        }
    }

    private fun collectSmartNextRuntimeState(
        root: AccessibilityNodeInfo,
        currentNode: AccessibilityNodeInfo?
    ): SmartNextRuntimeState {
        val collectResult = collectSmartNextInputs(root, currentNode)
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

        val normalizeResult = normalizeSmartNextInputs(root, collectResult)
        val currentPosition = CurrentPosition(
            resolvedCurrent = collectResult.focusState.resolvedCurrent,
            currentIndex = collectResult.focusState.currentIndex,
            fallbackIndex = collectResult.focusState.fallbackIndex,
            nextIndex = collectResult.focusState.nextIndex
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
        val smartNextState = SmartNextState(
            root = state.root,
            traversalList = state.normalize.traversalList,
            currentIndex = state.currentPosition.currentIndex,
            nextIndex = state.currentPosition.nextIndex,
            screenBounds = state.normalize.screenRect,
            scrollableContainer = state.collect.scrollState.scrollableNode
        )
        val initialTarget = decideInitialNextTarget(state)
        val navigationDecision = decideSmartNextNavigationDecision(state, initialTarget, smartNextState)
        return NextActionDecision(
            state = state,
            smartNextState = smartNextState,
            initialTarget = initialTarget,
            navigationDecision = navigationDecision
        )
    }

    private fun executeNextAction(decision: NextActionDecision): NextActionExecution {
        val state = decision.state
        return NextActionExecution(executeSmartNextPipeline(state, decision.initialTarget, decision.navigationDecision))
    }

    private fun verifyAndFinalizeNextAction(
        decision: NextActionDecision,
        execution: NextActionExecution
    ): TargetActionOutcome {
        val statusLockedByFinalCommit = lastFinalCommitTurnId != 0L && lastFinalCommitTurnId == activeSmartNextTurnId
        val finalizedOutcome = if (statusLockedByFinalCommit && !execution.outcome.success) {
            val lockedTarget = authoritativeCommittedNode ?: execution.outcome.target
            TargetActionOutcome(
                success = true,
                reason = authoritativeCommittedStatus,
                target = lockedTarget
            )
        } else {
            execution.outcome
        }
        if (statusLockedByFinalCommit) {
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT] status_locked_by_final_commit turnId=$activeSmartNextTurnId status=${finalizedOutcome.reason} success=${finalizedOutcome.success}"
            )
        }
        Log.i(
            "A11Y_HELPER",
            "[SMART_NEXT][FINALIZE] nextIndex=${decision.initialTarget.nextIndex} success=${finalizedOutcome.success} reason=${finalizedOutcome.reason}"
        )
        return finalizedOutcome
    }

    private fun decideSmartNextNavigationDecision(
        state: SmartNextRuntimeState,
        initialTarget: InitialNextTargetDecision,
        smartNextState: SmartNextState
    ): NavigationDecision {
        val traversalList = state.normalize.traversalList
        val normalize = state.normalize
        val collect = state.collect
        val currentIndex = state.currentPosition.currentIndex
        var nextIndex = initialTarget.nextIndex
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

        var nextIsBottomBar = nextIndex in traversalList.indices && isBottomNavigationBarNode(
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
            isFixedUiOf = { node -> isFixedSystemUI(node, collect.scrollState.mainScrollContainer) },
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
        return navigationDecision
    }

    private fun decideSmartNextExecution(
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
            NavigationType.BOTTOM_BAR -> "moved_to_bottom_bar"
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

    private fun executeSmartNextPipeline(
        state: SmartNextRuntimeState,
        initialTarget: InitialNextTargetDecision,
        navigationDecision: NavigationDecision
    ): TargetActionOutcome {
        val executionDecision = decideSmartNextExecution(state, initialTarget, navigationDecision)
        val executionContext = buildExecutionContext(state, initialTarget, executionDecision)
        val traversalList = executionContext.traversalList
        val currentIndex = executionContext.currentIndex
        if (traversalList.isEmpty()) {
            Log.i("A11Y_HELPER", "[EXECUTE] Traversal list is empty, failing.")
            return TargetActionOutcome(false, "Traversal list is empty")
        }

        if (currentIndex != -1) {
            setLastRequestedFocusIndex(maxOf(lastRequestedFocusIndex, A11yStateStore.lastRequestedFocusIndex, currentIndex))
            setLastRequestedFocusIndex(maxOf(lastRequestedFocusIndex, currentIndex))
        }
        Log.i("A11Y_HELPER", "[EXECUTE] navigation=${executionDecision.navigationDecision.type} expectedStatus=${executionDecision.expectedStatus} next=${executionDecision.nextIndex}")
        executionContext.root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
            val cleared = clearFocus(focusedNode)
            val focusedBounds = Rect().also { focusedNode.getBoundsInScreen(it) }
            Log.i("A11Y_HELPER", "[EXECUTE] Cleared existing accessibility focus before next move: result=$cleared bounds=$focusedBounds")
        }

        val boundaryDecision = decideBoundaryConditions(executionDecision)
        if (boundaryDecision.type == SelectionType.END) {
            return handleEndOfTraversal(executionContext, executionDecision)
        }

        val bottomBarResult = handleBottomBarTransition(executionContext, executionDecision)
        if (bottomBarResult != null) {
            return bottomBarResult
        }
        if (executionDecision.navigationDecision.type == NavigationType.PRE_SCROLL) {
            return handlePreScrollAndRefresh(executionContext, executionDecision)
        }
        return handleRegularFocusMove(executionContext, executionDecision)
    }

    private fun buildExecutionContext(
        state: SmartNextRuntimeState,
        initialTarget: InitialNextTargetDecision,
        executionDecision: SmartNextExecutionDecision
    ): SmartNextExecutionContext {
        val normalize = state.normalize
        val selectionDecision = initialTarget.selectionDecision
        Log.i("A11Y_HELPER", "[DECIDE] select_next currentIndex=${selectionDecision.currentIndex}, fallbackIndex=${selectionDecision.fallbackIndex}, nextIndex=${selectionDecision.nextIndex}")
        Log.i("A11Y_HELPER", "[DECIDE] fallbackIndex=${state.currentPosition.fallbackIndex}")
        val findAndFocusContext = FindAndFocusPhaseContext(
            root = state.root,
            traversalList = normalize.traversalList,
            screenTop = normalize.screenTop,
            screenBottom = normalize.screenBottom,
            effectiveBottom = normalize.effectiveBottom,
            screenHeight = normalize.screenHeight,
            focusNodeByNode = state.focusNodeByNode,
            visitedHistory = state.visitedHistory,
            visitedHistorySignatures = state.visitedHistorySignatures
        )
        return SmartNextExecutionContext(
            root = state.root,
            traversalList = normalize.traversalList,
            focusNodes = normalize.normalizedNodes,
            currentIndex = state.currentPosition.currentIndex,
            fallbackIndex = state.currentPosition.fallbackIndex,
            nextIndex = executionDecision.nextIndex,
            resolvedCurrent = state.currentPosition.resolvedCurrent,
            screenTop = normalize.screenTop,
            screenBottom = normalize.screenBottom,
            screenHeight = normalize.screenHeight,
            effectiveBottom = normalize.effectiveBottom,
            scrollableNode = state.collect.scrollState.scrollableNode,
            mainScrollContainer = state.collect.scrollState.mainScrollContainer,
            findAndFocusContext = findAndFocusContext
        )
    }

    private fun decideBoundaryConditions(executionDecision: SmartNextExecutionDecision): SelectionDecisionModel {
        return if (executionDecision.navigationDecision.type == NavigationType.END) {
            SelectionDecisionModel(SelectionType.END, reason = "end_boundary")
        } else {
            SelectionDecisionModel(SelectionType.REGULAR, targetIndex = executionDecision.nextIndex, reason = "in_bounds")
        }
    }

    private fun handleEndOfTraversal(
        context: SmartNextExecutionContext,
        executionDecision: SmartNextExecutionDecision
    ): TargetActionOutcome {
        val traversalList = context.traversalList
        val currentIndex = context.currentIndex
        val lastIndex = traversalList.lastIndex
        if (executionDecision.shouldTerminateAtLastBottomBar) {
            Log.i("A11Y_HELPER", "[EXECUTE] Last focused node is bottom bar and no next candidate. terminating.")
            return TargetActionOutcome(false, "reached_end")
        }
        if (executionDecision.shouldScrollAtEnd && context.scrollableNode != null) {
            return handlePreScrollAndRefresh(context, executionDecision, reason = "end_of_traversal")
        }
        if (executionDecision.isOutOfBounds && currentIndex < lastIndex) {
            val graceIndex = currentIndex + 1
            if (graceIndex in traversalList.indices) {
                Log.i("A11Y_HELPER", "[EXECUTE] Applying last-node grace focus at index=$graceIndex")
                return focusSequentiallyFromIndex(
                    context.root,
                    traversalList,
                    graceIndex,
                    context.screenTop,
                    context.effectiveBottom,
                    currentIndex,
                    "moved"
                )
            }
        }
        if (currentIndex == lastIndex && currentIndex in traversalList.indices) {
            val lastNode = traversalList[currentIndex]
            lastNode.refresh()
            lastNode.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            return TargetActionOutcome(false, "reached_end", lastNode)
        }
        return TargetActionOutcome(false, "reached_end")
    }

    private fun handleBottomBarTransition(
        context: SmartNextExecutionContext,
        executionDecision: SmartNextExecutionDecision
    ): TargetActionOutcome? {
        val traversalList = context.traversalList
        val nextIndex = executionDecision.nextIndex
        if (nextIndex !in traversalList.indices) return null
        val nextNode = traversalList[nextIndex]
        val nextBounds = Rect().also { nextNode.getBoundsInScreen(it) }
        val nextIsBottomBar = isBottomNavigationBarNode(
            className = nextNode.className?.toString(),
            viewIdResourceName = nextNode.viewIdResourceName,
            boundsInScreen = nextBounds,
            screenBottom = context.screenBottom,
            screenHeight = context.screenHeight
        )
        if (!nextIsBottomBar) return null
        if (executionDecision.navigationDecision.type == NavigationType.BOTTOM_BAR) {
            Log.i("A11Y_HELPER", "[EXECUTE] Bottom bar transition is allowed by decision.")
            return focusOrSkip(
                context.root,
                traversalList,
                nextNode,
                context.screenTop,
                context.effectiveBottom,
                context.currentIndex,
                executionDecision.expectedStatus,
                nextIndex
            )
        }
        return null
    }

    private fun handlePreScrollAndRefresh(
        context: SmartNextExecutionContext,
        executionDecision: SmartNextExecutionDecision,
        reason: String = "bottom_bar_guard"
    ): TargetActionOutcome {
        val scrollTarget = context.scrollableNode ?: return TargetActionOutcome(false, "failed")
        val preScrollAnchor = buildPreScrollAnchor(
            focusNodes = context.focusNodes,
            currentIndex = context.currentIndex,
            resolvedCurrent = context.resolvedCurrent
        )
        Log.i("A11Y_HELPER", "[EXECUTE] Pre-scroll start reason=$reason")
        val preScrollResult = performScroll(scrollTarget = scrollTarget, reason = reason)
        if (!preScrollResult.success) {
            if (reason == "end_of_traversal") return TargetActionOutcome(false, "reached_end")
            val nextNode = context.traversalList.getOrNull(executionDecision.nextIndex)
            if (nextNode != null) {
                return focusOrSkip(
                    context.root,
                    context.traversalList,
                    nextNode,
                    context.screenTop,
                    context.effectiveBottom,
                    context.currentIndex,
                    "moved_to_bottom_bar_direct",
                    executionDecision.nextIndex
                )
            }
            return TargetActionOutcome(false, "failed")
        }
        val visibleHistory = collectVisibleHistory(
            nodes = context.traversalList,
            screenTop = context.screenTop,
            screenBottom = context.screenBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            labelOf = { node ->
                node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            },
            isTopAppBarNodeOf = { node, bounds -> isTopAppBarNode(node.className?.toString(), node.viewIdResourceName, bounds, context.screenTop, context.screenHeight) },
            isBottomNavigationBarNodeOf = { node, bounds -> isBottomNavigationBarNode(node.className?.toString(), node.viewIdResourceName, bounds, context.screenBottom, context.screenHeight) }
        )
        val visibleHistorySignatures = collectVisibleHistorySignatures(
            nodes = context.traversalList,
            screenTop = context.screenTop,
            screenBottom = context.screenBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            labelOf = { node ->
                node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            },
            viewIdOf = { node -> node.viewIdResourceName },
            isTopAppBarNodeOf = { node, bounds -> isTopAppBarNode(node.className?.toString(), node.viewIdResourceName, bounds, context.screenTop, context.screenHeight) },
            isBottomNavigationBarNodeOf = { node, bounds -> isBottomNavigationBarNode(node.className?.toString(), node.viewIdResourceName, bounds, context.screenBottom, context.screenHeight) }
        )
        val oldSnapshot = buildNodeTextSnapshot(context.traversalList)
        val refreshedRoot = pollForUpdatedRoot(A11yHelperService.instance, oldSnapshot, context.root) ?: return TargetActionOutcome(false, "failed")
        val refreshedTraversal = buildFocusableTraversalList(refreshedRoot)
        if (oldSnapshot == buildNodeTextSnapshot(refreshedTraversal)) {
            if (reason == "end_of_traversal") return TargetActionOutcome(false, "reached_end_no_scroll_progress")
            val nextNode = context.traversalList.getOrNull(executionDecision.nextIndex)
            if (nextNode != null && executionDecision.allowBottomBarEntry) {
                return focusBottomBarAfterNoProgress(context.root, context.traversalList, nextNode, executionDecision.nextIndex)
            }
            return TargetActionOutcome(false, "reached_end_no_scroll_progress")
        }
        val refreshedRect = Rect().also { refreshedRoot.getBoundsInScreen(it) }
        val refreshedScreenBottom = refreshedRect.bottom
        val refreshedScreenHeight = refreshedRect.height().coerceAtLeast(1)
        val refreshedEffectiveBottom = calculateEffectiveBottom(
            nodes = refreshedTraversal,
            screenTop = refreshedRect.top,
            screenBottom = refreshedScreenBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            labelOf = { node ->
                node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.viewIdResourceName
            }
        )
        val outcome = findAndFocusFirstContent(
            context = context.findAndFocusContext.copy(
                root = refreshedRoot,
                traversalList = refreshedTraversal,
                screenTop = refreshedRect.top,
                screenBottom = refreshedScreenBottom,
                effectiveBottom = refreshedEffectiveBottom,
                screenHeight = refreshedScreenHeight
            ),
            request = FindAndFocusRequest(
                statusName = executionDecision.expectedStatus,
                isScrollAction = true,
                excludeDesc = context.resolvedCurrent?.contentDescription?.toString(),
                startIndex = executionDecision.postScrollScanStartIndex,
                visibleHistory = visibleHistory,
                visibleHistorySignatures = visibleHistorySignatures,
                allowLooping = executionDecision.allowLooping,
                preScrollAnchor = preScrollAnchor
            )
        )
        if (outcome.success || reason == "end_of_traversal") return outcome
        if (outcome.reason == "continuation_candidate_unresolved") return TargetActionOutcome(false, "failed")
        val nextNode = context.traversalList.getOrNull(executionDecision.nextIndex)
        if (nextNode != null && executionDecision.allowBottomBarEntry) {
            val bottomBarOutcome = focusOrSkip(
                context.root, context.traversalList, nextNode, context.screenTop, context.effectiveBottom, context.currentIndex, "moved_to_bottom_bar", executionDecision.nextIndex
            )
            return if (bottomBarOutcome.success) TargetActionOutcome(true, "moved_to_bottom_bar", nextNode) else bottomBarOutcome
        }
        return outcome
    }

    private fun handleRegularFocusMove(
        context: SmartNextExecutionContext,
        executionDecision: SmartNextExecutionDecision
    ): TargetActionOutcome {
        Log.i("A11Y_HELPER", "[EXECUTE] Performing regular next navigation")
        return findAndFocusFirstContent(
            context = context.findAndFocusContext,
            request = FindAndFocusRequest(
                statusName = executionDecision.expectedStatus,
                isScrollAction = false,
                excludeDesc = null,
                startIndex = executionDecision.nextIndex.coerceAtLeast(0),
                visibleHistory = emptySet(),
                visibleHistorySignatures = emptySet(),
                allowLooping = false,
                preScrollAnchor = null
            )
        )
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
        val localMainScrollContainer = A11yNodeUtils.findBestScrollableContainer(context.root)
            ?: findMainScrollContainer(
                nodes = context.traversalList,
                isScrollable = { it.isScrollable },
                boundsOf = { candidate -> Rect().also { candidate.getBoundsInScreen(it) } }
            )
        val postScrollContext = buildPostScrollSearchContext(context, request, localMainScrollContainer)
        val loopState = FocusLoopState()

        for (index in postScrollContext.anchorStartIndex until context.traversalList.size) {
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

        val noCandidateOutcome = handleNoCandidateAfterScroll(request, postScrollContext, loopState)
        if (noCandidateOutcome != null) {
            return noCandidateOutcome
        }
        return handleLoopFallback(context, request, loopState)
    }

    private fun buildPostScrollSearchContext(
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
            resolveAnchorIndexInRefreshedTraversal(
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
                val promotedRawOnlyViewIds = collectRawVisibleNodes(context.root)
                    .mapNotNull { raw -> raw.viewId?.substringAfterLast('/')?.trim() }
                    .filter { shortId -> isSettingsRowViewId(shortId) }
                    .toSet()
                val continuationSearchResult = selectContinuationCandidateAfterScrollResult(
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
                        isContentNode(
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
                    descendantLabelOf = { node -> recoverDescendantLabel(node) },
                    promotedViewIds = promotedRawOnlyViewIds,
                    preScrollAnchor = preScrollAnchor,
                    preScrollAnchorBottom = preScrollAnchor.bounds.bottom,
                    labelOf = { node ->
                        node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                            ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    }
                )
                val candidate = continuationSearchResult.index
                val selection = selectPostScrollCandidate(candidate)
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
        val postScrollDecision = decidePostScrollContinuation(
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

    private fun selectPostScrollCandidate(candidateIndex: Int): CandidateSelectionResult {
        val analysis = analyzePostScrollState(
            treeChanged = true,
            anchorMaintained = true,
            newlyExposedCandidateExists = candidateIndex >= 0
        )
        return selectPostScrollContinuationCandidate(candidateIndex, analysis)
    }

    private fun tryFocusCandidate(
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
            return null
        }
        val requestedFloorIndex = maxOf(lastRequestedFocusIndex, A11yStateStore.lastRequestedFocusIndex)
        if (!request.isScrollAction && requestedFloorIndex >= 0 && index <= requestedFloorIndex) {
            return null
        }
        if (isNodePhysicallyOffScreen(bounds, context.screenTop, context.screenBottom)) return null
        val isTopBar = isTopAppBarNode(node.className?.toString(), node.viewIdResourceName, bounds, context.screenTop, context.screenHeight)
        val isBottomBar = isBottomNavigationBarNode(node.className?.toString(), node.viewIdResourceName, bounds, context.screenBottom, context.screenHeight)
        val isFixedUi = isFixedSystemUI(node, localMainScrollContainer)
        val inVisitedHistory = isInVisitedHistory(
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
            isInsideMainScrollContainer = localMainScrollContainer?.let { container -> node == container || isDescendantOf(container, node) { it.parent } } ?: false,
            isTopArea = isWithinTopContentArea(bounds.top, context.screenTop, context.screenHeight)
        )
        if (shouldSkipHistory || (request.isScrollAction && inVisitedHistory)) return null
        if (postScrollContext.excludedIndex == -1 && !loopState.skippedExcludedNode && shouldSkipExcludedNodeByDescription(
                nodeDesc = node.contentDescription?.toString(),
                excludeDesc = request.excludeDesc,
                nodeBounds = bounds,
                screenTop = context.screenTop,
                screenHeight = context.screenHeight
            )) {
            loopState.skippedExcludedNode = true
            return null
        }
        if (!isTopBar && !isBottomBar) {
            if (label == "<no-label>") {
                label = recoverDescendantLabel(node) ?: label
            }
            loopState.focusAttempted = true
            val outcome = requestFocusFlow(
                root = context.root,
                target = node,
                screenTop = context.screenTop,
                effectiveBottom = context.effectiveBottom,
                status = request.statusName,
                isScrollAction = request.isScrollAction,
                traversalIndex = index,
                traversalListSnapshot = traversalList,
                currentFocusIndexHint = index - 1
            )
            val mappedOutcome = TargetActionOutcome(outcome.success, outcome.status, outcome.targetNode)
            if (mappedOutcome.success) {
                loopState.focusedAny = true
                loopState.focusedOutcome = mappedOutcome
                return mappedOutcome
            }
        }
        return null
    }

    private fun handleNoCandidateAfterScroll(
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

    private fun handleLoopFallback(
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

    private fun clearFocus(node: AccessibilityNodeInfo): Boolean {
        return node.performAction(AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
    }

    private fun performScroll(
        scrollTarget: AccessibilityNodeInfo,
        reason: String
    ): PreScrollResult {
        return executePreScrollIfNeeded(
            scrollTarget = scrollTarget,
            reason = reason
        )
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
        val result = requestFocusFlow(
            root = root,
            target = target,
            screenTop = screenTop,
            effectiveBottom = effectiveBottom,
            status = status,
            isScrollAction = false,
            traversalIndex = traversalIndex,
            traversalListSnapshot = traversalList,
            currentFocusIndexHint = currentIndex
        )
        return TargetActionOutcome(result.success, result.status, result.targetNode)
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

    private fun decideContinuationBeforeBottomBar(
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

    private fun decidePostScrollContinuation(
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

    private fun decideFallbackStrategy(
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

    private fun decideNextNavigationType(
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
    ): Int = selectContinuationCandidateAfterScrollResult(
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
    ).index

    internal fun <T> selectContinuationCandidateAfterScrollResult(
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
    ): PostScrollContinuationSearchResult = selectPostScrollContinuationCandidateResult(
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

    private fun <T> selectPostScrollContinuationCandidateResult(
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
            val isHeaderLikeNode = isHeaderLikeCandidate(
                className = classNameOf(node),
                viewIdResourceName = rawViewId,
                label = label,
                boundsInScreen = bounds,
                screenTop = screenTop,
                screenHeight = screenHeight
            )
            val descendantLabel = descendantLabelOf?.invoke(node)?.trim().orEmpty()
            val hasResolvedLabel = label.isNotBlank() || descendantLabel.isNotBlank()
            val preScrollSeen = inVisibleHistory
            val postScrollSeen = true
            val isPreScrollContinuationCandidate = preScrollSeen && isAfterPreScrollAnchor
            val preScrollHadResolvedLabel = preScrollSeen && hasPreScrollResolvedLabel(
                currentLabel = label,
                currentDescendantLabel = descendantLabel,
                rawViewId = rawViewId,
                bounds = bounds,
                visibleHistorySignatures = visibleHistorySignatures
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

    private data class RawVisibleNode(
        val label: String,
        val viewId: String?,
        val bounds: Rect
    )

    private fun hasPreScrollResolvedLabel(
        currentLabel: String,
        currentDescendantLabel: String,
        rawViewId: String?,
        bounds: Rect,
        visibleHistorySignatures: Set<VisibleHistorySignature>
    ): Boolean {
        if (visibleHistorySignatures.isEmpty()) return false
        val normalizedCurrentLabel = currentLabel.trim()
        val normalizedDescendantLabel = currentDescendantLabel.trim()
        return visibleHistorySignatures.any { signature ->
            val sameViewId = !rawViewId.isNullOrBlank() && signature.viewId.equals(rawViewId, ignoreCase = true)
            val sameBounds = signature.bounds == bounds
            if (!sameViewId && !sameBounds) return@any false
            val preScrollLabel = signature.label?.trim().orEmpty()
            preScrollLabel.isNotBlank() &&
                (preScrollLabel.equals(normalizedCurrentLabel, ignoreCase = true) ||
                    preScrollLabel.equals(normalizedDescendantLabel, ignoreCase = true))
        }
    }

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

    private fun snapshotVisitedHistoryLabels(): Set<String> = A11yHistoryManager.snapshotVisitedHistoryLabels()

    private fun snapshotVisitedHistorySignatures(): Set<VisibleHistorySignature> = A11yHistoryManager.snapshotVisitedHistorySignatures()

    private fun buildNodeIdentityForHistory(node: AccessibilityNodeInfo): String = nodeIdentityOf(node).orEmpty()

    private fun nodeIdentityOf(windowId: Int, className: String?, packageName: String?): String {
        val normalizedClassName = className?.trim().orEmpty()
        val normalizedPackageName = packageName?.trim().orEmpty()
        return "window=$windowId|class=$normalizedClassName|package=$normalizedPackageName"
    }

    private fun nodeIdentityOf(node: AccessibilityNodeInfo?): String? {
        node ?: return null
        return nodeIdentityOf(
            windowId = node.windowId,
            className = node.className?.toString(),
            packageName = node.packageName?.toString()
        )
    }

    private fun nodeIdentityOf(node: AccessibilityNodeInfoCompat?): String? {
        node ?: return null
        return nodeIdentityOf(
            windowId = node.windowId,
            className = node.className?.toString(),
            packageName = node.packageName?.toString()
        )
    }

    private fun nodeIdentityOf(snapshot: FocusSnapshot?): String? {
        snapshot ?: return null
        return nodeIdentityOf(
            windowId = -1,
            className = snapshot.className,
            packageName = snapshot.packageName
        )
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
        A11yHistoryManager.recordVisitedSignature(
            label = normalizedLabel,
            viewId = node.viewIdResourceName,
            bounds = bounds,
            nodeIdentity = nodeIdentity
        )
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

    internal fun requestFocusFlow(
        root: AccessibilityNodeInfo,
        target: AccessibilityNodeInfo,
        screenTop: Int,
        effectiveBottom: Int,
        status: String,
        isScrollAction: Boolean,
        traversalIndex: Int,
        traversalListSnapshot: List<AccessibilityNodeInfo>? = null,
        currentFocusIndexHint: Int = -1
    ): ActionResult {
        val label = target.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: target.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: "<no-label>"
        val rootBounds = Rect().also(root::getBoundsInScreen)
        val rootHeight = (rootBounds.bottom - rootBounds.top).coerceAtLeast(1)
        val targetBounds = Rect().also(target::getBoundsInScreen)

        // 1) Pre-Focus: 가시성 확보
        val isTopBar = isTopAppBarNode(target.className?.toString(), target.viewIdResourceName, targetBounds, screenTop, rootHeight)
        val isBottomBar = isBottomNavigationBarNode(target.className?.toString(), target.viewIdResourceName, targetBounds, rootBounds.bottom, rootHeight)
        if (!isTopBar && !isBottomBar && A11yNodeUtils.isNodePoorlyPositionedForFocus(targetBounds, screenTop, effectiveBottom)) {
            alignCandidateForReadableFocus(
                root = root,
                target = target,
                label = label,
                screenTop = screenTop,
                effectiveBottom = effectiveBottom,
                isTopBar = isTopBar,
                isBottomBar = isBottomBar,
                canScrollForwardHint = findScrollableForwardAncestorCandidate(target) != null || hasScrollableDownCandidate(root),
                intendedTrailingCandidate = traversalListSnapshot?.takeIf { traversalIndex in it.indices }?.let {
                    findNextEligibleTraversalCandidate(
                        traversalList = it,
                        fromIndex = traversalIndex,
                        screenTop = screenTop,
                        screenBottom = rootBounds.bottom,
                        screenHeight = rootHeight,
                        boundsOf = { node -> Rect().also(node::getBoundsInScreen) },
                        classNameOf = { node -> node.className?.toString() },
                        viewIdOf = { node -> node.viewIdResourceName }
                    )
                }
            )
        }

        val currentFocusedBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { Rect().also(it::getBoundsInScreen) }
        if (shouldReuseExistingAccessibilityFocus(label, isScrollAction, currentFocusedBounds, targetBounds)) {
            val commitDecision = resolveFocusRetargetDecision(root, target, label, traversalListSnapshot, traversalIndex, isScrollAction)
            recordRequestedFocusAttempt(traversalIndex, root)
            recordVisitedFocus(commitDecision.finalTarget, commitDecision.finalLabel, reason = "focus_reused_existing_target")
            return ActionResult(true, "moved", commitDecision.finalTarget)
        }

        clearAccessibilityFocusAndRefresh(root)
        requestInputFocusBeforeAccessibilityFocus(target, label)

        // 2) Action: 포커스 실행 + 재시도
        val focusExecution = A11yFocusExecutor.requestAccessibilityFocusWithRetry(
            target = target,
            root = root
        )
        if (!focusExecution.success) {
            syncLastRequestedFocusIndexToCurrentFocus(root, buildTalkBackLikeFocusNodes(root).map { it.node })
            return ActionResult(false, "failed", target)
        }

        // 3) Verify: 최종 focus 일치 + snap-back 체크
        val focusVerification = A11yFocusExecutor.verifyFocusStabilizationAfterAction(
            root = root,
            targetBounds = targetBounds,
            isTargetAccessibilityFocused = target.isAccessibilityFocused
        )
        if (focusVerification.snapBackDetected) {
            Log.w("A11Y_HELPER", "[SMART_NEXT] requestFocusFlow snap_back target=${formatBoundsForLog(targetBounds)} actual=${formatBoundsForLog(focusVerification.actualFocusedBounds)}")
            syncLastRequestedFocusIndexToCurrentFocus(root, buildTalkBackLikeFocusNodes(root).map { it.node })
            return ActionResult(false, "snap_back", target)
        }

        val commitDecision = resolveFocusRetargetDecision(root, target, label, traversalListSnapshot, traversalIndex, isScrollAction)
        recordRequestedFocusAttempt(traversalIndex, root)
        recordVisitedFocus(commitDecision.finalTarget, commitDecision.finalLabel, reason = "focus_confirmed_final")
        return ActionResult(true, status, commitDecision.finalTarget)
    }

    private fun resolveFocusRetargetDecision(
        root: AccessibilityNodeInfo,
        intendedTarget: AccessibilityNodeInfo,
        intendedLabel: String,
        traversalListSnapshot: List<AccessibilityNodeInfo>?,
        intendedIndex: Int,
        isScrollAction: Boolean
    ): FocusRetargetDecision {
        val actualFocusedNode = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val actualCandidateIndex = if (actualFocusedNode != null && traversalListSnapshot != null) {
            findNodeIndexByIdentity(
                nodes = traversalListSnapshot,
                target = actualFocusedNode,
                idOf = { it.viewIdResourceName },
                textOf = { it.text?.toString() },
                contentDescriptionOf = { it.contentDescription?.toString() },
                boundsOf = { Rect().also(it::getBoundsInScreen) }
            )
        } else {
            -1
        }
        val identityMatched = actualFocusedNode != null && isSameNode(intendedTarget, actualFocusedNode)
        val rootBounds = Rect().also(root::getBoundsInScreen)
        val rootHeight = (rootBounds.bottom - rootBounds.top).coerceAtLeast(1)
        val actualBounds = actualFocusedNode?.let { Rect().also(it::getBoundsInScreen) }
        val actualIsInteractiveContent = actualFocusedNode != null && actualBounds != null &&
            isContentNode(
                node = actualFocusedNode,
                bounds = actualBounds,
                screenTop = rootBounds.top,
                screenBottom = rootBounds.bottom,
                screenHeight = rootHeight,
                mainScrollContainer = null
            )
        val retarget = !identityMatched &&
            isScrollAction &&
            actualCandidateIndex >= 0 &&
            (intendedIndex < 0 || actualCandidateIndex != intendedIndex) &&
            actualIsInteractiveContent
        val shouldSuppressTopNoise = isScrollAction &&
            isWithinAuthoritativeFocusWindow() &&
            actualFocusedNode != null &&
            actualBounds != null &&
            isSuppressibleHeaderNoiseNode(
                node = actualFocusedNode,
                bounds = actualBounds,
                rootTop = rootBounds.top,
                rootHeight = rootHeight,
                anchorBounds = Rect().also(intendedTarget::getBoundsInScreen)
            )
        val reason = when {
            identityMatched -> "identity_matched"
            shouldSuppressTopNoise -> "suppressed_top_resurfaced_noise"
            !isScrollAction -> "not_scroll_action"
            actualFocusedNode == null -> "actual_focus_missing"
            actualCandidateIndex < 0 -> "actual_not_in_post_scroll_candidates"
            !actualIsInteractiveContent -> "actual_not_interactive_content"
            else -> "actual_valid_post_scroll_candidate"
        }
        Log.i(
            "A11Y_HELPER",
            "[FOCUS_VERIFY] focus_retarget_eval intended=${formatBoundsForLog(Rect().also(intendedTarget::getBoundsInScreen))} actual=${formatBoundsForLog(actualBounds)} actualCandidateIndex=$actualCandidateIndex retarget=$retarget reason=$reason"
        )
        val finalTarget = when {
            shouldSuppressTopNoise -> intendedTarget
            retarget -> actualFocusedNode!!
            else -> intendedTarget
        }
        val finalLabel = resolvePrimaryLabel(finalTarget)
            ?: recoverDescendantLabel(finalTarget)
            ?: intendedLabel
        val source = when {
            shouldSuppressTopNoise -> "suppressed_top_noise"
            retarget -> "retargeted_actual"
            else -> "intended"
        }
        if (shouldSuppressTopNoise) {
            Log.i(
                "A11Y_HELPER",
                "[FOCUS_VERIFY] suppression_window_event type=FOCUS_UPDATE suppressed=true reason=top_resurfaced_header_during_authoritative_window label=${resolvePrimaryLabel(actualFocusedNode) ?: recoverDescendantLabel(actualFocusedNode) ?: "<no-label>"}"
            )
            Log.i(
                "A11Y_HELPER",
                "[FOCUS_VERIFY] suppression_window_event type=A11Y_ANNOUNCEMENT suppressed=true reason=top_resurfaced_header_during_authoritative_window label=${resolvePrimaryLabel(actualFocusedNode) ?: recoverDescendantLabel(actualFocusedNode) ?: "<no-label>"}"
            )
        }
        if (isScrollAction) {
            startAuthoritativeFocusSuppressionWindow(finalTarget, finalLabel, "moved")
        } else if (!isWithinAuthoritativeFocusWindow()) {
            clearAuthoritativeFocusSuppressionWindow("window_expired_or_not_needed")
        }
        lastFinalCommitTurnId = activeSmartNextTurnId
        Log.i(
            "A11Y_HELPER",
            "[FOCUS_VERIFY] final_focus_commit candidate=${finalLabel.replace("\n", " ")} source=$source"
        )
        return FocusRetargetDecision(
            finalTarget = finalTarget,
            finalLabel = finalLabel,
            source = source,
            retargeted = retarget,
            authoritativeOverride = retarget || shouldSuppressTopNoise
        )
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
        val poorlyPositioned = A11yNodeUtils.isNodePoorlyPositionedForFocus(currentBounds, screenTop, effectiveBottom)
        if (!poorlyPositioned) return

        if (A11yNodeUtils.isNodeBottomClipped(currentBounds, effectiveBottom)) {
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
                canScrollForwardHint && (A11yNodeUtils.isNodeBottomClipped(currentBounds, effectiveBottom) || A11yNodeUtils.shouldLiftTrailingContentBeforeFocus(currentBounds, effectiveBottom))
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
            if (!A11yNodeUtils.isNodePoorlyPositionedForFocus(currentBounds, screenTop, effectiveBottom)) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Intended candidate is now fully visible")
                return
            }
            adjustments += 1
        }

        if (A11yNodeUtils.isNodeFullyVisible(currentBounds, screenTop, effectiveBottom)) {
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

    private fun isHeaderLikeCandidate(
        className: String?,
        viewIdResourceName: String?,
        label: String?,
        boundsInScreen: Rect,
        screenTop: Int,
        screenHeight: Int
    ): Boolean {
        val normalizedClass = className?.lowercase().orEmpty()
        val normalizedViewId = viewIdResourceName?.lowercase().orEmpty()
        val normalizedLabel = label?.lowercase().orEmpty()
        val topBoundary = screenTop + (screenHeight * 0.3f).toInt()
        if (boundsInScreen.top > topBoundary) return false

        val headerKeywordMatched =
            normalizedViewId.contains("toolbar") ||
                normalizedViewId.contains("appbar") ||
                normalizedViewId.contains("header") ||
                normalizedViewId.contains("title") ||
                normalizedViewId.contains("logo") ||
                normalizedViewId.contains("setting_button") ||
                normalizedViewId.contains("settings")
        val classKeywordMatched =
            normalizedClass.contains("toolbar") ||
                normalizedClass.contains("appbarlayout") ||
                normalizedClass.contains("actionbar")
        val labelKeywordMatched =
            normalizedLabel.contains("settings") ||
                normalizedLabel.contains("setting")
        return headerKeywordMatched || classKeywordMatched || labelKeywordMatched
    }

    private fun isSuppressibleHeaderNoiseNode(
        node: AccessibilityNodeInfo,
        bounds: Rect,
        rootTop: Int,
        rootHeight: Int,
        anchorBounds: Rect
    ): Boolean {
        val headerLike = isHeaderLikeCandidate(
            className = node.className?.toString(),
            viewIdResourceName = node.viewIdResourceName,
            label = resolvePrimaryLabel(node) ?: recoverDescendantLabel(node),
            boundsInScreen = bounds,
            screenTop = rootTop,
            screenHeight = rootHeight
        ) || isTopAppBarNode(
            className = node.className?.toString(),
            viewIdResourceName = node.viewIdResourceName,
            boundsInScreen = bounds,
            screenTop = rootTop,
            screenHeight = rootHeight
        )
        return headerLike && bounds.bottom <= anchorBounds.top
    }

    private fun isWithinAuthoritativeFocusWindow(nowMs: Long = System.currentTimeMillis()): Boolean {
        if (A11yHistoryManager.isWithinAuthoritativeFocusWindow(nowMs)) return true
        clearAuthoritativeFocusSuppressionWindow("window_expired")
        return false
    }

    internal fun shouldIgnorePostCommitResurfacedHeader(
        root: AccessibilityNodeInfo?,
        candidate: AccessibilityNodeInfo?,
        eventType: Int
    ): Boolean {
        if (candidate == null || !isWithinAuthoritativeFocusWindow()) return false
        val committedBounds = A11yHistoryManager.authoritativeCommittedBounds() ?: return false
        val candidateBounds = Rect().also(candidate::getBoundsInScreen)
        val sameBounds = candidateBounds == committedBounds
        val committedIdentity = A11yHistoryManager.authoritativeCommittedIdentity()
        val candidateIdentity = nodeIdentityOf(candidate)
        val sameIdentity = !committedIdentity.isNullOrBlank() && committedIdentity == candidateIdentity
        if (sameBounds || sameIdentity) return false

        val rootBounds = root?.let { Rect().also(it::getBoundsInScreen) } ?: Rect(0, 0, 0, candidateBounds.bottom)
        val rootTop = rootBounds.top
        val rootBottom = if (rootBounds.bottom > rootBounds.top) rootBounds.bottom else candidateBounds.bottom
        val rootHeight = (rootBottom - rootTop).coerceAtLeast(1)
        val isHeaderLike = isHeaderLikeCandidate(
            className = candidate.className?.toString(),
            viewIdResourceName = candidate.viewIdResourceName,
            label = resolvePrimaryLabel(candidate) ?: recoverDescendantLabel(candidate),
            boundsInScreen = candidateBounds,
            screenTop = rootTop,
            screenHeight = rootHeight
        )
        val isTopChrome = isTopAppBarNode(
            className = candidate.className?.toString(),
            viewIdResourceName = candidate.viewIdResourceName,
            boundsInScreen = candidateBounds,
            screenTop = rootTop,
            screenHeight = rootHeight
        )
        val isPersistentHeader = candidateBounds.top <= rootTop + (rootHeight / 4) && isHeaderLike
        val isContent = isContentNode(
            node = candidate,
            bounds = candidateBounds,
            screenTop = rootTop,
            screenBottom = rootBottom,
            screenHeight = rootHeight,
            mainScrollContainer = null
        )
        val shouldIgnore = (isTopChrome || isPersistentHeader || isHeaderLike) && !isContent
        if (shouldIgnore) {
            Log.i(
                "A11Y_HELPER",
                "[FOCUS_VERIFY] ignored_post_commit_resurfaced_header eventType=$eventType candidate=${(resolvePrimaryLabel(candidate) ?: recoverDescendantLabel(candidate) ?: "<no-label>").replace("\n", " ")} committed=${(A11yHistoryManager.authoritativeCommittedLabel() ?: "<no-label>").replace("\n", " ")} committedBounds=${formatBoundsForLog(committedBounds)} candidateBounds=${formatBoundsForLog(candidateBounds)}"
            )
        }
        return shouldIgnore
    }

    private fun startAuthoritativeFocusSuppressionWindow(candidate: AccessibilityNodeInfo, label: String, status: String) {
        val until = System.currentTimeMillis() + RETARGET_SUPPRESSION_WINDOW_MS
        authoritativeCommittedNode = candidate
        authoritativeCommittedStatus = status
        A11yHistoryManager.startAuthoritativeFocusWindow(
            untilMs = until,
            label = label,
            identity = nodeIdentityOf(candidate),
            bounds = Rect().also(candidate::getBoundsInScreen),
            status = status
        )
        Log.i(
            "A11Y_HELPER",
            "[FOCUS_VERIFY] suppression_window_start untilMs=$until candidate=${label.replace("\n", " ")} bounds=${formatBoundsForLog(Rect().also(candidate::getBoundsInScreen))}"
        )
    }

    private fun clearAuthoritativeFocusSuppressionWindow(reason: String) {
        if (!A11yHistoryManager.isWithinAuthoritativeFocusWindow()) return
        authoritativeCommittedNode = null
        authoritativeCommittedStatus = "moved"
        A11yHistoryManager.clearAuthoritativeFocusWindow()
        Log.i("A11Y_HELPER", "[FOCUS_VERIFY] suppression_window_end reason=$reason")
    }

    internal fun applyBottomNavigationSafetyGuide(
        effectiveBottom: Int,
        screenBottom: Int,
        minVisibleRatio: Float = 0.85f
    ): Int {
        val minGuideBottom = (screenBottom * minVisibleRatio).toInt()
        return minOf(effectiveBottom, minGuideBottom)
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

        val focused = requestFocusFlow(
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
        return TargetActionOutcome(focused.success, focused.status, focused.targetNode)
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
        return A11yNodeUtils.isContainerLikeClassName(className)
    }

    internal fun isContainerLikeViewId(viewIdResourceName: String?): Boolean {
        return A11yNodeUtils.isContainerLikeViewId(viewIdResourceName)
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
        return A11yNodeUtils.containsSettingsKeyword(normalizedViewId) || A11yNodeUtils.containsSettingsKeyword(mergedLabel)
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
        return A11yNodeUtils.isTopAppBar(
            className = className,
            viewIdResourceName = viewIdResourceName,
            boundsInScreen = boundsInScreen,
            screenTop = screenTop,
            screenHeight = screenHeight
        )
    }

    @Suppress("UNUSED_PARAMETER")
    internal fun isBottomNavigationBarNode(
        className: String?,
        viewIdResourceName: String?,
        boundsInScreen: Rect,
        screenBottom: Int,
        screenHeight: Int
    ): Boolean {
        return A11yNodeUtils.isBottomNavigationBar(
            className = className,
            viewIdResourceName = viewIdResourceName,
            boundsInScreen = boundsInScreen,
            screenBottom = screenBottom,
            screenHeight = screenHeight
        )
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
