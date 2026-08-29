package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class A11yTraversalAnalyzerTest {

    private class ComparatorNode(
        val name: String,
        val bounds: Rect,
        var parent: ComparatorNode? = null
    )

    private fun comparatorFor(
        order: Map<String, Long> = emptyMap(),
        yBucketSize: Int = 5
    ): Comparator<ComparatorNode> = Comparator { left, right ->
        A11yTraversalAnalyzer.compareByContainmentAndPosition(
            left = left,
            right = right,
            parentOf = { it.parent },
            boundsOf = { it.bounds },
            yBucketSize = yBucketSize,
            tieBreakerOf = { order[it.name] ?: it.name.hashCode().toLong() }
        )
    }

    private fun sign(value: Int): Int = when {
        value < 0 -> -1
        value > 0 -> 1
        else -> 0
    }

    private fun legacyComparator(left: ComparatorNode, right: ComparatorNode, yBucketSize: Int): Int {
        if (left === right) return 0
        if (isLegacyAncestor(left, right)) return -1
        if (isLegacyAncestor(right, left)) return 1

        val leftRect = left.bounds
        val rightRect = right.bounds
        val leftCenterY = (leftRect.top + leftRect.bottom) / 2
        val rightCenterY = (rightRect.top + rightRect.bottom) / 2
        if (kotlin.math.abs(leftCenterY - rightCenterY) < yBucketSize) {
            if (leftRect.bottom <= rightRect.top) return -1
            if (rightRect.bottom <= leftRect.top) return 1
        }
        val leftBucket = leftCenterY / yBucketSize
        val rightBucket = rightCenterY / yBucketSize
        if (leftBucket != rightBucket) return leftBucket - rightBucket
        if (leftRect.left != rightRect.left) return leftRect.left - rightRect.left
        return leftRect.top - rightRect.top
    }

    private fun isLegacyAncestor(ancestor: ComparatorNode, descendant: ComparatorNode): Boolean {
        var current = descendant.parent
        while (current != null) {
            if (current === ancestor) return true
            current = current.parent
        }
        return false
    }

    @Test
    fun version_isUpdated() {
        assertEquals("1.11.0", A11yTraversalAnalyzer.VERSION)
    }

    @Test
    fun shouldPromoteOneConnectStaticTextCandidate_acceptsReadableTextBlock() {
        val decision = A11yTraversalAnalyzer.shouldPromoteOneConnectStaticTextCandidate(
            packageName = "com.samsung.android.oneconnect",
            ancestorPackageName = "com.samsung.android.oneconnect",
            className = "android.widget.TextView",
            readableText = "Preheat the oven and mix the ingredients.",
            clickable = false,
            focusable = false,
            screenReaderFocusable = false,
            enabled = true,
            interactiveDescendantExists = false,
            bounds = Rect(80, 980, 960, 1120),
            ancestorBounds = Rect(0, 300, 1080, 2200),
            rootBounds = Rect(0, 0, 1080, 2400)
        )

        assertTrue(decision.accepted)
        assertEquals("oneconnect_readable_static_text", decision.reasonCode)
    }

    @Test
    fun shouldPromoteOneConnectStaticTextCandidate_rejectsInteractiveText() {
        val decision = A11yTraversalAnalyzer.shouldPromoteOneConnectStaticTextCandidate(
            packageName = "com.samsung.android.oneconnect",
            ancestorPackageName = "com.samsung.android.oneconnect",
            className = "android.widget.TextView",
            readableText = "Step 1",
            clickable = false,
            focusable = true,
            screenReaderFocusable = false,
            enabled = true,
            interactiveDescendantExists = false,
            bounds = Rect(80, 980, 960, 1080),
            ancestorBounds = Rect(0, 300, 1080, 2200),
            rootBounds = Rect(0, 0, 1080, 2400)
        )

        assertFalse(decision.accepted)
        assertEquals("interactive_text", decision.reasonCode)
    }

    @Test
    fun shouldRetainUnlabeledAdjustableTarget_acceptsVisibleEnabledFocusableSeekBar() {
        val retained = A11yTraversalAnalyzer.shouldRetainUnlabeledAdjustableTarget(
            visible = true,
            enabled = true,
            focusable = true,
            clickable = true,
            className = "android.widget.SeekBar",
            hasRangeInfo = true,
            hasSetProgressAction = false,
            bounds = Rect(204, 2173, 876, 2224)
        )

        assertTrue(retained)
    }

    @Test
    fun shouldRetainUnlabeledAdjustableTarget_acceptsGenericRangeControlWithoutLabelOrResourceId() {
        val retained = A11yTraversalAnalyzer.shouldRetainUnlabeledAdjustableTarget(
            visible = true,
            enabled = true,
            focusable = true,
            clickable = false,
            className = "com.example.CustomControl",
            hasRangeInfo = true,
            hasSetProgressAction = false,
            bounds = Rect(10, 100, 300, 160)
        )

        assertTrue(retained)
    }

    @Test
    fun shouldRetainUnlabeledAdjustableTarget_rejectsGenericFocusableViewWithoutAdjustableSemantics() {
        val retained = A11yTraversalAnalyzer.shouldRetainUnlabeledAdjustableTarget(
            visible = true,
            enabled = true,
            focusable = true,
            clickable = true,
            className = "android.view.View",
            hasRangeInfo = false,
            hasSetProgressAction = false,
            bounds = Rect(10, 100, 300, 160)
        )

        assertFalse(retained)
    }

    @Test
    fun shouldRetainUnlabeledAdjustableTarget_rejectsClassOnlySeekBar() {
        val retained = A11yTraversalAnalyzer.shouldRetainUnlabeledAdjustableTarget(
            visible = true,
            enabled = true,
            focusable = true,
            clickable = true,
            className = "android.widget.SeekBar",
            hasRangeInfo = false,
            hasSetProgressAction = false,
            bounds = Rect(204, 2173, 876, 2224)
        )

        assertFalse(retained)
    }

    @Test
    fun shouldRetainUnlabeledAdjustableTarget_rejectsInvisibleDisabledAndInvalidTargets() {
        fun retained(
            visible: Boolean = true,
            enabled: Boolean = true,
            focusable: Boolean = true,
            bounds: Rect = Rect(10, 100, 300, 160)
        ): Boolean = A11yTraversalAnalyzer.shouldRetainUnlabeledAdjustableTarget(
            visible = visible,
            enabled = enabled,
            focusable = focusable,
            clickable = true,
            className = "android.widget.SeekBar",
            hasRangeInfo = false,
            hasSetProgressAction = false,
            bounds = bounds
        )

        assertFalse(retained(visible = false))
        assertFalse(retained(enabled = false))
        assertFalse(retained(focusable = false))
        assertFalse(retained(bounds = Rect()))
    }

    @Test
    fun shouldProjectNestedAdjustableDescendant_acceptsStrongUnlabeledControlInContentScope() {
        val projected = A11yTraversalAnalyzer.shouldProjectNestedAdjustableDescendant(
            visible = true,
            enabled = true,
            focusable = true,
            clickable = true,
            className = "android.widget.SeekBar",
            hasRangeInfo = true,
            hasSetProgressAction = false,
            bounds = Rect(204, 2173, 876, 2224),
            hasReadableLabel = false,
            withinContentScope = true,
            alreadyRepresented = false
        )

        assertTrue(projected)
    }

    @Test
    fun shouldProjectNestedAdjustableDescendant_rejectsWeakOrOutOfScopeControls() {
        fun projected(
            visible: Boolean = true,
            enabled: Boolean = true,
            focusable: Boolean = true,
            hasRangeInfo: Boolean = true,
            hasSetProgressAction: Boolean = false,
            hasReadableLabel: Boolean = false,
            withinContentScope: Boolean = true,
            alreadyRepresented: Boolean = false,
            bounds: Rect = Rect(204, 2173, 876, 2224)
        ): Boolean = A11yTraversalAnalyzer.shouldProjectNestedAdjustableDescendant(
            visible = visible,
            enabled = enabled,
            focusable = focusable,
            clickable = true,
            className = "android.widget.SeekBar",
            hasRangeInfo = hasRangeInfo,
            hasSetProgressAction = hasSetProgressAction,
            bounds = bounds,
            hasReadableLabel = hasReadableLabel,
            withinContentScope = withinContentScope,
            alreadyRepresented = alreadyRepresented
        )

        assertFalse(projected(hasReadableLabel = true))
        assertFalse(projected(withinContentScope = false))
        assertFalse(projected(alreadyRepresented = true))
        assertFalse(projected(visible = false))
        assertFalse(projected(enabled = false))
        assertFalse(projected(focusable = false))
        assertFalse(projected(hasRangeInfo = false, hasSetProgressAction = false))
        assertFalse(projected(bounds = Rect()))
    }

    @Test
    fun collectActionableDescendantMetadata_preservesClickableDescendantInfo() {
        data class Node(
            val resourceId: String?,
            val className: String?,
            val contentDescription: String?,
            val clickable: Boolean,
            val focusable: Boolean,
            val enabled: Boolean = true,
            val visible: Boolean = true,
            val children: MutableList<Node> = mutableListOf()
        )

        val clickableChild = Node(
            resourceId = "com.samsung.android.oneconnect:id/settings_image",
            className = "android.widget.ImageButton",
            contentDescription = "Settings",
            clickable = true,
            focusable = true
        )
        val parent = Node(
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.FrameLayout",
            contentDescription = null,
            clickable = false,
            focusable = true,
            children = mutableListOf(clickableChild)
        )

        val metadata = A11yTraversalAnalyzer.collectActionableDescendantMetadata(
            container = parent,
            childCountOf = { it.children.size },
            childAt = { node, index -> node.children.getOrNull(index) },
            isVisible = { it.visible },
            isClickable = { it.clickable },
            isFocusable = { it.focusable },
            isEnabled = { it.enabled },
            resourceIdOf = { it.resourceId },
            classNameOf = { it.className },
            contentDescriptionOf = { it.contentDescription }
        )

        assertTrue(metadata.hasClickableDescendant)
        assertTrue(metadata.hasFocusableDescendant)
        assertEquals("com.samsung.android.oneconnect:id/settings_image", metadata.actionableDescendantResourceId)
        assertEquals("android.widget.ImageButton", metadata.actionableDescendantClassName)
        assertEquals("Settings", metadata.actionableDescendantContentDescription)
    }

    @Test
    fun collectActionableDescendantMetadata_prefersLabeledButtonLikeClickableChild() {
        data class Node(
            val resourceId: String?,
            val className: String?,
            val contentDescription: String?,
            val text: String?,
            val clickable: Boolean,
            val focusable: Boolean,
            val enabled: Boolean = true,
            val visible: Boolean = true,
            val children: MutableList<Node> = mutableListOf()
        )

        val plainClickable = Node(
            resourceId = "com.example:id/plain_clickable",
            className = "android.view.View",
            contentDescription = null,
            text = null,
            clickable = true,
            focusable = true
        )
        val imageButton = Node(
            resourceId = "com.example:id/settings_image",
            className = "android.widget.ImageButton",
            contentDescription = "Settings",
            text = null,
            clickable = true,
            focusable = true
        )
        val parent = Node(
            resourceId = "com.example:id/container",
            className = "android.widget.RelativeLayout",
            contentDescription = null,
            text = null,
            clickable = false,
            focusable = true,
            children = mutableListOf(plainClickable, imageButton)
        )

        val metadata = A11yTraversalAnalyzer.collectActionableDescendantMetadata(
            container = parent,
            childCountOf = { it.children.size },
            childAt = { node, index -> node.children.getOrNull(index) },
            isVisible = { it.visible },
            isClickable = { it.clickable },
            isFocusable = { it.focusable },
            isEnabled = { it.enabled },
            resourceIdOf = { it.resourceId },
            classNameOf = { it.className },
            contentDescriptionOf = { it.contentDescription },
            textOf = { it.text }
        )

        assertTrue(metadata.hasClickableDescendant)
        assertEquals("com.example:id/settings_image", metadata.actionableDescendantResourceId)
        assertEquals("android.widget.ImageButton", metadata.actionableDescendantClassName)
        assertEquals("Settings", metadata.actionableDescendantContentDescription)
    }

    @Test
    fun selectPostScrollContinuationCandidate_acceptsNonNegativeIndex() {
        val analysis = A11yTraversalAnalyzer.analyzePostScrollState(
            treeChanged = true,
            anchorMaintained = true,
            newlyExposedCandidateExists = true
        )
        val result = A11yTraversalAnalyzer.selectPostScrollContinuationCandidate(3, analysis)

        assertEquals(3, result.index)
        assertTrue(result.accepted)
        assertEquals("accepted:newly_revealed_after_scroll", result.reasonCode)
    }

    @Test
    fun selectPostScrollContinuationCandidate_rejectsNegativeIndex() {
        val analysis = A11yTraversalAnalyzer.analyzePostScrollState(
            treeChanged = false,
            anchorMaintained = false,
            newlyExposedCandidateExists = false
        )
        val result = A11yTraversalAnalyzer.selectPostScrollContinuationCandidate(-1, analysis)

        assertEquals(-1, result.index)
        assertFalse(result.accepted)
        assertEquals("rejected:no_progress_after_scroll", result.reasonCode)
    }

    @Test
    fun comparator_preservesSpatialOrderingForSimpleSiblings() {
        val upper = ComparatorNode("upper", Rect(0, 0, 100, 40))
        val lower = ComparatorNode("lower", Rect(0, 80, 100, 120))
        val comparator = comparatorFor(mapOf("upper" to 1L, "lower" to 2L))

        assertTrue(comparator.compare(upper, lower) < 0)
        assertTrue(comparator.compare(lower, upper) > 0)
    }

    @Test
    fun comparator_placesParentBeforeChildAndKeepsNestedHierarchyAcyclic() {
        val root = ComparatorNode("root", Rect(0, 0, 1080, 2400))
        val parent = ComparatorNode("parent", Rect(500, 500, 900, 900), root)
        val child = ComparatorNode("child", Rect(10, 10, 40, 40), parent)
        val grandchild = ComparatorNode("grandchild", Rect(20, 20, 30, 30), child)
        val comparator = comparatorFor(
            mapOf("root" to 0L, "parent" to 1L, "child" to 2L, "grandchild" to 3L)
        )

        assertTrue(comparator.compare(root, parent) < 0)
        assertTrue(comparator.compare(parent, child) < 0)
        assertTrue(comparator.compare(child, grandchild) < 0)
        assertTrue(comparator.compare(root, grandchild) < 0)
    }

    @Test
    fun comparator_handlesOverlappingAndIdenticalCoordinatesWithDeterministicTieBreakers() {
        val first = ComparatorNode("first", Rect(100, 100, 400, 400))
        val second = ComparatorNode("second", Rect(100, 100, 400, 400))
        val overlapping = ComparatorNode("overlapping", Rect(200, 200, 500, 500))
        val comparator = comparatorFor(
            mapOf("first" to 1L, "second" to 2L, "overlapping" to 3L)
        )

        assertTrue(comparator.compare(first, second) < 0)
        assertTrue(comparator.compare(second, first) > 0)
        assertTrue(comparator.compare(first, overlapping) < 0)
        assertEquals(0, comparator.compare(first, first))
    }

    @Test
    fun comparator_handlesIncompleteBoundsAndParentCyclesWithoutHanging() {
        val invalid = ComparatorNode("invalid", Rect())
        val partial = ComparatorNode("partial", Rect(0, 0, 0, 20))
        val cyclicA = ComparatorNode("cyclicA", Rect(0, 100, 40, 140))
        val cyclicB = ComparatorNode("cyclicB", Rect(0, 150, 40, 190), cyclicA)
        cyclicA.parent = cyclicB
        val comparator = comparatorFor(
            mapOf("invalid" to 1L, "partial" to 2L, "cyclicA" to 3L, "cyclicB" to 4L)
        )

        val sorted = listOf(cyclicB, invalid, partial, cyclicA).sortedWith(comparator)

        assertEquals(4, sorted.size)
        assertTrue(sorted.map { it.name }.toSet().size == 4)
        assertTrue(comparator.compare(cyclicA, cyclicB) != 0)
    }

    @Test
    fun comparator_rejectsTheFormerMixedAncestrySpatialCycle() {
        val ancestor = ComparatorNode("ancestor", Rect(100, 100, 200, 200))
        val descendant = ComparatorNode("descendant", Rect(0, 0, 50, 50), ancestor)
        val sibling = ComparatorNode("sibling", Rect(50, 50, 100, 100))
        val comparator = comparatorFor(
            mapOf("ancestor" to 1L, "descendant" to 2L, "sibling" to 3L),
            yBucketSize = 100
        )
        val nodes = listOf(ancestor, descendant, sibling)
        val sorted = nodes.sortedWith(comparator)

        for (left in nodes) {
            for (right in nodes) {
                assertEquals(
                    -sign(comparator.compare(right, left)),
                    sign(comparator.compare(left, right))
                )
            }
        }
        for (a in nodes) {
            for (b in nodes) {
                for (c in nodes) {
                    val ab = comparator.compare(a, b)
                    val bc = comparator.compare(b, c)
                    val ac = comparator.compare(a, c)
                    if (ab <= 0 && bc <= 0) assertTrue(ac <= 0)
                }
            }
        }
        assertTrue(sorted.map { it.name }.toSet() == setOf("ancestor", "descendant", "sibling"))
        assertTrue(sorted.indexOfFirst { it.name == "ancestor" } < sorted.indexOfFirst { it.name == "descendant" })

        assertTrue(legacyComparator(ancestor, descendant, 100) < 0)
        assertTrue(legacyComparator(descendant, sibling, 100) < 0)
        assertTrue(legacyComparator(sibling, ancestor, 100) < 0)
    }

    @Test
    fun comparator_isPermutationInvariantForDeterministicAdversarialCollections() {
        val random = Random(0xC0FFEE)
        val nodes = (0 until 64).map { index ->
            ComparatorNode(
                name = "node-$index",
                bounds = when (index % 7) {
                    0 -> Rect()
                    1 -> Rect(20, 20, 120, 120)
                    else -> Rect(
                        (random.nextInt(8) - 4) * 40,
                        (random.nextInt(16) - 8) * 40,
                        (random.nextInt(8) + 4) * 40,
                        (random.nextInt(16) + 8) * 40
                    )
                }
            )
        }
        nodes.forEach { node ->
            val parentIndex = node.name.substringAfter('-').toInt()
            if (parentIndex > 0) node.parent = nodes[(parentIndex - 1) / 2]
        }
        val order = nodes.mapIndexed { index, node -> node.name to index.toLong() }.toMap()
        val comparator = comparatorFor(order, yBucketSize = 20)
        val expected = nodes.sortedWith(comparator).map { it.name }

        repeat(20) {
            assertEquals(expected, nodes.shuffled(random).sortedWith(comparator).map { it.name })
        }
        for (a in nodes) {
            for (b in nodes) {
                for (c in nodes) {
                    val ab = comparator.compare(a, b)
                    val bc = comparator.compare(b, c)
                    if (ab <= 0 && bc <= 0) assertTrue(comparator.compare(a, c) <= 0)
                }
            }
        }
    }
}
