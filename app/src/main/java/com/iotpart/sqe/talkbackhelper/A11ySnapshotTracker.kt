package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

typealias SnapshotVisibleHistorySignature = A11yHistoryManager.VisibleHistorySignature

object A11ySnapshotTracker {
    const val SNAPSHOT_TRACKER_VERSION: String = "1.0.9"
    private const val ONECONNECT_UPDATE_APP_CARD_VIEW_ID = "com.samsung.android.oneconnect:id/update_app_card"
    private const val ONECONNECT_UPDATE_APP_TITLE_VIEW_ID = "com.samsung.android.oneconnect:id/update_app_title"
    private const val ONECONNECT_UPDATE_APP_TEXT_VIEW_ID = "com.samsung.android.oneconnect:id/update_app_text"
    private const val ONECONNECT_UPDATE_APP_CLOSE_BUTTON_VIEW_ID = "com.samsung.android.oneconnect:id/update_app_card_close_btn"
    private const val ONECONNECT_UPDATE_BUTTON_VIEW_ID = "com.samsung.android.oneconnect:id/update_button"

    internal data class RawVisibleNode(
        val label: String,
        val viewId: String?,
        val bounds: Rect
    )

    internal fun buildNodeTextSnapshot(nodes: List<AccessibilityNodeInfo>): String {
        val screenBounds = nodes.firstOrNull()?.let { node ->
            Rect().also { node.getBoundsInScreen(it) }
        }
        val screenTop = screenBounds?.top ?: 0
        val screenBottom = screenBounds?.bottom ?: Int.MAX_VALUE
        val screenHeight = (screenBottom - screenTop).coerceAtLeast(1)

        return nodes.joinToString(separator = "") { node ->
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            val isTopBar = A11yNodeUtils.isTopAppBar(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = bounds,
                screenTop = screenTop,
                screenHeight = screenHeight
            )
            val isBottomBar = A11yNodeUtils.isBottomNavigationBar(
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
            val isTopBar = A11yNodeUtils.isTopAppBar(
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                boundsInScreen = bounds,
                screenTop = screenTop,
                screenHeight = screenHeight
            )
            val isBottomBar = A11yNodeUtils.isBottomNavigationBar(
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

    internal fun buildSnapshotToken(
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

    internal fun pollForUpdatedRoot(
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

    internal fun logPostScrollRawVsTraversalSnapshot(
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

    internal fun collectRawVisibleNodes(root: AccessibilityNodeInfo): List<RawVisibleNode> {
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
        visibleHistorySignatures: Set<SnapshotVisibleHistorySignature>,
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

    internal fun isInVisitedHistory(
        label: String?,
        viewId: String?,
        bounds: Rect,
        visitedHistory: Set<String>,
        visitedHistorySignatures: Set<SnapshotVisibleHistorySignature>,
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
            val strictOneConnectUpdateAppAliasVisited = isStrictOneConnectUpdateAppAliasVisited(
                visitedViewId = signature.viewId,
                currentViewId = viewId,
                visitedBounds = signature.bounds,
                currentBounds = bounds
            )
            when {
                sameLabel && sameViewId -> true
                sameLabel && similarBounds -> true
                sameViewId && similarBounds && hasStrongNodeIdentity -> true
                strictOneConnectUpdateAppAliasVisited -> {
                    Log.d(
                        "A11Y_HELPER",
                        "[DEBUG][VISITED] update_app child skipped because representative already consumed"
                    )
                    true
                }
                else -> false
            }
        }
    }

    private fun isStrictOneConnectUpdateAppAliasVisited(
        visitedViewId: String?,
        currentViewId: String?,
        visitedBounds: Rect,
        currentBounds: Rect
    ): Boolean {
        val updateAppMemberViewIds = setOf(
            ONECONNECT_UPDATE_APP_TITLE_VIEW_ID,
            ONECONNECT_UPDATE_APP_TEXT_VIEW_ID,
            ONECONNECT_UPDATE_APP_CLOSE_BUTTON_VIEW_ID,
            ONECONNECT_UPDATE_BUTTON_VIEW_ID
        )
        val isCardAndMemberPair = (
            visitedViewId == ONECONNECT_UPDATE_APP_CARD_VIEW_ID &&
                currentViewId in updateAppMemberViewIds
            ) || (
            currentViewId == ONECONNECT_UPDATE_APP_CARD_VIEW_ID &&
                visitedViewId in updateAppMemberViewIds
            )
        if (!isCardAndMemberPair) return false
        if (visitedBounds.contains(currentBounds) || currentBounds.contains(visitedBounds)) return true
        val intersection = Rect()
        if (!intersection.setIntersect(visitedBounds, currentBounds)) return false
        val minArea = min(
            (visitedBounds.width() * visitedBounds.height()).coerceAtLeast(1),
            (currentBounds.width() * currentBounds.height()).coerceAtLeast(1)
        )
        val overlapRatio = intersection.width().toFloat() * intersection.height().toFloat() / max(1, minArea).toFloat()
        return overlapRatio >= 0.7f
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
            if (A11yNavigator.isNodePhysicallyOffScreen(bounds, screenTop, screenBottom)) {
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
    ): Set<SnapshotVisibleHistorySignature> {
        return nodes.mapNotNull { node ->
            val bounds = boundsOf(node)
            if (A11yNavigator.isNodePhysicallyOffScreen(bounds, screenTop, screenBottom)) {
                return@mapNotNull null
            }
            if (isTopAppBarNodeOf(node, bounds) || isBottomNavigationBarNodeOf(node, bounds)) {
                return@mapNotNull null
            }
            SnapshotVisibleHistorySignature(
                label = labelOf(node)?.trim()?.takeUnless { it.isEmpty() },
                viewId = viewIdOf(node)?.trim()?.takeUnless { it.isEmpty() },
                bounds = Rect(bounds),
                nodeIdentity = null
            )
        }.toSet()
    }

    internal fun hasPreScrollResolvedLabel(
        currentLabel: String,
        currentDescendantLabel: String,
        rawViewId: String?,
        bounds: Rect,
        visibleHistorySignatures: Set<SnapshotVisibleHistorySignature>
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
}
