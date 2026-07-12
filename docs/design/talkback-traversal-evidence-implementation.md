# TalkBack Traversal Evidence Instrumentation

상태: evidence-only shadow instrumentation
Schema: `evidence-event-v1`
Feature flag: `TB_EVIDENCE_LEDGER_ENABLED=1`
Identity shadow flag: `TB_EVIDENCE_IDENTITY_SHADOW_ENABLED=1` (requires ledger)

## Purpose

이 구현은 traversal 결과를 바꾸지 않는다. Runner와 Helper가 동일 action transaction의 관측 사실을 별도 JSONL ledger에 append하고, production row·Audit·Summary와 독립된 shadow reduction/reconciliation artifact를 만든다.

불변식:

- Step ≠ Transaction
- Ack ≠ Focus
- Representative ≠ Visit
- Consumed ≠ Visited
- XLSX ≠ Source of Truth
- Unknown is first-class

기본값은 **disabled**다. Flag가 없으면 ledger, manifest, reconciliation artifact를 만들지 않으며 기존 실행 경로를 사용한다.

## Artifacts

기존 `talkback_compare_<timestamp>.xlsx` output prefix 기준으로 다음 파일을 생성한다.

- `talkback_compare_<timestamp>.evidence.jsonl`: append-only structured events
- `talkback_compare_<timestamp>.evidence_manifest.json`: run provenance
- `talkback_compare_<timestamp>.evidence_reconciliation.json`: read-only summary consistency check

각 JSONL event는 deterministic JSON serialization을 사용하고 `event_id` idempotency를 보장한다. Write/flush failure는 `[EVIDENCE][warning]`만 남기며 traversal을 중단하지 않는다.

## Implemented event coverage

Runner:

- `SCENARIO_TRANSACTION_OPENED`, `STEP_CONTEXT_SET`
- `TRANSACTION_OPENED`, `PRE_FOCUS_OBSERVED`, `TARGET_REQUESTED`
- `ACTION_SENT`, `HELPER_ACK_RECEIVED`
- `POST_FOCUS_OBSERVED`, `ANNOUNCEMENT_OBSERVED`
- `FOCUS_STABILITY_WINDOW_CLOSED` (`immediate_only`, therefore normally `INDETERMINATE`)
- `REPRESENTATIVE_OBSERVED`, `REPRESENTATIVE_SELECTED`
- `REALIGN_STARTED`, `REALIGN_COMPLETED`
- `CANDIDATE_CONSUMED` with `PLANNING_ONLY` basis
- `VISIT_DECIDED` with `INDETERMINATE` visit kind
- `PERSIST_PROJECTED`, `SCENARIO_TERMINAL`, `TRANSACTION_CLOSED`

Helper structured log event (`EVIDENCE_HELPER`) when optional correlation metadata is supplied:

- `ACTION_EXECUTION_STARTED`
- `TARGET_RESOLVED`
- `ACTION_API_RESULT`
- `FOCUS_COMMIT_CLAIMED`
- `ACCESSIBILITY_FOCUS_EVENT`
- `ANNOUNCEMENT_OBSERVED`
- `HELPER_ACK_SENT`

Helper command extras are backward-compatible and optional:

- `evidenceRunId`
- `evidenceScenarioTxId`
- `evidenceTransactionId`
- `evidenceAttemptId`
- `evidenceLogicalActionId`

Existing `reqId`, `SMART_NAV_RESULT`, `TARGET_ACTION_RESULT`, and success/moved/failed meanings are unchanged.

For `SMART_NEXT`, the Helper also returns its currently buffered structured facts in the optional `evidenceEvents` response member. The Runner copies those facts to the JSONL ledger with its own receive timestamp. Older Helpers omit this member; older Runners ignore it.

When evidence is enabled, the Helper additionally retains the transaction's evidence facts until the Runner makes the optional `EVIDENCE_EVENTS` snapshot request after its normal focus and announcement collection. This is not a traversal command: it neither performs an accessibility action nor changes a result. It carries `POST_ACTION_OBSERVATION` plus `DELAYED_OBSERVATION` at 100/300/1000 ms, allowing snap-back evidence to be appended without changing the original `SMART_NAV_RESULT` timing or schema.

## Shadow reducer

The reducer produces only side-channel fields:

- transport
- action_api
- target_relation
- focus_commit_claim
- physical_focus_delta
- target_landing
- stability
- announcement
- evidence_completeness
- verdict: `MOVE_CONFIRMED`, `STATIC_FOCUS`, `MOVE_TO_OTHER_NODE`, `SNAP_BACK`, or `INDETERMINATE`

Legacy `SHADOW_ACTION_REDUCED`는 비교를 위해 유지한다. Identity flag가 켜진 run은 raw
observation을 `CanonicalObservation`으로 한 번 정규화한 뒤
`SHADOW_ACTION_REDUCED_V2`를 추가한다. V2는 immediate/100/300/1000 ms Helper observation을
사용하며, unstable 또는 unsupported delayed commit은 `INDETERMINATE`로 유지한다. 상세
판정 규칙은
[talkback-identity-shadow-phase8-completion.md](talkback-identity-shadow-phase8-completion.md)를
따른다.

## Provenance

The manifest records repository SHA/dirty state, runner hash, runtime config and scenario registry hashes, Helper APK/device/app/TalkBack/WebView metadata, locale/display, and schema version. Unavailable values are emitted as:

```json
{"status":"unavailable","value":null,"reason":"..."}
```

## Reconciliation

The shadow report checks that lifecycle facts do not regress, including card-found versus card-not-found, activation/transition stage regression, anchor abort retention, aborted-before-collection versus zero-valid, and no-eligible versus not-run. Phase 8 reconciliation also records non-blocking V2 transaction, verdict, confidence, and completeness metrics.

It never edits `summary.json` or changes a production verdict.

## Backward compatibility and production isolation

- No existing XLSX column is changed or repurposed.
- No candidate selection, traversal order, SMART_NEXT meaning, realign, stop, duplicate, visited, consumed, Audit, Summary, or Coverage behavior reads evidence output.
- Existing callers without evidence support continue because all hooks are duck-typed and failure-isolated.
- Existing Helper installations ignore unknown broadcast extras.

## Performance

Evidence disabled is near-zero cost: no runtime object is created and hooks return immediately.

Evidence enabled performs synchronous JSONL append/flush per event and writes elapsed time/event count to the reconciliation artifact. Delayed focus sampling is produced by best-effort Android Handler callbacks and transported by the read-only evidence snapshot path; it does not add Runner sleep or retry. Real-device collection must compare flag-off and flag-on runs using average step time, Helper response time, focus read time, ledger write time, event count, and file size.

## Real-device validation

```powershell
$env:TB_EVIDENCE_LEDGER_ENABLED='1'
python script_test.py --serial <SERIAL> --scenario home_safe_plugin --output-dir output\evidence_safe
```

Then verify the three evidence artifacts beside the XLSX and correlate a `SMART_NEXT` transaction by `transaction_id`, `attempt_id`, and Helper `EVIDENCE_HELPER` `correlation` fields.

For an off/on comparison, repeat with the flag removed and compare only production artifacts: rows, selected candidate, final result, stop reason, summary, coverage, and XLSX values must be unchanged. Evidence artifacts themselves are expected only with the flag on.

## Known limitations

- Runner currently ingests Helper facts returned with `SMART_NEXT`; facts emitted by other target-action commands remain in correlated Helper logs until a read-only collector is added.
- Delayed observations are best-effort Android Handler callbacks. A transaction remains `INDETERMINATE` if its snapshot is collected before the required callback, the Helper is restarted, or an older Helper does not support `EVIDENCE_EVENTS`.
- Node path, parent path, child index, window id, and display id are recorded when supplied by an observation source; current legacy focus payloads may leave them unavailable.
- Current Safe/Motion resolved nodes omit children and hierarchy paths, so container relation stays `INSUFFICIENT_EVIDENCE`; bounds-only hierarchy inference is forbidden.
- `VISIT_DECIDED` is fact-only and defaults to `INDETERMINATE`; it does not replace production visited semantics.
- Reconciliation is a shadow check; it does not rewrite historical `summary.json`.
