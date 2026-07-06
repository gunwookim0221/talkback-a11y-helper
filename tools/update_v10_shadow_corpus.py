from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from qa_frontend.backend.v10_shadow_corpus import (
    ShadowCorpusError,
    update_shadow_corpus,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append V10 shadow results to the long-term summary corpus.",
    )
    parser.add_argument(
        "--run-dir",
        help="Device run directory containing shadow artifacts",
    )
    parser.add_argument(
        "--corpus-dir",
        default="artifacts/v10/corpus",
        help="Corpus root (default: artifacts/v10/corpus)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild index and summaries from existing corpus entries",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and calculate output without writing files",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.run_dir and not args.rebuild:
        print(
            json.dumps(
                {"status": "error", "error": "run_dir_required_without_rebuild"}
            )
        )
        return 2
    try:
        result = update_shadow_corpus(
            corpus_dir=args.corpus_dir,
            run_dir=args.run_dir,
            rebuild=args.rebuild,
            dry_run=args.dry_run,
        )
    except (OSError, ShadowCorpusError) as exc:
        print(
            json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2

    output = {
        "status": result["status"],
        "operation": result["operation"],
        "corpus_dir": result["corpus_dir"],
        "corpus_entry_id": (
            result["entry"]["corpus_entry_id"] if result["entry"] else None
        ),
        "entry_count": result["index"]["entry_count"],
        "family_count": result["family_summary"]["family_count"],
        "v11_pilot_candidate_families": result["readiness_summary"][
            "v11_pilot_candidate_families"
        ],
        "files_written": result["files_written"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
