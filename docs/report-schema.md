# Report Schema

이 문서는 Excel raw/result row의 현재 semantics를 설명한다.

Updated for V10: 2026-07-03

## 기본 사용자-facing 컬럼

아래 컬럼은 **actual TalkBack focus 기준**이다.

- `visible_label`
- `merged_announcement`
- `focus_view_id`
- `focus_bounds`

즉 crop과 사용자가 실제로 들은 focus가 기본 visible 계열과 일치해야 한다.

## Representative 컬럼

아래 컬럼은 traversal representative를 보존한다.

- `representative_visible`
- `representative_speech`
- `representative_resource_id`
- `representative_bounds`
- `representative_row_source`

Traversal / scoring / representative selection은 유지되고, 저장 semantics만
분리된다.

## Actual focus metadata

- `actual_focus_visible`
- `actual_focus_speech`
- `actual_focus_resource_id`
- `actual_focus_bounds`
- `actual_focus_payload_source`

이 컬럼은 persistence 이전 actual focus snapshot을 별도로 남긴다.

## Source markers

- `row_source`
- `crop_source`

대표 의미:

- `row_source=actual_focus`
- `crop_source=actual_focus`
- `representative_row_source=representative`

V8 이후 result sheet에는 probe row source가 추가될 수 있다.

- `row_source=COVERAGE_PROBE_SHADOW`
- `row_source=COVERAGE_PROBE_PROMOTED`

의미:

- `COVERAGE_PROBE_SHADOW`
  Runtime Probe validation evidence row. `final_result=SHADOW`.
- `COVERAGE_PROBE_PROMOTED`
  Promotion policy와 dedup을 통과해 production report에 append된 row. `final_result=PASS`.

기존 traversal row semantics는 그대로 유지된다.

## V8 Probe Metadata

현재 result sheet는 V8 probe 관련 메타데이터를 추가로 가질 수 있다.

- `probe_validation_status`
- `probe_success_source`
- `promotion_status`
- `promotion_reason`
- `promotion_applied`
- `promotion_dedup_status`
- `promotion_dedup_reason`
- `probe_validation_confidence`
- `probe_target_strategy`
- `probe_intent`
- `probe_captured_speech`
- `probe_captured_visible_text`

이 필드는 shadow/promoted row를 설명하기 위한 reporting metadata다.
기존 traversal scoring이나 `PASS` / `WARN` / `FAIL` 정의를 재정의하지 않는다.

## V10 Shadow artifact

V10 Shadow 결과는 Excel row schema에 추가하지 않고 device run의 `shadow/`
directory에 분리 저장한다.

| Artifact | 내용 |
| --- | --- |
| `shadow_inventory.json` | inventory metadata와 runtime Device Card items |
| `shadow_identify.json` | plugin family candidate, confidence, evidence, restore diagnostics |
| `shadow_routing.json` | Policy Registry가 만든 scenario candidate와 eligibility |
| `shadow_compare.json` | Legacy/V10 comparison records와 aggregate metrics |
| `shadow_report.md` | 사람이 읽는 Shadow Validation report |
| `promotion_readiness.json` | family별 readiness와 gate 결과 |
| `promotion_readiness.md` | 사람이 읽는 Promotion Readiness report |
| `shadow_error.json` | pipeline 실패 stage/error와 Legacy 보존 여부 |

`shadow_compare.json` comparison result:

- `MATCH`
- `MISMATCH`
- `UNKNOWN`
- `AMBIGUOUS`
- `FAILED`

주요 metrics:

- match/mismatch/unknown/ambiguous/failed count
- match rate
- shadow coverage
- fallback rate
- promotion eligible count

`promotion_readiness.json` 상태:

- `READY`
- `HOLD`
- `BLOCKED`
- `INSUFFICIENT_DATA`
- `UNKNOWN_ONLY`

Readiness는 `mode=evaluation_only`,
`controlled_routing_enabled=false`를 기록한다. MISMATCH, FAILED 또는 Legacy 결과
미보존은 fail-closed blocker다. 작은 표본의 MATCH는 `ready_candidate=true`일 수
있지만 최종 상태는 HOLD다.

모든 V10 Shadow artifact는 Legacy XLSX, `normal.log`, batch result와 독립적이며
production traversal 결과를 수정하지 않는다.

## 예시

### Water leak

- `visible_label = 누수, 우리 집 - 거실`
- `representative_visible = Water sensor History`
- `crop_source = actual_focus`

### Camera

- `visible_label = More options`
- `representative_visible = Increase`
- `crop_source = actual_focus`

## Compatibility note

- 컬럼 삭제 없음
- 컬럼 rename 없음
- 하지만 `visible_label` 의미는 representative에서 **actual focus**로 바뀌었다
- probe 관련 행은 append-only 방식으로 추가된다

따라서 downstream이 representative 기준 visible을 기대한다면 이제
`representative_*`를 읽어야 한다.

## Related design documents

- [semantic-value-shadow-audit.md](design/semantic-value-shadow-audit.md)
- [audit-v7-focusable-coverage-design.md](design/audit-v7-focusable-coverage-design.md)
- [V10 Phase Closure](design/v10/v10-phase-closure.md)
