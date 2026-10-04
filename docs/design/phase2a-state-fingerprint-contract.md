# Phase 2A — State Fingerprint Contract

Date: 2026-10-05 (Asia/Seoul)

## 1. Verdict

```ini
PHASE2A_VERDICT=PASS_WITH_LIMITATIONS
PHASE2_BRANCH=feature/phase2-state-model
PYTHON_TEST_RESULT=2725 passed, 0 failed, 0 errors, 1 skipped
PRODUCTION_RUNTIME_CHANGED=NO
HELPER_CHANGED=NO
READY_FOR_PHASE2B=YES
PHASE2A_COMMITTED=NO
PHASE2A_PUSHED=NO
```

관찰 입력에서 deterministic fingerprint를 생성하는 Python foundation과 명시적 diagnostic CLI를 구현했다. Home/Devices/Life 반복 관찰, 실제 접근성 focus 이동, Home scroll 및 artifact replay를 검증했다. 실제 smoke 결과는 PASS이며, coarse core collision과 부분 관찰/locale/overlay 한계 때문에 단계 verdict는 PASS_WITH_LIMITATIONS다. `fingerprint_hash`는 최종 state ID 또는 화면 동등성 증명이 아니다.

## 2. Phase 1 Inputs

Source of truth: [Phase 1 gap analysis](phase1-state-auto-discovery-gap-analysis.md)의 §6 Identity Model, §7 Existing State Concepts, §8 State Fingerprint Gap, §14 Locale, §15 Performance/Persistence, §16 Observability, §20 MVP, §21 Subphases.

Phase 1의 `State → Viewport → Focusable instances`, raw/normalized 분리, missing/ambiguous 보존, observation-only integration을 적용했다. 기존 instance-v1과 strict actual visit/termination 계약은 그대로다.

Part A를 먼저 완료한 뒤 Part B를 시작했다. Phase 1 문서는 기존 25개 섹션, canonical 32 scenario matrix 및 24 capability matrix를 확인했고 내용 수정 없이 문서 하나만 publish했다. 기존 linear history에 맞춰 fast-forward merge했다.

```ini
PHASE1_COMMIT=4c829536503503a1d963ff5144cfd6bed576a84f
PHASE1_COMMITTED=YES
PHASE1_BRANCH_PUSH=SUCCESS
PHASE1_PUSHED=YES
PHASE1_MAIN_MERGE=SUCCESS_FAST_FORWARD
PHASE1_MERGED_TO_MAIN=YES
MAIN_PUSH=SUCCESS
MAIN_PUSHED=YES
HEAD_ORIGIN_MAIN_MATCH=YES
```

Published branch: `feature/phase1-state-auto-discovery-gap`. Commit message: `Document Phase 1 state auto-discovery gap analysis`. Phase 2 branch는 이 commit의 최신 main에서 생성했으며 현재 HEAD/main/origin/main은 모두 위 SHA다.

## 3. Existing Reused Assets

| 자산 | 실제 재사용 / 검토 결과 |
|---|---|
| `tb_runner/canonical_json.py` | NFC, sorted keys, compact JSON, UTF-8 + LF SHA256 재사용 |
| `tb_runner/scroll_reliability.py` | `flat_nodes`, Helper capability opt-in transport, axis-v1, legacy viewport 및 verified scroll 재사용 |
| `tb_runner/traversal_reliability.py` | `normalized_bounds`, instance-v1 진단 ID 재사용; identity 구현 수정 없음 |
| `tb_runner/utils.py` | bounds validation/parser 재사용 |
| `tb_runner/global_navigation.py` / `bottom_nav.py` | XML adapter, observed selected destination 및 구조 기반 tab discovery 재사용 |
| `tb_runner/label_matcher.py` | 기존 bottom-tab ko/en canonical labels 재사용 |
| `tb_runner/popup_handler.py` | 기존 modal evidence와 안전/위험 button observations 재사용; 새 detector 없음 |
| `talkback_lib/__init__.py` | existing Helper dump/fast focus 및 ADB transport; smoke에서는 existing focus/scroll/tab tap 사용 |
| `context_verifier.py` | expected route validator임을 확인; arbitrary screen equality로 사용하지 않음 |
| `environment_fingerprint.py` / `environment_profile.py` | run compatibility partition이며 UI fingerprint와 구분; 기존 구현 수정 없음 |
| `evidence_identity.py` / `content_terminal.py` / collection flow | snapshot/surface/terminal은 별도 기존 authority; 새 hash로 대체하지 않음 |

기존 evidence를 가진 caller는 `build_state_fingerprint(observation)`에 직접 전달한다. 명시적 live CLI만 부족한 selected/checked/enabled/window 정보를 기존 XML/ADB source에서 추가 관찰한다. production loop에 추가 capture를 넣지 않았다.

## 4. Fingerprint Goals / Non-goals

목표는 observation → normalized, versioned components → deterministic serialization/hash → diagnostic artifact다. 같은 입력은 같은 payload를 생성하며 focus/typed dynamic 값은 normalized hash에서 분리한다.

이번 구현에 state equality 판정, StateIdentity/Registry, graph, explorer, automatic action selection, scenario replacement, Safe Navigation, Phase 3 기능은 없다. Fingerprint 결과를 traversal branch, terminal, candidate, navigation 또는 visit-credit authority로 소비하는 production caller도 없다.

변경 파일은 전부 신규 파일이다.

| 파일 | 목적 |
|---|---|
| `tb_runner/state_fingerprint.py` | pure builder, immutable model, canonical sections/hashes, explicit JSONL writer |
| `tools/state_fingerprint_diagnostic.py` | saved observation replay / opt-in current-screen capture |
| `tests/test_state_fingerprint.py` | normalization/model/component/serialization 계약 |
| `tests/test_state_fingerprint_diagnostic.py` | transport provenance, unknown/conflict 처리, explicit CLI 경계 |
| `docs/design/phase2a-state-fingerprint-contract.md` | 이 보고서 |

## 5. Data Model

`StateFingerprint`는 frozen dataclass이며 canonical JSON 문자열로 sections를 보관한다. `to_dict()`는 독립적인 새 dict/list를 반환하므로 export를 수정해도 원본 model은 변하지 않는다. 생성 과정은 입력을 수정하지 않는다.

```text
StateFingerprint
  schema_version = state-fingerprint-v1
  core_signature / viewport_signature / overlay_signature
  fingerprint_hash
  core: normalization_version, package, activity, navigation context,
        observed selected tab/status, caller-scoped persistent markers
  viewport: sorted semantic node multiset, partial observation status,
            relative bounds strategy, normalized axis-v1 scroll fields
  overlay: observed kind/status, sorted semantic subset
  transient: timestamp/scenario/step/source, raw digest/context,
             existing positional IDs, focus summary, capability source,
             legacy viewport, missing/unknown counts, notes
```

주요 입력: `nodes`, `package_name`, `activity_name`, `navigation_context`, `selected_tab`, `display_bounds`, `capability`, `focus_node`, `overlay`, optional `core_nodes`, metadata. `nodes/core_nodes/overlay.nodes`는 list다. 잘못된 주요 container type은 ValueError로 거부한다. 누락된 내용은 추정으로 채우지 않는다.

## 6. Included / Excluded Fields

| 요소 | 분류 | 위치 / 의미 |
|---|---|---|
| package/activity | INCLUDED | observed scope guard; Android `.Class`를 observed package와 결합해 전체명으로 정규화; identifier case 유지 |
| navigation context | INCLUDED | 관찰된 context만 caller가 전달; CLI는 실제 selected bottom tab만 사용 |
| selected tab | INCLUDED | verified explicit metadata 또는 실제 selected node; 없음/다중 selected는 unknown/ambiguous |
| visible semantic nodes | INCLUDED | viewport; resource ID/class/role, semantic state/stateDescription, flags, relative geometry |
| overlay/dialog evidence | INCLUDED | 별도 overlay section; detector 미확인은 `unknown`, 부재 확정 아님 |
| scroll capability | INCLUDED | viewport: status/axis/axis contract/forward/vertical/horizontal/contradiction |
| focused element | DIAGNOSTIC_ONLY | actual A11y/input flags, bounds, normalized label; core와 viewport hash에서 제외 |
| transport source provenance | DIAGNOSTIC_ONLY | Helper/XML/context/capability source, capture notes; identity authority 아님 |
| raw pixel bounds / instance-v1 | DIAGNOSTIC_ONLY | existing positional IDs/focus/legacy viewport; normalized hash의 geometry는 relative bucket |
| timestamp/scenario/step | DIAGNOSTIC_ONLY | normalized hash에서 제외; artifact correlation |
| general labels with resource ID | EXCLUDED | locale 변화 완화; 명시적 state 의미와 stateDescription은 포함 |
| labels without resource ID | INCLUDED | normalized text fallback; 완전한 cross-locale equivalence는 주장하지 않음 |
| whole raw XML / volatile event/request/window IDs | EXCLUDED | diagnostic artifact에 XML 복사 없음; raw observation은 caller evidence와 별도로 연결 가능 |

Semantic flags는 enabled/checked/selected/clickable/focusable/scrollable이며 bool이 없으면 null이다. 명시적으로 invisible인 node만 제외한다. visibility 미확인은 유지하면서 unknown count로 표시한다. 비어 있는 observation은 `UNOBSERVED`이며 empty-screen 완료 증명이 아니다.

## 7. Core vs Viewport vs Transient

Core는 observed package/activity와 navigation context를 나타낸다. Live CLI는 body node 전체를 core에 넣지 않는다. `core_nodes`는 caller가 실제로 관찰한 persistent title/pane marker를 명시적으로 공급하는 확장점이며 geometry를 제외한다. 따라서 scroll로 viewport가 달라져도 같은 root core를 유지할 수 있다.

Viewport는 visible semantic multiset와 directional scroll capability다. Focus 이동은 transient에 기록된다. Overlay는 별도 interaction layer이며 body 변화와 함께 combined fingerprint에 반영될 수 있다.

Core가 같아도 같은 activity/tab 내 서로 다른 subpage일 수 있다. 전체 fingerprint도 id-bearing labels가 다른 화면을 합칠 수 있다. 이 collision을 숨기지 않으며 Phase 2B는 context/availability/markers/transition evidence를 검토해야 한다. Phase 2A는 SAME/DIFFERENT/UNKNOWN equality를 반환하지 않는다.

## 8. Dynamic Normalization

Normalization version: `semantic-values-v1-relative32`.

| 입력 변화 | 처리 |
|---|---|
| `23°C → 24°C`, signed decimal ℃/℉ | `<temperature>` typed mask |
| `battery 75% → battery 74%`, `배터리 75%` | contextual percentage mask |
| bare percentage | `<percentage>`; 제한된 fallback heuristic |
| `time 10:31 → time 10:32`, 시각/시간/clock, bare hh:mm | `<clock>` |
| model number / price / unknown ppm measurement | 보존; 일반 숫자 전체 삭제 없음 |
| Door locked → Door unlocked / 잠김 → 잠금 해제 | full-label semantic discriminator 유지 |
| 문 열림 / 문 닫힘 | open/closed로 구분; unlocked와 혼동하지 않음 |

온라인/오프라인 및 loading의 제한된 full-label vocabulary도 포함한다. `unlock door` 같은 action label을 unlocked 상태로 추정하지 않는다. 알려지지 않은 stateDescription은 normalized discriminator로 보존한다.

원본 observation은 수정하지 않으며 sorted raw node digest가 원본 값 변화의 증거를 남긴다. JSONL은 전체 raw tree를 다시 복사하지 않는다. 이번 smoke의 원본 입력은 별도의 `device_observations.json`에 보관했다. 일반 measurement/복합 label/임의 단위/날짜/countdown 전체 normalization은 미구현이다.

## 9. Locale Strategy

resource ID → class/role → observed flags/state semantics → relative geometry를 우선한다. ID가 있는 일반 text는 hash에서 제외하며, ID가 없으면 text/contentDescription/talkbackLabel fallback을 사용한다. 빈 text가 유효한 contentDescription을 가리지 않도록 처리했다.

ko/en Home/Device 구조 fixture와 잠김/Locked stateDescription fixture에서 normalized components가 동일함을 검증했다. 실제 영어 단말 pair 또는 전체 UI version 간 equality 검증은 수행하지 않았다. ID 없는 번역 label과 미등록 semantic vocabulary는 달라질 수 있다.

## 10. Bounds Strategy

기존 parser로 유효 bounds를 확인한 뒤 display-relative grid32 좌표를 사용한다. 네 edge를 display width/height로 나눠 32개 bucket으로 양자화한다. raw pixel geometry는 normalized semantic hash에 넣지 않는다.

Display bounds가 없거나 유효하지 않으면 geometry는 null, strategy는 `UNKNOWN_NO_DISPLAY_BOUNDS`다. invalid node bounds count를 진단한다. 해상도 배율 및 같은 bucket 내 작은 위치 변화 fixture를 검증했다. Bucket 경계/rotation/reflow까지 동등하다는 주장은 하지 않는다.

동일 resource ID의 여러 객체는 list/multiset로 유지한다. 다른 위치는 다른 bucket으로 표현하며, bucket이 같아도 rows를 set으로 합치지 않는다. 원래 instance-v1 구현과 pixel discriminator는 수정하지 않았다.

## 11. Deterministic Serialization

기존 canonical JSON을 재사용한다: sorted keys, compact formatting, NFC strings, UTF-8, finite JSON values. Semantic nodes/markers/overlay nodes는 canonical JSON을 sort key로 정렬하며 중복을 보존한다.

Raw digest는 flattened node에서 nested `children`만 제거한 뒤 정렬한다. 따라서 nested child 순서 변경만으로 부모의 원본 child 배열이 digest를 흔들지 않는다. focus/raw/path evidence 변화는 transient digest를 바꿀 수 있다.

같은 observation을 반복 입력하면 전체 `to_json()`이 byte equivalent다. 서로 다른 live captures는 timestamp/step/raw evidence가 달라 전체 record bytes가 달라질 수 있으나 normalized hash는 동일할 수 있다. 최종 real observation 17개를 JSON으로 저장하고 재입력했을 때 original JSONL과 17/17 records가 byte equivalent했다.

## 12. Hash Contract

```text
core_signature     = SHA256(canonical_json_bytes(core))
viewport_signature = SHA256(canonical_json_bytes(viewport))
overlay_signature  = SHA256(canonical_json_bytes(overlay))
fingerprint_hash   = SHA256(canonical_json_bytes({schema_version, core, viewport, overlay}))
```

기존 `canonical_json_bytes` 관례대로 마지막 LF를 포함해 해시한다. Transient는 위 hash들의 입력이 아니다. Core normalization version과 combined schema version이 규칙 revision을 구분한다. Payload/버전/관찰 가용성을 함께 검토해야 하며 hash 일치로 state ID를 부여하지 않는다.

## 13. Runtime Diagnostic Integration

사용 예:

```powershell
python -m tools.state_fingerprint_diagnostic --input observations.json --output output/state_fingerprints.jsonl
python -m tools.state_fingerprint_diagnostic --capture --serial R3CX40QFDBP --scenario-id home --output output/state_fingerprints.jsonl
```

CLI mode는 명시적으로 선택해야 한다. Replay는 device I/O가 없다. Capture는 현재 UI만 관찰한다. Helper capability를 focus 요청 이전에 복사해 mutable client cache drift를 방지한다. 기존 fast focus는 dump fallback 없이 요청하며, missing selected/checked/enabled/scrollable/visibility는 XML에서 관찰한다. 부재 attribute는 false로 추정하지 않는다.

Context는 unambiguous `mCurrentFocus`, 없을 때 unambiguous observed resumed activity에서 얻는다. 다중 focused/resumed activity는 UNKNOWN이다. XML의 observed package와 충돌하면 context를 사용하지 않고 conflict를 기록한다. Sources는 sequential이며 atomic snapshot을 주장하지 않는다. Activity short/full 형태를 builder에서 정규화하고 raw context/source는 transient에 남긴다.

기존 popup detector evidence만 사용한다. JSONL record에는 timestamp/scenario_id/step, hashes, normalized components, provenance/unknown summary가 있다. 전체 XML 중복 저장은 없다. 기존 dump가 사용하는 Helper request/logcat transport를 재사용하므로 진단 capture가 native 로그를 읽거나 비울 수는 있다. Production execution path에는 이 도구를 연결하지 않았다.

최종 normalization benchmark: 30번 replay, median 43.24 ms, max 53.98 ms(현재 호스트의 마지막 Home observation). 실제 capture는 Helper/XML/dumpsys를 순차 실행하므로 비용이 더 크다. 17 JSONL records는 1,157,654 bytes다. Future runtime 통합 전 existing evidence reuse와 artifact 크기를 다시 검토한다.

## 14. Unit Tests

새 테스트 52 passed, 0 failed/errors. 범위: determinism, immutable exports/input preservation, canonical hash/LF, focus independence, observed/ambiguous selected tab, overlay, temperature/battery/time, meaningful locked/unlocked/open, same-ID instances, nested ordering, ko/en structure, case-sensitive identifiers, Android short activity, bounds scaling/buckets, missing/invalid/unknown, hidden nodes, persistent markers, JSONL, capture provenance/cache, XML fallback, multiple windows, resumed activity/XML conflict, explicit replay/capture CLI.

```powershell
python -m pytest tests/test_state_fingerprint.py tests/test_state_fingerprint_diagnostic.py -q --basetemp output/phase2a_state_fingerprint_20261005/pytest_target4_tmp --junitxml output/phase2a_state_fingerprint_20261005/targeted_tests.xml
python -m pytest tests -q --basetemp output/phase2a_state_fingerprint_20261005/pytest_accepted_tmp --junitxml output/phase2a_state_fingerprint_20261005/python_regression_accepted.xml
```

전체 Python suite: **2726 collected, 2725 passed, 0 failed, 0 errors, 1 skipped**, 81.13 seconds. xlsxwriter가 설치되지 않아 기존 thumbnail test 하나가 skip됐다. 기존 `.pytest_cache`의 접근 권한 관련 warning 하나는 assertion/execution 실패가 아니다.

최초 sandbox 실행은 2684 passed / 1 skipped / 36 setup errors였다. 기존 runtime report parser fixture가 자체 `.test_tmp`에 생성하는 폴더의 접근 권한 문제였고, 해당 테스트/fixture를 수정하거나 제외하지 않았다. 권한 제한 밖에서 전체 suite를 실행해 통과를 확인했으며, device collector 보정 뒤 최종 전체 suite도 재실행했다.

Evidence: `output/phase2a_state_fingerprint_20261005/targeted_tests.xml`, `python_regression_accepted.xml`, `python_regression_accepted.log`. Helper/APK source는 변경하지 않았고 build/install은 수행하지 않았다.

## 15. Device Smoke

Device: R3CX40QFDBP / SM-F741N, 기존 TalkBack/Helper service enabled, battery 50% / USB charging 확인 후 시작. Full Run은 수행하지 않았다. 기존 TV plugin에서 bounded Android Back으로 root에 복귀했고, 기존 GlobalNav discovery/selected evidence로 Home/Devices/Life만 전환했다. 요청한 화면명을 관찰된 selected tab 대신 쓰지 않았다.

최종 authoritative evidence는 `output/phase2a_state_fingerprint_20261005/device_run3/`다.

| Root | 반복 횟수 | 관찰 node 수 | core unique | viewport unique | fingerprint unique | Result |
|---|---:|---:|---:|---:|---:|---|
| Home | 3 | 128/128/128 | 1 | 1 | 1 | PASS |
| Devices | 3 | 179/179/179 | 1 | 1 | 1 | PASS |
| Life | 3 | 178/178/178 | 1 | 1 | 1 | PASS |

Core signatures:

```text
Home    2748bb7787af93ed21c2f7c264fb4efa88219e1d95cdecfdd81cea19e620b489
Devices 086aa0a062a1f8a9ca8429f84e47f5dae1703f7d643fc323a5d550a57c3e237a
Life    45330581209fc7af85dde81efd4bca492b549aeadba81a09cba7399a59f84983
```

세 root core는 서로 다르다. 최종 17 captures의 context source는 activity_resumed 15, window_current_focus 2였으며 capture notes/conflict는 없었다.

**Focus:** Home에서 SmartNext 두 번 모두 moved ACK 이후 실제 `accessibilityFocused=true`를 관찰했다. `tab_title` bounds `168,136,612,256`에서 `mapview_layout` bounds `660,124,792,268`로 서로 다른 객체에 이동했다. Core와 viewport 모두 유지됐다. ACK만으로 실제 focus proof를 대신하지 않았다.

**Scroll:** Home의 실제 vertical forward capability를 확인한 뒤 기존 explicit container `0.0.7` / GridView에 down-scroll했다. `actionAttempted=true`, `actionSupported=true`, success=true, status=SCROLL_MOVED. 기존 Helper viewport instance count는 35→33, persisted=11, new=22, disappeared=24. Before/after는 동일 `home_scroll` scenario scope다. 이 수치는 physical visits가 아닌 viewport observations다.

```text
core unchanged = YES
viewport before = 6a43c8a1a10de44b5e040dd8e59e2f9bc418aebb6b61517524fc4e108e7d1bf3
viewport after  = df523b2ea60fdf0390577b791e841d521303336d75d651dc778261e30a924f5c
```

Devices의 해당 room viewport는 forward capability=false여서 Devices down-scroll은 실행하지 않았다. Home으로 scroll 요구를 충족했다. 이전 smoke의 Home 위치를 복원하는 bounded up-scroll을 사용했으며 마지막에도 Home selected/top viewport 복귀를 확인했다.

**Collision 분리:** Devices의 `com.samsung.android.oneconnect:id/device_name`, `base_card`, `device_action_dead_zone` 각각 12개 instance rows / 12개 distinct layout buckets가 유지됐다. resource ID 하나로 합치지 않았다. `device_name` sample buckets: `[18,12,25,13]`, `[18,15,25,16]`, `[18,19,25,19]`. 원래 positional IDs는 transient로 보존했다.

**발견/보정 이력:** 첫 수집에서 `dumpsys window windows`에 context가 없었다. 이후 Life의 `mCurrentFocus=null`과 OS의 short/full activity 표기 차이로 core instability를 실제 발견했다. Observed resumed activity fallback 및 ComponentName 정규화 뒤 3개 root 전체를 재실행해 통과했다. 초기 실패 artifacts는 보존했으며 최종 결과와 혼합하지 않았다.

**Artifact audit:** 17/17 saved observations의 fingerprint JSONL replay bytes 일치, required hashes/metadata 존재, XML 중복 없음: PASS. 원본 `device_observations.json`, `state_fingerprints.jsonl`, `device_smoke_summary.json`, `artifact_audit.json` 및 `device_smoke_run3.log`로 추적 가능하다. Real dialog 발생/영어 locale 검증은 하지 않았다.

## 16. Known Limitations

1. Core는 coarse navigation context다. 동일 activity/tab의 subpage 구분에는 caller의 persistent markers와 추가 transition evidence가 필요하다. Hash 자체는 state equality가 아니다.
2. General ID-bearing label을 제외하므로 label만 다른 화면이 collision할 수 있다. Exact bounded state vocabulary 밖의 복합 상태 문구도 전체 해석하지 않는다.
3. Helper flat tree와 XML 모두 partial observation이다. Missing/unknown/empty를 state NEW, SAME 또는 terminal completion으로 승격할 수 없다.
4. XML/Helper/window/activity 수집은 sequential이다. Async UI 변화, 여러 display/window, input-method foreground 등으로 conflicting/unknown context가 남을 수 있다. CLI는 캐시된 마지막 activity로 채우지 않는다.
5. Overlay detector는 기존 dismissal 중심 heuristic이다. `unknown/observed=false`가 dialog 부재를 증명하지 않는다. Dialog component 차이는 unit fixture로 검증했고 real overlay smoke는 하지 않았다.
6. ko/en structural fixtures만 검증했다. ID 없는 번역, role/schema/UI version 변경, unknown dynamic units와 bucket 경계는 fingerprint를 바꿀 수 있다. Cross-locale/state equality는 미구현이다.
7. Positional identity는 durable object identity가 아니다. Raw path/instance ID changes는 transient에 남고 normalized multiset는 tree ancestry 전체를 보존하지 않는다.
8. Live diagnostic capture 및 verbose positional diagnostics에는 비용이 있다. 현재 도구는 opt-in이며 production run performance에 포함하지 않았다.
9. Python suite의 기존 xlsxwriter skip 및 cache permission warning이 남아 있다. 실행한 전체 suite에서 failure/error는 없다.

## 17. Phase 2B Preconditions

Phase 2B foundation 작업은 진행 가능하다. 다음을 equality contract에서 먼저 고정해야 한다.

- SAME/DIFFERENT/UNKNOWN의 screen / interaction / viewport 범위와 source availability 정책. 동일 hash만으로 SAME 금지, missing/ambiguous에서 UNKNOWN 유지.
- Root 밖 persistent marker/selected local pane 관찰 계약. Same-activity/tab의 다른 subpage, recycled ID/bounds, identical normalized multiset의 false merge corpus를 포함한다.
- Reviewed replay manifest: 현재 Home/Devices/Life 반복, actual focus pair, Home scroll pair와 typed-value/locked/overlay/ko-en fixtures를 seed로 사용한다. Fixture는 synthetic임을 표시하고 실제 device observations와 분리한다.
- Expected component relations는 이번 검증대로 유지한다: 반복→동일 normalized hashes; focus-only→core/viewport 유지; selected root→core 변경; scroll→core 유지/viewport 변경; overlay→overlay 변경; locked/unlocked→semantic hash 변경. 이를 final state equality 규칙으로 자동 승격하지 않는다.
- Observed scope/overlay ambiguity, label-only subpage 및 locale pair의 추가 evidence를 보강한 뒤 UNKNOWN을 해소한다. Expected route labels로 observed context를 채우지 않는다.
- Normalization/schema version compatibility 및 environment partition 검토. Existing strict actual visit, ACK/focus separation, scroll evidence, terminal/QA authority를 계속 보호한다.
- Registry/persistence는 Phase 2C, graph/exploration/navigation activation은 이후 단계다. Phase 2B도 기존 runtime selection에 feedback하지 않는다.

## 18. Verdict

```ini
PHASE2A_VERDICT=PASS_WITH_LIMITATIONS
READY_FOR_PHASE2B=YES
ARTIFACT_AUDIT_RESULT=PASS
PRODUCTION_RUNTIME_CHANGED=NO
HELPER_CHANGED=NO
PRODUCTION_CONFIG_SHA256=6dd5d8a191d21e4366ed2513627d97b37515a1e2ae9c2ed342b8d2317fecb964
PHASE2A_COMMITTED=NO
PHASE2A_PUSHED=NO
```

Phase 1 publication 완료 후 Phase 2A 범위만 구현/검증했다. 기존 tracked runtime/config/Helper 파일의 diff는 없으며 production fingerprint consumer도 없다. 사용자 기존 `out/`는 보존했다. 모든 생성된 smoke/test artifacts는 ignored `output/`에 있고 stage하지 않았다.

최종 Git state:

```text
$ git branch --show-current
feature/phase2-state-model

$ git status --short
?? docs/design/phase2a-state-fingerprint-contract.md
?? out/
?? tb_runner/state_fingerprint.py
?? tests/test_state_fingerprint.py
?? tests/test_state_fingerprint_diagnostic.py
?? tools/state_fingerprint_diagnostic.py

$ git diff --stat
(no output)

$ git diff --name-only
(no output)

$ git diff --cached --stat
(no output)

$ git rev-parse HEAD
4c829536503503a1d963ff5144cfd6bed576a84f
```

Phase 2A의 다섯 파일이 모두 untracked 상태라 일반 `git diff --stat`에는 나타나지 않는다. 이 보고서의 changed-files 목록과 `git status --short`가 추가 범위를 기록한다. Phase 2A는 commit/push하지 않았으며 별도 사용자 승인 뒤 publish할 상태다.
