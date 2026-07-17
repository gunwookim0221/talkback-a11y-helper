# TalkBack Phase 10.3B — Comparator Core

상태: **Implemented**

기준일: 2026-07-17

기준 commit: `2b6f20522266c104f3bbdaeecce4c82bfd4ef2e9`
(`origin/main`과 동일, Phase 10.3A/10.3B 변경은 미커밋)

범위: canonical input adapter, One Connect version policy,
ComparisonCompatibilityKey, read-only baseline selection, compatibility grade,
aggregate delta와 deterministic core result

## 1. Scope

Phase 10.3B는 Approved Baseline과 Candidate를 같은
`talkback-comparator-input-v1`로 정규화하고, 기존 EnvironmentFingerprint/BaselineKey의
full-version exact lookup에 의존하지 않는 predecessor selector를 구현한다. 선택된 입력에 대해
Environment, Scenario, Coverage, Identity, Traversal, Recovery, Reconciliation, Profiler와
limitation issue-set aggregate를 비교한다.

구현 모듈:

- `tb_runner/comparator_schema.py`
- `tb_runner/comparison_input.py`
- `tb_runner/app_version.py`
- `tb_runner/comparison_compatibility.py`
- `tb_runner/baseline_selector.py`
- `tb_runner/aggregate_comparator.py`
- `tb_runner/comparator_core.py`

일반 node matching, text/speech observation normalization, limitation exact binding, final verdict,
CLI/Frontend/report writer와 repository mutation은 포함하지 않는다. Comparator는 Candidate,
Approved package, catalog/index/lifecycle/CAS/source artifact를 변경하지 않는다.

## 2. Input Adapter

`adapt_approved_baseline()`과 `adapt_candidate()`는 다음 공통 `ComparatorInput`을 만든다.

- identity:
  source kind/ID, document integrity digest, source/comparison/fingerprint schema map
- environment:
  app package/versionName/versionCode, locale, Android/One UI/TalkBack major/package,
  device family/form factor, traversal/identity/collection contracts, runtime/scenario hashes,
  comparison feature flags
- scenario:
  selected IDs, FULL/TARGETED, registry/set/order hash, executed/terminal count
- aggregate:
  run/Coverage/Identity/Recovery/Reconciliation/Profiler normalized summary
- reviewed limitations:
  Approved baseline은 `known_limitation_snapshot`, Candidate는 현재 limitation snapshot
- artifact:
  required/optional logical or content-addressed reference와 data availability
- provenance:
  revision/state/source IDs/commit 등 comparison identity와 분리된 정보

Adapter는 canonical bytes, supported schema, EnvironmentFingerprint source/hash,
BaselineKey source/hash와 required aggregate presence를 검증한다. raw absolute path는 input에
복사하지 않고 `qa-run://`/`artifact://sha256/` reference만 허용한다. source digest는 문서
integrity field이며 compatibility key나 semantic match key로 사용하지 않는다.

현재 Approved core에는 일반 node의 text/speech observation이 없다. 따라서 aggregate는
`AVAILABLE`, `node_text_speech`는 `DATA_UNAVAILABLE /
PHASE_10_3C_NOT_IMPLEMENTED`로 명시한다. Missing data를 aggregate에서 추정하지 않는다.

## 3. Version Parser

`app_version.py`는 One Connect version을 다음처럼 보수적으로 처리한다.

- `1.8.47.24`, `1.8.48` 같은 dotted numeric을 integer tuple로 파싱
- 첫 두 component를 `oneconnect-version-policy-v1` release train으로 사용
- same versionName/different versionCode는 versionCode로 hotfix/build ordering
- numeric versionName과 versionCode ordering이 충돌하면 `UNKNOWN_ORDER`
- opaque/non-standard version은 같은 package에서 versionCode가 둘 다 있을 때만
  MEDIUM-confidence ordering
- 이름과 code 모두 신뢰할 수 없으면 임의 lexical ordering 금지

출력 relation:

- `SAME`
- `UPGRADE`
- `DOWNGRADE`
- `UNKNOWN_ORDER`

Parser는 raw name, numeric tuple availability, train, versionCode, ordering basis/confidence/reason을
모두 보존한다. App version 차이 자체는 incomparability가 아니다.

## 4. ComparisonCompatibilityKey

`talkback-comparison-compatibility-key-v1` source:

```text
identity
  app_package
  locale
device_family
  device_family
  form_factor
platform_family
  android_major
  one_ui_major
  talkback_package
  talkback_major
semantic_contracts
  traversal_contract_major
  identity_contract_major
  collection_contract_majors
  core_feature_flags
app_policy
  policy_id
  release_train
```

Full app version, runtime/scenario hash와 document/path/time은 key source에서 제외한다. Full version은
predecessor ordering에, runtime/scenario hash는 compatibility assessment에 사용한다. Key는
canonical source, deterministic digest, `COMPLETE | INCOMPLETE | UNUSABLE`, missing/incompatible
diagnostic을 가진다. 기존 `talkback-environment-fingerprint-v1`과
`talkback-baseline-key-v1`은 변경하지 않았다.

## 5. Baseline Selection

Selector는 `baselines/lifecycle.jsonl`과 package를 직접 read-only로 읽는다.

1. lifecycle JSON/hash chain 확인
2. APPROVED event의 세 core checksum 확인
3. active `APPROVED`와 historical `SUPERSEDED` package adapter 검증
4. app package와 locale exact hard gate
5. form factor와 semantic contract gate
6. OS/TalkBack/device/scenario/runtime compatibility grade
7. app version predecessor relation
8. grade → active → closest numeric predecessor → versionCode → revision/time 순 ranking

Archived/orphan/corrupt package는 reject trace에 남긴다. Candidate보다 newer인 baseline은
predecessor로 자동 선택하지 않는다. Active가 newer/incompatible이면 historical compatible
predecessor를 선택할 수 있다. Unknown ordering이나 downgrade-only 후보는 자동 확정하지 않고
`REVIEW_REQUIRED`다. 모든 ranking field가 같은 후보가 둘 이상이면
`MULTIPLE_BASELINE_TIE`이며 manual selection이 필요하다.

결과에는 selected reference, grade/version relation, rationale, 모든 rejected baseline과 reason,
tie와 discovery error가 포함된다.

## 6. Compatibility Grades

- `EXACT_MATCH`
  - same version
  - EnvironmentFingerprint source equivalent
  - same Scenario Set/contracts
- `COMPATIBLE_PREDECESSOR`
  - same package/locale/device family/form factor
  - compatible train의 Candidate upgrade
  - same semantic/runtime/scenario contracts
- `COMPATIBLE_FAMILY`
  - versioned compatible-family pair가 명시적으로 제공되고 다른 review item이 없음
- `REVIEW_REQUIRED`
  - downgrade/unknown ordering
  - scenario/runtime hash 또는 core feature flag 변경
  - Android/One UI/TalkBack major/package 변경
  - unvalidated device family 또는 incomplete compatibility key
- `INCOMPARABLE`
  - package/locale/form factor mismatch
  - traversal/identity/collection major incompatibility
  - unsupported/corrupt canonical source

모든 assessment는 structured reason/review item을 반환한다.

## 7. Aggregate Delta Model

각 dimension은 `UNCHANGED | IMPROVED | REGRESSED | STRUCTURAL_CHANGE |
REVIEW_REQUIRED | DATA_UNAVAILABLE` 중 하나를 반환한다. Phase 10.3B는 이를 최종 PASS/FAIL로
reduce하지 않는다.

Environment:

- platform/package/locale/contract/runtime/scenario hash delta
- comparison feature flags와 collection contract delta
- 별도 `AppVersionComparison`

Scenario:

- common/added/removed ID
- order-only change
- executed/terminal delta

Coverage:

- expected/covered/missed/unknown totals와 rate
- denominator/structural change
- common-scenario totals와 scenario-local aggregate delta
- 새 denominator로 설명되는 missed/unknown 증가는 structural이며 rate 하락만으로 regression 금지
- common aggregate의 covered 손실 또는 denominator로 설명되지 않는 missed/unknown 증가는
  `REGRESSED`

Identity:

- transaction, COMPLETE/PARTIAL/INDETERMINATE count/ratio
- PARTIAL/INDETERMINATE 증가는 `REGRESSED`

Traversal:

- total steps, executed/terminal, anchor abort, repeat-no-progress와 stop-reason distribution
- step 변화만으로 accessibility regression을 확정하지 않음

Recovery/Reconciliation:

- attempts/recovered/failed/result distribution
- PASS/FAIL과 orphan/duplicate/write/anchor integrity delta

Profiler:

- total/scenario runtime, inclusive metric duration/count, major bottleneck delta
- performance `REGRESSED`를 반환할 수 있지만 `accessibility_verdict_effect=NONE`

Limitations:

- issue ID set, binding count, added/removed summary
- raw failure suppression을 적용하지 않음
- exact signature binding은 Phase 10.3C로 defer

## 8. Comparison Result Schema

`talkback-comparison-result-v1` 최소 구조:

```json
{
  "comparison_schema": "talkback-comparison-result-v1",
  "comparison_id": "comparison_<24-hex>",
  "generated_at": "...",
  "comparator_version": "phase10.3b-comparator-v1",
  "comparison_identity": {},
  "baseline_reference": {},
  "candidate_reference": {},
  "compatibility_key": {},
  "selected_baseline_rationale": [],
  "rejected_baselines": [],
  "selection_tie": false,
  "compatibility_grade": "COMPATIBLE_PREDECESSOR",
  "compatibility_reasons": [],
  "environment_delta": {},
  "app_version_delta": {},
  "scenario_delta": {},
  "coverage_aggregate_delta": {},
  "identity_aggregate_delta": {},
  "traversal_aggregate_delta": {},
  "recovery_aggregate_delta": {},
  "reconciliation_delta": {},
  "profiler_aggregate_delta": {},
  "limitation_summary_delta": {},
  "data_availability": {},
  "review_items": [],
  "implementation_warnings": [],
  "errors": []
}
```

`comparison_id` source는 comparator/schema version, baseline/candidate semantic source digest,
compatibility key source, grade/version relation과 tie다. `generated_at`, raw path와 document
integrity digest는 semantic ID source가 아니다. 동일 semantic input을 다른 시간에 실행해도 ID가
같다.

## 9. Read-only Safety

- selector는 `BaselineRepository.list_baselines()` 또는 `rebuild_indexes()`를 호출하지 않는다.
- lifecycle/catalog/index/package/CAS에 write하지 않는다.
- adapter와 comparator는 input object를 deep mutation하지 않는다.
- output은 memory의 canonical dict/string뿐이며 writer/CLI가 없다.
- repository test는 실행 전후 모든 `baselines/` file SHA-256 equality를 확인한다.
- corrupt package fallback과 rejected reason은 input state를 변경하지 않는다.

## 10. Failure Modes

Structured handling:

- `NO_BASELINE`, `NO_COMPARABLE_BASELINE`
- `MULTIPLE_BASELINE_TIE`
- `BASELINE_CORE_MISSING/CHECKSUM_MISMATCH`
- `CANDIDATE_CORRUPT/NON_CANONICAL`
- `UNSUPPORTED_SCHEMA`
- `APP_PACKAGE_MISMATCH`, `LOCALE_MISMATCH`, `INCOMPATIBLE_FORM_FACTOR`
- `INCOMPLETE_COMPATIBILITY_KEY`
- `UNKNOWN_VERSION_ORDERING`, `APP_VERSION_DOWNGRADE`
- `MISSING_REQUIRED_AGGREGATE`
- `OPTIONAL_ARTIFACT_UNAVAILABLE`
- `CORRUPT_FINGERPRINT`, `CORRUPT_BASELINE_KEY`
- lifecycle missing/corrupt/hash-chain mismatch

Candidate adapter 단계의 fatal error는 `INCOMPARABLE` core result로 변환된다. Optional observation
누락은 fatal error가 아니라 해당 dimension `DATA_UNAVAILABLE`이다.

## 11. Tests

`tests/test_comparator_core.py`는 다음을 검증한다.

- 실제 English/Korean Approved package self-compare `EXACT_MATCH`
- patch upgrade와 same-name/versionCode hotfix
- locale/package mismatch
- active predecessor와 historical fallback
- downgrade/unknown ordering
- scenario add/remove/order-only
- Coverage denominator-only non-regression과 covered→missed regression
- Identity INDETERMINATE 증가
- reconciliation failure
- profiler runtime regression 분리
- optional observation unavailable
- multiple tie
- deterministic comparison ID
- repository read-only file checksum
- unsupported schema/corrupt fingerprint
- 실제 repository 두 package/lifecycle/core checksum discovery

Phase 10 environment/candidate/repository regression suite와 repository verify, py_compile을 함께
검증한다.

검증 결과:

- Phase 10.3B 신규: 26 passed
- Comparator + Environment/Candidate/Repository targeted set: 85 passed
- Baseline repository verify: valid, 2 packages, 16 lifecycle events, error/warning 0
- 신규 모듈/test `py_compile`: PASS
- `git diff --check` 및 untracked-file whitespace 검사: PASS

## 12. Known Limitations

- 일반 node observation과 text/speech delta는 구현되지 않았다.
- Candidate raw limitation은 reviewed issue ID가 없을 수 있어 issue-set 비교가
  `STRUCTURAL_CHANGE`가 될 수 있다. exact binding은 10.3C 책임이다.
- Profiler regression threshold calibration이 없어 현재는 runtime 증가를 performance regression
  signal로 표시한다. 접근성 verdict에는 영향이 없다.
- Runtime-config semantic field map이 없어 hash 변경은 `REVIEW_REQUIRED`다.
- Scenario rename alias와 compatible device-family policy registry는 아직 없다.
- Optional evidence artifact는 logical availability를 표시할 뿐 Phase 10.3B에서 resolve/parse하지
  않는다.
- Final PASS/FAIL/PASS WITH LIMITATIONS reducer와 report persistence는 없다.

## 13. Phase 10.3C Handoff

Phase 10.3C 입력은 본 Phase의 selected `ComparatorInput`, compatibility assessment, aggregate
result와 artifact availability다. 구현할 범위:

1. `talkback-comparison-observation-set-v1`
2. evidence/XLSX/coverage source의 read-only observation normalizer
3. Tier 1–3 scenario-local semantic node matching
4. added/removed/split/merge/ambiguous node classification
5. visible/content/state text, speech/announcement deterministic normalization과 delta
6. Coverage candidate-level common cohort transition
7. Known Limitation exact/scope/signature/expiry binding
8. match confidence/evidence refs와 review items

10.3C도 Candidate/Baseline bytes를 수정하지 않으며, observation source가 없으면
`DATA_UNAVAILABLE`을 유지한다. Final verdict reducer와 Markdown/storage는 Phase 10.3D 범위다.
