package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yTraversalAnalyzerTest {

    @Test
    fun version_isUpdated() {
        assertEquals("1.10.6", A11yTraversalAnalyzer.VERSION)
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
}
