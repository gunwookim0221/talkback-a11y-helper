package com.iotpart.sqe.talkbackhelper

import android.net.Uri
import android.content.Intent
import android.os.SystemClock
import android.graphics.Rect
import android.view.View
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.Shadows.shadowOf
import org.robolectric.RuntimeEnvironment
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class EntryClickCaptureTest {

    @Test
    fun manifestRoutesOnlyCanonicalInvocationDataAndNoDataCaptureRequests() {
        val context = RuntimeEnvironment.getApplication()
        val receiverName = A11yCommandReceiver::class.java.name
        fun resolves(data: Uri?): Boolean {
            val intent = Intent("com.iotpart.sqe.talkbackhelper.ENTRY_CLICK_CAPTURE")
                .setPackage(context.packageName)
            if (data != null) intent.data = data
            return context.packageManager.queryBroadcastReceivers(intent, 0)
                .any { it.activityInfo?.name == receiverName }
        }

        assertTrue(resolves(Uri.parse("invocation_id:scenario-current")))
        assertTrue(resolves(null))
        assertFalse(resolves(Uri.parse("other:scenario-current")))
    }

    @Test
    fun canonicalInvocationUriMustMatchTheOwnerLeaseExactly() {
        val owner = JSONObject().put("invocation_id", "scenario-current")
        assertTrue(A11yCommandReceiver.canonicalInvocationUriMatches(
            Uri.parse("invocation_id:scenario-current"), owner,
        ))
        assertFalse(A11yCommandReceiver.canonicalInvocationUriMatches(
            Uri.parse("invocation_id:scenario-stale"), owner,
        ))
        assertFalse(A11yCommandReceiver.canonicalInvocationUriMatches(
            Uri.parse("invocation_id:"), owner,
        ))
        assertFalse(A11yCommandReceiver.canonicalInvocationUriMatches(null, owner))
        assertFalse(A11yCommandReceiver.canonicalInvocationUriMatches(
            Uri.parse("invocation_id:scenario-current"), JSONObject().put("invocation_id", ""),
        ))
    }

    @Test
    fun ownerLeaseRequestUsesShellSafeEncodingAndRetainsExactIdentityFields() {
        val expected = JSONObject()
            .put("run_id", "run-current")
            .put("invocation_id", "scenario-current")
            .put("scenario_id", "life_air_care_plugin")
            .put("request_id", "owner-request")
            .put("transaction_id", "action-transaction")
            .put("source_snapshot_id", "snapshot-current")
            .put("source_capture_request_id", "0123456789abcdef0123456789abcdef")
            .put("source_process_epoch", "process-epoch-current")
            .put("source_generation", 7)
            .put("source_service_instance_id", "service-current")
            .put("source_capture_sequence", 19)
            .put("source_root_digest", "b".repeat(64))
            .put("source_candidate_digest", "c".repeat(64))
            .put("source_capture_key", "d".repeat(64))
            .put("window_id", 45534)
            .put("package", "com.samsung.android.oneconnect")
            .put("node_path", org.json.JSONArray().put(0).put(1).put(2))
            .put("descriptor_digest", "a".repeat(64))
        val encoded = android.util.Base64.encodeToString(
            expected.toString().toByteArray(Charsets.UTF_8),
            android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP,
        )
        val decoded = A11yCommandReceiver.decodeOwnerLeaseRequest(encoded)
        assertEquals(expected.toString(), decoded?.toString())
        assertTrue(A11yCommandReceiver.canonicalInvocationUriMatches(
            Uri.parse("invocation_id:scenario-current"), decoded,
        ))
    }

    @Test
    fun missingMalformedAndNonCanonicalOwnerLeasePayloadsAreRejected() {
        assertNull(A11yCommandReceiver.decodeOwnerLeaseRequest(null))
        assertNull(A11yCommandReceiver.decodeOwnerLeaseRequest(""))
        assertNull(A11yCommandReceiver.decodeOwnerLeaseRequest("{\"invocation_id\":\"scenario-current\"}"))
        assertNull(A11yCommandReceiver.decodeOwnerLeaseRequest("%%%not-base64%%%"))
        val json = "{\"invocation_id\":\"scenario-current\"}"
        val valid = android.util.Base64.encodeToString(
            json.toByteArray(Charsets.UTF_8), android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP,
        )
        assertNull(A11yCommandReceiver.decodeOwnerLeaseRequest(" $valid"))
        assertEquals("scenario-current", A11yCommandReceiver.decodeOwnerLeaseRequest(valid)?.optString("invocation_id"))
    }

    @Test
    fun beginResponsePreservesNormalSuccessEnvelopeAndCorrelation() {
        val response = A11yCommandReceiver.buildEntryClickCaptureResponse(
            "response-1", "capture-request-1", "tx-1", "begin",
        ) {
            JSONObject().put("ok", true).put("reason", "ARMED").put("transactionId", "tx-1")
                .put("ownerLeaseId", "lease-1").put("ownerWindowId", 9)
        }
        assertTrue(response.optBoolean("ok"))
        assertEquals("ARMED", response.optString("reason"))
        assertEquals("tx-1", response.optString("transactionId"))
        assertEquals("lease-1", response.optString("ownerLeaseId"))
        assertEquals("response-1", response.optString("reqId"))
        assertEquals("capture-request-1", response.optString("captureReqId"))
        assertEquals("tx-1", response.optString("requestedTransactionId"))
        assertEquals("begin", response.optString("operation"))
    }

    @Test
    fun beginRejectionStripsAnyLeaseOrEventPayloadAuthority() {
        val response = A11yCommandReceiver.buildEntryClickCaptureResponse(
            "response-2", "capture-request-2", "tx-2", "begin",
        ) {
            JSONObject().put("ok", false).put("reason", "OBSERVATION_TARGET_NOT_ACTIONABLE")
                .put("ownerLeaseId", "must-not-escape").put("captureId", "must-not-escape")
                .put("evidenceEvents", org.json.JSONArray().put(JSONObject().put("eventType", "CLICK")))
                .put("diagnostics", JSONObject()
                    .put("stage", "live_node_actionability")
                    .put("code", "OBSERVATION_TARGET_NOT_ACTIONABLE")
                    .put("request_id", "capture-request-2")
                    .put("transaction_id", "tx-2")
                    .put("expected_path", org.json.JSONArray().put(0).put(1).put(4))
                    .put("expected_window_id", 26)
                    .put("expected_package", "com.samsung.android.oneconnect")
                    .put("expected_descriptor_digest", "a".repeat(64))
                    .put("expected_source_node_id_status", "FIELD_ABSENT")
                    .put("actual_live_node", JSONObject()
                        .put("class_name", "android.widget.RelativeLayout")
                        .put("resource_id", "com.samsung:id/containerNameLayout")
                        .put("package_name", "com.samsung.android.oneconnect")
                        .put("window_id", 26).put("visible", true).put("enabled", true)
                        .put("clickable", false).put("action_click", false)
                        .put("text", "PRIVATE LABEL").put("content_description", "PRIVATE DESCRIPTION"))
                    .put("currentness", JSONObject().put("source_capture_current", true)
                        .put("generation_matches", true).put("unexpected", "PRIVATE"))
                    .put("unexpected", "PRIVATE"))
        }
        assertFalse(response.optBoolean("ok"))
        assertEquals("OBSERVATION_TARGET_NOT_ACTIONABLE", response.optString("reason"))
        assertEquals("response-2", response.optString("reqId"))
        assertEquals("capture-request-2", response.optString("captureReqId"))
        assertEquals("tx-2", response.optString("requestedTransactionId"))
        assertFalse(response.has("ownerLeaseId"))
        assertFalse(response.has("captureId"))
        assertFalse(response.has("evidenceEvents"))
        assertFalse(response.has("transactionId"))
        val diagnostics = response.getJSONObject("diagnostics")
        assertEquals("live_node_actionability", diagnostics.optString("stage"))
        assertEquals("OBSERVATION_TARGET_NOT_ACTIONABLE", diagnostics.optString("code"))
        assertEquals("capture-request-2", diagnostics.optString("request_id"))
        assertEquals("tx-2", diagnostics.optString("transaction_id"))
        assertEquals("0,1,4", (0 until diagnostics.getJSONArray("expected_path").length())
            .joinToString(",") { diagnostics.getJSONArray("expected_path").getInt(it).toString() })
        val liveNode = diagnostics.getJSONObject("actual_live_node")
        assertEquals("android.widget.RelativeLayout", liveNode.optString("class_name"))
        assertEquals("com.samsung:id/containerNameLayout", liveNode.optString("resource_id"))
        assertFalse(liveNode.has("text"))
        assertFalse(liveNode.has("content_description"))
        assertFalse(diagnostics.has("unexpected"))
        assertFalse(diagnostics.getJSONObject("currentness").has("unexpected"))
    }

    @Test
    fun observationTargetActionabilityDiagnosticDoesNotChangeResolverRejection() {
        val window = AccessibilityWindowInfo.obtain().apply {
            shadowOf(this).setId(26)
            shadowOf(this).setType(1)
            shadowOf(this).setActive(true)
        }
        val target = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.RelativeLayout"
            viewIdResourceName = "com.samsung:id/containerNameLayout"
            text = "PRIVATE LABEL"
            contentDescription = "PRIVATE DESCRIPTION"
            isVisibleToUser = true
            isEnabled = true
            isClickable = false
            setBoundsInScreen(Rect(10, 20, 300, 400))
        }
        shadowOf(target).setAccessibilityWindowInfo(window)
        val root = AccessibilityNodeInfo.obtain().apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.FrameLayout"
            setBoundsInScreen(Rect(0, 0, 400, 800))
        }
        shadowOf(root).setAccessibilityWindowInfo(window)
        shadowOf(root).addChild(target)
        shadowOf(window).setRoot(root)
        val resolver = ExactLiveNodeResolver { listOf(ExactApplicationWindow(26, 1, true, root)) }
        val observed = mutableMapOf<String, Any>()
        val failure = try {
            resolver.captureObservationTarget(
                26, "com.samsung.android.oneconnect", listOf(0), resolver.descriptorDigest(target),
                "snapshot-current", "service-current", onResolvedNode = { node ->
                    observed["class"] = node.className.toString()
                    observed["resource"] = node.viewIdResourceName
                    observed["window"] = node.windowId
                    observed["visible"] = node.isVisibleToUser
                    observed["enabled"] = node.isEnabled
                    observed["clickable"] = node.isClickable
                    observed["actionClick"] = node.actionList.any {
                        it.id == AccessibilityNodeInfo.ACTION_CLICK
                    }
                },
            )
            throw AssertionError("non-clickable exact owner must remain rejected")
        } catch (error: ExactActionRejected) {
            error
        }
        assertEquals("OBSERVATION_TARGET_NOT_ACTIONABLE", failure.code)
        assertEquals("android.widget.RelativeLayout", observed["class"])
        assertEquals("com.samsung:id/containerNameLayout", observed["resource"])
        assertEquals(26, observed["window"])
        assertEquals(true, observed["visible"])
        assertEquals(true, observed["enabled"])
        assertEquals(false, observed["clickable"])
        assertEquals(false, observed["actionClick"])
    }

    @Test
    fun beginExceptionYieldsOneCorrelatedNegativeEnvelope() {
        var computeCount = 0
        val response = A11yCommandReceiver.buildEntryClickCaptureResponse(
            "response-3", "capture-request-3", "tx-3", "begin",
        ) {
            computeCount += 1
            throw IllegalStateException("private detail is not serialized")
        }
        assertEquals(1, computeCount)
        assertFalse(response.optBoolean("ok"))
        assertEquals("ENTRY_CLICK_CAPTURE_OPERATION_FAILED", response.optString("reason"))
        assertEquals("IllegalStateException", response.optString("failureType"))
        assertEquals("response-3", response.optString("reqId"))
        assertEquals("capture-request-3", response.optString("captureReqId"))
        assertFalse(response.has("ownerLeaseId"))
        assertFalse(response.has("captureId"))
        assertFalse(response.has("evidenceEvents"))
    }

    @Test
    fun exactOwnerFocusDispatchBindsDistinctNavigationAndCaptureRequests() {
        val ownerCaptureReqId = "owner-capture-" + UUID.randomUUID()
        val navigationRequestId = "navigation-request-" + UUID.randomUUID()
        assertNotEquals(ownerCaptureReqId, navigationRequestId)
        val transactionId = "transaction-" + UUID.randomUUID()
        val connectionId = "connection-" + UUID.randomUUID()
        val packageName = "com.samsung.android.oneconnect"
        val window = AccessibilityWindowInfo.obtain().apply {
            shadowOf(this).setId(344)
            shadowOf(this).setType(1)
            shadowOf(this).setActive(true)
        }
        fun actionableNode(resourceId: String) = AccessibilityNodeInfo.obtain().apply {
            setPackageName(packageName)
            className = "android.widget.RelativeLayout"
            viewIdResourceName = "$packageName:id/$resourceId"
            isEnabled = true
            isVisibleToUser = true
            isClickable = true
            isFocusable = true
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_ACCESSIBILITY_FOCUS)
            setBoundsInScreen(Rect(10, 20, 390, 380))
            shadowOf(this).setRefreshReturnValue(true)
        }
        val target = actionableNode("airCareEntry")
        target.isAccessibilityFocused = true
        target.addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
        val unrelated = actionableNode("otherEntry")
        val root = AccessibilityNodeInfo.obtain().apply {
            setPackageName(packageName)
            className = "android.widget.FrameLayout"
            setBoundsInScreen(Rect(0, 0, 400, 800))
        }
        listOf(target, unrelated, root).forEach { shadowOf(it).setAccessibilityWindowInfo(window) }
        shadowOf(root).addChild(target)
        shadowOf(root).addChild(unrelated)
        shadowOf(window).setRoot(root)
        val resolver = ExactLiveNodeResolver {
            listOf(ExactApplicationWindow(344, 1, true, root))
        }
        val snapshotId = "same-owner-focus-" + UUID.randomUUID()
        val targetObservation = resolver.captureObservationTarget(
            344, packageName, listOf(0), resolver.descriptorDigest(target), snapshotId, connectionId,
        )
        val unrelatedObservation = resolver.captureObservationTarget(
            344, packageName, listOf(1), resolver.descriptorDigest(unrelated), snapshotId, connectionId,
        )
        val sourceIdentity = EntryClickSourceIdentity(
            requestId = "source-request-" + UUID.randomUUID(),
            processEpoch = "process-epoch-1", generation = 1L,
            serviceInstanceId = connectionId, captureSequence = 1L,
            rootDigest = "a".repeat(64), candidateDigest = "b".repeat(64),
            captureKey = snapshotId, connectionEpoch = connectionId, bootEpoch = "boot:34",
            ownerSourceNodeId = targetObservation.sourceNodeId,
            ownerSourceNodeIdStatus = if (targetObservation.sourceNodeId.isBlank()) "FIELD_ABSENT" else "FIELD_PRESENT",
        )
        val armed = A11yEvidence.armEntryClickCapture(
            ownerCaptureReqId, transactionId, 2500L, connectionId, "run-focus", "invocation-focus",
            "life_plugin_navigate_up_to_landing", targetObservation, sourceIdentity,
            canonicalInvocationUriBound = true,
        )
        assertTrue(armed.optBoolean("ok"))
        val actualOwnerLeaseId = armed.getString("ownerLeaseId")

        val wrongTargetBinding = A11yEvidence.bindNavigationActionTarget(
            ownerCaptureReqId, navigationRequestId, transactionId, connectionId,
            "run-focus", "invocation-focus", "life_plugin_navigate_up_to_landing",
            armed.getString("captureId"), actualOwnerLeaseId, sourceIdentity,
            targetObservation.navigationActionLease(), unrelatedObservation.navigationActionLease(), null,
        )
        assertFalse(wrongTargetBinding.optBoolean("ok"))
        assertEquals("ENTRY_CLICK_CAPTURE_ACTION_TARGET_MISMATCH", wrongTargetBinding.optString("reason"))

        val bound = A11yEvidence.bindNavigationActionTarget(
            ownerCaptureReqId, navigationRequestId, transactionId, connectionId,
            "run-focus", "invocation-focus", "life_plugin_navigate_up_to_landing",
            armed.getString("captureId"), actualOwnerLeaseId, sourceIdentity,
            targetObservation.navigationActionLease(), targetObservation.navigationActionLease(), null,
        )
        assertTrue(bound.optBoolean("ok"))
        assertEquals(navigationRequestId, bound.optString("navigationRequestId"))
        assertEquals(ownerCaptureReqId, bound.optString("ownerCaptureReqId"))
        assertTrue(bound.isNull("activationOwnerRelation"))

        val focusElapsed = SystemClock.elapsedRealtime()
        val focusProof = NavigationFocusEvidence(
            navigationRequestId, ownerCaptureReqId, actualOwnerLeaseId, transactionId,
            connectionId, connectionId, 344, AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED,
            focusElapsed, target,
        )
        SystemClock.sleep(2L)
        val dispatchElapsed = SystemClock.elapsedRealtime()

        val invalidProof = focusProof.copy(requestId = "unrelated-navigation-request")
        val rejectedProof = A11yEvidence.markNavigationEntryClickDispatch(
            ownerCaptureReqId, transactionId, connectionId, dispatchElapsed, invalidProof,
        )
        assertFalse(rejectedProof.optBoolean("ok"))
        assertEquals("ENTRY_CLICK_CAPTURE_FOCUS_PROOF_MISMATCH", rejectedProof.optString("reason"))

        unrelated.contentDescription = "changed sibling"
        val changedTree = A11yEvidence.markNavigationEntryClickDispatch(
            ownerCaptureReqId, transactionId, connectionId, dispatchElapsed, focusProof,
        )
        assertFalse(changedTree.optBoolean("ok"))
        assertEquals("ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE", changedTree.optString("reason"))
        assertEquals("focus_neutral_hierarchy_digest_matches",
            changedTree.getJSONObject("focus_revalidation").optString("first_failed_check"))
        unrelated.contentDescription = null

        val marked = A11yEvidence.markNavigationEntryClickDispatch(
            ownerCaptureReqId, transactionId, connectionId, dispatchElapsed, focusProof,
        )
        assertTrue("same-owner mark: ${marked}", marked.optBoolean("ok"))
        assertEquals(navigationRequestId, marked.optString("navigationRequestId"))
        assertEquals(ownerCaptureReqId, marked.optString("ownerCaptureReqId"))
        assertEquals(0, marked.optInt("eligibleExactClickCount"))
        assertTrue(marked.optBoolean("dispatchTargetCurrentnessAccepted"))
        assertTrue(marked.optBoolean("focusProofAccepted"))
        assertTrue(A11yEvidence.disarmEntryClickCapture(ownerCaptureReqId).optBoolean("ok"))
    }

    @Test
    fun declaredChildOwnerIsBoundBeforeDispatchAndParentClickCannotSatisfyIt() {
        val reqId = "child-click-" + UUID.randomUUID()
        val navigationRequestId = "navigation-request-" + UUID.randomUUID()
        assertNotEquals(reqId, navigationRequestId)
        val transactionId = "transaction-" + UUID.randomUUID()
        val connectionId = "connection-" + UUID.randomUUID()
        val packageName = "com.samsung.android.oneconnect"
        val window = AccessibilityWindowInfo.obtain().apply {
            shadowOf(this).setId(150)
            shadowOf(this).setType(1)
            shadowOf(this).setActive(true)
        }
        val parent = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            this.packageName = packageName
            className = "android.widget.RelativeLayout"
            viewIdResourceName = packageName + ":id/containerNameLayout"
            isEnabled = true
            isVisibleToUser = true
            isClickable = true
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
            setBoundsInScreen(Rect(10, 20, 390, 780))
        }
        val child = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            this.packageName = packageName
            className = "android.widget.FrameLayout"
            viewIdResourceName = packageName + ":id/frameLayout"
            isEnabled = true
            isVisibleToUser = true
            isClickable = true
            isFocusable = true
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_ACCESSIBILITY_FOCUS)
            setBoundsInScreen(Rect(20, 500, 380, 760))
        }
        val root = AccessibilityNodeInfo.obtain().apply {
            this.packageName = packageName
            className = "android.widget.FrameLayout"
            setBoundsInScreen(Rect(0, 0, 400, 800))
        }
        listOf(parent, child, root).forEach { shadowOf(it).setAccessibilityWindowInfo(window) }
        shadowOf(parent).addChild(child)
        shadowOf(root).addChild(parent)
        shadowOf(window).setRoot(root)
        var activeWindows = listOf(ExactApplicationWindow(150, 1, true, root))
        val resolver = ExactLiveNodeResolver { activeWindows }
        val sourceSnapshotId = "aircare-source-" + UUID.randomUUID()
        val parentObservation = resolver.captureObservationTarget(
            150, packageName, listOf(0), resolver.descriptorDigest(parent), sourceSnapshotId, connectionId,
        )
        val parentLease = parentObservation.navigationActionLease()
        val relation = NavigationActivationOwnerRelation(
            "direct_child", 0, "^android\\.widget\\.FrameLayout$", packageName + ":id/frameLayout",
        )
        val childLease = requireNotNull(parentLease.exactDeclaredActivationChild(relation, connectionId)) {
            "approved direct FrameLayout child should resolve from the retained parent"
        }
        assertNotEquals(parentLease.nodePath, childLease.nodePath)
        val sourceIdentity = EntryClickSourceIdentity(
            requestId = "source-request-" + UUID.randomUUID(),
            processEpoch = "process-epoch-1",
            generation = 3L,
            serviceInstanceId = connectionId,
            captureSequence = 8L,
            rootDigest = "a".repeat(64),
            candidateDigest = "b".repeat(64),
            captureKey = sourceSnapshotId,
            connectionEpoch = connectionId,
            bootEpoch = "boot:33",
            ownerSourceNodeId = parentObservation.sourceNodeId,
            ownerSourceNodeIdStatus = if (parentObservation.sourceNodeId.isBlank()) "FIELD_ABSENT" else "FIELD_PRESENT",
        )
        val armed = A11yEvidence.armEntryClickCapture(
            reqId, transactionId, 2500L, connectionId, "run-1", "invocation-1", "life_air_care_plugin",
            parentObservation, sourceIdentity, canonicalInvocationUriBound = true,
        )
        assertTrue(armed.optBoolean("ok"))
        val captureId = armed.getString("captureId")
        val ownerLeaseId = armed.getString("ownerLeaseId")

        val wrongRelation = relation.copy(childIndex = 1)
        val wrongBinding = A11yEvidence.bindNavigationActionTarget(
            reqId, navigationRequestId, transactionId, connectionId, "run-1", "invocation-1", "life_air_care_plugin",
            captureId, ownerLeaseId, sourceIdentity, parentLease, childLease, wrongRelation,
        )
        assertFalse(wrongBinding.optBoolean("ok"))
        assertEquals("ENTRY_CLICK_CAPTURE_ACTION_CHILD_MISMATCH", wrongBinding.optString("reason"))

        val bound = A11yEvidence.bindNavigationActionTarget(
            reqId, navigationRequestId, transactionId, connectionId, "run-1", "invocation-1", "life_air_care_plugin",
            captureId, ownerLeaseId, sourceIdentity, parentLease, childLease, relation,
        )
        assertTrue(bound.optBoolean("ok"))
        assertEquals(navigationRequestId, bound.optString("navigationRequestId"))
        assertEquals(reqId, bound.optString("ownerCaptureReqId"))
        assertEquals(ownerLeaseId, bound.optString("ownerLeaseId"))
        assertEquals(parentLease.nodePath, (0 until bound.getJSONArray("ownerAuthorizationPath").length())
            .map { bound.getJSONArray("ownerAuthorizationPath").getInt(it) })
        assertEquals(childLease.nodePath, (0 until bound.getJSONArray("ownerActionPath").length())
            .map { bound.getJSONArray("ownerActionPath").getInt(it) })

        child.isAccessibilityFocused = true
        assertTrue(child.removeAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_ACCESSIBILITY_FOCUS))
        child.addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLEAR_ACCESSIBILITY_FOCUS)
        val focusElapsed = SystemClock.elapsedRealtime()
        val focusProof = NavigationFocusEvidence(navigationRequestId, reqId, ownerLeaseId, transactionId,
            sourceIdentity.serviceInstanceId, connectionId, 150,
            AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED, focusElapsed, child)
        SystemClock.sleep(2L)
        val dispatchElapsed = SystemClock.elapsedRealtime()

        val invalidFocusProofs = listOf(
            focusProof.copy(requestId = "other-navigation-request"),
            focusProof.copy(ownerCaptureReqId = "other-owner-capture"),
            focusProof.copy(ownerLeaseId = "other-owner-lease"),
            focusProof.copy(transactionId = "other-transaction"),
            focusProof.copy(serviceInstanceId = "other-service"),
            focusProof.copy(connectionId = "other-connection"),
            focusProof.copy(windowId = 192),
            focusProof.copy(eventType = AccessibilityEvent.TYPE_VIEW_CLICKED),
            focusProof.copy(eventElapsedRealtimeMs = dispatchElapsed + 1L),
            focusProof.copy(eventElapsedRealtimeMs = focusElapsed - 3_000L),
            focusProof.copy(source = parent),
        )
        invalidFocusProofs.forEach { invalidProof ->
            val rejected = A11yEvidence.markNavigationEntryClickDispatch(
                reqId, transactionId, connectionId, dispatchElapsed, invalidProof,
            )
            assertFalse(rejected.optBoolean("ok"))
            assertEquals("ENTRY_CLICK_CAPTURE_FOCUS_PROOF_MISMATCH", rejected.optString("reason"))
        }

        parent.contentDescription = "changed authorization parent"
        val changedParent = A11yEvidence.markNavigationEntryClickDispatch(
            reqId, transactionId, connectionId, dispatchElapsed, focusProof,
        )
        assertFalse(changedParent.optBoolean("ok"))
        assertEquals("ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE", changedParent.optString("reason"))
        assertEquals("parent_descriptor_matches",
            changedParent.getJSONObject("focus_revalidation").optString("first_failed_check"))
        parent.contentDescription = null

        val marked = A11yEvidence.markNavigationEntryClickDispatch(
            reqId, transactionId, connectionId, dispatchElapsed, focusProof,
        )
        assertTrue(marked.optBoolean("ok"))
        assertEquals(navigationRequestId, marked.optString("navigationRequestId"))
        assertEquals(reqId, marked.optString("ownerCaptureReqId"))
        assertEquals(ownerLeaseId, marked.optString("ownerLeaseId"))
        assertEquals(0, marked.optInt("eligibleExactClickCount"))
        assertTrue(marked.isNull("clickEventId"))
        assertEquals(parentLease.nodePath, (0 until marked.getJSONArray("ownerAuthorizationPath").length())
            .map { marked.getJSONArray("ownerAuthorizationPath").getInt(it) })
        assertEquals(childLease.nodePath, (0 until marked.getJSONArray("ownerActionPath").length())
            .map { marked.getJSONArray("ownerActionPath").getInt(it) })
        assertTrue(marked.optBoolean("dispatchTargetCurrentnessAccepted"))

        val destinationWindow = AccessibilityWindowInfo.obtain().apply {
            shadowOf(this).setId(192)
            shadowOf(this).setType(1)
            shadowOf(this).setActive(true)
        }
        val destinationRoot = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            setPackageName("com.samsung.android.oneconnect")
            className = "android.widget.FrameLayout"
            setBoundsInScreen(Rect(0, 0, 400, 800))
        }
        shadowOf(destinationRoot).setAccessibilityWindowInfo(destinationWindow)
        shadowOf(destinationWindow).setRoot(destinationRoot)
        shadowOf(window).setActive(false)
        activeWindows = listOf(ExactApplicationWindow(192, 1, true, destinationRoot))
        assertFalse(parentLease.stillCurrent(connectionId))
        assertFalse(childLease.stillCurrent(connectionId))

        fun clickFrom(source: AccessibilityNodeInfo): AccessibilityEvent {
            val event = AccessibilityEvent.obtain(AccessibilityEvent.TYPE_VIEW_CLICKED)
            event.eventTime = SystemClock.uptimeMillis()
            event.packageName = packageName
            shadowOf(event).apply {
                setSourceNode(source)
                setWindowId(150)
            }
            return event
        }

        SystemClock.sleep(3L)
        val parentEvent = clickFrom(parent)
        assertFalse(A11yEvidence.captureEntryClickEvent(parentEvent, connectionId).isNullOrBlank())
        val parentConfirmation = A11yEvidence.confirmEntryClickDispatch(
            reqId, transactionId, connectionId, dispatchElapsed,
        )
        assertFalse(parentConfirmation.optBoolean("ok"))
        assertEquals(0, parentConfirmation.optInt("eligibleExactClickCount"))
        parentEvent.recycle()

        SystemClock.sleep(3L)
        val childEvent = clickFrom(child)
        assertFalse(A11yEvidence.captureEntryClickEvent(childEvent, connectionId).isNullOrBlank())
        val confirmed = A11yEvidence.confirmEntryClickDispatch(
            reqId, transactionId, connectionId, dispatchElapsed,
        )
        assertTrue(confirmed.optBoolean("ok"))
        assertTrue(confirmed.optBoolean("dispatchTargetCurrentnessAccepted"))
        assertEquals(1, confirmed.optInt("eligibleExactClickCount"))
        assertEquals("EXACT_OWNER_CLICK_CONFIRMED", confirmed.optString("reason"))
        assertEquals(AccessibilityEvent.TYPE_VIEW_CLICKED, confirmed.optInt("clickEventType"))
        assertEquals(150, confirmed.optInt("ownerActionWindowId"))
        assertEquals(parentLease.nodePath, (0 until confirmed.getJSONArray("ownerAuthorizationPath").length())
            .map { confirmed.getJSONArray("ownerAuthorizationPath").getInt(it) })
        assertEquals(childLease.nodePath, (0 until confirmed.getJSONArray("ownerActionPath").length())
            .map { confirmed.getJSONArray("ownerActionPath").getInt(it) })
        val events = A11yEvidence.entryClickSnapshot(reqId).getJSONArray("evidenceEvents")
        val parentPayload = events.optJSONObject(0)?.optJSONObject("payload")
        assertEquals("OWNER_UNPROVEN", parentPayload?.optString("owner_relation"))
        val childPayload = events.optJSONObject(1)?.optJSONObject("payload")
        assertEquals("EXACT_RETAINED_NODE_REFERENCE", childPayload?.optString("owner_relation"))
        assertTrue(childPayload?.optBoolean("owner_exact") == true)
        assertEquals("HOST_MARKED", childPayload?.optString("dispatch_correlation_status"))
        assertEquals(parentLease.nodePath, (0 until childPayload!!.getJSONArray("owner_authorization_path").length())
            .map { childPayload.getJSONArray("owner_authorization_path").getInt(it) })
        assertEquals(childLease.nodePath, (0 until childPayload.getJSONArray("owner_action_path").length())
            .map { childPayload.getJSONArray("owner_action_path").getInt(it) })
        assertFalse(A11yEvidence.confirmEntryClickDispatch(
            reqId, transactionId, "foreign-connection", dispatchElapsed,
        ).optBoolean("ok"))
        SystemClock.sleep(2_510L)
        val expired = A11yEvidence.confirmEntryClickDispatch(
            reqId, transactionId, connectionId, dispatchElapsed,
        )
        assertFalse(expired.optBoolean("ok"))
        assertEquals("ENTRY_CLICK_CAPTURE_DISPATCH_PROOF_EXPIRED", expired.optString("reason"))
        childEvent.recycle()
        assertTrue(A11yEvidence.disarmEntryClickCapture(reqId).optBoolean("ok"))
    }

    @Test
    fun clickEventIsRetainedOnlyUnderArmedTransactionAndExactSourceIsExplicit() {
        val reqId = "click-${UUID.randomUUID()}"
        val transactionId = "transaction-${UUID.randomUUID()}"
        val connectionId = "connection-${UUID.randomUUID()}"
        val window = AccessibilityWindowInfo.obtain().apply {
            shadowOf(this).setId(9)
            shadowOf(this).setType(1)
            shadowOf(this).setActive(true)
        }
        val targetView = View(RuntimeEnvironment.getApplication())
        val target = AccessibilityNodeInfo.obtain(targetView).apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.RelativeLayout"
            contentDescription = "Air Care"
            isClickable = true
            isEnabled = true
            isVisibleToUser = true
            setBoundsInScreen(Rect(10, 20, 300, 400))
            addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK)
        }
        shadowOf(target).setAccessibilityWindowInfo(window)
        val root = AccessibilityNodeInfo.obtain().apply {
            packageName = "com.samsung.android.oneconnect"
            className = "android.widget.FrameLayout"
            setBoundsInScreen(Rect(0, 0, 400, 800))
        }
        shadowOf(root).setAccessibilityWindowInfo(window)
        shadowOf(root).addChild(target)
        shadowOf(window).setRoot(root)
        val resolver = ExactLiveNodeResolver { listOf(ExactApplicationWindow(9, 1, true, root)) }
        val targetDigest = resolver.descriptorDigest(target)
        val ownerTarget = resolver.captureObservationTarget(9, "com.samsung.android.oneconnect", listOf(0),
            targetDigest, "source-snapshot", connectionId)
        assertTrue(ownerTarget.sourceNodeId.isBlank())
        val invocationUriBound = A11yCommandReceiver.canonicalInvocationUriMatches(
            Uri.parse("invocation_id:invocation-1"), JSONObject().put("invocation_id", "invocation-1"),
        )
        assertTrue(invocationUriBound)
        val sourceIdentity = EntryClickSourceIdentity(
            requestId = "source-request-1",
            processEpoch = "process-epoch-1",
            generation = 3L,
            serviceInstanceId = connectionId,
            captureSequence = 8L,
            rootDigest = "a".repeat(64),
            candidateDigest = "b".repeat(64),
            captureKey = ownerTarget.sourceSnapshotId,
            connectionEpoch = "connection-epoch-1",
            bootEpoch = "boot:33",
            ownerSourceNodeId = ownerTarget.sourceNodeId,
            ownerSourceNodeIdStatus = if (ownerTarget.sourceNodeId.isBlank()) "FIELD_ABSENT" else "FIELD_PRESENT",
        )
        val armed = A11yEvidence.armEntryClickCapture(reqId, transactionId, 2000L, connectionId,
            "run-1", "invocation-1", "scenario-1", ownerTarget,
            sourceIdentity = sourceIdentity,
            canonicalInvocationUriBound = invocationUriBound)
        assertTrue(armed.optBoolean("ok"))
        assertTrue(armed.optBoolean("invocationUriBound"))
        assertEquals("scenario-1", armed.optString("scenarioId"))
        assertEquals(transactionId, armed.optString("transactionId"))
        assertEquals(connectionId, armed.optString("connectionId"))
        assertEquals("source-request-1", armed.optString("sourceCaptureRequestId"))
        assertEquals("connection-epoch-1", armed.optString("sourceConnectionEpoch"))
        assertEquals("boot:33", armed.optString("sourceBootEpoch"))
        assertEquals(ownerTarget.sourceNodeId, armed.optString("ownerSourceNodeId"))
        assertEquals("FIELD_ABSENT", armed.optString("ownerSourceNodeIdStatus"))
        val validated = A11yEvidence.validateEntryClickCapture(reqId, transactionId, connectionId)
        assertTrue(validated.optBoolean("ok"))
        assertEquals("source-request-1", validated.optString("sourceCaptureRequestId"))
        assertEquals("connection-epoch-1", validated.optString("sourceConnectionEpoch"))
        assertEquals("boot:33", validated.optString("sourceBootEpoch"))
        assertEquals("FIELD_ABSENT", validated.optString("ownerSourceNodeIdStatus"))
        val captureId = armed.optString("captureId")
        assertNull(A11yEvidence.navigationTargetLease(reqId, armed.getString("ownerLeaseId"), transactionId,
            connectionId, "run-1", "invocation-1", "scenario-other", captureId, sourceIdentity))
        assertTrue(A11yEvidence.navigationTargetLease(reqId, armed.getString("ownerLeaseId"), transactionId,
            connectionId, "run-1", "invocation-1", "scenario-1", captureId, sourceIdentity) != null)

        val dispatchUptimeMs = SystemClock.elapsedRealtime()
        SystemClock.sleep(5L)

        val event = AccessibilityEvent.obtain(AccessibilityEvent.TYPE_VIEW_CLICKED)
        event.eventTime = SystemClock.uptimeMillis()
        event.packageName = "com.samsung.android.oneconnect"
        event.className = "android.view.ViewGroup"
        event.text.add("Home Monitor")
        shadowOf(event).apply {
            setSourceNode(target)
            setWindowId(9)
        }

        val clickEventId = A11yEvidence.captureEntryClickEvent(event, connectionId)
        assertTrue(!clickEventId.isNullOrBlank())
        val dispatchMark = A11yEvidence.markEntryClickDispatch(
            reqId, transactionId, connectionId, dispatchUptimeMs,
        )
        assertTrue(dispatchMark.optBoolean("ok"))
        assertEquals(1, dispatchMark.optInt("eligibleExactClickCount"))
        assertEquals(clickEventId, dispatchMark.optString("clickEventId"))
        assertFalse(dispatchMark.optBoolean("dispatchTargetCurrentnessAccepted"))
        assertFalse(A11yEvidence.markEntryClickDispatch(
            reqId, "wrong-transaction", connectionId, dispatchUptimeMs + 1L,
        ).optBoolean("ok"))
        assertFalse(A11yEvidence.markEntryClickDispatch(
            reqId, transactionId, "wrong-connection", dispatchUptimeMs + 1L,
        ).optBoolean("ok"))
        SystemClock.sleep(2L)
        val currentHierarchy = JSONObject().put("sourceNodeId", "focus-node").put("windowId", 9)
            .put("accessibilityFocused", true).put("text", "Air Care").put("children", org.json.JSONArray())
        assertTrue(A11yEvidence.captureEntryClickPostActionObservation(
            clickEventId = clickEventId!!,
            connectionId = connectionId,
            rootWindowId = 9,
            focusNodeId = null,
            focusNodePath = emptyList(),
            focusWindowId = 9,
            accessibilityFocused = true,
            currentHierarchy = currentHierarchy,
        ))
        assertFalse(A11yEvidence.captureEntryClickPostActionObservation(
            clickEventId = clickEventId,
            connectionId = connectionId,
            rootWindowId = 9,
            focusNodeId = null,
            focusNodePath = emptyList(),
            focusWindowId = 9,
            accessibilityFocused = true,
            currentHierarchy = currentHierarchy,
        ))
        val snapshot = A11yEvidence.entryClickSnapshot(reqId)
        val records = snapshot.optJSONArray("evidenceEvents")
        assertEquals(transactionId, snapshot.optString("transactionId"))
        assertEquals(2, records?.length())
        val payload = records?.optJSONObject(0)?.optJSONObject("payload")
        assertEquals("TYPE_VIEW_CLICKED", payload?.optString("event_type"))
        assertEquals("com.samsung.android.oneconnect", payload?.optString("package"))
        assertEquals("android.view.ViewGroup", payload?.optString("class_name"))
        assertEquals("Home Monitor", payload?.optString("text"))
        assertEquals("FIELD_PRESENT", payload?.optString("source_status"))
        assertEquals("FIELD_ABSENT", payload?.optString("source_node_id_status"))
        assertTrue((payload?.optLong("event_time_elapsed_realtime_ms") ?: -1L) > dispatchUptimeMs)
        assertEquals(captureId, payload?.optString("capture_id"))
        assertEquals(connectionId, payload?.optString("connection_id"))
        // This legacy path marks after event capture: correlation is returned by the mark,
        // while the immutable event retains its capture-time (unmarked) dispatch fields.
        assertTrue(payload?.has("dispatch_uptime_ms") == true)
        assertTrue(payload?.isNull("dispatch_uptime_ms") == true)
        assertEquals("AWAITING_HOST_MARK", payload?.optString("dispatch_correlation_status"))
        assertEquals("EXACT_RETAINED_NODE_REFERENCE", payload?.optString("owner_relation"))
        assertTrue(payload?.optBoolean("owner_exact") == true)
        assertEquals(9, payload?.optInt("owner_window_id"))

        val postPayload = records?.optJSONObject(1)?.optJSONObject("payload")
        assertEquals("ENTRY_CLICK_POST_ACTION_OBSERVED", records?.optJSONObject(1)?.optString("eventType"))
        assertEquals(clickEventId, postPayload?.optString("source_click_event_id"))
        assertEquals(captureId, postPayload?.optString("capture_id"))
        assertEquals(connectionId, postPayload?.optString("connection_id"))
        assertEquals(0, postPayload?.optJSONArray("focus_node_path")?.length())
        assertTrue(postPayload?.optBoolean("accessibility_focused") == true)
        assertEquals("Air Care", postPayload?.optJSONObject("current_hierarchy")?.optString("text"))

        val ended = A11yEvidence.disarmEntryClickCapture(reqId)
        assertTrue(ended.optBoolean("ok"))
        assertEquals(transactionId, ended.optString("transactionId"))
        assertEquals(2, ended.optJSONArray("evidenceEvents")?.length())
        assertFalse(ended.optBoolean("active"))
        event.recycle()

        val lateRequestId = "late-click-${UUID.randomUUID()}"
        val lateTransactionId = "late-transaction-${UUID.randomUUID()}"
        assertTrue(A11yEvidence.armEntryClickCapture(lateRequestId, lateTransactionId, 2000L, connectionId,
            "run-1", "invocation-1", "scenario-1", ownerTarget, sourceIdentity,
            canonicalInvocationUriBound = true).optBoolean("ok"))
        val preDispatchEvent = AccessibilityEvent.obtain(AccessibilityEvent.TYPE_VIEW_CLICKED)
        preDispatchEvent.eventTime = SystemClock.uptimeMillis()
        preDispatchEvent.packageName = "com.samsung.android.oneconnect"
        shadowOf(preDispatchEvent).apply {
            setSourceNode(target)
            setWindowId(9)
        }
        assertFalse(A11yEvidence.captureEntryClickEvent(preDispatchEvent, connectionId).isNullOrBlank())
        val lateMark = A11yEvidence.markNavigationEntryClickDispatch(
            lateRequestId, lateTransactionId, connectionId, SystemClock.elapsedRealtime(),
        )
        assertFalse(lateMark.optBoolean("ok"))
        assertEquals("ENTRY_CLICK_CAPTURE_OWNER_EVENT_PRECEDED_DISPATCH", lateMark.optString("reason"))
        assertTrue(A11yEvidence.disarmEntryClickCapture(lateRequestId).optBoolean("ok"))
        preDispatchEvent.recycle()
    }

    @Test
    fun uptimeEventTimestampIsNormalizedIntoElapsedRealtimeClock() {
        assertEquals(62_000L, A11yEvidence.eventTimeElapsedRealtimeMs(42_000L, 100_000L, 80_000L))
        assertNull(A11yEvidence.eventTimeElapsedRealtimeMs(-1L, 100_000L, 80_000L))
        assertNull(A11yEvidence.eventTimeElapsedRealtimeMs(42_000L, 80_000L, 100_000L))
    }
}
