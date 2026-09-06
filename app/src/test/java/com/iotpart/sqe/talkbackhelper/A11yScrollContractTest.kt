package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class A11yScrollContractTest {
    private data class Node(
        val name: String,
        val scrollable: Boolean,
        val children: List<Node> = emptyList()
    )

    private val service = A11yHelperService()

    @Test
    fun treeFallbackSelectsFirstScrollableNodeInBreadthFirstOrder() {
        val nested = Node("nested", scrollable = true)
        val root = Node(
            "root",
            scrollable = false,
            children = listOf(Node("header", false), Node("content", false, listOf(nested)))
        )

        val result = service.findFirstScrollableInTree(
            root = root,
            childCountOf = { it.children.size },
            childAt = { node, index -> node.children.getOrNull(index) },
            isScrollable = { it.scrollable }
        )

        assertEquals("nested", result?.name)
    }

    @Test
    fun treeFallbackIsBoundedWhenNoScrollableNodeExists() {
        val root = Node("root", false, listOf(Node("child", false)))

        val result = service.findFirstScrollableInTree(
            root = root,
            maxNodes = 1,
            childCountOf = { it.children.size },
            childAt = { node, index -> node.children.getOrNull(index) },
            isScrollable = { it.scrollable }
        )

        assertNull(result)
    }
}
