package com.iotpart.sqe.talkbackhelper

object A11yTraversalAnalyzer {
    const val VERSION: String = "1.1.0"

    data class CandidateSelectionResult(
        val index: Int,
        val accepted: Boolean,
        val reasonCode: String
    )

    internal fun selectPostScrollCandidate(candidateIndex: Int): CandidateSelectionResult {
        return if (candidateIndex >= 0) {
            CandidateSelectionResult(index = candidateIndex, accepted = true, reasonCode = "accepted")
        } else {
            CandidateSelectionResult(index = -1, accepted = false, reasonCode = "missing")
        }
    }
}
