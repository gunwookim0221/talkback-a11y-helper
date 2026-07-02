# Python Runner 실행 흐름 (현재 운영 기준)

이 문서는 현재 Python runner의 운영 흐름을 요약한다.

Updated for V10: 2026-07-03

## 1) scenario start

`script_test.py`는 runtime 설정을 병합한 뒤 scenario별로
`collect_tab_rows(...)`를 호출한다.

start pipeline 순서:

1. stabilization mode 계산
2. tab stabilize
3. optional pre-navigation
4. anchor stabilize
5. post-open trace
6. global-nav start gate(해당 시)
7. anchor row(step 0) 수집

## 2) pre_navigation

### Life plugin

- `xml_scroll_search_tap`
- `scrollTouch`
- `select + click_focused`

### Devices plugin

Devices plugin은 `enter_device_card_plugin`을 사용한다.

1. Devices tab 선택
2. `All devices` selected 보장
3. visible inventory 우선 수집
4. target이 visible이면 expand 생략
5. target이 없을 때만 room expand
6. helper dump 기준 `device_card` / `device_card_camera` 수집
7. stable label normalize
8. ancestor card promotion
9. safe tap
10. 필요 시 **ADB swipe 기반 bounded search**

Devices card search에서는 helper scroll을 쓰지 않는다. helper scroll이 filter를
drift시킨 사례가 있었고, ADB swipe는 `All devices` 유지가 검증됐다.

## 3) main loop

main loop는 step마다 아래 순서로 진행한다.

1. `collect_focus_step(move=True, direction="next")`
2. row 품질 annotation
3. stop 평가
4. overlay 후보 분기
5. checkpoint save 조건 확인

## 4) overlay

overlay 후보면:

1. entry click
2. `overlay / navigation / unchanged` 분류
3. `overlay`일 때만 expand
4. overlay 종료 후 recovery
5. 필요 시 realign + anchor 재안정화

## 5) 저장 semantics

현재 raw/result 기본 visible 계열은 **actual focus 기준**이다.

- `visible_label`
- `merged_announcement`
- `focus_view_id`
- `focus_bounds`

Representative traversal 정보는 `representative_*` 컬럼에 별도 저장한다.
crop 기본 source도 `actual_focus`다.

## 6) 저장 시점

- open 실패 시 즉시 저장
- anchor row 후 checkpoint 저장
- stop 또는 checkpoint 주기마다 저장
- run 종료 finally에서 final save

## 7) 운영상 최근 고정 사항

- Devices plugin 12개 representative smoke: ko/en pass
- Devices plugin long-run: 실질 pass
- Global / Life / Device long-run 완료
- row semantics는 actual focus 기준으로 변경 완료

## 8) Full Run 이후 V10 Shadow pass

QA Frontend Full Run에서 request의 `shadow_validation=true`이고 run-local
`runtime_config.json`의 V10 네 flag가 모두 true일 때만 Legacy 종료 후 Shadow
Pipeline이 실행된다.

```text
Legacy traversal/report 저장
-> Devices surface 준비
-> Runtime Inventory
-> Quick Plugin Identify
-> Policy Registry candidate
-> Shadow Compare
-> Promotion Readiness
-> shadow JSON/Markdown 저장
-> Legacy result 반환
```

- Legacy만 실제 traversal을 수행한다.
- V10 candidate는 scenario 실행이나 routing을 수행하지 않는다.
- Shadow 예외는 warning과 `shadow_error.json`/report로 격리되며 Legacy PASS를
  변경하지 않는다.
- Shadow artifact는 Excel, `normal.log`, `batch_summary.json`과 분리된다.

기존 run을 대상으로 Shadow만 다시 실행하는 개발 도구:

```powershell
python tools/run_v10_shadow_only.py --run-dir "<device-run-dir>"
```

`--dry-run`, `--overwrite-shadow`, `--output-suffix`, `--device-id`를 지원하며 legacy
artifact의 size/mtime/hash 보존을 검사한다.
