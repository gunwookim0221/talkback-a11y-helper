# TalkBack Phase 10.3D — Comparator Finalization

상태: **Implemented / Controlled-operation ready**

기준일: 2026-07-17

범위: final verdict reducer, canonical JSON/Markdown report, portable observation
bundle migration, deterministic replay, English/Korean/synthetic acceptance

## 1. Scope

Phase 10.3D는 10.3B aggregate result와 10.3C node/text/speech result를 최종 운영
결과로 reduce한다.

구현:

- `tb_runner/verdict_engine.py`
- `tb_runner/comparison_report.py`
- `tb_runner/comparison_replay.py`
- `tb_runner/observation_bundle.py`
- `tests/test_comparator_finalization.py`
- `observation_bundles/index.json`
- English/Korean portable observation bundle

기존 Approved Baseline package, Candidate, lifecycle, catalog/index와 baseline CAS는 변경하지
않았다. 자동 approval, 자동 supersede, CLI/Frontend와 실기기 Full Run은 포함하지 않는다.

## 2. Final Verdict Contract

최종 schema는 `talkback-final-comparison-result-v1`, final comparator는
`phase10.3d-comparator-v1`, 정책은 `phase10.3d-verdict-policy-v1`이다.

지원 verdict:

- `PASS`
- `PASS_WITH_LIMITATIONS`
- `REVIEW_REQUIRED`
- `FAIL`
- `INCOMPARABLE`

Reduction precedence는 다음과 같다.

1. input/schema/baseline selection/compatibility hard gate
2. new node/text/speech failure와 critical accessibility aggregate regression
3. compatibility/structure/ambiguity/data availability/limitation review
4. reviewed limitation exact binding
5. clean compatible result

상위 verdict 조건이 있으면 하위 조건은 overall을 완화하지 않는다.

### 2.1 INCOMPARABLE

- compatibility가 `INCOMPARABLE`
- Comparator input error
- 선택된 baseline 없음

비교 계약 자체가 성립하지 않는 경우 code regression `FAIL`로 오표기하지 않는다.

### 2.2 FAIL

- `NEW_ACCESSIBILITY_FAILURE`가 하나 이상
- Coverage, Identity, Traversal, Recovery 또는 Reconciliation aggregate가
  `REGRESSED`

새 `EMPTY_VISIBLE`, 새 speech loss, covered-to-missed, role loss와 신규 unlabeled
focusable node가 이 축으로 들어온다.

### 2.3 REVIEW_REQUIRED

- compatibility `REVIEW_REQUIRED` 또는 아직 review policy가 없는
  `COMPATIBLE_FAMILY`
- baseline tie
- observation이 `COMPLETE`가 아님
- unresolved review item
- ambiguous accessibility failure
- structural node/scenario/environment/coverage change
- limitation signature/scope/version drift, expiry 또는 binding ambiguity

review item 하나라도 남으면 `PASS`나 `PASS_WITH_LIMITATIONS`를 만들지 않는다.

### 2.4 PASS_WITH_LIMITATIONS

- compatible comparison
- 신규 failure, regression, review item 없음
- candidate raw failure가 모두 valid reviewed limitation 또는 derivative duplicate에 exact
  binding

Raw `FAIL`은 유지되고 자동 PASS 변환이나 suppression은 없다.

### 2.5 PASS

- compatible comparison
- 필수 comparison dimension available
- 신규/기존 raw accessibility failure와 active limitation 없음
- unresolved review 없음

Known limitation resolution은 improvement다. 다른 review 요인이 없다면 `PASS`가 가능하다.

### 2.6 Profiler

Profiler status는 verdict에 함께 기록하지만 accessibility verdict를 `FAIL`로 만들지 않는다.
`performance_affects_accessibility_verdict=false` 계약을 유지한다.

어떤 verdict도 approval을 실행하지 않는다. `automatic_approval=false`가 항상 결과에 남는다.

## 3. Portable Observation Bundle

### 3.1 문제

기존 Approved Baseline package는 aggregate에 충분하지만 optional Evidence/XLSX가 package에
pin되지 않았다. `.baseline-artifacts`와 `qa_frontend_runs`도 `.gitignore` 대상이므로 CAS와
local source만으로는 Git clone portability를 보장할 수 없다.

### 3.2 결정

기존 package를 수정하지 않고 repository root에 additive tracked sidecar를 둔다.

```text
observation_bundles/
  index.json
  baseline_8f00aed49e61a07b_r0001.observations.json
  baseline_1f697e9b60c655df_r0001.observations.json
```

Bundle schema는 `talkback-portable-observation-bundle-v1`, index schema는
`talkback-portable-observation-bundle-index-v1`이다.

각 index entry:

- baseline ID
- relative bundle path
- bundle/document SHA-256
- canonical observation identity digest
- observation count
- locale/package

각 bundle:

- bundle ID와 canonical source digest
- baseline ID
- observation schema/identity digest
- locale/package/app version
- canonical observations
- logical artifact/digest provenance

절대 source path는 저장하지 않는다. Loader는 canonical JSON bytes, schema, index digest,
document digest, bundle identity, package/locale를 모두 검증한다. Corrupt tracked bundle이
있으면 local source로 조용히 fallback하지 않고 `CORRUPT`로 차단한다.

### 3.3 Migration

`migrate_baseline_observation_bundles()`가 기존 package를 read-only adaptation하고 보존 source
artifact의 digest를 검증한 뒤 sidecar를 생성한다. Existing destination과 bytes가 같으면
idempotent하고, 같은 이름에 다른 bytes가 있으면 immutable conflict로 실패한다.

현재 migration 결과:

| Baseline | Locale | Observations | Bundle bytes |
|---|---|---:|---:|
| `baseline_8f00aed49e61a07b_r0001` | en-US | 947 | 2,763,693 |
| `baseline_1f697e9b60c655df_r0001` | ko-KR | 879 | 2,601,696 |

기존 baseline package/core checksum/lifecycle에는 변화가 없다.

### 3.4 CAS 검토

CAS는 digest validation과 large artifact distribution에 적합하지만 현재
`.baseline-artifacts`는 Git에 포함되지 않는다. 따라서 CAS-only migration은 “다른 PC에서 Git
clone만”이라는 요구를 충족하지 못한다.

현재 결정은 tracked compact canonical bundle을 portability authority로 사용하고 CAS를 선택적
mirror/cache로 두는 것이다. 장기적으로 remote content-addressed distribution이 생기면 index의
document digest를 그대로 사용할 수 있다.

## 4. Observation Loading Policy

Comparator는 다음 순서로 observation을 찾는다.

1. 검증된 tracked portable bundle
2. 기존 digest-pinned/local logical artifact adapter
3. Coverage/Inventory/limitation fallback
4. `DATA_UNAVAILABLE`

Portable bundle은 baseline과 explicit self-replay candidate에 사용된다. Test가 optional
observation을 명시적으로 unavailable로 선언한 candidate에는 sidecar를 강제로 주입하지 않는다.
양쪽 availability가 비대칭이면 기존 10.3C 정책대로 full node compare를 금지한다.

## 5. Comparison Identity

Phase별 ID를 보존한다.

- `aggregate_comparison_id`: Phase 10.3B
- `observation_comparison_id`: Phase 10.3C
- `comparison_id`: Phase 10.3D final

Final ID source:

- observation comparison ID
- final comparator/schema version
- verdict policy version
- verdict semantic digest

Wall-clock generation time, report path와 local resolver path는 ID source가 아니다. Policy나
Comparator semantics가 바뀌면 새 final ID가 생성되고 과거 ID를 조용히 재해석하지 않는다.

## 6. Replay

`replay_selected_inputs()`는 명시된 Baseline/Candidate를 비교하고,
`run_comparison_replay()`는 repository predecessor selection을 포함한다.

Limitation expiry처럼 evaluation time이 semantic 결과에 영향을 주는 경우 Candidate
`created_at`을 사용한다. Self replay는 baseline `approved_at`을 사용한다. 둘 다 없을 때만
고정 replay epoch를 사용한다. 따라서 같은 canonical inputs에서 wall-clock `now()`가 verdict를
바꾸지 않는다.

Replay 반환:

- finalized result
- canonical JSON
- deterministic Markdown

Canonical report payload는 비semantic `generated_at`을 제외한다. 동일 Candidate/Baseline,
Comparator/정책/bundle이면 comparison ID, verdict, canonical JSON bytes와 Markdown bytes가
같다.

## 7. Canonical JSON Report

JSON report schema는 `talkback-comparison-report-v1`이다. 전체 finalized comparison을
canonical JSON으로 포함하며 key ordering, NFC와 newline 정책은 기존 `canonical_json` 계약을
사용한다.

Output writer는 다음 layout을 지원한다.

```text
comparisons/
  com.samsung.android.oneconnect/
    comparison_<24-hex>/
      comparison.json
      report.md
```

같은 ID/같은 bytes 재작성은 idempotent하다. 같은 ID에 다른 bytes가 있으면 immutable conflict로
실패한다. Writer는 Candidate/Baseline repository를 변경하지 않는다.

## 8. Markdown Report

Markdown은 고정 section 순서를 사용한다.

1. Environment
2. Version
3. Compatibility
4. Coverage
5. Identity
6. Traversal
7. Recovery
8. Profiler
9. Known Limitation
10. New Failure
11. Resolved Failure
12. Observation Availability
13. Review Items
14. Verdict Reasons
15. Recommendation

Markdown은 node raw dump가 아니라 사람이 검토할 수 있는 status/count/reason 중심이다.
Automatic approval disabled와 raw limitation retention을 명시한다.

## 9. Acceptance

실기기 없이 Approved package, tracked bundle과 synthetic mutation으로 검증한다.

| Case | Expected |
|---|---|
| English self compare | `PASS_WITH_LIMITATIONS`, 947 unchanged |
| Korean self compare | `PASS_WITH_LIMITATIONS`, 879 unchanged |
| Synthetic app upgrade | `COMPATIBLE_PREDECESSOR`, limitation version scope drift로 `REVIEW_REQUIRED` |
| Synthetic UI addition | `REVIEW_REQUIRED` |
| Known limitation unchanged | `PASS_WITH_LIMITATIONS` |
| Known limitation resolved | `PASS` |
| New EMPTY_VISIBLE | `FAIL` |
| Observation DATA_UNAVAILABLE | `REVIEW_REQUIRED` |
| Compatibility review | `REVIEW_REQUIRED` |
| Incomparable input | `INCOMPARABLE` |

추가 acceptance:

- profiler regression은 accessibility verdict와 분리
- report required sections
- replay byte determinism
- immutable/idempotent writer
- source run/CAS 없는 portable bundle replay
- index/bundle checksum validation
- corrupt bundle rejection
- final comparison ID determinism

## 10. Read-only and Safety

- Existing Baseline/Candidate/package/lifecycle/catalog/index/CAS 변경 없음
- Bundle migration은 package 밖 additive output만 생성
- Comparator/replay는 input과 repository read-only
- Report output은 별도 destination에만 명시적으로 생성
- 실기기/ADB 사용 없음
- 자동 approval/supersede 없음
- Commit/Push 없음

## 11. Operational Workflow

Controlled workflow:

```text
Full Validation
  -> Candidate automatic generation (when terminal Full Validation conditions pass)
  -> Comparator replay
  -> Canonical JSON + Markdown report
  -> Human review
  -> Explicit repository approve
  -> Baseline v2
  -> Additive portable observation bundle migration
```

Comparator와 report는 approval 근거를 만들지만 approval을 호출하지 않는다. Approval 뒤
portable bundle migration은 현재 explicit step이다.

## 12. Remaining Limitations

1. Future Candidate의 observation bundle은 Candidate build/approval 과정에 아직 자동으로
   첨부되지 않는다. Comparator 실행 PC에는 Candidate source artifacts가 필요하다.
2. 현재 Git clone portability는 migrated English/Korean Approved Baseline replay에 대해
   보장된다. 아직 migration되지 않은 미래 baseline/candidate에는 자동 적용되지 않는다.
3. Portable bundles 총 크기는 약 5.3 MB이며 raw UI/TalkBack observation을 포함한다. 장기
   privacy/redaction/retention budget의 owner 결정이 필요하다.
4. One Connect `1.8` release-train policy와 cross-device compatible-family registry는 여전히
   project policy다.
5. Matching threshold, performance threshold와 scenario rename alias corpus는 추가 calibration이
   필요하다.
6. CLI/Frontend/remote artifact distribution은 없다.
7. Comparator는 controlled production use를 위한 engine/library 수준이며 unattended service
   운영, automatic approval system은 아니다.

## 13. Final Questions

### 13.1 새 One Connect workflow가 완성되었는가?

**Controlled manual workflow 기준으로는 완성되었다.** Full Validation과 Candidate가 생성되면
Comparator, deterministic JSON/Markdown report, human review와 기존 explicit approval API를
거쳐 Baseline v2를 만들 수 있다.

다만 future Candidate bundle attachment와 post-approval portable migration은 explicit step이며
one-command 자동 orchestration은 아니다. 자동 approval은 의도적으로 금지되어 있다.

### 13.2 다른 PC에서 Git Clone만으로 동일 결과를 재현할 수 있는가?

**현재 migrated English/Korean Approved Baseline self/replay는 가능하다.** Tracked bundle만
복사한 source-run/CAS 없는 acceptance에서 동일 result를 검증한다.

**임의의 미래 Candidate까지 일반적으로 가능한 것은 아니다.** Candidate observation bundle 또는
source artifacts가 함께 전달되어야 한다. 새 baseline도 승인 후 sidecar migration이 필요하다.

### 13.3 Comparator가 Production Ready인가?

**Controlled/manual comparator engine으로는 Production Ready with limitations다.**
Deterministic verdict/report/replay, integrity validation, fail-safe availability와 immutable output을
갖췄다.

Unattended end-to-end service 관점에서는 future Candidate bundle 자동화, privacy policy,
CLI/Frontend와 remote artifact distribution이 남아 있어 아직 완전한 Production Ready가 아니다.
