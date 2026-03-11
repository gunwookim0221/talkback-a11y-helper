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
adb shell am broadcast -a com.example.a11yhelper.DUMP_TREE
```

- 로그의 `DUMP_TREE_RESULT [...]`를 파싱해 Python 스크립트가 원하는 대상 노드를 찾습니다.

## Step 4 – 타겟 노드 직접 제어

포커스 이동:

```bash
adb shell am broadcast -a com.example.a11yhelper.FOCUS_TARGET --es targetText "확인" --es targetClassName "android.widget.Button"
```

클릭 실행:

```bash
adb shell am broadcast -a com.example.a11yhelper.CLICK_TARGET --es targetViewId "com.example.app:id/btn_ok" --es targetClassName "android.widget.Button"
```

## Step 5 – 현재 포커스 스냅샷 확인

```bash
adb shell am broadcast -a com.example.a11yhelper.GET_FOCUS
```

- 포커스 스냅샷 JSON으로 최종 상태를 검증합니다.
