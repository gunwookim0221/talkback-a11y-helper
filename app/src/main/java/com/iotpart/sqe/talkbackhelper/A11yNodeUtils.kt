package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo

/**
 * UI 노드의 속성 판별 및 검색을 위한 유틸리티 모음
 */
object A11yNodeUtils {
    const val VERSION: String = "1.2.0"

    private val SETTINGS_BUTTON_KEYWORDS = listOf("setting_button_layout", "settings", "setting", "gear")

    private val TOP_APP_BAR_CLASS_KEYWORDS = listOf("toolbar", "actionbar", "appbarlayout")
    private val TOP_APP_BAR_VIEW_ID_KEYWORDS = listOf(
        "title_bar",
        "header",
        "toolbar",
        "more_menu",
        "action_bar",
        "home_button",
        "tab_title",
        "header_bar",
        "add_menu",
        "add_button",
        "menu_button"
    )

    private val BOTTOM_NAV_CLASS_KEYWORDS = listOf("bottomnavigation", "tablayout", "navigationbar")
    private val BOTTOM_NAV_VIEW_ID_KEYWORDS = listOf(
        "bottom",
        "footer",
        "tab_bar",
        "navigation",
        "menu_bar",
        "menu_favorites",
        "menu_devices",
        "menu_life",
        "menu_services",
        "menu_automations",
        "menu_more",
        "menu_routines",
        "menu_menu",
        "bottom_menu",
        "bottom_tab",
        "bottom_nav"
    )

    private val TRAVERSAL_CONTAINER_CLASS_KEYWORDS = listOf(
        "scrollview",
        "horizontalscrollview",
        "nestedscrollview",
        "recyclerview"
    )
    private val TRAVERSAL_CONTAINER_VIEW_ID_KEYWORDS = listOf(
        "mainscrollview",
        "content_container",
        "root_container",
        "main_content_container",
        "feature_item_menu",
        "section_wrapper",
        "group_wrapper",
        "row_container",
        "grid_container"
    )

    fun containsSettingsKeyword(value: String?): Boolean {
        val normalized = value?.lowercase().orEmpty()
        if (normalized.isEmpty()) return false
        return SETTINGS_BUTTON_KEYWORDS.any { keyword -> normalized.contains(keyword) }
    }

    fun isTopAppBar(node: AccessibilityNodeInfo?, screenTop: Int, screenHeight: Int): Boolean {
        if (node == null) return false
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        return isTopAppBar(node.className?.toString(), node.viewIdResourceName, bounds, screenTop, screenHeight)
    }

    fun isTopAppBar(
        className: String?,
        viewIdResourceName: String?,
        boundsInScreen: Rect,
        screenTop: Int,
        screenHeight: Int
    ): Boolean {
        val normalizedClass = className?.lowercase().orEmpty()
        val normalizedViewId = viewIdResourceName?.lowercase().orEmpty()
        if (containsSettingsKeyword(normalizedViewId)) {
            return false
        }

        if (TOP_APP_BAR_CLASS_KEYWORDS.any { keyword -> normalizedClass.contains(keyword) }) {
            return true
        }

        return TOP_APP_BAR_VIEW_ID_KEYWORDS.any { keyword -> normalizedViewId.contains(keyword) }
    }

    fun isBottomNavigationBar(node: AccessibilityNodeInfo?, screenBottom: Int, screenHeight: Int): Boolean {
        if (node == null) return false
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        return isBottomNavigationBar(node.className?.toString(), node.viewIdResourceName, bounds, screenBottom, screenHeight)
    }

    fun isBottomNavigationBar(
        className: String?,
        viewIdResourceName: String?,
        boundsInScreen: Rect,
        screenBottom: Int,
        screenHeight: Int
    ): Boolean {
        val normalizedClass = className?.lowercase().orEmpty()
        val normalizedViewId = viewIdResourceName?.lowercase().orEmpty()

        if (BOTTOM_NAV_CLASS_KEYWORDS.any { keyword -> normalizedClass.contains(keyword) }) {
            return true
        }

        return BOTTOM_NAV_VIEW_ID_KEYWORDS.any { keyword -> normalizedViewId.contains(keyword) }
    }

    fun isContainerLikeClassName(className: String?): Boolean {
        val normalized = className?.trim()?.lowercase().orEmpty()
        if (normalized.isEmpty()) return false
        return TRAVERSAL_CONTAINER_CLASS_KEYWORDS.any { keyword -> normalized.contains(keyword) }
    }

    fun isContainerLikeViewId(viewIdResourceName: String?): Boolean {
        val normalized = viewIdResourceName?.substringAfterLast('/')?.trim()?.lowercase().orEmpty()
        if (normalized.isEmpty()) return false
        return TRAVERSAL_CONTAINER_VIEW_ID_KEYWORDS.any { keyword -> normalized.contains(keyword) }
    }

    fun findBestScrollableContainer(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (root == null) return null
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)

        var bestNode: AccessibilityNodeInfo? = null
        var maxArea = -1L

        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            if (node.isScrollable) {
                val bounds = Rect().also { node.getBoundsInScreen(it) }
                val area = bounds.width().toLong() * bounds.height().toLong()
                if (area > maxArea) {
                    maxArea = area
                    bestNode = node
                }
            }
            for (index in 0 until node.childCount) {
                node.getChild(index)?.let(queue::add)
            }
        }
        return bestNode
    }



    fun isNodePhysicallyOffScreen(bounds: Rect, screenTop: Int, screenBottom: Int): Boolean {
        return bounds.bottom <= screenTop || bounds.top >= screenBottom
    }

    fun isWithinTopContentArea(
        nodeTop: Int,
        screenTop: Int,
        screenHeight: Int,
        topAreaMaxPx: Int = 500
    ): Boolean {
        val topAreaBoundary = screenTop + minOf(screenHeight / 5, topAreaMaxPx)
        return nodeTop < topAreaBoundary
    }

    fun isHeaderLikeCandidate(
        className: String?,
        viewIdResourceName: String?,
        label: String?,
        boundsInScreen: Rect,
        screenTop: Int,
        screenHeight: Int
    ): Boolean {
        val normalizedClass = className?.lowercase().orEmpty()
        val normalizedViewId = viewIdResourceName?.lowercase().orEmpty()
        val normalizedLabel = label?.lowercase().orEmpty()
        val topBoundary = screenTop + (screenHeight * 0.3f).toInt()
        if (boundsInScreen.top > topBoundary) return false

        val headerKeywordMatched =
            normalizedViewId.contains("toolbar") ||
                normalizedViewId.contains("appbar") ||
                normalizedViewId.contains("header") ||
                normalizedViewId.contains("title") ||
                normalizedViewId.contains("logo") ||
                normalizedViewId.contains("setting_button") ||
                normalizedViewId.contains("settings")
        val classKeywordMatched =
            normalizedClass.contains("toolbar") ||
                normalizedClass.contains("appbarlayout") ||
                normalizedClass.contains("actionbar")
        val labelKeywordMatched =
            normalizedLabel.contains("settings") ||
                normalizedLabel.contains("setting")
        return headerKeywordMatched || classKeywordMatched || labelKeywordMatched
    }

    fun isNodeFullyVisible(bounds: Rect, screenTop: Int, effectiveBottom: Int): Boolean {
        return bounds.top >= screenTop && bounds.bottom <= effectiveBottom
    }

    fun isNodeBottomClipped(bounds: Rect, effectiveBottom: Int, boundaryPaddingPx: Int = 16): Boolean {
        return bounds.bottom > effectiveBottom || bounds.bottom >= (effectiveBottom - boundaryPaddingPx)
    }

    fun shouldLiftTrailingContentBeforeFocus(
        bounds: Rect,
        effectiveBottom: Int,
        trailingEdgeThresholdPx: Int = 60,
        thinTrailingHeightPx: Int = 96
    ): Boolean {
        val height = (bounds.bottom - bounds.top).coerceAtLeast(0)
        val touchesBottomEdge = bounds.bottom >= (effectiveBottom - trailingEdgeThresholdPx)
        return height in 1..thinTrailingHeightPx && touchesBottomEdge
    }

    fun isNodePoorlyPositionedForFocus(
        bounds: Rect,
        screenTop: Int,
        effectiveBottom: Int,
        readableBottomZoneRatio: Float = 0.2f
    ): Boolean {
        if (!isNodeFullyVisible(bounds, screenTop, effectiveBottom)) return true
        if (isNodeBottomClipped(bounds, effectiveBottom)) return true
        if (shouldLiftTrailingContentBeforeFocus(bounds, effectiveBottom)) return true
        val safeBottom = effectiveBottom - ((effectiveBottom - screenTop) * readableBottomZoneRatio).toInt()
        return bounds.bottom > safeBottom
    }

    internal fun <T> isDescendantOf(
        ancestor: T,
        node: T,
        parentOf: (T) -> T?
    ): Boolean {
        var current = parentOf(node)
        while (current != null) {
            if (current == ancestor) return true
            current = parentOf(current)
        }
        return false
    }

    internal fun <T> isFixedSystemUI(
        node: T,
        mainScrollContainer: T?,
        parentOf: (T) -> T?,
        classNameOf: (T) -> String?,
        viewIdOf: (T) -> String?,
        textOf: (T) -> String?,
        contentDescriptionOf: (T) -> String?
    ): Boolean {
        val toolbarKeywords = listOf("toolbar", "actionbar", "bottomnavigationview")
        var current: T? = node
        while (current != null) {
            val className = classNameOf(current)?.lowercase().orEmpty()
            val viewId = viewIdOf(current)?.lowercase().orEmpty()
            if (toolbarKeywords.any { keyword -> className.contains(keyword) || viewId.contains(keyword) }) {
                return true
            }
            current = parentOf(current)
        }

        val className = classNameOf(node)?.substringAfterLast('.')?.lowercase().orEmpty()
        val isStrictFixedButtonClass = className == "button" || className == "imagebutton"
        if (!isStrictFixedButtonClass) {
            return false
        }

        val outsideMainScroll = mainScrollContainer == null || (node != mainScrollContainer && !isDescendantOf(mainScrollContainer, node, parentOf))
        if (outsideMainScroll) {
            return true
        }

        val normalizedLabel = listOfNotNull(textOf(node), contentDescriptionOf(node))
            .joinToString(separator = " ")
            .lowercase()
        val isSystemButton = normalizedLabel.contains("add") || normalizedLabel.contains("more options")
        return isSystemButton && outsideMainScroll
    }

    internal fun isFixedSystemUI(node: AccessibilityNodeInfo, mainScrollContainer: AccessibilityNodeInfo?): Boolean {
        if (A11yTraversalAnalyzer.isOneConnectSettingsCandidateNode(node)) {
            return false
        }
        return isFixedSystemUI(
            node = node,
            mainScrollContainer = mainScrollContainer,
            parentOf = { it.parent },
            classNameOf = { it.className?.toString() },
            viewIdOf = { it.viewIdResourceName },
            textOf = { it.text?.toString() },
            contentDescriptionOf = { it.contentDescription?.toString() }
        )
    }

    internal fun isContentNode(
        node: AccessibilityNodeInfo,
        bounds: Rect,
        screenTop: Int,
        screenBottom: Int,
        screenHeight: Int,
        mainScrollContainer: AccessibilityNodeInfo?
    ): Boolean {
        val isBottomNav = isBottomNavigationBar(
            className = node.className?.toString(),
            viewIdResourceName = node.viewIdResourceName,
            boundsInScreen = bounds,
            screenBottom = screenBottom,
            screenHeight = screenHeight
        )
        if (isBottomNav) return false
        val isTopBar = isTopAppBar(
            className = node.className?.toString(),
            viewIdResourceName = node.viewIdResourceName,
            boundsInScreen = bounds,
            screenTop = screenTop,
            screenHeight = screenHeight
        )
        if (isTopBar) return false
        if (isFixedSystemUI(node, mainScrollContainer)) return false
        val hasDescendantLabel = !A11yTraversalAnalyzer.recoverDescendantLabel(node).isNullOrBlank()
        val usableLabel = !node.contentDescription?.toString().isNullOrBlank() || !node.text?.toString().isNullOrBlank() || hasDescendantLabel
        val traversable = node.isVisibleToUser && !isNodePhysicallyOffScreen(bounds, screenTop, screenBottom)
        val interactive = node.isClickable || node.isFocusable || hasDescendantLabel
        val isContainerOnly = node == mainScrollContainer
        return traversable && interactive && usableLabel && !isContainerOnly
    }
}
