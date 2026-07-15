# TalkBack Phase 10.1A — Environment Capture & Contracts

상태: Implemented

기준 commit: `530b703c0dbf3bd019e0b39eb5e62d0a161d6a74`

범위: EnvironmentProfile model, read-only collector, semantic validation, canonical JSON,
redaction interface, document digest/environment fingerprint와 기존 manifest/summary의
additive reference

## 1. Scope

Phase 10.1A는 run preflight 시점의 환경을 versioned canonical metadata로 수집한다.
BaselineCandidate, Comparator, Promotion, Approval, Frontend, DB, KnownIssue, artifact pinning과
CLI는 구현하지 않는다. Environment capture 결과는 traversal/recovery/identity/coverage의
입력으로 사용하지 않으며, capture failure도 기존 실행 결과를 바꾸지 않는다.

## 2. Collection Structure

구현은 다음 계층으로 분리한다.

| 모듈 | 책임 |
|---|---|
| `tb_runner/environment_profile.py` | `EnvironmentField`, nested EnvironmentProfile dataclass와 status enum |
| `tb_runner/environment_validator.py` | package/locale/One UI/display/fold/active-display/git value의 순수 semantic parser |
| `tb_runner/environment_collector.py` | ADB, Git, runtime config, scenario registry를 read-only로 수집하고 profile artifact 작성 |
| `tb_runner/environment_redaction.py` | local profile에서 shared profile을 만드는 serial/fingerprint redaction boundary |
| `tb_runner/canonical_json.py` | Unicode NFC, sorted keys, compact UTF-8 JSON과 SHA-256 |

`script_test.py`는 output stem을 기준으로
`<stem>.environment_profile.json`을 preflight 직전에 작성한다. 먼저 local profile을 메모리에서
구성한 후 shared profile로 redaction하고 shared profile만 파일에 쓴다. writer는 temporary
file과 atomic replace를 사용한다.

각 leaf field는 다음 계약을 가진다.

```json
{
  "value": "en-US",
  "status": "AVAILABLE",
  "source": "adb:getprop:persist.sys.locale",
  "captured_at": "2026-07-15T00:00:00.000Z",
  "reason": ""
}
```

Top-level `schema_version`은 `talkback-environment-profile-v1`이고 `captured_at`은 UTC다.
EnvironmentProfile은 device, Android/One UI, TalkBack, target app, helper, locale, display,
fold, repository와 runtime contract 그룹을 가진다.

## 3. Reused Paths

기존 기능을 다음과 같이 재사용한다.

- `RunSpec`과 resolved feature flags를 capture context로 사용한다.
- run-local `runtime_config_path`와 `tb_runner/scenario_config.py`를 기존 실행과 동일한
  path에서 SHA-256한다.
- 기존 `A11yAdbClient._run()`을 adapter로 감싸므로 별도의 ADB process manager를 만들지 않는다.
- helper/target package, model, fingerprint, locale, display size와 helper APK SHA-256의 기존
  provenance command를 유지한다.
- evidence/identity/profiler/runtime-config의 기존 schema constants를
  `collection_schema_versions`에 사용한다.
- QA Frontend의 기존 log-derived summary와 batch device output directory 규칙을 사용해 profile
  reference를 연결한다.

## 4. Semantic Validation

ADB command success와 non-empty stdout만으로 `AVAILABLE`을 부여하지 않는다.

### 4.1 Package

Package validator는 다음을 모두 요구한다.

1. output이 package-not-found/error marker가 아니다.
2. requested package identity가 dumpsys output에 존재한다.
3. `versionName`과 numeric `versionCode`를 모두 parse할 수 있다.

`Unable to find package: ...`는 command exit code와 무관하게 `INVALID`다. Evidence manifest의
legacy package status도 package-not-found와 unparseable version을 더 이상 `available`로
표시하지 않는다.

### 4.2 TalkBack

`settings get secure enabled_accessibility_services`에서 실제 active component를 읽는다.
지원 package는 다음 두 개다.

- `com.samsung.android.accessibility.talkback`
- `com.google.android.marvin.talkback`

active package가 하나일 때만 선택하고 그 package에 `dumpsys package`를 실행한다. 두 package가
동시에 active이면 추정하지 않고 `INVALID`, active TalkBack이 없으면 `MISSING`이다. 선택된
package는 legacy Evidence manifest query에도 전달되므로 Samsung device에서 Google package만
조회하던 결함을 제거한다.

### 4.3 Locale

`persist.sys.locale`을 먼저 읽고 값이 없으면 `ro.product.locale`을 사용한다. language,
optional script, optional region 구조만 허용하고 `_`는 `-`로 정규화한다. 임의 text나 남는
segment가 있으면 `INVALID`다.

### 4.4 Display

`wm size`와 `wm density`를 구조화한다.

- physical size/density는 원래 panel 값이다.
- override는 command에 명시된 경우에만 AVAILABLE이다.
- logical은 explicit logical 값, override, physical 순서의 command semantics로 결정한다.
- parse할 수 없는 non-empty output은 INVALID이고 설정되지 않은 override는 MISSING이다.

### 4.5 Fold와 active display

`cmd device_state print-state`와 `print-states`의 identifier/name을 직접 연결한다. model명으로
foldable 여부나 posture를 추정하지 않는다. Active display는 `dumpsys window displays`의
non-null `mCurrentFocus`가 하나일 때 display ID와 focused package를 저장한다. main/cover role은
신뢰할 mapping이 없어 `role=UNKNOWN`으로 보존한다.

### 4.6 Git과 hashes

Commit은 정확히 40자리 hexadecimal SHA여야 한다. Dirty는 `git status --porcelain`의 empty/
non-empty로만 결정하며 diff 내용은 저장하지 않는다. Runtime config와 scenario registry는
file bytes의 SHA-256이며 file 없음은 MISSING, read failure는 INVALID다.

## 5. One UI Fallback

다음 property를 순서대로 시도한다.

1. `ro.build.version.oneui`
2. `ro.build.version.oneui.version`
3. `ro.build.version.oneui_version`

empty/missing 또는 semantic parse failure면 다음 후보로 이동한다. 모든 값이 비어 있으면
MISSING, non-empty지만 모두 invalid이면 INVALID다. `70000`은 documented parser contract에
따라 `7.0`, `60101`은 `6.1.1`로 정규화한다. `ro.build.version.sep`처럼 One UI version이 아닌
Samsung platform integer를 One UI로 추정하지 않는다.

## 6. Status Policy

| Status | 의미 |
|---|---|
| `AVAILABLE` | source와 semantic validation이 모두 성공 |
| `MISSING` | source/value가 없거나 현재 phase가 신뢰할 방법으로 수집할 수 없음 |
| `INVALID` | 값은 있으나 identity/format/semantic contract를 통과하지 못함 |
| `REDACTED` | local raw value를 shared profile에서 제거/축약 |
| `BACKFILLED` | historical artifact migration용 예약 status; 10.1A collector는 생성하지 않음 |

Collector는 field failure를 profile에 보존한다. Profile writer 자체가 실패해도 warning을
기록하고 기존 preflight/traversal을 계속한다.

## 7. Canonical JSON, Redaction, Document Digest and Environment Fingerprint

Canonical JSON은 key ordering, compact separators, UTF-8, Unicode NFC와 trailing newline을
고정하고 NaN/Infinity 및 지원하지 않는 object를 거부한다. Phase 10.1A.1부터 document
integrity와 environment matching identity를 서로 다른 canonical source와 digest로 분리한다.

### 7.1 Document Digest

`document_digest`는 redacted shared EnvironmentProfile 전체 canonical bytes의 SHA-256이다.
top-level/per-field `captured_at`, status, source, reason과 validation provenance를 모두 포함한다.
따라서 capture time이나 document 내용이 바뀌면 digest도 바뀌며, 이는 문서 무결성 관점에서
의도된 동작이다.

Reference에는 algorithm, scope, value를 구조화해 저장한다. 기존 `sha256`은 같은 digest의
하위 호환 alias다. `EnvironmentCaptureResult.environment_hash`와
`EnvironmentProfile.environment_hash()`도 deprecated compatibility alias이며 새 코드는
`document_digest` 명칭을 사용한다.

### 7.2 Environment Fingerprint Source

`talkback-environment-fingerprint-v1` source는 다음 comparison field만 가진다.

- direct: target package, app compatibility release train, scenario/runtime hash, locale,
  traversal/identity contract, comparison-relevant flags, collection contracts
- family: Android/One UI major, TalkBack package/major, form factor, device family

SmartThings release-train policy가 아직 승인되지 않았으므로 Architecture의 보수적 fallback에
따라 full target version을 release train 값으로 사용한다. `runtime_profiler`는 comparison
semantics를 바꾸지 않는 diagnostic flag이므로 제외하고 다른 resolved flags는 보수적으로
포함한다.

Fingerprint source에는 `captured_at`, field provenance/status/reason, run/batch/evidence ID,
serial/token, Git commit/dirty, document checksum, path/filename/temp filename, status counts를
포함하지 않는다. `fingerprint_source` canonical JSON이 truth이고 `hash`는 COMPLETE source의
lookup accelerator일 뿐이다.

### 7.3 Fingerprint Status

| Status | 의미 | Hash |
|---|---|---|
| `COMPLETE` | 모든 direct/family critical value가 usable | canonical source SHA-256 |
| `INCOMPLETE` | 하나 이상의 critical field가 MISSING/REDACTED | 생성하지 않음 (`null`) |
| `UNUSABLE` | critical field가 INVALID이거나 major/hash/value normalization 실패 | 생성하지 않음 (`null`) |

누락/invalid field 이름은 fingerprint wrapper의 diagnostic list에 남지만 fingerprint source와
hash 입력에는 validation reason/message를 넣지 않는다. Baseline lookup은 COMPLETE fingerprint만
사용할 수 있다.

Shared profile에서는:

- raw serial을 제거하고 status를 REDACTED로 바꾼다.
- `SerialTokenProvider` interface로 token을 받을 수 있다.
- 현재 기본 provider에는 secret/HMAC 구현이 없으므로 serial token은 MISSING이다.
- raw build fingerprint에서 incremental identifier를 제거하고 brand/product/device,
  Android release, build ID와 variant만 남긴다. parse 실패 시 raw 값을 전부 제거한다.

Local profile은 메모리에서만 유지한다. 기존 QA Frontend batch summary가 이미 raw serial을
보유하는 legacy behavior는 이번 phase에서 변경하지 않는다.

## 8. Manifest and Summary Integration

기존 schema version은 올리지 않고 optional field만 추가한다.

- Evidence manifest: `manifest.environment_profile`
- run summary: `environment_profile`
- batch root summary의 device entry: `environment_profile`
- batch device `summary.json`: `environment_profile`

Reference는 filename, profile schema version, `document_digest`, `environment_fingerprint`,
`fingerprint_schema`, `fingerprint_status`를 가진다. Evidence reference에는 status counts도
포함한다. 기존 `sha256`은 document digest alias로 유지한다. Environment marker가 없는
historical log와 profile이 없는 historical batch는 기존과 동일하게 reference가
`null`/absent다.

## 9. New ADB Commands

기존 provenance command 외에 Environment contract를 위해 다음 read-only command를 추가했다.

- `get-serialno` — RunSpec serial이 없을 때만
- `getprop ro.build.version.release`
- `getprop ro.build.version.sdk`
- One UI fallback property 1–3개
- `settings get secure enabled_accessibility_services`
- 선택된 실제 TalkBack package의 `dumpsys package`
- `wm density`
- `cmd device_state print-state`
- `cmd device_state print-states`
- `dumpsys window displays`

TalkBack status command은 frontend/core preflight에도 이미 존재하지만 EnvironmentProfile은
자기 capture timestamp와 source를 가져야 하므로 read-only로 다시 읽는다.

## 10. Backward Compatibility

- Traversal Engine과 scenario selection에 profile 값이 전달되지 않는다.
- Evidence, Coverage, Profiler, Recovery와 Identity reducer/writer semantics를 수정하지 않는다.
- capture/validation 실패는 run abort 조건이 아니다.
- 기존 manifest/summary field를 삭제하거나 이름/의미를 변경하지 않는다.
- 기존 `sha256` consumer는 전체 canonical document digest를 계속 읽는다.
- 기존 `environment_hash` accessor는 document digest alias로 계속 동작하지만 deprecated다.
- 새 consumer만 `environment_fingerprint.status/hash/fingerprint_source`를 사용한다.
- legacy Evidence package field는 semantic false-positive만 바로잡고 EnvironmentProfile을
  authoritative structured metadata로 사용한다.

관련 Environment/Evidence/Run Summary/Batch/RunSpec/Profiler tests로 additive behavior를
검증한다.

### 10.1 Migration

기존 Phase 10.1A profile은 embedded fingerprint가 없어도 reader가 profile value에서 새
fingerprint contract를 재구성한다. 원본 bytes와 legacy `sha256`은 바꾸지 않는다. 새 profile은
`environment_fingerprint`를 shared document에 embedded한 후 최종 document digest를 계산한다.
따라서 새 문서의 digest는 embedded contract까지 무결성 범위에 포함한다.

## 11. Known Limitations

- device family와 form factor mapping policy가 없어 두 field는 MISSING이다.
- HMAC secret/provider 구현이 없어 shared serial token은 MISSING이다.
- active display ID는 수집하지만 main/cover role은 UNKNOWN이다.
- One UI fallback은 명시된 One UI property만 사용한다. vendor가 다른 property만 제공하면
  MISSING이며 SEP/SEM 값에서 추정하지 않는다.
- fold state command를 지원하지 않는 Android/device는 MISSING 또는 INVALID다.
- local raw profile을 위한 별도 access-controlled store는 아직 없다. raw serial은 기존 local
  frontend provenance에만 남는다.
- runtime config hash는 effective run-local file bytes hash다. semantic canonical config hash와
  effective scenario registry descriptor는 Phase 10.1B에서 확장한다.
- 현재 collector는 reviewed device family/form factor mapping이 없으므로 fresh profile의
  fingerprint는 기본적으로 `INCOMPLETE`이며 hash가 없다. 임의 model inference로 COMPLETE를
  만들지 않는다.

## 12. Phase 10.1B Handoff

다음 항목은 10.1A 범위 밖이며 Phase 10.1B 이후로 넘긴다.

- HMAC-backed serial token provider와 secret lifecycle
- reviewed device-family/form-factor/active-display-role mapping
- semantic effective runtime/scenario registry canonicalization
- EnvironmentProfile completeness policy와 approval eligibility
- historical BACKFILLED profile migration
- BaselineCandidate와 artifact manifest
- lifecycle/promotion/approval, Comparator와 frontend
- object storage, artifact pinning과 DB
