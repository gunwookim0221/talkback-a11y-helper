# TalkBack Phase 10.0 Baseline Manager Architecture

상태: **Architecture decision / implementation 전 설계**

기준일: 2026-07-15

기준 commit: `c0a1da49508b38a1a96163a9bee7de362f89c961` (`origin/main`과 동일)

범위: Baseline Manager의 데이터 계약, 비교 가능성, lifecycle, 저장 경계

## 1. Executive Summary

Baseline Manager는 XLSX 복사본 보관기가 아니라, 승인된 run의 비교 가능한 사실을
immutable package로 고정하고 현재 run과의 환경·workload parity를 먼저 판정하는
comparison control plane이다. Traversal Engine은 Android, 단말, TalkBack 버전에 따라
분기하지 않는다. 환경 차이는 `EnvironmentProfile`, `BaselineKey`, matching policy와
Comparator에서만 다룬다.

핵심 결정은 다음과 같다.

- 승인 baseline의 canonical truth는 compact JSON 3개
  (`baseline.json`, `environment_profile.json`, `artifact_manifest.json`)다. XLSX, evidence
  JSONL, profiler 원본은 supporting artifact이며 canonical truth가 아니다.
- `BaselineKey`는 app/scenario/runtime/traversal/identity/locale/core flags를 직접 비교
  contract로, Android/One UI/TalkBack major/form factor를 baseline family로 표현한다.
  canonical source fields를 보존하고 그 canonical JSON의 SHA-256은 lookup용으로만 쓴다.
- 비교 가능성은 `EXACT_MATCH`, `COMPATIBLE_FAMILY`, `REVIEW_REQUIRED`,
  `INCOMPARABLE` 네 등급이다. A급 필드가 다르거나 누락되면 직접 비교하지 않는다.
- Coverage는 `covered/expected`와 inventory cohort를 함께 저장한다. cohort가 다르면
  intersection, added/removed candidates와 taxonomy를 분리하고 percentage 차이만으로
  regression을 선언하지 않는다.
- known issue는 원래 row/scenario FAIL을 바꾸거나 numerator를 조작하지 않는다. 정확히
  scope/signature가 일치할 때 comparator의 설명을 `KNOWN_LIMITATION`으로 추가할 뿐이다.
- 자동 승인은 없다. `PASS WITH LIMITATIONS` run은 limitation이 구조화되고, 신규 regression이
  없으며, reviewer가 명시적으로 수락한 경우에만 baseline으로 승인할 수 있다.
- metadata와 schema는 Git에서 공유할 수 있지만 raw run artifact는 Git에 넣지 않는다.
  첫 버전은 로컬 content-addressed artifact repository와 QA Frontend run 참조를 사용하며
  DB는 도입하지 않는다.

Phase 9.5.4 run `batch_20260715_082735`는 첫 **CANDIDATE**로 변환할 수 있다. 그러나
TalkBack version, Android SDK, One UI, display density, fold state 등 approval-critical
metadata가 실행 시점 자료로 완전하지 않다. 따라서 기존 자료만으로 APPROVED로 승격하지
않고, Phase 10.1 capture contract가 적용된 fresh full run을 승인 기준으로 삼는다.

## 2. Current Artifact Inventory

### 2.1 조사한 코드와 계약

| 영역 | 현재 경로 | 확인 결과 |
|---|---|---|
| Run contract | `tb_runner/run_spec.py` | serial, mode, language/launch mode, scenario IDs, output/runtime config, probe와 4개 evidence/identity/profiler flag를 보유한다. 환경 profile 자체는 없다. |
| Runtime config | `tb_runner/runtime_config.py`, `config/runtime_config.json` | run-local config 경로를 지원하고 loader version은 `1.10.0`이다. V10 flags도 config에 있으나 RunSpec의 4 flags와 한 객체로 정규화되지 않는다. |
| Scenario registry | `tb_runner/scenario_config.py` | `SCENARIO_CONFIG_VERSION`과 `TAB_CONFIGS`가 있다. evidence manifest는 파일 SHA-256을 저장한다. |
| Evidence | `tb_runner/evidence.py` | `.evidence.jsonl`, `.evidence_manifest.json`, `.evidence_reconciliation.json`을 생성한다. schema는 `evidence-event-v1`, reconciliation은 `evidence-reconciliation-v1`이다. |
| Identity | `tb_runner/evidence_identity.py` | normalization `canonical-observation-v1`, reducer `target-relation-v2`; per-transaction 결과와 reconciliation aggregate가 존재한다. |
| Coverage | `tb_runner/collection_flow.py` | `audit-v7-focusable-inventory-v1`, `audit-v7-focusable-coverage-v1`; canonical record, taxonomy, covered/missed/unknown, numerator/denominator를 보유한다. |
| Profiler | `tb_runner/traversal_profiler.py` | scenario별 `traversal-profiler-v1` JSON을 생성한다. runtime, metrics, recovery, counters를 보유한다. |
| Single-run summary | `qa_frontend/backend/run_summary.py` | summary schema `1`; log를 재파싱한 process/scenario 상태, locale, flags, scenario 목록, XLSX/log 경로를 저장한다. log가 여전히 source of truth다. |
| Batch summary | `qa_frontend/backend/batch_runner.py` | `batch_<timestamp>/batch_summary.json`, device별 `summary.json`; serial/model, run timestamps, paths, flags, quality/coverage와 scenarios를 노출한다. schema_version은 없다. |
| Device discovery | `qa_frontend/backend/adb.py` | `adb devices`와 `ro.product.model`; helper/TalkBack enabled 여부와 foreground package를 표시한다. |
| Locale | `qa_frontend/backend/device_locale.py` | `persist.sys.locale`, `system_locales`, fallback `ro.product.locale`을 읽고 requested locale을 검증한다. |
| Frontend history | `qa_frontend/backend/recent_runs.py`, `qa_frontend/frontend/src/components/RecentRunsPanel.tsx` | standalone log/summary와 batch device summary를 표시하고 XLSX 및 일부 artifact link를 노출한다. baseline 개념은 없다. |
| Roots | `qa_frontend/backend/paths.py` | regular output은 `output/`, run history는 `qa_frontend_runs/`다. 두 디렉터리는 `.gitignore` 대상이다. |

### 2.2 현재 ID와 artifact root 규칙

- standalone run ID: local timestamp `YYYYMMDD_HHMMSS`
- standalone log: `qa_frontend_runs/<run-id>_<mode>.log`
- standalone sidecar: `qa_frontend_runs/<run-id>_summary.json`
- batch ID: `batch_YYYYMMDD_HHMMSS`
- batch root: `qa_frontend_runs/<batch-id>/`
- device root:
  `qa_frontend_runs/<batch-id>/device_<sanitized-model>_<sanitized-serial>/`
- runner artifact stem: `talkback_compare_<YYYYMMDD_HHMMSS>`
- evidence run ID: 별도 random `run_<uuid>`; frontend run/batch ID와 동일하지 않다.
- crash artifact는 batch/device root 아래 `crashes/<crash-event-id>/`를 사용한다.

Baseline contract는 `source_run_id`, `source_batch_id`, `evidence_run_id`를 서로 다른 필드로
보존해야 한다. timestamp나 path stem을 서로의 ID로 추정해서는 안 된다.

### 2.3 Phase 9.5.4 실물 확인

조사 대상은
`qa_frontend_runs/batch_20260715_082735/device_SM-F741N_R3CX40QFDBP/`다.

| Artifact | 확인 내용 |
|---|---|
| `batch_summary.json`, device `summary.json` | 32/32 executed/completed, failed scenario 0, state passed, `scenario_result_status=warning`, flags 4개 ON |
| `.focusable_coverage.json` | schema `audit-v7-focusable-coverage-v1`, canonical records 653, cohort denominator 576, covered 323, missed 94, unknown 159, coverage 56.1% |
| `.evidence_reconciliation.json` | PASS, 27,395 events, anchor abort 0, orphan/duplicate/write failure 0, V2 864 transactions, INDETERMINATE 53 |
| `.evidence_manifest.json` | commit/dirty, runner/runtime/registry/helper hashes, model, locale, build fingerprint, display size와 package dumps를 보유 |
| `.profiler.zip` | 32개 scenario profiler JSON 포함 |
| `.xlsx`, `.normal.log`, `runner.log`, `.evidence.jsonl` | canonical summary의 근거가 되는 대형 supporting artifacts |

Phase 9.5.4 acceptance record의 aggregate는 Coverage `323/576 (56.1%)`, Recovery
`27 attempts / 12 recovered`, 최종 `PASS WITH LIMITATIONS`다. 현재 device `summary.json`은
Coverage aggregate를 노출하지만 acceptance result와 동일한 정의의 Recovery aggregate를
canonical field로 보유하지 않는다. 이처럼 parser/문서별 aggregate 정의가 흩어진 문제를
Phase 10 normalizer가 source schema와 reduction version을 붙여 해소해야 한다.

### 2.4 이미 수집 가능한 metadata

다음은 현재 artifact에서 명시적으로 읽을 수 있다.

- source batch ID, evidence run ID, started/finished timestamps
- raw serial과 model (현재 local summary; shared baseline에는 redaction 필요)
- verified locale `en-US`
- target app package dump와 version (`com.samsung.android.oneconnect`, `1.8.47.24`,
  versionCode `184724010`)
- Android build fingerprint와 fingerprint에 기록된 release token
- physical display size `1080x2640`
- repository commit, dirty boolean, runner source hash
- run-local runtime config hash와 scenario registry file hash
- helper package dump/version (`1.0`, versionCode `1`)과 APK hash
- feature flags: evidence ledger, identity shadow V2, traversal identity V2, profiler
- evidence/reconciliation/coverage/profiler schema versions와 identity reducer/normalization
- scenario terminal/status/steps, row quality, coverage record/cohort, recovery와 identity aggregate

단, package dump를 저장했다는 사실과 올바른 package/version을 수집했다는 사실은 다르다.
현재 manifest의 `talkback_version`은 `status=available`이지만 값은
`Unable to find package: com.google.android.marvin.talkback`이다. 실제 enabled component는
runner log에 `com.samsung.android.accessibility.talkback/...TalkBackService`로 남았다.
새 contract는 command exit code뿐 아니라 semantic parser validation을 통과해야
`available`로 인정한다.

### 2.5 새로 수집하거나 정규화해야 하는 metadata

- environment capture timestamp와 capture tool/schema version
- raw serial을 대신할 조직 내 opaque device token
- device family, validated-family revision, form factor
- `ro.build.version.release`, `ro.build.version.sdk`
- One UI version (`ro.build.version.oneui` 등 검증된 source)
- enabled TalkBack component에서 결정한 실제 package와 parsed versionName/versionCode
- target app package/name/code의 구조화된 값(전체 dumpsys blob이 아닌 parser result)
- display density (`wm density`)와 logical/override size 구분
- foldable capability/state, posture와 display role(main/cover) — foldable일 때 conditional required
- traversal engine contract version과 RunSpec/runner version의 명시적 분리
- 전체 effective feature flags: RunSpec 4개, coverage probe, launch/mode와 runtime V10 flags
- collection schema version map
- canonical scenario registry hash(파일 byte hash만이 아니라 effective scenario set/order 포함)
- canonical effective runtime config hash와 redacted snapshot
- 각 core/supporting artifact의 checksum, size, media type, logical locator
- inventory cohort hash 및 scenario별 cohort hash
- approval actor/reason/limitation snapshot

## 3. Design Goals

1. run이 생성된 실행 환경과 effective configuration을 재현 가능한 형태로 설명한다.
2. 승인 baseline 검색 전에 비교 가능성을 결정하며, 불일치 환경을 억지로 비교하지 않는다.
3. code regression, environment drift, dynamic inventory drift, known limitation을 독립 축으로
   분류한다.
4. Coverage, Identity, Recovery, Reconciliation, Profiler의 기존 semantics를 보존한다.
5. 승인 후 canonical package를 immutable하게 유지하고 provenance chain을 감사할 수 있게 한다.
6. Git metadata catalog, local artifact repository, QA Frontend run root를 분리한다.
7. 향후 object storage/DB로 옮겨도 JSON 계약과 content identity를 유지한다.

## 4. Non-goals

- Production Traversal Engine 또는 scenario behavior 변경
- Android/model/TalkBack별 traversal branch 추가
- Baseline promotion/approval UI와 frontend 구현
- 자동 승인, 자동 known-issue 생성 또는 자동 suppression
- DB/object storage 도입
- 기존 XLSX, evidence, profiler schema의 의미 변경
- raw screenshot, speech, JSONL, XLSX 전체의 Git 저장
- Phase 10.3 comparator production 구현

## 5. Environment Profile Schema

### 5.1 표현 원칙

`environment_profile.json`은 정규화된 값과 각 값의 provenance를 함께 가진다.
필드 값만 두지 않고 최소한 `value`, `status`, `source`, `captured_at`을 가진다.
`status`는 `AVAILABLE | MISSING | INVALID | REDACTED | BACKFILLED`다. parser가 package-not-found,
빈 값, ambiguous multi-package 결과를 받으면 `INVALID`이며 available이 아니다.

```json
{
  "schema_version": "talkback-environment-profile-v1",
  "captured_at": "2026-07-15T00:00:00Z",
  "fields": {
    "android_sdk": {
      "value": 35,
      "status": "AVAILABLE",
      "source": "adb:getprop:ro.build.version.sdk",
      "captured_at": "2026-07-15T00:00:00Z"
    }
  }
}
```

아래 표에서 `Key`는 `direct`, `family`, `warning`, `no` 중 하나다. `direct`는 반드시
동일해야 하고, `family`는 별도 baseline family 차원이며, `warning`은 같지 않아도
정책상 비교 가능할 수 있고, `no`는 provenance/diagnostic 전용이다.

### 5.2 필드 계약

| 필드 | 필수성 | 수집 출처 | 비교/Key | 진단 | 누락 시 영향 |
|---|---|---|---|---|---|
| `schema_version` | R | capture writer constant | schema gate / direct | 예 | 지원하지 않는 major면 INCOMPARABLE |
| `captured_at` | R | UTC clock at preflight | no | 예 | provenance incomplete, 승인 금지 |
| `device_serial` | R, redacted | selected ADB serial → HMAC opaque token | no | 물리 단말 추적 | raw/opaque token 모두 없으면 승인 금지; 비교 등급은 내리지 않음 |
| `device_model` | R | `ro.product.model` | warning | 예 | family가 있으면 REVIEW_REQUIRED, family도 없으면 INCOMPARABLE |
| `device_family` | R | reviewed mapping + mapping revision | family | 예 | compatible-family 비교 불가; exact model만 REVIEW_REQUIRED |
| `form_factor` | R | capability probe + reviewed enum | family | 예 | INCOMPARABLE |
| `android_release` | R | `ro.build.version.release` | family(major) | 예 | INCOMPARABLE |
| `android_sdk` | R | `ro.build.version.sdk` | warning/contract guard | 예 | REVIEW_REQUIRED; release도 없으면 INCOMPARABLE |
| `build_fingerprint` | R local, redacted shared | `ro.build.fingerprint` | warning | 예 | patch drift 판단 불가 → REVIEW_REQUIRED |
| `one_ui_version` | R on Samsung | validated Samsung property/parser | family(major) | 예 | Samsung family selection 불가 → REVIEW_REQUIRED; family가 바뀐 것으로 추정 금지 |
| `talkback_package` | R | enabled service component + installed package validation | direct | 예 | INCOMPARABLE |
| `talkback_version_name` | R | `dumpsys/package manager` structured parser | family(major), full warning | 예 | INCOMPARABLE |
| `talkback_version_code` | R | same parser | warning | 예 | name이 있으면 REVIEW_REQUIRED, 둘 다 없으면 INCOMPARABLE |
| `target_app_package` | R | configured expected package + installed/foreground validation | direct | 예 | INCOMPARABLE |
| `target_app_version_name` | R | structured package parser | release train direct, patch warning | 예 | INCOMPARABLE |
| `target_app_version_code` | R | same parser | warning | 예 | version name이 있으면 REVIEW_REQUIRED, 둘 다 없으면 INCOMPARABLE |
| `locale` | R | verified effective locale; requested value만 사용 금지 | direct | 예 | INCOMPARABLE |
| `display_size` | R | `wm size`, physical/logical/override 구조화 | warning | 예 | REVIEW_REQUIRED |
| `display_density` | R | `wm density`, physical/override 구조화 | warning | 예 | REVIEW_REQUIRED |
| `foldable_state` | conditional R | device-state/capability API; posture + active display | family for posture class | 예 | foldable이면 INCOMPARABLE, slab이면 `NOT_APPLICABLE` 허용 |
| `repository_commit_sha` | R | `git rev-parse HEAD` | no | 예 | 승인 금지, comparator 결과는 REVIEW_REQUIRED |
| `working_tree_dirty` | R | `git status --porcelain` boolean | no | 예 | missing/true 모두 승인 금지; 실행 비교는 REVIEW_REQUIRED |
| `scenario_registry_hash` | R | canonical effective registry SHA-256 | direct | 예 | INCOMPARABLE |
| `runtime_config_hash` | R | canonical effective/redacted config SHA-256 | direct | 예 | INCOMPARABLE |
| `traversal_engine_version` | R | explicit engine contract constant | direct(major contract) | 예 | INCOMPARABLE |
| `identity_version` | R | reducer + normalization versions | direct(major contract) | 예 | INCOMPARABLE |
| `feature_flags` | R | resolved effective flags after dependency expansion | core direct, diagnostic flags warning | 예 | core flag missing은 INCOMPARABLE, non-core missing은 REVIEW_REQUIRED |
| `helper_apk_version` | R | helper package version + APK SHA-256 | major contract direct, patch warning | 예 | INCOMPARABLE if action/evidence contract unknown |
| `collection_schema_versions` | R | writers/artifact headers map | direct(major contracts) | 예 | affected metric은 INCOMPARABLE; 전체 결과는 REVIEW_REQUIRED 또는 INCOMPARABLE |

`display_size`와 `display_density`는 문자열 하나가 아니라 physical/logical/override 값을
구분한다. `foldable_state`도 단일 open/closed 문자열이 아니라 `capable`, `posture`,
`active_display`, `hinge_state_source`를 가진다.

### 5.3 serial과 동일 모델 baseline 공유

Serial은 물리 단말 provenance일 뿐 BaselineKey가 아니다. 다음 조건을 모두 만족하면 다른
serial의 동일 모델 또는 validated device family가 baseline을 공유할 수 있다.

- A급 direct fields가 동일하다.
- device family/form factor, Android/One UI/TalkBack major family가 동일하다.
- model 간 compatibility가 명시적으로 검증되어 있다.
- display/posture 차이가 scenario inventory 또는 navigation geometry를 바꾸지 않았거나,
  해당 cohort 차이를 comparator가 분리한다.
- account/fixture와 inventory cohort가 비교 계약을 충족한다.

raw serial의 단순 SHA-256은 작은 입력 공간에서 역추적될 수 있으므로 공유 metadata에는
비밀키 기반 HMAC token만 저장한다. 키가 다른 조직 간 token equality는 요구하지 않는다.

## 6. Baseline Identity and Matching

### 6.1 Canonical BaselineKey

BaselineKey source는 sorted-key UTF-8 canonical JSON이다. 값의 공백, locale case, version
major 추출 규칙을 schema에 고정한다. hash만 저장하지 않는다.

```json
{
  "key_schema": "talkback-baseline-key-v1",
  "direct": {
    "target_app_package": "com.samsung.android.oneconnect",
    "target_app_release_train": "1.8",
    "scenario_registry_hash": "sha256:...",
    "runtime_config_hash": "sha256:...",
    "locale": "en-US",
    "traversal_contract": "production-traversal-v2",
    "identity_contract": "target-relation-v2+canonical-observation-v1",
    "core_feature_flags": {
      "evidence_ledger": true,
      "identity_shadow_v2": true,
      "traversal_identity_v2": true
    },
    "collection_contracts": {
      "evidence": "evidence-event-v1",
      "coverage": "audit-v7-focusable-coverage-v1"
    }
  },
  "family": {
    "android_major": 15,
    "one_ui_major": 7,
    "talkback_package": "com.samsung.android.accessibility.talkback",
    "talkback_major": "<captured>",
    "form_factor": "foldable_phone",
    "device_family": "galaxy-z-flip6"
  }
}
```

`key_digest = sha256(canonical_json(key_source))`는 index lookup과 corruption detection에만
사용한다. 사람에게는 위 source와 mismatch reason을 표시한다. `target_app_release_train`은
임의 semver 추측이 아니라 app별 version policy가 정의한 호환 train이다. policy가 없으면
full version을 direct field로 사용하고 version 변경을 `REVIEW_REQUIRED`로 둔다.

### 6.2 필드 등급

**A. 반드시 동일**

- target app package와 app compatibility release train
- effective scenario registry hash와 selected scenario set/order
- effective runtime config hash
- traversal/identity major contract
- verified locale
- core flags 및 coverage/evidence에 영향을 주는 flags
- relevant collection schema major contracts

**B. 별도 baseline family**

- Android major, One UI major, TalkBack package/major
- form factor, foldable posture class
- validated device family

**C. 차이가 가능하나 경고/검증 필요**

- 같은 release train 안의 target app patch/build
- 같은 validated family 안의 model/serial 변경
- Android/One UI/TalkBack patch
- build fingerprint, display size/density override
- helper patch version, profiler enabled 여부처럼 result semantics를 바꾸지 않는 diagnostic flag

**D. 비교에 사용하지 않는 provenance**

- captured/started/finished time, baseline/run/batch/evidence IDs
- serial token, artifact locator, approval actor
- repository commit SHA 자체(단, dirty 또는 missing은 approval gate)

Commit이 D인 이유는 서로 다른 commit을 비교하는 것이 regression 탐지의 목적이기 때문이다.
반대로 traversal contract나 scenario/runtime hash가 바뀌면 A 규칙이 직접 비교를 막는다.

### 6.3 Matching levels

| 등급 | 조건 | 허용 결과 |
|---|---|---|
| `EXACT_MATCH` | A/B 동일, comparator-relevant C도 동일, critical metadata 완전 | 모든 metric 직접 비교 가능 |
| `COMPATIBLE_FAMILY` | A 동일, B family 동일, C 차이가 사전 검증된 compatibility policy 안 | 직접 비교하되 warnings와 environment delta를 결과에 포함 |
| `REVIEW_REQUIRED` | A는 동일하나 B/C가 미검증, 비핵심 required metadata 누락, app patch policy 미정, dirty source 등 | exploratory delta만 생성; 자동 PASS 금지, reviewer disposition 필요 |
| `INCOMPARABLE` | A mismatch/missing, 지원하지 않는 schema major, B family가 다르고 cross-family policy 없음 | regression metric을 계산하지 않거나 참고용으로 격리; 최종 INCOMPARABLE |

평가 순서는 schema validity → critical completeness → A → B → C다. 가장 낮은 등급이 전체
등급이 된다. baseline 검색은 `APPROVED`와 non-archived만 대상으로 하고 exact를 우선,
그 다음 compatible family를 선택한다. 동률이면 자동으로 최신 것을 고르지 않고
`REVIEW_REQUIRED`로 후보 목록과 차이를 반환한다.

## 7. Baseline Artifact Contract

### 7.1 Core package: 세 파일

지나친 sidecar 분리를 피하기 위해 후보로 제시된 11개 파일을 다음 3개로 합친다.

| 파일 | canonical | 책임 |
|---|---|---|
| `baseline.json` | 예 | baseline ID/key, source IDs, lifecycle snapshot, approval, acceptance, structured limitations, scenario results, coverage/identity/recovery/reconciliation/profiler **summaries**, schema map |
| `environment_profile.json` | 예 | 환경 값, 각 값의 source/status/capture time, redaction과 completeness |
| `artifact_manifest.json` | 예 | core/supporting artifact logical reference, SHA-256, size, media type, source schema, required tier, availability와 relocation hints |

`provenance.json`은 source IDs/commit/approval가 `baseline.json`, field provenance가
`environment_profile.json`, artifact provenance가 manifest에 이미 있어 별도 파일로 만들지
않는다. `scenario_results.json`, `coverage_summary.json`, `identity_summary.json`,
`recovery_summary.json`, `reconciliation_summary.json`, `profiler_summary.json`도 비교 시 한
원자적 snapshot이어야 하므로 `baseline.json.summaries` 아래에 둔다.

`known_issues.json`도 baseline package 안에서는 `known_issue_snapshot`으로 고정한다. 별도의
tracked current policy registry는 존재할 수 있지만, 과거 baseline의 승인 근거가 나중 정책
변경으로 바뀌지 않도록 승인 시 사용한 issue revision을 embedded snapshot으로 보존한다.

### 7.2 Canonical truth와 supporting artifacts

Canonical truth는 comparator가 raw artifact 없이도 aggregate/scenario/metric/cohort/signature
비교를 완료할 수 있는 정규화된 core 3개다. supporting artifacts는 감사, 재파싱, UI drill-down,
parser migration을 위한 근거다.

- XLSX: canonical source로 사용하지 않는다. presentation/export이자 supporting artifact다.
- evidence JSONL: baseline 디렉터리에 복사하지 않는다. checksum과 logical reference를 남긴다.
  보존 정책상 pin할 경우 local/object artifact repository에 content-addressed copy를 둔다.
- profiler: comparator에 필요한 scenario/metric aggregate는 `baseline.json`에 저장하고 원본
  scenario JSON/zip은 reference한다.
- focusable coverage: cohort record의 stable signature와 aggregate는 canonical summary에
  포함한다. 원본 전체 JSON은 supporting reference다.
- logs/screenshots/speech/crops: 기본적으로 reference만 저장하며 redaction policy를 적용한다.

### 7.3 Required canonical summary

`baseline.json.summaries`는 최소 다음을 가진다.

- `run`: requested/executed/terminal counts, process/result status, acceptance result
- `scenarios[]`: scenario ID, terminal/status/stop reason, steps, row counts, issue signatures
- `coverage`: total numerator/denominator/unknown, scenario aggregates, `cohort_hash`, taxonomy와
  stable candidate signatures
- `identity`: transaction count, verdict/confidence/completeness distributions, exceptional signatures
- `recovery`: attempts/recovered/failed와 reason/signature distribution
- `reconciliation`: status/checks, anchor abort, orphan/duplicate/write failures
- `profiler`: scenario runtime과 named metric count/duration; inclusive metric임을 명시
- `known_issue_snapshot`: issue ID/revision/scope/signature/expected result/status/review date

각 summary에는 `source_schema_version`, `normalizer_version`, `source_artifact_id`가 있어야 한다.
summary 숫자는 원본과 reconciliation rule을 만족해야 하며 승인 때 다시 검증한다.

### 7.4 Immutability, checksum, path loss

- candidate package는 승인 전 보완 가능하지만 approval은 완성된 bytes를 새 immutable
  approved revision으로 materialize한다.
- 승인 package의 core file은 수정하지 않는다. `SUPERSEDED`, `ARCHIVED` 같은 사후 상태는
  catalog의 append-only lifecycle event로 기록한다.
- 모든 artifact는 SHA-256, byte size, media type과 schema를 가진다. manifest 자기 checksum은
  catalog entry가 보유한다.
- source path는 절대경로를 저장하지 않고 `qa-run://<batch>/<device>/<name>` 또는
  `artifact://sha256/<digest>` 같은 logical locator를 쓴다.
- artifact가 이동하면 digest lookup으로 재연결한다. 삭제되면 availability를 `MISSING`으로
  index에 표시하되 approved canonical package는 바꾸지 않는다.
- embedded canonical summary가 완전하면 비교는 가능하지만, 필수 audit-tier raw artifact가
  없으면 재승인/supersede review는 차단한다. core file이 없거나 checksum이 틀리면 baseline은
  사용 금지다.

## 8. Lifecycle and Approval

### 8.1 상태와 전이

```text
CANDIDATE ──manual approve──> APPROVED ──replacement──> SUPERSEDED ──retention──> ARCHIVED
    │                             └────────retire──────────────────────────> ARCHIVED
    └──manual reject──> REJECTED ─────────────────────────────────────────> ARCHIVED
```

- `CANDIDATE`: source run에서 정규화되었으나 승인되지 않음. comparator의 authoritative
  baseline으로 선택할 수 없다.
- `APPROVED`: manual gate를 통과한 immutable comparison authority.
- `SUPERSEDED`: 같은 key/family에서 새 approved baseline이 대체함. historical audit에는 유지.
- `REJECTED`: 결손, regression, 잘못된 cohort 등의 이유로 승인 거부.
- `ARCHIVED`: active lookup에서 제외하지만 record를 삭제하지 않음.

역전이는 없다. rejected/superseded baseline을 다시 활성화하려면 새 candidate revision을
만든다. 같은 BaselineKey/family에는 active approved baseline을 하나만 허용하며 새 승인은
기존 baseline의 supersede event와 원자적으로 기록한다.

### 8.2 Lifecycle metadata

필수 metadata는 `created_by`, `created_at`, `approved_by`, `approved_at`, `approval_reason`,
`source_run_id`, `source_batch_id`, `evidence_run_id`, `supersedes`, `superseded_by`,
`known_limitations`, `acceptance_result`, `review_notes`다. Actor는 free text가 아니라 조직
identity 또는 local operator ID와 authentication source를 가진다. `approved_by`는
`created_by`와 같을 수 있는지 팀 policy에서 결정하되 기본안은 2인 review다.

### 8.3 Approval gates

모두 통과해야 한다.

1. expected scenario가 모두 terminal이며 approved optional availability/skip은 구조화되어 있다.
2. reconciliation PASS, orphan/duplicate/write failure 0.
3. anchor abort 0. 단, scenario contract가 optional availability를 명시하고 reviewer가 exact
   skip signature를 승인한 경우에만 limitation으로 허용한다.
4. environment completeness policy를 충족하고 semantic parser validation이 PASS다.
5. commit SHA 존재, source working tree clean.
6. runtime/scenario hash와 effective config snapshot이 서로 일치한다.
7. core/supporting artifact checksum과 summary reconciliation이 PASS다.
8. known issue는 owner, exact scope/signature, review/expiry date, evidence reference를 가진다.
9. coverage numerator/denominator/cohort와 added/removed semantics가 고정되어 있다.
10. human reviewer가 approval reason과 acceptance result를 서명한다.

자동 승인, “가장 최근 성공 run” 자동 대체, known issue 자동 등록은 금지한다.

### 8.4 PASS WITH LIMITATIONS 승인

허용한다. 단 다음 조건을 모두 만족해야 한다.

- limitation의 실제 row/scenario 결과는 원래 `FAIL`/warning으로 보존한다.
- limitation이 exact KnownIssue scope/signature와 일치하고 신규 유사 failure는 포함하지 않는다.
- limitation이 coverage numerator/denominator를 수정하지 않는다.
- limitation 외 acceptance gate는 모두 통과한다.
- reviewer가 왜 baseline으로 유용한지, owner와 review date를 승인 metadata에 기록한다.

따라서 “row FAIL이 사라져 PASS가 됨”이 아니라 “비교 기준에 이미 존재하는 정확한
limitation을 가진 run이며 신규 regression은 없음”이라는 run-level 판정이다.

## 9. Comparator Contract

### 9.1 입력

```json
{
  "approved_baseline": "<validated core package>",
  "current_run_summary": "<same normalized summary contract>",
  "environment_profile": "<current profile>",
  "scenario_registry": "<effective canonical registry descriptor>",
  "known_issue_policy": "<versioned policy snapshot>"
}
```

입력 validator는 checksum/schema/status, baseline `APPROVED`, effective scenario set,
environment completeness를 먼저 확인한다. raw XLSX를 comparator input으로 직접 받지 않는다.

### 9.2 출력

```json
{
  "schema_version": "talkback-comparison-result-v1",
  "comparability": "EXACT_MATCH",
  "overall_result": "PASS_WITH_LIMITATIONS",
  "baseline_id": "...",
  "current_run_id": "...",
  "environment_deltas": [],
  "inventory_deltas": [],
  "findings": [],
  "decision_reasons": []
}
```

각 finding은 `classification`, `unit`, `scenario_id`, `metric`, `baseline_value`,
`current_value`, `absolute_delta`, `relative_delta`, `cohort_relation`, `issue_signature`,
`known_issue_match`, `evidence_refs`, `explanation`을 가진다.

Classification은 다음과 같다.

- `REGRESSION`: 동일 비교 contract/cohort에서 악화 또는 신규 failure
- `IMPROVEMENT`: 동일 조건에서 회복/개선; 자동 baseline 교체 근거는 아님
- `EXPECTED_VARIATION`: 사전 정의된 compatible environment/dynamic cohort 변화
- `KNOWN_LIMITATION`: 원래 실패는 유지되며 exact approved issue가 설명을 부착
- `REVIEW_REQUIRED`: 인과/호환/서명이 불충분해 사람 판정 필요
- `INCOMPARABLE`: 해당 unit을 직접 비교할 수 없음
- `UNCHANGED`: 동일

비교 단위 `unit`은 `run_aggregate | scenario | metric | row_issue_signature`다.

### 9.3 판정 순서와 overall result

1. Environment/key matching.
2. Reconciliation와 terminal/integrity gate.
3. Scenario set/status/stop 비교.
4. Coverage cohort set comparison.
5. Row/issue signature, identity, recovery, profiler metric 비교.
6. KnownIssue exact match annotation.
7. overall reduction.

Overall policy:

- `INCOMPARABLE`: overall comparability가 incomparable이거나 핵심 input/schema가 없음.
- `FAIL`: 신규/악화된 critical `REGRESSION`, integrity/terminal gate 실패, 또는 미해결
  `REVIEW_REQUIRED`가 존재. 후자의 reason은 code regression이 아니라
  `unresolved_review_required`로 명시한다.
- `PASS WITH LIMITATIONS`: regression이 없고 모든 non-pass finding이 승인된
  `KNOWN_LIMITATION` 또는 disposition이 끝난 expected variation임.
- `PASS`: exact/compatible 비교 가능, regression/known limitation/unresolved review 없음.

Improvement는 PASS를 만들 수 있지만 baseline을 자동 promote하지 않는다. Known limitation은
finding의 raw failure/status를 변경하지 않는다.

### 9.4 Coverage 비교

Coverage cohort ID는 canonical candidate signature 집합의 hash다. signature는 최소
`scenario_id`, stable semantic/resource identity, taxonomy, local-tab/surface scope를 포함하고
label/bounds처럼 동적인 값은 별도 attributes로 둔다.

Comparator는 다음을 반드시 보고한다.

- `same_denominator_cohort`: total/scenario cohort hash가 동일한가
- `added_candidates`, `removed_candidates`: stable signature set difference와 taxonomy
- `covered_delta`: same signature에서 covered 상태 변화
- `expected_delta`: denominator의 증감
- `coverage_rate_delta`: 위 숫자에서 파생한 표시 값
- `intersection_coverage`: 공통 cohort에 대한 baseline/current covered 비교

동일 cohort에서는 `COVERED → MISSED/UNKNOWN`이 regression 후보이고
`MISSED/UNKNOWN → COVERED`는 improvement다. cohort가 바뀌면:

- 공통 cohort 변화는 별도로 직접 비교한다.
- added/removed는 `DYNAMIC_INVENTORY_DELTA`로 분리한다.
- required candidate 제거, 대규모 unexplained drift, source/category 변화는
  `REVIEW_REQUIRED`다.
- percentage만 내려갔지만 공통 cohort covered가 유지되고 required candidates가 추가된 경우
  code regression으로 선언하지 않는다.

### 9.5 원인 분리 규칙

- A/B 환경 mismatch: environment difference 또는 incomparable; code regression으로 귀속 금지.
- same environment + same cohort + terminal/row/identity 악화: regression 근거.
- same environment + changed inventory + stable intersection: dynamic inventory variation.
- compatible-family C 차이와 delta가 동시에 발생: `REVIEW_REQUIRED`, environment delta를
  evidence로 연결하되 인과를 단정하지 않는다.
- exact known issue signature 재현: raw FAIL + `KNOWN_LIMITATION` annotation.
- signature가 비슷해도 exact match가 아니면 신규 finding이다.

## 10. Known Issue Contract

```json
{
  "issue_id": "TB-KI-0001",
  "revision": 1,
  "title": "Menu EMPTY_VISIBLE on app-owned inaccessible node",
  "issue_type": "APP_ACCESSIBILITY_LIMITATION",
  "scenario_id": "menu_main",
  "environment_scope": {"locale": "en-US", "app_release_train": "1.8"},
  "match_signature": {
    "mismatch_type": "EMPTY_VISIBLE",
    "final_result": "FAIL",
    "surface_role": "content",
    "stable_resource_or_node_signature": "..."
  },
  "expected_result": {"final_result": "FAIL"},
  "first_observed": "<run/evidence ref>",
  "last_confirmed": "<run/evidence ref>",
  "owner": "...",
  "status": "ACCEPTED_LIMITATION",
  "review_at": "2026-10-15T00:00:00Z",
  "expires_at": "2027-01-15T00:00:00Z",
  "evidence_references": []
}
```

추가 필수 필드는 `revision`, severity, scope schema version, signature normalizer version,
created/approved actor다. 상태는 `OPEN | ACCEPTED_LIMITATION | RESOLVED | EXPIRED`다.
`OPEN`, `RESOLVED`, `EXPIRED` issue는 suppression/limitation match에 사용할 수 없다.

Match는 issue ID가 아니라 exact structured signature와 environment scope 교집합으로 한다.
wildcard scenario, mismatch type만 있는 broad signature, 유효기간 없는 issue는 승인할 수 없다.
Menu와 Home Monitor는 서로 다른 issue로 등록한다.

Known issue는 절대로:

- row/scenario의 실제 FAIL을 PASS로 바꾸지 않는다.
- coverage numerator나 candidate taxonomy를 수정하지 않는다.
- 새 유사 FAIL을 자동 무시하지 않는다.
- environment scope 밖에서 적용되지 않는다.
- owner/review가 만료된 상태로 active baseline 승인을 정당화하지 않는다.

Comparator UI/JSON은 `raw_result=FAIL`, `classification=KNOWN_LIMITATION`, `issue_id=...`를
동시에 보여준다.

## 11. Storage Layout

### 11.1 Git-tracked metadata/schema

```text
baselines/
  catalog.schema.json
  <app-key>/
    index.json
    <baseline-id>/
      baseline.json
      environment_profile.json
      artifact_manifest.json
baseline-policies/
  known-issues.json
  device-families.json
  compatibility-policy.json
docs/design/schemas/
```

Git에는 compact, redacted, reviewable canonical metadata와 policy/schema만 저장한다. 승인
package당 크기 budget을 두고 row text/speech/screenshot/raw dumpsys는 넣지 않는다.
`index.json`은 active baseline과 append-only lifecycle events를 담는다.

### 11.2 Local artifact repository

```text
.baseline-artifacts/              # gitignored
  sha256/ab/<full-digest>/
    payload
    metadata.json
```

대형 XLSX, JSONL, profiler zip, logs/crops를 보존할 때 checksum으로 deduplicate한다. local
repository는 없어져도 Git core metadata를 손상시키지 않지만 audit-tier artifact가 없다는
상태는 명확히 표시한다.

### 11.3 QA Frontend run directory reference

초기 candidate는 `qa-run://batch_.../device-token/...` logical URI로 기존
`qa_frontend_runs`를 참조할 수 있다. 이 root는 local history이며 retention에 의해 삭제될 수
있으므로 APPROVED 시 retention-required supporting artifact는 `.baseline-artifacts`로 pin한다.
raw serial이 들어간 현재 directory name은 shared manifest에 복사하지 않는다.

### 11.4 향후 확장

`artifact://sha256/...` resolver만 local filesystem에서 object storage로 바꾸면 된다.
DB가 생겨도 source of truth는 versioned JSON contract와 content digest이며 DB row는 index/cache다.
Phase 10 첫 버전에는 DB, remote upload, distributed locking을 구현하지 않는다.

## 12. Privacy and Redaction

| 데이터 | canonical/shared baseline 정책 |
|---|---|
| device serial | raw 저장 금지. 조직 비밀키 HMAC token; local private provenance만 별도 접근 통제 가능 |
| 사용자 계정 정보 | 저장 금지. 필요하면 reviewer가 관리하는 fixture ID/tenant class만 저장 |
| 앱 화면 text | canonical에는 normalized signature/minimal stable token만. free text는 redact/hash; supporting artifact 접근 통제 |
| speech | canonical 원문 금지. mismatch category와 redacted digest만; 원본은 opt-in protected artifact |
| absolute local paths | 금지. logical URI와 digest 사용 |
| repository dirty diff | 저장 금지. boolean과 선택적 diff digest만; diff content 수집 금지 |
| build fingerprint | local profile에는 허용, shared profile은 정책에 따라 exact encrypted 또는 salted/HMAC digest + normalized build family/patch fields |

일반 hash는 serial/account 같은 low-entropy identifier의 익명화 수단이 아니다. HMAC key는
baseline package 밖에서 관리한다. Artifact manifest는 `contains_sensitive_data`,
`redaction_policy`, `retention_class`, `access_class`를 가진다. redaction 후 checksum을 계산하고,
원본을 보존하면 원본 checksum은 비공개 manifest에만 둔다.

## 13. Migration and Backfill

### 13.1 Phase 9.5.4 candidate 평가

`batch_20260715_082735`는 다음 이유로 CANDIDATE 생성이 가능하다.

- 32/32 terminal/executed, anchor abort 0
- reconciliation PASS, orphan/duplicate/write failure 0
- coverage 323/576과 full canonical record 보유
- V2 864 transactions / INDETERMINATE 53, profiler 32개
- acceptance record의 Recovery 27 attempts / 12 recovered
- commit `c0a1da4...`, dirty false
- runtime config/scenario registry hash와 flags 존재
- Menu와 Home Monitor `EMPTY_VISIBLE` raw FAIL이 summary/evidence로 남아 있음

Acceptance label은 요청의 확정 판정인 `PASS WITH LIMITATIONS`로 candidate에 기록하되,
현재 frontend `scenario_result_status=warning`과 row FAIL 2개를 덮어쓰지 않는다. 구조화된
limitation은 (1) Menu EMPTY_VISIBLE, (2) Home Monitor EMPTY_VISIBLE, (3) historical ko-KR
nominal과 direct parity 불가다. 세 번째는 row KnownIssue가 아니라
`COMPARISON_SCOPE_LIMITATION`이며 locale mismatch를 허용하는 suppression으로 사용해서는 안 된다.

### 13.2 증거로 backfill 가능한 항목

각 backfill은 `status=BACKFILLED`, source artifact digest, extraction tool version,
`backfilled_at`을 기록한다.

- batch/evidence run IDs, started/finished time, serial token, model
- locale `en-US`, display physical size
- repository commit/dirty, runner/runtime/registry/helper hashes
- target app package/version을 기존 package dump에서 구조화
- Android fingerprint와 그 안에 **명시된** release token(별도 release property를 읽은 것으로
  표현하지 않음)
- enabled service log에서 실제 TalkBack package/component
- feature flags, runtime config bytes/hash, selected 32 scenarios
- evidence/coverage/reconciliation/profiler/identity schema와 summaries
- 현재 보존된 artifact의 checksum/size. 단 이는 run-time checksum이 아니라
  `backfilled_at` 시점 checksum이며 실행 후 무변조를 소급 증명하지 않는다.
- known issue candidate의 Menu/Home Monitor exact row evidence reference

### 13.3 새 run이 필요한 항목

- environment `captured_at`의 동시성 보장
- Android SDK를 실행 시점의 explicit property로 수집
- One UI version
- Samsung TalkBack versionName/versionCode. 현재 Google package query 결과는 invalid이고
  log에는 실제 package component만 있다.
- display density/override, foldable capability/posture/active display
- reviewed device family/form factor mapping을 적용한 capture
- complete collection schema map과 explicit traversal engine contract
- semantic validation을 통과한 structured package metadata
- artifact checksum을 run finalization과 동시에 봉인한 provenance

현재 연결된 단말을 지금 조회한 값을 과거 run에 붙이면 안 된다. model 이름으로 form factor,
One UI, SDK, fold state를 추정해서도 안 된다. 따라서 이 candidate의 comparability는
`REVIEW_REQUIRED`, approval eligibility는 false다. Phase 10.1 collector가 적용된 fresh full
run이 APPROVED 후보가 된다.

Historical ko-KR nominal은 locale, runtime/scenario provenance와 inventory cohort parity가
없으므로 Phase 9.5.4 en-US candidate와 직접 비교하지 않는다. 별도 locale baseline family가
필요하다.

## 14. Failure Modes

| Failure | 처리 |
|---|---|
| package-not-found 문자열을 available로 저장 | semantic validator가 `INVALID`; approval 차단 |
| scenario/runtime hash mismatch | INCOMPARABLE; 실행 결과 비교 금지 |
| locale requested와 effective가 다름 | capture failure; candidate 생성은 가능하나 승인 금지 |
| baseline core checksum mismatch | baseline quarantine, lookup 제외 |
| supporting artifact missing | canonical 비교는 가능할 수 있으나 audit/reapproval 제한 표시 |
| 둘 이상의 exact approved baseline | catalog integrity failure; 자동 선택 금지 |
| dynamic denominator 변화 | set/cohort delta로 분리; rate-only regression 금지 |
| known issue signature가 너무 넓음/만료 | match 금지, 신규 finding으로 처리 |
| version 문자열 parse ambiguous | REVIEW_REQUIRED 또는 critical field면 INCOMPARABLE |
| dirty tree/commit missing | approval 금지; diff content는 수집하지 않음 |
| comparator schema가 metric semantics를 모름 | 해당 metric INCOMPARABLE; 숫자 coercion 금지 |
| candidate 작성 중 crash | temp directory 후 atomic rename; partial package lookup 제외 |
| lifecycle index와 package 불일치 | immutable package 우선, index repair 필요; 자동 상태 변경 금지 |
| raw serial/text/path 누출 | publish validation failure, redaction 후 새 revision 생성 |

## 15. Rollout Plan

1. **Phase 10.1 — Contracts and capture foundation**: schema/normalizer/validator, environment capture,
   current-run normalizer, local catalog layout와 candidate export. 승인/promotion 없음.
2. **Phase 10.2 — Manual lifecycle tooling**: offline validate, explicit approve/reject/supersede,
   checksum pinning, known issue registry와 audit log. frontend 없음.
3. **Phase 10.3 — Comparator**: matching levels, cohort-aware deltas, classifications와 overall
   decision contract 구현.
4. **Phase 10.4 — QA Frontend read-only integration**: baseline candidates/comparability/findings
   표시. 승인 UI는 별도 security review 후 검토.
5. fresh en-US full run으로 첫 approved baseline을 만들고, ko-KR과 다른 family/device는
   각각 독립 승인한다.

각 단계에서 기존 runner output은 backward-compatible하게 읽고, 새 capture 실패가 traversal
behavior를 바꾸지 않도록 side-channel/fail-closed-for-approval로 유지한다.

## 16. Phase 10.1 Implementation Scope

Phase 10.1의 정확한 구현 범위는 다음으로 제한한다.

1. versioned JSON schema/TypedDict 또는 dataclass contract:
   `EnvironmentProfile`, `BaselineCandidate`, `ArtifactManifest`, normalized run summary.
2. preflight/finalization의 read-only environment collector와 semantic validators:
   Android/One UI, actual enabled TalkBack package/version, target/helper versions, display/fold,
   Git/config/registry/engine/schema/flags.
3. canonical JSON과 SHA-256 utilities, redaction/logical URI rules.
4. 기존 evidence/coverage/profiler/batch summary를 읽어 compact normalized summary와 inventory
   cohort hash를 생성하는 offline candidate builder.
5. core/supporting artifact checksum manifest와 local Git-ignored artifact resolver/pinning primitive.
6. completeness/matching **validation model**과 report. Phase 10.3 metric comparator는 구현하지 않음.
7. Phase 9.5.4를 partial candidate로 변환하는 dry-run/backfill report와 fresh-run readiness test.
8. unit/schema fixture tests: deterministic hash, invalid package output, locale/config mismatch,
   redaction, missing artifact, cohort stability.
9. 문서화된 CLI 초안은 `inspect`/`build-candidate`/`validate`까지만 허용한다.

명시적으로 제외한다.

- `approve`, `promote`, `supersede` mutation
- frontend/API 변경
- DB/object storage/network upload
- production traversal/scenario/recovery/identity behavior 변경
- automatic known issue registration 또는 baseline selection

## 17. Open Decisions

1. SmartThings version의 compatibility release train을 `1.8`로 볼지 full version으로 볼지.
   vendor release semantics를 검증하기 전에는 full version + REVIEW_REQUIRED가 안전하다.
2. Android/One UI/TalkBack patch 차이에 대한 validated compatibility matrix의 owner와 review
   주기.
3. `device_family` mapping의 관리 주체, mapping revision과 같은 family 내 model validation 기준.
4. foldable에서 cover/main display와 open/closed posture를 각각 별도 family로 둘 범위.
5. shared Git profile에 build fingerprint HMAC만 둘지, normalized build ID/patch를 추가할지.
6. approved package의 Git size budget과 coverage stable signatures의 최소 보존 범위.
7. supporting artifact retention 기간, 삭제 권한, local artifact pin 실패 시 approval 정책.
8. 2인 approval을 필수로 할지와 actor identity source.
9. optional availability/skip을 baseline approval에 허용할 scenario contract와 severity.
10. profiler threshold는 workload parity를 어떤 metric(count/steps/transactions/cohort)로 충족한
    후 적용할지. threshold 자체는 Phase 10.3에서 calibration한다.
11. account-dependent dynamic inventory를 개인정보 없이 구분할 fixture/cohort identifier.
12. existing raw text/speech/screenshot의 redaction tool과 접근/retention policy.

이 결정들이 닫히기 전에도 Phase 10.1 capture/validation은 진행할 수 있다. 다만 app release
train, device family, patch compatibility가 확정되지 않은 조합은 보수적으로
`REVIEW_REQUIRED`로 남겨야 한다.
