# Identity Shadow V2 Frontend Integration

Phase 7 adds a read-only QA view over the append-only evidence ledger. It exposes no raw Android node payload and never changes traversal, representative selection, visit/coverage/audit/summary production, or any production verdict.

`GET /api/runs/{run_id}/devices/{device_id}/identity-shadow` returns `identity-shadow-report-v1`. It joins relevant events by transaction ID and displays Legacy/V2 comparison, relation, stability, confidence, and evidence completeness. Availability is explicitly `NO_EVIDENCE_FILE`, `LEGACY_ONLY`, `V2_PARTIAL`, `V2_AVAILABLE`, or `MALFORMED_EVIDENCE`.

JSONL is cached by resolved path, size, and mtime nanoseconds. Changed files are reparsed; malformed lines and duplicate event IDs are ignored without breaking Run Details. The UI is labelled experimental/read-only and uses textual states rather than production PASS/FAIL styling.

Limitations: the report is a derived shadow view; missing or partial Helper evidence remains incomplete and cannot promote V2 into production. Phase 8 may only consider promotion after evidence quality and replay gates are independently accepted.
