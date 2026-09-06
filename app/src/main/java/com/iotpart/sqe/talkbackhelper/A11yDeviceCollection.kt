package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.util.IdentityHashMap

/**
 * A deliberately small, structural contract for device-list scrolling.
 *
 * The selector does not identify a collection from a class name or resource id
 * alone. A candidate must be a fresh, visible, enabled, scrollable container
 * that owns actionable, labelled card-like descendants. The score prefers the
 * nearest owner (direct card children) so an outer pager is not selected when
 * a nested collection actually owns the cards.
 */
internal data class A11yDeviceCollectionCandidate<T>(
    val value: T,
    val key: String,
    val visible: Boolean,
    val enabled: Boolean,
    val scrollable: Boolean,
    val directCardCount: Int,
    val ownedCardCount: Int,
    val minimumCardDepth: Int,
    val supportsForward: Boolean,
    val supportsBackward: Boolean,
    val fresh: Boolean = true
) {
    fun selectionRank(): List<Int> = listOf(
        if (directCardCount > 0) 1 else 0,
        directCardCount,
        ownedCardCount,
        -minimumCardDepth
    )
}

internal object A11yDeviceCollectionSelector {
    fun <T> select(
        candidates: List<A11yDeviceCollectionCandidate<T>>
    ): A11yDeviceCollectionCandidate<T>? {
        val eligible = candidates.filter {
            it.fresh &&
                it.visible &&
                it.enabled &&
                it.scrollable &&
                it.directCardCount > 0
        }
        if (eligible.isEmpty()) return null

        val ordered = eligible.sortedWith(
            compareByDescending<A11yDeviceCollectionCandidate<T>> { it.selectionRank()[0] }
                .thenByDescending { it.selectionRank()[1] }
                .thenByDescending { it.selectionRank()[2] }
                .thenByDescending { it.selectionRank()[3] }
        )
        val bestRank = ordered.first().selectionRank()
        val winners = eligible.filter { it.selectionRank() == bestRank }
        return winners.singleOrNull()
    }
}

internal enum class A11yDeviceCollectionScrollDecision {
    PERFORM_FORWARD,
    PERFORM_BACKWARD,
    TOP_BOUNDARY,
    REJECT
}

internal object A11yDeviceCollectionActionPolicy {
    private const val ACTION_SCROLL_FORWARD = 4096
    private const val ACTION_SCROLL_BACKWARD = 8192

    fun decide(
        candidate: A11yDeviceCollectionCandidate<*>?,
        backward: Boolean,
        attemptsMade: Int = 0,
        maxAttempts: Int = 1
    ): A11yDeviceCollectionScrollDecision {
        if (candidate == null || attemptsMade >= maxAttempts) {
            return A11yDeviceCollectionScrollDecision.REJECT
        }
        if (backward) {
            return if (candidate.supportsBackward) {
                A11yDeviceCollectionScrollDecision.PERFORM_BACKWARD
            } else {
                A11yDeviceCollectionScrollDecision.TOP_BOUNDARY
            }
        }
        return if (candidate.supportsForward) {
            A11yDeviceCollectionScrollDecision.PERFORM_FORWARD
        } else {
            A11yDeviceCollectionScrollDecision.REJECT
        }
    }

    fun actionId(decision: A11yDeviceCollectionScrollDecision): Int? = when (decision) {
        A11yDeviceCollectionScrollDecision.PERFORM_FORWARD -> ACTION_SCROLL_FORWARD
        A11yDeviceCollectionScrollDecision.PERFORM_BACKWARD -> ACTION_SCROLL_BACKWARD
        A11yDeviceCollectionScrollDecision.TOP_BOUNDARY,
        A11yDeviceCollectionScrollDecision.REJECT -> null
    }
}

internal data class A11yDeviceCardEvidence(
    val path: String,
    val bounds: Rect,
    val label: String?,
    val viewIdResourceName: String?,
    val visible: Boolean,
    val enabled: Boolean,
    val actionable: Boolean
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("path", path)
        put("boundsInScreen", JSONObject().apply {
            put("l", bounds.left)
            put("t", bounds.top)
            put("r", bounds.right)
            put("b", bounds.bottom)
        })
        put("label", label ?: JSONObject.NULL)
        put("viewIdResourceName", viewIdResourceName ?: JSONObject.NULL)
        put("isVisibleToUser", visible)
        put("isEnabled", enabled)
        put("actionable", actionable)
    }
}

internal data class A11yValidatedDeviceCollection(
    val node: AccessibilityNodeInfo,
    val path: String,
    val parentPath: String?,
    val bounds: Rect,
    val className: String?,
    val viewIdResourceName: String?,
    val isScrollable: Boolean,
    val isVisibleToUser: Boolean,
    val isEnabled: Boolean,
    val scrollForwardSupported: Boolean,
    val scrollBackwardSupported: Boolean,
    val cards: List<A11yDeviceCardEvidence>
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("verified", true)
        put("path", path)
        put("parentPath", parentPath ?: JSONObject.NULL)
        put("boundsInScreen", JSONObject().apply {
            put("l", bounds.left)
            put("t", bounds.top)
            put("r", bounds.right)
            put("b", bounds.bottom)
        })
        put("className", className ?: JSONObject.NULL)
        put("viewIdResourceName", viewIdResourceName ?: JSONObject.NULL)
        put("isScrollable", isScrollable)
        put("isVisibleToUser", isVisibleToUser)
        put("isEnabled", isEnabled)
        put("scrollForwardSupported", scrollForwardSupported)
        put("scrollBackwardSupported", scrollBackwardSupported)
        put("cardBounds", JSONArray().apply { cards.forEach { put(it.toJson()) } })
    }
}

internal object A11yDeviceCollection {
    private const val MAX_NODES = 512
    private const val MAX_CARD_DEPTH = 3

    private data class PendingNode(
        val node: AccessibilityNodeInfo,
        val path: String,
        val parentPath: String?
    )

    private data class CardMatch(
        val evidence: A11yDeviceCardEvidence,
        val depth: Int
    )

    fun findValidated(root: AccessibilityNodeInfo?, maxNodes: Int = MAX_NODES): A11yValidatedDeviceCollection? {
        if (root == null || maxNodes <= 0) return null

        val queue = ArrayDeque<PendingNode>()
        queue.add(PendingNode(root, "0", null))
        val candidates = mutableListOf<Pair<PendingNode, List<CardMatch>>>()
        var visited = 0

        while (queue.isNotEmpty() && visited < maxNodes) {
            val pending = queue.removeFirst()
            visited += 1
            val node = pending.node
            val cardMatches = collectCardDescendants(node, pending.path)
            if (node.isScrollable && isUsableNode(node) && cardMatches.isNotEmpty()) {
                candidates += pending to cardMatches
            }

            for (index in 0 until node.childCount) {
                node.getChild(index)?.let { child ->
                    queue.add(PendingNode(child, "${pending.path}.$index", pending.path))
                }
            }
        }

        val candidateModels = candidates.map { (pending, cards) ->
            val actions = A11yScrollActionCapabilities.fromActionIds(
                runCatching { pending.node.actionList.map { it.id } }.getOrDefault(emptyList())
            )
            A11yDeviceCollectionCandidate(
                value = pending.node,
                key = pending.path,
                visible = pending.node.isVisibleToUser,
                enabled = pending.node.isEnabled,
                scrollable = pending.node.isScrollable,
                directCardCount = cards.count { it.depth == 1 },
                ownedCardCount = cards.size,
                minimumCardDepth = cards.minOf { it.depth },
                supportsForward = actions.scrollForwardSupported,
                supportsBackward = actions.scrollBackwardSupported
            )
        }
        val selected = A11yDeviceCollectionSelector.select(candidateModels) ?: return null
        val selectedCards = candidates.firstOrNull { it.first.path == selected.key }?.second.orEmpty()
        val selectedPending = candidates.first { it.first.path == selected.key }.first
        val bounds = Rect().also { selectedPending.node.getBoundsInScreen(it) }
        val actions = A11yScrollActionCapabilities.fromActionIds(
            runCatching { selectedPending.node.actionList.map { it.id } }.getOrDefault(emptyList())
        )
        return A11yValidatedDeviceCollection(
            node = selectedPending.node,
            path = selected.key,
            parentPath = selectedPending.parentPath,
            bounds = bounds,
            className = selectedPending.node.className?.toString(),
            viewIdResourceName = selectedPending.node.viewIdResourceName,
            isScrollable = selectedPending.node.isScrollable,
            isVisibleToUser = selectedPending.node.isVisibleToUser,
            isEnabled = selectedPending.node.isEnabled,
            scrollForwardSupported = actions.scrollForwardSupported,
            scrollBackwardSupported = actions.scrollBackwardSupported,
            cards = selectedCards.map { it.evidence }
        )
    }

    private fun collectCardDescendants(
        owner: AccessibilityNodeInfo,
        ownerPath: String
    ): List<CardMatch> {
        data class PendingCard(
            val node: AccessibilityNodeInfo,
            val path: String,
            val depth: Int
        )

        val queue = ArrayDeque<PendingCard>()
        val seen = IdentityHashMap<AccessibilityNodeInfo, Boolean>()
        for (index in 0 until owner.childCount) {
            owner.getChild(index)?.let { child ->
                queue.add(PendingCard(child, "$ownerPath.$index", 1))
            }
        }

        val matches = mutableListOf<CardMatch>()
        while (queue.isNotEmpty()) {
            val pending = queue.removeFirst()
            if (pending.depth > MAX_CARD_DEPTH || seen.put(pending.node, true) != null) continue
            if (isDeviceCardNode(pending.node)) {
                val bounds = Rect().also { pending.node.getBoundsInScreen(it) }
                matches += CardMatch(
                    evidence = A11yDeviceCardEvidence(
                        path = pending.path,
                        bounds = bounds,
                        label = A11yNavigator.resolvePrimaryLabel(pending.node)
                            ?: A11yTraversalAnalyzer.recoverDescendantLabel(pending.node),
                        viewIdResourceName = pending.node.viewIdResourceName,
                        visible = pending.node.isVisibleToUser,
                        enabled = pending.node.isEnabled,
                        actionable = isActionable(pending.node)
                    ),
                    depth = pending.depth
                )
                continue
            }
            for (index in 0 until pending.node.childCount) {
                pending.node.getChild(index)?.let { child ->
                    queue.add(PendingCard(child, "${pending.path}.$index", pending.depth + 1))
                }
            }
        }
        return matches
    }

    private fun isDeviceCardNode(node: AccessibilityNodeInfo): Boolean {
        if (!isUsableNode(node) || node.isScrollable || !isActionable(node)) return false
        val label = A11yNavigator.resolvePrimaryLabel(node)
            ?: A11yTraversalAnalyzer.recoverDescendantLabel(node)
        if (label.isNullOrBlank()) return false
        val className = node.className?.toString()?.lowercase().orEmpty()
        val viewId = node.viewIdResourceName?.lowercase().orEmpty()
        val containerLike = node.childCount > 0 ||
            className.contains("viewgroup") ||
            className.contains("layout") ||
            className.contains("card")
        if (!containerLike) return false
        if (A11yNodeUtils.isBottomNavigationBar(node, screenBottom = Int.MAX_VALUE, screenHeight = Int.MAX_VALUE)) return false
        return viewId.contains("card") || className.contains("card") || className.contains("viewgroup") || node.childCount > 0
    }

    private fun isUsableNode(node: AccessibilityNodeInfo): Boolean {
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        return node.isVisibleToUser && node.isEnabled && !bounds.isEmpty
    }

    private fun isActionable(node: AccessibilityNodeInfo): Boolean {
        if (node.isClickable || node.isFocusable) return true
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        val seen = IdentityHashMap<AccessibilityNodeInfo, Boolean>()
        for (index in 0 until node.childCount) {
            node.getChild(index)?.let(queue::addLast)
        }
        var visited = 0
        while (queue.isNotEmpty() && visited < MAX_NODES) {
            val current = queue.removeFirst()
            if (seen.put(current, true) != null) continue
            visited += 1
            if (current.isVisibleToUser && current.isEnabled && (current.isClickable || current.isFocusable)) {
                return true
            }
            for (index in 0 until current.childCount) {
                current.getChild(index)?.let(queue::addLast)
            }
        }
        return false
    }
}
