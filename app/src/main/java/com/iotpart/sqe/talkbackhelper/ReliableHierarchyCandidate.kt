package com.iotpart.sqe.talkbackhelper

import android.view.accessibility.AccessibilityNodeInfo
import android.os.Build
import org.json.JSONObject

/**
 * Versioned contract for the candidate projection that mirrors dump_tree().
 * Candidate policy remains owned by the existing Kotlin generator.
 */
internal object ReliableHierarchyCandidateContract {
    const val SCHEMA_VERSION = "legacy-traversal-candidates.v1"
    const val CONTRACT_VERSION = "legacy-traversal-candidate-contract.v1"
    const val PROFILE_ID = "oneconnect-traversal-policy"
    const val PROFILE_VERSION = OneConnectTraversalPolicy.VERSION

    private val ROOT_REF = Regex("^windows\\[(0|[1-9][0-9]*)]\\.root$")

    fun traversalRootIndex(windowIds: List<Int>, traversalRootWindowId: Int): Int {
        val matches = windowIds.indices.filter { windowIds[it] == traversalRootWindowId }
        require(matches.size == 1) { "TRAVERSAL_ROOT_UNBOUND" }
        return matches.single()
    }

    /**
     * Requires the raw root and candidate root to be the very same captured
     * AccessibilityNodeInfo instance. This keeps the reference meaningful for
     * this request without turning it into a persistent node identity.
     */
    fun build(
        candidateRoot: AccessibilityNodeInfo,
        serializedRawRoot: AccessibilityNodeInfo,
        traversalRootRef: String
    ): JSONObject {
        require(candidateRoot === serializedRawRoot) { "TRAVERSAL_ROOT_INSTANCE_MISMATCH" }
        require(ROOT_REF.matches(traversalRootRef)) { "TRAVERSAL_ROOT_REF_INVALID" }

        val legacy = A11yNavigator.dumpTreeFlat(candidateRoot)
        require(legacy.optJSONArray("nodes") != null) { "CANDIDATE_PROJECTION_MISSING" }
        val candidates = legacy.getJSONArray("nodes")

        return JSONObject()
            .put("schema_version", SCHEMA_VERSION)
            .put("candidate_contract_version", CONTRACT_VERSION)
            .put("algorithmVersion", A11yNavigator.NAVIGATOR_ALGORITHM_VERSION)
            .put("analyzerVersion", A11yTraversalAnalyzer.VERSION)
            .put("profileId", PROFILE_ID)
            .put("profileVersion", PROFILE_VERSION)
            .put("completion", JSONObject()
                .put("status", "COMPLETE")
                .put("complete", true)
                .put("candidate_count", candidates.length()))
            .put("traversalRootRef", traversalRootRef)
            .put("traversalRootWindowId", candidateRoot.windowId)
            .put("canScrollDown", legacy.optBoolean("canScrollDown", false))
            .put("scrollAxisContract", "axis-v1")
            .put("candidates", candidates)
    }

    /** Fail closed unless the candidate projection points at a serialized raw root. */
    fun hasValidRootBinding(payload: JSONObject): Boolean {
        if (payload.optString("schemaVersion") != HierarchyPayloadActions.PAYLOAD_SCHEMA) return false
        val rawRef = payload.optString("traversalRootRef")
        val candidateProjection = payload.optJSONObject("traversalCandidates") ?: return false
        val candidateRef = candidateProjection.optString("traversalRootRef")
        if (rawRef.isBlank() || candidateRef != rawRef) return false

        val match = ROOT_REF.matchEntire(rawRef) ?: return false
        val windowIndex = match.groupValues[1].toIntOrNull() ?: return false
        val windows = payload.optJSONArray("windows") ?: return false
        if (windowIndex !in 0 until windows.length()) return false
        val rawRoot = windows.optJSONObject(windowIndex)?.optJSONObject("root") ?: return false
        val rawWindowId = rawRoot.optInt("windowId", Int.MIN_VALUE)
        if (rawWindowId == Int.MIN_VALUE) return false
        if (payload.optInt("traversalRootWindowId", Int.MIN_VALUE) != rawWindowId) return false
        if (candidateProjection.optInt("traversalRootWindowId", Int.MIN_VALUE) != rawWindowId) return false

        val completion = candidateProjection.optJSONObject("completion") ?: return false
        if (!completion.optBoolean("complete", false) || completion.optString("status") != "COMPLETE") return false
        if (candidateProjection.optString("schema_version") != SCHEMA_VERSION) return false
        if (candidateProjection.optString("candidate_contract_version") != CONTRACT_VERSION) return false
        if (candidateProjection.optJSONArray("candidates") == null) return false
        return completion.optInt("candidate_count", -1) == candidateProjection.getJSONArray("candidates").length()
    }
}

internal object ReliableHierarchySchemaV2 {
    fun addRawMetadata(payload: JSONObject, platformApiLevel: Int): JSONObject = payload.apply {
        put("schemaVersion", HierarchyPayloadActions.PAYLOAD_SCHEMA)
        put("platformApiLevel", platformApiLevel)
        put("nodeMetadataSchemaName", "talkback.helper.read_only_node_metadata")
        put("nodeMetadataSchemaVersion", "1.0")
        put("nodeMetadataCapabilities", JSONObject().apply {
            put("source_node_id", platformApiLevel >= Build.VERSION_CODES.TIRAMISU)
            put("resource_id", true)
            put("class_name", true)
            put("text", true)
            put("content_description", true)
            put("bounds", true)
            put("clickable", true)
            put("focusable", true)
            put("screen_reader_focusable", platformApiLevel >= Build.VERSION_CODES.P)
            put("range_info_present", true)
            put("enabled", true)
            put("selected", true)
            put("accessibility_focused", true)
            put("input_focused", true)
            put("scrollable", true)
            put("visible_to_user", true)
            put("actions", true)
            put("window_id", true)
            put("package", true)
            put("semantic_role", false)
            put("production_qualified_focus_identity", false)
            put("activity", false)
            put("platform_generation_id", false)
        })
    }
}

internal data class ReliableHierarchyCapture(
    val payload: JSONObject,
    val rawHierarchyBytesEstimate: Long,
    val candidateProjectionBytesEstimate: Long,
    val totalPayloadBytesEstimate: Long,
    val candidateCount: Int,
    val rawNodeCount: Int,
    val rawSerializationElapsedNanos: Long,
    val candidateGenerationElapsedNanos: Long,
    val candidateSerializationElapsedNanos: Long
)
