# System Overview

[Architecture 보기](architecture.md) | [Testing Pipeline 보기](testing-pipeline.md)

## Overview

기존 사내 UI 자동화 라이브러리는 객체 탐색/클릭을 포함한 핵심 기능을 이미 제공하며, 일반 테스트 환경에서는 안정적으로 동작합니다.

이 시스템(`talkback-a11y-helper`)의 도입 목적은 기존 라이브러리 대체가 아니라, **TalkBack이 켜진 접근성 테스트 환경에서만 발생하는 객체 인식/제어 공백을 보완**하는 데 있습니다.

운영 원칙은 다음과 같습니다.

- 일반 환경: 기존(레거시) 자동화 함수 사용
- 접근성(TalkBack) 환경에서 기존 함수 실패 시: 헬퍼 앱 기반 경로로 Override/Fallback

즉 본 시스템은 전면 교체 솔루션이 아니라, 접근성 환경 전용의 보완 계층으로서 자동화 신뢰도를 높이는 것을 목표로 합니다.

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

- `com.iotpart.sqe.talkbackhelper.GET_FOCUS`
- `com.iotpart.sqe.talkbackhelper.DUMP_TREE`
- `com.iotpart.sqe.talkbackhelper.FOCUS_TARGET` (`targetName`, `targetType`, `targetIndex`, `className`, `clickable`, `focusable`, `targetText`, `targetId`)
- `com.iotpart.sqe.talkbackhelper.CLICK_TARGET` (`targetName`, `targetType`, `targetIndex`, `isLongClick`)
- `com.iotpart.sqe.talkbackhelper.CHECK_TARGET` (`targetName`, `targetType`, `targetIndex`, `className`, `clickable`, `focusable`, `targetText`, `targetId`)
- `com.iotpart.sqe.talkbackhelper.NEXT`
- `com.iotpart.sqe.talkbackhelper.PREV`
- `com.iotpart.sqe.talkbackhelper.SMART_NEXT`
- `com.iotpart.sqe.talkbackhelper.CLICK_FOCUSED`

## Stability Characteristics

- 좌표 입력 대신 접근성 노드 자체를 기준으로 제어
- 전체 화면 트리를 Flat JSON으로 수집해 외부 스크립트가 파싱하기 쉬움
- `targetName`/`targetType`/`targetIndex` 기본 매칭 + `className`/`clickable`/`focusable`/`targetText`/`targetId` AND 필터로 정밀 제어
- `NEXT/PREV`는 클릭 가능한 부모 그룹을 우선하고, 그 자식 파편 노드는 이동 경로에서 제외


## Security Guardrail

- 명령 receiver는 `android.permission.DUMP` 보호 권한으로 노출되어, ADB shell 또는 시스템 수준 권한을 가진 송신자만 브로드캐스트를 전송할 수 있습니다.
