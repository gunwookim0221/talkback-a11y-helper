# System Overview (현재 운영 기준)

[Project README](../README.md) | [Architecture](architecture.md) |
[Runner Flow](runner_flow.md) | [Testing Pipeline](testing-pipeline.md)

Updated for current `main`: 2026-08-26

## 1) 시스템 목적

`talkback-a11y-helper`는 SmartThings TalkBack 환경에서 일반적인 UI 자동화만으로
안정적으로 다루기 어려운 focus 이동, 화면 진입, scenario traversal, step 수집과
접근성 report 생성을 보조합니다. Android Helper가 accessibility bridge를 제공하고,
Python Runner가 실행 semantics와 evidence 수집을 조정하며, QA Frontend가 preflight부터
review와 비교까지의 controlled/manual workflow를 제공합니다.

## 2) 현재 실행 lifecycle

```text
QA Frontend
  -> Device / ADB / Helper / TalkBack preflight
  -> Run Profile + scenario selection
  -> Batch Runner
  -> Python Runner <-> Android Helper
  -> Traversal / recovery / evidence collection
  -> XLSX + JSON/log/evidence artifacts
  -> QA Review / Automation Diagnostics classification
  -> Candidate + Offline Validation
  -> Comparator / Compare UI
  -> Human decision
  -> Approved Baseline + observation bundle
```

QA Frontend는 선택된 device와 scenario를 확인하고 Batch Runner에 run-scoped profile을
전달합니다. Runner는 `script_test.py`, `collection_flow.py`, `tb_runner/`와
`talkback_lib/`를 통해 scenario를 실행합니다. Helper는 tree/focus/action/evidence
bridge를 담당하고, Runner는 traversal, recovery, stop, persistence와 report row를
담당합니다.

Candidate는 qualifying Full Validation의 기존 artifact에서 additive하게 만들어지는
비승인 비교 입력입니다. Offline Validation과 Comparator는 입력을 읽어 deterministic
report/verdict를 만들지만, Baseline을 자동 승인하거나 변경하지 않습니다. 최종 승인은
사람이 수행합니다.

## 3) Canonical Full Validation과 runtime defaults

현재 canonical Full Validation은 `tb_runner/scenario_config.py`의
`canonical_full_scenario_ids()`가 반환하는 `TAB_CONFIGS` 전체 **32개 scenario**입니다.
구성은 main/navigation 6개, Device plugin 12개, Life plugin 12개,
auxiliary/support 2개입니다.

`config/runtime_config.json`의 `enabled`는 targeted execution default입니다. checked-in
기본 config는 32개 entry 중 1개만 enabled로 두고 있지만, 이 값은 Full Validation의
membership을 정의하지 않습니다. QA Frontend가 exact canonical selection을 전달하면
Full Validation으로 분류하고, 일부 선택은 Custom Run으로 분류합니다.

Full Validation profile은 Clean launch, Full mode, Coverage Probe, Evidence Ledger,
Identity V2, Production Traversal V2, Profiler를 사용합니다. Shadow Validation은 별도
opt-in입니다. Smoke/targeted run은 재현과 진단 입력이며 Full acceptance evidence와
동일하지 않습니다.

## 4) 현재 traversal과 evidence

- `collection_flow.py`는 step lifecycle의 outer orchestrator입니다.
- `traversal_orchestration.py`는 stop/recovery/visit coordination을 기존 action/policy와
  연결합니다.
- Traversal Identity V2는 현재 run-scoped Production Default입니다.
- complete transaction, ACK, matching transaction ID, stable landing, high-confidence를
  갖춘 강한 evidence만 V2 gate가 production progress/visit/stop/recovery에 제한적으로
  사용할 수 있습니다.
- `MOVE_TO_OTHER_NODE`, `SNAP_BACK`, incomplete, malformed, orphan, indeterminate 결과는
  Legacy fallback입니다. `TB_TRAVERSAL_IDENTITY_V2_ENABLED=0`은 해당 run의 Legacy
  Compatibility path를 명시적으로 선택합니다.

Evidence에는 actual TalkBack focus, visible text, accessibility/evidence event,
TalkBack speech observation, screenshot/crop, raw/filtered/summary/result row,
reconciliation와 run artifact가 포함될 수 있습니다. Report의 기본 visible 계열은
actual focus 기준이며, traversal representative는 `representative_*` 컬럼으로 분리됩니다.

Evidence Ledger는 append-only transaction/evidence correlation과 V2 reconciliation을
지원합니다. Coverage Probe는 focusable candidate/coverage를 보강하는 opt-in probe이고,
`coverage_health` projection은 validator-facing 진단입니다. Coverage/audit/probe는
제품의 Full PASS/FAIL authority를 임의로 대체하지 않습니다.

## 5) QA finding과 automation diagnostic

현재 quality signal은 common review classification contract에 따라 다음처럼 나뉩니다.

- **QA accessibility finding (`qa_accessibility`)**: 실제 접근성 품질 검토가 필요한
  signal. Review Required panel의 QA Review count와 human review 대상에 포함됩니다.
- **Automation diagnostic (`automation_engine`)**: traversal, recovery, artifact,
  environment 또는 engine 동작을 조사할 signal. QA accessibility finding으로 자동
  승격하지 않으며 별도 diagnostic으로 표시됩니다.
- **Unknown**: 분류 근거가 부족한 signal. 임의로 QA 또는 automation에 넣지 않고
  classification provenance를 보강해야 합니다.

이 구분은 자동으로 product verdict를 확정한다는 뜻이 아닙니다. Candidate approval에는
QA review decision, known-limitation snapshot, automation acknowledgment와 offline
validation이 각각 필요한 controlled/manual 절차가 적용됩니다.

## 6) V10 Shadow 경계

V10은 다음 read-only/shadow 기능을 제공합니다.

- Devices Runtime Inventory와 bounded discovery
- capability/resource-id/XML/header evidence 기반 Quick Plugin Identify
- versioned Policy Registry와 scenario candidate 생성
- Legacy 결과와 V10 candidate의 Shadow Compare
- Promotion Readiness, corpus/readiness와 QA Frontend reporting

V10 candidate는 production routing이나 traversal을 시작하지 않습니다. V10 Controlled
Routing은 아직 구현되지 않았고, V10 문서의 `READY`/`MATCH`/readiness 표시는 shadow
evaluation 결과입니다. Production authority는 현재 Runner와 Traversal Identity V2
경로이며, V10은 그 경로의 verdict를 자동으로 바꾸지 않습니다.

## 7) 현재 운영 범위와 제한

- `com.samsung.android.oneconnect` SmartThings application
- English와 Korean locale 실행
- `config/device_classification_policy.json`에 exact reviewed model로 등록된 단말
- Full Validation, Quick Smoke, Custom/Debug 실행과 local Batch/Run History
- XLSX, JSON/log/evidence/crop, Candidate/Comparator/Approved Baseline workflow

현재 readiness는 **Production Ready with Limitations (controlled/manual)**입니다.
사람의 approval이 필요하고 unattended approval은 없습니다. Run History는 backend
process/local artifact 범위이며 remote CAS와 durable shared history가 없습니다. Baseline
family/multi-device coverage는 제한적이고, unknown model은 자동 승인하지 않습니다.
Candidate의 일반적인 portable observation bundle 첨부와 일부 post-approval migration도
명시적인 운영 단계로 남아 있습니다.

## 8) Acceptance evidence의 scope

저장소의 다음 결과는 모두 dated/group evidence입니다.

- 2026-07-03 문서에 기록된 Global long-run `7/7`, Life `12/12`, Device `12/12`,
  ko/en representative smoke 결과
- Phase 8/8.5 identity/traversal acceptance와 recovery/reconciliation 수치
- Phase 9.5 및 9.5.1의 Full Run/regression 실패와 후속 RCA/fix 기록
- Phase 10의 controlled/manual offline/comparator acceptance

이 결과들은 해당 checkpoint의 상태를 보존합니다. 현재 `main`의 최신 physical-device
canonical 32-scenario Full Validation에 대한 새로운 tracked acceptance result가 없으므로,
위 결과를 최신 HEAD의 PASS 증거로 제시하지 않습니다. 현재 문서의 `current` 표시는
구현 capability와 운영 계약을 의미하며, fresh validation result를 의미하지 않습니다.

## 9) Related current documents

1. [Operational Runbook](operations/talkback-operational-runbook.md)
2. [QA Frontend README](../qa_frontend/README.md) / [Validation contract](../qa_frontend/VALIDATION.md)
3. [Architecture](architecture.md)
4. [Current client architecture](current-client-architecture.md)
5. [Runner flow](runner_flow.md) / [Testing pipeline](testing-pipeline.md)
6. [Device plugin guide](device-plugin-guide.md) / [Report schema](report-schema.md)
7. [Phase 10.2.5 Run Profiles](design/talkback-phase10.2.5-run-profiles.md)
8. [Comparator finalization](design/talkback-phase10.3d-comparator-finalization.md) /
   [Phase 10.4 Compare UI](design/talkback-phase10.4-compare-ui.md)
9. [V10 phase closure](design/v10/v10-phase-closure.md)

Historical 설계 문서는 [archive/](archive/)와 각 phase 문서에 보존되어 있으며, current
운영 판단은 위 문서와 current source를 우선합니다.
