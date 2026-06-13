"""CLI entrypoint for the Audit V5 offline traversal parser."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_v5_traversal_core import build_report
from tools.audit_v5_traversal_report import render_markdown, write_report

__all__ = ["build_report", "render_markdown", "write_report", "main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Audit V5 traversal-engine report from existing artifacts.")
    parser.add_argument("--artifact-dir", type=Path, required=True, help="Scenario or run output directory to parse.")
    parser.add_argument("--output-dir", type=Path, default=Path("output"), help="Directory for traversal_audit.json/md.")
    args = parser.parse_args(argv)

    report = build_report(args.artifact_dir)
    json_path, markdown_path = write_report(report, args.output_dir)
    print(
        "[AUDIT_V5] wrote "
        f"json={json_path} markdown={markdown_path} "
        f"discovered={report['metrics']['discovered_count']} "
        f"visited={report['metrics']['visited_count']} "
        f"missed={report['metrics']['missed_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
