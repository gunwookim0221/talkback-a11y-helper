# Current Client Architecture (현재 운영 기준)

이 문서는 현재 `talkback_lib`와 runner integration의 운영 기준을 정리한다.

## 1) 현재 `talkback_lib` 구조

- `talkback_lib/__init__.py`
  - `A11yAdbClient` 공개 API 제공
- `adb_executor.py`
- `logcat_reader.py`
- `action_result_parser.py`
- `helper_bridge.py`
- `focus_service.py`
- `step_row_builder.py`
- `step_collection_service.py`
- `focus_trace_builder.py`

## 2) `A11yAdbClient`의 역할

`A11yAdbClient`는 façade다.

- 외부 public API 유지
- 내부 서비스 orchestration
- helper action / focus 수집 / step 수집 조합

## 3) runner와의 경계

- `collect_focus_step`는 step row 입력을 제공
- runner는 그 row를 사용해:
  - open / anchor
  - main traversal
  - overlay
  - stop
  - persist
  를 수행한다

## 4) row dict 계약

### 기본 사용자-facing 컬럼

- `visible_label`
- `merged_announcement`
- `focus_view_id`
- `focus_bounds`

위 컬럼은 **actual TalkBack focus 기준**이다.

### representative 보존 컬럼

- `representative_visible`
- `representative_speech`
- `representative_resource_id`
- `representative_bounds`
- `representative_row_source`

위 컬럼은 traversal representative를 별도로 보존한다.

### actual focus snapshot 컬럼

- `actual_focus_visible`
- `actual_focus_speech`
- `actual_focus_resource_id`
- `actual_focus_bounds`
- `actual_focus_payload_source`

상세 semantics는 [report-schema.md](report-schema.md)를 우선한다.

## 5) 절대 보존 계약

- helper protocol unchanged
- `get_focus` fallback semantics 유지
- traversal / scoring / representative selection unchanged
- overlay realign 후 main loop 복귀 semantics 유지
- 운영 로그 키 유지

## 6) 문서 사용 원칙

- 이 문서는 현재 운영 기준이다
- historical 설계 문서는 [archive/](archive/) 아래에 보존한다
- 운영 판단은 아래 문서를 우선한다
  - [system-overview.md](system-overview.md)
  - [runner_flow.md](runner_flow.md)
  - [testing-pipeline.md](testing-pipeline.md)
  - [device-plugin-guide.md](device-plugin-guide.md)
  - [report-schema.md](report-schema.md)
