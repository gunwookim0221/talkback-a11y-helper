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

따라서 downstream이 representative 기준 visible을 기대한다면 이제
`representative_*`를 읽어야 한다.

## Related design documents

- [semantic-value-shadow-audit.md](design/semantic-value-shadow-audit.md)
- [audit-v7-focusable-coverage-design.md](design/audit-v7-focusable-coverage-design.md)
