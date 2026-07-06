from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from .paths import ROOT_DIR


DEFAULT_CORPUS_DIR = ROOT_DIR / "artifacts" / "v10" / "corpus"
CORPUS_TARGETS = {
    "folder": Path("."),
    "index": Path("index.json"),
    "family-summary": Path("summaries") / "family_summary.json",
    "readiness-summary": Path("summaries") / "readiness_summary.json",
}
READINESS_STATUSES = (
    "READY",
    "HOLD",
    "BLOCKED",
    "INSUFFICIENT_DATA",
    "UNKNOWN_ONLY",
)


def load_corpus_dashboard(
    corpus_dir: str | Path | None = None,
) -> dict[str, Any]:
    corpus_path = _corpus_path(corpus_dir)
    index = _read_json(corpus_path / "index.json")
    family_summary = _read_json(
        corpus_path / "summaries" / "family_summary.json"
    )
    readiness_summary = _read_json(
        corpus_path / "summaries" / "readiness_summary.json"
    )
    if not index or not family_summary or not readiness_summary:
        return _empty_dashboard(corpus_path)

    families = [
        _normalize_family(item)
        for item in _mapping_list(family_summary.get("families"))
    ]
    distribution = _readiness_distribution(
        readiness_summary.get("overall_readiness_distribution")
    )
    candidates = [
        str(value)
        for value in readiness_summary.get(
            "v11_pilot_candidate_families", []
        )
        if isinstance(value, str) and value
    ]
    family_readiness_counts = {
        status: sum(1 for item in families if item["readiness"] == status)
        for status in READINESS_STATUSES
    }
    totals = {
        result: sum(
            int(item.get(f"{result.lower()}_count", 0)) for item in families
        )
        for result in ("MATCH", "UNKNOWN", "AMBIGUOUS", "MISMATCH", "FAILED")
    }
    return {
        "available": True,
        "corpus_dir": str(corpus_path),
        "entry_count": _integer(index.get("entry_count")),
        "last_updated": str(
            readiness_summary.get("updated_at")
            or family_summary.get("updated_at")
            or index.get("updated_at")
            or ""
        ),
        "overall_readiness": _overall_readiness(distribution),
        "overall_readiness_distribution": distribution,
        "family_readiness_counts": family_readiness_counts,
        "totals": totals,
        "family_count": len(families),
        "families": families,
        "candidate_for_v11_pilot": candidates,
        "candidate_count": len(candidates),
        "blocking_families": [
            item["family"]
            for item in families
            if item["readiness_distribution"]["BLOCKED"] > 0
        ],
        "unknown_only_families": [
            item["family"]
            for item in families
            if item["readiness_distribution"]["UNKNOWN_ONLY"] > 0
        ],
        "diversity_metrics": {
            "unique_labels": len(
                {
                    label
                    for item in families
                    for label in item["unique_device_labels"]
                }
            ),
            "unique_device_models": len(
                {
                    model
                    for item in families
                    for model in item["unique_device_models"]
                }
            ),
            "max_unique_devices_per_family": max(
                (
                    item["unique_device_serial_count"]
                    for item in families
                ),
                default=0,
            ),
            "unique_locales": len(
                {
                    locale
                    for item in families
                    for locale in item["unique_locales"]
                }
            ),
            "unique_app_versions": len(
                {
                    version
                    for item in families
                    for version in item["unique_app_versions"]
                }
            ),
        },
        "controlled_routing_enabled": False,
    }


def open_corpus_target(
    target: str,
    *,
    corpus_dir: str | Path | None = None,
    opener: Callable[[Path], None] | None = None,
) -> Path:
    if target not in CORPUS_TARGETS:
        raise ValueError(f"unsupported_corpus_target:{target}")
    corpus_path = _corpus_path(corpus_dir)
    path = (corpus_path / CORPUS_TARGETS[target]).resolve()
    if target == "folder":
        if not path.is_dir():
            raise FileNotFoundError(path)
    elif not path.is_file():
        raise FileNotFoundError(path)
    (opener or _open_path)(path)
    return path


def _normalize_family(item: Mapping[str, Any]) -> dict[str, Any]:
    distribution = _readiness_distribution(item.get("readiness_distribution"))
    return {
        "family": str(item.get("family") or "Unknown"),
        "total_runs": _integer(item.get("total_runs")),
        "total_observations": _integer(item.get("total_observations")),
        "match_count": _integer(item.get("match_count")),
        "unknown_count": _integer(item.get("unknown_count")),
        "ambiguous_count": _integer(item.get("ambiguous_count")),
        "mismatch_count": _integer(item.get("mismatch_count")),
        "failed_count": _integer(item.get("failed_count")),
        "unique_device_labels": _string_list(item.get("unique_device_labels")),
        "unique_device_label_count": _integer(
            item.get("unique_device_label_count")
        ),
        "unique_device_models": _string_list(item.get("unique_device_models")),
        "unique_device_model_count": _integer(
            item.get("unique_device_model_count")
        ),
        "unique_device_serial_count": _integer(
            item.get("unique_device_serial_count")
        ),
        "unique_locales": _string_list(item.get("unique_locales")),
        "unique_locale_count": _integer(item.get("unique_locale_count")),
        "unique_app_versions": _string_list(item.get("unique_app_versions")),
        "unique_app_version_count": _integer(
            item.get("unique_app_version_count")
        ),
        "last_seen_at": str(item.get("last_seen_at") or ""),
        "readiness": _overall_readiness(distribution),
        "readiness_distribution": distribution,
        "candidate_for_v11_pilot": (
            item.get("candidate_for_v11_pilot") is True
        ),
    }


def _empty_dashboard(corpus_path: Path) -> dict[str, Any]:
    return {
        "available": False,
        "corpus_dir": str(corpus_path),
        "entry_count": 0,
        "last_updated": "",
        "overall_readiness": "INSUFFICIENT_DATA",
        "overall_readiness_distribution": {
            status: 0 for status in READINESS_STATUSES
        },
        "family_readiness_counts": {
            status: 0 for status in READINESS_STATUSES
        },
        "totals": {
            result: 0
            for result in ("MATCH", "UNKNOWN", "AMBIGUOUS", "MISMATCH", "FAILED")
        },
        "family_count": 0,
        "families": [],
        "candidate_for_v11_pilot": [],
        "candidate_count": 0,
        "blocking_families": [],
        "unknown_only_families": [],
        "diversity_metrics": {
            "unique_labels": 0,
            "unique_device_models": 0,
            "max_unique_devices_per_family": 0,
            "unique_locales": 0,
            "unique_app_versions": 0,
        },
        "controlled_routing_enabled": False,
    }


def _overall_readiness(distribution: Mapping[str, int]) -> str:
    for status in (
        "BLOCKED",
        "HOLD",
        "INSUFFICIENT_DATA",
        "UNKNOWN_ONLY",
        "READY",
    ):
        if distribution.get(status, 0) > 0:
            return status
    return "INSUFFICIENT_DATA"


def _readiness_distribution(value: Any) -> dict[str, int]:
    source = value if isinstance(value, Mapping) else {}
    return {status: _integer(source.get(status)) for status in READINESS_STATUSES}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _corpus_path(corpus_dir: str | Path | None) -> Path:
    return Path(corpus_dir or DEFAULT_CORPUS_DIR).expanduser().resolve()


def _open_path(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(
            ["xdg-open", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
