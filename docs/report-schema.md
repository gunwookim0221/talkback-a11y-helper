# Report Schema

이 문서는 Excel raw/result row의 현재 semantics를 설명한다.

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
