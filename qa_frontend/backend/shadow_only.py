from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .shadow_pipeline import (
    run_shadow_validation_pipeline,
    write_shadow_error_artifacts,
)


SHADOW_ARTIFACT_NAMES = (
    "shadow_inventory.json",
    "shadow_identify.json",
    "shadow_routing.json",
    "shadow_compare.json",
    "shadow_report.md",
    "shadow_error.json",
)
_PROTECTED_PATTERNS = (
    "runtime_config.json",
    "summary.json",
)
_LEGACY_RESULT_PATTERNS = (
    "runner.log",
    "*.normal.log",
    "*.xlsx",
)
_SAFE_SUFFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class ShadowOnlyContext:
    run_dir: Path
    runtime_config_path: Path
    summary_path: Path
    scenario_ids: tuple[str, ...]
    serial: str
    run_id: str
    device_name: str
    legacy_artifacts: tuple[Path, ...]


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label}_missing:{path.name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_invalid:{path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label}_invalid:{path.name}")
    return payload


def _enabled_scenario_ids(runtime_config: Mapping[str, Any]) -> tuple[str, ...]:
    scenarios = runtime_config.get("scenarios")
    if not isinstance(scenarios, Mapping):
        return ()
    return tuple(
        str(scenario_id)
        for scenario_id, config in scenarios.items()
        if isinstance(config, Mapping) and config.get("enabled") is True
    )


def _legacy_artifacts(run_dir: Path) -> tuple[Path, ...]:
    artifacts: set[Path] = set()
    for pattern in (*_PROTECTED_PATTERNS, *_LEGACY_RESULT_PATTERNS):
        artifacts.update(path for path in run_dir.glob(pattern) if path.is_file())
    return tuple(sorted(artifacts))


def inspect_shadow_only_run(
    run_dir: str | Path,
    *,
    device_id: str | None = None,
) -> ShadowOnlyContext:
    resolved = Path(run_dir).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"run_dir_invalid:{resolved}")

    runtime_config_path = resolved / "runtime_config.json"
    summary_path = resolved / "summary.json"
    runtime_config = _read_json_object(runtime_config_path, label="runtime_config")
    summary = _read_json_object(summary_path, label="summary")
    legacy_artifacts = _legacy_artifacts(resolved)
    if not any(
        path.match(pattern)
        for path in legacy_artifacts
        for pattern in _LEGACY_RESULT_PATTERNS
    ):
        raise ValueError("legacy_artifacts_missing")

    serial = str(device_id or summary.get("serial") or "").strip()
    run_id = str(summary.get("batch_id") or summary.get("run_id") or resolved.parent.name).strip()
    device_name = str(summary.get("model") or summary.get("device_name") or resolved.name).strip()
    return ShadowOnlyContext(
        run_dir=resolved,
        runtime_config_path=runtime_config_path,
        summary_path=summary_path,
        scenario_ids=_enabled_scenario_ids(runtime_config),
        serial=serial,
        run_id=run_id,
        device_name=device_name,
        legacy_artifacts=legacy_artifacts,
    )


def resolve_shadow_output_dir(
    run_dir: Path,
    *,
    output_suffix: str | None = None,
) -> Path:
    suffix = str(output_suffix or "").strip()
    if not suffix:
        return run_dir / "shadow"
    if not _SAFE_SUFFIX.fullmatch(suffix) or suffix in {".", ".."}:
        raise ValueError("output_suffix_invalid")
    return run_dir / f"shadow_{suffix}"


def _file_digest(path: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, digest.hexdigest()


def snapshot_legacy_artifacts(context: ShadowOnlyContext) -> dict[Path, tuple[int, int, str]]:
    return {path: _file_digest(path) for path in context.legacy_artifacts}


def _forced_shadow_config(source_path: Path, output_path: Path) -> None:
    payload = _read_json_object(source_path, label="runtime_config")
    v10 = payload.setdefault("v10", {})
    if not isinstance(v10, dict):
        v10 = {}
        payload["v10"] = v10
    flags = v10.setdefault("feature_flags", {})
    if not isinstance(flags, dict):
        flags = {}
        v10["feature_flags"] = flags
    for flag in (
        "inventory_enabled",
        "quick_identify_enabled",
        "policy_mapping_enabled",
        "shadow_validation_enabled",
    ):
        flags[flag] = True
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _prepare_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    existing = output_dir.exists() and any(output_dir.iterdir())
    if existing and not overwrite:
        raise ValueError(f"shadow_output_exists:{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    if overwrite:
        for name in SHADOW_ARTIFACT_NAMES:
            path = output_dir / name
            if path.is_file():
                path.unlink()


def run_shadow_only(
    run_dir: str | Path,
    *,
    overwrite_shadow: bool = False,
    output_suffix: str | None = None,
    device_id: str | None = None,
    dry_run: bool = False,
    pipeline_runner: Callable[..., dict[str, Any]] = run_shadow_validation_pipeline,
) -> dict[str, Any]:
    context = inspect_shadow_only_run(run_dir, device_id=device_id)
    output_dir = resolve_shadow_output_dir(
        context.run_dir,
        output_suffix=output_suffix,
    )
    result: dict[str, Any] = {
        "status": "validated" if dry_run else "pending",
        "run_dir": str(context.run_dir),
        "runtime_config_path": str(context.runtime_config_path),
        "summary_path": str(context.summary_path),
        "scenario_ids": list(context.scenario_ids),
        "serial": context.serial,
        "run_id": context.run_id,
        "device_name": context.device_name,
        "artifact_dir": str(output_dir),
        "legacy_artifacts": [str(path) for path in context.legacy_artifacts],
        "legacy_result_preserved": True,
    }
    if dry_run:
        return result

    _prepare_output_dir(output_dir, overwrite=overwrite_shadow)
    before = snapshot_legacy_artifacts(context)
    try:
        with tempfile.TemporaryDirectory(prefix="v10-shadow-only-") as temp_dir:
            forced_config = Path(temp_dir) / "runtime_config.json"
            _forced_shadow_config(context.runtime_config_path, forced_config)
            pipeline_result = pipeline_runner(
                runtime_config_path=forced_config,
                requested=True,
                output_dir=context.run_dir,
                artifact_dir=output_dir,
                scenario_ids=context.scenario_ids,
                serial=context.serial or None,
                run_id=context.run_id,
                device_name=context.device_name,
            )
    except Exception as exc:
        write_shadow_error_artifacts(
            output_dir,
            error=exc,
            stage="shadow_only_execution",
            run_id=context.run_id,
            device_name=context.device_name,
        )
        pipeline_result = {
            "status": "warning",
            "artifact_dir": str(output_dir),
            "warning": str(exc) or exc.__class__.__name__,
            "legacy_result_preserved": True,
        }

    after = snapshot_legacy_artifacts(context)
    if before != after:
        raise RuntimeError("legacy_artifact_modified")
    return {
        **result,
        **pipeline_result,
        "artifact_dir": str(output_dir),
        "legacy_result_preserved": True,
    }
