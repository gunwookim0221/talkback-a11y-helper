"""Deterministic JSON serialization used by environment contracts."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


def normalize_canonical_value(value: Any) -> Any:
    """Return a JSON-safe value with stable Unicode and collection ordering."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Enum):
        return normalize_canonical_value(value.value)
    if isinstance(value, Mapping):
        return {
            unicodedata.normalize("NFC", str(key)): normalize_canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [normalize_canonical_value(item) for item in value]
    if isinstance(value, set):
        normalized = [normalize_canonical_value(item) for item in value]
        return sorted(normalized, key=lambda item: canonical_json(item))
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("canonical JSON does not allow non-finite floats")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize as sorted, compact UTF-8 JSON with NFC-normalized strings."""
    return json.dumps(
        normalize_canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "canonical_json",
    "canonical_json_bytes",
    "canonical_sha256",
    "normalize_canonical_value",
]
