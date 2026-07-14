# TalkBack Phase 9.5.2 Aggregate Regression RCA

상태: **ANALYSIS COMPLETE — IMPLEMENTATION NOT STARTED**  
기준일: 2026-07-15  
분석 범위: Nominal → Phase 9.5 → Phase 9.5.1  
단말: `SM-F741N` / `R3CX40QFDBP`

## 1. Executive Summary

Phase 9.5.1은 WebView `FOCUS_RESULT` parser defect를 제거했고 Home Care와
Clothing Care의 `ANCHOR_ABORT`도 제거했다. 그러나 aggregate acceptance의
`704 → 649` raw steps, `567 → 515` result rows, `57.7% → 55.5%` coverage,
`869 → 856` V2 transactions, `3.5% → 7.1%` INDETERMINATE는 하나의 남은
regression으로 설명되지 않는다.

이번 RCA의 핵심 결론은 다음과 같다.

1. **Nominal과 현재 run은 동일 corpus가 아니다.** Nominal은 `ko-KR`, Phase 9.5와
   9.5.1은 `en-US`다. Nominal runtime-config hash는 존재하지만 두 current run은
   `runtime_config_unavailable`이다. repository commit도 다르다. 따라서 aggregate
   percentage 차이를 Phase 9.4 code regression으로 직접 귀속할 수 없다.
2. **Coverage 분모가 유지된 cohort에는 aggregate regression이 없다.** expected
   denominator가 동일한 11개 scenario의 합계는 Nominal과 Phase 9.5.1 모두
   `95/181 (52.5%)`다. 전체 coverage 하락은 denominator가 바뀐 20개 scenario에서만
   발생한다.
3. **Menu에는 독립적인 production defect가 확정됐다.** 영문 content card인
   `Home profile...`과 `Supported devices...`가 `resource_hint,label` 조합으로
   global navigation으로 오분류된다. 그 결과 Menu는 실제 bottom tab에 도달하기 전에
   `global_nav_entry`로 종료한다. Menu 단독 기여는 raw `-22`, result `-20`, covered
   `-13`, transaction `-22`다.
4. **Energy, Life main, Home Care의 감소는 Menu와 같은 원인이 아니다.** 이들은
   global-nav false positive가 아니라 각각 더 작은 inventory와 `repeat_no_progress`
   workload로 종료했다. Nominal과 현재 locale/surface가 다르므로 현재 artifact만으로
   code regression과 dynamic/locale workload를 분리할 수 없다.
5. **Identity normalization 자체가 INDETERMINATE 증가의 primary cause는 아니다.**
   Phase 9.5.1의 61건 모두 target physical relation을 계산했고, 60/61 transaction에는
   representative event가 없었다. 판정 불능의 직접 분기는 action rejected 31건,
   delayed commit 19건, unstable landing 9건, physical delta 1건, incomplete evidence
   1건이다. Anchor interaction이나 representative selection이 이 61건을 만든 증거는 없다.
6. **Recovery recovered count는 복원됐다.** Nominal `19/11`, Phase 9.5.1 `26/11`이다.
   attempt corpus는 달라졌지만 recovered 절대 건수는 baseline과 같다. 남은 10건의
   recovery-phase INDETERMINATE는 모두 `no_content_candidate_in_bounds`와 연결된다.
7. **Verification wait가 transaction 감소를 일으켰다는 증거는 없다.** Phase 9.5에서
   9.5.1로 transactions가 `793 → 856` 증가할 때 profiler verification count도
   `746 → 809`로 같은 방향으로 증가했다. Nominal에는 profiler control이 없으므로
   adaptive wait의 인과는 미확정이다.

따라서 다음 구현 Phase는 aggregate 수치 하나를 복원하는 광범위 수정이 아니라,
확정된 Menu classifier defect를 먼저 분리하고 동일 locale/inventory control run을 만든
뒤, Energy/Life main 및 Identity timing corpus를 각각 독립적으로 다뤄야 한다.

## 2. Evidence Set and Method

### 2.1 Authoritative artifacts

| Cohort | Artifact root | Repository | Locale |
|---|---|---|---|
| Nominal | `qa_frontend_runs/batch_20260712_214922/device_SM-F741N_R3CX40QFDBP` | `0e3b294` | `ko-KR` |
| Phase 9.5 | `tmp_phase95_full_acceptance` | `e15ec2d` | `en-US` |
| Phase 9.5.1 | `tmp_phase951_full_acceptance_retry` | manifest `22af264`, parser change present in working tree | `en-US` |

각 root의 XLSX, `focusable_coverage.json`, `evidence.jsonl`, manifest,
reconciliation, normal log와 profiler를 함께 사용했다. Phase 9.5.1의 앞선 ADB-disconnect
run은 제외했다.

### 2.2 Counting rules

- Raw steps: XLSX `raw` sheet data rows.
- Result rows: XLSX `result` sheet data rows.
- V2 transaction: `SHADOW_ACTION_REDUCED_V2`의 unique transaction.
- Coverage: `focusable_coverage.json.summary`의 `covered_count / expected_count`.
- Recovery: `RECOVERY_CANDIDATE_RESULT`, recovered는
  `strong_recovery=true`와 `identity_v2_move_confirmed`를 만족한 event.
- Scenario별 overlay row는 export에서 `scenario_id`가 비어 있다. Workbook이 scenario
  순서로 직렬화된다는 사실에 따라 직전 non-null `scenario_id`로 귀속했다. 이 방식은
  aggregate raw/result 총계와 정확히 일치하지만, overlay row가 canonical scenario ID를
  직접 보존하지 않는 것은 별도의 observability limitation이다.

## 3. Regression Summary Table

| Metric | Nominal | Phase 9.5 | Phase 9.5.1 | RCA disposition |
|---|---:|---:|---:|---|
| Requested / terminal scenarios | 32 / 32 | 32 / 32 | 32 / 32 | 동일 |
| Traversal started | 31 | 30 | 32 | parser fix로 복원 |
| Anchor abort | 1 | 2 | 0 | parser fix로 제거 |
| Raw steps | 704 | 613 | 649 | nominal 대비 `-55` |
| Result rows | 567 | 482 | 515 | nominal 대비 `-52` |
| Coverage | 388/673 (57.7%) | 294/560 (52.5%) | 315/568 (55.5%) | corpus와 Menu defect 혼합 |
| Raw inventory | 1,219 | 1,086 | 1,061 | nominal 대비 `-158` |
| Canonical expected | 722 | 637 | 645 | nominal 대비 `-77` |
| V2 transactions | 869 | 793 | 856 | nominal 대비 `-13`, scenario churn 큼 |
| INDETERMINATE | 30 (3.5%) | 53 (6.7%) | 61 (7.1%) | lifecycle category 증가 |
| Recovery attempts / recovered | 19 / 11 | 23 / 9 | 26 / 11 | recovered count 복원 |
| Reconciliation | PASS | PASS | PASS | integrity regression 없음 |
| Orphan / duplicate / write failure | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | integrity regression 없음 |

## 4. Coverage RCA

### 4.1 Aggregate decomposition

Nominal 대비 Phase 9.5.1의 covered count는 `388 → 315 (-73)`이고 expected count는
`673 → 568 (-105)`다. 이 차이는 전체 scenario에 균일하게 나타나지 않는다.

| Cohort | N | Nominal | Phase 9.5.1 | Covered delta | Expected delta |
|---|---:|---:|---:|---:|---:|
| Same expected denominator | 11 | 95/181 (52.5%) | 95/181 (52.5%) | 0 | 0 |
| Changed expected denominator | 20 | 293/492 (59.6%) | 215/378 (56.9%) | -78 | -114 |
| Missing in Nominal coverage | 1 | Clothing Care unavailable | 5/9 | +5 | +9 |

분모가 같은 11개 scenario는 Global Nav, Home, Routines, Audio, Door Lock, Home Camera,
Humidity, Temperature/Humidity, TV, Water Leak, Music Sync다. Audio의 `12/19 → 11/19`를
Home Camera의 `12/19 → 13/19`가 상쇄했고 나머지는 동일하다.

따라서 `57.7% → 55.5%`는 공통 traversal visit-rate regression이 아니라 changed-surface
cohort에 집중된 변화다.

### 4.2 Largest covered-count changes

| Scenario | Nominal | Phase 9.5.1 | Covered Δ | Expected Δ | Rate Δ |
|---|---:|---:|---:|---:|---:|
| Menu | 15/26 | 2/15 | -13 | -11 | -44.4%p |
| Family Care | 27/47 | 16/38 | -11 | -9 | -15.3%p |
| Life main | 13/26 | 4/10 | -9 | -16 | -10.0%p |
| Energy | 20/28 | 13/18 | -7 | -10 | +0.8%p |
| Settings | 35/40 | 28/33 | -7 | -7 | -2.7%p |
| Home Care | 15/34 | 9/12 | -6 | -22 | +30.9%p |
| Plant Care | 13/19 | 7/16 | -6 | -3 | -24.6%p |
| Washer | 11/25 | 6/23 | -5 | -2 | -17.9%p |
| Home Monitor | 14/29 | 10/24 | -4 | -5 | -6.6%p |
| Safe | 10/13 | 7/11 | -3 | -2 | -13.3%p |

Energy와 Home Care는 covered absolute count가 줄었지만 denominator가 더 크게 줄어 rate는
오히려 유지 또는 상승했다. 이를 traversal efficiency regression으로 분류하면 안 된다.

### 4.3 Candidate-stage attribution

| Stage | Nominal | Phase 9.5.1 | Delta | Interpretation |
|---|---:|---:|---:|---|
| Raw inventory | 1,219 | 1,061 | -158 | capture한 surface workload 자체가 다름 |
| Canonical expected | 722 | 645 | -77 | merge/eligibility 이후에도 corpus 차이 유지 |
| Expected | 673 | 568 | -105 | audit denominator가 동일하지 않음 |
| Covered | 388 | 315 | -73 | denominator 차이 + scenario-local traversal 차이 |

`raw inventory`부터 차이가 시작되므로 evidence gate만으로 전체 coverage 하락을 설명할 수
없다. XLSX status에는 explicit `SKIPPED` 증가도 없다. Phase 9.5.1 raw status는
`OK 581 / END 35 / ANCHOR 33`이며 anchor abort가 없다.

Evidence gate에서 `identity_v2_indeterminate`이고 visit credit이 false인 action은
Nominal 8건에서 Phase 9.5.1 35건으로 증가했다. 이는 일부 visit credit 감소의
contributing factor지만 primary root는 아니다. 35건 중 terminal/recovery action이 다수이고,
surface inventory 감소는 gate 이전에 이미 존재한다.

### 4.4 Confirmed Menu classifier defect

Phase 9.5 Menu terminal row:

- actual focus: `Supported devices Find out which devices work with SmartThings.`
- resource-id: `...:id/supported_devices_card_view_layout`
- bounds: `(30,1158)-(1050,1525)`, bottom tab 영역이 아님
- classification: `is_global_nav=true`, `global_nav_reason=resource_hint,label`

Phase 9.5.1 Menu terminal row:

- actual focus: `Home profile Design your smart home to match your daily life`
- resource-id: `...:id/my_profile_card_view`
- bounds: `(30,310)-(1050,671)`, bottom tab 영역이 아님
- classification: `is_global_nav=true`, `global_nav_reason=resource_hint,label`

Code chain:

1. `tb_runner/diagnostics.py:283`은 generic token에 `home`, `devices`, `life`,
   `routines`, `menu`를 포함한다.
2. `is_global_nav_row()`의 `347-360`은 resource-id substring hint에 1점,
   configured label substring에 2점을 준다. `Home profile`은 label `Home`을,
   `supported_devices_card_view_layout`은 resource hint `devices`를 만족한다.
3. `383-384`는 strong label signal과 score 3만으로 global nav를 확정한다. 실제
   bottom-region evidence는 필수가 아니다.
4. `StopEvaluator`의 `655-662`는 content scenario에서 false→true transition이면
   `global_nav_entry`로 즉시 종료한다.
5. `tb_runner/scenario_config.py:3-13`의 bottom-tab labels가 substring source다.

Nominal `ko-KR` labels에는 영문 generic token이 없어서 같은 content card가 이 경로를
trigger하지 않았다. 이 결함은 locale-dependent이지만 Menu 전용 하드코딩 문제는 아니다.

## 5. Step / Row RCA

### 5.1 모든 감소 scenario

| Scenario | Raw N→9.5.1 | Raw Δ | Result N→9.5.1 | Result Δ | Terminal N→9.5.1 |
|---|---:|---:|---:|---:|---|
| Energy | 57→31 | -26 | 47→25 | -22 | safety_limit→repeat_no_progress |
| Menu | 25→3 | -22 | 22→2 | -20 | global_nav_entry→global_nav_entry (false target) |
| Home Care | 25→12 | -13 | 22→10 | -12 | plugin_boundary_global_nav→repeat_no_progress |
| Life main | 25→12 | -13 | 21→8 | -13 | global_nav_entry→repeat_no_progress |
| Washer | 27→23 | -4 | 17→14 | -3 | safety_limit→safety_limit |
| Audio | 27→23 | -4 | 24→21 | -3 | confirmed exhaustion→confirmed exhaustion |
| Pet Care | 43→41 | -2 | 38→33 | -5 | local-tab revisit→same |
| Home Monitor | 24→22 | -2 | 19→20 | +1 | repeat_no_progress→safety_limit |
| Motion | 18→17 | -1 | 12→13 | +1 | confirmed exhaustion→same |
| Door Lock | 16→15 | -1 | 10→11 | +1 | confirmed exhaustion→same |
| Air Purifier | 28→27 | -1 | 21→24 | +3 | confirmed exhaustion→same |
| Humidity | 16→15 | -1 | 10→11 | +1 | confirmed exhaustion→same |
| Temperature/Humidity | 16→15 | -1 | 10→11 | +1 | confirmed exhaustion→same |
| Routines | 8→7 | -1 | 7→6 | -1 | global_nav_entry→same |
| Family Care | 41→40 | -1 | 37→32 | -5 | strip-only exhaustion→same |
| Video | 14→13 | -1 | 12→11 | -1 | repeat_no_progress→same |

감소 합계는 raw `-95`, result `-88`이고, 다른 scenario의 증가가 raw `+40`, result
`+36`을 상쇄해 최종 net `-55 / -52`가 된다. 즉 aggregate net만 보면 scenario churn을
숨긴다.

### 5.2 Root-cause clustering

| Cluster | Scenario | Evidence | Classification |
|---|---|---|---|
| False boundary classification | Menu | content bounds/resource가 global nav로 오판 | **Confirmed code defect** |
| Smaller visible/inventory corpus | Energy, Life main, Home Care | expected denominator 각각 -10/-16/-22 | **Confirmed workload difference**, code cause unconfirmed |
| Same terminal, modest row variation | Washer, Audio, Pet, device plugins | stop reason 유지, count 소폭 변화 | Dynamic/local-tab state likely; code cause unconfirmed |
| Parser recovery adds workload | Home Care, Clothing Care | 9.5 abort→9.5.1 traversal | **Confirmed parser effect**, already fixed |
| Larger current workload | Food, Plant, Clothing, Camera | raw/transactions 증가 | Dynamic workload; aggregate loss offset |

Energy는 current 두 run 모두 31 raw rows와 `repeat_no_progress`를 재현했고 Life main도
둘 모두 12 raw rows와 `repeat_no_progress`를 재현했다. 이 지속성은 단순 random one-off보다
강한 신호지만, Nominal과 locale/runtime provenance가 다르므로 Phase 9.4 regression이라고
확정할 수는 없다.

## 6. Identity RCA

### 6.1 Identity pipeline loss point

`reduce_shadow_v2()`는 representative를 comparator input으로 사용하지 않는다.
`tb_runner/evidence_identity.py:1071-1147`에서 pre focus, resolved target, helper/runner
post focus와 delayed observations를 canonicalize하고 physical/target relation을 계산한다.
Phase 9.5.1의 61 INDETERMINATE 중:

- physical target relation: `DIFFERENT_PHYSICAL_NODE 33`, `STRONG_PHYSICAL_LINK 28`
- representative selected event present: 1/61
- post-focus observation present: 61/61
- hierarchy relation: 61/61 `INSUFFICIENT_EVIDENCE`
- missing common fields: node path, parent path, window ID, accessibility node ID, display ID,
  semantic role 각 61건

Hierarchy evidence는 모두 부족하지만 target physical relation은 모두 계산됐다. 따라서
container merge/hierarchy absence는 관측 품질 limitation이지만 현재 61건의 직접 verdict
branch는 아니다. Representative selection도 60건에서 아예 발생하지 않아 primary cause가
될 수 없다.

Anchor 역시 직접 원인이 아니다. Phase 9.5.1은 32/32 traversal이 시작됐고 anchor abort가
0이다. Anchor 전 실패는 action transaction을 만들지 않지만 이번 61건은 모두 transaction
내 action lifecycle에서 발생했다.

### 6.2 Focus identity vs timing

Physical comparator가 판정 불능인 transaction은 1건뿐이다. 나머지 60건은 physical node
관계를 판정했지만 다음 조건 때문에 final verdict를 보수적으로 보류했다.

- `DELAYED_COMMIT`: immediate focus는 pre와 같고 delayed final focus는 다른 node로 안정됨.
- `UNSTABLE`: delayed observation들이 같은 landing을 유지하지 않음.
- `ACTION_NOT_ACCEPTED`: helper action API가 rejected인데 focus delta가 changed이거나
  recovery primitive가 실패함.

`tb_runner/evidence_identity.py:1163-1244`는 complete + stable landing + accepted action을
MOVE confirmation의 필수 조건으로 둔다. `evaluate_stability()`의 `851-930`은 delayed
commit과 unstable을 별도 temporal relation으로 보존한다. 현재 artifact는 comparator
identity 손실보다 action acceptance와 observation timing의 불일치를 보여준다.

## 7. INDETERMINATE RCA

### 7.1 Complete classification of 61 transactions

| Category | Count | Phase | Direct evidence | RCA class |
|---|---:|---|---|---|
| ACTION_NOT_ACCEPTED: reached_end/end_of_sequence | 21 | main loop | rejected action, stable landing, often changed pre→post | lifecycle contradiction |
| ACTION_NOT_ACCEPTED: no_content_candidate_in_bounds | 10 | recovery | recovery helper failure | recovery primitive/candidate availability |
| DELAYED_COMMIT_UNCONFIRMED | 19 | main loop | accepted moved, final delayed focus differs from immediate | observation timing / conservative reducer |
| LANDING_NOT_STABLE | 9 | main loop | delayed focus series unstable | physical timing instability |
| PHYSICAL_DELTA_INDETERMINATE | 1 | main loop | semantic label/package unavailable | evidence insufficiency |
| EVIDENCE_INCOMPLETE | 1 | main loop | delayed 1000 ms missing | transport completeness |

이를 상위 분류로 합치면 action terminal/failure 31, temporal instability/delay 28, genuine
evidence insufficiency 2다.

### 7.2 Scenario distribution

| Scenario | Count | Dominant category |
|---|---:|---|
| Food | 14 | delayed commit 11 |
| Home Care | 6 | reached_end 4 + unstable 2 |
| Family Care | 6 | delayed commit 4 + unstable 2 |
| Life main | 5 | recovery failure 4 + unstable 1 |
| Camera | 3 | reached_end 2 + unstable 1 |
| Smoke / Water Leak / Motion / TV | 2 each | reached_end |
| Settings / Pet / Find | 2 each | recovery failure or delayed commit |
| 나머지 13 scenario | 1 each | mixed |

`EMPTY_VISIBLE`, `NO_FOCUS`, `LOW_CONFIDENCE`, `ANCHOR`는 V2 INDETERMINATE category가
아니다. `EMPTY_VISIBLE`은 XLSX row-quality/shadow classification, Anchor는 pre-traversal
state다. 이들을 V2 transaction verdict와 합치면 layer aggregation 오류가 된다.

### 7.3 Why the baseline was not restored

Nominal 대비 증가 `+31`건의 가장 큰 scenario contributor는 Food `+10`, Home Care `+4`,
Life main `+3`, Family Care `+3`이다. Device endpoint의 `reached_end` INDETERMINATE도
여러 scenario에 각 1~2건씩 새로 나타났다.

Food의 workload는 raw `+8`, transactions `+10`으로 오히려 늘었다. 따라서 Food의
INDETERMINATE 증가는 traversal loss가 아니라 더 많은 delayed-commit transaction을
실행한 결과다. 반대로 Home Care와 Life main은 workload가 작아졌지만 terminal/recovery
action 비중이 커졌다. 동일한 aggregate ratio에는 서로 반대 방향의 원인이 섞여 있다.

## 8. Transaction RCA

### 8.1 All scenario transaction decreases

| Scenario | Nominal→9.5.1 | Δ |
|---|---:|---:|
| Energy | 55→31 | -24 |
| Menu | 24→2 | -22 |
| Settings | 53→43 | -10 |
| Home Care | 33→24 | -9 |
| Video | 34→27 | -7 |
| Pet Care | 44→40 | -4 |
| Life main | 43→40 | -3 |
| Routines | 9→6 | -3 |
| Safe, Motion, Door Lock, Air Purifier, Humidity, Temperature/Humidity, Family Care | each -1 | -7 total |

감소 합계는 `-89`지만 Clothing `+22`, Home Monitor `+18`, Air Care `+11`, Food `+10`,
Plant `+8`, TV `+4` 등 증가 `+76`이 상쇄해 net은 `-13`이다.

Scenario별 raw-step delta와 transaction delta의 Pearson correlation은 `0.778`이다.
Transaction aggregate는 독립 producer regression보다 수행된 action/workload 양에 강하게
종속된다.

### 8.2 Verification wait relation

| Metric | Phase 9.5 | Phase 9.5.1 |
|---|---:|---:|
| V2 transactions | 793 | 856 |
| Profiler verification count | 746 | 809 |
| Verification fast-path hits | 571 | 616 |
| Verification fallback/timeouts | 294 | 314 |
| Internal poll attempts | 3,584 | 3,851 |

두 run은 같은 adaptive verification code를 사용하며 transaction과 verification count가
같은 방향으로 증가했다. `StepCollectionService`의 adaptive branch는 focus/announcement
correlation 후 wait completion 시점을 선택하지만 action request 자체를 skip하지 않는다.
다만 더 이른 completion이 다음 action의 UI timing에 간접 영향을 줄 가능성은 있다.
Nominal에는 profiler/control OFF artifact가 없으므로 이 가능성은 **미확정 가설**이다.

## 9. Dynamic Workload Analysis

### 9.1 Controlled and uncontrolled dimensions

| Dimension | Result |
|---|---|
| Device / Android build | 동일 |
| SmartThings version | 동일 `1.8.47.24` / `184724010` |
| WebView version | 동일 `149.0.7827.160` |
| Helper APK SHA-256 | 동일 |
| Scenario registry hash | 동일 |
| Locale | **Nominal ko-KR, current en-US** |
| Repository | `0e3b294` vs `e15ec2d` / parser working tree |
| Runtime-config hash | Nominal available, current unavailable |
| Account data / card content / timestamps | 동적, 고정되지 않음 |

### 9.2 Evidence for dynamic variation

- Phase 9.5와 9.5.1은 동일 locale와 동일 traversal/verification code다. 22/32 scenario의
  raw row count가 완전히 같았다.
- 변경된 10개 중 Home Care `+11`, Clothing `+7`은 parser fix로 설명된다.
- 나머지에서 Camera는 `17 → 31`, Family `37 → 40`, Audio `21 → 23`처럼 code change
  없이 workload가 바뀌었다.
- Expected denominator도 두 current run 사이에 10개 scenario에서 변했다. Air Purifier는
  `47 → 32`, Camera는 `13 → 15`였다.
- 반대로 Energy 31, Life main 12, Washer 23, Pet 41, Plant 35 등 22개 scenario는 두
  current run에서 raw count가 동일했다. 이 persistent current behavior는 random noise만으로
  치부할 수 없지만 locale/surface difference와 code regression을 분리할 control이 없다.

### 9.3 Classification

| Signal | Verdict |
|---|---|
| Menu early stop | **Code regression/latent classifier defect confirmed** |
| Aggregate coverage 57.7→55.5 | **Not a workload-normalized regression metric** |
| Energy/Life main smaller traversal | Persistent under en-US, root cause unconfirmed |
| Camera/Family/Audio run-to-run changes | Dynamic workload confirmed |
| Identity INDETERMINATE increase | Category shift confirmed; common identity defect unconfirmed |
| Recovery success | recovered count parity restored; attempt-rate comparison not normalized |

## 10. Scenario Ranking

Impact score는 negative raw, result, covered, transaction delta와 positive INDETERMINATE
delta의 합이다. 이는 우선순위용이며 severity를 대체하지 않는다.

| Rank | Scenario | Key deltas (raw/result/covered/tx/indet) | Root cause status | Difficulty | Cross-scenario impact |
|---:|---|---|---|---|---|
| 1 | Energy | -26/-22/-7/-24/-1 | smaller corpus + early repeat, cause unconfirmed | High | Medium |
| 2 | Menu | -22/-20/-13/-22/-2 | global-nav false positive confirmed | Medium | High; all English content labels |
| 3 | Home Care | -13/-12/-6/-9/+4 | parser fixed; remaining corpus/timing split | High | High for WebView lifecycle |
| 4 | Life main | -13/-13/-9/-3/+3 | smaller service inventory + recovery failures | High | High; cross-plugin entry surface |
| 5 | Family Care | -1/-5/-11/-1/+3 | dynamic content + delayed/unstable focus | High | Medium |
| 6 | Settings | +1/+3/-7/-10/+2 | action mix changed; coverage denominator -7 | Medium | Medium |
| 7 | Pet Care | -2/-5/+1/-4/+2 | same stop, dynamic WebView content | Medium | Medium |
| 8 | Video | -1/-1/-3/-7/0 | same repeat stop, recovery mix | Medium | Low |
| 9 | Washer | -4/-3/-5/0/-1 | same safety stop, content/local-tab difference | Medium | Medium for device plugins |
| 10 | Food | +8/+9/+1/+10/+10 | no workload loss; delayed-commit identity concentration | High | High for temporal reducer policy |

Menu가 score 2위지만 유일하게 production code root cause가 직접 확정됐으므로 구현 순서는
Energy보다 앞선다.

## 11. Independent Root Causes

### RC-1 — English content mistaken for global navigation

- Status: **CONFIRMED**
- Scope: Menu에서 재현, matcher는 공통 코드.
- Cause: generic substring token + label substring score가 bottom region/resource exactness 없이
  strong global-nav signal이 됨.
- Symptoms explained: Menu raw/result/covered/transaction 급감과 premature stop.
- Does not explain: Energy, Life main, Identity 61건.

### RC-2 — Acceptance corpus mismatch

- Status: **CONFIRMED measurement root cause**
- Scope: aggregate Nominal comparison 전체.
- Cause: locale, repository provenance, runtime-config provenance, dynamic inventory가 불일치.
- Symptoms explained: denominator `673 → 568`, raw inventory `1,219 → 1,061`, locale-specific
  routing/classification exposure.
- This is not a traversal code defect, but it prevents causal acceptance.

### RC-3 — Scenario-local dynamic/smaller surface workload

- Status: **HIGH CONFIDENCE as contributor; producer cause unconfirmed**
- Scope: Energy, Life main, Home Care, Family, Settings 등.
- Evidence: candidate/raw inventory부터 감소; some current run-to-run inventory variation.
- Possible producers: account data, locale layout, load/scroll state, app content. Current evidence
  does not choose one.

### RC-4 — Action lifecycle / temporal evidence category shift

- Status: **CONFIRMED direct cause of INDETERMINATE; physical root unconfirmed**
- Scope: 61 V2 transactions.
- Cause at reducer boundary: rejected action 31, delayed commit 19, unstable 9, insufficient 2.
- Not caused by representative or anchor. Container hierarchy is unavailable but not the direct branch.

### RC-5 — Recovery candidate cannot resolve a content node

- Status: **CONFIRMED for 10 recovery INDETERMINATE transactions**
- Scope: Life main 4, Settings 2, and Air/Home/Clothing/Video 1 each.
- Cause at helper boundary: `no_content_candidate_in_bounds`.
- It does not explain the other 51 INDETERMINATE or Menu.

### RC-6 — Energy/Life main early repeat under en-US

- Status: **UNCONFIRMED hypothesis**
- Evidence: identical reduced raw counts and stop reason in both en-US full runs.
- Missing proof: matched en-US pre-adaptive control and fixed inventory replay.
- It may require zero code changes if the surface legitimately exposes fewer nodes.

## 12. Recommended Fix Order

1. **Menu/global-nav classifier boundary** — first because the code defect and physical counterexample
   are both confirmed and the matcher is shared across scenarios.
2. **Matched acceptance corpus** — rerun Nominal/current with identical `en-US`, runtime config hash,
   app/account state and captured inventory. Do this before changing stop, coverage or identity semantics.
3. **Life main and Energy isolated replay** — compare candidate inventory, scroll attempts, actual focus
   and repeat stop on the same captured surface. Only implement if the matched control reproduces loss.
4. **INDETERMINATE category-specific investigation** — keep rejected terminal actions, delayed commit,
   unstable landing and recovery failure separate. Do not relax the reducer globally.
5. **Recovery primitive corpus** — investigate the 10 `no_content_candidate_in_bounds` transactions
   independently from main-loop identity.
6. **Container hierarchy evidence** — improve only after demonstrating a transaction whose verdict is
   blocked by hierarchy. Current 61-count increase is not such proof.

## 13. Risk Assessment

| Risk | Severity | Evidence | Guardrail |
|---|---|---|---|
| Fixing aggregate percentage instead of root cause | Critical | denominator differs by 105 | fixed-workload cohort gate |
| Weakening global-nav detection too broadly | High | valid bottom tabs still need terminal detection | retain exact resource + region evidence |
| Promoting delayed commit to MOVE without causation | High | 19 delayed transactions lack action-to-late-event proof | require correlated event/commit evidence |
| Treating reached_end + changed focus as success | High | 21 contradictory transactions | preserve INDETERMINATE until lifecycle clarified |
| Relaxing recovery gate | High | 10 helper failures are physical candidate failures | keep strong evidence gate |
| Plugin-specific fixes | High | classifier and lifecycle paths are common | use generic identity/region/action rules |
| Comparing overlay rows by blank scenario ID | Medium | export omits scenario ID | add analysis-time provenance; do not infer cross-order |

## 14. Phase 9.5.3 Implementation Plan

This section defines scope; Phase 9.5.2 does not implement it.

### Workstream A — Confirmed boundary defect

- Create a focused corpus containing valid bottom tabs and content cards with words Home, Devices,
  Life, Routines and Menu.
- Correct the common global-nav classification contract without scenario/plugin branches.
- Validate Menu, Home, Life and Routines start/terminal behavior in both `ko-KR` and `en-US`.

### Workstream B — Corpus-controlled regression decision

- Persist locale, runtime-config hash, app/account fixture ID, expected inventory hash and repository
  dirty-state hash as the acceptance key.
- Rerun Energy and Life main with the same XML/focus starting surface on old/current verification policy.
- If rows and focus sequence match, close as dynamic workload. If they diverge, open one bounded
  scroll/progress defect per distinct divergence.

### Workstream C — Identity category experiments

- For 19 delayed commits, capture the accessibility event/commit causation linking the late focus to
  the requested action.
- For 21 reached-end contradictions, compare pre/immediate/delayed focus and helper action status at
  the same transaction.
- For 9 unstable landings, distinguish A→B→A snap-back from B/C oscillation.
- For 10 recovery failures, preserve helper failure semantics and inspect node-resolution evidence.

### Acceptance gates

- Menu content card is not global nav; real bottom tab remains detected.
- Same-workload scenario raw/result/transaction counts are equal or differences are transaction-level
  explained.
- Coverage is compared only when expected inventory hash matches.
- No change to coverage meaning, recovery credit, stop thresholds or Identity verdict without a
  positive and negative evidence corpus.
- Reconciliation remains PASS with orphan/duplicate/write failure 0.

## 15. Final Verdict

### Confirmed Root Causes

1. **Global-nav substring false positive**: Menu content cards are physically outside the bottom strip
   yet classified global nav by `resource_hint,label`; code and two en-US full-run rows confirm it.
2. **Unmatched acceptance corpus**: locale and runtime provenance differ, and raw inventory drops by
   158 before traversal credit is considered.
3. **INDETERMINATE direct categories**: rejected actions 31, delayed commits 19, unstable landings 9,
   evidence insufficiency 2.
4. **Recovery physical failure subset**: 10 recovery transactions report
   `no_content_candidate_in_bounds`.

### Unconfirmed Hypotheses

- Adaptive verification wait causes Energy/Life main early stop.
- Life main and Energy require a production traversal fix rather than reflecting a smaller English
  app surface.
- Delayed commits can safely be promoted without stronger causation evidence.
- Missing container hierarchy is responsible for the current INDETERMINATE increase.

### Independent Regressions

- Menu boundary classification is independent of WebView parser, Energy/Life main workload and
  Identity timing.
- Energy and Life main are independent from each other until a matched replay proves a shared
  scroll/progress cause.
- Identity temporal/action categories are independent from aggregate coverage denominator changes,
  though a conservative gate can contribute to visit/progress suppression downstream.
- Recovery `no_content_candidate_in_bounds` is a distinct helper/candidate-resolution class.

### Recommended Implementation Order

1. Common global-nav boundary classifier.
2. Matched-corpus control and acceptance key.
3. Energy/Life main isolated replay decision.
4. Delayed/reached-end/unstable identity experiments.
5. Recovery candidate-resolution subset.

### Estimated Number of Required Fixes

- **Confirmed now: 1 production code fix** (common global-nav matcher).
- **Measurement/acceptance change: 1 independent work item** (matched corpus key).
- **Potential after experiments: 2–3 additional bounded fixes** for scroll/progress, temporal action
  correlation and recovery node resolution. They are not yet authorized by evidence.

### Confidence

**Medium-High.** Menu and INDETERMINATE category attribution are high-confidence because transaction,
row and code evidence agree. Aggregate causality is medium confidence because Nominal and current
locale/runtime corpus are not equivalent. Broad traversal or Identity changes are not justified yet.

