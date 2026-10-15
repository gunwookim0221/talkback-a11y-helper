# Phase 5D-C5 관찰·검증 계약

## 범위와 승인

C5는 승인된 정확한 대상 액션의 **사후 증거**를 검증한다. 액션을 승인하거나 재시도하지 않으며 방문·커버리지·시나리오 PASS를 기록하지 않는다. C4의 39개 사전 조건, `HIT_OWNER_AMBIGUOUS`, 기본 OFF 빌드/런타임 게이트와 영속 hard stop을 유지한다. 기기 설치·설정 변경·실기기 액션 없이 합성·보존 자료·Robolectric으로 검증한다.

Home Monitor의 의미 및 보안 격리는 아직 입증되지 않았다. C5 결과로 첫 클릭의 안전성을 소급 승인할 수 없다. Scenario 31은 REJECT, Scenario 32는 NOT_STARTED이며 Phase 5/5C는 미완료다.

## 프로토콜과 소유권

- C4 요청 `talkback.exact-action.v2`, ACK `2`를 유지한다. ACK의 성공은 여전히 효과나 목적지 성공을 뜻하지 않는다.
- C5 증거는 `talkback.post-action.v1`의 별도 봉투다. 기존 transaction/request/permit/nonce/ownership 및 build/connection/boot/stop epoch를 복사·비교한다. 새 소유권 체계는 만들지 않는다.
- 선택적인 `ExactPostActionPlan`은 C4 등록 및 정확한 노드 해석 후, claim/API 호출 전에 커서와 정확한 참조 결합을 영속 기록한다. 기본 runtime에는 계획이나 관찰 readiness가 공급되지 않는다. RPC는 관찰기를 등록하거나 게이트를 켜지 못한다.
- 기존 SQLite C4 journal의 검증된 전체 해시 체인을 읽기 전용으로 내보낸다. Python은 체인, 원래 요청, 허가 조건, 소비 영수증, 실행 시작, 실제 호출 결과 및 ACK의 연결을 재검증한다. 해시는 로컬 무결성 증거이며 원격 출처를 인증하는 서명이 아니다. 신뢰 경계는 기존 C4의 신뢰된 로컬 Helper/호스트와 동일하다.
- 호스트는 기존 `DurableActionJournal`을 사용한다. 원시 export, 해석 결과, 목적지/금지 효과, 최종 판정은 append-only다. export와 최종 판정은 거래별 단 한 번 기록한다. 과거 C4 행은 수정하지 않는다.

## 관찰 및 시계

기본 효과 창은 5,000ms, 수신 유예는 1,000ms다. 커서 생성 시 고정한 deadline은 이벤트로 연장되지 않는다. 기본 창보다 짧은 창을 테스트할 수 있다. Android uptime의 생성시각·Helper 수신시각을 같은 영역에서만 비교한다. elapsedRealtimeNanos, wall clock 및 호스트 시각은 별도로 보존하고 서로 빼지 않는다. 재접속·재시작은 관찰을 중단한다. 동일 프로세스의 C4 효과 미검증 stop은 관찰을 해제하지 않으며, 관찰 결과도 그 stop을 해제하지 않는다.

Helper는 창 종료 콜백을 예약한다. 생성시각이 창 안이고 수신이 유예 이내인 지연 이벤트는 사용 가능하다. 창 밖/유예 이후 이벤트는 원문을 남기되 성공에 사용하지 않는다. 종료 거래를 다시 열지 않는다. 서비스 연결 변경 및 쓰기 실패는 관찰기를 오염 상태로 만들며 자동 복구·액션 재전송은 없다. 모든 관찰기 상태와 SQLite 기록은 C4와 같은 실행 잠금을 사용해 잠금 역전을 방지한다.

서비스 이벤트 설정에는 기존 유형에 더해 내용 변경·창 변경·스크롤·선택 이벤트를 추가한다. 활성 관찰기가 없으면 C5 경로는 원시 이벤트를 저장하지 않는다. 기존 production 이벤트 처리·방문 로직은 그대로 유지한다.

## 원시 자료와 상관관계

원시 이벤트에는 유형/uptime/수신시각, package/class/text/description, source provenance, 가능한 source ID/bounds/창/상태, producer sequence 및 epoch를 남긴다. 정규화는 별도 행이다. 중복을 표시하되 원시 복사본을 삭제하지 않는다.

상관관계는 `STRONG_MATCH`, `SUPPORTING_MATCH`, `AMBIGUOUS`, `NOT_MATCHED`다. 텍스트·동일 좌표·근접 시각·클릭 이벤트 한 건만으로 강한 일치를 만들지 않는다. 정확한 대상의 원래 노드 참조와 실제 이벤트 source가 같고 C4 구조/창/package가 일치할 때만 참조 결합을 사용한다. 부모·자식으로 대체하지 않는다. 소스가 없거나 부분 정보만 있으면 정확한 descriptor를 생성하지 않는다. 동일 source ID의 전역/재시작 안정성을 가정하지 않는다.

복수 클릭/접근성 포커스 액션 후보, 다른 거래 실행, 불일치 소유권 및 부모/자식 소스 불확실성은 모호성으로 남긴다. 첫 번째·가장 가까운·점수가 높은 후보를 선택하지 않는다. 일반 내용 변경이나 입력 포커스는 보조 증거다.

## 목적지와 금지 효과

목적지 계약은 C4의 이미 승인된 semantic intent digest에 결합한다. package/허용 activity/루트 구조 서명/필수 가시 마커/구조/context/출발 화면 서명/최소 관찰 수/settle/timeout 및 버전 있는 금지 효과 계약을 포함한다. activity/context가 없으면 승인하지 않는다. 범용 엔진에 앱별 문자열은 없다.

목적지는 최소 두 번, 기본 100ms 이상의 간격으로 일관되게 관찰되어야 한다. 마지막 관찰들이 모두 만족해야 하며 앞선 일시적 성공만 고를 수 없다. 원래 화면 서명은 목적지 텍스트가 남아 있어도 목적지로 인정하지 않는다. Helper probe에는 원시 계층, 구조/가시 마커, 창, 대상 존재 수, 독립 상태 selector의 결과와 거래/관찰 소유권을 남긴다. Python에서 원시 계층의 파생값을 다시 계산한다. 누락·중복 selector나 실패한 read는 보안 상태를 증명하지 못한다.

금지 계약은 형제 상태 컨트롤, 잘못된 modal/package/activity/구조 및 독립 상태 변경을 거부할 수 있다. 금지 텍스트 규칙은 **거부만** 하며 소스 식별이나 성공을 부여하지 않는다. 명백한 잘못된 효과는 hard-stop 증거다.

`FORBIDDEN_EFFECT_NOT_OBSERVED`와 `FORBIDDEN_EFFECT_PROVEN_ABSENT`는 다르다. 후자는 계약의 지정 채널에 대한 독립적·연속적 관찰 범위와 증거 참조가 명시되고 baseline/사후 probe 및 닫힌 창이 모두 완전할 때만 가능하다. 기본 관찰 가능성은 UNKNOWN이다. 두 화면에서 같은 라벨을 읽는 것만으로 중간 보안 상태가 변하지 않았다고 주장할 수 없다. 실제 Home Monitor의 독립적 관찰 채널은 이번 작업으로 입증하지 않았다. 합성 양성 사례의 완전 채널은 테스트 입력임을 명시한다.

## 판정과 전달

1. `ACTION_DISPATCH_CONFIRMED`: 영속 시작/소비/정확한 대상/소유권/ACK가 일치하고 실제 호출이 1회 시도됨. 반환 false도 호출 시도 증거일 수 있다.
2. `ACTION_EFFECT_CONFIRMED`: 충분히 대상과 연관된 관측 효과. true 반환 자체는 효과가 아니다.
3. `EXPECTED_NAVIGATION_CONFIRMED`: 위 두 조건, 승인된 안정 목적지, 금지 효과 관찰 가능성, 완전한 영속 감사까지 모두 만족.

결과는 `NAVIGATION_CONFIRMED`, `DISPATCH_ONLY`, `NO_EFFECT`, `EFFECT_CONFIRMED_WRONG_DESTINATION`, `FORBIDDEN_EFFECT`, `AMBIGUOUS_EFFECT`, `POST_ACTION_TIMEOUT`, `AUDIT_FAILURE`, `UNKNOWN_EXECUTION_STATE` 모델을 갖는다. C4 실패 코드와 상태도 보존한다. false 반환은 자동 재시도하지 않으며 목적지 성공을 주지 않는다. true+무효과는 NO_EFFECT, 잘못된 효과는 거부, 부분/재시작/감사 실패는 성공 불가다.

최종 판정 쓰기 전에 공개 replay는 navigation 성공을 반환하지 않는다. 최종 쓰기가 실패하면 메모리의 성공을 버린다. handoff는 해시 검증된 최종 감사가 있을 때만 증거를 제공하며 `visit_authority=false`, `requires_production_focus_reconciliation=true`를 고정한다. production reconciliation만 방문 권한을 가진다. replay는 원시/기존 감사를 변경하지 않는다.

## C6로 전달하는 제한

C5 인프라는 오프라인/합성 C6 검증용이다. 서비스 수신·필요 이벤트·커서·sequence·감사 쓰기·현재 epoch·비경쟁 거래·승인 계약·상태 관찰 범위 모두가 readiness 조건이다. 현재 production runtime의 `c5_ready` 및 모든 액션 게이트는 OFF로 유지한다. 실제 이벤트의 source 가용성, 독립 보안 상태 채널 및 Home Monitor 사전 의미/격리 증거는 별도 C6 과제이며 실기기 클릭 승인을 뜻하지 않는다.

재현 도구:

- `python -m tools.exact_c5_fixture`: 공개 가능한 범용 합성 자료만 생성.
- `python -m pytest tests/test_exact_c5.py -q`: 단위/경계/소유권/목적지/금지 효과/재시작/감사 테스트.
- `ExactPostActionTest`, `ExactActionEngineTest`: 실제 SQLite writer, 읽기 전용 계층 파생, 기본 OFF 및 mock 액션 연결 검사.
- `python -m tools.exact_c5_replay --output out/<새 디렉터리>`: 보존 로그/B3, 합성 양성, 실제 Kotlin export의 Python 재검증 및 성능 측정. 보존 파일이 없으면 성공을 꾸며내지 않고 실패한다. 개인 기기 원문은 out에만 보존하고 커밋하지 않는다.
