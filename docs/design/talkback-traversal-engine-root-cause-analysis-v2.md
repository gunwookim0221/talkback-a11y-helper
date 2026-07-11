# TalkBack Traversal Engine Root Cause Analysis (V2)

작성일: 2026-07-11
분석 범위: 저장소 전체, 최신 Safe 단독 실행, 이전 Safe 실행, 2026-07-09 Full Run, 2026-07-11 Full Run, XML/Helper dump, screenshot crop, XLSX, V7/Probe 산출물
변경 범위: 분석 문서만 작성. 코드·테스트·실행 정책은 변경하지 않음.

## 1. Executive Summary

최종 판정은 다음과 같다.

- `MULTIPLE_INTERACTING_DEFECTS`
- `COMMON_ENGINE_DEFECT`
- `COMMON_ANCHOR_REGRESSION` (행동 회귀는 확인, 특정 최근 커밋 귀속은 불충분)
- `TRAVERSAL_ENGINE_DEFECT`
- `FOCUS_IDENTITY_DEFECT`
- `ANCHOR_MATCHER_DEFECT`
- `AUDIT_GAP`

Safe 전용 문제가 아니다. 2026-07-11 Full Run에서 `SMART_NEXT/SMART_NAV=moved`인데 실제 접근성 포커스 identity가 직전 step과 같은 사례가 Energy 1건, Motion Sensor 3건, Air Purifier 1건, TV 10건, Family Care 2건으로 합계 17건 확인됐다. 같은 다섯 scenario에서 representative와 actual focus identity가 다른 row는 합계 67건이었다.

핵심 결함은 세 층이 상호작용하는 구조다.

1. Helper의 `moved`는 Runner가 관찰한 실제 포커스 이동과 동치가 아니다. Runner는 이동 전/후 actual focus identity를 강제 비교하지 않고 `smart_nav_result`를 PASS의 1차 근거로 사용한다.
2. Runner는 실제 포커스를 보존한 뒤 working row의 `focus_node`, label, bounds를 representative candidate로 덮어쓴다. 중복/visited/stop 판정은 이 변형 row를 사용하고, XLSX 저장 직전에만 actual focus를 복원한다. 따라서 엔진 내부에서는 candidate가 방문된 것처럼 진전하지만 XLSX의 actual focus는 정지해 있을 수 있다.
3. Audit V4/V5는 실제 포커스 ledger가 아니라 traversal label 또는 representative가 들어간 `[STEP] END visible=...`를 visit 근거로 사용한다. Coverage Probe는 Safe에서 REQUIRED 후보가 0이어서 계획 자체가 0건이었다. 그러므로 `Discovery 성공 → Visited 집계 성공 → 실제 Focus 실패`가 탐지되지 않았다.

최신 Safe abort도 screen transition 실패가 아니다. Safe card tap 후 실제 focus는 `SmartThings Safe plugin` WebView였으므로 진입은 성공했다. 이후 anchor selection이 `세이프 버튼` TextView를 선택하려 했지만 Helper target finder가 clickable ancestor인 full-screen `primary`로 대체했고, 그 노드에 대한 `ACTION_ACCESSIBILITY_FOCUS success`를 selection 성공으로 반환했다. 검증 read는 빈 label의 `primary`를 두 번 관찰해 anchor mismatch를 올바르게 냈다. 그러나 fallback은 “explicit anchor match가 없을 때”만 생성되므로 explicit match가 잘못된 ancestor로 resolve된 이번 경로에서는 `fallback_candidate_absent`로 abort했다.

따라서 Safe anchor regex나 Safe retry만 손보는 방향은 권고하지 않는다. Runner/Helper/Audit가 공유하는 범용 focus identity, move commit, representative separation, anchor target contract, object ledger를 먼저 수정 범위로 잡아야 한다.

## 2. Evidence Set

주요 artifact:

- 최신 Safe: `qa_frontend_runs/batch_20260711_103140/device_SM-F741N_R3CX40QFDBP/`
  - `talkback_compare_20260711_103152.normal.log`
  - `runner.log`, `logcat.txt`, `talkback_compare_20260711_103152.xlsx`
  - `talkback_compare_20260711_103152.focusable_inventory.json`
- 이전 Safe 부분 순회: `qa_frontend_runs/batch_20260708_235615/device_SM-F741N_R3CX40QFDBP/`
  - `talkback_compare_20260708_235625.normal.log`
  - `runner.log`, `logcat.txt`, `talkback_compare_20260708_235625.xlsx`
  - `talkback_compare_20260708_235625/home_safe_plugin/xml_dumps/`
  - `talkback_compare_20260708_235625/crops/`
  - V7 inventory/coverage 및 Coverage Probe JSON
- 교차 플러그인 Full Run: `qa_frontend_runs/batch_20260709_001336/device_SM-F741N_R3CX40QFDBP/`
- 최신 교차 검증 Full Run: `qa_frontend_runs/batch_20260711_094543/device_SM-F741N_R3CX40QFDBP/`

XLSX는 원본을 수정하지 않고 read-only로 읽었다. 전용 artifact-tool loader는 세션에 제공되지 않아 저장소의 런타임 Python 데이터프레임 경로로 값을 교차검증했다.

## 3. Safe Timeline

### 3.1 최신 실행: traversal 시작 전 abort

| 시각 | 실제 상태 | 엔진 판단 | 판정 |
|---|---|---|---|
| 10:32:09 | Home bottom tab focus 요청 성공 | `focus_align_ok=True` | 정상 |
| 10:32:17 | Safe favorite card 발견, bounds `42,1521,519,1866` | card 발견 성공 | 정상 |
| 10:32:23 | card focus/click 성공 | pre-navigation action success | 정상 |
| 10:32:25 | actual focus=`SmartThings Safe plugin`, class=`WebView`, bounds=`0,94,1080,2496` | `[SCENARIO][pre_nav] success` | screen transition 성공 |
| 10:32:26 | Helper dump에 back/title/more/body/practice/SOS 존재 | explicit anchor 후보 중 `세이프 버튼` 선택 | 후보 선택은 가능 |
| 10:32:27 | target finder가 `세이프 버튼`의 clickable ancestor `primary`를 action target으로 반환 | `ACTION_ACCESSIBILITY_FOCUS success` | anchor target substitution |
| 10:32:28 | actual focus=`primary`, empty label, full-screen bounds | anchor mismatch / not stable | 검증 결과 자체는 타당 |
| 10:32:30~32 | 동일 exact-title 선택이 다시 `primary`로 resolve | 두 번째 mismatch / not stable | 반복 |
| 10:32:32 | 화면은 여전히 Safe지만 fallback 객체는 생성되지 않음 | `low_confidence_anchor_start` → `fallback_candidate_absent` → abort | `TRAVERSAL_ABORT_BEFORE_START` |

직접 근거:

- 최신 normal log 92~112행: scenario mode, card 발견, mismatch, abort.
- 최신 runner log 146~206행: pre-nav 후 WebView focus, `targetName='(?i)^세이프\\ 버튼$'`, `attemptedResourceId='primary'`, empty `primary` verify.
- 최신 logcat 41638~41640행: Safe 화면의 Helper dump에 실제 body 후보가 존재.
- 최신 XLSX: raw 1행, result 0행. placeholder만 저장됐고 traversal row는 생성되지 않았다.
- 최신 focusable inventory: `count=0`, 즉 abort 이전 snapshot이 audit inventory로 승격되지 않았다.

### 3.2 이전 실행: traversal은 시작했지만 실제 focus가 대표 후보를 따라가지 않음

| Step | Move | Previous/Current actual focus | Representative | Engine result | 문제 |
|---:|---|---|---|---|---|
| 0 | - | `SmartThings Safe plugin` WebView | - | anchor row | 정상 시작 |
| 1 | moved | `세이프 버튼` `168,118,924,286` | `도움 요청 연습하기...` `30,1327,1050,1756` | PASS_MOVED | representative/actual divergence |
| 2 | moved | **동일 `세이프 버튼`, 동일 bounds** | `안창준, 오늘도...` | PASS_MOVED | `MOVE_SUCCESS_WITH_STATIC_FOCUS` |
| 3 | moved | `옵션 더보기` `more` | empty-state/record card container | PASS_MOVED | divergence |
| 4 | moved | greeting text | - | PASS_MOVED | 실제 이동 |
| 5 | moved | record/empty-state container | - | PASS_MOVED | container visit |
| 7 | moved | `기록` | `ic_function_indepth` detail button | PASS_MOVED | detail button은 실제 focus 아님 |
| 10~13 | moved | record/empty-state container 반복 | 같은 record representative 반복 | PASS_MOVED, 마지막 repeat stop | actual/representative 모두 정체 |

중요한 시각 근거:

- step 1 crop은 `세이프 버튼`에 파란 focus outline이 있다. 같은 row의 representative는 화면 하단 practice button이다.
- step 5 crop은 `기록 / 아직 사용 기록이 없습니다 / 설명`을 하나의 큰 focus rectangle로 보여준다.
- step 13 crop은 같은 container 영역을 반복한다.
- XML 000~006은 모두 42 node, 19개 non-empty attribute record로 동일했다. viewport exhaustion snapshot이 7회 저장됐지만 XML viewport 자체는 변하지 않았다.

### 3.3 Safe에서 발견됐지만 실제로 방문되지 않은 항목

| 객체 | XML/Helper | Representative로 선택 | Actual focus | V7 결과 |
|---|---|---|---|---|
| 도움 요청 연습하기 + 설명 | 존재, clickable/focusable button | step 1 | 방문 안 됨 | UNKNOWN / related_bounds_only |
| 도움 요청 (`sos`) | 존재, rid=`sos`, clickable/focusable | 없음 | 방문 안 됨 | UNKNOWN / related_bounds_only |
| `ic_function_indepth` detail button | 존재, clickable/focusable | step 7 | 실제 focus는 `기록` | UNKNOWN / related_bounds_only |
| 아직 사용 기록이 없습니다 | 존재, static TextView | section header로 반복 선택 허용 | 독립 focus는 없음 | UNKNOWN / related_bounds_only |
| 설명 텍스트 | 존재, static TextView | container에 병합 | 독립 focus는 없음 | UNKNOWN / related_bounds_only |

정적인 설명을 독립 TalkBack target으로 요구할지는 정책 문제지만, clickable/focusable인 practice/SOS/detail button이 actual focus ledger에 없는 것은 정책이 아니라 traversal miss다.

## 4. Anchor Timeline and Root Cause

### 4.1 왜 pre-navigation success인데 anchor mismatch인가

두 신호가 서로 다른 계약을 나타낸다.

- pre-navigation success: card를 찾고, 진입 action을 수행하고, 진입 직후 WebView focus를 읽었다.
- anchor success: anchor candidate selection 뒤 두 번의 focus read가 anchor config와 일치해야 한다.

최신 실행은 첫 계약은 만족했고 두 번째 계약에서 실패했다. 실패 원인은 화면 미전환이 아니라 anchor action target substitution이다.

`A11yTargetFinder.resolveMatchedTarget()`은 query가 일치한 node를 그대로 쓰지 않고 `resolveToClickableAncestor()`로 올린다 (`A11yTargetFinder.kt:208-230`). Safe title은 focusable TextView지만 clickable하지 않으므로 full-screen clickable `primary`까지 올라간다. 반환 payload도 `targetName=세이프 버튼`인데 `attemptedResourceId=primary`다.

Anchor engine은 action success를 selected=true로 받지만 candidate identity와 returned target identity가 같은지 확인하지 않는다 (`anchor_logic.py:531-554`). 이후 double verification은 빈 `primary`를 읽으므로 mismatch가 된다 (`anchor_logic.py:562-606`).

### 4.2 fallback이 왜 없었나

fallback candidate는 `best is None`일 때만 계산된다 (`anchor_logic.py:669-756`). 최신 Safe에서는 dump에서 `세이프 버튼`이 explicit anchor와 match하므로 `best`는 존재한다. 그 candidate가 wrong ancestor로 resolve됐다는 사실은 fallback 생성 조건으로 되돌아가지 않는다. 결과 객체의 `fallback_candidate_used`는 false이고, `collection_flow.py:1905-1930`의 low-confidence gate가 `fallback_candidate_absent`를 반환한다.

즉 `fallback_candidate_absent`는 “화면에 fallback 가능한 body가 없음”을 뜻하지 않는다. “explicit anchor selection 실패 경로가 fallback 후보 생성 단계로 재진입하지 않음”을 뜻한다. 최신 dump에는 greeting, record, empty state, practice, SOS가 모두 있었다.

### 4.3 anchor false positive / false negative 구분

- False positive: `ACTION_ACCESSIBILITY_FOCUS success`를 requested anchor 성공으로 해석한 selection layer.
- True negative: 두 verify read가 empty `primary`를 보고 anchor mismatch를 낸 verification layer.
- Scenario readiness false negative: Safe 화면 identity는 충분했는데 anchor-only + skipped context + absent fallback 때문에 전체 scenario를 abort한 최종 gate.

따라서 최종 진단은 `ANCHOR_TARGET_SUBSTITUTION` + `ANCHOR_FALSE_NEGATIVE`이며, anchor regex만의 문제가 아니다.

### 4.4 공통성

2026-07-11 09:45 Full Run에서 Life Pet Care도 동일한 `low_confidence_anchor_start` → `fallback_candidate_absent`로 traversal 전 abort했다(normal log 4085~4094). Family Care는 같은 실행에서 select action이 실패했는데 double verify가 실제 back anchor를 관찰하여 `verified_without_select`로 성공했다(4153행). 즉 같은 공통 anchor engine이 세 가지 결과를 만든다.

Safe와 Pet Care의 구체적인 candidate 모양은 다르지만 공통 결함은 다음과 같다.

- action success와 requested target identity가 분리됨
- screen identity/context와 focus anchor identity가 분리됨
- explicit-match failure가 fallback path로 이어지지 않음
- abort 전 `new_screen` readiness를 독립 증거로 판정하지 않음

## 5. Traversal Timeline and Root Cause

### 5.1 false-positive move

Runner row에는 이미 `actual_focus_*`와 `representative_*`가 모두 존재한다. 그러나 판정 순서가 잘못됐다.

1. Step collection은 actual focus를 `actual_focus_visible/resource_id/bounds`에 저장한다 (`talkback_lib/step_collection_service.py:22` 부근).
2. Representative/CTA selection은 working row의 `focus_node`, `focus_view_id`, `visible_label`, `merged_announcement`, `focus_bounds`를 candidate로 덮어쓴다 (`collection_flow.py:10001-10034`).
3. fingerprint/duplicate/visited/stop 판단은 변형된 working row를 사용한다 (`collection_flow.py:9506`, `15531`; `utils.py:140-166`).
4. 저장 직전에 `_build_persisted_row_semantics()`가 actual focus를 visible/focus fields로 되돌리고 representative를 별도 열에 저장한다 (`collection_flow.py:10108-10142`).

그 결과 런타임의 `[STEP] END visible=...`는 representative이고, XLSX raw의 `visible_label`은 actual focus다. Safe step 1 로그는 visible=`도움 요청 연습하기...`이지만 crop과 XLSX actual focus는 `세이프 버튼`이다.

### 5.2 move success 판정의 결손

Safe row의 `post_move_verdict_source='smart_nav_result'`다. `SMART_NAV_RESULT status=moved`를 받은 뒤 actual focus가 이전 identity와 같은지 확인하는 범용 gate가 없다. `prev_speech_same`가 true여도 `traversal_result=PASS_MOVED`가 유지된 row가 있다.

필요한 최소 불변식은 다음이다.

```text
MOVE_COMMITTED =
  helper_action_success
  AND post_focus_observed
  AND post_focus_identity != pre_focus_identity
  AND (requested/resolved target identity is compatible with post_focus_identity)
```

이 불변식이 없으면 대표 candidate의 변화가 실제 이동을 대신한다.

### 5.3 current Full Run 공통 증거

2026-07-11 Full Run에서 다음이 확인됐다.

| Scenario | moved rows | moved + static actual focus | representative/actual divergence |
|---|---:|---:|---:|
| Energy | 41 | 1 | 24 |
| Motion Sensor | 13 | 3 | 5 |
| Air Purifier | 11 | 1 | 6 |
| TV | 29 | 10 | 18 |
| Family Care | 33 | 2 | 14 |
| **합계** | **127** | **17** | **67** |

예시:

- Motion Sensor step 7~8: actual focus는 `MotionSensorCapabilityCardView_header_title`, label `동작 감지 센서`, bounds `84,460,822,529`로 동일하지만 representative는 각각 history compound row와 `100%`로 바뀐다.
- TV step 7~8: actual focus는 `custom.picturemode_DetailCanvas_4_header_title`, label `picturemode`, bounds `84,1330,936,1399`로 동일하지만 representative는 `Standard`, `변경`으로 바뀐다.
- Family Care step 2: actual focus는 `패밀리 케어` title인데 representative는 긴 건강 문구다.

이는 Safe 전용 WebView 현상이 아니라 common Runner/Helper contract defect다.

## 6. Focus Identity Analysis

### 6.1 Android Helper identity

현재 `nodeIdentityOf()`는 `windowId + className + packageName`만 포함한다 (`A11yNavigator.kt:2614-2645`). Text, content description, resource-id, bounds, hierarchy path, child index는 포함하지 않는다. 단독 identity로는 매우 약하다.

다만 `isSameNodeIdentity()`는 bounds가 완전히 같으면 즉시 same으로 보고, 그렇지 않으면 id/text/contentDescription 일치 후 다시 bounds 완전 일치를 요구한다 (`A11yNavigator.kt:3233-3278`). Helper의 exact same-node 비교는 사실상 bounds exact가 핵심이다.

Visited history는 bounds가 같고 `(same view-id 또는 same weak node identity)`일 때 visited로 본다 (`A11yNavigator.kt:2395-2407`). SnapshotTracker에는 label만 visited history에 있으면 즉시 skip하는 경로도 있다 (`A11ySnapshotTracker.kt:248` 부근). 동일 text를 가진 다른 node가 별도 resource-id를 잃는 WebView에서는 오판 위험이 있다.

### 6.2 Runner identity

Runner strict fingerprint는 `resource-id + visible + speech + bounds center`다 (`tb_runner/utils.py:140-151`). Semantic fingerprint는 bounds를 완전히 제거하고 `resource-id + visible + speech`만 사용한다 (`utils.py:154-166`).

더 큰 문제는 이 fingerprint가 actual focus가 아니라 representative로 덮인 working row에서 계산될 수 있다는 점이다. 그래서 Safe actual focus가 정지했어도 representative label/bounds가 바뀌면 strict/semantic history가 진전한다.

### 6.3 요청된 identity 구성 요소 현황

| 요소 | Helper same-node | Helper history identity | Runner strict | Runner semantic | 권고 |
|---|---|---|---|---|---|
| Text | 조건부 | 별도 label history | 포함 | 포함 | 보조 신호 |
| Content description | 조건부 | label로 혼합 | speech로 혼합 | speech로 혼합 | 보조 신호 |
| Resource-id | 조건부 | 별도 signature | 포함 | 포함 | 강한 신호 |
| Bounds | exact | exact/tolerance 경로 | center만 | 없음 | full rect + tolerance 필요 |
| Hierarchy path | 없음 | 없음 | 없음 | 없음 | WebView/무-id node에 필요 |
| Accessibility node/window | window만 | window/class/package | 없음 | 없음 | window id 보존 필요 |
| Class | same-node 직접 비교 없음 | weak identity에 포함 | 없음 | 없음 | 보조 신호 |
| Child index | 없음 | 없음 | 없음 | 없음 | path와 함께 보조 신호 |

권고 identity는 하나의 문자열이 아니라 다음을 분리해야 한다.

- `physical_focus_identity`: window + package + class + resource-id + full bounds + stable hierarchy path/index
- `semantic_identity`: normalized text/content-description/state
- `candidate_identity`: discovery source + node metadata + snapshot/viewport identity
- `alias_group_identity`: container/child가 TalkBack에서 하나로 합쳐지는 경우에만 명시적으로 부여

## 7. Cross Plugin Findings / XML Discovery / Candidate Diagnostics

2026-07-09 Full Run의 최초 entry XML, V7 canonical inventory, XLSX actual focus를 비교했다. `XML`은 첫 entry dump의 non-empty text/content-desc node 수, `XML eligible`은 그중 clickable 또는 focusable인 수다. `V7 canonical`은 여러 Helper/focus snapshot을 merge한 canonical expected count다. 서로 분모가 다르므로 visit rate는 V7 canonical 대비 unique actual focus의 진단값이며 공식 coverage가 아니다.

| Plugin | XML | XML eligible | V7 canonical | Unique actual focus | Diagnostic visit rate | Recent duplicate rows | Anchor abort | Moved/static focus |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Safe | 11 | 8 | 13 | 3 | 23.1% | 1 | 0 (해당 run) | 3 |
| Food | 83 | 49 | 32 | 24 | 75.0% | 2 | 0 | 0 |
| Home Care | 10 | 9 | 11 | 5 | 45.5% | 1 | 1 | 0 |
| Family Care | 36 | 9 | 40 | 16 | 40.0% | 1 | 0 | 2 |
| Motion Sensor | 11 | 9 | 13 | 10 | 76.9% | 5 | 0 | 1 |
| Smoke Sensor | 13 | 9 | 16 | 11 | 68.8% | 3 | 0 | 1 |
| Water Leak | 14 | 10 | 17 | 11 | 64.7% | 2 | 0 | 1 |
| Energy | 15 | 13 | 32 | 32 | 100.0%* | 5 | 0 | 0 |
| Air Care | 16 | 13 | 13 | 10 | 76.9% | 2 | 0 | 0 |

`*` Energy의 100%는 실제 full coverage를 뜻하지 않는다. V7 결과는 canonical 32 중 covered 21, unknown 8이었다. unique actual focus 수와 canonical candidate 수가 우연히 같을 뿐 object-to-object join이 없으므로 aggregation count만으로는 coverage를 판단할 수 없다는 반례다.

후보가 사라지는 주요 지점:

1. XML → Helper representative: static leaf가 container merged label로 흡수되고, 동일 bounds group이 representative 하나로 축약된다.
2. Helper representative → selection: chrome/status/section-header/visited/cluster-consumed 필터가 적용된다.
3. selection → actual focus: select/re-align가 실패하거나 SMART_NEXT가 다른 node/동일 node에 남아도 representative는 계속 소비될 수 있다.
4. actual focus → visited aggregation: Runner log와 V5가 representative label을 VISITED로 커밋한다.

Safe는 3과 4에서 가장 크게 손실된다. XML/Helper에는 practice/SOS/detail이 있지만 actual focus에는 없고, representative label 때문에 방문처럼 보이는 항목이 생긴다.

## 8. Audit Gap Analysis

### 8.1 Audit V4

V4 coverage는 normalized label exact match를 중심으로 traversal label set과 XML label set을 비교한다 (`tools/audit_xml_coverage.py:67-95`). 실제 focus identity, move 전/후 identity, requested target을 join하지 않는다. Compound representative에 XML leaf label이 포함된 경우도 별도 reason으로 취급될 뿐 실제 focus 여부는 검증하지 않는다.

### 8.2 Audit V5

V5는 `[STEP] END`의 `visible`/`speech`를 `VISITED` event로 만든다 (`tools/audit_v5_traversal_core.py:634-653`). 그런데 `[STEP] END`는 persistence 전 working row이므로 representative label이다. 또한 `contained_in_text()`가 compound text 안의 여러 discovered label을 모두 VISITED로 확장한다. Safe record container 하나가 `기록`, icon, empty-state, description을 여러 방문으로 부풀릴 수 있다.

V5 설계 문서가 목표로 한 `selected → activation attempted → focus landed → visited` ledger와 실제 구현 사이에 다음 누락이 있다.

- pre/post actual focus identity event 없음
- move action result와 focus landed result의 분리 없음
- representative candidate와 actual focus candidate의 명시적 join 없음
- visit commit이 actual focus identity에 의해 조건화되지 않음
- scenario start abort가 traversal ledger 밖에서 placeholder로만 남음

### 8.3 Coverage Probe

이전 Safe artifact의 V7 summary는 expected 13, covered 4, unknown 9였지만 required expected count가 0이었다. Probe plan은 candidate 0, eligible 0, results 0이었다. Probe는 `UNKNOWN + related_bounds_only`만으로는 충분하지 않고 taxonomy/actionability eligibility를 추가 적용한다 (`coverage_probe_engine.py:219-246`). Safe 후보가 OPTIONAL/REVIEW로 분류되어 탐색 대상에서 빠졌다.

최신 Safe는 traversal 전 abort하여 focusable inventory count 자체가 0이다. Probe도 candidate 0으로 정상 종료했다. 즉 audit pipeline은 “검사할 대상 없음”과 “검사 전 abort”를 구분하지 않는다.

### 8.4 Aggregation 오류

확인된 aggregation 오류는 다음이다.

```text
XML/Helper discovery 성공
→ representative selection 성공
→ [STEP] END에 representative label 기록
→ V5 VISITED 증가
→ XLSX persistence에서 actual focus로 되돌림
→ 실제 focus는 정지 또는 다른 node
```

이것이 이번 문제를 Audit V4/V5/Probe가 막지 못한 직접 이유다.

## 9. Regression Analysis

### 9.1 최근 변경과의 관계

- `76e7590 Harden partial FOCUS_RESULT fallback handling`: 최신 Safe FOCUS_RESULT는 parse-error salvage가 아니라 완전한 top-level payload였다. `partial_parse` 경로가 아니므로 직접 원인이 아니다.
- `e3896bb`, `1fa23d3` local-tab 변경: Safe abort는 main traversal/local-tab 진입 전 발생한다. 직접 원인이 될 수 없다.
- `fcf3ba2` Safe scenario 추가: broad Safe anchor와 anchor-only 설정을 도입했다. Safe가 기존 공통 anchor/target substitution defect를 드러내는 계기지만, Helper target substitution과 fallback gate는 더 오래된 공통 코드다.
- Anchor selection helper는 2026-04-03 코드(`da5d9f6`), target clickable-ancestor resolution은 2026-03-27~28 코드(`7d786c6`, `7800ccb`), representative overwrite는 2026-04-22(`1fa9a28`), actual/representative persistence split은 2026-05-16~17(`8956c3c`, `c342eb0`)에 도입됐다.

따라서 “최근 다른 플러그인 수정이 anchor engine 코드를 직접 깨뜨렸다”는 증거는 없다. 확인된 것은 **행동 회귀**다: 7월 8일에는 exact candidate action이 실패해 broad anchor fallback이 WebView를 잡았고, 7월 11일에는 exact candidate action이 wrong `primary` ancestor에서 성공하여 fallback이 차단됐다. 동일 latent defect가 device/tree/action state에 따라 성공/실패를 바꾼 것이다.

### 9.2 영향 영역

| 영역 | 확인 결과 |
|---|---|
| Anchor Engine | target substitution, fallback re-entry 결손, screen identity와 anchor identity 결합 부족 |
| Traversal Engine | move result와 actual focus movement 불일치 |
| Representative Selection | actual focus와 독립적으로 candidate 소비/visited 진행 |
| Candidate Merge | compound/container가 leaf visit을 대신할 위험 |
| Chrome Detection | Safe title actual focus 때문에 body representative row가 `chrome` lifecycle로 남는 사례. actual/representative lifecycle 축 분리 필요 |
| Local Tab / Bottom Strip | 이번 Safe abort 직접 원인은 아님. Full Run static focus/representative divergence에는 영향을 받음 |
| Focus Identity | Helper/Runner/Audit가 서로 다른 identity를 사용하고 semantic fingerprint는 bounds를 제거 |
| Context Verification | `anchor_only`에서 context가 skipped라 Safe screen readiness 증거를 사용하지 못함 |
| Screen Transition | 최신 Safe는 실제로 성공. transition failure로 분류하면 오진 |

## 10. Root Cause Tree

```text
MULTIPLE_INTERACTING_DEFECTS
├─ Anchor start abort
│  ├─ matched TextView → clickable ancestor `primary`로 target substitution
│  ├─ action success를 requested anchor success로 오인
│  ├─ double verify는 empty `primary`를 읽어 mismatch
│  ├─ explicit match가 있었으므로 fallback candidate 미생성
│  └─ anchor_only라 screen-context evidence를 사용하지 않고 abort
├─ Traversal under-coverage
│  ├─ SMART_NAV moved를 actual focus delta 없이 신뢰
│  ├─ actual focus 정지 중 representative만 변경
│  ├─ representative working row가 visited/duplicate/stop state를 갱신
│  └─ XML actionable 후보가 actual focus에 도달하기 전에 consumed 처리
└─ Audit false assurance
   ├─ V4 label aggregation, identity join 없음
   ├─ V5 representative `[STEP] END`를 VISITED로 사용
   ├─ compound text contained match로 여러 leaf 방문 처리
   ├─ Probe taxonomy가 Safe 후보를 모두 제외
   └─ pre-start abort와 no-candidate를 모두 0건으로 집계
```

## 11. New Diagnostics

필수 추가 진단:

- `FOCUS_MOVE_MISMATCH`: helper move result와 pre/post actual focus identity 비교 결과가 다름.
- `MOVE_SUCCESS_WITH_STATIC_FOCUS`: move success이지만 physical focus identity 동일.
- `REPRESENTATIVE_ACTUAL_DIVERGENCE`: representative와 actual focus identity/label/bounds가 다름.
- `DISCOVERED_NOT_VISITED`: canonical discovered object에 actual-focus visit edge가 없음.
- `BODY_AS_CHROME`: body representative가 actual chrome focus 때문에 chrome lifecycle로 분류됨.
- `ANCHOR_FALSE_NEGATIVE`: screen identity는 충족하지만 focus anchor만 실패.
- `ANCHOR_FALSE_POSITIVE`: selection action success지만 returned target이 requested candidate와 다름.
- `TRAVERSAL_ABORT_BEFORE_START`: main step 0건, anchor/pre-nav stage abort.

추가 권고:

- `ANCHOR_TARGET_SUBSTITUTION`: requested candidate id/bounds/label과 attempted node가 다름.
- `ANCHOR_FALLBACK_PATH_NOT_ENTERED`: explicit match 후 selection/verification 실패인데 fallback 미실행.
- `VISIT_COMMIT_WITHOUT_FOCUS_EDGE`: representative를 visited 처리했지만 focus landed event 없음.
- `PROBE_ZERO_DUE_TO_TAXONOMY`: unknown/missed가 있지만 eligibility 때문에 plan 0.
- `INVENTORY_ZERO_DUE_TO_PRESTART_ABORT`: 화면에 dump 후보가 있지만 run inventory 0.
- `SAME_TEXT_DIFFERENT_NODE`: text는 같지만 bounds/resource-id/path가 다른 node.
- `REPRESENTATIVE_CONSUMED_ACTUAL_UNCHANGED`: representative state만 consumed되고 actual focus는 그대로.

각 step에 다음 필드를 원자적으로 기록해야 한다.

- `pre_actual_focus_identity`
- `post_actual_focus_identity`
- `requested_candidate_identity`
- `resolved_candidate_identity`
- `representative_identity`
- `move_action_result`
- `focus_landed_result`
- `visit_commit_result`
- `visit_commit_basis`
- `row_lifecycle_actual`
- `row_lifecycle_representative`

## 12. Risk Analysis

범용 수정 시 영향 가능 영역:

- WebView와 native view 모두의 target selection/ancestor promotion
- icon-only child를 clickable parent로 올리는 기존 성공 경로
- CTA/container alias grouping
- local-tab activation과 bottom-strip progression
- scroll 후 bounds 변화가 있는 node history
- overlay/menu anchor realignment
- 동일 text를 가진 status/value/button node
- Excel result의 actual/representative 표시 호환성
- Audit V4/V5 baseline 및 historical trend
- Coverage Probe promotion/validation

특히 ancestor promotion을 전면 금지하면 icon child 클릭/포커스가 깨질 수 있다. 따라서 promotion 자체를 제거하는 대신 “requested node identity”, “action node identity”, “post-focus identity”를 모두 기록하고 action별 허용 관계를 명시해야 한다.

Audit 분모/분자 정의를 바꾸면 과거 coverage와 직접 비교가 어려워진다. 새 metric은 version을 올리고 기존 label coverage와 actual-focus coverage를 병행해야 한다.

## 13. Recommended Fix Scope (No Implementation)

### Priority 0: 공통 move/focus commit contract

- Helper action success와 Runner visit success를 분리한다.
- 모든 SMART_NEXT/SELECT/REALIGN 후 pre/post physical focus identity를 비교한다.
- static focus이면 `moved`를 `MOVE_SUCCESS_WITH_STATIC_FOCUS`로 재분류하고 representative 소비를 금지한다.
- requested/resolved/actual identity 호환성이 없으면 visit을 commit하지 않는다.

### Priority 1: actual focus와 representative state 완전 분리

- working row의 `focus_*`를 representative로 덮어쓰지 않는다.
- `actual_focus`, `representative_candidate`, `selection_target`을 별도 구조체로 유지한다.
- duplicate/stop은 actual focus history와 candidate-consumption history를 별도로 계산한다.
- representative는 focus landed가 확인된 뒤에만 visited/consumed로 승격한다.

### Priority 2: 범용 anchor contract

- target finder가 ancestor를 반환할 때 requested node와 action node의 identity 및 promotion reason을 반환한다.
- anchor selection은 action node가 candidate와 허용된 alias 관계인지 확인한다.
- explicit candidate가 select/verify 실패하면 fallback search로 재진입한다.
- `new_screen`은 focus anchor와 screen identity를 별도 축으로 검증하고, screen identity가 강하면 `anchor_false_negative`로 분류한다.
- `verified_without_select`, `selected_and_verified`, `anchor_only`, low-confidence fallback을 하나의 state machine으로 명문화한다.

### Priority 3: canonical object ledger와 Audit 재설계

- XML/Helper candidate마다 canonical candidate identity를 부여한다.
- `DISCOVERED → SELECTED → ACTIVATION_ATTEMPTED → FOCUS_LANDED → VISITED` edge를 저장한다.
- V5 VISITED는 `[STEP] END visible`이 아니라 actual focus identity edge만 사용한다.
- compound text contained match는 “semantic covered”와 “directly focused”를 분리한다.
- abort-before-start도 scenario audit record로 저장한다.
- Probe plan 0이면 unknown/missed count와 exclusion reason을 함께 실패/경고로 노출한다.

### Priority 4: regression suite 범위

구현 단계에서 필요한 범용 회귀 케이스만 제안한다.

- requested TextView가 clickable full-screen ancestor로 promotion되는 WebView
- action success + static actual focus
- representative changed + actual focus static
- same text + different bounds/resource-id
- verified_without_select 정상 경로
- explicit anchor select failure 후 fallback 성공
- screen identity success + anchor focus failure
- pre-start abort의 inventory/probe/audit 집계
- compound container가 leaf direct-focus를 대신하지 못하도록 하는 V5 ledger

Safe 전용 regex, sleep, retry 증가는 수정 범위에서 제외한다.

## 14. Final Verdict

| Verdict | 결론 | Confidence |
|---|---|---|
| `COMMON_ENGINE_DEFECT` | 여러 plugin에서 moved/static focus와 representative divergence 확인 | High |
| `COMMON_ANCHOR_REGRESSION` | Safe와 Pet Care에서 최신 pre-start abort 확인. 단, 특정 최근 커밋 귀속은 불충분 | High for behavior / Medium for code attribution |
| `TRAVERSAL_ENGINE_DEFECT` | actual focus delta 없이 PASS/visited/consumed 진행 | High |
| `FOCUS_IDENTITY_DEFECT` | Helper/Runner/Audit identity 불일치 및 representative 기반 fingerprint | High |
| `ANCHOR_MATCHER_DEFECT` | target substitution 검증 및 fallback re-entry 결손 | High |
| `AUDIT_GAP` | V4/V5/Probe가 실제 focus failure를 방문/0-candidate로 집계 | High |
| `MULTIPLE_INTERACTING_DEFECTS` | 위 결함들이 연쇄적으로 Safe 누락과 abort를 생성 | High |

최종 결론: Safe는 공통 결함을 가장 선명하게 드러낸 재현 사례다. Safe만 수정하면 target substitution, false-positive move, representative/actual divergence, audit false assurance가 다른 plugin에 남는다. 수정 범위는 Runner/Helper/Audit의 공통 move-focus-visit contract와 canonical object ledger가 우선이다.
