# Phase 5D-C4 제한 실행 계약

입력 설계 판정: DESIGN_READY_WITH_LIMITATIONS. C4만 구현하며 C5 의미적 성공,
실기기 동작, Scenario 31/32는 허용하지 않는다. 기본 빌드/실행 게이트는 OFF다.

## exact-canonical.v1

UTF-8 바이트, BOM/마지막 개행 없음. 객체 키는 UTF-16 unsigned code-unit 순서로
정렬한다. 배열 순서는 보존한다. 구분자는 `,`와 `:`이며 공백은 없다.
문자열은 ASCII JSON으로 표현한다. quote/backslash와 b/f/n/r/t를 escape하고,
U+0000..001F와 U+007F 이상은 소문자 `\uXXXX`로 표현한다. 보충 문자는 UTF-16
surrogate pair 두 개로 표현하며 고립 surrogate는 거절한다. slash는 escape하지 않는다.
정규화나 locale 변환은 없다. null/true/false는 소문자다. 숫자는 signed int64 정수만
허용하며 부동소수점은 거절한다. 객체/배열에 같은 규칙을 재귀 적용한다.
필드 부재와 명시적 null은 다르다. provenance도 일반 구조로 그대로 포함한다.
request_digest 자체만 제외한 모든 요청 필드(버전 포함)의 canonical 바이트를 SHA-256한다.
MAC은 별도 인증이며 digest는 인증을 대체하지 않는다.

## 버전 행렬

| 요청 | ACK | 권한 |
|---|---|---|
| talkback.exact-navigation.v1 | 1 또는 1.1 | 읽기 전용, 실행 불가 |
| talkback.exact-action.v2 | 2 | 인증된 단일 ACTION_CLICK, 두 게이트 필요 |
| 누락/기타 | 거절 | 실행 불가 |

읽기 전용 ACK 1.1은 validation_detail/failure_detail의 명시적 nullable 문자열만
추가 허용한다. 미등록 필드는 거절한다. perform_action_return은 필수이며
미호출 null과 호출 false를 구분한다.

## 승인된 안전 경계

Python은 의도만 승인한다. Helper는 실제 최신 노드/계보/자손/action/epoch와
로컬 stop을 독립 검사한다. 인증된 permit은 request/nonce/전체 소유권, 대상 digest,
앱/빌드/패키지, 탐색 의미 및 목적지 계약, session/boot/connection/stop, 만료,
max_calls=1에 결합한다. secret은 RPC 요청에서 받아 신뢰하지 않는다.

호스트 JSONL은 필수 저장 실패를 전파한다. Helper SQLite는 고유 request/nonce/permit
claim과 DISPATCH_STARTED/CONSUMED를 한 transaction으로 먼저 영속 확정한다.
그 뒤 crash는 미실행으로 추정하지 않는다. 재시작/timeout/false/예외 후 재전송은 없다.
감사 원본은 append-only다. receipt 읽기는 권한을 되살리지 않는다.

검증한 live AccessibilityNodeInfo 참조만 한 번 호출한다. 부모/자식/형제/nearest/focus
치환, legacy 클릭 연결, 물리 fallback은 없다. ACTION_FOCUS를 추가하지 않는다.
빌드/런타임 OFF, 의미 미입증, 불완전 관찰 계약, hard stop이면 호출 0회다.
C4는 ACTION_EFFECT_CONFIRMED/EXPECTED_NAVIGATION_CONFIRMED를 만들지 않는다.
기존 생산 reconciliation만 방문 권한을 유지한다.

Home Monitor 여섯 대상은 모두 실행 불가다. 두 본체는 MIXED_ACTION_CONTAINER,
헤더는 의미 미입증 UNKNOWN_ACTIONABLE, 보안 세 제어는 STATE_MUTATION_CONTROL이다.
분류기에 이 label/resource를 특별 취급하는 규칙은 넣지 않는다.

단계 순서: C4-0 호환성 실증 → A 순수 모델/인증 → D 영속 저장/복구 →
C ACK/조회 → B 기본 OFF 실제 노드 경로. 각 단계의 검증 실패는 범위 내에서 수정하며
안전 계약 완화나 실기기 동작이 필요해지면 중단한다.

## C4 구현의 의도적인 활성화 제한

빌드 상수 BUILD_EXACT_ACTION_SUPPORT=false이며 설정/Gradle property로 뒤집을 수 없다.
런타임은 기본 OFF, 신뢰 session 없음, C5 readiness 전부 false다. RPC는 session key나
gate 설정을 받지 않는다. configureTrustedLocalSession은 신뢰된 프로세스 내부 조립 지점만
제공하며 production 호출 지점은 없다. 읽기 전용 요청으로 액션 허가를 만들 수 없다.
session은 승인 target digest 하나와 transaction 하나에 제한된다. 재연결은 인증을 폐기하며
session 자체도 monotonic clock 기준 최대 5초로 제한해 UTC 시각 역행으로 수명이 연장되지 않는다.
stopped 상태를 해제하지 않는다. 실제 사용을 위한 신뢰 issuer 연결과 C5 관찰 준비는 후속 검토 대상이다.

정확한 노드 실행은 별도 단일 작업자에서 처리하며 대기열을 쌓지 않는다. 로컬 stop과
dispatch claim은 동일 lock으로 순서를 확정한다. 원격 호스트 중단은 이미 시작된 호출을
소급 취소하지 않는다. 수동 재시도도 새 ID만으로 승인되지 않는다.
durable claim 직후 한 번 더 유효성/만료를 검사하고 실패 시 소비를 유지하며 호출하지 않는다.
어떤 호출 결과든 C4는 효과가 검증되지 않았으므로 후속 실행을 중단한다.

호스트 prepare는 필수 JSONL 저장/sync가 끝난 뒤에만 immutable packet을 반환한다.
전송/재전송 코드는 제공하지 않는다. receipt 조회는 정확히 등록된 원래 packet을 대조해
기존 영속 증거만 읽는다. ACK_EMITTED는 logcat 기록 시도를 의미하며 수신 확인이 아니다.
테스트 인증 키는 공개 합성 자료일 뿐이며 runtime key로 등록되지 않는다.
