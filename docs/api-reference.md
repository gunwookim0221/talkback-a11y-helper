# A11yAdbClient API Reference

이 문서는 `talkback_lib/__init__.py`의 `A11yAdbClient` public API 기준 문서다.

Updated for Canonical Identity Shadow Phase 8: 2026-07-12

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

## QA Frontend V10 Shadow API

### Run request

Single/Batch request는 optional `shadow_validation` boolean을 받는다.

```http
POST /api/run/start
POST /api/batch/start
```

```json
{
  "mode": "full",
  "shadow_validation": true
}
```

- 기본값은 `false`다.
- `mode=full`에서만 true가 유효하다.
- Full + request true인 경우에만 run-local runtime config의 V10 네 flag가
  활성화된다.
- source `config/runtime_config.json`은 변경하지 않는다.

### Recent Batch response

```http
GET /api/batch/recent
```

Shadow artifact가 있는 device에는 optional `shadow_validation` field가 포함된다.

```json
{
  "shadow_validation": {
    "available": true,
    "status": "completed",
    "inventory_count": 15,
    "identified_count": 6,
    "identify_unknown_count": 9,
    "match_count": 6,
    "unknown_count": 9,
    "ambiguous_count": 0,
    "mismatch_count": 0,
    "failed_count": 0,
    "promotion_eligible_count": 6,
    "legacy_preserved": true,
    "promotion_readiness": {
      "overall_status": "HOLD",
      "status_counts": {
        "READY": 0,
        "HOLD": 6,
        "BLOCKED": 0,
        "INSUFFICIENT_DATA": 6,
        "UNKNOWN_ONLY": 1
      },
      "controlled_routing_enabled": false,
      "families": []
    },
    "artifacts": {
      "report": "qa_frontend_runs/.../shadow/shadow_report.md",
      "compare": "qa_frontend_runs/.../shadow/shadow_compare.json",
      "readiness_report": "qa_frontend_runs/.../shadow/promotion_readiness.md",
      "readiness_json": "qa_frontend_runs/.../shadow/promotion_readiness.json",
      "folder_available": true
    }
  }
}
```

Shadow artifact가 없는 run에서는 `shadow_validation`이 `null`이거나 UI에서
표시되지 않는다.

### Shadow artifact access

```http
GET /api/batch/file?path=<relative-artifact-path>
POST /api/runs/{run_id}/devices/{device_id}/shadow/open-folder
```

첫 endpoint는 `qa_frontend_runs/` 내부의 Shadow JSON/Markdown을 반환한다. 두 번째
endpoint는 검증된 device run의 `shadow/` directory를 로컬 파일 탐색기로 연다.
Promotion Readiness 전용 mutation endpoint나 routing 활성화 endpoint는 없다.

## QA Frontend Canonical Identity Shadow API

### Run-scoped feature flags

Single/Batch start request는 다음 optional boolean을 받는다.

```json
{
  "evidence_ledger": true,
  "identity_shadow_v2": true
}
```

둘 다 기본값은 `false`다. `identity_shadow_v2=true`이면 backend가 해당 run에만
Evidence Ledger도 활성화한다. Uvicorn process의 global state나 source runtime config는
변경하지 않는다.

### Read-only Identity report

```http
GET /api/runs/{run_id}/devices/{device_id}/identity-shadow
```

응답 schema 이름은 `identity-shadow-report-v1`을 유지하며 Phase 8 field는 additive다.

```json
{
  "available": true,
  "schema": "identity-shadow-report-v1",
  "availability": "V2_AVAILABLE",
  "legacy_available": true,
  "v2_available": true,
  "summary": {
    "transactions": 20,
    "v2_verdicts": {
      "MOVE_CONFIRMED": 11,
      "STATIC_FOCUS": 9
    },
    "v2_verdict_percentages": {
      "MOVE_CONFIRMED": 55.0,
      "STATIC_FOCUS": 45.0,
      "MOVE_TO_OTHER_NODE": 0.0,
      "SNAP_BACK": 0.0,
      "INDETERMINATE": 0.0
    },
    "confidence_counts": {"HIGH_CONFIDENCE": 20},
    "confidence_percentages": {"HIGH_CONFIDENCE": 100.0},
    "relation_counts": {"STRONG_PHYSICAL_LINK": 20},
    "relation_percentages": {"STRONG_PHYSICAL_LINK": 100.0}
  },
  "transactions": []
}
```

Percentage denominator는 V2 verdict가 기록된 transaction 수다. Legacy-only transaction은
`V2_PARTIAL` 상태에는 포함되지만 V2 percentage denominator에는 포함되지 않는다.
Endpoint는 ledger를 읽어 projection만 만들며 ledger, traversal, summary, coverage,
audit, XLSX를 수정하지 않는다.

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

## QA Frontend Plugin Onboarding API

Plugin Onboarding Wizard MVP는 신규 Life / Device plugin을 발견하고 draft scenario를
적용 전후로 검토하기 위한 local backend API를 제공한다.

### Plugin Discovery

```http
POST /api/plugin-discovery/discover
```

현재 SmartThings 화면에서 visible Life / Device plugin 후보를 수집한다.

Request:

```json
{
  "targets": ["life", "device"],
  "include_xml": true,
  "current_view_only": true
}
```

### Plugin Probe

```http
POST /api/plugin-probe/start
```

Discovery card를 입력으로 받아 plugin 진입을 짧게 시도하고 draft seed를 수집한다.

### Draft Generate

```http
POST /api/plugin-draft/generate
```

card와 probe 결과를 기반으로 scenario/runtime config draft를 생성한다. 이 단계는
파일을 수정하지 않는다.

### Draft Review

```http
POST /api/plugin-draft/review
```

scenario id 중복, runtime config key 중복, manual review 필요 여부와 diff preview를
검사한다. 이 단계도 파일을 수정하지 않는다.

### Apply Draft

```http
POST /api/plugin-draft/apply
```

review가 허용한 draft를 `tb_runner/scenario_config.py`와
`config/runtime_config.json`에 적용한다. apply 전 backup은
`output/plugin_draft_backups/<timestamp>/`에 생성된다.

### Smoke Start

```http
POST /api/plugin-draft/smoke
```

apply된 scenario 하나를 smoke mode로 실행한다.

제약:

- `scenario_id` 1개
- `max_steps <= 10`
- `mode=smoke`
- runtime config 원본은 override 방식으로 유지

### Smoke Status

```http
GET /api/plugin-draft/smoke/{run_id}?scenario_id=...
```

run 상태, log/xlsx artifact, smoke summary를 조회한다.

### Onboarding Session Create

```http
POST /api/plugin-onboarding/session
```

card 기준 onboarding session을 생성한다. session 파일은
`output/plugin_onboarding_sessions/<session_id>.json`에 저장된다.

### Onboarding Session Step Save

```http
POST /api/plugin-onboarding/session/{session_id}/step
```

지원 step:

- `discovery`
- `probe`
- `draft`
- `review`
- `apply`
- `smoke`

### Onboarding Session Get/List

```http
GET /api/plugin-onboarding/session/{session_id}
GET /api/plugin-onboarding/sessions
```

단일 session 또는 최근 updated_at 기준 session 목록을 조회한다.

### Session Restore

```http
GET /api/plugin-onboarding/session/{session_id}/restore
```

저장된 step payload에서 wizard state를 best-effort로 복원하고 next action
recommendation을 반환한다.

Response shape:

```json
{
  "ok": true,
  "schema_version": "plugin-onboarding-restore-v1",
  "session": {},
  "restored_state": {
    "selected_card": {},
    "probe_result": {},
    "draft_result": {},
    "review_result": {},
    "apply_result": {},
    "smoke_start_result": {},
    "smoke_status_result": {}
  },
  "recommendation": {
    "next_action": "ready_for_manual_validation",
    "severity": "success",
    "reasons": [],
    "allowed_actions": [],
    "blocked_actions": []
  }
}
```

### Rollback Preview

```http
POST /api/plugin-onboarding/session/{session_id}/rollback/preview
```

apply backup과 현재 파일을 비교해 실제 rollback 전에 복원 가능성과 영향 범위를
반환한다. 실제 파일 복원은 하지 않는다.

Response shape:

```json
{
  "ok": true,
  "schema_version": "plugin-rollback-preview-v1",
  "rollback_status": "preview_ready",
  "can_rollback": true,
  "target_files": [
    "tb_runner/scenario_config.py",
    "config/runtime_config.json"
  ],
  "backup": {
    "found": true,
    "paths": []
  },
  "preview": {
    "scenario_entry_will_be_removed": true,
    "runtime_config_entry_will_be_removed": true,
    "diff_preview": "..."
  },
  "diagnostics": {
    "warnings": [],
    "errors": []
  }
}
```

## Plugin Onboarding API limitations

- Discovery/probe는 현재 visible card 중심이다.
- bounded scroll discovery와 자동 tab 이동은 아직 없다.
- Smoke result는 수동 refresh 방식이다.
- Apply는 backup을 생성하지만 rollback 실행은 아직 preview only다.
- `serial`은 smoke request schema에 있지만 현재 runner 경로에 직접 연결되지 않는다.
