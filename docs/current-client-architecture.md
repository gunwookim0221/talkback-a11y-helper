# Current Client Architecture (PR14 반영 기준)

이 문서는 **현재 운영 기준 문서**입니다.  
기준 시점: PR14-A/B/C 반영 이후의 `talkback_lib` 구조.

---

## 1) 현재 `talkback_lib` 구조

현재 Python client는 단일 파일이 아니라 책임별 모듈로 분리되어 있습니다.

- `talkback_lib/__init__.py`
  - `A11yAdbClient` 공개 API 제공
  - 하위 서비스/헬퍼 조합 오케스트레이션
- `talkback_lib/adb_executor.py`
  - ADB 명령 실행 공통화
- `talkback_lib/logcat_reader.py`
  - logcat polling/req_id 기반 결과 읽기
- `talkback_lib/action_result_parser.py`
  - 브로드캐스트 payload 추출/정규화
- `talkback_lib/helper_bridge.py`
  - helper broadcast 요청 계층
- `talkback_lib/focus_service.py`
  - `get_focus` 실행 + fallback dump 분기
- `talkback_lib/step_row_builder.py`
  - step row dict 조립/필드 채움 함수
- `talkback_lib/step_collection_service.py`
  - `collect_focus_step` orchestration
- `talkback_lib/focus_trace_builder.py`
  - get_focus trace 초기화/후보 추출 보조
- 기타: `adb_device.py`, `models.py`, `utils.py`, `constants.py`

---

## 2) `A11yAdbClient`의 현재 역할: façade

`A11yAdbClient`는 현재도 외부 진입점이지만, 내부 구현 책임은 분리되어 있습니다.

- 외부 계약 유지
  - 기존 public method 이름/인자/반환 호환 유지
- 내부 위임
  - ADB 실행: `AdbExecutor`
  - log 읽기: `LogcatReader`
  - helper 요청: `HelperBridge`
  - focus 수집: `FocusService`
  - step 수집: `StepCollectionService`
- 결론
  - `A11yAdbClient`는 “모든 로직 구현 클래스”가 아니라 **오케스트레이터 façade**입니다.

---

## 3) PR14-A/B/C 분리 결과

### PR14-A (low-level 분리)

- ADB 실행 / logcat 읽기 / action 결과 파싱 계층 분리
- 핵심 모듈: `adb_executor.py`, `logcat_reader.py`, `action_result_parser.py`, `helper_bridge.py`

### PR14-B (trace/row assembly 분리)

- `get_focus` trace 조립과 step row 조립 책임 분리
- 핵심 모듈: `focus_trace_builder.py`, `step_row_builder.py`, `focus_service.py`, `step_collection_service.py`

### PR14-C (orchestration service 분리)

- `A11yAdbClient`에서 대형 메서드 책임 축소
- `FocusService`, `StepCollectionService`로 orchestration 분리
- `A11yAdbClient`는 공개 API 및 상태 결합 지점으로 유지

---

## 4) 현재 `tb_runner` 주요 흐름

`script_test.py`와 `tb_runner/*`는 아래 고정 흐름으로 동작합니다.

1. runtime config 병합 로드
2. scenario open
   - tab stabilize
   - pre_navigation (옵션)
   - anchor stabilize
3. anchor row(step 0) 수집
4. main step loop
   - `collect_focus_step(move=True)`
   - stop evaluator 판단
   - overlay 후보면 overlay 확장/복귀
5. checkpoint/final 엑셀 저장

핵심은 `A11yAdbClient.collect_focus_step`이 step row 계약을 유지한 채 runner의 main loop 입력을 공급한다는 점입니다.

---

## 5) 절대 보존 계약 (운영 불변식)

다음 항목은 현재 운영 계약이며, 문서/리팩토링 시에도 유지해야 합니다.

1. **row dict 구조**
   - `collect_focus_step` 결과 key 집합과 의미를 깨면 안 됨
2. **get_focus fallback semantics**
   - `success=false` + top-level payload 처리
   - 필요 시 dump fallback 진입 조건 유지
3. **overlay realign semantics**
   - overlay 종료 후 realign + 후속 안정화 흐름 유지
4. **stop semantics**
   - `StopEvaluator` strong/weak 조합 의미 유지
5. **로그 불변 원칙**
   - 운영 분석 파이프라인이 의존하는 핵심 로그 키/패턴은 하위 호환 유지

---

## 6) 문서 사용 원칙

- 이 문서는 “현재 운영 기준”입니다.
- PR1/2/3/4/14 문서는 설계 당시 기록이며, 현재 동작 확인은 본 문서 + 아래 운영 문서를 우선합니다.
  - `docs/system-overview.md`
  - `docs/architecture.md`
  - `docs/testing-pipeline.md`
  - `docs/api-reference.md`
