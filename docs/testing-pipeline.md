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

## Step 6 – Overlay 확장 수집(Allowlist 기반)

- linear `move_smart` 순회는 기본 경로로 유지하고, overlay 진입은 allowlist에 등록된 entry에서만 수행합니다.
- 현재 allowlist:
  - `com.samsung.android.oneconnect:id/add_menu_button` (`Add`)
  - `com.samsung.android.oneconnect:id/more_menu_button` (`More options`)
- allowlist 외 항목은 클릭/확장을 시도하지 않습니다.
- overlay 내부는 짧은 step 상한(`OVERLAY_MAX_STEPS`)으로만 수집하고, 수집 종료 후 `press_back_and_recover_focus(...)`로 부모 컨텍스트 복귀를 수행합니다.
