# TalkBack A11y Helper

`talkback-a11y-helper`는 TalkBack 활성화 환경에서 접근성 자동화 수집/제어를 보조하는 프로젝트입니다.

---

## 프로젝트 구성 (현재 기준)

### 1) Android Helper (`app/`)

- `AccessibilityService` 기반 helper APK
- ADB broadcast 액션 수신
- 트리 덤프 / 포커스 이동 / 클릭 / 스크롤 / 텍스트 입력 수행

### 2) Python Runner (`script_test.py`, `tb_runner/`, `talkback_lib/`)

- 시나리오 기반 수집 실행
- step row 생성/정제/저장(`raw/filtered/summary/result`)
- overlay 처리, stop 정책, diagnostics 로깅

---

## Python client 구조 요약 (PR14 완료)

PR14-A/B/C까지 반영되어 Python client 책임 분해가 완료되었습니다.

- `A11yAdbClient` (`talkback_lib/__init__.py`): 공개 API façade
- low-level 분리
  - `adb_executor.py`, `logcat_reader.py`, `action_result_parser.py`, `helper_bridge.py`
- trace/row assembly 분리
  - `focus_trace_builder.py`, `focus_service.py`, `step_row_builder.py`, `step_collection_service.py`
- 결과: 공개 계약은 유지하면서 내부 책임을 모듈별로 분리

상세: `docs/current-client-architecture.md`

---

## 현재 문서 체계

### A. 현재 운영 기준 문서

- `docs/system-overview.md`
- `docs/architecture.md`
- `docs/testing-pipeline.md`
- `docs/api-reference.md`
- `docs/runtime-config.md`
- `docs/scenario-config.md`
- `docs/runner_flow.md`
- `docs/current-client-architecture.md`

### B. 과거 PR 설계 기록 (historical design record)

- `docs/pr1_function_split.md`
- `docs/pr2_start_pipeline_design.md`
- `docs/pr3_stop_policy_design.md`
- `docs/pr4_overlay_flow_design.md`
- `docs/pr14_client_split_design.md`

> 위 PR 문서들은 당시 설계 의사결정 기록이며, 현재 운영 기준은 A 섹션 문서를 우선합니다.

---

## 빠른 문서 안내

- 시스템 개요: `docs/system-overview.md`
- 아키텍처: `docs/architecture.md`
- 실행 파이프라인: `docs/testing-pipeline.md`
- 클라이언트 API: `docs/api-reference.md`
- Runner 상세 흐름: `docs/runner_flow.md`
- 시나리오/런타임 설정: `docs/scenario-config.md`, `docs/runtime-config.md`

---

## Debug Bundle 자동 캡처 (Python Runner)

`capture_debug_bundle.py`는 기본적으로 **Life plugin list scroll_capture**를 자동 수행합니다.

- 기본 실행: `python capture_debug_bundle.py`
- 선택 옵션:
  - `--mode scroll_capture` (기본: `scroll_capture`)
  - `--max_steps 10`
  - `--save_xml true|false` (기본: `true`)

저장 경로는 timestamp 기반으로 생성됩니다.

- `output/capture_bundles/life_plugin_scroll_capture/<run_id>/step_XX/`
- 각 step에는 `helper_dump.json`, `meta.json`, `screenshot.jpg`가 저장됩니다.
- `--save_xml=true`일 때 `window_dump.xml`도 함께 저장됩니다.
- run 루트에는 스텝 메타를 통합한 `summary.json`이 저장됩니다.
- `meta.json`에는 resource id 분석 필드(`resource_ids_top_n`, `resource_id_counts`, `resource_id_sources`, `resource_ids_card_like_top_n`)와 chrome 분리 필드(`top_bar_present`, `bottom_tab_present`, `chrome_filtered_labels`, `content_candidate_labels`)가 포함됩니다.
- `summary.json`에는 step 통합 resource id 필드(`resource_ids_union_top_n`, `resource_ids_card_like_union_top_n`, `steps_with_no_resource_ids` 등)가 포함됩니다.

---

## Overlay first-row 경로 디버그 게이트

overlay first-row 생명주기 추적 로그는 기본 OFF이며, 아래 환경변수 하나로만 활성화됩니다.

- `TB_OVERLAY_FIRST_ROW_DEBUG=true`

활성화 시 `[OVERLAY][FIRSTROW][...]` prefix 로그가 추가되어 synthetic 생성/append/반환/caller 수신/export 직전 경로를 추적할 수 있습니다.
