"""Offline same-input equivalence checks for Kotlin legacy and v2 candidates."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .reliable_hierarchy_schema import (
    CANDIDATE_CONTRACT_VERSION,
    CANDIDATE_SCHEMA_VERSION,
    RAW_SCHEMA_VERSION,
    CAPTURE_ENVELOPE_SCHEMA_VERSION,
    CAPTURE_CANONICALIZATION_VERSION,
    CAPTURE_ROOT_IDENTITY_VERSION,
    ReliableHierarchySchemaError,
    decode_reliable_hierarchy_payload,
    legacy_dump_tree_response,
)


FIXTURE_SCHEMA = "talkback-candidate-equivalence-inputs.v1"
PAIR_SCHEMA = "talkback-candidate-equivalence-pairs.v1"
VERDICT_EXACT = "EXACT_EQUIVALENT"
VERDICT_SEMANTIC = "SEMANTIC_EQUIVALENT"
VERDICT_KNOWN = "KNOWN_INTENTIONAL_DIFFERENCE"
VERDICT_INCOMPATIBLE = "INCOMPATIBLE"
VERDICT_NONCOMPARABLE = "NONCOMPARABLE"

_TRAVERSAL_IMPACTING_CLASSES = {
    "CANDIDATE_MEMBERSHIP",
    "ORDER",
    "LABEL",
    "BOUNDS",
    "IDENTITY_INPUT",
    "FOCUS_STATE",
    "ACTIONABILITY",
    "VISIBILITY",
    "SCROLL_METADATA",
    "DEVICE_COLLECTION",
    "SCHEMA",
    "OTHER",
}
_CANDIDATE_FIELDS = {
    "text",
    "contentDescription",
    "className",
    "viewIdResourceName",
    "boundsInScreen",
    "clickable",
    "focusable",
    "isVisibleToUser",
    "focused",
    "accessibilityFocused",
    "isTopAppBar",
    "isBottomNavigationBar",
    "hasClickableDescendant",
    "hasFocusableDescendant",
    "effectiveClickable",
    "actionableDescendantResourceId",
    "actionableDescendantClassName",
    "actionableDescendantContentDescription",
}
_FIELD_CLASS = {
    "text": "LABEL",
    "contentDescription": "LABEL",
    "boundsInScreen": "BOUNDS",
    "viewIdResourceName": "IDENTITY_INPUT",
    "focused": "FOCUS_STATE",
    "accessibilityFocused": "FOCUS_STATE",
    "isVisibleToUser": "VISIBILITY",
    "clickable": "ACTIONABILITY",
    "focusable": "ACTIONABILITY",
    "isTopAppBar": "ACTIONABILITY",
    "isBottomNavigationBar": "ACTIONABILITY",
    "hasClickableDescendant": "ACTIONABILITY",
    "hasFocusableDescendant": "ACTIONABILITY",
    "effectiveClickable": "ACTIONABILITY",
    "actionableDescendantResourceId": "ACTIONABILITY",
    "actionableDescendantClassName": "ACTIONABILITY",
    "actionableDescendantContentDescription": "ACTIONABILITY",
}


@dataclass(frozen=True)
class CandidateDifference:
    difference_class: str
    path: str
    legacy_value: Any
    v2_value: Any
    traversal_impacting: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "class": self.difference_class,
            "path": self.path,
            "legacy": self.legacy_value,
            "v2": self.v2_value,
            "traversal_impacting": self.traversal_impacting,
        }


def canonical_input_sha256(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _classify_field(field: str) -> str:
    if field in _FIELD_CLASS:
        return _FIELD_CLASS[field]
    if field in {"className"}:
        return "IDENTITY_INPUT"
    if field in _CANDIDATE_FIELDS:
        return "OTHER"
    if field == "canScrollDown" or field.startswith("scroll"):
        return "SCROLL_METADATA"
    if field == "deviceCollection":
        return "DEVICE_COLLECTION"
    return "SCHEMA" if field in {"algorithmVersion"} else "OTHER"


def compare_candidate_responses(
    legacy: Mapping[str, Any], v2_compat: Mapping[str, Any]
) -> list[CandidateDifference]:
    """Compare the complete legacy response shape with C3's adapted response."""
    differences: list[CandidateDifference] = []
    legacy_nodes = legacy.get("nodes")
    v2_nodes = v2_compat.get("nodes")
    if not isinstance(legacy_nodes, list) or not isinstance(v2_nodes, list):
        return [CandidateDifference(
            "SCHEMA", "nodes", legacy_nodes, v2_nodes, True
        )]

    if len(legacy_nodes) != len(v2_nodes):
        differences.append(CandidateDifference(
            "CANDIDATE_MEMBERSHIP", "nodes.length", len(legacy_nodes), len(v2_nodes), True
        ))
    elif Counter(_full_candidate_key(item) for item in legacy_nodes) == Counter(
        _full_candidate_key(item) for item in v2_nodes
    ) and legacy_nodes != v2_nodes:
        differences.append(CandidateDifference(
            "ORDER", "nodes", legacy_nodes, v2_nodes, True
        ))
    else:
        for index in range(min(len(legacy_nodes), len(v2_nodes))):
            left, right = legacy_nodes[index], v2_nodes[index]
            if not isinstance(left, Mapping) or not isinstance(right, Mapping):
                if left != right:
                    differences.append(CandidateDifference(
                        "CANDIDATE_MEMBERSHIP", f"nodes[{index}]", left, right, True
                    ))
                continue
            fields = sorted(set(left) | set(right))
            for field in fields:
                left_value = left.get(field, _MISSING)
                right_value = right.get(field, _MISSING)
                if left_value != right_value:
                    difference_class = _classify_field(field)
                    differences.append(CandidateDifference(
                        difference_class,
                        f"nodes[{index}].{field}",
                        _visible_value(left_value),
                        _visible_value(right_value),
                        difference_class in _TRAVERSAL_IMPACTING_CLASSES,
                    ))

    for field in sorted((set(legacy) | set(v2_compat)) - {"nodes"}):
        left_value = legacy.get(field, _MISSING)
        right_value = v2_compat.get(field, _MISSING)
        if left_value != right_value:
            difference_class = _classify_field(field)
            differences.append(CandidateDifference(
                difference_class,
                field,
                _visible_value(left_value),
                _visible_value(right_value),
                difference_class in _TRAVERSAL_IMPACTING_CLASSES,
            ))
    return differences


class _Missing:
    def __repr__(self) -> str:
        return "<MISSING>"


_MISSING = _Missing()


def _visible_value(value: Any) -> Any:
    return "<MISSING>" if value is _MISSING else value


def _full_candidate_key(candidate: Any) -> str:
    return json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fixture_map(input_path: Path) -> tuple[dict[str, Mapping[str, Any]], str]:
    source = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(source, Mapping) or source.get("fixture_schema") != FIXTURE_SCHEMA:
        raise ValueError("C4_INPUT_FIXTURE_SCHEMA_INVALID")
    fixtures = source.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("C4_INPUT_FIXTURES_MISSING")
    result: dict[str, Mapping[str, Any]] = {}
    for fixture in fixtures:
        if not isinstance(fixture, Mapping) or not isinstance(fixture.get("fixture_id"), str):
            raise ValueError("C4_INPUT_FIXTURE_ID_INVALID")
        fixture_id = fixture["fixture_id"]
        if fixture_id in result:
            raise ValueError(f"C4_INPUT_FIXTURE_DUPLICATE:{fixture_id}")
        result[fixture_id] = fixture
    return result, hashlib.sha256(input_path.read_bytes()).hexdigest()


def _capabilities() -> dict[str, Any]:
    return {
        "payload_schema_version": RAW_SCHEMA_VERSION,
        "supported_payload_schema_versions": [RAW_SCHEMA_VERSION],
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "supported_candidate_schema_versions": [CANDIDATE_SCHEMA_VERSION],
        "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
        "capture_envelope_schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
        "supported_capture_envelope_schema_versions": [CAPTURE_ENVELOPE_SCHEMA_VERSION],
        "capture_canonicalization_version": CAPTURE_CANONICALIZATION_VERSION,
        "supported_capture_canonicalization_versions": [CAPTURE_CANONICALIZATION_VERSION],
        "capture_root_id_version": CAPTURE_ROOT_IDENTITY_VERSION,
        "supported_capture_root_id_versions": [CAPTURE_ROOT_IDENTITY_VERSION],
        "capabilities": [
            "content_provider_pfd",
            "service_hierarchy_v2",
            CANDIDATE_SCHEMA_VERSION,
            CAPTURE_ENVELOPE_SCHEMA_VERSION,
            CAPTURE_CANONICALIZATION_VERSION,
            CAPTURE_ROOT_IDENTITY_VERSION,
        ],
    }


def _load_pair_files(pair_paths: Sequence[Path]) -> list[Mapping[str, Any]]:
    pairs: list[Mapping[str, Any]] = []
    for path in pair_paths:
        source = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(source, Mapping) or source.get("fixture_schema") != PAIR_SCHEMA:
            raise ValueError(f"C4_PAIR_SCHEMA_INVALID:{path}")
        items = source.get("pairs")
        if not isinstance(items, list):
            raise ValueError(f"C4_PAIR_LIST_MISSING:{path}")
        pairs.extend(items)
    return pairs


def run_candidate_equivalence(
    input_path: Path, pair_paths: Sequence[Path]
) -> dict[str, Any]:
    """Verify pair provenance, decode through C3, and compare every candidate field."""
    fixtures, input_file_digest = _fixture_map(input_path)
    pairs = _load_pair_files(pair_paths)
    by_id: dict[str, Mapping[str, Any]] = {}
    for pair in pairs:
        fixture_id = pair.get("fixture_id") if isinstance(pair, Mapping) else None
        if not isinstance(fixture_id, str) or fixture_id in by_id:
            raise ValueError(f"C4_PAIR_ID_INVALID_OR_DUPLICATE:{fixture_id}")
        by_id[fixture_id] = pair

    results: list[dict[str, Any]] = []
    for fixture_id, fixture in fixtures.items():
        pair = by_id.get(fixture_id)
        if pair is None:
            results.append({
                "fixture_id": fixture_id,
                "input_sha256": input_file_digest,
                "verdict": VERDICT_NONCOMPARABLE,
                "difference_count": 1,
                "traversal_impacting_difference_count": 1,
                "differences": [{
                    "class": "SCHEMA",
                    "path": "pair",
                    "legacy": "<MISSING>",
                    "v2": "<MISSING>",
                    "traversal_impacting": True,
                }],
                "root_binding_valid": False,
                "schema_versions_valid": False,
                "raw_input_match": False,
            })
            continue

        expected_digest = input_file_digest
        provenance_errors = []
        if pair.get("input_sha256") != expected_digest:
            provenance_errors.append("INPUT_DIGEST_MISMATCH")
        if pair.get("legacy_generator_version") != "2.76.3":
            provenance_errors.append("LEGACY_GENERATOR_VERSION_MISMATCH")
        if pair.get("analyzer_version") != "1.11.1":
            provenance_errors.append("ANALYZER_VERSION_MISMATCH")
        if pair.get("raw_schema_version") != RAW_SCHEMA_VERSION:
            provenance_errors.append("RAW_SCHEMA_VERSION_MISMATCH")
        if pair.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION:
            provenance_errors.append("CANDIDATE_SCHEMA_VERSION_MISMATCH")
        if pair.get("candidate_contract_version") != CANDIDATE_CONTRACT_VERSION:
            provenance_errors.append("CANDIDATE_CONTRACT_VERSION_MISMATCH")

        payload = pair.get("v2_payload")
        legacy = pair.get("legacy_output")
        decoded = None
        v2_compat: Mapping[str, Any] | None = None
        decode_error = None
        try:
            if not isinstance(payload, Mapping) or not isinstance(legacy, Mapping):
                raise ValueError("C4_PAIR_BODY_MISSING")
            transport_metadata = pair.get("capture_transport_metadata")
            if not isinstance(transport_metadata, Mapping):
                raise ValueError("C4_PAIR_CAPTURE_TRANSPORT_METADATA_MISSING")
            decoded = decode_reliable_hierarchy_payload(
                payload,
                capabilities=_capabilities(),
                transport_metadata=transport_metadata,
            )
            v2_compat = legacy_dump_tree_response(decoded)
        except (ReliableHierarchySchemaError, ValueError, TypeError) as exc:
            decode_error = str(exc)

        raw_input_match = decoded is not None and _raw_payload_matches_input(payload, fixture)
        if decoded is not None and not raw_input_match:
            provenance_errors.append("RAW_INPUT_MISMATCH")
        root_binding_valid = decoded is not None and (
            payload.get("traversalRootRef") == decoded.traversal_root_ref
            and payload.get("traversalRootWindowId") == decoded.traversal_root_window_id
        ) and pair.get("root_binding_valid") is True
        schema_versions_valid = not provenance_errors and decoded is not None
        differences = (
            compare_candidate_responses(legacy, v2_compat)
            if isinstance(legacy, Mapping) and isinstance(v2_compat, Mapping)
            else []
        )
        if provenance_errors or decode_error:
            verdict = VERDICT_NONCOMPARABLE
            differences.append(CandidateDifference(
                "SCHEMA",
                "provenance_or_decode",
                provenance_errors or None,
                decode_error,
                True,
            ))
        elif differences:
            verdict = VERDICT_INCOMPATIBLE if any(d.traversal_impacting for d in differences) else VERDICT_KNOWN
        else:
            verdict = VERDICT_EXACT

        legacy_count = len(legacy.get("nodes", [])) if isinstance(legacy, Mapping) and isinstance(legacy.get("nodes"), list) else None
        v2_count = decoded.traversal_candidates.candidate_count if decoded else None
        if pair.get("legacy_candidate_count") != legacy_count or pair.get("v2_candidate_count") != v2_count:
            differences.append(CandidateDifference(
                "SCHEMA", "candidate_count_provenance", pair.get("legacy_candidate_count"), v2_count, True
            ))
            verdict = VERDICT_NONCOMPARABLE

        results.append({
            "fixture_id": fixture_id,
            "input_sha256": expected_digest,
            "input_file_sha256": input_file_digest,
            "legacy_candidate_count": legacy_count,
            "v2_candidate_count": v2_count,
            "verdict": verdict,
            "difference_count": len(differences),
            "traversal_impacting_difference_count": sum(d.traversal_impacting for d in differences),
            "differences": [difference.to_dict() for difference in differences],
            "root_binding_valid": root_binding_valid,
            "schema_versions_valid": schema_versions_valid,
            "raw_input_match": raw_input_match,
            "decode_error": decode_error,
        })

    extra_pair_ids = sorted(set(by_id) - set(fixtures))
    counts = Counter(result["verdict"] for result in results)
    all_differences = [difference for result in results for difference in result["differences"]]
    home = next((result for result in results if result["fixture_id"] == "home_monitor"), None)
    home_pair = by_id.get("home_monitor")
    home_labels = _home_monitor_content_valid(home_pair, fixtures.get("home_monitor"))
    passed = (
        len(results) > 0
        and len(by_id) == len(fixtures)
        and not extra_pair_ids
        and home is not None
        and home["verdict"] in {VERDICT_EXACT, VERDICT_SEMANTIC}
        and home_labels
        and counts[VERDICT_INCOMPATIBLE] == 0
        and counts[VERDICT_NONCOMPARABLE] == 0
        and sum(difference["traversal_impacting"] for difference in all_differences) == 0
        and all(result["root_binding_valid"] for result in results)
        and all(result["schema_versions_valid"] for result in results)
        and all(result["raw_input_match"] for result in results)
    )
    return {
        "fixture_schema": "talkback-candidate-equivalence-results.v1",
        "input_file_sha256": input_file_digest,
        "paired_fixture_count": len(by_id),
        "fixture_count": len(fixtures),
        "fixture_ids": [result["fixture_id"] for result in results],
        "extra_pair_ids": extra_pair_ids,
        "exact_equivalent_count": counts[VERDICT_EXACT],
        "semantic_equivalent_count": counts[VERDICT_SEMANTIC],
        "known_intentional_difference_count": counts[VERDICT_KNOWN],
        "incompatible_count": counts[VERDICT_INCOMPATIBLE],
        "noncomparable_count": counts[VERDICT_NONCOMPARABLE],
        "traversal_impacting_difference_count": sum(
            difference["traversal_impacting"] for difference in all_differences
        ),
        "root_binding_all_pass": all(result["root_binding_valid"] for result in results),
        "schema_versions_all_pass": all(result["schema_versions_valid"] for result in results),
        "raw_input_all_pass": all(result["raw_input_match"] for result in results),
        "home_monitor_pair_present": home_pair is not None,
        "home_monitor_equivalence_pass": bool(
            home is not None and home["verdict"] in {VERDICT_EXACT, VERDICT_SEMANTIC} and home_labels
        ),
        "no_legacy_rescue": True,
        "no_raw_flattening_fallback": True,
        "passed": passed,
        "results": results,
    }


def _raw_payload_matches_input(payload: Mapping[str, Any], fixture: Mapping[str, Any]) -> bool:
    """Compare the complete fixed input tree with the serialized v2 raw tree."""
    root_ref = payload.get("traversalRootRef")
    if not isinstance(root_ref, str) or not root_ref.startswith("windows[") or not root_ref.endswith("].root"):
        return False
    index_text = root_ref[len("windows[") : -len("].root")]
    if not index_text.isdigit() or str(int(index_text)) != index_text:
        return False
    windows = payload.get("windows")
    if not isinstance(windows, list) or int(index_text) >= len(windows):
        return False
    window = windows[int(index_text)]
    expected_root = fixture.get("root")
    actual_root = window.get("root") if isinstance(window, Mapping) else None
    api_level = fixture.get("platform_api_level")
    if not isinstance(expected_root, Mapping) or not isinstance(actual_root, Mapping):
        return False
    if type(api_level) is not int or payload.get("platformApiLevel") != api_level:
        return False

    def matches(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
        expected_bounds = expected.get("bounds", [0, 0, 1080, 2400])
        if not isinstance(expected_bounds, list) or len(expected_bounds) != 4:
            return False
        bounds = actual.get("boundsInScreen")
        if not isinstance(bounds, Mapping) or [bounds.get(key) for key in ("l", "t", "r", "b")] != expected_bounds:
            return False

        scalar_fields = {
            "className": expected.get("className", "android.widget.FrameLayout"),
            "packageName": expected.get("packageName", "com.samsung.android.oneconnect"),
            "text": expected.get("text"),
            "contentDescription": expected.get("description"),
            "viewIdResourceName": expected.get("resourceId"),
            "clickable": expected.get("clickable", False),
            "focusable": expected.get("focusable", False),
            "enabled": expected.get("enabled", True),
            "focused": expected.get("focused", False),
            "inputFocused": expected.get("focused", False),
            "accessibilityFocused": expected.get("accessibilityFocused", False),
            "selected": expected.get("selected", False),
            "scrollable": expected.get("scrollable", False),
            "isScrollable": expected.get("scrollable", False),
            "visibleToUser": expected.get("visible", True),
            "isVisibleToUser": expected.get("visible", True),
            "effectiveClickable": expected.get("clickable", False),
            "rangeInfoPresent": "rangeInfo" in expected,
        }
        if any(actual.get(key) != value for key, value in scalar_fields.items()):
            return False
        expected_screen_reader_focusable = (
            expected.get("screenReaderFocusable", False) if api_level >= 28 else None
        )
        if actual.get("screenReaderFocusable") != expected_screen_reader_focusable:
            return False

        expected_actions = expected.get("actions", [])
        actual_actions = actual.get("actions")
        if not isinstance(expected_actions, list) or not isinstance(actual_actions, list):
            return False
        actual_action_ids = [action.get("id") for action in actual_actions if isinstance(action, Mapping)]
        if len(actual_action_ids) != len(actual_actions) or actual_action_ids != expected_actions:
            return False

        expected_children = expected.get("children", [])
        actual_children = actual.get("children")
        if not isinstance(expected_children, list) or not isinstance(actual_children, list):
            return False
        if len(expected_children) != len(actual_children):
            return False
        return all(
            isinstance(expected_child, Mapping)
            and isinstance(actual_child, Mapping)
            and matches(actual_child, expected_child)
            for actual_child, expected_child in zip(actual_children, expected_children)
        )

    return matches(actual_root, expected_root)


def _fixture_bounds(node: Mapping[str, Any]) -> dict[str, int] | None:
    values = node.get("bounds", [0, 0, 1080, 2400])
    if not isinstance(values, list) or len(values) != 4 or any(type(value) is not int for value in values):
        return None
    return dict(zip(("l", "t", "r", "b"), values))


def _home_monitor_content_valid(
    pair: Mapping[str, Any] | None,
    fixture: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(pair, Mapping):
        return False
    root = fixture.get("root") if isinstance(fixture, Mapping) else None
    if not isinstance(root, Mapping) or not isinstance(root.get("children"), list):
        return False
    fixture_children = [child for child in root["children"] if isinstance(child, Mapping)]
    legacy = pair.get("legacy_output")
    if not isinstance(legacy, Mapping) or not isinstance(legacy.get("nodes"), list):
        return False
    nodes = legacy["nodes"]
    texts = {node.get("text") for node in nodes if isinstance(node, Mapping)}
    descriptions = {node.get("contentDescription") for node in nodes if isinstance(node, Mapping)}
    by_id = {
        node.get("viewIdResourceName"): node
        for node in nodes
        if isinstance(node, Mapping) and isinstance(node.get("viewIdResourceName"), str)
    }
    required = {
        "com.samsung.android.oneconnect:id/shmBannerAwayButton": "Arm away",
        "com.samsung.android.oneconnect:id/shmBannerStayButton": "Armed stay",
        "com.samsung.android.oneconnect:id/shmBannerDisarmedButton": "Disarm",
    }
    heading_spec = next((node for node in fixture_children if node.get("text") == "Home Monitor"), None)
    more_spec = next((node for node in fixture_children if node.get("description") == "More options"), None)
    if heading_spec is None or more_spec is None:
        return False
    heading = next((node for node in nodes if isinstance(node, Mapping) and node.get("text") == "Home Monitor"), None)
    more = next((node for node in nodes if isinstance(node, Mapping) and node.get("contentDescription") == "More options"), None)
    if (heading is None or heading.get("boundsInScreen") != _fixture_bounds(heading_spec)
            or more is None or more.get("boundsInScreen") != _fixture_bounds(more_spec)
            or more.get("clickable") is not True or more.get("focusable") is not True
            or more.get("effectiveClickable") is not True):
        return False

    control_indices = []
    for resource_id, label in required.items():
        spec = next((node for node in fixture_children if node.get("resourceId") == resource_id), None)
        node = by_id.get(resource_id)
        if (spec is None or node is None or node.get("text") != label
                or node.get("boundsInScreen") != _fixture_bounds(spec)
                or node.get("clickable") is not True or node.get("focusable") is not True
                or node.get("effectiveClickable") is not True):
            return False
        control_indices.append(nodes.index(node))
    return (
        "Home Monitor" in texts
        and "More options" in descriptions
        and nodes.index(heading) < nodes.index(more) < control_indices[0] < control_indices[1] < control_indices[2]
    )
