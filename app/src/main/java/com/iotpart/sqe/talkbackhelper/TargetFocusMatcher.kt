package com.iotpart.sqe.talkbackhelper

/** Pure identity matching for planner-selected accessibility targets. */
internal object TargetFocusMatcher {
    data class Descriptor(
        val bounds: String,
        val resourceId: String = "",
        val label: String = "",
        val className: String = ""
    )

    data class Candidate(
        val bounds: String,
        val resourceId: String = "",
        val label: String = "",
        val className: String = ""
    )

    enum class Resolution { MATCHED, NOT_FOUND, AMBIGUOUS, INVALID }

    data class Result(val resolution: Resolution, val index: Int = -1)

    private fun normalized(value: String): String = value.trim().replace(Regex("\\s+"), " ").lowercase()
    private fun normalizedBounds(value: String): String =
        Regex("-?\\d+").findAll(value).map { it.value }.take(4).joinToString(",")

    fun resolve(descriptor: Descriptor, candidates: List<Candidate>): Result {
        val expectedBounds = normalizedBounds(descriptor.bounds)
        val hasStrongMetadata = descriptor.resourceId.isNotBlank() || descriptor.label.isNotBlank() || descriptor.className.isNotBlank()
        if (expectedBounds.split(',').size != 4 || !hasStrongMetadata) return Result(Resolution.INVALID)
        val matches = candidates.withIndex().filter { (_, candidate) ->
            normalizedBounds(candidate.bounds) == expectedBounds &&
                (descriptor.resourceId.isBlank() || normalized(candidate.resourceId) == normalized(descriptor.resourceId)) &&
                (descriptor.label.isBlank() || normalized(candidate.label) == normalized(descriptor.label)) &&
                (descriptor.className.isBlank() || normalized(candidate.className) == normalized(descriptor.className))
        }
        return when (matches.size) {
            0 -> Result(Resolution.NOT_FOUND)
            1 -> Result(Resolution.MATCHED, matches.single().index)
            else -> Result(Resolution.AMBIGUOUS)
        }
    }

    fun sameIdentity(descriptor: Descriptor, candidate: Candidate): Boolean =
        resolve(descriptor, listOf(candidate)).resolution == Resolution.MATCHED
}
