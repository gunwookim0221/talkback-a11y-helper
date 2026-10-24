# RF2R3 readiness 근거 결합 범위

## 범위와 결과의 의미

SHADOW만 변경한다. 최종 판정은 기존 ProductionRedirectProofProvider와 RedirectEvidenceBundle / evaluate_redirect_readiness가 수행한다. 여기의 일치 검사는 frame.evidence_current를 위한 원천 결합이며 실행 승인이나 별도 READY 판정기가 아니다. ACTIVE, accounting, scheduler, Phase5 정책은 변경하지 않는다.

pre-capture는 지정한 원천의 primitive equality seal만 만든다. provider, resolver, evaluator, deepcopy, JSON/해시 계산, 파일/기기 I/O를 수행하지 않는다. 전체 runtime 또는 전체 history row를 복제하지 않는다. 동기식 collector 전후를 비교하며 collector는 한 번만 호출한다. registry/provider 평가와 token 해시는 collector 이후 실행한다.

## Coverage 표

모든 runtime 원천은 collector 중 변경 가능하다. 아래 A는 immutable token, B는 같은 decision에 결합된 실제 production provider의 사후 재계산이다. C는 근거 누락/한도 초과 시 UNKNOWN이다.

| 근거 authority | collector 중 변경 | token 범위(A) | 사후 근거(B) / 결합 규칙 | 불일치 | 근거 누락 |
|---|---|---|---|---|---|
| Helper request | YES | helper_source: phase5c_primary_action_request_id, smart_nav_req_id; observation ownership, run/scope | 원문 ID의 exact equality; 파생 status만 비교하지 않음 | MISMATCH/UNKNOWN, non-ready | UNKNOWN |
| Helper ACK | YES | command_ack_status, command_ack_result, command_ack_raw_result | 동일 row request/scope의 원문 ACK exact equality; timeout 차단 우선 | UNAVAILABLE/UNKNOWN, non-ready | UNKNOWN |
| planner | YES | planner_history: ledger scenario/target/step, visits, attempts, stale alias keys, allowed IDs, reconciliation history의 4개 필드, scroll/transition/no-progress; raw_provider_sources, registry_generation | plan_shadow가 동일 observation/state/inventory 원천에서 재계산; frontier와 공통 proof 비교 | evidence_current=False | UNKNOWN |
| Phase4 gate | YES | 위 planner 원천, runtime_safety, provider_budget, Helper/lifecycle, raw focus/viewport | 기존 execution_gate 결과를 동일 frame/target의 proof provenance로 결합 | non-ready | UNKNOWN |
| Phase5 read-only safety | YES | raw semantic nodes, overlay, context, capability; state/substate의 원천; safety_policy/reference | 기존 SafetySession(mode=shadow).assess; 동일 candidate 및 frame provenance; permit 없음 | non-ready | UNKNOWN |
| binding | YES | bounded tree 원문 구조/semantics, frontier target, observation, registry generation | 기존 exact resolver가 동일 입력으로 재계산; proof_refs와 frame provenance | non-ready | UNKNOWN |
| presence | YES | binding과 동일, 모든 경쟁 node 포함 | resolver의 동일 candidate/observation 결과; capture ID만 신뢰하지 않음 | non-ready | UNKNOWN |
| frontier | YES | frontier identity/priority/type/substate/condition; decision_eligibility; production_terminal | selected_redirect_hint와 production provider target의 공통 비교 | non-ready | UNKNOWN |
| inventory/cache | YES | source_step/state/complete/observation_ref 및 source reference; tree content seal | 캐시 observation이 동일 row/decision capture임을 재검사. cached candidates는 provider 입력이 아니며 presence 근거로 쓰지 않음 | non-ready | UNKNOWN |
| state/substate/context | YES | record.state, row/owner context, plugin/entry evidence, raw source, registry generation, summary의 3개 계약 필드 | graph/discovery refs의 identity domain과 관측 tuple, provider semantic_substates 일치 | non-ready | UNKNOWN |
| observation | YES | decision_observation, row_observation, source step, row step_index/step fallback, timestamp, capture/run identity | provider가 scope/observation/epoch/context를 frame과 재대조 | non-ready | UNKNOWN |
| clock/epoch/watermark | YES | lock 아래 최소 clock tuple, decision watermark/ID, observation tuple | post clock 동일 scope/context 및 non-decreasing cursor; 이전 decision 원천이 동일할 때만 정상 advance 허용 | non-ready | UNKNOWN |
| lifecycle | YES | 기존 raw lifecycle_token | 기존 pre/post projection, BLOCKED 우선; CLEAR는 recorder/PID 연속성 필요 | BLOCKED/UNKNOWN | UNKNOWN |
| overlay | YES | raw_provider_sources의 overlay 및 tree | pre/post exact equality 필요; pre block의 사후 소실도 일치 실패 | non-ready | UNKNOWN |
| recovery | YES | runtime_safety의 기존 pending 필드 | pre/post exact equality; 기존 projection 및 gate | non-ready | UNKNOWN |
| transition | YES | runtime_safety/post_realign/stop 및 pending_transition, planner latest | pre/post exact equality; 기존 projection 및 gate | non-ready | UNKNOWN |

## 원천 한도 / 누락 처리

metadata 기존 한도는 유지한다. 추가 source seal은 group당 primitive 65,536개, container 2,048개, 깊이 16, string 262,144자 및 총 string 1,048,576자를 한도로 한다. 한도 초과, 비지원 타입, 실제 raw read 예외는 token UNKNOWN이며 collector 실행 및 결과는 유지된다. 보장할 수 없는 큰 history/registry는 낙관적으로 READY 처리하지 않는다. 성능 수용 범위는 오프라인 검증이며 실제 기기 latency는 아직 검증하지 않았다.

노드는 resolver와 state/safety가 소비하는 원문 구조이므로 bounded primitive content를 결합한다. 변경 가능한 node를 unchanged capture ID / object ID / length로만 신뢰하지 않는다. source seal은 container 타입과 bool/int 타입을 구분하고 metadata 비교도 exact type을 요구한다. True==1 등의 Python 동등성이 변경된 safety/eligibility 근거를 숨길 수 없다. row/context/history 원천에서는 key 부재와 명시적 None도 구분한다. get(key, default)의 의미가 바뀌어 step/coverage/scenario fallback이 사후 개선되는 경우를 차단한다. planner history는 소비하는 필드만 결합하고, registry observation/continuity는 이미 저장된 immutable 문서를 사용한다. 새 serialization/equality 평가를 pre-capture에서 호출하지 않는다.

Helper generation/ACK 독립 request sequence 필드는 현재 이 row readiness projection에 존재하지 않는다. 가상의 필드는 만들지 않는다. 기존 request ID와 observation의 ownership/scope/epoch를 결합한다. ACK result/raw result가 모두 누락된 경우에도 UNKNOWN으로 처리해 필수 원천의 누락을 낙관적으로 통과시키지 않는다. 타임아웃 등 기존 차단 근거는 사후 MOVED로 소거할 수 없다. 원문은 trace.conditions.helper_evidence에 pre/post/effective/reason으로 남는다. UNKNOWN은 기존 evaluator에서 UNKNOWN을 유지하도록 authority proof를 낙관적으로 만들지 않는다.

planner/gate/safety 알고리즘 정의는 runtime 증거가 아니다. 반면 cached default_config dict는 safety_policy 및 safety_policy_reference, cache_current로 결합한다. cache_clear 후 provider가 다른 원천을 다시 로드하는 경우도 사전 근거로 승인하지 않는다. action_safety의 작은 원천 공개 변수는 기존 로딩 시에만 설정한다. pre-capture는 sys.modules의 이미 로드된 원천을 읽을 뿐 import/config 로딩/I/O를 하지 않는다. 정책 미로드 상태는 근거 누락 UNKNOWN이며 collector 중 로드되어도 이전 decision을 READY로 개선하지 않는다. 실제 proof는 token으로 결합된 원천에 대해 사후 계산한다. 새로운 runtime authority/input을 추가할 때는 _PHASE6D3A_PROVENANCE_AUTHORITIES와 이 표, mutation regression을 함께 갱신해야 한다. 임의 monkeypatch/악성 object.__setattr__까지 방어하는 계약은 아니다.

## 보존한 계약

collector=1, production result parity, dispatch=0, extra device I/O=0, budget/failure streak 변경 없음. lifecycle temporal merge, foreign scope/observation 차단, provider/evaluator 포함·collector 제외 latency를 유지한다. 기존 ACTIVE orchestration 본문은 checkpoint와 동일해야 한다.

RF3 / targeted live SHADOW / ACTIVE 모두 승인하지 않는다. commit/push 및 기기 실행은 하지 않는다.
