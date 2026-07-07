from __future__ import annotations

import glob
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from talkback_lib import A11yAdbClient
from talkback_lib.constants import DEFAULT_ADB_PATH
from tb_runner.accessibility_preflight import HELPER_SERVICE_COMPONENT
from tb_runner.samsung_account_popup import find_samsung_account_popup_candidate

from .paths import ROOT_DIR


HELPER_PACKAGE_NAME = "com.iotpart.sqe.talkbackhelper"
HELPER_SERVICE_SHORT_COMPONENT = "com.iotpart.sqe.talkbackhelper/.A11yHelperService"
HELPER_NAME = "TalkBack A11y Helper"
HELPER_APK_SEARCH_PATTERNS = [
    "app/build/outputs/apk/**/*.apk",
    "android/app/build/outputs/apk/**/*.apk",
]
HELPER_BUILD_COMMAND = r".\gradlew.bat :app:assembleDebug"
TALKBACK_SERVICE_CANDIDATES = [
    "com.samsung.android.accessibility.talkback/com.samsung.android.marvin.talkback.TalkBackService",
    "com.google.android.marvin.talkback/com.google.android.marvin.talkback.TalkBackService",
]
TALKBACK_PACKAGE_TO_SERVICE = {
    "com.samsung.android.accessibility.talkback": TALKBACK_SERVICE_CANDIDATES[0],
    "com.google.android.marvin.talkback": TALKBACK_SERVICE_CANDIDATES[1],
}
def _relative_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _helper_metadata(apk_path: Path | None = None) -> dict[str, object]:
    return {
        "helper_name": HELPER_NAME,
        "package_name": HELPER_PACKAGE_NAME,
        "service_name": HELPER_SERVICE_COMPONENT,
        "component": HELPER_SERVICE_COMPONENT,
        "package": HELPER_PACKAGE_NAME,
        "apk_found": apk_path is not None,
        "apk_path": _relative_path(apk_path),
        "apk_searched": HELPER_APK_SEARCH_PATTERNS,
        "build_command": HELPER_BUILD_COMMAND,
    }


def _dismiss_samsung_account_popup_once(adb_runner=None) -> dict[str, object]:
    adb_runner = adb_runner or run_adb
    dump_result = adb_runner(["shell", "uiautomator", "dump", "/sdcard/fix_talkback_popup.xml"], timeout=8.0)
    if not dump_result.get("ok"):
        return {"popup_detected": False, "popup_dismissed": False}
    cat_result = adb_runner(["shell", "cat", "/sdcard/fix_talkback_popup.xml"], timeout=8.0)
    if not cat_result.get("ok"):
        return {"popup_detected": False, "popup_dismissed": False}
    try:
        root = ET.fromstring(str(cat_result.get("stdout", "")))
    except ET.ParseError:
        return {"popup_detected": False, "popup_dismissed": False}

    candidate = find_samsung_account_popup_candidate(root.iter("node"))
    if candidate is None:
        return {"popup_detected": False, "popup_dismissed": False}
    tap_result = adb_runner(["shell", "input", "tap", str(candidate.x), str(candidate.y)], timeout=5.0)
    return {
        "popup_detected": True,
        "popup_dismissed": bool(tap_result.get("ok")),
        "dismiss_method": candidate.method,
        "label": candidate.label,
        "resource_id": candidate.resource_id,
        "locale": candidate.locale,
        "title": candidate.title,
    }


def run_adb(args: list[str], timeout: float = 10.0) -> dict[str, object]:
    command = [DEFAULT_ADB_PATH, *args]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "status": "error", "error": str(exc), "command": command}
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "status": "error",
            "error": f"adb command timed out after {timeout}s",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "command": command,
        }
    except Exception as exc:
        return {"ok": False, "status": "error", "error": str(exc), "command": command}

    return {
        "ok": completed.returncode == 0,
        "status": "ok" if completed.returncode == 0 else "error",
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "command": command,
    }


def get_adb_status() -> dict[str, object]:
    result = run_adb(["devices"], timeout=8.0)
    if not result.get("ok"):
        return {**result, "devices": []}

    devices: list[dict[str, str]] = []
    for line in str(result.get("stdout", "")).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devices.append({"serial": parts[0], "state": parts[1]})
    return {**result, "devices": devices}


def get_helper_status() -> dict[str, object]:
    apk_path = _find_helper_apk()
    metadata = _helper_metadata(apk_path)
    if apk_path is None:
        return {
            **metadata,
            "ok": True,
            "status": "apk_not_found",
            "installed": False,
            "accessibility_enabled": False,
            "package_installed": False,
            "enabled": False,
            "enabled_accessibility_services": "",
        }

    package_result = run_adb(["shell", "pm", "list", "packages"], timeout=8.0)
    if not package_result.get("ok"):
        return {
            **package_result,
            **metadata,
            "status": "error",
            "adb_status": "adb_error",
            "installed": False,
            "accessibility_enabled": False,
            "package_installed": False,
            "enabled": False,
            "enabled_accessibility_services": "",
        }

    services_result = run_adb(["shell", "settings", "get", "secure", "enabled_accessibility_services"], timeout=8.0)
    if not services_result.get("ok"):
        return {
            **services_result,
            **metadata,
            "status": "error",
            "adb_status": "adb_error",
            "installed": False,
            "accessibility_enabled": False,
            "package_installed": False,
            "enabled": False,
            "enabled_accessibility_services": "",
        }

    installed_packages = str(package_result.get("stdout", "")).splitlines()
    package_installed = any(line.strip() == f"package:{HELPER_PACKAGE_NAME}" for line in installed_packages)
    enabled_services = str(services_result.get("stdout", "")).strip()
    enabled = _has_enabled_helper_service(enabled_services)
    if package_installed and enabled:
        status = "ok"
    elif package_installed:
        status = "disabled"
    else:
        status = "not_installed"
    return {
        **services_result,
        **metadata,
        "status": status,
        "installed": package_installed,
        "accessibility_enabled": enabled,
        "package_installed": package_installed,
        "enabled": enabled,
        "enabled_accessibility_services": enabled_services,
    }


def _get_installed_packages() -> dict[str, object]:
    result = run_adb(["shell", "pm", "list", "packages"], timeout=8.0)
    if not result.get("ok"):
        return {**result, "packages": set()}
    packages = {
        line.strip().split(":", 1)[1]
        for line in str(result.get("stdout", "")).splitlines()
        if line.strip().startswith("package:")
    }
    return {**result, "packages": packages}


def _get_enabled_accessibility_services() -> dict[str, object]:
    result = run_adb(["shell", "settings", "get", "secure", "enabled_accessibility_services"], timeout=8.0)
    services = str(result.get("stdout", "")).strip() if result.get("ok") else ""
    return {**result, "enabled_accessibility_services": services}


def _get_accessibility_enabled() -> dict[str, object]:
    result = run_adb(["shell", "settings", "get", "secure", "accessibility_enabled"], timeout=8.0)
    value = str(result.get("stdout", "")).strip() if result.get("ok") else ""
    return {**result, "accessibility_enabled": value}


def _split_enabled_accessibility_services(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"null", "none"}:
        return []
    return [item.strip().lower() for item in raw.split(":") if item.strip()]


def _split_enabled_accessibility_services_preserve(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"null", "none"}:
        return []
    return [item.strip() for item in raw.split(":") if item.strip()]


def _has_enabled_helper_service(enabled_services: str | None) -> bool:
    services = set(_split_enabled_accessibility_services(enabled_services))
    return (
        HELPER_SERVICE_COMPONENT.lower() in services
        or HELPER_SERVICE_SHORT_COMPONENT.lower() in services
    )


def _find_helper_apk() -> Path | None:
    candidates: list[Path] = []
    for pattern in HELPER_APK_SEARCH_PATTERNS:
        candidates.extend(Path(match) for match in glob.glob(str(ROOT_DIR / pattern), recursive=True))
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def install_helper() -> dict[str, object]:
    apk_path = _find_helper_apk()
    if apk_path is None:
        return {
            "ok": False,
            "status": "apk_not_found",
            **_helper_metadata(None),
            "error": f"{HELPER_NAME} APK not found. Build it first: {HELPER_BUILD_COMMAND}",
            "searched": HELPER_APK_SEARCH_PATTERNS,
        }
    result = run_adb(["install", "-r", str(apk_path)], timeout=120.0)
    return {**result, **_helper_metadata(apk_path), "apk": str(apk_path)}


def enable_helper() -> dict[str, object]:
    services_result = _get_enabled_accessibility_services()
    if not services_result.get("ok"):
        return {
            **services_result,
            **_helper_metadata(_find_helper_apk()),
            "status": "error",
            "adb_status": "adb_error",
            "error": services_result.get("error") or services_result.get("stderr") or "failed to read accessibility services",
        }

    before = str(services_result.get("enabled_accessibility_services", "")).strip()
    services = _split_enabled_accessibility_services_preserve(before)
    normalized = {service.lower() for service in services}
    appended = False
    if (
        HELPER_SERVICE_COMPONENT.lower() not in normalized
        and HELPER_SERVICE_SHORT_COMPONENT.lower() not in normalized
    ):
        services.append(HELPER_SERVICE_COMPONENT)
        appended = True
        write_result = run_adb(
            ["shell", "settings", "put", "secure", "enabled_accessibility_services", ":".join(services)],
            timeout=8.0,
        )
        if not write_result.get("ok"):
            return {
                **write_result,
                **_helper_metadata(_find_helper_apk()),
                "status": "error",
                "adb_status": "adb_error",
                "error": write_result.get("error") or write_result.get("stderr") or "failed to update accessibility services",
                "before_enabled_accessibility_services": before,
            }

    enabled_result = run_adb(["shell", "settings", "put", "secure", "accessibility_enabled", "1"], timeout=8.0)
    if not enabled_result.get("ok"):
        return {
            **enabled_result,
            **_helper_metadata(_find_helper_apk()),
            "status": "error",
            "adb_status": "adb_error",
            "error": enabled_result.get("error") or enabled_result.get("stderr") or "failed to enable accessibility",
            "before_enabled_accessibility_services": before,
            "helper_service_appended": appended,
        }

    status = get_helper_status()
    return {
        **status,
        "before_enabled_accessibility_services": before,
        "after_enabled_accessibility_services": ":".join(services),
        "helper_service_appended": appended,
    }


def enable_talkback() -> dict[str, object]:
    packages_result = _get_installed_packages()
    if not packages_result.get("ok"):
        return {
            **packages_result,
            "status": "error",
            "adb_status": "adb_error",
            "candidates": TALKBACK_SERVICE_CANDIDATES,
            "error": packages_result.get("error") or packages_result.get("stderr") or "failed to read installed packages",
        }

    installed_packages = packages_result.get("packages")
    package_names = installed_packages if isinstance(installed_packages, set) else set()
    selected_service = next(
        (service for package, service in TALKBACK_PACKAGE_TO_SERVICE.items() if package in package_names),
        None,
    )
    if selected_service is None:
        return {
            "ok": False,
            "status": "error",
            "error": "TalkBack service package not found",
            "candidates": TALKBACK_SERVICE_CANDIDATES,
        }

    services_result = _get_enabled_accessibility_services()
    if not services_result.get("ok"):
        return {
            **services_result,
            "status": "error",
            "adb_status": "adb_error",
            "service_name": selected_service,
            "candidates": TALKBACK_SERVICE_CANDIDATES,
            "error": services_result.get("error") or services_result.get("stderr") or "failed to read accessibility services",
        }

    accessibility_enabled_result = _get_accessibility_enabled()
    if not accessibility_enabled_result.get("ok"):
        return {
            **accessibility_enabled_result,
            "status": "error",
            "adb_status": "adb_error",
            "service_name": selected_service,
            "candidates": TALKBACK_SERVICE_CANDIDATES,
            "error": accessibility_enabled_result.get("error") or accessibility_enabled_result.get("stderr") or "failed to read accessibility enabled state",
        }

    before_services = str(services_result.get("enabled_accessibility_services", "")).strip()
    services = _split_enabled_accessibility_services_preserve(before_services)
    normalized = {service.lower() for service in services}
    appended = False
    if selected_service.lower() not in normalized:
        services.append(selected_service)
        appended = True
        write_services_result = run_adb(
            ["shell", "settings", "put", "secure", "enabled_accessibility_services", ":".join(services)],
            timeout=8.0,
        )
        if not write_services_result.get("ok"):
            return {
                **write_services_result,
                "status": "error",
                "adb_status": "adb_error",
                "service_name": selected_service,
                "candidates": TALKBACK_SERVICE_CANDIDATES,
                "before_enabled_accessibility_services": before_services,
                "error": write_services_result.get("error") or write_services_result.get("stderr") or "failed to update accessibility services",
            }

    enable_result = run_adb(["shell", "settings", "put", "secure", "accessibility_enabled", "1"], timeout=8.0)
    if not enable_result.get("ok"):
        return {
            **enable_result,
            "status": "error",
            "adb_status": "adb_error",
            "service_name": selected_service,
            "candidates": TALKBACK_SERVICE_CANDIDATES,
            "before_enabled_accessibility_services": before_services,
            "error": enable_result.get("error") or enable_result.get("stderr") or "failed to enable accessibility",
        }

    verify_services_result = _get_enabled_accessibility_services()
    verify_enabled_result = _get_accessibility_enabled()
    final_services = str(verify_services_result.get("enabled_accessibility_services", "")).strip()
    enabled = selected_service.lower() in {service.lower() for service in _split_enabled_accessibility_services(final_services)}
    if not verify_services_result.get("ok") or not verify_enabled_result.get("ok") or not enabled:
        return {
            "ok": False,
            "status": "error",
            "service_name": selected_service,
            "candidates": TALKBACK_SERVICE_CANDIDATES,
            "before_enabled_accessibility_services": before_services,
            "enabled_accessibility_services": final_services,
            "accessibility_enabled": str(verify_enabled_result.get("accessibility_enabled", "")).strip(),
            "helper_service_preserved": _has_enabled_helper_service(final_services),
            "talkback_service_appended": appended,
            "error": "TalkBack service did not verify after update",
        }

    return {
        "ok": True,
        "status": "enabled",
        "service_name": selected_service,
        "selected_package": selected_service.split("/", 1)[0],
        "candidates": TALKBACK_SERVICE_CANDIDATES,
        "before_enabled_accessibility_services": before_services,
        "enabled_accessibility_services": final_services,
        "accessibility_enabled": str(verify_enabled_result.get("accessibility_enabled", "")).strip(),
        "helper_service_preserved": _has_enabled_helper_service(final_services),
        "talkback_service_appended": appended,
    }


def fix_talkback(
    *,
    adb_status_fn=get_adb_status,
    helper_status_fn=get_helper_status,
    enable_helper_fn=enable_helper,
    enable_talkback_fn=enable_talkback,
    open_settings_fn=None,
    client_factory=A11yAdbClient,
    sleep_fn=time.sleep,
) -> dict[str, object]:
    steps: list[dict[str, object]] = []

    adb_status = adb_status_fn()
    device_ready = bool(adb_status.get("ok")) and any(
        isinstance(device, dict) and device.get("state") == "device"
        for device in adb_status.get("devices", [])
        if isinstance(device, dict)
    )
    if not device_ready:
        return {
            "ok": False,
            "status": "adb_unavailable",
            "message": "ADB device is not ready. Connect a device and retry.",
            "adb_status": adb_status,
            "steps": steps,
        }

    wake_result = run_adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], timeout=8.0)
    steps.append({"step": "wake_device", "ok": bool(wake_result.get("ok"))})
    unlock_result = run_adb(["shell", "input", "swipe", "500", "1800", "500", "600", "300"], timeout=8.0)
    steps.append({"step": "unlock_swipe", "ok": bool(unlock_result.get("ok"))})

    helper_status = helper_status_fn()
    helper_state = str(helper_status.get("status") or "")
    if helper_state == "apk_not_found":
        return {
            "ok": False,
            "status": "helper_not_ready",
            "message": "Helper APK was not found. Build or install the helper, then retry.",
            "helper_status": helper_status,
            "steps": steps,
        }
    if helper_state != "ok":
        helper_status = enable_helper_fn()
        steps.append({"step": "enable_helper", "ok": bool(helper_status.get("ok")), "status": helper_status.get("status")})
        if helper_status.get("status") != "ok":
            return {
                "ok": False,
                "status": "helper_not_ready",
                "message": "Helper accessibility service is not ready. Enable Helper service and retry.",
                "helper_status": helper_status,
                "steps": steps,
            }

    enable_result = enable_talkback_fn()
    steps.append({"step": "enable_talkback", "ok": bool(enable_result.get("ok")), "status": enable_result.get("status")})
    if not enable_result.get("ok"):
        return {
            "ok": False,
            "status": "talkback_enable_failed",
            "message": str(enable_result.get("error") or "TalkBack could not be enabled via ADB."),
            "talkback_enable": enable_result,
            "steps": steps,
        }

    sleep_fn(1.0)
    popup_result = _dismiss_samsung_account_popup_once(run_adb)
    if popup_result.get("popup_detected"):
        steps.append(
            {
                "step": "dismiss_samsung_account_popup",
                "ok": bool(popup_result.get("popup_dismissed")),
                "status": "dismissed" if popup_result.get("popup_dismissed") else "dismiss_failed",
            }
        )
        sleep_fn(0.5)
    client = client_factory(start_monitor=False)
    readiness = client.check_talkback_ready()
    talkback_status = str(readiness.get("status") or "")
    talkback_reason = str(readiness.get("reason") or "")
    steps.append({"step": "readiness_probe", "ok": talkback_status == "enabled", "status": talkback_status, "reason": talkback_reason})

    if talkback_status == "enabled":
        return {
            "ok": True,
            "status": "fixed",
            "talkback_status": "ready",
            "talkback_reason": talkback_reason or "ok",
            "message": "TalkBack is ready.",
            "talkback_enable": enable_result,
            "readiness": readiness,
            "steps": steps,
        }

    if talkback_reason == "external_popup_contamination":
        return {
            "ok": False,
            "status": "popup_contamination",
            "talkback_status": talkback_status,
            "talkback_reason": talkback_reason,
            "message": "External popup is blocking TalkBack focus. Close the popup and retry.",
            "talkback_enable": enable_result,
            "readiness": readiness,
            "steps": steps,
        }

    if open_settings_fn is None:
        open_settings_fn = open_accessibility_settings
    settings_result = open_settings_fn()
    return {
        "ok": False,
        "status": "still_not_ready",
        "talkback_status": talkback_status,
        "talkback_reason": talkback_reason,
        "settings_opened": bool(settings_result.get("accessibility_settings_opened") or settings_result.get("ok")),
        "message": "TalkBack service is configured but readiness probe failed. Toggle TalkBack manually and retry.",
        "talkback_enable": enable_result,
        "readiness": readiness,
        "accessibility_settings_result": settings_result,
        "steps": steps,
    }


def open_accessibility_settings() -> dict[str, object]:
    result = run_adb(["shell", "am", "start", "-a", "android.settings.ACCESSIBILITY_SETTINGS"], timeout=8.0)
    return {
        **result,
        **_helper_metadata(_find_helper_apk()),
        "accessibility_settings_opened": bool(result.get("ok")),
    }


def _make_adb_runner_for_serial(serial: str):
    def runner(args: list[str], timeout: float = 10.0) -> dict[str, object]:
        return run_adb(["-s", serial] + args, timeout)
    return runner


def get_devices() -> list[dict[str, object]]:
    status = get_adb_status()
    devices = status.get("devices", [])
    if not isinstance(devices, list):
        return []

    from .preflight import get_talkback_status, get_foreground_package

    result = []
    for device in devices:
        serial = device.get("serial")
        state = device.get("state")
        if not isinstance(serial, str) or not serial:
            continue

        if state != "device":
            result.append({
                "serial": serial,
                "model": "Unknown",
                "state": state,
                "helper_ready": False,
                "talkback_enabled": False,
                "foreground_package": None,
            })
            continue

        runner = _make_adb_runner_for_serial(serial)

        prop_res = runner(["shell", "getprop", "ro.product.model"], 5.0)
        model = str(prop_res.get("stdout", "")).strip() if prop_res.get("ok") else "Unknown"

        try:
            tb_status = get_talkback_status(runner)
            talkback_enabled = tb_status.get("status") == "enabled"
        except Exception:
            talkback_enabled = False

        try:
            pm_res = runner(["shell", "pm", "list", "packages", HELPER_PACKAGE_NAME], 5.0)
            helper_ready = HELPER_PACKAGE_NAME in str(pm_res.get("stdout", "")) if pm_res.get("ok") else False
        except Exception:
            helper_ready = False

        try:
            fg_status = get_foreground_package(runner)
            fg_package = fg_status.get("package")
        except Exception:
            fg_package = None

        result.append({
            "serial": serial,
            "model": model,
            "state": state,
            "helper_ready": helper_ready,
            "talkback_enabled": talkback_enabled,
            "foreground_package": fg_package,
        })

    return result
