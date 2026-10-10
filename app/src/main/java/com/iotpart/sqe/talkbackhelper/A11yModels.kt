package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

internal typealias FocusedNode = A11yTraversalAnalyzer.FocusedNode

object A11yModelVersion {
    const val VERSION: String = "1.6.4"
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
    val aliasMembersByRepresentativeIndex: Map<Int, List<AccessibilityNodeInfo>>,
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
    val actualCurrent: AccessibilityNodeInfo?,
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
    val selectionDecision: SelectionDecision,
    val forceDirectBottomTabFocus: Boolean = false
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
    val aliasMembersByRepresentativeIndex: Map<Int, List<AccessibilityNodeInfo>>,
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
    val target: AccessibilityNodeInfo? = null,
    val attemptedResourceId: String? = null,
    val attemptedClassName: String? = null
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
                    SmartNextPerf.getChild(node, index, "A11yModels.fromNode")?.let { child ->
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
    val isBottomNavigationBar: Boolean,
    val hasClickableDescendant: Boolean = false,
    val hasFocusableDescendant: Boolean = false,
    val effectiveClickable: Boolean = false,
    val actionableDescendantResourceId: String? = null,
    val actionableDescendantClassName: String? = null,
    val actionableDescendantContentDescription: String? = null
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
            put("hasClickableDescendant", hasClickableDescendant)
            put("hasFocusableDescendant", hasFocusableDescendant)
            put("effectiveClickable", effectiveClickable)
            put("actionableDescendantResourceId", actionableDescendantResourceId ?: JSONObject.NULL)
            put("actionableDescendantClassName", actionableDescendantClassName ?: JSONObject.NULL)
            put("actionableDescendantContentDescription", actionableDescendantContentDescription ?: JSONObject.NULL)
        }
    }
}

/**
 * Diagnostic-only view of AccessibilityNodeInfo.actionList.
 *
 * This is intentionally separate from A11yNodeInfo so the normal flattened
 * traversal payload and all production navigation decisions remain unchanged.
 */
data class A11yScrollActionCapability(
    val id: Int,
    val name: String
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("id", id)
            put("name", name)
        }
    }
}

data class A11yScrollActionCapabilities(
    val actions: List<A11yScrollActionCapability>,
    val scrollForwardSupported: Boolean,
    val scrollBackwardSupported: Boolean,
    val scrollUpSupported: Boolean,
    val scrollDownSupported: Boolean
) {
    companion object {
        // AccessibilityAction ids are part of the Android accessibility
        // contract. The directional ids are not exposed as int constants by
        // compileSdk 34, so keep the diagnostic mapping explicit and stable.
        private const val ACTION_SCROLL_FORWARD_ID = 4096
        private const val ACTION_SCROLL_BACKWARD_ID = 8192
        private const val ACTION_SCROLL_UP_ID = 16908344
        private const val ACTION_SCROLL_DOWN_ID = 16908346

        fun fromActionIds(actionIds: Iterable<Int>): A11yScrollActionCapabilities {
            val ids = actionIds.toSet().sorted()

            return A11yScrollActionCapabilities(
                actions = ids.map { id ->
                    A11yScrollActionCapability(id = id, name = actionName(id))
                },
                scrollForwardSupported = ACTION_SCROLL_FORWARD_ID in ids,
                scrollBackwardSupported = ACTION_SCROLL_BACKWARD_ID in ids,
                scrollUpSupported = ACTION_SCROLL_UP_ID in ids,
                scrollDownSupported = ACTION_SCROLL_DOWN_ID in ids
            )
        }

        private fun actionName(id: Int): String {
            return when (id) {
                ACTION_SCROLL_FORWARD_ID -> "ACTION_SCROLL_FORWARD"
                ACTION_SCROLL_BACKWARD_ID -> "ACTION_SCROLL_BACKWARD"
                ACTION_SCROLL_UP_ID -> "ACTION_SCROLL_UP"
                ACTION_SCROLL_DOWN_ID -> "ACTION_SCROLL_DOWN"
                else -> "ACTION_$id"
            }
        }
    }
}

data class A11yScrollCapability(
    val path: String,
    val parentPath: String?,
    val childPaths: List<String>,
    val className: String?,
    val viewIdResourceName: String?,
    val boundsInScreen: Rect,
    val scrollable: Boolean,
    val visibleToUser: Boolean,
    val enabled: Boolean,
    val actions: List<A11yScrollActionCapability>,
    val scrollForwardSupported: Boolean,
    val scrollBackwardSupported: Boolean,
    val scrollUpSupported: Boolean,
    val scrollDownSupported: Boolean
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("path", path)
            put("parentPath", parentPath ?: JSONObject.NULL)
            put("childPaths", JSONArray().apply { childPaths.forEach(::put) })
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
            put("isScrollable", scrollable)
            put("isVisibleToUser", visibleToUser)
            put("isEnabled", enabled)
            put("actions", JSONArray().apply { actions.forEach { put(it.toJson()) } })
            put("scroll_forward_supported", scrollForwardSupported)
            put("scroll_backward_supported", scrollBackwardSupported)
            put("scroll_up_supported", scrollUpSupported)
            put("scroll_down_supported", scrollDownSupported)
            val axis = A11yNavigator.scrollAxis(className.orEmpty(), actions.map { it.id })
            put("axis", axis)
            put("axis_source", if (actions.any { it.id in 16908344..16908347 }) "directional_actions" else "class_or_unknown")
            put("axis_confidence", if (axis == "UNKNOWN") "unknown" else "explicit")
            put("vertical_can_scroll_forward", if (axis in setOf("VERTICAL", "BIDIRECTIONAL"))
                A11yNavigator.verticalScrollAction("down", actions.map { it.id }) != null else if (axis == "UNKNOWN") JSONObject.NULL else false)
        }
    }

    companion object {
        fun fromNode(
            node: AccessibilityNodeInfo,
            path: String,
            parentPath: String?,
            childPaths: List<String>
        ): A11yScrollCapability {
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            val actionCapabilities = A11yScrollActionCapabilities.fromActionIds(
                runCatching { node.actionList.map { it.id } }.getOrDefault(emptyList())
            )
            return A11yScrollCapability(
                path = path,
                parentPath = parentPath,
                childPaths = childPaths,
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = bounds,
                scrollable = node.isScrollable,
                visibleToUser = node.isVisibleToUser,
                enabled = node.isEnabled,
                actions = actionCapabilities.actions,
                scrollForwardSupported = actionCapabilities.scrollForwardSupported,
                scrollBackwardSupported = actionCapabilities.scrollBackwardSupported,
                scrollUpSupported = actionCapabilities.scrollUpSupported,
                scrollDownSupported = actionCapabilities.scrollDownSupported
            )
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
    fun toJson(includeChildren: Boolean = true): JSONObject {
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
                    if (includeChildren) {
                        children.forEach { put(it.toJson()) }
                    }
                }
            )
        }
    }

    fun toTransportJson(): JSONObject = toJson(includeChildren = false)

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
