package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Test

class FocusLabelBuilderTest {

    @Test
    fun buildMergedLabel_prefersNodeTextWhenPresent() {
        val root = FocusLabelBuilder.LabelNode(
            text = "Location QR code",
            children = listOf(
                FocusLabelBuilder.LabelNode(text = "Devices")
            )
        )

        assertEquals("Location QR code", FocusLabelBuilder.buildMergedLabel(root))
    }

    @Test
    fun buildMergedLabel_usesChildTextWhenRootIsEmpty() {
        val root = FocusLabelBuilder.LabelNode(
            children = listOf(
                FocusLabelBuilder.LabelNode(text = "Location QR code")
            )
        )

        assertEquals("Location QR code", FocusLabelBuilder.buildMergedLabel(root))
    }

    @Test
    fun buildMergedLabel_mergesChildrenAndRemovesDuplicates() {
        val root = FocusLabelBuilder.LabelNode(
            children = listOf(
                FocusLabelBuilder.LabelNode(text = "Living room"),
                FocusLabelBuilder.LabelNode(contentDescription = "Air purifier"),
                FocusLabelBuilder.LabelNode(text = "Living room")
            )
        )

        assertEquals("Living room Air purifier", FocusLabelBuilder.buildMergedLabel(root))
    }

    @Test
    fun buildMergedLabel_usesContentDescriptionForIconButton() {
        val root = FocusLabelBuilder.LabelNode(contentDescription = "설정")

        assertEquals("설정", FocusLabelBuilder.buildMergedLabel(root))
    }

    @Test
    fun buildMergedLabel_collectsLabelsByDfsPreOrder() {
        val root = FocusLabelBuilder.LabelNode(
            children = listOf(
                FocusLabelBuilder.LabelNode(
                    text = "A",
                    children = listOf(
                        FocusLabelBuilder.LabelNode(text = "B")
                    )
                ),
                FocusLabelBuilder.LabelNode(contentDescription = "C")
            )
        )

        assertEquals("A B C", FocusLabelBuilder.buildMergedLabel(root))
    }

    @Test
    fun buildMergedLabel_stopsAtConfiguredDepth() {
        val root = FocusLabelBuilder.LabelNode(
            children = listOf(
                FocusLabelBuilder.LabelNode(
                    children = listOf(
                        FocusLabelBuilder.LabelNode(
                            children = listOf(
                                FocusLabelBuilder.LabelNode(text = "DEEP_LABEL")
                            )
                        )
                    )
                )
            )
        )

        assertEquals("", FocusLabelBuilder.buildMergedLabel(root, maxDepth = 2))
    }
}
