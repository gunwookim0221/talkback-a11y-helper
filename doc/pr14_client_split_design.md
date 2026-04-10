# PR14 Client 분해 설계서 (동작 보존 최우선)

본 문서는 `talkback_lib/__init__.py`에 집중된 책임을 다음 리팩토링 단계에서 안전하게 분리하기 위한 **기준 설계서**다.

- 범위: Python client (`talkback_lib/__init__.py`) 구조 분해 설계
- 제외: Android Helper (`app/*`) 수정, 런타임 동작/정책 변경
- 현재 기준: PR9~PR13까지 반영된 안정 상태
  - PR9: `get_focus` / `collect_focus_step` 내부 분해
  - PR10: action result normalize 정리
  - PR11: retry/timeout 공통화
  - PR12: payload 판정 helper 정리
  - PR13: `TARGET_ACTION_RESULT` 경량 cache 최적화

---

## 0) 왜 지금 분해를 시작하는가

지금은 정책 변경을 할 타이밍이 아니라, 이미 안정화된 정책을 **구조적으로 분리해 유지보수 비용을 줄일 타이밍**이다.

- PR9~PR13에서 위험도가 높은 동작 계층(포커스 수집/normalize/retry/payload/cache)은 이미 안정화됨.
- 이 상태에서 책임 분해를 시작하면, “정책 수정 + 구조 변경”이 한 번에 섞이는 위험을 피할 수 있다.
- 즉 PR14 계열의 목표는 기능 개선이 아니라 **회귀 리스크를 줄이는 구조화**다.

---

## 1) 현재 문제 정의: `talkback_lib/__init__.py`의 과집중 책임

현재 `A11yAdbClient`는 아래 책임을 사실상 단일 파일/단일 클래스에 집중시키고 있다.

1. ADB 실행/전송 계층
   - `_run`, `_broadcast`, `clear_logcat`, 탭/스크롤/터치 계열 실행
2. Helper 액션 요청 계층
   - `touch`, `select`, `click_focused`, `move_focus`, `move_focus_smart`, `dump_tree`, `get_focus`
3. logcat 수집/파싱 계층
   - `_read_log_result`, `_extract_*payload*`, req_id 매칭
4. payload/결과 normalize 계층
   - `_normalize_action_result`, `_normalize_target_action_payload`, 성공/실패 판정 helper
5. focus trace 조립 계층
   - `get_focus` trace 기록 + fallback dump 연계
6. step row 조립 계층
   - `collect_focus_step`의 row dict 생성/필드 채움/trace 반영
7. screenshot/dump 보조 계층
   - `_take_snapshot`, `_save_failure_image`, dump 보강
8. retry/timeout orchestration 계층
   - `_run_with_retry`, wait/sleep/backoff 적용
9. announcement/history/state cache 계층
   - helper 상태 cache, last action cache, focus/announcement 관련 상태 유지

문제는 “기능이 많다”가 아니라, **변경 단위와 책임 단위가 맞지 않는다**는 점이다.

- 예: payload 파싱을 수정하려 해도 `get_focus`/`collect_focus_step`/logcat read 흐름까지 함께 검토해야 함.
- 예: retry/timeout 조정을 검토할 때 action normalize 및 상태 cache 부작용까지 동반 검토가 필요함.

---

## 2) 분해 목표 (지향 구조, 즉시 구현안 아님)

아래는 PR14 이후 단계에서 지향할 모듈 책임 경계다. **이번 문서의 목표는 구조 기준 제시이며 즉시 전면 구현이 아니다.**

### 2-1. 지향 책임 단위

- `AdbExecutor` (또는 `AdbTransport`)
  - adb command 실행, serial 해석, timeout 공통 처리
- `HelperActionClient`
  - helper action broadcast 요청/응답 orchestration
- `LogcatReader`
  - logcat 읽기, req_id 매칭, marker/시간축 처리
- `ActionResultParser`
  - payload 추출/정규화/성공 판정
- `FocusCollector`
  - `get_focus` 실행 + trace + fallback dump 정책 적용
- `StepRowBuilder`
  - `collect_focus_step` row dict 조립 및 필드 규격 고정
- `RetryPolicy` (또는 retry helper layer)
  - 공통 retry/sleep/timeout semantics 캡슐화

### 2-2. 아키텍처 원칙

1. `A11yAdbClient`는 façade/orchestrator로 축소한다.
2. 정책(semantics)과 전송/파싱/조립(implementation detail)을 분리한다.
3. public method signature 및 반환 구조는 기존과 동일하게 유지한다.
4. 각 PR은 “하나의 책임층”만 이동시킨다.

---

## 3) 절대 유지해야 하는 계약 (변경 금지)

다음 항목은 리팩토링 과정에서 **절대 변경 금지**다.

### 3-1. 수집 API/데이터 계약

- `collect_focus_step()`의 외부 계약(인자/반환/호출자 기대)
- row dict key 이름, 존재 조건, 값 타입
- `get_focus` trace 필드 및 `collect_focus_step` row 반영 방식

### 3-2. 동작/정책 계약

- timeout/sleep/retry semantics (시도 횟수, 대기 간격, 실패 시 종료 조건)
- `get_focus` success/fallback 정책 (fallback dump 진입 조건 포함)
- overlay/realign 흐름에서 client가 제공하는 상태/필드 semantics
- `move_focus_smart` status semantics (stop 판단/상위 로직과 호환)

### 3-3. 호환성 계약

- 기존 로그 문자열(운영 로그/디버그 로그 식별자)
- bool/string/dict 혼합 반환을 기대하는 기존 호출부와의 호환
- 현재 테스트가 기대하는 출력/상태/필드 존재성

---

## 4) 위험 포인트 (깨지기 쉬운 지점)

### 4-1. 반환 호환성 위험

- `select`/`touch`/`move_focus_smart`의 반환 타입·필드가 미세하게 바뀌면 상위 stop/overlay 판단이 연쇄적으로 깨질 수 있음.
- normalize 계층을 별도 모듈로 옮길 때 “truthy/falsy 판정”이 달라지는 위험이 큼.

### 4-2. trace ↔ row 연결 위험

- `get_focus` trace 필드명 또는 trace 채움 시점이 달라지면 `collect_focus_step` row의 품질 필드가 달라짐.
- 이 변경은 테스트 실패보다 먼저 runtime 로그/분석 파이프라인에서 문제로 드러날 수 있음.

### 4-3. overlay recovery 연계 위험

- overlay 종료 후 realign 관련 상태 필드(`overlay_recovery_status` 계열)와 step row 반영 타이밍이 조금만 달라도 PR4 기반 흐름과 불일치 발생.
- `move_result` 표현 변경이 stop 판단식에 직접 영향 가능.

### 4-4. logcat req_id 타이밍 위험

- `LogcatReader` 분리 시, req_id marker 탐지 타이밍/재시도 타이밍이 바뀌면 payload miss/오탐이 발생할 수 있음.
- 특히 “payload 없음”과 “아직 안 옴”의 판정 경계가 바뀌면 retry 정책이 사실상 변경됨.

### 4-5. cache/상태 필드 이동 위험

- PR13 cache 최적화(`TARGET_ACTION_RESULT`) 관련 상태를 다른 모듈로 이동할 때 cache hit/miss 시점이 달라질 가능성.
- helper status cache(serial별 TTL)도 의존 경로를 바꾸면 preflight 동작이 미세하게 달라질 수 있음.

---

## 5) 권장 PR 순서 (2~4개 중 3개 권장)

아래 순서는 “데이터/정책 경계가 안정적인 계층부터” 분리하도록 설계했다.

## PR14-A: logcat/adb/action parsing 계층 분리

- 수정 대상
  - adb 실행 래퍼, logcat 읽기/req_id 매칭, payload parse/normalize helper
- 기대 효과
  - I/O 계층과 정책 계층 분리
  - action parsing 변경의 영향 범위를 축소
- 위험도
  - 중간 (req_id 타이밍/normalize 호환성 리스크)
- 선행조건
  - PR10~PR13 기준 테스트 및 로그 baseline 확보
  - 기존 helper 함수명/로그 문자열 snapshot 확보

## PR14-B: focus/step row 조립 분리

- 수정 대상
  - `get_focus` trace 조립 책임과 `collect_focus_step` row 조립 책임의 분리
- 기대 효과
  - row schema 변경 없이 조립 로직 가시성 개선
  - 수집 품질 이슈 디버깅 경로 단순화
- 위험도
  - 높음 (trace↔row 계약 파손 가능성 큼)
- 선행조건
  - PR14-A 완료 후 I/O/parse 경계 고정
  - row key/필수 필드/선택 필드 목록 명문화

## PR14-C: `A11yAdbClient`를 orchestration façade로 축소

- 수정 대상
  - `A11yAdbClient` 내부의 orchestration 외 세부 구현 위임
- 기대 효과
  - 클래스 복잡도/리뷰 난이도 감소
  - 이후 변경 시 책임 단위 PR 가능
- 위험도
  - 중간 (상태 필드 이동 중 side effect 위험)
- 선행조건
  - PR14-A/B에서 추출한 모듈 경계 안정화
  - public API/로그 문자열/테스트 호환 재검증

---

## 6) 하지 말아야 할 것 (금지 항목)

1. 한 PR에서 대규모 파일 이동 + 의미 변경을 동시에 하지 않는다.
2. PR10/PR11/PR12에서 안정화한 normalize/retry/payload 판정 정책을 다시 손대지 않는다.
3. Android Helper와 Python client를 같은 PR에서 동시에 변경하지 않는다.
4. 테스트를 맞추기 위해 외부 계약(반환 타입/row key/로그 문자열)을 암묵적으로 바꾸지 않는다.
5. 신규 helper를 임시 보정용으로 증식시키지 않는다(책임 중복 금지).
6. fallback/late success/suppression 같은 임시 우회 분기를 추가하지 않는다.

---

## 7) 단계별 승인 기준 (PR gate)

각 PR은 아래를 통과해야 merge 가능하다.

### 7-1. 기본 테스트 게이트

- `pytest -q test_talkback_lib.py tests/test_collection_flow.py` 통과

### 7-2. 로그/런타임 게이트

- step/overlay/stop 흐름 로그 시퀀스가 기존과 동일
- 허용 가능한 diff가 있다면 “문자열 변경 이유 + 영향 없음”을 PR 본문에 명시

### 7-3. 품질 게이트

- fallback dump 발생 건수 증가 없음
- realign_success_rate 유지(기준 run 대비 하락 금지)
- stop reason 분포가 기준 run 대비 유의미하게 변하지 않음

### 7-4. 계약 게이트

- `collect_focus_step` row key/값 타입 변화 없음
- `move_focus_smart` status semantics 변화 없음
- get_focus 성공/실패/fallback 진입 규칙 변화 없음

---

## 8) 실행 체크리스트 (PR 작성자용)

1. 이 PR이 책임 하나만 이동하는지 확인
2. public signature 변경 여부 확인 (없어야 함)
3. 로그 문자열 변경 여부 확인 (없어야 함)
4. row dict key/type 변경 여부 확인 (없어야 함)
5. 테스트 + 샘플 runtime 로그 diff 첨부
6. 위험 포인트(반환/trace/req_id/cache) 점검 결과를 PR 본문에 기록

---

## 9) 결론

PR14 계열의 핵심은 “새 기능”이 아니라 “안정화된 동작의 안전한 구조 분리”다. 
따라서 권장 순서는 **I/O/파싱 분리 → trace/row 조립 분리 → façade 축소**이며, 각 단계는 계약/로그/테스트 동일성을 먼저 증명해야 한다.
