# Architecture (현재 운영 기준)

[System Overview](system-overview.md) | [Current Client Architecture](current-client-architecture.md) | [Device Plugin Guide](device-plugin-guide.md)

Updated for Canonical Identity Shadow Phase 8: 2026-07-12

## 1) 상위 구조

```text
Python Runner
  script_test.py
  tb_runner/*
  talkback_lib/*
    -> A11yAdbClient façade
    -> focus / step / row assembly
    -> runtime log parsing and report save

Android Helper
  app/*
    -> AccessibilityService
    -> target action / dump_tree / SMART_NEXT bridge

QA Frontend / V10 Shadow
  qa_frontend/backend/*
  tb_runner/device_inventory.py
  tb_runner/quick_plugin_identify.py
  tb_runner/policy_registry.py
  tb_runner/shadow_compare.py
    -> inventory / identify / candidate / comparison
    -> promotion readiness / Recent Runs reporting

Traversal Evidence / Canonical Identity Shadow
  tb_runner/evidence.py
  tb_runner/evidence_identity.py
  qa_frontend/backend/evidence_identity_reporting.py
    -> append-only action evidence
    -> canonical observation normalization
    -> V2 physical/semantic/hierarchy/temporal relation
    -> read-only verdict distribution reporting
```

## 2) 운영 계층

### Client 계층
- `A11yAdbClient`
- `FocusService`
- `StepCollectionService`
- `StepRowBuilder`

### Runner 계층
- `collection_flow.py`: scenario open, main loop, persist
- `anchor_logic.py`, `tab_logic.py`: start stabilization
- `overlay_logic.py`: overlay branch and recovery
- `excel_report.py`: workbook export

### Scenario 계층
- Global / main tabs
- Life plugins
- Device plugins

### V10 Shadow 계층

- `device_inventory.py`: bounded Device Card inventory와 conservative boundary dedupe
- `quick_plugin_identify.py`: post-open helper/XML evidence와 fail-closed classification
- `policy_registry.py`: versioned plugin-family-to-scenario candidate mapping
- `shadow_compare.py`: Legacy/V10 comparison과 metrics
- `shadow_pipeline.py`: Full Run 이후 별도 pass orchestration
- `promotion_readiness.py`: family별 readiness 평가와 JSON/Markdown 생성
- `shadow_reporting.py`: Recent Runs용 optional summary

현재 실행 관계:

```text
Legacy Full Run (authoritative)
  -> Legacy artifact 저장
  -> [Shadow requested + run-local flags ON]
     Runtime Inventory
       -> Quick Plugin Identify
       -> Policy Registry candidate
       -> Legacy/V10 Shadow Compare
       -> Promotion Readiness
       -> Shadow Reporting
  -> Legacy result 반환
```

V10 경로는 scenario candidate를 만들지만 production routing이나 traversal을 수행하지
않는다.

### Canonical Identity Shadow 계층

Canonical Identity Shadow는 위 Device Card V10 Shadow와 독립된 evidence 분석 계층이다.

```text
Helper evidenceEvents
  -> Runner transaction correlation
  -> evidence-event-v1 ledger
  -> Legacy shadow reducer (retained)
  -> CanonicalObservation normalization
  -> target-relation-v2 reducer
  -> append-only SHADOW_ACTION_REDUCED_V2
  -> reconciliation metrics / QA Frontend read-only report
```

Raw camelCase/snake_case observation은 normalization boundary에서 한 번만 변환한다.
이후 physical, semantic, hierarchy, temporal comparator는 CanonicalObservation만 읽는다.
Missing은 difference가 아니라 unavailable이며, hierarchy는 path/parent/assertion evidence만
사용한다. Bounds-only container inference는 금지한다.

최종 V2 verdict는 `MOVE_CONFIRMED`, `STATIC_FOCUS`, `MOVE_TO_OTHER_NODE`,
`SNAP_BACK`, `INDETERMINATE`다. 이 verdict는 traversal, visit, coverage, audit,
production summary/PASS/FAIL 또는 XLSX의 입력이 아니다. 상세 acceptance와 limitation은
[talkback-identity-shadow-phase8-completion.md](design/talkback-identity-shadow-phase8-completion.md)를
따른다.

## 3) Devices plugin 운영 추가점

Devices plugin은 일반 Life plugin과 다르게 Devices list normalization을 먼저
수행한다.

- `enter_device_card_plugin` pre-navigation 사용
- `All devices` selected 보장
- visible inventory 우선 매칭
- 필요할 때만 room expand
- safe tap 적용
- bounded search는 helper scroll이 아니라 **ADB swipe** 사용

자세한 흐름은 [device-plugin-guide.md](device-plugin-guide.md)를 따른다.

## 4) Report row semantics

현재 raw/result 기본 visible 계열은 representative가 아니라 **actual TalkBack
focus 기준**이다.

- 기본 컬럼: actual focus
- `representative_*`: traversal representative

자세한 스키마는 [report-schema.md](report-schema.md)를 본다.

## 5) 불변 계약

- helper protocol unchanged
- traversal / scoring / representative selection unchanged
- stop reason 해석 유지
- 운영 로그 키 유지
- row schema는 additive change를 우선
- Shadow 실패는 Legacy 결과로 전파하지 않음
- `unknown`, `ambiguous`, `failed`는 fail-closed
- Controlled Routing과 V10 traversal은 비활성/미구현
- Canonical Identity V2 verdict는 shadow-only이며 production consumer가 없음
