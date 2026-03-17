package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject

object A11yNavigator {
    const val NAVIGATOR_ALGORITHM_VERSION: String = "2.6.1"

    data class TargetActionOutcome(
        val success: Boolean,
        val reason: String,
        val target: AccessibilityNodeInfo? = null
    )

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



    fun performSmartNext(root: AccessibilityNodeInfo?, currentNode: AccessibilityNodeInfo?): TargetActionOutcome {
        if (root == null) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] rootInActiveWindow is null.")
            return TargetActionOutcome(false, "Root node is null")
        }

        val traversalList = buildFocusableTraversalList(root)
        Log.i("A11Y_HELPER", "[SMART_NEXT] Nodes count=${traversalList.size}")
        traversalList.forEachIndexed { index, node ->
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            val label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: "<no-label>"
            Log.i("A11Y_HELPER", "[SMART_NEXT] #$index: ${label.replace("\n", " ")} (Top: ${bounds.top})")
        }
        if (traversalList.isEmpty()) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Traversal list is empty, failing.")
            return TargetActionOutcome(false, "Traversal list is empty")
        }

        val resolvedCurrent = currentNode?.let {
            resolveToClickableAncestor(
                node = it,
                parentOf = { node -> node.parent },
                isClickable = { node -> node.isClickable }
            )
        }

        val currentIndex = resolvedCurrent?.let { resolved ->
            traversalList.indexOfFirst { candidate ->
                isSameNode(candidate, resolved)
            }
        } ?: -1

        val fallbackIndex = if (currentIndex == -1) {
            val focusedNode = currentNode ?: resolvedCurrent
            if (focusedNode == null) {
                -1
            } else {
                findClosestNodeBelowCenter(
                    nodes = traversalList,
                    reference = focusedNode,
                    boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } }
                )
            }
        } else {
            -1
        }

        val nextIndex = if (currentIndex == -1 && fallbackIndex != -1) fallbackIndex else currentIndex + 1
        Log.i("A11Y_HELPER", "[SMART_NEXT] currentIndex=$currentIndex, nextIndex=$nextIndex")

        if (currentIndex == -1 && fallbackIndex != -1) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Current node matching failed. Using fallback nextIndex based on vertical proximity.")
        }

        val screenRect = Rect().also { root.getBoundsInScreen(it) }
        val screenTop = screenRect.top
        val screenBottom = screenRect.bottom
        val screenHeight = (screenBottom - screenTop).coerceAtLeast(1)

        fun findAndFocusFirstContent(
            traversalList: List<AccessibilityNodeInfo>,
            screenTop: Int,
            screenBottom: Int,
            screenHeight: Int,
            statusName: String,
            isScrollAction: Boolean = false,
            excludeDesc: String? = null
        ): TargetActionOutcome {
            var skippedExcludedNode = false

            for (node in traversalList) {
                val bounds = Rect().also { node.getBoundsInScreen(it) }
                if (!skippedExcludedNode &&
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

                    if (shouldReuseExistingAccessibilityFocus(node.isAccessibilityFocused, isScrollAction)) {
                        Log.i("A11Y_HELPER", "[SMART_NEXT] Node is already focused (status=$statusName)")
                        return TargetActionOutcome(true, statusName, node)
                    }

                    var focused = node.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
                    if (!focused) {
                        Thread.sleep(100)
                        focused = node.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
                    }
                    if (focused) {
                        Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_ACCESSIBILITY_FOCUS succeeded (status=$statusName)")
                        return TargetActionOutcome(true, statusName, node)
                    } else {
                        Log.w("A11Y_HELPER", "[SMART_NEXT] Node focus denied, trying next candidate...")
                    }
                }
            }

            Log.e("A11Y_HELPER", "[SMART_NEXT] Failed to focus any valid content node (status=failed)")
            return TargetActionOutcome(false, "failed")
        }

        fun focusOrSkip(target: AccessibilityNodeInfo, status: String): TargetActionOutcome {
            if (target.isAccessibilityFocused) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Target already has accessibility focus, skipping focus action (status=$status)")
                return TargetActionOutcome(true, status, target)
            }
            var focused = target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            if (!focused) {
                Thread.sleep(100)
                focused = target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            }
            Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_ACCESSIBILITY_FOCUS result=$focused (status=$status)")
            return TargetActionOutcome(focused, if (focused) status else "failed", target)
        }

        if (nextIndex !in traversalList.indices || currentIndex == traversalList.lastIndex) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Reached last node or next node unavailable -> looping to first content")
            return findAndFocusFirstContent(traversalList, screenTop, screenBottom, screenHeight, "looped")
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

        val scrollableNode = findScrollableForwardAncestorCandidate(resolvedCurrent)
            ?: findScrollableForwardCandidate(root)
        if (nextIsBottomBar && scrollableNode != null) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Scrollable container found for smart scroll.")
            Log.i("A11Y_HELPER", "[SMART_NEXT] Next node is bottom bar and scroll target exists -> attempting scroll")
            val lastDesc = resolvedCurrent?.contentDescription?.toString()
            val scrolled = scrollableNode.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
            Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_SCROLL_FORWARD result=$scrolled")
            if (!scrolled) {
                return TargetActionOutcome(false, "failed")
            }

            currentNode?.let {
                val cleared = it.performAction(AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
                Log.i("A11Y_HELPER", "[SMART_NEXT] Current focus clear result after scroll=$cleared")
            }

            Thread.sleep(1500)

            val tempRoot = A11yHelperService.instance?.rootInActiveWindow
            tempRoot?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { oldFocus ->
                oldFocus.performAction(AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
                Log.i("A11Y_HELPER", "[SMART_NEXT] Cleared stale accessibility focus lock after scroll")
                Thread.sleep(150)
            }

            val refreshedRoot = A11yHelperService.instance?.rootInActiveWindow
            val refreshedTraversal = refreshedRoot?.let { buildFocusableTraversalList(it) }.orEmpty()
            val refreshedRect = Rect().also { (refreshedRoot ?: root).getBoundsInScreen(it) }
            val refreshedTop = refreshedRect.top
            val refreshedBottom = refreshedRect.bottom
            val refreshedHeight = (refreshedBottom - refreshedTop).coerceAtLeast(1)
            return findAndFocusFirstContent(
                traversalList = refreshedTraversal,
                screenTop = refreshedTop,
                screenBottom = refreshedBottom,
                screenHeight = refreshedHeight,
                statusName = "scrolled",
                isScrollAction = true,
                excludeDesc = lastDesc
            )
        }

        Log.i("A11Y_HELPER", "[SMART_NEXT] Performing regular next navigation")
        return focusOrSkip(nextNode, "moved")
    }

    internal fun shouldReuseExistingAccessibilityFocus(
        isAccessibilityFocused: Boolean,
        isScrollAction: Boolean
    ): Boolean {
        if (isScrollAction && isAccessibilityFocused) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Reusing TalkBack auto-focused node after scroll")
        }
        return isAccessibilityFocused
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
                textOf = { node -> node.text?.toString() ?: node.contentDescription?.toString() },
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
        val contentDescription: String?
    )

    private fun buildTalkBackLikeFocusNodes(root: AccessibilityNodeInfo): List<FocusedNode> {
        val focusNodes = mutableListOf<FocusedNode>()
        collectFocusableNodes(node = root, containerAncestor = null, sink = focusNodes)

        return focusNodes
            .filterNot { shouldExcludeAsEmptyShell(it) }
            .sortedWith(spatialComparator())
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
            sink += FocusedNode(node, mergedText, mergedDescription)
        } else if (containerAncestor == null && hasAnyText(node)) {
            sink += FocusedNode(
                node = node,
                text = node.text?.toString(),
                contentDescription = node.contentDescription?.toString()
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
        return node.isClickable || screenReaderFocusable
    }

    private fun hasAnyText(node: AccessibilityNodeInfo): Boolean {
        val text = node.text?.toString()?.trim().orEmpty()
        val description = node.contentDescription?.toString()?.trim().orEmpty()
        return text.isNotEmpty() || description.isNotEmpty()
    }

    private fun shouldExcludeAsEmptyShell(node: FocusedNode): Boolean {
        val current = node.node
        return shouldExcludeAsEmptyShell(
            mergedText = node.text,
            mergedContentDescription = node.contentDescription,
            clickable = current.isClickable,
            childCount = current.childCount
        )
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
        boundsOf: (T) -> Rect
    ): Int {
        val targetId = idOf(target)
        val targetText = textOf(target)
        val targetBounds = boundsOf(target)

        return nodes.indexOfFirst { candidate ->
            val candidateBounds = boundsOf(candidate)
            idOf(candidate) == targetId &&
                textOf(candidate) == targetText &&
                candidateBounds.left == targetBounds.left &&
                candidateBounds.top == targetBounds.top &&
                candidateBounds.right == targetBounds.right &&
                candidateBounds.bottom == targetBounds.bottom
        }
    }

    internal fun isSameNode(a: AccessibilityNodeInfo, b: AccessibilityNodeInfo): Boolean {
        val aBounds = Rect().also { a.getBoundsInScreen(it) }
        val bBounds = Rect().also { b.getBoundsInScreen(it) }

        return a.viewIdResourceName == b.viewIdResourceName &&
            a.text?.toString() == b.text?.toString() &&
            a.contentDescription?.toString() == b.contentDescription?.toString() &&
            aBounds.left == bBounds.left &&
            aBounds.top == bBounds.top &&
            aBounds.right == bBounds.right &&
            aBounds.bottom == bBounds.bottom
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
            normalizedViewId.contains("header_bar")
        if (matchesViewId) return true

        return false
    }

    internal fun isBottomNavigationBarNode(
        className: String?,
        viewIdResourceName: String?,
        boundsInScreen: Rect,
        screenBottom: Int,
        screenHeight: Int
    ): Boolean {
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
            normalizedViewId.contains("menu_") ||
            normalizedViewId.contains("tab_") ||
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
