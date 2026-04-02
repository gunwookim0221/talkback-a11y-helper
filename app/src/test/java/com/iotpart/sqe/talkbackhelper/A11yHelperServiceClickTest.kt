package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
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
        var accessibilityFocused: Boolean = false,
        var focusable: Boolean = false,
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
        val focused = TestNode(id = "focused", clickable = true, clickResult = true, accessibilityFocused = true, focusable = true)

        val result = runExecute(focused)

        assertTrue(result.success)
        assertEquals("Focused node clicked", result.reason)
        assertEquals(A11yHelperService.ClickPath.DIRECT, result.path)
        assertEquals(focused, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_wrapperRecovery_picksInsideClickable_whenFocusedWrapperIsTopSmallAndEmpty() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedWrapper = TestNode(
            id = "focused_wrapper",
            className = "android.widget.RelativeLayout",
            clickable = false,
            accessibilityFocused = true,
            focusable = true,
            bounds = Rect(930, 160, 1030, 260)
        )
        val insideClickable = TestNode(
            id = "inside_clickable",
            className = "android.widget.ImageButton",
            clickable = true,
            clickResult = true,
            bounds = Rect(944, 176, 1016, 248)
        )
        val farBodyClickable = TestNode(
            id = "far_body_clickable",
            className = "android.widget.Button",
            clickable = true,
            clickResult = true,
            bounds = Rect(120, 1300, 960, 1880)
        )
        root.addChild(focusedWrapper)
        root.addChild(insideClickable)
        root.addChild(farBodyClickable)

        val result = runExecute(focusedWrapper, root)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.WRAPPER_RECOVERY, result.path)
        assertEquals(insideClickable, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_wrapperRecovery_topSmallTarget_doesNotTapBodyCandidate() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedWrapper = TestNode(
            id = "focused_wrapper",
            className = "android.widget.RelativeLayout",
            clickable = false,
            accessibilityFocused = true,
            focusable = true,
            bounds = Rect(930, 160, 1030, 260)
        )
        val bodyClickable = TestNode(
            id = "body_clickable",
            className = "android.widget.Button",
            clickable = true,
            clickResult = true,
            bounds = Rect(920, 700, 1040, 820)
        )
        root.addChild(focusedWrapper)
        root.addChild(bodyClickable)

        val result = runExecute(focusedWrapper, root)

        assertFalse(result.success)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
        assertEquals(focusedWrapper, result.attemptedNode)
    }

    @Test
    fun executeClickFromFocusedNode_wrapperRecovery_rejectsGiantAndFarCandidates() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedWrapper = TestNode(
            id = "focused_wrapper",
            className = "android.widget.RelativeLayout",
            clickable = false,
            accessibilityFocused = true,
            focusable = true,
            bounds = Rect(930, 160, 1030, 260)
        )
        val giantContainer = TestNode(
            id = "mainScrollView",
            className = "android.widget.ScrollView",
            clickable = true,
            clickResult = true,
            bounds = Rect(0, 120, 1080, 2320)
        )
        val farTopTiny = TestNode(
            id = "far_top_tiny",
            className = "android.widget.ImageButton",
            clickable = true,
            clickResult = true,
            bounds = Rect(20, 20, 90, 90)
        )
        root.addChild(focusedWrapper)
        root.addChild(giantContainer)
        root.addChild(farTopTiny)

        val result = runExecute(focusedWrapper, root)

        assertFalse(result.success)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
        assertEquals(focusedWrapper, result.attemptedNode)
    }

    @Test
    fun executeClickFromFocusedNode_wrapperRecovery_notTriggered_whenAccessibilityFocusedFlagMissing() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedWrapper = TestNode(
            id = "focused_wrapper",
            className = "android.widget.RelativeLayout",
            clickable = false,
            accessibilityFocused = false,
            focusable = true,
            bounds = Rect(930, 160, 1030, 260)
        )
        val insideClickable = TestNode(
            id = "inside_clickable",
            className = "android.widget.ImageButton",
            clickable = true,
            clickResult = true,
            bounds = Rect(944, 176, 1016, 248)
        )
        root.addChild(focusedWrapper)
        root.addChild(insideClickable)

        val result = runExecute(focusedWrapper, root)

        assertFalse(result.success)
        assertNotEquals(A11yHelperService.ClickPath.WRAPPER_RECOVERY, result.path)
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
    fun executeClickFromFocusedNode_mirrorResolve_prefersLocalSmallToolbarNode_overGiantScrollContainer() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val toolbarMirror = TestNode(
            id = "toolbar_mirror",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(926, 156, 1038, 272)
        )
        val toolbarMirrorChild = TestNode(
            id = "toolbar_mirror_child",
            className = "android.widget.ImageButton",
            clickable = true,
            clickResult = true,
            bounds = Rect(948, 178, 1018, 248)
        )
        val giantScrollContainer = TestNode(
            id = "more_layout",
            className = "android.widget.ScrollView",
            clickable = false,
            bounds = Rect(0, 94, 1080, 2316)
        )
        val giantChild = TestNode(
            id = "my_profile_card_view",
            clickable = true,
            clickResult = true,
            bounds = Rect(48, 420, 1032, 1120)
        )

        toolbarMirror.addChild(toolbarMirrorChild)
        giantScrollContainer.addChild(giantChild)
        root.addChild(focused)
        root.addChild(giantScrollContainer)
        root.addChild(toolbarMirror)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(toolbarMirrorChild, result.clickedNode)
        assertEquals(toolbarMirror, result.mirrorNode)
    }

    @Test
    fun executeClickFromFocusedNode_mirrorResolve_rejectsGiantRecyclerAndFrameContainers_whenLocalCandidateExists() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val localMirror = TestNode(
            id = "local_mirror",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(920, 150, 1036, 278)
        )
        val localMirrorChild = TestNode(
            id = "local_mirror_child",
            clickable = true,
            clickResult = true,
            bounds = Rect(946, 176, 1016, 246)
        )
        val recyclerContainer = TestNode(
            id = "giant_recycler",
            className = "androidx.recyclerview.widget.RecyclerView",
            clickable = false,
            bounds = Rect(0, 260, 1080, 2330)
        )
        val frameContainer = TestNode(
            id = "giant_frame",
            className = "android.widget.FrameLayout",
            clickable = false,
            bounds = Rect(0, 0, 1080, 2200)
        )

        localMirror.addChild(localMirrorChild)
        root.addChild(focused)
        root.addChild(recyclerContainer)
        root.addChild(frameContainer)
        root.addChild(localMirror)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(localMirror, result.mirrorNode)
        assertEquals(localMirrorChild, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_mirrorResolve_rejectsFarBodyText_forTopRightFocusedTarget() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val farBodyText = TestNode(
            id = "my_profile_desc",
            resourceId = "com.example:id/my_profile_desc",
            className = "android.widget.TextView",
            clickable = false,
            text = "내 프로필",
            bounds = Rect(84, 477, 642, 599)
        )

        root.addChild(focused)
        root.addChild(farBodyText)

        val result = runExecute(focused, root)

        assertFalse(result.success)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
        assertEquals(focused, result.attemptedNode)
    }

    @Test
    fun executeClickFromFocusedNode_mirrorResolve_rejectsBodyRegionCandidate_whenFocusedIsSmallTopTarget() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val bodyCandidate = TestNode(
            id = "body_text",
            className = "android.widget.TextView",
            clickable = false,
            text = "Body",
            bounds = Rect(920, 520, 1028, 604)
        )

        root.addChild(focused)
        root.addChild(bodyCandidate)

        val result = runExecute(focused, root)

        assertFalse(result.success)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
    }

    @Test
    fun executeClickFromFocusedNode_mirrorResolve_prefersNearToolbarMirror_whenFarLeafTextAlsoExists() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val toolbarMirror = TestNode(
            id = "toolbar_mirror",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(928, 158, 1034, 270)
        )
        val toolbarChild = TestNode(
            id = "toolbar_mirror_child",
            className = "android.widget.ImageButton",
            clickable = true,
            clickResult = true,
            bounds = Rect(946, 176, 1016, 246)
        )
        val farLeafText = TestNode(
            id = "content_desc",
            className = "android.widget.TextView",
            clickable = false,
            text = "far body",
            bounds = Rect(120, 480, 660, 620)
        )

        toolbarMirror.addChild(toolbarChild)
        root.addChild(focused)
        root.addChild(toolbarMirror)
        root.addChild(farLeafText)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(toolbarMirror, result.mirrorNode)
        assertEquals(toolbarChild, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_mirrorResolve_keepsTopClickableCandidate_whenTopSmallTargetHasDyGap() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val topClickable = TestNode(
            id = "top_clickable",
            className = "android.widget.ImageButton",
            clickable = true,
            clickResult = true,
            bounds = Rect(760, 280, 860, 380)
        )
        val bodyText = TestNode(
            id = "body_text",
            className = "android.widget.TextView",
            clickable = false,
            text = "body",
            bounds = Rect(120, 700, 760, 840)
        )

        root.addChild(focused)
        root.addChild(topClickable)
        root.addChild(bodyText)

        val result = runExecute(focused, root)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(topClickable, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_mirrorResolve_collectsFocusedDescendantCandidatesWithDedicatedLog() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val focusedChild = TestNode(
            id = "focused_child_settings_image",
            resourceId = "com.samsung.android.oneconnect:id/settings_image",
            className = "android.widget.ImageButton",
            contentDesc = "Settings",
            clickable = true,
            clickResult = false,
            bounds = Rect(940, 172, 1022, 252)
        )
        val mirrorParent = TestNode(
            id = "mirror_parent",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(928, 160, 1034, 268)
        )
        val mirrorChild = TestNode(
            id = "mirror_settings_image",
            resourceId = "com.samsung.android.oneconnect:id/settings_image",
            className = "android.widget.ImageButton",
            contentDesc = "Settings",
            clickable = true,
            clickResult = true,
            bounds = Rect(944, 176, 1018, 252)
        )
        val logs = mutableListOf<String>()

        focused.addChild(focusedChild)
        mirrorParent.addChild(mirrorChild)
        root.addChild(focused)
        root.addChild(mirrorParent)

        val result = runExecute(focused, root, logs)

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(mirrorChild, result.clickedNode)
        assertNotNull(
            logs.find {
                it.contains("[click_focused_descendant_candidate_seen]") &&
                    it.contains("com.samsung.android.oneconnect:id/settings_image") &&
                    it.contains("source='raw_descendant'")
            }
        )
        assertNotNull(
            logs.find {
                it.contains("[click_focused_candidate_pass_stage]") &&
                    it.contains("stage='raw_descendant_collected'") &&
                    it.contains("com.samsung.android.oneconnect:id/settings_image")
            }
        )
    }

    @Test
    fun executeClickFromFocusedNode_snapshotChildrenEmpty_reResolvesRawFocusedNodeAndCollectsDescendant() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedSnapshot = TestNode(
            id = "focused_snapshot_only",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val rawFocusedWrapper = TestNode(
            id = "raw_focused_wrapper",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val rawChildTarget = TestNode(
            id = "raw_child_settings_image",
            resourceId = "com.samsung.android.oneconnect:id/settings_image",
            className = "android.widget.ImageButton",
            contentDesc = "Settings",
            clickable = true,
            clickResult = true,
            bounds = Rect(944, 176, 1018, 252)
        )
        val logs = mutableListOf<String>()
        rawFocusedWrapper.addChild(rawChildTarget)
        root.addChild(rawFocusedWrapper)

        val result = runExecute(
            focusedNode = focusedSnapshot,
            rootNode = root,
            logs = logs,
            reResolveFocusedNodeFromRoot = { snapshot, treeRoot, logger ->
                logger?.invoke(
                    "[click_focused_raw_focus_resolve] resolved=true resourceId='${snapshot.resourceId}' className='${snapshot.className}' bounds='${snapshot.bounds.toShortString()}' reason='test_resolved_by_resource_class_bounds'"
                )
                treeRoot?.children?.firstOrNull { it.resourceId == snapshot.resourceId && it.className == snapshot.className }
            }
        )

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.DESCENDANT, result.path)
        assertEquals(rawChildTarget, result.clickedNode)
        assertNotNull(logs.find { it.contains("[click_focused_raw_focus_resolve]") && it.contains("resolved=true") })
        assertNotNull(logs.find { it.contains("[click_focused_descendant_candidate_seen]") && it.contains("com.samsung.android.oneconnect:id/settings_image") })
    }

    @Test
    fun executeClickFromFocusedNode_localRawSearch_runsWhenResolvedRawSubtreeIsEmpty_andFindsTopRightActionable() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedSnapshot = TestNode(
            id = "focused_snapshot_only",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val rawResolvedWrapper = TestNode(
            id = "raw_resolved_wrapper",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val topRightSettingsImage = TestNode(
            id = "settings_image_local",
            resourceId = "com.samsung.android.oneconnect:id/settings_image",
            className = "android.widget.ImageButton",
            contentDesc = "Settings",
            clickable = true,
            clickResult = true,
            bounds = Rect(945, 178, 1017, 250)
        )
        val giantBodyCard = TestNode(
            id = "giant_body_card",
            className = "android.widget.ScrollView",
            clickable = true,
            clickResult = true,
            bounds = Rect(0, 240, 1080, 2280)
        )
        val logs = mutableListOf<String>()

        root.addChild(rawResolvedWrapper)
        root.addChild(topRightSettingsImage)
        root.addChild(giantBodyCard)

        val result = runExecute(
            focusedNode = focusedSnapshot,
            rootNode = root,
            logs = logs,
            reResolveFocusedNodeFromRoot = { _, _, logger ->
                logger?.invoke(
                    "[click_focused_raw_focus_resolve] resolved=true resourceId='${focusedSnapshot.resourceId}' className='${focusedSnapshot.className}' bounds='${focusedSnapshot.bounds.toShortString()}' reason='test_resolved_raw_focus_empty_children'"
                )
                rawResolvedWrapper
            }
        )

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(topRightSettingsImage, result.clickedNode)
        assertNotNull(logs.find { it.contains("[click_focused_descendant_scan_start]") && it.contains("childCount=0") && it.contains("source='resolved_raw_focus'") })
        assertNotNull(logs.find { it.contains("[click_focused_local_raw_search_start]") })
        assertNotNull(logs.find { it.contains("[click_focused_local_raw_scan_node]") && it.contains("source='local_raw_search'") })
        assertNotNull(
            logs.find {
                it.contains("[click_focused_local_raw_candidate_seen]") &&
                    it.contains("com.samsung.android.oneconnect:id/settings_image") &&
                    it.contains("source='local_raw_search'")
            }
        )
        assertNotNull(
            logs.find {
                it.contains("[click_focused_candidate_pass_stage]") &&
                    it.contains("stage='local_raw_collected'") &&
                    it.contains("com.samsung.android.oneconnect:id/settings_image")
            }
        )
        assertNull(
            logs.find {
                it.contains("[click_focused_candidate_seen]") &&
                    it.contains("com.samsung.android.oneconnect:id/settings_image") &&
                    it.contains("source='root_tree'")
            }
        )
        assertNotEquals(giantBodyCard, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_localRawSearch_safeFailWhenNoLocalCandidateExists() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedSnapshot = TestNode(
            id = "focused_snapshot_only",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val rawResolvedWrapper = TestNode(
            id = "raw_resolved_wrapper",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val giantScrollContainer = TestNode(
            id = "giant_scroll",
            className = "android.widget.ScrollView",
            clickable = false,
            bounds = Rect(0, 94, 1080, 2316)
        )
        val farBodyCard = TestNode(
            id = "far_body_card",
            className = "android.widget.FrameLayout",
            clickable = true,
            clickResult = true,
            bounds = Rect(60, 980, 1020, 1880)
        )
        val logs = mutableListOf<String>()

        root.addChild(rawResolvedWrapper)
        root.addChild(giantScrollContainer)
        root.addChild(farBodyCard)

        val result = runExecute(
            focusedNode = focusedSnapshot,
            rootNode = root,
            logs = logs,
            reResolveFocusedNodeFromRoot = { _, _, logger ->
                logger?.invoke(
                    "[click_focused_raw_focus_resolve] resolved=true resourceId='${focusedSnapshot.resourceId}' className='${focusedSnapshot.className}' bounds='${focusedSnapshot.bounds.toShortString()}' reason='test_resolved_raw_focus_empty_children'"
                )
                rawResolvedWrapper
            }
        )

        assertFalse(result.success)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
        assertNotNull(logs.find { it.contains("[click_focused_descendant_scan_start]") && it.contains("childCount=0") })
        assertNotNull(logs.find { it.contains("[click_focused_local_raw_search_start]") })
        assertNotNull(logs.find { it.contains("[click_focused_local_raw_scan_node]") && it.contains("source='local_raw_search'") })
        assertEquals(0, logs.count { it.contains("[click_focused_local_raw_candidate_seen]") })
    }

    @Test
    fun executeClickFromFocusedNode_localRawSearch_fullTraversalFindsNestedSmallChild_whenTopLevelDoesNotContainCandidate() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedSnapshot = TestNode(
            id = "focused_snapshot_only",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val rawResolvedWrapper = TestNode(
            id = "raw_resolved_wrapper",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val toolbarContainer = TestNode(
            id = "toolbar_container",
            className = "android.widget.FrameLayout",
            clickable = false,
            bounds = Rect(880, 120, 1060, 320)
        )
        val nestedSettingsImage = TestNode(
            id = "nested_settings_image",
            resourceId = "com.samsung.android.oneconnect:id/settings_image",
            className = "android.widget.ImageButton",
            contentDesc = "Settings",
            clickable = true,
            clickResult = true,
            bounds = Rect(945, 178, 1017, 250)
        )
        val giantBodyCard = TestNode(
            id = "my_profile_card_view",
            className = "android.widget.ScrollView",
            clickable = true,
            clickResult = true,
            bounds = Rect(0, 300, 1080, 2280)
        )
        val logs = mutableListOf<String>()

        toolbarContainer.addChild(nestedSettingsImage)
        root.addChild(rawResolvedWrapper)
        root.addChild(toolbarContainer)
        root.addChild(giantBodyCard)

        val result = runExecute(
            focusedNode = focusedSnapshot,
            rootNode = root,
            logs = logs,
            reResolveFocusedNodeFromRoot = { _, _, logger ->
                logger?.invoke(
                    "[click_focused_raw_focus_resolve] resolved=true resourceId='${focusedSnapshot.resourceId}' className='${focusedSnapshot.className}' bounds='${focusedSnapshot.bounds.toShortString()}' reason='test_resolved_raw_focus_empty_children_nested_target'"
                )
                rawResolvedWrapper
            }
        )

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(nestedSettingsImage, result.clickedNode)
        assertNotNull(logs.find { it.contains("[click_focused_descendant_scan_start]") && it.contains("childCount=0") })
        assertNotNull(logs.find { it.contains("[click_focused_local_raw_scan_node]") && it.contains("resourceId='com.samsung.android.oneconnect:id/settings_image'") })
        assertNotNull(logs.find { it.contains("[click_focused_local_raw_candidate_seen]") && it.contains("resourceId='com.samsung.android.oneconnect:id/settings_image'") })
        assertNotNull(logs.find { it.contains("[click_focused_candidate_pass_stage]") && it.contains("stage='local_raw_collected'") && it.contains("com.samsung.android.oneconnect:id/settings_image") })
        assertNull(
            logs.find {
                it.contains("[click_focused_candidate_seen]") &&
                    it.contains("resourceId='com.samsung.android.oneconnect:id/settings_image'") &&
                    it.contains("source='root_tree'")
            }
        )
        assertNotEquals(giantBodyCard, result.clickedNode)
    }

    @Test
    fun executeClickFromFocusedNode_localRawSearch_logsToolbarBranchExpansion_andFindsWrapperAndImageChild() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedSnapshot = TestNode(
            id = "focused_snapshot",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val rawResolvedWrapper = TestNode(
            id = "raw_resolved_wrapper",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val appBarLayout = TestNode(
            id = "app_bar_layout",
            resourceId = "com.samsung.android.oneconnect:id/app_bar_layout",
            className = "android.widget.FrameLayout",
            clickable = false,
            bounds = Rect(0, 0, 1080, 360)
        )
        val settingButtonLayout = TestNode(
            id = "setting_button_layout",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val settingsImage = TestNode(
            id = "settings_image",
            resourceId = "com.samsung.android.oneconnect:id/settings_image",
            className = "android.widget.ImageButton",
            clickable = true,
            clickResult = true,
            bounds = Rect(945, 178, 1017, 250)
        )
        val logs = mutableListOf<String>()

        settingButtonLayout.addChild(settingsImage)
        appBarLayout.addChild(settingButtonLayout)
        root.addChild(rawResolvedWrapper)
        root.addChild(appBarLayout)

        val result = runExecute(
            focusedNode = focusedSnapshot,
            rootNode = root,
            logs = logs,
            reResolveFocusedNodeFromRoot = { _, _, _ -> rawResolvedWrapper }
        )

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(settingsImage, result.clickedNode)
        assertNotNull(logs.find { it.contains("[click_focused_local_raw_expand]") && it.contains("app_bar_layout") })
        assertNotNull(
            logs.find {
                it.contains("[click_focused_local_raw_child]") &&
                    it.contains("parentResourceId='com.samsung.android.oneconnect:id/setting_button_layout'") &&
                    it.contains("childResourceId='com.samsung.android.oneconnect:id/settings_image'") &&
                    it.contains("enqueued=true")
            }
        )
        assertNotNull(logs.find { it.contains("[click_focused_local_raw_scan_node]") && it.contains("com.samsung.android.oneconnect:id/settings_image") })
        assertNotNull(logs.find { it.contains("[click_focused_local_raw_toolbar_summary]") && it.contains("seenSettingWrapper=true") && it.contains("seenSettingsImage=true") })
    }

    @Test
    fun executeClickFromFocusedNode_localRawSearch_doesNotPruneNonClickableParent_beforeClickableNestedChild() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focusedSnapshot = TestNode(
            id = "focused_snapshot",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val rawResolvedWrapper = TestNode(
            id = "raw_resolved_wrapper",
            resourceId = "com.samsung.android.oneconnect:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val nonClickableParent = TestNode(
            id = "non_clickable_parent",
            resourceId = "com.example:id/non_clickable_parent",
            className = "android.widget.FrameLayout",
            clickable = false,
            bounds = Rect(900, 130, 1040, 320)
        )
        val clickableNested = TestNode(
            id = "clickable_nested",
            resourceId = "com.example:id/settings_image",
            className = "android.widget.ImageButton",
            clickable = true,
            clickResult = true,
            bounds = Rect(944, 176, 1018, 252)
        )
        val giantBodyCard = TestNode(
            id = "giant_body_card",
            className = "android.widget.ScrollView",
            clickable = true,
            clickResult = true,
            bounds = Rect(0, 360, 1080, 2280)
        )
        val logs = mutableListOf<String>()

        nonClickableParent.addChild(clickableNested)
        root.addChild(rawResolvedWrapper)
        root.addChild(nonClickableParent)
        root.addChild(giantBodyCard)

        val result = runExecute(
            focusedNode = focusedSnapshot,
            rootNode = root,
            logs = logs,
            reResolveFocusedNodeFromRoot = { _, _, _ -> rawResolvedWrapper }
        )

        assertTrue(result.success)
        assertEquals(A11yHelperService.ClickPath.MIRROR_DESCENDANT, result.path)
        assertEquals(clickableNested, result.clickedNode)
        assertNotEquals(giantBodyCard, result.clickedNode)
        assertNotNull(
            logs.find {
                it.contains("[click_focused_local_raw_candidate_skip]") &&
                    it.contains("reason='not_clickable'") &&
                    it.contains("com.example:id/non_clickable_parent")
            }
        )
        assertNotNull(
            logs.find {
                it.contains("[click_focused_local_raw_candidate_seen]") &&
                    it.contains("com.example:id/settings_image")
            }
        )
    }

    @Test
    fun executeClickFromFocusedNode_mirrorResolve_failsSafely_whenOnlyGiantContainerCandidatesExist() {
        val root = TestNode(id = "root", bounds = Rect(0, 0, 1080, 2400))
        val focused = TestNode(
            id = "focused_parent",
            resourceId = "com.example:id/setting_button_layout",
            className = "android.widget.RelativeLayout",
            clickable = false,
            bounds = Rect(930, 163, 1032, 265)
        )
        val giantScrollContainer = TestNode(
            id = "only_scroll_container",
            className = "android.widget.ScrollView",
            clickable = false,
            bounds = Rect(0, 94, 1080, 2316)
        )
        val giantFrameContainer = TestNode(
            id = "only_frame_container",
            className = "android.widget.FrameLayout",
            clickable = false,
            bounds = Rect(0, 0, 1080, 2200)
        )

        root.addChild(focused)
        root.addChild(giantScrollContainer)
        root.addChild(giantFrameContainer)

        val result = runExecute(focused, root)

        assertFalse(result.success)
        assertEquals(A11yHelperService.ClickPath.NONE, result.path)
        assertEquals(focused, result.attemptedNode)
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
        rootNode: TestNode? = focusedNode,
        logs: MutableList<String>? = null,
        reResolveFocusedNodeFromRoot: ((focusedNode: TestNode, rootNode: TestNode?, log: ((String) -> Unit)?) -> TestNode?)? = null
    ): A11yHelperService.ClickExecutionResult<TestNode> {
        return A11yHelperService().executeClickFromFocusedNode(
            focusedNode = focusedNode,
            rootNode = rootNode,
            reResolveFocusedNodeFromRoot = reResolveFocusedNodeFromRoot,
            childCountOf = { it.children.size },
            childAt = { node, index -> node.children.getOrNull(index) },
            parentOf = { it.parent },
            isAccessibilityFocused = { it.accessibilityFocused },
            isFocusable = { it.focusable },
            isClickable = { it.clickable },
            isVisible = { it.visible },
            isEnabled = { it.enabled },
            boundsOf = { it.bounds },
            resourceIdOf = { it.resourceId },
            classNameOf = { it.className },
            contentDescOf = { it.contentDesc },
            textOf = { it.text },
            performClick = { it.clickResult },
            log = logs?.let { sink -> { line -> sink += line } }
        )
    }
}
