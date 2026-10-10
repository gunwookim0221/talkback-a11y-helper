package com.iotpart.sqe.talkbackhelper

import android.view.accessibility.AccessibilityNodeInfo

/** One collection only: invalidation discards both positive and negative entries. */
internal class SnapshotRelationshipCache<N>(private val copy: (N) -> N = { it }, private val generation: () -> Long) {
    private var epoch = generation()
    private val parents = HashMap<N, N?>()
    private val children = HashMap<Pair<N, Int>, N?>()
    var parentHits = 0L; private set
    var parentMisses = 0L; private set
    var childHits = 0L; private set
    var childMisses = 0L; private set

    fun invalidate() {
        parents.clear()
        children.clear()
        epoch = generation()
    }
    private fun sync() {
        if (generation() != epoch) invalidate()
    }
    fun parent(node: N, read: () -> N?): N? {
        sync()
        if (parents.containsKey(node)) {
            val value = parents[node]
            if (generation() == epoch) {
                val returned = value?.let(copy)
                if (generation() == epoch) { parentHits++; return returned }
            }
            invalidate()
        }
        parentMisses++
        val before = generation()
        val value = read()
        if (generation() == before) parents[node] = value?.let(copy) else invalidate()
        return value
    }
    fun child(node: N, index: Int, read: () -> N?): N? {
        sync()
        val key = node to index
        if (children.containsKey(key)) {
            val value = children[key]
            if (generation() == epoch) {
                val returned = value?.let(copy)
                if (generation() == epoch) { childHits++; return returned }
            }
            invalidate()
        }
        childMisses++
        val before = generation()
        val value = read()
        if (generation() == before) children[key] = value?.let(copy) else invalidate()
        return value
    }
}

/** Maps exist only on the collecting worker's stack, never across requests/actions. */
internal object SnapshotRelationshipAccess {
    private val active = ThreadLocal<SnapshotRelationshipCache<AccessibilityNodeInfo>>()
    private val disabled = ThreadLocal<Boolean>()
    fun invalidate() { active.get()?.invalidate() }
    fun parent(node: AccessibilityNodeInfo, read: () -> AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        val cache = active.get()
        return if (cache == null) read() else cache.parent(node, read)
    }
    fun child(node: AccessibilityNodeInfo, index: Int, read: () -> AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        val cache = active.get()
        return if (cache == null) read() else cache.child(node, index, read)
    }
    fun <T> withoutCache(block: () -> T): T {
        val previous = disabled.get()
        disabled.set(true)
        try { return block() } finally { if (previous == null) disabled.remove() else disabled.set(previous) }
    }
    fun <T> collect(block: () -> T): T {
        if (disabled.get() == true) return block()
        val previous = active.get()
        // Android's node cache returns caller-owned copies. Preserve that identity
        // behavior: traversal also uses IdentityHashMap, so shared hit objects
        // must never leak into candidate enumeration or ancestor algorithms.
        val cache = SnapshotRelationshipCache<AccessibilityNodeInfo>(copy = { AccessibilityNodeInfo.obtain(it) }) {
            SmartNextLookupTrace.generation()
        }
        active.set(cache)
        try { return block() } finally {
            SmartNextPerf.count("parent_cache_hits", cache.parentHits)
            SmartNextPerf.count("parent_cache_misses", cache.parentMisses)
            SmartNextPerf.count("child_cache_hits", cache.childHits)
            SmartNextPerf.count("child_cache_misses", cache.childMisses)
            cache.invalidate()
            if (previous == null) active.remove() else active.set(previous)
        }
    }
}
