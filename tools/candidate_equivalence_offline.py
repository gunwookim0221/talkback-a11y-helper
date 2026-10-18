from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from talkback_lib.candidate_equivalence import run_candidate_equivalence


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline legacy/v2 candidate equivalence.")
    parser.add_argument(
        "--inputs",
        type=Path,
        default=ROOT / "app/src/test/resources/candidate_equivalence/inputs.json",
    )
    parser.add_argument(
        "--pairs",
        type=Path,
        nargs="*",
        default=sorted((ROOT / "app/src/test/resources/candidate_equivalence").glob("pairs_api*.json")),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "app/build/reports/candidate-equivalence/results.json",
    )
    args = parser.parse_args()
    result = run_candidate_equivalence(args.inputs, args.pairs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: result[key] for key in (
        "paired_fixture_count",
        "exact_equivalent_count",
        "semantic_equivalent_count",
        "known_intentional_difference_count",
        "incompatible_count",
        "noncomparable_count",
        "traversal_impacting_difference_count",
        "home_monitor_equivalence_pass",
        "root_binding_all_pass",
        "schema_versions_all_pass",
        "passed",
    )}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print(f"RESULT_FILE={args.output}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
