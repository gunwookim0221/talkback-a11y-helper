package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.util.IdentityHashMap

/**
 * Same-tree differential oracle for the eager collector in cd5e8048.
 * The reference deliberately evaluates metadata for rejected nodes too. Shared
 * helpers below are unchanged by the experiment; the decision point and recursive
 * walk are independent. These fixtures do not claim cross-date device equivalence.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class FamilyCareMetadataEquivalenceTest {
    private fun node(
        rid: String? = null,
        text: String? = null,
        desc: String? = null,
        bounds: Rect = Rect(0, 0, 1080, 2640),
        clickable: Boolean = false,
        focusable: Boolean = false,
        visible: Boolean = true,
        className: String = "android.widget.LinearLayout",
        children: List<AccessibilityNodeInfo> = emptyList()
    ): AccessibilityNodeInfo = AccessibilityNodeInfo.obtain().apply {
        packageName = "com.samsung.android.oneconnect"
        viewIdResourceName = rid
        this.text = text
        contentDescription = desc
        this.className = className
        isClickable = clickable
        isFocusable = focusable
        isVisibleToUser = visible
        isEnabled = true
        setBoundsInScreen(bounds)
        children.forEach { shadowOf(this).addChild(it) }
    }

    private fun eagerBaseline(
        current: AccessibilityNodeInfo,
        ancestor: AccessibilityNodeInfo?,
        sink: MutableList<A11yTraversalAnalyzer.FocusedNode>,
        emitted: MutableMap<AccessibilityNodeInfo, Boolean>
    ) {
        if (!current.isVisibleToUser || emitted.containsKey(current)) return
        val container = A11yTraversalAnalyzer.isFocusContainer(current)
        // Original evaluation order: metadata before any eligibility branch.
        val metadata = A11yTraversalAnalyzer.collectActionableDescendantMetadata(current)
        val topLevelText = ancestor == null && A11yTraversalAnalyzer.hasAnyText(current)
        val promotedText = !container && !topLevelText &&
            A11yTraversalAnalyzer.evaluateOneConnectStaticTextPromotion(current, ancestor).accepted
        if (container || topLevelText || promotedText) {
            val merged = if (container) A11yTraversalAnalyzer.collectMergedTextFromContainer(current) else emptyList()
            sink += A11yTraversalAnalyzer.FocusedNode(
                node = current,
                text = if (container) merged.firstOrNull() else current.text?.toString(),
                contentDescription = if (container) merged.getOrNull(1) else current.contentDescription?.toString(),
                mergedLabel = if (container) merged.firstOrNull() else null,
                hasClickableDescendant = metadata.hasClickableDescendant,
                hasFocusableDescendant = metadata.hasFocusableDescendant,
                effectiveClickable = current.isClickable || metadata.hasClickableDescendant,
                actionableDescendantResourceId = metadata.actionableDescendantResourceId,
                actionableDescendantClassName = metadata.actionableDescendantClassName,
                actionableDescendantContentDescription = metadata.actionableDescendantContentDescription
            )
            emitted[current] = true
        }
        val className = current.className?.toString().orEmpty()
        val viewId = current.viewIdResourceName.orEmpty()
        val structural = className.contains("GridView", true) || className.contains("RecyclerView", true) ||
            className.contains("ScrollView", true) || className.contains("ViewPager", true) ||
            viewId.contains("recycler_view", true)
        val nextAncestor = if (container && !structural) current else ancestor
        for (index in 0 until current.childCount) {
            current.getChild(index)?.let { eagerBaseline(it, nextAncestor, sink, emitted) }
        }
        // The adjustable projection was not changed. Exercise the same unchanged
        // implementation after the independent reference recursion.
        A11yTraversalAnalyzer::class.java.getDeclaredMethod(
            "projectNestedAdjustableDescendants", AccessibilityNodeInfo::class.java,
            List::class.java, Map::class.java
        ).apply { isAccessible = true }.invoke(A11yTraversalAnalyzer, current, sink, emitted)
    }

    private fun signature(candidate: A11yTraversalAnalyzer.FocusedNode): List<Any?> = listOf(
        candidate.node.viewIdResourceName,
        Rect().also { candidate.node.getBoundsInScreen(it) }.toShortString(),
        candidate.node.className?.toString(), candidate.text, candidate.contentDescription,
        candidate.mergedLabel, candidate.hasClickableDescendant, candidate.hasFocusableDescendant,
        candidate.effectiveClickable, candidate.actionableDescendantResourceId,
        candidate.actionableDescendantClassName, candidate.actionableDescendantContentDescription
    )

    private fun assertEquivalent(root: AccessibilityNodeInfo): List<A11yTraversalAnalyzer.FocusedNode> {
        val reference = mutableListOf<A11yTraversalAnalyzer.FocusedNode>()
        eagerBaseline(root, null, reference, IdentityHashMap())
        val optimized = mutableListOf<A11yTraversalAnalyzer.FocusedNode>()
        A11yTraversalAnalyzer.collectFocusableNodes(root, null, optimized)
        assertEquals(reference.map(::signature), optimized.map(::signature))
        assertEquals(
            reference.filterNot(A11yTraversalAnalyzer::shouldExcludeAsEmptyShell).map(::signature),
            optimized.filterNot(A11yTraversalAnalyzer::shouldExcludeAsEmptyShell).map(::signature)
        )
        return optimized
    }

    @Test
    fun activeFamilyCareClockAndClickableDescendantPreserveBaselineCandidates() {
        val time = node(text = "8:40", bounds = Rect(657, 1246, 824, 1354), className = "android.widget.TextView")
        val info = node(rid = "com.samsung.android.plugin.care:id/device_info", desc = "정보 보기",
            bounds = Rect(936, 1368, 978, 1410), clickable = true, focusable = true, className = "android.widget.ImageButton")
        val card = node(rid = "com.samsung.android.plugin.care:id/last_activity_layout",
            bounds = Rect(552, 1191, 996, 1423), focusable = true, children = listOf(time, info))
        val candidates = assertEquivalent(node(children = listOf(card)))
        val parent = candidates.single { it.node.viewIdResourceName?.endsWith("last_activity_layout") == true }
        assertTrue(parent.hasClickableDescendant)
        assertTrue(parent.hasFocusableDescendant)
        assertTrue(parent.effectiveClickable)
        assertEquals(info.viewIdResourceName, parent.actionableDescendantResourceId)
        assertEquals("정보 보기", parent.actionableDescendantContentDescription)
        assertTrue(candidates.any { it.text == "8:40" })
        assertTrue(candidates.any { it.node.viewIdResourceName == info.viewIdResourceName })
    }

    @Test
    fun inactiveFamilyCareShapeChangesCandidatesWithoutChangingCollectorSemantics() {
        val waiting = node(text = "대기 중", bounds = Rect(552, 1301, 730, 1406), className = "android.widget.TextView")
        val card = node(rid = "com.samsung.android.plugin.care:id/last_activity_layout",
            bounds = Rect(552, 1246, 996, 1475), focusable = true, children = listOf(waiting))
        val candidates = assertEquivalent(node(children = listOf(card)))
        assertTrue(candidates.any { it.text == "대기 중" })
        assertFalse(candidates.any { it.text == "8:40" })
        assertFalse(candidates.first { it.node.viewIdResourceName == card.viewIdResourceName }.effectiveClickable)
    }

    @Test
    fun zeroStepsLeafAndMergedParentBothRemainCandidates() {
        val steps = node(text = "0 걸음", bounds = Rect(84, 1254, 660, 1362), className = "android.widget.TextView")
        val goal = node(text = "/ 6000 걸음", bounds = Rect(660, 1254, 996, 1362), className = "android.widget.TextView")
        val parent = node(bounds = Rect(84, 1254, 996, 1417), focusable = true, children = listOf(steps, goal))
        val candidates = assertEquivalent(node(children = listOf(parent)))
        assertTrue(candidates.any { it.text == "0 걸음" && it.mergedLabel == null })
        assertTrue(candidates.any { it.mergedLabel?.contains("6000 걸음") == true })
    }

    @Test
    fun rejectedStructuralWrappersStillRecurseIntoActionableDescendants() {
        val button = node(rid = "care:id/device_info", desc = "정보 보기", clickable = true,
            className = "android.widget.ImageButton")
        val wrapper = node(children = listOf(node(children = listOf(button))))
        val candidates = assertEquivalent(wrapper)
        assertEquals(listOf(button.viewIdResourceName), candidates.map { it.node.viewIdResourceName })
        val stats = A11yTraversalAnalyzer.FocusNodeCollectionStats()
        A11yTraversalAnalyzer.collectFocusableNodes(wrapper, null, mutableListOf(), stats = stats)
        assertEquals(3, stats.visibleNodeVisits)
        assertEquals(1, stats.descendantMetadataScans)
    }

    @Test
    fun invisibleChildAndDisabledActionableChildPreserveMetadataRanking() {
        val invisible = node(rid = "hidden", desc = "숨김", clickable = true, visible = false)
        val disabled = node(rid = "disabled", desc = "사용 불가", clickable = true).apply { isEnabled = false }
        val enabled = node(rid = "enabled", desc = "정보 보기", clickable = true, className = "android.widget.ImageButton")
        val parent = node(rid = "parent", focusable = true, children = listOf(invisible, disabled, enabled))
        val candidates = assertEquivalent(node(children = listOf(parent)))
        assertEquals("enabled", candidates.first { it.node.viewIdResourceName == "parent" }.actionableDescendantResourceId)
        assertFalse(candidates.any { it.node.viewIdResourceName == "hidden" })
    }
}
