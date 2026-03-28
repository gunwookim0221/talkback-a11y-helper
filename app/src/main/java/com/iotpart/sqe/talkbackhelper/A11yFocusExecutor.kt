package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import kotlin.math.abs

object A11yFocusExecutor {
    const val VERSION: String = "1.4.8"

    data class FocusExecutionResult(
        val success: Boolean,
        val attempts: Int,
        val lastFocusedBounds: Rect?
    )

    data class FocusVerificationResult(
        val resolved: Boolean,
        val snapBackDetected: Boolean,
        val actualFocusedBounds: Rect?,
        val hardFailureSignal: Boolean
    )

    internal data class PreFocusAlignmentResult(
        val adjusted: Boolean = false,
        val bottomClipped: Boolean = false,
        val reasonablyAligned: Boolean = false
    )

    fun requestAccessibilityFocusWithRetry(
        target: AccessibilityNodeInfo,
        root: AccessibilityNodeInfo,
        maxAttempts: Int = 3,
        pollIntervalMs: Long = 75L,
        verificationWindowMs: Long = 550L,
        retryDelayMs: Long = 120L
    ): FocusExecutionResult {
        val targetBounds = Rect().also { target.getBoundsInScreen(it) }
        val expectedPackageName = target.packageName?.toString()
        var lastBounds: Rect? = null

        Log.i(
            "A11Y_HELPER",
            "[FOCUS_EXEC] Start focus target=$targetBounds expectedPackage=$expectedPackageName pollIntervalMs=$pollIntervalMs verificationWindowMs=$verificationWindowMs maxAttempts=$maxAttempts"
        )

        repeat(maxAttempts) { attempt ->
            target.refresh()
            val actionResult = target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            Log.i("A11Y_HELPER", "[FOCUS_EXEC] Attempt ${attempt + 1}: performAction=$actionResult")

            val verification = pollForTargetFocusWithinWindow(
                root = root,
                targetBounds = targetBounds,
                intendedTarget = target,
                expectedPackageName = expectedPackageName,
                pollIntervalMs = pollIntervalMs,
                totalWindowMs = verificationWindowMs,
                phaseTag = "attempt_${attempt + 1}"
            )
            lastBounds = verification.lastFocusedBounds

            if (verification.matched) {
                Log.i("A11Y_HELPER", "[FOCUS_EXEC] Success! Focus reached target during polling window.")
                return FocusExecutionResult(true, attempt + 1, lastBounds)
            }

            if (attempt < maxAttempts - 1) {
                waitWithoutMainThreadSleep(retryDelayMs, "retry_delay")
            }
        }
        Log.e("A11Y_HELPER", "[FOCUS_EXEC] Failed all attempts. Last actual focus: $lastBounds")
        return FocusExecutionResult(false, maxAttempts, lastBounds)
    }

    fun verifyFocusStabilizationAfterAction(
        root: AccessibilityNodeInfo,
        intendedTarget: AccessibilityNodeInfo,
        targetBounds: Rect,
        expectedPackageName: String?,
        attemptMatched: Boolean,
        settleDelayMs: Long = 75L,
        settleWindowMs: Long = 450L
    ): FocusVerificationResult {
        val settleResult = pollForTargetFocusWithinWindow(
            root = root,
            targetBounds = targetBounds,
            intendedTarget = intendedTarget,
            expectedPackageName = expectedPackageName,
            pollIntervalMs = settleDelayMs,
            totalWindowMs = settleWindowMs,
            phaseTag = "post_action_settle"
        )
        val actualBounds = settleResult.lastFocusedBounds
        val snapBack = shouldTreatAsSnapBackAfterVerification(
            actualFocusedBounds = actualBounds,
            targetBounds = targetBounds,
            actualMatch = settleResult.matched
        )
        val hardFailureSignal = settleResult.externalPackageObserved && !settleResult.systemUiObserved
        val resolved = if (attemptMatched && !hardFailureSignal) true else !snapBack
        return FocusVerificationResult(
            resolved = resolved,
            snapBackDetected = snapBack,
            actualFocusedBounds = actualBounds,
            hardFailureSignal = hardFailureSignal
        )
    }

    internal fun shouldTreatAsSnapBackAfterVerification(
        actualFocusedBounds: Rect?,
        targetBounds: Rect,
        actualMatch: Boolean
    ): Boolean {
        if (actualMatch) return false
        if (actualFocusedBounds == null) return true
        return !isWithinSnapBackTolerance(targetBounds, actualFocusedBounds)
    }

    internal fun isTargetFocusResolved(
        actualFocusedNode: AccessibilityNodeInfo?,
        actualFocusedBounds: Rect?,
        targetBounds: Rect,
        expectedPackageName: String?,
        intendedTarget: AccessibilityNodeInfo? = null
    ): Boolean {
        if (actualFocusedNode == null || actualFocusedBounds == null) return false
        val actualPackageName = actualFocusedNode.packageName?.toString()
        if (expectedPackageName != null && actualPackageName != expectedPackageName) return false
        if (intendedTarget != null && isLogicallySameCandidate(intendedTarget, actualFocusedNode, actualFocusedBounds)) {
            return true
        }
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
        currentFocusIndexHint: Int = -1,
        aliasMembersByTraversalIndex: Map<Int, List<AccessibilityNodeInfo>> = emptyMap()
    ): ActionResult {
        val label = target.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: target.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
            ?: "<no-label>"
        val rootBounds = Rect().also(root::getBoundsInScreen)
        val rootHeight = (rootBounds.bottom - rootBounds.top).coerceAtLeast(1)
        val targetBounds = Rect().also(target::getBoundsInScreen)
        val expectedPackageName = target.packageName?.toString()

        // 1) Pre-Focus: 가시성 확보
        val isTopBar = A11yNodeUtils.isTopAppBar(target.className?.toString(), target.viewIdResourceName, targetBounds, screenTop, rootHeight)
        val isBottomBar = A11yNodeUtils.isBottomNavigationBar(target.className?.toString(), target.viewIdResourceName, targetBounds, rootBounds.bottom, rootHeight)
        val preFocusAlignment = if (!isTopBar && !isBottomBar && A11yNodeUtils.isNodePoorlyPositionedForFocus(targetBounds, screenTop, effectiveBottom)) {
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
        } else {
            PreFocusAlignmentResult()
        }
        if (status == "moved" && preFocusAlignment.adjusted) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] status_detail pre_focus_alignment_adjusted=true")
        }

        val currentFocusedBounds = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { Rect().also(it::getBoundsInScreen) }
        if (A11yNavigator.shouldReuseExistingAccessibilityFocus(label, isScrollAction, currentFocusedBounds, targetBounds)) {
            val commitDecision = resolveFocusRetargetDecision(root, target, label, traversalListSnapshot, traversalIndex, isScrollAction, status)
            return commitFinalFocusCandidate(
                decision = commitDecision,
                reason = "focus_reused_existing_target",
                aliasGroupMembers = aliasMembersByTraversalIndex[traversalIndex].orEmpty()
            )
        }

        clearAccessibilityFocusAndRefresh(root)
        requestInputFocusBeforeAccessibilityFocus(target, label)

        // 2) Action: 포커스 실행 + 재시도
        val focusExecution = requestAccessibilityFocusWithRetry(
            target = target,
            root = root
        )
        if (!focusExecution.success) {
            return ActionResult(false, "failed", target)
        }

        // 3) Verify: 최종 focus 일치 + snap-back 체크
        val focusVerification = verifyFocusStabilizationAfterAction(
            root = root,
            intendedTarget = target,
            targetBounds = targetBounds,
            expectedPackageName = expectedPackageName,
            attemptMatched = focusExecution.success
        )
        if (focusVerification.snapBackDetected) {
            Log.w("A11Y_HELPER", "[SMART_NEXT] requestFocusFlow snap_back target=${A11yNavigator.formatBoundsForLog(targetBounds)} actual=${A11yNavigator.formatBoundsForLog(focusVerification.actualFocusedBounds)}")
        }
        if (focusVerification.hardFailureSignal) {
            Log.w(
                "A11Y_HELPER",
                "[FOCUS_VERIFY] hard_failure_signal external_package_departure targetPackage=$expectedPackageName actual=${A11yNavigator.formatBoundsForLog(focusVerification.actualFocusedBounds)}"
            )
            return ActionResult(false, "failed_external_focus_departure", target)
        }

        val commitDecision = resolveFocusRetargetDecision(root, target, label, traversalListSnapshot, traversalIndex, isScrollAction, status)
        if (!commitDecision.success && focusExecution.success && focusVerification.resolved) {
            Log.i("A11Y_HELPER", "[FOCUS_VERIFY] keeping_prior_attempt_success despite settle mismatch")
            return commitFinalFocusCandidate(
                FocusRetargetDecision(
                    finalTarget = target,
                    finalLabel = label,
                    source = "attempt_confirmed",
                    retargeted = false,
                    commitStatus = status,
                    success = true,
                    reason = "success_basis=attempt_match_persisted"
                ),
                reason = "focus_confirmed_from_attempt",
                aliasGroupMembers = aliasMembersByTraversalIndex[traversalIndex].orEmpty()
            )
        }
        if (!commitDecision.success) return ActionResult(false, "failed_focus_rejected", target)
        return commitFinalFocusCandidate(
            decision = commitDecision,
            reason = "focus_confirmed_final",
            aliasGroupMembers = aliasMembersByTraversalIndex[traversalIndex].orEmpty()
        )
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
        val shouldSuppressTopNoise = A11yHistoryManager.isWithinAuthoritativeFocusWindow() &&
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
        reason: String,
        aliasGroupMembers: List<AccessibilityNodeInfo> = emptyList()
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
            A11yNavigator.recordVisitedAliasMembers(
                representativeNode = decision.finalTarget,
                representativeLabel = decision.finalLabel,
                aliasMembers = aliasGroupMembers,
                reason = reason
            )
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
        maxPreFocusAdjustments: Int = 2
    ): PreFocusAlignmentResult {
        if (isTopBar) return PreFocusAlignmentResult()
        if (isBottomBar) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Detected bottom navigation target -> skipping pre-focus alignment")
            return PreFocusAlignmentResult()
        }
        var currentBounds = Rect().also { target.getBoundsInScreen(it) }
        val poorlyPositioned = A11yNodeUtils.isNodePoorlyPositionedForFocus(currentBounds, screenTop, effectiveBottom)
        if (!poorlyPositioned) return PreFocusAlignmentResult()
        val bottomClippedCandidate = A11yNodeUtils.isNodeBottomClipped(currentBounds, effectiveBottom)

        if (bottomClippedCandidate) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Candidate is bottom-clipped, attempting pre-focus alignment")
        }

        val shouldUseMinimalAdjustment = !bottomClippedCandidate && shouldUseMinimalPreFocusAdjustment(
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
        var adjustedAny = false
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

            val requiresReadableAlignmentScroll =
                bottomClippedCandidate ||
                    !A11yNodeUtils.isNodeFullyVisible(currentBounds, screenTop, effectiveBottom) ||
                    A11yNodeUtils.isNodeBottomClipped(currentBounds, effectiveBottom) ||
                    A11yNodeUtils.shouldLiftTrailingContentBeforeFocus(currentBounds, effectiveBottom)
            val shouldTryContainerScroll = canScrollForwardHint && requiresReadableAlignmentScroll
            if (shouldTryContainerScroll) {
                val scrollableNode = A11yNavigator.findScrollableForwardAncestorCandidate(target) ?: findScrollableNode(root)
                if (scrollableNode != null) {
                    val scrolled = scrollableNode.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
                    Log.i("A11Y_HELPER", "[SMART_NEXT] Pre-focus readable alignment scroll result=$scrolled label=$label")
                    adjusted = adjusted || scrolled
                }
            } else if (!requiresReadableAlignmentScroll && !bottomClippedCandidate) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping pre-focus readable alignment scroll for regular visible candidate")
            } else if (!canScrollForwardHint && !adjusted) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Last content cannot be top-aligned, using fully-visible fallback")
            }

            adjustedAny = adjustedAny || adjusted
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
            if (isReasonablyAlignedForFocus(currentBounds, screenTop, effectiveBottom)) {
                Log.i("A11Y_HELPER", "[SMART_NEXT] Intended candidate reached readable alignment")
                return PreFocusAlignmentResult(adjusted = adjustedAny, bottomClipped = bottomClippedCandidate, reasonablyAligned = true)
            }
            adjustments += 1
        }

        val reasonablyAligned = isReasonablyAlignedForFocus(currentBounds, screenTop, effectiveBottom)
        if (reasonablyAligned) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Intended candidate reached readable alignment")
        } else if (A11yNodeUtils.isNodeFullyVisible(currentBounds, screenTop, effectiveBottom)) {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Intended candidate is fully visible but close to bottom edge")
        } else {
            Log.i("A11Y_HELPER", "[SMART_NEXT] Proceeding with best-effort focus on intended candidate")
        }
        return PreFocusAlignmentResult(adjusted = adjustedAny, bottomClipped = bottomClippedCandidate, reasonablyAligned = reasonablyAligned)
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
        val cleared = clearAccessibilityFocus(root)
        Log.i("A11Y_HELPER", "[SMART_NEXT] Skipping manual accessibility focus clear to prevent auto-snap: result=$cleared")
    }

    fun clearAccessibilityFocus(root: AccessibilityNodeInfo?): Boolean {
        // OS의 Auto-snap 버그 방지를 위해 수동 해제를 비활성화함
        return true
    }

    internal fun requestInputFocusBeforeAccessibilityFocus(target: AccessibilityNodeInfo, label: String): Boolean {
        val inputFocusResult = target.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        Log.i("A11Y_HELPER", "[SMART_NEXT] ACTION_FOCUS priming result=$inputFocusResult label=$label")
        return inputFocusResult
    }

    private data class FocusPollingResult(
        val matched: Boolean,
        val lastFocusedBounds: Rect?,
        val systemUiObserved: Boolean,
        val externalPackageObserved: Boolean
    )

    private fun pollForTargetFocusWithinWindow(
        root: AccessibilityNodeInfo,
        targetBounds: Rect,
        intendedTarget: AccessibilityNodeInfo?,
        expectedPackageName: String?,
        pollIntervalMs: Long,
        totalWindowMs: Long,
        phaseTag: String
    ): FocusPollingResult {
        val effectivePollInterval = pollIntervalMs.coerceIn(50L, 100L)
        val effectiveWindow = totalWindowMs.coerceIn(400L, 700L)
        val deadline = SystemClock.uptimeMillis() + effectiveWindow
        var lastBounds: Rect? = null
        var systemUiObserved = false
        var externalPackageObserved = false
        val isMainThread = Looper.myLooper() == Looper.getMainLooper()
        if (isMainThread) {
            Log.w("A11Y_HELPER", "[FOCUS_EXEC] Poll on main thread phase=$phaseTag executorVersion=$VERSION")
        }

        while (true) {
            root.refresh()
            val actualFocusNode = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
            val actualPackageName = actualFocusNode?.packageName?.toString()
            val packageAllowed = expectedPackageName == null || actualPackageName == expectedPackageName
            val systemUiPackage = actualPackageName == "com.android.systemui"
            if (!packageAllowed && systemUiPackage) {
                systemUiObserved = true
            }
            if (!packageAllowed && !systemUiPackage && actualFocusNode != null) {
                externalPackageObserved = true
            }

            val verificationNode = if (packageAllowed) actualFocusNode else null
            lastBounds = verificationNode?.let { Rect().also(it::getBoundsInScreen) }
            val latestTargetBounds = intendedTarget?.let { targetNode ->
                targetNode.refresh()
                Rect().also(targetNode::getBoundsInScreen)
            } ?: targetBounds
            val matched = isTargetFocusResolved(
                actualFocusedNode = verificationNode,
                actualFocusedBounds = lastBounds,
                targetBounds = latestTargetBounds,
                expectedPackageName = expectedPackageName,
                intendedTarget = intendedTarget
            )
            Log.i(
                "A11Y_HELPER",
                "[FOCUS_EXEC] Poll phase=$phaseTag expectedPackage=$expectedPackageName actualPackage=$actualPackageName packageAllowed=$packageAllowed target=${A11yNavigator.formatBoundsForLog(latestTargetBounds)} actual=${A11yNavigator.formatBoundsForLog(lastBounds)} matched=$matched"
            )
            if (matched) {
                return FocusPollingResult(
                    matched = true,
                    lastFocusedBounds = lastBounds,
                    systemUiObserved = systemUiObserved,
                    externalPackageObserved = externalPackageObserved
                )
            }

            if (isMainThread) break
            val now = SystemClock.uptimeMillis()
            if (now >= deadline) break
            waitWithoutMainThreadSleep(minOf(effectivePollInterval, deadline - now), "poll_$phaseTag")
        }

        Log.w(
            "A11Y_HELPER",
            "[FOCUS_EXEC] Poll timeout phase=$phaseTag target=${A11yNavigator.formatBoundsForLog(targetBounds)} lastActual=${A11yNavigator.formatBoundsForLog(lastBounds)}"
        )
        return FocusPollingResult(
            matched = false,
            lastFocusedBounds = lastBounds,
            systemUiObserved = systemUiObserved,
            externalPackageObserved = externalPackageObserved
        )
    }

    private fun waitWithoutMainThreadSleep(durationMs: Long, phaseTag: String): Boolean {
        val waitDuration = durationMs.coerceAtLeast(0L)
        if (waitDuration == 0L) return true
        val isMainThread = Looper.myLooper() == Looper.getMainLooper()
        if (!isMainThread) {
            Thread.sleep(waitDuration)
            return true
        }
        Log.w("A11Y_HELPER", "[FOCUS_EXEC] Skip blocking wait on main thread phase=$phaseTag durationMs=$waitDuration")
        return false
    }

    private fun isWithinSnapBackTolerance(targetBounds: Rect, actualFocusedBounds: Rect, tolerancePx: Int = 10): Boolean {
        return abs(targetBounds.left - actualFocusedBounds.left) <= tolerancePx &&
            abs(targetBounds.top - actualFocusedBounds.top) <= tolerancePx &&
            abs(targetBounds.right - actualFocusedBounds.right) <= tolerancePx &&
            abs(targetBounds.bottom - actualFocusedBounds.bottom) <= tolerancePx
    }

    private fun isReasonablyAlignedForFocus(bounds: Rect, screenTop: Int, effectiveBottom: Int): Boolean {
        if (!A11yNodeUtils.isNodeFullyVisible(bounds, screenTop, effectiveBottom)) return false
        val viewportHeight = (effectiveBottom - screenTop).coerceAtLeast(1)
        val readableBottom = effectiveBottom - (viewportHeight * 0.12f).toInt()
        return bounds.bottom <= readableBottom
    }

    private fun isLogicallySameCandidate(
        intendedTarget: AccessibilityNodeInfo,
        actualFocusedNode: AccessibilityNodeInfo,
        actualBounds: Rect
    ): Boolean {
        if (A11yNavigator.isSameNode(intendedTarget, actualFocusedNode)) return true
        val intendedBounds = Rect().also(intendedTarget::getBoundsInScreen)
        val samePackage = intendedTarget.packageName?.toString() == actualFocusedNode.packageName?.toString()
        val sameWindow = intendedTarget.windowId == actualFocusedNode.windowId
        val sameClass = intendedTarget.className?.toString() == actualFocusedNode.className?.toString()
        if (!samePackage || !sameWindow || !sameClass) return false

        val intendedLabel = normalizedNodeLabel(intendedTarget)
        val actualLabel = normalizedNodeLabel(actualFocusedNode)
        val sameLabel = intendedLabel.isNotEmpty() && intendedLabel == actualLabel
        val sameViewId = intendedTarget.viewIdResourceName?.takeIf { it.isNotBlank() } ==
            actualFocusedNode.viewIdResourceName?.takeIf { it.isNotBlank() }
        val sameText = normalizeText(intendedTarget.text?.toString()) == normalizeText(actualFocusedNode.text?.toString())
        val sameDescription = normalizeText(intendedTarget.contentDescription?.toString()) == normalizeText(actualFocusedNode.contentDescription?.toString())
        val sizeStable = abs(intendedBounds.width() - actualBounds.width()) <= 24 && abs(intendedBounds.height() - actualBounds.height()) <= 24
        val horizontalStable = abs(intendedBounds.left - actualBounds.left) <= 18 && abs(intendedBounds.right - actualBounds.right) <= 18

        return sizeStable && horizontalStable && (sameViewId || sameLabel || (sameText && sameDescription))
    }

    private fun normalizedNodeLabel(node: AccessibilityNodeInfo): String {
        val label = A11yNavigator.resolvePrimaryLabel(node) ?: A11yTraversalAnalyzer.recoverDescendantLabel(node)
        return normalizeText(label)
    }

    private fun normalizeText(value: String?): String = value
        ?.trim()
        ?.replace("\\s+".toRegex(), " ")
        ?.lowercase()
        .orEmpty()

    internal fun recordRequestedFocusAttempt(node: android.view.accessibility.AccessibilityNodeInfo, label: String, reason: String) {
        android.util.Log.i("A11Y_HELPER", "[FOCUS_ATTEMPT] reason=$reason label=$label")
    }
}
