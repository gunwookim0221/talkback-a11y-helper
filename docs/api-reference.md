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

## QA Frontend Crash API

Crash Issues UI는 아래 read-only backend API를 사용한다. 모든 endpoint는 `qa_frontend_runs/<run_id>/<device_id>/crashes/<crash_event_id>/` 아래 artifact만 읽는다.

### Crash Summary

```http
GET /api/runs/{run_id}/devices/{device_id}/crashes
```

응답 예:

```json
{
  "crash_count": 1,
  "crashes": [
    {
      "crash_event_id": "CRASH-0001",
      "crash_type": "APP_TERMINATED",
      "scenario": "global_nav_main",
      "timestamp": "2026-06-04T01:23:45+09:00",
      "recovery_result": "CRASH_RECOVERED",
      "repro_guide_exists": true,
      "screenshot_exists": true,
      "helper_dump_exists": true,
      "window_dump_exists": true
    }
  ]
}
```

### Crash Detail

```http
GET /api/runs/{run_id}/devices/{device_id}/crashes/{crash_event_id}
```

응답 예:

```json
{
  "crash_event_id": "CRASH-0001",
  "crash_type": "APP_TERMINATED",
  "scenario": "global_nav_main",
  "timestamp": "2026-06-04T01:23:45+09:00",
  "recovery_result": "CRASH_RECOVERED",
  "repro_guide_exists": true,
  "screenshot_exists": true,
  "helper_dump_exists": true,
  "window_dump_exists": true,
  "repro_guide": "# Manual Repro Guide\n...",
  "artifacts": {
    "screenshot": true,
    "helper_dump": true,
    "window_dump": true
  }
}
```

### Screenshot

```http
GET /api/runs/{run_id}/devices/{device_id}/crashes/{crash_event_id}/screenshot
```

성공 시 `crash_screenshot.png`를 `image/png`로 반환한다. 파일이 없으면 `404`를 반환한다.

### Artifact Download

```http
GET /api/runs/{run_id}/devices/{device_id}/crashes/{crash_event_id}/download
```

성공 시 zip 파일을 반환한다. 포함 대상은 best-effort이며 존재하는 파일만 들어간다.

- `crash_event.json`
- `crash_context.json`
- `crash_repro.md`
- `crash_screenshot.png`
- `crash_window_dump.xml`
- `crash_helper_dump.json`
- `focus_state.json`
- `logcat_excerpt.txt`
