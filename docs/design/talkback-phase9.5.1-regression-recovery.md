# TalkBack Phase 9.5.1 Regression Recovery

상태: **FAIL**  
기준일: 2026-07-15  
기준 commit: `22af264c9f33f75a819ac1c2f7724c4cb5d7a18d`  
단말: `SM-F741N` / `R3CX40QFDBP` / locale `en-US`

## 1. Regression Summary

Phase 9.5의 32-scenario run은 process exit `0`, evidence reconciliation `PASS`,
orphan/duplicate/write failure `0`을 유지했지만 Home Care와 Clothing Care가 traversal
전에 `ANCHOR_ABORT`로 끝났다. 그 결과 coverage, rows, steps와 transaction workload가
감소했고, runtime 감소를 성능 개선으로 인정할 수 없었다.

Phase 9.5의 before/current 비교에는 추가 confound가 있었다.

| 항목 | Before full | Phase 9.5 |
|---|---|---|
| Locale | `ko-KR` | `en-US` |
| Repository | `0e3b294` | `e15ec2d` |
| Runtime config provenance | hash available | unavailable in manifest |
| Requested scenarios | 32 | 32 |

따라서 `57.7% -> 52.5%`, recovery `19/11 -> 23/9`, identity INDETERMINATE
`3.5% -> 6.7%`를 Phase 9.4 하나의 인과로 단정할 수 없다. 동일 locale과 동일 dynamic
UI corpus가 아니며, scenario별 inventory denominator와 transaction workload도 달랐다.

## 2. Root Cause

### 2.1 Home Care와 Clothing Care Anchor Abort

두 abort의 공통 primary root cause는 Anchor matcher나 Abort policy가 아니라
`FOCUS_RESULT` transport boundary였다.

1. XML entry는 올바른 Life card를 찾고 tap했다.
2. Helper의 post-entry focus는 실제 plugin WebView였다.
3. WebView focus snapshot의 child hierarchy가 커서 Android logcat 단일 line 한계에서
   JSON이 약 4,040자 부근에 잘렸다.
4. `ActionResultParser`는 children 앞에 이미 완전하게 직렬화된 root identity와 bounds도
   `partial_root_complete=false`로 판정했다.
5. `get_focus()`가 안전을 위해 partial node를 폐기했고 UIAutomator dump는 WebView 내부
   focus를 복원하지 못했다.
6. Anchor verification은 실제 plugin screen evidence를 받지 못해 low-confidence start를
   거부했다.

Phase 9.5 artifact의 직접 증거:

| Scenario | Actual truncated root | Parse failure | Result |
|---|---|---|---|
| Home Care | class `android.webkit.WebView`, text `SmartThings Home Care` | char 4039 | `ANCHOR_ABORT` |
| Clothing Care | class `android.webkit.WebView`, text `Clothing Care` | char 4041 | `ANCHOR_ABORT` |

Phase 9.4는 이 parser를 변경하지 않았다. 이 결함은 이전부터 존재한 latent defect이며,
영문 WebView hierarchy가 logcat limit을 넘으면서 재현됐다. Before run에서 Home Care가
성공한 사실은 locale와 payload 크기가 달랐으므로 반례가 아니다.

### 2.2 Coverage, Rows, Steps와 Runtime

Home Care abort는 step 감소의 contributor지만 전체 감소의 단일 원인은 아니다.
Phase 9.5의 총 step 감소는 91이고 Home Care는 그중 24 step만 설명한다. Menu, Life main,
Energy의 조기 stop/서로 다른 workload가 나머지 대부분을 차지한다. 특히 Home Care는
Phase 9.5에서 V2 transaction이 0이므로 INDETERMINATE 증가의 원인이 될 수 없고,
before/current 모두 recovery attempt가 0이므로 recovery `19/11 -> 23/9`도 유발하지
않았다.

결론적으로 두 abort는 공통 parser defect이고, aggregate coverage/recovery/identity 변화는
동일하지 않은 corpus와 여러 scenario의 독립적인 결과가 섞인 symptom이다.

### 2.3 Menu EMPTY_VISIBLE

Menu step 1은 실제 accessibility focus가
`com.samsung.android.oneconnect:id/setting_button_layout`, bounds
`(930,163)-(1032,265)`로 이동했다. Helper dump와 Runner row에서 visible label과 speech가
모두 비어 있었고 V2 transaction은 `MOVE_CONFIRMED`/`COMPLETE`였다.

따라서 이 row는 focus transport failure가 아니라 앱이 노출한 무라벨 accessibility node다.
현재 coverage/quality 의미를 유지하는 조건에서는 `EMPTY_VISIBLE`을 PASS로 바꾸면 안 된다.
Phase 9.5.1은 이 판정을 변경하지 않는다.

## 3. Fix

`talkback_lib/action_result_parser.py`의 partial focus parsing에 root-field-prefix validation을
추가했다.

- `children` 이전 byte range만 별도의 JSON object로 parse한다.
- root prefix가 문법적으로 완전하고 bounds와 text/content-description/resource identity가
  있을 때만 기존 `partial_payload_trusted` gate를 통과한다.
- child field는 prefix 밖에 있으므로 root identity로 섞일 수 없다.
- incomplete root scalar/bounds는 계속 untrusted이며 기존 dump fallback을 사용한다.

Anchor matcher, abort condition, wait/retry/sleep, traversal, coverage, recovery, stop,
evidence ledger와 Identity V2는 변경하지 않았다.

## 4. Validation

### 4.1 Unit and regression tests

| Test | Result |
|---|---:|
| `tests/test_focus_result_parser.py` | 15 passed |
| focus parser + anchor + collection regression | 495 passed |

추가된 tests는 완전한 WebView root prefix는 신뢰하고, root bounds가 불완전한 경우와
child-only identity는 계속 거부함을 검증한다.

### 4.2 Single-device acceptance

공통 조건: Clean Launch, Current Language (`en-US`), Runtime Coverage Probe OFF,
Traversal V2/Evidence/Identity/Profiler ON.

| Scenario | Before | After | Rows | Coverage | Reconciliation | V2 completeness |
|---|---|---|---:|---:|---|---|
| Home Care | `ANCHOR_ABORT` | traversal, `repeat_no_progress` | 10 raw / 10 filtered | 9/11, 81.8% | PASS | 20/20 COMPLETE |
| Clothing Care | `ANCHOR_ABORT` | traversal, `repeat_no_progress` | 8 raw / 5 filtered | 5/9, 55.6% | PASS | 22/22 COMPLETE |
| Menu | `EMPTY_VISIBLE` | same physical empty-label row | 4 raw / 4 filtered | 2/15, 13.3% | PASS | 3/3 COMPLETE |

Home Care는 기존 low-confidence fallback policy가 salvaged WebView focus evidence를 받아
`fallback_candidate_and_focus_evidence`로 시작했다. Clothing Care는 `Clothing Care`
root label로 `verified_without_select`, matched/stable=true가 됐다. 어느 경우에도 anchor를
bypass하지 않았다.

첫 Menu 단독 시도는 이전 Clothing WebView가 launch 후 복원되어 bottom navigation
precondition이 없었으므로 validation corpus에서 제외했다. launcher root와 bottom navigation을
확인한 재실행 결과만 위 표에 사용했다.

### 4.3 32-scenario full run

동일 `en-US` 설정으로 32개 scenario를 재실행했다.

- Clean Launch / Current Language (`en-US`)
- Runtime Coverage Probe OFF
- Traversal V2 / Evidence Ledger / Identity Shadow V2 / Runtime Profiler ON
- process exit `0`, wall time `10,004.3 s`
- scenario profiler `32/32`
- evidence reconciliation `PASS`
- orphan / duplicate / write failure `0 / 0 / 0`
- scenario terminal `32/32`, traversal started `32/32`, anchor abort `0`

유효 artifact:

- `tmp_phase951_full_acceptance_retry/talkback_compare_20260714_224157.normal.log`
- `tmp_phase951_full_acceptance_retry/talkback_compare_20260714_224157.xlsx`
- `tmp_phase951_full_acceptance_retry/talkback_compare_20260714_224157.evidence.jsonl`
- `tmp_phase951_full_acceptance_retry/talkback_compare_20260714_224157.evidence_reconciliation.json`
- `tmp_phase951_full_acceptance_retry/talkback_compare_20260714_224157.focusable_coverage.json`
- `tmp_phase951_full_acceptance_retry/talkback_compare_20260714_224157.profiler/*.profiler.json`

앞선 첫 full-run 시도는 18개 scenario 뒤 ADB가 disconnect되어 `adb timeout`,
`device not found`, `app_exited_after_back`을 기록했다. 그 실행은 중단 corpus이며 아래
집계에서 제외했다.

| 항목 | Nominal before | Phase 9.5 | Phase 9.5.1 | 판정 |
|---|---:|---:|---:|---|
| Traversal started | 31 | 30 | 32 | abort 제거 |
| Anchor abort | 1 | 2 | 0 | **PASS** |
| Raw steps / rows | 704 | 613 | 649 | current 대비 복원, nominal 미달 |
| Result clean / review / fail | 391 / 175 / 1 | 342 / 138 / 2 | 356 / 158 / 1 | FAIL baseline 복원 |
| Shadow pass / review / warn / fail | 369 / 137 / 60 / 1 | 294 / 100 / 86 / 2 | 306 / 115 / 93 / 1 | FAIL baseline 복원 |
| Focusable Coverage | 57.7% (388/673) | 52.5% (294/560) | 55.5% (315/568) | nominal 미달 |
| Recovery attempts / recovered | 19 / 11 | 23 / 9 | 26 / 11 | recovered baseline 복원 |
| Evidence transactions | 869 | 793 | 856 | current 대비 복원, nominal 미달 |
| INDETERMINATE | 30/869 (3.5%) | 53/793 (6.7%) | 61/856 (7.1%) | **FAIL** |
| Reconciliation | PASS | PASS | PASS | 유지 |

Phase 9.5.1 identity distribution은 `MOVE_CONFIRMED 547`, `STATIC_FOCUS 241`,
`INDETERMINATE 61`, `MOVE_TO_OTHER_NODE 1`, `SNAP_BACK 6`이다. Transaction completeness는
`COMPLETE 855 / PARTIAL 1`로 transport integrity는 유지됐지만 identity baseline은
복원되지 않았다. INDETERMINATE의 주요 corpus는 Food 14, Home Care 6, Family Care 6,
Life main 5였다. 새로 복원된 Home Care workload도 6건을 추가했으므로 absolute count만
Phase 9.5와 비교해서는 안 되지만, 비율도 `6.7% -> 7.1%`로 개선되지 않았다.

Recovery는 ledger canonical count 기준 `26 attempts / 11 recovered`다. 성공 건수는
nominal 11건을 복원했지만 attempt 수와 dynamic candidate corpus가 달라 성공률 parity는
입증하지 못했다.

Menu는 단독 재현에서는 physical empty-label node를 유지했지만 full run의 최종 row에서
신규 Shadow FAIL을 재현하지 않았다. Full run의 유일한 row/Shadow FAIL은 기존 known issue인
Home Monitor 1건이었다. 이는 Menu 결함이 수정됐다는 뜻이 아니라 dynamic focus state에 따라
재현되지 않았다는 뜻이다.

Profiler scenario runtime 합은 `9,729.2 s`, run summary runtime은 `9,977.6 s`다.
Phase 9.5보다 raw steps가 `5.9%` 증가하면서 run runtime도 `6.6%` 증가했다. Step당 run
runtime은 `15.37 s`로 nominal before의 `15.35 s`와 사실상 같아서, runtime 차이는 새
최적화가 아니라 workload 복원과 일치한다.

## 5. Before / After

Home Care와 Clothing Care의 traversal-before-start abort는 단독 run과 full run 모두에서
제거됐다. Full run에서 Home Care는 `repeat_no_progress`, 11 main steps, coverage
`9/12 (75.0%)`; Clothing Care는 `repeat_no_progress`, 7 main steps, coverage
`5/9 (55.6%)`로 종료했다. 두 scenario 모두 기존 entry/anchor gate를 통과했으며 bypass는
없었다.

그러나 aggregate 의미는 nominal before와 같지 않다. Coverage는 `55.5%`로 Phase 9.5보다
3.0%p 회복했지만 nominal보다 2.2%p 낮다. Raw steps는 36개 복원됐지만 nominal보다 55개
적고, evidence transaction도 nominal보다 13개 적다. Identity INDETERMINATE와 SNAP_BACK은
오히려 nominal보다 높다. 따라서 공통 parser defect 제거와 전체 acceptance 통과는 구분해야
한다.

## 6. Residual Risk

- Android logcat 자체는 여전히 child hierarchy를 자를 수 있다. 이번 fix는 root identity만
  안전하게 복원하며 omitted child hierarchy를 복원하지 않는다.
- WebView root에 usable label/resource/bounds가 없으면 partial payload는 계속 untrusted다.
- Menu와 Home Monitor의 physical empty-label nodes는 app accessibility limitation으로 남는다.
- Dynamic inventory, locale, account/device state가 다른 run의 aggregate coverage/recovery를
  직접 비교하면 잘못된 regression 결론을 만들 수 있다.
- 동일 `en-US` 재실행에서도 dynamic candidate/workload가 완전히 고정되지 않아 nominal
  row/step/coverage parity를 입증하지 못했다.
- Identity `INDETERMINATE 61`, `SNAP_BACK 6`, `MOVE_TO_OTHER_NODE 1`은 parser fix 범위를
  넘어서는 residual acceptance blocker다. 이번 phase에서는 Identity V2 의미를 변경하지 않았다.

## 7. Lessons Learned

1. 동일 scenario count는 동일 workload를 의미하지 않는다. Locale, scenario selection,
   runtime-config hash와 dynamic denominator를 acceptance key로 함께 고정해야 한다.
2. WebView root identity와 child hierarchy completeness는 별도의 신뢰 축이어야 한다.
3. Anchor Abort는 원인이 아니라 verified physical focus evidence가 소실된 결과일 수 있다.
4. Aggregate runtime 감소는 rows/steps/transactions parity가 없으면 최적화 증거가 아니다.
5. Physical empty-label focus는 transport failure와 구분해 보고하며 판정 의미를 완화하지 않는다.

## 8. Final Verdict

**Phase 9.5.1: FAIL**

Primary parser root cause는 제거됐고 Home Care/Clothing Care anchor abort, recovered count,
row/Shadow FAIL count는 복원됐다. Evidence reconciliation도 계속 PASS다. 그러나 사용자가
정한 strict gate 중 Coverage baseline 이상, rows/steps 동일, Identity baseline 이상을
충족하지 못했다. Recovery는 recovered 11건을 복원했지만 candidate attempt corpus가 달라
동일 성공률을 입증하지 못했다.

따라서 이 변경은 **확인된 anchor evidence-loss defect의 최소 수정**으로는 성공했지만,
Phase 9.5.1 전체 Regression Recovery Acceptance는 통과하지 못했다. 추가 최적화나 의미 변경이
아니라 동일 locale/account/screen inventory를 고정한 반복 corpus와 remaining
INDETERMINATE/SNAP_BACK 분류가 선행돼야 한다.
