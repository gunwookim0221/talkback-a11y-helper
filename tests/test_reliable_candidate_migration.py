from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from talkback_lib import A11yAdbClient
from talkback_lib.hierarchy_file_transport import (
    DEFAULT_HIERARCHY_TRANSPORT_MODE,
    HierarchyTransportError,
)
from talkback_lib.reliable_hierarchy_schema import (
    CANDIDATE_ALGORITHM_VERSION,
    CANDIDATE_ANALYZER_VERSION,
    CANDIDATE_CONTRACT_VERSION,
    CANDIDATE_PROFILE_ID,
    CANDIDATE_PROFILE_VERSION,
    CANDIDATE_SCHEMA_VERSION,
    RAW_SCHEMA_VERSION,
    legacy_dump_tree_response,
)


def _candidate(
    text: str = "Candidate",
    bounds: tuple[int, int, int, int] = (0, 0, 100, 80),
) -> dict:
    return {
        "text": text,
        "contentDescription": None,
        "className": "android.widget.Button",
        "viewIdResourceName": "app:id/example",
        "boundsInScreen": dict(zip(("l", "t", "r", "b"), bounds)),
        "clickable": True,
        "focusable": True,
        "isVisibleToUser": True,
        "focused": False,
        "accessibilityFocused": False,
        "isTopAppBar": False,
        "isBottomNavigationBar": False,
        "hasClickableDescendant": False,
        "hasFocusableDescendant": False,
        "effectiveClickable": True,
        "actionableDescendantResourceId": None,
        "actionableDescendantClassName": None,
        "actionableDescendantContentDescription": None,
    }


def _payload(candidates: list[dict] | None = None) -> dict:
    root = {
        "text": "root",
        "contentDescription": None,
        "viewIdResourceName": "app:id/root",
        "className": "android.widget.FrameLayout",
        "packageName": "com.example",
        "windowId": 17,
        "boundsInScreen": {"l": 0, "t": 0, "r": 1080, "b": 2400},
        "clickable": False,
        "effectiveClickable": False,
        "enabled": True,
        "focusable": False,
        "focused": False,
        "inputFocused": False,
        "accessibilityFocused": False,
        "selected": False,
        "scrollable": False,
        "isScrollable": False,
        "checkable": False,
        "checked": False,
        "visibleToUser": True,
        "isVisibleToUser": True,
        "screenReaderFocusable": False,
        "rangeInfoPresent": False,
        "actions": [],
        "children": [],
    }
    rows = deepcopy(candidates if candidates is not None else [_candidate()])
    return {
        "reqId": "request-123",
        "success": True,
        "schemaVersion": RAW_SCHEMA_VERSION,
        "platformApiLevel": 34,
        "traversalRootRef": "windows[0].root",
        "traversalRootWindowId": 17,
        "nodeCount": 1,
        "nodes": [root],
        "windows": [{
            "order": 0,
            "id": 17,
            "type": 1,
            "layer": 0,
            "title": "Example",
            "active": True,
            "focused": True,
            "boundsInScreen": {"l": 0, "t": 0, "r": 1080, "b": 2400},
            "root": root,
        }],
        "traversalCandidates": {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
            "algorithmVersion": CANDIDATE_ALGORITHM_VERSION,
            "analyzerVersion": CANDIDATE_ANALYZER_VERSION,
            "profileId": CANDIDATE_PROFILE_ID,
            "profileVersion": CANDIDATE_PROFILE_VERSION,
            "completion": {"status": "COMPLETE", "complete": True, "candidate_count": len(rows)},
            "traversalRootRef": "windows[0].root",
            "traversalRootWindowId": 17,
            "canScrollDown": True,
            "scrollAxisContract": "axis-v1",
            "candidates": rows,
        },
    }


def _capabilities() -> dict:
    return {
        "payload_schema_version": RAW_SCHEMA_VERSION,
        "supported_payload_schema_versions": [RAW_SCHEMA_VERSION],
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "supported_candidate_schema_versions": [CANDIDATE_SCHEMA_VERSION],
        "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
        "capabilities": ["content_provider_pfd", "service_hierarchy_v2", CANDIDATE_SCHEMA_VERSION],
    }


def _transport_metadata() -> dict:
    identity = {"build_id": "a" * 64, "git_commit": "b" * 40}
    record = {
        "request_id": "request-123",
        "client_nonce": "nonce-1",
        "process_epoch": "epoch-1",
        "generation": 3,
        "service_instance_id": "service-1",
        "payload_schema_version": RAW_SCHEMA_VERSION,
        "helper_build_identity": identity,
    }
    return {"header": deepcopy(record), "control": deepcopy(record)}


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_CONSUMERS = (
    "tb_runner/anchor_logic.py",
    "tb_runner/collection_flow.py",
    "talkback_lib/focus_service.py",
    "tb_runner/context_verifier.py",
    "tb_runner/scroll_reliability.py",
    "tb_runner/coverage_probe_engine.py",
    "tb_runner/device_inventory.py",
    "tb_runner/quick_plugin_identify.py",
    "tb_runner/tab_logic.py",
)


def _reliable_client(body: dict) -> A11yAdbClient:
    client = A11yAdbClient(start_monitor=False)
    client.dump_hierarchy = lambda **_kwargs: body
    client._last_hierarchy_capabilities = _capabilities()
    client._last_hierarchy_transport_metadata = _transport_metadata()
    client.check_helper_status = lambda **_kwargs: True
    return client


def test_normal_dump_tree_uses_reliable_candidate_adapter_without_legacy_broadcast():
    body = _payload()
    client = _reliable_client(body)
    broadcasts = []
    client._broadcast = lambda *args, **kwargs: broadcasts.append((args, kwargs))

    candidates = client.dump_tree()

    assert DEFAULT_HIERARCHY_TRANSPORT_MODE == "RELIABLE_FILE_PFD"
    assert candidates == body["traversalCandidates"]["candidates"]
    assert client.last_dump_metadata["transportMode"] == "RELIABLE_FILE_PFD"
    assert client.last_dump_metadata["candidateSchemaVersion"] == CANDIDATE_SCHEMA_VERSION
    assert client.last_dump_metadata["candidateContractVersion"]
    assert client.last_dump_metadata["scrollAxisContract"] == "axis-v1"
    assert client.last_dump_metadata["requestId"] == "request-123"
    assert broadcasts == []


def test_explicit_legacy_mode_is_the_only_dump_tree_debug_route():
    client = _reliable_client(_payload())
    calls = []
    legacy_nodes = [{"text": "debug-only"}]
    client._dump_tree_legacy = lambda **kwargs: calls.append(kwargs) or legacy_nodes

    assert client.dump_tree(transport_mode="LEGACY_LOGCAT") is legacy_nodes
    assert calls == [{
        "dev": None,
        "wait_seconds": 5.0,
        "include_scroll_capabilities": False,
        "include_device_collection": False,
    }]


@pytest.mark.parametrize(
    "reason",
    [
        "PFD_READ_FAILED",
        "SHA256_MISMATCH",
        "CANDIDATE_INCOMPLETE",
        "TRAVERSAL_ROOT_MISMATCH",
        "UNSUPPORTED_CANDIDATE_SCHEMA",
    ],
)
def test_reliable_failure_never_rescues_with_legacy_dump(reason: str):
    client = _reliable_client(_payload())
    client.dump_hierarchy_decoded = lambda **_kwargs: (_ for _ in ()).throw(
        HierarchyTransportError(reason, "request-123")
    )
    client._dump_tree_legacy = lambda **_kwargs: pytest.fail("legacy rescue must remain unused")

    with pytest.raises(HierarchyTransportError, match=reason):
        client.dump_tree(include_device_collection=True)


def test_device_collection_supplement_never_replaces_reliable_candidates():
    body = _payload()
    client = _reliable_client(body)
    decoded = client.dump_hierarchy_decoded()
    legacy_view = legacy_dump_tree_response(decoded)
    calls = []

    def supplemental(**_kwargs):
        calls.append(_kwargs)
        client.last_dump_metadata = {
            "algorithmVersion": legacy_view["algorithmVersion"],
            "canScrollDown": legacy_view["canScrollDown"],
        }
        client.last_device_collection = {"cards": [{"resourceId": "device-1"}]}
        return deepcopy(legacy_view["nodes"])

    client._dump_tree_legacy = supplemental
    candidates = client.dump_tree(include_device_collection=True)

    assert candidates == body["traversalCandidates"]["candidates"]
    assert client.last_device_collection == {"cards": [{"resourceId": "device-1"}]}
    assert client.last_dump_metadata["transportMode"] == "RELIABLE_FILE_PFD"
    assert calls and calls[0]["include_device_collection"] is True


def test_device_collection_supplement_mismatch_fails_closed():
    body = _payload()
    client = _reliable_client(body)
    legacy_view = legacy_dump_tree_response(client.dump_hierarchy_decoded())
    changed = deepcopy(legacy_view["nodes"])
    changed[0]["text"] = "different candidate"
    client._dump_tree_legacy = lambda **_kwargs: changed
    client.last_device_collection = {"cards": [{"resourceId": "must-not-leak"}]}

    with pytest.raises(HierarchyTransportError, match="SUPPLEMENTAL_METADATA_CANDIDATE_MISMATCH"):
        client.dump_tree(include_device_collection=True)
    assert client.last_device_collection == {}


def test_direct_dump_tree_action_is_confined_to_explicit_legacy_implementation():
    source = (ROOT / "talkback_lib" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    owners: list[str] = []

    def visit(node: ast.AST, owner: str = "") -> None:
        current = owner
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            current = node.name
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "_broadcast" and len(node.args) >= 2:
                if isinstance(node.args[1], ast.Name) and node.args[1].id == "ACTION_DUMP_TREE":
                    owners.append(current)
        for child in ast.iter_child_nodes(node):
            visit(child, current)

    visit(tree)
    assert owners == ["_dump_tree_legacy"]

    public_dump = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "dump_tree"
    )
    public_attributes = {
        node.attr for node in ast.walk(public_dump)
        if isinstance(node, ast.Attribute)
    }
    assert "get_traversal_candidate_snapshot" in public_attributes
    assert "ACTION_DUMP_TREE" not in public_attributes


@pytest.mark.parametrize("relative_path", PRODUCTION_CONSUMERS)
def test_production_consumers_cannot_issue_legacy_hierarchy_action(relative_path: str):
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    forbidden = {"ACTION_DUMP_TREE", "_dump_tree_legacy"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    assert not (forbidden & (names | attributes))


def test_c3_adapter_keeps_instance_v1_inputs_for_same_resource_id_different_bounds():
    from tb_runner.traversal_reliability import instance_id

    body = _payload(candidates=[
        {
            **_payload()["traversalCandidates"]["candidates"][0],
            "viewIdResourceName": "same/resource",
            "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 80},
        },
        {
            **_payload()["traversalCandidates"]["candidates"][0],
            "viewIdResourceName": "same/resource",
            "boundsInScreen": {"l": 0, "t": 100, "r": 100, "b": 180},
        },
    ])
    client = _reliable_client(body)
    first, second = client.get_traversal_candidates()

    assert first["viewIdResourceName"] == second["viewIdResourceName"] == "same/resource"
    assert first["boundsInScreen"] != second["boundsInScreen"]
    assert instance_id({"view_id": first["viewIdResourceName"], "bounds": first["boundsInScreen"]}) != instance_id(
        {"view_id": second["viewIdResourceName"], "bounds": second["boundsInScreen"]}
    )
