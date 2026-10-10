package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.util.ReflectionHelpers
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SnapshotRelationshipCacheTest {
    @Test fun repeatedParentIncludingNullLoadsOnce() {
        val cache = SnapshotRelationshipCache<String> { 0 }
        var calls = 0
        repeat(5) { assertEquals("root", cache.parent("leaf") { calls++; "root" }) }
        repeat(5) { assertNull(cache.parent("root") { calls++; null }) }
        assertEquals(2, calls)
        assertEquals(8, cache.parentHits.toInt())
    }
    @Test fun repeatedChildIsScopedByNodeAndIndex() {
        val cache = SnapshotRelationshipCache<String> { 0 }
        var calls = 0
        repeat(4) { assertEquals("a", cache.child("root", 0) { calls++; "a" }) }
        repeat(4) { assertEquals("b", cache.child("root", 1) { calls++; "b" }) }
        assertEquals(2, calls)
    }
    @Test fun structuralGenerationInvalidatesBothMaps() {
        var epoch = 0L
        val cache = SnapshotRelationshipCache<String> { epoch }
        assertEquals("p1", cache.parent("n") { "p1" })
        assertEquals("c1", cache.child("n", 0) { "c1" })
        epoch++
        assertEquals("p2", cache.parent("n") { "p2" })
        assertEquals("c2", cache.child("n", 0) { "c2" })
    }
    @Test fun explicitNewRootInvalidationClearsNegativeResults() {
        val cache = SnapshotRelationshipCache<String> { 0 }
        assertNull(cache.parent("root") { null })
        assertNull(cache.child("root", 0) { null })
        cache.invalidate()
        assertEquals("new-parent", cache.parent("root") { "new-parent" })
        assertEquals("new-child", cache.child("root", 0) { "new-child" })
    }
    @Test fun newCollectionAndRequestNeverShareEntries() {
        val first = SnapshotRelationshipCache<String> { 0 }
        val second = SnapshotRelationshipCache<String> { 0 }
        assertEquals("old", first.parent("n") { "old" })
        assertEquals("new", second.parent("n") { "new" })
        assertEquals("new-child", second.child("n", 0) { "new-child" })
        assertEquals(0, second.parentHits.toInt())
    }
    @Test fun generationChangingDuringReadDoesNotInstallTheValue() {
        var epoch = 0L
        val cache = SnapshotRelationshipCache<String> { epoch }
        assertEquals("old", cache.parent("n") { epoch++; "old" })
        assertEquals("new", cache.parent("n") { "new" })
        assertEquals(0, cache.parentHits.toInt())
    }
    @Test fun equalHashDifferentLogicalNodesDoNotAlias() {
        data class Key(val id: Int) { override fun hashCode() = 1 }
        val cache = SnapshotRelationshipCache<Key> { 0 }
        val one = Key(1); val two = Key(2)
        assertEquals(Key(3), cache.parent(one) { Key(3) })
        assertEquals(Key(4), cache.parent(two) { Key(4) })
        assertEquals(Key(3), cache.parent(Key(1)) { error("repeat must hit") })
    }
    @Test fun generationChangingWhileCopyingAHitForcesAFreshRead() {
        var epoch = 0L
        var changeWhileCopying = false
        val cache = SnapshotRelationshipCache<String>(copy = { value ->
            if (changeWhileCopying) { epoch++; changeWhileCopying = false }
            value
        }) { epoch }
        assertEquals("old", cache.parent("n") { "old" })
        changeWhileCopying = true
        assertEquals("fresh", cache.parent("n") { "fresh" })
        assertEquals(0, cache.parentHits.toInt())
    }
    @Test fun collectionCleanupAlsoRunsOnExceptions() {
        val node = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication()))
        runCatching { SnapshotRelationshipAccess.collect {
            SnapshotRelationshipAccess.parent(node) { node }
            error("collection failed")
        } }
        var reads = 0
        repeat(2) { SnapshotRelationshipAccess.parent(node) { reads++; node } }
        assertEquals(2, reads)
    }
    @Test fun cachedAndroidNodesRetainCallerOwnedCopyIdentity() {
        val node = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication()))
        val parent = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication()))
        SnapshotRelationshipAccess.collect {
            val first = SnapshotRelationshipAccess.parent(node) { parent }
            val second = SnapshotRelationshipAccess.parent(node) { error("must hit") }
            val third = SnapshotRelationshipAccess.parent(node) { error("must hit") }
            assertEquals(first, second)
            assertNotSame(first, second)
            assertNotSame(second, third)
            val childFirst = SnapshotRelationshipAccess.child(parent, 0) { node }
            val childSecond = SnapshotRelationshipAccess.child(parent, 0) { error("must hit") }
            assertEquals(childFirst, childSecond)
            assertNotSame(childFirst, childSecond)
        }
    }
    @Test fun newRootFocusActionAndRefreshInvalidateAnActiveCollection() {
        val node = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication()))
        var reads = 0
        SnapshotRelationshipAccess.collect {
            fun read() = SnapshotRelationshipAccess.parent(node) { reads++; node }
            read(); read()
            assertEquals(1, reads)
            SmartNextPerf.rootBoundary("test_new_root")
            read(); assertEquals(2, reads)
            SmartNextPerf.performAction(node, AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            read(); assertEquals(3, reads)
            SmartNextPerf.refresh(node)
            read(); assertEquals(4, reads)
        }
    }

    private fun fixture(name: String): AccessibilityNodeInfo {
        val json = javaClass.getResourceAsStream("/relationship_cache/$name.json")!!.bufferedReader().use { it.readText() }
        return build(JSONObject(json), null)
    }
    private fun build(json: JSONObject, parent: AccessibilityNodeInfo?): AccessibilityNodeInfo {
        val node = AccessibilityNodeInfo.obtain(View(RuntimeEnvironment.getApplication())).apply {
            packageName = json.optString("packageName")
            className = json.optString("className")
            viewIdResourceName = json.optString("viewIdResourceName").takeIf { it.isNotEmpty() && it != "null" }
            text = json.optString("text").takeIf { it.isNotEmpty() && it != "null" }
            contentDescription = json.optString("contentDescription").takeIf { it.isNotEmpty() && it != "null" }
            isVisibleToUser = json.optBoolean("visibleToUser", true)
            isClickable = json.optBoolean("clickable")
            isFocusable = json.optBoolean("focusable")
            isEnabled = json.optBoolean("enabled", true)
            isSelected = json.optBoolean("selected")
            isCheckable = json.optBoolean("checkable")
            isChecked = json.optBoolean("checked")
            isScrollable = json.optBoolean("scrollable")
            isAccessibilityFocused = json.optBoolean("accessibilityFocused")
            val bounds = json.getJSONObject("boundsInScreen")
            setBoundsInScreen(Rect(bounds.getInt("l"), bounds.getInt("t"), bounds.getInt("r"), bounds.getInt("b")))
        }
        val children = json.optJSONArray("children")
        if (children != null) for (index in 0 until children.length()) {
            val child = build(children.getJSONObject(index), node)
            shadowOf(node).addChild(child)
            assertEquals("fixture parent relationship", node, child.parent)
        }
        // Real accessibility-service snapshots are sealed. The view-built test
        // fixture has no connection; sealed findFocus therefore returns null,
        // while each focus case is supplied explicitly to the production collector.
        ReflectionHelpers.setField(node, "mSealed", true)
        return node
    }
    private fun state(root: AccessibilityNodeInfo, focus: AccessibilityNodeInfo?, cached: Boolean): SmartNextRuntimeState {
        val method = A11yNavigator::class.java.getDeclaredMethod("collectSmartNextRuntimeState", AccessibilityNodeInfo::class.java, AccessibilityNodeInfo::class.java)
        method.isAccessible = true
        return if (cached) method.invoke(A11yNavigator, root, focus) as SmartNextRuntimeState
               else SnapshotRelationshipAccess.withoutCache { method.invoke(A11yNavigator, root, focus) as SmartNextRuntimeState }
    }
    private fun decision(state: SmartNextRuntimeState): NextActionDecision {
        val method = A11yNavigator::class.java.getDeclaredMethod("decideNextAction", SmartNextRuntimeState::class.java)
        method.isAccessible = true
        return method.invoke(A11yNavigator, state) as NextActionDecision
    }
    private fun compare(root: AccessibilityNodeInfo) {
        A11yNavigator.resetFocusHistory()
        val initial = state(root, null, false)
        assertTrue("fixture must exercise candidate selection", initial.normalize.traversalList.isNotEmpty())
        val focusCases = listOf(null) + initial.normalize.traversalList
        for (focus in focusCases) {
            A11yNavigator.resetFocusHistory()
            // The production resolver remembers a repeated container signature.
            // Both variants must start with identical resolver state, as well as
            // the same node graph; invoking old then cached otherwise changes it.
            val signature = ReflectionHelpers.getStaticField<String?>(A11yNavigator::class.java, "lastContainerLikeCurrentSignature")
            val old = state(root, focus, false)
            ReflectionHelpers.setStaticField(A11yNavigator::class.java, "lastContainerLikeCurrentSignature", signature)
            val cached = state(root, focus, true)
            // All candidate metadata, order, aliases, ancestor-derived keys, history,
            // fallback indexes, screen/end inputs and current target are compared.
            assertEquals(old, cached)
            val oldDecision = decision(old)
            val cachedDecision = decision(cached)
            assertEquals(oldDecision, cachedDecision)
            assertEquals(
                A11yNavigationPolicy.decideSmartNextExecution(old, oldDecision.initialTarget, oldDecision.navigationDecision),
                A11yNavigationPolicy.decideSmartNextExecution(cached, cachedDecision.initialTarget, cachedDecision.navigationDecision)
            )
            var postCollectionReads = 0
            repeat(2) { SnapshotRelationshipAccess.parent(root) { postCollectionReads++; null } }
            assertEquals("cache must be released before execution/verification", 2, postCollectionReads)
        }
    }
    @Test fun capturedActiveCandidateOrderTargetEligibilityAndEndInputsAreIdentical() { compare(fixture("family_active")) }
    @Test fun capturedMenuAliasesAndFallbackInputsAreIdentical() { compare(fixture("menu")) }
    @Test fun originalLocalActiveCaptureHasIdenticalSemanticsWhenAvailable() {
        val rootDir = generateSequence(File(System.getProperty("user.dir"))) { it.parentFile }
            .firstOrNull { File(it, "family_care_relationship_rca_20261010/before/before_hierarchy.json").exists() }
        val root = if (rootDir == null) fixture("family_active") else {
            val windows = JSONObject(File(rootDir, "family_care_relationship_rca_20261010/before/before_hierarchy.json").readText()).getJSONArray("windows")
            val window = (0 until windows.length()).map { windows.getJSONObject(it) }.first { it.optBoolean("active") }
            build(window.getJSONObject("root"), null)
        }
        compare(root)
    }
}
