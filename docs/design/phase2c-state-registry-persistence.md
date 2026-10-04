# Phase 2C — State Registry / Persistence

2026-10-05 · `feature/phase2-state-model` · [2A contract](phase2a-state-fingerprint-contract.md) · [2B Gate](phase2b-state-identity-equality.md).

## 1. Verdict / Gate

```ini
PHASE2C_VERDICT=PASS_WITH_LIMITATIONS
REGISTRY_STATE_COUNT=3
UNSAFE_MERGE_COUNT=0
PERSISTENCE_ROUNDTRIP=BYTE_IDENTICAL
PYTHON_TEST_RESULT=2806 passed, 0 failed, 0 errors, 1 skipped
FINAL_DEPENDENCY_REGRESSION=2850 passed, 0 failed, 0 errors, 1 skipped
PRODUCTION_RUNTIME_CHANGED=NO
READY_FOR_PHASE2D=YES
```

2B Gate를 기록한 후 2C를 구현했고, 2C Gate를 확인한 후 2D로 진행했다. State count 3은 fresh 실단말 corpus의 값이다. Synthetic 상태와 unknown/corruption 사례는 독립 테스트로 검증했다.

## 2. Registry responsibility and IDs

`StateRegistry.observe(StateObservation, optional VerifiedScrollEvidence)`는 기존 대표 관찰과 equality를 비교해 CREATED / REUSED / UNRESOLVED를 반환한다. Logical ID는 namespace 안에서 순차 할당하고 저장한다. 예: `phase2-diagnostic:state:00000001`. Fingerprint hash나 coarse scope key를 ID로 사용하지 않는다.

같은 saved registry의 재시작·재진입에서는 ID가 유지된다. 독립 empty registry의 할당 번호는 입력 순서에 따라 달라질 수 있다. 별도 registry의 순서 변경 검증은 번호가 아닌 logical partition을 비교한다. Global cross-registry identity는 구현하지 않았다.

입력 checksum과 secondary 구조를 검증하고 평가가 완료된 뒤 데이터를 갱신한다. Export는 독립 복사본이다.

## 3. Records and metrics

Record에는 state_id, identity schema, scope_index_key, canonical observation reference, first/last seen(timestamp+sequence), observation_count, unique observation references, representative references, viewport observations, scenario/context provenance와 확인 가능한 overlay base_state_id를 저장한다.

호출 수와 unique observation 수는 분리된다. 같은 observation 재입력 시 events와 observation_count는 증가하지만 document는 중복 저장하지 않는다. Viewport별 counts/references도 보존한다. 이 수치는 physical visits나 화면 탐색 완료 수치가 아니다.

동일 normalized behavior의 대표 관찰로 비교 중복을 줄인다. Incoming scroll proof가 비대표 관찰에 연결돼 있어도 실제 endpoint를 비교한다. Secondary labels를 대표 선택에 포함해 coarse collision을 숨기지 않는다.

## 4. Dedup and ambiguity

- 다른 ambiguous candidate가 없고 SAME candidate가 하나일 때 REUSED.
- 기존 후보가 모두 DIFFERENT이고 입력이 usable이면 CREATED.
- Missing/ambiguous input, 여러 SAME, 후보 충돌은 UNRESOLVED. State ID는 null이며 observation과 equality evidence를 저장한다.
- 한 state의 여러 viewport에서 SAME과 AMBIGUOUS가 섞이면 verified membership을 인정할 수 있다. DIFFERENT도 섞이면 AMBIGUOUS로 되돌린다.
- Verified scroll은 같은 state에 viewport를 추가한다. 확인된 overlay는 2B 계약에 따라 별도 interaction record로 저장하고 확인 가능한 base reference를 남긴다.

Coarse-collision fixture의 두 번째 관찰은 UNRESOLVED이며 state count는 1이다. Unknown activity의 첫 관찰은 state count 0이다. 미해결 관찰을 강제 merge하거나 새 state로 만들지 않는다.

## 5. Persistence contract

Schema는 `state-registry-v1`. Envelope에 equality/observation versions, namespace, next allocation sequence, states/observations/continuities/events와 content_sha256을 저장한다. Canonical UTF-8 JSON + LF이며 checksum은 digest를 제외한 payload를 대상으로 한다.

같은 directory의 unique temporary file에 write/flush/fsync한 뒤 `os.replace`로 교체한다. 실패하면 기존 file을 보존하고 자신이 만든 temporary file을 정리한다. Concurrent writer locking은 제공하지 않는다.

Load는 version/checksum, observation/fingerprint checksums, secondary 구조, continuity references, duplicate IDs/JSON keys와 event sequence를 검증한다. Events를 fresh registry에 재적용한 결과와 전체 known payload가 일치해야 한다. Orphan reference, count 또는 resolution 변조는 outer checksum을 다시 계산해도 거부한다.

Unknown envelope fields는 비실행 metadata로 보존한다. Unknown schema/equality version은 거부한다. Semantic collection의 임의 추가 필드 호환성을 보장하지 않는다. Load는 단말 action을 실행하지 않는다.

## 6. Unit and full regression

원래 2C Gate: 신규 **33 passed**, 전체 **2806 passed / 0 failed / 0 errors / 1 skipped**, 71.85초. Empty/create/reuse/focus/scroll/nonrepresentative endpoint/root/overlay/semantic/ambiguity/locale/count/roundtrip/restart/determinism, checksum 재계산 후 corruption, unknown envelope, duplicate JSON key, atomic replacement 실패를 검증했다.

2D 재진입에서 Life의 `map_area` 위치 확인 age가 `59분 전 → 1시간 전 → 지금`으로 변했다. Equality의 해당 필드 비교 정규화를 대표 선택에도 적용했다. 저장된 sidecar/fingerprint는 변경하지 않았으며 장치 이름, 다른 상태 문구, 다른 resource ID는 보존한다. Registry 보호 테스트를 추가해 최종 **34 passed**다.

최종 관련 2B/2C/2D **125 passed**, 전체 **2850 passed / 0 failed / 0 errors / 1 skipped**, 73.47초. Evidence: `output/phase2_state_model_20261005/final_regression2.xml`.

```powershell
python -m pytest tests -q --basetemp output/phase2_state_model_20261005/pytest_final_full2 --junitxml output/phase2_state_model_20261005/final_regression2.xml
```

기존 `.test_tmp` 접근 제약 때문에 전체 suite는 sandbox 밖에서 실행했다. 기존 xlsxwriter thumbnail skip과 pytest cache permission warning은 남아 있다. 테스트 삭제/exclude/assertion 약화는 없다.

## 7. Fresh device corpus

Evidence: `output/phase2_state_model_20261005/phase2c_device/`와 `phase2c_device.log`. Fresh Home 반복·실제 focus 이동·실제 scroll, Devices/Life 각 3회, Home 재진입, optional room popup/dismiss를 18 observations로 등록했다. 필수 equality 12 comparisons PASS.

| 관찰 | Registry 결과 |
|---|---|
| Home 반복 / 실제 focus 이동 | state 00000001 재사용 |
| Home verified scroll | 같은 state, viewport 2개 |
| Devices | 별도 state 00000002 |
| Life | 별도 state 00000003 |
| Home 재진입 / popup dismiss | state 00000001 재사용 |
| Popup의 verified selected context 누락 | UNRESOLVED, merge/state 증가 없음 |

State 3, events 18, unresolved 1, unsafe merge 0. Save/load는 byte equivalent이며 loaded registry에 Home을 재입력해도 같은 ID와 state count를 유지한다. 재입력 count는 `state_registry_restarted.json`에 별도로 저장했다.

2D에서 같은 저장 파일을 로드해 root 순서를 바꿔 재진입하고 4회 focus churn과 scroll/down-up을 추가 검증했다. 최종 수치와 별도 process restart 결과는 [Phase 2 closure](phase2-state-model-closure.md)에 기록한다.

## 8. Changed files and isolation

2C 신규: `tb_runner/state_registry.py`, `tests/test_state_registry.py`, 이 문서. 2D에서는 대표 선택 정규화와 보호 테스트만 추가했다. 2A 다섯 파일과 기존 `out/`는 보존했다. Smoke harness/output은 ignored `output/`에만 있다.

Registry 결과를 production selection/termination/max_steps/navigation에 연결하지 않았다. Config/Helper/APK 변경, Full32, Auto Discovery/graph/action selector 구현, commit/push/merge는 없다.

## 9. Limitations

Partial observations와 unknown overlay는 unresolved로 남을 수 있다. Registry는 whole-app identity, physical visit 또는 terminal completeness의 authority가 아니다. Event-replay load 비용과 artifact 크기는 corpus 확대 시 재평가해야 한다. Persistent local ID는 global ID가 아니다. Parallel writer locking, navigation resume와 automatic action policy는 범위 밖이다.

## 10. Phase 2D readiness

```ini
READY_FOR_PHASE2D=YES
```

State/viewport dedup, unsafe merge 0, byte-equivalent persistence, restart reuse와 regression 0 failed를 확인했다. 2D에서는 curated/2A/2B/2C artifacts와 fresh reordered device corpus, focus churn, scroll/revisit, 별도 process load/replay 및 unknown/partial cases를 검증한다.
