---
slug: environment-bootstrap-comparator
status: awaiting-approval
intent: clear
review_required: false
pending-action: write .omo/plans/environment-bootstrap-comparator.md
approach: Add a read-only environment bootstrap policy layer between aggregate comparison and existing verdict finalization.
---

# Draft: environment-bootstrap-comparator

## Components (topology ledger)
| id | outcome (one line) | status | evidence path |
|---|---|---|---|
| environment-group | Deterministic, model-independent group key and matching for approved Comparator inputs. | active | tb_runner/environment_fingerprint.py:150-190 |
| bootstrap-policy | Detect absence of an approved same-group baseline and convert only aggregate regressions to review in bootstrap mode. | active | tb_runner/comparison_replay.py:33-80; tb_runner/verdict_engine.py:56-145 |
| backend-integration | Supply all approved baseline inputs to the policy layer without mutating the baseline repository. | active | qa_frontend/backend/comparator_ui.py:95-136, 238-280 |
| result-contract | Additive mode/group/review metadata to deterministic JSON and Markdown report output. | active | tb_runner/comparison_report.py:20-150 |
| verification-docs | Lock normal/bootstrap behavior in tests and document manual bootstrap acceptance. | active | tests/test_comparator_finalization.py; docs/design/talkback-phase10.3d-comparator-finalization.md |

## Open assumptions (announced defaults)
| assumption | adopted default | rationale | reversible? |
|---|---|---|---|
| Group scope | target app package and locale plus form factor, Android major, One UI major, TalkBack package, and TalkBack major. | Locale/app identity remain existing comparison boundaries; version remains outside the group so normal predecessor comparison across app upgrades is retained. | yes |
| Device identity | Exclude device model and device family. | Meets model-independent requirement and groups platform-capable devices rather than handset names. | yes |
| Incomplete fields | Never bootstrap from an incomplete candidate fingerprint; preserve existing hard failure/review behavior. | A group cannot be safely computed from unknown environment values. | yes |
| Bootstrap reduction | Preserve raw aggregate values and add an effective `REVIEW_REQUIRED` policy view used by existing finalization. | Keeps Comparator Core and existing same-environment regression rules intact while making the applied mode explicit. | yes |

## Findings (cited - path:lines)

- `build_environment_fingerprint` already exposes canonical form factor, Android/One UI major, TalkBack package/major, and device family fields; no model parsing is needed: `tb_runner/environment_fingerprint.py:150-190`.
- `compare_selected_inputs` is read-only aggregate production and `comparison_replay._replay` is the finalization seam: `tb_runner/comparator_core.py:98-132`; `tb_runner/comparison_replay.py:33-64`.
- Existing `reduce_verdict` converts every REGRESSED accessibility aggregate to FAIL irrespective of compatibility: `tb_runner/verdict_engine.py:20-35, 96-120`.
- Backend already enumerates/loads every approved baseline through `BaselineRepository` and `adapt_approved_baseline`: `qa_frontend/backend/comparator_ui.py:95-136, 238-280`.
- Existing compatibility correctly emits review metadata for device/platform differences but has no bootstrap concept: `tb_runner/comparison_compatibility.py:226-300`.
- Current report/history is session-only; replay JSON/Markdown are canonical deterministic artifacts: `qa_frontend/backend/comparator_ui.py:273-297`; `tb_runner/comparison_replay.py:33-64`.

## Decisions (with rationale)

- Introduce a new policy module, not model branches or Candidate/Baseline schema fields.
- Calculate Group from canonical ComparatorInput environment values and expose its source/digest/status additively in the comparison result.
- Bootstrap means no approved baseline in the supplied approved-baseline set shares the candidate group; the selected Flip6 baseline remains a reference input, not a same-group predecessor.
- In Bootstrap mode, retain original aggregate deltas but present their effective policy status as review for Coverage, Identity, Recovery, Traversal, and Environment. New node accessibility failures, incomplete terminal/reconciliation/artifact/fingerprint conditions keep their existing behavior.
- Do not alter automatic approval. Bootstrap results remain human-review-only and documentation supplies the acceptance checklist.

## Scope IN

- Read-only Environment Group calculation and deterministic bootstrap decision.
- Replay/finalization orchestration and Backend approved-baseline input enumeration.
- Additive report/API fields, tests, and requested design/runbook documentation.

## Scope OUT (Must NOT have)

- No Fold8/Flip6/model/candidate-ID special cases.
- No Device Traversal, Candidate Builder/schema, Baseline Repository mutation, Observation Comparator, Comparator Core, Verdict Engine regression-rule, Comparator UI, or approval workflow modification.
- No automatic approval, candidate/baseline approval, ADB/device run, or commit/push.

## Open questions

- None. The user-specified environment-based model and the announced defaults resolve the implementation boundary.

## Approval gate
status: awaiting-approval
next workflow action: create the decision-complete `.omo/plans/environment-bootstrap-comparator.md` plan; implementation remains a separate explicit start action.
