package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.util.Collections

/** Immutable copied facts for one service traversal root; it retains no live AccessibilityNodeInfo. */
internal data class ImmutableHierarchyCapture(val root: CapturedHierarchyNode, val nodeCount: Int) {
    companion object {
        fun capture(root: AccessibilityNodeInfo): ImmutableHierarchyCapture {
            val count = intArrayOf(0)
            return ImmutableHierarchyCapture(copyNode(root, null, 0, count), count[0])
        }
        private fun copyNode(node: AccessibilityNodeInfo, childIndex: Int?, depth: Int, count: IntArray): CapturedHierarchyNode {
            if (depth > 80) throw IllegalStateException("SERIALIZATION_LIMIT_EXCEEDED:depth>80")
            count[0] += 1
            if (count[0] > 4096) throw IllegalStateException("SERIALIZATION_LIMIT_EXCEEDED:nodes>4096")
            // Reserve preorder identity before descending so every branch gets a unique ID.
            val stableIndex = count[0] - 1
            val rect = Rect().also(node::getBoundsInScreen)
            val actions = node.actionList.map { CapturedHierarchyAction(it.id, A11yNavigator.hierarchyActionName(it.id), it.label?.toString()) }
            val children = ArrayList<CapturedHierarchyNode>(node.childCount)
            for (index in 0 until node.childCount) {
                val child = SmartNextPerf.getChild(node, index, "ImmutableHierarchyCapture.copyNode")
                    ?: throw IllegalStateException("SERIALIZATION_ERROR:child_unavailable index=$index")
                children += copyNode(child, index, depth + 1, count)
            }
            val uniqueId = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) runCatching { node.uniqueId }.getOrNull() else null
            return CapturedHierarchyNode(
                stableIndex = stableIndex, childIndex = childIndex, text = node.text?.toString(),
                contentDescription = node.contentDescription?.toString(), resourceId = node.viewIdResourceName,
                className = node.className?.toString(), packageName = node.packageName?.toString(), sourceNodeId = uniqueId,
                windowId = node.windowId, bounds = CapturedBounds(rect.left, rect.top, rect.right, rect.bottom),
                clickable = node.isClickable, enabled = node.isEnabled, focusable = node.isFocusable,
                focused = node.isFocused, accessibilityFocused = node.isAccessibilityFocused, selected = node.isSelected,
                scrollable = node.isScrollable, checkable = node.isCheckable, checked = node.isChecked,
                visibleToUser = node.isVisibleToUser,
                screenReaderFocusable = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) node.isScreenReaderFocusable else null,
                rangeInfoPresent = node.rangeInfo != null,
                actions = Collections.unmodifiableList(actions), children = Collections.unmodifiableList(children)
            )
        }
    }
}

internal data class CapturedBounds(val left: Int, val top: Int, val right: Int, val bottom: Int) {
    fun rect() = Rect(left, top, right, bottom)
    val isEmpty get() = left >= right || top >= bottom
    val width get() = (right - left).coerceAtLeast(0)
    val height get() = (bottom - top).coerceAtLeast(0)
    fun contains(other: CapturedBounds) = left <= other.left && top <= other.top && right >= other.right && bottom >= other.bottom
}
internal data class CapturedHierarchyAction(val id: Int, val name: String, val label: String?)
internal data class CapturedHierarchyNode(
    val stableIndex: Int, val childIndex: Int?, val text: String?, val contentDescription: String?,
    val resourceId: String?, val className: String?, val packageName: String?, val sourceNodeId: String?,
    val windowId: Int, val bounds: CapturedBounds, val clickable: Boolean, val enabled: Boolean,
    val focusable: Boolean, val focused: Boolean, val accessibilityFocused: Boolean, val selected: Boolean,
    val scrollable: Boolean, val checkable: Boolean, val checked: Boolean, val visibleToUser: Boolean,
    val screenReaderFocusable: Boolean?, val rangeInfoPresent: Boolean,
    val actions: List<CapturedHierarchyAction>, val children: List<CapturedHierarchyNode>
) {
    fun toRawJson(): JSONObject = JSONObject().apply {
        put("text", text ?: JSONObject.NULL); put("contentDescription", contentDescription ?: JSONObject.NULL)
        put("viewIdResourceName", resourceId ?: JSONObject.NULL); put("className", className ?: JSONObject.NULL)
        put("packageName", packageName ?: JSONObject.NULL)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) put("sourceNodeId", sourceNodeId ?: JSONObject.NULL)
        put("windowId", windowId)
        put("boundsInScreen", JSONObject().apply {
            put("l", bounds.left); put("t", bounds.top); put("r", bounds.right); put("b", bounds.bottom)
            put("left", bounds.left); put("top", bounds.top); put("right", bounds.right); put("bottom", bounds.bottom)
        })
        put("clickable", clickable); put("effectiveClickable", clickable); put("enabled", enabled)
        put("focusable", focusable); put("focused", focused); put("inputFocused", focused)
        put("accessibilityFocused", accessibilityFocused); put("selected", selected)
        put("scrollable", scrollable); put("isScrollable", scrollable); put("checkable", checkable); put("checked", checked)
        put("visibleToUser", visibleToUser); put("isVisibleToUser", visibleToUser)
        put("screenReaderFocusable", screenReaderFocusable ?: JSONObject.NULL); put("rangeInfoPresent", rangeInfoPresent)
        put("actions", JSONArray().apply { actions.forEach { a -> put(JSONObject().apply {
            put("id", a.id); put("name", a.name); put("label", a.label ?: JSONObject.NULL)
        }) } })
        put("children", JSONArray().apply { children.forEach { put(it.toRawJson()) } })
        if (childIndex != null) put("childIndex", childIndex)
    }
}

/** Legacy candidate policy evaluated only from the immutable capture DTO. */
internal object ImmutableHierarchyCandidateProjection {
    private data class Metadata(val clickable: Boolean, val focusable: Boolean, val resource: String?, val className: String?, val description: String?)
    private data class Candidate(val node: CapturedHierarchyNode, val path: List<CapturedBounds>, val text: String?, val description: String?, val metadata: Metadata)
    private data class SortPart(val validity: Int, val centerY: Long, val left: Long, val top: Long, val right: Long, val bottom: Long)

    fun build(root: CapturedHierarchyNode): JSONObject {
        val found = mutableListOf<Candidate>()
        collect(root, null, listOf(root.bounds), mutableSetOf(), found)
        val deduped = found.distinctBy { it.node.bounds.rect() }
        val stableOrder = deduped.withIndex().associate { it.value.node.stableIndex to it.index }
        val candidates = deduped.filterNot { excluded(it, root.bounds) }
            .sortedWith { a, b ->
                compareSort(a, b, stableOrder.getValue(a.node.stableIndex), stableOrder.getValue(b.node.stableIndex))
            }
        val screenTop = root.bounds.top
        val screenBottom = root.bounds.bottom
        val screenHeight = (screenBottom - screenTop).coerceAtLeast(1)
        val rows = candidates.map { f ->
            val n = f.node
            val rect = n.bounds.rect()
            JSONObject().apply {
                put("text", f.text ?: n.text ?: JSONObject.NULL)
                put("contentDescription", f.description ?: n.contentDescription ?: JSONObject.NULL)
                put("className", n.className ?: JSONObject.NULL); put("viewIdResourceName", n.resourceId ?: JSONObject.NULL)
                put("boundsInScreen", JSONObject().apply { put("l", rect.left); put("t", rect.top); put("r", rect.right); put("b", rect.bottom) })
                put("clickable", n.clickable); put("focusable", n.focusable); put("isVisibleToUser", n.visibleToUser)
                put("focused", n.focused); put("accessibilityFocused", n.accessibilityFocused)
                put("isTopAppBar", A11yNodeUtils.isTopAppBar(n.className, n.resourceId, rect, screenTop, screenHeight))
                put("isBottomNavigationBar", A11yNodeUtils.isBottomNavigationBar(n.className, n.resourceId, rect, screenBottom, screenHeight))
                put("hasClickableDescendant", f.metadata.clickable); put("hasFocusableDescendant", f.metadata.focusable)
                put("effectiveClickable", n.clickable || f.metadata.clickable)
                put("actionableDescendantResourceId", f.metadata.resource ?: JSONObject.NULL)
                put("actionableDescendantClassName", f.metadata.className ?: JSONObject.NULL)
                put("actionableDescendantContentDescription", f.metadata.description ?: JSONObject.NULL)
            }
        }
        return JSONObject().put("algorithmVersion", A11yNavigator.NAVIGATOR_ALGORITHM_VERSION)
            .put("canScrollDown", canScrollDown(root)).put("nodes", JSONArray().apply { rows.forEach(::put) })
    }

    private fun collect(n: CapturedHierarchyNode, ancestor: CapturedHierarchyNode?, path: List<CapturedBounds>, emitted: MutableSet<Int>, sink: MutableList<Candidate>) {
        if (!n.visibleToUser || n.stableIndex in emitted) return
        val container = isContainer(n)
        if (container) {
            val labels = mergedLabels(n)
            sink += Candidate(n, path, labels.firstOrNull(), labels.getOrNull(1), metadata(n)); emitted += n.stableIndex
        } else if (ancestor == null && hasText(n)) {
            sink += Candidate(n, path, n.text, n.contentDescription, metadata(n)); emitted += n.stableIndex
        } else if (promote(n, ancestor, path.first().rect())) {
            sink += Candidate(n, path, n.text, n.contentDescription, metadata(n)); emitted += n.stableIndex
        }
        val structural = listOf("GridView", "RecyclerView", "ScrollView", "ViewPager").any { n.className.orEmpty().contains(it, true) } || n.resourceId.orEmpty().contains("recycler_view", true)
        val next = if (container && !structural) n else ancestor
        n.children.forEach { collect(it, next, path + it.bounds, emitted, sink) }
        projectAdjustables(n, path, emitted, sink)
    }

    private fun projectAdjustables(owner: CapturedHierarchyNode, path: List<CapturedBounds>, emitted: MutableSet<Int>, sink: MutableList<Candidate>) {
        if (!isContainer(owner) || !owner.visibleToUser || !owner.enabled || owner.bounds.isEmpty) return
        val b = owner.bounds.rect()
        if (A11yNodeUtils.isTopAppBar(owner.className, owner.resourceId, b, 0, 1) || A11yNodeUtils.isBottomNavigationBar(owner.className, owner.resourceId, b, 1, 1)) return
        val tokens = setOf("bottom_nav", "bottomnavigation", "navbar", "nav_bar", "navigation", "tab", "segment")
        if (tokens.any { owner.resourceId.orEmpty().lowercase().contains(it) || owner.className.orEmpty().lowercase().contains(it) }) return
        val queue = ArrayDeque<Pair<CapturedHierarchyNode, List<CapturedBounds>>>()
        owner.children.forEach { queue += it to (path + it.bounds) }
        val seen = mutableSetOf<Int>()
        while (queue.isNotEmpty()) {
            val (n, nPath) = queue.removeFirst()
            if (!seen.add(n.stableIndex) || !n.visibleToUser) continue
            val adjustable = !hasText(n) && n.stableIndex !in emitted && n.enabled && n.focusable && !n.bounds.isEmpty &&
                (n.rangeInfoPresent || n.actions.any { it.id == AccessibilityNodeInfo.AccessibilityAction.ACTION_SET_PROGRESS.id })
            if (adjustable) { sink += Candidate(n, nPath, n.text, n.contentDescription, metadata(n)); emitted += n.stableIndex; continue }
            if (isContainer(n)) continue
            n.children.forEach { queue += it to (nPath + it.bounds) }
        }
    }

    private fun promote(n: CapturedHierarchyNode, ancestor: CapturedHierarchyNode?, root: Rect): Boolean {
        if (ancestor == null) return false
        val label = n.text?.trim()?.takeIf(String::isNotEmpty) ?: n.contentDescription?.trim()?.takeIf(String::isNotEmpty)
        return OneConnectTraversalPolicy.evaluateStaticTextPromotion(
            packageName = n.packageName?.trim().orEmpty(), ancestorPackageName = ancestor.packageName?.trim().orEmpty(),
            className = n.className, readableText = label, clickable = n.clickable, focusable = n.focusable,
            screenReaderFocusable = n.screenReaderFocusable == true, enabled = n.enabled,
            interactiveDescendantExists = countInteractive(n, 1) > 0,
            bounds = n.bounds.rect(), ancestorBounds = ancestor.bounds.rect(), rootBounds = root
        ).accepted
    }

    private fun isContainer(n: CapturedHierarchyNode) = n.clickable || n.focusable || n.screenReaderFocusable == true || A11yTraversalAnalyzer.isSettingsRowViewId(n.resourceId)
    private fun hasText(n: CapturedHierarchyNode) = !n.text?.trim().isNullOrEmpty() || !n.contentDescription?.trim().isNullOrEmpty()
    private fun mergedLabels(n: CapturedHierarchyNode): List<String> { val values = mutableListOf<String>(); readable(n, values); if (values.isEmpty()) return emptyList(); val joined = values.joinToString(" "); return listOf(joined, joined) }
    private fun readable(n: CapturedHierarchyNode, values: MutableList<String>) {
        if (!n.visibleToUser) return
        n.text?.trim()?.takeIf(String::isNotEmpty)?.let(values::add); n.contentDescription?.trim()?.takeIf(String::isNotEmpty)?.let(values::add)
        n.children.forEach { c -> if (c.visibleToUser) if (isContainer(c)) {
            c.text?.trim()?.takeIf(String::isNotEmpty)?.let(values::add); c.contentDescription?.trim()?.takeIf(String::isNotEmpty)?.let(values::add)
        } else readable(c, values) }
    }
    private fun metadata(root: CapturedHierarchyNode): Metadata {
        var hasClick = false; var hasFocus = false; var best: CapturedHierarchyNode? = null; var bestScore = Int.MIN_VALUE; var bestDepth = Int.MAX_VALUE
        val queue = ArrayDeque<Pair<CapturedHierarchyNode, Int>>(); queue += root to 0
        while (queue.isNotEmpty()) {
            val (n, depth) = queue.removeFirst()
            if (depth > 0 && n.visibleToUser) {
                if (n.focusable) hasFocus = true
                if (n.clickable) hasClick = true
                if (n.clickable && n.enabled && !n.bounds.isEmpty) {
                    var score = 100
                    if (!n.contentDescription.isNullOrBlank() || !n.text.isNullOrBlank()) score += 35
                    if (listOf("button", "imagebutton", "floatingactionbutton").any { n.className.orEmpty().contains(it, true) }) score += 30
                    val candidateBounds = n.bounds.rect()
                    val containerBounds = root.bounds.rect()
                    if (containerBounds.contains(candidateBounds) ||
                        containerBounds.contains(candidateBounds.centerX(), candidateBounds.centerY())) score += 20
                    score -= minOf(25, depth)
                    if (score > bestScore || score == bestScore && depth < bestDepth) { best = n; bestScore = score; bestDepth = depth }
                }
            }
            n.children.forEach { queue += it to depth + 1 }
        }
        return Metadata(hasClick, hasFocus, best?.resourceId, best?.className, best?.contentDescription)
    }
    private fun countInteractive(root: CapturedHierarchyNode, limit: Int): Int {
        var count = 0; val queue = ArrayDeque<CapturedHierarchyNode>(); queue += root
        while (queue.isNotEmpty() && count < limit) { val n = queue.removeFirst(); if (n !== root && n.visibleToUser && (n.clickable || n.focusable || n.screenReaderFocusable == true)) count++; n.children.forEach(queue::addLast) }
        return count
    }
    private fun excluded(f: Candidate, root: CapturedBounds): Boolean {
        val n = f.node
        if (A11yTraversalAnalyzer.isSettingsRowViewId(n.resourceId) && n.visibleToUser && (n.clickable || n.focusable)) return false
        val labels = mutableListOf<String>(); readable(n, labels); val recovered = labels.firstOrNull()
        val isComposite = composite(n, labels, root); val isHero = hero(n, labels, root.rect())
        if (excludeContainer(n, labels, root) && !isComposite && !isHero) return true
        if (isComposite && !recovered.isNullOrBlank()) return false
        if (!recovered.isNullOrBlank() && (n.clickable || n.focusable) && allowRecovered(labels)) return false
        if (oneConnectSettings(n, recovered)) return false
        if (n.visibleToUser && n.enabled && n.focusable && !n.bounds.isEmpty && (n.rangeInfoPresent || n.actions.any { it.id == AccessibilityNodeInfo.AccessibilityAction.ACTION_SET_PROGRESS.id })) return false
        return (f.text.isNullOrBlank() && f.description.isNullOrBlank()) && (n.clickable || n.children.isEmpty())
    }
    private fun excludeContainer(n: CapturedHierarchyNode, labels: List<String>, root: CapturedBounds): Boolean {
        if (composite(n, labels, root) || hero(n, labels, root.rect())) return false
        if (A11yNodeUtils.isContainerLikeClassName(n.className) || A11yNodeUtils.isContainerLikeViewId(n.resourceId)) return true
        if (n.children.count { it.visibleToUser && (it.clickable || it.focusable || it.screenReaderFocusable == true) } >= 2) return true
        if (countInteractive(n, 3) >= 3 && coversMost(n, root)) return true
        if (!coversMost(n, root) || countInteractive(n, 3) < 2) return false
        return !allowRecovered(labels)
    }
    private fun composite(n: CapturedHierarchyNode, labels: List<String>, root: CapturedBounds): Boolean {
        if (!n.visibleToUser || !n.clickable || !n.focusable || independent(n.className)) return false
        if (countInteractive(n, 4) < 2 && labels.map(String::trim).filter(String::isNotEmpty).distinct().take(4).size < 2) return false
        if (n.bounds.width <= 0 || n.bounds.height <= 0 || root.width <= 0 || root.height <= 0) return false
        val width = n.bounds.width.toFloat() / root.width; val height = n.bounds.height.toFloat() / root.height
        val area = (n.bounds.width.toLong() * n.bounds.height).toFloat() / (root.width.toLong() * root.height).toFloat()
        return width >= .65f && height >= .10f && area >= .06f
    }
    private fun hero(n: CapturedHierarchyNode, rawLabels: List<String>, root: Rect): Boolean {
        if (!n.visibleToUser || n.clickable || !n.focusable || !OneConnectTraversalPolicy.isOneConnectPackageName(n.packageName)) return false
        val labels = rawLabels.map(String::trim).filter(String::isNotEmpty).distinct(); val recovered = labels.firstOrNull()
        val general = allowRecovered(labels); val length = labels.joinToString(" ").length
        val action = labels.any { it.contains("meal planner", true) || it.contains("saved recipes", true) }
        val meta = labels.any { l -> listOf("kcal", "cal", "min", "serving").any { l.contains(it, true) } }
        val tabOnly = labels.all { l -> listOf("ingredients", "instructions", "reviews").any { l.contains(it, true) } }
        val recipe = labels.size in 3..12 && length in 20..220 && action && meta && !tabOnly
        if (recovered.isNullOrBlank() || (!general && !recipe)) return false
        val b = n.bounds
        if (root.width() <= 0 || root.height() <= 0 || b.width <= 0 || b.height <= 0) return false
        if (A11yNodeUtils.isTopAppBar(n.className, n.resourceId, b.rect(), root.top, root.height()) || A11yNodeUtils.isBottomNavigationBar(n.className, n.resourceId, b.rect(), root.bottom, root.height()) || b.top <= root.top) return false
        if (b.top - root.top > (root.height() * .72f).toInt()) return false
        if (b.height !in (root.height() * .08f).toInt()..(root.height() * .42f).toInt()) return false
        return countInteractive(n, 5) in 1..4
    }
    private fun oneConnectSettings(n: CapturedHierarchyNode, recovered: String?): Boolean {
        if (!n.visibleToUser || !OneConnectTraversalPolicy.isOneConnectPackageName(n.packageName) || (!n.clickable && !n.focusable) || n.bounds.top <= 0 || n.bounds.left < 0) return false
        val id = n.resourceId?.substringAfterLast('/')?.trim().orEmpty().lowercase()
        val label = listOfNotNull(n.contentDescription?.trim()?.takeIf(String::isNotEmpty), recovered?.trim()).joinToString(" ").lowercase()
        return A11yNodeUtils.containsSettingsKeyword(id) || A11yNodeUtils.containsSettingsKeyword(label)
    }
    private fun allowRecovered(values: List<String>): Boolean {
        val normalized = values.map(String::trim).filter(String::isNotEmpty).distinct()
        if (normalized.isEmpty()) return false
        if (normalized.size <= 2) return true
        return normalized.size <= 3 && normalized.joinToString(" ").length <= 60
    }
    private fun independent(className: String?): Boolean { val n = className?.lowercase().orEmpty(); return listOf("button", "switch", "toggle", "checkbox", "radiobutton", "seekbar", "edittext", "spinner").any(n::contains) }
    private fun coversMost(n: CapturedHierarchyNode, root: CapturedBounds): Boolean {
        if (n.bounds.width <= 0 || n.bounds.height <= 0 || root.width <= 0 || root.height <= 0) return false
        val w = n.bounds.width.toFloat() / root.width; val h = n.bounds.height.toFloat() / root.height
        val a = (n.bounds.width.toLong() * n.bounds.height).toFloat() / (root.width.toLong() * root.height).toFloat()
        return w >= .85f && h >= .45f && a >= .40f
    }
    private fun canScrollDown(root: CapturedHierarchyNode): Boolean {
        val queue = ArrayDeque<CapturedHierarchyNode>(); queue += root
        while (queue.isNotEmpty()) { val n = queue.removeFirst(); val ids = n.actions.map { it.id }
            if (n.visibleToUser && n.scrollable && A11yNavigator.scrollAxis(n.className.orEmpty(), ids) in setOf("VERTICAL", "BIDIRECTIONAL") && A11yNavigator.verticalScrollAction("down", ids) != null) return true
            n.children.forEach(queue::addLast)
        }; return false
    }
    private fun compareSort(a: Candidate, b: Candidate, ai: Int, bi: Int): Int {
        val left = a.path.map(::sortPart); val right = b.path.map(::sortPart)
        for (i in 0 until minOf(left.size, right.size)) { val c = compareValuesBy(left[i], right[i], SortPart::validity, SortPart::centerY, SortPart::left, SortPart::top, SortPart::right, SortPart::bottom); if (c != 0) return c }
        val len = left.size.compareTo(right.size); return if (len != 0) len else ai.compareTo(bi)
    }
    private fun sortPart(b: CapturedBounds): SortPart { val top=b.top.toLong();val bottom=b.bottom.toLong();return SortPart(if(b.right>b.left&&b.bottom>b.top)0 else 1,((top+bottom)/2L)/5L,b.left.toLong(),top,b.right.toLong(),bottom) }
}
