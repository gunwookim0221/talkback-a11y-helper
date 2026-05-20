from __future__ import annotations

from pathlib import Path

from .paths import OUTPUT_DIR

ALLOWED_OUTPUT_SUFFIXES = {".xlsx", ".json", ".log"}


def safe_output_path(filename: str) -> Path:
    if not filename or filename != Path(filename).name:
        raise ValueError("invalid output filename")

    path = (OUTPUT_DIR / filename).resolve()
    output_root = OUTPUT_DIR.resolve()
    if output_root != path.parent:
        raise ValueError("invalid output path")
    if path.suffix.lower() not in ALLOWED_OUTPUT_SUFFIXES:
        raise ValueError("unsupported output file type")
    if not path.is_file():
        raise FileNotFoundError(filename)
    return path


def list_outputs() -> list[dict[str, object]]:
    if not OUTPUT_DIR.exists():
        return []

    files: list[dict[str, object]] = []
    for path in OUTPUT_DIR.iterdir():
        if not path.is_file() or path.suffix.lower() not in ALLOWED_OUTPUT_SUFFIXES:
            continue
        stat = path.stat()
        files.append(
            {
                "filename": path.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
            }
        )
    return sorted(files, key=lambda item: float(item["modified"]), reverse=True)
