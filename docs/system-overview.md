# System Overview

[Architecture 보기](architecture.md) | [Testing Pipeline 보기](testing-pipeline.md)

## Overview

이 시스템은 Android 단말 내부의 헬퍼 앱과 PC/CI 자동화 환경을 연결하여, 접근성 트리 기반으로 UI를 직접 제어하고 검증 가능한 JSON 데이터를 반환합니다.

## End-to-End Flow

```text
PC Automation Script
    -> ADB broadcast
    -> Helper App
    -> Accessibility Tree Dump / Target Action
    -> Target App UI
```

## Automation Communication Flow

1. Automation Script(Python/CI)가 액션을 선택합니다.
2. `adb broadcast` 명령으로 헬퍼 앱에 제어 신호를 보냅니다.
3. 헬퍼 앱이 접근성 트리를 순회하거나 타겟 노드를 검색합니다.
4. 덤프 결과 또는 타겟 액션 수행 결과를 JSON/로그로 제공합니다.

## Supported Broadcast Actions

- `com.example.a11yhelper.GET_FOCUS`
- `com.example.a11yhelper.DUMP_TREE`
- `com.example.a11yhelper.FOCUS_TARGET` (`targetName`, `targetType`, `targetIndex`)
- `com.example.a11yhelper.CLICK_TARGET` (`targetName`, `targetType`, `targetIndex`, `isLongClick`)
- `com.example.a11yhelper.CHECK_TARGET` (`targetName`, `targetType`, `targetIndex`)
- `com.example.a11yhelper.NEXT`
- `com.example.a11yhelper.PREV`
- `com.example.a11yhelper.CLICK_FOCUSED`

## Stability Characteristics

- 좌표 입력 대신 접근성 노드 자체를 기준으로 제어
- 전체 화면 트리를 Flat JSON으로 수집해 외부 스크립트가 파싱하기 쉬움
- `targetName`/`targetType`/`targetIndex` 기반 직접 포커스/클릭/존재확인으로 정밀 제어
