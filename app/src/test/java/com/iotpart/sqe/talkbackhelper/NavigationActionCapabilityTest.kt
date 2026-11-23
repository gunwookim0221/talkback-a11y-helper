package com.iotpart.sqe.talkbackhelper

import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class NavigationActionCapabilityTest {
    @Test fun ownerEvidenceIsRecordedBeforeNavigationWaiterIsWoken() {
        val order = mutableListOf<String>()
        NavigationActionEventHandoff.captureOwnerEvidenceBeforeWake(
            captureOwnerEvidence = { order += "owner-evidence" },
            wakeNavigationVerifier = { order += "navigation-waiter" },
        )
        assertEquals(listOf("owner-evidence", "navigation-waiter"), order)
    }

    @Test fun navigationClickCallbackSourceIsReadOnceAndCarriesNoUiText() {
        val target = FakeTarget()
        val binding = binding(target, contract())
        val event = AccessibilityEvent.obtain(AccessibilityEvent.TYPE_VIEW_CLICKED)
        val source = AccessibilityNodeInfo.obtain()
        var reads = 0
        val observation = captureNavigationCallbackSourceObservation(
            binding, target, event, binding.serviceInstanceId, binding.connectionId, 1_000L, 6_000L,
        ) { reads += 1; source }

        assertEquals(1, reads)
        assertSame(source, observation.source)
        assertEquals("FIELD_PRESENT", observation.sourceReadStatus)
        assertEquals(binding.requestId, observation.requestId)
        assertEquals(binding.transactionId, observation.transactionId)
        val matchedObservation = matchingNavigationCallbackSourceObservation(
            observation, event, binding.requestId, binding.transactionId,
            binding.serviceInstanceId, binding.connectionId)
        assertSame(observation, matchedObservation)
        assertTrue(matchedObservation!!.eventElapsedRealtimeMs >= 0L)
        var legacyTimestampReads = 0
        val evidenceElapsed = navigationClickElapsedRealtimeMs(
            observation, event, binding.requestId, binding.transactionId,
            binding.serviceInstanceId, binding.connectionId,
        ) { legacyTimestampReads += 1; observation.eventElapsedRealtimeMs + 20L }
        val collectorElapsed = navigationClickElapsedRealtimeMs(
            observation, event, binding.requestId, binding.transactionId,
            binding.serviceInstanceId, binding.connectionId,
        ) { legacyTimestampReads += 1; observation.eventElapsedRealtimeMs + 20L }
        assertEquals(observation.eventElapsedRealtimeMs, evidenceElapsed)
        assertEquals(evidenceElapsed, collectorElapsed)
        assertEquals(0, legacyTimestampReads)
        assertNull(matchingNavigationCallbackSourceObservation(
            observation, event, binding.requestId, binding.transactionId,
            "foreign-service", binding.connectionId))
        assertNull(navigationClickElapsedRealtimeMs(
            observation, event, binding.requestId, binding.transactionId,
            "foreign-service", binding.connectionId,
        ) { legacyTimestampReads += 1; observation.eventElapsedRealtimeMs + 20L })
        assertEquals(0, legacyTimestampReads)
        val mismatchedEvent = AccessibilityEvent.obtain(AccessibilityEvent.TYPE_VIEW_CLICKED).apply {
            eventTime = event.eventTime + 1L
        }
        assertNull(matchingNavigationCallbackSourceObservation(
            observation, mismatchedEvent, binding.requestId, binding.transactionId,
            binding.serviceInstanceId, binding.connectionId))
        assertNull(navigationClickElapsedRealtimeMs(
            observation, mismatchedEvent, binding.requestId, binding.transactionId,
            binding.serviceInstanceId, binding.connectionId,
        ) { legacyTimestampReads += 1; observation.eventElapsedRealtimeMs + 20L })
        assertEquals(0, legacyTimestampReads)
        val legacyElapsed = navigationClickElapsedRealtimeMs(
            null, event, binding.requestId, binding.transactionId,
            binding.serviceInstanceId, binding.connectionId,
        ) { legacyTimestampReads += 1; 123L }
        assertEquals(123L, legacyElapsed)
        assertEquals(1, legacyTimestampReads)
        mismatchedEvent.recycle()
        val diagnostic = observation.toJson(true, false, "SOURCE_OWNER_MISMATCH")
        assertEquals("navigation-click-source-v1", diagnostic.optString("schema"))
        assertTrue(diagnostic.optBoolean("first_click_selected"))
        assertFalse(diagnostic.has("text"))
        assertFalse(diagnostic.has("content_description"))

        var absentReads = 0
        val absent = captureNavigationCallbackSourceObservation(
            binding, target, event, binding.serviceInstanceId, binding.connectionId, 1_000L, 6_000L,
        ) { absentReads += 1; null }
        assertEquals(1, absentReads)
        assertNull(absent.source)
        assertEquals("FIELD_ABSENT", absent.sourceReadStatus)
        source.recycle()
        event.recycle()
    }

    @Test fun postCapturePollSleepIsCappedByRemainingDeadline() {
        assertEquals(50L, navigationPostCapturePollDelayMs(100L, 200L))
        assertEquals(36L, navigationPostCapturePollDelayMs(190_793_055L, 190_793_091L))
        assertEquals(0L, navigationPostCapturePollDelayMs(200L, 200L))
        assertEquals(0L, navigationPostCapturePollDelayMs(201L, 200L))
    }

    @Test fun structuralFocusPollingWaitsForLeaseWithinTheSameDeadline() {
        assertFalse(navigationPostCaptureSampleReady(
            hierarchyChanged = true, destinationMatches = true, anchorMatchCount = 1,
            emptyStateAnchorRequired = false, structuralAnchorRequired = true,
            focusInCurrentHierarchy = false, destinationAnchorTargetAvailable = false,
        ))
        assertTrue(navigationPostCaptureSampleReady(
            hierarchyChanged = true, destinationMatches = true, anchorMatchCount = 1,
            emptyStateAnchorRequired = false, structuralAnchorRequired = true,
            focusInCurrentHierarchy = false, destinationAnchorTargetAvailable = true,
        ))
        assertTrue(navigationPostCaptureSampleReady(
            hierarchyChanged = true, destinationMatches = true, anchorMatchCount = 1,
            emptyStateAnchorRequired = false, structuralAnchorRequired = true,
            focusInCurrentHierarchy = true, destinationAnchorTargetAvailable = false,
        ))
        assertTrue(navigationPostCaptureSampleReady(
            hierarchyChanged = true, destinationMatches = true, anchorMatchCount = 1,
            emptyStateAnchorRequired = true, structuralAnchorRequired = false,
            focusInCurrentHierarchy = false, destinationAnchorTargetAvailable = false,
        ))
        assertFalse(navigationPostCaptureSampleReady(
            hierarchyChanged = false, destinationMatches = true, anchorMatchCount = 1,
            emptyStateAnchorRequired = false, structuralAnchorRequired = true,
            focusInCurrentHierarchy = false, destinationAnchorTargetAvailable = true,
        ))
    }

    @Test fun focusOnlyCapabilityIsStructuralOnlyAndEmptyStateStillRequiresClick() {
        assertTrue(navigationFocusTargetActionsAllowed(
            clickRequired = false, hasClickAction = false, hasAccessibilityFocusAction = true,
        ))
        assertFalse(navigationFocusTargetActionsAllowed(
            clickRequired = true, hasClickAction = false, hasAccessibilityFocusAction = true,
        ))
        assertTrue(navigationFocusTargetActionsAllowed(
            clickRequired = true, hasClickAction = true, hasAccessibilityFocusAction = true,
        ))
    }

    @Test fun activationModeMustBeAllowlistedBeforeDispatch() {
        val target = FakeTarget()
        val contract = contract()
        val binding = binding(target, contract, "COORDINATE_DOUBLE_TAP")
        val capability = NavigationActionCapability(mapOf(contract.id to contract), { 1_000L })

        val prepared = capability.prepare(binding, target, "service-1", target.connectionId)

        assertEquals("REJECTED", prepared.optString("status"))
        assertEquals("NAVIGATION_BINDING_MISMATCH", prepared.optString("failure_code"))
        assertEquals(0, target.focusActionCalls)
        assertEquals(0, target.parentActionCalls)
    }

    @Test fun focusCurrentnessNormalizationIgnoresOnlyAccessibilityFocusedBit() {
        val before = JSONObject().put("accessibilityFocused", false).put("focused", false)
            .put("inputFocused", false).put("boundsInScreen", "same-bounds").put("actions", "same-actions")
        val afterAccessibilityFocus = JSONObject(before.toString()).put("accessibilityFocused", true)
        val beforeFocusNeutral = exactNodeDescriptorForFocusCurrentness(before, true)
        val afterFocusNeutral = exactNodeDescriptorForFocusCurrentness(afterAccessibilityFocus, true)
        assertEquals(beforeFocusNeutral.toString(), afterFocusNeutral.toString())
        val expectedFieldHashes = exactNodeDescriptorFieldHashes(beforeFocusNeutral)
        assertTrue(exactNodeDescriptorChangedFields(expectedFieldHashes, afterFocusNeutral).isEmpty())
        assertNotEquals(exactNodeDescriptorForFocusCurrentness(before, false).toString(),
            exactNodeDescriptorForFocusCurrentness(afterAccessibilityFocus, false).toString())
        val changedFocused = exactNodeDescriptorForFocusCurrentness(JSONObject(afterAccessibilityFocus.toString())
            .put("focused", true), true)
        assertNotEquals(afterFocusNeutral.toString(), changedFocused.toString())
        assertEquals(listOf("focused"), exactNodeDescriptorChangedFields(expectedFieldHashes, changedFocused))
        val changedBounds = exactNodeDescriptorForFocusCurrentness(JSONObject(afterAccessibilityFocus.toString())
            .put("boundsInScreen", "changed-bounds"), true)
        assertNotEquals(afterFocusNeutral.toString(), changedBounds.toString())
        assertEquals(listOf("boundsInScreen"), exactNodeDescriptorChangedFields(expectedFieldHashes, changedBounds))
        val changedResource = exactNodeDescriptorForFocusCurrentness(JSONObject(afterAccessibilityFocus.toString())
            .put("viewIdResourceName", "com.example:id/other"), true)
        assertEquals(listOf("viewIdResourceName"),
            exactNodeDescriptorChangedFields(expectedFieldHashes, changedResource))
    }

    @Test fun focusActionIdDeltaIsReportedAndOnlyFocusNeutralDescriptorNormalizesPair() {
        val originalActions = org.json.JSONArray()
            .put(JSONObject().put("id", AccessibilityNodeInfo.ACTION_CLICK).put("label", "private click label"))
            .put(JSONObject().put("id", AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
                .put("label", "private focus label"))
        val before = JSONObject().put("accessibilityFocused", false).put("actions", originalActions)
        val beforeNeutral = exactNodeDescriptorForFocusCurrentness(
            before, true, normalizeFocusActionIds = true)
        val beforeHashes = exactNodeDescriptorFieldHashes(beforeNeutral)
        val beforeIds = exactNodeActionIds(before)

        val focusedActions = org.json.JSONArray()
            .put(JSONObject().put("id", AccessibilityNodeInfo.ACTION_CLICK).put("label", "private click label"))
            .put(JSONObject().put("id", AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
                .put("label", "private clear label"))
        val focusedRawDescriptor = JSONObject().put("accessibilityFocused", true).put("actions", focusedActions)
        val afterFocus = exactNodeDescriptorForFocusCurrentness(
            focusedRawDescriptor, true, normalizeFocusActionIds = true)
        val focusDelta = exactNodeActionIdDelta(beforeIds, exactNodeActionIds(focusedRawDescriptor))

        assertEquals(listOf(AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS), focusDelta.added)
        assertEquals(listOf(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS), focusDelta.removed)
        assertTrue(focusDelta.complete)
        assertEquals(emptyList<String>(), exactNodeDescriptorChangedFields(beforeHashes, afterFocus))
        assertEquals(beforeNeutral.toString(), afterFocus.toString())
        assertEquals(listOf(AccessibilityNodeInfo.ACTION_CLICK), exactNodeActionIds(beforeNeutral).ids)

        val unnormalizedBefore = exactNodeDescriptorForFocusCurrentness(before, true)
        val unnormalizedAfter = exactNodeDescriptorForFocusCurrentness(focusedRawDescriptor, true)
        assertEquals(listOf("actions"), exactNodeDescriptorChangedFields(
            exactNodeDescriptorFieldHashes(unnormalizedBefore), unnormalizedAfter))

        val changedActions = org.json.JSONArray()
            .put(JSONObject().put("id", AccessibilityNodeInfo.ACTION_LONG_CLICK).put("label", "private long label"))
            .put(JSONObject().put("id", AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
                .put("label", "private focus label"))
        val unrelatedRawDescriptor = JSONObject().put("accessibilityFocused", true).put("actions", changedActions)
        val unrelatedChange = exactNodeDescriptorForFocusCurrentness(
            unrelatedRawDescriptor, true, normalizeFocusActionIds = true)
        val unrelatedDelta = exactNodeActionIdDelta(beforeIds, exactNodeActionIds(unrelatedRawDescriptor))
        assertEquals(listOf(AccessibilityNodeInfo.ACTION_LONG_CLICK), unrelatedDelta.added)
        assertEquals(listOf(AccessibilityNodeInfo.ACTION_CLICK), unrelatedDelta.removed)
        assertEquals(listOf("actions"), exactNodeDescriptorChangedFields(beforeHashes, unrelatedChange))
        assertNotEquals(beforeNeutral.toString(), unrelatedChange.toString())

        val oversizedActions = org.json.JSONArray().apply {
            repeat(MAX_FOCUS_REVALIDATION_ACTION_IDS + 5) { index ->
                put(JSONObject().put("id", index + 1).put("label", "must not be persisted"))
            }
        }
        val bounded = exactNodeActionIds(JSONObject().put("actions", oversizedActions))
        assertEquals(MAX_FOCUS_REVALIDATION_ACTION_IDS, bounded.ids.size)
        assertFalse(bounded.complete)
    }

    @Test fun declaredChildFocusComparatorAllowsOnlyBoundChildFocusDelta() {
        fun fingerprint(
            descriptor: String,
            focusNeutral: String = descriptor,
            actions: List<Int> = emptyList(),
            focused: Boolean? = false,
            complete: Boolean = true,
        ) = ExactHierarchyNodeFingerprint(
            descriptorDigest = descriptor,
            focusNeutralDescriptorDigest = focusNeutral,
            actionIds = ExactNodeActionIds(actions, complete),
            accessibilityFocused = focused,
        )

        val rootPath = emptyList<Int>()
        val childPath = listOf(0)
        val siblingPath = listOf(1)
        val before = mapOf(
            rootPath to fingerprint("parent"),
            childPath to fingerprint("child-before", "child-neutral",
                listOf(AccessibilityNodeInfo.ACTION_CLICK,
                    AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS), false),
            siblingPath to fingerprint("sibling"),
        )
        val focused = before + (childPath to fingerprint("child-after", "child-neutral",
            listOf(AccessibilityNodeInfo.ACTION_CLICK,
                AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS), true))

        assertTrue(exactDeclaredChildFocusHierarchyMatches(before, focused, childPath))
        assertFalse(exactDeclaredChildFocusHierarchyMatches(
            before, focused + (rootPath to fingerprint("changed-parent")), childPath))
        assertFalse(exactDeclaredChildFocusHierarchyMatches(
            before, focused + (siblingPath to fingerprint("changed-sibling")), childPath))
        assertFalse(exactDeclaredChildFocusHierarchyMatches(
            before, focused + (childPath to fingerprint("child-after", "changed-bounds",
                listOf(AccessibilityNodeInfo.ACTION_CLICK,
                    AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS), true)), childPath))
        assertFalse(exactDeclaredChildFocusHierarchyMatches(
            before, focused + (childPath to fingerprint("child-after", "child-neutral",
                listOf(AccessibilityNodeInfo.ACTION_LONG_CLICK,
                    AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS), true)), childPath))
        assertFalse(exactDeclaredChildFocusHierarchyMatches(before, focused, siblingPath))
        assertFalse(exactDeclaredChildFocusHierarchyMatches(before, focused - setOf(siblingPath), childPath))
        assertFalse(exactDeclaredChildFocusHierarchyMatches(
            before, focused + (childPath to fingerprint("child-after", "child-neutral",
                listOf(AccessibilityNodeInfo.ACTION_CLICK,
                    AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS), true, complete = false)),
            childPath))
        assertFalse(exactDeclaredChildFocusHierarchyMatches(
            before, focused + (childPath to fingerprint("child-after", "child-neutral",
                listOf(AccessibilityNodeInfo.ACTION_CLICK,
                    AccessibilityNodeInfo.ACTION_CLEAR_ACCESSIBILITY_FOCUS), false)), childPath))
    }

    private class FakeTarget(
        override val packageName: String = "com.example.app",
        override val className: String = "android.widget.RelativeLayout",
        override val resourceId: String = "",
        override val label: String = "Example",
        override val windowId: Int = 7,
        override val nodePath: List<Int> = listOf(2, 1),
        override val descriptorDigest: String = "d".repeat(64),
        override val sourceSnapshotId: String = "source-snapshot",
        override val helperSnapshotId: String = "helper-snapshot",
        override val baselineHierarchyDigest: String = "b".repeat(64),
        override val connectionId: String = "connection-1",
        override val independentDescendants: Int = 1,
        override val independentSiblings: Int = 0,
        override val isUniqueInSnapshot: Boolean = true,
        override val hasClickAction: Boolean = true,
        override val hasAccessibilityFocusAction: Boolean = true,
        override val subtreeLabels: List<String> = listOf("Example context"),
        override val descendantEvidenceComplete: Boolean = true,
        private val descendants: List<NavigationDescendantEvidence> = listOf(
            NavigationDescendantEvidence("android.widget.FrameLayout", "com.example.app:id/action_child",
                "Excluded action child", true, false, false, false, false, setOf(16)),
            NavigationDescendantEvidence("android.widget.TextView", "com.example.app:id/safe_label",
                "Safe label", false, false, false, false, false, emptySet()),
        ),
    ) : NavigationActionTargetLease {
        val identity = Any()
        var current = true
        var currentAfterFocus = true
        var focusActionAcknowledged = true
        var focusRevalidationResult: NavigationFocusRevalidationResult? = null
        var accessibilityFocused = false
        var activationChild: NavigationActionTargetLease? = null
        var focusActionCalls = 0
        var parentActionCalls = 0
        var childActionCalls = 0
        val actionSequence = mutableListOf<String>()
        override fun stillCurrent(currentConnectionId: String) = current && currentConnectionId == connectionId
        override fun stillCurrentAfterAccessibilityFocus(currentConnectionId: String) =
            current && currentAfterFocus && accessibilityFocused && currentConnectionId == connectionId
        override fun revalidateAfterAccessibilityFocus(currentConnectionId: String) =
            focusRevalidationResult ?: super<NavigationActionTargetLease>
                .revalidateAfterAccessibilityFocus(currentConnectionId)
        override fun descendantEvidence() = descendants
        override fun exactDeclaredActivationChild(
            relation: NavigationActivationOwnerRelation,
            currentConnectionId: String,
        ): NavigationActionTargetLease? = activationChild?.takeIf { child ->
            relation.isWellFormed() && stillCurrent(currentConnectionId) &&
                child.windowId == windowId && child.connectionId == currentConnectionId &&
                child.nodePath == nodePath + relation.childIndex && child.packageName == packageName &&
                Regex(relation.childClassPattern).matches(child.className) &&
                child.resourceId == relation.childResourceId && child.isUniqueInSnapshot && child.hasClickAction &&
                child.stillCurrent(currentConnectionId)
        }
        override fun eventSourceMatches(source: Any?, eventWindowId: Int, currentConnectionId: String) =
            source === identity && eventWindowId == windowId && currentConnectionId == connectionId && current
        override fun performNavigationAccessibilityFocus(
            authorization: NavigationActionDispatchAuthorization,
            requestId: String,
            transactionId: String,
            leaseToken: String,
            currentConnectionId: String,
        ): Boolean {
            if (!authorization.consume(requestId, transactionId, leaseToken, NAVIGATION_ACTION_ACCESSIBILITY_FOCUS) ||
                !stillCurrent(currentConnectionId) || !hasAccessibilityFocusAction || !focusActionAcknowledged) return false
            focusActionCalls++
            accessibilityFocused = true
            actionSequence += "focus"
            return true
        }
        override fun performNavigationClick(
            authorization: NavigationActionDispatchAuthorization,
            requestId: String,
            transactionId: String,
            leaseToken: String,
            currentConnectionId: String,
        ): Boolean {
            if (!authorization.consume(requestId, transactionId, leaseToken, NAVIGATION_ACTION_CLICK) ||
                !stillCurrent(currentConnectionId)) return false
            parentActionCalls++
            actionSequence += "click"
            return true
        }
        override fun performNavigationClickAfterAccessibilityFocus(
            authorization: NavigationActionDispatchAuthorization,
            requestId: String,
            transactionId: String,
            leaseToken: String,
            currentConnectionId: String,
        ): Boolean {
            if (!authorization.consume(requestId, transactionId, leaseToken, NAVIGATION_ACTION_CLICK) ||
                !stillCurrentAfterAccessibilityFocus(currentConnectionId)) return false
            parentActionCalls++
            actionSequence += "click"
            return true
        }
    }

    private fun contract(): NavigationEffectContract {
        val id = "reviewed-navigation-test"
        val evidence = listOf("review:test-contract")
        val effect = "read_only_navigation"
        val packageName = "com.example.app"
        val targetClass = "android\\.widget\\.RelativeLayout"
        val targetResource = ".*"
        val targetLabel = "^Example$"
        val targetSubtree = "Example context"
        val destination = "Dashboard"
        val anchor = "Navigate up"
        val returnTransport = "BACK"
        val expectedDescendantCount = 2
        val excludedChildren = listOf("com.example.app:id/action_child")
        val requiredNonActionableLabels = listOf("^Safe label$")
        val scenarios = listOf("scenario-test")
        val sourceEvidenceDigest = "e".repeat(64)
        val digest = NavigationEffectContract.digestFor(id, effect, packageName, targetClass,
            targetResource, targetLabel, targetSubtree, destination, anchor, returnTransport,
            expectedDescendantCount, excludedChildren, requiredNonActionableLabels,
            scenarios, evidence, sourceEvidenceDigest)
        return NavigationEffectContract(id, digest, effect, packageName, targetClass, targetResource,
            targetLabel, targetSubtree, destination, anchor, returnTransport, expectedDescendantCount,
            excludedChildren, requiredNonActionableLabels, scenarios, evidence, sourceEvidenceDigest)
    }

    private fun airCareDiagnosticContract(): NavigationEffectContract {
        val id = "life_service_card_read_only_navigation"
        val effect = "read_only_navigation"
        val packageName = "com.samsung.android.oneconnect"
        val targetClass = "^android\\.widget\\.RelativeLayout$"
        val targetResource = ".*"
        val targetLabel = "^Air Care$"
        val targetSubtree = "Air Care"
        val destination = """(?i)^(?:air\s*care|에어\s*케어)$"""
        val anchor = "(?i)^(?:navigate\\s*up|navigate\\s*to\\s*parent\\s*menu|상위\\s*메뉴로\\s*이동)$"
        val scenarios = listOf("life_air_care_plugin")
        val evidence = listOf("reviewed:air-care-parent")
        val sourceDigest = "e".repeat(64)
        val relation = NavigationActivationOwnerRelation("direct_child", 0,
            "^android\\.widget\\.FrameLayout$", "com.samsung.android.oneconnect:id/frameLayout")
        val emptyState = NavigationEmptyStateSignature(
            "방에 에어컨이나 공기청정기를 추가하여 방 안의 공기를 자동으로 관리해 보세요.",
            "android.widget.FrameLayout", "android.view.View", "paneContainer", "android.webkit.WebView",
            "android.widget.Button", "back", "android.widget.GridView")
        val digest = NavigationEffectContract.digestFor(id, effect, packageName, targetClass,
            targetResource, targetLabel, targetSubtree, destination, anchor, "BACK", 0,
            emptyList(), emptyList(), scenarios, evidence, sourceDigest, relation, emptyState)
        return NavigationEffectContract(id, digest, effect, packageName, targetClass, targetResource,
            targetLabel, targetSubtree, destination, anchor, "BACK", 0, emptyList(), emptyList(),
            scenarios, evidence, sourceDigest, relation, emptyState)
    }

    private fun airCareDiagnosticParent(connectionId: String = "service-1", windowId: Int = 150): FakeTarget {
        val parent = FakeTarget(
            packageName = "com.samsung.android.oneconnect", className = "android.widget.RelativeLayout",
            label = "Air Care", windowId = windowId, nodePath = listOf(0, 1, 4),
            descriptorDigest = "p".repeat(64), sourceSnapshotId = "aircare-source",
            helperSnapshotId = "aircare-helper", baselineHierarchyDigest = "h".repeat(64),
            connectionId = connectionId, independentDescendants = 0, independentSiblings = 0,
            subtreeLabels = listOf("Air Care"), descendantEvidenceComplete = true, descendants = emptyList(),
        )
        parent.activationChild = airCareDiagnosticChild(parent)
        return parent
    }

    private fun airCareDiagnosticChild(
        parent: FakeTarget,
        path: List<Int> = parent.nodePath + 0,
        className: String = "android.widget.FrameLayout",
        resourceId: String = "com.samsung.android.oneconnect:id/frameLayout",
        windowId: Int = parent.windowId,
        connectionId: String = parent.connectionId,
    ) = FakeTarget(
        packageName = "com.samsung.android.oneconnect", className = className, resourceId = resourceId,
        label = "", windowId = windowId, nodePath = path, descriptorDigest = "c".repeat(64),
        sourceSnapshotId = "aircare-source", helperSnapshotId = "aircare-helper",
        baselineHierarchyDigest = "h".repeat(64), connectionId = connectionId,
        independentDescendants = 0, independentSiblings = 0, subtreeLabels = emptyList(),
        descendantEvidenceComplete = true, descendants = emptyList(),
    )

    private fun airCareAuthority(
        binding: NavigationActionBinding,
        postWindowId: Int = 192,
        activeIds: List<Int> = listOf(postWindowId),
        serviceId: String = binding.serviceInstanceId,
        connectionId: String = binding.connectionId,
        observedAt: Long = 1_002L,
        rootWindowId: Int = postWindowId,
        rootPackage: String = "com.samsung.android.oneconnect",
        rootClass: String = "android.widget.FrameLayout",
    ) = NavigationPostWindowAuthority(
        requestId = binding.requestId, transactionId = binding.transactionId,
        serviceInstanceId = serviceId, connectionId = connectionId,
        actionWindowId = binding.windowId, clickWindowId = binding.windowId,
        clickEventType = AccessibilityEvent.TYPE_VIEW_CLICKED, clickEventElapsedRealtimeMs = 1_001L,
        postWindowId = postWindowId, activeType1WindowIds = activeIds, observedAtUptimeMs = observedAt,
        rootWindowId = rootWindowId, rootPackageName = rootPackage, rootClassName = rootClass,
    )

    private fun airCarePost(
        binding: NavigationActionBinding,
        captureId: String = "aircare-post",
        capturedAt: Long = 1_003L,
        focused: Boolean = true,
        structure: NavigationPostStructureEvidence = NavigationPostStructureEvidence(
            exactTextCount = 1, exactTextWithinWebView = true, containerCount = 1,
            containerWithinWebView = false, webViewCount = 2, exactBackAnchorCount = 1,
            excludedClassPresent = false, anchorPath = listOf(0, 0, 0),
        ),
        authority: NavigationPostWindowAuthority = airCareAuthority(binding),
        anchorTarget: NavigationActionTargetLease? = null,
    ) = NavigationPostActionEvidence(
        requestId = binding.requestId, transactionId = binding.transactionId,
        serviceInstanceId = binding.serviceInstanceId, connectionId = binding.connectionId,
        windowId = authority.postWindowId, captureId = captureId, capturedAtUptimeMs = capturedAt,
        hierarchyDigest = "f".repeat(64),
        labels = listOf(
            "방에 에어컨이나 공기청정기를 추가하여 방 안의 공기를 자동으로 관리해 보세요.",
            "에어 케어", "상위 메뉴로 이동"),
        focusWindowId = if (focused) authority.postWindowId else null,
        accessibilityFocused = focused, focusInCurrentHierarchy = focused,
        nodeCount = 65, rootPackageName = authority.rootPackageName,
        rootClassName = authority.rootClassName, postWindowAuthority = authority,
        structureEvidence = structure, destinationAnchorTarget = anchorTarget,
    )

    private fun ownerDispatchReceipt(
        binding: NavigationActionBinding,
        actionTarget: NavigationActionTargetLease,
        authorizationTarget: NavigationActionTargetLease,
        relation: NavigationActivationOwnerRelation?,
        dispatchElapsedRealtimeMs: Long,
    ) = ownerReceipt(binding, actionTarget, authorizationTarget, relation, dispatchElapsedRealtimeMs,
        eligibleExactClickCount = 0, clickEventId = null, clickEventElapsedRealtimeMs = null,
        clickEventType = null, clickEventWindowId = null, ownerExact = false)

    private fun ownerConfirmedClickReceipt(
        binding: NavigationActionBinding,
        actionTarget: NavigationActionTargetLease,
        authorizationTarget: NavigationActionTargetLease,
        relation: NavigationActivationOwnerRelation?,
        dispatchElapsedRealtimeMs: Long,
        clickEventElapsedRealtimeMs: Long = 1_001L,
        clickEventType: Int = AccessibilityEvent.TYPE_VIEW_CLICKED,
        clickEventWindowId: Int = binding.windowId,
    ) = ownerReceipt(binding, actionTarget, authorizationTarget, relation, dispatchElapsedRealtimeMs,
        eligibleExactClickCount = 1, clickEventId = "owner-click",
        clickEventElapsedRealtimeMs = clickEventElapsedRealtimeMs,
        clickEventType = clickEventType, clickEventWindowId = clickEventWindowId, ownerExact = true)

    private fun ownerReceipt(
        binding: NavigationActionBinding,
        actionTarget: NavigationActionTargetLease,
        authorizationTarget: NavigationActionTargetLease,
        relation: NavigationActivationOwnerRelation?,
        dispatchElapsedRealtimeMs: Long,
        eligibleExactClickCount: Int,
        clickEventId: String?,
        clickEventElapsedRealtimeMs: Long?,
        clickEventType: Int?,
        clickEventWindowId: Int?,
        ownerExact: Boolean,
    ) = JSONObject()
        .put("ok", true)
        .put("reason", if (ownerExact) "EXACT_OWNER_CLICK_CONFIRMED" else "DISPATCH_MARKED")
        .put("ownerLeaseId", binding.ownerLeaseId)
        .put("dispatchElapsedRealtimeMs", dispatchElapsedRealtimeMs)
        .put("eligibleExactClickCount", eligibleExactClickCount)
        .put("clickEventId", clickEventId ?: JSONObject.NULL)
        .put("clickEventElapsedRealtimeMs", clickEventElapsedRealtimeMs ?: JSONObject.NULL)
        .put("clickEventType", clickEventType ?: JSONObject.NULL)
        .put("clickEventWindowId", clickEventWindowId ?: JSONObject.NULL)
        .put("ownerExact", ownerExact)
        .put("ownerActionPath", org.json.JSONArray(actionTarget.nodePath))
        .put("ownerActionDescriptorDigest", actionTarget.descriptorDigest)
        .put("ownerActionWindowId", actionTarget.windowId)
        .put("ownerActionConnectionId", actionTarget.connectionId)
        .put("ownerAuthorizationPath", org.json.JSONArray(authorizationTarget.nodePath))
        .put("ownerAuthorizationDescriptorDigest", authorizationTarget.descriptorDigest)
        .put("ownerAuthorizationWindowId", authorizationTarget.windowId)
        .put("activationOwnerRelation", relation?.toJson() ?: JSONObject.NULL)
        .put("navigationRequestId", binding.requestId)
        .put("ownerCaptureReqId", binding.ownerCaptureReqId)
        .put("transactionId", binding.transactionId)
        .put("serviceInstanceId", binding.serviceInstanceId)

    @Test fun productionAirCareDeclaredChildKeepsActionWindowAndBindsFreshPostWindow() {
        val policy = airCareDiagnosticContract()
        val parent = airCareDiagnosticParent()
        val child = airCareDiagnosticChild(parent)
        val actionBinding = binding(child, policy).copy(scenarioId = "life_air_care_plugin")
        val capability = NavigationActionCapability(mapOf(policy.id to policy), { 1_000L })
        val wrongChild = airCareDiagnosticChild(parent, path = parent.nodePath + 1)
        parent.activationChild = wrongChild
        val wrongBinding = binding(wrongChild, policy).copy(scenarioId = "life_air_care_plugin")
        val wrong = capability.prepare(wrongBinding, wrongChild, "service-1", wrongChild.connectionId,
            activationOwnerTarget = parent)
        assertEquals("NAVIGATION_ACTIVATION_CHILD_UNPROVEN", wrong.optString("failure_code"))
        parent.activationChild = child
        val prepared = capability.prepare(actionBinding, child, "service-1", child.connectionId,
            activationOwnerTarget = parent)
        assertEquals("PREPARED", prepared.optString("status"))
        val post = airCarePost(actionBinding)
        val receipt = capability.dispatch(
            prepared.getString("lease_token"), actionBinding, "service-1", child.connectionId,
            armCollector = { bound, target -> bound == actionBinding && target === child },
            awaitClick = { NavigationClickEvidence(actionBinding.requestId, actionBinding.transactionId,
                actionBinding.serviceInstanceId, actionBinding.connectionId, actionBinding.windowId,
                AccessibilityEvent.TYPE_VIEW_CLICKED, 1_001L, child.identity) },
            markOwnerDispatch = { dispatchElapsed ->
                assertEquals(0, child.parentActionCalls)
                ownerDispatchReceipt(actionBinding, child, parent, policy.activationOwnerRelation, dispatchElapsed)
            },
            confirmOwnerDispatch = { dispatchElapsed ->
                assertEquals(1, child.parentActionCalls)
                ownerConfirmedClickReceipt(actionBinding, child, parent, policy.activationOwnerRelation,
                    dispatchElapsed)
            },
            capturePostAction = { deadline, click ->
                assertEquals(6_000L, deadline)
                assertEquals(actionBinding.requestId, click.requestId)
                post
            },
            currentServiceStillBound = { true },
        )
        assertTrue(receipt.optBoolean("verified_navigation"))
        assertEquals("ACTION_CLICK", receipt.optString("action"))
        assertFalse(receipt.has("activation_mode"))
        assertEquals(150, receipt.optInt("window_id"))
        val diagnostics = receipt.getJSONObject("post_state_diagnostics")
        assertEquals(150, diagnostics.optInt("action_window_id"))
        assertEquals(192, diagnostics.optInt("capture_window_id"))
        assertEquals(192, diagnostics.optInt("post_window_id"))
        assertEquals(parent.nodePath, (0 until diagnostics.getJSONArray("action_owner_path").length())
            .map { diagnostics.getJSONArray("action_owner_path").getInt(it) })
        assertEquals(child.nodePath, (0 until diagnostics.getJSONArray("action_target_path").length())
            .map { diagnostics.getJSONArray("action_target_path").getInt(it) })
        val authority = diagnostics.getJSONObject("post_window_authority")
        assertEquals(150, authority.optInt("action_window_id"))
        assertEquals(192, authority.optInt("post_window_id"))
        assertEquals(listOf(192), (0 until authority.getJSONArray("active_type1_window_ids").length())
            .map { authority.getJSONArray("active_type1_window_ids").getInt(it) })
        assertEquals(0, parent.parentActionCalls)
        assertEquals(1, child.parentActionCalls)
        assertFalse(receipt.optBoolean("visit_authority"))
        assertFalse(receipt.optBoolean("c5_credit"))
    }

    @Test fun productionAirCarePostWindowRejectsStaleForeignAmbiguousAndMismatchedAuthority() {
        val policy = airCareDiagnosticContract()
        fun dispatchWith(authorityFactory: (NavigationActionBinding) -> NavigationPostWindowAuthority): JSONObject {
            val parent = airCareDiagnosticParent()
            val child = airCareDiagnosticChild(parent)
            val actionBinding = binding(child, policy).copy(scenarioId = "life_air_care_plugin")
            val capability = NavigationActionCapability(mapOf(policy.id to policy), { 1_000L })
            val prepared = capability.prepare(actionBinding, child, "service-1", child.connectionId,
                activationOwnerTarget = parent)
            assertEquals("PREPARED", prepared.optString("status"))
            val post = airCarePost(actionBinding, authority = authorityFactory(actionBinding))
            return capability.dispatch(
                prepared.getString("lease_token"), actionBinding, "service-1", child.connectionId,
                armCollector = { _, target -> target === child },
                awaitClick = { NavigationClickEvidence(actionBinding.requestId, actionBinding.transactionId,
                    actionBinding.serviceInstanceId, actionBinding.connectionId, actionBinding.windowId,
                    AccessibilityEvent.TYPE_VIEW_CLICKED, 1_001L, child.identity) },
                markOwnerDispatch = { dispatchElapsed -> ownerDispatchReceipt(actionBinding, child, parent,
                    policy.activationOwnerRelation, dispatchElapsed) },
                confirmOwnerDispatch = { dispatchElapsed -> ownerConfirmedClickReceipt(actionBinding, child, parent,
                    policy.activationOwnerRelation, dispatchElapsed) },
                capturePostAction = { _, _ -> post },
                currentServiceStillBound = { true },
            )
        }
        val invalid = listOf<(NavigationActionBinding) -> NavigationPostWindowAuthority>(
            { airCareAuthority(it, observedAt = 1_000L) },
            { airCareAuthority(it, serviceId = "foreign-service") },
            { airCareAuthority(it, connectionId = "foreign-connection") },
            { airCareAuthority(it, activeIds = listOf(192, 193)) },
            { airCareAuthority(it, rootWindowId = 150) },
            { airCareAuthority(it, rootPackage = "com.other.app") },
        )
        invalid.forEach { factory ->
            val receipt = dispatchWith(factory)
            assertEquals("NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE", receipt.optString("failure_code"))
            assertTrue(receipt.getJSONArray("post_state_mismatch_fields").toString()
                .contains("post_window_authority_mismatch"))
            assertFalse(receipt.optBoolean("verified_navigation"))
            assertFalse(receipt.optBoolean("visit_authority"))
            assertFalse(receipt.optBoolean("c5_credit"))
        }
    }

    @Test fun productionAirCareEmptyStateRejectsLifeGridAndUsesExistingExactFocusAction() {
        val policy = airCareDiagnosticContract()
        val parent = airCareDiagnosticParent()
        val child = airCareDiagnosticChild(parent)
        val actionBinding = binding(child, policy).copy(scenarioId = "life_air_care_plugin")
        var now = 1_000L
        val capability = NavigationActionCapability(mapOf(policy.id to policy), { now })
        val prepared = capability.prepare(actionBinding, child, "service-1", child.connectionId,
            activationOwnerTarget = parent)
        assertEquals("PREPARED", prepared.optString("status"))
        val base = airCarePost(actionBinding, capturedAt = 1_002L, focused = false)
        val anchor = FakeTarget(
            packageName = "com.samsung.android.oneconnect", className = "android.widget.Button",
            resourceId = "back", label = "상위 메뉴로 이동", windowId = 192,
            nodePath = base.structureEvidence!!.anchorPath, descriptorDigest = "a".repeat(64),
            sourceSnapshotId = base.captureId, helperSnapshotId = base.captureId,
            baselineHierarchyDigest = "b".repeat(64), connectionId = actionBinding.connectionId,
        )
        val initial = base.copy(destinationAnchorTarget = anchor)
        val fresh = airCarePost(actionBinding, captureId = "aircare-post-focused", capturedAt = 1_004L,
            focused = true, authority = airCareAuthority(actionBinding, observedAt = 1_003L))
        var captures = 0
        val receipt = capability.dispatch(
            prepared.getString("lease_token"), actionBinding, "service-1", child.connectionId,
            armCollector = { _, target -> target === child },
            awaitClick = { NavigationClickEvidence(actionBinding.requestId, actionBinding.transactionId,
                actionBinding.serviceInstanceId, actionBinding.connectionId, actionBinding.windowId,
                AccessibilityEvent.TYPE_VIEW_CLICKED, 1_001L, child.identity) },
            markOwnerDispatch = { dispatchElapsed -> ownerDispatchReceipt(actionBinding, child, parent,
                policy.activationOwnerRelation, dispatchElapsed) },
            confirmOwnerDispatch = { dispatchElapsed -> ownerConfirmedClickReceipt(actionBinding, child, parent,
                policy.activationOwnerRelation, dispatchElapsed) },
            capturePostAction = { deadline, _ ->
                assertEquals(6_000L, deadline)
                captures++
                if (captures == 1) { now = 1_002L; initial }
                else { now = 1_004L; fresh }
            },
            currentServiceStillBound = { true },
        )
        assertTrue(receipt.optBoolean("verified_navigation"))
        assertEquals(2, captures)
        assertEquals(1, anchor.focusActionCalls)
        assertEquals(0, anchor.parentActionCalls)
        val focus = receipt.getJSONObject("post_state_diagnostics").getJSONObject("destination_anchor_focus")
        assertEquals("aircare-post-focused", focus.optString("fresh_capture_id"))
        assertEquals(192, focus.optInt("fresh_capture_window_id"))
        assertTrue(focus.optBoolean("same_post_window"))

        val excluded = airCarePost(actionBinding,
            structure = base.structureEvidence!!.copy(excludedClassPresent = true))
        val excludedCap = NavigationActionCapability(mapOf(policy.id to policy), { 1_000L })
        val excludedPrepared = excludedCap.prepare(actionBinding, child, "service-1", child.connectionId,
            activationOwnerTarget = parent)
        assertEquals("PREPARED", excludedPrepared.optString("status"))
        val excludedReceipt = excludedCap.dispatch(
            excludedPrepared.getString("lease_token"), actionBinding, "service-1", child.connectionId,
            armCollector = { _, target -> target === child },
            awaitClick = { NavigationClickEvidence(actionBinding.requestId, actionBinding.transactionId,
                actionBinding.serviceInstanceId, actionBinding.connectionId, actionBinding.windowId,
                AccessibilityEvent.TYPE_VIEW_CLICKED, 1_001L, child.identity) },
            markOwnerDispatch = { dispatchElapsed -> ownerDispatchReceipt(actionBinding, child, parent,
                policy.activationOwnerRelation, dispatchElapsed) },
            confirmOwnerDispatch = { dispatchElapsed -> ownerConfirmedClickReceipt(actionBinding, child, parent,
                policy.activationOwnerRelation, dispatchElapsed) },
            capturePostAction = { _, _ -> excluded },
            currentServiceStillBound = { true },
        )
        assertEquals("NAVIGATION_DESTINATION_FOCUS_ANCHOR_UNPROVEN", excludedReceipt.optString("failure_code"))
        assertFalse(excludedReceipt.optBoolean("verified_navigation"))
        assertEquals(0, child.focusActionCalls)
    }

    @Test fun airCareDiagnosticChildRequiresExactCurrentSameWindowLease() {
        val policy = airCareDiagnosticContract()
        val parent = airCareDiagnosticParent()
        val child = airCareDiagnosticChild(parent)
        fun prepare(target: FakeTarget, parentTarget: FakeTarget = parent,
            service: String = "service-1"): JSONObject {
            val actionBinding = binding(target, policy,
                NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK)
                .copy(scenarioId = "life_air_care_plugin")
            return NavigationActionCapability(mapOf(policy.id to policy), { 1_000L })
                .prepare(actionBinding, target, service, target.connectionId, parentTarget)
        }

        val exact = prepare(child)
        assertEquals("PREPARED", exact.optString("status"))
        assertFalse(exact.optBoolean("visit_authority"))
        assertEquals("NAVIGATION_DIAGNOSTIC_CHILD_UNPROVEN",
            prepare(airCareDiagnosticChild(parent, path = parent.nodePath + 1)).optString("failure_code"))
        assertEquals("NAVIGATION_DIAGNOSTIC_CHILD_UNPROVEN",
            prepare(airCareDiagnosticChild(parent,
                resourceId = "com.samsung.android.oneconnect:id/include")).optString("failure_code"))
        assertEquals("NAVIGATION_DIAGNOSTIC_CHILD_UNPROVEN",
            prepare(airCareDiagnosticChild(parent, className = "android.widget.LinearLayout"))
                .optString("failure_code"))
        assertEquals("NAVIGATION_DIAGNOSTIC_CHILD_UNPROVEN",
            prepare(airCareDiagnosticChild(parent, windowId = 151)).optString("failure_code"))
        assertEquals("NAVIGATION_BINDING_MISMATCH",
            prepare(child, service = "other-service").optString("failure_code"))
        parent.current = false
        assertEquals("NAVIGATION_DIAGNOSTIC_CHILD_UNPROVEN", prepare(child).optString("failure_code"))
        assertEquals(0, parent.parentActionCalls)
        assertEquals(0, child.parentActionCalls)
    }

    @Test fun airCareDiagnosticChildActionAndPostSampleNeverGrantCredit() {
        val policy = airCareDiagnosticContract()
        val parent = airCareDiagnosticParent()
        val child = airCareDiagnosticChild(parent)
        val mode = NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK
        val actionBinding = binding(child, policy, mode).copy(scenarioId = "life_air_care_plugin")
        val capability = NavigationActionCapability(mapOf(policy.id to policy), { 1_000L })
        val prepared = capability.prepare(actionBinding, child, "service-1", child.connectionId, parent)
        assertEquals("PREPARED", prepared.optString("status"))

        val receipt = dispatch(capability, actionBinding, prepared.getString("lease_token"), child)

        assertEquals("DIAGNOSTIC_ONLY", receipt.optString("status"))
        assertTrue(receipt.optBoolean("diagnostic_only"))
        assertTrue(receipt.optBoolean("diagnostic_action_dispatched"))
        assertFalse(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertFalse(receipt.optBoolean("c5_credit"))
        assertFalse(receipt.optBoolean("traversal_credit"))
        assertEquals(1, receipt.optInt("action_call_count"))
        val target = receipt.getJSONObject("diagnostic_target")
        assertEquals("android.widget.FrameLayout", target.optString("class_name"))
        assertEquals("com.samsung.android.oneconnect:id/frameLayout", target.optString("resource_id"))
        assertEquals(listOf(0, 1, 4, 0), (0 until target.getJSONArray("path").length())
            .map { target.getJSONArray("path").getInt(it) })
        assertTrue(receipt.getJSONObject("diagnostic_click_event").optBoolean("exact_target_match"))
        assertEquals("NAVIGATION_DESTINATION_FOCUS_ANCHOR_UNPROVEN", receipt.optString("failure_code"))
        assertEquals(0, parent.parentActionCalls)
        assertEquals(1, child.parentActionCalls)
    }

    @Test fun diagnosticPollTraceSurvivesNullSampleAndRecordsWindowAndServiceStagesWithoutCredit() {
        val policy = airCareDiagnosticContract()
        val parent = airCareDiagnosticParent()
        val child = airCareDiagnosticChild(parent)
        val mode = NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK
        val actionBinding = binding(child, policy, mode).copy(scenarioId = "life_air_care_plugin")
        val capability = NavigationActionCapability(mapOf(policy.id to policy), { 1_000L })
        val prepared = capability.prepare(actionBinding, child, "service-1", child.connectionId, parent)
        assertEquals("PREPARED", prepared.optString("status"))

        val trace = NavigationPostCapturePollTrace(actionBinding)
        trace.beginAttempt(1_100L)
        trace.observeWindows(listOf(
            NavigationPostCaptureWindowObservation(actionBinding.windowId, 1, false),
            NavigationPostCaptureWindowObservation(actionBinding.windowId + 1, 1, true),
            NavigationPostCaptureWindowObservation(actionBinding.windowId + 2, 3, true),
        ))
        trace.skip("ACTION_WINDOW_NOT_ACTIVE_TYPE1")
        trace.beginAttempt(1_150L)
        trace.markServiceChanged(1_150L)

        val receipt = dispatch(capability, actionBinding, prepared.getString("lease_token"), child,
            captureMissing = true, pollingDiagnostics = trace.toJson())

        assertEquals("DIAGNOSTIC_ONLY", receipt.optString("status"))
        assertFalse(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertFalse(receipt.optBoolean("c5_credit"))
        assertFalse(receipt.optBoolean("traversal_credit"))
        val diagnostics = receipt.getJSONObject("post_state_diagnostics")
        assertEquals("MISSING", diagnostics.optString("capture_call_result"))
        val polling = diagnostics.getJSONObject("capture_polling")
        assertEquals(actionBinding.requestId, polling.optString("request_id"))
        assertEquals(actionBinding.transactionId, polling.optString("transaction_id"))
        assertEquals(actionBinding.serviceInstanceId, polling.optString("service_instance_id"))
        assertEquals(actionBinding.connectionId, polling.optString("connection_id"))
        assertEquals(actionBinding.windowId, polling.optInt("action_window_id"))
        assertEquals(2, polling.optInt("attempt_count"))
        assertEquals(0, polling.optInt("complete_sample_count"))
        assertEquals(1_100L, polling.optLong("first_attempt_elapsed_realtime_ms"))
        assertEquals(1_150L, polling.optLong("last_attempt_elapsed_realtime_ms"))
        assertEquals(listOf(actionBinding.windowId + 1), (0 until
            polling.getJSONArray("observed_active_type1_window_ids").length()).map {
            polling.getJSONArray("observed_active_type1_window_ids").getInt(it)
        })
        val rows = polling.getJSONArray("observed_type1_window_states")
        assertEquals(2, rows.length())
        assertEquals(actionBinding.windowId, rows.getJSONObject(0).optInt("window_id"))
        assertFalse(rows.getJSONObject(0).optBoolean("last_active"))
        assertEquals(1, rows.getJSONObject(0).optInt("inactive_observation_count"))
        assertEquals(1, polling.getJSONObject("skip_reason_counts")
            .optInt("ACTION_WINDOW_NOT_ACTIVE_TYPE1"))
        assertTrue(polling.optBoolean("service_changed"))
        assertEquals("SERVICE_CHANGED_DURING_POLL", polling.optString("termination_stage"))
        assertFalse(polling.optBoolean("deadline_reached"))
        assertTrue(polling.isNull("root_package_name"))
        assertTrue(polling.isNull("root_class_name"))

        val deadlineTrace = NavigationPostCapturePollTrace(actionBinding)
        deadlineTrace.beginAttempt(2_000L)
        deadlineTrace.recordCompleteSample(2_010L, "com.samsung.android.oneconnect", "android.widget.FrameLayout")
        deadlineTrace.skip("COMPLETE_SAMPLE_NOT_VERIFIED")
        deadlineTrace.markDeadlineReached(2_050L)
        val deadline = deadlineTrace.toJson()
        assertEquals(1, deadline.optInt("complete_sample_count"))
        assertTrue(deadline.optBoolean("deadline_reached"))
        assertEquals("POST_CAPTURE_DEADLINE_REACHED", deadline.optString("termination_stage"))
        assertEquals("com.samsung.android.oneconnect", deadline.optString("root_package_name"))
        assertEquals("android.widget.FrameLayout", deadline.optString("root_class_name"))
    }

    @Test fun contractRegistryUsesOnlyEnabledLocalRowsAndBindsTheirSourceBytes() {
        val row = JSONObject().put("id", "reviewed_nav")
            .put("enabled", true)
            .put("package", "com.example.app")
            .put("resource_id", "com.example.app:id/navigation")
            .put("target_class_pattern", "android\\.widget\\.Button")
            .put("label_pattern", "^Open$" )
            .put("target_subtree_pattern", "Open target")
            .put("scenario_ids", org.json.JSONArray().put("scenario-test"))
            .put("effect", "read_only_navigation")
            .put("destination_pattern", "Dashboard")
            .put("required_anchor_pattern", "Navigate up")
            .put("return_transport", "BACK")
            .put("expected_descendant_count", 2)
            .put("excluded_descendant_resource_ids", org.json.JSONArray().put("com.example.app:id/action_child"))
            .put("required_non_actionable_descendant_label_patterns", org.json.JSONArray().put("^Safe label$"))
            .put("evidence_refs", org.json.JSONArray().put("review:test-policy"))
        val disabledRow = JSONObject(row.toString()).put("enabled", false)
        val disabled = JSONObject().put("schema", "safe-navigation-contracts-v1")
            .put("default_enabled", false).put("contracts", org.json.JSONArray().put(disabledRow))
            .toString().toByteArray(Charsets.UTF_8)
        assertTrue(NavigationEffectContractRegistry.load(disabled).isEmpty())

        val incomplete = JSONObject(row.toString())
        incomplete.remove("destination_pattern")
        incomplete.remove("required_anchor_pattern")
        val incompleteEnabled = JSONObject().put("schema", "safe-navigation-contracts-v1")
            .put("default_enabled", false).put("contracts", org.json.JSONArray().put(incomplete))
            .toString().toByteArray(Charsets.UTF_8)
        assertTrue(NavigationEffectContractRegistry.load(incompleteEnabled).isEmpty())

        val missingChildConstraints = JSONObject(row.toString())
        missingChildConstraints.remove("excluded_descendant_resource_ids")
        val missingChildConstraintsPolicy = JSONObject().put("schema", "safe-navigation-contracts-v1")
            .put("default_enabled", false).put("contracts", org.json.JSONArray().put(missingChildConstraints))
            .toString().toByteArray(Charsets.UTF_8)
        assertTrue(NavigationEffectContractRegistry.load(missingChildConstraintsPolicy).isEmpty())

        val enabled = JSONObject().put("schema", "safe-navigation-contracts-v1")
            .put("default_enabled", false).put("contracts", org.json.JSONArray().put(row))
            .toString().toByteArray(Charsets.UTF_8)
        val loaded = NavigationEffectContractRegistry.load(enabled).getValue("reviewed_nav")
        assertTrue(loaded.isWellFormed(loaded.digest))
        val globallyEnabled = JSONObject().put("schema", "safe-navigation-contracts-v1")
            .put("default_enabled", true).put("contracts", org.json.JSONArray().put(row))
            .toString().toByteArray(Charsets.UTF_8)
        assertTrue(NavigationEffectContractRegistry.load(globallyEnabled).isEmpty())
        val changedSource = (enabled.toString(Charsets.UTF_8) + " ").toByteArray(Charsets.UTF_8)
        val changed = NavigationEffectContractRegistry.load(changedSource).getValue("reviewed_nav")
        assertNotEquals(loaded.sourceEvidenceDigest, changed.sourceEvidenceDigest)
        assertNotEquals(loaded.digest, changed.digest)
    }

    private fun binding(target: FakeTarget, contract: NavigationEffectContract,
        activationMode: String = NAVIGATION_ACTIVATION_DIRECT_CLICK) = NavigationActionBinding(
        runId = "run-1", invocationId = "invocation-1", scenarioId = "scenario-test",
        requestId = "request-1", action = NAVIGATION_ACTION_CLICK, transactionId = "tx-1", ownerCaptureReqId = "owner-capture",
        ownerLeaseId = "owner-lease",
        serviceInstanceId = "service-1", connectionId = target.connectionId, windowId = target.windowId,
        sourceSnapshotId = target.sourceSnapshotId, helperSnapshotId = target.helperSnapshotId,
        captureId = "capture-1", nodePath = target.nodePath, descriptorDigest = target.descriptorDigest,
        baselineHierarchyDigest = target.baselineHierarchyDigest, effectContractId = contract.id,
        effectContractDigest = contract.digest,
        sourceIdentity = EntryClickSourceIdentity(
            requestId = "source-request-1", processEpoch = "process-1", generation = 7L,
            serviceInstanceId = "service-1", captureSequence = 12L,
            rootDigest = "a".repeat(64), candidateDigest = "c".repeat(64),
            captureKey = target.sourceSnapshotId, connectionEpoch = "connection-1",
            bootEpoch = "boot:33", ownerSourceNodeId = "owner-node-1",
            ownerSourceNodeIdStatus = "FIELD_PRESENT",
        ),
        activationMode = activationMode,
    )

    @Test fun windowChangeDiagnosticsBindToActiveRequestTransactionServiceAndWindow() {
        val target = FakeTarget()
        val binding = binding(target, contract())
        val event = NavigationWindowEventDiagnosticPolicy.correlate(
            binding = binding,
            target = target,
            currentServiceInstanceId = binding.serviceInstanceId,
            currentConnectionId = binding.connectionId,
            actionDispatchElapsedRealtimeMs = 1_000L,
            dispatchDeadlineElapsedRealtimeMs = 6_000L,
            eventType = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            eventPackage = target.packageName,
            eventClass = "com.example.app.DestinationActivity",
            eventWindowId = target.windowId,
            eventElapsedRealtimeMs = 1_001L,
        )

        assertNotNull(event)
        assertEquals(binding.requestId, event!!.requestId)
        assertEquals(binding.transactionId, event.transactionId)
        assertEquals(binding.serviceInstanceId, event.serviceInstanceId)
        assertEquals(binding.connectionId, event.connectionId)
        assertEquals(binding.windowId, event.ownerWindowId)
        assertEquals(binding.windowId, event.eventWindowId)
        assertEquals(1_001L, event.eventElapsedRealtimeMs)
        assertNotNull(NavigationWindowEventDiagnosticPolicy.correlate(
            binding, target, binding.serviceInstanceId, binding.connectionId, 1_000L, 6_000L,
            AccessibilityEvent.TYPE_WINDOWS_CHANGED, target.packageName, null, target.windowId, 1_002L))
    }

    @Test fun staleUnrelatedOrOutOfWindowChangeEventsAreRejectedAsDiagnostics() {
        val target = FakeTarget()
        val binding = binding(target, contract())
        fun correlate(
            service: String = binding.serviceInstanceId,
            connection: String = binding.connectionId,
            type: Int = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            eventPackage: String? = target.packageName,
            window: Int = target.windowId,
            eventTime: Long = 1_001L,
        ) = NavigationWindowEventDiagnosticPolicy.correlate(
            binding, target, service, connection, 1_000L, 6_000L,
            type, eventPackage, "DestinationActivity", window, eventTime)

        assertNull(correlate(service = "stale-service"))
        assertNull(correlate(connection = "stale-connection"))
        assertNull(correlate(window = target.windowId + 1))
        assertNull(correlate(eventPackage = "com.other.app"))
        assertNull(correlate(eventTime = 999L))
        assertNull(correlate(eventTime = 6_001L))
        assertNull(correlate(type = AccessibilityEvent.TYPE_VIEW_CLICKED))
    }

    @Test fun secondaryWindowDiagnosticsStayOutsideStrictReceiptAndCredit() {
        val receipt = JSONObject().put("status", "REJECTED").put("verified_navigation", false)
            .put("visit_authority", false).put("c5_credit", false)
        val strict = JSONObject().put("success", false).put("receipt", receipt)
        val before = strict.toString()
        val diagnostics = JSONObject().put("evidence_role", "SECONDARY_ONLY")
            .put("request_id", "request-1").put("transaction_id", "tx-1")

        val response = attachSecondaryNavigationWindowDiagnostics(strict, diagnostics)

        assertEquals(before, strict.toString())
        assertEquals("REJECTED", response.getJSONObject("receipt").optString("status"))
        assertFalse(response.getJSONObject("receipt").optBoolean("visit_authority"))
        assertFalse(response.getJSONObject("receipt").optBoolean("c5_credit"))
        assertEquals("SECONDARY_ONLY", response.getJSONObject("secondary_window_event_diagnostics")
            .optString("evidence_role"))
    }

    private fun rig(target: FakeTarget, contract: NavigationEffectContract = contract(),
        activationMode: String = NAVIGATION_ACTIVATION_DIRECT_CLICK): Triple<NavigationActionCapability, NavigationActionBinding, String> {
        val capability = NavigationActionCapability(mapOf(contract.id to contract), { 1_000L })
        val binding = binding(target, contract, activationMode)
        val prepared = capability.prepare(binding, target, "service-1", target.connectionId)
        assertEquals("PREPARED", prepared.optString("status"))
        return Triple(capability, binding, prepared.getString("lease_token"))
    }

    private fun dispatch(
        capability: NavigationActionCapability,
        binding: NavigationActionBinding,
        token: String,
        target: FakeTarget,
        post: NavigationPostActionEvidence? = null,
        captureMissing: Boolean = false,
        clickSource: Any? = target.identity,
        focusEvent: NavigationFocusEvidence? = null,
        markOwnerDispatchAfterFocus: ((Long, NavigationFocusEvidence) -> JSONObject)? = null,
        ownerReceipt: JSONObject? = null,
        markActionDispatch: (Long, Long) -> Unit = { _, _ -> },
        pollingDiagnostics: JSONObject? = null,
    ): JSONObject = capability.dispatch(token, binding, "service-1", target.connectionId,
        armCollector = { bound, leased -> bound == binding && leased === target },
        awaitClick = { deadline -> NavigationClickEvidence(binding.requestId, binding.transactionId,
            binding.serviceInstanceId, binding.connectionId, target.windowId,
            AccessibilityEvent.TYPE_VIEW_CLICKED, 1_001L, clickSource) },
        markOwnerDispatch = { dispatchElapsed -> ownerDispatchReceipt(binding, target, target, null, dispatchElapsed) },
        markOwnerDispatchAfterFocus = markOwnerDispatchAfterFocus,
        confirmOwnerDispatch = { dispatchElapsed -> ownerReceipt ?: ownerConfirmedClickReceipt(
            binding, target, target, null, dispatchElapsed) },
        capturePostAction = { _, _ -> if (captureMissing) null else post ?: NavigationPostActionEvidence(
            binding.requestId, binding.transactionId, binding.serviceInstanceId, binding.connectionId,
            target.windowId, "post-capture", 1_002L, "c".repeat(64),
            listOf("Dashboard", "Navigate up"), target.windowId, true, true) },
        markActionDispatch = markActionDispatch,
        awaitAccessibilityFocus = { focusEvent },
        capturePostPollingDiagnostics = { pollingDiagnostics })

    @Test fun windowDiagnosticIntervalStartsImmediatelyBeforeExactActionCall() {
        val target = FakeTarget()
        val (capability, binding, token) = rig(target)
        var actionCallsAtMark = -1
        var interval: Pair<Long, Long>? = null

        val receipt = dispatch(capability, binding, token, target, markActionDispatch = { start, deadline ->
            actionCallsAtMark = target.parentActionCalls
            interval = start to deadline
        })

        assertEquals(0, actionCallsAtMark)
        assertEquals(1_000L to 6_000L, interval)
        assertTrue(receipt.optBoolean("verified_navigation"))
        assertEquals(1, target.parentActionCalls)
        assertEquals(0, target.focusActionCalls)
        assertEquals(listOf("click"), target.actionSequence)
    }

    @Test fun exactOwnerFocusThenClickRequiresMatchingFocusEventBeforeClick() {
        val target = FakeTarget()
        val activationMode = NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
        val (capability, binding, token) = rig(target, activationMode = activationMode)
        val focusEvent = NavigationFocusEvidence(binding.requestId, binding.ownerCaptureReqId, binding.ownerLeaseId,
            binding.transactionId, binding.serviceInstanceId, binding.connectionId, target.windowId,
            AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED, 1_000L, target.identity)

        val receipt = dispatch(capability, binding, token, target, focusEvent = focusEvent)

        assertTrue(receipt.optBoolean("verified_navigation"))
        assertEquals(activationMode, receipt.optString("activation_mode"))
        assertEquals("EXACT_OWNER_FOCUSED_CURRENT",
            receipt.getJSONObject("activation_diagnostics").optString("focus_event_status"))
        assertEquals(1, target.focusActionCalls)
        assertEquals(1, target.parentActionCalls)
        assertEquals(listOf("focus", "click"), target.actionSequence)
    }

    @Test fun exactFocusProofUsesTypedOwnerMarkBeforeClick() {
        val target = FakeTarget()
        val activationMode = NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
        val (capability, binding, token) = rig(target, activationMode = activationMode)
        val focusEvent = NavigationFocusEvidence(binding.requestId, binding.ownerCaptureReqId, binding.ownerLeaseId,
            binding.transactionId, binding.serviceInstanceId, binding.connectionId, target.windowId,
            AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED, 1_000L, target.identity)
        assertNotEquals(binding.requestId, binding.ownerCaptureReqId)
        var markedProof: NavigationFocusEvidence? = null

        val receipt = dispatch(capability, binding, token, target, focusEvent = focusEvent,
            markOwnerDispatchAfterFocus = { dispatchElapsed, proof ->
                assertEquals(0, target.parentActionCalls)
                assertEquals(listOf("focus"), target.actionSequence)
                assertEquals(1_000L, dispatchElapsed)
                markedProof = proof
                ownerDispatchReceipt(binding, target, target, null, dispatchElapsed)
            })

        assertTrue(receipt.optBoolean("verified_navigation"))
        assertEquals(focusEvent, markedProof)
        assertEquals(binding.requestId, markedProof?.requestId)
        assertEquals(binding.ownerCaptureReqId, markedProof?.ownerCaptureReqId)
        assertEquals(binding.ownerLeaseId, markedProof?.ownerLeaseId)
        assertEquals(listOf("focus", "click"), target.actionSequence)
        assertEquals(1, target.parentActionCalls)
    }

    @Test fun staleOwnerMarkPreservesFirstFailedCurrentnessCheckAndPreventsClick() {
        val target = FakeTarget()
        val activationMode = NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
        val (capability, binding, token) = rig(target, activationMode = activationMode)
        val focusEvent = NavigationFocusEvidence(binding.requestId, binding.ownerCaptureReqId,
            binding.ownerLeaseId, binding.transactionId, binding.serviceInstanceId, binding.connectionId,
            target.windowId, AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED, 1_000L, target.identity)
        assertNotEquals(binding.requestId, binding.ownerCaptureReqId)
        val mark = JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE")
            .put("focus_revalidation", JSONObject().put("diagnostics_available", true)
                .put("first_failed_check", "focus_scoped_full_tree_matches")
                .put("aggregate_accepted", false))

        val result = dispatch(capability, binding, token, target, focusEvent = focusEvent,
            markOwnerDispatchAfterFocus = { _, proof ->
                assertEquals(focusEvent, proof)
                mark
            })

        assertEquals("NAVIGATION_OWNER_DISPATCH_MARK_UNVERIFIED", result.optString("failure_code"))
        assertEquals("ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE",
            result.optString("owner_dispatch_mark_reason"))
        assertEquals("focus_scoped_full_tree_matches",
            result.getJSONObject("owner_dispatch_mark_focus_revalidation")
                .optString("first_failed_check"))
        assertFalse(result.optBoolean("verified_navigation"))
        assertFalse(result.optBoolean("visit_authority"))
        assertFalse(result.optBoolean("c5_credit"))
        assertEquals(listOf("focus"), target.actionSequence)
        assertEquals(0, target.parentActionCalls)
    }

    @Test fun focusProofRequiresTheStoredNavigationAndOwnerBindingBeforeMark() {
        val tamperProof: List<(NavigationFocusEvidence) -> NavigationFocusEvidence> = listOf(
            { it.copy(requestId = "unrelated-navigation-request") },
            { it.copy(ownerCaptureReqId = "unrelated-owner-capture") },
            { it.copy(ownerLeaseId = "unrelated-owner-lease") },
            { it.copy(transactionId = "unrelated-transaction") },
            { it.copy(serviceInstanceId = "unrelated-service") },
            { it.copy(connectionId = "unrelated-connection") },
            { it.copy(windowId = it.windowId + 1) },
            { it.copy(eventElapsedRealtimeMs = 999L) },
        )
        tamperProof.forEach { tamper ->
            val target = FakeTarget()
            val (capability, binding, token) = rig(target,
                activationMode = NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK)
            assertNotEquals(binding.requestId, binding.ownerCaptureReqId)
            val focusEvent = NavigationFocusEvidence(binding.requestId, binding.ownerCaptureReqId,
                binding.ownerLeaseId, binding.transactionId, binding.serviceInstanceId, binding.connectionId,
                target.windowId, AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED, 1_000L, target.identity)
            var typedMarkCalled = false
            val receipt = dispatch(capability, binding, token, target, focusEvent = tamper(focusEvent),
                markOwnerDispatchAfterFocus = { _, _ ->
                    typedMarkCalled = true
                    ownerDispatchReceipt(binding, target, target, null, 1_001L)
                })
            assertFalse(typedMarkCalled)
            assertEquals("NAVIGATION_FOCUS_EVENT_SOURCE_MISMATCH", receipt.optString("failure_code"))
            assertFalse(receipt.optBoolean("verified_navigation"))
            assertFalse(receipt.optBoolean("visit_authority"))
            assertEquals(0, target.parentActionCalls)
            assertEquals(listOf("focus"), target.actionSequence)
        }
    }

    @Test fun focusEventFromDifferentNodeRejectsBeforeClick() {
        val target = FakeTarget()
        val (capability, binding, token) = rig(target,
            activationMode = NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK)
        val focusEvent = NavigationFocusEvidence(binding.requestId, binding.ownerCaptureReqId, binding.ownerLeaseId,
            binding.transactionId, binding.serviceInstanceId, binding.connectionId, target.windowId,
            AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED, 1_000L, Any())

        var typedMarkCalled = false
        val receipt = dispatch(capability, binding, token, target, focusEvent = focusEvent,
            markOwnerDispatchAfterFocus = { _, _ ->
                typedMarkCalled = true
                ownerDispatchReceipt(binding, target, target, null, 1_001L)
            })

        assertFalse(typedMarkCalled)
        assertEquals("NAVIGATION_FOCUS_EVENT_SOURCE_MISMATCH", receipt.optString("failure_code"))
        assertFalse(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertEquals(1, target.focusActionCalls)
        assertEquals(0, target.parentActionCalls)
        assertEquals(listOf("focus"), target.actionSequence)
    }

    @Test fun unrelatedHierarchyChangeAfterFocusRejectsBeforeClick() {
        val target = FakeTarget().apply { currentAfterFocus = false }
        val (capability, binding, token) = rig(target,
            activationMode = NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK)
        val focusEvent = NavigationFocusEvidence(binding.requestId, binding.ownerCaptureReqId, binding.ownerLeaseId,
            binding.transactionId, binding.serviceInstanceId, binding.connectionId, target.windowId,
            AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED, 1_000L, target.identity)

        val receipt = dispatch(capability, binding, token, target, focusEvent = focusEvent)

        assertEquals("NAVIGATION_FOCUSED_TARGET_STALE", receipt.optString("failure_code"))
        assertFalse(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertEquals(1, target.focusActionCalls)
        assertEquals(0, target.parentActionCalls)
        assertEquals(listOf("focus"), target.actionSequence)
    }

    @Test fun failedFocusRevalidationReportsLeafChecksAndRejectsBeforeClick() {
        val target = FakeTarget()
        val leafDiagnostics = JSONObject()
            .put("diagnostics_available", true)
            .put("capture_lease_fresh", true)
            .put("connection_identity_matches", true)
            .put("retained_node_refresh_succeeded", true)
            .put("window_identity_matches", true)
            .put("retained_node_accessibility_focused", true)
            .put("unique_active_window", true)
            .put("root_available", true)
            .put("node_at_path_resolved", true)
            .put("retained_node_identity_matches", true)
            .put("focus_neutral_descriptor_matches", true)
            .put("focus_neutral_hierarchy_digest_matches", false)
            .put("capture_complete", true)
            .put("first_failed_check", "focus_neutral_hierarchy_digest_matches")
            .put("aggregate_accepted", false)
        target.focusRevalidationResult = NavigationFocusRevalidationResult(false, leafDiagnostics)
        val (capability, binding, token) = rig(target,
            activationMode = NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK)
        val focusEvent = NavigationFocusEvidence(binding.requestId, binding.ownerCaptureReqId, binding.ownerLeaseId,
            binding.transactionId, binding.serviceInstanceId, binding.connectionId, target.windowId,
            AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED, 1_000L, target.identity)

        val receipt = dispatch(capability, binding, token, target, focusEvent = focusEvent)

        assertEquals("NAVIGATION_FOCUSED_TARGET_STALE", receipt.optString("failure_code"))
        assertFalse(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        val diagnostics = receipt.getJSONObject("activation_diagnostics")
        val revalidation = diagnostics.getJSONObject("focus_revalidation")
        assertTrue(revalidation.optBoolean("prepared_deadline_valid"))
        assertTrue(revalidation.optBoolean("service_identity_matches"))
        assertTrue(revalidation.optBoolean("connection_identity_matches"))
        assertTrue(revalidation.optBoolean("window_identity_matches"))
        assertTrue(revalidation.optBoolean("focus_event_owner_matches"))
        val currentness = revalidation.getJSONObject("target_currentness")
        assertEquals("focus_neutral_hierarchy_digest_matches", currentness.optString("first_failed_check"))
        assertFalse(currentness.optBoolean("focus_neutral_hierarchy_digest_matches"))
        assertFalse(currentness.optBoolean("aggregate_accepted"))
        assertEquals(1, target.focusActionCalls)
        assertEquals(0, target.parentActionCalls)
        assertEquals(listOf("focus"), target.actionSequence)
    }

    @Test fun strictReceiptEmbedsBoundedRedactedExactPostCaptureSampleWithoutGrantingAuthority() {
        val target = FakeTarget()
        val contract = contract()
        val (capability, binding, token) = rig(target, contract)
        val child = CapturedHierarchyNode(
            stableIndex = 1, childIndex = 0, text = "Navigate up", contentDescription = "private description",
            resourceId = "com.example.app:id/nav_up", className = "android.widget.Button",
            packageName = "com.example.app", sourceNodeId = "private-node-id", windowId = target.windowId,
            bounds = CapturedBounds(10, 20, 30, 40), clickable = true, enabled = true, focusable = true,
            focused = false, accessibilityFocused = false, selected = false, scrollable = false,
            checkable = false, checked = false, visibleToUser = true, screenReaderFocusable = null,
            rangeInfoPresent = false,
            actions = listOf(CapturedHierarchyAction(16, "ACTION_CLICK", "private action label")),
            children = emptyList(),
        )
        val root = CapturedHierarchyNode(
            stableIndex = 0, childIndex = null, text = "Dashboard", contentDescription = "private root text",
            resourceId = "com.example.app:id/root", className = "android.widget.FrameLayout",
            packageName = "com.example.app", sourceNodeId = "private-root-id", windowId = target.windowId,
            bounds = CapturedBounds(0, 0, 100, 100), clickable = false, enabled = true, focusable = false,
            focused = false, accessibilityFocused = false, selected = false, scrollable = false,
            checkable = false, checked = false, visibleToUser = true, screenReaderFocusable = null,
            rangeInfoPresent = false, actions = emptyList(), children = listOf(child),
        )
        val capture = ImmutableHierarchyCapture(root, nodeCount = 2)
        val sample = NavigationPostCaptureArtifact.fromCapture(
            capture, binding.requestId, binding.transactionId, binding.serviceInstanceId,
            binding.connectionId, target.windowId, "strict-post-capture-id", 1_002L,
            "c".repeat(64), contract,
        )
        val post = NavigationPostActionEvidence(
            binding.requestId, binding.transactionId, binding.serviceInstanceId, binding.connectionId,
            target.windowId, "strict-post-capture-id", 1_002L, "c".repeat(64),
            listOf("Dashboard", "Navigate up"), focusWindowId = null,
            accessibilityFocused = false, focusInCurrentHierarchy = false,
            nodeCount = capture.nodeCount, rootPackageName = root.packageName,
            rootClassName = root.className, captureSample = sample,
        )

        val receipt = dispatch(capability, binding, token, target, post)
        val diagnostics = receipt.getJSONObject("post_state_diagnostics")
        val artifact = diagnostics.getJSONObject("post_capture_sample_artifact")
        val payload = artifact.getJSONObject("payload")
        val nodes = payload.getJSONArray("nodes")
        val persistedChild = nodes.getJSONObject(1)

        assertEquals("NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE", receipt.optString("failure_code"))
        assertFalse(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertFalse(receipt.optBoolean("c5_credit"))
        assertEquals("REJECTED", diagnostics.optString("receipt_decision"))
        assertEquals("EMBEDDED_COMPLETE", diagnostics.optString("post_capture_sample_persistence_status"))
        assertEquals("NAVIGATION_ACTION_RESULT", artifact.optString("result_channel"))
        assertEquals(binding.requestId, artifact.optString("request_id"))
        assertEquals("receipt.post_state_diagnostics.post_capture_sample_artifact.payload",
            artifact.optString("receipt_field"))
        assertEquals("COMPLETE", artifact.optString("completeness"))
        assertEquals(2, artifact.optInt("node_count"))
        assertEquals(2, artifact.optInt("persisted_node_count"))
        assertEquals(sample.sha256, artifact.optString("artifact_sha256"))
        assertEquals(sample.byteCount, artifact.optInt("artifact_bytes"))
        assertEquals(ExactProtocolJson.sha256(ExactProtocolJson.canonical(payload)), artifact.optString("artifact_sha256"))
        assertEquals(binding.requestId, payload.optString("request_id"))
        assertEquals(binding.transactionId, payload.optString("transaction_id"))
        assertEquals(binding.serviceInstanceId, payload.optString("service_instance_id"))
        assertEquals(binding.connectionId, payload.optString("connection_id"))
        assertEquals(target.windowId, payload.optInt("window_id"))
        assertEquals(post.captureId, payload.optString("capture_id"))
        assertEquals(post.capturedAtUptimeMs, payload.optLong("captured_at_elapsed_realtime_ms"))
        assertEquals(post.hierarchyDigest, payload.optString("hierarchy_digest"))
        assertEquals(post.hierarchyDigest, diagnostics.optString("post_hierarchy_digest"))
        assertEquals(0, nodes.getJSONObject(0).optInt("id"))
        assertTrue(nodes.getJSONObject(0).isNull("parent_id"))
        assertEquals(1, persistedChild.optInt("id"))
        assertEquals(0, persistedChild.optInt("parent_id"))
        assertEquals(0, persistedChild.optInt("child_index"))
        assertEquals("android.widget.Button", persistedChild.optString("class_name"))
        assertEquals("com.example.app:id/nav_up", persistedChild.optString("resource_id"))
        assertEquals(0, persistedChild.getJSONArray("path").optInt(0))
        assertTrue(persistedChild.optBoolean("clickable"))
        assertTrue(persistedChild.optBoolean("text_present"))
        assertTrue(persistedChild.optBoolean("content_description_present"))
        assertEquals(16, persistedChild.getJSONArray("action_ids").optInt(0))
        assertTrue(nodes.getJSONObject(0).optBoolean("destination_label_match"))
        assertTrue(nodes.getJSONObject(0).getJSONArray("diagnostic_policy_match_ids").toString()
            .contains("destination_label"))
        assertFalse(persistedChild.optBoolean("destination_label_match"))
        assertEquals(1, persistedChild.optInt("required_anchor_match_count"))
        assertTrue(persistedChild.getJSONArray("diagnostic_policy_match_ids").toString()
            .contains("required_anchor_label"))
        assertTrue(payload.optBoolean("diagnostic_only"))
        assertEquals(contract.id, payload.optString("effect_contract_id"))
        assertTrue(payload.getJSONArray("omitted_fields").toString().contains("contentDescription"))
        assertFalse(nodes.getJSONObject(0).has("text"))
        assertFalse(nodes.getJSONObject(1).has("contentDescription"))
        assertFalse(nodes.getJSONObject(1).has("sourceNodeId"))
        assertFalse(payload.toString().contains("private description"))
        assertFalse(payload.toString().contains("private action label"))
        assertFalse(payload.toString().contains("private-node-id"))
        assertEquals(1, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)
    }

    @Test fun strictPostDiagnosticKeepsPolicyTitleAndDoesNotInferAckMeaningFromResourceId() {
        val target = FakeTarget()
        val binding = binding(target, contract())
        val base = contract()
        val signature = NavigationEmptyStateSignature(
            exactText = "Configured empty state title",
            rootClassName = "android.widget.FrameLayout",
            containerClassName = "android.view.View",
            containerResourceId = "paneContainer",
            webViewClassName = "android.webkit.WebView",
            anchorClassName = "android.widget.Button",
            anchorResourceId = "ack",
            excludedClassName = "android.widget.GridView",
        )
        val policyDigest = NavigationEffectContract.digestFor(
            id = base.id, effect = base.effect, packageName = base.packageName,
            targetClassPattern = base.targetClassPattern, targetResourcePattern = base.targetResourcePattern,
            targetLabelPattern = base.targetLabelPattern, targetSubtreePattern = base.targetSubtreePattern,
            destinationPattern = base.destinationPattern, requiredAnchorPattern = base.requiredAnchorPattern,
            returnTransport = base.returnTransport, expectedDescendantCount = base.expectedDescendantCount,
            excludedDescendantResourceIds = base.excludedDescendantResourceIds,
            requiredNonActionableDescendantLabelPatterns = base.requiredNonActionableDescendantLabelPatterns,
            allowedScenarioIds = base.allowedScenarioIds, evidenceRefs = base.evidenceRefs,
            sourceEvidenceDigest = base.sourceEvidenceDigest, activationOwnerRelation = base.activationOwnerRelation,
            emptyStateSignature = signature,
        )
        val policy = base.copy(digest = policyDigest, emptyStateSignature = signature)
        val ackCandidate = CapturedHierarchyNode(
            stableIndex = 1, childIndex = 0, text = null, contentDescription = "private ack meaning",
            resourceId = "ack", className = "android.widget.Button", packageName = "com.example.app",
            sourceNodeId = "private-node-id", windowId = target.windowId,
            bounds = CapturedBounds(10, 20, 30, 40), clickable = true, enabled = true, focusable = true,
            focused = true, accessibilityFocused = true, selected = false, scrollable = false,
            checkable = false, checked = false, visibleToUser = true, screenReaderFocusable = null,
            rangeInfoPresent = false,
            actions = listOf(CapturedHierarchyAction(AccessibilityNodeInfo.ACTION_CLICK, "ACTION_CLICK", "private action label")),
            children = emptyList(),
        )
        val semanticAnchor = ackCandidate.copy(
            stableIndex = 2, childIndex = 1, text = "Navigate up", contentDescription = "private description",
        )
        val root = CapturedHierarchyNode(
            stableIndex = 0, childIndex = null, text = "Configured empty state title", contentDescription = null,
            resourceId = "com.example.app:id/root", className = "android.widget.FrameLayout",
            packageName = "com.example.app", sourceNodeId = "private-root-id", windowId = target.windowId,
            bounds = CapturedBounds(0, 0, 100, 100), clickable = false, enabled = true, focusable = false,
            focused = false, accessibilityFocused = false, selected = false, scrollable = false,
            checkable = false, checked = false, visibleToUser = true, screenReaderFocusable = null,
            rangeInfoPresent = false, actions = emptyList(), children = listOf(ackCandidate, semanticAnchor),
        )
        val capture = ImmutableHierarchyCapture(root, nodeCount = 3)
        val sample = NavigationPostCaptureArtifact.fromCapture(
            capture, binding.requestId, binding.transactionId, binding.serviceInstanceId,
            binding.connectionId, target.windowId, "ack-post-capture", 1_002L, "f".repeat(64), policy,
        )
        val payload = sample.payload
        val nodes = payload.getJSONArray("nodes")
        val rootSummary = nodes.getJSONObject(0)
        val anchorSummary = nodes.getJSONObject(1)
        val semanticAnchorSummary = nodes.getJSONObject(2)

        assertTrue(rootSummary.getJSONArray("diagnostic_policy_match_ids").toString()
            .contains("empty_state_exact_text"))
        assertEquals("UNKNOWN", anchorSummary.optString("diagnostic_anchor_semantic_status"))
        assertTrue(anchorSummary.getJSONArray("diagnostic_policy_match_ids").toString()
            .contains("empty_state_anchor_candidate"))
        assertFalse(anchorSummary.getJSONArray("diagnostic_policy_match_ids").toString()
            .contains("empty_state_anchor_semantic_click_target"))
        assertEquals("ack", anchorSummary.optString("resource_id"))
        assertEquals("android.widget.Button", anchorSummary.optString("class_name"))
        assertEquals(0, anchorSummary.getJSONArray("path").optInt(0))
        assertTrue(anchorSummary.optBoolean("focused"))
        assertTrue(anchorSummary.optBoolean("accessibility_focused"))
        assertTrue(anchorSummary.optBoolean("clickable"))
        assertEquals(AccessibilityNodeInfo.ACTION_CLICK,
            anchorSummary.getJSONArray("action_ids").optInt(0))
        assertEquals("POLICY_LABEL_MATCH", semanticAnchorSummary.optString("diagnostic_anchor_semantic_status"))
        assertTrue(semanticAnchorSummary.getJSONArray("diagnostic_policy_match_ids").toString()
            .contains("required_anchor_label"))
        assertTrue(semanticAnchorSummary.getJSONArray("diagnostic_policy_match_ids").toString()
            .contains("empty_state_anchor_semantic_click_target"))
        assertEquals(1, semanticAnchorSummary.getJSONArray("path").optInt(0))
        assertFalse(payload.toString().contains("Configured empty state title"))
        assertFalse(payload.toString().contains("private ack meaning"))
        assertFalse(payload.toString().contains("private action label"))
        assertEquals(binding.requestId, payload.optString("request_id"))
        assertEquals(binding.transactionId, payload.optString("transaction_id"))
        assertEquals(binding.serviceInstanceId, payload.optString("service_instance_id"))
        assertEquals(binding.connectionId, payload.optString("connection_id"))
        assertEquals(target.windowId, payload.optInt("window_id"))
        assertEquals("ack-post-capture", payload.optString("capture_id"))
        assertEquals("f".repeat(64), payload.optString("hierarchy_digest"))
        assertEquals(ExactProtocolJson.sha256(ExactProtocolJson.canonical(payload)), sample.sha256)
    }

    @Test fun strictPostCaptureArtifactReportsSizeTruncationAsIncomplete() {
        val target = FakeTarget()
        val contract = contract()
        val (capability, binding, token) = rig(target, contract)
        val children = (1..256).map { index ->
            CapturedHierarchyNode(
                stableIndex = index, childIndex = index - 1, text = null, contentDescription = null,
                resourceId = "com.example.app:id/node_$index", className = "android.view.View",
                packageName = "com.example.app", sourceNodeId = null, windowId = target.windowId,
                bounds = CapturedBounds(index, index, index + 1, index + 1), clickable = false,
                enabled = true, focusable = false, focused = false, accessibilityFocused = false,
                selected = false, scrollable = false, checkable = false, checked = false,
                visibleToUser = true, screenReaderFocusable = null, rangeInfoPresent = false,
                actions = emptyList(), children = emptyList(),
            )
        }
        val root = CapturedHierarchyNode(
            stableIndex = 0, childIndex = null, text = null, contentDescription = null,
            resourceId = "com.example.app:id/root", className = "android.widget.FrameLayout",
            packageName = "com.example.app", sourceNodeId = null, windowId = target.windowId,
            bounds = CapturedBounds(0, 0, 1000, 1000), clickable = false, enabled = true,
            focusable = false, focused = false, accessibilityFocused = false, selected = false,
            scrollable = false, checkable = false, checked = false, visibleToUser = true,
            screenReaderFocusable = null, rangeInfoPresent = false, actions = emptyList(), children = children,
        )
        val capture = ImmutableHierarchyCapture(root, nodeCount = children.size + 1)
        val sample = NavigationPostCaptureArtifact.fromCapture(
            capture, binding.requestId, binding.transactionId, binding.serviceInstanceId,
            binding.connectionId, target.windowId, "post-cap", 1_002L, "d".repeat(64), contract,
        )
        val receipt = dispatch(capability, binding, token, target,
            NavigationPostActionEvidence(binding.requestId, binding.transactionId, binding.serviceInstanceId,
                binding.connectionId, target.windowId, "post-cap", 1_002L, "d".repeat(64),
                listOf("Dashboard", "Navigate up"), target.windowId, true, true,
                capture.nodeCount, root.packageName, root.className, sample))
        val artifact = receipt.getJSONObject("post_state_diagnostics").getJSONObject("post_capture_sample_artifact")

        assertTrue(receipt.optBoolean("verified_navigation"))
        assertEquals("INCOMPLETE_SIZE_LIMIT", artifact.optString("completeness"))
        assertEquals(capture.nodeCount, artifact.optInt("node_count"))
        assertTrue(artifact.optInt("persisted_node_count") < capture.nodeCount)
        assertTrue(artifact.optInt("artifact_bytes") <= 48 * 1024)
        assertEquals(artifact.optInt("persisted_node_count"), artifact.getJSONObject("payload")
            .getJSONArray("nodes").length())
    }

    @Test fun postActionWindowStartsAtExactClickAfterCollectorArmingAndKeepsStrictGates() {
        val target = FakeTarget()
        val contract = contract()
        var now = 1_000L
        val capability = NavigationActionCapability(mapOf(contract.id to contract), { now })
        val binding = binding(target, contract)
        val prepared = capability.prepare(binding, target, "service-1", target.connectionId)
        assertEquals("PREPARED", prepared.optString("status"))
        var interval: Pair<Long, Long>? = null

        val receipt = capability.dispatch(
            prepared.getString("lease_token"), binding, "service-1", target.connectionId,
            armCollector = { bound, leased ->
                assertEquals(binding, bound)
                assertSame(target, leased)
                now = 1_400L // Pre-dispatch setup must not consume the 5-second post-action window.
                true
            },
            awaitClick = { deadline ->
                assertEquals(6_400L, deadline)
                NavigationClickEvidence(binding.requestId, binding.transactionId,
                    binding.serviceInstanceId, binding.connectionId, target.windowId,
                    AccessibilityEvent.TYPE_VIEW_CLICKED, 1_401L, target.identity)
            },
            markOwnerDispatch = { dispatchElapsed -> ownerDispatchReceipt(binding, target, target, null,
                dispatchElapsed) },
            confirmOwnerDispatch = { dispatchElapsed -> ownerConfirmedClickReceipt(binding, target, target,
                null, dispatchElapsed, clickEventElapsedRealtimeMs = 1_401L) },
            capturePostAction = { deadline, _ ->
                assertEquals(6_400L, deadline)
                now = deadline
                NavigationPostActionEvidence(binding.requestId, binding.transactionId,
                    binding.serviceInstanceId, binding.connectionId, target.windowId, "post-capture",
                    deadline, "c".repeat(64), listOf("Dashboard", "Navigate up"),
                    target.windowId, true, true)
            },
            markActionDispatch = { start, deadline -> interval = start to deadline },
        )

        assertEquals(1_400L to 6_400L, interval)
        assertTrue(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertFalse(receipt.optBoolean("c5_credit"))
        assertEquals(1, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)
        val diagnostics = receipt.getJSONObject("post_state_diagnostics")
        assertEquals(1_400L, diagnostics.getLong("dispatch_elapsed_realtime_ms"))
        assertEquals(6_400L, diagnostics.getLong("dispatch_deadline_elapsed_realtime_ms"))
        assertEquals(1_400L, diagnostics.getLong("capture_call_start_elapsed_realtime_ms"))
        assertEquals(6_400L, diagnostics.getLong("capture_call_completion_elapsed_realtime_ms"))
        assertEquals(6_400L, diagnostics.getLong("post_state_evaluation_elapsed_realtime_ms"))
        assertEquals(6_400L, diagnostics.getLong("receipt_decision_elapsed_realtime_ms"))
        assertEquals(binding.requestId, diagnostics.getString("request_id"))
        assertEquals(binding.transactionId, diagnostics.getString("transaction_id"))
        assertEquals(binding.sourceIdentity.requestId, diagnostics.getString("source_capture_request_id"))
        assertEquals(binding.sourceIdentity.captureKey, diagnostics.getString("source_capture_key"))
        assertEquals(binding.sourceIdentity.generation, diagnostics.getLong("source_capture_generation"))
        assertEquals(binding.sourceIdentity.captureSequence, diagnostics.getLong("source_capture_sequence"))
        assertEquals(binding.serviceInstanceId, diagnostics.getString("action_service_instance_id"))
        assertEquals(binding.connectionId, diagnostics.getString("action_connection_id"))
        assertEquals(binding.windowId, diagnostics.getInt("action_window_id"))
        assertEquals("service-1", diagnostics.getString("capture_service_instance_id"))
        assertEquals("connection-1", diagnostics.getString("capture_connection_id"))
        assertEquals(target.windowId, diagnostics.getInt("capture_window_id"))
        assertEquals("RETURNED", diagnostics.getString("capture_call_result"))
        assertEquals("VERIFIED_NAVIGATION", diagnostics.getString("receipt_decision"))
        assertTrue(diagnostics.getBoolean("required_destination_match"))
        assertEquals(1, diagnostics.getInt("required_anchor_match_count"))
        assertEquals("MATCHED", diagnostics.getString("required_anchor_outcome"))
        assertEquals(0, diagnostics.getJSONArray("failure_stages").length())
    }

    @Test fun exactRetainedParentDispatchDoesNotInvokeIndependentChild() {
        val target = FakeTarget(independentDescendants = 1)
        val (capability, binding, token) = rig(target)
        val receipt = dispatch(capability, binding, token, target)
        assertTrue(receipt.getBoolean("verified_navigation"))
        assertFalse(receipt.getBoolean("visit_authority"))
        assertFalse(receipt.getBoolean("c5_credit"))
        assertEquals(1, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)
    }

    @Test fun missingStrictPostCaptureEmitsDiagnosticsAndRemainsRejected() {
        val target = FakeTarget()
        val (capability, binding, token) = rig(target)
        val receipt = dispatch(capability, binding, token, target, captureMissing = true)

        assertEquals("REJECTED", receipt.optString("status"))
        assertEquals("NAVIGATION_POST_CAPTURE_MISSING", receipt.optString("failure_code"))
        assertFalse(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertFalse(receipt.optBoolean("c5_credit"))
        assertEquals(1, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)
        val diagnostics = receipt.getJSONObject("post_state_diagnostics")
        assertEquals("MISSING", diagnostics.getString("capture_call_result"))
        assertEquals(binding.requestId, diagnostics.getString("request_id"))
        assertEquals(binding.transactionId, diagnostics.getString("transaction_id"))
        assertEquals(1_000L, diagnostics.getLong("capture_call_start_elapsed_realtime_ms"))
        assertEquals(1_000L, diagnostics.getLong("capture_call_completion_elapsed_realtime_ms"))
        assertTrue(diagnostics.isNull("capture_service_instance_id"))
        assertTrue(diagnostics.isNull("capture_connection_id"))
        assertTrue(diagnostics.isNull("capture_window_id"))
        assertEquals("NOT_EVALUATED_CAPTURE_MISSING", diagnostics.getString("required_anchor_outcome"))
        assertEquals("NAVIGATION_POST_CAPTURE_MISSING", diagnostics.getString("receipt_failure_code"))
        assertEquals("post_capture_missing", diagnostics.getJSONArray("failure_stages").getString(0))
        assertEquals("NO_COMPLETE_SAMPLE", diagnostics.getString("post_capture_completeness"))
        assertEquals("post_capture_missing", diagnostics.getString("post_capture_failure_stage"))
        assertTrue(diagnostics.isNull("post_capture_node_count"))
        assertTrue(diagnostics.isNull("post_capture_root_package"))
        assertTrue(diagnostics.isNull("post_capture_root_class"))
    }

    @Test fun exactRetainedParentCanUseDescriptorLeaseWhenSourceIdIsExplicitlyAbsent() {
        val target = FakeTarget(independentDescendants = 1)
        val contract = contract()
        val capability = NavigationActionCapability(mapOf(contract.id to contract), { 1_000L })
        val binding = binding(target, contract).copy(sourceIdentity = binding(target, contract).sourceIdentity.copy(
            ownerSourceNodeId = "", ownerSourceNodeIdStatus = "FIELD_ABSENT"))
        val prepared = capability.prepare(binding, target, "service-1", target.connectionId)
        assertEquals("PREPARED", prepared.optString("status"))
        val receipt = dispatch(capability, binding, prepared.getString("lease_token"), target)
        assertTrue(receipt.getBoolean("verified_navigation"))
        assertEquals(1, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)
        assertEquals("FIELD_ABSENT", receipt.getJSONObject("source_identity").optString("owner_source_node_id_status"))
    }

    @Test fun absentSourceIdRequiresExplicitStatusAndNeverAcceptsContradictoryIdentity() {
        val target = FakeTarget()
        val contract = contract()
        val capability = NavigationActionCapability(mapOf(contract.id to contract), { 1_000L })
        val binding = binding(target, contract).copy(sourceIdentity = binding(target, contract).sourceIdentity.copy(
            ownerSourceNodeId = "", ownerSourceNodeIdStatus = "FIELD_PRESENT"))
        val prepared = capability.prepare(binding, target, "service-1", target.connectionId)
        assertEquals("REJECTED", prepared.optString("status"))
        assertEquals("NAVIGATION_BINDING_MISMATCH", prepared.optString("failure_code"))
        assertEquals(0, target.parentActionCalls)
    }

    @Test fun onlyExplicitlyAllowlistedActionCanPrepareDispatch() {
        val target = FakeTarget()
        val contract = contract()
        val capability = NavigationActionCapability(mapOf(contract.id to contract), { 1_000L })
        val unallowlisted = binding(target, contract).copy(action = "ACTION_LONG_CLICK")
        val prepared = capability.prepare(unallowlisted, target, "service-1", target.connectionId)
        assertEquals("REJECTED", prepared.optString("status"))
        assertEquals("NAVIGATION_BINDING_MISMATCH", prepared.optString("failure_code"))
        assertEquals(0, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)
    }

    @Test fun packagedAirCareContractAllowsOnlyExactParentAndExpectedNonActionableLabels() {
        val policyBytes = RuntimeEnvironment.getApplication().resources
            .openRawResource(R.raw.safe_navigation_contracts).use { it.readBytes() }
        val contracts = NavigationEffectContractRegistry.load(policyBytes)
        assertEquals(setOf("life_service_card_read_only_navigation", "life_plugin_navigate_up_to_landing"), contracts.keys)
        val route = contracts.getValue("life_service_card_read_only_navigation")
        assertTrue(route.isWellFormed(route.digest))
        assertTrue(route.allowsScenario("life_air_care_plugin"))
        assertFalse(route.allowsScenario("another_scenario"))

        val frameId = "com.samsung.android.oneconnect:id/frameLayout"
        val includeId = "com.samsung.android.oneconnect:id/include"
        val airCareTarget = FakeTarget(
            packageName = "com.samsung.android.oneconnect",
            className = "android.widget.RelativeLayout",
            resourceId = "",
            label = "",
            subtreeLabels = listOf("llCard", "에어 케어", "공기청정기나 에어컨을 추가해서 우리 집 공기를 실외 공기처럼 깨끗하게 유지해 보세요.",
                "include", "보통", "야외"),
            descendants = listOf(
                NavigationDescendantEvidence("android.widget.FrameLayout", frameId, "", true, true,
                    false, false, false, setOf(16, 32)),
                NavigationDescendantEvidence("android.widget.LinearLayout", "com.samsung.android.oneconnect:id/llCard",
                    "에어 케어", false, false, false, false, false, emptySet()),
                NavigationDescendantEvidence("android.widget.TextView", "com.samsung.android.oneconnect:id/tvHeaderTitle",
                    "공기청정기나 에어컨을 추가해서 우리 집 공기를 실외 공기처럼 깨끗하게 유지해 보세요.",
                    false, false, false, false, false, emptySet()),
                NavigationDescendantEvidence("android.widget.LinearLayout", includeId, "보통 야외", true,
                    false, false, false, false, setOf(16)),
                NavigationDescendantEvidence("android.widget.ImageView", "", "사진", false, false,
                    false, false, false, emptySet()),
                NavigationDescendantEvidence("android.widget.TextView", "com.samsung.android.oneconnect:id/textView",
                    "보통", false, false, false, false, false, emptySet()),
                NavigationDescendantEvidence("android.widget.TextView", "com.samsung.android.oneconnect:id/textView2",
                    "야외", false, false, false, false, false, emptySet()),
            ),
        )
        assertTrue(route.matches(airCareTarget))

        val observedPoorStatus = FakeTarget(
            packageName = airCareTarget.packageName,
            className = airCareTarget.className,
            resourceId = airCareTarget.resourceId,
            label = airCareTarget.label,
            subtreeLabels = airCareTarget.subtreeLabels.map { if (it == "보통") "나쁨" else it },
            descendants = airCareTarget.descendantEvidence().map { if (it.label == "보통") it.copy(label = "나쁨") else it },
        )
        assertTrue("the observed air-quality grade is a display value, not card identity", route.matches(observedPoorStatus))
        val unobservedStatus = FakeTarget(
            packageName = airCareTarget.packageName,
            className = airCareTarget.className,
            resourceId = airCareTarget.resourceId,
            label = airCareTarget.label,
            subtreeLabels = airCareTarget.subtreeLabels.map { if (it == "보통") "좋음" else it },
            descendants = airCareTarget.descendantEvidence().map { if (it.label == "보통") it.copy(label = "좋음") else it },
        )
        assertFalse("unobserved status variants stay fail-closed", route.matches(unobservedStatus))

        val frameChild = FakeTarget(packageName = "com.samsung.android.oneconnect",
            className = "android.widget.FrameLayout", resourceId = frameId, label = "",
            subtreeLabels = airCareTarget.subtreeLabels)
        assertFalse("FrameLayout must never be promoted to target", route.matches(frameChild))
        val includeChild = FakeTarget(packageName = "com.samsung.android.oneconnect",
            className = "android.widget.LinearLayout", resourceId = includeId, label = "보통 야외",
            subtreeLabels = listOf("보통", "야외"))
        assertFalse("Normal/Outdoor control must never be selected", route.matches(includeChild))

        val unexpectedActionableChild = FakeTarget(
            packageName = airCareTarget.packageName,
            className = airCareTarget.className,
            resourceId = airCareTarget.resourceId,
            label = airCareTarget.label,
            subtreeLabels = airCareTarget.subtreeLabels,
            descendants = airCareTarget.descendantEvidence() + NavigationDescendantEvidence(
                "android.widget.Button", "com.samsung.android.oneconnect:id/new_action", "New action",
                true, false, false, false, false, setOf(16)),
        )
        assertFalse("Any extra actionable descendant must close the policy", route.matches(unexpectedActionableChild))

        val changedLabel = FakeTarget(
            packageName = airCareTarget.packageName,
            className = airCareTarget.className,
            resourceId = airCareTarget.resourceId,
            label = airCareTarget.label,
            subtreeLabels = airCareTarget.subtreeLabels,
            descendants = airCareTarget.descendantEvidence().map {
                if (it.label == "야외") it.copy(clickable = true, actionIds = setOf(16)) else it
            },
        )
        assertFalse("Normal/Outdoor label becoming actionable must close the policy", route.matches(changedLabel))

        val navigateUp = contracts.getValue("life_plugin_navigate_up_to_landing")
        assertTrue(navigateUp.isWellFormed(navigateUp.digest))
        assertTrue(navigateUp.allowsScenario("life_air_care_plugin"))
        assertEquals(0, navigateUp.expectedDescendantCount)
        assertTrue(navigateUp.excludedDescendantResourceIds.isEmpty())
        assertTrue(navigateUp.requiredNonActionableDescendantLabelPatterns.isEmpty())

        assertTrue(route.destinationMatches(listOf("에어 케어")))
        assertFalse(route.destinationMatches(listOf("실외 공기질 보통")))

        val setupSentence = "방에 에어컨이나 공기청정기를 추가하여 방 안의 공기를 자동으로 관리해 보세요."
        var postCaptureIndex = 0
        fun receiptFor(labels: List<String>, focused: Boolean): JSONObject {
            val actionTarget = FakeTarget(
                packageName = airCareTarget.packageName,
                className = "android.widget.FrameLayout",
                resourceId = frameId,
                label = "",
                windowId = airCareTarget.windowId,
                nodePath = airCareTarget.nodePath + 0,
                descriptorDigest = "e".repeat(64),
                sourceSnapshotId = airCareTarget.sourceSnapshotId,
                helperSnapshotId = airCareTarget.helperSnapshotId,
                baselineHierarchyDigest = airCareTarget.baselineHierarchyDigest,
                connectionId = airCareTarget.connectionId,
                independentDescendants = 0,
                independentSiblings = 0,
                subtreeLabels = emptyList(),
                descendants = emptyList(),
            )
            airCareTarget.activationChild = actionTarget
            val actionBinding = binding(actionTarget, route).copy(scenarioId = "life_air_care_plugin")
            val capability = NavigationActionCapability(mapOf(route.id to route), { 1_000L })
            val prepared = capability.prepare(actionBinding, actionTarget, "service-1", actionTarget.connectionId,
                activationOwnerTarget = airCareTarget)
            assertEquals("PREPARED", prepared.optString("status"))
            val post = NavigationPostActionEvidence(
                requestId = actionBinding.requestId,
                transactionId = actionBinding.transactionId,
                serviceInstanceId = actionBinding.serviceInstanceId,
                connectionId = actionBinding.connectionId,
                windowId = airCareTarget.windowId,
                captureId = "korean-post-${postCaptureIndex++}",
                capturedAtUptimeMs = 1_002L,
                hierarchyDigest = "c".repeat(64),
                labels = labels,
                focusWindowId = airCareTarget.windowId,
                accessibilityFocused = focused,
                focusInCurrentHierarchy = focused,
                rootPackageName = airCareTarget.packageName,
                rootClassName = "android.widget.FrameLayout",
                structureEvidence = NavigationPostStructureEvidence(
                    exactTextCount = labels.count { it == setupSentence },
                    exactTextWithinWebView = labels.count { it == setupSentence } == 1,
                    containerCount = 1,
                    containerWithinWebView = false,
                    webViewCount = 2,
                    exactBackAnchorCount = labels.count { it == "상위 메뉴로 이동" },
                    excludedClassPresent = false,
                    anchorPath = if (labels.count { it == "상위 메뉴로 이동" } == 1)
                        listOf(0, 0, 0) else emptyList(),
                ),
            )
            return capability.dispatch(
                prepared.getString("lease_token"), actionBinding, "service-1", actionTarget.connectionId,
                armCollector = { bound, leased -> bound == actionBinding && leased === actionTarget },
                awaitClick = { NavigationClickEvidence(
                    actionBinding.requestId, actionBinding.transactionId, actionBinding.serviceInstanceId,
                    actionBinding.connectionId, actionBinding.windowId, AccessibilityEvent.TYPE_VIEW_CLICKED,
                    1_001L, actionTarget.identity,
                ) },
                markOwnerDispatch = { dispatchElapsed -> ownerDispatchReceipt(
                    actionBinding, actionTarget, airCareTarget, route.activationOwnerRelation, dispatchElapsed,
                ) },
                confirmOwnerDispatch = { dispatchElapsed -> ownerConfirmedClickReceipt(
                    actionBinding, actionTarget, airCareTarget, route.activationOwnerRelation, dispatchElapsed,
                ) },
                capturePostAction = { _, _ -> post },
                currentServiceStillBound = { true },
            )
        }

        val verifiedKoreanDestination = receiptFor(
            listOf(setupSentence, "에어 케어", "상위 메뉴로 이동"), focused = true)
        assertTrue(verifiedKoreanDestination.optBoolean("verified_navigation"))
        assertFalse(verifiedKoreanDestination.optBoolean("visit_authority"))
        assertFalse(verifiedKoreanDestination.optBoolean("c5_credit"))

        val lifeCardOnly = receiptFor(
            listOf("Life", "에어 케어", "실외 공기질 보통", "상위 메뉴로 이동"), focused = true)
        assertEquals("NAVIGATION_DESTINATION_FOCUS_ANCHOR_UNPROVEN",
            lifeCardOnly.optString("failure_code"))
        assertFalse(lifeCardOnly.optBoolean("verified_navigation"))

        val titleWithAnchorButMissingFocus = receiptFor(
            listOf(setupSentence, "에어 케어", "상위 메뉴로 이동"), focused = false)
        assertEquals("NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
            titleWithAnchorButMissingFocus.optString("failure_code"))
        assertTrue(titleWithAnchorButMissingFocus.getJSONArray("post_state_mismatch_fields")
            .toString().contains("accessibility_focus_missing"))
        assertFalse(titleWithAnchorButMissingFocus.optBoolean("verified_navigation"))
        assertFalse(titleWithAnchorButMissingFocus.optBoolean("visit_authority"))
        assertFalse(titleWithAnchorButMissingFocus.optBoolean("c5_credit"))
    }

    @Test fun recoveryAnchorCountsOnlyUniqueConfiguredLifeTabStructureInCompleteCapture() {
        val contracts = NavigationEffectContractRegistry.load(RuntimeEnvironment.getApplication().resources
            .openRawResource(R.raw.safe_navigation_contracts).use { it.readBytes() })
        val recovery = contracts.getValue("life_plugin_navigate_up_to_landing")
        val structure = recovery.requiredAnchorStructure!!
        val packageName = recovery.packageName
        val windowId = 1820
        val bottomNavigationId = "com.samsung.android.oneconnect:id/bottom_navigation"
        val titleId = "com.samsung.android.oneconnect:id/title"

        fun sample(
            candidateLabel: String? = "라이프",
            childLabel: String? = "라이프",
            bodyLabel: String? = "라이프",
            candidateClass: String? = "android.widget.LinearLayout",
            parentClass: String? = "android.widget.HorizontalScrollView",
            parentResourceId: String? = bottomNavigationId,
            candidateWindowId: Int = windowId,
            candidatePackage: String = packageName,
            duplicateEligibleAnchor: Boolean = false,
        ): NavigationPostCaptureArtifact {
            var nextId = 0
            fun node(
                childIndex: Int?,
                className: String?,
                text: String? = null,
                resourceId: String? = null,
                children: List<CapturedHierarchyNode> = emptyList(),
                nodePackage: String = packageName,
                nodeWindow: Int = windowId,
            ): CapturedHierarchyNode {
                val id = nextId++
                return CapturedHierarchyNode(
                    stableIndex = id, childIndex = childIndex, text = text, contentDescription = null,
                    resourceId = resourceId, className = className, packageName = nodePackage,
                    sourceNodeId = "private-node-$id", windowId = nodeWindow,
                    bounds = CapturedBounds(id * 10, 0, id * 10 + 8, 8), clickable = false,
                    enabled = true, focusable = false, focused = false, accessibilityFocused = false,
                    selected = false, scrollable = false, checkable = false, checked = false,
                    visibleToUser = true, screenReaderFocusable = null, rangeInfoPresent = false,
                    actions = emptyList(), children = children,
                )
            }
            fun fillerChain(count: Int, childIndex: Int?): CapturedHierarchyNode =
                if (count == 1) node(childIndex, "android.view.View")
                else node(childIndex, "android.view.View", children = listOf(fillerChain(count - 1, 0)))

            val body = node(6, "android.widget.TextView", text = bodyLabel)
            val scrollChildren = buildList {
                add(fillerChain(44, 0))
                for (index in 1..5) add(node(index, "android.view.View"))
                add(body)
            }
            val scroll = node(0, "android.widget.ScrollView", children = scrollChildren)
            val title = node(0, "android.widget.TextView", text = childLabel, resourceId = titleId)
            val tab = node(2, candidateClass, text = candidateLabel, children = listOf(title),
                nodePackage = candidatePackage, nodeWindow = candidateWindowId)
            val navigationChildren = mutableListOf(
                node(0, "android.view.View"), node(1, "android.view.View"), tab,
            )
            if (duplicateEligibleAnchor) {
                navigationChildren.add(node(3, "android.widget.LinearLayout", text = "라이프"))
            }
            val navigation = node(1, parentClass, resourceId = parentResourceId, children = navigationChildren)
            val root = node(null, "android.widget.FrameLayout", children = listOf(scroll, navigation))
            val capture = ImmutableHierarchyCapture(root, nodeCount = nextId)
            if (!duplicateEligibleAnchor) assertEquals(57, nextId)
            val artifact = NavigationPostCaptureArtifact.fromCapture(
                capture = capture,
                requestId = "anchor-test-request",
                transactionId = "anchor-test-transaction",
                serviceInstanceId = "anchor-test-service",
                connectionId = "anchor-test-connection",
                windowId = windowId,
                captureId = "anchor-test-capture",
                capturedAtUptimeMs = 10L,
                hierarchyDigest = "a".repeat(64),
                contract = recovery,
                scenarioId = "life_air_care_plugin",
            )
            assertEquals("COMPLETE", artifact.completeness)
            assertEquals(nextId, artifact.persistedNodeCount)
            return artifact
        }

        val verifiedShape = sample()
        assertEquals(1, verifiedShape.requiredAnchorStructuralMatchCount)
        assertEquals(1, recovery.anchorMatchCount(listOf("라이프", "라이프", "라이프"),
            verifiedShape.requiredAnchorStructuralMatchCount))
        val projectedNodes = verifiedShape.payload.getJSONArray("nodes")
        val structuralRows = (0 until projectedNodes.length()).map { projectedNodes.getJSONObject(it) }
            .filter { row ->
                val ids = row.optJSONArray("diagnostic_policy_match_ids") ?: return@filter false
                (0 until ids.length()).any { ids.optString(it) == "required_anchor_structural_match" }
            }
        assertEquals(1, structuralRows.size)
        assertEquals("android.widget.LinearLayout", structuralRows.single().optString("class_name"))
        val parentId = structuralRows.single().getInt("parent_id")
        val parent = (0 until projectedNodes.length()).map { projectedNodes.getJSONObject(it) }
            .single { it.getInt("id") == parentId }
        assertEquals("android.widget.HorizontalScrollView", parent.optString("class_name"))
        assertEquals(bottomNavigationId, parent.optString("resource_id"))
        assertFalse(verifiedShape.payload.toString().contains("라이프"))

        val rejectedShapes = listOf(
            sample(candidateLabel = null, childLabel = null), // body label alone
            sample(candidateLabel = null, childLabel = "라이프"), // title child alone
            sample(parentClass = "android.widget.FrameLayout"),
            sample(parentClass = null),
            sample(parentResourceId = null),
            sample(parentResourceId = "com.samsung.android.oneconnect:id/other_container"),
            sample(candidateClass = "android.widget.TextView"),
            sample(candidateWindowId = windowId + 1),
            sample(candidatePackage = "com.example.foreign"),
        )
        rejectedShapes.forEach { rejected ->
            assertEquals(0, rejected.requiredAnchorStructuralMatchCount)
            assertNotEquals(1, recovery.anchorMatchCount(listOf("라이프", "라이프"),
                rejected.requiredAnchorStructuralMatchCount))
        }
        val duplicate = sample(duplicateEligibleAnchor = true)
        assertEquals(2, duplicate.requiredAnchorStructuralMatchCount)
        assertNotEquals(1, recovery.anchorMatchCount(listOf("라이프", "라이프", "라이프"),
            duplicate.requiredAnchorStructuralMatchCount))
        assertFalse(recovery.destinationMatches(listOf("에어 케어"), null, packageName,
            "android.widget.FrameLayout"))
        assertFalse(recovery.isWellFormed("0".repeat(64)))
        assertTrue(structure.isWellFormed())
    }

    @Test fun recoveryPostDiagnosticUsesSameScenarioPolicyButStillRejectsKnownEmptyStateAsLife() {
        val contracts = NavigationEffectContractRegistry.load(RuntimeEnvironment.getApplication().resources
            .openRawResource(R.raw.safe_navigation_contracts).use { it.readBytes() })
        val recovery = contracts.getValue("life_plugin_navigate_up_to_landing")
        val source = contracts.getValue("life_service_card_read_only_navigation")
        assertNull(recovery.emptyStateSignature)
        val signature = source.emptyStateSignature!!
        val scenarioId = "life_air_care_plugin"
        val target = FakeTarget(
            packageName = recovery.packageName,
            className = "android.widget.Button",
            resourceId = "back",
            label = "navigate up",
            windowId = 45534,
            independentDescendants = 0,
            subtreeLabels = listOf("navigate up"),
            descendants = emptyList(),
        )
        val actionBinding = binding(target, recovery).copy(
            scenarioId = scenarioId,
            effectContractId = recovery.id,
            effectContractDigest = recovery.digest,
        )
        val capability = NavigationActionCapability(contracts, { 1_000L })
        val prepared = capability.prepare(actionBinding, target, "service-1", target.connectionId)
        assertEquals("PREPARED", prepared.optString("status"))

        fun capturedNode(
            id: Int,
            childIndex: Int?,
            text: String?,
            contentDescription: String?,
            resourceId: String?,
            className: String,
            clickable: Boolean = false,
            actions: List<CapturedHierarchyAction> = emptyList(),
            children: List<CapturedHierarchyNode> = emptyList(),
        ) = CapturedHierarchyNode(
            stableIndex = id, childIndex = childIndex, text = text, contentDescription = contentDescription,
            resourceId = resourceId, className = className, packageName = recovery.packageName,
            sourceNodeId = "private-node-$id", windowId = target.windowId,
            bounds = CapturedBounds(id * 10, 0, id * 10 + 8, 8), clickable = clickable, enabled = true,
            focusable = clickable, focused = false, accessibilityFocused = false, selected = false,
            scrollable = false, checkable = false, checked = false, visibleToUser = true,
            screenReaderFocusable = null, rangeInfoPresent = false, actions = actions, children = children,
        )

        val unmatchedAck = capturedNode(
            1, 0, null, "private ack meaning", signature.anchorResourceId, signature.anchorClassName,
            clickable = true,
            actions = listOf(CapturedHierarchyAction(
                AccessibilityNodeInfo.ACTION_CLICK, "ACTION_CLICK", "private action label")),
        )
        val unrelatedText = capturedNode(
            2, 1, "unrelated private UI text", null, null, "android.widget.TextView")
        val root = capturedNode(
            0, null, signature.exactText, null, "com.samsung.android.oneconnect:id/root",
            signature.rootClassName, children = listOf(unmatchedAck, unrelatedText))
        val capture = ImmutableHierarchyCapture(root, nodeCount = 3)
        val sample = NavigationPostCaptureArtifact.fromCapture(
            capture = capture,
            requestId = actionBinding.requestId,
            transactionId = actionBinding.transactionId,
            serviceInstanceId = actionBinding.serviceInstanceId,
            connectionId = actionBinding.connectionId,
            windowId = target.windowId,
            captureId = "recovery-post-capture",
            capturedAtUptimeMs = 1_002L,
            hierarchyDigest = "e".repeat(64),
            contract = recovery,
            scenarioId = scenarioId,
            diagnosticPolicyContracts = contracts.values,
        )
        val nodes = sample.payload.getJSONArray("nodes")
        val titleMatch = nodes.getJSONObject(0).getJSONArray("diagnostic_policy_matches").getJSONObject(0)
        assertEquals(source.id, titleMatch.optString("contract_id"))
        assertEquals(source.digest, titleMatch.optString("contract_digest"))
        assertEquals("empty_state_exact_text", titleMatch.getJSONArray("match_ids").getString(0))
        val ackSummary = nodes.getJSONObject(1)
        val ackMatch = ackSummary.getJSONArray("diagnostic_policy_matches").getJSONObject(0)
        assertEquals("UNKNOWN", ackMatch.optString("anchor_semantic_status"))
        assertTrue(ackMatch.getJSONArray("match_ids").toString().contains("empty_state_anchor_candidate"))
        assertFalse(ackMatch.getJSONArray("match_ids").toString().contains("required_anchor_label"))
        assertFalse(ackMatch.getJSONArray("match_ids").toString().contains("empty_state_anchor_semantic_click_target"))
        assertEquals(listOf(0), (0 until ackSummary.getJSONArray("path").length())
            .map { ackSummary.getJSONArray("path").getInt(it) })
        assertEquals(signature.anchorClassName, ackSummary.optString("class_name"))
        assertEquals(signature.anchorResourceId, ackSummary.optString("resource_id"))
        assertFalse(nodes.getJSONObject(2).has("diagnostic_policy_matches"))
        assertFalse(sample.payload.toString().contains(signature.exactText))
        assertFalse(sample.payload.toString().contains("private ack meaning"))
        assertFalse(sample.payload.toString().contains("unrelated private UI text"))
        assertFalse(sample.payload.toString().contains("private-node-"))
        assertEquals(ExactProtocolJson.sha256(ExactProtocolJson.canonical(sample.payload)), sample.sha256)

        val post = NavigationPostActionEvidence(
            requestId = actionBinding.requestId,
            transactionId = actionBinding.transactionId,
            serviceInstanceId = actionBinding.serviceInstanceId,
            connectionId = actionBinding.connectionId,
            windowId = target.windowId,
            captureId = "recovery-post-capture",
            capturedAtUptimeMs = 1_002L,
            hierarchyDigest = "e".repeat(64),
            labels = listOf(signature.exactText, "unrelated private UI text"),
            focusWindowId = target.windowId,
            accessibilityFocused = true,
            focusInCurrentHierarchy = true,
            nodeCount = capture.nodeCount,
            rootPackageName = root.packageName,
            rootClassName = root.className,
            captureSample = sample,
        )
        val receipt = dispatch(capability, actionBinding, prepared.getString("lease_token"), target, post = post)
        assertEquals("NAVIGATION_DESTINATION_FOCUS_ANCHOR_UNPROVEN", receipt.optString("failure_code"))
        assertFalse(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertFalse(receipt.optBoolean("c5_credit"))
        val diagnostics = receipt.getJSONObject("post_state_diagnostics")
        assertFalse(diagnostics.optBoolean("required_destination_match"))
        assertEquals("REJECTED", diagnostics.optString("receipt_decision"))
        val artifact = diagnostics.getJSONObject("post_capture_sample_artifact")
        assertEquals(sample.sha256, artifact.optString("artifact_sha256"))
        assertEquals(actionBinding.requestId, artifact.getJSONObject("payload").optString("request_id"))
        assertEquals(actionBinding.transactionId, artifact.getJSONObject("payload").optString("transaction_id"))
        assertEquals(1, target.parentActionCalls)

        val foreignScenario = NavigationPostCaptureArtifact.fromCapture(
            capture, actionBinding.requestId, actionBinding.transactionId, actionBinding.serviceInstanceId,
            actionBinding.connectionId, target.windowId, "foreign-scenario-capture", 1_003L,
            "f".repeat(64), recovery, scenarioId = "another_scenario",
            diagnosticPolicyContracts = listOf(source),
        )
        assertFalse(foreignScenario.payload.getJSONArray("nodes").getJSONObject(0)
            .has("diagnostic_policy_matches"))
        val foreignPackage = NavigationPostCaptureArtifact.fromCapture(
            capture, actionBinding.requestId, actionBinding.transactionId, actionBinding.serviceInstanceId,
            actionBinding.connectionId, target.windowId, "foreign-package-capture", 1_004L,
            "a".repeat(64), recovery, scenarioId = scenarioId,
            diagnosticPolicyContracts = listOf(source.copy(packageName = "com.example.foreign")),
        )
        assertFalse(foreignPackage.payload.getJSONArray("nodes").getJSONObject(0)
            .has("diagnostic_policy_matches"))
    }

    @Test fun structuralLifeDestinationWithoutEmptyStateUsesOnlySameCaptureFocusAnchor() {
        val contract = NavigationEffectContractRegistry.load(RuntimeEnvironment.getApplication().resources
            .openRawResource(R.raw.safe_navigation_contracts).use { it.readBytes() })
            .getValue("life_plugin_navigate_up_to_landing")
        assertNull(contract.emptyStateSignature)
        assertNotNull(contract.requiredAnchorStructure)

        fun runCase(suffix: String, focusPath: List<Int>, completeness: String = "COMPLETE",
            structuralCount: Int? = 1, includeFocusTarget: Boolean = true): Triple<JSONObject, FakeTarget, Int> {
            var now = 1_000L
            val actionTarget = FakeTarget(
                packageName = contract.packageName, className = "android.widget.Button",
                resourceId = "back", label = "상위 메뉴로 이동", windowId = 45534,
                connectionId = "service-1", independentDescendants = 0,
                subtreeLabels = listOf("상위 메뉴로 이동"), descendants = emptyList(),
            )
            val actionBinding = binding(actionTarget, contract).copy(
                requestId = "structural-focus-$suffix", transactionId = "structural-focus-tx-$suffix",
                scenarioId = "life_air_care_plugin", effectContractId = contract.id,
                effectContractDigest = contract.digest,
            )
            val capability = NavigationActionCapability(mapOf(contract.id to contract), { now })
            val prepared = capability.prepare(actionBinding, actionTarget,
                actionBinding.serviceInstanceId, actionTarget.connectionId)
            assertEquals("PREPARED", prepared.optString("status"))

            val captureId = "structural-post-$suffix"
            fun sample(id: String, capturedAt: Long): NavigationPostCaptureArtifact {
                val nodes = JSONArray()
                    .put(JSONObject().put("id", 0).put("path", JSONArray()))
                    .put(JSONObject().put("id", 1).put("path", JSONArray().put(1)))
                    .put(JSONObject().put("id", 2).put("path", JSONArray().put(1).put(2))
                        .put("diagnostic_policy_match_ids", JSONArray()
                            .put("required_anchor_label").put("required_anchor_structural_match")))
                val payload = JSONObject()
                    .put("schema", "strict-post-capture-redacted-v1")
                    .put("request_id", actionBinding.requestId)
                    .put("transaction_id", actionBinding.transactionId)
                    .put("service_instance_id", actionBinding.serviceInstanceId)
                    .put("connection_id", actionBinding.connectionId)
                    .put("window_id", 192)
                    .put("capture_id", id)
                    .put("captured_at_elapsed_realtime_ms", capturedAt)
                    .put("hierarchy_digest", "f".repeat(64))
                    .put("diagnostic_only", true)
                    .put("effect_contract_id", contract.id)
                    .put("node_count", 3)
                    .put("persisted_node_count", 3)
                    .put("completeness", completeness)
                    .put("omitted_fields", JSONArray(listOf("text", "contentDescription", "action_labels", "sourceNodeId")))
                    .put("required_anchor_structural_match_count",
                        if (completeness == "COMPLETE") structuralCount ?: JSONObject.NULL else JSONObject.NULL)
                    .put("nodes", nodes)
                val canonical = ExactProtocolJson.canonical(payload)
                return NavigationPostCaptureArtifact(payload, ExactProtocolJson.sha256(canonical),
                    canonical.toByteArray(Charsets.UTF_8).size, completeness, 3, 3,
                    if (completeness == "COMPLETE") structuralCount else null)
            }

            val focusTarget = FakeTarget(
                packageName = contract.packageName, className = "android.widget.LinearLayout",
                resourceId = "", label = "라이프", windowId = 192, nodePath = focusPath,
                sourceSnapshotId = captureId, helperSnapshotId = captureId,
                baselineHierarchyDigest = "e".repeat(64), connectionId = actionTarget.connectionId,
                independentDescendants = 0, independentSiblings = 0, hasClickAction = false,
                subtreeLabels = listOf("라이프"), descendantEvidenceComplete = true, descendants = emptyList(),
            )
            fun post(id: String, capturedAt: Long, focused: Boolean,
                anchorTarget: NavigationActionTargetLease?): NavigationPostActionEvidence =
                NavigationPostActionEvidence(
                    requestId = actionBinding.requestId, transactionId = actionBinding.transactionId,
                    serviceInstanceId = actionBinding.serviceInstanceId, connectionId = actionBinding.connectionId,
                    windowId = 192, captureId = id, capturedAtUptimeMs = capturedAt,
                    hierarchyDigest = "f".repeat(64), labels = listOf("라이프"),
                    focusWindowId = if (focused) 192 else null,
                    accessibilityFocused = focused, focusInCurrentHierarchy = focused, nodeCount = 3,
                    rootPackageName = contract.packageName, rootClassName = "android.widget.FrameLayout",
                    captureSample = sample(id, capturedAt),
                    postWindowAuthority = airCareAuthority(actionBinding, postWindowId = 192, observedAt = capturedAt),
                    structureEvidence = null, destinationAnchorTarget = anchorTarget,
                )
            val initial = post(captureId, 1_002L, false, focusTarget.takeIf { includeFocusTarget })
            val fresh = post("$captureId-focused", 1_004L, true, null)
            var captures = 0
            val receipt = capability.dispatch(
                prepared.getString("lease_token"), actionBinding, actionBinding.serviceInstanceId,
                actionTarget.connectionId,
                armCollector = { _, target -> target === actionTarget },
                awaitClick = { NavigationClickEvidence(actionBinding.requestId, actionBinding.transactionId,
                    actionBinding.serviceInstanceId, actionBinding.connectionId, actionTarget.windowId,
                    AccessibilityEvent.TYPE_VIEW_CLICKED, 1_001L, actionTarget.identity) },
                markOwnerDispatch = { elapsed -> ownerDispatchReceipt(actionBinding, actionTarget,
                    actionTarget, null, elapsed) },
                confirmOwnerDispatch = { elapsed -> ownerConfirmedClickReceipt(actionBinding, actionTarget,
                    actionTarget, null, elapsed) },
                capturePostAction = { deadline, _ ->
                    assertEquals(6_000L, deadline)
                    captures++
                    if (captures == 1) { now = 1_002L; initial }
                    else { now = 1_004L; fresh }
                },
                currentServiceStillBound = { true },
            )
            return Triple(receipt, focusTarget, captures)
        }

        val (verified, verifiedTarget, verifiedCaptures) = runCase("exact", listOf(1, 2))
        assertTrue(verified.toString(), verified.optBoolean("verified_navigation"))
        assertFalse(verifiedTarget.hasClickAction)
        assertEquals(1, verifiedTarget.focusActionCalls)
        assertEquals(2, verifiedCaptures)
        val focus = verified.getJSONObject("post_state_diagnostics").getJSONObject("destination_anchor_focus")
        assertEquals(1, focus.optInt("focus_action_count"))
        assertEquals("structural-post-exact-focused", focus.optString("fresh_capture_id"))
        assertTrue(focus.optBoolean("same_post_window"))
        assertFalse(verified.optBoolean("visit_authority"))
        assertFalse(verified.optBoolean("c5_credit"))

        val (wrongPath, wrongPathTarget, wrongPathCaptures) = runCase("wrong-path", listOf(1, 1))
        assertFalse(wrongPath.optBoolean("verified_navigation"))
        assertEquals(0, wrongPathTarget.focusActionCalls)
        assertEquals(1, wrongPathCaptures)
        assertFalse(wrongPath.optBoolean("visit_authority"))
        assertFalse(wrongPath.optBoolean("c5_credit"))

        val (incomplete, incompleteTarget, incompleteCaptures) = runCase(
            "incomplete", listOf(1, 2), "INCOMPLETE_NODE_LIMIT", null)
        assertFalse(incomplete.optBoolean("verified_navigation"))
        assertEquals(0, incompleteTarget.focusActionCalls)
        assertEquals(1, incompleteCaptures)
        assertFalse(incomplete.optBoolean("visit_authority"))
        assertFalse(incomplete.optBoolean("c5_credit"))

        val (targetUnavailable, unavailableTarget, unavailableCaptures) =
            runCase("target-unavailable", listOf(1, 2), includeFocusTarget = false)
        assertFalse(targetUnavailable.optBoolean("verified_navigation"))
        assertEquals(0, unavailableTarget.focusActionCalls)
        assertEquals(1, unavailableCaptures)
        val unavailableFocus = targetUnavailable.getJSONObject("post_state_diagnostics")
            .getJSONObject("destination_anchor_focus")
        assertEquals("FOCUS_TARGET_UNAVAILABLE", unavailableFocus.optString("status"))
        assertEquals("target_resolution", unavailableFocus.optString("failure_stage"))
        assertFalse(targetUnavailable.optBoolean("visit_authority"))
        assertFalse(targetUnavailable.optBoolean("c5_credit"))
    }

    @Test fun configuredNavigateUpDispatchesOnlyExactLeafButtonAndRequiresLifeLandingEvidence() {
        val policyBytes = RuntimeEnvironment.getApplication().resources
            .openRawResource(R.raw.safe_navigation_contracts).use { it.readBytes() }
        val contract = NavigationEffectContractRegistry.load(policyBytes)
            .getValue("life_plugin_navigate_up_to_landing")
        val target = FakeTarget(
            packageName = "com.samsung.android.oneconnect",
            className = "android.widget.Button",
            resourceId = "back",
            label = "상위 메뉴로 이동",
            windowId = 45534,
            independentDescendants = 0,
            subtreeLabels = listOf("상위 메뉴로 이동"),
            descendants = emptyList(),
        )
        val parentBinding = binding(target, contract).copy(
            scenarioId = "life_air_care_plugin",
            effectContractId = contract.id,
            effectContractDigest = contract.digest,
        )
        val capability = NavigationActionCapability(mapOf(contract.id to contract), { 1_000L })
        val prepared = capability.prepare(parentBinding, target, "service-1", target.connectionId)
        assertEquals("PREPARED", prepared.optString("status"))
        fun captured(
            id: Int,
            childIndex: Int?,
            className: String,
            text: String? = null,
            resourceId: String? = null,
            children: List<CapturedHierarchyNode> = emptyList(),
        ) = CapturedHierarchyNode(
            stableIndex = id, childIndex = childIndex, text = text, contentDescription = null,
            resourceId = resourceId, className = className, packageName = target.packageName,
            sourceNodeId = "private-node-$id", windowId = target.windowId,
            bounds = CapturedBounds(id * 10, 0, id * 10 + 8, 8), clickable = false, enabled = true,
            focusable = false, focused = false, accessibilityFocused = false, selected = false,
            scrollable = false, checkable = false, checked = false, visibleToUser = true,
            screenReaderFocusable = null, rangeInfoPresent = false, actions = emptyList(), children = children,
        )
        val tab = captured(2, 0, "android.widget.LinearLayout", text = "라이프")
        val bottomNavigation = captured(1, 0, "android.widget.HorizontalScrollView",
            resourceId = "com.samsung.android.oneconnect:id/bottom_navigation", children = listOf(tab))
        val root = captured(0, null, "android.widget.FrameLayout", children = listOf(bottomNavigation))
        val capture = ImmutableHierarchyCapture(root, nodeCount = 3)
        val captureSample = NavigationPostCaptureArtifact.fromCapture(
            capture = capture,
            requestId = parentBinding.requestId,
            transactionId = parentBinding.transactionId,
            serviceInstanceId = parentBinding.serviceInstanceId,
            connectionId = parentBinding.connectionId,
            windowId = target.windowId,
            captureId = "post-life-capture",
            capturedAtUptimeMs = 1_002L,
            hierarchyDigest = "d".repeat(64),
            contract = contract,
            scenarioId = "life_air_care_plugin",
        )
        assertEquals(1, captureSample.requiredAnchorStructuralMatchCount)
        val post = NavigationPostActionEvidence(
            parentBinding.requestId, parentBinding.transactionId, parentBinding.serviceInstanceId, parentBinding.connectionId,
            target.windowId, "post-life", 1_002L, "c".repeat(64), listOf("라이프"),
            target.windowId, true, true, nodeCount = capture.nodeCount,
            rootPackageName = root.packageName, rootClassName = root.className, captureSample = captureSample,
        )
        val receipt = dispatch(capability, parentBinding, prepared.getString("lease_token"), target, post = post)
        assertTrue(receipt.getBoolean("verified_navigation"))
        assertFalse(receipt.getBoolean("visit_authority"))
        assertFalse(receipt.getBoolean("c5_credit"))
        assertEquals(1, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)

        val child = FakeTarget(
            packageName = target.packageName,
            className = "android.widget.FrameLayout",
            resourceId = "com.samsung.android.oneconnect:id/frameLayout",
            label = "",
            windowId = target.windowId,
            independentDescendants = 0,
            subtreeLabels = listOf("상위 메뉴로 이동"),
            descendants = emptyList(),
        )
        val childBinding = binding(child, contract).copy(
            requestId = "request-child",
            scenarioId = "life_air_care_plugin",
            effectContractId = contract.id,
            effectContractDigest = contract.digest,
        )
        val rejected = capability.prepare(childBinding, child, "service-1", child.connectionId)
        assertEquals("NAVIGATION_EFFECT_UNPROVEN", rejected.optString("failure_code"))
        assertEquals(0, child.parentActionCalls)
    }

    @Test fun childSelectionAndAmbiguousTargetFailBeforeDispatch() {
        val contract = contract()
        val child = FakeTarget(className = "android.widget.Button", label = "Power", independentDescendants = 0)
        val capability = NavigationActionCapability(mapOf(contract.id to contract), { 1_000L })
        val childDecision = capability.prepare(binding(child, contract), child, "service-1", child.connectionId)
        assertEquals("NAVIGATION_EFFECT_UNPROVEN", childDecision.optString("failure_code"))
        assertEquals(0, child.parentActionCalls)

        val ambiguous = FakeTarget(isUniqueInSnapshot = false)
        val ambiguousDecision = capability.prepare(binding(ambiguous, contract), ambiguous, "service-1", ambiguous.connectionId)
        assertEquals("NAVIGATION_TARGET_UNPROVEN", ambiguousDecision.optString("failure_code"))
        assertEquals(0, ambiguous.parentActionCalls)
    }

    @Test fun contractRequiresExactScenarioAndTargetSubtree() {
        val contract = contract()
        val target = FakeTarget(subtreeLabels = listOf("Other context"))
        val capability = NavigationActionCapability(mapOf(contract.id to contract), { 1_000L })
        val wrongSubtree = capability.prepare(binding(target, contract), target, "service-1", target.connectionId)
        assertEquals("NAVIGATION_EFFECT_UNPROVEN", wrongSubtree.optString("failure_code"))

        val exactTarget = FakeTarget()
        val wrongScenario = capability.prepare(binding(exactTarget, contract).copy(scenarioId = "scenario-other"),
            exactTarget, "service-1", exactTarget.connectionId)
        assertEquals("NAVIGATION_SCENARIO_NOT_AUTHORIZED", wrongScenario.optString("failure_code"))
        assertEquals(0, exactTarget.parentActionCalls)
    }

    @Test fun exactEventWithoutMatchingOwnerDispatchReceiptNeverVerifies() {
        val target = FakeTarget()
        val (capability, binding, token) = rig(target)
        val wrongReceipt = JSONObject().put("ok", true).put("ownerLeaseId", "different-lease")
            .put("eligibleExactClickCount", 1).put("clickEventId", "owner-click")
        val receipt = dispatch(capability, binding, token, target, ownerReceipt = wrongReceipt)
        assertEquals("NAVIGATION_OWNER_RECEIPT_UNVERIFIED", receipt.optString("failure_code"))
        assertFalse(receipt.getBoolean("verified_navigation"))
        assertFalse(receipt.getBoolean("visit_authority"))
        assertFalse(receipt.getBoolean("c5_credit"))
        assertEquals(false, receipt.getBoolean("owner_receipt_lease_match"))
        assertEquals(1, receipt.getInt("owner_receipt_eligible_exact_click_count"))
        assertTrue(receipt.getBoolean("owner_receipt_click_event_present"))
        assertEquals(1, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)
    }

    @Test fun missingContractAndStaleWindowOrConnectionFailClosed() {
        val target = FakeTarget()
        val contract = contract()
        val missing = NavigationActionCapability(emptyMap(), { 1_000L })
            .prepare(binding(target, contract), target, "service-1", target.connectionId)
        assertEquals("NAVIGATION_EFFECT_CONTRACT_UNAVAILABLE", missing.optString("failure_code"))

        val capability = NavigationActionCapability(mapOf(contract.id to contract), { 1_000L })
        val staleWindow = capability.prepare(binding(target, contract).copy(windowId = 8), target,
            "service-1", target.connectionId)
        assertEquals("NAVIGATION_BINDING_MISMATCH", staleWindow.optString("failure_code"))
        val staleConnection = capability.prepare(binding(target, contract), target,
            "service-1", "connection-old")
        assertEquals("NAVIGATION_BINDING_MISMATCH", staleConnection.optString("failure_code"))
    }

    @Test fun wrongTransactionOrStaleLeaseCannotDispatch() {
        val target = FakeTarget()
        val (capability, binding, token) = rig(target)
        val mismatch = dispatch(capability, binding.copy(transactionId = "tx-other"), token, target)
        assertEquals("NAVIGATION_PRE_DISPATCH_BINDING_REJECTED", mismatch.optString("failure_code"))
        assertEquals(0, target.parentActionCalls)

        val (staleCapability, staleBinding, staleToken) = rig(target)
        target.current = false
        val stale = dispatch(staleCapability, staleBinding, staleToken, target)
        assertEquals("NAVIGATION_TARGET_STALE", stale.optString("failure_code"))
        assertEquals(0, target.parentActionCalls)
    }

    @Test fun sourceMismatchNoTransitionMissingFocusOrAnchorNeverVerifies() {
        val target = FakeTarget()
        val (cap1, binding1, token1) = rig(target)
        val wrongSource = dispatch(cap1, binding1, token1, target, clickSource = Any())
        assertEquals("NAVIGATION_EVENT_SOURCE_MISMATCH", wrongSource.optString("failure_code"))
        assertFalse(wrongSource.getBoolean("visit_authority"))

        val (cap2, binding2, token2) = rig(target)
        val noTransition = NavigationPostActionEvidence(binding2.requestId, binding2.transactionId,
            binding2.serviceInstanceId, binding2.connectionId, target.windowId, "post-2", 1_002L,
            binding2.baselineHierarchyDigest, listOf("Dashboard", "Navigate up"), target.windowId, true, true)
        val noTransitionReceipt = dispatch(cap2, binding2, token2, target, noTransition)
        assertEquals("NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE", noTransitionReceipt.optString("failure_code"))
        assertTrue(noTransitionReceipt.getJSONArray("post_state_mismatch_fields").toString()
            .contains("hierarchy_digest_missing_or_unchanged"))
        assertEquals(2, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)

        val (cap3, binding3, token3) = rig(target)
        val noFocus = NavigationPostActionEvidence(binding3.requestId, binding3.transactionId,
            binding3.serviceInstanceId, binding3.connectionId, target.windowId, "post-3", 1_002L,
            "c".repeat(64), listOf("Dashboard", "Navigate up"), target.windowId, false, true)
        val noFocusReceipt = dispatch(cap3, binding3, token3, target, noFocus)
        assertEquals("NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE", noFocusReceipt.optString("failure_code"))
        assertTrue(noFocusReceipt.getJSONArray("post_state_mismatch_fields").toString()
            .contains("accessibility_focus_missing"))
        assertFalse(noFocusReceipt.getBoolean("visit_authority"))
        assertFalse(noFocusReceipt.getBoolean("c5_credit"))
        assertEquals(3, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)

        val (cap4, binding4, token4) = rig(target)
        val noAnchor = NavigationPostActionEvidence(binding4.requestId, binding4.transactionId,
            binding4.serviceInstanceId, binding4.connectionId, target.windowId, "post-4", 1_002L,
            "c".repeat(64), listOf("Dashboard"), target.windowId, true, true)
        assertEquals("NAVIGATION_DESTINATION_FOCUS_ANCHOR_UNPROVEN",
            dispatch(cap4, binding4, token4, target, noAnchor).optString("failure_code"))
    }

    @Test fun stalePostStateReceiptExplainsMatchedClickAndMissingFocusWithoutGrantingAuthority() {
        val target = FakeTarget()
        val (capability, binding, token) = rig(target)
        val missingFocusWindow = NavigationPostActionEvidence(
            requestId = binding.requestId,
            transactionId = binding.transactionId,
            serviceInstanceId = binding.serviceInstanceId,
            connectionId = binding.connectionId,
            windowId = target.windowId,
            captureId = "post-capture-missing-focus",
            capturedAtUptimeMs = 1_002L,
            hierarchyDigest = "c".repeat(64),
            labels = listOf("Air Care"),
            focusWindowId = null,
            accessibilityFocused = false,
            focusInCurrentHierarchy = false,
            nodeCount = 12,
            rootPackageName = "com.example.smartthings",
            rootClassName = "android.widget.FrameLayout",
        )

        val receipt = dispatch(capability, binding, token, target, missingFocusWindow)

        assertEquals("NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE", receipt.optString("failure_code"))
        assertEquals(listOf("accessibility_focus_missing", "focus_not_in_current_hierarchy",
            "focus_window_mismatch"), (0 until receipt.getJSONArray("post_state_mismatch_fields").length())
            .map { receipt.getJSONArray("post_state_mismatch_fields").getString(it) })
        val diagnostics = receipt.getJSONObject("post_state_diagnostics")
        assertEquals("EXACT_RETAINED_NODE_MATCH", diagnostics.optString("event_source_status"))
        assertEquals(binding.requestId, diagnostics.optString("event_source_request_id"))
        assertEquals(binding.transactionId, diagnostics.optString("event_source_transaction_id"))
        assertTrue(diagnostics.optBoolean("event_source_connection_match"))
        assertEquals(target.windowId, diagnostics.optInt("event_source_event_window_id"))
        assertEquals("post-capture-missing-focus", diagnostics.optString("post_capture_id"))
        assertEquals("FIELD_ABSENT", diagnostics.optString("focus_window_id_status"))
        assertTrue(diagnostics.isNull("focus_window_id"))
        assertFalse(diagnostics.optBoolean("accessibility_focused"))
        assertFalse(diagnostics.optBoolean("focus_in_current_hierarchy"))
        assertEquals("COMPLETE", diagnostics.optString("post_capture_completeness"))
        assertTrue(diagnostics.isNull("post_capture_failure_stage"))
        assertEquals(12, diagnostics.optInt("post_capture_node_count"))
        assertEquals("com.example.smartthings", diagnostics.optString("post_capture_root_package"))
        assertEquals("android.widget.FrameLayout", diagnostics.optString("post_capture_root_class"))
        assertFalse(receipt.optBoolean("verified_navigation"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertFalse(receipt.optBoolean("c5_credit"))
        assertEquals(binding.requestId, diagnostics.optString("request_id"))
        assertEquals(binding.transactionId, diagnostics.optString("transaction_id"))
        assertEquals(binding.serviceInstanceId, diagnostics.optString("action_service_instance_id"))
        assertEquals(binding.connectionId, diagnostics.optString("action_connection_id"))
        assertEquals(target.windowId, diagnostics.optInt("action_window_id"))
        assertTrue(diagnostics.optLong("capture_call_completion_elapsed_realtime_ms") >=
            diagnostics.optLong("capture_call_start_elapsed_realtime_ms"))
        assertFalse(diagnostics.optBoolean("required_destination_match"))
        assertTrue(diagnostics.isNull("required_anchor_match_count"))
        assertEquals("DESTINATION_NOT_MATCHED", diagnostics.optString("required_anchor_outcome"))
        assertEquals("REJECTED", diagnostics.optString("receipt_decision"))
        assertEquals("NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE", diagnostics.optString("receipt_failure_code"))
        assertTrue(diagnostics.getJSONArray("failure_stages").toString()
            .contains("accessibility_focus_missing"))
        assertFalse(receipt.optBoolean("visit_authority"))
        assertFalse(receipt.optBoolean("c5_credit"))
        assertEquals(1, target.parentActionCalls)
        assertEquals(0, target.childActionCalls)
    }
}
