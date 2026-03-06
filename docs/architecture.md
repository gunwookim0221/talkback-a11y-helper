# Architecture

## Overview

`talkback-a11y-helper`는 **Android `AccessibilityService` 기반의 헬퍼 앱**으로, TalkBack 접근성 자동화 테스트를 안정적으로 수행하기 위한 중간 제어 계층입니다. 일반적인 입력 자동화(터치/키 이벤트)만으로는 TalkBack의 실제 탐색 동작을 재현하기 어렵기 때문에, 접근성 트리를 직접 해석하고 현재 포커스를 추적하는 전용 헬퍼 앱이 필요합니다.

일반적인 ADB 자동화가 TalkBack 테스트에 적합하지 않은 이유는 다음과 같습니다.

- `adb swipe`는 화면 좌표 기반의 **단순 터치 이벤트**이며, TalkBack의 스와이프 제스처와 동일하지 않습니다.
- TalkBack swipe는 좌표 스와이프가 아니라 **접근성 포커스 이동 제스처**입니다.
- DPAD/TAB 기반 이동은 일반 포커스 체계를 따르며, TalkBack의 접근성 traversal 순서를 그대로 보장하지 않습니다.

## Architecture Diagram

아래는 헬퍼 앱 내부의 핵심 처리 흐름입니다.

```text
AccessibilityService
    -> Navigation Engine
    -> State Store
    -> Broadcast Interface
```

### Component Responsibilities

#### A11yHelperService

- Android 접근성 이벤트를 구독합니다.
- 현재 접근성 포커스 노드를 추적하고 변경 사항을 반영합니다.
- 테스트 시점의 포커스 상태를 내부 탐색 엔진과 상태 저장소에 전달합니다.

#### A11yCommandReceiver

- ADB에서 전달된 `am broadcast` 명령을 수신합니다.
- 수신한 액션(예: NEXT/PREV/GET_FOCUS)을 헬퍼 앱 내부 로직으로 전달합니다.
- 필요 시 결과를 다시 브로드캐스트 또는 로그/파일 방식으로 노출합니다.

#### A11yNavigator

- 접근성 노드 트리를 순회하여 다음/이전 포커스 후보를 계산합니다.
- TalkBack 탐색 특성과 유사한 방향의 traversal 로직을 수행합니다.
- 포커스 이동 후 결과 노드를 상태 저장소에 반영하도록 연계합니다.

#### A11yStateStore

- 현재 포커스 노드 정보를 JSON 형태로 저장합니다.
- 자동화 스크립트가 읽기 쉬운 구조로 상태를 직렬화합니다.
- 비교/검증 단계에서 재사용할 수 있도록 최신 상태를 유지합니다.

## Accessibility Events Used

헬퍼 앱은 일반적으로 다음 이벤트를 기반으로 포커스 및 화면 상태를 해석합니다.

- `TYPE_VIEW_ACCESSIBILITY_FOCUSED`
- `TYPE_VIEW_FOCUSED`
- `TYPE_WINDOW_STATE_CHANGED`
- `TYPE_ANNOUNCEMENT`

## Focus Node Data Fields

포커스된 노드에서 수집되는 대표 필드는 다음과 같습니다.

- `packageName`
- `className`
- `viewId`
- `text`
- `contentDescription`
- `bounds`
- `clickable`
- `focusable`
- `checked`
- `selected`
- `enabled`

## Output Channels

헬퍼 앱은 수집된 데이터를 아래 채널을 통해 반환할 수 있습니다.

- `logcat` 출력
- JSON 파일 저장
- broadcast 응답

## Known Limitations

- Samsung 기기에서는 TTS 로그가 인코딩/암호화되어 발화 텍스트를 직접 확인하기 어려울 수 있습니다.
- speech overlay 텍스트가 UIAutomator XML dump에 나타나지 않을 수 있습니다.
- `RecyclerView` / `WebView` / Compose UI에서는 traversal 순서가 달라질 수 있습니다.

## Future Improvements

- 공간(geometry) 기반 navigation 개선
- container-aware traversal 강화
- locale 기반 speech prediction 정밀화
- OCR 기반 검증 파이프라인 고도화
