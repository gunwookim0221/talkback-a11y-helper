package com.iotpart.sqe.talkbackhelper

import android.util.JsonReader
import android.util.JsonToken
import org.json.JSONArray
import org.json.JSONObject
import java.io.StringReader
import java.security.MessageDigest
import java.time.Instant
import java.util.Collections

/**
 * Read-only Phase 5D-C exact node resolver. This class only inspects a serialized
 * full hierarchy. It contains no AccessibilityNodeInfo reference and no dispatch
 * dependency by construction.
 */
internal object ExactNodeResolver {
    const val PROTOCOL_VERSION = "talkback.exact-navigation.v1"
    const val COMMAND = "RESOLVE_EXACT_NODE"
    const val ACTION_TYPE = "EXACT_READ_ONLY_NAVIGATION"

    private val requestIds = Collections.synchronizedSet(mutableSetOf<String>())
    private val nonces = Collections.synchronizedSet(mutableSetOf<String>())
    private val permits = Collections.synchronizedMap(mutableMapOf<String, String>())
    private val transactions = Collections.synchronizedMap(mutableMapOf<String, String>())

    private val requestFields = setOf(
        "protocol_version", "command", "request_id", "transaction_id", "permit_id", "request_nonce",
        "ownership", "action_type", "expected_package", "expected_window", "authorized_snapshot_id",
        "reacquire_snapshot_id", "target_identity_schema", "target_identity", "target_action_set",
        "target_lineage_signature", "target_child_structure_signature", "created_at", "expires_at",
        "permit_created_at", "permit_expires_at",
        "hard_stop_active", "source_request_id", "helper_service_instance_id", "host_session_id",
        "stop_epoch", "request_digest", "evidence_refs"
    )

    private val requiredRequestFields = requestFields - "evidence_refs"
    private val targetFields = setOf(
        "package", "window_id", "resource_id", "class_name", "text", "content_description", "bounds",
        "source_node_id", "source_node_id_provenance", "node_local_id", "hierarchy_path", "parent_identity",
        "lineage_signature", "child_structure_signature", "actions", "semantic_role", "snapshot_id",
        "field_provenance"
    )

    fun resolve(
        requestJson: String,
        hierarchy: JSONObject,
        hardStopActive: Boolean = false,
        helperServiceInstanceId: String? = null,
    ): JSONObject {
        var request: JSONObject? = null
        return try {
            val ack = if (hasDuplicateJsonKey(requestJson)) {
                failureAck(null, "REQUEST_INVALID", 0).put("validation_detail", "duplicate_or_malformed_json")
            } else {
                request = JSONObject(requestJson)
                val invalid = validate(request!!, hardStopActive, helperServiceInstanceId)
                if (invalid != null) {
                    failureAck(request!!, invalid, 0)
                } else {
                    resolveValidated(request!!, hierarchy)
                }
            }
            if (helperServiceInstanceId != null) ack.put("helper_service_instance_id", helperServiceInstanceId)
            ack
        } catch (error: Exception) {
            failureAck(request, "REQUEST_INVALID", 0).put("validation_detail", error.javaClass.simpleName)
        }
    }

    fun invalidRequestAck(requestId: String, failureCode: String): JSONObject = baseAck(null).apply {
        put("request_id", requestId.ifBlank { "unavailable" })
        put("failure_code", failureCode)
    }

    /** Stateless continuity check; action replay protection belongs to the durable action store. */
    internal fun resolveForAction(requestJson:String,hierarchy:JSONObject,connectionEpoch:String):JSONObject {
        if(hasDuplicateJsonKey(requestJson))return failureAck(null,"REQUEST_INVALID",0)
        return try {
            val request=JSONObject(requestJson)
            val error=validateOnly(request,false,connectionEpoch)
            if(error!=null)failureAck(request,error,0) else resolveValidated(request,hierarchy)
        } catch(error:Exception) { failureAck(null,"REQUEST_INVALID",0) }
    }

    internal fun validateOnly(request: JSONObject, hardStopActive: Boolean, helperServiceInstanceId: String?): String? =
        validate(request, hardStopActive, helperServiceInstanceId, claim = false)

    private fun validate(request: JSONObject, hardStopActive: Boolean, helperServiceInstanceId: String?, claim: Boolean = true): String? {
        if (!hasExactly(request, requiredRequestFields, requestFields)) return "REQUEST_INVALID"
        if (request.optString("protocol_version") != PROTOCOL_VERSION) return "PROTOCOL_VERSION_UNSUPPORTED"
        if (request.optString("command") != COMMAND || request.optString("action_type") != ACTION_TYPE) return "ACTION_EXECUTION_DISABLED"
        if (hardStopActive || request.opt("hard_stop_active") != false) return "HARD_STOP_ACTIVE"
        for (key in listOf("request_id", "transaction_id", "permit_id", "request_nonce", "expected_package",
                "authorized_snapshot_id", "reacquire_snapshot_id", "helper_service_instance_id", "host_session_id", "stop_epoch")) {
            if (request.opt(key) !is String || !validId(request.optString(key))) return "REQUEST_INVALID"
        }
        if (request.opt("source_request_id") !is String || !validId(request.optString("source_request_id"))) return "REQUEST_INVALID"
        if (helperServiceInstanceId != null && request.optString("helper_service_instance_id") != helperServiceInstanceId) {
            return "HELPER_SERVICE_INSTANCE_MISMATCH"
        }
        if (request.optString("authorized_snapshot_id") == request.optString("reacquire_snapshot_id")) return "SNAPSHOT_STALE"
        val expectedWindow = request.optJSONObject("expected_window") ?: return "REQUEST_INVALID"
        if (!hasExactly(expectedWindow, setOf("id", "type"), setOf("id", "type", "context_epoch"))) return "REQUEST_INVALID"
        if (!expectedWindow.has("id") || !expectedWindow.has("type") || expectedWindow.isNull("id") || expectedWindow.isNull("type")) return "WINDOW_MISMATCH"
        val ownership = request.optJSONObject("ownership") ?: return "REQUEST_INVALID"
        val ownershipFields = setOf("run_id", "scenario_id", "scenario_transaction_id", "step_action_id", "parent_action_id")
        if (!hasExactly(ownership, ownershipFields, ownershipFields)) return "REQUEST_INVALID"
        for (key in listOf("run_id", "scenario_id", "scenario_transaction_id", "step_action_id")) {
            if (ownership.opt(key) !is String || !validId(ownership.optString(key))) return "REQUEST_INVALID"
        }
        val parentAction = ownership.opt("parent_action_id")
        if (parentAction !== JSONObject.NULL && !validId(parentAction as? String ?: return "REQUEST_INVALID")) return "REQUEST_INVALID"

        val target = request.optJSONObject("target_identity") ?: return "METADATA_INCOMPLETE"
        if (!hasExactly(target, targetFields, targetFields)) return "METADATA_INCOMPLETE"
        for(field in listOf("resource_id","class_name","node_local_id","package","snapshot_id"))if(target.opt(field) !is String)return "METADATA_INCOMPLETE"
        if (request.optString("target_identity_schema") != "talkback.exact-node-descriptor.v1") return "REQUEST_INVALID"
        if (target.optString("package") != request.optString("expected_package")) return "PACKAGE_MISMATCH"
        if (!sameJsonValue(target.opt("window_id"), expectedWindow.opt("id"))) return "WINDOW_MISMATCH"
        if (target.optString("snapshot_id") != request.optString("reacquire_snapshot_id")) return "SNAPSHOT_STALE"
        if (target.optString("resource_id").isBlank() || target.optString("class_name").isBlank() || target.optString("node_local_id").isBlank()) return "METADATA_INCOMPLETE"
        val provenance = target.optJSONObject("field_provenance") ?: return "METADATA_INCOMPLETE"
        val provenanceFields = setOf("package", "resource_id", "class_name", "text", "content_description", "bounds", "actions", "source_node_id", "semantic_role")
        if (provenance.keys().asSequence().toSet() != provenanceFields) return "METADATA_INCOMPLETE"
        val validProvenance = setOf("PRESENT", "ABSENT_IN_SOURCE", "NOT_SUPPORTED_BY_SOURCE", "PARSE_FAILED")
        for (field in provenanceFields) {
            val entry = provenance.optJSONObject(field) ?: return "METADATA_INCOMPLETE"
            if (!hasExactly(entry, setOf("status", "source_field", "derivation"), setOf("status", "source_field", "derivation"))) return "METADATA_INCOMPLETE"
            if (entry.optString("status") !in validProvenance) return "METADATA_INCOMPLETE"
            val sourceField = entry.opt("source_field")
            if (sourceField !== JSONObject.NULL && sourceField !is String) return "METADATA_INCOMPLETE"
            if (entry.opt("derivation") !is String) return "METADATA_INCOMPLETE"
        }
        for (field in listOf("package", "resource_id", "class_name", "bounds", "actions")) {
            if (provenance.optJSONObject(field)?.optString("status") != "PRESENT") return "METADATA_INCOMPLETE"
        }
        if (target.optString("source_node_id_provenance") != provenance.optJSONObject("source_node_id")?.optString("status")) return "REQUEST_INVALID"
        val bounds = target.optJSONObject("bounds") ?: return "METADATA_INCOMPLETE"
        for (coordinate in listOf("left", "top", "right", "bottom")) if (bounds.opt(coordinate) !is Number) return "METADATA_INCOMPLETE"
        if (!validActionList(target.optJSONArray("actions")) || !validActionList(request.optJSONArray("target_action_set"))) return "METADATA_INCOMPLETE"
        if (request.optJSONArray("target_action_set")?.length() == 0) return "METADATA_INCOMPLETE"
        if (!sameJsonValue(request.optJSONArray("target_action_set"), target.optJSONArray("actions"))) return "ACTION_SET_CHANGED"
        val lineage = request.optJSONArray("target_lineage_signature") ?: return "METADATA_INCOMPLETE"
        val childStructure = request.optJSONArray("target_child_structure_signature") ?: return "METADATA_INCOMPLETE"
        if (!validSignatureList(lineage, nested = false) || !validSignatureList(childStructure, nested = true)) return "METADATA_INCOMPLETE"
        if (!sameJsonValue(lineage, target.optJSONArray("lineage_signature"))) return "REQUEST_INVALID"
        if (!sameJsonValue(childStructure, target.optJSONArray("child_structure_signature"))) return "REQUEST_INVALID"
        val expectedParent = if (lineage.length() > 0) lineage.opt(lineage.length() - 1) else JSONObject.NULL
        if (!sameJsonValue(target.opt("parent_identity"), expectedParent)) return "REQUEST_INVALID"
        val path = target.optJSONObject("hierarchy_path") ?: return "METADATA_INCOMPLETE"
        if (!hasExactly(path, setOf("window_order", "child_indices"), setOf("window_order", "child_indices")) ||
            !isNonnegativeInteger(path.opt("window_order"))) return "METADATA_INCOMPLETE"
        val childIndices = path.optJSONArray("child_indices") ?: return "METADATA_INCOMPLETE"
        for (index in 0 until childIndices.length()) if (!isNonnegativeInteger(childIndices.opt(index))) return "METADATA_INCOMPLETE"
        val createdAt = runCatching { Instant.parse(request.optString("created_at")) }.getOrNull() ?: return "REQUEST_INVALID"
        val expiresAt = runCatching { Instant.parse(request.optString("expires_at")) }.getOrNull() ?: return "REQUEST_INVALID"
        if (expiresAt <= createdAt) return "REQUEST_INVALID"
        if (Instant.now() >= expiresAt) return "REQUEST_EXPIRED"
        val permitCreatedAt = runCatching { Instant.parse(request.optString("permit_created_at")) }.getOrNull() ?: return "PERMIT_INVALID"
        val permitExpiresAt = runCatching { Instant.parse(request.optString("permit_expires_at")) }.getOrNull() ?: return "PERMIT_INVALID"
        if (permitExpiresAt <= permitCreatedAt) return "PERMIT_INVALID"
        if (Instant.now() >= permitExpiresAt) return "PERMIT_EXPIRED"
        val digest = request.optString("request_digest")
        if (!digest.matches(Regex("[0-9a-f]{64}"))) return "REQUEST_INVALID"
        val calculated = requestDigest(request)
        if (digest != calculated) return "REQUEST_INVALID"

        if (!claim) return null // Action channel has a separate durable claim; never executes here.
        val requestId = request.optString("request_id")
        val nonce = request.optString("request_nonce")
        val permitId = request.optString("permit_id")
        val transactionId = request.optString("transaction_id")
        synchronized(requestIds) {
            if (requestIds.contains(requestId) || nonces.contains(nonce) || permits.containsKey(permitId)) return "REQUEST_REPLAYED"
            val priorPermit = transactions[transactionId]
            if (priorPermit != null && priorPermit != permitId) return "TRANSACTION_MISMATCH"
            requestIds.add(requestId)
            nonces.add(nonce)
            permits[permitId] = transactionId
            transactions[transactionId] = permitId
        }
        return null
    }

    private data class Candidate(
        val node: JSONObject,
        val window: JSONObject,
        val windowOrder: Int,
        val ancestors: List<Pair<JSONObject, Int>>,
        val siblingIndex: Int,
        val hierarchyPath: List<Int>,
    )

    private fun resolveValidated(request: JSONObject, hierarchy: JSONObject): JSONObject {
        val helperSnapshotId = hierarchy.optString("snapshotId")
        if (helperSnapshotId.isBlank() || helperSnapshotId == request.optString("authorized_snapshot_id") ||
            helperSnapshotId == request.optString("reacquire_snapshot_id")) {
            return failureAck(request, "SNAPSHOT_STALE", 0)
                .put("helper_validation_snapshot_id", helperSnapshotId.ifBlank { JSONObject.NULL })
        }
        val expectedWindow = request.getJSONObject("expected_window")
        val target = request.getJSONObject("target_identity")
        val windows = hierarchy.optJSONArray("windows") ?: return failureAck(request, "HELPER_REACQUIRE_FAILED", 0)
        val matchingWindows = (0 until windows.length()).mapNotNull { index -> windows.optJSONObject(index)?.let { index to it } }
            .filter { (_, window) -> sameJsonValue(window.opt("id"), expectedWindow.opt("id")) && sameJsonValue(window.opt("type"), expectedWindow.opt("type")) }
        if (matchingWindows.isEmpty()) return failureAck(request, "WINDOW_MISMATCH", 0)
        val candidates = mutableListOf<Candidate>()
        matchingWindows.forEach { (windowOrder, window) ->
            walk(window.optJSONObject("root"), 0, window, windowOrder, emptyList(), emptyList(), candidates)
        }
        val sameIdentity = candidates.filter { candidate ->
            candidate.node.optString("viewIdResourceName") == target.optString("resource_id") &&
                candidate.node.optString("className") == target.optString("class_name")
        }
        val base = sameIdentity.filter { it.node.optString("packageName") == request.optString("expected_package") }
        if (base.isEmpty() && sameIdentity.isNotEmpty()) return failureAck(request, "PACKAGE_MISMATCH", sameIdentity.size)
        if (base.isEmpty()) return failureAck(request, "TARGET_NOT_FOUND", 0)
        if (base.size > 1) return failureAck(request, "TARGET_MULTI_MATCH", base.size)
        val rejected = mutableListOf<String>()
        val matches = base.filter { candidate ->
            val reason = mismatchReason(candidate, target, request)
            if (reason != null) rejected.add(reason)
            reason == null
        }
        if (matches.size > 1) return failureAck(request, "TARGET_MULTI_MATCH", matches.size)
        if (matches.isEmpty()) {
            val reason = listOf("TARGET_LINEAGE_MISMATCH", "TARGET_CHILD_STRUCTURE_CHANGED", "ACTION_SET_CHANGED", "SOURCE_NODE_ID_MISMATCH", "TARGET_IDENTITY_MISMATCH")
                .firstOrNull { it in rejected } ?: "TARGET_IDENTITY_MISMATCH"
            return failureAck(request, reason, base.size).put("identity_match_summary", JSONObject().put("rejected_reasons", JSONArray(rejected.distinct())))
        }
        val match = matches.single()
        val node = match.node
        val freshIdentity = resolvedTargetIdentity(target, match, helperSnapshotId)
        return baseAck(request).apply {
            put("resolved", true)
            put("candidate_count", 1)
            put("reacquire_verdict", "RESOLVED")
            put("resolved_target_identity", freshIdentity)
            put("resolved_source_node_id", nullable(node.opt("sourceNodeId")))
            put("resolved_source_node_id_provenance", if (node.has("sourceNodeId") && !node.isNull("sourceNodeId")) "PRESENT" else "ABSENT_IN_SOURCE")
            put("resolved_resource_id", node.optString("viewIdResourceName"))
            put("resolved_class", node.optString("className"))
            put("resolved_bounds", node.optJSONObject("boundsInScreen") ?: JSONObject.NULL)
            put("resolved_action_set", node.optJSONArray("actions") ?: JSONArray())
            put("resolved_lineage_summary", freshIdentity.getJSONArray("lineage_signature"))
            put("resolved_child_structure_summary", freshIdentity.getJSONArray("child_structure_signature"))
            put("identity_match_summary", JSONObject()
                .put("matched", JSONArray(listOf("package", "resource_id", "class_name", "lineage", "child_structure", "action_set")))
                .put("bounds_policy", "SUPPORTING_ONLY")
                .put("source_node_id_policy", "OPTIONAL_PROVENANCE_NO_GLOBAL_STABILITY"))
            put("failure_code", JSONObject.NULL)
            put("helper_validation_snapshot_id", hierarchy.optString("snapshotId").ifBlank { JSONObject.NULL })
            put("audit_event_id", sha256(request.optString("request_id") + ":helper-resolution"))
        }
    }

    private fun mismatchReason(candidate: Candidate, target: JSONObject, request: JSONObject): String? {
        val node = candidate.node
        if (!sameJsonValue(nullable(node.opt("text")), nullable(target.opt("text"))) ||
            !sameJsonValue(nullable(node.opt("contentDescription")), nullable(target.opt("content_description")))) return "TARGET_IDENTITY_MISMATCH"
        val expectedSource = target.opt("source_node_id")
        if (target.optString("source_node_id_provenance") == "PRESENT" && !target.isNull("source_node_id") &&
            (!node.has("sourceNodeId") || node.isNull("sourceNodeId") || !sameJsonValue(expectedSource, node.opt("sourceNodeId")))) return "SOURCE_NODE_ID_MISMATCH"
        if (!sameJsonValue(lineageSignature(candidate.ancestors), request.optJSONArray("target_lineage_signature"))) return "TARGET_LINEAGE_MISMATCH"
        if (!sameJsonValue(childSignature(node), request.optJSONArray("target_child_structure_signature"))) return "TARGET_CHILD_STRUCTURE_CHANGED"
        if (!sameJsonValue(actionSet(node), request.optJSONArray("target_action_set"))) return "ACTION_SET_CHANGED"
        return null
    }

    private fun walk(
        node: JSONObject?,
        nodeSiblingIndex: Int,
        window: JSONObject,
        windowOrder: Int,
        ancestors: List<Pair<JSONObject, Int>>,
        hierarchyPath: List<Int>,
        output: MutableList<Candidate>,
    ) {
        if (node == null) return
        val children = node.optJSONArray("children") ?: return
        for (index in 0 until children.length()) {
            val child = children.optJSONObject(index) ?: continue
            val childPath = hierarchyPath + index
            output.add(Candidate(child, window, windowOrder, ancestors + (node to nodeSiblingIndex), index, childPath))
            walk(child, index, window, windowOrder, ancestors + (node to nodeSiblingIndex), childPath, output)
        }
        if (ancestors.isEmpty()) output.add(Candidate(node, window, windowOrder, ancestors, 0, hierarchyPath))
    }

    private fun resolvedTargetIdentity(target: JSONObject, candidate: Candidate, snapshotId: String): JSONObject {
        val node = candidate.node
        val lineage = lineageSignature(candidate.ancestors)
        val children = childSignature(node)
        val childIndices = JSONArray().apply { candidate.hierarchyPath.forEach(::put) }
        val result = JSONObject(target.toString())
        val provenance = JSONObject()
        val fields = listOf(
            Triple("package", listOf("packageName", "package"), node.opt("packageName")),
            Triple("resource_id", listOf("viewIdResourceName", "resource_id"), node.opt("viewIdResourceName")),
            Triple("class_name", listOf("className", "class_name"), node.opt("className")),
            Triple("text", listOf("text"), node.opt("text")),
            Triple("content_description", listOf("contentDescription", "content_description"), node.opt("contentDescription")),
            Triple("bounds", listOf("boundsInScreen", "bounds"), node.opt("boundsInScreen")),
            Triple("actions", listOf("actions"), actionSet(node)),
            Triple("source_node_id", listOf("sourceNodeId", "source_node_id"), node.opt("sourceNodeId")),
            Triple("semantic_role", listOf("semanticRole", "semantic_role"), node.opt("semanticRole")),
        )
        fields.forEach { (field, aliases, value) ->
            val sourceField = aliases.firstOrNull(node::has)
            val status = when {
                sourceField == null -> "NOT_SUPPORTED_BY_SOURCE"
                value == null || value === JSONObject.NULL -> "ABSENT_IN_SOURCE"
                else -> "PRESENT"
            }
            result.put(field, nullable(value))
            provenance.put(field, JSONObject()
                .put("status", status)
                .put("source_field", sourceField ?: JSONObject.NULL)
                .put("derivation", "source_value"))
        }
        val windowId = nullable(candidate.window.opt("id"))
        result.put("window_id", windowId)
        result.put("snapshot_id", snapshotId)
        result.put("node_local_id", "$snapshotId:${candidate.windowOrder}:${candidate.hierarchyPath.joinToString(".").ifEmpty { "root" }}")
        result.put("hierarchy_path", JSONObject().put("window_order", candidate.windowOrder).put("child_indices", childIndices))
        result.put("lineage_signature", lineage)
        result.put("parent_identity", if (lineage.length() > 0) lineage.opt(lineage.length() - 1) else JSONObject.NULL)
        result.put("child_structure_signature", children)
        result.put("field_provenance", provenance)
        result.put("source_node_id_provenance", provenance.getJSONObject("source_node_id").optString("status"))
        return result
    }

    private fun lineageSignature(ancestors: List<Pair<JSONObject, Int>>): JSONArray = JSONArray().apply {
        ancestors.forEach { (node, siblingIndex) -> put(nodeSignature(node, siblingIndex, includeChildren = false)) }
    }

    private fun childSignature(node: JSONObject): JSONArray {
        val children = node.optJSONArray("children") ?: return JSONArray()
        return JSONArray().apply {
            for (index in 0 until children.length()) {
                children.optJSONObject(index)?.let { put(nodeSignature(it, index, includeChildren = true)) }
            }
        }
    }

    private fun nodeSignature(node: JSONObject, index: Int, includeChildren: Boolean): JSONObject = JSONObject().apply {
        put("resource_id", nullable(node.opt("viewIdResourceName")))
        put("class_name", nullable(node.opt("className")))
        put("package", nullable(node.opt("packageName")))
        put("text", nullable(node.opt("text")))
        put("content_description", nullable(node.opt("contentDescription")))
        put("clickable", nullable(node.opt("clickable")))
        put("focusable", nullable(node.opt("focusable")))
        put("enabled", nullable(node.opt("enabled")))
        put("visible", nullable(node.opt("visibleToUser")))
        put("child_index", index)
        put("actions", actionSet(node))
        if (includeChildren) put("children", childSignature(node))
    }

    private fun actionSet(node: JSONObject): JSONArray {
        val source = node.optJSONArray("actions") ?: return JSONArray()
        return JSONArray().apply {
            for (index in 0 until source.length()) {
                val item = source.optJSONObject(index) ?: continue
                put(JSONObject().put("id", item.optInt("id", Int.MIN_VALUE))
                    .put("name", nullable(item.opt("name"))).put("label", nullable(item.opt("label"))))
            }
        }
    }

    private fun baseAck(request: JSONObject?): JSONObject {
        val target = request?.optJSONObject("target_identity")
        return JSONObject()
            .put("protocol_version", PROTOCOL_VERSION)
            .put("ack_schema_version", "1.1")
            .put("request_id", request?.optString("request_id").orEmpty().ifBlank { "unavailable" })
            .put("transaction_id", request?.optString("transaction_id").orEmpty().ifBlank { "unavailable" })
            .put("permit_id", request?.optString("permit_id").orEmpty().ifBlank { "unavailable" })
            .put("request_nonce", request?.optString("request_nonce").orEmpty().ifBlank { "unavailable" })
            .put("resolved", false)
            .put("candidate_count", 0)
            .put("reacquire_verdict", "REJECTED")
            .put("resolved_target_identity", JSONObject.NULL)
            .put("resolved_source_node_id", JSONObject.NULL)
            .put("resolved_source_node_id_provenance", "NOT_SUPPORTED_BY_SOURCE")
            .put("resolved_resource_id", JSONObject.NULL)
            .put("resolved_class", JSONObject.NULL)
            .put("resolved_bounds", JSONObject.NULL)
            .put("resolved_action_set", JSONObject.NULL)
            .put("resolved_lineage_summary", JSONObject.NULL)
            .put("resolved_child_structure_summary", JSONObject.NULL)
            .put("identity_match_summary", JSONObject().put("matched", JSONArray()).put("rejected_reasons", JSONArray()))
            .put("perform_action_called", false)
            .put("perform_action_call_count", 0)
            .put("perform_action_return", JSONObject.NULL)
            .put("failure_code", JSONObject.NULL)
            .put("timestamp", Instant.now().toString())
            .put("authorized_snapshot_id", request?.optString("authorized_snapshot_id") ?: JSONObject.NULL)
            .put("reacquire_snapshot_id", request?.optString("reacquire_snapshot_id") ?: JSONObject.NULL)
            .put("helper_validation_snapshot_id", JSONObject.NULL)
            .put("helper_service_instance_id", request?.optString("helper_service_instance_id") ?: JSONObject.NULL)
            .put("audit_event_id", JSONObject.NULL)
            .put("visit_authority", false)
    }

    private fun failureAck(request: JSONObject?, code: String, candidateCount: Int): JSONObject = baseAck(request).apply {
        put("candidate_count", candidateCount)
        put("failure_code", code)
    }

    private fun hasExactly(obj: JSONObject, required: Set<String>, allowed: Set<String>): Boolean {
        val names = obj.keys().asSequence().toSet()
        return names.containsAll(required) && names.all { it in allowed }
    }

    private fun validActionList(actions: JSONArray?): Boolean {
        if (actions == null) return false
        for (index in 0 until actions.length()) {
            val action = actions.optJSONObject(index) ?: return false
            if (action.keys().asSequence().toSet() != setOf("id", "name", "label") || action.opt("id") !is Number) return false
            for (field in listOf("name", "label")) {
                val value = action.opt(field)
                if (value !== JSONObject.NULL && value !is String) return false
            }
        }
        return true
    }

    private fun validSignatureList(items: JSONArray, nested: Boolean): Boolean {
        for (index in 0 until items.length()) {
            val node = items.optJSONObject(index) ?: return false
            if (!validSignatureNode(node, nested)) return false
        }
        return true
    }

    private fun validSignatureNode(node: JSONObject, nested: Boolean): Boolean {
        val fields = setOf("resource_id", "class_name", "package", "text", "content_description", "clickable",
            "focusable", "enabled", "visible", "child_index", "actions") + if (nested) setOf("children") else emptySet()
        if (node.keys().asSequence().toSet() != fields) return false
        if (node.optString("class_name").isBlank() || node.optString("package").isBlank()) return false
        if (node.opt("child_index") !is Number) return false
        for (flag in listOf("clickable", "focusable", "enabled", "visible")) if (node.opt(flag) !is Boolean) return false
        if (!validActionList(node.optJSONArray("actions"))) return false
        if (nested) {
            val children = node.optJSONArray("children") ?: return false
            for (index in 0 until children.length()) {
                val child = children.optJSONObject(index) ?: return false
                if (!validSignatureNode(child, nested = true)) return false
            }
        }
        return true
    }

    private fun validId(value: String): Boolean = value.matches(Regex("[A-Za-z0-9][A-Za-z0-9._:-]{0,255}"))

    private fun isNonnegativeInteger(value: Any?): Boolean = value is Number &&
        value.toDouble().isFinite() && value.toDouble() >= 0.0 && value.toDouble() % 1.0 == 0.0

    internal fun hasDuplicateJsonKey(json: String): Boolean = runCatching {
        JsonReader(StringReader(json)).use { reader ->
            reader.isLenient = false
            fun skipValue(): Boolean = when (reader.peek()) {
                JsonToken.BEGIN_OBJECT -> {
                    reader.beginObject()
                    val names = mutableSetOf<String>()
                    var duplicate = false
                    while (reader.hasNext()) {
                        val name = reader.nextName()
                        if (!names.add(name)) duplicate = true
                        if (skipValue()) duplicate = true
                    }
                    reader.endObject()
                    duplicate
                }
                JsonToken.BEGIN_ARRAY -> {
                    reader.beginArray()
                    var duplicate = false
                    while (reader.hasNext()) if (skipValue()) duplicate = true
                    reader.endArray()
                    duplicate
                }
                JsonToken.STRING -> { reader.nextString(); false }
                JsonToken.NUMBER -> { reader.nextString(); false }
                JsonToken.BOOLEAN -> { reader.nextBoolean(); false }
                JsonToken.NULL -> { reader.nextNull(); false }
                else -> true
            }
            val duplicate = skipValue()
            duplicate || reader.peek() != JsonToken.END_DOCUMENT
        }
    }.getOrDefault(true)

    private fun nullable(value: Any?): Any = if (value == null || value === JSONObject.NULL) JSONObject.NULL else value

    private fun sameJsonValue(left: Any?, right: Any?): Boolean = canonical(left) == canonical(right)

    private fun canonical(value: Any?): String = ExactProtocolJson.canonical(value)

    private fun requestDigest(request: JSONObject): String {
        val copy = JSONObject()
        request.keys().asSequence().filter { it != "request_digest" }.forEach { key -> copy.put(key, request.opt(key)) }
        return sha256(canonical(copy))
    }

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
}
