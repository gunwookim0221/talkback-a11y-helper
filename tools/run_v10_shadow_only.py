from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from qa_frontend.backend.shadow_only import run_shadow_only


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-run the V10 shadow pipeline for an existing device run.",
    )
    parser.add_argument("--run-dir", required=True, help="Existing device run directory")
    parser.add_argument(
        "--overwrite-shadow",
        action="store_true",
        help="Replace known artifacts in the selected shadow output directory",
    )
    parser.add_argument(
        "--output-suffix",
        help="Write to shadow_<suffix> instead of shadow",
    )
    parser.add_argument("--device-id", help="ADB device serial override")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate run metadata without connecting to a device",
    )
    parser.add_argument(
        "--update-corpus",
        action="store_true",
        help="Append completed shadow results to the V10 corpus (default: off)",
    )
    parser.add_argument(
        "--corpus-dir",
        default="artifacts/v10/corpus",
        help="Corpus root used with --update-corpus",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_shadow_only(
            args.run_dir,
            overwrite_shadow=args.overwrite_shadow,
            output_suffix=args.output_suffix,
            device_id=args.device_id,
            dry_run=args.dry_run,
            update_corpus=args.update_corpus,
            corpus_dir=args.corpus_dir,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"validated", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
