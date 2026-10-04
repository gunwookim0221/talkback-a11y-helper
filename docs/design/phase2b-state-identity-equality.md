# Phase 2B — State Identity / Equality

Date: 2026-10-05. Branch: `feature/phase2-state-model`. Baseline: `4c829536503503a1d963ff5144cfd6bed576a84f`.

## 1. Verdict / Gate

```ini
PHASE2B_VERDICT=PASS_WITH_LIMITATIONS
EQUALITY_COLLISION_BLOCKER_COUNT=0
PYTHON_TEST_RESULT=2773 passed, 0 failed, 0 errors, 1 skipped
PRODUCTION_RUNTIME_CHANGED=NO
READY_FOR_PHASE2C=YES
```

Gate는 전체 regression, synthetic collision/semantic/unknown tests, fresh device 필수 12 comparisons 통과를 확인한 뒤 열었다. 2C 구현은 이 Gate 이후에 시작한다. Phase 2A의 다섯 파일과 기존 `out/`는 그대로 보존했다. Full Run/Helper/APK/config/commit/push/merge는 없다.

## 2. Inputs and model separation

Source: [Phase 1](phase1-state-auto-discovery-gap-analysis.md) §6–8, §20–21 및 [Phase 2A](phase2a-state-fingerprint-contract.md) §16–17.

- `StateFingerprint`: 기존 관찰/normalized component/hash. Schema와 구현 수정 없음.
- `StateObservation`: fingerprint + secondary normalized label/semantic evidence + declared coverage/partition/source. Frozen model과 canonical serialization. Raw XML을 중복 저장하지 않는다.
- `StateEqualityResult`: SAME/DIFFERENT/AMBIGUOUS, base relation, logical/viewport/overlay relation, reasons, matching/differing components, confidence 및 observation refs.
- `StateIdentity`: 이후 Registry에서 부여/지속하는 logical ID. `scope_index_key`는 coarse index일 뿐 unique ID가 아니다. Fingerprint hash를 state_id로 대입하지 않는다.

Bare hash 또는 secondary evidence 없는 fingerprint를 equality API에 넣으면 TypeError다. Same artifact의 raw observations 또는 versioned StateObservation sidecar가 필요하다.

## 3. Equality dimensions

| Dimension | 분류 | 정책 |
|---|---|---|
| package/activity | HARD_IDENTITY | 관찰된 값 변경은 DIFFERENT; missing은 AMBIGUOUS |
| observed navigation context/selected tab | HARD_IDENTITY | 실제 selected context; requested route 사용 금지 |
| environment partition | HARD_IDENTITY | 양쪽 known 값 변경은 DIFFERENT; 한쪽만 있으면 AMBIGUOUS |
| persistent marker structure/semantics | HARD_IDENTITY | caller가 실제 persistent marker를 공급한 경우 구조 변경 구분 |
| normalized body multiset/secondary labels | SOFT_IDENTITY | 동일하면 bounded SAME; 미확인 label/subpage 변경은 AMBIGUOUS |
| meaningful semantic state | HARD_IDENTITY | unambiguous same-position correspondence의 enabled/checked/selected/locked/connected 등 변경은 DIFFERENT |
| viewport geometry/capability | VIEWPORT_ONLY | 별도 bool; 변경만으로 screen DIFFERENT/SAME을 강제하지 않음 |
| overlay | HARD_IDENTITY (interaction) | observed overlay 변경은 distinct interaction; 확인 가능한 base relation 보존 |
| locale | DIAGNOSTIC_ONLY | reviewed aliases만 사용; 모르는 번역은 AMBIGUOUS |
| focus/timestamp/step/raw digest/instance IDs | TRANSIENT | state split 근거로 사용하지 않음 |
| source/unknown/coverage/reason evidence | DIAGNOSTIC_ONLY | availability/conflict를 SAME 판단의 guard로 사용 |

SAME은 관찰된 구성요소 범위의 relation이다. Whole-screen completeness, overlay absence 또는 cross-version global identity를 증명하지 않는다. Confidence는 BOUNDED_OBSERVED이며, 부분 관찰이 full 관찰과 자동으로 같아지지 않는다.

## 4. Focus and viewport

Focus-only changes는 normalized body/context를 유지하면 SAME이다. Focus proof/visit credit는 기존 runtime authority에 남는다.

Viewport 변경에 대해 logical SAME을 인정하려면 `VerifiedScrollEvidence`가 정확한 before/after observation IDs에 연결돼야 한다. 생성 조건은 기존 transition의 SCROLL_MOVED, actual success, viewport_changed, 유효한 서로 다른 legacy viewport signatures, observation에 실제 보관된 signatures 일치, normalized viewport 차이, known vertical axis다. ACK만으로 생성할 수 없다. 다른 capture timestamp를 가진 관찰에 proof를 재사용할 수도 없다.

Movement 없이 같은 coarse core와 다른 body/geometry만 관찰하면 AMBIGUOUS다. Evidence는 pair relation을 검증하는 진단 정보이며 action/state graph 또는 runtime navigation selector가 아니다.

## 5. Semantic values and locale

2A dynamic normalization을 재사용해 typed temperature/battery/time 변동을 SAME으로 취급한다. Secondary layer는 ID 때문에 2A hash에서 빠진 label도 보존한다. Full-label locked/unlocked/open/closed/online/offline/loading 및 connected/disconnected의 제한된 ko/en vocabulary를 사용한다. Enabled/checked/selected의 실제 bool 변경을 구분하며 unknown을 false로 채우지 않는다.

Known Home/Device ko/en fixture는 structural SAME candidate다. 미등록 번역은 AMBIGUOUS이며 임의 text 전체를 제거하지 않는다. 같은 resource ID의 여러 instance는 list/multiset로 유지한다. Geometry가 겹친 중복 객체의 의미 상태 변경은 AMBIGUOUS로 남긴다.

## 6. Coarse collision analysis

Fixture의 같은 `pkg:id/card`, 같은 bounds/class, 같은 root에서 `Settings subpage`와 `Details subpage`는 **core뿐 아니라 전체 2A fingerprint_hash도 동일**하다. Secondary normalized labels가 다르므로 equality는 AMBIGUOUS다. 이를 SAME 또는 다른 화면임이 확정된 DIFFERENT로 강제하지 않는다. Actual persistent marker resource 구조가 다른 fixture는 DIFFERENT다.

Raw fingerprint collision은 재현됐다. Unsafe equality merge/collision blocker는 없다. Registry는 이 AMBIGUOUS를 unresolved로 보존해야 한다.

실제 2A scroll artifact의 동일 bounds/ID 없는 FrameLayout 수량 3→4 변화도 재현했다. Neutral container count는 viewport에 남긴다. Duplication의 known semantic-state set이 달라지면 AMBIGUOUS를 유지하며, 수량만 달라지는 verified scroll pair는 logical SAME이다. 이를 보호하는 별도 regression을 추가했다.

## 7. Serialization and evidence

Schemas: `state-observation-v1`, `observed-discriminators-v1`, `state-equality-v1`, `logical-state-identity-v1`, `state-scroll-continuity-v1`.

Same inputs/evidence는 동일 canonical result를 생성한다. Observation ID는 fingerprint/transient/secondary/coverage를 포함한 document checksum이며 state ID가 아니다. Saved observation 및 기존 fingerprint component/hash를 load 시 검증한다. Unknown/incompatible schema 또는 orphan scroll refs는 거부한다.

## 8. Tests

새 2B tests: **48 passed**. 2A 포함 targeted coverage는 기존 52개와 합쳐 100개다. Whole Python regression: **2774 collected / 2773 passed / 0 failed / 0 errors / 1 skipped**, 72.00 seconds.

```powershell
python -m pytest tests -q --basetemp output/phase2_state_model_20261005/pytest_2b_full --junitxml output/phase2_state_model_20261005/phase2b_regression.xml
```

기존 `.test_tmp` 권한 제약 때문에 sandbox 밖에서 전체 suite를 실행했다. Xlsxwriter 없는 기존 thumbnail test skip과 기존 pytest cache permission warning은 남았다. Tests 삭제/exclude/assertion 약화는 없다.

최소 요구한 exact/focus/roots/scroll/overlay/dynamic/semantic/order/locale/collision/insufficient/partial-full을 모두 포함한다. Additional cases: unknown flags, ambiguous duplicate geometry, partition mismatch, checksums, serialization, proof linkage/orphan, neutral container count 변화.

## 9. Fresh device verification

Serial R3CX40QFDBP / SM-F741N, USB charging/battery 50%, Helper READY 확인. 처음 런처에서 시작한 scope-check 실패는 별도 artifact로 보존했다. Package manager가 resolve한 실제 launcher component `com.samsung.android.oneconnect/.ui.SCMainActivity`를 정상 실행한 뒤 재개했다. Force-stop/reset/config 변경은 없다.

Authoritative evidence: `output/phase2_state_model_20261005/phase2b_device_run2/` 및 `phase2b_device_run2.log`.

| Case | Result |
|---|---|
| Home 3 observations | 반복 2 comparisons SAME / viewport equal |
| Actual Home focus A→B | 두 moved ACK 뒤 실제 accessibilityFocused=true; SAME / viewport equal |
| Home actual vertical scroll | SCROLL_MOVED; logical SAME / viewport DIFFERENT |
| Devices 3 observations | 반복 2 comparisons SAME |
| Life 3 observations | 반복 2 comparisons SAME |
| Home vs Devices / Life | 각각 DIFFERENT |
| Home 재진입 / optional popup dismiss 후 | 각각 SAME / viewport equal |

총 18 captures, 필수 12 comparisons PASS. Scroll counts 35→33, persisted 11/new 22/disappeared 24는 viewport observations이며 physical visits가 아니다.

Optional room-selector popup을 열고 항목 선택 없이 Android Back으로 닫았다. 기존 detector는 overlay를 확정하지 못했고 popup capture에서는 selected context가 사라졌다. Equality는 AMBIGUOUS로 보존했다. 이를 실제 dialog SAME/DIFFERENT 성공으로 보고하지 않는다. Unit fixture의 dialog/popup/bottom-sheet/permission overlay는 각각 distinct interaction/base relation을 검증했다.

## 10. Changed files

2B 신규: `tb_runner/state_observation.py`, `tb_runner/state_equality.py`, `tests/state_model_fixtures.py`, `tests/test_state_equality.py`, 이 문서. Diagnostic smoke와 outputs는 ignored `output/`에만 있다. 기존 2A implementation/contract files는 변경하지 않았다.

## 11. Limitations

- Equality는 observed/partial scope다. Empty/missing/contradictory/coverage mismatch는 AMBIGUOUS이며 real popup의 unknown context도 같은 정책이다.
- Root 밖 subpage, unreviewed locale/text와 new viewport에 continuity가 없으면 unresolved가 늘 수 있다. Conservative ambiguity를 success나 NEW state로 바꾸지 않는다.
- Meaningful state correspondence는 positional 구조가 명확한 경우로 제한한다. Duplicate/recycled geometry의 logical object identity를 새로 구현하지 않는다.
- Bare fingerprints만으로 collision secondary labels를 복원할 수 없다. Raw evidence 또는 StateObservation sidecar가 필요하다.
- Schema compatibility와 scope guard가 production completeness/visited-state authority를 대신하지 않는다.

## 12. Phase 2C readiness

```ini
READY_FOR_PHASE2C=YES
```

Deterministic equality, focus/roots/viewport/semantic separation, collision의 안전한 AMBIGUOUS 처리 및 0 regression failures를 확인했다. 2C에서는 AMBIGUOUS 무조건 merge/new 금지, persistent ID allocation, observation/viewport retention, version/checksum/ref integrity, atomic save와 restart replay를 구현한다. Action selection/graph/runtime control은 연결하지 않는다.

### 2D 재진입에서 발견한 typed age 보정과 재검증

Life `map_area`의 위치 확인 문구가 `59분 전 → 1시간 전 → 지금`으로 변하면서 기존 secondary label 비교가 AMBIGUOUS가 되는 두 번의 smoke 실패를 보존했다. 비교 시 이 resource ID의 명시적인 위치 확인 age만 정규화했다. 숫자·단위, `지금/방금`, 영어 equivalent를 처리하며 장치 이름·다른 ID·다른 상태 문구를 제거하지 않는다. 저장된 sidecar와 기존 2A fingerprint bytes는 수정하지 않았다.

최종 2B tests는 **55 passed**, 2B/2C/2D 관련 tests **125 passed**, 전체 regression은 **2850 passed / 0 failed / 0 errors / 1 skipped**, 73.47초다. Authoritative 재진입 smoke는 `output/phase2_state_model_20261005/phase2d_device_run3/`이며 필수 비교 23/23, 새 state 0, root ID 3개 유지다. 기존 2B Gate 조건을 다시 확인했으며 Gate verdict와 다음 단계 readiness는 유지된다. 최종 replay·보존 감사는 [Phase 2 closure](phase2-state-model-closure.md)에 기록한다.
