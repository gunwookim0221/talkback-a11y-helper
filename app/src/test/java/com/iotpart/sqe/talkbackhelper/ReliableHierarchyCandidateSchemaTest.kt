package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ReliableHierarchyCandidateSchemaTest {
    private fun node(
        className: String = "android.widget.FrameLayout",
        resourceId: String? = null,
        text: String? = null,
        description: String? = null,
        bounds: Rect = Rect(0, 0, 1080, 2400),
        clickable: Boolean = false,
        focusable: Boolean = false,
        visible: Boolean = true,
        packageName: String = "com.samsung.android.oneconnect",
        children: List<AccessibilityNodeInfo> = emptyList()
    ): AccessibilityNodeInfo = AccessibilityNodeInfo.obtain().apply {
        this.className = className
        this.viewIdResourceName = resourceId
        this.text = text
        this.contentDescription = description
        this.packageName = packageName
        isClickable = clickable
        isFocusable = focusable
        isEnabled = true
        isVisibleToUser = visible
        setBoundsInScreen(bounds)
        children.forEach { shadowOf(this).addChild(it) }
    }

    private fun payloadFor(
        root: AccessibilityNodeInfo,
        ref: String = "windows[0].root",
        windowIds: List<Int> = listOf(root.windowId)
    ): JSONObject {
        val activeIndex = ReliableHierarchyCandidateContract.traversalRootIndex(windowIds, root.windowId)
        val projection = ReliableHierarchyCandidateContract.build(root, root, ref)
        val windows = JSONArray()
        val nodes = JSONArray()
        var rawNodeCount = 0
        windowIds.forEachIndexed { index, windowId ->
            val nodeCount = intArrayOf(0)
            val rawRoot = if (index == activeIndex) {
                A11yNavigator.hierarchyNodeToJson(root, nodeCount, 0, includeCandidateFacts = true)
                    .put("windowId", windowId)
            } else {
                JSONObject().put("windowId", windowId).put("children", JSONArray())
            }
            if (index == activeIndex) rawNodeCount = nodeCount[0]
            windows.put(JSONObject().put("id", windowId).put("root", rawRoot))
            nodes.put(rawRoot)
        }
        require(ref == "windows[$activeIndex].root")
        val rawRoot = windows.getJSONObject(activeIndex).getJSONObject("root")
        val rootDigest = CaptureCanonicalJson.sha256(rawRoot)
        val rootCaptureId = ReliableHierarchyCandidateContract.rootCaptureId(
            "request-test", "epoch-test", 3L, "service-test", 2L, ref, rootDigest
        )
        projection.put("source_root_digest", rootDigest)
        projection.put("rootCaptureId", rootCaptureId)
        projection.put("candidate_digest", CaptureCanonicalJson.sha256(projection))
        return JSONObject()
            .put("reqId", "request-test")
            .put("schemaVersion", HierarchyPayloadActions.PAYLOAD_SCHEMA)
            .put("traversalRootRef", ref)
            .put("traversalRootWindowId", root.windowId)
            .put("nodeCount", rawNodeCount)
            .put("windows", windows)
            .put("nodes", nodes)
            .put("traversalCandidates", projection)
            .put("captureEnvelope", JSONObject()
                .put("schema_version", HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA)
                .put("canonicalization", CaptureCanonicalJson.VERSION)
                .put("request_id", "request-test")
                .put("process_epoch", "epoch-test")
                .put("generation", 3)
                .put("service_instance_id", "service-test")
                .put("capture_sequence", 2)
                .put("root_ref", ref)
                .put("root_digest", rootDigest)
                .put("candidate_digest", projection.getString("candidate_digest")))
    }

    private fun resignCandidate(payload: JSONObject) {
        val projection = payload.getJSONObject("traversalCandidates")
        val digestInput = JSONObject(projection.toString()).apply { remove("candidate_digest") }
        projection.put("candidate_digest", CaptureCanonicalJson.sha256(digestInput))
        payload.getJSONObject("captureEnvelope")
            .put("candidate_digest", projection.getString("candidate_digest"))
    }

    private fun candidateViewIds(nodes: JSONArray): List<String> = (0 until nodes.length()).map {
        nodes.getJSONObject(it).optString("viewIdResourceName")
    }

    private fun assertLegacyCandidateOrder(legacy: JSONArray, projected: JSONArray) {
        val legacyIds = candidateViewIds(legacy)
        val projectedIds = candidateViewIds(projected)
        assertEquals(legacyIds, projectedIds)
        legacyIds.forEach { id -> assertEquals(1, projectedIds.count { it == id }) }
    }

    @Test
    fun v2ProjectionMatchesLegacyDumpTreeCandidateJsonExactly() {
        val label = node(
            className = "android.widget.Button",
            resourceId = "com.example:id/action",
            description = "Start",
            bounds = Rect(80, 100, 420, 180),
            clickable = true,
            focusable = true,
            packageName = "com.example"
        )
        val root = node(children = listOf(label), packageName = "com.example")

        val legacy = A11yNavigator.dumpTreeFlat(root)
        val projection = ReliableHierarchyCandidateContract.build(root, root, "windows[0].root")

        assertEquals("legacy-traversal-candidates.v1", projection.getString("schema_version"))
        assertEquals("legacy-traversal-candidate-contract.v1", projection.getString("candidate_contract_version"))
        assertEquals(A11yNavigator.NAVIGATOR_ALGORITHM_VERSION, projection.getString("algorithmVersion"))
        assertEquals(A11yTraversalAnalyzer.VERSION, projection.getString("analyzerVersion"))
        assertEquals(legacy.getJSONArray("nodes").toString(), projection.getJSONArray("candidates").toString())
        val immutable = ImmutableHierarchyCapture.capture(root)
        val immutableProjection = ImmutableHierarchyCandidateProjection.build(immutable.root)
        assertEquals(legacy.getJSONArray("nodes").toString(), immutableProjection.getJSONArray("nodes").toString())
        assertEquals(legacy.getBoolean("canScrollDown"), projection.getBoolean("canScrollDown"))
        assertEquals("COMPLETE", projection.getJSONObject("completion").getString("status"))
        assertEquals(projection.getJSONArray("candidates").length(), projection.getJSONObject("completion").getInt("candidate_count"))
        assertTrue(ReliableHierarchyCandidateContract.hasValidRootBinding(payloadFor(root)))
    }

    @Test
    fun nestedMultiBranchCaptureHasUniquePreorderIdsAndExactCandidateParity() {
        val branchOne = node(
            className = "android.widget.LinearLayout", clickable = true, focusable = true,
            bounds = Rect(0, 100, 500, 800), children = listOf(
                node(className = "android.widget.Button", resourceId = "pkg:id/first",
                    text = "First", clickable = true, focusable = true,
                    bounds = Rect(20, 120, 220, 220)),
                node(className = "android.widget.Button", resourceId = "pkg:id/second",
                    text = "Second", clickable = true, focusable = true,
                    bounds = Rect(240, 240, 460, 340))
            )
        )
        val branchTwo = node(
            className = "android.widget.LinearLayout", clickable = true, focusable = true,
            bounds = Rect(0, 900, 500, 1600), children = listOf(
                node(className = "android.widget.Button", resourceId = "pkg:id/third",
                    text = "Third", clickable = true, focusable = true,
                    bounds = Rect(20, 920, 220, 1020)),
                node(className = "android.widget.Button", resourceId = "pkg:id/fourth",
                    text = "Fourth", clickable = true, focusable = true,
                    bounds = Rect(240, 1040, 460, 1140))
            )
        )
        val root = node(children = listOf(branchOne, branchTwo))
        val legacy = A11yNavigator.dumpTreeFlat(root)
        val capture = ImmutableHierarchyCapture.capture(root)
        val projection = ImmutableHierarchyCandidateProjection.build(capture.root)
        val ids = mutableListOf<Int>()
        fun collect(n: CapturedHierarchyNode) { ids += n.stableIndex; n.children.forEach(::collect) }
        collect(capture.root)

        assertEquals(capture.nodeCount, ids.size)
        assertEquals((0 until capture.nodeCount).toList(), ids)
        val legacyCandidates = legacy.getJSONArray("nodes")
        val immutableCandidates = projection.getJSONArray("nodes")
        assertEquals(legacyCandidates.toString(), immutableCandidates.toString())
        assertLegacyCandidateOrder(legacyCandidates, immutableCandidates)
        val candidateIds = (0 until immutableCandidates.length()).map {
            immutableCandidates.getJSONObject(it).getString("viewIdResourceName")
        }
        assertEquals(4, candidateIds.size)
        assertEquals(setOf("pkg:id/first", "pkg:id/second", "pkg:id/third", "pkg:id/fourth"),
            candidateIds.toSet())
        assertEquals(candidateIds.size, candidateIds.toSet().size)
    }

    @Test
    fun immutableProjectionDedupesSameBoundsNodesAndKeepsClippedCenterDescendantMetadata() {
        val owner = node(
            className = "android.widget.LinearLayout", resourceId = "pkg:id/owner",
            clickable = true, focusable = true, bounds = Rect(0, 0, 100, 100),
            children = listOf(
                node(className = "android.widget.Button", resourceId = "pkg:id/clipped_center",
                    text = "Center", clickable = true, bounds = Rect(-20, 10, 20, 30)),
                node(className = "android.widget.Button", resourceId = "pkg:id/outside_center",
                    text = "Outside", clickable = true, bounds = Rect(-40, 40, -10, 60)),
                node(className = "android.widget.Button", resourceId = "pkg:id/same_bounds_a",
                    text = "A", clickable = true, focusable = true, bounds = Rect(10, 70, 30, 90)),
                node(className = "android.widget.Button", resourceId = "pkg:id/same_bounds_b",
                    text = "B", clickable = true, focusable = true, bounds = Rect(10, 70, 30, 90))
            )
        )
        val root = node(children = listOf(owner), bounds = Rect(0, 0, 100, 100))
        val legacy = A11yNavigator.dumpTreeFlat(root).getJSONArray("nodes")
        val capture = ImmutableHierarchyCapture.capture(root)
        val projection = ImmutableHierarchyCandidateProjection.build(capture.root).getJSONArray("nodes")
        val rows = (0 until projection.length()).map { projection.getJSONObject(it) }
        val ownerRow = rows.single { it.optString("viewIdResourceName") == "pkg:id/owner" }
        val legacyIds = candidateViewIds(legacy)
        val projectedIds = candidateViewIds(projection)
        fun findCaptured(n: CapturedHierarchyNode, resourceId: String): CapturedHierarchyNode? {
            if (n.resourceId == resourceId) return n
            return n.children.asSequence().mapNotNull { findCaptured(it, resourceId) }.firstOrNull()
        }
        val sameBoundsA = requireNotNull(findCaptured(capture.root, "pkg:id/same_bounds_a"))
        val sameBoundsB = requireNotNull(findCaptured(capture.root, "pkg:id/same_bounds_b"))

        assertEquals("pkg:id/clipped_center", ownerRow.getString("actionableDescendantResourceId"))
        assertEquals(6, capture.nodeCount)
        assertTrue(sameBoundsA.stableIndex != sameBoundsB.stableIndex)
        assertEquals(sameBoundsA.bounds, sameBoundsB.bounds)
        assertEquals(1, rows.count { it.optString("viewIdResourceName") == "pkg:id/same_bounds_a" })
        assertEquals(0, rows.count { it.optString("viewIdResourceName") == "pkg:id/same_bounds_b" })
        assertEquals(
            listOf("pkg:id/owner", "pkg:id/clipped_center", "pkg:id/outside_center", "pkg:id/same_bounds_a"),
            projectedIds,
        )
        assertEquals(legacyIds, projectedIds)
        assertEquals(listOf("pkg:id/same_bounds_a", "pkg:id/same_bounds_b"),
            capture.root.children.single { it.resourceId == "pkg:id/owner" }
                .children.filter { it.resourceId?.startsWith("pkg:id/same_bounds_") == true }
                .map { it.resourceId })
    }

    @Test
    fun rawFactsIncludeApiLevelScreenReaderFocusableAndRangePresenceWithoutChangingLegacyCandidateShape() {
        val node = node(className = "android.widget.SeekBar", focusable = true)
        node.isScreenReaderFocusable = true
        node.rangeInfo = AccessibilityNodeInfo.RangeInfo.obtain(
            AccessibilityNodeInfo.RangeInfo.RANGE_TYPE_FLOAT, 0f, 100f, 25f
        )

        val raw = A11yNavigator.hierarchyNodeToJson(node, intArrayOf(0), 0, includeCandidateFacts = true)
        val legacyRaw = A11yNavigator.hierarchyNodeToJson(node, intArrayOf(0), 0)

        assertTrue(raw.getBoolean("screenReaderFocusable"))
        assertTrue(raw.getBoolean("rangeInfoPresent"))
        assertTrue(raw.has("rangeInfoPresent"))
        val envelope = ReliableHierarchySchemaV2.addRawMetadata(JSONObject(), Build.VERSION.SDK_INT)
        assertEquals(Build.VERSION.SDK_INT, envelope.getInt("platformApiLevel"))
        assertEquals(HierarchyPayloadActions.PAYLOAD_SCHEMA, envelope.getString("schemaVersion"))
        assertTrue(envelope.getJSONObject("nodeMetadataCapabilities").getBoolean("screen_reader_focusable"))
        assertFalse(legacyRaw.has("screenReaderFocusable"))
        assertFalse(legacyRaw.has("rangeInfoPresent"))
    }

    @Test
    fun rawFactsRepresentFalseAndNullRangeValuesExplicitly() {
        val node = node()
        node.isScreenReaderFocusable = false
        val raw = A11yNavigator.hierarchyNodeToJson(node, intArrayOf(0), 0, includeCandidateFacts = true)

        assertFalse(raw.getBoolean("screenReaderFocusable"))
        assertFalse(raw.getBoolean("rangeInfoPresent"))
    }

    @Test
    @Config(sdk = [27])
    fun screenReaderFocusableIsExplicitlyUnsupportedBelowApi28() {
        val raw = A11yNavigator.hierarchyNodeToJson(node(), intArrayOf(0), 0, includeCandidateFacts = true)
        val envelope = ReliableHierarchySchemaV2.addRawMetadata(JSONObject(), Build.VERSION.SDK_INT)

        assertEquals(27, envelope.getInt("platformApiLevel"))
        assertFalse(envelope.getJSONObject("nodeMetadataCapabilities").getBoolean("screen_reader_focusable"))
        assertTrue(raw.has("screenReaderFocusable"))
        assertEquals(JSONObject.NULL, raw.get("screenReaderFocusable"))
        assertFalse(raw.getBoolean("rangeInfoPresent"))
    }

    @Test
    fun invalidMissingAndMismatchedRootBindingsFailClosed() {
        val root = node()
        val valid = payloadFor(root)
        assertTrue(ReliableHierarchyCandidateContract.hasValidRootBinding(valid))

        val missingRef = JSONObject(valid.toString()).apply {
            remove("traversalRootRef")
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(missingRef))

        val unresolved = JSONObject(valid.toString()).apply {
            put("traversalRootRef", "windows[2].root")
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(unresolved))

        val candidateMismatch = JSONObject(valid.toString()).apply {
            getJSONObject("traversalCandidates").put("traversalRootRef", "windows[1].root")
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(candidateMismatch))
    }

    @Test
    fun missingMalformedAndMismatchedCandidateDigestsFailClosed() {
        val root = node()
        val valid = payloadFor(root)
        assertTrue(ReliableHierarchyCandidateContract.hasValidRootBinding(valid))

        val missing = JSONObject(valid.toString()).apply {
            getJSONObject("traversalCandidates").remove("candidate_digest")
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(missing))

        val malformed = JSONObject(valid.toString()).apply {
            getJSONObject("traversalCandidates").put("candidate_digest", "not-a-sha256")
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(malformed))

        val mismatched = JSONObject(valid.toString()).apply {
            getJSONObject("traversalCandidates").put("candidate_digest", "0".repeat(64))
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(mismatched))
    }

    @Test
    fun missingAndMismatchedRootCaptureIdsFailClosedAfterCandidateResigning() {
        val root = node()
        val valid = payloadFor(root)
        assertTrue(ReliableHierarchyCandidateContract.hasValidRootBinding(valid))

        val missing = JSONObject(valid.toString()).apply {
            getJSONObject("traversalCandidates").remove("rootCaptureId")
            resignCandidate(this)
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(missing))

        val mismatched = JSONObject(valid.toString()).apply {
            getJSONObject("traversalCandidates").put("rootCaptureId", "0".repeat(64))
            resignCandidate(this)
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(mismatched))
    }

    @Test
    fun reusedWindowIdWithDifferentRootSubtreeRejectsAfterResigningDigests() {
        val valid = payloadFor(node())
        assertTrue(ReliableHierarchyCandidateContract.hasValidRootBinding(valid))
        val originalRootDigest = valid.getJSONObject("captureEnvelope").getString("root_digest")
        val originalRootCaptureId = valid.getJSONObject("traversalCandidates").getString("rootCaptureId")

        val reusedWindow = JSONObject(valid.toString()).apply {
            val windows = getJSONArray("windows")
            val originalRoot = windows.getJSONObject(0).getJSONObject("root")
            val reusedWindowId = originalRoot.getInt("windowId")
            val changedRoot = JSONObject(originalRoot.toString()).apply {
                put("children", JSONArray().put(JSONObject()
                    .put("className", "android.widget.TextView")
                    .put("viewIdResourceName", "pkg:id/reused_window_child")
                    .put("windowId", reusedWindowId)))
            }
            windows.getJSONObject(0).put("root", changedRoot)
            getJSONArray("nodes").put(0, changedRoot)

            val changedRootDigest = CaptureCanonicalJson.sha256(changedRoot)
            getJSONObject("traversalCandidates").put("source_root_digest", changedRootDigest)
            getJSONObject("captureEnvelope").put("root_digest", changedRootDigest)
            resignCandidate(this)

            assertFalse(originalRootDigest == changedRootDigest)
            val expectedChangedRootCaptureId = ReliableHierarchyCandidateContract.rootCaptureId(
                "request-test", "epoch-test", 3L, "service-test", 2L,
                "windows[0].root", changedRootDigest
            )
            assertFalse(originalRootCaptureId == expectedChangedRootCaptureId)
        }

        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(reusedWindow))
    }

    @Test
    fun differentCapturedRootInstanceCannotProduceBoundCandidates() {
        val serializedRoot = node()
        val candidateRoot = node()

        assertNotSame(serializedRoot, candidateRoot)
        assertThrows(IllegalArgumentException::class.java) {
            ReliableHierarchyCandidateContract.build(candidateRoot, serializedRoot, "windows[0].root")
        }
    }

    @Test
    fun multipleWindowsResolveOnlyTheExactTraversalRootIndex() {
        val root = node()
        val windowIds = listOf(17, root.windowId)
        val rootIndex = ReliableHierarchyCandidateContract.traversalRootIndex(windowIds, root.windowId)
        val payload = payloadFor(root, ref = "windows[$rootIndex].root", windowIds = windowIds)

        assertEquals(1, rootIndex)
        assertTrue(ReliableHierarchyCandidateContract.hasValidRootBinding(payload))
        assertThrows(IllegalArgumentException::class.java) {
            ReliableHierarchyCandidateContract.traversalRootIndex(listOf(root.windowId, root.windowId), root.windowId)
        }
    }

    @Test
    fun v1RawOnlyAndIncompleteCandidateContractsAreNotV2CapabilityEvidence() {
        val root = node()
        val valid = payloadFor(root)

        val v1 = JSONObject(valid.toString()).put("schemaVersion", HierarchyPayloadActions.LEGACY_DIAGNOSTIC_SCHEMA)
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(v1))

        val missingCandidates = JSONObject(valid.toString()).apply { remove("traversalCandidates") }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(missingCandidates))

        val incomplete = JSONObject(valid.toString()).apply {
            getJSONObject("traversalCandidates").getJSONObject("completion").put("complete", false)
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(incomplete))

        val versionMismatch = JSONObject(valid.toString()).apply {
            getJSONObject("traversalCandidates").put("candidate_contract_version", "unknown")
        }
        assertFalse(ReliableHierarchyCandidateContract.hasValidRootBinding(versionMismatch))
    }

    @Test
    fun homeMonitorCandidateFixturePreservesHeadingMoreOptionsAndSecurityControlCandidates() {
        val root = CandidateEquivalenceFixtureSupport.root(
            CandidateEquivalenceFixtureSupport.fixture("home_monitor")
        )

        val projection = ReliableHierarchyCandidateContract.build(root, root, "windows[0].root")
        val candidates = projection.getJSONArray("candidates")
        val byId = (0 until candidates.length()).map { candidates.getJSONObject(it) }
            .associateBy { it.optString("viewIdResourceName") }

        assertTrue(candidates.length() >= 5)
        assertTrue(candidates.toString().contains("Home Monitor"))
        assertTrue(candidates.toString().contains("More options"))
        listOf("shmBannerAwayButton", "shmBannerStayButton", "shmBannerDisarmedButton").forEach { suffix ->
            val candidate = byId.getValue("com.samsung.android.oneconnect:id/$suffix")
            assertTrue(candidate.getBoolean("effectiveClickable"))
        }
        assertEquals("Arm away", byId.getValue("com.samsung.android.oneconnect:id/shmBannerAwayButton").getString("text"))
        assertEquals("Armed stay", byId.getValue("com.samsung.android.oneconnect:id/shmBannerStayButton").getString("text"))
        assertEquals("Disarm", byId.getValue("com.samsung.android.oneconnect:id/shmBannerDisarmedButton").getString("text"))
    }

    @Test
    fun sizeInstrumentationCountsRawTreeCandidatesAndCombinedPayload() {
        val root = node(children = listOf(node(
            className = "android.widget.Button",
            text = "Inspect",
            bounds = Rect(20, 30, 260, 90),
            clickable = true,
            focusable = true
        )))
        val payload = payloadFor(root)
        val projection = payload.getJSONObject("traversalCandidates")
        val rawOnly = JSONObject(payload.toString()).apply { remove("traversalCandidates") }
        val rawBytes = HierarchyPayloadEnvelope.estimatedJsonUtf8Bytes(rawOnly, Int.MAX_VALUE)
        val candidateBytes = HierarchyPayloadEnvelope.estimatedJsonUtf8Bytes(projection, Int.MAX_VALUE)
        val totalBytes = HierarchyPayloadEnvelope.estimatedJsonUtf8Bytes(payload, Int.MAX_VALUE)

        assertEquals(2, rawOnly.getInt("nodeCount"))
        assertTrue(projection.getJSONArray("candidates").length() > 0)
        assertTrue(rawBytes > 0)
        assertTrue(candidateBytes > 0)
        assertTrue(totalBytes > rawBytes)
        assertTrue(totalBytes <= HierarchyPayloadEnvelope.MAX_PAYLOAD_BYTES)
    }
}


@RunWith(RobolectricTestRunner::class)
class CaptureCanonicalJsonTest {
    @Test
    fun v1CanonicalJsonAndSha256MatchPythonGoldenVector() {
        val value = JSONObject()
            .put("z", "é/😀")
            .put("a", Long.MIN_VALUE)
            .put("A", "\u007f\n")
        assertEquals(
            """{"A":"\u007f\n","a":-9223372036854775808,"z":"\u00e9/\ud83d\ude00"}""",
            CaptureCanonicalJson.canonical(value),
        )
        assertEquals(
            "97f5f3ff991358c6eed142b77437d1c6989edb9044a442ab21a04b9cd8d80045",
            CaptureCanonicalJson.sha256(value),
        )
    }

    @Test
    fun canonicalJsonRejectsFloatingNumbersAndUnpairedSurrogates() {
        assertThrows(IllegalStateException::class.java) {
            CaptureCanonicalJson.canonical(JSONObject().put("bad", 1.5))
        }
        assertThrows(IllegalArgumentException::class.java) {
            CaptureCanonicalJson.canonical("\uD800")
        }
    }
}
