#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

REPLACEMENTS = {
    "\u00A0": " ",   # non-breaking space -> regular space
    "\u200B": "",    # zero-width space remove
    "\uFEFF": "",    # UTF-8 BOM remove
}


def sanitize_text(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for bad, good in REPLACEMENTS.items():
        cnt = text.count(bad)
        if cnt:
            counts[bad] = cnt
            text = text.replace(bad, good)
    return text, counts


def iter_python_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.py")
        if not any(part in {".git", ".venv", "venv", "__pycache__"} for part in p.parts)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sanitize invisible unicode whitespace in Python files.")
    parser.add_argument("--dry-run", action="store_true", help="Only report files that would change.")
    parser.add_argument("--root", default=".", help="Root directory to scan (default: current directory)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    files = iter_python_files(root)

    total_replacements = {k: 0 for k in REPLACEMENTS}
    changed = []

    for path in files:
        text = path.read_text(encoding="utf-8")
        new_text, counts = sanitize_text(text)
        if not counts:
            continue

        rel_path = path.relative_to(root)
        changed.append((rel_path, counts))
        for k, v in counts.items():
            total_replacements[k] += v

        if not args.dry_run:
            path.write_text(new_text, encoding="utf-8")

    mode = "[DRY-RUN]" if args.dry_run else "[APPLY]"
    if not changed:
        print(f"{mode} No Python files required sanitization.")
        return 0

    print(f"{mode} Sanitized {len(changed)} file(s):")
    for rel_path, counts in changed:
        detail = ", ".join(f"U+{ord(ch):04X}={cnt}" for ch, cnt in counts.items())
        print(f" - {rel_path}: {detail}")

    summary = ", ".join(
        f"U+{ord(ch):04X}={cnt}" for ch, cnt in total_replacements.items() if cnt
    )
    print(f"{mode} Total replacements: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
