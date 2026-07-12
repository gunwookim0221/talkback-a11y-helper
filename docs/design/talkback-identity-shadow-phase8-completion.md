# TalkBack Canonical Identity Shadow Phase 8 Completion

상태: Phase 8 acceptance complete; V10 Shadow Engine complete with known limitations
기준일: 2026-07-12
범위: Canonical Identity V2 reducer, evidence reporting, QA Frontend read-only projection
Production traversal semantics 변경: 없음

> 이 문서의 `Phase 8`은 TalkBack Canonical Identity Shadow 작업을 뜻한다. Device
> Inventory, Quick Identify, Policy Mapping, Controlled Routing을 다루는 별도의 V10
> 프로그램과 동일한 promotion gate가 아니다.

> 후속 Phase 8.5는 별도 default-OFF production migration이다. 이 문서의
> `production traversal unchanged` 판정은 Phase 8 shadow acceptance 경계에 대한 기록이며,
> opt-in Phase 8.5 규칙은
> [talkback-production-traversal-migration.md](talkback-production-traversal-migration.md)를
> 따른다.

## 1. Outcome

Identity reducer rule은 `target-relation-v2`로 갱신됐다. 변경은
`SHADOW_ACTION_REDUCED_V2`와 그 read-only projection에만 적용된다. Legacy reducer,
Helper success, SMART_NEXT, anchor, representative, visit/consumed, stop, coverage,
audit, production summary, XLSX와 production PASS/WARN/FAIL은 입력 또는 consumer로
사용하지 않는다.

Phase 8에서 확인된 직접 원인은 세 가지다.

1. Frozen Motion/Safe의 남은 `INDETERMINATE` 5건은 evidence 부족이 아니었다. 모두
   `reached_end + rejected action + complete stable unchanged focus`였으며, action API
   acceptance를 `STATIC_FOCUS`의 필수 조건으로 둔 reducer limitation이었다.
2. V2는 immediate landing이 unstable 또는 delayed commit이어도 최종 verdict를 낼 수
   있었다. 또한 immediate focus가 없을 때 resolved target을 snap-back의 중간 focus로
   사용할 수 있었다. 둘 다 target fact와 observed focus fact를 혼합한 temporal defect다.
3. QA Frontend reporter는 실제 nested identity diagnostics와
   `evidence_completeness=COMPLETE`를 읽지 못해 complete Safe transaction 20건을 모두
   incomplete로 표시했다.

## 2. Reducer V2 Rules

| Verdict | Phase 8 evidence gate |
|---|---|
| `SNAP_BACK` | observed immediate focus가 있는 A → B → delayed A strong relation |
| `STATIC_FOCUS` | complete transaction, stable landing, pre↔landing exact/strong, physical contradiction 없음, action accepted 또는 explicit `reached_end` |
| `MOVE_CONFIRMED` | complete transaction, accepted action, changed physical focus, stable landing, target-compatible relation |
| `MOVE_TO_OTHER_NODE` | complete transaction, accepted action, changed physical focus, stable landing, positive different-node relation |
| `INDETERMINATE` | partial evidence, unstable landing, unsupported delayed commit, ambiguous delta/target relation, 또는 unrelated rejection |

`reached_end` static은 `action_api=REJECTED`를 그대로 유지하고
`verdict_reason=REACHED_END_STABLE_UNCHANGED`로 구분한다. accepted-but-static은
`ACCEPTED_STABLE_UNCHANGED`다. 따라서 expected terminal no-op와 movement claim의
static focus를 같은 원인으로 집계할 필요가 없다.

Physical package/window contradiction은 label, bounds 또는 repeated resource-id 같은
semantic diagnostic보다 우선한다. Hierarchy relation은 node path, parent path 또는
explicit assertion만 사용하며 bounds containment heuristic은 사용하지 않는다.

## 3. Frozen Replay

Source ledger는 append-only이며 replay가 원본을 수정하지 않는다.

| Corpus | Transactions | Legacy | V2 before Phase 8 | V2 Phase 8 |
|---|---:|---|---|---|
| Motion | 16 | `MOVE_TO_OTHER_NODE 16` | `MOVE_CONFIRMED 11 / STATIC_FOCUS 3 / INDETERMINATE 2` | `MOVE_CONFIRMED 11 / STATIC_FOCUS 5 / INDETERMINATE 0` |
| Safe | 20 | `MOVE_TO_OTHER_NODE 20` | `MOVE_CONFIRMED 11 / STATIC_FOCUS 6 / INDETERMINATE 3` | `MOVE_CONFIRMED 11 / STATIC_FOCUS 9 / INDETERMINATE 0` |

Ledger provenance:

- Motion: `batch_20260711_212123`, SHA-256
  `44A7B8732F14EC5C54421FDD06D0C3845D82F788CC536E0D3284C4BF7F3763D1`
- Safe: `batch_20260711_212734`, SHA-256
  `CD6384007E6AC21F21B1E24041C2171718438CD2B830BD418132E153476ACC7F`

모든 36건은 `HIGH_CONFIDENCE`; target relation은
`STRONG_PHYSICAL_LINK`; stability는 `STABLE_LANDING`이다. Legacy 결과는 그대로
유지됐다. Frozen ledger는 현재 `qa_frontend_runs/`의 gitignored local artifact이므로
이 replay test는 artifact가 없는 환경에서 skip된다. CI 재현 가능한 sanitized fixture는
아직 없다.

## 4. STATIC_FOCUS and INDETERMINATE

Phase 8은 두 방향을 동시에 보수적으로 처리한다.

- False negative 감소: explicit `reached_end` 5건을 strong stable evidence에 근거해
  `STATIC_FOCUS`로 분류한다.
- False positive 방지: delayed sample 부재, unstable landing, unsupported delayed commit,
  physical contradiction이 있으면 static 또는 move verdict로 승격하지 않는다.
- `DELAYED_COMMIT`은 final target-compatible focus event의 attribution이 없으므로 여전히
  `INDETERMINATE`다.
- 임의의 rejected/unsupported action은 focus가 정지해도 `STATIC_FOCUS`로 승격하지
  않는다.

Frozen corpus의 `INDETERMINATE`는 0이 되었지만, 이는 unknown을 제거하는 일반 정책이
아니다. complete stable evidence가 있는 다섯 reducer-limited case만 재분류한 결과다.

## 5. Container Limitation

Frozen Motion/Safe 36건 모두 resolved observation에 `childrenOmitted=true`가 있고,
`node_path`, `parent_path`, accessibility node ID가 없다. 따라서 hierarchy는 36/36
`INSUFFICIENT_EVIDENCE`다. Bounds는 hierarchy evidence로 사용하지 않으며, 현재 corpus에
container-positive 판정을 추가하지 않았다.

## 6. Reporting and Reconciliation

QA Frontend의 Identity Shadow card는 기존 KPI와 transaction table을 유지하면서 다음
read-only distribution을 추가한다.

- five-verdict distribution: count and percent
- confidence distribution
- aggregate target relation distribution

Reporter는 새 flat diagnostics를 우선 읽고 Phase 6/7 nested diagnostics를 fallback으로
읽는다. Report schema와 endpoint는 유지되며 field만 additive다. 기존 Safe V2 ledger의
projection은 `incomplete 20 → 0`, `STRONG_PHYSICAL_LINK 100%`로 교정된다. Phase 6/7
event에는 final verdict confidence가 없으므로 historical confidence는 `UNAVAILABLE`이며,
nested target-relation confidence를 verdict confidence로 승격하지 않는다. Phase 8 이후
event는 top-level verdict confidence를 기록한다.

Evidence reconciliation에는 V2 transaction/verdict/confidence/completeness metrics가
추가된다. 이 metrics는 reconciliation PASS/FAIL이나 production 결과를 변경하지 않는다.

## 7. Production Isolation

다음 경계는 유지된다.

```text
Evidence OFF
  -> Identity reducer not called
  -> no evidence artifact
  -> legacy traversal/report path only

Evidence ON + Identity OFF
  -> ledger + legacy shadow only

Evidence ON + Identity ON
  -> legacy shadow + append-only V2 result
  -> read-only reporting/reconciliation
  -> no production consumer
```

Acceptance에서 Evidence OFF / Evidence ON / Identity ON parity와 per-run feature flag
flow를 다시 검증했다. 최종 상태는 다음과 같다.

- Reconciliation PASS
- `anchor_abort_preserved=true`
- Identity Shadow V2 frontend reporting available
- run-scoped feature flags preserved
- production traversal semantics unchanged
- Evidence OFF parity confirmed

## 8. Validation Record

| Gate | Result |
|---|---|
| Identity/evidence/reporting targeted pytest | PASS, 74 tests |
| QA Frontend regression pytest | PASS, 81 tests |
| Frozen Motion/Safe replay | PASS locally; fixture portability limitation |
| Frontend selection test | PASS, 6 tests |
| Frontend production build | PASS with isolated output directory; default `dist` was locked by another process |
| Full pytest | PASS for Phase 8 acceptance target suites; repository-wide unrelated failures remain outside this scope |
| Android `:app:assembleDebug` | PASS in accepted Phase 8 validation flow |
| XLSX / production parity | PASS at acceptance scope; production semantics unchanged |
| Current 32-scenario Evidence ON + Identity V2 acceptance | PASS |

현재 `config/runtime_config.json` 기준 corpus는 Safe 포함 32 scenario다. Acceptance에서는
Evidence ON + Identity V2 ON 상태에서 reconciliation, anchor abort preservation,
feature-flag provenance, frontend reporting, Evidence OFF parity를 확인했다. 이 문서는 그
최종 accepted 상태를 기록한다.

## 9. Remaining Limitations and Phase 11 Candidates

1. Container hierarchy evidence가 여전히 부족해 hierarchy-positive relation 판정은 제한적이다.
2. Positive `MOVE_TO_OTHER_NODE` / `SNAP_BACK` 실기기 corpus가 아직 부족하다.
3. Shadow V2는 traversal을 바꾸지 않으며 future traversal improvement와 자동 결합하지 않는다.
4. Frozen ledger를 sanitized committed fixture로 전환하면 CI replay portability가 개선된다.
5. Delayed commit promotion에는 attributable physical focus event가 추가로 필요하다.

이 항목들은 향후 Phase 11이 있다면 evidence/corpus/acceptance 범위로 다룬다. Traversal,
visit, coverage 또는 routing promotion과 자동 결합하지 않는다.

## 10. Final Verdict

**Can V10 Shadow Engine be considered production-ready? — YES WITH LIMITATIONS**

Phase 8 acceptance 기준인 reconciliation PASS, `anchor_abort_preserved=true`, per-run
feature flag, Identity Shadow V2 frontend integration, production traversal unchanged,
Evidence OFF parity는 모두 충족했다. 다만 container hierarchy evidence와 positive
`MOVE_TO_OTHER_NODE` / `SNAP_BACK` 실기기 corpus는 여전히 제한적이다. 따라서 V10 Shadow
Engine은 shadow-only 완료 상태로 간주할 수 있지만, 남은 limitation은 이후 corpus/evidence
확장 과제로 분리해 관리해야 한다.
