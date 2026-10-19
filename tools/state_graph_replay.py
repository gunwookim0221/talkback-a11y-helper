"""Deterministic offline replay for Phase 6B shadow graph fixtures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from tb_runner.state_graph import replay_state_graph, write_state_graph


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    recorder = replay_state_graph(manifest)
    target = write_state_graph(args.output, recorder, terminal=manifest.get("terminal"))
    print(json.dumps({"artifact": str(target), **recorder.to_dict().get("summary", {})},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
