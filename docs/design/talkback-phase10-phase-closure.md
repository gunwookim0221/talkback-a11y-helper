# TalkBack Accessibility Helper — Phase 10 Closure

Status: **Accepted for controlled/manual production operation with limitations**  
Validation date: 2026-07-17  
Device policy: no physical-device Full Validation was run during this acceptance.

## 1. Goals

Phase 10 established immutable Baseline management, environment capture, approved Baseline
repository, deterministic Comparator/reports/replay, portable observation bundles, and a QA
Frontend Compare workflow. Approval remains an explicit human action.

## 2. Architecture

The operating path is:

```text
Full Validation → Candidate → Offline Validation → Comparator → JSON/Markdown Report
  → Human Approval → Baseline registration → next-version comparison
```

Baseline packages and lifecycle/catalog state are immutable. The Comparator is read-only and
selects a compatible predecessor, compares aggregate and observation dimensions, reduces a
versioned verdict, and emits deterministic canonical JSON and Markdown. Tracked portable bundles
are the portability authority; CAS is an optional digest/cache layer. The QA Frontend calls this
engine through read-only catalogue, compare, result, report, download, and history APIs.

## 3. Completed implementation

- Baseline Manager, environment capture, repository catalog/lifecycle/checksum verification.
- English and Korean Approved Baselines.
- Comparator architecture, core aggregate comparison, observation comparison, final verdict reducer.
- PASS, PASS_WITH_LIMITATIONS, REVIEW_REQUIRED, FAIL, and INCOMPARABLE policy.
- Canonical JSON/Markdown reports and deterministic replay identity.
- English/Korean portable observation bundles and verified bundle index.
- QA Frontend Candidate/Baseline selectors, Compare action, verdict badge, result dimensions,
  review accordions, Markdown viewer, downloads, history, progress and error handling.
- No automatic approval, Candidate mutation, Baseline mutation, repository mutation, or device
  execution was introduced.

## 4. Acceptance checklist

| Area | Result | Evidence |
|---|---|---|
| Full Validation contract | PASS (offline acceptance; no device run) | Existing Full Validation/Candidate contracts and no-device policy |
| Candidate | PASS | Candidate adapter and synthetic candidate fixtures |
| Offline Validation | PASS | Replay and portable-bundle tests |
| Baseline Repository | PASS | `BaselineRepository.verify()` returned valid with no errors |
| Approved Baseline | PASS | English and Korean package/catalog/lifecycle checks |
| Comparator | PASS | 111 comparator/repository/bundle acceptance tests |
| Compare UI | PASS | 191 QA Frontend regression tests, API/UI tests, production build |
| Report | PASS | Required Markdown sections, canonical JSON, download routes |
| Replay | PASS | Same ID, verdict, JSON bytes, and Markdown bytes |
| Human Approval Workflow | PASS | Approval remains explicit and automatic approval is false |

Comparator cases all passed: English self compare, Korean self compare, synthetic upgrade,
synthetic structural/UI addition, known limitation unchanged/resolved, new `EMPTY_VISIBLE`,
`DATA_UNAVAILABLE`, and `INCOMPARABLE`.

Repository acceptance passed for catalog, lifecycle, Approved Baselines, Candidate adaptation,
portable bundle index/document digests, CAS/digest references, and replay. Frontend acceptance
passed for selection, Compare, report viewing/download, history, errors, progress, and disabled
actions.

Additional checks:

- `python -m pytest` comparator/repository/frontend acceptance set: **111 passed**.
- QA Frontend regression set: **191 passed**.
- `npm run build -- --outDir build-acceptance`: **passed**.
- `python -m compileall -q tb_runner qa_frontend/backend`: **passed**.
- `git diff --check`: **passed**.

## 5. Production readiness

| Area | Rating | Rationale |
|---|---|---|
| Architecture | READY | Contracts and read-only boundaries are versioned |
| Repository | READY | Catalog, lifecycle, checksum, and immutable verification are covered |
| Baseline | READY WITH LIMITATIONS | Approved packages are stable; future bundle migration remains explicit |
| Comparator | READY WITH LIMITATIONS | Deterministic controlled/manual operation; no unattended approval |
| Frontend | READY WITH LIMITATIONS | Complete Compare workflow; history is session-only |
| Replay | READY | Deterministic ID, JSON, Markdown, and verdict |
| Operation | READY WITH LIMITATIONS | Human-controlled workflow, not one-command orchestration |
| Maintainability | READY | Additive modules, tests, documented contracts |
| Extensibility | READY WITH LIMITATIONS | Multi-device, remote artifacts, and policy registries remain future work |

Overall: **Production Ready for controlled/manual comparator operation**, not unattended service
production readiness.

## 6. Operating limitations

- Future Candidate observations are not automatically bundled at Candidate creation time.
- QA Frontend comparison history and reports are process-session memory; restart requires replay.
- Future Baselines require an explicit additive portable-bundle migration after approval.
- Candidate/source artifacts are required unless a portable Candidate observation bundle exists.
- One Connect release-train and cross-device compatibility policies remain project policy.
- Bundle payloads contain raw accessibility observations and need retention/redaction ownership.

## 7. Technical debt

- Candidate bundle generation and validation should be part of Offline Validation.
- Report/history persistence and remote content-addressed distribution are absent.
- Matching thresholds, performance thresholds, and scenario rename aliases need calibration.
- Multi-device Baseline identity and cohort policy are not yet modeled.
- Frontend lacks a richer diff visualization and server-side comparison indexing.

## 8. Phase 11 recommendations

1. Candidate portable-bundle generation and CI/offline automatic compare (highest priority).
2. Durable report/history index with remote CAS distribution and retention/redaction policy.
3. HTML side-by-side diff viewer for node/text/speech and review evidence.
4. Multi-device Baseline and compatibility-family registry.
5. Dashboard and trend analysis across versions, locales, and verdict dimensions.

## 9. Lessons learned

Immutable source contracts and explicit availability states prevent missing artifacts from being
mistaken for accessibility regressions. Separating aggregate, observation, limitation, and
compatibility verdict axes makes manual review auditable. Deterministic IDs must exclude wall-clock
and local paths. Portability requires a canonical tracked artifact, not only a local CAS/cache.

## 10. Closure decision

Phase 10 is formally closable for the defined controlled/manual scope. The acceptance evidence
supports the workflow from Full Validation through Candidate, Offline Validation, Comparator,
report, human approval, and Baseline registration. Phase 11 should address the limitations above;
none is a reason to reopen Phase 10 scope.

