from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tb_runner import device_tab_logic
from tb_runner.collection_flow import _ensure_all_devices_location_selected
from tb_runner.device_inventory import run_inventory_shadow_if_enabled
from tb_runner.policy_registry import run_policy_mapping_if_enabled
from tb_runner.quick_plugin_identify import run_quick_identify_if_enabled
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.shadow_compare import (
    build_shadow_report,
    compare_shadow_candidate,
    render_shadow_report_markdown,
)
from tb_runner.tab_logic import (
    match_tab_candidate,
    normalize_tab_config,
    stabilize_tab_selection,
)
from tb_runner.v10_preparation import V10VersionSchema, build_v10_preparation_config
from .promotion_readiness import (
    evaluate_promotion_readiness,
    write_promotion_readiness_artifacts,
)

SHADOW_PIPELINE_SCHEMA_VERSION = "v10-shadow-pipeline-v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _read_v10_config(runtime_config_path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(runtime_config_path).read_text(encoding="utf-8"))
    raw_v10 = payload.get("v10") if isinstance(payload, Mapping) else {}
    return build_v10_preparation_config(raw_v10)


def shadow_validation_enabled(
    runtime_config_path: str | Path,
    *,
    requested: bool,
) -> bool:
    if requested is not True:
        return False
    try:
        config = _read_v10_config(runtime_config_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return config["feature_flags"]["shadow_validation_enabled"] is True


def _pipeline_config(v10_config: Mapping[str, Any]) -> dict[str, Any]:
    config = dict(v10_config)
    config["feature_flags"] = {
        "inventory_enabled": True,
        "quick_identify_enabled": True,
        "policy_mapping_enabled": True,
        "shadow_validation_enabled": True,
    }
    return config


def _device_tab_config() -> dict[str, Any]:
    for config in TAB_CONFIGS:
        if config.get("scenario_id") == "devices_main":
            return dict(config)
    raise RuntimeError("devices_main scenario config is unavailable")


def _extract_nodes(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping) and isinstance(payload.get("nodes"), list):
        payload = payload["nodes"]
    return [node for node in payload if isinstance(node, dict)] if isinstance(payload, list) else []


def _has_device_tab_candidate(nodes: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> bool:
    normalized = normalize_tab_config(dict(config))
    return any(
        match_tab_candidate(dict(node), normalized).get("matched")
        for node in nodes
        if isinstance(node, Mapping)
    )


def _send_back(client: Any, serial: str | None) -> bool:
    run = getattr(client, "_run", None)
    if not callable(run):
        return False
    try:
        run(["shell", "input", "keyevent", "4"], dev=serial, timeout=5.0)
        return True
    except Exception:
        return False


def _selection_failure_reason(selection: Mapping[str, Any]) -> str:
    direct_reason = _text(selection.get("reason"))
    if direct_reason:
        return direct_reason
    focus_align = selection.get("focus_align")
    if isinstance(focus_align, Mapping) and _text(focus_align.get("reason")):
        return f"focus_align_{_text(focus_align.get('reason'))}"
    context = selection.get("verify_context") or selection.get("context")
    if isinstance(context, Mapping) and _text(context.get("reason")):
        return f"context_{_text(context.get('reason'))}"
    if selection.get("selected") is False:
        return "tab_select_failed"
    return "verification_failed"


def prepare_device_inventory_surface(
    client: Any,
    serial: str | None,
    *,
    max_back_attempts: int = 4,
    settle_seconds: float = 0.8,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    config = _device_tab_config()
    dump_tree = getattr(client, "dump_tree", None)
    if not callable(dump_tree):
        raise RuntimeError("helper_dump_unavailable")

    nodes: list[dict[str, Any]] = []
    for back_attempt in range(max(0, int(max_back_attempts)) + 1):
        nodes = _extract_nodes(dump_tree(dev=serial))
        if _has_device_tab_candidate(nodes, config):
            break
        if back_attempt >= max_back_attempts:
            raise RuntimeError(
                f"device_tab_selection_failed:"
                f"device_tab_candidate_not_found_after_{max_back_attempts}_back"
            )
        if not _send_back(client, serial):
            raise RuntimeError("device_tab_selection_failed:back_navigation_unavailable")
        sleep(max(0.0, settle_seconds))

    selection = stabilize_tab_selection(client, serial, config, max_retries=3)
    if not selection.get("ok"):
        raise RuntimeError(
            f"device_tab_selection_failed:{_selection_failure_reason(selection)}"
        )

    nodes = _extract_nodes(dump_tree(dev=serial))
    selected, _nodes, reason = _ensure_all_devices_location_selected(
        client,
        serial,
        nodes,
        lambda **kwargs: _extract_nodes(dump_tree(**kwargs)),
        step_wait_seconds=0.8,
    )
    if not selected:
        raise RuntimeError(f"all_devices_selection_failed:{reason}")

    # Inventory viewport indexes are session-local and must share one origin.
    # Full runs can leave the Devices list at an arbitrary scroll offset.
    scroll_to_top = getattr(client, "scroll_to_top", None)
    if callable(scroll_to_top):
        result = scroll_to_top(dev=serial, max_swipes=8, pause=0.25)
        if isinstance(result, Mapping) and result.get("ok") is False:
            raise RuntimeError(
                f"device_inventory_viewport_normalization_failed:"
                f"{_text(result.get('reason')) or 'unknown'}"
            )
        sleep(0.25)
        normalized_nodes = _extract_nodes(dump_tree(dev=serial))
        location_state = device_tab_logic.detect_selected_device_location(normalized_nodes)
        if not location_state.get("selected"):
            raise RuntimeError(
                "device_inventory_viewport_normalization_failed:"
                "all_devices_selection_lost"
            )


def _legacy_label_registry(
    selected_scenario_ids: Sequence[str],
) -> dict[str, list[str]]:
    selected = {scenario_id for scenario_id in selected_scenario_ids if scenario_id}
    registry: dict[str, list[str]] = {}
    for config in TAB_CONFIGS:
        scenario_id = _text(config.get("scenario_id"))
        if not scenario_id.startswith("device_") or scenario_id not in selected:
            continue
        for step in config.get("pre_navigation", []):
            if not isinstance(step, Mapping) or step.get("action") != "enter_device_card_plugin":
                continue
            labels = step.get("target_stable_labels", [])
            if isinstance(labels, str):
                labels = [labels]
            for label in labels if isinstance(labels, list) else []:
                normalized = device_tab_logic.normalize_device_match_label(label)
                if normalized:
                    registry.setdefault(normalized, []).append(scenario_id)
    return registry


def _legacy_result(
    inventory: Mapping[str, Any],
    item: Mapping[str, Any],
    label_registry: Mapping[str, list[str]],
    *,
    run_id: str,
    device_name: str,
) -> dict[str, Any]:
    stable_label = _text(item.get("stable_label"))
    normalized = device_tab_logic.normalize_device_match_label(stable_label)
    matches = list(dict.fromkeys(label_registry.get(normalized, [])))
    if len(matches) == 1:
        decision = "resolved"
        scenario = matches[0]
    elif len(matches) > 1:
        decision = "ambiguous"
        scenario = ""
    else:
        decision = "unknown"
        scenario = ""
    return {
        "inventory_id": _text(inventory.get("inventory_id")),
        "runtime_card_id": _text(item.get("runtime_card_id")),
        "display_label": _text(item.get("display_label")),
        "stable_label": stable_label,
        "run_id": run_id,
        "device_name": device_name,
        "legacy_scenario": scenario,
        "decision": decision,
        "fallback_used": False,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_shadow_error_artifacts(
    shadow_dir: Path,
    *,
    error: Exception,
    stage: str,
    run_id: str,
    device_name: str,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    reason = _text(error) or error.__class__.__name__
    payload = {
        "schema_version": SHADOW_PIPELINE_SCHEMA_VERSION,
        "status": "failed",
        "stage": stage,
        "error_type": error.__class__.__name__,
        "error": reason,
        "run_id": run_id,
        "device_name": device_name,
        "timestamp": timestamp,
        "legacy_authoritative": True,
        "legacy_result_preserved": True,
        "v10_routing_performed": False,
    }
    _write_json(shadow_dir / "shadow_error.json", payload)
    (shadow_dir / "shadow_report.md").write_text(
        "\n".join(
            [
                "# V10 Shadow Validation Report",
                "",
                "## Status",
                "",
                "- Result: FAILED",
                f"- Stage: {stage}",
                f"- Error: {reason}",
                f"- Timestamp: {timestamp}",
                "- Legacy authoritative: true",
                "- Legacy result preserved: true",
                "- V10 routing performed: false",
                "",
            ]
        ),
        encoding="utf-8",
    )


def run_shadow_validation_pipeline(
    *,
    runtime_config_path: str | Path,
    requested: bool,
    output_dir: str | Path,
    artifact_dir: str | Path | None = None,
    scenario_ids: Sequence[str],
    serial: str | None = None,
    run_id: str = "",
    device_name: str = "",
    client_factory: Callable[..., Any] | None = None,
    surface_preparer: Callable[[Any, str | None], None] = prepare_device_inventory_surface,
    inventory_runner: Callable[..., dict[str, Any]] = run_inventory_shadow_if_enabled,
    identify_runner: Callable[..., dict[str, Any]] = run_quick_identify_if_enabled,
    mapping_runner: Callable[..., dict[str, Any]] = run_policy_mapping_if_enabled,
) -> dict[str, Any]:
    if not shadow_validation_enabled(runtime_config_path, requested=requested):
        return {"status": "disabled", "artifact_dir": "", "warning": ""}

    if client_factory is None:
        from talkback_lib import A11yAdbClient

        client_factory = A11yAdbClient

    shadow_dir = Path(artifact_dir) if artifact_dir is not None else Path(output_dir) / "shadow"
    shadow_dir.mkdir(parents=True, exist_ok=True)
    stage = "initialization"
    try:
        v10_config = _read_v10_config(runtime_config_path)
        pipeline_config = _pipeline_config(v10_config)
        versions = V10VersionSchema.from_mapping(pipeline_config.get("versions"))
        client = client_factory(dev_serial=serial, start_monitor=False)
        stage = "device_surface_preparation"
        surface_preparer(client, serial)

        with tempfile.TemporaryDirectory(prefix="v10-shadow-") as stage_dir:
            stage_root = Path(stage_dir)
            stage = "inventory"
            inventory_output = inventory_runner(
                client,
                serial,
                pipeline_config,
                artifact_dir=stage_root / "inventory",
            )
            inventory = inventory_output.get("inventory")
            if not isinstance(inventory, Mapping):
                raise RuntimeError(
                    f"shadow_inventory_failed:{inventory_output.get('error', inventory_output.get('status', 'unknown'))}"
                )

            identify_results: list[dict[str, Any]] = []
            routing_candidates: list[dict[str, Any]] = []
            comparison_inputs: list[dict[str, Any]] = []
            label_registry = _legacy_label_registry(scenario_ids)
            inventory_items = [
                item for item in inventory.get("items", []) if isinstance(item, Mapping)
            ]

            for item in inventory_items:
                # Inventory collection ends at its final bounded viewport. Re-enter
                # the Devices surface so each opaque runtime card is replayed from
                # the same known location state.
                stage = "identify_surface_restore"
                surface_preparer(client, serial)
                runtime_card_id = _text(item.get("runtime_card_id"))
                stage = "identify"
                identify_output = identify_runner(
                    client,
                    serial,
                    pipeline_config,
                    inventory,
                    runtime_card_id,
                    artifact_dir=stage_root / "identify",
                )
                identify_result = identify_output.get("result")
                if not isinstance(identify_result, Mapping):
                    continue
                identify_record = dict(identify_result)
                identify_results.append(identify_record)

                stage = "policy_mapping"
                mapping_output = mapping_runner(
                    pipeline_config,
                    identify_record,
                    artifact_dir=stage_root / "routing",
                )
                candidate = mapping_output.get("result")
                if not isinstance(candidate, Mapping):
                    continue
                candidate_record = {
                    **dict(candidate),
                    "display_label": _text(item.get("display_label")),
                    "stable_label": _text(item.get("stable_label")),
                    "run_id": run_id,
                    "device_name": device_name,
                }
                routing_candidates.append(candidate_record)
                comparison_inputs.append(
                    {
                        "legacy": _legacy_result(
                            inventory,
                            item,
                            label_registry,
                            run_id=run_id,
                            device_name=device_name,
                        ),
                        "shadow_candidate": candidate_record,
                    }
                )

        stage = "comparison"
        comparisons = [
            compare_shadow_candidate(
                item["legacy"],
                item["shadow_candidate"],
                versions=versions,
            )
            for item in comparison_inputs
        ]
        report = build_shadow_report(
            comparisons,
            versions=versions,
            eligible_inventory_count=len(inventory_items),
        )
        inventory_artifact = {
            "schema_version": SHADOW_PIPELINE_SCHEMA_VERSION,
            "run_id": run_id,
            "device_name": device_name,
            "inventory": dict(inventory),
        }
        identify_artifact = {
            "schema_version": SHADOW_PIPELINE_SCHEMA_VERSION,
            "inventory_id": _text(inventory.get("inventory_id")),
            "results": identify_results,
        }
        routing_artifact = {
            "schema_version": SHADOW_PIPELINE_SCHEMA_VERSION,
            "inventory_id": _text(inventory.get("inventory_id")),
            "candidates": routing_candidates,
        }
        stage = "artifact_write"
        _write_json(shadow_dir / "shadow_inventory.json", inventory_artifact)
        _write_json(shadow_dir / "shadow_identify.json", identify_artifact)
        _write_json(shadow_dir / "shadow_routing.json", routing_artifact)
        _write_json(shadow_dir / "shadow_compare.json", report)
        (shadow_dir / "shadow_report.md").write_text(
            render_shadow_report_markdown(report),
            encoding="utf-8",
        )
        stage = "promotion_readiness"
        readiness = evaluate_promotion_readiness(
            comparisons,
            identify_results=identify_results,
            legacy_preserved=report.get("legacy_authoritative") is True,
        )
        write_promotion_readiness_artifacts(readiness, shadow_dir=shadow_dir)
        return {
            "status": "completed",
            "artifact_dir": str(shadow_dir),
            "warning": "",
            "metrics": dict(report.get("metrics", {})),
            "promotion_readiness": readiness["overall_status"],
        }
    except Exception as exc:
        write_shadow_error_artifacts(
            shadow_dir,
            error=exc,
            stage=stage,
            run_id=run_id,
            device_name=device_name,
        )
        return {
            "status": "warning",
            "artifact_dir": str(shadow_dir),
            "warning": _text(exc) or exc.__class__.__name__,
            "legacy_result_preserved": True,
        }
