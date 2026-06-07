from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from talkback_lib import A11yAdbClient
from tb_runner.plugin_card_discovery import (
    build_discovery_response,
    build_known_plugin_index,
    discover_device_cards,
    discover_life_cards_from_xml,
)
from tb_runner.scenario_config import TAB_CONFIGS


class PluginDiscoveryRequest(BaseModel):
    targets: list[str] = ["life", "device"]
    include_xml: bool = True
    current_view_only: bool = True
    serial: str | None = None


def _normalize_targets(targets: list[str]) -> list[str]:
    normalized: list[str] = []
    for target in targets:
        value = str(target or "").strip().lower()
        if value in {"life", "device"} and value not in normalized:
            normalized.append(value)
    return normalized or ["life", "device"]


def _extract_helper_nodes(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [node for node in payload if isinstance(node, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("nodes"), list):
        return [node for node in payload["nodes"] if isinstance(node, dict)]
    return []


def _capture_helper_nodes(client: A11yAdbClient, serial: str | None) -> tuple[list[dict[str, Any]], str]:
    try:
        return _extract_helper_nodes(client.dump_tree(dev=serial)), ""
    except Exception as exc:
        return [], f"helper_dump_failed:{exc}"


def _capture_window_xml(client: A11yAdbClient, serial: str | None) -> tuple[str, str]:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return "", "xml_dump_failed:client_run_not_supported"
    remote_xml = "/sdcard/window_dump_plugin_discovery.xml"
    try:
        run_fn(["shell", "uiautomator", "dump", remote_xml], dev=serial)
        xml_text = str(run_fn(["shell", "cat", remote_xml], dev=serial) or "")
        return xml_text, "" if xml_text.strip() else "xml_dump_failed:empty_xml"
    except Exception as exc:
        return "", f"xml_dump_failed:{exc}"
    finally:
        try:
            run_fn(["shell", "rm", "-f", remote_xml], dev=serial)
        except Exception:
            pass


def discover_plugins(request: PluginDiscoveryRequest, *, client: A11yAdbClient | None = None) -> dict[str, Any]:
    targets = _normalize_targets(request.targets)
    client = client or A11yAdbClient()
    warnings: list[str] = []
    cards: list[dict[str, Any]] = []
    known_index = build_known_plugin_index(TAB_CONFIGS)

    if not request.current_view_only:
        warnings.append("bounded_discovery_not_implemented_current_view_only_used")

    helper_nodes: list[dict[str, Any]] = []
    helper_error = ""
    if "device" in targets:
        helper_nodes, helper_error = _capture_helper_nodes(client, request.serial)
        if helper_error:
            warnings.append(helper_error)
        else:
            cards.extend(discover_device_cards(helper_nodes, known_index=known_index))

    if "life" in targets:
        if not request.include_xml:
            warnings.append("life_discovery_requires_xml_for_phase5a_minimal")
        else:
            xml_text, xml_error = _capture_window_xml(client, request.serial)
            if xml_error:
                warnings.append(xml_error)
            else:
                cards.extend(discover_life_cards_from_xml(xml_text, known_index=known_index))

    hard_failures = []
    if "device" in targets and helper_error:
        hard_failures.append(helper_error)
    if "life" in targets and request.include_xml and any(warning.startswith("xml_dump_failed:") for warning in warnings):
        hard_failures.append("xml_dump_failed")
    ok = not hard_failures
    return build_discovery_response(cards=cards, warnings=warnings, ok=ok)
