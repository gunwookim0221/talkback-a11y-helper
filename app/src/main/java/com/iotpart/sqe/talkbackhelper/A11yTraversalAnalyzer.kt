package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect

object A11yTraversalAnalyzer {
    const val VERSION: String = "1.0.0"

    fun selectPostScrollCandidate(candidateIndex: Int): A11yNavigator.CandidateSelectionResult {
        return if (candidateIndex >= 0) {
            A11yNavigator.CandidateSelectionResult(index = candidateIndex, accepted = true, reasonCode = "accepted")
        } else {
            A11yNavigator.CandidateSelectionResult(index = -1, accepted = false, reasonCode = "missing")
        }
    }

    internal fun <T> selectPostScrollCandidate(
        traversalList: List<T>,
        startIndex: Int,
        visibleHistory: Set<String>,
        visibleHistorySignatures: Set<A11yHistoryManager.VisibleHistorySignature>,
        visitedHistory: Set<String>,
        visitedHistorySignatures: Set<A11yHistoryManager.VisibleHistorySignature>,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        boundsOf: (T) -> Rect,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        isContentNodeOf: (T) -> Boolean = { true },
        clickableOf: ((T) -> Boolean)? = null,
        focusableOf: ((T) -> Boolean)? = null,
        descendantLabelOf: ((T) -> String?)? = null,
        preScrollAnchor: A11yHistoryManager.PreScrollAnchor? = null,
        preScrollAnchorBottom: Int? = null,
        labelOf: (T) -> String?
    ): A11yNavigator.PostScrollContinuationSearchResult {
        return A11yNavigator.selectContinuationCandidateAfterScrollResult(
            traversalList = traversalList,
            startIndex = startIndex,
            visibleHistory = visibleHistory,
            visibleHistorySignatures = visibleHistorySignatures,
            visitedHistory = visitedHistory,
            visitedHistorySignatures = visitedHistorySignatures,
            screenTop = screenTop,
            screenBottom = screenBottom,
            screenHeight = screenHeight,
            boundsOf = boundsOf,
            classNameOf = classNameOf,
            viewIdOf = viewIdOf,
            isContentNodeOf = isContentNodeOf,
            clickableOf = clickableOf,
            focusableOf = focusableOf,
            descendantLabelOf = descendantLabelOf,
            preScrollAnchor = preScrollAnchor,
            preScrollAnchorBottom = preScrollAnchorBottom,
            labelOf = labelOf
        )
    }
}
