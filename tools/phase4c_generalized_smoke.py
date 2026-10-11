"""Explicit Phase 4C opt-in. Production entry and reconciliation remain intact."""
from tools.phase4b_controlled_smoke import main

if __name__ == "__main__":
    raise SystemExit(main(generalized=True))
