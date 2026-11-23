package com.iotpart.sqe.talkbackhelper

import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.os.Build
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

internal const val NAVIGATION_ACTION_CLICK = "ACTION_CLICK"
internal const val NAVIGATION_ACTION_ACCESSIBILITY_FOCUS = "ACTION_ACCESSIBILITY_FOCUS"
internal const val NAVIGATION_ACTIVATION_DIRECT_CLICK = "DIRECT_CLICK"
internal const val NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK = "EXACT_OWNER_FOCUS_THEN_CLICK"
internal const val NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK =
    "DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK"

internal fun navigationPostCapturePollDelayMs(nowElapsedRealtimeMs: Long, deadlineElapsedRealtimeMs: Long): Long {
    if (nowElapsedRealtimeMs >= deadlineElapsedRealtimeMs) return 0L
    return minOf(50L, deadlineElapsedRealtimeMs - nowElapsedRealtimeMs)
}

private fun validOwnerSourceNodeIdentity(sourceIdentity: EntryClickSourceIdentity): Boolean =
    when (sourceIdentity.ownerSourceNodeIdStatus) {
        "FIELD_PRESENT" -> sourceIdentity.ownerSourceNodeId.isNotBlank()
        "FIELD_ABSENT" -> sourceIdentity.ownerSourceNodeId.isBlank()
        else -> false
    }

/** Single-use proof minted only after the navigation capability validates the request and contract. */
internal class NavigationActionDispatchAuthorization private constructor(
    val requestId: String,
    val transactionId: String,
    val leaseToken: String,
    val action: String,
) {
    private var consumed = false
    @Synchronized fun consume(requestId: String, transactionId: String, leaseToken: String, action: String): Boolean {
        if (consumed || this.requestId != requestId || this.transactionId != transactionId ||
            this.leaseToken != leaseToken || this.action != action) return false
        consumed = true
        return true
    }
    companion object {
        internal fun afterNavigationGate(requestId: String, transactionId: String, leaseToken: String, action: String) =
            NavigationActionDispatchAuthorization(requestId, transactionId, leaseToken, action)
    }
}

/** Correlation for one no-credit, read-only navigation action. */
internal data class NavigationActionBinding(
    val runId: String,
    val invocationId: String,
    val scenarioId: String,
    val requestId: String,
    val action: String,
    val transactionId: String,
    val ownerCaptureReqId: String,
    val ownerLeaseId: String,
    val serviceInstanceId: String,
    val connectionId: String,
    val windowId: Int,
    val sourceSnapshotId: String,
    val helperSnapshotId: String,
    val captureId: String,
    val nodePath: List<Int>,
    val descriptorDigest: String,
    val baselineHierarchyDigest: String,
    val effectContractId: String,
    val effectContractDigest: String,
    val sourceIdentity: EntryClickSourceIdentity,
    val activationMode: String = NAVIGATION_ACTIVATION_DIRECT_CLICK,
)

internal data class NavigationFocusEvidence(
    val requestId: String,
    val ownerCaptureReqId: String,
    val ownerLeaseId: String,
    val transactionId: String,
    val serviceInstanceId: String,
    val connectionId: String,
    val windowId: Int,
    val eventType: Int,
    val eventElapsedRealtimeMs: Long,
    val source: Any?,
)

/** Action-relevant metadata captured from a descendant of the retained exact target node. */
internal data class NavigationDescendantEvidence(
    val className: String,
    val resourceId: String,
    val label: String,
    val clickable: Boolean,
    val longClickable: Boolean,
    val checkable: Boolean,
    val editable: Boolean,
    val scrollable: Boolean,
    val actionIds: Set<Int>,
) {
    val mayChangeState: Boolean get() = clickable || longClickable || checkable || editable || scrollable ||
        actionIds.any { it in STATE_CHANGING_ACTION_IDS }

    companion object {
        private val STATE_CHANGING_ACTION_IDS = setOf(
            AccessibilityNodeInfo.ACTION_CLICK,
            AccessibilityNodeInfo.ACTION_LONG_CLICK,
            AccessibilityNodeInfo.ACTION_SET_TEXT,
            16908349, // ACTION_SET_PROGRESS is not exposed as a field by all compile SDKs.
            AccessibilityNodeInfo.ACTION_EXPAND,
            AccessibilityNodeInfo.ACTION_COLLAPSE,
        )
    }
}

internal data class NavigationActivationOwnerRelation(
    val kind: String,
    val childIndex: Int,
    val childClassPattern: String,
    val childResourceId: String,
) {
    fun isWellFormed(): Boolean = kind == "direct_child" && childIndex in 0..4096 &&
        childClassPattern.isNotBlank() && runCatching { Regex(childClassPattern) }.isSuccess &&
        childResourceId.isNotBlank() && childResourceId.length <= 256

    fun toJson(): JSONObject = JSONObject().put("kind", kind).put("child_index", childIndex)
        .put("child_class_pattern", childClassPattern).put("child_resource_id", childResourceId)
}

internal data class NavigationEmptyStateSignature(
    val exactText: String,
    val rootClassName: String,
    val containerClassName: String,
    val containerResourceId: String,
    val webViewClassName: String,
    val anchorClassName: String,
    val anchorResourceId: String,
    val excludedClassName: String,
) {
    fun isWellFormed(): Boolean = exactText.isNotBlank() && exactText.length <= 512 &&
        listOf(rootClassName, containerClassName, containerResourceId, webViewClassName,
            anchorClassName, anchorResourceId, excludedClassName).all { it.isNotBlank() && it.length <= 256 }

    fun toJson(): JSONObject = JSONObject().put("exact_text", exactText)
        .put("root_class_name", rootClassName).put("container_class_name", containerClassName)
        .put("container_resource_id", containerResourceId).put("web_view_class_name", webViewClassName)
        .put("anchor_class_name", anchorClassName).put("anchor_resource_id", anchorResourceId)
        .put("excluded_class_name", excludedClassName)
}

/** Optional policy-owned direct-parent structure for disambiguating a labeled post-action anchor. */
internal data class NavigationAnchorStructure(
    val relation: String,
    val nodeClassPattern: String,
    val parentClassPattern: String,
    val parentResourceIdPattern: String,
) {
    fun isWellFormed(): Boolean = relation == "direct_parent" &&
        listOf(nodeClassPattern, parentClassPattern, parentResourceIdPattern).all {
            it.isNotBlank() && it.length <= 256 &&
                runCatching { Regex(it, RegexOption.IGNORE_CASE) }.isSuccess
        }

    fun matches(
        node: CapturedHierarchyNode,
        parent: CapturedHierarchyNode?,
        expectedPackageName: String,
        expectedWindowId: Int,
    ): Boolean = parent != null && matches(
        nodeClassName = node.className,
        nodePackageName = node.packageName,
        nodeWindowId = node.windowId,
        parentClassName = parent.className,
        parentResourceId = parent.resourceId,
        parentPackageName = parent.packageName,
        parentWindowId = parent.windowId,
        expectedPackageName = expectedPackageName,
        expectedWindowId = expectedWindowId,
    )

    fun matches(
        nodeClassName: String?,
        nodePackageName: String?,
        nodeWindowId: Int,
        parentClassName: String?,
        parentResourceId: String?,
        parentPackageName: String?,
        parentWindowId: Int,
        expectedPackageName: String,
        expectedWindowId: Int,
    ): Boolean = relation == "direct_parent" &&
        nodePackageName == expectedPackageName && parentPackageName == expectedPackageName &&
        nodeWindowId == expectedWindowId && parentWindowId == expectedWindowId &&
        Regex(nodeClassPattern, RegexOption.IGNORE_CASE).matches(nodeClassName.orEmpty()) &&
        Regex(parentClassPattern, RegexOption.IGNORE_CASE).matches(parentClassName.orEmpty()) &&
        Regex(parentResourceIdPattern, RegexOption.IGNORE_CASE).matches(parentResourceId.orEmpty())

    fun toJson(): JSONObject = JSONObject()
        .put("relation", relation)
        .put("node_class_pattern", nodeClassPattern)
        .put("parent_class_pattern", parentClassPattern)
        .put("parent_resource_id_pattern", parentResourceIdPattern)
}

/** Structural counts are derived from the same completed post-window tree; UI text is not persisted here. */
internal data class NavigationPostStructureEvidence(
    val exactTextCount: Int,
    val exactTextWithinWebView: Boolean,
    val containerCount: Int,
    val containerWithinWebView: Boolean,
    val webViewCount: Int,
    val exactBackAnchorCount: Int,
    val excludedClassPresent: Boolean,
    val anchorPath: List<Int> = emptyList(),
) {
    fun matches(signature: NavigationEmptyStateSignature, rootClassName: String?): Boolean =
        exactTextCount == 1 && exactTextWithinWebView && containerCount == 1 &&
            webViewCount >= 1 && exactBackAnchorCount == 1 &&
            !excludedClassPresent && rootClassName == signature.rootClassName &&
            anchorPath.isNotEmpty() && anchorPath.size <= 80 && anchorPath.all { it in 0..4096 }

    fun toJson(): JSONObject = JSONObject().put("exact_text_count", exactTextCount)
        .put("exact_text_within_webview", exactTextWithinWebView)
        .put("container_count", containerCount).put("container_within_webview", containerWithinWebView)
        .put("webview_count", webViewCount).put("exact_back_anchor_count", exactBackAnchorCount)
        .put("excluded_class_present", excludedClassPresent)
        .put("anchor_path", JSONArray().apply { anchorPath.forEach { put(it) } })
}

internal data class NavigationFocusRevalidationResult(
    val accepted: Boolean,
    val diagnostics: JSONObject,
)

internal interface NavigationActionTargetLease {
    val windowId: Int
    val nodePath: List<Int>
    val descriptorDigest: String
    val sourceSnapshotId: String
    val helperSnapshotId: String
    val baselineHierarchyDigest: String
    val connectionId: String
    val independentDescendants: Int
    val independentSiblings: Int
    val isUniqueInSnapshot: Boolean
    val packageName: String
    val className: String
    val resourceId: String
    val label: String
    val subtreeLabels: List<String>
    val descendantEvidenceComplete: Boolean
    fun descendantEvidence(): List<NavigationDescendantEvidence>
    val hasClickAction: Boolean
    val hasAccessibilityFocusAction: Boolean
    fun exactDeclaredActivationChild(
        relation: NavigationActivationOwnerRelation,
        currentConnectionId: String,
    ): NavigationActionTargetLease? = null
    fun stillCurrent(currentConnectionId: String): Boolean
    fun stillCurrentAfterAccessibilityFocus(currentConnectionId: String): Boolean
    fun revalidateAfterAccessibilityFocus(currentConnectionId: String): NavigationFocusRevalidationResult {
        val accepted = stillCurrentAfterAccessibilityFocus(currentConnectionId)
        return NavigationFocusRevalidationResult(accepted,
            JSONObject().put("diagnostics_available", false).put("aggregate_accepted", accepted))
    }
    fun revalidateAfterDeclaredChildAccessibilityFocus(
        currentConnectionId: String,
        authorizationTarget: NavigationActionTargetLease,
        relation: NavigationActivationOwnerRelation,
        focusProof: NavigationFocusEvidence,
    ): NavigationFocusRevalidationResult = NavigationFocusRevalidationResult(
        false,
        JSONObject().put("diagnostics_available", true)
            .put("aggregate_accepted", false)
            .put("first_failed_check", "DECLARED_CHILD_FOCUS_REVALIDATION_UNSUPPORTED"),
    )
    fun eventSourceMatches(source: Any?, eventWindowId: Int, currentConnectionId: String): Boolean
    fun performNavigationAccessibilityFocus(
        authorization: NavigationActionDispatchAuthorization,
        requestId: String,
        transactionId: String,
        leaseToken: String,
        currentConnectionId: String,
    ): Boolean
    fun performNavigationClick(
        authorization: NavigationActionDispatchAuthorization,
        requestId: String,
        transactionId: String,
        leaseToken: String,
        currentConnectionId: String,
    ): Boolean
    fun performNavigationClickAfterAccessibilityFocus(
        authorization: NavigationActionDispatchAuthorization,
        requestId: String,
        transactionId: String,
        leaseToken: String,
        currentConnectionId: String,
    ): Boolean
}

/** Only a trusted local registry may provide contracts to the capability. RPC data cannot create one. */
internal data class NavigationEffectContract(
    val id: String,
    val digest: String,
    val effect: String,
    val packageName: String,
    val targetClassPattern: String,
    val targetResourcePattern: String,
    val targetLabelPattern: String,
    val targetSubtreePattern: String,
    val destinationPattern: String,
    val requiredAnchorPattern: String,
    val returnTransport: String,
    val expectedDescendantCount: Int,
    val excludedDescendantResourceIds: List<String>,
    val requiredNonActionableDescendantLabelPatterns: List<String>,
    val allowedScenarioIds: List<String>,
    val evidenceRefs: List<String>,
    val sourceEvidenceDigest: String,
    val activationOwnerRelation: NavigationActivationOwnerRelation? = null,
    val emptyStateSignature: NavigationEmptyStateSignature? = null,
    val requiredAnchorStructure: NavigationAnchorStructure? = null,
) {
    fun isWellFormed(expectedDigest: String): Boolean = id.isNotBlank() && digest == expectedDigest &&
        effect == "read_only_navigation" && packageName.isNotBlank() && evidenceRefs.isNotEmpty() &&
        allowedScenarioIds.isNotEmpty() && allowedScenarioIds.distinct().size == allowedScenarioIds.size &&
        returnTransport == "BACK" && expectedDescendantCount in 0..100 &&
        ((expectedDescendantCount == 0 && excludedDescendantResourceIds.isEmpty() &&
            requiredNonActionableDescendantLabelPatterns.isEmpty()) ||
            (expectedDescendantCount > 0 && excludedDescendantResourceIds.isNotEmpty() &&
                requiredNonActionableDescendantLabelPatterns.isNotEmpty())) &&
        excludedDescendantResourceIds.all { it.isNotBlank() } &&
        excludedDescendantResourceIds.distinct().size == excludedDescendantResourceIds.size &&
        evidenceRefs.all { it.isNotBlank() } && sourceEvidenceDigest.matches(Regex("[0-9a-f]{64}")) &&
        listOf(targetClassPattern, targetResourcePattern,
            targetLabelPattern, targetSubtreePattern, destinationPattern, requiredAnchorPattern).all { pattern ->
            pattern.isNotBlank() && runCatching { Regex(pattern, RegexOption.IGNORE_CASE) }.isSuccess
        } && requiredNonActionableDescendantLabelPatterns.all { pattern ->
            pattern.isNotBlank() && runCatching { Regex(pattern, RegexOption.IGNORE_CASE) }.isSuccess
        } && (activationOwnerRelation == null || activationOwnerRelation.isWellFormed()) &&
        (emptyStateSignature == null || emptyStateSignature.isWellFormed()) &&
        (requiredAnchorStructure == null || requiredAnchorStructure.isWellFormed()) && digest == canonicalDigest()

    fun matches(target: NavigationActionTargetLease): Boolean {
        if (effect != "read_only_navigation" || target.packageName != packageName) return false
        if (!Regex(targetClassPattern, RegexOption.IGNORE_CASE).matches(target.className) ||
            !Regex(targetResourcePattern, RegexOption.IGNORE_CASE).matches(target.resourceId) ||
            !Regex(targetLabelPattern, RegexOption.IGNORE_CASE).matches(target.label) ||
            !Regex(targetSubtreePattern, RegexOption.IGNORE_CASE).containsMatchIn(target.subtreeLabels.joinToString("\n")) ||
            !target.descendantEvidenceComplete) return false

        val descendants = target.descendantEvidence()
        if (descendants.size != expectedDescendantCount) return false
        val excluded = excludedDescendantResourceIds.toSet()
        if (excluded.any { resourceId -> descendants.count { it.resourceId == resourceId } != 1 }) return false
        val actionableIds = descendants.filter { it.mayChangeState }.map { it.resourceId }
        if (actionableIds.any { it !in excluded } || actionableIds.toSet() != excluded ||
            actionableIds.size != excluded.size) return false
        return requiredNonActionableDescendantLabelPatterns.all { pattern ->
            val regex = Regex(pattern, RegexOption.IGNORE_CASE)
            val matches = descendants.filter { regex.matches(it.label) }
            matches.size == 1 && !matches.single().mayChangeState
        }
    }

    fun allowsScenario(scenarioId: String): Boolean = scenarioId in allowedScenarioIds

    fun destinationMatches(labels: List<String>): Boolean {
        val exactEmptyState = emptyStateSignature?.exactText
        if (exactEmptyState != null && labels.any { it == exactEmptyState }) return false
        return labels.any { Regex(destinationPattern, RegexOption.IGNORE_CASE).containsMatchIn(it) }
    }

    fun destinationMatches(
        labels: List<String>,
        structure: NavigationPostStructureEvidence?,
        rootPackageName: String?,
        rootClassName: String?,
    ): Boolean {
        val emptyState = emptyStateSignature
        if (emptyState != null) {
            return labels.any { it == emptyState.exactText } &&
                rootPackageName == packageName && structure?.matches(emptyState, rootClassName) == true
        }
        return labels.any { Regex(destinationPattern, RegexOption.IGNORE_CASE).containsMatchIn(it) }
    }

    fun anchorMatchCount(labels: List<String>, structuralMatchCount: Int? = null): Int =
        requiredAnchorStructure?.let { structuralMatchCount ?: 0 }
            ?: labels.sumOf { Regex(requiredAnchorPattern, RegexOption.IGNORE_CASE).findAll(it).count() }

    private fun canonicalDigest(): String {
        val canonicalPolicy = JSONObject()
        canonicalPolicy.put("id", id).put("effect", effect).put("package", packageName)
        .put("target_class_pattern", targetClassPattern).put("target_resource_pattern", targetResourcePattern)
        .put("target_label_pattern", targetLabelPattern).put("target_subtree_pattern", targetSubtreePattern)
        .put("destination_pattern", destinationPattern)
        .put("required_anchor_pattern", requiredAnchorPattern)
        .put("return_transport", returnTransport)
        .put("expected_descendant_count", expectedDescendantCount)
        .put("excluded_descendant_resource_ids", JSONArray().apply {
            excludedDescendantResourceIds.sorted().forEach { put(it) }
        })
        .put("required_non_actionable_descendant_label_patterns", JSONArray().apply {
            requiredNonActionableDescendantLabelPatterns.sorted().forEach { put(it) }
        })
        .put("activation_owner_relation", activationOwnerRelation?.toJson() ?: JSONObject.NULL)
        .put("empty_state_signature", emptyStateSignature?.toJson() ?: JSONObject.NULL)
        .put("scenario_ids", JSONArray().apply { allowedScenarioIds.sorted().forEach { put(it) } })
        .put("evidence_refs", JSONArray().apply { evidenceRefs.sorted().forEach { put(it) } })
        .put("source_evidence_digest", sourceEvidenceDigest)
        requiredAnchorStructure?.let { canonicalPolicy.put("required_anchor_structure", it.toJson()) }
        return ExactProtocolJson.sha256(ExactProtocolJson.canonical(canonicalPolicy))
    }

    companion object {
        internal fun digestFor(
            id: String, effect: String, packageName: String, targetClassPattern: String,
            targetResourcePattern: String, targetLabelPattern: String, targetSubtreePattern: String,
            destinationPattern: String, requiredAnchorPattern: String, returnTransport: String,
            expectedDescendantCount: Int, excludedDescendantResourceIds: List<String>,
            requiredNonActionableDescendantLabelPatterns: List<String>, allowedScenarioIds: List<String>,
            evidenceRefs: List<String>, sourceEvidenceDigest: String,
            activationOwnerRelation: NavigationActivationOwnerRelation? = null,
            emptyStateSignature: NavigationEmptyStateSignature? = null,
            requiredAnchorStructure: NavigationAnchorStructure? = null,
        ): String = NavigationEffectContract(id, "", effect, packageName, targetClassPattern,
            targetResourcePattern, targetLabelPattern, targetSubtreePattern, destinationPattern,
            requiredAnchorPattern, returnTransport, expectedDescendantCount, excludedDescendantResourceIds,
            requiredNonActionableDescendantLabelPatterns, allowedScenarioIds, evidenceRefs,
            sourceEvidenceDigest, activationOwnerRelation, emptyStateSignature, requiredAnchorStructure)
            .canonicalDigest()
    }
}

/** Loads only locally packaged, reviewed policy. Caller data never supplies contract semantics. */
internal object NavigationEffectContractRegistry {
    private const val MAX_POLICY_BYTES = 64 * 1024
    private const val MAX_CONTRACTS = 64

    fun load(policyBytes: ByteArray): Map<String, NavigationEffectContract> {
        if (policyBytes.isEmpty() || policyBytes.size > MAX_POLICY_BYTES) return emptyMap()
        val raw = policyBytes.toString(Charsets.UTF_8)
        if (ExactNodeResolver.hasDuplicateJsonKey(raw)) return emptyMap()
        return runCatching {
            val root = JSONObject(raw)
            if (root.optString("schema") != "safe-navigation-contracts-v1" ||
                root.optBoolean("default_enabled", false)) return@runCatching emptyMap()
            val rows = root.optJSONArray("contracts") ?: return@runCatching emptyMap()
            if (rows.length() > MAX_CONTRACTS) return@runCatching emptyMap()
            val sourceDigest = sha256(policyBytes)
            val result = linkedMapOf<String, NavigationEffectContract>()
            for (index in 0 until rows.length()) {
                val row = rows.optJSONObject(index) ?: return@runCatching emptyMap()
                if (!row.optBoolean("enabled", false)) continue
                val id = row.optString("id").trim()
                val packageName = row.optString("package").trim()
                val resourceId = row.optString("resource_id").trim()
                val targetClass = row.optString("target_class_pattern").trim()
                val targetLabel = row.optString("label_pattern").trim()
                val targetSubtree = row.optString("target_subtree_pattern").trim()
                val destination = row.optString("destination_pattern").trim()
                val anchor = row.optString("required_anchor_pattern").trim()
                val returnTransport = row.optString("return_transport").trim()
                val expectedDescendantCount = row.optInt("expected_descendant_count", -1)
                val excludedChildrenArray = row.optJSONArray("excluded_descendant_resource_ids")
                    ?: return@runCatching emptyMap()
                val excludedChildren = (0 until excludedChildrenArray.length()).map {
                    excludedChildrenArray.optString(it).trim()
                }
                val nonActionableLabelsArray = row.optJSONArray("required_non_actionable_descendant_label_patterns")
                    ?: return@runCatching emptyMap()
                val nonActionableLabels = (0 until nonActionableLabelsArray.length()).map {
                    nonActionableLabelsArray.optString(it).trim()
                }
                val activationOwnerRelation = row.optJSONObject("activation_owner_relation")?.let { relation ->
                    NavigationActivationOwnerRelation(
                        kind = relation.optString("kind").trim(),
                        childIndex = relation.optInt("child_index", -1),
                        childClassPattern = relation.optString("child_class_pattern").trim(),
                        childResourceId = relation.optString("child_resource_id").trim(),
                    ).takeIf { it.isWellFormed() } ?: return@runCatching emptyMap()
                }
                val emptyStateSignature = row.optJSONObject("empty_state_signature")?.let { signature ->
                    NavigationEmptyStateSignature(
                        exactText = signature.optString("exact_text"),
                        rootClassName = signature.optString("root_class_name"),
                        containerClassName = signature.optString("container_class_name"),
                        containerResourceId = signature.optString("container_resource_id"),
                        webViewClassName = signature.optString("web_view_class_name"),
                        anchorClassName = signature.optString("anchor_class_name"),
                        anchorResourceId = signature.optString("anchor_resource_id"),
                        excludedClassName = signature.optString("excluded_class_name"),
                    ).takeIf { it.isWellFormed() } ?: return@runCatching emptyMap()
                }
                val requiredAnchorStructure = if (row.has("required_anchor_structure")) {
                    val structure = row.optJSONObject("required_anchor_structure")
                        ?: return@runCatching emptyMap()
                    NavigationAnchorStructure(
                        relation = structure.optString("relation").trim(),
                        nodeClassPattern = structure.optString("node_class_pattern").trim(),
                        parentClassPattern = structure.optString("parent_class_pattern").trim(),
                        parentResourceIdPattern = structure.optString("parent_resource_id_pattern").trim(),
                    ).takeIf { it.isWellFormed() } ?: return@runCatching emptyMap()
                } else null
                val effect = row.optString("effect").trim()
                val scenarioArray = row.optJSONArray("scenario_ids") ?: return@runCatching emptyMap()
                val scenarios = (0 until scenarioArray.length()).map { scenarioArray.optString(it).trim() }
                val evidenceArray = row.optJSONArray("evidence_refs") ?: return@runCatching emptyMap()
                val evidence = (0 until evidenceArray.length()).map { evidenceArray.optString(it).trim() }
                if (id.isBlank() || packageName.isBlank() || targetClass.isBlank() ||
                    targetLabel.isBlank() || targetSubtree.isBlank() || destination.isBlank() || anchor.isBlank() ||
                    returnTransport != "BACK" || expectedDescendantCount !in 0..100 ||
                    !((expectedDescendantCount == 0 && excludedChildren.isEmpty() && nonActionableLabels.isEmpty()) ||
                        (expectedDescendantCount > 0 && excludedChildren.isNotEmpty() && nonActionableLabels.isNotEmpty())) ||
                    excludedChildren.any { it.isBlank() } ||
                    excludedChildren.distinct().size != excludedChildren.size ||
                    nonActionableLabels.any { it.isBlank() } ||
                    scenarios.isEmpty() || scenarios.any { it.isBlank() } || scenarios.distinct().size != scenarios.size ||
                    effect != "read_only_navigation" || evidence.isEmpty() || evidence.any { it.isBlank() } ||
                    result.containsKey(id)) return@runCatching emptyMap()
                val targetResource = "^${Regex.escape(resourceId)}$"
                val digest = NavigationEffectContract.digestFor(id, effect, packageName, targetClass,
                    targetResource, targetLabel, targetSubtree, destination, anchor, returnTransport,
                    expectedDescendantCount, excludedChildren, nonActionableLabels, scenarios, evidence, sourceDigest,
                    activationOwnerRelation, emptyStateSignature, requiredAnchorStructure)
                val contract = NavigationEffectContract(id, digest, effect, packageName, targetClass,
                    targetResource, targetLabel, targetSubtree, destination, anchor, returnTransport,
                    expectedDescendantCount, excludedChildren, nonActionableLabels, scenarios, evidence, sourceDigest,
                    activationOwnerRelation, emptyStateSignature, requiredAnchorStructure)
                if (!contract.isWellFormed(digest)) return@runCatching emptyMap()
                result[id] = contract
            }
            result.toMap()
        }.getOrDefault(emptyMap())
    }

    private fun sha256(bytes: ByteArray): String = java.security.MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }
}

internal data class NavigationClickEvidence(
    val requestId: String,
    val transactionId: String,
    val serviceInstanceId: String,
    val connectionId: String,
    val windowId: Int,
    val eventType: Int,
    val eventElapsedRealtimeMs: Long,
    val source: Any?,
    val callbackSourceObservation: NavigationCallbackSourceObservation? = null,
)

/** One early, text-free source observation shared by the strict click verifier and evidence adapters. */
internal data class NavigationCallbackSourceObservation(
    val requestId: String,
    val transactionId: String,
    val serviceInstanceId: String,
    val connectionId: String,
    val eventType: Int,
    val eventWindowId: Int,
    val eventUptimeMs: Long,
    val eventElapsedRealtimeMs: Long,
    val callbackElapsedRealtimeMs: Long,
    val dispatchElapsedRealtimeMs: Long,
    val dispatchDeadlineElapsedRealtimeMs: Long,
    val source: AccessibilityNodeInfo?,
    val sourceReadStatus: String,
    val sourceWindowId: Int?,
    val sourceWindowStatus: String,
    val sourceNodeIdStatus: String,
    val sourceResourceIdStatus: String,
    val sourceClassNameStatus: String,
    val sourceOwnerExactAtCallback: Boolean,
) {
    fun matches(event: AccessibilityEvent, binding: NavigationActionBinding,
        currentServiceInstanceId: String, currentConnectionId: String): Boolean =
        matches(event, binding.requestId, binding.transactionId, currentServiceInstanceId, currentConnectionId)

    fun matches(event: AccessibilityEvent, expectedRequestId: String, expectedTransactionId: String,
        currentServiceInstanceId: String, currentConnectionId: String): Boolean =
        eventElapsedRealtimeMs >= 0L && requestId == expectedRequestId &&
            transactionId == expectedTransactionId && serviceInstanceId == currentServiceInstanceId &&
            connectionId == currentConnectionId && eventType == event.eventType &&
            eventWindowId == event.windowId && eventUptimeMs == event.eventTime

    fun toJson(firstClickSelected: Boolean, strictSourceOwnerExact: Boolean, firstFailureCheck: String): JSONObject =
        JSONObject().put("schema", "navigation-click-source-v1")
            .put("request_id", requestId).put("transaction_id", transactionId)
            .put("service_instance_id", serviceInstanceId).put("connection_id", connectionId)
            .put("event_type", eventType).put("event_window_id", eventWindowId)
            .put("event_elapsed_realtime_ms", eventElapsedRealtimeMs)
            .put("callback_elapsed_realtime_ms", callbackElapsedRealtimeMs)
            .put("dispatch_elapsed_realtime_ms", dispatchElapsedRealtimeMs)
            .put("dispatch_deadline_elapsed_realtime_ms", dispatchDeadlineElapsedRealtimeMs)
            .put("callback_source_status", sourceReadStatus)
            .put("callback_source_window_id", sourceWindowId ?: JSONObject.NULL)
            .put("callback_source_window_status", sourceWindowStatus)
            .put("callback_source_node_id_status", sourceNodeIdStatus)
            .put("callback_source_resource_id_status", sourceResourceIdStatus)
            .put("callback_source_class_name_status", sourceClassNameStatus)
            .put("callback_source_owner_exact", sourceOwnerExactAtCallback)
            .put("first_click_selected", firstClickSelected)
            .put("strict_source_status", if (source == null) "FIELD_ABSENT" else "FIELD_PRESENT")
            .put("strict_source_owner_exact", strictSourceOwnerExact)
            .put("first_failure_check", firstFailureCheck)
}

internal fun matchingNavigationCallbackSourceObservation(
    observation: NavigationCallbackSourceObservation?,
    event: AccessibilityEvent,
    requestId: String,
    transactionId: String,
    serviceInstanceId: String,
    connectionId: String,
): NavigationCallbackSourceObservation? = observation?.takeIf {
    it.matches(event, requestId, transactionId, serviceInstanceId, connectionId)
}

internal fun navigationClickElapsedRealtimeMs(
    observation: NavigationCallbackSourceObservation?,
    event: AccessibilityEvent,
    requestId: String,
    transactionId: String,
    serviceInstanceId: String,
    connectionId: String,
    legacyTimestamp: () -> Long?,
): Long? = if (observation == null) {
    legacyTimestamp()
} else {
    matchingNavigationCallbackSourceObservation(
        observation, event, requestId, transactionId, serviceInstanceId, connectionId,
    )?.eventElapsedRealtimeMs
}

internal fun captureNavigationCallbackSourceObservation(
    binding: NavigationActionBinding,
    target: NavigationActionTargetLease,
    event: AccessibilityEvent,
    currentServiceInstanceId: String,
    currentConnectionId: String,
    dispatchElapsedRealtimeMs: Long,
    dispatchDeadlineElapsedRealtimeMs: Long,
    readSource: () -> AccessibilityNodeInfo? = { event.source },
): NavigationCallbackSourceObservation {
    val callbackElapsed = SystemClock.elapsedRealtime()
    val sourceResult = runCatching(readSource)
    val source = sourceResult.getOrNull()
    fun fieldStatus(read: () -> String?): String = when {
        sourceResult.isFailure -> "READ_FAILED"
        source == null -> "FIELD_ABSENT"
        else -> runCatching(read).fold(
            { value -> if (value.isNullOrBlank()) "FIELD_ABSENT" else "FIELD_PRESENT" },
            { "READ_FAILED" },
        )
    }
    val sourceWindowResult = if (source == null) null else runCatching { source.windowId }
    val sourceWindowId = sourceWindowResult?.getOrNull()?.takeIf { it >= 0 }
    val eventElapsed = A11yEvidence.eventTimeElapsedRealtimeMs(
        event.eventTime, callbackElapsed, SystemClock.uptimeMillis()) ?: -1L
    return NavigationCallbackSourceObservation(
        requestId = binding.requestId,
        transactionId = binding.transactionId,
        serviceInstanceId = currentServiceInstanceId,
        connectionId = currentConnectionId,
        eventType = event.eventType,
        eventWindowId = event.windowId,
        eventUptimeMs = event.eventTime,
        eventElapsedRealtimeMs = eventElapsed,
        callbackElapsedRealtimeMs = callbackElapsed,
        dispatchElapsedRealtimeMs = dispatchElapsedRealtimeMs,
        dispatchDeadlineElapsedRealtimeMs = dispatchDeadlineElapsedRealtimeMs,
        source = source,
        sourceReadStatus = when {
            sourceResult.isFailure -> "READ_FAILED"
            source == null -> "FIELD_ABSENT"
            else -> "FIELD_PRESENT"
        },
        sourceWindowId = sourceWindowId,
        sourceWindowStatus = when {
            source == null -> "FIELD_ABSENT"
            sourceWindowResult?.isFailure == true -> "READ_FAILED"
            sourceWindowId == null -> "FIELD_ABSENT"
            else -> "FIELD_PRESENT"
        },
        sourceNodeIdStatus = when {
            source == null -> "FIELD_ABSENT"
            Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU -> "UNSUPPORTED_API"
            else -> fieldStatus { source.uniqueId }
        },
        sourceResourceIdStatus = fieldStatus { source?.viewIdResourceName },
        sourceClassNameStatus = fieldStatus { source?.className?.toString() },
        sourceOwnerExactAtCallback = runCatching {
            target.eventSourceMatches(source, event.windowId, currentConnectionId)
        }.getOrDefault(false),
    )
}

internal fun navigationClickSourceFirstFailureCheck(
    binding: NavigationActionBinding,
    click: NavigationClickEvidence,
    currentConnectionId: String,
    strictSourceOwnerExact: Boolean,
): String = when {
    click.requestId != binding.requestId -> "REQUEST_ID_MISMATCH"
    click.transactionId != binding.transactionId -> "TRANSACTION_ID_MISMATCH"
    click.serviceInstanceId != binding.serviceInstanceId -> "SERVICE_INSTANCE_MISMATCH"
    click.connectionId != binding.connectionId || currentConnectionId != binding.connectionId -> "CONNECTION_MISMATCH"
    click.windowId != binding.windowId -> "ACTION_WINDOW_MISMATCH"
    click.eventType != AccessibilityEvent.TYPE_VIEW_CLICKED -> "EVENT_TYPE_MISMATCH"
    click.eventElapsedRealtimeMs < 0L -> "EVENT_TIME_UNAVAILABLE"
    click.callbackSourceObservation?.let {
        click.eventElapsedRealtimeMs < it.dispatchElapsedRealtimeMs ||
            click.eventElapsedRealtimeMs > it.dispatchDeadlineElapsedRealtimeMs
    } == true -> "EVENT_OUTSIDE_DISPATCH"
    click.callbackSourceObservation?.sourceReadStatus == "READ_FAILED" -> "CALLBACK_SOURCE_READ_FAILED"
    click.source == null && click.callbackSourceObservation != null -> "CALLBACK_SOURCE_ABSENT"
    click.source == null -> "VERIFIER_SOURCE_ABSENT"
    !strictSourceOwnerExact -> "SOURCE_OWNER_MISMATCH"
    else -> "NONE"
}

internal fun navigationClickSourceDiagnostics(
    binding: NavigationActionBinding,
    click: NavigationClickEvidence,
    currentConnectionId: String,
    strictSourceOwnerExact: Boolean,
): JSONObject {
    val firstFailure = navigationClickSourceFirstFailureCheck(
        binding, click, currentConnectionId, strictSourceOwnerExact)
    val observation = click.callbackSourceObservation
    val result = observation?.toJson(
        firstClickSelected = true,
        strictSourceOwnerExact = strictSourceOwnerExact,
        firstFailureCheck = firstFailure,
    ) ?: JSONObject().put("schema", "navigation-click-source-v1")
        .put("request_id", click.requestId).put("transaction_id", click.transactionId)
        .put("service_instance_id", click.serviceInstanceId).put("connection_id", click.connectionId)
        .put("event_type", click.eventType).put("event_window_id", click.windowId)
        .put("event_elapsed_realtime_ms", click.eventElapsedRealtimeMs)
        .put("callback_elapsed_realtime_ms", JSONObject.NULL)
        .put("dispatch_elapsed_realtime_ms", JSONObject.NULL)
        .put("dispatch_deadline_elapsed_realtime_ms", JSONObject.NULL)
        .put("callback_source_status", "NOT_CAPTURED")
        .put("callback_source_window_id", JSONObject.NULL)
        .put("callback_source_window_status", "NOT_CAPTURED")
        .put("callback_source_node_id_status", "NOT_CAPTURED")
        .put("callback_source_resource_id_status", "NOT_CAPTURED")
        .put("callback_source_class_name_status", "NOT_CAPTURED")
        .put("callback_source_owner_exact", false)
        .put("first_click_selected", true)
        .put("strict_source_status", if (click.source == null) "FIELD_ABSENT" else "FIELD_PRESENT")
        .put("strict_source_owner_exact", strictSourceOwnerExact)
        .put("first_failure_check", firstFailure)
    return result.put("request_binding_match", click.requestId == binding.requestId)
        .put("transaction_binding_match", click.transactionId == binding.transactionId)
        .put("service_binding_match", click.serviceInstanceId == binding.serviceInstanceId)
        .put("connection_binding_match", click.connectionId == binding.connectionId &&
            currentConnectionId == binding.connectionId)
        .put("action_window_match", click.windowId == binding.windowId)
        .put("dispatch_window_match", click.callbackSourceObservation?.let {
            click.eventElapsedRealtimeMs in it.dispatchElapsedRealtimeMs..it.dispatchDeadlineElapsedRealtimeMs
        } ?: (click.eventElapsedRealtimeMs >= 0L))
}

/** Binds a captured post window to the exact click and transaction that authorized the action. */
internal data class NavigationPostWindowAuthority(
    val requestId: String,
    val transactionId: String,
    val serviceInstanceId: String,
    val connectionId: String,
    val actionWindowId: Int,
    val clickWindowId: Int,
    val clickEventType: Int,
    val clickEventElapsedRealtimeMs: Long,
    val postWindowId: Int,
    val activeType1WindowIds: List<Int>,
    val observedAtUptimeMs: Long,
    val rootWindowId: Int,
    val rootPackageName: String?,
    val rootClassName: String?,
) {
    fun matches(
        binding: NavigationActionBinding,
        click: NavigationClickEvidence,
        post: NavigationPostActionEvidence,
        contract: NavigationEffectContract,
        dispatchElapsedRealtimeMs: Long,
        deadlineElapsedRealtimeMs: Long,
    ): Boolean = requestId == binding.requestId && transactionId == binding.transactionId &&
        serviceInstanceId == binding.serviceInstanceId && connectionId == binding.connectionId &&
        actionWindowId == binding.windowId && clickWindowId == binding.windowId &&
        click.windowId == binding.windowId && click.requestId == binding.requestId &&
        click.transactionId == binding.transactionId && click.serviceInstanceId == binding.serviceInstanceId &&
        click.connectionId == binding.connectionId && clickEventType == AccessibilityEvent.TYPE_VIEW_CLICKED &&
        click.eventType == clickEventType && clickEventElapsedRealtimeMs == click.eventElapsedRealtimeMs &&
        clickEventElapsedRealtimeMs in dispatchElapsedRealtimeMs..deadlineElapsedRealtimeMs &&
        postWindowId == post.windowId && rootWindowId == postWindowId &&
        activeType1WindowIds.size == 1 && activeType1WindowIds.distinct().size == 1 &&
        activeType1WindowIds.single() == postWindowId && observedAtUptimeMs >= clickEventElapsedRealtimeMs &&
        observedAtUptimeMs <= post.capturedAtUptimeMs && post.capturedAtUptimeMs <= deadlineElapsedRealtimeMs &&
        rootPackageName == contract.packageName && post.rootPackageName == rootPackageName &&
        rootClassName == post.rootClassName && rootClassName?.isNotBlank() == true

    fun toJson(): JSONObject = JSONObject().put("schema", "navigation-post-window-authority-v1")
        .put("request_id", requestId).put("transaction_id", transactionId)
        .put("service_instance_id", serviceInstanceId).put("connection_id", connectionId)
        .put("action_window_id", actionWindowId).put("click_window_id", clickWindowId)
        .put("click_event_type", clickEventType)
        .put("click_event_elapsed_realtime_ms", clickEventElapsedRealtimeMs)
        .put("post_window_id", postWindowId).put("active_type1_window_ids", JSONArray().apply {
            activeType1WindowIds.take(16).forEach { put(it) }
        }).put("observed_at_elapsed_realtime_ms", observedAtUptimeMs)
        .put("root_window_id", rootWindowId).put("root_package_name", rootPackageName ?: JSONObject.NULL)
        .put("root_class_name", rootClassName ?: JSONObject.NULL)
}

/** Focus and labels must all come from the same fresh post-action hierarchy capture. */
internal data class NavigationPostActionEvidence(
    val requestId: String,
    val transactionId: String,
    val serviceInstanceId: String,
    val connectionId: String,
    val windowId: Int,
    val captureId: String,
    val capturedAtUptimeMs: Long,
    val hierarchyDigest: String,
    val labels: List<String>,
    val focusWindowId: Int?,
    val accessibilityFocused: Boolean,
    val focusInCurrentHierarchy: Boolean,
    val nodeCount: Int = 0,
    val rootPackageName: String? = null,
    val rootClassName: String? = null,
    val captureSample: NavigationPostCaptureArtifact? = null,
    val postWindowAuthority: NavigationPostWindowAuthority? = null,
    val structureEvidence: NavigationPostStructureEvidence? = null,
    val destinationAnchorTarget: NavigationActionTargetLease? = null,
    val destinationAnchorResolutionFailureCode: String? = null,
)

internal fun navigationFocusTargetActionsAllowed(
    clickRequired: Boolean,
    hasClickAction: Boolean,
    hasAccessibilityFocusAction: Boolean,
): Boolean = hasAccessibilityFocusAction && (!clickRequired || hasClickAction)

internal fun navigationPostCaptureSampleReady(
    hierarchyChanged: Boolean,
    destinationMatches: Boolean,
    anchorMatchCount: Int,
    emptyStateAnchorRequired: Boolean,
    structuralAnchorRequired: Boolean,
    focusInCurrentHierarchy: Boolean,
    destinationAnchorTargetAvailable: Boolean,
): Boolean {
    if (!hierarchyChanged || !destinationMatches || anchorMatchCount != 1) return false
    if (emptyStateAnchorRequired) return true
    if (structuralAnchorRequired) return focusInCurrentHierarchy || destinationAnchorTargetAvailable
    return true
}

/** Redacted facts collected from the existing post-action diagnostic poll loop. */
internal data class NavigationPostCaptureWindowObservation(
    val windowId: Int,
    val type: Int,
    val active: Boolean,
)

internal class NavigationPostCapturePollTrace(private val binding: NavigationActionBinding) {
    private data class WindowState(
        var lastActive: Boolean,
        var activeObservations: Int = 0,
        var inactiveObservations: Int = 0,
    )

    companion object {
        private const val MAX_WINDOW_IDS = 16
        private val ALLOWED_SKIP_REASONS = setOf(
            "ACTION_WINDOW_NOT_ACTIVE_TYPE1", "ACTION_WINDOW_ACTIVE_TYPE1_AMBIGUOUS",
            "ROOT_MISSING", "TREE_INCOMPLETE", "IMMUTABLE_CAPTURE_UNAVAILABLE",
            "COMPLETE_SAMPLE_NOT_VERIFIED", "ACTIVE_TYPE1_WINDOW_AMBIGUOUS",
            "ACTIVE_TYPE1_WINDOW_UNAVAILABLE", "POST_WINDOW_ROOT_MISMATCH",
            "POST_WINDOW_PACKAGE_MISMATCH",
        )
    }

    private var attemptCount = 0
    private var completeSampleCount = 0
    private var firstAttemptElapsedRealtimeMs: Long? = null
    private var lastAttemptElapsedRealtimeMs: Long? = null
    private var lastCompleteSampleElapsedRealtimeMs: Long? = null
    private val skipReasonCounts = linkedMapOf<String, Int>()
    private val windowStates = linkedMapOf<Int, WindowState>()
    private val activeWindowIds = linkedSetOf<Int>()
    private var omittedWindowStateCount = 0
    private var omittedActiveWindowIdCount = 0
    private var rootPackageName: String? = null
    private var rootClassName: String? = null
    private var serviceChanged = false
    private var serviceChangeElapsedRealtimeMs: Long? = null
    private var deadlineReached = false
    private var deadlineElapsedRealtimeMs: Long? = null
    private var terminationStage = "POLLING"

    fun beginAttempt(elapsedRealtimeMs: Long) {
        attemptCount++
        if (firstAttemptElapsedRealtimeMs == null) firstAttemptElapsedRealtimeMs = elapsedRealtimeMs
        lastAttemptElapsedRealtimeMs = elapsedRealtimeMs
    }

    fun observeWindows(observations: List<NavigationPostCaptureWindowObservation>) {
        observations.asSequence().filter { it.type == 1 }
            .sortedBy { if (it.windowId == binding.windowId) 0 else 1 }
            .forEach { observation ->
                val state = windowStates[observation.windowId] ?: run {
                    if (windowStates.size >= MAX_WINDOW_IDS) {
                        omittedWindowStateCount++
                        return@forEach
                    }
                    WindowState(observation.active).also { windowStates[observation.windowId] = it }
                }
                state.lastActive = observation.active
                if (observation.active) {
                    state.activeObservations++
                    if (observation.windowId !in activeWindowIds) {
                        if (activeWindowIds.size < MAX_WINDOW_IDS) activeWindowIds.add(observation.windowId)
                        else omittedActiveWindowIdCount++
                    }
                } else state.inactiveObservations++
            }
    }

    fun skip(reason: String) {
        if (reason in ALLOWED_SKIP_REASONS) skipReasonCounts[reason] = (skipReasonCounts[reason] ?: 0) + 1
    }

    fun recordCompleteSample(elapsedRealtimeMs: Long, packageName: String?, className: String?) {
        completeSampleCount++
        lastCompleteSampleElapsedRealtimeMs = elapsedRealtimeMs
        rootPackageName = packageName?.take(256)
        rootClassName = className?.take(256)
    }

    fun markServiceChanged(elapsedRealtimeMs: Long) {
        serviceChanged = true
        serviceChangeElapsedRealtimeMs = elapsedRealtimeMs
        terminationStage = "SERVICE_CHANGED_DURING_POLL"
    }

    fun markSampleAccepted() {
        terminationStage = "DESTINATION_AND_ANCHOR_SAMPLE_SELECTED"
    }

    fun markDeadlineReached(elapsedRealtimeMs: Long) {
        deadlineReached = true
        deadlineElapsedRealtimeMs = elapsedRealtimeMs
        terminationStage = "POST_CAPTURE_DEADLINE_REACHED"
    }

    fun toJson(): JSONObject {
        val windowRows = JSONArray().apply {
            windowStates.toSortedMap().forEach { (id, state) ->
                put(JSONObject().put("window_id", id).put("last_active", state.lastActive)
                    .put("active_observation_count", state.activeObservations)
                    .put("inactive_observation_count", state.inactiveObservations))
            }
        }
        val activeIds = JSONArray().apply { activeWindowIds.forEach { id -> put(id) } }
        val skips = JSONObject().apply { skipReasonCounts.forEach { (reason, count) -> put(reason, count) } }
        return JSONObject().put("schema", "navigation-post-capture-poll-v1")
            .put("request_id", binding.requestId).put("transaction_id", binding.transactionId)
            .put("service_instance_id", binding.serviceInstanceId).put("connection_id", binding.connectionId)
            .put("action_window_id", binding.windowId)
            .put("attempt_count", attemptCount).put("complete_sample_count", completeSampleCount)
            .put("first_attempt_elapsed_realtime_ms", firstAttemptElapsedRealtimeMs ?: JSONObject.NULL)
            .put("last_attempt_elapsed_realtime_ms", lastAttemptElapsedRealtimeMs ?: JSONObject.NULL)
            .put("last_complete_sample_elapsed_realtime_ms", lastCompleteSampleElapsedRealtimeMs ?: JSONObject.NULL)
            .put("observed_type1_window_states", windowRows)
            .put("observed_active_type1_window_ids", activeIds)
            .put("omitted_window_state_count", omittedWindowStateCount)
            .put("omitted_active_window_id_count", omittedActiveWindowIdCount)
            .put("skip_reason_counts", skips).put("service_changed", serviceChanged)
            .put("service_change_elapsed_realtime_ms", serviceChangeElapsedRealtimeMs ?: JSONObject.NULL)
            .put("deadline_reached", deadlineReached)
            .put("deadline_elapsed_realtime_ms", deadlineElapsedRealtimeMs ?: JSONObject.NULL)
            .put("termination_stage", terminationStage)
            .put("root_package_name", rootPackageName ?: JSONObject.NULL)
            .put("root_class_name", rootClassName ?: JSONObject.NULL)
    }
}

/** Bounded, text-redacted projection of the exact immutable tree used for the post-capture digest. */
internal data class NavigationPostCaptureArtifact(
    val payload: JSONObject,
    val sha256: String,
    val byteCount: Int,
    val completeness: String,
    val nodeCount: Int,
    val persistedNodeCount: Int,
    val requiredAnchorStructuralMatchCount: Int? = null,
) {
    fun requiredAnchorStructuralMatchPaths(): List<List<Int>> {
        val nodes = payload.optJSONArray("nodes") ?: return emptyList()
        val paths = mutableListOf<List<Int>>()
        for (nodeIndex in 0 until nodes.length()) {
            val node = nodes.optJSONObject(nodeIndex) ?: return emptyList()
            val matchIds = node.optJSONArray("diagnostic_policy_match_ids") ?: continue
            val markerCount = (0 until matchIds.length()).count {
                matchIds.optString(it) == "required_anchor_structural_match"
            }
            if (markerCount == 0) continue
            if (markerCount != 1) return emptyList()
            val pathJson = node.optJSONArray("path") ?: return emptyList()
            if (pathJson.length() !in 1..80) return emptyList()
            val path = mutableListOf<Int>()
            for (index in 0 until pathJson.length()) {
                val raw = pathJson.opt(index)
                if (raw !is Number) return emptyList()
                val value = raw.toDouble()
                if (!value.isFinite() || value % 1.0 != 0.0 || value !in 0.0..4096.0) return emptyList()
                path += value.toInt()
            }
            paths += path
        }
        return paths
    }

    fun toJson(): JSONObject = JSONObject()
        .put("result_channel", "NAVIGATION_ACTION_RESULT")
        .put("request_id", payload.optString("request_id"))
        .put("receipt_field", "receipt.post_state_diagnostics.post_capture_sample_artifact.payload")
        .put("artifact_sha256", sha256)
        .put("artifact_bytes", byteCount)
        .put("completeness", completeness)
        .put("node_count", nodeCount)
        .put("persisted_node_count", persistedNodeCount)
        .put("payload", JSONObject(payload.toString()))

    companion object {
        private const val MAX_NODES = 256
        private const val MAX_BYTES = 48 * 1024
        private const val MAX_DIAGNOSTIC_POLICY_SOURCES = 8

        fun fromCapture(
            capture: ImmutableHierarchyCapture,
            requestId: String,
            transactionId: String,
            serviceInstanceId: String,
            connectionId: String,
            windowId: Int,
            captureId: String,
            capturedAtUptimeMs: Long,
            hierarchyDigest: String,
            contract: NavigationEffectContract,
            scenarioId: String? = null,
            diagnosticPolicyContracts: Collection<NavigationEffectContract> = emptyList(),
        ): NavigationPostCaptureArtifact {
            val diagnosticPolicies = diagnosticPolicyContracts.asSequence()
                .filter { source -> source.id != contract.id && source.packageName == contract.packageName &&
                    scenarioId != null && source.allowsScenario(scenarioId) &&
                    source.emptyStateSignature != null && source.isWellFormed(source.digest) }
                .distinctBy { it.id }
                .sortedBy { it.id }
                .take(MAX_DIAGNOSTIC_POLICY_SOURCES)
                .toList()
            val destinationRegex = Regex(contract.destinationPattern, RegexOption.IGNORE_CASE)
            val anchorRegex = Regex(contract.requiredAnchorPattern, RegexOption.IGNORE_CASE)
            val nodes = JSONArray()
            var nodeLimitReached = false
            var actionLimitReached = false
            var structuralAnchorMatchCount = 0
            val identityLimitReached = listOf(requestId, transactionId, serviceInstanceId, connectionId, captureId)
                .any { it.length > 256 }

            fun append(
                node: CapturedHierarchyNode,
                parentIndex: Int?,
                path: List<Int>,
                parentNode: CapturedHierarchyNode?,
            ) {
                if (nodes.length() >= MAX_NODES) {
                    nodeLimitReached = true
                    return
                }
                val labels = listOfNotNull(node.text, node.contentDescription, node.resourceId)
                val textLabels = listOfNotNull(node.text, node.contentDescription)
                val actions = node.actions.take(64)
                if (actions.size != node.actions.size) actionLimitReached = true
                val stateSignature = contract.emptyStateSignature
                val anchorCandidate = stateSignature != null &&
                    node.className == stateSignature.anchorClassName &&
                    node.resourceId == stateSignature.anchorResourceId
                val semanticAnchorLabelMatch = anchorCandidate && textLabels.any(anchorRegex::matches)
                val requiredAnchorLabelMatch = textLabels.any(anchorRegex::matches)
                val requiredAnchorStructuralMatch = requiredAnchorLabelMatch &&
                    contract.requiredAnchorStructure?.matches(
                        node, parentNode, contract.packageName, windowId) == true
                if (requiredAnchorStructuralMatch) structuralAnchorMatchCount++
                val diagnosticMatchIds = JSONArray().apply {
                    if (labels.any(destinationRegex::containsMatchIn)) put("destination_label")
                    if (stateSignature != null && textLabels.any { it == stateSignature.exactText }) {
                        put("empty_state_exact_text")
                    }
                    if (requiredAnchorLabelMatch) put("required_anchor_label")
                    if (requiredAnchorStructuralMatch) put("required_anchor_structural_match")
                    if (anchorCandidate) put("empty_state_anchor_candidate")
                    if (semanticAnchorLabelMatch && node.enabled && node.visibleToUser && node.clickable &&
                        node.actions.any { it.id == AccessibilityNodeInfo.ACTION_CLICK }) {
                        put("empty_state_anchor_semantic_click_target")
                    }
                }
                val diagnosticPolicyMatches = JSONArray()
                diagnosticPolicies.forEach { source ->
                    if (node.packageName != source.packageName) return@forEach
                    val signature = source.emptyStateSignature ?: return@forEach
                    val sourceAnchorCandidate = node.className == signature.anchorClassName &&
                        node.resourceId == signature.anchorResourceId
                    val sourceExactTextMatch = textLabels.any { it == signature.exactText }
                    val sourceSemanticAnchorMatch = sourceAnchorCandidate && textLabels.any { label ->
                        Regex(source.requiredAnchorPattern, RegexOption.IGNORE_CASE).matches(label)
                    }
                    val sourceMatchIds = JSONArray().apply {
                        if (sourceExactTextMatch) put("empty_state_exact_text")
                        if (sourceSemanticAnchorMatch) put("required_anchor_label")
                        if (sourceAnchorCandidate) put("empty_state_anchor_candidate")
                        if (sourceSemanticAnchorMatch && node.enabled && node.visibleToUser && node.clickable &&
                            node.actions.any { it.id == AccessibilityNodeInfo.ACTION_CLICK }) {
                            put("empty_state_anchor_semantic_click_target")
                        }
                    }
                    if (sourceMatchIds.length() > 0) {
                        val sourceMatch = JSONObject()
                            .put("contract_id", source.id)
                            .put("contract_digest", source.digest)
                            .put("match_ids", sourceMatchIds)
                        if (sourceAnchorCandidate) {
                            sourceMatch.put("anchor_semantic_status",
                                if (sourceSemanticAnchorMatch) "POLICY_LABEL_MATCH" else "UNKNOWN")
                        }
                        diagnosticPolicyMatches.put(sourceMatch)
                    }
                }
                val bounds = JSONArray().put(node.bounds.left).put(node.bounds.top)
                    .put(node.bounds.right).put(node.bounds.bottom)
                val summary = JSONObject()
                    .put("id", node.stableIndex)
                    .put("parent_id", parentIndex ?: JSONObject.NULL)
                    .put("child_index", node.childIndex ?: JSONObject.NULL)
                    .put("path", JSONArray(path))
                    .put("class_name", node.className?.take(256) ?: JSONObject.NULL)
                    .put("package_name", node.packageName?.take(256) ?: JSONObject.NULL)
                    .put("resource_id", node.resourceId?.take(256) ?: JSONObject.NULL)
                    .put("window_id", node.windowId)
                    .put("bounds", bounds)
                    .put("text_present", !node.text.isNullOrEmpty())
                    .put("content_description_present", !node.contentDescription.isNullOrEmpty())
                    .put("resource_id_present", !node.resourceId.isNullOrEmpty())
                    .put("clickable", node.clickable)
                    .put("enabled", node.enabled)
                    .put("focusable", node.focusable)
                    .put("focused", node.focused)
                    .put("accessibility_focused", node.accessibilityFocused)
                    .put("selected", node.selected)
                    .put("scrollable", node.scrollable)
                    .put("visible_to_user", node.visibleToUser)
                    .put("action_ids", JSONArray().apply { actions.forEach { put(it.id) } })
                    .put("action_count", node.actions.size)
                    .put("action_ids_complete", actions.size == node.actions.size)
                    .put("destination_label_match", labels.any { destinationRegex.containsMatchIn(it) })
                    .put("required_anchor_match_count", labels.sumOf { label ->
                        anchorRegex.findAll(label).count()
                    })
                if (diagnosticMatchIds.length() > 0) {
                    summary.put("diagnostic_policy_match_ids", diagnosticMatchIds)
                }
                if (diagnosticPolicyMatches.length() > 0) {
                    summary.put("diagnostic_policy_matches", diagnosticPolicyMatches)
                }
                if (anchorCandidate) {
                    summary.put("diagnostic_anchor_semantic_status",
                        if (semanticAnchorLabelMatch) "POLICY_LABEL_MATCH" else "UNKNOWN")
                }
                nodes.put(summary)
                node.children.forEach { child ->
                    append(child, node.stableIndex, path + (child.childIndex ?: 0), node)
                }
            }

            append(capture.root, null, emptyList(), null)
            var completeness = when {
                identityLimitReached -> "INCOMPLETE_IDENTITY_LIMIT"
                nodeLimitReached || nodes.length() != capture.nodeCount -> "INCOMPLETE_NODE_LIMIT"
                actionLimitReached -> "INCOMPLETE_ACTION_LIMIT"
                else -> "COMPLETE"
            }
            fun payload(): JSONObject {
                val body = JSONObject()
                    .put("schema", "strict-post-capture-redacted-v1")
                    .put("request_id", requestId.take(256))
                    .put("transaction_id", transactionId.take(256))
                    .put("service_instance_id", serviceInstanceId.take(256))
                    .put("connection_id", connectionId.take(256))
                    .put("window_id", windowId)
                    .put("capture_id", captureId.take(256))
                    .put("captured_at_elapsed_realtime_ms", capturedAtUptimeMs)
                    .put("hierarchy_digest", hierarchyDigest)
                    .put("diagnostic_only", true)
                    .put("effect_contract_id", contract.id)
                    .put("node_count", capture.nodeCount)
                    .put("persisted_node_count", nodes.length())
                    .put("completeness", completeness)
                    .put("omitted_fields", JSONArray(listOf(
                        "text", "contentDescription", "action_labels", "sourceNodeId",
                    )))
                    .put("nodes", nodes)
                if (contract.requiredAnchorStructure != null) {
                    body.put("required_anchor_structural_match_count",
                        if (completeness == "COMPLETE") structuralAnchorMatchCount else JSONObject.NULL)
                }
                return body
            }

            var body = payload()
            var canonical = ExactProtocolJson.canonical(body)
            while (canonical.toByteArray(Charsets.UTF_8).size > MAX_BYTES && nodes.length() > 1) {
                nodes.remove(nodes.length() - 1)
                completeness = "INCOMPLETE_SIZE_LIMIT"
                body = payload()
                canonical = ExactProtocolJson.canonical(body)
            }
            val bytes = canonical.toByteArray(Charsets.UTF_8).size
            if (bytes > MAX_BYTES) completeness = "INCOMPLETE_SIZE_LIMIT"
            if (body.optString("completeness") != completeness) {
                body.put("completeness", completeness)
                body.put("persisted_node_count", nodes.length())
                canonical = ExactProtocolJson.canonical(body)
            }
            if (canonical.toByteArray(Charsets.UTF_8).size > MAX_BYTES) {
                completeness = "INCOMPLETE_SIZE_LIMIT"
                body = JSONObject()
                    .put("schema", "strict-post-capture-redacted-v1")
                    .put("request_id", requestId.take(256))
                    .put("transaction_id", transactionId.take(256))
                    .put("service_instance_id", serviceInstanceId.take(256))
                    .put("connection_id", connectionId.take(256))
                    .put("window_id", windowId)
                    .put("capture_id", captureId.take(256))
                    .put("captured_at_elapsed_realtime_ms", capturedAtUptimeMs)
                    .put("hierarchy_digest", hierarchyDigest)
                    .put("diagnostic_only", true)
                    .put("effect_contract_id", contract.id)
                    .put("node_count", capture.nodeCount)
                    .put("persisted_node_count", 0)
                    .put("completeness", completeness)
                    .put("omitted_fields", JSONArray(listOf(
                        "text", "contentDescription", "action_labels", "sourceNodeId", "node_summary_size_limit",
                    )))
                    .put("nodes", JSONArray())
                if (contract.requiredAnchorStructure != null) {
                    body.put("required_anchor_structural_match_count", JSONObject.NULL)
                }
                nodes.length().let { count -> for (index in count - 1 downTo 0) nodes.remove(index) }
                canonical = ExactProtocolJson.canonical(body)
            }
            val finalBytes = canonical.toByteArray(Charsets.UTF_8).size
            return NavigationPostCaptureArtifact(
                payload = body,
                sha256 = ExactProtocolJson.sha256(canonical),
                byteCount = finalBytes,
                completeness = completeness,
                nodeCount = capture.nodeCount,
                persistedNodeCount = nodes.length(),
                requiredAnchorStructuralMatchCount = if (
                    contract.requiredAnchorStructure != null && completeness == "COMPLETE" &&
                    nodes.length() == capture.nodeCount
                ) structuralAnchorMatchCount else null,
            )
        }
    }
}

/** Read-only event metadata correlated by the already-active navigation binding. */
internal data class NavigationWindowEventDiagnostic(
    val requestId: String,
    val transactionId: String,
    val serviceInstanceId: String,
    val connectionId: String,
    val ownerWindowId: Int,
    val eventType: Int,
    val eventPackage: String,
    val eventClass: String?,
    val eventWindowId: Int,
    val eventElapsedRealtimeMs: Long,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("request_id", requestId)
        .put("transaction_id", transactionId)
        .put("service_instance_id", serviceInstanceId)
        .put("connection_id", connectionId)
        .put("owner_window_id", ownerWindowId)
        .put("event_type", eventType)
        .put("event_package", eventPackage)
        .put("event_class", eventClass ?: JSONObject.NULL)
        .put("event_window_id", eventWindowId)
        .put("event_elapsed_realtime_ms", eventElapsedRealtimeMs)
}

/** Correlates secondary window events without changing the strict click or post-state verifier. */
internal object NavigationWindowEventDiagnosticPolicy {
    fun correlate(
        binding: NavigationActionBinding,
        target: NavigationActionTargetLease,
        currentServiceInstanceId: String,
        currentConnectionId: String,
        actionDispatchElapsedRealtimeMs: Long,
        dispatchDeadlineElapsedRealtimeMs: Long,
        eventType: Int,
        eventPackage: String?,
        eventClass: String?,
        eventWindowId: Int,
        eventElapsedRealtimeMs: Long,
    ): NavigationWindowEventDiagnostic? {
        if (eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            eventType != AccessibilityEvent.TYPE_WINDOWS_CHANGED) return null
        if (currentServiceInstanceId != binding.serviceInstanceId ||
            currentConnectionId != binding.connectionId ||
            binding.windowId != target.windowId || eventWindowId != binding.windowId ||
            eventPackage.isNullOrBlank() || eventPackage != target.packageName ||
            actionDispatchElapsedRealtimeMs < 0 ||
            dispatchDeadlineElapsedRealtimeMs < actionDispatchElapsedRealtimeMs ||
            eventElapsedRealtimeMs < actionDispatchElapsedRealtimeMs ||
            eventElapsedRealtimeMs > dispatchDeadlineElapsedRealtimeMs) return null
        return NavigationWindowEventDiagnostic(
            requestId = binding.requestId,
            transactionId = binding.transactionId,
            serviceInstanceId = binding.serviceInstanceId,
            connectionId = binding.connectionId,
            ownerWindowId = binding.windowId,
            eventType = eventType,
            eventPackage = eventPackage,
            eventClass = eventClass,
            eventWindowId = eventWindowId,
            eventElapsedRealtimeMs = eventElapsedRealtimeMs,
        )
    }
}

/** Adds diagnostics beside, never inside, the strict navigation receipt. */
internal fun attachSecondaryNavigationWindowDiagnostics(
    strictResult: JSONObject,
    diagnostics: JSONObject,
): JSONObject = JSONObject(strictResult.toString()).put("secondary_window_event_diagnostics", diagnostics)

/** Production event adapter. It is armed before ACTION_CLICK and retains the first click event only. */
private class NavigationActionEventCollector(
    private val binding: NavigationActionBinding,
    private val target: NavigationActionTargetLease,
    private val serviceInstanceId: String,
) {
    private val monitor = java.lang.Object()
    @Volatile private var firstClick: NavigationClickEvidence? = null
    @Volatile private var firstAccessibilityFocus: NavigationFocusEvidence? = null
    private var focusDispatchElapsedRealtimeMs: Long? = null
    private var focusDeadlineElapsedRealtimeMs: Long? = null
    private var actionDispatchElapsedRealtimeMs: Long? = null
    private var dispatchDeadlineElapsedRealtimeMs: Long? = null
    private val windowEvents = mutableListOf<NavigationWindowEventDiagnostic>()
    private var droppedWindowEventCount = 0

    fun markActionDispatch(dispatchElapsedRealtimeMs: Long, deadlineElapsedRealtimeMs: Long) {
        synchronized(monitor) {
            if (actionDispatchElapsedRealtimeMs == null) {
                actionDispatchElapsedRealtimeMs = dispatchElapsedRealtimeMs
                dispatchDeadlineElapsedRealtimeMs = deadlineElapsedRealtimeMs
            }
        }
    }

    fun markAccessibilityFocusDispatch(dispatchElapsedRealtimeMs: Long, deadlineElapsedRealtimeMs: Long) {
        synchronized(monitor) {
            if (focusDispatchElapsedRealtimeMs == null) {
                focusDispatchElapsedRealtimeMs = dispatchElapsedRealtimeMs
                focusDeadlineElapsedRealtimeMs = deadlineElapsedRealtimeMs
            }
        }
    }

    fun captureCallbackSourceAtEntry(
        event: AccessibilityEvent,
        currentServiceInstanceId: String,
        currentConnectionId: String,
    ): NavigationCallbackSourceObservation? {
        if (event.eventType != AccessibilityEvent.TYPE_VIEW_CLICKED ||
            currentServiceInstanceId != binding.serviceInstanceId || currentConnectionId != binding.connectionId) return null
        val dispatch = synchronized(monitor) {
            if (firstClick != null) null else {
                val started = actionDispatchElapsedRealtimeMs ?: return@synchronized null
                val deadline = dispatchDeadlineElapsedRealtimeMs ?: return@synchronized null
                started to deadline
            }
        } ?: return null
        return captureNavigationCallbackSourceObservation(
            binding, target, event, currentServiceInstanceId, currentConnectionId, dispatch.first, dispatch.second)
    }

    fun receive(
        event: AccessibilityEvent,
        currentServiceInstanceId: String,
        currentConnectionId: String,
        callbackSourceObservation: NavigationCallbackSourceObservation? = null,
    ) {
        if (currentServiceInstanceId != binding.serviceInstanceId || currentConnectionId != binding.connectionId) return
        if (event.eventType == AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED &&
            firstAccessibilityFocus == null) {
            val focusDispatch = synchronized(monitor) { focusDispatchElapsedRealtimeMs } ?: return
            val focusDeadline = synchronized(monitor) { focusDeadlineElapsedRealtimeMs } ?: return
            val eventElapsed = A11yEvidence.eventTimeElapsedRealtimeMs(
                event.eventTime, SystemClock.elapsedRealtime(), SystemClock.uptimeMillis()) ?: return
            val source = runCatching { event.source }.getOrNull()
            if (eventElapsed !in focusDispatch..focusDeadline ||
                !target.eventSourceMatches(source, event.windowId, currentConnectionId)) return
            synchronized(monitor) {
                if (firstAccessibilityFocus == null) {
                    firstAccessibilityFocus = NavigationFocusEvidence(
                        requestId = binding.requestId,
                        ownerCaptureReqId = binding.ownerCaptureReqId,
                        ownerLeaseId = binding.ownerLeaseId,
                        transactionId = binding.transactionId,
                        serviceInstanceId = currentServiceInstanceId,
                        connectionId = currentConnectionId,
                        windowId = event.windowId,
                        eventType = event.eventType,
                        eventElapsedRealtimeMs = eventElapsed,
                        source = source,
                    )
                    monitor.notifyAll()
                }
            }
            return
        }
        if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED ||
            event.eventType == AccessibilityEvent.TYPE_WINDOWS_CHANGED) {
            val eventElapsedRealtimeMs = A11yEvidence.eventTimeElapsedRealtimeMs(
                event.eventTime, SystemClock.elapsedRealtime(), SystemClock.uptimeMillis()) ?: return
            recordWindowEvent(
                currentServiceInstanceId = currentServiceInstanceId,
                currentConnectionId = currentConnectionId,
                eventType = event.eventType,
                eventPackage = runCatching { event.packageName?.toString() }.getOrNull(),
                eventClass = runCatching { event.className?.toString()?.take(160) }.getOrNull(),
                eventWindowId = event.windowId,
                eventElapsedRealtimeMs = eventElapsedRealtimeMs,
            )
            return
        }
        if (event.eventType != AccessibilityEvent.TYPE_VIEW_CLICKED || firstClick != null) return
        val matchingCallbackObservation = matchingNavigationCallbackSourceObservation(
            callbackSourceObservation, event, binding.requestId, binding.transactionId,
            currentServiceInstanceId, currentConnectionId)
        val source = when {
            callbackSourceObservation == null -> runCatching { event.source }.getOrNull()
            else -> matchingCallbackObservation?.source
        }
        val eventElapsedRealtimeMs = navigationClickElapsedRealtimeMs(
            callbackSourceObservation, event, binding.requestId, binding.transactionId,
            currentServiceInstanceId, currentConnectionId,
        ) {
            A11yEvidence.eventTimeElapsedRealtimeMs(
                event.eventTime, SystemClock.elapsedRealtime(), SystemClock.uptimeMillis())
        } ?: -1L
        synchronized(monitor) {
            if (firstClick == null) {
                firstClick = NavigationClickEvidence(binding.requestId, binding.transactionId, serviceInstanceId,
                    currentConnectionId, event.windowId, event.eventType, eventElapsedRealtimeMs,
                    source, matchingCallbackObservation)
                monitor.notifyAll()
            }
        }
    }

    private fun recordWindowEvent(
        currentServiceInstanceId: String,
        currentConnectionId: String,
        eventType: Int,
        eventPackage: String?,
        eventClass: String?,
        eventWindowId: Int,
        eventElapsedRealtimeMs: Long,
    ) {
        synchronized(monitor) {
            val start = actionDispatchElapsedRealtimeMs ?: return
            val deadline = dispatchDeadlineElapsedRealtimeMs ?: return
            val diagnostic = NavigationWindowEventDiagnosticPolicy.correlate(
                binding, target, currentServiceInstanceId, currentConnectionId, start, deadline,
                eventType, eventPackage, eventClass, eventWindowId, eventElapsedRealtimeMs,
            ) ?: return
            if (windowEvents.size < MAX_WINDOW_EVENTS) windowEvents.add(diagnostic)
            else droppedWindowEventCount++
        }
    }

    fun windowEventDiagnostics(): JSONObject = synchronized(monitor) {
        JSONObject()
            .put("evidence_role", "SECONDARY_ONLY")
            .put("status", if (actionDispatchElapsedRealtimeMs == null) "NOT_DISPATCHED" else "RECORDED")
            .put("request_id", binding.requestId)
            .put("transaction_id", binding.transactionId)
            .put("service_instance_id", binding.serviceInstanceId)
            .put("connection_id", binding.connectionId)
            .put("owner_window_id", binding.windowId)
            .put("action_dispatch_elapsed_realtime_ms", actionDispatchElapsedRealtimeMs ?: JSONObject.NULL)
            .put("dispatch_deadline_elapsed_realtime_ms", dispatchDeadlineElapsedRealtimeMs ?: JSONObject.NULL)
            .put("event_count", windowEvents.size)
            .put("dropped_event_count", droppedWindowEventCount)
            .put("events", JSONArray().apply { windowEvents.forEach { put(it.toJson()) } })
    }

    private companion object {
        const val MAX_WINDOW_EVENTS = 8
    }

    fun await(deadlineUptimeMs: Long): NavigationClickEvidence? = synchronized(monitor) {
        while (firstClick == null && SystemClock.elapsedRealtime() <= deadlineUptimeMs) {
            val remaining = deadlineUptimeMs - SystemClock.elapsedRealtime()
            if (remaining <= 0) break
            monitor.wait(remaining.coerceAtMost(250L))
        }
        firstClick
    }

    fun awaitAccessibilityFocus(deadlineUptimeMs: Long): NavigationFocusEvidence? = synchronized(monitor) {
        while (firstAccessibilityFocus == null && SystemClock.elapsedRealtime() <= deadlineUptimeMs) {
            val remaining = deadlineUptimeMs - SystemClock.elapsedRealtime()
            if (remaining <= 0) break
            monitor.wait(remaining.coerceAtMost(50L))
        }
        firstAccessibilityFocus
    }
}

/** Ensure the transaction-owned capture records a click before it wakes the nav verifier. */
internal object NavigationActionEventHandoff {
    fun captureOwnerEvidenceBeforeWake(captureOwnerEvidence: () -> Unit, wakeNavigationVerifier: () -> Unit) {
        captureOwnerEvidence()
        wakeNavigationVerifier()
    }
}

/** Helper-side composition loads reviewed contracts from the packaged policy resource. */
internal object NavigationActionRuntime {
    private data class RuntimePolicy(
        val contracts: Map<String, NavigationEffectContract>,
        val capability: NavigationActionCapability,
    )
    @Volatile private var runtimePolicy: RuntimePolicy? = null
    private val worker = java.util.concurrent.Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "navigation-action").apply { isDaemon = true }
    }
    @Volatile private var collector: NavigationActionEventCollector? = null

    private fun policyFor(service: A11yHelperService): RuntimePolicy {
        runtimePolicy?.let { return it }
        return synchronized(this) {
            runtimePolicy ?: run {
                val bytes = runCatching {
                    service.resources.openRawResource(R.raw.safe_navigation_contracts).use { it.readBytes() }
                }.getOrDefault(byteArrayOf())
                val contracts = NavigationEffectContractRegistry.load(bytes)
                RuntimePolicy(contracts, NavigationActionCapability(contracts, SystemClock::elapsedRealtime))
                    .also { runtimePolicy = it }
            }
        }
    }

    fun dispatch(service: A11yHelperService, raw: String, transportRequestId: String, complete: (JSONObject) -> Unit) {
        if (raw.toByteArray(Charsets.UTF_8).size > 64 * 1024 || ExactNodeResolver.hasDuplicateJsonKey(raw)) {
            complete(JSONObject().put("status", "REJECTED").put("failure_code", "NAVIGATION_REQUEST_INVALID")
                .put("verified_navigation", false).put("visit_authority", false)); return
        }
        val request = runCatching { JSONObject(raw) }.getOrElse {
            complete(JSONObject().put("status", "REJECTED").put("failure_code", "NAVIGATION_REQUEST_INVALID")
                .put("verified_navigation", false).put("visit_authority", false)); return
        }
        val localPolicy = policyFor(service)
        val id = request.optString("request_id")
        val contract = localPolicy.contracts[request.optString("effect_contract_id")]
        if (contract == null || request.optString("effect_contract_digest") != contract.digest) {
            complete(JSONObject().put("status", "REJECTED").put("failure_code", "NAVIGATION_EFFECT_CONTRACT_UNAVAILABLE")
                .put("request_id", id).put("visit_authority", false).put("c5_credit", false)); return
        }
        try {
            worker.execute {
                complete(runCatching { dispatchOnce(service, request, transportRequestId, contract, localPolicy.capability, localPolicy.contracts.values) }
                    .getOrElse { JSONObject().put("status", "REJECTED")
                        .put("failure_code", if (it is ExactActionRejected) it.code else "NAVIGATION_ACTION_FAILED")
                        .put("request_id", id).put("visit_authority", false).put("c5_credit", false) })
            }
        } catch (_: java.util.concurrent.RejectedExecutionException) {
            complete(JSONObject().put("status", "REJECTED").put("failure_code", "NAVIGATION_CONCURRENT_ACTION")
                .put("request_id", id).put("visit_authority", false).put("c5_credit", false))
        }
    }

    fun captureCallbackSourceAtEntry(
        event: AccessibilityEvent,
        serviceInstanceId: String,
    ): NavigationCallbackSourceObservation? =
        collector?.captureCallbackSourceAtEntry(event, serviceInstanceId, serviceInstanceId)

    fun receive(
        event: AccessibilityEvent,
        serviceInstanceId: String,
        callbackSourceObservation: NavigationCallbackSourceObservation? = null,
    ) {
        collector?.receive(event, serviceInstanceId, serviceInstanceId, callbackSourceObservation)
    }

    fun stop(serviceInstanceId: String) {
        val current = collector
        if (current != null) synchronized(this) { if (collector === current) collector = null }
    }

    fun capabilityStatus(service: A11yHelperService?): JSONObject {
        val policy = service?.let(::policyFor)
        val contracts = policy?.contracts?.values.orEmpty()
        val serviceId = A11yHelperService.serviceInstanceId
        val ready = service != null && A11yHelperService.instance === service && serviceId.isNotBlank() && contracts.isNotEmpty()
        val rows = JSONArray().apply {
            contracts.sortedBy { it.id }.forEach { contract ->
                put(JSONObject().put("contract_id", contract.id).put("contract_digest", contract.digest)
                    .put("scenario_ids", JSONArray().apply { contract.allowedScenarioIds.sorted().forEach { put(it) } }))
            }
        }
        return JSONObject().put("supported", true).put("enabled", contracts.isNotEmpty())
            .put("ready", ready).put("default_enabled", false).put("service_instance_id", serviceId)
            .put("contracts", rows).put("visit_credit", false).put("c5_credit", false)
            .put("exact_action_gate_independent", true)
            .put("reason", when {
                service == null || A11yHelperService.instance !== service -> "SERVICE_UNAVAILABLE"
                contracts.isEmpty() -> "NO_ENABLED_REVIEWED_CONTRACT"
                else -> "READY"
            })
    }

    private fun dispatchOnce(service: A11yHelperService, request: JSONObject, transportRequestId: String,
        contract: NavigationEffectContract, capability: NavigationActionCapability,
        diagnosticPolicyContracts: Collection<NavigationEffectContract>): JSONObject {
        fun requiredString(name: String) = request.optString(name).takeIf { it.isNotBlank() }
            ?: throw ExactActionRejected("NAVIGATION_REQUEST_INVALID")
        val requestId = requiredString("request_id")
        ExactActionContract.requireThat(requestId == transportRequestId, "NAVIGATION_REQUEST_OWNERSHIP_MISMATCH")
        val action = requiredString("action")
        ExactActionContract.requireThat(action == NAVIGATION_ACTION_CLICK, "NAVIGATION_ACTION_NOT_ALLOWLISTED")
        val activationMode = request.optString("activation_mode", NAVIGATION_ACTIVATION_DIRECT_CLICK)
        ExactActionContract.requireThat(activationMode in setOf(NAVIGATION_ACTIVATION_DIRECT_CLICK,
            NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
            NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK),
            "NAVIGATION_ACTIVATION_MODE_NOT_ALLOWLISTED")
        val serviceId = requiredString("service_instance_id")
        val connection = requiredString("connection_id")
        val activeServiceId = A11yHelperService.serviceInstanceId
        ExactActionContract.requireThat(A11yHelperService.instance === service && serviceId == activeServiceId &&
            connection == activeServiceId,
            "NAVIGATION_CONNECTION_MISMATCH")
        val pathJson = request.optJSONArray("node_path") ?: throw ExactActionRejected("NAVIGATION_REQUEST_INVALID")
        val path = (0 until pathJson.length()).map { pathJson.getInt(it) }
        val windowId = request.optInt("window_id", -1)
        val sourceSnapshotId = requiredString("source_snapshot_id")
        val captureId = requiredString("capture_id")
        val expectedDigest = requiredString("descriptor_digest")
        val packageName = requiredString("package_name")
        val scenarioId = requiredString("scenario_id")
        val ownerCaptureReqId = requiredString("owner_capture_request_id")
        val ownerLeaseId = requiredString("owner_lease_id")
        val runId = requiredString("run_id")
        val invocationId = requiredString("invocation_id")
        val transactionId = requiredString("transaction_id")
        val sourceJson = request.optJSONObject("source_identity")
            ?: throw ExactActionRejected("NAVIGATION_SOURCE_IDENTITY_MISSING")
        val sourceIdentity = EntryClickSourceIdentity(
            requestId = sourceJson.optString("request_id"),
            processEpoch = sourceJson.optString("process_epoch"),
            generation = sourceJson.optLong("generation", -1L),
            serviceInstanceId = sourceJson.optString("service_instance_id"),
            captureSequence = sourceJson.optLong("capture_sequence", -1L),
            rootDigest = sourceJson.optString("root_digest"),
            candidateDigest = sourceJson.optString("candidate_digest"),
            captureKey = sourceJson.optString("capture_key"),
            connectionEpoch = sourceJson.optString("connection_epoch"),
            bootEpoch = sourceJson.optString("boot_epoch"),
            ownerSourceNodeId = sourceJson.optString("owner_source_node_id"),
            ownerSourceNodeIdStatus = sourceJson.optString("owner_source_node_id_status"),
        )
        ExactActionContract.requireThat(sourceIdentity.requestId.isNotBlank() &&
            sourceIdentity.processEpoch.isNotBlank() && sourceIdentity.generation > 0L &&
            sourceIdentity.serviceInstanceId == serviceId && sourceIdentity.captureSequence > 0L &&
            sourceIdentity.rootDigest.matches(Regex("[0-9a-f]{64}")) &&
            sourceIdentity.candidateDigest.matches(Regex("[0-9a-f]{64}")) &&
            sourceIdentity.captureKey == sourceSnapshotId && sourceIdentity.connectionEpoch.isNotBlank() &&
            sourceIdentity.bootEpoch.isNotBlank() && validOwnerSourceNodeIdentity(sourceIdentity),
            "NAVIGATION_SOURCE_IDENTITY_INVALID")
        val currentLifecycle = ExactActionRuntime.status()
        ExactActionContract.requireThat(currentLifecycle.optString("connection_epoch") == sourceIdentity.connectionEpoch &&
            currentLifecycle.optString("boot_epoch") == sourceIdentity.bootEpoch,
            "NAVIGATION_SOURCE_LIFECYCLE_IDENTITY_STALE")
        val ownerTarget = A11yEvidence.navigationTargetLease(ownerCaptureReqId, ownerLeaseId,
            transactionId, connection, runId, invocationId, scenarioId, captureId, sourceIdentity)
            ?: throw ExactActionRejected("NAVIGATION_OWNER_LEASE_UNAVAILABLE")
        ExactActionContract.requireThat(ownerTarget.windowId == windowId && ownerTarget.packageName == packageName &&
            ownerTarget.nodePath == path && ownerTarget.descriptorDigest == expectedDigest &&
            ownerTarget.sourceSnapshotId == sourceSnapshotId &&
            ownerTarget.helperSnapshotId == requiredString("helper_snapshot_id") &&
            ownerTarget.baselineHierarchyDigest == requiredString("baseline_hierarchy_digest"),
            "NAVIGATION_OWNER_LEASE_MISMATCH")
        val diagnosticOnly = activationMode == NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK
        val target = when {
            contract.activationOwnerRelation != null -> ownerTarget.exactDeclaredActivationChild(
                contract.activationOwnerRelation, connection)
                ?: throw ExactActionRejected("NAVIGATION_ACTIVATION_CHILD_UNAVAILABLE")
            diagnosticOnly -> throw ExactActionRejected("NAVIGATION_DIAGNOSTIC_CHILD_UNAVAILABLE")
            else -> ownerTarget
        }
        val binding = NavigationActionBinding(
            runId = runId, invocationId = invocationId, scenarioId = scenarioId, requestId = requestId,
            action = action,
            transactionId = transactionId, ownerCaptureReqId = ownerCaptureReqId, ownerLeaseId = ownerLeaseId,
            serviceInstanceId = serviceId, connectionId = connection,
            windowId = windowId, sourceSnapshotId = sourceSnapshotId, helperSnapshotId = target.helperSnapshotId,
            captureId = captureId, nodePath = target.nodePath, descriptorDigest = target.descriptorDigest,
            baselineHierarchyDigest = target.baselineHierarchyDigest, effectContractId = contract.id,
            effectContractDigest = contract.digest,
            sourceIdentity = sourceIdentity,
            activationMode = activationMode,
        )
        val prepared = capability.prepare(binding, target, A11yHelperService.serviceInstanceId, serviceId,
            activationOwnerTarget = if (contract.activationOwnerRelation != null || diagnosticOnly)
                ownerTarget else null)
        if (prepared.optString("status") != "PREPARED") return prepared
        val token = prepared.getString("lease_token")
        var actionCollector: NavigationActionEventCollector? = null
        val capturePollTrace = if (activationMode == NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK)
            NavigationPostCapturePollTrace(binding) else null
        return capability.dispatch(token, binding, A11yHelperService.serviceInstanceId, serviceId,
            armCollector = { bound, leased ->
                val relation = contract.activationOwnerRelation
                val bindSameOwnerFocus = relation == null &&
                    bound.activationMode == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
                val ownerActionBound = if (relation == null && !bindSameOwnerFocus) true else {
                    val bindingResult = A11yEvidence.bindNavigationActionTarget(
                        binding.ownerCaptureReqId, binding.requestId, binding.transactionId, binding.connectionId,
                        binding.runId, binding.invocationId, binding.scenarioId, binding.captureId,
                        binding.ownerLeaseId, binding.sourceIdentity, ownerTarget, leased, relation)
                    bindingResult.optBoolean("ok") && navigationOwnerReceiptMatchesTarget(
                        bindingResult, binding, ownerTarget, relation)
                }
                if (!ownerActionBound) false else synchronized(this) {
                    if (A11yHelperService.instance !== service ||
                        A11yHelperService.serviceInstanceId != bound.serviceInstanceId || collector != null) false else {
                        actionCollector = NavigationActionEventCollector(bound, leased, A11yHelperService.serviceInstanceId)
                        collector = actionCollector
                        true
                    }
                }
            },
            awaitClick = { deadline -> collector?.await(deadline) },
            awaitAccessibilityFocus = { deadline -> collector?.awaitAccessibilityFocus(deadline) },
            markOwnerDispatch = { dispatchElapsed ->
                if (A11yHelperService.instance !== service ||
                    A11yHelperService.serviceInstanceId != binding.serviceInstanceId) {
                    JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_SERVICE_CHANGED")
                } else A11yEvidence.markNavigationEntryClickDispatch(binding.ownerCaptureReqId,
                    binding.transactionId, A11yHelperService.serviceInstanceId, dispatchElapsed)
            },
            markOwnerDispatchAfterFocus = { dispatchElapsed, focusEvidence ->
                if (A11yHelperService.instance !== service ||
                    A11yHelperService.serviceInstanceId != binding.serviceInstanceId) {
                    JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_SERVICE_CHANGED")
                } else A11yEvidence.markNavigationEntryClickDispatch(binding.ownerCaptureReqId,
                    binding.transactionId, A11yHelperService.serviceInstanceId, dispatchElapsed, focusEvidence)
            },
            confirmOwnerDispatch = { dispatchElapsed ->
                if (A11yHelperService.instance !== service ||
                    A11yHelperService.serviceInstanceId != binding.serviceInstanceId) {
                    JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_SERVICE_CHANGED")
                } else A11yEvidence.confirmEntryClickDispatch(binding.ownerCaptureReqId,
                    binding.transactionId, A11yHelperService.serviceInstanceId, dispatchElapsed)
            },
            capturePostAction = { deadline, click ->
                capturePost(service, binding, contract, deadline, click, capturePollTrace, diagnosticPolicyContracts)
            },
            currentServiceStillBound = {
                A11yHelperService.instance === service &&
                    A11yHelperService.serviceInstanceId == binding.serviceInstanceId &&
                    connection == binding.connectionId
            },
            capturePostPollingDiagnostics = { capturePollTrace?.toJson() },
            markActionDispatch = { dispatchElapsed, deadline ->
                runCatching { actionCollector?.markActionDispatch(dispatchElapsed, deadline) }
            },
            markAccessibilityFocusDispatch = { dispatchElapsed, deadline ->
                runCatching { actionCollector?.markAccessibilityFocusDispatch(dispatchElapsed, deadline) }
            },
        ).let { strictResult ->
            val response = actionCollector?.let { activeCollector ->
                runCatching {
                    attachSecondaryNavigationWindowDiagnostics(strictResult, activeCollector.windowEventDiagnostics())
                }.getOrDefault(strictResult)
            } ?: strictResult
            synchronized(this) { if (collector === actionCollector) collector = null }
            response
        }
    }

    private fun capturePost(service: A11yHelperService, binding: NavigationActionBinding,
        contract: NavigationEffectContract, deadline: Long, click: NavigationClickEvidence,
        pollTrace: NavigationPostCapturePollTrace? = null,
        diagnosticPolicyContracts: Collection<NavigationEffectContract> = emptyList()): NavigationPostActionEvidence? {
        var latest: NavigationPostActionEvidence? = null
        var firstStructuralAnchorResolutionFailure: String? = null
        while (SystemClock.elapsedRealtime() < deadline) {
            val attemptAt = if (pollTrace != null) SystemClock.elapsedRealtime().also(pollTrace::beginAttempt) else 0L
            if (A11yHelperService.instance !== service ||
                A11yHelperService.serviceInstanceId != binding.serviceInstanceId) {
                pollTrace?.markServiceChanged(attemptAt)
                return null
            }
            val observedWindows = service.windows.map { window ->
                window to NavigationPostCaptureWindowObservation(window.id, window.type, window.isActive)
            }
            pollTrace?.observeWindows(observedWindows.map { it.second })
            val activeType1 = observedWindows.filter { (_, observation) ->
                observation.type == 1 && observation.active
            }
            if (activeType1.size == 1) {
                val (window, _) = activeType1.single()
                val windowObservedAt = SystemClock.elapsedRealtime()
                val root = window.root
                if (root != null) {
                    if (root.windowId != window.id) {
                        pollTrace?.skip("POST_WINDOW_ROOT_MISMATCH")
                        val pollDelayMs = navigationPostCapturePollDelayMs(SystemClock.elapsedRealtime(), deadline)
                        if (pollDelayMs == 0L) break
                        Thread.sleep(pollDelayMs)
                        continue
                    }
                    if (root.packageName?.toString() != contract.packageName) {
                        pollTrace?.skip("POST_WINDOW_PACKAGE_MISMATCH")
                        val pollDelayMs = navigationPostCapturePollDelayMs(SystemClock.elapsedRealtime(), deadline)
                        if (pollDelayMs == 0L) break
                        Thread.sleep(pollDelayMs)
                        continue
                    }
                    val labels = mutableListOf<String>()
                    val focused = runCatching { root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY) }.getOrNull()
                    var focusMatches = 0
                    var complete = true
                    val nodeCount = intArrayOf(0)
                    val emptyState = contract.emptyStateSignature
                    var exactTextCount = 0
                    var exactTextWithinWebView = false
                    var containerCount = 0
                    var containerWithinWebView = false
                    var webViewCount = 0
                    var exactBackAnchorCount = 0
                    var excludedClassPresent = false
                    var anchorPath: List<Int> = emptyList()
                    val anchorMatcher = Regex(contract.requiredAnchorPattern, RegexOption.IGNORE_CASE)
                    fun walk(node: AccessibilityNodeInfo, depth: Int, path: List<Int>, ancestors: List<String>) {
                        if (depth > 80 || ++nodeCount[0] > 5_000) { complete = false; return }
                        if (node == focused) focusMatches++
                        val className = node.className?.toString().orEmpty()
                        val resourceId = node.viewIdResourceName.orEmpty()
                        val text = node.text?.toString().orEmpty()
                        val contentDescription = node.contentDescription?.toString().orEmpty()
                        listOf(node.text, node.contentDescription, node.viewIdResourceName).forEach { value ->
                            value?.toString()?.takeIf { it.isNotBlank() }?.let(labels::add)
                        }
                        emptyState?.let { signature ->
                            if (className == signature.webViewClassName) webViewCount++
                            val insideWebView = className == signature.webViewClassName ||
                                signature.webViewClassName in ancestors
                            if (text == signature.exactText || contentDescription == signature.exactText) {
                                exactTextCount++
                                exactTextWithinWebView = exactTextWithinWebView || insideWebView
                            }
                            if (className == signature.containerClassName &&
                                resourceId == signature.containerResourceId) {
                                containerCount++
                                containerWithinWebView = containerWithinWebView || insideWebView
                            }
                            if (className == signature.excludedClassName) excludedClassPresent = true
                            if (className == signature.anchorClassName && resourceId == signature.anchorResourceId &&
                                (anchorMatcher.matches(text) || anchorMatcher.matches(contentDescription)) &&
                                node.isEnabled && node.isVisibleToUser && node.isClickable &&
                                node.actionList.any { it.id == AccessibilityNodeInfo.ACTION_CLICK }) {
                                exactBackAnchorCount++
                                if (exactBackAnchorCount == 1) anchorPath = path
                            }
                        }
                        val nextAncestors = if (emptyState != null && className == emptyState.webViewClassName)
                            ancestors + className else ancestors
                        for (index in 0 until node.childCount) {
                            val child = runCatching { node.getChild(index) }.getOrNull()
                            if (child == null) { complete = false; return }
                            walk(child, depth + 1, path + index, nextAncestors)
                        }
                    }
                    walk(root, 0, emptyList(), emptyList())
                    if (!complete) pollTrace?.skip("TREE_INCOMPLETE")
                    if (complete) {
                        val captured = runCatching { ImmutableHierarchyCapture.capture(root) }.getOrNull()
                        val raw = captured?.let { runCatching { it.root.toRawJson() }.getOrNull() }
                        if (captured != null && raw != null) {
                            val digest = ExactProtocolJson.sha256(ExactProtocolJson.canonical(raw))
                            val captureId = UUID.randomUUID().toString()
                            val capturedAt = SystemClock.elapsedRealtime()
                            val sample = runCatching {
                                NavigationPostCaptureArtifact.fromCapture(
                                    capture = captured,
                                    requestId = binding.requestId,
                                    transactionId = binding.transactionId,
                                    serviceInstanceId = binding.serviceInstanceId,
                                    connectionId = binding.connectionId,
                                    windowId = root.windowId,
                                    captureId = captureId,
                                    capturedAtUptimeMs = capturedAt,
                                    hierarchyDigest = digest,
                                    contract = contract,
                                    scenarioId = binding.scenarioId,
                                    diagnosticPolicyContracts = diagnosticPolicyContracts,
                                )
                            }.getOrNull()
                            val rootPackage = captured.root.packageName?.toString()?.take(256)
                            val rootClass = captured.root.className?.toString()?.take(256)
                            val structure = emptyState?.let {
                                NavigationPostStructureEvidence(exactTextCount, exactTextWithinWebView,
                                    containerCount, containerWithinWebView, webViewCount, exactBackAnchorCount,
                                    excludedClassPresent, if (exactBackAnchorCount == 1) anchorPath else emptyList())
                            }
                            val windowAuthority = NavigationPostWindowAuthority(
                                requestId = binding.requestId,
                                transactionId = binding.transactionId,
                                serviceInstanceId = binding.serviceInstanceId,
                                connectionId = binding.connectionId,
                                actionWindowId = binding.windowId,
                                clickWindowId = click.windowId,
                                clickEventType = click.eventType,
                                clickEventElapsedRealtimeMs = click.eventElapsedRealtimeMs,
                                postWindowId = window.id,
                                activeType1WindowIds = activeType1.map { it.first.id },
                                observedAtUptimeMs = windowObservedAt,
                                rootWindowId = root.windowId,
                                rootPackageName = rootPackage,
                                rootClassName = rootClass,
                            )
                            val postStructure = structure?.takeIf { it.matches(emptyState!!, rootClass) }
                            val structuralAnchor = contract.requiredAnchorStructure
                            val structuralAnchorPath = sample?.takeIf {
                                it.completeness == "COMPLETE" && it.requiredAnchorStructuralMatchCount == 1
                            }?.requiredAnchorStructuralMatchPaths()?.singleOrNull()
                            val focusAnchorEvidenceReady = if (emptyState != null) {
                                postStructure != null
                            } else {
                                structuralAnchor != null && structuralAnchorPath != null
                            }
                            var anchorTarget: NavigationActionTargetLease? = null
                            val destinationMatches = contract.destinationMatches(labels, structure, rootPackage, rootClass)
                            val anchorMatches = contract.anchorMatchCount(
                                labels, sample?.requiredAnchorStructuralMatchCount)
                            val focusInTree = focused != null && focusMatches == 1 && focused.windowId == root.windowId
                            if (destinationMatches && anchorMatches == 1 && !focusInTree && focusAnchorEvidenceReady &&
                                capturedAt <= deadline) {
                                val resolver = ExactLiveNodeResolver {
                                    service.windows.map { currentWindow -> ExactApplicationWindow(
                                        currentWindow.id, currentWindow.type, currentWindow.isActive, currentWindow.root)
                                    }
                                }
                                anchorTarget = if (emptyState != null) {
                                    resolver.captureUniqueDestinationAnchor(
                                        expectedWindowId = root.windowId,
                                        expectedPackage = contract.packageName,
                                        sourceSnapshotId = captureId,
                                        connectionId = binding.connectionId,
                                        signature = emptyState,
                                        anchorPattern = contract.requiredAnchorPattern,
                                    )
                                } else {
                                    resolver.captureUniqueStructuralDestinationAnchor(
                                        expectedWindowId = root.windowId,
                                        expectedRootClassName = rootClass,
                                        expectedPackage = contract.packageName,
                                        sourceSnapshotId = captureId,
                                        connectionId = binding.connectionId,
                                        expectedNodePath = structuralAnchorPath!!,
                                        structure = structuralAnchor!!,
                                        anchorPattern = contract.requiredAnchorPattern,
                                        onFailure = { code ->
                                            if (firstStructuralAnchorResolutionFailure == null) {
                                                firstStructuralAnchorResolutionFailure = code
                                            }
                                        },
                                    )
                                }
                            }
                            latest = NavigationPostActionEvidence(binding.requestId, binding.transactionId,
                                binding.serviceInstanceId, binding.connectionId, root.windowId, captureId,
                                capturedAt, digest, labels, focused?.windowId,
                                focused?.isAccessibilityFocused == true, focusInTree,
                                captured.nodeCount, rootPackage, rootClass, sample, windowAuthority,
                                structure, anchorTarget, firstStructuralAnchorResolutionFailure)
                            pollTrace?.recordCompleteSample(capturedAt, rootPackage, rootClass)
                            val hierarchyChanged = latest!!.hierarchyDigest != binding.baselineHierarchyDigest
                            if (navigationPostCaptureSampleReady(
                                    hierarchyChanged = hierarchyChanged,
                                    destinationMatches = destinationMatches,
                                    anchorMatchCount = anchorMatches,
                                    emptyStateAnchorRequired = emptyState != null,
                                    structuralAnchorRequired = structuralAnchor != null,
                                    focusInCurrentHierarchy = focusInTree,
                                    destinationAnchorTargetAvailable = anchorTarget != null,
                                )) {
                                pollTrace?.markSampleAccepted()
                                return latest
                            }
                            if (structuralAnchor != null && emptyState == null && destinationMatches &&
                                anchorMatches == 1 && !focusInTree && anchorTarget == null) {
                                pollTrace?.skip("STRUCTURAL_FOCUS_TARGET_UNAVAILABLE")
                            } else pollTrace?.skip("COMPLETE_SAMPLE_NOT_VERIFIED")
                        } else pollTrace?.skip("IMMUTABLE_CAPTURE_UNAVAILABLE")
                    }
                } else pollTrace?.skip("ROOT_MISSING")
            } else if (activeType1.isEmpty()) pollTrace?.skip("ACTIVE_TYPE1_WINDOW_UNAVAILABLE")
            else pollTrace?.skip("ACTIVE_TYPE1_WINDOW_AMBIGUOUS")
            val pollDelayMs = navigationPostCapturePollDelayMs(SystemClock.elapsedRealtime(), deadline)
            if (pollDelayMs == 0L) break
            Thread.sleep(pollDelayMs)
        }
        pollTrace?.markDeadlineReached(SystemClock.elapsedRealtime())
        return latest
    }
}

/** Navigation verification is never visit or C5 authority. */
private fun navigationOwnerReceiptPath(receipt: JSONObject, key: String): List<Int>? {
    val path = receipt.optJSONArray(key) ?: return null
    if (path.length() > 80) return null
    val values = (0 until path.length()).map { path.optInt(it, -1) }
    return values.takeIf { it.all { index -> index in 0..4096 } }
}

private fun navigationOwnerReceiptMatchesTarget(
    receipt: JSONObject,
    binding: NavigationActionBinding,
    authorizationTarget: NavigationActionTargetLease,
    relation: NavigationActivationOwnerRelation?,
): Boolean {
    val actualRelation = receipt.optJSONObject("activationOwnerRelation")
    val relationMatches = if (relation == null) actualRelation == null else actualRelation != null &&
        actualRelation.optString("kind") == relation.kind &&
        actualRelation.optInt("child_index", -1) == relation.childIndex &&
        actualRelation.optString("child_class_pattern") == relation.childClassPattern &&
        actualRelation.optString("child_resource_id") == relation.childResourceId
    val requestBindingRequired = relation != null ||
        binding.activationMode == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
    val requestBindingMatches = !requestBindingRequired || (
        receipt.optString("navigationRequestId") == binding.requestId &&
            receipt.optString("ownerCaptureReqId") == binding.ownerCaptureReqId &&
            receipt.optString("ownerLeaseId") == binding.ownerLeaseId &&
            receipt.optString("transactionId") == binding.transactionId &&
            receipt.optString("serviceInstanceId") == binding.serviceInstanceId &&
            receipt.optString("ownerActionConnectionId") == binding.connectionId)
    return requestBindingMatches && navigationOwnerReceiptPath(receipt, "ownerActionPath") == binding.nodePath &&
        navigationOwnerReceiptPath(receipt, "ownerAuthorizationPath") == authorizationTarget.nodePath &&
        receipt.optString("ownerActionDescriptorDigest") == binding.descriptorDigest &&
        receipt.optString("ownerAuthorizationDescriptorDigest") == authorizationTarget.descriptorDigest &&
        receipt.optInt("ownerActionWindowId", -1) == binding.windowId &&
        receipt.optInt("ownerAuthorizationWindowId", -1) == authorizationTarget.windowId &&
        receipt.optString("ownerActionConnectionId") == binding.connectionId &&
        relationMatches
}

internal class NavigationActionCapability(
    private val contracts: Map<String, NavigationEffectContract>,
    private val uptime: () -> Long,
    private val leaseWindowMs: Long = 2_500L,
    private val postWindowMs: Long = 5_000L,
) {
    private data class Prepared(
        val token: String,
        val binding: NavigationActionBinding,
        val target: NavigationActionTargetLease,
        val contractAuthorityTarget: NavigationActionTargetLease,
        val contract: NavigationEffectContract,
        val deadline: Long,
    )

    private val lock = Any()
    private val leases = linkedMapOf<String, Prepared>()
    private val usedRequests = mutableSetOf<String>()

    fun prepare(binding: NavigationActionBinding, target: NavigationActionTargetLease,
        currentServiceInstanceId: String, currentConnectionId: String,
        activationOwnerTarget: NavigationActionTargetLease? = null): JSONObject = synchronized(lock) {
        val contract = contracts[binding.effectContractId]
            ?: return@synchronized rejected(binding, "NAVIGATION_EFFECT_CONTRACT_UNAVAILABLE")
        val diagnosticMode = binding.activationMode == NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK
        val hasDeclaredRelation = contract.activationOwnerRelation != null
        val contractAuthorityTarget = if (hasDeclaredRelation || diagnosticMode) activationOwnerTarget
            ?: return@synchronized rejected(binding, "NAVIGATION_ACTIVATION_OWNER_MISSING") else target
        if (!validBinding(binding) || binding.serviceInstanceId != currentServiceInstanceId ||
            binding.connectionId != currentConnectionId || binding.windowId != target.windowId ||
            binding.connectionId != target.connectionId || binding.sourceSnapshotId != target.sourceSnapshotId ||
            binding.helperSnapshotId != target.helperSnapshotId || binding.nodePath != target.nodePath ||
            binding.descriptorDigest != target.descriptorDigest ||
            binding.baselineHierarchyDigest != target.baselineHierarchyDigest || binding.captureId.isBlank()) {
            return@synchronized rejected(binding, "NAVIGATION_BINDING_MISMATCH")
        }
        if (!contract.isWellFormed(binding.effectContractDigest) || !contract.matches(contractAuthorityTarget))
            return@synchronized rejected(binding, "NAVIGATION_EFFECT_UNPROVEN")
        if (hasDeclaredRelation && !validDeclaredActivationTarget(
                binding, contract, contractAuthorityTarget, target, currentConnectionId))
            return@synchronized rejected(binding, if (diagnosticMode)
                "NAVIGATION_DIAGNOSTIC_CHILD_UNPROVEN" else "NAVIGATION_ACTIVATION_CHILD_UNPROVEN")
        if (diagnosticMode && (binding.scenarioId != "life_air_care_plugin" ||
                binding.effectContractId != "life_service_card_read_only_navigation" || !hasDeclaredRelation))
            return@synchronized rejected(binding, "NAVIGATION_DIAGNOSTIC_CHILD_UNPROVEN")
        if (!contract.allowsScenario(binding.scenarioId))
            return@synchronized rejected(binding, "NAVIGATION_SCENARIO_NOT_AUTHORIZED")
        if (!target.isUniqueInSnapshot || target.independentDescendants < 0 || target.independentSiblings < 0 ||
            target.descriptorDigest.isBlank() || !target.hasClickAction || !target.stillCurrent(currentConnectionId))
            return@synchronized rejected(binding, "NAVIGATION_TARGET_UNPROVEN")
        if (binding.activationMode == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK &&
            !target.hasAccessibilityFocusAction)
            return@synchronized rejected(binding, "NAVIGATION_FOCUS_ACTION_UNAVAILABLE")
        if (usedRequests.contains(binding.requestId) || leases.values.any { it.binding.requestId == binding.requestId })
            return@synchronized rejected(binding, "NAVIGATION_REQUEST_REPLAY")
        val now = uptime()
        if (now < 0 || leaseWindowMs !in 1..2_500L) return@synchronized rejected(binding, "NAVIGATION_LEASE_INVALID")
        val token = UUID.randomUUID().toString()
        leases[token] = Prepared(token, binding, target, contractAuthorityTarget, contract,
            Math.addExact(now, leaseWindowMs))
        JSONObject().put("status", "PREPARED").put("lease_token", token)
            .put("request_id", binding.requestId).put("transaction_id", binding.transactionId)
            .put("scenario_id", binding.scenarioId).put("owner_lease_id", binding.ownerLeaseId)
            .put("helper_snapshot_id", binding.helperSnapshotId).put("visit_authority", false)
    }

    fun dispatch(
        leaseToken: String,
        binding: NavigationActionBinding,
        currentServiceInstanceId: String,
        currentConnectionId: String,
        armCollector: (NavigationActionBinding, NavigationActionTargetLease) -> Boolean,
        awaitClick: (deadlineUptimeMs: Long) -> NavigationClickEvidence?,
        markOwnerDispatch: (dispatchElapsedRealtimeMs: Long) -> JSONObject,
        markOwnerDispatchAfterFocus: ((Long, NavigationFocusEvidence) -> JSONObject)? = null,
        confirmOwnerDispatch: (dispatchElapsedRealtimeMs: Long) -> JSONObject = markOwnerDispatch,
        capturePostAction: (deadlineUptimeMs: Long, click: NavigationClickEvidence) -> NavigationPostActionEvidence?,
        currentServiceStillBound: () -> Boolean = { true },
        markActionDispatch: (dispatchElapsedRealtimeMs: Long, deadlineElapsedRealtimeMs: Long) -> Unit = { _, _ -> },
        awaitAccessibilityFocus: (deadlineUptimeMs: Long) -> NavigationFocusEvidence? = { null },
        markAccessibilityFocusDispatch: (dispatchElapsedRealtimeMs: Long, deadlineElapsedRealtimeMs: Long) -> Unit = { _, _ -> },
        capturePostPollingDiagnostics: () -> JSONObject? = { null },
    ): JSONObject {
        val prepared = synchronized(lock) {
            val found = leases.remove(leaseToken) ?: return rejected(binding, "NAVIGATION_LEASE_UNKNOWN")
            usedRequests += found.binding.requestId
            found
        }
        val target = prepared.target
        val now = uptime()
        if (prepared.binding != binding || !validBinding(binding) ||
            currentServiceInstanceId != binding.serviceInstanceId || currentConnectionId != binding.connectionId ||
            now < 0 || now > prepared.deadline || binding.windowId != target.windowId ||
            binding.helperSnapshotId != target.helperSnapshotId || binding.sourceSnapshotId != target.sourceSnapshotId ||
            binding.nodePath != target.nodePath || binding.descriptorDigest != target.descriptorDigest ||
            binding.baselineHierarchyDigest != target.baselineHierarchyDigest ||
            !prepared.contract.isWellFormed(binding.effectContractDigest) ||
            !prepared.contract.matches(prepared.contractAuthorityTarget) ||
            (prepared.contract.activationOwnerRelation != null && !validDeclaredActivationTarget(
                binding, prepared.contract, prepared.contractAuthorityTarget, target, currentConnectionId)) ||
            (binding.activationMode == NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK &&
                (binding.scenarioId != "life_air_care_plugin" ||
                    binding.effectContractId != "life_service_card_read_only_navigation" ||
                    prepared.contract.activationOwnerRelation == null)) ||
            !prepared.contract.allowsScenario(binding.scenarioId)) {
            return rejected(binding, "NAVIGATION_PRE_DISPATCH_BINDING_REJECTED")
        }
        if (!target.stillCurrent(currentConnectionId)) return rejected(binding, "NAVIGATION_TARGET_STALE")
        if (!armCollector(binding, target)) return rejected(binding, "NAVIGATION_COLLECTOR_NOT_ARMED")
        var focusDiagnostics: JSONObject? = null
        var verifiedFocusEvent: NavigationFocusEvidence? = null
        fun withActivationDiagnostics(result: JSONObject): JSONObject {
            val diagnostics = focusDiagnostics ?: return result
            result.put("activation_mode", binding.activationMode)
                .put("activation_diagnostics", diagnostics)
            return result
        }
        val diagnosticOnly = binding.activationMode == NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK
        fun diagnosticResult(
            failureCode: String,
            actionDispatched: Boolean = false,
            clickEvidence: NavigationClickEvidence? = null,
            postDiagnostics: JSONObject? = null,
        ): JSONObject = rejected(binding, failureCode)
            .put("status", "DIAGNOSTIC_ONLY")
            .put("verified_navigation", false).put("visit_authority", false)
            .put("c5_credit", false).put("traversal_credit", false)
            .put("diagnostic_only", true).put("diagnostic_action_dispatched", actionDispatched)
            .put("action_call_count", if (actionDispatched) 1 else 0)
            .put("activation_mode", binding.activationMode)
            .put("action", binding.action).put("scenario_id", binding.scenarioId)
            .put("owner_capture_request_id", binding.ownerCaptureReqId)
            .put("owner_lease_id", binding.ownerLeaseId)
            .put("service_instance_id", binding.serviceInstanceId)
            .put("connection_id", binding.connectionId)
            .put("window_id", binding.windowId)
            .put("source_capture_id", binding.captureId)
            .put("helper_snapshot_id", binding.helperSnapshotId)
            .put("effect_contract_id", binding.effectContractId)
            .put("effect_contract_digest", binding.effectContractDigest)
            .put("source_identity", JSONObject().put("request_id", binding.sourceIdentity.requestId)
                .put("process_epoch", binding.sourceIdentity.processEpoch)
                .put("generation", binding.sourceIdentity.generation)
                .put("service_instance_id", binding.sourceIdentity.serviceInstanceId)
                .put("capture_sequence", binding.sourceIdentity.captureSequence)
                .put("root_digest", binding.sourceIdentity.rootDigest)
                .put("candidate_digest", binding.sourceIdentity.candidateDigest)
                .put("capture_key", binding.sourceIdentity.captureKey)
                .put("connection_epoch", binding.sourceIdentity.connectionEpoch)
                .put("boot_epoch", binding.sourceIdentity.bootEpoch)
                .put("owner_source_node_id", binding.sourceIdentity.ownerSourceNodeId)
                .put("owner_source_node_id_status", binding.sourceIdentity.ownerSourceNodeIdStatus))
            .put("diagnostic_target", JSONObject()
                .put("path", JSONArray(binding.nodePath)).put("class_name", target.className)
                .put("resource_id", target.resourceId).put("window_id", target.windowId)
                .put("descriptor_digest", target.descriptorDigest)
                .put("source_snapshot_id", target.sourceSnapshotId)
                .put("helper_snapshot_id", target.helperSnapshotId)
                .put("baseline_hierarchy_digest", target.baselineHierarchyDigest)
                .put("parent_path", JSONArray(prepared.contractAuthorityTarget.nodePath)))
            .put("diagnostic_click_event", clickEvidence?.let { click ->
                JSONObject().put("exact_target_match", true).put("event_type", click.eventType)
                    .put("event_elapsed_realtime_ms", click.eventElapsedRealtimeMs)
                    .put("request_id", click.requestId).put("transaction_id", click.transactionId)
                    .put("service_instance_id", click.serviceInstanceId)
                    .put("connection_id", click.connectionId).put("window_id", click.windowId)
            } ?: JSONObject.NULL)
            .put("post_state_diagnostics", postDiagnostics ?: JSONObject.NULL)
            .also {
                if (diagnosticOnly && postDiagnostics != null) {
                    runCatching(capturePostPollingDiagnostics).getOrNull()?.let { polling ->
                        postDiagnostics.put("capture_polling", JSONObject(polling.toString()))
                    }
                }
            }
        if (binding.activationMode == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK) {
            val focusDispatchElapsed = uptime()
            if (focusDispatchElapsed < 0 || focusDispatchElapsed > prepared.deadline ||
                !target.stillCurrent(currentConnectionId))
                return rejected(binding, "NAVIGATION_FOCUS_TARGET_STALE")
                    .put("activation_mode", binding.activationMode)
                    .put("focus_event_status", "NOT_DISPATCHED")
            val focusDeadline = minOf(prepared.deadline, Math.addExact(focusDispatchElapsed, 2_500L))
            val diagnostics = JSONObject().put("activation_mode", binding.activationMode)
                .put("focus_action", NAVIGATION_ACTION_ACCESSIBILITY_FOCUS)
                .put("focus_action_count", 0)
                .put("focus_dispatch_elapsed_realtime_ms", focusDispatchElapsed)
                .put("focus_event_deadline_elapsed_realtime_ms", focusDeadline)
                .put("focus_event_status", "AWAITING_EXACT_OWNER_EVENT")
            focusDiagnostics = diagnostics
            runCatching { markAccessibilityFocusDispatch(focusDispatchElapsed, focusDeadline) }
            val focusAuthorization = NavigationActionDispatchAuthorization.afterNavigationGate(
                binding.requestId, binding.transactionId, leaseToken, NAVIGATION_ACTION_ACCESSIBILITY_FOCUS)
            val focusReturned = runCatching {
                target.performNavigationAccessibilityFocus(focusAuthorization, binding.requestId,
                    binding.transactionId, leaseToken, currentConnectionId)
            }.getOrElse {
                diagnostics.put("focus_event_status", "FOCUS_ACTION_REJECTED")
                    .put("focus_failure_code", if (it is ExactActionRejected) it.code else "NAVIGATION_FOCUS_ACTION_FAILED")
                return rejected(binding, "NAVIGATION_FOCUS_ACTION_FAILED")
                    .put("activation_mode", binding.activationMode).put("activation_diagnostics", diagnostics)
            }
            if (!focusReturned) {
                diagnostics.put("focus_event_status", "FOCUS_ACTION_NOT_ACKED")
                return rejected(binding, "NAVIGATION_FOCUS_ACTION_NOT_ACKED")
                    .put("activation_mode", binding.activationMode).put("activation_diagnostics", diagnostics)
            }
            diagnostics.put("focus_action_acknowledged", true).put("focus_action_count", 1)
            val focusEvent = awaitAccessibilityFocus(focusDeadline)
            if (focusEvent == null) {
                diagnostics.put("focus_event_status", "EXACT_FOCUS_EVENT_MISSING")
                return rejected(binding, "NAVIGATION_FOCUS_EVENT_MISSING")
                    .put("activation_mode", binding.activationMode).put("activation_diagnostics", diagnostics)
            }
            val exactFocusEvent = focusEvent.requestId == binding.requestId &&
                focusEvent.ownerCaptureReqId == binding.ownerCaptureReqId &&
                focusEvent.ownerLeaseId == binding.ownerLeaseId &&
                focusEvent.transactionId == binding.transactionId &&
                focusEvent.serviceInstanceId == binding.serviceInstanceId &&
                focusEvent.connectionId == binding.connectionId && focusEvent.windowId == binding.windowId &&
                focusEvent.eventType == AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED &&
                focusEvent.eventElapsedRealtimeMs in focusDispatchElapsed..focusDeadline &&
                target.eventSourceMatches(focusEvent.source, focusEvent.windowId, currentConnectionId)
            diagnostics.put("focus_event_elapsed_realtime_ms", focusEvent.eventElapsedRealtimeMs)
                .put("focus_event_window_id", focusEvent.windowId)
                .put("focus_navigation_request_id", focusEvent.requestId)
                .put("focus_owner_capture_request_id", focusEvent.ownerCaptureReqId)
                .put("focus_owner_lease_id", focusEvent.ownerLeaseId)
                .put("focus_event_owner_exact", exactFocusEvent)
            if (!exactFocusEvent) {
                diagnostics.put("focus_event_status", "FOCUS_EVENT_IDENTITY_MISMATCH")
                return rejected(binding, "NAVIGATION_FOCUS_EVENT_SOURCE_MISMATCH")
                    .put("activation_mode", binding.activationMode).put("activation_diagnostics", diagnostics)
            }
            val preparedDeadlineExpired = uptime() > prepared.deadline
            val focusRevalidation = if (preparedDeadlineExpired) null else
                target.revalidateAfterAccessibilityFocus(currentConnectionId)
            val focusRevalidationAccepted = !preparedDeadlineExpired && focusRevalidation?.accepted == true
            val currentServiceMatches = currentServiceInstanceId == binding.serviceInstanceId &&
                focusEvent.serviceInstanceId == binding.serviceInstanceId
            val currentConnectionMatches = currentConnectionId == binding.connectionId &&
                focusEvent.connectionId == binding.connectionId
            val currentWindowMatches = target.windowId == binding.windowId &&
                focusEvent.windowId == binding.windowId
            diagnostics.put("focus_revalidation", JSONObject()
                .put("prepared_deadline_valid", !preparedDeadlineExpired)
                .put("service_identity_matches", currentServiceMatches)
                .put("connection_identity_matches", currentConnectionMatches)
                .put("window_identity_matches", currentWindowMatches)
                .put("focus_event_owner_matches", exactFocusEvent)
                .put("target_currentness", focusRevalidation?.diagnostics ?: JSONObject()
                    .put("diagnostics_available", false)
                    .put("evaluation", "SKIPPED_PREPARED_DEADLINE"))
                .put("aggregate_accepted", focusRevalidationAccepted))
            if (!focusRevalidationAccepted) {
                diagnostics.put("focus_event_status", "FOCUSED_HIERARCHY_REVALIDATION_FAILED")
                return rejected(binding, "NAVIGATION_FOCUSED_TARGET_STALE")
                    .put("activation_mode", binding.activationMode).put("activation_diagnostics", diagnostics)
            }
            verifiedFocusEvent = focusEvent
            diagnostics.put("focus_event_status", "EXACT_OWNER_FOCUSED_CURRENT")
                .put("focus_node_path", JSONArray(binding.nodePath))
                .put("focus_descriptor_digest", binding.descriptorDigest)
                .put("focus_service_instance_id", binding.serviceInstanceId)
                .put("focus_connection_id", binding.connectionId)
                .put("focus_window_id", binding.windowId)
        }
        // Keep the direct-click path's original revalidation and dispatch behavior unchanged.
        val targetCurrentBeforeClick = if (binding.activationMode == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK)
            target.stillCurrentAfterAccessibilityFocus(currentConnectionId) else target.stillCurrent(currentConnectionId)
        if (uptime() > prepared.deadline || !targetCurrentBeforeClick)
            return withActivationDiagnostics(rejected(binding,
                if (focusDiagnostics == null) "NAVIGATION_TARGET_STALE" else "NAVIGATION_FOCUSED_TARGET_STALE"))
        val actionDispatchElapsed = uptime()
        if (actionDispatchElapsed < 0 || actionDispatchElapsed > prepared.deadline)
            return rejected(binding, "NAVIGATION_TARGET_STALE")
        // The bounded post-action window begins at the exact retained-node ACTION_CLICK call,
        // not before collector arming and the final currentness check.
        val dispatchDeadline = Math.addExact(actionDispatchElapsed, postWindowMs)
        focusDiagnostics?.let {
            it.put("navigation_action", NAVIGATION_ACTION_CLICK)
                .put("click_action_count", 1)
                .put("click_dispatch_elapsed_realtime_ms", actionDispatchElapsed)
        }
        runCatching { markActionDispatch(actionDispatchElapsed, dispatchDeadline) }
        val ownerDispatchMark = if (diagnosticOnly) null else runCatching {
            val focusProof = verifiedFocusEvent
            if (focusProof == null) {
                markOwnerDispatch(actionDispatchElapsed)
            } else {
                markOwnerDispatchAfterFocus?.invoke(actionDispatchElapsed, focusProof)
                    ?: markOwnerDispatch(actionDispatchElapsed)
            }
        }.getOrElse { JSONObject().put("ok", false).put("reason", "OWNER_DISPATCH_MARK_FAILED") }
        if (!diagnosticOnly) {
            val mark = ownerDispatchMark ?: JSONObject()
            val targetMatches = navigationOwnerReceiptMatchesTarget(
                mark, binding, prepared.contractAuthorityTarget, prepared.contract.activationOwnerRelation)
            if (!mark.optBoolean("ok") || mark.optString("ownerLeaseId") != binding.ownerLeaseId ||
                mark.optLong("dispatchElapsedRealtimeMs", -1L) != actionDispatchElapsed ||
                mark.optInt("eligibleExactClickCount", -1) != 0 || !mark.isNull("clickEventId") ||
                !targetMatches) {
                return withActivationDiagnostics(rejected(binding, "NAVIGATION_OWNER_DISPATCH_MARK_UNVERIFIED")
                    .put("owner_dispatch_mark_reason", mark.optString("reason"))
                    .put("owner_dispatch_mark_ok", mark.optBoolean("ok"))
                    .put("owner_dispatch_mark_lease_match", mark.optString("ownerLeaseId") == binding.ownerLeaseId)
                    .put("owner_dispatch_mark_target_match", targetMatches)
                    .put("owner_dispatch_mark_eligible_exact_click_count",
                        mark.optInt("eligibleExactClickCount", -1))
                    .put("owner_dispatch_mark_focus_revalidation",
                        mark.optJSONObject("focus_revalidation") ?: JSONObject.NULL))
            }
        }
        val authorization = NavigationActionDispatchAuthorization.afterNavigationGate(
            binding.requestId, binding.transactionId, leaseToken, binding.action)
        val actionReturned = runCatching {
            if (binding.activationMode == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK) {
                target.performNavigationClickAfterAccessibilityFocus(authorization, binding.requestId,
                    binding.transactionId, leaseToken, currentConnectionId)
            } else {
                target.performNavigationClick(authorization, binding.requestId, binding.transactionId,
                    leaseToken, currentConnectionId)
            }
        }.getOrElse {
            val code = if (it is ExactActionRejected) it.code else "NAVIGATION_ACTION_FAILED"
            return if (diagnosticOnly) diagnosticResult(code, actionDispatched = true) else rejected(binding, code)
        }
        if (!actionReturned) return if (diagnosticOnly) diagnosticResult("NAVIGATION_ACTION_NOT_ACKED", true)
            else withActivationDiagnostics(rejected(binding, "NAVIGATION_ACTION_NOT_ACKED"))

        val click = awaitClick(dispatchDeadline)
            ?: return if (diagnosticOnly) diagnosticResult("NAVIGATION_EXACT_EVENT_MISSING", true)
                else withActivationDiagnostics(rejected(binding, "NAVIGATION_EXACT_EVENT_MISSING"))
        val clickBindingAndTimingMatch = click.requestId == binding.requestId &&
            click.transactionId == binding.transactionId && click.serviceInstanceId == binding.serviceInstanceId &&
            click.connectionId == binding.connectionId && click.windowId == binding.windowId &&
            click.eventType == AccessibilityEvent.TYPE_VIEW_CLICKED &&
            click.eventElapsedRealtimeMs >= actionDispatchElapsed && click.eventElapsedRealtimeMs <= dispatchDeadline
        val clickSourceOwnerExact = target.eventSourceMatches(click.source, click.windowId, currentConnectionId)
        if (!clickBindingAndTimingMatch || !clickSourceOwnerExact) {
            val mismatch = if (diagnosticOnly) diagnosticResult("NAVIGATION_EVENT_SOURCE_MISMATCH", true)
                else withActivationDiagnostics(rejected(binding, "NAVIGATION_EVENT_SOURCE_MISMATCH"))
            return mismatch.put("click_event_source_diagnostics", navigationClickSourceDiagnostics(
                binding, click, currentConnectionId, clickSourceOwnerExact))
        }
        focusDiagnostics?.let {
            it.put("click_event_status", "EXACT_OWNER_CLICKED")
                .put("click_event_elapsed_realtime_ms", click.eventElapsedRealtimeMs)
                .put("click_event_owner_exact", true)
        }
        val ownerReceipt = if (diagnosticOnly) null else runCatching {
            confirmOwnerDispatch(actionDispatchElapsed)
        }.getOrElse { JSONObject().put("ok", false).put("reason", "OWNER_DISPATCH_CONFIRM_FAILED") }
        var ownerClickProvenance: JSONObject? = null
        if (!diagnosticOnly) {
            val receipt = ownerReceipt ?: JSONObject()
            val targetMatches = navigationOwnerReceiptMatchesTarget(
                receipt, binding, prepared.contractAuthorityTarget, prepared.contract.activationOwnerRelation)
            val eventMatches = receipt.optBoolean("ownerExact") &&
                receipt.optLong("dispatchElapsedRealtimeMs", -1L) == actionDispatchElapsed &&
                receipt.optLong("clickEventElapsedRealtimeMs", -1L) == click.eventElapsedRealtimeMs &&
                receipt.optInt("clickEventType", -1) == click.eventType &&
                receipt.optInt("clickEventWindowId", -1) == click.windowId
            if (!receipt.optBoolean("ok") || receipt.optString("ownerLeaseId") != binding.ownerLeaseId ||
                receipt.optInt("eligibleExactClickCount", -1) != 1 ||
                receipt.optString("clickEventId").isBlank() || !targetMatches || !eventMatches) {
                val ownerReceiptFailure = rejected(binding, "NAVIGATION_OWNER_RECEIPT_UNVERIFIED")
                    .put("owner_receipt_reason", receipt.optString("reason"))
                    .put("owner_receipt_ok", receipt.optBoolean("ok"))
                    .put("owner_receipt_lease_match", receipt.optString("ownerLeaseId") == binding.ownerLeaseId)
                    .put("owner_receipt_target_match", targetMatches)
                    .put("owner_receipt_event_match", eventMatches)
                    .put("owner_receipt_eligible_exact_click_count", receipt.optInt("eligibleExactClickCount", -1))
                    .put("owner_receipt_click_event_present", receipt.optString("clickEventId").isNotBlank())
                    .put("owner_receipt_click_event_elapsed_realtime_ms",
                        receipt.optLong("clickEventElapsedRealtimeMs", -1L))
                    .put("owner_click_event_elapsed_realtime_ms", click.eventElapsedRealtimeMs)
                    .put("click_event_source_diagnostics", navigationClickSourceDiagnostics(
                        binding, click, currentConnectionId, clickSourceOwnerExact))
                return withActivationDiagnostics(ownerReceiptFailure)
            }
            ownerClickProvenance = JSONObject()
                .put("schema", "navigation-owner-click-v1")
                .put("request_id", binding.requestId)
                .put("transaction_id", binding.transactionId)
                .put("owner_lease_id", binding.ownerLeaseId)
                .put("action_window_id", binding.windowId)
                .put("service_instance_id", binding.serviceInstanceId)
                .put("connection_id", binding.connectionId)
                .put("dispatch_marked_before_action", true)
                .put("dispatch_target_currentness_accepted", receipt.optBoolean("dispatchTargetCurrentnessAccepted"))
                .put("dispatch_elapsed_realtime_ms", actionDispatchElapsed)
                .put("eligible_exact_click_count", receipt.optInt("eligibleExactClickCount"))
                .put("click_event_id", receipt.optString("clickEventId"))
                .put("click_event_type", click.eventType)
                .put("click_event_elapsed_realtime_ms", click.eventElapsedRealtimeMs)
                .put("click_event_window_id", click.windowId)
                .put("owner_exact", true)
                .put("click_event_source_diagnostics", navigationClickSourceDiagnostics(
                    binding, click, currentConnectionId, clickSourceOwnerExact))
                .put("authorization_owner_path", receipt.optJSONArray("ownerAuthorizationPath")
                    ?.let { JSONArray(it.toString()) } ?: JSONObject.NULL)
                .put("action_target_path", receipt.optJSONArray("ownerActionPath")
                    ?.let { JSONArray(it.toString()) } ?: JSONObject.NULL)
                .put("authorization_owner_descriptor_digest", receipt.optString("ownerAuthorizationDescriptorDigest"))
                .put("action_target_descriptor_digest", receipt.optString("ownerActionDescriptorDigest"))
                .put("activation_owner_relation", receipt.opt("activationOwnerRelation") ?: JSONObject.NULL)
        }
        val captureCallStartedAt = uptime()
        var post = capturePostAction(dispatchDeadline, click)
        var captureCallCompletedAt = uptime()
        val destinationFocusDiagnostics = JSONObject()
            .put("focus_action", NAVIGATION_ACTION_ACCESSIBILITY_FOCUS)
            .put("focus_action_count", 0)
            .put("status", "NOT_EVALUATED")
        var focusExpectedPostWindowId: Int? = null
        var focusCaptureFailure: String? = null
        val emptyState = prepared.contract.emptyStateSignature
        val structuralAnchor = prepared.contract.requiredAnchorStructure
        val structuralSample = post?.captureSample
        val structuralAnchorPath = structuralSample?.takeIf {
            it.completeness == "COMPLETE" && it.requiredAnchorStructuralMatchCount == 1
        }?.requiredAnchorStructuralMatchPaths()?.singleOrNull()
        val focusDestinationMatches = post?.let {
            prepared.contract.destinationMatches(it.labels, it.structureEvidence, it.rootPackageName, it.rootClassName)
        } == true
        val focusAnchorMatchCount = post?.let {
            prepared.contract.anchorMatchCount(it.labels, it.captureSample?.requiredAnchorStructuralMatchCount)
        } ?: 0
        val focusAnchorEvidenceVerified = when {
            post == null -> false
            emptyState != null -> post.structureEvidence?.matches(emptyState, post.rootClassName) == true
            structuralAnchor != null -> structuralAnchorPath != null
            else -> false
        }
        if (!diagnosticOnly && post != null && (emptyState != null || structuralAnchor != null) &&
            focusDestinationMatches && focusAnchorMatchCount == 1 &&
            focusAnchorEvidenceVerified && !post.focusInCurrentHierarchy) {
            val focusTarget = post.destinationAnchorTarget
            val focusTargetMatchesContract = focusTarget?.let { target ->
                when {
                    emptyState != null -> target.className == emptyState.anchorClassName &&
                        target.resourceId == emptyState.anchorResourceId
                    structuralAnchor != null -> structuralAnchorPath != null &&
                        target.nodePath == structuralAnchorPath &&
                        Regex(structuralAnchor.nodeClassPattern, RegexOption.IGNORE_CASE).matches(target.className)
                    else -> false
                }
            } == true
            val postAuthorityValid = post.postWindowAuthority?.matches(
                binding, click, post, prepared.contract, actionDispatchElapsed, dispatchDeadline) == true
            val exactFocusTarget = focusTarget != null && postAuthorityValid && focusAnchorEvidenceVerified &&
                focusTargetMatchesContract &&
                focusTarget.windowId == post.windowId && focusTarget.packageName == prepared.contract.packageName &&
                Regex(prepared.contract.requiredAnchorPattern, RegexOption.IGNORE_CASE).matches(focusTarget.label) &&
                focusTarget.connectionId == binding.connectionId && focusTarget.sourceSnapshotId == post.captureId &&
                focusTarget.helperSnapshotId == post.captureId && focusTarget.isUniqueInSnapshot &&
                navigationFocusTargetActionsAllowed(
                    clickRequired = emptyState != null,
                    hasClickAction = focusTarget.hasClickAction,
                    hasAccessibilityFocusAction = focusTarget.hasAccessibilityFocusAction,
                )
            val focusDispatchElapsed = uptime()
            if (exactFocusTarget && focusTarget != null && currentServiceStillBound() && focusDispatchElapsed in
                maxOf(click.eventElapsedRealtimeMs, post.capturedAtUptimeMs)..dispatchDeadline &&
                focusTarget.stillCurrent(currentConnectionId)) {
                destinationFocusDiagnostics.put("status", "FOCUS_ACTION_DISPATCHED")
                    .put("window_id", focusTarget.windowId)
                    .put("dispatch_elapsed_realtime_ms", focusDispatchElapsed)
                val focusAuthorization = NavigationActionDispatchAuthorization.afterNavigationGate(
                    binding.requestId, binding.transactionId, leaseToken, NAVIGATION_ACTION_ACCESSIBILITY_FOCUS)
                val focusReturned = runCatching {
                    focusTarget.performNavigationAccessibilityFocus(focusAuthorization, binding.requestId,
                        binding.transactionId, leaseToken, currentConnectionId)
                }.getOrDefault(false)
                destinationFocusDiagnostics.put("focus_action_acknowledged", focusReturned)
                if (focusReturned && currentServiceStillBound() && uptime() <= dispatchDeadline) {
                    destinationFocusDiagnostics.put("focus_action_count", 1)
                    val revalidation = focusTarget.revalidateAfterAccessibilityFocus(currentConnectionId)
                    val revalidationAccepted = revalidation.accepted && currentServiceStillBound() &&
                        uptime() <= dispatchDeadline && focusTarget.windowId == post.windowId
                    destinationFocusDiagnostics.put("currentness_revalidation", revalidation.diagnostics)
                        .put("currentness_revalidation_accepted", revalidationAccepted)
                    if (revalidationAccepted) {
                        focusExpectedPostWindowId = post.windowId
                        val freshPost = capturePostAction(dispatchDeadline, click)
                        captureCallCompletedAt = uptime()
                        if (freshPost == null) {
                            focusCaptureFailure = "post_focus_capture_missing"
                            destinationFocusDiagnostics.put("status", "FRESH_CAPTURE_MISSING")
                        } else {
                            val sameWindow = freshPost.windowId == focusExpectedPostWindowId
                            destinationFocusDiagnostics.put("fresh_capture_id", freshPost.captureId)
                                .put("fresh_capture_window_id", freshPost.windowId)
                                .put("fresh_capture_after_focus", freshPost.capturedAtUptimeMs >= focusDispatchElapsed)
                                .put("same_post_window", sameWindow)
                            if (freshPost.capturedAtUptimeMs < focusDispatchElapsed)
                                focusCaptureFailure = "post_focus_capture_stale"
                            else if (!sameWindow) focusCaptureFailure = "post_window_changed_after_focus"
                            post = freshPost
                            destinationFocusDiagnostics.put("status", if (focusCaptureFailure == null)
                                "FRESH_CAPTURE_RETURNED" else "FRESH_CAPTURE_MISMATCH")
                        }
                    } else {
                        focusCaptureFailure = "destination_focus_currentness_failed"
                        destinationFocusDiagnostics.put("status", "CURRENTNESS_REVALIDATION_FAILED")
                    }
                } else {
                    focusCaptureFailure = if (!focusReturned) "destination_focus_action_not_acknowledged"
                        else "destination_focus_deadline_or_service_changed"
                    destinationFocusDiagnostics.put("status", "FOCUS_ACTION_FAILED")
                }
            } else {
                focusCaptureFailure = when {
                    focusTarget == null -> "destination_focus_target_unavailable"
                    !focusTargetMatchesContract -> "destination_focus_target_mismatch"
                    emptyState != null && !focusTarget.hasClickAction -> "destination_anchor_click_action_unavailable"
                    !focusTarget.hasAccessibilityFocusAction -> "destination_anchor_focus_action_unavailable"
                    !postAuthorityValid -> "destination_post_window_authority_unproven"
                    !currentServiceStillBound() -> "service_changed_before_destination_focus"
                    focusDispatchElapsed !in click.eventElapsedRealtimeMs..dispatchDeadline -> "destination_focus_out_of_bounds"
                    else -> "destination_anchor_focus_target_stale"
                }
                destinationFocusDiagnostics
                    .put("status", if (focusTarget == null) "FOCUS_TARGET_UNAVAILABLE" else "FOCUS_NOT_DISPATCHED")
                    .put("failure_stage", if (focusTarget == null) "target_resolution" else "pre_dispatch_validation")
                if (focusTarget == null) {
                    post.destinationAnchorResolutionFailureCode
                        ?.takeIf { Regex("[A-Z][A-Z0-9_]{0,79}").matches(it) }
                        ?.let { destinationFocusDiagnostics.put("resolver_failure_code", it) }
                }
            }
        } else if (!diagnosticOnly && post != null && (emptyState != null || structuralAnchor != null)) {
            val status = when {
                post.focusInCurrentHierarchy -> "FOCUS_ALREADY_PRESENT"
                !focusDestinationMatches -> "DESTINATION_UNVERIFIED"
                focusAnchorMatchCount != 1 || !focusAnchorEvidenceVerified -> "FOCUS_ANCHOR_EVIDENCE_UNAVAILABLE"
                else -> "FOCUS_NOT_REQUIRED"
            }
            destinationFocusDiagnostics.put("status", status)
        }
        if (post == null) {
            val decisionAt = uptime()
            val diagnostics = strictPostActionDiagnostics(
                binding = binding,
                dispatchElapsed = actionDispatchElapsed,
                deadlineElapsed = dispatchDeadline,
                captureStartedAt = captureCallStartedAt,
                captureCompletedAt = captureCallCompletedAt,
                postStateEvaluatedAt = null,
                decisionAt = decisionAt,
                post = null,
                destinationMatches = null,
                anchorMatchCount = null,
                receiptDecision = "REJECTED",
                failureCode = "NAVIGATION_POST_CAPTURE_MISSING",
                failureStages = listOf("post_capture_missing"),
            ).put("destination_anchor_focus", destinationFocusDiagnostics)
                .put("owner_click_provenance", ownerClickProvenance ?: JSONObject.NULL)
            return if (diagnosticOnly) diagnosticResult("NAVIGATION_POST_CAPTURE_MISSING", true, click, diagnostics)
                else withActivationDiagnostics(rejected(binding, "NAVIGATION_POST_CAPTURE_MISSING")
                    .put("post_state_diagnostics", diagnostics))
        }
        val postStateEvaluatedAt = uptime()
        val postStateMismatches = buildList {
            if (postStateEvaluatedAt > dispatchDeadline) add("post_deadline_exceeded")
            if (post.requestId != binding.requestId) add("request_id_mismatch")
            if (post.transactionId != binding.transactionId) add("transaction_id_mismatch")
            if (post.serviceInstanceId != binding.serviceInstanceId) add("service_instance_mismatch")
            if (post.connectionId != binding.connectionId) add("connection_mismatch")
            val postWindowAuthorityValid = post.postWindowAuthority?.matches(
                binding, click, post, prepared.contract, actionDispatchElapsed, dispatchDeadline)
            if (postWindowAuthorityValid == false) add("post_window_authority_mismatch")
            if (post.windowId != binding.windowId && postWindowAuthorityValid != true) add("window_mismatch")
            if (focusExpectedPostWindowId != null && post.windowId != focusExpectedPostWindowId)
                add("post_window_changed_after_focus")
            if (focusCaptureFailure != null) add(focusCaptureFailure!!)
            if (post.captureId.isBlank() || post.captureId == binding.captureId) add("capture_id_missing_or_reused")
            if (post.capturedAtUptimeMs < now || post.capturedAtUptimeMs > dispatchDeadline)
                add("capture_time_out_of_bounds")
            if (post.hierarchyDigest.isBlank() || post.hierarchyDigest == binding.baselineHierarchyDigest)
                add("hierarchy_digest_missing_or_unchanged")
            if (!post.accessibilityFocused) add("accessibility_focus_missing")
            if (!post.focusInCurrentHierarchy) add("focus_not_in_current_hierarchy")
            if (post.focusWindowId != post.windowId) add("focus_window_mismatch")
        }
        if (postStateMismatches.isNotEmpty()) {
            val decisionAt = uptime()
            // These contract checks are diagnostic only on the stale/incomplete path;
            // the existing post-state rejection remains authoritative.
            val diagnosticDestinationMatches = runCatching {
                prepared.contract.destinationMatches(post.labels, post.structureEvidence,
                    post.rootPackageName, post.rootClassName)
            }.getOrNull()
            val diagnosticAnchorMatchCount = if (diagnosticDestinationMatches == true) {
                runCatching { prepared.contract.anchorMatchCount(post.labels,
                    post.captureSample?.requiredAnchorStructuralMatchCount) }.getOrNull()
            } else null
            val clickSource = click.source as? AccessibilityNodeInfo
            val clickSourceUniqueId = if (Build.VERSION.SDK_INT >= 33 && clickSource != null) {
                runCatching { clickSource.uniqueId.orEmpty() }.getOrDefault("")
            } else ""
            val sourceIdStatus = when {
                clickSource == null -> "SOURCE_NODE_UNAVAILABLE"
                Build.VERSION.SDK_INT < 33 -> "API_UNAVAILABLE"
                clickSourceUniqueId.isBlank() -> "FIELD_ABSENT"
                else -> "FIELD_PRESENT"
            }
            val ownerSourceIdMatch = when {
                binding.sourceIdentity.ownerSourceNodeIdStatus == "FIELD_ABSENT" -> JSONObject.NULL
                sourceIdStatus != "FIELD_PRESENT" -> JSONObject.NULL
                else -> clickSourceUniqueId == binding.sourceIdentity.ownerSourceNodeId
            }
            val postDiagnostics = strictPostActionDiagnostics(
                binding = binding,
                dispatchElapsed = actionDispatchElapsed,
                deadlineElapsed = dispatchDeadline,
                captureStartedAt = captureCallStartedAt,
                captureCompletedAt = captureCallCompletedAt,
                postStateEvaluatedAt = postStateEvaluatedAt,
                decisionAt = decisionAt,
                post = post,
                destinationMatches = diagnosticDestinationMatches,
                anchorMatchCount = diagnosticAnchorMatchCount,
                receiptDecision = "REJECTED",
                failureCode = "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
                failureStages = postStateMismatches,
            ).put("destination_anchor_focus", destinationFocusDiagnostics)
                .put("owner_click_provenance", ownerClickProvenance ?: JSONObject.NULL)
                .put("activation_owner_relation", prepared.contract.activationOwnerRelation?.toJson() ?: JSONObject.NULL)
                .put("action_owner_path", JSONArray(prepared.contractAuthorityTarget.nodePath))
                .put("action_target_path", JSONArray(binding.nodePath))
                .put("event_source_status", "EXACT_RETAINED_NODE_MATCH")
                .put("event_source_request_id", click.requestId)
                .put("event_source_transaction_id", click.transactionId)
                .put("event_source_service_instance_id", click.serviceInstanceId)
                .put("event_source_connection_id", click.connectionId)
                .put("event_source_connection_match", click.connectionId == binding.connectionId)
                .put("event_source_event_type", click.eventType)
                .put("event_source_event_window_id", click.windowId)
                .put("event_source_node_window_id", clickSource?.windowId ?: JSONObject.NULL)
                .put("event_source_node_id_status", sourceIdStatus)
                .put("event_source_node_id_sha256", if (sourceIdStatus == "FIELD_PRESENT")
                    runCatching {
                        java.security.MessageDigest.getInstance("SHA-256")
                            .digest(clickSourceUniqueId.toByteArray(Charsets.UTF_8))
                            .joinToString("") { "%02x".format(it) }
                    }.getOrNull() ?: JSONObject.NULL else JSONObject.NULL)
                .put("event_source_owner_node_id_match", ownerSourceIdMatch)
                .put("owner_receipt_click_event_id", ownerReceipt?.optString("clickEventId") ?: JSONObject.NULL)
                .put("post_request_id", post.requestId)
                .put("post_transaction_id", post.transactionId)
                .put("post_service_instance_id", post.serviceInstanceId)
                .put("post_connection_id", post.connectionId)
                .put("post_window_id", post.windowId)
                .put("post_capture_id", post.captureId)
                .put("post_captured_at_uptime_ms", post.capturedAtUptimeMs)
                .put("post_hierarchy_digest_changed", post.hierarchyDigest.isNotBlank() &&
                    post.hierarchyDigest != binding.baselineHierarchyDigest)
                .put("focus_window_id", post.focusWindowId ?: JSONObject.NULL)
                .put("focus_window_id_status", if (post.focusWindowId == null) "FIELD_ABSENT" else "FIELD_PRESENT")
                .put("accessibility_focused", post.accessibilityFocused)
                .put("focus_in_current_hierarchy", post.focusInCurrentHierarchy)
            return if (diagnosticOnly) diagnosticResult("NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE", true,
                click, postDiagnostics).put("post_state_mismatch_fields", JSONArray(postStateMismatches))
                else withActivationDiagnostics(rejected(binding, "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE")
                    .put("post_state_mismatch_fields", JSONArray(postStateMismatches))
                    .put("post_state_diagnostics", postDiagnostics))
        }
        val destinationMatches = prepared.contract.destinationMatches(post.labels, post.structureEvidence,
            post.rootPackageName, post.rootClassName)
        val anchorMatchCount = if (destinationMatches) prepared.contract.anchorMatchCount(post.labels,
            post.captureSample?.requiredAnchorStructuralMatchCount) else 0
        val anchorFailure = !destinationMatches || anchorMatchCount != 1
        val decisionAt = uptime()
        val diagnostics = strictPostActionDiagnostics(
            binding = binding,
            dispatchElapsed = actionDispatchElapsed,
            deadlineElapsed = dispatchDeadline,
            captureStartedAt = captureCallStartedAt,
            captureCompletedAt = captureCallCompletedAt,
            postStateEvaluatedAt = postStateEvaluatedAt,
            decisionAt = decisionAt,
            post = post,
            destinationMatches = destinationMatches,
            anchorMatchCount = if (destinationMatches) anchorMatchCount else null,
            receiptDecision = when {
                diagnosticOnly -> "DIAGNOSTIC_ONLY_NO_CREDIT"
                anchorFailure -> "REJECTED"
                else -> "VERIFIED_NAVIGATION"
            },
            failureCode = when {
                diagnosticOnly -> "DIAGNOSTIC_ONLY_NO_NAVIGATION_CREDIT"
                anchorFailure -> "NAVIGATION_DESTINATION_FOCUS_ANCHOR_UNPROVEN"
                else -> null
            },
            failureStages = buildList {
                if (anchorFailure) add("required_destination_anchor_unproven")
                if (diagnosticOnly) add("diagnostic_mode_never_grants_navigation_credit")
            },
        ).put("destination_anchor_focus", destinationFocusDiagnostics)
                .put("owner_click_provenance", ownerClickProvenance ?: JSONObject.NULL)
            .put("activation_owner_relation", prepared.contract.activationOwnerRelation?.toJson() ?: JSONObject.NULL)
            .put("action_owner_path", JSONArray(prepared.contractAuthorityTarget.nodePath))
            .put("action_target_path", JSONArray(binding.nodePath))
        if (anchorFailure)
            return if (diagnosticOnly) diagnosticResult("NAVIGATION_DESTINATION_FOCUS_ANCHOR_UNPROVEN", true,
                click, diagnostics)
                else withActivationDiagnostics(rejected(binding, "NAVIGATION_DESTINATION_FOCUS_ANCHOR_UNPROVEN")
                    .put("post_state_diagnostics", diagnostics))
        if (diagnosticOnly)
            return diagnosticResult("DIAGNOSTIC_ONLY_NO_NAVIGATION_CREDIT", true, click, diagnostics)
        val success = JSONObject().put("status", "VERIFIED_NAVIGATION").put("verified_navigation", true)
            .put("visit_authority", false).put("c5_credit", false).put("action_call_count", 1)
            .put("request_id", binding.requestId).put("transaction_id", binding.transactionId)
            .put("run_id", binding.runId).put("invocation_id", binding.invocationId)
            .put("scenario_id", binding.scenarioId).put("owner_capture_request_id", binding.ownerCaptureReqId)
            .put("action", binding.action)
            .put("owner_lease_id", binding.ownerLeaseId)
            .put("service_instance_id", binding.serviceInstanceId).put("connection_id", binding.connectionId)
            .put("window_id", binding.windowId).put("source_capture_id", binding.captureId)
            .put("helper_snapshot_id", binding.helperSnapshotId).put("post_capture_id", post.captureId)
            .put("source_identity", JSONObject().put("request_id", binding.sourceIdentity.requestId)
                .put("process_epoch", binding.sourceIdentity.processEpoch)
                .put("generation", binding.sourceIdentity.generation)
                .put("service_instance_id", binding.sourceIdentity.serviceInstanceId)
                .put("capture_sequence", binding.sourceIdentity.captureSequence)
                .put("root_digest", binding.sourceIdentity.rootDigest)
                .put("candidate_digest", binding.sourceIdentity.candidateDigest)
                .put("capture_key", binding.sourceIdentity.captureKey)
                .put("connection_epoch", binding.sourceIdentity.connectionEpoch)
                .put("boot_epoch", binding.sourceIdentity.bootEpoch)
                .put("owner_source_node_id", binding.sourceIdentity.ownerSourceNodeId)
                .put("owner_source_node_id_status", binding.sourceIdentity.ownerSourceNodeIdStatus))
            .put("effect_contract_id", binding.effectContractId).put("effect_contract_digest", binding.effectContractDigest)
            .put("post_state_diagnostics", diagnostics)
            .put("owner_click_provenance", ownerClickProvenance ?: JSONObject.NULL)
        return if (focusDiagnostics != null) success.put("activation_mode", binding.activationMode)
            .put("activation_diagnostics", focusDiagnostics) else success
    }

    private fun strictPostActionDiagnostics(
        binding: NavigationActionBinding,
        dispatchElapsed: Long,
        deadlineElapsed: Long,
        captureStartedAt: Long,
        captureCompletedAt: Long,
        postStateEvaluatedAt: Long?,
        decisionAt: Long,
        post: NavigationPostActionEvidence?,
        destinationMatches: Boolean?,
        anchorMatchCount: Int?,
        receiptDecision: String,
        failureCode: String?,
        failureStages: List<String>,
    ): JSONObject {
        val anchorOutcome = when {
            post == null -> "NOT_EVALUATED_CAPTURE_MISSING"
            destinationMatches == null -> "NOT_EVALUATED"
            destinationMatches == false -> "DESTINATION_NOT_MATCHED"
            anchorMatchCount == null -> "NOT_EVALUATED"
            anchorMatchCount == 0 -> "MISSING"
            anchorMatchCount == 1 -> "MATCHED"
            else -> "AMBIGUOUS"
        }
        val stages = JSONArray()
        failureStages.forEach { stages.put(it) }
        val sample = post?.captureSample
        val sampleJson = sample?.let { runCatching { it.toJson() }.getOrNull() }
        val samplePersistenceStatus = when {
            post == null -> "NO_CAPTURE"
            sample == null -> "UNAVAILABLE"
            sampleJson == null -> "SERIALIZATION_FAILED"
            sample.completeness != "COMPLETE" -> sample.completeness
            else -> "EMBEDDED_COMPLETE"
        }
        return JSONObject()
            .put("diagnostic_schema", "strict-post-action-v1")
            .put("request_id", binding.requestId)
            .put("transaction_id", binding.transactionId)
            .put("action", binding.action)
            .put("dispatch_elapsed_realtime_ms", dispatchElapsed)
            .put("dispatch_deadline_elapsed_realtime_ms", deadlineElapsed)
            .put("capture_call_start_elapsed_realtime_ms", captureStartedAt)
            .put("capture_call_completion_elapsed_realtime_ms", captureCompletedAt)
            .put("post_state_evaluation_elapsed_realtime_ms", postStateEvaluatedAt ?: JSONObject.NULL)
            .put("receipt_decision_elapsed_realtime_ms", decisionAt)
            .put("source_service_instance_id", binding.sourceIdentity.serviceInstanceId)
            .put("source_connection_epoch", binding.sourceIdentity.connectionEpoch)
            .put("source_capture_request_id", binding.sourceIdentity.requestId)
            .put("source_capture_key", binding.sourceIdentity.captureKey)
            .put("source_capture_generation", binding.sourceIdentity.generation)
            .put("source_capture_sequence", binding.sourceIdentity.captureSequence)
            .put("action_service_instance_id", binding.serviceInstanceId)
            .put("action_connection_id", binding.connectionId)
            .put("action_window_id", binding.windowId)
            .put("capture_request_id", post?.requestId ?: JSONObject.NULL)
            .put("capture_transaction_id", post?.transactionId ?: JSONObject.NULL)
            .put("capture_service_instance_id", post?.serviceInstanceId ?: JSONObject.NULL)
            .put("capture_connection_id", post?.connectionId ?: JSONObject.NULL)
            .put("capture_window_id", post?.windowId ?: JSONObject.NULL)
            .put("post_window_id", post?.windowId ?: JSONObject.NULL)
            .put("post_window_authority", post?.postWindowAuthority?.toJson() ?: JSONObject.NULL)
            .put("post_structure_evidence", post?.structureEvidence?.toJson() ?: JSONObject.NULL)
            .put("capture_call_result", if (post == null) "MISSING" else "RETURNED")
            .put("post_capture_id", post?.captureId ?: JSONObject.NULL)
            .put("post_captured_at_elapsed_realtime_ms", post?.capturedAtUptimeMs ?: JSONObject.NULL)
            .put("post_capture_completeness", if (post == null) "NO_COMPLETE_SAMPLE" else "COMPLETE")
            .put("post_capture_failure_stage", if (post == null) "post_capture_missing" else JSONObject.NULL)
            .put("post_capture_node_count", post?.nodeCount ?: JSONObject.NULL)
            .put("post_capture_root_package", post?.rootPackageName ?: JSONObject.NULL)
            .put("post_capture_root_class", post?.rootClassName ?: JSONObject.NULL)
            .put("post_hierarchy_digest", post?.hierarchyDigest ?: JSONObject.NULL)
            .put("post_capture_sample_persistence_status", samplePersistenceStatus)
            .put("post_capture_sample_artifact", sampleJson ?: JSONObject.NULL)
            .put("focus_window_id", post?.focusWindowId ?: JSONObject.NULL)
            .put("focus_window_id_status", when {
                post == null -> "CAPTURE_MISSING"
                post.focusWindowId == null -> "FIELD_ABSENT"
                else -> "FIELD_PRESENT"
            })
            .put("accessibility_focused", post?.accessibilityFocused ?: JSONObject.NULL)
            .put("focus_in_current_hierarchy", post?.focusInCurrentHierarchy ?: JSONObject.NULL)
            .put("required_destination_match", destinationMatches ?: JSONObject.NULL)
            .put("required_anchor_match_count", anchorMatchCount ?: JSONObject.NULL)
            .put("required_anchor_outcome", anchorOutcome)
            .put("receipt_decision", receiptDecision)
            .put("receipt_failure_code", failureCode ?: JSONObject.NULL)
            .put("failure_stages", stages)
    }

    private fun validBinding(binding: NavigationActionBinding): Boolean =
        listOf(binding.runId, binding.invocationId, binding.requestId, binding.transactionId,
            binding.scenarioId, binding.ownerCaptureReqId, binding.ownerLeaseId,
            binding.serviceInstanceId, binding.connectionId, binding.sourceSnapshotId,
            binding.helperSnapshotId, binding.captureId, binding.descriptorDigest, binding.baselineHierarchyDigest,
            binding.effectContractId, binding.effectContractDigest,
            binding.sourceIdentity.requestId, binding.sourceIdentity.processEpoch,
            binding.sourceIdentity.serviceInstanceId, binding.sourceIdentity.rootDigest,
            binding.sourceIdentity.candidateDigest, binding.sourceIdentity.captureKey,
            binding.sourceIdentity.connectionEpoch, binding.sourceIdentity.bootEpoch,
            binding.sourceIdentity.ownerSourceNodeIdStatus).all { it.isNotBlank() } &&
            validOwnerSourceNodeIdentity(binding.sourceIdentity) &&
            binding.sourceIdentity.generation > 0L && binding.sourceIdentity.captureSequence > 0L &&
            binding.sourceIdentity.serviceInstanceId == binding.serviceInstanceId &&
            binding.sourceIdentity.captureKey == binding.sourceSnapshotId &&
            binding.action == NAVIGATION_ACTION_CLICK &&
            binding.activationMode in setOf(NAVIGATION_ACTIVATION_DIRECT_CLICK,
                NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
                NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK) &&
            binding.windowId >= 0 && binding.nodePath.size <= 80 && binding.nodePath.all { it in 0..4096 } &&
            binding.descriptorDigest.matches(Regex("[0-9a-f]{64}")) &&
            binding.effectContractDigest.matches(Regex("[0-9a-f]{64}"))

    private fun validDeclaredActivationTarget(
        binding: NavigationActionBinding,
        contract: NavigationEffectContract,
        parent: NavigationActionTargetLease,
        child: NavigationActionTargetLease,
        currentConnectionId: String,
    ): Boolean {
        val relation = contract.activationOwnerRelation ?: return false
        return relation.isWellFormed() && parent.windowId == binding.windowId &&
            child.windowId == parent.windowId && parent.packageName == contract.packageName &&
            parent.packageName == child.packageName && parent.connectionId == binding.connectionId &&
            child.connectionId == binding.connectionId && currentConnectionId == binding.connectionId &&
            child.sourceSnapshotId == parent.sourceSnapshotId && child.helperSnapshotId == parent.helperSnapshotId &&
            child.baselineHierarchyDigest == parent.baselineHierarchyDigest &&
            child.nodePath == parent.nodePath + relation.childIndex &&
            Regex(relation.childClassPattern).matches(child.className) &&
            child.resourceId == relation.childResourceId && child.isUniqueInSnapshot && child.hasClickAction &&
            child.stillCurrent(currentConnectionId) && parent.stillCurrent(currentConnectionId)
    }

    private fun rejected(binding: NavigationActionBinding, code: String): JSONObject {
        val result = JSONObject().put("status", "REJECTED").put("failure_code", code)
            .put("verified_navigation", false).put("visit_authority", false).put("c5_credit", false)
            .put("request_id", binding.requestId).put("transaction_id", binding.transactionId)
            .put("run_id", binding.runId).put("invocation_id", binding.invocationId)
        if (binding.activationMode != NAVIGATION_ACTIVATION_DIRECT_CLICK)
            result.put("activation_mode", binding.activationMode)
        return result
    }
}
