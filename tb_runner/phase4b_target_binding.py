"""Bind a fresh focus candidate without changing production instance identity."""
from tb_runner.phase4a_planner import production_instance
from tb_runner.scroll_reliability import flat_nodes, normalized_bounds
from tb_runner.traversal_reliability import normalized


def resolve_focus_target(raw, recommendation, scenario):
    target = recommendation["recommended_target"]
    identity = recommendation["recommended_instance_id"]
    matches = [n for n in flat_nodes(raw.get("nodes", [])) if production_instance(dict(
        resource_id=n.get("viewIdResourceName") or n.get("resourceId") or "",
        bounds=normalized_bounds(n.get("boundsInScreen") or n.get("bounds")),
        class_name=n.get("className", "")), scenario) == identity]
    proof = dict(schema_version="phase4b-target-binding-v1", production_instance_id=identity,
                 positional_match_count=len(matches), canonical_path=None, reason="TARGET_DISAPPEARED_OR_AMBIGUOUS")
    eligible = [n for n in matches if normalized(n.get("className")) == normalized(target.get("class_name"))
                and n.get("focusable") is True and n.get("enabled") is True
                and n.get("isVisibleToUser", n.get("visibleToUser")) is True]
    proof["eligible_match_count"] = len(eligible)
    if len(eligible) != 1:
        return None, proof
    selected = eligible[0]
    if len(matches) > 1:
        path = selected.get("stable_node_path")
        paths = [n.get("stable_node_path") for n in matches]
        if not path or not all(isinstance(p, str) and p for p in paths) or len(set(paths)) != len(paths):
            proof["reason"] = "WRAPPER_HIERARCHY_NOT_PROVEN"
            return None, proof
        for node in matches:
            if node is selected:
                continue
            other = node["stable_node_path"]
            # Only observed ancestors/descendants with no action or focus are
            # presentation wrappers. Never discard another actionable control.
            related = path.startswith(other + ".") or other.startswith(path + ".")
            if (not related or node.get("focusable") is not False or node.get("clickable") is not False
                    or node.get("accessibilityFocused") is not False
                    or any(node.get(k) for k in ("text", "contentDescription", "talkbackLabel", "mergedLabel"))):
                proof["reason"] = "DISTINCT_OR_UNPROVEN_LOGICAL_TARGETS"
                return None, proof
        proof["reason"] = "CANONICAL_FOCUSABLE_NODE_WITH_NON_ACTIONABLE_WRAPPERS"
    else:
        proof["reason"] = "UNIQUE_FRESH_FOCUS_TARGET"
    proof["canonical_path"] = selected.get("stable_node_path")
    return selected, proof


def actual_target_matches(node, target):
    """A positional alias alone cannot verify controlled target landing."""
    return bool(isinstance(node, dict) and node.get("accessibilityFocused") is True
        and normalized_bounds(node.get("boundsInScreen") or node.get("bounds")) == target.get("bounds")
        and normalized(node.get("viewIdResourceName") or node.get("resourceId")) == normalized(target.get("resource_id"))
        and normalized(node.get("className")) == normalized(target.get("class_name")))
