from __future__ import annotations

import glob
import subprocess
from pathlib import Path

from talkback_lib.constants import DEFAULT_ADB_PATH
from tb_runner.accessibility_preflight import HELPER_SERVICE_COMPONENT

from .paths import ROOT_DIR


HELPER_PACKAGE_NAME = "com.iotpart.sqe.talkbackhelper"
HELPER_SERVICE_SHORT_COMPONENT = "com.iotpart.sqe.talkbackhelper/.A11yHelperService"


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
    package_result = run_adb(["shell", "pm", "list", "packages"], timeout=8.0)
    if not package_result.get("ok"):
        return {
            **package_result,
            "status": "adb_error",
            "component": HELPER_SERVICE_COMPONENT,
            "package": HELPER_PACKAGE_NAME,
            "package_installed": False,
            "enabled": False,
            "enabled_accessibility_services": "",
        }

    services_result = run_adb(["shell", "settings", "get", "secure", "enabled_accessibility_services"], timeout=8.0)
    if not services_result.get("ok"):
        return {
            **services_result,
            "status": "adb_error",
            "component": HELPER_SERVICE_COMPONENT,
            "package": HELPER_PACKAGE_NAME,
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
        status = "installed_but_disabled"
    else:
        status = "not_installed"
    return {
        **services_result,
        "status": status,
        "component": HELPER_SERVICE_COMPONENT,
        "package": HELPER_PACKAGE_NAME,
        "package_installed": package_installed,
        "enabled": enabled,
        "enabled_accessibility_services": enabled_services,
    }


def _split_enabled_accessibility_services(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"null", "none"}:
        return []
    return [item.strip().lower() for item in raw.split(":") if item.strip()]


def _has_enabled_helper_service(enabled_services: str | None) -> bool:
    services = set(_split_enabled_accessibility_services(enabled_services))
    return (
        HELPER_SERVICE_COMPONENT.lower() in services
        or HELPER_SERVICE_SHORT_COMPONENT.lower() in services
    )


def _find_helper_apk() -> Path | None:
    patterns = [
        "app/build/outputs/apk/**/*.apk",
        "android/app/build/outputs/apk/**/*.apk",
    ]
    candidates: list[Path] = []
    for pattern in patterns:
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
            "status": "error",
            "error": "helper APK not found",
            "searched": [
                "app/build/outputs/apk/**/*.apk",
                "android/app/build/outputs/apk/**/*.apk",
            ],
        }
    result = run_adb(["install", "-r", str(apk_path)], timeout=120.0)
    return {**result, "apk": str(apk_path)}
