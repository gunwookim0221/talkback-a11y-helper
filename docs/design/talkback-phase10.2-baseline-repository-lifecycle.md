# TalkBack Phase 10.2 — Manual Baseline Repository & Lifecycle

상태: Implemented

기준 commit: `8a6c86926d8a31e6a60e67ed985bd51b3e849b9b`

범위: offline Candidate revalidation, 수동 approve/reject/supersede/archive, immutable core package,
content-addressed artifact pinning, append-only lifecycle과 rebuild 가능한 local catalog. Comparator,
자동 승인/선택, Frontend, DB와 remote storage는 포함하지 않는다.

## 1. Executive Summary

Phase 10.2는 `talkback-baseline-candidate-v1`을 직접 수정하거나 상태만 바꾸지 않는다. 사람이
검토한 Candidate를 승인 직전에 원본 run root에서 다시 검증하고, 새로운
`talkback-approved-baseline-v1` immutable package로 materialize한다. 승인과 거부에는 구조화된
actor와 명시적 reason이 필요하다. `NOT_ELIGIBLE`, INCOMPLETE fingerprint, dirty source 또는
required artifact 결손은 자동으로 우회할 수 없다.

승인 package의 세 core JSON은 이후 덮어쓰지 않는다. 현재 상태는 hash-chain을 가진
`lifecycle.jsonl`에서 reduce하고 `catalog.json`과 app index는 재생성 가능한 cache로 취급한다.
Environment fingerprint는 비교 identity이고 Candidate/Environment/core checksum은 문서 무결성
identity이므로 서로 대체하지 않는다.

## 2. Repository Layout

```text
baselines/
  catalog.json
  lifecycle.jsonl
  <target-app-package>/
    index.json
    baseline_<key-prefix>_r0001/
      baseline.json
      environment_profile.json
      artifact_manifest.json

.baseline-artifacts/                 # Git ignored
  sha256/<first-two>/<full-digest>/
    payload
    metadata.json
```

`baselines/`에는 compact/redacted canonical metadata만 둔다. raw XLSX, JSONL, log와 profiler ZIP은
core package에 복사하지 않는다. App key는 검증된 target package를 소문자 safe token으로
정규화한다. Package path나 raw device directory는 JSON에 저장하지 않는다.

## 3. Core Package Contract

승인 시 다음 세 파일을 canonical sorted-key/NFC/compact UTF-8 JSON과 trailing newline으로 쓴다.

### `baseline.json`

- schema, deterministic `baseline_<key-prefix>_rNNNN`, append-only revision
- source Candidate/run/batch/evidence ID와 reviewed Candidate document digest
- `talkback-baseline-key-v1` source와 lookup용 digest
- COMPLETE EnvironmentFingerprint source/status/hash
- immutable approval 시점 lifecycle snapshot
- acceptance, structured limitations, raw Candidate limitations와 reviewed known-limitation snapshot
- Scenario Set contract와 comparison/normalizer version
- run/coverage/identity/recovery/reconciliation/profiler normalized summaries
- core schema map, source commit/dirty, Candidate creation time와 approval time

### `environment_profile.json`

Candidate가 참조한 redacted EnvironmentProfile의 정확한 canonical object다. 승인 전에 파일 byte
digest, embedded fingerprint, profile 값에서 재생성한 fingerprint와 Candidate fingerprint를 모두
비교한다. `captured_at`과 field provenance는 문서에는 남지만 BaselineKey에는 들어가지 않는다.

### `artifact_manifest.json`

각 entry는 type, logical reference, content digest, media type, size, source schema, required/tier,
source availability, pinned reference, sensitive-data flag와 retention class를 가진다. Core JSON은
서로의 checksum을 embed하지 않는다. 세 checksum은 APPROVED lifecycle event가 보유하여 checksum
cycle을 피한다.

## 4. Approval Workflow

API는 `BaselineRepository.approve(ApprovalRequest)`다. 요청은 Candidate path와 reviewer가 확인한
Candidate SHA-256, `identity + authentication_source` actor, reason, acceptance, limitations,
optional `supersedes`, pin policy를 요구한다.

처리 순서는 다음과 같다.

1. Candidate canonical bytes/digest/schema/deterministic ID 재검증
2. 현 Candidate validator 재실행 및 `CANDIDATE + eligible=true` 확인
3. Environment document digest와 COMPLETE fingerprint source/hash 재검증
4. required artifact 존재/digest, FULL Scenario Set, reconciliation, clean Git와 schema gate 확인
5. reviewed limitation completeness/exact signature/wildcard/explicit acceptance 확인
6. local repository lock 아래 duplicate Candidate, revision과 active BaselineKey 재확인
7. required artifacts를 content-addressed store에 pin
8. temp core package 생성, canonical byte/checksum 재검증 후 atomic directory rename
9. CANDIDATE_VALIDATED, ARTIFACT_PINNED, APPROVED와 필요 시 SUPERSEDED event append/fsync
10. catalog/app index atomic rebuild

Eligibility는 review 가능 조건일 뿐 승인 명령을 호출하지 않는다. Candidate digest는 fingerprint가
아니며 Candidate review bytes의 integrity guard다. 같은 Candidate ID의 중복 승인은 차단한다.

`PASS WITH LIMITATIONS`는 reviewer가 명시적으로 수락해야 한다. 모든 raw Candidate limitation은
reviewed object와 scenario/mismatch signature가 연결되어야 하며 owner, non-empty environment
scope, exact scenario/signature, review 또는 expiry date, evidence reference가 필요하다. `*`가 든
broad scope/signature는 거부한다. Raw FAIL/WARNING은 `candidate_limitations`에 그대로 보존한다.

## 5. Rejection Workflow

`BaselineRepository.reject(...)`는 canonical Candidate와 optional reviewed digest를 확인한 뒤
REJECTED event를 append한다. Reviewer, reason과 category가 필수다. Candidate 파일이나 source run은
삭제하지 않는다. Reject는 baseline package를 생성하거나 active lookup을 변경하지 않는다.

## 6. Supersede and Archive

정상 replacement 경로는 새 Candidate 승인 요청의 `supersedes=<active-baseline-id>`다. 현재 active가
있으면 이 값을 생략할 수 없다. 이전/new BaselineKey digest가 정확히 같아야 하고 서로 다른 family는
거부한다. APPROVED event 자체가 이전 ID를 SUPERSEDED로 reduce하므로 event 사이 crash가 나도 active
두 개가 되지 않는다. 뒤이은 명시적 SUPERSEDED event는 `superseded_by` 감사 관계를 기록한다.

`supersede(...)` 함수/CLI도 두 existing APPROVED package를 검사하는 명시적 관리 API로 제공한다.
건강한 repository의 일반 교체에는 위 replacement approval을 사용한다. `archive(...)`는 APPROVED,
REJECTED 또는 SUPERSEDED record에 ARCHIVED event만 추가한다. Package를 삭제하거나 다시 APPROVED로
되돌리지 않는다.

## 7. Catalog and Index

Global `catalog.json`은 schema/repository version, baseline summaries, BaselineKey별 active mapping,
lifecycle tail hash/count, update time과 self-checksum을 가진다. Checksum source는
`catalog_checksum` field를 제외한 canonical catalog다.

App `index.json`은 app key, baseline key/fingerprint, active mapping, approved/superseded/archived
revision과 approval summary를 가진다. Package와 lifecycle이 authoritative하며
`rebuild_indexes()`는 손상되거나 없는 catalog를 무시하고 둘로부터 재생성한다. REJECTED Candidate는
package가 없으므로 lifecycle에서만 보존한다.

## 8. Lifecycle Audit Log

각 JSONL event는 `talkback-baseline-lifecycle-event-v1`, deterministic event ID, type, 대상,
actor/reason/time, previous hash와 event hash를 가진다. Hash source는 event ID/hash를 제외한 canonical
event이고 previous hash를 포함한다. 지원 type은 다음과 같다.

- `CANDIDATE_VALIDATED`
- `APPROVED`
- `REJECTED`
- `SUPERSEDED`
- `ARCHIVED`
- `ARTIFACT_PINNED`
- `VALIDATION_FAILED`

Event는 append와 fsync만 수행한다. `verify()`는 line JSON, schema chain, event hash, lifecycle relation
cycle과 active BaselineKey uniqueness를 확인한다.

## 9. Artifact Pinning

`ContentAddressedArtifactStore`는 source와 expected SHA-256을 먼저 비교한다. 같은 filesystem의
temporary directory에 payload와 path-free metadata를 쓴 뒤 payload checksum을 다시 확인하고
directory를 atomic rename한다. Existing digest는 payload checksum을 확인한 후 deduplicate한다.
Reference는 `artifact://sha256/<digest>`다.

모든 required artifact는 pin되며 정책으로 끌 수 없다. Required pin 실패는 approval 실패다.
선택된 optional artifact의 pin 실패는 immutable manifest에서 pinned reference를 null로 두고 warning을
반환한다. Metadata에는 source path, raw serial 또는 account value를 저장하지 않으며 sensitive flag와
retention class만 기록한다. Encryption/HMAC/remote upload는 범위 밖이다.

## 10. Offline Revalidation

`offline_revalidate_candidate()`는 read-only 검사 API다. Candidate 파일 UTF-8/canonical/digest,
deterministic Candidate ID, current schema/eligibility report, EnvironmentProfile canonical digest,
recomputed/embedded/Candidate fingerprint equality, logical URI resolution과 artifact digest를 검사한다.
`validate-candidate` CLI는 동일 API를 호출한다.

EnvironmentProfile filename과 artifact logical URI의 마지막 filename만 run root에서 resolve한다.
Candidate가 가진 absolute path나 legacy output directory는 사용하지 않는다. Candidate 생성 후 source
artifact가 삭제/변경되면 승인 시점 revalidation이 실패한다.

## 11. Failure Atomicity

Repository write는 `O_EXCL` lock file로 한 local writer만 허용한다. Approval은 validation/pin 이후
temp package를 검증하고 destination이 없을 때만 atomic rename한다. Core destination overwrite는
없다. Lifecycle append는 flush/fsync 후 catalog를 temp+replace로 갱신한다.

APPROVED event의 `supersedes` reduction은 교체 중간 crash에서도 active 하나를 유지한다. Package rename
후 audit append 전 crash는 package를 몰래 승인하지 않고 `orphan_package`로 검출한다. Audit 후 catalog
전 crash는 rebuild로 복구한다. Pin 중 실패는 core package를 만들지 않는다. 이미 성공한 CAS blob은
content identity상 안전한 deduplicated orphan일 수 있다.

## 12. Privacy

- shared EnvironmentProfile의 raw serial value가 non-empty이면 materialization을 거부한다.
- Windows/known user-home absolute path를 core JSON에서 거부한다.
- artifact metadata에 source path를 넣지 않는다.
- source logical URI는 `qa-run://...`, pinned reference는 `artifact://sha256/...`만 사용한다.
- serial의 일반 SHA-256을 pseudonym으로 만들지 않는다.
- dirty source는 boolean만 보존하고 diff는 수집하지 않는다.

## 13. CLI/API

Entry point는 `python -m tb_runner.baseline_cli`다.

```text
inspect-candidate       validate-candidate
approve                 reject
supersede               archive
list-baselines          inspect-baseline
verify-repository       rebuild-index
```

Write command는 `--repository`, `--actor`, `--auth-source`, `--reason`과 대상을 명시한다. Approve는
`--digest`, `--acceptance`가 필수이고 JSON limitation snapshot, explicit limitation acceptance,
supersedes와 optional pin type을 받을 수 있다. 함수 API가 primary이며 CLI는 JSON 결과와 non-zero
failure code를 제공한다.

## 14. Validation Results

신규 tests는 COMPLETE approval/core/index, NOT_ELIGIBLE/INCOMPLETE/dirty/missing/checksum gate,
PASS WITH LIMITATIONS completeness와 wildcard, duplicate/immutability, reject/supersede/archive,
active uniqueness/hash chain, catalog rebuild/package loss, CAS checksum/dedup/temp rename,
required/optional pin failure, privacy, determinism과 read-only CLI를 다룬다.

- Phase 10.2 repository module: 18 passed
- Phase 10.1A + 10.1B + 10.2 contract set: 57 passed
- Environment/Baseline/Evidence/Coverage/Identity/Recovery/Profiler 관련 broad set: 257 passed
- 전체 `tests/` 시도: 1,894 passed, 1 skipped, 16 failed, 36 setup errors. 실패는 현 HEAD의
  non-Phase-10 capture/overlay/dashboard expectation 및 suite-global config 상태이고, setup error는
  기존 `.test_tmp` ACL의 `PermissionError`다. Phase 10 관련 targeted/broad set에서는 재현되지 않았다.

Phase 9.5.4 `batch_20260715_082735`는 dry-run validation만 수행한다. 환경 profile/digest와 COMPLETE
fingerprint가 없어 `NOT_ELIGIBLE`이며 승인하지 않는다. Artifact manifest는 파싱 가능하고 source
run은 Candidate staging 입력으로 사용할 수 있지만 실제 첫 APPROVED는 collector가 적용된 fresh
32-scenario full run 이후다.

## 15. Known Limitations

- lifecycle hash chain은 tamper evidence이지 인증 서명/HMAC이 아니다.
- local lock에는 lease/stale-lock 자동 판정이 없고 distributed writer를 지원하지 않는다.
- package rename과 first audit append를 하나의 filesystem transaction으로 묶을 수 없어 crash 시
  orphan package를 자동 승인하지 않고 검출만 한다.
- CAS encryption, access control, garbage collection, remote replication과 retention executor는 없다.
- standalone `supersede`는 existing approved package의 관리/복구용이며 정상 replacement는 approval의
  explicit `supersedes` 계약을 사용한다.
- device family/form factor mapping이 준비되지 않은 Collector profile은 여전히 INCOMPLETE이므로
  production approval 전에 reviewed mapping이 필요하다.
- Known Issue Engine 전체가 아니며 승인 시 전달된 immutable reviewed snapshot만 검증/보존한다.

## 16. Phase 10.3 Comparator Input

Comparator는 catalog의 `active_baselines[baseline_key_digest]`만 lookup하고 package/lifecycle/core
checksum 검증을 먼저 수행한다. 입력 canonical truth는 다음이다.

- `baseline.json.baseline_key` source와 digest
- COMPLETE `environment_fingerprint` source/status/hash
- `scenario_set_contract`
- comparison/normalizer contract versions
- run, coverage/cohort, identity, recovery, reconciliation, profiler summaries
- raw-result-preserving structured/known limitation snapshot
- exact redacted `environment_profile.json`
- audit drill-down용 `artifact_manifest.json` logical/pinned reference

Phase 10.3은 raw XLSX를 canonical comparator input으로 사용하거나 catalog의 가장 최신 revision을
자동 선택하지 않는다. Active package가 없거나 checksum/schema가 틀리면 INCOMPARABLE/validation
failure로 처리해야 한다.
