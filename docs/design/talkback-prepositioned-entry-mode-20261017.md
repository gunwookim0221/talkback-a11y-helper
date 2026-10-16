# 수동 진입 후 내부 탐색 모드

`RunSpec.entry_mode`와 `script_test.py --entry-mode`가 `AUTOMATED`(기본값)와
`PREPOSITIONED`를 지원한다. 현재는 CLI/RunSpec 기능이며 frontend/API 실행 옵션은
추가하지 않았다. 환경 변수로 모드를 추론하지 않는다.

```powershell
python script_test.py --serial SERIAL --mode full --language-mode current --entry-mode PREPOSITIONED --scenario life_home_monitor_plugin --output-dir out/manual_internal_validation
```

`PREPOSITIONED`는 하나의 시나리오를 명시적으로 선택해야 한다. 별도의 coverage-probe
탐색은 허용하지 않는다. 화면 켜기, 잠금 해제, 접근성 서비스 활성화, 앱 실행,
팝업 닫기, 원래 탭 복구, 카드 탭, crash 재실행과 자동 재진입을 수행하지 않는다.
기존 `AUTOMATED` 경로는 그대로 사용한다.

읽기 전용 preflight에서 연결, 화면/잠금 상태, TalkBack 서비스/PID, Helper 빌드 식별,
기존 transaction 및 exact-action 게이트 상태와 목적지를 검사한다. 목적지는 시나리오의
`prepositioned_destination` 계약으로 검증한다. 예상 package/activity와 현재 focus 창이
일치하고, 유일한 활성 계층 창에 독립적인 구조 resource ID 두 개 이상 및 의미 표식이
보이며 원래 목록 화면 표식이 없어야 `PASS`다. 증거 부족은 `AMBIGUOUS`, 불일치는
`FAIL`이며 두 경우 모두 자동 진입으로 전환하지 않는다.

`collection_flow.open_scenario()`의 진입 경계에서 목적지를 다시 확인한다. `PASS`를
기록한 뒤 기존 `stabilize_anchor`, post-open focus 수집, anchor 행, main-loop 상태 생성과
내부 탐색·스크롤·비교·종료 처리를 재사용한다. `pre_navigation_success`나
`trusted_entry_verified`를 임의로 참으로 만들지 않는다. 방문 인정 권한은 기존 production
reconciliation에만 있다.

이 모드는 포커스/스크롤 수집용이다. 실행 범위에 묶인 ADB guard는 읽기 전용 진단과
검증 후의 정상 포커스/스크롤만 허용한다. 클릭, 탭, 키 입력, 앱 실행 및 알 수 없는 명령은
전송 전에 중단한다. 직접 ADB 탭 경로도 같은 guard를 거친다. 이미 중단된 session은
후속 탐색·활성화 명령을 허용하지 않는다. `PrepositionedSafetyStop`은 일반 `except Exception`의
재시도·복구 처리에 흡수되지 않으며 CLI가 명시적으로 수집하고 종료한다.
중단 후에는 수동적인 읽기 전용 증거 마감만 허용한다. 차단된 transaction을
`BLOCKED_BEFORE_DISPATCH`/`executed=false`로 추가 기록하고 닫으며 ACK나 방문을 만들지 않는다.
앞선 실행이 포함될 수 있는 기존 transaction을 미실행으로 바꾸지 않고, 차단 요청에
별도의 자식 transaction과 정확한 request ID를 부여한다. 기존 실행 증거는 보존한다.

Home Monitor 계약은 `HomeMonitorMainActivity`, 내부 Security 표식과 구조 resource ID,
Life 하단 탭 부재를 사용한다. Away/Stay/Disarmed는 정상 TalkBack 포커스로 읽을 수 있다.
이들의 화면상 텍스트/selected/checked 증거가 변하면 중단한다. 포커스 속성의 변화는
보안 상태 변화로 간주하지 않는다. 화면상 증거는 authoritative 보안 상태 조회를
대체하지 않으므로 자동 진입의 기존 안전 제한은 해소되지 않는다.

모드, 사전 조건, 전송 허용/차단, post-entry handoff 및 종료는 실행별
`*.prepositioned.jsonl`에 추가 기록한다. 목적지 검증은 일반 evidence ledger에도 기록한다.
실제 결과는 post-closure 보충 증거이며 Scenario 31 canonical
`INCOMPLETE_SAFETY_LIMIT`와 `counts_as_pass=false`를 변경하지 않는다.

이번 단일 실기기 보충 검증에서는 목적지와 anchor 검증 후 traversal step 1 및 발화 수집이
완료됐다. 기존 overlay 확장 경로가 `More options`에 대한 `CLICK_TARGET`을 요청해 전송 전에
중단했다. 보안 버튼은 활성화하지 않았다. 내부 전체 탐색 완료와 제한 원인이 진입에만
있다는 결론은 아직 입증되지 않았다. 이 실행은 다시 시작하지 않았다.
보존된 실기기 실행은 중단 당시의 감사 마감까지 완료되지 않았다. 이 문제는 실행 후
읽기 전용 마감과 blocked-command 자식 기록으로 보완하고 오프라인 회귀로 검증했다.
실기기 원본을 사후 수정하거나 완료된 감사로 재분류하지 않는다.
