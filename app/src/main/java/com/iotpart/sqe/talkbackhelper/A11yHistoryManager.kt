package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect

object A11yHistoryManager {
    const val VERSION: String = "1.0.0"

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
    private var authoritativeFocusWindowUntilMs: Long = 0L
    @Volatile
    private var authoritativeCommittedBounds: Rect? = null
    @Volatile
    private var authoritativeCommittedIdentity: String? = null
    @Volatile
    private var authoritativeCommittedLabel: String? = null
    @Volatile
    private var authoritativeCommittedStatus: String = "moved"

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

    fun isWithinAuthoritativeFocusWindow(nowMs: Long = System.currentTimeMillis()): Boolean {
        if (authoritativeFocusWindowUntilMs <= 0L) return false
        return nowMs <= authoritativeFocusWindowUntilMs
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
