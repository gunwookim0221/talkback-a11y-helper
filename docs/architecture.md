# Architecture (현재 운영 기준)

[System Overview](system-overview.md) | [Testing Pipeline](testing-pipeline.md) | [Current Client Architecture](current-client-architecture.md)

---

## 1) 상위 구조

```text
Python Runner (script_test.py, tb_runner/*)
  -> A11yAdbClient (talkback_lib/__init__.py, façade)
    -> HelperBridge / AdbExecutor / LogcatReader / ActionResultParser
    -> FocusService / StepCollectionService / StepRowBuilder
  -> adb broadcast
Android Helper (app/*)
  -> AccessibilityService
  -> UI tree dump / target action
```

---

## 2) Python client 계층 책임

### Façade
- `A11yAdbClient` (`talkback_lib/__init__.py`)
- 외부 public API 유지 및 내부 서비스 조합

### Low-level
- `AdbExecutor`: adb 실행
- `LogcatReader`: logcat marker/req_id 기반 결과 수집
- `ActionResultParser`: payload 파싱/정규화
- `HelperBridge`: helper action 요청 라우팅

### Focus/Step 조립
- `FocusService`: `get_focus` 오케스트레이션 + fallback dump
- `FocusTraceBuilder`: get_focus trace 생성/후보 추출
- `StepCollectionService`: `collect_focus_step` 단계 실행
- `StepRowBuilder`: row dict 필드 조립

---

## 3) Runner 계층 책임

- `script_test.py`: run 진입점, 시나리오 반복, final 저장
- `tb_runner/collection_flow.py`: open/main/overlay/persist 오케스트레이션
- `tb_runner/anchor_logic.py`, `tab_logic.py`: 시작 안정화
- `tb_runner/diagnostics.py`: stop 평가/중복/품질 판단
- `tb_runner/overlay_logic.py`: overlay 확장/복귀
- `tb_runner/excel_report.py`, `perf_stats.py`: 저장/리포트

---

## 4) 현재 불변 계약

- `collect_focus_step` row dict schema 유지
- `get_focus` fallback semantics 유지
- overlay realign 후 main loop 복귀 semantics 유지
- stop reason/top-level status 해석 유지
- 운영 파이프라인이 의존하는 핵심 로그 키 유지

세부는 `docs/current-client-architecture.md`를 기준으로 확인합니다.
