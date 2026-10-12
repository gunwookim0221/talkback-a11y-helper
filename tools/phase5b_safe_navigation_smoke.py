"""Explicit Phase 5B runner; no production flag changes."""
from tools.phase4b_controlled_smoke import main

if __name__ == "__main__":
    raise SystemExit(main(generalized=True, safe_navigation=True))
