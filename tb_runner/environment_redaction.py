"""Shared-profile redaction boundary for environment metadata."""

from __future__ import annotations

import copy
import re
from typing import Protocol

from tb_runner.environment_profile import EnvironmentProfile, FieldStatus


class SerialTokenProvider(Protocol):
    """Interface for a future secret-backed HMAC token provider."""

    def token_for(self, serial: str) -> str | None: ...


class NoSerialTokenProvider:
    def token_for(self, serial: str) -> str | None:
        return None


def normalize_build_fingerprint(value: str) -> dict[str, str] | None:
    """Keep non-unique build family fields while dropping the full fingerprint."""
    match = re.fullmatch(
        r"(?P<brand>[^/]+)/(?P<product>[^/]+)/(?P<device>[^:]+):"
        r"(?P<release>[^/]+)/(?P<build_id>[^/]+)/(?P<incremental>[^:]+):(?P<variant>.+)",
        str(value or "").strip(),
    )
    if not match:
        return None
    return {
        "brand": match.group("brand"),
        "product": match.group("product"),
        "device": match.group("device"),
        "release": match.group("release"),
        "build_id": match.group("build_id"),
        "variant": match.group("variant"),
    }


def redact_environment_profile(
    profile: EnvironmentProfile,
    *,
    serial_token_provider: SerialTokenProvider | None = None,
) -> dict:
    """Return the canonical shared view; the input local profile is untouched."""
    payload = copy.deepcopy(profile.to_dict())
    provider = serial_token_provider or NoSerialTokenProvider()

    serial_field = payload["device"]["serial"]
    raw_serial = str(serial_field.get("value") or "")
    serial_field.update(
        {
            "value": None,
            "status": FieldStatus.REDACTED.value,
            "source": "redaction:device_serial",
            "reason": "raw_serial_excluded_from_shared_profile",
        }
    )
    token = provider.token_for(raw_serial) if raw_serial else None
    token_field = payload["device"]["serial_token"]
    if token:
        token_field.update(
            {
                "value": str(token),
                "status": FieldStatus.AVAILABLE.value,
                "source": "redaction:serial_token_provider",
                "reason": "",
            }
        )
    else:
        token_field.update(
            {
                "value": None,
                "status": FieldStatus.MISSING.value,
                "source": "redaction:serial_token_provider",
                "reason": "hmac_token_provider_not_configured",
            }
        )

    fingerprint_field = payload["android"]["build_fingerprint"]
    raw_fingerprint = str(fingerprint_field.get("value") or "")
    normalized = normalize_build_fingerprint(raw_fingerprint)
    fingerprint_field.update(
        {
            "value": normalized,
            "status": FieldStatus.REDACTED.value,
            "source": "redaction:normalized_build_fingerprint",
            "reason": "incremental_identifier_removed" if normalized else "raw_fingerprint_removed",
        }
    )
    return payload


__all__ = [
    "NoSerialTokenProvider",
    "SerialTokenProvider",
    "normalize_build_fingerprint",
    "redact_environment_profile",
]
