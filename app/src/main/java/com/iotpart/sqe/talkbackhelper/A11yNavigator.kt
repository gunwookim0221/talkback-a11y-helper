package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject

object A11yNavigator {
    const val NAVIGATOR_ALGORITHM_VERSION: String = "2.8.9"

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
            Log.w("A11Y_HELPER", "[SMART_NEXT] Current node matching failed. Dumping traversal identity candidates for diagnosis.")
            traversalList.forEachIndexed { index, candidate ->
                Log.w(
                    "A11Y_HELPER",
                    "[SMART_NEXT] [MATCH_DEBUG] #$index id=${candidate.viewIdResourceName} text=${candidate.text} desc=${candidate.contentDescription}"
                )
            }

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
        Log.i("A11Y_HELPER", "[SMART_NEXT] effectiveBottom=$effectiveBottom, screenBottom=$screenBottom")

        fun findAndFocusFirstContent(
            traversalList: List<AccessibilityNodeInfo>,
            screenTop: Int,
            screenBottom: Int,
            effectiveBottom: Int,
            screenHeight: Int,
            statusName: String,
            isScrollAction: Boolean = false,
            excludeDesc: String? = null,
            startIndex: Int = 0,
            visibleHistory: Set<String> = emptySet(),
            allowLooping: Boolean = true
        ): TargetActionOutcome {
            val excludedIndex = findIndexByDescription(
                nodes = traversalList,
                descriptionOf = {
                    it.contentDescription?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                        ?: it.text?.toString()?.trim().takeUnless { text -> text.isNullOrEmpty() }
                },
                excludeDesc = excludeDesc
            )

            val traversalStartIndex = if (isScrollAction) {
                startIndex.coerceAtLeast(0)
            } else {
                if (excludedIndex != -1) excludedIndex + 1 else startIndex.coerceAtLeast(0)
            }
            var skippedExcludedNode = false
            var focusedAny = false
            var focusedOutcome: TargetActionOutcome? = null

            if (excludedIndex != -1) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Excluded node found at index=$excludedIndex. Starting traversal from index=$traversalStartIndex")
            } else if (!excludeDesc.isNullOrBlank()) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Excluded node not found. Starting traversal from beginning with top-area guard")
            }

            for (index in traversalStartIndex until traversalList.size) {
                val node = traversalList[index]
                val bounds = Rect().also { node.getBoundsInScreen(it) }
                val label = node.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: node.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                    ?: "<no-label>"
                val inHistory = visibleHistory.contains(label)
                Log.i(
                    "A11Y_HELPER",
                    "[SMART_DEBUG] Index:$index, Label:${label.replace("\n", " ")}, Y_Bottom:${bounds.bottom}, Eff_Bottom:$effectiveBottom, InHistory:$inHistory"
                )
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
                if (shouldSkipHistoryNodeAfterScroll(isScrollAction, inHistory, isTopBar, isBottomBar)) {
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping history node after scroll: $label")
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
                    focusedOutcome = performFocusWithVisibilityCheck(
                        root = root,
                        target = node,
                        screenTop = screenTop,
                        effectiveBottom = effectiveBottom,
                        status = statusName,
                        isScrollAction = isScrollAction
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

            if (shouldTriggerLoopFallback(focusedAny, isScrollAction, excludeDesc)) {
                if (!allowLooping) {
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Loop fallback blocked because allowLooping=false")
                    return TargetActionOutcome(false, "failed_no_new_content")
                }
                Log.i("A11Y_HELPER", "[SMART_NEXT] No content after scroll. Looping to first content.")
                Log.i("A11Y_HELPER", "[SMART_NEXT] Fallback loop triggered - resetting filters")
                return findAndFocusFirstContent(
                    traversalList = traversalList,
                    screenTop = screenTop,
                    screenBottom = screenBottom,
                    effectiveBottom = effectiveBottom,
                    screenHeight = screenHeight,
                    statusName = "looped",
                    isScrollAction = false,
                    excludeDesc = null,
                    startIndex = 0,
                    visibleHistory = emptySet()
                )
            }

            Log.e("A11Y_HELPER", "[SMART_NEXT] Failed to focus any valid content node (status=failed)")
            return TargetActionOutcome(false, "failed")
        }

        fun focusOrSkip(target: AccessibilityNodeInfo, status: String): TargetActionOutcome {
            return performFocusWithVisibilityCheck(
                root = root,
                target = target,
                screenTop = screenTop,
                effectiveBottom = effectiveBottom,
                status = status,
                isScrollAction = false
            )
        }

        val scrollableNode = findScrollableForwardAncestorCandidate(resolvedCurrent)
            ?: findScrollableForwardCandidate(root)

        if (nextIndex !in traversalList.indices || currentIndex == traversalList.lastIndex) {
            if (scrollableNode != null) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Reached last node or next unavailable, but scrollable container exists -> attempting scroll first")
                val lastDesc = resolvedCurrent?.contentDescription?.toString()
                val scrolled = scrollableNode.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
                Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_SCROLL_FORWARD result=$scrolled")
                if (!scrolled) {
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
                    traversalList = refreshedList,
                    screenTop = refreshedRect.top,
                    screenBottom = refreshedScreenBottom,
                    effectiveBottom = refreshedEffectiveBottom,
                    screenHeight = refreshedScreenHeight,
                    statusName = "scrolled",
                    isScrollAction = true,
                    excludeDesc = lastDesc,
                    startIndex = 0,
                    visibleHistory = visibleHistory
                )
            }

            Log.i("A11Y_HELPER", "[SMART_NEXT] Reached last node or next node unavailable -> looping to first content")
            return findAndFocusFirstContent(
                traversalList = traversalList,
                screenTop = screenTop,
                screenBottom = screenBottom,
                effectiveBottom = effectiveBottom,
                screenHeight = screenHeight,
                statusName = "looped"
            )
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

        if (nextIsBottomBar && scrollableNode != null) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Scrollable container found for smart scroll.")
            Log.i("A11Y_HELPER", "[SMART_NEXT] Next node is bottom bar and scroll target exists -> attempting scroll")
            val lastDesc = resolvedCurrent?.contentDescription?.toString()
            val scrolled = scrollableNode.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
            Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_SCROLL_FORWARD result=$scrolled")
            if (!scrolled) {
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

            val service = A11yHelperService.instance
            val oldSnapshot = buildNodeTextSnapshot(traversalList)
            val refreshedRoot = pollForUpdatedRoot(
                service = service,
                oldSnapshot = oldSnapshot,
                fallbackRoot = root
            )
            val refreshedTraversal = refreshedRoot?.let { buildFocusableTraversalList(it) }.orEmpty()
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
                traversalList = refreshedTraversal,
                screenTop = refreshedTop,
                screenBottom = refreshedBottom,
                effectiveBottom = refreshedEffectiveBottom,
                screenHeight = refreshedHeight,
                statusName = "scrolled",
                isScrollAction = true,
                excludeDesc = lastDesc,
                startIndex = 0,
                visibleHistory = visibleHistory,
                allowLooping = false
            )
            if (outcome.success) {
                return outcome
            }
            Log.i("A11Y_HELPER", "[SMART_NEXT] No new content after scroll. Moving focus to bottom bar target.")
            val bottomBarOutcome = focusOrSkip(nextNode, "moved_to_bottom_bar")
            return if (bottomBarOutcome.success) {
                TargetActionOutcome(true, "moved_to_bottom_bar", nextNode)
            } else {
                bottomBarOutcome
            }
        }

        Log.i("A11Y_HELPER", "[SMART_NEXT] Performing regular next navigation")
        return focusOrSkip(nextNode, "moved")
    }


    internal fun performFocusWithVisibilityCheck(
        root: AccessibilityNodeInfo,
        target: AccessibilityNodeInfo,
        screenTop: Int,
        effectiveBottom: Int,
        status: String,
        isScrollAction: Boolean
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

        fun requestVisibilityAdjustment(bounds: Rect) {
            val shouldAdjustVisibility = shouldTriggerShowOnScreen(
                bounds = bounds,
                effectiveBottom = effectiveBottom,
                screenTop = screenTop,
                isScrollAction = isScrollAction,
                isTopBar = isTopBar,
                isBottomBar = isBottomBar
            )
            if (!shouldAdjustVisibility) return

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Visibility adjustment triggered for: $label (Y:${bounds.top})")
                target.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.id)
            } else {
                Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_SHOW_ON_SCREEN not supported on this API level")
            }
        }

        requestVisibilityAdjustment(Rect().also { target.getBoundsInScreen(it) })

        var focused = target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
        if (!focused) {
            focused = target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
        }

        if (!focused) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_ACCESSIBILITY_FOCUS result=false (status=$status)")
            return TargetActionOutcome(false, "failed", target)
        }

        val focusedBounds = Rect().also { target.getBoundsInScreen(it) }
        requestVisibilityAdjustment(focusedBounds)
        Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_ACCESSIBILITY_FOCUS result=true (status=$status)")
        Log.i("A11Y_HELPER", "[SMART_NEXT] Focused top-most content at Y=${focusedBounds.top}")
        return TargetActionOutcome(true, status, target)
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
        isAccessibilityFocused: Boolean,
        isScrollAction: Boolean
    ): Boolean {
        if (isScrollAction && isAccessibilityFocused) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Reusing TalkBack auto-focused node after scroll")
        }
        return isAccessibilityFocused
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

    internal fun buildNodeTextSnapshot(nodes: List<AccessibilityNodeInfo>): String {
        return nodes.joinToString(separator = "") { node ->
            listOf(
                node.text?.toString()?.trim().orEmpty(),
                node.contentDescription?.toString()?.trim().orEmpty(),
                node.viewIdResourceName?.trim().orEmpty()
            ).joinToString(separator = "|")
        }
    }

    internal fun buildNodeTextSnapshot(root: AccessibilityNodeInfo): String {
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        val tokens = mutableListOf<String>()
        stack.add(root)

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            tokens += listOf(
                node.text?.toString()?.trim().orEmpty(),
                node.contentDescription?.toString()?.trim().orEmpty(),
                node.viewIdResourceName?.trim().orEmpty()
            ).joinToString(separator = "|")

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
                Log.i("A11Y_HELPER", "[SMART_NEXT] Tree updated successfully at loop $i")
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

    internal fun shouldSkipHistoryNodeAfterScroll(
        isScrollAction: Boolean,
        inHistory: Boolean,
        isTopBar: Boolean,
        isBottomBar: Boolean
    ): Boolean = isScrollAction && inHistory && !isTopBar && !isBottomBar

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
        contentDescriptionOf: (T) -> String?,
        boundsOf: (T) -> Rect
    ): Int {
        val targetId = idOf(target)
        val targetText = textOf(target)
        val targetContentDescription = contentDescriptionOf(target)
        val targetBounds = boundsOf(target)

        val strictMatchIndex = nodes.indexOfFirst { candidate ->
            val candidateBounds = boundsOf(candidate)
            idOf(candidate) == targetId &&
                textOf(candidate) == targetText &&
                contentDescriptionOf(candidate) == targetContentDescription &&
                candidateBounds.left == targetBounds.left &&
                candidateBounds.top == targetBounds.top &&
                candidateBounds.right == targetBounds.right &&
                candidateBounds.bottom == targetBounds.bottom
        }

        if (strictMatchIndex != -1) {
            return strictMatchIndex
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
        val strictMatch = aId == bId &&
            aText == bText &&
            aContentDescription == bContentDescription &&
            aBounds.left == bBounds.left &&
            aBounds.top == bBounds.top &&
            aBounds.right == bBounds.right &&
            aBounds.bottom == bBounds.bottom

        if (strictMatch) {
            return true
        }

        return aId == bId && aText == bText && aContentDescription == bContentDescription
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
