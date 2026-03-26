package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo

object A11yHistoryManager {
    const val VERSION: String = "1.2.0"
    private const val RETARGET_SUPPRESSION_WINDOW_MS: Long = 400L

    data class VisibleHistorySignature(
        val label: String?,
        val viewId: String?,
        val bounds: Rect,
        val nodeIdentity: String?
    )

    data class PreScrollAnchor(
        val viewIdResourceName: String?,
        val mergedLabel: String?,
        val talkbackLabel: String?,
        val text: String?,
        val contentDescription: String?,
        val bounds: Rect
    )

    private val visitedHistoryLock = Any()
    private val visitedHistoryLabels = linkedSetOf<String>()
    private val visitedHistorySignatures = mutableListOf<VisibleHistorySignature>()

    @Volatile
    internal var activeSmartNextTurnId: Long = 0L
    @Volatile
    internal var lastFinalCommitTurnId: Long = 0L
    @Volatile
    internal var smartNextTurnSeed: Long = 0L

    @Volatile
    private var authoritativeFocusWindowUntilMs: Long = 0L
    @Volatile
    private var authoritativeCommittedBounds: Rect? = null
    @Volatile
    private var authoritativeCommittedIdentity: String? = null
    @Volatile
    private var authoritativeCommittedLabel: String? = null
    @Volatile
    internal var authoritativeCommittedNode: AccessibilityNodeInfo? = null
    @Volatile
    internal var authoritativeCommittedStatus: String = "moved"

    fun clearVisitedHistory() {
        synchronized(visitedHistoryLock) {
            visitedHistoryLabels.clear()
            visitedHistorySignatures.clear()
        }
    }

    fun snapshotVisitedHistoryLabels(): Set<String> = synchronized(visitedHistoryLock) { visitedHistoryLabels.toSet() }

    fun snapshotVisitedHistorySignatures(): Set<VisibleHistorySignature> = synchronized(visitedHistoryLock) {
        visitedHistorySignatures.toSet()
    }

    fun recordVisitedSignature(label: String, viewId: String?, bounds: Rect, nodeIdentity: String?) {
        val normalizedLabel = label.trim()
        synchronized(visitedHistoryLock) {
            if (normalizedLabel.isNotEmpty() && normalizedLabel != "<no-label>") {
                visitedHistoryLabels += normalizedLabel
            }
            visitedHistorySignatures += VisibleHistorySignature(
                label = normalizedLabel.takeUnless { it.isBlank() || it == "<no-label>" },
                viewId = viewId,
                bounds = Rect(bounds),
                nodeIdentity = nodeIdentity
            )
            if (visitedHistorySignatures.size > 120) {
                visitedHistorySignatures.removeAt(0)
            }
        }
    }

    internal fun issueNextSmartNextTurnId(): Long = synchronized(this) {
        smartNextTurnSeed += 1L
        smartNextTurnSeed
    }

    internal fun isWithinAuthoritativeFocusWindow(nowMs: Long = System.currentTimeMillis()): Boolean {
        if (authoritativeFocusWindowUntilMs <= 0L) return false
        val stillWithin = nowMs <= authoritativeFocusWindowUntilMs
        if (!stillWithin) {
            authoritativeCommittedNode = null
            clearAuthoritativeFocusWindow()
        }
        return stillWithin
    }

    internal fun shouldIgnorePostCommitResurfacedHeader(
        root: AccessibilityNodeInfo?,
        candidate: AccessibilityNodeInfo?,
        eventType: Int
    ): Boolean {
        if (candidate == null || !isWithinAuthoritativeFocusWindow()) return false
        val committedBounds = authoritativeCommittedBounds() ?: return false
        val candidateBounds = Rect().also(candidate::getBoundsInScreen)
        val sameBounds = candidateBounds == committedBounds
        val committedIdentity = authoritativeCommittedIdentity()
        val candidateIdentity = A11yNavigator.nodeIdentityOf(candidate)
        val sameIdentity = !committedIdentity.isNullOrBlank() && committedIdentity == candidateIdentity
        if (sameBounds || sameIdentity) return false

        val rootBounds = root?.let { Rect().also(it::getBoundsInScreen) } ?: Rect(0, 0, 0, candidateBounds.bottom)
        val rootTop = rootBounds.top
        val rootBottom = if (rootBounds.bottom > rootBounds.top) rootBounds.bottom else candidateBounds.bottom
        val rootHeight = (rootBottom - rootTop).coerceAtLeast(1)
        val isHeaderLike = A11yNavigator.isHeaderLikeCandidate(
            className = candidate.className?.toString(),
            viewIdResourceName = candidate.viewIdResourceName,
            label = A11yNavigator.resolvePrimaryLabel(candidate) ?: A11yTraversalAnalyzer.recoverDescendantLabel(candidate),
            boundsInScreen = candidateBounds,
            screenTop = rootTop,
            screenHeight = rootHeight
        )
        val isTopChrome = A11yNodeUtils.isTopAppBar(
            className = candidate.className?.toString(),
            viewIdResourceName = candidate.viewIdResourceName,
            boundsInScreen = candidateBounds,
            screenTop = rootTop,
            screenHeight = rootHeight
        )
        val isPersistentHeader = candidateBounds.top <= rootTop + (rootHeight / 4) && isHeaderLike
        val isContent = A11yNodeUtils.isContentNode(
            node = candidate,
            bounds = candidateBounds,
            screenTop = rootTop,
            screenBottom = rootBottom,
            screenHeight = rootHeight,
            mainScrollContainer = null
        )
        val shouldIgnore = (isTopChrome || isPersistentHeader || isHeaderLike) && !isContent
        if (shouldIgnore) {
            Log.i(
                "A11Y_HELPER",
                "[FOCUS_VERIFY] ignored_post_commit_resurfaced_header eventType=$eventType candidate=${(A11yNavigator.resolvePrimaryLabel(candidate) ?: A11yTraversalAnalyzer.recoverDescendantLabel(candidate) ?: "<no-label>").replace("\n", " ")} committed=${(authoritativeCommittedLabel() ?: "<no-label>").replace("\n", " ")} committedBounds=${A11yNavigator.formatBoundsForLog(committedBounds)} candidateBounds=${A11yNavigator.formatBoundsForLog(candidateBounds)}"
            )
        }
        return shouldIgnore
    }

    internal fun startAuthoritativeFocusSuppressionWindow(candidate: AccessibilityNodeInfo, label: String, status: String) {
        val until = System.currentTimeMillis() + RETARGET_SUPPRESSION_WINDOW_MS
        authoritativeCommittedNode = candidate
        authoritativeCommittedStatus = status
        startAuthoritativeFocusWindow(
            untilMs = until,
            label = label,
            identity = A11yNavigator.nodeIdentityOf(candidate),
            bounds = Rect().also(candidate::getBoundsInScreen),
            status = status
        )
        Log.i(
            "A11Y_HELPER",
            "[FOCUS_VERIFY] suppression_window_start untilMs=$until candidate=${label.replace("\n", " ")} bounds=${A11yNavigator.formatBoundsForLog(Rect().also(candidate::getBoundsInScreen))}"
        )
    }

    internal fun clearAuthoritativeFocusSuppressionWindow(reason: String) {
        if (authoritativeFocusWindowUntilMs <= 0L) return
        authoritativeCommittedNode = null
        authoritativeCommittedStatus = "moved"
        clearAuthoritativeFocusWindow()
        Log.i("A11Y_HELPER", "[FOCUS_VERIFY] suppression_window_end reason=$reason")
    }

    fun startAuthoritativeFocusWindow(untilMs: Long, label: String, identity: String?, bounds: Rect, status: String) {
        authoritativeFocusWindowUntilMs = untilMs
        authoritativeCommittedLabel = label
        authoritativeCommittedIdentity = identity
        authoritativeCommittedBounds = Rect(bounds)
        authoritativeCommittedStatus = status
    }

    fun clearAuthoritativeFocusWindow() {
        authoritativeFocusWindowUntilMs = 0L
        authoritativeCommittedLabel = null
        authoritativeCommittedIdentity = null
        authoritativeCommittedBounds = null
        authoritativeCommittedStatus = "moved"
    }

    fun authoritativeCommittedBounds(): Rect? = authoritativeCommittedBounds?.let(::Rect)
    fun authoritativeCommittedIdentity(): String? = authoritativeCommittedIdentity
    fun authoritativeCommittedLabel(): String? = authoritativeCommittedLabel
}
