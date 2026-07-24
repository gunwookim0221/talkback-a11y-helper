import argparse
from pathlib import Path

from .workbook import generate_review_checklist, generate_review_summary


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.review_checklist")
    subparsers = parser.add_subparsers(dest="command", required=True)
    detail = subparsers.add_parser("generate", help="Generate one Run detail checklist")
    detail.add_argument("source", type=Path)
    detail.add_argument("--output", type=Path)
    detail.add_argument("--pass-sample-rate", type=float, default=0.0)
    detail.add_argument("--force-regenerate", action="store_true")
    combined = subparsers.add_parser("summary", help="Combine detail Summary sheets")
    combined.add_argument("details", nargs="+", type=Path)
    combined.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "generate":
        print(generate_review_checklist(args.source, output=args.output, pass_sample_rate=args.pass_sample_rate, force_regenerate=args.force_regenerate))
    else:
        print(generate_review_summary(args.details, output=args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
