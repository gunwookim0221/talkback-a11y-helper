# V10 Shadow Corpus / History Design

| Metadata | Value |
| --- | --- |
| Status | Implemented |
| Phase | V10 Follow-up |
| Last Updated | 2026-07-06 |
| Related | [V10 Shadow Validation](v10-shadow-validation-design.md), [V10 Phase Closure](v10-phase-closure.md) |

## 1. 목적

V10 Shadow Corpus는 개별 device run의 shadow 결과를 작고 안정적인 history entry로
누적한다. 목적은 V11 Controlled Routing Pilot 후보를 고를 때 단일 run의 MATCH 수가
아니라 family별 장기 결과와 단말·모델·locale 다양성을 함께 볼 수 있게 하는 것이다.

Corpus는 평가 데이터 저장소다. Controlled Routing을 실행하거나 기존 Promotion
Readiness 결과를 다시 판정하지 않는다.

## 2. 왜 필요한가

기존 `device-run-dir/shadow/` artifact는 한 run의 상세 진단에는 충분하지만, 다음
질문에는 답하기 어렵다.

- 같은 family가 여러 run에서도 일관되게 MATCH하는가
- 한 계정과 한 단말의 반복 결과에 편향되지 않았는가
- locale, device model, app version이 달라져도 결과가 유지되는가
- 과거 MISMATCH, FAILED, UNKNOWN evidence가 최근 MATCH에 가려지지 않았는가

Corpus는 raw artifact를 복제하지 않고 비교와 readiness에 필요한 요약 필드와 원본
artifact 경로만 보존한다.

## 3. V10과 V11 사이에서의 역할

```text
V10 run-local shadow artifacts
-> Corpus entry
-> Family / Readiness summaries
-> V11 pilot review evidence
```

`candidate_for_v11_pilot`은 검토용 신호이며 routing 승인이 아니다. V11은 별도의
allowlist, rollback, kill switch와 운영 승인을 가져야 한다.

## 4. 저장 위치

기본 위치는 `artifacts/v10/corpus/`다.

```text
artifacts/v10/corpus/
  index.json
  entries/
    <corpus_entry_id>.json
  summaries/
    family_summary.json
    readiness_summary.json
```

`entries/`에는 JSON 요약만 저장한다. XLSX, screenshot, XML dump, full log,
Markdown report를 복사하지 않는다. `source_artifacts`는 원본 파일 reference만
기록한다.

## 5. Entry Schema

Schema version은 `v10-shadow-corpus-entry-v1`이다.

| 필드 | 의미 |
| --- | --- |
| `corpus_entry_id` | source run, shadow run, 생성 시각으로 만든 deterministic ID |
| `created_at` | shadow comparison 생성 시각 |
| `source_run_dir`, `source_shadow_dir` | 원본 run과 shadow 위치 |
| `source_artifacts` | 원본 shadow JSON/Markdown reference |
| `batch_id` | source batch/run 식별자 |
| `device_serial`, `device_model` | 실행 단말 metadata |
| `app_version`, `android_version`, `locale` | source metadata에 있을 때 기록 |
| `shadow_run_id` | V10 shadow pipeline run ID |
| `inventory_count` | inventory item 수 |
| `identify_count` | identify 시도 수 |
| `identified_count`, `identify_unknown_count` | identify decision 누계 |
| `match_count`, `unknown_count` | comparison 누계 |
| `mismatch_count`, `failed_count`, `ambiguous_count` | 보존해야 할 부정/불확실 evidence |
| `promotion_eligible_count` | source compare 결과의 값 |
| `overall_readiness` | source Promotion Readiness의 overall status |
| `family_results` | runtime card별 compact comparison 결과 |

`family_results[]`는 `family`, `legacy_scenario`, `display_label`,
`stable_label`, `comparison_result`, `confidence`, `readiness`, `reason`,
`source_runtime_card_id`를 포함한다. readiness와 threshold를 새로 계산하지 않고
source artifact 값을 기록한다.

## 6. Summary Schema

`index.json`은 entry ID, 생성 시각, source run, device metadata와 overall readiness를
가진 entry catalog다. 동일 deterministic ID는 append하지 않고 update한다.

`family_summary.json`의 family별 주요 필드는 다음과 같다.

- `total_runs`, `total_observations`
- `match_count`, `unknown_count`, `ambiguous_count`, `mismatch_count`,
  `failed_count`
- `readiness_distribution`
- `unique_device_labels`, `unique_device_models`
- `unique_device_serial_count`, `unique_locales`, `unique_app_versions`
- `last_seen_at`
- `candidate_for_v11_pilot`

`readiness_summary.json`은 run별 `overall_readiness_distribution`, family별 readiness
분포와 V11 검토 후보 목록을 제공한다. 항상 `controlled_routing_enabled=false`다.

## 7. 다양성 지표

동일 계정/단말 반복만으로 READY처럼 보이는 것을 막기 위해 MATCH 수와 다양성을
분리한다.

- run 다양성: 서로 다른 corpus entry 수
- 단말 다양성: unique serial 수
- 모델 다양성: unique device model 수
- locale 다양성: unique locale 수
- version 다양성: unique app version 수
- label 다양성: family에서 관찰된 stable/display label 집합

현재 source artifact에는 account identifier가 없으므로 account 다양성은 계산하지
않는다. 민감한 account identifier를 추론하거나 새로 수집하지 않는다.

`candidate_for_v11_pilot`은 MATCH가 존재하고 UNKNOWN/AMBIGUOUS/MISMATCH/FAILED가
없으며, 최소 2개 run·serial·model·locale에서 관측되고 source readiness에 READY가
있을 때만 true다. 이는 보수적인 corpus review gate이며 Promotion threshold 변경이
아니다. metadata가 비어 있으면 후보가 되지 않는다.

## 8. Promotion Readiness와의 관계

Corpus는 `promotion_readiness.json`의 overall/family status를 그대로 저장한다.
기존 최소 observation, confidence, promotion eligibility threshold를 변경하거나
재평가하지 않는다.

MISMATCH와 FAILED는 모든 entry에서 누적 보존된다. UNKNOWN은 family evidence gap으로
남는다. 이후 MATCH가 증가해도 과거 부정 evidence가 summary에서 제거되지 않는다.

## 9. Shadow-only Runner와의 관계

독립 CLI:

```powershell
python tools/update_v10_shadow_corpus.py --run-dir "<device-run-dir>"
python tools/update_v10_shadow_corpus.py --run-dir "<device-run-dir>" --dry-run
python tools/update_v10_shadow_corpus.py --corpus-dir "<path>" --rebuild
```

Shadow-only 실행과 함께 사용할 수 있다.

```powershell
python tools/run_v10_shadow_only.py --run-dir "<device-run-dir>" `
  --output-suffix test --update-corpus
```

`--update-corpus` 기본값은 OFF다. 옵션을 켠 경우에만 completed shadow output을
corpus에 추가하며, suffix output도 해당 `shadow_<suffix>`를 source로 기록한다.

## 10. 제한사항

- 과거 source artifact가 삭제되면 reference는 더 이상 열리지 않는다.
- metadata가 source summary/runtime config에 없으면 빈 문자열로 남는다.
- corpus는 raw evidence archive가 아니므로 상세 조사는 source artifact가 필요하다.
- 동시 다중 writer용 locking은 제공하지 않는다. 동일 corpus에는 update process를
  직렬로 실행해야 한다.
- schema migration과 retention policy는 아직 없다.
- Frontend API/UI와 Controlled Routing은 이번 범위에 포함하지 않는다.

## 11. V11에서 활용 방법

V11 pilot 준비 시 family summary에서 부정 evidence, UNKNOWN gap, confidence와
다양성을 함께 검토한다. 후보 flag만으로 route를 켜지 않고 source artifact 표본
검토, account cohort 보완, allowlist 승인, rollback/kill-switch 검증을 추가로
수행한다.

Corpus는 pilot 전후 drift 비교에도 사용할 수 있다. app/Android/locale cohort별
UNKNOWN 또는 MISMATCH 증가를 감지하면 해당 family를 pilot에서 제외하는 근거가 된다.
