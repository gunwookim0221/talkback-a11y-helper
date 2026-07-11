# TalkBack Traversal Engine RCA V2 — Independent Technical Review

작성일: 2026-07-11
검토 대상: `talkback-traversal-engine-root-cause-analysis-v2.md`
검토 원칙: 코드·테스트·설계 변경 없이, 현재 RCA를 반증하는 관점에서 artifact와 소스를 재검증

## 1. Executive Review

### 최종 판단

**Can Implementation Start? — NO**

현재 RCA는 최신 Safe의 scenario-start abort와 이전 Safe의 under-coverage를 잘 포착했다. 특히 다음 사실은 강하게 유지된다.

- 최신 Safe는 card tap 후 실제 Safe WebView에 진입했고 `pre_navigation success`까지 도달했다.
- exact anchor query `세이프 버튼`의 action 대상이 full-screen `primary` ancestor로 바뀌었고, 실제 focus도 빈 `primary`에 놓였다.
- anchor verification은 두 번 실패했고 `fallback_candidate_absent`로 traversal 전에 종료됐다.
- 이전 Safe에서 XML/Helper에는 `도움 요청 연습하기`, `도움 요청`, empty-state 관련 node가 있었으나 actual-focus 결과는 소수에 그쳤다.
- Runner의 working row에는 actual focus와 representative가 서로 다른 의미로 공존하며, persistence 전 fingerprint·STEP END·일부 consumed 상태는 representative 기준으로 계산된다.
- 최신 summary는 card 발견·screen 진입·anchor abort를 `optional Safe card not found`로 잘못 요약한다. 이는 RCA가 충분히 강조하지 못한 별도의 aggregation 오류다.

그러나 RCA의 가장 넓은 결론을 지지하는 핵심 정량 근거는 깨졌다.

1. `moved + static actual focus`는 동일 SMART_NEXT 직전/직후의 원자적 비교가 아니다. 연속 XLSX main row의 endpoint 비교이며, 중간 overlay·realign·selection을 생략한다.
2. `representative != actual focus`도 같은 시점 비교가 아니다. `actual_focus_*`는 representative 선택 또는 focus realign 이전 snapshot일 수 있다.
3. Motion Sensor step 8은 XLSX에서 actual focus가 header로 남지만, 같은 step 로그에는 representative `100%`로 focus realign 성공이 명시된다. 이 행을 move mismatch로 세는 것은 반례다.
4. 이전 Safe step 1에서 Helper는 `세이프 버튼`의 bounds에 실제 focus 도달, focus event, announcement를 확인했다. 따라서 이 사례의 `SMART_NAV=moved`는 false positive가 아니다.
5. 현재 소스와 실행 artifact 사이의 exact commit/build provenance가 없다. 특히 Helper 핵심 파일은 현재 dirty 상태이므로 현 소스 구조를 과거 바이너리의 직접 원인으로 동일시할 수 없다.
6. V5의 구조적 over-credit 가능성은 확인되지만, 첨부 artifact에 V5 실행 결과가 없어 “이번 문제를 실제로 놓쳤다”는 operational claim은 입증되지 않았다.

따라서 현재 RCA는 **강한 Safe anchor incident analysis**이지만, **Runner/Helper/Audit 전체 변경의 설계 기준으로 사용할 만큼 공통 원인과 규모가 확정된 RCA는 아니다.**

### 신뢰도 점수

| 평가 항목 | 점수 | 검토 의견 |
|---|---:|---|
| Evidence completeness | 66/100 | Safe anchor chain은 충분하나 cross-plugin atomic focus evidence, V5 산출물, build provenance가 부족하다. |
| Logical consistency | 57/100 | 일부 구간에서 endpoint equality를 action-level static focus로, symptom을 root cause로 승격했다. |
| Alternative hypothesis coverage | 34/100 | container merge, WebView focus reset, realign 후 stale row, XML/TalkBack 의미 차이를 충분히 배제하지 않았다. |
| Implementation readiness | 38/100 | 공통 수정 범위의 필요성과 우선 원인이 아직 분리되지 않았다. |
| Regression risk analysis | 63/100 | 영향 영역은 넓게 식별했지만, 그 넓이가 곧 수정 필요 범위라는 증거는 아니다. |
| Architecture confidence | 55/100 | row lifecycle 및 audit 위험은 강하지만 Helper false-positive와 identity causality는 미확정이다. |
| **Overall confidence** | **52/100** | 평균 반올림. 현상 설명용으로는 유용하나 전체 구현 기준으로는 불충분하다. |

## 2. Evidence Validation

### 2.1 주요 결론 재평가

| RCA 주요 결론 | 검증 등급 | 검증 결과 | 원인 계층 재분류 |
|---|---|---|---|
| Safe card tap 후 Safe screen transition 성공 | **CONFIRMED** | WebView `SmartThings Safe plugin` 관측 후 pre-nav 성공. [latest runner](../../qa_frontend_runs/batch_20260711_103140/device_SM-F741N_R3CX40QFDBP/runner.log#L168) | Context fact |
| exact title query가 `primary` ancestor를 action target으로 사용 | **CONFIRMED** | query는 `^세이프 버튼$`, attempted node는 `primary`, class `View`, full-screen bounds. [latest runner](../../qa_frontend_runs/batch_20260711_103140/device_SM-F741N_R3CX40QFDBP/runner.log#L171) | **Primary Root Cause** of this Safe abort |
| `anchor mismatch`가 root cause | **REFUTED as root cause** | mismatch는 wrong target에 focus된 뒤 verification이 실패한 결과다. | **Symptom** |
| `anchor not stable` | **CONFIRMED as observation** | 두 verification cycle에서 stable anchor를 얻지 못했다. [normal log](../../qa_frontend_runs/batch_20260711_103140/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260711_103152.normal.log#L102) | **Symptom** |
| fallback이 explicit match 후 verification 실패에 재진입하지 않음 | **HIGH CONFIDENCE** | fallback candidate 계산은 `best is None`일 때만 수행된다. [anchor logic](../../tb_runner/anchor_logic.py#L669) | **Secondary Root Cause / Contributing Factor** |
| `fallback_candidate_absent`가 root cause | **REFUTED as root cause** | 상위 selection/verification/fallback state의 결과 코드다. | **Symptom** |
| ancestor promotion 자체가 defect | **PLAUSIBLE, not confirmed** | icon/leaf action을 clickable parent로 올리는 것은 정상 설계일 수 있다. 문제는 Safe의 full-screen empty ancestor가 성공으로 수용된 구체 사례다. [target finder](../../app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yTargetFinder.kt#L208) | Potential contributing factor |
| 이전 Safe under-coverage | **CONFIRMED** | V7은 expected 13, covered 4, unknown 9이며 XML에는 practice/SOS가 존재한다. [coverage](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260708_235625.focusable_coverage.json#L7), [XML](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260708_235625/home_safe_plugin/xml_dumps/000_step_001_entry.xml) | **Symptom** |
| 이전 Safe step 1의 SMART_NEXT moved가 false positive | **REFUTED** | Helper는 title bounds match, focus commit, `FOCUS_UPDATE`, 발화를 확인했다. [logcat](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/logcat.txt#L43797) | Not a defect in this step |
| 연속 actual focus 동일이면 movement가 없었음 | **REFUTED as a general inference** | Safe step 1→2 사이에 options overlay와 realign이 존재한다. 같은 endpoint라도 중간 focus 변화가 있었다. [runner](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/runner.log#L243) | Measurement artifact |
| representative/actual divergence가 곧 focus mismatch | **REFUTED as a general inference** | Motion step 8은 persisted actual이 header지만 같은 step에서 `100%` realign 성공. [full-run runner](../../qa_frontend_runs/batch_20260711_094543/device_SM-F741N_R3CX40QFDBP/runner.log#L3540) | Mixed-phase row artifact |
| representative state가 fingerprint와 STEP END에 반영 | **CONFIRMED in current source and Safe log** | working row는 representative로 덮이고, persistence 전에 fingerprint와 STEP END가 생성된다. [collection flow](../../tb_runner/collection_flow.py#L10001), [quality phase](../../tb_runner/collection_flow.py#L13877), [Safe STEP END](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/runner.log#L233) | **Contributing Factor**, causal scope HIGH CONFIDENCE |
| Safe practice candidate가 actual focus 없이 consumed | **HIGH CONFIDENCE** | step 1은 current title과 representative mismatch를 기록한 뒤 practice cluster를 consumed하고 PASS로 진행한다. [runner](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/runner.log#L227) | **Primary Root Cause candidate** for Safe under-coverage |
| 동일 traversal defect가 모든 plugin에 존재 | **PLAUSIBLE** | mixed-phase rows는 공통이나, 각 plugin의 divergence가 실제 landing failure인지 realign/merge인지 분해되지 않았다. | Unproven common root cause |
| Helper identity weakness가 이번 현상의 원인 | **PLAUSIBLE** | weak identity 구조와 label-history 위험은 코드상 존재하나 Safe abort/under-coverage와의 causal edge가 제시되지 않았다. | Potential contributing factor |
| `COMMON_ANCHOR_REGRESSION` | **PLAUSIBLE** | Safe와 Pet Care가 같은 top-level reason으로 abort한 것은 확인되지만, 같은 target substitution인지 및 어느 변경이 회귀를 만들었는지는 미확정이다. | Behavioral symptom cluster |
| V5가 이번 artifact를 false visited 처리 | **PLAUSIBLE operationally / HIGH CONFIDENCE structurally** | STEP END와 contained text를 VISITED로 만드는 코드는 확인된다. 하지만 첨부 run에는 V5 report가 없다. [V5 core](../../tools/audit_v5_traversal_core.py#L634) | Audit design risk |
| Probe가 Safe 누락을 검증하지 못함 | **CONFIRMED** | required count와 probe candidate가 0이었고 실제 plan도 비었다. [probe plan](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260708_235625.coverage_probe_plan.json) | **Secondary Root Cause** of false assurance |
| Runner/Helper/Audit 전체 수정이 필요 | **SPECULATION** | 세 영역에 각각 위험은 있으나 동일 원인이 세 영역의 변경을 모두 필요로 한다는 증거는 없다. | Scope conclusion, not root cause |

### 2.2 Cross-plugin 정량표의 유효성

RCA는 Full Run에서 `127 moved`, `17 moved + static actual focus`, `67 representative/actual divergence`를 공통 결함 증거로 사용했다. 이 중 moved 행 수는 관측값이지만 뒤의 두 수치는 defect count로 사용할 수 없다.

- XLSX `actual_focus_*`와 `representative_*`는 한 시점의 두 sensor reading이 아니다. actual snapshot 이후 representative selection 또는 realign이 발생한다.
- Energy와 Family Care의 동일-focus pair 사이에는 persisted overlay row가 각각 6개, 9개 존재한다.
- Motion step 7→8은 main row 사이 overlay가 없지만 step 8 안에서 `100%` focus realign이 성공한 뒤에도 persisted `actual_focus_*`는 earlier header snapshot을 보존한다.
- TV 등의 remaining endpoint-static 사례도 Helper commit 시점, Runner snapshot 시점, optional realign 이후 시점이 join되지 않아 false-positive인지 snap-back인지 확정할 수 없다.

따라서 표가 증명하는 것은 다음뿐이다.

> 여러 plugin의 persisted row에 서로 다른 phase의 actual-focus snapshot과 representative state가 함께 존재한다.

이는 **row lifecycle/observability 문제의 강한 증거**이지만, `SMART_NEXT false positive 17건` 또는 `physical focus mismatch 67건`의 증거는 아니다. [Full Run XLSX](../../qa_frontend_runs/batch_20260711_094543/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260711_094553.xlsx)

### 2.3 Root Cause와 Symptom 재분류

| 분류 | 항목 | 신뢰도 |
|---|---|---|
| Symptom | XML 대비 actual-focus coverage 부족 | CONFIRMED |
| Symptom | anchor mismatch / anchor not stable | CONFIRMED |
| Symptom | low_confidence_anchor_start / fallback_candidate_absent | CONFIRMED |
| Symptom | repeat_no_progress | CONFIRMED |
| Symptom | 최신 run이 traversal 전 종료 | CONFIRMED |
| Contributing Factor | actual snapshot, representative, realign 결과가 한 row에서 phase 구분 없이 소비됨 | HIGH CONFIDENCE |
| Contributing Factor | representative candidate가 actual focus edge 없이 cluster-consumed 되는 Safe 경로 | HIGH CONFIDENCE |
| Contributing Factor | explicit match 존재 시 fallback candidate가 구성되지 않는 state path | HIGH CONFIDENCE |
| Contributing Factor | Coverage Probe required/eligible 분류가 Safe missed candidates를 0으로 만듦 | CONFIRMED |
| Contributing Factor | Helper/Runner/Audit identity 정의 불일치 | CONFIRMED structurally, causal role PLAUSIBLE |
| Primary Root Cause | 최신 Safe에서 matched title이 full-screen empty `primary`로 action-target substitution된 뒤 성공 처리됨 | HIGH CONFIDENCE |
| Primary Root Cause candidate | 이전 Safe에서 focus와 불일치한 representative가 consumed/visited progression에 기여 | HIGH CONFIDENCE, exact loss share unquantified |
| Secondary Root Cause | verification 실패 후 useful fallback 경로가 구성되지 않음 | HIGH CONFIDENCE |
| Secondary Root Cause | summary/audit가 abort와 no-candidate, pass와 low coverage를 충분히 구분하지 않음 | CONFIRMED |
| 미확정 원인 | Helper가 실제 이동 없이 moved를 반환 | PLAUSIBLE in some runs, refuted for cited Safe step |
| 미확정 원인 | weak focus identity가 현재 Safe miss를 유발 | PLAUSIBLE |
| 미확정 원인 | Safe와 Pet Care가 동일 anchor root cause를 공유 | PLAUSIBLE |

### 2.4 RCA가 놓친 confirmed aggregation 오류

최신 Safe 로그는 card 발견, tap, Safe WebView 진입, pre-nav 성공, anchor abort를 보여준다. 그러나 `summary.json`은 scenario를 `NOT_AVAILABLE`, 이유를 `optional Safe card not found`로 기록한다. [latest summary](../../qa_frontend_runs/batch_20260711_103140/device_SM-F741N_R3CX40QFDBP/summary.json#L79)

이것은 단순 표현 차이가 아니다. scenario open failure의 실제 stage를 소실해 downstream audit이 discovery failure로 오진할 수 있다. 현재 RCA의 `AUDIT_GAP` 방향은 맞지만, 실제로 확인된 가장 직접적인 최신 aggregation 오류는 이 summary misclassification이다.

이전 Safe도 `repeat_no_progress`, coverage 30.8%인데 batch state와 scenario status는 `passed`다. 다만 shadow verdict는 `SHADOW_REVIEW`이므로 “Audit이 아무 신호도 내지 않았다”는 표현은 과장이다. [previous summary](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/summary.json#L1)

## 3. Alternative Hypotheses

현재 RCA가 배제하지 못한 반대 가설은 다음과 같다.

1. **TalkBack container merge가 정상 동작이다.** XML leaf 여러 개가 하나의 container announcement로 합쳐지는 것은 접근성 의미상 정상일 수 있다. XML object 수와 TalkBack focus stop 수는 원래 같지 않을 수 있다.
2. **XML `focusable=true`는 TalkBack direct-focus 보장이 아니다.** WebView virtual node의 focusability, traversal order, accessibility importance는 UIAutomator snapshot만으로 완전히 재현되지 않는다.
3. **Representative는 의도적으로 actual focus와 다른 planning object다.** 차이 자체는 defect가 아니며, defect 여부는 representative가 어떤 lifecycle 결정을 바꾸는지로 판단해야 한다.
4. **Endpoint가 같아도 movement는 실제로 있었다.** overlay, focus realign, WebView reset 또는 auto-snap 후 같은 node로 돌아올 수 있다. 이전 Safe step 1→2가 실제 반례다.
5. **Helper success 후 focus가 일시적으로 이동했다가 되돌아왔을 수 있다.** 이 경우 Helper false positive가 아니라 focus stability 또는 later action 문제다.
6. **Runner의 `actual_focus_*`가 final focus가 아니다.** Motion step 8처럼 snapshot 후 realign 성공이 row에 반영되지 않을 수 있다.
7. **Ancestor promotion은 정상 action routing일 수 있다.** leaf가 직접 action을 지원하지 않을 때 clickable ancestor 사용은 필요하다. Safe의 문제를 promotion 전체의 결함으로 일반화할 수 없다.
8. **Safe DOM/hierarchy가 run 간 달랐을 수 있다.** 7월 8일 broad WebView fallback과 7월 11일 exact title→primary 성공 차이는 코드 회귀 외에도 hydration, focus state, DOM actionability 차이로 설명 가능하다.
9. **Pet Care의 동일 stop reason은 동일 root cause를 뜻하지 않는다.** exact matched node, resolved node, post-focus identity가 Safe와 같은지 제시되지 않았다.
10. **동일 text의 다른 bounds가 반드시 다른 semantic object는 아니다.** sticky header, duplicated WebView virtual node, responsive clone일 수 있다.
11. **V5 over-credit는 input-source 의존적이다.** normal.log의 representative STEP END와 XLSX의 restored actual visible을 함께 소비하므로 실제 verdict는 source ordering과 candidate match에 달려 있다.
12. **Coverage 30.8%는 direct TalkBack visit rate가 아니다.** canonical inventory는 focus payload, Helper snapshot, actionable descendant를 혼합하며 taxonomy도 대부분 OPTIONAL이다.
13. **현재 소스가 artifact 실행 코드와 동일하다는 보장이 없다.** runner version은 같아도 exact git SHA와 Helper APK source SHA가 artifact에 없다.
14. **screenshot/crop은 focus 이벤트의 원자적 증거가 아니다.** capture 전후에 focus가 바뀔 수 있으며 crop filename도 earlier focus label을 사용할 수 있다.

## 4. Top 10 Dangerous Assumptions

| 순위 | 위험한 가정 | 왜 위험한가 | 현재 판정 |
|---:|---|---|---|
| 1 | 연속 XLSX actual identity가 같으면 SMART_NEXT가 실제로 움직이지 않았다 | 중간 overlay/realign과 intra-step focus 변화를 제거한다. | **REFUTED** |
| 2 | representative와 actual focus가 다르면 항상 defect다 | 서로 다른 phase와 역할의 값을 비교한다. container/planning abstraction일 수 있다. | **REFUTED as universal rule** |
| 3 | XML candidate 하나는 TalkBack direct-focus stop 하나여야 한다 | WebView와 TalkBack merge semantics를 무시한다. | **SPECULATION** |
| 4 | `anchor mismatch`가 root cause다 | wrong target resolution 또는 unstable focus의 downstream symptom이다. | **REFUTED** |
| 5 | 같은 abort reason을 가진 plugin은 같은 root cause를 가진다 | reason taxonomy가 거칠고 resolved target evidence가 없다. | **PLAUSIBLE only** |
| 6 | 7월 8일 성공, 7월 11일 실패는 최근 코드 regression이다 | exact build SHA, DOM state, repeated-run 재현이 없다. | **SPECULATION** |
| 7 | weak focus identity가 이번 Safe failure를 만들었다 | 구조적 위험과 incident causality를 혼동한다. | **PLAUSIBLE only** |
| 8 | Audit V4/V5/Probe 모두 이번 defect를 실제로 놓쳤다 | Probe/summary 근거는 있으나 V5 실행 산출물은 없다. Shadow는 REVIEW를 냈다. | **Partially confirmed** |
| 9 | `pre_navigation success`는 anchor DOM과 focus가 안정됐다는 뜻이다 | screen entry와 anchor readiness는 다른 조건이다. | **REFUTED** |
| 10 | 세 subsystem에서 위험이 보이면 세 subsystem 모두 수정해야 한다 | 영향 범위와 필수 수정 범위를 동일시한다. | **SPECULATION** |

## 5. Additional Experiments Required

아래는 결론 확정을 위한 증거 요구사항이다. 구현 방법이나 수정안이 아니라, 현재 가설을 판별하기 위한 실험 조건이다.

| 미확정 질문 | 필요한 로그/계측 | 필요한 실기기 테스트 | 확정 기준 |
|---|---|---|---|
| SMART_NEXT false positive가 실제 존재하는가 | 동일 request-id의 pre-focus, action target, Helper commit focus, Runner read focus, 이후 realign/overlay를 단일 timestamp ledger로 기록 | static으로 분류된 Motion/TV step을 반복 재현 | action 직전과 commit 직후 physical identity가 같고 중간 event도 없을 때만 false positive 확정 |
| focus가 이동 후 snap-back하는가 | focus event stream과 +100/+300/+1000ms identity | 화면 녹화와 TalkBack 실제 swipe/Helper action 동시 수행 | commit 시 target 도달 후 later source로 복귀하면 snap-back 확정 |
| representative divergence가 defect인가 | representative 선정 시점, realign attempt/result, final focus를 분리한 trace | Safe, Motion, TV에서 representative가 다른 행 재현 | final focus가 representative alias와 불일치한 채 candidate가 consumed될 때만 defect 확정 |
| Safe practice/SOS가 TalkBack direct-focus 가능한가 | Android accessibility event와 Helper candidate identity | 수동 TalkBack 순방향/역방향 traversal로 각 node 도달 여부 확인 | 수동 TalkBack도 도달하지 못하면 XML 대비 miss를 engine defect로 볼 수 없음 |
| Safe anchor failure가 deterministic한가 | matched node와 resolved action node 전체 path, bounds, action support | 동일 APK/Runner/초기 상태에서 다회 반복 | `세이프 버튼→primary→mismatch`가 반복되면 incident root cause 확정도 상승 |
| Pet Care가 Safe와 같은 root cause인가 | Pet Care requested/matched/resolved/post-focus identity | 같은 build에서 Safe/Pet Care 연속 반복 | 둘 다 full-screen/empty ancestor substitution이면 common anchor cause 확정 |
| code regression인가 latent nondeterminism인가 | Runner SHA, Helper APK SHA/version, scenario config hash, app/WebView version | 이전 성공 build와 최신 실패 build의 교차 실행 | code version에 따라 결과가 재현되고 device state 교차에서 유지될 때 regression 확정 |
| identity weakness가 실제 skip을 만드는가 | skip decision마다 compared identities와 matched component | same text/different bounds/resource-id fixture 및 실화면 | distinct physical node가 same identity로 skip된 구체 event 필요 |
| V5가 실제 over-credit하는가 | frozen artifact에 대한 V5 event ledger와 source provenance | log-only, XLSX-only, combined 입력 결과 비교 | unfocused candidate가 VISITED가 되는 event chain이 산출물에 존재해야 확정 |
| Probe zero가 taxonomy 때문만인가 | 모든 excluded candidate와 exclusion reason | 이전 Safe artifact 재평가 | 13 expected 중 어떤 조건이 0 eligible을 만들었는지 전수 합계가 맞아야 함 |
| summary misclassification 범위는 어디까지인가 | scenario stage transition과 final summary mapping | Safe anchor abort, card absent, tap failure를 각각 재현 | 세 failure가 서로 다른 final reason으로 보존돼야 분류 신뢰 가능 |
| XML/Helper/XLSX 분모가 비교 가능한가 | 동일 timestamp snapshot-id와 object join 결과 | 화면 변화가 없는 고정 viewport에서 capture | candidate별 1:1 또는 explicit alias relation 없이는 visit rate 확정 금지 |

## 6. Can Implementation Start?

### 결론: NO

이 결론은 “문제가 없다”는 뜻이 아니다. 최신 Safe anchor abort와 이전 Safe under-coverage는 실제 문제다. 그러나 현재 RCA를 그대로 구현 기준으로 사용하면 다음 잘못된 전제가 설계에 들어갈 위험이 크다.

- 실제로 성공한 Helper movement를 false positive로 재분류할 수 있다.
- realign 이전 snapshot을 final actual focus로 오인할 수 있다.
- 정상 TalkBack container merge를 누락으로 셀 수 있다.
- 서로 다른 Pet Care/Safe failure를 하나의 common regression으로 묶을 수 있다.
- source provenance가 없는 현 코드를 과거 실행 원인으로 고정할 수 있다.
- 확인되지 않은 V5 operational failure를 전체 Audit 재작업의 근거로 사용할 수 있다.

### 현재 RCA verdict의 독립 재판정

| 기존 Verdict | 독립 판정 | 이유 |
|---|---|---|
| `COMMON_ENGINE_DEFECT` | **PLAUSIBLE** | 공통 mixed-phase row/observability 위험은 확인, 공통 physical-focus defect는 미확정 |
| `COMMON_ANCHOR_REGRESSION` | **PLAUSIBLE behavior cluster / SPECULATION as regression** | 두 plugin abort, 동일 root와 code regression은 미확정 |
| `TRAVERSAL_ENGINE_DEFECT` | **HIGH CONFIDENCE for Safe representative consumption; PLAUSIBLE cross-plugin** | Safe causal chain은 강하지만 cross-plugin count가 phase-incoherent |
| `FOCUS_IDENTITY_DEFECT` | **CONFIRMED structural weakness / PLAUSIBLE incident cause** | 구조와 causality를 분리해야 함 |
| `ANCHOR_MATCHER_DEFECT` | **Misnamed** | matcher는 title을 찾았다. Safe 직접 문제는 resolved action target/verification/fallback chain이다. |
| `AUDIT_GAP` | **CONFIRMED** | Probe zero, pass/low-coverage 병존, 최신 summary의 card-not-found 오분류가 직접 증거 |
| `MULTIPLE_INTERACTING_DEFECTS` | **HIGH CONFIDENCE for Safe, PLAUSIBLE as universal architecture verdict** | Safe에는 여러 문제가 상호작용하나 전체 plugin 동일성은 미확정 |

구현 착수 전에 최소한 다음 evidence gate가 충족돼야 한다.

1. Cross-plugin move mismatch를 원자적 pre/post focus 기준으로 다시 산정한다.
2. representative 선정 전 snapshot과 realign 후 final focus를 분리해 기존 divergence 수치를 재검증한다.
3. 수동 TalkBack traversal로 XML leaf와 actual focus obligation의 관계를 확정한다.
4. Safe와 Pet Care anchor failure의 resolved target chain을 각각 증명한다.
5. artifact와 Runner/Helper source의 exact build provenance를 확보한다.
6. V5를 frozen artifact에 실제 실행해 false VISITED event를 확인한다.

이 gate 전에는 Safe anchor incident에 대한 제한적 대응 범위조차 검증할 수는 있어도, 현재 RCA가 권고한 Runner/Helper/Audit 전체 범위의 구현을 시작해서는 안 된다.

## Evidence Index

- 검토 대상 RCA: [RCA V2](talkback-traversal-engine-root-cause-analysis-v2.md)
- 최신 Safe normal log: [20260711 normal.log](../../qa_frontend_runs/batch_20260711_103140/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260711_103152.normal.log)
- 최신 Safe runner log: [20260711 runner.log](../../qa_frontend_runs/batch_20260711_103140/device_SM-F741N_R3CX40QFDBP/runner.log)
- 최신 Safe summary: [20260711 summary.json](../../qa_frontend_runs/batch_20260711_103140/device_SM-F741N_R3CX40QFDBP/summary.json)
- 이전 Safe runner log: [20260708 runner.log](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/runner.log)
- 이전 Safe Helper/logcat: [20260708 logcat.txt](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/logcat.txt)
- 이전 Safe XLSX: [20260708 XLSX](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260708_235625.xlsx)
- 이전 Safe XML: [entry XML](../../qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260708_235625/home_safe_plugin/xml_dumps/000_step_001_entry.xml)
- Full Run XLSX: [20260711 Full Run](../../qa_frontend_runs/batch_20260711_094543/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260711_094553.xlsx)
- Full Run runner log: [20260711 Full Run runner.log](../../qa_frontend_runs/batch_20260711_094543/device_SM-F741N_R3CX40QFDBP/runner.log)
