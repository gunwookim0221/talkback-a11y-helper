package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yHelperServiceClickTest {

    private data class TestNode(
        val id: String,
        val resourceId: String? = null,
        val className: String? = null,
        val contentDesc: String? = null,
        val text: String? = null,
        var clickable: Boolean = false,
        var visible: Boolean = true,
        var enabled: Boolean = true,
        var bounds: Rect = Rect(0, 0, 100, 100),
        var parent: TestNode? = null,
        val children: MutableList<TestNode> = mutableListOf(),
        var clickResult: Boolean = false
    ) {
        fun addChild(child: TestNode): TestNode {
            child.parent = this
            children += child
            return this
        }
    }

    @Test
    fun executeClickFromFocusedNode_directSuccess_keepsRegression() {
        val focused = TestNode(id = "focused", clickable = true, clickResult = true)

        val result = runExecute(focused)

        assertTrue(result.success)
        assertEquals("Focused node clicked", result.reason)
        assertEquals(A11yHelperService.ClickPath.DIRECT, result.path)
        assertEquals(focused, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_descendantAfterDirectFail() {
        val focused = TestNode(id = "focused", clickable = true, clickResult = false)
        val child = TestNode(id = "child", clickable = true, clickResult = true)
        focused.addChild(child)

        val result = runExecute(focused)

        assertTrue(result.success)
        assertEquals("Clickable descendant clicked", result.reason)
        assertEquals(A11yHelperService.ClickPath.DESCENDANT, result.path)
        assertEquals(child, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_ancestorAfterDescendantFail() {
        val ancestor = TestNode(id = "ancestor", clickable = true, clickResult = true)
        val focused = TestNode(id = "focused", clickable = false, clickResult = false)
        ancestor.addChild(focused)

        val result = runExecute(focused)

        assertTrue(result.success)
        assertEquals("Clickable ancestor clicked", result.reason)
        assertEquals(A11yHelperService.ClickPath.ANCESTOR, result.path)
        assertEquals(ancestor, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_allFail_keepsReasonAndAttempted() {
        val focused = TestNode(id = "focused", clickable = false, clickResult = false)
        val descendant = TestNode(id = "desc", clickable = true, clickResult = false)
        focused.addChild(descendant)

        val result = runExecute(focused)

        assertFalse(result.success)
        assertEquals("No clickable node found from focused node subtree or root tree", result.reason)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
        assertEquals(descendant, result.attemptedNode)
    }

    @Test
    fun executeClickFromFocusedNode_rootRetargetSuccess_whenRawDescendantInvisibleInFocusedTree() {
        val root = TestNode(id = "root", clickable = false, clickResult = false, bounds = Rect(0, 0, 1000, 1000))
        val branchA = TestNode(id = "branchA", clickable = false, clickResult = false, bounds = Rect(0, 0, 500, 500))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.FrameLayout",
            contentDesc = "Settings",
            clickable = false,
            clickResult = false,
            bounds = Rect(100, 100, 260, 260)
        )
        val branchB = TestNode(id = "branchB", clickable = false, clickResult = false, bounds = Rect(0, 0, 1000, 1000))
        val actualClickableChild = TestNode(
            id = "settings_image",
            resourceId = "com.example:id/settings_image",
            className = "android.widget.ImageButton",
            contentDesc = "Settings",
            clickable = true,
            clickResult = true,
            bounds = Rect(120, 120, 240, 240)
        )

        root.addChild(branchA)
        branchA.addChild(focused)
        root.addChild(branchB)
        branchB.addChild(actualClickableChild)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals("Retargeted clickable node clicked from root tree", result.reason)
        assertEquals(A11yHelperService.ClickPath.ROOT_RETARGET, result.path)
        assertEquals(actualClickableChild, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_descendantMetadataRetarget_afterDescendantClickFail() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val subtreeClickableButActionFail = TestNode(
            id = "focused_child",
            resourceId = "com.example:id/settings_image",
            className = "android.widget.ImageButton",
            contentDesc = "Settings",
            clickable = true,
            clickResult = false,
            bounds = Rect(940, 170, 1020, 250)
        )
        val rootMirrorClickableChild = TestNode(
            id = "root_settings_image",
            resourceId = "com.example:id/settings_image",
            className = "android.widget.ImageButton",
            contentDesc = "Settings",
            clickable = true,
            clickResult = true,
            bounds = Rect(950, 180, 1010, 240)
        )
        root.addChild(focused)
        focused.addChild(subtreeClickableButActionFail)
        root.addChild(rootMirrorClickableChild)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals("Clickable descendant metadata retarget clicked", result.reason)
        assertEquals(A11yHelperService.ClickPath.DESCENDANT, result.path)
        assertEquals(rootMirrorClickableChild, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_rootRetarget_prefersInsideCandidateOverDistantLargeCard() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val insideClickable = TestNode(
            id = "settings_image",
            clickable = true,
            clickResult = true,
            bounds = Rect(945, 178, 1017, 250)
        )
        val distantLargeCard = TestNode(
            id = "explore_card",
            clickable = true,
            clickResult = true,
            bounds = Rect(60, 650, 1020, 1450)
        )

        root.addChild(focused)
        root.addChild(insideClickable)
        root.addChild(distantLargeCard)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.ROOT_RETARGET, result.path)
        assertEquals(insideClickable, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_rootRetarget_usesOverlapWhenInsideMissing() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val overlapClickable = TestNode(
            id = "toolbar_overlap",
            clickable = true,
            clickResult = true,
            bounds = Rect(900, 130, 1000, 230)
        )
        val globalFar = TestNode(
            id = "global_far",
            clickable = true,
            clickResult = true,
            bounds = Rect(80, 1500, 1000, 2100)
        )

        root.addChild(focused)
        root.addChild(overlapClickable)
        root.addChild(globalFar)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.ROOT_RETARGET, result.path)
        assertEquals(overlapClickable, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_rootRetarget_failsForTopLocalTargetWhenInsideAndOverlapMissing() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val localBandClickable = TestNode(
            id = "toolbar_neighbor",
            clickable = true,
            clickResult = true,
            bounds = Rect(760, 120, 900, 240)
        )
        val farGlobalClickable = TestNode(
            id = "content_card",
            clickable = true,
            clickResult = true,
            bounds = Rect(60, 1200, 1020, 2000)
        )

        root.addChild(focused)
        root.addChild(localBandClickable)
        root.addChild(farGlobalClickable)

        val result = runExecute(focused, root)

        assertFalse(result.success)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
        assertEquals(focused, result.attemptedNode)
    }

    @Test
    fun executeClickFromFocusedNode_rootRetarget_doesNotPickGiantCardWhenOnlyLocalOrGlobalRemain() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val giantCard = TestNode(
            id = "my_profile_card_view",
            clickable = true,
            clickResult = true,
            bounds = Rect(40, 420, 1040, 2100)
        )
        root.addChild(focused)
        root.addChild(giantCard)

        val result = runExecute(focused, root)

        assertFalse(result.success)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
        assertEquals(focused, result.attemptedNode)
    }

    @Test
    fun executeClickFromFocusedNode_rootRetarget_doesNotPickLargeDistantCardWhenOverlapExists() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val overlapClickable = TestNode(
            id = "near_overlap",
            clickable = true,
            clickResult = true,
            bounds = Rect(920, 150, 1060, 290)
        )
        val hugeDistantCard = TestNode(
            id = "huge_card",
            clickable = true,
            clickResult = true,
            bounds = Rect(0, 500, 1080, 2200)
        )

        root.addChild(focused)
        root.addChild(overlapClickable)
        root.addChild(hugeDistantCard)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.ROOT_RETARGET, result.path)
        assertEquals(overlapClickable, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_mirrorDescendantSuccess_whenFocusedSubtreeIsEmpty() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.FrameLayout",
            contentDesc = "Settings",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val mirrorParent = TestNode(
            id = "mirror_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.FrameLayout",
            contentDesc = "Settings",
            clickable = false,
            bounds = Rect(928, 160, 1034, 268)
        )
        val mirrorChild = TestNode(
            id = "mirror_child",
            resourceId = "com.example:id/settings_image",
            className = "android.widget.ImageButton",
            contentDesc = "Settings",
            clickable = true,
            clickResult = true,
            bounds = Rect(944, 176, 1018, 252)
        )
        val giantCard = TestNode(
            id = "giant_card",
            clickable = true,
            clickResult = true,
            bounds = Rect(0, 500, 1080, 2200)
        )
        mirrorParent.addChild(mirrorChild)
        root.addChild(focused)
        root.addChild(mirrorParent)
        root.addChild(giantCard)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(mirrorChild, result.clickedNode)
        assertEquals(mirrorParent, result.mirrorNode)
    }

    @Test
    fun executeClickFromFocusedNode_mirrorResolveMiss_keepsStrictFailurePolicy() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.FrameLayout",
            contentDesc = "Settings",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val localBandClickable = TestNode(
            id = "toolbar_neighbor",
            clickable = true,
            clickResult = true,
            bounds = Rect(760, 120, 900, 240)
        )
        val farGlobalClickable = TestNode(
            id = "content_card",
            clickable = true,
            clickResult = true,
            bounds = Rect(60, 1200, 1020, 2000)
        )
        root.addChild(focused)
        root.addChild(localBandClickable)
        root.addChild(farGlobalClickable)

        val result = runExecute(focused, root)

        assertFalse(result.success)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
        assertEquals(focused, result.attemptedNode)
    }

    @Test
    fun executeClickFromFocusedNode_nullFocusedFailsImmediately() {
        val result = runExecute(null)

        assertFalse(result.success)
        assertEquals("Focused node not found", result.reason)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
    }

    private fun runExecute(
        focusedNode: TestNode?,
        rootNode: TestNode? = focusedNode
    ): A11yHelperService.ClickExecutionResult<TestNode> {
        return A11yHelperService().executeClickFromFocusedNode(
            focusedNode = focusedNode,
            rootNode = rootNode,
            childCountOf = { it.children.size },
            childAt = { node, index -> node.children.getOrNull(index) },
            parentOf = { it.parent },
            isClickable = { it.clickable },
            isVisible = { it.visible },
            isEnabled = { it.enabled },
            boundsOf = { it.bounds },
            resourceIdOf = { it.resourceId },
            classNameOf = { it.className },
            contentDescOf = { it.contentDesc },
            textOf = { it.text },
            performClick = { it.clickResult }
        )
    }
}
