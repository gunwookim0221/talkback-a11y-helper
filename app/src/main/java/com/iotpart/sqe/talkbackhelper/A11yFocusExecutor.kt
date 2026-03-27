package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import kotlin.math.abs

object A11yFocusExecutor {
    const val VERSION: String = "1.3.7"

    data class FocusExecutionResult(
        val success: Boolean,
        val attempts: Int,
        val lastFocusedBounds: Rect?
    )

    data class FocusVerificationResult(
        val resolved: Boolean,
        val snapBackDetected: Boolean,
        val actualFocusedBounds: Rect?
    )

    fun requestAccessibilityFocusWithRetry(
        target: AccessibilityNodeInfo,
        root: AccessibilityNodeInfo,
        maxAttempts: Int = 4,
        retryDelayMs: Long = 250L
    ): FocusExecutionResult {
        val targetBounds = Rect().also(target::getBoundsInScreen)
        var lastBounds: Rect? = null
        Log.i("A11Y_HELPER", "[FOCUS_EXEC] Start focus target=$targetBounds")

        repeat(maxAttempts) { attempt ->
            target.refresh()
            val actionResult = target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            Log.i("A11Y_HELPER", "[FOCUS_EXEC] Attempt ${attempt + 1}: performAction=$actionResult")

            Thread.sleep(retryDelayMs)
            val freshRoot = A11yStateStore.currentRoot ?: root
            val actualFocusNode = freshRoot.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
            lastBounds = actualFocusNode?.let { Rect().also(it::getBoundsInScreen) }
            Log.i("A11Y_HELPER", "[FOCUS_EXEC] Attempt ${attempt + 1} actual focus=$lastBounds")

            if (lastBounds != null && lastBounds == targetBounds) {
                Log.i("A11Y_HELPER", "[FOCUS_EXEC] Success! Focus matched.")
                return FocusExecutionResult(true, attempt + 1, lastBounds)
            }
        }
        Log.e("A11Y_HELPER", "[FOCUS_EXEC] Failed all attempts. Last actual focus: $lastBounds")
        return FocusExecutionResult(false, maxAttempts, lastBounds)
    }

    fun verifyFocusStabilizationAfterAction(
        root: AccessibilityNodeInfo,
        targetBounds: Rect,
        isTargetAccessibilityFocused: Boolean,
        settleDelayMs: Long = 100L
    ): FocusVerificationResult {
        Thread.sleep(settleDelayMs)
        val actualBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { Rect().also(it::getBoundsInScreen) }
        val snapBack = shouldTreatAsSnapBackAfterVerification(actualBounds, targetBounds, isTargetAccessibilityFocused)
        return FocusVerificationResult(
            resolved = !snapBack,
            snapBackDetected = snapBack,
            actualFocusedBounds = actualBounds
        )
    }

    internal fun shouldTreatAsSnapBackAfterVerification(
        actualFocusedBounds: Rect?,
        targetBounds: Rect,
        isTargetAccessibilityFocused: Boolean
    ): Boolean {
        if (isTargetAccessibilityFocused) return false
        if (actualFocusedBounds == null) return true
        return !isWithinSnapBackTolerance(targetBounds, actualFocusedBounds)
    }

    internal fun isTargetFocusResolved(
        isTargetAccessibilityFocused: Boolean,
        actualFocusedBounds: Rect?,
        targetBounds: Rect
    ): Boolean {
        if (isTargetAccessibilityFocused) return true
        if (actualFocusedBounds == null) return false
        return isWithinSnapBackTolerance(targetBounds, actualFocusedBounds)
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
        val isTopBar = A11yNodeUtils.isTopAppBar(target.className?.toString(), target.viewIdResourceName, targetBounds, screenTop, rootHeight)
        val isBottomBar = A11yNodeUtils.isBottomNavigationBar(target.className?.toString(), target.viewIdResourceName, targetBounds, rootBounds.bottom, rootHeight)
        if (!isTopBar && !isBottomBar && A11yNodeUtils.isNodePoorlyPositionedForFocus(targetBounds, screenTop, effectiveBottom)) {
            alignCandidateForReadableFocus(
                root = root,
                target = target,
                label = label,
                screenTop = screenTop,
                effectiveBottom = effectiveBottom,
                isTopBar = isTopBar,
                isBottomBar = isBottomBar,
                canScrollForwardHint = A11yNavigator.findScrollableForwardAncestorCandidate(target) != null || A11yNavigator.hasScrollableDownCandidate(root),
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
        if (A11yNavigator.shouldReuseExistingAccessibilityFocus(label, isScrollAction, currentFocusedBounds, targetBounds)) {
            val commitDecision = resolveFocusRetargetDecision(root, target, label, traversalListSnapshot, traversalIndex, isScrollAction, status)
            return commitFinalFocusCandidate(commitDecision, reason = "focus_reused_existing_target")
        }

        clearAccessibilityFocusAndRefresh(root)
        requestInputFocusBeforeAccessibilityFocus(target, label)

        // 2) Action: 포커스 실행 + 재시도
        val focusExecution = requestAccessibilityFocusWithRetry(
            target = target,
            root = root
        )
        if (!focusExecution.success) {
            A11yNavigator.syncLastRequestedFocusIndexToCurrentFocus(root, A11yTraversalAnalyzer.buildTalkBackLikeFocusNodes(root).map { it.node })
            return ActionResult(false, "failed", target)
        }

        // 3) Verify: 최종 focus 일치 + snap-back 체크
        val focusVerification = verifyFocusStabilizationAfterAction(
            root = root,
            targetBounds = targetBounds,
            isTargetAccessibilityFocused = target.isAccessibilityFocused
        )
        if (focusVerification.snapBackDetected) {
            Log.w("A11Y_HELPER", "[SMART_NEXT] requestFocusFlow snap_back target=${A11yNavigator.formatBoundsForLog(targetBounds)} actual=${A11yNavigator.formatBoundsForLog(focusVerification.actualFocusedBounds)}")
        }

        val commitDecision = resolveFocusRetargetDecision(root, target, label, traversalListSnapshot, traversalIndex, isScrollAction, status)
        if (!commitDecision.success) {
            A11yNavigator.syncLastRequestedFocusIndexToCurrentFocus(root, A11yTraversalAnalyzer.buildTalkBackLikeFocusNodes(root).map { it.node })
        }
        return commitFinalFocusCandidate(commitDecision, reason = "focus_confirmed_final")
    }

    internal fun resolveFocusRetargetDecision(
        root: AccessibilityNodeInfo,
        intendedTarget: AccessibilityNodeInfo,
        intendedLabel: String,
        traversalListSnapshot: List<AccessibilityNodeInfo>?,
        intendedIndex: Int,
        isScrollAction: Boolean,
        requestedStatus: String
    ): FocusRetargetDecision {
        val actualFocusedNode = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val actualCandidateIndex = if (actualFocusedNode != null && traversalListSnapshot != null) {
            A11yTraversalAnalyzer.findNodeIndexByIdentity(
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
        val identityMatched = actualFocusedNode != null && A11yNavigator.isSameNode(intendedTarget, actualFocusedNode)
        val rootBounds = Rect().also(root::getBoundsInScreen)
        val rootHeight = (rootBounds.bottom - rootBounds.top).coerceAtLeast(1)
        val actualBounds = actualFocusedNode?.let { Rect().also(it::getBoundsInScreen) }
        val actualIsInteractiveContent = actualFocusedNode != null && actualBounds != null &&
            A11yNodeUtils.isContentNode(
                node = actualFocusedNode,
                bounds = actualBounds,
                screenTop = rootBounds.top,
                screenBottom = rootBounds.bottom,
                screenHeight = rootHeight,
                mainScrollContainer = null
            )
        val isPostScrollValidCandidate = actualFocusedNode != null && actualBounds != null &&
            !A11yNodeUtils.isTopAppBar(
                className = actualFocusedNode.className?.toString(),
                viewIdResourceName = actualFocusedNode.viewIdResourceName,
                boundsInScreen = actualBounds,
                screenTop = rootBounds.top,
                screenHeight = rootHeight
            ) &&
            !A11yNodeUtils.isBottomNavigationBar(
                className = actualFocusedNode.className?.toString(),
                viewIdResourceName = actualFocusedNode.viewIdResourceName,
                boundsInScreen = actualBounds,
                screenBottom = rootBounds.bottom,
                screenHeight = rootHeight
            ) &&
            actualIsInteractiveContent
        val retarget = !identityMatched &&
            isScrollAction &&
            (actualCandidateIndex >= 0 || traversalListSnapshot.isNullOrEmpty()) &&
            (intendedIndex < 0 || actualCandidateIndex != intendedIndex) &&
            isPostScrollValidCandidate
        val shouldSuppressTopNoise = isScrollAction &&
            A11yHistoryManager.isWithinAuthoritativeFocusWindow() &&
            actualFocusedNode != null &&
            actualBounds != null &&
            A11yNavigator.isSuppressibleHeaderNoiseNode(
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
            !isPostScrollValidCandidate -> "actual_not_post_scroll_valid_candidate"
            else -> "actual_valid_post_scroll_candidate"
        }
        Log.i(
            "A11Y_HELPER",
            "[FOCUS_VERIFY] candidate_classification actualCandidateIndex=$actualCandidateIndex isTopChrome=${actualFocusedNode != null && actualBounds != null && A11yNodeUtils.isTopAppBar(actualFocusedNode.className?.toString(), actualFocusedNode.viewIdResourceName, actualBounds, rootBounds.top, rootHeight)} isPersistentHeader=${actualBounds != null && actualBounds.top <= rootBounds.top + (rootHeight / 4)} isWithinContentBounds=$actualIsInteractiveContent isPostScrollValidCandidate=$isPostScrollValidCandidate"
        )
        Log.i(
            "A11Y_HELPER",
            "[FOCUS_VERIFY] focus_retarget_eval intended=${A11yNavigator.formatBoundsForLog(Rect().also(intendedTarget::getBoundsInScreen))} actual=${A11yNavigator.formatBoundsForLog(actualBounds)} actualCandidateIndex=$actualCandidateIndex retarget=$retarget reason=$reason"
        )
        val finalTarget = when {
            shouldSuppressTopNoise -> intendedTarget
            retarget -> actualFocusedNode!!
            else -> intendedTarget
        }
        val finalLabel = A11yNavigator.resolvePrimaryLabel(finalTarget)
            ?: A11yTraversalAnalyzer.recoverDescendantLabel(finalTarget)
            ?: intendedLabel
        val source = when {
            shouldSuppressTopNoise -> "suppressed_top_noise"
            retarget -> "retargeted_actual"
            else -> "intended"
        }
        if (retarget) {
            Log.i(
                "A11Y_HELPER",
                "[FOCUS_VERIFY] retarget_accepted intended=${A11yNavigator.formatBoundsForLog(Rect().also(intendedTarget::getBoundsInScreen))} actual=${A11yNavigator.formatBoundsForLog(actualBounds)}"
            )
        }
        if (shouldSuppressTopNoise) {
            Log.i(
                "A11Y_HELPER",
                "[FOCUS_VERIFY] suppression_window_event type=FOCUS_UPDATE suppressed=true reason=top_resurfaced_header_during_authoritative_window label=${A11yNavigator.resolvePrimaryLabel(actualFocusedNode) ?: A11yTraversalAnalyzer.recoverDescendantLabel(actualFocusedNode) ?: "<no-label>"}"
            )
            Log.i(
                "A11Y_HELPER",
                "[FOCUS_VERIFY] suppression_window_event type=A11Y_ANNOUNCEMENT suppressed=true reason=top_resurfaced_header_during_authoritative_window label=${A11yNavigator.resolvePrimaryLabel(actualFocusedNode) ?: A11yTraversalAnalyzer.recoverDescendantLabel(actualFocusedNode) ?: "<no-label>"}"
            )
        }
        val success = when {
            shouldSuppressTopNoise -> true
            retarget -> true
            actualFocusedNode == null -> false
            identityMatched -> true
            else -> false
        }
        val commitStatus = if (success) requestedStatus else "failed"
        val finalReason = if (success) "success_basis=committed_candidate" else reason
        return FocusRetargetDecision(
            finalTarget = finalTarget,
            finalLabel = finalLabel,
            source = source,
            retargeted = retarget,
            commitStatus = commitStatus,
            success = success,
            reason = finalReason
        )
    }

    private fun commitFinalFocusCandidate(
        decision: FocusRetargetDecision,
        reason: String
    ): ActionResult {
        val activeTurnId = A11yHistoryManager.activeSmartNextTurnId
        if (A11yHistoryManager.hasCommittedFinalFocusForTurn(activeTurnId)) {
            Log.i(
                "A11Y_HELPER",
                "[FOCUS_VERIFY] final_focus_ignored_event reason=already_committed candidate=${decision.finalLabel.replace("\n", " ")} source=${decision.source}"
            )
            val lockedNode = A11yHistoryManager.authoritativeCommittedNode ?: decision.finalTarget
            return ActionResult(true, A11yHistoryManager.authoritativeCommittedStatus, lockedNode)
        }
        if (decision.success) {
            A11yNavigator.recordVisitedFocus(decision.finalTarget, decision.finalLabel, reason = reason)
            A11yHistoryManager.startAuthoritativeFocusSuppressionWindow(decision.finalTarget, decision.finalLabel, decision.commitStatus)
            A11yHistoryManager.markFinalCommitTurn(activeTurnId)
            Log.i("A11Y_HELPER", "[FOCUS_VERIFY] success_basis=committed_candidate")
        }
        Log.i("A11Y_HELPER", "[FOCUS_VERIFY] final_focus_commit candidate=${decision.finalLabel.replace("\n", " ")} source=${decision.source}")
        return ActionResult(decision.success, if (decision.success) decision.commitStatus else decision.reason, decision.finalTarget)
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
                val shown = target.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.id)
                if (shown) {
                    adjusted = true
                }
            } else {
                Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_SHOW_ON_SCREEN not supported on this API level")
            }

            val shouldTryContainerScroll =
                !shouldUseMinimalAdjustment &&
                canScrollForwardHint &&
                !adjusted &&
                (A11yNodeUtils.isNodeBottomClipped(currentBounds, effectiveBottom) || A11yNodeUtils.shouldLiftTrailingContentBeforeFocus(currentBounds, effectiveBottom))
            if (shouldTryContainerScroll) {
                val scrollableNode = A11yNavigator.findScrollableForwardAncestorCandidate(target) ?: findScrollableNode(root)
                if (scrollableNode != null) {
                    val scrolled = scrollableNode.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Pre-focus readable alignment scroll result=$scrolled label=$label")
                    adjusted = adjusted || scrolled
                }
            } else if (!canScrollForwardHint && !adjusted) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Last content cannot be top-aligned, using fully-visible fallback")
            }

            if (!adjusted) break
            Thread.sleep(400)
            target.refresh()
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
            if (A11yNodeUtils.isTopAppBar(classNameOf(candidate), viewIdOf(candidate), bounds, screenTop, screenHeight)) continue
            if (A11yNodeUtils.isBottomNavigationBar(classNameOf(candidate), viewIdOf(candidate), bounds, screenBottom, screenHeight)) continue
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
            if (A11yNodeUtils.isTopAppBar(classNameOf(candidate), viewIdOf(candidate), bounds, screenTop, screenHeight)) continue
            if (A11yNodeUtils.isBottomNavigationBar(classNameOf(candidate), viewIdOf(candidate), bounds, screenBottom, screenHeight)) continue
            return candidate
        }
        return null
    }

    internal fun findScrollableNode(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue += root
        var bestNode: AccessibilityNodeInfo? = null
        var maxScore = -1L

        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()

            for (i in 0 until node.childCount) {
                node.getChild(i)?.let { queue.addLast(it) }
            }

            if (node.isScrollable) {
                val className = node.className?.toString()?.lowercase() ?: ""
                if (className.contains("horizontal") || className.contains("viewpager")) {
                    continue
                }

                val bounds = android.graphics.Rect()
                node.getBoundsInScreen(bounds)
                val score = bounds.width().toLong() * bounds.height().toLong()

                if (score >= maxScore && score > 0) {
                    maxScore = score
                    bestNode = node
                }
            }
        }
        return bestNode
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

    private fun isWithinSnapBackTolerance(targetBounds: Rect, actualFocusedBounds: Rect, tolerancePx: Int = 10): Boolean {
        return abs(targetBounds.left - actualFocusedBounds.left) <= tolerancePx &&
            abs(targetBounds.top - actualFocusedBounds.top) <= tolerancePx &&
            abs(targetBounds.right - actualFocusedBounds.right) <= tolerancePx &&
            abs(targetBounds.bottom - actualFocusedBounds.bottom) <= tolerancePx
    }

    internal fun recordRequestedFocusAttempt(node: android.view.accessibility.AccessibilityNodeInfo, label: String, reason: String) {
        android.util.Log.i("A11Y_HELPER", "[FOCUS_ATTEMPT] reason=$reason label=$label")
    }
}
