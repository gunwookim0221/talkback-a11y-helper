# Phase 6D2R 결정 정렬 및 redirect 증거 계약

## 범위

- 기준: `integration/phase3-current-main`, `b156c4fc3803adce6fbabd8b6c4aa4f290bdc153`.
- 증거 수집과 SHADOW 판단만 수정한다. production 실행·종료·스크롤·방문·안전 정책은 유지한다.
- Android 소스, 기기, 시나리오, Phase 6D3A/6D3B를 사용하거나 변경하지 않는다.

## 전송 경계 감사

| 경로 | 관측 위치 | 처리 |
|---|---|---|
| SMART_NEXT, targeted focus, activation, BACK, swipe 등 | `AdbDevice._run_adb_command`의 `subprocess.run` 직전 | 기존 guard 통과 후 epoch 증가. 반환 실패·예외도 이전 관측 무효화 |
| 직접 좌표 탭 | `AdbDevice._tap`의 `subprocess.run` 직전 | 별도 native 경로도 동일하게 기록 |
| binary ADB 명령 | `AdbDevice._run_adb_binary_command`의 `subprocess.Popen` 직전 | 동일 분류 사용. PFD/content read는 읽기이므로 증가하지 않음 |
| logcat 정리·진단 캡처 | 별도 진단 subprocess | UI 전송이 아니므로 제외 |
| 초기 accessibility 사전 점검 | 실행 전 CLI 환경 설정 | 활성 6D 관측을 소비하는 runtime 경로가 아님 |

ADB forwarding wrapper에서는 epoch를 증가시키지 않아 실제 경계에서 한 번만 기록한다.
알 수 없는 native shell 전송은 보수적으로 무효화하지만 정확한 소유권을 꾸며내지 않는다.
Helper의 읽기 전용 요청, hierarchy transfer control/PFD read, lifecycle 진단 쿼리는 증가시키지 않는다.
물리 UI를 바꾸지 않는 명시적 history reset은 action epoch를 증가시키지 않는다. 별도 context revision으로 이전 planner 문맥을 만료시키며, 캡처 도중 reset도 검출한다.

## 관측과 시간 정렬

- `EvidenceClock.action_epoch`는 실제 native 전송 시도마다 단조 증가한다.
- `observation_epoch`는 캡처 당시 action epoch다. 별도의 observation sequence와 상관관계 scope를 보관한다.
- scope 토큰은 증거 상관관계에만 사용하며 production target identity에는 들어가지 않는다.
- step 수집의 실제 관측 구간과 기존 reconciliation hierarchy fallback 캡처에 provenance를 기록한다.
- 캡처 도중 action이 발생하거나, 이후 action/관련 관측이 발생하면 이전 증거는 현재 증거로 인정하지 않는다.
- 준비 시점과 최종 확정 시점 모두 검사한다. step 기반 decision watermark는 action epoch와 별개다.
- Food 검증 실패와 popup 클릭 실패는 외부 반환값이 False여도 native receipt로 검출된다.
- PRIMARY/SEQUENTIAL/TARGETED/FALLBACK/RECOVERY/OPTIONAL_EXPANSION/POPUP/TAB/OTHER와 request/action ID를 기록한다.
- 새 hierarchy 요청이나 UI action은 추가하지 않는다.

## 완료 증거와 선택 대상 증거

`completion_evidence_complete`는 기존 범위 완료 조건을 유지한다.
`selected_frontier_execution_evidence`와 `selected_frontier_execution_ready`는 특정 대상의 실행 준비 증거다.
두 값은 독립적으로 검증한다.

선택 대상 증거에는 frontier/state/edge/target, 실제 production planner proof,
Phase 5 FOCUS proof, exact resolver binding 및 presence proof, 관측/epoch/watermark,
state/substate, 실제 action 소유권과 정책 참조가 필요하다.

- graph novelty나 state 존재만으로 eligibility 또는 binding RESOLVED를 생성하지 않는다.
- 기존 controlled 경로의 실제 gate/resolver 결과와 실제 authorization context가 내준 FOCUS permit만 관측한다.
- 보호된 `phase5b_navigation.py`는 원문 그대로 유지한다. 정책·permit 소비 절차를 수정하지 않는다.
- provenance가 없는 raw snapshot에 현재 epoch를 붙이지 않는다. 기존 production 증거를 연결할 수 없으면 UNKNOWN으로 남긴다.
- 일치하는 현재 planner/safety/binding/presence 증거가 제공될 때만 post-action frontier에 전달한다.
- target 불일치, 누락, 오래된 관측, 정책/증거 참조 변경, pending recovery/action은 READY를 만들지 않는다.
- summary의 합성 사유는 `AGGREGATE_ONLY`로 표시하고 원래 frontier 사유 참조를 별도로 보존한다.

## 향후 dispatch 계약

`READY`는 현재 증거 상태이며 실행 권한이 아니다. 항상 `REQUIRES_DISPATCH_TIME_REVALIDATION`을 보관한다.
향후 6D3A는 기존 Phase 4 gate → exact resolver → Phase 5 FOCUS authorization → controlled collection → production reconciliation을 다시 통과해야 한다.
기존 planner가 다른 대상을 선택하면 redirect는 준비되지 않은 상태로 처리한다.
이 변경은 재획득·추가 I/O·redirect dispatch를 수행하지 않는다.

## 제한과 다음 검토

일반 수집에서 현재 planner/FOCUS/exact binding 증거가 없으면 UNKNOWN이 정상 결과다.
합성 오프라인 READY 테스트는 계약 검증이며 실제 기기 실행 허가를 의미하지 않는다.
다음 단계는 Sol의 읽기 전용 temporal alignment 및 6D3A 준비 상태 재검토다.


## 최종 오프라인 검증

- 전체 Python: **5,130 passed, 1 skipped**, 실패 0, 214.63초.
- Phase 6B/C1/C2/D1/D2 및 관련 recovery/popup/focus/visit/content/Phase5 회귀 묶음: **1,166 passed**.
- Food 전송 후 검증 실패, popup 클릭 실패, 기존 Phase5 firewall 차단, 단일 native 전송 계수, 새 관측, 여러 action, READY/UNKNOWN/STALE 및 독립된 completion/redirect 증거를 검사했다.
- 중간 전체 검증에서 보호된 Phase5 모듈 원문 보존 검사 1개가 실패했다. 테스트 기준은 변경하지 않고 관측 코드를 기존 controlled adapter로 옮겨 해결했다.
- 최종 검증 시작 후 소스·테스트 14개 파일의 SHA-256 불변을 확인했다.
- `git diff --check`: 통과. Android source diff: 없음.
- 실제 UI action 0, 추가 hierarchy 요청 0, 기기/시나리오 실행 0.
- 판정: `PHASE6D2R_ALIGNMENT_REPAIR_PASS`.
- `SAFE_FOR_6D2R_SOL_REVIEW=YES`. 활성 redirect 허가를 뜻하지 않는다.
