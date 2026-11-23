package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf

@RunWith(RobolectricTestRunner::class)
class EntryObservationTargetLeaseTest {
    private data class Rig(
        val resolver: ExactLiveNodeResolver,
        val root: AccessibilityNodeInfo,
        val target: AccessibilityNodeInfo,
        val window: AccessibilityWindowInfo,
    )

    private fun node(resource: String, window: AccessibilityWindowInfo): AccessibilityNodeInfo =
        AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.RelativeLayout"
            viewIdResourceName = resource
            contentDescription = "Air Care"
            isClickable = true
            isEnabled = true
            isVisibleToUser = true
            setBoundsInScreen(Rect(20, 40, 500, 600))
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
            shadowOf(this).setAccessibilityWindowInfo(window)
            shadowOf(this).setRefreshReturnValue(true)
        }

    private fun rig(duplicate: Boolean = false): Rig {
        val window = AccessibilityWindowInfo.obtain().apply {
            shadowOf(this).setId(45518)
            shadowOf(this).setType(1)
            shadowOf(this).setActive(true)
        }
        val root = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.FrameLayout"
            setBoundsInScreen(Rect(0, 0, 1080, 2400))
            shadowOf(this).setAccessibilityWindowInfo(window)
            shadowOf(this).setRefreshReturnValue(true)
        }
        val target = node("", window)
        shadowOf(root).addChild(target)
        if (duplicate) shadowOf(root).addChild(node("", window))
        shadowOf(window).setRoot(root)
        val resolver = ExactLiveNodeResolver { listOf(ExactApplicationWindow(45518, 1, true, root)) }
        return Rig(resolver, root, target, window)
    }

    private fun lease(rig: Rig, path: List<Int> = listOf(0)): ExactLiveNodeResolver.ObservationTarget {
        val digest = rig.resolver.descriptorDigest(rig.target)
        return rig.resolver.captureObservationTarget(
            expectedWindowId = 45518,
            expectedPackage = "com.samsung.android.oneconnect",
            nodePath = path,
            expectedDescriptorDigest = digest,
            sourceSnapshotId = "source-snapshot-1",
            connectionId = "connection-generation-1",
        )
    }

    private fun sourceIdentity(target: ExactLiveNodeResolver.ObservationTarget, requestId: String) =
        EntryClickSourceIdentity(
            requestId = requestId,
            processEpoch = "process-epoch-1",
            generation = 4L,
            serviceInstanceId = "connection-generation-1",
            captureSequence = 9L,
            rootDigest = "a".repeat(64),
            candidateDigest = "b".repeat(64),
            captureKey = target.sourceSnapshotId,
            connectionEpoch = "connection-generation-1",
            bootEpoch = "boot:33",
            ownerSourceNodeId = target.sourceNodeId,
            ownerSourceNodeIdStatus = if (target.sourceNodeId.isBlank()) "FIELD_ABSENT" else "FIELD_PRESENT",
        )

    @Test
    fun exactFrameworkSourceMatchIsWindowAndConnectionBoundWithoutPublicUniqueId() {
        val rig = rig()
        val target = lease(rig)
        assertNull(rig.target.uniqueId)
        assertTrue(target.sourceNodeId.isBlank())
        assertTrue(target.eventSourceMatches(rig.target, 45518, "connection-generation-1"))
        assertFalse(target.eventSourceMatches(rig.target, 45519, "connection-generation-1"))
        assertFalse(target.eventSourceMatches(rig.target, 45518, "connection-generation-2"))
        assertFalse(target.eventSourceMatches(node("", rig.window), 45518, "connection-generation-1"))
    }

    @Test
    fun absentSourceIdStillRevalidatesUniqueDescriptorAndRetainedFrameworkNode() {
        val rig = rig()
        val target = lease(rig)
        assertEquals(1, target.descriptorMatchCount)
        assertTrue(target.sourceNodeId.isBlank())
        assertTrue(target.stillCurrent("connection-generation-1"))
        assertTrue(target.eventSourceMatches(rig.target, 45518, "connection-generation-1"))
        assertFalse(target.eventSourceMatches(node("", rig.window), 45518, "connection-generation-1"))
    }

    @Test
    fun duplicateDescriptorAndChangedPathFailClosed() {
        val duplicate = rig(duplicate = true)
        val digest = duplicate.resolver.descriptorDigest(duplicate.target)
        assertThrows(ExactActionRejected::class.java) {
            duplicate.resolver.captureObservationTarget(45518, "com.samsung.android.oneconnect", listOf(0),
                digest, "source-snapshot-1", "connection-generation-1")
        }

        val changed = rig()
        val target = lease(changed)
        changed.target.text = "Changed after capture"
        assertFalse(target.stillCurrent("connection-generation-1"))
    }

    @Test
    fun observationTargetRejectsMismatchedSourceNodeIdentity() {
        val rig = rig()
        val digest = rig.resolver.descriptorDigest(rig.target)
        assertThrows(ExactActionRejected::class.java) {
            rig.resolver.captureObservationTarget(
                expectedWindowId = 45518,
                expectedPackage = "com.samsung.android.oneconnect",
                nodePath = listOf(0),
                expectedDescriptorDigest = digest,
                sourceSnapshotId = "source-snapshot-1",
                connectionId = "connection-generation-1",
                expectedSourceNodeId = "different-node",
            )
        }
    }

    @Test
    fun declaredActivationChildAndDestinationAnchorStayExactInLiveResolver() {
        val rig = rig()
        val child = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.FrameLayout"
            viewIdResourceName = "com.samsung.android.oneconnect:id/frameLayout"
            isClickable = true
            isEnabled = true
            isVisibleToUser = true
            setBoundsInScreen(Rect(30, 50, 490, 580))
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
            shadowOf(this).setAccessibilityWindowInfo(rig.window)
            shadowOf(this).setRefreshReturnValue(true)
        }
        shadowOf(rig.target).addChild(child)
        val parentObservation = lease(rig)
        val parent = rig.resolver.captureNavigationActionTarget(
            expectedWindowId = 45518,
            expectedPackage = "com.samsung.android.oneconnect",
            nodePath = listOf(0),
            expectedDescriptorDigest = parentObservation.descriptorDigest,
            sourceSnapshotId = "source-snapshot-1",
            connectionId = "connection-generation-1",
        )
        val relation = NavigationActivationOwnerRelation(
            "direct_child", 0, """^android\.widget\.FrameLayout$""",
            "com.samsung.android.oneconnect:id/frameLayout",
        )
        val actionChild = parent.exactDeclaredActivationChild(relation, "connection-generation-1")
        assertNotNull(actionChild)
        assertEquals(listOf(0, 0), actionChild!!.nodePath)
        assertEquals(parent.windowId, actionChild.windowId)
        assertEquals(parent.sourceSnapshotId, actionChild.sourceSnapshotId)
        assertEquals(parent.helperSnapshotId, actionChild.helperSnapshotId)
        assertEquals(parent.baselineHierarchyDigest, actionChild.baselineHierarchyDigest)
        assertNull(parent.exactDeclaredActivationChild(
            relation.copy(childIndex = 1), "connection-generation-1"))
        assertNull(parent.exactDeclaredActivationChild(
            relation.copy(childResourceId = "com.samsung.android.oneconnect:id/include"),
            "connection-generation-1"))

        val webView = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.webkit.WebView"
            isEnabled = true
            isVisibleToUser = true
            setBoundsInScreen(Rect(0, 0, 1080, 2000))
            shadowOf(this).setAccessibilityWindowInfo(rig.window)
            shadowOf(this).setRefreshReturnValue(true)
        }
        val back = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.Button"
            viewIdResourceName = "back"
            text = "상위 메뉴로 이동"
            isClickable = true
            isEnabled = true
            isVisibleToUser = true
            setBoundsInScreen(Rect(20, 30, 120, 90))
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_ACCESSIBILITY_FOCUS)
            shadowOf(this).setAccessibilityWindowInfo(rig.window)
            shadowOf(this).setRefreshReturnValue(true)
        }
        shadowOf(webView).addChild(back)
        shadowOf(rig.root).addChild(webView)
        shadowOf(rig.window).setRoot(rig.root)
        val signature = NavigationEmptyStateSignature(
            exactText = "Exact observed Air Care setup sentence",
            rootClassName = "android.widget.FrameLayout",
            containerClassName = "android.view.View",
            containerResourceId = "paneContainer",
            webViewClassName = "android.webkit.WebView",
            anchorClassName = "android.widget.Button",
            anchorResourceId = "back",
            excludedClassName = "android.widget.GridView",
        )
        val anchor = rig.resolver.captureUniqueDestinationAnchor(
            expectedWindowId = 45518,
            expectedPackage = "com.samsung.android.oneconnect",
            sourceSnapshotId = "post-capture-1",
            connectionId = "connection-generation-1",
            signature = signature,
            anchorPattern = "(?i)^(?:navigate up|상위 메뉴로 이동)$",
        )
        assertNotNull(anchor)
        assertEquals(listOf(1, 0), anchor!!.nodePath)
        assertEquals("android.widget.Button", anchor.className)
        assertEquals("back", anchor.resourceId)
        assertEquals(45518, anchor.windowId)
        assertTrue(anchor.hasAccessibilityFocusAction)
    }

    private fun structuralAnchorRig(
        label: String = "\uB77C\uC774\uD504",
        parentResourceId: String = "com.samsung.android.oneconnect:id/bottom_navigation",
        duplicate: Boolean = false,
        includeClickAction: Boolean = false,
    ): Rig {
        val rig = rig()
        val container = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.HorizontalScrollView"
            viewIdResourceName = parentResourceId
            isEnabled = true
            isVisibleToUser = true
            isFocusable = true
            setBoundsInScreen(Rect(0, 1600, 1080, 1900))
            shadowOf(this).setAccessibilityWindowInfo(rig.window)
            shadowOf(this).setRefreshReturnValue(true)
        }
        fun slot(resourceId: String) = node(resourceId, rig.window)
        shadowOf(container).addChild(slot("nav_slot_0"))
        shadowOf(container).addChild(slot("nav_slot_1"))
        fun lifeAnchor() = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.LinearLayout"
            contentDescription = label
            isClickable = false
            isEnabled = true
            isVisibleToUser = true
            isFocusable = true
            setBoundsInScreen(Rect(500, 1600, 700, 1900))
            if (includeClickAction) addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_ACCESSIBILITY_FOCUS)
            shadowOf(this).setAccessibilityWindowInfo(rig.window)
            shadowOf(this).setRefreshReturnValue(true)
        }
        shadowOf(container).addChild(lifeAnchor())
        if (duplicate) shadowOf(container).addChild(lifeAnchor())
        shadowOf(rig.root).addChild(container)
        shadowOf(rig.window).setRoot(rig.root)
        return rig
    }

    private fun captureStructuralAnchor(
        rig: Rig,
        expectedPath: List<Int> = listOf(1, 2),
    ): ExactLiveNodeResolver.NavigationTargetLease? = rig.resolver.captureUniqueStructuralDestinationAnchor(
        expectedWindowId = 45518,
        expectedRootClassName = "android.widget.FrameLayout",
        expectedPackage = "com.samsung.android.oneconnect",
        sourceSnapshotId = "post-capture-1",
        connectionId = "connection-generation-1",
        expectedNodePath = expectedPath,
        structure = NavigationAnchorStructure(
            relation = "direct_parent",
            nodeClassPattern = "^android.widget.LinearLayout$",
            parentClassPattern = "^android.widget.HorizontalScrollView$",
            parentResourceIdPattern = "^com\\.samsung\\.android\\.oneconnect:id/bottom_navigation$",
        ),
        anchorPattern = "(?i)^\uB77C\uC774\uD504$",
    )

    @Test
    fun structuralDestinationCapturesFocusableNoClickAnchorAndCannotGrantClick() {
        val rig = structuralAnchorRig()
        val anchor = captureStructuralAnchor(rig)
        assertNotNull(anchor)
        assertEquals(listOf(1, 2), anchor!!.nodePath)
        assertTrue(anchor.hasAccessibilityFocusAction)
        assertFalse(anchor.hasClickAction)

        val authorization = NavigationActionDispatchAuthorization.afterNavigationGate(
            "focus-request", "focus-transaction", "focus-lease", NAVIGATION_ACTION_CLICK,
        )
        val rejected = assertThrows(ExactActionRejected::class.java) {
            anchor.performNavigationClick(
                authorization, "focus-request", "focus-transaction", "focus-lease", "connection-generation-1",
            )
        }
        assertEquals("OBSERVATION_TARGET_NOT_ACTIONABLE", rejected.code)

        val clickCapableNode = structuralAnchorRig(includeClickAction = true)
        val focusOnlyLease = captureStructuralAnchor(clickCapableNode)
        assertNotNull(focusOnlyLease)
        assertFalse(focusOnlyLease!!.hasClickAction)
        val clickDenied = assertThrows(ExactActionRejected::class.java) {
            focusOnlyLease.performNavigationClick(
                NavigationActionDispatchAuthorization.afterNavigationGate(
                    "focus-request-2", "focus-transaction-2", "focus-lease-2", NAVIGATION_ACTION_CLICK,
                ), "focus-request-2", "focus-transaction-2", "focus-lease-2", "connection-generation-1",
            )
        }
        assertEquals("OBSERVATION_TARGET_NOT_ACTIONABLE", clickDenied.code)
    }

    @Test
    fun structuralDestinationRejectsWrongPathMissingWrongParentAndAmbiguousAnchors() {
        val wrongPath = structuralAnchorRig()
        assertNull(captureStructuralAnchor(wrongPath, listOf(1, 1)))

        val missing = structuralAnchorRig(label = "Devices")
        assertNull(captureStructuralAnchor(missing))

        val wrongParent = structuralAnchorRig(parentResourceId = "com.samsung.android.oneconnect:id/other")
        assertNull(captureStructuralAnchor(wrongParent))

        val ambiguous = structuralAnchorRig(duplicate = true)
        assertNull(captureStructuralAnchor(ambiguous))
    }

    @Test
    fun navigationLeaseCannotSubstituteAnActionableChildForTheRetainedParent() {
        val rig = rig()
        val child = node("child_action", rig.window)
        shadowOf(rig.target).addChild(child)
        val observation = lease(rig)
        val navigationTarget = rig.resolver.NavigationTargetLease(observation, child)
        val authorization = NavigationActionDispatchAuthorization.afterNavigationGate(
            "request", "transaction", "lease", NAVIGATION_ACTION_CLICK,
        )

        val rejected = assertThrows(ExactActionRejected::class.java) {
            navigationTarget.performNavigationClick(
                authorization,
                "request",
                "transaction",
                "lease",
                "connection-generation-1",
            )
        }
        assertTrue(rejected.code == "NAVIGATION_TARGET_IDENTITY_MISMATCH")
    }

    @Test
    fun navigationRequiresCanonicalInvocationBoundOwnerCapture() {
        val rig = rig()
        val owner = lease(rig)
        val sourceNonCanonical = sourceIdentity(owner, "source-request-1")
        val sourceCanonical = sourceIdentity(owner, "source-request-2")
        val connection = "connection-generation-1"
        val nonCanonicalReq = "owner-capture-noncanonical"
        val nonCanonical = A11yEvidence.armEntryClickCapture(
            reqId = nonCanonicalReq,
            transactionId = "transaction-1",
            leaseMs = 2_000L,
            connectionId = connection,
            runId = "run-1",
            invocationId = "invocation-1",
            scenarioId = "life_air_care_plugin",
            ownerTarget = owner,
            sourceIdentity = sourceNonCanonical,
            canonicalInvocationUriBound = false,
        )
        assertTrue(nonCanonical.optBoolean("ok"))
        assertFalse(nonCanonical.optBoolean("invocationUriBound"))
        assertNull(A11yEvidence.navigationTargetLease(
            ownerCaptureReqId = nonCanonicalReq,
            ownerLeaseId = nonCanonical.getString("ownerLeaseId"),
            transactionId = "transaction-1",
            connectionId = connection,
            runId = "run-1",
            invocationId = "invocation-1",
            scenarioId = "life_air_care_plugin",
            captureId = nonCanonical.getString("captureId"),
            sourceIdentity = sourceNonCanonical,
        ))
        A11yEvidence.disarmEntryClickCapture(nonCanonicalReq)

        val canonicalReq = "owner-capture-canonical"
        val canonical = A11yEvidence.armEntryClickCapture(
            reqId = canonicalReq,
            transactionId = "transaction-2",
            leaseMs = 2_000L,
            connectionId = connection,
            runId = "run-1",
            invocationId = "invocation-2",
            scenarioId = "life_air_care_plugin",
            ownerTarget = owner,
            sourceIdentity = sourceCanonical,
            canonicalInvocationUriBound = true,
        )
        try {
            assertTrue(canonical.optBoolean("ok"))
            assertTrue(canonical.optBoolean("invocationUriBound"))
            assertNotNull(A11yEvidence.navigationTargetLease(
                ownerCaptureReqId = canonicalReq,
                ownerLeaseId = canonical.getString("ownerLeaseId"),
                transactionId = "transaction-2",
                connectionId = connection,
                runId = "run-1",
                invocationId = "invocation-2",
                scenarioId = "life_air_care_plugin",
                captureId = canonical.getString("captureId"),
                sourceIdentity = sourceCanonical,
            ))
            assertNull(A11yEvidence.navigationTargetLease(
                ownerCaptureReqId = canonicalReq,
                ownerLeaseId = canonical.getString("ownerLeaseId"),
                transactionId = "transaction-2",
                connectionId = connection,
                runId = "run-1",
                invocationId = "invocation-2",
                scenarioId = "life_air_care_plugin",
                captureId = canonical.getString("captureId"),
                sourceIdentity = sourceCanonical.copy(connectionEpoch = "stale-connection"),
            ))
        } finally {
            A11yEvidence.disarmEntryClickCapture(canonicalReq)
        }
    }
}
