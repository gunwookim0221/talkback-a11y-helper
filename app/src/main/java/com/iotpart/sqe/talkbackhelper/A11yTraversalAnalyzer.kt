package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo

object A11yTraversalAnalyzer {
    const val VERSION: String = "1.2.0"
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
        logSettingsCandidateStatus(root, filteredNodes)
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

        val nextContainer = if (container) node else containerAncestor
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

    internal fun selectPostScrollCandidate(candidateIndex: Int): CandidateSelectionResult {
        return if (candidateIndex >= 0) {
            CandidateSelectionResult(index = candidateIndex, accepted = true, reasonCode = "accepted")
        } else {
            CandidateSelectionResult(index = -1, accepted = false, reasonCode = "missing")
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

    private fun recoverLabelFromDescendantTexts(textCandidates: List<String>): String? {
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

    private fun shouldAllowRecoveredDescendantLabelForTraversal(textCandidates: List<String>): Boolean {
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
}
