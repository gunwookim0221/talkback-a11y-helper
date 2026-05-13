#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from talkback_lib import A11yAdbClient
from talkback_lib.constants import DEFAULT_ADB_PATH
from tb_runner.accessibility_preflight import (
    HELPER_SERVICE_COMPONENT,
    ensure_accessibility_service_enabled,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure TalkBack helper AccessibilityService is enabled.")
    parser.add_argument("--serial", default="", help="Optional adb serial.")
    parser.add_argument("--adb", default=DEFAULT_ADB_PATH, help="ADB executable path.")
    parser.add_argument("--skip-helper-ready", action="store_true", help="Only update settings; skip helper PING.")
    args = parser.parse_args()

    serial = args.serial or None
    client = A11yAdbClient(adb_path=args.adb, dev_serial=serial) if not args.skip_helper_ready else None

    result = ensure_accessibility_service_enabled(
        serial=serial,
        adb_path=args.adb,
        component=HELPER_SERVICE_COMPONENT,
        helper_ready_check=(lambda: bool(client and client.ping(dev=serial, wait_=3.0)))
        if not args.skip_helper_ready
        else None,
        log_fn=print,
    )
    print(f"helper_service_component={HELPER_SERVICE_COMPONENT}")
    print(f"before.enabled_accessibility_services={result.before.enabled_accessibility_services}")
    print(f"before.accessibility_enabled={result.before.accessibility_enabled}")
    print(f"after.enabled_accessibility_services={result.after.enabled_accessibility_services}")
    print(f"after.accessibility_enabled={result.after.accessibility_enabled}")
    print(f"enable_attempted={str(result.enable_attempted).lower()}")
    print(f"helper_ready={str(result.helper_ready).lower()}")
    print(f"result={result.reason}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
