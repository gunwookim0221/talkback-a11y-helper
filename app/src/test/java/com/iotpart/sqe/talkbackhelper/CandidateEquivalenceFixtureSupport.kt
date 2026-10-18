package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import org.robolectric.Shadows.shadowOf
import java.security.MessageDigest

/** Shared fixed-input loader used by Kotlin's legacy oracle and v2 pair generator. */
internal object CandidateEquivalenceFixtureSupport {
    private const val RESOURCE = "/candidate_equivalence/inputs.json"

    fun inputManifestSha256(): String {
        val stream = requireNotNull(javaClass.getResourceAsStream(RESOURCE)) {
            "C4_INPUT_FIXTURE_RESOURCE_MISSING:$RESOURCE"
        }
        return sha256(stream.use { it.readBytes() })
    }

    fun manifest(): JSONObject {
        val stream = requireNotNull(javaClass.getResourceAsStream(RESOURCE)) {
            "C4_INPUT_FIXTURE_RESOURCE_MISSING:$RESOURCE"
        }
        return stream.bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
    }

    fun fixtures(): List<JSONObject> {
        val values = manifest().getJSONArray("fixtures")
        return (0 until values.length()).map { values.getJSONObject(it) }
    }

    fun fixture(fixtureId: String): JSONObject = fixtures().single { it.getString("fixture_id") == fixtureId }

    fun root(fixture: JSONObject): AccessibilityNodeInfo = buildNode(fixture.getJSONObject("root"))

    fun buildNode(spec: JSONObject): AccessibilityNodeInfo {
        val bounds = spec.optJSONArray("bounds")?.let { values ->
            require(values.length() == 4) { "C4_INPUT_BOUNDS_INVALID" }
            Rect(values.getInt(0), values.getInt(1), values.getInt(2), values.getInt(3))
        } ?: Rect(0, 0, 1080, 2400)
        val node = AccessibilityNodeInfo.obtain().apply {
            className = spec.optString("className", "android.widget.FrameLayout")
            viewIdResourceName = spec.optNullableString("resourceId")
            text = spec.optNullableString("text")
            contentDescription = spec.optNullableString("description")
            packageName = spec.optString("packageName", "com.samsung.android.oneconnect")
            isClickable = spec.optBoolean("clickable", false)
            isFocusable = spec.optBoolean("focusable", false)
            isEnabled = spec.optBoolean("enabled", true)
            isVisibleToUser = spec.optBoolean("visible", true)
            isFocused = spec.optBoolean("focused", false)
            isAccessibilityFocused = spec.optBoolean("accessibilityFocused", false)
            isSelected = spec.optBoolean("selected", false)
            isScrollable = spec.optBoolean("scrollable", false)
            setBoundsInScreen(bounds)

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && spec.has("screenReaderFocusable")) {
                isScreenReaderFocusable = spec.getBoolean("screenReaderFocusable")
            }
            if (spec.has("rangeInfo")) {
                val range = spec.getJSONObject("rangeInfo")
                rangeInfo = AccessibilityNodeInfo.RangeInfo.obtain(
                    range.optInt("type", AccessibilityNodeInfo.RangeInfo.RANGE_TYPE_FLOAT),
                    range.getDouble("min").toFloat(),
                    range.getDouble("max").toFloat(),
                    range.getDouble("current").toFloat()
                )
            }
            spec.optJSONArray("actions")?.let { actions ->
                for (index in 0 until actions.length()) {
                    addAction(AccessibilityNodeInfo.AccessibilityAction(actions.getInt(index), null))
                }
            }
        }

        spec.optJSONArray("children")?.let { children ->
            for (index in 0 until children.length()) {
                shadowOf(node).addChild(buildNode(children.getJSONObject(index)))
            }
        }
        return node
    }

    fun reliablePayload(root: AccessibilityNodeInfo, requestId: String): JSONObject {
        val rootIndex = ReliableHierarchyCandidateContract.traversalRootIndex(
            listOf(root.windowId), root.windowId
        )
        val rootRef = "windows[$rootIndex].root"
        val projection = ReliableHierarchyCandidateContract.build(root, root, rootRef)
        val nodeCount = intArrayOf(0)
        val rawRoot = A11yNavigator.hierarchyNodeToJson(root, nodeCount, 0, includeCandidateFacts = true)
            .put("windowId", root.windowId)
        val rootBounds = Rect().also(root::getBoundsInScreen)
        val windows = JSONArray().put(JSONObject()
            .put("order", 0)
            .put("id", root.windowId)
            .put("type", JSONObject.NULL)
            .put("layer", JSONObject.NULL)
            .put("title", JSONObject.NULL)
            .put("active", true)
            .put("focused", false)
            .put("boundsInScreen", A11yNavigator.rectToJson(rootBounds))
            .put("root", rawRoot))
        val roots = JSONArray().put(rawRoot)
        val payload = ReliableHierarchySchemaV2.addRawMetadata(JSONObject(), Build.VERSION.SDK_INT)
            .put("reqId", requestId)
            .put("success", true)
            .put("source", "accessibility_service_windows")
            .put("windowCoverage", "active_root_fallback")
            .put("traversalRootRef", rootRef)
            .put("traversalRootWindowId", root.windowId)
            .put("nodeCount", nodeCount[0])
            .put("windows", windows)
            .put("nodes", roots)
            .put("traversalCandidates", projection)
        require(ReliableHierarchyCandidateContract.hasValidRootBinding(payload)) {
            "C4_ROOT_BINDING_INVALID:$requestId"
        }
        return payload
    }

    fun inputDigest(fixture: JSONObject): String {
        // Bind a fixture ID to the exact checked-in common input manifest bytes.
        require(fixtures().any { it.getString("fixture_id") == fixture.getString("fixture_id") }) {
            "C4_INPUT_FIXTURE_NOT_IN_MANIFEST"
        }
        return inputManifestSha256()
    }

    fun canonicalJson(value: Any?): String = when (value) {
        null, JSONObject.NULL -> "null"
        is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") { key ->
            "${JSONObject.quote(key)}:${canonicalJson(value.get(key))}"
        }
        is JSONArray -> (0 until value.length()).joinToString(",", "[", "]") { index ->
            canonicalJson(value.get(index))
        }
        is String -> JSONObject.quote(value)
        is Number, is Boolean -> value.toString()
        else -> error("C4_INPUT_VALUE_UNSUPPORTED:${value::class.java.name}")
    }

    fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }

    private fun sha256(value: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(value)
        .joinToString("") { "%02x".format(it) }

    private fun JSONObject.optNullableString(key: String): String? =
        if (!has(key) || isNull(key)) null else getString(key)
}
