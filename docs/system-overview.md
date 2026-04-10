# System Overview (현재 운영 기준)

[Architecture](architecture.md) | [Testing Pipeline](testing-pipeline.md) | [Current Client Architecture](current-client-architecture.md)

---

## 1) 시스템 목적

`talkback-a11y-helper`는 기존 자동화 라이브러리를 대체하는 프로젝트가 아니라,
**TalkBack 활성화 환경에서 발생하는 접근성 제어 공백을 보완**하는 프로젝트입니다.

- 일반 환경: 기존 자동화 경로 사용
- TalkBack 환경 실패 구간: helper + Python runner 경로 사용

---

## 2) 현재 구성

### Android Helper (`app/`)
- 접근성 이벤트 수신
- broadcast 액션 처리(GET_FOCUS, DUMP_TREE, SMART_NEXT 등)
- 포커스/클릭/스크롤/텍스트 입력 액션 실행

### Python Runner (`script_test.py`, `tb_runner/`, `talkback_lib/`)
- scenario open → step loop → overlay → stop 판단 → 저장
- row 기반 결과 수집 및 엑셀 리포트 생성

---

## 3) 현재 실행 축

1. `script_test.py`가 runtime 설정을 병합
2. 시나리오별 `collect_tab_rows(...)` 실행
3. step마다 `A11yAdbClient.collect_focus_step(...)` 호출
4. `StopEvaluator`로 종료 판단
5. `save_excel_with_perf(...)`로 checkpoint/final 저장

---

## 4) 현재 문서 우선순위

운영/구현 기준은 아래 문서를 우선합니다.

1. `docs/current-client-architecture.md`
2. `docs/testing-pipeline.md`
3. `docs/api-reference.md`
4. `docs/runner_flow.md`

PR 설계 문서(`docs/pr*.md`)는 historical design record이며, 현재 운영 기준 문서가 아닙니다.
