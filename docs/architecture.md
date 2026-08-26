# Architecture (현재 운영 기준)

[System Overview](system-overview.md) | [Current Client Architecture](current-client-architecture.md) |
[Operational Runbook](operations/talkback-operational-runbook.md) | [Device Plugin Guide](device-plugin-guide.md)

Updated for current `main`: 2026-08-26

## 1) 계층과 실행 경계

```text
QA Frontend / Backend control plane
  -> device / ADB / Helper / TalkBack preflight
  -> Full Validation / Quick Smoke / Custom profile
  -> canonical scenario selection
  -> Batch Runner and current-run/history projection

Execution plane
  -> RunSpec feature flags
  -> script_test.py / A11yAdbClient façade
  -> collection_flow (step lifecycle outer orchestrator)
  -> TraversalCoordinator
       -> StopPolicy
       -> RecoveryCoordinator
       -> RecoveryExecutor / FOCUS_IN_BOUNDS action lifecycle
       -> VisitTracker
       -> Traversal Evidence Gate
  -> Android Helper AccessibilityService
  -> XLSX + JSON/log/evidence/crop artifacts

Review / comparison plane
  -> QA Review vs Automation Diagnostics classification
  -> terminal Full Run Candidate generation
  -> Offline Validation
  -> Comparator / Compare UI
  -> human approval
  -> Approved Baseline + observation bundle

Diagnostic / shadow plane (read-only to production routing)
  -> Coverage Probe / coverage health
  -> V10 Runtime Inventory / Quick Identify / Policy Registry
  -> V10 Shadow Compare / Promotion Readiness / Corpus Readiness
```

Production execution은 `collection_flow`의 lifecycle과 기존 action/policy 구현을
중심으로 동작합니다. `traversal_orchestration.py`는 이 lifecycle에 stop/recovery/visit
결정을 연결하고, Android Helper는 실제 accessibility action과 tree/focus bridge를
제공합니다.

## 2) Production authority

### Run profile과 scenario membership

`tb_runner/scenario_config.py`의 `canonical_full_scenario_ids()`가 `TAB_CONFIGS` 전체를
반환하며 현재 canonical Full Validation membership은 32개입니다. `runtime_config.json`
의 `enabled`는 targeted execution default일 뿐 Full membership을 정의하지 않습니다.
QA Frontend에서 exact canonical selection은 Full Validation이고 partial selection은
Custom Run입니다.

Full Validation profile은 Clean launch, Full mode, Coverage Probe, Evidence Ledger,
Identity V2, Production Traversal V2, Profiler를 사용합니다. Shadow Validation은 별도
opt-in이며 Full profile의 production traversal authority와 혼동하지 않습니다.

### Traversal Identity V2

Traversal Identity V2는 현재 Production Default입니다. source-level default는
`tb_runner/run_spec.py`, QA Backend Batch Runner, QA Frontend Full profile에서 모두
enabled입니다. V2가 ON이면 Identity와 Evidence Ledger dependency가 run-scoped로
함께 활성화됩니다.

`tb_runner/traversal_evidence_gate.py`는 complete transaction, ACKed helper transport,
matching transaction ID, stable landing, high-confidence와 contradiction 여부를 확인한
강한 evidence를 production decision에 전달합니다.

- strong `MOVE_CONFIRMED`: 실제 이동/visit 진행에 제한적으로 사용
- strong `STATIC_FOCUS`: 정적 focus를 확인해 false progress를 억제하는 데 사용
- `MOVE_TO_OTHER_NODE`, `SNAP_BACK`, incomplete, malformed, orphan, uncorrelated,
  indeterminate: Legacy fallback

`TB_TRAVERSAL_IDENTITY_V2_ENABLED=0`을 명시한 run은 Legacy Compatibility path입니다.
이 path는 기존 traversal/anchor/representative/visit/coverage/audit/summary/XLSX
계약을 유지하기 위한 run-scoped compatibility입니다. V2의 shadow reducer 자체와
production gate 소비를 혼동하지 않아야 합니다.

```text
Traversal engine selection (run-scoped)
  flag omitted or 1 -> Traversal Identity V2 / Production Default
  flag explicitly 0 -> Legacy Traversal / Compatibility Mode
```

`collection_flow.py`는 side-effect ordering과 step lifecycle의 source of truth로 남고,
`TraversalCoordinator`는 policy와 Android action을 재구현하지 않습니다. Candidate
selection, focus action, recovery result, stop counter/threshold, row persistence,
coverage, representative selection과 evidence emission은 기존 phase contract를
통해 실행됩니다.

### Evidence Ledger와 Coverage

Evidence Ledger는 helper action/evidence event를 transaction과 correlation ID에 따라
append-only로 기록하고, Canonical Identity normalization/reconciliation에 필요한
입력을 제공합니다. 이 ledger가 있어야 V2가 closed transaction 여부와 orphan/duplicate/
contradiction을 판단할 수 있습니다.

Coverage Probe는 focusable inventory에서 bounded `FOCUS_IN_BOUNDS` probe를 수행해
candidate coverage와 semantic-value evidence를 보강하는 별도 경로입니다. 현재 Full
Validation profile에서는 켜지지만 probe/coverage health는 validator-facing diagnostic
projection이며, 그것만으로 traversal이나 제품 PASS/FAIL verdict의 권위를 갖지 않습니다.
Coverage, audit, semantic shadow 결과는 조사와 review의 근거로 사용되고, production
traversal gate의 명시된 strong-evidence 계약을 대체하지 않습니다.

## 3) Helper, client, runner 계층

### Android Helper

`app/`의 `AccessibilityService`는 ADB broadcast 명령을 받아 tree dump, focus target,
click, next/previous, smart-next, scroll, text input과 evidence event를 수행합니다.
대용량 tree dump는 chunked transport를 사용합니다.

### Python client

- `talkback_lib/__init__.py`: 공개 `A11yAdbClient` façade
- low-level ADB execution, logcat, action result parsing, helper bridge
- focus trace, focus service, step row, collection service

공개 client 계약은 유지하고 내부 책임은 모듈별로 분리되어 있습니다. 상세 내용은
[current-client-architecture.md](current-client-architecture.md)를 따릅니다.

### Runner와 plugin traversal

- `collection_flow.py`: scenario open, precondition, main loop, checkpoint, persist
- `anchor_logic.py`, `tab_logic.py`, `local_tab_logic.py`: start/local-tab stabilization
- `overlay_logic.py`: overlay classification과 bounded recovery
- Device plugin: `All devices` 상태, visible inventory 우선, 필요 시 room expand,
  safe tap, bounded ADB swipe search
- Life plugin: locale-aware XML scroll/search와 plugin-specific anchors/context
- `excel_report.py`: raw/result/summary와 final workbook export

Report의 기본 visible 계열은 actual TalkBack focus 기준이고 traversal representative는
`representative_*` 컬럼에 따로 저장됩니다.

## 4) QA Frontend와 review 계층

QA Frontend Backend는 ADB/device preflight, run-scoped `RunSpec`, Batch Runner, current
progress, terminal status, crash/coverage/identity/recovery projection을 제공합니다.
Frontend는 Full/Smoke/Custom profile, scenario selection, current run, history, review,
comparator 화면을 제공합니다.

Quality signal은 `review_classification.py` 계약으로 분리됩니다.

- `qa_accessibility`: 실제 접근성 품질을 사람이 판단해야 하는 QA Review 대상
- `automation_engine`: runner/recovery/artifact/environment의 automation diagnostic
- `unknown`: 분류 provenance가 부족하여 별도 조사해야 하는 대상

Review Required panel의 QA count에는 Automation Diagnostics가 포함되지 않습니다. 이
분리는 automation 오류를 사용자 접근성 결함으로 자동 오인하지 않게 하지만, QA review,
known-limitation snapshot, automation acknowledgment가 모두 필요한 Candidate approval
절차를 없애지는 않습니다.

## 5) Candidate, Comparator, Baseline

```text
qualifying terminal Full Validation
  -> deterministic profiler archive
  -> Candidate (write-only/additive, unapproved)
  -> Offline Validation
  -> Comparator replay / canonical JSON + Markdown report
  -> QA review + automation acknowledgment
  -> explicit human approval
  -> Approved Baseline + portable observation bundle
```

Batch Runner는 full registry, terminal state, successful device return code, zero
`NO_TARGET_CANDIDATE`와 required artifacts 등의 조건을 만족할 때 Candidate generation을
시도합니다. Candidate가 `NOT_ELIGIBLE`이어도 읽을 수 있으면 Comparator 선택 목록에는
남을 수 있지만 approval을 의미하지 않습니다.

Comparator는 명시적으로 선택한 Candidate와 Approved Baseline을 read-only로 비교합니다.
입력은 local `qa_frontend_runs/`와 tracked/migrated baseline package에서 오며, Comparator
또는 Frontend가 Baseline, Candidate, repository lifecycle을 자동 변경하지 않습니다.
비교 history는 현재 backend process memory 범위이며 remote CAS/durable shared history는
제공되지 않습니다.

## 6) Diagnostic, shadow, and V10 boundary

### Coverage/audit/shadow

Coverage health, Device Plugin Audit, semantic-value shadow와 Identity Shadow reporting은
관찰/분석/리포팅 계층입니다. Identity V2의 reducer는 shadow evidence를 만들고, 명시된
strong closed transaction만 Production Traversal Gate를 통해 제한적으로 소비됩니다.
그 밖의 incomplete/indeterminate 결과와 모든 audit/coverage projection은 fallback 또는
진단으로 남습니다.

### V10

V10은 Runtime Inventory, Quick Plugin Identify, versioned Policy Registry, Shadow Compare,
Promotion Readiness, Shadow Corpus와 QA Frontend readiness card를 제공합니다. V10은
Legacy run artifact를 입력으로 candidate/readiness를 평가하지만 production routing이나
traversal을 시작하지 않습니다.

**Controlled Routing은 NOT STARTED입니다.** V10의 `READY`, `MATCH`, family readiness와
corpus 요약은 shadow evaluation이며 production verdict authority가 아닙니다.

```text
Production authority
  RunSpec -> collection_flow -> Traversal Identity V2 gate/fallback
  -> Runner/Helper actions -> report and terminal result

Diagnostic / shadow only
  Coverage Probe, audit, V10 identify/compare/readiness/corpus
  -> observe/analyze/report; no Controlled Routing
```

## 7) 운영 불변 계약과 제한

- Helper protocol과 public client contract 유지
- V2 OFF 시 Legacy Compatibility semantics 유지
- Shadow 실패는 Legacy/production result로 자동 전파하지 않음
- `unknown`, `ambiguous`, `failed`는 fail-closed
- exact reviewed model policy를 사용하며 unknown model 자동 승인을 하지 않음
- Full Validation은 controlled/manual이며 human approval이 필요
- 최신 `main`의 32-scenario physical-device acceptance 결과를 이 문서가 주장하지 않음

현재 운영 readiness는 **Production Ready with Limitations (controlled/manual)**입니다.
Phase 8/9/10 문서의 acceptance와 RCA는 각 날짜와 scope의 historical evidence로 보존되며,
현재 architecture contract나 최신 validation result로 재해석하지 않습니다.
