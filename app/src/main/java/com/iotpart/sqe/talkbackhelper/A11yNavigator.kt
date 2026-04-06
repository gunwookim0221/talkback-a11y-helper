package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityEvent
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat
import kotlin.jvm.JvmName
import org.json.JSONObject

typealias PreScrollAnchor = A11yHistoryManager.PreScrollAnchor
typealias VisibleHistorySignature = A11yHistoryManager.VisibleHistorySignature

object A11yNavigator {
    const val NAVIGATOR_ALGORITHM_VERSION: String = "2.72.0"
    private const val MAX_ONECONNECT_SETTINGS_ROW_ANCESTOR_DISTANCE = 3
    private const val MIN_ONECONNECT_SETTINGS_ROW_HEIGHT_PX = 80


    @Volatile
    internal var lastRequestedFocusIndex: Int = A11yStateStore.lastRequestedFocusIndex

    @JvmName("setLastRequestedFocusIndexExplicit")
    internal fun setLastRequestedFocusIndex(index: Int) {
        lastRequestedFocusIndex = index
    }

    internal fun nodeObjectId(node: Any?): Int {
        return System.identityHashCode(node)
    }


    fun resetFocusHistory() {
        setLastRequestedFocusIndex(-1)
        A11yStateStore.updateLastRequestedFocusIndex(-1)
        A11yHistoryManager.clearVisitedHistory()
        Log.i("A11Y_HELPER", "Focus history has been explicitly reset by external command.")
    }

    fun dumpTreeFlat(root: AccessibilityNodeInfo?): JSONObject {
        if (root == null) {
            return A11yDumpResponse(
                algorithmVersion = NAVIGATOR_ALGORITHM_VERSION,
                canScrollDown = false,
                nodes = emptyList()
            ).toJson()
        }

        val focusNodes = A11yTraversalAnalyzer.buildTalkBackLikeFocusNodes(root)
        val screenRect = Rect().also { root.getBoundsInScreen(it) }
        val screenTop = screenRect.top
        val screenBottom = screenRect.bottom
        val screenHeight = (screenRect.bottom - screenRect.top).coerceAtLeast(1)

        val nodeInfos = focusNodes.map { focusedNode ->
            nodeToModel(
                node = focusedNode.node,
                textOverride = focusedNode.text,
                contentDescriptionOverride = focusedNode.contentDescription,
                hasClickableDescendant = focusedNode.hasClickableDescendant,
                hasFocusableDescendant = focusedNode.hasFocusableDescendant,
                effectiveClickable = focusedNode.effectiveClickable,
                actionableDescendantResourceId = focusedNode.actionableDescendantResourceId,
                actionableDescendantClassName = focusedNode.actionableDescendantClassName,
                actionableDescendantContentDescription = focusedNode.actionableDescendantContentDescription,
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


    private fun collectNodes(root: AccessibilityNodeInfo): List<FocusedNode> = A11yTraversalAnalyzer.buildTalkBackLikeFocusNodes(root)

    private fun buildTraversalList(normalizedNodes: List<FocusedNode>): List<AccessibilityNodeInfo> = normalizedNodes.map { it.node }

    internal fun resolvePrimaryLabel(node: AccessibilityNodeInfo?): String? {
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

    private fun normalizeNodes(
        focusNodes: List<FocusedNode>
    ): Pair<List<FocusedNode>, Map<Int, List<AccessibilityNodeInfo>>> {
        if (focusNodes.isEmpty()) return focusNodes to emptyMap()
        val groups = mutableListOf<MutableList<FocusedNode>>()
        focusNodes.forEach { candidate ->
            val candidateLabel = resolveFocusedNodeLabel(candidate)
            val matchingGroup = groups.firstOrNull { group ->
                val representative = selectAliasGroupRepresentative(group)
                shouldTreatAsOneConnectSettingsRowAliasGroup(
                    group = group,
                    candidate = candidate
                ) ||
                A11yTraversalAnalyzer.shouldTreatAsAliasWrapperDuplicate(
                    primaryNode = representative.node,
                    secondaryNode = candidate.node,
                    primaryLabel = resolveFocusedNodeLabel(representative),
                    secondaryLabel = candidateLabel
                )
            }
            if (matchingGroup != null) {
                matchingGroup += candidate
            } else {
                groups += mutableListOf(candidate)
            }
        }
        val normalizedNodes = mutableListOf<FocusedNode>()
        val aliasMembersByIndex = mutableMapOf<Int, List<AccessibilityNodeInfo>>()
        groups.forEach { group ->
            val representative = selectAliasGroupRepresentative(group)
            val groupIndex = normalizedNodes.size
            normalizedNodes += representative
            aliasMembersByIndex[groupIndex] = group.map { it.node }
            val groupViewIds = group.mapNotNull { it.node.viewIdResourceName }
            val oneConnectRowRepresentative = findOneConnectSettingsRowContainer(representative.node)
            if (oneConnectRowRepresentative != null) {
                val memberSummary = group.joinToString(separator = ",") { member ->
                    member.node.viewIdResourceName ?: resolvePrimaryLabel(member.node).orEmpty()
                }
                Log.d(
                    "A11Y_HELPER",
                    "[DEBUG][ROW_GROUP] formed rep=${oneConnectRowRepresentative.viewIdResourceName} members=[$memberSummary]"
                )
            }
            val hasUpdateAppCard = groupViewIds.contains(OneConnectTraversalPolicy.UPDATE_APP_CARD_VIEW_ID)
            val hasUpdateAppMember = groupViewIds.any { isOneConnectUpdateAppMemberViewId(it) }
            if (hasUpdateAppCard && hasUpdateAppMember) {
                Log.i(
                    "A11Y_HELPER",
                    "[NORMALIZE][update_app_alias_group] representative=${representative.node.viewIdResourceName} members=${groupViewIds.joinToString()}"
                )
            }
        }
        return normalizedNodes to aliasMembersByIndex
    }

    private fun normalizeSmartNextInputs(
        root: AccessibilityNodeInfo,
        collectResult: CollectResult
    ): NormalizeResult {
        val (normalizedNodes, aliasMembersByIndex) = normalizeNodes(collectResult.focusNodes)
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
        val normalizedSummary = traversalList.mapIndexed { index, node ->
            val label = (resolvePrimaryLabel(node) ?: A11yTraversalAnalyzer.recoverDescendantLabel(node) ?: "<no-label>")
                .replace("\n", " ")
            val viewId = node.viewIdResourceName ?: "<no-id>"
            "$index:$viewId:$label"
        }.joinToString(separator = " | ")
        Log.d("A11Y_HELPER", "[DEBUG][NORMALIZE] final normalized traversal summary=$normalizedSummary")
        return NormalizeResult(
            normalizedNodes = normalizedNodes,
            traversalList = traversalList,
            aliasMembersByRepresentativeIndex = aliasMembersByIndex,
            screenRect = screenRect,
            screenTop = screenTop,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            effectiveBottom = effectiveBottom
        )
    }

    private fun resolveCurrentAndNextIndex(
        traversalList: List<AccessibilityNodeInfo>,
        currentNode: AccessibilityNodeInfo?,
        aliasMembersByRepresentativeIndex: Map<Int, List<AccessibilityNodeInfo>> = emptyMap()
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
            currentIndex = A11yTraversalAnalyzer.findNodeIndexByIdentity(
                nodes = traversalList,
                target = resolvedCurrent,
                idOf = { it.viewIdResourceName },
                textOf = { it.text?.toString() },
                contentDescriptionOf = { it.contentDescription?.toString() },
                boundsOf = { Rect().also(it::getBoundsInScreen) }
            )
        }
        if (currentIndex == -1 && resolvedCurrent != null) {
            currentIndex = resolveAliasRepresentativeIndex(
                aliasMembersByRepresentativeIndex = aliasMembersByRepresentativeIndex,
                target = resolvedCurrent
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
        Log.i(
            "A11Y_HELPER",
            "[DECIDE][CURRENT] raw=${summarizeNodeForDecision(currentNode)} resolved=${summarizeNodeForDecision(resolvedCurrent)} currentIndex=$currentIndex fallbackIndex=$fallbackIndex nextIndex=$nextIndex size=${traversalList.size}"
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
        A11yHistoryManager.clearAuthoritativeFocusSuppressionWindow("new_smart_next_command_started")
        val turnId = A11yHistoryManager.issueNextSmartNextTurnId()
        A11yHistoryManager.activeSmartNextTurnId = turnId
        return try {
            val runtimeState = collectSmartNextRuntimeState(root, currentNode)
            val nextActionDecision = decideNextAction(runtimeState)
            val execution = executeNextAction(nextActionDecision)
            verifyAndFinalizeNextAction(nextActionDecision, execution)
        } finally {
            A11yHistoryManager.clearTopChromeTransientSystemUiSuppression("smart_next_turn_finished")
            if (A11yHistoryManager.activeSmartNextTurnId == turnId) {
                A11yHistoryManager.activeSmartNextTurnId = 0L
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
        val currentPosition = resolveCurrentAndNextIndex(
            traversalList = normalizeResult.traversalList,
            currentNode = currentNode,
            aliasMembersByRepresentativeIndex = normalizeResult.aliasMembersByRepresentativeIndex
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
        val navigationDecision = A11yNavigationPolicy.decideSmartNextNavigationDecision(state, initialTarget, smartNextState)
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
        val statusLockedByFinalCommit = A11yHistoryManager.lastFinalCommitTurnId != 0L &&
            A11yHistoryManager.lastFinalCommitTurnId == A11yHistoryManager.activeSmartNextTurnId
        val finalizedOutcome = if (statusLockedByFinalCommit && !execution.outcome.success) {
            val lockedTarget = A11yHistoryManager.authoritativeCommittedNode ?: execution.outcome.target
            TargetActionOutcome(
                success = true,
                reason = A11yHistoryManager.authoritativeCommittedStatus,
                target = lockedTarget
            )
        } else {
            execution.outcome
        }
        if (statusLockedByFinalCommit) {
            Log.i(
                "A11Y_HELPER",
                "[SMART_NEXT] status_locked_by_final_commit turnId=${A11yHistoryManager.activeSmartNextTurnId} status=${finalizedOutcome.reason} success=${finalizedOutcome.success}"
            )
        }
        Log.i(
            "A11Y_HELPER",
            "[SMART_NEXT][FINALIZE] nextIndex=${decision.initialTarget.nextIndex} success=${finalizedOutcome.success} reason=${finalizedOutcome.reason}"
        )
        return finalizedOutcome
    }
    private fun executeSmartNextPipeline(
        state: SmartNextRuntimeState,
        initialTarget: InitialNextTargetDecision,
        navigationDecision: NavigationDecision
    ): TargetActionOutcome {
        val executionDecision = A11yNavigationPolicy.decideSmartNextExecution(state, initialTarget, navigationDecision)
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
        val boundaryDecision = decideBoundaryConditions(executionDecision)
        if (boundaryDecision.type == SelectionType.END) {
            return handleEndOfTraversal(executionContext, executionDecision)
        }

        executionContext.root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { focusedNode ->
            val cleared = clearFocus(focusedNode)
            val focusedBounds = Rect().also { focusedNode.getBoundsInScreen(it) }
            Log.i("A11Y_HELPER", "[EXECUTE] Cleared existing accessibility focus before next move: result=$cleared bounds=$focusedBounds")
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
        val selectedCandidate = normalize.traversalList.getOrNull(executionDecision.nextIndex)
        if (selectedCandidate != null) {
            Log.i(
                "A11Y_HELPER",
                "[DECIDE] selected_candidate index=${executionDecision.nextIndex} viewId=${selectedCandidate.viewIdResourceName} label=${(resolvePrimaryLabel(selectedCandidate) ?: A11yTraversalAnalyzer.recoverDescendantLabel(selectedCandidate) ?: "<no-label>").replace("\n", " ")}"
            )
        }
        val findAndFocusContext = FindAndFocusPhaseContext(
            root = state.root,
            traversalList = normalize.traversalList,
            screenTop = normalize.screenTop,
            screenBottom = normalize.screenBottom,
            effectiveBottom = normalize.effectiveBottom,
            screenHeight = normalize.screenHeight,
            focusNodeByNode = state.focusNodeByNode,
            aliasMembersByRepresentativeIndex = normalize.aliasMembersByRepresentativeIndex,
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
            val terminalNode = traversalList.getOrNull(currentIndex)
            Log.i("A11Y_HELPER", "[EXECUTE] Last focused node is bottom bar and no next candidate. terminal end_of_sequence.")
            return TargetActionOutcome(false, "end_of_sequence", terminalNode)
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
        val nextIsBottomBar = A11yNodeUtils.isBottomNavigationBar(
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
        val visibleHistory = A11ySnapshotTracker.collectVisibleHistory(
            nodes = context.traversalList,
            screenTop = context.screenTop,
            screenBottom = context.screenBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            labelOf = { node ->
                node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            },
            isTopAppBarNodeOf = { node, bounds -> A11yNodeUtils.isTopAppBar(node.className?.toString(), node.viewIdResourceName, bounds, context.screenTop, context.screenHeight) },
            isBottomNavigationBarNodeOf = { node, bounds -> A11yNodeUtils.isBottomNavigationBar(node.className?.toString(), node.viewIdResourceName, bounds, context.screenBottom, context.screenHeight) }
        )
        val visibleHistorySignatures = A11ySnapshotTracker.collectVisibleHistorySignatures(
            nodes = context.traversalList,
            screenTop = context.screenTop,
            screenBottom = context.screenBottom,
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            labelOf = { node ->
                node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            },
            viewIdOf = { node -> node.viewIdResourceName },
            isTopAppBarNodeOf = { node, bounds -> A11yNodeUtils.isTopAppBar(node.className?.toString(), node.viewIdResourceName, bounds, context.screenTop, context.screenHeight) },
            isBottomNavigationBarNodeOf = { node, bounds -> A11yNodeUtils.isBottomNavigationBar(node.className?.toString(), node.viewIdResourceName, bounds, context.screenBottom, context.screenHeight) }
        )
        val oldSnapshot = A11ySnapshotTracker.buildNodeTextSnapshot(context.traversalList)
        val refreshedRoot = A11ySnapshotTracker.pollForUpdatedRoot(A11yHelperService.instance, oldSnapshot, context.root) ?: return TargetActionOutcome(false, "failed")
        val refreshedTraversal = buildFocusableTraversalList(refreshedRoot)
        if (oldSnapshot == A11ySnapshotTracker.buildNodeTextSnapshot(refreshedTraversal)) {
            if (reason == "end_of_traversal") return TargetActionOutcome(false, "reached_end_no_scroll_progress")
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
        val outcome = A11yPostScrollScanner.findAndFocusFirstContent(
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
        Log.e("A11Y_HELPER", "[SMART_NEXT] Post-scroll focus failed. Aborting to prevent fallback sweep loop.")
        return TargetActionOutcome(false, "failed_focus_rejected")
    }

    private fun handleRegularFocusMove(
        context: SmartNextExecutionContext,
        executionDecision: SmartNextExecutionDecision
    ): TargetActionOutcome {
        val targetIndex = executionDecision.nextIndex.coerceAtLeast(0)
        val targetNode = context.traversalList.getOrNull(targetIndex)
        if (shouldEmitOneConnectSettingsDebugLogs(current = targetNode, contextNodes = context.traversalList)) {
            Log.d("A11Y_HELPER", "[DEBUG][REGULAR] enter")
        }
        Log.i("A11Y_HELPER", "[EXECUTE] Performing regular next navigation in single-target mode targetIndex=$targetIndex")
        val outcome = A11yPostScrollScanner.findAndFocusFirstContent(
            context = context.findAndFocusContext,
            request = FindAndFocusRequest(
                statusName = executionDecision.expectedStatus,
                isScrollAction = false,
                singleTargetOnly = true,
                excludeDesc = null,
                startIndex = targetIndex,
                visibleHistory = emptySet(),
                visibleHistorySignatures = emptySet(),
                allowLooping = false,
                preScrollAnchor = null
            )
        )
        if (!outcome.success) {
            Log.i("A11Y_HELPER", "[EXECUTE] regular single-target failed -> stop sweep targetIndex=$targetIndex reason=${outcome.reason}")
            val focusedAfterFailure = context.root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
            Log.i(
                "A11Y_HELPER",
                "[EXECUTE][REGULAR_FAIL] target=${summarizeNodeForDecision(targetNode)} focusedAfterFailure=${summarizeNodeForDecision(focusedAfterFailure)} current=${summarizeNodeForDecision(context.resolvedCurrent)}"
            )
            val currentNode = context.resolvedCurrent
                ?: context.root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
            val currentNotificationsRow = findOneConnectNotificationsRowContainer(currentNode)
            if (currentNotificationsRow != null) {
                val intendedNode = context.traversalList.getOrNull(targetIndex)
                val intendedRow = findOneConnectNotificationsRowContainer(intendedNode)
                val actualFocusedNode = context.root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
                val actualFocusedRow = findOneConnectNotificationsRowContainer(actualFocusedNode)
                val failedWithinSameNotificationsGroup = (intendedRow != null && isSameNode(intendedRow, currentNotificationsRow)) ||
                    (actualFocusedRow != null && isSameNode(actualFocusedRow, currentNotificationsRow))
                if (failedWithinSameNotificationsGroup) {
                    val externalIndex = ((targetIndex + 1).coerceAtLeast(context.currentIndex + 1) until context.traversalList.size)
                        .firstOrNull { candidateIndex ->
                            val candidateRow = findOneConnectNotificationsRowContainer(context.traversalList[candidateIndex])
                            candidateRow == null || !isSameNode(candidateRow, currentNotificationsRow)
                        }
                    if (externalIndex != null) {
                        Log.d(
                            "A11Y_HELPER",
                            "[DEBUG][SMART_NEXT] notifications fallback advanced to next external candidate failedIndex=$targetIndex nextExternalIndex=$externalIndex"
                        )
                        return A11yPostScrollScanner.findAndFocusFirstContent(
                            context = context.findAndFocusContext,
                            request = FindAndFocusRequest(
                                statusName = executionDecision.expectedStatus,
                                isScrollAction = false,
                                singleTargetOnly = true,
                                excludeDesc = null,
                                startIndex = externalIndex,
                                visibleHistory = emptySet(),
                                visibleHistorySignatures = emptySet(),
                                allowLooping = false,
                                preScrollAnchor = null
                            )
                        )
                    }
                }
            }
        }
        return outcome
    }

    private fun decideInitialNextTarget(state: SmartNextRuntimeState): InitialNextTargetDecision {
        val traversalList = state.normalize.traversalList
        val currentIndex = state.currentPosition.currentIndex
        val fallbackIndex = state.currentPosition.fallbackIndex
        var nextIndex = state.currentPosition.nextIndex
        val collectCurrentIndex = state.collect.focusState.currentIndex
        val collectNextIndex = state.collect.focusState.nextIndex
        val collectTraversalSize = state.collect.traversalList.size
        val debugAroundDecision = shouldEmitOneConnectSettingsDebugLogs(
            current = traversalList.getOrNull(currentIndex),
            next = traversalList.getOrNull(nextIndex),
            fallback = traversalList.getOrNull(fallbackIndex),
            contextNodes = traversalList
        )
        if (debugAroundDecision) {
            Log.d("A11Y_HELPER", "[DEBUG][DECIDE] enter")
        }
        if (debugAroundDecision) {
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][DECIDE] source=normalize currentIndex=$currentIndex nextIndex=$nextIndex size=${traversalList.size} collectCurrentIndex=$collectCurrentIndex collectNextIndex=$collectNextIndex collectSize=$collectTraversalSize"
            )
            Log.d("A11Y_HELPER", "[DEBUG][DECIDE] current=${summarizeTraversalCandidate(traversalList, currentIndex, state)}")
            Log.d("A11Y_HELPER", "[DEBUG][DECIDE] initial_next=${summarizeTraversalCandidate(traversalList, nextIndex, state)}")
            dumpDecisionWindow(state, currentIndex, source = "normalize")
        }

        if (currentIndex == -1) {
            val initialHeroIndex = findInitialHeroSummaryCandidateIndex(traversalList)
            if (initialHeroIndex >= 0 && initialHeroIndex != nextIndex) {
                Log.i("A11Y_HELPER", "[DECIDE] initial hero summary override -> index=$initialHeroIndex")
                nextIndex = initialHeroIndex
            } else if (initialHeroIndex == -1) {
                val navigateUpIndex = traversalList.indexOfFirst { node ->
                    val packageName = node.packageName?.toString()?.trim().orEmpty()
                    if (!OneConnectTraversalPolicy.isOneConnectPackageName(packageName)) return@indexOfFirst false
                    val label = (
                        resolvePrimaryLabel(node)
                            ?: A11yTraversalAnalyzer.recoverDescendantLabel(node)
                        ).orEmpty().lowercase()
                    if (!(label.contains("navigate up") || label.contains("뒤로") || label.contains("back"))) {
                        return@indexOfFirst false
                    }
                    val rootBounds = A11yTraversalAnalyzer.resolveRootBounds(node) ?: return@indexOfFirst false
                    A11yNodeUtils.isTopAppBar(node, rootBounds.top, rootBounds.height())
                }
                if (navigateUpIndex >= 0 && navigateUpIndex != nextIndex) {
                    Log.i("A11Y_HELPER", "[DECIDE] initial hero missing -> navigate up override index=$navigateUpIndex")
                    nextIndex = navigateUpIndex
                }
            }
        }

        if (currentIndex in traversalList.indices) {
            val currentBounds = Rect().also { traversalList[currentIndex].getBoundsInScreen(it) }
            val immediateCandidateIndex = currentIndex + 1
            if (nextIndex == immediateCandidateIndex) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Preserving immediate candidate at index=$nextIndex without duplicate-skip compensation")
                val immediateNode = traversalList.getOrNull(immediateCandidateIndex)
                if (immediateNode?.viewIdResourceName?.substringAfterLast('/') == "item_history") {
                    Log.d("A11Y_HELPER", "[DEBUG][SMART_NEXT] samsung account candidate preserved between update_app and notifications index=$immediateCandidateIndex")
                }
            } else {
                val skipRecords = mutableListOf<String>()
                val beforeSkipIndex = nextIndex
                nextIndex = skipCoordinateDuplicateTraversalIndices(
                    nodes = traversalList,
                    currentBounds = currentBounds,
                    startIndex = nextIndex,
                    boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
                    onSkip = { skippedIndex, advancedIndex ->
                        if (debugAroundDecision) {
                            skipRecords += "idx=$skippedIndex(${summarizeTraversalCandidate(traversalList, skippedIndex, state)})"
                        }
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping invisible duplicate at index $skippedIndex")
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping coordinate duplicate: jumping from $skippedIndex to $advancedIndex")
                    }
                )
                if (debugAroundDecision && skipRecords.isNotEmpty()) {
                    Log.d(
                        "A11Y_HELPER",
                        "[DEBUG][DECIDE][SKIP] reason=coordinate_duplicate before=${summarizeTraversalCandidate(traversalList, beforeSkipIndex, state)} after=${summarizeTraversalCandidate(traversalList, nextIndex, state)}"
                    )
                    Log.d("A11Y_HELPER", "[DEBUG][DECIDE][SKIP] skipped_candidates=${skipRecords.joinToString(" | ")}")
                }
            }
        }
        val beforeSameRowPrevention = nextIndex
        nextIndex = preventOneConnectSettingsSameRowReselection(state, nextIndex)
        nextIndex = preventOneConnectNotificationsSameRowReselection(
            state = state,
            nextIndex = nextIndex,
            genericPreventionApplied = nextIndex != beforeSameRowPrevention
        )
        if (debugAroundDecision) {
            Log.d("A11Y_HELPER", "[DEBUG][DECIDE] final_next=${summarizeTraversalCandidate(traversalList, nextIndex, state)}")
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

    private fun findInitialHeroSummaryCandidateIndex(
        traversalList: List<AccessibilityNodeInfo>
    ): Int {
        return traversalList.indexOfFirst { node ->
            if (!node.isVisibleToUser || node.isClickable || !node.isFocusable) return@indexOfFirst false
            val packageName = node.packageName?.toString()?.trim().orEmpty()
            if (!OneConnectTraversalPolicy.isOneConnectPackageName(packageName)) return@indexOfFirst false
            val descendantTextCandidates = mutableListOf<String>()
            A11yTraversalAnalyzer.collectDescendantReadableText(
                node = node,
                includeCurrentNode = true,
                sink = descendantTextCandidates
            )
            val accepted = A11yTraversalAnalyzer.isOneConnectHeroSummaryContainer(node, descendantTextCandidates)
            if (!accepted) {
                Log.i("A11Y_HELPER", "[DECIDE] initial hero rejected index=${traversalList.indexOf(node)}")
            }
            accepted
        }
    }

    private fun resolveAliasRepresentativeIndex(
        aliasMembersByRepresentativeIndex: Map<Int, List<AccessibilityNodeInfo>>,
        target: AccessibilityNodeInfo
    ): Int {
        if (aliasMembersByRepresentativeIndex.isEmpty()) return -1
        return aliasMembersByRepresentativeIndex.entries.firstOrNull { (_, members) ->
            members.any { member ->
                isSameNode(member, target) || A11yTraversalAnalyzer.findNodeIndexByIdentity(
                    nodes = listOf(member),
                    target = target,
                    idOf = { it.viewIdResourceName },
                    textOf = { it.text?.toString() },
                    contentDescriptionOf = { it.contentDescription?.toString() },
                    boundsOf = { Rect().also(it::getBoundsInScreen) }
                ) != -1
            }
        }?.key ?: -1
    }

    private fun resolveFocusedNodeLabel(node: FocusedNode): String {
        return node.mergedLabel?.trim().takeUnless { it.isNullOrEmpty() }
            ?: node.contentDescription?.trim().takeUnless { it.isNullOrEmpty() }
            ?: node.text?.trim().takeUnless { it.isNullOrEmpty() }
            ?: resolvePrimaryLabel(node.node)
            ?: A11yTraversalAnalyzer.recoverDescendantLabel(node.node)
            ?: ""
    }

    private fun selectAliasGroupRepresentative(group: List<FocusedNode>): FocusedNode {
        selectOneConnectSettingsRowRepresentative(group)?.let { settingsRow ->
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][ROW_GROUP] representative chosen=${settingsRow.node.viewIdResourceName}"
            )
            return settingsRow
        }
        val containsUpdateAppCard = group.any {
            it.node.packageName?.toString()?.trim() == OneConnectTraversalPolicy.PACKAGE_NAME &&
                it.node.viewIdResourceName == OneConnectTraversalPolicy.UPDATE_APP_CARD_VIEW_ID
        }
        val containsUpdateAppMember = group.any {
            it.node.packageName?.toString()?.trim() == OneConnectTraversalPolicy.PACKAGE_NAME &&
                isOneConnectUpdateAppMemberViewId(it.node.viewIdResourceName)
        }
        if (containsUpdateAppCard && containsUpdateAppMember) {
            group.firstOrNull { it.node.viewIdResourceName == OneConnectTraversalPolicy.UPDATE_APP_CARD_VIEW_ID }?.let { updateAppCard ->
                Log.d(
                    "A11Y_HELPER",
                    "[DEBUG][NORMALIZE] update_app representative chosen: update_app_card"
                )
                return updateAppCard
            }
        }
        return group
            .sortedWith(
                compareByDescending<FocusedNode> { aliasRepresentativeScore(it) }
                    .thenBy { candidate ->
                        Rect().also { candidate.node.getBoundsInScreen(it) }.width() *
                            Rect().also { candidate.node.getBoundsInScreen(it) }.height()
                    }
            )
            .first()
    }

    private fun aliasRepresentativeScore(candidate: FocusedNode): Int {
        val node = candidate.node
        var score = 0
        val className = node.className?.toString()?.lowercase().orEmpty()
        if (node.isFocusable) score += 3
        if (node.isClickable) score += 2
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && node.isScreenReaderFocusable) score += 1
        if (className.contains("imagebutton")) score += 4
        if (className.contains("switch") || className.contains("toggle")) score += 4
        if (className.contains("button")) score += 2
        if (className.contains("framelayout") || className.contains("linearlayout") || className.contains("viewgroup")) {
            score -= 2
        }
        if (A11yTraversalAnalyzer.countClickableOrFocusableDescendants(node, limit = 2) == 0) score += 1
        return score
    }

    private fun isOneConnectUpdateAppMemberViewId(viewId: String?): Boolean {
        return OneConnectTraversalPolicy.isUpdateAppMemberViewId(viewId)
    }

    private fun shouldTreatAsOneConnectSettingsRowAliasGroup(
        group: List<FocusedNode>,
        candidate: FocusedNode
    ): Boolean {
        val candidateRowContainer = findOneConnectSettingsRowContainer(candidate.node) ?: return false
        return group.any { member ->
            val memberRowContainer = findOneConnectSettingsRowContainer(member.node) ?: return@any false
            if (!isSameNode(memberRowContainer, candidateRowContainer)) return@any false
            val isCandidateInRow = isNodeInsideAncestor(candidate.node, candidateRowContainer)
            val isMemberInRow = isNodeInsideAncestor(member.node, memberRowContainer)
            val candidateBounds = Rect().also { candidate.node.getBoundsInScreen(it) }
            val memberBounds = Rect().also { member.node.getBoundsInScreen(it) }
            val rowBounds = Rect().also { candidateRowContainer.getBoundsInScreen(it) }
            if (!isCandidateInRow || !isMemberInRow || !rowBounds.contains(candidateBounds) || !rowBounds.contains(memberBounds)) {
                return@any false
            }
            true
        }
    }

    private fun selectOneConnectSettingsRowRepresentative(group: List<FocusedNode>): FocusedNode? {
        val rowNode = group.mapNotNull { findOneConnectSettingsRowContainer(it.node) }
            .firstOrNull()
            ?: return null
        group.firstOrNull { isSameNode(it.node, rowNode) }?.let { return it }
        val metadata = A11yTraversalAnalyzer.collectActionableDescendantMetadata(rowNode)
        val rowLabel = resolvePrimaryLabel(rowNode) ?: A11yTraversalAnalyzer.recoverDescendantLabel(rowNode)
        return FocusedNode(
            node = rowNode,
            text = rowLabel,
            contentDescription = rowNode.contentDescription?.toString(),
            mergedLabel = rowLabel,
            hasClickableDescendant = metadata.hasClickableDescendant,
            hasFocusableDescendant = metadata.hasFocusableDescendant,
            effectiveClickable = rowNode.isClickable,
            actionableDescendantResourceId = metadata.actionableDescendantResourceId,
            actionableDescendantClassName = metadata.actionableDescendantClassName,
            actionableDescendantContentDescription = metadata.actionableDescendantContentDescription
        )
    }

    private fun findOneConnectSettingsRowContainer(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        var current = node ?: return null
        while (true) {
            val packageName = current.packageName?.toString()?.trim().orEmpty()
            if (packageName == OneConnectTraversalPolicy.PACKAGE_NAME && (current.isClickable || current.isFocusable)) {
                if (isOneConnectSettingsRowContainer(current)) {
                    return current
                }
            }
            current = current.parent ?: break
        }
        return null
    }

    private fun isOneConnectSettingsRowContainer(node: AccessibilityNodeInfo): Boolean {
        if (OneConnectTraversalPolicy.shouldRejectSettingsRowContainerEarly(node, ::isSettingsRowViewId)) {
            Log.d("A11Y_HELPER", "[DEBUG][ROW_GROUP] rejected ancestor too high=${node.viewIdResourceName}")
            return false
        }
        val rowBounds = Rect().also { node.getBoundsInScreen(it) }
        val rowHeight = rowBounds.height()
        val rowWidth = rowBounds.width()
        if (rowHeight < MIN_ONECONNECT_SETTINGS_ROW_HEIGHT_PX || rowWidth <= 0) return false
        if (rowHeight > (rowWidth * 0.6f).toInt()) {
            Log.d("A11Y_HELPER", "[DEBUG][ROW_GROUP] rejected ancestor too high=${node.viewIdResourceName}")
            return false
        }
        val titleNode = findDescendantByPredicate(
            node = node,
            maxDepth = MAX_ONECONNECT_SETTINGS_ROW_ANCESTOR_DISTANCE
        ) { child -> OneConnectTraversalPolicy.isSettingsTitleNodeCandidate(child) } ?: return false
        val hasSettingsTitle = titleNode.viewIdResourceName == OneConnectTraversalPolicy.ANDROID_TITLE_VIEW_ID ||
            OneConnectTraversalPolicy.isOneConnectPrefTitleNode(titleNode)
        if (titleNode.viewIdResourceName == OneConnectTraversalPolicy.PREF_TITLE_VIEW_ID) {
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][ROW_GROUP] title accepted resource=pref_title row=${node.viewIdResourceName}"
            )
        }
        val hasSettingsRowViewId = isSettingsRowViewId(node.viewIdResourceName)
        if (!hasSettingsTitle && !hasSettingsRowViewId) return false
        val titleDepth = ancestorDistance(ancestor = node, descendant = titleNode)
        if (titleDepth > MAX_ONECONNECT_SETTINGS_ROW_ANCESTOR_DISTANCE) {
            Log.d("A11Y_HELPER", "[DEBUG][ROW_GROUP] rejected ancestor too high=${node.viewIdResourceName}")
            return false
        }
        val titleBounds = Rect().also { titleNode.getBoundsInScreen(it) }
        if (!rowBounds.contains(titleBounds)) return false
        val switchNode = findDescendantByPredicate(
            node = node,
            maxDepth = MAX_ONECONNECT_SETTINGS_ROW_ANCESTOR_DISTANCE
        ) { child ->
            val className = child.className?.toString()?.lowercase().orEmpty()
            className.contains("switch") || child.isCheckable
        }
        val summaryNode = findDescendantByViewId(node, OneConnectTraversalPolicy.ANDROID_SUMMARY_VIEW_ID)
        if (summaryNode != null) {
            val summaryBounds = Rect().also { summaryNode.getBoundsInScreen(it) }
            if (!rowBounds.contains(summaryBounds)) return false
        }
        val anchorNode = switchNode ?: titleNode
        val nearestClickableCommonAncestor = findNearestClickableCommonAncestor(
            first = titleNode,
            second = anchorNode,
            boundary = node
        )
        if (nearestClickableCommonAncestor != null && !isSameNode(nearestClickableCommonAncestor, node)) {
            Log.d("A11Y_HELPER", "[DEBUG][ROW_GROUP] rejected ancestor too high=${node.viewIdResourceName}")
            return false
        }
        return true
    }

    private fun findOneConnectNotificationsRowContainer(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        var current = node ?: return null
        while (true) {
            val packageName = current.packageName?.toString()?.trim().orEmpty()
            if (packageName == OneConnectTraversalPolicy.PACKAGE_NAME && (current.isClickable || current.isFocusable)) {
                val titleNode = findDescendantByViewId(current, OneConnectTraversalPolicy.NOTIFICATIONS_TITLE_VIEW_ID)
                val switchNode = findDescendantByViewId(current, OneConnectTraversalPolicy.NOTIFICATIONS_SWITCH_VIEW_ID)
                if (titleNode != null && switchNode != null) {
                    val rowBounds = Rect().also { current.getBoundsInScreen(it) }
                    val titleBounds = Rect().also { titleNode.getBoundsInScreen(it) }
                    val switchBounds = Rect().also { switchNode.getBoundsInScreen(it) }
                    val titleDepth = ancestorDistance(ancestor = current, descendant = titleNode)
                    val switchDepth = ancestorDistance(ancestor = current, descendant = switchNode)
                    val nearestClickableCommonAncestor = findNearestClickableCommonAncestor(
                        first = titleNode,
                        second = switchNode,
                        boundary = current
                    )
                    val hasCloserRowAncestor = nearestClickableCommonAncestor != null && !isSameNode(nearestClickableCommonAncestor, current)
                    val tooHighByDepth = titleDepth > MAX_ONECONNECT_SETTINGS_ROW_ANCESTOR_DISTANCE ||
                        switchDepth > MAX_ONECONNECT_SETTINGS_ROW_ANCESTOR_DISTANCE
                    if (hasCloserRowAncestor || tooHighByDepth) {
                        Log.d(
                            "A11Y_HELPER",
                            "[DEBUG][NORMALIZE] notifications representative rejected because ancestor too high viewId=${current.viewIdResourceName} titleDepth=$titleDepth switchDepth=$switchDepth"
                        )
                    } else if (rowBounds.contains(titleBounds) && rowBounds.contains(switchBounds)) {
                        return current
                    }
                }
            }
            current = current.parent ?: break
        }
        return null
    }

    private fun findDescendantByPredicate(
        node: AccessibilityNodeInfo,
        maxDepth: Int,
        predicate: (AccessibilityNodeInfo) -> Boolean
    ): AccessibilityNodeInfo? {
        val pending = ArrayDeque<Pair<AccessibilityNodeInfo, Int>>()
        pending.add(node to 0)
        while (pending.isNotEmpty()) {
            val (current, depth) = pending.removeFirst()
            if (depth > maxDepth) continue
            if (!(depth == 0 && isSameNode(current, node)) && predicate(current)) {
                return current
            }
            if (depth == maxDepth) continue
            for (i in 0 until current.childCount) {
                val child = current.getChild(i) ?: continue
                pending.add(child to depth + 1)
            }
        }
        return null
    }

    private fun findDescendantByViewId(node: AccessibilityNodeInfo, viewId: String): AccessibilityNodeInfo? {
        if (node.viewIdResourceName == viewId) return node
        val pending = ArrayDeque<AccessibilityNodeInfo>()
        pending.add(node)
        while (pending.isNotEmpty()) {
            val current = pending.removeFirst()
            for (i in 0 until current.childCount) {
                val child = current.getChild(i) ?: continue
                if (child.viewIdResourceName == viewId) {
                    return child
                }
                pending.add(child)
            }
        }
        return null
    }

    private fun ancestorDistance(
        ancestor: AccessibilityNodeInfo,
        descendant: AccessibilityNodeInfo
    ): Int {
        var distance = 0
        var current: AccessibilityNodeInfo? = descendant
        while (current != null) {
            if (isSameNode(current, ancestor)) return distance
            current = current.parent
            distance += 1
        }
        return Int.MAX_VALUE
    }

    private fun findNearestClickableCommonAncestor(
        first: AccessibilityNodeInfo,
        second: AccessibilityNodeInfo,
        boundary: AccessibilityNodeInfo
    ): AccessibilityNodeInfo? {
        val firstAncestors = mutableListOf<AccessibilityNodeInfo>()
        var current: AccessibilityNodeInfo? = first
        while (current != null) {
            firstAncestors += current
            if (isSameNode(current, boundary)) break
            current = current.parent
        }
        var secondCurrent: AccessibilityNodeInfo? = second
        while (secondCurrent != null) {
            val secondCurrentNode = secondCurrent
            val matched = firstAncestors.firstOrNull { candidate -> isSameNode(candidate, secondCurrentNode) }
            if (matched != null && (matched.isClickable || matched.isFocusable)) {
                return matched
            }
            if (isSameNode(secondCurrentNode, boundary)) break
            secondCurrent = secondCurrentNode.parent
        }
        return null
    }

    private fun isNodeInsideAncestor(node: AccessibilityNodeInfo, ancestor: AccessibilityNodeInfo): Boolean {
        if (isSameNode(node, ancestor)) return true
        var current = node.parent
        while (current != null) {
            if (isSameNode(current, ancestor)) return true
            current = current.parent
        }
        return false
    }

    private fun preventOneConnectSettingsSameRowReselection(
        state: SmartNextRuntimeState,
        nextIndex: Int
    ): Int {
        val normalizedTraversal = state.normalize.traversalList
        if (nextIndex !in normalizedTraversal.indices) return nextIndex
        val currentNode = state.currentPosition.resolvedCurrent ?: normalizedTraversal.getOrNull(state.currentPosition.currentIndex)
            ?: return nextIndex
        val currentRowContainer = findOneConnectSettingsRowContainer(currentNode) ?: return nextIndex
        val nextCandidate = normalizedTraversal[nextIndex]
        val nextCandidateRow = findOneConnectSettingsRowContainer(nextCandidate) ?: return nextIndex
        if (!isSameNode(nextCandidateRow, currentRowContainer)) return nextIndex
        if (nextCandidate.viewIdResourceName == OneConnectTraversalPolicy.PREF_TITLE_VIEW_ID) {
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][ROW_GROUP] representative already consumed for pref_title row"
            )
        }
        Log.d(
            "A11Y_HELPER",
            "[DEBUG][ROW_GROUP] skip same-row candidate resource=${nextCandidate.viewIdResourceName}"
        )
        for (index in (nextIndex + 1) until normalizedTraversal.size) {
            val candidate = normalizedTraversal[index]
            val candidateRow = findOneConnectSettingsRowContainer(candidate)
            if (candidateRow != null && isSameNode(candidateRow, currentRowContainer)) {
                Log.d(
                    "A11Y_HELPER",
                    "[DEBUG][ROW_GROUP] skip same-row candidate resource=${candidate.viewIdResourceName}"
                )
                continue
            }
            return index
        }
        return nextIndex
    }

    private fun preventOneConnectNotificationsSameRowReselection(
        state: SmartNextRuntimeState,
        nextIndex: Int,
        genericPreventionApplied: Boolean
    ): Int {
        if (genericPreventionApplied) return nextIndex
        val normalizedTraversal = state.normalize.traversalList
        val debugEnabled = shouldEmitOneConnectSettingsDebugLogs(
            current = state.currentPosition.resolvedCurrent ?: normalizedTraversal.getOrNull(state.currentPosition.currentIndex),
            next = normalizedTraversal.getOrNull(nextIndex),
            contextNodes = normalizedTraversal
        )
        if (debugEnabled) {
            Log.d("A11Y_HELPER", "[DEBUG][ONECONNECT][NOTI_FALLBACK] enter")
        }
        if (nextIndex !in normalizedTraversal.indices) return nextIndex
        val currentNode = state.currentPosition.resolvedCurrent ?: normalizedTraversal.getOrNull(state.currentPosition.currentIndex)
            ?: return nextIndex
        val currentRowContainer = findOneConnectNotificationsRowContainer(currentNode) ?: return nextIndex
        val representativeIndex = normalizedTraversal.indexOfFirst { candidate ->
            val candidateRow = findOneConnectNotificationsRowContainer(candidate) ?: return@indexOfFirst false
            isSameNode(candidateRow, currentRowContainer)
        }
        if (representativeIndex !in normalizedTraversal.indices) return nextIndex
        val representativeNode = normalizedTraversal[representativeIndex]
        val representativeVisited = isNodeVisitedBySignature(representativeNode, state.visitedHistorySignatures)
        val nextCandidate = normalizedTraversal[nextIndex]
        val nextCandidateRow = findOneConnectNotificationsRowContainer(nextCandidate)
        val sameRow = nextCandidateRow != null && isSameNode(nextCandidateRow, currentRowContainer)
        if (debugEnabled) {
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][ONECONNECT][NOTI_FALLBACK] enter current=${summarizeTraversalCandidate(normalizedTraversal, state.currentPosition.currentIndex, state)} next=${summarizeTraversalCandidate(normalizedTraversal, nextIndex, state)} rep=${summarizeTraversalCandidate(normalizedTraversal, representativeIndex, state)}"
            )
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][ONECONNECT][NOTI_FALLBACK] repVisited=$representativeVisited sameRow=$sameRow nextIndex=$nextIndex representativeIndex=$representativeIndex"
            )
        }
        if (!sameRow) {
            if (debugEnabled) {
                Log.d("A11Y_HELPER", "[DEBUG][ONECONNECT][NOTI_FALLBACK] prevented=false reason=next_candidate_not_same_row")
            }
            return nextIndex
        }
        Log.d(
            "A11Y_HELPER",
            "[DEBUG][ONECONNECT][NOTI_FALLBACK] notifications same-row reselection prevented index=$nextIndex representativeIndex=$representativeIndex representativeVisited=$representativeVisited"
        )
        for (index in (nextIndex + 1) until normalizedTraversal.size) {
            val candidateRow = findOneConnectNotificationsRowContainer(normalizedTraversal[index])
            if (candidateRow != null && isSameNode(candidateRow, currentRowContainer)) {
                Log.d(
                    "A11Y_HELPER",
                    "[DEBUG][ONECONNECT][NOTI_FALLBACK] notifications group skipped because representative already consumed"
                )
                continue
            }
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][ONECONNECT][NOTI_FALLBACK] notifications advanced to next external candidate index=$index"
            )
            if (debugEnabled) {
                Log.d(
                    "A11Y_HELPER",
                    "[DEBUG][ONECONNECT][NOTI_FALLBACK] prevented=true replacement=${summarizeTraversalCandidate(normalizedTraversal, index, state)}"
                )
            }
            return index
        }
        if (debugEnabled) {
            Log.d("A11Y_HELPER", "[DEBUG][ONECONNECT][NOTI_FALLBACK] prevented=false reason=no_external_candidate")
        }
        return nextIndex
    }

    private fun isNodeVisitedBySignature(
        node: AccessibilityNodeInfo,
        visitedSignatures: Set<VisibleHistorySignature>
    ): Boolean {
        if (visitedSignatures.isEmpty()) return false
        val bounds = Rect().also(node::getBoundsInScreen)
        val viewId = node.viewIdResourceName
        val identity = buildNodeIdentityForHistory(node)
        return visitedSignatures.any { signature ->
            val sameBounds = signature.bounds == bounds
            val sameViewId = !viewId.isNullOrBlank() && viewId == signature.viewId
            val sameIdentity = !identity.isNullOrBlank() && identity == signature.nodeIdentity
            sameBounds && (sameViewId || sameIdentity)
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
        traversalIndex: Int = -1,
        aliasMembersByRepresentativeIndex: Map<Int, List<AccessibilityNodeInfo>> = emptyMap()
    ): TargetActionOutcome {
        val result = A11yFocusExecutor.requestFocusFlow(
            root = root,
            target = target,
            screenTop = screenTop,
            effectiveBottom = effectiveBottom,
            status = status,
            isScrollAction = false,
            traversalIndex = traversalIndex,
            traversalListSnapshot = traversalList,
            currentFocusIndexHint = currentIndex,
            aliasMembersByTraversalIndex = aliasMembersByRepresentativeIndex
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


    private fun snapshotVisitedHistoryLabels(): Set<String> = A11yHistoryManager.snapshotVisitedHistoryLabels()

    private fun snapshotVisitedHistorySignatures(): Set<VisibleHistorySignature> = A11yHistoryManager.snapshotVisitedHistorySignatures()

    private fun buildNodeIdentityForHistory(node: AccessibilityNodeInfo): String = nodeIdentityOf(node).orEmpty()

    internal fun nodeIdentityOf(windowId: Int, className: String?, packageName: String?): String {
        val normalizedClassName = className?.trim().orEmpty()
        val normalizedPackageName = packageName?.trim().orEmpty()
        return "window=$windowId|class=$normalizedClassName|package=$normalizedPackageName"
    }

    internal fun nodeIdentityOf(node: AccessibilityNodeInfo?): String? {
        node ?: return null
        return nodeIdentityOf(
            windowId = node.windowId,
            className = node.className?.toString(),
            packageName = node.packageName?.toString()
        )
    }

    internal fun nodeIdentityOf(node: AccessibilityNodeInfoCompat?): String? {
        node ?: return null
        return nodeIdentityOf(
            windowId = node.windowId,
            className = node.className?.toString(),
            packageName = node.packageName?.toString()
        )
    }

    internal fun nodeIdentityOf(snapshot: FocusSnapshot?): String? {
        snapshot ?: return null
        return nodeIdentityOf(
            windowId = -1,
            className = snapshot.className,
            packageName = snapshot.packageName
        )
    }

    internal fun logVisitedHistorySkip(reason: String, label: String?, viewId: String?, bounds: Rect? = null) {
        A11yHistoryManager.logVisitedHistorySkip(reason, label, viewId, bounds)
    }

    internal fun recordVisitedFocus(node: AccessibilityNodeInfo, label: String, reason: String) {
        val normalizedLabel = label.trim()
        if (shouldEmitOneConnectSettingsDebugLogs(current = node)) {
            Log.d("A11Y_HELPER", "[DEBUG][VISITED] enter")
        }
        val descendantTextCandidates = mutableListOf<String>().also { textCandidates ->
            A11yTraversalAnalyzer.collectDescendantReadableText(
                node = node,
                includeCurrentNode = true,
                sink = textCandidates
            )
        }
        if (A11yTraversalAnalyzer.shouldExcludeContainerNodeFromTraversal(node, descendantTextCandidates)) {
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
        if (shouldEmitOneConnectSettingsDebugLogs(current = node)) {
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][ROW_GROUP][VISITED] representative=${summarizeNodeCompact(node)} signature=viewId=${node.viewIdResourceName} bounds=${formatBoundsForLog(bounds)} identity=$nodeIdentity"
            )
        }
    }

    internal fun recordVisitedAliasMembers(
        representativeNode: AccessibilityNodeInfo,
        representativeLabel: String,
        aliasMembers: List<AccessibilityNodeInfo>,
        reason: String
    ) {
        val mergedAliasMembers = OneConnectTraversalPolicy.extendUpdateAppAliasMembers(
            representativeNode = representativeNode,
            aliasMembers = aliasMembers
        )
        if (mergedAliasMembers.isEmpty()) return
        val normalizedRepresentativeLabel = representativeLabel.trim()
        val recordedKeys = linkedSetOf<String>()
        mergedAliasMembers.forEach { member ->
            val bounds = Rect().also { member.getBoundsInScreen(it) }
            val memberIdentity = buildNodeIdentityForHistory(member)
            val uniqueKey = "${member.viewIdResourceName}|$bounds|$memberIdentity"
            if (!recordedKeys.add(uniqueKey)) return@forEach
            val memberLabel = resolvePrimaryLabel(member)
                ?: A11yTraversalAnalyzer.recoverDescendantLabel(member)
                ?: normalizedRepresentativeLabel
            A11yHistoryManager.recordVisitedSignature(
                label = memberLabel,
                viewId = member.viewIdResourceName,
                bounds = bounds,
                nodeIdentity = memberIdentity
            )
        }
        val representativeIdentity = buildNodeIdentityForHistory(representativeNode)
        Log.i(
            "A11Y_HELPER",
            "[SMART_NEXT] visitedHistory alias_group add: reason=$reason representative=${normalizedRepresentativeLabel.replace("\n", " ")} identity=$representativeIdentity aliases=${recordedKeys.size}"
        )
        if (shouldEmitOneConnectSettingsDebugLogs(current = representativeNode)) {
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][ROW_GROUP][VISITED] representative=${summarizeNodeCompact(representativeNode)} aliases=${recordedKeys.size} signature=viewId=${representativeNode.viewIdResourceName} identity=$representativeIdentity"
            )
        }
    }

    private fun shouldEmitOneConnectSettingsDebugLogs(
        current: AccessibilityNodeInfo? = null,
        next: AccessibilityNodeInfo? = null,
        fallback: AccessibilityNodeInfo? = null,
        contextNodes: List<AccessibilityNodeInfo> = emptyList()
    ): Boolean {
        val scopedNodes = buildList {
            current?.let(::add)
            next?.let(::add)
            fallback?.let(::add)
            if (contextNodes.isNotEmpty()) {
                add(contextNodes.first())
                add(contextNodes.last())
            }
        }
        return scopedNodes.any(::isOneConnectSettingsDebugTargetNode) ||
            contextNodes.any(::isOneConnectSettingsDebugTargetNode)
    }

    private fun isOneConnectSettingsDebugTargetNode(node: AccessibilityNodeInfo): Boolean {
        val label = (resolvePrimaryLabel(node) ?: A11yTraversalAnalyzer.recoverDescendantLabel(node)).orEmpty().lowercase()
        return OneConnectTraversalPolicy.isSettingsDebugTargetNode(node, label)
    }

    private fun summarizeTraversalCandidate(
        traversal: List<AccessibilityNodeInfo>,
        index: Int,
        state: SmartNextRuntimeState
    ): String {
        if (index !in traversal.indices) return "idx=$index(out_of_bounds)"
        val node = traversal[index]
        val label = state.focusNodeByNode[node]?.mergedLabel?.trim().takeUnless { it.isNullOrEmpty() }
            ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: A11yTraversalAnalyzer.recoverDescendantLabel(node)
            ?: "<no-label>"
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        val representative = state.normalize.aliasMembersByRepresentativeIndex[index]?.any { member -> isSameNode(member, node) } == true
        return "idx=$index id=${node.viewIdResourceName} class=${node.className} bounds=${formatBoundsForLog(bounds)} label=${label.replace("\n", " ")} clickable=${node.isClickable} focusable=${node.isFocusable} representative=$representative source=normalize"
    }

    private fun summarizeNodeCompact(node: AccessibilityNodeInfo): String {
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        val label = resolvePrimaryLabel(node) ?: A11yTraversalAnalyzer.recoverDescendantLabel(node) ?: "<no-label>"
        return "id=${node.viewIdResourceName} bounds=${formatBoundsForLog(bounds)} label=${label.replace("\n", " ")}"
    }

    private fun summarizeNodeForDecision(node: AccessibilityNodeInfo?): String {
        if (node == null) return "null"
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        val label = resolvePrimaryLabel(node)
            ?: A11yTraversalAnalyzer.recoverDescendantLabel(node)
            ?: "<no-label>"
        val className = node.className?.toString().orEmpty()
        val viewId = node.viewIdResourceName ?: "<no-id>"
        val focused = node.isAccessibilityFocused || node.isFocused
        return "id=$viewId class=$className bounds=${formatBoundsForLog(bounds)} label=${label.replace("\n", " ")} focused=$focused"
    }

    private fun dumpDecisionWindow(state: SmartNextRuntimeState, centerIndex: Int, source: String, radius: Int = 4) {
        val traversal = state.normalize.traversalList
        if (traversal.isEmpty()) return
        val safeCenter = centerIndex.coerceIn(0, traversal.lastIndex)
        val start = (safeCenter - radius).coerceAtLeast(0)
        val end = (safeCenter + radius).coerceAtMost(traversal.lastIndex)
        for (index in start..end) {
            val node = traversal[index]
            if (!isOneConnectSettingsDebugTargetNode(node) && index != safeCenter) continue
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            val label = state.focusNodeByNode[node]?.mergedLabel?.trim().takeUnless { it.isNullOrEmpty() }
                ?: resolvePrimaryLabel(node)
                ?: A11yTraversalAnalyzer.recoverDescendantLabel(node)
                ?: "<no-label>"
            val representative = state.normalize.aliasMembersByRepresentativeIndex[index]?.any { member -> isSameNode(member, node) } == true
            Log.d(
                "A11Y_HELPER",
                "[DEBUG][DECIDE][WINDOW] idx=$index id=${node.viewIdResourceName} top=${bounds.top} left=${bounds.left} label=${label.replace("\n", " ")} representative=$representative source=$source"
            )
        }
    }

    internal fun resolveFocusRetargetDecision(
        root: AccessibilityNodeInfo,
        intendedTarget: AccessibilityNodeInfo,
        intendedLabel: String,
        traversalListSnapshot: List<AccessibilityNodeInfo>?,
        intendedIndex: Int,
        isScrollAction: Boolean,
        requestedStatus: String
    ): FocusRetargetDecision = A11yFocusExecutor.resolveFocusRetargetDecision(
        root = root,
        intendedTarget = intendedTarget,
        intendedLabel = intendedLabel,
        traversalListSnapshot = traversalListSnapshot,
        intendedIndex = intendedIndex,
        isScrollAction = isScrollAction,
        requestedStatus = requestedStatus
    )

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
    ) = A11yFocusExecutor.alignCandidateForReadableFocus(
        root = root,
        target = target,
        label = label,
        screenTop = screenTop,
        effectiveBottom = effectiveBottom,
        isTopBar = isTopBar,
        isBottomBar = isBottomBar,
        canScrollForwardHint = canScrollForwardHint,
        intendedTrailingCandidate = intendedTrailingCandidate,
        maxPreFocusAdjustments = maxPreFocusAdjustments
    )

    internal fun shouldUseMinimalPreFocusAdjustment(
        intendedBounds: Rect,
        trailingCandidateBounds: Rect?,
        screenTop: Int,
        effectiveBottom: Int
    ): Boolean = A11yFocusExecutor.shouldUseMinimalPreFocusAdjustment(
        intendedBounds = intendedBounds,
        trailingCandidateBounds = trailingCandidateBounds,
        screenTop = screenTop,
        effectiveBottom = effectiveBottom
    )

    internal fun isNodePartiallyVisible(bounds: Rect, screenTop: Int, effectiveBottom: Int): Boolean =
        A11yFocusExecutor.isNodePartiallyVisible(bounds, screenTop, effectiveBottom)

    internal fun wouldOvershootPastIntendedCandidate(
        intendedBounds: Rect,
        trailingCandidateBounds: Rect?,
        screenTop: Int,
        effectiveBottom: Int
    ): Boolean = A11yFocusExecutor.wouldOvershootPastIntendedCandidate(
        intendedBounds = intendedBounds,
        trailingCandidateBounds = trailingCandidateBounds,
        screenTop = screenTop,
        effectiveBottom = effectiveBottom
    )

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
    ): Int = A11yFocusExecutor.findPartiallyVisibleNextCandidate(
        traversalList = traversalList,
        currentIndex = currentIndex,
        screenTop = screenTop,
        effectiveBottom = effectiveBottom,
        screenBottom = screenBottom,
        screenHeight = screenHeight,
        boundsOf = boundsOf,
        classNameOf = classNameOf,
        viewIdOf = viewIdOf
    )

    internal fun visibleHeightInViewport(bounds: Rect, screenTop: Int, effectiveBottom: Int): Int =
        A11yFocusExecutor.visibleHeightInViewport(bounds, screenTop, effectiveBottom)

    internal fun <T> findNextEligibleTraversalCandidate(
        traversalList: List<T>,
        fromIndex: Int,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?
    ): T? = A11yFocusExecutor.findNextEligibleTraversalCandidate(
        traversalList = traversalList,
        fromIndex = fromIndex,
        screenTop = screenTop,
        screenBottom = screenBottom,
        screenHeight = screenHeight,
        boundsOf = boundsOf,
        classNameOf = classNameOf,
        viewIdOf = viewIdOf
    )

    internal fun clearAccessibilityFocusAndRefresh(root: AccessibilityNodeInfo) =
        A11yFocusExecutor.clearAccessibilityFocusAndRefresh(root)

    internal fun requestInputFocusBeforeAccessibilityFocus(target: AccessibilityNodeInfo, label: String): Boolean =
        A11yFocusExecutor.requestInputFocusBeforeAccessibilityFocus(target, label)

    internal fun formatBoundsForLog(bounds: Rect?): String {
        return bounds?.let { "[${it.left},${it.top},${it.right},${it.bottom}]" } ?: "[null]"
    }

    internal fun isHeaderLikeCandidate(
        className: String?,
        viewIdResourceName: String?,
        label: String?,
        boundsInScreen: Rect,
        screenTop: Int,
        screenHeight: Int
    ): Boolean = A11yNodeUtils.isHeaderLikeCandidate(
        className = className,
        viewIdResourceName = viewIdResourceName,
        label = label,
        boundsInScreen = boundsInScreen,
        screenTop = screenTop,
        screenHeight = screenHeight
    )


    internal fun isSuppressibleHeaderNoiseNode(
        node: AccessibilityNodeInfo,
        bounds: Rect,
        rootTop: Int,
        rootHeight: Int,
        anchorBounds: Rect
    ): Boolean {
        val headerLike = isHeaderLikeCandidate(
            className = node.className?.toString(),
            viewIdResourceName = node.viewIdResourceName,
            label = resolvePrimaryLabel(node) ?: A11yTraversalAnalyzer.recoverDescendantLabel(node),
            boundsInScreen = bounds,
            screenTop = rootTop,
            screenHeight = rootHeight
        ) || A11yNodeUtils.isTopAppBar(
            className = node.className?.toString(),
            viewIdResourceName = node.viewIdResourceName,
            boundsInScreen = bounds,
            screenTop = rootTop,
            screenHeight = rootHeight
        )
        return headerLike && bounds.bottom <= anchorBounds.top
    }

    internal fun applyBottomNavigationSafetyGuide(
        effectiveBottom: Int,
        screenBottom: Int,
        minVisibleRatio: Float = 0.85f
    ): Int {
        val minGuideBottom = (screenBottom * minVisibleRatio).toInt()
        return minOf(effectiveBottom, minGuideBottom)
    }
    internal fun shouldReuseExistingAccessibilityFocus(
        label: String,
        isScrollAction: Boolean,
        currentFocusedBounds: Rect?,
        targetBounds: Rect?
    ): Boolean {
        return false
    }

    internal fun isNodePhysicallyOffScreen(bounds: Rect, screenTop: Int, screenBottom: Int): Boolean =
        A11yNodeUtils.isNodePhysicallyOffScreen(bounds, screenTop, screenBottom)

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
            isScrollable = { isEligibleVerticalScrollNode(it) },
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } }
        )
    }

    internal fun isWithinTopContentArea(
        nodeTop: Int,
        screenTop: Int,
        screenHeight: Int,
        topAreaMaxPx: Int = 500
    ): Boolean = A11yNodeUtils.isWithinTopContentArea(nodeTop, screenTop, screenHeight, topAreaMaxPx)

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

    internal fun isSettingsRowViewId(viewIdResourceName: String?): Boolean {
        return A11yTraversalAnalyzer.isSettingsRowViewId(viewIdResourceName)
    }

    internal fun isContainerLikeClassName(className: String?): Boolean {
        return A11yNodeUtils.isContainerLikeClassName(className)
    }

    internal fun isContainerLikeViewId(viewIdResourceName: String?): Boolean {
        return A11yNodeUtils.isContainerLikeViewId(viewIdResourceName)
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
            A11yTraversalAnalyzer.findNodeIndexByIdentity(
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
        return A11yTraversalAnalyzer.buildTalkBackLikeFocusNodes(root).map { it.node }
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

    internal fun hasScrollableDownCandidate(root: AccessibilityNodeInfo?): Boolean {
        return findScrollableForwardCandidate(root) != null
    }

    internal fun findScrollableForwardCandidate(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (root == null) return null

        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)

        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            val hasScrollableDown = hasScrollableDownCandidateByAction(
                nodesInOrder = listOf(node),
                isVisibleToUser = { it.isVisibleToUser },
                isScrollable = { isEligibleVerticalScrollNode(it) },
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

    internal fun findScrollableForwardAncestorCandidate(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        return findScrollableForwardAncestorCandidate(
            node = node,
            parentOf = { it.parent },
            isScrollable = { isEligibleVerticalScrollNode(it) },
            hasScrollForwardAction = {
                it.actionList.contains(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_FORWARD)
            }
        )
    }

    internal fun isEligibleVerticalScrollNode(node: AccessibilityNodeInfo): Boolean {
        if (!node.isScrollable) return false
        val className = node.className?.toString()?.lowercase() ?: ""
        return !className.contains("horizontal") && !className.contains("viewpager")
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

    private fun nodeToModel(
        node: AccessibilityNodeInfo,
        textOverride: String? = null,
        contentDescriptionOverride: String? = null,
        hasClickableDescendant: Boolean = false,
        hasFocusableDescendant: Boolean = false,
        effectiveClickable: Boolean = false,
        actionableDescendantResourceId: String? = null,
        actionableDescendantClassName: String? = null,
        actionableDescendantContentDescription: String? = null,
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
            isTopAppBar = A11yNodeUtils.isTopAppBar(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = rect,
                screenTop = screenTop,
                screenHeight = screenHeight
            ),
            isBottomNavigationBar = A11yNodeUtils.isBottomNavigationBar(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = rect,
                screenBottom = screenBottom,
                screenHeight = screenHeight
            ),
            hasClickableDescendant = hasClickableDescendant,
            hasFocusableDescendant = hasFocusableDescendant,
            effectiveClickable = effectiveClickable,
            actionableDescendantResourceId = actionableDescendantResourceId,
            actionableDescendantClassName = actionableDescendantClassName,
            actionableDescendantContentDescription = actionableDescendantContentDescription
        )
    }
}
