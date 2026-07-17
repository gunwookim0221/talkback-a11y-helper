# Phase 10.4 Comparator QA UI

## Architecture

The QA Frontend is a read-only adapter over the completed Phase 10.3 comparator. It discovers approved packages from `baselines/` and candidate artifacts from `qa_frontend_runs/`, adapts the selected pair, and calls `replay_selected_inputs`. It neither writes reports nor changes Baselines, Candidates, repository lifecycle state, or approval state.

Reports and recent-comparison history live only in the backend process memory (maximum 25 entries). A server restart clears that UI history; the canonical Phase 10.3 report remains reproducible by selecting the same immutable inputs again.

## API

- `GET /api/comparator/baselines` — approved Baseline catalogue.
- `GET /api/comparator/candidates` — readable Candidate catalogue.
- `POST /api/comparator/compare` — accepts `baseline_id` and `candidate_id`, returns the finalized comparison.
- `GET /api/comparator/history` — recent in-session comparisons.
- `GET /api/comparator/results/{comparison_id}` — finalized canonical result.
- `GET /api/comparator/results/{comparison_id}/markdown` — Markdown viewer content.
- `GET /api/comparator/results/{comparison_id}/report.json` and `/report.md` — download responses.

Errors use stable codes: `BASELINE_REPOSITORY_UNAVAILABLE`, `NO_APPROVED_BASELINES`, `NO_CANDIDATES`, `BASELINE_NOT_FOUND`, `CANDIDATE_NOT_FOUND`, `DATA_UNAVAILABLE`, and `COMPARISON_UNAVAILABLE`.

## Frontend and workflow

The Compare panel presents an `Available run / candidate` selection on the left and an approved Baseline selection on the right. Candidate options are local run inputs, not an approval list. Existing artifact metadata supplies `APPROVED SOURCE`, `ELIGIBLE CANDIDATE`, `NOT ELIGIBLE`, `RUN ONLY`, or `UNKNOWN`, with blocker reasons such as `SMOKE`, `TARGETED`, `DIRTY`, and `MISSING ARTIFACT`. `APPROVED SOURCE` requires an exact candidate/source identity match to an approved Baseline's recorded source candidate/run/batch; locale/version alone is never sufficient. All statuses remain selectable and do not alter Comparator behavior.

The panel explains: “Runs are local comparison inputs. Approved baselines are managed separately.” A clean clone on another PC may have no local `qa_frontend_runs/` artifacts, so its Candidate list can be empty even when Approved Baselines are present.

While a comparison or report load is in progress, inputs and actions are disabled and the action displays progress. The result includes environment, version, compatibility, coverage, identity, traversal, recovery, profiler, final verdict badge, recommendation, expandable limitation/failure/review groups, Markdown viewer, downloads, and recent history.

Verdict badges map PASS to green, PASS WITH LIMITATIONS to amber, REVIEW REQUIRED and INCOMPARABLE to neutral, and FAIL to red. `DATA_UNAVAILABLE` remains a result/diagnostic from the comparator when data can be compared partially; unreadable selected input is an API error.

## Known limitation

History is deliberately session-only to preserve the no-mutation boundary. Reports are not durable UI artifacts and cannot be reopened after a backend restart without replaying the selected immutable inputs. Approval remains completely manual.

## Acceptance

Backend tests cover unavailable repository/candidate states and result/Markdown/JSON routes without a device. The frontend build and regression suite verify the TypeScript integration. The implementation never starts a run or invokes ADB.
### Comparator finalization notes

Approved Source self-compare is recognized only when the candidate ID, source
run/batch IDs, source candidate digest, app identity, comparison contract,
runtime hash, and clean source revision all match the approved baseline
provenance. The approved baseline packages currently do not contain
`normalized_runtime_config_hash`; this missing provenance-only field is ignored
only for that verified exact-source pair. Ordinary predecessor comparisons
still treat a missing-versus-present value as a change/review condition.

For `INCOMPARABLE`, `REVIEW_REQUIRED`, and `FAIL`, ComparePanel reuses
structured verdict, compatibility, review-item, and source-status data in
separate Blocking reasons, Review reasons, and Source warnings sections.
