# Testing Pipeline

[System Overview 보기](system-overview.md) | [Architecture 보기](architecture.md)

## Overview

이 문서는 헬퍼 앱의 트리 덤프/타겟 제어 기능을 활용한 접근성 자동화 검증 파이프라인을 설명합니다.

## Step 1 – TalkBack 및 헬퍼 서비스 활성화

- 테스트 단말에서 TalkBack과 `TalkBack A11y Helper` 접근성 서비스를 활성화합니다.

## Step 2 – 화면 전환 감지

- 앱 화면을 이동한 뒤 logcat에서 `A11Y_HELPER: SCREEN_CHANGED` 로그를 확인합니다.

## Step 3 – 전체 접근성 트리 덤프

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.DUMP_TREE -p com.iotpart.sqe.talkbackhelper --es reqId "dump-001"
```

- 로그에서 `DUMP_TREE_PART <reqId> ...` 조각 중 요청 `reqId`와 일치하는 항목만 순서대로 합쳐 JSON으로 파싱합니다.
- 조각 로그가 없으면 `DUMP_TREE_RESULT <reqId> [...]` 단일 로그를 fallback으로 파싱합니다.

## Step 4 – 타겟 노드 직접 제어

포커스 이동:

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.FOCUS_TARGET -p com.iotpart.sqe.talkbackhelper --es targetName "확인" --es targetType "t" --ei targetIndex 0
```

클릭 실행:

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.CLICK_TARGET -p com.iotpart.sqe.talkbackhelper --es targetName "com.example.app:id/btn_ok" --es targetType "r" --ei targetIndex 0 --ez isLongClick false
```

## Step 5 – 현재 포커스 스냅샷 확인

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.GET_FOCUS -p com.iotpart.sqe.talkbackhelper --es reqId "focus-001"
```

- 포커스 스냅샷 JSON(`reqId` 포함)으로 최종 상태를 검증합니다.

## Step 5.5 – Anchor Stabilization + Scenario Context Verify (Runner, Python)

- `script_test.py` 러너(`SCRIPT_VERSION=1.6.3`)는 탭 진입 직후 anchor를 바로 신뢰하지 않고 안정화 단계를 수행합니다.
- anchor는 `resource_id_regex`, `text_regex`, `announcement_regex`, `class_name_regex` 조합으로 판정합니다.
- `allow_resource_id_only=true`면 resourceId 단독 매칭도 허용하며, 복수 후보는 `(top, left)` 오름차순(좌상단 우선)으로 tie-break 합니다.
- 안정화 성공 조건은 `anchor matched == True` **그리고** `context_verify == True`입니다.
- `selected` 값은 성공 조건이 아니라 로그/진단용 참고값으로만 사용합니다(`selected_and_verified` 또는 `verified_without_select`).
- 기본 하단 탭은 Home/Devices/Life/Routines 공통으로 `Location QR code` anchor를 사용하고, `menu_main`만 `SmartThings` anchor를 사용합니다.
- `context_verify`는 시나리오별 optional 설정이며 미설정(또는 `type: none`) 시 기존과 동일하게 동작합니다.
  - `selected_bottom_tab`: **현재 focus payload가 아닌 dump_tree_nodes 기반** 하단 탭 선택 문맥 검증 (`selected=true` 또는 `Selected|선택됨` + Home/Devices/...). step cache에 dump가 비어 있으면 검증 시점에 lazy dump를 1회 수행해 동일 규칙으로 판정합니다.
  - `screen`: 화면 문맥 텍스트/announcement 정규식 검증
  - `plugin`: 플러그인 고유 레이블/announcement 정규식 검증
- 동일 stabilization + context 검증 로직을 overlay 복귀 재정렬 직후에도 재사용합니다.

## Step 6 – Overlay 확장 수집(Candidate + Post-click Classification)

- linear `move_smart` 순회는 기본 경로로 유지하고, overlay entry는 전역 candidate 또는 시나리오별 `overlay_policy`에서 먼저 후보로만 판정합니다.
- 현재 기본 candidate:
  - `com.samsung.android.oneconnect:id/add_menu_button` (`Add`)
  - `com.samsung.android.oneconnect:id/more_menu_button` (`More options`)
- `overlay_policy.block_candidates`는 `allow_candidates`보다 우선합니다(예: Devices 탭에서 `Add` 차단).
- candidate를 클릭한 뒤 `collect_focus_step(move=False)` probe로 결과를 분류합니다:
  - `overlay`: overlay 루틴 진입
  - `navigation`: 일반 화면 전이로 간주하고 overlay 루틴 미진입
  - `unchanged`: 클릭 실패/변화 없음으로 간주하고 overlay 루틴 미진입
- overlay 내부는 짧은 step 상한(`OVERLAY_MAX_STEPS`)으로만 수집하고, 수집 종료 후 `press_back_and_recover_focus(...)`로 부모 컨텍스트 복귀를 수행합니다.
- 복귀 직후 entry 기준 재정렬(re-align)은 `post_click classification='overlay'`일 때만 수행합니다.
- 재정렬 단계는 일반 step 수집 API 대신 lightweight probe(`get_focus` + 최소 필드 매칭) 경로를 사용해, announcement/row 저장/crop 없이 entry 판정에 필요한 정보(view_id/label/bounds)만 확인합니다.
- 재정렬 구간은 main 결과 row로 저장하지 않아, overlay 복귀 직후 `우리 집 → Map View → Add` 같은 중복 row 누적과 stop 조건 오탐을 줄입니다.
