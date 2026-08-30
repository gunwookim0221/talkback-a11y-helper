from __future__ import annotations

import time
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable

from talkback_lib import A11yAdbClient

from .adb import run_adb

LanguageMode = str

SUPPORTED_LANGUAGE_MODES = {"current", "ko-KR", "en-US"}
LANGUAGE_SETTINGS_INTENT = "android.settings.LOCALE_SETTINGS"
SETTINGS_INTENT = "android.settings.SETTINGS"
SAMSUNG_MANUFACTURER = "samsung"
SAMSUNG_ONEUI_PROPERTY = "ro.build.version.oneui"
LOCALE_PICKER_REMOTE_XML = "/sdcard/talkback_helper_locale_picker.xml"
_LOCALE_LABELS = {
    "en-US": ("English (United States)", "English (United States)"),
    "ko-KR": ("Korean (South Korea)", "한국어(대한민국)"),
}


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
    helper_client_factory: Callable[..., Any] | None = None,
    device_serial: str | None = None,
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
                direct_result = {
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
                return _try_samsung_accessibility_fallback(
                    direct_result,
                    target_locale=mode,
                    before_locale=current_locale,
                    adb_runner=adb_runner,
                    sleep=sleep,
                    helper_client_factory=helper_client_factory,
                    device_serial=device_serial,
                )

    final_status = get_device_locale(adb_runner)
    final_locale = _normalize_locale(str(final_status.get("device_locale") or "")) if final_status.get("ok") else current_locale
    direct_result = {
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
    return _try_samsung_accessibility_fallback(
        direct_result,
        target_locale=mode,
        before_locale=current_locale,
        adb_runner=adb_runner,
        sleep=sleep,
        helper_client_factory=helper_client_factory,
        device_serial=device_serial,
    )


def is_verified_samsung_oneui(
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
) -> dict[str, object]:
    """Read-only capability gate for the isolated Samsung locale adapter."""
    try:
        manufacturer_result = adb_runner(["shell", "getprop", "ro.product.manufacturer"], 8.0)
        oneui_result = adb_runner(["shell", "getprop", SAMSUNG_ONEUI_PROPERTY], 8.0)
    except Exception as exc:
        return {
            "supported": False,
            "manufacturer": None,
            "oneui_version": None,
            "reason": f"capability_read_failed:{type(exc).__name__}",
        }

    manufacturer = str(manufacturer_result.get("stdout", "")).strip().lower()
    oneui_version = str(oneui_result.get("stdout", "")).strip()
    supported = (
        bool(manufacturer_result.get("ok"))
        and bool(oneui_result.get("ok"))
        and manufacturer == SAMSUNG_MANUFACTURER
        and bool(oneui_version)
    )
    return {
        "supported": supported,
        "manufacturer": manufacturer or None,
        "oneui_version": oneui_version or None,
        "reason": "samsung_oneui_verified" if supported else "samsung_oneui_not_verified",
    }


def _try_samsung_accessibility_fallback(
    direct_result: dict[str, object],
    *,
    target_locale: str,
    before_locale: str,
    adb_runner: Callable[[list[str], float], dict[str, object]],
    sleep: Callable[[float], None],
    helper_client_factory: Callable[..., Any] | None,
    device_serial: str | None,
) -> dict[str, object]:
    capability = is_verified_samsung_oneui(adb_runner)
    if not capability.get("supported"):
        return direct_result

    open_result = _open_locale_picker_direct(adb_runner)
    if not open_result.get("ok"):
        return {
            **direct_result,
            "fallback_attempted": True,
            "fallback_status": "FAILED",
            "fallback_reason": "locale_picker_open_failed",
            "samsung_oneui_capability": capability,
            "locale_picker_open": open_result,
        }
    sleep(0.5)

    window = _read_locale_picker_window(adb_runner)
    if not window.get("visible"):
        return {
            **direct_result,
            "fallback_attempted": True,
            "fallback_status": "WRONG_SCREEN",
            "fallback_reason": window.get("reason") or "locale_picker_window_not_verified",
            "samsung_oneui_capability": capability,
            "locale_picker_open": open_result,
            "locale_picker_window": window,
        }

    screen = _read_locale_picker_semantics(adb_runner, target_locale=target_locale)
    if not screen.get("visible"):
        return {
            **direct_result,
            "fallback_attempted": True,
            "fallback_status": _locale_picker_failure_status(screen),
            "fallback_reason": screen.get("reason") or "locale_picker_not_verified",
            "samsung_oneui_capability": capability,
            "locale_picker_open": open_result,
            "locale_picker_window": window,
            "locale_picker_screen": screen,
            "readiness": screen.get("readiness"),
        }

    target = screen.get("target") if isinstance(screen.get("target"), dict) else {}
    match_count = int(screen.get("target_match_count", 0))
    if match_count != 1:
        fallback_status = "TARGET_AMBIGUOUS" if match_count > 1 else "TARGET_NOT_FOUND"
        return {
            **direct_result,
            "fallback_attempted": True,
            "fallback_status": fallback_status,
            "fallback_reason": "target_match_count_must_equal_one",
            "samsung_oneui_capability": capability,
            "locale_picker_open": open_result,
            "locale_picker_window": window,
            "locale_picker_screen": screen,
            "readiness": screen.get("readiness"),
        }
    if not all(bool(target.get(key)) for key in ("visible", "enabled", "clickable")):
        return {
            **direct_result,
            "fallback_attempted": True,
            "fallback_status": "TARGET_NOT_ACTIONABLE",
            "fallback_reason": _target_actionability_failure_reason(target),
            "samsung_oneui_capability": capability,
            "locale_picker_open": open_result,
            "locale_picker_window": window,
            "locale_picker_screen": screen,
            "readiness": screen.get("readiness"),
        }

    try:
        if helper_client_factory is None:
            helper = A11yAdbClient(dev_serial=device_serial, start_monitor=False)
        else:
            try:
                helper = helper_client_factory(dev_serial=device_serial, start_monitor=False)
            except TypeError:
                helper = helper_client_factory()
        if not helper.check_helper_status(dev=device_serial):
            raise RuntimeError("helper_service_unavailable")
        helper_result = helper.set_system_language(
            dev=device_serial,
            locale=target_locale,
            current_locale=before_locale,
            wait_=5.0,
        )
    except Exception as exc:
        return {
            **direct_result,
            "fallback_attempted": True,
            "fallback_status": "HELPER_SERVICE_UNAVAILABLE" if str(exc) in {
                "helper_not_ready",
                "helper_service_unavailable",
            } else "FAILED",
            "fallback_reason": str(exc) or type(exc).__name__,
            "samsung_oneui_capability": capability,
            "locale_picker_open": open_result,
            "locale_picker_window": window,
            "locale_picker_screen": screen,
            "readiness": screen.get("readiness"),
        }

    helper_status = str(helper_result.get("status") or "FAILED")
    if helper_status not in {"ACTION_PERFORMED", "ALREADY_ACTIVE"}:
        return {
            **direct_result,
            "fallback_attempted": True,
            "fallback_status": helper_status,
            "fallback_reason": helper_result.get("reason") or "helper_rejected_locale_target",
            "samsung_oneui_capability": capability,
            "locale_picker_open": open_result,
            "locale_picker_window": window,
            "locale_picker_screen": screen,
            "helper_result": helper_result,
            "readiness": helper_result.get("readiness") or screen.get("readiness"),
        }

    verification = _poll_effective_locale(
        target_locale=target_locale,
        adb_runner=adb_runner,
        sleep=sleep,
        attempts=12,
        interval_seconds=1.0,
    )
    if verification.get("verified"):
        return {
            **direct_result,
            "ok": True,
            "status": "ok",
            "device_locale": verification.get("device_locale"),
            "target_locale": target_locale,
            "changed": before_locale != target_locale,
            "verified": True,
            "fallback_attempted": True,
            "fallback_status": "SUCCESS",
            "samsung_oneui_capability": capability,
            "locale_picker_open": open_result,
            "locale_picker_screen": screen,
            "helper_result": helper_result,
            "readiness": helper_result.get("readiness") or screen.get("readiness"),
            "post_action_verification": verification,
        }

    observation = _observe_locale_picker_after_action(adb_runner, helper, device_serial)
    return {
        **direct_result,
        "fallback_attempted": True,
        "fallback_status": observation["status"],
        "fallback_reason": observation["reason"],
        "confirmation_ui": observation["confirmation_ui"],
        "confirmation_action_executed": False,
        "samsung_oneui_capability": capability,
        "locale_picker_open": open_result,
        "locale_picker_screen": screen,
        "helper_result": helper_result,
        "readiness": helper_result.get("readiness") or screen.get("readiness"),
        "post_action_verification": verification,
        "post_action_observation": observation,
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


def _open_locale_picker_direct(
    adb_runner: Callable[[list[str], float], dict[str, object]],
) -> dict[str, object]:
    result = adb_runner(["shell", "am", "start", "-a", LANGUAGE_SETTINGS_INTENT], 10.0)
    return {
        **result,
        "intent": LANGUAGE_SETTINGS_INTENT,
        "status": "opened" if result.get("ok") else "error",
    }


def _read_locale_picker_window(
    adb_runner: Callable[[list[str], float], dict[str, object]],
) -> dict[str, object]:
    result = adb_runner(["shell", "dumpsys", "window"], 8.0)
    output = str(result.get("stdout", ""))
    component = "com.android.settings/.Settings$LocalePickerActivity"
    visible = bool(result.get("ok")) and "com.android.settings" in output and component in output
    return {
        "visible": visible,
        "component": component if visible else None,
        "reason": None if visible else "locale_picker_window_not_verified",
    }


def _read_locale_picker_semantics(
    adb_runner: Callable[[list[str], float], dict[str, object]],
    *,
    target_locale: str = "ko-KR",
) -> dict[str, object]:
    dump = adb_runner(["shell", "uiautomator", "dump", LOCALE_PICKER_REMOTE_XML], 8.0)
    if not dump.get("ok"):
        return {
            "visible": False,
            "reason": "uiautomator_dump_failed",
            "readiness": _empty_locale_readiness(root_available=False),
        }
    raw = adb_runner(["shell", "cat", LOCALE_PICKER_REMOTE_XML], 8.0)
    if not raw.get("ok"):
        return {
            "visible": False,
            "reason": "uiautomator_dump_read_failed",
            "readiness": _empty_locale_readiness(root_available=False),
        }
    try:
        hierarchy = ET.fromstring(str(raw.get("stdout", "")))
    except ET.ParseError:
        return {
            "visible": False,
            "reason": "uiautomator_xml_invalid",
            "readiness": _empty_locale_readiness(root_available=False),
        }

    root = hierarchy.find("node")
    nodes = list(root.iter("node")) if root is not None else []
    root_package = root.attrib.get("package") if root is not None else None
    package_matches = root_package == "com.android.settings"
    list_node = next(
        (node for node in nodes if node.attrib.get("resource-id") == "com.android.settings:id/locale_list_view"),
        None,
    )
    recycler = next(
        (node for node in nodes if node.attrib.get("resource-id") == "com.android.settings:id/locale_recycler_view"),
        None,
    )
    language_desc = next(
        (node for node in nodes if node.attrib.get("resource-id") == "com.android.settings:id/language_desc"),
        None,
    )
    expected_ancestry = (
        recycler is not None
        and _is_locale_picker_context_node(recycler)
        and language_desc is not None
        and _is_locale_picker_context_node(language_desc)
    )
    readiness = {
        "serviceAvailable": True,
        "rootAvailable": root is not None,
        "rootPackage": root_package,
        "packageMatches": package_matches,
        "localeListPresent": list_node is not None,
        "localeRecyclerPresent": recycler is not None,
        "languageDescriptionPresent": language_desc is not None,
        "expectedAncestry": expected_ancestry,
        "targetMatchCount": 0,
        "targetVisible": None,
        "targetEnabled": None,
        "targetClickable": None,
    }
    if not package_matches:
        return {
            "visible": False,
            "reason": "expected_settings_package",
            "readiness": readiness,
        }
    if not all(
        bool(readiness[key])
        for key in (
            "localeRecyclerPresent",
            "languageDescriptionPresent",
            "expectedAncestry",
        )
    ):
        return {
            "visible": False,
            "reason": _locale_picker_readiness_failure_reason(readiness),
            "readiness": readiness,
        }

    result: dict[str, object] = {
        "visible": True,
        "package": "com.android.settings",
        "target_match_count": 0,
        "english_match_count": 0,
        "korean_match_count": 0,
        "readiness": readiness,
    }

    def row_matches_locale(row: ET.Element, locale: str) -> ET.Element | None:
        canonical, native = _LOCALE_LABELS[locale]
        labels = [
            node
            for node in row.iter("node")
            if node.attrib.get("resource-id") == "com.android.settings:id/label"
        ]
        return next(
            (
                candidate
                for candidate in labels
                if candidate.attrib.get("text", "").strip() in {canonical, native}
                or candidate.attrib.get("content-desc", "").strip() in {canonical, native}
            ),
            None,
        )

    target_evidence: dict[str, object] | None = None
    for row in list(recycler):
        label = row_matches_locale(row, target_locale)
        if label is None:
            continue
        evidence = {
            "resource_id": row.attrib.get("resource-id") or None,
            "class_name": row.attrib.get("class", ""),
            "visible": _xml_row_is_visible(row, recycler),
            "enabled": row.attrib.get("enabled", "false").lower() == "true",
            "clickable": row.attrib.get("clickable", "false").lower() == "true",
            "focusable": row.attrib.get("focusable", "false").lower() == "true",
            "bounds": row.attrib.get("bounds", ""),
            "label_text": label.attrib.get("text", ""),
            "label_content_description": label.attrib.get("content-desc", ""),
        }
        result["target_match_count"] = int(result["target_match_count"]) + 1
        if target_evidence is None:
            target_evidence = evidence

    for row in list(recycler):
        if row_matches_locale(row, "en-US") is not None:
            result["english_match_count"] = int(result["english_match_count"]) + 1
        if row_matches_locale(row, "ko-KR") is not None:
            result["korean_match_count"] = int(result["korean_match_count"]) + 1
    result["target"] = target_evidence or {}
    readiness["targetMatchCount"] = result["target_match_count"]
    if target_evidence is not None:
        readiness["targetVisible"] = target_evidence["visible"]
        readiness["targetEnabled"] = target_evidence["enabled"]
        readiness["targetClickable"] = target_evidence["clickable"]
    return result


def _empty_locale_readiness(*, root_available: bool) -> dict[str, object]:
    return {
        "serviceAvailable": True,
        "rootAvailable": root_available,
        "rootPackage": None,
        "packageMatches": False,
        "localeListPresent": False,
        "localeRecyclerPresent": False,
        "languageDescriptionPresent": False,
        "expectedAncestry": False,
        "targetMatchCount": 0,
        "targetVisible": None,
        "targetEnabled": None,
        "targetClickable": None,
    }


def _locale_picker_readiness_failure_reason(readiness: dict[str, object]) -> str:
    if not readiness.get("localeRecyclerPresent"):
        return "locale_recycler_missing"
    if not readiness.get("languageDescriptionPresent"):
        return "language_desc_missing"
    if not readiness.get("expectedAncestry"):
        return "expected_ancestry_missing"
    return "locale_picker_hierarchy_not_ready"


def _is_locale_picker_context_node(node: ET.Element) -> bool:
    package = node.attrib.get("package", "").strip()
    return not package or package == "com.android.settings"


def _locale_picker_failure_status(screen: dict[str, object]) -> str:
    readiness = screen.get("readiness")
    if not isinstance(readiness, dict):
        return "WINDOW_NOT_READY"
    if readiness.get("rootAvailable") is False:
        return "WINDOW_NOT_READY"
    if readiness.get("packageMatches") is False and readiness.get("rootPackage"):
        return "WRONG_SCREEN"
    return "WINDOW_NOT_READY"


def _target_actionability_failure_reason(target: dict[str, object]) -> str:
    if not target.get("visible"):
        return "target_not_visible"
    if not target.get("enabled"):
        return "target_not_enabled"
    if not target.get("clickable"):
        return "target_not_clickable"
    return "target_not_actionable"


def _xml_bounds(value: str | None) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", str(value or "").strip())
    if match is None:
        return None
    return tuple(int(item) for item in match.groups())


def _xml_row_is_visible(row: ET.Element, recycler: ET.Element) -> bool:
    explicit = row.attrib.get("visible-to-user")
    if explicit is not None:
        return explicit.lower() == "true"
    row_bounds = _xml_bounds(row.attrib.get("bounds"))
    recycler_bounds = _xml_bounds(recycler.attrib.get("bounds"))
    if row_bounds is None or recycler_bounds is None:
        return False
    row_left, row_top, row_right, row_bottom = row_bounds
    list_left, list_top, list_right, list_bottom = recycler_bounds
    return (
        row_left < list_right
        and row_right > list_left
        and row_top < list_bottom
        and row_bottom > list_top
    )


def _poll_effective_locale(
    *,
    target_locale: str,
    adb_runner: Callable[[list[str], float], dict[str, object]],
    sleep: Callable[[float], None],
    attempts: int,
    interval_seconds: float,
) -> dict[str, object]:
    last: dict[str, object] = {"ok": False, "device_locale": None, "system_locale": None}
    count = max(1, attempts)
    for attempt in range(count):
        last = get_device_locale(adb_runner)
        if last.get("ok") and _normalize_locale(str(last.get("device_locale") or "")) == target_locale:
            return {
                "verified": True,
                "attempt": attempt + 1,
                "device_locale": target_locale,
                "system_locale": last.get("system_locale"),
            }
        if attempt + 1 < count:
            sleep(interval_seconds)
    return {
        "verified": False,
        "attempts": count,
        "device_locale": last.get("device_locale"),
        "system_locale": last.get("system_locale"),
    }


def _observe_locale_picker_after_action(adb_runner, helper: Any, device_serial: str | None) -> dict[str, object]:
    window = adb_runner(["shell", "dumpsys", "window"], 8.0)
    window_text = str(window.get("stdout", ""))
    try:
        tree = helper.dump_tree(dev=device_serial, wait_seconds=3.0)
    except Exception as exc:
        tree = []
        tree_error = f"dump_tree_failed:{type(exc).__name__}"
    else:
        tree_error = None
    tree_text = " ".join(
        str(item.get(key, ""))
        for item in tree
        if isinstance(item, dict)
        for key in ("text", "contentDescription", "content-desc", "className", "resourceId")
    )
    combined = f"{window_text} {tree_text}".lower()
    confirmation_tokens = ("confirm", "apply", "done", "ok", "확인", "적용", "완료")
    confirmation_discovered = any(token in combined for token in confirmation_tokens)
    locale_picker_still_visible = "com.android.settings" in window_text and "LocalePickerActivity" in window_text
    if confirmation_discovered:
        return {
            "status": "CONFIRMATION_REQUIRED",
            "reason": "confirmation_ui_discovered_without_safe_confirmation_contract",
            "confirmation_ui": "DISCOVERED",
            "locale_picker_still_visible": locale_picker_still_visible,
            "tree_error": tree_error,
        }
    return {
        "status": "LOCALE_CHANGE_UNVERIFIED",
        "reason": "effective_locale_did_not_verify_and_no_safe_confirmation_contract",
        "confirmation_ui": "NONE",
        "locale_picker_still_visible": locale_picker_still_visible,
        "tree_error": tree_error,
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
