# TalkBack Accessibility Helper — Korean Locale / Baseline Phase Closure

## Status

| Item | Result |
|---|---|
| Phase status | **CLOSED** |
| Overall result | **PASS WITH LIMITATIONS** |
| Korean locale adapter | Production accepted |
| Korean canonical Full | Accepted |
| Korean Candidate | Accepted with limitations |
| Korean Baseline | Approved and published |
| Closure scope | Samsung One UI locale provisioning and Korean Baseline registration |

This document is the handoff record for the completed Korean locale and Baseline cycle. It
records the final evidence and decisions; it does not reopen the phase or change production,
Candidate, QA Review, or Baseline state.

## Scope

The phase covered:

- provisioning `en-US` and `ko-KR` through the Samsung One UI system-language flow;
- authoritative effective-locale verification after the change;
- one clean Korean canonical 32-scenario Full Validation;
- Candidate validation and human disposition of the six non-PASS findings;
- creation, verification, and publication of the Korean Approved Baseline.

It did not change TalkBack state, replace the production traversal policy, run a new Full after
Baseline approval, or promote any additional Candidate.

## Problem Statement

Korean Full Validation requires an explicit system-locale transition on Samsung One UI. The
effective locale cannot be safely inferred from `system_locales` alone: the primary locale,
active UI, and the application-visible language can temporarily disagree. Likewise, a
successful Helper action is only an action result, not proof that the effective locale changed.

Korean therefore has a distinct BaselineKey slot. It must be accepted from a clean, canonical
Korean Full and must retain its locale and environment identity instead of being treated as the
English Baseline.

## Final Architecture

The locale path is implemented as Python orchestration in `device_locale.py` with a Helper
AccessibilityService fallback for Samsung Settings. Its final contract is:

- supported locales are `en-US` and `ko-KR`;
- selectors are fail-closed and target a unique actionable locale row;
- no coordinate-based interaction is used;
- the locale row activation budget is at most one;
- the Apply activation budget is at most one;
- total mutating UI actions are bounded to two;
- row, Apply, and command retries are not automatic;
- a fresh accessibility root is required after locale-row activation;
- `locale_list_view` and `apply_btn_layout` are diagnostic structure, not mandatory production
  readiness gates;
- Apply selection does not depend on English text;
- effective locale verification is authoritative;
- `system_locales` alone and `ACTION_PERFORMED` alone cannot produce locale success;
- TalkBack/accessibility state is not mutated by the adapter.

This keeps locale provisioning isolated from traversal, semantic coverage, and crash policy.

## Real-Device Acceptance

Device `R3CX40QFDBP` (`SM-F741N`) completed both production paths:

| Transition | Result |
|---|---|
| `en-US -> ko-KR` | PASS |
| `ko-KR -> en-US` | PASS |

`BIDIRECTIONAL_LOCALE_E2E_ACCEPTED=YES` and
`LOCALE_ADAPTER_REAL_DEVICE_ACCEPTANCE_COMPLETE=YES`. No further locale acceptance is pending
for this phase.

## Clean Korean Full Acceptance

Authoritative run: `batch_20260831_084021`
Source commit: `647d451fbc85cd80996ba052a693d810ff079ec7`
Run kind: `FULL`
Selected scenarios: `32`

| Dimension | Result |
|---|---:|
| Observed / terminal / completed | `32 / 32 / 32` |
| Unavailable / failed / entry failures | `0 / 0 / 0` |
| Scenario result | `9 passed / 23 warnings / 0 failed` |
| Device/plugin entry | `12/12` correct |
| Wrong sibling / false plugin success / anchor abort | `0 / 0 / 0` |
| Helper/comparator exceptions | `0` |
| DUMP_TREE failures / Helper not-ready / crashes | `0 / 0 / 0` |
| Traversed steps | `682` |
| Raw / eligible probe candidates | `11 / 11` |
| Successful / matched promotable probes | `7 / 0` |
| Focusable coverage | `320/589` (`54.3%`) |
| Semantic coverage | `96/97` (`99.0%`) |
| Required misses / unexplained misses | `4 / 0` |
| Review unknowns | `19` |
| Reconciliation | `PASS` |
| Full acceptance | `PASS_WITH_LIMITATIONS` |

The nine `repeat_no_progress` and eight `FAIL_STUCK` results were bounded scenario diagnostics,
not infrastructure stalls. There was no E4, E6, E7, or E8 regression.

The approved E7 policy remains HYBRID: the semantic target is the primary coverage unit, the
runtime node is the evidence unit, and exact traversal order is diagnostic rather than a normal
coverage gate. E7 current-value association remains `UNVERIFIED /
KNOWN_EVIDENCE_LIMITATION`; it is accepted evidence scope, not a resolved defect or open phase
blocker.

For E8, `0 걸음 / 6000 걸음 0 %` was observed as visible and spoken during traversal. A separate
probe could not correlate the target from a bottom-tab focus state. The result is a known
evidence-linkage limitation:

`E8_REQUIRED_MISS_REVIEW=PASS`

## Candidate Review

| Item | Value |
|---|---|
| Candidate | `candidate_92e644771635772b6671ac9f` |
| Candidate digest | `4a6cacb7e03c10dfaea0fa7cba46183b4fa5fece0cb49a654a23aa4d256c5d94` |
| Source batch | `batch_20260831_084021` |
| Source commit | `647d451fbc85cd80996ba052a693d810ff079ec7` |
| Validator | `phase10.1b-validator-v2` |
| Eligibility / provenance | `YES / clean` |
| Validation counts | `24 PASS / 1 WARNING / 0 FAIL` |
| Human disposition | `ACCEPT_WITH_LIMITATIONS` |

The six non-PASS findings were reviewed against exact scenario, step, resource, and transaction
evidence. Three are QA known limitations and three are bounded automation diagnostics:

| Findings | Disposition | Interpretation |
|---|---|---|
| Audio step 20 `EMPTY_VISIBLE` | Accepted known limitation | Real `SeekBar` target moved successfully and passed production identity verification; the compound observation has no independent label. |
| Motion `lowBattery` step 2 `EMPTY_VISIBLE` | Accepted known limitation | The node exists and passes move/gate/VISIT; the dynamic value is empty for the current state. |
| Water Leak `lowBattery` step 2 `EMPTY_VISIBLE` | Accepted known limitation | Same bounded dynamic empty-state behavior as Motion. |
| Clothing `DASC_0127-25` `terminal_not_handled` | Expected policy warning | Correct Clothing Care context and blank disabled terminal node; no wrong-plugin navigation or false success. |
| Clothing `DASC_0127-25` `move_failed` | Expected policy warning | Non-scrollable blank node; bounded `reached_end=false` and conservative indeterminate gate. |
| Clothing `DASC_0127-25` `repeat_no_progress` | Expected policy warning | Same fingerprint repeated; bounded stop prevented an automation stall. |

All six are represented exactly once in the review inputs. No functional, provenance, navigation,
automation, or evidence blocker remained.

## Approved Known Limitations

The following are intentionally retained as limitations, not described as fixed defects:

- Audio `EMPTY_VISIBLE` compound accessibility observation;
- Motion Sensor and Water Leak Sensor dynamic `lowBattery` empty-state observation;
- Clothing Care bounded terminal/move/repeat diagnostics on `DASC_0127-25`;
- E7 current-value association evidence limitation;
- E8 probe-correlation evidence limitation.

Raw failure evidence remains preserved. Acceptance means these findings are explicitly bounded
and reviewed for this Baseline; it does not remove or rewrite their source observations.

## Korean Baseline

| Item | Value |
|---|---|
| Baseline ID | `baseline_26445adc51b362ab_r0001` |
| Revision | `1` |
| State | `APPROVED` |
| Acceptance | `PASS WITH LIMITATIONS` |
| Baseline key digest | `26445adc51b362abdeb586da3f8d6fbce1218ca25246b8f46e040ca8b68a2482` |
| Locale | `ko-KR` |
| Source Candidate | `candidate_92e644771635772b6671ac9f` |
| Source Candidate digest | `4a6cacb7e03c10dfaea0fa7cba46183b4fa5fece0cb49a654a23aa4d256c5d94` |
| Source batch | `batch_20260831_084021` |
| Source commit | `647d451fbc85cd80996ba052a693d810ff079ec7` |
| English Baseline collision | `NO` |
| Persisted known limitations / acknowledgements | `3 / 3` |
| Repository package / audit event count | `8 / 64` |
| Repository verification | `PASS` |

The Korean Baseline has its own locale-bearing BaselineKey and is not an exact match for the
English Baseline. The English Baseline and historical Korean Baselines remain unchanged.

## Closure Decision

This phase is formally closed.

- No further Korean Full is required for this phase.
- No further locale acceptance is required.
- No additional Candidate review is required for this Candidate.
- No Baseline promotion action remains.
- The published Baseline is the approved Korean reference for this environment/key.

## Deferred / Optional Follow-up

These are optional future improvements, not closure blockers:

- improve E7 current-value association evidence;
- improve E8 probe-to-traversal correlation;
- revisit `EMPTY_VISIBLE` evidence semantics with a broader semantic model;
- improve the bounded Clothing Care diagnostic representation.

Previously documented `A11yNavigatorTest.kt` unresolved test references and repository-wide Ruff
debt are unrelated technical debt and were not blockers for this closure.

## Preservation / Repository Notes

- Locale implementation commit: `647d451fbc85cd80996ba052a693d810ff079ec7`
  (`Add Samsung locale switching adapter`).
- Korean Baseline publication commit: `0d1a722141358e66fab88ead9014df415cd18d9f`
  (`Approve Korean TalkBack baseline`).
- The approved Baseline core, catalog, index, and lifecycle are version-controlled.
- Run outputs, Candidate source artifacts, raw evidence, and local CAS remain outside the
  version-controlled Baseline core according to the repository convention.
- `stash@{0}` (`pre-full preserved mixed WIP after E7`) remains intentionally preserved and was
  not applied, merged, resolved, or dropped.

The next repository action after this document is ordinary phase handoff, not another Full,
locale transition, Candidate generation, or Baseline approval.
