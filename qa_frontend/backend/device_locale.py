from __future__ import annotations

import time
from typing import Callable

from .adb import run_adb

LanguageMode = str

SUPPORTED_LANGUAGE_MODES = {"current", "ko-KR", "en-US"}
LANGUAGE_SETTINGS_INTENT = "android.settings.LOCALE_SETTINGS"
SETTINGS_INTENT = "android.settings.SETTINGS"


def normalize_language_mode(language_mode: str | None) -> LanguageMode:
    value = str(language_mode or "current").strip()
    if value not in SUPPORTED_LANGUAGE_MODES:
        raise ValueError("language_mode must be current, ko-KR, or en-US")
    return value


def get_device_locale(adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb) -> dict[str, object]:
    persist = adb_runner(["shell", "getprop", "persist.sys.locale"], 8.0)
    if not persist.get("ok"):
        return {
            **persist,
            "status": "error",
            "device_locale": None,
            "error": persist.get("error") or persist.get("stderr") or "failed to read persist.sys.locale",
        }

    locale = _normalize_locale(str(persist.get("stdout", "")).strip())
    persist_locale = locale
    source = "persist.sys.locale"
    system_locales_result = adb_runner(["shell", "settings", "get", "system", "system_locales"], 8.0)
    system_locale = _normalize_locale(str(system_locales_result.get("stdout", "")).strip().split(",", 1)[0]) if system_locales_result.get("ok") else None
    if not locale:
        product = adb_runner(["shell", "getprop", "ro.product.locale"], 8.0)
        if not product.get("ok"):
            return {
                **product,
                "status": "error",
                "device_locale": None,
                "error": product.get("error") or product.get("stderr") or "failed to read ro.product.locale",
            }
        locale = _normalize_locale(str(product.get("stdout", "")).strip())
        source = "ro.product.locale"

    return {
        "ok": True,
        "status": "ok",
        "device_locale": locale,
        "source": source,
        "persist_locale": persist_locale,
        "system_locale": system_locale,
    }


def apply_language_mode(
    language_mode: str | None,
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    mode = normalize_language_mode(language_mode)
    if mode == "current":
        current = get_device_locale(adb_runner)
        return {
            "ok": True,
            "status": "ok" if current.get("ok") else "unknown",
            "language_mode": mode,
            "device_locale": _normalize_locale(str(current.get("device_locale") or "")),
            "before_locale": _normalize_locale(str(current.get("device_locale") or "")),
            "target_locale": None,
            "changed": False,
            "verified": bool(current.get("ok")),
            "commands_attempted": [],
            "error": current.get("error") if not current.get("ok") else None,
        }

    before = get_device_locale(adb_runner)
    if not before.get("ok"):
        return {
            **before,
            "ok": False,
            "status": "error",
            "language_mode": mode,
            "device_locale": before.get("device_locale"),
            "changed": False,
            "verified": False,
        }

    current_locale = _normalize_locale(str(before.get("device_locale") or ""))
    current_system_locale = _normalize_locale(str(before.get("system_locale") or ""))
    if current_locale == mode and current_system_locale == mode:
        return {
            "ok": True,
            "status": "ok",
            "language_mode": mode,
            "device_locale": current_locale,
            "before_locale": current_locale,
            "target_locale": mode,
            "changed": False,
            "verified": True,
            "commands_attempted": [],
        }

    commands = [["shell", "settings", "put", "system", "system_locales", mode]]
    attempted: list[dict[str, object]] = []
    for command in commands:
        result = adb_runner(command, 12.0)
        attempted.append(
            {
                "command": command,
                "ok": bool(result.get("ok")),
                "stderr": result.get("stderr"),
                "stdout": result.get("stdout"),
            }
        )
        if result.get("ok"):
            sleep(2.0)
            verify = get_device_locale(adb_runner)
            verified_locale = _normalize_locale(str(verify.get("device_locale") or ""))
            if verify.get("ok") and verified_locale == mode:
                return {
                    "ok": True,
                    "status": "ok",
                    "language_mode": mode,
                    "device_locale": verified_locale,
                    "before_locale": current_locale,
                    "target_locale": mode,
                    "changed": True,
                    "verified": True,
                    "commands_attempted": attempted,
                }
            if verify.get("ok") and _normalize_locale(str(verify.get("system_locale") or "")) == mode:
                return {
                    "ok": False,
                    "status": "error",
                    "language_mode": mode,
                    "device_locale": verified_locale,
                    "before_locale": current_locale,
                    "target_locale": mode,
                    "changed": False,
                    "verified": False,
                    "commands_attempted": attempted,
                    "manual_language_change_required": True,
                    "settings_intent": LANGUAGE_SETTINGS_INTENT,
                    "error": (
                        f"device locale did not verify as {mode}. "
                        "Manual language change required: system_locales was updated, but the effective device locale did not change on this device."
                    ),
                }

    final_status = get_device_locale(adb_runner)
    final_locale = _normalize_locale(str(final_status.get("device_locale") or "")) if final_status.get("ok") else current_locale
    return {
        "ok": False,
        "status": "error",
        "language_mode": mode,
        "device_locale": final_locale,
        "before_locale": current_locale,
        "target_locale": mode,
        "changed": False,
        "verified": False,
        "commands_attempted": attempted,
        "manual_language_change_required": True,
        "settings_intent": LANGUAGE_SETTINGS_INTENT,
        "error": f"device locale did not verify as {mode}. Manual language change required on this device.",
    }


def open_language_settings(adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb) -> dict[str, object]:
    attempted: list[dict[str, object]] = []
    for intent in (LANGUAGE_SETTINGS_INTENT, SETTINGS_INTENT):
        result = adb_runner(["shell", "am", "start", "-a", intent], 10.0)
        attempted.append(
            {
                "intent": intent,
                "ok": bool(result.get("ok")),
                "stdout": result.get("stdout"),
                "stderr": result.get("stderr"),
            }
        )
        if result.get("ok"):
            return {
                "ok": True,
                "status": "opened",
                "intent": intent,
                "attempted": attempted,
            }

    last = attempted[-1] if attempted else {}
    return {
        "ok": False,
        "status": "error",
        "intent": LANGUAGE_SETTINGS_INTENT,
        "attempted": attempted,
        "error": last.get("stderr") or last.get("stdout") or "failed to open language settings",
    }


def format_language_log_lines(language_status: dict[str, object]) -> list[str]:
    return [
        "[QA_FRONTEND][language] "
        f"language_mode='{language_status.get('language_mode')}' "
        f"device_locale='{language_status.get('device_locale')}' "
        f"target_locale='{language_status.get('target_locale')}' "
        f"changed='{str(bool(language_status.get('changed'))).lower()}' "
        f"verified='{str(bool(language_status.get('verified'))).lower()}' "
        f"status='{language_status.get('status')}'",
    ]


def _normalize_locale(value: str) -> str | None:
    raw = value.strip().replace("_", "-")
    if not raw or raw.lower() in {"null", "none"}:
        return None
    parts = raw.split("-")
    if len(parts) == 1:
        return parts[0].lower()
    return f"{parts[0].lower()}-{parts[1].upper()}"
