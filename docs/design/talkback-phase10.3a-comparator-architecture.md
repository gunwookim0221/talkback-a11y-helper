# TalkBack Phase 10.3A — Comparator Architecture & Version-Compatibility Policy

상태: **Architecture decision / implementation 전 설계**

기준일: 2026-07-17

기준 commit: `2b6f20522266c104f3bbdaeecce4c82bfd4ef2e9`
(`origin/main`과 동일)

범위: Comparator 입력, predecessor 선택, 호환성, semantic delta, verdict, 저장 및
Phase 10.3 구현 분할

## 1. Executive Summary

새 One Connect 버전은 기존 Approved Baseline과 비교할 수 있다. 앱 버전 차이는 기본적으로
비교 불가 사유가 아니라 **predecessor ordering과 비교 대상 delta**다. 현재
`EnvironmentFingerprint`와 `BaselineKey`에는 승인된 app-specific release-train policy가 없어서
full version `1.8.47.24`가 direct field로 들어간다. 따라서 `1.8.48.x` Candidate의 exact
fingerprint/key hash는 기존 baseline을 찾지 못한다. Comparator가 catalog의 exact hash lookup만
사용하면 안 되는 이유다.

기존 fingerprint 계약은 변경하지 않는다. 대신 read-only Comparator에
`talkback-comparison-compatibility-key-v1`과 versioned predecessor-selection policy를 둔다.
역할은 다음처럼 분리한다.

| 계약 | 역할 | app version 처리 |
|---|---|---|
| `BaselineKey` | 동일 승인 slot/revision과 lifecycle identity | 현재 full version을 포함한 기존 계약 유지 |
| `EnvironmentFingerprint` | capture 시점 environment source의 exact identity와 integrity lookup | 현재 full version을 포함한 기존 계약 유지 |
| `ComparisonCompatibilityKey` | predecessor 후보를 넓게 찾는 stable compatibility projection | full version 제외; package와 policy-defined release train만 gate |
| `AppVersionDelta` | predecessor ordering, upgrade/downgrade/hotfix/staged rollout evidence | versionName, versionCode, APK digest를 구조화하여 비교 |

선택은 exact active baseline을 먼저 사용하고, 없으면 같은 package/locale/device family에서
active compatible predecessor를 평가한다. active가 version ordering 또는 release-train policy에
맞지 않을 때만 verified historical Approved/Superseded baseline 전체에서 가장 가까운 predecessor를
찾는다. 선택된 후보뿐 아니라 거절된 후보와 이유도 report에 보존한다.

호환성은 `EXACT_MATCH`, `COMPATIBLE_PREDECESSOR`, `COMPATIBLE_FAMILY`,
`REVIEW_REQUIRED`, `INCOMPARABLE` 다섯 등급이다. `1.8.47.24 → 1.8.48.x`처럼 같은 package,
locale, device family/form factor, compatible release train, scenario/collection/traversal/identity
contract를 가진 upgrade는 `COMPATIBLE_PREDECESSOR`로 full semantic comparison을 허용한다.

Comparator는 raw path, XLSX 또는 document digest를 semantic identity로 사용하지 않는다.
canonical source fields가 truth이고 digest는 integrity/lookup accelerator다. UI 변화는 scenario
common set과 evidence-backed semantic node matching으로 추적한다. Coverage는 percentage가 아니라
common cohort의 상태 전이, added/removed candidates와 denominator 변화를 분리한다. Known
Limitation은 raw FAIL을 바꾸지 않고 별도 annotation만 추가한다.

현재 승인 package만으로 가능한 비교 범위에도 한계가 있다. `baseline.json`에는 Coverage
cohort와 aggregate Identity/Recovery/Reconciliation/Profiler는 있지만 모든 일반 node의 visible
text, content/state description, speech observation은 없다. Evidence ledger와 XLSX는 optional이며
현재 승인 package에서 pinned되지 않았다. 따라서 기존 schema를 변경하지 않고 predecessor 선택,
호환성, scenario/Coverage/aggregate 비교는 구현할 수 있지만, 모든 node에 대한 재현 가능한
text/speech 비교를 항상 보장할 수는 없다. 해당 dimension은 artifact가 없을 때
`DATA_UNAVAILABLE`/`REVIEW_REQUIRED`로 정직하게 축소해야 한다.

Phase 10.3은 네 단계로 진행한다.

1. **10.3A**: 본 설계와 정책 확정.
2. **10.3B**: read-only input adapter, version parser, compatibility key, predecessor selection,
   compatibility grade, core schema/result skeleton과 aggregate self/version comparison.
3. **10.3C**: canonical observation normalizer, node/cohort matching, Coverage와
   text/speech/limitation semantic delta.
4. **10.3D**: verdict reducer, Markdown report, immutable local comparison storage, replay/version
   migration과 end-to-end fixtures.

자동 approval, production traversal 변경, Candidate/Baseline mutation은 어느 단계에도 포함하지
않는다.

## 2. Current Baseline Contracts

### 2.1 현재 승인 상태

현재 repository에는 app `com.samsung.android.oneconnect`, versionName `1.8.47.24`,
versionCode `184724010`의 active Approved Baseline 두 개가 있다.

| Locale | Baseline | Fingerprint | Coverage | Identity transactions | Limitations |
|---|---|---|---|---:|---:|
| `en-US` | `baseline_8f00aed49e61a07b_r0001` | `c7b389db…ca7ab0` | `272/521`, missed 107, unknown 142 | 817 | 5 |
| `ko-KR` | `baseline_1f697e9b60c655df_r0001` | `ee1eafba…0bfe7` | `315/561`, missed 104, unknown 142 | 767 | 5 |

두 package 모두 `PASS WITH LIMITATIONS`, reconciliation `PASS`, anchor/orphan/duplicate/write
failure 0, 32개 Full scenario, clean source다. locale는 BaselineKey direct field이므로 두
baseline 사이 직접 text/speech 비교는 금지한다.

### 2.2 BaselineKey

`talkback-baseline-key-v1`은 EnvironmentFingerprint source에 Scenario Set identity를 더한
승인 slot key다.

- direct:
  target app package/release train, locale, scenario registry/runtime config hash,
  selected-scenario set/order/count, traversal/identity contract, comparison feature flags,
  collection contract versions
- family:
  Android major, One UI major, TalkBack package/major, form factor, device family
- `baseline_key_digest`:
  canonical source의 SHA-256 lookup key

현재 `_baseline_key()`는 fingerprint direct source를 그대로 복사하므로 full app version이
BaselineKey에도 들어간다. Repository의 supersede는 같은 BaselineKey digest 사이에서만 허용된다.
따라서 새 app version baseline은 현재 lifecycle 관점에서 새 slot이며, 이것은 기존 immutable
lifecycle 계약으로서 유지한다.

### 2.3 EnvironmentFingerprint와 EnvironmentProfile

`talkback-environment-fingerprint-v1`은 capture time, provenance, commit, path를 제외한
comparison-relevant direct/family source다. `COMPLETE`일 때만 hash를 생성한다. 현재
`target_app_release_train`은 승인된 vendor policy가 없다는 보수적 fallback 때문에 full
versionName이다.

`environment_profile.json`은 값뿐 아니라 `status`, `source`, `captured_at`, `reason`을 가진
capture document다. app versionName/versionCode, Android/One UI/TalkBack, device family/form
factor, display/fold, repository와 runtime contract의 authoritative provenance다.
`document_digest`는 전체 shared profile bytes의 integrity identity이며 semantic comparison
identity가 아니다.

### 2.4 Candidate comparison contract

`talkback-comparison-input-v1`은 다음 normalized summary를 보유한다.

- environment package/version/locale와 EnvironmentFingerprint
- repository commit/dirty
- runtime scenario/config hashes, contracts, flags
- Scenario Set ID 목록/set hash/order hash/count와 FULL/TARGETED
- run scenario status/steps/stop/traversal result
- Coverage numerator/denominator/unknown, scenario summaries, cohort signatures/candidates
- Identity aggregate/distributions
- Recovery aggregate/result distribution
- Reconciliation integrity counts/checks
- Profiler per-scenario runtime, named metric count/duration, counters

Candidate ID는 source IDs, fingerprint source, Scenario Set과 runtime hash의 deterministic
digest다. `created_at`, raw path와 artifact mtime은 ID에 들어가지 않는다.

### 2.5 Approved normalized summaries와 limitation snapshot

Approved `baseline.json`은 Candidate comparison contract의 run/Coverage/Identity/Recovery/
Reconciliation/Profiler summary를 immutable하게 복사한다. Candidate의 raw limitation,
reviewed structured limitation과 `known_limitation_snapshot`을 분리한다. 현재 English/Korean
baseline은 Water/Motion `lowBattery`, Clothing `DASC_0127-25`, Home Monitor settings button과
Clothing derivative failure를 raw FAIL을 유지한 채 reviewed snapshot으로 보유한다.

Coverage candidate의 현재 stable source는 `scenario_id + canonical_id + taxonomy`다. bounds와
label은 cohort digest에 직접 들어가지 않는다. 이 구조는 common cohort 비교에 유용하지만 일반
node의 전체 label/speech observation contract는 아니다.

### 2.6 Artifact manifest

Approved manifest는 logical/content-addressed reference, digest, size, media/schema, required/tier,
sensitivity와 retention을 가진다. run summary, EnvironmentProfile, Evidence Manifest/
Reconciliation, Coverage, Profiler archive는 required/pinned다. Evidence ledger, XLSX, logs와
inventory는 supporting/optional이며 현재 승인 package에서는 pinned reference가 없을 수 있다.

결론적으로 core package는 aggregate comparator에는 충분하지만 모든 node의 text/speech
reduction을 재생성하는 데 항상 충분하지 않다.

## 3. Problem Statement

### 3.1 Exact fingerprint lookup의 한계

Candidate app version이 `1.8.47.24`에서 `1.8.48.x`로 바뀌면
`target_app_release_train` direct value가 바뀐다. 그 결과:

1. EnvironmentFingerprint hash가 달라진다.
2. 그 fingerprint source를 포함한 BaselineKey digest도 달라진다.
3. `catalog.active_baselines[baseline_key_digest]` exact lookup은 기존 baseline을 반환하지 않는다.

따라서 exact lookup만 사용하면 새 버전 Candidate는 비교 가능한 predecessor가 있어도
`NO_BASELINE`처럼 보인다. Hash collision/miss가 semantic comparability 결론이 되어서는 안 된다.

### 3.2 Lookup identity와 comparison dimension

- app package는 identity/hard gate다.
- locale는 text/speech comparison identity/hard gate다.
- app version은 exact slot identity에는 들어가지만 Comparator에서는 predecessor ordering,
  metadata와 verdict evidence다.
- compatible release train은 policy gate다.
- scenario/runtime/engine contract는 byte equality만 보는 identity가 아니라 semantic
  compatibility 판정 대상이다.
- commit과 dirty는 provenance/approval gate이며 app regression 비교 목적상 commit equality를
  요구하지 않는다.

### 3.3 Fingerprint에서 app version을 제거하지 않는 이유

기존 fingerprint는 이미 승인 package, Candidate ID, BaselineKey, lifecycle checksum과 catalog
lookup에 포함됐다. 제거하거나 의미를 바꾸면:

- 기존 hash와 package identity가 깨진다.
- migration 없이 승인 package를 재해석하게 된다.
- 같은 capture가 writer version에 따라 다른 의미를 갖는다.
- supersede slot과 audit trail이 바뀐다.

따라서 `talkback-environment-fingerprint-v1`은 그대로 두고 별도 selection projection을
추가하는 편이 안전하다.

### 3.4 Schema를 변경하지 않고 가능한 범위

가능:

- 기존 canonical source에서 ComparisonCompatibilityKey를 read-only로 파생
- app version parse/order와 predecessor 선택
- environment/scenario/contract compatibility grade
- Coverage common cohort와 aggregate Identity/Traversal/Recovery/Profiler 비교
- 기존 reviewed limitation의 exact/scope/expiry 비교

항상 가능하지 않음:

- 모든 node의 visible/content/state text와 TalkBack speech 비교
- resource-id가 바뀐 일반 node의 ancestry/neighborhood 기반 matching
- raw announcement/duplicate speech 재분석

후자는 현 core summary에 observation이 없고 optional evidence가 보존되지 않을 수 있기 때문이다.
Comparator는 누락 데이터를 합성하지 않는다. Phase 10.3C는 available supporting artifact를
read-only로 normalize하는 `talkback-comparison-observation-set-v1`을 정의한다. 장기적으로 모든
승인에서 semantic 비교를 보장하려면 이 compact observation set을 새 required canonical
artifact로 pin하거나 comparison contract에 additive하게 포함하는 후속 계약 결정이 필요하다.
기존 Approved Baseline/Candidate bytes는 migration하거나 수정하지 않는다.

## 4. Version Compatibility Model

### 4.1 ComparisonCompatibilityKey

이 key는 저장 identity가 아니라 candidate discovery projection이다.

```json
{
  "key_schema": "talkback-comparison-compatibility-key-v1",
  "identity": {
    "target_app_package": "com.samsung.android.oneconnect",
    "locale": "en-US"
  },
  "device_family": {
    "device_family": "galaxy-z-flip6",
    "form_factor": "foldable_phone"
  },
  "platform_family": {
    "android_major": 15,
    "one_ui_major": 7,
    "talkback_package": "com.samsung.android.accessibility.talkback",
    "talkback_major": 15
  },
  "semantic_contracts": {
    "traversal_contract_major": "production-traversal-v2",
    "identity_contract_major": "target-relation-v2+canonical-observation-v1",
    "collection_contract_majors": {},
    "core_feature_flags": {}
  },
  "app_policy": {
    "policy_id": "oneconnect-version-policy-v1",
    "release_train": "1.8"
  }
}
```

`scenario_registry_hash`, selected count/order, runtime-config hash와 full app version은 이 discovery
key에 넣지 않고 별도 compatibility dimension으로 평가한다. 그렇지 않으면 scenario 32→33,
order-only 변경 또는 app patch upgrade가 후보 탐색 자체를 막는다. Key hash가 추가되더라도
source fields가 authoritative다.

### 4.2 App version parsing

Parser 결과는 원문을 보존하고 다음을 구조화한다.

```text
raw_version_name
scheme = DOTTED_NUMERIC | SEMVER | OPAQUE | MISSING
numeric_components
prerelease/build tokens
version_code
release_train
ordering = UPGRADE | SAME | DOWNGRADE | AMBIGUOUS
confidence
policy_id/policy_digest
```

정책:

- `1.8.47.24` 같은 vendor dotted numeric은 SemVer라고 잘못 부르지 않고 각 numeric component의
  tuple로 비교한다.
- 유효한 SemVer는 SemVer precedence를 사용한다.
- leading zero가 의미를 바꾸지 않는 numeric token은 integer로 정규화하되 raw 값을 보존한다.
- opaque/non-semver 문자열은 versionCode가 같은 package/signing lineage 안에서 신뢰 가능할 때만
  ordering 보조 근거로 사용한다.
- versionName과 versionCode가 충돌하면 ordering은 `AMBIGUOUS`이며 자동 predecessor 확정 금지다.
- versionCode는 서로 다른 package, signing lineage 또는 release channel 사이에서 전역 순서를
  의미하지 않는다.

### 4.3 One Connect release-train 정책

본 설계의 초기 policy는 같은 package의 dotted numeric version에서 첫 두 component를 train으로
사용한다. 따라서 `1.8.47.24 → 1.8.48.x`는 같은 `1.8` train의 upgrade다. 이 규칙은
fingerprint 의미를 바꾸지 않고 Comparator policy에서만 적용한다.

Vendor release semantics가 확인되면 policy revision을 올린다. policy ID와 digest는 comparison
결과에 들어가므로 과거 결과를 조용히 재해석하지 않는다. 다른 train은 기본
`REVIEW_REQUIRED`; 명시적 incompatibility matrix가 있으면 `INCOMPARABLE`이다.

### 4.4 Version 상황별 처리

| 상황 | Lookup | Ordering | Comparability/verdict 영향 |
|---|---|---|---|
| same versionName/code | exact 우선 | SAME | 다른 contract 차이가 없으면 EXACT |
| compatible patch/minor 증가 | predecessor search | UPGRADE | 차이 자체는 차단하지 않음 |
| same name, higher code | predecessor search | UPGRADE_BUILD | hotfix/staged build evidence |
| same name, different code + APK hash | predecessor search | UPGRADE/DOWNGRADE_BUILD 또는 AMBIGUOUS | hash 차이는 metadata; 단독 regression 아님 |
| downgrade | historical `<= candidate` 우선 | DOWNGRADE | reverse-only baseline이면 REVIEW_REQUIRED, PASS 금지 |
| opaque version + ordered code | compatible 후보 탐색 | code-based, MEDIUM confidence | REVIEW_REQUIRED unless app policy validates |
| opaque version + no reliable code | same package 후보 탐색 | AMBIGUOUS | REVIEW_REQUIRED, tie 자동 해소 금지 |
| incompatible release train | same-package 후보만 진단 | policy mismatch | REVIEW_REQUIRED 또는 policy-declared INCOMPARABLE |
| package changed | 후보 제외 | N/A | INCOMPARABLE |
| APK hash only changed | 같은 version relation 유지 | metadata | tamper/signing anomaly가 아니면 incomparability 아님 |

APK hash는 version metadata와 signing provenance를 보강하는 verdict evidence다. 예상 version과
APK hash가 모순되거나 signing lineage가 바뀌면 integrity/security review item을 만들지만, 정상
staged rollout의 hash 차이를 접근성 FAIL로 만들지 않는다.

### 4.5 App version의 역할

| 역할 | 정책 |
|---|---|
| baseline lookup discriminator | exact BaselineKey lookup에는 기존 계약상 사용하지만 predecessor discovery의 hard discriminator로 사용하지 않음 |
| predecessor ordering | versionName policy와 versionCode를 사용하며 가장 가까운 `<= Candidate`를 우선 |
| comparison metadata | raw/parsed name, code, train, APK digest와 rollout relation을 모두 report |
| verdict evidence | 접근성 delta가 version change와 함께 나타났다는 provenance; version 차이만으로 FAIL을 만들지 않음 |
| incomparability trigger | package change 또는 policy가 명시한 incompatible train만 해당; 단순 version change는 해당하지 않음 |

## 5. Baseline Selection Policy

### 5.1 후보 수집과 검증

1. Candidate canonical bytes/schema/digest와 referenced EnvironmentProfile을 read-only 검증한다.
2. app catalog에서 active와 historical Approved/Superseded package를 열거한다.
3. lifecycle state, core checksums, BaselineKey/Fingerprint source와 digest를 재검증한다.
4. package가 다른 baseline은 `APP_PACKAGE_MISMATCH`로 reject한다.
5. locale가 다른 baseline은 direct comparison 후보에서 제외한다. cross-locale fallback은 없다.
6. 각 후보에 compatibility grade, app version relation, scenario/contract delta와 rejection reason을
   계산한다.

Archived baseline은 기본 검색에서 제외한다. 명시적 audit replay에서만 opt-in할 수 있다.
Rejected Candidate는 baseline 후보가 아니다.

### 5.2 선택 우선순위

| Selection class | 조건 |
|---|---|
| `EXACT_ACTIVE_MATCH` | active, BaselineKey source/digest exact, validated core |
| `SAME_LOCALE_SAME_DEVICE_FAMILY_PREDECESSOR` | 같은 locale/family/form factor, compatible contracts/train, version `<=` Candidate |
| `SAME_LOCALE_COMPATIBLE_FAMILY` | reviewed device-family/platform compatibility policy가 허용 |
| `CROSS_DEVICE_REVIEW_ONLY` | 같은 locale/package이나 family/form factor가 다르며 common-scenario 참고 비교만 가능 |
| `NO_COMPARABLE_BASELINE` | hard gate를 만족하는 후보 없음 |

같은 class 안의 ranking은:

1. active 상태
2. highest compatibility grade
3. candidate보다 크지 않은 가장 가까운 app version/versionCode
4. scenario common-set과 contract compatibility가 큰 후보
5. approval time이 아니라 explicit version proximity

active가 compatible predecessor이면 historical보다 우선한다. active가 candidate보다 newer,
incompatible train이거나 필요한 common scenarios를 가지지 않으면 historical Approved/
Superseded 중 best predecessor를 찾는다.

### 5.3 Historical baseline 정책

직전 active 하나만 보는 정책은 rollback, parallel staged rollout과 release-train 전환에서 잘못된
predecessor를 고를 수 있다. 따라서 active-first이되 historical search를 허용한다. Historical
baseline도 승인 당시 immutable core checksum과 lifecycle 관계가 검증되어야 한다.

동점 후보가 둘 이상이고 version/proximity/compatibility로 결정할 수 없으면 임의로 최신
approval time을 선택하지 않는다. selection 결과를 `MULTIPLE_BASELINE_TIE`로 두고
`REVIEW_REQUIRED`로 반환한다.

### 5.4 선택 결과 audit

결과에는 다음을 보존한다.

- selected baseline ID/revision/state와 selection class
- compatibility grade와 app version relation
- policy ID/digest
- 각 비교 field의 match/delta/unknown
- 모든 rejected candidate의 ID/state/version/grade/rejection codes
- tie-break trace
- historical predecessor를 사용한 이유

## 6. Compatibility Grades

| Grade | 허용 차이 | 차단 차이 | 비교 범위 | Verdict/승인 제한 |
|---|---|---|---|---|
| `EXACT_MATCH` | provenance time, commit, diagnostic-only profiler metadata | package/locale/key/critical contract mismatch | 모든 available dimension | PASS 가능; 수동 승인 가능 |
| `COMPATIBLE_PREDECESSOR` | compatible train의 newer app version/code/APK, otherwise same family/contracts | downgrade-only/ambiguous ordering, package/locale/family/critical contract mismatch | full semantic + common cohort + added/removed | PASS 가능; 수동 승인 가능 |
| `COMPATIBLE_FAMILY` | reviewed same-family model, OS/One UI/TalkBack patch, display/build drift | unreviewed major/family/form-factor change | full semantic; environment delta 필수 | PASS 가능하나 family policy와 human review 필요 |
| `REVIEW_REQUIRED` | major platform change, partial scenario/registry/runtime meaning change, dirty/incomplete provenance, ambiguous version, cross-device | package/locale mismatch와 unreadable critical schema는 이 등급으로 완화 불가 | common scenario/cohort와 명시된 available dimension만 | 자동 PASS 금지; 결과는 REVIEW_REQUIRED, comparison-backed 승인 금지 |
| `INCOMPARABLE` | 없음 | package/locale mismatch, unsupported critical schema, severe contract incompatibility, no common semantic unit, corrupt canonical input | integrity/diagnostic report만 | verdict INCOMPARABLE; 승인 근거로 사용 불가 |

`COMPATIBLE_FAMILY`는 “비슷해 보이는 model”이 아니라 versioned compatibility policy에 등록된
family relation만 허용한다. `REVIEW_REQUIRED` finding을 사람이 disposition했다고 해서 원본
comparison 결과가 소급 PASS로 바뀌지 않는다. disposition을 포함한 새 report generation 또는
후속 comparison record가 필요하다.

## 7. Comparator Input Contract

### 7.1 Canonical envelope

Comparator 내부 입력은 `talkback-comparator-input-v1` envelope로 통일한다. Baseline/Candidate
문서를 수정하지 않고 adapter가 canonical source에서 파생한다.

```json
{
  "input_schema": "talkback-comparator-input-v1",
  "baseline": {
    "baseline_id": "...",
    "revision": 1,
    "repository_state": "APPROVED",
    "baseline_key": {},
    "environment_fingerprint": {},
    "environment_profile": {},
    "app": {"package": "...", "version_name": "...", "version_code": 0},
    "scenario_set": {},
    "comparison_contract": {},
    "summaries": {},
    "reviewed_limitations": [],
    "artifact_manifest": {}
  },
  "candidate": {
    "candidate_id": "...",
    "environment_fingerprint": {},
    "environment_profile": {},
    "app": {"package": "...", "version_name": "...", "version_code": 0},
    "source_repository": {"commit": "...", "dirty": false},
    "scenario_set": {},
    "comparison_contract": {},
    "raw_limitations": [],
    "artifact_manifest": {}
  },
  "derived": {
    "comparison_compatibility_key": {},
    "app_version_delta": {},
    "observation_availability": {}
  }
}
```

### 7.2 Authoritative source rules

- Baseline state/key/summary는 validated `baseline.json`과 lifecycle이 truth다.
- Environment 값은 exact `environment_profile.json`의 canonical fields가 truth다.
- Candidate normalized metrics는 `comparison_contract`가 truth다.
- digest는 bytes integrity와 lookup accelerator이며 field equality를 대체하지 않는다.
- Candidate/document digest를 semantic identity로 사용하지 않는다.
- absolute/raw path는 canonical input에 넣지 않는다.
- artifact는 `artifact://sha256/...` 또는 validated logical reference로 resolver가 열고, 열린
  bytes의 digest를 다시 확인한다.
- provenance ID/commit/time과 comparison identity를 별도 object에 둔다.
- source schema/normalizer version을 metric마다 보존하고 다른 semantics의 숫자를 강제 합치지
  않는다.

### 7.3 Observation availability

각 dimension은 `AVAILABLE | PARTIAL | DATA_UNAVAILABLE | CORRUPT | UNSUPPORTED`를 가진다.
일반 node text/speech source가 없는 기존 baseline은 aggregate 비교 전체를 막지 않고 해당
dimension만 `DATA_UNAVAILABLE`로 표시한다. 다만 새 raw accessibility failure의 존재를 판정할
자료가 없으면 overall PASS는 허용하지 않고 `REVIEW_REQUIRED`다.

## 8. Scenario Compatibility

Scenario compatibility는 count equality가 아니라 stable scenario ID set과 per-scenario contract를
사용한다.

| 변화 | 결과 | 규칙 |
|---|---|---|
| registry hash 동일, IDs/order 동일 | full comparison | exact scenario contract |
| hash 변경, IDs와 semantic descriptor 동일 | full comparison + metadata delta | byte-only registry drift |
| scenario 순서만 변경 | full per-scenario comparison; traversal-order aggregate review | order-sensitive global metric만 REVIEW_REQUIRED |
| scenario 추가 (32→33 포함) | common 32 + added scenario structural delta | 비교 가능; count mismatch로 차단 금지 |
| scenario 삭제 | common set + removed scenario | removed required scenario는 REVIEW_REQUIRED |
| rename + explicit alias/migration map | common scenario로 비교 | alias revision/evidence 보존 |
| rename, alias 없음 | removed + added | fuzzy name으로 동일 scenario 확정 금지 |
| runtime-config hash 변경, canonical semantics 동일 | full comparison + provenance delta | normalized config field diff가 비어야 함 |
| runtime-config 의미 일부 변경 | affected common scenarios only | REVIEW_REQUIRED |
| feature flag diagnostic-only 변경 | full comparison | metadata |
| core collection/traversal/identity flag 변경 | affected dimension partial/incomparable | overall 최소 REVIEW_REQUIRED |
| traversal/identity contract compatible minor | common comparison + adapter version 기록 | policy-declared compatibility 필요 |
| traversal/identity major 변경 | affected dimension incomparable | overall REVIEW_REQUIRED 또는 전부 critical이면 INCOMPARABLE |
| collection schema additive/adapter-supported | normalized common comparison | adapter와 loss map 기록 |
| collection schema semantic breaking | affected metric incomparable | 숫자 coercion 금지 |

`common_scenarios`, `added_scenarios`, `removed_scenarios`, `renamed_scenarios`,
`order_changed`, `affected_by_runtime_config`를 별도 배열로 report한다. Targeted/partial run은
common scenario exploratory comparison은 가능하지만 baseline approval 근거가 될 수 없고
overall PASS를 만들 수 없다.

## 9. Node Matching

### 9.1 Canonical node observation

Node observation은 scenario-local이며 최소 다음을 가진다.

- observation/scenario/transaction identity와 source evidence refs
- package, role/class, resource ID와 normalized resource family
- visible text, contentDescription, stateDescription, hint
- TalkBack speech/announcement sequence
- structural ancestry/child role signature
- normalized bounds region과 relative geometry
- action role, accessibility state
- predecessor/successor semantic signatures
- traversal step/visit relation

Raw string과 redacted digest를 구분한다. privacy policy로 raw를 보존할 수 없으면 deterministic
normalization 결과와 evidence availability를 명시한다.

### 9.2 Matching tiers

| Tier | Evidence | 허용 판정 |
|---|---|---|
| 1 — Stable identity | same scenario, exact stable resource ID, compatible role/class, stable semantic identity/transaction relation | HIGH confidence one-to-one |
| 2 — Semantic structure | resource family, normalized label/state, ancestry, relative bounds region, action role | HIGH/MEDIUM; multiple independent signals 필요 |
| 3 — Traversal neighborhood | scenario-local text/speech pair, predecessor/successor, visit/order neighborhood, structural signature | MEDIUM/LOW; ambiguity check 필수 |
| 4 — Unmatched | 신뢰 가능한 one-to-one match 없음 | ADDED/REMOVED 또는 AMBIGUOUS |

금지:

- exact bounds 하나만으로 identity 확정
- label 하나만으로 identity 확정
- fuzzy text 하나로 match 확정
- plugin/scenario별 hard-coded matcher
- 낮은 confidence match를 known limitation exact binding으로 승격

### 9.3 Matching result

```json
{
  "match_id": "node_match_...",
  "baseline_node_id": "...",
  "candidate_node_ids": ["..."],
  "classification": "SAME_NODE_CHANGED_SPEECH",
  "tier": 2,
  "confidence": "MEDIUM",
  "score": 0.84,
  "runner_up_score": 0.61,
  "evidence": [
    {"signal": "resource_family", "result": "MATCH"},
    {"signal": "ancestry", "result": "MATCH"},
    {"signal": "bounds_region", "result": "CHANGED"}
  ],
  "evidence_refs": []
}
```

지원 classification:

- `SAME_NODE_UNCHANGED`
- `SAME_NODE_CHANGED_LABEL`
- `SAME_NODE_CHANGED_SPEECH`
- `SAME_NODE_CHANGED_BOUNDS`
- `SAME_NODE_CHANGED_ROLE`
- `ADDED_NODE`
- `REMOVED_NODE`
- `SPLIT_NODE`
- `MERGED_NODE`
- `AMBIGUOUS_MATCH`

Matching은 scenario별 maximum-confidence one-to-one assignment 후 split/merge 후보를 별도
검증한다. top score가 threshold를 넘더라도 runner-up과의 margin이 작으면
`AMBIGUOUS_MATCH`다. threshold/margin은 comparator policy version에 고정하며 report에 기록한다.
LOW confidence match는 regression 확정 근거가 아니라 review evidence다.

## 10. Coverage Comparison

Coverage는 rate가 아니라 set transition으로 비교한다.

### 10.1 Required output

- baseline/candidate expected numerator와 denominator
- cohort hash와 signature-set equality
- common cohort, added candidates, removed candidates
- common candidate의 `COVERED → MISSED`, `COVERED → UNKNOWN`,
  `MISSED/UNKNOWN → COVERED` 전이
- scenario/taxonomy별 transition matrix
- match tier/confidence와 ambiguous count
- baseline/candidate/common-cohort coverage rate
- denominator absolute/relative delta

### 10.2 Verdict

| Coverage verdict | 조건 |
|---|---|
| `UNCHANGED` | common cohort 상태 동일, 구조 변화 없음 |
| `IMPROVED` | 신뢰 가능한 common cohort에서 missed/unknown→covered, 악화 없음 |
| `REGRESSED` | 신뢰 가능한 required common candidate가 covered→missed; unexplained covered→unknown은 severity에 따라 regression/review |
| `STRUCTURAL_CHANGE` | added/removed만 있고 common cohort 접근성 상태가 유지 |
| `REVIEW_REQUIRED` | large denominator shift, required removal, ambiguous/low-confidence match, unknown transition 증가 |

새 UI로 denominator가 증가하고 percentage가 내려가더라도 common cohort가 유지되면 자동
regression이 아니다. 새 required node가 추가됐지만 아직 missed이면 `ADDED_NODE_MISSED` finding을
별도로 만들며, 그것이 접근성 요구 위반인지 scenario policy로 판단한다. 단순 percentage delta는
표시용 파생 값이다.

“significant denominator shift”의 절대/상대 threshold는 실제 fixture calibration 후 policy에
고정한다. Phase 10.3A에서 임의 숫자를 승인하지 않는다.

## 11. Identity/Traversal/Recovery/Profiler

### 11.1 Identity

공통 scenario에서 다음을 비교한다.

- COMPLETE/PARTIAL/INDETERMINATE distribution
- transaction count와 workload-normalized rate
- correlation failure/legacy fallback
- delayed commit, snapback/unstable landing
- verdict/confidence distribution

같은 workload에서 COMPLETE→PARTIAL/INDETERMINATE, correlation failure 증가, unstable landing
증가는 regression 후보다. transaction count 자체는 UI node 수 변화와 분리한다.

### 11.2 Traversal

- requested/executed/terminal
- scenario status, stop reason, step/visit count
- repeated row/duplicate-derived relation
- anchor abort와 progress verdict
- ordering/predecessor/successor changes

Anchor abort, required scenario non-terminal과 reconciliation integrity failure는 critical FAIL이다.
step/visit count 증감만으로 FAIL을 만들지 않는다. node matching 결과와 stop/progress evidence를
함께 본다.

### 11.3 Recovery

- attempt/recovered/failed
- failure reason/result distribution
- recovery type/executor
- scenario-local recovery delta

UI가 바뀌어 recovery attempt가 새로 필요해진 경우는 regression 후보이지만, recovery count만으로
접근성 FAIL을 확정하지 않는다. unrecovered 결과가 traversal terminal/coverage loss와 연결되면
severity가 올라간다.

### 11.4 Profiler

- scenario runtime
- traversal loop
- verification poll
- focus-in-bounds
- recovery executor
- named metric count/duration와 counters

Profiler는 별도 `PERFORMANCE_IMPROVED | PERFORMANCE_REGRESSED | PERFORMANCE_UNCHANGED |
PERFORMANCE_REVIEW_REQUIRED` 축이다. 접근성 overall FAIL과 합치지 않는다. threshold는 동일
scenario/common workload, warm-up policy, absolute+relative delta를 함께 요구한다. inclusive
duration semantics가 다르면 비교하지 않는다.

## 12. Text/Speech Comparison

### 12.1 Normalization

동일 locale에서만 직접 비교한다. field별 raw presence와 normalized value를 분리한다.

- Unicode NFC, locale-aware case/spacing rules
- whitespace/punctuation-only delta
- visible text, contentDescription, stateDescription, hint를 별도 보존
- TalkBack speech와 announcement sequence를 별도 보존
- deterministic dynamic tokenization: count, percentage, time/date, duration, device value
- locale-specific number/plural/punctuation normalization
- policy-defined synonym/role/state equivalence

LLM/fuzzy semantic 추론은 사용하지 않는다. deterministic equivalence rule이 없으면
`AMBIGUOUS`다.

### 12.2 Delta taxonomy

- `TEXT_CHANGED_SPEECH_MATCHED`
- `TEXT_MATCHED_SPEECH_CHANGED`
- `BOTH_CHANGED_EQUIVALENT`
- `BOTH_CHANGED_NON_EQUIVALENT`
- `SPEECH_MISSING`
- `VISIBLE_LABEL_MISSING`
- `NEW_EMPTY_VISIBLE`
- `KNOWN_EMPTY_VISIBLE`
- `UNEXPECTED_SPEECH`
- `DUPLICATE_SPEECH`
- `DYNAMIC_VALUE_ONLY`
- `PUNCTUATION_WHITESPACE_ONLY`
- `LOCALE_EXPECTED_CHANGE`
- `AMBIGUOUS`
- `DATA_UNAVAILABLE`

`SPEECH_MISSING`, `VISIBLE_LABEL_MISSING`, `NEW_EMPTY_VISIBLE`는 새 raw accessibility failure
후보다. `TEXT_CHANGED_SPEECH_MATCHED`는 화면 문구만 바뀌고 접근성 발화가 의도적으로 안정된
경우일 수 있어 review evidence다. `TEXT_MATCHED_SPEECH_CHANGED`는 state/role announcement의
정상 개선일 수도 있으므로 expected speech contract와 비교한다.

Dynamic value가 변해도 type/unit/context가 같으면 `DYNAMIC_VALUE_ONLY`다. 시간/count 값이
사라지거나 잘못된 단위로 발화되면 semantic regression이다. 다른 locale baseline을 가져와
`LOCALE_EXPECTED_CHANGE`로 완화하는 것은 금지한다. 이 분류는 같은 locale 안에서 locale-specific
formatting rule이 설명하는 변화에만 사용한다.

## 13. Known Limitation Comparison

Known Limitation annotation은 raw result와 독립이다.

```json
{
  "raw_result": "FAIL",
  "raw_failure_type": "EMPTY_VISIBLE",
  "limitation_annotation": {
    "classification": "KNOWN_LIMITATION_UNCHANGED",
    "issue_id": "...",
    "revision": 1,
    "binding_confidence": "HIGH"
  }
}
```

### 13.1 Binding 순서

1. issue status/review/expiry와 environment scope 확인
2. same locale/package/release scope 확인
3. scenario 또는 explicit scenario alias 확인
4. node matcher의 stable identity/signature 확인
5. mismatch/raw result와 derivative relation 확인
6. evidence reference와 confidence 기록

### 13.2 결과

| 결과 | 의미 |
|---|---|
| `KNOWN_LIMITATION_UNCHANGED` | valid scope + same issue/signature + same raw failure |
| `KNOWN_LIMITATION_CHANGED` | same semantic node/issue이나 bounds/resource/label/signature drift |
| `KNOWN_LIMITATION_RESOLVED` | node가 남아 있고 raw failure가 사라졌거나 expected accessible output 회복 |
| `NEW_UNREVIEWED_FAILURE` | binding되는 reviewed issue 없음 |
| `LIMITATION_SCOPE_EXPANDED` | 새 scenario/node/release scope로 failure가 확장 |
| `LIMITATION_EXPIRED` | expiry/review date가 지남 |
| `LIMITATION_SCOPE_MISMATCH` | locale/package/train/device scope 밖 |

Bounds 변경만으로 새 issue라 단정하지 않는다. stable identity와 Tier 2 structural evidence가 같으면
`KNOWN_LIMITATION_CHANGED`다. resource ID가 바뀌어도 semantic match가 충분하면 changed/review로
남긴다. 반대로 fuzzy label 유사성만으로 unchanged를 선언하지 않는다.

현재 snapshot의 `environment_scope.app_release_train`은 `1.8.47.24`다. 새 `1.8.48.x`에서 같은
failure가 보여도 자동으로 limitation을 계승하지 않는다. app comparison policy상 두 version은
비교 가능하지만 limitation scope는 별도 계약이므로 `KNOWN_LIMITATION_CHANGED` 또는
`LIMITATION_SCOPE_EXPANDED` review가 필요하다. Reviewer가 새 scope를 수락하기 전 raw finding은
new/unreviewed 상태를 유지한다.

Issue가 사라지면 PASS를 약화시키지 않고 `KNOWN_LIMITATION_RESOLVED` improvement로 보고한다.
Derivative duplicate는 raw row를 보존하되 독립 defect count에서 parent issue와 연결한다.

## 14. Verdict Policy

Overall verdict:

- `PASS`
- `PASS_WITH_LIMITATIONS`
- `REVIEW_REQUIRED`
- `FAIL`
- `INCOMPARABLE`

Reduction 순서:

1. input integrity/schema와 baseline selection
2. compatibility grade와 allowed comparison scope
3. reconciliation/terminal/anchor critical gates
4. scenario/node/Coverage/Identity/Traversal/Recovery/Text/Speech raw findings
5. profiler의 별도 performance verdict
6. Known Limitation annotation
7. unresolved review/data availability
8. overall reduction

### 14.1 FAIL

다음 중 하나면 FAIL이다.

- new unreviewed accessibility failure
- required common node의 speech/visible label loss
- anchor abort 또는 required scenario non-terminal
- reconciliation orphan/duplicate/write/integrity failure
- required canonical artifact corruption
- selected comparable contract 안에서 severe traversal/identity regression
- declared-compatible pair에서 발견된 severe contract incompatibility/corruption

Contract가 단순히 호환되지 않아 delta를 계산할 수 없는 경우는 code regression FAIL로
오표기하지 않고 INCOMPARABLE이다.

### 14.2 REVIEW_REQUIRED

- structural UI change 또는 significant denominator shift
- ambiguous/low-confidence node matching
- scenario add/remove/rename, partial run
- One UI/TalkBack/Android major 변경
- runtime-config semantic 변경
- version ordering/tie ambiguity 또는 dirty/incomplete environment
- limitation signature/scope drift/expiry
- PASS 판정에 필요한 text/speech data unavailable

`REVIEW_REQUIRED`가 하나라도 unresolved이면 PASS/PASS_WITH_LIMITATIONS를 만들지 않는다.

### 14.3 PASS_WITH_LIMITATIONS

- compatibility가 `EXACT_MATCH`, `COMPATIBLE_PREDECESSOR` 또는 reviewed
  `COMPATIBLE_FAMILY`
- 신규 regression과 unresolved review 없음
- raw FAIL은 모두 유효한 reviewed limitation과 exact/accepted binding
- limitation raw result가 숨겨지거나 numerator가 수정되지 않음

### 14.4 PASS

- compatible comparison
- raw FAIL, unresolved review, active limitation 없음
- 필수 comparison dimension available

어떤 verdict도 Candidate를 자동 approve하거나 baseline을 자동 supersede하지 않는다.

## 15. Comparison Schema

Canonical result schema는 `talkback-comparison-result-v1`이다.

```json
{
  "schema_version": "talkback-comparison-result-v1",
  "comparison_id": "comparison_<24-hex>",
  "comparison_identity": {
    "baseline_id": "...",
    "baseline_revision": 1,
    "candidate_id": "...",
    "baseline_semantic_digest": "sha256:...",
    "candidate_semantic_digest": "sha256:...",
    "comparator_version": "phase10.3b-comparator-v1",
    "policy_digest": "sha256:..."
  },
  "generated_at": "2026-07-17T00:00:00Z",
  "baseline_reference": {},
  "candidate_reference": {},
  "compatibility": {
    "grade": "COMPATIBLE_PREDECESSOR",
    "comparison_scope": [],
    "reasons": []
  },
  "baseline_selection": {
    "selection_class": "SAME_LOCALE_SAME_DEVICE_FAMILY_PREDECESSOR",
    "rationale": [],
    "rejected_candidates": []
  },
  "environment_delta": {},
  "app_version_delta": {},
  "scenario_set_delta": {},
  "node_match_summary": {},
  "coverage_delta": {},
  "identity_delta": {},
  "traversal_delta": {},
  "recovery_delta": {},
  "profiler_delta": {},
  "text_speech_delta": {},
  "limitation_delta": {},
  "findings": [],
  "verdict": {
    "overall": "REVIEW_REQUIRED",
    "raw_failure_count": 0,
    "known_limitation_count": 0,
    "review_item_count": 1,
    "reasons": []
  },
  "review_items": [],
  "artifact_references": [],
  "schema_map": {},
  "comparator": {
    "version": "phase10.3b-comparator-v1",
    "node_match_policy": "...",
    "version_policy": "...",
    "verdict_policy": "..."
  }
}
```

`comparison_id` source는 baseline/candidate deterministic semantic reference, comparator version과
policy digest다. `generated_at`, report path, local resolver와 rendering time은 ID source가 아니다.
같은 source/policy/version을 재생성하면 같은 comparison ID다. Comparator나 policy version이
바뀌면 새 ID가 되어 과거 결과를 덮어쓰지 않는다.

각 finding은 최소 `finding_id`, dimension, classification, severity, scenario/node/match refs,
baseline/candidate raw value, normalized delta, compatibility scope, confidence, raw result,
limitation annotation, evidence refs와 review state를 가진다.

## 16. Storage and Lifecycle

권장 layout:

```text
comparisons/
  com.samsung.android.oneconnect/
    comparison_<id>/
      comparison.json
      report.md

.comparison-artifacts/
  sha256/<prefix>/<digest>/
    payload
    metadata.json
```

정책:

- `comparison.json`은 redacted compact canonical result, `report.md`는 deterministic rendering이다.
- draft는 기본 local/gitignored다.
- human decision이나 baseline approval 근거로 채택된 compact comparison/report만 명시적 review
  후 Git에 올릴 수 있다.
- raw text/speech, screenshots, evidence ledger와 large match trace는 local content-addressed
  artifact로 두고 digest reference만 공유한다.
- comparison directory는 immutable하다. 같은 ID의 다른 bytes는 corruption이다.
- Candidate가 승인되거나 baseline이 superseded되어도 comparison은 삭제하지 않는다.
- baseline/candidate lifecycle은 comparison이 변경하지 않는다.
- historical report 재생성은 원래 comparator/policy version으로 같은 ID를 재현하거나, 새
  version이면 새 comparison ID와 `supersedes_comparison_id` 관계를 만든다.
- missing optional artifact 때문에 과거 report를 완전히 재생성할 수 없으면 기존 immutable
  report를 유지하고 replay result에 `DATA_UNAVAILABLE`을 기록한다.

Git 저장은 privacy validator와 size budget을 통과해야 한다. 저장 자체가 approval을 의미하지
않는다.

## 17. Failure Safety

Comparator는 전 구간 read-only다. Candidate, baseline, catalog, lifecycle, CAS artifact를 수정하지
않는다. 출력은 별도 temp directory에서 완성한 뒤 comparison repository에 atomic rename한다.

| Failure | 결과 |
|---|---|
| baseline 없음 | `INCOMPARABLE / NO_COMPARABLE_BASELINE` |
| Candidate JSON/digest corrupt | `INCOMPARABLE / CANDIDATE_CORRUPT` |
| baseline core/checksum corrupt | 후보 quarantine, 다른 predecessor 탐색; 없으면 INCOMPARABLE |
| required artifact missing/corrupt | affected required dimension FAIL integrity; baseline 선택 권위 손상 시 INCOMPARABLE |
| optional artifact missing | dimension DATA_UNAVAILABLE; PASS 필요 자료면 REVIEW_REQUIRED |
| schema unsupported | affected dimension INCOMPARABLE; critical input이면 overall INCOMPARABLE |
| multiple baseline tie | 선택 중단, REVIEW_REQUIRED |
| ambiguous version ordering | 자동 선택 금지, REVIEW_REQUIRED |
| Candidate dirty | 비교는 가능, provenance warning; PASS/approval 근거 금지 |
| environment incomplete | known common fields만 exploratory; REVIEW_REQUIRED 또는 critical missing이면 INCOMPARABLE |
| locale mismatch | 후보 제외; cross-locale text/speech 비교 금지 |
| contract mismatch | adapter-supported common scope만; severe/unknown semantics는 INCOMPARABLE |
| partial scenario run | common set only, REVIEW_REQUIRED; approval 불가 |
| comparator 중단 | temp output만 남기거나 정리; input/lifecycle 불변 |

Hash mismatch를 field delta로 해석하거나 corrupt baseline을 다음 최신 baseline으로 조용히
대체하지 않는다. 모든 fallback은 selection trace에 남긴다.

## 18. Test Strategy

실기기 Full Run 없이 canonical fixture와 approved package copy를 사용한다.

필수 end-to-end fixture:

1. English baseline self-compare → EXACT_MATCH, limitations unchanged
2. Korean baseline self-compare → EXACT_MATCH, locale-local result
3. patch-version upgrade, no changes → COMPATIBLE_PREDECESSOR
4. app version upgrade + added node → STRUCTURAL_CHANGE
5. resource-id changed, semantic node same → Tier 2 match
6. visible text changed, speech unchanged
7. speech missing → new raw accessibility failure
8. known limitation unchanged
9. known limitation resolved
10. new EMPTY_VISIBLE
11. scenario added → common comparison + added
12. scenario removed → common comparison + review
13. TalkBack major changed → REVIEW_REQUIRED
14. locale mismatch → INCOMPARABLE/no candidate
15. ambiguous node match → REVIEW_REQUIRED
16. corrupt artifact → fail-safe result, no input mutation
17. no baseline → INCOMPARABLE
18. multiple compatible baselines → deterministic rank 또는 tie review

추가 unit/property tests:

- dotted numeric/SemVer/opaque/versionCode conflict/downgrade parser
- compatibility key excludes full version/time/path but includes package/locale/contracts
- exact fingerprint miss 뒤 predecessor discovery
- active-first/historical fallback/tie trace
- scenario set algebra, alias map과 order-only delta
- one-to-one/split/merge/ambiguity matching invariants
- Coverage transition conservation과 rate-only non-regression
- dynamic/locale text normalization
- limitation expiry/scope/resource/bounds drift
- verdict precedence와 profiler separation
- comparison ID determinism/generated_at exclusion
- canonical JSON/privacy/path rejection
- read-only test: input tree와 lifecycle checksums before/after 동일

Golden report test는 JSON semantics와 Markdown rendering을 분리한다. Threshold는 synthetic fixture와
두 현재 baseline self-compare에서 false delta가 0임을 확인한 뒤 고정한다.

## 19. Phase 10.3B Scope

Phase 10.3B의 정확한 구현 범위:

1. `talkback-comparator-input-v1`, `talkback-comparison-compatibility-key-v1`,
   `talkback-comparison-result-v1` Python contract와 canonical JSON validator.
2. 기존 Approved Baseline/Candidate/EnvironmentProfile/manifest를 수정하지 않는 read-only input
   adapter와 repository package verification.
3. One Connect dotted numeric + SemVer + opaque/versionCode app version parser와
   `oneconnect-version-policy-v1`.
4. active-first/historical predecessor enumeration, ranking, rejection trace와 tie handling.
5. 다섯 compatibility grade와 scenario/contract/environment compatibility matrix evaluator.
6. existing normalized summary만 사용한 run/scenario/Coverage common-cohort 및 aggregate
   Identity/Traversal/Recovery/Reconciliation/Profiler delta.
7. comparison ID, schema map, observation availability, verdict **skeleton**. Node/text/speech 자료가
   없으면 합성하지 않고 DATA_UNAVAILABLE/REVIEW_REQUIRED.
8. English/Korean self-compare, patch upgrade, scenario add/remove, TalkBack major, locale mismatch,
   corrupt/no/tied baseline unit fixtures.
9. read-only API만 제공. CLI, Frontend, report storage와 lifecycle mutation은 구현하지 않음.

Phase 10.3B에서 제외:

- general node matching과 observation extraction
- text/speech semantic delta와 limitation fuzzy/structural rebinding
- Markdown report/storage
- automatic approval/suppression
- Candidate/Repository schema migration
- production traversal/Frontend/CLI

Phase 10.3C는 observation normalizer와 semantic matching, 10.3D는 final verdict/report/storage를
구현한다.

## 20. Open Questions and Decisions

### 20.1 확정 결정

1. 앱 버전 차이는 기본 incomparability trigger가 아니다.
2. EnvironmentFingerprint/BaselineKey v1은 변경하지 않는다.
3. 별도 ComparisonCompatibilityKey와 predecessor policy를 사용한다.
4. package와 locale mismatch는 hard incomparable이다.
5. active-first 후 historical best predecessor를 탐색한다.
6. scenario count equality를 compatibility 조건으로 사용하지 않는다.
7. Coverage는 common cohort transition과 structural delta로 비교한다.
8. Known Limitation은 raw FAIL과 분리하고 새 app version에 자동 carry-forward하지 않는다.
9. Profiler regression은 accessibility verdict와 분리한다.
10. Comparator는 read-only이며 자동 approval을 하지 않는다.
11. Phase 10.3은 A/B/C/D 네 단계로 진행한다.

### 20.2 남은 open question

1. One Connect `1.8` train 규칙을 vendor/team이 장기 policy로 승인할지, 다른 channel/train metadata가
   필요한가?
2. versionCode와 APK signing lineage/hash를 capture contract에 어떤 source로 추가할 것인가?
3. Scenario rename alias와 per-scenario semantic descriptor의 owner/versioning은 누가 담당하는가?
4. runtime-config field별 semantic impact map과 diagnostic/core flag 분류의 owner는 누구인가?
5. node matching threshold/margin과 Coverage significant denominator threshold를 어떤 fixture
   corpus로 calibration할 것인가?
6. text/speech raw value의 redaction, retention, locale normalization policy는 무엇인가?
7. `talkback-comparison-observation-set-v1`을 향후 required pinned artifact로 만들 것인가, approved
   baseline comparison contract에 additive summary로 넣을 것인가?
8. 기존 두 baseline의 unpinned Evidence ledger/XLSX를 보존된 local source에서 one-time pin할 수
   있는가? 불가능하면 text/speech dimension은 어떤 acceptance 제한을 가질 것인가?
9. same-family model, fold posture/display role과 OS/TalkBack major compatibility matrix의 owner와
   review 주기는 무엇인가?
10. reviewed comparison.json/report.md의 Git size/privacy budget과 human disposition schema는
    무엇인가?

### 20.3 최종 질문에 대한 답

1. **One Connect 새 버전이 나와도 기존 baseline과 비교 가능한가?**

   가능하다. 같은 package/locale과 compatible family/contracts를 만족하면 active 또는 historical
   best predecessor를 선택한다.

2. **앱 버전 차이를 비교 불가 사유로 사용하지 않도록 설계됐는가?**

   그렇다. full version 차이는 exact fingerprint/key miss를 만들 수 있지만, Comparator는 별도
   compatibility key와 version policy로 후보를 찾고 version delta를 비교 evidence로 다룬다.

3. **UI 구조가 바뀌어도 common cohort와 semantic node matching으로 변화 추적이 가능한가?**

   가능하도록 계약을 정의했다. scenario/common Coverage cohort, Tier 1–3 semantic evidence와
   added/removed/split/merge/ambiguous 결과를 사용한다. 다만 기존 package에 observation artifact가
   없으면 해당 dimension은 DATA_UNAVAILABLE로 제한한다.

4. **실제 접근성 회귀와 정상 UI 변경을 구분할 수 있는 계약이 준비됐는가?**

   설계 계약은 준비됐다. common-node 상태 전이와 text/speech loss는 regression으로, denominator/
   added/removed 변화는 structural delta로, ambiguity와 contract/environment drift는 review로
   분리한다. Phase 10.3B–D에서 이 계약을 순차 구현해야 production-ready가 된다.
