package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

internal typealias FocusedNode = A11yTraversalAnalyzer.FocusedNode

object A11yModelVersion {
    const val VERSION: String = "1.6.2"
}

internal data class PostScrollContinuationPlan(
    val anchorStartIndex: Int,
    val skipGeneralScan: Boolean
)

internal data class CollectResult(
    val focusNodes: List<FocusedNode>,
    val traversalList: List<AccessibilityNodeInfo>,
    val focusNodeByNode: Map<AccessibilityNodeInfo, FocusedNode>,
    val focusState: FocusState,
    val scrollState: ScrollState
)

internal data class NormalizeResult(
    val normalizedNodes: List<FocusedNode>,
    val traversalList: List<AccessibilityNodeInfo>,
    val screenRect: Rect,
    val screenTop: Int,
    val screenBottom: Int,
    val screenHeight: Int,
    val effectiveBottom: Int
)

internal data class FocusState(
    val resolvedCurrent: AccessibilityNodeInfo?,
    val currentIndex: Int,
    val fallbackIndex: Int,
    val nextIndex: Int
)

internal data class ScrollState(
    val mainScrollContainer: AccessibilityNodeInfo?,
    val scrollableNode: AccessibilityNodeInfo?
)

internal enum class SelectionType {
    CONTINUATION,
    SCROLL,
    BOTTOM_BAR,
    END,
    REGULAR,
    FALLBACK
}

internal data class SelectionDecisionModel(
    val type: SelectionType,
    val targetIndex: Int? = null,
    val reason: String
)

internal data class SelectionDecision(
    val currentIndex: Int,
    val fallbackIndex: Int,
    val nextIndex: Int
)

internal data class FocusAttemptResult(
    val outcome: TargetActionOutcome,
    val verificationPassed: Boolean,
    val snapBackDetected: Boolean
)

internal data class CurrentPosition(
    val resolvedCurrent: AccessibilityNodeInfo?,
    val currentIndex: Int,
    val fallbackIndex: Int,
    val nextIndex: Int
)

internal data class PreScrollResult(
    val attempted: Boolean,
    val success: Boolean,
    val anchor: A11yHistoryManager.PreScrollAnchor? = null,
    val reason: String
)

internal data class PostScrollAnalysis(
    val treeChanged: Boolean,
    val anchorMaintained: Boolean,
    val newlyExposedCandidateExists: Boolean,
    val noProgress: Boolean,
    val reason: String
)

internal data class FocusExecutionResult(
    val outcome: TargetActionOutcome,
    val reasonCode: String
)

internal data class ContinuationCandidateEvaluation(
    val priority: Int,
    val rejectionReasons: List<String>,
    val isLogicalSuccessor: Boolean = false,
    val acceptedDespiteRewoundBeforeAnchor: Boolean = false
)

internal data class NewlyRevealedEvaluation(
    val prioritizedNewlyRevealed: Boolean,
    val reasons: List<String>
)

internal data class CandidateClassification(
    val isTopChrome: Boolean,
    val isPersistentHeader: Boolean,
    val isContentNode: Boolean
)

internal data class FocusRetargetDecision(
    val finalTarget: AccessibilityNodeInfo,
    val finalLabel: String,
    val source: String,
    val retargeted: Boolean,
    val commitStatus: String,
    val success: Boolean,
    val reason: String
)

internal data class PostScrollContinuationSearchResult(
    val index: Int,
    val hasValidPostScrollCandidate: Boolean
)

internal data class SmartNextRuntimeState(
    val root: AccessibilityNodeInfo,
    val collect: CollectResult,
    val normalize: NormalizeResult,
    val currentPosition: CurrentPosition,
    val visitedHistory: Set<String>,
    val visitedHistorySignatures: Set<A11yHistoryManager.VisibleHistorySignature>,
    val focusNodeByNode: Map<AccessibilityNodeInfo, FocusedNode>
)

internal data class InitialNextTargetDecision(
    val nextIndex: Int,
    val selectionDecision: SelectionDecision
)

internal data class SmartNextExecutionDecision(
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

internal data class NextActionDecision(
    val state: SmartNextRuntimeState,
    val smartNextState: SmartNextState,
    val initialTarget: InitialNextTargetDecision,
    val navigationDecision: NavigationDecision
)

internal data class NextActionExecution(
    val outcome: TargetActionOutcome
)

internal data class FindAndFocusPhaseContext(
    val root: AccessibilityNodeInfo,
    val traversalList: List<AccessibilityNodeInfo>,
    val screenTop: Int,
    val screenBottom: Int,
    val effectiveBottom: Int,
    val screenHeight: Int,
    val focusNodeByNode: Map<AccessibilityNodeInfo, FocusedNode>,
    val visitedHistory: Set<String>,
    val visitedHistorySignatures: Set<A11yHistoryManager.VisibleHistorySignature>
)

internal data class FindAndFocusRequest(
    val statusName: String,
    val isScrollAction: Boolean = false,
    val singleTargetOnly: Boolean = false,
    val excludeDesc: String? = null,
    val startIndex: Int = 0,
    val visibleHistory: Set<String> = emptySet(),
    val visibleHistorySignatures: Set<A11yHistoryManager.VisibleHistorySignature> = emptySet(),
    val allowLooping: Boolean = true,
    val preScrollAnchor: A11yHistoryManager.PreScrollAnchor? = null
)

internal data class PostScrollSearchContext(
    val excludedIndex: Int,
    val traversalStartIndex: Int,
    val resolvedAnchorIndex: Int,
    val continuationFallbackAttempted: Boolean,
    val continuationFallbackFailed: Boolean,
    val fallbackBelowAnchorIndex: Int,
    val anchorStartIndex: Int,
    val skipGeneralScan: Boolean
)

internal data class FocusLoopState(
    var skippedExcludedNode: Boolean = false,
    var focusedAny: Boolean = false,
    var focusAttempted: Boolean = false,
    var focusedOutcome: TargetActionOutcome? = null
)

internal data class SmartNextExecutionContext(
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

data class SmartNextState(
    val root: AccessibilityNodeInfo,
    val traversalList: List<AccessibilityNodeInfo>,
    val currentIndex: Int,
    val nextIndex: Int,
    val screenBounds: Rect,
    val scrollableContainer: AccessibilityNodeInfo?
)

data class NavigationDecision(
    val type: NavigationType,
    val targetIndex: Int? = null,
    val reason: String
)

enum class NavigationType {
    REGULAR,
    PRE_SCROLL,
    BOTTOM_BAR,
    END
}

data class ActionResult(
    val success: Boolean,
    val status: String,
    val targetNode: AccessibilityNodeInfo? = null
)

data class TargetActionOutcome(
    val success: Boolean,
    val reason: String,
    val target: AccessibilityNodeInfo? = null
)

object FocusLabelBuilder {
    private const val MERGED_LABEL_MAX_DEPTH = 5

    data class LabelNode(
        val text: String? = null,
        val contentDescription: String? = null,
        val children: List<LabelNode> = emptyList()
    )

    fun buildMergedLabel(root: LabelNode?, maxDepth: Int = MERGED_LABEL_MAX_DEPTH): String {
        if (root == null) return ""
        val labels = linkedSetOf<String>()
        addCandidate(labels, root.text)
        addCandidate(labels, root.contentDescription)

        if (labels.isEmpty()) {
            collectChildLabels(root.children, labels, currentDepth = 1, maxDepth = maxDepth)
        }
        return labels.joinToString(separator = " ")
    }

    private fun collectChildLabels(
        children: List<LabelNode>,
        labels: LinkedHashSet<String>,
        currentDepth: Int,
        maxDepth: Int
    ) {
        if (currentDepth > maxDepth) return
        children.forEach { child ->
            addCandidate(labels, child.text)
            addCandidate(labels, child.contentDescription)
            collectChildLabels(
                children = child.children,
                labels = labels,
                currentDepth = currentDepth + 1,
                maxDepth = maxDepth
            )
        }
    }

    private fun addCandidate(labels: LinkedHashSet<String>, value: String?) {
        value?.trim()?.takeIf { it.isNotEmpty() }?.let(labels::add)
    }
}

data class FocusChildNode(
    val text: String?,
    val contentDescription: String?,
    val className: String?,
    val viewIdResourceName: String?,
    val clickable: Boolean,
    val focusable: Boolean,
    val accessibilityFocused: Boolean,
    val visibleToUser: Boolean,
    val boundsInScreen: Rect,
    val children: List<FocusChildNode>
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("text", text ?: JSONObject.NULL)
            put("contentDescription", contentDescription ?: JSONObject.NULL)
            put("className", className ?: JSONObject.NULL)
            put("viewIdResourceName", viewIdResourceName ?: JSONObject.NULL)
            put("clickable", clickable)
            put("focusable", focusable)
            put("accessibilityFocused", accessibilityFocused)
            put("visibleToUser", visibleToUser)
            put(
                "boundsInScreen", JSONObject().apply {
                    put("l", boundsInScreen.left)
                    put("t", boundsInScreen.top)
                    put("r", boundsInScreen.right)
                    put("b", boundsInScreen.bottom)
                }
            )
            put(
                "children", JSONArray().apply {
                    children.forEach { put(it.toJson()) }
                }
            )
        }
    }

    companion object {
        private const val MAX_CHILDREN_PER_NODE = 12

        fun fromNode(
            node: AccessibilityNodeInfo,
            maxDepth: Int,
            currentDepth: Int = 1
        ): FocusChildNode {
            val rect = Rect()
            node.getBoundsInScreen(rect)
            val childSnapshots = if (currentDepth >= maxDepth) {
                emptyList()
            } else {
                val limit = minOf(node.childCount, MAX_CHILDREN_PER_NODE)
                (0 until limit).mapNotNull { index ->
                    node.getChild(index)?.let { child ->
                        fromNode(child, maxDepth = maxDepth, currentDepth = currentDepth + 1)
                    }
                }
            }

            return FocusChildNode(
                text = node.text?.toString(),
                contentDescription = node.contentDescription?.toString(),
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                clickable = node.isClickable,
                focusable = node.isFocusable,
                accessibilityFocused = node.isAccessibilityFocused,
                visibleToUser = node.isVisibleToUser,
                boundsInScreen = rect,
                children = childSnapshots
            )
        }
    }
}

data class A11yNodeInfo(
    val text: String?,
    val contentDescription: String?,
    val className: String?,
    val viewIdResourceName: String?,
    val boundsInScreen: Rect,
    val clickable: Boolean,
    val focusable: Boolean,
    val isVisibleToUser: Boolean,
    val focused: Boolean,
    val accessibilityFocused: Boolean,
    val isTopAppBar: Boolean,
    val isBottomNavigationBar: Boolean
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("text", text ?: JSONObject.NULL)
            put("contentDescription", contentDescription ?: JSONObject.NULL)
            put("className", className ?: JSONObject.NULL)
            put("viewIdResourceName", viewIdResourceName ?: JSONObject.NULL)
            put(
                "boundsInScreen", JSONObject().apply {
                    put("l", boundsInScreen.left)
                    put("t", boundsInScreen.top)
                    put("r", boundsInScreen.right)
                    put("b", boundsInScreen.bottom)
                }
            )
            put("clickable", clickable)
            put("focusable", focusable)
            put("isVisibleToUser", isVisibleToUser)
            put("focused", focused)
            put("accessibilityFocused", accessibilityFocused)
            put("isTopAppBar", isTopAppBar)
            put("isBottomNavigationBar", isBottomNavigationBar)
        }
    }
}

data class A11yDumpResponse(
    val algorithmVersion: String,
    val canScrollDown: Boolean,
    val nodes: List<A11yNodeInfo>
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("algorithmVersion", algorithmVersion)
            put("canScrollDown", canScrollDown)
            put(
                "nodes", JSONArray().apply {
                    nodes.forEach { put(it.toJson()) }
                }
            )
        }
    }
}

data class FocusSnapshot(
    val timestamp: Long,
    val schemaVersion: String,
    val snapshotBuilderVersion: String,
    val packageName: String?,
    val className: String?,
    val viewIdResourceName: String?,
    val text: String?,
    val contentDescription: String?,
    val mergedLabel: String,
    val talkbackLabel: String,
    val clickable: Boolean,
    val focusable: Boolean,
    val focused: Boolean,
    val accessibilityFocused: Boolean,
    val visibleToUser: Boolean,
    val selected: Boolean,
    val checkable: Boolean,
    val checked: Boolean,
    val enabled: Boolean,
    val boundsInScreen: Rect,
    val children: List<FocusChildNode>
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("timestamp", timestamp)
            put("schemaVersion", schemaVersion)
            put("snapshotBuilderVersion", snapshotBuilderVersion)
            put("packageName", packageName ?: JSONObject.NULL)
            put("className", className ?: JSONObject.NULL)
            put("viewIdResourceName", viewIdResourceName ?: JSONObject.NULL)
            put("text", text ?: JSONObject.NULL)
            put("contentDescription", contentDescription ?: JSONObject.NULL)
            put("mergedLabel", mergedLabel)
            put("talkbackLabel", talkbackLabel)
            put("clickable", clickable)
            put("focusable", focusable)
            put("focused", focused)
            put("accessibilityFocused", accessibilityFocused)
            put("visibleToUser", visibleToUser)
            put("isVisibleToUser", visibleToUser)
            put("selected", selected)
            put("checkable", checkable)
            put("checked", checked)
            put("enabled", enabled)
            put(
                "boundsInScreen", JSONObject().apply {
                    put("l", boundsInScreen.left)
                    put("t", boundsInScreen.top)
                    put("r", boundsInScreen.right)
                    put("b", boundsInScreen.bottom)
                    put("left", boundsInScreen.left)
                    put("top", boundsInScreen.top)
                    put("right", boundsInScreen.right)
                    put("bottom", boundsInScreen.bottom)
                }
            )
            put(
                "children", JSONArray().apply {
                    children.forEach { put(it.toJson()) }
                }
            )
        }
    }

    companion object {
        private const val TAG = "A11Y_FOCUS_SNAPSHOT"
        const val GET_FOCUS_SCHEMA_VERSION: String = "1.2.0"
        const val SNAPSHOT_BUILDER_VERSION: String = "1.2.0"
        private const val FOCUS_CHILD_MAX_DEPTH = 5

        fun fromNodeOrNull(node: AccessibilityNodeInfo?): FocusSnapshot? {
            if (node == null) {
                return null
            }
            return fromNode(node)
        }

        fun fromNode(node: AccessibilityNodeInfo): FocusSnapshot {
            val rootChildSnapshot = FocusChildNode.fromNode(node, maxDepth = FOCUS_CHILD_MAX_DEPTH)
            val mergedLabel = FocusLabelBuilder.buildMergedLabel(rootChildSnapshot.toLabelNode())
            if (mergedLabel.isNotBlank()) {
                Log.d(TAG, "mergedLabel=$mergedLabel class=${node.className} id=${node.viewIdResourceName}")
            }
            return FocusSnapshot(
                timestamp = System.currentTimeMillis(),
                schemaVersion = GET_FOCUS_SCHEMA_VERSION,
                snapshotBuilderVersion = SNAPSHOT_BUILDER_VERSION,
                packageName = node.packageName?.toString(),
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                text = node.text?.toString(),
                contentDescription = node.contentDescription?.toString(),
                mergedLabel = mergedLabel,
                talkbackLabel = mergedLabel,
                clickable = node.isClickable,
                focusable = node.isFocusable,
                focused = node.isFocused,
                accessibilityFocused = node.isAccessibilityFocused,
                visibleToUser = node.isVisibleToUser,
                selected = node.isSelected,
                checkable = node.isCheckable,
                checked = node.isChecked,
                enabled = node.isEnabled,
                boundsInScreen = rootChildSnapshot.boundsInScreen,
                children = rootChildSnapshot.children
            )
        }

        private fun FocusChildNode.toLabelNode(): FocusLabelBuilder.LabelNode {
            return FocusLabelBuilder.LabelNode(
                text = text,
                contentDescription = contentDescription,
                children = children.map { it.toLabelNode() }
            )
        }
    }
}
