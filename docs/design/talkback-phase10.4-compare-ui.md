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

The Compare panel presents Candidate selection on the left and approved Baseline selection on the right. While a comparison or report load is in progress, inputs and actions are disabled and the action displays progress. The result includes environment, version, compatibility, coverage, identity, traversal, recovery, profiler, final verdict badge, recommendation, expandable limitation/failure/review groups, Markdown viewer, downloads, and recent history.

Verdict badges map PASS to green, PASS WITH LIMITATIONS to amber, REVIEW REQUIRED and INCOMPARABLE to neutral, and FAIL to red. `DATA_UNAVAILABLE` remains a result/diagnostic from the comparator when data can be compared partially; unreadable selected input is an API error.

## Known limitation

History is deliberately session-only to preserve the no-mutation boundary. Reports are not durable UI artifacts and cannot be reopened after a backend restart without replaying the selected immutable inputs. Approval remains completely manual.

## Acceptance

Backend tests cover unavailable repository/candidate states and result/Markdown/JSON routes without a device. The frontend build and regression suite verify the TypeScript integration. The implementation never starts a run or invokes ADB.
