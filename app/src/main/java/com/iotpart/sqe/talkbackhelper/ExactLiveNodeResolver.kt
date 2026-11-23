package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityEvent
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

internal data class ExactApplicationWindow(val id:Int,val type:Int,val active:Boolean,val root:AccessibilityNodeInfo?)

internal val EXACT_NODE_FOCUS_CURRENTNESS_DESCRIPTOR_FIELDS = listOf(
    "text", "contentDescription", "viewIdResourceName", "className", "packageName",
    "sourceNodeId", "windowId", "boundsInScreen", "clickable", "effectiveClickable",
    "enabled", "focusable", "focused", "inputFocused", "accessibilityFocused", "selected",
    "scrollable", "isScrollable", "checkable", "checked", "visibleToUser",
    "isVisibleToUser", "actions",
)
internal const val MAX_FOCUS_REVALIDATION_ACTION_IDS = 64

internal data class ExactNodeActionIds(val ids: List<Int>, val complete: Boolean)

internal data class ExactHierarchyNodeFingerprint(
    val descriptorDigest: String,
    val focusNeutralDescriptorDigest: String,
    val actionIds: ExactNodeActionIds,
    val accessibilityFocused: Boolean?,
)

internal data class ExactHierarchyFingerprintSnapshot(
    val strictHierarchyDigest: String,
    val focusNeutralHierarchyDigest: String,
    val byPath: Map<List<Int>, ExactHierarchyNodeFingerprint>,
)

internal fun exactDeclaredChildFocusHierarchyMatches(
    expected: Map<List<Int>, ExactHierarchyNodeFingerprint>,
    current: Map<List<Int>, ExactHierarchyNodeFingerprint>,
    childPath: List<Int>,
): Boolean {
    if (expected.isEmpty() || expected.size > 5_000 || expected.keys != current.keys ||
        childPath !in expected) return false
    val focusActions = setOf(
        AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS,
        AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS,
    )
    for ((path, before) in expected) {
        val after = current[path] ?: return false
        if (path == childPath) {
            if (before.focusNeutralDescriptorDigest.isBlank() ||
                before.focusNeutralDescriptorDigest != after.focusNeutralDescriptorDigest ||
                !before.actionIds.complete || !after.actionIds.complete ||
                after.accessibilityFocused != true) return false
            val delta = exactNodeActionIdDelta(before.actionIds, after.actionIds)
            if (!delta.complete || delta.added.any { it !in focusActions } ||
                delta.removed.any { it !in focusActions }) return false
        } else if (before.descriptorDigest != after.descriptorDigest) {
            return false
        }
    }
    return true
}

internal fun exactNodeActionIds(descriptor: JSONObject): ExactNodeActionIds {
    val actions = descriptor.optJSONArray("actions") ?: return ExactNodeActionIds(emptyList(), false)
    val ids = mutableListOf<Int>()
    var complete = actions.length() <= MAX_FOCUS_REVALIDATION_ACTION_IDS
    val count = minOf(actions.length(), MAX_FOCUS_REVALIDATION_ACTION_IDS)
    for (index in 0 until count) {
        val rawId = actions.optJSONObject(index)?.opt("id")
        val number = rawId as? Number
        val longId = number?.toLong()
        if (number == null || longId == null || longId !in 0..Int.MAX_VALUE.toLong() ||
            number.toDouble() != longId.toDouble()) {
            complete = false
            continue
        }
        ids += longId.toInt()
    }
    return ExactNodeActionIds(ids.distinct().sorted(), complete)
}

internal data class ExactNodeActionIdDelta(
    val added: List<Int>,
    val removed: List<Int>,
    val complete: Boolean,
)

internal fun exactNodeActionIdDelta(
    expected: ExactNodeActionIds,
    current: ExactNodeActionIds,
): ExactNodeActionIdDelta = ExactNodeActionIdDelta(
    added = current.ids.filterNot(expected.ids.toSet()::contains).sorted().take(MAX_FOCUS_REVALIDATION_ACTION_IDS),
    removed = expected.ids.filterNot(current.ids.toSet()::contains).sorted().take(MAX_FOCUS_REVALIDATION_ACTION_IDS),
    complete = expected.complete && current.complete,
)

internal fun exactNodeDescriptorForFocusCurrentness(
    raw: JSONObject,
    normalizeAccessibilityFocus: Boolean,
    normalizeFocusActionIds: Boolean = false,
): JSONObject {
    return JSONObject().apply {
        EXACT_NODE_FOCUS_CURRENTNESS_DESCRIPTOR_FIELDS
            .filterNot { normalizeAccessibilityFocus && it == "accessibilityFocused" }
            .forEach { field ->
                val actions = if (field == "actions") raw.optJSONArray(field) else null
                val value = if (normalizeFocusActionIds && actions != null) {
                    focusNeutralActionList(actions)
                } else {
                    raw.opt(field) ?: JSONObject.NULL
                }
                put(field, value)
            }
    }
}

private fun focusNeutralActionList(actions: JSONArray): JSONArray {
    val focusActionIds = setOf(
        AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS,
        AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS,
    )
    return JSONArray().apply {
        for (index in 0 until actions.length()) {
            val action = actions.optJSONObject(index)
            val number = action?.opt("id") as? Number
            val longId = number?.toLong()
            val actionId = if (number != null && longId != null &&
                number.toDouble() == longId.toDouble() && longId in 0..Int.MAX_VALUE.toLong()) {
                longId.toInt()
            } else null
            if (actionId != null && actionId in focusActionIds) continue
            put(actions.opt(index))
        }
    }
}

/** Stores only per-field hashes so revalidation can name changed fields without retaining their values. */
internal fun exactNodeDescriptorFieldHashes(descriptor: JSONObject): Map<String, String> =
    EXACT_NODE_FOCUS_CURRENTNESS_DESCRIPTOR_FIELDS
        .filter { it != "accessibilityFocused" && descriptor.has(it) }
        .associateWith { field ->
            val value = descriptor.opt(field) ?: JSONObject.NULL
            ExactProtocolJson.sha256(ExactProtocolJson.canonical(
                JSONObject().put("field", field).put("value", value)))
        }

internal fun exactNodeDescriptorChangedFields(
    expectedFieldHashes: Map<String, String>,
    currentDescriptor: JSONObject,
): List<String> {
    val currentFieldHashes = exactNodeDescriptorFieldHashes(currentDescriptor)
    return EXACT_NODE_FOCUS_CURRENTNESS_DESCRIPTOR_FIELDS.filter { field ->
        field != "accessibilityFocused" && expectedFieldHashes[field] != currentFieldHashes[field]
    }
}

/** Keeps the exact reference that supplied the validated descriptor. No legacy target finder. */
internal class ExactLiveNodeResolver(private val windows:()->List<ExactApplicationWindow>) {
    inner class ObservationTarget internal constructor(
        private val node: AccessibilityNodeInfo,
        val windowId: Int,
        val nodePath: List<Int>,
        val descriptorDigest: String,
        val sourceSnapshotId: String,
        val sourceNodeId: String,
        val helperSnapshotId: String,
        val baselineHierarchyDigest: String,
        private val focusNeutralDescriptorDigest: String,
        private val focusNeutralDescriptorFieldHashes: Map<String, String>,
        private val focusNeutralActionIds: ExactNodeActionIds,
        private val focusNeutralHierarchyDigest: String,
        private val baselineHierarchyNodeFingerprints: Map<List<Int>, ExactHierarchyNodeFingerprint>,
        val connectionId: String,
        val independentDescendants: Int,
        val independentSiblings: Int,
        val descriptorMatchCount: Int,
        private val capturedAt: Long,
        val clickActionAllowed: Boolean = true,
    ) {
        val packageName: String get() = node.packageName?.toString().orEmpty()
        val className: String get() = node.className?.toString().orEmpty()
        val resourceId: String get() = node.viewIdResourceName.orEmpty()
        val label: String get() = node.text?.toString()?.takeIf { it.isNotBlank() }
            ?: node.contentDescription?.toString().orEmpty()
        fun subtreeLabels(): List<String> {
            val labels = mutableListOf<String>()
            var count = 0
            var complete = true
            fun walk(current: AccessibilityNodeInfo, depth: Int) {
                if (depth > 80 || ++count > 1_000) { complete = false; return }
                listOf(current.text, current.contentDescription, current.viewIdResourceName).forEach { value ->
                    value?.toString()?.takeIf { it.isNotBlank() }?.let(labels::add)
                }
                for (index in 0 until current.childCount) {
                    val child = runCatching { current.getChild(index) }.getOrNull()
                    if (child == null) { complete = false; return }
                    walk(child, depth + 1)
                }
            }
            walk(node, 0)
            return if (complete) labels else emptyList()
        }
        fun descendantEvidence(): Pair<Boolean, List<NavigationDescendantEvidence>> {
            val evidence = mutableListOf<NavigationDescendantEvidence>()
            var complete = true
            var count = 0
            fun walk(current: AccessibilityNodeInfo, depth: Int) {
                if (depth > 80 || ++count > 1_000) { complete = false; return }
                if (current !== node) {
                    val label = current.text?.toString()?.takeIf { it.isNotBlank() }
                        ?: current.contentDescription?.toString().orEmpty()
                    evidence += NavigationDescendantEvidence(
                        className = current.className?.toString().orEmpty(),
                        resourceId = current.viewIdResourceName.orEmpty(),
                        label = label,
                        clickable = current.isClickable,
                        longClickable = current.isLongClickable,
                        checkable = current.isCheckable,
                        editable = current.isEditable,
                        scrollable = current.isScrollable,
                        actionIds = current.actionList.map { it.id }.toSet(),
                    )
                }
                for (index in 0 until current.childCount) {
                    val child = runCatching { current.getChild(index) }.getOrNull()
                    if (child == null) { complete = false; return }
                    walk(child, depth + 1)
                }
            }
            for (index in 0 until node.childCount) {
                val child = runCatching { node.getChild(index) }.getOrNull()
                if (child == null) { complete = false; break }
                walk(child, 1)
            }
            return complete to if (complete) evidence else emptyList()
        }
        val hasClickAction: Boolean get() = node.actionList.any { it.id == AccessibilityNodeInfo.ACTION_CLICK }
        val hasAccessibilityFocusAction: Boolean
            get() = node.actionList.any { it.id == AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS }

        fun eventSourceMatches(source: AccessibilityNodeInfo?, eventWindowId: Int, currentConnectionId: String): Boolean =
            SystemClock.elapsedRealtime() - capturedAt in 0..2_500 &&
                currentConnectionId == connectionId && source != null && source == node &&
                eventWindowId == windowId && source.windowId == windowId

        fun identifiesRetainedNode(candidate: AccessibilityNodeInfo): Boolean =
            candidate == node && candidate.windowId == windowId

        /** Wraps this same retained observation node; it never resolves a replacement. */
        internal fun navigationActionLease(): NavigationTargetLease = NavigationTargetLease(this, node)

        /** Resolves only the contract-declared direct child while retaining this approved parent snapshot. */
        internal fun exactDeclaredActivationChild(
            relation: NavigationActivationOwnerRelation,
            currentConnectionId: String,
        ): NavigationActionTargetLease? = runCatching {
            ExactActionContract.requireThat(relation.isWellFormed() && stillCurrent(currentConnectionId),
                "NAVIGATION_ACTIVATION_PARENT_STALE")
            val childPath = nodePath + relation.childIndex
            val active = windows().filter { it.id == windowId && it.type == 1 && it.active }
            ExactActionContract.requireThat(active.size == 1, "NAVIGATION_ACTIVATION_WINDOW_MISMATCH")
            val root = active.single().root ?: throw ExactActionRejected("NAVIGATION_ACTIVATION_ROOT_MISSING")
            ExactActionContract.requireThat(hierarchyDigest(root) == baselineHierarchyDigest,
                "NAVIGATION_ACTIVATION_SOURCE_TREE_CHANGED")
            val child = nodeAtPath(root, childPath)
            ExactActionContract.requireThat(child.packageName?.toString() == packageName &&
                child.windowId == windowId && Regex(relation.childClassPattern).matches(child.className?.toString().orEmpty()) &&
                child.viewIdResourceName == relation.childResourceId && child.isEnabled && child.isVisibleToUser &&
                child.isClickable && child.actionList.any { it.id == AccessibilityNodeInfo.ACTION_CLICK },
                "NAVIGATION_ACTIVATION_CHILD_NOT_ACTIONABLE")
            val (childObservation, retainedChild) = captureTarget(
                expectedWindowId = windowId,
                expectedPackage = packageName,
                nodePath = childPath,
                expectedDescriptorDigest = descriptorDigest(child),
                sourceSnapshotId = sourceSnapshotId,
                connectionId = currentConnectionId,
                helperSnapshotIdOverride = helperSnapshotId,
            )
            ExactActionContract.requireThat(childObservation.baselineHierarchyDigest == baselineHierarchyDigest &&
                childObservation.helperSnapshotId == helperSnapshotId &&
                childObservation.descriptorMatchCount == 1 && retainedChild == child &&
                stillCurrent(currentConnectionId), "NAVIGATION_ACTIVATION_CHILD_STALE")
            childObservation.navigationActionLease()
        }.getOrNull()

        fun stillCurrent(currentConnectionId: String): Boolean {
            if (SystemClock.elapsedRealtime() - capturedAt !in 0..2_500 || currentConnectionId != connectionId ||
                !runCatching { node.refresh() }.getOrDefault(false) || node.windowId != windowId) return false
            val matching = windows().filter { it.id == windowId && it.type == 1 && it.active }
            if (matching.size != 1) return false
            val root = matching.single().root ?: return false
            val atPath = runCatching { nodeAtPath(root, nodePath) }.getOrNull() ?: return false
            return atPath == node && descriptorDigest(atPath) == this.descriptorDigest &&
                hierarchyDigest(root) == baselineHierarchyDigest
        }

        /** Revalidate from one current window/root sample; only accessibility focus is normalized. */
        fun revalidateAfterAccessibilityFocus(currentConnectionId: String): NavigationFocusRevalidationResult {
            val diagnostics = JSONObject().put("diagnostics_available", true)
            val leaves = listOf(
                "capture_lease_fresh", "connection_identity_matches", "retained_node_refresh_succeeded",
                "window_identity_matches", "retained_node_accessibility_focused", "unique_active_window",
                "root_available", "node_at_path_resolved", "retained_node_identity_matches",
                "focus_neutral_descriptor_matches", "focus_neutral_hierarchy_digest_matches",
                "capture_complete",
            )
            leaves.forEach { diagnostics.put(it, JSONObject.NULL) }
            diagnostics.put("first_failed_check", JSONObject.NULL)

            fun finish(accepted: Boolean, failedCheck: String? = null): NavigationFocusRevalidationResult {
                if (failedCheck != null) diagnostics.put("first_failed_check", failedCheck)
                diagnostics.put("aggregate_accepted", accepted)
                return NavigationFocusRevalidationResult(accepted, diagnostics)
            }
            fun check(name: String, value: Boolean): Boolean {
                diagnostics.put(name, value)
                return value
            }

            val leaseAgeMs = SystemClock.elapsedRealtime() - capturedAt
            diagnostics.put("capture_lease_age_ms", leaseAgeMs)
            if (!check("capture_lease_fresh", leaseAgeMs in 0..2_500))
                return finish(false, "capture_lease_fresh")
            if (!check("connection_identity_matches", currentConnectionId == connectionId))
                return finish(false, "connection_identity_matches")
            val refreshSucceeded = runCatching { node.refresh() }.getOrDefault(false)
            if (!check("retained_node_refresh_succeeded", refreshSucceeded))
                return finish(false, "retained_node_refresh_succeeded")
            if (!check("window_identity_matches", node.windowId == windowId))
                return finish(false, "window_identity_matches")
            if (!check("retained_node_accessibility_focused", node.isAccessibilityFocused))
                return finish(false, "retained_node_accessibility_focused")

            val matching = windows().filter { it.id == windowId && it.type == 1 && it.active }
            if (!check("unique_active_window", matching.size == 1))
                return finish(false, "unique_active_window")
            val root = matching.single().root
            if (!check("root_available", root != null)) {
                diagnostics.put("capture_complete", false)
                return finish(false, "root_available")
            }
            val currentRoot = root ?: return finish(false, "root_available")
            val atPath = runCatching { nodeAtPath(currentRoot, nodePath) }.getOrNull()
            if (!check("node_at_path_resolved", atPath != null)) {
                diagnostics.put("capture_complete", false)
                return finish(false, "node_at_path_resolved")
            }
            val currentNode = atPath ?: return finish(false, "node_at_path_resolved")
            if (!check("retained_node_identity_matches", currentNode == node))
                return finish(false, "retained_node_identity_matches")

            val currentRawDescriptor = A11yNavigator.hierarchyNodeToJson(currentNode, intArrayOf(0), 0)
            val currentActionIds = exactNodeActionIds(currentRawDescriptor)
            val currentDescriptor = exactNodeDescriptorForFocusCurrentness(
                currentRawDescriptor,
                normalizeAccessibilityFocus = true,
                normalizeFocusActionIds = true,
            )
            val currentDescriptorDigest = ExactProtocolJson.sha256(ExactProtocolJson.canonical(currentDescriptor))
            val changedDescriptorFields = exactNodeDescriptorChangedFields(
                focusNeutralDescriptorFieldHashes, currentDescriptor)
            val actionIdDelta = exactNodeActionIdDelta(
                focusNeutralActionIds, currentActionIds)
            diagnostics.put("expected_focus_neutral_descriptor_digest", focusNeutralDescriptorDigest)
                .put("current_focus_neutral_descriptor_digest", currentDescriptorDigest)
                .put("focus_neutral_descriptor_mismatch_fields", JSONArray(changedDescriptorFields))
                .put("focus_neutral_action_ids_added", JSONArray(actionIdDelta.added))
                .put("focus_neutral_action_ids_removed", JSONArray(actionIdDelta.removed))
                .put("focus_neutral_action_id_delta_complete", actionIdDelta.complete)
            if (!check("focus_neutral_descriptor_matches",
                    currentDescriptorDigest == focusNeutralDescriptorDigest))
                return finish(false, "focus_neutral_descriptor_matches")

            val currentHierarchyDigest = hierarchyDigest(
                currentRoot, normalizeAccessibilityFocus = true, normalizeFocusActionIds = true)
            diagnostics.put("expected_focus_neutral_hierarchy_digest", focusNeutralHierarchyDigest)
                .put("current_focus_neutral_hierarchy_digest", currentHierarchyDigest)
                .put("capture_complete", true)
            if (!check("focus_neutral_hierarchy_digest_matches",
                    currentHierarchyDigest == focusNeutralHierarchyDigest))
                return finish(false, "focus_neutral_hierarchy_digest_matches")
            return finish(true)
        }

        /** Revalidate the exact declared child focus while retaining the parent and every other node strictly. */
        fun revalidateAfterDeclaredChildAccessibilityFocus(
            currentConnectionId: String,
            authorizationTarget: NavigationActionTargetLease,
            relation: NavigationActivationOwnerRelation,
            focusProof: NavigationFocusEvidence,
        ): NavigationFocusRevalidationResult {
            val diagnostics = JSONObject().put("diagnostics_available", true)
            fun finish(accepted: Boolean, firstFailure: String? = null): NavigationFocusRevalidationResult {
                firstFailure?.let { diagnostics.put("first_failed_check", it) }
                diagnostics.put("aggregate_accepted", accepted)
                return NavigationFocusRevalidationResult(accepted, diagnostics)
            }
            fun check(name: String, accepted: Boolean): Boolean {
                diagnostics.put(name, accepted)
                return accepted
            }

            val now = SystemClock.elapsedRealtime()
            if (!check("child_capture_fresh", now - capturedAt in 0..2_500L))
                return finish(false, "child_capture_fresh")
            if (!check("connection_identity_matches",
                    currentConnectionId == connectionId && authorizationTarget.connectionId == connectionId))
                return finish(false, "connection_identity_matches")
            if (!check("declared_relation_matches",
                    relation.isWellFormed() && authorizationTarget.windowId == windowId &&
                        authorizationTarget.packageName == packageName &&
                        authorizationTarget.sourceSnapshotId == sourceSnapshotId &&
                        authorizationTarget.helperSnapshotId == helperSnapshotId &&
                        authorizationTarget.baselineHierarchyDigest == baselineHierarchyDigest &&
                        authorizationTarget.nodePath + relation.childIndex == nodePath &&
                        authorizationTarget.isUniqueInSnapshot && descriptorMatchCount == 1 && hasClickAction &&
                        Regex(relation.childClassPattern).matches(className) &&
                        resourceId == relation.childResourceId))
                return finish(false, "declared_relation_matches")
            if (!check("focus_event_identity_matches",
                    focusProof.connectionId == currentConnectionId &&
                        focusProof.windowId == windowId &&
                        focusProof.eventType == AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED &&
                        focusProof.eventElapsedRealtimeMs in 0..now &&
                        now - focusProof.eventElapsedRealtimeMs in 0..2_500L &&
                        navigationActionLease().eventSourceMatches(
                            focusProof.source as? AccessibilityNodeInfo,
                            focusProof.windowId, currentConnectionId)))
                return finish(false, "focus_event_identity_matches")

            if (!runCatching { node.refresh() }.getOrDefault(false))
                return finish(false, "retained_child_refresh_succeeded")
            val activePackageWindows = windows().filter { window ->
                window.type == 1 && window.active &&
                    window.root?.packageName?.toString() == packageName
            }
            if (!check("unique_active_package_window",
                    activePackageWindows.size == 1 && activePackageWindows.single().id == windowId))
                return finish(false, "unique_active_package_window")
            val root = activePackageWindows.single().root
                ?: return finish(false, "current_root_available")
            val parentAtPath = runCatching {
                nodeAtPath(root, authorizationTarget.nodePath)
            }.getOrNull()
            val childAtPath = runCatching { nodeAtPath(root, nodePath) }.getOrNull()
            if (!check("retained_parent_path_identity_matches",
                    parentAtPath != null && authorizationTarget.eventSourceMatches(
                        parentAtPath, authorizationTarget.windowId, currentConnectionId)))
                return finish(false, "retained_parent_path_identity_matches")
            if (!check("retained_child_path_identity_matches",
                    childAtPath != null && childAtPath == node && childAtPath.windowId == windowId))
                return finish(false, "retained_child_path_identity_matches")

            val currentSnapshot = runCatching { hierarchyFingerprintSnapshot(root) }.getOrNull()
                ?: return finish(false, "hierarchy_capture_complete")
            diagnostics.put("hierarchy_capture_complete", true)
            if (!check("parent_descriptor_matches",
                    currentSnapshot.byPath[authorizationTarget.nodePath]?.descriptorDigest ==
                        authorizationTarget.descriptorDigest &&
                        baselineHierarchyNodeFingerprints[authorizationTarget.nodePath]?.descriptorDigest ==
                            authorizationTarget.descriptorDigest))
                return finish(false, "parent_descriptor_matches")
            if (!check("declared_child_actionable",
                    childAtPath?.packageName?.toString() == packageName &&
                        Regex(relation.childClassPattern).matches(childAtPath.className?.toString().orEmpty()) &&
                        childAtPath.viewIdResourceName == relation.childResourceId &&
                        childAtPath.isEnabled && childAtPath.isVisibleToUser && childAtPath.isClickable &&
                        childAtPath.actionList.any { it.id == AccessibilityNodeInfo.ACTION_CLICK }))
                return finish(false, "declared_child_actionable")
            if (!check("focus_scoped_full_tree_matches",
                    exactDeclaredChildFocusHierarchyMatches(
                        baselineHierarchyNodeFingerprints, currentSnapshot.byPath, nodePath)))
                return finish(false, "focus_scoped_full_tree_matches")
            return finish(true)
        }

        /** Revalidate after the authorized focus step, normalizing only accessibilityFocused bits. */
        fun stillCurrentAfterAccessibilityFocus(currentConnectionId: String): Boolean =
            revalidateAfterAccessibilityFocus(currentConnectionId).accepted
    }

    /** Navigation-only wrapper. Its only action method requires a capability-minted one-shot authorization. */
    inner class NavigationTargetLease internal constructor(
        private val observation: ObservationTarget,
        private val node: AccessibilityNodeInfo,
    ) : NavigationActionTargetLease {
        override val windowId get() = observation.windowId
        override val nodePath get() = observation.nodePath
        override val descriptorDigest get() = observation.descriptorDigest
        override val sourceSnapshotId get() = observation.sourceSnapshotId
        override val helperSnapshotId get() = observation.helperSnapshotId
        override val baselineHierarchyDigest get() = observation.baselineHierarchyDigest
        override val connectionId get() = observation.connectionId
        override val independentDescendants get() = observation.independentDescendants
        override val independentSiblings get() = observation.independentSiblings
        override val isUniqueInSnapshot get() = observation.descriptorMatchCount == 1
        override val packageName get() = observation.packageName
        override val className get() = observation.className
        override val resourceId get() = observation.resourceId
        override val label get() = observation.label
        override val subtreeLabels get() = observation.subtreeLabels()
        override val descendantEvidenceComplete get() = observation.descendantEvidence().first
        override fun descendantEvidence() = observation.descendantEvidence().second
        override val hasClickAction get() = observation.clickActionAllowed && observation.hasClickAction
        override val hasAccessibilityFocusAction get() = observation.hasAccessibilityFocusAction
        override fun exactDeclaredActivationChild(
            relation: NavigationActivationOwnerRelation,
            currentConnectionId: String,
        ): NavigationActionTargetLease? = observation.exactDeclaredActivationChild(relation, currentConnectionId)

        override fun eventSourceMatches(source: Any?, eventWindowId: Int, currentConnectionId: String): Boolean =
            observation.eventSourceMatches(source as? AccessibilityNodeInfo, eventWindowId, currentConnectionId)

        override fun stillCurrent(currentConnectionId: String): Boolean = observation.stillCurrent(currentConnectionId)

        override fun stillCurrentAfterAccessibilityFocus(currentConnectionId: String): Boolean =
            observation.stillCurrentAfterAccessibilityFocus(currentConnectionId)

        override fun revalidateAfterAccessibilityFocus(currentConnectionId: String): NavigationFocusRevalidationResult =
            observation.revalidateAfterAccessibilityFocus(currentConnectionId)

        override fun revalidateAfterDeclaredChildAccessibilityFocus(
            currentConnectionId: String,
            authorizationTarget: NavigationActionTargetLease,
            relation: NavigationActivationOwnerRelation,
            focusProof: NavigationFocusEvidence,
        ): NavigationFocusRevalidationResult =
            observation.revalidateAfterDeclaredChildAccessibilityFocus(
                currentConnectionId, authorizationTarget, relation, focusProof)

        override fun performNavigationAccessibilityFocus(
            authorization: NavigationActionDispatchAuthorization,
            requestId: String,
            transactionId: String,
            leaseToken: String,
            currentConnectionId: String,
        ): Boolean {
            ExactActionContract.requireThat(authorization.consume(requestId, transactionId, leaseToken,
                NAVIGATION_ACTION_ACCESSIBILITY_FOCUS), "NAVIGATION_DISPATCH_UNAUTHORIZED")
            ExactActionContract.requireThat(observation.identifiesRetainedNode(node),
                "NAVIGATION_TARGET_IDENTITY_MISMATCH")
            ExactActionContract.requireThat(observation.stillCurrent(currentConnectionId), "OBSERVATION_TARGET_STALE")
            ExactActionContract.requireThat(node.isEnabled && node.isVisibleToUser && hasAccessibilityFocusAction,
                "OBSERVATION_TARGET_FOCUS_NOT_ACTIONABLE")
            return node.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
        }

        override fun performNavigationClick(
            authorization: NavigationActionDispatchAuthorization,
            requestId: String,
            transactionId: String,
            leaseToken: String,
            currentConnectionId: String,
        ): Boolean {
            ExactActionContract.requireThat(authorization.consume(requestId, transactionId, leaseToken,
                NAVIGATION_ACTION_CLICK),
                "NAVIGATION_DISPATCH_UNAUTHORIZED")
            ExactActionContract.requireThat(observation.identifiesRetainedNode(node),
                "NAVIGATION_TARGET_IDENTITY_MISMATCH")
            ExactActionContract.requireThat(observation.stillCurrent(currentConnectionId), "OBSERVATION_TARGET_STALE")
            ExactActionContract.requireThat(node.isEnabled && node.isVisibleToUser && hasClickAction,
                "OBSERVATION_TARGET_NOT_ACTIONABLE")
            return node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        }

        override fun performNavigationClickAfterAccessibilityFocus(
            authorization: NavigationActionDispatchAuthorization,
            requestId: String,
            transactionId: String,
            leaseToken: String,
            currentConnectionId: String,
        ): Boolean {
            ExactActionContract.requireThat(authorization.consume(requestId, transactionId, leaseToken,
                NAVIGATION_ACTION_CLICK), "NAVIGATION_DISPATCH_UNAUTHORIZED")
            ExactActionContract.requireThat(observation.identifiesRetainedNode(node),
                "NAVIGATION_TARGET_IDENTITY_MISMATCH")
            ExactActionContract.requireThat(observation.stillCurrentAfterAccessibilityFocus(currentConnectionId),
                "OBSERVATION_TARGET_STALE_AFTER_FOCUS")
            ExactActionContract.requireThat(node.isEnabled && node.isVisibleToUser && hasClickAction,
                "OBSERVATION_TARGET_NOT_ACTIONABLE")
            return node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        }
    }

    /** Read-only lease: retain the exact current node object selected by a snapshot path and full descriptor. */
    fun captureObservationTarget(
        expectedWindowId: Int,
        expectedPackage: String,
        nodePath: List<Int>,
        expectedDescriptorDigest: String,
        sourceSnapshotId: String,
        connectionId: String,
        expectedSourceNodeId: String? = null,
        onResolvedNode: ((AccessibilityNodeInfo) -> Unit)? = null,
    ): ObservationTarget = captureTarget(expectedWindowId, expectedPackage, nodePath, expectedDescriptorDigest,
        sourceSnapshotId, connectionId, expectedSourceNodeId, onResolvedNode).first

    fun captureNavigationActionTarget(
        expectedWindowId: Int,
        expectedPackage: String,
        nodePath: List<Int>,
        expectedDescriptorDigest: String,
        sourceSnapshotId: String,
        connectionId: String,
    ): NavigationTargetLease {
        val (observation, node) = captureTarget(expectedWindowId, expectedPackage, nodePath,
            expectedDescriptorDigest, sourceSnapshotId, connectionId)
        return NavigationTargetLease(observation, node)
    }

    /** Resolves a unique, clickable, focusable destination anchor from one current active app window. */
    fun captureUniqueDestinationAnchor(
        expectedWindowId: Int,
        expectedPackage: String,
        sourceSnapshotId: String,
        connectionId: String,
        signature: NavigationEmptyStateSignature,
        anchorPattern: String,
    ): NavigationTargetLease? = runCatching {
        ExactActionContract.requireThat(signature.isWellFormed() && expectedPackage.isNotBlank() &&
            sourceSnapshotId.isNotBlank() && connectionId.isNotBlank() && anchorPattern.isNotBlank(),
            "NAVIGATION_DESTINATION_ANCHOR_REQUEST_INVALID")
        val active = windows().filter { it.id == expectedWindowId && it.type == 1 && it.active }
        ExactActionContract.requireThat(active.size == 1, "NAVIGATION_DESTINATION_WINDOW_AMBIGUOUS")
        val root = active.single().root ?: throw ExactActionRejected("NAVIGATION_DESTINATION_ROOT_MISSING")
        ExactActionContract.requireThat(root.windowId == expectedWindowId &&
            root.packageName?.toString() == expectedPackage &&
            root.className?.toString() == signature.rootClassName,
            "NAVIGATION_DESTINATION_ROOT_MISMATCH")
        val matcher = Regex(anchorPattern, RegexOption.IGNORE_CASE)
        val matches = mutableListOf<Pair<List<Int>, AccessibilityNodeInfo>>()
        fun walk(node: AccessibilityNodeInfo, path: List<Int>, depth: Int) {
            ExactActionContract.requireThat(depth <= 80 && matches.size <= 1, "METADATA_INCOMPLETE")
            val label = node.text?.toString()?.takeIf { it.isNotBlank() }
                ?: node.contentDescription?.toString().orEmpty()
            if (node.className?.toString() == signature.anchorClassName &&
                node.viewIdResourceName == signature.anchorResourceId && matcher.matches(label) &&
                node.packageName?.toString() == expectedPackage && node.windowId == expectedWindowId &&
                node.isEnabled && node.isVisibleToUser && node.isClickable &&
                node.actionList.any { it.id == AccessibilityNodeInfo.ACTION_CLICK } &&
                node.actionList.any { it.id == AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS }) {
                matches += path to node
            }
            for (index in 0 until node.childCount) {
                val child = node.getChild(index) ?: throw ExactActionRejected("METADATA_INCOMPLETE")
                walk(child, path + index, depth + 1)
            }
        }
        walk(root, emptyList(), 0)
        ExactActionContract.requireThat(matches.size == 1, "NAVIGATION_DESTINATION_ANCHOR_NOT_UNIQUE")
        val (path, candidate) = matches.single()
        val (observation, retained) = captureTarget(
            expectedWindowId = expectedWindowId,
            expectedPackage = expectedPackage,
            nodePath = path,
            expectedDescriptorDigest = descriptorDigest(candidate),
            sourceSnapshotId = sourceSnapshotId,
            connectionId = connectionId,
            helperSnapshotIdOverride = sourceSnapshotId,
        )
        ExactActionContract.requireThat(retained.className?.toString() == signature.anchorClassName &&
            retained.viewIdResourceName == signature.anchorResourceId &&
            matcher.matches(retained.text?.toString()?.takeIf { it.isNotBlank() }
                ?: retained.contentDescription?.toString().orEmpty()) &&
            observation.hasClickAction && observation.hasAccessibilityFocusAction && observation.descriptorMatchCount == 1 &&
            observation.stillCurrent(connectionId), "NAVIGATION_DESTINATION_ANCHOR_STALE")
        NavigationTargetLease(observation, retained)
    }.getOrNull()

    /** Resolve the exact policy-structural anchor from the same completed post-capture path. */
    fun captureUniqueStructuralDestinationAnchor(
        expectedWindowId: Int,
        expectedRootClassName: String?,
        expectedPackage: String,
        sourceSnapshotId: String,
        connectionId: String,
        expectedNodePath: List<Int>,
        structure: NavigationAnchorStructure,
        anchorPattern: String,
        onFailure: ((String) -> Unit)? = null,
    ): NavigationTargetLease? {
        val result = runCatching {
        ExactActionContract.requireThat(structure.isWellFormed() && expectedPackage.isNotBlank() &&
            sourceSnapshotId.isNotBlank() && connectionId.isNotBlank() && anchorPattern.isNotBlank() &&
            !expectedRootClassName.isNullOrBlank() && expectedNodePath.isNotEmpty() && expectedNodePath.size <= 80 &&
            expectedNodePath.all { it in 0..4096 }, "NAVIGATION_DESTINATION_ANCHOR_REQUEST_INVALID")
        val active = windows().filter { it.id == expectedWindowId && it.type == 1 && it.active }
        ExactActionContract.requireThat(active.size == 1, "NAVIGATION_DESTINATION_WINDOW_AMBIGUOUS")
        val root = active.single().root ?: throw ExactActionRejected("NAVIGATION_DESTINATION_ROOT_MISSING")
        ExactActionContract.requireThat(root.windowId == expectedWindowId &&
            root.packageName?.toString() == expectedPackage &&
            root.className?.toString() == expectedRootClassName,
            "NAVIGATION_DESTINATION_ROOT_MISMATCH")
        val matcher = Regex(anchorPattern, RegexOption.IGNORE_CASE)
        val matches = mutableListOf<Pair<List<Int>, AccessibilityNodeInfo>>()
        fun walk(node: AccessibilityNodeInfo, parent: AccessibilityNodeInfo?, path: List<Int>, depth: Int) {
            ExactActionContract.requireThat(depth <= 80 && matches.size <= 1, "METADATA_INCOMPLETE")
            val structuralMatch = structure.matches(
                nodeClassName = node.className?.toString(),
                nodePackageName = node.packageName?.toString(),
                nodeWindowId = node.windowId,
                parentClassName = parent?.className?.toString(),
                parentResourceId = parent?.viewIdResourceName,
                parentPackageName = parent?.packageName?.toString(),
                parentWindowId = parent?.windowId ?: -1,
                expectedPackageName = expectedPackage,
                expectedWindowId = expectedWindowId,
            )
            val labelMatch = matcher.matches(node.text?.toString().orEmpty()) ||
                matcher.matches(node.contentDescription?.toString().orEmpty())
            val actions = node.actionList
            if (structuralMatch && labelMatch && node.isEnabled && node.isVisibleToUser &&
                node.isFocusable &&
                actions.any { it.id == AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS }) {
                matches += path to node
            }
            for (index in 0 until node.childCount) {
                val child = node.getChild(index) ?: throw ExactActionRejected("METADATA_INCOMPLETE")
                walk(child, node, path + index, depth + 1)
            }
        }
        walk(root, null, emptyList(), 0)
        ExactActionContract.requireThat(matches.size == 1 && matches.single().first == expectedNodePath,
            "NAVIGATION_DESTINATION_ANCHOR_NOT_UNIQUE")
        val (path, candidate) = matches.single()
        val (observation, retained) = captureTarget(
            expectedWindowId = expectedWindowId,
            expectedPackage = expectedPackage,
            nodePath = path,
            expectedDescriptorDigest = descriptorDigest(candidate),
            sourceSnapshotId = sourceSnapshotId,
            connectionId = connectionId,
            helperSnapshotIdOverride = sourceSnapshotId,
            requiredActionId = AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS,
        )
        ExactActionContract.requireThat(
            Regex(structure.nodeClassPattern, RegexOption.IGNORE_CASE).matches(retained.className?.toString().orEmpty()) &&
                (matcher.matches(retained.text?.toString().orEmpty()) ||
                    matcher.matches(retained.contentDescription?.toString().orEmpty())),
            "NAVIGATION_DESTINATION_ANCHOR_STALE")
        ExactActionContract.requireThat(observation.hasAccessibilityFocusAction &&
            observation.descriptorMatchCount == 1 && observation.stillCurrent(connectionId),
            "NAVIGATION_DESTINATION_ANCHOR_STALE")
        NavigationTargetLease(observation, retained)
        }
        result.exceptionOrNull()?.let { failure ->
            val code = (failure as? ExactActionRejected)?.code
                ?.takeIf { Regex("[A-Z][A-Z0-9_]{0,79}").matches(it) }
                ?: "NAVIGATION_DESTINATION_ANCHOR_RESOLUTION_FAILED"
            runCatching { onFailure?.invoke(code) }
        }
        return result.getOrNull()
    }

    private fun captureTarget(
        expectedWindowId: Int,
        expectedPackage: String,
        nodePath: List<Int>,
        expectedDescriptorDigest: String,
        sourceSnapshotId: String,
        connectionId: String,
        expectedSourceNodeId: String? = null,
        onResolvedNode: ((AccessibilityNodeInfo) -> Unit)? = null,
        helperSnapshotIdOverride: String? = null,
        requiredActionId: Int = AccessibilityNodeInfo.ACTION_CLICK,
    ): Pair<ObservationTarget, AccessibilityNodeInfo> {
        ExactActionContract.requireThat(expectedWindowId >= 0 && expectedPackage.isNotBlank() &&
            nodePath.size <= 80 && nodePath.all { it in 0..4096 } &&
            expectedDescriptorDigest.matches(Regex("[0-9a-f]{64}")) && sourceSnapshotId.isNotBlank() &&
            connectionId.isNotBlank(), "OBSERVATION_LEASE_REQUEST_INVALID")
        val active = windows().filter { it.id == expectedWindowId && it.type == 1 && it.active }
        ExactActionContract.requireThat(active.size == 1, "OBSERVATION_WINDOW_AMBIGUOUS")
        val window = active.single()
        val root = window.root ?: throw ExactActionRejected("HELPER_REACQUIRE_FAILED")
        val target = nodeAtPath(root, nodePath)
        // Diagnostic-only projection. A callback failure must never change the
        // existing resolver verdict or allow the target through.
        runCatching { onResolvedNode?.invoke(target) }
        val sourceNodeId = if (Build.VERSION.SDK_INT >= 33) target.uniqueId.orEmpty() else ""
        if (expectedSourceNodeId != null) {
            ExactActionContract.requireThat(expectedSourceNodeId.isNotBlank() &&
                sourceNodeId == expectedSourceNodeId, "OBSERVATION_SOURCE_NODE_ID_MISMATCH")
        }
        val requiredActionAvailable = when (requiredActionId) {
            AccessibilityNodeInfo.ACTION_CLICK -> target.isClickable ||
                target.actionList.any { it.id == AccessibilityNodeInfo.ACTION_CLICK }
            AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS -> target.isFocusable &&
                target.actionList.any { it.id == AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS }
            else -> false
        }
        ExactActionContract.requireThat(target.packageName?.toString() == expectedPackage &&
            target.windowId == expectedWindowId && target.isVisibleToUser && target.isEnabled &&
            requiredActionAvailable, "OBSERVATION_TARGET_NOT_ACTIONABLE")
        ExactActionContract.requireThat(descriptorDigest(target) == expectedDescriptorDigest,
            "OBSERVATION_TARGET_DESCRIPTOR_MISMATCH")
        var identical = 0
        fun count(node: AccessibilityNodeInfo, depth: Int) {
            ExactActionContract.requireThat(depth <= 80, "METADATA_INCOMPLETE")
            if (descriptorDigest(node) == expectedDescriptorDigest) identical++
            for (index in 0 until node.childCount) {
                val child = node.getChild(index) ?: throw ExactActionRejected("METADATA_INCOMPLETE")
                count(child, depth + 1)
            }
        }
        count(root, 0)
        ExactActionContract.requireThat(identical == 1, "OBSERVATION_TARGET_DESCRIPTOR_AMBIGUOUS")
        val independentDescendants = countActionable(target, includeSelf = false)
        val independentSiblings = countActionableSiblings(root, nodePath)
        val hierarchySnapshot = hierarchyFingerprintSnapshot(root)
        val baselineDigest = hierarchySnapshot.strictHierarchyDigest
        val rawFocusNeutralDescriptor = A11yNavigator.hierarchyNodeToJson(target, intArrayOf(0), 0)
        val focusNeutralActionIds = exactNodeActionIds(rawFocusNeutralDescriptor)
        val focusNeutralDescriptor = exactNodeDescriptorForFocusCurrentness(
            rawFocusNeutralDescriptor,
            normalizeAccessibilityFocus = true,
            normalizeFocusActionIds = true,
        )
        val focusNeutralDescriptorDigest = ExactProtocolJson.sha256(ExactProtocolJson.canonical(focusNeutralDescriptor))
        val focusNeutralDescriptorFieldHashes = exactNodeDescriptorFieldHashes(focusNeutralDescriptor)
        val focusNeutralHierarchyDigest = hierarchySnapshot.focusNeutralHierarchyDigest
        val snapshotId = helperSnapshotIdOverride ?: java.util.UUID.randomUUID().toString()
        val targetLease = ObservationTarget(target, expectedWindowId, nodePath.toList(), expectedDescriptorDigest,
            sourceSnapshotId, sourceNodeId, snapshotId, baselineDigest, focusNeutralDescriptorDigest,
            focusNeutralDescriptorFieldHashes, focusNeutralActionIds,
            focusNeutralHierarchyDigest, hierarchySnapshot.byPath, connectionId, independentDescendants,
            independentSiblings, identical,
            SystemClock.elapsedRealtime(), clickActionAllowed = requiredActionId == AccessibilityNodeInfo.ACTION_CLICK)
        ExactActionContract.requireThat(targetLease.stillCurrent(connectionId), "OBSERVATION_TARGET_STALE")
        return targetLease to target
    }

    private fun countActionable(node: AccessibilityNodeInfo, includeSelf: Boolean, depth: Int = 0): Int {
        ExactActionContract.requireThat(depth <= 80, "METADATA_INCOMPLETE")
        val own = if (includeSelf && (node.isClickable || node.actionList.any { it.id == AccessibilityNodeInfo.ACTION_CLICK })) 1 else 0
        var total = own
        for (index in 0 until node.childCount) {
            val child = node.getChild(index) ?: throw ExactActionRejected("METADATA_INCOMPLETE")
            total += countActionable(child, true, depth + 1)
        }
        return total
    }

    private fun countActionableSiblings(root: AccessibilityNodeInfo, path: List<Int>): Int {
        if (path.isEmpty()) return 0
        var parent = root
        for (index in path.dropLast(1)) {
            ExactActionContract.requireThat(index in 0 until parent.childCount, "OBSERVATION_TARGET_PATH_CHANGED")
            parent = parent.getChild(index) ?: throw ExactActionRejected("OBSERVATION_TARGET_PATH_CHANGED")
        }
        val targetIndex = path.last()
        ExactActionContract.requireThat(targetIndex in 0 until parent.childCount, "OBSERVATION_TARGET_PATH_CHANGED")
        var total = 0
        for (index in 0 until parent.childCount) {
            if (index == targetIndex) continue
            val sibling = parent.getChild(index) ?: throw ExactActionRejected("METADATA_INCOMPLETE")
            total += countActionable(sibling, true)
        }
        return total
    }

    private fun hierarchyFingerprintSnapshot(root: AccessibilityNodeInfo): ExactHierarchyFingerprintSnapshot {
        val strictNodes = JSONArray()
        val focusNeutralNodes = JSONArray()
        val byPath = linkedMapOf<List<Int>, ExactHierarchyNodeFingerprint>()
        var count = 0
        fun walk(current: AccessibilityNodeInfo, path: List<Int>, depth: Int) {
            ExactActionContract.requireThat(depth <= 80 && ++count <= 5_000,
                "METADATA_INCOMPLETE")
            val raw = A11yNavigator.hierarchyNodeToJson(current, intArrayOf(0), 0)
            val strictDescriptor = exactNodeDescriptorForFocusCurrentness(
                raw, normalizeAccessibilityFocus = false, normalizeFocusActionIds = false)
            val focusNeutralDescriptor = exactNodeDescriptorForFocusCurrentness(
                raw, normalizeAccessibilityFocus = true, normalizeFocusActionIds = true)
            val strictDigest = ExactProtocolJson.sha256(ExactProtocolJson.canonical(strictDescriptor))
            val focusNeutralDigest = ExactProtocolJson.sha256(
                ExactProtocolJson.canonical(focusNeutralDescriptor))
            val stablePath = path.toList()
            byPath[stablePath] = ExactHierarchyNodeFingerprint(
                descriptorDigest = strictDigest,
                focusNeutralDescriptorDigest = focusNeutralDigest,
                actionIds = exactNodeActionIds(raw),
                accessibilityFocused = if (raw.has("accessibilityFocused")) {
                    raw.optBoolean("accessibilityFocused")
                } else null,
            )
            strictNodes.put(JSONObject()
                .put("path", JSONArray().apply { stablePath.forEach { put(it) } })
                .put("descriptor_digest", strictDigest))
            focusNeutralNodes.put(JSONObject()
                .put("path", JSONArray().apply { stablePath.forEach { put(it) } })
                .put("descriptor_digest", focusNeutralDigest))
            for (index in 0 until current.childCount) {
                val child = current.getChild(index)
                    ?: throw ExactActionRejected("METADATA_INCOMPLETE")
                walk(child, path + index, depth + 1)
            }
        }
        walk(root, emptyList(), 0)
        return ExactHierarchyFingerprintSnapshot(
            strictHierarchyDigest = ExactProtocolJson.sha256(ExactProtocolJson.canonical(strictNodes)),
            focusNeutralHierarchyDigest = ExactProtocolJson.sha256(
                ExactProtocolJson.canonical(focusNeutralNodes)),
            byPath = byPath.toMap(),
        )
    }

    private fun hierarchyDigest(
        root: AccessibilityNodeInfo,
        normalizeAccessibilityFocus: Boolean = false,
        normalizeFocusActionIds: Boolean = false,
    ): String {
        val nodes = JSONArray()
        var count = 0
        fun walk(node: AccessibilityNodeInfo, path: List<Int>, depth: Int) {
            ExactActionContract.requireThat(depth <= 80 && ++count <= 5000, "METADATA_INCOMPLETE")
            nodes.put(JSONObject().put("path", JSONArray().apply { path.forEach { put(it) } })
                .put("descriptor_digest", descriptorDigest(
                    node, normalizeAccessibilityFocus, normalizeFocusActionIds)))
            for (index in 0 until node.childCount) {
                val child = node.getChild(index) ?: throw ExactActionRejected("METADATA_INCOMPLETE")
                walk(child, path + index, depth + 1)
            }
        }
        walk(root, emptyList(), 0)
        return ExactProtocolJson.sha256(ExactProtocolJson.canonical(nodes))
    }

    private fun nodeAtPath(root: AccessibilityNodeInfo, path: List<Int>): AccessibilityNodeInfo {
        var current = root
        for (childIndex in path) {
            ExactActionContract.requireThat(childIndex in 0 until current.childCount, "OBSERVATION_TARGET_PATH_CHANGED")
            current = current.getChild(childIndex) ?: throw ExactActionRejected("OBSERVATION_TARGET_PATH_CHANGED")
        }
        return current
    }

    internal fun descriptorDigest(
        node: AccessibilityNodeInfo,
        normalizeAccessibilityFocus: Boolean = false,
        normalizeFocusActionIds: Boolean = false,
    ): String {
        val raw = A11yNavigator.hierarchyNodeToJson(node, intArrayOf(0), 0)
        val descriptor = exactNodeDescriptorForFocusCurrentness(
            raw, normalizeAccessibilityFocus, normalizeFocusActionIds)
        return ExactProtocolJson.sha256(ExactProtocolJson.canonical(descriptor))
    }

    inner class Target internal constructor(val node:AccessibilityNodeInfo,val ack:JSONObject,
        val independentDescendants:Int,val independentSiblings:Int,
        private val request:JSONObject,private val connection:String,private val capturedAt:Long) {
        fun revalidate():JSONObject {
            ExactActionContract.requireThat(SystemClock.elapsedRealtime()-capturedAt in 0..1000,"SNAPSHOT_STALE")
            ExactActionContract.requireThat(node.refresh(),"TARGET_STALE")
            val fresh=capture(request,connection)
            ExactActionContract.requireThat(node.windowId==request.getJSONObject("expected_window").getInt("id") &&
                node.packageName?.toString()==request.getString("expected_package"),"WINDOW_MISMATCH")
            ExactActionContract.requireThat(node.isEnabled,"TARGET_DISABLED")
            ExactActionContract.requireThat(node.isVisibleToUser,"TARGET_NOT_VISIBLE")
            ExactActionContract.requireThat(node.actionList.any{it.id==16},"ACTION_NOT_AVAILABLE")
            ExactActionContract.requireThat(fresh.independentDescendants==0 && fresh.independentSiblings==0,"ISOLATION_UNPROVEN")
            // Compare the retained reference itself, not merely a newly looked-up replacement.
            ExactActionContract.requireThat(ExactProtocolJson.canonical(serialize(node,0,intArrayOf(0),null,"",null)) ==
                ExactProtocolJson.canonical(serialize(fresh.node,0,intArrayOf(0),null,"",null)),"TARGET_IDENTITY_MISMATCH")
            return fresh.ack
        }
        fun click():Boolean = node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    fun capture(request:JSONObject,connection:String):Target {
        val captureStarted=SystemClock.elapsedRealtime()
        val expected=request.getJSONObject("expected_window")
        ExactActionContract.requireThat(expected.opt("type")==1,"WINDOW_MISMATCH")
        val matching=windows().filter { it.id==expected.getInt("id") && it.type==1 && it.active }
        ExactActionContract.requireThat(matching.size==1,"WINDOW_MISMATCH")
        val window=matching.single();val root=window.root ?: throw ExactActionRejected("HELPER_REACQUIRE_FAILED")
        val handles=mutableMapOf<String,AccessibilityNodeInfo>();val rawNodes=mutableMapOf<String,JSONObject>()
        val hierarchy=JSONObject().put("snapshotId",UUID.randomUUID().toString()).put("success",true)
            .put("windows",JSONArray().put(JSONObject().put("id",window.id).put("type",window.type)
                .put("root",serialize(root,0,intArrayOf(0),handles,"",rawNodes))))
        val ack=ExactNodeResolver.resolveForAction(request.toString(),hierarchy,connection)
        ExactActionContract.requireThat(ack.optBoolean("resolved"),ack.optString("failure_code","TARGET_NOT_FOUND"))
        val indices=ack.getJSONObject("resolved_target_identity").getJSONObject("hierarchy_path").getJSONArray("child_indices")
        val key=(0 until indices.length()).joinToString("."){indices.getInt(it).toString()}
        val node=handles[key] ?: throw ExactActionRejected("TARGET_NOT_FOUND")
        ExactActionContract.requireThat(node.windowId==window.id,"WINDOW_MISMATCH")
        val raw=rawNodes.getValue(key)
        val descendantCount=children(raw).sumOf(::actionableCount)
        val parent=if(key.contains('.'))key.substringBeforeLast('.') else ""
        val siblings=if(key.isBlank())0 else children(rawNodes.getValue(parent)).filter { it !== raw }.sumOf(::actionableCount)
        ExactActionContract.requireThat(SystemClock.elapsedRealtime()-captureStarted in 0..1000,"SNAPSHOT_STALE")
        return Target(node,ack,descendantCount,siblings,request,connection,captureStarted)
    }

    private fun children(node:JSONObject):List<JSONObject> = node.getJSONArray("children").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
    private fun actionableCount(node:JSONObject):Int {
        val actions=node.getJSONArray("actions")
        val self=node.optBoolean("clickable") || (0 until actions.length()).any { actions.getJSONObject(it).getInt("id")==16 }
        return (if(self)1 else 0)+children(node).sumOf(::actionableCount)
    }

    private fun serialize(node:AccessibilityNodeInfo,depth:Int,count:IntArray,handles:MutableMap<String,AccessibilityNodeInfo>?,
        path:String,rawNodes:MutableMap<String,JSONObject>?):JSONObject {
        ExactActionContract.requireThat(depth<=80 && ++count[0]<=5000,"METADATA_INCOMPLETE")
        val bounds=Rect().also(node::getBoundsInScreen)
        val result=JSONObject().put("packageName",node.packageName?.toString() ?: JSONObject.NULL)
            .put("viewIdResourceName",node.viewIdResourceName ?: JSONObject.NULL).put("className",node.className?.toString() ?: JSONObject.NULL)
            .put("text",node.text?.toString() ?: JSONObject.NULL).put("contentDescription",node.contentDescription?.toString() ?: JSONObject.NULL)
            .put("boundsInScreen",A11yNavigator.rectToJson(bounds)).put("clickable",node.isClickable)
            .put("focusable",node.isFocusable).put("enabled",node.isEnabled).put("visibleToUser",node.isVisibleToUser)
            .put("actions",JSONArray().apply { node.actionList.forEach {
                put(JSONObject().put("id",it.id).put("name",A11yNavigator.hierarchyActionName(it.id)).put("label",it.label?.toString() ?: JSONObject.NULL))
            } })
        handles?.put(path,node);rawNodes?.put(path,result)
        if(Build.VERSION.SDK_INT>=33)result.put("sourceNodeId",node.uniqueId ?: JSONObject.NULL)
        result.put("children",JSONArray().apply {
            for(i in 0 until node.childCount) {
                val child=node.getChild(i) ?: throw ExactActionRejected("METADATA_INCOMPLETE")
                put(serialize(child,depth+1,count,handles,if(path.isBlank())"$i" else "$path.$i",rawNodes))
            }
        })
        return result
    }
}
