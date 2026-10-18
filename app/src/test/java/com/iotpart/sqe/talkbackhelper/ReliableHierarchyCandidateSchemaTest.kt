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
        return JSONObject()
            .put("schemaVersion", HierarchyPayloadActions.PAYLOAD_SCHEMA)
            .put("traversalRootRef", ref)
            .put("traversalRootWindowId", root.windowId)
            .put("nodeCount", rawNodeCount)
            .put("windows", windows)
            .put("nodes", nodes)
            .put("traversalCandidates", projection)
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
        assertEquals(legacy.getBoolean("canScrollDown"), projection.getBoolean("canScrollDown"))
        assertEquals("COMPLETE", projection.getJSONObject("completion").getString("status"))
        assertEquals(projection.getJSONArray("candidates").length(), projection.getJSONObject("completion").getInt("candidate_count"))
        assertTrue(ReliableHierarchyCandidateContract.hasValidRootBinding(payloadFor(root)))
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
        val heading = node(
            className = "android.widget.TextView",
            text = "Home Monitor",
            bounds = Rect(40, 80, 700, 150)
        )
        val moreOptions = node(
            className = "android.widget.ImageButton",
            resourceId = "com.samsung.android.oneconnect:id/plugin_more_options",
            description = "More options",
            bounds = Rect(900, 80, 1040, 180),
            clickable = true,
            focusable = true
        )
        fun securityButton(id: String, label: String, top: Int): AccessibilityNodeInfo {
            val labelNode = node(
                className = "android.widget.TextView",
                text = label,
                bounds = Rect(100, top + 10, 900, top + 75)
            )
            val labelWrapper = node(
                className = "android.widget.LinearLayout",
                bounds = Rect(80, top + 5, 940, top + 85),
                children = listOf(labelNode)
            )
            return node(
                className = "android.widget.Button",
                resourceId = "com.samsung.android.oneconnect:id/$id",
                bounds = Rect(60, top, 1020, top + 100),
                clickable = true,
                focusable = true,
                children = listOf(labelWrapper)
            )
        }
        val root = node(children = listOf(
            heading,
            moreOptions,
            securityButton("shmBannerAwayButton", "Arm away", 400),
            securityButton("shmBannerStayButton", "Armed stay", 540),
            securityButton("shmBannerDisarmedButton", "Disarm", 680)
        ))

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
