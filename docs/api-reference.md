# A11yAdbClient API Reference

이 문서는 `talkback_lib/__init__.py`의 `A11yAdbClient` public API 기준 문서다.

운영 흐름 자체는 아래 문서를 우선한다.

- [runner_flow.md](runner_flow.md)
- [testing-pipeline.md](testing-pipeline.md)
- [report-schema.md](report-schema.md)

## 핵심 public API

- `ping`
- `check_helper_status`
- `check_talkback_ready`
- `dump_tree`
- `select`
- `touch`
- `scroll`
- `move_focus`
- `move_focus_smart`
- `get_focus`
- `collect_focus_step`
- `scrollFind`
- `scrollSelect`
- `scrollTouch`
- `press_back_and_recover_focus`

## 운영상 중요 메모

- helper/client API 계약은 유지한다
- Android helper protocol은 바꾸지 않는다
- `collect_focus_step`의 row는 현재 raw/result 저장 시 actual focus semantics를
  사용한다
- representative traversal 정보는 `representative_*` 컬럼으로 분리 저장된다

세부 row semantics는 [report-schema.md](report-schema.md)를 본다.
