# TalkBack Phase 10.1B — Baseline Candidate Builder

상태: Implemented

기준 commit: `40d3d0375600e44e78705120470824481ffa495e`

범위: offline BaselineCandidate builder, normalized comparison input, artifact reference manifest,
validation/approval eligibility와 legacy backfill. Approval, promotion, comparator 실행, frontend,
DB/storage/pinning은 포함하지 않는다.

## 1. Candidate Schema

Candidate schema는 `talkback-baseline-candidate-v1`이다. Candidate는 승인된 baseline이 아니라
review 가능한 immutable-input snapshot의 초안이다.

주요 필드는 다음과 같다.

- `candidate_id`: volatile time/path를 제외한 canonical identity source의 deterministic digest
- `created_at`: candidate materialization time; candidate ID 입력이 아님
- `source_run_id`, `source_batch_id`, `evidence_run_id`: 서로 추정하지 않고 별도로 보존
- `environment_reference`, `environment_fingerprint`, `document_digest`
- `approval_state`: `CANDIDATE | NOT_ELIGIBLE`만 지원
- `approval_eligibility`: 자동 validation 결과와 failure reason
- `limitations`: 관찰된 limitation과 provenance/comparison scope limitation
- `artifact_manifest`: raw artifact를 복사하지 않는 logical reference/checksum manifest
- `comparison_contract`: Phase 10.3 comparator가 소비할 normalized input
- `validation_report`: PASS/WARNING/FAIL check 목록

Candidate 문서는 sorted-key, NFC, compact UTF-8 canonical JSON으로 기록한다. Candidate 파일명은
`<candidate-id>.baseline_candidate.json`이며 atomic replace를 사용한다.

## 2. Deterministic Candidate ID

ID source는 candidate schema, source run/batch/evidence ID, EnvironmentFingerprint source/status,
Scenario Set hashes와 runtime/registry hashes다. `created_at`, artifact mtime, absolute/local path,
raw serial, candidate filename과 validation message는 제외한다.

같은 source run contract를 다른 시간에 다시 build하면 candidate ID는 동일하다. Candidate
document digest는 `created_at`과 validation/artifact snapshot을 포함하므로 달라질 수 있다.

## 3. Approval State and Eligibility

Phase 10.1B는 approval mutation을 구현하지 않는다.

| 상태 | 의미 |
|---|---|
| `CANDIDATE` | 모든 automatic eligibility check가 PASS인 review 대상 |
| `NOT_ELIGIBLE` | Candidate 생성은 성공했지만 하나 이상의 approval gate가 FAIL |

`CANDIDATE`도 APPROVED가 아니며 comparator의 authoritative baseline으로 사용할 수 없다.

Eligibility는 다음을 모두 요구한다.

1. EnvironmentFingerprint `COMPLETE`, supported schema와 64자리 hash
2. EnvironmentProfile document digest 존재
3. supported comparison contract
4. coverage/identity/profiler normalized summary 존재
5. reconciliation PASS
6. orphan/duplicate/write failure/anchor abort 0
7. scenario/runtime hashes와 traversal/identity/collection contracts 존재
8. target app package/version 존재
9. repository commit 존재, dirty false
10. full scenario registry와 동일한 workload
11. selected scenario 전부 executed/terminal
12. Evidence Manifest 및 모든 required artifact 존재와 SHA-256 확인

WARNING은 Candidate에 남지만 현재 automatic eligibility를 직접 false로 만들지 않는다.
실제 approval은 Phase 10.2의 수동 review/gate가 수행한다.

## 4. Candidate Validator

각 check는 `PASS | WARNING | FAIL`을 반환하고 `check_id`, message, structured details를 가진다.
FAIL은 `approval_eligibility.reasons`로 축약된다. 주요 FAIL check는 environment completeness,
document integrity metadata, schema/contracts, workload terminal parity, reconciliation, clean Git,
required artifacts다.

`limitations_present`, `historical_backfill`은 WARNING이다. Known Issue matching이나 suppression은
하지 않는다.

## 5. Artifact Contract

Artifact manifest schema는 `talkback-baseline-artifact-manifest-v1`이다. Raw JSONL, XLSX,
profiler ZIP, logs와 coverage 원본을 Candidate 안에 복사하지 않는다.

각 artifact entry는 다음을 가진다.

- `artifact_type`
- `relative_reference`: `qa-run://<batch>/device/<filename>` logical URI
- `document_digest`: SHA-256 of artifact bytes
- `schema_version`
- `size`
- `created_at`: source file mtime UTC
- `availability`: `AVAILABLE | MISSING`
- `required`, `tier`: core/supporting gate

Absolute path와 raw serial이 들어간 device directory name은 canonical Candidate에 복사하지 않는다.
Required core는 run summary, EnvironmentProfile, Evidence Manifest/Reconciliation, Coverage,
Profiler archive다. Inventory, evidence JSONL, XLSX, runtime config와 logs는 supporting reference다.

Candidate reference를 source summary에 쓸 때 candidate document digest는 의도적으로 제외한다.
source summary 자체가 Candidate artifact input이므로 digest를 양방향으로 embed하면 checksum cycle이
생기기 때문이다. Reference는 schema/ID/filename/state/eligibility만 가지며 Candidate 파일의
document digest는 builder result와 Candidate repository가 관리한다.

## 6. Scenario Set Contract

Scenario Set schema는 `talkback-scenario-set-v1`이며 다음을 분리한다.

- captured `scenario_registry_hash`
- `selected_scenario_hash`: sorted selected ID set의 canonical hash
- `selected_scenario_count`
- `scenario_order_hash`: execution order의 canonical hash
- registry scenario count/version
- `run_kind`: `FULL | TARGETED`
- `is_targeted`

`FULL`은 batch/run mode가 full이고 selected ID set이 현재 registry 전체와 정확히 같을 때만
부여한다. 단순히 scenario 수가 32라는 이유만으로 full로 추정하지 않는다.

## 7. Comparison Contract

Contract version은 `talkback-comparison-input-v1`이다. 비교는 수행하지 않고 다음 normalized
입력만 생성한다.

- environment values와 complete/partial fingerprint
- repository commit/dirty
- captured runtime/scenario hashes, canonical runtime-config JSON hash, flags/contracts
- Scenario Set
- run/scenario terminal/status snapshot
- Coverage totals, scenario summaries, stable cohort-signature hash/set
- Identity aggregate
- Recovery aggregate와 result distribution
- Reconciliation integrity counts/checks
- profiler scenario runtime, named metric count/duration, counters

각 metric summary는 `source_schema_version`, `normalizer_version`, `source_artifact_id`를 보존한다.
Profiler metric duration은 기존 inclusive semantics를 명시한다.

## 8. Limitations

Builder는 다음 limitation을 구조화할 수 있다.

- `ENVIRONMENT_INCOMPLETE`
- `HISTORICAL_BACKFILL`
- `HISTORICAL_PARITY_UNAVAILABLE`
- `TARGETED_RUN`
- source `quality_issues`의 mismatch type(예: `EMPTY_VISIBLE`), scenario와 raw result

Observed limitation은 `review_status=UNREVIEWED`이며 raw FAIL/warning을 변경하지 않는다.
Known Issue 등록, exact matching 또는 suppression은 구현하지 않는다.

## 9. Compatibility and Manifest Integration

Builder는 offline side-channel이다. Traversal, Recovery, Coverage, Identity, Evidence와 Profiler
writer/semantics를 변경하지 않는다. Candidate build 성공 후 다음 source에 optional
`baseline_candidate` reference를 additive하게 연결한다.

- device `summary.json`
- batch `batch_summary.json`의 해당 device entry
- Evidence Manifest의 `manifest.baseline_candidate`

Standalone Run Summary와 Batch Summary writer는 이미 존재하는 Candidate reference를 이후
재작성에서도 보존한다. Candidate build 실패는 source run 결과를 재분류하지 않는다.

## 10. Migration and Backfill

EnvironmentProfile이 없는 historical run도 Candidate 생성은 성공한다. Builder는 legacy
Evidence Manifest의 target package/version, locale, runtime/scenario hash와 flags를 명시적
BACKFILLED source로 사용하고 나머지는 추정하지 않는다.

Legacy fingerprint는 `INCOMPLETE`, hash null이며 EnvironmentProfile document digest도 없다.
따라서 approval eligibility는 false다. 현재 연결된 장치 조회나 model-name inference는 하지
않는다.

`batch_20260715_082735` dry-run 결과:

- Candidate ID: `candidate_c2aa06decb4c456c860cff17`
- 32 scenarios, `FULL`
- Coverage 323/576, unknown 159
- Identity transactions 864
- profiler scenarios 32
- profiler recovery records 23 attempts / 12 recovered
- reconciliation PASS, orphan/duplicate/write failure/anchor abort 0
- EnvironmentFingerprint INCOMPLETE
- approval state `NOT_ELIGIBLE`
- FAIL gates: environment fingerprint/document, known contracts, required EnvironmentProfile
- limitations: historical backfill/parity, environment incomplete, Menu/Home Monitor EMPTY_VISIBLE

Architecture acceptance record의 Recovery 27 attempts는 별도 acceptance reduction이며 보존된
profiler ZIP의 recovery records는 23이다. Builder는 source semantics를 섞거나 27을 추정하지
않고 profiler-derived 23/12를 명시한다.

## 11. Known Limitations

- current Environment Collector에는 reviewed device-family/form-factor mapping이 없어 fresh
  Candidate도 fingerprint가 INCOMPLETE일 수 있다.
- runtime config canonical hash는 run-local JSON snapshot hash이며 fully expanded effective
  scenario descriptor는 아직 별도 snapshot이 아니다.
- historical TalkBack version/One UI/SDK/fold/display density는 current device에서 보충하지 않는다.
- Candidate document checksum catalog, artifact pinning과 retention enforcement는 Phase 10.2다.
- Approval actor/signature, lifecycle audit log, Known Issue registry는 구현하지 않는다.

## 12. Phase 10.2 Input

Phase 10.2는 Candidate의 canonical JSON, EnvironmentProfile, Artifact Manifest와 validation report를
입력으로 사용한다. 구현 대상은 offline revalidation, manual approve/reject/supersede lifecycle,
immutable approved revision materialization, candidate/core checksum catalog, required supporting
artifact pinning, known-issue reviewed snapshot과 append-only audit log다.
