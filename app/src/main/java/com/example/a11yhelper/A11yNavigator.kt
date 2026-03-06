package com.example.a11yhelper

import android.content.res.Resources
import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import kotlin.math.abs
import kotlin.math.roundToInt

object A11yNavigator {
    private val ROW_THRESHOLD_PX: Int = dpToPx(12f).coerceAtLeast(1)

    data class NavOutcome(
        val success: Boolean,
        val reason: String,
        val fromIndex: Int,
        val targetIndex: Int,
        val targetNode: AccessibilityNodeInfo?
    )

    fun collectNavigableNodes(
        root: AccessibilityNodeInfo?,
        foregroundPackageName: String? = root?.packageName?.toString()
    ): List<AccessibilityNodeInfo> {
        if (root == null) return emptyList()

        val candidates = mutableListOf<AccessibilityNodeInfo>()
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.add(root)

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            if (isNodeCandidate(node)) {
                candidates.add(node)
            }
            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }

        return candidates
            .map { node ->
                val bounds = Rect().also { node.getBoundsInScreen(it) }
                NodeSortMeta(
                    node = node,
                    bounds = bounds,
                    isEmptyBounds = bounds.width() <= 0 || bounds.height() <= 0,
                    packagePriority = packagePriority(node, foregroundPackageName)
                )
            }
            .sortedWith(NODE_SPATIAL_COMPARATOR)
            .map { it.node }
    }

    fun navigate(root: AccessibilityNodeInfo?, direction: Int): NavOutcome {
        val nodes = collectNavigableNodes(root)
        if (nodes.isEmpty()) {
            return NavOutcome(false, "No navigable nodes", -1, -1, null)
        }
        val currentIdx = nodes.indexOfFirst { it.isAccessibilityFocused || it.isFocused }
        val anchor = if (currentIdx >= 0) currentIdx else if (direction > 0) -1 else nodes.size
        val targetIdx = anchor + direction

        if (targetIdx !in nodes.indices) {
            return NavOutcome(
                success = false,
                reason = "Reached boundary (nodes=${nodes.size}, current=$currentIdx, direction=$direction)",
                fromIndex = currentIdx,
                targetIndex = targetIdx,
                targetNode = null
            )
        }

        val target = nodes[targetIdx]
        val actionOk = target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
        val reason = if (actionOk) "ACTION_ACCESSIBILITY_FOCUS success" else "ACTION_ACCESSIBILITY_FOCUS failed"

        return NavOutcome(
            success = actionOk,
            reason = reason,
            fromIndex = currentIdx,
            targetIndex = targetIdx,
            targetNode = target
        )
    }

    private fun isNodeCandidate(node: AccessibilityNodeInfo): Boolean {
        return node.isVisibleToUser && (node.isFocusable || node.isClickable || !node.text.isNullOrBlank() || !node.contentDescription.isNullOrBlank())
    }

    private fun packagePriority(node: AccessibilityNodeInfo, foregroundPackageName: String?): Int {
        if (foregroundPackageName.isNullOrBlank()) return 0
        val nodePackage = node.packageName?.toString()
        return if (nodePackage == foregroundPackageName) 0 else 1
    }

    private fun rowKey(top: Int): Int = top / ROW_THRESHOLD_PX

    private val NODE_SPATIAL_COMPARATOR = Comparator<NodeSortMeta> { a, b ->
        compareValuesBy(
            a,
            b,
            { it.packagePriority },
            { if (it.isEmptyBounds) 1 else 0 },
            { rowKey(it.bounds.top) },
            { it.bounds.left },
            { it.bounds.top }
        ).takeIf { it != 0 }
            ?: run {
                if (abs(a.bounds.top - b.bounds.top) <= ROW_THRESHOLD_PX) {
                    compareValuesBy(a, b, { it.bounds.left }, { it.bounds.top })
                } else {
                    a.bounds.top.compareTo(b.bounds.top)
                }
            }
    }

    private fun dpToPx(dp: Float): Int {
        val density = Resources.getSystem().displayMetrics.density
        return (dp * density).roundToInt()
    }

    private data class NodeSortMeta(
        val node: AccessibilityNodeInfo,
        val bounds: Rect,
        val isEmptyBounds: Boolean,
        val packagePriority: Int
    )
}
