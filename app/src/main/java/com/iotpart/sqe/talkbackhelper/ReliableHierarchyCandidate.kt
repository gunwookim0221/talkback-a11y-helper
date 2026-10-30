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
    const val ROOT_CAPTURE_ID_VERSION = "phase6d-root-capture-id-v1"

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

    /** Capture-local root correlation derived from the accepted transfer identity and exact root bytes. */
    fun rootCaptureId(
        requestId: String, processEpoch: String, generation: Long, serviceInstanceId: String,
        captureSequence: Long, rootRef: String, rootDigest: String
    ): String {
        require(requestId.isNotBlank() && processEpoch.isNotBlank() && serviceInstanceId.isNotBlank()) {
            "CAPTURE_ROOT_IDENTITY_INVALID"
        }
        require(generation > 0 && captureSequence > 0 && ROOT_REF.matches(rootRef)) {
            "CAPTURE_ROOT_IDENTITY_INVALID"
        }
        require(rootDigest.matches(Regex("[0-9a-f]{64}"))) { "CAPTURE_ROOT_DIGEST_INVALID" }
        return CaptureCanonicalJson.sha256(JSONObject()
            .put("identity_schema", ROOT_CAPTURE_ID_VERSION)
            .put("schema_version", HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA)
            .put("canonicalization", CaptureCanonicalJson.VERSION)
            .put("request_id", requestId)
            .put("process_epoch", processEpoch)
            .put("generation", generation)
            .put("service_instance_id", serviceInstanceId)
            .put("capture_sequence", captureSequence)
            .put("root_ref", rootRef)
            .put("root_digest", rootDigest))
    }

    /** Production projection over the immutable DTO and exact serialized root digest. */
    fun buildFromImmutable(
        root: CapturedHierarchyNode, traversalRootRef: String, rootDigest: String, rootCaptureId: String
    ): JSONObject {
        require(ROOT_REF.matches(traversalRootRef)) { "TRAVERSAL_ROOT_REF_INVALID" }
        require(rootDigest.matches(Regex("[0-9a-f]{64}"))) { "TRAVERSAL_ROOT_DIGEST_INVALID" }
        require(rootCaptureId.matches(Regex("[0-9a-f]{64}"))) { "TRAVERSAL_ROOT_CAPTURE_ID_INVALID" }
        val legacy = ImmutableHierarchyCandidateProjection.build(root)
        val candidates = legacy.getJSONArray("nodes")
        val projection = JSONObject()
            .put("schema_version", SCHEMA_VERSION)
            .put("candidate_contract_version", CONTRACT_VERSION)
            .put("algorithmVersion", A11yNavigator.NAVIGATOR_ALGORITHM_VERSION)
            .put("analyzerVersion", A11yTraversalAnalyzer.VERSION)
            .put("profileId", PROFILE_ID)
            .put("profileVersion", PROFILE_VERSION)
            .put("completion", JSONObject().put("status", "COMPLETE").put("complete", true).put("candidate_count", candidates.length()))
            .put("traversalRootRef", traversalRootRef)
            .put("traversalRootWindowId", root.windowId)
            .put("canScrollDown", legacy.optBoolean("canScrollDown", false))
            .put("scrollAxisContract", "axis-v1")
            .put("source_root_digest", rootDigest)
            .put("rootCaptureId", rootCaptureId)
            .put("candidates", candidates)
        return projection.put("candidate_digest", CaptureCanonicalJson.sha256(projection))
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
        if (completion.optInt("candidate_count", -1) != candidateProjection.getJSONArray("candidates").length()) return false
        val rawDigest = CaptureCanonicalJson.sha256(rawRoot)
        if (candidateProjection.optString("source_root_digest") != rawDigest) return false
        val candidateDigest = candidateProjection.optString("candidate_digest")
        if (!candidateDigest.matches(Regex("[0-9a-f]{64}"))) return false
        val digestInput = JSONObject(candidateProjection.toString()).apply { remove("candidate_digest") }
        if (CaptureCanonicalJson.sha256(digestInput) != candidateDigest) return false
        val envelope = payload.optJSONObject("captureEnvelope") ?: return false
        val generation = envelope.opt("generation")
        val captureSequence = envelope.opt("capture_sequence")
        if (envelope.optString("schema_version") != HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA ||
            envelope.optString("canonicalization") != CaptureCanonicalJson.VERSION ||
            envelope.optString("request_id") != payload.optString("reqId") ||
            payload.optString("reqId").isBlank() ||
            envelope.optString("process_epoch").isBlank() ||
            envelope.optString("service_instance_id").isBlank() ||
            generation !is Long && generation !is Int ||
            captureSequence !is Long && captureSequence !is Int ||
            (generation as Number).toLong() <= 0L || (captureSequence as Number).toLong() <= 0L ||
            envelope.optString("root_ref") != rawRef || envelope.optString("root_digest") != rawDigest ||
            envelope.optString("candidate_digest") != candidateDigest) return false
        val expectedRootCaptureId = runCatching {
            rootCaptureId(
                envelope.getString("request_id"), envelope.getString("process_epoch"),
                (generation as Number).toLong(), envelope.getString("service_instance_id"),
                (captureSequence as Number).toLong(), envelope.getString("root_ref"),
                envelope.getString("root_digest")
            )
        }.getOrNull() ?: return false
        if (candidateProjection.optString("rootCaptureId") != expectedRootCaptureId) return false
        return true
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
