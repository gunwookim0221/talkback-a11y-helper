package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo

object OneConnectTraversalPolicy {
    const val VERSION: String = "1.0.0"
    const val PACKAGE_NAME = "com.samsung.android.oneconnect"
    const val UPDATE_APP_CARD_VIEW_ID = "com.samsung.android.oneconnect:id/update_app_card"
    const val UPDATE_APP_TITLE_VIEW_ID = "com.samsung.android.oneconnect:id/update_app_title"
    const val UPDATE_APP_TEXT_VIEW_ID = "com.samsung.android.oneconnect:id/update_app_text"
    const val UPDATE_APP_CLOSE_BUTTON_VIEW_ID = "com.samsung.android.oneconnect:id/update_app_card_close_btn"
    const val UPDATE_BUTTON_VIEW_ID = "com.samsung.android.oneconnect:id/update_button"
    const val NOTIFICATIONS_TITLE_VIEW_ID = "com.samsung.android.oneconnect:id/noti_title"
    const val NOTIFICATIONS_SWITCH_VIEW_ID = "com.samsung.android.oneconnect:id/notification_item_switch"
    const val PREF_TITLE_VIEW_ID = "com.samsung.android.oneconnect:id/pref_title"
    const val ANDROID_TITLE_VIEW_ID = "android:id/title"
    const val ANDROID_SUMMARY_VIEW_ID = "android:id/summary"

    val UPDATE_APP_MEMBER_VIEW_IDS: Set<String> = setOf(
        UPDATE_APP_TITLE_VIEW_ID,
        UPDATE_APP_TEXT_VIEW_ID,
        UPDATE_APP_CLOSE_BUTTON_VIEW_ID,
        UPDATE_BUTTON_VIEW_ID
    )

    data class StaticTextPromotionDecision(
        val accepted: Boolean,
        val reasonCode: String,
        val shouldLog: Boolean
    )

    fun isOneConnectPackageName(packageName: String?): Boolean = packageName?.trim() == PACKAGE_NAME

    fun isUpdateAppMemberViewId(viewId: String?): Boolean = viewId != null && UPDATE_APP_MEMBER_VIEW_IDS.contains(viewId)

    fun evaluateStaticTextPromotion(
        packageName: String,
        ancestorPackageName: String,
        className: String?,
        readableText: String?,
        clickable: Boolean,
        focusable: Boolean,
        screenReaderFocusable: Boolean,
        enabled: Boolean,
        interactiveDescendantExists: Boolean,
        bounds: Rect,
        ancestorBounds: Rect,
        rootBounds: Rect?
    ): StaticTextPromotionDecision {
        val inOneConnect = packageName == PACKAGE_NAME && ancestorPackageName == PACKAGE_NAME
        if (!inOneConnect) return StaticTextPromotionDecision(false, "non_oneconnect_package", false)
        if (readableText.isNullOrBlank()) return StaticTextPromotionDecision(false, "no_readable_text", false)

        val normalizedClass = className?.lowercase().orEmpty()
        if (!normalizedClass.contains("textview")) return StaticTextPromotionDecision(false, "not_text_view", true)
        if (clickable || focusable || screenReaderFocusable) return StaticTextPromotionDecision(false, "interactive_text", true)
        if (!enabled) return StaticTextPromotionDecision(false, "disabled", true)
        if (interactiveDescendantExists) return StaticTextPromotionDecision(false, "interactive_descendant_exists", true)
        if (bounds.width() <= 0 || bounds.height() <= 0) return StaticTextPromotionDecision(false, "invalid_bounds", true)
        if (ancestorBounds.width() <= 0 || ancestorBounds.height() <= 0) return StaticTextPromotionDecision(false, "invalid_ancestor_bounds", true)
        if (bounds.bottom < ancestorBounds.top || bounds.top > ancestorBounds.bottom) {
            return StaticTextPromotionDecision(false, "outside_ancestor_section", true)
        }

        val textLength = readableText.length
        if (bounds.height() < 16 && textLength < 4) return StaticTextPromotionDecision(false, "too_small_short_text", true)
        if (textLength > 260) return StaticTextPromotionDecision(false, "too_long_block_text", true)

        if (rootBounds != null) {
            if (A11yNodeUtils.isTopAppBar(className, null, bounds, rootBounds.top, rootBounds.height())) {
                return StaticTextPromotionDecision(false, "top_app_bar_region", true)
            }
            if (A11yNodeUtils.isBottomNavigationBar(className, null, bounds, rootBounds.bottom, rootBounds.height())) {
                return StaticTextPromotionDecision(false, "bottom_nav_region", true)
            }
        }
        return StaticTextPromotionDecision(true, "oneconnect_readable_static_text", true)
    }

    fun isUpdateAppAliasPair(
        primaryNode: AccessibilityNodeInfo,
        secondaryNode: AccessibilityNodeInfo,
        primaryBounds: Rect,
        secondaryBounds: Rect,
        isAncestorOf: (AccessibilityNodeInfo, AccessibilityNodeInfo) -> Boolean
    ): Boolean {
        val primaryPackage = primaryNode.packageName?.toString()?.trim().orEmpty()
        val secondaryPackage = secondaryNode.packageName?.toString()?.trim().orEmpty()
        if (primaryPackage != PACKAGE_NAME || secondaryPackage != PACKAGE_NAME) return false
        val primaryViewId = primaryNode.viewIdResourceName?.trim().orEmpty()
        val secondaryViewId = secondaryNode.viewIdResourceName?.trim().orEmpty()
        val cardAndMember = when {
            primaryViewId == UPDATE_APP_CARD_VIEW_ID && secondaryViewId in UPDATE_APP_MEMBER_VIEW_IDS ->
                Triple(primaryNode, secondaryNode, secondaryViewId)
            secondaryViewId == UPDATE_APP_CARD_VIEW_ID && primaryViewId in UPDATE_APP_MEMBER_VIEW_IDS ->
                Triple(secondaryNode, primaryNode, primaryViewId)
            else -> null
        } ?: return false
        val cardNode = cardAndMember.first
        val memberNode = cardAndMember.second
        val cardBounds = if (cardNode === primaryNode) primaryBounds else secondaryBounds
        val memberBounds = if (memberNode === primaryNode) primaryBounds else secondaryBounds
        if (!isAncestorOf(cardNode, memberNode)) return false
        return cardBounds.contains(memberBounds)
    }

    fun shouldRejectSettingsRowContainerEarly(node: AccessibilityNodeInfo, isSettingsRowViewId: (String?) -> Boolean): Boolean {
        if (isUpdateAppMemberViewId(node.viewIdResourceName) || node.viewIdResourceName == UPDATE_APP_CARD_VIEW_ID) return true
        val viewId = node.viewIdResourceName?.lowercase().orEmpty()
        if (viewId.contains("wrapperlayout") || viewId.contains("scrollview") || viewId.contains("recycler")) return true
        if (A11yNodeUtils.isContainerLikeClassName(node.className?.toString()) && !isSettingsRowViewId(node.viewIdResourceName)) return true
        return false
    }

    fun isOneConnectPrefTitleNode(node: AccessibilityNodeInfo): Boolean {
        return isOneConnectPackageName(node.packageName?.toString()) && node.viewIdResourceName == PREF_TITLE_VIEW_ID
    }

    fun isSettingsTitleNodeCandidate(node: AccessibilityNodeInfo): Boolean {
        return node.viewIdResourceName == ANDROID_TITLE_VIEW_ID ||
            isOneConnectPrefTitleNode(node) ||
            (!node.text.isNullOrBlank() && !A11yNodeUtils.isContainerLikeClassName(node.className?.toString()))
    }

    fun extendUpdateAppAliasMembers(
        representativeNode: AccessibilityNodeInfo,
        aliasMembers: Collection<AccessibilityNodeInfo>
    ): LinkedHashSet<AccessibilityNodeInfo> {
        val merged = LinkedHashSet<AccessibilityNodeInfo>()
        merged.addAll(aliasMembers)
        val representativeViewId = representativeNode.viewIdResourceName
        if (representativeViewId == UPDATE_APP_CARD_VIEW_ID) {
            val pending = ArrayDeque<AccessibilityNodeInfo>()
            pending.add(representativeNode)
            while (pending.isNotEmpty()) {
                val current = pending.removeFirst()
                for (i in 0 until current.childCount) {
                    val child = current.getChild(i) ?: continue
                    if (child.viewIdResourceName == UPDATE_APP_TITLE_VIEW_ID) {
                        merged.add(child)
                    }
                    pending.add(child)
                }
            }
        } else if (representativeViewId == UPDATE_APP_TITLE_VIEW_ID) {
            var parent = representativeNode.parent
            while (parent != null) {
                if (parent.viewIdResourceName == UPDATE_APP_CARD_VIEW_ID) {
                    merged.add(parent)
                    break
                }
                parent = parent.parent
            }
        }
        return merged
    }

    fun isSettingsDebugTargetNode(
        node: AccessibilityNodeInfo,
        resolvedLabel: String
    ): Boolean {
        if (isOneConnectPackageName(node.packageName?.toString())) return true
        val viewId = node.viewIdResourceName
        if (viewId == UPDATE_APP_CARD_VIEW_ID ||
            viewId == NOTIFICATIONS_TITLE_VIEW_ID ||
            viewId == NOTIFICATIONS_SWITCH_VIEW_ID
        ) return true
        if (viewId == ANDROID_TITLE_VIEW_ID) {
            if (resolvedLabel.contains("samsung account") || resolvedLabel.contains("notifications")) return true
        }
        return resolvedLabel.contains("update app") || resolvedLabel.contains("samsung account") || resolvedLabel.contains("notifications")
    }
}
